import sqlite3
import unittest
from datetime import date

from seo_report import okr as O


def _seed(con):
    """Hai mục tiêu, ba hạng mục như vừa đồng bộ từ sheet (trước khi chuyển sang tool)."""
    its = [
        {"code": "O1", "objective": "O1", "is_objective": True, "grp": "", "title": "Audit", "details": "", "qty": "",
         "unit": "", "month_text": "", "start": "2026-10-08", "end": "2026-11-27", "pic": "", "status": "",
         "status_raw": "", "progress": None, "link": "", "note": "", "sort": 0},
        {"code": "O1.01", "objective": "O1", "is_objective": False, "grp": "", "title": "Audit kỹ thuật", "details": "",
         "qty": "", "unit": "", "month_text": "", "start": "2026-10-08", "end": "2026-10-20", "pic": "Thịnh",
         "status": O.DONE, "status_raw": "Hoàn thành", "progress": 100.0, "link": "", "note": "", "sort": 1},
        {"code": "O1.02", "objective": "O1", "is_objective": False, "grp": "", "title": "Audit nội dung", "details": "",
         "qty": "", "unit": "", "month_text": "", "start": "2026-10-21", "end": "2026-11-27", "pic": "", "status": O.TODO,
         "status_raw": "", "progress": None, "link": "", "note": "", "sort": 2},
    ]
    O.save(con, O.combine([("OKRs 3 tháng", its)]), [], date(2026, 11, 1), "api")


class OkrToolTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        _seed(self.con)

    def test_take_over_keeps_items_and_builds_cycles(self):
        self.assertFalse(O.tool_owned(self.con))
        O.take_over(self.con, date(2026, 11, 7))
        self.assertTrue(O.tool_owned(self.con))
        self.assertEqual(len(O.items(self.con)), 3)
        self.assertEqual(O.cycle_list(self.con),
                         [{"name": "OKRs 3 tháng", "start": "2026-10-08", "end": "2026-11-27"}])

    def test_codes_and_order(self):
        O.take_over(self.con)
        o2 = O.add_objective(self.con, "OKRs 3 tháng", "Nội dung")
        a = O.add_item(self.con, o2, "Viết bài A", pic="Lan")
        O.add_item(self.con, "O1", "Audit schema")
        codes = [i["code"] for i in O.items(self.con)]
        self.assertEqual(codes, ["O1", "O1.01", "O1.02", "O1.03", "O2", "O2.01"])
        self.assertEqual(next(i for i in O.items(self.con) if i["uid"] == a)["status"], O.TODO)

    def test_update_status_logs_and_sets_progress(self):
        O.take_over(self.con)
        O.update_item(self.con, "O1.02", today=date(2026, 11, 7), status=O.DONE)
        it = next(i for i in O.items(self.con) if i["uid"] == "O1.02")
        self.assertEqual((it["status"], it["progress"], it["status_raw"]), (O.DONE, 100.0, "Hoàn thành"))
        self.assertEqual(O.done_dates(self.con)["O1.02"], "2026-11-07")
        with self.assertRaises(ValueError):
            O.update_item(self.con, "O1.02", title="  ")
        with self.assertRaises(ValueError):
            O.update_item(self.con, "O1.02", start="2026-12-01", end="2026-11-01")

    def test_delete_objective_removes_children(self):
        O.take_over(self.con)
        O.delete_item(self.con, "O1")
        self.assertEqual(O.items(self.con), [])

    def test_copy_cycle_shifts_dates_and_resets_status(self):
        O.take_over(self.con)
        O.add_cycle(self.con, "Q1/2027", "2027-01-07", "2027-03-31", copy_from="OKRs 3 tháng")
        new = [i for i in O.items(self.con) if i["cycle"] == "Q1/2027"]
        self.assertEqual(len(new), 3)
        kid = next(i for i in new if i["code"] == "O1.01")
        self.assertEqual((kid["start"], kid["status"], kid["progress"]), ("2027-01-07", O.TODO, None))
        obj = next(i for i in new if i["is_objective"])
        self.assertEqual(kid["objective"], obj["uid"])
        with self.assertRaises(ValueError):
            O.add_cycle(self.con, "q1/2027", None, None)

    def test_rename_cycle_moves_items(self):
        O.take_over(self.con)
        O.update_cycle(self.con, "OKRs 3 tháng", "Q4/2026", "2026-10-08", "2026-12-31")
        self.assertEqual({i["cycle"] for i in O.items(self.con)}, {"Q4/2026"})

    def test_sync_after_take_over_only_reads_weekly(self):
        O.take_over(self.con)
        O.save_tasks(self.con, [{"row": 3, "week": "2026-11-02", "kind": "", "okr_code": "O1.02", "item": "",
                                 "task": "Viết outline", "link": "", "issue": "", "pic": "", "priority": "",
                                 "start": None, "deadline": None, "status": O.TODO, "status_raw": "",
                                 "progress": None, "note": ""}], "api")
        self.assertEqual(len(O.items(self.con)), 3)
        self.assertEqual(len(O.tasks(self.con)), 1)

    def test_sync_reads_only_weekly_tab_when_tool_owned(self):
        from types import SimpleNamespace
        from unittest import mock
        O.take_over(self.con)
        tables = {"OKRs 3 tháng": [["ID", "Hạng mục công việc"], ["O9", "Từ sheet"]],
                  "Weekly Task Tracker": [["Ngày", "Task tuần / hành động"], ["03/11/2026", "Viết bài"]]}
        cfg = SimpleNamespace(okr=SimpleNamespace(weekly_tab="Weekly Task Tracker"))
        with mock.patch.object(O, "fetch_tables", return_value=(tables, "api")):
            res = O.sync(self.con, cfg, date(2026, 11, 7))
        self.assertEqual((res["items"], res["tasks"]), (2, 1))
        self.assertNotIn("O9", [i["code"] for i in O.items(self.con)])  # OKR trên tool không bị sheet ghi đè

    def test_sheet_rows_round_trip(self):
        O.take_over(self.con)
        rows = O.sheet_rows(self.con, "OKRs 3 tháng", "Ghi chú.", "07/11/2026 10:00", date(2026, 11, 7))
        self.assertEqual(rows[3], O.SHEET_HEAD)
        back = O.parse_okr(rows, date(2026, 11, 7))  # đọc lại được bằng bộ đọc tab OKR cũ
        self.assertEqual([b["code"] for b in back], ["O1", "O1.01", "O1.02"])
        self.assertEqual(back[1]["status"], O.DONE)
        self.assertEqual(back[1]["start"], "2026-10-08")


class OkrTemplateTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        O.ensure_tables(self.con)
        O.take_over(self.con)
        O.add_cycle(self.con, "Q1/2027", "2027-01-01", "2027-03-31")

    def test_builtin_template_fills_cycle_with_scaled_dates(self):
        t = O.builtin_templates()[0]
        res = O.apply_template(self.con, "Q1/2027", t, include=[0, 4])
        self.assertEqual(res["objectives"], 2)
        its = O.items(self.con)
        self.assertEqual([i["code"] for i in its if i["is_objective"]], ["O1", "O2"])
        leaf = [i for i in its if not i["is_objective"]]
        self.assertTrue(all("2027-01-01" <= i["start"] <= i["end"] <= "2027-03-31" for i in leaf))
        self.assertEqual(leaf[0]["start"], "2027-01-01")  # hạng mục đầu bắt đầu cùng đợt
        self.assertTrue(all(i["status"] == O.TODO for i in leaf))

    def test_quick_paste(self):
        q = O.parse_quick("Tăng traffic\n- Viết 10 bài | CONTENT\n  Tối ưu onpage\n\nLocal\n* GBP")
        self.assertEqual([(o["title"], [i["title"] for i in o["items"]]) for o in q["objectives"]],
                         [("Tăng traffic", ["Viết 10 bài", "Tối ưu onpage"]), ("Local", ["GBP"])])
        self.assertEqual(q["objectives"][0]["items"][0]["pic"], "CONTENT")
        self.assertEqual(O.parse_quick("- lẻ")["objectives"][0]["title"], "Mục tiêu 1")

    def test_save_cycle_as_template_round_trip(self):
        O.apply_template(self.con, "Q1/2027", O.parse_quick("A\n- a1 | SEO\n- a2"))
        app = sqlite3.connect(":memory:")
        O.save_template(app, "Khung của tôi", O.template_from_cycle(self.con, "Q1/2027"))
        mine = O.saved_templates(app)
        self.assertEqual([t["name"] for t in mine], ["Khung của tôi"])
        O.add_cycle(self.con, "Q2/2027", "2027-04-01", "2027-06-30")
        O.apply_template(self.con, "Q2/2027", mine[0])
        q2 = [i for i in O.items(self.con) if i["cycle"] == "Q2/2027" and not i["is_objective"]]
        self.assertEqual([(i["title"], i["pic"]) for i in q2], [("a1", "SEO"), ("a2", "")])
        with self.assertRaises(ValueError):
            O.save_template(app, "Rỗng", {"objectives": []})
        O.delete_template(app, mine[0]["key"])
        self.assertEqual(O.saved_templates(app), [])


if __name__ == "__main__":
    unittest.main()
