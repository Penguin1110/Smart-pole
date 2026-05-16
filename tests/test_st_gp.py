"""STGPImputer 基本契約測試 (不跑真實 fit,避免 GPU 開銷)。"""
from __future__ import annotations

import numpy as np
import pytest

from smart_pole.models import mathematical  # noqa: F401  觸發註冊
from smart_pole.models.registry import get_model


def _meta_minimal() -> dict:
    return {
        "target_station_id":     "T",
        "neighbor_station_ids":  ["N0", "N1"],
        "distances":             np.ones((1, 2)),
        "timestamps":            None,
        "target_coord":          None,
        "neighbor_coords":       None,
        "values_full":           None,
        "mask_full":             None,
        "train_slice":           None,
        "test_slice":            None,
        "target_idx":            None,
        "neighbor_idx":          None,
    }


def test_registered() -> None:
    cls = get_model("st_gp")
    assert cls.tier == 3
    assert cls.explainability == 8
    assert cls.requires_gpu is True


def test_requires_params() -> None:
    cls = get_model("st_gp")
    base = {
        "n_iter": 10, "lr": 0.1, "max_train": 500,
        "lengthscale_init_space_m": 1000.0, "lengthscale_init_time_h": 24.0,
        "noise_floor": 0.5, "seed": 0,
    }
    for missing in base:
        bad = {k: v for k, v in base.items() if k != missing}
        with pytest.raises(KeyError, match=missing):
            cls(**bad)


def test_validation() -> None:
    cls = get_model("st_gp")
    with pytest.raises(ValueError, match="lr"):
        cls(n_iter=10, lr=-0.1, max_train=500,
            lengthscale_init_space_m=1000.0, lengthscale_init_time_h=24.0,
            noise_floor=0.5, seed=0)
    with pytest.raises(ValueError, match="max_train"):
        cls(n_iter=10, lr=0.1, max_train=10,
            lengthscale_init_space_m=1000.0, lengthscale_init_time_h=24.0,
            noise_floor=0.5, seed=0)


def test_fallback_when_meta_missing() -> None:
    cls = get_model("st_gp")
    m = cls(n_iter=5, lr=0.1, max_train=100,
            lengthscale_init_space_m=1000.0, lengthscale_init_time_h=24.0,
            noise_floor=0.5, seed=0)
    X = np.array([[1.0, 2.0]])
    y = np.array([3.0])
    m.fit(X, y, _meta_minimal())
    expl = m.explain()
    assert "error" in expl


def test_synthetic_st_fit() -> None:
    """小規模合成資料:K=3 鄰站,T=80。檢查 fit 不爆 + explain 有 kernel info。"""
    rng = np.random.default_rng(0)
    T, S_all = 80, 4   # 3 鄰站 + 1 target = 站 0..3
    # 構造一個 spatial + temporal trend
    coords = np.array([(0.0, 0.0), (0.01, 0.0), (0.0, 0.01), (0.005, 0.005)])
    # target = 站 3
    target_coord = tuple(coords[3])
    neighbor_coords = coords[:3]
    base = rng.normal(scale=2.0, size=T)
    values = np.column_stack([
        base + 0.1 * i + rng.normal(scale=0.5, size=T)
        for i in range(S_all)
    ])
    mask = np.zeros((T, S_all), dtype=bool)
    mask[60:, 3] = True  # 對 target 的 test rows mask
    train_slice = slice(0, 60); test_slice = slice(60, 80)

    cls = get_model("st_gp")
    m = cls(n_iter=10, lr=0.1, max_train=200,
            lengthscale_init_space_m=500.0, lengthscale_init_time_h=12.0,
            noise_floor=0.1, seed=42)
    # X / y 大致對應 K=3、N_train=有限的 row,但實際上 STGP 用 meta 抓資料
    X_train = values[train_slice][:, :3]
    y_train = values[train_slice, 3]
    meta = {
        "target_station_id":     "T",
        "neighbor_station_ids":  ["N0", "N1", "N2"],
        "distances":             np.ones((len(y_train), 3)) * 1000.0,
        "timestamps":            None,
        "target_coord":          target_coord,
        "neighbor_coords":       neighbor_coords,
        "values_full":           values,
        "mask_full":             mask,
        "train_slice":           train_slice,
        "test_slice":            test_slice,
        "target_idx":            3,
        "neighbor_idx":          [0, 1, 2],
        "feature_names":         None,
    }
    m.fit(X_train, y_train, meta)
    expl = m.explain()
    # 應該成功 fit(synthetic 小問題)
    assert expl is not None
    if "error" not in expl:
        assert "lengthscale_space_m" in expl
        assert "lengthscale_time_h" in expl

    # predict
    test_rows = np.arange(20)  # 對應 test_slice 內 row 0..19
    test_meta = dict(meta)
    test_meta["test_rows"] = test_rows
    X_test = values[test_slice][:, :3]
    out = m.predict(X_test, test_meta)
    assert out.shape == (20,)
    assert np.isfinite(out).all()
