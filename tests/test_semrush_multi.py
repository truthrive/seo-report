import json
import sqlite3
import unittest

from seo_report import backlink_gap as BG
from seo_report import backlink_links as BLL
from seo_report import semrush as SR

SITE = "https://matkinhtamduc.com/"
REF = ("Domain ascore,Domain,Backlinks,IP Address,Country,First seen,Last seen\n"
       "48,baoangiang.com.vn,409,103.1.1.1,vn,2025-11-14,2026-10-25\n"
       "39,bao.vn,10,9.9.9.9,vn,2025-12-06,2026-11-02\n"
       "20,p1.vn,5,45.1.2.3,us,2025-01-01,2026-01-01\n20,p2.vn,5,45.1.2.4,us,2025-01-01,2026-01-01\n"
       "20,p3.vn,5,45.1.2.5,us,2025-01-01,2026-01-01\n")
BL = ("Page ascore,Source title,Source url,Target url,Anchor,External links,Internal links,Nofollow,Sponsored,Ugc,Text,"
      "Frame,Form,Image,Sitewide,First seen,Last seen,New link,Lost link\n"
      "30,Bài,https://baoangiang.com.vn/a,https://matkinhshady.com/x,kính,5,5,false,false,false,true,false,false,false,"
      "false,2026-01-01,2026-02-01,false,false\n")


class MultiImportTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        BG.ensure_tables(self.con)
        BLL.ensure_tables(self.con)
        mine = [BLL.slim({"domain_from": "bao.vn", "url_from": "https://bao.vn/z", "url_to": SITE})]
        self.con.execute("INSERT INTO backlink_link_runs VALUES (?, '2026-11-12T00:00:00+00:00', 1, 0, ?)",
                         (SITE, json.dumps(mine)))

    def test_preview_detects_kind_owner_role(self):
        rivals = [{"name": "Shady", "domain": "matkinhshady.com"}]
        pv = SR.preview(REF.encode(), "matkinhshady.com-backlinks_refdomains.csv", SITE, rivals)
        self.assertEqual((pv["kind"], pv["owner"], pv["role"], pv["rival"]),
                         ("refdomains", "matkinhshady.com", "rival", "Shady"))
        pv = SR.preview(REF.encode(), "matkinhtamduc.com-refdomains.csv", SITE, rivals)
        self.assertEqual(pv["role"], "own")
        pv = SR.preview(BL.encode(), "export.csv", SITE, rivals)  # tên file không có tên miền: theo trang đích
        self.assertEqual((pv["kind"], pv["owner"], pv["role"]), ("backlinks", "matkinhshady.com", "rival"))
        self.assertIn("error", SR.preview(b"a,b\n1,2", "x.csv", SITE, rivals))

    def test_rival_gap_and_own_enrich(self):
        SR.save(self.con, SITE, "matkinhshady.com", "refdomains", REF.encode(), "f.csv")
        SR.save(self.con, SITE, "matkinhshady.com", "backlinks", BL.encode(), "g.csv")
        SR.set_name(self.con, SITE, "matkinhshady.com", "Shady")
        BG.rebuild(self.con, SITE)
        g = BG.latest(self.con, SITE)
        doms = {x["domain"]: x for x in g["items"]}
        self.assertNotIn("bao.vn", doms)  # đã trỏ về mình: không vào GAP
        self.assertEqual(doms["baoangiang.com.vn"]["rivals"], ["Shady"])
        self.assertEqual((doms["baoangiang.com.vn"]["ascore"], doms["baoangiang.com.vn"]["country"]), (48, "VN"))
        self.assertEqual(doms["baoangiang.com.vn"]["src"], ["semrush"])
        self.assertEqual(g["rivals"][0]["total"], 4)
        links = SR.rival_links(self.con, SITE, "baoangiang.com.vn")
        self.assertEqual((links[0]["rival"], links[0]["anchor"]), ("Shady", "kính"))
        # file Referring Domains của website mình: bổ sung IP / quốc gia cho link
        SR.save(self.con, SITE, "matkinhtamduc.com", "refdomains", REF.encode(), "own.csv")
        d = BLL.latest(self.con, SITE)
        self.assertEqual((d["items"][0]["ip"], d["items"][0]["country"]), ("9.9.9.9", "VN"))
        BG.rebuild(self.con, SITE)  # website trong file của mình cũng tính là đã trỏ về
        self.assertEqual(BG.latest(self.con, SITE)["items"], [])
