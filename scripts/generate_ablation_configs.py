"""產生 Stream C 的 16 個 ablation YAML(4 selector × 4 weighting)。

固定軸:K=10, seeds=[1..5], mask=random_point, ratio=0.2。
hyperparameter 採各模型「合理 default」(在 exp_<model>.yaml 裡用的同一組):
  - idw:            power=2.0, eps=1.0(distances 統一為公尺後,所有 selector 適用)
  - corr_weighted:  min_overlap=24
  - weighted_ridge: alpha=1.0, weight_kind=none
  - mean:           無 hyperparam
"""
from __future__ import annotations

from pathlib import Path

import yaml


SELECTORS = ["distance", "correlation", "diverse", "hybrid"]
WEIGHTINGS = {
    "mean":             {"name": "mean",            "params": {}},
    "idw":              {"name": "idw",             "params": {"power": 2.0, "eps": 1.0}},
    "corr":             {"name": "corr_weighted",   "params": {"min_overlap": 24}},
    "ridge":            {"name": "weighted_ridge",  "params": {"alpha": 1.0, "weight_kind": "none"}},
}


def make_config(selector: str, weighting_key: str) -> dict:
    w = WEIGHTINGS[weighting_key]
    exp_id = f"abl_sel_{selector}_w_{weighting_key}"
    return {
        "experiment_id": exp_id,
        "seeds": [1, 2, 3, 4, 5],
        "data": {
            "cache_path":        "data/pole_hourly.parquet",
            "station_info_path": "data/MOENV_iot_station.csv",
            "target_var":        "pm25",
            "start":             "2025-12-04",
            "end":               "2026-02-05",
            "freq":              "1h",
        },
        "masking": {"strategy": "random_point", "ratio": 0.20},
        "neighbors": {"selector": selector, "k_list": [10]},
        "split": {"method": "time_based", "train_ratio": 0.8},
        "model": w,
        "evaluation": {
            "metrics": ["mae", "rmse", "r2"],
            "plots":   ["scatter", "residual_ts", "k_curve", "spatial_error"],
        },
    }


def main() -> int:
    out_dir = Path(__file__).resolve().parent.parent / "configs" / "experiments" / "ablation"
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for sel in SELECTORS:
        for w in WEIGHTINGS:
            cfg = make_config(sel, w)
            path = out_dir / f"sel_{sel}_w_{w}.yaml"
            with path.open("w", encoding="utf-8") as f:
                f.write(f"# Stream C ablation cell: selector={sel}, weighting={w}\n")
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
            n += 1
    print(f"寫入 {n} 個 ablation config 到 {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
