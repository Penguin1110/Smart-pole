"""主實驗 runner——吃 resolved config,執行完整 pipeline:

    load → 建 neighbor table → 對每個 seed:mask → split → 對每個 K:fit → predict → metrics → save

每個 (seed, K) 各自寫一個 run 資料夾(schema 見 CLAUDE.md)。多 seed 跑完後額外
寫一個 ``agg_*`` 資料夾,內含 per-K mean ± std 與帶狀 K-curve。
"""
from __future__ import annotations

import json
import logging
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ..data.loader import load_pole_hourly
from ..evaluation.metrics import compute_metrics
from ..masking import make_mask
from ..models import registry as model_registry
from ..neighbors.selector import select_by_distance
from ..visualization.plots import make_plots, plot_k_curve_band, setup_chinese_font

# 強制 import models 套件,讓 @register decorator 跑過
from .. import models as _models  # noqa: F401

logger = logging.getLogger(__name__)


# ---------- config helpers ----------------------------------------------------


def _deep_update(base: dict, overlay: dict) -> dict:
    """遞迴合併,overlay 蓋掉 base。"""
    out = deepcopy(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_update(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def load_config(config_path: Path | str, project_root: Path) -> dict[str, Any]:
    """讀 experiment YAML;若同目錄上一層有 ``base.yaml`` 就先讀進來當預設值。"""
    config_path = Path(config_path)
    base_path = project_root / "configs" / "base.yaml"

    base: dict[str, Any] = {}
    if base_path.exists():
        with base_path.open("r", encoding="utf-8") as f:
            base = yaml.safe_load(f) or {}

    with config_path.open("r", encoding="utf-8") as f:
        exp = yaml.safe_load(f) or {}

    return _deep_update(base, exp)


def resolve_seeds(config: dict[str, Any]) -> list[int]:
    """從 config 取出 seeds 清單。``seeds: list[int]`` 為主,單一 ``seed: int`` 為向後相容。"""
    if "seeds" in config and config["seeds"] is not None:
        seeds = list(config["seeds"])
    elif "seed" in config and config["seed"] is not None:
        seeds = [int(config["seed"])]
    else:
        raise KeyError("config 需提供 `seeds: list[int]` 或 `seed: int`")
    if not seeds:
        raise ValueError("seeds 不能為空")
    return [int(s) for s in seeds]


# ---------- json helpers ------------------------------------------------------


def _explain_json_default(obj: Any) -> Any:
    """``json.dump`` 的 fallback——把 numpy 純量 / 陣列轉成 Python 原生型別。"""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.bool_):
        return bool(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ---------- runner ------------------------------------------------------------


@dataclass
class ExperimentResult:
    """單一 (seed, K) 的結果摘要。"""

    K: int
    seed: int
    run_dir: Path
    metrics: dict[str, float]
    n_predictions: int


@dataclass
class AggregatedResult:
    """跨 seeds 的聚合摘要——對應 ``results/runs/agg_*/``。"""

    agg_dir: Path
    per_k: dict[int, dict[str, dict[str, float]]] = field(default_factory=dict)
    # per_k[K] = {"mae": {"mean": ..., "std": ...}, "rmse": {...}, "r2": {...}, "n": {...}}
    seeds: list[int] = field(default_factory=list)


def run_experiment(
    config: dict[str, Any],
    *,
    project_root: Path,
) -> tuple[list[ExperimentResult], AggregatedResult | None]:
    """執行多 seed × K sweep 完整實驗。

    回傳 (per_seed_per_K 結果清單, 聚合結果)。當 seeds 只有 1 個時,聚合結果仍會產生
    (帶狀就退化成純線),但 ``agg_dir`` 仍會被寫出,供 downstream 程式碼一致處理。
    """
    seeds = resolve_seeds(config)
    exp_id = str(config["experiment_id"])

    # 1. 資料(只讀一次)
    data_cfg = config["data"]
    station_info_path = data_cfg.get("station_info_path")
    dataset = load_pole_hourly(
        cache_path=project_root / data_cfg["cache_path"],
        target_var=data_cfg.get("target_var", "pm25"),
        start=data_cfg.get("start"),
        end=data_cfg.get("end"),
        station_info_path=project_root / station_info_path if station_info_path else None,
    )

    timestamps = dataset.timestamps
    station_ids = dataset.station_ids
    values = dataset.values
    coords = dataset.coords
    T, S = values.shape
    sid_to_idx = {s: i for i, s in enumerate(station_ids)}

    # 2. split(seed 無關)
    split_cfg = config["split"]
    method = split_cfg["method"]
    train_ratio = float(split_cfg["train_ratio"])
    if method != "time_based":
        raise NotImplementedError(f"split.method={method!r} 尚未實作")
    train_end = int(T * train_ratio)
    train_slice = slice(0, train_end)
    test_slice = slice(train_end, T)
    test_offset = train_end
    logger.info(
        "time_based split:train=[0:%d] (%.1f%%), test=[%d:%d] (%.1f%%)",
        train_end, train_ratio * 100, train_end, T, (1 - train_ratio) * 100,
    )

    # 3. neighbor table(seed 無關;算一次)
    neigh_cfg = config["neighbors"]
    selector_name = neigh_cfg["selector"]
    k_list: list[int] = sorted(int(k) for k in neigh_cfg["k_list"])
    K_max = max(k_list)

    neighbor_table = _build_neighbor_table(
        selector_name=selector_name,
        station_ids=station_ids,
        values=values,
        train_slice=train_slice,
        coords=coords,
        K_max=K_max,
        selector_params=dict(neigh_cfg.get("params") or {}),
    )

    # 4. 模型 class(只 lookup 一次)
    model_cfg = config["model"]
    model_cls = model_registry.get_model(model_cfg["name"])
    model_params: dict[str, Any] = dict(model_cfg.get("params") or {})

    # 5. seeds × K sweep
    mask_cfg = config["masking"]
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    eval_plots = list(config.get("evaluation", {}).get("plots") or [])
    setup_chinese_font(project_root / "NotoSansCJKtc-Regular.otf")

    all_results: list[ExperimentResult] = []
    # metrics_by_seed_k[seed][K] = metrics dict
    metrics_by_seed_k: dict[int, dict[int, dict[str, float]]] = {}

    runs_root = project_root / "results" / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    # Phase 3 預設輸出 explain.json。bool(...) 允許 YAML 的 false / null 關掉
    eval_cfg = config.get("evaluation", {}) or {}
    collect_explain = bool(eval_cfg.get("explain", False))

    # Phase 3c:時空特徵設定。features.enabled=false 時與 Phase 2 完全等價。
    features_cfg = config.get("features", {}) or {}
    features_enabled = bool(features_cfg.get("enabled", False))
    feature_builder = None
    if features_enabled:
        from ..features import TemporalFeatureBuilder
        feature_builder = TemporalFeatureBuilder(
            lags=list(features_cfg.get("lags", []) or []),
            rolling=list(features_cfg.get("rolling", []) or []),
        )
        logger.info(
            "features.enabled=true:lags=%s, rolling=%s,每 target 額外 %d feature columns",
            feature_builder.lags, feature_builder.rolling,
            feature_builder.n_features_per_neighbor(),
        )

    for seed in seeds:
        logger.info("=== seed=%d ===", seed)
        mask = make_mask(values, mask_cfg=mask_cfg, seed=seed)

        metrics_by_k: dict[int, dict[str, float]] = {}
        predictions_by_k: dict[int, pd.DataFrame] = {}
        explain_by_k: dict[int, dict[str, Any]] = {}

        for K in k_list:
            t0 = time.time()
            preds_df, explain_per_target = _run_one_k(
                K=K,
                model_cls=model_cls,
                model_params=model_params,
                sid_to_idx=sid_to_idx,
                values=values,
                mask=mask,
                timestamps=timestamps,
                train_slice=train_slice,
                test_slice=test_slice,
                test_offset=test_offset,
                neighbor_table=neighbor_table,
                coords=coords,
                collect_explain=collect_explain,
                feature_builder=feature_builder,
            )
            metrics = compute_metrics(preds_df["y_true"].to_numpy(), preds_df["y_pred"].to_numpy())
            predictions_by_k[K] = preds_df
            metrics_by_k[K] = metrics
            explain_by_k[K] = explain_per_target
            logger.info(
                "seed=%d K=%d: n=%d, MAE=%.3f, RMSE=%.3f, R²=%.3f (耗時 %.1fs)",
                seed, K, metrics["n"], metrics["mae"], metrics["rmse"], metrics["r2"],
                time.time() - t0,
            )

        metrics_by_seed_k[seed] = metrics_by_k

        # 寫 per-(seed, K) run dir
        for K in k_list:
            run_dir = runs_root / f"{exp_id}_{model_cfg['name']}_K{K}_seed{seed}_{ts_str}"
            run_dir.mkdir(parents=True, exist_ok=True)

            with (run_dir / "config.yaml").open("w", encoding="utf-8") as f:
                yaml.safe_dump(_with_actual_k(config, K, seed), f, allow_unicode=True, sort_keys=False)

            with (run_dir / "metrics.json").open("w", encoding="utf-8") as f:
                json.dump(metrics_by_k[K], f, ensure_ascii=False, indent=2)

            predictions_by_k[K].to_parquet(run_dir / "predictions.parquet", index=False)
            (run_dir / "log.txt").touch(exist_ok=True)

            # Phase 3:有任一 target 給出 explain dict 就寫
            if explain_by_k[K]:
                with (run_dir / "explain.json").open("w", encoding="utf-8") as f:
                    json.dump(explain_by_k[K], f, ensure_ascii=False, indent=2, default=_explain_json_default)

            make_plots(
                predictions=predictions_by_k[K],
                metrics_by_k=metrics_by_k,  # 該 seed 的單線 k_curve
                out_dir=run_dir / "plots",
                which=eval_plots,
            )

            all_results.append(ExperimentResult(
                K=K, seed=seed, run_dir=run_dir, metrics=metrics_by_k[K],
                n_predictions=len(predictions_by_k[K]),
            ))

    # 6. 跨 seed 聚合
    agg = _aggregate(metrics_by_seed_k, k_list)
    agg_dir = runs_root / f"agg_{exp_id}_{model_cfg['name']}_{ts_str}"
    agg_dir.mkdir(parents=True, exist_ok=True)
    (agg_dir / "plots").mkdir(parents=True, exist_ok=True)

    with (agg_dir / "config.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(_with_seeds(config, seeds), f, allow_unicode=True, sort_keys=False)
    with (agg_dir / "aggregated_metrics.json").open("w", encoding="utf-8") as f:
        json.dump({"seeds": seeds, "per_k": agg}, f, ensure_ascii=False, indent=2)

    # 寫一份所有 seeds 的原始數據,方便 notebook 拿
    long_rows: list[dict[str, Any]] = []
    for seed, mbk in metrics_by_seed_k.items():
        for K, m in mbk.items():
            long_rows.append({"seed": seed, "K": K, **{k: v for k, v in m.items()}})
    pd.DataFrame(long_rows).to_parquet(agg_dir / "per_seed_metrics.parquet", index=False)

    plot_k_curve_band(metrics_by_seed_k, out_path=agg_dir / "plots" / "k_curve.png")

    result_agg = AggregatedResult(agg_dir=agg_dir, per_k=agg, seeds=seeds)

    return all_results, result_agg


def _aggregate(
    metrics_by_seed_k: dict[int, dict[int, dict[str, float]]],
    k_list: list[int],
) -> dict[int, dict[str, dict[str, float]]]:
    """把 metrics_by_seed_k 縮成 per_k[K][metric_name] = {mean, std}。"""
    out: dict[int, dict[str, dict[str, float]]] = {}
    if not metrics_by_seed_k:
        return out
    sample_metrics = next(iter(next(iter(metrics_by_seed_k.values())).values()))
    metric_names = list(sample_metrics.keys())
    for K in k_list:
        out[K] = {}
        for m in metric_names:
            arr = np.array(
                [metrics_by_seed_k[s][K][m] for s in metrics_by_seed_k if K in metrics_by_seed_k[s]],
                dtype=np.float64,
            )
            out[K][m] = {
                "mean": float(np.nanmean(arr)) if arr.size else float("nan"),
                "std":  float(np.nanstd(arr, ddof=1)) if arr.size > 1 else 0.0,
                "n":    int(arr.size),
            }
    return out


def _with_actual_k(config: dict[str, Any], K: int, seed: int) -> dict[str, Any]:
    """resolved config + 該次 run 的單一 K / seed。"""
    out = deepcopy(config)
    out.setdefault("neighbors", {})["k_actual"] = K
    out["seed"] = seed
    return out


def _with_seeds(config: dict[str, Any], seeds: list[int]) -> dict[str, Any]:
    out = deepcopy(config)
    out["seeds"] = seeds
    return out


def _build_neighbor_table(
    *,
    selector_name: str,
    station_ids: list[str],
    values: np.ndarray,
    train_slice: slice,
    coords: dict[str, tuple[float, float]] | None,
    K_max: int,
    selector_params: dict[str, Any] | None = None,
) -> dict[str, tuple[list[str], np.ndarray]]:
    """一次算出所有 target 的 K_max 個鄰站,K sweep 時取前 K 即可。

    現在支援的 selector:distance / correlation / diverse / hybrid / wind_aligned。
    後三者見 ``smart_pole.neighbors.*``。
    """
    selector_params = selector_params or {}
    table: dict[str, tuple[list[str], np.ndarray]] = {}

    if selector_name == "distance":
        if coords is None:
            raise RuntimeError(
                "selector=distance 但 raw 資料沒有座標。請在 raw CSV 補上 lat/lon,"
                "或暫時改用 selector=correlation"
            )
        for target in station_ids:
            if target not in coords:
                logger.warning("target %s 沒有座標,跳過", target)
                continue
            try:
                ids, dists = select_by_distance(target, station_ids, coords, K_max)
            except ValueError as e:
                logger.warning("無法替 %s 選 distance neighbors:%s", target, e)
                continue
            table[target] = (ids, dists)

    elif selector_name == "correlation":
        ids_per_target, _proxy_per_target = _corr_table(
            station_ids, values, train_slice, K_max,
        )
        for target, ids in zip(station_ids, ids_per_target):
            if ids is None:
                continue
            # 把 proxy 換成真實距離(公尺),讓 IDW / GaussianKernel 直接吃
            if coords is None or target not in coords:
                continue
            from ..neighbors.selector import _haversine
            lon_t, lat_t = coords[target]
            lons = np.array([coords[s][0] for s in ids if s in coords], dtype=np.float64)
            lats = np.array([coords[s][1] for s in ids if s in coords], dtype=np.float64)
            if len(lons) != len(ids):
                # 有鄰站沒座標——這在現行資料不會發生,但留個防線
                logger.warning("target %s 的鄰站有缺座標,跳過", target)
                continue
            dists = _haversine(lon_t, lat_t, lons, lats)
            table[target] = (ids, dists)

    elif selector_name == "diverse":
        from ..neighbors.diverse import select_diverse_table
        if coords is None:
            raise RuntimeError("selector=diverse 需要座標")
        table = select_diverse_table(station_ids, coords, K_max)

    elif selector_name == "hybrid":
        from ..neighbors.hybrid import select_hybrid_table
        if coords is None:
            raise RuntimeError("selector=hybrid 需要座標")
        table = select_hybrid_table(
            station_ids, values, train_slice, coords, K_max,
        )

    elif selector_name == "wind_aligned":
        from ..neighbors.wind_aligned import select_wind_aligned_table
        if coords is None:
            raise RuntimeError("selector=wind_aligned 需要座標")
        table = select_wind_aligned_table(
            station_ids=station_ids,
            coords=coords,
            K_max=K_max,
            **selector_params,
        )

    else:
        raise NotImplementedError(f"selector={selector_name!r} 尚未實作")

    logger.info("建好 neighbor table:%d / %d 站", len(table), len(station_ids))
    return table


def _corr_table(
    station_ids: list[str],
    values: np.ndarray,
    train_slice: slice,
    K_max: int,
) -> tuple[list[list[str] | None], list[np.ndarray | None]]:
    """向量化算 (S, S) 相關矩陣,各 target 取 |r| 最高的前 K_max 站。

    回傳兩個 list(長度 S);若某站候選不足會擺 None。
    """
    train_vals = values[train_slice]
    col_mean = np.nanmean(train_vals, axis=0)
    filled = np.where(np.isfinite(train_vals), train_vals, col_mean)
    filled = np.nan_to_num(filled, nan=0.0)
    centered = filled - filled.mean(axis=0, keepdims=True)
    std = np.linalg.norm(centered, axis=0)
    std[std == 0.0] = 1.0
    normed = centered / std
    corr = normed.T @ normed

    obs = np.isfinite(train_vals)
    overlap = obs.astype(np.int32).T @ obs.astype(np.int32)
    min_overlap = 24
    abs_r = np.abs(corr)
    abs_r[overlap < min_overlap] = np.nan
    np.fill_diagonal(abs_r, np.nan)

    ids_per_target: list[list[str] | None] = []
    proxy_per_target: list[np.ndarray | None] = []
    for i, target in enumerate(station_ids):
        row = abs_r[i]
        valid = np.flatnonzero(np.isfinite(row))
        if len(valid) < K_max:
            logger.warning("target %s 可用候選 %d 不足 K_max=%d,跳過",
                           target, len(valid), K_max)
            ids_per_target.append(None)
            proxy_per_target.append(None)
            continue
        order = valid[np.argsort(-row[valid], kind="stable")[:K_max]]
        ids = [station_ids[j] for j in order]
        proxy = 1.0 - row[order]
        ids_per_target.append(ids)
        proxy_per_target.append(proxy)
    return ids_per_target, proxy_per_target


def _run_one_k(
    *,
    K: int,
    model_cls,
    model_params: dict[str, Any],
    sid_to_idx: dict[str, int],
    values: np.ndarray,
    mask: np.ndarray,
    timestamps: pd.DatetimeIndex,
    train_slice: slice,
    test_slice: slice,
    test_offset: int,
    neighbor_table: dict[str, tuple[list[str], np.ndarray]],
    coords: dict[str, tuple[float, float]] | None,
    collect_explain: bool = False,
    feature_builder=None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """對每個 target station 取前 K 個鄰居,fit-predict-收集 predictions。

    回傳 (predictions_df, explain_per_target);後者僅在 ``collect_explain=True``
    且模型的 ``.explain()`` 回傳非 None 時填值。

    當 ``feature_builder`` 非 None,會在 K 鄰站基礎上加 lag / rolling / target 歷史 column,
    並透過 ``meta["feature_names"]`` 給模型對應的 column 名。
    """
    rows: list[dict[str, Any]] = []
    explain_per_target: dict[str, Any] = {}

    train_end = train_slice.stop
    test_values = values[test_slice]
    test_mask = mask[test_slice]

    for target, (full_neighbors, full_dists) in neighbor_table.items():
        neighbors = full_neighbors[:K]
        dists = full_dists[:K]
        t_idx = sid_to_idx[target]
        n_idx = [sid_to_idx[s] for s in neighbors]

        # 全段(T 列)的「鄰站 K 欄」+ target 歷史
        neighbor_ts_full = values[:, n_idx]      # (T, K)
        target_ts_full   = values[:, t_idx]      # (T,)

        if feature_builder is not None:
            # Phase 3c+:擴成 (T, K*(1+L+R) + L)
            X_full, feature_names = feature_builder.build(
                neighbor_ts_full, target_history=target_ts_full,
            )
        else:
            X_full = neighbor_ts_full
            feature_names = [f"nb{k}_t" for k in range(K)]

        # ---- train segment ----
        X_train_full = X_full[train_slice]
        y_train_full = target_ts_full[train_slice]
        if feature_builder is not None:
            # Phase 3c+:任何 feature 或 y 是 NaN 的 row 都丟掉(線性模型不吃 NaN)
            train_finite = np.isfinite(X_train_full).all(axis=1) & np.isfinite(y_train_full)
        else:
            # Phase 1/2 行為:只 drop y NaN,X 內 NaN 由模型自己(np.nanmean 等)處理
            train_finite = np.isfinite(y_train_full)
        if train_finite.sum() < max(8, X_full.shape[1] + 1):
            continue
        X_train = X_train_full[train_finite]
        y_train = y_train_full[train_finite]
        ts_train = timestamps[train_slice][train_finite]

        # ---- test segment ----
        target_mask = test_mask[:, t_idx]
        test_rows = np.flatnonzero(target_mask)
        if len(test_rows) == 0:
            continue
        X_test = X_full[test_offset + test_rows]
        y_test = test_values[test_rows, t_idx]
        test_ts = timestamps[test_offset + test_rows]

        target_coord = coords.get(target) if coords else None
        neighbor_coords = (
            np.array([coords[s] for s in neighbors], dtype=np.float64)
            if coords and all(s in coords for s in neighbors)
            else None
        )

        # 注意:distances 仍是 (n_samples, K)——只對應原始 K 鄰站當下值 column,
        # 不對 lag / rolling 延伸 column。用 distance / kernel 類模型需自行對齊。
        # ``*_full`` 是 Phase 3b 才用的 read-only references——
        # 大部分模型忽略,DINEOF / ST-GP 才會讀
        meta_common: dict[str, Any] = {
            "target_station_id": target,
            "neighbor_station_ids": neighbors,
            "target_coord": target_coord,
            "neighbor_coords": neighbor_coords,
            "feature_names": feature_names,
            "values_full": values,         # (T, S) read-only reference
            "mask_full":   mask,           # (T, S) bool
            "train_slice": train_slice,
            "test_slice":  test_slice,
            "target_idx":  t_idx,
            "neighbor_idx": n_idx,
        }
        meta_train = {
            **meta_common,
            "distances": np.tile(dists, (len(y_train), 1)),
            "timestamps": ts_train,
        }
        meta_test = {
            **meta_common,
            "distances": np.tile(dists, (len(test_rows), 1)),
            "timestamps": test_ts,
            "test_rows": test_rows,        # 對應 test_slice 內的 row 偏移
        }

        model = model_cls(**model_params)
        model.fit(X_train, y_train, meta_train)
        y_pred = model.predict(X_test, meta_test)

        if collect_explain:
            try:
                expl = model.explain()
            except Exception as e:
                logger.warning("target %s 的 explain() 失敗:%s", target, e)
                expl = None
            if expl is not None:
                explain_per_target[target] = expl

        for ts, yt, yp in zip(test_ts, y_test, y_pred):
            rows.append({
                "timestamp":  ts,
                "station_id": target,
                "y_true":     float(yt),
                "y_pred":     float(yp),
                "residual":   float(yp - yt),
            })

    preds_df = pd.DataFrame(rows, columns=["timestamp", "station_id", "y_true", "y_pred", "residual"])
    return preds_df, explain_per_target
