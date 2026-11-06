import sqlite3
import unittest
from datetime import date
from types import SimpleNamespace

from seo_report import backlinks as BL
from seo_report import rank as R

SITE = "sc-domain:example.vn"


class FakeClient:
    """DataForSEO giả: không gọi mạng, đếm số lần gọi."""

    def __init__(self, ref=120, backlinks=900):
        self.calls = []
        self.ref, self.backlinks = ref, backlinks

    def summary(self, target):
        self.calls.append(("summary", target))
        return {"backlinks": self.backlinks, "referring_domains": self.ref, "referring_main_domains": 110,
                "referring_domains_nofollow": 20, "rank": 182, "backlinks_spam_score": 7,
                "broken_backlinks": 3}, 0.02

    def history(self, target, date_from):
        self.calls.append(("history", date_from))
        return [{"date": "2026-09-01 00:00:00 +00:00", "backlinks": 800, "referring_domains": 100,
                 "new_backlinks": 40, "lost_backlinks": 10, "new_referring_domains": 5, "lost_referring_domains": 1,
                 "rank": 170},
                {"date": "2026-10-01 00:00:00 +00:00", "backlinks": 850, "referring_domains": 112,
                 "new_backlinks": 60, "lost_backlinks": 12, "new_referring_domains": 14, "lost_referring_domains": 2,
                 "rank": 178}], 0.03

    def referring_domains(self, target):
        self.calls.append(("domains", target))
        return {"total_count": 272, "items": [
            {"domain": "vnexpress.net", "rank": 610, "backlinks": 3, "referring_pages": 3,
             "referring_pages_nofollow": 1, "first_seen": "2025-04-02 08:11:41 +00:00", "backlinks_spam_score": 2}]}, 0.02

    def changes(self, target, since):
        self.calls.append(("changes", since))
        return {"total_count": 2, "items": [
            {"is_lost": False, "domain_from": "a.vn", "url_from": "https://a.vn/x", "page_from_title": "Bài A",
             "url_to": "https://example.vn/gong-kinh/", "anchor": "gọng kính", "dofollow": True,
             "item_type": "anchor", "domain_from_rank": 120, "first_seen": "2026-10-20 01:00:00 +00:00",
             "last_seen": "2026-11-03 01:00:00 +00:00"},
            {"is_lost": True, "domain_from": "b.vn", "url_from": "https://b.vn/y", "anchor": "",
             "url_to": "https://example.vn/", "dofollow": False, "first_seen": "2025-01-01 00:00:00 +00:00",
             "last_seen": "2026-10-15 00:00:00 +00:00"}]}, 0.021

    def anchors(self, target):
        self.calls.append(("anchors", target))
        return {"total_count": 40, "items": [{"anchor": "Tâm Đức", "backlinks": 120, "referring_domains": 50,
                                              "first_seen": "2024-01-01 00:00:00 +00:00",
                                              "backlinks_spam_score": 1}]}, 0.02

    def pages(self, target):
        self.calls.append(("pages", target))
        return {"total_count": 90, "items": [{"page": "https://example.vn/", "meta": {"title": "Trang chủ"},
                                              "status_code": 200, "page_summary": {
                                                  "backlinks": 300, "referring_domains": 80, "rank": 210}}]}, 0.02


def cfg(budget=5.0, paused=False):
    return SimpleNamespace(rank=SimpleNamespace(paused=paused, monthly_budget_usd=budget),
                           dataforseo_secret="secrets/none.toml")


class BacklinksTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        R.ensure_tables(self.con)

    def test_first_fetch_saves_summary_history_and_cost(self):
        fake = FakeClient()
        self.assertTrue(BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 4), client=fake, log=lambda m: None))
        self.assertEqual([c[0] for c in fake.calls], ["summary", "history", "domains", "changes", "anchors", "pages"])
        self.assertEqual(fake.calls[3][1], "2026-10-05")  # link mới / mất 30 ngày gần nhất
        self.assertEqual(fake.calls[0][1], "example.vn")  # tên miền, không kèm sc-domain:
        bl = BL.latest(self.con, SITE)
        self.assertEqual((bl["now"]["referring_domains"], bl["now"]["backlinks"], bl["now"]["rank"]), (120, 900, 182))
        self.assertIsNone(bl["prev"])
        self.assertEqual([h["month"] for h in bl["history"]], ["2026-09", "2026-10"])
        # chi phí tính chung ngân sách DataForSEO của website (cùng check rank, volume)
        # (chi phí ghi theo giờ thật: so tháng hiện tại)
        spent = R.cost_by_month(self.con, [date.today().strftime("%Y-%m")])[date.today().strftime("%Y-%m")]
        self.assertAlmostEqual(spent["backlinks"], 0.05 + 0.081)

    def test_lists_saved_slim_and_logged(self):
        BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 4), client=FakeClient(), log=lambda m: None)
        ls = BL.lists(self.con, SITE)
        self.assertEqual(set(ls), {"domains", "changes", "anchors", "pages"})
        self.assertEqual(ls["domains"]["total"], 272)
        self.assertEqual(ls["domains"]["items"][0], {"domain": "vnexpress.net", "rank": 610, "backlinks": 3, "pages": 3,
                                                     "dofollow_pages": 2, "first_seen": "2025-04-02", "spam": 2})
        new, lost = ls["changes"]["items"]
        self.assertEqual((new["lost"], new["anchor"], new["first_seen"]), (False, "gọng kính", "2026-10-20"))
        self.assertEqual((lost["lost"], lost["last_seen"], lost["dofollow"]), (True, "2026-10-15", False))
        self.assertEqual(ls["pages"]["items"][0]["title"], "Trang chủ")
        self.assertEqual(ls["pages"]["items"][0]["domains"], 80)
        kinds = [x["detail"] for x in R.spend_log(self.con, date.today().strftime("%Y-%m"))]
        self.assertIn("Danh sách website trỏ về", kinds)
        self.assertIn("Link mới / mất 30 ngày", kinds)

    def test_one_list_failing_keeps_others(self):
        fake = FakeClient()

        def boom(target):
            raise RuntimeError("40204 chưa bật")
        fake.anchors = boom
        logs = []
        BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 4), client=fake, log=logs.append)
        self.assertEqual(set(BL.lists(self.con, SITE)), {"domains", "changes", "pages"})
        self.assertTrue(any("anchors" in m for m in logs))

    def test_weekly_refresh_and_compare_with_previous(self):
        BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 4), client=FakeClient(), log=lambda m: None)
        fake = FakeClient(ref=128)
        # trong 7 ngày: không gọi lại (không tốn tiền)
        self.assertFalse(BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 8), client=fake, log=lambda m: None))
        self.assertEqual(fake.calls, [])
        # đủ 7 ngày: lấy số tổng + 4 danh sách; lịch sử tháng trước đã có nên không hỏi lại
        self.assertTrue(BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 11), client=fake, log=lambda m: None))
        self.assertEqual([c[0] for c in fake.calls], ["summary", "domains", "changes", "anchors", "pages"])
        bl = BL.latest(self.con, SITE)
        self.assertEqual((bl["now"]["referring_domains"], bl["prev"]["referring_domains"]), (128, 120))

    def test_paused_or_over_budget_does_not_call(self):
        fake = FakeClient()
        self.assertFalse(BL.refresh(self.con, SITE, cfg(paused=True), today=date(2026, 11, 4), client=fake,
                                    force=True, log=lambda m: None))
        with self.assertRaises(RuntimeError):
            BL.refresh(self.con, SITE, cfg(budget=0.01), today=date(2026, 11, 4), client=fake, force=True,
                       log=lambda m: None)
        self.assertEqual(fake.calls, [])


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        R.ensure_tables(self.con)

    def test_default_weekly_all_lists(self):
        st = BL.settings(self.con, SITE)
        self.assertEqual((st["every_days"], st["paused"], st["lists"]), (7, False, list(BL.LIST_KINDS)))

    def test_monthly_only_chosen_lists(self):
        BL.save_settings(self.con, SITE, 30, False, ["changes", "domains"], "an")
        self.assertEqual(BL.settings(self.con, SITE)["lists"], ["domains", "changes"])
        fake = FakeClient()
        BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 4), client=fake, log=lambda m: None)
        self.assertEqual([c[0] for c in fake.calls], ["summary", "history", "domains", "changes"])
        fake.calls.clear()  # 14 ngày sau: lịch tháng chưa đến hạn
        self.assertFalse(BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 18), client=fake, log=lambda m: None))
        self.assertEqual(BL.next_due(self.con, SITE, date(2026, 11, 18)), date(2026, 12, 4))
        self.assertTrue(BL.refresh(self.con, SITE, cfg(), today=date(2026, 12, 4), client=fake, log=lambda m: None))

    def test_paused_skips_schedule_but_button_still_works(self):
        BL.save_settings(self.con, SITE, 7, True, [], "an")
        fake = FakeClient()
        self.assertFalse(BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 4), client=fake, log=lambda m: None))
        self.assertEqual(fake.calls, [])
        self.assertIsNone(BL.next_due(self.con, SITE))
        self.assertEqual(BL.monthly_estimate(BL.settings(self.con, SITE)), 0)
        self.assertTrue(BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 4), client=fake, force=True,
                                   log=lambda m: None))
        self.assertEqual([c[0] for c in fake.calls], ["summary", "history"])  # không danh sách nào được chọn

    def test_estimate(self):
        self.assertAlmostEqual(BL.monthly_estimate({"paused": False, "every_days": 30, "lists": ["domains"]}),
                               BL.COST_SUMMARY + BL.COST_LIST)
        with self.assertRaises(ValueError):
            BL.save_settings(self.con, SITE, 3, False, [])


class AuditTest(unittest.TestCase):
    def lists(self):
        def L(items):
            return {"items": items}
        return {
            "changes": L([{"lost": False, "domain_from": "spam.xyz", "anchor": "High Quality Backlinks", "spam": 90,
                           "first_seen": "2026-11-01"},
                          {"lost": False, "domain_from": "spam.xyz", "anchor": "x", "spam": 60, "first_seen": "2026-11-02"},
                          {"lost": False, "domain_from": "good.vn", "anchor": "Tâm Đức", "spam": 0,
                           "first_seen": "2026-11-01"},
                          {"lost": True, "domain_from": "news.vn", "anchor": "kính", "spam": 0, "domain_rank": 400,
                           "url_to": "https://example.vn/a", "last_seen": "2026-10-20"}]),
            "pages": L([{"page": "https://example.vn/", "status": 200, "domains": 100, "backlinks": 200},
                        {"page": "https://example.vn/cu", "status": 404, "domains": 3, "backlinks": 4},
                        {"page": "https://example.vn/doi", "status": 308, "domains": 2, "backlinks": 2}]),
            "anchors": L([{"anchor": "Backlinks for example.vn", "domains": 80, "spam": 37},
                          {"anchor": "gọng kính", "domains": 10, "spam": 2},
                          {"anchor": "Tâm Đức", "domains": 10, "spam": 0}]),
            "domains": L([{"domain": "sitewide.vn", "backlinks": 96, "rank": 200, "spam": 5},
                          {"domain": "a.vn", "backlinks": 2, "rank": 100, "spam": 1}])}

    def test_checks_and_order(self):
        from seo_report import backlink_audit as AU
        checks = {c["key"]: c for c in AU.audit(self.lists(), ["tam duc", "example"])}
        self.assertEqual((checks["spam"]["level"], checks["spam"]["count"]), ("high", 2))
        self.assertEqual(checks["spam"]["rows"][0]["spam"], 90)  # spam nhất lên đầu
        self.assertEqual((checks["broken"]["count"], checks["broken"]["rows"][0]["status"]), (1, 404))
        self.assertEqual((checks["redirect"]["level"], checks["redirect"]["count"]), ("info", 1))
        self.assertEqual((checks["lost"]["level"], checks["lost"]["count"]), ("medium", 1))
        self.assertEqual(checks["anchor_spam"]["count"], 1)
        self.assertEqual(checks["anchor_mix"]["level"], "ok")  # từ khóa 10% (anchor URL 80%)
        self.assertEqual(checks["anchor_mix"]["mix"]["url"], 80)
        self.assertEqual([x["domain"] for x in checks["heavy"]["rows"]], ["sitewide.vn"])
        levels = [c["level"] for c in AU.audit(self.lists(), [])]
        self.assertEqual(levels, sorted(levels, key=["high", "medium", "info", "ok"].index))

    def test_filters_match_the_check_counts(self):
        """Bấm một mục kiểm tra = lọc bảng của tab: số dòng sau lọc khớp số của mục đó."""
        from seo_report import backlink_audit as AU
        ls = self.lists()
        for c in AU.audit(ls, ["tam duc", "example"]):
            if c["key"] == "anchor_mix":
                continue
            items = ls[AU.CHECK_TAB[c["key"]]]["items"]
            self.assertEqual(sum(1 for x in items if AU.matches(c["key"], x)), c["count"], c["key"])
        kw = [x["anchor"] for x in ls["anchors"]["items"] if AU.matches("anchor_mix", x, ["tam duc", "example"])]
        self.assertEqual(kw, ["gọng kính"])

    def test_disavow_file(self):
        from seo_report import backlink_audit as AU
        text = AU.disavow(self.lists(), "06/11/2026")
        self.assertEqual([ln for ln in text.splitlines() if not ln.startswith("#")], ["domain:spam.xyz"])

    def test_missing_lists_give_no_checks(self):
        from seo_report import backlink_audit as AU
        self.assertEqual(AU.audit({}, []), [])


class ExportTest(unittest.TestCase):
    def test_full_and_single_workbooks(self):
        import io as _io

        from openpyxl import load_workbook

        from seo_report import backlink_export as BX
        con = sqlite3.connect(":memory:")
        R.ensure_tables(con)
        BL.refresh(con, SITE, cfg(), today=date(2026, 11, 4), client=FakeClient(), log=lambda m: None)
        ls, latest = BL.lists(con, SITE), BL.latest(con, SITE)
        wb = load_workbook(_io.BytesIO(BX.build(ls, latest, ["example"], SITE)))
        self.assertEqual(wb.sheetnames[:3], ["Tổng quan", "Lịch sử 12 tháng", "Audit"])
        for name in ("Website trỏ về", "Link mới - mất", "Anchor text", "Trang được link"):
            self.assertIn(name, wb.sheetnames)
        self.assertEqual(wb["Tổng quan"]["B2"].value, 120)  # website trỏ về
        ch = wb["Link mới - mất"]
        self.assertEqual([c.value for c in ch[2]][:2], ["Mới", "a.vn"])
        self.assertTrue(all(len(n) <= 31 for n in wb.sheetnames))  # giới hạn tên sheet của Excel
        one = load_workbook(_io.BytesIO(BX.build(ls, latest, [], SITE, "anchors")))
        self.assertEqual(one.sheetnames[:2], ["Anchor text", "Kiểm tra"])  # kèm kiểm tra của riêng tab Anchor
        self.assertEqual({r[1].value for r in one["Kiểm tra"].iter_rows(min_row=2)},
                         {"Anchor có điểm spam cao", "Cơ cấu anchor"})
        au = load_workbook(_io.BytesIO(BX.build(ls, latest, [], SITE, "audit")))
        self.assertEqual(au.sheetnames[0], "Audit")


class AnchorTypeTest(unittest.TestCase):
    def test_brand_url_keyword_empty(self):
        from seo_report.web_backlink import anchor_type
        terms = ["tam duc", "matkinhtamduc"]
        self.assertEqual([anchor_type(a, terms) for a in
                          ["Tâm Đức", "Mắt Kính TÂM ĐỨC", "matkinhtamduc.com", "https://abc.vn/x", "gọng kính", ""]],
                         ["brand", "brand", "url", "url", "keyword", "empty"])


if __name__ == "__main__":
    unittest.main()
