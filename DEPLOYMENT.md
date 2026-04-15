# 智慧桿靜態整合儀表板

## 已新增檔案

- `integrated_dashboard.html`: 靜態整合版儀表板
- `integrated_dashboard.css`: 版面與響應式樣式
- `integrated_dashboard.js`: 畫面初始化、圖表與資料綁定
- `smartpole_static_data.js`: 靜態氣象/污染物/時間/空間特徵產生器
- `dataFetcher.js`: 可切換 static / live 的整合抓取器
- `test_apis.html`: API 測試頁

## 本地啟動

因為 `integrated_dashboard.html` 會讀取 `timeseries_data.json`，請不要直接用 `file://` 開啟。

可用任一靜態伺服器，例如：

```powershell
python -m http.server 8080
```

之後開啟：

```text
http://localhost:8080/integrated_dashboard.html
```

## 如何切到真實 API

1. 打開 [dataFetcher.js](/c:/Users/admin/Desktop/智慧桿/dataFetcher.js:1)
2. 建立 `new SmartPoleDataFetcher({ mode: 'live', cwaApiKey: '...', epaApiKey: '...' })`
3. 補上 CORS 解法
4. 以真實 API 回傳取代目前 `static-fixture`

## 目前資料策略

- PM2.5: 直接使用 `timeseries_data.json`
- 氣象欄位: 依時間、季節、PM2.5 與站點 profile 產生靜態展示值
- 其他污染物: 依 PM2.5 與鄰近站點濃度推估展示值
- 時間特徵: 由 timestamp 即時計算
- 空間特徵: 由站點對應表與既有鄰近測站欄位組成

## 建議下一步

1. 先用 `test_apis.html` 驗證 CWA / EPA key
2. 把 `mode: 'static'` 切成 `mode: 'live'`
3. 若正式上線，新增後端 proxy 避免瀏覽器暴露 API key
