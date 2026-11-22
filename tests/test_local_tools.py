import json
import sqlite3
import unittest
from datetime import date
from unittest import mock

from seo_report import gbp as G
from seo_report import gbp_reviews as GR


def rv(loc, rid, rating, created, reply=None, reply_at=None, comment="ok"):
    return {"location": loc, "id": rid, "author": "A", "rating": rating, "comment": comment, "created": created,
            "updated": created, "reply": reply, "reply_at": reply_at}


class SpecialHoursTest(unittest.TestCase):
    def test_merge_keeps_other_days_and_replaces_overlap(self):
        cur = [{"startDate": {"year": 2027, "month": 1, "day": 1}, "endDate": {"year": 2027, "month": 1, "day": 1},
                "closed": True},
               {"startDate": {"year": 2027, "month": 2, "day": 5}, "endDate": {"year": 2027, "month": 2, "day": 9},
                "closed": True}]
        out = G.merge_special(cur, "2027-02-06", "2027-02-07", "hours", "08:00", "12:30")
        self.assertEqual(len(out), 3)  # giữ 01/01, bỏ khoảng 05–09/02 bị trùng, thêm 2 ngày giờ khác
        self.assertEqual(out[1]["openTime"], {"hours": 8})
        self.assertEqual(out[2]["closeTime"], {"hours": 12, "minutes": 30})
        closed = G.merge_special(cur, "2027-02-05", "2027-02-09", "closed")
        self.assertEqual(closed[-1], {"startDate": {"year": 2027, "month": 2, "day": 5},
                                      "endDate": {"year": 2027, "month": 2, "day": 9}, "closed": True})
        self.assertEqual(len(G.merge_special(cur, "2027-01-01", "2027-01-01", "remove")), 1)
        with self.assertRaises(ValueError):
            G.merge_special(cur, "2027-02-09", "2027-02-01", "closed")
        with self.assertRaises(ValueError):
            G.merge_special(cur, "2027-02-01", "2027-02-01", "hours", "17:00", "08:00")

    def test_apply_special_per_branch(self):
        con = sqlite3.connect(":memory:")
        G.ensure_tables(con)
        con.execute("INSERT INTO gbp_locations (name, account, title, data, linked, added_by, added_at, fetched_at) "
                    "VALUES ('locations/1', 'accounts/9', 'A', '{}', 1, 'x', 'x', 'x')")

        class C:
            def location(self, name):
                if name == "locations/2":
                    raise RuntimeError("403 PERMISSION_DENIED")
                return {"title": "A", "specialHours": {"specialHourPeriods": []}}

            def set_special_hours(self, name, periods):
                self.sent = (name, periods)
        out = G.apply_special(con, C(), ["locations/1", "locations/2"], "2027-02-10", "2027-02-12", "closed")
        self.assertEqual(out["locations/1"], "")
        self.assertIn("quyền", out["locations/2"])
        data = json.loads(con.execute("SELECT data FROM gbp_locations").fetchone()[0])
        self.assertTrue(data["specialHours"]["specialHourPeriods"][0]["closed"])
        sp = G.special_periods(data, date(2027, 1, 1))
        self.assertEqual((sp[0]["start"], sp[0]["end"], sp[0]["closed"]), ("2027-02-10", "2027-02-12", True))


class ReviewToolsTest(unittest.TestCase):
    def test_clean_google_translation(self):
        self.assertEqual(GR.clean("Kính tệ\n\n(Translated by Google)\nThe glass is bad"), "Kính tệ")
        self.assertEqual(GR.clean("(Translated by Google) Good\n\n(Original)\nGood shop"), "Good shop")
        self.assertEqual(GR.clean(None), "")

    def test_voice_and_templates(self):
        con = sqlite3.connect(":memory:")
        self.assertEqual(len(GR.templates(con)), len(GR.DEFAULT_TEMPLATES))  # chưa lưu: mẫu mặc định
        self.assertGreaterEqual(len(GR.DEFAULT_TEMPLATES), 15)
        self.assertFalse([x["id"] for x in GR.DEFAULT_TEMPLATES if "chúng tôi" in x["text"].lower()])
        self.assertEqual({t["stars"] for t in GR.DEFAULT_TEMPLATES}, {"5", "4", "3", "low", "all"})
        v = GR.save_voice(con, {"brand": "Mắt Kính Tâm Đức", "self": "", "contact": "Zalo OA Tâm Đức",
                                "sign": "— Mắt Kính Tâm Đức"})
        self.assertEqual(v["self"], "")  # để trống: tự chọn theo loại cửa hàng
        self.assertEqual(GR.self_name(v), "shop")  # mắt kính → shop
        self.assertEqual(GR.self_name({"brand": "Nha khoa Tinh Hoa"}), "nha khoa")
        self.assertEqual(GR.self_name({"self": "chúng tôi", "brand": "ABC"}), "cửa hàng")  # mặc định cũ bị bỏ
        self.assertEqual(GR.self_name({"self": "Tâm Đức"}), "Tâm Đức")
        self.assertEqual(GR.fill("{xung} xin lỗi {khach}. {xung} sẽ gọi lại.", {"author": "Lê Bình"},
                                 "Nha khoa Tinh Hoa - Q1", {"customer": "anh/chị"}),
                         "Nha khoa xin lỗi anh/chị Bình. Nha khoa sẽ gọi lại.")
        saved = GR.save_templates(con, [{"name": "A", "stars": "low", "text": "Xin lỗi {khach}, liên hệ {lien_he}."},
                                        {"name": "rỗng", "stars": "5", "text": "  "}])
        self.assertEqual(len(saved), 1)  # mẫu trống bị bỏ
        low = GR.templates_for(GR.templates(con), 2)
        self.assertEqual(low[0]["name"], "A")
        txt = GR.fill(low[0]["text"], {"author": "Nguyễn Văn An"}, "Mắt Kính Tâm Đức - Gò Vấp", GR.voice(con))
        self.assertEqual(txt, "Xin lỗi anh/chị An, liên hệ Zalo OA Tâm Đức.\n— Mắt Kính Tâm Đức")

    def test_prompt_rules_by_stars_and_style(self):
        p1 = GR.draft_prompt("Tâm Đức", {"rating": 1, "author": "A", "comment": "Kính nứt sau 1 tuần, rất tệ"},
                             v={"contact": "hotline 1900"}, branch="Gò Vấp")
        self.assertIn("xin lỗi", p1)
        self.assertIn("hotline 1900", p1)
        self.assertIn("không emoji", p1)
        self.assertIn("KHÔNG dùng “chúng tôi”", p1)
        self.assertIn("tự xưng là “shop”", GR.draft_prompt("Mắt Kính Tâm Đức", {"rating": 5, "comment": "ok"}))
        p5 = GR.draft_prompt("Tâm Đức", {"rating": 5, "author": "B", "comment": ""})
        self.assertIn("chỉ chấm sao", p5)
        en = GR.draft_prompt("Tâm Đức", {"rating": 4, "author": "C", "comment": "Great service and nice frames"})
        self.assertIn("đúng ngôn ngữ", en)

    def test_queue_low_first(self):
        rs = [rv("L", "1", 5, "2026-11-10"), rv("L", "2", 2, "2026-10-01"), rv("L", "3", 1, "2026-11-01"),
              rv("L", "4", 5, "2026-11-12", reply="cảm ơn")]
        self.assertEqual([r["id"] for r in GR.queue(rs)], ["3", "2", "1"])

    def test_reply_speed(self):
        rs = [rv("L", "1", 5, "2026-11-01T00:00:00Z", "ok", "2026-11-03T00:00:00Z"),
              rv("L", "2", 5, "2026-11-02T00:00:00Z"),
              rv("M", "3", 4, "2026-11-05T00:00:00Z", "ok", "2026-11-05T06:00:00Z")]
        sp = GR.reply_speed(rs, today=date(2026, 11, 20))
        self.assertEqual(sp["L"]["median_days"], 2.0)
        self.assertEqual(sp["L"]["rate"], 0.5)
        self.assertEqual(sp["_all"]["total"], 3)

    def test_drafts_cleared_on_reply(self):
        con = sqlite3.connect(":memory:")
        GR.ensure_tables(con)
        con.execute("INSERT INTO gbp_reviews VALUES ('L', '1', 'A', 2, 'tệ', 'x', 'x', NULL, NULL, 'x')")
        GR.save_draft(con, "L", "1", "Xin lỗi anh/chị", "an")
        self.assertEqual(GR.drafts(con), {("L", "1"): "Xin lỗi anh/chị"})
        GR.mark_replied(con, "L", "1", "Xin lỗi anh/chị")
        self.assertEqual(GR.drafts(con), {})
        GR.save_draft(con, "L", "2", "Nháp mẫu", "an")
        GR.save_draft(con, "L", "2", "   ", "an")  # xóa hàng loạt nội dung đã điền: xóa luôn nháp
        self.assertEqual(GR.drafts(con), {})

    def test_analyze_parses_json(self):
        rs = [rv("L", str(i), 5 if i % 2 else 2, f"2026-11-{i + 1:02d}", comment=f"nội dung {i}") for i in range(10)]
        ans = ('Đây: {"summary": "Khách hài lòng", "praise": [{"topic": "Nhân viên nhiệt tình", "count": 5, '
               '"example": "rất nhiệt tình"}], "complaints": [{"topic": "Chờ lâu", "count": "3", "example": "đợi 30p", '
               '"branches": ["Q1"]}], "actions": ["Thêm nhân sự giờ cao điểm"]}')
        with mock.patch("seo_report.ai_http.ask", return_value=ans) as ask:
            out = GR.analyze({}, "Tâm Đức", rs, {"L": "Q1"})
        self.assertEqual(out["praise"][0]["topic"], "Nhân viên nhiệt tình")
        self.assertEqual(out["complaints"][0]["count"], 3)
        self.assertEqual(out["complaints"][0]["branches"], ["Q1"])
        self.assertEqual((out["sample"], out["low"]), (10, 5))
        self.assertIn("[Q1] 2★", ask.call_args[0][1])
        con = sqlite3.connect(":memory:")
        GR.save_insight(con, "all", out, "an")
        self.assertEqual(GR.insight(con, "all")["summary"], "Khách hài lòng")


if __name__ == "__main__":
    unittest.main()
