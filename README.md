# 市場熱度雷達 Pro

這是一個台股市場熱度 MVP，現在升級成「三層資訊引擎」：

| 層級 | 目的 |
| --- | --- |
| 社群熱度 | Threads、PTT、Dcard 相關討論：大家在討論什麼 |
| 券商／投信研究 | 券商晨報、投信觀點、產業報告：法人看好什麼 |
| 市場數據 | 法人買賣超、成交量、重大訊息、法說會：資金是否真的流入 |

## 目前輸出

- 今日市場總結：「市場今天在討論什麼」
- AI 法人共識分析
- 今日十大法人共識股
- 明日最值得關注的 5 檔股票
- 市場熱度交叉分析表
- 來源明細與 JSON API：`data/latest.json`

## GitHub Pages 自動更新

GitHub Actions 會在台灣時間以下時段自動更新：

- 08:37
- 12:37
- 15:17
- 20:07

也可以手動到 GitHub Actions 執行 `Update Market Radar Dashboard`。

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

目前 Pro 版先用公開 Google News RSS 做三層資料偵測與交叉分析，屬於低成本 MVP。正式接入 Threads API、PTT/Dcard、券商報告授權、TWSE/TPEx 法人與成交資料時，可以沿用同一個三層架構，只要替換資料蒐集器。

此工具只做資訊整理，不構成投資建議。
