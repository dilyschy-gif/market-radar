from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests


FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
DEFAULT_SNAPSHOT_URL = "https://dilyschy-gif.github.io/market-radar/data/ic-chip.json"
TAIPEI_TZ = timezone(timedelta(hours=8))

# 固定股票池可避免免費 API 每天掃描全市場。分類採人工維護，避免把晶圓代工、
# 封測與記憶體製造商一起誤列為 IC 設計。market 僅用於資料品質追蹤。
IC_DESIGN_STOCKS = [
    {"code": "2401", "name": "凌陽", "market": "TWSE"},
    {"code": "2454", "name": "聯發科", "market": "TWSE"},
    {"code": "2379", "name": "瑞昱", "market": "TWSE"},
    {"code": "3034", "name": "聯詠", "market": "TWSE"},
    {"code": "3035", "name": "智原", "market": "TWSE"},
    {"code": "3014", "name": "聯陽", "market": "TWSE"},
    {"code": "3227", "name": "原相", "market": "TPEx"},
    {"code": "3228", "name": "金麗科", "market": "TPEx"},
    {"code": "3317", "name": "尼克森", "market": "TPEx"},
    {"code": "3443", "name": "創意", "market": "TWSE"},
    {"code": "3527", "name": "聚積", "market": "TPEx"},
    {"code": "3257", "name": "虹冠電", "market": "TPEx"},
    {"code": "3438", "name": "類比科", "market": "TPEx"},
    {"code": "3529", "name": "力旺", "market": "TPEx"},
    {"code": "3530", "name": "晶相光", "market": "TPEx"},
    {"code": "3545", "name": "敦泰", "market": "TWSE"},
    {"code": "3556", "name": "禾瑞亞", "market": "TPEx"},
    {"code": "3588", "name": "通嘉", "market": "TPEx"},
    {"code": "3592", "name": "瑞鼎", "market": "TWSE"},
    {"code": "3661", "name": "世芯-KY", "market": "TWSE"},
    {"code": "4919", "name": "新唐", "market": "TWSE"},
    {"code": "4952", "name": "凌通", "market": "TPEx"},
    {"code": "4961", "name": "天鈺", "market": "TWSE"},
    {"code": "4966", "name": "譜瑞-KY", "market": "TWSE"},
    {"code": "5269", "name": "祥碩", "market": "TWSE"},
    {"code": "5274", "name": "信驊", "market": "TPEx"},
    {"code": "5299", "name": "杰力", "market": "TPEx"},
    {"code": "5302", "name": "太欣", "market": "TPEx"},
    {"code": "5351", "name": "鈺創", "market": "TPEx"},
    {"code": "5471", "name": "松翰", "market": "TPEx"},
    {"code": "5487", "name": "通泰", "market": "TPEx"},
    {"code": "6104", "name": "創惟", "market": "TPEx"},
    {"code": "6129", "name": "普誠", "market": "TPEx"},
    {"code": "6138", "name": "茂達", "market": "TPEx"},
    {"code": "6202", "name": "盛群", "market": "TWSE"},
    {"code": "6233", "name": "旺玖", "market": "TPEx"},
    {"code": "6243", "name": "迅杰", "market": "TPEx"},
    {"code": "6291", "name": "沛亨", "market": "TPEx"},
    {"code": "6415", "name": "矽力*-KY", "market": "TWSE"},
    {"code": "6435", "name": "大中", "market": "TPEx"},
    {"code": "6526", "name": "達發", "market": "TWSE"},
    {"code": "6531", "name": "愛普*", "market": "TWSE"},
    {"code": "6533", "name": "晶心科", "market": "TWSE"},
    {"code": "6568", "name": "宏觀", "market": "TPEx"},
    {"code": "6643", "name": "M31", "market": "TPEx"},
    {"code": "6684", "name": "安格", "market": "TPEx"},
    {"code": "6716", "name": "應廣", "market": "TPEx"},
    {"code": "6732", "name": "昇佳電子", "market": "TPEx"},
    {"code": "6756", "name": "威鋒電子", "market": "TWSE"},
    {"code": "6799", "name": "來頡", "market": "TWSE"},
    {"code": "8016", "name": "矽創", "market": "TWSE"},
    {"code": "8054", "name": "安國", "market": "TPEx"},
    {"code": "8081", "name": "致新", "market": "TPEx"},
    {"code": "8261", "name": "富鼎", "market": "TWSE"},
    {"code": "8299", "name": "群聯", "market": "TPEx"},
]


class FinMindError(RuntimeError):
    pass


@dataclass
class FinMindClient:
    token: str
    timeout: int = 20
    max_retries: int = 3
    throttle_seconds: float = 0.03
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        self.session = self.session or requests.Session()
        self.request_count = 0

    def get_dataset(self, dataset: str, stock_id: str, start_date: str, end_date: str) -> list[dict]:
        params = {
            "dataset": dataset,
            "data_id": stock_id,
            "start_date": start_date,
            "end_date": end_date,
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "market-radar-finmind/1.0",
        }
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.request_count += 1
                response = self.session.get(FINMIND_URL, params=params, headers=headers, timeout=self.timeout)
                if response.status_code == 402:
                    raise FinMindError("FinMind 免費 API 額度已用完（HTTP 402）")
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"FinMind temporary HTTP {response.status_code}")
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") != 200:
                    raise FinMindError(str(payload.get("msg") or "FinMind API 回傳失敗"))
                data = payload.get("data")
                if not isinstance(data, list):
                    raise FinMindError("FinMind API data 欄位格式不正確")
                if self.throttle_seconds:
                    time.sleep(self.throttle_seconds)
                return data
            except (requests.RequestException, ValueError, FinMindError) as exc:
                last_error = exc
                if isinstance(exc, FinMindError) and "HTTP 402" in str(exc):
                    break
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)
        raise FinMindError(f"{stock_id} {dataset} 讀取失敗：{last_error}")


def scan_ic_design(
    token: str | None = None,
    cache_path: Path | None = None,
    expected_trade_date: str | None = None,
    official_facts: dict | None = None,
    stocks: Iterable[dict] = IC_DESIGN_STOCKS,
    now: datetime | None = None,
    force_refresh: bool | None = None,
    client: FinMindClient | None = None,
) -> dict:
    """掃描固定 IC 設計股票池；完整快照會寫入 cache_path，供盤中更新沿用。"""
    now = now or datetime.now(TAIPEI_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TAIPEI_TZ)
    else:
        now = now.astimezone(TAIPEI_TZ)
    token = token or os.getenv("FINMIND_API_TOKEN")
    force_refresh = (
        force_refresh
        if force_refresh is not None
        else os.getenv("FINMIND_FORCE_REFRESH", "").lower() in ("1", "true", "yes")
    )
    previous = load_snapshot(cache_path)
    if not previous and not force_refresh:
        snapshot_url = os.getenv("FINMIND_SNAPSHOT_URL", DEFAULT_SNAPSHOT_URL)
        previous = load_remote_snapshot(snapshot_url)
        if previous and cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")

    if not token:
        if previous:
            return cached_snapshot(previous, "未設定 FINMIND_API_TOKEN，沿用最近完整快照")
        return empty_snapshot("disabled", "未設定 FINMIND_API_TOKEN，IC 籌碼掃描未啟用")

    previous_date = previous.get("as_of") if previous else None
    previous_success = int(previous.get("success_count") or 0) if previous else 0
    previous_aligned = int(previous.get("aligned_count") or 0) if previous else 0
    enough_aligned = previous_success > 0 and previous_aligned >= max(1, round(previous_success * 0.80))
    already_current = bool(expected_trade_date and previous_date == expected_trade_date and enough_aligned)
    after_settlement = (now.hour, now.minute) >= (21, 10)
    if previous and not force_refresh and (already_current or not after_settlement):
        reason = (
            "最近快照已是最新交易日"
            if already_current
            else "等待台灣時間 21:10 後的法人與融資券完整資料"
        )
        return cached_snapshot(previous, reason)

    stock_rows = list(stocks)
    client = client or FinMindClient(token)
    start_date = (now.date() - timedelta(days=120)).isoformat()
    end_date = now.date().isoformat()
    features: list[dict] = []
    errors: list[str] = []

    for stock in stock_rows:
        code = stock["code"]
        try:
            price = client.get_dataset("TaiwanStockPrice", code, start_date, end_date)
            inst = client.get_dataset("TaiwanStockInstitutionalInvestorsBuySell", code, start_date, end_date)
            margin = client.get_dataset("TaiwanStockMarginPurchaseShortSale", code, start_date, end_date)
            features.append(compute_features(stock, price, inst, margin))
        except FinMindError as exc:
            errors.append(str(exc))

    scored = score_rows(features)
    as_of = max((row.get("as_of") or "" for row in scored), default="") or None
    complete_count = sum(bool(row.get("data_complete")) for row in scored)
    aligned_count = sum(
        bool(row.get("as_of") == row.get("inst_as_of") == row.get("margin_as_of")) for row in scored
    )
    verification = verify_against_twse(scored, official_facts or {})
    aligned_ready = bool(scored and aligned_count >= max(1, round(len(scored) * 0.80)))
    status = "ok" if scored and not errors and aligned_ready else "partial" if scored else "error"
    message = (
        f"FinMind完成 {len(scored)}/{len(stock_rows)} 檔；資料完整 {complete_count} 檔；"
        f"日期對齊 {aligned_count} 檔；本次使用 {client.request_count} 次API請求"
    )
    if errors:
        message += f"；失敗 {len(errors)} 檔"
    snapshot = {
        "status": status,
        "message": message,
        "generated_at": now.isoformat(),
        "as_of": as_of,
        "stale": False,
        "refresh_skipped": False,
        "request_count": client.request_count,
        "universe_size": len(stock_rows),
        "success_count": len(scored),
        "complete_count": complete_count,
        "aligned_count": aligned_count,
        "verification": verification,
        "errors": errors[:10],
        "rows": scored,
    }
    if cache_path and scored:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    if not scored and previous:
        return cached_snapshot(previous, "FinMind本次抓取失敗，沿用最近完整快照", stale=True)
    return snapshot


def compute_features(stock: dict, price_rows: list[dict], inst_rows: list[dict], margin_rows: list[dict]) -> dict:
    price = pd.DataFrame(price_rows)
    inst = pd.DataFrame(inst_rows)
    margin = pd.DataFrame(margin_rows)
    required_price = {"date", "close", "Trading_Volume", "Trading_money"}
    if price.empty or not required_price.issubset(price.columns):
        raise FinMindError(f"{stock['code']} 股價資料不足或欄位不完整")

    price = price.sort_values("date").drop_duplicates("date", keep="last")
    for column in ["close", "Trading_Volume", "Trading_money"]:
        price[column] = pd.to_numeric(price[column], errors="coerce")
    price = price.dropna(subset=["close", "Trading_Volume"])
    if len(price) < 21:
        raise FinMindError(f"{stock['code']} 可用股價少於21個交易日")

    inst_daily = prepare_institutional(inst)
    margin_daily = prepare_margin(margin)
    df = price.merge(inst_daily, on="date", how="left").merge(margin_daily, on="date", how="left")
    for column in ["foreign_net", "trust_net", "dealer_net"]:
        df[column] = df[column].fillna(0.0)

    latest = df.iloc[-1]
    last5 = df.tail(5)
    last20 = df.tail(20)
    previous5 = df.iloc[-6:-1]
    volume_5d = float(last5["Trading_Volume"].sum())
    foreign_5d = float(last5["foreign_net"].sum())
    foreign_20d = float(last20["foreign_net"].sum())
    trust_20d = float(last20["trust_net"].sum())
    dealer_5d = float(last5["dealer_net"].sum())
    ret_20d = safe_change(float(latest["close"]), float(df.iloc[-21]["close"]))
    ma20 = float(last20["close"].mean())
    avg_turnover20 = float(last20["Trading_money"].fillna(0).mean())
    previous_volume = float(previous5["Trading_Volume"].mean()) if not previous5.empty else 0
    volume_ratio = safe_ratio(float(latest["Trading_Volume"]), previous_volume)

    margin_balance = number_or_none(latest.get("MarginPurchaseTodayBalance"))
    short_balance = number_or_none(latest.get("ShortSaleTodayBalance"))
    margin_5d = series_change(df.get("MarginPurchaseTodayBalance"), 5)
    short_5d = series_change(df.get("ShortSaleTodayBalance"), 5)
    short_margin_ratio = safe_ratio(short_balance, margin_balance)

    price_date = str(price["date"].iloc[-1])
    inst_date = str(inst["date"].max()) if not inst.empty and "date" in inst else None
    margin_date = str(margin["date"].max()) if not margin.empty and "date" in margin else None
    data_complete = bool(price_date == inst_date == margin_date and len(inst_daily) >= 20 and len(margin_daily) >= 6)

    return {
        "code": stock["code"],
        "name": stock["name"],
        "market": stock.get("market", ""),
        "as_of": price_date,
        "inst_as_of": inst_date,
        "margin_as_of": margin_date,
        "data_complete": data_complete,
        "close": round(float(latest["close"]), 2),
        "ma20": round(ma20, 2),
        "above_ma20": bool(float(latest["close"]) > ma20),
        "ret_20d": ret_20d,
        "volume_ratio": volume_ratio,
        "avg_turnover20": avg_turnover20,
        "foreign_5d": foreign_5d,
        "foreign_20d": foreign_20d,
        "trust_20d": trust_20d,
        "dealer_5d": dealer_5d,
        "inst_total_1d": float(latest["foreign_net"] + latest["trust_net"] + latest["dealer_net"]),
        "foreign_5d_ratio": safe_ratio(foreign_5d, volume_5d),
        "foreign_20d_ratio": safe_ratio(foreign_20d, float(last20["Trading_Volume"].sum())),
        "trust_20d_ratio": safe_ratio(trust_20d, float(last20["Trading_Volume"].sum())),
        "margin_balance": margin_balance,
        "margin_5d": margin_5d,
        "short_balance": short_balance,
        "short_5d": short_5d,
        "short_margin_ratio": short_margin_ratio,
    }


def prepare_institutional(inst: pd.DataFrame) -> pd.DataFrame:
    columns = ["date", "foreign_net", "trust_net", "dealer_net"]
    if inst.empty or not {"date", "name", "buy", "sell"}.issubset(inst.columns):
        return pd.DataFrame(columns=columns)
    inst = inst.copy()
    inst["buy"] = pd.to_numeric(inst["buy"], errors="coerce").fillna(0)
    inst["sell"] = pd.to_numeric(inst["sell"], errors="coerce").fillna(0)
    inst["net"] = inst["buy"] - inst["sell"]
    names = inst["name"].astype(str)
    inst["bucket"] = "dealer_net"
    inst.loc[names.eq("Foreign_Investor"), "bucket"] = "foreign_net"
    inst.loc[names.str.contains("Investment_Trust", case=False, na=False), "bucket"] = "trust_net"
    daily = inst.pivot_table(index="date", columns="bucket", values="net", aggfunc="sum", fill_value=0).reset_index()
    for column in columns[1:]:
        if column not in daily:
            daily[column] = 0.0
    return daily[columns].sort_values("date")


def prepare_margin(margin: pd.DataFrame) -> pd.DataFrame:
    columns = ["date", "MarginPurchaseTodayBalance", "ShortSaleTodayBalance"]
    if margin.empty or "date" not in margin:
        return pd.DataFrame(columns=columns)
    margin = margin.copy().sort_values("date").drop_duplicates("date", keep="last")
    for column in columns[1:]:
        if column not in margin:
            margin[column] = pd.NA
        margin[column] = pd.to_numeric(margin[column], errors="coerce")
    return margin[columns]


def score_rows(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    for row in rows:
        row["foreign_5d_rank"] = percentile(row, rows, "foreign_5d_ratio")
        row["foreign_20d_rank"] = percentile(row, rows, "foreign_20d_ratio")
        row["trust_20d_rank"] = percentile(row, rows, "trust_20d_ratio")
        row["institution_score"] = round(
            0.50 * row["foreign_5d_rank"]
            + 0.20 * row["foreign_20d_rank"]
            + 0.30 * row["trust_20d_rank"]
        )
        row["financing_score"] = financing_health(row.get("margin_5d"), row.get("ret_20d"))
        row["short_score"] = short_pressure(
            row.get("short_margin_ratio"), row.get("short_5d"), row.get("foreign_5d")
        )
        row["trend_score"] = trend_confirmation(
            row.get("above_ma20"), row.get("ret_20d"), row.get("volume_ratio")
        )
        row["score"] = round(
            0.40 * row["institution_score"]
            + 0.20 * row["financing_score"]
            + 0.15 * row["short_score"]
            + 0.25 * row["trend_score"]
        )
        row["eligible"] = bool(row["avg_turnover20"] >= 100_000_000 and row["data_complete"])
        row["liquidity_group"] = liquidity_group(row["avg_turnover20"])
        row["grade"] = grade_row(row)
        row["reason"] = reason_for(row)
        add_display_fields(row)
    rows.sort(key=lambda row: (row["eligible"], row["score"]), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        for key in ["foreign_5d_rank", "foreign_20d_rank", "trust_20d_rank"]:
            row.pop(key, None)
    return rows


def percentile(row: dict, rows: list[dict], field: str) -> float:
    values = sorted(float(item[field]) for item in rows if item.get(field) is not None)
    value = row.get(field)
    if value is None or not values:
        return 50.0
    if len(values) == 1:
        return 50.0
    below = sum(item < float(value) for item in values)
    equal = sum(item == float(value) for item in values)
    return round(100 * (below + 0.5 * (equal - 1)) / (len(values) - 1), 2)


def financing_health(margin_5d: float | None, ret_20d: float | None) -> int:
    if margin_5d is None:
        return 50
    if margin_5d <= 0:
        return 100 if (ret_20d or 0) > 0 else 65
    if margin_5d <= 0.05:
        return 85
    if margin_5d <= 0.10:
        return 70
    if margin_5d <= 0.15:
        return 50
    return max(0, round(50 - (margin_5d - 0.15) * 200))


def short_pressure(short_ratio: float | None, short_5d: float | None, foreign_5d: float | None) -> int:
    if short_ratio is None:
        return 35
    if 0.05 <= short_ratio <= 0.30:
        score = 60
    elif short_ratio < 0.05:
        score = 25
    else:
        score = 30
    if (short_5d or 0) > 0:
        score += 15
    if (foreign_5d or 0) > 0:
        score += 25
    return min(100, score)


def trend_confirmation(above_ma20: bool | None, ret_20d: float | None, volume_ratio: float | None) -> int:
    score = 40 if above_ma20 else 0
    if ret_20d is not None:
        if 0 < ret_20d <= 0.30:
            score += 35
        elif ret_20d > 0.30:
            score += 20
    if volume_ratio is not None:
        if 1.0 <= volume_ratio <= 2.5:
            score += 25
        elif volume_ratio > 2.5:
            score += 15
        elif volume_ratio >= 0.8:
            score += 10
    return min(100, score)


def grade_row(row: dict) -> str:
    if not row["eligible"]:
        return "資料不足"
    if (
        row["score"] >= 70
        and row["foreign_5d"] > 0
        and row["trust_20d"] > 0
        and (row["margin_5d"] is None or row["margin_5d"] < 0.15)
        and row["above_ma20"]
    ):
        return "A"
    if row["score"] >= 55 and row["above_ma20"]:
        return "B"
    return "觀察"


def reason_for(row: dict) -> str:
    reasons = []
    if row["foreign_5d"] > 0:
        reasons.append("外資5日買超")
    if row["trust_20d"] > 0:
        reasons.append("投信20日買超")
    if row["above_ma20"]:
        reasons.append("站上20MA")
    if row.get("margin_5d") is not None and row["margin_5d"] >= 0.15:
        reasons.append("融資增幅過熱")
    if row["avg_turnover20"] < 100_000_000:
        reasons.append("成交值未達門檻")
    if not row["data_complete"]:
        reasons.append("資料日期未完全對齊")
    return "、".join(reasons) or "籌碼尚未形成明確方向"


def add_display_fields(row: dict) -> None:
    row["foreign_5d_lots"] = round(row["foreign_5d"] / 1000)
    row["trust_20d_lots"] = round(row["trust_20d"] / 1000)
    row["margin_5d_pct"] = percent_display(row.get("margin_5d"))
    row["short_margin_pct"] = percent_display(row.get("short_margin_ratio"))
    row["ret_20d_pct"] = percent_display(row.get("ret_20d"))
    row["avg_turnover20_million"] = round(row["avg_turnover20"] / 1_000_000)


def liquidity_group(value: float) -> str:
    if value >= 1_000_000_000:
        return "高流動"
    if value >= 300_000_000:
        return "中流動"
    return "基本門檻"


def verify_against_twse(rows: list[dict], facts: dict) -> dict:
    quotes = facts.get("quotes", {})
    t86 = facts.get("t86", {})
    checked = 0
    matched = 0
    mismatches = []
    by_code = {row["code"]: row for row in rows}
    for code in sorted(set(by_code) & set(quotes)):
        checked += 1
        row = by_code[code]
        official_close = quotes[code].get("close")
        official_lots = (t86.get(code) or {}).get("total_lots")
        close_ok = official_close is not None and abs(float(official_close) - row["close"]) <= 0.01
        inst_lots = round(row["inst_total_1d"] / 1000)
        inst_ok = official_lots is None or abs(float(official_lots) - inst_lots) <= 5
        if close_ok and inst_ok:
            matched += 1
        else:
            mismatches.append(code)
    return {"checked": checked, "matched": matched, "mismatches": mismatches}


def load_snapshot(path: Path | None) -> dict | None:
    if not path or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("rows"), list) else None


def load_remote_snapshot(url: str) -> dict | None:
    if not url:
        return None
    try:
        response = requests.get(url, headers={"User-Agent": "market-radar-finmind/1.0"}, timeout=10)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("rows"), list) else None


def cached_snapshot(snapshot: dict, reason: str, stale: bool = False) -> dict:
    result = dict(snapshot)
    result["status"] = "cached" if not stale else "stale"
    result["message"] = reason + f"；快照資料日 {snapshot.get('as_of') or '未知'}"
    result["stale"] = stale
    result["refresh_skipped"] = True
    result["request_count"] = 0
    return result


def empty_snapshot(status: str, message: str) -> dict:
    return {
        "status": status,
        "message": message,
        "generated_at": datetime.now(TAIPEI_TZ).isoformat(),
        "as_of": None,
        "stale": False,
        "refresh_skipped": True,
        "request_count": 0,
        "universe_size": len(IC_DESIGN_STOCKS),
        "success_count": 0,
        "complete_count": 0,
        "aligned_count": 0,
        "verification": {"checked": 0, "matched": 0, "mismatches": []},
        "errors": [],
        "rows": [],
    }


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator) / float(denominator)


def safe_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return float(current) / float(previous) - 1


def series_change(series: pd.Series | None, periods: int) -> float | None:
    if series is None:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) <= periods:
        return None
    return safe_change(float(values.iloc[-1]), float(values.iloc[-periods - 1]))


def number_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percent_display(value: float | None) -> str:
    return "－" if value is None else f"{value * 100:.1f}%"
