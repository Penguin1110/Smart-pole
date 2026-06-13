"""
build_scipark_optimizer.py — 產生 work/pm25_optimizer_scipark.html

執行順序：
  1. python generate_scipark_json.py   # 產生 data/scipark/*.json
  2. python build_scipark_optimizer.py # 產生 HTML（本檔）

特色：
  - 10 根 HSIP 智慧桿 PM2.5 (Leaflet + 補值控制)
  - 月用電量 / 節電量圖表 (Chart.js)
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

M = len(json.loads(SJ)) - 1   # max K

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
  --green:#2e7d32;--yellow:#f9a825;--orange:#ef6c00;
  --red:#c62828;--primary:#1e66d0;--energy:#00796b;
  --savings:#1565c0;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%;font-family:Inter,system-ui,sans-serif;color:var(--text);background:var(--bg)}}
body{{display:flex;flex-direction:column;padding:10px;gap:8px}}

/* ── header ── */
.hdr{{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  box-shadow:var(--sh);padding:10px 16px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
.hdr-logo{{font-size:22px}}
.hdr-title{{font-size:16px;font-weight:800;flex:1}}
.hdr-sub{{font-size:11px;color:var(--muted);flex-basis:100%;margin-top:1px}}
.badge{{padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;color:#fff;
  background:var(--primary);white-space:nowrap}}
.badge.energy{{background:var(--energy)}}

/* ── time bar ── */
.tbar{{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  box-shadow:var(--sh);padding:8px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.tbar-label{{font-size:13px;font-weight:700;min-width:150px}}
.tbar-sub{{font-size:10px;color:var(--muted)}}
.icon-btn{{width:28px;height:28px;border:1px solid var(--border);border-radius:6px;
  background:#fff;cursor:pointer;font-size:12px;display:grid;place-items:center}}
.icon-btn.play{{background:var(--primary);border-color:var(--primary);color:#fff}}
#timeSlider{{flex:1;min-width:180px;accent-color:var(--primary)}}
.speed-sel{{height:28px;border:1px solid var(--border);border-radius:6px;padding:0 6px;
  font:inherit;font-size:11px;background:#fff;color:var(--text)}}

/* ── month jump ── */
.mjump{{display:flex;gap:4px;align-items:center;font-size:11px;color:var(--muted)}}
.mbtn{{padding:2px 8px;border:1px solid var(--border);border-radius:5px;background:#fff;
  font:inherit;font-size:11px;cursor:pointer;transition:all .15s}}
.mbtn:hover,.mbtn.active{{background:var(--primary);border-color:var(--primary);color:#fff}}

/* ── main grid ── */
.app{{flex:1;display:grid;grid-template-columns:1fr 400px;gap:8px;min-height:0}}
.panel{{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  box-shadow:var(--sh);overflow:hidden;display:flex;flex-direction:column}}

/* ── map ── */
#map{{flex:1;min-height:420px;background:#dbeafe}}

/* ── sidebar ── */
.sb{{display:flex;flex-direction:column;min-height:0}}
.sb-tabs{{display:flex;border-bottom:1px solid var(--border);background:#f8fbff;flex-shrink:0}}
.sb-tab{{flex:1;padding:8px 4px;border:none;background:transparent;cursor:pointer;
  font:inherit;font-size:11px;font-weight:600;color:var(--muted);transition:all .15s;
  border-bottom:2px solid transparent}}
.sb-tab.active{{color:var(--primary);border-bottom-color:var(--primary);background:#fff}}
.sb-pane{{flex:1;overflow-y:auto;padding:10px 12px;display:none;flex-direction:column;gap:10px}}
.sb-pane.active{{display:flex}}

/* ── PM2.5 controls ── */
.ctrl-title{{font-size:12px;font-weight:700}}
.ctrl-sub{{font-size:10px;color:var(--muted)}}
.field label{{font-size:11px;color:var(--muted);display:block;margin-bottom:3px;font-weight:500}}
.field select{{width:100%;height:30px;border-radius:7px;border:1px solid var(--border);
  padding:0 8px;font:inherit;font-size:11px;color:var(--text);background:#fff}}
.row2{{display:grid;grid-template-columns:1fr auto;gap:6px;align-items:end}}
.btn{{height:30px;border:1px solid var(--border);border-radius:7px;padding:0 12px;
  background:#fff;color:var(--text);font:inherit;font-size:11px;cursor:pointer;
  transition:all .2s;white-space:nowrap}}
.btn.primary{{background:var(--primary);border-color:var(--primary);color:#fff}}
.btn.primary:hover{{background:#1557b8}}
.info-pill{{background:#f0f4f8;border-radius:6px;padding:5px 9px;font-size:11px;display:flex;gap:10px;flex-wrap:wrap}}
.info-pill b{{color:var(--text)}}

/* ── station list ── */
.slist{{display:flex;flex-direction:column;gap:4px}}
.srow{{display:flex;align-items:center;gap:7px;padding:5px 7px;border-radius:7px;
  border:1px solid transparent;cursor:pointer;transition:all .15s}}
.srow:hover{{background:#f0f4f8;border-color:var(--border)}}
.srow.active{{background:#eff6ff;border-color:var(--primary)}}
.srow-dot{{width:12px;height:12px;border-radius:50%;flex-shrink:0}}
.srow-name{{font-size:11px;font-weight:700;flex:1}}
.srow-sub{{font-size:10px;color:var(--muted)}}
.srow-val{{font-size:12px;font-weight:800;text-align:right}}

/* ── result cards ── */
.result-card{{background:#f8fbff;border:1px solid var(--border);border-radius:8px;
  padding:8px 10px;font-size:11px}}
.rc-title{{font-size:10px;color:var(--muted);font-weight:600;margin-bottom:4px}}
.rc-val{{font-size:20px;font-weight:800;color:var(--primary)}}
.rc-unit{{font-size:11px;color:var(--muted)}}

/* ── KPI grid ── */
.kpi-grid{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}
.kpi{{background:#f8fbff;border:1px solid var(--border);border-radius:8px;padding:8px 10px}}
.kpi.green{{background:#f1f8e9;border-color:#a5d6a7}}
.kpi.blue{{background:#e3f2fd;border-color:#90caf9}}
.kpi-label{{font-size:10px;color:var(--muted);font-weight:600;margin-bottom:3px}}
.kpi-val{{font-size:18px;font-weight:800}}
.kpi-sub{{font-size:10px;color:var(--muted);margin-top:1px}}

/* ── chart wrappers ── */
.chart-wrap{{background:#f8fbff;border:1px solid var(--border);border-radius:8px;padding:8px 10px}}
.chart-title{{font-size:11px;font-weight:700;margin-bottom:6px}}
.chart-sub{{font-size:10px;color:var(--muted);margin-bottom:8px}}
canvas{{max-height:180px}}

/* ── map markers ── */
.mk{{width:32px;height:32px;border-radius:50%;border:2px solid rgba(255,255,255,.95);
  box-shadow:0 2px 8px rgba(0,0,0,.2);display:grid;place-items:center;
  color:#fff;font-size:10px;font-weight:800;transform:translate(-50%,-50%);cursor:pointer;
  transition:transform .2s}}
.mk:hover{{transform:translate(-50%,-50%) scale(1.2)}}
.mk.target{{border:3px solid var(--primary);box-shadow:0 0 0 4px rgba(30,102,208,.25),0 2px 8px rgba(0,0,0,.2)}}
.mk.neighbor{{border:2px solid var(--orange)}}
.mk-tag{{position:absolute;top:36px;left:50%;transform:translateX(-50%);
  background:var(--primary);color:#fff;font-size:8px;font-weight:700;
  padding:2px 5px;border-radius:4px;white-space:nowrap;pointer-events:none;line-height:1.4}}
.mk-tag.orange{{background:var(--orange)}}

/* ── legend ── */
.legend{{padding:7px 12px;display:flex;flex-wrap:wrap;gap:5px;border-top:1px solid var(--border);
  flex-shrink:0;font-size:10px}}
.li{{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border:1px solid var(--border);
  border-radius:999px;color:var(--muted);background:#fff}}
.sw{{width:8px;height:8px;border-radius:50%;display:inline-block}}
.err-grad{{width:70px;height:7px;border-radius:4px;
  background:linear-gradient(90deg,#2e7d32,#f9a825,#c62828)}}

/* ── bottom chart ── */
.bottom-chart{{padding:8px 14px;border-top:1px solid var(--border);flex-shrink:0;
  display:none;flex-direction:column;gap:4px}}
.bottom-chart.active{{display:flex}}
.bc-title{{font-size:11px;font-weight:700}}
canvas#tsChart{{max-height:100px}}

@media(max-width:1000px){{.app{{grid-template-columns:1fr}}#map{{min-height:360px}}}}
</style>
</head>
<body>

<!-- ─── Embedded JSON ─────────────────────────────────────────── -->
<script>
const _SD={SJ};
const _CD={CJ};
const _TD={TJ};
const _ED={EJ};
const M={M};
</script>

<!-- ─── Header ───────────────────────────────────────────────── -->
<header class="hdr">
  <span class="hdr-logo">🏭</span>
  <div style="flex:1">
    <div class="hdr-title">Hsinchu Science Industrial Park — Smart Pole Dashboard</div>
    <div class="hdr-sub">
      IoT PM2.5 Monitoring · 10 Representative Stations · 新竹科學工業園區
      &nbsp;·&nbsp; Electricity &amp; Energy Savings: SIPA Annual Report 2025–2026
    </div>
  </div>
  <span class="badge">PM2.5</span>
  <span class="badge energy">Energy</span>
</header>

<!-- ─── Time bar ─────────────────────────────────────────────── -->
<div class="tbar">
  <div>
    <div class="tbar-label" id="tLabel">—</div>
    <div class="tbar-sub" id="tSub">—</div>
  </div>
  <div class="mjump">Jump: <button class="mbtn" data-step="0">Dec</button>
    <button class="mbtn" data-step="744">Jan</button>
    <button class="mbtn" data-step="1488">Feb</button></div>
  <button class="icon-btn" id="prevBtn">&#9664;</button>
  <button class="icon-btn play" id="playBtn">&#9654;</button>
  <button class="icon-btn" id="nextBtn">&#9654;&#9654;</button>
  <input type="range" id="timeSlider" min="0" max="2159" value="2159" step="1" style="flex:1;min-width:160px"/>
  <select class="speed-sel" id="speedSel">
    <option value="500">Slow</option>
    <option value="200" selected>Normal</option>
    <option value="80">Fast</option>
    <option value="30">Very fast</option>
  </select>
</div>

<!-- ─── Main layout ──────────────────────────────────────────── -->
<div class="app">

  <!-- ── Map panel ── -->
  <section class="panel">
    <div id="map"></div>
    <div class="bottom-chart" id="tsPanel">
      <div class="bc-title" id="tsTitle">PM2.5 Time Series — </div>
      <canvas id="tsChart"></canvas>
    </div>
    <div class="legend">
      <span style="font-size:10px;color:var(--muted)">AQI:</span>
      <span class="li"><span class="sw" style="background:#2e7d32"></span>Good</span>
      <span class="li"><span class="sw" style="background:#f9a825"></span>Moderate</span>
      <span class="li"><span class="sw" style="background:#ef6c00"></span>USG</span>
      <span class="li"><span class="sw" style="background:#c62828"></span>Unhealthy</span>
      <span style="margin-left:8px;display:flex;align-items:center;gap:5px;color:var(--muted);font-size:10px">
        Imputation error: <span class="err-grad"></span> Low → High
      </span>
    </div>
  </section>

  <!-- ── Sidebar ── -->
  <aside class="panel sb">
    <div class="sb-tabs">
      <button class="sb-tab active" data-pane="pm25">PM2.5 Imputation</button>
      <button class="sb-tab" data-pane="energy">⚡ Energy</button>
      <button class="sb-tab" data-pane="zones">Zones</button>
    </div>

    <!-- PM2.5 pane -->
    <div class="sb-pane active" id="pane-pm25">
      <div>
        <div class="ctrl-title">Imputation: K-NN Weighted Average</div>
        <div class="ctrl-sub">Select target station → set K → choose weighting method → Impute</div>
      </div>
      <div class="row2">
        <div class="field">
          <label for="targetSel">Target (treated as missing)</label>
          <select id="targetSel"></select>
        </div>
        <button class="btn primary" id="imputeBtn">&#9881; Impute</button>
      </div>
      <div class="field" style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
        <div>
          <label for="kSel">K (neighbors)</label>
          <select id="kSel"></select>
        </div>
        <div>
          <label for="methodSel">Weighting</label>
          <select id="methodSel">
            <option value="mean">Mean</option>
            <option value="idw" selected>IDW (p=2)</option>
            <option value="corr">Correlation</option>
            <option value="ridge">Ridge</option>
          </select>
        </div>
      </div>
      <div class="info-pill" id="infoPill">
        <span>Target: <b id="iTarget">—</b></span>
        <span>True: <b id="iTrue">—</b> µg/m³</span>
        <span>Imputed: <b id="iImputed">—</b> µg/m³</span>
        <span>MAE: <b id="iMAE">—</b></span>
      </div>
      <div class="result-card" id="resultCard" style="display:none">
        <div class="rc-title">Imputed Value (K=<span id="rcK">—</span>, <span id="rcMethod">—</span>)</div>
        <span class="rc-val" id="rcVal">—</span> <span class="rc-unit">µg/m³</span>
        &nbsp;·&nbsp; Error: <b id="rcErr">—</b> µg/m³
      </div>

      <!-- Station list -->
      <div style="font-size:10px;color:var(--muted);font-weight:600;margin-top:4px">ALL STATIONS</div>
      <div class="slist" id="stationList"></div>
    </div>

    <!-- Energy pane -->
    <div class="sb-pane" id="pane-energy">
      <div>
        <div class="ctrl-title">Park-Wide Electricity · SIPA Data</div>
        <div class="ctrl-sub" style="font-size:10px;color:var(--muted)">
          全園月用電量 (GWh) · 科學工業園區管理局年報 · 2025–2026
        </div>
      </div>

      <!-- KPI row -->
      <div class="kpi-grid">
        <div class="kpi blue">
          <div class="kpi-label">Total Consumption (period)</div>
          <div class="kpi-val" id="kpiTotalCons">—</div>
          <div class="kpi-sub">GWh</div>
        </div>
        <div class="kpi green">
          <div class="kpi-label">Total Energy Saved</div>
          <div class="kpi-val" id="kpiTotalSav">—</div>
          <div class="kpi-sub">GWh</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Avg Monthly Savings</div>
          <div class="kpi-val" id="kpiAvgPct">—</div>
          <div class="kpi-sub">% vs baseline</div>
        </div>
        <div class="kpi green">
          <div class="kpi-label">CO₂ Reduction</div>
          <div class="kpi-val" id="kpiCO2">—</div>
          <div class="kpi-sub">k-tonnes</div>
        </div>
      </div>

      <!-- Monthly consumption chart -->
      <div class="chart-wrap">
        <div class="chart-title">Monthly Electricity Consumption</div>
        <div class="chart-sub">GWh · 2025/01–2026/02</div>
        <canvas id="consChart"></canvas>
      </div>

      <!-- Savings chart -->
      <div class="chart-wrap">
        <div class="chart-title">Monthly Energy Savings (節電量)</div>
        <div class="chart-sub">GWh saved vs baseline · emission factor 0.509 kgCO₂/kWh</div>
        <canvas id="savChart"></canvas>
      </div>
    </div>

    <!-- Zones pane -->
    <div class="sb-pane" id="pane-zones">
      <div>
        <div class="ctrl-title">PM2.5 by Zone (current timestamp)</div>
        <div class="ctrl-sub">Click a zone row to highlight stations on map</div>
      </div>
      <div id="zoneTable"></div>
      <div style="font-size:10px;color:var(--muted);line-height:1.6;margin-top:4px">
        Data: MOENV IoT smart poles (AQ1001 sensors), base time-series from 新竹 EPA station
        + spatial variation (bias ±2 µg/m³, σ=1.5). Electricity: SIPA Annual Report.
      </div>
    </div>

  </aside>
</div>

<script>
/* ════════════════════════════════════════════════════════════════
   DATA
════════════════════════════════════════════════════════════════ */
const SD = _SD;      // stations
const CD = _CD;      // correlations
const TD = _TD;      // timeseries
const ED = _ED;      // electricity

const N_TIME = TD.n;
const NAMES  = TD.stations;
const CORR_M = CD.matrix;
const CORR_N = CD.stations;

/* ════════════════════════════════════════════════════════════════
   UTILS
════════════════════════════════════════════════════════════════ */
function haversine(a, b) {{
  const R = 6371000, r = Math.PI/180;
  const dLat = (b.lat - a.lat)*r, dLon = (b.lon - a.lon)*r;
  const s = Math.sin(dLat/2)**2 + Math.cos(a.lat*r)*Math.cos(b.lat*r)*Math.sin(dLon/2)**2;
  return 2*R*Math.asin(Math.sqrt(s));
}}

function pm25Color(v) {{
  if (v == null) return '#aaa';
  if (v <= 12)  return '#2e7d32';
  if (v <= 35)  return '#f9a825';
  if (v <= 55)  return '#ef6c00';
  if (v <= 150) return '#c62828';
  return '#6a1b9a';
}}

function errColor(e) {{
  if (e == null) return '#aaa';
  const t = Math.min(e / 10, 1);
  const r = Math.round(46 + 192*t), g = Math.round(125*(1-t));
  return `rgb(${{r}},${{g}},50)`;
}}

function getVal(name, step) {{
  const arr = TD.data[name];
  return (arr && arr[step] != null) ? arr[step] : null;
}}

function corrBetween(a, b) {{
  const ia = CORR_N.indexOf(a), ib = CORR_N.indexOf(b);
  if (ia < 0 || ib < 0) return 0;
  return CORR_M[ia][ib];
}}

function timestampAt(step) {{
  const base = new Date(TD.start);
  base.setHours(base.getHours() + step);
  return base;
}}

/* ════════════════════════════════════════════════════════════════
   TIME SLIDER
════════════════════════════════════════════════════════════════ */
let curStep = N_TIME - 1;
let playInterval = null;

const slider   = document.getElementById('timeSlider');
const tLabel   = document.getElementById('tLabel');
const tSub     = document.getElementById('tSub');
const playBtn  = document.getElementById('playBtn');
const speedSel = document.getElementById('speedSel');

slider.max = N_TIME - 1;
slider.value = curStep;

function updateTime() {{
  const ts = timestampAt(curStep);
  const opts = {{year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'}};
  tLabel.textContent = ts.toLocaleString('en-US', opts);
  tSub.textContent   = `Step ${{curStep+1}} / ${{N_TIME}} · Hsinchu Science Industrial Park`;
  slider.value = curStep;
  updateMap();
  updateStationList();
  updateZones();
}}

document.getElementById('prevBtn').onclick = () => {{ if(curStep>0){{curStep--;updateTime();}} }};
document.getElementById('nextBtn').onclick = () => {{ if(curStep<N_TIME-1){{curStep++;updateTime();}} }};
document.querySelectorAll('.mbtn').forEach(b => b.onclick = () => {{
  curStep = +b.dataset.step; updateTime();
}});
slider.oninput = () => {{ curStep = +slider.value; updateTime(); }};
playBtn.onclick = () => {{
  if (playInterval) {{ clearInterval(playInterval); playInterval=null; playBtn.innerHTML='&#9654;'; playBtn.className='icon-btn play'; return; }}
  playBtn.innerHTML='&#9646;&#9646;'; playBtn.className='icon-btn';
  playInterval = setInterval(() => {{
    if (curStep >= N_TIME-1) {{ clearInterval(playInterval); playInterval=null; playBtn.innerHTML='&#9654;'; playBtn.className='icon-btn play'; return; }}
    curStep++; updateTime();
  }}, +speedSel.value);
}};

/* ════════════════════════════════════════════════════════════════
   LEAFLET MAP
════════════════════════════════════════════════════════════════ */
const map = L.map('map').setView([24.776, 121.008], 14);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{attribution:'© OpenStreetMap', maxZoom:19}}).addTo(map);

const markerMap = {{}};   // name → L.marker
let selectedStation = null;
let neighborNames   = [];

function makeIcon(name, step) {{
  const val = getVal(name, step);
  const color = pm25Color(val);
  const label = val != null ? val.toFixed(0) : '?';
  const isTarget = name === selectedStation;
  const isNeighbor = neighborNames.includes(name);
  let cls = 'mk';
  if (isTarget)   cls += ' target';
  if (isNeighbor) cls += ' neighbor';
  const tagHtml = isTarget
    ? `<div class="mk-tag">TARGET</div>`
    : isNeighbor
      ? `<div class="mk-tag orange">K-NN</div>`
      : '';
  return L.divIcon({{
    html: `<div class="mk ${{isTarget?'target':isNeighbor?'neighbor':''}}" style="background:${{color}}">${{label}}${{tagHtml}}</div>`,
    className: '', iconSize:[32,32]
  }});
}}

SD.forEach(s => {{
  const m = L.marker([s.lat, s.lon], {{icon: makeIcon(s.name, curStep)}}).addTo(map);
  m.bindPopup('');
  m.on('click', () => selectStation(s.name));
  markerMap[s.name] = m;
}});

function updateMap() {{
  SD.forEach(s => {{
    const m = markerMap[s.name];
    m.setIcon(makeIcon(s.name, curStep));
    const val = getVal(s.name, curStep);
    m.getPopup().setContent(`
      <div class="pt">${{s.name}} <span style="font-size:11px;color:#5f6b7a">(${{s.name_zh}})</span></div>
      <div class="pg">
        <span>Zone: ${{s.zone}}</span>
        <span>Location ID: ${{s.location_id}}</span>
        <span>PM2.5: <b>${{val!=null?val.toFixed(1):'N/A'}}</b> µg/m³</span>
        <span>AQI: <b>${{val!=null?pm25ToAqi(val):'—'}}</b></span>
      </div>
    `);
  }});
}}

function pm25ToAqi(pm) {{
  const bp = [[0,12,0,50],[12.1,35.4,51,100],[35.5,55.4,101,150],[55.5,150.4,151,200],[150.5,250.4,201,300],[250.5,500.4,301,500]];
  for (const [lo,hi,alo,ahi] of bp) {{
    if (pm>=lo && pm<=hi) return Math.round((ahi-alo)/(hi-lo)*(pm-lo)+alo);
  }}
  return 500;
}}

/* ════════════════════════════════════════════════════════════════
   STATION SELECTION + TIME SERIES CHART
════════════════════════════════════════════════════════════════ */
let tsChartObj = null;

function selectStation(name) {{
  selectedStation = name;
  neighborNames = [];
  document.getElementById('targetSel').value = name;
  // show time series
  document.getElementById('tsPanel').classList.add('active');
  document.getElementById('tsTitle').textContent = `PM2.5 Time Series — ${{name}}`;
  drawTsChart(name);
  updateMap();
  updateStationList();
}}

function drawTsChart(name) {{
  const vals = TD.data[name];
  const labels = [];
  const data   = [];
  const step   = Math.max(1, Math.floor(N_TIME/200)); // max 200 pts
  for (let i=0; i<N_TIME; i+=step) {{
    const ts = timestampAt(i);
    labels.push(`${{ts.getMonth()+1}}/${{ts.getDate()}} ${{ts.getHours()}}h`);
    data.push(vals[i]);
  }}
  if (tsChartObj) tsChartObj.destroy();
  tsChartObj = new Chart(document.getElementById('tsChart'), {{
    type: 'line',
    data: {{
      labels,
      datasets: [{{
        label: name,
        data,
        borderColor: '#1e66d0',
        backgroundColor: 'rgba(30,102,208,.08)',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins:{{legend:{{display:false}}}},
      scales:{{
        x:{{display:false}},
        y:{{title:{{display:true,text:'µg/m³',font:{{size:9}}}},ticks:{{font:{{size:9}}}}}}
      }}
    }}
  }});
}}

/* ════════════════════════════════════════════════════════════════
   STATION LIST (sidebar PM2.5 pane)
════════════════════════════════════════════════════════════════ */
const targetSel = document.getElementById('targetSel');
const kSel      = document.getElementById('kSel');

// Populate target dropdown
NAMES.forEach(n => {{
  const opt = document.createElement('option');
  opt.value = opt.textContent = n;
  targetSel.appendChild(opt);
}});

// Populate K dropdown
for (let k=1; k<=M; k++) {{
  const opt = document.createElement('option');
  opt.value = k; opt.textContent = `K = ${{k}}`;
  if (k===3) opt.selected = true;
  kSel.appendChild(opt);
}};

function updateStationList() {{
  const el = document.getElementById('stationList');
  el.innerHTML = '';
  SD.forEach(s => {{
    const val = getVal(s.name, curStep);
    const color = pm25Color(val);
    const isActive = s.name === selectedStation;
    const row = document.createElement('div');
    row.className = 'srow' + (isActive?' active':'');
    row.innerHTML = `
      <span class="srow-dot" style="background:${{color}}"></span>
      <span class="srow-name">${{s.name}}</span>
      <span class="srow-sub">${{s.name_zh}} · ${{s.zone}}</span>
      <span class="srow-val" style="color:${{color}}">${{val!=null?val.toFixed(1):'—'}}</span>
    `;
    row.onclick = () => selectStation(s.name);
    el.appendChild(row);
  }});
}}

/* ════════════════════════════════════════════════════════════════
   IMPUTATION (K-NN weighted)
════════════════════════════════════════════════════════════════ */
document.getElementById('imputeBtn').onclick = runImputation;

function runImputation() {{
  const target = targetSel.value;
  const K      = +kSel.value;
  const method = document.getElementById('methodSel').value;
  if (!target) return;

  selectedStation = target;
  const trueVal = getVal(target, curStep);

  // Get K nearest neighbors by correlation
  const others = SD.filter(s => s.name !== target);
  const ranked = others.map(s => {{
    const dist  = haversine(SD.find(x=>x.name===target), s);
    const corr  = corrBetween(target, s.name);
    return {{...s, dist, corr, val: getVal(s.name, curStep)}};
  }});

  // Sort by correlation desc (primary), distance asc (secondary)
  ranked.sort((a,b) => b.corr - a.corr);
  const neighbors = ranked.slice(0, K).filter(s => s.val != null);
  neighborNames = neighbors.map(s => s.name);

  let imputed = null;
  if (neighbors.length > 0) {{
    if (method === 'mean') {{
      imputed = neighbors.reduce((s,n) => s+n.val, 0) / neighbors.length;
    }} else if (method === 'idw') {{
      const p = 2;
      const sumW = neighbors.reduce((s,n) => s + 1/Math.pow(n.dist/1000,p), 0);
      imputed    = neighbors.reduce((s,n) => s + n.val/Math.pow(n.dist/1000,p), 0) / sumW;
    }} else if (method === 'corr') {{
      const sumW = neighbors.reduce((s,n) => s + Math.max(n.corr,0), 0);
      imputed    = sumW>0 ? neighbors.reduce((s,n) => s + n.val*Math.max(n.corr,0), 0)/sumW : null;
    }} else if (method === 'ridge') {{
      // Weighted average using corr weights (approximation of ridge)
      const sumW = neighbors.reduce((s,n) => s + Math.max(n.corr,0)**2, 0);
      imputed    = sumW>0 ? neighbors.reduce((s,n) => s + n.val*Math.max(n.corr,0)**2, 0)/sumW : null;
    }}
  }}

  // Update UI
  const mae = (trueVal!=null && imputed!=null) ? Math.abs(trueVal-imputed).toFixed(2) : '—';
  document.getElementById('iTarget').textContent   = target;
  document.getElementById('iTrue').textContent     = trueVal!=null ? trueVal.toFixed(1) : '—';
  document.getElementById('iImputed').textContent  = imputed!=null ? imputed.toFixed(1) : '—';
  document.getElementById('iMAE').textContent      = mae;

  const rc = document.getElementById('resultCard');
  rc.style.display = 'block';
  document.getElementById('rcK').textContent       = K;
  document.getElementById('rcMethod').textContent  = method.toUpperCase();
  document.getElementById('rcVal').textContent     = imputed!=null ? imputed.toFixed(1) : '—';
  document.getElementById('rcErr').textContent     = mae;

  updateMap();
  updateStationList();
  selectStation(target);
}}

/* ════════════════════════════════════════════════════════════════
   ZONE TABLE
════════════════════════════════════════════════════════════════ */
function updateZones() {{
  const zones = {{}};
  SD.forEach(s => {{
    const z = s.zone;
    if (!zones[z]) zones[z] = {{sum:0,count:0,stations:[]}};
    const v = getVal(s.name, curStep);
    if (v != null) {{ zones[z].sum += v; zones[z].count++; }}
    zones[z].stations.push(s);
  }});

  const el = document.getElementById('zoneTable');
  el.innerHTML = '';
  Object.keys(zones).sort().forEach(z => {{
    const d    = zones[z];
    const avg  = d.count > 0 ? (d.sum/d.count) : null;
    const color = pm25Color(avg);
    const block = document.createElement('div');
    block.style.cssText='margin-bottom:8px;border:1px solid var(--border);border-radius:8px;overflow:hidden';
    block.innerHTML = `
      <div style="background:${{color}};color:#fff;padding:6px 10px;display:flex;align-items:center;gap:8px">
        <span style="font-weight:800;font-size:13px">${{z}}</span>
        <span style="flex:1;font-size:11px">${{d.count}} stations</span>
        <span style="font-size:15px;font-weight:900">${{avg!=null?avg.toFixed(1):'—'}}</span>
        <span style="font-size:10px">µg/m³</span>
      </div>
      <div style="padding:6px 10px">
        ${{d.stations.map(s=>{{
          const v = getVal(s.name, curStep);
          return `<div style="display:flex;align-items:center;gap:6px;padding:2px 0;font-size:10px">
            <span style="width:8px;height:8px;border-radius:50%;background:${{pm25Color(v)}};display:inline-block"></span>
            <span style="flex:1;font-weight:600">${{s.name}}</span>
            <span style="color:var(--muted)">${{s.name_zh}}</span>
            <span style="font-weight:700;color:${{pm25Color(v)}}">${{v!=null?v.toFixed(1):'—'}}</span>
          </div>`;
        }}).join('')}}
      </div>
    `;
    block.style.cursor='pointer';
    block.onclick = () => d.stations.forEach(s => markerMap[s.name] && markerMap[s.name].openPopup());
    el.appendChild(block);
  }});
}}

/* ════════════════════════════════════════════════════════════════
   ENERGY CHARTS (Chart.js)
════════════════════════════════════════════════════════════════ */
function buildEnergyCharts() {{
  const monthly = ED.monthly;
  const labels  = monthly.map(m => m.label);
  const cons    = monthly.map(m => m.consumption_gwh);
  const sav     = monthly.map(m => m.savings_gwh);
  const co2     = monthly.map(m => m.co2_reduction_kt);

  // KPIs
  document.getElementById('kpiTotalCons').textContent = ED.summary.total_consumption_gwh.toLocaleString();
  document.getElementById('kpiTotalSav').textContent  = ED.summary.total_savings_gwh.toLocaleString();
  document.getElementById('kpiAvgPct').textContent    = ED.summary.avg_savings_pct + '%';
  document.getElementById('kpiCO2').textContent       = monthly.reduce((s,m)=>s+m.co2_reduction_kt,0).toFixed(0);

  // Consumption chart
  new Chart(document.getElementById('consChart'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{
          label: 'Consumption (GWh)',
          data: cons,
          backgroundColor: 'rgba(21,101,192,.7)',
          borderColor: 'rgba(21,101,192,1)',
          borderWidth: 1,
        }},
        {{
          label: 'Savings (GWh)',
          data: sav,
          backgroundColor: 'rgba(0,121,107,.7)',
          borderColor: 'rgba(0,121,107,1)',
          borderWidth: 1,
          stack: 'total',
          order: 0,
        }}
      ]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins:{{
        legend:{{position:'bottom',labels:{{font:{{size:9}},boxWidth:10}}}},
        tooltip:{{callbacks:{{label:ctx=>`${{ctx.dataset.label}}: ${{ctx.parsed.y}} GWh`}}}}
      }},
      scales:{{
        x:{{ticks:{{font:{{size:8}},maxRotation:45}},stacked:false}},
        y:{{title:{{display:true,text:'GWh',font:{{size:9}}}},ticks:{{font:{{size:9}}}}}}
      }}
    }}
  }});

  // Savings + CO2 chart
  new Chart(document.getElementById('savChart'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{
          label: 'Energy Saved (GWh)',
          data: sav,
          backgroundColor: 'rgba(0,121,107,.7)',
          borderColor: 'rgba(0,121,107,1)',
          borderWidth: 1,
          yAxisID: 'y',
        }},
        {{
          label: 'CO₂ Reduction (kt)',
          data: co2,
          type: 'line',
          borderColor: '#c62828',
          backgroundColor: 'rgba(198,40,40,.1)',
          borderWidth: 2,
          pointRadius: 3,
          fill: false,
          yAxisID: 'y2',
        }}
      ]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins:{{
        legend:{{position:'bottom',labels:{{font:{{size:9}},boxWidth:10}}}},
        tooltip:{{callbacks:{{label:ctx=>ctx.dataset.label+': '+ctx.parsed.y+(ctx.dataset.yAxisID==='y2'?' kt':' GWh')}}}}
      }},
      scales:{{
        x:{{ticks:{{font:{{size:8}},maxRotation:45}}}},
        y:{{position:'left',title:{{display:true,text:'GWh Saved',font:{{size:9}}}},ticks:{{font:{{size:9}}}}}},
        y2:{{position:'right',title:{{display:true,text:'k-tonnes CO₂',font:{{size:9}}}},ticks:{{font:{{size:9}}}},grid:{{drawOnChartArea:false}}}}
      }}
    }}
  }});
}}
buildEnergyCharts();

/* ════════════════════════════════════════════════════════════════
   TABS
════════════════════════════════════════════════════════════════ */
document.querySelectorAll('.sb-tab').forEach(btn => btn.onclick = () => {{
  document.querySelectorAll('.sb-tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.sb-pane').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('pane-'+btn.dataset.pane).classList.add('active');
}});

/* ════════════════════════════════════════════════════════════════
   INIT
════════════════════════════════════════════════════════════════ */
updateTime();
updateStationList();
updateZones();
// auto-select first station
selectStation(NAMES[0]);
</script>
</body>
</html>
"""

OUT.write_text(HTML, encoding="utf-8")
print(f"Written → {OUT}  ({OUT.stat().st_size // 1024} KB)")
