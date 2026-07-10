from __future__ import annotations

import html
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

ROOT = Path(__file__).resolve().parent
SITE_DIR = ROOT / "site"
DATA_DIR = SITE_DIR / "data"
HISTORY_DIR = DATA_DIR / "history"
INDEX_PATH = SITE_DIR / "index.html"
JSON_PATH = DATA_DIR / "latest.json"
RSS_ENDPOINT = "https://news.google.com/rss/search?q={query}+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
TAIPEI_TZ = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 證交所公開資料端點（免金鑰）。這是「事實層」的來源，跟新聞聲量完全獨立：
#   T86        三大法人個股買賣超（每交易日約 16:30 後公布）→ 也拿來當「今天有沒有交易」的判準，
#              因為臨時休市（颱風假）不會出現在排定假日行事曆裡，只有「當天根本沒有資料」這件事是可靠的。
#   STOCK_DAY  個股當月每日成交（收盤價、漲跌價差、成交股數）→ 算漲跌% 與量比（今日量/前5日均量）。
#   HOLIDAY    排定休市行事曆 → 只用來解釋「為什麼今天沒資料」（週末/排定假日/臨時休市三種文案）。
# 與 market_radar_cloud.py 內同名區塊保持同步，修改請兩份一起改。
# ---------------------------------------------------------------------------
TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86?date={date}&selectType=ALLBUT0999&response=json"
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={date}&stockNo={code}&response=json"
TWSE_HOLIDAY_URL = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
HTTP_HEADERS = {"User-Agent": "market-radar-pro/0.3"}
INST_BUY_LOTS = 500      # 三大法人買超達此張數，判讀才視為「法人實買」
INST_SELL_LOTS = -500    # 賣超達此張數，判讀視為「法人實賣」
VOLUME_SURGE_RATIO = 1.8 # 今日量 / 前5日均量 達此倍數視為爆量
SOCIAL_HOT_SCORE = 55    # 社群相對分數（0-100）達此值視為「社群熱」


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
        "label": '市場新聞',
        "subtitle": '媒體報導的資金動向（僅新聞聲量，真實數據見法人買賣超欄位）',
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
    facts = fetch_market_facts([stock["code"] for stock in STOCKS])
    layers = {layer: summarize_layer(items, layer) for layer in LAYERS}
    cross = build_cross_analysis(layers, facts)
    consensus = build_consensus(layers, items)
    watchlist = cross[:5]
    headline = market_status_prefix(facts) + build_headline(consensus, watchlist)
    notes = [
        '「三大法人買賣超」「收盤/漲跌%」「量比」為證交所公布之真實交易數據（T86 / STOCK_DAY），非新聞聲量。',
        '「社群熱度」「話題分數」仍為 Google News 公開 RSS 的新聞聲量推估，並非 Threads/PTT 官方 API，情緒判斷僅為關鍵字正負計數。',
        '判讀矩陣門檻：法人買/賣超 ±' + str(INST_BUY_LOTS) + ' 張、社群相對分數 ' + str(SOCIAL_HOT_SCORE) + '、量比 ' + str(VOLUME_SURGE_RATIO) + ' 倍，皆為可調參數而非最佳化結果。',
        '本工具是「今天該研究什麼」的清單產生器，不是進場訊號：上榜 → 等收盤確認法人是否真的買 → 隔日看是否延續，再決定要不要動作。',
    ]
    if not facts["ok"]:
        notes.insert(0, '本次證交所市場數據抓取失敗，量價與法人欄位缺漏，僅剩新聞聲量層，判讀可信度大幅下降。')
    if used_fallback:
        headline = '【示範假資料，非即時訊號】' + headline
        notes.insert(0, '本次即時新聞抓取全部失敗，以下內容改用示範用假資料（fallback），並非真實市場訊號，請勿作為投資判斷依據。')
    return {
        "generated_at": datetime.now(TAIPEI_TZ).isoformat(),
        "data_quality": "fallback" if used_fallback else "live",
        "market_facts": {k: facts[k] for k in ("ok", "trade_date", "market_open_today", "status")},
        "headline": headline,
        "layers": layers,
        "cross_analysis": cross,
        "consensus": consensus,
        "watchlist": watchlist,
        "source_items": serialize_items(items[:120]),
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# 事實層：證交所真實數據
# ---------------------------------------------------------------------------

def fetch_market_facts(codes: list[str]) -> dict:
    """抓取最近交易日的三大法人買賣超與個股量價，並判斷今天是否為交易日。

    回傳：
      ok                bool  是否成功取得任何市場數據
      trade_date        str   最近一個有資料的交易日（ISO），None 表示連續多日都抓不到
      market_open_today bool  今天是否有成交（以 T86 當日有無資料為準，抓得到颱風臨時休市）
      status            str   給讀者看的市場狀態說明
      t86               dict  {code: {"foreign_lots","trust_lots","total_lots"}} 單位：張
      quotes            dict  {code: {"close","change_pct","volume_lots","volume_ratio","quote_date"}}
    """
    facts = {"ok": False, "trade_date": None, "market_open_today": None, "status": "", "t86": {}, "quotes": {}}
    today = datetime.now(TAIPEI_TZ).date()
    t86_payload = None
    probe = today
    for _ in range(8):
        payload = fetch_json(TWSE_T86_URL.format(date=probe.strftime("%Y%m%d")))
        if payload and payload.get("stat") == "OK" and payload.get("data"):
            t86_payload = payload
            facts["trade_date"] = probe.isoformat()
            break
        probe -= timedelta(days=1)
        time.sleep(0.3)
    if t86_payload is None:
        facts["status"] = '證交所資料抓取失敗（連續 8 天無 T86 資料），本次僅有新聞聲量，無任何真實交易數據。'
        return facts

    facts["ok"] = True
    facts["market_open_today"] = facts["trade_date"] == today.isoformat()
    trade_label = facts["trade_date"][5:].replace("-", "/")
    if facts["market_open_today"]:
        facts["status"] = f'今日（{today.strftime("%m/%d")}）為交易日，法人與量價為今日收盤後公布數據。'
    else:
        facts["status"] = (
            f'今日（{today.strftime("%m/%d")}）{closed_reason(today)}，市場沒有任何成交；'
            f'以下量價與法人數據為最近交易日 {trade_label} 的收盤資料，今日的新聞熱度不對應任何真實資金流動。'
        )

    wanted = set(codes)
    for row in t86_payload.get("data", []):
        code = str(row[0]).strip()
        if code not in wanted:
            continue
        # T86 fields 索引：4=外陸資買賣超股數、10=投信買賣超股數、最後一欄=三大法人買賣超股數，單位為股
        facts["t86"][code] = {
            "foreign_lots": shares_to_lots(row[4]),
            "trust_lots": shares_to_lots(row[10]),
            "total_lots": shares_to_lots(row[-1]),
        }

    day_param = facts["trade_date"].replace("-", "")
    for code in codes:
        payload = fetch_json(TWSE_STOCK_DAY_URL.format(date=day_param, code=code))
        time.sleep(0.35)  # 溫和抓取，避免被證交所限流
        if not payload or payload.get("stat") != "OK":
            continue
        rows = [r for r in payload.get("data", []) if to_num(r[6]) is not None]
        if not rows:
            continue
        last = rows[-1]
        close = to_num(last[6])
        diff = signed_num(last[7])  # 漲跌價差，格式如 "+95.00" / "-40.00" / "X0.00"
        volume_lots = (to_num(last[1]) or 0) / 1000
        prev_volumes = [(to_num(r[1]) or 0) / 1000 for r in rows[:-1]][-5:]
        avg_volume = sum(prev_volumes) / len(prev_volumes) if prev_volumes else None
        prev_close = close - diff if (close is not None and diff is not None) else None
        facts["quotes"][code] = {
            "close": close,
            "change_pct": round(diff / prev_close * 100, 2) if prev_close else None,
            "volume_lots": round(volume_lots),
            "volume_ratio": round(volume_lots / avg_volume, 2) if avg_volume else None,
            "quote_date": last[0],
        }
    return facts


def closed_reason(today: date) -> str:
    """今天沒有 T86 資料時，解釋原因：週末／排定假日／臨時休市或尚未公布。"""
    if today.weekday() >= 5:
        return '為週末休市'
    holidays = fetch_json(TWSE_HOLIDAY_URL)
    if isinstance(holidays, list):
        roc_today = f"{today.year - 1911}{today.strftime('%m%d')}"
        for row in holidays:
            if str(row.get("Date", "")) == roc_today:
                name = row.get("Name", "假日")
                return f'為排定休市（{name}）'
    return '無成交資料（可能為颱風等臨時休市，或今日尚未收盤/證交所尚未公布）'


def market_status_prefix(facts: dict) -> str:
    if not facts["ok"]:
        return '【市場數據缺漏】'
    if facts["market_open_today"] is False:
        return f'【今日休市或無成交資料，資金數據為 {facts["trade_date"][5:].replace("-", "/")} 收盤】'
    return ''


def shares_to_lots(value: object) -> float | None:
    num = to_num(value)
    return round(num / 1000) if num is not None else None


def to_num(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text in ("--", "-", "X"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def signed_num(value: object) -> float | None:
    """解析 STOCK_DAY 漲跌價差欄位：'+95.00' / '-40.00' / 'X0.00'（不比價）。"""
    text = str(value or "").replace(",", "").strip()
    if not text or text.upper().startswith("X"):
        return 0.0
    return to_num(text)


def fetch_json(url: str) -> object | None:
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=20)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"Fetch failed for {url}: {exc}")
        return None


# ---------------------------------------------------------------------------
# 話題層：新聞聲量
# ---------------------------------------------------------------------------

def collect_items() -> list[dict]:
    rows = []
    # 去重採「每層獨立」而非全域共用，避免同一篇文章因為先被 social 層抓到，
    # 就永遠不會被計入 institutional / market 層，導致後面的層系統性被低估。
    seen_by_layer: dict[str, set] = {layer: set() for layer in LAYERS}
    for layer, config in LAYERS.items():
        seen = seen_by_layer[layer]
        for query in config["queries"]:
            try:
                response = requests.get(RSS_ENDPOINT.format(query=quote_plus(query)), headers=HTTP_HEADERS, timeout=15)
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
    # 雜訊過濾：只有掛得到個股或題材的訊號才算「有效」；Threads 當機、颱風假、NBA 之類
    # 完全無關的新聞仍列入原始數，但不再灌水「今日訊號數」。
    matched = [item for item in layer_items if item["stocks"] or item["topics"]]
    return {
        "label": LAYERS[layer]["label"],
        "subtitle": LAYERS[layer]["subtitle"],
        "signal_count": len(matched),
        "raw_signal_count": len(layer_items),
        "top_stocks": rank_entities(matched, "stocks")[:12],
        "top_topics": rank_entities(matched, "topics")[:12],
        "top_events": top_events(matched),
    }


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


# ---------------------------------------------------------------------------
# 交叉分析：話題（新聞聲量）× 事實（真實量價與法人買賣超）
# ---------------------------------------------------------------------------

def build_cross_analysis(layers: dict, facts: dict) -> list[dict]:
    stocks: dict[str, dict] = {}
    name_by_code = {stock["code"]: stock["name"] for stock in STOCKS}
    for layer, summary in layers.items():
        for row in summary["top_stocks"]:
            item = stocks.setdefault(row["code"], {"code": row["code"], "name": row["name"], "social_heat": 0, "inst_mentions": 0, "market_news_mentions": 0})
            if layer == "social":
                item["social_heat"] = max(item["social_heat"], row["heat"])
            elif layer == "institutional":
                item["inst_mentions"] += row["mentions"]
            elif layer == "market":
                item["market_news_mentions"] += row["mentions"]
    # 「法人默默買」是最有價值的訊號之一：股票池裡法人大買但新聞完全沒討論的股票，
    # 也要進交叉分析，否則永遠只看得到已經很熱的名字。
    for code, inst in facts["t86"].items():
        total = inst.get("total_lots")
        if code not in stocks and total is not None and abs(total) >= INST_BUY_LOTS:
            stocks[code] = {"code": code, "name": name_by_code.get(code, code), "social_heat": 0, "inst_mentions": 0, "market_news_mentions": 0}

    max_social = max([v["social_heat"] for v in stocks.values()] or [1])
    max_inst = max([v["inst_mentions"] for v in stocks.values()] or [1])
    max_market = max([v["market_news_mentions"] for v in stocks.values()] or [1])
    rows = []
    for row in stocks.values():
        social_score = 100 * row["social_heat"] / max_social if max_social else 0
        inst_score = 100 * row["inst_mentions"] / max_inst if max_inst else 0
        market_score = 100 * row["market_news_mentions"] / max_market if max_market else 0
        buzz_score = round(0.45 * social_score + 0.35 * inst_score + 0.20 * market_score)
        inst_data = facts["t86"].get(row["code"])
        quote = facts["quotes"].get(row["code"])
        rows.append({
            **row,
            "buzz_score": buzz_score,
            "close": quote["close"] if quote else None,
            "change_pct": quote["change_pct"] if quote else None,
            "volume_lots": quote["volume_lots"] if quote else None,
            "volume_ratio": quote["volume_ratio"] if quote else None,
            "inst_net_lots": inst_data["total_lots"] if inst_data else None,
            "inst_display": format_lots(inst_data["total_lots"] if inst_data else None),
            "signal": judge_signal(social_score, inst_data, quote, facts),
        })
    # 排序：先看「有事實支撐的熱度」——法人實買的排前面，再依話題分數
    rows.sort(key=lambda r: ((r["inst_net_lots"] or 0) >= INST_BUY_LOTS, r["buzz_score"]), reverse=True)
    return rows


def judge_signal(social_score: float, inst_data: dict | None, quote: dict | None, facts: dict) -> str:
    """熱度 × 事實判讀矩陣。話題告訴你「該看哪裡」，法人與量價告訴你「錢有沒有真的進來」。"""
    if not facts["ok"]:
        return '無市場數據，僅新聞聲量，不足以判讀'
    net = inst_data.get("total_lots") if inst_data else None
    hot = social_score >= SOCIAL_HOT_SCORE
    if net is None:
        base = '社群熱但查無法人資料' if hot else '待觀察（無法人資料）'
    elif hot and net >= INST_BUY_LOTS:
        base = '社群熱＋法人實買：動能確認，再查位階與基本面'
    elif hot and net <= INST_SELL_LOTS:
        base = '社群熱但法人賣超：話題與資金背離，追價風險高'
    elif hot:
        base = '社群熱、法人觀望：純題材，先等法人動向'
    elif net >= INST_BUY_LOTS:
        base = '法人買超但討論度低：早期訊號，值得研究'
    elif net <= INST_SELL_LOTS:
        base = '法人賣超、討論度低：留意風險'
    else:
        base = '待觀察'
    if quote and quote.get("volume_ratio") and quote["volume_ratio"] >= VOLUME_SURGE_RATIO:
        base += f'（爆量 ×{quote["volume_ratio"]}）'
    if facts["market_open_today"] is False:
        base += '［非今日成交］'
    return base


def format_lots(net_lots: float | None) -> str:
    if net_lots is None:
        return '－'
    if net_lots > 0:
        return f'買超 {int(net_lots):,} 張'
    if net_lots < 0:
        return f'賣超 {abs(int(net_lots)):,} 張'
    return '持平'


def build_consensus(layers: dict, items: list[dict]) -> dict:
    inst = layers["institutional"]
    market = layers["market"]
    return {"report_count": inst["signal_count"], "common_topics": merge_ranked_names([inst["top_topics"], market["top_topics"]])[:8], "common_stocks": merge_ranked_names([inst["top_stocks"], market["top_stocks"]])[:10], "events": [event["title"] for event in top_events(items)[:8]]}


def build_headline(consensus: dict, watchlist: list[dict]) -> str:
    topics = '、'.join(consensus["common_topics"][:4]) or '市場焦點仍在形成'
    stocks = '、'.join(row["name"] for row in watchlist[:5]) or '尚無明顯共識股'
    return '今天市場主要討論：' + topics + '；話題與資金交叉檢驗值得追蹤：' + stocks + '。'


def write_outputs(analysis: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(analysis, ensure_ascii=False, indent=2)
    JSON_PATH.write_text(payload, encoding="utf-8")
    # 每日留檔：累積歷史快照後才能回測「上榜股票後 N 日報酬」，
    # 這是驗證這台雷達有沒有真實 edge 的唯一方法。
    history_path_for(analysis).write_text(payload, encoding="utf-8")
    INDEX_PATH.write_text(render_html(analysis), encoding="utf-8")


def history_path_for(analysis: dict) -> Path:
    day = str(analysis.get("generated_at", ""))[:10] or datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")
    return HISTORY_DIR / f"{day}.json"


# ---------------------------------------------------------------------------
# 版面輸出
# ---------------------------------------------------------------------------

def render_html(data: dict) -> str:
    title = '市場熱度雷達 Pro'
    subtitle = '話題層（社群／券商／市場新聞）× 事實層（證交所法人買賣超與量價）'
    banners = []
    if data.get("data_quality") == "fallback":
        banners.append(banner_html('注意：本次即時新聞抓取全部失敗，以下內容為示範用假資料（fallback），並非真實市場訊號，請勿作為投資判斷依據。', "#fee2e2", "#fca5a5", "#991b1b"))
    market_facts = data.get("market_facts", {})
    status_text = market_facts.get("status", "")
    if status_text:
        if not market_facts.get("ok"):
            banners.append(banner_html(status_text, "#fee2e2", "#fca5a5", "#991b1b"))
        elif market_facts.get("market_open_today") is False:
            banners.append(banner_html(status_text, "#fef3c7", "#fcd34d", "#92400e"))
        else:
            banners.append(banner_html(status_text, "#ecfdf5", "#6ee7b7", "#065f46"))
    notes_html = "".join(f"<li>{esc(note)}</li>" for note in data.get("notes", []))
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>{esc(title)}</title><style>body{{margin:0;background:#f8fafc;color:#111827;font-family:'Microsoft JhengHei','Noto Sans TC',Arial,sans-serif}}.wrap{{max-width:1280px;margin:0 auto;padding:28px 22px 44px}}.top{{display:flex;justify-content:space-between;align-items:end;gap:16px;margin-bottom:18px}}h1{{margin:0;font-size:30px}}h2{{margin:0 0 12px;font-size:19px}}.muted{{color:#64748b;font-size:14px}}.headline{{border-left:5px solid #0f766e;background:#fff;border-radius:8px;padding:16px 18px;line-height:1.8;font-size:17px;margin-bottom:16px}}.grid3{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:16px}}.grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-bottom:16px}}.panel{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;box-shadow:0 1px 2px rgba(15,23,42,.04);overflow:hidden}}.score{{font-size:28px;font-weight:700;margin-top:8px}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:10px 9px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}th{{background:#f1f5f9;color:#334155}}.table-scroll{{max-height:520px;overflow:auto;border:1px solid #e5e7eb;border-radius:8px}}.tag{{display:inline-block;background:#ecfeff;color:#0f766e;border:1px solid #99f6e4;border-radius:999px;padding:4px 9px;margin:0 6px 6px 0;font-size:13px}}.footnote{{font-size:12px;color:#64748b;line-height:1.7}}@media(max-width:980px){{.grid3,.grid2,.top{{display:block}}.panel{{margin-bottom:14px}}}}</style></head><body><main class='wrap'><div class='top'><div><h1>{esc(title)}</h1><div class='muted'>{esc(subtitle)}</div></div><div class='muted'>{esc('更新時間：')}{esc(format_time(data['generated_at']))}</div></div>{''.join(banners)}<section class='headline'>{esc(data['headline'])}</section><section class='grid3'>{render_layer_cards(data['layers'])}</section><section class='grid2'><div class='panel'><h2>{esc('法人研究共識（新聞聲量）')}</h2>{render_consensus(data['consensus'])}</div><div class='panel'><h2>{esc('觀察名單：話題 × 資金交叉檢驗前 5 檔')}</h2>{render_table(data['watchlist'], watch_columns())}</div></section><section class='panel'><h2>{esc('市場熱度交叉分析（話題聲量 vs 證交所真實數據）')}</h2>{render_table(data['cross_analysis'][:18], cross_columns())}</section><section class='panel' style='margin-top:16px'><h2>{esc('來源明細')}</h2>{render_sources(data['source_items'])}</section><section class='panel footnote'><h2 style='font-size:15px'>{esc('資料與方法限制說明')}</h2><ul>{notes_html}</ul></section></main></body></html>"""


def banner_html(text: str, bg: str, border: str, color: str) -> str:
    return f"<section style='background:{bg};border:1px solid {border};color:{color};border-radius:8px;padding:12px 16px;margin-bottom:16px;font-weight:600'>{esc(text)}</section>"


def render_layer_cards(layers: dict) -> str:
    cards = []
    for key in ["social", "institutional", "market"]:
        layer = layers[key]
        topics = "".join(f"<span class='tag'>{esc(row['name'])}</span>" for row in layer["top_topics"][:5])
        stocks = '、'.join(row["name"] for row in layer["top_stocks"][:5]) or '尚未辨識到個股'
        raw = layer.get("raw_signal_count", layer["signal_count"])
        cards.append(f"<div class='panel'><h2>{esc(layer['label'])}</h2><div class='muted'>{esc(layer['subtitle'])}</div><div class='score'>{layer['signal_count']}</div><div class='muted'>{esc(f'今日有效訊號數（原始抓到 {raw} 則，其餘與股市無關已排除）')}</div><p><b>{esc('熱門題材')}</b></p>{topics}<p><b>{esc('相關個股')}</b><br>{esc(stocks)}</p></div>")
    return "".join(cards)


def render_consensus(consensus: dict) -> str:
    topics = "".join(f"<span class='tag'>{esc(topic)}</span>" for topic in consensus["common_topics"][:8])
    stocks = "".join(f"<span class='tag'>{esc(stock)}</span>" for stock in consensus["common_stocks"][:10])
    events = "".join(f"<li>{esc(event)}</li>" for event in consensus["events"][:6])
    return f"<p>{esc('今日法人／研究訊號共')} <b>{consensus['report_count']}</b> {esc('則')}</p><p><b>{esc('共同關注題材')}</b></p>{topics}<p><b>{esc('共同看好股票')}</b></p>{stocks}<p><b>{esc('今日關注事件')}</b></p><ul>{events}</ul>"


def watch_columns() -> list[tuple[str, str]]:
    return [("name", '股票'), ("close", '收盤'), ("change_pct", '漲跌%'), ("inst_display", '三大法人買賣超'), ("volume_ratio", '量比*'), ("signal", '判讀')]


def cross_columns() -> list[tuple[str, str]]:
    return [("name", '股票'), ("close", '收盤'), ("change_pct", '漲跌%'), ("volume_lots", '成交量(張)'), ("volume_ratio", '量比*'), ("inst_display", '三大法人買賣超'), ("social_heat", '社群熱度'), ("inst_mentions", '券商提及'), ("buzz_score", '話題分數'), ("signal", '判讀')]


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
        cells = ""
        for key, _ in columns:
            value = row.get(key, '')
            if value is None:
                value = '－'
            cells += f"<td>{esc(value) if escape_values else value}</td>"
        body += f"<tr>{cells}</tr>"
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
