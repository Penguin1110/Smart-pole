"""IDW with auto-selected power(Phase 3a)。

Phase 2 的 ``IDWImputer`` 用固定 power(由 YAML 設);本模型在 fit 階段對每個 target
做 k-fold CV,從 ``power_grid`` 中挑出 train CV MAE 最低的 power,然後用它做預測。

可解釋性 10/10:
  - ``.explain()`` 直接回傳每個 candidate power 的 CV MAE 與被挑中的值,
    任何審閱者都看得懂

設計選擇:
  - CV 方式:KFold(shuffle 過,給定 seed),純 row-level 切分
  - 由於 fit 不會學任何「真參數」,挑出的 power 就是最終 deploy 用的;不需 refit
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.model_selection import KFold

from ..base import BaseImputer
from ..registry import register
from ..weighted._utils import nan_safe_weighted_mean, neighbor_distances_from_meta

logger = logging.getLogger(__name__)


@register
class IDWOptimalImputer(BaseImputer):
    """Cross-validated IDW:fit 時挑最佳 power,predict 時固定用它。

    Params(沒有 default):
        power_grid: list[float] — CV 候選 power 集合,例:``[0.5, 1.0, 1.5, 2.0, 2.5, 3.0]``
        eps:        float ≥ 0   — d_i=0 時的 floor(避免除 0)
        cv_folds:   int  ≥ 2    — KFold 折數
        cv_seed:    int          — KFold 洗牌種子(可解釋性需要可重現)
    """

    name = "idw_optimal"
    tier = 3
    explainability = 10

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("power_grid", "eps", "cv_folds", "cv_seed"):
            if k not in params:
                raise KeyError(f"IDWOptimal 需 `{k}` 參數(YAML 設,沒有 default)")
        self.power_grid = [float(p) for p in params["power_grid"]]
        self.eps = float(params["eps"])
        self.cv_folds = int(params["cv_folds"])
        self.cv_seed = int(params["cv_seed"])

        if not self.power_grid:
            raise ValueError("power_grid 不能為空")
        if any(p <= 0 for p in self.power_grid):
            raise ValueError(f"power_grid 內所有元素需 > 0,收到 {self.power_grid}")
        if self.eps < 0:
            raise ValueError(f"eps 需 ≥ 0,收到 {self.eps}")
        if self.cv_folds < 2:
            raise ValueError(f"cv_folds 需 ≥ 2,收到 {self.cv_folds}")

        self._power_chosen: float | None = None
        self._cv_mae: dict[float, float] = {}
        self._n_train: int = 0

    # ---- CV ------------------------------------------------------------------

    @staticmethod
    def _idw_predict(X: np.ndarray, d: np.ndarray, p: float, eps: float) -> np.ndarray:
        w = 1.0 / np.power(d + eps, p)
        return nan_safe_weighted_mean(X, w)

    def _cv_score_for_power(self, X: np.ndarray, y: np.ndarray, d: np.ndarray,
                            power: float) -> float:
        """計算單一 power 下的 CV MAE。

        IDW 沒有 fit 過程,所以 CV 不在 fit 模型(沒東西可 fit)——
        而是在 「給定 power → 對 hold-out row 計算 IDW 預測 → MAE」。
        理論上等於對 power 做直接訓練集評估,但用 KFold 確保
        各 fold 評估彼此獨立、噪音被平均。
        """
        kf = KFold(n_splits=self.cv_folds, shuffle=True, random_state=self.cv_seed)
        fold_maes: list[float] = []
        for _, hold in kf.split(X):
            X_h, y_h = X[hold], y[hold]
            y_hat = self._idw_predict(X_h, d, power, self.eps)
            m = np.isfinite(y_hat) & np.isfinite(y_h)
            if m.sum() < 2:
                continue
            fold_maes.append(float(np.mean(np.abs(y_hat[m] - y_h[m]))))
        if not fold_maes:
            return float("nan")
        return float(np.mean(fold_maes))

    # ---- BaseImputer API -----------------------------------------------------

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "IDWOptimalImputer":
        K = X.shape[1]
        d = neighbor_distances_from_meta(meta, K)
        finite = np.isfinite(y) & np.isfinite(X).all(axis=1)
        Xf, yf = X[finite], y[finite]
        self._n_train = int(finite.sum())

        if self._n_train < self.cv_folds * 2:
            # 樣本太少:退回 power_grid 中位數,別 CV
            mid = self.power_grid[len(self.power_grid) // 2]
            logger.debug("target %s: 樣本 %d < %d,跳 CV 用 power=%g",
                         meta.get("target_station_id"), self._n_train, self.cv_folds * 2, mid)
            self._power_chosen = mid
            self._cv_mae = {}
            self._fitted = True
            return self

        scores: dict[float, float] = {}
        for p in self.power_grid:
            scores[p] = self._cv_score_for_power(Xf, yf, d, p)

        self._cv_mae = scores
        valid = {p: s for p, s in scores.items() if np.isfinite(s)}
        if not valid:
            self._power_chosen = self.power_grid[len(self.power_grid) // 2]
        else:
            self._power_chosen = min(valid, key=lambda p: valid[p])
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if not self._fitted or self._power_chosen is None:
            raise RuntimeError("IDWOptimalImputer 還沒 fit")
        K = X.shape[1]
        d = neighbor_distances_from_meta(meta, K)
        return self._idw_predict(X, d, self._power_chosen, self.eps)

    def explain(self) -> dict[str, Any]:
        return {
            "power_chosen": float(self._power_chosen) if self._power_chosen is not None else None,
            "cv_mae_per_power": {f"{p:g}": float(m) for p, m in self._cv_mae.items()},
            "power_grid": list(self.power_grid),
            "cv_folds": self.cv_folds,
            "n_train": self._n_train,
        }
