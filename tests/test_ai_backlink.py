import unittest

from seo_report import ai_backlink as AB
from seo_report import ai_http as AH
from tests.test_ai_rank import PROV, reply


def link(d, spam=0, anchor="kính mắt", to="https://s.vn/", src=("dfs",), threat=""):
    return {"d_from": d, "u_from": f"https://{d}/a", "u_to": to, "anchor": anchor, "follow": True, "spam": spam,
            "d_rank": 100, "d_ascore": 20, "src": list(src), "type": "anchor", "threat": threat, "title": "Bài viết"}


ITEMS = [link("a.vn"), link("a.vn", to="https://s.vn/trong-kinh"), link("b.vn", spam=70),
         link("c.com", threat="MALWARE"), link("d.vn", src=("semrush",))]


class ProfileTest(unittest.TestCase):
    def test_facts_and_write(self):
        checks = [{"key": "L_spam", "title": "Spam", "level": "high", "count": 1, "unit": "website"},
                  {"key": "ok", "title": "Ổn", "level": "ok", "count": 0, "unit": ""}]
        f = AB.profile_facts({"items": ITEMS}, {"now": {"rank": 200}}, checks, {"Báo": 1})
        self.assertEqual(f["theo_nguon"]["all"]["website"], 4)
        self.assertEqual(f["theo_nguon"]["semrush"]["backlink"], 1)
        self.assertEqual(len(f["muc_kiem_tra"]), 1)  # mục "ok" không gửi
        res, _ = AB.write_profile(None, f, dict(PROV), opener=reply({
            "headline": "Hồ sơ có 4 website trỏ về.",
            "points": [{"level": "risk", "text": "Có 1 website spam."}, {"level": "x", "text": "Có 999 link lạ."}],
            "actions": ["Disavow website spam"]}))
        self.assertEqual(res["headline"], "Hồ sơ có 4 website trỏ về.")
        self.assertEqual([p["text"] for p in res["points"]], ["Có 1 website spam."])  # số bịa bị bỏ
        self.assertTrue(res["fingerprint"])


class ClassifyTest(unittest.TestCase):
    def test_only_unlabeled_and_check(self):
        f = AB.classify_facts(ITEMS, {"a.vn": ["Báo"]}, ["Báo", "Diễn đàn"])
        self.assertNotIn("a.vn", [d["website"] for d in f["website"]])
        self.assertEqual(f["nhan_duoc_phep"][-1], "Khác")
        res, _ = AB.write_classify(None, f, dict(PROV), opener=reply({"items": [
            {"website": "b.vn", "label": "Diễn đàn", "confidence": "high", "reason": "tiêu đề diễn đàn"},
            {"website": "b.vn", "label": "Báo", "confidence": "high", "reason": "trùng"},
            {"website": "x.vn", "label": "Báo", "confidence": "high", "reason": "không có trong dữ liệu"},
            {"website": "c.com", "label": "Nhãn lạ", "confidence": "high", "reason": "nhãn ngoài danh sách"}]}))
        self.assertEqual([(x["website"], x["label"]) for x in res["items"]], [("b.vn", "Diễn đàn")])


class DisavowTest(unittest.TestCase):
    def test_flags_and_text(self):
        f = AB.disavow_facts(ITEMS, [])
        self.assertEqual({d["website"] for d in f["website"]}, {"b.vn", "c.com"})
        res, _ = AB.write_disavow(None, f, dict(PROV), opener=reply({"items": [
            {"website": "b.vn", "decision": "disavow", "reason": "spam 70"},
            {"website": "c.com", "decision": "??", "reason": "cảnh báo"}], "note": "Xem lại trước khi nộp."}))
        self.assertEqual({x["website"]: x["decision"] for x in res["items"]}, {"b.vn": "disavow", "c.com": "review"})
        txt = AB.disavow_text(res["items"], "13/11/2026")
        self.assertIn("domain:b.vn", txt)
        self.assertNotIn("domain:c.com", txt)


class RivalsTest(unittest.TestCase):
    GAP = {"rivals": [{"name": "r1.vn"}, {"name": "r2.vn"}],
           "items": [{"domain": "x.vn", "rivals": ["r1.vn", "r2.vn"], "ascore": 30, "rank": 200, "country": "VN"},
                     {"domain": "y.com", "rivals": ["r1.vn"], "ascore": 5, "spam": 40}]}

    def test_facts_and_write(self):
        f = AB.rivals_facts(self.GAP, {"x.vn": ["Báo"]})
        self.assertEqual([r["name"] for r in f["doi_thu"]], ["r1.vn", "r2.vn"])
        self.assertEqual(f["doi_thu"][0]["theo_nhan"], {"Báo": 1, "chưa gắn nhãn": 1})
        self.assertEqual(f["website_tro_ve_tu_2_doi_thu"], 1)
        res, _ = AB.write_rivals(None, f, dict(PROV), opener=reply({
            "summary": "Đối thủ dựa vào báo.", "rivals": [{"name": "r1.vn", "strategy": "Báo chí", "evidence": ""},
                                                          {"name": "lạ.vn", "strategy": "x"}],
            "lessons": ["Xin link báo"]}))
        self.assertEqual([r["name"] for r in res["rivals"]], ["r1.vn"])

    def test_empty_gap(self):
        with self.assertRaises(AH.AIError):
            AB.write_rivals(None, AB.rivals_facts(None, {}), dict(PROV), opener=reply({}))


class PlanTest(unittest.TestCase):
    def test_codes_and_sources(self):
        rows = [{"url": "https://s.vn/trong-kinh", "best": {"q": "tròng kính", "pos": 8}, "domains": 1, "impr": 500}]
        data = AB.plan_facts(rows, ITEMS, RivalsTest.GAP, {}, ["tâm đức"])
        f, codes = data
        self.assertEqual(codes, {"p1": "https://s.vn/trong-kinh"})
        self.assertEqual(f["trang"][0]["website_tro_ve"], 1)
        self.assertEqual([s["website"] for s in f["nguon_goi_y"]], ["x.vn"])  # y.com spam 40 bị loại
        res, _ = AB.write_plan(None, data, dict(PROV), opener=reply({"items": [
            {"url": "p1", "anchor_kind": "brand", "anchors": ["Tâm Đức"], "sources": ["x.vn", "z.vn"],
             "steps": ["Viết bài PR"]}, {"url": "p9", "anchor_kind": "url"}]}))
        self.assertEqual(len(res["items"]), 1)
        x = res["items"][0]
        self.assertEqual((x["url"], x["keyword"], x["sources"]), ("https://s.vn/trong-kinh", "tròng kính", ["x.vn"]))


if __name__ == "__main__":
    unittest.main()
