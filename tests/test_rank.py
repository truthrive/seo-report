import sqlite3
import unittest
from datetime import date

from seo_report import db
from seo_report import rank as R
from seo_report import urls as U
from seo_report.config import RankSettings

SITE = "https://matkinhtamduc.com/"
A = "https://matkinhtamduc.com/gong-kinh/"
B = "https://matkinhtamduc.com/gong-kinh-nam/"
END = date(2026, 10, 28)
TUE = date(2026, 10, 27)  # thứ Ba


def q(url, query, pos, impr=100):
    return {"keys": [url, query], "clicks": 1, "impressions": impr, "ctr": 0, "position": pos}


class FakeDataForSEO:
    """Trả kết quả SERP dựng sẵn: mỗi keyword ứng với danh sách (domain, url) theo thứ tự."""

    def __init__(self, serps):
        self.serps, self.posted, self.tasks = serps, [], {}

    def post(self, tasks):
        out = []
        for t in tasks:
            tid = f"t{len(self.tasks)}"
            self.tasks[tid] = t
            self.posted.append(t)
            out.append({"id": tid, "status_code": 20100, "cost": 0.0006 * (t["depth"] // 10)})
        return out

    def ready_ids(self):
        return set(self.tasks)

    def get(self, tid):
        items = [{"type": "organic", "rank_group": i + 1, "domain": d, "url": u}
                 for i, (d, u) in enumerate(self.serps.get(self.tasks[tid]["keyword"], []))]
        return {"status_code": 20000, "result": [{"items": items}]}


def run(con, s, fake, day, **kw):
    R.run(con, SITE, s, fake, END, today=day, wait_minutes=0, log=lambda *_: None, sleep=lambda *_: None, **kw)


class RankTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        db.replace_day(self.con, SITE, "2026-10-20", [], [q(A, "gọng kính", 4.0), q(A, "gọng kính nam", 12.0)])
        U.assign_urls(self.con, SITE)
        self.a = self.con.execute("SELECT id FROM urls WHERE url = ?", (A,)).fetchone()[0]
        self.s = RankSettings(monthly_budget_usd=20)

    def add(self, text, s=None):
        return R.add_keywords(self.con, SITE, s or self.s, END, R.parse_lines(text), "test")

    def test_parse_lines(self):
        self.assertEqual(R.parse_lines("Gọng  Kính\nkính zeiss | https://x.vn/a/\nkính mát\thttps://x.vn/b/\n"
                                       "mắt kính https://x.vn/c/\n\n"),
                         [("gọng kính", None), ("kính zeiss", "https://x.vn/a/"), ("kính mát", "https://x.vn/b/"),
                          ("mắt kính", "https://x.vn/c/")])

    def test_add_manual_keywords_with_optional_target(self):
        r = self.add(f"gọng kính | {A}\nkính mắt giá rẻ\nkính mát | https://other.vn/x/")
        self.assertEqual((r["added"], r["bad_url"]), (["gọng kính", "kính mắt giá rẻ"], ["kính mát | https://other.vn/x/"]))
        kws = {k["keyword"]: k for k in R.keywords(self.con, SITE, END)}
        self.assertEqual(kws["gọng kính"]["target_url"], A)
        self.assertEqual(kws["gọng kính"]["depth"], 30)  # lần đầu luôn top 30, không dựa vào position GSC
        self.assertIsNone(kws["kính mắt giá rẻ"]["target_url"])
        self.assertEqual(self.add(f"gọng kính | {B}")["updated"], ["gọng kính"])

    def test_schedule_weekdays_with_catch_up_and_monthly(self):
        sched = {"type": "weekdays", "weekdays": [1], "day": 1, "depth": "auto"}
        self.assertEqual(R.last_scheduled_day(sched, date(2026, 10, 29)), TUE)  # thứ Năm → check bù thứ Ba
        monthly = {**sched, "type": "monthly", "day": 31}
        self.assertEqual(R.last_scheduled_day(monthly, date(2026, 11, 15)), date(2026, 10, 31))
        self.assertEqual(R.last_scheduled_day(monthly, date(2026, 12, 1)), date(2026, 11, 30))
        self.assertIsNone(R.last_scheduled_day({**sched, "type": "manual"}, TUE))
        self.assertAlmostEqual(R.checks_per_month({**sched, "weekdays": [0, 3]}), 60 / 7)

    def test_run_follows_schedule_and_parses_ranks(self):
        self.add(f"gọng kính | {A}\ngọng kính nam | {A}")
        fake = FakeDataForSEO({
            "gọng kính": [("other.vn", "https://other.vn/"), ("matkinhtamduc.com", A + "#top")],
            "gọng kính nam": [("www.matkinhtamduc.com", B), ("matkinhtamduc.com", A)],
        })
        run(self.con, self.s, fake, date(2026, 10, 26))  # thứ Hai: lịch mặc định thứ Ba, chưa check lần nào → check
        self.assertEqual({(t["keyword"], t["depth"], t["device"], t["location_code"]) for t in fake.posted},
                         {("gọng kính", 30, "mobile", 2704), ("gọng kính nam", 30, "mobile", 2704)})
        run(self.con, self.s, fake, date(2026, 10, 26))  # cùng ngày: không gửi lại
        self.assertEqual(len(fake.posted), 2)
        run(self.con, self.s, fake, TUE)  # đến ngày lịch: check lại, độ sâu theo vị trí lần trước (2 và 1)
        self.assertEqual([t["depth"] for t in fake.posted[2:]], [10, 10])
        kws = {k["keyword"]: k for k in R.keywords(self.con, SITE, END)}
        self.assertEqual((kws["gọng kính"]["rank"], kws["gọng kính"]["ranking_url"], kws["gọng kính"]["best"]), (2, A, 2))
        self.assertEqual((kws["gọng kính nam"]["rank"], kws["gọng kính nam"]["ranking_url"],
                          kws["gọng kính nam"]["target_rank"]), (1, B, 2))
        self.assertEqual(kws["gọng kính"]["prev"], 2)
        self.assertEqual(len(R.history(self.con, kws["gọng kính"]["id"])), 2)

    def test_manual_schedule_only_runs_on_check_now(self):
        self.add("gọng kính")
        R.set_schedule(self.con, SITE, {"type": "manual", "weekdays": [], "day": 1, "depth": 50}, "test")
        fake = FakeDataForSEO({})
        run(self.con, self.s, fake, TUE)
        self.assertEqual(fake.posted, [])
        kid = R.keywords(self.con, SITE, END)[0]["id"]
        run(self.con, self.s, fake, TUE, only_ids=[kid])
        self.assertEqual([(t["keyword"], t["depth"]) for t in fake.posted], [("gọng kính", 50)])
        self.assertEqual(R.keywords(self.con, SITE, END)[0]["rank"], None)  # không thấy → ngoài top 50

    def test_budget_blocks_adding(self):
        tiny = RankSettings(monthly_budget_usd=0.008)  # 1 keyword top 30, 1 lần/tuần ≈ 0,0077 USD/tháng
        self.assertEqual(self.add("gọng kính", s=tiny)["added"], ["gọng kính"])
        self.assertEqual(self.add("gọng kính nam", s=tiny)["over_budget"], ["gọng kính nam"])
        ok, msg = R.toggle_star(self.con, SITE, tiny, END, self.a, "gọng kính nam", "test")
        self.assertFalse(ok)
        self.assertTrue(R.toggle_star(self.con, SITE, tiny, END, self.a, "gọng kính", "test")[0])  # bỏ theo dõi
        self.assertEqual(R.keywords(self.con, SITE, END), [])

    def test_spent_budget_stops_posting(self):
        self.add("gọng kính")
        fake = FakeDataForSEO({})
        run(self.con, RankSettings(monthly_budget_usd=0.0), fake, TUE)
        self.assertEqual(fake.posted, [])

    def test_migrates_old_stars(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
            CREATE TABLE urls (id INTEGER PRIMARY KEY, site TEXT, url TEXT);
            INSERT INTO urls VALUES (1, 's', 'https://matkinhtamduc.com/');
            CREATE TABLE rank_stars (url_id, query, frequency, starred_at, starred_by);
            INSERT INTO rank_stars VALUES (1, 'mắt kính', 'daily', 'x', 'test');
            CREATE TABLE rank_checks (url_id, query, check_date);
        """)
        R.ensure_tables(con)
        self.assertEqual(con.execute("SELECT site, keyword, url_id, source FROM rank_keywords").fetchall(),
                         [("s", "mắt kính", 1, "gsc")])
        self.assertIsNone(con.execute("SELECT 1 FROM sqlite_master WHERE name = 'rank_stars'").fetchone())


if __name__ == "__main__":
    unittest.main()
