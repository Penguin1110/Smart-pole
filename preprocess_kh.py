#!/usr/bin/env python3
"""
preprocess_kh.py
讀取 cleaned_data_kaoshiung/ 下所有感測器 CSV，
計算小時均值後輸出三個 JSON 供前端使用：

  kh_timeseries.json  — [{time:"YYYY-MM-DD HH:00", <device_id>: value, ...}, ...]
  kh_daily_avg.json   — [{time:"YYYY-MM-DD", <device_id>_hourly: value, ...}, ...]
  kh_sensor_meta.json — {device_id: {device_id, name, lat, lon, ...}, ...}

用法：
  python3 preprocess_kh.py
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime

# ── 路徑設定 ────────────────────────────────────────────────
SENSOR_DIR      = "./cleaned_data_kaoshiung"
OUT_TIMESERIES  = "./kh_timeseries.json"
OUT_DAILY_AVG   = "./kh_daily_avg.json"
OUT_META        = "./kh_sensor_meta.json"

# 資料期間（超出範圍的筆數直接跳過）
DATE_START = "2025-12-04"
DATE_END   = "2026-02-08"

# PM2.5 有效值範圍
PM25_MIN =   0.0
PM25_MAX = 500.0

# ── 工具函式 ────────────────────────────────────────────────

def parse_hour(time_str: str) -> str | None:
    """將 'YYYY-MM-DD HH:MM:SS' 截短為 'YYYY-MM-DD HH:00'，失敗回傳 None。"""
    s = time_str.strip()
    if len(s) < 13:
        return None
    # 只要前 13 個字元：'YYYY-MM-DD HH'
    return s[:13] + ":00"

def parse_date(time_str: str) -> str | None:
    """取出日期部分 'YYYY-MM-DD'。"""
    return time_str[:10] if len(time_str) >= 10 else None

def safe_float(v: str) -> float | None:
    """轉 float，超出有效範圍或無法解析回傳 None。"""
    try:
        f = float(v)
        return f if PM25_MIN <= f <= PM25_MAX else None
    except (ValueError, TypeError):
        return None

def r2(v: float | None) -> float | None:
    return round(v, 2) if v is not None else None

# ── Step 1：讀取所有 CSV，累積小時列表 ────────────────────────

print("=== Step 1：讀取感測器 CSV ===")

# hourly_vals[device_id][hour_str] = [pm25, ...]
hourly_vals: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
# 記錄每台裝置的座標（CSV 裡通常為空，保留以備未來補充）
lats: dict[str, list[float]] = defaultdict(list)
lons: dict[str, list[float]] = defaultdict(list)
# 各裝置原始筆數與時間範圍
raw_counts:  dict[str, int] = {}
time_ranges: dict[str, tuple[str, str]] = {}

csv_files = sorted(f for f in os.listdir(SENSOR_DIR) if f.endswith(".csv"))
total = len(csv_files)
print(f"  找到 {total} 個 CSV 檔案\n")

for idx, fname in enumerate(csv_files, 1):
    device_id = fname[:-4]          # 去掉 .csv 即為裝置 ID
    fpath     = os.path.join(SENSOR_DIR, fname)
    count = valid = 0

    try:
        with open(fpath, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            # 清除欄位名稱可能的 BOM / 空白
            if reader.fieldnames:
                reader.fieldnames = [h.strip() for h in reader.fieldnames]

            for row in reader:
                count += 1
                t = row.get("time", "").strip()
                if not t:
                    continue
                d = parse_date(t)
                if d is None or not (DATE_START <= d <= DATE_END):
                    continue
                pm25 = safe_float(row.get("PM2.5", ""))
                if pm25 is None:
                    continue
                h = parse_hour(t)
                if h is None:
                    continue
                hourly_vals[device_id][h].append(pm25)
                valid += 1
                # 嘗試讀取座標（多數檔案為空）
                lat = safe_float(row.get("lat", ""))
                lon = safe_float(row.get("lon", ""))
                if lat is not None:
                    lats[device_id].append(lat)
                if lon is not None:
                    lons[device_id].append(lon)

    except Exception as e:
        print(f"  [警告] 無法讀取 {fname}: {e}")
        continue

    raw_counts[device_id] = count
    hours = list(hourly_vals[device_id].keys())
    if hours:
        time_ranges[device_id] = (min(hours), max(hours))

    if idx % 100 == 0 or idx == total:
        print(f"  [{idx}/{total}] {device_id}: {count} 筆原始 → "
              f"{len(hourly_vals[device_id])} 個整點小時")

# ── 計算小時均值 ─────────────────────────────────────────────

# hourly_avg[device_id][hour_str] = float | None
hourly_avg: dict[str, dict[str, float | None]] = {}
for device_id, h_dict in hourly_vals.items():
    hourly_avg[device_id] = {
        h: r2(sum(vals) / len(vals)) if vals else None
        for h, vals in h_dict.items()
    }

device_ids = sorted(hourly_avg.keys())
print(f"\n有效裝置數：{len(device_ids)}")

# ── Step 2：輸出 kh_timeseries.json ─────────────────────────

print("\n=== Step 2：建立 kh_timeseries.json ===")

# 收集所有整點時間戳
all_hours: set[str] = set()
for h_dict in hourly_avg.values():
    all_hours.update(h_dict.keys())

ts_list = []
for h in sorted(all_hours):
    row: dict = {"time": h}
    for device_id in device_ids:
        row[device_id] = hourly_avg[device_id].get(h)
    ts_list.append(row)

with open(OUT_TIMESERIES, "w", encoding="utf-8") as f:
    json.dump(ts_list, f, ensure_ascii=False, separators=(",", ":"))

print(f"  輸出 {len(ts_list)} 筆（整點）到 {OUT_TIMESERIES}")

# ── Step 3：輸出 kh_daily_avg.json ──────────────────────────

print("\n=== Step 3：建立 kh_daily_avg.json ===")

# 每裝置每日均值
daily_avg: dict[str, dict[str, float | None]] = {}
for device_id in device_ids:
    day_vals: dict[str, list[float]] = defaultdict(list)
    for h, v in hourly_avg[device_id].items():
        if v is not None:
            day_vals[h[:10]].append(v)
    daily_avg[device_id] = {
        d: r2(sum(vals) / len(vals)) for d, vals in day_vals.items()
    }

# 收集所有日期
all_dates: set[str] = set()
for d_dict in daily_avg.values():
    all_dates.update(d_dict.keys())

daily_list = []
for d in sorted(all_dates):
    row: dict = {"time": d}
    for device_id in device_ids:
        row[f"{device_id}_hourly"] = daily_avg[device_id].get(d)
    daily_list.append(row)

with open(OUT_DAILY_AVG, "w", encoding="utf-8") as f:
    json.dump(daily_list, f, ensure_ascii=False, separators=(",", ":"))

print(f"  輸出 {len(daily_list)} 天到 {OUT_DAILY_AVG}")

# ── Step 4：輸出 kh_sensor_meta.json ────────────────────────

print("\n=== Step 4：建立 kh_sensor_meta.json ===")

meta: dict[str, dict] = {}
for device_id in device_ids:
    lat = r2(sum(lats[device_id]) / len(lats[device_id])) if lats[device_id] else None
    lon = r2(sum(lons[device_id]) / len(lons[device_id])) if lons[device_id] else None
    t_start, t_end = time_ranges.get(device_id, (None, None))
    h_count = sum(1 for v in hourly_avg[device_id].values() if v is not None)

    meta[device_id] = {
        "device_id":    device_id,
        "name":         device_id,   # 無名稱對照表，預設用 ID；可事後手動補充
        "lat":          lat,
        "lon":          lon,
        "town":         None,
        "areatype":     None,
        "hourly_count": h_count,
        "time_start":   t_start,
        "time_end":     t_end,
    }

with open(OUT_META, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print(f"  輸出 {len(meta)} 台裝置到 {OUT_META}")

# ── 完成 ─────────────────────────────────────────────────────

print("\n=== 完成 ===")
print(f"  {OUT_TIMESERIES}")
print(f"  {OUT_DAILY_AVG}")
print(f"  {OUT_META}")
print("\n※ kh_sensor_meta.json 的 name / lat / lon / town 欄位目前為空，")
print("  請視需要手動補充或串接外部座標資料庫。")
