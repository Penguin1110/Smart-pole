"""從 canonical parquet 讀資料,輸出 (timestamps, station_ids, values, coords)。

canonical parquet 格式(`data/pole_hourly.parquet`,由 `data_gathering.py` 產出):
    wide table,第一欄 ``time``,其餘每欄一個 station_id,值為該小時 PM2.5。

座標來源:`data/MOENV_iot_station.csv`(環境部 IoT 測站清單,全台 10999 站,
欄位 deviceId/locationId/desc/lat/lon/area/areatype/town/county/project_name)。
透過 ``station_info_path`` 參數傳入路徑。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PoleDataset:
    """一份對齊好的竿體小時資料。

    Attributes:
        timestamps:  pd.DatetimeIndex, shape (T,)
        station_ids: list[str], length S
        values:      np.ndarray, shape (T, S),NaN 表示缺值
        coords:      dict[str, tuple[float, float]] | None
                     key=station_id, value=(lon, lat)。None 表示原始資料無座標。
    """

    timestamps: pd.DatetimeIndex
    station_ids: list[str]
    values: np.ndarray
    coords: dict[str, tuple[float, float]] | None


def _load_station_coords(
    station_info_path: Path, station_ids: list[str]
) -> dict[str, tuple[float, float]]:
    """從 MOENV_iot_station.csv 讀 deviceId → (lon, lat) 對應表。

    CSV 欄位:deviceId, locationId, desc, lat, lon, area, areatype, town, county, project_name。
    全國 ~11k 站,本函式只挑 ``station_ids`` 內的(高雄竿體)。
    """
    df = pd.read_csv(
        station_info_path,
        usecols=["deviceId", "lat", "lon"],
        dtype={"deviceId": str},
    )
    df = df.dropna(subset=["lat", "lon"]).drop_duplicates(subset="deviceId", keep="first")

    wanted = set(station_ids)
    df = df[df["deviceId"].isin(wanted)]
    coords = {
        sid: (float(lon), float(lat))
        for sid, lat, lon in zip(df["deviceId"], df["lat"], df["lon"])
    }
    missing = wanted - coords.keys()
    if missing:
        logger.warning(
            "%d / %d 站在 station info 中沒有座標(範例:%s)",
            len(missing), len(station_ids), sorted(missing)[:3],
        )
    return coords


def load_pole_hourly(
    cache_path: Path | str,
    *,
    target_var: str = "pm25",
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
    station_info_path: Path | str | None = None,
) -> PoleDataset:
    """讀 canonical parquet,依時間範圍切片,並接上站點座標。

    Args:
        cache_path:        `data/pole_hourly.parquet` 的路徑
        target_var:        目前只支援 "pm25"
        start, end:        ISO 字串或 pd.Timestamp;包含起、不含迄(半開區間)
        station_info_path: `data/MOENV_iot_station.csv`,提供 lat/lon。
                           None 時 ``coords`` 回傳 None,distance selector 不可用。

    Returns:
        PoleDataset
    """
    if target_var != "pm25":
        raise NotImplementedError(f"目前只支援 target_var='pm25',收到 {target_var!r}")

    cache_path = Path(cache_path)
    df = pd.read_parquet(cache_path)
    if "time" not in df.columns:
        raise ValueError(f"{cache_path} 缺少 'time' 欄位")

    df["time"] = pd.to_datetime(df["time"])
    if start is not None:
        df = df[df["time"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["time"] < pd.Timestamp(end)]
    df = df.sort_values("time").reset_index(drop=True)

    timestamps = pd.DatetimeIndex(df["time"].values)
    station_ids = [c for c in df.columns if c != "time"]
    values = df[station_ids].to_numpy(dtype=np.float64)

    coords: dict[str, tuple[float, float]] | None = None
    if station_info_path is not None:
        coords = _load_station_coords(Path(station_info_path), station_ids)
        logger.info(
            "從 %s 取得 %d / %d 站座標",
            Path(station_info_path).name, len(coords), len(station_ids),
        )

    logger.info(
        "載入 %s:%d hr × %d station,時間 %s ~ %s,完整度 %.2f%%",
        cache_path.name, len(timestamps), len(station_ids),
        timestamps.min(), timestamps.max(),
        np.isfinite(values).mean() * 100,
    )
    return PoleDataset(
        timestamps=timestamps,
        station_ids=station_ids,
        values=values,
        coords=coords,
    )
