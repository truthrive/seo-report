import sqlite3
import unittest
from datetime import date, timedelta

from seo_report import gsc_types as GT

SITE = "https://a.vn/"


class Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeGSC:
    def __init__(self):
        self.bodies = []

    def searchanalytics(self):
        return self

    def sitemaps(self):
        return self

    def query(self, siteUrl, body):
        self.bodies.append(body)
        t = body["type"]
        if t == "news":
            def boom():
                raise RuntimeError("400 bad request")
            return Req(boom)
        if body["dimensions"] == ["date"]:
            s, e = date.fromisoformat(body["startDate"]), date.fromisoformat(body["endDate"])
            days = [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]
            return Req(lambda: {"rows": [{"keys": [d], "clicks": 10 if t == "discover" else 2, "impressions": 100,
                                          "position": 3.0} for d in days]})
        return Req(lambda: {"rows": [{"keys": [SITE + "bai-viet/"], "clicks": 50, "impressions": 900,
                                      "position": 2.5}]})

    def list(self, siteUrl):
        return Req(lambda: {"sitemap": [{"path": SITE + "sitemap.xml", "errors": "2", "warnings": "0",
                                         "lastDownloaded": "2026-08-01T00:00:00Z", "isPending": False}]})


class RefreshTest(unittest.TestCase):
    def test_refresh_and_read(self):
        con = sqlite3.connect(":memory:")
        fake = FakeGSC()
        logs = []
        today = date(2026, 11, 6)
        out = GT.refresh(con, SITE, fake, today, log=logs.append)
        self.assertEqual(out["discover"], GT.FIRST_DAYS)  # lần đầu ~16 tháng
        self.assertNotIn("news", out)                      # loại lỗi không chặn loại khác
        self.assertTrue(any("Tab Tin tức" in m for m in logs))
        self.assertEqual(out["sitemaps"], 1)
        t = GT.totals(con, SITE, date(2026, 10, 30), date(2026, 11, 5))
        self.assertEqual((t["discover"]["clicks"], t["discover"]["position"]), (70, None))  # Discover: không có vị trí
        self.assertAlmostEqual(t["image"]["position"], 3.0)
        rows, period = GT.top_pages(con, SITE, "discover")
        self.assertEqual((rows[0]["clicks"], rows[0]["prev_clicks"]), (50, 50))
        self.assertEqual(period, ("2026-10-07", "2026-11-03"))
        self.assertEqual(sum(w["clicks"] for w in GT.series(con, SITE, "discover", date(2026, 10, 26),
                                                             date(2026, 11, 1))), 70)
        # tuần chưa đủ 7 ngày ở đầu / cuối khoảng: bỏ
        self.assertEqual([w["week"] for w in GT.series(con, SITE, "discover", date(2026, 10, 22), date(2026, 11, 5))],
                         ["2026-10-26"])
        fake.bodies.clear()  # hôm sau: lấy nối tiếp từ ngày cuối trừ 3 ngày
        GT.refresh(con, SITE, fake, today + timedelta(days=1), log=logs.append)
        b = next(x for x in fake.bodies if x["type"] == "web" and x["dimensions"] == ["date"])
        self.assertEqual(b["startDate"], "2026-11-02")

    def test_sitemap_checks(self):
        checks = GT.sitemap_checks([{"path": "s.xml", "errors": "2", "warnings": "1",
                                     "lastDownloaded": "2026-08-01T00:00:00Z"}], date(2026, 11, 6))
        self.assertEqual([c["level"] for c in checks], ["high", "medium", "medium"])
        self.assertEqual(GT.sitemap_checks([])[0]["level"], "medium")


if __name__ == "__main__":
    unittest.main()
