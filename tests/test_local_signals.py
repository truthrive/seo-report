import sqlite3
import unittest
from datetime import date
from types import SimpleNamespace

from seo_report import ai_writer as AW
from seo_report import gbp as G
from seo_report import gbp_reviews as GR
from seo_report import local_signals as LS

SITE = "https://x.vn/"


def setup_db():
    con = sqlite3.connect(":memory:")
    G.ensure_tables(con)
    GR.ensure_tables(con)
    for n, t in (("L1", "Mắt Kính Tâm Đức - Gò Vấp"), ("L2", "Mắt Kính Tâm Đức - Quận 1")):
        con.execute("INSERT INTO gbp_locations (name, account, title, data, linked, added_by, added_at, fetched_at) "
                    "VALUES (?, 'a', ?, '{}', 1, 'x', 'x', 'x')", (n, t))
    con.execute("CREATE TABLE rank_keywords (site TEXT, keyword TEXT, removed_at TEXT)")
    con.execute("INSERT INTO rank_keywords VALUES (?, 'kính cận', NULL)", (SITE,))
    for loc in ("L1", "L2"):
        for m in ("2026-09", "2026-10"):
            con.execute("INSERT INTO gbp_months VALUES (?, ?, 'x')", (loc, m))
    rows = [("2026-10", "mắt kính", 800), ("2026-10", "kính cận", 500), ("2026-10", "tâm đức", 300),
            ("2026-10", "quận 11", 400), ("2026-10", "kính râm nam", 150), ("2026-09", "tâm đức", 900)]
    for m, k, v in rows:
        con.execute("INSERT INTO gbp_keywords VALUES ('L1', ?, ?, ?, NULL)", (m, k, v))
    return con


class LocalSignalsTest(unittest.TestCase):
    def test_fold_and_brand(self):
        self.assertEqual(LS.fold("Tâm Đức"), LS.fold("tam duc"))
        con = setup_db()
        self.assertEqual(LS.brand_tokens(con, SITE, G.linked(con)), ["tamduc"])

    def test_untracked_keywords_skip_brand_place_tracked(self):
        con = setup_db()
        s = LS.untracked_keywords(con, SITE, ["L1", "L2"], ["tamduc"])
        self.assertEqual(s[0:2], ("Local SEO", "low"))
        self.assertIn("“mắt kính” 800 lượt", s[2])
        self.assertIn("kính râm nam", s[2])
        for x in ("kính cận", "tâm đức", "quận 11"):  # đã theo dõi / tên thương hiệu / địa điểm
            self.assertNotIn(x, s[2])

    def test_brand_drop_needs_both_sources(self):
        con = setup_db()
        self.assertIsNone(LS.brand_drop(con, SITE, ["L1", "L2"], ["tamduc"]))  # chưa có số Search Console

    def test_web_vs_organic(self):
        con = setup_db()
        for d, v in (("2026-11-01", 50), ("2026-11-08", 80)):
            con.execute("INSERT INTO gbp_daily VALUES ('L1', ?, 'WEBSITE_CLICKS', ?)", (d, v))
        for d in ("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09"):
            con.execute("INSERT INTO gbp_daily VALUES ('L1', ?, 'BUSINESS_IMPRESSIONS_MOBILE_MAPS', 100)", (d,))
        cur, prev = (date(2026, 11, 8), date(2026, 11, 8)), (date(2026, 11, 1), date(2026, 11, 1))
        s = LS.web_vs_organic(con, ["L1"], cur, prev, {"sessions": 90, "prev": 100})
        self.assertIn("50 → 80 (+60%)", s[2])
        self.assertIsNone(LS.web_vs_organic(con, ["L1"], cur, prev, None))

    def test_report_lines_and_prompt(self):
        con = setup_db()
        con.execute("INSERT INTO gbp_reviews VALUES ('L1', 'r1', 'A', 2, 'tệ', '2026-11-10T00:00:00Z', 'x', NULL, "
                    "NULL, 'x')")
        rep = SimpleNamespace(week=(date(2026, 11, 9), date(2026, 11, 15)),
                              prev_week=(date(2026, 11, 2), date(2026, 11, 8)), organic=None)
        lines = LS.report_lines(con, SITE, rep)
        self.assertTrue(any(x.startswith("Đánh giá Google Maps trong kỳ: 1 mới") for x in lines))
        self.assertIn("chưa trả lời: 1", "\n".join(lines))
        rep2 = SimpleNamespace(kind="week")
        orig = AW.report_facts
        try:
            AW.report_facts = lambda r: "Chỉ số SEO: ..."
            p = AW.report_prompt(rep2, "\n".join(lines))
        finally:
            AW.report_facts = orig
        self.assertIn("Đánh giá Google Maps trong kỳ", p)
        self.assertIn("1 gạch đầu dòng nói về Maps", p)


if __name__ == "__main__":
    unittest.main()
