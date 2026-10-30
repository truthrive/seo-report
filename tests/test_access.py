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
        u, why = A.identify({}, S, "Truong Thinh")
        self.assertEqual((str(u), u.role, why), ("Truong Thinh", A.LOCAL, ""))
        self.assertTrue(A.can_edit(u))

    def test_roles_from_access_header(self):
        u, _ = A.identify({"cf-ray": "x", "cf-access-authenticated-user-email": "marketing@MATKINHTAMDUC.com"}, S, "me")
        self.assertEqual((str(u), u.role), ("marketing@matkinhtamduc.com", A.EDITOR))
        u, _ = A.identify({"cf-ray": "x", "cf-access-authenticated-user-email": "boss@gmail.com"}, S, "me")
        self.assertEqual(u.role, A.VIEWER)
        self.assertFalse(A.can_edit(u))

    def test_remote_without_login_or_not_listed_is_blocked(self):
        u, why = A.identify({"cf-ray": "x"}, S, "me")
        self.assertIsNone(u)
        self.assertIn("Chưa đăng nhập", why)
        u, why = A.identify({"cf-ray": "x", "cf-access-authenticated-user-email": "la@gmail.com"}, S, "me")
        self.assertIsNone(u)
        self.assertIn("la@gmail.com", why)

    def test_tailscale_serve(self):
        u, _ = A.identify({"tailscale-user-login": "Boss@gmail.com", "x-forwarded-for": "100.64.0.2"}, S, "me")
        self.assertEqual((str(u), u.role), ("boss@gmail.com", A.VIEWER))
        # Qua proxy mà không có danh tính (ví dụ máy gắn tag) thì chặn, không coi là chủ máy
        u, why = A.identify({"x-forwarded-for": "100.64.0.9"}, S, "me")
        self.assertIsNone(u)
        self.assertIn("Tailscale", why)


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
