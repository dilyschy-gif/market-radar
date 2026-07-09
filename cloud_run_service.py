from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import requests
from flask import Flask, jsonify, request

from market_radar_pro import INDEX_PATH, JSON_PATH, build_market_radar, write_outputs

# 需要額外安裝 google-auth（Cloud Run 環境通常已內建，本機測試請自行
# `pip install google-auth`）：用來驗證 Cloud Scheduler 呼叫 /run 時附上的 OIDC ID Token。
try:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    _GOOGLE_AUTH_AVAILABLE = True
except ImportError:  # pragma: no cover - 只有在缺少套件時才會走到
    _GOOGLE_AUTH_AVAILABLE = False

app = Flask(__name__)

# ---------------------------------------------------------------------------
# 驗證設定
# ---------------------------------------------------------------------------
# REQUIRE_OIDC_AUTH=false 只建議在本機開發時使用；部署到 Cloud Run 時務必保持
# 預設值 true，否則任何知道網址的人都能觸發 /run，並用伺服器端的 GITHUB_TOKEN 對 repo 寫入。
REQUIRE_OIDC_AUTH = os.getenv("REQUIRE_OIDC_AUTH", "true").lower() not in ("false", "0", "")
# 預期的 audience：Cloud Scheduler 設定的 OIDC token audience，通常就是這個服務的完整網址，
# 例如 https://market-radar-xxxxx-uc.a.run.app/run。留空的話會退而求其次，用當次請求的 URL 當作 audience。
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "")
# 選填：只允許特定的服務帳號 email 觸發（Cloud Scheduler 設定的 Service Account）。留空則不檢查 email。
ALLOWED_INVOKER_EMAIL = os.getenv("ALLOWED_INVOKER_EMAIL", "")


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message = message
        self.status = status


def verify_oidc_request() -> None:
    """驗證帶入的 Authorization: Bearer <OIDC ID Token>。

    Cloud Scheduler 觸發 Cloud Run 時可以設定「新增 OIDC token」，這裡驗證的就是那個 token，
    確保呼叫者真的是我們指定的 Cloud Scheduler job / 服務帳號，而不是任何知道網址的訪客。
    """
    if not REQUIRE_OIDC_AUTH:
        app.logger.warning("REQUIRE_OIDC_AUTH is disabled - /run is unauthenticated. Do not use this in production.")
        return

    if not _GOOGLE_AUTH_AVAILABLE:
        # 安全考量：驗證用的套件缺失時，寧可拒絕請求（fail closed），也不要悄悄放行。
        raise AuthError("Server misconfiguration: google-auth is not installed, cannot verify OIDC token.", 500)

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AuthError("Missing Authorization: Bearer <OIDC token> header.")
    token = header[len("Bearer "):].strip()
    if not token:
        raise AuthError("Empty bearer token.")

    audience = OIDC_AUDIENCE or request.base_url
    try:
        claims = google_id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)
    except Exception as exc:
        # 涵蓋 ValueError（token 格式/簽章/audience 錯誤）以及抓取 Google 憑證時的網路錯誤，
        # 一律視為驗證失敗（401），避免把底層例外的 stack trace 當成 500 洩漏出去。
        raise AuthError(f"Invalid OIDC token: {exc}") from exc

    if ALLOWED_INVOKER_EMAIL and claims.get("email") != ALLOWED_INVOKER_EMAIL:
        raise AuthError(f"Token email {claims.get('email')!r} is not an allowed invoker.", 403)


@app.errorhandler(AuthError)
def handle_auth_error(err: AuthError):
    return jsonify({"ok": False, "error": err.message}), err.status


@app.get("/")
def health() -> tuple[dict, int]:
    return {"ok": True, "service": "market-radar-pro"}, 200


@app.get("/run")
@app.post("/run")
def run() -> tuple[dict, int]:
    verify_oidc_request()
    analysis = build_market_radar()
    write_outputs(analysis)
    publish_result = publish_to_github([INDEX_PATH, JSON_PATH])
    return jsonify({"ok": True, "headline": analysis["headline"], "publish": publish_result}), 200


def publish_to_github(paths: list[Path]) -> dict:
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY", "dilyschy-gif/market-radar")
    branch = os.getenv("GITHUB_BRANCH", "gh-pages")
    if not token:
        return {"skipped": True, "reason": "GITHUB_TOKEN is not set"}

    published = []
    for path in paths:
        if not path.exists():
            continue
        repo_path = "index.html" if path.name == "index.html" else "data/latest.json"
        put_github_file(repo, branch, repo_path, path.read_text(encoding="utf-8"), token)
        published.append(repo_path)
    return {"skipped": False, "repo": repo, "branch": branch, "files": published}


def put_github_file(repo: str, branch: str, path: str, content: str, token: str, max_retries: int = 3) -> None:
    """PUT a file to GitHub Contents API, retrying on 409 (sha conflict).

    這個服務（Cloud Run）跟 GitHub Actions 排程都會寫入同一個 gh-pages 分支的同兩個檔案。
    兩邊幾乎同時觸發時，其中一邊會先更新 sha，另一邊原本拿到的 sha 就過期了，PUT 會收到 409。
    這裡在遇到 409 時重新抓最新的 sha 再重試，而不是直接讓 raise_for_status() 把整個 /run 弄成 500。
    這只是緩解症狀；真正該做的是讓兩個排程只有一個負責寫入 gh-pages（見稽核建議：收斂成單一排程來源）。
    """
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    payload_content = base64.b64encode(content.encode("utf-8")).decode("ascii")

    for attempt in range(1, max_retries + 1):
        current = requests.get(api, headers=headers, params={"ref": branch}, timeout=20)
        sha = current.json().get("sha") if current.status_code == 200 else None
        payload = {
            "message": f"Update market radar Pro {path}",
            "content": payload_content,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        response = requests.put(api, headers=headers, data=json.dumps(payload), timeout=30)
        if response.status_code == 409 and attempt < max_retries:
            # 另一個排程剛好搶先寫入，稍等一下再重新抓 sha 重試。
            time.sleep(0.5 * attempt)
            continue
        response.raise_for_status()
        return


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
