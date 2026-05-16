"""BaseImputer 契約。

CLAUDE.md 規定:所有補值模型必須繼承此基底。Runner 假設介面長這樣;
動 signature 整個 pipeline 都壞。新增超參一律走 ``__init__(**params)``,
新增 sample-level 資訊一律走 ``meta`` dict,不要加位置參數。

Phase 3 新增約束:
  - class-level ``explainability: int`` ∈ [0, 10],Phase 3 模型(tier >= 3)
    必須宣告 ``explainability >= 8``,registry 會擋住低於這個的註冊。
  - ``explain(self)`` 回傳 JSON-serializable dict,描述「為什麼這樣預測」。
    Phase 1/2 模型可保留 default ``None``;Phase 3 應實作。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np


class BaseImputer(ABC):
    """所有補值模型的統一介面。

    參數慣例:
        X:    shape (n_samples, K) — K 個鄰站當下的 PM2.5 值
              (``features.enabled=true`` 時 shape 變 (n_samples, K * (1 + L + R) + L),
               含鄰站滯後 / 滾動 / target 自己的歷史。column 順序由
               ``smart_pole.features.temporal.TemporalFeatureBuilder`` 決定。)
        y:    shape (n_samples,)   — 目標站的真值
        meta: dict,含:
            - target_station_id:    str
            - neighbor_station_ids: list[str]
            - distances:            np.ndarray, shape (n_samples, K)  鄰站距離(公尺);未提供時為 None
            - timestamps:           pd.DatetimeIndex
            - target_coord:         tuple[float, float] | None  (lon, lat)
            - neighbor_coords:      np.ndarray | None, shape (K, 2)
            - feature_names:        list[str] | None
                                    Phase 3 ``features.enabled=true`` 時必填,長度 = X.shape[1]

        Phase 3b 才會用到的 optional fields(其他模型可忽略):
            - values_full:    np.ndarray (T, S)  整段資料矩陣的 read-only reference
            - mask_full:      np.ndarray (T, S) bool  該 seed 的人造 mask
            - train_slice:    slice
            - test_slice:     slice
            - target_idx:     int  ``values_full`` 中 target 的欄 index
            - neighbor_idx:   list[int]  K 鄰站欄 indexes
            - test_rows:      np.ndarray  test_slice 內被 mask 的 row 偏移
                              (僅 ``predict`` 的 meta 才有)
    """

    name: str = "base"
    tier: int = 0
    requires_gpu: bool = False
    explainability: int = 0   # 1–10;tier >= 3 強制要求 >= 8

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
        return {
            "name": self.name,
            "tier": self.tier,
            "explainability": self.explainability,
            "params": self.params,
        }

    def explain(self) -> dict[str, Any] | None:
        """回傳「為什麼這樣預測」的可讀資訊。JSON-serializable。

        Phase 3 模型(tier >= 3)必須 override 此方法。default ``None`` 表示
        此模型本質上不需解釋(例:純算術平均)或 caller 不需要。

        命名建議:
          - ridge / 線性類:`{"weights": [...], "intercept": float}`
          - kriging:`{"variogram": {"sill", "range", "nugget", "model"}}`
          - GP:`{"lengthscale": float, "noise_variance": float, "kernel": str}`
        """
        return None
