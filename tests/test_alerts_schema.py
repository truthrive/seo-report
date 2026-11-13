import json
import sqlite3
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from seo_report import gsc_types as GT
from seo_report import notices as N
from seo_report import site_audit as SA

LD = """<html><head><title>Kính</title><script type="application/ld+json">{"@context":"https://schema.org",
"@graph":[{"@type":"Product","name":"Gọng A","image":"a.jpg","sku":"A1","offers":{"@type":"Offer","price":"0",
"priceCurrency":"VND"}}]}</script></head><body><h1>Gọng A</h1></body></html>"""
OK = LD.replace('"price":"0"', '"price":"416000","availability":"https://schema.org/InStock"').replace(
    '"sku":"A1"', '"sku":"A1","brand":{"@type":"Brand","name":"X"},"aggregateRating":{"ratingValue":4.8,"reviewCount":9}')


class SchemaTest(unittest.TestCase):
    def test_product_parse_and_problems(self):
        d = SA.parse(LD, "https://s.vn/a")
        self.assertEqual(d["products"][0]["price"], "0")
        must, nice = SA.product_problems(d["products"])
        self.assertIn("giá (price) trống hoặc bằng 0", must)
        self.assertIn("tình trạng hàng (availability)", must)
        must, nice = SA.product_problems(SA.parse(OK, "https://s.vn/a")["products"])
        self.assertEqual((must, nice), ([], []))
        self.assertEqual(SA.parse("<div itemtype='https://schema.org/Product'></div>", "https://s.vn/")["products"], [])
        self.assertTrue(SA.parse("<div itemtype='https://schema.org/Product'></div>", "https://s.vn/")["micro_product"])


class AlertsTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        GT.ensure_tables(self.con)
        self.cfg = SimpleNamespace(site_url="s")

    def test_hourly_drop_and_rich_drop(self):
        base = datetime(2026, 11, 10, 0, tzinfo=timezone.utc)
        rows = []
        for h in range(48):
            t = (base + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00")
            rows.append(("s", t, 10 if h < 24 else 4, 100, None, "x"))
        self.con.executemany("INSERT INTO gsc_hourly VALUES (?, ?, ?, ?, ?, ?)", rows)
        self.con.executemany("INSERT INTO gsc_appearance VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            ("s", "now", "PRODUCT_SNIPPETS", 60, 1000, 5, "a", "2026-11-09"),
            ("s", "prev", "PRODUCT_SNIPPETS", 100, 1000, 5, "b", "c")])
        got = N._traffic(self.con, self.cfg)
        self.assertEqual([n["kind"] for n in got], ["traffic", "traffic"])
        self.assertIn("60%", got[0]["title"])  # 96 so với 240 click
        self.assertIn("40%", got[1]["title"])

    def test_no_alert_small_site(self):
        base = datetime(2026, 11, 10, 0, tzinfo=timezone.utc)
        self.con.executemany("INSERT INTO gsc_hourly VALUES (?, ?, ?, ?, ?, ?)", [
            ("s", (base + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00"), 1 if h < 24 else 0, 5, None, "x")
            for h in range(48)])
        self.assertEqual(N._traffic(self.con, self.cfg), [])  # 24 click: dưới ngưỡng tối thiểu

    def test_low_reviews(self):
        from seo_report import gbp_reviews as GR
        GR.ensure_tables(self.con)
        today = date(2026, 11, 13)
        self.con.executemany("INSERT INTO gbp_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            ("l", "r1", "An", 2, "Chậm", "2026-11-01T00:00:00Z", None, None, None, "x"),
            ("l", "r2", "Bình", 5, "Tốt", "2026-11-02T00:00:00Z", None, None, None, "x"),
            ("l", "r3", "Chi", 1, "Tệ", "2026-11-03T00:00:00Z", None, "Xin lỗi", None, "x"),
            ("l", "r4", "Dũng", 3, "Cũ", "2026-08-01T00:00:00Z", None, None, None, "x")])
        self.assertEqual([n["key"] for n in N._local(self.con, today)], ["review:r1"])

    def test_link_alerts(self):
        from seo_report import backlink_links as BLL
        BLL.ensure_tables(self.con)
        prev = [BLL.slim({"domain_from": "a.vn", "url_from": "https://a.vn/1", "url_to": "https://s.vn/"})]
        cur = prev + [BLL.slim({"domain_from": "spam.vn", "url_from": "https://spam.vn/x", "url_to": "https://s.vn/",
                                "backlink_spam_score": 90}),
                      BLL.slim({"domain_from": "b.vn", "url_from": "https://b.vn/y", "url_to": "https://s.vn/old",
                                "url_to_status_code": 404})]
        for x in cur:
            x["threat"] = "MALWARE" if x["d_from"] == "spam.vn" else ""
        self.con.execute("INSERT INTO backlink_link_runs VALUES ('s', '2026-11-01', 1, 0, ?)", (json.dumps(prev),))
        self.con.execute("INSERT INTO backlink_link_runs VALUES ('s', '2026-11-12', 3, 0, ?)", (json.dumps(cur),))
        keys = [n["key"].split(":")[0] for n in N._links(self.con, self.cfg)]
        self.assertEqual(keys, ["links-threat", "links-spam-new", "links-broken"])


class PopupTest(unittest.TestCase):
    def test_once_per_day_only_important_unseen(self):
        con = sqlite3.connect(":memory:")
        items = [{"key": "a", "level": "high", "seen": False}, {"key": "b", "level": "info", "seen": False},
                 {"key": "c", "level": "medium", "seen": True}]
        self.assertEqual([n["key"] for n in N.popup_items(con, "u", items, "2026-11-13")], ["a"])
        self.assertEqual(N.popup_items(con, "u", items, "2026-11-13"), [])  # đã hiện hôm nay
        self.assertEqual(len(N.popup_items(con, "v", items, "2026-11-13")), 1)  # người khác vẫn hiện
        self.assertEqual(N.popup_items(con, "w", [items[1]], "2026-11-13"), [])  # không có gì đáng báo
        self.assertEqual(len(N.popup_items(con, "w", items, "2026-11-13")), 1)  # chưa ghi nhận nên vẫn hiện được
