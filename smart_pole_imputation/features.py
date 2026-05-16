"""TemporalFeatureBuilder — 把 (T, K) 鄰站時序攤成 Phase 3 線性 / GLS 模型的特徵矩陣。

Column layout(K 鄰站、L = len(lags)、R = len(rolling)):

    cols [0,              K)              ← 鄰站當下值 t
    cols [K,              K*(1+L))        ← 鄰站滯後 t-lag_i
    cols [K*(1+L),        K*(1+L+R))      ← 鄰站滾動 mean[t-w+1, t]
    cols [K*(1+L+R),      K*(1+L+R)+L)    ← target 自己的滯後 t-lag_i

對應 shape:``(T, K*(1+L+R) + L)``。

邊界 row(t < max(lag) 或 t < max(rolling)-1)在對應的延伸 column 會是 NaN。
target 只用「嚴格在 t 之前」的滯後 column,避免任何形式的 leakage。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _shift_with_nan_pad(arr: np.ndarray, lag: int) -> np.ndarray:
    if lag < 1:
        raise ValueError(f"lag 必須 ≥ 1,收到 {lag}")
    out = np.full_like(arr, np.nan, dtype=np.float64)
    if lag < arr.shape[0]:
        out[lag:] = arr[:-lag]
    return out


def _rolling_mean_nan(X: np.ndarray, window: int) -> np.ndarray:
    if window < 1:
        raise ValueError(f"window 必須 ≥ 1,收到 {window}")
    if X.ndim == 1:
        df = pd.Series(X)
        out = np.array(df.rolling(window=window, min_periods=1).mean().to_numpy(), copy=True)
    else:
        df = pd.DataFrame(X)
        out = np.array(df.rolling(window=window, min_periods=1).mean().to_numpy(), copy=True)
    out[: window - 1] = np.nan
    return out


class TemporalFeatureBuilder:
    """把鄰站當下值 + 鄰站延伸 + target 歷史拼成特徵矩陣。

    Args:
        lags:    list[int] — 每個元素是要加的 lag(小時,≥ 1)。空 list = 不加 lag column。
        rolling: list[int] — 每個元素是 rolling window 長度(小時,≥ 1)。
    """

    def __init__(self, lags: list[int], rolling: list[int]) -> None:
        if not isinstance(lags, list):
            raise TypeError(f"lags 須為 list,收到 {type(lags)}")
        if not isinstance(rolling, list):
            raise TypeError(f"rolling 須為 list,收到 {type(rolling)}")
        if any(int(x) < 1 for x in lags):
            raise ValueError(f"lags 每個元素需 ≥ 1,收到 {lags}")
        if any(int(x) < 1 for x in rolling):
            raise ValueError(f"rolling 每個元素需 ≥ 1,收到 {rolling}")
        seen_l: set[int] = set()
        self.lags: list[int] = []
        for x in lags:
            xi = int(x)
            if xi not in seen_l:
                seen_l.add(xi)
                self.lags.append(xi)
        seen_r: set[int] = set()
        self.rolling: list[int] = []
        for x in rolling:
            xi = int(x)
            if xi not in seen_r:
                seen_r.add(xi)
                self.rolling.append(xi)

    def n_features_per_neighbor(self) -> int:
        return 1 + len(self.lags) + len(self.rolling)

    def n_target_features(self) -> int:
        return len(self.lags)

    def n_total_columns(self, K: int) -> int:
        return K * self.n_features_per_neighbor() + self.n_target_features()

    def is_identity(self) -> bool:
        return not self.lags and not self.rolling

    def build(
        self,
        X: np.ndarray,
        target_history: np.ndarray | None = None,
    ) -> tuple[np.ndarray, list[str]]:
        """構造 X_aug 與 column 名稱。

        Args:
            X:               shape (T, K) — 鄰站時序矩陣
            target_history:  shape (T,)   — target 自己的時序,lags 非空時必填

        Returns:
            X_aug:           shape (T, K*(1+L+R) + L)
            feature_names:   字串列表
        """
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2:
            raise ValueError(f"X 須 2D (T, K),收到 shape={X.shape}")
        T, K = X.shape
        L = len(self.lags)
        R = len(self.rolling)

        if L > 0 and target_history is None:
            raise ValueError("lags 非空時必須提供 target_history")
        if target_history is not None:
            target_history = np.asarray(target_history, dtype=np.float64)
            if target_history.shape != (T,):
                raise ValueError(
                    f"target_history shape {target_history.shape} 與 X T={T} 不符"
                )

        names: list[str] = [f"nb{k}_t" for k in range(K)]
        parts: list[np.ndarray] = [X]

        for lag in self.lags:
            parts.append(_shift_with_nan_pad(X, lag))
            names.extend(f"nb{k}_t-{lag}" for k in range(K))

        for w in self.rolling:
            parts.append(_rolling_mean_nan(X, w))
            names.extend(f"nb{k}_roll{w}" for k in range(K))

        if L > 0:
            assert target_history is not None
            target_lags = np.full((T, L), np.nan, dtype=np.float64)
            for li, lag in enumerate(self.lags):
                target_lags[:, li] = _shift_with_nan_pad(target_history, lag)
            parts.append(target_lags)
            names.extend(f"tgt_t-{lag}" for lag in self.lags)

        X_aug = np.concatenate(parts, axis=1)
        assert X_aug.shape == (T, self.n_total_columns(K))
        assert len(names) == X_aug.shape[1]
        return X_aug, names
