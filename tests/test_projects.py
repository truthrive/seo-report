"""Nhiều dự án (website): dự án đầu tạo từ config.toml, mỗi dự án một file dữ liệu riêng, cấu hình riêng."""
import shutil
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from seo_report import db
from seo_report import projects as PJ
from seo_report import urls as U
from seo_report.config import Config, KeywordSettings
from seo_report.okr import OkrSettings

SITE = "https://matkinhtamduc.com/"


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base = Config(site_url=SITE, db_path=self.tmp / "seo.db", client_secret=Path("x"), token_path=Path("y"),
                           ga4_property="properties/1", keywords=KeywordSettings(brand_terms=("tâm đức",)),
                           okr=OkrSettings(sheet="okr-sheet"))
        self.con = db.connect(self.base.db_path)
        PJ.ensure(self.con, self.base)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_project_from_config_uses_existing_file(self):
        ps = PJ.list_projects(self.con)
        self.assertEqual(len(ps), 1)
        p = ps[0]
        self.assertEqual((p["site_url"], p["ga4_property"], p["db_file"]), (SITE, "properties/1", "seo.db"))
        cfg = PJ.config_for(self.base, p)
        self.assertEqual(cfg.db_path, self.base.db_path)
        self.assertEqual(cfg.keywords.brand_terms, ("tâm đức",))
        self.assertEqual(cfg.okr.sheet, "okr-sheet")
        PJ.ensure(self.con, self.base)  # chạy lại không tạo thêm
        self.assertEqual(len(PJ.list_projects(self.con)), 1)

    def test_new_project_has_own_file_and_settings(self):
        p = PJ.create(self.con, self.base, {"name": "Khách A", "site_url": "sc-domain:khach-a.vn",
                                            "ga4_property": "987", "brand_terms": "khách a, khacha",
                                            "rank_budget_usd": "15"}, "t")
        self.assertEqual(p["slug"], "khach-a-vn")
        cfg = PJ.config_for(self.base, p)
        self.assertEqual(cfg.db_path, self.tmp / "projects" / "khach-a-vn.db")
        self.assertTrue(cfg.db_path.exists())
        self.assertEqual(cfg.ga4_property, "properties/987")
        self.assertEqual(cfg.keywords.brand_terms, ("khách a", "khacha"))
        self.assertEqual(cfg.rank.monthly_budget_usd, 15.0)
        self.assertEqual(cfg.okr.sheet, "")  # không thừa hưởng sheet OKR của dự án khác
        with closing(db.connect(cfg.db_path)) as c:  # đủ bảng để các màn mở được khi chưa có số liệu
            names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for t in ("gsc_page_daily", "rank_keywords", "kpi_versions", "okr_items", "report_notes", "url_targets"):
            self.assertIn(t, names)

    def test_data_isolated_between_projects(self):
        p = PJ.create(self.con, self.base, {"name": "B", "site_url": "https://b.vn"}, "t")
        db.replace_day(self.con, SITE, "2026-10-01", [{"keys": [SITE], "clicks": 5, "impressions": 9,
                                                     "position": 1}], [])
        with closing(db.connect(PJ.config_for(self.base, p).db_path)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM gsc_page_daily").fetchone()[0], 0)

    def test_domain(self):  # property dạng sc-domain hay URL đều ra cùng tên miền (dùng để so URL check rank / index)
        self.assertEqual(PJ.domain("sc-domain:abc.vn"), "abc.vn")
        self.assertEqual(PJ.domain("https://www.ABC.vn/"), "abc.vn")
        self.assertEqual(PJ.domain("https://abc.vn/gong-kinh/x/"), "abc.vn")

    def test_validation(self):
        with self.assertRaises(ValueError):
            PJ.create(self.con, self.base, {"name": "", "site_url": "sc-domain:x.vn"}, "t")
        with self.assertRaises(ValueError):
            PJ.create(self.con, self.base, {"name": "X", "site_url": "x"}, "t")
        with self.assertRaises(ValueError):  # property đã có dự án
            PJ.create(self.con, self.base, {"name": "Trùng", "site_url": SITE}, "t")
        p = PJ.create(self.con, self.base, {"name": "B", "site_url": "https://b.vn"}, "t")
        self.assertEqual(p["site_url"], "https://b.vn/")  # tự thêm / cuối như GSC ghi

    def test_archive_and_restore(self):
        first = PJ.list_projects(self.con)[0]
        with self.assertRaises(ValueError):  # phải còn ít nhất một dự án
            PJ.archive(self.con, first["slug"], "t")
        p = PJ.create(self.con, self.base, {"name": "B", "site_url": "sc-domain:b.vn"}, "t")
        PJ.archive(self.con, p["slug"], "t")
        self.assertEqual([x["slug"] for x in PJ.list_projects(self.con)], [first["slug"]])
        self.assertEqual(PJ.get(self.con, p["slug"])["slug"], first["slug"])  # dự án lưu trữ không mở được
        self.assertTrue(PJ.config_for(self.base, p).db_path.exists())  # dữ liệu giữ nguyên
        PJ.restore(self.con, p["slug"], "t")
        self.assertEqual(len(PJ.list_projects(self.con)), 2)
        p2 = PJ.create(self.con, self.base, {"name": "B2", "site_url": "https://www.b.vn/"}, "t")
        self.assertEqual(p2["slug"], "b-vn-2")  # cùng tên miền: slug không trùng

    def test_update(self):
        p = PJ.create(self.con, self.base, {"name": "B", "site_url": "sc-domain:b.vn"}, "t")
        p = PJ.update(self.con, p["slug"], {"name": "Khách B", "site_url": "sc-domain:b.vn", "rank_budget_usd": 0},
                      "t")
        self.assertEqual((p["name"], p["settings"]["rank_budget_usd"]), ("Khách B", 0.0))
        with self.assertRaises(ValueError):
            PJ.update(self.con, p["slug"], {"name": "B", "site_url": SITE}, "t")

    def test_url_rules_only_for_own_site(self):
        self.assertEqual(U.classify_by_rules("https://khach.vn/gong-kinh/abc/")[0], None)  # đọc schema
        self.assertEqual(U.classify_by_rules("https://khach.vn/blog/bai-viet/")[0], None)
        self.assertEqual(U.classify_by_rules("https://khach.vn/lien-he/")[0], U.INFO)
        self.assertEqual(U.classify_by_rules("https://khach.vn/")[0], U.HOME)
        self.assertEqual(U.classify_by_rules("https://khach.vn/2021/09/29/x/")[0], U.LEGACY)
        self.assertEqual(U.classify_by_rules(SITE + "gong-kinh/abc/")[0], U.BRAND)


if __name__ == "__main__":
    unittest.main()
