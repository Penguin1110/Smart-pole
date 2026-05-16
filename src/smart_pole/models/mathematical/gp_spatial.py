"""Spatial Gaussian Process(Phase 3a)。

對每個 target 把 K+1 個位置(K 鄰站 + target 自己)的 train 段時間平均值當作
GP 訓練點,用 gpytorch ExactGP + RBF 或 Matern52 kernel 擬合 lengthscale /
output_scale / noise。

預測時把擬好的 kernel 拿出來算 K_*c @ (K_cc + σ² I)^{-1},得到對 target
的 K 個權重,然後對每個 timestamp 做 weighted sum。本質上是 OK 的近親
(同樣是「kernel-based 線性 BLUP」),但用 ML 最大化邊際似然挑 kernel 參數,
而非 Kriging 的 variogram 二階矩擬合。

可解釋性 8/10:lengthscale / output_scale / noise 三個學到的數字物理意義明確,
但 gpytorch 內部優化是 black-box,所以扣 2 分。

GPU 需求:**不需要**——K+1 個點是極小問題,CPU 反而比資料搬到 GPU 來回快。
ST-GP(Phase 3b)再開 GPU。
"""
from __future__ import annotations

import logging
import warnings
from typing import Any

import gpytorch
import numpy as np
import torch

from ..base import BaseImputer
from ..registry import register

logger = logging.getLogger(__name__)


class _SpatialGPModel(gpytorch.models.ExactGP):
    """最小 ExactGP:ConstantMean + ScaleKernel(RBF / Matern52)。"""

    def __init__(self, train_x, train_y, likelihood, kernel_type: str) -> None:
        super().__init__(train_x, train_y, likelihood)
        self.mean_module = gpytorch.means.ConstantMean()
        if kernel_type == "rbf":
            base = gpytorch.kernels.RBFKernel()
        elif kernel_type == "matern52":
            base = gpytorch.kernels.MaternKernel(nu=2.5)
        else:
            raise ValueError(f"未知 kernel: {kernel_type!r}")
        self.covar_module = gpytorch.kernels.ScaleKernel(base)

    def forward(self, x):
        return gpytorch.distributions.MultivariateNormal(
            self.mean_module(x), self.covar_module(x),
        )


def _local_xy_from_lonlat(
    coords: np.ndarray, origin_lon: float, origin_lat: float
) -> np.ndarray:
    """把 (N, 2) [lon, lat] 投影到以 (origin_lon, origin_lat) 為原點的 meter 平面。

    對台灣尺度(~30km)夠用——緯度方向 1° ≈ 111.32 km,經度方向乘 cos(lat)。
    """
    coords = np.asarray(coords, dtype=np.float64)
    lat0_rad = np.radians(origin_lat)
    x = (coords[:, 0] - origin_lon) * np.cos(lat0_rad) * 111_320.0
    y = (coords[:, 1] - origin_lat) * 111_320.0
    return np.column_stack([x, y])


@register
class SpatialGPImputer(BaseImputer):
    """Per-target Spatial GP:fit kernel on K+1 站位置,predict 走 kernel weights。

    Params(沒有 default):
        kernel:              'rbf' | 'matern52'
        n_iter:              int ≥ 1   — Adam 迭代次數
        lr:                  float > 0 — Adam 學習率
        lengthscale_init_m:  float > 0 — kernel lengthscale 初始值(meters)
        noise_floor:         float ≥ 0 — noise variance 下界(避免擬到 0)
    """

    name = "spatial_gp"
    tier = 3
    explainability = 8
    requires_gpu = False    # K+1=11 點問題,CPU 即可;ST-GP 才需要 GPU

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("kernel", "n_iter", "lr", "lengthscale_init_m", "noise_floor"):
            if k not in params:
                raise KeyError(f"SpatialGP 需 `{k}` 參數(YAML 設,沒有 default)")
        self.kernel = str(params["kernel"])
        if self.kernel not in {"rbf", "matern52"}:
            raise ValueError(f"kernel 須 rbf|matern52,收到 {self.kernel!r}")
        self.n_iter = int(params["n_iter"])
        self.lr = float(params["lr"])
        self.lengthscale_init_m = float(params["lengthscale_init_m"])
        self.noise_floor = float(params["noise_floor"])
        if self.n_iter < 1:
            raise ValueError(f"n_iter ≥ 1,收到 {self.n_iter}")
        if self.lr <= 0:
            raise ValueError(f"lr > 0,收到 {self.lr}")
        if self.lengthscale_init_m <= 0:
            raise ValueError(f"lengthscale_init_m > 0,收到 {self.lengthscale_init_m}")
        if self.noise_floor < 0:
            raise ValueError(f"noise_floor ≥ 0,收到 {self.noise_floor}")

        self._weights: np.ndarray | None = None
        self._global_mean: float = 0.0
        self._explain: dict[str, Any] | None = None

    # ---- BaseImputer API ----------------------------------------------------

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "SpatialGPImputer":
        K = X.shape[1]
        neighbor_coords = meta.get("neighbor_coords")
        target_coord = meta.get("target_coord")

        if neighbor_coords is None or target_coord is None:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._global_mean = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._explain = {"error": "missing coords; fallback to uniform mean"}
            self._fitted = True
            return self

        target_coord = np.asarray(target_coord, dtype=np.float64)

        # 每站 train 平均值(K+1)
        finite = np.isfinite(y)
        y_f = y[finite]
        X_f = X[finite]
        if len(y_f) < 10:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._global_mean = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._explain = {"error": "n_train < 10; fallback to uniform mean"}
            self._fitted = True
            return self

        mean_target = float(y_f.mean())
        mean_neighbors = np.nanmean(X_f, axis=0)
        if not np.isfinite(mean_neighbors).all():
            # 至少一個鄰站全 NaN
            mean_neighbors = np.where(np.isfinite(mean_neighbors), mean_neighbors, mean_target)

        means_all = np.concatenate([mean_neighbors, [mean_target]])
        coords_all = np.vstack([neighbor_coords, target_coord[None, :]])

        global_mean = float(means_all.mean())
        centered = means_all - global_mean
        self._global_mean = global_mean

        # 經度緯度 → meters 平面
        xy = _local_xy_from_lonlat(coords_all, target_coord[0], target_coord[1])
        train_x = torch.tensor(xy, dtype=torch.float64)
        train_y = torch.tensor(centered, dtype=torch.float64)

        likelihood = gpytorch.likelihoods.GaussianLikelihood()
        try:
            model = _SpatialGPModel(train_x, train_y, likelihood, self.kernel).double()
        except ValueError as e:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._explain = {"error": str(e), "fallback": "uniform mean"}
            self._fitted = True
            return self

        # 初始值
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
                    output = model(train_x)
                    loss = -mll(output, train_y)
                except RuntimeError:
                    break
                loss.backward()
                optimizer.step()

        # 取出擬合超參
        try:
            lengthscale = float(model.covar_module.base_kernel.lengthscale.item())
            outputscale = float(model.covar_module.outputscale.item())
            noise       = max(float(likelihood.noise.item()), self.noise_floor)
        except Exception as e:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._explain = {"error": f"hyperparam extract failed: {e}", "fallback": "uniform mean"}
            self._fitted = True
            return self

        # 算 kernel weights: K_*c @ (K_cc + noise * I)^{-1}
        model.eval()
        likelihood.eval()
        with torch.no_grad():
            neighbor_x = train_x[:K]
            target_x = train_x[K:K + 1]
            K_nn = model.covar_module(neighbor_x, neighbor_x).to_dense().numpy()
            K_target_nb = model.covar_module(target_x, neighbor_x).to_dense().numpy().flatten()

        A = K_nn + noise * np.eye(K)
        try:
            weights = np.linalg.solve(A, K_target_nb)
        except np.linalg.LinAlgError:
            weights = np.linalg.lstsq(A, K_target_nb, rcond=None)[0]

        # weights 合理性檢查(同 Kriging 邏輯)
        weights_sum = float(weights.sum()) if np.isfinite(weights).all() else float("nan")
        weight_max_abs = float(np.max(np.abs(weights))) if np.isfinite(weights).all() else float("nan")
        if (not np.isfinite(weights).all()) or weight_max_abs > 3.0:
            logger.debug("GP weights degenerate for %s (max|w|=%s), fallback",
                         meta.get("target_station_id"), weight_max_abs)
            self._weights = np.ones(K, dtype=np.float64) / K
            self._explain = {
                "error":           "weights degenerate",
                "weight_max_abs":  weight_max_abs,
                "lengthscale_m":   lengthscale,
                "outputscale":     outputscale,
                "noise":           noise,
                "fallback":        "uniform mean",
            }
            self._fitted = True
            return self

        self._weights = weights
        self._explain = {
            "kernel":         self.kernel,
            "lengthscale_m":  lengthscale,
            "outputscale":    outputscale,
            "noise":          noise,
            "weights":        weights.tolist(),
            "weights_sum":    weights_sum,
            "n_train_means":  int(len(means_all)),
        }
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if not self._fitted or self._weights is None:
            raise RuntimeError("SpatialGPImputer 還沒 fit")
        # NaN 處理:用全域平均「補上去」,讓對應 weight 貢獻變 (1 - Σ w_valid) * mean
        # 與 Kriging 採同一策略
        w = self._weights
        X_filled = np.where(np.isfinite(X), X, self._global_mean)
        sum_w = float(w.sum())
        # GP predict 公式:y = mean + K_*c K_cc^{-1} (y_obs - mean)
        #               = mean + Σ w_i (x_i - mean)
        #               = (1 - Σw) * mean + Σ w_i x_i
        pred = X_filled @ w + (1.0 - sum_w) * self._global_mean
        return np.clip(pred, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        return self._explain
