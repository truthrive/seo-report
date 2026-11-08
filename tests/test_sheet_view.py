"""Sheet dự án là nơi xem: tool ghi tab KPI, tab từng bộ, tab Dữ liệu check; từ khóa cam kết lấy từ tool."""
import unittest
from datetime import date
from types import SimpleNamespace

from seo_report import db
from seo_report import kpi as KP
from seo_report import okr as O
from seo_report import rank as R
from seo_report import sheet_view as SV
from seo_report.config import RankSettings
from tests.test_rank import END, SITE, TUE, FakeDataForSEO, run


class _Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeSheets:
    """Đủ cho publish(): danh sách tab, thêm / đổi tên / xóa tab, xóa và ghi ô."""

    def __init__(self, tabs):
        self.tabs = {gid: {"title": t, "values": [], "protected": []} for gid, t in tabs.items()}
        self.next = 900

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, fields=None, range=None):
        if range:  # values().get: các ô của một tab
            return _Call(lambda: {"values": self.tabs[self.by_title(range.split("!")[0].strip("'"))]["values"]})
        return _Call(lambda: {"sheets": [{"properties": {"sheetId": g, "title": t["title"]},
                                          "protectedRanges": t["protected"]} for g, t in self.tabs.items()]})

    def by_title(self, title):
        return next(g for g, t in self.tabs.items() if t["title"] == title)

    def batchUpdate(self, spreadsheetId, body):
        def go():
            if "data" in body:  # values().batchUpdate
                for d in body["data"]:
                    self.tabs[self.by_title(d["range"].split("!")[0].strip("'"))]["values"] = d["values"]
                return {}
            replies = []
            for r in body["requests"]:
                if "addSheet" in r:
                    self.next += 1
                    self.tabs[self.next] = {"title": r["addSheet"]["properties"]["title"], "values": [],
                                            "protected": []}
                    replies.append({"addSheet": {"properties": {"sheetId": self.next,
                                                                "title": self.tabs[self.next]["title"]}}})
                elif "updateSheetProperties" in r and "title" in r["updateSheetProperties"]["properties"]:
                    p = r["updateSheetProperties"]["properties"]
                    self.tabs[p["sheetId"]]["title"] = p["title"]
                    replies.append({})
                elif "deleteSheet" in r:
                    self.tabs.pop(r["deleteSheet"]["sheetId"])
                    replies.append({})
                elif "addProtectedRange" in r:
                    pr = r["addProtectedRange"]["protectedRange"]
                    self.tabs[pr["range"]["sheetId"]]["protected"].append({"description": pr["description"]})
                    replies.append({})
                else:
                    replies.append({})
            return {"replies": replies}
        return _Call(go)

    def batchClear(self, spreadsheetId, body):
        def go():
            for rng in body["ranges"]:
                self.tabs[self.by_title(rng.strip("'"))]["values"] = []
            return {}
        return _Call(go)


DATA = {"project": "x", "start": "2026-10-01", "months": [1, 2],
        "baseline": {"organic": None, "ai": None},
        "lines": [{"kind": "rank", "top": 3, "mode": "shared", "unit": "count", "targets": {"1": 1, "2": 2}}],
        "keywords": [{"keyword": "a", "url": "", "target": 3}, {"keyword": "b", "url": "", "target": None}]}


class SheetViewTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.s = RankSettings(monthly_budget_usd=20)
        self.cfg = SimpleNamespace(site_url=SITE, rank=self.s)
        KP.ensure_tables(self.con)
        KP.set_sheet(self.con, "https://docs.google.com/spreadsheets/d/" + "x" * 30 + "/edit")
        KP.save(self.con, DATA, date(2026, 10, 1))

    def test_keywords_come_from_tool_sets(self):
        # chưa có bộ Cam kết: lấy từ khóa của phiên bản cũ (đọc từ sheet trước đây) tạo bộ
        KP.snapshot_keywords(self.con, SITE, date(2026, 10, 5))
        k = R.kpi_set(self.con, SITE)
        self.assertEqual(sorted(x["keyword"] for x in R.keywords(self.con, SITE, END, k["id"])), ["a", "b"])
        R.add_keywords(self.con, SITE, self.s, END, [("c", None, 5)], "t", set_id=k["id"])
        draft = R.create_set(self.con, SITE, "Nháp", "t", kind="kpi", state="draft")
        R.add_keywords(self.con, SITE, self.s, END, [("d", None)], "t", set_id=draft)  # bộ Nháp chưa tính
        self.assertTrue(KP.snapshot_keywords(self.con, SITE, date(2026, 10, 6)))
        cur = KP.versions(self.con)[-1]["data"]
        self.assertEqual([x["keyword"] for x in cur["keywords"]], ["a", "b", "c"])
        self.assertEqual(cur["lines"], DATA["lines"])  # dòng cam kết giữ nguyên
        self.assertFalse(KP.snapshot_keywords(self.con, SITE, date(2026, 10, 7)))  # không đổi: không lưu

    def test_line_can_score_one_set(self):
        KP.snapshot_keywords(self.con, SITE, date(2026, 10, 5))
        other = R.create_set(self.con, SITE, "Cam kết 2", "t", kind="kpi")
        R.add_keywords(self.con, SITE, self.s, END, [("z", None)], "t", set_id=other)
        KP.snapshot_keywords(self.con, SITE, date(2026, 10, 6))
        items = [{"keyword": "a", "set": 1, "target": 3}, {"keyword": "z", "set": other, "target": None}]
        line = {"kind": "rank", "top": 3, "mode": "shared", "set": other}
        self.assertEqual([x["keyword"] for x in KP.rank_pool(line, items)], ["z"])
        self.assertEqual(KP.line_id(line), f"top3@{other}")

    def test_publish_writes_tabs_reuses_old_keyword_tab_and_drops_deleted_set(self):
        KP.snapshot_keywords(self.con, SITE, date(2026, 10, 5))
        k = R.kpi_set(self.con, SITE)
        blog = R.create_set(self.con, SITE, "Blog", "t")
        R.add_keywords(self.con, SITE, self.s, END, [("e", None)], "t", set_id=blog)
        run(self.con, self.s, FakeDataForSEO({"a": [("vidushop.com", SITE)]}), TUE)
        sid = KP.sheet_id(self.con)
        KP.set_tab_id(self.con, sid, KP.KPI_TAB, 1)
        KP.set_tab_id(self.con, sid, KP.KW_TAB, 2)
        sh = FakeSheets({1: "2. KPI SEO 12 tháng", 2: "Từ khóa (khách đổi tên)", 3: "OKRs 3 tháng"})
        info = SV.publish(self.con, self.cfg, today=date(2026, 10, 10), sh=sh)
        titles = {g: t["title"] for g, t in sh.tabs.items()}
        self.assertEqual(titles[1], "2. KPI SEO 12 tháng")  # tab KPI khách tự làm: không đụng
        self.assertEqual(sh.tabs[1]["values"], [])
        self.assertIn(KP.KPI_TAB, titles.values())  # tool ghi tab KPI riêng
        self.assertEqual(titles[2], "Bộ – Cam kết")  # tab từ khóa cũ thành tab của bộ Cam kết
        self.assertEqual(titles[3], "OKRs 3 tháng")  # tab khác của khách không đụng
        self.assertIn("Bộ – Blog", titles.values())
        self.assertIn(SV.DATA_TAB, titles.values())
        cam = sh.tabs[2]["values"]
        self.assertEqual(cam[3][:3], ["Từ khóa", "URL mục tiêu", "Top mục tiêu"])
        row_a = next(r for r in cam if r and r[0] == "a")
        self.assertEqual(row_a[5], 1)  # hạng mới nhất
        data = sh.tabs[sh.by_title(SV.DATA_TAB)]["values"]
        self.assertEqual(info["rows"], len(data) - 2)
        self.assertTrue(all(t["protected"] for t in sh.tabs.values() if t["title"] not in ("OKRs 3 tháng",
                                                                                            "2. KPI SEO 12 tháng")))
        R.delete_set(self.con, blog, "t")  # xóa bộ: tab của bộ và các dòng dữ liệu của bộ cũng đi
        SV.publish(self.con, self.cfg, today=date(2026, 10, 10), sh=sh)
        self.assertNotIn("Bộ – Blog", [t["title"] for t in sh.tabs.values()])
        data = sh.tabs[sh.by_title(SV.DATA_TAB)]["values"]
        self.assertFalse(any(r[1:2] == ["Blog"] for r in data))
        self.assertEqual(len([t for t in sh.tabs.values() if t["protected"]]), 4)  # Thông tin, KPI, Cam kết, Dữ liệu
        info = sh.tabs[sh.by_title(SV.INFO_TAB)]["values"]
        self.assertIn(["Tab", "Ai sửa", "Ghi chú"], info)
        self.assertIsNotNone(k)


if __name__ == "__main__":
    unittest.main()


class OkrTabsTest(unittest.TestCase):
    """OKR sửa trên tool: mỗi đợt một tab OKRs do tool ghi; tab OKR cũ của team và tab Weekly không bị ghi đè."""

    def setUp(self):
        self.con = db.connect(":memory:")
        self.cfg = SimpleNamespace(site_url=SITE, rank=RankSettings(monthly_budget_usd=20),
                                   okr=SimpleNamespace(weekly_tab="Weekly Task Tracker"))
        KP.ensure_tables(self.con)
        KP.set_sheet(self.con, "https://docs.google.com/spreadsheets/d/" + "y" * 30 + "/edit")
        O.ensure_tables(self.con)
        O.take_over(self.con)
        O.add_cycle(self.con, "Q4/2026", "2026-10-01", "2026-12-31")
        o = O.add_objective(self.con, "Q4/2026", "Nền tảng")
        O.add_item(self.con, o, "Audit kỹ thuật", pic="Thịnh")

    def test_okr_tabs_follow_cycles(self):
        sh = FakeSheets({1: "OKRs 3 tháng", 2: "Weekly Task Tracker", 3: "Content"})
        team_okr, weekly = ["ID", "team tự thiết kế"], [["Tuần"], ["Ngày", "Task tuần / hành động"]]
        sh.tabs[1]["values"], sh.tabs[2]["values"] = [team_okr], weekly
        SV.publish(self.con, self.cfg, today=date(2026, 11, 7), sh=sh)
        gid = sh.by_title("OKRs Q4-2026")
        rows = sh.tabs[gid]["values"]
        self.assertEqual(rows[3], O.SHEET_HEAD)
        self.assertEqual(rows[5][:3], ["O1.01", "", "Audit kỹ thuật"])
        self.assertEqual(sh.tabs[1]["values"], [team_okr])  # tab OKR cũ của team: không đụng
        self.assertEqual(sh.tabs[2]["values"], weekly)  # tab Weekly: chỉ khóa hàng tiêu đề
        self.assertEqual([p["description"] for p in sh.tabs[2]["protected"]], [SV.HEADER_TAG])
        self.assertEqual(sh.tabs[3]["protected"], [])
        O.update_cycle(self.con, "Q4/2026", "OKRs Q4 2026", "2026-10-01", "2026-12-31")
        SV.publish(self.con, self.cfg, today=date(2026, 11, 7), sh=sh)
        self.assertEqual(sh.tabs[gid]["title"], "OKRs Q4 2026")  # đổi tên đợt: cùng tab, đổi tên tab
        SV.publish(self.con, self.cfg, today=date(2026, 11, 7), sh=sh)
        self.assertEqual(len(sh.tabs[2]["protected"]), 1)  # khóa hàng tiêu đề một lần
        O.delete_cycle(self.con, "OKRs Q4 2026")
        SV.publish(self.con, self.cfg, today=date(2026, 11, 7), sh=sh)
        self.assertNotIn(gid, sh.tabs)

    def test_fingerprint_changes_when_okr_changes(self):
        before = SV.fingerprint(self.con, SITE)
        O.update_item(self.con, "O1.01", status=O.DOING)
        self.assertNotEqual(before, SV.fingerprint(self.con, SITE))
