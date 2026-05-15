"""MeanImputer 行為測試。"""
from __future__ import annotations

import numpy as np
import pytest

from smart_pole.models import baseline  # 觸發註冊 noqa: F401
from smart_pole.models.registry import get_model


def _meta(K: int = 3, n: int = 5) -> dict:
    return {
        "target_station_id":    "T",
        "neighbor_station_ids": [f"N{i}" for i in range(K)],
        "distances":            np.ones((n, K)),
        "timestamps":           None,
        "target_coord":         None,
        "neighbor_coords":      None,
    }


def test_mean_registered() -> None:
    cls = get_model("mean")
    assert cls.name == "mean"
    assert cls.tier == 1


def test_mean_predicts_row_mean() -> None:
    cls = get_model("mean")
    m = cls().fit(np.zeros((1, 3)), np.zeros(1), _meta(K=3, n=1))
    X = np.array([[1.0, 2.0, 3.0],
                  [4.0, 4.0, 4.0],
                  [0.0, 10.0, 5.0]])
    out = m.predict(X, _meta(K=3, n=3))
    np.testing.assert_allclose(out, [2.0, 4.0, 5.0])


def test_mean_handles_nan_with_nanmean() -> None:
    """K 個鄰站有部分 NaN 時,用剩下的算平均;全 NaN 才回 NaN。"""
    cls = get_model("mean")
    m = cls().fit(np.zeros((1, 3)), np.zeros(1), _meta(K=3, n=1))
    X = np.array([[1.0, np.nan, 3.0],     # mean = 2
                  [np.nan, np.nan, np.nan],  # 全 NaN → NaN
                  [10.0, 10.0, np.nan]])     # mean = 10
    with pytest.warns(RuntimeWarning):
        out = m.predict(X, _meta(K=3, n=3))
    assert out[0] == pytest.approx(2.0)
    assert np.isnan(out[1])
    assert out[2] == pytest.approx(10.0)


def test_metrics_basic() -> None:
    from smart_pole.evaluation.metrics import compute_metrics
    y_true = np.array([1.0, 2.0, 3.0, 4.0])
    y_pred = np.array([1.0, 2.0, 3.0, 4.0])
    m = compute_metrics(y_true, y_pred)
    assert m["mae"] == 0.0
    assert m["rmse"] == 0.0
    assert m["r2"] == 1.0
    assert m["n"] == 4


def test_metrics_skips_nan() -> None:
    from smart_pole.evaluation.metrics import compute_metrics
    y_true = np.array([1.0, 2.0, np.nan, 4.0])
    y_pred = np.array([1.0, np.nan, 3.0, 6.0])
    m = compute_metrics(y_true, y_pred)
    assert m["n"] == 2
    assert m["mae"] == pytest.approx(1.0)  # |1-1| + |6-4| / 2


def test_random_point_mask_shape_and_ratio() -> None:
    from smart_pole.masking.random_point import make_random_point_mask
    rng = np.random.default_rng(0)
    values = rng.normal(size=(100, 50))
    values[rng.random(values.shape) < 0.1] = np.nan  # 一些天然缺值
    mask = make_random_point_mask(values, ratio=0.2, seed=42)
    assert mask.dtype == bool
    assert mask.shape == values.shape
    # mask 只在有觀測的格子
    assert not (mask & ~np.isfinite(values)).any()
    n_obs = np.isfinite(values).sum()
    # 接近 ratio,容差 ±1(round)
    assert abs(mask.sum() - round(n_obs * 0.2)) <= 1


def test_random_point_mask_seed_deterministic() -> None:
    from smart_pole.masking.random_point import make_random_point_mask
    values = np.ones((50, 20))
    m1 = make_random_point_mask(values, ratio=0.3, seed=7)
    m2 = make_random_point_mask(values, ratio=0.3, seed=7)
    m3 = make_random_point_mask(values, ratio=0.3, seed=8)
    np.testing.assert_array_equal(m1, m2)
    assert not np.array_equal(m1, m3)
