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


LAYERS = {
    "social": {
        "label": '社群熱度',
        "subtitle": 'Threads、PTT、Dcard：大家在討論什麼',
        "queries": ['台股 Threads', '台股 PTT Stock', '台股 Dcard 投資', 'AI伺服器 台股 討論', 'PCB CCL 台股 討論', '散熱 台股 討論', 'BBU 台股', '矽光子 CPO 台股'],
    },
    "institutional": {
        "label": '券商／投信研究',
        "subtitle": '法人看好什麼',
        "queries": ['券商晨報 台股 AI PCB', '投信觀點 台股 AI', '凱基投顧 台股', '群益投顧 台股', '玉山證券 市場觀點', '富邦投顧 研究報告', '野村投信 台股 AI', '元大投信 台股 ETF', '復華投信 台股', '國泰投信 產業觀點'],
    },
    "market": {
        "label": '市場數據',
        "subtitle": '資金是否真的流入',
        "queries": ['台股 法人 買超', '外資 買超 台股', '投信 買超 台股', '台股 成交量 爆量', '證交所 重大訊息', '法說會 台股', '外資 目標價 台股', '台股 技術面 突破'],
    },
}

# 每檔股票除了 code/name/aliases 外，可選填：
#   exclude:      文字命中此清單中的任一詞，就整段判定為誤判（例如「長榮航」屬於航空股 2618，不是航運股 2603）
#   require_any:  別名為通用詞彙時，必須同時命中清單中至少一詞才算數（例如「創意」太常見，需搭配 IC 設計相關字樣）
# 此清單與 market_radar_cloud.py 的 STOCKS 保持同步；未來新增/移除個股請兩個檔案一起改。
STOCKS = [
    {"code": "2330", "name": '台積電', "aliases": ['台積電', "TSMC", "2330"]},
    {"code": "2317", "name": '鴻海', "aliases": ['鴻海', "2317"]},
    {"code": "2454", "name": '聯發科', "aliases": ['聯發科', "2454"]},
    {"code": "2308", "name": '台達電', "aliases": ['台達電', '台達', "2308"]},
    {"code": "2382", "name": '廣達', "aliases": ['廣達', "2382"]},
    {"code": "3231", "name": '緯創', "aliases": ['緯創', "3231"]},
    {"code": "6669", "name": '緯穎', "aliases": ['緯穎', "6669"]},
    {"code": "3017", "name": '奇鋐', "aliases": ['奇鋐', "3017"]},
    {"code": "3324", "name": '雙鴻', "aliases": ['雙鴻', "3324"]},
    {"code": "2059", "name": '川湖', "aliases": ['川湖', "2059"]},
    {"code": "2383", "name": '台光電', "aliases": ['台光電', "2383"]},
    {"code": "6274", "name": '台燿', "aliases": ['台燿', "6274"]},
    {"code": "3037", "name": '欣興', "aliases": ['欣興', "3037"]},
    {"code": "8046", "name": '南電', "aliases": ['南電', "8046"]},
    {"code": "2303", "name": '聯電', "aliases": ['聯電', "UMC", "2303"]},
    {"code": "2408", "name": '南亞科', "aliases": ['南亞科', "2408"]},
    {"code": "3711", "name": '日月光投控', "aliases": ['日月光', "3711"]},
    {"code": "3661", "name": '世芯-KY', "aliases": ['世芯', "3661"]},
    {
        "code": "3443", "name": '創意', "aliases": ['創意', "3443"],
        "require_any": ["3443", "IC設計", "IC 設計", "晶片", "設計服務", "台積電"],
    },
    {
        "code": "2603", "name": '長榮', "aliases": ['長榮', "2603"],
        "exclude": ["長榮航", "長榮航空", "長榮空運", "長榮酒店", "長榮大學", "長榮集團旗下航空"],
    },
    {"code": "2609", "name": '陽明', "aliases": ['陽明', "2609"]},
    {"code": "2881", "name": '富邦金', "aliases": ['富邦金', "2881"]},
    {"code": "2882", "name": '國泰金', "aliases": ['國泰金', "2882"]},
    {"code": "0050", "name": '元大台灣50', "aliases": ['元大台灣50', "0050"]},
    {"code": "00878", "name": '國泰永續高股息', "aliases": ['國泰永續高股息', "00878"]},
    {"code": "00919", "name": '群益台灣精選高息', "aliases": ['群益台灣精選高息', "00919"]},
]

TOPICS = [
    ("AI Server", ['AI伺服器', "AI server", "GB200", "GB300", "NVIDIA"]),
    ("PCB/CCL", ["PCB", "CCL", '載板', '高階板']),
    ("ASIC", ["ASIC", '特殊應用晶片']),
    ("CoWoS", ["CoWoS", '先進封裝']),
    ("CPO/SiPh", ['矽光子', "CPO", '光通訊']),
    ('散熱', ['散熱', '水冷', '液冷']),
    ("BBU/UPS", ["BBU", "UPS", '電池備援']),
    ('軍工/無人機', ['軍工', '無人機']),
    ('記憶體/DRAM', ['記憶體', "DRAM", "HBM", "DDR5"]),
    ('ETF配置', ["ETF", '高股息']),
]

POSITIVE = ['看好', '買進', '買超', '上修', '成長', '突破', '受惠']
NEGATIVE = ['看壞', '賣超', '下修', '風險', '警訊']


def main() -> None:
    analysis = build_market_radar()
    write_outputs(analysis)
    print(analysis["headline"])


def build_market_radar() -> dict:
    fetched = collect_items()
    used_fallback = not fetched
    items = fetched or fallback_items()
    for item in items:
        item.setdefault("is_fallback", False)
        enrich_item(item)
    layers = {layer: summarize_layer(items, layer) for layer in LAYERS}
    cross = build_cross_analysis(layers)
    consensus = build_consensus(layers, items)
    watchlist = cross[:5]
    headline = build_headline(consensus, watchlist)
    notes = [
        '目前為公開 RSS MVP，尚未接入 Threads 官方 API 與券商授權報告。',
        '三層（社群熱度／券商投信／市場數據）目前皆透過 Google News 公開 RSS 檢索，'
        '並非各自獨立的資料源；「交叉分析」反映的是關鍵字命中差異，而非真正跨來源驗證，請謹慎解讀。',
        '「資金話題度」「法人來源多樣度」為新聞聲量推估指標，不是官方公布的法人買賣超或投信申購數據。',
    ]
    if used_fallback:
        headline = '【示範假資料，非即時訊號】' + headline
        notes.insert(0, '本次即時新聞抓取全部失敗，以下內容改用示範用假資料（fallback），並非真實市場訊號，請勿作為投資判斷依據。')
    return {
        "generated_at": datetime.now(TAIPEI_TZ).isoformat(),
        "data_quality": "fallback" if used_fallback else "live",
        "headline": headline,
        "layers": layers,
        "cross_analysis": cross,
        "consensus": consensus,
        "watchlist": watchlist,
        "source_items": serialize_items(items[:120]),
        "notes": notes,
    }


def collect_items() -> list[dict]:
    rows = []
    # 去重採「每層獨立」而非全域共用，避免同一篇文章因為先被 social 層抓到，
    # 就永遠不會被計入 institutional / market 層，導致後面的層系統性被低估。
    seen_by_layer: dict[str, set] = {layer: set() for layer in LAYERS}
    headers = {"User-Agent": "market-radar-pro/0.2"}
    for layer, config in LAYERS.items():
        seen = seen_by_layer[layer]
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
    # 注意：這些是「示範用假資料」，只有在所有 RSS 抓取全部失敗時才會用到。
    # 內容一律標記 is_fallback=True，供 build_market_radar() 在輸出時加上明顯警示，
    # 避免讀者誤把示範標題當成真實市場訊號。
    now = datetime.now(timezone.utc)
    samples = [
        ("social", '（示範假資料）台股社群今天集中討論 AI Server、PCB/CCL、散熱與矽光子，台光電、奇鋐、川湖被重複點名。'),
        ("institutional", '（示範假資料）券商與投信觀點偏向 AI Server、CoWoS、CPO，共同看好台積電、台光電、奇鋐、緯穎。'),
        ("market", '（示範假資料）法人資金對電子權值與 AI 供應鏈偏多，PCB 與散熱成交量明顯放大。'),
    ]
    return [{"layer": layer, "query": "fallback", "source": "MVP fallback（非真實資料）", "title": title, "summary": "", "url": "", "published_at": now, "is_fallback": True} for layer, title in samples]


def enrich_item(item: dict) -> None:
    text = f"{item['title']} {item['summary']}"
    normalized = text.upper()
    item["stocks"] = [{"code": stock["code"], "name": stock["name"]} for stock in STOCKS if stock_matches(normalized, stock)]
    item["topics"] = [name for name, aliases in TOPICS if any(contains_alias(normalized, alias) for alias in aliases)]
    score = sum(text.count(term) for term in POSITIVE) - sum(text.count(term) for term in NEGATIVE)
    item["sentiment_score"] = score
    item["sentiment"] = '偏樂觀' if score >= 2 else '偏保守' if score <= -2 else '中性'


def stock_matches(normalized_text: str, stock: dict) -> bool:
    if not any(contains_alias(normalized_text, alias) for alias in stock["aliases"]):
        return False
    exclude = stock.get("exclude", [])
    if exclude and any(term.upper() in normalized_text for term in exclude):
        return False
    require_any = stock.get("require_any", [])
    if require_any and not any(term.upper() in normalized_text for term in require_any):
        return False
    return True


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
            signal = '社群很熱，法人尚未跟上'
        elif inst_score >= 70 and social_score < 40:
            signal = '法人先行，社群尚未發酵'
        elif social_score >= 55 and inst_score >= 55:
            signal = '社群與法人同步升溫'
        else:
            signal = '待持續追蹤'
        rows.append({**row, "capital_flow": star_rating(market_score), "ai_score": ai_score, "signal": signal})
    return sorted(rows, key=lambda row: row["ai_score"], reverse=True)


def build_consensus(layers: dict, items: list[dict]) -> dict:
    inst = layers["institutional"]
    market = layers["market"]
    return {"report_count": inst["signal_count"], "common_topics": merge_ranked_names([inst["top_topics"], market["top_topics"]])[:8], "common_stocks": merge_ranked_names([inst["top_stocks"], market["top_stocks"]])[:10], "events": [event["title"] for event in top_events(items)[:8]]}


def build_headline(consensus: dict, watchlist: list[dict]) -> str:
    topics = '、'.join(consensus["common_topics"][:4]) or '市場焦點仍在形成'
    stocks = '、'.join(row["name"] for row in watchlist[:5]) or '尚無明顯共識股'
    return '今天市場主要討論：' + topics + '；法人與資金共振值得追蹤：' + stocks + '。'


def write_outputs(analysis: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    INDEX_PATH.write_text(render_html(analysis), encoding="utf-8")


def render_html(data: dict) -> str:
    title = '市場熱度雷達 Pro'
    subtitle = '三層資訊引擎：社群熱度、券商／投信研究、市場數據'
    fallback_banner = ""
    if data.get("data_quality") == "fallback":
        fallback_banner = f"<section style='background:#fee2e2;border:1px solid #fca5a5;color:#991b1b;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-weight:600'>{esc('注意：本次即時新聞抓取全部失敗，以下內容為示範用假資料（fallback），並非真實市場訊號，請勿作為投資判斷依據。')}</section>"
    notes_html = "".join(f"<li>{esc(note)}</li>" for note in data.get("notes", []))
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>{esc(title)}</title><style>body{{margin:0;background:#f8fafc;color:#111827;font-family:'Microsoft JhengHei','Noto Sans TC',Arial,sans-serif}}.wrap{{max-width:1280px;margin:0 auto;padding:28px 22px 44px}}.top{{display:flex;justify-content:space-between;align-items:end;gap:16px;margin-bottom:18px}}h1{{margin:0;font-size:30px}}h2{{margin:0 0 12px;font-size:19px}}.muted{{color:#64748b;font-size:14px}}.headline{{border-left:5px solid #0f766e;background:#fff;border-radius:8px;padding:16px 18px;line-height:1.8;font-size:17px;margin-bottom:16px}}.grid3{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:16px}}.grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-bottom:16px}}.panel{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;box-shadow:0 1px 2px rgba(15,23,42,.04);overflow:hidden}}.score{{font-size:28px;font-weight:700;margin-top:8px}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:10px 9px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}th{{background:#f1f5f9;color:#334155}}.table-scroll{{max-height:520px;overflow:auto;border:1px solid #e5e7eb;border-radius:8px}}.tag{{display:inline-block;background:#ecfeff;color:#0f766e;border:1px solid #99f6e4;border-radius:999px;padding:4px 9px;margin:0 6px 6px 0;font-size:13px}}.footnote{{font-size:12px;color:#64748b;line-height:1.7}}@media(max-width:980px){{.grid3,.grid2,.top{{display:block}}.panel{{margin-bottom:14px}}}}</style></head><body><main class='wrap'><div class='top'><div><h1>{esc(title)}</h1><div class='muted'>{esc(subtitle)}</div></div><div class='muted'>{esc('更新時間：')}{esc(format_time(data['generated_at']))}</div></div>{fallback_banner}<section class='headline'>{esc(data['headline'])}</section><section class='grid3'>{render_layer_cards(data['layers'])}</section><section class='grid2'><div class='panel'><h2>{esc('AI 法人共識分析')}</h2>{render_consensus(data['consensus'])}</div><div class='panel'><h2>{esc('今日社群/法人共振評分最高的 5 檔股票')}</h2>{render_table(data['watchlist'], watch_columns())}</div></section><section class='panel'><h2>{esc('市場熱度交叉分析')}</h2>{render_table(data['cross_analysis'][:18], cross_columns())}</section><section class='panel' style='margin-top:16px'><h2>{esc('來源明細')}</h2>{render_sources(data['source_items'])}</section><section class='panel footnote'><h2 style='font-size:15px'>{esc('資料與方法限制說明')}</h2><ul>{notes_html}</ul></section></main></body></html>"""


def render_layer_cards(layers: dict) -> str:
    cards = []
    for key in ["social", "institutional", "market"]:
        layer = layers[key]
        topics = "".join(f"<span class='tag'>{esc(row['name'])}</span>" for row in layer["top_topics"][:5])
        stocks = '、'.join(row["name"] for row in layer["top_stocks"][:5]) or '尚未辨識到個股'
        cards.append(f"<div class='panel'><h2>{esc(layer['label'])}</h2><div class='muted'>{esc(layer['subtitle'])}</div><div class='score'>{layer['signal_count']}</div><div class='muted'>{esc('今日訊號數')}</div><p><b>{esc('熱門題材')}</b></p>{topics}<p><b>{esc('相關個股')}</b><br>{esc(stocks)}</p></div>")
    return "".join(cards)


def render_consensus(consensus: dict) -> str:
    topics = "".join(f"<span class='tag'>{esc(topic)}</span>" for topic in consensus["common_topics"][:8])
    stocks = "".join(f"<span class='tag'>{esc(stock)}</span>" for stock in consensus["common_stocks"][:10])
    events = "".join(f"<li>{esc(event)}</li>" for event in consensus["events"][:6])
    return f"<p>{esc('今日法人／研究訊號共')} <b>{consensus['report_count']}</b> {esc('則')}</p><p><b>{esc('共同關注題材')}</b></p>{topics}<p><b>{esc('共同看好股票')}</b></p>{stocks}<p><b>{esc('今日關注事件')}</b></p><ul>{events}</ul>"


def watch_columns() -> list[tuple[str, str]]:
    return [("name", '股票'), ("social_heat", '社群熱度'), ("broker_mentions", '券商提及'), ("fund_mentions", '法人來源多樣度*'), ("capital_flow", '資金話題度*'), ("ai_score", 'AI評分')]


def cross_columns() -> list[tuple[str, str]]:
    return [("name", '股票'), ("social_heat", 'Threads/社群熱度'), ("broker_mentions", '券商提及'), ("fund_mentions", '法人來源多樣度*'), ("market_mentions", '市場數據提及'), ("capital_flow", '資金話題度*'), ("ai_score", 'AI評分'), ("signal", '判讀')]


def render_sources(items: list[dict]) -> str:
    rows = []
    for item in items[:80]:
        title = f"<a href='{esc(item['url'])}' target='_blank' rel='noreferrer'>{esc(item['title'])}</a>" if item.get("url") else esc(item["title"])
        # source 欄位是 RSS 發布者名稱（外部可控輸入），連同其他欄位都要先 esc() 過，
        # 只有 title 因為本身就是刻意組出來的安全 <a> 標籤，才維持原樣輸出。
        rows.append({
            "layer_label": esc(LAYERS[item["layer"]]["label"]),
            "time": esc(format_time(item["published_at"])),
            "source": esc(item["source"]),
            "title": title,
            "stocks_text": esc('、'.join(stock["name"] for stock in item["stocks"])),
            "topics_text": esc('、'.join(item["topics"])),
        })
    cols = [("layer_label", '層級'), ("time", '時間'), ("source", '來源'), ("title", '標題'), ("stocks_text", '股票'), ("topics_text", '題材')]
    return render_table(rows, cols, escape_values=False)


def render_table(rows: list[dict], columns: list[tuple[str, str]], escape_values: bool = True) -> str:
    if not rows:
        return f"<p class='muted'>{esc('目前沒有足夠資料。')}</p>"
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
    if score <= 0:
        return '－'  # 無市場層資料時顯示「無資料」，避免看起來像有法人買超
    stars = max(1, min(5, math.ceil(score / 20)))
    return '★' * stars + '☆' * (5 - stars)


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
        # 排除股票代號恰好是年份的一部分，例如「2059年」不應命中股票代號 2059
        return bool(re.search(rf"(?<!\d){re.escape(alias_norm)}(?!\d)(?!年)", text))
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
