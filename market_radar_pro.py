from __future__ import annotations

import html
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

ROOT = Path(__file__).resolve().parent
SITE_DIR = ROOT / "site"
DATA_DIR = SITE_DIR / "data"
INDEX_PATH = SITE_DIR / "index.html"
JSON_PATH = DATA_DIR / "latest.json"
RSS_ENDPOINT = "https://news.google.com/rss/search?q={query}+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
TAIPEI_TZ = timezone(timedelta(hours=8))


def u(value: str) -> str:
    return value.encode("ascii").decode("unicode_escape")


LAYERS = {
    "social": {
        "label": u(r"\u793e\u7fa4\u71b1\u5ea6"),
        "subtitle": u(r"Threads\u3001PTT\u3001Dcard\uff1a\u5927\u5bb6\u5728\u8a0e\u8ad6\u4ec0\u9ebc"),
        "queries": [u(r"\u53f0\u80a1 Threads"), u(r"\u53f0\u80a1 PTT Stock"), u(r"\u53f0\u80a1 Dcard \u6295\u8cc7"), u(r"AI\u4f3a\u670d\u5668 \u53f0\u80a1 \u8a0e\u8ad6"), u(r"PCB CCL \u53f0\u80a1 \u8a0e\u8ad6"), u(r"\u6563\u71b1 \u53f0\u80a1 \u8a0e\u8ad6"), u(r"BBU \u53f0\u80a1"), u(r"\u77fd\u5149\u5b50 CPO \u53f0\u80a1")],
    },
    "institutional": {
        "label": u(r"\u5238\u5546\uff0f\u6295\u4fe1\u7814\u7a76"),
        "subtitle": u(r"\u6cd5\u4eba\u770b\u597d\u4ec0\u9ebc"),
        "queries": [u(r"\u5238\u5546\u6668\u5831 \u53f0\u80a1 AI PCB"), u(r"\u6295\u4fe1\u89c0\u9ede \u53f0\u80a1 AI"), u(r"\u51f1\u57fa\u6295\u9867 \u53f0\u80a1"), u(r"\u7fa4\u76ca\u6295\u9867 \u53f0\u80a1"), u(r"\u7389\u5c71\u8b49\u5238 \u5e02\u5834\u89c0\u9ede"), u(r"\u5bcc\u90a6\u6295\u9867 \u7814\u7a76\u5831\u544a"), u(r"\u91ce\u6751\u6295\u4fe1 \u53f0\u80a1 AI"), u(r"\u5143\u5927\u6295\u4fe1 \u53f0\u80a1 ETF"), u(r"\u5fa9\u83ef\u6295\u4fe1 \u53f0\u80a1"), u(r"\u570b\u6cf0\u6295\u4fe1 \u7522\u696d\u89c0\u9ede")],
    },
    "market": {
        "label": u(r"\u5e02\u5834\u6578\u64da"),
        "subtitle": u(r"\u8cc7\u91d1\u662f\u5426\u771f\u7684\u6d41\u5165"),
        "queries": [u(r"\u53f0\u80a1 \u6cd5\u4eba \u8cb7\u8d85"), u(r"\u5916\u8cc7 \u8cb7\u8d85 \u53f0\u80a1"), u(r"\u6295\u4fe1 \u8cb7\u8d85 \u53f0\u80a1"), u(r"\u53f0\u80a1 \u6210\u4ea4\u91cf \u7206\u91cf"), u(r"\u8b49\u4ea4\u6240 \u91cd\u5927\u8a0a\u606f"), u(r"\u6cd5\u8aaa\u6703 \u53f0\u80a1"), u(r"\u5916\u8cc7 \u76ee\u6a19\u50f9 \u53f0\u80a1"), u(r"\u53f0\u80a1 \u6280\u8853\u9762 \u7a81\u7834")],
    },
}

STOCKS = [
    ("2330", u(r"\u53f0\u7a4d\u96fb"), [u(r"\u53f0\u7a4d\u96fb"), "TSMC", "2330"]),
    ("2317", u(r"\u9d3b\u6d77"), [u(r"\u9d3b\u6d77"), "2317"]),
    ("2454", u(r"\u806f\u767c\u79d1"), [u(r"\u806f\u767c\u79d1"), "2454"]),
    ("2308", u(r"\u53f0\u9054\u96fb"), [u(r"\u53f0\u9054\u96fb"), u(r"\u53f0\u9054"), "2308"]),
    ("2382", u(r"\u5ee3\u9054"), [u(r"\u5ee3\u9054"), "2382"]),
    ("3231", u(r"\u7def\u5275"), [u(r"\u7def\u5275"), "3231"]),
    ("6669", u(r"\u7def\u7a4e"), [u(r"\u7def\u7a4e"), "6669"]),
    ("3017", u(r"\u5947\u92d0"), [u(r"\u5947\u92d0"), "3017"]),
    ("3324", u(r"\u96d9\u9d3b"), [u(r"\u96d9\u9d3b"), "3324"]),
    ("2059", u(r"\u5ddd\u6e56"), [u(r"\u5ddd\u6e56"), "2059"]),
    ("2383", u(r"\u53f0\u5149\u96fb"), [u(r"\u53f0\u5149\u96fb"), "2383"]),
    ("6274", u(r"\u53f0\u71ff"), [u(r"\u53f0\u71ff"), "6274"]),
    ("3037", u(r"\u6b23\u8208"), [u(r"\u6b23\u8208"), "3037"]),
    ("8046", u(r"\u5357\u96fb"), [u(r"\u5357\u96fb"), "8046"]),
    ("3711", u(r"\u65e5\u6708\u5149\u6295\u63a7"), [u(r"\u65e5\u6708\u5149"), "3711"]),
    ("3661", u(r"\u4e16\u82af-KY"), [u(r"\u4e16\u82af"), "3661"]),
    ("3443", u(r"\u5275\u610f"), [u(r"\u5275\u610f"), "3443"]),
    ("2603", u(r"\u9577\u69ae"), [u(r"\u9577\u69ae"), "2603"]),
    ("2881", u(r"\u5bcc\u90a6\u91d1"), [u(r"\u5bcc\u90a6\u91d1"), "2881"]),
    ("0050", u(r"\u5143\u5927\u53f0\u706350"), [u(r"\u5143\u5927\u53f0\u706350"), "0050"]),
]

TOPICS = [
    ("AI Server", [u(r"AI\u4f3a\u670d\u5668"), "AI server", "GB200", "GB300", "NVIDIA"]),
    ("PCB/CCL", ["PCB", "CCL", u(r"\u8f09\u677f"), u(r"\u9ad8\u968e\u677f")]),
    ("ASIC", ["ASIC", u(r"\u7279\u6b8a\u61c9\u7528\u6676\u7247")]),
    ("CoWoS", ["CoWoS", u(r"\u5148\u9032\u5c01\u88dd")]),
    ("CPO/SiPh", [u(r"\u77fd\u5149\u5b50"), "CPO", u(r"\u5149\u901a\u8a0a")]),
    (u(r"\u6563\u71b1"), [u(r"\u6563\u71b1"), u(r"\u6c34\u51b7"), u(r"\u6db2\u51b7")]),
    ("BBU/UPS", ["BBU", "UPS", u(r"\u96fb\u6c60\u5099\u63f4")]),
    (u(r"\u8ecd\u5de5/\u7121\u4eba\u6a5f"), [u(r"\u8ecd\u5de5"), u(r"\u7121\u4eba\u6a5f")]),
    (u(r"\u8a18\u61b6\u9ad4/DRAM"), [u(r"\u8a18\u61b6\u9ad4"), "DRAM", "HBM", "DDR5"]),
    (u(r"ETF\u914d\u7f6e"), ["ETF", u(r"\u9ad8\u80a1\u606f")]),
]

POSITIVE = [u(r"\u770b\u597d"), u(r"\u8cb7\u9032"), u(r"\u8cb7\u8d85"), u(r"\u4e0a\u4fee"), u(r"\u6210\u9577"), u(r"\u7a81\u7834"), u(r"\u53d7\u60e0")]
NEGATIVE = [u(r"\u770b\u58de"), u(r"\u8ce3\u8d85"), u(r"\u4e0b\u4fee"), u(r"\u98a8\u96aa"), u(r"\u8b66\u8a0a")]


def main() -> None:
    analysis = build_market_radar()
    write_outputs(analysis)
    print(analysis["headline"])


def build_market_radar() -> dict:
    items = collect_items() or fallback_items()
    for item in items:
        enrich_item(item)
    layers = {layer: summarize_layer(items, layer) for layer in LAYERS}
    cross = build_cross_analysis(layers)
    consensus = build_consensus(layers, items)
    watchlist = cross[:5]
    return {
        "generated_at": datetime.now(TAIPEI_TZ).isoformat(),
        "headline": build_headline(consensus, watchlist),
        "layers": layers,
        "cross_analysis": cross,
        "consensus": consensus,
        "watchlist": watchlist,
        "source_items": serialize_items(items[:120]),
        "notes": [u(r"\u76ee\u524d\u70ba\u516c\u958b RSS MVP\uff0c\u5c1a\u672a\u63a5\u5165 Threads \u5b98\u65b9 API \u8207\u5238\u5546\u6388\u6b0a\u5831\u544a\u3002")],
    }


def collect_items() -> list[dict]:
    rows = []
    seen = set()
    headers = {"User-Agent": "market-radar-pro/0.2"}
    for layer, config in LAYERS.items():
        for query in config["queries"]:
            try:
                response = requests.get(RSS_ENDPOINT.format(query=quote_plus(query)), headers=headers, timeout=15)
                response.raise_for_status()
            except requests.RequestException as exc:
                print(f"Fetch failed for {layer}:{query}: {exc}")
                continue
            feed = feedparser.parse(response.content)
            for entry in feed.entries[:12]:
                title = clean(getattr(entry, "title", ""))
                summary = clean(getattr(entry, "summary", ""))
                url = getattr(entry, "link", "")
                key = url or title
                if not title or key in seen:
                    continue
                seen.add(key)
                rows.append({"layer": layer, "query": query, "source": source_name(entry, title), "title": title, "summary": summary, "url": url, "published_at": parse_dt(getattr(entry, "published", None))})
    return rows


def fallback_items() -> list[dict]:
    now = datetime.now(timezone.utc)
    samples = [
        ("social", u(r"\u53f0\u80a1\u793e\u7fa4\u4eca\u5929\u96c6\u4e2d\u8a0e\u8ad6 AI Server\u3001PCB/CCL\u3001\u6563\u71b1\u8207\u77fd\u5149\u5b50\uff0c\u53f0\u5149\u96fb\u3001\u5947\u92d0\u3001\u5ddd\u6e56\u88ab\u91cd\u8907\u9ede\u540d\u3002")),
        ("institutional", u(r"\u5238\u5546\u8207\u6295\u4fe1\u89c0\u9ede\u504f\u5411 AI Server\u3001CoWoS\u3001CPO\uff0c\u5171\u540c\u770b\u597d\u53f0\u7a4d\u96fb\u3001\u53f0\u5149\u96fb\u3001\u5947\u92d0\u3001\u7def\u7a4e\u3002")),
        ("market", u(r"\u6cd5\u4eba\u8cc7\u91d1\u5c0d\u96fb\u5b50\u6b0a\u503c\u8207 AI \u4f9b\u61c9\u93c8\u504f\u591a\uff0cPCB \u8207\u6563\u71b1\u6210\u4ea4\u91cf\u660e\u986f\u653e\u5927\u3002")),
    ]
    return [{"layer": layer, "query": "fallback", "source": "MVP fallback", "title": title, "summary": "", "url": "", "published_at": now} for layer, title in samples]


def enrich_item(item: dict) -> None:
    text = f"{item['title']} {item['summary']}"
    normalized = text.upper()
    item["stocks"] = [{"code": code, "name": name} for code, name, aliases in STOCKS if any(contains_alias(normalized, alias) for alias in aliases)]
    item["topics"] = [name for name, aliases in TOPICS if any(contains_alias(normalized, alias) for alias in aliases)]
    score = sum(text.count(term) for term in POSITIVE) - sum(text.count(term) for term in NEGATIVE)
    item["sentiment_score"] = score
    item["sentiment"] = u(r"\u504f\u6a02\u89c0") if score >= 2 else u(r"\u504f\u4fdd\u5b88") if score <= -2 else u(r"\u4e2d\u6027")


def summarize_layer(items: list[dict], layer: str) -> dict:
    layer_items = [item for item in items if item["layer"] == layer]
    return {"label": LAYERS[layer]["label"], "subtitle": LAYERS[layer]["subtitle"], "signal_count": len(layer_items), "top_stocks": rank_entities(layer_items, "stocks")[:12], "top_topics": rank_entities(layer_items, "topics")[:12], "top_events": top_events(layer_items)}


def rank_entities(items: list[dict], field: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    bucket: dict[str, dict] = {}
    for item in items:
        heat = article_heat(item, now)
        for entity in item[field]:
            key = entity["code"] if isinstance(entity, dict) else entity
            name = entity["name"] if isinstance(entity, dict) else entity
            code = entity["code"] if isinstance(entity, dict) else ""
            row = bucket.setdefault(key, {"code": code, "name": name, "mentions": 0, "heat": 0.0, "sources": set(), "sentiment_sum": 0})
            row["mentions"] += 1
            row["heat"] += heat
            row["sources"].add(item["source"])
            row["sentiment_sum"] += item["sentiment_score"]
    return sorted([{"code": row["code"], "name": row["name"], "mentions": row["mentions"], "sources": len(row["sources"]), "heat": round(row["heat"] + row["mentions"] * 1.5 + len(row["sources"]) * 1.2, 2)} for row in bucket.values()], key=lambda row: (row["heat"], row["mentions"]), reverse=True)


def build_cross_analysis(layers: dict) -> list[dict]:
    stocks: dict[str, dict] = {}
    for layer, summary in layers.items():
        for row in summary["top_stocks"]:
            item = stocks.setdefault(row["code"], {"code": row["code"], "name": row["name"], "social_heat": 0, "broker_mentions": 0, "fund_mentions": 0, "market_mentions": 0})
            if layer == "social":
                item["social_heat"] = max(item["social_heat"], row["heat"])
            elif layer == "institutional":
                item["broker_mentions"] += row["mentions"]
                item["fund_mentions"] += max(0, row["sources"] - 1)
            elif layer == "market":
                item["market_mentions"] += row["mentions"]
    max_social = max([v["social_heat"] for v in stocks.values()] or [1])
    max_inst = max([v["broker_mentions"] + v["fund_mentions"] for v in stocks.values()] or [1])
    max_market = max([v["market_mentions"] for v in stocks.values()] or [1])
    rows = []
    for row in stocks.values():
        social_score = 100 * row["social_heat"] / max_social if max_social else 0
        inst_score = 100 * (row["broker_mentions"] + row["fund_mentions"]) / max_inst if max_inst else 0
        market_score = 100 * row["market_mentions"] / max_market if max_market else 0
        ai_score = round(0.38 * social_score + 0.37 * inst_score + 0.25 * market_score)
        if social_score >= 70 and inst_score < 30:
            signal = u(r"\u793e\u7fa4\u5f88\u71b1\uff0c\u6cd5\u4eba\u5c1a\u672a\u8ddf\u4e0a")
        elif inst_score >= 70 and social_score < 40:
            signal = u(r"\u6cd5\u4eba\u5148\u884c\uff0c\u793e\u7fa4\u5c1a\u672a\u767c\u9175")
        elif social_score >= 55 and inst_score >= 55:
            signal = u(r"\u793e\u7fa4\u8207\u6cd5\u4eba\u540c\u6b65\u5347\u6eab")
        else:
            signal = u(r"\u5f85\u6301\u7e8c\u8ffd\u8e64")
        rows.append({**row, "capital_flow": star_rating(market_score), "ai_score": ai_score, "signal": signal})
    return sorted(rows, key=lambda row: row["ai_score"], reverse=True)


def build_consensus(layers: dict, items: list[dict]) -> dict:
    inst = layers["institutional"]
    market = layers["market"]
    return {"report_count": inst["signal_count"], "common_topics": merge_ranked_names([inst["top_topics"], market["top_topics"]])[:8], "common_stocks": merge_ranked_names([inst["top_stocks"], market["top_stocks"]])[:10], "events": [event["title"] for event in top_events(items)[:8]]}


def build_headline(consensus: dict, watchlist: list[dict]) -> str:
    topics = u(r"\u3001").join(consensus["common_topics"][:4]) or u(r"\u5e02\u5834\u7126\u9ede\u4ecd\u5728\u5f62\u6210")
    stocks = u(r"\u3001").join(row["name"] for row in watchlist[:5]) or u(r"\u5c1a\u7121\u660e\u986f\u5171\u8b58\u80a1")
    return u(r"\u4eca\u5929\u5e02\u5834\u4e3b\u8981\u8a0e\u8ad6\uff1a") + topics + u(r"\uff1b\u6cd5\u4eba\u8207\u8cc7\u91d1\u5171\u632f\u503c\u5f97\u8ffd\u8e64\uff1a") + stocks + u(r"\u3002")


def write_outputs(analysis: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    INDEX_PATH.write_text(render_html(analysis), encoding="utf-8")


def render_html(data: dict) -> str:
    title = u(r"\u5e02\u5834\u71b1\u5ea6\u96f7\u9054 Pro")
    subtitle = u(r"\u4e09\u5c64\u8cc7\u8a0a\u5f15\u64ce\uff1a\u793e\u7fa4\u71b1\u5ea6\u3001\u5238\u5546\uff0f\u6295\u4fe1\u7814\u7a76\u3001\u5e02\u5834\u6578\u64da")
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>{esc(title)}</title><style>body{{margin:0;background:#f8fafc;color:#111827;font-family:'Microsoft JhengHei','Noto Sans TC',Arial,sans-serif}}.wrap{{max-width:1280px;margin:0 auto;padding:28px 22px 44px}}.top{{display:flex;justify-content:space-between;align-items:end;gap:16px;margin-bottom:18px}}h1{{margin:0;font-size:30px}}h2{{margin:0 0 12px;font-size:19px}}.muted{{color:#64748b;font-size:14px}}.headline{{border-left:5px solid #0f766e;background:#fff;border-radius:8px;padding:16px 18px;line-height:1.8;font-size:17px;margin-bottom:16px}}.grid3{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:16px}}.grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-bottom:16px}}.panel{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;box-shadow:0 1px 2px rgba(15,23,42,.04);overflow:hidden}}.score{{font-size:28px;font-weight:700;margin-top:8px}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:10px 9px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}th{{background:#f1f5f9;color:#334155}}.table-scroll{{max-height:520px;overflow:auto;border:1px solid #e5e7eb;border-radius:8px}}.tag{{display:inline-block;background:#ecfeff;color:#0f766e;border:1px solid #99f6e4;border-radius:999px;padding:4px 9px;margin:0 6px 6px 0;font-size:13px}}@media(max-width:980px){{.grid3,.grid2,.top{{display:block}}.panel{{margin-bottom:14px}}}}</style></head><body><main class='wrap'><div class='top'><div><h1>{esc(title)}</h1><div class='muted'>{esc(subtitle)}</div></div><div class='muted'>{esc(u(r'\u66f4\u65b0\u6642\u9593\uff1a'))}{esc(format_time(data['generated_at']))}</div></div><section class='headline'>{esc(data['headline'])}</section><section class='grid3'>{render_layer_cards(data['layers'])}</section><section class='grid2'><div class='panel'><h2>{esc(u(r'AI \u6cd5\u4eba\u5171\u8b58\u5206\u6790'))}</h2>{render_consensus(data['consensus'])}</div><div class='panel'><h2>{esc(u(r'\u660e\u65e5\u6700\u503c\u5f97\u95dc\u6ce8\u7684 5 \u6a94\u80a1\u7968'))}</h2>{render_table(data['watchlist'], watch_columns())}</div></section><section class='panel'><h2>{esc(u(r'\u5e02\u5834\u71b1\u5ea6\u4ea4\u53c9\u5206\u6790'))}</h2>{render_table(data['cross_analysis'][:18], cross_columns())}</section><section class='panel' style='margin-top:16px'><h2>{esc(u(r'\u4f86\u6e90\u660e\u7d30'))}</h2>{render_sources(data['source_items'])}</section></main></body></html>"""


def render_layer_cards(layers: dict) -> str:
    cards = []
    for key in ["social", "institutional", "market"]:
        layer = layers[key]
        topics = "".join(f"<span class='tag'>{esc(row['name'])}</span>" for row in layer["top_topics"][:5])
        stocks = u(r"\u3001").join(row["name"] for row in layer["top_stocks"][:5]) or u(r"\u5c1a\u672a\u8fa8\u8b58\u5230\u500b\u80a1")
        cards.append(f"<div class='panel'><h2>{esc(layer['label'])}</h2><div class='muted'>{esc(layer['subtitle'])}</div><div class='score'>{layer['signal_count']}</div><div class='muted'>{esc(u(r'\u4eca\u65e5\u8a0a\u865f\u6578'))}</div><p><b>{esc(u(r'\u71b1\u9580\u984c\u6750'))}</b></p>{topics}<p><b>{esc(u(r'\u76f8\u95dc\u500b\u80a1'))}</b><br>{esc(stocks)}</p></div>")
    return "".join(cards)


def render_consensus(consensus: dict) -> str:
    topics = "".join(f"<span class='tag'>{esc(topic)}</span>" for topic in consensus["common_topics"][:8])
    stocks = "".join(f"<span class='tag'>{esc(stock)}</span>" for stock in consensus["common_stocks"][:10])
    events = "".join(f"<li>{esc(event)}</li>" for event in consensus["events"][:6])
    return f"<p>{esc(u(r'\u4eca\u65e5\u6cd5\u4eba\uff0f\u7814\u7a76\u8a0a\u865f\u5171'))} <b>{consensus['report_count']}</b> {esc(u(r'\u5247'))}</p><p><b>{esc(u(r'\u5171\u540c\u95dc\u6ce8\u984c\u6750'))}</b></p>{topics}<p><b>{esc(u(r'\u5171\u540c\u770b\u597d\u80a1\u7968'))}</b></p>{stocks}<p><b>{esc(u(r'\u4eca\u65e5\u95dc\u6ce8\u4e8b\u4ef6'))}</b></p><ul>{events}</ul>"


def watch_columns() -> list[tuple[str, str]]:
    return [("name", u(r"\u80a1\u7968")), ("social_heat", u(r"\u793e\u7fa4\u71b1\u5ea6")), ("broker_mentions", u(r"\u5238\u5546\u63d0\u53ca")), ("fund_mentions", u(r"\u6295\u4fe1\u63d0\u53ca")), ("capital_flow", u(r"\u6cd5\u4eba\u8cb7\u8d85")), ("ai_score", u(r"AI\u8a55\u5206"))]


def cross_columns() -> list[tuple[str, str]]:
    return [("name", u(r"\u80a1\u7968")), ("social_heat", u(r"Threads/\u793e\u7fa4\u71b1\u5ea6")), ("broker_mentions", u(r"\u5238\u5546\u63d0\u53ca")), ("fund_mentions", u(r"\u6295\u4fe1\u63d0\u53ca")), ("market_mentions", u(r"\u5e02\u5834\u6578\u64da\u63d0\u53ca")), ("capital_flow", u(r"\u8cc7\u91d1\u6d41\u5411")), ("ai_score", u(r"AI\u8a55\u5206")), ("signal", u(r"\u5224\u8b80"))]


def render_sources(items: list[dict]) -> str:
    rows = []
    for item in items[:80]:
        title = f"<a href='{esc(item['url'])}' target='_blank' rel='noreferrer'>{esc(item['title'])}</a>" if item.get("url") else esc(item["title"])
        rows.append({"layer_label": LAYERS[item["layer"]]["label"], "time": format_time(item["published_at"]), "source": item["source"], "title": title, "stocks_text": u(r"\u3001").join(stock["name"] for stock in item["stocks"]), "topics_text": u(r"\u3001").join(item["topics"])})
    cols = [("layer_label", u(r"\u5c64\u7d1a")), ("time", u(r"\u6642\u9593")), ("source", u(r"\u4f86\u6e90")), ("title", u(r"\u6a19\u984c")), ("stocks_text", u(r"\u80a1\u7968")), ("topics_text", u(r"\u984c\u6750"))]
    return render_table(rows, cols, escape_values=False)


def render_table(rows: list[dict], columns: list[tuple[str, str]], escape_values: bool = True) -> str:
    if not rows:
        return f"<p class='muted'>{esc(u(r'\u76ee\u524d\u6c92\u6709\u8db3\u5920\u8cc7\u6599\u3002'))}</p>"
    header = "".join(f"<th>{esc(label)}</th>" for _, label in columns)
    body = ""
    for row in rows:
        body += "<tr>" + "".join(f"<td>{esc(row.get(key, '')) if escape_values else row.get(key, '')}</td>" for key, _ in columns) + "</tr>"
    return f"<div class='table-scroll'><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"


def serialize_items(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        row = dict(item)
        row["published_at"] = item["published_at"].isoformat()
        rows.append(row)
    return rows


def article_heat(item: dict, now: datetime) -> float:
    age_hours = max((now - item["published_at"]).total_seconds() / 3600, 0)
    return 3 + max(0.2, 1.8 - age_hours / 18) + abs(item["sentiment_score"]) * 0.35


def top_events(items: list[dict]) -> list[dict]:
    ranked = sorted(items, key=lambda item: (len(item["topics"]) + len(item["stocks"]), item["published_at"]), reverse=True)
    return [{"title": item["title"], "source": item["source"], "layer": item["layer"]} for item in ranked[:10]]


def merge_ranked_names(ranked_lists: list[list[dict]]) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for rows in ranked_lists:
        for idx, row in enumerate(rows):
            scores[row["name"]] += max(1, 12 - idx)
    return [name for name, _ in sorted(scores.items(), key=lambda pair: pair[1], reverse=True)]


def star_rating(score: float) -> str:
    stars = max(1, min(5, math.ceil(score / 20)))
    return u(r"\u2605") * stars + u(r"\u2606") * (5 - stars)


def clean(value: str | None) -> str:
    if not value:
        return ""
    return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", value).split()))


def parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def source_name(entry: object, title: str) -> str:
    source = getattr(entry, "source", None)
    if isinstance(source, dict) and source.get("title"):
        return source["title"]
    return title.rsplit(" - ", 1)[-1] if " - " in title else "Google News"


def contains_alias(text: str, alias: str) -> bool:
    alias_norm = alias.upper()
    if alias_norm.isdigit():
        return bool(re.search(rf"(?<!\d){re.escape(alias_norm)}(?!\d)", text))
    return alias_norm in text


def format_time(value: str | datetime) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.astimezone(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")


def esc(value: object) -> str:
    return html.escape(str(value) if value is not None else "", quote=True)


if __name__ == "__main__":
    main()
