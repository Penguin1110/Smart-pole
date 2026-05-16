"""所有 PM2.5 補值演算法 (Phase 1 ~ Phase 3)。

11 個演算法共用 ``BaseImputer`` 契約,自動註冊到 ``REGISTRY``。

模型清單(tier / explainability):

  Tier 1 baseline:
    - ``mean``           算術平均                            (1, 10)

  Tier 2 weighted(Phase 2):
    - ``idw``            1 / (d+eps)^power 加權             (2, 10)
    - ``corr_weighted``  train Pearson r 為權重              (2, 10)
    - ``gaussian_kernel`` exp(-d²/2σ²) 加權                  (2,  9)
    - ``weighted_ridge`` per-target Ridge 線性               (2,  8)

  Tier 3 純空間(Phase 3a, features.enabled=false):
    - ``idw_optimal``    CV-tuned power IDW                  (3, 10)
    - ``kriging``        Ordinary Kriging (gstools)          (3,  9)
    - ``spatial_gp``     gpytorch ExactGP (RBF/Matern52)     (3,  8)

  Tier 3 時空線性(Phase 3c, features.enabled=true):
    - ``timelag_ridge``  Ridge + lag/rolling/target_lag     (3, 10)
    - ``elastic_net``    L1+L2 自動挑 feature                (3, 10)
    - ``gls``            statsmodels OLS / GLSAR             (3,  9)

  Tier 3 時空數學(Phase 3b):
    - ``dineof``         SVD-iterative impute on (T, S)      (3,  9)
    - ``st_gp``          gpytorch separable ST-GP (GPU)      (3,  8)

每個模型實作 ``BaseImputer`` 三件套:``fit(X, y, meta)`` / ``predict(X, meta)`` /
``explain()``。``meta`` dict 規格詳見 ``BaseImputer`` docstring。
"""
from __future__ import annotations

import logging
import warnings
from abc import ABC, abstractmethod
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# BaseImputer
# =============================================================================


class BaseImputer(ABC):
    """所有補值模型的統一介面。

    參數慣例:
        X:    shape (n_samples, K) — K 個鄰站當下值
              (features 模式 shape 變 (n_samples, K * (1 + L + R) + L))
        y:    shape (n_samples,)   — 目標站真值
        meta: dict,含:
            - target_station_id:    str
            - neighbor_station_ids: list[str]
            - distances:            np.ndarray, shape (n_samples, K) | None
            - timestamps:           pd.DatetimeIndex
            - target_coord:         tuple[float, float] | None  (lon, lat)
            - neighbor_coords:      np.ndarray | None, shape (K, 2)
            - feature_names:        list[str] | None
            - values_full:    np.ndarray (T, S)  整段資料矩陣(DINEOF / ST-GP 才用)
            - mask_full:      np.ndarray (T, S) bool
            - train_slice:    slice
            - test_slice:     slice
            - target_idx:     int
            - neighbor_idx:   list[int]
            - test_rows:      np.ndarray  (僅 ``predict`` 的 meta 才有)
    """

    name: str = "base"
    tier: int = 0
    requires_gpu: bool = False
    explainability: int = 0

    def __init__(self, **params: Any) -> None:
        self.params = params
        self._fitted = False

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "BaseImputer":
        ...

    @abstractmethod
    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        ...

    def get_config(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tier": self.tier,
            "explainability": self.explainability,
            "params": self.params,
        }

    def explain(self) -> dict[str, Any] | None:
        return None


# =============================================================================
# Registry
# =============================================================================


REGISTRY: dict[str, type[BaseImputer]] = {}


def register(cls: type[BaseImputer]) -> type[BaseImputer]:
    name = getattr(cls, "name", None)
    if not name or name == "base":
        raise ValueError(f"模型 {cls.__name__} 必須設定 class-level `name`")
    if name in REGISTRY and REGISTRY[name] is not cls:
        raise ValueError(f"模型名 '{name}' 重複註冊")
    tier = int(getattr(cls, "tier", 0))
    expl = int(getattr(cls, "explainability", 0))
    if tier >= 3 and expl < 8:
        raise ValueError(
            f"{cls.__name__} (tier={tier}) explainability={expl} < 8,違反 Phase 3 規範"
        )
    REGISTRY[name] = cls
    return cls


def get_model(name: str) -> type[BaseImputer]:
    if name not in REGISTRY:
        raise KeyError(f"找不到模型 '{name}'。已註冊:{sorted(REGISTRY.keys())}")
    return REGISTRY[name]


def list_models() -> list[str]:
    return sorted(REGISTRY.keys())


# =============================================================================
# Shared utilities
# =============================================================================


_EARTH_RADIUS_M = 6_371_000.0


def _haversine_pair(a: np.ndarray, b: np.ndarray) -> float:
    rlon1, rlat1 = np.radians(a[0]), np.radians(a[1])
    rlon2, rlat2 = np.radians(b[0]), np.radians(b[1])
    dlon = rlon2 - rlon1
    dlat = rlat2 - rlat1
    h = np.sin(dlat / 2) ** 2 + np.cos(rlat1) * np.cos(rlat2) * np.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * float(np.arcsin(np.sqrt(h)))


def _haversine_matrix(coords: np.ndarray) -> np.ndarray:
    M = coords.shape[0]
    D = np.zeros((M, M))
    for i in range(M):
        for j in range(i + 1, M):
            D[i, j] = D[j, i] = _haversine_pair(coords[i], coords[j])
    return D


def _local_xy_from_lonlat(
    coords: np.ndarray, origin_lon: float, origin_lat: float
) -> np.ndarray:
    coords = np.asarray(coords, dtype=np.float64)
    lat0_rad = np.radians(origin_lat)
    x = (coords[:, 0] - origin_lon) * np.cos(lat0_rad) * 111_320.0
    y = (coords[:, 1] - origin_lat) * 111_320.0
    return np.column_stack([x, y])


def _nan_safe_weighted_mean(
    X: np.ndarray,
    w_per_neighbor: np.ndarray,
    *,
    weight_floor: float = 0.0,
) -> np.ndarray:
    if X.ndim != 2:
        raise ValueError(f"X 須 2D,收到 shape={X.shape}")
    if w_per_neighbor.shape != (X.shape[1],):
        raise ValueError(f"w shape {w_per_neighbor.shape} 與 X K={X.shape[1]} 不符")

    valid = np.isfinite(X)
    w = np.broadcast_to(w_per_neighbor, X.shape).astype(np.float64)
    w_valid = np.where(valid, w, 0.0)
    x_valid = np.where(valid, X, 0.0)

    num = (x_valid * w_valid).sum(axis=1)
    denom = w_valid.sum(axis=1)
    out = np.full(X.shape[0], np.nan, dtype=np.float64)
    ok = denom > weight_floor
    out[ok] = num[ok] / denom[ok]
    return out


def _neighbor_distances_from_meta(meta: dict, K: int) -> np.ndarray:
    d = meta.get("distances")
    if d is None:
        raise KeyError("meta 缺 'distances'——weighted 模型需要")
    if d.ndim == 1:
        if d.shape[0] != K:
            raise ValueError(f"distances 長度 {d.shape[0]} ≠ K={K}")
        return d.astype(np.float64)
    if d.ndim == 2:
        if d.shape[1] != K:
            raise ValueError(f"distances 第二維 {d.shape[1]} ≠ K={K}")
        return d[0].astype(np.float64)
    raise ValueError(f"distances 維度異常:shape={d.shape}")


# =============================================================================
# Tier 1 — mean
# =============================================================================


@register
class MeanImputer(BaseImputer):
    """K 個鄰站 PM2.5 的算術平均。"""

    name = "mean"
    tier = 1
    explainability = 10

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "MeanImputer":
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        return np.nanmean(X, axis=1)


# =============================================================================
# Tier 2 — weighted (Phase 2)
# =============================================================================


@register
class IDWImputer(BaseImputer):
    """w_i = 1 / (d_i + eps)^power 加權平均。

    Params:
        power: float > 0
        eps:   float ≥ 0
    """

    name = "idw"
    tier = 2
    explainability = 10

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("power", "eps"):
            if k not in params:
                raise KeyError(f"IDW 需 `{k}` 參數")
        self.power = float(params["power"])
        self.eps = float(params["eps"])
        if self.power <= 0:
            raise ValueError(f"power 需 > 0,收到 {self.power}")
        if self.eps < 0:
            raise ValueError(f"eps 需 ≥ 0,收到 {self.eps}")

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "IDWImputer":
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        K = X.shape[1]
        d = _neighbor_distances_from_meta(meta, K)
        w = 1.0 / np.power(d + self.eps, self.power)
        return _nan_safe_weighted_mean(X, w)


@register
class CorrWeightedImputer(BaseImputer):
    """w_i = max(0, Pearson r_i),加權平均。

    Params:
        min_overlap: int ≥ 1
    """

    name = "corr_weighted"
    tier = 2
    explainability = 10

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        if "min_overlap" not in params:
            raise KeyError("CorrWeighted 需 `min_overlap` 參數")
        self.min_overlap = int(params["min_overlap"])
        if self.min_overlap < 1:
            raise ValueError(f"min_overlap ≥ 1,收到 {self.min_overlap}")
        self._weights: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "CorrWeightedImputer":
        n, K = X.shape
        weights = np.zeros(K, dtype=np.float64)
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
            weights[k] = max(0.0, r)
        self._weights = weights
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if self._weights is None:
            raise RuntimeError("CorrWeightedImputer 還沒 fit")
        return _nan_safe_weighted_mean(X, self._weights)

    def explain(self) -> dict[str, Any]:
        return {"weights": (self._weights.tolist() if self._weights is not None else None)}


@register
class GaussianKernelImputer(BaseImputer):
    """w_i = exp(-d_i² / (2 σ²)),加權平均。

    Params:
        sigma: float > 0
    """

    name = "gaussian_kernel"
    tier = 2
    explainability = 9

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        if "sigma" not in params:
            raise KeyError("GaussianKernel 需 `sigma` 參數")
        self.sigma = float(params["sigma"])
        if self.sigma <= 0:
            raise ValueError(f"sigma 需 > 0,收到 {self.sigma}")

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "GaussianKernelImputer":
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        K = X.shape[1]
        d = _neighbor_distances_from_meta(meta, K)
        z = d * d / (2.0 * self.sigma * self.sigma)
        z = z - z.min()
        w = np.exp(-z)
        return _nan_safe_weighted_mean(X, w)


@register
class WeightedRidgeImputer(BaseImputer):
    """Per-target Ridge 線性回歸,可選 distance / correlation feature scaling。

    Params:
        alpha:       float ≥ 0
        weight_kind: 'none' | 'distance' | 'correlation'
        eps:         float ≥ 0    (weight_kind='distance' 才用)
        power:       float > 0    (weight_kind='distance' 才用)
        min_overlap: int           (weight_kind='correlation' 才用)
    """

    name = "weighted_ridge"
    tier = 2
    explainability = 8

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for required in ("alpha", "weight_kind"):
            if required not in params:
                raise KeyError(f"WeightedRidge 需 `{required}`")
        self.alpha = float(params["alpha"])
        self.weight_kind = str(params["weight_kind"])
        if self.alpha < 0:
            raise ValueError(f"alpha ≥ 0,收到 {self.alpha}")
        if self.weight_kind not in {"none", "distance", "correlation"}:
            raise ValueError(f"weight_kind 須是 none/distance/correlation,收到 {self.weight_kind!r}")

        if self.weight_kind == "distance":
            for r in ("eps", "power"):
                if r not in params:
                    raise KeyError(f"weight_kind='distance' 需 `{r}`")
            self.eps = float(params["eps"])
            self.power = float(params["power"])
            if self.power <= 0:
                raise ValueError(f"power > 0,收到 {self.power}")
            if self.eps < 0:
                raise ValueError(f"eps ≥ 0,收到 {self.eps}")
        elif self.weight_kind == "correlation":
            if "min_overlap" not in params:
                raise KeyError("weight_kind='correlation' 需 `min_overlap`")
            self.min_overlap = int(params["min_overlap"])
            if self.min_overlap < 1:
                raise ValueError(f"min_overlap ≥ 1,收到 {self.min_overlap}")

        self._model = None
        self._col_scale: np.ndarray | None = None
        self._fit_mean_y: float = 0.0

    def _scale_from_distance(self, K: int, meta: dict[str, Any]) -> np.ndarray:
        d = _neighbor_distances_from_meta(meta, K)
        w = 1.0 / np.power(d + self.eps, self.power)
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

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "WeightedRidgeImputer":
        from sklearn.linear_model import Ridge

        finite = np.isfinite(X).all(axis=1) & np.isfinite(y)
        if int(finite.sum()) < max(8, X.shape[1] + 1):
            self._model = None
            self._fit_mean_y = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._col_scale = np.ones(X.shape[1], dtype=np.float64)
            self._fitted = True
            return self
        Xf, yf = X[finite], y[finite]

        scale = self._make_scale(Xf, yf, meta)
        Xs = Xf * scale

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
        Xc = np.where(np.isfinite(X), X, 0.0)
        Xs = Xc * self._col_scale
        y_pred = self._model.predict(Xs)
        all_nan = ~np.isfinite(X).any(axis=1)
        if all_nan.any():
            y_pred = y_pred.copy()
            y_pred[all_nan] = self._fit_mean_y
        return y_pred

    def explain(self) -> dict[str, Any]:
        if self._model is None:
            return {"error": "fallback to mean predictor"}
        return {
            "alpha": self.alpha,
            "weight_kind": self.weight_kind,
            "coef": np.asarray(self._model.coef_).tolist(),
            "intercept": float(self._model.intercept_),
            "col_scale": (self._col_scale.tolist() if self._col_scale is not None else None),
        }


# =============================================================================
# Tier 3 — pure spatial (Phase 3a)
# =============================================================================


@register
class IDWOptimalImputer(BaseImputer):
    """Cross-validated IDW:fit 時挑最佳 power。

    Params:
        power_grid: list[float]
        eps:        float ≥ 0
        cv_folds:   int ≥ 2
        cv_seed:    int
    """

    name = "idw_optimal"
    tier = 3
    explainability = 10

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("power_grid", "eps", "cv_folds", "cv_seed"):
            if k not in params:
                raise KeyError(f"IDWOptimal 需 `{k}`")
        self.power_grid = [float(p) for p in params["power_grid"]]
        self.eps = float(params["eps"])
        self.cv_folds = int(params["cv_folds"])
        self.cv_seed = int(params["cv_seed"])

        if not self.power_grid:
            raise ValueError("power_grid 不能為空")
        if any(p <= 0 for p in self.power_grid):
            raise ValueError(f"power_grid 元素需 > 0,收到 {self.power_grid}")
        if self.eps < 0:
            raise ValueError(f"eps ≥ 0,收到 {self.eps}")
        if self.cv_folds < 2:
            raise ValueError(f"cv_folds ≥ 2,收到 {self.cv_folds}")

        self._power_chosen: float | None = None
        self._cv_mae: dict[float, float] = {}
        self._n_train: int = 0

    @staticmethod
    def _idw_predict(X: np.ndarray, d: np.ndarray, p: float, eps: float) -> np.ndarray:
        w = 1.0 / np.power(d + eps, p)
        return _nan_safe_weighted_mean(X, w)

    def _cv_score_for_power(
        self, X: np.ndarray, y: np.ndarray, d: np.ndarray, power: float
    ) -> float:
        from sklearn.model_selection import KFold

        kf = KFold(n_splits=self.cv_folds, shuffle=True, random_state=self.cv_seed)
        fold_maes: list[float] = []
        for _, hold in kf.split(X):
            X_h, y_h = X[hold], y[hold]
            y_hat = self._idw_predict(X_h, d, power, self.eps)
            m = np.isfinite(y_hat) & np.isfinite(y_h)
            if m.sum() < 2:
                continue
            fold_maes.append(float(np.mean(np.abs(y_hat[m] - y_h[m]))))
        if not fold_maes:
            return float("nan")
        return float(np.mean(fold_maes))

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "IDWOptimalImputer":
        K = X.shape[1]
        d = _neighbor_distances_from_meta(meta, K)
        finite = np.isfinite(y) & np.isfinite(X).all(axis=1)
        Xf, yf = X[finite], y[finite]
        self._n_train = int(finite.sum())

        if self._n_train < self.cv_folds * 2:
            mid = self.power_grid[len(self.power_grid) // 2]
            self._power_chosen = mid
            self._cv_mae = {}
            self._fitted = True
            return self

        scores: dict[float, float] = {}
        for p in self.power_grid:
            scores[p] = self._cv_score_for_power(Xf, yf, d, p)

        self._cv_mae = scores
        valid = {p: s for p, s in scores.items() if np.isfinite(s)}
        if not valid:
            self._power_chosen = self.power_grid[len(self.power_grid) // 2]
        else:
            self._power_chosen = min(valid, key=lambda p: valid[p])
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if not self._fitted or self._power_chosen is None:
            raise RuntimeError("IDWOptimalImputer 還沒 fit")
        K = X.shape[1]
        d = _neighbor_distances_from_meta(meta, K)
        return self._idw_predict(X, d, self._power_chosen, self.eps)

    def explain(self) -> dict[str, Any]:
        return {
            "power_chosen": float(self._power_chosen) if self._power_chosen is not None else None,
            "cv_mae_per_power": {f"{p:g}": float(m) for p, m in self._cv_mae.items()},
            "power_grid": list(self.power_grid),
            "cv_folds": self.cv_folds,
            "n_train": self._n_train,
        }


@register
class OrdinaryKrigingImputer(BaseImputer):
    """Ordinary Kriging:從 train 段值與 K+1 站位置擬 variogram。

    Params:
        variogram_model: 'spherical' | 'exponential' | 'gaussian'
        n_bins:          int ≥ 3
        max_range_m:     float > 0
        nugget:          'fit' | float ≥ 0
    """

    name = "kriging"
    tier = 3
    explainability = 9

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        import gstools as gs

        self._models_map = {
            "spherical": gs.Spherical,
            "exponential": gs.Exponential,
            "gaussian": gs.Gaussian,
        }
        for k in ("variogram_model", "n_bins", "max_range_m", "nugget"):
            if k not in params:
                raise KeyError(f"Kriging 需 `{k}`")
        self.variogram_model = str(params["variogram_model"])
        if self.variogram_model not in self._models_map:
            raise ValueError(f"variogram_model 須在 {sorted(self._models_map)}")
        self.n_bins = int(params["n_bins"])
        self.max_range_m = float(params["max_range_m"])
        nug = params["nugget"]
        if isinstance(nug, str):
            if nug != "fit":
                raise ValueError("nugget 字串只能 'fit'")
            self.nugget_fit = True
            self.nugget_fixed = 0.0
        else:
            self.nugget_fit = False
            self.nugget_fixed = float(nug)
            if self.nugget_fixed < 0:
                raise ValueError(f"nugget ≥ 0,收到 {self.nugget_fixed}")
        if self.n_bins < 3:
            raise ValueError(f"n_bins ≥ 3")
        if self.max_range_m <= 0:
            raise ValueError(f"max_range_m > 0")

        self._weights: np.ndarray | None = None
        self._fit_mean_y: float = 0.0
        self._explain_dict: dict[str, Any] | None = None

    def _fit_variogram(self, z_all: np.ndarray, coords_all: np.ndarray):
        T, M = z_all.shape
        D = _haversine_matrix(coords_all)
        ii, jj = np.triu_indices(M, k=1)
        d_pairs = D[ii, jj]
        keep = d_pairs <= self.max_range_m
        if keep.sum() < 3:
            return None, {"error": "no pairs within max_range_m"}
        ii, jj, d_pairs = ii[keep], jj[keep], d_pairs[keep]

        gamma_per_pair = np.full(len(d_pairs), np.nan)
        n_per_pair = np.zeros(len(d_pairs), dtype=int)
        for p, (i, j) in enumerate(zip(ii, jj)):
            zi = z_all[:, i]
            zj = z_all[:, j]
            m = np.isfinite(zi) & np.isfinite(zj)
            n = int(m.sum())
            if n < 10:
                continue
            diff = zi[m] - zj[m]
            gamma_per_pair[p] = float(0.5 * np.mean(diff * diff))
            n_per_pair[p] = n

        valid = np.isfinite(gamma_per_pair)
        if valid.sum() < 3:
            return None, {"error": "not enough valid pairs"}

        d_valid = d_pairs[valid]
        g_valid = gamma_per_pair[valid]
        w_valid = n_per_pair[valid].astype(float)

        bins = np.linspace(0, self.max_range_m, self.n_bins + 1)
        bin_idx = np.digitize(d_valid, bins) - 1
        bin_idx = np.clip(bin_idx, 0, self.n_bins - 1)
        bin_center = np.full(self.n_bins, np.nan)
        bin_gamma = np.full(self.n_bins, np.nan)
        bin_count = np.zeros(self.n_bins, dtype=int)
        for b in range(self.n_bins):
            sel = bin_idx == b
            if sel.sum() == 0:
                continue
            bin_count[b] = int(sel.sum())
            bin_center[b] = float(np.average(d_valid[sel], weights=w_valid[sel]))
            bin_gamma[b] = float(np.average(g_valid[sel], weights=w_valid[sel]))

        finite = np.isfinite(bin_center) & np.isfinite(bin_gamma)
        if finite.sum() < 3:
            return None, {"error": "not enough binned points"}

        model_cls = self._models_map[self.variogram_model]
        model = model_cls(dim=2)
        try:
            if self.nugget_fit:
                model.fit_variogram(bin_center[finite], bin_gamma[finite], nugget=True)
            else:
                model.nugget = self.nugget_fixed
                model.fit_variogram(bin_center[finite], bin_gamma[finite], nugget=False)
        except Exception as e:
            return None, {"error": f"fit failed: {e}"}

        diag = {
            "sill": float(model.sill),
            "var": float(model.var),
            "range": float(model.len_scale),
            "nugget": float(model.nugget),
            "bin_center": bin_center[finite].tolist(),
            "bin_gamma": bin_gamma[finite].tolist(),
            "bin_count": bin_count[finite].tolist(),
            "n_pairs_used": int(finite.sum()),
        }
        return model, diag

    def _compute_kriging_weights(self, model, neighbor_coords, target_coord) -> np.ndarray:
        K = neighbor_coords.shape[0]
        D_nn = _haversine_matrix(neighbor_coords)
        d_nt = np.array([_haversine_pair(neighbor_coords[i], target_coord) for i in range(K)])

        A = np.ones((K + 1, K + 1))
        A[K, K] = 0.0
        A[:K, :K] = model.variogram(D_nn)
        b = np.ones(K + 1)
        b[:K] = model.variogram(d_nt)

        jitter = max(float(model.nugget) * 0.01, float(model.sill) * 1e-6, 1e-9)
        A[:K, :K] += jitter * np.eye(K)

        try:
            sol = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            sol = np.linalg.lstsq(A, b, rcond=None)[0]
        return sol[:K]

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "OrdinaryKrigingImputer":
        K = X.shape[1]
        neighbor_coords = meta.get("neighbor_coords")
        target_coord = meta.get("target_coord")
        if neighbor_coords is None or target_coord is None:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._fit_mean_y = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._explain_dict = {"error": "missing coords; fallback to uniform mean"}
            self._fitted = True
            return self

        target_coord = np.asarray(target_coord, dtype=np.float64)
        finite = np.isfinite(y)
        y_f = y[finite]
        X_f = X[finite]
        n_train = len(y_f)
        if n_train < 10:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._fit_mean_y = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._explain_dict = {"error": "n_train < 10; fallback to uniform mean"}
            self._fitted = True
            return self

        z_all = np.column_stack([X_f, y_f])
        coords_all = np.vstack([neighbor_coords, target_coord[None, :]])

        model, diag = self._fit_variogram(z_all, coords_all)
        if model is None:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._fit_mean_y = float(np.nanmean(y_f))
            self._explain_dict = {"error": diag.get("error", "unknown"), "fallback": "uniform mean"}
            self._fitted = True
            return self

        weights = self._compute_kriging_weights(model, neighbor_coords, target_coord)
        weights_sum = float(weights.sum()) if np.isfinite(weights).all() else float("nan")
        weight_max_abs = (
            float(np.max(np.abs(weights))) if np.isfinite(weights).all() else float("nan")
        )
        if (
            not np.isfinite(weights).all()
            or abs(weights_sum - 1.0) > 0.1
            or weight_max_abs > 3.0
        ):
            self._weights = np.ones(K, dtype=np.float64) / K
            self._fit_mean_y = float(np.nanmean(y_f))
            self._explain_dict = {
                "error": "kriging weights degenerate",
                "weights_sum": weights_sum,
                "weight_max_abs": weight_max_abs,
                "fallback": "uniform mean",
                "variogram_params": {
                    "sill": diag["sill"],
                    "range": diag["range"],
                    "nugget": diag["nugget"],
                },
            }
            self._fitted = True
            return self

        self._weights = weights
        self._fit_mean_y = float(np.nanmean(y_f))
        self._explain_dict = {
            "variogram_model": self.variogram_model,
            "variogram_params": {
                "sill": diag["sill"],
                "range": diag["range"],
                "nugget": diag["nugget"],
            },
            "weights": self._weights.tolist(),
            "weights_sum": weights_sum,
            "n_train": n_train,
            "n_pairs_used": diag["n_pairs_used"],
        }
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if not self._fitted or self._weights is None:
            raise RuntimeError("OrdinaryKrigingImputer 還沒 fit")
        w = self._weights
        valid = np.isfinite(X)
        X_filled = np.where(valid, X, self._fit_mean_y)
        w_broad = np.broadcast_to(w, X.shape).astype(np.float64)
        num = (X_filled * w_broad).sum(axis=1)
        return np.clip(num, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        return self._explain_dict


@register
class SpatialGPImputer(BaseImputer):
    """Per-target Spatial GP:fit kernel on K+1 站位置,predict 走 kernel weights。

    Params:
        kernel:              'rbf' | 'matern52'
        n_iter:              int ≥ 1
        lr:                  float > 0
        lengthscale_init_m:  float > 0
        noise_floor:         float ≥ 0
    """

    name = "spatial_gp"
    tier = 3
    explainability = 8
    requires_gpu = False

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("kernel", "n_iter", "lr", "lengthscale_init_m", "noise_floor"):
            if k not in params:
                raise KeyError(f"SpatialGP 需 `{k}`")
        self.kernel = str(params["kernel"])
        if self.kernel not in {"rbf", "matern52"}:
            raise ValueError(f"kernel 須 rbf|matern52,收到 {self.kernel!r}")
        self.n_iter = int(params["n_iter"])
        self.lr = float(params["lr"])
        self.lengthscale_init_m = float(params["lengthscale_init_m"])
        self.noise_floor = float(params["noise_floor"])
        if self.n_iter < 1:
            raise ValueError(f"n_iter ≥ 1")
        if self.lr <= 0:
            raise ValueError(f"lr > 0")
        if self.lengthscale_init_m <= 0:
            raise ValueError(f"lengthscale_init_m > 0")
        if self.noise_floor < 0:
            raise ValueError(f"noise_floor ≥ 0")

        self._weights: np.ndarray | None = None
        self._global_mean: float = 0.0
        self._explain_dict: dict[str, Any] | None = None

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "SpatialGPImputer":
        import gpytorch
        import torch

        K = X.shape[1]
        neighbor_coords = meta.get("neighbor_coords")
        target_coord = meta.get("target_coord")

        if neighbor_coords is None or target_coord is None:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._global_mean = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._explain_dict = {"error": "missing coords; fallback uniform mean"}
            self._fitted = True
            return self

        target_coord = np.asarray(target_coord, dtype=np.float64)
        finite = np.isfinite(y)
        y_f = y[finite]
        X_f = X[finite]
        if len(y_f) < 10:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._global_mean = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._explain_dict = {"error": "n_train < 10; fallback uniform mean"}
            self._fitted = True
            return self

        mean_target = float(y_f.mean())
        mean_neighbors = np.nanmean(X_f, axis=0)
        if not np.isfinite(mean_neighbors).all():
            mean_neighbors = np.where(np.isfinite(mean_neighbors), mean_neighbors, mean_target)

        means_all = np.concatenate([mean_neighbors, [mean_target]])
        coords_all = np.vstack([neighbor_coords, target_coord[None, :]])

        global_mean = float(means_all.mean())
        centered = means_all - global_mean
        self._global_mean = global_mean

        xy = _local_xy_from_lonlat(coords_all, target_coord[0], target_coord[1])
        train_x = torch.tensor(xy, dtype=torch.float64)
        train_y = torch.tensor(centered, dtype=torch.float64)

        class _Model(gpytorch.models.ExactGP):
            def __init__(self, tx, ty, lk, kernel_type):
                super().__init__(tx, ty, lk)
                self.mean_module = gpytorch.means.ConstantMean()
                if kernel_type == "rbf":
                    base = gpytorch.kernels.RBFKernel()
                else:
                    base = gpytorch.kernels.MaternKernel(nu=2.5)
                self.covar_module = gpytorch.kernels.ScaleKernel(base)

            def forward(self, x):
                return gpytorch.distributions.MultivariateNormal(
                    self.mean_module(x), self.covar_module(x)
                )

        likelihood = gpytorch.likelihoods.GaussianLikelihood()
        try:
            model = _Model(train_x, train_y, likelihood, self.kernel).double()
        except ValueError as e:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._explain_dict = {"error": str(e), "fallback": "uniform mean"}
            self._fitted = True
            return self

        empirical_var = float(centered.var()) if centered.var() > 0 else 1.0
        with torch.no_grad():
            model.covar_module.base_kernel.lengthscale = float(self.lengthscale_init_m)
            model.covar_module.outputscale = empirical_var
            likelihood.noise = max(empirical_var * 0.05, self.noise_floor, 1e-6)

        model.train()
        likelihood.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=self.lr)
        mll = gpytorch.mlls.ExactMarginalLogLikelihood(likelihood, model)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for _ in range(self.n_iter):
                optimizer.zero_grad()
                try:
                    out = model(train_x)
                    loss = -mll(out, train_y)
                except RuntimeError:
                    break
                loss.backward()
                optimizer.step()

        try:
            lengthscale = float(model.covar_module.base_kernel.lengthscale.item())
            outputscale = float(model.covar_module.outputscale.item())
            noise = max(float(likelihood.noise.item()), self.noise_floor)
        except Exception as e:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._explain_dict = {"error": f"hyperparam extract: {e}"}
            self._fitted = True
            return self

        model.eval()
        likelihood.eval()
        with torch.no_grad():
            neighbor_x = train_x[:K]
            target_x = train_x[K : K + 1]
            K_nn = model.covar_module(neighbor_x, neighbor_x).to_dense().numpy()
            K_target_nb = model.covar_module(target_x, neighbor_x).to_dense().numpy().flatten()

        A = K_nn + noise * np.eye(K)
        try:
            weights = np.linalg.solve(A, K_target_nb)
        except np.linalg.LinAlgError:
            weights = np.linalg.lstsq(A, K_target_nb, rcond=None)[0]

        weights_sum = float(weights.sum()) if np.isfinite(weights).all() else float("nan")
        weight_max_abs = (
            float(np.max(np.abs(weights))) if np.isfinite(weights).all() else float("nan")
        )
        if (not np.isfinite(weights).all()) or weight_max_abs > 3.0:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._explain_dict = {
                "error": "weights degenerate",
                "weight_max_abs": weight_max_abs,
                "lengthscale_m": lengthscale,
                "outputscale": outputscale,
                "noise": noise,
                "fallback": "uniform mean",
            }
            self._fitted = True
            return self

        self._weights = weights
        self._explain_dict = {
            "kernel": self.kernel,
            "lengthscale_m": lengthscale,
            "outputscale": outputscale,
            "noise": noise,
            "weights": weights.tolist(),
            "weights_sum": weights_sum,
            "n_train_means": int(len(means_all)),
        }
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if not self._fitted or self._weights is None:
            raise RuntimeError("SpatialGPImputer 還沒 fit")
        w = self._weights
        X_filled = np.where(np.isfinite(X), X, self._global_mean)
        sum_w = float(w.sum())
        pred = X_filled @ w + (1.0 - sum_w) * self._global_mean
        return np.clip(pred, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        return self._explain_dict


# =============================================================================
# Tier 3 — spatiotemporal linear (Phase 3c)
# =============================================================================


@register
class TimeLagRidgeImputer(BaseImputer):
    """Per-target Ridge,X 含時空 feature(由 TemporalFeatureBuilder 提供)。

    Params:
        alpha:     float ≥ 0
        min_train: int
    """

    name = "timelag_ridge"
    tier = 3
    explainability = 10

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("alpha", "min_train"):
            if k not in params:
                raise KeyError(f"TimeLagRidge 需 `{k}`")
        self.alpha = float(params["alpha"])
        self.min_train = int(params["min_train"])
        if self.alpha < 0:
            raise ValueError(f"alpha ≥ 0")
        if self.min_train < 1:
            raise ValueError(f"min_train ≥ 1")

        self._model = None
        self._col_means: np.ndarray | None = None
        self._feature_names: list[str] | None = None
        self._fit_mean_y: float = 0.0
        self._n_train: int = 0

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "TimeLagRidgeImputer":
        from sklearn.linear_model import Ridge

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

        self._model = Ridge(alpha=self.alpha, fit_intercept=True).fit(Xf, yf)
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

        order = np.argsort(-np.abs(coefs))
        top_k = min(5, len(coefs))
        top = [(names[i], float(coefs[i])) for i in order[:top_k]]

        group_abs: dict[str, float] = {}
        for name, w in zip(names, coefs):
            if name.startswith("nb"):
                _, rest = name.split("_", 1)
                group = f"nb_{rest}"
            else:
                group = name
            group_abs[group] = group_abs.get(group, 0.0) + abs(float(w))

        return {
            "alpha": self.alpha,
            "intercept": float(self._model.intercept_),
            "n_train": self._n_train,
            "n_features": int(len(coefs)),
            "top_5_features": top,
            "group_abs_weight": dict(sorted(group_abs.items(), key=lambda kv: -kv[1])),
            "weights": coefs.tolist(),
            "feature_names": names,
        }


@register
class ElasticNetImputer(BaseImputer):
    """Per-target ElasticNet,自動挑 feature。

    Params:
        alpha:     float ≥ 0
        l1_ratio:  float ∈ [0, 1]
        max_iter:  int > 0
        min_train: int
    """

    name = "elastic_net"
    tier = 3
    explainability = 10

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("alpha", "l1_ratio", "max_iter", "min_train"):
            if k not in params:
                raise KeyError(f"ElasticNet 需 `{k}`")
        self.alpha = float(params["alpha"])
        self.l1_ratio = float(params["l1_ratio"])
        self.max_iter = int(params["max_iter"])
        self.min_train = int(params["min_train"])
        if self.alpha < 0:
            raise ValueError(f"alpha ≥ 0")
        if not 0.0 <= self.l1_ratio <= 1.0:
            raise ValueError(f"l1_ratio ∈ [0, 1]")
        if self.max_iter < 1:
            raise ValueError(f"max_iter ≥ 1")
        if self.min_train < 1:
            raise ValueError(f"min_train ≥ 1")

        self._model = None
        self._col_means: np.ndarray | None = None
        self._feature_names: list[str] | None = None
        self._fit_mean_y: float = 0.0
        self._n_train: int = 0

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "ElasticNetImputer":
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.linear_model import ElasticNet as SKElasticNet

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

        model = SKElasticNet(
            alpha=self.alpha,
            l1_ratio=self.l1_ratio,
            max_iter=self.max_iter,
            fit_intercept=True,
            random_state=0,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
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
        kept = [(names[i], float(coefs[i])) for i in nonzero_idx]
        kept.sort(key=lambda kv: -abs(kv[1]))

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
            "alpha": self.alpha,
            "l1_ratio": self.l1_ratio,
            "intercept": float(self._model.intercept_),
            "n_train": self._n_train,
            "n_features": int(len(coefs)),
            "n_features_kept": int(len(nonzero_idx)),
            "kept_features": kept[:20],
            "group_n_kept": group_n_kept,
            "weights": coefs.tolist(),
            "feature_names": names,
        }


@register
class GLSImputer(BaseImputer):
    """Per-target GLS 線性回歸。

    Params:
        cov_structure: 'iid' | 'ar1'
        max_iter:      int > 0
        min_train:     int
    """

    name = "gls"
    tier = 3
    explainability = 9

    _VALID_COV = {"iid", "ar1"}

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("cov_structure", "max_iter", "min_train"):
            if k not in params:
                raise KeyError(f"GLS 需 `{k}`")
        self.cov_structure = str(params["cov_structure"])
        if self.cov_structure not in self._VALID_COV:
            raise ValueError(f"cov_structure ∈ {sorted(self._VALID_COV)}")
        self.max_iter = int(params["max_iter"])
        self.min_train = int(params["min_train"])
        if self.max_iter < 1:
            raise ValueError(f"max_iter ≥ 1")
        if self.min_train < 1:
            raise ValueError(f"min_train ≥ 1")

        self._params: np.ndarray | None = None
        self._rho: float | None = None
        self._col_means: np.ndarray | None = None
        self._feature_names: list[str] | None = None
        self._fit_mean_y: float = 0.0
        self._n_train: int = 0
        self._fit_method: str = ""

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "GLSImputer":
        import statsmodels.api as sm

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

        Xc = sm.add_constant(Xf, has_constant="add")

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
                    rho_val = glsar.rho
                    if np.ndim(rho_val) > 0:
                        rho_val = float(np.atleast_1d(rho_val)[0])
                    self._rho = float(rho_val)

            params = np.asarray(res.params, dtype=np.float64)
            if not np.isfinite(params).all():
                raise RuntimeError("非有限參數")
            self._params = params
        except Exception as e:
            self._params = None
            self._fit_method = f"fallback_{e.__class__.__name__}"

        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if self._params is None:
            return np.full(X.shape[0], self._fit_mean_y, dtype=np.float64)
        assert self._col_means is not None
        X_filled = np.where(np.isfinite(X), X, self._col_means)
        Xc = np.column_stack([np.ones(X_filled.shape[0]), X_filled])
        if Xc.shape[1] != self._params.shape[0]:
            return np.full(X.shape[0], self._fit_mean_y, dtype=np.float64)
        y_pred = Xc @ self._params
        return np.clip(y_pred, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        if self._params is None:
            return {
                "error": "no fit",
                "n_train": self._n_train,
                "fit_method": self._fit_method,
                "fallback": "uniform mean",
            }
        intercept = float(self._params[0])
        coefs = self._params[1:]
        names = self._feature_names or [f"x{i}" for i in range(len(coefs))]
        if len(names) != len(coefs):
            names = [f"x{i}" for i in range(len(coefs))]

        order = np.argsort(-np.abs(coefs))
        top_5 = [(names[int(i)], float(coefs[int(i)])) for i in order[:5]]

        out: dict[str, Any] = {
            "cov_structure": self.cov_structure,
            "fit_method": self._fit_method,
            "intercept": intercept,
            "n_train": self._n_train,
            "n_features": int(len(coefs)),
            "top_5_features": top_5,
            "weights": coefs.tolist(),
            "feature_names": names,
        }
        if self._rho is not None:
            out["ar1_rho"] = self._rho
        return out


# =============================================================================
# Tier 3 — DINEOF (Phase 3b)
# =============================================================================


_DINEOF_CACHE: dict[tuple, tuple[np.ndarray, dict[str, Any]]] = {}


def _dineof_impute(
    values: np.ndarray,
    mask: np.ndarray,
    *,
    n_modes: int,
    max_iter: int,
    tol: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    T, S = values.shape
    missing = (~np.isfinite(values)) | mask
    n_missing = int(missing.sum())
    if n_missing == 0:
        return values.copy(), {"warning": "no missing cells"}

    obs = np.isfinite(values) & (~mask)
    col_sum = np.where(obs, values, 0.0).sum(axis=0)
    col_count = obs.sum(axis=0)
    col_mean = np.where(col_count > 0, col_sum / np.maximum(col_count, 1), 0.0)

    X = np.where(missing, col_mean, values).astype(np.float64, copy=True)

    rmse_history: list[float] = []
    sing_vals: np.ndarray | None = None
    iters_used = 0

    for it in range(max_iter):
        global_mean = float(X.mean())
        X_centered = X - global_mean

        try:
            U, s, Vt = np.linalg.svd(X_centered, full_matrices=False)
        except np.linalg.LinAlgError as e:
            logger.warning("DINEOF SVD failed iter=%d: %s", it, e)
            break

        s_trunc = s.copy()
        s_trunc[n_modes:] = 0.0
        X_rec_centered = U @ np.diag(s_trunc) @ Vt
        X_rec = X_rec_centered + global_mean

        diff = X_rec[missing] - X[missing]
        rmse_iter = float(np.sqrt(np.mean(diff * diff))) if diff.size else 0.0
        rmse_history.append(rmse_iter)

        X = np.where(missing, X_rec, X)
        iters_used = it + 1
        sing_vals = s

        if rmse_iter < tol:
            break

    if sing_vals is not None:
        total_var = float((sing_vals**2).sum())
        modes_var = sing_vals[:n_modes] ** 2 / max(total_var, 1e-12)
        explained_var = float(modes_var.sum())
    else:
        explained_var = float("nan")

    explain = {
        "n_modes": n_modes,
        "max_iter": max_iter,
        "iters_used": iters_used,
        "rmse_history": rmse_history[-10:],
        "explained_variance_ratio": explained_var,
        "n_missing_cells": n_missing,
        "n_cells_total": int(values.size),
    }
    return X, explain


@register
class DINEOFImputer(BaseImputer):
    """SVD-based iterative impute on full (T, S) matrix.

    Params:
        n_modes:  int ≥ 1
        max_iter: int ≥ 1
        tol:      float > 0
    """

    name = "dineof"
    tier = 3
    explainability = 9

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("n_modes", "max_iter", "tol"):
            if k not in params:
                raise KeyError(f"DINEOF 需 `{k}`")
        self.n_modes = int(params["n_modes"])
        self.max_iter = int(params["max_iter"])
        self.tol = float(params["tol"])
        if self.n_modes < 1:
            raise ValueError(f"n_modes ≥ 1")
        if self.max_iter < 1:
            raise ValueError(f"max_iter ≥ 1")
        if self.tol <= 0:
            raise ValueError(f"tol > 0")

        self._imputed: np.ndarray | None = None
        self._explain_dict: dict[str, Any] | None = None
        self._target_idx: int = -1

    def _ensure_imputed(self, meta: dict[str, Any]) -> None:
        values = meta.get("values_full")
        mask = meta.get("mask_full")
        if values is None or mask is None:
            raise RuntimeError(
                "DINEOF 需要 meta['values_full'] 與 meta['mask_full']"
            )
        key = (id(values), id(mask), self.n_modes, self.max_iter, self.tol)
        if key not in _DINEOF_CACHE:
            _DINEOF_CACHE[key] = _dineof_impute(
                values, mask, n_modes=self.n_modes, max_iter=self.max_iter, tol=self.tol
            )
        self._imputed, self._explain_dict = _DINEOF_CACHE[key]

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "DINEOFImputer":
        self._ensure_imputed(meta)
        self._target_idx = int(meta.get("target_idx", -1))
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if self._imputed is None:
            raise RuntimeError("DINEOFImputer 還沒 fit")
        if self._target_idx < 0:
            raise RuntimeError("meta 缺 target_idx")
        test_rows = meta.get("test_rows")
        test_slice = meta.get("test_slice")
        if test_rows is None or test_slice is None:
            raise RuntimeError("meta 缺 test_rows / test_slice")
        test_offset = test_slice.start
        y_pred = self._imputed[test_offset + np.asarray(test_rows), self._target_idx]
        return np.clip(y_pred, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        if self._explain_dict is None:
            return None
        return dict(self._explain_dict)


# =============================================================================
# Tier 3 — Spatio-Temporal GP (Phase 3b, GPU)
# =============================================================================


@register
class STGPImputer(BaseImputer):
    """Per-target Spatio-Temporal GP (separable RBF_s × RBF_t).

    Params:
        n_iter:                 int ≥ 1
        lr:                     float > 0
        max_train:              int ≥ 50
        lengthscale_init_space_m: float > 0
        lengthscale_init_time_h:  float > 0
        noise_floor:            float ≥ 0
        seed:                   int
    """

    name = "st_gp"
    tier = 3
    explainability = 8
    requires_gpu = True

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        required = (
            "n_iter", "lr", "max_train",
            "lengthscale_init_space_m", "lengthscale_init_time_h",
            "noise_floor", "seed",
        )
        for k in required:
            if k not in params:
                raise KeyError(f"STGP 需 `{k}`")
        self.n_iter = int(params["n_iter"])
        self.lr = float(params["lr"])
        self.max_train = int(params["max_train"])
        self.lengthscale_init_space_m = float(params["lengthscale_init_space_m"])
        self.lengthscale_init_time_h = float(params["lengthscale_init_time_h"])
        self.noise_floor = float(params["noise_floor"])
        self.seed = int(params["seed"])

        if self.n_iter < 1:
            raise ValueError(f"n_iter ≥ 1")
        if self.max_train < 50:
            raise ValueError(f"max_train ≥ 50")
        for n, v in (
            ("lr", self.lr),
            ("lengthscale_init_space_m", self.lengthscale_init_space_m),
            ("lengthscale_init_time_h", self.lengthscale_init_time_h),
        ):
            if v <= 0:
                raise ValueError(f"{n} > 0")
        if self.noise_floor < 0:
            raise ValueError(f"noise_floor ≥ 0")

        self._device = None
        self._model = None
        self._likelihood = None
        self._train_x = None
        self._train_y = None
        self._global_mean: float = 0.0
        self._explain_dict: dict[str, Any] | None = None

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "STGPImputer":
        import gpytorch
        import torch

        neighbor_coords = meta.get("neighbor_coords")
        target_coord = meta.get("target_coord")
        values_full = meta.get("values_full")
        train_slice = meta.get("train_slice")
        target_idx = meta.get("target_idx")
        neighbor_idx = meta.get("neighbor_idx")

        if (
            neighbor_coords is None or target_coord is None
            or values_full is None or train_slice is None
            or target_idx is None or neighbor_idx is None
        ):
            self._explain_dict = {"error": "缺 meta 必要欄位;fallback uniform mean"}
            self._global_mean = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._fitted = True
            return self

        target_coord_arr = np.asarray(target_coord, dtype=np.float64)
        test_slice = meta.get("test_slice")
        K = len(neighbor_idx)

        train_values = values_full[train_slice]
        T_train = train_values.shape[0]
        train_all_idx = list(neighbor_idx) + [int(target_idx)]
        train_all_coords = np.vstack([neighbor_coords, target_coord_arr[None, :]])

        train_block = train_values[:, train_all_idx]
        finite_tr = np.isfinite(train_block)
        rows_tr, cols_tr = np.where(finite_tr)
        v_tr = train_block[rows_tr, cols_tr]
        xy_tr = train_all_coords[cols_tr]
        t_tr = rows_tr.astype(np.float64)

        v_te = np.empty(0)
        xy_te = np.empty((0, 2))
        t_te = np.empty(0)
        if test_slice is not None:
            test_values = values_full[test_slice]
            test_block = test_values[:, list(neighbor_idx)]
            finite_te = np.isfinite(test_block)
            rows_te, cols_te = np.where(finite_te)
            v_te = test_block[rows_te, cols_te]
            xy_te = neighbor_coords[cols_te]
            t_te = (T_train + rows_te).astype(np.float64)

        values_flat = np.concatenate([v_tr, v_te])
        xy_flat = np.vstack([xy_tr, xy_te])
        time_flat = np.concatenate([t_tr, t_te])
        n_finite = len(values_flat)
        if n_finite < 50:
            self._explain_dict = {"error": f"finite cells {n_finite} < 50; fallback"}
            self._global_mean = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._fitted = True
            return self

        xy_meters = _local_xy_from_lonlat(xy_flat, target_coord_arr[0], target_coord_arr[1])
        rng = np.random.default_rng(self.seed)
        if n_finite > self.max_train:
            keep = rng.choice(n_finite, size=self.max_train, replace=False)
        else:
            keep = np.arange(n_finite)
        X_sub = np.column_stack([xy_meters[keep], time_flat[keep]])
        y_sub = values_flat[keep]
        n_sub = len(keep)

        self._global_mean = float(y_sub.mean())
        y_centered = y_sub - self._global_mean

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        device = self._device

        train_x = torch.tensor(X_sub, dtype=torch.float64, device=device)
        train_y = torch.tensor(y_centered, dtype=torch.float64, device=device)

        class _Model(gpytorch.models.ExactGP):
            def __init__(self, tx, ty, lk):
                super().__init__(tx, ty, lk)
                self.mean_module = gpytorch.means.ConstantMean()
                space_k = gpytorch.kernels.RBFKernel(active_dims=[0, 1])
                time_k = gpytorch.kernels.RBFKernel(active_dims=[2])
                self.covar_module = gpytorch.kernels.ScaleKernel(space_k * time_k)

            def forward(self, x):
                return gpytorch.distributions.MultivariateNormal(
                    self.mean_module(x), self.covar_module(x)
                )

        likelihood = gpytorch.likelihoods.GaussianLikelihood().to(device).double()
        model = _Model(train_x, train_y, likelihood).to(device).double()

        empirical_var = float(np.var(y_centered)) if np.var(y_centered) > 0 else 1.0
        with torch.no_grad():
            model.covar_module.outputscale = empirical_var
            kk = model.covar_module.base_kernel.kernels
            kk[0].lengthscale = float(self.lengthscale_init_space_m)
            kk[1].lengthscale = float(self.lengthscale_init_time_h)
            likelihood.noise = max(empirical_var * 0.05, self.noise_floor, 1e-6)

        model.train()
        likelihood.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=self.lr)
        mll = gpytorch.mlls.ExactMarginalLogLikelihood(likelihood, model)

        last_loss = float("nan")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for _ in range(self.n_iter):
                optimizer.zero_grad()
                try:
                    out = model(train_x)
                    loss = -mll(out, train_y)
                except RuntimeError:
                    break
                loss.backward()
                optimizer.step()
                last_loss = float(loss.detach().item())

        try:
            base_kernels = model.covar_module.base_kernel.kernels
            lengthscale_s = float(base_kernels[0].lengthscale.item())
            lengthscale_t = float(base_kernels[1].lengthscale.item())
            outputscale = float(model.covar_module.outputscale.item())
            noise = max(float(likelihood.noise.item()), self.noise_floor)
        except Exception as e:
            self._explain_dict = {"error": f"hyperparam extract: {e}"}
            self._model = None
            self._fitted = True
            return self

        model.eval()
        likelihood.eval()
        self._model = model
        self._likelihood = likelihood
        self._train_x = train_x
        self._train_y = train_y
        self._explain_dict = {
            "kernel": "separable RBF_s × RBF_t",
            "lengthscale_space_m": lengthscale_s,
            "lengthscale_time_h": lengthscale_t,
            "outputscale": outputscale,
            "noise": noise,
            "n_train_used": n_sub,
            "n_train_pool": n_finite,
            "final_loss": last_loss,
            "device": str(device),
        }
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        import gpytorch
        import torch

        if self._model is None:
            return np.full(X.shape[0], self._global_mean, dtype=np.float64)
        test_rows = meta.get("test_rows")
        test_slice = meta.get("test_slice")
        if test_rows is None or test_slice is None:
            return np.full(X.shape[0], self._global_mean, dtype=np.float64)

        test_offset = test_slice.start
        n = len(test_rows)
        test_hours = (test_offset + np.asarray(test_rows)).astype(np.float64)
        X_q = np.column_stack([np.zeros((n, 2)), test_hours])
        x_t = torch.tensor(X_q, dtype=torch.float64, device=self._device)

        with torch.no_grad(), gpytorch.settings.fast_pred_var():
            try:
                preds = self._likelihood(self._model(x_t))
                mean = preds.mean.detach().cpu().numpy()
            except RuntimeError:
                return np.full(n, self._global_mean, dtype=np.float64)

        y_pred = mean + self._global_mean
        return np.clip(y_pred, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        return self._explain_dict
