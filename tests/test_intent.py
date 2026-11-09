"""Ý định tìm kiếm đoán theo chữ của từ khóa và trang kết quả Google."""
import unittest

from seo_report import intent as I


class IntentTest(unittest.TestCase):
    def test_words_brand_and_serp(self):
        self.assertEqual(I.classify("mắt kính tâm đức", brand_terms=["Tâm Đức"])[0], "N")
        self.assertEqual(I.classify("cách đọc bảng đo thị lực")[0], "I")
        self.assertEqual(I.classify("mẹo chọn gọng kính")[0], "I")
        self.assertEqual(I.classify("kính cận mắt mèo")[0], "C")  # "mèo" không phải "mẹo"
        self.assertEqual(I.classify("mua kính cận ở đâu")[0], "T")
        self.assertEqual(I.classify("gọng kính", ["local_pack"])[0], "T")
        self.assertEqual(I.classify("bảng giá tròng kính chemi")[0], "C")
        blog = [{"url": f"https://a{i}.vn/blog/bai-{i}"} for i in range(6)] + [{"url": "https://b.vn/san-pham/x"}]
        self.assertEqual(I.classify("kính đa tròng", [], blog)[0], "I")
        shop = [{"url": f"https://a{i}.vn/danh-muc/kinh"} for i in range(8)]
        self.assertEqual(I.classify("kính đa tròng", [], shop)[0], "C")
        self.assertEqual(I.label("C"), "Commercial (Cân nhắc mua)")


class FetchTest(unittest.TestCase):
    def test_fetch_once_and_prefer_dataforseo(self):
        from datetime import date
        from types import SimpleNamespace

        from seo_report import db
        from seo_report import rank as R
        from seo_report.config import RankSettings
        from tests.test_rank import END, SITE
        con = db.connect(":memory:")
        s = RankSettings(monthly_budget_usd=5)
        cfg = SimpleNamespace(site_url=SITE, rank=s, keywords=SimpleNamespace(brand_terms=()))
        R.add_keywords(con, SITE, s, END, [("gọng kính", None), ("Cách đọc bảng đo", None)], "t")
        calls = []

        def post(body):
            calls.append(body[0]["keywords"])
            return {"tasks": [{"status_code": 20000, "cost": 0.0122, "result": [{"items": [
                {"keyword": kw, "keyword_intent": {"label": "commercial", "probability": 0.6},
                 "secondary_keyword_intents": [{"label": "transactional", "probability": 0.3}]}
                for kw in body[0]["keywords"]]}]}]}
        self.assertEqual(I.fetch_missing(con, cfg, ("u", "p"), post=post), 2)
        self.assertEqual(calls, [["cách đọc bảng đo", "gọng kính"]])
        self.assertEqual(I.fetch_missing(con, cfg, ("u", "p"), post=post), 0)  # đã có: không gọi lại
        self.assertAlmostEqual(R.spent_this_month(con, date.today()), 0.0122)
        got = I.for_keywords(con, cfg, R.keywords(con, SITE, END))
        self.assertEqual({v[0] for v in got.values()}, {"C"})
        self.assertIn("DataForSEO, chắc 60%", next(iter(got.values()))[1])
        v = next(iter(got.values()))
        self.assertEqual(v[2], [("T", 0.3)])  # ý định phụ
        self.assertEqual(I.excel_cells(v), ["Commercial", "Transactional"])
        self.assertIn("có thể là: Transactional (Mua / giao dịch) 30%", I.tip(v))


if __name__ == "__main__":
    unittest.main()
