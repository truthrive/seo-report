import sqlite3
import unittest
from datetime import date

from seo_report import backlink_build as BB

SITE = "https://matkinhtamduc.com/"
HTML = """<html><body>
<p>Xem <a href="https://www.matkinhtamduc.com/kinh-can/" rel="nofollow">kính cận</a></p>
<p>Ghé <a href="/khac">khác</a> và <a href="https://matkinhtamduc.com/trong-kinh">Tròng  Kính</a></p>
<a href="https://matkinhtamduc.com/anh"><img src="x.png" alt="ảnh kính"></a>
</body></html>"""


class _Resp:
    def __init__(self, body=b"", status=200, url="https://bao.vn/bai"):
        self.body, self.status, self.url = body, status, url
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body

    def geturl(self):
        return self.url


class FindLinkTest(unittest.TestCase):
    def test_states(self):
        base = "https://bao.vn/bai"
        self.assertEqual(BB.find_link(HTML, base, "https://matkinhtamduc.com/trong-kinh/", "tròng kính")["state"],
                         "ok")  # www, dấu /, khoảng trắng, chữ hoa không ảnh hưởng
        self.assertEqual(BB.find_link(HTML, base, "https://matkinhtamduc.com/kinh-can", None)["state"], "nofollow")
        r = BB.find_link(HTML, base, "https://matkinhtamduc.com/trong-kinh", "kính cận giá rẻ")
        self.assertEqual((r["state"], r["anchor_seen"]), ("anchor", "Tròng Kính"))
        self.assertEqual(BB.find_link(HTML, base, "https://matkinhtamduc.com/khong-co", None)["state"], "lost")
        self.assertEqual(BB.find_link(HTML, base, "https://matkinhtamduc.com/anh", "ảnh kính")["state"], "ok")

    def test_check_link_http(self):
        ok = BB.check_link("https://bao.vn/bai", "https://matkinhtamduc.com/kinh-can", None,
                           opener=lambda req, timeout=0: _Resp(HTML.encode()))
        self.assertEqual((ok["state"], ok["http_status"]), ("nofollow", 200))

        def gone(req, timeout=0):
            e = OSError("Not Found")
            e.code = 404
            raise e
        r = BB.check_link("https://bao.vn/bai", "https://matkinhtamduc.com/kinh-can", None, opener=gone)
        self.assertEqual((r["state"], r["http_status"]), ("lost", 404))

    def test_private_address_not_fetched(self):
        r = BB.check_link("http://127.0.0.1/admin", "https://matkinhtamduc.com/", None)
        self.assertEqual(r["state"], "error")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")

    def test_add_validates_and_dedupes(self):
        rows = BB.parse_rows("https://bao.vn/a | https://matkinhtamduc.com/x | kính | 05/11/2026 | 1.500.000\n"
                             "https://bao.vn/b | https://khac.com/x\n"
                             "bao.vn/c | /x\n"
                             "https://bao.vn/d | /trang-tuong-doi | | 31/02/2026\n"
                             "https://www.bao.vn/a/ | https://matkinhtamduc.com/x/")
        res = BB.add_links(self.con, SITE, rows, "team")
        self.assertEqual(res["added"], 1)
        self.assertEqual(len(res["bad"]), 4)
        r = BB.links(self.con, SITE)[0]
        self.assertEqual((r["placed_on"], r["cost"], r["state"]), ("2026-11-05", 1500000.0, "pending"))

    def test_check_due_and_alerts(self):
        BB.add_links(self.con, SITE, [{"url_from": "https://bao.vn/a", "url_to": "https://matkinhtamduc.com/x"}], "t")
        n = BB.check_due(self.con, SITE, opener=lambda req, timeout=0: _Resp(b"<a href='/khac'>x</a>"))
        self.assertEqual(n, 1)
        r = BB.links(self.con, SITE)[0]
        self.assertEqual(r["state"], "lost")
        self.assertIsNotNone(r["lost_at"])
        self.assertEqual(BB.check_due(self.con, SITE, opener=None), 0)  # mới kiểm tra: chưa tới hạn
        al = BB.alerts(self.con, SITE, {"changes": {"fetched_at": "2026-11-06", "items": [
            {"lost": True, "domain_rank": 400, "domain_from": "vnexpress.net"},
            {"lost": True, "domain_rank": 10, "domain_from": "nho.vn"}]}})
        titles = [a["title"] for a in al]
        self.assertIn("Mất 1 link từ website mạnh", titles)
        self.assertIn("1 link đã xây bị mất", titles)


class NeedsTest(unittest.TestCase):
    def test_pages_ranked_by_opportunity(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
            CREATE TABLE pages (id INTEGER PRIMARY KEY, site TEXT, url TEXT);
            CREATE TABLE queries (id INTEGER PRIMARY KEY, text TEXT);
            CREATE TABLE gsc_query_daily (date TEXT, page_id INT, query_id INT, clicks INT, impressions INT,
                                          position REAL);""")
        con.execute("INSERT INTO pages VALUES (1, ?, 'https://matkinhtamduc.com/a/'), "
                    "(2, ?, 'https://matkinhtamduc.com/b/'), (3, ?, 'https://matkinhtamduc.com/c/')",
                    (SITE, SITE, SITE))
        con.execute("INSERT INTO queries VALUES (1, 'kính a'), (2, 'kính b'), (3, 'kính c')")
        con.executemany("INSERT INTO gsc_query_daily VALUES (?,?,?,?,?,?)", [
            ("2026-11-01", 1, 1, 1, 500, 8.0),    # trang a: vị trí 8, nhiều hiển thị, đã có 10 website trỏ về
            ("2026-11-01", 2, 2, 1, 300, 6.0),    # trang b: vị trí 6, chưa có link
            ("2026-11-01", 3, 3, 9, 900, 2.0)])   # trang c: đã Top 3 → không phải trang cần link
        lists = {"pages": {"total": 1, "items": [{"page": "https://matkinhtamduc.com/a", "domains": 10}]}}
        res = BB.needs(con, SITE, lists, date(2026, 11, 6))
        self.assertEqual([r["url"][-2:] for r in res["rows"]], ["b/", "a/"])
        self.assertEqual([r["domains"] for r in res["rows"]], [0, 10])
        self.assertTrue(res["complete"])


class SeoUrlsTest(unittest.TestCase):
    def test_groups_and_filter(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
            CREATE TABLE urls (id INTEGER PRIMARY KEY, site TEXT, url TEXT);
            CREATE TABLE url_groups (id INTEGER PRIMARY KEY, site TEXT, name TEXT);
            CREATE TABLE url_group_members (group_id INT, url_id INT, added_at TEXT, added_by TEXT);
            CREATE TABLE pages (id INTEGER PRIMARY KEY, site TEXT, url TEXT);
            CREATE TABLE queries (id INTEGER PRIMARY KEY, text TEXT);
            CREATE TABLE gsc_query_daily (date TEXT, page_id INT, query_id INT, clicks INT, impressions INT,
                                          position REAL);""")
        con.execute("INSERT INTO urls VALUES (1, ?, 'https://matkinhtamduc.com/a/'), (2, ?, 'https://matkinhtamduc.com/b/')",
                    (SITE, SITE))
        con.execute("INSERT INTO url_groups VALUES (1, ?, 'SEO chủ lực'), (2, ?, 'Blog')", (SITE, SITE))
        con.executemany("INSERT INTO url_group_members VALUES (?, ?, '', '')", [(1, 1), (2, 1), (2, 2)])
        seo = BB.seo_urls(con, SITE)
        self.assertEqual({r["url"][-2:]: r["groups"] for r in seo}, {"a/": ["SEO chủ lực", "Blog"], "b/": ["Blog"]})
        con.execute("INSERT INTO pages VALUES (1, ?, 'https://matkinhtamduc.com/a/'), (2, ?, 'https://matkinhtamduc.com/b/')",
                    (SITE, SITE))
        con.execute("INSERT INTO queries VALUES (1, 'q1'), (2, 'q2')")
        con.executemany("INSERT INTO gsc_query_daily VALUES ('2026-11-01', ?, ?, 0, 100, 7)", [(1, 1), (2, 2)])
        only = {BB.norm(r["url"]) for r in seo if 1 in r["group_ids"]}
        res = BB.needs(con, SITE, {}, date(2026, 11, 6), only=only)
        self.assertEqual([r["url"][-2:] for r in res["rows"]], ["a/"])
        info = BB.url_info(con, SITE, "https://www.matkinhtamduc.com/a", {}, date(2026, 11, 6))
        self.assertIsNotNone(info["need"])
        self.assertEqual(info["built"], [])


def _gsc_db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE pages (id INTEGER PRIMARY KEY, site TEXT, url TEXT);
        CREATE TABLE queries (id INTEGER PRIMARY KEY, text TEXT);
        CREATE TABLE gsc_query_daily (date TEXT, page_id INT, query_id INT, clicks INT, impressions INT, position REAL);
        CREATE TABLE gsc_page_daily (date TEXT, page_id INT, clicks INT, impressions INT, position REAL);""")
    return con


class InternalTest(unittest.TestCase):
    def test_same_topic_pages_suggested(self):
        con = _gsc_db()
        urls = ["t", "zeiss", "hoya", "gong"]
        con.executemany("INSERT INTO pages VALUES (?, ?, ?)",
                        [(i + 1, SITE, f"https://matkinhtamduc.com/{u}/") for i, u in enumerate(urls)])
        qs = ["tròng kính đổi màu", "tròng kính zeiss đổi màu", "tròng kính hoya đổi màu", "gọng kính nam",
              "kính", "kính cận", "kính mát", "mắt kính"]
        con.executemany("INSERT INTO queries VALUES (?, ?)", [(i + 1, q) for i, q in enumerate(qs)])
        con.executemany("INSERT INTO gsc_query_daily VALUES ('2026-11-01', ?, ?, ?, ?, ?)", [
            (1, 1, 2, 400, 9.0), (2, 2, 50, 300, 3.0), (3, 3, 30, 200, 4.0), (4, 4, 90, 900, 2.0),
            (4, 5, 1, 50, 30.0), (2, 6, 1, 50, 30.0), (3, 7, 1, 50, 30.0), (1, 8, 1, 50, 30.0)])
        sg = BB.internal_suggestions(con, SITE, "https://matkinhtamduc.com/t", date(2026, 11, 6))
        self.assertEqual(sg["anchor"], "tròng kính đổi màu")
        self.assertEqual([r["url"].split("/")[-2] for r in sg["rows"]], ["zeiss", "hoya"])  # trang gọng: khác chủ đề

    def test_has_link(self):
        self.assertTrue(BB.has_link("https://bao.vn/bai", "https://matkinhtamduc.com/kinh-can",
                                    opener=lambda req, timeout=0: _Resp(HTML.encode())))
        self.assertFalse(BB.has_link("https://bao.vn/bai", "https://matkinhtamduc.com/khac-han",
                                     opener=lambda req, timeout=0: _Resp(HTML.encode())))


class EffectTest(unittest.TestCase):
    def test_before_after(self):
        from datetime import timedelta
        con = _gsc_db()
        con.execute("INSERT INTO pages VALUES (1, ?, 'https://matkinhtamduc.com/x/')", (SITE,))
        d0 = date(2026, 10, 1)
        rows = []
        for i in range(1, 29):
            rows.append(((d0 - timedelta(days=i)).isoformat(), 1, 2, 100, 12.0))
            rows.append(((d0 + timedelta(days=i)).isoformat(), 1, 5, 100, 8.0))
        con.executemany("INSERT INTO gsc_page_daily VALUES (?,?,?,?,?)", rows)
        link = {"url_to": "https://matkinhtamduc.com/x", "placed_on": d0.isoformat(), "url_from": "https://bao.vn/a",
                "cost": 3000000}
        ef = BB.effect(con, SITE, link, date(2026, 11, 6))
        self.assertEqual(ef["status"], "ok")
        self.assertAlmostEqual(ef["pos_change"], 4.0)
        self.assertAlmostEqual(ef["clicks_change"], 3.0)
        self.assertEqual(BB.effect(con, SITE, {**link, "placed_on": "2026-11-01"}, date(2026, 11, 6))["status"], "wait")
        self.assertEqual(BB.effect(con, SITE, {**link, "placed_on": None}, date(2026, 11, 6))["status"], "no_date")
        g = BB.effects_by_source(con, SITE, [link], date(2026, 11, 6))[0]
        self.assertEqual((g["host"], g["measured"]), ("bao.vn", 1))
        self.assertAlmostEqual(g["cost_per_click"], 3000000 / 90)


if __name__ == "__main__":
    unittest.main()


class DfsMatchTest(unittest.TestCase):
    def test_match_states_and_unrecorded(self):
        from datetime import date as _d

        from seo_report import backlink_build as BB_
        from seo_report import backlink_links as BLL
        rows = [{"id": 1, "url_from": "https://www.bao.vn/a/", "url_to": "https://s.vn/x", "placed_on": "2026-08-01"},
                {"id": 2, "url_from": "https://blog.vn/b", "url_to": "https://s.vn/y", "placed_on": "2026-08-01"},
                {"id": 3, "url_from": "https://new.vn/c", "url_to": "https://s.vn/z", "placed_on": "2026-11-01"},
                {"id": 4, "url_from": "https://gone.vn/d", "url_to": "https://s.vn/", "placed_on": "2026-06-01"},
                {"id": 5, "url_from": "https://nf.vn/e", "url_to": "https://s.vn/", "placed_on": "2026-06-01"}]
        sl = lambda f, t, **k: BLL.slim({"domain_from": f.split("/")[2], "url_from": f, "url_to": t, **k})  # noqa
        cur = [sl("https://bao.vn/a", "https://s.vn/x/", dofollow=True, first_seen="2026-08-05 00:00:00 +00:00",
                  anchor="kính"),
               sl("https://nf.vn/e", "https://s.vn/", dofollow=False),
               sl("https://pr.vn/new", "https://s.vn/", dofollow=True, first_seen="2026-11-01 00:00:00 +00:00")]
        prev = cur + [sl("https://gone.vn/d", "https://s.vn/")]
        data = {"fetched_at": "2026-11-12T00:00:00+00:00", "items": cur, "prev": {"items": prev}}
        m = BB_.dfs_match(rows, data)
        self.assertEqual({k: v["state"] for k, v in m.items()},
                         {1: "found", 2: "missing", 3: "waiting", 4: "lost", 5: "found_nofollow"})
        self.assertEqual(m[1]["first"], "2026-08-05")
        un = BB_.unrecorded(rows, data, {"pr.vn": ["Báo PR"], "bao.vn": ["Báo PR"]}, _d(2026, 11, 13))
        self.assertEqual([x["d_from"] for x in un], ["pr.vn"])  # bao.vn đã ghi; nf.vn không có nhãn
        self.assertEqual(BB_.dfs_match(rows, None)[1]["state"], "none")
