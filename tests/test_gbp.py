import sqlite3
import unittest
from datetime import date, timedelta

from seo_report import gbp as G

SITE = "https://matkinh.vn/"
LOC = {"name": "locations/1", "title": "Mắt kính Q1",
       "storefrontAddress": {"addressLines": ["12 Lê Lợi"], "locality": "Quận 1"},
       "categories": {"primaryCategory": {"displayName": "Cửa hàng kính mắt"},
                      "additionalCategories": [{"displayName": "Bác sĩ nhãn khoa"}]},
       "profile": {"description": "Ngắn"}, "phoneNumbers": {"primaryPhone": "028 1234"},
       "websiteUri": "https://www.matkinh.vn/", "regularHours": {"periods": [{"openDay": "MONDAY"}]},
       "openInfo": {"status": "OPEN"}, "metadata": {"hasVoiceOfMerchant": True}}


def series_resp(start: date, end: date, per_day: dict) -> dict:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return {"multiDailyMetricTimeSeries": [{"dailyMetricTimeSeries": [
        {"dailyMetric": m, "timeSeries": {"datedValues": [
            {"date": {"year": d.year, "month": d.month, "day": d.day}, "value": str(v)} for d in days]}}
        for m, v in per_day.items()]}]}


class FakeClient:
    def __init__(self):
        self.calls = []

    def location(self, name):
        self.calls.append(("location", name))
        return LOC

    def daily(self, name, start, end):
        self.calls.append(("daily", start, end))
        return series_resp(start, end, {"BUSINESS_IMPRESSIONS_MOBILE_MAPS": 10, "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": 5,
                                        "CALL_CLICKS": 1})

    def keywords(self, name, year, month):
        self.calls.append(("keywords", year, month))
        return [{"searchKeyword": "Kính Mắt Q1", "insightsValue": {"value": str(100 + month)}},
                {"searchKeyword": "cắt kính", "insightsValue": {"threshold": "15"}}]


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        G.link(self.con, [{"name": "locations/1", "account": "accounts/9", "title": "Q1", "data": {}}], "me")

    def test_first_then_incremental(self):
        fake = FakeClient()
        today = date(2026, 11, 6)
        r = G.refresh(self.con, None, today, client=fake, log=lambda m: None)
        self.assertEqual((r["locations"], r["months"]), (1, 12))
        first = [c for c in fake.calls if c[0] == "daily"][0]
        self.assertEqual((first[1], first[2]), (today - timedelta(days=G.FIRST_DAYS), today - timedelta(days=1)))
        self.assertEqual(G.last_day(self.con), "2026-11-05")
        self.assertEqual(G.linked(self.con)[0]["title"], "Mắt kính Q1")  # hồ sơ cập nhật từ Google
        fake.calls.clear()  # hôm sau: lấy nối tiếp (lùi vài ngày), từ khóa tháng đã có thì không hỏi lại
        G.refresh(self.con, None, today + timedelta(days=1), client=fake, log=lambda m: None)
        d = [c for c in fake.calls if c[0] == "daily"][0]
        self.assertEqual(d[1], date(2026, 11, 5) - timedelta(days=G.OVERLAP_DAYS))
        self.assertEqual([c for c in fake.calls if c[0] == "keywords"], [])
        fake.calls.clear()  # sang tháng mới: chỉ lấy tháng vừa hết
        G.refresh(self.con, None, date(2026, 12, 3), client=fake, log=lambda m: None)
        self.assertEqual([c[1:] for c in fake.calls if c[0] == "keywords"], [(2026, 11)])

    def test_totals_series_keywords(self):
        G.refresh(self.con, None, date(2026, 11, 6), client=FakeClient(), log=lambda m: None)
        t = G.totals(self.con, ["locations/1"], date(2026, 10, 30), date(2026, 11, 5))
        self.assertEqual((t["views"], t["CALL_CLICKS"]), (7 * 15, 7))
        s = G.series(self.con, ["locations/1"], date(2026, 10, 26), date(2026, 11, 1))
        self.assertEqual([(x["period"], x["views"]) for x in s], [("2026-10-26", 105)])
        rows = G.keyword_rows(self.con, ["locations/1"], ["2026-10"])
        self.assertEqual((rows[0]["keyword"], rows[0]["value"], rows[0]["prev"]), ("kính mắt q1", 110, 109))
        self.assertEqual((rows[1]["keyword"], rows[1]["value"], rows[1]["below"]), ("cắt kính", 0, 15))
        self.assertEqual(G.keyword_months(self.con, ["locations/1"])[-1], "2026-10")

    def test_link_and_unlink(self):
        G.link(self.con, [{"name": "locations/2", "title": "Q3"}], "me")  # bỏ chọn Q1, chọn Q3
        self.assertEqual([x["name"] for x in G.linked(self.con)], ["locations/2"])


class AuditTest(unittest.TestCase):
    def test_checks(self):
        checks = {c["key"]: c for c in G.audit({"data": LOC}, SITE)}
        self.assertEqual(checks["website"]["level"], "ok")  # www. cùng website
        self.assertEqual(checks["description"]["level"], "medium")  # mô tả quá ngắn
        self.assertEqual(checks["categories"]["level"], "medium")   # mới 1 danh mục phụ
        self.assertEqual(checks["open"]["level"], "ok")
        bad = dict(LOC, websiteUri="https://khac.vn", openInfo={"status": "CLOSED_TEMPORARILY"}, metadata={},
                   regularHours={}, phoneNumbers={})
        checks = {c["key"]: c for c in G.audit({"data": bad}, SITE)}
        for k in ("website", "open", "verified", "hours", "phone"):
            self.assertEqual(checks[k]["level"], "high", k)
        levels = [c["level"] for c in G.audit({"data": bad}, SITE)]
        self.assertEqual(levels, sorted(levels, key=["high", "medium", "info", "ok"].index))


if __name__ == "__main__":
    unittest.main()
