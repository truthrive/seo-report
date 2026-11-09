import sqlite3
import unittest

from seo_report import feedback as FB


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")

    def test_add_and_list_mine(self):
        FB.add(self.con, "Khach@Example.com ", "Số click tuần này lệch GSC", "Tổng quan", "/?days=28", "data")
        FB.add(self.con, "other@example.com", "Câu hỏi khác")
        mine = FB.list_mine(self.con, "khach@example.com")
        self.assertEqual(len(mine), 1)
        self.assertEqual((mine[0]["page"], mine[0]["path"], mine[0]["category"], mine[0]["status"]),
                         ("Tổng quan", "/?days=28", "data", "new"))
        self.assertEqual(FB.count_new(self.con), 2)

    def test_validation(self):
        with self.assertRaises(ValueError):
            FB.add(self.con, "a@b.c", "   ")
        with self.assertRaises(ValueError):
            FB.add(self.con, "a@b.c", "x" * (FB.MAX_LEN + 1))
        fid = FB.add(self.con, "a@b.c", "ok", category="lạ")
        self.assertEqual(FB.list_all(self.con)[0]["category"], "other")
        with self.assertRaises(ValueError):
            FB.reply(self.con, fid, " ", "team@x")

    def test_flow_new_seen_reply_done_reopen(self):
        fid = FB.add(self.con, "a@b.c", "Nhờ kiểm tra")
        FB.mark_seen(self.con, [fid])
        self.assertEqual(FB.list_all(self.con)[0]["status"], "seen")
        self.assertEqual(FB.count_new(self.con), 0)
        FB.reply(self.con, fid, "Đã kiểm tra, số đúng", "team@x", done=True)
        f = FB.list_all(self.con)[0]
        self.assertEqual((f["status"], f["reply"], f["replied_by"]), ("done", "Đã kiểm tra, số đúng", "team@x"))
        self.assertTrue(f["done_at"])
        FB.set_status(self.con, fid, "seen")
        f = FB.list_all(self.con)[0]
        self.assertEqual((f["status"], f["done_at"]), ("seen", None))
        self.assertEqual(len(FB.list_all(self.con, status="done")), 0)


if __name__ == "__main__":
    unittest.main()
