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

    def test_wait_pauses_late_and_extends_on_resume(self):
        from datetime import timedelta
        started = date(2026, 11, 3)
        with self.assertRaises(ValueError):
            O.update_item(self.con, self.soon, status=O.WAIT)  # phải nói chờ ai
        self.assertEqual(O.start_wait(self.con, [self.soon, self.done], "client", "chờ duyệt bài", by="an",
                                      today=started), 1)  # hạng mục đã xong thì bỏ qua
        a = O.alerts(self.con, self.today + timedelta(days=5))  # quá hạn 09/11 trong lúc chờ: không tính trễ
        self.assertNotIn(self.soon, [i["uid"] for i in a["late"] + a["due_soon"]])
        self.assertEqual([i["uid"] for i in a["waiting"]], [self.soon])
        w = a["waiting"][0]["wait"]
        self.assertEqual((w["who_label"], w["days"], w["note"]), ("khách duyệt", 9, "chờ duyệt bài"))
        self.assertEqual(O.wait_text(w), "Chờ khách duyệt 9 ngày: chờ duyệt bài")
        ov = O.overview(self.con, self.today + timedelta(days=5))
        self.assertEqual(ov["counts"][O.WAIT], 1)
        self.assertNotIn(self.soon, [i["uid"] for i in ov["late"]])
        # hết chờ sau 6 ngày: hạn dời thêm 6 ngày, ghi nhật ký gia hạn
        O.update_item(self.con, self.soon, today=started + timedelta(days=6), by="an", status=O.DOING)
        it = next(i for i in O.items(self.con) if i["uid"] == self.soon)
        self.assertEqual((it["status"], it["end"], it["wait"]), (O.DOING, "2026-11-15", None))
        log = O.extensions(self.con, self.soon)
        self.assertEqual((log[-1]["old_end"], log[-1]["new_end"]), ("2026-11-09", "2026-11-15"))
        self.assertEqual(log[-1]["reason"], "Chờ khách duyệt 6 ngày: chờ duyệt bài")
        self.assertEqual(O.wait_log(self.con, self.soon)[0]["days"], 6)

    def test_wait_reminder_notice(self):
        from seo_report import notices as N
        O.start_wait(self.con, [self.idle], "vendor", "chờ bên in ấn", today=date(2026, 11, 1))
        out = [n for n in N._okr(self.con, self.today) if "okr-wait" in n["key"]]
        self.assertEqual(len(out), 1)
        self.assertIn("đã chờ bên thứ ba 6 ngày", out[0]["title"])

    def test_update_log_and_links(self):
        O.add_update(self.con, self.soon, "Đã gửi bản nháp cho khách", by="an@x.vn")
        O.add_update(self.con, self.soon, "Khách góp ý lần 1", by="binh@x.vn")
        log = O.updates(self.con, self.soon)
        self.assertEqual([x["text"] for x in log], ["Khách góp ý lần 1", "Đã gửi bản nháp cho khách"])
        it = next(i for i in O.items(self.con) if i["uid"] == self.soon)
        self.assertEqual(it["note"], "Khách góp ý lần 1")  # dòng mới nhất là ghi chú (ghi lên sheet)
        with self.assertRaises(ValueError):
            O.add_update(self.con, self.soon, "   ")
        O.set_links(self.con, self.soon, ["https://docs.google.com/document/d/a", " https://x.vn/bai/ ",
                                          "https://x.vn/bai/"])
        it = next(i for i in O.items(self.con) if i["uid"] == self.soon)
        self.assertEqual(O.links(it), ["https://docs.google.com/document/d/a", "https://x.vn/bai/"])
        with self.assertRaises(ValueError):
            O.set_links(self.con, self.soon, ["x.vn/khong-co-http"])
        rows = O.sheet_rows(self.con, "Q4", "", "", today=self.today)
        row = next(r for r in rows if r and r[0] == it["code"])
        self.assertIn("https://x.vn/bai/", row[12])
        self.assertIn("Khách góp ý lần 1", row[13])
        O.delete_items(self.con, [self.soon])
        self.assertEqual(O.updates(self.con, self.soon), [])

    def test_last_updates_and_progress_of(self):
        O.add_update(self.con, self.soon, "một", by="an")
        O.add_update(self.con, self.soon, "hai", by="an")
        O.add_update(self.con, self.idle, "ba", by="binh")
        lu = O.last_updates(self.con)
        self.assertEqual((lu[self.soon]["text"], lu[self.idle]["text"]), ("hai", "ba"))
        self.assertNotIn(self.late, lu)
        self.assertEqual(O.progress_of({"status": O.DONE, "progress": None}), 100.0)  # xong mà chưa ghi %
        self.assertEqual(O.progress_of({"status": O.DOING, "progress": 40}), 40.0)

    def test_pause_not_late_not_counted(self):
        O.update_item(self.con, self.late, status=O.PAUSE)
        a = O.alerts(self.con, self.today)
        self.assertNotIn(self.late, [i["uid"] for k in ("late", "due_soon", "not_started", "waiting") for i in a[k]])
        ov = O.overview(self.con, self.today)
        self.assertEqual(ov["total"], 3)  # 4 hạng mục, 1 tạm hoãn: không tính vào % hoàn thành
        self.assertEqual([i["uid"] for i in ov["paused"]], [self.late])
        self.assertEqual(ov["counts"][O.PAUSE], 1)
        self.assertEqual(ov["objectives"][0]["pct"], 1 / 3)  # 1 xong / 3 hạng mục còn tính
        self.assertFalse(O.is_late(next(i for i in ov["items"] if i["uid"] == self.late), self.today))
        # mở lại: chọn hạn mới (ghi nhật ký gia hạn) rồi đổi trạng thái
        O.extend(self.con, [self.late], new_end="2026-11-30", reason="Mở lại sau tạm hoãn", today=self.today)
        O.set_status_many(self.con, [self.late], O.DOING)
        it = next(i for i in O.items(self.con) if i["uid"] == self.late)
        self.assertEqual((it["status"], it["end"]), (O.DOING, "2026-11-30"))
        self.assertEqual(O.norm_status("Tạm hoãn"), O.PAUSE)
        self.assertEqual(O.norm_status("Pending"), O.PAUSE)
        self.assertEqual(O.norm_status("Chờ khách"), O.WAIT)

    def test_sheet_status_wait(self):
        self.assertEqual(O.norm_status("Đang chờ duyệt"), O.WAIT)
        self.assertEqual(O.norm_status("Đang làm"), O.DOING)

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
