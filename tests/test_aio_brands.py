"""Dashboard AI Overview theo thương hiệu: nhận biết nhắc tên, được trích, số theo tuần, thay đổi so với lần trước."""
import json
import unittest
from datetime import date
from types import SimpleNamespace

from seo_report import aio as AO
from seo_report import db
from seo_report import rank as R
from seo_report.config import RankSettings
from tests.test_rank import END, SITE

CFG = SimpleNamespace(site_url=SITE, keywords=SimpleNamespace(brand_terms=("vidu shop", "vidushop")))


def ref(d):
    return {"domain": d, "url": f"https://{d}/", "title": ""}


class BrandMatchTest(unittest.TestCase):
    def test_norm_and_mentions_ignore_case_and_accents(self):
        self.assertEqual(AO.norm("Mắt Kính TÂM ĐỨC, Hà Nội!"), "mat kinh tam duc ha noi")
        b = {"name": "Tâm Đức", "aliases": ["Mắt kính Tâm Đức"], "domains": ["matkinhtamduc.com"]}
        self.assertTrue(AO.mentioned(AO.norm("Nên mua ở mắt kính tam duc hoặc..."), b))
        self.assertTrue(AO.mentioned(AO.norm("Xem tại matkinhtamduc.com"), b))
        self.assertFalse(AO.mentioned(AO.norm("tâm đứcx không phải"), b))  # phải trọn từ
        self.assertTrue(AO.cited([ref("www.matkinhtamduc.com")], b))
        self.assertFalse(AO.cited([ref("other.vn")], b))


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        s = RankSettings(monthly_budget_usd=20)
        R.add_keywords(self.con, SITE, s, END, [("a", None), ("b", None), ("c", None)], "t")
        self.ids = {k["keyword"]: k["id"] for k in R.keywords(self.con, SITE, END)}

    def put(self, kw, day, aio, refs=(), text=None, top10=()):
        R.ensure_tables(self.con)
        self.con.execute("INSERT OR REPLACE INTO rank_serp (keyword_id, check_date, aio, aio_cited, aio_refs, top10, "
                         "features, aio_text) VALUES (?, ?, ?, NULL, ?, ?, '[]', ?)",
                         (self.ids[kw], day, aio, json.dumps([ref(d) for d in refs]),
                          json.dumps([{"rank": i + 1, "domain": d, "url": ""} for i, d in enumerate(top10)]), text))

    def test_own_brand_seeded_and_competitor_crud(self):
        bs = AO.brands(self.con, CFG)
        self.assertEqual((len(bs), bs[0]["own"], bs[0]["domains"]), (1, True, ["vidushop.com"]))
        self.assertEqual(bs[0]["aliases"], ["vidu shop", "vidushop"])
        bid = AO.save_brand(self.con, SITE, "Rival", "Rival Shop", "https://www.rival.vn/")
        self.assertEqual(AO.brands(self.con, CFG)[1]["domains"], ["rival.vn"])
        AO.remove_brand(self.con, SITE, bid)
        AO.remove_brand(self.con, SITE, bs[0]["id"])  # không bỏ được thương hiệu của mình
        self.assertEqual([b["name"] for b in AO.brands(self.con, CFG)], [bs[0]["name"]])

    def test_weekly_metrics_kpis_and_changes(self):
        AO.save_brand(self.con, SITE, "Rival", "", "rival.vn")
        # tuần 12/10
        self.put("a", "2026-10-13", 1, ["rival.vn"], "Rival là lựa chọn tốt", ["rival.vn", "vidushop.com"])
        self.put("b", "2026-10-13", 1, ["vidushop.com"], "Vidu Shop bán gọng kính", ["vidushop.com"])
        self.put("c", "2026-10-13", 0)
        # tuần 19/10: a được nhắc + trích, b mất nhắc + mất trích
        self.put("a", "2026-10-20", 1, ["vidushop.com", "rival.vn"], "Mua ở vidushop hoặc Rival", ["vidushop.com"])
        self.put("b", "2026-10-20", 1, ["rival.vn"], "Rival có nhiều mẫu")
        self.put("c", "2026-10-20", 1, ["rival.vn"], None)  # có AIO nhưng chưa lưu chữ: không tính nhắc tên
        d = AO.dashboard(self.con, CFG, today=date(2026, 10, 21), weeks=4)
        self.assertEqual([w["week"] for w in d["weeks"]], ["2026-10-12", "2026-10-19"])
        self.assertEqual(d["now"]["visibility"], (1, 2))   # nhắc tên trên số AIO có chữ
        self.assertEqual(d["now"]["citations"], (1, 3))
        self.assertEqual(d["now"]["presence"], (3, 3))
        self.assertEqual(d["prev"]["presence"], (2, 3))
        self.assertEqual(d["now"]["organic"], (1, 3))
        rival = d["brands"][1]["id"]
        self.assertEqual(d["weeks"][-1]["brands"][rival], {"mention": 2, "cite": 3})
        ch = AO.changes(self.con, CFG)
        self.assertEqual([x["keyword"] for x in ch["new_mention"]], ["a"])
        self.assertEqual([x["keyword"] for x in ch["lost_mention"]], ["b"])
        self.assertEqual([x["keyword"] for x in ch["new_cite"]], ["a"])
        self.assertEqual([x["keyword"] for x in ch["lost_cite"]], ["b"])
        rows = {r["keyword"]: r for r in AO.keyword_rows(self.con, CFG)}
        self.assertEqual(rows["a"]["mentioned"], [d["own"]["name"], "Rival"])
        self.assertIsNone(rows["c"]["own_mentioned"])
        self.assertEqual(AO.suggestions(self.con, CFG), [])  # rival.vn đã có trong danh sách



    def test_logo_fetched_once_and_refetched_when_domain_changes(self):
        bid = AO.save_brand(self.con, SITE, "Rival", "", "rival.vn")
        AO.save_brand(self.con, SITE, "Nope", "", "nope.vn")
        seen = []

        def fetch(d):
            seen.append(d)
            return "data:image/png;base64,AAAA" if d == "rival.vn" else None
        self.assertEqual(AO.fill_logos(self.con, CFG, fetch), 2)
        logos = {b["name"]: b["logo"] for b in AO.brands(self.con, CFG)}
        self.assertEqual((logos["Rival"], logos["Nope"]), ("data:image/png;base64,AAAA", ""))  # '' = không thử lại
        self.assertEqual(AO.fill_logos(self.con, CFG, fetch), 0)
        AO.save_brand(self.con, SITE, "Rival", "", "rival2.vn", bid)  # đổi tên miền: lấy lại
        self.assertEqual(AO.fill_logos(self.con, CFG, fetch), 1)
        self.assertEqual(seen[-1], "rival2.vn")

class CompetitorTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")

    def test_at_most_ten_competitors(self):
        AO.brands(self.con, CFG)  # thương hiệu của mình không tính
        for i in range(AO.MAX_COMPETITORS):
            AO.save_brand(self.con, SITE, f"Đối thủ {i}", "", f"dt{i}.vn")
        with self.assertRaises(ValueError):
            AO.save_brand(self.con, SITE, "Thứ 11", "", "dt11.vn")
        bid = AO.brands(self.con, CFG)[1]["id"]
        AO.save_brand(self.con, SITE, "Đổi tên", "", "dt0.vn", bid)  # sửa vẫn được
        AO.remove_brand(self.con, SITE, bid)
        AO.save_brand(self.con, SITE, "Thứ 11", "", "dt11.vn")

    def test_competitor_ranks_from_full_depth(self):
        items = [{"type": "organic", "rank_group": i + 1, "domain": d, "url": f"https://{d}/p"}
                 for i, d in enumerate(["a.vn"] * 3 + ["x.vn"] * 9 + ["www.rival.vn", "vidushop.com"])]
        serp = R.parse_serp({"result": [{"items": items}]}, SITE)
        self.assertEqual((len(serp["top10"]), len(serp["organic"])), (10, 14))
        rival = {"id": 1, "domains": ["rival.vn"]}
        nobody = {"id": 2, "domains": ["none.vn"]}
        got = AO.brand_ranks(serp["organic"], [rival, nobody])
        self.assertEqual((got[1]["rank"], got[2]), (13, None))


class ScheduleTest(unittest.TestCase):
    def test_next_scheduled_day(self):
        today = date(2026, 11, 5)  # thứ Năm
        self.assertEqual(R.next_scheduled_day({"type": "weekdays", "weekdays": [1]}, today), date(2026, 11, 10))
        self.assertEqual(R.next_scheduled_day({"type": "monthly", "day": 1}, today), date(2026, 12, 1))
        self.assertIsNone(R.next_scheduled_day({"type": "manual"}, today))

if __name__ == "__main__":
    unittest.main()
