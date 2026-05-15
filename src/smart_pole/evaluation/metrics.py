"""補值誤差三件套:MAE、RMSE、R²。

跳過 y_true 或 y_pred 為 NaN 的樣本(模型偶爾會吐 NaN——例如 K 個鄰站全 NaN
時的 nanmean)。所有 metric 在沒有有效樣本時回傳 NaN,讓上游能感知問題。
"""
from __future__ import annotations

import numpy as np


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    if y_true.shape != y_pred.shape:
        raise ValueError(f"shape 不一致:y_true={y_true.shape}, y_pred={y_pred.shape}")

    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    n = int(mask.sum())
    if n == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "r2": float("nan"), "n": 0}

    yt = y_true[mask]
    yp = y_pred[mask]
    err = yp - yt
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err * err)))

    ss_res = float(np.sum(err * err))
    ss_tot = float(np.sum((yt - yt.mean()) ** 2))
    r2 = float("nan") if ss_tot == 0.0 else 1.0 - ss_res / ss_tot

    return {"mae": mae, "rmse": rmse, "r2": r2, "n": n}
