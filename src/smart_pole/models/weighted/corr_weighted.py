"""CorrWeighted:用 train 段 Pearson r 算每個鄰站對 target 的相關係數,
取 ``w_i = max(0, r_i)`` 標準化後做加權平均。

跟 IDW 的差別:IDW 用 *selector 給的距離 proxy*(可能是真距離或 1-|r|);
CorrWeighted 不依賴 selector,自行在 fit 時從訓練資料算 signed r,**不取絕對值**,
負相關直接設 0 不採用。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..base import BaseImputer
from ..registry import register
from ._utils import nan_safe_weighted_mean


@register
class CorrWeightedImputer(BaseImputer):
    """w_i = max(0, Pearson r_i),加權平均。

    Params:
        min_overlap: int — 該鄰站與 target 在 train 段共有觀測數小於此值時,
                     r_i 視為 0(不採用)。沒有 default。
    """

    name = "corr_weighted"
    tier = 2
    explainability = 10

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        if "min_overlap" not in params:
            raise KeyError("CorrWeighted 需 `min_overlap` 參數(YAML 設,沒有 default)")
        self.min_overlap = int(params["min_overlap"])
        if self.min_overlap < 1:
            raise ValueError(f"min_overlap 需 ≥ 1,收到 {self.min_overlap}")
        self._weights: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "CorrWeightedImputer":
        n, K = X.shape
        weights = np.zeros(K, dtype=np.float64)
        y_obs = np.isfinite(y)
        for k in range(K):
            x = X[:, k]
            m = y_obs & np.isfinite(x)
            if int(m.sum()) < self.min_overlap:
                continue
            yc = y[m] - y[m].mean()
            xc = x[m] - x[m].mean()
            denom = float(np.sqrt((yc * yc).sum() * (xc * xc).sum()))
            if denom == 0.0:
                continue
            r = float((yc * xc).sum() / denom)
            weights[k] = max(0.0, r)
        self._weights = weights
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if self._weights is None:
            raise RuntimeError("CorrWeightedImputer 還沒 fit")
        return nan_safe_weighted_mean(X, self._weights)
