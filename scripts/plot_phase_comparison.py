"""畫 Phase 1 / 2 / 3a / 3c K-curve 對比,存到 results/phase_comparison_kcurve.png。

從各 `agg_*` 目錄讀 `aggregated_metrics.json`,取每模型的最近一次 run。
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from smart_pole.visualization.plots import setup_chinese_font


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS = PROJECT_ROOT / "results" / "runs"


CURVES = [
    ("Phase 1 mean × correlation",  "agg_exp01_mean_corr_ms_mean_*",     "C7", "o-"),
    ("Phase 2 ridge × correlation", "agg_exp_phase2_best_*",              "C2", "s-"),
    ("Phase 3a idw_optimal",        "agg_exp_idw_optimal_*",              "C0", "D-"),
    ("Phase 3a kriging",            "agg_exp_kriging_kriging_*",          "C1", "^-"),
    ("Phase 3a spatial_gp",         "agg_exp_spatial_gp_spatial_gp_*",    "C3", "v-"),
    ("Phase 3c timelag_ridge",      "agg_exp_timelag_ridge_*",            "C4", "P-"),
    ("Phase 3c elastic_net",        "agg_exp_elastic_net_*",              "C5", "X-"),
    ("Phase 3c gls",                "agg_exp_gls_gls_*",                  "C6", "*-"),
]


def latest(pattern: str) -> Path | None:
    cands = sorted(RUNS.glob(pattern))
    return cands[-1] if cands else None


def main() -> int:
    setup_chinese_font(PROJECT_ROOT / "NotoSansCJKtc-Regular.otf")
    fig, ax = plt.subplots(figsize=(8.5, 5))

    for label, pat, color, style in CURVES:
        d = latest(pat)
        if d is None:
            print(f"⚠️  找不到 {pat}, 跳過")
            continue
        meta = json.loads((d / "aggregated_metrics.json").read_text())
        per_k = meta["per_k"]
        ks = sorted(int(k) for k in per_k)
        mae = np.array([per_k[str(k)]["mae"]["mean"] for k in ks])
        std = np.array([per_k[str(k)]["mae"]["std"]  for k in ks])
        ax.plot(ks, mae, style, color=color, label=label)
        ax.fill_between(ks, mae - std, mae + std, color=color, alpha=0.2)

    ax.set_xlabel("K (鄰站數)")
    ax.set_ylabel("MAE  (PM2.5, µg/m³)")
    ax.set_title("Phase 1 → 2 → 3a → 3c 的 K-curve(5 seeds、correlation selector、random_point 0.2)")
    ax.legend(loc="upper right", fontsize=8.5, ncol=2)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out = PROJECT_ROOT / "results" / "phase_comparison_kcurve.png"
    fig.savefig(out, dpi=120)
    print(f"已存 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
