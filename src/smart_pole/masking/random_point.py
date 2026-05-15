"""隨機點缺失策略:在 (T, S) 矩陣中,從原本有觀測值的位置隨機抽出比例 ``ratio``
標成「缺失」,當作補值任務的 ground truth 來源。

原本就是 NaN(感測器掛掉、訊號斷)不算進來——只 mask 有值的點。
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def make_random_point_mask(
    values: np.ndarray,
    *,
    ratio: float,
    seed: int,
) -> np.ndarray:
    """產生 boolean mask,True 表示「人為隱藏」這格。

    Args:
        values: shape (T, S),NaN 代表原本就缺
        ratio:  0 < ratio < 1,在有觀測值的位置中隨機選這麼多比例
        seed:   隨機種子(CLAUDE.md 規定:無 default seed)

    Returns:
        mask: shape (T, S),bool。True 處應在訓練/評估時當作未知。
    """
    if not 0.0 < ratio < 1.0:
        raise ValueError(f"ratio 需在 (0, 1) 之間,收到 {ratio}")
    if values.ndim != 2:
        raise ValueError(f"values 須為 2D (T, S),收到 shape={values.shape}")

    rng = np.random.default_rng(seed)
    observed = np.isfinite(values)
    n_observed = int(observed.sum())
    n_mask = int(round(n_observed * ratio))

    obs_idx = np.flatnonzero(observed.ravel())
    chosen = rng.choice(obs_idx, size=n_mask, replace=False)

    mask = np.zeros(values.shape, dtype=bool)
    mask.ravel()[chosen] = True

    logger.info(
        "random_point mask:在 %d 個有效格中抽 %d 個(ratio=%.4f, seed=%d)",
        n_observed, n_mask, ratio, seed,
    )
    return mask
