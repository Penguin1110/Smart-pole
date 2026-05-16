"""OrdinaryKrigingImputer 行為測試。"""
from __future__ import annotations

import json

import numpy as np
import pytest

from smart_pole.models import mathematical  # noqa: F401  觸發註冊
from smart_pole.models.registry import get_model


def _meta(K: int, n: int, neighbor_coords: np.ndarray, target_coord: tuple[float, float]) -> dict:
    return {
        "target_station_id":    "T",
        "neighbor_station_ids": [f"N{i}" for i in range(K)],
        "distances":            np.tile(np.linspace(100.0, 1000.0, K), (n, 1)),
        "timestamps":           None,
        "target_coord":         target_coord,
        "neighbor_coords":      neighbor_coords,
    }


def test_kriging_registered() -> None:
    cls = get_model("kriging")
    assert cls.tier == 3
    assert cls.explainability == 9


def test_requires_params() -> None:
    cls = get_model("kriging")
    base = {"variogram_model": "spherical", "n_bins": 8,
            "max_range_m": 30000.0, "nugget": "fit"}
    for missing in base:
        bad = {k: v for k, v in base.items() if k != missing}
        with pytest.raises(KeyError, match=missing):
            cls(**bad)


def test_rejects_unknown_variogram_model() -> None:
    cls = get_model("kriging")
    with pytest.raises(ValueError, match="variogram_model"):
        cls(variogram_model="invalid", n_bins=8, max_range_m=30000.0, nugget=0.0)


def _spread_neighbor_coords(K: int, target_coord: tuple[float, float], spread_deg: float = 0.02) -> np.ndarray:
    """以 target 為中心,K 個鄰站在隨機方位、不同半徑展開,避免 pair 距離全擠同一 bin。"""
    rng = np.random.default_rng(2026)
    angles = np.linspace(0, 2 * np.pi, K, endpoint=False) + rng.uniform(-0.2, 0.2, size=K)
    radii  = spread_deg * np.linspace(0.3, 1.0, K)  # 不同半徑
    return np.array([
        (target_coord[0] + r * np.cos(a), target_coord[1] + r * np.sin(a))
        for a, r in zip(angles, radii)
    ])


def test_fit_predict_synthetic_grid() -> None:
    """造一個合成 spatial signal,Kriging 應該預測接近真值。"""
    rng = np.random.default_rng(42)
    K = 8
    target_coord = (120.300, 22.600)
    neighbor_coords = _spread_neighbor_coords(K, target_coord, spread_deg=0.02)

    n = 300
    base_field = rng.normal(scale=2.0, size=n)
    X = np.column_stack([base_field + rng.normal(scale=0.5, size=n) for _ in range(K)])
    y = base_field + rng.normal(scale=0.3, size=n)

    cls = get_model("kriging")
    m = cls(variogram_model="exponential", n_bins=5,
            max_range_m=5000.0, nugget="fit")
    m.fit(X, y, _meta(K, n, neighbor_coords, target_coord))

    expl = m.explain()
    assert expl is not None and "variogram_params" in expl, f"expl={expl}"
    X_test = X[:10]; y_test = y[:10]
    y_pred = m.predict(X_test, _meta(K, 10, neighbor_coords, target_coord))
    mae_kriging = float(np.mean(np.abs(y_test - y_pred)))
    mae_zero    = float(np.mean(np.abs(y_test)))
    assert mae_kriging < mae_zero, f"MAE_kriging={mae_kriging} 沒比 zero pred ({mae_zero}) 好"


def test_explain_is_json_serializable() -> None:
    rng = np.random.default_rng(7)
    K = 6
    target_coord = (120.3, 22.6)
    neighbor_coords = _spread_neighbor_coords(K, target_coord, spread_deg=0.02)
    n = 200
    X = rng.normal(size=(n, K))
    y = rng.normal(size=n)
    cls = get_model("kriging")
    m = cls(variogram_model="spherical", n_bins=5,
            max_range_m=5000.0, nugget=0.5).fit(X, y, _meta(K, n, neighbor_coords, target_coord))
    blob = json.dumps(m.explain())
    assert "variogram_model" in blob


def test_fallback_when_no_coords() -> None:
    """meta 缺座標時不要 crash,退回等權平均。"""
    cls = get_model("kriging")
    m = cls(variogram_model="exponential", n_bins=5, max_range_m=5000.0, nugget=0.0)
    X = np.array([[1.0, 2.0, 3.0],
                  [4.0, 5.0, 6.0]])
    y = np.array([2.0, 5.0])
    no_coord_meta = {"target_station_id": "T", "neighbor_station_ids": ["A", "B", "C"],
                      "distances": np.ones((2, 3)), "timestamps": None,
                      "target_coord": None, "neighbor_coords": None}
    m.fit(X, y, no_coord_meta)
    expl = m.explain()
    assert "error" in expl
    out = m.predict(np.array([[10.0, 10.0, 10.0]]), no_coord_meta)
    # 退回 uniform mean → 10.0
    np.testing.assert_allclose(out, [10.0])
