import json
import sqlite3
import unittest
from types import SimpleNamespace

from seo_report import backlink_gap as BG
from seo_report import rank as R


def _item(dom, rank, links=3, spam=0, seen="2026-05-01 10:00:00 +00:00"):
    return {"domain_intersection": {"1": {"target": dom, "rank": rank, "backlinks": links,
                                          "backlinks_spam_score": spam, "first_seen": seen}},
            "summary": {"intersections_count": 1}}


class FakeClient:
    def __init__(self, data):
        self.data, self.calls = data, []

    def _live(self, endpoint, body):
        self.calls.append((endpoint, body))
        dom = body["targets"]["1"]
        if dom == "loi.vn":
            raise RuntimeError("DataForSEO 40501: lỗi")
        return {"total_count": len(self.data[dom]), "items": self.data[dom]}, 0.0276


CFG = SimpleNamespace(site_url="https://matkinhtamduc.com/",
                      rank=SimpleNamespace(paused=False, monthly_budget_usd=50.0), dataforseo_secret="")


class GapTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        R.ensure_tables(self.con)

    def test_merge_and_save(self):
        cl = FakeClient({"a.vn": [_item("www.vnexpress.net", 800), _item("blog.x.vn", 120),
                                  _item("matkinhtamduc.com", 500)],
                         "b.vn": [_item("vnexpress.net", 780, spam=5), _item("diendan.vn", 300, spam=60)]})
        chosen = [{"name": "A", "domain": "a.vn"}, {"name": "B", "domain": "b.vn"}, {"name": "Lỗi", "domain": "loi.vn"}]
        logs = []
        res = BG.fetch(self.con, CFG, chosen, "team", client=cl, log=logs.append)
        self.assertEqual(res["rivals"], 2)
        self.assertEqual(len(logs), 1)  # đối thủ lỗi: báo, không chặn đối thủ khác
        body = cl.calls[0][1]
        self.assertEqual(body["exclude_targets"], ["matkinhtamduc.com"])
        self.assertEqual(body["backlinks_filters"], [["dofollow", "=", True]])
        g = BG.latest(self.con, CFG.site_url)
        doms = [x["domain"] for x in g["items"]]
        self.assertEqual(doms[0], "vnexpress.net")  # trỏ về 2 đối thủ: lên đầu
        self.assertNotIn("matkinhtamduc.com", doms)  # chính mình: bỏ
        self.assertEqual(g["items"][0]["rivals"], ["A", "B"])
        self.assertEqual(g["items"][0]["first_seen"], "2026-05-01")
        spent = self.con.execute("SELECT SUM(cost) FROM backlink_runs WHERE kind = 'gap'").fetchone()[0]
        self.assertAlmostEqual(spent, 0.0552)

    def test_budget_blocks_before_calling(self):
        cfg = SimpleNamespace(**{**CFG.__dict__, "rank": SimpleNamespace(paused=False, monthly_budget_usd=0.01)})
        cl = FakeClient({"a.vn": []})
        with self.assertRaises(RuntimeError):
            BG.fetch(self.con, cfg, [{"name": "A", "domain": "a.vn"}], client=cl)
        self.assertEqual(cl.calls, [])

    def test_estimate(self):
        self.assertAlmostEqual(BG.estimate(5), 5 * (0.024 + 0.000036 * BG.LIMIT), places=4)


if __name__ == "__main__":
    unittest.main()


class ByRivalTest(unittest.TestCase):
    def test_gap_per_rival_from_last_run(self):
        import json
        import sqlite3
        from types import SimpleNamespace
        from unittest import mock

        from seo_report import backlink_gap as BG
        con = sqlite3.connect(":memory:")
        cfg = SimpleNamespace(site_url="https://me.vn/")
        self.assertIsNone(BG.by_rival(con, cfg))
        con.execute("INSERT INTO backlink_gap VALUES (?, '2026-11-11T02:00:00+00:00', 'a', ?, ?, 0.2)",
                    (cfg.site_url, json.dumps([{"name": "A", "domain": "a.vn", "total": 10},
                                               {"name": "B", "domain": "www.b.vn", "total": 30}]),
                     json.dumps([{"domain": "x.com", "rivals": ["A", "B"], "spam": 0},
                                 {"domain": "y.com", "rivals": ["A", "B"], "spam": 80},
                                 {"domain": "z.com", "rivals": ["A"], "spam": 0}])))
        rv = [{"id": 1, "name": "A", "domain": "a.vn"}, {"id": 2, "name": "B", "domain": "b.vn"},
              {"id": 3, "name": "C", "domain": "c.vn"}]
        with mock.patch.object(BG, "rivals", return_value=rv):
            g = BG.by_rival(con, cfg)
        self.assertEqual([(r["name"], r["total"]) for r in g["rows"]], [("B", 30), ("A", 10)])
        self.assertEqual((g["missing"], g["shared"]), (["C"], 1))  # y.com là spam: không tính


class LinksClient:
    def __init__(self):
        self.calls = []

    def _live(self, endpoint, body):
        self.calls.append((endpoint, body))
        if body["target"] == "b.vn":
            return {"items": [{"domain_from": "m.vnexpress.net", "url_from": "https://m.vnexpress.net/x",
                               "page_from_title": " Bài  B ", "url_to": "https://b.vn/", "anchor": "kính",
                               "first_seen": "2026-03-02 00:00:00 +00:00", "page_from_rank": 300,
                               "dofollow": True},
                              {"domain_from": "notvnexpress.net", "url_from": "https://notvnexpress.net/y"}]}, 0.0241
        return {"items": [{"domain_from": "vnexpress.net", "url_from": "https://vnexpress.net/a",
                           "url_to": "https://a.vn/p", "anchor": "mắt kính", "dofollow": False,
                           "attributes": ["nofollow", "sponsored", "noopener"]}]}, 0.0241


class GapLinksTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        R.ensure_tables(self.con)
        cl = FakeClient({"a.vn": [_item("vnexpress.net", 800)], "b.vn": [_item("vnexpress.net", 780)]})
        BG.fetch(self.con, CFG, [{"name": "A", "domain": "a.vn"}, {"name": "B", "domain": "b.vn"}], "team",
                 client=cl)

    def test_fetch_links_per_rival_and_save(self):
        self.assertEqual([t["domain"] for t in BG.link_targets(self.con, CFG, "vnexpress.net")], ["a.vn", "b.vn"])
        self.assertAlmostEqual(BG.links_estimate(self.con, CFG, "vnexpress.net"), 2 * BG.COST_TASK + 6 * BG.COST_ROW, places=4)
        cl = LinksClient()
        res = BG.fetch_links(self.con, CFG, "vnexpress.net", "team", client=cl)
        self.assertEqual(len(cl.calls), 2)
        self.assertEqual(cl.calls[0][0], "backlinks")
        self.assertNotIn(["dofollow", "=", True], cl.calls[0][1]["filters"])  # lấy cả nofollow
        self.assertEqual((res["links"][0]["dofollow"], res["links"][1]["dofollow"]), (False, True))
        self.assertEqual(res["links"][0]["attrs"], ["nofollow", "sponsored"])
        self.assertEqual([(x["rival"], x["url_from"]) for x in res["links"]],
                         [("A", "https://vnexpress.net/a"), ("B", "https://m.vnexpress.net/x")])  # tên miền khác: bỏ
        self.assertEqual(res["links"][1]["title"], "Bài B")
        self.assertEqual(res["links"][1]["first_seen"], "2026-03-02")
        saved = BG.saved_links(self.con, CFG.site_url)["vnexpress.net"]
        self.assertEqual(len(saved["links"]), 2)
        kind = self.con.execute("SELECT kind, cost FROM backlink_runs ORDER BY rowid DESC").fetchone()
        self.assertEqual(kind[0], "gap_links")
        self.assertAlmostEqual(kind[1], 0.0482)

    def test_unknown_domain(self):
        with self.assertRaises(RuntimeError):
            BG.fetch_links(self.con, CFG, "khong-co.vn", client=LinksClient())


class ExtraRivalsTest(unittest.TestCase):
    def test_add_validate_remove(self):
        con = sqlite3.connect(":memory:")
        R.ensure_tables(con)
        from unittest import mock
        with mock.patch.object(BG, "rivals", lambda c, cfg: [{"id": 1, "name": "A", "domain": "a.vn"}]):
            x = BG.add_extra(con, CFG, "https://www.KinhABC.vn/trang", "team")
            self.assertEqual(x["domain"], "kinhabc.vn")
            for bad in ("abc", "matkinhtamduc.com", "kinhabc.vn", "a.vn", "http://"):
                with self.assertRaises(RuntimeError):
                    BG.add_extra(con, CFG, bad)
            self.assertEqual([r["domain"] for r in BG.all_rivals(con, CFG)], ["a.vn", "kinhabc.vn"])
            BG.remove_extra(con, CFG.site_url, "kinhabc.vn")
            self.assertEqual(len(BG.all_rivals(con, CFG)), 1)


class PerRivalTest(unittest.TestCase):
    def test_refetch_one_keeps_others(self):
        con = sqlite3.connect(":memory:")
        R.ensure_tables(con)
        cl = FakeClient({"a.vn": [_item("vnexpress.net", 800, links=4), _item("x.vn", 100)],
                         "b.vn": [_item("vnexpress.net", 780, links=6)]})
        BG.fetch(con, CFG, [{"name": "A", "domain": "a.vn"}, {"name": "B", "domain": "b.vn"}], "team", client=cl)
        cl.data["b.vn"] = [_item("vnexpress.net", 790, links=9), _item("y.vn", 50)]
        BG.fetch(con, CFG, [{"name": "B", "domain": "b.vn"}], "team", client=cl)
        g = BG.latest(con, CFG.site_url)
        self.assertEqual(sorted(r["domain"] for r in g["rivals"]), ["a.vn", "b.vn"])  # A vẫn còn
        items = {x["domain"]: x for x in g["items"]}
        self.assertEqual(items["vnexpress.net"]["backlinks"], 13)
        self.assertEqual(set(items), {"vnexpress.net", "x.vn", "y.vn"})
        BG.remove_result(con, CFG.site_url, "b.vn")
        self.assertEqual({x["domain"] for x in BG.latest(con, CFG.site_url)["items"]}, {"vnexpress.net", "x.vn"})

    def test_legacy_migration(self):
        con = sqlite3.connect(":memory:")
        BG.ensure_tables(con)
        legacy = [{"domain": "v.vn", "rank": 5, "rivals": ["A", "B"], "backlinks": 10, "spam": 0, "first_seen": None},
                  {"domain": "w.vn", "rank": 3, "rivals": ["A"], "backlinks": 2, "spam": 0, "first_seen": None}]
        con.execute("INSERT INTO backlink_gap VALUES (?, ?, ?, ?, ?, ?)",
                    (CFG.site_url, "2026-10-01T00:00:00+00:00", "x", json.dumps(
                        [{"name": "A", "domain": "a.vn", "total": 2}, {"name": "B", "domain": "b.vn", "total": 1}]),
                     json.dumps(legacy), 0.05))
        self.assertEqual(set(BG.fetched(con, CFG.site_url)), {"a.vn", "b.vn"})
        BG.rebuild(con, CFG.site_url)
        items = {x["domain"]: x for x in BG.latest(con, CFG.site_url)["items"]}
        self.assertEqual((items["v.vn"]["backlinks"], items["w.vn"]["backlinks"]), (10, 2))  # tổng cũ giữ nguyên
        cl = FakeClient({"b.vn": [_item("v.vn", 5, links=3)]})
        BG.fetch(con, CFG, [{"name": "B", "domain": "b.vn"}], client=cl)
        v = {x["domain"]: x for x in BG.latest(con, CFG.site_url)["items"]}["v.vn"]
        self.assertTrue(v.get("partial"))  # phần của A chưa tách được: hiện "≥"


class MultiTest(unittest.TestCase):
    def test_multi_merges_with_full(self):
        con = sqlite3.connect(":memory:")
        R.ensure_tables(con)
        BG.fetch(con, CFG, [{"name": "A", "domain": "a.vn"}], client=FakeClient(
            {"a.vn": [_item("v.vn", 50, links=2), _item("only-a.vn", 10)]}))

        class C:
            calls = []

            def _live(self, ep, body):
                self.calls.append(body)
                return {"total_count": 2, "items": [
                    {"domain_intersection": {"1": {"target": "v.vn", "rank": 60, "backlinks": 5},
                                             "2": {"target": "v.vn", "rank": 60, "backlinks": 7}}},
                    {"domain_intersection": {"1": None, "2": {"target": "www.w.vn", "rank": 9, "backlinks": 1},
                                             "3": {"target": "w.vn", "rank": 9, "backlinks": 1}}}]}, 0.027
        cl = C()
        with self.assertRaises(RuntimeError):
            BG.fetch_multi(con, CFG, [{"name": "A", "domain": "a.vn"}], client=cl)
        res = BG.fetch_multi(con, CFG, [{"name": "A", "domain": "a.vn"}, {"name": "B", "domain": "b.vn"},
                                        {"name": "C", "domain": "c.vn"}], client=cl)
        self.assertEqual(cl.calls[0]["intersection_mode"], "partial")
        self.assertEqual(res["sites"], 2)
        g = BG.latest(con, CFG.site_url)
        items = {x["domain"]: x for x in g["items"]}
        self.assertEqual(items["v.vn"]["rivals"], ["A", "B"])
        self.assertEqual(items["v.vn"]["backlinks"], 12)  # số mới hơn của A (5) + B (7)
        self.assertIn("only-a.vn", items)  # kết quả đầy đủ của A vẫn giữ
        self.assertEqual(items["w.vn"]["rivals"], ["B", "C"])
        BG.remove_result(con, CFG.site_url, "c.vn")
        self.assertEqual({x["domain"]: x for x in BG.latest(con, CFG.site_url)["items"]}["w.vn"]["rivals"], ["B"])
