import json
import sqlite3
import unittest

from seo_report import backlink_links as BLL
from seo_report import link_audit as LA

HEAD = ("Page ascore,Source title,Source url,Target url,Anchor,External links,Internal links,Nofollow,Sponsored,Ugc,"
        "Text,Frame,Form,Image,Sitewide,First seen,Last seen,New link,Lost link\n")
CSV = (HEAD
       + "25,Bài A,https://www.bao.vn/a/,https://matkinhtamduc.com/x/,kính,68,218,false,false,false,true,false,false,"
         "false,false,2026-04-19,2026-08-13,false,false\n"
       + "20,Bài B,https://blog.vn/b,https://www.matkinhtamduc.com/,matkinhtamduc.com,150,3,true,true,false,true,false,"
         "false,true,true,2026-07-21,2026-07-21,true,false\n"
       + "10,Đã mất,https://gone.vn/c,https://matkinhtamduc.com/,x,1,1,false,false,false,true,false,false,false,false,"
         "2025-01-01,2025-02-01,false,true\n"
       + "10,Khác site,https://other.vn/d,https://khac.vn/,x,1,1,false,false,false,true,false,false,false,false,"
         "2025-01-01,2025-02-01,false,false\n")
SITE = "https://matkinhtamduc.com/"


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        BLL.ensure_tables(self.con)
        dfs = [BLL.slim({"domain_from": "bao.vn", "url_from": "https://bao.vn/a", "url_to": "https://matkinhtamduc.com/x",
                         "dofollow": True, "backlink_spam_score": 5, "url_to_status_code": 200})]
        self.con.execute("INSERT INTO backlink_link_runs VALUES (?, '2026-11-12T00:00:00+00:00', 1, 0, ?)",
                         (SITE, json.dumps(dfs)))

    def test_detect_parse_merge(self):
        self.assertEqual(BLL.detect(HEAD.strip().split(",")), "semrush")
        self.assertIsNone(BLL.detect(["Referring page URL", "Target URL"]))
        res = BLL.import_file(self.con, SITE, CSV.encode("utf-8-sig"), "f.csv", "u")
        self.assertEqual((res["count"], res["lost"], res["new_domains"]), (2, 1, 1))
        d = BLL.latest(self.con, SITE)
        by = {x["d_from"]: x for x in d["items"]}
        self.assertEqual(len(d["items"]), 2)  # bao.vn trùng: một dòng
        self.assertEqual(by["bao.vn"]["src"], ["dfs", "semrush"])
        self.assertEqual(by["bao.vn"]["ascore"], 25)
        b = by["blog.vn"]
        self.assertEqual((b["follow"], b["attrs"], b["type"], b["sitewide"], b["ext"]),
                         (False, ["nofollow", "sponsored"], "image", True, 150))
        keys = {c["key"] for c in LA.audit(d["items"], None, [], {}) if c["rows"]}
        self.assertIn("L_sitewide", keys)
        self.assertIn("L_farm", keys)
        self.assertEqual(BLL.diff(d["items"], [])[0][0]["d_from"], "bao.vn")  # link nhập không tính là "mới"

    def test_bad_file_and_targets(self):
        with self.assertRaises(ValueError):
            BLL.import_file(self.con, SITE, b"a,b\n1,2\n")
        BLL.import_file(self.con, SITE, CSV.encode("utf-8"))
        r = BLL.check_targets(self.con, SITE, fetcher=lambda u: {"status": 404, "final_url": None}, sleep=lambda s: None)
        self.assertEqual(r["broken"], 1)  # /x/ dùng lại mã 200 của DataForSEO, chỉ trang chủ được mở (giả lập 404)
        BLL.remove_import(self.con, SITE, "semrush")
        self.assertNotIn("imports", BLL.latest(self.con, SITE))
