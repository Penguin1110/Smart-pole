"""ElasticNet(Phase 3c)。

L1 + L2 混合正則化的線性回歸。L1 部分把不重要的 feature 權重壓 0,自動挑出對該 target
真正有用的 lag / rolling / 鄰站 column。

可解釋性 10/10:除了 weight 本身,**「哪些 column 被 L1 壓 0」這件事就是 finding**——
論文寫起來會很漂亮:「lag={1,24} 是模型最常用的時間訊號,72h 以上的 lag 幾乎被丟光」。

差異 vs TimeLagRidge:
  - TimeLagRidge:Ridge,所有 weight 非 0,小但稠密
  - ElasticNet:L1 把 weight 推 0,稀疏可挑特徵
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.linear_model import ElasticNet as SKElasticNet

from ..base import BaseImputer
from ..registry import register

logger = logging.getLogger(__name__)


@register
class ElasticNetImputer(BaseImputer):
    """Per-target ElasticNet 線性回歸,自動挑 feature。

    Params(沒有 default):
        alpha:     float ≥ 0 — 總正則化強度
        l1_ratio:  float ∈ [0, 1] — L1 占比;0 = pure Ridge,1 = pure Lasso
        max_iter:  int > 0 — sklearn 收斂上限
        min_train: int        — 樣本不足 fallback uniform mean
    """

    name = "elastic_net"
    tier = 3
    explainability = 10

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("alpha", "l1_ratio", "max_iter", "min_train"):
            if k not in params:
                raise KeyError(f"ElasticNet 需 `{k}` 參數(YAML 設,沒有 default)")
        self.alpha = float(params["alpha"])
        self.l1_ratio = float(params["l1_ratio"])
        self.max_iter = int(params["max_iter"])
        self.min_train = int(params["min_train"])
        if self.alpha < 0:
            raise ValueError(f"alpha ≥ 0,收到 {self.alpha}")
        if not 0.0 <= self.l1_ratio <= 1.0:
            raise ValueError(f"l1_ratio ∈ [0, 1],收到 {self.l1_ratio}")
        if self.max_iter < 1:
            raise ValueError(f"max_iter ≥ 1,收到 {self.max_iter}")
        if self.min_train < 1:
            raise ValueError(f"min_train ≥ 1,收到 {self.min_train}")

        self._model: SKElasticNet | None = None
        self._col_means: np.ndarray | None = None
        self._feature_names: list[str] | None = None
        self._fit_mean_y: float = 0.0
        self._n_train: int = 0

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "ElasticNetImputer":
        feature_names = meta.get("feature_names")
        self._feature_names = list(feature_names) if feature_names else None

        finite = np.isfinite(X).all(axis=1) & np.isfinite(y)
        n_train = int(finite.sum())
        self._n_train = n_train
        if n_train < max(self.min_train, X.shape[1] + 1):
            self._model = None
            self._fit_mean_y = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._col_means = np.zeros(X.shape[1], dtype=np.float64)
            self._fitted = True
            return self

        Xf, yf = X[finite], y[finite]
        self._col_means = np.nan_to_num(np.nanmean(Xf, axis=0), nan=0.0)
        self._fit_mean_y = float(yf.mean())

        # ElasticNet 對 X scale 敏感;但這裡所有 feature 都是 PM2.5 同量綱
        # (lag / rolling 都是 µg/m³),不額外標準化以保留 weight 可解讀性
        model = SKElasticNet(
            alpha=self.alpha, l1_ratio=self.l1_ratio,
            max_iter=self.max_iter, fit_intercept=True,
            random_state=0,
        )
        # sklearn 偶爾在共線性極高時 ConvergenceWarning;忽略不影響擬合結果
        import warnings as _w
        from sklearn.exceptions import ConvergenceWarning
        with _w.catch_warnings():
            _w.simplefilter("ignore", ConvergenceWarning)
            model.fit(Xf, yf)
        self._model = model
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if self._model is None:
            return np.full(X.shape[0], self._fit_mean_y, dtype=np.float64)
        assert self._col_means is not None
        X_filled = np.where(np.isfinite(X), X, self._col_means)
        y_pred = self._model.predict(X_filled)
        return np.clip(y_pred, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        if self._model is None:
            return {"error": "no fit", "n_train": self._n_train, "fallback": "uniform mean"}
        coefs = np.asarray(self._model.coef_, dtype=np.float64)
        names = self._feature_names or [f"x{i}" for i in range(len(coefs))]
        if len(names) != len(coefs):
            names = [f"x{i}" for i in range(len(coefs))]

        nonzero_idx = np.flatnonzero(coefs != 0.0)
        # 非 0 feature(挑出的)
        kept = [(names[i], float(coefs[i])) for i in nonzero_idx]
        kept.sort(key=lambda kv: -abs(kv[1]))

        # 群組統計(同 feature 種類)
        group_n_kept: dict[str, int] = {}
        for i in nonzero_idx:
            name = names[i]
            if name.startswith("nb"):
                _, rest = name.split("_", 1)
                grp = f"nb_{rest}"
            else:
                grp = name
            group_n_kept[grp] = group_n_kept.get(grp, 0) + 1

        return {
            "alpha":           self.alpha,
            "l1_ratio":        self.l1_ratio,
            "intercept":       float(self._model.intercept_),
            "n_train":         self._n_train,
            "n_features":      int(len(coefs)),
            "n_features_kept": int(len(nonzero_idx)),
            "kept_features":   kept[:20],          # 太長砍 head
            "group_n_kept":    group_n_kept,
            "weights":         coefs.tolist(),
            "feature_names":   names,
        }
