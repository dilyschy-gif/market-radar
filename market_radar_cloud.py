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
import plotly.express as px
import plotly.graph_objects as go
import requests

SITE_DIR = Path("site")
DATA_DIR = SITE_DIR / "data"
HISTORY_DIR = DATA_DIR / "history"
OUTPUT = SITE_DIR / "index.html"
RSS_ENDPOINT = "https://news.google.com/rss/search?q={query}+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
TAIPEI_TZ = timezone(timedelta(hours=8))
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

# ---------------------------------------------------------------------------
# 證交所公開資料端點（免金鑰）。「事實層」來源，跟新聞聲量完全獨立：
#   T86        三大法人個股買賣超 → 也拿來當「今天有沒有交易」的判準（颱風臨時休市
#              不會出現在排定假日行事曆，只有「當天根本沒資料」這件事是可靠的）。
#   STOCK_DAY  個股當月每日成交 → 算漲跌% 與量比（今日量/前5日均量）。
#   HOLIDAY    排定休市行事曆 → 只用來解釋「為什麼今天沒資料」。
# 與 market_radar_pro.py 內同名區塊保持同步，修改請兩份一起改。
# ---------------------------------------------------------------------------
TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86?date={date}&selectType=ALLBUT0999&response=json"
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={date}&stockNo={code}&response=json"
TWSE_HOLIDAY_URL = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
HTTP_HEADERS = {"User-Agent": "market-radar-github-actions/0.2"}
INST_BUY_LOTS = 500      # 三大法人買超達此張數，判讀才視為「法人實買」
INST_SELL_LOTS = -500    # 賣超達此張數，判讀視為「法人實賣」
VOLUME_SURGE_RATIO = 1.8 # 今日量 / 前5日均量 達此倍數視為爆量
SOCIAL_HOT_SCORE = 55    # 熱度相對分數（0-100）達此值視為「討論熱」

# 股票池與 market_radar_pro.py 保持同步（兩份主程式的股票池曾經不同步、輸出互相矛盾，
# 這裡改為聯集後的同一份清單；未來新增/移除個股請兩個檔案一起改）。
# exclude / require_any 用法同 market_radar_pro.py：
#   exclude:      命中即判定為誤判（例如「長榮航」是航空股 2618，不是航運股 2603）
#   require_any:  別名為通用詞彙時，需搭配清單中至少一詞才算數（例如「創意」需搭配 IC 設計相關字樣）
STOCKS = [
    {"code": "2330", "name": "台積電", "aliases": ["台積電", "TSMC", "2330"]},
    {"code": "2317", "name": "鴻海", "aliases": ["鴻海", "富士康", "2317"]},
    {"code": "2454", "name": "聯發科", "aliases": ["聯發科", "發哥", "2454"]},
    {"code": "2308", "name": "台達電", "aliases": ["台達電", "台達", "2308"]},
    {"code": "2382", "name": "廣達", "aliases": ["廣達", "2382"]},
    {"code": "3231", "name": "緯創", "aliases": ["緯創", "3231"]},
    {"code": "6669", "name": "緯穎", "aliases": ["緯穎", "6669"]},
    {"code": "3017", "name": "奇鋐", "aliases": ["奇鋐", "3017"]},
    {"code": "3324", "name": "雙鴻", "aliases": ["雙鴻", "3324"]},
    {"code": "2059", "name": "川湖", "aliases": ["川湖", "2059"]},
    {"code": "2383", "name": "台光電", "aliases": ["台光電", "2383"]},
    {"code": "6274", "name": "台燿", "aliases": ["台燿", "6274"]},
    {"code": "3037", "name": "欣興", "aliases": ["欣興", "3037"]},
    {"code": "8046", "name": "南電", "aliases": ["南電", "8046"]},
    {"code": "2303", "name": "聯電", "aliases": ["聯電", "UMC", "2303"]},
    {"code": "2408", "name": "南亞科", "aliases": ["南亞科", "2408"]},
    {"code": "3711", "name": "日月光投控", "aliases": ["日月光", "日月光投控", "3711"]},
    {"code": "3661", "name": "世芯-KY", "aliases": ["世芯", "3661"]},
    {
        "code": "3443", "name": "創意", "aliases": ["創意", "3443"],
        "require_any": ["3443", "IC設計", "IC 設計", "晶片", "設計服務", "台積電"],
    },
    {
        "code": "2603", "name": "長榮", "aliases": ["長榮", "2603"],
        "exclude": ["長榮航", "長榮航空", "長榮空運", "長榮酒店", "長榮大學", "長榮集團旗下航空"],
    },
    {"code": "2609", "name": "陽明", "aliases": ["陽明", "2609"]},
    {"code": "2881", "name": "富邦金", "aliases": ["富邦金", "2881"]},
    {"code": "2882", "name": "國泰金", "aliases": ["國泰金", "2882"]},
    {"code": "0050", "name": "元大台灣50", "aliases": ["元大台灣50", "台灣50", "0050"]},
    {"code": "00878", "name": "國泰永續高股息", "aliases": ["國泰永續高股息", "00878"]},
    {"code": "00919", "name": "群益台灣精選高息", "aliases": ["群益台灣精選高息", "00919"]},
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
    used_fallback = not items
    if used_fallback:
        items = fallback_items()
    for item in items:
        item.setdefault("is_fallback", False)
        enrich(item)
    facts = fetch_market_facts([stock["code"] for stock in STOCKS])
    analysis = analyze(items, used_fallback, facts)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_html(analysis), encoding="utf-8")
    write_history(analysis)
    print(analysis["headline"])
    print(f"Generated {OUTPUT} with {analysis['effective_count']} effective signals ({len(items)} raw)")


# ---------------------------------------------------------------------------
# 事實層：證交所真實數據（與 market_radar_pro.py 保持同步）
# ---------------------------------------------------------------------------

def fetch_market_facts(codes: list[str]) -> dict:
    """抓取最近交易日的三大法人買賣超與個股量價，並判斷今天是否為交易日。"""
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
        diff = signed_num(last[7])
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


def judge_signal(social_score: float, net_lots: float | None, volume_ratio: float | None, facts: dict) -> str:
    """熱度 × 事實判讀矩陣。話題告訴你「該看哪裡」，法人與量價告訴你「錢有沒有真的進來」。"""
    if not facts["ok"]:
        return '無市場數據，僅新聞聲量，不足以判讀'
    hot = social_score >= SOCIAL_HOT_SCORE
    if net_lots is None:
        base = '討論熱但查無法人資料' if hot else '待觀察（無法人資料）'
    elif hot and net_lots >= INST_BUY_LOTS:
        base = '討論熱＋法人實買：動能確認，再查位階與基本面'
    elif hot and net_lots <= INST_SELL_LOTS:
        base = '討論熱但法人賣超：話題與資金背離，追價風險高'
    elif hot:
        base = '討論熱、法人觀望：純題材，先等法人動向'
    elif net_lots >= INST_BUY_LOTS:
        base = '法人買超但討論度低：早期訊號，值得研究'
    elif net_lots <= INST_SELL_LOTS:
        base = '法人賣超、討論度低：留意風險'
    else:
        base = '待觀察'
    if volume_ratio and volume_ratio >= VOLUME_SURGE_RATIO:
        base += f'（爆量 ×{volume_ratio}）'
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
    rows: list[dict] = []
    seen: set[str] = set()
    for query in QUERIES:
        url = RSS_ENDPOINT.format(query=quote_plus(query))
        try:
            response = requests.get(url, headers=HTTP_HEADERS, timeout=15)
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
    # 注意：這些是「示範用假資料」，只有在所有 RSS 抓取全部失敗時才會用到，
    # 一律標記 is_fallback=True，供 main()/render_html() 顯示明顯警示，
    # 避免讀者把示範標題當成真實市場訊號。
    now = datetime.now(timezone.utc)
    titles = [
        "（示範假資料）台股今天討論 AI伺服器、PCB、散熱，台積電、廣達、緯創被反覆提到",
        "（示範假資料）BBU/儲能與矽光子題材升溫，市場關注台達電、台光電、台燿",
        "（示範假資料）高股息ETF、金融股與航運股討論度同步增加",
    ]
    return [{"source": "MVP fallback（非真實資料）", "title": t, "summary": "示範資料", "url": "", "query": "fallback", "published_at": now, "engagement": 0, "is_fallback": True} for t in titles]


def enrich(item: dict) -> None:
    text = f"{item['title']} {item['summary']}"
    normalized = text.upper()
    stocks = [{"code": stock["code"], "name": stock["name"]} for stock in STOCKS if stock_matches(normalized, stock)]
    topics = [name for name, aliases in TOPICS if any(contains_alias(normalized, alias) for alias in aliases)]
    score = sum(text.count(term) for term in POSITIVE) - sum(text.count(term) for term in NEGATIVE)
    item["stocks"] = stocks
    item["topics"] = topics
    item["sentiment_score"] = score
    item["sentiment"] = "偏樂觀" if score >= 2 else "偏保守" if score <= -2 else "中性"


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


def analyze(items: list[dict], used_fallback: bool = False, facts: dict | None = None) -> dict:
    facts = facts or {"ok": False, "trade_date": None, "market_open_today": None, "status": "", "t86": {}, "quotes": {}}
    now = datetime.now(timezone.utc)
    # 雜訊過濾：只有掛得到個股或題材的訊號才算「有效」；Threads 當機、颱風假、NBA 之類
    # 完全無關的新聞仍列入原始數，但不再灌水「今日訊號數」。
    matched = [item for item in items if item["stocks"] or item["topics"]]
    stocks = rank_entities(matched, "stocks", now)
    attach_market_facts(stocks, facts)
    topics = rank_entities(matched, "topics", now)
    momentum = rank_momentum(matched, now)
    sentiment = sorted(stocks, key=lambda row: (abs(row["sentiment_sum"]), row["mentions"]), reverse=True)
    top_topics = "、".join(row["name"] for row in topics[:3]) or "尚未形成明確題材"
    top_stocks = "、".join(f"{row['name']}({row['code']})" for row in stocks[:4]) or "尚未抓到明確個股"
    surges = "、".join(row["name"] for row in momentum[:3]) or top_topics
    headline = f"市場今天主要在討論：{top_topics}。被提到最多的個股是 {top_stocks}；短線突然升溫的題材集中在 {surges}。"
    if facts["ok"] and facts["market_open_today"] is False:
        headline = f'【今日休市或無成交資料，資金數據為 {facts["trade_date"][5:].replace("-", "/")} 收盤】' + headline
    elif not facts["ok"]:
        headline = '【市場數據缺漏】' + headline
    notes = [
        "「三大法人買賣超」「收盤/漲跌%」「量比」為證交所公布之真實交易數據（T86 / STOCK_DAY），非新聞聲量。",
        "新聞熱度來自 Google News 公開 RSS，並非社群或法人的獨立資料源，情緒判斷僅為關鍵字正負計數，非真正語意分析。",
        "「暴增倍數」需要先前累積至少 3 則提及才會顯示倍數，樣本太少時會標示為新興題材，避免以極小基期算出誤導性的倍數。",
        "本工具是「今天該研究什麼」的清單產生器，不是進場訊號：上榜 → 等收盤確認法人是否真的買 → 隔日看是否延續，再決定要不要動作。",
    ]
    if not facts["ok"]:
        notes.insert(0, "本次證交所市場數據抓取失敗，量價與法人欄位缺漏，僅剩新聞聲量，判讀可信度大幅下降。")
    if used_fallback:
        headline = "【示範假資料，非即時訊號】" + headline
        notes.insert(0, "本次即時新聞抓取全部失敗，以下內容改用示範用假資料（fallback），並非真實市場訊號，請勿作為投資判斷依據。")
    return {
        "generated_at": datetime.now(TAIPEI_TZ).isoformat(),
        "items": items,
        "effective_count": len(matched),
        "raw_count": len(items),
        "market_facts": {k: facts[k] for k in ("ok", "trade_date", "market_open_today", "status")},
        "stocks": stocks,
        "topics": topics,
        "momentum": momentum,
        "sentiment": sentiment,
        "headline": headline,
        "data_quality": "fallback" if used_fallback else "live",
        "notes": notes,
    }


def attach_market_facts(stock_rows: list[dict], facts: dict) -> None:
    """把證交所真實數據掛到每一列股票排名上，並產生熱度×事實判讀。"""
    max_heat = max([row["heat"] for row in stock_rows] or [1])
    for row in stock_rows:
        inst = facts["t86"].get(row["code"])
        quote = facts["quotes"].get(row["code"])
        net_lots = inst["total_lots"] if inst else None
        social_score = 100 * row["heat"] / max_heat if max_heat else 0
        row["close"] = quote["close"] if quote else None
        row["change_pct"] = quote["change_pct"] if quote else None
        row["volume_lots"] = quote["volume_lots"] if quote else None
        row["volume_ratio"] = quote["volume_ratio"] if quote else None
        row["inst_net_lots"] = net_lots
        row["inst_display"] = format_lots(net_lots)
        row["signal"] = judge_signal(social_score, net_lots, quote["volume_ratio"] if quote else None, facts)


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
    for row in bucket.values():
        rows.append({**row, "sources": len(row["sources"]), "heat": round(row["heat"] + row["mentions"] * 1.6 + len(row["sources"]) * 1.2, 2), "sentiment": sentiment_label(row["sentiment_sum"]), "latest_at": row["latest_at"].astimezone(TAIPEI_TZ).strftime("%m/%d %H:%M")})
    return sorted(rows, key=lambda row: (row["heat"], row["mentions"]), reverse=True)


MOMENTUM_MIN_BASELINE = 3  # 至少要有這麼多「先前」提及，倍數才有意義


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
        if not row["recent"]:
            continue
        if row["older"] < MOMENTUM_MIN_BASELINE:
            # 基期太小（例如 older=2）算出來的倍數沒有統計意義，改標示為新興題材，
            # 並用 recent_mentions 當排序依據，不再用假倍數誤導讀者。
            momentum = None
            display = f"新興（近6小時{row['recent']}則，先前僅{row['older']}則，樣本不足以估算倍數）"
            sort_key = row["recent"]
        else:
            momentum = round(row["recent"] / row["older"], 2)
            display = f"×{momentum}"
            sort_key = momentum
        rows.append({
            "name": name,
            "recent_mentions": row["recent"],
            "older_mentions": row["older"],
            "momentum": momentum,
            "momentum_display": display,
            "_sort_key": sort_key,
            "sources": len(row["sources"]),
            "latest_title": row["latest_title"],
        })
    return sorted(rows, key=lambda row: (row["_sort_key"], row["recent_mentions"]), reverse=True)


def article_heat(item: dict, now: datetime) -> float:
    age_hours = max((now - item["published_at"]).total_seconds() / 3600, 0)
    return 3 + max(0.2, 1.8 - age_hours / 18) + abs(item["sentiment_score"]) * 0.35


# ---------------------------------------------------------------------------
# 每日留檔：累積歷史快照後才能回測「上榜股票後 N 日報酬」，
# 這是驗證這台雷達有沒有真實 edge 的唯一方法。
# ---------------------------------------------------------------------------

def write_history(analysis: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    day = str(analysis.get("generated_at", ""))[:10] or datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")
    snapshot = {key: analysis[key] for key in ("generated_at", "data_quality", "market_facts", "headline", "effective_count", "raw_count", "stocks", "topics", "momentum", "notes") if key in analysis}
    (HISTORY_DIR / f"{day}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# 版面輸出
# ---------------------------------------------------------------------------

def render_html(analysis: dict) -> str:
    generated_at = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")
    topic_chart = bar_chart(analysis["topics"], "name", "heat", "#0f766e")
    stock_rows = [{**row, "label": f"{row['name']} {row['code']}"} for row in analysis["stocks"]]
    stock_chart = bar_chart(stock_rows, "label", "heat", "#2563eb")
    sankey_html = sankey(analysis["items"])
    banners = ""
    if analysis.get("data_quality") == "fallback":
        banners += banner_html("注意：本次即時新聞抓取全部失敗，以下內容為示範用假資料（fallback），並非真實市場訊號，請勿作為投資判斷依據。", "#fee2e2", "#fca5a5", "#991b1b")
    market_facts = analysis.get("market_facts", {})
    status_text = market_facts.get("status", "")
    if status_text:
        if not market_facts.get("ok"):
            banners += banner_html(status_text, "#fee2e2", "#fca5a5", "#991b1b")
        elif market_facts.get("market_open_today") is False:
            banners += banner_html(status_text, "#fef3c7", "#fcd34d", "#92400e")
        else:
            banners += banner_html(status_text, "#ecfdf5", "#6ee7b7", "#065f46")
    market_state = "交易日" if market_facts.get("market_open_today") else ("休市/無成交" if market_facts.get("ok") else "數據缺漏")
    notes_html = "".join(f"<li>{esc(note)}</li>" for note in analysis.get("notes", []))
    fact_table = table(analysis["stocks"], ["name", "close", "change_pct", "volume_lots", "volume_ratio", "inst_display", "heat", "signal"])
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Threads 台股市場熱度雷達</title><style>body{{margin:0;font-family:'Microsoft JhengHei','Noto Sans TC',Arial,sans-serif;background:#f8fafc;color:#111827}}.wrap{{max-width:1240px;margin:0 auto;padding:28px 22px 42px}}.top{{display:flex;justify-content:space-between;gap:18px;align-items:end;margin-bottom:18px}}h1{{margin:0;font-size:30px}}h2{{font-size:19px;margin:0 0 12px}}.muted{{color:#64748b;font-size:14px}}.headline{{border-left:5px solid #0f766e;background:#fff;border-radius:8px;padding:16px 18px;line-height:1.8;font-size:17px;margin-bottom:16px}}.metrics,.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}.metric,.panel{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 1px 2px rgba(15,23,42,.04)}}.metric{{padding:14px}}.metric .label{{color:#64748b;font-size:13px;margin-bottom:8px}}.metric .value{{font-size:26px;font-weight:700}}.panel{{padding:16px;overflow:hidden;margin-bottom:16px}}table{{width:100%;border-collapse:collapse;font-size:14px;background:#fff}}th,td{{padding:10px 9px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}th{{color:#334155;background:#f1f5f9;position:sticky;top:0}}.table-scroll{{max-height:480px;overflow:auto;border:1px solid #e5e7eb;border-radius:8px}}a{{color:#2563eb;text-decoration:none}}.footnote{{font-size:12px;color:#64748b;line-height:1.7}}@media(max-width:900px){{.metrics,.grid{{grid-template-columns:1fr}}.top{{display:block}}}}</style></head><body><main class='wrap'><div class='top'><div><h1>Threads 台股市場熱度雷達</h1><div class='muted'>GitHub Pages 雲端自動更新版</div></div><div class='muted'>產生時間：{generated_at}</div></div>{banners}<section class='headline'>{esc(analysis['headline'])}</section><section class='metrics'><div class='metric'><div class='label'>近 24 小時有效訊號（原始 {analysis['raw_count']}）</div><div class='value'>{analysis['effective_count']}</div></div><div class='metric'><div class='label'>市場狀態</div><div class='value'>{esc(market_state)}</div></div><div class='metric'><div class='label'>熱門股票數</div><div class='value'>{len(analysis['stocks'])}</div></div><div class='metric'><div class='label'>最後訊號</div><div class='value'>{latest_time(analysis['items'])}</div></div></section><section class='panel'><h2>個股熱度 × 真實資金（證交所數據）</h2>{fact_table}</section><section class='grid'><div class='panel'><h2>今日最熱產業</h2>{topic_chart}</div><div class='panel'><h2>今日最熱股票</h2>{stock_chart}</div></section><section class='grid'><div class='panel'><h2>突然暴增題材</h2>{table(analysis['momentum'], ['name','momentum_display','recent_mentions','older_mentions','sources','latest_title'])}</div><div class='panel'><h2>情緒榜</h2>{table(analysis['sentiment'], ['code','name','sentiment','sentiment_sum','mentions','latest_title'])}</div></section><section class='panel'><h2>資金流向圖：題材 → 受惠股（新聞聲量，非真實金流）</h2>{sankey_html}</section><section class='panel'><h2>來源訊號</h2>{source_table(analysis['items'])}</section><section class='panel footnote'><h2 style='font-size:15px'>資料與方法限制說明</h2><ul>{notes_html}</ul></section><p class='muted'>資料來源：公開新聞 RSS ＋ 證交所公開 API（T86／STOCK_DAY）。以討論熱度排序，不構成投資建議。</p></main></body></html>"""


def banner_html(text: str, bg: str, border: str, color: str) -> str:
    return f"<section style='background:{bg};border:1px solid {border};color:{color};border-radius:8px;padding:12px 16px;margin-bottom:16px;font-weight:600'>{esc(text)}</section>"


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
    labels = {"code": "代號", "name": "名稱", "heat": "熱度", "mentions": "提及", "sources": "來源數", "sentiment": "情緒", "sentiment_sum": "情緒分", "latest_title": "最新訊號", "momentum": "暴增倍數", "momentum_display": "暴增狀態", "recent_mentions": "近 6 小時", "older_mentions": "較早", "close": "收盤", "change_pct": "漲跌%", "volume_lots": "成交量(張)", "volume_ratio": "量比*", "inst_display": "三大法人買賣超", "signal": "判讀"}
    header = "".join(f"<th>{labels.get(col, col)}</th>" for col in columns)
    body = ""
    for row in rows[:limit]:
        cells = ""
        for col in columns:
            value = row.get(col, "")
            if value is None:
                value = "－"
            cells += f"<td>{esc(value)}</td>"
        body += f"<tr>{cells}</tr>"
    return f"<div class='table-scroll'><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"


def source_table(items: list[dict]) -> str:
    rows = []
    for item in items[:80]:
        title = esc(item["title"])
        link = f"<a href='{esc(item['url'])}' target='_blank' rel='noreferrer'>{title}</a>" if item["url"] else title
        rows.append((item["published_at"].astimezone(TAIPEI_TZ).strftime("%m/%d %H:%M"), item["source"], link, "、".join(f"{s['name']}({s['code']})" for s in item["stocks"]), "、".join(item["topics"])))
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
        # 排除股票代號恰好是年份的一部分，例如「2059年」不應命中股票代號 2059
        return bool(re.search(rf"(?<!\d){re.escape(alias_norm)}(?!\d)(?!年)", text))
    return alias_norm in text


def latest_time(items: list[dict]) -> str:
    if not items:
        return "-"
    return max(item["published_at"] for item in items).astimezone(TAIPEI_TZ).strftime("%m/%d %H:%M")


def sentiment_label(score: int) -> str:
    return "偏樂觀" if score >= 2 else "偏保守" if score <= -2 else "中性"


def esc(value: object) -> str:
    return html.escape(str(value) if value is not None else "", quote=True)


if __name__ == "__main__":
    main()
