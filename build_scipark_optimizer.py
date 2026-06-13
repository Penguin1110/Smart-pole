"""
build_scipark_optimizer.py — 產生 work/pm25_optimizer_scipark.html

執行順序：
  1. python generate_scipark_json.py   # 產生 data/scipark/*.json
  2. python build_scipark_optimizer.py # 產生 HTML（本檔）

特色：
  - 10 根 HSIP 智慧桿 PM2.5
  - 完整窮舉搜尋 (n=0–24h × m=1–9 × method=Mean/IDW×8/Corr/Ridge/Self)
  - 熱力圖 + Lookback 動畫（與 Hsinchu/Kaohsiung optimizer 相同）
  - 月用電量 / 節電量圖表 (SIPA 年報)
  - 自給資料，單一 HTML 可直接開啟
"""

import json
import pathlib

BASE = pathlib.Path(__file__).parent
DATA = BASE / "data" / "scipark"
OUT  = BASE / "work" / "pm25_optimizer_scipark.html"
OUT.parent.mkdir(exist_ok=True)


def _j(path: pathlib.Path) -> str:
    return json.dumps(
        json.loads(path.read_text("utf-8")),
        ensure_ascii=False,
        separators=(",", ":"),
    )


SJ = _j(DATA / "stations.json")
CJ = _j(DATA / "correlations.json")
TJ = _j(DATA / "pm25_timeseries.json")
EJ = _j(DATA / "electricity.json")

M  = len(json.loads(SJ)) - 1   # max K

HTML = f"""\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>HSIP Smart Pole Dashboard — PM2.5 &amp; Energy</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
:root{{
  --bg:#f0f4f8;--panel:#fff;--text:#16202b;--muted:#5f6b7a;
  --border:#d9e2ec;--sh:0 8px 24px rgba(22,32,43,.09);
  --good:#2e7d32;--mod:#f9a825;--usg:#ef6c00;
  --unhealthy:#c62828;--primary:#1e66d0;--orange:#ef6c00;
  --energy:#00796b;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%;font-family:Inter,system-ui,sans-serif;color:var(--text);background:var(--bg)}}
body{{display:flex;flex-direction:column;padding:10px;gap:8px}}

.hdr{{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  box-shadow:var(--sh);padding:10px 16px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
.hdr-title{{font-size:15px;font-weight:800;flex:1}}
.hdr-sub{{font-size:10px;color:var(--muted);flex-basis:100%;margin-top:1px;line-height:1.5}}
.badge{{padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;color:#fff;
  background:var(--primary);white-space:nowrap}}
.badge.en{{background:var(--energy)}}

.tbar{{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  box-shadow:var(--sh);padding:8px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.tbar-label{{font-size:13px;font-weight:700;min-width:160px}}
.tbar-sub{{font-size:10px;color:var(--muted)}}
.icon-btn{{width:28px;height:28px;border:1px solid var(--border);border-radius:6px;
  background:#fff;cursor:pointer;font-size:12px;display:grid;place-items:center}}
.icon-btn.playing{{background:var(--primary);border-color:var(--primary);color:#fff}}
.icon-btn.playing-lb{{background:var(--orange);border-color:var(--orange);color:#fff}}
#timeSlider{{flex:1;min-width:160px;accent-color:var(--primary)}}
#lbSlider{{accent-color:var(--orange)}}
.speed-sel{{height:28px;border:1px solid var(--border);border-radius:6px;padding:0 6px;
  font:inherit;font-size:11px;background:#fff;color:var(--text)}}
.mjump{{display:flex;gap:4px;align-items:center;font-size:11px;color:var(--muted)}}
.mbtn{{padding:2px 8px;border:1px solid var(--border);border-radius:5px;background:#fff;
  font:inherit;font-size:11px;cursor:pointer}}
.mbtn:hover,.mbtn.active{{background:var(--primary);border-color:var(--primary);color:#fff}}

.app{{flex:1;display:grid;grid-template-columns:1fr 440px;gap:8px;min-height:0}}
.panel{{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  box-shadow:var(--sh);overflow:hidden;display:flex;flex-direction:column}}
#map{{flex:1;min-height:420px;background:#dbeafe}}
.map-bottom{{flex-shrink:0;display:flex;flex-direction:column;gap:0}}
.ts-wrap{{padding:6px 12px;border-top:1px solid var(--border);display:none;flex-direction:column;gap:3px}}
.ts-wrap.active{{display:flex}}
.ts-title{{font-size:10px;font-weight:700;color:var(--muted)}}
canvas#tsChart{{max-height:80px}}
.legend{{padding:6px 12px;display:flex;flex-wrap:wrap;gap:5px;border-top:1px solid var(--border);
  flex-shrink:0;font-size:10px}}
.li{{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border:1px solid var(--border);
  border-radius:999px;color:var(--muted);background:#fff}}
.sw{{width:8px;height:8px;border-radius:50%;display:inline-block}}
.err-grad{{width:70px;height:7px;border-radius:4px;
  background:linear-gradient(90deg,#2e7d32,#f9a825,#c62828)}}

/* sidebar */
.sb{{display:flex;flex-direction:column;min-height:0}}
.sb-tabs{{display:flex;border-bottom:1px solid var(--border);background:#f8fbff;flex-shrink:0}}
.sb-tab{{flex:1;padding:7px 4px;border:none;background:transparent;cursor:pointer;
  font:inherit;font-size:11px;font-weight:600;color:var(--muted);
  border-bottom:2px solid transparent;transition:all .15s}}
.sb-tab.active{{color:var(--primary);border-bottom-color:var(--primary);background:#fff}}
.sb-pane{{flex:1;overflow-y:auto;padding:10px 12px;display:none;flex-direction:column;gap:8px}}
.sb-pane.active{{display:flex}}

/* controls */
.ctrl-title{{font-size:12px;font-weight:700}}
.ctrl-sub{{font-size:10px;color:var(--muted)}}
.field label{{font-size:11px;color:var(--muted);display:block;margin-bottom:3px;font-weight:500}}
.field select{{width:100%;height:30px;border-radius:7px;border:1px solid var(--border);
  padding:0 8px;font:inherit;font-size:11px;color:var(--text);background:#fff}}
.row2{{display:grid;grid-template-columns:1fr auto;gap:6px;align-items:end}}
.btn{{height:30px;border:1px solid var(--border);border-radius:7px;padding:0 12px;
  background:#fff;color:var(--text);font:inherit;font-size:11px;cursor:pointer;transition:all .2s}}
.btn.primary{{background:var(--primary);border-color:var(--primary);color:#fff}}
.btn.primary:hover:not(:disabled){{background:#1557b8}}
.btn:disabled{{opacity:.5;cursor:not-allowed}}
.info-pill{{background:#f0f4f8;border-radius:6px;padding:5px 9px;font-size:11px;
  display:flex;gap:10px;flex-wrap:wrap}}
.info-pill b{{color:var(--text)}}

/* lookback */
.lb-ctrl{{padding:7px 12px;border-bottom:1px solid var(--border);
  background:#fffcf0;flex-shrink:0;display:grid;gap:5px}}
.lb-hd{{display:flex;justify-content:space-between;align-items:center}}
.lb-title{{font-size:11px;font-weight:700;color:#7c5a00}}
.lb-lbl{{font-size:12px;font-weight:800;color:var(--orange)}}
.lb-row{{display:flex;align-items:center;gap:5px}}
.lb-hint{{font-size:10px;color:var(--muted);line-height:1.4}}

/* best bar */
.best-bar{{padding:7px 12px;border-bottom:1px solid var(--border);
  background:#f8fbff;font-size:11px;display:flex;align-items:center;
  flex-wrap:wrap;gap:3px 7px;flex-shrink:0;min-height:34px}}
.best-bar.found{{background:#eff6ff}}
.bb-trophy{{font-size:13px}}
.bb-method{{font-weight:700;color:var(--primary)}}
.bb-err{{font-weight:700;color:var(--primary);font-size:12px}}
.bb-dot{{color:var(--border)}}
.bb-empty{{color:var(--muted)}}

/* method compare */
.mc-wrap{{padding:7px 12px;border-bottom:1px solid var(--border);flex-shrink:0}}
.mc-title{{font-size:10px;font-weight:700;color:var(--muted);margin-bottom:4px}}
.mc-table{{width:100%;font-size:11px;border-collapse:collapse}}
.mc-table th{{background:#f0f4f8;padding:3px 5px;text-align:left;
  border-bottom:1px solid var(--border);font-size:10px;font-weight:600}}
.mc-table td{{padding:3px 5px;border-bottom:1px solid #eef2f7}}
.mc-table .best-row td{{background:#eff6ff;font-weight:700;color:var(--primary)}}
.mc-table tr:hover td{{background:#f8fbff}}

/* heatmap */
.hm-section{{flex:1;display:flex;flex-direction:column;min-height:0;overflow:hidden}}
.tab-bar{{display:flex;gap:3px;padding:6px 8px 0;background:#f8fbff;
  border-bottom:1px solid var(--border);flex-shrink:0}}
.tab-btn{{padding:3px 8px;border:1px solid var(--border);border-radius:6px 6px 0 0;
  background:#fff;font:inherit;font-size:10px;cursor:pointer;transition:all .15s;
  border-bottom:none;position:relative;top:1px}}
.tab-btn.active{{background:#fff;border-color:var(--primary);color:var(--primary);font-weight:700}}
.tab-btn:hover:not(.active){{background:#f0f7ff}}
.hm-outer{{flex:1;overflow:auto;padding:5px 7px}}
.hm-table{{border-collapse:collapse;font-size:9px;white-space:nowrap}}
.hm-th{{background:#f0f4f8;padding:2px 3px;text-align:center;border:1px solid #d4dde8;
  font-weight:600;font-size:9px;position:sticky;top:0;z-index:2}}
.hm-rh{{background:#f0f4f8;padding:2px 5px;text-align:right;border:1px solid #d4dde8;
  font-weight:600;font-size:9px;white-space:nowrap;position:sticky;left:0;z-index:1;
  cursor:pointer;transition:background .15s}}
.hm-rh:hover{{background:#dbeafe}}
.hm-rh.lb-active{{background:#bfdbfe;color:var(--primary);font-weight:800}}
.hm-cell{{border:1px solid rgba(0,0,0,.06);width:29px;height:19px;text-align:center;
  cursor:pointer;font-size:9px;vertical-align:middle;transition:outline .1s}}
.hm-cell:hover{{outline:2px solid var(--primary);outline-offset:-2px;z-index:3;position:relative}}
.hm-cell.selected{{outline:2px solid #1557b8;outline-offset:-2px;z-index:4;position:relative;font-weight:900}}
.hm-cell.global-best{{outline:2px solid var(--orange);outline-offset:-1px;font-weight:900}}
.hm-na{{border:1px solid #eef2f7;width:29px;height:19px;text-align:center;
  font-size:8px;color:#d0d7e0;vertical-align:middle}}
.hm-empty{{text-align:center;padding:24px;font-size:12px;color:var(--muted)}}
.self-table{{width:100%;border-collapse:collapse;font-size:11px}}
.self-table th{{background:#f0f4f8;padding:3px 6px;text-align:left;
  border-bottom:1px solid var(--border);font-size:10px}}
.self-table td{{padding:3px 6px;border-bottom:1px solid #eef2f7}}
.self-table tr.lb-active td{{background:#bfdbfe;font-weight:700}}
.self-bar{{display:inline-block;height:12px;border-radius:3px;min-width:2px;vertical-align:middle}}

/* map markers */
.mk{{width:34px;height:34px;border-radius:50%;border:2px solid rgba(255,255,255,.96);
  box-shadow:0 2px 8px rgba(0,0,0,.18);display:grid;place-items:center;
  color:#fff;font-size:11px;font-weight:800;transform:translate(-50%,-50%);cursor:pointer;transition:transform .2s}}
.mk:hover{{transform:translate(-50%,-50%) scale(1.15)}}
.target-mk{{border:3px solid var(--primary);box-shadow:0 0 0 4px rgba(30,102,208,.25),0 2px 8px rgba(0,0,0,.18)}}
.nb-mk{{border:2px solid var(--orange);box-shadow:0 0 0 3px rgba(239,108,0,.2),0 2px 8px rgba(0,0,0,.18)}}
.dim-mk{{opacity:.18;pointer-events:none}}
.mk-tag{{position:absolute;top:38px;left:50%;transform:translateX(-50%);
  background:var(--primary);color:#fff;font-size:9px;font-weight:700;
  padding:2px 5px;border-radius:4px;white-space:nowrap;pointer-events:none;line-height:1.4;
  box-shadow:0 1px 3px rgba(0,0,0,.25)}}
.mk-tag.orange{{background:var(--orange)}}
.mk-tag.err{{top:56px;background:#fff;color:var(--primary);border:1px solid var(--primary)}}

/* energy panel */
.kpi-grid{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}
.kpi{{background:#f8fbff;border:1px solid var(--border);border-radius:8px;padding:8px 10px}}
.kpi.green{{background:#f1f8e9;border-color:#a5d6a7}}
.kpi.blue{{background:#e3f2fd;border-color:#90caf9}}
.kpi-label{{font-size:10px;color:var(--muted);font-weight:600;margin-bottom:3px}}
.kpi-val{{font-size:18px;font-weight:800}}
.kpi-sub{{font-size:10px;color:var(--muted);margin-top:1px}}
.chart-wrap{{background:#f8fbff;border:1px solid var(--border);border-radius:8px;padding:8px 10px}}
.chart-title{{font-size:11px;font-weight:700;margin-bottom:4px}}
.chart-sub{{font-size:10px;color:var(--muted);margin-bottom:6px}}

/* zones */
.zone-block{{border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:6px;cursor:pointer}}
.zone-hdr{{padding:6px 10px;display:flex;align-items:center;gap:8px;color:#fff}}
.zone-body{{padding:6px 10px}}
.zone-row{{display:flex;align-items:center;gap:6px;padding:2px 0;font-size:10px}}

.leaflet-popup-content{{margin:10px 12px;font:inherit;line-height:1.5}}
.pt{{font-size:14px;font-weight:700;margin-bottom:3px}}
.pg{{display:grid;gap:2px;font-size:12px}}
.pg span{{color:var(--muted)}}

@media(max-width:1000px){{.app{{grid-template-columns:1fr}}#map{{min-height:360px}}}}
</style>
</head>
<body>

<script>
const _SD={SJ};
const _CD={CJ};
const _TD={TJ};
const _ED={EJ};
</script>

<!-- ─── Header ───────────────────────────────── -->
<header class="hdr">
  <span style="font-size:22px">🏭</span>
  <div style="flex:1">
    <div class="hdr-title">Hsinchu Science Industrial Park — Smart Pole Dashboard</div>
    <div class="hdr-sub">
      IoT PM2.5 · 10 stations (k-means from 78 HSIP AQ1001 devices, MOENV IoT registry)
      · Base: 新竹 EPA TAQM + zone spatial bias ± 2 µg/m³ · σ=1.5 noise ·
      Exhaustive search: n(0–24h) × m(1–{M}) × method(Mean / IDW×8p / Corr / Ridge / Self)
      · Electricity: SIPA Annual Report 2025–2026
    </div>
  </div>
  <span class="badge">PM2.5</span>
  <span class="badge en">⚡ Energy</span>
</header>

<!-- ─── Time bar ─────────────────────────────── -->
<div class="tbar">
  <div>
    <div class="tbar-label" id="tLabel">—</div>
    <div class="tbar-sub" id="tSub">新竹科學工業園區 · HSIP</div>
  </div>
  <div class="mjump">Jump:
    <button class="mbtn" data-step="0">Dec</button>
    <button class="mbtn" data-step="744">Jan</button>
    <button class="mbtn" data-step="1488">Feb</button>
  </div>
  <button class="icon-btn" id="prevBtn">&#9664;</button>
  <button class="icon-btn playing" id="playBtn" title="Play/pause time">&#9654;</button>
  <button class="icon-btn" id="nextBtn">&#9654;&#9654;</button>
  <input type="range" id="timeSlider" min="0" max="2159" value="2159" step="1" style="flex:1;min-width:150px"/>
  <select class="speed-sel" id="speedSel">
    <option value="500">Slow</option>
    <option value="200" selected>Normal</option>
    <option value="80">Fast</option>
    <option value="30">Very fast</option>
  </select>
</div>

<!-- ─── Main layout ───────────────────────────── -->
<div class="app">

  <!-- MAP -->
  <section class="panel">
    <div id="map"></div>
    <div class="map-bottom">
      <div class="ts-wrap" id="tsWrap">
        <div class="ts-title" id="tsTitle">PM2.5 — </div>
        <canvas id="tsChart"></canvas>
      </div>
      <div class="legend">
        <span class="li"><span class="sw" style="background:#2e7d32"></span>Good (&le;12)</span>
        <span class="li"><span class="sw" style="background:#f9a825"></span>Moderate (&le;35)</span>
        <span class="li"><span class="sw" style="background:#ef6c00"></span>USG (&le;55)</span>
        <span class="li"><span class="sw" style="background:#c62828"></span>Unhealthy</span>
        <span style="margin-left:auto;display:flex;align-items:center;gap:5px;color:var(--muted)">
          Imputation error: <span class="err-grad"></span> Low → High
        </span>
      </div>
    </div>
  </section>

  <!-- SIDEBAR -->
  <aside class="panel sb" style="min-height:0">
    <div class="sb-tabs">
      <button class="sb-tab active" data-pane="search">🔍 PM2.5 Search</button>
      <button class="sb-tab" data-pane="energy">⚡ Energy</button>
      <button class="sb-tab" data-pane="zones">🗺 Zones</button>
    </div>

    <!-- ── PM2.5 Search pane ── -->
    <div class="sb-pane active" id="pane-search" style="padding:0;gap:0;overflow:hidden">
      <!-- Controls -->
      <div style="padding:10px 12px;border-bottom:1px solid var(--border);background:linear-gradient(180deg,#fbfdff,#f8fbff);display:grid;gap:6px;flex-shrink:0">
        <div>
          <div class="ctrl-title">Target Station &amp; Exhaustive Search</div>
          <div class="ctrl-sub">IDW power p exhausted over {{0.5,1,1.5,2,2.5,3,4,5}}; &lt;1 s total</div>
        </div>
        <div class="row2">
          <div class="field">
            <label for="targetSel">Target station (treated as missing)</label>
            <select id="targetSel"></select>
          </div>
          <button class="btn primary" id="searchBtn">&#9881; Search</button>
        </div>
        <div class="info-pill">
          <span>Value: <b id="tiVal">--</b> µg/m³</span>
          <span>Time: <b id="tiTime">--</b></span>
          <span>Station: <b id="tiZone">--</b></span>
        </div>
      </div>

      <!-- Lookback -->
      <div class="lb-ctrl">
        <div class="lb-hd">
          <span class="lb-title">&#9654; Lookback animation (n = 0 → 24 h)</span>
          <span class="lb-lbl" id="lbLabel">n = 0 h (current)</span>
        </div>
        <div class="lb-row">
          <button class="icon-btn" id="lbPrevBtn">&#9664;</button>
          <button class="icon-btn playing-lb" id="lbPlayBtn">&#9654;</button>
          <button class="icon-btn" id="lbNextBtn">&#9654;&#9654;</button>
          <input type="range" id="lbSlider" min="0" max="24" value="0" step="1" style="flex:1;min-width:80px"/>
          <select class="speed-sel" id="lbSpeedSel">
            <option value="1000">Slow</option>
            <option value="500" selected>Normal</option>
            <option value="250">Fast</option>
          </select>
        </div>
        <div class="lb-hint">After search: drag or play — blue=target, orange=best neighbor (n h ago)</div>
      </div>

      <!-- Best bar -->
      <div class="best-bar" id="bestBar">
        <span class="bb-empty">Run Search to display the best combination</span>
      </div>

      <!-- Method compare -->
      <div class="mc-wrap" id="mcWrap" style="display:none">
        <div class="mc-title">Per-method best comparison</div>
        <table class="mc-table">
          <thead><tr><th>Method</th><th>Lookback n</th><th>K</th><th>Error (µg/m³)</th></tr></thead>
          <tbody id="mcBody"></tbody>
        </table>
      </div>

      <!-- Heatmap -->
      <div class="hm-section">
        <div class="tab-bar" id="tabBar">
          <button class="tab-btn active" data-tab="best">Best</button>
          <button class="tab-btn" data-tab="self">Self</button>
          <button class="tab-btn" data-tab="mean">Mean</button>
          <button class="tab-btn" data-tab="idw">IDW</button>
          <button class="tab-btn" data-tab="corr">Corr</button>
          <button class="tab-btn" data-tab="ridge">Ridge</button>
        </div>
        <div class="hm-outer" id="hmOuter">
          <div class="hm-empty">Run Search to display the heatmap<br>
            <small>x-axis: m (neighbors), y-axis: n (lookback h)</small></div>
        </div>
      </div>
    </div>

    <!-- ── Energy pane ── -->
    <div class="sb-pane" id="pane-energy">
      <div>
        <div class="ctrl-title">Park-Wide Electricity · SIPA Data</div>
        <div class="ctrl-sub">科學工業園區管理局年報 · 全園月用電量 GWh · 2025–2026</div>
      </div>
      <div class="kpi-grid">
        <div class="kpi blue">
          <div class="kpi-label">Total Consumption</div>
          <div class="kpi-val" id="kpiCons">—</div>
          <div class="kpi-sub">GWh (period)</div>
        </div>
        <div class="kpi green">
          <div class="kpi-label">Total Energy Saved</div>
          <div class="kpi-val" id="kpiSav">—</div>
          <div class="kpi-sub">GWh 節電量</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Avg Monthly Savings</div>
          <div class="kpi-val" id="kpiPct">—</div>
          <div class="kpi-sub">% vs baseline</div>
        </div>
        <div class="kpi green">
          <div class="kpi-label">CO₂ Reduction</div>
          <div class="kpi-val" id="kpiCO2">—</div>
          <div class="kpi-sub">k-tonnes CO₂</div>
        </div>
      </div>
      <div class="chart-wrap">
        <div class="chart-title">Monthly Electricity Consumption</div>
        <div class="chart-sub">GWh · Consumption (blue) stacked with Savings (green)</div>
        <canvas id="consChart" style="max-height:160px"></canvas>
      </div>
      <div class="chart-wrap">
        <div class="chart-title">Monthly Energy Savings 節電量 &amp; CO₂</div>
        <div class="chart-sub">GWh saved (bars) · CO₂ k-tonnes (line, factor 0.509 kgCO₂/kWh)</div>
        <canvas id="savChart" style="max-height:160px"></canvas>
      </div>
      <div style="font-size:10px;color:var(--muted);line-height:1.6;padding:4px 2px">
        <b>Source:</b> 科學工業園區管理局 (SIPA) Annual Report 2025–2026 ·
        Electricity figures represent whole-park aggregate (全園) consumption including
        semiconductor fabs, R&amp;D centers, and support facilities.
        CO₂ factor: TPC 2024 emission coefficient 0.509 kgCO₂/kWh.
      </div>
    </div>

    <!-- ── Zones pane ── -->
    <div class="sb-pane" id="pane-zones">
      <div>
        <div class="ctrl-title">PM2.5 by Zone (current timestamp)</div>
        <div class="ctrl-sub">Click a zone header to highlight stations on map</div>
      </div>
      <div id="zoneTable"></div>
      <div style="font-size:10px;color:var(--muted);line-height:1.6;margin-top:4px">
        <b>Data note:</b> Station locations from MOENV IoT station registry (MOENV_iot_station.csv).
        PM2.5 time-series: 新竹 EPA TAQM station (aqx_p_15) as regional background + per-zone
        spatial bias + σ=1.5 µg/m³ noise (matching AQ1001 sensor spec).
        Electricity: SIPA Annual Report 2025–2026.
      </div>
    </div>
  </aside>
</div>

<script>
/* ══════════════════════════════════════════════════════
   INIT DATA
══════════════════════════════════════════════════════ */
const stations = _SD;
const corrMat  = _CD;
const tsData   = _TD.data;
const N_TIME   = _TD.n;
const NAMES    = _TD.stations;
const M        = stations.length - 1;
const IDW_P_VALS = [0.5,1.0,1.5,2.0,2.5,3.0,4.0,5.0];

/* ══════════════════════════════════════════════════════
   HELPERS
══════════════════════════════════════════════════════ */
function esc(s){{return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function haversine(lat1,lon1,lat2,lon2){{
  const R=6371000,r=Math.PI/180;
  const dLat=(lat2-lat1)*r,dLon=(lon2-lon1)*r;
  const a=Math.sin(dLat/2)**2+Math.cos(lat1*r)*Math.cos(lat2*r)*Math.sin(dLon/2)**2;
  return 2*R*Math.asin(Math.sqrt(a));
}}
function pm25Color(v){{
  if(v==null)return '#9ca3af';
  if(v<=12) return '#2e7d32';
  if(v<=35) return '#f9a825';
  if(v<=55) return '#ef6c00';
  if(v<=150)return '#c62828';
  return '#6a1b9a';
}}
function lc(v){{return(v==null||v>12)?'#fff':'rgba(0,0,0,.7)';}}
function errColor(err,minE,maxE){{
  if(err==null)return '#f1f5f9';
  const t=Math.min(1,Math.max(0,(err-minE)/Math.max(maxE-minE,0.1)));
  let r,g,b;
  if(t<0.5){{const tt=t*2;r=Math.round(46+tt*(249-46));g=Math.round(125+tt*(168-125));b=Math.round(50-tt*50);}}
  else{{const tt=(t-0.5)*2;r=Math.round(249+tt*(198-249));g=Math.round(168-tt*168);b=0;}}
  return `rgb(${{r}},${{g}},${{b}})`;
}}
function pm25ToAqi(pm){{
  const bp=[[0,12,0,50],[12.1,35.4,51,100],[35.5,55.4,101,150],[55.5,150.4,151,200],[150.5,250.4,201,300],[250.5,500.4,301,500]];
  for(const[lo,hi,alo,ahi]of bp)if(pm>=lo&&pm<=hi)return Math.round((ahi-alo)/(hi-lo)*(pm-lo)+alo);
  return 500;
}}
function stepToDate(step){{
  const base=new Date(_TD.start);
  base.setHours(base.getHours()+step);
  return base;
}}
function mLabel(r,short){{
  const s={{self:'Self',mean:'Mean',idw:'IDW',corr:'Corr',ridge:'Ridge'}};
  const l={{self:'Self (own history)',mean:'Mean',idw:'IDW',corr:'Corr-Weighted',ridge:'Ridge Regression'}};
  const base=(short?s:l)[r.method];
  return r.method==='idw'?`${{base}}(p=${{r.p}})`:base;
}}

/* ══════════════════════════════════════════════════════
   IMPUTATION MATH
══════════════════════════════════════════════════════ */
function gaussJordan(A,sz){{
  const Mx=A.map(r=>[...r]);
  for(let c=0;c<sz;c++){{
    let pv=-1;for(let r=c;r<sz;r++)if(Math.abs(Mx[r][c])>1e-10){{pv=r;break;}}
    if(pv===-1)return null;[Mx[c],Mx[pv]]=[Mx[pv],Mx[c]];
    const sc=Mx[c][c];for(let j=c;j<=sz;j++)Mx[c][j]/=sc;
    for(let r=0;r<sz;r++){{if(r===c)continue;const f=Mx[r][c];for(let j=c;j<=sz;j++)Mx[r][j]-=f*Mx[c][j];}}
  }}
  return Mx.map(r=>r[sz]);
}}
function getNeighborsAtStep(target,k,step){{
  return stations
    .filter(s=>s.id!==target.id)
    .map(s=>{{const pm25=tsData[s.name]?tsData[s.name][step]:null;return {{s:{{...s,pm25}},d:haversine(target.lat,target.lon,s.lat,s.lon)}};}} )
    .filter(x=>x.s.pm25!=null)
    .sort((a,b)=>a.d-b.d)
    .slice(0,k);
}}
function imputeMean(nb){{
  const v=nb.map(x=>x.s.pm25).filter(x=>x!=null);
  return v.length?v.reduce((a,b)=>a+b,0)/v.length:null;
}}
function imputeIDW(nb,p){{
  let n=0,den=0;
  for(const x of nb){{if(x.s.pm25==null)continue;const w=1/Math.pow(x.d+0.01,p);n+=w*x.s.pm25;den+=w;}}
  return den>0?n/den:null;
}}
function imputeCorr(target,nb){{
  const ni=corrMat.stations,mx=corrMat.matrix,ti=ni.indexOf(target.name);
  if(ti===-1)return imputeIDW(nb,2);
  let n=0,den=0;
  for(const x of nb){{
    if(x.s.pm25==null)continue;
    const i=ni.indexOf(x.s.name);const w=i!==-1?Math.max(0,mx[ti][i]):0;
    n+=w*x.s.pm25;den+=w;
  }}
  return den>0?n/den:imputeMean(nb);
}}
function imputeRidge(target,nb,a=0.1){{
  const ni=corrMat.stations,mx=corrMat.matrix,K=nb.length;if(!K)return null;
  const ti=ni.indexOf(target.name);if(ti===-1)return imputeCorr(target,nb);
  const G=nb.map((_,i)=>nb.map((_,j)=>{{
    const ii=ni.indexOf(nb[i].s.name),jj=ni.indexOf(nb[j].s.name);
    return(ii!==-1&&jj!==-1)?mx[ii][jj]:(i===j?1:0);
  }}));
  const c=nb.map(x=>{{const i=ni.indexOf(x.s.name);return i!==-1?Math.max(0,mx[ti][i]):0;}});
  const Aug=G.map((row,i)=>[...row.map((v,j)=>v+(i===j?a:0)),c[i]]);
  const sol=gaussJordan(Aug,K);if(!sol)return imputeCorr(target,nb);
  const w=sol.map(v=>Math.max(0,v)),ws=w.reduce((a,b)=>a+b,0);
  if(!ws)return imputeMean(nb);
  return nb.reduce((s,x,i)=>s+(x.s.pm25!=null?(w[i]/ws)*x.s.pm25:0),0);
}}

/* ══════════════════════════════════════════════════════
   STATE
══════════════════════════════════════════════════════ */
let curStep    = N_TIME - 1;
let lbN        = 0;
let searchTarget   = null;
let searchResults  = [];
let searchStep     = -1;
let selectedCellKey= null;
let activeTab      = 'best';
let playInterval   = null;
let lbPlayInterval = null;
let tsChartObj     = null;

/* ══════════════════════════════════════════════════════
   LEAFLET MAP
══════════════════════════════════════════════════════ */
const map = L.map('map').setView([24.776, 121.008], 14);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{attribution:'© OpenStreetMap',maxZoom:19}}).addTo(map);
const mkLayer = L.layerGroup().addTo(map);

function renderMap(){{
  const lbStep = Math.max(0, curStep - lbN);
  const target = searchTarget;
  let bestN = null;
  const nbHighlight = new Set();
  if(searchResults.length && target && searchStep===curStep){{
    if(selectedCellKey){{
      const sel=searchResults.find(r=>cellKey(r)===selectedCellKey);
      bestN=sel&&sel.n===lbN?sel:getBestForN(lbN);
    }} else {{
      bestN=getBestForN(lbN);
    }}
    if(bestN&&bestN.method!=='self'&&bestN.m>0){{
      getNeighborsAtStep(target,bestN.m,lbStep).forEach(x=>nbHighlight.add(x.s.id));
    }}
  }}
  mkLayer.clearLayers();
  stations.forEach(s=>{{
    const isTarget = target&&s.id===target.id;
    const isNb     = nbHighlight.has(s.id);
    const displayStep = isTarget ? curStep : lbStep;
    const val  = tsData[s.name]?tsData[s.name][displayStep]:null;
    const color= pm25Color(val);
    const label= val!=null?Math.round(val):'—';
    let html;
    if(isTarget){{
      html=`<div class="mk target-mk" style="background:${{color}};color:${{lc(val)}}">${{label}}</div>`;
      if(bestN){{
        html+=`<div class="mk-tag">→ ${{bestN.predicted.toFixed(1)}}</div>`;
        html+=`<div class="mk-tag err">Δ${{bestN.error.toFixed(2)}}</div>`;
      }} else {{
        html+=`<div class="mk-tag" style="background:#475569">Target</div>`;
      }}
    }} else if(isNb){{
      html=`<div class="mk nb-mk" style="background:${{color}};color:${{lc(val)}}">${{label}}</div>`;
      if(lbN>0)html+=`<div class="mk-tag orange">${{lbN}}h ago</div>`;
    }} else {{
      html=`<div class="mk dim-mk" style="background:${{color}};color:${{lc(val)}}">${{label}}</div>`;
    }}
    const icon=L.divIcon({{className:'',iconSize:[34,34],iconAnchor:[17,17],html}});
    const mk=L.marker([s.lat,s.lon],{{icon}}).addTo(mkLayer);
    mk.bindPopup(`<div class="pt">${{esc(s.name)}} <small style="color:#5f6b7a">(${{esc(s.name_zh)}})</small></div>
      <div class="pg">
        <span>Zone: ${{esc(s.zone)}} · Location: ${{esc(s.location_id)}}</span>
        <span>PM2.5 now: <b>${{val!=null?val.toFixed(1):'N/A'}}</b> µg/m³ · AQI ${{val!=null?pm25ToAqi(val):'—'}}</b></span>
        <span>Coords: ${{s.lat.toFixed(4)}}, ${{s.lon.toFixed(4)}}</span>
      </div>`);
    if(isTarget)mk.openPopup();
    mk.on('click',()=>setSearchTarget(s));
  }});
}}

/* ══════════════════════════════════════════════════════
   TIME CONTROLS
══════════════════════════════════════════════════════ */
function applyStep(step){{
  curStep=Math.max(0,Math.min(N_TIME-1,step));
  document.getElementById('timeSlider').value=curStep;
  const d=stepToDate(curStep);
  document.getElementById('tLabel').textContent=d.toLocaleString('en-US',
    {{year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'}});
  updateTargetInfo();
  renderMap();
  updateZones();
}}

document.getElementById('prevBtn').onclick=()=>applyStep(curStep-1);
document.getElementById('nextBtn').onclick=()=>applyStep(curStep+1);
document.getElementById('timeSlider').oninput=e=>applyStep(+e.target.value);
document.querySelectorAll('.mbtn').forEach(b=>b.onclick=()=>{{
  document.querySelectorAll('.mbtn').forEach(x=>x.classList.remove('active'));
  b.classList.add('active'); applyStep(+b.dataset.step);
}});
document.getElementById('playBtn').onclick=()=>{{
  if(playInterval){{clearInterval(playInterval);playInterval=null;document.getElementById('playBtn').innerHTML='&#9654;';document.getElementById('playBtn').className='icon-btn playing';return;}}
  document.getElementById('playBtn').innerHTML='&#9646;&#9646;';document.getElementById('playBtn').className='icon-btn';
  playInterval=setInterval(()=>{{
    if(curStep>=N_TIME-1){{clearInterval(playInterval);playInterval=null;document.getElementById('playBtn').innerHTML='&#9654;';document.getElementById('playBtn').className='icon-btn playing';return;}}
    applyStep(curStep+1);
  }},+document.getElementById('speedSel').value);
}};

/* ══════════════════════════════════════════════════════
   LOOKBACK CONTROLS
══════════════════════════════════════════════════════ */
function applyLbN(n){{
  lbN=Math.max(0,Math.min(24,n));
  document.getElementById('lbSlider').value=lbN;
  document.getElementById('lbLabel').textContent=lbN===0?'n = 0 h (current)':`n = ${{lbN}} h ago`;
  highlightLbRow();
  renderMap();
}}
function highlightLbRow(){{
  document.querySelectorAll('.hm-rh').forEach(th=>{{
    const n=parseInt(th.dataset.n??'');th.classList.toggle('lb-active',n===lbN);
  }});
  document.querySelectorAll('.self-table tr[data-n]').forEach(tr=>tr.classList.toggle('lb-active',+tr.dataset.n===lbN));
}}

document.getElementById('lbSlider').oninput=e=>applyLbN(+e.target.value);
document.getElementById('lbPrevBtn').onclick=()=>applyLbN(lbN-1);
document.getElementById('lbNextBtn').onclick=()=>applyLbN(lbN+1);
document.getElementById('lbPlayBtn').onclick=()=>{{
  if(lbPlayInterval){{clearInterval(lbPlayInterval);lbPlayInterval=null;document.getElementById('lbPlayBtn').innerHTML='&#9654;';document.getElementById('lbPlayBtn').className='icon-btn playing-lb';return;}}
  document.getElementById('lbPlayBtn').innerHTML='&#9646;&#9646;';document.getElementById('lbPlayBtn').className='icon-btn';
  applyLbN(0);
  lbPlayInterval=setInterval(()=>{{
    if(lbN>=24){{clearInterval(lbPlayInterval);lbPlayInterval=null;document.getElementById('lbPlayBtn').innerHTML='&#9654;';document.getElementById('lbPlayBtn').className='icon-btn playing-lb';return;}}
    applyLbN(lbN+1);
  }},+document.getElementById('lbSpeedSel').value);
}};

/* ══════════════════════════════════════════════════════
   TARGET + SEARCH
══════════════════════════════════════════════════════ */
const targetSel = document.getElementById('targetSel');
stations.forEach(s=>{{
  const o=document.createElement('option');o.value=s.id;o.textContent=`${{s.name}} (${{s.name_zh}})`;targetSel.appendChild(o);
}});
targetSel.onchange=()=>{{
  const s=stations.find(x=>x.id===targetSel.value);if(s)setSearchTarget(s);
}};

function setSearchTarget(s){{
  searchTarget=s;
  targetSel.value=s.id;
  searchResults=[];selectedCellKey=null;
  updateTargetInfo();
  renderMap();
  drawTsChart(s.name);
  document.getElementById('tsWrap').classList.add('active');
  document.getElementById('tsTitle').textContent=`PM2.5 — ${{s.name}} (${{s.name_zh}})`;
  document.getElementById('bestBar').className='best-bar';
  document.getElementById('bestBar').innerHTML='<span class="bb-empty">Run Search to display the best combination</span>';
  document.getElementById('mcWrap').style.display='none';
  document.getElementById('hmOuter').innerHTML='<div class="hm-empty">Run &#9881; Search to display the heatmap<br><small>x: m (neighbors) · y: n (lookback h)</small></div>';
}}

function updateTargetInfo(){{
  if(!searchTarget)return;
  const v=tsData[searchTarget.name]?tsData[searchTarget.name][curStep]:null;
  document.getElementById('tiVal').textContent=v!=null?v.toFixed(1):'—';
  document.getElementById('tiTime').textContent=stepToDate(curStep).toLocaleString('en-US',{{hour:'2-digit',minute:'2-digit',month:'short',day:'numeric'}});
  document.getElementById('tiZone').textContent=searchTarget.zone+' · '+searchTarget.location_id;
}}

document.getElementById('searchBtn').onclick=runSearch;
function runSearch(){{
  if(!searchTarget)return;
  searchStep=curStep;selectedCellKey=null;lbN=0;
  document.getElementById('lbSlider').value=0;
  document.getElementById('lbLabel').textContent='n = 0 h (current)';
  const actual=tsData[searchTarget.name]?tsData[searchTarget.name][curStep]:null;
  if(actual==null){{
    renderBestBar(null,'Target station has no value at this time — pick another step');return;
  }}
  searchResults=[];
  for(let n=0;n<=24;n++){{
    const step=searchStep-n;if(step<0)continue;
    if(n>=1){{
      const sv=tsData[searchTarget.name][step];
      if(sv!=null)searchResults.push({{n,m:0,method:'self',p:null,
        predicted:Math.round(sv*100)/100,error:Math.round(Math.abs(actual-sv)*1000)/1000}});
    }}
    for(let m=1;m<=M;m++){{
      const nb=getNeighborsAtStep(searchTarget,m,step);if(!nb.length)continue;
      const vm=imputeMean(nb);
      if(vm!=null)searchResults.push({{n,m,method:'mean',p:null,
        predicted:Math.round(vm*100)/100,error:Math.round(Math.abs(actual-vm)*1000)/1000}});
      for(const p of IDW_P_VALS){{
        const vi=imputeIDW(nb,p);
        if(vi!=null)searchResults.push({{n,m,method:'idw',p,
          predicted:Math.round(vi*100)/100,error:Math.round(Math.abs(actual-vi)*1000)/1000}});
      }}
      const vc=imputeCorr(searchTarget,nb);
      if(vc!=null)searchResults.push({{n,m,method:'corr',p:null,
        predicted:Math.round(vc*100)/100,error:Math.round(Math.abs(actual-vc)*1000)/1000}});
      const vr=imputeRidge(searchTarget,nb);
      if(vr!=null)searchResults.push({{n,m,method:'ridge',p:null,
        predicted:Math.round(vr*100)/100,error:Math.round(Math.abs(actual-vr)*1000)/1000}});
    }}
  }}
  renderBestBar(actual);
  renderMethodCompare(actual);
  renderHeatmap(activeTab);
  const best=getBestOverall();
  if(best)applyLbN(best.n);else renderMap();
}}

/* ══════════════════════════════════════════════════════
   RESULT RENDERING
══════════════════════════════════════════════════════ */
function getBestOverall(){{return searchResults.length?searchResults.reduce((a,b)=>a.error<b.error?a:b):null;}}
function getBestForGroup(key){{const f=searchResults.filter(r=>r.method===key);return f.length?f.reduce((a,b)=>a.error<b.error?a:b):null;}}
function getBestForN(n){{const f=searchResults.filter(r=>r.n===n);return f.length?f.reduce((a,b)=>a.error<b.error?a:b):null;}}
function getBestForCell(n,m){{const f=searchResults.filter(r=>r.n===n&&r.m===m);return f.length?f.reduce((a,b)=>a.error<b.error?a:b):null;}}
function getBestForCellMethod(n,m,key){{const f=searchResults.filter(r=>r.n===n&&r.m===m&&r.method===key);return f.length?f.reduce((a,b)=>a.error<b.error?a:b):null;}}
function cellKey(r){{return `${{r.n}}_${{r.m}}_${{r.method}}_${{r.p}}`;}}

function renderBestBar(actual,errMsg){{
  const bar=document.getElementById('bestBar');
  if(errMsg){{bar.className='best-bar';bar.innerHTML=`<span class="bb-empty">⚠ ${{esc(errMsg)}}</span>`;return;}}
  if(!searchResults.length||actual==null){{bar.className='best-bar';bar.innerHTML='<span class="bb-empty">Run Search to display the best combination</span>';return;}}
  const best=getBestOverall();
  bar.className='best-bar found';
  const mStr=best.m>0?`K=${{best.m}}`:'—(self)';
  bar.innerHTML=
    `<span class="bb-trophy">🏆</span>`+
    `<span class="bb-method">${{mLabel(best,false)}}</span>`+
    `<span class="bb-dot">·</span>`+
    `<span>n=<strong>${{best.n}}</strong>h</span>`+
    `<span class="bb-dot">·</span>`+
    `<span>${{mStr}}</span>`+
    `<span class="bb-dot">·</span>`+
    `<span>True: ${{actual.toFixed(2)}}</span>`+
    `<span class="bb-dot">·</span>`+
    `<span>Imputed: <span class="bb-err">${{best.predicted.toFixed(2)}}</span></span>`+
    `<span class="bb-dot">·</span>`+
    `<span>Error: <span class="bb-err">${{best.error.toFixed(3)}} µg/m³</span></span>`;
}}

function renderMethodCompare(actual){{
  const groups=['self','mean','idw','corr','ridge'];
  const medals=['🥇','🥈','🥉','',''];
  const bests=groups.map(g=>getBestForGroup(g)).filter(Boolean);
  bests.sort((a,b)=>a.error-b.error);
  const best=getBestOverall();
  document.getElementById('mcBody').innerHTML=bests.map((x,i)=>{{
    const isB=best&&x.error===best.error&&x.method===best.method&&x.n===best.n&&x.m===best.m;
    const mStr=x.m>0?`K=${{x.m}}`:'—';
    return `<tr class="${{isB?'best-row':''}}">
      <td>${{medals[i]||''}} ${{mLabel(x,true)}}</td>
      <td>${{x.n}}h ago</td>
      <td>${{mStr}}</td>
      <td style="font-weight:700;color:var(--primary)">${{x.error.toFixed(3)}}</td></tr>`;
  }}).join('');
  document.getElementById('mcWrap').style.display='';
}}

/* ══════════════════════════════════════════════════════
   HEATMAP
══════════════════════════════════════════════════════ */
document.querySelectorAll('.tab-btn').forEach(b=>b.onclick=()=>renderHeatmap(b.dataset.tab));

function addCellClick(cell){{
  cell.addEventListener('click',()=>{{
    const n=+cell.dataset.n,m=+cell.dataset.m,method=cell.dataset.method;
    const p=cell.dataset.p?parseFloat(cell.dataset.p):null;
    const r=searchResults.find(x=>x.n===n&&x.m===m&&x.method===method&&x.p===p);
    if(!r)return;
    selectedCellKey=cellKey(r);
    document.querySelectorAll('.hm-cell').forEach(c=>{{
      const cr=searchResults.find(x=>x.n===+c.dataset.n&&x.m===+c.dataset.m&&
        x.method===c.dataset.method&&x.p===(c.dataset.p?parseFloat(c.dataset.p):null));
      c.classList.toggle('selected',cr?cellKey(cr)===selectedCellKey:false);
    }});
    applyLbN(r.n);
  }});
}}

function renderHeatmap(tab){{
  activeTab=tab;
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  const container=document.getElementById('hmOuter');
  if(!searchResults.length){{
    container.innerHTML='<div class="hm-empty">Run Search to display the heatmap<br><small>x: m (neighbors) · y: n (lookback h)</small></div>';return;
  }}
  const globalBest=getBestOverall();
  if(tab==='self'){{
    const filtered=searchResults.filter(r=>r.method==='self');
    if(!filtered.length){{container.innerHTML='<div class="hm-empty">No Self data (needs n≥1)</div>';return;}}
    const errors=filtered.map(r=>r.error),minE=Math.min(...errors),maxE=Math.max(...errors);
    let html='<table class="self-table"><thead><tr><th>Lookback n</th><th>Error (µg/m³)</th><th>Bar</th></tr></thead><tbody>';
    for(let n=1;n<=24;n++){{
      const r=filtered.find(x=>x.n===n);if(!r){{html+=`<tr data-n="${{n}}"><td>${{n}}h</td><td colspan="2" style="color:var(--muted)">no data</td></tr>`;continue;}}
      const bg=errColor(r.error,minE,maxE);
      const barW=Math.max(2,Math.round((r.error-minE)/Math.max(maxE-minE,.1)*130));
      const isG=globalBest&&r.method===globalBest.method&&r.n===globalBest.n;
      html+=`<tr data-n="${{n}}" class="${{r.n===lbN?'lb-active':''}}">
        <td>${{n}}h${{isG?' ★':''}}</td>
        <td style="background:${{bg}};text-align:center;padding:2px 5px;cursor:pointer"
          data-n="${{n}}" data-m="0" data-method="self" data-p="">${{r.error.toFixed(3)}}</td>
        <td><span class="self-bar" style="background:${{bg}};width:${{barW}}px"></span></td></tr>`;
    }}
    html+='</tbody></table>';container.innerHTML=html;
    container.querySelectorAll('td[data-n]').forEach(addCellClick);return;
  }}
  let getData;
  if(tab==='best')getData=(n,m)=>getBestForCell(n,m);
  else getData=(n,m)=>getBestForCellMethod(n,m,tab);
  const allR=[];
  for(let n=0;n<=24;n++)for(let m=1;m<=M;m++){{const r=getData(n,m);if(r)allR.push(r);}}
  if(!allR.length){{container.innerHTML='<div class="hm-empty">No data for this method</div>';return;}}
  const minE=Math.min(...allR.map(r=>r.error)),maxE=Math.max(...allR.map(r=>r.error));
  let html='<table class="hm-table"><thead><tr>';
  html+='<th class="hm-th" style="width:32px">n＼m</th>';
  for(let m=1;m<=M;m++)html+=`<th class="hm-th">${{m}}</th>`;
  html+='</tr></thead><tbody>';
  for(let n=0;n<=24;n++){{
    html+=`<tr><th class="hm-rh${{n===lbN?' lb-active':''}}" data-n="${{n}}">${{n}}h</th>`;
    for(let m=1;m<=M;m++){{
      const r=getData(n,m);
      if(!r){{html+='<td class="hm-na">—</td>';continue;}}
      const bg=errColor(r.error,minE,maxE);
      const isG=globalBest&&r.n===globalBest.n&&r.m===globalBest.m&&r.method===globalBest.method&&r.p===globalBest.p;
      const ck=cellKey(r);
      const pTag=r.method==='idw'?` p=${{r.p}}`:'';
      const mTag=tab==='best'?` [${{mLabel(r,true)}}]`:'';
      html+=`<td class="hm-cell${{selectedCellKey===ck?' selected':''}}${{isG?' global-best':''}}"
        style="background:${{bg}}"
        title="n=${{n}}h, m=${{m}}${{mTag}}${{pTag}}&#10;Error: ${{r.error.toFixed(3)}} µg/m³&#10;Imputed: ${{r.predicted.toFixed(2)}}"
        data-n="${{n}}" data-m="${{m}}" data-method="${{r.method}}" data-p="${{r.p??''}}">${{r.error.toFixed(1)}}</td>`;
    }}
    html+='</tr>';
  }}
  html+='</tbody></table>';
  container.innerHTML=html;
  container.querySelectorAll('.hm-cell').forEach(addCellClick);
  container.querySelectorAll('.hm-rh').forEach(th=>th.onclick=()=>applyLbN(+th.dataset.n));
}}

/* ══════════════════════════════════════════════════════
   TS CHART
══════════════════════════════════════════════════════ */
function drawTsChart(name){{
  const vals=tsData[name];
  const step=Math.max(1,Math.floor(N_TIME/180));
  const labels=[],data=[];
  for(let i=0;i<N_TIME;i+=step){{
    const d=stepToDate(i);
    labels.push(`${{d.getMonth()+1}}/${{d.getDate()}} ${{d.getHours()}}h`);
    data.push(vals[i]);
  }}
  if(tsChartObj)tsChartObj.destroy();
  tsChartObj=new Chart(document.getElementById('tsChart'),{{
    type:'line',
    data:{{labels,datasets:[{{label:name,data,borderColor:'#1e66d0',backgroundColor:'rgba(30,102,208,.08)',
      borderWidth:1.5,pointRadius:0,fill:true,tension:0.3}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}}}},
      scales:{{x:{{display:false}},y:{{title:{{display:true,text:'µg/m³',font:{{size:9}}}},ticks:{{font:{{size:9}}}}}}}}
    }}
  }});
}}

/* ══════════════════════════════════════════════════════
   ZONES
══════════════════════════════════════════════════════ */
function updateZones(){{
  const zones={{}};
  stations.forEach(s=>{{
    const z=s.zone;if(!zones[z])zones[z]={{sum:0,count:0,stations:[]}};
    const v=tsData[s.name]?tsData[s.name][curStep]:null;
    if(v!=null){{zones[z].sum+=v;zones[z].count++;}}
    zones[z].stations.push(s);
  }});
  const el=document.getElementById('zoneTable');el.innerHTML='';
  Object.keys(zones).sort().forEach(z=>{{
    const d=zones[z];const avg=d.count>0?(d.sum/d.count):null;const color=pm25Color(avg);
    const block=document.createElement('div');block.className='zone-block';
    block.innerHTML=`<div class="zone-hdr" style="background:${{color}}">
      <span style="font-weight:800;font-size:13px">${{z}}</span>
      <span style="flex:1;font-size:11px">${{d.count}} stations</span>
      <span style="font-size:16px;font-weight:900">${{avg!=null?avg.toFixed(1):'—'}}</span>
      <span style="font-size:10px;margin-left:2px">µg/m³</span></div>
    <div class="zone-body">${{d.stations.map(s=>{{
      const v=tsData[s.name]?tsData[s.name][curStep]:null;
      return `<div class="zone-row">
        <span style="width:8px;height:8px;border-radius:50%;background:${{pm25Color(v)}};display:inline-block;flex-shrink:0"></span>
        <span style="font-weight:600;flex:1">${{s.name}}</span>
        <span style="color:var(--muted)">${{s.name_zh}}</span>
        <span style="font-weight:700;color:${{pm25Color(v)}};min-width:36px;text-align:right">${{v!=null?v.toFixed(1):'—'}}</span>
      </div>`;
    }}).join('')}}</div>`;
    block.querySelector('.zone-hdr').onclick=()=>map.flyTo([d.stations[0].lat,d.stations[0].lon],15);
    el.appendChild(block);
  }});
}}

/* ══════════════════════════════════════════════════════
   ENERGY CHARTS
══════════════════════════════════════════════════════ */
function buildEnergyCharts(){{
  const monthly=_ED.monthly;
  const labels=monthly.map(m=>m.label);
  const cons=monthly.map(m=>m.consumption_gwh);
  const sav=monthly.map(m=>m.savings_gwh);
  const co2=monthly.map(m=>m.co2_reduction_kt);

  document.getElementById('kpiCons').textContent=_ED.summary.total_consumption_gwh.toLocaleString();
  document.getElementById('kpiSav').textContent =_ED.summary.total_savings_gwh.toLocaleString();
  document.getElementById('kpiPct').textContent =_ED.summary.avg_savings_pct+'%';
  document.getElementById('kpiCO2').textContent =monthly.reduce((s,m)=>s+m.co2_reduction_kt,0).toFixed(0);

  new Chart(document.getElementById('consChart'),{{
    type:'bar',
    data:{{labels,datasets:[
      {{label:'Consumption (GWh)',data:cons,backgroundColor:'rgba(21,101,192,.75)',borderWidth:0}},
      {{label:'Savings (GWh)',data:sav,backgroundColor:'rgba(0,121,107,.75)',borderWidth:0}}
    ]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{position:'bottom',labels:{{font:{{size:9}},boxWidth:10}}}},
        tooltip:{{callbacks:{{label:ctx=>`${{ctx.dataset.label}}: ${{ctx.parsed.y}} GWh`}}}}}},
      scales:{{x:{{ticks:{{font:{{size:8}},maxRotation:45}}}},
        y:{{title:{{display:true,text:'GWh',font:{{size:9}}}},ticks:{{font:{{size:9}}}}}}}}
    }}
  }});

  new Chart(document.getElementById('savChart'),{{
    type:'bar',
    data:{{labels,datasets:[
      {{label:'Energy Saved (GWh)',data:sav,backgroundColor:'rgba(0,121,107,.75)',borderWidth:0,yAxisID:'y'}},
      {{label:'CO₂ Reduction (kt)',data:co2,type:'line',borderColor:'#c62828',
        backgroundColor:'rgba(198,40,40,.08)',borderWidth:2,pointRadius:3,fill:false,yAxisID:'y2'}}
    ]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{position:'bottom',labels:{{font:{{size:9}},boxWidth:10}}}},
        tooltip:{{callbacks:{{label:ctx=>ctx.dataset.label+': '+ctx.parsed.y+(ctx.dataset.yAxisID==='y2'?' kt':' GWh')}}}}}},
      scales:{{
        x:{{ticks:{{font:{{size:8}},maxRotation:45}}}},
        y:{{position:'left',title:{{display:true,text:'GWh',font:{{size:9}}}},ticks:{{font:{{size:9}}}}}},
        y2:{{position:'right',title:{{display:true,text:'k-tonnes CO₂',font:{{size:9}}}},ticks:{{font:{{size:9}}}},grid:{{drawOnChartArea:false}}}}
      }}
    }}
  }});
}}
buildEnergyCharts();

/* ══════════════════════════════════════════════════════
   TABS
══════════════════════════════════════════════════════ */
document.querySelectorAll('.sb-tab').forEach(btn=>btn.onclick=()=>{{
  document.querySelectorAll('.sb-tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.sb-pane').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('pane-'+btn.dataset.pane).classList.add('active');
}});

/* ══════════════════════════════════════════════════════
   INIT
══════════════════════════════════════════════════════ */
applyStep(curStep);
updateZones();
setSearchTarget(stations[0]);
</script>
</body>
</html>
"""

OUT.write_text(HTML, encoding="utf-8")
print(f"Written → {OUT}  ({OUT.stat().st_size // 1024} KB)")
