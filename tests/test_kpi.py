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
        for kw in ("a", "b", "c", "d"):
            cur = self.con.execute("INSERT INTO rank_keywords (site, keyword, url_id, source, added_by, added_at) "
                                   "VALUES (?, ?, NULL, 'kpi', 't', '2026-11-01')", (SITE, kw))
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


if __name__ == "__main__":
    unittest.main()
