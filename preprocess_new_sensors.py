#!/usr/bin/env python3
"""
preprocess_new_sensors.py
讀取 cleaned_data/ 下所有微型感測器 CSV，計算小時平均後
合併進 timeseries_data.json、daily_avg.json、peak_data.js，
並輸出 sensor_meta.json。
"""

import csv
import json
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

# ── 路徑設定 ──────────────────────────────────────────────
SENSOR_DIR    = "./cleaned_data"
OUT_TIMESERIES = "./timeseries_data.json"
OUT_DAILY_AVG  = "./daily_avg.json"
OUT_PEAK_DATA  = "./peak_data.js"
OUT_META       = "./sensor_meta.json"

# 資料期間篩選（使用者指定）
DATE_START = "2025-12-03"
DATE_END   = "2026-02-04"

# PM2.5 有效範圍
PM25_MIN = 0
PM25_MAX = 500

# ── 工具函式 ─────────────────────────────────────────────

def parse_hour(time_str):
    """回傳整點字串 'YYYY-MM-DD HH:00:00'，失敗回傳 None。"""
    try:
        dt = datetime.strptime(time_str.strip(), "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:00:00")
    except Exception:
        return None

def parse_date(time_str):
    """回傳日期字串 'YYYY-MM-DD'。"""
    return time_str[:10] if len(time_str) >= 10 else None

def safe_float(v):
    try:
        f = float(v)
        return f if PM25_MIN <= f <= PM25_MAX else None
    except Exception:
        return None

def round2(v):
    return round(v, 2) if v is not None else None

# ── Step 1：讀取所有 CSV，計算小時平均 ───────────────────

print("=== Step 1: 讀取感測器 CSV ===")

# 結構：device_id -> hour_str -> [pm25, ...]
hourly_raw  = defaultdict(lambda: defaultdict(list))
# 結構：device_id -> [lon, ...]  /  [lat, ...]
all_lons    = defaultdict(list)
all_lats    = defaultdict(list)
record_counts = {}
time_ranges   = {}  # device_id -> (min_hour, max_hour)

csv_files = sorted(f for f in os.listdir(SENSOR_DIR) if f.endswith(".csv"))
print(f"  找到 {len(csv_files)} 個 CSV 檔案")

for fname in csv_files:
    device_id = fname[:-4]  # 去掉 .csv
    fpath = os.path.join(SENSOR_DIR, fname)
    count = 0
    valid = 0

    try:
        with open(fpath, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            # 去除 BOM 可能在欄位名稱上殘留的空白
            reader.fieldnames = [h.strip() for h in (reader.fieldnames or [])]
            for row in reader:
                count += 1
                t = row.get("time", "").strip()
                if not t:
                    continue
                # 日期篩選
                d = parse_date(t)
                if d is None or d < DATE_START or d > DATE_END:
                    continue
                pm25 = safe_float(row.get("PM2.5", ""))
                if pm25 is None:
                    continue
                h = parse_hour(t)
                if h is None:
                    continue
                hourly_raw[device_id][h].append(pm25)
                valid += 1
                try:
                    lon = float(row.get("lon", ""))
                    lat = float(row.get("lat", ""))
                    all_lons[device_id].append(lon)
                    all_lats[device_id].append(lat)
                except Exception:
                    pass
    except Exception as e:
        print(f"  [警告] 無法讀取 {fname}: {e}")
        continue

    record_counts[device_id] = count
    hours = list(hourly_raw[device_id].keys())
    if hours:
        time_ranges[device_id] = (min(hours), max(hours))
    print(f"  {device_id}: {count} 筆原始 → {len(hourly_raw[device_id])} 整點小時")

# ── 計算每裝置的小時均值 ──────────────────────────────────
# hourly_avg[device_id][hour_str] = float 或 None
hourly_avg = {}
for device_id, h_dict in hourly_raw.items():
    hourly_avg[device_id] = {}
    for h, vals in h_dict.items():
        if vals:
            hourly_avg[device_id][h] = round2(sum(vals) / len(vals))
        else:
            hourly_avg[device_id][h] = None

device_ids = sorted(hourly_avg.keys())
print(f"\n有效裝置數：{len(device_ids)}")

# ── Step 2：合併 timeseries_data.json ────────────────────

print("\n=== Step 2: 合併 timeseries_data.json ===")

with open(OUT_TIMESERIES, encoding="utf-8") as f:
    ts_list = json.load(f)

# 以 time 為 key 建立索引
ts_map = {row["time"]: row for row in ts_list}

# 收集現有 + 新裝置產生的所有整點時間戳
all_hours = set()
for row in ts_list:
    t = row["time"]
    # 只收集整點行（分秒為 :00:00）
    if t.endswith(":00:00"):
        all_hours.add(t)
# 加入新裝置的整點時間
for device_id in device_ids:
    for h in hourly_avg[device_id]:
        all_hours.add(h)

# 建立新的整點行（若不存在）
existing_cols = ["time", "sp05_raw", "sp05_hourly",
                 "songshan", "zhongshan", "wanhua", "guting", "shilin", "yangming"]
for h in all_hours:
    if h not in ts_map:
        ts_map[h] = {col: None for col in existing_cols}
        ts_map[h]["time"] = h

# 寫入新裝置欄位到所有 rows
for time_str, row in ts_map.items():
    is_hourly = time_str.endswith(":00:00")
    for device_id in device_ids:
        col = f"{device_id}_hourly"
        if is_hourly and time_str in hourly_avg[device_id]:
            row[col] = hourly_avg[device_id][time_str]
        else:
            if col not in row:
                row[col] = None

# 重新排序輸出
ts_out = sorted(ts_map.values(), key=lambda r: r["time"])
with open(OUT_TIMESERIES, "w", encoding="utf-8") as f:
    json.dump(ts_out, f, ensure_ascii=False, separators=(",", ":"))
print(f"  輸出 {len(ts_out)} 筆到 {OUT_TIMESERIES}")

# ── Step 3：更新 daily_avg.json ───────────────────────────

print("\n=== Step 3: 更新 daily_avg.json ===")

with open(OUT_DAILY_AVG, encoding="utf-8") as f:
    daily_list = json.load(f)

# 以日期為 key
daily_map = {row["time"]: row for row in daily_list}

# 計算每裝置每日均值（用小時平均的均值）
daily_device = defaultdict(dict)  # device_id -> date -> avg
for device_id in device_ids:
    day_vals = defaultdict(list)
    for h, v in hourly_avg[device_id].items():
        if v is not None:
            d = h[:10]
            day_vals[d].append(v)
    for d, vals in day_vals.items():
        daily_device[device_id][d] = round2(sum(vals) / len(vals))

# 補入現有 daily_map
for date_str, row in daily_map.items():
    for device_id in device_ids:
        col = f"{device_id}_hourly"
        row[col] = daily_device[device_id].get(date_str, None)

# 新增新裝置有但 daily_map 沒有的日期
all_dates = set(daily_map.keys())
for device_id in device_ids:
    for d in daily_device[device_id]:
        all_dates.add(d)

for d in all_dates:
    if d not in daily_map:
        new_row = {"time": d, "sp05_hourly": None,
                   "songshan": None, "zhongshan": None, "wanhua": None,
                   "guting": None, "shilin": None, "yangming": None}
        for device_id in device_ids:
            new_row[f"{device_id}_hourly"] = daily_device[device_id].get(d, None)
        daily_map[d] = new_row

daily_out = sorted(daily_map.values(), key=lambda r: r["time"])
with open(OUT_DAILY_AVG, "w", encoding="utf-8") as f:
    json.dump(daily_out, f, ensure_ascii=False, separators=(",", ":"))
print(f"  輸出 {len(daily_out)} 天到 {OUT_DAILY_AVG}")

# ── Step 4：更新 peak_data.js ─────────────────────────────

print("\n=== Step 4: 更新 peak_data.js ===")

with open(OUT_PEAK_DATA, encoding="utf-8") as f:
    raw_js = f.read()

# 擷取 JSON 部分（const PEAK_DATA = {...};）
m = re.search(r"const PEAK_DATA\s*=\s*(\{.*\})\s*;?\s*$", raw_js, re.DOTALL)
if not m:
    print("  [錯誤] 無法解析 peak_data.js，跳過此步驟")
else:
    peak_obj = json.loads(m.group(1))

    for date_str, day_data in peak_obj["ALL_DATA"].items():
        # daily 物件補入各裝置日均值
        for device_id in device_ids:
            col = f"{device_id}_hourly"
            day_data["daily"][col] = daily_device[device_id].get(date_str, None)

        # hourly 物件補入 24 小時陣列
        for device_id in device_ids:
            col = f"{device_id}_hourly"
            hourly_arr = []
            for h in range(24):
                hour_key = f"{date_str} {h:02d}:00:00"
                v = hourly_avg[device_id].get(hour_key, None)
                hourly_arr.append(v)
            day_data["hourly"][col] = hourly_arr

        # peaks 物件補入各裝置峰值
        for device_id in device_ids:
            col = f"{device_id}_hourly"
            arr = day_data["hourly"][col]
            valid_pairs = [(h, v) for h, v in enumerate(arr) if v is not None]
            if valid_pairs:
                peak_h, peak_v = max(valid_pairs, key=lambda x: x[1])
                day_data["peaks"][col] = {"h": peak_h, "v": peak_v}
            else:
                day_data["peaks"][col] = None

    out_js = "const PEAK_DATA = " + json.dumps(peak_obj, ensure_ascii=False, separators=(",", ":")) + ";"
    with open(OUT_PEAK_DATA, "w", encoding="utf-8") as f:
        f.write(out_js)
    print(f"  已更新 {OUT_PEAK_DATA}，補入 {len(device_ids)} 個裝置")

# ── Step 5：輸出 sensor_meta.json ─────────────────────────

print("\n=== Step 5: 輸出 sensor_meta.json ===")

meta = {}
for device_id in device_ids:
    lons = all_lons[device_id]
    lats = all_lats[device_id]
    hours = sorted(hourly_avg[device_id].keys())
    meta[device_id] = {
        "device_id": device_id,
        "lat": round(statistics.median(lats), 6) if lats else None,
        "lon": round(statistics.median(lons), 6) if lons else None,
        "record_count": record_counts.get(device_id, 0),
        "hourly_count": len(hours),
        "time_start": hours[0][:16].replace(" ", "T") if hours else None,
        "time_end":   hours[-1][:16].replace(" ", "T") if hours else None,
    }

with open(OUT_META, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print(f"  輸出 {len(meta)} 個裝置到 {OUT_META}")

print("\n=== 完成 ===")
print(f"裝置清單：{device_ids}")
