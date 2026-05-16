"""讀 canonical parquet + 站點座標 CSV → ``PoleDataset``。

parquet 格式:wide table,第一欄 ``time``,其餘每欄一個 station_id,值為該小時 PM2.5(µg/m³)。
座標 CSV 欄位:deviceId / lat / lon(其他欄位被忽略)。
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
        values:      np.ndarray, shape (T, S),NaN 表缺值
        coords:      dict[str, (lon, lat)] | None
    """

    timestamps: pd.DatetimeIndex
    station_ids: list[str]
    values: np.ndarray
    coords: dict[str, tuple[float, float]] | None


def _load_station_coords(
    station_info_path: Path, station_ids: list[str]
) -> dict[str, tuple[float, float]]:
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
            "%d / %d 站缺座標(範例:%s)",
            len(missing), len(station_ids), sorted(missing)[:3],
        )
    return coords


def load_pole_hourly(
    cache_path: Path | str,
    *,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
    station_info_path: Path | str | None = None,
) -> PoleDataset:
    """讀 parquet,依時間範圍切片,並接上站點座標。

    Args:
        cache_path:        ``pole_hourly.parquet`` 路徑
        start, end:        ISO 字串或 pd.Timestamp;包含起、不含迄(半開區間)
        station_info_path: ``MOENV_iot_station.csv``,提供 lat/lon。
                           None 時 ``coords`` 回 None(distance-based 演算法不可用)。
    """
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
        "載入 %s:%d hr × %d 站,完整度 %.2f%%",
        cache_path.name, len(timestamps), len(station_ids),
        np.isfinite(values).mean() * 100,
    )
    return PoleDataset(
        timestamps=timestamps,
        station_ids=station_ids,
        values=values,
        coords=coords,
    )


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """單對 lon/lat → 公尺。給儀表板算「使用者選的鄰居跟 target 多遠」用。"""
    R = 6_371_000.0
    rlon1, rlat1 = np.radians(lon1), np.radians(lat1)
    rlon2, rlat2 = np.radians(lon2), np.radians(lat2)
    dlon = rlon2 - rlon1
    dlat = rlat2 - rlat1
    a = np.sin(dlat / 2) ** 2 + np.cos(rlat1) * np.cos(rlat2) * np.sin(dlon / 2) ** 2
    return 2 * R * float(np.arcsin(np.sqrt(a)))
