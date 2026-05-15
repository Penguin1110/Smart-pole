"""CLI 入口:`uv run python scripts/run_experiment.py --config <path>`。

把 logging 設好(同時印到 console + 寫進每個 run 資料夾的 log.txt),呼叫
``runner.experiment.run_experiment``。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from smart_pole.runner.experiment import load_config, run_experiment


def _setup_root_logger() -> logging.Handler:
    """設定 root logger:console 印 INFO,並回傳一個 in-memory buffer handler
    讓我們在 run 結束後把 log 寫進每個 run 資料夾。"""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 清空舊 handler(避免 jupyter 留下的污染)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    root.addHandler(console)

    # buffer 用 FileHandler 寫進一個 temp 路徑,run 完再 copy 進去
    import io
    buf = io.StringIO()
    buf_handler = logging.StreamHandler(buf)
    buf_handler.setFormatter(fmt)
    root.addHandler(buf_handler)
    buf_handler.stream_buffer = buf  # type: ignore[attr-defined]
    return buf_handler


def main() -> int:
    parser = argparse.ArgumentParser(description="跑單一 smart_pole 補值實驗")
    parser.add_argument("--config", required=True, type=Path, help="實驗 YAML 路徑")
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parent.parent,
        help="專案根目錄,預設為 scripts/ 的上一層",
    )
    args = parser.parse_args()

    buf_handler = _setup_root_logger()
    log = logging.getLogger(__name__)
    log.info("讀 config:%s", args.config)

    config = load_config(args.config, project_root=args.project_root)
    log.info("experiment_id=%s, model=%s, seed=%d",
             config["experiment_id"], config["model"]["name"], config["seed"])

    results, agg = run_experiment(config, project_root=args.project_root)

    # log 內容寫進每個 run dir 與 agg 資料夾
    log_text = buf_handler.stream_buffer.getvalue()  # type: ignore[attr-defined]
    for r in results:
        (r.run_dir / "log.txt").write_text(log_text, encoding="utf-8")
    if agg is not None:
        (agg.agg_dir / "log.txt").write_text(log_text, encoding="utf-8")

    log.info("完成 %d 個 (seed, K)——結果在:", len(results))
    for r in results:
        log.info("  seed=%d K=%-3d  MAE=%.3f  RMSE=%.3f  R²=%.3f  →  %s",
                 r.seed, r.K, r.metrics["mae"], r.metrics["rmse"], r.metrics["r2"], r.run_dir)
    if agg is not None:
        log.info("聚合結果在:%s", agg.agg_dir)
        for K, by_metric in agg.per_k.items():
            log.info("  K=%-3d  MAE=%.3f ± %.3f  RMSE=%.3f ± %.3f  R²=%.3f ± %.3f  (n_seed=%d)",
                     K,
                     by_metric["mae"]["mean"],  by_metric["mae"]["std"],
                     by_metric["rmse"]["mean"], by_metric["rmse"]["std"],
                     by_metric["r2"]["mean"],   by_metric["r2"]["std"],
                     by_metric["mae"]["n"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
