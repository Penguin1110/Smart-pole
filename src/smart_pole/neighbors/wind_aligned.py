"""wind_aligned selector:偏好上風 / 下風方向的鄰站。

研究動機:污染物隨風飄移,上風站的訊號比下風站「領先」、下風站的訊號比上風
「滯後」,兩者都比側風方向更能解釋 target 的當下值。Phase 2 沒接 CWA 即時風,
所以這版用「實驗期間平均風向」當常數;若 CWA 資料補齊,可換成時變版本。

評分函數:
  score(neighbor) = cos(2 * (θ_neighbor - θ_wind))  ∈ [-1, 1]
  其中 θ_neighbor 是 target → neighbor 的方位角,θ_wind 是風來的方向。
  ``cos(2θ)`` 在 θ=0 (上風) 和 θ=180° (下風) 都是 1,在側風 ±90° 是 -1。

最終得分 = α * cos(2θ) - β * normalized_distance,意思是「越上下風 + 越近 越好」。
α / β 可由 selector_params 控,預設 α=1, β=0.3(距離次要)。
"""
from __future__ import annotations

import logging

import numpy as np

from .selector import _haversine

logger = logging.getLogger(__name__)


def _bearing_deg(lon1: float, lat1: float, lon2: np.ndarray, lat2: np.ndarray) -> np.ndarray:
    """從點1看點2的方位角(度,0=北,順時針)。"""
    rlon1, rlat1 = np.radians(lon1), np.radians(lat1)
    rlon2, rlat2 = np.radians(lon2), np.radians(lat2)
    dlon = rlon2 - rlon1
    y = np.sin(dlon) * np.cos(rlat2)
    x = np.cos(rlat1) * np.sin(rlat2) - np.sin(rlat1) * np.cos(rlat2) * np.cos(dlon)
    brng = np.rad2deg(np.arctan2(y, x))
    return (brng + 360.0) % 360.0


def select_wind_aligned(
    target: str,
    station_ids: list[str],
    coords: dict[str, tuple[float, float]],
    K: int,
    *,
    wind_dir_deg: float,
    alpha: float = 1.0,
    beta: float = 0.3,
) -> tuple[list[str], np.ndarray]:
    """挑 K 個最對齊風軸(上風或下風)的鄰站。

    Args:
        wind_dir_deg: 風來的方向(度,0=北,順時針,氣象慣例)
        alpha:        風軸得分權重(>0)
        beta:         距離懲罰權重(>=0;0 表示完全不在乎距離)
    """
    if target not in coords:
        raise KeyError(f"target {target!r} 無座標")
    if K <= 0:
        raise ValueError(f"K 需 > 0,收到 {K}")
    candidates = [s for s in station_ids if s != target and s in coords]
    if len(candidates) < K:
        raise ValueError(f"可用候選 {len(candidates)} 不足 K={K}")

    lon_t, lat_t = coords[target]
    lons = np.array([coords[s][0] for s in candidates], dtype=np.float64)
    lats = np.array([coords[s][1] for s in candidates], dtype=np.float64)

    bearings = _bearing_deg(lon_t, lat_t, lons, lats)
    # cos(2θ):θ 是與風軸的夾角
    dtheta = np.deg2rad(bearings - wind_dir_deg)
    wind_score = np.cos(2.0 * dtheta)   # [-1, 1]

    dists = _haversine(lon_t, lat_t, lons, lats)
    # 距離 normalize 到 [0, 1] 內,避免兩個 term 量級不一致
    d_max = float(dists.max()) if dists.max() > 0 else 1.0
    norm_d = dists / d_max
    score = alpha * wind_score - beta * norm_d

    order = np.argsort(-score, kind="stable")[:K]
    neighbor_ids = [candidates[i] for i in order]
    distances = dists[order]
    return neighbor_ids, distances


def select_wind_aligned_table(
    station_ids: list[str],
    coords: dict[str, tuple[float, float]],
    K_max: int,
    *,
    wind_dir_deg: float,
    alpha: float = 1.0,
    beta: float = 0.3,
) -> dict[str, tuple[list[str], np.ndarray]]:
    """對所有站算 wind_aligned K_max 鄰居,回傳 runner 用的 table。"""
    table: dict[str, tuple[list[str], np.ndarray]] = {}
    for target in station_ids:
        if target not in coords:
            continue
        try:
            ids, dists = select_wind_aligned(
                target, station_ids, coords, K_max,
                wind_dir_deg=wind_dir_deg, alpha=alpha, beta=beta,
            )
        except ValueError as e:
            logger.warning("無法替 %s 選 wind_aligned neighbors:%s", target, e)
            continue
        table[target] = (ids, dists)
    return table
