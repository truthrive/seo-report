import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from seo_report import access as A
from seo_report import google_login as GL

S = A.AccessSettings(editors=["owner@x.vn"])
URL = "https://report.x.vn"


class GoogleLoginFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "google_login.toml").write_text('client_id = "123.apps.googleusercontent.com"\n'
                                              'client_secret = "s3cret"\n', encoding="utf-8")
        self.cfg = SimpleNamespace(client_secret=d / "client_secret.json")

    def tearDown(self):
        self.tmp.cleanup()

    def start(self):
        url, pending = GL.start(self.cfg, URL + "/", "/kpi")
        return parse_qs(urlparse(url).query), pending

    def test_start_url(self):
        q, p = self.start()
        self.assertTrue(GL.ready(self.cfg))
        self.assertEqual(q["redirect_uri"], ["https://report.x.vn/auth/google"])
        self.assertEqual(q["scope"], ["openid email"])
        self.assertEqual(q["state"], [p["state"]])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertNotIn(p["verifier"], str(q))  # chỉ gửi mã băm của verifier
        self.assertEqual(p["next"], "/kpi")

    def test_finish_ok_and_checks(self):
        q, p = self.start()
        sent = {}

        def post(url, data):
            sent.update(data)
            return {"id_token": "tok"}

        info = {"email": "Ban@Gmail.com", "email_verified": True, "nonce": p["nonce"]}
        email = GL.finish(self.cfg, URL, p, {"state": p["state"], "code": "c1"}, post=post, verify=lambda t, c: info)
        self.assertEqual(email, "ban@gmail.com")
        self.assertEqual(sent["code_verifier"], p["verifier"])
        self.assertEqual(sent["client_secret"], "s3cret")
        bad = [({"state": "khac", "code": "c"}, info),  # state của trình duyệt khác
               ({"state": p["state"], "code": "c"}, {**info, "nonce": "khac"}),
               ({"state": p["state"], "code": "c"}, {**info, "email_verified": False}),
               ({"error": "access_denied"}, info)]
        for query, inf in bad:
            with self.assertRaises(ValueError):
                GL.finish(self.cfg, URL, p, query, post=post, verify=lambda t, c, i=inf: i)
        with self.assertRaises(ValueError):  # không có phiên chờ
            GL.finish(self.cfg, URL, None, {"state": p["state"]}, post=post, verify=lambda t, c: info)
        old = {**p, "at": time.time() - GL.TTL - 5}
        with self.assertRaises(ValueError):  # hết hạn
            GL.finish(self.cfg, URL, old, {"state": p["state"], "code": "c"}, post=post, verify=lambda t, c: info)

    def test_client_check(self):
        v = {"client_id": "1.apps.googleusercontent.com", "client_secret": "x"}
        self.assertTrue(GL.test_client(None, v, post=lambda u, d: {"error": "invalid_grant"})[0])
        self.assertFalse(GL.test_client(None, v, post=lambda u, d: {"error": "invalid_client"})[0])
        self.assertFalse(GL.test_client(None, {"client_id": "abc", "client_secret": "x"})[0])


class GoogleOnlyAccessTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        A.set_user(self.con, "mem@gmail.com", A.MEMBER, "me")
        A.set_password(self.con, S, "mem@gmail.com", "mat-khau-mem-1", must_change=False)
        A.set_password(self.con, S, "owner@x.vn", "mat-khau-owner-1", must_change=False)

    def tearDown(self):
        self.con.close()

    def test_google_session(self):
        u, why, sess = A.google_login(self.con, S, "Mem@Gmail.com")
        self.assertEqual((str(u), u.via), ("mem@gmail.com", "google"))
        self.assertEqual(A.from_session(self.con, S, sess).via, "google")
        row = next(x for x in A.users(self.con, S) if x["email"] == "mem@gmail.com")
        self.assertTrue(row["google_login"])
        self.assertIsNone(A.google_login(self.con, S, "la@gmail.com")[0])  # chưa được cấp quyền
        A.remove_user(self.con, "mem@gmail.com", "me")
        self.assertIsNone(A.from_session(self.con, S, sess))  # gỡ quyền: phiên Google hết hiệu lực

    def test_access_requests(self):
        self.assertEqual(A.add_request(self.con, "Moi@Gmail.com"), "new")
        self.assertEqual(A.add_request(self.con, "moi@gmail.com"), "pending")  # một dòng mỗi email
        self.assertEqual([r["email"] for r in A.pending_requests(self.con, S)], ["moi@gmail.com"])
        A.add_request(self.con, "mem@gmail.com")  # đã có quyền: không hiện trong danh sách chờ
        self.assertEqual(len(A.pending_requests(self.con, S)), 1)
        self.assertEqual(len(A.pending_requests(self.con)), 1)
        A.resolve_request(self.con, "moi@gmail.com", "rejected", "owner@x.vn")
        self.assertEqual(A.pending_requests(self.con, S), [])
        self.assertEqual(A.add_request(self.con, "moi@gmail.com"), "rejected")  # bị từ chối: không xin lại liên tục
        for i in range(A.MAX_PENDING):
            A.add_request(self.con, f"spam{i}@gmail.com")
        self.assertEqual(A.add_request(self.con, "them@gmail.com"), "full")

    def test_google_only_keeps_owner_password(self):
        _, _, mem_sess = A.login(self.con, S, "mem@gmail.com", "mat-khau-mem-1")
        self.assertIsNotNone(A.from_session(self.con, S, mem_sess))
        A.set_google_only(self.con, True, "owner@x.vn")
        self.assertIsNone(A.from_session(self.con, S, mem_sess))  # phiên mật khẩu cũ bị đăng xuất
        u, why, _ = A.login(self.con, S, "mem@gmail.com", "mat-khau-mem-1")
        self.assertIsNone(u)
        self.assertEqual(why, A.GOOGLE_ONLY_MSG)
        self.assertNotEqual(A.login(self.con, S, "mem@gmail.com", "sai-mat-khau")[1], A.GOOGLE_ONLY_MSG)
        owner, _, sess = A.login(self.con, S, "owner@x.vn", "mat-khau-owner-1")
        self.assertIsNotNone(owner)
        self.assertIsNotNone(A.from_session(self.con, S, sess))
        A.set_google_only(self.con, False, "owner@x.vn")
        self.assertIsNotNone(A.login(self.con, S, "mem@gmail.com", "mat-khau-mem-1")[0])


if __name__ == "__main__":
    unittest.main()
