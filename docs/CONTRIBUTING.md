# 共同開發規則

這個專案目前以前端儀表板與氣象/PM2.5 資料為主。多人使用 AI 修改時，請用小分支、小任務、明確檔案邊界來避免互相覆蓋。

## 專案架構

- `dashboard_index.html`：入口頁，連到目前主儀表板。
- `main/wind_pm25_lag_dashboard.html`：主儀表板 HTML 結構與控制元件。
- `main/css/wind_pm25_lag_dashboard.css`：主儀表板樣式。
- `main/js/wind_pm25_lag_dashboard.js`：主儀表板互動邏輯、地圖、圖表、事件診斷。
- `main/wind_pm25_data.js`：自動產生的風向/PM2.5 資料。
- `main/event_diagnosis_data.js`：自動產生的事件診斷資料。
- `main/peak_data.js`：前端讀取的高峰事件資料。
- `preprocess_wind_pm25.py`：資料前處理腳本。
- `CWA_Weather_Final/`：原始 CWA 氣象 CSV。
- `docs/DASHBOARDS.md`、`docs/DATA_CATALOG.md`：儀表板與資料說明。
- `docs/AI_TASK_TEMPLATE.md`：給 AI 的任務說明模板。

## 分支流程

- 不直接在 `main` 分支開發。
- 每個任務建立自己的 feature branch，例如 `feature/wind-map-layer`、`feature/event-panel-ui`。
- 修改前先執行 `git status`，確認目前工作區有哪些既有變更。
- 開始前先同步最新主分支，再從最新主分支切 feature branch。
- 發 PR 前附上修改重點、影響檔案、測試方式。

建議流程：

```bash
git checkout main
git pull
git checkout -b feature/your-task-name
```

## 任務切分

優先用這些邊界分工：

- 地圖、PM/CWA marker、風向疊圖：`main/js/wind_pm25_lag_dashboard.js` 的 map/icon/drawMap 相關函式，以及 `main/css/wind_pm25_lag_dashboard.css` 的地圖樣式。
- 圖表、polar plot、lag chart：`main/js/wind_pm25_lag_dashboard.js` 的 chart/polar 相關函式。
- 事件列表、診斷表格、右側資訊面板：`main/wind_pm25_lag_dashboard.html`、`main/js/wind_pm25_lag_dashboard.js` 的 render/diagnosis 相關函式，以及 CSS。
- 資料前處理：`preprocess_wind_pm25.py`。
- 自動產生資料：`main/wind_pm25_data.js`、`main/event_diagnosis_data.js`。這些檔案應由 script 產生，不手改。
- 文件與資料說明：`docs/DASHBOARDS.md`、`docs/DATA_CATALOG.md`、`docs/CONTRIBUTING.md`、`docs/AI_TASK_TEMPLATE.md`。

## 同時開發避免衝突

同一時間盡量讓每個人只擁有一個區域。開工前先在群組或 issue 留一句「我這次會改哪些檔案」。

建議 ownership：

- 地圖功能 owner：`main/js/wind_pm25_lag_dashboard.js` 的 map/icon/drawMap 相關函式，必要時搭配 CSS 的 marker/map 區塊。
- 圖表功能 owner：`main/js/wind_pm25_lag_dashboard.js` 的 drawLagChart/drawSeries/drawPolar 相關函式。
- 事件面板 owner：`main/wind_pm25_lag_dashboard.html` 的事件/診斷區塊，和 JS 的 renderEvents/renderDetail/drawDiagnosisTable。
- 視覺樣式 owner：`main/css/wind_pm25_lag_dashboard.css`，但要在 PR 說明影響到哪些畫面區域。
- 資料 owner：`preprocess_wind_pm25.py`。產生檔只由資料 owner 更新。
- 文件 owner：Markdown 文件。

避免衝突規則：

- 兩個人不要同時大改 `main/js/wind_pm25_lag_dashboard.js`。如果必要，請先切函式範圍，例如一人只改 map，一人只改 chart。
- CSS 修改請用區塊註解標示目的，例如 map、panel、event list、chart，避免整份重排。
- HTML 修改只改任務相關區塊，不重新格式化整頁。
- 自動產生檔 `main/wind_pm25_data.js`、`main/event_diagnosis_data.js` 不跟 UI PR 混在一起。
- 如果任務需要跨 HTML/CSS/JS 三個檔案，PR 要小，並清楚列出每個檔案的用途。

## AI 修改原則

- 每次請 AI 修改時，先貼 `docs/AI_TASK_TEMPLATE.md` 的專案架構與任務限制。
- 指定「只能改哪些檔案」。
- 指定「只能改哪些函式或區塊」。
- 要求 AI 保留其他人的變更，不要回復、覆蓋、整理無關程式碼。
- 不要求 AI 一次重構整個前端。
- 不讓 AI 同時修改資料檔與 UI，除非任務本身就是資料格式變更。
- 不要求 AI 大量重排格式，避免 PR diff 失真。
- AI 完成後一定檢查 `git diff`，確認沒有不相關變更。

## Merge / PR 說明

每次 PR 建議包含：

- 修改摘要：這次解決什麼問題。
- 影響範圍：HTML、CSS、JS、資料檔、文件各自是否有變更。
- 衝突風險：這次是否有改到常見共用檔案，例如 `main/js/wind_pm25_lag_dashboard.js`。
- 測試方式：如何打開頁面、操作哪些控制項、檢查哪些結果。
- 合併注意事項：是否需要重新跑 `preprocess_wind_pm25.py`，是否影響主儀表板入口。

合併前請確認：

- 沒有直接手改 `main/wind_pm25_data.js` 或 `main/event_diagnosis_data.js`，除非 PR 明確說明原因。
- `dashboard_index.html` 仍能連到主儀表板。
- `dashboard_index.html` 仍能載入並連到主儀表板。
- 瀏覽器 console 沒有明顯錯誤。

## Merge 前檢查清單

開 PR 前請跑：

```bash
git status
git diff --stat
```

檢查重點：

- diff 只包含這次任務需要的檔案。
- 沒有整份 HTML/CSS/JS 被重新排版。
- 沒有不小心改到自動產生資料檔。
- 若改到 `main/js/wind_pm25_lag_dashboard.js`，PR 說明有列出修改的函式名稱。
- 若與別人的 PR 同時改同一檔，先等其中一個合併，再把另一個 branch 更新到最新主分支後測試。

## 衝突處理

如果 merge 時發生衝突：

- 先確認衝突檔案是否真的屬於自己的任務範圍。
- 優先保留雙方功能，不要直接接受整份 ours/theirs。
- 解完衝突後重新打開 `main/wind_pm25_lag_dashboard.html` 測試互動。
- 如果衝突在自動產生資料檔，請重新跑資料產生流程，不手動拼接大型 JS 資料檔。

## 本地檢查

靜態頁可以直接打開：

- `dashboard_index.html`
- `main/wind_pm25_lag_dashboard.html`

修改主儀表板後，至少確認：

- 主頁能載入。
- 地圖有出現。
- PM 測站與 CWA 風站 marker 有出現。
- 事件切換、lag slider、時間 offset slider 可操作。
- 瀏覽器 console 沒有明顯錯誤。
