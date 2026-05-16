"""Ordinary Kriging(Phase 3a)。

對每個 target,把 K 個鄰站 + target 共 K+1 個位置的時序值拿來:
  1. 計算所有 pair 的「(z_a(t) - z_b(t))^2 / 2」聚合到距離 bin → 經驗 variogram
  2. 用 gstools 的 spherical / exponential / gaussian 模型擬合 (sill, range, nugget)
  3. 解 Ordinary Kriging 系統 (K+1)×(K+1) 拿 weights
  4. 預測 = weights @ neighbor 值

可解釋性 9/10:variogram 三參數 (sill, range, nugget) + 模型名是常見地統計術語,
``.explain()`` 回傳這些 + chosen model + 經驗 variogram 點數。
"""
from __future__ import annotations

import logging
from typing import Any

import gstools as gs
import numpy as np

from ..base import BaseImputer
from ..registry import register

logger = logging.getLogger(__name__)


_VARIOGRAM_MODELS: dict[str, type] = {
    "spherical":   gs.Spherical,
    "exponential": gs.Exponential,
    "gaussian":    gs.Gaussian,
}


def _haversine_pair(a: np.ndarray, b: np.ndarray) -> float:
    """a, b: (lon, lat) 度。回傳公尺。"""
    R = 6_371_000.0
    rlon1, rlat1 = np.radians(a[0]), np.radians(a[1])
    rlon2, rlat2 = np.radians(b[0]), np.radians(b[1])
    dlon = rlon2 - rlon1
    dlat = rlat2 - rlat1
    h = np.sin(dlat / 2) ** 2 + np.cos(rlat1) * np.cos(rlat2) * np.sin(dlon / 2) ** 2
    return 2 * R * float(np.arcsin(np.sqrt(h)))


def _haversine_matrix(coords: np.ndarray) -> np.ndarray:
    """coords: (M, 2) [lon, lat]。回傳 M×M 公尺距離矩陣。"""
    M = coords.shape[0]
    D = np.zeros((M, M))
    for i in range(M):
        for j in range(i + 1, M):
            D[i, j] = D[j, i] = _haversine_pair(coords[i], coords[j])
    return D


@register
class OrdinaryKrigingImputer(BaseImputer):
    """Ordinary Kriging:從 train 段值與 K+1 站位置擬 variogram,解 OK 系統取 weights。

    Params(沒有 default):
        variogram_model: 'spherical' | 'exponential' | 'gaussian'
        n_bins:          int ≥ 3 — 經驗 variogram 距離 bin 數
        max_range_m:     float > 0 — 經驗 variogram 最大距離(公尺),超過此範圍 pair 不算
        nugget:          'fit' | float ≥ 0 — 'fit' 表 nugget 也擬合;float 表固定
    """

    name = "kriging"
    tier = 3
    explainability = 9

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        for k in ("variogram_model", "n_bins", "max_range_m", "nugget"):
            if k not in params:
                raise KeyError(f"Kriging 需 `{k}` 參數(YAML 設,沒有 default)")
        self.variogram_model = str(params["variogram_model"])
        if self.variogram_model not in _VARIOGRAM_MODELS:
            raise ValueError(
                f"variogram_model 須在 {sorted(_VARIOGRAM_MODELS)},收到 {self.variogram_model!r}"
            )
        self.n_bins = int(params["n_bins"])
        self.max_range_m = float(params["max_range_m"])
        nug = params["nugget"]
        if isinstance(nug, str):
            if nug != "fit":
                raise ValueError("nugget 若為字串只能是 'fit'")
            self.nugget_fit: bool = True
            self.nugget_fixed: float = 0.0
        else:
            self.nugget_fit = False
            self.nugget_fixed = float(nug)
            if self.nugget_fixed < 0:
                raise ValueError(f"nugget 需 ≥ 0,收到 {self.nugget_fixed}")
        if self.n_bins < 3:
            raise ValueError(f"n_bins ≥ 3,收到 {self.n_bins}")
        if self.max_range_m <= 0:
            raise ValueError(f"max_range_m > 0,收到 {self.max_range_m}")

        self._weights: np.ndarray | None = None
        self._fit_mean_y: float = 0.0
        self._explain: dict[str, Any] | None = None

    # ---- variogram fit -------------------------------------------------------

    def _fit_variogram(
        self,
        z_all: np.ndarray,        # (T, M=K+1)
        coords_all: np.ndarray,   # (M, 2)
    ) -> tuple[gs.CovModel, dict[str, Any]]:
        """從 K+1 站的 train 段時序擬 variogram。

        經驗 variogram 用時間 pooled 方式——每個 (i,j) pair 在每個 valid 時刻貢獻一個
        (z_i - z_j)^2 / 2,bin 後平均。
        """
        T, M = z_all.shape
        D = _haversine_matrix(coords_all)

        # pair indices (i < j)
        ii, jj = np.triu_indices(M, k=1)
        d_pairs = D[ii, jj]  # (P,)
        # 過濾超過 max_range_m
        keep = d_pairs <= self.max_range_m
        if keep.sum() < 3:
            # K+1 站全部太遠 → 沒辦法擬;落到「fallback weights = 等權平均」
            return None, {"error": "no pairs within max_range_m"}
        ii, jj, d_pairs = ii[keep], jj[keep], d_pairs[keep]

        # 對每個 pair 算 time-pooled (z_i - z_j)^2 / 2 平均
        gamma_per_pair = np.full(len(d_pairs), np.nan)
        n_per_pair = np.zeros(len(d_pairs), dtype=int)
        for p, (i, j) in enumerate(zip(ii, jj)):
            zi = z_all[:, i]; zj = z_all[:, j]
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
        w_valid = n_per_pair[valid].astype(float)  # 加權:時序樣本多的 pair 比較信任

        # bin
        bins = np.linspace(0, self.max_range_m, self.n_bins + 1)
        bin_idx = np.digitize(d_valid, bins) - 1
        bin_idx = np.clip(bin_idx, 0, self.n_bins - 1)
        bin_center = np.full(self.n_bins, np.nan)
        bin_gamma  = np.full(self.n_bins, np.nan)
        bin_count  = np.zeros(self.n_bins, dtype=int)
        for b in range(self.n_bins):
            sel = bin_idx == b
            if sel.sum() == 0:
                continue
            bin_count[b] = int(sel.sum())
            bin_center[b] = float(np.average(d_valid[sel], weights=w_valid[sel]))
            bin_gamma[b]  = float(np.average(g_valid[sel], weights=w_valid[sel]))

        finite = np.isfinite(bin_center) & np.isfinite(bin_gamma)
        if finite.sum() < 3:
            return None, {"error": "not enough binned points"}

        # 用 gstools 模型擬合
        model_cls = _VARIOGRAM_MODELS[self.variogram_model]
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
            "sill":    float(model.sill),    # var + nugget
            "var":     float(model.var),     # sill - nugget
            "range":   float(model.len_scale),
            "nugget":  float(model.nugget),
            "bin_center":  bin_center[finite].tolist(),
            "bin_gamma":   bin_gamma[finite].tolist(),
            "bin_count":   bin_count[finite].tolist(),
            "n_pairs_used": int(finite.sum()),
        }
        return model, diag

    # ---- kriging system -----------------------------------------------------

    def _compute_kriging_weights(
        self,
        model: gs.CovModel,
        neighbor_coords: np.ndarray,    # (K, 2)
        target_coord: np.ndarray,       # (2,)
    ) -> np.ndarray:
        K = neighbor_coords.shape[0]
        D_nn = _haversine_matrix(neighbor_coords)  # K × K
        d_nt = np.array([_haversine_pair(neighbor_coords[i], target_coord) for i in range(K)])

        # Ordinary Kriging:用 variogram 構建 (K+1) × (K+1) 系統
        A = np.ones((K + 1, K + 1))
        A[K, K] = 0.0
        A[:K, :K] = model.variogram(D_nn)
        b = np.ones(K + 1)
        b[:K] = model.variogram(d_nt)

        # Tikhonov 正則化:近距離 K 鄰站常擠在同一點(高雄都會區),
        # γ matrix 兩 row 近乎相同 → 數值奇異。加 jitter 到對角線。
        jitter = max(float(model.nugget) * 0.01, float(model.sill) * 1e-6, 1e-9)
        A[:K, :K] += jitter * np.eye(K)

        try:
            sol = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            sol = np.linalg.lstsq(A, b, rcond=None)[0]
        return sol[:K]

    # ---- BaseImputer API ----------------------------------------------------

    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "OrdinaryKrigingImputer":
        K = X.shape[1]
        neighbor_coords = meta.get("neighbor_coords")
        target_coord = meta.get("target_coord")
        if neighbor_coords is None or target_coord is None:
            # 沒座標 → 退回 mean predictor
            self._weights = np.ones(K, dtype=np.float64) / K
            self._fit_mean_y = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._explain = {"error": "missing coords; fallback to uniform mean"}
            self._fitted = True
            return self

        target_coord = np.asarray(target_coord, dtype=np.float64)

        # 把 K 鄰站 + target 自己 一起當作 K+1 個站做 variogram
        # train 段:y 是 target 自己,X 是 K 鄰站
        finite = np.isfinite(y)
        y_f = y[finite]
        X_f = X[finite]
        n_train = len(y_f)
        if n_train < 10:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._fit_mean_y = float(np.nanmean(y)) if np.isfinite(y).any() else 0.0
            self._explain = {"error": "n_train < 10; fallback to uniform mean"}
            self._fitted = True
            return self

        z_all = np.column_stack([X_f, y_f])  # (n_train, K+1),最後一欄 = target
        coords_all = np.vstack([neighbor_coords, target_coord[None, :]])  # (K+1, 2)

        model, diag = self._fit_variogram(z_all, coords_all)
        if model is None:
            self._weights = np.ones(K, dtype=np.float64) / K
            self._fit_mean_y = float(np.nanmean(y_f))
            self._explain = {"error": diag.get("error", "unknown"), "fallback": "uniform mean"}
            self._fitted = True
            return self

        weights = self._compute_kriging_weights(model, neighbor_coords, target_coord)
        weights_sum = float(weights.sum()) if np.isfinite(weights).all() else float("nan")
        # weights 應該 Σ≈1 且每個分量大致在 [-1, +1] 之間(極端時到 ±2.5)。
        # max|w| > 3 通常代表 γ matrix 數值崩壞(K 鄰站太相似)→ 退 uniform mean。
        # 這個 threshold 在 1287 站高雄資料上會讓 ~10–15% 站 fallback,
        # 但留住的站有可靠 OK 預測,RMSE 才不會被個別 outlier 拖死
        weight_max_abs = float(np.max(np.abs(weights))) if np.isfinite(weights).all() else float("nan")
        if (not np.isfinite(weights).all()
                or abs(weights_sum - 1.0) > 0.1
                or weight_max_abs > 3.0):
            logger.debug("kriging weights degenerate for %s (sum=%s, max|w|=%s), fallback",
                         meta.get("target_station_id"), weights_sum, weight_max_abs)
            self._weights = np.ones(K, dtype=np.float64) / K
            self._fit_mean_y = float(np.nanmean(y_f))
            self._explain = {
                "error": "kriging weights degenerate",
                "weights_sum": weights_sum,
                "weight_max_abs": weight_max_abs,
                "fallback": "uniform mean",
                "variogram_params": {
                    "sill":   diag["sill"],
                    "range":  diag["range"],
                    "nugget": diag["nugget"],
                },
            }
            self._fitted = True
            return self
        self._weights = weights

        self._fit_mean_y = float(np.nanmean(y_f))
        self._explain = {
            "variogram_model": self.variogram_model,
            "variogram_params": {
                "sill":   diag["sill"],
                "range":  diag["range"],
                "nugget": diag["nugget"],
            },
            "weights":          self._weights.tolist(),
            "weights_sum":      weights_sum,
            "n_train":          n_train,
            "n_pairs_used":     diag["n_pairs_used"],
        }
        self._fitted = True
        return self

    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        if not self._fitted or self._weights is None:
            raise RuntimeError("OrdinaryKrigingImputer 還沒 fit")
        # NaN-safe:對每個 row,缺失鄰站「假裝是 fit 期 mean」(避免發散)。
        # 這比「除以 valid weight 和」穩健——後者在 valid weight 接近 0 時會炸
        w = self._weights
        valid = np.isfinite(X)
        X_filled = np.where(valid, X, self._fit_mean_y)
        w_broad = np.broadcast_to(w, X.shape).astype(np.float64)
        num = (X_filled * w_broad).sum(axis=1)
        # 物理約束:PM2.5 不會 < 0,實務上不會 > 500 µg/m³。clip 以防 OK 數值
        # 殘留異常(weight × 大值的線性組合偶爾會跑掉)。
        out = np.clip(num, 0.0, 500.0)
        return out

    def explain(self) -> dict[str, Any] | None:
        return self._explain
