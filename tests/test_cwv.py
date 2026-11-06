import sqlite3
import unittest
from datetime import date
from types import SimpleNamespace

from seo_report import cwv as C
from seo_report import db

SITE = "https://matkinh.vn/"

HISTORY = {"record": {
    "collectionPeriods": [{"firstDate": {"year": 2026, "month": 9, "day": 7}, "lastDate": {"year": 2026, "month": 10, "day": 4}},
                          {"firstDate": {"year": 2026, "month": 9, "day": 14}, "lastDate": {"year": 2026, "month": 10, "day": 11}}],
    "metrics": {"largest_contentful_paint": {"percentilesTimeseries": {"p75s": [2400, 2700]}},
                "interaction_to_next_paint": {"percentilesTimeseries": {"p75s": ["NaN", 180]}},
                "cumulative_layout_shift": {"percentilesTimeseries": {"p75s": ["0.05", "0.30"]}}}}}

PSI = {"lighthouseResult": {
    "categories": {"performance": {"score": 0.42}, "seo": {"score": 0.92}, "accessibility": {"score": 0.8},
                   "best-practices": {"score": 1}},
    "audits": {"largest-contentful-paint": {"numericValue": 5200.4}, "cumulative-layout-shift": {"numericValue": 0.02},
               "total-blocking-time": {"numericValue": 900}, "first-contentful-paint": {"numericValue": 2100},
               "speed-index": {"numericValue": 4000},
               "render-blocking-resources": {"title": "Loại bỏ tài nguyên chặn hiển thị", "score": 0.3,
                                             "details": {"type": "opportunity", "overallSavingsMs": 1200}},
               "uses-webp-images": {"title": "Dùng ảnh WebP", "score": 0.5,
                                    "details": {"type": "opportunity", "overallSavingsMs": 50}}}},
    "loadingExperience": {"metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 3100},
                                      "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 8}}}}


class ParseTest(unittest.TestCase):
    def test_history(self):
        pts = C.parse_history(HISTORY)
        self.assertEqual([p["period_end"] for p in pts], ["2026-10-04", "2026-10-11"])
        self.assertEqual((pts[0]["lcp"], pts[0]["inp"], pts[1]["cls"]), (2400, None, 0.30))

    def test_psi(self):
        r = C.parse_psi(PSI)
        self.assertEqual((r["perf"], r["seo"], r["bp"]), (42, 92, 100))
        self.assertAlmostEqual(r["lab"]["lcp"], 5200.4)
        self.assertEqual(r["field"], {"lcp": 3100, "cls": 0.08})  # CLS của PSI nhân 100
        self.assertEqual(r["opps"], [{"title": "Loại bỏ tài nguyên chặn hiển thị", "ms": 1200}])  # bỏ việc < 100 ms
        fb = dict(PSI, loadingExperience={**PSI["loadingExperience"], "origin_fallback": True})
        self.assertEqual(C.parse_psi(fb)["field"], {})  # số cả website trả thay: không coi là số của trang

    def test_rating_and_assess(self):
        self.assertEqual([C.rating("lcp", v) for v in (2000, 3000, 4500, None)], ["good", "ni", "poor", "none"])
        self.assertEqual(C.rating("cls", 0.1), "good")
        self.assertEqual(C.assess({"lcp": 2000, "inp": 150, "cls": 0.05}), "good")
        self.assertEqual(C.assess({"lcp": 2000, "inp": 600, "cls": 0.05}), "poor")
        self.assertEqual(C.assess({"lcp": 3000, "cls": 0.05}), "ni")
        self.assertEqual(C.assess({}), "none")
        self.assertEqual((C.fmt("lcp", 2450), C.fmt("inp", 180), C.fmt("cls", 0.123)), ("2,5 s", "180 ms", "0,12"))


class AuditTest(unittest.TestCase):
    def pages(self):
        opp = {"title": "Giảm JavaScript không dùng đến", "ms": 300}
        return [{"url": f"https://a.vn/{i}", "perf": perf, "seo": seo, "a11y": 90, "field": field, "opps": [opp],
                 "error": None}
                for i, (perf, seo, field) in enumerate([(40, 100, {}), (70, 85, {"lcp": 4500, "cls": 0.01}),
                                                        (95, 100, {})])]

    def test_metric_score(self):
        from seo_report import cwv_audit as CA
        self.assertEqual(CA.metric_score("lcp", 2000), 100)
        self.assertEqual(CA.metric_score("lcp", 4000), 50)
        self.assertEqual(CA.metric_score("lcp", 8000), 0)
        self.assertAlmostEqual(CA.metric_score("lcp", 3250), 75)

    def test_score_weights_and_missing_parts(self):
        from seo_report import cwv_audit as CA
        good = [{"lcp": 2000, "inp": 100, "cls": 0.0}]
        r = CA.score(good, good, self.pages())
        self.assertEqual(r["parts"], {"phone": 100, "desktop": 100, "lab": 68})
        self.assertEqual((r["score"], r["grade"]), (90, "Rất tốt"))   # 100·0,5 + 100·0,2 + 68·0,3 ≈ 90
        r = CA.score([], [], self.pages())  # chưa có số người dùng thật: chỉ tính PageSpeed
        self.assertEqual((r["score"], r["grade"]), (68, "Trung bình"))
        self.assertIsNone(CA.score([], [], [])["score"])

    def test_checks(self):
        from seo_report import cwv_audit as CA
        phone = [{"lcp": 1500, "inp": 150, "cls": 0.0, "ttfb": 1200, "fcp": 1500}] * 8 + [
            {"lcp": 2400, "inp": 150, "cls": 0.0, "ttfb": 1200, "fcp": 1500}]
        checks = {c["key"]: c for c in CA.audit(phone, [], self.pages())}
        self.assertEqual(checks["cwv_phone"]["level"], "ok")
        self.assertEqual(checks["near_lcp"]["level"], "medium")      # 2,4 s / ngưỡng 2,5 s
        self.assertIn("worse_lcp", checks)                            # 1,5 s → 2,4 s
        self.assertEqual(checks["ttfb_slow"]["level"], "medium")
        self.assertEqual(checks["perf_low"]["pages"], ["https://a.vn/0"])
        self.assertEqual(checks["page_field"]["pages"], ["https://a.vn/1"])
        self.assertEqual(checks["seo_low"]["pages"], ["https://a.vn/1"])
        self.assertEqual(len(checks["common_Giảm JavaScript không dùng đến"]["pages"]), 3)
        levels = [c["level"] for c in CA.audit(phone, [], self.pages())]
        self.assertEqual(levels, sorted(levels, key=["high", "medium", "info", "ok"].index))


class Fake:
    def __init__(self):
        self.psi_calls = []

    def crux_history(self, origin, form):
        if form == "DESKTOP":
            raise RuntimeError("404 NOT_FOUND: chrome ux report data not found")
        return HISTORY

    def psi(self, url, strategy):
        self.psi_calls.append(url)
        if "loi" in url:
            raise RuntimeError("500 INTERNAL")
        return PSI


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.cfg = SimpleNamespace(site_url=SITE)
        for i, (url, clicks) in enumerate([(SITE + "gong-kinh/", 50), (SITE + "loi/", 30), (SITE, 10)], 1):
            self.con.execute("INSERT INTO pages (id, site, url) VALUES (?, ?, ?)", (i, SITE, url))
            self.con.execute("INSERT INTO gsc_page_daily VALUES ('2026-11-01', ?, ?, 100, 3)", (i, clicks))

    def test_weekly_refresh(self):
        fake = Fake()
        logs = []
        r = C.refresh(self.con, self.cfg, date(2026, 11, 6), client=fake, log=logs.append, workers=1)
        self.assertEqual((r["origin_points"], r["pages"], r["errors"]), (2, 3, 1))
        self.assertEqual(fake.psi_calls[0], SITE)  # trang chủ trước, rồi theo click
        self.assertEqual(C.origin_series(self.con, "PHONE")[-1]["lcp"], 2700)
        self.assertEqual(C.origin_series(self.con, "DESKTOP"), [])  # chưa đủ lượt truy cập: không có số
        pages = {p["url"]: p for p in C.latest_pages(self.con)}
        self.assertEqual(pages[SITE + "gong-kinh/"]["perf"], 42)
        self.assertIn("500", pages[SITE + "loi/"]["error"])
        self.assertIsNone(C.refresh(self.con, self.cfg, date(2026, 11, 8), client=fake, log=logs.append))  # chưa đủ 7 ngày
        from unittest import mock
        with mock.patch.object(C, "_now", lambda: "2099-01-01T00:00:00+00:00"):  # lần sau, giờ khác
            self.assertIsNotNone(C.refresh(self.con, self.cfg, date(2026, 11, 8), client=fake, force=True,
                                           log=logs.append, workers=1))
        self.assertEqual(C.latest_pages(self.con)[0]["prev_perf"], 42)  # có điểm lần trước để so


if __name__ == "__main__":
    unittest.main()
