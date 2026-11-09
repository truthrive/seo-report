import json
import unittest
from datetime import date
from types import SimpleNamespace

from seo_report import aio
from seo_report import db
from seo_report import keyword_research as KR
from seo_report import rank as R
from seo_report import rank_overview as RO
from seo_report import seo_value as SV
from seo_report import volume as V
from seo_report.config import KeywordSettings, RankSettings

SITE = "https://x.vn/"
END = date(2026, 11, 5)


class SeoValueTest(unittest.TestCase):
    def setUp(self):
        self.con = c = db.connect(":memory:")
        R.ensure_tables(c)
        V.ensure_tables(c)
        KR.ensure_tables(c)
        c.execute("INSERT INTO kw_meta VALUES ('currency', 'VND')")
        self.cfg = SimpleNamespace(site_url=SITE, keywords=KeywordSettings(brand_terms=("xvn",)), logo="",
                                   rank=RankSettings(monthly_budget_usd=100.0))
        aio.brands(c, self.cfg)
        self.rival = aio.save_brand(c, SITE, "Đối thủ Y", "", "y.vn")
        self.set_id = R.create_set(c, SITE, "Theo dõi", "t", schedule={"type": "weekdays", "weekdays": [0],
                                                                         "depth": 20, "time": "07:00"})
        R.add_keywords(c, SITE, self.cfg.rank, END, [("kính cận", None), ("gọng kính", None), ("kính hiếm", None)],
                       "t", set_id=self.set_id)
        self.ids = {k["keyword"]: k["id"] for k in R.keywords(c, SITE, END, self.set_id)}

    def tearDown(self):
        self.con.close()

    def check(self, kw, day, rank, organic):
        kid = self.ids[kw]
        with self.con:
            self.con.execute("INSERT INTO rank_checks VALUES (?, ?, 20, ?, NULL, NULL, 0.002, ?)",
                             (kid, day, rank, day + "T00:00:00"))
            self.con.execute("INSERT INTO rank_serp (keyword_id, check_date, organic) VALUES (?, ?, ?)",
                             (kid, day, json.dumps([{"rank": r, "domain": d, "url": f"https://{d}/a"}
                                                    for r, d in organic])))

    def prices(self):
        KR.save_cpc(self.con, [
            {"keyword": "kính cận", "volume": 1000, "low_bid": 1000.0, "high_bid": 3000.0,
             "monthly": [(f"2026-{m:02d}", 1000 if m != 12 else 3000) for m in range(1, 13)]},
            {"keyword": "gọng kính", "volume": 500, "low_bid": 500.0, "high_bid": 500.0, "monthly": []},
            {"keyword": "kính hiếm"}])  # Google Ads không có số

    def test_share_of_voice_weights_by_volume(self):
        self.prices()
        self.check("kính cận", "2026-11-03", 1, [(1, "x.vn"), (2, "y.vn")])
        self.check("gọng kính", "2026-11-03", 5, [(1, "y.vn"), (5, "x.vn")])
        self.check("kính hiếm", "2026-11-03", 1, [(1, "x.vn")])
        sov = SV.share_of_voice(self.con, self.cfg, END)
        rows = {r["brand"]["name"]: r for r in sov["rows"]}
        own = next(r for r in sov["rows"] if r["brand"]["own"])
        mine = 1000 * RO.CTR[1] + 500 * RO.CTR[5]
        self.assertEqual(own["clicks"], round(mine))
        self.assertEqual(rows["Đối thủ Y"]["clicks"], round(1000 * RO.CTR[2] + 500 * RO.CTR[1]))
        self.assertAlmostEqual(own["share"], mine / (1500 * SV.TOP10_CTR))
        self.assertEqual(own["value"], round(1000 * RO.CTR[1] * 2000 + 500 * RO.CTR[5] * 500))
        self.assertEqual((sov["keywords"], sov["no_volume"]), (2, 1))  # "kính hiếm" không ai tìm: không tính

    def test_forecast_and_season(self):
        self.prices()
        self.check("kính cận", "2026-11-03", 8, [(8, "x.vn")])
        self.check("gọng kính", "2026-11-03", 2, [(2, "x.vn")])
        fc = SV.forecast(self.con, self.cfg, END, today=date(2026, 10, 15))
        self.assertEqual([r["keyword"] for r in fc["rows"]], ["kính cận"])  # gọng kính đã ở top 3
        r = fc["rows"][0]
        self.assertEqual(r["gain"], round(1000 * (RO.CTR[3] - RO.CTR[8])))
        self.assertEqual(r["value"], round(1000 * (RO.CTR[3] - RO.CTR[8]) * 2000))
        self.assertEqual(r["peak"], 12)
        self.assertTrue(r["soon"])  # tháng 11–12 cao hơn trung bình năm

    def test_check_advice_and_apply(self):
        self.prices()
        for d in ("2026-10-06", "2026-10-13", "2026-10-20", "2026-10-27"):
            self.check("kính cận", d, 2, [(2, "x.vn")])  # đứng yên top 3
            self.check("gọng kính", d, None, [])  # không thấy trong độ sâu check 4 lần liền
        adv = SV.check_advice(self.con, self.cfg, END)
        items = {i["keyword"]: i["why"] for s in adv["sets"] for i in s["items"]}
        self.assertEqual(items, {"kính cận": "stable", "kính hiếm": "low", "gọng kính": "far"})
        per = R._pages(20) * self.cfg.rank.price_per_page
        self.assertAlmostEqual(adv["saving"], 3 * per * (R.checks_per_month({"type": "weekdays", "weekdays": [0]}) - 1))
        res = SV.apply_advice(self.con, self.cfg, [self.ids["kính cận"]], "t")
        self.assertEqual(len(res["moved"]), 1)
        dest = next(s for s in R.sets(self.con, SITE) if s["name"] == SV.MONTHLY_SET)
        self.assertEqual(dest["schedule"]["type"], "monthly")
        self.assertEqual(len(SV.check_advice(self.con, self.cfg, END)["sets"][0]["items"]), 2)


if __name__ == "__main__":
    unittest.main()
