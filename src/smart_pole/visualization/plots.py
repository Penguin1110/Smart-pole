"""畫圖工具——scatter / residual_ts / k_curve / spatial_error。

config 的 ``evaluation.plots`` 列哪幾個,就畫哪幾個。中文字型由 ``setup_chinese_font``
從專案根目錄載入。
"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

matplotlib.use("Agg")  # headless container


def setup_chinese_font(font_path: Path | str) -> None:
    """載入 NotoSansCJKtc-Regular.otf;字型檔位置由呼叫端傳入。"""
    font_path = Path(font_path)
    if not font_path.exists():
        logger.warning("中文字型 %s 不存在,圖中文會變豆腐", font_path)
        return
    fm.fontManager.addfont(str(font_path))
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK TC"]
    plt.rcParams["axes.unicode_minus"] = False


def plot_scatter(predictions: pd.DataFrame, out_path: Path) -> None:
    """y_true vs y_pred 散佈圖,對角線為理想預測。"""
    fig, ax = plt.subplots(figsize=(6, 6))
    yt = predictions["y_true"].to_numpy()
    yp = predictions["y_pred"].to_numpy()
    m = np.isfinite(yt) & np.isfinite(yp)
    ax.scatter(yt[m], yp[m], s=4, alpha=0.3)
    lo = float(min(np.nanmin(yt[m]), np.nanmin(yp[m])))
    hi = float(max(np.nanmax(yt[m]), np.nanmax(yp[m])))
    ax.plot([lo, hi], [lo, hi], "k--", lw=1)
    ax.set_xlabel("y_true (PM2.5)")
    ax.set_ylabel("y_pred (PM2.5)")
    ax.set_title("預測 vs 真值")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_residual_ts(predictions: pd.DataFrame, out_path: Path) -> None:
    """每小時平均殘差時序圖——能看出系統性偏差或時段性異常。"""
    df = predictions.copy()
    df["residual"] = df["y_pred"] - df["y_true"]
    agg = df.groupby("timestamp")["residual"].mean()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(agg.index, agg.values, lw=0.8)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("時間")
    ax.set_ylabel("平均殘差 (y_pred - y_true)")
    ax.set_title("殘差時序")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_spatial_error(predictions: pd.DataFrame, out_path: Path) -> None:
    """每個 station 的 MAE 分布——畫直方圖(沒有座標時的 fallback)。

    日後 coords 補上,可以改成散點地圖。
    """
    df = predictions.copy()
    df["abs_err"] = (df["y_pred"] - df["y_true"]).abs()
    per_station = df.groupby("station_id")["abs_err"].mean().dropna()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(per_station.values, bins=40)
    ax.set_xlabel("該站平均 |誤差|")
    ax.set_ylabel("站數")
    ax.set_title(f"各站 MAE 分布(n={len(per_station)})")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_k_curve(metrics_by_k: dict[int, dict[str, float]], out_path: Path) -> None:
    """K vs MAE/RMSE 曲線(單 seed)——核心研究問題的視覺化。"""
    if not metrics_by_k:
        return
    ks = sorted(metrics_by_k.keys())
    mae = [metrics_by_k[k]["mae"] for k in ks]
    rmse = [metrics_by_k[k]["rmse"] for k in ks]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(ks, mae, "o-", label="MAE")
    ax.plot(ks, rmse, "s-", label="RMSE")
    ax.set_xlabel("K (鄰站數)")
    ax.set_ylabel("誤差")
    ax.set_title("K vs 誤差")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_k_curve_band(
    metrics_by_seed_k: dict[int, dict[int, dict[str, float]]],
    out_path: Path,
) -> None:
    """K vs MAE/RMSE 帶狀圖——中線 mean,半透明帶 ±1 std。

    Args:
        metrics_by_seed_k: metrics_by_seed_k[seed][K] = metrics dict
    """
    if not metrics_by_seed_k:
        return
    seeds = sorted(metrics_by_seed_k.keys())
    # 取所有 seed 都跑過的 K
    common_ks = None
    for s in seeds:
        ks = set(metrics_by_seed_k[s].keys())
        common_ks = ks if common_ks is None else (common_ks & ks)
    if not common_ks:
        return
    ks = sorted(common_ks)

    def stats(metric: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        per_seed = np.array(
            [[metrics_by_seed_k[s][k][metric] for k in ks] for s in seeds],
            dtype=np.float64,
        )
        m = np.nanmean(per_seed, axis=0)
        std = np.nanstd(per_seed, axis=0, ddof=1) if per_seed.shape[0] > 1 else np.zeros_like(m)
        return per_seed, m, std

    fig, ax = plt.subplots(figsize=(7, 4))
    for metric, marker, color in [("mae", "o", "C0"), ("rmse", "s", "C1")]:
        per_seed, mean, std = stats(metric)
        # 個別 seed 細線(輔助線)
        for row in per_seed:
            ax.plot(ks, row, color=color, alpha=0.15, lw=0.8)
        ax.plot(ks, mean, f"{marker}-", color=color, label=f"{metric.upper()} (mean, n_seed={len(seeds)})")
        ax.fill_between(ks, mean - std, mean + std, color=color, alpha=0.2)
    ax.set_xlabel("K (鄰站數)")
    ax.set_ylabel("誤差")
    ax.set_title("K vs 誤差(帶狀 ±1 std)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def make_plots(
    predictions: pd.DataFrame,
    metrics_by_k: dict[int, dict[str, float]],
    out_dir: Path,
    which: list[str],
) -> None:
    """依 ``which`` 清單畫圖,存到 ``out_dir``。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    dispatch = {
        "scatter":       lambda: plot_scatter(predictions, out_dir / "scatter.png"),
        "residual_ts":   lambda: plot_residual_ts(predictions, out_dir / "residual_ts.png"),
        "spatial_error": lambda: plot_spatial_error(predictions, out_dir / "spatial_error.png"),
        "k_curve":       lambda: plot_k_curve(metrics_by_k, out_dir / "k_curve.png"),
    }
    for name in which:
        if name not in dispatch:
            logger.warning("未知的 plot 種類:%s", name)
            continue
        try:
            dispatch[name]()
        except Exception as exc:
            logger.exception("畫 %s 失敗:%s", name, exc)
