# 智慧桿 PM2.5 風向儀表板

這個專案目前聚焦在 PM2.5 高峰事件、CWA 風向/風速、靜風條件與事件診斷。主畫面是地圖優先的風向疊圖儀表板。

## Quick Start

靜態頁可以直接用本機 HTTP server 開：

```powershell
python -m http.server 8080
```

然後打開：

```text
http://localhost:8080/dashboard_index.html
```

## Project Structure

- `dashboard_index.html` - 專案入口頁。
- `main/` - 目前主前端與前端載入資料。
- `main/wind_pm25_lag_dashboard.html` - 主儀表板。
- `main/css/` - 主儀表板樣式。
- `main/js/` - 主儀表板互動邏輯。
- `data/` - 可人工檢視或前處理使用的 JSON 資料。
- `CWA_Weather_Final/` - 原始 CWA 氣象 CSV。
- `docs/` - 專案文件、資料說明與 AI 協作模板。
- `legacy/` - 舊版靜態資料抓取工具，保留作參考，主儀表板不載入。
- `preprocess_wind_pm25.py` - 產生主儀表板資料的前處理腳本。

## Data Refresh

```powershell
python preprocess_wind_pm25.py
```

讀取：

- `data/timeseries_data.json`
- `main/peak_data.js`
- `CWA_Weather_Final/`

輸出：

- `main/wind_pm25_data.js`
- `main/event_diagnosis_data.js`

## Collaboration

多人用 AI 共同開發前，請先看：

- `docs/CONTRIBUTING.md`
- `docs/AI_TASK_TEMPLATE.md`

原則是小分支、小任務、明確指定 AI 可修改的檔案與函式，避免全檔重排和資料檔混入 UI PR。
