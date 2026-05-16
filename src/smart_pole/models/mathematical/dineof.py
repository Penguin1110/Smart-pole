"""DINEOF — Data Interpolating EOF(Phase 3b)。

正規 DINEOF 演算法是 Beckers & Rixen (2003) 的「iterative SVD with EOF cross-validation」。
本實作走 CLAUDE.md 規範的**簡化版**:sklearn ``IterativeImputer`` 的精神 + ``TruncatedSVD`` 的核心,
手寫 iter-SVD 迴圈,結果等價。

演算法:
  1. 把 ``mask_full=True`` 的格子當成 NaN,初始用 column mean 填補
  2. SVD 取前 ``n_modes`` 個 mode,low-rank 重建整個 (T, S) 矩陣
  3. 只把「原本被 mask 的格子」更新成重建值,其餘保持原本觀測值
  4. 收斂或達 ``max_iter`` 後停止
  5. test 時對某個 (test_row, target_idx),直接讀重建矩陣的對應格

特性:
  - **K-independent**:模型完全不看 K 鄰站。runner 走 K-sweep 時各 K 結果應該幾乎一樣
    (差異來自 K-過小時 train_finite filter 可能讓某些 target 被略過)
  - 計算 O(T S min(T,S))——對 (1456, 1287) 矩陣大約 1 秒一次 SVD,iter 30 次 ~ 30 秒
  - **要用 module-level cache 防止 1287 targets 各跑一次**:cache key = (id(values), id(mask), n_modes, max_iter)

可解釋性 9/10:
  - 空間 modes(SVD 右奇異向量)是「PM2.5 空間分佈樣式」,可在地圖上畫
  - 時間 modes(左奇異向量 × 奇異值)是「對應時間序列強度」,可畫 K-line
  - ``.explain()`` 回傳 chosen n_modes / 收斂時 RMSE / 各 mode 解釋變異比例
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ..base import BaseImputer
from ..registry import register

logger = logging.getLogger(__name__)


# Module-level cache:避免 1287 targets 各跑一次 SVD-impute。
# key = (id(values), id(mask), n_modes, max_iter, tol)
# val = (imputed_matrix, explain_dict)
_IMPUTE_CACHE: dict[tuple, tuple[np.ndarray, dict[str, Any]]] = {}


def _dineof_impute(
    values: np.ndarray,           # (T, S),NaN 表原本就缺
    mask: np.ndarray,             # (T, S) bool,True = 人造 mask + 視同缺
    *,
    n_modes: int,
    max_iter: int,
    tol: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    """主迴圈。回傳 (imputed_TxS, explain dict)。"""
    T, S = values.shape
    # 真正當「未知」的格子:原本缺值 + mask 命中的格子
    missing = (~np.isfinite(values)) | mask
    n_missing = int(missing.sum())
    if n_missing == 0:
        return values.copy(), {"warning": "no missing cells"}

    # 初始填補:column mean(只用「真正觀測到」的格子)
    obs = np.isfinite(values) & (~mask)
    col_sum   = np.where(obs, values, 0.0).sum(axis=0)
    col_count = obs.sum(axis=0)
    col_mean  = np.where(col_count > 0, col_sum / np.maximum(col_count, 1), 0.0)

    X = np.where(missing, col_mean, values).astype(np.float64, copy=True)

    rmse_history: list[float] = []
    sing_vals: np.ndarray | None = None
    iters_used = 0

    for it in range(max_iter):
        # 中心化(用全表 mean,簡化版選擇)
        global_mean = float(X.mean())
        X_centered = X - global_mean

        # SVD truncated to n_modes
        # 全 SVD 比 TruncatedSVD 在 (1456, 1287) 規模上實際更快(LAPACK gesdd 直接,不用 iter)
        try:
            U, s, Vt = np.linalg.svd(X_centered, full_matrices=False)
        except np.linalg.LinAlgError as e:
            logger.warning("DINEOF SVD 失敗 iter=%d: %s", it, e)
            break

        s_trunc = s.copy()
        s_trunc[n_modes:] = 0.0
        X_rec_centered = U @ np.diag(s_trunc) @ Vt
        X_rec = X_rec_centered + global_mean

        # 收斂判斷:只看 missing 格子的變動
        diff = X_rec[missing] - X[missing]
        rmse_iter = float(np.sqrt(np.mean(diff * diff))) if diff.size else 0.0
        rmse_history.append(rmse_iter)

        # 更新:只覆蓋 missing
        X = np.where(missing, X_rec, X)
        iters_used = it + 1
        sing_vals = s

        if rmse_iter < tol:
            logger.debug("DINEOF converged at iter %d, rmse=%.6f", it, rmse_iter)
            break

    if sing_vals is not None:
        total_var = float((sing_vals ** 2).sum())
        modes_var = sing_vals[:n_modes] ** 2 / max(total_var, 1e-12)
        explained_var = float(modes_var.sum())
    else:
        explained_var = float("nan")

    explain = {
        "n_modes":          n_modes,
        "max_iter":         max_iter,
        "iters_used":       iters_used,
        "rmse_history":     rmse_history[-10:],  # 末 10 iter 看收斂
        "explained_variance_ratio": explained_var,
        "n_missing_cells":  n_missing,
        "n_cells_total":    int(values.size),
    }
    return X, explain


@register
class DINEOFImputer(BaseImputer):
    """SVD-based iterative impute on full (T, S) matrix。

    Params(沒有 default):
        n_modes:  int ≥ 1 — 保留幾個 SVD modes
        max_iter: int ≥ 1 — iter-SVD 最多幾輪
        tol:      float > 0 — 收斂條件:該 iter missing-cell RMSE 變動量
    """

    name = "dineof"
    tier = 3
    explainability = 9

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("n_modes", "max_iter", "tol"):
            if k not in params:
                raise KeyError(f"DINEOF 需 `{k}` 參數(YAML 設,沒有 default)")
        self.n_modes  = int(params["n_modes"])
        self.max_iter = int(params["max_iter"])
        self.tol      = float(params["tol"])
        if self.n_modes < 1:
            raise ValueError(f"n_modes ≥ 1,收到 {self.n_modes}")
        if self.max_iter < 1:
            raise ValueError(f"max_iter ≥ 1,收到 {self.max_iter}")
        if self.tol <= 0:
            raise ValueError(f"tol > 0,收到 {self.tol}")

        self._imputed: np.ndarray | None = None
        self._explain: dict[str, Any] | None = None
        self._target_idx: int = -1

    def _ensure_imputed(self, meta: dict[str, Any]) -> None:
        """從 module-level cache 取或計算 imputed 矩陣。"""
        values = meta.get("values_full")
        mask = meta.get("mask_full")
        if values is None or mask is None:
            raise RuntimeError(
                "DINEOF 需要 meta['values_full'] 與 meta['mask_full']——"
                "確認你跑的是 Phase 3 之後的 runner(meta 已擴充)"
            )
        key = (id(values), id(mask), self.n_modes, self.max_iter, self.tol)
        if key not in _IMPUTE_CACHE:
            logger.info("DINEOF cache miss → 跑 SVD-impute,T×S=%s,n_modes=%d",
                        values.shape, self.n_modes)
            _IMPUTE_CACHE[key] = _dineof_impute(
                values, mask,
                n_modes=self.n_modes, max_iter=self.max_iter, tol=self.tol,
            )
        self._imputed, self._explain = _IMPUTE_CACHE[key]

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "DINEOFImputer":
        self._ensure_imputed(meta)
        self._target_idx = int(meta.get("target_idx", -1))
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if self._imputed is None:
            raise RuntimeError("DINEOFImputer 還沒 fit")
        if self._target_idx < 0:
            raise RuntimeError("meta 缺 target_idx——runner 沒接到 Phase 3b extended meta?")
        test_rows = meta.get("test_rows")
        test_slice = meta.get("test_slice")
        if test_rows is None or test_slice is None:
            raise RuntimeError("meta 缺 test_rows / test_slice")
        # imputed 在 test_slice 範圍內、target 那一欄
        test_offset = test_slice.start
        y_pred = self._imputed[test_offset + np.asarray(test_rows), self._target_idx]
        return np.clip(y_pred, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        if self._explain is None:
            return None
        return dict(self._explain)  # shallow copy
