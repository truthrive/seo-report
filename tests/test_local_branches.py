import sqlite3
import unittest
from datetime import date

from seo_report import gbp as G
from seo_report import gbp_reviews as GR
from seo_report import local_branches as LB

TODAY = date(2026, 11, 20)


def add_review(con, loc, rid, rating, created, reply=None):
    con.execute("INSERT INTO gbp_reviews VALUES (?, ?, 'A', ?, 'x', ?, ?, ?, ?, 'x')",
                (loc, rid, rating, created, created, reply, created if reply else None))


class BranchCompareTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        G.ensure_tables(self.con)
        GR.ensure_tables(self.con)
        self.locs = [{"name": "L1", "title": "Mắt Kính Tâm Đức - Gò Vấp"},
                     {"name": "L2", "title": "Mắt Kính Tâm Đức - Quận 1"}]
        i = 0
        # Gò Vấp: 10 đánh giá trong kỳ, 4 sao thấp (2 chưa trả lời)
        for st in (5, 5, 5, 5, 5, 5, 1, 2, 3, 3):
            i += 1
            add_review(self.con, "L1", str(i), st, "2026-11-10T00:00:00Z", None if st in (1, 2) else "cảm ơn")
        # Quận 1: 10 đánh giá, 1 sao thấp đã trả lời
        for st in (5, 5, 5, 5, 5, 5, 5, 4, 4, 2):
            i += 1
            add_review(self.con, "L2", str(i), st, "2026-11-12T00:00:00Z", "cảm ơn")
        add_review(self.con, "L2", "old", 1, "2026-03-05T00:00:00Z", "xin lỗi")  # ngoài kỳ 28 ngày

    def test_short(self):
        self.assertEqual(LB.short("Mắt Kính Tâm Đức - Gò Vấp"), "Gò Vấp")
        self.assertEqual(LB.short("Nha khoa Tinh Hoa"), "Nha khoa Tinh Hoa")

    def test_review_block(self):
        rs = GR.rows(self.con, ["L1"])
        b = LB.review_block(rs, date(2026, 11, 1), TODAY)
        self.assertEqual((b["total"], b["low"], b["stars"][3]), (10, 4, 2))
        self.assertAlmostEqual(b["low_share"], 0.4)

    def test_compare_flags_low_share_branch_first(self):
        out = LB.compare(self.con, self.locs, "https://x.vn/", 28, today=TODAY)
        rows = out["rows"]
        self.assertEqual(rows[0]["short"], "Gò Vấp")  # cần xem trước
        self.assertEqual(rows[0]["low_unanswered"], 2)
        self.assertAlmostEqual(rows[0]["low_part"], 0.8)  # 4 / 5 đánh giá thấp của hệ thống
        texts = " | ".join(t for _, t in rows[0]["flags"])
        self.assertIn("Sao thấp 40%", texts)
        self.assertIn("2 đánh giá thấp chưa trả lời", texts)
        self.assertEqual(out["totals"]["reviews"]["low"], 5)
        self.assertEqual(rows[1]["reviews"]["total"], 10)  # đánh giá tháng 3 không tính vào kỳ
        self.assertEqual(rows[1]["life"]["total"], 11)

    def test_month_matrix(self):
        m = LB.month_matrix(self.con, self.locs, today=TODAY)
        self.assertEqual((m["months"][0], m["months"][-1], len(m["months"])), ("2025-12", "2026-11", 12))
        nov = m["rows"][0]["cells"][-1]
        self.assertEqual((nov["total"], nov["low"]), (10, 4))
        mar = m["rows"][1]["cells"][m["months"].index("2026-03")]
        self.assertEqual((mar["total"], mar["share"]), (1, 1.0))
        self.assertIsNone(m["rows"][0]["cells"][0]["share"])  # tháng không có đánh giá

    def test_recent_low(self):
        lows = LB.recent_low(self.con, "L1")
        self.assertEqual(len(lows), 4)
        self.assertTrue(all(r["rating"] <= 3 for r in lows))


if __name__ == "__main__":
    unittest.main()
