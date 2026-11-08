import io
import json
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from seo_report import db
from seo_report import google_ads as GA
from seo_report import keyword_research as KR
from seo_report.config import KeywordSettings
from tests.test_opportunities import END, SITE, Gsc


class Creds:
    valid, token = True, "t"


SETTINGS = {"developer_token": "d", "customer_id": "1", "login_customer_id": ""}


def idea(text, vol, lo=1_000_000_000, hi=3_000_000_000):
    return {"text": text, "keywordIdeaMetrics": {
        "avgMonthlySearches": str(vol), "competition": "HIGH", "competitionIndex": "90",
        "lowTopOfPageBidMicros": str(lo), "highTopOfPageBidMicros": str(hi),
        "monthlySearchVolumes": [{"year": "2026", "month": "FEBRUARY", "monthlySearches": "10"},
                                 {"year": "2026", "month": "JANUARY", "monthlySearches": "20"}]}}


class GoogleAdsIdeasTest(unittest.TestCase):
    def test_ideas_paginate_and_parse(self):
        pages = [{"results": [idea("kính cận", 100)], "nextPageToken": "p2"}, {"results": [idea("gọng kính", 500)]}]
        bodies = []

        def opener(req, timeout=0):
            bodies.append(json.loads(req.data))
            return io.BytesIO(json.dumps(pages[len(bodies) - 1]).encode())
        rows = GA.keyword_ideas(Creds(), SETTINGS, 2704, "vi", keywords=["kính"], opener=opener)
        self.assertEqual([r["keyword"] for r in rows], ["gọng kính", "kính cận"])  # nhiều volume trước
        self.assertEqual(bodies[0]["keywordSeed"], {"keywords": ["kính"]})
        self.assertEqual(bodies[1]["pageToken"], "p2")
        r = rows[1]
        self.assertEqual((r["volume"], r["competition"], r["competition_index"]), (100, "HIGH", 90))
        self.assertEqual((r["low_bid"], r["high_bid"]), (1000.0, 3000.0))
        self.assertEqual(r["monthly"], [("2026-01", 20), ("2026-02", 10)])
        self.assertEqual(KR.cpc(r), 2000.0)

    def test_site_seed(self):
        sent = {}

        def opener(req, timeout=0):
            sent.update(json.loads(req.data))
            return io.BytesIO(b"{}")
        GA.keyword_ideas(Creds(), SETTINGS, 2704, "vi", site="doithu.vn", opener=opener)
        self.assertEqual(sent["siteSeed"], {"site": "doithu.vn"})


class ResearchTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.g = Gsc(self.con)
        self.cfg = SimpleNamespace(site_url=SITE, keywords=KeywordSettings(brand_terms=("xvn",)),
                                   rank=SimpleNamespace(location_code=2704, language_code="vi"))
        KR.ensure_tables(self.con)
        self.con.execute("INSERT INTO kw_meta VALUES ('currency', 'VND')")

    def tearDown(self):
        self.con.close()

    def test_parse_seed(self):
        self.assertEqual(KR.parse_seed("keywords", "a, b\nc"), {"keywords": ["a", "b", "c"]})
        self.assertEqual(KR.parse_seed("site", "https://www.doithu.vn/abc"), {"site": "doithu.vn"})
        with self.assertRaises(ValueError):
            KR.parse_seed("url", "doithu.vn")

    def test_research_saves_and_marks_site_rank(self):
        self.g.day(END - timedelta(days=1), "/can/", 7, 200, 4.0, "Kính Cận")
        fake = [{"keyword": "kính cận", "volume": 900, "competition": "HIGH", "competition_index": 90,
                 "low_bid": 1000.0, "high_bid": 3000.0, "monthly": [("2026-01", 900)]},
                {"keyword": "xvn kính", "volume": 50, "competition": None, "competition_index": None,
                 "low_bid": None, "high_bid": None, "monthly": []}]
        with mock.patch.object(GA, "keyword_ideas", return_value=fake):
            rec = KR.research(self.con, self.cfg, "keywords", "kính", "team@x.vn", ads=(Creds(), SETTINGS))
        a, b = rec["rows"]
        self.assertEqual((a["gsc_pos"], a["gsc_clicks"], a["cpc"]), (4.0, 7, 2000.0))
        self.assertTrue(a["gsc_page"].endswith("/can/"))
        self.assertTrue(b["brand"])
        self.assertEqual(b["gsc_impr"], 0)
        self.assertEqual(KR.history(self.con)[0]["n"], 2)
        # giá thầu được lưu để tính giá trị traffic
        v = KR.traffic_value(self.con, self.cfg, END - timedelta(days=27), END)
        self.assertEqual((v["value"], v["priced_clicks"], v["clicks"]), (14000, 7, 7))

    def test_traffic_value_skips_brand_and_unpriced(self):
        self.g.day(END - timedelta(days=2), "/a/", 10, 100, 2.0, "tròng kính")
        self.g.day(END - timedelta(days=2), "/b/", 50, 100, 1.0, "xvn")
        self.g.day(END - timedelta(days=2), "/c/", 5, 100, 3.0, "không có giá")
        KR.save_cpc(self.con, [{"keyword": "Tròng Kính", "low_bid": 500.0, "high_bid": 1500.0}])
        v = KR.traffic_value(self.con, self.cfg, END - timedelta(days=27), END)
        self.assertEqual((v["value"], v["clicks"], v["priced_clicks"]), (10000, 15, 10))
        self.assertEqual(v["top"][0]["query"], "tròng kính")

    def test_refresh_cpc_asks_only_missing(self):
        self.g.day(END - timedelta(days=2), "/a/", 10, 100, 2.0, "tròng kính")
        self.g.day(END - timedelta(days=2), "/b/", 9, 100, 2.0, "gọng kính")
        KR.save_cpc(self.con, [{"keyword": "tròng kính", "low_bid": 1.0, "high_bid": 2.0}])
        with mock.patch.object(GA, "metrics", return_value=[]) as m:
            n = KR.refresh_cpc(self.con, self.cfg, end=END, ads=(Creds(), SETTINGS), log=lambda s: None)
        self.assertEqual(n, 1)
        self.assertEqual(m.call_args[0][2], ["gọng kính"])
        # không có số: lưu dòng trống để không hỏi lại
        with mock.patch.object(GA, "metrics", return_value=[]) as m:
            self.assertEqual(KR.refresh_cpc(self.con, self.cfg, end=END, ads=(Creds(), SETTINGS), log=lambda s: None),
                             0)

    def test_money(self):
        self.assertEqual(KR.money(17_512_345), "17,5 triệu ₫")
        self.assertEqual(KR.money(2_000_000_000), "2 tỷ ₫")
        self.assertEqual(KR.money(294_600), "294,6 nghìn ₫")
        self.assertEqual(KR.money(950), "950 ₫")
        self.assertEqual(KR.money(1234, "USD"), "1.234 USD")


if __name__ == "__main__":
    unittest.main()
