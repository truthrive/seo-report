import unittest

from seo_report import crawl, db
from seo_report import urls as U

SITE = "https://matkinhtamduc.com/"
BASE = "https://matkinhtamduc.com"


def page(url, clicks=1):
    return {"keys": [url], "clicks": clicks, "impressions": clicks * 10, "ctr": 0, "position": 5.0}


class NormalizeTest(unittest.TestCase):
    def test_strips_fragment_and_tracking_keeps_other_params(self):
        self.assertEqual(U.normalize(f"{BASE}/mat-kinh-bi-xuoc/#nguyen-nhan"), f"{BASE}/mat-kinh-bi-xuoc/")
        self.assertEqual(U.normalize(f"{BASE}/dat-lich-hen/?utm_source=gmb&utm_campaign=quan-7"), f"{BASE}/dat-lich-hen/")
        self.assertEqual(U.normalize(f"{BASE}/gong-kinh/x/?page=2&gclid=abc"), f"{BASE}/gong-kinh/x/?page=2")
        self.assertEqual(U.normalize("matkinhtamduc.com/gong-kinh/"), f"{BASE}/gong-kinh/")

    def test_rules(self):
        cases = {
            "/": U.HOME,
            "/gong-kinh/": U.CATEGORY,
            "/trong-kinh-chinh-hang/trong-kinh-zeiss/": U.BRAND,
            "/gong-kinh/gong-td-design/gong-kinh-povino/": U.BRAND,
            "/bo-suu-tap/gong-kinh/": U.CATEGORY,
            "/cua-hang-mat-kinh-quan-1/": U.STORE,
            "/chinh-sach-bao-hanh/": U.INFO,
            "/2021/09/29/gong-kinh-tre-em/": U.LEGACY,
            "/category/cham-soc-mat/page/3/": U.LEGACY,
            "/?post_type=product&p=80030": U.LEGACY,
            "/gong-kinh-levius-83713/": None,
            "/mat-xech-la-gi/": None,
        }
        for path, expected in cases.items():
            self.assertEqual(U.classify_by_rules(BASE + path)[0], expected, path)

    def test_schema(self):
        product = '<script type="application/ld+json">{"@type":"Product"}</script>'
        article = '<script type="application/ld+json">{"@graph":[{"@type":"Article"}]}</script>'
        self.assertEqual(crawl.type_from_html(product)[0], U.PRODUCT)
        self.assertEqual(crawl.type_from_html(article)[0], U.BLOG)
        self.assertEqual(crawl.type_from_html("<html></html>")[0], U.CATEGORY)


class GroupTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        db.replace_day(self.con, SITE, "2099-01-01",
                       [page(f"{BASE}/mat-kinh-bi-xuoc/", 10), page(f"{BASE}/mat-kinh-bi-xuoc/#a", 2),
                        page(f"{BASE}/gong-kinh/", 5), page(f"{BASE}/?p=1", 9)], [])
        U.assign_urls(self.con, SITE)
        self.gid = U.ensure_group(self.con, SITE)

    def test_fragment_rows_merge_into_one_url(self):
        rows = {r["url"]: r for r in U.all_urls(self.con, SITE, days=100000)}
        self.assertEqual(rows[f"{BASE}/mat-kinh-bi-xuoc/"]["clicks"], 12)
        self.assertEqual(len(rows), 3)

    def test_paste_matches_variants_and_logs(self):
        text = "matkinhtamduc.com/gong-kinh\nhttps://www.matkinhtamduc.com/mat-kinh-bi-xuoc/#x  khong-phai-link\n" \
               f"{BASE}/trang-moi/\n{BASE}/gong-kinh/"
        r = U.add_to_group(self.con, SITE, self.gid, text, "test")
        self.assertEqual(r["added"], [f"{BASE}/gong-kinh/", f"{BASE}/mat-kinh-bi-xuoc/", f"{BASE}/trang-moi/"])
        self.assertEqual(r["no_data"], [f"{BASE}/trang-moi/"])
        self.assertEqual(r["invalid"], ["khong-phai-link"])
        self.assertEqual(r["already"], [])
        again = U.add_to_group(self.con, SITE, self.gid, f"{BASE}/gong-kinh/", "test")
        self.assertEqual(again["already"], [f"{BASE}/gong-kinh/"])
        self.assertEqual(len(U.recent_changes(self.con, SITE)), 3)

    def test_suggestions_skip_members_and_legacy(self):
        U.add_to_group(self.con, SITE, self.gid, f"{BASE}/gong-kinh/", "test")
        urls = [s["url"] for s in U.suggestions(self.con, SITE, self.gid, days=100000)]
        self.assertEqual(urls, [f"{BASE}/mat-kinh-bi-xuoc/"])

    def test_manual_type_wins_and_remove_keeps_data(self):
        U.add_to_group(self.con, SITE, self.gid, f"{BASE}/gong-kinh/", "test")
        member = U.group_members(self.con, self.gid, days=100000)[0]
        U.set_type(self.con, SITE, [member["id"]], U.INFO, "test")
        U.remove_from_group(self.con, SITE, self.gid, [member["id"]], "test")
        self.assertEqual(U.group_members(self.con, self.gid), [])
        row = self.con.execute("SELECT type, type_source FROM urls WHERE id = ?", (member["id"],)).fetchone()
        self.assertEqual(row, (U.INFO, "manual"))

    def test_classify_pending_only_touches_unknown(self):
        seen = []
        n = crawl.classify_pending(self.con, SITE, fetch=lambda u: (seen.append(u), (U.BLOG, ""))[1],
                                   log=lambda *a, **k: None, sleep=lambda *_: None)
        self.assertEqual((n, seen), (1, [f"{BASE}/mat-kinh-bi-xuoc/"]))


if __name__ == "__main__":
    unittest.main()
