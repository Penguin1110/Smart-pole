"""CWA(中央氣象署)風速風向 loader,為 Stream B 的 wind_aligned selector 暖身。

實際 CWA 開放資料 API 需另外抓檔(本專案範圍外)。本模組提供:

  1. 讀取 ``data/cwa_wind_hourly.csv`` 的標準介面(若檔案存在)
  2. ``prevailing_wind_dir`` 算「實驗期間平均風向」的圓形均值——供 wind_aligned
     在沒有時間解析的風資料時當作 fallback scalar 用
  3. 一個靜態 fallback:高雄 12 月–2 月 NE 季風主導,平均風向 ~ 45°
     (NW–E 之間搖擺,參考交通部氣象站長期氣候統計,僅供 wind_aligned
     在 CWA 檔案缺席時當預設值)

期望 CSV 格式(欄位順序不限):
  - time:           ISO 字串,小時對齊
  - station_id:     字串
  - wind_speed_ms:  m/s
  - wind_dir_deg:   度(氣象慣例:0=北,90=東,順時針)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# 高雄冬季 NE 季風主導,長期氣候統計上平均風向約 45°(N→E 之間)
KAOHSIUNG_WINTER_PREVAILING_WIND_DEG = 45.0


@dataclass
class WindDataset:
    """CWA 風資料,長表結構。

    Attributes:
        df:      shape (n_rows, 4) 的 DataFrame,
                 欄位 [time, station_id, wind_speed_ms, wind_dir_deg]
        source:  描述資料來源,寫進 log
    """

    df: pd.DataFrame
    source: str


def load_cwa_wind_hourly(csv_path: Path | str) -> WindDataset | None:
    """讀 CWA 小時風資料 CSV。檔案不存在則回 None,並警告。"""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        logger.warning("CWA 風資料 %s 不存在,wind_aligned 將以 prevailing scalar 取代", csv_path)
        return None
    df = pd.read_csv(csv_path)
    required = {"time", "station_id", "wind_speed_ms", "wind_dir_deg"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CWA CSV {csv_path} 缺欄位:{sorted(missing)}")
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values(["time", "station_id"]).reset_index(drop=True)
    logger.info("讀 CWA 風資料:%d 筆,%d 站,時間 %s ~ %s",
                len(df), df["station_id"].nunique(), df["time"].min(), df["time"].max())
    return WindDataset(df=df, source=str(csv_path))


def prevailing_wind_dir(
    wind: WindDataset | None,
    *,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
    fallback_deg: float = KAOHSIUNG_WINTER_PREVAILING_WIND_DEG,
) -> float:
    """計算實驗期間平均風向(圓形均值,單位度)。

    無資料時回傳 ``fallback_deg``——讓 wind_aligned 在沒有 CWA 檔案的情境下仍可運作。
    """
    if wind is None or wind.df.empty:
        logger.info("用 fallback 平均風向 %.1f° (高雄冬季 NE 季風)", fallback_deg)
        return float(fallback_deg)

    df = wind.df
    if start is not None:
        df = df[df["time"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["time"] < pd.Timestamp(end)]
    if df.empty:
        logger.warning("CWA 風資料在 %s ~ %s 區間內為空,改用 fallback %.1f°",
                       start, end, fallback_deg)
        return float(fallback_deg)

    deg = df["wind_dir_deg"].to_numpy(dtype=np.float64)
    rad = np.deg2rad(deg)
    s = np.nanmean(np.sin(rad))
    c = np.nanmean(np.cos(rad))
    mean_rad = float(np.arctan2(s, c))
    mean_deg = float(np.rad2deg(mean_rad) % 360.0)
    logger.info("實驗期間平均風向(圓形均值):%.1f° (n=%d)", mean_deg, len(df))
    return mean_deg


__all__ = [
    "WindDataset",
    "load_cwa_wind_hourly",
    "prevailing_wind_dir",
    "KAOHSIUNG_WINTER_PREVAILING_WIND_DEG",
]
