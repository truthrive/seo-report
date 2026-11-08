import io
import json
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError

from seo_report import aio
from seo_report import brand_entity as BE
from seo_report import db
from seo_report.config import KeywordSettings

HOME = """<html><head><script type="application/ld+json">{"@context": "https://schema.org", "@graph": [
 {"@type": ["Organization", "Optician"], "name": "Mắt Kính X", "url": "https://x.vn/", "logo": {"@type": "ImageObject",
  "url": "https://x.vn/logo.png"}, "sameAs": ["https://www.facebook.com/x", "https://www.youtube.com/@x"],
  "telephone": "0909", "address": {"@type": "PostalAddress", "streetAddress": "1 Lê Lợi", "addressLocality": "Q1"}},
 {"@type": "WebSite", "name": "X"}]}</script></head><body></body></html>"""


def kg_reply(items):
    return io.BytesIO(json.dumps({"itemListElement": [{"resultScore": s, "result": r} for s, r in items]}).encode())


class BrandEntityTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.cfg = SimpleNamespace(site_url="https://x.vn/", keywords=KeywordSettings(brand_terms=("mắt kính x",)),
                                   logo="")
        aio.brands(self.con, self.cfg)  # tạo dòng thương hiệu của mình
        aio.save_brand(self.con, self.cfg.site_url, "Kính Y", "", "y.vn")

    def tearDown(self):
        self.con.close()

    def test_org_schema_reads_graph(self):
        s = BE.org_schema(HOME)
        self.assertTrue(s["found"])
        self.assertEqual(s["name"], "Mắt Kính X")
        self.assertEqual(s["logo"], "https://x.vn/logo.png")
        self.assertEqual(BE.social(s["same_as"]), ["Facebook", "YouTube"])
        self.assertEqual(s["address"], "1 Lê Lợi, Q1")

    def test_pick_by_domain_or_org_name(self):
        brand = {"name": "Kính Y", "aliases": [], "domains": ["y.vn"]}
        res = [{"name": "Kính Y", "types": ["Thing"], "url": "", "score": 3},
               {"name": "Công ty Y", "types": ["Organization"], "url": "https://www.y.vn/", "score": 1}]
        self.assertEqual(BE.pick(res, brand)["match"], "domain")
        self.assertIsNone(BE.pick([{"name": "Kính Y", "types": ["Movie"], "url": "", "score": 9}], brand))
        self.assertEqual(BE.pick([{"name": "Kính Y Việt Nam", "types": ["Corporation"], "url": "", "score": 2}],
                                 brand)["match"], "name")

    def test_run_and_checklist(self):
        def opener(url, timeout=0):
            if "Y" in url:
                return kg_reply([])
            return kg_reply([(120.5, {"@id": "kg:/g/1", "name": "Mắt Kính X", "@type": ["Organization", "Thing"],
                                      "url": "https://x.vn/", "description": "Cửa hàng kính"})])
        r = BE.run(self.con, self.cfg, "k", opener=opener, home_fetch=lambda u: HOME)
        self.assertEqual((r["brands"], r["found"], r["error"]), (2, 1, None))
        lt = BE.latest(self.con, self.cfg)
        self.assertEqual([(b["name"], b["found"]) for b in lt["brands"]], [("Mắt Kính X", True), ("Kính Y", False)])
        ok = {c["code"]: c["ok"] for c in lt["checks"]}
        self.assertTrue(ok["kg"] and ok["kg_url"] and ok["kg_desc"] and ok["schema"] and ok["schema_core"]
                        and ok["nap"])
        self.assertFalse(ok["same_as"])  # mới 2 hồ sơ
        self.assertFalse(ok["wikidata"])

    def test_blocked_api_explained_and_schema_still_checked(self):
        def opener(url, timeout=0):
            raise HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b'{"error": {"message": "Requests to this API '
                                                                    b'kgsearch.googleapis.com ... are blocked."}}'))
        r = BE.run(self.con, self.cfg, "k", opener=opener, home_fetch=lambda u: HOME)
        self.assertIn("Knowledge Graph Search API", r["error"])
        lt = BE.latest(self.con, self.cfg)
        self.assertEqual(lt["error"], r["error"])
        ok = {c["code"]: c["ok"] for c in lt["checks"]}
        self.assertIsNone(ok["kg"])  # chưa biết, không phải "chưa đạt"
        self.assertTrue(ok["schema"])


if __name__ == "__main__":
    unittest.main()
