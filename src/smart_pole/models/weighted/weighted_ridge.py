"""Weighted Ridge:per-target Ridge 線性回歸,X 欄位為 K 個鄰站值,
y 為目標站當下值。Ridge 由 alpha 控正則化強度。

可選 feature scaling 提供 distance / correlation 先驗:當 ``weight_kind != 'none'``,
對 X 的每一欄乘以 w_i^{1/2}(其中 w_i = 1/d_i^p 或 max(0, r_i)),fit 後預測時
同樣對 X_test 乘以 w_i^{1/2}。這等同於 generalized ridge 中對近 / 高度相關的鄰站
給予較弱的正則化。

K-curve 出現 U 形是這個模型對的標誌(CLAUDE.md sanity check)——
小 K 欠擬合,大 K 隨樣本到 OK 但正則化不夠時會微升。
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.linear_model import Ridge

from ..base import BaseImputer
from ..registry import register
from ._utils import neighbor_distances_from_meta

logger = logging.getLogger(__name__)


@register
class WeightedRidgeImputer(BaseImputer):
    """Per-target Ridge 線性回歸。

    Params(沒有 default):
        alpha:       float ≥ 0 — Ridge 正則化強度
        weight_kind: 'none' | 'distance' | 'correlation' — feature 先驗 scaling 來源
                     - 'none':         不做 scaling,等同標準 Ridge
                     - 'distance':     w_i = 1/(d_i+eps)^power,d_i 從 meta['distances']
                     - 'correlation':  w_i = max(0, Pearson r_i),從 train 段算
        eps:         float ≥ 0(weight_kind='distance' 才用)
        power:       float > 0(weight_kind='distance' 才用)
        min_overlap: int(weight_kind='correlation' 才用)
    """

    name = "weighted_ridge"
    tier = 2
    explainability = 8

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for required in ("alpha", "weight_kind"):
            if required not in params:
                raise KeyError(f"WeightedRidge 需 `{required}` 參數(YAML 設,沒有 default)")
        self.alpha = float(params["alpha"])
        self.weight_kind = str(params["weight_kind"])
        if self.alpha < 0:
            raise ValueError(f"alpha 需 ≥ 0,收到 {self.alpha}")
        if self.weight_kind not in {"none", "distance", "correlation"}:
            raise ValueError(
                f"weight_kind 需是 'none'|'distance'|'correlation',收到 {self.weight_kind!r}"
            )

        if self.weight_kind == "distance":
            for required in ("eps", "power"):
                if required not in params:
                    raise KeyError(
                        f"weight_kind='distance' 需 `{required}` 參數(YAML 設,沒有 default)"
                    )
            self.eps = float(params["eps"])
            self.power = float(params["power"])
            if self.power <= 0:
                raise ValueError(f"power 需 > 0,收到 {self.power}")
            if self.eps < 0:
                raise ValueError(f"eps 需 ≥ 0,收到 {self.eps}")
        elif self.weight_kind == "correlation":
            if "min_overlap" not in params:
                raise KeyError("weight_kind='correlation' 需 `min_overlap`(YAML 設,沒有 default)")
            self.min_overlap = int(params["min_overlap"])
            if self.min_overlap < 1:
                raise ValueError(f"min_overlap 需 ≥ 1,收到 {self.min_overlap}")

        self._model: Ridge | None = None
        self._col_scale: np.ndarray | None = None  # shape (K,),X 各欄要乘的 sqrt(w)
        self._fit_mean_y: float = 0.0  # 全 NaN row 時的 fallback

    # ---- feature scaling -----------------------------------------------------

    def _scale_from_distance(self, K: int, meta: dict[str, Any]) -> np.ndarray:
        d = neighbor_distances_from_meta(meta, K)
        w = 1.0 / np.power(d + self.eps, self.power)
        # 拿 sqrt;若 sum 為 0 退回全 1
        s = np.sqrt(w)
        if not np.isfinite(s).all() or s.sum() == 0.0:
            return np.ones(K, dtype=np.float64)
        return s

    def _scale_from_correlation(self, X: np.ndarray, y: np.ndarray) -> np.ndarray:
        K = X.shape[1]
        w = np.zeros(K, dtype=np.float64)
        y_obs = np.isfinite(y)
        for k in range(K):
            x = X[:, k]
            m = y_obs & np.isfinite(x)
            if int(m.sum()) < self.min_overlap:
                continue
            yc = y[m] - y[m].mean()
            xc = x[m] - x[m].mean()
            denom = float(np.sqrt((yc * yc).sum() * (xc * xc).sum()))
            if denom == 0.0:
                continue
            r = float((yc * xc).sum() / denom)
            w[k] = max(0.0, r)
        s = np.sqrt(w)
        if s.sum() == 0.0:
            return np.ones(K, dtype=np.float64)
        return s

    def _make_scale(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        K = X.shape[1]
        if self.weight_kind == "none":
            return np.ones(K, dtype=np.float64)
        if self.weight_kind == "distance":
            return self._scale_from_distance(K, meta)
        return self._scale_from_correlation(X, y)

    # ---- BaseImputer API -----------------------------------------------------

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "WeightedRidgeImputer":
        # Ridge 不吃 NaN,刪掉任一格有 NaN 的列(或欄補列均值)。先用 row drop 較安全
        finite = np.isfinite(X).all(axis=1) & np.isfinite(y)
        if int(finite.sum()) < max(8, X.shape[1] + 1):
            # 樣本不足以擬合,退回「均值預測器」
            self._model = None
            self._fit_mean_y = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._col_scale = np.ones(X.shape[1], dtype=np.float64)
            self._fitted = True
            return self
        Xf, yf = X[finite], y[finite]

        scale = self._make_scale(Xf, yf, meta)
        Xs = Xf * scale  # column-wise scaling

        model = Ridge(alpha=self.alpha, fit_intercept=True)
        model.fit(Xs, yf)
        self._model = model
        self._col_scale = scale
        self._fit_mean_y = float(yf.mean())
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if self._model is None:
            return np.full(X.shape[0], self._fit_mean_y, dtype=np.float64)
        assert self._col_scale is not None
        # NaN 欄就地用該欄訓練段的近似:lazy,直接用該列其他欄的 ridge 預測 + fallback。
        # 簡單做法:把 NaN 欄填 0(等同於 ignore 該欄貢獻;intercept 會吸收 mean bias)。
        Xc = np.where(np.isfinite(X), X, 0.0)
        Xs = Xc * self._col_scale
        y_pred = self._model.predict(Xs)
        # 若整列原本全 NaN,改用 fit_mean_y;這比輸出 intercept 還穩
        all_nan = ~np.isfinite(X).any(axis=1)
        if all_nan.any():
            y_pred = y_pred.copy()
            y_pred[all_nan] = self._fit_mean_y
        return y_pred
