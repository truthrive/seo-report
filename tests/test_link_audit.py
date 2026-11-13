import sqlite3
import unittest

from seo_report import backlink_links as BLL
from seo_report import backlinks as BL
from seo_report import link_audit as LA


def raw(i, dom, to="https://s.vn/", **kw):
    it = {"domain_from": dom, "url_from": f"https://{dom}/p{i}", "url_to": to, "anchor": kw.pop("anchor", "mắt kính"),
          "dofollow": kw.pop("dofollow", True), "item_type": kw.pop("item_type", "anchor"),
          "semantic_location": kw.pop("loc", "article"), "domain_from_rank": 100, "backlink_spam_score": 0,
          "page_from_language": "vi", "domain_from_country": "VN", "domain_from_ip": kw.pop("ip", f"9.9.{i}.1"),
          "first_seen": "2026-10-01 00:00:00 +00:00", "url_to_status_code": 200}
    it.update(kw)
    return it


class Client:
    def __init__(self, n):
        self.n, self.calls = n, []

    def _live(self, ep, body):
        self.calls.append(body)
        off, lim = body["offset"], body["limit"]
        return {"total_count": self.n, "items": [raw(i, f"d{i}.vn") for i in range(off, min(off + lim, self.n))]}, 0.03


class FetchTest(unittest.TestCase):
    def test_pages_cap_keep_and_diff(self):
        con = sqlite3.connect(":memory:")
        BL.ensure_tables(con)
        cl = Client(2300)
        BLL.fetch(con, "s", cl, "s.vn", log=lambda m: None)
        self.assertEqual([c["offset"] for c in cl.calls], [0, 1000, 2000])
        d = BLL.latest(con, "s")
        self.assertEqual((len(d["items"]), d["total"], d["prev"]), (2300, 2300, None))
        self.assertAlmostEqual(BLL.estimate(656), 0.024 + 656 * 0.000036, places=4)
        for _ in range(BLL.KEEP + 1):
            BLL.fetch(con, "s", Client(3), "s.vn", log=lambda m: None)
        self.assertLessEqual(con.execute("SELECT COUNT(*) FROM backlink_link_runs").fetchone()[0], BLL.KEEP)
        a, b = [BLL.slim(raw(1, "a.vn")), BLL.slim(raw(2, "b.vn"))], [BLL.slim(raw(2, "b.vn")), BLL.slim(raw(3, "c.vn"))]
        new, lost = BLL.diff(a, b)
        self.assertEqual(([x["d_from"] for x in new], [x["d_from"] for x in lost]), (["a.vn"], ["c.vn"]))
        self.assertEqual(len(BLL.for_page(a, "http://www.s.vn")), 2)
        self.assertEqual(len(BLL.for_site(a, "www.a.vn")), 1)


class AuditTest(unittest.TestCase):
    def test_checks(self):
        items = [BLL.slim(x) for x in [
            raw(1, "a.vn", url_to_status_code=404, is_broken=True),
            raw(2, "spam.vn", backlink_spam_score=80),
            raw(3, "p1.vn", ip="45.1.2.3"), raw(4, "p2.vn", ip="45.1.2.3"), raw(5, "p3.vn", ip="45.1.2.9"),
            raw(6, "cf1.vn", ip="104.16.1.1"), raw(7, "cf2.vn", ip="104.16.1.1"), raw(8, "cf3.vn", ip="104.16.1.1"),
            raw(9, "f.vn", loc="footer"), raw(10, "img.vn", item_type="image", alt=""),
            raw(11, "en.com", page_from_language="en", domain_from_country="US"),
            raw(12, "news.vn", domain_from_platform_type=["news"], ranked_keywords_info={
                "page_from_keywords_count_top_10": 3}),
        ]] + [BLL.slim(raw(20 + i, f"k{i}.vn", to="https://s.vn/gong/", anchor="gọng kính giá rẻ")) for i in range(5)]
        got = {c["key"]: c for c in LA.audit(items, None, ["tam duc"], {})}
        self.assertEqual([x["d_from"] for x in got["L_broken"]["rows"]], ["a.vn"])
        self.assertEqual([x["d_from"] for x in got["L_spam"]["rows"]], ["spam.vn"])
        self.assertEqual(got["L_pbn"]["count"], 3)  # p1-p3 (cùng dải /24); IP Cloudflare không tính
        self.assertEqual([x["d_from"] for x in got["L_sitewide"]["rows"]], ["f.vn"])
        self.assertEqual([x["d_from"] for x in got["L_img_alt"]["rows"]], ["img.vn"])
        self.assertEqual([x["d_from"] for x in got["L_foreign"]["rows"]], ["en.com"])
        self.assertEqual(got["L_anchor_page"]["count"], 2)  # trang chủ và /gong/ đều dồn anchor từ khóa
        self.assertEqual(got["L_platform"]["suggest"], {"news.vn": ["Báo PR"]})
        self.assertIn("news.vn", [x["d_from"] for x in got["L_quality"]["rows"]])
        self.assertNotIn("L_lost", got)  # chưa có lần trước
        self.assertEqual(got["L_broken"]["level"], "high")
        self.assertIn("domain:spam.vn", LA.disavow(items))
        got2 = {c["key"]: c for c in LA.audit(items[1:], items, [], {"news.vn": ["Báo PR"]})}
        self.assertEqual([x["d_from"] for x in got2["L_lost"]["rows"]], ["a.vn"])
        self.assertEqual(got2["L_platform"]["count"], 0)  # đã gắn nhãn: không gợi ý
