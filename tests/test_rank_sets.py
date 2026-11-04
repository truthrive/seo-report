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
        k = R.kpi_set(self.con, SITE, create=True)
        with self.assertRaises(ValueError):
            R.delete_set(self.con, k["id"], "t")

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
        self.assertEqual((h[0]["top3"], h[0]["top10"], h[0]["top30"], h[0]["out"], h[0]["avg"]), (0, 1, 1, 1, 8.5))
        self.assertEqual((h[1]["top3"], h[1]["up"], h[1]["down"], h[1]["same"]), (1, 1, 1, 1))  # c giữ lần trước
        self.assertEqual((h[1]["target_hit"], h[1]["target_total"]), (1, 2))

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
