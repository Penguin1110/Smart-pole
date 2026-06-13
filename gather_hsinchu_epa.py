"""
從環境部 (MOENV) 開放資料 API 抓取大新竹周邊 EPA 測站的 PM2.5 小時值，
存成 data/epa_data/epa_<站名>.csv。

Dataset: aqx_p_15 (一般空氣品質測站每小時測值)
涵蓋 8 站：新竹市（1）、新竹縣（2）、苗栗縣（2）、桃園市（3）
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_15"

# 大新竹周邊 8 站（官方站名，對應 MOENV aqx_p_15 sitename）
HSINCHU_EPA_STATIONS = ["新竹", "竹東", "湖口", "頭份", "苗栗", "龍潭", "觀音", "大園"]

DATE_START = "2025-12-01"
DATE_END   = "2026-02-28"

OUT_DIR = Path(__file__).parent / "data" / "epa_data"


def fetch_station(sitename: str, api_key: str) -> pd.DataFrame:
    """抓一個測站在日期區間內的 PM2.5，轉成 long format: [time, pm25, station]。"""
    params = {
        "format":   "json",
        "limit":    1000,
        "offset":   0,
        "api_key":  api_key,
        "filters": (
            f"itemengname,EQ,PM2.5|sitename,EQ,{sitename}|"
            f"monitordate,GR,2025-11-30|monitordate,LE,2026-03-01"
        ),
    }

    all_rows: list[dict] = []
    while True:
        r = requests.get(BASE_URL, params=params, timeout=60, verify=False)
        r.raise_for_status()
        batch = r.json()
        if not isinstance(batch, list) or len(batch) == 0:
            break
        all_rows.extend(batch)
        if len(batch) < params["limit"]:
            break
        params["offset"] += params["limit"]
        time.sleep(0.3)

    if not all_rows:
        return pd.DataFrame(columns=["time", "pm25", "station"])

    records = []
    for row in all_rows:
        date = pd.to_datetime(row["monitordate"].strip()).normalize()
        for h in range(24):
            v = row.get(f"monitorvalue{h:02d}")
            if v in (None, "", "x", "NA", "-"):
                pm25 = None
            else:
                try:
                    pm25 = float(v)
                except ValueError:
                    pm25 = None
            records.append({
                "time":    date + pd.Timedelta(hours=h),
                "pm25":    pm25,
                "station": sitename,
            })

    df = pd.DataFrame(records)
    mask = (
        (df["time"] >= pd.Timestamp(DATE_START)) &
        (df["time"] <  pd.Timestamp(DATE_END) + pd.Timedelta(days=1))
    )
    df = df[mask].sort_values("time").reset_index(drop=True)
    return df


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    load_env(Path(__file__).parent / ".env")
    api_key = os.environ.get("epa_api_key", "")
    if not api_key:
        raise RuntimeError("請在 .env 設定 epa_api_key=<你的金鑰>")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    summary = []
    for site in HSINCHU_EPA_STATIONS:
        print(f"[{site}] 下載中…", end="", flush=True)
        df = fetch_station(site, api_key)
        n = len(df)
        n_valid = df["pm25"].notna().sum() if n else 0

        out_path = OUT_DIR / f"epa_{site}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"  {n:5d} hr  (有效 {n_valid:5d}, {n_valid / max(n, 1) * 100:5.1f}%)  → {out_path.name}")
        summary.append({
            "station": site,
            "rows": n,
            "valid": n_valid,
            "completeness": n_valid / max(n, 1),
        })

    sm = pd.DataFrame(summary)
    sm.to_csv(OUT_DIR / "_hsinchu_summary.csv", index=False, encoding="utf-8-sig")
    sm.to_csv(OUT_DIR / "_greater_hsinchu_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\n完成 — {len(HSINCHU_EPA_STATIONS)} 站，範圍 {DATE_START} ~ {DATE_END}")
    print(f"輸出目錄: {OUT_DIR}")


if __name__ == "__main__":
    main()
