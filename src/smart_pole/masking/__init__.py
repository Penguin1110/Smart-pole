"""缺失策略 dispatcher。

config 的 ``masking.strategy`` 對應這邊的字串 key:
  - ``random_point`` → 隨機在 (T, S) 抽 ratio 比例的格子當缺失
  - ``block``        → 對每個站隨機選 ratio 比例的連續時段(block_hours 小時)
  - ``whole_station``→ 隨機選 ratio 比例的站,該站全段當缺失(尚未實作)
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .block import make_block_mask
from .random_point import make_random_point_mask


def make_mask(values: np.ndarray, *, mask_cfg: dict[str, Any], seed: int) -> np.ndarray:
    """依 mask_cfg 派發策略,回傳 boolean mask。True = 人為遮蔽。"""
    strategy = mask_cfg["strategy"]
    ratio = float(mask_cfg["ratio"])

    if strategy == "random_point":
        return make_random_point_mask(values, ratio=ratio, seed=seed)
    if strategy == "block":
        block_hours = int(mask_cfg.get("block_hours", 6))
        return make_block_mask(values, ratio=ratio, block_hours=block_hours, seed=seed)
    if strategy == "whole_station":
        raise NotImplementedError("masking.strategy='whole_station' 尚未實作")
    raise NotImplementedError(f"masking.strategy={strategy!r} 尚未實作")


__all__ = ["make_mask", "make_random_point_mask", "make_block_mask"]
