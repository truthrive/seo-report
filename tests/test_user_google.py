import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from seo_report import access as A
from seo_report import projects as PJ
from seo_report import user_google as UG
from seo_report.config import Config

S = A.AccessSettings(editors=["owner@x.vn"])


class UserGoogleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "secrets").mkdir()
        self.base = Config(site_url="https://goc.vn/", db_path=d / "data" / "seo.db",
                           client_secret=d / "secrets" / "client_secret.json", token_path=d / "secrets" / "token.json",
                           access=S)
        (d / "data").mkdir()
        self.con = sqlite3.connect(self.base.db_path)
        self.con.executescript(PJ.SCHEMA)
        PJ.create(self.con, self.base, {"name": "Gốc", "site_url": "https://goc.vn/"}, "owner@x.vn")
        A.set_user(self.con, "mem@gmail.com", A.MEMBER, "owner@x.vn")
        A.set_user(self.con, "team@gmail.com", A.MEMBER, "owner@x.vn", team_role=A.EDITOR)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_token_path_private(self):
        p = UG.token_path(self.base, "Mem@Gmail.com")
        self.assertEqual(p, UG.token_path(self.base, "mem@gmail.com"))
        self.assertNotIn("mem", p.name)
        self.assertEqual(p.parent.name, "user_tokens")

    def test_add_site_uses_owner_token_and_blocks_paid(self):
        p = UG.add_site(self.con, self.base, "mem@gmail.com", "Shop Mem", "sc-domain:mem.vn")
        cfg = PJ.config_for(self.base, p)
        self.assertEqual(cfg.token_path, UG.token_path(self.base, "mem@gmail.com"))
        self.assertFalse(cfg.paid_ok)
        self.assertTrue(cfg.rank.paused)  # không gửi yêu cầu DataForSEO
        self.assertTrue(UG.blocked(cfg, "rank"))
        self.assertTrue(UG.blocked(cfg, "ai_report"))
        self.assertFalse(UG.blocked(cfg, "audit"))  # miễn phí: dùng ngay
        UG.set_paid(self.con, p["slug"], True, "owner@x.vn")
        cfg2 = PJ.config_for(self.base, PJ.get(self.con, p["slug"]))
        self.assertTrue(cfg2.paid_ok)
        self.assertFalse(UG.blocked(cfg2, "rank"))
        root = PJ.config_for(self.base, PJ.get(self.con, "goc-vn"))  # website thường: token chung của tool
        self.assertEqual(root.token_path, self.base.token_path)
        self.assertFalse(UG.blocked(root, "rank"))
        self.assertEqual([x["slug"] for x in UG.my_sites(self.con, "mem@gmail.com")], [p["slug"]])

    def test_private_site_visibility(self):
        p = UG.add_site(self.con, self.base, "mem@gmail.com", "Shop Mem", "sc-domain:mem.vn")
        first = "goc-vn"
        mem = A.User("mem@gmail.com", A.VIEWER)
        team = A.User("team@gmail.com", A.VIEWER)
        admin = A.User("ad@x.vn", A.ADMIN_ACCT)
        self.assertEqual(A.project_role(self.con, S, mem, p["slug"], first, True), A.EDITOR)
        self.assertIsNone(A.project_role(self.con, S, team, p["slug"], first, True))  # Team mọi dự án: không thấy
        self.assertEqual(A.project_role(self.con, S, team, first, first, False), A.EDITOR)
        self.assertIsNotNone(A.project_role(self.con, S, admin, p["slug"], first, True))
        people = {x["email"] for x in A.people_in_project(self.con, S, p["slug"], first, True)}
        self.assertIn("mem@gmail.com", people)
        self.assertNotIn("team@gmail.com", people)

    def test_points_take_blocks(self):
        from seo_report import points as PT
        notes = []
        ui = SimpleNamespace(notify=lambda *a, **k: notes.append(a[0]))
        cfg = SimpleNamespace(site_url="sc-domain:mem.vn", google_owner="mem@gmail.com", paid_ok=False)
        self.assertIs(PT.take(ui, A.User("mem@gmail.com", A.EDITOR), cfg, "rank"), False)
        self.assertIn("chưa được bật", notes[0])

    def test_ask_once(self):
        from seo_report import web_my_google as MG
        (self.base.client_secret.parent / "google_login.toml").write_text(
            'client_id = "1.apps.googleusercontent.com"\nclient_secret = "s"\n', encoding="utf-8")
        mem = A.User("mem@gmail.com", A.VIEWER)
        A.set_member(self.con, "mem@gmail.com", "goc-vn", A.EDITOR, "owner@x.vn")
        self.assertTrue(MG.should_ask(self.con, self.base, mem))
        MG.mark_asked(self.con, "mem@gmail.com")
        self.assertFalse(MG.should_ask(self.con, self.base, mem))  # chỉ hỏi một lần
        A.set_user(self.con, "khach@gmail.com", A.MEMBER, "owner@x.vn")
        A.set_member(self.con, "khach@gmail.com", "goc-vn", A.CLIENT, "owner@x.vn")
        self.assertFalse(MG.should_ask(self.con, self.base, A.User("khach@gmail.com", A.VIEWER)))  # Guest: không

    def test_finish_rejects_other_user(self):
        UG._FLOWS["st1"] = (object(), __import__("time").monotonic(), "mem@gmail.com")
        with self.assertRaises(ValueError):
            UG.finish(self.con, self.base, "team@gmail.com", "st1", "https://x/oauth/google/me?state=st1")
        with self.assertRaises(ValueError):  # phiên đã dùng
            UG.finish(self.con, self.base, "mem@gmail.com", "st1", "https://x/oauth/google/me?state=st1")


if __name__ == "__main__":
    unittest.main()
