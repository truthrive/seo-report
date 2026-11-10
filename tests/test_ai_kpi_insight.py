import json
import unittest

from seo_report import ai_kpi_insight as AKI
from seo_report import kpi as KP

TOP3 = {"kind": "rank", "unit": "count", "top": 3, "mode": "shared"}
ORG = {"kind": "level", "source": "organic", "watch": True}


def _p():
    l3 = KP.line_id(TOP3)
    lo = KP.line_id(ORG)
    rk = lambda c: {"kind": "rank", "checked": 7, "total": 7, "count": c, "actual": c / 7, "target": None}  # noqa: E731
    return {"lines": [TOP3, ORG], "months": [
        {"n": 1, "status": "closed", "targets": {}, "checks": {l3: rk(3), lo: {"kind": "level", "actual": 1000}}},
        {"n": 2, "status": "running", "days_done": 3, "days_total": 30, "targets": {},
         "checks": {l3: rk(5), lo: {"kind": "level", "actual": 100, "forecast": 1100}}},
        {"n": 3, "status": "future", "targets": {}},
        {"n": 4, "status": "future", "targets": {l3: 6}},
    ]}


class FactsTest(unittest.TestCase):
    def test_pace_and_forecast(self):
        f = AKI.facts(_p())
        top3 = next(k for k in f["kpi"] if k["ten"] == "Top 3")
        self.assertEqual(top3["hien_tai"], 5)
        self.assertEqual(top3["toc_do_moi_thang"], 2)
        self.assertEqual(top3["du_bao_thang_4"], 9)
        self.assertEqual(top3["con_thieu_den_cam_ket_ke_tiep"], 1)
        org = next(k for k in f["kpi"] if k["ten"] == "Organic traffic")
        self.assertEqual(org["hien_tai"], 1100)  # tháng đang chạy dùng dự báo cuối tháng

    def test_old_keyword_set_not_used_for_pace(self):
        p = _p()
        l3 = KP.line_id(TOP3)
        p["months"][0]["checks"][l3]["total"] = 50  # tháng 1 chấm theo bộ 50 từ khóa, nay bộ còn 7
        top3 = next(k for k in AKI.facts(p)["kpi"] if k["ten"] == "Top 3")
        self.assertNotIn("toc_do_moi_thang", top3)
        self.assertEqual([h["thang"] for h in top3["lich_su"]], [2])

    def test_check_drops_unknown_numbers_and_kpis(self):
        f = AKI.facts(_p())
        l3 = KP.line_id(TOP3)
        raw = {"headline": "Top 3 đang có 5 từ khóa",
               "items": [{"kpi": l3, "level": "good", "insight": "Đang có 5/7 từ khóa trong Top 3",
                          "forecast": "Tháng 4 dự kiến 9 từ khóa", "action": "Tối ưu thêm 47 trang"},
                         {"kpi": "khong-co", "level": "risk", "insight": "x"},
                         {"kpi": KP.line_id(ORG), "level": "lạ", "insight": "Traffic 123456 phiên"}]}
        res = AKI.check(raw, f)
        self.assertEqual([i["kpi"] for i in res["items"]], [l3])
        self.assertEqual(res["items"][0]["action"], "")  # 47 không có trong số liệu: bỏ câu
        self.assertEqual(res["items"][0]["forecast"], "Tháng 4 dự kiến 9 từ khóa")
        self.assertGreaterEqual(res["dropped"], 3)

    def test_write_parses_json(self):
        f = AKI.facts(_p())
        l3 = KP.line_id(TOP3)
        reply = json.dumps({"headline": "", "items": [{"kpi": l3, "level": "watch", "insight": "Có 5 từ khóa"}]})

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": reply}}]}).encode()
        prov = {"name": "x", "style": "chat", "base": "http://x", "key": "k", "model": "m"}
        res, _ = AKI.write(None, f, prov, opener=lambda req, timeout=0: R())
        self.assertEqual(res["items"][0]["level"], "watch")
        self.assertEqual(res["fingerprint"], AKI.fingerprint(f))


if __name__ == "__main__":
    unittest.main()
