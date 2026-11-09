import sqlite3
import unittest
from datetime import date
from types import SimpleNamespace

from seo_report import access as A
from seo_report import feedback as FB
from seo_report import notices as N
from seo_report import okr as O


def user(email, role):
    return A.User(email, role)


class NoticesTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        O.ensure_tables(self.con)
        O.take_over(self.con)
        O.add_cycle(self.con, "Q4", "2026-10-01", "2026-12-31")
        o = O.add_objective(self.con, "Q4", "Nền tảng")
        self.late = O.add_item(self.con, o, "Trễ", start="2026-10-01", end="2026-11-01")
        O.add_item(self.con, o, "Sắp hạn", start="2026-11-01", end="2026-11-09")
        self.today = date(2026, 11, 7)
        self.cfg = SimpleNamespace(site_url="sc-domain:x.vn", rank=None)
        self.fb = FB.add(self.con, "khach@x.vn", "Số click tuần này sai?", category="data")
        self.team = user("team@x.vn", A.EDITOR)
        self.client = user("khach@x.vn", A.CLIENT)

    def tearDown(self):
        self.con.close()

    def test_team_sees_okr_and_support_heaviest_first(self):
        ns = N.collect(self.con, self.cfg, self.team, today=self.today)
        kinds = [(n["kind"], n["level"]) for n in ns]
        self.assertIn(("okr", "high"), kinds)
        self.assertIn(("support", "high"), kinds)  # báo lỗi số liệu: cần xử lý
        self.assertIn(("okr", "medium"), kinds)
        self.assertEqual([n["level"] for n in ns], sorted((n["level"] for n in ns), key=N._ORDER.get))

    def test_client_sees_only_replies_to_own_requests(self):
        self.assertEqual(N.collect(self.con, self.cfg, self.client, today=self.today), [])
        FB.reply(self.con, self.fb, "Đã kiểm tra, số đúng", "team@x.vn")
        ns = N.collect(self.con, self.cfg, self.client, today=self.today)
        self.assertEqual([(n["kind"], n["href"]) for n in ns], [("support", "/yeu-cau")])

    def test_mark_seen_per_user_and_new_key_after_extension(self):
        ns = N.collect(self.con, self.cfg, self.team, today=self.today)
        N.mark_seen(self.con, self.team, [n["key"] for n in ns])
        self.assertEqual(N.unseen(N.collect(self.con, self.cfg, self.team, today=self.today)), 0)
        other = user("b@x.vn", A.VIEWER)
        self.assertGreater(N.unseen(N.collect(self.con, self.cfg, other, today=self.today)), 0)
        O.extend(self.con, [self.late], new_end="2026-11-05")  # gia hạn rồi lại trễ: báo lại
        again = [n for n in N.collect(self.con, self.cfg, self.team, today=self.today) if not n["seen"]]
        self.assertEqual([n["kind"] for n in again], ["okr"])


if __name__ == "__main__":
    unittest.main()
