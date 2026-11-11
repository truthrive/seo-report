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
