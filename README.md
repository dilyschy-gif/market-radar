# Threads 台股市場熱度雷達

這是一個雲端版 MVP，用來回答「市場今天在討論什麼」。

## 功能

- 每天在 GitHub Actions 自動更新
- 抓取公開新聞/RSS fallback
- 自動辨識台股個股、ETF、產業題材
- 計算今日熱度、突然暴增題材、情緒方向
- 自動部署到 GitHub Pages

## 更新時間

GitHub Actions 使用 UTC 排程，對應台灣時間：

- 08:37
- 12:37
- 15:17
- 20:07

也可以在 GitHub 的 `Actions` 頁面手動執行 `Update Market Radar Dashboard`。

## GitHub Pages 設定

請到 repo 的：

`Settings` → `Pages` → `Build and deployment` → 選 `GitHub Actions`

首次設定後，到 `Actions` 手動執行一次 workflow。完成後網站會在：

`https://dilyschy-gif.github.io/market-radar/`

## 費用

公開 repo 使用 GitHub Pages 和標準 GitHub-hosted Actions runner，通常不會產生費用。

## 注意

此 MVP 使用公開新聞/RSS 訊號估算市場討論熱度，不構成投資建議。