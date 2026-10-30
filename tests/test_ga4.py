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
            {"accountSummaries": [{"displayName": "Tâm Đức", "propertySummaries": [
                {"property": "properties/1", "displayName": "matkinhtamduc.com"}]}], "nextPageToken": "1"},
            {"accountSummaries": [{"displayName": "Khác", "propertySummaries": [
                {"property": "properties/2", "displayName": "site 2"}]}]},
        ])
        self.assertEqual([p["property"] for p in ga4.list_properties(admin)], ["properties/1", "properties/2"])

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
