import io
import json
import unittest

from seo_report import ai_brief as B
from seo_report import ai_http as AH

SIGS = [{"id": "S1", "area": "Index", "level": "high", "fact": "3 URL vừa rớt khỏi index", "href": "/index"},
        {"id": "S2", "area": "Traffic", "level": "medium", "fact": "Click Google cả site tuần này 5.049 → 4.100 (-19%)",
         "href": "/url"},
        {"id": "S3", "area": "OKR", "level": "low", "fact": "1 việc OKR quá hạn", "href": "/okr"}]
PROV = {"name": "x", "style": "chat", "base": "https://gw.example/v1", "key": "k", "model": "m"}


class BriefValidateTest(unittest.TestCase):
    def test_rules(self):
        raw = {"headline": "Tuần này cần xử lý index trước.",
               "items": [
                   {"id": "S3", "priority": "high", "title": "OKR trễ", "why": "Ảnh hưởng tiến độ",
                    "action": "Cập nhật trạng thái"},                    # mức cao hơn tối đa → hạ về low
                   {"id": "S9", "priority": "high", "title": "Việc bịa"},  # mã lạ → bỏ
                   {"id": "s1", "priority": "high", "title": "3 URL rớt index", "why": "Mất traffic",
                    "action": "Kiểm tra 3 URL trong GSC"},
                   {"id": "S1", "priority": "high", "title": "trùng"},       # trùng mã → bỏ
                   {"id": "S2", "priority": "medium", "title": "Click giảm 25%",  # số lạ → thay bằng câu của tool
                    "why": "Click 5.049 → 4.100", "action": "Xem trang giảm click"}]}
        out = B.validate(raw, SIGS)
        self.assertEqual([x["id"] for x in out["items"]], ["S1", "S2", "S3"])
        self.assertEqual(out["dropped"], 2)
        s3 = next(x for x in out["items"] if x["id"] == "S3")
        self.assertEqual(s3["priority"], "low")
        s2 = next(x for x in out["items"] if x["id"] == "S2")
        self.assertEqual(s2["title"], SIGS[1]["fact"])
        self.assertFalse(s2["checked"])
        self.assertEqual(s2["why"], "Click 5.049 → 4.100")  # số có trong tín hiệu: giữ
        self.assertEqual(s2["href"], "/url")  # link lấy từ tín hiệu

    def test_max_two_per_area(self):
        sigs = [{"id": f"S{i}", "area": "Thứ hạng", "level": "medium", "fact": f"từ khóa {i} rớt", "href": "/rank"}
                for i in range(1, 5)]
        raw = {"items": [{"id": f"S{i}", "priority": "medium", "title": "rớt"} for i in range(1, 5)]}
        self.assertEqual(len(B.validate(raw, sigs)["items"]), 2)

    def test_numbers_normalised(self):
        self.assertEqual(B._nums("5.049 click, giảm 1,4% còn 05"), {"5049", "1.4", "5"})

    def test_run_rejects_empty(self):
        def op(req, timeout=0):
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": '{"items": [{"id": "S7"}]}'}}]}).encode())
        with self.assertRaises(AH.AIError):
            B.run(None, SIGS, PROV, op)

    def test_fingerprint_changes_with_facts(self):
        a = B.fingerprint(SIGS)
        self.assertEqual(a, B.fingerprint(list(reversed(SIGS))))
        self.assertNotEqual(a, B.fingerprint(SIGS[:2]))


if __name__ == "__main__":
    unittest.main()
