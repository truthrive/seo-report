import base64
import json
import time
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from seo_report import access as A

S = A.AccessSettings(editors=["Marketing@matkinhtamduc.com"], viewers=["boss@gmail.com"])


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class IdentifyTest(unittest.TestCase):
    def test_local_is_owner(self):
        u, why = A.identify({}, S, "Truong Thinh", "127.0.0.1")
        self.assertEqual((str(u), u.role, why), ("Truong Thinh", A.LOCAL, ""))
        self.assertTrue(A.can_edit(u))

    def test_lan_or_proxied_request_is_not_owner(self):
        # Máy khác trong mạng (nếu sau này mở cho LAN) hay yêu cầu qua proxy không được coi là chủ máy
        self.assertIsNone(A.identify({}, S, "me", "192.168.1.20")[0])
        self.assertIsNone(A.identify({"x-forwarded-for": "1.2.3.4"}, S, "me", "127.0.0.1")[0])

    def test_cloudflare_email_header_not_trusted_without_jwt_check(self):
        u, _ = A.identify({"cf-ray": "x", "cf-access-authenticated-user-email": "marketing@matkinhtamduc.com"},
                          S, "me", "127.0.0.1")
        self.assertIsNone(u)  # header có thể bị giả: bắt đăng nhập bằng mật khẩu

    def test_tailscale_serve(self):
        u, _ = A.identify({"tailscale-user-login": "Boss@gmail.com", "x-forwarded-for": "100.64.0.2"}, S, "me")
        self.assertEqual((str(u), u.role), ("boss@gmail.com", A.VIEWER))
        u, why = A.identify({"tailscale-user-login": "la@gmail.com"}, S, "me")
        self.assertIsNone(u)
        self.assertIn("la@gmail.com", why)


class ToolListTest(unittest.TestCase):
    """Email thêm trên màn Phân quyền cộng với danh sách trong config.toml."""

    def setUp(self):
        import sqlite3
        self.con = sqlite3.connect(":memory:")

    def tearDown(self):
        self.con.close()

    def test_add_change_remove(self):
        A.set_user(self.con, " Khach@ABC.vn ", A.VIEWER, "me", "khách hàng ABC")
        self.assertIn("khach@abc.vn", A.effective(self.con, S).viewers)
        A.set_user(self.con, "khach@abc.vn", A.EDITOR, "me")
        self.assertIn("khach@abc.vn", A.effective(self.con, S).editors)
        A.remove_user(self.con, "khach@abc.vn", "me")
        self.assertNotIn("khach@abc.vn", A.effective(self.con, S).editors)
        # gỡ mềm: vẫn còn dòng lịch sử
        self.assertEqual(self.con.execute("SELECT removed_by FROM access_users").fetchone()[0], "me")

    def test_config_role_is_authoritative(self):
        A.set_user(self.con, "boss@gmail.com", A.EDITOR, "me")  # boss@gmail.com là viewer trong config
        us = {u["email"]: u for u in A.users(self.con, S)}
        self.assertEqual((us["boss@gmail.com"]["role"], us["boss@gmail.com"]["source"]), (A.VIEWER, "config"))

    def test_bad_email(self):
        with self.assertRaises(ValueError):
            A.set_user(self.con, "khong-phai-email", A.VIEWER, "me")


class PasswordTest(unittest.TestCase):
    def setUp(self):
        import sqlite3
        self.con = sqlite3.connect(":memory:")
        A.set_user(self.con, "khach@abc.vn", A.VIEWER, "me")

    def tearDown(self):
        self.con.close()

    def test_hash_is_salted_and_checked(self):
        h1, h2 = A.hash_password("mat-khau-123"), A.hash_password("mat-khau-123")
        self.assertNotEqual(h1, h2)
        self.assertTrue(A.check_password("mat-khau-123", h1))
        self.assertFalse(A.check_password("mat-khau-124", h1))
        self.assertFalse(A.check_password("x", None))

    def test_temp_password_must_change_then_login(self):
        tmp = A.temp_password()
        self.assertEqual(len(tmp), 14)
        A.set_password(self.con, S, "khach@abc.vn", tmp, must_change=True)
        u, why, sess = A.login(self.con, S, "Khach@ABC.vn", tmp)
        self.assertEqual((u.role, u.must_change, u.via), (A.VIEWER, True, "password"))
        self.assertEqual(A.from_session(self.con, S, sess), "khach@abc.vn")
        # đổi mật khẩu: phiên cũ (gắn với lần đặt mật khẩu trước) hết hiệu lực
        A.set_password(self.con, S, "khach@abc.vn", "mat-khau-moi-123", must_change=False)
        self.assertIsNone(A.from_session(self.con, S, sess))
        u, _, sess2 = A.login(self.con, S, "khach@abc.vn", "mat-khau-moi-123")
        self.assertFalse(u.must_change)
        # gỡ quyền: phiên hết hiệu lực, không đăng nhập được nữa
        A.remove_user(self.con, "khach@abc.vn", "me")
        self.assertIsNone(A.from_session(self.con, S, sess2))
        self.assertIsNone(A.login(self.con, S, "khach@abc.vn", "mat-khau-moi-123")[0])

    def test_config_user_can_get_password(self):
        A.set_password(self.con, S, "boss@gmail.com", "mat-khau-sep-1", must_change=True)
        u, _, _ = A.login(self.con, S, "boss@gmail.com", "mat-khau-sep-1")
        self.assertEqual(u.role, A.VIEWER)

    def test_lockout_after_five_failures(self):
        from datetime import datetime, timedelta, timezone
        A.set_password(self.con, S, "khach@abc.vn", "dung-mat-khau-1", must_change=False)
        now = datetime.now(timezone.utc)
        for _ in range(A.MAX_FAILED):
            u, why, _ = A.login(self.con, S, "khach@abc.vn", "sai-mat-khau-0", now)
        self.assertIn("tạm khóa", why)
        u, why, _ = A.login(self.con, S, "khach@abc.vn", "dung-mat-khau-1", now)
        self.assertIsNone(u)  # đúng mật khẩu vẫn bị chặn khi đang khóa
        u, _, _ = A.login(self.con, S, "khach@abc.vn", "dung-mat-khau-1", now + timedelta(minutes=A.LOCK_MINUTES + 1))
        self.assertIsNotNone(u)

    def test_short_password_and_unknown_email(self):
        with self.assertRaises(ValueError):
            A.set_password(self.con, S, "khach@abc.vn", "ngan", must_change=False)
        with self.assertRaises(ValueError):
            A.set_password(self.con, S, "la@gmail.com", "mat-khau-dai-1", must_change=False)
        self.assertEqual(A.login(self.con, S, "la@gmail.com", "x")[1], "Email hoặc mật khẩu không đúng")


class JwtTest(unittest.TestCase):
    def setUp(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = self.key.public_key().public_numbers()
        A._CERTS.update(at=time.time(), keys={"k1": {
            "kid": "k1", "n": b64(pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")),
            "e": b64(pub.e.to_bytes(3, "big"))}})
        self.s = A.AccessSettings(editors=["a@matkinhtamduc.com"], team_domain="x.cloudflareaccess.com", aud="AUD1")

    def token(self, **body):
        head = b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode())
        payload = b64(json.dumps({"aud": ["AUD1"], "exp": time.time() + 60, "email": "a@matkinhtamduc.com",
                                  **body}).encode())
        sig = self.key.sign(f"{head}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{head}.{payload}.{b64(sig)}"

    def test_valid_token(self):
        u, _ = A.identify({"cf-ray": "x", "cf-access-jwt-assertion": self.token()}, self.s, "me")
        self.assertEqual(u.role, A.EDITOR)

    def test_header_email_ignored_when_jwt_configured(self):
        u, why = A.identify({"cf-ray": "x", "cf-access-authenticated-user-email": "a@matkinhtamduc.com"}, self.s, "me")
        self.assertIsNone(u)

    def test_wrong_aud_expired_or_tampered(self):
        for t in (self.token(aud=["OTHER"]), self.token(exp=time.time() - 5),
                  self.token()[:-6] + "AAAAAA"):
            u, why = A.identify({"cf-ray": "x", "cf-access-jwt-assertion": t}, self.s, "me")
            self.assertIsNone(u, why)


if __name__ == "__main__":
    unittest.main()


class ProjectAccessTest(unittest.TestCase):
    """Nhiều dự án: mỗi tài khoản theo dự án chỉ vào được các website được gắn, quyền riêng từng website."""

    def setUp(self):
        import sqlite3
        self.con = sqlite3.connect(":memory:")
        A.set_user(self.con, "khach-a@a.vn", A.MEMBER, "me")
        A.set_member(self.con, "khach-a@a.vn", "a", A.CLIENT, "me")
        A.set_user(self.con, "team@x.vn", A.MEMBER, "me")
        A.set_member(self.con, "team@x.vn", "a", A.EDITOR, "me")
        A.set_member(self.con, "team@x.vn", "b", A.VIEWER, "me")

    def tearDown(self):
        self.con.close()

    def role(self, user, project, first="tam-duc"):
        return A.project_role(self.con, S, user, project, first)

    def test_member_only_sees_assigned_projects(self):
        khach = A.User("khach-a@a.vn", A.MEMBER)
        self.assertEqual(self.role(khach, "a"), A.CLIENT)
        self.assertIsNone(self.role(khach, "b"))
        self.assertIsNone(self.role(khach, "tam-duc"))
        team = A.User("team@x.vn", A.MEMBER)
        self.assertEqual((self.role(team, "a"), self.role(team, "b")), (A.EDITOR, A.VIEWER))

    def test_admin_and_owner_see_everything(self):
        self.assertEqual(self.role(A.User("Truong Thinh", A.LOCAL), "b"), A.LOCAL)
        self.assertEqual(self.role(A.User("marketing@matkinhtamduc.com", A.ADMIN), "b"), A.EDITOR)

    def test_rights_inside_project(self):
        khach = A.in_project(A.User("khach-a@a.vn", A.MEMBER), A.CLIENT)
        self.assertTrue(A.is_client(khach))
        self.assertFalse(A.can_edit(khach) or A.is_admin(khach))
        team = A.in_project(A.User("team@x.vn", A.MEMBER), A.EDITOR)
        self.assertTrue(A.can_edit(team))
        self.assertFalse(A.is_admin(team))  # được sửa một dự án không có nghĩa là quản trị dự án / phân quyền
        admin = A.in_project(A.User("m@x.vn", A.ADMIN), A.EDITOR)
        self.assertTrue(A.is_admin(admin))

    def test_owner_preview_keeps_preview_role_and_is_not_admin(self):
        pv = A.User("Truong Thinh", A.CLIENT, preview=True, admin=True)
        self.assertEqual(self.role(pv, "b"), A.CLIENT)
        self.assertFalse(A.is_admin(A.in_project(pv, A.CLIENT)))

    def test_remove_member_revokes(self):
        A.remove_member(self.con, "team@x.vn", "b", "me")
        self.assertIsNone(self.role(A.User("team@x.vn", A.MEMBER), "b"))
        A.set_member(self.con, "team@x.vn", "b", A.CLIENT, "me")  # gắn lại được
        self.assertEqual(self.role(A.User("team@x.vn", A.MEMBER), "b"), A.CLIENT)

    def test_config_viewer_always_keeps_first_project(self):
        boss = A.User("boss@gmail.com", A.MEMBER)
        self.assertEqual(self.role(boss, "tam-duc"), A.VIEWER)
        self.assertIsNone(self.role(boss, "a"))
        A.set_member(self.con, "boss@gmail.com", "a", A.VIEWER, "me")  # gắn thêm dự án khác: không mất dự án đầu
        self.assertEqual((self.role(boss, "tam-duc"), self.role(boss, "a")), (A.VIEWER, A.VIEWER))
        A.set_member(self.con, "boss@gmail.com", "tam-duc", A.CLIENT, "me")  # gắn riêng dự án đầu: theo quyền gắn
        self.assertEqual(self.role(boss, "tam-duc"), A.CLIENT)

    def test_bad_project_role(self):
        with self.assertRaises(ValueError):
            A.set_member(self.con, "khach-a@a.vn", "a", "owner", "me")

    def test_migrate_old_viewers_once(self):
        A.set_user(self.con, "cu@x.vn", A.VIEWER, "me")  # tài khoản chỉ xem từ trước khi có nhiều dự án
        self.assertEqual(A.migrate_members(self.con, S, "tam-duc"), 1)
        self.assertEqual(self.role(A.User("cu@x.vn", A.MEMBER), "tam-duc"), A.VIEWER)
        A.set_user(self.con, "moi@x.vn", A.VIEWER, "me")
        self.assertEqual(A.migrate_members(self.con, S, "tam-duc"), 0)  # chỉ chạy một lần
        self.assertIsNone(self.role(A.User("moi@x.vn", A.MEMBER), "tam-duc"))
