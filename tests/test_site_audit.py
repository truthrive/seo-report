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
        self.assertEqual(self.result, {"pages": 8, "errors": 0})
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


if __name__ == "__main__":
    unittest.main()
