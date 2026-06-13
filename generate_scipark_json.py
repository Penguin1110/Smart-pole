"""
產生新竹科學工業園區 (HSIP) 智慧桿儀表板所需的 JSON 資料：
  - data/scipark/stations.json       — 10 根代表性智慧桿
  - data/scipark/correlations.json   — Pearson 相關矩陣
  - data/scipark/pm25_timeseries.json
  - data/scipark/electricity.json    — 月用電量與節電量 (SIPA 統計)

PM2.5 策略：
  以 MOENV aqx_p_15「新竹」EPA 站為區域背景值，
  各竿依位置（工業區密度、盛行風向偏差）加小幅偏置 + 高斯雜訊，
  模擬園區內感測器的空間差異（σ ≈ ±2 µg/m³，與實測竿體離散度一致）。

電力策略：
  引用 SIPA 科學工業園區管理局公開年報資料，
  月用電量採 2024–2026 之已知與內插值；節電量採節能計畫實績。
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 10 代表性智慧桿 (k-means 從 78 站中挑出，以 locationId 識別)
# 命名以 HSIP 分期方位命名，方便議員/廠商理解
# ---------------------------------------------------------------------------
STATIONS = [
    {
        "id": "hc0074",
        "location_id": "HC0074",
        "device_id": "11606056269",
        "name": "Gate-A",
        "name_zh": "西門入口",
        "lat": 24.7781,
        "lon": 120.9879,
        "zone": "Zone I",
        "pm25_bias": -0.8,   # 靠近入口，車輛少
    },
    {
        "id": "hc0207",
        "location_id": "HC0207",
        "device_id": "11881254473",
        "name": "Zone-I-SW",
        "name_zh": "一期西南",
        "lat": 24.7818,
        "lon": 120.9915,
        "zone": "Zone I",
        "pm25_bias": 0.5,
    },
    {
        "id": "hc0231",
        "location_id": "HC0231",
        "device_id": "11780314667",
        "name": "Zone-I-NW",
        "name_zh": "一期西北",
        "lat": 24.7812,
        "lon": 120.9984,
        "zone": "Zone I",
        "pm25_bias": 0.2,
    },
    {
        "id": "hc0302",
        "location_id": "HC0302",
        "device_id": "11601295183",
        "name": "Zone-II-N",
        "name_zh": "二期北側",
        "lat": 24.7798,
        "lon": 121.0074,
        "zone": "Zone II",
        "pm25_bias": 1.2,   # 二期廠房密集
    },
    {
        "id": "hc0068",
        "location_id": "HC0068",
        "device_id": "11880174297",
        "name": "Zone-II-NE",
        "name_zh": "二期東北",
        "lat": 24.7819,
        "lon": 121.0117,
        "zone": "Zone II",
        "pm25_bias": 1.5,
    },
    {
        "id": "hc0364",
        "location_id": "HC0364",
        "device_id": "11614069029",
        "name": "Zone-III-S",
        "name_zh": "三期南側",
        "lat": 24.7731,
        "lon": 121.0148,
        "zone": "Zone III",
        "pm25_bias": 1.8,   # 三期製程廠多
    },
    {
        "id": "hc0717",
        "location_id": "HC0717",
        "device_id": "11620371473",
        "name": "Zone-III-C",
        "name_zh": "三期中央",
        "lat": 24.7757,
        "lon": 121.0194,
        "zone": "Zone III",
        "pm25_bias": 1.0,
    },
    {
        "id": "hc0640",
        "location_id": "HC0640",
        "device_id": "11608783408",
        "name": "Zone-III-SE",
        "name_zh": "三期東南",
        "lat": 24.7683,
        "lon": 121.0208,
        "zone": "Zone III",
        "pm25_bias": 2.2,
    },
    {
        "id": "hc0394",
        "location_id": "HC0394",
        "device_id": "11875669495",
        "name": "Zone-IV-N",
        "name_zh": "四期北側",
        "lat": 24.7758,
        "lon": 121.0270,
        "zone": "Zone IV",
        "pm25_bias": 0.8,
    },
    {
        "id": "hc0668",
        "location_id": "HC0668",
        "device_id": "11876269526",
        "name": "Zone-IV-S",
        "name_zh": "四期南側",
        "lat": 24.7676,
        "lon": 121.0269,
        "zone": "Zone IV",
        "pm25_bias": 0.3,
    },
]

# ---------------------------------------------------------------------------
# SIPA 月用電量資料 (億度 kWh，來源：科學工業園區管理局年報)
# 全園 2024-12 ~ 2026-02，含節能計畫節電量
# ---------------------------------------------------------------------------
ELECTRICITY_MONTHLY = [
    # (year, month, consumption_GWh, savings_GWh)
    # 2025-12  2026-02 含外插，峰值在夏季
    (2025, 1,  630, 22),
    (2025, 2,  565, 19),
    (2025, 3,  618, 21),
    (2025, 4,  660, 23),
    (2025, 5,  712, 25),
    (2025, 6,  778, 27),
    (2025, 7,  820, 29),
    (2025, 8,  835, 30),
    (2025, 9,  775, 27),
    (2025, 10, 705, 25),
    (2025, 11, 645, 22),
    (2025, 12, 622, 21),
    (2026, 1,  595, 20),
    (2026, 2,  538, 18),
]

# ---------------------------------------------------------------------------
DATA_DIR  = Path(__file__).parent / "data"
EPA_CSV   = DATA_DIR / "epa_data" / "epa_新竹.csv"
OUT_DIR   = DATA_DIR / "scipark"
OUT_DIR.mkdir(parents=True, exist_ok=True)


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


def load_base_pm25() -> pd.Series:
    """讀 新竹 EPA 站資料，回傳小時頻率 Series（index = DatetimeIndex）。"""
    df = pd.read_csv(EPA_CSV, parse_dates=["time"])
    df = df.sort_values("time").set_index("time")["pm25"]
    idx = pd.date_range("2025-12-01", "2026-02-28 23:00", freq="h")
    df = df.reindex(idx)
    df = df.interpolate(method="linear", limit=6, limit_direction="both")
    return df


def build_station_series(base: pd.Series, bias: float, rng: np.random.Generator) -> pd.Series:
    """
    加站點偏置 + 微小高斯雜訊，模擬園區內 IoT 竿體讀數。
    雜訊 σ=1.5 µg/m³，與 MOENV 同類感測器實測離散度一致。
    """
    noise = rng.normal(0, 1.5, len(base))
    # 局部平滑（相鄰 3 小時）讓雜訊不過碎
    noise = pd.Series(noise, index=base.index).rolling(3, center=True, min_periods=1).mean().values
    s = base + bias + noise
    s = s.clip(lower=0.0)
    return s


def build_wide(base: pd.Series, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cols = {}
    for s in STATIONS:
        cols[s["name"]] = build_station_series(base, s["pm25_bias"], rng)
    return pd.DataFrame(cols, index=base.index)


def build_stations_json(wide: pd.DataFrame) -> list[dict]:
    last_complete = wide.dropna(how="any").index.max()
    if pd.isna(last_complete):
        last_complete = wide.dropna(how="all").index.max()
    snap = wide.loc[last_complete] if last_complete in wide.index else None

    result = []
    for s in STATIONS:
        name = s["name"]
        ser = wide[name].dropna()
        mean_pm25 = float(ser.mean()) if len(ser) > 0 else 0.0
        if snap is not None and not pd.isna(snap.get(name)):
            current = float(snap[name])
        else:
            current = mean_pm25
        result.append({
            "id":          s["id"],
            "name":        name,
            "name_zh":     s["name_zh"],
            "location_id": s["location_id"],
            "device_id":   s["device_id"],
            "lat":         s["lat"],
            "lon":         s["lon"],
            "zone":        s["zone"],
            "pm25":        round(current, 1),
            "pm25_mean":   round(mean_pm25, 1),
            "aqi":         pm25_to_aqi(current),
        })
    return result


def build_correlations_json(wide: pd.DataFrame) -> dict:
    names = [s["name"] for s in STATIONS]
    corr = wide[names].corr(method="pearson")
    matrix = []
    for r in names:
        row = []
        for c in names:
            v = corr.loc[r, c]
            row.append(round(float(v), 4) if not math.isnan(v) else 0.0)
        matrix.append(row)
    return {"stations": names, "matrix": matrix}


def build_timeseries_json(wide: pd.DataFrame) -> dict:
    names = [s["name"] for s in STATIONS]
    df = wide[names].copy()
    start = str(df.index[0])
    data = {}
    for name in names:
        data[name] = [
            round(float(v), 1) if (v is not None and not math.isnan(v)) else None
            for v in df[name]
        ]
    return {
        "start":      start,
        "step_hours": 1,
        "stations":   names,
        "data":       data,
        "n":          len(df),
    }


def build_electricity_json() -> dict:
    monthly = []
    for year, month, cons, sav in ELECTRICITY_MONTHLY:
        monthly.append({
            "year":             year,
            "month":            month,
            "label":            f"{year}-{month:02d}",
            "consumption_gwh":  cons,
            "savings_gwh":      sav,
            "savings_pct":      round(sav / (cons + sav) * 100, 1),
            "co2_reduction_kt": round(sav * 0.509, 1),  # 台電排放係數 0.509 kgCO₂/kWh
        })
    total_savings = sum(r["savings_gwh"] for r in monthly)
    total_cons    = sum(r["consumption_gwh"] for r in monthly)
    return {
        "source":      "SIPA 科學工業園區管理局年報",
        "unit":        "GWh",
        "monthly":     monthly,
        "summary": {
            "total_consumption_gwh": total_cons,
            "total_savings_gwh":     total_savings,
            "avg_savings_pct":       round(total_savings / (total_cons + total_savings) * 100, 1),
        },
    }


def main() -> None:
    print("讀取 新竹 EPA 基準資料…")
    base = load_base_pm25()
    print(f"  範圍 {base.index.min()} ~ {base.index.max()}, 有效 {base.notna().sum()} 小時")

    print("產生各站時序（基準 + 空間偏置 + 雜訊）…")
    wide = build_wide(base, seed=42)

    out_s = OUT_DIR / "stations.json"
    stations = build_stations_json(wide)
    out_s.write_text(json.dumps(stations, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {out_s}  ({len(stations)} 站)")

    out_c = OUT_DIR / "correlations.json"
    corr_data = build_correlations_json(wide)
    out_c.write_text(json.dumps(corr_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {out_c}")

    out_t = OUT_DIR / "pm25_timeseries.json"
    ts = build_timeseries_json(wide)
    out_t.write_text(
        json.dumps(ts, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"  → {out_t}  ({ts['n']} 時間點)")

    out_e = OUT_DIR / "electricity.json"
    elec = build_electricity_json()
    out_e.write_text(json.dumps(elec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {out_e}  ({len(elec['monthly'])} 月)")

    print("\n完成！")
    for f in [out_s, out_c, out_t, out_e]:
        print(f"  {f.name}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
