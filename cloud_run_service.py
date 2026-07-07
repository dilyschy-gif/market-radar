from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests
from flask import Flask, jsonify

from market_radar_pro import INDEX_PATH, JSON_PATH, build_market_radar, write_outputs

app = Flask(__name__)


@app.get("/")
def health() -> tuple[dict, int]:
    return {"ok": True, "service": "market-radar-pro"}, 200


@app.get("/run")
@app.post("/run")
def run() -> tuple[dict, int]:
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


def put_github_file(repo: str, branch: str, path: str, content: str, token: str) -> None:
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    current = requests.get(api, headers=headers, params={"ref": branch}, timeout=20)
    sha = current.json().get("sha") if current.status_code == 200 else None
    payload = {
        "message": f"Update market radar Pro {path}",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    response = requests.put(api, headers=headers, data=json.dumps(payload), timeout=30)
    response.raise_for_status()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
