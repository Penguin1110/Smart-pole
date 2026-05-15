"""Stream B selector 行為測試。

驗收條件(per CLAUDE.md):
  (a) 不選到 target 自己
  (b) 回傳數量等於 K
  (c) 順序與 selector 語意一致
"""
from __future__ import annotations

import numpy as np
import pytest

from smart_pole.neighbors.diverse import select_diverse
from smart_pole.neighbors.hybrid import select_hybrid
from smart_pole.neighbors.wind_aligned import select_wind_aligned, _bearing_deg


# ---- helpers -----------------------------------------------------------------


def _grid_coords(side: int = 5, spacing_deg: float = 0.01) -> dict[str, tuple[float, float]]:
    """產生 side×side 的格狀座標,key 為 'g_{i}_{j}'。"""
    coords = {}
    for i in range(side):
        for j in range(side):
            coords[f"g_{i}_{j}"] = (120.0 + j * spacing_deg, 22.0 + i * spacing_deg)
    return coords


# ---- diverse -----------------------------------------------------------------


def test_diverse_excludes_target() -> None:
    coords = _grid_coords(5)
    target = "g_2_2"
    ids = list(coords.keys())
    chosen, _ = select_diverse(target, ids, coords, K=5)
    assert target not in chosen


def test_diverse_count_matches_K() -> None:
    coords = _grid_coords(5)
    target = "g_0_0"
    ids = list(coords.keys())
    for K in (1, 3, 10):
        chosen, dists = select_diverse(target, ids, coords, K=K)
        assert len(chosen) == K
        assert dists.shape == (K,)


def test_diverse_first_is_nearest() -> None:
    """K=1 時 diverse 應退化為 distance 最近站。"""
    coords = _grid_coords(5)
    target = "g_2_2"
    ids = list(coords.keys())
    chosen, _ = select_diverse(target, ids, coords, K=1)
    # g_2_2 的鄰居四選一(上下左右都距離一格),任一即可
    assert chosen[0] in {"g_1_2", "g_3_2", "g_2_1", "g_2_3"}


def test_diverse_spreads_more_than_distance() -> None:
    """相同 K=4 下,diverse 選出的鄰站兩兩距離總和應 > distance 最近 K 的總和。"""
    from smart_pole.neighbors.selector import select_by_distance
    coords = _grid_coords(7)
    target = "g_3_3"
    ids = list(coords.keys())
    dist_ids, _ = select_by_distance(target, ids, coords, K=4)
    div_ids, _ = select_diverse(target, ids, coords, K=4)

    def pairsum(chosen):
        from smart_pole.neighbors.selector import _haversine
        total = 0.0
        for i, a in enumerate(chosen):
            for b in chosen[i + 1:]:
                la, lo = coords[a]
                lb, lob = coords[b]
                total += float(_haversine(la, lo, np.array([lb]), np.array([lob]))[0])
        return total

    assert pairsum(div_ids) > pairsum(dist_ids), \
        f"diverse {div_ids} 散度應 > distance {dist_ids}"


# ---- hybrid ------------------------------------------------------------------


def _synth_values_for_hybrid(coords: dict[str, tuple[float, float]],
                             seed: int = 0) -> tuple[list[str], np.ndarray]:
    """造一份合成 values:每個站 = 兩個潛在源 + 雜訊;與 target 相關的源是 source0。"""
    rng = np.random.default_rng(seed)
    n_t = 300
    source0 = rng.normal(size=n_t)
    source1 = rng.normal(size=n_t)
    ids = list(coords.keys())
    vals = np.zeros((n_t, len(ids)), dtype=np.float64)
    for k, sid in enumerate(ids):
        # 隨機 mix 兩個 source,target 站只跟 source0 有關
        if sid == "target":
            vals[:, k] = source0 + 0.05 * rng.normal(size=n_t)
        else:
            mix = rng.random()
            vals[:, k] = mix * source0 + (1 - mix) * source1 + 0.1 * rng.normal(size=n_t)
    return ids, vals


def test_hybrid_excludes_target() -> None:
    coords = _grid_coords(5)
    coords["target"] = (120.025, 22.025)
    ids, values = _synth_values_for_hybrid(coords)
    chosen, _ = select_hybrid("target", ids, values, coords, K=4)
    assert "target" not in chosen


def test_hybrid_count_and_dist_shape() -> None:
    coords = _grid_coords(5)
    coords["target"] = (120.025, 22.025)
    ids, values = _synth_values_for_hybrid(coords)
    for K in (1, 3, 8):
        chosen, dists = select_hybrid("target", ids, values, coords, K=K)
        assert len(chosen) == K
        assert dists.shape == (K,)


def test_hybrid_distances_are_meters() -> None:
    """hybrid 回傳的 dist 應為真實距離(>0),不是 1-|r|。"""
    coords = _grid_coords(5)
    coords["target"] = (120.025, 22.025)
    ids, values = _synth_values_for_hybrid(coords)
    _, dists = select_hybrid("target", ids, values, coords, K=4)
    # 公尺單位:|grid spacing 0.01°| ≈ ~1.1km,所以 dist 應在數百到數千 m
    assert (dists > 50).all() and (dists < 1e5).all()


# ---- wind_aligned ------------------------------------------------------------


def test_bearing_north_zero() -> None:
    """正北方位角應為 ~0°。"""
    b = _bearing_deg(0.0, 0.0, np.array([0.0]), np.array([1.0]))
    assert abs(b[0]) < 0.1 or abs(b[0] - 360.0) < 0.1


def test_bearing_east_ninety() -> None:
    b = _bearing_deg(0.0, 0.0, np.array([1.0]), np.array([0.0]))
    assert abs(b[0] - 90.0) < 0.1


def test_wind_aligned_excludes_target() -> None:
    coords = _grid_coords(5)
    target = "g_2_2"
    ids = list(coords.keys())
    chosen, _ = select_wind_aligned(target, ids, coords, K=5, wind_dir_deg=0.0)
    assert target not in chosen


def test_wind_aligned_picks_along_axis() -> None:
    """風向 = 0°(北)時,應傾向選 target 正北 / 正南方向的站。"""
    coords = _grid_coords(7)
    target = "g_3_3"
    ids = list(coords.keys())
    chosen, _ = select_wind_aligned(target, ids, coords, K=4,
                                    wind_dir_deg=0.0, alpha=1.0, beta=0.0)
    # 期望多數選在「相同 column」(g_*_3)上;至少前 2 名應在風軸上
    on_axis = [s for s in chosen if s.endswith("_3")]
    assert len(on_axis) >= 2, f"風軸上應至少 2 個,實際:{chosen}"


def test_wind_aligned_count_matches_K() -> None:
    coords = _grid_coords(5)
    target = "g_0_0"
    ids = list(coords.keys())
    for K in (1, 5, 10):
        chosen, dists = select_wind_aligned(target, ids, coords, K=K, wind_dir_deg=45.0)
        assert len(chosen) == K
        assert dists.shape == (K,)
