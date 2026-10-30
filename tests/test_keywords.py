import unittest
from datetime import date

from seo_report import db
from seo_report import keywords as K
from seo_report import urls as U
from seo_report.config import KeywordSettings

SITE = "https://matkinhtamduc.com/"
A = "https://matkinhtamduc.com/gong-kinh/"
B = "https://matkinhtamduc.com/"
DAY = "2026-10-20"


def q(url, query, clicks, impr, pos=3.0):
    return {"keys": [url, query], "clicks": clicks, "impressions": impr, "ctr": 0, "position": pos}


class KeywordTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        rows = [
            q(A, "gọng kính", 50, 900),           # head
            q(A, "gong kinh nam", 10, 300),       # phụ
            q(A, "gọng kính tâm đức", 40, 100),   # thương hiệu
            q(A, "gọng kính titan", 0, 20),       # impression thấp
            q(A, "kính cận", 3, 400, pos=45),     # position quá xa
            q(A, "mắt kính", 2, 200),             # URL khác mạnh hơn + cannibalization
            q(B, "mắt kính", 30, 800),
        ] + [q(A, f"gọng kính loại {i}", 1, 100) for i in range(6)]  # 6 ứng viên, chỉ còn chỗ cho 4
        db.replace_day(self.con, SITE, DAY, [], rows)
        U.assign_urls(self.con, SITE)
        self.ids = dict(self.con.execute("SELECT url, id FROM urls").fetchall())
        self.settings = KeywordSettings(window_days=28, min_impressions=50, max_position=30, max_secondary=5,
                                        brand_terms=("tâm đức",))
        self.res = K.analyze(self.con, SITE, [self.ids[A]], date(2026, 10, 28), self.settings)[self.ids[A]]

    def test_head_skips_brand(self):
        self.assertEqual(self.res.head.query, "gọng kính")
        self.assertEqual(self.res.head_basis, "click")

    def test_secondary_and_reasons(self):
        self.assertEqual([k.query for k in self.res.secondary][:1], ["gong kinh nam"])
        self.assertEqual(len(self.res.secondary), 5)
        reasons = {k.query: k.reason for k in self.res.excluded}
        self.assertEqual(reasons["gọng kính tâm đức"], K.R_BRAND)
        self.assertEqual(reasons["gọng kính titan"], K.R_LOW_IMPR)
        self.assertEqual(reasons["kính cận"], K.R_FAR)
        self.assertEqual(reasons["mắt kính"], K.R_OTHER_URL)
        self.assertEqual(list(reasons.values()).count(K.R_OVER_LIMIT), 2)

    def test_cannibalization_points_to_stronger_url(self):
        self.assertEqual([(k.query, k.stronger_url) for k in self.res.cannibal], [("mắt kính", B)])

    def test_window_excludes_old_data(self):
        res = K.analyze(self.con, SITE, [self.ids[A]], date(2026, 12, 31), self.settings)[self.ids[A]]
        self.assertIsNone(res.head)

    def test_target_match_ignores_accents_and_logs(self):
        K.set_target(self.con, SITE, self.ids[A], "  Gong   Kinh ", "test")
        target = K.targets(self.con, [self.ids[A]])[self.ids[A]]
        self.assertEqual(target, "gong kinh")
        self.assertTrue(K.head_matches_target(self.res.head, target))
        self.assertFalse(K.head_matches_target(self.res.head, "gọng kính nam"))
        self.assertEqual(U.recent_changes(self.con, SITE)[0]["action"], "Sửa target KW")

    def test_weeks_are_monday_to_sunday(self):
        wks = K.weeks(date(2026, 10, 28), 2)  # thứ Tư
        self.assertEqual(wks, [(date(2026, 10, 19), date(2026, 10, 25)), (date(2026, 10, 12), date(2026, 10, 18))])

    def test_fold(self):
        self.assertEqual(K.fold("Mắt Kính Tâm Đức!"), "matkinhtamduc")


if __name__ == "__main__":
    unittest.main()
