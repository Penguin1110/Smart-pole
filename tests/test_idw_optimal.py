"""IDWOptimalImputer 行為測試。"""
from __future__ import annotations

import numpy as np
import pytest

from smart_pole.models import mathematical  # noqa: F401  觸發註冊
from smart_pole.models.registry import get_model


def _meta(K: int, n: int, dists: np.ndarray) -> dict:
    return {
        "target_station_id":    "T",
        "neighbor_station_ids": [f"N{i}" for i in range(K)],
        "distances":            np.tile(dists, (n, 1)),
        "timestamps":           None,
        "target_coord":         None,
        "neighbor_coords":      None,
    }


def test_idw_optimal_registered() -> None:
    cls = get_model("idw_optimal")
    assert cls.tier == 3
    assert cls.explainability == 10


def test_requires_params() -> None:
    cls = get_model("idw_optimal")
    base = {"power_grid": [1.0, 2.0], "eps": 1.0, "cv_folds": 3, "cv_seed": 0}
    for missing in base:
        bad = {k: v for k, v in base.items() if k != missing}
        with pytest.raises(KeyError, match=missing):
            cls(**bad)


def test_validation_bad_power() -> None:
    cls = get_model("idw_optimal")
    with pytest.raises(ValueError, match="power_grid"):
        cls(power_grid=[], eps=1.0, cv_folds=3, cv_seed=0)
    with pytest.raises(ValueError, match="power_grid"):
        cls(power_grid=[-1.0], eps=1.0, cv_folds=3, cv_seed=0)


def test_cv_picks_lower_mae_power() -> None:
    """合成資料中 power=1 的 IDW 預測比 power=10 接近真值;CV 應該挑 power=1。"""
    rng = np.random.default_rng(0)
    K = 5
    d = np.array([100.0, 200.0, 300.0, 400.0, 500.0])
    n = 200
    # y 與最近兩個鄰站線性相關(IDW power=1 接近最優)
    X = rng.normal(loc=10.0, scale=2.0, size=(n, K))
    # 構造 y ≈ IDW(X, d, power=1) + noise
    w_true = 1.0 / d
    y_true_signal = (X * w_true).sum(axis=1) / w_true.sum()
    y = y_true_signal + rng.normal(scale=0.1, size=n)

    cls = get_model("idw_optimal")
    m = cls(power_grid=[0.5, 1.0, 2.0, 5.0, 10.0], eps=1.0, cv_folds=5, cv_seed=42)
    m.fit(X, y, _meta(K, n, d))
    exp = m.explain()
    # CV MAE 應在 power=1 附近最低
    cv = exp["cv_mae_per_power"]
    print(cv)
    assert exp["power_chosen"] in (0.5, 1.0, 2.0), f'挑到 {exp["power_chosen"]}'


def test_predict_uses_chosen_power() -> None:
    cls = get_model("idw_optimal")
    K = 3
    d = np.array([1.0, 2.0, 3.0])
    rng = np.random.default_rng(1)
    n = 100
    X = rng.normal(size=(n, K))
    y = rng.normal(size=n)
    m = cls(power_grid=[1.0], eps=0.0, cv_folds=2, cv_seed=0).fit(X, y, _meta(K, n, d))
    # 唯一候選 → 一定挑 1.0
    assert m._power_chosen == 1.0
    # predict 與 hand-compute 一致
    X_t = np.array([[3.0, 6.0, 9.0]])
    out = m.predict(X_t, _meta(K, 1, d))
    w = 1.0 / d
    expected = (X_t[0] * w).sum() / w.sum()
    np.testing.assert_allclose(out, [expected])


def test_explain_is_json_serializable() -> None:
    import json
    cls = get_model("idw_optimal")
    K, n = 4, 150
    d = np.array([1.0, 2.0, 3.0, 4.0])
    rng = np.random.default_rng(2)
    X = rng.normal(size=(n, K))
    y = rng.normal(size=n)
    m = cls(power_grid=[1.0, 2.0, 3.0], eps=1.0, cv_folds=3, cv_seed=0).fit(X, y, _meta(K, n, d))
    blob = json.dumps(m.explain())
    assert "power_chosen" in blob
    assert "cv_mae_per_power" in blob


def test_tier3_low_explainability_rejected() -> None:
    """sanity:registry 守門員真的會擋 explainability < 8 的 tier 3 模型。"""
    from smart_pole.models.base import BaseImputer
    from smart_pole.models.registry import register

    class _Bad(BaseImputer):
        name = "_t3_low_expl"
        tier = 3
        explainability = 5
        def fit(self, X, y, meta): return self
        def predict(self, X, meta): return np.zeros(len(X))

    with pytest.raises(ValueError, match="explainability"):
        register(_Bad)
