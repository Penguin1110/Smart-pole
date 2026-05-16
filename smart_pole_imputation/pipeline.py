"""高階 API:給定 (target, neighbors, timestamp) 跑所有演算法,回傳預測 + 誤差。

對儀表板情境設計:
  1. 使用者選一根 target 竿體要「消失」+ K 根鄰居 + 時間點 t*
  2. 系統把 (target, t*) 真值藏起來,用其他歷史訓練
  3. 對 t* 做預測,並把 |pred - true| 回給前端

主要 API:
    ``impute_single(...)``  ← 一次跑所有演算法,回傳 dict[algo_name → result]

預設 model params 來自 Phase 3 實驗的 best config(``configs/experiments/``)。
"""
from __future__ import annotations

import logging
import time as _time
from typing import Any

import numpy as np
import pandas as pd

from .data_io import PoleDataset, haversine_m
from .features import TemporalFeatureBuilder
from .imputers import REGISTRY, BaseImputer

logger = logging.getLogger(__name__)


# Phase 3 實驗驗證過的「合理 default」。caller 可在 model_params 覆寫單一模型。
DEFAULT_MODEL_PARAMS: dict[str, dict[str, Any]] = {
    "mean": {},
    "idw": {"power": 2.0, "eps": 1.0},
    "corr_weighted": {"min_overlap": 24},
    "gaussian_kernel": {"sigma": 5000.0},
    "weighted_ridge": {"alpha": 1.0, "weight_kind": "correlation", "min_overlap": 24},
    "idw_optimal": {
        "power_grid": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
        "eps": 1.0,
        "cv_folds": 5,
        "cv_seed": 1,
    },
    "kriging": {
        "variogram_model": "exponential",
        "n_bins": 10,
        "max_range_m": 40000.0,
        "nugget": "fit",
    },
    "spatial_gp": {
        "kernel": "matern52",
        "n_iter": 100,
        "lr": 0.05,
        "lengthscale_init_m": 5000.0,
        "noise_floor": 1e-3,
    },
    "timelag_ridge": {"alpha": 1.0, "min_train": 24},
    "elastic_net": {"alpha": 0.05, "l1_ratio": 0.5, "max_iter": 5000, "min_train": 24},
    "gls": {"cov_structure": "ar1", "max_iter": 5, "min_train": 24},
    "dineof": {"n_modes": 5, "max_iter": 30, "tol": 1e-3},
    "st_gp": {
        "n_iter": 50,
        "lr": 0.05,
        "max_train": 1500,
        "lengthscale_init_space_m": 5000.0,
        "lengthscale_init_time_h": 24.0,
        "noise_floor": 1e-3,
        "seed": 1,
    },
}


# 哪些模型在 fit/predict 需要 features(TemporalFeatureBuilder 處理過的 X)
_FEATURE_MODELS = {"timelag_ridge", "elastic_net", "gls"}

# 哪些模型需要整段 (T, S) 矩陣 meta(values_full / mask_full / target_idx 等)
_FULL_MATRIX_MODELS = {"dineof", "st_gp"}


def _build_meta(
    dataset: PoleDataset,
    target_id: str,
    neighbor_ids: list[str],
    K: int,
    *,
    feature_names: list[str] | None = None,
    distances_m: np.ndarray | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    coords = dataset.coords
    target_coord: tuple[float, float] | None = None
    neighbor_coords: np.ndarray | None = None
    if coords is not None and target_id in coords:
        target_coord = coords[target_id]
        if all(n in coords for n in neighbor_ids):
            neighbor_coords = np.array(
                [coords[n] for n in neighbor_ids], dtype=np.float64
            )

    meta: dict[str, Any] = {
        "target_station_id": target_id,
        "neighbor_station_ids": list(neighbor_ids),
        "distances": distances_m,
        "timestamps": dataset.timestamps,
        "target_coord": target_coord,
        "neighbor_coords": neighbor_coords,
        "feature_names": feature_names,
    }
    if extras:
        meta.update(extras)
    return meta


def _validate_inputs(
    dataset: PoleDataset,
    target_id: str,
    neighbor_ids: list[str],
    target_time: pd.Timestamp,
) -> tuple[int, list[int], int]:
    if target_id not in dataset.station_ids:
        raise KeyError(f"target {target_id!r} 不在 dataset 中")
    if target_id in neighbor_ids:
        raise ValueError(f"target {target_id!r} 不可同時當鄰居")
    if len(set(neighbor_ids)) != len(neighbor_ids):
        raise ValueError(f"neighbor_ids 有重複:{neighbor_ids}")
    if len(neighbor_ids) < 1:
        raise ValueError("K 至少 1")
    missing = [n for n in neighbor_ids if n not in dataset.station_ids]
    if missing:
        raise KeyError(f"鄰居不在 dataset:{missing}")

    target_idx = dataset.station_ids.index(target_id)
    neighbor_idx = [dataset.station_ids.index(n) for n in neighbor_ids]

    # 找最接近的 timestamp
    ts = dataset.timestamps
    pos = ts.get_indexer([target_time])[0]
    if pos < 0:
        raise KeyError(f"target_time {target_time} 不在 dataset 範圍內")
    return target_idx, neighbor_idx, int(pos)


def _make_distances(
    dataset: PoleDataset, target_id: str, neighbor_ids: list[str]
) -> np.ndarray | None:
    """有座標就回真距離(公尺);沒座標時退回 None。"""
    coords = dataset.coords
    if coords is None or target_id not in coords:
        return None
    if not all(n in coords for n in neighbor_ids):
        return None
    lon_t, lat_t = coords[target_id]
    d = np.array(
        [haversine_m(lon_t, lat_t, *coords[n]) for n in neighbor_ids],
        dtype=np.float64,
    )
    return d


def _resolve_params(
    name: str, override: dict[str, dict[str, Any]] | None
) -> dict[str, Any]:
    base = dict(DEFAULT_MODEL_PARAMS.get(name, {}))
    if override and name in override:
        base.update(override[name])
    return base


def _instantiate(name: str, params: dict[str, Any]) -> BaseImputer:
    cls = REGISTRY[name]
    return cls(**params)


def impute_single(
    dataset: PoleDataset,
    target_id: str,
    neighbor_ids: list[str],
    target_time: pd.Timestamp | str,
    *,
    models: list[str] | None = None,
    feature_lags: list[int] | None = None,
    feature_rolling: list[int] | None = None,
    model_params: dict[str, dict[str, Any]] | None = None,
    skip_gpu: bool = False,
) -> dict[str, dict[str, Any]]:
    """對使用者指定的 (target, K 鄰居, t*) 跑所有演算法。

    流程(每個演算法):
      1. ``target`` 在 ``target_time`` 的真值 y_true 被「藏起來」(target series 該 row 置 NaN)
      2. 演算法用其他歷史 fit
      3. 預測 t* 的 PM2.5 值 → ``prediction``
      4. ``absolute_error = |prediction - y_true|``
      5. 順便算 train 段 MAE(該演算法在訓練資料上的典型誤差)

    Args:
        dataset:         由 ``load_pole_hourly`` 載入的 PoleDataset
        target_id:       要藏起來的竿體 station_id
        neighbor_ids:    使用者挑的 K 根鄰居(不可包含 target,長度 = K)
        target_time:     要預測的 timestamp(必須在 dataset 時間範圍內)
        models:          要跑哪些演算法。None = 全跑;否則填 ``REGISTRY`` 中的 key
        feature_lags:    給 ``TemporalFeatureBuilder`` 的 lag(小時)。
                         None → 預設 [1, 2, 3, 6, 24]
        feature_rolling: rolling window(小時)。None → 預設 [3, 6, 24]
        model_params:    {algo_name: {param: value}};只覆寫單一模型的部分超參
        skip_gpu:        True 時跳過 ``requires_gpu=True`` 的模型(預設 False)

    Returns:
        dict[algo_name → result_dict],每個 result_dict 含:
            - ``prediction``: float            演算法在 t* 的預測值(可能為 NaN)
            - ``ground_truth``: float          dataset 中該格的真值
            - ``absolute_error``: float        |pred - true|(NaN 若任一端 NaN)
            - ``train_mae``: float             該演算法在 train 集上的 MAE
            - ``elapsed_s``: float             fit + predict 牆鐘時間
            - ``explain``: dict | None         BaseImputer.explain() 結果
            - ``error``: str | None            若該模型整段拋例外,訊息在這
    """
    target_idx, neighbor_idx, t_pos = _validate_inputs(
        dataset, target_id, neighbor_ids, pd.Timestamp(target_time)
    )
    K = len(neighbor_ids)

    feature_lags = feature_lags if feature_lags is not None else [1, 2, 3, 6, 24]
    feature_rolling = feature_rolling if feature_rolling is not None else [3, 6, 24]

    if models is None:
        chosen = list(REGISTRY.keys())
    else:
        unknown = [m for m in models if m not in REGISTRY]
        if unknown:
            raise KeyError(f"未知演算法:{unknown}。可用:{sorted(REGISTRY.keys())}")
        chosen = list(models)

    if skip_gpu:
        chosen = [m for m in chosen if not getattr(REGISTRY[m], "requires_gpu", False)]

    # 真值(藏起來前先記下來)
    y_true_at_t = float(dataset.values[t_pos, target_idx])

    # 把 target series 在 target_time 那 row 暫時 mask 掉(產生「使用者剛剛把竿體點消失」的假設)
    values_full = dataset.values.copy()
    values_full[t_pos, target_idx] = np.nan

    target_series = values_full[:, target_idx]                 # (T,),t_pos 是 NaN
    neighbor_block = values_full[:, neighbor_idx]              # (T, K)
    T = values_full.shape[0]

    # 距離(給 weighted 系列用;沒座標就 None)
    distances_1d = _make_distances(dataset, target_id, neighbor_ids)
    distances_mat: np.ndarray | None = None
    if distances_1d is not None:
        distances_mat = np.broadcast_to(distances_1d, (T, K)).copy()

    # ---- Temporal features --------------------------------------------------
    builder = TemporalFeatureBuilder(lags=list(feature_lags), rolling=list(feature_rolling))
    X_features, feature_names = builder.build(neighbor_block, target_history=target_series)

    # ---- train / test row 切分 ----------------------------------------------
    test_rows = np.array([t_pos], dtype=np.int64)
    # train 用所有非 t_pos 且 target 有觀測的 row(避免 leak)
    train_mask = np.ones(T, dtype=bool)
    train_mask[t_pos] = False

    # ---- 主迴圈 -------------------------------------------------------------
    results: dict[str, dict[str, Any]] = {}

    for name in chosen:
        cls = REGISTRY[name]
        params = _resolve_params(name, model_params)
        t0 = _time.perf_counter()

        try:
            imputer: BaseImputer = cls(**params)

            if name in _FULL_MATRIX_MODELS:
                # DINEOF / ST-GP:吃整段矩陣
                mask_full = np.zeros_like(values_full, dtype=bool)
                mask_full[t_pos, target_idx] = True
                # train_slice / test_slice 用單一一塊涵蓋整段;test_rows 標 t_pos
                extras = {
                    "values_full": values_full,
                    "mask_full": mask_full,
                    "train_slice": slice(0, T),
                    "test_slice": slice(0, T),
                    "target_idx": target_idx,
                    "neighbor_idx": neighbor_idx,
                }
                meta = _build_meta(
                    dataset, target_id, neighbor_ids, K,
                    feature_names=None,
                    distances_m=distances_1d,
                    extras=extras,
                )
                # fit 不需要 X/y(模型走 meta 矩陣);仍傳形狀對的空 placeholder
                imputer.fit(neighbor_block, target_series, meta)
                meta_pred = dict(meta)
                meta_pred["test_rows"] = test_rows
                pred = imputer.predict(neighbor_block[test_rows], meta_pred)

                # train_mae 對全矩陣模型沒有直接定義:DINEOF 只動了被 mask 的單一格,
                # 其餘 row 維持原值 → train_mae 必然為 0(不是真的 0 誤差,而是 trivial)。
                # ST-GP 也類似,要再 query GP 一次才能算,成本高。一律標 NaN。
                train_mae = float("nan")

            elif name in _FEATURE_MODELS:
                meta = _build_meta(
                    dataset, target_id, neighbor_ids, K,
                    feature_names=feature_names,
                    distances_m=distances_mat,
                )
                # fit:用 train_mask 的 X_features + target_series
                imputer.fit(
                    X_features[train_mask], target_series[train_mask], meta
                )
                pred = imputer.predict(X_features[test_rows], meta)

                # train MAE(只取 features 完整 + y 有效的 row)
                X_tr = X_features[train_mask]
                y_tr = target_series[train_mask]
                pred_tr = imputer.predict(X_tr, meta)
                m_tr = np.isfinite(pred_tr) & np.isfinite(y_tr)
                train_mae = (
                    float(np.mean(np.abs(pred_tr[m_tr] - y_tr[m_tr])))
                    if m_tr.any() else float("nan")
                )

            else:
                # Tier 1 / Tier 2 / 純空間 Tier 3:用鄰站當下值
                meta = _build_meta(
                    dataset, target_id, neighbor_ids, K,
                    feature_names=None,
                    distances_m=distances_mat,
                )
                imputer.fit(
                    neighbor_block[train_mask], target_series[train_mask], meta
                )
                pred = imputer.predict(neighbor_block[test_rows], meta)

                X_tr = neighbor_block[train_mask]
                y_tr = target_series[train_mask]
                pred_tr = imputer.predict(X_tr, meta)
                m_tr = np.isfinite(pred_tr) & np.isfinite(y_tr)
                train_mae = (
                    float(np.mean(np.abs(pred_tr[m_tr] - y_tr[m_tr])))
                    if m_tr.any() else float("nan")
                )

            elapsed = _time.perf_counter() - t0
            pred_val = float(pred[0]) if len(pred) else float("nan")
            abs_err = (
                abs(pred_val - y_true_at_t)
                if (np.isfinite(pred_val) and np.isfinite(y_true_at_t))
                else float("nan")
            )

            results[name] = {
                "prediction": pred_val,
                "ground_truth": y_true_at_t,
                "absolute_error": abs_err,
                "train_mae": train_mae,
                "elapsed_s": elapsed,
                "explain": imputer.explain(),
                "error": None,
            }

        except Exception as e:
            elapsed = _time.perf_counter() - t0
            logger.exception("model %s 失敗", name)
            results[name] = {
                "prediction": float("nan"),
                "ground_truth": y_true_at_t,
                "absolute_error": float("nan"),
                "train_mae": float("nan"),
                "elapsed_s": elapsed,
                "explain": None,
                "error": f"{type(e).__name__}: {e}",
            }

    return results


def summarize(results: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """把 ``impute_single`` 的回傳整理成 DataFrame,給儀表板右側框用。

    columns: model, prediction, ground_truth, absolute_error, train_mae, elapsed_s, error
    """
    rows = []
    for name, r in results.items():
        rows.append({
            "model": name,
            "prediction": r["prediction"],
            "ground_truth": r["ground_truth"],
            "absolute_error": r["absolute_error"],
            "train_mae": r["train_mae"],
            "elapsed_s": r["elapsed_s"],
            "error": r.get("error"),
        })
    df = pd.DataFrame(rows)
    return df.sort_values("absolute_error", na_position="last").reset_index(drop=True)
