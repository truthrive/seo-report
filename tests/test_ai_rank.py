import io
import json
import unittest

from seo_report import ai_rank as AR

PROV = {"name": "Cổng", "key_name": "gateway", "style": "chat", "base": "https://a.example/v1", "key": "k",
        "model": "m"}


def reply(obj):
    def open_(req, timeout=0):
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)},
                                                   "finish_reason": "stop"}]}).encode())
    return open_


def kw(i, name, rank, prev, target="", ranking="", top=None):
    return {"id": i, "keyword": name, "date": "2026-11-08", "rank": rank, "prev": prev, "last_depth": 20,
            "prev_depth": 20, "target_url": target, "ranking_url": ranking, "top_target": top, "paused": False,
            "note": ""}


class SetInsightTest(unittest.TestCase):
    def setUp(self):
        self.kws = [kw(1, "tròng kính", 1, 3, top=3), kw(2, "kính cận", None, 7), kw(3, "gọng kính", 6, None),
                    kw(4, "kính râm", 5, 5, "https://s.vn/a", "https://s.vn/b")]
        self.f = AR.set_facts("Cam kết", self.kws, {1: {"volume": 2900}}, [{"label": "05/11"}, {"label": "08/11"}])

    def test_facts(self):
        f = self.f
        self.assertEqual((f["top_hien_tai"]["top3"], f["top_lan_truoc"]["top3"]), (1, 1))
        self.assertEqual((f["so_len_hang"], f["so_rot_khoi_top"], f["so_vao_top"]), (1, 1, 1))
        self.assertEqual((f["sai_url_muc_tieu"], f["chua_co_url_muc_tieu"]), (1, 3))
        self.assertEqual(f["tang_manh"][0]["tu_khoa"], "gọng kính")  # vào top xếp trước số lên hạng

    def test_write_drops_invented_numbers(self):
        res, _ = AR.write_insight(None, self.f, dict(PROV), opener=reply({
            "headline": "Bộ giữ 1 từ khóa top 3",
            "points": [{"level": "good", "text": "tròng kính lên 1"}, {"level": "risk", "text": "mất 999 click"},
                       {"level": "bad", "text": "kính cận rớt khỏi top 20"}],
            "actions": ["Sửa trang kính cận", "Tăng 12345 backlink"]}))
        self.assertEqual([p["text"] for p in res["points"]], ["tròng kính lên 1", "kính cận rớt khỏi top 20"])
        self.assertEqual(res["points"][1]["level"], "watch")  # mức lạ → theo dõi
        self.assertEqual(res["actions"], ["Sửa trang kính cận"])


class TargetTest(unittest.TestCase):
    def test_only_listed_urls(self):
        rows = [{"keyword": "kính cận", "link_full": "https://s.vn/kinh-can/", "pos": "5", "volume": 880},
                {"keyword": "gọng kính", "link_full": "", "pos": ">20", "volume": -1}]
        data = AR.target_facts(rows, [{"url": "https://s.vn/gong/", "groups": ["SEO chủ lực"]}], "https://s.vn/")
        f, codes = data
        self.assertEqual(codes["u1"], "https://s.vn/")
        code_gong = next(c for c, u in codes.items() if u == "https://s.vn/gong/")
        res, _ = AR.write_targets(None, data, dict(PROV), opener=reply({"items": [
            {"kw": "kính cận", "url": "u2", "reason": "trang đang xếp hạng"},
            {"kw": "gọng kính", "url": code_gong, "reason": "danh mục"},
            {"kw": "lạ", "url": "u1"}, {"kw": "kính cận", "url": "u9"}]}))
        self.assertEqual([(x["kw"], x["url"]) for x in res["items"]],
                         [("kính cận", "https://s.vn/kinh-can/"), ("gọng kính", "https://s.vn/gong/")])
        self.assertIsNone(f["tu_khoa"][1]["volume"])  # volume < 10 không đưa số giả


class ActionsDiagTest(unittest.TestCase):
    def test_actions_types_and_order(self):
        f = AR.actions_facts([{"keyword": "a", "pos": "7"}, {"keyword": "b", "pos": "12"}])
        res, _ = AR.write_actions(None, f, dict(PROV), opener=reply({"items": [
            {"kw": "b", "actions": [{"type": "weird", "text": "Thêm FAQ"}]},
            {"kw": "a", "actions": [{"type": "internal", "text": "Đặt link từ trang chủ"}]},
            {"kw": "z", "actions": [{"type": "onpage", "text": "x"}]}]}))
        self.assertEqual([x["kw"] for x in res["items"]], ["a", "b"])
        self.assertEqual(res["items"][1]["actions"][0]["type"], "onpage")
        self.assertIn("[Link nội bộ] Đặt link từ trang chủ", AR.actions_text(res["items"]))

    def test_diag_needs_serp_and_flags_new_rivals(self):
        row = {"keyword": "kính cận", "pos": ">20", "prev_pos": "7"}
        now = {"date": "2026-11-08", "organic": [{"rank": 1, "domain": "a.vn", "url": "u"},
                                                  {"rank": 2, "domain": "new.vn", "url": "v"}]}
        before = {"date": "2026-11-05", "organic": [{"rank": 1, "domain": "a.vn", "url": "u"},
                                                     {"rank": 7, "domain": "s.vn", "url": "w"}]}
        f = AR.kw_facts(row, [now, before], "s.vn")
        self.assertEqual(f["website_moi_vao_top10"], ["new.vn"])
        with self.assertRaises(AR.AH.AIError):
            AR.write_diag(None, AR.kw_facts(row, [], "s.vn"), dict(PROV), opener=reply({}))
        res, _ = AR.write_diag(None, f, dict(PROV), opener=reply({
            "summary": "Rớt từ 7 ra ngoài top 20", "causes": [{"cause": "new.vn vượt lên", "evidence": "hạng 2"}],
            "fixes": ["Bổ sung bảng giá"]}))
        self.assertEqual(res["causes"][0]["cause"], "new.vn vượt lên")


if __name__ == "__main__":
    unittest.main()


class HistoryTest(unittest.TestCase):
    def test_history_newest_first_and_refs(self):
        import sqlite3

        from seo_report import ai_writer as AW
        con = sqlite3.connect(":memory:")
        for ref, h in (("set:1", "cũ"), ("set:2", "bộ khác"), ("set:1", "mới")):
            AW.save(con, "s", "rank_insight", ref, {"headline": h}, {"name": "Cổng", "model": "m"}, "a")
        self.assertEqual([x["headline"] for x in AW.history(con, "s", "rank_insight", ["set:1"])], ["mới", "cũ"])
        self.assertEqual(len(AW.history(con, "s", "rank_insight")), 3)
        self.assertEqual(AW.history(con, "s", "rank_insight", []), [])
