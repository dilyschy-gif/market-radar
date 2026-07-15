import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import market_radar_pro as radar


class MarketRadarIntegrationTests(unittest.TestCase):
    def test_finmind_ranking_is_in_json_and_html(self):
        item = {
            "layer": "social",
            "query": "test",
            "source": "test",
            "title": "聯發科 IC設計買超",
            "summary": "",
            "url": "https://example.com",
            "published_at": datetime.now(timezone.utc),
        }
        facts = {
            "ok": True,
            "trade_date": "2026-07-15",
            "market_open_today": True,
            "status": "測試資料",
            "t86": {"2454": {"foreign_lots": 100, "trust_lots": 20, "total_lots": 120}},
            "quotes": {"2454": {"close": 1500, "change_pct": 1.2, "volume_lots": 1000, "volume_ratio": 1.1}},
        }
        ic_chip = {
            "status": "ok",
            "message": "FinMind測試完成",
            "as_of": "2026-07-15",
            "complete_count": 1,
            "universe_size": 1,
            "rows": [
                {
                    "rank": 1, "code": "2454", "name": "聯發科", "eligible": True,
                    "liquidity_group": "高流動", "score": 78, "grade": "A",
                    "institution_score": 82, "financing_score": 85, "short_score": 60,
                    "trend_score": 75, "foreign_5d_lots": 500, "trust_20d_lots": 300,
                    "margin_5d_pct": "2.0%", "ret_20d_pct": "8.0%", "reason": "外資5日買超",
                }
            ],
        }
        with (
            patch.object(radar, "collect_items", return_value=[item]),
            patch.object(radar, "fetch_market_facts", return_value=facts),
            patch.object(radar, "scan_ic_design", return_value=ic_chip),
        ):
            analysis = radar.build_market_radar()

        self.assertEqual(analysis["ic_chip"]["rows"][0]["score"], 78)
        self.assertIn("IC設計籌碼領先", analysis["headline"])
        json.dumps(analysis, ensure_ascii=False)
        html = radar.render_html(analysis)
        self.assertIn("IC設計籌碼分數（FinMind）", html)
        self.assertIn("聯發科", html)


if __name__ == "__main__":
    unittest.main()
