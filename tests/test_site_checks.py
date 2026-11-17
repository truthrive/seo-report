"""Kiểm tra cấp website của Technical Audit (site_checks) và các mục mới theo bộ tri thức Technical Search & GEO.
Không gọi mạng: mọi lần mở URL đi qua hàm giả."""
import unittest
from datetime import timedelta
from types import SimpleNamespace

from seo_report import db
from seo_report import site_audit as SA
from seo_report import site_checks as SC
from seo_report.config import KeywordSettings
from tests.test_opportunities import END, SITE, Gsc
from tests.test_site_audit import page

ROBOTS = """
User-agent: *
Disallow: /wp-admin/
Disallow: /chan/
Allow: /chan/mo-lai/
Disallow: /*?orderby=
Disallow: /*.pdf$

User-agent: GPTBot
User-agent: CCBot
Disallow: /

User-agent: OAI-SearchBot
Disallow: /blog/
"""


class RobotsTest(unittest.TestCase):
    def setUp(self):
        self.g = SC.parse_robots(ROBOTS)

    def rule(self, agent, path):
        return SC.robots_rule(self.g, agent, "https://x.vn" + path)

    def test_google_matching(self):
        self.assertEqual(self.rule("Googlebot", "/chan/abc"), (False, "Disallow: /chan/"))
        self.assertEqual(self.rule("Googlebot", "/chan/mo-lai/x"), (True, ""))  # Allow dài hơn thắng
        self.assertTrue(self.rule("Googlebot", "/kinh/")[0])
        self.assertFalse(self.rule("Googlebot", "/kinh/?orderby=price")[0])  # dấu *
        self.assertFalse(self.rule("Googlebot", "/a/b.pdf")[0])  # dấu $
        self.assertTrue(self.rule("Googlebot", "/a/b.pdf?x=1")[0])  # $ là hết URL
        # bot có nhóm riêng thì chỉ theo nhóm đó (không cộng nhóm *)
        self.assertFalse(self.rule("GPTBot", "/kinh/")[0])
        self.assertFalse(self.rule("ccbot", "/")[0])  # không phân biệt hoa thường
        self.assertTrue(self.rule("OAI-SearchBot", "/chan/abc")[0])
        self.assertFalse(self.rule("OAI-SearchBot", "/blog/x")[0])

    def test_empty_disallow_and_comments(self):
        g = SC.parse_robots("User-agent: *  # mọi bot\nDisallow:\n")
        self.assertTrue(SC.robots_rule(g, "Googlebot", "https://x.vn/x")[0])
        self.assertTrue(SC.robots_rule([], "Googlebot", "https://x.vn/x")[0])

    def test_bot_policy(self):
        pol = {b["bot"]: b for b in SC.bot_policy({"groups": self.g}, ["https://x.vn/blog/a", "https://x.vn/kinh/"],
                                                  "https://x.vn/")}
        self.assertFalse(pol["GPTBot"]["home"])
        self.assertEqual(pol["GPTBot"]["kind"], "train")
        self.assertTrue(pol["OAI-SearchBot"]["home"])
        self.assertEqual(pol["OAI-SearchBot"]["blocked"], 1)
        self.assertEqual(pol["PerplexityBot"]["blocked"], 0)
        self.assertEqual(SC.bot_policy({"groups": None}, [], "https://x.vn/"), [])


def fake_web(table):
    """Hàm mở URL giả: table {url: (status, location)}; URL không có trong bảng: không mở được."""
    def opener(url):
        if url not in table:
            return {"status": None, "location": None, "error": "getaddrinfo failed"}
        st, loc = table[url]
        return {"status": st, "location": loc, "error": None}
    return opener


class HostTest(unittest.TestCase):
    def test_good_setup(self):
        op = fake_web({"https://x.vn/": (200, None), "https://www.x.vn/": (301, "https://x.vn/"),
                       "http://x.vn/": (301, "https://x.vn/"), "http://www.x.vn/": (301, "https://x.vn/")})
        self.assertTrue(all(not h["problem"] for h in SC.host_check(SITE, op)))

    def test_problems(self):
        op = fake_web({"https://x.vn/": (200, None), "http://x.vn/": (200, None),
                       "http://www.x.vn/": (302, "https://x.vn/")})  # www không có DNS: bỏ qua
        res = {h["url"]: h for h in SC.host_check(SITE, op)}
        self.assertEqual(res["http://x.vn/"]["level"], "high")
        self.assertEqual(res["http://www.x.vn/"]["level"], "medium")
        self.assertEqual(res["https://www.x.vn/"]["problem"], "")

    def test_follow_loop_and_chain(self):
        op = fake_web({"https://x.vn/a": (301, "https://x.vn/b"), "https://x.vn/b": (301, "https://x.vn/a")})
        self.assertTrue(SC.follow("https://x.vn/a", op)["loop"])
        op = fake_web({"https://x.vn/a": (301, "https://x.vn/b"), "https://x.vn/b": (301, "https://x.vn/c"),
                       "https://x.vn/c": (200, None)})
        r = SC.follow("https://x.vn/a", op)
        self.assertEqual((len(r["chain"]), r["status"], r["final"]), (3, 200, "https://x.vn/c"))

    def test_clean_link(self):
        self.assertEqual(SC.clean_link("/kinh/#mo-ta", SITE), "https://x.vn/kinh/")
        self.assertEqual(SC.clean_link("https://www.x.vn/x", SITE), "https://www.x.vn/x")
        for bad in ("?add-to-cart=1", "/a.jpg", "https://khac.vn/", "mailto:a@b.c", "/wp-admin/", "#top"):
            self.assertIsNone(SC.clean_link(bad, SITE), bad)


class FullScanTest(unittest.TestCase):
    """Quét đủ: trang + kiểm tra cấp website, rồi đọc ra các mục mới."""

    def setUp(self):
        self.con = db.connect(":memory:")
        self.g = Gsc(self.con)
        self.cfg = SimpleNamespace(site_url=SITE, db_path=":memory:", keywords=KeywordSettings())
        link = '<a href="/hong/">Hỏng</a><a href="/cu/">Trang cũ</a><a href="/tot/">Tốt</a>'
        self.pages = {
            "/a/": page("Trang có link hỏng và canonical tốt nhất", extra="<link rel='canonical' href='/a/'>"
                        "<meta name='viewport' content='width=device-width'>" + link),
            "/chan/b/": page("Trang bị robots.txt chặn mất rồi đó nha",
                             extra="<link rel='canonical' href='/chan/b/'><meta name='robots' content='nosnippet'>"),
            "/hai/": page("Trang có hai thẻ canonical khác nhau",
                          extra="<link rel='canonical' href='/hai/'><link rel='canonical' href='/khac/'>"),
            "/ct/": page("Trang canonical trỏ tới trang lỗi rồi",
                         extra="<link rel='canonical' href='/mat/'><span data-nosnippet>x</span>"),
        }
        for i, path in enumerate(list(self.pages) + ["/chuyen/"]):
            self.g.day(END - timedelta(days=3), path, 100 - i, 1000, 8.0, None)
        with self.con:
            self.con.execute("CREATE TABLE IF NOT EXISTS sitemap_urls (site TEXT, url TEXT, first_seen TEXT, "
                             "last_seen TEXT)")
            for u in ("https://x.vn/a/", "https://x.vn/hong/", "https://x.vn/cu/", "https://x.vn/chan/b/"):
                self.con.execute("INSERT INTO sitemap_urls VALUES (?, ?, ?, ?)", (SITE, u, "2026-11-01", "2026-11-05"))

        def fetcher(url):
            path = url.replace(SITE.rstrip("/"), "")
            if path == "/chuyen/":
                return {"status": 301, "final_url": SITE + "b1/", "ms": 50, "html": "", "x_robots": "", "error": None}
            return {"status": 200, "final_url": None, "ms": 100, "html": self.pages[path], "x_robots": "",
                    "error": None, "enc": "", "bytes": 5000}
        web = fake_web({"https://x.vn/": (200, None), "http://x.vn/": (200, None),
                        "https://x.vn/hong/": (404, None), "https://x.vn/cu/": (301, "https://x.vn/tot/"),
                        "https://x.vn/tot/": (200, None), "https://x.vn/mat/": (410, None),
                        "https://x.vn/chuyen/": (301, "https://x.vn/b1/"), "https://x.vn/b1/": (301, "https://x.vn/b2/"), "https://x.vn/b2/": (200, None)})
        robots = "User-agent: *\nDisallow: /chan/\n\nUser-agent: OAI-SearchBot\nDisallow: /\n"
        SA.run(self.con, SITE, END, "test", fetcher=fetcher, sleep=lambda s: None, log=lambda m: None,
               key="k", opener=web, text_get=lambda u: {"status": 200, "text": robots, "error": None},
               sb_query=lambda key, urls: {"https://x.vn/ct/": "MALWARE"})
        self.f = SA.findings(self.con, self.cfg, END)
        self.by = {c["code"]: c for c in self.f["checks"]}

    def tearDown(self):
        self.con.close()

    def paths(self, code):
        return sorted(p["url"].replace(SITE.rstrip("/"), "") if p["url"].startswith("http") else p["url"]
                      for p in self.by.get(code, {"pages": []})["pages"])

    def test_page_checks(self):
        self.assertEqual(self.paths("robots_blocked"), ["/chan/b/"])
        self.assertEqual(self.paths("nosnippet"), ["/chan/b/"])
        self.assertEqual(self.paths("data_nosnippet"), ["/ct/"])
        self.assertEqual(self.paths("canonical_multi"), ["/hai/"])
        self.assertEqual(self.paths("canonical_bad_target"), ["/ct/"])
        self.assertEqual(self.paths("unsafe"), ["/ct/"])
        self.assertEqual(self.paths("link_broken"), ["/a/"])
        row = self.by["link_broken"]["pages"][0]  # mỗi link một dòng: đang là / nên là / anchor
        self.assertEqual((row["now"], row["extra"]), ("link tới /hong/ (404)", "anchor “Hỏng”"))
        red = self.by["link_redirect"]["pages"][0]
        self.assertEqual((red["now"], red["want"]), ("link tới /cu/ (301)", "link tới /tot/"))
        self.assertEqual(self.by["link_broken"]["unit"], "link")
        self.assertEqual(self.paths("link_redirect"), ["/a/"])
        self.assertEqual(self.paths("redirect_chain"), ["/chuyen/"])
        self.assertIn("no_viewport", self.by)  # các trang khác không có viewport
        self.assertNotIn("/a/", self.paths("no_viewport"))

    def test_site_checks_not_counted_as_pages(self):
        self.assertEqual(self.paths("host_dup"), ["http://x.vn/"])
        self.assertTrue(self.by["host_dup"]["site"])
        self.assertEqual(self.by["host_dup"]["unit"], "URL")
        self.assertIn("OAI-SearchBot", self.paths("ai_search_blocked"))
        self.assertNotIn("GPTBot", self.paths("ai_search_blocked"))  # bot huấn luyện: chính sách, không phải lỗi
        self.assertEqual(self.paths("sitemap_broken"), ["/hong/"])
        self.assertEqual(self.paths("sitemap_redirect"), ["/cu/"])
        # mục cấp website không làm sai ô "trang có mục Cần sửa"
        pages_high = {p["url_id"] for c in self.f["checks"] if c["level"] == "high" and not c["site"]
                      for p in c["pages"]}
        self.assertEqual(SA.level_pages(self.f)["high"], len(pages_high))
        self.assertNotIn(None, pages_high)
        site = SC.latest(self.con)
        self.assertEqual(site["safe"]["flagged"], {"https://x.vn/ct/": "MALWARE"})
        self.assertEqual(site["links"]["targets"], 3)

    def test_status_cache_and_budget(self):
        calls = []
        op = lambda u: calls.append(u) or {"status": 200, "location": None, "error": None}  # noqa: E731
        n = SC.check_statuses(self.con, ["https://x.vn/x1", "https://x.vn/x2", "https://x.vn/hong/"], budget=1,
                              opener=op, pause=0)
        self.assertEqual((n, calls), (1, ["https://x.vn/x1"]))  # /hong/ đã có trạng thái còn hạn: không mở lại
        self.assertEqual(SC.check_statuses(self.con, ["https://x.vn/x1"], opener=op, pause=0), 0)

    def test_no_key_and_robots_error(self):
        con = db.connect(":memory:")
        try:
            out = SC.collect(con, SITE, [], key="", opener=fake_web({}), log=lambda m: None,
                             text_get=lambda u: {"status": 503, "text": "", "error": None})
            self.assertEqual(out["safe"]["error"], "chưa có Google API key")
            self.assertTrue(out["robots"]["error"])
            self.assertEqual(out["bots"], [])
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
