"""鄰站挑選——回傳 K 個鄰居 + 一個距離/相似度 proxy。

提供兩種策略(對應 config schema 的 ``selector: distance | correlation``):

  - ``select_by_distance``: 用 haversine 算地表距離,挑最近 K 站。
    需要 ``coords: dict[str, (lon, lat)]``,目前 raw 資料缺 lat/lon,
    補上後此函式即可生效。
  - ``select_by_correlation``: 用 train 段的 Pearson 相關係數(對應 |r| 高的視為「近」),
    當作 distance 不可用時的 fallback。回傳的「距離」是 ``1 - |r|``,純粹給 runner
    當 sortable proxy 用,**不是地理距離**。
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


# 地球平均半徑(公尺)—— haversine 用
_EARTH_RADIUS_M = 6_371_000.0


def _haversine(lon1: float, lat1: float, lon2: np.ndarray, lat2: np.ndarray) -> np.ndarray:
    """單點 vs 多點 haversine,結果單位公尺。"""
    rlon1, rlat1 = np.radians(lon1), np.radians(lat1)
    rlon2, rlat2 = np.radians(lon2), np.radians(lat2)
    dlon = rlon2 - rlon1
    dlat = rlat2 - rlat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(rlat1) * np.cos(rlat2) * np.sin(dlon / 2.0) ** 2
    return 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def select_by_distance(
    target: str,
    station_ids: list[str],
    coords: dict[str, tuple[float, float]],
    K: int,
) -> tuple[list[str], np.ndarray]:
    """挑離 target 最近的 K 個鄰站。

    Args:
        target:      目標站 station_id,必須在 coords 內
        station_ids: 所有候選站(會自動排除 target 本身與沒有座標的站)
        coords:      dict[station_id, (lon, lat)]
        K:           取前 K 名

    Returns:
        (neighbor_ids, distances_m) 兩者長度都是 K,並依距離由近到遠排序。
    """
    if target not in coords:
        raise KeyError(f"target station {target!r} 沒有座標,無法做 distance selection")
    if K <= 0:
        raise ValueError(f"K 需 > 0,收到 {K}")

    candidates = [s for s in station_ids if s != target and s in coords]
    if len(candidates) < K:
        raise ValueError(
            f"可用鄰站數 {len(candidates)} 小於 K={K}(target={target})"
        )

    lon_t, lat_t = coords[target]
    lons = np.array([coords[s][0] for s in candidates], dtype=np.float64)
    lats = np.array([coords[s][1] for s in candidates], dtype=np.float64)
    dists = _haversine(lon_t, lat_t, lons, lats)

    order = np.argsort(dists, kind="stable")[:K]
    neighbor_ids = [candidates[i] for i in order]
    return neighbor_ids, dists[order]


def select_by_correlation(
    target: str,
    station_ids: list[str],
    values: np.ndarray,
    K: int,
    *,
    train_slice: slice | None = None,
    min_overlap: int = 24,
) -> tuple[list[str], np.ndarray]:
    """挑與 target 在 train 段 Pearson |r| 最高的 K 站。

    回傳的「距離」是 ``1 - |r|``,值越小越相關。**不是真實距離**,只是
    給 runner 當 sortable proxy 用。

    Args:
        target:       目標 station_id
        station_ids:  所有站(含 target)
        values:       shape (T, S),NaN 表缺值
        K:            取前 K 名
        train_slice:  計算相關係數要用的時間切片;None=用全部
        min_overlap: 兩站共同非 NaN 樣本數小於此值時,該候選被剔除
    """
    if target not in station_ids:
        raise KeyError(f"target station {target!r} 不在 station_ids 內")
    if K <= 0:
        raise ValueError(f"K 需 > 0,收到 {K}")

    sub = values if train_slice is None else values[train_slice]
    t_idx = station_ids.index(target)
    y = sub[:, t_idx]

    n_stations = sub.shape[1]
    abs_r = np.full(n_stations, np.nan, dtype=np.float64)

    y_mask = np.isfinite(y)
    for j in range(n_stations):
        if j == t_idx:
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
        raise ValueError(
            f"與 {target} 有足夠重疊樣本的候選站只有 {len(valid)} 個,小於 K={K}"
        )
    order = valid[np.argsort(-abs_r[valid], kind="stable")[:K]]
    neighbor_ids = [station_ids[i] for i in order]
    proxy = 1.0 - abs_r[order]
    return neighbor_ids, proxy
