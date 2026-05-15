"""連續時段缺失策略(模擬真實 EdiBox 故障)。

對每個 station,隨機挑若干個長度為 ``block_hours`` 的連續區段,把這些區段內
所有「原本有觀測值」的格子標成缺失。目標是讓全表 mask 比例 ≈ ratio。

與 random_point 的差別:殘差會有時間相關;補值模型不能再依賴「同站短窗插補」。
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def make_block_mask(
    values: np.ndarray,
    *,
    ratio: float,
    block_hours: int,
    seed: int,
) -> np.ndarray:
    """產生 block mask,True 表示「人為隱藏」。

    Args:
        values:      shape (T, S),NaN 表原本就缺
        ratio:       (0, 1),目標 mask 比例(對全表有效格子數而言)
        block_hours: 每個 block 的長度(小時),> 0
        seed:        隨機種子(無 default)

    Returns:
        mask: shape (T, S), bool

    策略:逐站獨立,根據站內有效觀測數 n_obs_s 推目標 mask 點數 ~ ratio * n_obs_s,
    再除以 block_hours 得到該站要放幾個 block。隨機抽不重疊的起點,從每個起點
    向後 block_hours 小時內標 True(只對原本有觀測的格)。
    """
    if not 0.0 < ratio < 1.0:
        raise ValueError(f"ratio 需在 (0, 1),收到 {ratio}")
    if values.ndim != 2:
        raise ValueError(f"values 須 2D (T, S),收到 shape={values.shape}")
    if block_hours <= 0:
        raise ValueError(f"block_hours 需 > 0,收到 {block_hours}")

    rng = np.random.default_rng(seed)
    T, S = values.shape
    observed = np.isfinite(values)
    mask = np.zeros(values.shape, dtype=bool)

    n_obs_total = int(observed.sum())
    target_total = int(round(n_obs_total * ratio))

    for s in range(S):
        obs_s = observed[:, s]
        n_obs_s = int(obs_s.sum())
        if n_obs_s == 0:
            continue
        target_s = int(round(n_obs_s * ratio))
        if target_s == 0:
            continue
        # 期望每個 block 中位數命中 block_hours * (n_obs_s / T) 個觀測格;
        # 用實際密度估,避免 sparse 站只放一兩個 block
        density = n_obs_s / max(T, 1)
        per_block_hits = max(1.0, block_hours * density)
        n_blocks = max(1, int(round(target_s / per_block_hits)))

        # 起點候選:0..T-block_hours,避免越界。允許重疊發生(後面截斷處理)
        max_start = max(1, T - block_hours + 1)
        starts = rng.choice(max_start, size=min(n_blocks, max_start), replace=False)
        for st in starts:
            ed = min(st + block_hours, T)
            rng_slice = slice(st, ed)
            cells = obs_s[rng_slice]
            mask[rng_slice, s] |= cells

    # 控制總量:若超過 target_total 太多,隨機 unmask 多出來的;若不足也不再追加
    # (避免把 block 切碎反而像 random)
    n_masked = int(mask.sum())
    if n_masked > target_total * 1.25 and target_total > 0:
        extra = n_masked - target_total
        flat_idx = np.flatnonzero(mask.ravel())
        drop = rng.choice(flat_idx, size=extra, replace=False)
        mask.ravel()[drop] = False
        n_masked = int(mask.sum())

    logger.info(
        "block mask:T=%d S=%d, block_hours=%d, 目標 ≈ %d (ratio=%.4f, seed=%d), 實際 %d (%.4f)",
        T, S, block_hours, target_total, ratio, seed, n_masked,
        n_masked / max(n_obs_total, 1),
    )
    return mask
