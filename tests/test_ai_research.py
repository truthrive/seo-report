import io
import json
import unittest

from seo_report import ai_http as AH
from seo_report import ai_research as AR

PROV = {"name": "x", "style": "chat", "base": "https://gw.example/v1", "key": "k", "model": "m"}
ROWS = [{"keyword": "gọng kính cận", "volume": 1600, "intent": "transactional", "gsc_pos": 15.2,
         "gsc_page": "https://a.vn/gong-kinh/"},
        {"keyword": "gọng kính cận nữ", "volume": 500, "intent": "transactional"},
        {"keyword": "cách chọn gọng kính", "volume": 300, "intent": "informational"},
        {"keyword": "kính râm", "volume": 5400, "intent": "transactional"}]


def reply(obj):
    def op(req, timeout=0):
        op.body = json.loads(req.data)
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}]})
                          .encode())
    return op


class StrategyTest(unittest.TestCase):
    def test_check_rules(self):
        from seo_report import ai_strategy as S
        raw = {"summary": "Tập trung nhóm gọng kính.",
               "pillars": [
                   {"name": "Gọng kính cận", "role": "revenue", "existing_url": "https://a.vn/gong-kinh/",
                    "keywords": ["Gọng kính cận", "gọng kính cận nữ", "bịa"], "why": "Doanh thu chính"},
                   {"name": "Trùng", "keywords": ["gọng kính cận"]},
                   {"name": "Kiến thức", "role": "lạ", "existing_url": "https://bia.vn", "keywords": ["cách chọn gọng kính"]}],
               "quick_wins": [{"action": "Tối ưu trang gọng kính", "keywords": ["gọng kính cận", "kính râm"]},
                              {"action": "Không hợp lệ", "keywords": ["kính râm"]}],
               "phases": [{"name": "GĐ1", "actions": ["a", ""]}, {"name": "GĐ2"}, {}, {"actions": ["x"]}],
               "kpis": ["Top 10 nhóm gọng"], "risks": []}
        out = S.check(raw, ROWS)
        self.assertEqual([p["name"] for p in out["pillars"]], ["Gọng kính cận", "Kiến thức"])
        p0, p1 = out["pillars"]
        self.assertEqual((p0["volume"], p0["best"], p0["ranked"]), (2100, 15.2, 1))
        self.assertEqual(p0["existing_url"], "https://a.vn/gong-kinh/")
        self.assertEqual((p1["role"], p1["existing_url"]), ("coverage", ""))
        self.assertEqual(len(out["quick_wins"]), 1)  # kính râm chưa có hạng: không phải thắng nhanh
        self.assertEqual(out["quick_wins"][0]["keywords"], [{"keyword": "gọng kính cận", "pos": 15, "volume": 1600}])
        self.assertEqual([p["name"] for p in out["phases"]], ["GĐ1"])  # tối đa 3, bỏ giai đoạn rỗng
        self.assertEqual(out["unassigned"], ["kính râm"])
        st = out["status"]
        self.assertEqual((st["n"], st["volume"], st["page2"], st["none"]), (4, 7800, 1, 3))

    def test_write_and_ref(self):
        from seo_report import ai_strategy as S
        op = reply({"pillars": [{"name": "A", "keywords": ["kính râm"]}]})
        out, _ = S.write(None, ROWS, "Tâm Đức", PROV, op)
        self.assertEqual(out["pillars"][0]["volume"], 5400)
        msg = op.body["messages"][1]["content"]
        self.assertIn("1 ở trang 2", msg)
        self.assertIn("trang của site: https://a.vn/gong-kinh/", msg)
        with self.assertRaises(AH.AIError):
            S.write(None, ROWS, "", PROV, reply({"pillars": [{"keywords": ["bịa"]}]}))
        self.assertEqual(S.ref(ROWS), S.ref(list(reversed(ROWS))))


class BriefTest(unittest.TestCase):
    def test_write_brief(self):
        d = {"keyword": "gọng kính cận", "intent": "transactional", "questions": [{"keyword": "gọng kính nào tốt", "volume": 10}],
             "variations": [], "site": None, "serp": {"results": [{"rank": 1, "domain": "b.vn", "url": "https://b.vn"}]}}
        op = reply({"title": "T" * 200, "outline": [{"h2": "Mở đầu", "h3": ["a", ""]}, {"h2": ""}], "faq": ["q1"]})
        out, _ = AR.write_brief(None, d, "", PROV, op)
        self.assertEqual(len(out["title"]), 90)
        self.assertEqual(out["outline"], [{"h2": "Mở đầu", "h3": ["a"], "note": ""}])
        self.assertIn("gọng kính nào tốt", op.body["messages"][1]["content"])
        with self.assertRaises(AH.AIError):
            AR.write_brief(None, d, "", PROV, reply({"outline": []}))


if __name__ == "__main__":
    unittest.main()
