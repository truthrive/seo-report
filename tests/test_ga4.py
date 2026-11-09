import json
import tempfile
import unittest
from pathlib import Path

from seo_report import auth, ga4
from seo_report.config import Config, _ga4_property


def cfg_with_token(scopes) -> Config:
    tmp = Path(tempfile.mkdtemp())
    token = tmp / "token.json"
    token.write_text(json.dumps({"token": "x", "refresh_token": "r", "client_id": "c", "client_secret": "s",
                                 "token_uri": "https://oauth2.googleapis.com/token", "scopes": scopes,
                                 "expiry": "2999-01-01T00:00:00Z"}), encoding="utf-8")
    return Config(site_url="https://x.vn/", db_path=tmp / "db", client_secret=tmp / "cs.json", token_path=token)


class Req:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeAdmin:
    def __init__(self, pages):
        self.pages = pages

    def accountSummaries(self):
        return self

    def list(self, pageSize, pageToken):
        return Req(self.pages[int(pageToken or 0)])


class AuthTest(unittest.TestCase):
    def test_old_gsc_token_keeps_working_for_gsc(self):
        cfg = cfg_with_token([auth.GSC_SCOPE])
        self.assertEqual(auth.get_credentials(cfg).scopes, [auth.GSC_SCOPE])

    def test_ga4_needs_relogin_with_clear_message(self):
        cfg = cfg_with_token([auth.GSC_SCOPE])
        with self.assertRaises(SystemExit) as ctx:
            auth.get_credentials(cfg, need=auth.ALL_SCOPES)
        self.assertIn("seo_report login", str(ctx.exception))

    def test_token_with_both_scopes(self):
        cfg = cfg_with_token(auth.ALL_SCOPES)
        self.assertTrue(auth.get_credentials(cfg, need=auth.ALL_SCOPES).valid)


class Ga4Test(unittest.TestCase):
    def test_property_id_normalized(self):
        self.assertEqual(_ga4_property("123456789"), "properties/123456789")
        self.assertEqual(_ga4_property(" properties/42 "), "properties/42")
        self.assertEqual(_ga4_property(""), "")

    def test_list_properties_follows_pages(self):
        admin = FakeAdmin([
            {"accountSummaries": [{"displayName": "Vi Du Shop", "propertySummaries": [
                {"property": "properties/1", "displayName": "vidushop.com"}]}], "nextPageToken": "1"},
            {"accountSummaries": [{"displayName": "Khác", "propertySummaries": [
                {"property": "properties/2", "displayName": "site 2"}]}]},
        ])
        self.assertEqual([p["property"] for p in ga4.list_properties(admin)], ["properties/1", "properties/2"])

    def test_stream_check(self):
        """Đối chiếu luồng dữ liệu GA4 với website dự án (vụ Vinpest: property gắn nhầm thu số trang khác)."""
        def s(*urls):
            return [{"url": u} for u in urls]
        site = "sc-domain:vinpest.vn"
        self.assertEqual(ga4.stream_check(site, s("https://vinpest.vn/"))["status"], "ok")
        self.assertEqual(ga4.stream_check("https://vinpest.vn/", s("https://www.vinpest.vn"))["status"], "ok")
        r = ga4.stream_check(site, s("https://truongthinh-portfolio.vercel.app/"))
        self.assertEqual(r["status"], "mismatch")
        self.assertIn("truongthinh-portfolio.vercel.app", r["message"])
        mixed = ga4.stream_check("https://gfcalumi.vn/", s("https://gfcalumi.vn/", "https://x.vercel.app/"))
        self.assertEqual((mixed["status"], mixed["domains"]), ("mixed", ["gfcalumi.vn", "x.vercel.app"]))
        self.assertEqual(ga4.stream_check(site, [])["status"], "no_stream")
        self.assertEqual(ga4.stream_check(site, s("https://shop.vinpest.vn/"))["status"], "ok")  # tên miền con

    def test_web_streams(self):
        class Admin:
            def properties(self):
                return self

            def dataStreams(self):
                return self

            def list(self, parent, pageSize):
                return Req({"dataStreams": [
                    {"type": "WEB_DATA_STREAM", "displayName": "Web", "webStreamData": {
                        "defaultUri": "https://a.vn", "measurementId": "G-1"}},
                    {"type": "ANDROID_APP_DATA_STREAM", "displayName": "App"}]})
        self.assertEqual(ga4.web_streams(Admin(), "properties/1"),
                         [{"name": "Web", "url": "https://a.vn", "measurement_id": "G-1"}])

    def test_explain_disabled_api(self):
        from googleapiclient.errors import HttpError
        resp = type("R", (), {"status": 403, "reason": "Forbidden"})()
        err = HttpError(resp, b'{"error":{"message":"Google Analytics Data API has not been used in project 1"}}')
        self.assertIn("Enable", ga4.explain(err))

    def test_clients_build_offline(self):
        creds = auth.get_credentials(cfg_with_token(auth.ALL_SCOPES), need=auth.ALL_SCOPES)
        self.assertTrue(hasattr(auth.build_ga4_data(creds), "properties"))
        self.assertTrue(hasattr(auth.build_ga4_admin(creds), "accountSummaries"))


if __name__ == "__main__":
    unittest.main()
