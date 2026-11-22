import sqlite3
import unittest
from datetime import date, datetime

from seo_report import ai_auto as AU
from seo_report import ai_settings as AIS


class DueTest(unittest.TestCase):
    def test_weekly(self):
        st = {"days": [0, 1, 2, 3, 4, 5], "time": "07:00"}
        mon = datetime(2026, 11, 9, 7, 0)  # thứ Hai
        self.assertTrue(AU.due(mon, st, "weekly", None))
        self.assertFalse(AU.due(mon.replace(hour=6, minute=59), st, "weekly", None))
        self.assertTrue(AU.due(mon.replace(hour=11, minute=59), st, "weekly", "2026-11-08"))  # chạy bù trong 5 giờ
        self.assertFalse(AU.due(mon.replace(hour=12, minute=1), st, "weekly", None))
        self.assertFalse(AU.due(mon, st, "weekly", "2026-11-09"))
        self.assertFalse(AU.due(datetime(2026, 11, 15, 7, 5), st, "weekly", None))  # Chủ nhật
        self.assertTrue(AU.due(datetime(2026, 11, 9, 8, 30), {"days": [0], "time": "08:00"}, "weekly", None))

    def test_monthly(self):
        st = {"day": 1, "time": "08:00"}
        self.assertFalse(AU.due(datetime(2026, 12, 1, 7, 59), st, "monthly", None))
        self.assertTrue(AU.due(datetime(2026, 12, 1, 8, 0), st, "monthly", "2026-11-01"))
        self.assertTrue(AU.due(datetime(2026, 12, 3, 6, 0), st, "monthly", "2026-11-01"))  # máy tắt ngày 1: chạy bù
        self.assertFalse(AU.due(datetime(2026, 12, 3, 9, 0), st, "monthly", "2026-12-01"))  # tháng này đã chạy

    def test_runs(self):
        con = sqlite3.connect(":memory:")
        self.assertIsNone(AU.last_run(con, "brief"))
        AU.mark(con, "brief", date(2026, 11, 9), "ok")
        AU.mark(con, "aio_answer", date(2026, 11, 10), "ok")
        self.assertEqual(AU.last_run(con, "brief"), "2026-11-09")
        self.assertEqual(len(AU.runs(con)), 2)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")

    def test_defaults_override_and_cap(self):
        c = self.con
        self.assertEqual(AIS.task_settings(c, "brief")["time"], "07:00")
        AIS.save_task(c, "brief", {"time": "06:30", "days": [0, 2], "bogus": 1})
        st = AIS.task_settings(c, "brief")
        self.assertEqual((st["time"], st["days"]), ("06:30", [0, 2]))
        self.assertNotIn("bogus", st)
        AIS.save_override(c, "https://a.vn/", "brief", "auto", False)
        self.assertFalse(AIS.effective(c, "https://a.vn/", "brief")["auto"])
        self.assertTrue(AIS.effective(c, "https://b.vn/", "brief")["auto"])
        AIS.save_override(c, "https://a.vn/", "brief", "auto", None)  # về theo chung
        self.assertTrue(AIS.effective(c, "https://a.vn/", "brief")["auto"])
        self.assertEqual(AIS.cap(c), AIS.CAP_DEFAULT)
        AIS.set_cap(c, 50)
        self.assertEqual(AIS.cap(c), 50)

    def test_calls_summary(self):
        c = self.con
        AIS.ensure(c)
        for trig, ok in (("auto", 1), ("auto", 0), ("manual", 1)):
            c.execute("INSERT INTO ai_calls (at, month, site, task, trigger, ok, credits) VALUES "
                      "('2026-11-10T01:00:00+00:00', '2026-11', 'a', 'brief', ?, ?, 5)", (trig, ok))
        self.assertEqual(AIS.auto_used(c, "2026-11"), 2)
        s = AIS.summary(c, "2026-11")
        self.assertEqual((s["total"], s["auto"], s["errors"], s["credits"]), (3, 2, 1, 15))
        self.assertEqual(len(AIS.calls(c, "2026-11", "a")), 3)


if __name__ == "__main__":
    unittest.main()
