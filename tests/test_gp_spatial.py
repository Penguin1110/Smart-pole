"""SpatialGPImputer 行為測試。"""
from __future__ import annotations

import json

import numpy as np
import pytest

from smart_pole.models import mathematical  # noqa: F401  觸發註冊
from smart_pole.models.registry import get_model


def _spread_neighbor_coords(K: int, target_coord, spread_deg: float = 0.02) -> np.ndarray:
    rng = np.random.default_rng(2026)
    angles = np.linspace(0, 2 * np.pi, K, endpoint=False) + rng.uniform(-0.2, 0.2, size=K)
    radii  = spread_deg * np.linspace(0.3, 1.0, K)
    return np.array([
        (target_coord[0] + r * np.cos(a), target_coord[1] + r * np.sin(a))
        for a, r in zip(angles, radii)
    ])


def _meta(K: int, n: int, neighbor_coords, target_coord) -> dict:
    return {
        "target_station_id":    "T",
        "neighbor_station_ids": [f"N{i}" for i in range(K)],
        "distances":            np.tile(np.linspace(100.0, 1000.0, K), (n, 1)),
        "timestamps":           None,
        "target_coord":         target_coord,
        "neighbor_coords":      neighbor_coords,
    }


def test_spatial_gp_registered() -> None:
    cls = get_model("spatial_gp")
    assert cls.tier == 3
    assert cls.explainability == 8
    assert cls.requires_gpu is False


def test_requires_params() -> None:
    cls = get_model("spatial_gp")
    base = {"kernel": "rbf", "n_iter": 20, "lr": 0.1,
            "lengthscale_init_m": 1000.0, "noise_floor": 0.01}
    for missing in base:
        bad = {k: v for k, v in base.items() if k != missing}
        with pytest.raises(KeyError, match=missing):
            cls(**bad)


def test_rejects_unknown_kernel() -> None:
    cls = get_model("spatial_gp")
    with pytest.raises(ValueError, match="kernel"):
        cls(kernel="bad", n_iter=10, lr=0.1, lengthscale_init_m=1000.0, noise_floor=0.01)


def test_fit_predict_synthetic() -> None:
    rng = np.random.default_rng(42)
    K = 8
    target_coord = (120.300, 22.600)
    neighbor_coords = _spread_neighbor_coords(K, target_coord, spread_deg=0.02)
    n = 200
    base_field = rng.normal(scale=2.0, size=n)
    X = np.column_stack([base_field + rng.normal(scale=0.5, size=n) for _ in range(K)])
    y = base_field + rng.normal(scale=0.3, size=n)

    cls = get_model("spatial_gp")
    m = cls(kernel="matern52", n_iter=30, lr=0.1,
            lengthscale_init_m=1000.0, noise_floor=0.01)
    m.fit(X, y, _meta(K, n, neighbor_coords, target_coord))

    expl = m.explain()
    assert expl is not None
    # 沒 fallback 的情況應有 kernel 字段
    if "error" not in expl:
        assert "kernel" in expl and "lengthscale_m" in expl

    X_test = X[:10]; y_test = y[:10]
    y_pred = m.predict(X_test, _meta(K, 10, neighbor_coords, target_coord))
    assert y_pred.shape == (10,)
    mae_gp   = float(np.mean(np.abs(y_test - y_pred)))
    mae_mean = float(np.mean(np.abs(y_test - y_test.mean())))
    assert mae_gp < mae_mean * 2.0, f"GP MAE {mae_gp} 不比 mean baseline {mae_mean} 合理"


def test_explain_is_json_serializable() -> None:
    rng = np.random.default_rng(7)
    K = 6
    target_coord = (120.3, 22.6)
    neighbor_coords = _spread_neighbor_coords(K, target_coord, spread_deg=0.02)
    n = 200
    X = rng.normal(size=(n, K))
    y = rng.normal(size=n)
    cls = get_model("spatial_gp")
    m = cls(kernel="rbf", n_iter=10, lr=0.1,
            lengthscale_init_m=1000.0, noise_floor=0.01).fit(X, y, _meta(K, n, neighbor_coords, target_coord))
    json.dumps(m.explain())  # 不能炸


def test_fallback_when_no_coords() -> None:
    cls = get_model("spatial_gp")
    m = cls(kernel="rbf", n_iter=5, lr=0.1, lengthscale_init_m=1000.0, noise_floor=0.0)
    X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    y = np.array([1.0, 3.0, 5.0])
    no_coord = {"target_station_id": "T", "neighbor_station_ids": ["A", "B"],
                 "distances": np.ones((3, 2)), "timestamps": None,
                 "target_coord": None, "neighbor_coords": None}
    m.fit(X, y, no_coord)
    out = m.predict(np.array([[10.0, 10.0]]), no_coord)
    np.testing.assert_allclose(out, [10.0])
