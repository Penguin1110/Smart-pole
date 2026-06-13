"""
從 data/epa_data/ 的大新竹周邊 EPA 測站 CSV 產生 work/ 所需的 JSON 檔案：
  - stations_hsinchu.json
  - correlations_hsinchu.json
  - pm25_timeseries_hsinchu.json

涵蓋 8 站，站名全部使用官方英文（來源：MOENV aqx_p_07 siteengname）。
座標來源：MOENV aqx_p_07 twd97lat / twd97lon（實際為 WGS84 十進位度）。
執行前請先跑 gather_hsinchu_epa.py 取得真實資料。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

# name_zh: MOENV aqx_p_15 sitename（用於讀取 CSV）
# name_en: MOENV aqx_p_07 siteengname（官方英文名，用於 HTML 顯示）
STATIONS = [
    {"id": "hsinchu", "name_zh": "新竹", "name_en": "Hsinchu",  "lat": 24.80563560, "lon": 120.97236752, "county": "Hsinchu City"},
    {"id": "zhudong", "name_zh": "竹東", "name_en": "Zhudong",  "lat": 24.74091408, "lon": 121.08895493, "county": "Hsinchu County"},
    {"id": "hukou",   "name_zh": "湖口", "name_en": "Hukou",    "lat": 24.90009696, "lon": 121.03886894, "county": "Hsinchu County"},
    {"id": "toufen",  "name_zh": "頭份", "name_en": "Toufen",   "lat": 24.69690679, "lon": 120.89869286, "county": "Miaoli County"},
    {"id": "miaoli",  "name_zh": "苗栗", "name_en": "Miaoli",   "lat": 24.56499183, "lon": 120.82011468, "county": "Miaoli County"},
    {"id": "longtan", "name_zh": "龍潭", "name_en": "Longtan",  "lat": 24.86400048, "lon": 121.21645772, "county": "Taoyuan City"},
    {"id": "guanyin", "name_zh": "觀音", "name_en": "Guanyin",  "lat": 25.03556747, "lon": 121.08283092, "county": "Taoyuan City"},
    {"id": "dayuan",  "name_zh": "大園", "name_en": "Dayuan",   "lat": 25.06100357, "lon": 121.20251473, "county": "Taoyuan City"},
]

DATA_DIR = Path(__file__).parent / "data" / "epa_data"
OUT_DIR  = Path(__file__).parent / "work"
OUT_DIR.mkdir(exist_ok=True)


def pm25_to_aqi(pm25: float) -> int:
    if math.isnan(pm25) or pm25 < 0:
        return 0
    breakpoints = [
        (0.0,   12.0,   0,  50),
        (12.1,  35.4,  51, 100),
        (35.5,  55.4, 101, 150),
        (55.5, 150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 500.4, 301, 500),
    ]
    for lo_pm, hi_pm, lo_aqi, hi_aqi in breakpoints:
        if lo_pm <= pm25 <= hi_pm:
            return round((hi_aqi - lo_aqi) / (hi_pm - lo_pm) * (pm25 - lo_pm) + lo_aqi)
    return 500


def load_all() -> dict[str, pd.DataFrame]:
    """key = name_en（英文）"""
    dfs = {}
    for s in STATIONS:
        path = DATA_DIR / f"epa_{s['name_zh']}.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"找不到 {path}，請先執行 gather_hsinchu_epa.py"
            )
        df = pd.read_csv(path, parse_dates=["time"])
        df = df.sort_values("time").reset_index(drop=True)
        dfs[s["name_en"]] = df
    return dfs


def build_wide(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    series = {name_en: df.set_index("time")["pm25"] for name_en, df in dfs.items()}
    wide = pd.DataFrame(series).sort_index()
    idx = pd.date_range("2025-12-01", "2026-02-28 23:00", freq="h")
    wide = wide.reindex(idx)
    return wide


def build_stations_json(
    dfs: dict[str, pd.DataFrame], wide: pd.DataFrame
) -> list[dict]:
    last_complete = wide.dropna(how="any").index.max()
    if pd.isna(last_complete):
        last_complete = wide.dropna(how="all").index.max()

    snapshot_row = wide.loc[last_complete] if last_complete in wide.index else None

    result = []
    for s in STATIONS:
        en = s["name_en"]
        df = dfs[en]
        mean_pm25 = float(df["pm25"].mean(skipna=True))

        if snapshot_row is not None and not pd.isna(snapshot_row.get(en)):
            snap = float(snapshot_row[en])
        else:
            last_valid = df["pm25"].dropna().iloc[-1] if df["pm25"].notna().any() else mean_pm25
            snap = float(last_valid)

        aqi = pm25_to_aqi(snap)
        result.append({
            "id":        s["id"],
            "name":      en,          # HTML 顯示英文
            "name_zh":   s["name_zh"],
            "lat":       s["lat"],
            "lon":       s["lon"],
            "pm25":      round(snap, 1),
            "pm25_mean": round(mean_pm25, 1),
            "aqi":       aqi,
            "county":    s["county"],
        })
    return result


def build_correlations_json(wide: pd.DataFrame) -> dict:
    names_en = [s["name_en"] for s in STATIONS]
    corr = wide[names_en].corr(method="pearson")
    matrix = []
    for r in names_en:
        row = []
        for c in names_en:
            v = corr.loc[r, c]
            row.append(round(float(v), 4) if not math.isnan(v) else 0.0)
        matrix.append(row)
    return {"stations": names_en, "matrix": matrix}


def build_timeseries_json(wide: pd.DataFrame) -> dict:
    names_en = [s["name_en"] for s in STATIONS]
    df = wide[names_en].copy()
    df = df.interpolate(method="linear", limit=3, limit_direction="both")

    start = str(df.index[0])
    data = {}
    for name in names_en:
        data[name] = [
            round(float(v), 1) if (v is not None and not math.isnan(v)) else None
            for v in df[name]
        ]
    return {
        "start":      start,
        "step_hours": 1,
        "stations":   names_en,
        "data":       data,
        "n":          len(df),
    }


def main() -> None:
    print("讀取新竹 EPA 資料…")
    dfs = load_all()
    wide = build_wide(dfs)

    n_total = len(wide)
    n_complete = wide.dropna(how="any").shape[0]
    print(f"  時間範圍: {wide.index.min()} ~ {wide.index.max()}")
    print(f"  總時間點: {n_total}，完整時間點（{len(STATIONS)} 站都有值）: {n_complete}")

    print("產生 stations_hsinchu.json…")
    stations = build_stations_json(dfs, wide)
    out_s = OUT_DIR / "stations_hsinchu.json"
    out_s.write_text(
        json.dumps(stations, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  → {len(stations)} 站")

    print("計算相關係數矩陣…")
    corr_data = build_correlations_json(wide)
    out_c = OUT_DIR / "correlations_hsinchu.json"
    out_c.write_text(
        json.dumps(corr_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("產生完整時序資料…")
    ts = build_timeseries_json(wide)
    out_t = OUT_DIR / "pm25_timeseries_hsinchu.json"
    out_t.write_text(
        json.dumps(ts, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    print(f"\n完成！輸出至 {OUT_DIR}/")
    for f in [out_s, out_c, out_t]:
        print(f"  {f.name}  ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
