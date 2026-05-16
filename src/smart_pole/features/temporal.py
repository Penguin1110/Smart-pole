"""TemporalFeatureBuilder——把 (T, K) 的鄰站時序攤成 Phase 3 線性 / GLS 模型的特徵矩陣。

呼叫慣例:caller 拿到整段時間軸的鄰站矩陣 ``X`` 與 target 自己的時序
``target_history``,builder 一次產出所有時點的 ``X_aug``,**含 lag / rolling 兩種延伸**。

輸出 column layout(K 鄰站、L = len(lags)、R = len(rolling)):

    cols [0,              K)              ← 鄰站當下值 t           (Phase 2 等價的部分)
    cols [K,              K*(1+L))        ← 鄰站滯後值 t-lag_i      (每個 lag 一個 K 區塊)
    cols [K*(1+L),        K*(1+L+R))      ← 鄰站滾動平均 mean[t-w+1, t]
    cols [K*(1+L+R),      K*(1+L+R)+L)    ← target 自己的滯後 t-lag_i

對應 shape:``(T, K*(1+L+R) + L)``。

**邊界**:早期 row(t < max(lag) 或 t < max(rolling)-1)在對應的延伸 column 會是 NaN——
這在物理上就是「沒有歷史」。上層 fit 要 row-drop。

**為什麼沒有 target 滾動?** target 是 y;它的滾動平均逼近 y 本身,等於把答案漏進 X。
target 只用「嚴格在 t 之前」的滯後 column,避免任何形式的 leakage。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _shift_with_nan_pad(arr: np.ndarray, lag: int) -> np.ndarray:
    """把 (T, ...) 沿 axis=0 向後位移 ``lag``,前 ``lag`` row 補 NaN。"""
    if lag < 1:
        raise ValueError(f"lag 必須 ≥ 1,收到 {lag}")
    out = np.full_like(arr, np.nan, dtype=np.float64)
    if lag < arr.shape[0]:
        out[lag:] = arr[:-lag]
    return out


def _rolling_mean_nan(X: np.ndarray, window: int) -> np.ndarray:
    """逐欄 rolling mean,window 內有 NaN 也照算(用 nan-aware mean)。

    需要 ``window`` 個非 NaN 點才出 valid value——簡化規則:用 pandas 的 ``min_periods=1``
    + 限制前 ``window-1`` row 強制 NaN(因為「沒滿 window」)。
    """
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

    **設計約定**:
        - 不吃 timestamps——lag/rolling 都是 row 位置上的 shift,
          caller 必須保證輸入時序是等距、同向(本專案是 hourly,已對齊)
        - 不分 train / test:builder 一次處理全段時間;mask 由上層套
        - ``feature_names`` 對應每個 column,給模型 ``.explain()`` 用
        - 沒有 default 值——空 lags / 空 rolling 是合法,但要 caller 顯式傳
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
        # 保留 caller 順序但去重(避免重複 column)
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
        """``lags=[] and rolling=[]``——只回傳鄰站當下值,等價於 Phase 2 行為。"""
        return not self.lags and not self.rolling

    def build(
        self,
        X: np.ndarray,
        target_history: np.ndarray | None = None,
    ) -> tuple[np.ndarray, list[str]]:
        """構造 ``X_aug`` 與 column 名稱。

        Args:
            X:               shape (T, K) — 鄰站時序矩陣
            target_history:  shape (T,)   — target 自己的時序;``lags`` 非空時必填,
                             空 lags 時可傳 None(會被忽略)

        Returns:
            X_aug:           shape (T, K*(1+L+R) + L)
            feature_names:   len = X_aug.shape[1] 的字串列表
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

        # 鄰站滯後(每個 lag 一個 (T, K) 區塊)
        for lag in self.lags:
            parts.append(_shift_with_nan_pad(X, lag))
            names.extend(f"nb{k}_t-{lag}" for k in range(K))

        # 鄰站 rolling
        for w in self.rolling:
            parts.append(_rolling_mean_nan(X, w))
            names.extend(f"nb{k}_roll{w}" for k in range(K))

        # target 自己的 lag(只有 lag,沒有 rolling/current)
        if L > 0:
            assert target_history is not None
            target_lags = np.full((T, L), np.nan, dtype=np.float64)
            for li, lag in enumerate(self.lags):
                shifted = _shift_with_nan_pad(target_history, lag)
                target_lags[:, li] = shifted
            parts.append(target_lags)
            names.extend(f"tgt_t-{lag}" for lag in self.lags)

        X_aug = np.concatenate(parts, axis=1)
        assert X_aug.shape == (T, self.n_total_columns(K)), (
            f"shape mismatch: 預期 {(T, self.n_total_columns(K))}, 實際 {X_aug.shape}"
        )
        assert len(names) == X_aug.shape[1]
        return X_aug, names
