"""Checklist Technical Audit: trạng thái tiêu chí (Đạt / Chưa kiểm / Không áp dụng / lỗi), việc làm trước, so với lần
quét trước, "Cố ý, bỏ qua", chưa mở được ≠ lỗi, file Excel dạng checklist."""
import io
import json
import unittest
from datetime import timedelta
from types import SimpleNamespace

from openpyxl import load_workbook

from seo_report import audit_checklist as AC
from seo_report import db
from seo_report import site_audit as SA
from seo_report.config import KeywordSettings
from tests.test_opportunities import END, SITE, Gsc
from tests.test_site_audit import page
from tests.test_site_checks import fake_web


def ck(code, level, urls, unit="trang", site=False):
    return {"code": code, "level": level, "name": code, "fix": "sửa", "unit": unit, "site": site, "ignored": [],
            "pages": [{"url": u, "url_id": i, "detail": "", "now": "", "want": ""} for i, u in urls]}


class BuildTest(unittest.TestCase):
    def rows(self, au, sc=None, meta=None):
        meta = {"pages": 10, "fmt": True, "schema": True, "products": 0, "merchant": False, **(meta or {})}
        return {(r["code"], r["name"]): r for a in AC.build(au, sc, meta) for r in a["rows"]}

    def test_statuses(self):
        au = {"checks": [ck("noindex", "high", [(1, "https://x.vn/a")]), ck("noalt", "info", [(2, "https://x.vn/b")])]}
        r = self.rows(au, sc={"robots": {"groups": []}, "host": [{"url": "x"}], "links": {}, "bots": [],
                              "safe": {"error": "chưa có Google API key"}, "sitemap": {"urls": 0}})
        self.assertEqual(r[("INDEX-001", "Trang có traffic cho phép index")]["status"], "high")
        self.assertEqual(r[("MEDIA-001", "Ảnh có mô tả (alt)")]["status"], "info")
        self.assertEqual(r[("ACC-003", "robots.txt không chặn trang quan trọng")]["status"], "ok")
        safe = r[("ACC-009", "Google Safe Browsing không cảnh báo")]
        self.assertEqual(safe["status"], "unknown")
        self.assertIn("API key", safe["why"])
        self.assertEqual(r[("DISC-002", "Sitemap chỉ chứa URL 200, cho phép index")]["status"], "unknown")
        self.assertEqual(r[("", "Sản phẩm có sao đánh giá")]["status"], "na")  # không có trang sản phẩm
        tot = AC.totals(AC.build(au, None, {"pages": 10, "fmt": False}))
        self.assertEqual(tot["checked"], tot["high"] + tot["medium"] + tot["info"] + tot["ok"])
        self.assertGreater(tot["unknown"], 0)  # dữ liệu mới chưa có (fmt=False): không giả là "Đạt"

    def test_priorities_by_level_then_clicks(self):
        au = {"checks": [ck("dup_title", "medium", [(1, "a"), (2, "b")]), ck("noindex", "high", [(3, "c")]),
                         ck("no_h1", "medium", [(4, "d")]), ck("noalt", "info", [(5, "e")])]}
        pr = AC.priorities(au, {4: (900, 1), 1: (10, 1), 2: (5, 1)})
        self.assertEqual([p["code"] for p in pr], ["noindex", "no_h1", "dup_title"])  # Tham khảo không vào
        self.assertEqual(pr[1]["clicks"], 900)

    def test_diff(self):
        prev = {"noindex": ["https://x.vn/a", "https://x.vn/b"], "slow": ["https://x.vn/gone"]}
        cur = {"noindex": ["https://x.vn/a"], "dup_title": ["https://x.vn/c"]}
        d = AC.diff(cur, prev, {"https://x.vn/a", "https://x.vn/b", "https://x.vn/c"})
        self.assertEqual(d["new"], [("dup_title", "https://x.vn/c")])
        # /gone không còn được quét: chưa biết đã sửa hay chưa, không tính là "đã hết"
        self.assertEqual(d["fixed"], [("noindex", "https://x.vn/b")])
        self.assertFalse(AC.diff(cur, None, set())["has_prev"])

    def test_diff_splits_first_time_pages(self):
        prev = {"noalt": ["https://x.vn/a"]}
        cur = {"noalt": ["https://x.vn/a", "https://x.vn/b", "https://x.vn/c"]}
        d = AC.diff(cur, prev, {"https://x.vn/a", "https://x.vn/b", "https://x.vn/c"}, {"https://x.vn/a", "https://x.vn/b"})
        self.assertEqual(d["new"], [("noalt", "https://x.vn/b")])  # trang đã quét lần trước: lỗi mới thật
        self.assertEqual(d["first"], [("noalt", "https://x.vn/c")])  # trang lần đầu được quét
        self.assertEqual(d["first_pages"], 1)


class IgnoreAndHistoryTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.g = Gsc(self.con)
        self.cfg = SimpleNamespace(site_url=SITE, db_path=":memory:", keywords=KeywordSettings())
        self.pages = {"/a/": page("Trang bị noindex có traffic nè",
                                  extra="<meta name='robots' content='noindex'><link rel='canonical' href='/a/'>"
                                        "<a href='/mat/'>x</a>"),
                      "/b/": page("Trang bình thường có canonical đủ",
                                  extra="<link rel='canonical' href='/b/'><meta name='viewport' content='x'>")}
        for i, path in enumerate(self.pages):
            self.g.day(END - timedelta(days=3), path, 100 - i, 1000, 8.0, None)
        self.scan(fake_web({"https://x.vn/": (200, None)}))  # /mat/ không mở được lúc kiểm

    def scan(self, web):
        def fetcher(url):
            path = url.replace(SITE.rstrip("/"), "")
            return {"status": 200, "final_url": None, "ms": 100, "html": self.pages[path], "x_robots": "",
                    "error": None, "enc": "gzip", "bytes": 3000}
        SA.run(self.con, SITE, END, "test", fetcher=fetcher, sleep=lambda s: None, log=lambda m: None, opener=web,
               text_get=lambda u: {"status": 404, "text": "", "error": None})

    def tearDown(self):
        self.con.close()

    def test_unopened_link_is_unknown_not_broken(self):
        f = SA.findings(self.con, self.cfg, END)
        codes = {c["code"] for c in f["checks"]}
        self.assertNotIn("link_broken", codes)
        self.assertEqual(f["meta"]["unknown"]["links"], 1)
        self.assertTrue(f["meta"]["fmt"])

    def test_ignore_and_history(self):
        f = SA.findings(self.con, self.cfg, END)
        self.assertIn("noindex", {c["code"] for c in f["checks"]})
        SA.set_ignored(self.con, "noindex", [SITE + "a/"], True, "test")
        f2 = SA.findings(self.con, self.cfg, END)
        self.assertNotIn("noindex", {c["code"] for c in f2["checks"]})
        self.assertEqual([c["code"] for c in f2["ignored_checks"]], ["noindex"])
        row = {r["code"]: r for a in AC.build(f2, None, f2["meta"]) for r in a["rows"]}["INDEX-001"]
        self.assertEqual(row["status"], "ok")  # đã bỏ qua có chủ ý: tiêu chí đạt, vẫn xem lại được
        SA.set_ignored(self.con, "noindex", [SITE + "a/"], False, "test")
        self.assertIn("noindex", {c["code"] for c in SA.findings(self.con, self.cfg, END)["checks"]})
        # lịch sử: lần quét đầu chưa có lần trước để so; lần sau thì có
        self.assertEqual(SA.findings_history(self.con, f), (None, None))
        self.scan(fake_web({"https://x.vn/": (200, None)}))
        f3 = SA.findings(self.con, self.cfg, END)
        prev, at = SA.findings_history(self.con, f3)
        self.assertIn("noindex", prev)
        self.assertTrue(at)

    def test_xlsx_checklist_sheet(self):
        from seo_report import web_audit as WA
        f = SA.findings(self.con, self.cfg, END)
        data = WA.audit_xlsx(f, SITE, AC.build(f, None, f["meta"]))
        wb = load_workbook(io.BytesIO(data))
        self.assertEqual(wb.sheetnames[0], "Checklist")
        ws = wb["Checklist"]
        head = [c.value for c in ws[1]]
        self.assertEqual(head[:4], ["Hạng mục", "Mã", "Tiêu chí", "Trạng thái"])
        statuses = {r[3] for r in ws.iter_rows(min_row=2, values_only=True)}
        self.assertIn("Cần sửa", statuses)
        self.assertIn("Đạt", statuses)
        json.dumps(f["meta"])  # meta ghi được ra JSON


if __name__ == "__main__":
    unittest.main()
