import unittest
from datetime import date, datetime, timedelta, timezone

from seo_report import db
from seo_report import indexing as IX
from seo_report import urls as U

SITE = "https://matkinhtamduc.com/"
CORE = "https://matkinhtamduc.com/gong-kinh/"
ACTIVE = "https://matkinhtamduc.com/mat-xech-la-gi/"
OLD = "https://matkinhtamduc.com/?p=1"
TODAY = datetime.now(timezone.utc).date()  # tool ghi thời điểm kiểm tra theo giờ thật (UTC)


def sitemap(urls):
    return lambda _: "<urlset>" + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>"


class FakeInspect:
    def __init__(self, results):
        self.results, self.calls = results, []

    def urlInspection(self):
        return self

    def index(self):
        return self

    def inspect(self, body):
        self.calls.append(body["inspectionUrl"])
        res = {"inspectionResult": {"indexStatusResult": self.results.get(body["inspectionUrl"], {"verdict": "PASS"})}}
        return type("R", (), {"execute": lambda _self: res})()


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        page = lambda u, i: {"keys": [u], "clicks": 1, "impressions": i, "ctr": 0, "position": 3}
        db.replace_day(self.con, SITE, (TODAY - timedelta(days=9)).isoformat(), [page(CORE, 10), page(ACTIVE, 10), page(OLD, 0)], [])
        U.assign_urls(self.con, SITE)
        gid = U.ensure_group(self.con, SITE)
        U.add_to_group(self.con, SITE, gid, CORE, "test")
        self.ids = dict(self.con.execute("SELECT url, id FROM urls"))

    def test_priority_order(self):
        IX.sync_sitemap(self.con, SITE, TODAY, fetch=sitemap([CORE, ACTIVE]))
        q = IX.queue(self.con, SITE, TODAY, 10)
        self.assertEqual([(u, r) for _, u, r in q][:2], [(CORE, "URL trong nhóm"), (ACTIVE, "Có impression 28 ngày")])
        self.assertEqual(q[-1][1], OLD)  # URL cũ/kỹ thuật xếp cuối
        self.assertEqual(len(IX.queue(self.con, SITE, TODAY, 1)), 1)

    def test_first_sitemap_read_is_not_new_but_later_urls_are(self):
        self.assertEqual(IX.sync_sitemap(self.con, SITE, TODAY, fetch=sitemap([CORE])), 0)
        new_url = "https://matkinhtamduc.com/bai-moi/"
        self.assertEqual(IX.sync_sitemap(self.con, SITE, TODAY, fetch=sitemap([CORE, new_url])), 1)
        later = TODAY + timedelta(days=3)  # 3 ngày sau
        self.assertIn((new_url, "URL mới (3 ngày)"), [(u, r) for _, u, r in IX.queue(self.con, SITE, later, 50)])

    def test_run_saves_and_detects_drop(self):
        svc = FakeInspect({})
        IX.run(self.con, SITE, lambda: svc, daily_limit=2, workers=1, today=TODAY, log=lambda *_: None)
        self.assertEqual(len(svc.calls), 2)
        self.assertEqual(IX.run(self.con, SITE, lambda: svc, daily_limit=2, workers=1, today=TODAY,
                                log=lambda *_: None), 0)  # hết lượt trong ngày
        core = self.ids[CORE]
        IX.save(self.con, core, {"verdict": "NEUTRAL", "coverageState": "Đã thu thập dữ liệu nhưng chưa lập chỉ mục",
                                 "googleCanonical": "https://matkinhtamduc.com/"})
        latest = IX.latest(self.con, [core])[core]
        self.assertFalse(latest["indexed"])
        self.assertTrue(latest["dropped"])
        self.assertTrue(IX.canonical_mismatch(latest, CORE))

    def test_watch_list_paste_check_and_follow_up(self):
        new = "https://matkinhtamduc.com/bai-moi/"
        items, invalid = IX.add_watch(self.con, SITE, f"{new}#muc-1\nmatkinhtamduc.com/bai-moi\n"
                                                      "https://othersite.vn/x/", "test")
        self.assertEqual([u for _, u in items], [new])
        self.assertEqual(invalid, ["https://othersite.vn/x/"])
        svc = FakeInspect({new: {"verdict": "NEUTRAL", "coverageState": "Đã phát hiện, chưa lập chỉ mục"}})
        self.assertEqual(IX.check_now(self.con, SITE, items, lambda: svc, workers=1, today=TODAY), (1, 0))
        w = IX.watch_list(self.con, SITE, today=TODAY)[0]
        self.assertEqual((w["indexed"], w["checks"], w["overdue"]), (False, 1, False))
        # Chưa đến mốc 3 ngày: không kiểm tra lại; đến mốc thì có.
        reason = lambda day: dict((u, r) for _, u, r in IX.queue(self.con, SITE, day, 50)).get(new, "")
        self.assertFalse(reason(TODAY + timedelta(days=1)).startswith("Đang theo dõi"))
        self.assertEqual(reason(TODAY + timedelta(days=3)), "Đang theo dõi (3 ngày)")
        self.assertTrue(IX.watch_list(self.con, SITE, today=TODAY + timedelta(days=14))[0]["overdue"])
        # Được index thì thôi theo dõi.
        IX.save(self.con, items[0][0], {"verdict": "PASS"})
        self.assertTrue(IX.watch_list(self.con, SITE, today=TODAY + timedelta(days=14))[0]["indexed"])
        self.assertNotIn(("Đang theo dõi"), [r for _, _, r in IX.queue(self.con, SITE, TODAY + timedelta(days=14), 50)])

    def test_check_now_respects_daily_quota(self):
        items, _ = IX.add_watch(self.con, SITE, f"{CORE}\n{ACTIVE}", "test")
        old = IX.DAILY_QUOTA
        IX.DAILY_QUOTA = 1
        try:
            self.assertEqual(IX.check_now(self.con, SITE, items, lambda: FakeInspect({}), workers=1,
                                          today=TODAY), (1, 1))
        finally:
            IX.DAILY_QUOTA = old

    def test_gsc_link(self):
        self.assertEqual(IX.gsc_inspect_link(SITE, CORE),
                         "https://search.google.com/search-console/inspect?resource_id=https%3A%2F%2Fmatkinhtamduc.com"
                         "%2F&id=https%3A%2F%2Fmatkinhtamduc.com%2Fgong-kinh%2F")

    def test_sitemap_index_is_followed(self):
        pages = {"https://matkinhtamduc.com/sitemap.xml":
                 "<sitemapindex><sitemap><loc>https://matkinhtamduc.com/s1.xml</loc></sitemap></sitemapindex>",
                 "https://matkinhtamduc.com/s1.xml": "<urlset><url><loc>https://matkinhtamduc.com/a/</loc></url></urlset>"}
        self.assertEqual(IX.read_sitemap("https://matkinhtamduc.com/sitemap.xml", pages.get),
                         ["https://matkinhtamduc.com/a/"])


if __name__ == "__main__":
    unittest.main()
