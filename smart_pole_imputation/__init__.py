"""Smart Pole PM2.5 補值套件——11 個演算法,單一 API。

主要 entry points:

    from smart_pole_imputation.data_io import load_pole_hourly
    from smart_pole_imputation.pipeline import impute_single, summarize

    dataset = load_pole_hourly(
        "sample_data/pole_hourly_sample.parquet",
        station_info_path="sample_data/MOENV_iot_station.csv",
    )
    results = impute_single(
        dataset,
        target_id="...",
        neighbor_ids=["...", "...", "..."],
        target_time="2026-01-15 14:00",
    )
    summarize(results)   # → pandas DataFrame
"""
from __future__ import annotations

from .data_io import PoleDataset, load_pole_hourly
from .features import TemporalFeatureBuilder
from .imputers import REGISTRY, BaseImputer, get_model, list_models
from .pipeline import DEFAULT_MODEL_PARAMS, impute_single, summarize

__all__ = [
    "BaseImputer",
    "DEFAULT_MODEL_PARAMS",
    "PoleDataset",
    "REGISTRY",
    "TemporalFeatureBuilder",
    "get_model",
    "impute_single",
    "list_models",
    "load_pole_hourly",
    "summarize",
]
