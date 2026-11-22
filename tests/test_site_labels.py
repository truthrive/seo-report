import sqlite3
import unittest

from seo_report import site_labels as SL


class SiteLabelsTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        SL.ensure(self.con)

    def test_defaults_add_apply_lookup(self):
        self.assertEqual(SL.defs(self.con)[0]["name"], "Textlink")
        x = SL.add_def(self.con, "  Guest   post ", "", "u")
        self.assertEqual(x["name"], "Guest post")
        self.assertEqual(SL.add_def(self.con, "guest post")["name"], "Guest post")  # trùng: trả nhãn cũ
        with self.assertRaises(ValueError):
            SL.add_def(self.con, "  ")
        n = SL.apply(self.con, ["https://www.BaoAnGiang.com.vn/x", "baoangiang.com.vn", "abc.vn"],
                     add=["Báo PR", "Textlink", "Lạ"], user="u")
        self.assertEqual(n, 2)
        t = SL.all_labels(self.con)
        self.assertEqual(t["baoangiang.com.vn"], ["Textlink", "Báo PR"])  # theo thứ tự nhãn, bỏ nhãn chưa có
        self.assertEqual(SL.lookup(t, "m.baoangiang.com.vn"), ["Textlink", "Báo PR"])  # website con: theo cha
        self.assertEqual(SL.lookup(t, "com.vn"), [])
        SL.apply(self.con, ["abc.vn"], remove=["Textlink"])
        self.assertEqual(SL.all_labels(self.con)["abc.vn"], ["Báo PR"])
        SL.remove_def(self.con, "Báo PR")
        self.assertNotIn("abc.vn", SL.all_labels(self.con))

    def test_by_rival(self):
        SL.apply(self.con, ["a.vn"], add=["Textlink"])
        SL.apply(self.con, ["b.vn"], add=["Textlink", "PBN"])
        pairs = {"Shady": {"a.vn": {"backlinks": 10}, "b.vn": {"backlinks": 3}, "c.vn": {"backlinks": 1}},
                 "Hải Triều": {"a.vn": {"backlinks": None}}}
        got = SL.by_rival(pairs, SL.all_labels(self.con))
        self.assertEqual(got["Shady"], {"Textlink": [2, 13], "PBN": [1, 3]})
        self.assertEqual(got["Hải Triều"], {"Textlink": [1, None]})  # số link chưa tách được: không bịa
