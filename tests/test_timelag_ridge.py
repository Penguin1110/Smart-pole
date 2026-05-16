"""TimeLagRidgeImputer 行為測試。"""
from __future__ import annotations

import json

import numpy as np
import pytest

from smart_pole.models import mathematical  # noqa: F401  觸發註冊
from smart_pole.models.registry import get_model


def _meta(K_features: int, n: int, feature_names: list[str] | None = None) -> dict:
    if feature_names is None:
        feature_names = [f"nb{i}_t" for i in range(K_features)]
    return {
        "target_station_id":    "T",
        "neighbor_station_ids": [f"N{i}" for i in range(K_features)],
        "distances":            np.tile(np.linspace(100.0, 1000.0, K_features), (n, 1)),
        "timestamps":           None,
        "target_coord":         None,
        "neighbor_coords":      None,
        "feature_names":        feature_names,
    }


def test_registered() -> None:
    cls = get_model("timelag_ridge")
    assert cls.tier == 3
    assert cls.explainability == 10


def test_requires_params() -> None:
    cls = get_model("timelag_ridge")
    with pytest.raises(KeyError, match="alpha"):
        cls()
    with pytest.raises(KeyError, match="min_train"):
        cls(alpha=1.0)


def test_validation() -> None:
    cls = get_model("timelag_ridge")
    with pytest.raises(ValueError, match="alpha"):
        cls(alpha=-1.0, min_train=10)
    with pytest.raises(ValueError, match="min_train"):
        cls(alpha=1.0, min_train=0)


def test_learns_linear_combo() -> None:
    """y = 0.5 nb0 + 0.3 nb1 + 0.2 nb2 + noise → ridge 應該學到接近的權重。"""
    rng = np.random.default_rng(42)
    n = 500
    x0, x1, x2 = rng.normal(size=n), rng.normal(size=n), rng.normal(size=n)
    y = 0.5 * x0 + 0.3 * x1 + 0.2 * x2 + rng.normal(scale=0.05, size=n)
    X = np.column_stack([x0, x1, x2])

    cls = get_model("timelag_ridge")
    m = cls(alpha=0.01, min_train=10).fit(X, y, _meta(3, n))
    out = m.predict(np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]),
                    _meta(3, 3))
    np.testing.assert_allclose(out, [0.5, 0.3, 0.2], atol=0.1)


def test_fallback_too_few_samples() -> None:
    cls = get_model("timelag_ridge")
    X = np.ones((3, 10))
    y = np.array([1.0, 2.0, 3.0])
    m = cls(alpha=1.0, min_train=50).fit(X, y, _meta(10, 3))
    out = m.predict(np.ones((1, 10)), _meta(10, 1))
    # mean = 2
    np.testing.assert_allclose(out, [2.0])


def test_nan_in_predict_uses_train_col_mean() -> None:
    """X_test 有 NaN 時應該用 train col mean 補,而不是炸掉。"""
    rng = np.random.default_rng(0)
    n = 200
    X = rng.normal(loc=5.0, size=(n, 3))
    y = X.sum(axis=1) + rng.normal(scale=0.1, size=n)
    cls = get_model("timelag_ridge")
    m = cls(alpha=0.1, min_train=10).fit(X, y, _meta(3, n))
    # 預測時放 NaN
    X_test = np.array([[10.0, np.nan, 10.0]])
    out = m.predict(X_test, _meta(3, 1))
    # 應該不是 NaN,落在合理範圍
    assert np.isfinite(out).all()
    assert 0 <= out[0] <= 500


def test_predict_clips_to_physical_range() -> None:
    """極端輸入造成的爆炸預測應該被 clip 到 [0, 500]。"""
    cls = get_model("timelag_ridge")
    rng = np.random.default_rng(0)
    n = 50
    X = rng.normal(size=(n, 3))
    y = rng.normal(size=n)
    m = cls(alpha=0.001, min_train=10).fit(X, y, _meta(3, n))
    # 餵極大值,看 predict 會不會被 clip
    out = m.predict(np.array([[1e6, 1e6, 1e6]]), _meta(3, 1))
    assert out[0] <= 500.0 and out[0] >= 0.0


def test_explain_json_serializable_and_has_top_features() -> None:
    rng = np.random.default_rng(1)
    n = 200
    X = rng.normal(size=(n, 5))
    y = X[:, 0] * 2 + X[:, 2] * -1 + rng.normal(scale=0.1, size=n)
    names = ["nb0_t", "nb0_t-1", "nb1_t", "nb1_t-1", "tgt_t-1"]
    cls = get_model("timelag_ridge")
    m = cls(alpha=0.01, min_train=10).fit(X, y, _meta(5, n, names))
    expl = m.explain()
    blob = json.dumps(expl)
    assert "top_5_features" in expl
    # top 1 應該是 nb0_t(coef ≈ 2.0)
    top1_name, top1_coef = expl["top_5_features"][0]
    assert top1_name == "nb0_t"
    assert abs(top1_coef - 2.0) < 0.1
