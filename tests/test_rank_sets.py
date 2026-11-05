"""Bộ từ khóa: mỗi tab một bộ, nơi check / lịch riêng, bộ Cam kết khớp sheet, biểu đồ tăng trưởng."""
import json
import unittest
from datetime import date

from seo_report import db
from seo_report import kpi as KP
from seo_report import rank as R
from seo_report.config import RankSettings
from tests.test_rank import END, SITE, TUE, FakeDataForSEO, run

HCM = 1028581


class SetsTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.s = RankSettings(monthly_budget_usd=20)

    def test_old_single_list_moves_into_sets_keeping_ids(self):
        con = db.connect(":memory:")
        con.executescript("""
            CREATE TABLE rank_keywords (id INTEGER PRIMARY KEY, site TEXT NOT NULL, keyword TEXT NOT NULL,
                url_id INTEGER, source TEXT NOT NULL, added_by TEXT NOT NULL, added_at TEXT NOT NULL,
                UNIQUE (site, keyword));
            CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);""")
        con.execute("INSERT INTO app_settings VALUES ('rank_schedule', ?)",
                    (json.dumps({"type": "weekdays", "weekdays": [1], "day": 1, "depth": 20}),))
        for i, kw in ((7, "tròng kính"), (9, "kính mát")):
            con.execute("INSERT INTO rank_keywords VALUES (?, ?, ?, NULL, 'kpi', 't', '2026-11-01')", (i, SITE, kw))
        KP.ensure_tables(con)
        KP.save(con, {"project": "x", "start": None, "months": [], "baseline": {}, "lines": [],
                      "keywords": [{"keyword": "Tròng kính", "url": "", "target": 3}]}, date(2026, 11, 1))
        R.ensure_tables(con)
        names = {x["name"]: x for x in R.sets(con, SITE)}
        self.assertEqual(set(names), {"Cam kết", "Từ khóa chính"})
        self.assertEqual(names["Cam kết"]["kind"], "kpi")
        self.assertEqual(names["Cam kết"]["schedule"]["depth"], 20)  # lịch chung cũ thành lịch của bộ
        kws = {k["keyword"]: k for k in R.keywords(con, SITE, END)}
        self.assertEqual((kws["tròng kính"]["id"], kws["tròng kính"]["set_name"]), (7, "Cam kết"))
        self.assertEqual((kws["kính mát"]["id"], kws["kính mát"]["set_name"]), (9, "Từ khóa chính"))

    def test_same_keyword_in_two_sets_checks_each_with_own_place(self):
        hn = R.create_set(self.con, SITE, "Hà Nội", "t", settings={"location_code": 1028580})
        hcm = R.create_set(self.con, SITE, "HCM", "t", settings={"location_code": HCM, "device": "desktop"})
        R.add_keywords(self.con, SITE, self.s, END, [("gọng kính", None)], "t", set_id=hn)
        R.add_keywords(self.con, SITE, self.s, END, [("gọng kính", None, 3)], "t", set_id=hcm)
        self.assertEqual(len(R.keywords(self.con, SITE, END)), 2)
        self.assertEqual(len(R.primary_keywords(self.con, SITE, END)), 1)
        fake = FakeDataForSEO({"gọng kính": [("vidushop.com", SITE)]})
        run(self.con, self.s, fake, TUE)
        got = sorted((t["location_code"], t["device"]) for t in fake.posted)
        self.assertEqual(got, [(1028580, "mobile"), (HCM, "desktop")])
        self.assertEqual(R.keywords(self.con, SITE, END, hcm)[0]["top_target"], 3)

    def test_schedule_per_set(self):
        a = R.create_set(self.con, SITE, "Hằng tuần", "t")
        b = R.create_set(self.con, SITE, "Thủ công", "t", schedule={"type": "manual"})
        R.add_keywords(self.con, SITE, self.s, END, [("a", None)], "t", set_id=a)
        R.add_keywords(self.con, SITE, self.s, END, [("b", None)], "t", set_id=b)
        self.assertEqual([k["keyword"] for k in R.due(self.con, SITE, END, TUE)], ["a"])
        self.assertIn("Thủ công: Chỉ khi bấm Check ngay", R.describe_sets(self.con, SITE))

    def test_create_rename_delete(self):
        a = R.create_set(self.con, SITE, "Blog", "t")
        with self.assertRaises(ValueError):
            R.create_set(self.con, SITE, "blog", "t")
        R.update_set(self.con, a, "t", name="Bài viết", settings={"device": "desktop"})
        st = R.get_set(self.con, a)
        self.assertEqual((st["name"], R.settings_for(self.s, st).device), ("Bài viết", "desktop"))
        R.add_keywords(self.con, SITE, self.s, END, [("a", None)], "t", set_id=a)
        R.delete_set(self.con, a, "t")
        self.assertEqual(R.sets(self.con, SITE), [])
        k = R.kpi_set(self.con, SITE, create=True)  # bộ Cam kết giờ cũng đổi tên / xóa được
        R.update_set(self.con, k["id"], "t", name="Cam kết 2026")
        self.assertEqual(R.get_set(self.con, k["id"])["name"], "Cam kết 2026")
        R.delete_set(self.con, k["id"], "t")
        self.assertEqual(R.sets(self.con, SITE), [])


class SetModelTest(unittest.TestCase):
    """Bộ đặt tên tự do, loại Cam kết / Theo dõi, Nháp → Chốt, lịch có giờ, dùng lại kết quả trùng, xóa vĩnh viễn."""

    def setUp(self):
        self.con = db.connect(":memory:")
        self.s = RankSettings(monthly_budget_usd=20)

    def test_draft_set_is_not_checked_until_locked(self):
        a = R.create_set(self.con, SITE, "Bổ trợ", "t", kind="kpi", state="draft")
        R.add_keywords(self.con, SITE, self.s, END, [("a", None)], "t", set_id=a)
        st = R.get_set(self.con, a)
        self.assertEqual((st["kind"], st["draft"]), ("kpi", True))
        self.assertEqual(R.due(self.con, SITE, END, TUE), [])
        fake = FakeDataForSEO({})
        self.assertEqual(R.post(self.con, SITE, self.s, fake, R.keywords(self.con, SITE, END), TUE,
                                lambda *_: None), 0)  # bấm Check trên bộ Nháp cũng không gửi
        R.lock_set(self.con, a, "t")
        self.assertEqual([k["keyword"] for k in R.due(self.con, SITE, END, TUE)], ["a"])
        R.update_set(self.con, a, "t", kind="custom")
        self.assertEqual(R.get_set(self.con, a)["kind"], "custom")

    def test_zero_budget_blocks_active_set_but_not_draft_or_paused_project(self):
        from dataclasses import replace
        broke = RankSettings(monthly_budget_usd=0)
        live = R.create_set(self.con, SITE, "Chạy", "t")
        draft = R.create_set(self.con, SITE, "Nháp", "t", state="draft")
        self.assertEqual(R.add_keywords(self.con, SITE, broke, END, [("a", None)], "t", set_id=live)["over_budget"],
                         ["a"])
        self.assertEqual(R.add_keywords(self.con, SITE, broke, END, [("a", None)], "t", set_id=draft)["added"], ["a"])
        paused = replace(broke, paused=True)
        self.assertEqual(R.add_keywords(self.con, SITE, paused, END, [("b", None)], "t", set_id=live)["added"], ["b"])

    def test_schedule_time(self):
        from datetime import datetime
        a = R.create_set(self.con, SITE, "Sáng", "t", schedule={"type": "weekdays", "weekdays": [1], "time": "9:30"})
        self.assertEqual(R.get_set(self.con, a)["schedule"]["time"], "09:30")
        self.assertIn("lúc 09:30", R.describe_sets(self.con, SITE))
        R.add_keywords(self.con, SITE, self.s, END, [("a", None)], "t", set_id=a)
        tue = datetime.combine(TUE, datetime.min.time())
        from datetime import timedelta
        kid = R.keywords(self.con, SITE, END)[0]["id"]  # đã check thứ Ba tuần trước
        self.con.execute("INSERT INTO rank_checks VALUES (?, ?, 10, 3, NULL, NULL, 0, 'x')",
                         (kid, (TUE - timedelta(days=7)).isoformat()))
        self.assertEqual(R.due(self.con, SITE, END, TUE, tue.replace(hour=9)), [])  # thứ Ba 9:00: chưa tới giờ
        self.assertEqual(len(R.due(self.con, SITE, END, TUE, tue.replace(hour=9, minute=30))), 1)
        with self.assertRaises(ValueError):
            R.update_set(self.con, a, "t", schedule={"type": "weekdays", "weekdays": [1], "time": "25:00"})
        # từ khóa mới thêm (chưa check lần nào) sau giờ theo lịch: chờ lần theo lịch sau, không check ngay
        R.add_keywords(self.con, SITE, self.s, END, [("mới", None)], "t", set_id=a)
        now = datetime.now()
        self.assertNotIn("mới", [k["keyword"] for k in R.due(self.con, SITE, END, now.date(), now)])

    def test_same_keyword_same_place_same_day_is_paid_once(self):
        a = R.create_set(self.con, SITE, "A", "t")
        b = R.create_set(self.con, SITE, "B", "t", schedule={"type": "manual"})
        R.add_keywords(self.con, SITE, self.s, END, [("gọng kính", None)], "t", set_id=a)
        R.add_keywords(self.con, SITE, self.s, END, [("gọng kính", f"{SITE}gong/")], "t", set_id=b)
        fake = FakeDataForSEO({"gọng kính": [("x.com", "https://x.com/"), ("vidushop.com", f"{SITE}gong/")]})
        run(self.con, self.s, fake, TUE)  # bộ A theo lịch
        self.assertEqual(len(fake.posted), 1)
        kb = R.keywords(self.con, SITE, END, b)[0]
        run(self.con, self.s, fake, TUE, only_ids=[kb["id"]])  # bộ B bấm Check cùng ngày: dùng lại
        self.assertEqual(len(fake.posted), 1)
        kb = R.keywords(self.con, SITE, END, b)[0]
        self.assertEqual((kb["rank"], kb["target_rank"]), (2, 2))  # URL mục tiêu riêng của bộ B
        self.assertEqual(self.con.execute("SELECT cost FROM rank_checks WHERE keyword_id = ?",
                                          (kb["id"],)).fetchone()[0], 0)
        both = R.keywords(self.con, SITE, END)
        R.purge_keywords(self.con, SITE, [k["id"] for k in both], "t")  # xóa chép: hôm sau gửi lại
        self.assertEqual(R.keywords(self.con, SITE, END), [])

    def test_hard_delete_keeps_month_cost(self):
        a = R.create_set(self.con, SITE, "A", "t")
        R.add_keywords(self.con, SITE, self.s, END, [("a", None), ("b", None)], "t", set_id=a)
        run(self.con, self.s, FakeDataForSEO({"a": [("vidushop.com", SITE)]}), TUE)
        spent = R.spent_this_month(self.con, TUE)
        ka = next(k for k in R.keywords(self.con, SITE, END) if k["keyword"] == "a")
        self.assertEqual(R.purge_stats(self.con, [ka["id"]])["checks"], 1)
        R.purge_keywords(self.con, SITE, [ka["id"]], "t")
        self.assertEqual([k["keyword"] for k in R.keywords(self.con, SITE, END)], ["b"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM rank_checks WHERE keyword_id = ?",
                                          (ka["id"],)).fetchone()[0], 0)
        self.assertAlmostEqual(R.spent_this_month(self.con, TUE), spent)  # tiền đã trả vẫn tính
        stats = R.delete_set(self.con, a, "t")
        self.assertEqual((stats["keywords"], R.sets(self.con, SITE)), (1, []))

    def test_kpi_set_follows_sheet(self):
        sheet = [{"keyword": "a", "url": "", "target": 3}, {"keyword": "b", "url": "", "target": None}]
        R.sync_kpi_set(self.con, SITE, self.s, END, sheet, "t")
        k = R.kpi_set(self.con, SITE)
        got = {x["keyword"]: x["top_target"] for x in R.keywords(self.con, SITE, END, k["id"])}
        self.assertEqual(got, {"a": 3, "b": None})
        other = R.create_set(self.con, SITE, "Blog", "t")
        R.add_keywords(self.con, SITE, self.s, END, [("b", None)], "t", set_id=other)
        # sheet đổi Top của a, bỏ b (đã có ở bộ Blog) và c mới; rồi bỏ a (không có ở bộ khác)
        res = R.sync_kpi_set(self.con, SITE, self.s, END, [{"keyword": "a", "url": "", "target": 5},
                                                          {"keyword": "c", "url": "", "target": None}], "t")
        self.assertEqual(res["moved"], ["b"])
        got = {x["keyword"]: x["top_target"] for x in R.keywords(self.con, SITE, END, k["id"])}
        self.assertEqual(got, {"a": 5, "c": None})
        R.sync_kpi_set(self.con, SITE, self.s, END, [{"keyword": "c", "url": "", "target": None}], "t")
        dropped = next(x for x in R.sets(self.con, SITE) if x["name"] == R.DROPPED_SET_NAME)
        self.assertEqual([x["keyword"] for x in R.keywords(self.con, SITE, END, dropped["id"])], ["a"])

    def test_growth_history(self):
        sid = R.create_set(self.con, SITE, "Bộ", "t")
        R.add_keywords(self.con, SITE, self.s, END, [("a", None, 3), ("b", None, 10), ("c", None)], "t", set_id=sid)
        ids = {k["keyword"]: k["id"] for k in R.keywords(self.con, SITE, END, sid)}
        for kw, d, r in (("a", "2026-10-06", 5), ("b", "2026-10-06", 12), ("c", "2026-10-06", None),
                         ("a", "2026-10-13", 2), ("b", "2026-10-13", 15)):
            self.con.execute("INSERT INTO rank_checks VALUES (?, ?, 30, ?, NULL, NULL, 0, '')", (ids[kw], d, r))
        h = R.set_history(self.con, SITE, sid)
        self.assertEqual([x["date"] for x in h], ["2026-10-06", "2026-10-13"])
        self.assertEqual((h[0]["top3"], h[0]["top5"], h[0]["top10"], h[0]["top30"], h[0]["out"], h[0]["avg"]),
                         (0, 1, 0, 1, 1, 8.5))
        self.assertEqual((h[1]["top3"], h[1]["up"], h[1]["down"], h[1]["same"]), (1, 1, 1, 1))  # c giữ lần trước
        self.assertEqual((h[1]["target_hit"], h[1]["target_total"]), (1, 2))
        # theo tuần: tuần 06/10 và 13/10, tuần 20/10 không check vẫn có điểm (giữ số tuần trước)
        w = R.set_history(self.con, SITE, sid, period="week", today=date(2026, 10, 21))
        self.assertEqual([x["label"] for x in w], ["Tuần 05/10", "Tuần 12/10", "Tuần 19/10"])
        self.assertEqual((w[2]["top3"], w[2]["up"], w[2]["down"]), (1, 0, 0))
        m = R.set_history(self.con, SITE, sid, period="month", today=date(2026, 11, 2))
        self.assertEqual([x["label"] for x in m], ["T10/2026", "T11/2026"])
        self.assertEqual((m[0]["top3"], m[0]["end"]), (1, "2026-10-31"))

    def test_growth_buckets_follow_check_depth(self):
        """Nhóm loại trừ nhau theo độ sâu thật: không thấy ở top 20 là "ngoài top 20", không phải ngoài top 30; hạng
        45 (check top 50) là thấy ở hạng 11 trở đi; từ khóa chưa check đếm riêng."""
        sid = R.create_set(self.con, SITE, "Sâu", "t")
        R.add_keywords(self.con, SITE, self.s, END, [("a", None), ("b", None), ("c", None), ("d", None)], "t",
                       set_id=sid)
        ids = {k["keyword"]: k["id"] for k in R.keywords(self.con, SITE, END, sid)}
        for kw, dep, r in (("a", 20, None), ("b", 50, 45), ("c", 10, 2)):
            self.con.execute("INSERT INTO rank_checks VALUES (?, '2026-10-06', ?, ?, NULL, NULL, 0, '')",
                             (ids[kw], dep, r))
        h = R.set_history(self.con, SITE, sid)[-1]
        self.assertEqual((h["top3"], h["top5"], h["top10"], h["top30"], h["out"], h["unchecked"]), (1, 0, 0, 1, 1, 1))
        self.assertEqual(h["top3"] + h["top5"] + h["top10"] + h["top30"] + h["out"] + h["unchecked"], 4)
        self.assertEqual(R.band_labels(h), ("Hạng 11 trở đi", "Ngoài top 20"))
        self.assertEqual(R.band_labels({"depths": [20], "out_depths": [20]}), ("Hạng 11–20", "Ngoài top 20"))
        self.assertEqual(R.band_labels({"depths": [10, 30], "out_depths": [10, 30]})[1],
                         "Không thấy trong độ sâu check")

    def test_dashboard_rank_snapshot_counts_like_rank_page(self):
        """Tổng quan đếm giống màn Thứ hạng: Top 3 / 5 / 10 trên tổng từ khóa; rớt khỏi độ sâu check vẫn là rớt hạng,
        vào lại top N là lên hạng; không còn "Top 30" đoán mò khi chỉ check top 10."""
        from seo_report.web_dashboard import rank_snapshot
        sid = R.create_set(self.con, SITE, "Bộ", "t")
        R.add_keywords(self.con, SITE, self.s, END, [("a", None), ("b", None), ("c", None), ("d", None)], "t",
                       set_id=sid)
        ids = {k["keyword"]: k["id"] for k in R.keywords(self.con, SITE, END, sid)}
        for kw, d, r in (("a", "2026-10-06", 5), ("a", "2026-10-13", None), ("b", "2026-10-06", None),
                         ("b", "2026-10-13", 8), ("c", "2026-10-06", 2), ("c", "2026-10-13", 2)):
            self.con.execute("INSERT INTO rank_checks VALUES (?, ?, 10, ?, NULL, NULL, 0, '')", (ids[kw], d, r))
        snap = rank_snapshot(self.con, SITE, END)
        self.assertEqual((snap["total"], snap["checked"]), (4, 3))
        self.assertEqual((snap["top3"], snap["top5"], snap["top10"]), (1, 1, 2))
        self.assertEqual((snap["up"], snap["down"]), (1, 1))
        self.assertNotIn("top30", snap)

    def test_budget_counts_each_set_schedule(self):
        a = R.create_set(self.con, SITE, "Tuần", "t", schedule={"depth": 10})
        b = R.create_set(self.con, SITE, "Tháng", "t", schedule={"type": "monthly", "depth": 10})
        R.add_keywords(self.con, SITE, self.s, END, [("a", None)], "t", set_id=a)
        R.add_keywords(self.con, SITE, self.s, END, [("a", None)], "t", set_id=b)
        st = R.budget_status(self.con, SITE, self.s, END)
        self.assertAlmostEqual(st["estimate"], 0.0006 * 30 / 7 + 0.0006 * 1)


class SheetRowPlanTest(unittest.TestCase):
    ROWS = [["Từ khóa", "URL mục tiêu", "Top target", "Ghi chú"],
            ["tròng kính", "https://x.vn/a/", "Top 3", "giữ nguyên"],
            ["kính mát", "", "", ""]]

    def test_update_only_touches_url_and_top_cells(self):
        p = KP.keyword_row_plan(self.ROWS, "upsert", "Tròng  Kính", "https://x.vn/b/", 5)
        self.assertEqual(p, {"action": "update", "row": 1, "cells": {1: "https://x.vn/b/", 2: "Top 5"}})

    def test_append_and_delete(self):
        p = KP.keyword_row_plan(self.ROWS, "upsert", "gọng kính", None, 10)
        self.assertEqual(p, {"action": "append", "values": ["gọng kính", "", "Top 10"]})
        self.assertEqual(KP.keyword_row_plan(self.ROWS, "delete", "kính mát"), {"action": "delete", "row": 2})
        self.assertEqual(KP.keyword_row_plan(self.ROWS, "delete", "không có"), {"action": "none"})

    def test_adds_top_column_when_missing(self):
        rows = [["Từ khóa", "URL mục tiêu"], ["a", ""]]
        self.assertEqual(KP.keyword_row_plan(rows, "upsert", "a", "", 3),
                         {"action": "header", "col": 2, "header_row": 0})


class CrudTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.s = RankSettings(monthly_budget_usd=20)
        self.a = R.create_set(self.con, SITE, "A", "t")
        self.b = R.create_set(self.con, SITE, "B", "t", settings={"device": "desktop"})
        R.add_keywords(self.con, SITE, self.s, END, [("x", None, 3), ("y", None)], "t", set_id=self.a)
        self.ids = {k["keyword"]: k["id"] for k in R.keywords(self.con, SITE, END, self.a)}

    def test_trash_and_restore_keep_history(self):
        self.con.execute("INSERT INTO rank_checks VALUES (?, '2026-10-06', 30, 4, NULL, NULL, 0, '')", (self.ids["x"],))
        R.remove_keywords(self.con, SITE, [self.ids["x"]], "t")
        self.assertEqual([k["keyword"] for k in R.keywords(self.con, SITE, END, self.a)], ["y"])
        self.assertEqual([k["keyword"] for k in R.keywords(self.con, SITE, END, self.a, removed=True)], ["x"])
        self.assertEqual(R.sets(self.con, SITE)[0]["count"], 1)
        R.add_keywords(self.con, SITE, self.s, END, [("x", None)], "t", set_id=self.a)  # thêm lại = khôi phục
        back = {k["keyword"]: k for k in R.keywords(self.con, SITE, END, self.a)}
        self.assertEqual((back["x"]["id"], back["x"]["rank"], back["x"]["top_target"]), (self.ids["x"], 4, 3))
        R.remove_keywords(self.con, SITE, [self.ids["y"]], "t")
        self.assertEqual(R.restore_keywords(self.con, SITE, [self.ids["y"]], "t"), 1)

    def test_pause_keyword_and_set(self):
        R.set_paused(self.con, SITE, [self.ids["x"]], True, "t")
        self.assertEqual([k["keyword"] for k in R.due(self.con, SITE, END, TUE)], ["y"])
        R.update_set(self.con, self.a, "t", paused=True)
        self.assertEqual(R.due(self.con, SITE, END, TUE), [])
        self.assertEqual(R.budget_status(self.con, SITE, self.s, END)["estimate"], 0)
        self.assertTrue(all(k["paused"] for k in R.keywords(self.con, SITE, END, self.a)))

    def test_move_copy_note_and_log(self):
        R.set_note(self.con, SITE, [self.ids["x"]], "viết lại bài", "t")
        c = R.copy_keywords(self.con, SITE, self.s, END, [self.ids["x"]], self.b, "t")
        self.assertEqual(c["added"], ["x"])
        copied = R.keywords(self.con, SITE, END, self.b)[0]
        self.assertEqual((copied["top_target"], copied["note"]), (3, "viết lại bài"))
        m = R.move_keywords(self.con, SITE, [self.ids["x"], self.ids["y"]], self.b, "t")
        self.assertEqual((m["moved"], m["skipped"]), (["y"], ["x"]))  # x đã có ở B
        in_b = {k["keyword"]: k["id"] for k in R.keywords(self.con, SITE, END, self.b)}
        self.assertEqual(in_b["y"], self.ids["y"])  # cùng dòng, giữ lịch sử
        actions = [x["action"] for x in R.keyword_log(self.con, SITE, "x")]
        self.assertIn("Ghi chú keyword", actions)
        self.assertNotIn("Chuyển keyword sang bộ B", actions)

    def test_events_and_delete_check(self):
        R.add_event(self.con, SITE, date(2026, 10, 10), "Google core update", "t")
        R.add_event(self.con, SITE, date(2026, 10, 12), "Đẩy backlink", "t", set_id=self.b)
        self.assertEqual([e["text"] for e in R.events(self.con, SITE, self.a)], ["Google core update"])
        self.assertEqual(len(R.events(self.con, SITE, self.b)), 2)
        R.delete_event(self.con, SITE, R.events(self.con, SITE, self.b)[1]["id"], "t")
        self.assertEqual(len(R.events(self.con, SITE, self.b)), 1)
        self.con.execute("INSERT INTO rank_checks VALUES (?, '2026-10-06', 30, 4, NULL, NULL, 0, '')", (self.ids["x"],))
        self.assertTrue(R.delete_check(self.con, SITE, self.ids["x"], "2026-10-06", "t"))
        self.assertEqual(R.history(self.con, self.ids["x"]), [])


class ProjectOverviewTest(unittest.TestCase):
    def test_overview_counts_each_keyword_once_and_competitors(self):
        from types import SimpleNamespace
        from seo_report import aio as AO
        from seo_report import rank_overview as RO
        con = db.connect(":memory:")
        s = RankSettings(monthly_budget_usd=20)
        a = R.create_set(con, SITE, "A", "t", kind="kpi")
        b = R.create_set(con, SITE, "B", "t")
        d = R.create_set(con, SITE, "Nháp", "t", state="draft")
        R.add_keywords(con, SITE, s, END, [("x", None), ("y", None)], "t", set_id=a)
        R.add_keywords(con, SITE, s, END, [("x", None)], "t", set_id=b)
        R.add_keywords(con, SITE, s, END, [("z", None)], "t", set_id=d)  # bộ Nháp không tính
        cfg = SimpleNamespace(site_url=SITE, keywords=SimpleNamespace(brand_terms=()), rank=s)
        AO.save_brand(con, SITE, "Rival", "", "rival.vn")
        fake = FakeDataForSEO({"x": [("rival.vn", "https://rival.vn/a"), ("vidushop.com", SITE)],
                               "y": [("vidushop.com", SITE), ("rival.vn", "https://rival.vn/b")]})
        run(con, s, fake, TUE)
        self.assertEqual(len(fake.posted), 2)  # x ở hai bộ cùng nơi check: một lần
        sm = RO.summary(con, SITE, END)
        self.assertEqual((sm["total"], sm["top3"]), (2, 2))
        rows = {r["name"]: r for r in RO.set_rows(con, SITE, END, s)}
        self.assertEqual((rows["B"]["top3"], rows["Nháp"]["cost"]), (1, 0.0))
        comp = RO.competitors(con, cfg, END)
        own, rival = comp["rows"]
        self.assertTrue(own["brand"]["own"])
        self.assertEqual((rival["present"], rival["ahead_count"], rival["avg"]), (2, 1, 1.5))
        self.assertAlmostEqual(own["visibility"], (RO.ctr(2) + RO.ctr(1)) / (2 * RO.CTR[1]))
        import io
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(RO.competitor_workbook(con, cfg, END)))
        self.assertEqual(wb.sheetnames, ["Vị trí theo từ khóa", "Kết quả Google", "Tổng quan đối thủ", "Ghi chú"])
        pos = list(wb["Vị trí theo từ khóa"].values)
        self.assertEqual(pos[0][8:10], (own["brand"]["name"], "Rival"))
        self.assertEqual(pos[0][1:3], ("Ý định chính", "Ý định khác"))
        # mọi bộ, kể cả từ khóa trùng ở bộ B (một dòng mỗi bộ); bộ Nháp không có
        self.assertEqual(sorted((r[0], r[3], r[8], r[9]) for r in pos[1:]),
                         [("x", "A", 2, 1), ("x", "B", 2, 1), ("y", "A", 1, 2)])
        self.assertEqual(len(list(wb["Kết quả Google"].values)) - 1, 6)
        # lần check sau: Rival rớt khỏi top 3 ở x, mình lên 1 → bảng xếp hạng đổi, có ▲▼ Top 3
        from datetime import timedelta
        fake.serps = {"x": [("vidushop.com", SITE), ("a.vn", "https://a.vn/"), ("b.vn", "https://b.vn/"),
                            ("rival.vn", "https://rival.vn/a")],
                      "y": [("vidushop.com", SITE), ("rival.vn", "https://rival.vn/b")]}
        run(con, s, fake, TUE + timedelta(days=7))
        comp = RO.competitors(con, cfg, END)
        rows = {r["brand"]["own"]: r for r in comp["rows"]}
        self.assertEqual((rows[True]["place"], rows[True]["move"], rows[False]["move"]), (1, 0, 0))
        self.assertEqual(rows[False]["delta"], {3: -1, 5: 0, 10: 0})
        self.assertEqual(rows[True]["delta"], {3: 0, 5: 0, 10: 0})
        # hạng trước = hạng hiện tại + bậc đã lên; hạng 1 không thể "xuống"
        self.assertTrue(all(r["move"] is None or r["place"] + r["move"] >= 1 for r in comp["rows"]))
        self.assertEqual((rows[False]["behind_count"], rows[False]["ahead_count"]), (2, 0))

