#!/usr/bin/env python3
"""
Preprocess CWA wind data + EPA PM2.5 timeseries into a combined JS data file
for the PM2.5 + Wind Direction dashboard.
"""

import os
import csv
import json
import io
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
CWA_DIR = os.path.join(BASE, "CWA_Weather_Final")
TS_FILE = os.path.join(BASE, "timeseries_data.json")
OUT_FILE = os.path.join(BASE, "wind_pm25_data.js")

# CWA station coordinates (WGS84). Keep this as the single source of truth
# for wind station metadata used by preprocessing and generated dashboard data.
CWA_STATION_META = {
    "taipei": {
        "station_id": "466920",
        "station_name": "臺北",
        "folder": "466920_臺北",
        "prefix": "466920",
        "lat": 25.037658,
        "lng": 121.514853,
        "has_full": True,
    },
    "xinyi": {
        "station_id": "C0AC70",
        "station_name": "信義",
        "folder": "C0A9C0_信義",
        "prefix": "C0AC70",
        "lat": 25.037822,
        "lng": 121.564597,
        "has_full": False,
    },
    "songshan_cwa": {
        "station_id": "C0AH70",
        "station_name": "松山",
        "folder": "C0AH70_松山",
        "prefix": "C0AH70",
        "lat": 25.048710,
        "lng": 121.550420,
        "has_full": False,
    },
    "wenshan": {
        "station_id": "C0AC80",
        "station_name": "文山",
        "folder": "C0AC80_文山",
        "prefix": "C0AC80",
        "lat": 25.002350,
        "lng": 121.575728,
        "has_full": False,
    },
    "neihu": {
        "station_id": "C0A9F0",
        "station_name": "內湖",
        "folder": "C0A9F0_內湖",
        "prefix": "C0A9F0",
        "lat": 25.079422,
        "lng": 121.575450,
        "has_full": False,
    },
    "yonghe": {
        "station_id": "C0AH10",
        "station_name": "永和",
        "folder": "C0AH10_永和",
        "prefix": "C0AH10",
        "lat": 25.011250,
        "lng": 121.508111,
        "has_full": False,
    },
}


def make_wind_station(key, meta):
    return {
        "key": key,
        "station_id": meta["station_id"],
        "station_name": meta["station_name"],
        "name": f"{meta['station_name']} {meta['station_id']}",
        "folder": meta["folder"],
        "prefix": meta["prefix"],
        "lat": meta["lat"],
        "lng": meta["lng"],
        "wd_col": "WD",
        "ws_col": "WS",
        "rh_col": "RH",
        "temp_col": "Temperature",
        "has_full": meta["has_full"],
    }


# Stations that have CWA wind direction columns in the local CSV folder.
WIND_STATIONS = [
    make_wind_station(key, meta)
    for key, meta in CWA_STATION_META.items()
]

INVALID = {'/', '--', '&', 'T', '', None}

def parse_float(s):
    if s is None: return None
    s = str(s).strip().strip('"')
    if s in INVALID:
        return None
    try:
        return float(s)
    except ValueError:
        return None

def parse_int(s):
    v = parse_float(s)
    return int(round(v)) if v is not None else None

def load_station_wind(station):
    folder = os.path.join(CWA_DIR, station["folder"])
    if not os.path.isdir(folder):
        print(f"  [WARN] Folder not found: {folder}")
        return []

    records = []
    files = sorted(f for f in os.listdir(folder) if f.endswith(".csv"))
    print(f"  Loading {len(files)} files from {station['folder']}")

    for fname in files:
        # Extract date from filename: PREFIX-YYYY-MM-DD.csv
        parts = fname.replace(".csv", "").split("-")
        if len(parts) < 4:
            continue
        try:
            date_str = f"{parts[-3]}-{parts[-2]}-{parts[-1]}"
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue

        fpath = os.path.join(folder, fname)
        try:
            with open(fpath, "r", encoding="utf-8-sig") as f:
                raw = f.read()
        except Exception:
            try:
                with open(fpath, "r", encoding="big5") as f:
                    raw = f.read()
            except Exception as e:
                print(f"    [ERROR] {fname}: {e}")
                continue

        lines = raw.strip().split("\n")
        if len(lines) < 3:
            continue

        # Row 0: Chinese headers, Row 1: English headers, Row 2+: data
        def parse_row(line):
            reader = csv.reader(io.StringIO(line))
            for row in reader:
                return [c.strip().strip('"') for c in row]
            return []

        eng_header = parse_row(lines[1])

        for line in lines[2:]:
            row = parse_row(line)
            if not row or len(row) < 3:
                continue

            def get(col_name):
                try:
                    idx = eng_header.index(col_name)
                    return row[idx] if idx < len(row) else None
                except ValueError:
                    return None

            obs_hour_str = get("ObsTime") or ""
            obs_hour_str = obs_hour_str.strip().strip('"')
            try:
                hour = int(obs_hour_str) % 24
            except Exception:
                continue

            ts = date + timedelta(hours=hour)

            wd = parse_int(get(station["wd_col"]))
            ws = parse_float(get(station["ws_col"]))
            rh = parse_float(get(station.get("rh_col", "RH")))
            temp = parse_float(get(station.get("temp_col", "Temperature")))

            records.append({
                "t": ts.strftime("%Y-%m-%dT%H:00"),
                "WD": wd,
                "WS": ws,
                "RH": rh,
                "Temp": round(temp, 1) if temp is not None else None
            })

    records.sort(key=lambda r: r["t"])
    print(f"    -> {len(records)} records, range: {records[0]['t'] if records else 'N/A'} ~ {records[-1]['t'] if records else 'N/A'}")
    return records


def load_pm25_timeseries():
    """Load timeseries_data.json and return as dict of station -> list of {t, v}"""
    with open(TS_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    pm25_keys = ["sp05_hourly", "songshan", "zhongshan", "wanhua", "guting", "shilin", "yangming"]
    stations = {k: [] for k in pm25_keys}

    for entry in raw:
        t_str = entry.get("time", "")
        # Normalize to YYYY-MM-DDTHH:00
        try:
            dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")
            t_norm = dt.strftime("%Y-%m-%dT%H:00")
        except Exception:
            continue

        for k in pm25_keys:
            v = entry.get(k)
            if v is not None:
                try:
                    stations[k].append({"t": t_norm, "v": round(float(v), 1)})
                except (ValueError, TypeError):
                    pass

    for k in pm25_keys:
        stations[k].sort(key=lambda r: r["t"])
        print(f"  PM2.5 {k}: {len(stations[k])} records")

    return stations


def compute_wind_rose(records, num_sectors=16):
    """Count frequency and avg WS per direction sector"""
    sector_size = 360 / num_sectors
    sectors = [{"dir": round(i * sector_size), "count": 0, "ws_sum": 0.0} for i in range(num_sectors)]

    for r in records:
        if r["WD"] is None or r["WS"] is None:
            continue
        idx = int((r["WD"] + sector_size / 2) / sector_size) % num_sectors
        sectors[idx]["count"] += 1
        sectors[idx]["ws_sum"] += r["WS"]

    total = sum(s["count"] for s in sectors)
    for s in sectors:
        s["freq"] = round(s["count"] / total * 100, 2) if total > 0 else 0
        s["avg_ws"] = round(s["ws_sum"] / s["count"], 2) if s["count"] > 0 else 0
        del s["ws_sum"]

    return sectors


def compute_dir_pm25(wind_records, pm25_records, num_sectors=8):
    """Bin PM2.5 values by wind direction sector (match by hour)"""
    pm25_map = {r["t"]: r["v"] for r in pm25_records}
    sector_size = 360 / num_sectors
    dir_names = ["北(N)", "東北(NE)", "東(E)", "東南(SE)", "南(S)", "西南(SW)", "西(W)", "西北(NW)"]

    bins = [[] for _ in range(num_sectors)]
    for r in wind_records:
        if r["WD"] is None:
            continue
        pm25 = pm25_map.get(r["t"])
        if pm25 is None:
            continue
        idx = int((r["WD"] + sector_size / 2) / sector_size) % num_sectors
        bins[idx].append(pm25)

    result = []
    for i, vals in enumerate(bins):
        if vals:
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            result.append({
                "dir": dir_names[i],
                "count": n,
                "mean": round(sum(vals) / n, 1),
                "median": round(vals_sorted[n // 2], 1),
                "q1": round(vals_sorted[n // 4], 1),
                "q3": round(vals_sorted[3 * n // 4], 1),
                "max": round(max(vals), 1),
                "min": round(min(vals), 1)
            })
        else:
            result.append({"dir": dir_names[i], "count": 0, "mean": None, "median": None, "q1": None, "q3": None, "max": None, "min": None})
    return result


def compute_scatter(wind_records, pm25_records, max_pts=800):
    """Create scatter data: (WS, WD, PM2.5) matched by hour"""
    pm25_map = {r["t"]: r["v"] for r in pm25_records}
    pts = []
    for r in wind_records:
        if r["WD"] is None or r["WS"] is None:
            continue
        pm25 = pm25_map.get(r["t"])
        if pm25 is None:
            continue
        pts.append({"t": r["t"], "WD": r["WD"], "WS": round(r["WS"], 1), "pm25": pm25})

    # Sample if too many
    if len(pts) > max_pts:
        step = len(pts) / max_pts
        pts = [pts[int(i * step)] for i in range(max_pts)]
    return pts


def main():
    print("=== Preprocessing Wind + PM2.5 Data ===\n")

    # Load wind data
    wind_data = {}
    for stn in WIND_STATIONS:
        print(f"[Wind] {stn['name']}")
        wind_data[stn["key"]] = {
            "meta": {k: stn[k] for k in ["key", "station_id", "station_name", "name", "lat", "lng"]},
            "records": load_station_wind(stn)
        }

    print(f"\n[PM2.5] Loading from timeseries_data.json")
    pm25_data = load_pm25_timeseries()

    # PM2.5 station metadata
    PM25_META = {
        "sp05_hourly": {"name": "SP-05 松菸", "lat": 25.044, "lng": 121.562},
        "songshan":    {"name": "松山 EPA",   "lat": 25.0497, "lng": 121.5775},
        "zhongshan":   {"name": "中山 EPA",   "lat": 25.0632, "lng": 121.5236},
        "wanhua":      {"name": "萬華 EPA",   "lat": 25.0313, "lng": 121.4992},
        "guting":      {"name": "古亭 EPA",   "lat": 25.020,  "lng": 121.530},
        "shilin":      {"name": "士林 EPA",   "lat": 25.0870, "lng": 121.5233},
        "yangming":    {"name": "陽明 EPA",   "lat": 25.1773, "lng": 121.5447},
    }

    # Build default pairing: taipei wind + songshan PM2.5
    print("\n[Analysis] Computing wind rose and correlations...")
    taipei_wind = wind_data["taipei"]["records"]
    songshan_pm25 = pm25_data["songshan"]

    # Build combined output
    output = {
        "wind_stations": {},
        "pm25_stations": PM25_META,
        "pm25_data": pm25_data,
        "precomputed": {}
    }

    for key, wdata in wind_data.items():
        records = wdata["records"]
        # Build time-series for compact transmission (keep only needed cols)
        compact = [{"t": r["t"], "WD": r["WD"], "WS": r["WS"], "RH": r["RH"]} for r in records]
        output["wind_stations"][key] = {
            **wdata["meta"],
            "records": compact
        }

    # Precompute for default pairing (taipei + each PM2.5 station)
    for pm25_key, pm25_records in pm25_data.items():
        output["precomputed"][f"taipei_{pm25_key}"] = {
            "wind_rose": compute_wind_rose(taipei_wind),
            "dir_pm25": compute_dir_pm25(taipei_wind, pm25_records),
            "scatter": compute_scatter(taipei_wind, pm25_records)
        }

    # Also precompute xinyi + songshan
    xinyi_wind = wind_data["xinyi"]["records"]
    output["precomputed"]["xinyi_songshan"] = {
        "wind_rose": compute_wind_rose(xinyi_wind),
        "dir_pm25": compute_dir_pm25(xinyi_wind, songshan_pm25),
        "scatter": compute_scatter(xinyi_wind, songshan_pm25)
    }

    # Precompute neihu + shilin
    neihu_wind = wind_data["neihu"]["records"]
    output["precomputed"]["neihu_shilin"] = {
        "wind_rose": compute_wind_rose(neihu_wind),
        "dir_pm25": compute_dir_pm25(neihu_wind, pm25_data["shilin"]),
        "scatter": compute_scatter(neihu_wind, pm25_data["shilin"])
    }

    # Precompute wenshan + guting
    wenshan_wind = wind_data["wenshan"]["records"]
    output["precomputed"]["wenshan_guting"] = {
        "wind_rose": compute_wind_rose(wenshan_wind),
        "dir_pm25": compute_dir_pm25(wenshan_wind, pm25_data["guting"]),
        "scatter": compute_scatter(wenshan_wind, pm25_data["guting"])
    }

    json_str = json.dumps(output, ensure_ascii=False, separators=(',', ':'))
    js_content = f"// Auto-generated by preprocess_wind_pm25.py\nconst WIND_PM25_DATA = {json_str};\n"

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(js_content)

    size_kb = os.path.getsize(OUT_FILE) / 1024
    print(f"\nOK Written: {OUT_FILE}")
    print(f"  File size: {size_kb:.1f} KB")
    print(f"  Wind stations: {list(wind_data.keys())}")
    print(f"  PM2.5 stations: {list(pm25_data.keys())}")
    print("Done!")


if __name__ == "__main__":
    main()
