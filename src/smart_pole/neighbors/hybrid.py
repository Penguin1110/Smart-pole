"""hybrid selector:先用 correlation 挑 2K,再從中挑 K 個最分散。

動機:correlation 解決「最近不一定相似」,但同一個污染源附近的高相關鄰站
仍可能聚成一團;再套 farthest-point 強制空間覆蓋,理論上吃兩種好處。
"""
from __future__ import annotations

import logging

import numpy as np

from .selector import _haversine

logger = logging.getLogger(__name__)


def select_hybrid(
    target: str,
    station_ids: list[str],
    values: np.ndarray,
    coords: dict[str, tuple[float, float]],
    K: int,
    *,
    train_slice: slice | None = None,
    min_overlap: int = 24,
    pool_multiplier: int = 2,
) -> tuple[list[str], np.ndarray]:
    """先抓 |r| 最高的 pool_multiplier*K 站,再從中 maximin 挑 K 個。

    回傳的「距離 proxy」是到 target 的實際距離(公尺),與 distance / diverse 一致。
    """
    if target not in coords:
        raise KeyError(f"target {target!r} 無座標")
    if K <= 0:
        raise ValueError(f"K 需 > 0,收到 {K}")
    if pool_multiplier < 1:
        raise ValueError(f"pool_multiplier 需 ≥ 1,收到 {pool_multiplier}")

    pool_size = pool_multiplier * K
    sub = values if train_slice is None else values[train_slice]
    if target not in station_ids:
        raise KeyError(f"target {target!r} 不在 station_ids")
    t_idx = station_ids.index(target)
    y = sub[:, t_idx]
    y_mask = np.isfinite(y)

    n_stations = sub.shape[1]
    abs_r = np.full(n_stations, np.nan, dtype=np.float64)
    for j in range(n_stations):
        if j == t_idx:
            continue
        if station_ids[j] not in coords:
            continue
        x = sub[:, j]
        m = y_mask & np.isfinite(x)
        n = int(m.sum())
        if n < min_overlap:
            continue
        yc, xc = y[m] - y[m].mean(), x[m] - x[m].mean()
        denom = float(np.sqrt((yc * yc).sum() * (xc * xc).sum()))
        if denom == 0.0:
            continue
        r = float((yc * xc).sum() / denom)
        abs_r[j] = abs(r)

    valid = np.flatnonzero(np.isfinite(abs_r))
    if len(valid) < K:
        raise ValueError(f"target {target} 高相關候選 {len(valid)} 不足 K={K}")
    take = min(pool_size, len(valid))
    pool_idx = valid[np.argsort(-abs_r[valid], kind="stable")[:take]]
    pool_ids = [station_ids[i] for i in pool_idx]

    # 在 pool 內做 farthest-point sampling
    lon_t, lat_t = coords[target]
    lons = np.array([coords[s][0] for s in pool_ids], dtype=np.float64)
    lats = np.array([coords[s][1] for s in pool_ids], dtype=np.float64)
    d_to_target = _haversine(lon_t, lat_t, lons, lats)

    # 第一個取「pool 內 |r| 最高」,讓 K=1 退化成 correlation baseline
    # (pool 已經依 |r| 降序,index 0 就是最高)
    chosen_local: list[int] = [0]
    min_d = _haversine(lons[0], lats[0], lons, lats)
    min_d[0] = -np.inf

    while len(chosen_local) < K:
        next_i = int(np.argmax(min_d))
        chosen_local.append(next_i)
        d_from_new = _haversine(lons[next_i], lats[next_i], lons, lats)
        min_d = np.minimum(min_d, d_from_new)
        min_d[next_i] = -np.inf

    neighbor_ids = [pool_ids[i] for i in chosen_local]
    distances = d_to_target[np.array(chosen_local, dtype=int)]
    return neighbor_ids, distances


def select_hybrid_table(
    station_ids: list[str],
    values: np.ndarray,
    train_slice: slice,
    coords: dict[str, tuple[float, float]],
    K_max: int,
    *,
    pool_multiplier: int = 2,
) -> dict[str, tuple[list[str], np.ndarray]]:
    """對所有站算 hybrid K_max 鄰居,回傳 runner 用的 table。"""
    table: dict[str, tuple[list[str], np.ndarray]] = {}
    for target in station_ids:
        if target not in coords:
            continue
        try:
            ids, dists = select_hybrid(
                target, station_ids, values, coords, K_max,
                train_slice=train_slice, pool_multiplier=pool_multiplier,
            )
        except ValueError as e:
            logger.warning("無法替 %s 選 hybrid neighbors:%s", target, e)
            continue
        table[target] = (ids, dists)
    return table
