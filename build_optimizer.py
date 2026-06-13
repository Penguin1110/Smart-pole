"""build_optimizer.py — 產生 work/pm25_optimizer.html
窮舉: n(0-24h) × m(1-11站) × 方法(Mean / IDW[p=0.5~5×8種] / Corr / Ridge / Self)
功能:
  - 搜索後摘要列出「全域最優一行」
  - 熱力圖 (n×m) 保留，Tab: 最優/Self/Mean/IDW(最優p)/Corr/Ridge
  - 播放鍵：在固定時刻 t，逐步往前推 n=0→24，地圖即時顯示各 n 的最優補值
  - 點擊熱力圖格子 → 地圖高亮對應鄰站、回溯軸跳到該 n
"""
import json, pathlib

work = pathlib.Path(__file__).parent / "work"
SJ = json.dumps(json.loads((work/"stations.json").read_text("utf-8")),      ensure_ascii=False, separators=(',',':'))
CJ = json.dumps(json.loads((work/"correlations.json").read_text("utf-8")),  ensure_ascii=False, separators=(',',':'))
TJ = json.dumps(json.loads((work/"pm25_timeseries.json").read_text("utf-8")),ensure_ascii=False, separators=(',',':'))

P1 = """\
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>高雄 PM2.5 補值最優化</title>
  <link rel="preconnect" href="https://unpkg.com"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    :root{
      --bg:#f4f7fb;--panel:#fff;--text:#16202b;--muted:#5f6b7a;
      --border:#d9e2ec;--shadow:0 10px 30px rgba(22,32,43,.08);
      --good:#2e7d32;--moderate:#f9a825;--ufs:#ef6c00;
      --unhealthy:#c62828;--vu:#6a1b9a;--haz:#4e342e;
      --primary:#1e66d0;--orange:#ef6c00;
    }
    *{box-sizing:border-box}
    html,body{height:100%;margin:0;font-family:Inter,"Noto Sans TC",system-ui,sans-serif;
      color:var(--text);background:var(--bg)}
    body{padding:14px}

    .page-header{background:var(--panel);border:1px solid var(--border);border-radius:12px;
      box-shadow:var(--shadow);padding:12px 16px;margin-bottom:10px;display:grid;gap:4px}
    .page-header h1{margin:0;font-size:18px}
    .page-header p{margin:0;color:var(--muted);font-size:12px;line-height:1.6}

    /* 時間列 */
    .time-bar{background:var(--panel);border:1px solid var(--border);border-radius:12px;
      box-shadow:var(--shadow);padding:10px 16px;margin-bottom:10px;display:grid;gap:8px}
    .time-top{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
    .time-label{font-size:14px;font-weight:700;min-width:160px}
    .time-sub{font-size:11px;color:var(--muted)}
    .time-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .btn-icon{width:30px;height:30px;border:1px solid var(--border);border-radius:7px;
      background:#fff;cursor:pointer;font-size:14px;display:grid;place-items:center;transition:background .15s}
    .btn-icon:hover{background:#f0f7ff}
    .btn-icon.playing{background:var(--primary);border-color:var(--primary);color:#fff}
    .btn-icon.playing-lb{background:var(--orange);border-color:var(--orange);color:#fff}
    #timeSlider{flex:1;min-width:200px;accent-color:var(--primary)}
    #lbSlider{flex:1;accent-color:var(--orange)}
    .speed-sel{height:30px;border:1px solid var(--border);border-radius:7px;padding:0 6px;
      font:inherit;font-size:11px;background:#fff;color:var(--text)}
    .month-btns{display:flex;gap:5px;align-items:center}
    .month-btns span{font-size:11px;color:var(--muted)}
    .mbtn{padding:3px 9px;border:1px solid var(--border);border-radius:6px;background:#fff;
      font:inherit;font-size:11px;cursor:pointer;transition:all .15s}
    .mbtn.active,.mbtn:hover{background:var(--primary);border-color:var(--primary);color:#fff}

    /* 主版面 */
    .app{min-height:calc(100vh - 210px);display:grid;grid-template-columns:1fr 440px;gap:12px}
    .panel{background:var(--panel);border:1px solid var(--border);border-radius:12px;
      box-shadow:var(--shadow);overflow:hidden;min-height:0}
    #map{width:100%;height:100%;min-height:460px;background:#dbeafe}

    /* 側欄 */
    .sidebar{display:flex;flex-direction:column;min-width:0;overflow:hidden}

    /* 控制區 */
    .controls{padding:10px 13px;border-bottom:1px solid var(--border);display:grid;gap:6px;
      background:linear-gradient(180deg,#fbfdff,#f8fbff);flex-shrink:0}
    .controls h2{margin:0;font-size:13px}
    .controls p{margin:0;font-size:10px;color:var(--muted)}
    .field label{font-size:11px;color:var(--muted);font-weight:500;display:block;margin-bottom:3px}
    .field select{width:100%;height:32px;border-radius:8px;border:1px solid var(--border);
      padding:0 9px;font:inherit;color:var(--text);background:#fff;outline:none}
    .field select:focus{border-color:#7aa7d9;box-shadow:0 0 0 3px rgba(122,167,217,.18)}
    .row2{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:end}
    .btn{height:32px;border:1px solid var(--border);border-radius:8px;padding:0 12px;
      background:#fff;color:var(--text);font:inherit;cursor:pointer;transition:all .2s;white-space:nowrap}
    .btn.primary{background:var(--primary);border-color:var(--primary);color:#fff}
    .btn.primary:hover:not(:disabled){background:#1557b8}
    .btn:disabled{opacity:.5;cursor:not-allowed}
    .target-info{background:#f0f4f8;border-radius:7px;padding:4px 9px;font-size:11px;
      color:var(--muted);display:flex;gap:10px;flex-wrap:wrap}
    .ti-val{font-weight:700;color:var(--text)}

    /* 回溯動畫控制 */
    .lb-ctrl{padding:8px 13px;border-bottom:1px solid var(--border);
      background:#fffcf0;flex-shrink:0;display:grid;gap:5px}
    .lb-hd{display:flex;justify-content:space-between;align-items:center}
    .lb-title{font-size:11px;font-weight:700;color:#7c5a00}
    .lb-lbl{font-size:12px;font-weight:800;color:var(--orange)}
    .lb-row{display:flex;align-items:center;gap:5px}
    .lb-hint{font-size:10px;color:var(--muted);line-height:1.4}

    /* 最優一行摘要 */
    .best-bar{padding:7px 13px;border-bottom:1px solid var(--border);
      background:#f8fbff;font-size:11px;display:flex;align-items:center;
      flex-wrap:wrap;gap:3px 7px;flex-shrink:0;min-height:34px}
    .best-bar.found{background:#eff6ff}
    .bb-trophy{font-size:13px}
    .bb-method{font-weight:700;color:var(--primary)}
    .bb-err{font-weight:700;color:var(--primary);font-size:12px}
    .bb-dot{color:var(--border)}
    .bb-empty{color:var(--muted)}

    /* 各方法比較 */
    .mc-wrap{padding:7px 13px;border-bottom:1px solid var(--border);flex-shrink:0}
    .mc-title{font-size:10px;font-weight:700;color:var(--muted);margin-bottom:4px}
    .mc-table{width:100%;font-size:11px;border-collapse:collapse}
    .mc-table th{background:#f0f4f8;padding:3px 5px;text-align:left;
      border-bottom:1px solid var(--border);font-size:10px;font-weight:600}
    .mc-table td{padding:3px 5px;border-bottom:1px solid #eef2f7}
    .mc-table .best-row td{background:#eff6ff;font-weight:700;color:var(--primary)}
    .mc-table tr:hover td{background:#f8fbff}

    /* 熱力圖 */
    .hm-section{flex:1;display:flex;flex-direction:column;min-height:0;overflow:hidden}
    .tab-bar{display:flex;gap:3px;padding:6px 8px 0;background:#f8fbff;
      border-bottom:1px solid var(--border);flex-shrink:0}
    .tab-btn{padding:3px 8px;border:1px solid var(--border);border-radius:6px 6px 0 0;
      background:#fff;font:inherit;font-size:10px;cursor:pointer;transition:all .15s;
      border-bottom:none;position:relative;top:1px}
    .tab-btn.active{background:#fff;border-color:var(--primary);color:var(--primary);font-weight:700}
    .tab-btn:hover:not(.active){background:#f0f7ff}
    .hm-outer{flex:1;overflow:auto;padding:5px 7px}

    .hm-table{border-collapse:collapse;font-size:9px;white-space:nowrap}
    .hm-th{background:#f0f4f8;padding:2px 3px;text-align:center;border:1px solid #d4dde8;
      font-weight:600;font-size:9px;position:sticky;top:0;z-index:2}
    .hm-rh{background:#f0f4f8;padding:2px 5px;text-align:right;border:1px solid #d4dde8;
      font-weight:600;font-size:9px;white-space:nowrap;position:sticky;left:0;z-index:1;
      cursor:pointer;transition:background .15s}
    .hm-rh:hover{background:#dbeafe}
    .hm-rh.lb-active{background:#bfdbfe;color:var(--primary);font-weight:800}
    .hm-cell{border:1px solid rgba(0,0,0,.06);width:29px;height:19px;text-align:center;
      cursor:pointer;font-size:9px;vertical-align:middle;transition:outline .1s}
    .hm-cell:hover{outline:2px solid var(--primary);outline-offset:-2px;z-index:3;position:relative}
    .hm-cell.selected{outline:2px solid #1557b8;outline-offset:-2px;z-index:4;position:relative;font-weight:900}
    .hm-cell.global-best{outline:2px solid var(--orange);outline-offset:-1px;font-weight:900}
    .hm-na{border:1px solid #eef2f7;width:29px;height:19px;text-align:center;
      font-size:8px;color:#d0d7e0;vertical-align:middle}
    .hm-empty{text-align:center;padding:24px;font-size:12px;color:var(--muted)}

    /* 自身 tab 長條 */
    .self-table{width:100%;border-collapse:collapse;font-size:11px}
    .self-table th{background:#f0f4f8;padding:3px 6px;text-align:left;
      border-bottom:1px solid var(--border);font-size:10px}
    .self-table td{padding:3px 6px;border-bottom:1px solid #eef2f7}
    .self-table tr.lb-active td{background:#bfdbfe;font-weight:700}
    .self-bar{display:inline-block;height:12px;border-radius:3px;min-width:2px;vertical-align:middle}

    /* 圖例 */
    .legend{padding:7px 13px;display:flex;flex-wrap:wrap;gap:5px;flex-shrink:0;
      border-top:1px solid var(--border)}
    .li{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border:1px solid var(--border);
      border-radius:999px;font-size:11px;color:var(--muted);background:#fff}
    .sw{width:8px;height:8px;border-radius:50%;display:inline-block}
    .err-legend{display:flex;align-items:center;gap:6px;font-size:10px;color:var(--muted)}
    .err-grad{width:80px;height:8px;border-radius:4px;
      background:linear-gradient(90deg,#2e7d32,#f9a825,#c62828)}

    /* 地圖標記 */
    .mk{width:34px;height:34px;border-radius:50%;border:2px solid rgba(255,255,255,.96);
      box-shadow:0 2px 8px rgba(0,0,0,.18);display:grid;place-items:center;
      color:#fff;font-size:11px;font-weight:800;transform:translate(-50%,-50%);cursor:pointer;transition:transform .2s}
    .mk:hover{transform:translate(-50%,-50%) scale(1.15)}
    .mk.target-mk{border:3px solid rgba(30,102,208,1);box-shadow:0 0 0 4px rgba(30,102,208,.25),0 2px 8px rgba(0,0,0,.18)}
    .mk.nb-mk{border:2px solid rgba(239,108,0,.9);box-shadow:0 0 0 3px rgba(239,108,0,.2),0 2px 8px rgba(0,0,0,.18)}
    .mk.dim-mk{opacity:0.18;pointer-events:none}
    .mk-tag{position:absolute;top:38px;left:50%;transform:translateX(-50%);
      background:var(--primary);color:#fff;font-size:9px;font-weight:700;
      padding:2px 5px;border-radius:4px;white-space:nowrap;pointer-events:none;line-height:1.4;
      box-shadow:0 1px 3px rgba(0,0,0,.25)}
    .mk-tag.orange{background:var(--orange)}
    .mk-tag.err{top:56px;background:#fff;color:var(--primary);border:1px solid var(--primary)}
    .leaflet-popup-content{margin:10px 12px;font:inherit;line-height:1.5}
    .pt{font-size:14px;font-weight:700;margin-bottom:3px}
    .pg{display:grid;gap:2px;font-size:12px}
    .pg span{color:var(--muted)}

    @media(max-width:1100px){.app{grid-template-columns:1fr}#map{min-height:380px}}
  </style>
</head>
<body>
  <header class="page-header">
    <h1>高雄 PM2.5 補值最優化搜索器</h1>
    <p>固定基準時刻 t，窮舉 <strong>n(0-24h) &times; m(1-11站) &times; 方法(Mean / IDW×8種p / Corr / Ridge / Self) ≈ 3000 組合</strong>。
       熱力圖橫軸=鄰站數 m，縱軸=回溯 n；點格子或拖動回溯軸，地圖即時高亮鄰站（橘色=n小時前值）並標示最優補值。</p>
  </header>

  <!-- 主時間列：選定基準時刻 t -->
  <div class="time-bar">
    <div class="time-top">
      <div>
        <div class="time-label" id="timeLabel">—</div>
        <div class="time-sub" id="timeSub">—</div>
      </div>
      <div class="month-btns">
        <span>快速跳至：</span>
        <button class="mbtn" data-step="0">12月</button>
        <button class="mbtn" data-step="744">1月</button>
        <button class="mbtn" data-step="1488">2月</button>
      </div>
    </div>
    <div class="time-row">
      <button class="btn-icon" id="prevBtn">&#9664;</button>
      <button class="btn-icon" id="mainPlayBtn">&#9654;</button>
      <button class="btn-icon" id="nextBtn">&#9654;</button>
      <input type="range" id="timeSlider" min="0" max="2159" value="2159" step="1"/>
      <select class="speed-sel" id="speedSel">
        <option value="500">慢速</option>
        <option value="200" selected>正常</option>
        <option value="100">快速</option>
        <option value="50">極快</option>
      </select>
    </div>
  </div>

  <main class="app">
    <section class="panel" style="display:grid;grid-template-rows:1fr;min-width:0">
      <div id="map"></div>
    </section>

    <aside class="panel sidebar">

      <!-- 1. 目標站 & 搜索 -->
      <div class="controls">
        <div><h2>目標站 &amp; 搜索</h2>
          <p>IDW 冪次 p 自動窮舉 {0.5,1,1.5,2,2.5,3,4,5}，共約 3000 組合（&lt;0.5 秒）</p></div>
        <div class="row2">
          <div class="field">
            <label for="targetSel">目標測站（視為缺測，其他站補值）</label>
            <select id="targetSel"></select>
          </div>
          <button class="btn primary" id="searchBtn" style="margin-bottom:0">&#9881; 搜索</button>
        </div>
        <div class="target-info">
          <span>當前值：<span class="ti-val" id="tiVal">--</span> μg/m³</span>
          <span>時刻：<span class="ti-val" id="tiTime">--</span></span>
        </div>
      </div>

      <!-- 2. 回溯動畫（播放 n=0→24） -->
      <div class="lb-ctrl">
        <div class="lb-hd">
          <span class="lb-title">&#9654; 回溯動畫（播放 n=0 &#8594; 24h）</span>
          <span class="lb-lbl" id="lbLabel">n = 0h（當下）</span>
        </div>
        <div class="lb-row">
          <button class="btn-icon" id="lbPrevBtn">&#9664;</button>
          <button class="btn-icon" id="lbPlayBtn">&#9654;</button>
          <button class="btn-icon" id="lbNextBtn">&#9654;</button>
          <input type="range" id="lbSlider" min="0" max="24" value="0" step="1"/>
          <select class="speed-sel" id="lbSpeedSel">
            <option value="1000">慢</option>
            <option value="500" selected>正常</option>
            <option value="250">快</option>
          </select>
        </div>
        <div class="lb-hint">搜索後拖動或播放：地圖藍色=目標站（當前），橘色=最優鄰站（n小時前），標記顯示最優補值結果。</div>
      </div>

      <!-- 3. 全域最優一行摘要 -->
      <div class="best-bar" id="bestBar">
        <span class="bb-empty">執行搜索後顯示最優組合</span>
      </div>

      <!-- 4. 各方法最優比較 -->
      <div class="mc-wrap" id="mcWrap" style="display:none">
        <div class="mc-title">各方法最優比較</div>
        <table class="mc-table">
          <thead><tr><th>方法</th><th>回溯 n</th><th>鄰站 m</th><th>誤差 (μg/m³)</th></tr></thead>
          <tbody id="mcBody"></tbody>
        </table>
      </div>

      <!-- 5. 熱力圖 -->
      <div class="hm-section">
        <div class="tab-bar" id="tabBar">
          <button class="tab-btn active" data-tab="best">最優</button>
          <button class="tab-btn" data-tab="self">Self</button>
          <button class="tab-btn" data-tab="mean">Mean</button>
          <button class="tab-btn" data-tab="idw">IDW</button>
          <button class="tab-btn" data-tab="corr">Corr</button>
          <button class="tab-btn" data-tab="ridge">Ridge</button>
        </div>
        <div class="hm-outer" id="hmOuter">
          <div class="hm-empty">執行搜索後顯示熱力圖<br><small>橫軸 m=鄰站數，縱軸 n=回溯小時</small></div>
        </div>
      </div>

      <!-- 6. 圖例 -->
      <div class="legend">
        <div class="li" style="border-color:var(--primary)">
          <span class="sw" style="background:var(--primary)"></span>目標站（當前）</div>
        <div class="li" style="border-color:var(--orange)">
          <span class="sw" style="background:var(--orange)"></span>最優鄰站（n小時前）</div>
        <div class="li"><span class="sw" style="background:#94a3b8"></span>其他（淡化）</div>
        <div class="err-legend">
          <span>低誤差</span>
          <div class="err-grad"></div>
          <span>高誤差</span>
        </div>
        <div class="li" style="border-color:var(--orange)">
          <span style="color:var(--orange);font-weight:700">■</span>全域最優格</div>
      </div>

    </aside>
  </main>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
/* ── 內嵌資料 ── */
const _SD="""

P2 = """;
const _CD="""

P3 = """;
const _TD="""

P4 = """;

/* ── 狀態 ── */
let stations=[], corrMat={}, tsData={};
let curStep=0, mainTimer=null;
let lbN=0, lbTimer=null;
let searchTarget=null, searchStep=-1;
let searchResults=[];  // { n, m, method, p, predicted, error }
let activeTab='best';
let selectedCellKey=null;

const IDW_P_VALS=[0.5,1.0,1.5,2.0,2.5,3.0,4.0,5.0];

const el={
  targetSel:   document.getElementById('targetSel'),
  searchBtn:   document.getElementById('searchBtn'),
  lbSlider:    document.getElementById('lbSlider'),
  lbPlayBtn:   document.getElementById('lbPlayBtn'),
  lbPrevBtn:   document.getElementById('lbPrevBtn'),
  lbNextBtn:   document.getElementById('lbNextBtn'),
  lbLabel:     document.getElementById('lbLabel'),
  lbSpeedSel:  document.getElementById('lbSpeedSel'),
  tiVal:       document.getElementById('tiVal'),
  tiTime:      document.getElementById('tiTime'),
  slider:      document.getElementById('timeSlider'),
  timeLabel:   document.getElementById('timeLabel'),
  timeSub:     document.getElementById('timeSub'),
  mainPlayBtn: document.getElementById('mainPlayBtn'),
  prevBtn:     document.getElementById('prevBtn'),
  nextBtn:     document.getElementById('nextBtn'),
  speedSel:    document.getElementById('speedSel'),
};

/* ── 地圖 ── */
const map=L.map('map',{zoomControl:true,preferCanvas:true,minZoom:9}).setView([22.65,120.35],11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:18,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
const mkLayer=L.layerGroup().addTo(map);

/* ── 工具 ── */
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const css=k=>getComputedStyle(document.documentElement).getPropertyValue(k).trim();
function pm25Color(v){
  if(v==null)return '#64748b';
  if(v<=35)return css('--good');if(v<=53)return css('--moderate');
  if(v<=70)return css('--ufs');if(v<=150)return css('--unhealthy');
  if(v<=250)return css('--vu');return css('--haz');
}
function lc(v){ return(v!=null&&v<=53)?'#111827':'#fff'; }
function haversine(a,b,c,d){
  const R=6371,r=Math.PI/180,dl=(c-a)*r,dL=(d-b)*r;
  const x=Math.sin(dl/2)**2+Math.cos(a*r)*Math.cos(c*r)*Math.sin(dL/2)**2;
  return R*2*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));
}
function pm25ToAqi(pm){
  if(pm==null)return null;
  const bp=[[0,12,0,50],[12.1,35.4,51,100],[35.5,55.4,101,150],
            [55.5,150.4,151,200],[150.5,250.4,201,300],[250.5,500.4,301,500]];
  for(const[lo,hi,la,ha]of bp)if(pm>=lo&&pm<=hi)return Math.round((ha-la)/(hi-lo)*(pm-lo)+la);
  return pm>500?500:0;
}
function stepToDate(s){ return new Date(new Date('2025-12-01T00:00:00').getTime()+s*3600000); }
function fmtDate(d){
  const p=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:00`;
}

/* ── 補值函數 ── */
function imputeMean(nb){
  const v=nb.map(x=>x.s.pm25).filter(x=>x!=null);
  return v.length?v.reduce((a,b)=>a+b,0)/v.length:null;
}
function imputeIDW(nb,p){
  let n=0,den=0;
  for(const x of nb){if(x.s.pm25==null)continue;const w=1/Math.pow(x.d+0.01,p);n+=w*x.s.pm25;den+=w;}
  return den>0?n/den:null;
}
function imputeCorr(target,nb){
  const ni=corrMat.stations,mx=corrMat.matrix,ti=ni.indexOf(target.name);
  if(ti===-1)return imputeIDW(nb,2);
  let n=0,den=0;
  for(const x of nb){
    if(x.s.pm25==null)continue;
    const i=ni.indexOf(x.s.name);const w=i!==-1?Math.max(0,mx[ti][i]):0;
    n+=w*x.s.pm25;den+=w;
  }
  return den>0?n/den:null;
}
function gaussJordan(A,sz){
  const M=A.map(r=>[...r]);
  for(let c=0;c<sz;c++){
    let pv=-1;for(let r=c;r<sz;r++)if(Math.abs(M[r][c])>1e-10){pv=r;break;}
    if(pv===-1)return null;[M[c],M[pv]]=[M[pv],M[c]];
    const sc=M[c][c];for(let j=c;j<=sz;j++)M[c][j]/=sc;
    for(let r=0;r<sz;r++){if(r===c)continue;const f=M[r][c];for(let j=c;j<=sz;j++)M[r][j]-=f*M[c][j];}
  }
  return M.map(r=>r[sz]);
}
function imputeRidge(target,nb,a=0.1){
  const ni=corrMat.stations,mx=corrMat.matrix,K=nb.length;if(!K)return null;
  const ti=ni.indexOf(target.name);if(ti===-1)return imputeCorr(target,nb);
  const G=nb.map((_,i)=>nb.map((_,j)=>{
    const ii=ni.indexOf(nb[i].s.name),jj=ni.indexOf(nb[j].s.name);
    return(ii!==-1&&jj!==-1)?mx[ii][jj]:(i===j?1:0);
  }));
  const c=nb.map(x=>{const i=ni.indexOf(x.s.name);return i!==-1?Math.max(0,mx[ti][i]):0;});
  const Aug=G.map((row,i)=>[...row.map((v,j)=>v+(i===j?a:0)),c[i]]);
  const sol=gaussJordan(Aug,K);if(!sol)return imputeCorr(target,nb);
  const w=sol.map(v=>Math.max(0,v)),ws=w.reduce((a,b)=>a+b,0);
  if(!ws)return imputeMean(nb);
  return nb.reduce((s,x,i)=>s+(x.s.pm25!=null?(w[i]/ws)*x.s.pm25:0),0);
}
function getNeighborsAtStep(target,k,step){
  return stations
    .filter(s=>s.id!==target.id)
    .map(s=>({s:{...s,pm25:tsData[s.name]?tsData[s.name][step]:null},
              d:haversine(target.lat,target.lon,s.lat,s.lon)}))
    .filter(x=>x.s.pm25!=null)
    .sort((a,b)=>a.d-b.d)
    .slice(0,k);
}

/* ── 主時間軸 ── */
function applyStep(step){
  curStep=Math.max(0,Math.min(_TD.n-1,step));
  el.slider.value=curStep;
  const d=stepToDate(curStep);
  el.timeLabel.textContent=fmtDate(d);
  el.timeSub.textContent=`第 ${curStep+1} / ${_TD.n} 小時`;
  for(const s of stations){const arr=tsData[s.name];s.pm25=arr?arr[curStep]:null;s.aqi=pm25ToAqi(s.pm25);}
  updateTargetInfo();
  if(searchResults.length&&searchStep!==curStep){
    searchResults=[];searchStep=-1;selectedCellKey=null;
    renderBestBar(null);document.getElementById('mcWrap').style.display='none';
    document.getElementById('hmOuter').innerHTML=
      '<div class="hm-empty">時刻已更換，請重新執行搜索</div>';
  }
  renderMap();
}

/* ── 回溯動畫軸 ── */
function applyLbN(n){
  lbN=Math.max(0,Math.min(24,n));
  el.lbSlider.value=lbN;
  el.lbLabel.textContent=lbN===0?'n = 0h（當下）':`n = ${lbN}h 前`;
  highlightLbRow();
  renderMap();
}
function highlightLbRow(){
  document.querySelectorAll('.hm-rh').forEach(th=>{
    const n=parseInt(th.dataset.n??'');
    th.classList.toggle('lb-active',n===lbN);
  });
  document.querySelectorAll('.self-table tr[data-n]').forEach(tr=>{
    tr.classList.toggle('lb-active',+tr.dataset.n===lbN);
  });
}

function updateTargetInfo(){
  if(!searchTarget)return;
  const v=searchTarget.pm25;
  el.tiVal.textContent=v!=null?v.toFixed(1):'缺測';
  el.tiTime.textContent=el.timeLabel.textContent;
}

/* ── 窮舉搜索 ── */
function runSearch(){
  if(!searchTarget)return;
  searchStep=curStep;selectedCellKey=null;
  const actual=tsData[searchTarget.name][searchStep];
  if(actual==null){
    renderBestBar(null,'當前時刻目標站缺測，請換一個時刻');return;
  }
  searchResults=[];
  for(let n=0;n<=24;n++){
    const step=searchStep-n;if(step<0)continue;
    if(n>=1){
      const sv=tsData[searchTarget.name][step];
      if(sv!=null) searchResults.push({n,m:0,method:'self',p:null,
        predicted:Math.round(sv*100)/100,error:Math.round(Math.abs(actual-sv)*1000)/1000});
    }
    for(let m=1;m<=11;m++){
      const nb=getNeighborsAtStep(searchTarget,m,step);if(!nb.length)continue;
      const vm=imputeMean(nb);
      if(vm!=null) searchResults.push({n,m,method:'mean',p:null,
        predicted:Math.round(vm*100)/100,error:Math.round(Math.abs(actual-vm)*1000)/1000});
      for(const p of IDW_P_VALS){
        const vi=imputeIDW(nb,p);
        if(vi!=null) searchResults.push({n,m,method:'idw',p,
          predicted:Math.round(vi*100)/100,error:Math.round(Math.abs(actual-vi)*1000)/1000});
      }
      const vc=imputeCorr(searchTarget,nb);
      if(vc!=null) searchResults.push({n,m,method:'corr',p:null,
        predicted:Math.round(vc*100)/100,error:Math.round(Math.abs(actual-vc)*1000)/1000});
      const vr=imputeRidge(searchTarget,nb);
      if(vr!=null) searchResults.push({n,m,method:'ridge',p:null,
        predicted:Math.round(vr*100)/100,error:Math.round(Math.abs(actual-vr)*1000)/1000});
    }
  }
  renderBestBar(actual);
  renderMethodCompare(actual);
  renderHeatmap(activeTab);
  const best=getBestOverall();
  if(best)applyLbN(best.n); else renderMap();
}

/* ── 查詢 ── */
function getBestOverall(){
  return searchResults.length?searchResults.reduce((a,b)=>a.error<b.error?a:b):null;
}
function getBestForGroup(key){
  const f=searchResults.filter(r=>r.method===key);
  return f.length?f.reduce((a,b)=>a.error<b.error?a:b):null;
}
function getBestForN(n){
  const f=searchResults.filter(r=>r.n===n);
  return f.length?f.reduce((a,b)=>a.error<b.error?a:b):null;
}
function getBestForCell(n,m){
  const f=searchResults.filter(r=>r.n===n&&r.m===m);
  return f.length?f.reduce((a,b)=>a.error<b.error?a:b):null;
}
function getBestForCellMethod(n,m,key){
  const f=searchResults.filter(r=>r.n===n&&r.m===m&&r.method===key);
  return f.length?f.reduce((a,b)=>a.error<b.error?a:b):null;
}
function cellKey(r){ return `${r.n}_${r.m}_${r.method}_${r.p}`; }
function mLabel(r,short){
  const s={self:'Self',mean:'Mean',idw:'IDW',corr:'Corr',ridge:'Ridge'};
  const l={self:'Self 自身歷史',mean:'Mean 均值',idw:'IDW',corr:'Corr-Weighted',ridge:'Ridge 回歸'};
  const base=(short?s:l)[r.method];
  return r.method==='idw'?`${base}(p=${r.p})`:base;
}

/* ── 顏色 ── */
function errColor(err,minE,maxE){
  if(err==null)return '#f1f5f9';
  const t=Math.min(1,Math.max(0,(err-minE)/Math.max(maxE-minE,0.1)));
  let r,g,b;
  if(t<0.5){const tt=t*2;r=Math.round(46+tt*(249-46));g=Math.round(125+tt*(168-125));b=Math.round(50-tt*50);}
  else{const tt=(t-0.5)*2;r=Math.round(249+tt*(198-249));g=Math.round(168+tt*(40-168));b=Math.round(3+tt*34);}
  return `rgb(${r},${g},${b})`;
}

/* ── 最優一行摘要 ── */
function renderBestBar(actual, errMsg){
  const bar=document.getElementById('bestBar');
  if(errMsg){bar.className='best-bar';bar.innerHTML=`<span class="bb-empty">&#9888; ${esc(errMsg)}</span>`;return;}
  if(!searchResults.length||actual==null){
    bar.className='best-bar';
    bar.innerHTML='<span class="bb-empty">執行搜索後顯示最優組合</span>';return;
  }
  const best=getBestOverall();
  bar.className='best-bar found';
  const mStr=best.m>0?`m=${best.m}`:'m=—(self)';
  bar.innerHTML=
    `<span class="bb-trophy">&#127942;</span>`+
    `<span class="bb-method">${mLabel(best,false)}</span>`+
    `<span class="bb-dot">&#183;</span>`+
    `<span>n=<strong>${best.n}</strong>h</span>`+
    `<span class="bb-dot">&#183;</span>`+
    `<span>${mStr}</span>`+
    `<span class="bb-dot">&#183;</span>`+
    `<span class="bb-err">誤差 <strong>${best.error.toFixed(3)}</strong> μg/m³</span>`+
    `<span class="bb-dot">&#183;</span>`+
    `<span>補值 <strong>${best.predicted.toFixed(2)}</strong> / 真實 <strong>${actual.toFixed(2)}</strong></span>`;
}

/* ── 各方法比較表 ── */
function renderMethodCompare(actual){
  const groups=['self','mean','idw','corr','ridge'];
  const medals=['&#127942;','&#129352;','&#129353;','',''];
  const bests=groups.map(g=>getBestForGroup(g)).filter(Boolean);
  bests.sort((a,b)=>a.error-b.error);
  const best=getBestOverall();
  document.getElementById('mcBody').innerHTML=bests.map((x,i)=>{
    const isB=best&&x.error===best.error&&x.method===best.method&&x.n===best.n&&x.m===best.m;
    const mStr=x.m>0?`K=${x.m}`:'—';
    return `<tr class="${isB?'best-row':''}">
      <td>${medals[i]||''} ${mLabel(x,true)}</td>
      <td>${x.n}h 前</td><td>${mStr}</td>
      <td><strong>${x.error.toFixed(3)}</strong></td></tr>`;
  }).join('');
  document.getElementById('mcWrap').style.display='';
}

/* ── 熱力圖 ── */
function renderHeatmap(tab){
  activeTab=tab;
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  const container=document.getElementById('hmOuter');
  if(!searchResults.length){
    container.innerHTML='<div class="hm-empty">執行搜索後顯示熱力圖<br><small>橫軸 m=鄰站數，縱軸 n=回溯小時</small></div>';
    return;
  }

  const globalBest=getBestOverall();

  // Self tab：1D 長條圖
  if(tab==='self'){
    const filtered=searchResults.filter(r=>r.method==='self');
    if(!filtered.length){container.innerHTML='<div class="hm-empty">Self 無資料（需 n≥1）</div>';return;}
    const errors=filtered.map(r=>r.error),minE=Math.min(...errors),maxE=Math.max(...errors);
    let html='<table class="self-table"><thead><tr><th>回溯 n</th><th>誤差</th><th>大小</th></tr></thead><tbody>';
    for(let n=1;n<=24;n++){
      const r=filtered.find(x=>x.n===n);if(!r){html+=`<tr data-n="${n}"><td>${n}h</td><td colspan="2" style="color:var(--muted)">無資料</td></tr>`;continue;}
      const bg=errColor(r.error,minE,maxE);
      const barW=Math.max(2,Math.round((r.error-minE)/Math.max(maxE-minE,0.1)*130));
      const isG=globalBest&&r.method===globalBest.method&&r.n===globalBest.n;
      html+=`<tr data-n="${n}" class="${r.n===lbN?'lb-active':''}">
        <td>${n}h${isG?' &#9733;':''}</td>
        <td style="background:${bg};text-align:center;padding:2px 5px;cursor:pointer"
          data-n="${n}" data-m="0" data-method="self" data-p="">${r.error.toFixed(3)}</td>
        <td><span class="self-bar" style="background:${bg};width:${barW}px"></span></td></tr>`;
    }
    html+='</tbody></table>';
    container.innerHTML=html;
    container.querySelectorAll('td[data-n]').forEach(addCellClick);
    return;
  }

  // 2D 熱力圖
  let getData;
  if(tab==='best') getData=(n,m)=>getBestForCell(n,m);
  else getData=(n,m)=>getBestForCellMethod(n,m,tab);

  // 收集有效格子計算色域
  const allR=[];
  for(let n=0;n<=24;n++) for(let m=1;m<=11;m++){const r=getData(n,m);if(r)allR.push(r);}
  if(!allR.length){container.innerHTML='<div class="hm-empty">此方法無資料</div>';return;}
  const minE=Math.min(...allR.map(r=>r.error)),maxE=Math.max(...allR.map(r=>r.error));

  let html='<table class="hm-table"><thead><tr>';
  html+='<th class="hm-th" style="width:32px">n\\m</th>';
  for(let m=1;m<=11;m++)html+=`<th class="hm-th">${m}</th>`;
  html+='</tr></thead><tbody>';

  for(let n=0;n<=24;n++){
    html+=`<tr><th class="hm-rh${n===lbN?' lb-active':''}" data-n="${n}">${n}h</th>`;
    for(let m=1;m<=11;m++){
      const r=getData(n,m);
      if(!r){html+='<td class="hm-na">—</td>';continue;}
      const bg=errColor(r.error,minE,maxE);
      const isG=globalBest&&r.n===globalBest.n&&r.m===globalBest.m&&r.method===globalBest.method&&r.p===globalBest.p;
      const ck=cellKey(r);
      const pTag=r.method==='idw'?` p=${r.p}`:'';
      const mTag=tab==='best'?` [${mLabel(r,true)}]`:'';
      html+=`<td class="hm-cell${selectedCellKey===ck?' selected':''}${isG?' global-best':''}"
        style="background:${bg}"
        title="n=${n}h, m=${m}${mTag}${pTag}&#10;誤差: ${r.error.toFixed(3)} μg/m³&#10;補值: ${r.predicted.toFixed(2)}"
        data-n="${n}" data-m="${m}" data-method="${r.method}" data-p="${r.p??''}">${r.error.toFixed(1)}</td>`;
    }
    html+='</tr>';
  }
  html+='</tbody></table>';
  container.innerHTML=html;
  container.querySelectorAll('.hm-cell').forEach(addCellClick);
  // 點 row header → 只切換 lbN
  container.querySelectorAll('.hm-rh').forEach(th=>{
    th.addEventListener('click',()=>applyLbN(+th.dataset.n));
  });
}

function addCellClick(cell){
  cell.addEventListener('click',()=>{
    const n=+cell.dataset.n,m=+cell.dataset.m,method=cell.dataset.method;
    const p=cell.dataset.p?parseFloat(cell.dataset.p):null;
    const r=searchResults.find(x=>x.n===n&&x.m===m&&x.method===method&&x.p===p);
    if(!r)return;
    selectedCellKey=cellKey(r);
    // 重繪選中高亮
    document.querySelectorAll('.hm-cell').forEach(c=>{
      const cr=searchResults.find(x=>x.n===+c.dataset.n&&x.m===+c.dataset.m&&
        x.method===c.dataset.method&&x.p===(c.dataset.p?parseFloat(c.dataset.p):null));
      c.classList.toggle('selected',cr?cellKey(cr)===selectedCellKey:false);
    });
    applyLbN(n);
  });
}

/* ── 地圖 ── */
function renderMap(){
  const lbStep=Math.max(0,curStep-lbN);
  const target=searchTarget;

  let bestN=null, nbHighlight=new Set();
  if(searchResults.length&&target&&searchStep===curStep){
    if(selectedCellKey){
      const sel=searchResults.find(r=>cellKey(r)===selectedCellKey);
      bestN=sel&&sel.n===lbN?sel:getBestForN(lbN);
    } else {
      bestN=getBestForN(lbN);
    }
    if(bestN&&bestN.method!=='self'&&bestN.m>0){
      getNeighborsAtStep(target,bestN.m,lbStep).forEach(x=>nbHighlight.add(x.s.id));
    }
  }

  mkLayer.clearLayers();
  stations.forEach(s=>{
    const isTarget=target&&s.id===target.id;
    const isNb=nbHighlight.has(s.id);
    const displayStep=isTarget?curStep:lbStep;
    const val=tsData[s.name]?tsData[s.name][displayStep]:null;
    const color=pm25Color(val);
    const label=val!=null?Math.round(val):'–';

    let html;
    if(isTarget){
      html=`<div class="mk target-mk" style="background:${color};color:${lc(val)}"><span>${esc(label)}</span></div>`;
      if(bestN){
        html+=`<div class="mk-tag">&#8594; ${bestN.predicted.toFixed(1)}</div>`;
        html+=`<div class="mk-tag err">&#916;${bestN.error.toFixed(2)}</div>`;
      } else {
        html+=`<div class="mk-tag" style="background:#475569">目標站</div>`;
      }
    } else if(isNb){
      html=`<div class="mk nb-mk" style="background:${color};color:${lc(val)}"><span>${esc(label)}</span></div>`;
      if(lbN>0)html+=`<div class="mk-tag orange">${lbN}h前</div>`;
    } else {
      html=`<div class="mk dim-mk" style="background:${color};color:${lc(val)}"><span>${esc(label)}</span></div>`;
    }

    const icon=L.divIcon({className:'',iconSize:[34,34],iconAnchor:[17,17],html});
    const mk=L.marker([s.lat,s.lon],{icon}).addTo(mkLayer);
    let pop=`<div class="pt">${esc(s.name)}</div><div class="pg">`;
    pop+=`<div><span>${isNb&&lbN>0?`PM2.5（${lbN}h前）`:'PM2.5（當前）'}</span> ${val!=null?val+' μg/m³':'缺測'}</div>`;
    if(isTarget&&bestN){
      pop+=`<div><span>最優補值 @ n=${lbN}h</span> <strong style="color:var(--primary)">${bestN.predicted.toFixed(2)} μg/m³</strong></div>`;
      pop+=`<div><span>方法</span> ${mLabel(bestN,false)}</div>`;
      pop+=`<div><span>鄰站數</span> ${bestN.m>0?bestN.m:'— (self)'}</div>`;
      pop+=`<div><span>誤差</span> <strong>${bestN.error.toFixed(3)} μg/m³</strong></div>`;
    }
    pop+='</div>';
    mk.bindPopup(pop);
  });
}

/* ── 事件 ── */
el.slider.addEventListener('input',()=>applyStep(+el.slider.value));
el.prevBtn.addEventListener('click',()=>applyStep(curStep-1));
el.nextBtn.addEventListener('click',()=>applyStep(curStep+1));
el.mainPlayBtn.addEventListener('click',()=>{
  if(mainTimer){clearInterval(mainTimer);mainTimer=null;
    el.mainPlayBtn.classList.remove('playing');el.mainPlayBtn.innerHTML='&#9654;';return;}
  el.mainPlayBtn.classList.add('playing');el.mainPlayBtn.innerHTML='&#9646;&#9646;';
  mainTimer=setInterval(()=>{
    if(curStep>=_TD.n-1){clearInterval(mainTimer);mainTimer=null;
      el.mainPlayBtn.classList.remove('playing');el.mainPlayBtn.innerHTML='&#9654;';return;}
    applyStep(curStep+1);
  },+el.speedSel.value);
});
document.querySelectorAll('.mbtn').forEach(b=>{
  b.addEventListener('click',()=>{
    applyStep(+b.dataset.step);
    document.querySelectorAll('.mbtn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
  });
});

el.lbSlider.addEventListener('input',()=>applyLbN(+el.lbSlider.value));
el.lbPrevBtn.addEventListener('click',()=>applyLbN(lbN-1));
el.lbNextBtn.addEventListener('click',()=>applyLbN(lbN+1));
el.lbPlayBtn.addEventListener('click',()=>{
  if(lbTimer){clearInterval(lbTimer);lbTimer=null;
    el.lbPlayBtn.classList.remove('playing-lb');el.lbPlayBtn.innerHTML='&#9654;';return;}
  if(lbN>=24)applyLbN(0);
  el.lbPlayBtn.classList.add('playing-lb');el.lbPlayBtn.innerHTML='&#9646;&#9646;';
  lbTimer=setInterval(()=>{
    if(lbN>=24){clearInterval(lbTimer);lbTimer=null;
      el.lbPlayBtn.classList.remove('playing-lb');el.lbPlayBtn.innerHTML='&#9654;';return;}
    applyLbN(lbN+1);
  },+el.lbSpeedSel.value);
});

el.targetSel.addEventListener('change',()=>{
  searchTarget=stations.find(s=>s.id===el.targetSel.value)||null;
  searchResults=[];searchStep=-1;selectedCellKey=null;
  updateTargetInfo();renderBestBar(null);
  document.getElementById('mcWrap').style.display='none';
  document.getElementById('hmOuter').innerHTML=
    '<div class="hm-empty">按「搜索」後顯示熱力圖<br><small>橫軸 m，縱軸 n</small></div>';
  applyLbN(0);
});
el.searchBtn.addEventListener('click',()=>{
  el.searchBtn.disabled=true;el.searchBtn.textContent='計算中…';
  setTimeout(()=>{runSearch();el.searchBtn.disabled=false;el.searchBtn.innerHTML='&#9881; 搜索';},10);
});
document.querySelectorAll('.tab-btn').forEach(b=>{
  b.addEventListener('click',()=>renderHeatmap(b.dataset.tab));
});

/* ── 初始化 ── */
stations=_SD.map(s=>({...s}));corrMat=_CD;tsData=_TD.data;
el.slider.max=_TD.n-1;
const lats=stations.map(s=>s.lat),lons=stations.map(s=>s.lon);
map.fitBounds([[Math.min(...lats)-.06,Math.min(...lons)-.06],[Math.max(...lats)+.06,Math.max(...lons)+.06]]);
stations.forEach(s=>{
  const opt=document.createElement('option');opt.value=s.id;opt.textContent=s.name;
  el.targetSel.appendChild(opt);
});
searchTarget=stations[0];
applyStep(_TD.n-1);
setTimeout(()=>map.invalidateSize(),0);
  </script>
</body>
</html>"""

HTML = P1 + SJ + P2 + CJ + P3 + TJ + P4
out = work / "pm25_optimizer.html"
out.write_text(HTML, encoding="utf-8")
print(f"OK  {out}  ({out.stat().st_size//1024} KB)")
