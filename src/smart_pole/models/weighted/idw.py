"""IDW(Inverse-Distance Weighting):經典的 w_i = 1 / (d_i + eps)^power。

對 ``selector=distance`` 是傳統用法;對 ``selector=correlation`` 也能跑——
此時 ``meta['distances']`` 是 ``1 - |r|``(相關度差),於是 IDW 退化為
「越相關權重越大」的加權,在語意上合理但 power/eps 的最佳值會不同。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..base import BaseImputer
from ..registry import register
from ._utils import nan_safe_weighted_mean, neighbor_distances_from_meta


@register
class IDWImputer(BaseImputer):
    """w_i = 1 / (d_i + eps)^power,以加權平均當預測。

    Params(沒有 default):
        power: float > 0 — 距離指數
        eps:   float ≥ 0 — 避免 d_i=0 時除以 0;當 0 時最近鄰會獨佔權重
    """

    name = "idw"
    tier = 2
    explainability = 10

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        if "power" not in params:
            raise KeyError("IDW 需 `power` 參數(YAML 設,沒有 default)")
        if "eps" not in params:
            raise KeyError("IDW 需 `eps` 參數(YAML 設,沒有 default)")
        self.power = float(params["power"])
        self.eps = float(params["eps"])
        if self.power <= 0:
            raise ValueError(f"power 需 > 0,收到 {self.power}")
        if self.eps < 0:
            raise ValueError(f"eps 需 ≥ 0,收到 {self.eps}")

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "IDWImputer":
        # 純距離權重,fit 不需訓練;保留契約。
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        K = X.shape[1]
        d = neighbor_distances_from_meta(meta, K)
        w = 1.0 / np.power(d + self.eps, self.power)
        return nan_safe_weighted_mean(X, w)
