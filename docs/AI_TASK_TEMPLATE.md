# AI 任務說明模板

把下面整段貼給 AI，再依照實際任務調整。重點是先讓 AI 知道專案架構，再限制它這次可以改的範圍。

```text
你現在協助的是「智慧桿 PM2.5 與 CWA 風向/氣象資料儀表板」專案。

專案目標：
- 用前端儀表板檢視 PM2.5 高峰事件。
- 主軸是 CWA 風向、風速、靜風條件、PM2.5 測站，以及事件診斷。
- 目前主頁是地圖優先的風向疊圖與事件診斷 dashboard。

專案架構：
- dashboard_index.html
  - 專案入口頁，連到目前主儀表板。
- main/wind_pm25_lag_dashboard.html
  - 主儀表板 HTML 結構與控制元件。
- main/css/wind_pm25_lag_dashboard.css
  - 主儀表板樣式、地圖、面板、marker、圖表與 responsive layout。
- main/js/wind_pm25_lag_dashboard.js
  - 主儀表板互動邏輯、地圖渲染、風向 marker、事件列表、診斷表格、lag chart、polar plot。
- main/wind_pm25_data.js
  - 自動產生的風向/PM2.5 資料，不要手動修改。
- main/event_diagnosis_data.js
  - 自動產生的事件診斷資料，不要手動修改。
- main/peak_data.js
  - 前端讀取的高峰事件資料。
- data/
  - 可人工檢視或前處理使用的 JSON 資料，例如 data/timeseries_data.json、data/peak_hourly_clean.json。
- preprocess_wind_pm25.py
  - 產生 main/wind_pm25_data.js 與 main/event_diagnosis_data.js 的資料前處理腳本。
- CWA_Weather_Final/
  - 原始 CWA 氣象 CSV 資料，不要隨意修改。
- docs/DASHBOARDS.md、docs/DATA_CATALOG.md、docs/CONTRIBUTING.md
  - 儀表板、資料與共同開發說明。

這次任務目標：
- 

允許修改的檔案：
- 

不要修改的檔案：
- main/wind_pm25_data.js
- main/event_diagnosis_data.js
- data/
- CWA_Weather_Final/

開發限制：
- 不要重排整個檔案。
- 不要做與任務無關的重構。
- 不要改變資料格式，除非我明確要求。
- 如果需要新增檔案，請先說明檔名與用途。
- 修改前先確認目前檔案用途，避免破壞主儀表板入口。
- 只修改我列出的檔案、函式或區塊。
- 保留其他人的既有變更，不要回復或覆蓋無關程式碼。
- 如果發現必須修改未列入的檔案，先停止並說明原因。
- 讓 diff 盡量小，不要做全檔格式化。

完成後請回報：
- 修改了哪些檔案。
- 主要改了什麼。
- 修改了哪些函式或區塊。
- 是否有碰到資料檔或產生檔。
- 是否可能和其他人開發中的區塊衝突。
- 我該怎麼測試。
```

## Merge / PR 說明模板

開 PR 或請 AI 幫忙整理 merge 說明時，使用下面模板。

```text
請幫我整理這次前端修改的 merge 說明。

請依照這個格式輸出：

標題：
- 

修改摘要：
- 

影響範圍：
- 主儀表板：
- CSS：
- JS：
- 資料檔：
- 文件：

衝突風險：
- 是否改到共用 JS 檔：
- 是否改到共用 CSS 檔：
- 是否有全檔格式化：
- 是否需要等其他 PR 先合併：

測試方式：
- 打開 dashboard_index.html。
- 進入 main/wind_pm25_lag_dashboard.html。
- 確認地圖、PM marker、CWA 風向 marker 顯示正常。
- 確認事件切換、lag slider、時間 offset slider 可操作。
- 確認瀏覽器 console 沒有明顯錯誤。

合併注意事項：
- 是否修改自動產生資料檔：
- 是否需要重新執行 preprocess_wind_pm25.py：
- 是否可能影響主儀表板入口：
- 是否有需要 reviewer 特別看的地方：
```

## 同時開發時給 AI 的補充指令

多人同時開發時，請在任務模板後面追加這段：

```text
這是多人共同開發分支。請特別注意：

- 只處理這次任務指定的區塊。
- 不要重排或清理未指定區塊。
- 不要改動其他人可能正在處理的功能。
- 如果你需要修改 main/js/wind_pm25_lag_dashboard.js，請只改指定函式，並在回覆列出函式名稱。
- 如果你需要修改 main/css/wind_pm25_lag_dashboard.css，請只改指定 selector 或新增任務專用 selector。
- 不要修改自動產生資料檔。
- 完成後請列出可能的 merge 衝突風險。
```

## 範例：只改地圖

```text
這次任務目標：
- 改善風向 marker 的視覺層級，讓靜風與有效風向更容易區分。

允許修改的檔案：
- main/js/wind_pm25_lag_dashboard.js
- main/css/wind_pm25_lag_dashboard.css

不要修改的檔案：
- main/wind_pm25_data.js
- main/event_diagnosis_data.js
- preprocess_wind_pm25.py
- 其他 HTML 頁面
```

## 範例：只改事件面板

```text
這次任務目標：
- 讓事件列表更容易掃描，顯示日期、峰值小時、事件分類。

允許修改的檔案：
- main/wind_pm25_lag_dashboard.html
- main/js/wind_pm25_lag_dashboard.js
- main/css/wind_pm25_lag_dashboard.css

不要修改的檔案：
- main/wind_pm25_data.js
- main/event_diagnosis_data.js
- preprocess_wind_pm25.py

開發限制：
- 不要改地圖邏輯。
- 不要改資料產生腳本。
```
