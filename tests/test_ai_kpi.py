import io
import json
import unittest

from seo_report import ai_http as AH
from seo_report import ai_kpi as AK

SHEET = """### Tab: KPI cam kết
Tên dự án | Tâm Đức
Ngày bắt đầu | 08/10/2026
Loại | Nguồn | Đơn vị | 1 | 2 | 3
Top 3 | Bộ riêng | số từ khóa | 4 | 6 | 10
Top 10 | Bộ riêng | % | 20% | 30% | 40%
Mức tháng | Organic | phiên | 25.000 | 26.500 | 28.000
### Tab: Từ khóa cam kết
Từ khóa | Top target
giá tròng kính | 3
kính râm | 10"""
PROV = {"name": "x", "style": "chat", "base": "https://gw.example/v1", "key": "k", "model": "m"}


class AiKpiTest(unittest.TestCase):
    def test_check_drops_invented(self):
        raw = {"start": "08/10/2026", "months": 3,
               "rows": {"top3": {"unit": "count", "values": [4, 6, 99]},          # 99 không có trong sheet
                        "top10": {"unit": "pct", "values": [20, 0.3, 40]},
                        "organic": {"values": [25000, "26.500", 28000]}},
               "keywords": {"3": [{"keyword": "giá tròng kính"}, {"keyword": "từ khóa bịa"}],
                            "10": [{"keyword": "kính râm"}, {"keyword": "Giá tròng kính"}]}}
        out = AK.check(raw, SHEET)
        self.assertEqual(out["rows"]["top3"]["values"], [4, 6, None])
        self.assertEqual(out["rows"]["top10"]["values"], [0.2, 0.3, 0.4])
        self.assertEqual(out["rows"]["organic"]["values"], [25000, 26500, 28000])
        self.assertEqual([k["keyword"] for k in out["keywords"][3]], ["giá tròng kính"])
        self.assertEqual([k["keyword"] for k in out["keywords"][10]], ["kính râm"])  # trùng mốc 3: bỏ
        self.assertEqual(out["dropped"], 2)
        self.assertEqual((out["start"], out["months"]), ("08/10/2026", 3))

    def test_read_rejects_empty(self):
        def op(req, timeout=0):
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": '{"rows": {}}'}}]}).encode())
        with self.assertRaises(AH.AIError):
            AK.read(None, SHEET, PROV, op)


if __name__ == "__main__":
    unittest.main()
