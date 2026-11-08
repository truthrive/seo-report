import unittest
from datetime import date

from seo_report import kpi as KP


class PeriodSessionsTest(unittest.TestCase):
    """Phiên của một kỳ: ưu tiên tổng kỳ của GA4 (khớp giao diện GA4); không có thì cộng theo ngày."""

    def test_uses_period_total_when_available(self):
        def daily(source, s, e):
            return {"20261101": 100, "20261102": 100}  # cộng lại 200, nhưng GA4 tổng kỳ là 196
        daily.total = lambda source, s, e: 196
        self.assertEqual(KP._period_sessions(daily, "organic", date(2026, 11, 1), date(2026, 11, 2)), 196)

    def test_falls_back_to_daily_sum(self):
        def daily(source, s, e):
            return {"20261101": 100, "20261102": 50}
        self.assertEqual(KP._period_sessions(daily, "organic", date(2026, 11, 1), date(2026, 11, 2)), 150)


if __name__ == "__main__":
    unittest.main()
