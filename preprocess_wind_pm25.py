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
DATA_DIR = os.path.join(BASE, "data")
MAIN_DIR = os.path.join(BASE, "main")
CWA_DIR = os.path.join(BASE, "CWA_Weather_Final")
OTHER_PM25_DIR = os.path.join(CWA_DIR, "其他")
TS_FILE = os.path.join(DATA_DIR, "timeseries_data.json")
PEAK_FILE = os.path.join(MAIN_DIR, "peak_data.js")
OUT_FILE = os.path.join(MAIN_DIR, "wind_pm25_data.js")
EVENT_OUT_FILE = os.path.join(MAIN_DIR, "event_diagnosis_data.js")

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
DIR16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
PM25_KEYS = ["sp05_hourly", "songshan", "zhongshan", "wanhua", "guting", "shilin", "yangming"]

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
                obs_hour = int(obs_hour_str)
            except Exception:
                continue

            if obs_hour == 24:
                ts = date + timedelta(days=1)
            elif 0 <= obs_hour <= 23:
                ts = date + timedelta(hours=obs_hour)
            else:
                continue

            wd = parse_int(get(station["wd_col"]))
            ws = parse_float(get(station["ws_col"]))
            rh = parse_float(get(station.get("rh_col", "RH")))
            temp = parse_float(get(station.get("temp_col", "Temperature")))
            td = parse_float(get("Td dew point"))
            stn_pres = parse_float(get("StnPres"))
            sea_pres = parse_float(get("SeaPres"))
            ws_gust = parse_float(get("WSGust"))
            wd_gust = parse_int(get("WDGust"))
            precp = parse_float(get("Precp"))
            precp_hour = parse_float(get("PrecpHour"))
            sunshine = parse_float(get("SunShine"))
            globl_rad = parse_float(get("GloblRad"))
            uvi = parse_float(get("UVI"))
            cloud = parse_float(get("Cloud Amount Sat"))

            records.append({
                "t": ts.strftime("%Y-%m-%dT%H:00"),
                "WD": wd,
                "WS": ws,
                "RH": rh,
                "Temp": round(temp, 1) if temp is not None else None,
                "Td": round(td, 1) if td is not None else None,
                "StnPres": round(stn_pres, 1) if stn_pres is not None else None,
                "SeaPres": round(sea_pres, 1) if sea_pres is not None else None,
                "WSGust": ws_gust,
                "WDGust": wd_gust,
                "Precp": precp,
                "PrecpHour": precp_hour,
                "SunShine": sunshine,
                "GloblRad": globl_rad,
                "UVI": uvi,
                "Cloud": cloud,
            })

    records.sort(key=lambda r: r["t"])
    print(f"    -> {len(records)} records, range: {records[0]['t'] if records else 'N/A'} ~ {records[-1]['t'] if records else 'N/A'}")
    return records


def load_pm25_timeseries():
    """Load data/timeseries_data.json and return station -> records."""
    with open(TS_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    stations = {k: [] for k in PM25_KEYS}

    for entry in raw:
        t_str = entry.get("time", "")
        # Normalize to YYYY-MM-DDTHH:00
        try:
            dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")
            t_norm = dt.strftime("%Y-%m-%dT%H:00")
        except Exception:
            continue

        for k in PM25_KEYS:
            v = entry.get(k)
            if v is not None:
                try:
                    stations[k].append({"t": t_norm, "v": round(float(v), 1)})
                except (ValueError, TypeError):
                    pass

    for k in PM25_KEYS:
        stations[k].sort(key=lambda r: r["t"])
        print(f"  PM2.5 {k}: {len(stations[k])} records")

    return stations


def load_other_pm25_sensors():
    """Load minute-level PM2.5 sensor CSVs under CWA_Weather_Final/其他 and aggregate to hourly means."""
    if not os.path.isdir(OTHER_PM25_DIR):
        return {}, {}

    data = {}
    meta = {}
    files = sorted(f for f in os.listdir(OTHER_PM25_DIR) if f.lower().endswith(".csv"))
    print(f"\n[Other PM2.5] Loading {len(files)} files from CWA_Weather_Final/其他")

    for fname in files:
        path = os.path.join(OTHER_PM25_DIR, fname)
        buckets = {}
        sensor_id = os.path.splitext(fname)[0]
        lat = None
        lng = None

        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = (row.get("deviceId") or sensor_id).strip()
                    sensor_id = sid or sensor_id
                    value = parse_float(row.get("PM2.5"))
                    t_raw = row.get("time")
                    if value is None or not t_raw:
                        continue
                    try:
                        dt = datetime.strptime(t_raw.strip(), "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue
                    t_hour = dt.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00")
                    buckets.setdefault(t_hour, []).append(value)
                    if lat is None:
                        lat = parse_float(row.get("lat"))
                    if lng is None:
                        lng = parse_float(row.get("lon"))
        except Exception as e:
            print(f"  [WARN] Failed to read {fname}: {e}")
            continue

        key = f"sensor_{sensor_id}"
        records = [
            {"t": t, "v": round(sum(vals) / len(vals), 1)}
            for t, vals in sorted(buckets.items())
            if vals
        ]
        if not records:
            print(f"  [WARN] {fname}: no usable PM2.5 rows")
            continue

        data[key] = records
        meta[key] = {
            "name": f"感測器 {sensor_id}",
            "device_id": sensor_id,
            "lat": lat,
            "lng": lng,
            "source": "CWA_Weather_Final/其他",
        }
        print(f"  {sensor_id}: {len(records)} hourly records, lat={lat}, lng={lng}")

    return data, meta


def load_peak_data():
    """Load main/peak_data.js without executing JavaScript."""
    with open(PEAK_FILE, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    prefix = "const PEAK_DATA = "
    if not raw.startswith(prefix):
        raise ValueError(f"Unsupported peak data format: {PEAK_FILE}")
    if raw.endswith(";"):
        raw = raw[:-1]
    return json.loads(raw[len(prefix):])


def parse_iso_hour(t):
    return datetime.strptime(t, "%Y-%m-%dT%H:00")


def fmt_iso_hour(dt):
    return dt.strftime("%Y-%m-%dT%H:00")


def add_hours(t, hours):
    return fmt_iso_hour(parse_iso_hour(t) + timedelta(hours=hours))


def mean(vals):
    clean = [v for v in vals if v is not None]
    return round(sum(clean) / len(clean), 2) if clean else None


def dir_name(wd):
    if wd is None:
        return None
    return DIR16[round((wd % 360) / 22.5) % 16]


def summarize_wind_window(wind_map, peak_time, lag, calm_threshold=0.5):
    rows = []
    for offset in range(-6, 1):
        pm_time = add_hours(peak_time, offset)
        wind_time = add_hours(pm_time, -lag)
        rec = wind_map.get(wind_time)
        if rec:
            rows.append({"pm_time": pm_time, "wind_time": wind_time, **rec})

    valid_wind = [r for r in rows if r.get("WD") is not None and r.get("WS") is not None]
    non_calm = [r for r in valid_wind if r["WS"] >= calm_threshold]
    calm_ratio = round((len(valid_wind) - len(non_calm)) / len(valid_wind), 2) if valid_wind else None

    dominant_dir = None
    direction_stability = None
    if non_calm:
        # Weighted circular mean. Use standard library only to keep preprocessing portable.
        import math
        x = sum(math.cos(math.radians(r["WD"])) * r["WS"] for r in non_calm)
        y = sum(math.sin(math.radians(r["WD"])) * r["WS"] for r in non_calm)
        total_ws = sum(r["WS"] for r in non_calm)
        wd = (math.degrees(math.atan2(y, x)) + 360) % 360
        dominant_dir = dir_name(wd)
        direction_stability = round(min(1, (x * x + y * y) ** 0.5 / total_ws), 2) if total_ws else None

    gust_ratios = []
    for r in valid_wind:
        ws = r.get("WS")
        gust = r.get("WSGust")
        if ws and gust is not None and ws > 0:
            gust_ratios.append(gust / ws)

    pressures = [r.get("StnPres") for r in rows if r.get("StnPres") is not None]
    pressure_delta = round(pressures[-1] - pressures[0], 2) if len(pressures) >= 2 else None
    rain_total = sum((r.get("Precp") or 0) for r in rows)

    return {
        "lag": lag,
        "wind_time": add_hours(peak_time, -lag),
        "n": len(valid_wind),
        "mean_ws": mean([r.get("WS") for r in valid_wind]),
        "calm_ratio": calm_ratio,
        "dominant_dir": dominant_dir,
        "direction_stability": direction_stability,
        "mean_rh": mean([r.get("RH") for r in rows]),
        "mean_temp": mean([r.get("Temp") for r in rows]),
        "mean_td": mean([r.get("Td") for r in rows]),
        "mean_temp_td_gap": mean([
            r.get("Temp") - r.get("Td")
            for r in rows
            if r.get("Temp") is not None and r.get("Td") is not None
        ]),
        "rain_total": round(rain_total, 2),
        "pressure_delta": pressure_delta,
        "mean_gust_ratio": round(sum(gust_ratios) / len(gust_ratios), 2) if gust_ratios else None,
    }


def summarize_pm_sync(peak_data, event):
    day = peak_data.get("ALL_DATA", {}).get(event["date"], {})
    hourly = day.get("hourly", {})
    peak_h = event["peakH"]
    values = {}
    for key in PM25_KEYS:
        series = hourly.get(key)
        if series and peak_h < len(series) and series[peak_h] is not None:
            values[key] = series[peak_h]
    elevated = {k: v for k, v in values.items() if v >= 25}
    high = {k: v for k, v in values.items() if v >= 35}
    return {
        "total": len(values),
        "elevated_count": len(elevated),
        "high_count": len(high),
        "mean_pm25": mean(list(values.values())),
        "values": values,
    }


def classify_event_summary(pm_sync, wind_summary):
    flags = []
    if pm_sync["total"] and pm_sync["elevated_count"] / pm_sync["total"] >= 0.6:
        flags.append("regional_sync")
    if wind_summary.get("calm_ratio") is not None and wind_summary["calm_ratio"] >= 0.45:
        flags.append("stagnation")
    if wind_summary.get("mean_rh") is not None and wind_summary["mean_rh"] >= 75:
        flags.append("humid_growth_possible")
    if wind_summary.get("mean_temp_td_gap") is not None and wind_summary["mean_temp_td_gap"] <= 3:
        flags.append("near_saturation")
    if wind_summary.get("rain_total") and wind_summary["rain_total"] > 0:
        flags.append("rain_affected")
    if (
        wind_summary.get("mean_ws") is not None
        and wind_summary["mean_ws"] >= 2
        and wind_summary.get("direction_stability") is not None
        and wind_summary["direction_stability"] >= 0.55
    ):
        flags.append("transport_plausible")

    if "regional_sync" in flags and "transport_plausible" in flags:
        label = "regional/transport"
    elif "stagnation" in flags:
        label = "stagnation"
    elif "regional_sync" in flags:
        label = "regional"
    elif "humid_growth_possible" in flags or "near_saturation" in flags:
        label = "humidity-influenced"
    elif "transport_plausible" in flags:
        label = "transport possible"
    else:
        label = "local/mixed"

    return {"label": label, "flags": flags}


def build_event_diagnosis(peak_data, wind_data):
    out = {
        "generated_by": "preprocess_wind_pm25.py",
        "window": "peak time offsets -6h..0h, paired with Wind(PM time - lag)",
        "calm_threshold": 0.5,
        "events": [],
    }
    wind_maps = {
        key: {r["t"]: r for r in wdata["records"]}
        for key, wdata in wind_data.items()
    }

    for event in peak_data.get("RANKED", []):
        peak_time = f"{event['date']}T{event['peakH']:02d}:00"
        pm_sync = summarize_pm_sync(peak_data, event)
        per_wind = {}
        for wind_key, wind_map in wind_maps.items():
            per_lag = {}
            for lag in range(-6, 7):
                summary = summarize_wind_window(wind_map, peak_time, lag)
                per_lag[str(lag)] = {
                    **summary,
                    "diagnosis": classify_event_summary(pm_sync, summary),
                }
            per_wind[wind_key] = per_lag
        out["events"].append({
            "rank": event["rank"],
            "date": event["date"],
            "peak_time": peak_time,
            "peak_hour": event["peakH"],
            "peak_pm25": event["peakV"],
            "daily_sp05": event.get("sp05"),
            "pm_sync": pm_sync,
            "wind": per_wind,
        })
    return out


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

    print(f"\n[PM2.5] Loading from {TS_FILE}")
    pm25_data = load_pm25_timeseries()
    other_pm25_data, other_pm25_meta = load_other_pm25_sensors()
    for key in other_pm25_data:
        if key not in PM25_KEYS:
            PM25_KEYS.append(key)
    pm25_data.update(other_pm25_data)
    print(f"\n[Peak] Loading from {PEAK_FILE}")
    peak_data = load_peak_data()

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

    PM25_META.update(other_pm25_meta)

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
        compact_cols = [
            "t", "WD", "WS", "RH", "Temp", "Td", "StnPres", "SeaPres",
            "WSGust", "WDGust", "Precp", "PrecpHour", "SunShine",
            "GloblRad", "UVI", "Cloud",
        ]
        compact = [{k: r.get(k) for k in compact_cols} for r in records]
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

    os.makedirs(MAIN_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(js_content)

    event_output = build_event_diagnosis(peak_data, wind_data)
    event_json = json.dumps(event_output, ensure_ascii=False, separators=(',', ':'))
    event_js = f"// Auto-generated by preprocess_wind_pm25.py\nconst EVENT_DIAGNOSIS_DATA = {event_json};\n"
    with open(EVENT_OUT_FILE, "w", encoding="utf-8") as f:
        f.write(event_js)

    size_kb = os.path.getsize(OUT_FILE) / 1024
    event_size_kb = os.path.getsize(EVENT_OUT_FILE) / 1024
    print(f"\nOK Written: {OUT_FILE}")
    print(f"  File size: {size_kb:.1f} KB")
    print(f"OK Written: {EVENT_OUT_FILE}")
    print(f"  File size: {event_size_kb:.1f} KB")
    print(f"  Wind stations: {list(wind_data.keys())}")
    print(f"  PM2.5 stations: {list(pm25_data.keys())}")
    print(f"  Event diagnoses: {len(event_output['events'])}")
    print("Done!")


if __name__ == "__main__":
    main()
