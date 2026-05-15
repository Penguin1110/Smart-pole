"""最廢的 baseline:K 個鄰站當下值的算術平均。"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..base import BaseImputer
from ..registry import register


@register
class MeanImputer(BaseImputer):
    """直接取 K 個鄰站 PM2.5 的算術平均。"""

    name = "mean"
    tier = 1

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "MeanImputer":
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        return np.nanmean(X, axis=1)
