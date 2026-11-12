import sqlite3
import unittest

from seo_report import quick_prefs as QP


class QuickPrefsTest(unittest.TestCase):
    def test_defaults_by_role(self):
        self.assertEqual([x["key"] for x in QP.defaults(True)], QP.DEFAULT_EDIT)
        self.assertEqual([x["key"] for x in QP.defaults(False)], QP.DEFAULT_VIEW)

    def test_clean_filters_permission_links_and_dupes(self):
        items = [{"key": "kw"}, {"key": "look"}, {"key": "look"}, {"key": "page:/thu-hang", "label": "  Thứ  hạng "},
                 {"key": "page://evil.com"}, {"key": "link:javascript:alert(1)"}, {"key": "link:https://a.vn/x"},
                 {"key": "link:/noi-bo", "icon": "bad icon!"}, {"key": "lạ"}, "rác"]
        out = QP.clean(items, can_edit=False)
        self.assertEqual([x["key"] for x in out], ["look", "page:/thu-hang", "link:https://a.vn/x", "link:/noi-bo"])
        self.assertEqual(out[1]["label"], "Thứ hạng")
        self.assertEqual(out[3]["icon"], "open_in_new")
        self.assertEqual(QP.clean(items, can_edit=True)[0]["key"], "kw")

    def test_max_items(self):
        items = [{"key": f"page:/p{i}"} for i in range(12)]
        self.assertEqual(len(QP.clean(items, True)), QP.MAX_ITEMS)

    def test_save_get_reset(self):
        con = sqlite3.connect(":memory:")
        self.assertEqual(QP.get(con, "A@x.vn", True), QP.defaults(True))
        QP.save(con, "A@x.vn", [{"key": "credit"}, {"key": "kw"}], True)
        self.assertEqual([x["key"] for x in QP.get(con, "a@x.vn", True)], ["credit", "kw"])
        # quyền bị hạ xuống chỉ xem: thao tác cần quyền sửa tự rơi ra
        self.assertEqual([x["key"] for x in QP.get(con, "a@x.vn", False)], ["credit"])
        QP.reset(con, "a@x.vn")
        self.assertEqual(QP.get(con, "a@x.vn", True), QP.defaults(True))


if __name__ == "__main__":
    unittest.main()
