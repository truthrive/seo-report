"""Volume từ Google Ads API (Keyword Planner): đọc cấu hình, đọc kết quả, báo lỗi dễ hiểu, dùng DataForSEO khi lỗi."""
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

from seo_report import db, google_ads as GA, rank as R, volume as V
from seo_report.config import Config

SITE = "https://vidushop.com/"
TODAY = date(2026, 11, 3)


class FakeCreds:
    valid, token = True, "tok"


class Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return json.dumps(self.body).encode()


class GoogleAdsTest(unittest.TestCase):
    def test_settings_template_and_digits(self):
        p = Path(tempfile.mkdtemp()) / "google_ads.toml"
        self.assertTrue(GA.write_template(p))
        self.assertIsNone(GA.load_settings(p))  # mẫu chưa điền
        self.assertFalse(GA.write_template(p))  # không ghi đè
        p.write_text('developer_token = "abc"\nlogin_customer_id = "123-456-7890"\ncustomer_id = "111-222-3333"\n',
                     encoding="utf-8")
        s = GA.load_settings(p)
        self.assertEqual((s["login_customer_id"], s["customer_id"], s["api_version"]),
                         ("1234567890", "1112223333", GA.API_VERSION))

    def test_parse_results_with_close_variants(self):
        seen = {}

        def opener(req, timeout):
            seen["url"], seen["headers"], seen["body"] = req.full_url, dict(req.header_items()), json.loads(req.data)
            return Resp({"results": [
                {"text": "tròng kính", "closeVariants": ["trong kinh"],
                 "keywordMetrics": {"avgMonthlySearches": "2900", "competition": "HIGH"}},
                {"text": "kính lạ", "keywordMetrics": {}}]})
        s = {"developer_token": "dev", "login_customer_id": "999", "customer_id": "111", "api_version": "v26"}
        got = GA.historical_metrics(FakeCreds(), s, ["tròng kính", "trong kinh", "kính lạ"], 2704, "vi",
                                    opener=opener)
        self.assertEqual(got["cost"], 0.0)
        self.assertEqual(got["result"], [
            {"keyword": "tròng kính", "search_volume": 2900, "competition": "HIGH"},
            {"keyword": "trong kinh", "search_volume": 2900, "competition": "HIGH"},
            {"keyword": "kính lạ", "search_volume": None, "competition": None}])
        self.assertTrue(seen["url"].endswith("/v26/customers/111:generateKeywordHistoricalMetrics"))
        self.assertEqual(seen["headers"]["Developer-token"], "dev")
        self.assertEqual(seen["headers"]["Login-customer-id"], "999")
        self.assertEqual(seen["body"]["geoTargetConstants"], ["geoTargetConstants/2704"])
        self.assertEqual(seen["body"]["language"], "languageConstants/1040")

    def test_test_level_token_error_is_plain(self):
        body = {"error": {"message": "x", "details": [{"errors": [
            {"errorCode": {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"}}]}]}}

        def opener(req, timeout):
            raise HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(json.dumps(body).encode()))
        s = {"developer_token": "d", "login_customer_id": "", "customer_id": "1", "api_version": "v26"}
        with self.assertRaises(RuntimeError) as cm:
            GA.historical_metrics(FakeCreds(), s, ["a"], 2704, "vi", opener=opener)
        self.assertIn("chưa được duyệt mức Basic", str(cm.exception))


    def test_explorer_access_needs_basic(self):
        body = {"error": {"details": [{"errors": [{"errorCode": {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"},
                                                   "message": "This method is not allowed for use with explorer "
                                                              "access. Please apply for basic or standard access."}]}]}}
        self.assertIn("cần xin mức Basic", GA._error_text(body, 403))


class VolumeSourceTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "dfs.toml").write_text('login = "x"\npassword = "y"\n', encoding="utf-8")
        self.cfg = Config(site_url=SITE, db_path=Path(":memory:"), client_secret=Path("x"), token_path=Path("y"),
                          dataforseo_secret=tmp / "dfs.toml")
        self.con = db.connect(":memory:")
        R.add_keywords(self.con, SITE, self.cfg.rank, TODAY, [("mắt kính", None)], "t")
        self._orig = (V._google_ads, GA.historical_metrics, V.fetch)

    def tearDown(self):
        V._google_ads, GA.historical_metrics, V.fetch = self._orig

    def test_google_ads_is_free_and_preferred(self):
        V._google_ads = lambda cfg: (FakeCreds(), {})
        GA.historical_metrics = lambda *a, **k: {"cost": 0.0, "result": [
            {"keyword": "mắt kính", "search_volume": 33100, "competition": "MEDIUM"}]}
        logs = []
        self.assertEqual(V.refresh(self.con, SITE, self.cfg, TODAY, TODAY, log=logs.append), 1)
        self.assertEqual(list(V.latest(self.con).values())[0]["volume"], 33100)
        self.assertEqual(V.spent_this_month(self.con, TODAY), 0)
        self.assertIn("Google Ads", logs[-1])

    def test_falls_back_to_dataforseo_on_error(self):
        V._google_ads = lambda cfg: (FakeCreds(), {})

        def boom(*a, **k):
            raise RuntimeError("Google Ads: developer token chưa được duyệt mức Basic")
        GA.historical_metrics = boom
        calls = []

        def dfs(login, pw, kws, loc, lang):
            calls.append(kws)
            return {"cost": 0.09, "result": [{"keyword": "mắt kính", "search_volume": 33100, "competition": "LOW"}]}
        V.fetch = dfs
        logs = []
        self.assertEqual(V.refresh(self.con, SITE, self.cfg, TODAY, TODAY, log=logs.append, fetcher=dfs), 1)
        self.assertEqual(calls, [["mắt kính"]])
        self.assertTrue(any("dùng DataForSEO" in m for m in logs))
