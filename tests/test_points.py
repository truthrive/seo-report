import sqlite3
import unittest
from datetime import date

from seo_report import access as A
from seo_report import points as PT


def member(email="seo@x.vn"):
    return A.in_project(A.User(email, A.MEMBER), A.EDITOR)


class PointsTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        PT.ensure(self.con)
        self.d = date(2026, 11, 9)

    def tearDown(self):
        self.con.close()

    def test_costs(self):
        self.assertEqual(PT.rank_points([10, 20, 20, 30]), 1 + 2 + 2 + 3)
        self.assertEqual(PT.cost("aio", 25), 50)
        self.assertEqual(PT.cost("backlink"), 150)

    def test_member_limit_spend_refund_and_new_month(self):
        u = member()
        PT.set_limit(self.con, "seo@x.vn", 10, "boss")
        i = PT.spend(self.con, u, "a.vn", "research", 6, today=self.d)
        self.assertEqual(PT.balance(self.con, "seo@x.vn", "2026-11")["left"], 4)
        with self.assertRaises(PT.NotEnough):
            PT.spend(self.con, u, "a.vn", "aio", 6, today=self.d)
        PT.refund(self.con, i)
        self.assertEqual(PT.balance(self.con, "seo@x.vn", "2026-11")["left"], 10)
        PT.spend(self.con, u, "a.vn", "aio", 10, today=self.d)
        self.assertEqual(PT.balance(self.con, "seo@x.vn", "2026-12")["left"], 10)  # tháng mới: đặt lại

    def test_grant_adds_this_month_only(self):
        PT.grant(self.con, "seo@x.vn", 500, "admin", today=self.d)
        self.assertEqual(PT.balance(self.con, "seo@x.vn", "2026-11")["limit"], PT.DEFAULT_MONTHLY + 500)
        self.assertEqual(PT.balance(self.con, "seo@x.vn", "2026-12")["limit"], PT.DEFAULT_MONTHLY)
        with self.assertRaises(ValueError):
            PT.grant(self.con, "seo@x.vn", 0, "admin")

    def test_admin_unlimited_but_logged_guest_free(self):
        admin = A.in_project(A.User("ad@x.vn", A.ADMIN), A.EDITOR)
        self.assertIsNotNone(PT.spend(self.con, admin, "a.vn", "backlink", 999_999, today=self.d))
        self.assertEqual(PT.used(self.con, "ad@x.vn", "2026-11"), 0)  # không tính vào hạn mức
        guest = A.in_project(A.User("k@x.vn", A.MEMBER), A.CLIENT)
        self.assertIsNone(PT.spend(self.con, guest, "a.vn", "research", 2, today=self.d))
        rows = PT.usage(self.con, "2026-11")
        self.assertEqual([(r["email"], r["member"], r["points"]) for r in rows], [("ad@x.vn", False, 999_999)])

    def test_calc(self):
        r = PT.calc(rank_keywords=100, rank_depth=30, rank_times=4, aio=25, backlink=1, research=0)
        self.assertEqual([x[3] for x in r["lines"]], [100 * 4 * 3, 50, 150])
        self.assertEqual(r["total"], 1400)
        self.assertEqual(PT.calc()["total"], 0)

    def test_label_only_for_members(self):
        self.assertEqual(PT.label(member(), "aio", 3), " · 6 điểm")
        self.assertEqual(PT.label(A.User("o@x.vn", A.EDITOR), "aio", 3), "")


if __name__ == "__main__":
    unittest.main()
