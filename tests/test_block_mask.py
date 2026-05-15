"""block masking 行為測試。"""
from __future__ import annotations

import numpy as np
import pytest

from smart_pole.masking.block import make_block_mask


def test_block_mask_shape_and_dtype() -> None:
    values = np.ones((100, 20))
    mask = make_block_mask(values, ratio=0.2, block_hours=6, seed=0)
    assert mask.shape == values.shape
    assert mask.dtype == bool


def test_block_mask_only_on_observed_cells() -> None:
    rng = np.random.default_rng(0)
    values = rng.normal(size=(200, 30))
    values[rng.random(values.shape) < 0.1] = np.nan
    mask = make_block_mask(values, ratio=0.2, block_hours=4, seed=42)
    # 不應在原本就是 NaN 的格子上 mask
    assert not (mask & ~np.isfinite(values)).any()


def test_block_mask_ratio_approx() -> None:
    rng = np.random.default_rng(0)
    values = rng.normal(size=(500, 50))
    mask = make_block_mask(values, ratio=0.2, block_hours=6, seed=0)
    n_obs = int(np.isfinite(values).sum())
    actual = mask.sum() / n_obs
    # block 因為連續、會碰到邊界——容差放寬到 ±50%(內部有 25% 削減,實際往下偏)
    assert 0.05 < actual < 0.30


def test_block_mask_contains_contiguous_runs() -> None:
    """每個站至少出現一段 ≥ 2 小時的連續 True——驗證 block 性質。"""
    values = np.ones((300, 5))
    mask = make_block_mask(values, ratio=0.3, block_hours=10, seed=7)
    found_long_run = False
    for s in range(values.shape[1]):
        col = mask[:, s].astype(np.int8)
        # 算連續 True 的最大長度
        max_run = 0
        cur = 0
        for v in col:
            cur = cur + 1 if v else 0
            if cur > max_run:
                max_run = cur
        if max_run >= 2:
            found_long_run = True
            break
    assert found_long_run, "block masking 應產生連續 True 區段"


def test_block_mask_seed_deterministic() -> None:
    values = np.ones((100, 10))
    m1 = make_block_mask(values, ratio=0.2, block_hours=4, seed=1)
    m2 = make_block_mask(values, ratio=0.2, block_hours=4, seed=1)
    m3 = make_block_mask(values, ratio=0.2, block_hours=4, seed=2)
    np.testing.assert_array_equal(m1, m2)
    assert not np.array_equal(m1, m3)


def test_block_mask_rejects_bad_args() -> None:
    values = np.ones((50, 5))
    with pytest.raises(ValueError):
        make_block_mask(values, ratio=0.0, block_hours=4, seed=0)
    with pytest.raises(ValueError):
        make_block_mask(values, ratio=1.0, block_hours=4, seed=0)
    with pytest.raises(ValueError):
        make_block_mask(values, ratio=0.2, block_hours=0, seed=0)
