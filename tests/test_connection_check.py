import unittest

from seo_report import connection_check as CC

SITES = [{"siteUrl": "sc-domain:abc.vn", "permissionLevel": "siteOwner"},
         {"siteUrl": "https://xyz.vn/", "permissionLevel": "siteUnverifiedUser"},
         {"siteUrl": "https://www.other.vn/", "permissionLevel": "siteFullUser"}]


class GscCheckTest(unittest.TestCase):
    def test_exact_property(self):
        r = CC.gsc_check("sc-domain:abc.vn", SITES)
        self.assertEqual((r["status"], r["code"]), ("ok", "ok"))

    def test_unverified(self):
        self.assertEqual(CC.gsc_check("https://xyz.vn/", SITES)["code"], "unverified")

    def test_other_form_suggests_right_property(self):
        r = CC.gsc_check("https://abc.vn/", SITES)
        self.assertEqual((r["code"], r["suggest"]), ("other_form", "sc-domain:abc.vn"))
        r = CC.gsc_check("sc-domain:other.vn", SITES)  # www. coi như cùng tên miền
        self.assertEqual((r["code"], r["suggest"]), ("other_form", "https://www.other.vn/"))

    def test_missing(self):
        self.assertEqual(CC.gsc_check("sc-domain:khong-co.vn", SITES)["code"], "missing")

    def test_data(self):
        self.assertEqual(CC.gsc_data_check([], 7)["status"], "warn")
        r = CC.gsc_data_check([{"clicks": 3, "impressions": 1200}, {"clicks": 1, "impressions": 300}], 7)
        self.assertEqual(r["status"], "ok")
        self.assertIn("1.500 lượt hiển thị", r["message"])


class Ga4ResultTest(unittest.TestCase):
    def test_stream_result_levels(self):
        from seo_report import ga4
        ok = CC.ga4_stream_result(ga4.stream_check("sc-domain:abc.vn", [{"url": "https://www.abc.vn"}]))
        mixed = CC.ga4_stream_result(ga4.stream_check("sc-domain:abc.vn", [{"url": "https://abc.vn"},
                                                                          {"url": "https://xyz.vn"}]))
        wrong = CC.ga4_stream_result(ga4.stream_check("sc-domain:abc.vn", [{"url": "https://xyz.vn"}]))
        none = CC.ga4_stream_result(ga4.stream_check("sc-domain:abc.vn", []))
        self.assertEqual([r["status"] for r in (ok, mixed, wrong, none)], ["ok", "warn", "error", "error"])
        self.assertIn("xyz.vn", wrong["message"])

    def test_data(self):
        self.assertEqual(CC.ga4_data_check(0, 7)["status"], "warn")
        self.assertIn("1.234 phiên", CC.ga4_data_check(1234, 7)["message"])


if __name__ == "__main__":
    unittest.main()
