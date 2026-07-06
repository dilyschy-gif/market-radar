from __future__ import annotations

import html
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import plotly.express as px
import plotly.graph_objects as go
import requests

SITE_DIR = Path("site")
OUTPUT = SITE_DIR / "index.html"
RSS_ENDPOINT = "https://news.google.com/rss/search?q={query}+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
QUERIES = [
    "台股",
    "台積電",
    "AI伺服器 台股",
    "PCB 台股",
    "散熱 台股",
    "軍工 台股",
    "BBU 台股",
    "矽光子 台股",
    "台股 法人 買超",
    "台股 成交量 題材",
]

STOCKS = [
    ("2330", "台積電", ["台積電", "TSMC", "2330"]),
    ("2317", "鴻海", ["鴻海", "富士康", "2317"]),
    ("2454", "聯發科", ["聯發科", "發哥", "2454"]),
    ("2308", "台達電", ["台達電", "台達", "2308"]),
    ("2382", "廣達", ["廣達", "2382"]),
    ("3231", "緯創", ["緯創", "3231"]),
    ("6669", "緯穎", ["緯穎", "6669"]),
    ("3017", "奇鋐", ["奇鋐", "3017"]),
    ("3324", "雙鴻", ["雙鴻", "3324"]),
    ("2383", "台光電", ["台光電", "2383"]),
    ("6274", "台燿", ["台燿", "6274"]),
    ("3037", "欣興", ["欣興", "3037"]),
    ("8046", "南電", ["南電", "8046"]),
    ("2303", "聯電", ["聯電", "UMC", "2303"]),
    ("2408", "南亞科", ["南亞科", "2408"]),
    ("3711", "日月光投控", ["日月光", "日月光投控", "3711"]),
    ("2603", "長榮", ["長榮", "2603"]),
    ("2609", "陽明", ["陽明", "2609"]),
    ("2881", "富邦金", ["富邦金", "2881"]),
    ("2882", "國泰金", ["國泰金", "2882"]),
    ("0050", "元大台灣50", ["元大台灣50", "台灣50", "0050"]),
    ("00878", "國泰永續高股息", ["國泰永續高股息", "00878"]),
    ("00919", "群益台灣精選高息", ["群益台灣精選高息", "00919"]),
]

TOPICS = [
    ("AI伺服器", ["AI伺服器", "AI server", "GB200", "GB300", "輝達", "NVIDIA"]),
    ("PCB/CCL", ["PCB", "CCL", "銅箔基板", "高階板", "載板"]),
    ("散熱/水冷", ["散熱", "水冷", "液冷", "風扇", "均熱片"]),
    ("BBU/儲能", ["BBU", "備援電池", "儲能", "UPS"]),
    ("矽光子/CPO", ["矽光子", "CPO", "光通訊", "共同封裝光學"]),
    ("軍工/無人機", ["軍工", "無人機", "國防", "航太"]),
    ("半導體", ["半導體", "晶圓", "先進製程", "晶片"]),
    ("先進封裝/CoWoS", ["CoWoS", "先進封裝", "封裝", "2.5D"]),
    ("記憶體/DRAM", ["記憶體", "DRAM", "HBM", "NAND"]),
    ("電動車", ["電動車", "EV", "車用", "特斯拉"]),
    ("航運", ["航運", "貨櫃", "運價", "紅海"]),
    ("金融", ["金融", "金控", "壽險", "銀行"]),
    ("高股息ETF", ["高股息", "ETF", "配息"]),
]

POSITIVE = ["創高", "大漲", "買超", "看好", "利多", "旺", "成長", "上修", "爆量", "噴出"]
NEGATIVE = ["大跌", "賣超", "利空", "衰退", "下修", "恐慌", "解套", "套牢", "警訊", "疲弱"]


def main() -> None:
    items = collect_items()
    if not items:
        items = fallback_items()
    for item in items:
        enrich(item)
    analysis = analyze(items)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_html(analysis), encoding="utf-8")
    print(analysis["headline"])
    print(f"Generated {OUTPUT} with {len(items)} signals")


def collect_items() -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    headers = {"User-Agent": "market-radar-github-actions/0.1"}
    for query in QUERIES:
        url = RSS_ENDPOINT.format(query=quote_plus(query))
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"Fetch failed for {query}: {exc}")
            continue
        feed = feedparser.parse(response.content)
        for entry in feed.entries[:18]:
            title = clean(getattr(entry, "title", ""))
            summary = clean(getattr(entry, "summary", ""))
            link = getattr(entry, "link", "")
            key = link or title
            if not title or key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "source": source_name(entry, title),
                    "title": title,
                    "summary": summary,
                    "url": link,
                    "query": query,
                    "published_at": parse_dt(getattr(entry, "published", None)),
                    "engagement": 0,
                }
            )
    return rows


def fallback_items() -> list[dict]:
    now = datetime.now(timezone.utc)
    titles = [
        "台股今天討論 AI伺服器、PCB、散熱，台積電、廣達、緯創被反覆提到",
        "BBU/儲能與矽光子題材升溫，市場關注台達電、台光電、台燿",
        "高股息ETF、金融股與航運股討論度同步增加",
    ]
    return [{"source": "MVP fallback", "title": t, "summary": "示範資料", "url": "", "query": "fallback", "published_at": now, "engagement": 0} for t in titles]


def enrich(item: dict) -> None:
    text = f"{item['title']} {item['summary']}"
    normalized = text.upper()
    stocks = []
    seen = set()
    for code, name, aliases in STOCKS:
        if any(contains_alias(normalized, alias) for alias in aliases):
            if code not in seen:
                stocks.append({"code": code, "name": name})
                seen.add(code)
    topics = [name for name, aliases in TOPICS if any(contains_alias(normalized, alias) for alias in aliases)]
    score = sum(text.count(term) for term in POSITIVE) - sum(text.count(term) for term in NEGATIVE)
    item["stocks"] = stocks
    item["topics"] = topics
    item["sentiment_score"] = score
    item["sentiment"] = "偏樂觀" if score >= 2 else "偏保守" if score <= -2 else "中性"


def analyze(items: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    stocks = rank_entities(items, "stocks", now)
    topics = rank_entities(items, "topics", now)
    momentum = rank_momentum(items, now)
    sentiment = sorted(stocks, key=lambda row: (abs(row["sentiment_sum"]), row["mentions"]), reverse=True)
    top_topics = "、".join(row["name"] for row in topics[:3]) or "尚未形成明確題材"
    top_stocks = "、".join(f"{row['name']}({row['code']})" for row in stocks[:4]) or "尚未抓到明確個股"
    surges = "、".join(row["name"] for row in momentum[:3]) or top_topics
    return {
        "items": items,
        "stocks": stocks,
        "topics": topics,
        "momentum": momentum,
        "sentiment": sentiment,
        "headline": f"市場今天主要在討論：{top_topics}。被提到最多的個股是 {top_stocks}；短線突然升溫的題材集中在 {surges}。",
    }


def rank_entities(items: list[dict], field: str, now: datetime) -> list[dict]:
    bucket: dict[str, dict] = {}
    for item in items:
        heat = article_heat(item, now)
        for entity in item[field]:
            if isinstance(entity, dict):
                key, name, code = entity["code"], entity["name"], entity["code"]
            else:
                key, name, code = entity, entity, ""
            row = bucket.setdefault(key, {"code": code, "name": name, "mentions": 0, "heat": 0.0, "sources": set(), "sentiment_sum": 0, "latest_title": "", "latest_url": "", "latest_at": item["published_at"]})
            row["mentions"] += 1
            row["heat"] += heat
            row["sources"].add(item["source"])
            row["sentiment_sum"] += item["sentiment_score"]
            if item["published_at"] >= row["latest_at"]:
                row["latest_at"] = item["published_at"]
                row["latest_title"] = item["title"]
                row["latest_url"] = item["url"]
    rows = []
    tz = timezone(timedelta(hours=8))
    for row in bucket.values():
        rows.append({**row, "sources": len(row["sources"]), "heat": round(row["heat"] + row["mentions"] * 1.6 + len(row["sources"]) * 1.2, 2), "sentiment": sentiment_label(row["sentiment_sum"]), "latest_at": row["latest_at"].astimezone(tz).strftime("%m/%d %H:%M")})
    return sorted(rows, key=lambda row: (row["heat"], row["mentions"]), reverse=True)


def rank_momentum(items: list[dict], now: datetime) -> list[dict]:
    recent_since = now - timedelta(hours=6)
    counts = defaultdict(lambda: {"recent": 0, "older": 0, "sources": set(), "latest_title": ""})
    for item in items:
        entities = set(item["topics"]) | {stock["name"] for stock in item["stocks"]}
        for entity in entities:
            if item["published_at"] >= recent_since:
                counts[entity]["recent"] += 1
                counts[entity]["latest_title"] = item["title"]
            else:
                counts[entity]["older"] += 1
            counts[entity]["sources"].add(item["source"])
    rows = []
    for name, row in counts.items():
        if row["recent"]:
            baseline = max(row["older"] / 5, 0.4)
            rows.append({"name": name, "recent_mentions": row["recent"], "older_mentions": row["older"], "momentum": round(row["recent"] / baseline, 2), "sources": len(row["sources"]), "latest_title": row["latest_title"]})
    return sorted(rows, key=lambda row: (row["momentum"], row["recent_mentions"]), reverse=True)


def article_heat(item: dict, now: datetime) -> float:
    age_hours = max((now - item["published_at"]).total_seconds() / 3600, 0)
    return 3 + max(0.2, 1.8 - age_hours / 18) + abs(item["sentiment_score"]) * 0.35


def render_html(analysis: dict) -> str:
    generated_at = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    topic_chart = bar_chart(analysis["topics"], "name", "heat", "#0f766e")
    stock_rows = [{**row, "label": f"{row['name']} {row['code']}"} for row in analysis["stocks"]]
    stock_chart = bar_chart(stock_rows, "label", "heat", "#2563eb")
    sankey_html = sankey(analysis["items"])
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Threads 台股市場熱度雷達</title><style>body{{margin:0;font-family:'Microsoft JhengHei','Noto Sans TC',Arial,sans-serif;background:#f8fafc;color:#111827}}.wrap{{max-width:1240px;margin:0 auto;padding:28px 22px 42px}}.top{{display:flex;justify-content:space-between;gap:18px;align-items:end;margin-bottom:18px}}h1{{margin:0;font-size:30px}}h2{{font-size:19px;margin:0 0 12px}}.muted{{color:#64748b;font-size:14px}}.headline{{border-left:5px solid #0f766e;background:#fff;border-radius:8px;padding:16px 18px;line-height:1.8;font-size:17px;margin-bottom:16px}}.metrics,.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}.metric,.panel{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 1px 2px rgba(15,23,42,.04)}}.metric{{padding:14px}}.metric .label{{color:#64748b;font-size:13px;margin-bottom:8px}}.metric .value{{font-size:26px;font-weight:700}}.panel{{padding:16px;overflow:hidden;margin-bottom:16px}}table{{width:100%;border-collapse:collapse;font-size:14px;background:#fff}}th,td{{padding:10px 9px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}th{{color:#334155;background:#f1f5f9;position:sticky;top:0}}.table-scroll{{max-height:480px;overflow:auto;border:1px solid #e5e7eb;border-radius:8px}}a{{color:#2563eb;text-decoration:none}}@media(max-width:900px){{.metrics,.grid{{grid-template-columns:1fr}}.top{{display:block}}}}</style></head><body><main class='wrap'><div class='top'><div><h1>Threads 台股市場熱度雷達</h1><div class='muted'>GitHub Pages 雲端自動更新版</div></div><div class='muted'>產生時間：{generated_at}</div></div><section class='headline'>{esc(analysis['headline'])}</section><section class='metrics'><div class='metric'><div class='label'>近 36 小時訊號</div><div class='value'>{len(analysis['items'])}</div></div><div class='metric'><div class='label'>熱門股票數</div><div class='value'>{len(analysis['stocks'])}</div></div><div class='metric'><div class='label'>熱門題材數</div><div class='value'>{len(analysis['topics'])}</div></div><div class='metric'><div class='label'>最後訊號</div><div class='value'>{latest_time(analysis['items'])}</div></div></section><section class='grid'><div class='panel'><h2>今日最熱產業</h2>{topic_chart}</div><div class='panel'><h2>今日最熱股票</h2>{stock_chart}</div></section><section class='grid'><div class='panel'><h2>突然暴增題材</h2>{table(analysis['momentum'], ['name','momentum','recent_mentions','older_mentions','sources','latest_title'])}</div><div class='panel'><h2>情緒榜</h2>{table(analysis['sentiment'], ['code','name','sentiment','sentiment_sum','mentions','latest_title'])}</div></section><section class='panel'><h2>資金流向圖：題材 → 受惠股</h2>{sankey_html}</section><section class='panel'><h2>來源訊號</h2>{source_table(analysis['items'])}</section><p class='muted'>資料來源：公開新聞/RSS fallback。MVP 以討論熱度排序，不構成投資建議。</p></main></body></html>"""


def bar_chart(rows: list[dict], y_col: str, x_col: str, color: str) -> str:
    if not rows:
        return "<p class='muted'>目前沒有足夠資料。</p>"
    chart_rows = sorted(rows[:8], key=lambda row: row[x_col])
    fig = px.bar(chart_rows, x=x_col, y=y_col, orientation="h", text=x_col)
    fig.update_traces(marker_color=color, texttemplate="%{text:.1f}", textposition="outside")
    fig.update_layout(height=350, margin=dict(l=0, r=20, t=4, b=8), xaxis_title="熱度分數", yaxis_title="", plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", font=dict(family="Microsoft JhengHei, Arial"))
    return fig.to_html(full_html=False, include_plotlyjs="cdn", config={"displayModeBar": False})


def sankey(items: list[dict]) -> str:
    links = {}
    for item in items:
        for topic in item["topics"]:
            for stock in item["stocks"]:
                key = (topic, f"{stock['name']}({stock['code']})")
                links[key] = links.get(key, 0) + 1
    if not links:
        return "<p class='muted'>目前沒有足夠資料。</p>"
    top_links = sorted(links.items(), key=lambda pair: pair[1], reverse=True)[:18]
    labels = list(dict.fromkeys([src for (src, _), _ in top_links] + [dst for (_, dst), _ in top_links]))
    index = {label: idx for idx, label in enumerate(labels)}
    fig = go.Figure(data=[go.Sankey(node=dict(label=labels, pad=18, thickness=18, color="#e2e8f0"), link=dict(source=[index[src] for (src, _), _ in top_links], target=[index[dst] for (_, dst), _ in top_links], value=[value for _, value in top_links], color="rgba(15,118,110,.28)"))])
    fig.update_layout(height=480, margin=dict(l=8, r=8, t=6, b=6), paper_bgcolor="#ffffff")
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})


def table(rows: list[dict], columns: list[str], limit: int = 18) -> str:
    if not rows:
        return "<p class='muted'>目前沒有足夠資料。</p>"
    labels = {"code":"代號","name":"名稱","heat":"熱度","mentions":"提及","sources":"來源數","sentiment":"情緒","sentiment_sum":"情緒分","latest_title":"最新訊號","momentum":"暴增倍數","recent_mentions":"近 6 小時","older_mentions":"較早"}
    header = "".join(f"<th>{labels.get(col, col)}</th>" for col in columns)
    body = "".join("<tr>" + "".join(f"<td>{esc(row.get(col, ''))}</td>" for col in columns) + "</tr>" for row in rows[:limit])
    return f"<div class='table-scroll'><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"


def source_table(items: list[dict]) -> str:
    tz = timezone(timedelta(hours=8))
    rows = []
    for item in items[:80]:
        title = esc(item["title"])
        link = f"<a href='{esc(item['url'])}' target='_blank' rel='noreferrer'>{title}</a>" if item["url"] else title
        rows.append((item["published_at"].astimezone(tz).strftime("%m/%d %H:%M"), item["source"], link, "、".join(f"{s['name']}({s['code']})" for s in item["stocks"]), "、".join(item["topics"])))
    header = "".join(f"<th>{h}</th>" for h in ["時間", "來源", "標題", "股票", "題材"])
    body = "".join(f"<tr><td>{esc(t)}</td><td>{esc(src)}</td><td>{title}</td><td>{esc(stocks)}</td><td>{esc(topics)}</td></tr>" for t, src, title, stocks, topics in rows)
    return f"<div class='table-scroll'><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"


def clean(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(" ".join(text.split()))


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


def latest_time(items: list[dict]) -> str:
    if not items:
        return "-"
    return max(item["published_at"] for item in items).astimezone(timezone(timedelta(hours=8))).strftime("%m/%d %H:%M")


def sentiment_label(score: int) -> str:
    return "偏樂觀" if score >= 2 else "偏保守" if score <= -2 else "中性"


def esc(value: object) -> str:
    return html.escape(str(value) if value is not None else "", quote=True)


if __name__ == "__main__":
    main()
