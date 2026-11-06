"""Đăng nhập Google ngay trong tool: link đăng nhập xin đủ quyền, phiên chờ dùng một lần, báo quyền còn thiếu."""
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from seo_report import auth
from seo_report.config import Config


def cfg(tmp: Path) -> Config:
    secret = tmp / "client_secret.json"
    secret.write_text(json.dumps({"installed": {
        "client_id": "id.apps.googleusercontent.com", "client_secret": "s", "redirect_uris": ["http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}}),
        encoding="utf-8")
    return Config(site_url="https://x.vn/", db_path=tmp / "seo.db", client_secret=secret, token_path=tmp / "t.json")


class WebLoginTest(unittest.TestCase):
    def test_login_url_asks_all_scopes_with_pkce(self):
        c = cfg(Path(tempfile.mkdtemp()))
        url = auth.web_login_url(c, "http://localhost:8080/oauth/google", switch_account=True)
        q = parse_qs(urlsplit(url).query)
        self.assertEqual(q["redirect_uri"], ["http://localhost:8080/oauth/google"])
        self.assertEqual(set(q["scope"][0].split()), set(auth.SCOPES))
        self.assertIn(auth.ADS_SCOPE, q["scope"][0])
        self.assertEqual(q["access_type"], ["offline"])
        self.assertIn("select_account", q["prompt"][0])
        self.assertIn("code_challenge", q)
        self.assertIn(q["state"][0], auth._WEB_FLOWS)

    def test_unknown_or_reused_state_is_refused(self):
        c = cfg(Path(tempfile.mkdtemp()))
        with self.assertRaises(ValueError):
            auth.web_login_finish(c, "la", "http://localhost:8080/oauth/google?code=x&state=la")

    def test_granted_status(self):
        tmp = Path(tempfile.mkdtemp())
        c = cfg(tmp)
        self.assertFalse(auth.granted_status(c)["connected"])
        c.token_path.write_text(json.dumps({"token": "a", "refresh_token": "r", "client_id": "i", "client_secret": "s",
                                            "scopes": [auth.GSC_SCOPE, auth.GA4_SCOPE, auth.DRIVE_FULL_SCOPE,
                                                       auth.SHEETS_WRITE_SCOPE]}), encoding="utf-8")
        st = auth.granted_status(c)
        self.assertEqual((st["connected"], st["missing"]), (True, ["Google Ads", "Google Business Profile"]))
