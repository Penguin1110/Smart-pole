"""diverse selector:greedy farthest-point sampling 強制空間分散度。

對「最近 K 站常擠在污染源相似的同一區」這個 Phase 1 finding 的反命題:
強制 K 個鄰站盡量散在不同方位 / 距離,期望覆蓋更多獨立的訊號。

策略:
  1. 取所有候選站(排除 target)
  2. 第一個鄰站 = 距離 target 最近的站(讓 K=1 退化成 distance baseline)
  3. 之後每一輪挑「離已選鄰站集合最遠的站」(maximin)
  4. 重複到 K 個

回傳的「距離 proxy」是該鄰站到 target 的真實距離(公尺),與 distance selector
語意相同——讓 weighted 模型不用知道 selector 內部演算法即可吃。
"""
from __future__ import annotations

import logging

import numpy as np

from .selector import _haversine

logger = logging.getLogger(__name__)


def select_diverse(
    target: str,
    station_ids: list[str],
    coords: dict[str, tuple[float, float]],
    K: int,
) -> tuple[list[str], np.ndarray]:
    """greedy farthest-point sampling 選 K 個分散鄰站。

    回傳 (neighbor_ids, distance_to_target_m)。順序保證:第一個 = 最近站,
    之後依加入順序(maximin)。
    """
    if target not in coords:
        raise KeyError(f"target {target!r} 沒有座標")
    if K <= 0:
        raise ValueError(f"K 需 > 0,收到 {K}")
    candidates = [s for s in station_ids if s != target and s in coords]
    if len(candidates) < K:
        raise ValueError(f"可用候選 {len(candidates)} 不足 K={K}")

    lon_t, lat_t = coords[target]
    lons = np.array([coords[s][0] for s in candidates], dtype=np.float64)
    lats = np.array([coords[s][1] for s in candidates], dtype=np.float64)

    d_to_target = _haversine(lon_t, lat_t, lons, lats)

    # 候選間兩兩距離(只算需要時 lazy 算太麻煩,直接全算——1287 站 ~ 1.6M pair,可接受)
    # 但 K 通常小,優化只算 picked vs rest 即可
    chosen_idx: list[int] = [int(np.argmin(d_to_target))]
    remaining = set(range(len(candidates))) - set(chosen_idx)

    # min_d_to_chosen[i] = i 到已選集合最小距離
    last_chosen_lon = lons[chosen_idx[0]]
    last_chosen_lat = lats[chosen_idx[0]]
    min_d = _haversine(last_chosen_lon, last_chosen_lat, lons, lats)
    min_d[chosen_idx[0]] = -np.inf  # 標記已選,讓 argmax 不會選回去

    while len(chosen_idx) < K:
        next_i = int(np.argmax(min_d))
        chosen_idx.append(next_i)
        # 更新 min_d:新加入點到其他點的距離,取 min
        d_from_new = _haversine(lons[next_i], lats[next_i], lons, lats)
        min_d = np.minimum(min_d, d_from_new)
        min_d[next_i] = -np.inf

    neighbor_ids = [candidates[i] for i in chosen_idx]
    distances = d_to_target[np.array(chosen_idx, dtype=int)]
    return neighbor_ids, distances


def select_diverse_table(
    station_ids: list[str],
    coords: dict[str, tuple[float, float]],
    K_max: int,
) -> dict[str, tuple[list[str], np.ndarray]]:
    """對所有站算 diverse K_max 鄰居,回傳 runner 用的 table。"""
    table: dict[str, tuple[list[str], np.ndarray]] = {}
    for target in station_ids:
        if target not in coords:
            logger.warning("target %s 無座標,跳過", target)
            continue
        try:
            ids, dists = select_diverse(target, station_ids, coords, K_max)
        except ValueError as e:
            logger.warning("無法替 %s 選 diverse neighbors:%s", target, e)
            continue
        table[target] = (ids, dists)
    return table
