# 市場熱度雷達 Pro

這是一個台股市場熱度 MVP，現在升級成「三層資訊引擎」：

| 層級 | 目的 |
| --- | --- |
| 社群熱度 | Threads、PTT、Dcard 相關討論：大家在討論什麼 |
| 券商／投信研究 | 券商晨報、投信觀點、產業報告：法人看好什麼 |
| 市場數據 | 法人買賣超、成交量、重大訊息、法說會：資金是否真的流入 |

另外加入「IC設計籌碼分數」：使用 FinMind 日價量、三大法人與融資融券，依法人40%、融資健康20%、短空壓力15%、趨勢25%評分。固定股票池控制在免費API額度內，TWSE既有事實層負責抽樣核對上市股。

## 目前輸出

- 今日市場總結：「市場今天在討論什麼」
- AI 法人共識分析
- 今日十大法人共識股
- 明日最值得關注的 5 檔股票
- 市場熱度交叉分析表
- IC設計籌碼A／B／觀察名單與四項分數
- 來源明細與 JSON API：`data/latest.json`
- 獨立IC籌碼快照：`data/ic-chip.json`

## GitHub Pages 自動更新

GitHub Actions 會在台灣時間以下時段自動更新：

- 08:37
- 12:37
- 15:17
- 20:07
- 21:17（FinMind盤後完整資料更新）

也可以手動到 GitHub Actions 執行 `Update Market Radar Dashboard`。

## FinMind免費API設定

1. 到 repository 的 `Settings → Secrets and variables → Actions`。
2. 新增 Repository secret：`FINMIND_API_TOKEN`。
3. 不要把Token寫入Python、YAML或任何會提交到Git的檔案。

掃描器只在台灣時間21:10後、而且最新快照尚未涵蓋當日資料時重新抓取。早盤、盤中及Cloud Run冷啟動會從 `gh-pages/data/ic-chip.json` 恢復最近完整快照，因此不會每次排程都消耗約160次FinMind請求。手動測試如需強制更新，可設定環境變數 `FINMIND_FORCE_REFRESH=true`。

## Google Cloud 架構

正式雲端架構：

```text
Cloud Scheduler
        ↓
Cloud Run
        ↓
GitHub Repository 更新 gh-pages/index.html 與 data/latest.json
        ↓
GitHub Pages
```

Cloud Run 入口檔是 `cloud_run_service.py`，容器設定是 `Dockerfile`。部署步驟請看 `CLOUD_RUN_SETUP.md`。

## 資料來源狀態

目前新聞三層仍以公開 Google News RSS 做低成本資料偵測；量價與法人事實層使用TWSE公開資料，IC設計籌碼層使用FinMind。Threads API、PTT/Dcard及券商報告仍未使用正式授權API。

此工具只做資訊整理，不構成投資建議。
