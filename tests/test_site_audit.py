import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from seo_report import db
from seo_report import site_audit as SA
from seo_report.config import KeywordSettings
from tests.test_opportunities import END, SITE, Gsc

GOOD = """<html><head><title>Gọng kính cận nam đẹp, chính hãng | X</title>
<meta name="description" content="Gọng kính cận nam chính hãng nhiều mẫu, đo mắt miễn phí, bảo hành 12 tháng tại cửa
hàng, giao hàng toàn quốc nhanh.">
<link rel="canonical" href="https://x.vn/gong/"><script type="application/ld+json">{"@type": "Product"}</script>
</head><body><h1>Gọng kính cận nam</h1><img src="a.jpg" alt="gọng"><img src="b.jpg">
<a href="/khac/">x</a><a href="https://y.vn/">y</a><script>var a = "không tính chữ";</script>
<p>Nội dung ngắn.</p></body></html>"""


def page(title="Trang", desc="d" * 100, h1="<h1>H</h1>", extra=""):
    return (f"<html><head><title>{title}</title><meta name='description' content='{desc}'>{extra}</head>"
            f"<body>{h1}</body></html>")


class ParseTest(unittest.TestCase):
    def test_parse_reads_seo_tags(self):
        d = SA.parse(GOOD, "https://x.vn/gong/")
        self.assertEqual(d["title"], "Gọng kính cận nam đẹp, chính hãng | X")
        self.assertTrue(d["desc"].startswith("Gọng kính cận nam chính hãng"))
        self.assertEqual(d["canonical"], "https://x.vn/gong/")
        self.assertEqual((d["h1_count"], d["imgs"], d["noalt"]), (1, 2, 1))
        self.assertEqual((d["links_int"], d["links_ext"]), (1, 1))
        self.assertEqual(d["schema"], ["Product"])
        self.assertLess(d["words"], 20)  # chữ trong script không tính


class FindingsTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.g = Gsc(self.con)
        self.cfg = SimpleNamespace(site_url=SITE, db_path=":memory:", keywords=KeywordSettings())
        pages = {
            "/ok/": page("Gọng kính cận nam đẹp chính hãng giá tốt", h1="<h1>Gọng</h1>"),
            "/dup1/": page("Kính mát thời trang nữ đẹp nhất năm"),
            "/dup2/": page("Kính mát thời trang nữ đẹp nhất năm"),
            "/noidx/": page("Trang bị chặn index bởi thẻ robots meta",
                            extra="<meta name='robots' content='noindex, follow'>"),
            "/can/": page("Trang có canonical trỏ sang trang khác hẳn", extra="<link rel='canonical' href='/ok/'>"),
            "/noh1/": page("Trang không có thẻ H1 nào cả trong thân", h1=""),
        }
        for i, path in enumerate(list(pages) + ["/hong/", "/chuyen/"]):
            self.g.day(END - timedelta(days=3), path, 100 - i, 1000, 8.0, "kính cận" if path == "/ok/" else None)
        self.pages = pages

        def fetcher(url):
            path = url.replace(SITE.rstrip("/"), "")
            if path == "/hong/":
                return {"status": 404, "final_url": None, "ms": 50, "html": "", "x_robots": "", "error": None}
            if path == "/chuyen/":
                return {"status": 301, "final_url": SITE + "moi/", "ms": 50, "html": "", "x_robots": "",
                        "error": None}
            return {"status": 200, "final_url": None, "ms": 4000 if path == "/ok/" else 100,
                    "html": self.pages[path], "x_robots": "", "error": None}
        self.fetcher = fetcher
        self.result = SA.run(self.con, SITE, END, "test", fetcher=fetcher, sleep=lambda s: None, log=lambda m: None,
                             site_checks=False)

    def tearDown(self):
        self.con.close()

    def test_seo_group_always_scanned(self):
        from seo_report import urls as U
        # trang mới trong nhóm URL SEO, chưa có click nào: trước đây không bao giờ được quét
        uid = self.con.execute("INSERT INTO urls (site, url) VALUES (?, ?)", (SITE, SITE + "moi-dang/")).lastrowid
        gid = U.ensure_group(self.con, SITE)
        self.con.execute("INSERT INTO url_group_members VALUES (?, ?, ?, ?)", (gid, uid, "2026-11-17", "test"))
        picked = SA.pick_pages(self.con, SITE, END, limit=3)
        self.assertEqual(picked[0], (uid, SITE + "moi-dang/"))  # nhóm đứng đầu
        self.assertEqual(len(picked), 3)                        # rồi lấp bằng trang nhiều click cho đủ
        self.assertEqual(len({i for i, _ in picked}), 3)        # không trùng
        # nhóm lớn hơn giới hạn: vẫn quét đủ nhóm
        self.assertEqual(len(SA.pick_pages(self.con, SITE, END, limit=1)), 1)
        self.assertEqual(SA.url_groups(self.con, SITE), {uid: [U.DEFAULT_GROUP]})

    def test_sitemap_non_product_pages_and_product_sample(self):
        from seo_report import urls as U
        con = self.con
        con.execute("CREATE TABLE IF NOT EXISTS sitemap_urls (site TEXT, url TEXT, first_seen TEXT, last_seen TEXT)")

        def add(path, type_, in_sitemap=True):
            uid = con.execute("INSERT INTO urls (site, url, type) VALUES (?, ?, ?)", (SITE, SITE + path, type_)).lastrowid
            if in_sitemap:
                con.execute("INSERT INTO sitemap_urls VALUES (?, ?, ?, ?)", (SITE, SITE + path, "2026-11-01", "2026-11-05"))
            return uid
        blog = add("bai-chua-co-click/", U.BLOG)          # bài viết chưa có click: vẫn quét (nội dung riêng)
        cat = add("danh-muc-moi/", U.CATEGORY)
        prod = add("san-pham-khong-click/", U.PRODUCT)     # sản phẩm không có click: không quét (chỉ quét mẫu)
        add("bai-cu/", U.BLOG, in_sitemap=False)          # không còn trong sitemap: không quét
        ids = {i for i, _ in SA.sitemap_pages(con, SITE)}
        self.assertEqual(ids, {blog, cat})
        picked = {i for i, _ in SA.pick_pages(con, SITE, END, top=2, top_products=0)}
        self.assertTrue({blog, cat} <= picked)
        self.assertNotIn(prod, picked)
        # trang khung (danh mục) đứng trước bài viết khi bị giới hạn
        self.assertEqual([i for i, _ in SA.sitemap_pages(con, SITE)][0], cat)
        # có sitemap nhưng chưa từng đọc: không lỗi
        con.execute("DELETE FROM sitemap_urls")
        self.assertEqual(SA.sitemap_pages(con, SITE), [])

    def test_page_clicks_and_level_pages(self):
        f = SA.findings(self.con, self.cfg, END)
        ids = sorted({p["url_id"] for c in f["checks"] for p in c["pages"]})
        clicks = SA.page_clicks(self.con, SITE, END, ids)
        noidx = next(p for c in f["checks"] if c["code"] == "noindex" for p in c["pages"])
        self.assertEqual(clicks[noidx["url_id"]], (97, 1000))  # /noidx/ là trang thứ 4: 100 - 3 click
        self.assertEqual(SA.page_clicks(self.con, SITE, END, []), {})
        # đếm trang thật, không cộng dồn: trang 1 có 2 mục "Cần sửa" vẫn tính 1 trang (trước đây tính 2 "lượt trang")
        au = {"checks": [{"level": "high", "pages": [{"url_id": 1}, {"url_id": 2}]},
                         {"level": "high", "pages": [{"url_id": 1}]}, {"level": "info", "pages": [{"url_id": 1}]}]}
        self.assertEqual(SA.level_pages(au), {"high": 2, "medium": 0, "info": 1})

    def codes(self):
        f = SA.findings(self.con, self.cfg, END)
        return f, {c["code"]: sorted(p["url"].replace(SITE.rstrip("/"), "") for p in c["pages"]) for c in f["checks"]}

    def test_run_scans_pages_and_checks(self):
        self.assertEqual(self.result, {"pages": 8, "errors": 0, "blocked": 0, "stopped_early": False})
        f, codes = self.codes()
        self.assertEqual(codes["4xx"], ["/hong/"])
        self.assertEqual(codes["redirect"], ["/chuyen/"])
        self.assertEqual(codes["noindex"], ["/noidx/"])
        self.assertEqual(codes["canonical"], ["/can/"])
        self.assertEqual(codes["dup_title"], ["/dup1/", "/dup2/"])
        self.assertEqual(codes["no_h1"], ["/noh1/"])
        self.assertEqual(codes["slow"], ["/ok/"])
        self.assertNotIn("kw_title", codes)  # "kính cận" có trong tiêu đề /ok/
        self.assertEqual(f["checks"][0]["level"], "high")
        self.assertEqual(f["pages"], 8)
        self.assertEqual(f["healthy"], 8 - 3)  # 4xx, noindex, canonical (chuyển hướng chỉ là Nên sửa)
        self.assertEqual(SA.CHECKS["redirect"][0], "medium")

    def test_keyword_missing_from_title_and_low_ctr(self):
        self.g.day(END - timedelta(days=2), "/dup1/", 4, 3000, 2.0, "kính râm phân cực")
        _, codes = self.codes()
        self.assertEqual(codes["kw_title"], ["/dup1/"])
        self.assertEqual(codes["low_ctr"], ["/dup1/"])  # vị trí ~2, CTR ~2,6%

    def test_refresh_waits_a_week(self):
        cfg = SimpleNamespace(site_url=SITE, db_path=":memory:", keywords=KeywordSettings())
        self.assertIsNone(SA.refresh(self.con, cfg, today=date.today()))

    def test_schedule_due_and_pause(self):
        from datetime import datetime, timezone
        tz = timezone.utc
        self.assertEqual(SA.schedule(self.con)["weekday"], 0)
        SA.save_schedule(self.con, 2, 3, False, "an")  # thứ Tư 03:00
        now = datetime(2026, 11, 18, 10, 0, tzinfo=tz)  # thứ Tư
        sch = SA.schedule(self.con)
        self.assertEqual(SA.last_slot(sch, now), datetime(2026, 11, 18, 3, 0, tzinfo=tz))
        self.assertEqual(SA.next_slot(sch, now), datetime(2026, 11, 25, 3, 0, tzinfo=tz))
        early = datetime(2026, 11, 18, 2, 0, tzinfo=tz)
        self.assertEqual(SA.last_slot(sch, early), datetime(2026, 11, 11, 3, 0, tzinfo=tz))
        with self.con:
            self.con.execute("UPDATE audit_runs SET started_at = ?", ("2026-11-17T09:00:00+00:00",))
        self.assertTrue(SA.due(self.con, now))  # quét lần cuối trước mốc thứ Tư
        self.assertFalse(SA.due(self.con, early))
        SA.save_schedule(self.con, 2, 3, True, "an")
        self.assertFalse(SA.due(self.con, now))  # tạm ngưng

    def test_old_history_record_gets_status(self):
        import json
        SA.ensure_tables(self.con)
        f = SA.findings(self.con, self.cfg, END)
        old = {c["code"]: [p["url"] for p in c["pages"]] for c in f["checks"]}  # kiểu cũ: chỉ {mã: [URL]}
        with self.con:
            self.con.execute("INSERT INTO audit_findings_hist VALUES (?, ?, ?)",
                             (f["run"]["id"], f["run"]["finished_at"], json.dumps(old)))
        SA.findings_history(self.con, f)
        h = SA.history_list(self.con)[0]
        self.assertTrue(h["status"])
        self.assertTrue(all(isinstance(v, list) for v in h["codes"].values()))
        self.assertIn("noindex", h["codes"])

    def test_stopped_scan_is_detected_and_rescanned(self):
        from datetime import datetime, timezone
        done = SA.last_run(self.con)
        t0 = datetime(2026, 11, 18, 3, 0, tzinfo=timezone.utc)
        with self.con:
            self.con.execute("INSERT INTO audit_runs (started_at, created_by) VALUES (?, 'an')", (t0.isoformat(),))
            self.con.execute("UPDATE audit_pages SET fetched_at = ?", ((t0 - timedelta(days=1)).isoformat(),))
            self.con.execute("UPDATE audit_pages SET fetched_at = ? WHERE url LIKE '%/ok/'",
                             ((t0 + timedelta(minutes=2)).isoformat(),))
        # còn đang ghi trang: chưa tính là dừng, không quét chồng
        self.assertIsNone(SA.stopped(self.con, t0 + timedelta(minutes=5)))
        self.assertFalse(SA.due(self.con, t0 + timedelta(minutes=5)))
        st = SA.stopped(self.con, t0 + timedelta(minutes=30))
        self.assertEqual(st["pages_done"], 1)
        self.assertTrue(SA.due(self.con, t0 + timedelta(minutes=30)))  # quét bù
        SA.save_schedule(self.con, 0, 2, True, "an")
        self.assertFalse(SA.due(self.con, t0 + timedelta(minutes=30)))  # tạm ngưng thì không tự quét
        # kết quả hiển thị vẫn dựa trên lần quét xong gần nhất
        self.assertEqual(SA.last_run(self.con, done=True)["id"], done["id"])
        self.assertEqual(SA.findings(self.con, self.cfg, END)["run"]["id"], done["id"])

    def test_track_progress_and_eta(self):
        prog = SA.track("x.db", "an")
        try:
            prog(10, 100, "pages", "https://x.vn/a/")
            r = SA.running["x.db"]
            self.assertEqual((r["phase"], r["n"], r["url"]), ("pages", 10, "https://x.vn/a/"))
            self.assertEqual(SA.eta(r, now=r["pt0"] + 20), 180)  # 2 giây / trang, còn 90 trang
            prog(0, 400, "links")
            self.assertEqual(SA.running["x.db"]["phase"], "links")
            self.assertIsNone(SA.eta(SA.running["x.db"]))  # chưa đủ số để ước
        finally:
            SA.running.pop("x.db", None)

    def _rescan(self, fetcher):
        return SA.run(self.con, SITE, END, "test", fetcher=fetcher, sleep=lambda s: None, log=lambda m: None,
                      site_checks=False)

    def test_firewall_block_is_unknown_not_4xx(self):
        base = self.fetcher

        def fetcher(url):
            if url.endswith("/dup1/"):  # trang thử thách của tường lửa
                return {"status": 403, "final_url": None, "ms": 50, "html": "", "x_robots": "", "error": None,
                        "blocked": True}
            return base(url)
        r = self._rescan(fetcher)
        self.assertEqual(r["blocked"], 1)
        _, codes = self.codes()
        self.assertEqual(codes["blocked"], ["/dup1/"])
        self.assertEqual(codes["4xx"], ["/hong/"])  # 404 thật vẫn là lỗi

    def test_429_waits_then_retries(self):
        base, calls, waits = self.fetcher, [], []

        def fetcher(url):
            calls.append(url)
            if url.endswith("/ok/") and calls.count(url) == 1:
                return {"status": 429, "final_url": None, "ms": 5, "html": "", "x_robots": "", "error": None,
                        "retry_after": "7"}
            return base(url)
        SA.run(self.con, SITE, END, "test", fetcher=fetcher, sleep=waits.append, log=lambda m: None,
               site_checks=False)
        self.assertIn(7, waits)
        _, codes = self.codes()
        self.assertNotIn("blocked", codes)

    def test_stops_after_blocked_streak(self):
        old = SA.BLOCK_STREAK
        SA.BLOCK_STREAK = 3
        try:
            r = self._rescan(lambda url: {"status": 403, "final_url": None, "ms": 5, "html": "", "x_robots": "",
                                          "error": None, "blocked": True})
        finally:
            SA.BLOCK_STREAK = old
        self.assertTrue(r["stopped_early"])
        self.assertEqual(r["blocked"], 3)

    def test_block_mark(self):
        self.assertTrue(SA._block_mark("<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'>"))
        self.assertFalse(SA._block_mark("<html><title>Gọng kính</title></html>"))

    def test_history_list(self):
        SA.findings_history(self.con, SA.findings(self.con, self.cfg, END))
        h = SA.history_list(self.con)
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["pages"], 8)
        self.assertIn("noindex", h[0]["codes"])
        st = h[0]["status"]
        self.assertTrue(st and all(len(v) == 2 for v in st.values()))
        self.assertIn("high", {v[0] for v in st.values()})
        f = SA.findings(self.con, self.cfg, END)
        self.assertEqual(SA.prev_scanned(self.con, {"run": {"id": f["run"]["id"] + 1}}), set(f["scanned"]))

    def test_recheck_reports_pass_and_fail(self):
        self.pages["/noidx/"] = page("Trang bị chặn index bởi thẻ robots meta")  # đã gỡ noindex
        u = SITE.rstrip("/")
        res = SA.recheck(self.con, self.cfg, [("noindex", u + "/noidx/"), ("no_h1", u + "/noh1/"),
                                              ("low_ctr", u + "/ok/")], "an", fetcher=self.fetcher,
                         sleep=lambda s: None)
        got = {r["code"]: r["result"] for r in res}
        self.assertEqual(got, {"noindex": "pass", "no_h1": "fail", "low_ctr": "unknown"})
        log = SA.fix_log(self.con, ["noindex"])
        self.assertEqual((log[0]["by"], log[0]["result"]), ("an", "pass"))
        _, codes = self.codes()
        self.assertNotIn("noindex", codes)


if __name__ == "__main__":
    unittest.main()
