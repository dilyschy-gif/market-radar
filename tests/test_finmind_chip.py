import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from finmind_chip import TAIPEI_TZ, compute_features, scan_ic_design, score_rows


def sample_payload(code: str = "2454", days: int = 30, positive: bool = True):
    start = datetime(2026, 5, 1)
    price = []
    inst = []
    margin = []
    for idx in range(days):
        day = (start + timedelta(days=idx)).date().isoformat()
        close = 100 + idx * (1 if positive else -0.2)
        volume = 2_000_000 + idx * 10_000
        price.append(
            {
                "date": day,
                "stock_id": code,
                "close": close,
                "Trading_Volume": volume,
                "Trading_money": volume * close,
            }
        )
        inst.extend(
            [
                {"date": day, "stock_id": code, "name": "Foreign_Investor", "buy": 200_000 if positive else 80_000, "sell": 100_000},
                {"date": day, "stock_id": code, "name": "Investment_Trust", "buy": 50_000, "sell": 30_000 if positive else 60_000},
                {"date": day, "stock_id": code, "name": "Dealer_self", "buy": 30_000, "sell": 20_000},
            ]
        )
        margin.append(
            {
                "date": day,
                "stock_id": code,
                "MarginPurchaseTodayBalance": 1_000_000 + idx * 1_000,
                "ShortSaleTodayBalance": 100_000 + idx * 500,
            }
        )
    return price, inst, margin


class FakeClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.request_count = 0

    def get_dataset(self, dataset, stock_id, start_date, end_date):
        self.request_count += 1
        return self.payloads[stock_id][dataset]


class FinMindChipTests(unittest.TestCase):
    def test_compute_features_uses_actual_finmind_columns(self):
        price, inst, margin = sample_payload()
        row = compute_features(
            {"code": "2454", "name": "聯發科", "market": "TWSE"},
            price,
            inst,
            margin,
        )
        self.assertTrue(row["data_complete"])
        self.assertGreater(row["foreign_5d"], 0)
        self.assertGreater(row["trust_20d"], 0)
        self.assertTrue(row["above_ma20"])
        self.assertGreater(row["avg_turnover20"], 100_000_000)
        self.assertAlmostEqual(row["short_margin_ratio"], 114_500 / 1_029_000)

    def test_scoring_produces_a_ranked_research_list(self):
        payload_a = sample_payload("2454", positive=True)
        payload_b = sample_payload("3034", positive=False)
        rows = [
            compute_features({"code": "2454", "name": "聯發科", "market": "TWSE"}, *payload_a),
            compute_features({"code": "3034", "name": "聯詠", "market": "TWSE"}, *payload_b),
        ]
        scored = score_rows(rows)
        self.assertEqual(scored[0]["code"], "2454")
        self.assertEqual(scored[0]["rank"], 1)
        self.assertIn(scored[0]["grade"], {"A", "B", "觀察"})
        self.assertGreaterEqual(scored[0]["score"], scored[1]["score"])

    def test_scan_writes_snapshot_and_reuses_current_cache(self):
        price, inst, margin = sample_payload()
        payloads = {
            "2454": {
                "TaiwanStockPrice": price,
                "TaiwanStockInstitutionalInvestorsBuySell": inst,
                "TaiwanStockMarginPurchaseShortSale": margin,
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "ic-chip.json"
            first = scan_ic_design(
                token="test-token",
                cache_path=cache,
                stocks=[{"code": "2454", "name": "聯發科", "market": "TWSE"}],
                now=datetime(2026, 6, 1, 21, 20, tzinfo=TAIPEI_TZ),
                force_refresh=True,
                client=FakeClient(payloads),
            )
            self.assertEqual(first["request_count"], 3)
            self.assertTrue(cache.exists())
            self.assertNotIn("test-token", cache.read_text(encoding="utf-8"))

            second = scan_ic_design(
                token="test-token",
                cache_path=cache,
                expected_trade_date=first["as_of"],
                stocks=[{"code": "2454", "name": "聯發科", "market": "TWSE"}],
                now=datetime(2026, 6, 2, 8, 30, tzinfo=TAIPEI_TZ),
                client=FakeClient(payloads),
            )
            self.assertEqual(second["status"], "cached")
            self.assertEqual(second["request_count"], 0)

    def test_missing_token_falls_back_to_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "ic-chip.json"
            cache.write_text(
                json.dumps({"as_of": "2026-05-30", "rows": [{"code": "2454"}]}),
                encoding="utf-8",
            )
            result = scan_ic_design(token=None, cache_path=cache)
            self.assertEqual(result["status"], "cached")
            self.assertEqual(result["rows"][0]["code"], "2454")

    def test_incomplete_same_day_snapshot_refreshes_after_settlement(self):
        price, inst, margin = sample_payload()
        payloads = {
            "2454": {
                "TaiwanStockPrice": price,
                "TaiwanStockInstitutionalInvestorsBuySell": inst,
                "TaiwanStockMarginPurchaseShortSale": margin,
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "ic-chip.json"
            cache.write_text(
                json.dumps(
                    {
                        "as_of": "2026-05-30", "success_count": 1, "aligned_count": 0,
                        "rows": [{"code": "2454"}],
                    }
                ),
                encoding="utf-8",
            )
            result = scan_ic_design(
                token="test-token",
                cache_path=cache,
                expected_trade_date="2026-05-30",
                stocks=[{"code": "2454", "name": "聯發科", "market": "TWSE"}],
                now=datetime(2026, 6, 1, 21, 20, tzinfo=TAIPEI_TZ),
                client=FakeClient(payloads),
            )
            self.assertEqual(result["request_count"], 3)


if __name__ == "__main__":
    unittest.main()
