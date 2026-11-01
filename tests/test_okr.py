import sqlite3
import unittest
from datetime import date
from types import SimpleNamespace

from seo_report import okr as O
from seo_report.report import okr_block

TODAY = date(2026, 10, 30)
OKR_ROWS = [
    ["OKRs 3 tháng"],
    ["ID", "Nhóm", "Hạng mục công việc", "Start date", "End date", "PIC", "Trạng thái", "% Tiến độ"],
    ["O1", "", "Audit", "", "", "", "", ""],
    ["O1.01", "Tech", "Audit technical", "08/10/2026", "21/10/2026", "A", "Hoàn thành", "100%"],
    ["O1.02", "Tech", "Audit logfile", "13/10/2026", "28/10/2026", "A", "Đang làm", 0.5],
    ["O1.03", "Tech", "Audit backlink", "26/10/2026", "01/11/2026", "B", "Chưa bắt đầu", ""],
    ["", "", "dòng trống", "", "", "", "", ""],
    ["O2", "", "Content", "", "", "", "", ""],
    ["O2.01", "Content", "Outline", "02/11/2026", "06/11/2026", "B", "", ""],
]
WEEKLY_ROWS = [
    ["Ngày", "Loại task", "Mã OKR", "Task tuần / hành động", "PIC", "Deadline", "Trạng thái"],
    ["Thứ Hai, 26 /10", "OKR", "O1.02", "Đọc log", "A", "28/10/2026", "Đang làm"],
    ["", "OKR", "O1.03", "Lấy backlink", "B", "", "Chưa bắt đầu"],
    ["", "", "", "", "", "", ""],
    ["Thứ Hai, 19 thg 10,26", "OKR", "O1.01", "Crawl", "A", "", "Hoàn thành"],
]


class ParseTest(unittest.TestCase):
    def test_parse_date_variants(self):
        self.assertEqual(O.parse_date(46315, TODAY), date(2026, 10, 20))  # serial của Sheets
        self.assertEqual(O.parse_date("13/10/2026", TODAY), date(2026, 10, 13))
        self.assertEqual(O.parse_date("Thứ Ba, 13 /10", TODAY), date(2026, 10, 13))
        self.assertEqual(O.parse_date("Thứ Hai, 12 thg 10,26", TODAY), date(2026, 10, 12))
        # Thiếu năm: lấy năm gần hôm nay nhất (đầu tháng 1 năm sau, không phải tháng 1 năm nay)
        self.assertEqual(O.parse_date("05/01", TODAY), date(2027, 1, 5))
        self.assertIsNone(O.parse_date("", TODAY))
        self.assertIsNone(O.parse_date("31/02/2026", TODAY))

    def test_status_and_pct(self):
        self.assertEqual(O.norm_status("XONG"), O.DONE)
        self.assertEqual(O.norm_status("Đang làm"), O.DOING)
        self.assertEqual(O.norm_status(""), O.TODO)
        self.assertEqual(O._pct("100%"), 100)
        self.assertEqual(O._pct(0.5), 50)

    def test_parse_okr(self):
        items = O.parse_okr(OKR_ROWS, TODAY)
        self.assertEqual([i["code"] for i in items], ["O1", "O1.01", "O1.02", "O1.03", "O2", "O2.01"])
        o102 = items[2]
        self.assertEqual((o102["objective"], o102["status"], o102["progress"]), ("O1", O.DOING, 50))
        self.assertEqual(items[5]["objective"], "O2")
        self.assertTrue(items[0]["is_objective"])

    def test_parse_weekly_fills_week_and_skips_empty(self):
        tasks = O.parse_weekly(WEEKLY_ROWS, TODAY)
        self.assertEqual([t["task"] for t in tasks], ["Đọc log", "Lấy backlink", "Crawl"])
        self.assertEqual([t["week"] for t in tasks], ["2026-10-26", "2026-10-26", "2026-10-19"])


class OverviewTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.items = O.parse_okr(OKR_ROWS, TODAY)
        self.tasks = O.parse_weekly(WEEKLY_ROWS, TODAY)

    def tearDown(self):
        self.con.close()

    def test_counts_late_and_period(self):
        O.save(self.con, self.items, self.tasks, TODAY, "api")
        ov = O.overview(self.con, TODAY, (date(2026, 10, 26), date(2026, 11, 1)))
        self.assertEqual(ov["total"], 4)
        self.assertEqual(ov["counts"][O.DONE], 1)
        self.assertEqual([i["code"] for i in ov["late"]], ["O1.02"])  # hạn 28/10, chưa xong
        p = ov["period"]
        self.assertEqual([i["code"] for i in p["due"]], ["O1.02", "O1.03"])
        self.assertEqual([i["code"] for i in p["next"]], ["O2.01"])
        # O1.01 xong từ trước lần đồng bộ đầu, hạn 21/10 không nằm trong tuần: không tính là xong trong tuần
        self.assertEqual(p["done"], [])
        o1 = ov["objectives"][0]
        self.assertEqual((o1["total"], o1["done"], o1["late"]), (3, 1, 1))

    def test_done_date_from_snapshots(self):
        O.save(self.con, self.items, self.tasks, date(2026, 10, 20), "api")
        changed = [dict(i, status=O.DONE) if i["code"] == "O1.03" else i for i in self.items]
        O.save(self.con, changed, self.tasks, date(2026, 10, 27), "api")
        week = (date(2026, 10, 26), date(2026, 11, 1))
        done = O.overview(self.con, TODAY, week)["period"]["done"]
        self.assertEqual([i["code"] for i in done], ["O1.03"])  # chuyển sang Hoàn thành ngày 27/10
        prev = O.overview(self.con, TODAY, (date(2026, 10, 19), date(2026, 10, 25)))["period"]["done"]
        # O1.01 thấy xong ngay lần đồng bộ đầu: không biết ngày xong, tính theo hạn 21/10 (trong tuần 19–25/10)
        self.assertEqual([i["code"] for i in prev], ["O1.01"])

    def test_okr_block(self):
        cfg = SimpleNamespace(okr=O.OkrSettings(sheet=""))
        self.assertIsNone(okr_block(self.con, cfg, (date(2026, 10, 26), date(2026, 11, 1)), TODAY))
        cfg = SimpleNamespace(okr=O.OkrSettings(sheet="https://docs.google.com/spreadsheets/d/abc123/edit"))
        self.assertIsNone(okr_block(self.con, cfg, (date(2026, 10, 26), date(2026, 11, 1)), TODAY))  # chưa đồng bộ
        O.save(self.con, self.items, self.tasks, TODAY, "api")
        k = okr_block(self.con, cfg, (date(2026, 10, 1), date(2026, 10, 31)), TODAY)
        self.assertEqual(len(k["tasks"]), 3)  # task của các tuần bắt đầu trong tháng 10
        self.assertIn("synced", k)


class CycleTest(unittest.TestCase):
    """Nhiều đợt OKR: mỗi tab "OKRs …" là một đợt; mã trùng giữa hai đợt vẫn tách riêng."""

    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        q1 = O.parse_okr(OKR_ROWS, TODAY)  # đợt 1: 08/10 → 06/11
        rows2 = [OKR_ROWS[1], ["O1", "", "Đợt 2", "", "", "", "", ""],
                 ["O1.01", "Tech", "Việc đợt 2", "10/11/2026", "20/12/2026", "A", "Đang làm", ""]]
        q2 = O.parse_okr(rows2, TODAY)
        self.items = O.combine([("OKRs 3 tháng", q1), ("OKRs Q1-2027", q2)])
        O.save(self.con, self.items, [], TODAY, "api")

    def tearDown(self):
        self.con.close()

    def test_duplicate_codes_get_cycle_prefix(self):
        uids = [i["uid"] for i in self.items]
        self.assertIn("OKRs 3 tháng|O1.01", uids)
        self.assertIn("OKRs Q1-2027|O1.01", uids)
        self.assertIn("O2.01", uids)  # mã không trùng giữ nguyên
        kid = next(i for i in self.items if i["uid"] == "OKRs Q1-2027|O1.01")
        self.assertEqual(kid["objective"], "OKRs Q1-2027|O1")

    def test_overview_picks_cycle_by_date(self):
        ov = O.overview(self.con, TODAY)  # 30/10: đang ở đợt 1
        self.assertEqual(ov["cycle"], "OKRs 3 tháng")
        self.assertEqual(ov["total"], 4)
        later = O.overview(self.con, date(2026, 12, 1))
        self.assertEqual((later["cycle"], later["total"]), ("OKRs Q1-2027", 1))
        self.assertEqual(later["objectives"][0]["total"], 1)
        pick = O.overview(self.con, TODAY, cycle="OKRs Q1-2027")
        self.assertEqual(pick["cycle"], "OKRs Q1-2027")
        self.assertEqual([c["name"] for c in pick["cycles"]], ["OKRs 3 tháng", "OKRs Q1-2027"])

    def test_tab_names(self):
        from types import SimpleNamespace
        cfg = SimpleNamespace(okr=O.OkrSettings())
        titles = ["OKRs 3 tháng", "Đề xuất chi phí", " Weekly Task Tracker", "OKRs Q1-2027", "Content"]
        self.assertEqual(O.okr_tab_names(titles, cfg), ["OKRs 3 tháng", "OKRs Q1-2027"])


if __name__ == "__main__":
    unittest.main()
