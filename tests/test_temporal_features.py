"""TemporalFeatureBuilder 契約 + 行為測試。

Stream 0 驗收條件:``lags=[] and rolling=[]`` 退化成 Phase 2 行為(X 不變)。
"""
from __future__ import annotations

import numpy as np
import pytest

from smart_pole.features.temporal import (
    TemporalFeatureBuilder,
    _rolling_mean_nan,
    _shift_with_nan_pad,
)


# ---- 邊界 / 驗證 -------------------------------------------------------------


def test_rejects_zero_or_negative_lag() -> None:
    with pytest.raises(ValueError, match="lags"):
        TemporalFeatureBuilder(lags=[0], rolling=[])
    with pytest.raises(ValueError, match="lags"):
        TemporalFeatureBuilder(lags=[-1, 1], rolling=[])


def test_rejects_zero_or_negative_window() -> None:
    with pytest.raises(ValueError, match="rolling"):
        TemporalFeatureBuilder(lags=[], rolling=[0])


def test_dedup_lags_and_rolling() -> None:
    b = TemporalFeatureBuilder(lags=[1, 1, 24, 24], rolling=[3, 3])
    assert b.lags == [1, 24]
    assert b.rolling == [3]


def test_rejects_non_list() -> None:
    with pytest.raises(TypeError):
        TemporalFeatureBuilder(lags=(1, 2), rolling=[])  # type: ignore[arg-type]


# ---- identity (Phase 2 等價)--------------------------------------------------


def test_identity_when_both_empty() -> None:
    b = TemporalFeatureBuilder(lags=[], rolling=[])
    assert b.is_identity()
    X = np.arange(20).reshape(5, 4).astype(np.float64)
    X_aug, names = b.build(X)
    np.testing.assert_array_equal(X_aug, X)
    assert names == [f"nb{k}_t" for k in range(4)]
    # 確認沒額外配記憶體(同 shape)
    assert X_aug.shape == X.shape


def test_identity_ignores_target_history() -> None:
    """lags=[] 時 target_history 可選且應被忽略。"""
    b = TemporalFeatureBuilder(lags=[], rolling=[])
    X = np.ones((10, 3))
    X1, _ = b.build(X, target_history=None)
    X2, _ = b.build(X, target_history=np.arange(10).astype(float))
    np.testing.assert_array_equal(X1, X2)


# ---- shape -------------------------------------------------------------------


def test_shape_with_lags_only() -> None:
    b = TemporalFeatureBuilder(lags=[1, 2, 3], rolling=[])
    T, K = 20, 4
    X = np.ones((T, K))
    target = np.zeros(T)
    X_aug, names = b.build(X, target_history=target)
    # K + K*L + L = 4 + 12 + 3 = 19
    assert X_aug.shape == (T, K * (1 + 3) + 3)
    assert len(names) == X_aug.shape[1]


def test_shape_with_rolling_only() -> None:
    b = TemporalFeatureBuilder(lags=[], rolling=[3, 6])
    T, K = 30, 5
    X = np.ones((T, K))
    X_aug, names = b.build(X)
    # K + K*R + 0 = 5 + 10 = 15
    assert X_aug.shape == (T, K * (1 + 2))
    assert len(names) == X_aug.shape[1]


def test_shape_full() -> None:
    b = TemporalFeatureBuilder(lags=[1, 24], rolling=[3, 6, 24])
    T, K = 100, 10
    X_aug, _ = b.build(np.ones((T, K)), target_history=np.zeros(T))
    # K*(1+L+R) + L = 10*6 + 2 = 62
    assert X_aug.shape == (T, K * (1 + 2 + 3) + 2)


def test_requires_target_history_when_lags_nonempty() -> None:
    b = TemporalFeatureBuilder(lags=[1], rolling=[])
    with pytest.raises(ValueError, match="target_history"):
        b.build(np.ones((10, 3)))


def test_target_history_shape_check() -> None:
    b = TemporalFeatureBuilder(lags=[1], rolling=[])
    with pytest.raises(ValueError, match="shape"):
        b.build(np.ones((10, 3)), target_history=np.ones(11))


# ---- 數值正確性 --------------------------------------------------------------


def test_neighbor_current_block_is_X_itself() -> None:
    """X_aug 的前 K column 必須 == X。"""
    b = TemporalFeatureBuilder(lags=[1, 6], rolling=[3])
    X = np.arange(40).reshape(10, 4).astype(np.float64)
    target = np.zeros(10)
    X_aug, _ = b.build(X, target_history=target)
    np.testing.assert_array_equal(X_aug[:, :4], X)


def test_lag_column_is_shifted_value() -> None:
    """lag=2 的 X_aug column == X 沿 axis 0 推 2 步。"""
    b = TemporalFeatureBuilder(lags=[2], rolling=[])
    X = np.arange(20).reshape(10, 2).astype(np.float64)
    target = np.zeros(10)
    X_aug, names = b.build(X, target_history=target)
    # col 0-1: current; col 2-3: lag=2 neighbor;col 4: tgt_t-2
    assert names[2:4] == ["nb0_t-2", "nb1_t-2"]
    # 前兩 row 應 NaN
    assert np.isnan(X_aug[:2, 2:4]).all()
    # 第 2 row 起 = X 第 0 row
    np.testing.assert_array_equal(X_aug[2:, 2:4], X[:-2])


def test_rolling_column_window_mean() -> None:
    """rolling=3 column == 該 row 前 3 hr 的均值(含當下)。"""
    b = TemporalFeatureBuilder(lags=[], rolling=[3])
    X = np.arange(10).reshape(10, 1).astype(np.float64)
    X_aug, names = b.build(X)
    assert names == ["nb0_t", "nb0_roll3"]
    roll = X_aug[:, 1]
    # 前 2 row NaN
    assert np.isnan(roll[:2]).all()
    # row 2 起 = mean of (i-2, i-1, i)
    expected = np.array([(i - 2 + i - 1 + i) / 3.0 for i in range(2, 10)])
    np.testing.assert_allclose(roll[2:], expected)


def test_target_history_lag_column() -> None:
    b = TemporalFeatureBuilder(lags=[1, 3], rolling=[])
    T, K = 10, 2
    X = np.zeros((T, K))
    target = np.arange(T).astype(np.float64)
    X_aug, names = b.build(X, target_history=target)
    # 最後 2 column 是 tgt_t-1, tgt_t-3
    assert names[-2:] == ["tgt_t-1", "tgt_t-3"]
    # lag=1
    np.testing.assert_array_equal(X_aug[1:, -2], target[:-1])
    assert np.isnan(X_aug[0, -2])
    # lag=3
    np.testing.assert_array_equal(X_aug[3:, -1], target[:-3])
    assert np.isnan(X_aug[:3, -1]).all()


def test_lag_propagates_existing_nan() -> None:
    """X 內已經有的 NaN,shift 後仍是 NaN。"""
    b = TemporalFeatureBuilder(lags=[1], rolling=[])
    X = np.array([[1.0, 2.0],
                  [3.0, np.nan],
                  [5.0, 6.0]])
    target = np.zeros(3)
    X_aug, _ = b.build(X, target_history=target)
    # col 2 = lag=1 of col 0 (nb0_t-1):row 0 NaN, row 1 = 1, row 2 = 3
    assert np.isnan(X_aug[0, 2])
    assert X_aug[1, 2] == 1.0
    assert X_aug[2, 2] == 3.0
    # col 3 = lag=1 of col 1 (nb1_t-1):row 0 NaN, row 1 = 2, row 2 = NaN(從 X[1,1])
    assert np.isnan(X_aug[0, 3])
    assert X_aug[1, 3] == 2.0
    assert np.isnan(X_aug[2, 3])


# ---- helpers ----------------------------------------------------------------


def test_shift_helper_rejects_zero() -> None:
    with pytest.raises(ValueError):
        _shift_with_nan_pad(np.zeros(5), 0)


def test_rolling_helper_rejects_zero() -> None:
    with pytest.raises(ValueError):
        _rolling_mean_nan(np.zeros(5), 0)


def test_n_total_columns_matches_output() -> None:
    b = TemporalFeatureBuilder(lags=[1, 24], rolling=[6])
    K = 7
    X = np.ones((50, K))
    X_aug, _ = b.build(X, target_history=np.zeros(50))
    assert X_aug.shape[1] == b.n_total_columns(K)
