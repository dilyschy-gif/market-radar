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
| `FINMIND_API_TOKEN` | FinMind API Token；只放 Secret Manager，不可寫入映像或原始碼 |

`GITHUB_TOKEN` 與 `FINMIND_API_TOKEN` 都建議放在 Secret Manager，不要寫死在程式碼或公開檔案。

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

建議時段：08:37、12:37、15:17、20:07、21:17。IC設計籌碼分數只會在21:10後且資料日尚未更新時重新抓取；其他時段沿用最近完整快照。

## 現階段資料限制

目前 Pro 版是低成本 MVP：新聞層仍使用公開RSS；TWSE提供上市股量價與法人事實層；FinMind免費API提供固定IC設計股票池的日價量、三大法人與融資融券。它還不是正式授權的Threads API、券商報告API或完整全市場資料庫。
