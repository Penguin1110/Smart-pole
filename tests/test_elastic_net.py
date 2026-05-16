"""ElasticNetImputer 行為測試。"""
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
    cls = get_model("elastic_net")
    assert cls.tier == 3
    assert cls.explainability == 10


def test_requires_params() -> None:
    cls = get_model("elastic_net")
    base = {"alpha": 1.0, "l1_ratio": 0.5, "max_iter": 1000, "min_train": 50}
    for missing in base:
        bad = {k: v for k, v in base.items() if k != missing}
        with pytest.raises(KeyError, match=missing):
            cls(**bad)


def test_validation() -> None:
    cls = get_model("elastic_net")
    with pytest.raises(ValueError, match="l1_ratio"):
        cls(alpha=1.0, l1_ratio=1.5, max_iter=100, min_train=10)


def test_l1_picks_sparse_features() -> None:
    """y = 2 * x0 + 噪音;ElasticNet 應該把 x1..x4 壓 0,保留 x0。"""
    rng = np.random.default_rng(42)
    n = 500
    x0 = rng.normal(size=n)
    noise = rng.normal(scale=0.5, size=(n, 4))
    X = np.column_stack([x0, noise])
    y = 2.0 * x0 + rng.normal(scale=0.1, size=n)

    cls = get_model("elastic_net")
    m = cls(alpha=0.1, l1_ratio=0.9, max_iter=5000, min_train=10)
    m.fit(X, y, _meta(5, n))
    expl = m.explain()
    # 至少應保留 x0,大部分其他應被壓 0
    assert expl["n_features_kept"] >= 1
    assert expl["n_features_kept"] <= 3  # 不該保留全部
    # x0 是 top 特徵
    top1_name, top1_coef = expl["kept_features"][0]
    assert top1_name == "nb0_t"
    assert abs(top1_coef - 2.0) < 0.2


def test_fallback_too_few_samples() -> None:
    cls = get_model("elastic_net")
    X = np.ones((3, 10))
    y = np.array([1.0, 2.0, 3.0])
    m = cls(alpha=1.0, l1_ratio=0.5, max_iter=100, min_train=50).fit(X, y, _meta(10, 3))
    out = m.predict(np.ones((1, 10)), _meta(10, 1))
    np.testing.assert_allclose(out, [2.0])


def test_explain_json_serializable() -> None:
    rng = np.random.default_rng(0)
    n = 200
    X = rng.normal(size=(n, 5))
    y = X[:, 0] + rng.normal(scale=0.1, size=n)
    names = ["nb0_t", "nb0_t-1", "nb1_t", "nb1_t-1", "tgt_t-1"]
    cls = get_model("elastic_net")
    m = cls(alpha=0.01, l1_ratio=0.5, max_iter=2000, min_train=10).fit(X, y, _meta(5, n, names))
    blob = json.dumps(m.explain())
    assert "kept_features" in blob
    assert "group_n_kept" in blob
