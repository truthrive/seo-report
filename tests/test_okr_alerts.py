import sqlite3
import unittest
from datetime import date

from seo_report import okr as O


class OkrAlertsTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        O.ensure_tables(self.con)
        O.take_over(self.con)
        O.add_cycle(self.con, "Q4", "2026-10-01", "2026-12-31")
        o = O.add_objective(self.con, "Q4", "Nền tảng")
        self.late = O.add_item(self.con, o, "Trễ", start="2026-10-01", end="2026-11-01")
        self.soon = O.add_item(self.con, o, "Sắp hạn", start="2026-11-01", end="2026-11-09")
        self.idle = O.add_item(self.con, o, "Chưa bắt đầu", start="2026-11-05", end="2026-11-30")
        self.done = O.add_item(self.con, o, "Xong rồi", start="2026-10-01", end="2026-10-05")
        O.update_item(self.con, self.done, status=O.DONE)
        self.today = date(2026, 11, 7)

    def test_alert_groups(self):
        a = O.alerts(self.con, self.today)
        self.assertEqual(a["cycle"], "Q4")
        self.assertEqual([i["uid"] for i in a["late"]], [self.late])  # đã xong thì không báo
        self.assertEqual([i["uid"] for i in a["due_soon"]], [self.soon])
        self.assertEqual([i["uid"] for i in a["not_started"]], [self.soon, self.idle])

    def test_extend_from_today_when_overdue_and_log(self):
        n = O.extend(self.con, [self.late], days=7, by="team@x", reason="chờ khách duyệt", today=self.today)
        self.assertEqual(n, 1)
        it = next(i for i in O.items(self.con) if i["uid"] == self.late)
        self.assertEqual(it["end"], "2026-11-14")  # hạn cũ đã qua: tính từ hôm nay
        log = O.extensions(self.con, self.late)
        self.assertEqual((log[0]["old_end"], log[0]["new_end"], log[0]["reason"]),
                         ("2026-11-01", "2026-11-14", "chờ khách duyệt"))
        O.extend(self.con, [self.soon], days=3, today=self.today)  # chưa quá hạn: cộng vào hạn cũ
        self.assertEqual(next(i for i in O.items(self.con) if i["uid"] == self.soon)["end"], "2026-11-12")
        self.assertEqual(O.extension_counts(self.con), {self.late: 1, self.soon: 1})
        self.assertEqual(O.alerts(self.con, self.today)["late"], [])
        with self.assertRaises(ValueError):
            O.extend(self.con, [self.idle], new_end="2026-11-01")  # trước ngày bắt đầu

    def test_sheet_warns_extension(self):
        O.extend(self.con, [self.late], days=7, today=self.today)
        rows = O.sheet_rows(self.con, "Q4", "x", "y", self.today)
        row = next(r for r in rows if r[:1] == ["O1.01"])
        self.assertIn("Gia hạn 1 lần", row[-1])

    def test_bulk_delete_and_status(self):
        O.set_status_many(self.con, [self.late, self.soon], O.DOING)
        self.assertEqual({i["status"] for i in O.items(self.con) if i["uid"] in (self.late, self.soon)}, {O.DOING})
        O.extend(self.con, [self.late], days=1, today=self.today)
        O.delete_items(self.con, [self.late, self.soon])
        self.assertEqual(sorted(i["title"] for i in O.items(self.con) if not i["is_objective"]),
                         ["Chưa bắt đầu", "Xong rồi"])
        self.assertEqual(O.extension_counts(self.con), {})


if __name__ == "__main__":
    unittest.main()
