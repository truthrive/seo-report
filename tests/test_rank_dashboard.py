"""Dashboard Tổng quan: phạm vi, từ khóa duy nhất, biến động chỉ trên từ khóa có lịch sử, xu hướng theo %."""
import unittest
from datetime import timedelta
from types import SimpleNamespace

from seo_report import db
from seo_report import rank as R
from seo_report import rank_dashboard as D
from seo_report.config import RankSettings
from tests.test_rank import END, SITE, TUE, FakeDataForSEO, run


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.s = RankSettings(monthly_budget_usd=20)
        self.a = R.create_set(self.con, SITE, "A", "t", kind="kpi")
        self.b = R.create_set(self.con, SITE, "B", "t")
        R.add_keywords(self.con, SITE, self.s, END, [("x", None), ("y", None)], "t", set_id=self.a)
        R.add_keywords(self.con, SITE, self.s, END, [("x", None), ("z", None)], "t", set_id=self.b)
        self.fake = FakeDataForSEO({"x": [("vidushop.com", SITE)], "y": [("a.vn", "https://a.vn/")] * 3
                                    + [("vidushop.com", SITE)], "z": [("vidushop.com", SITE)]})
        run(self.con, self.s, self.fake, TUE)

    def test_scope_unique_keywords_and_moves(self):
        kws, rows = D.scope_keywords(self.con, SITE, END, "all")
        self.assertEqual((len(kws), rows), (3, 4))  # x ở 2 bộ: 1 từ khóa, 2 lượt
        self.assertEqual(len(D.scope_keywords(self.con, SITE, END, "custom")[0]), 2)
        k = D.kpis(kws)
        self.assertEqual((k["history"], k["new"], k["tiers"][3]["count"], k["tiers"][3]["new"]), (0, 3, 2, 2))
        # lần sau: x rớt khỏi top 3 → rời 1, không có từ khóa mới
        self.fake.serps["x"] = [("a.vn", "https://a.vn/")] * 4 + [("vidushop.com", SITE)]
        run(self.con, self.s, self.fake, TUE + timedelta(days=7))
        kws, _ = D.scope_keywords(self.con, SITE, END, "all")
        k = D.kpis(kws)
        t3 = k["tiers"][3]
        self.assertEqual((t3["count"], t3["enter"], t3["leave"], t3["new"], k["down"]), (1, 0, 1, 0, 1))
        titles = [i["title"] for i in D.insights(kws, None)]
        self.assertIn("1 từ khóa rời Top 3", titles)
        tr = D.trend(self.con, kws, "check")
        self.assertEqual([p["pct3"] for p in tr], [round(2 / 3 * 100, 1), round(1 / 3 * 100, 1)])
        R.add_keywords(self.con, SITE, self.s, END, [(f"k{i}", None) for i in range(6)], "t", set_id=self.a)
        kws, _ = D.scope_keywords(self.con, SITE, END, "all")
        self.assertTrue(all(p["thin"] and p["pct3"] is None for p in D.trend(self.con, kws, "check")))
        weeks = D.trend(self.con, kws, "week", 6, today=TUE + timedelta(days=21))
        self.assertTrue(any(p["pct3"] is None for p in weeks))  # tuần không check: để trống, không nối

    def test_competitors_need_same_place(self):
        R.update_set(self.con, self.b, "t", settings={"device": "desktop"})
        cfg = SimpleNamespace(site_url=SITE, rank=self.s, keywords=SimpleNamespace(brand_terms=()))
        kws, _ = D.scope_keywords(self.con, SITE, END, "all")
        self.assertIn("invalid", D.competitor_snapshot(self.con, cfg, END, "all", kws))


if __name__ == "__main__":
    unittest.main()
