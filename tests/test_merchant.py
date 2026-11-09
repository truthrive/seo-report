import sqlite3
import unittest
from datetime import date

from seo_report import merchant as M

ACC = {"name": "accounts/123", "accountId": "123", "accountName": "Shop A", "homepageUri": "https://a.vn"}


def pv(id_, status, issues=(), **kw):
    return {"productView": {"id": id_, "offerId": id_.split("~")[-1], "title": f"SP {id_}", "brand": kw.get("brand", "X"),
                            "availability": kw.get("availability", "IN_STOCK"), "condition": "NEW",
                            "gtin": kw.get("gtin", ["123"]), "price": {"amountMicros": "1500000000", "currencyCode": "VND"},
                            "thumbnailLink": "", "channel": "ONLINE", "clickPotential": "HIGH",
                            "expirationDate": kw.get("exp"), "aggregatedReportingContextStatus": status,
                            "itemIssues": list(issues)}}


ISSUE_GTIN = {"type": {"code": "missing_gtin", "canonicalAttribute": "gtin"},
              "severity": {"aggregatedSeverity": "DEMOTED"}, "resolution": "MERCHANT_ACTION"}
ISSUE_IMG = {"type": {"code": "image_too_small", "canonicalAttribute": "image_link"},
             "severity": {"aggregatedSeverity": "DISAPPROVED"}, "resolution": "MERCHANT_ACTION"}
ISSUE_WAIT = {"type": {"code": "pending_check", "canonicalAttribute": "price"},
              "severity": {"aggregatedSeverity": "PENDING"}, "resolution": "PENDING_PROCESSING"}


class FakeClient:
    def __init__(self, fail_perf=False):
        self.queries = []
        self.fail_perf = fail_perf

    def search(self, account, query):
        self.queries.append(query)
        if "product_view" in query:
            return [pv("online~vi~VN~a1", "ELIGIBLE"),
                    pv("online~vi~VN~a2", "ELIGIBLE_LIMITED", [ISSUE_GTIN], gtin=[], brand=""),
                    pv("online~vi~VN~a3", "NOT_ELIGIBLE_OR_DISAPPROVED", [ISSUE_IMG, ISSUE_WAIT]),
                    pv("online~vi~VN~a4", "ELIGIBLE_LIMITED", [ISSUE_GTIN], gtin=[], exp={"year": 2026, "month": 11,
                                                                                          "day": 10})]
        if self.fail_perf:
            raise M.ApiError("403 PERMISSION_DENIED: no")
        return [{"productPerformanceView": {"date": {"year": 2026, "month": 11, "day": d}, "offerId": "a1",
                                            "title": "SP a1", "marketingMethod": "ORGANIC", "clicks": "3",
                                            "impressions": "40"}} for d in (2, 3, 4)] + [
            {"productPerformanceView": {"date": {"year": 2026, "month": 11, "day": 4}, "offerId": "a1", "title": "SP a1",
                                        "marketingMethod": "ADS", "clicks": "5", "impressions": "90"}}]

    def account_issues(self, account):
        return [{"name": "accounts/123/issues/1", "title": "Chưa xác minh website", "severity": "CRITICAL",
                 "detail": "Xác minh và xác nhận quyền sở hữu website", "documentationUri": "https://x"}]


class MerchantTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        M.ensure_tables(self.con)

    def test_refresh_without_account_does_nothing(self):
        self.assertEqual(M.refresh(self.con, None, client=FakeClient()), {})

    def test_refresh_and_audit(self):
        M.link(self.con, ACC, "u")
        logs = []
        out = M.refresh(self.con, None, today=date(2026, 11, 6), client=FakeClient(), log=logs.append)
        self.assertEqual((out["products"], out["perf_rows"], out["issues"]), (4, 4, 1))
        self.assertEqual(logs, [])
        prods = M.products(self.con)
        self.assertEqual(prods[0]["price"], 1500.0)
        self.assertEqual(M.totals(self.con, date(2026, 11, 1), date(2026, 11, 5)), {"clicks": 9, "impressions": 120})
        self.assertEqual(M.totals(self.con, date(2026, 11, 1), date(2026, 11, 5), "ADS")["clicks"], 5)
        self.assertEqual(M.methods(self.con), ["ADS", "ORGANIC"])
        perf = M.per_product(self.con, date(2026, 10, 9), date(2026, 11, 5))
        checks = M.audit(prods, M.account_issues(self.con), perf, today=date(2026, 11, 6))
        keys = [c["key"] for c in checks]
        self.assertEqual(checks[0]["level"], "high")              # vấn đề tài khoản CRITICAL đứng đầu
        self.assertIn("st:dis", keys)
        self.assertIn("st:lim", keys)
        gtin = next(c for c in checks if c["key"] == "is:missing_gtin|gtin")
        self.assertEqual(len(gtin["ids"]), 2)
        self.assertIn("Mã GTIN", gtin["title"])
        self.assertFalse(any("pending_check" in k for k in keys))  # Google đang xử lý: không tính
        self.assertIn("at:brand", keys)
        self.assertIn("at:exp", keys)                              # hết hạn 10/11, trong 7 ngày
        zero = next(c for c in checks if c["key"] == "pf:zero")    # a2, a4 đủ điều kiện mà 0 lượt hiển thị
        self.assertEqual(len(zero["ids"]), 2)

    def test_part_failure_keeps_others(self):
        M.link(self.con, ACC, "u")
        logs = []
        out = M.refresh(self.con, None, today=date(2026, 11, 6), client=FakeClient(fail_perf=True), log=logs.append)
        self.assertEqual(out["products"], 4)
        self.assertIsNone(out["perf_rows"])
        self.assertTrue(logs and "Merchant Center" in logs[0] and "quyền" in logs[0])

    def test_relink_other_account_clears_data(self):
        M.link(self.con, ACC, "u")
        M.refresh(self.con, None, today=date(2026, 11, 6), client=FakeClient())
        M.link(self.con, {**ACC, "name": "accounts/999"}, "u")
        self.assertEqual(M.products(self.con), [])
        self.assertEqual(M.linked(self.con)["account"], "accounts/999")


if __name__ == "__main__":
    unittest.main()
