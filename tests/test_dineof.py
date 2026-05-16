"""DINEOFImputer 行為測試。"""
from __future__ import annotations

import json

import numpy as np
import pytest

from smart_pole.models import mathematical  # noqa: F401  觸發註冊
from smart_pole.models.mathematical.dineof import _IMPUTE_CACHE, _dineof_impute
from smart_pole.models.registry import get_model


def test_registered() -> None:
    cls = get_model("dineof")
    assert cls.tier == 3
    assert cls.explainability == 9


def test_requires_params() -> None:
    cls = get_model("dineof")
    base = {"n_modes": 5, "max_iter": 30, "tol": 1e-4}
    for missing in base:
        bad = {k: v for k, v in base.items() if k != missing}
        with pytest.raises(KeyError, match=missing):
            cls(**bad)


def test_dineof_impute_recovers_low_rank() -> None:
    """造 rank-2 矩陣 + 20% 隨機 mask,DINEOF 應該幾乎完全 recover。"""
    rng = np.random.default_rng(0)
    T, S = 50, 30
    U = rng.normal(size=(T, 2))
    V = rng.normal(size=(S, 2))
    truth = U @ V.T + rng.normal(scale=0.05, size=(T, S))

    mask = rng.random((T, S)) < 0.2
    obs = truth.copy()
    # NaN 給原本就「沒觀測」的格子(我們的演算法要 NaN | mask 並集)
    # 這個測試裡所有格子都觀測,只有 mask
    imputed, expl = _dineof_impute(obs, mask, n_modes=2, max_iter=50, tol=1e-6)
    err = np.abs(imputed[mask] - truth[mask])
    assert err.mean() < 0.3, f"DINEOF 復原 MAE = {err.mean()},應該 < 0.3"
    assert expl["iters_used"] >= 1


def test_module_cache_avoids_recompute() -> None:
    """同一份 (values, mask) 兩次 fit 應只計算一次 SVD。"""
    rng = np.random.default_rng(1)
    T, S = 40, 20
    values = rng.normal(size=(T, S))
    mask = rng.random((T, S)) < 0.2

    _IMPUTE_CACHE.clear()
    cls = get_model("dineof")
    m1 = cls(n_modes=3, max_iter=10, tol=1e-4)
    m2 = cls(n_modes=3, max_iter=10, tol=1e-4)

    meta = {
        "values_full": values, "mask_full": mask,
        "train_slice": slice(0, 30), "test_slice": slice(30, 40),
        "target_idx": 0,
    }
    X_dummy = np.zeros((1, 1))
    y_dummy = np.zeros(1)
    m1.fit(X_dummy, y_dummy, meta)
    assert len(_IMPUTE_CACHE) == 1
    m2.fit(X_dummy, y_dummy, meta)
    assert len(_IMPUTE_CACHE) == 1   # 沒新增

    _IMPUTE_CACHE.clear()


def test_predict_reads_imputed() -> None:
    rng = np.random.default_rng(2)
    T, S = 60, 25
    values = rng.normal(size=(T, S))
    mask = np.zeros((T, S), dtype=bool)
    mask[40:50, 5] = True  # 目標站 5,test rows 40..49 被 mask

    _IMPUTE_CACHE.clear()
    cls = get_model("dineof")
    m = cls(n_modes=3, max_iter=10, tol=1e-4)
    meta = {
        "values_full": values, "mask_full": mask,
        "train_slice": slice(0, 40), "test_slice": slice(40, 60),
        "target_idx": 5,
    }
    m.fit(np.zeros((1, 1)), np.zeros(1), meta)
    test_meta = dict(meta)
    test_meta["test_rows"] = np.arange(10)  # 對應 row 40..49
    out = m.predict(np.zeros((10, 1)), test_meta)
    assert out.shape == (10,)
    assert np.isfinite(out).all()
    _IMPUTE_CACHE.clear()


def test_explain_serializable() -> None:
    rng = np.random.default_rng(3)
    T, S = 30, 15
    values = rng.normal(size=(T, S))
    mask = rng.random((T, S)) < 0.2

    _IMPUTE_CACHE.clear()
    cls = get_model("dineof")
    m = cls(n_modes=3, max_iter=5, tol=1e-4)
    meta = {"values_full": values, "mask_full": mask,
            "train_slice": slice(0, 20), "test_slice": slice(20, 30),
            "target_idx": 0}
    m.fit(np.zeros((1, 1)), np.zeros(1), meta)
    json.dumps(m.explain())
    _IMPUTE_CACHE.clear()
