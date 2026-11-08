import os
import tempfile
import time
import unittest
from contextlib import closing
from datetime import date, timedelta
from types import SimpleNamespace

from seo_report import access as A
from seo_report import db
from seo_report import notices as N
from seo_report import opportunities as O
from seo_report import web_events as EV
from seo_report.config import KeywordSettings

SITE = "https://x.vn/"
END = date(2026, 11, 5)
KS = KeywordSettings(brand_terms=("xvn",))


class Gsc:
    """Dựng dữ liệu GSC tối thiểu: URL, query, số theo ngày."""

    def __init__(self, con):
        self.con, self.urls, self.queries = con, {}, {}
        con.execute("INSERT INTO gsc_fetch_log VALUES (?, ?, 0, 0, '')", (SITE, (END - timedelta(days=450)).isoformat()))
        con.execute("INSERT INTO gsc_fetch_log VALUES (?, ?, 0, 0, '')", (SITE, END.isoformat()))

    def url(self, path: str) -> int:
        if path not in self.urls:
            u = SITE.rstrip("/") + path
            pid = self.con.execute("INSERT INTO pages (site, url) VALUES (?, ?)", (SITE, u)).lastrowid
            uid = self.con.execute("INSERT INTO urls (site, url) VALUES (?, ?)", (SITE, u)).lastrowid
            self.con.execute("INSERT INTO page_url VALUES (?, ?)", (pid, uid))
            self.urls[path] = (pid, uid)
        return self.urls[path][0]

    def q(self, text: str) -> int:
        if text not in self.queries:
            self.queries[text] = self.con.execute("INSERT INTO queries (text) VALUES (?)", (text,)).lastrowid
        return self.queries[text]

    def day(self, d: date, path: str, clicks: int, impr: int, pos: float, query: str | None = None) -> None:
        pid = self.url(path)
        self.con.execute("INSERT INTO gsc_page_daily VALUES (?, ?, ?, ?, ?) ON CONFLICT DO UPDATE SET "
                         "clicks = clicks + excluded.clicks, impressions = impressions + excluded.impressions",
                         (d.isoformat(), pid, clicks, impr, pos))
        if query:
            self.con.execute("INSERT INTO gsc_query_daily VALUES (?, ?, ?, ?, ?, ?)",
                             (d.isoformat(), pid, self.q(query), clicks, impr, pos))


class OpportunitiesTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.g = Gsc(self.con)

    def tearDown(self):
        self.con.close()

    def test_striking_keeps_positions_4_to_15_and_skips_brand(self):
        g = self.g
        g.day(END, "/a/", 5, 300, 6.0, "kính cận")  # vị trí 6, nhiều hiển thị: cơ hội
        g.day(END, "/b/", 50, 300, 2.0, "kính râm")  # đã top 3
        g.day(END, "/c/", 1, 300, 30.0, "kính áp tròng")  # quá xa
        g.day(END, "/a/", 2, 300, 5.0, "xvn kính")  # thương hiệu
        g.day(END, "/d/", 0, 20, 7.0, "kính đọc sách")  # quá ít hiển thị
        g.day(END - timedelta(days=30), "/a/", 1, 100, 9.0, "kính cận")
        rows = O.striking(self.con, SITE, END, KS)
        self.assertEqual([r["query"] for r in rows], ["kính cận"])
        r = rows[0]
        self.assertEqual(r["potential"], round(300 * O.CTR_TOP3 - 5))
        self.assertEqual(r["prev_position"], 9.0)
        self.assertFalse(r["tracked"])

    def test_decay_finds_drop_and_cause(self):
        g = self.g
        g.day(END - timedelta(days=40), "/rot/", 100, 1000, 3.0)
        g.day(END - timedelta(days=5), "/rot/", 40, 900, 7.0)  # rớt hạng
        g.day(END - timedelta(days=40), "/ctr/", 60, 1000, 4.0)
        g.day(END - timedelta(days=5), "/ctr/", 20, 1000, 4.2)  # vẫn hiển thị, ít bấm
        g.day(END - timedelta(days=40), "/nho/", 10, 100, 4.0)
        g.day(END - timedelta(days=5), "/nho/", 2, 100, 4.0)  # quá ít click để báo
        g.day(END - timedelta(days=40), "/on/", 100, 1000, 4.0)
        g.day(END - timedelta(days=5), "/on/", 90, 1000, 4.0)  # giảm 10%: không báo
        rows = O.decay(self.con, SITE, END)
        self.assertEqual([(r["url"][-5:], r["cause"]) for r in rows], [("/rot/", "rank"), ("/ctr/", "ctr")])
        self.assertEqual(rows[0]["lost"], 60)

    def test_decay_flags_seasonal_when_last_year_also_dropped(self):
        g = self.g
        for back in (0, 364):
            g.day(END - timedelta(days=40 + back), "/mua/", 100, 1000, 3.0)
            g.day(END - timedelta(days=5 + back), "/mua/", 40, 400, 3.0)
        self.assertTrue(O.decay(self.con, SITE, END)[0]["seasonal"])

    def test_cannibal_groups_urls_and_flags_serious(self):
        g = self.g
        g.day(END, "/mot/", 5, 300, 6.0, "gọng kính nam")
        g.day(END, "/hai/", 2, 200, 8.0, "gọng kính nam")
        g.day(END, "/mot/", 30, 300, 1.5, "tròng kính")
        g.day(END, "/hai/", 0, 60, 9.0, "tròng kính")
        groups = {x["query"]: x for x in O.cannibal(self.con, SITE, END, KS)}
        self.assertEqual(len(groups["gọng kính nam"]["urls"]), 2)
        self.assertTrue(groups["gọng kính nam"]["serious"])  # trang chính vị trí 6, trang phụ 40%
        self.assertFalse(groups["tròng kính"]["serious"])  # trang chính đã top 3
        self.assertAlmostEqual(groups["gọng kính nam"]["urls"][0]["share"], 0.6)

    def test_new_pages_first_7_30_90_days(self):
        g = self.g
        g.day(END - timedelta(days=300), "/cu/", 1, 10, 5.0)
        g.day(END - timedelta(days=5), "/cu/", 1, 10, 5.0)
        start = END - timedelta(days=19)
        for i in range(20):
            g.day(start + timedelta(days=i), "/moi/", 1, 3, 8.0, "kính mới" if i == 19 else None)
        rows = O.new_pages(self.con, SITE, END)
        self.assertEqual([r["url"][-5:] for r in rows], ["/moi/"])
        r = rows[0]
        self.assertEqual(r["first_seen"], start)
        self.assertEqual(r["age"], 20)
        self.assertEqual((r["periods"][7]["clicks"], r["periods"][7]["done"]), (7, True))
        self.assertEqual((r["periods"][30]["clicks"], r["periods"][30]["done"]), (20, False))
        self.assertEqual(r["impressions"], 60)
        self.assertEqual(r["head"]["query"], "kính mới")

    def test_event_marks_land_on_bucket(self):
        spans = [(date(2026, 11, 2), date(2026, 11, 8)), (date(2026, 11, 9), date(2026, 11, 15))]
        evs = [{"day": "2026-11-10", "text": "Core update"}, {"day": "2026-11-11", "text": "Sửa menu"},
               {"day": "2026-10-01", "text": "Ngoài kỳ"}]
        self.assertEqual(EV.marks(evs, spans, ["02/11", "09/11"]), [("09/11", "10/11 Core update · 11/11 Sửa menu")])
        self.assertEqual(EV.mark_line([]), {})
        self.assertEqual(EV.mark_line([("09/11", "x")])["markLine"]["data"][0]["xAxis"], "09/11")


class SeoNoticesTest(unittest.TestCase):
    def test_bell_shows_decay_after_background_summary(self):
        O.forget()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.db")
            with closing(db.connect(path)) as con:
                g = Gsc(con)
                g.day(END - timedelta(days=40), "/rot/", 100, 1000, 3.0)
                g.day(END - timedelta(days=5), "/rot/", 20, 900, 9.0)
                con.commit()
            cfg = SimpleNamespace(site_url=SITE, db_path=path, keywords=KS, rank=None)
            team = A.User("team@x.vn", A.EDITOR)
            with closing(db.connect(path)) as con:
                first = [n for n in N.collect(con, cfg, team, today=END) if n["kind"] == "seo"]
                self.assertEqual(first, [])  # lần đầu: đang tính ở luồng nền, trang không phải chờ
                for _ in range(100):
                    if path not in O._warming:
                        break
                    time.sleep(0.05)
                seo = [n for n in N.collect(con, cfg, team, today=END) if n["kind"] == "seo"]
                client = [n for n in N.collect(con, cfg, A.User("k@x.vn", A.CLIENT), today=END)
                          if n["kind"] == "seo"]
            self.assertEqual(len(seo), 1)
            self.assertEqual(seo[0]["href"], "/co-hoi?tab=giam")
            self.assertEqual(seo[0]["level"], "high")  # mất 80%
            self.assertEqual(client, [])
        O.forget()


if __name__ == "__main__":
    unittest.main()
