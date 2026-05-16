"""Spatio-Temporal GP(Phase 3b)。

對每個 target,建一個 separable kernel 的 gpytorch ExactGP:
    k_st((s, t), (s', t')) = σ² · RBF_s(s, s') · RBF_t(t, t')
時間 lengthscale 與空間 lengthscale 分開學;noise 一個 σ²。

訓練資料:K 鄰站 + target 在 train_slice 內全部有觀測的格子,
打散成 (lon_m, lat_m, time_hr) 三維特徵向量。為了控住 CUDA 算力,
**隨機 subsample 到 ``max_train`` 個 conditioning points**(預設 1500)。

預測:對每個 test_row(target 被 mask 的時刻 t),用 GP 條件後驗預測
``(target_pos, t)`` 的值;test 時的 K 鄰站當下值 **也** 加進 conditioning,
模擬「real-time imputation 時其他竿體還在報」。

可解釋性 8/10:
  - spatial lengthscale + temporal lengthscale + output_scale + noise
    四個學到的數字物理意義明確
  - gpytorch 內部優化是 black-box,扣 2 分

GPU:``requires_gpu = True``——大量目標 × 中型 conditioning(1500 點)很適合 CUDA。
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


def _local_xy_from_lonlat(
    coords: np.ndarray, origin_lon: float, origin_lat: float
) -> np.ndarray:
    """把 (N, 2) [lon, lat] 投影到以 origin 為原點的 meter 平面。"""
    coords = np.asarray(coords, dtype=np.float64)
    lat0_rad = np.radians(origin_lat)
    x = (coords[:, 0] - origin_lon) * np.cos(lat0_rad) * 111_320.0
    y = (coords[:, 1] - origin_lat) * 111_320.0
    return np.column_stack([x, y])


class _STGPModel(gpytorch.models.ExactGP):
    """ExactGP with separable spatial × temporal RBF kernel.

    輸入 X: (N, 3) — col 0,1 = spatial xy in meters,col 2 = time in hours.
    """

    def __init__(self, train_x, train_y, likelihood) -> None:
        super().__init__(train_x, train_y, likelihood)
        self.mean_module = gpytorch.means.ConstantMean()
        space_k = gpytorch.kernels.RBFKernel(active_dims=[0, 1])
        time_k  = gpytorch.kernels.RBFKernel(active_dims=[2])
        self.covar_module = gpytorch.kernels.ScaleKernel(space_k * time_k)

    def forward(self, x):
        return gpytorch.distributions.MultivariateNormal(
            self.mean_module(x), self.covar_module(x),
        )


@register
class STGPImputer(BaseImputer):
    """Per-target Spatio-Temporal GP。

    Params(沒有 default):
        n_iter:                 int ≥ 1   — Adam 迭代次數
        lr:                     float > 0 — Adam lr
        max_train:              int ≥ 50  — conditioning set 上限(隨機 subsample)
        lengthscale_init_space_m: float > 0 — 空間 lengthscale 初始值 (公尺)
        lengthscale_init_time_h:  float > 0 — 時間 lengthscale 初始值 (小時)
        noise_floor:            float ≥ 0 — noise 下界
        seed:                   int        — subsample 用的 RNG seed
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
                raise KeyError(f"STGP 需 `{k}` 參數(YAML 設,沒有 default)")
        self.n_iter   = int(params["n_iter"])
        self.lr       = float(params["lr"])
        self.max_train = int(params["max_train"])
        self.lengthscale_init_space_m = float(params["lengthscale_init_space_m"])
        self.lengthscale_init_time_h  = float(params["lengthscale_init_time_h"])
        self.noise_floor = float(params["noise_floor"])
        self.seed = int(params["seed"])

        for name, v in (
            ("n_iter", self.n_iter), ("max_train", self.max_train),
        ):
            if v < 1:
                raise ValueError(f"{name} ≥ 1,收到 {v}")
        for name, v in (
            ("lr", self.lr),
            ("lengthscale_init_space_m", self.lengthscale_init_space_m),
            ("lengthscale_init_time_h",  self.lengthscale_init_time_h),
        ):
            if v <= 0:
                raise ValueError(f"{name} > 0,收到 {v}")
        if self.noise_floor < 0:
            raise ValueError(f"noise_floor ≥ 0,收到 {self.noise_floor}")
        if self.max_train < 50:
            raise ValueError(f"max_train ≥ 50,收到 {self.max_train}")

        self._device: torch.device | None = None
        self._model: _STGPModel | None = None
        self._likelihood: gpytorch.likelihoods.GaussianLikelihood | None = None
        self._train_x: torch.Tensor | None = None
        self._train_y: torch.Tensor | None = None
        self._global_mean: float = 0.0
        self._target_xy: np.ndarray | None = None
        self._explain: dict[str, Any] | None = None

    # ---- helpers -------------------------------------------------------------

    def _pick_device(self) -> torch.device:
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    # ---- BaseImputer API ----------------------------------------------------

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "STGPImputer":
        neighbor_coords = meta.get("neighbor_coords")
        target_coord = meta.get("target_coord")
        values_full = meta.get("values_full")
        train_slice = meta.get("train_slice")
        target_idx = meta.get("target_idx")
        neighbor_idx = meta.get("neighbor_idx")

        if (neighbor_coords is None or target_coord is None
                or values_full is None or train_slice is None
                or target_idx is None or neighbor_idx is None):
            self._explain = {"error": "缺 meta 必要欄位;fallback uniform mean"}
            self._global_mean = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._fitted = True
            return self

        target_coord_arr = np.asarray(target_coord, dtype=np.float64)
        test_slice = meta.get("test_slice")
        K = len(neighbor_idx)

        # 構造 (station_idx, time_hr, value) 三維資料庫
        train_values = values_full[train_slice]   # (T_train, S)
        T_train = train_values.shape[0]
        # K 鄰站 + target
        train_all_idx = list(neighbor_idx) + [int(target_idx)]
        train_all_coords = np.vstack([neighbor_coords, target_coord_arr[None, :]])  # (K+1, 2)

        # train 段:K 鄰站 + target 整段時序
        train_block = train_values[:, train_all_idx]  # (T_train, K+1)
        finite_tr = np.isfinite(train_block)
        rows_tr, cols_tr = np.where(finite_tr)
        v_tr  = train_block[rows_tr, cols_tr]
        xy_tr = train_all_coords[cols_tr]
        t_tr  = rows_tr.astype(np.float64)

        # **關鍵**:test 段也把 K 鄰站(不含 target)當 conditioning 餵進來。
        # 否則 GP 要往 test 段(離 train 數百 hour)外推,RBF kernel 會崩潰到 prior mean。
        # 鄰站當下值不是 target 的 mask 對象,使用無洩漏(同 Phase 1/2 慣例)。
        test_block = None
        v_te = np.empty(0); xy_te = np.empty((0, 2)); t_te = np.empty(0)
        if test_slice is not None:
            test_values = values_full[test_slice]
            test_block = test_values[:, list(neighbor_idx)]  # (T_test, K)
            finite_te = np.isfinite(test_block)
            rows_te, cols_te = np.where(finite_te)
            v_te  = test_block[rows_te, cols_te]
            xy_te = neighbor_coords[cols_te]
            t_te  = (T_train + rows_te).astype(np.float64)

        values_flat = np.concatenate([v_tr, v_te])
        xy_flat = np.vstack([xy_tr, xy_te])
        time_flat = np.concatenate([t_tr, t_te])
        n_finite = len(values_flat)
        if n_finite < 50:
            self._explain = {"error": f"finite cells {n_finite} < 50; fallback"}
            self._global_mean = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._fitted = True
            return self

        # 投影到 target 原點的米座標
        xy_meters = _local_xy_from_lonlat(xy_flat, target_coord_arr[0], target_coord_arr[1])
        # subsample
        rng = np.random.default_rng(self.seed)
        if n_finite > self.max_train:
            keep = rng.choice(n_finite, size=self.max_train, replace=False)
        else:
            keep = np.arange(n_finite)
        X_sub = np.column_stack([xy_meters[keep], time_flat[keep]])  # (n_sub, 3)
        y_sub = values_flat[keep]
        n_sub = len(keep)

        # 中心化(GP 假設 ConstantMean 接近 0)
        self._global_mean = float(y_sub.mean())
        y_centered = y_sub - self._global_mean

        self._device = self._pick_device()
        device = self._device

        train_x = torch.tensor(X_sub, dtype=torch.float64, device=device)
        train_y = torch.tensor(y_centered, dtype=torch.float64, device=device)

        likelihood = gpytorch.likelihoods.GaussianLikelihood().to(device).double()
        model = _STGPModel(train_x, train_y, likelihood).to(device).double()

        # 初始值
        empirical_var = float(np.var(y_centered)) if np.var(y_centered) > 0 else 1.0
        with torch.no_grad():
            model.covar_module.outputscale = empirical_var
            # base = ScaleKernel(space_k * time_k);access base_kernel.kernels
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
                except RuntimeError as e:
                    logger.debug("STGP fit failed iter loop: %s", e)
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
            self._explain = {"error": f"hyperparam extract: {e}; fallback"}
            self._model = None
            self._fitted = True
            return self

        model.eval()
        likelihood.eval()

        self._model = model
        self._likelihood = likelihood
        self._train_x = train_x
        self._train_y = train_y
        self._target_xy = np.array([0.0, 0.0], dtype=np.float64)  # target 在 origin
        self._explain = {
            "kernel":              "separable RBF_s × RBF_t",
            "lengthscale_space_m": lengthscale_s,
            "lengthscale_time_h":  lengthscale_t,
            "outputscale":         outputscale,
            "noise":               noise,
            "n_train_used":        n_sub,
            "n_train_pool":        n_finite,
            "final_loss":          last_loss,
            "device":              str(device),
        }
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if self._model is None:
            return np.full(X.shape[0], self._global_mean, dtype=np.float64)
        assert self._target_xy is not None
        test_rows = meta.get("test_rows")
        test_slice = meta.get("test_slice")
        if test_rows is None or test_slice is None:
            return np.full(X.shape[0], self._global_mean, dtype=np.float64)

        test_offset = test_slice.start
        n = len(test_rows)
        # query points: (target_xy=[0,0], hour=test_offset + test_row)
        test_hours = (test_offset + np.asarray(test_rows)).astype(np.float64)
        X_q = np.column_stack([
            np.zeros((n, 2)),    # target xy = origin
            test_hours,
        ])
        x_t = torch.tensor(X_q, dtype=torch.float64, device=self._device)

        with torch.no_grad(), gpytorch.settings.fast_pred_var():
            try:
                preds = self._likelihood(self._model(x_t))
                mean = preds.mean.detach().cpu().numpy()
            except RuntimeError as e:
                logger.debug("STGP predict failed: %s", e)
                return np.full(n, self._global_mean, dtype=np.float64)

        # 加回 global mean,然後物理範圍 clip
        y_pred = mean + self._global_mean
        return np.clip(y_pred, 0.0, 500.0)

    def explain(self) -> dict[str, Any] | None:
        return self._explain
