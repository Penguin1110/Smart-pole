"""GLS (Generalized Least Squares) (Phase 3c)。

Per-target 線性回歸,但允許殘差協方差不是 σ² I。本實作支援:

  - ``cov_structure='iid'`` → 退化成 OLS(殘差獨立同分佈假設)
  - ``cov_structure='ar1'`` → AR(1) 殘差結構,
    用 ``statsmodels.regression.linear_model.GLSAR`` 走 Cochrane-Orcutt 迭代

當殘差有時間自相關(PM2.5 在 1h 內 ACF ≈ 0.89,1h 殘差也會繼承這個結構),
OLS 標準誤估計會偏低、coef 仍 unbiased 但效率不是最佳。GLS / GLSAR 修正這件事,
**本質上是線性版的 ST-Kriging**(把時間結構編進 likelihood)。

可解釋性 9/10:OLS / GLSAR 係數可讀但「殘差 AR 結構估計」多了一步間接性,扣 1 分。
"""
from __future__ import annotations

import logging
import warnings
from typing import Any

import numpy as np
import statsmodels.api as sm

from ..base import BaseImputer
from ..registry import register

logger = logging.getLogger(__name__)


_VALID_COV = {"iid", "ar1"}


@register
class GLSImputer(BaseImputer):
    """Per-target GLS 線性回歸。

    Params(沒有 default):
        cov_structure: 'iid' | 'ar1'
        max_iter:      int > 0 — GLSAR iterative_fit 最大迭代;cov_structure='iid' 時無效
        min_train:     int     — 樣本不足 fallback uniform mean
    """

    name = "gls"
    tier = 3
    explainability = 9

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("cov_structure", "max_iter", "min_train"):
            if k not in params:
                raise KeyError(f"GLS 需 `{k}` 參數(YAML 設,沒有 default)")
        self.cov_structure = str(params["cov_structure"])
        if self.cov_structure not in _VALID_COV:
            raise ValueError(f"cov_structure ∈ {sorted(_VALID_COV)},收到 {self.cov_structure!r}")
        self.max_iter = int(params["max_iter"])
        self.min_train = int(params["min_train"])
        if self.max_iter < 1:
            raise ValueError(f"max_iter ≥ 1,收到 {self.max_iter}")
        if self.min_train < 1:
            raise ValueError(f"min_train ≥ 1,收到 {self.min_train}")

        self._params: np.ndarray | None = None     # 包含 intercept(index 0)
        self._rho: float | None = None              # AR(1) 學到的 ρ
        self._col_means: np.ndarray | None = None
        self._feature_names: list[str] | None = None
        self._fit_mean_y: float = 0.0
        self._n_train: int = 0
        self._fit_method: str = ""

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "GLSImputer":
        feature_names = meta.get("feature_names")
        self._feature_names = list(feature_names) if feature_names else None

        finite = np.isfinite(X).all(axis=1) & np.isfinite(y)
        n_train = int(finite.sum())
        self._n_train = n_train
        if n_train < max(self.min_train, X.shape[1] + 2):
            self._params = None
            self._fit_mean_y = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._col_means = np.zeros(X.shape[1], dtype=np.float64)
            self._fit_method = "fallback_too_few"
            self._fitted = True
            return self

        Xf, yf = X[finite], y[finite]
        self._col_means = np.nan_to_num(np.nanmean(Xf, axis=0), nan=0.0)
        self._fit_mean_y = float(yf.mean())

        Xc = sm.add_constant(Xf, has_constant="add")  # 第 0 欄 = intercept

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if self.cov_structure == "iid":
                    res = sm.OLS(yf, Xc).fit()
                    self._fit_method = "ols"
                    self._rho = None
                else:
                    glsar = sm.GLSAR(yf, Xc, rho=1)
                    res = glsar.iterative_fit(maxiter=self.max_iter)
                    self._fit_method = "glsar"
                    # 取最終學到的 rho(可能是 scalar 或 array)
                    rho_val = glsar.rho
                    if np.ndim(rho_val) > 0:
                        rho_val = float(np.atleast_1d(rho_val)[0])
                    self._rho = float(rho_val)

            params = np.asarray(res.params, dtype=np.float64)
            if not np.isfinite(params).all():
                raise RuntimeError("非有限參數")
            self._params = params

        except Exception as e:
            logger.debug("GLS fit failed for %s: %s",
                         meta.get("target_station_id"), e)
            self._params = None
            self._fit_method = f"fallback_{e.__class__.__name__}"

        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if self._params is None:
            return np.full(X.shape[0], self._fit_mean_y, dtype=np.float64)
        assert self._col_means is not None
        X_filled = np.where(np.isfinite(X), X, self._col_means)
        # 加常數欄
        Xc = np.column_stack([np.ones(X_filled.shape[0]), X_filled])
        if Xc.shape[1] != self._params.shape[0]:
            # 形狀不對(理論上不會發生)→ fallback
            return np.full(X.shape[0], self._fit_mean_y, dtype=np.float64)
        y_pred = Xc @ self._params
        return np.clip(y_pred, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        if self._params is None:
            return {
                "error":      "no fit",
                "n_train":    self._n_train,
                "fit_method": self._fit_method,
                "fallback":   "uniform mean",
            }
        intercept = float(self._params[0])
        coefs = self._params[1:]
        names = self._feature_names or [f"x{i}" for i in range(len(coefs))]
        if len(names) != len(coefs):
            names = [f"x{i}" for i in range(len(coefs))]

        order = np.argsort(-np.abs(coefs))
        top_5 = [(names[int(i)], float(coefs[int(i)])) for i in order[:5]]

        out: dict[str, Any] = {
            "cov_structure":  self.cov_structure,
            "fit_method":     self._fit_method,
            "intercept":      intercept,
            "n_train":        self._n_train,
            "n_features":     int(len(coefs)),
            "top_5_features": top_5,
            "weights":        coefs.tolist(),
            "feature_names":  names,
        }
        if self._rho is not None:
            out["ar1_rho"] = self._rho
        return out
