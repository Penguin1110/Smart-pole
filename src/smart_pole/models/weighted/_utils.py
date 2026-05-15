"""weighted imputer 共用工具。"""
from __future__ import annotations

import numpy as np


def nan_safe_weighted_mean(
    X: np.ndarray,
    w_per_neighbor: np.ndarray,
    *,
    weight_floor: float = 0.0,
) -> np.ndarray:
    """對每一個 sample 做 NaN-safe 的加權平均。

    Args:
        X:                shape (n_samples, K) — 每列是 K 個鄰站當下值
        w_per_neighbor:   shape (K,) — 不分 sample,K 個鄰站的權重(>= 0)
        weight_floor:     當有效權重和小於此值就回 NaN(避免除以幾乎 0)

    Returns:
        shape (n_samples,) — 該 sample 加權平均;若該 sample 所有鄰站都 NaN 或
        有效權重和 <= weight_floor,則回 NaN。
    """
    if X.ndim != 2:
        raise ValueError(f"X 須 2D,收到 shape={X.shape}")
    if w_per_neighbor.shape != (X.shape[1],):
        raise ValueError(
            f"w_per_neighbor shape {w_per_neighbor.shape} 與 X 列數 {X.shape[1]} 不符"
        )

    valid = np.isfinite(X)
    w = np.broadcast_to(w_per_neighbor, X.shape).astype(np.float64)
    w_valid = np.where(valid, w, 0.0)
    x_valid = np.where(valid, X, 0.0)

    num = (x_valid * w_valid).sum(axis=1)
    denom = w_valid.sum(axis=1)
    out = np.full(X.shape[0], np.nan, dtype=np.float64)
    ok = denom > weight_floor
    out[ok] = num[ok] / denom[ok]
    return out


def neighbor_distances_from_meta(meta: dict, K: int) -> np.ndarray:
    """從 meta 取得 K 維距離向量(shape (K,))。

    runner 把 distances tile 成 (n_samples, K),但對一個 target 內所有 sample 都相同,
    所以取第一列即可。
    """
    d = meta.get("distances")
    if d is None:
        raise KeyError("meta 缺 'distances'——weighted 模型需要")
    if d.ndim == 1:
        if d.shape[0] != K:
            raise ValueError(f"distances 長度 {d.shape[0]} ≠ K={K}")
        return d.astype(np.float64)
    if d.ndim == 2:
        if d.shape[1] != K:
            raise ValueError(f"distances 第二維 {d.shape[1]} ≠ K={K}")
        return d[0].astype(np.float64)
    raise ValueError(f"distances 維度異常:shape={d.shape}")
