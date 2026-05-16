"""GLSImputer 行為測試。"""
from __future__ import annotations

import json

import numpy as np
import pytest

from smart_pole.models import mathematical  # noqa: F401  觸發註冊
from smart_pole.models.registry import get_model


def _meta(K: int, n: int, feature_names: list[str] | None = None) -> dict:
    if feature_names is None:
        feature_names = [f"nb{i}_t" for i in range(K)]
    return {
        "target_station_id":    "T",
        "neighbor_station_ids": [f"N{i}" for i in range(K)],
        "distances":            np.tile(np.linspace(100.0, 1000.0, K), (n, 1)),
        "timestamps":           None,
        "target_coord":         None,
        "neighbor_coords":      None,
        "feature_names":        feature_names,
    }


def test_registered() -> None:
    cls = get_model("gls")
    assert cls.tier == 3
    assert cls.explainability == 9


def test_requires_params() -> None:
    cls = get_model("gls")
    base = {"cov_structure": "iid", "max_iter": 3, "min_train": 50}
    for missing in base:
        bad = {k: v for k, v in base.items() if k != missing}
        with pytest.raises(KeyError, match=missing):
            cls(**bad)


def test_validation_cov_structure() -> None:
    cls = get_model("gls")
    with pytest.raises(ValueError, match="cov_structure"):
        cls(cov_structure="unknown", max_iter=3, min_train=10)


def test_iid_equivalent_to_ols() -> None:
    """cov_structure=iid 應與 sm.OLS 一致(coefs / intercept)。"""
    import statsmodels.api as sm
    rng = np.random.default_rng(42)
    n = 200
    X = rng.normal(size=(n, 3))
    y = X @ np.array([1.5, -0.5, 0.3]) + rng.normal(scale=0.1, size=n)

    cls = get_model("gls")
    m = cls(cov_structure="iid", max_iter=3, min_train=10).fit(X, y, _meta(3, n))
    out = m.predict(np.array([[1.0, 0.0, 0.0]]), _meta(3, 1))
    # 應接近 intercept + 1.5
    ols = sm.OLS(y, sm.add_constant(X)).fit()
    expected = float(ols.params[0] + ols.params[1])
    assert abs(float(out[0]) - expected) < 1e-3


def test_ar1_runs_and_estimates_rho() -> None:
    """AR(1) 殘差訊號:cov_structure='ar1' 應該擬出 rho > 0。"""
    rng = np.random.default_rng(0)
    n = 300
    X = rng.normal(size=(n, 2))
    # 殘差用 AR(1) ρ=0.6 產生
    e = np.zeros(n); rho_true = 0.6
    e[0] = rng.normal()
    for t in range(1, n):
        e[t] = rho_true * e[t - 1] + rng.normal(scale=0.5)
    y = X @ np.array([2.0, -1.0]) + e

    cls = get_model("gls")
    m = cls(cov_structure="ar1", max_iter=5, min_train=10).fit(X, y, _meta(2, n))
    expl = m.explain()
    assert "ar1_rho" in expl
    # 學到的 ρ 應 > 0,不見得剛好 0.6 但應該朝那個方向
    assert expl["ar1_rho"] > 0.2, f"ar1_rho={expl['ar1_rho']}"


def test_fallback_too_few_samples() -> None:
    cls = get_model("gls")
    X = np.ones((3, 10))
    y = np.array([1.0, 2.0, 3.0])
    m = cls(cov_structure="iid", max_iter=3, min_train=50).fit(X, y, _meta(10, 3))
    out = m.predict(np.ones((1, 10)), _meta(10, 1))
    np.testing.assert_allclose(out, [2.0])


def test_explain_serializable() -> None:
    rng = np.random.default_rng(7)
    n = 200
    X = rng.normal(size=(n, 5))
    y = X[:, 0] + rng.normal(scale=0.1, size=n)
    names = ["nb0_t", "nb0_t-1", "nb1_t", "nb1_t-1", "tgt_t-1"]
    cls = get_model("gls")
    m = cls(cov_structure="ar1", max_iter=3, min_train=10).fit(X, y, _meta(5, n, names))
    json.dumps(m.explain())
