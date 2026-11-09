"""AI Overview và đối thủ top 10 đọc từ kết quả check rank (DataForSEO bản advanced)."""
import json
import unittest

from seo_report import db
from seo_report import rank as R
from seo_report import urls as U
from seo_report.config import RankSettings
from tests.test_rank import END, SITE, TUE, q, run

A = "https://vidushop.com/gong-kinh/"


def aio_item(refs, async_=False, nested=None):
    return {"type": "ai_overview", "asynchronous_ai_overview": async_, "references": refs,
            "items": [{"type": "ai_overview_element", "references": nested or []}]}


def ref(domain_, url):
    return {"type": "ai_overview_reference", "domain": domain_, "url": url, "title": "t", "source": domain_}


class FakeAdvanced:
    """Kết quả advanced: kết quả tự nhiên + (tùy từ khóa) ô AI Overview."""

    def __init__(self, serps, aio):
        self.serps, self.aio, self.tasks, self.posted = serps, aio, {}, []

    def post(self, tasks):
        out = []
        for t in tasks:
            tid = f"t{len(self.tasks)}"
            self.tasks[tid] = t
            self.posted.append(t)
            out.append({"id": tid, "status_code": 20100, "cost": 0.001})
        return out

    def ready_ids(self):
        return set(self.tasks)

    def get(self, tid):
        kw = self.tasks[tid]["keyword"]
        items = [{"type": "organic", "rank_group": i + 1, "domain": d, "url": u}
                 for i, (d, u) in enumerate(self.serps.get(kw, []))]
        if kw in self.aio:
            items.insert(0, self.aio[kw])
        items.append({"type": "people_also_ask"})
        return {"status_code": 20000, "result": [{"items": items}]}


class ParseSerpTest(unittest.TestCase):
    def test_cited_via_nested_reference_and_top10(self):
        task = {"result": [{"items": [
            aio_item([ref("www.other.vn", "https://other.vn/a")], nested=[ref("vidushop.com", A)]),
            {"type": "organic", "rank_group": 1, "domain": "www.rival.vn", "url": "https://rival.vn/"},
            {"type": "organic", "rank_group": 2, "domain": "vidushop.com", "url": A},
            {"type": "organic", "rank_group": 11, "domain": "far.vn", "url": "https://far.vn/"},
            {"type": "featured_snippet"}]}]}
        s = R.parse_serp(task, SITE)
        self.assertTrue(s["aio"])
        self.assertTrue(s["aio_cited"])
        self.assertEqual({r["domain"] for r in s["aio_refs"]}, {"other.vn", "vidushop.com"})
        self.assertEqual([x["domain"] for x in s["top10"]], ["rival.vn", "vidushop.com"])  # hạng 11 không tính
        self.assertEqual(s["features"], ["ai_overview", "featured_snippet"])

    def test_no_aio_and_async_not_loaded(self):
        none = R.parse_serp({"result": [{"items": [{"type": "organic", "rank_group": 1, "domain": "a.vn"}]}]}, SITE)
        self.assertEqual((none["aio"], none["aio_cited"]), (False, False))
        # có AI Overview nhưng không tải được nội dung: không biết site có được trích hay không
        unknown = R.parse_serp({"result": [{"items": [aio_item([], async_=True)]}]}, SITE)
        self.assertEqual((unknown["aio"], unknown["aio_cited"]), (True, None))


class AioFlowTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        db.replace_day(self.con, SITE, "2026-10-20", [], [q(A, "gọng kính", 4.0), q(A, "kính mát", 12.0)])
        U.assign_urls(self.con, SITE)
        self.s = RankSettings(monthly_budget_usd=20)
        R.add_keywords(self.con, SITE, self.s, END, [("gọng kính", A), ("kính mát", None), ("kính râm", None)], "t")

    def test_check_saves_serp_and_summary(self):
        serps = {"gọng kính": [("rival.vn", "https://rival.vn/"), ("vidushop.com", A)],
                 "kính mát": [("rival.vn", "https://rival.vn/m"), ("shop2.vn", "https://shop2.vn/")],
                 "kính râm": [("shop2.vn", "https://shop2.vn/r")]}
        fake = FakeAdvanced(serps, {"gọng kính": aio_item([ref("vidushop.com", A)]),
                                    "kính mát": aio_item([ref("rival.vn", "https://rival.vn/m")])})
        run(self.con, self.s, fake, TUE)
        self.assertTrue(all(t["load_async_ai_overview"] for t in fake.posted))  # tải cả AI Overview hiện chậm
        rows = R.serp_latest(self.con, SITE, END)
        by = {r["keyword"]: r for r in rows}
        self.assertEqual((by["gọng kính"]["aio"], by["gọng kính"]["cited"]), (True, True))
        self.assertEqual((by["kính mát"]["aio"], by["kính mát"]["cited"]), (True, False))
        self.assertEqual(by["kính râm"]["aio"], False)
        summ = R.aio_summary(rows, SITE)
        self.assertEqual((summ["total"], summ["checked"], summ["aio"], summ["cited"]), (3, 3, 2, 1))
        self.assertEqual(summ["top_refs"], [("rival.vn", 1)])  # không tính chính site
        self.assertEqual([c[0] for c in summ["competitors"]], ["rival.vn", "shop2.vn"])  # gặp 2 lần mỗi site
        stored = self.con.execute("SELECT features FROM rank_serp LIMIT 1").fetchone()[0]
        self.assertIn("people_also_ask", json.loads(stored))

        # chi tiết một từ khóa: trang kết quả + cờ cho bảng
        kid = by["gọng kính"]["id"]
        hist = R.serp_history(self.con, kid)
        self.assertEqual((len(hist), hist[0]["aio"], hist[0]["cited"]), (1, True, True))
        flags = R.serp_flags(self.con, [r["id"] for r in rows])
        self.assertEqual(flags[kid], (True, True))
        self.assertEqual(flags[by["kính râm"]["id"]], (False, False))

    def test_compare_top10_moves(self):
        cur = [{"rank": 1, "domain": "b.vn", "url": ""}, {"rank": 2, "domain": "a.vn", "url": ""},
               {"rank": 3, "domain": "c.vn", "url": ""}]
        prev = [{"rank": 1, "domain": "a.vn", "url": ""}, {"rank": 4, "domain": "b.vn", "url": ""}]
        got = {x["domain"]: x["move"] for x in R.compare_top10(cur, prev)}
        self.assertEqual(got, {"b.vn": 3, "a.vn": -1, "c.vn": "new"})
        self.assertIsNone(R.compare_top10(cur, None)[0]["move"])  # lần đầu: không có gì để so

    def test_four_week_window_and_weekly_trend(self):
        """Số chính tính trên 4 tuần (lần check cuối mỗi tuần), không phải một lần chụp."""
        from datetime import date as d_
        ids = {k["keyword"]: k["id"] for k in R.keywords(self.con, SITE, END)}
        rows = [  # (từ khóa, ngày, có AIO, được trích)
            ("gọng kính", "2026-10-06", 1, 1), ("gọng kính", "2026-10-13", 1, 0),
            ("gọng kính", "2026-10-14", 1, 1),  # cùng tuần với 13/10: lấy lần cuối tuần (được trích)
            ("gọng kính", "2026-10-20", 0, 0), ("gọng kính", "2026-10-27", 1, None),  # AIO không đọc được nội dung
            ("kính mát", "2026-10-27", 1, 0),
            ("gọng kính", "2026-09-01", 1, 1)]  # ngoài 4 tuần
        for kw, day, aio, cited in rows:
            self.con.execute("INSERT INTO rank_serp (keyword_id, check_date, aio, aio_cited, aio_refs, top10, "
                             "features) VALUES (?, ?, ?, ?, '[]', '[]', '[]')", (ids[kw], day, aio, cited))
        win = {r["keyword"]: r for r in R.aio_window(self.con, SITE, END, d_(2026, 10, 28))}
        g = win["gọng kính"]
        self.assertEqual((g["weeks"], g["aio_weeks"], g["known_weeks"], g["cited_weeks"]), (4, 3, 2, 2))
        self.assertEqual(win["kính râm"]["weeks"], 0)  # chưa check: không tính vào tỷ lệ
        st = R.aio_stats(list(win.values()))
        self.assertEqual((st["total"], st["checked"], st["checks"], st["aio"], st["known"], st["cited"]),
                         (3, 2, 5, 4, 3, 2))
        self.assertAlmostEqual(st["cited_rate"], 2 / 3)
        wk = R.aio_weekly(self.con, SITE, END, d_(2026, 10, 28))
        self.assertEqual([w["week"] for w in wk][-4:], ["2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"])  # thứ Hai đầu tuần
        self.assertEqual((wk[-1]["checked"], wk[-1]["aio"], wk[-1]["known"], wk[-1]["cited"]), (2, 2, 1, 0))

    def test_reparse_reports_other_account(self):
        """Đọc lại kết quả của tài khoản DataForSEO khác: báo rõ, không im lặng."""
        fake = FakeAdvanced({"gọng kính": [("vidushop.com", A)]}, {})
        run(self.con, self.s, fake, TUE)

        class Other(FakeAdvanced):
            def get(self, tid):
                return {"status_code": 40001, "status_message": "This id is used by another client"}
        logs = []
        R.reparse(self.con, SITE, Other({}, {}), TUE, log=logs.append)
        self.assertTrue(any("tài khoản DataForSEO cũ" in m for m in logs))

if __name__ == "__main__":
    unittest.main()
