import unittest
from datetime import date, timedelta

from seo_report.web_dashboard import buckets, kpi_counts, kpi_rank_line, windows


class BucketsTest(unittest.TestCase):
    """Biểu đồ nhỏ phải biểu diễn đúng khoảng ngày mà số tổng của ô đang tính, và kỳ so sánh phải thẳng hàng."""

    def test_every_window_covers_exactly_its_days(self):
        end = date(2026, 11, 3)
        for days in (7, 28, 90):
            cur, prev = windows(end, days)
            for rng in (cur, prev):
                b = buckets(rng, days)
                covered = [s + timedelta(days=k) for s, e in b for k in range((e - s).days + 1)]
                expect = [rng[0] + timedelta(days=k) for k in range(days)]
                self.assertEqual(covered, expect, f"{days} ngày: thiếu / thừa / trùng ngày")

    def test_previous_period_points_align_one_to_one(self):
        cur, prev = windows(date(2026, 11, 3), 90)
        b, pb = buckets(cur, 90), buckets(prev, 90)
        self.assertEqual(len(b), len(pb))
        # điểm thứ i của kỳ này và kỳ trước cách nhau đúng 90 ngày, cùng độ dài
        self.assertTrue(all(c[0] - p[0] == timedelta(days=90) and (c[1] - c[0]) == (p[1] - p[0])
                            for c, p in zip(b, pb)))
        self.assertEqual(prev[1] + timedelta(days=1), cur[0])  # hai kỳ liền nhau, không chồng / hở


class KpiRankLineTest(unittest.TestCase):
    def test_line_from_running_month(self):
        p = {"lines": [{"kind": "rank", "top": 3}, {"kind": "level", "source": "organic"}],
             "months": [{"n": 1, "status": "done", "checks": {"top3": {"checked": 1, "count": 1, "total": 4}}},
                        {"n": 2, "status": "running", "checks": {"top3": {"checked": 2, "count": 2, "total": 4}}},
                        {"n": 3, "status": "future", "checks": {}}]}
        self.assertIn("tháng dự án 2", kpi_rank_line(p))
        self.assertIn("Top 3 <b>2/4</b>", kpi_rank_line(p))
        self.assertIn("tháng đang chạy", kpi_rank_line(p))      # tháng chưa hết: không nói "cuối tháng"
        p["months"][1]["status"] = "done"
        p["months"][2]["status"] = "running"
        p["months"][2]["checks"] = {}
        self.assertEqual(kpi_rank_line(p), "")                   # tháng đang chạy chưa có lần check
        p["months"][2]["status"] = "future"
        self.assertIn("tháng dự án 2 (bộ cam kết, lần check cuối tháng)", kpi_rank_line(p))

    def test_empty(self):
        self.assertEqual(kpi_rank_line(None), "")
        self.assertEqual(kpi_rank_line({"lines": [{"kind": "level", "source": "organic"}],
                                        "months": [{"n": 1, "status": "running", "checks": {}}]}), "")


class KpiCountsTest(unittest.TestCase):
    def test_counts_same_rule_as_kpi_block(self):
        from unittest import mock
        p = {"lines": [{"kind": "rank", "top": 3}, {"kind": "rank", "top": 10}, {"kind": "level", "source": "organic"}],
             "months": [{"n": 1, "status": "done", "checks": {}},
                        {"n": 2, "status": "running",
                         "checks": {"top3": {"target": 5}, "top10": {"target": 10}, "level:organic": {"target": None}}},
                        {"n": 3, "status": "future", "checks": {}}]}
        tones = iter([("Đang đạt", "green"), ("Thiếu 2 từ khóa", "amber")])
        with mock.patch("seo_report.kpi.status", lambda ch, running: next(tones)):
            self.assertEqual(kpi_counts(p), (1, 2, 2, True))  # tháng không cam kết (target None) không tính
        self.assertIsNone(kpi_counts(None))


if __name__ == "__main__":
    unittest.main()
