# Google Cloud Run 部署說明

目標架構：

```text
Cloud Scheduler
        ↓
Cloud Run
        ↓
GitHub Repository：更新 gh-pages/index.html 與 data/latest.json
        ↓
GitHub Pages
```

## Cloud Run 環境變數

| 名稱 | 用途 |
| --- | --- |
| `GITHUB_TOKEN` | GitHub fine-grained token，需有目標 repo 的 Contents read/write 權限 |
| `GITHUB_REPOSITORY` | 預設 `dilyschy-gif/market-radar` |
| `GITHUB_BRANCH` | 預設 `gh-pages` |

`GITHUB_TOKEN` 建議放在 Secret Manager，不要寫死在程式碼或公開檔案。

## 部署 Cloud Run

```bash
gcloud run deploy market-radar-pro \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-env-vars GITHUB_REPOSITORY=dilyschy-gif/market-radar,GITHUB_BRANCH=gh-pages
```

Cloud Scheduler 建立 HTTP job，定時呼叫：

```text
https://<cloud-run-url>/run
```

建議時段：08:37、12:37、15:17、20:07。

## 現階段資料限制

目前 Pro 版是低成本 MVP，先用公開 RSS 查詢模擬三層資訊引擎。它可以每天更新「市場今天在討論什麼」，但還不是正式授權的 Threads API、券商報告 API 或完整 TWSE/TPEx 資料庫。下一版可逐步替換成正式資料源。
