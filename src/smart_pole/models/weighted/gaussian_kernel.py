"""Gaussian Kernel:w_i = exp(-d_i^2 / (2 σ²))。

Phase 3 Kriging / Gaussian Process 的前奏;σ 控制「視野半徑」。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..base import BaseImputer
from ..registry import register
from ._utils import nan_safe_weighted_mean, neighbor_distances_from_meta


@register
class GaussianKernelImputer(BaseImputer):
    """w_i = exp(-d_i² / (2 σ²)),加權平均。

    Params(沒有 default):
        sigma: float > 0 — 距離尺度(公尺,當 selector=distance);
               correlation selector 下 distance proxy 在 [0, 1],sigma 設小一些更合理
    """

    name = "gaussian_kernel"
    tier = 2

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        if "sigma" not in params:
            raise KeyError("GaussianKernel 需 `sigma` 參數(YAML 設,沒有 default)")
        self.sigma = float(params["sigma"])
        if self.sigma <= 0:
            raise ValueError(f"sigma 需 > 0,收到 {self.sigma}")

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "GaussianKernelImputer":
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        K = X.shape[1]
        d = neighbor_distances_from_meta(meta, K)
        # 避免大 d 導致 underflow:減去最小 d²/2σ² 等同於整體乘常數,
        # 在 normalize 後不影響結果
        z = d * d / (2.0 * self.sigma * self.sigma)
        z = z - z.min()
        w = np.exp(-z)
        return nan_safe_weighted_mean(X, w)
