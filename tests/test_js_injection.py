"""Chuỗi do người dùng nhập không được thoát vào mã JavaScript, thuộc tính HTML hay tooltip dạng HTML."""
import json
import sqlite3
import unittest

from seo_report import okr as O
from seo_report import projects as PJ
from seo_report import site_labels as SL
from seo_report import static_site as S
from seo_report import web as W
from seo_report import web_rivals as WR

from tests.test_okr_tool import _seed

QUOTE = 'https://a.example/x" innerHTML="<img src=x onerror=alert(1)>'


class OkrLinkTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        _seed(self.con)

    def test_safe_link(self):
        self.assertTrue(O.safe_link("https://docs.google.com/document/d/abc_123/edit?usp=sharing#x"))
        for bad in (QUOTE, "javascript:alert(1)", "https://a.example/ x", "https://a.example/'", "https://a.example/<b>",
                    "https://a.example/`", "https://a.example/\\x", "ftp://a.example/", "", "https://" + "a" * 3000):
            self.assertFalse(O.safe_link(bad), bad[:40])

    def test_set_links_rejects_quote_breakout(self):
        with self.assertRaises(ValueError):
            O.set_links(self.con, "O1.02", [QUOTE])
        O.set_links(self.con, "O1.02", ["https://a.example/ok", "https://a.example/ok"])
        item = next(i for i in O.load_items(self.con) if i["uid"] == "O1.02") if hasattr(O, "load_items") else None
        if item is not None:
            self.assertEqual(O.links(item), ["https://a.example/ok"])

    def test_update_item_link_goes_through_same_check(self):
        with self.assertRaises(ValueError):  # đường hộp chi tiết trước đây ghi thẳng, không kiểm gì
            O.update_item(self.con, "O1.02", link="javascript:alert(1)")
        with self.assertRaises(ValueError):
            O.update_item(self.con, "O1.02", link="https://a.example/ok\n" + QUOTE)
        O.update_item(self.con, "O1.02", link="https://a.example/1\nhttps://a.example/2")

    def test_links_drops_unsafe_synced_values(self):
        it = {"link": "https://a.example/ok\n" + QUOTE + "\njavascript:alert(1)\n  https://b.example/y  "}
        self.assertEqual(O.links(it), ["https://a.example/ok", "https://b.example/y"])


class SiteUrlJsTest(unittest.TestCase):
    def test_format_js_embeds_site_as_json_string(self):
        site = "https://a.com/x'),alert(1),('/"
        js = W.url_format_js(site)
        self.assertEqual(js, f"val => (val || '').replace({json.dumps(site.rstrip('/'))}, '') || '/'")
        self.assertNotIn("'),alert(1)", js.replace(json.dumps(site.rstrip('/')), ""))
        ls = chr(0x2028)  # ký tự phân dòng của JavaScript phải được thoát, không để nguyên trong mã
        out = W.url_format_js("https://a.com/" + ls + "x/")
        self.assertNotIn(ls, out)
        self.assertIn(chr(92) + "u2028", out)

    def test_valid_site_url_rejects_code_characters(self):
        self.assertTrue(PJ.valid_site_url("https://abc.com/"))
        self.assertTrue(PJ.valid_site_url("https://abc.com/blog/"))
        self.assertTrue(PJ.valid_site_url("sc-domain:abc.com"))
        for bad in ("https://a.com/x'),alert(1),('/", 'https://a.com/x"/', "https://a.com/<b>/", "https://a.com/`/",
                    "https://a.com/\\x/", "https://a'.com/"):
            self.assertFalse(PJ.valid_site_url(bad), bad)


class LabelJsTest(unittest.TestCase):
    def test_sort_js_uses_only_the_column_index(self):
        self.assertEqual(WR.sort_js(3), "(a, b, ra, rb) => (ra['_3'] || 0) - (rb['_3'] || 0)")
        with self.assertRaises(ValueError):
            WR.sort_js("']),alert(1),(['")

    def test_tooltip_escapes_the_name(self):
        self.assertIn("esc(p.name)", WR.TIP_JS)
        self.assertNotIn("p => p.name", WR.TIP_JS)

    def test_label_name_rejects_code_characters(self):
        con = sqlite3.connect(":memory:")
        self.assertEqual(SL.add_def(con, "Báo PR (chính)")["name"], "Báo PR (chính)")
        for bad in ("']),alert(1),(['", 'a"b', "a<b", "a`b", "a\\b", "a{b}"):
            with self.assertRaises(ValueError, msg=bad):
                SL.add_def(con, bad)


class StaticGanttTest(unittest.TestCase):
    def test_gantt_name_is_html_escaped(self):
        i = {"code": "O1.02", "title": "<img src=x onerror=alert(1)>", "start": "2026-10-21", "end": "2026-11-27",
             "status": O.TODO, "wait": None}
        name = S.gantt_name(i)
        self.assertNotIn("<img", name)
        self.assertIn("&lt;img", name)


if __name__ == "__main__":
    unittest.main()
