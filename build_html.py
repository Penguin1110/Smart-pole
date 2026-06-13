"""產生 work/pm25_imputation.html，將三份 JSON 直接內嵌。"""
import json, pathlib

work = pathlib.Path(__file__).parent / "work"

stations_raw = json.loads((work / "stations.json").read_text(encoding="utf-8"))
corr_raw     = json.loads((work / "correlations.json").read_text(encoding="utf-8"))
ts_raw       = json.loads((work / "pm25_timeseries.json").read_text(encoding="utf-8"))

SJ = json.dumps(stations_raw, ensure_ascii=False, separators=(',', ':'))
CJ = json.dumps(corr_raw,     ensure_ascii=False, separators=(',', ':'))
TJ = json.dumps(ts_raw,       ensure_ascii=False, separators=(',', ':'))

HTML = """\
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>高雄 PM2.5 補值模擬系統</title>
  <link rel="preconnect" href="https://unpkg.com"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    :root{
      --bg:#f4f7fb;--panel:#fff;--text:#16202b;--muted:#5f6b7a;
      --border:#d9e2ec;--shadow:0 10px 30px rgba(22,32,43,.08);
      --good:#2e7d32;--moderate:#f9a825;--ufs:#ef6c00;
      --unhealthy:#c62828;--vu:#6a1b9a;--haz:#4e342e;
      --selected:#1e66d0;--primary:#1e66d0;
    }
    *{box-sizing:border-box}
    html,body{height:100%;margin:0;font-family:Inter,"Noto Sans TC",system-ui,sans-serif;color:var(--text);background:var(--bg)}
    body{padding:14px}

    .page-header{background:var(--panel);border:1px solid var(--border);border-radius:12px;
      box-shadow:var(--shadow);padding:12px 16px;margin-bottom:10px;display:grid;gap:4px}
    .page-header h1{margin:0;font-size:19px}
    .page-header p{margin:0;color:var(--muted);font-size:12px;line-height:1.6}

    /* ── 時間列 ── */
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
    #timeSlider{flex:1;min-width:200px;accent-color:var(--primary)}
    .speed-sel{height:30px;border:1px solid var(--border);border-radius:7px;padding:0 6px;
      font:inherit;font-size:11px;background:#fff;color:var(--text)}
    .month-btns{display:flex;gap:5px;align-items:center}
    .month-btns span{font-size:11px;color:var(--muted)}
    .mbtn{padding:3px 9px;border:1px solid var(--border);border-radius:6px;background:#fff;
      font:inherit;font-size:11px;cursor:pointer;transition:all .15s}
    .mbtn.active,.mbtn:hover{background:var(--primary);border-color:var(--primary);color:#fff}

    /* ── 主版 ── */
    .app{min-height:calc(100vh - 210px);display:grid;grid-template-columns:1fr 430px;gap:12px}
    .panel{background:var(--panel);border:1px solid var(--border);border-radius:12px;
      box-shadow:var(--shadow);overflow:hidden;min-height:0}
    #map{width:100%;height:100%;min-height:460px;background:#dbeafe}

    .sidebar{display:grid;grid-template-rows:auto auto auto auto 1fr;min-width:0;overflow:hidden}

    /* 公式說明區 — 限高 + 捲動，避免撐爆 sidebar */
    .formula-panel{padding:10px 13px;border-bottom:1px solid var(--border);
      display:grid;gap:6px;max-height:220px;overflow-y:auto}
    .fp-title{font-size:12px;font-weight:700;color:var(--text);margin-bottom:2px}
    .fp-card{background:#f8fbff;border:1px solid var(--border);border-radius:7px;padding:7px 10px;display:grid;gap:3px}
    .fp-card.active{border-color:var(--primary);background:#eff6ff}
    .fp-name{font-size:11px;font-weight:700;color:var(--primary)}
    .fp-eq{font-family:"Courier New",monospace;font-size:11px;color:#1a4a7a;
      background:#e8f4fd;border-radius:5px;padding:3px 7px;line-height:1.6;
      overflow-x:auto;white-space:pre;max-width:100%}
    .fp-desc{font-size:10px;color:var(--muted);line-height:1.5}

    /* 控制 */
    .controls{padding:11px 13px;border-bottom:1px solid var(--border);display:grid;gap:7px;
      background:linear-gradient(180deg,#fbfdff,#f8fbff)}
    .controls h2{margin:0 0 1px;font-size:13px}
    .controls p{margin:0;font-size:11px;color:var(--muted)}
    .field{display:grid;gap:3px}
    .field label{font-size:11px;color:var(--muted);font-weight:500}
    .field select,.field input{width:100%;height:33px;border-radius:8px;border:1px solid var(--border);
      padding:0 9px;font:inherit;color:var(--text);background:#fff;outline:none}
    .field select:focus,.field input:focus{border-color:#7aa7d9;box-shadow:0 0 0 3px rgba(122,167,217,.18)}
    .row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
    .btn{height:33px;border:1px solid var(--border);border-radius:8px;padding:0 12px;
      background:#fff;color:var(--text);font:inherit;cursor:pointer;transition:all .2s}
    .btn.primary{background:var(--primary);border-color:var(--primary);color:#fff}
    .btn.primary:hover:not(:disabled){background:#1557b8}
    .btn:disabled{opacity:.5;cursor:not-allowed}
    .formula-box{background:#f0f7ff;border:1px solid #c2d9f0;border-radius:8px;
      padding:6px 9px;font-size:11px;color:#1a4a7a;line-height:1.6}

    /* MAE */
    .mae-sec{padding:11px 13px;border-bottom:1px solid var(--border);display:grid;gap:7px}
    .mae-hd{display:flex;justify-content:space-between;align-items:baseline}
    .mae-title{font-size:12px;font-weight:600}
    .mae-num{font-size:20px;font-weight:800;color:var(--primary)}
    .mae-bar-wrap{position:relative;height:20px}
    .mae-bar-bg{position:absolute;width:100%;height:100%;border-radius:10px;
      background:linear-gradient(90deg,#2e7d32 0%,#7cb342 25%,#f9a825 50%,#ef6c00 75%,#c62828 100%);
      border:1px solid var(--border)}
    .mae-ptr{position:absolute;top:50%;left:0%;transform:translate(-50%,-50%);pointer-events:none;transition:left .3s}
    .mae-ptr::before{content:"";position:absolute;left:50%;bottom:10px;transform:translateX(-50%);
      border-left:6px solid transparent;border-right:6px solid transparent;border-top:9px solid #111}
    .mae-ptr::after{content:"";position:absolute;left:50%;top:8px;transform:translateX(-50%);
      width:2px;height:16px;background:#111;border-radius:999px}
    .mae-scale{display:flex;justify-content:space-between;font-size:10px;color:var(--muted)}
    .mcards{display:grid;gap:5px}
    .mcard{background:#f8fbff;border:1px solid var(--border);border-radius:7px;padding:6px 9px;display:grid;gap:3px}
    .mcard.active{border:2px solid var(--primary);background:#eff6ff}
    .mcard-hd{display:flex;justify-content:space-between;align-items:baseline;gap:6px}
    .mcard-name{font-size:11px;font-weight:600}
    .mcard-mae{font-size:14px;font-weight:800;color:var(--primary)}
    .mbar{position:relative;height:3px;border-radius:999px;background:#e5e7eb;overflow:hidden}
    .mfill{position:absolute;top:0;left:0;height:100%;
      background:linear-gradient(90deg,#2e7d32,#f9a825,#ef6c00,#c62828);border-radius:999px;transition:width .3s}
    .mcard-desc{font-size:10px;color:var(--muted)}

    /* 圖例 */
    .legend{padding:7px 13px;display:flex;flex-wrap:wrap;gap:5px;border-bottom:1px solid var(--border)}
    .li{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border:1px solid var(--border);
      border-radius:999px;font-size:11px;color:var(--muted);background:#fff}
    .sw{width:8px;height:8px;border-radius:50%;display:inline-block}

    /* 清單 */
    .list{overflow:auto;min-height:0}
    table{width:100%;border-collapse:collapse;table-layout:fixed}
    thead th{position:sticky;top:0;background:#f8fbff;z-index:1;text-align:left;
      font-size:11px;color:var(--muted);padding:7px 11px;border-bottom:1px solid var(--border)}
    tbody td{padding:8px 11px;border-bottom:1px solid #eef2f7;font-size:12px;
      vertical-align:middle;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    tbody tr{cursor:pointer;transition:background .15s}
    tbody tr:hover{background:#f8fbff}
    tbody tr.selected{background:#e3f2fd}
    .pill{display:inline-flex;align-items:center;justify-content:center;
      min-width:38px;height:24px;padding:0 7px;border-radius:999px;color:#fff;font-weight:700;font-size:11px}

    /* 地圖標記 */
    .mk{width:34px;height:34px;border-radius:50%;border:2px solid rgba(255,255,255,.96);
      box-shadow:0 2px 8px rgba(0,0,0,.18);display:grid;place-items:center;
      color:#fff;font-size:11px;font-weight:800;transform:translate(-50%,-50%);
      cursor:pointer;transition:transform .2s}
    .mk:hover{transform:translate(-50%,-50%) scale(1.15)}
    .mk.sel{border-color:rgba(30,102,208,1);box-shadow:0 0 0 3px rgba(30,102,208,.3),0 2px 8px rgba(0,0,0,.18)}
    /* 補值 tag：顯示在標記正下方 */
    .mk-imp{position:absolute;top:38px;left:50%;transform:translateX(-50%);
      background:var(--primary);color:#fff;font-size:9px;font-weight:700;
      padding:2px 6px;border-radius:4px;white-space:nowrap;
      box-shadow:0 1px 3px rgba(0,0,0,.3);pointer-events:none;line-height:1.4}
    .mk-imp .arr{opacity:.7}
    /* 方法 tag：顯示在補值 tag 下方 */
    .mk-method{position:absolute;top:56px;left:50%;transform:translateX(-50%);
      background:#fff;color:var(--primary);border:1px solid var(--primary);
      font-size:8px;font-weight:700;padding:1px 5px;border-radius:4px;
      white-space:nowrap;pointer-events:none}
    .leaflet-popup-content{margin:10px 12px;font:inherit;line-height:1.5}
    .pt{font-size:14px;font-weight:700;margin-bottom:3px}
    .pg{display:grid;gap:2px;font-size:12px}
    .pg span{color:var(--muted)}

    @media(max-width:1100px){.app{grid-template-columns:1fr}#map{min-height:380px}}
  </style>
</head>
<body>
  <header class="page-header">
    <h1>高雄市 PM2.5 補值方法互動實驗平台</h1>
    <p>MOENV 環境部 12 個高雄 TAQM 測站 · 2025/12/01–2026/02/28 · 共 2160 小時。
       <strong>拖動時間軸</strong>切換觀測時刻；點擊地圖測站選為「待補值」，再按「計算補值」比較各方法。</p>
  </header>

  <!-- 時間列 -->
  <div class="time-bar">
    <div class="time-top">
      <div>
        <div class="time-label" id="timeLabel">—</div>
        <div class="time-sub"  id="timeSub">—</div>
      </div>
      <div class="month-btns">
        <span>快速跳至：</span>
        <button class="mbtn" data-step="0">12月</button>
        <button class="mbtn" data-step="744">1月</button>
        <button class="mbtn" data-step="1488">2月</button>
      </div>
    </div>
    <div class="time-row">
      <button class="btn-icon" id="prevBtn" title="上一小時">&#9664;</button>
      <button class="btn-icon" id="playBtn" title="播放">&#9654;</button>
      <button class="btn-icon" id="nextBtn" title="下一小時">&#9654;</button>
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
      <!-- 設定 -->
      <div class="controls">
        <div><h2>補值設定</h2><p>點擊測站標記為「待補值」，其他站作為鄰站來源</p></div>
        <div class="field">
          <label for="methodSel">補值方法</label>
          <select id="methodSel">
            <option value="mean">均值補值（Mean）</option>
            <option value="idw" selected>距離加權（IDW）</option>
            <option value="corr">相關性加權（Corr-Weighted）</option>
            <option value="ridge">Ridge 回歸</option>
          </select>
        </div>
        <div class="row2">
          <div class="field"><label for="kVal">鄰站數 K</label>
            <input id="kVal" type="number" min="1" max="11" value="5"/></div>
          <div class="field"><label for="pVal">IDW 冪次 p</label>
            <input id="pVal" type="number" min="0.5" max="5" step="0.5" value="2"/></div>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn primary" id="calcBtn" disabled style="flex:1">計算補值</button>
          <button class="btn" id="resetBtn">重設</button>
        </div>
        <div class="formula-box" id="fBox"></div>
      </div>
      <!-- MAE -->
      <div class="mae-sec">
        <div class="mae-hd">
          <span class="mae-title">MAE 光譜（當前方法）</span>
          <span class="mae-num" id="maeNum">--</span>
        </div>
        <div class="mae-bar-wrap"><div class="mae-bar-bg"></div><div class="mae-ptr" id="maePtr"></div></div>
        <div class="mae-scale"><span>0</span><span>5</span><span>10</span><span>15</span><span>≥20</span></div>
        <div class="mcards" id="mcards">
          <div style="font-size:11px;color:var(--muted);text-align:center;padding:4px 0">選擇測站後按「計算補值」</div>
        </div>
      </div>
      <!-- 公式說明 -->
      <div class="formula-panel" id="fPanel"></div>

      <!-- 圖例 -->
      <div class="legend">
        <div class="li"><span class="sw" style="background:var(--good)"></span>0–35 良好</div>
        <div class="li"><span class="sw" style="background:var(--moderate)"></span>36–53 普通</div>
        <div class="li"><span class="sw" style="background:var(--ufs)"></span>54–70 敏感</div>
        <div class="li"><span class="sw" style="background:var(--unhealthy)"></span>≥71 不健康</div>
        <div class="li"><span class="sw" style="background:var(--selected)"></span>待補值</div>
      </div>
      <!-- 清單 -->
      <div class="list" id="list"></div>
    </aside>
  </main>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
/* ── 內嵌資料 ── */
const _SD=""" + SJ + """;
const _CD=""" + CJ + """;
const _TD=""" + TJ + """;

/* ── 狀態 ── */
let stations=[], corrMat={}, tsData={};
let curStep=0, imputed={}, playTimer=null, autoCalc=false;

const el={
  methodSel:document.getElementById('methodSel'),
  kVal:document.getElementById('kVal'),
  pVal:document.getElementById('pVal'),
  calcBtn:document.getElementById('calcBtn'),
  resetBtn:document.getElementById('resetBtn'),
  maeNum:document.getElementById('maeNum'),
  maePtr:document.getElementById('maePtr'),
  mcards:document.getElementById('mcards'),
  fBox:document.getElementById('fBox'),
  list:document.getElementById('list'),
  slider:document.getElementById('timeSlider'),
  timeLabel:document.getElementById('timeLabel'),
  timeSub:document.getElementById('timeSub'),
  playBtn:document.getElementById('playBtn'),
  prevBtn:document.getElementById('prevBtn'),
  nextBtn:document.getElementById('nextBtn'),
  speedSel:document.getElementById('speedSel'),
};

/* ── 地圖 ── */
const map=L.map('map',{zoomControl:true,preferCanvas:true,minZoom:9}).setView([22.65,120.35],11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
const mkLayer=L.layerGroup().addTo(map);

/* ── 工具 ── */
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const css=k=>getComputedStyle(document.documentElement).getPropertyValue(k).trim();

function pm25Color(v){
  if(v==null)return '#64748b';
  if(v<=35) return css('--good');
  if(v<=53) return css('--moderate');
  if(v<=70) return css('--ufs');
  if(v<=150)return css('--unhealthy');
  if(v<=250)return css('--vu');
  return css('--haz');
}
function lc(v){return(v!=null&&v<=53)?'#111827':'#fff'}

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

/* ── 時間 ── */
function stepToDate(s){return new Date(new Date('2025-12-01T00:00:00').getTime()+s*3600000)}
function fmtDate(d){const p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:00`}

function applyStep(step){
  curStep=Math.max(0,Math.min(_TD.n-1,step));
  el.slider.value=curStep;
  const d=stepToDate(curStep);
  el.timeLabel.textContent=fmtDate(d);
  el.timeSub.textContent=`第 ${curStep+1} / ${_TD.n} 小時`;
  /* 從時序更新各站 PM2.5 */
  for(const s of stations){
    const arr=tsData[s.name];
    s.pm25=arr?arr[curStep]:null;
    s.aqi=pm25ToAqi(s.pm25);
  }
  if(autoCalc)recalc();
  else{imputed={};renderMAE();}
  renderAll();
}

/* ── 補值 ── */
function neighbors(target,k){
  return stations
    .filter(s=>s.id!==target.id&&s.pm25!=null)
    .map(s=>({s,d:haversine(target.lat,target.lon,s.lat,s.lon)}))
    .sort((a,b)=>a.d-b.d).slice(0,k);
}
function wMean(nb,wfn){
  let n=0,den=0;
  for(const x of nb){if(x.s.pm25==null)continue;const w=wfn(x);n+=w*x.s.pm25;den+=w}
  return den>0?n/den:null;
}
function imputeMean(nb){const v=nb.map(x=>x.s.pm25).filter(x=>x!=null);return v.length?v.reduce((a,b)=>a+b,0)/v.length:null}
function imputeIDW(nb,p){return wMean(nb,x=>1/Math.pow(x.d+0.01,p))}
function imputeCorr(target,nb){
  const ni=corrMat.stations,mx=corrMat.matrix,ti=ni.indexOf(target.name);
  if(ti===-1)return imputeIDW(nb,2);
  return wMean(nb,x=>{const i=ni.indexOf(x.s.name);return i!==-1?Math.max(0,mx[ti][i]):0});
}
function gaussJordan(A,n){
  const M=A.map(r=>[...r]);
  for(let c=0;c<n;c++){
    let pv=-1;for(let r=c;r<n;r++)if(Math.abs(M[r][c])>1e-10){pv=r;break}
    if(pv===-1)return null;[M[c],M[pv]]=[M[pv],M[c]];
    const sc=M[c][c];for(let j=c;j<=n;j++)M[c][j]/=sc;
    for(let r=0;r<n;r++){if(r===c)continue;const f=M[r][c];for(let j=c;j<=n;j++)M[r][j]-=f*M[c][j]}
  }
  return M.map(r=>r[n]);
}
function imputeRidge(target,nb,a=0.1){
  const ni=corrMat.stations,mx=corrMat.matrix,K=nb.length;if(!K)return null;
  const ti=ni.indexOf(target.name);if(ti===-1)return imputeCorr(target,nb);
  const G=nb.map((_,i)=>nb.map((_,j)=>{const ii=ni.indexOf(nb[i].s.name),jj=ni.indexOf(nb[j].s.name);return(ii!==-1&&jj!==-1)?mx[ii][jj]:(i===j?1:0)}));
  const c=nb.map(x=>{const i=ni.indexOf(x.s.name);return i!==-1?Math.max(0,mx[ti][i]):0});
  const Aug=G.map((row,i)=>[...row.map((v,j)=>v+(i===j?a:0)),c[i]]);
  const sol=gaussJordan(Aug,K);if(!sol)return imputeCorr(target,nb);
  const w=sol.map(v=>Math.max(0,v)),ws=w.reduce((a,b)=>a+b,0);
  if(!ws)return imputeMean(nb);
  return nb.reduce((s,x,i)=>s+(x.s.pm25!=null?(w[i]/ws)*x.s.pm25:0),0);
}
function doImpute(target,method,k,p){
  const nb=neighbors(target,k);
  switch(method){case'mean':return imputeMean(nb);case'idw':return imputeIDW(nb,p);
    case'corr':return imputeCorr(target,nb);case'ridge':return imputeRidge(target,nb);default:return imputeMean(nb)}
}
function recalc(){
  const method=el.methodSel.value,k=+el.kVal.value,p=+el.pVal.value;
  imputed={};
  for(const s of stations.filter(s=>s.selected)){const v=doImpute(s,method,k,p);if(v!=null)imputed[s.id]=v}
}

/* ── 公式說明 ── */
const METHODS_DEF=[
  {id:'mean', name:'均值補值（Mean）',
   eq:'PM&#x0302; = (1/K) &Sigma;&#x1D62; nb&#x1D62;',
   desc:'取距離最近的 K 個鄰站 PM2.5 算術平均。最簡單的基線方法（Tier-1 Baseline）。'},
  {id:'idw',  name:'距離加權（IDW）',
   eq:'PM&#x0302; = &Sigma;&#x1D62; w&#x1D62;&middot;nb&#x1D62; / &Sigma;&#x1D62; w&#x1D62;<br>w&#x1D62; = 1 / (d&#x1D62; + &epsilon;)&#x1D56;',
   desc:'距離 dᵢ 越近，權重越大。ε = 0.01 km 防零距離；冪次 p 可調（預設 p = 2）。（Tier-2）'},
  {id:'corr', name:'相關性加權（Corr-Weighted）',
   eq:'PM&#x0302; = &Sigma;&#x1D62; w&#x1D62;&middot;nb&#x1D62; / &Sigma;&#x1D62; w&#x1D62;<br>w&#x1D62; = max(0, r(nb&#x1D62;, target))',
   desc:'以鄰站與目標站的 Pearson 相關係數為權重；負相關站權重設為 0。權重來自 2025/12–2026/02 歷史資料。（Tier-2）'},
  {id:'ridge', name:'Ridge 回歸',
   eq:'min &Vert;y &minus; Xw&Vert;&sup2; + &alpha;&Vert;w&Vert;&sup2; (&alpha;=0.1)<br>&rarr; w = (G + &alpha;I)&#x207B;&sup1; c<br>G&#x1D62;&#x2C7C; = r(nb&#x1D62;, nb&#x2C7C;), c&#x1D62; = max(0, r(nb&#x1D62;, target))',
   desc:'L2 正則化線性回歸；以相關係數矩陣近似 Gram 矩陣 G，Gauss-Jordan 解析求解。非負約束後正規化。（Tier-2）'},
];

function renderFormulas(){
  const active=el.methodSel.value;
  const panel=document.getElementById('fPanel');
  panel.innerHTML='<div class="fp-title">補值公式說明</div>'+
    METHODS_DEF.map(m=>`
      <div class="fp-card ${m.id===active?'active':''}">
        <div class="fp-name">${m.id===active?'▶ ':''} ${m.name}</div>
        <div class="fp-eq">${m.eq}</div>
        <div class="fp-desc">${m.desc}</div>
      </div>`).join('');
}
function updateFmt(){
  el.fBox.innerHTML='';   // 小框不再需要，保留 div 但清空
  renderFormulas();
}

/* ── 渲染工具 ── */
/* 地圖標記顏色：永遠基於原始 PM2.5；選中站加藍色 border（靠 CSS .sel） */
function markerColor(s){ return pm25Color(s.pm25) }

function renderMarkers(){
  mkLayer.clearLayers();
  const method=el.methodSel.value;
  const MLABEL={mean:'均值',idw:'IDW',corr:'Corr',ridge:'Ridge'};
  stations.forEach(s=>{
    const orig=s.pm25;           // 永遠顯示原始值
    const imp=imputed[s.id]??null;
    const color=markerColor(s);
    const label=orig!=null?Math.round(orig):'–';
    const lcolor=lc(orig);
    /* 標記 HTML：原始值圓 + 補值 tag（若已補值） + 方法 tag */
    let html=`<div class="mk ${s.selected?'sel':''}" style="background:${color};color:${lcolor}"><span>${esc(label)}</span></div>`;
    if(s.selected&&imp!=null){
      html+=`<div class="mk-imp"><span class="arr">→</span> ${imp.toFixed(1)}</div>`;
      html+=`<div class="mk-method">${esc(MLABEL[method])}</div>`;
    } else if(s.selected){
      html+=`<div class="mk-imp" style="background:#94a3b8">待補值</div>`;
    }
    /* iconSize 固定 34×34；tag 用 position:absolute 往下延伸，不影響 Leaflet 錨點 */
    const icon=L.divIcon({className:'',iconSize:[34,34],iconAnchor:[17,17],html});
    const mk=L.marker([s.lat,s.lon],{icon}).addTo(mkLayer);
    /* popup */
    const aqi=s.aqi;
    const impAqi=imp!=null?pm25ToAqi(imp):null;
    mk.bindPopup(
      `<div class="pt">${esc(s.name)}</div><div class="pg">`+
      `<div><span>時間</span> ${esc(el.timeLabel.textContent)}</div>`+
      `<div><span>原始 PM2.5</span> ${orig!=null?orig+' μg/m³':'缺測'}</div>`+
      `<div><span>原始 AQI</span> ${esc(aqi??'—')}</div>`+
      (s.selected&&imp!=null?
        `<div style="grid-column:1/-1;padding:4px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);margin:3px 0">`+
        `<span>補值結果</span> <strong style="color:var(--primary)">${imp.toFixed(2)} μg/m³</strong>　`+
        `AQI ${esc(impAqi??'—')}</div>`+
        (orig!=null?`<div><span>誤差</span> <strong>${Math.abs(orig-imp).toFixed(2)} μg/m³</strong></div>`:'')+
        `<div><span>方法</span> ${esc(MLABEL[method])}</div>`:'')+
      `<div style="margin-top:3px;padding-top:3px;border-top:1px solid var(--border);font-size:10px;color:var(--muted)">`+
      `${s.selected?'點擊取消選取':'點擊選為待補值'}</div></div>`
    );
    mk.on('click',e=>{L.DomEvent.stopPropagation(e);toggle(s.id)});
  });
}

function renderTable(){
  const sorted=[...stations].sort((a,b)=>{
    if(a.selected!==b.selected)return a.selected?-1:1;
    return(b.pm25??-1)-(a.pm25??-1);
  });
  const rows=sorted.map(s=>{
    const orig=s.pm25;
    const imp=imputed[s.id]??null;
    /* AQI pill 永遠基於原始值；選中站加藍色邊框 */
    const pillBg=pm25Color(orig);
    const pillStyle=s.selected
      ?`background:${pillBg};outline:2px solid var(--primary);outline-offset:1px`
      :`background:${pillBg}`;
    /* 原始值欄 */
    const origCell=orig!=null
      ?`${orig} <small style="color:var(--muted)">μg/m³</small>`
      :`<span style="color:var(--muted)">缺測</span>`;
    /* 補值欄：只對選中站顯示 */
    let impCell='<span style="color:#cbd5e1">—</span>';
    if(s.selected){
      if(imp!=null){
        const diff=orig!=null?Math.abs(orig-imp):null;
        const diffColor=diff!=null&&diff<3?'#2e7d32':diff!=null&&diff<6?'#f9a825':'#c62828';
        impCell=`<strong style="color:var(--primary)">${imp.toFixed(1)}</strong>`+
                (diff!=null?` <small style="color:${diffColor}">Δ${diff.toFixed(1)}</small>`:'');
      } else {
        impCell=`<span style="color:var(--selected);font-size:11px">待計算</span>`;
      }
    }
    return `<tr data-id="${esc(s.id)}" class="${s.selected?'selected':''}">
      <td>${esc(s.name)}</td>
      <td><span class="pill" style="${pillStyle}">${esc(s.aqi??'–')}</span></td>
      <td>${origCell}</td>
      <td>${impCell}</td></tr>`;
  }).join('');
  el.list.innerHTML=`<table><thead><tr><th>測站</th><th>AQI</th><th>原始值</th><th>補值</th></tr></thead><tbody>${rows}</tbody></table>`;
  el.list.querySelectorAll('tbody tr').forEach(tr=>tr.addEventListener('click',()=>toggle(tr.dataset.id)));
}

function renderMAE(){
  const sel=stations.filter(s=>s.selected);
  if(!sel.length||!Object.keys(imputed).length){
    el.maeNum.textContent='--';el.maePtr.style.left='0%';
    el.mcards.innerHTML=`<div style="font-size:11px;color:var(--muted);text-align:center;padding:4px 0">選擇測站後按「計算補值」</div>`;
    return;
  }
  const method=el.methodSel.value,k=+el.kVal.value,p=+el.pVal.value;
  const methods=[
    {id:'mean',label:'均值補值',desc:`K=${k}`},
    {id:'idw',label:'IDW',desc:`K=${k}, p=${p}`},
    {id:'corr',label:'相關性加權',desc:`K=${k}`},
    {id:'ridge',label:'Ridge',desc:`K=${k}, α=0.1`},
  ];
  const res=methods.map(m=>{
    let err=0,cnt=0;
    for(const s of sel){
      if(s.pm25==null)continue;
      const v=doImpute(s,m.id,k,p);
      if(v!=null){err+=Math.abs(s.pm25-v);cnt++}
    }
    return{...m,mae:cnt?err/cnt:null};
  }).filter(r=>r.mae!=null);
  const cur=res.find(r=>r.id===method);
  if(cur){el.maeNum.textContent=cur.mae.toFixed(2);el.maePtr.style.left=`${Math.min(100,cur.mae/20*100)}%`}
  const maxM=Math.max(...res.map(r=>r.mae),1);
  const medals=['🥇','🥈','🥉',''];
  el.mcards.innerHTML=[...res].sort((a,b)=>a.mae-b.mae).map((r,i)=>
    `<div class="mcard ${r.id===method?'active':''}">
      <div class="mcard-hd"><span class="mcard-name">${medals[i]||''} ${esc(r.label)} ${r.id===method?'(使用中)':''}</span>
      <span class="mcard-mae">${r.mae.toFixed(2)}</span></div>
      <div class="mbar"><div class="mfill" style="width:${(r.mae/maxM*100).toFixed(1)}%"></div></div>
      <div class="mcard-desc">${esc(r.desc)}</div></div>`
  ).join('');
}

function renderAll(){renderMarkers();renderTable()}

function toggle(id){
  const s=stations.find(s=>s.id===id);if(!s)return;
  s.selected=!s.selected;imputed={};autoCalc=false;
  el.calcBtn.disabled=stations.every(s=>!s.selected);
  renderMAE();renderAll();
}

/* ── 事件 ── */
el.slider.addEventListener('input',()=>applyStep(+el.slider.value));
el.prevBtn.addEventListener('click',()=>applyStep(curStep-1));
el.nextBtn.addEventListener('click',()=>applyStep(curStep+1));
el.playBtn.addEventListener('click',()=>{
  if(playTimer){clearInterval(playTimer);playTimer=null;el.playBtn.classList.remove('playing');el.playBtn.innerHTML='&#9654;';return}
  el.playBtn.classList.add('playing');el.playBtn.innerHTML='&#9646;&#9646;';
  playTimer=setInterval(()=>{
    if(curStep>=_TD.n-1){clearInterval(playTimer);playTimer=null;el.playBtn.classList.remove('playing');el.playBtn.innerHTML='&#9654;';return}
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
el.calcBtn.addEventListener('click',()=>{recalc();autoCalc=true;renderMAE();renderAll()});
el.resetBtn.addEventListener('click',()=>{
  stations.forEach(s=>s.selected=false);imputed={};autoCalc=false;
  el.calcBtn.disabled=true;renderMAE();renderAll();
});
el.methodSel.addEventListener('change',()=>{if(autoCalc)recalc();renderAll();renderMAE();renderFormulas()});
el.kVal.addEventListener('change',()=>{if(autoCalc)recalc();renderAll();renderMAE()});
el.pVal.addEventListener('change',()=>{if(autoCalc)recalc();renderAll();renderMAE()});

/* ── 初始化 ── */
stations  = _SD.map(s=>({...s,selected:false}));
corrMat   = _CD;
tsData    = _TD.data;

el.slider.max=_TD.n-1;
const lats=stations.map(s=>s.lat),lons=stations.map(s=>s.lon);
map.fitBounds([[Math.min(...lats)-.06,Math.min(...lons)-.06],[Math.max(...lats)+.06,Math.max(...lons)+.06]]);
updateFmt();
applyStep(_TD.n-1);   // 預設最後時刻
setTimeout(()=>map.invalidateSize(),0); // layout 穩定後重算地圖尺寸
  </script>
</body>
</html>
"""

out = work / "pm25_imputation.html"
out.write_text(HTML, encoding="utf-8")
print(f"OK  {out}  ({out.stat().st_size//1024} KB)")
