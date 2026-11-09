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

SITE = "https://vidushop.com/"


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base = Config(site_url=SITE, db_path=self.tmp / "seo.db", client_secret=Path("x"), token_path=Path("y"),
                           ga4_property="properties/1", keywords=KeywordSettings(brand_terms=("ví dụ shop",)),
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
        self.assertEqual(cfg.keywords.brand_terms, ("ví dụ shop",))
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

    def test_delete_forever(self):
        from seo_report import access as A
        first = PJ.list_projects(self.con)[0]
        self.assertTrue(PJ.is_root(self.base, first))
        with self.assertRaises(ValueError):  # dự án gốc (dữ liệu chung file cấu hình tool): không xóa
            PJ.delete(self.con, self.base, first["slug"], "t")
        p = PJ.create(self.con, self.base, {"name": "B", "site_url": "sc-domain:b.vn"}, "t")
        A.set_member(self.con, "khach@b.vn", p["slug"], A.CLIENT, "t")
        path = PJ.config_for(self.base, p).db_path
        self.assertTrue(path.exists())
        moved = PJ.delete(self.con, self.base, p["slug"], "t")
        self.assertFalse(path.exists())
        self.assertTrue(moved.exists() and moved.parent.name == "da-xoa")  # bản cuối, phòng xóa nhầm
        self.assertEqual([x["slug"] for x in PJ.list_projects(self.con, archived=True)], [first["slug"]])
        self.assertEqual(A.members(self.con), {})  # quyền gắn với dự án cũng xóa
        self.assertEqual(A.log_entries(self.con)[0]["action"], "Xóa vĩnh viễn dự án")
        # tạo lại website đã xóa: được (không còn dự án lưu trữ chặn)
        self.assertEqual(PJ.create(self.con, self.base, {"name": "B", "site_url": "sc-domain:b.vn"}, "t")["slug"],
                         "b-vn")

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
        self.assertIsNone(U.classify_by_rules(SITE + "gong-kinh/abc/")[0])  # không còn quy tắc viết cứng cho site nào


if __name__ == "__main__":
    unittest.main()


class LogoTest(unittest.TestCase):
    def test_bitmap_shrunk_to_small_png(self):
        import base64
        import io

        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (512, 512), "red").save(buf, "JPEG")
        uri = PJ.data_uri(buf.getvalue(), "image/jpeg")
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        img = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
        self.assertLessEqual(max(img.size), 192)

    def test_rejects_non_image_and_too_big(self):
        with self.assertRaises(ValueError):
            PJ.data_uri(b"<html>", "text/html")
        with self.assertRaises(ValueError):
            PJ.data_uri(b"x" * (PJ.MAX_LOGO_BYTES + 1), "image/png")

    def test_icon_of(self):
        self.assertEqual(PJ.icon_of({"logo": "data:image/png;base64,AA=="}), "data:image/png;base64,AA==")
        self.assertEqual(PJ.icon_of({"logo": ""}), "")
        self.assertIsNone(PJ.logo_bytes("data:image/svg+xml;base64,PHN2Zz4="))  # Excel / slide không chèn SVG
        self.assertEqual(PJ.logo_bytes("data:image/png;base64,AAEC"), b"\x00\x01\x02")


class BudgetTest(unittest.TestCase):
    def test_last_months_and_cost_by_month(self):
        from datetime import date

        from seo_report import rank as R
        from seo_report import volume as V
        self.assertEqual(R.last_months(date(2026, 2, 10), 3), ["2025-12", "2026-01", "2026-02"])
        con = db.connect(":memory:")
        R.ensure_tables(con)
        V.ensure_tables(con)
        cols = "(task_id, keyword_id, depth, check_date, posted_at, cost, status)"
        con.execute(f"INSERT INTO rank_tasks {cols} VALUES ('t1', 1, 10, '2026-01-05', 'x', 0.01, 'done')")
        con.execute(f"INSERT INTO rank_tasks {cols} VALUES ('t2', 1, 30, '2026-02-05', 'x', 0.03, 'done')")
        con.execute("INSERT INTO volume_runs VALUES ('2026-02-01T00:00:00', 10, 0.075)")
        got = R.cost_by_month(con, ["2026-01", "2026-02"])
        self.assertEqual(got["2026-01"]["checks"], 1)
        self.assertAlmostEqual(got["2026-02"]["total"], 0.105)

    def test_spend_log_splits_by_api_and_batch(self):
        """Nhật ký chi tiền: check rank gộp theo lượt gửi (phút + người chạy), mỗi lần volume / backlink / ý định một
        dòng; chỉ tháng được hỏi; mới trước cũ sau."""
        from seo_report import backlinks as B
        from seo_report import intent as IN
        from seo_report import rank as R
        from seo_report import volume as V
        con = db.connect(":memory:")
        R.ensure_tables(con)
        V.ensure_tables(con)
        B.ensure_tables(con)
        IN.ensure_tables(con)
        sid = R.create_set(con, SITE, "Cam kết", "u")
        con.execute("INSERT INTO rank_keywords (id, site, keyword, source, added_by, added_at, set_id) "
                    "VALUES (1, ?, 'a', 'manual', 'u', 'x', ?), (2, ?, 'b', 'manual', 'u', 'x', ?)",
                    (SITE, sid, SITE, sid))
        ins = ("INSERT INTO rank_tasks (task_id, keyword_id, depth, check_date, posted_at, cost, status, by_user) "
               "VALUES (?, ?, ?, '2026-11-05', ?, ?, 'done', ?)")
        con.execute(ins, ("t1", 1, 20, "2026-11-05T07:15:02+00:00", 0.0018, "an"))
        con.execute(ins, ("t2", 2, 30, "2026-11-05T07:15:40+00:00", 0.0024, "an"))
        con.execute(ins, ("t3", 0, 20, "2026-11-04T01:00:00+00:00", 0.0018, None))  # bộ đã xóa, lịch cũ
        con.execute(ins, ("t4", 1, 20, "2026-10-30T01:00:00+00:00", 0.0018, None))  # tháng khác
        con.execute("INSERT INTO volume_runs VALUES ('2026-11-06T01:06:43+00:00', 48, 0.09)")
        con.execute("INSERT INTO backlink_runs VALUES ('2026-11-04T08:57:15+00:00', ?, 'history', 0.0244)", (SITE,))
        con.execute("INSERT INTO intent_runs VALUES ('2026-11-05T07:48:31+00:00', 69, 0.0203)")
        log = R.spend_log(con, "2026-11")
        self.assertEqual([x["kind"] for x in log], ["volume", "intent", "rank", "backlinks", "rank"])
        batch = log[2]
        self.assertEqual((batch["qty"], batch["by"]), (2, "an"))
        self.assertAlmostEqual(batch["cost"], 0.0042)
        self.assertIn("Cam kết", batch["detail"])
        self.assertIn("top 20/top 30", batch["detail"])
        self.assertIn("bộ đã xóa", log[4]["detail"])
        self.assertAlmostEqual(sum(x["cost"] for x in log), 0.0042 + 0.0018 + 0.09 + 0.0244 + 0.0203)

    def test_set_budget(self):
        tmp = Path(tempfile.mkdtemp())
        base = Config(site_url=SITE, db_path=tmp / "seo.db", client_secret=Path("x"), token_path=Path("y"))
        with closing(db.connect(base.db_path)) as con:
            PJ.ensure(con, base)
            slug = PJ.list_projects(con)[0]["slug"]
            PJ.set_budget(con, slug, 35, "t")
            self.assertEqual(PJ.config_for(base, PJ.get(con, slug)).rank.monthly_budget_usd, 35.0)
            with self.assertRaises(ValueError):
                PJ.set_budget(con, slug, -1, "t")
        shutil.rmtree(tmp, ignore_errors=True)


    def test_set_rank_target(self):
        tmp = Path(tempfile.mkdtemp())
        base = Config(site_url=SITE, db_path=tmp / "seo.db", client_secret=Path("x"), token_path=Path("y"))
        with closing(db.connect(base.db_path)) as con:
            PJ.ensure(con, base)
            slug = PJ.list_projects(con)[0]["slug"]
            self.assertEqual(PJ.config_for(base, PJ.get(con, slug)).rank.se_domain, "google.com.vn")
            PJ.set_rank_target(con, slug, {"se_domain": "google.com", "device": "desktop", "location_code": 1028581,
                                           "language_code": "vi"}, "t")
            r = PJ.config_for(base, PJ.get(con, slug)).rank
            self.assertEqual((r.se_domain, r.device, r.location_code), ("google.com", "desktop", 1028581))
            with self.assertRaises(ValueError):
                PJ.set_rank_target(con, slug, {"se_domain": "bing.com", "device": "desktop", "location_code": 2704,
                                               "language_code": "vi"}, "t")
        shutil.rmtree(tmp, ignore_errors=True)


class PauseTest(unittest.TestCase):
    def test_paused_project_sends_nothing(self):
        from datetime import date

        from seo_report import rank as R
        from seo_report import volume as V
        tmp = Path(tempfile.mkdtemp())
        base = Config(site_url=SITE, db_path=tmp / "seo.db", client_secret=Path("x"), token_path=Path("y"))
        with closing(db.connect(base.db_path)) as con:
            PJ.ensure(con, base)
            slug = PJ.list_projects(con)[0]["slug"]
            PJ.set_paused(con, slug, True, "t")
            cfg = PJ.config_for(base, PJ.get(con, slug))
            PJ.update(con, slug, {"name": "X", "site_url": SITE, "rank_paused": True}, "t")  # sửa dự án giữ trạng thái
            self.assertTrue(PJ.get(con, slug)["settings"]["rank_paused"])
        self.assertTrue(cfg.rank.paused)
        con = db.connect(":memory:")
        logs = []
        R.run(con, SITE, cfg.rank, client=None, end=date(2026, 10, 1), log=logs.append)  # client None: không được gọi
        self.assertIn("Tạm ngưng", logs[0])
        calls = []
        self.assertEqual(V.refresh(con, SITE, cfg, date(2026, 10, 1), fetcher=lambda *a, **k: calls.append(1),
                                   log=lambda m: None), 0)
        self.assertEqual(calls, [])
        with closing(db.connect(base.db_path)) as c2:
            PJ.set_paused(c2, slug, False, "t")
            self.assertFalse(PJ.config_for(base, PJ.get(c2, slug)).rank.paused)
        shutil.rmtree(tmp, ignore_errors=True)


class BudgetProjectionTest(unittest.TestCase):
    def test_projected_never_below_spent(self):
        from datetime import date

        from seo_report.web_budget import projected
        self.assertAlmostEqual(projected(0.09, 0.30, date(2026, 11, 2)), 0.09 + 0.30 * 28 / 30)
        self.assertEqual(projected(0.09, 0.30, date(2026, 11, 30)), 0.09)
        self.assertEqual(projected(0.09, 0.30, date(2026, 11, 2), paused=True), 0.09)


class LogoSafetyTest(unittest.TestCase):
    def test_non_image_bytes_are_rejected(self):
        with self.assertRaises(ValueError):
            PJ.data_uri(b'{"refresh_token": "x"}', "image/png")
        with self.assertRaises(ValueError):
            PJ.data_uri(b"not svg", "image/svg+xml")
        self.assertTrue(PJ.data_uri(b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml").startswith(
            "data:image/svg+xml;base64,"))

    def test_file_scheme_icon_is_never_opened(self):
        import io
        import urllib.request
        from unittest import mock
        opened = []

        class Resp(io.BytesIO):
            headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(self, req, timeout=None):
            opened.append(req.full_url)
            if req.full_url == "https://example.test/":
                return Resp(b'<link rel="apple-touch-icon" sizes="999" href="file:secrets/token.json#.png">')
            raise OSError("offline")
        with mock.patch.object(urllib.request.OpenerDirector, "open", fake_open):
            self.assertIsNone(PJ.fetch_logo("https://example.test/"))
        self.assertFalse([u for u in opened if u.startswith("file:")])
