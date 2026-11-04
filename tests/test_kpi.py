import sqlite3
import unittest
from datetime import date, timedelta

from seo_report import kpi as KP
from seo_report import rank as R

SITE = "https://x.vn/"
TODAY = date(2027, 1, 20)
OLD_ROWS = [  # mẫu cũ: hàng "Tháng thứ dự án", 3 hàng top theo %, hàng traffic
    ["KPI cam kết SEO"],
    [],
    ["Tên dự án", "SEO x.vn"],
    ["Ngày bắt đầu", "01/11/2026"],
    [],
    ["Tháng thứ dự án", 1, 2, 3],
    ["Giai đoạn", "Review tối ưu nền tảng", "", "Thúc đẩy"],
    ["Số lượng từ khóa vào top 3 (cam kết)", "-%", "-", "50%"],
    ["Số lượng từ khóa vào top 5 (cam kết)", "-", "", 0.5],
    ["Số lượng từ khóa vào top 10 (cam kết)", "", "25%", 75],
    ["Traffic Session Organic Search (GA4)", "39,000", 39000, "59.348"],
]
NEW_ROWS = [  # mẫu mới: mỗi cam kết một dòng
    ["KPI cam kết SEO"],
    [],
    ["Tên dự án", "SEO x.vn"],
    ["Ngày bắt đầu", "01/11/2026", "dd/mm/yyyy"],
    ["Số tháng", 3],
    ["Baseline Organic Search", "1.000", "phiên/tháng"],
    ["Baseline AI Assistant", 50],
    [],
    ["Loại", "Nguồn / Bộ", "Đơn vị", 1, 2, 3, "Tổng"],
    ["Top 3", "Bộ riêng Top 3", "số từ khóa", "-", 1, 2, ""],
    ["Top 10", "Bộ chung", "%", "", "25%", 0.75, ""],
    ["Mức tháng", "Organic Search", "phiên", 1200, 1500, "2.000", ""],
    ["Tăng thêm cộng dồn", "Organic Search", "phiên", 500, 1000, 1500, "=SUM(D12:F12)"],
    ["Mức tháng", "AI Assistant", "phiên", "-", 80, 100, ""],
    [],
    ["Cách nhập:"],
    ["• ghi chú"],
]


def by_id(d: dict) -> dict:
    return {KP.line_id(ln): ln for ln in d["lines"]}


class ParseTest(unittest.TestCase):
    def test_parse_old_format(self):
        d = KP.parse_kpi(OLD_ROWS, TODAY)
        self.assertEqual((d["project"], d["start"], d["months"]), ("SEO x.vn", "2026-11-01", [1, 2, 3]))
        ln = by_id(d)
        self.assertEqual(list(ln), ["top3", "top5", "top10", "level:organic"])
        self.assertEqual((ln["top3"]["mode"], ln["top3"]["unit"]), ("shared", "pct"))
        self.assertEqual(ln["top3"]["targets"], {"1": None, "2": None, "3": 0.5})
        self.assertEqual((ln["top10"]["targets"]["2"], ln["top5"]["targets"]["3"]), (0.25, 0.5))
        self.assertEqual(ln["level:organic"]["targets"], {"1": 39000, "2": 39000, "3": 59348})
        self.assertEqual(d["baseline"], {"organic": None, "ai": None})

    def test_parse_new_format(self):
        d = KP.parse_kpi(NEW_ROWS, TODAY)
        self.assertEqual(d["months"], [1, 2, 3])                    # cột "Tổng" không phải tháng
        self.assertEqual(d["baseline"], {"organic": 1000, "ai": 50})
        ln = by_id(d)
        self.assertEqual(list(ln), ["top3", "top10", "level:organic", "cum:organic", "level:ai"])
        self.assertEqual((ln["top3"]["mode"], ln["top3"]["unit"], ln["top3"]["targets"]),
                         ("per_tier", "count", {"1": None, "2": 1, "3": 2}))
        self.assertEqual((ln["top10"]["mode"], ln["top10"]["unit"], ln["top10"]["targets"]),
                         ("shared", "pct", {"1": None, "2": 0.25, "3": 0.75}))
        self.assertEqual(ln["level:organic"]["targets"], {"1": 1200, "2": 1500, "3": 2000})
        self.assertEqual(ln["cum:organic"]["targets"], {"1": 500, "2": 1000, "3": 1500})
        self.assertEqual(ln["level:ai"]["targets"], {"1": None, "2": 80, "3": 100})

    def test_more_months_added_later(self):
        rows = [r[:] for r in OLD_ROWS]
        rows[5] = ["Tháng thứ dự án"] + list(range(1, 10))           # dự án kéo dài thành 9 tháng
        rows[9] = ["Số lượng từ khóa vào top 10 (cam kết)"] + ["-"] * 8 + ["70%"]
        d = KP.parse_kpi(rows, TODAY)
        self.assertEqual(d["months"], list(range(1, 10)))
        self.assertEqual(by_id(d)["top10"]["targets"]["9"], 0.7)

    def test_grid_roundtrip(self):
        d = KP.parse_kpi(NEW_ROWS, TODAY)
        d2 = KP.parse_kpi(KP.kpi_grid(d), TODAY)
        self.assertEqual(d2, d)
        self.assertEqual(KP.kpi_grid(d)[12][6], "=SUM(D13:F13)")    # dòng tích lũy có ô Tổng

    def test_keywords_dedup_and_header(self):
        kws = KP.parse_keywords([["Từ khóa", "URL mục tiêu"], ["kính A", "https://x.vn/a/"], ["Kính A", ""],
                                 ["kính B"], ["", "x"]])
        self.assertEqual(kws, [{"keyword": "kính A", "url": "https://x.vn/a/", "target": None},
                               {"keyword": "kính B", "url": "", "target": None}])

    def test_keywords_by_header_with_top_target(self):
        kws = KP.parse_keywords([["Ghi chú", "Từ khóa", "Top target", "URL mục tiêu"],
                                 ["", "kính A", "Top 3", "https://x.vn/a/"], ["x", "kính B", 10, ""],
                                 ["", "kính C", "", ""]])
        self.assertEqual([(k["keyword"], k["target"], k["url"]) for k in kws],
                         [("kính A", 3, "https://x.vn/a/"), ("kính B", 10, ""), ("kính C", None, "")])

    def test_month_window(self):
        self.assertEqual(KP.month_window(date(2026, 11, 1), 1), (date(2026, 11, 1), date(2026, 11, 30)))
        self.assertEqual(KP.month_window(date(2026, 11, 1), 3), (date(2027, 1, 1), date(2027, 1, 31)))
        self.assertEqual(KP.month_window(date(2026, 1, 31), 2), (date(2026, 2, 28), date(2026, 3, 30)))

    def test_upgrade_old_saved_version(self):
        old = {"project": "P", "start": "2026-11-01", "keywords": [],
               "months": [{"n": 1, "phase": "a", "top3": None, "top5": 0.1, "top10": 0.2, "sessions": 100}]}
        d = KP._upgrade(old)
        self.assertEqual(d["months"], [1])
        self.assertEqual(by_id(d)["top5"]["targets"], {"1": 0.1})
        self.assertEqual(by_id(d)["level:organic"]["targets"], {"1": 100})


def daily(per_day):
    return lambda src, s, e: {(s + timedelta(days=i)).isoformat(): per_day[src] for i in range((e - s).days + 1)}


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        R.ensure_tables(self.con)
        self.ids = {}
        sid = self.con.execute("INSERT INTO rank_sets (site, name, kind, schedule, created_by, created_at) "
                               "VALUES (?, 'Cam kết', 'kpi', '{}', 't', '2026-11-01')", (SITE,)).lastrowid
        for kw in ("a", "b", "c", "d"):
            cur = self.con.execute("INSERT INTO rank_keywords (site, keyword, url_id, source, added_by, added_at, "
                                   "set_id) VALUES (?, ?, NULL, 'kpi', 't', '2026-11-01', ?)", (SITE, kw, sid))
            self.ids[kw] = cur.lastrowid
        self.keywords = [{"keyword": k, "url": "", "target": t} for k, t in
                         (("a", 3), ("b", 3), ("c", 10), ("d", None))]

    def tearDown(self):
        self.con.close()

    def save(self, rows, day=date(2026, 11, 1)):
        data = KP.parse_kpi(rows, TODAY)
        data["keywords"] = self.keywords
        return KP.save(self.con, data, day)

    def check(self, kw, day, rank):
        self.con.execute("INSERT INTO rank_checks VALUES (?, ?, 30, ?, NULL, NULL, 0, ?)",
                         (self.ids[kw], day, rank, day))

    def test_old_format_last_check_in_month_and_sessions(self):
        self.save(OLD_ROWS)
        self.check("a", "2027-01-05", 15)
        self.check("a", "2027-01-15", 2)   # lần cuối trong tháng 3 → top 3
        self.check("b", "2027-01-15", 4)
        self.check("c", "2026-12-20", 1)   # check ở tháng 2, tháng 3 chưa check → chưa đạt
        p = KP.progress(self.con, SITE, TODAY, daily({"organic": 1000}))
        self.assertEqual(p["current"], 3)
        self.assertEqual([KP.line_id(ln) for ln in p["lines"]], ["top3", "top5", "top10", "level:organic"])
        m3 = p["months"][2]
        ch = m3["checks"]
        self.assertEqual((ch["top3"]["count"], ch["top5"]["count"], ch["top10"]["count"], m3["rank"]["checked"]),
                         (1, 2, 2, 2))
        self.assertEqual((ch["top3"]["need"], ch["top3"]["gap"], ch["top3"]["ok"], ch["top3"]["total"]),
                         (2, 1, False, 4))
        self.assertEqual((ch["top5"]["ok"], ch["top10"]["gap"]), (True, 1))
        lv = ch["level:organic"]
        self.assertEqual((lv["actual"], lv["forecast"]), (19000, 31000))   # 01/01 → 19/01 (hôm qua); 1000/ngày × 31
        self.assertFalse(lv["ok"])                                          # dự báo 31.000 < cam kết 59.348
        self.assertEqual((m3["rank"]["target_set"], m3["rank"]["target_ok"]), (3, 1))  # a đạt top 3, b hạng 4
        items = {x["keyword"]: x["ok"] for x in m3["rank"]["items"]}
        self.assertEqual(items, {"a": True, "b": False, "c": False, "d": None})
        m1 = p["months"][0]
        self.assertEqual(m1["status"], "closed")
        self.assertIsNone(m1["checks"]["top10"]["ok"])    # tháng không cam kết: không chấm
        self.assertEqual(KP.status(m1["checks"]["top10"], False), ("Tháng này không cam kết", "grey"))
        self.assertEqual(KP.status(ch["top3"], True), ("Thiếu 1 từ khóa", "amber"))

    def test_new_format_per_tier_count_level_and_cumulative(self):
        self.save(NEW_ROWS)
        self.check("a", "2027-01-15", 2)   # bộ Top 3 = {a, b}: a đạt, b chưa check
        self.check("c", "2027-01-15", 8)
        self.check("d", "2027-01-15", 30)
        p = KP.progress(self.con, SITE, TODAY, daily({"organic": 100, "ai": 3}))
        self.assertEqual([KP.line_id(ln) for ln in p["lines"]],
                         ["top3", "top10", "level:organic", "cum:organic", "level:ai"])
        m1, m2, m3 = p["months"]
        # Top 3 bộ riêng: mẫu số 2 từ khóa, cam kết 2 từ → thiếu 1; tỷ lệ cam kết quy ra 100%
        t3 = m3["checks"]["top3"]
        self.assertEqual((t3["total"], t3["count"], t3["need"], t3["target_pct"], t3["ok"], t3["gap"]),
                         (2, 1, 2, 1.0, False, 1))
        # Top 10 bộ chung: 4 từ khóa, 75% → cần 3, có 2 (a, c)
        t10 = m3["checks"]["top10"]
        self.assertEqual((t10["total"], t10["count"], t10["need"], t10["actual"], t10["ok"]), (4, 2, 3, 0.5, False))
        self.assertEqual(KP.describe(by_id(p)["top10"], t10, True)["actual"],
                         "50% (2/4 từ khóa)")
        # Tháng 1, 2 đã chốt: 100 phiên/ngày → tháng 11 = 3.000, tháng 12 = 3.100
        self.assertEqual((m1["checks"]["level:organic"]["actual"], m1["checks"]["level:organic"]["ok"]), (3000, True))
        c1, c2, c3 = (m["checks"]["cum:organic"] for m in (m1, m2, m3))
        self.assertEqual((c1["actual"], c1["cum"], c1["plan_cum"], c1["total"], c1["ok"]), (2000, 2000, 500, 3000, True))
        self.assertEqual((c2["actual"], c2["cum"], c2["plan_cum"], c2["ok"]), (2100, 4100, 1500, True))
        # Tháng 3 đang chạy: 19 ngày × 100 = 1.900, dự báo 3.100 → tăng thêm dự báo 2.100, lũy kế 6.200 ≥ 3.000
        self.assertEqual((c3["actual"], c3["forecast_inc"], c3["cum"], c3["ok"]), (900, 2100, 6200, True))
        self.assertEqual((m2["checks"]["level:ai"]["actual"], m2["checks"]["level:ai"]["ok"]), (93, True))
        self.assertIsNone(m1["checks"]["level:ai"]["ok"])  # tháng 1 AI không cam kết

    def test_cumulative_counts_months_below_baseline(self):
        self.save(NEW_ROWS)
        p = KP.progress(self.con, SITE, TODAY, daily({"organic": 20, "ai": 0}))  # 600/tháng < baseline 1.000
        c1, c2 = (m["checks"]["cum:organic"] for m in p["months"][:2])
        self.assertEqual((c1["actual"], c1["cum"], c1["ok"]), (-400, -400, False))
        self.assertEqual((c2["cum"], c2["gap"]), (-780, 2280))
        self.assertEqual(KP.status(c2, False), ("Lũy kế thiếu 2.280 phiên", "red"))

    def test_cumulative_without_baseline_or_ga4(self):
        rows = [r[:] for r in NEW_ROWS]
        rows[5] = ["Baseline Organic Search", ""]
        self.save(rows)
        p = KP.progress(self.con, SITE, TODAY, daily({"organic": 100, "ai": 3}))
        c = p["months"][0]["checks"]["cum:organic"]
        self.assertEqual((c["baseline"], c["actual"], c["ok"]), (None, None, None))
        self.assertEqual(KP.status(c, False), ("Chưa nhập baseline", "grey"))
        p = KP.progress(self.con, SITE, TODAY, None)
        self.assertEqual(p["months"][0]["checks"]["level:organic"]["actual"], None)  # chưa kết nối GA4: không hiện 0

    def test_closed_month_uses_version_at_month_end(self):
        self.save(OLD_ROWS)
        # Điều chỉnh KPI giữa tháng 3: tháng 2 (đã chốt) vẫn chấm theo bản cũ
        data = KP.parse_kpi(OLD_ROWS, TODAY)
        by_id(data)["top10"]["targets"]["2"] = 0.9
        data["keywords"] = [{"keyword": k, "url": ""} for k in ("a", "b", "c", "d")]
        self.assertTrue(KP.save(self.con, data, date(2027, 1, 10)))
        self.assertFalse(KP.save(self.con, data, date(2027, 1, 11)))  # không đổi thì không lưu thêm
        p = KP.progress(self.con, SITE, TODAY, None)
        self.assertEqual(p["months"][1]["targets"]["top10"], 0.25)
        self.assertEqual(p["months"][2]["targets"]["top10"], 0.75)

    def test_old_saved_version_is_not_resaved(self):
        import json
        old = {"project": "SEO x.vn", "start": "2026-11-01", "keywords": self.keywords,
               "months": [{"n": n, "phase": "", "top3": t3, "top5": t5, "top10": t10, "sessions": s} for n, t3, t5, t10, s
                          in ((1, None, None, None, 39000), (2, None, None, 0.25, 39000), (3, 0.5, 0.5, 0.75, 59348))]}
        KP.ensure_tables(self.con)
        self.con.execute("INSERT INTO kpi_versions (day, synced_at, data, sheet) VALUES ('2026-11-01', 'x', ?, NULL)",
                         (json.dumps(old, ensure_ascii=False),))
        self.assertFalse(self.save(OLD_ROWS, date(2027, 1, 10)))     # cùng nội dung sau khi nâng cấu trúc
        self.assertEqual(len(KP.versions(self.con)), 1)

    def test_template_roundtrip(self):
        import io

        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(KP.template_xlsx("SEO x.vn", [("kính A", "https://x.vn/a/")])))
        rows = [list(r) for r in wb[KP.KPI_TAB].iter_rows(values_only=True)]
        d = KP.parse_kpi(rows, TODAY)
        self.assertEqual(by_id(d)["top10"]["targets"], {str(i): v for i, v in
                                                        enumerate([None, None, 0.34, 0.40, 0.49, 0.63], start=1)})
        self.assertEqual(by_id(d)["level:organic"]["targets"]["6"], 71228)
        self.assertIsNone(d["start"])
        kws = KP.parse_keywords([list(r) for r in wb[KP.KW_TAB].iter_rows(values_only=True)])
        self.assertEqual(kws, [{"keyword": "kính A", "url": "https://x.vn/a/", "target": None}])


class JudgeTest(unittest.TestCase):
    LEVEL = {"kind": "level", "source": "organic", "targets": {"3": 39000}}

    def test_running_month_without_forecast_is_not_judged(self):
        row = {"n": 3, "status": "running", "sessions": {"organic": 382}, "forecast": {}, "days_done": 1,
               "days_total": 30}
        ch = KP._judge(self.LEVEL, row)
        self.assertIsNone(ch["ok"])
        self.assertEqual(ch["expected"], 1300)
        self.assertEqual(KP.status(ch, True), ("Chưa đủ ngày để dự báo", "grey"))

    def test_running_month_judged_on_forecast(self):
        row = {"n": 3, "status": "running", "sessions": {"organic": 4000}, "forecast": {"organic": 40000},
               "days_done": 3, "days_total": 30}
        self.assertTrue(KP._judge(self.LEVEL, row)["ok"])

    def test_rank_need_and_describe_both_units(self):
        pct = {"kind": "rank", "top": 3, "mode": "shared", "unit": "pct"}
        cnt = {"kind": "rank", "top": 3, "mode": "per_tier", "unit": "count"}
        self.assertEqual(KP.rank_need(pct, 0.4, 40), (16, 0.4))
        self.assertEqual(KP.rank_need(cnt, 16, 40), (16, 0.4))
        self.assertEqual(KP.rank_need(cnt, 16, 0), (16, None))
        self.assertEqual(KP.rank_need(pct, None, 40), (None, None))
        items = [{"target": 3, "rank": r, "date": "d"} for r in (1, 2, 5, None)]
        row = {"n": 1, "status": "closed", "rank": {"items": items}, "sessions": {}, "forecast": {}}
        d = KP.describe({**pct, "targets": {"1": 0.4}}, KP._judge({**pct, "targets": {"1": 0.4}}, row), False)
        self.assertEqual((d["target"], d["actual"], d["status"]), ("40% (2 từ khóa)", "50% (2/4 từ khóa)", "Đạt"))
        d = KP.describe({**cnt, "targets": {"1": 3}}, KP._judge({**cnt, "targets": {"1": 3}}, row), False)
        self.assertEqual((d["target"], d["actual"], d["status"]),
                         ("3 từ khóa (75%)", "50% (2/4 từ khóa)", "Thiếu 1 từ khóa"))


class WizardTest(unittest.TestCase):
    SPEC = {"project": "SEO x.vn", "start": "2026-12-01", "months": 6, "baseline": {"organic": 5000, "ai": 120},
            "rank": {"tops": [3, 10], "mode": "per_tier", "unit": "pct", "from": 3, "finals": {"3": 0.2, "10": 0.6}},
            "traffic": {"organic": {"level": 10000, "cum": 10000}, "ai": {"level": 480, "cum": None}}}

    def test_plan_spreads_targets(self):
        d = KP.plan(self.SPEC)
        ln = by_id(d)
        self.assertEqual(list(ln), ["top3", "top10", "level:organic", "cum:organic", "level:ai"])
        self.assertEqual(ln["top3"]["targets"], {"1": None, "2": None, "3": 0.05, "4": 0.1, "5": 0.15, "6": 0.2})
        self.assertEqual((ln["top3"]["mode"], ln["top3"]["unit"]), ("per_tier", "pct"))
        self.assertEqual(ln["level:organic"]["targets"]["6"], 15000)      # baseline + mức tăng
        self.assertEqual(ln["level:organic"]["targets"]["1"], 6667)
        self.assertEqual(sum(ln["cum:organic"]["targets"].values()), 10000)  # tổng các ô = cam kết tích lũy
        self.assertEqual(ln["level:ai"]["targets"], {str(i): v for i, v in enumerate((200, 280, 360, 440, 520, 600), 1)})
        self.assertEqual(KP.parse_kpi(KP.kpi_grid(d), TODAY), d)   # ghi ra tab rồi đọc lại ra đúng dữ liệu

    def test_plan_without_finals_or_rank(self):
        d = KP.plan({"project": "P", "months": 3, "rank": {"tops": [5], "unit": "count"}, "traffic": {}})
        self.assertEqual(by_id(d)["top5"]["targets"], {"1": None, "2": None, "3": None})
        self.assertEqual(KP.plan({"months": 2})["lines"], [])
        self.assertEqual(KP.split_total(10, 3), [3, 3, 4])
        self.assertEqual(KP.spread(0.6, 4), [0.15, 0.3, 0.45, 0.6])
        self.assertEqual(KP.spread(16, 3, 0, integer=True), [5, 11, 16])

    def test_baseline_three_full_months_before_start(self):
        calls = []

        def fn(src, s, e):
            calls.append((src, s.isoformat(), e.isoformat()))
            return {s.isoformat(): 300 if src == "organic" else 30, e.isoformat(): 0}
        b = KP.baseline_suggest(fn, date(2026, 12, 15))
        self.assertEqual([m["label"] for m in b["months"]], ["09/2026", "10/2026", "11/2026"])
        self.assertIn(("organic", "2026-09-01", "2026-09-30"), calls)
        self.assertIn(("ai", "2026-11-01", "2026-11-30"), calls)
        self.assertEqual((b["organic"], b["ai"]), (300, 30))

    def test_keyword_text_and_sheet_values(self):
        kws = KP.parse_keyword_text("kính A | https://x.vn/a/ | Top 3\nkính B\tTop 10\n# bỏ\nKÍNH A\n\nkính C | 5")
        self.assertEqual(kws, [("kính A", "https://x.vn/a/", 3), ("kính B", "", 10), ("kính C", "", 5)])
        v = KP.sheet_values(KP.plan(self.SPEC), kws)
        self.assertEqual(v[KP.KW_TAB][0], ["Từ khóa", "URL mục tiêu", "Top target", "Ghi chú"])
        self.assertEqual(v[KP.KW_TAB][1], ["kính A", "https://x.vn/a/", "Top 3", ""])
        self.assertEqual(KP.parse_keywords(v[KP.KW_TAB])[1], {"keyword": "kính B", "url": "", "target": 10})
        self.assertEqual(v[KP.KPI_TAB][8][:3], ["Loại", "Nguồn / Bộ", "Đơn vị"])

    def test_format_requests_percent_rows_only(self):
        rows = KP.kpi_grid(KP.plan(self.SPEC))
        reqs = KP._format_requests({"sheetId": 7}, rows, True)
        fmts = [r["repeatCell"]["cell"]["userEnteredFormat"].get("numberFormat", {}).get("type")
                for r in reqs if "repeatCell" in r and "numberFormat" in r["repeatCell"]["cell"]["userEnteredFormat"]]
        self.assertEqual(fmts, ["PERCENT", "PERCENT", "NUMBER", "NUMBER", "NUMBER"])
        self.assertTrue(all(r["repeatCell"]["range"]["sheetId"] == 7 for r in reqs if "repeatCell" in r))

    def test_template_from_plan_roundtrip(self):
        import io

        from openpyxl import load_workbook
        d = KP.plan(self.SPEC)
        wb = load_workbook(io.BytesIO(KP.template_xlsx("SEO x.vn", [("kính A", "https://x.vn/a/", 3)], d)))
        got = KP.parse_kpi([list(r) for r in wb[KP.KPI_TAB].iter_rows(values_only=True)], TODAY)
        self.assertEqual(got["baseline"], {"organic": 5000, "ai": 120})
        self.assertEqual(by_id(got)["cum:organic"]["targets"], by_id(d)["cum:organic"]["targets"])
        kws = KP.parse_keywords([list(r) for r in wb[KP.KW_TAB].iter_rows(values_only=True)])
        self.assertEqual(kws, [{"keyword": "kính A", "url": "https://x.vn/a/", "target": 3}])

    def test_workbook_from_master_replaces_kpi_tabs_and_sets_start(self):
        import io

        from openpyxl import Workbook, load_workbook
        wb = Workbook()
        okr = wb.active
        okr.title = "OKRs 3 tháng"
        okr["M1"], okr["O2"] = "Bắt đầu →", '=IF($N$1="","",$N$1)'
        wb.create_sheet("Weekly Task Tracker")["A1"] = "Ngày"
        wb.create_sheet("Bản sao của KPI cam kết")["A1"] = "cũ"
        buf = io.BytesIO()
        wb.save(buf)
        d = KP.plan(self.SPEC)
        out = load_workbook(io.BytesIO(KP.workbook_from_master(buf.getvalue(), d, [("kính A", "", 3)])))
        self.assertEqual(out.sheetnames, ["OKRs 3 tháng", "Weekly Task Tracker", KP.KPI_TAB, KP.KW_TAB])
        self.assertEqual(out["OKRs 3 tháng"]["N1"].value.date(), date(2026, 12, 1))   # ô cạnh "Bắt đầu →"
        self.assertEqual(out["OKRs 3 tháng"]["O2"].value, '=IF($N$1="","",$N$1)')
        got = KP.parse_kpi([list(r) for r in out[KP.KPI_TAB].iter_rows(values_only=True)], TODAY)
        self.assertEqual(by_id(got)["level:ai"]["targets"], by_id(d)["level:ai"]["targets"])
        self.assertEqual(out[KP.KW_TAB]["C2"].value, 3)

    def test_unlink_sheet_keeps_versions_of_old_sheet(self):
        con = sqlite3.connect(":memory:")
        KP.set_sheet(con, "https://docs.google.com/spreadsheets/d/1Zv0NHbM71a80uvshJ-NNGoB8YTxp_RXCZ1O/edit")
        KP.save(con, KP.plan(WizardTest.SPEC), TODAY)
        self.assertEqual(len(KP.versions(con)), 1)
        self.assertEqual(KP.unlink_sheet(con), "1Zv0NHbM71a80uvshJ-NNGoB8YTxp_RXCZ1O")
        self.assertEqual((KP.sheet_id(con), KP.sync_info(con), KP.versions(con)), ("", None, []))
        KP.set_sheet(con, "1Zv0NHbM71a80uvshJ-NNGoB8YTxp_RXCZ1O")   # gắn lại link cũ: phiên bản cũ dùng tiếp
        self.assertEqual(len(KP.versions(con)), 1)


class ScopeTest(unittest.TestCase):
    def test_wider_scope_covers_narrower(self):
        from seo_report import auth as A
        full = [A.GSC_SCOPE, A.GA4_SCOPE, A.DRIVE_FULL_SCOPE, A.SHEETS_WRITE_SCOPE]
        self.assertEqual(A.missing_scopes(full, (A.DRIVE_SCOPE, A.SHEETS_SCOPE, A.SHEETS_WRITE_SCOPE)), [])
        old = [A.GSC_SCOPE, A.DRIVE_SCOPE, A.SHEETS_SCOPE]
        self.assertEqual(A.missing_scopes(old, (A.DRIVE_SCOPE, A.SHEETS_SCOPE)), [])   # token cũ vẫn đọc / xuất được
        self.assertEqual(A.missing_scopes(old, (A.DRIVE_FULL_SCOPE, A.SHEETS_WRITE_SCOPE)),
                         [A.DRIVE_FULL_SCOPE, A.SHEETS_WRITE_SCOPE])


class MasterSheetTest(unittest.TestCase):
    def test_master_sheet_setting(self):
        from seo_report import projects as PJ
        con = sqlite3.connect(":memory:")
        self.assertEqual(PJ.master_sheet(con), "")
        sid = PJ.set_master_sheet(con, "https://docs.google.com/spreadsheets/d/1Zv0NHbM71a80uvshJ-NNGoB8YTxp_RXCZ1O/edit#gid=1")
        self.assertEqual(sid, "1Zv0NHbM71a80uvshJ-NNGoB8YTxp_RXCZ1O")
        self.assertEqual(PJ.master_sheet(con), sid)
        with self.assertRaises(ValueError):
            PJ.set_master_sheet(con, "abc")
        self.assertEqual(PJ.set_master_sheet(con, ""), "")


class EditTest(unittest.TestCase):
    def test_keyword_text_roundtrip(self):
        kws = [("kính A", "https://x.vn/a/", 3), ("kính B", "", None), ("kính C", "", 10)]
        text = KP.keyword_text(kws)
        self.assertEqual(text.splitlines(), ["kính A | https://x.vn/a/ | Top 3", "kính B", "kính C | Top 10"])
        self.assertEqual(KP.parse_keyword_text(text), kws)
        self.assertEqual(KP.keyword_text([{"keyword": "k", "url": "", "target": 5}]), "k | Top 5")

    def test_fingerprint_changes_with_content(self):
        a = {KP.KPI_TAB: NEW_ROWS, KP.KW_TAB: [["Từ khóa"], ["a"]]}
        b = {KP.KPI_TAB: NEW_ROWS, KP.KW_TAB: [["Từ khóa"], ["b"]]}
        self.assertEqual(KP.fingerprint(a), KP.fingerprint(dict(a)))
        self.assertNotEqual(KP.fingerprint(a), KP.fingerprint(b))

    def test_load_for_edit_detects_old_format(self):
        from unittest import mock
        with mock.patch.object(KP, "fetch", return_value={KP.KPI_TAB: OLD_ROWS, KP.KW_TAB: [["Từ khóa", "URL mục tiêu"],
                                                                                            ["a", "https://x.vn/"]]}):
            ld = KP.load_for_edit(None, "sid", TODAY)
        self.assertTrue(ld["old_format"])
        self.assertEqual(ld["keywords"], [("a", "https://x.vn/", None)])
        self.assertEqual([KP.line_id(ln) for ln in ld["data"]["lines"]], ["top3", "top5", "top10", "level:organic"])
        with mock.patch.object(KP, "fetch", return_value={KP.KPI_TAB: NEW_ROWS}):
            self.assertFalse(KP.load_for_edit(None, "sid", TODAY)["old_format"])

    def test_write_sheet_refuses_when_sheet_changed_unless_forced(self):
        from unittest import mock

        from seo_report import auth
        before = {KP.KPI_TAB: NEW_ROWS, KP.KW_TAB: []}
        after = {KP.KPI_TAB: NEW_ROWS, KP.KW_TAB: [["Từ khóa"], ["mới"]]}
        creds = mock.Mock(scopes=[auth.SHEETS_WRITE_SCOPE])
        written = []
        with mock.patch.object(auth, "get_credentials", return_value=creds), \
                mock.patch.object(KP, "fetch", return_value=after), \
                mock.patch.object(KP, "write_tabs", side_effect=lambda sh, sid, values: written.append(values)), \
                mock.patch("googleapiclient.discovery.build", return_value=object()):
            d = KP.plan(WizardTest.SPEC)
            with self.assertRaises(KP.SheetChanged):
                KP.write_sheet(None, "sid", d, [], expect=KP.fingerprint(before))
            self.assertEqual(written, [])
            fp = KP.write_sheet(None, "sid", d, [("k", "", 3)], expect=KP.fingerprint(before), force=True)
            self.assertEqual(fp, KP.fingerprint(after))
            self.assertEqual(written[0][KP.KW_TAB][1], ["k", "", "Top 3", ""])
            KP.write_sheet(None, "sid", d, [], expect=KP.fingerprint(after))   # không đổi: ghi bình thường
            self.assertEqual(len(written), 2)


class ParentFolderTest(unittest.TestCase):
    """Folder gốc của dự án nằm trong folder cha ([drive] parent_folder) khi có; thiếu quyền thì không hỏng."""

    class FakeSvc:
        def __init__(self, parents=None, fail=None):
            self.parents, self.fail, self.calls = parents or {}, fail, []

        def files(self):
            return self

        def create(self, body, fields):
            self.calls.append(("create", body))
            if self.fail == "create":
                from googleapiclient.errors import HttpError
                raise HttpError(type("R", (), {"status": 404, "reason": "x"})(), b"")
            self.parents["new"] = list(body.get("parents", []))
            return type("Q", (), {"execute": lambda s: {"id": "new"}})()

        def get(self, fileId, fields):
            if fileId not in self.parents:
                from googleapiclient.errors import HttpError
                raise HttpError(type("R", (), {"status": 404, "reason": "x"})(), b"")
            return type("Q", (), {"execute": lambda s: {"id": fileId, "trashed": False,
                                                        "parents": self.parents[fileId]}})()

        def update(self, fileId, addParents, removeParents, fields):
            self.calls.append(("move", fileId, addParents, removeParents))
            self.parents[fileId] = [addParents]
            return type("Q", (), {"execute": lambda s: {"id": fileId}})()

    def test_new_root_created_under_parent(self):
        from seo_report import drive as D
        con = sqlite3.connect(":memory:")
        svc = self.FakeSvc()
        self.assertEqual(D.root_folder(con, svc, SITE, "PARENT"), "new")
        self.assertEqual(svc.calls[0][1]["parents"], ["PARENT"])
        self.assertEqual(D.root_folder(con, svc, SITE, "PARENT"), "new")   # lần sau: dùng lại, không tạo thêm
        self.assertEqual(len([c for c in svc.calls if c[0] == "create"]), 1)

    def test_existing_root_moved_under_parent_when_possible(self):
        from seo_report import drive as D
        con = sqlite3.connect(":memory:")
        D._setting(con, "drive_root", "old")
        svc = self.FakeSvc(parents={"old": ["mydrive"]})
        self.assertEqual(D.root_folder(con, svc, SITE, "PARENT"), "old")
        self.assertEqual(svc.calls, [("move", "old", "PARENT", "mydrive")])
        self.assertEqual(D.root_folder(con, svc, SITE, "PARENT"), "old")   # đã đúng chỗ: không chuyển nữa
        self.assertEqual(len(svc.calls), 1)
        self.assertEqual(D.root_folder(con, svc, SITE), "old")             # không cài folder cha: giữ nguyên

    def test_parent_not_accessible_gives_clear_message(self):
        from seo_report import drive as D
        con = sqlite3.connect(":memory:")
        with self.assertRaises(SystemExit) as cm:
            D.root_folder(con, svc := self.FakeSvc(fail="create"), SITE, "PARENT")
        self.assertIn("login", str(cm.exception))
        self.assertEqual(D._setting(con, "drive_root"), None)

    def test_folder_id_from_link(self):
        from seo_report.config import _folder_id
        self.assertEqual(_folder_id("https://drive.google.com/drive/folders/1c-XjFa8_aT15?usp=sharing"), "1c-XjFa8_aT15")
        self.assertEqual(_folder_id(" 1abc "), "1abc")
        self.assertEqual(_folder_id(""), "")


if __name__ == "__main__":
    unittest.main()
