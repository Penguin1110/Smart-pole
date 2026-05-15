"""Stream A weighted 模型契約 + 行為測試。"""
from __future__ import annotations

import numpy as np
import pytest

from smart_pole.models import weighted  # noqa: F401  觸發註冊
from smart_pole.models.registry import get_model


def _meta(K: int, n: int, dists: np.ndarray | None = None) -> dict:
    if dists is None:
        dists = np.linspace(100.0, 1000.0, K)
    return {
        "target_station_id":    "T",
        "neighbor_station_ids": [f"N{i}" for i in range(K)],
        "distances":            np.tile(dists, (n, 1)),
        "timestamps":           None,
        "target_coord":         None,
        "neighbor_coords":      None,
    }


# ---- IDW ---------------------------------------------------------------------


def test_idw_registered() -> None:
    cls = get_model("idw")
    assert cls.name == "idw"
    assert cls.tier == 2


def test_idw_requires_params() -> None:
    cls = get_model("idw")
    with pytest.raises(KeyError, match="power"):
        cls()
    with pytest.raises(KeyError, match="eps"):
        cls(power=2.0)
    with pytest.raises(ValueError, match="power"):
        cls(power=0.0, eps=1e-9)


def test_idw_predict_uses_inverse_distance() -> None:
    cls = get_model("idw")
    m = cls(power=2.0, eps=0.0).fit(np.zeros((1, 2)), np.zeros(1), _meta(2, 1))
    # 鄰站 N0 距離 1,N1 距離 2 → 權重 1 / 1, 1 / 4 → norm = [4/5, 1/5]
    dists = np.array([1.0, 2.0])
    X = np.array([[10.0, 20.0]])
    out = m.predict(X, _meta(2, 1, dists=dists))
    expected = (10.0 * (1 / 1.0) + 20.0 * (1 / 4.0)) / (1.0 + 0.25)
    np.testing.assert_allclose(out, [expected])


def test_idw_handles_nan() -> None:
    cls = get_model("idw")
    m = cls(power=1.0, eps=0.1).fit(np.zeros((1, 3)), np.zeros(1), _meta(3, 1))
    X = np.array([[np.nan, 5.0, 10.0]])
    dists = np.array([100.0, 100.0, 100.0])
    out = m.predict(X, _meta(3, 1, dists=dists))
    np.testing.assert_allclose(out, [7.5])  # 兩個有效值的等權平均


# ---- CorrWeighted ------------------------------------------------------------


def test_corr_weighted_registered() -> None:
    cls = get_model("corr_weighted")
    assert cls.tier == 2


def test_corr_weighted_requires_min_overlap() -> None:
    cls = get_model("corr_weighted")
    with pytest.raises(KeyError, match="min_overlap"):
        cls()
    with pytest.raises(ValueError):
        cls(min_overlap=0)


def test_corr_weighted_picks_positively_correlated() -> None:
    rng = np.random.default_rng(0)
    n = 200
    y = rng.normal(size=n)
    # N0 與 y 完全正相關;N1 與 y 完全負相關;N2 雜訊
    x0 = y.copy()
    x1 = -y.copy()
    x2 = rng.normal(size=n)
    X_train = np.column_stack([x0, x1, x2])

    cls = get_model("corr_weighted")
    m = cls(min_overlap=10).fit(X_train, y, _meta(3, n))
    # 預測:N0 應主導
    X_test = np.array([[1.0, -1.0, 0.0]])
    out = m.predict(X_test, _meta(3, 1))
    assert out[0] > 0.5  # 因為 N0 ≈ 1.0 且權重高


def test_corr_weighted_drops_negative_corr() -> None:
    """負相關鄰站應被權重 0 排除。"""
    rng = np.random.default_rng(1)
    n = 200
    y = rng.normal(size=n)
    x_neg = -y.copy()
    X = np.column_stack([x_neg])
    cls = get_model("corr_weighted")
    m = cls(min_overlap=10).fit(X, y, _meta(1, n))
    # 所有權重 0 → 預測應為 NaN
    out = m.predict(np.array([[5.0]]), _meta(1, 1))
    assert np.isnan(out[0])


# ---- GaussianKernel ----------------------------------------------------------


def test_gaussian_kernel_registered() -> None:
    cls = get_model("gaussian_kernel")
    assert cls.tier == 2


def test_gaussian_kernel_requires_sigma() -> None:
    cls = get_model("gaussian_kernel")
    with pytest.raises(KeyError, match="sigma"):
        cls()
    with pytest.raises(ValueError):
        cls(sigma=0.0)


def test_gaussian_kernel_weights_closer_higher() -> None:
    cls = get_model("gaussian_kernel")
    m = cls(sigma=100.0).fit(np.zeros((1, 2)), np.zeros(1), _meta(2, 1))
    # 鄰站距離 50 vs 500
    dists = np.array([50.0, 500.0])
    X = np.array([[10.0, 0.0]])
    out = m.predict(X, _meta(2, 1, dists=dists))
    # 近鄰權重壓倒性,結果應接近 10
    assert out[0] > 9.0


# ---- WeightedRidge -----------------------------------------------------------


def test_weighted_ridge_registered() -> None:
    cls = get_model("weighted_ridge")
    assert cls.tier == 2


def test_weighted_ridge_requires_params() -> None:
    cls = get_model("weighted_ridge")
    with pytest.raises(KeyError, match="alpha"):
        cls()
    with pytest.raises(KeyError, match="weight_kind"):
        cls(alpha=1.0)
    with pytest.raises(ValueError, match="weight_kind"):
        cls(alpha=1.0, weight_kind="garbage")
    with pytest.raises(KeyError, match="eps"):
        cls(alpha=1.0, weight_kind="distance")


def test_weighted_ridge_learns_linear_combo() -> None:
    """合成 y = 0.7 x0 + 0.3 x1 + ε,ridge 應該學到接近的權重。"""
    rng = np.random.default_rng(42)
    n = 500
    x0 = rng.normal(size=n)
    x1 = rng.normal(size=n)
    eps = rng.normal(scale=0.05, size=n)
    y = 0.7 * x0 + 0.3 * x1 + eps
    X = np.column_stack([x0, x1])

    cls = get_model("weighted_ridge")
    m = cls(alpha=0.01, weight_kind="none").fit(X, y, _meta(2, n))
    # 預測測試集
    X_test = np.array([[1.0, 0.0], [0.0, 1.0]])
    out = m.predict(X_test, _meta(2, 2))
    np.testing.assert_allclose(out, [0.7, 0.3], atol=0.05)


def test_weighted_ridge_handles_too_few_samples() -> None:
    """樣本少於 K+1 時退回 mean predictor。"""
    cls = get_model("weighted_ridge")
    X = np.ones((3, 10))   # 3 samples, 10 features → underdetermined
    y = np.array([1.0, 2.0, 3.0])
    m = cls(alpha=1.0, weight_kind="none").fit(X, y, _meta(10, 3))
    out = m.predict(np.ones((1, 10)), _meta(10, 1))
    # 應該是 y.mean() = 2.0
    np.testing.assert_allclose(out, [2.0])


def test_weighted_ridge_distance_scaling() -> None:
    """distance scaling 不應讓模型炸掉,且結果合理。"""
    rng = np.random.default_rng(3)
    n = 200
    y = rng.normal(size=n)
    X = np.column_stack([y + rng.normal(scale=0.1, size=n) for _ in range(3)])
    cls = get_model("weighted_ridge")
    m = cls(alpha=0.1, weight_kind="distance", eps=1.0, power=2.0)
    m.fit(X, y, _meta(3, n, dists=np.array([100.0, 500.0, 1000.0])))
    out = m.predict(X[:5], _meta(3, 5, dists=np.array([100.0, 500.0, 1000.0])))
    assert out.shape == (5,)
    assert np.isfinite(out).all()
