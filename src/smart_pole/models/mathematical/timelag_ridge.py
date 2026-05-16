"""TimeLag Ridge(Phase 3c)。

Phase 2 ``weighted_ridge`` 的時空升級——只是 X 變寬:
  原本 K 鄰站當下值 → 變成 K*(1+L+R) + L 個 column,加入 lag / rolling / target 歷史。

Ridge 結構完全沒改,只是 features 變多。理論上 lag column 把 PM2.5 ACF 在 24h 內的訊號吃進來,
能補 Phase 2 ridge 看不到的「時間軸」資訊。

可解釋性 10/10:
  - 每個 column 有名字(``feature_names``)
  - ``.explain()`` 回傳完整 weight vector + 對應 feature names + intercept
  - 審閱者直接看 weight 最大的前幾個 feature,就知道模型靠什麼預測
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.linear_model import Ridge

from ..base import BaseImputer
from ..registry import register

logger = logging.getLogger(__name__)


@register
class TimeLagRidgeImputer(BaseImputer):
    """Per-target Ridge 線性回歸,X 包含時空 feature(由 runner + TemporalFeatureBuilder 提供)。

    Params(沒有 default):
        alpha:        float ≥ 0 — Ridge 正則化強度
        min_train:    int        — train rows 不足這個就 fallback uniform mean
    """

    name = "timelag_ridge"
    tier = 3
    explainability = 10

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("alpha", "min_train"):
            if k not in params:
                raise KeyError(f"TimeLagRidge 需 `{k}` 參數(YAML 設,沒有 default)")
        self.alpha = float(params["alpha"])
        self.min_train = int(params["min_train"])
        if self.alpha < 0:
            raise ValueError(f"alpha 需 ≥ 0,收到 {self.alpha}")
        if self.min_train < 1:
            raise ValueError(f"min_train ≥ 1,收到 {self.min_train}")

        self._model: Ridge | None = None
        self._col_means: np.ndarray | None = None  # NaN 填補用
        self._feature_names: list[str] | None = None
        self._fit_mean_y: float = 0.0
        self._n_train: int = 0

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "TimeLagRidgeImputer":
        feature_names = meta.get("feature_names")
        self._feature_names = list(feature_names) if feature_names else None

        # runner 已 drop NaN row(features.enabled=true 時),但保險起見再過一次
        finite = np.isfinite(X).all(axis=1) & np.isfinite(y)
        n_train = int(finite.sum())
        self._n_train = n_train

        if n_train < max(self.min_train, X.shape[1] + 1):
            # 樣本不夠擬合 → fallback
            self._model = None
            self._fit_mean_y = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._col_means = np.zeros(X.shape[1], dtype=np.float64)
            self._fitted = True
            return self

        Xf, yf = X[finite], y[finite]
        self._col_means = np.nan_to_num(np.nanmean(Xf, axis=0), nan=0.0)
        self._fit_mean_y = float(yf.mean())

        self._model = Ridge(alpha=self.alpha, fit_intercept=True).fit(Xf, yf)
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if self._model is None:
            return np.full(X.shape[0], self._fit_mean_y, dtype=np.float64)
        # 缺值用 column train mean 補,讓對應 weight 貢獻 ≈ 該 feature 的均值水準
        assert self._col_means is not None
        X_filled = np.where(np.isfinite(X), X, self._col_means)
        y_pred = self._model.predict(X_filled)
        # 物理上 PM2.5 ∈ [0, ~500],clip 防偶發數值崩壞
        return np.clip(y_pred, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        if self._model is None:
            return {"error": "no fit", "n_train": self._n_train, "fallback": "uniform mean"}
        coefs = np.asarray(self._model.coef_, dtype=np.float64)
        names = self._feature_names or [f"x{i}" for i in range(len(coefs))]
        if len(names) != len(coefs):
            names = [f"x{i}" for i in range(len(coefs))]

        # 依 |coef| 排序找 top 5 重要 feature
        order = np.argsort(-np.abs(coefs))
        top_k = min(5, len(coefs))
        top = [(names[i], float(coefs[i])) for i in order[:top_k]]

        # 把 weight 按 column 類別聚合(同 feature group 的 column 加起來看影響)
        # 例:nb0_t / nb0_t-1 / nb0_t-24 / nb0_roll24 / tgt_t-1 / ...
        group_abs: dict[str, float] = {}
        for name, w in zip(names, coefs):
            # 取 "群組"——拿掉鄰站編號保留 feature 種類
            if name.startswith("nb"):
                # nb{k}_<rest> → 'nb_<rest>'
                _, rest = name.split("_", 1)
                group = f"nb_{rest}"
            else:
                group = name
            group_abs[group] = group_abs.get(group, 0.0) + abs(float(w))

        return {
            "alpha":          self.alpha,
            "intercept":      float(self._model.intercept_),
            "n_train":        self._n_train,
            "n_features":     int(len(coefs)),
            "top_5_features": top,
            "group_abs_weight": dict(sorted(group_abs.items(), key=lambda kv: -kv[1])),
            "weights":        coefs.tolist(),
            "feature_names":  names,
        }
