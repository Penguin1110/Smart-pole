"""BaseImputer 契約。

CLAUDE.md 規定:所有補值模型必須繼承此基底。Runner 假設介面長這樣;
動 signature 整個 pipeline 都壞。新增超參一律走 ``__init__(**params)``,
新增 sample-level 資訊一律走 ``meta`` dict,不要加位置參數。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np


class BaseImputer(ABC):
    """所有補值模型的統一介面。

    參數慣例:
        X:    shape (n_samples, K) — K 個鄰站當下的 PM2.5 值
        y:    shape (n_samples,)   — 目標站的真值
        meta: dict,含:
            - target_station_id:    str
            - neighbor_station_ids: list[str]
            - distances:            np.ndarray, shape (n_samples, K)  鄰站距離(公尺);未提供時為 None
            - timestamps:           pd.DatetimeIndex
            - target_coord:         tuple[float, float] | None  (lon, lat)
            - neighbor_coords:      np.ndarray | None, shape (K, 2)
    """

    name: str = "base"
    tier: int = 0
    requires_gpu: bool = False

    def __init__(self, **params: Any) -> None:
        self.params = params
        self._fitted = False

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "BaseImputer":
        ...

    @abstractmethod
    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        ...

    def get_config(self) -> dict[str, Any]:
        return {"name": self.name, "tier": self.tier, "params": self.params}
