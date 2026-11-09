import sqlite3
import unittest
from types import SimpleNamespace

from seo_report import ai_writer as AW
from seo_report import web_ai_library as L

PROV = {"name": "x", "model": "m"}


class LibraryTest(unittest.TestCase):
    def test_rows_latest_per_ref_and_titles(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE rank_keywords (id INTEGER PRIMARY KEY, keyword TEXT)")
        con.execute("INSERT INTO rank_keywords VALUES (7, 'kính rayban')")
        cfg = SimpleNamespace(site_url="https://a.vn/")
        AW.save(con, cfg.site_url, "kw_strategy", "h1", {"title": "cũ", "pillars": []}, PROV, "u")
        AW.save(con, cfg.site_url, "kw_strategy", "h1", {"title": "gọng kính + 9 từ khóa", "summary": "S",
                                                          "pillars": []}, PROV, "u")
        AW.save(con, cfg.site_url, "aio_answer", "7", {"answer": "A"}, PROV, "u")
        AW.save(con, cfg.site_url, "report_note", "2026-10-26", {"note": "- Tuần tốt.\n- B"}, PROV, "u")
        AW.save(con, cfg.site_url, "report_note", "month:2026-10-01", {"note": "x"}, PROV, "u")
        AW.save(con, "https://khac.vn/", "kw_brief", "k", {"keyword": "x"}, PROV, "u")  # website khác: không hiện
        rows = {(r["kind"], r["ref"]): r for r in L._rows(con, cfg)}
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[("kw_strategy", "h1")]["title"], "gọng kính + 9 từ khóa")
        self.assertEqual(rows[("aio_answer", "7")]["title"], "kính rayban")
        self.assertEqual(rows[("report_note", "2026-10-26")]["title"], "Báo cáo tuần 26/10/2026")
        self.assertEqual(rows[("report_note", "2026-10-26")]["snippet"], "Tuần tốt.")
        self.assertEqual(rows[("report_note", "month:2026-10-01")]["title"], "Báo cáo tháng 10/2026")
        self.assertEqual(L.delete(con, cfg.site_url, "kw_strategy", "h1"), 2)  # xóa mọi lần viết của bản đó
        self.assertNotIn(("kw_strategy", "h1"), {(r["kind"], r["ref"]) for r in L._rows(con, cfg)})
        self.assertEqual(L.delete(con, cfg.site_url, "kw_strategy", "h1"), 0)


if __name__ == "__main__":
    unittest.main()
