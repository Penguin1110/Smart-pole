"""
從 data/epa_data/ 的 12 個高雄 EPA 測站 CSV 產生 work/ 所需的 JSON 檔案：
  - stations.json      : 測站元資料（初始 PM2.5 取最後完整時刻）
  - correlations.json  : 12×12 Pearson 相關係數矩陣
  - pm25_timeseries.json: 完整 2160 小時時序（供前端時間滑桿使用）
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

# ── 測站座標（公開 TAQM 資料） ─────────────────────────────────────────────────
STATIONS = [
    {"id": "fuxing",    "name": "復興", "lat": 22.7326, "lon": 120.2924},
    {"id": "xiaogang",  "name": "小港", "lat": 22.5706, "lon": 120.3492},
    {"id": "qianzhen",  "name": "前鎮", "lat": 22.5942, "lon": 120.3201},
    {"id": "qianjin",   "name": "前金", "lat": 22.6224, "lon": 120.3079},
    {"id": "zuoying",   "name": "左營", "lat": 22.6870, "lon": 120.2988},
    {"id": "nanzi",     "name": "楠梓", "lat": 22.7317, "lon": 120.3073},
    {"id": "linyuan",   "name": "林園", "lat": 22.4986, "lon": 120.3768},
    {"id": "daliao",    "name": "大寮", "lat": 22.5677, "lon": 120.3875},
    {"id": "fengshan",  "name": "鳳山", "lat": 22.6222, "lon": 120.3574},
    {"id": "renwu",     "name": "仁武", "lat": 22.6976, "lon": 120.3608},
    {"id": "qiaotou",   "name": "橋頭", "lat": 22.7558, "lon": 120.3075},
    {"id": "meinong",   "name": "美濃", "lat": 22.8925, "lon": 120.5440},
]

DATA_DIR = Path(__file__).parent / "data" / "epa_data"
OUT_DIR  = Path(__file__).parent / "work"
OUT_DIR.mkdir(exist_ok=True)


def pm25_to_aqi(pm25: float) -> int:
    """線性內插 PM2.5 → AQI（台灣/美國 EPA 分段）。"""
    if math.isnan(pm25) or pm25 < 0:
        return 0
    breakpoints = [
        (0.0,   12.0,   0,   50),
        (12.1,  35.4,  51,  100),
        (35.5,  55.4, 101,  150),
        (55.5, 150.4, 151,  200),
        (150.5, 250.4, 201, 300),
        (250.5, 500.4, 301, 500),
    ]
    for lo_pm, hi_pm, lo_aqi, hi_aqi in breakpoints:
        if lo_pm <= pm25 <= hi_pm:
            return round((hi_aqi - lo_aqi) / (hi_pm - lo_pm) * (pm25 - lo_pm) + lo_aqi)
    return 500


def load_all() -> dict[str, pd.DataFrame]:
    dfs = {}
    for s in STATIONS:
        path = DATA_DIR / f"epa_{s['name']}.csv"
        df = pd.read_csv(path, parse_dates=["time"])
        df = df.sort_values("time").reset_index(drop=True)
        dfs[s["name"]] = df
    return dfs


def build_wide(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """合併成寬格式 DataFrame，index=time，columns=站名。"""
    series = {name: df.set_index("time")["pm25"] for name, df in dfs.items()}
    wide = pd.DataFrame(series)
    wide = wide.sort_index()
    return wide


def build_stations_json(dfs: dict[str, pd.DataFrame], wide: pd.DataFrame) -> list[dict]:
    """產生 stations.json — 包含座標、平均 PM2.5、AQI、最新快照值。"""
    # 找最後一個所有站都有資料的小時
    last_complete = wide.dropna(how="any").index.max()
    if pd.isna(last_complete):
        last_complete = wide.dropna(how="all").index.max()

    snapshot_row = wide.loc[last_complete] if last_complete in wide.index else None

    result = []
    for s in STATIONS:
        df = dfs[s["name"]]
        mean_pm25 = float(df["pm25"].mean(skipna=True))

        if snapshot_row is not None and not pd.isna(snapshot_row.get(s["name"])):
            snap = float(snapshot_row[s["name"]])
        else:
            # fallback: 最近有效值
            last_valid = df["pm25"].dropna().iloc[-1] if df["pm25"].notna().any() else mean_pm25
            snap = float(last_valid)

        aqi = pm25_to_aqi(snap)

        result.append({
            "id":       s["id"],
            "name":     s["name"],
            "lat":      s["lat"],
            "lon":      s["lon"],
            "pm25":     round(snap, 1),
            "pm25_mean": round(mean_pm25, 1),
            "aqi":      aqi,
            "county":   "高雄市",
        })
    return result


def build_correlations_json(wide: pd.DataFrame) -> dict:
    """計算各站兩兩 Pearson 相關係數。"""
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
    """完整時序（2160 小時）供前端時間滑桿使用。
    格式：
      start      : ISO8601 字串（第一個時間點）
      step_hours : 步長（固定 1）
      stations   : 站名列表（與 matrix 行順序一致）
      data       : { 站名: [v0, v1, ...] }，null 表示缺測
    """
    names = [s["name"] for s in STATIONS]
    df = wide[names].copy()
    # 短缺口用線性插補填補；長缺口保留 null
    df = df.interpolate(method="linear", limit=3, limit_direction="both")

    start = str(df.index[0])
    data = {}
    for name in names:
        data[name] = [round(float(v), 1) if (v is not None and not math.isnan(v)) else None
                      for v in df[name]]
    return {
        "start":      start,
        "step_hours": 1,
        "stations":   names,
        "data":       data,
        "n":          len(df),
    }


def main():
    print("讀取 EPA 資料…")
    dfs = load_all()
    wide = build_wide(dfs)

    print(f"  時間範圍: {wide.index.min()} ~ {wide.index.max()}")
    print(f"  總時間點: {len(wide)}, 完整時間點(所有站都有值): {wide.dropna(how='any').shape[0]}")

    print("產生 stations.json…")
    stations = build_stations_json(dfs, wide)
    (OUT_DIR / "stations.json").write_text(
        json.dumps(stations, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  → {len(stations)} 站")

    print("計算相關係數矩陣…")
    corr_data = build_correlations_json(wide)
    (OUT_DIR / "correlations.json").write_text(
        json.dumps(corr_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("產生完整時序資料（2160 小時）…")
    ts = build_timeseries_json(wide)
    (OUT_DIR / "pm25_timeseries.json").write_text(
        json.dumps(ts, ensure_ascii=False, separators=(',', ':')), encoding="utf-8"
    )

    print(f"\n完成！輸出至 {OUT_DIR}/")
    for f in sorted(OUT_DIR.glob("*.json")):
        print(f"  {f.name}  ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
