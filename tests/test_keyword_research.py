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


class QuotaTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.old = GA.OPS_DB
        GA.OPS_DB = Path(self.tmp.name) / "ops.sqlite"

    def tearDown(self):
        GA.OPS_DB = self.old
        self.tmp.cleanup()

    def test_guard_counts_and_stops_at_cap(self):
        self.assertEqual(GA.cap(), GA.DEFAULT_CAP)
        GA.set_cap(3)
        GA._guard("ideas")
        GA._guard("ideas")
        GA._guard("volume")
        with self.assertRaises(GA.QuotaExceeded):
            GA._guard("ideas")
        self.assertEqual(GA.used(), 3)
        last = GA.usage(3)[-1]
        self.assertEqual((last["total"], last["kinds"]), (3, {"ideas": 2, "volume": 1}))
        self.assertEqual(GA.set_cap(99999), GA.DAILY_LIMIT)

    def test_quota_day_pacific(self):
        from datetime import datetime, timezone
        self.assertEqual(GA.quota_day(datetime(2026, 11, 8, 7, 59, tzinfo=timezone.utc)), "2026-11-07")  # PST
        self.assertEqual(GA.quota_day(datetime(2026, 11, 8, 8, 0, tzinfo=timezone.utc)), "2026-11-08")
        self.assertEqual(GA.quota_day(datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)), "2026-07-01")  # PDT

    def test_volume_does_not_fall_back_to_paid_when_quota_hit(self):
        from seo_report import volume as V
        con = db.connect(":memory:")
        V.ensure_tables(con)
        cfg = SimpleNamespace(rank=SimpleNamespace(paused=False, location_code=2704, language_code="vi"),
                              dataforseo_secret="x")
        todo = [{"id": 1, "keyword": "kính"}]
        with mock.patch.object(V, "missing", return_value=todo), \
                mock.patch.object(V, "_copy_known", return_value=todo), \
                mock.patch.object(V, "_google_ads", return_value=(Creds(), SETTINGS)), \
                mock.patch.object(GA, "historical_metrics", side_effect=GA.QuotaExceeded("hết")), \
                mock.patch.object(V.R, "load_credentials") as paid:
            self.assertEqual(V._refresh(con, SITE, cfg, END, None, None, lambda m: None, V.fetch), 0)
        paid.assert_not_called()
        con.close()


class ClusterTest(unittest.TestCase):
    def row(self, kw, vol, page=None, pos=None, cpc=None):
        return {"keyword": kw, "volume": vol, "gsc_page": page, "gsc_impr": 10 if page else 0, "gsc_pos": pos,
                "cpc": cpc}

    def test_groups_by_page_then_similarity(self):
        rows = [self.row("gọng kính cận", 1000, SITE + "gong/", 3.0, 2000),
                self.row("gọng kính cận giá rẻ", 200, cpc=1000),  # chỉ thêm từ phụ: cùng nhóm
                self.row("gọng kính cận nam", 300),  # 3/4 từ trùng: cùng nhóm
                self.row("tròng kính đổi màu", 500),
                self.row("giá tròng kính đổi màu", 50),
                self.row("kính áp tròng", 400)]
        gs = {g["name"]: g for g in KR.clusters(rows, SITE)}
        self.assertEqual([r["keyword"] for r in gs["gọng kính cận"]["rows"]],
                         ["gọng kính cận", "gọng kính cận nam", "gọng kính cận giá rẻ"])
        g = gs["gọng kính cận"]
        self.assertEqual((g["path"], g["ranked"], g["best"], g["volume"]), ("/gong/", 1, 3.0, 1500))
        self.assertEqual(g["action"], "Bổ sung 2 từ khóa vào trang")
        self.assertAlmostEqual(g["cpc"], (2000 * 1000 + 1000 * 200) / 1200, places=1)
        self.assertEqual(len(gs["tròng kính đổi màu"]["rows"]), 2)
        self.assertTrue(gs["tròng kính đổi màu"]["new"])
        self.assertEqual(gs["tròng kính đổi màu"]["action"], "Cần trang mới")
        self.assertIn("kính áp tròng", gs)  # "kính áp tròng" khác "tròng kính đổi màu"
        self.assertEqual(list(gs)[0], "gọng kính cận")  # nhiều volume trước

    def test_ranked_page_all_covered(self):
        g = KR.clusters([self.row("kính mát", 100, SITE + "kinh-mat/", 15.0)], SITE)[0]
        self.assertEqual(g["action"], "Tối ưu trang (chưa vào top 10)")


class FilterTest(unittest.TestCase):
    def rows(self):
        base = {"cpc": None, "competition": "LOW", "tracked": False, "brand": False, "rival": False, "intent": "C",
                "gsc_impr": 0, "gsc_pos": None, "trend": "", "soon": False, "question": False}
        return [
            {**base, "keyword": "gọng kính cận", "volume": 5000, "cpc": 3000.0, "competition": "HIGH", "words": 3,
             "tracked": True, "gsc_impr": 100, "gsc_pos": 4.0},
            {**base, "keyword": "kính cận là gì", "volume": 800, "intent": "I", "words": 4, "question": True,
             "trend": "up"},
            {**base, "keyword": "mắt việt kính cận", "volume": 300, "intent": "N", "words": 4, "rival": True},
            {**base, "keyword": "mua kính cận giá rẻ", "volume": 50, "cpc": 8000.0, "intent": "T", "words": 5,
             "gsc_impr": 10, "gsc_pos": 25.0, "soon": True},
        ]

    def names(self, f):
        return [r["keyword"] for r in KR.apply_filters(self.rows(), f)]

    def test_filters(self):
        self.assertEqual(len(self.names({})), 4)
        self.assertEqual(self.names({"vol": [101, 1000]}), ["kính cận là gì", "mắt việt kính cận"])
        self.assertEqual(self.names({"comp": ["HIGH"]}), ["gọng kính cận"])
        self.assertEqual(self.names({"intent": ["I", "T"]}), ["kính cận là gì", "mua kính cận giá rẻ"])
        self.assertEqual(self.names({"cpc": [5000, None]}), ["mua kính cận giá rẻ"])
        self.assertEqual(self.names({"inc": ["giá", "mua"], "inc_all": True}), ["mua kính cận giá rẻ"])
        self.assertEqual(len(self.names({"inc": ["giá", "gọng"]})), 2)
        self.assertEqual(self.names({"exc": ["cận là"], "exc_tracked": True, "exc_rival": True}),
                         ["mua kính cận giá rẻ"])
        self.assertEqual(self.names({"words": [5, None]}), ["mua kính cận giá rẻ"])
        self.assertEqual(self.names({"site": "none"}), ["kính cận là gì", "mắt việt kính cận"])
        self.assertEqual(self.names({"site": "top10"}), ["gọng kính cận"])
        self.assertEqual(self.names({"site": "11_30"}), ["mua kính cận giá rẻ"])
        self.assertEqual(self.names({"trend": "up"}), ["kính cận là gì"])
        self.assertEqual(self.names({"trend": "soon"}), ["mua kính cận giá rẻ"])
        self.assertEqual(self.names({"question": True}), ["kính cận là gì"])
        self.assertEqual(KR.active_filters({"vol": [1, None], "exc_tracked": True}), 2)

    def test_question_and_trend(self):
        self.assertTrue(KR.is_question("kính cận là gì"))
        self.assertTrue(KR.is_question("kính cận có tốt không"))
        self.assertTrue(KR.is_question("giá tròng kính bao nhiêu"))
        self.assertFalse(KR.is_question("gọng kính cận nam"))
        m = [(f"2026-{i:02d}", n) for i, n in enumerate([10, 10, 10, 10, 10, 10], 1)]
        self.assertEqual(KR.trend(m), "")
        self.assertEqual(KR.trend(m[:3] + [(x, 20) for x, _ in m[3:]]), "up")
        self.assertEqual(KR.trend(m[:3] + [(x, 5) for x, _ in m[3:]]), "down")


class UrlLookupTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.g = Gsc(self.con)
        KR.ensure_tables(self.con)
        self.cfg = SimpleNamespace(site_url=SITE, keywords=KeywordSettings(),
                                   rank=SimpleNamespace(location_code=2704, language_code="vi"))

    def tearDown(self):
        self.con.close()

    def test_own_url_reads_gsc_and_prices(self):
        self.g.day(END - timedelta(days=1), "/gong/", 5, 100, 3.0, "gọng kính")
        self.g.day(END - timedelta(days=1), "/gong/", 1, 50, 8.0, "kinh can")
        self.g.day(END - timedelta(days=1), "/khac/", 9, 90, 1.0, "khác")
        KR.save_cpc(self.con, [{"keyword": "gọng kính", "volume": 8100, "low_bid": 1.0, "high_bid": 3.0},
                               {"keyword": "kính cận", "volume": 5400}])
        with mock.patch.object(GA, "metrics", return_value=[{"keyword": "kinh can", "volume": 20}]) as m:
            rows = KR.url_keywords(self.con, self.cfg, "http://www.x.vn/gong?utm_source=a", ads=(Creds(), SETTINGS),
                                   end=END)
        self.assertEqual([(r["keyword"], r["url_clicks"], r["url_pos"], r["volume"]) for r in rows],
                         [("gọng kính", 5, 3.0, 8100), ("kinh can", 1, 8.0, 20)])
        self.assertEqual(m.call_args[0][2], ["kinh can"])  # chỉ hỏi từ khóa chưa có số; "kính cận" không bị gộp

    def test_ckey_keeps_accents(self):
        self.assertNotEqual(KR.ckey("kính cận"), KR.ckey("kinh can"))
        self.assertEqual(KR.ckey(" Kính  Cận "), "kính cận")
        self.assertEqual(KR.url_key("https://www.X.vn/a/?srsltid=1#top"), KR.url_key("http://x.vn/a"))


class KeywordOverviewTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.g = Gsc(self.con)
        KR.ensure_tables(self.con)
        self.con.execute("INSERT INTO kw_meta VALUES ('currency', 'VND')")
        self.cfg = SimpleNamespace(site_url=SITE, keywords=KeywordSettings(), logo="",
                                   rank=SimpleNamespace(location_code=2704, language_code="vi"))

    def tearDown(self):
        self.con.close()

    def test_overview_and_cache(self):
        from seo_report import keyword_overview as KO
        self.g.day(END - timedelta(days=1), "/meo/", 3, 40, 6.0, "gọng kính mắt mèo")
        months = [(f"2026-{m:02d}", 800 + 10 * m) for m in range(1, 13)]

        def metrics(creds, s, kws, loc, lang, opener=None):
            vol = {2704: 880, None: 980}.get(loc, 20)
            return [{"keyword": kws[0], "volume": vol, "competition": "HIGH", "competition_index": 79,
                     "low_bid": 1000.0, "high_bid": 3000.0, "monthly": months if loc == 2704 else []}]
        ideas = [{"keyword": "gọng kính mắt mèo nữ", "volume": 140, "competition": None, "competition_index": None,
                  "low_bid": None, "high_bid": None, "monthly": []},
                 {"keyword": "mặt tròn đeo kính mắt mèo có hợp không", "volume": 50, "competition": None,
                  "competition_index": None, "low_bid": None, "high_bid": None, "monthly": []}]
        with mock.patch.object(GA, "metrics", side_effect=metrics) as m, \
                mock.patch.object(GA, "keyword_ideas", return_value=ideas):
            o = KO.get(self.con, self.cfg, " gọng  kính mắt mèo ", ads=(Creds(), SETTINGS))
            self.assertEqual(m.call_count, 2 + len(KO.COUNTRIES))
            again = KO.get(self.con, self.cfg, "gọng kính mắt mèo", ads=(Creds(), SETTINGS))
            self.assertEqual(m.call_count, 2 + len(KO.COUNTRIES))  # lấy từ cache, không gọi lại
        self.assertEqual((o["volume"], o["world"], o["cpc"]), (880, 980, 2000.0))
        self.assertEqual([c["volume"] for c in o["countries"]], [20] * len(KO.COUNTRIES))
        self.assertEqual([r["keyword"] for r in o["variations"]], ["gọng kính mắt mèo nữ"])
        self.assertEqual([r["keyword"] for r in o["questions"]], ["mặt tròn đeo kính mắt mèo có hợp không"])
        self.assertEqual((o["site"]["clicks"], o["site"]["position"]), (3, 6.0))
        self.assertIsNone(o["serp"])  # chưa theo dõi hạng
        self.assertEqual(again["volume"], 880)


class MagicTest(unittest.TestCase):
    rows = [{"keyword": k, "volume": v} for k, v in (
        ("gọng kính cận nam", 100), ("kính cận gọng nhựa", 50), ("gọng kính titan", 30), ("giá gọng kính cận", 20),
        ("tròng kính", 10))]

    def test_match(self):
        names = lambda kind: [r["keyword"] for r in KR.match_rows(self.rows, "gọng kính cận", kind)]  # noqa: E731
        self.assertEqual(names("broad"), ["gọng kính cận nam", "kính cận gọng nhựa", "giá gọng kính cận"])
        self.assertEqual(names("phrase"), ["gọng kính cận nam", "giá gọng kính cận"])
        self.assertEqual(len(names("all")), 5)

    def test_word_groups(self):
        g = {x["word"]: x for x in KR.word_groups(self.rows, "kính")}
        self.assertEqual((g["gong"]["count"], g["gong"]["volume"], g["gong"]["label"]), (4, 200, "gọng"))
        self.assertEqual(g["can"]["count"], 3)
        self.assertNotIn("kinh", g)  # từ của từ khóa gốc
        self.assertNotIn("titan", g)  # chỉ 1 từ khóa
        self.assertEqual(KR.word_groups(self.rows, "kính", by="volume")[0]["word"], "gong")


class FindRecentTest(unittest.TestCase):
    def test_find_recent(self):
        con = db.connect(":memory:")
        KR.ensure_tables(con)
        con.execute("INSERT INTO kw_research (created_at, created_by, mode, seed, n, results) VALUES (?, 't', "
                    "'keywords', 'Gọng  Kính', 0, '[]')", (KR._now(),))
        self.assertIsNotNone(KR.find_recent(con, "keywords", "gọng kính"))
        self.assertIsNone(KR.find_recent(con, "site", "gọng kính"))
        self.assertIsNone(KR.find_recent(con, "keywords", "tròng kính"))
        con.close()


class MultiSeedTest(unittest.TestCase):
    def test_split_keywords(self):
        text = "gọng kính\r\nkính cận\tkính râm; Gọng  Kính\n\nkính áp tròng, tròng kính"
        self.assertEqual(KR.split_keywords(text), ["gọng kính", "kính cận", "kính râm", "kính áp tròng",
                                                   "tròng kính"])
        with self.assertRaises(ValueError):
            KR.parse_seed("keywords", "\n".join(f"từ {i}" for i in range(101)))

    def test_research_batches_of_20(self):
        con = db.connect(":memory:")
        Gsc(con)
        KR.ensure_tables(con)
        con.execute("INSERT INTO kw_meta VALUES ('currency', 'VND')")
        cfg = SimpleNamespace(site_url=SITE, keywords=KeywordSettings(), logo="",
                              rank=SimpleNamespace(location_code=2704, language_code="vi"))
        calls = []

        def ideas(creds, s, loc, lang, keywords=(), limit=0, **kw):
            calls.append(list(keywords))
            return [{"keyword": k, "volume": i, "competition": None, "competition_index": None, "low_bid": None,
                     "high_bid": None, "monthly": []} for i, k in enumerate(keywords + ["chung"])]
        seeds = "\n".join(f"từ khóa {i}" for i in range(45))
        with mock.patch.object(GA, "keyword_ideas", side_effect=ideas):
            rec = KR.research(con, cfg, "keywords", seeds, "t", ads=(Creds(), SETTINGS))
        self.assertEqual([len(c) for c in calls], [20, 20, 5])
        self.assertEqual(len(rec["rows"]), 46)  # 45 + "chung" (bỏ trùng giữa các nhóm)
        con.close()


class SerpLookupTest(unittest.TestCase):
    def test_fetch_serp_logs_cost_and_shows(self):
        from seo_report import keyword_overview as KO
        from seo_report import rank as R
        con = db.connect(":memory:")
        Gsc(con)
        KR.ensure_tables(con)
        KO.ensure_tables(con)
        con.execute("INSERT INTO kw_meta VALUES ('currency', 'VND')")
        cfg = SimpleNamespace(site_url=SITE, keywords=KeywordSettings(), logo="",
                              rank=SimpleNamespace(location_code=2704, language_code="vi", device="desktop",
                                                   se_domain="google.com.vn", paused=False, monthly_budget_usd=5.0))
        raw = {"keyword": "kính cận", "vn": {"volume": 10}, "world": {}, "countries": [], "ideas": []}
        con.execute("INSERT INTO kw_overview VALUES (?, ?, ?)", (KR.ckey("kính cận"), KR._now(), json.dumps(raw)))

        class Client:
            def live(self, task):
                return {"status_code": 20000, "cost": 0.002, "result": [{"items": [
                    {"type": "organic", "rank_group": 1, "domain": "x.vn", "url": "https://x.vn/a"},
                    {"type": "organic", "rank_group": 2, "domain": "y.vn", "url": "https://y.vn/b"},
                    {"type": "people_also_ask"}]}]}
        KO.fetch_serp(con, cfg, "kính cận", "t", client=Client())
        o = KO.get(con, cfg, "kính cận")
        self.assertTrue(o["serp"]["live"])
        self.assertEqual(o["serp"]["own_rank"], 1)
        self.assertEqual([r["domain"] for r in o["serp"]["results"]], ["x.vn", "y.vn"])
        self.assertAlmostEqual(R.serp_lookup_spent(con, KR._now()[:7]), 0.002)
        cfg.rank.paused = True
        with self.assertRaises(RuntimeError):
            KO.fetch_serp(con, cfg, "kính cận", "t", client=Client())
        con.close()


class ListModeTest(unittest.TestCase):
    def test_list_mode_checks_only_given_keywords(self):
        con = db.connect(":memory:")
        Gsc(con)
        KR.ensure_tables(con)
        con.execute("INSERT INTO kw_meta VALUES ('currency', 'VND')")
        cfg = SimpleNamespace(site_url=SITE, keywords=KeywordSettings(), logo="",
                              rank=SimpleNamespace(location_code=2704, language_code="vi"))
        got = [{"keyword": "kính cận", "volume": 5400, "competition": "HIGH", "competition_index": 90,
                "low_bid": 1.0, "high_bid": 2.0, "monthly": []}]
        with mock.patch.object(GA, "metrics", return_value=got) as m, \
                mock.patch.object(GA, "keyword_ideas") as ideas:
            rec = KR.research(con, cfg, "list", "kính cận\nkính hiếm lắm", "t", ads=(Creds(), SETTINGS))
        ideas.assert_not_called()
        self.assertEqual(m.call_args[0][2], ["kính cận", "kính hiếm lắm"])
        self.assertEqual([(r["keyword"], r["volume"]) for r in rec["rows"]], [("kính cận", 5400), ("kính hiếm lắm", None)])
        self.assertEqual(KR.history(con)[0]["seed"], "kính cận\nkính hiếm lắm")  # lưu đủ danh sách
        con.close()

    def test_aio_known_from_cache(self):
        from seo_report import keyword_overview as KO
        con = db.connect(":memory:")
        KO.ensure_tables(con)
        con.execute("INSERT INTO kw_serp_cache VALUES (?, ?, ?)",
                    (KR.ckey("kính cận"), "2026-11-08T10:00:00+00:00", json.dumps({"aio": True, "aio_cited": False})))
        a = KR.aio_known(con, SITE)
        self.assertEqual((a["kính cận"]["shown"], a["kính cận"]["cited"]), (True, False))
        con.close()


class PillarTest(unittest.TestCase):
    def test_pillar_is_best_ranked_on_same_url(self):
        rows = [{"keyword": "mắt kính gần nhất", "gsc_page": "u1", "gsc_pos": 3.8, "volume": 390},
                {"keyword": "tiệm kính gần đây", "gsc_page": "u1", "gsc_pos": 2.1, "volume": 2400},
                {"keyword": "tiệm kính", "gsc_page": "u1", "gsc_pos": 2.1, "volume": 1600},
                {"keyword": "gọng browline", "gsc_page": "u2", "gsc_pos": 9.0, "volume": 480},
                {"keyword": "chưa có hạng", "gsc_page": None, "gsc_pos": None, "volume": 10}]
        KR.set_pillars(rows)
        self.assertEqual([r["pillar"] for r in rows],
                         ["tiệm kính gần đây", "tiệm kính gần đây", "tiệm kính gần đây", "gọng browline", None])
        self.assertEqual([r["is_pillar"] for r in rows], [False, True, False, True, False])
