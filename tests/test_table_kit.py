import unittest

from seo_report import table_kit as TK

ROWS = [{"k": "a", "domain": "báo-đà-nẵng.vn", "rank": 64, "follow": "dofollow", "rivals": ["A", "B"],
         "first_iso": "2026-03-08"},
        {"k": "b", "domain": "spam.ru", "rank": 5, "follow": "nofollow", "rivals": ["B"], "first_iso": "2025-01-02"},
        {"k": "c", "domain": "cnnd.vn", "rank": None, "follow": "dofollow", "rivals": ["C"], "first_iso": ""}]
FILTERS = [("text", "Website", ["domain"]), ("num", "Uy tín", "rank"), ("enum", "Loại", "follow"),
           ("enum", "Đối thủ", "rivals"), ("date", "Thấy lần đầu", "first_iso")]


def keys(st):
    return [r["k"] for r in TK.apply(ROWS, FILTERS, st)]


class TableKitTest(unittest.TestCase):
    def test_filters(self):
        st = TK.new_state()
        self.assertEqual(keys(st), ["a", "b", "c"])
        self.assertEqual(keys({**st, "inc": ["đa-nang"]}), ["a"])  # bỏ dấu khi so
        self.assertEqual(keys({**st, "exc": [".ru"]}), ["a", "c"])
        self.assertEqual(keys({**st, "num": {"rank": (10, None)}}), ["a"])  # trống số: không qua khi có điều kiện
        self.assertEqual(keys({**st, "enum": {"follow": {"nofollow"}}}), ["b"])
        self.assertEqual(keys({**st, "enum": {"rivals": {"B"}}}), ["a", "b"])  # trường danh sách: khớp bất kỳ
        self.assertEqual(keys({**st, "date": {"first_iso": ("2026-01-01", "")}}), ["a"])

    def test_copy_is_tab_separated_with_header(self):
        text = TK.tsv(ROWS[:2], [("Website", "domain"), ("Uy tín", "rank"), ("Đối thủ", "rivals")])
        self.assertEqual(text.split("\n"), ["Website\tUy tín\tĐối thủ", "báo-đà-nẵng.vn\t64\tA, B",
                                            "spam.ru\t5\tB"])
        self.assertEqual(TK.tsv([{"x": 1.5}], [("X", "x")]).split("\n")[1], "1,5")

    def test_fixed_columns(self):
        cols = TK.fixed_columns([{"name": "a", "label": "A", "width": 90}, {"name": "b", "label": "B"}])
        self.assertIn("width:90px", cols[0]["style"])
        self.assertNotIn("style", cols[1])  # cột co giãn
        self.assertNotIn("width", cols[0])


if __name__ == "__main__":
    unittest.main()


class RankChipFilterTest(unittest.TestCase):
    def test_or_within_group_and_across(self):
        from seo_report import web_rank as WR
        kws = [{"rank": 2, "date": "d", "top_target": 3, "target_url": "u", "ranking_url": "u", "paused": False,
                "note": "", "id": 1},
               {"rank": 7, "date": "d", "top_target": 3, "target_url": "u", "ranking_url": "x", "paused": False,
                "note": "n", "id": 2},
               {"rank": 15, "date": "d", "top_target": None, "target_url": "", "ranking_url": "", "paused": False,
                "note": "", "id": 3}]
        pick = lambda on: [k["id"] for k in kws if WR.filter_keep(set(on))(k)]
        self.assertEqual(pick([]), [1, 2, 3])
        self.assertEqual(pick(["top3", "top10"]), [1, 2])          # cùng nhóm: hoặc
        self.assertEqual(pick(["top10", "top30", "wrong"]), [2])   # khác nhóm: và
        self.assertEqual(pick(["note", "notarget"]), [2, 3])


class MinMoveTest(unittest.TestCase):
    def test_in_and_out_of_depth(self):
        from seo_report import web_rank as WR
        self.assertEqual(WR._min_move({"rank": 1, "prev": None, "prev_depth": 20, "last_depth": 20}, 100), 20)
        self.assertEqual(WR._min_move({"rank": 14, "prev": None, "prev_depth": 20, "last_depth": 20}, 100), 7)
        self.assertEqual(WR._min_move({"rank": None, "prev": 7, "prev_depth": 20, "last_depth": 20}, -100), 14)
        self.assertIsNone(WR._min_move({"rank": 3, "prev": 5, "prev_depth": 20, "last_depth": 20}, 2))


class XlsxTest(unittest.TestCase):
    def test_xlsx_columns_and_lists(self):
        import io

        from openpyxl import load_workbook
        data = TK.xlsx([{"a": "x.vn", "b": ["A", "B"], "c": 3}], [("Website", "a"), ("Đối thủ", "b"), ("Số", "c")],
                       "Link")
        ws = load_workbook(io.BytesIO(data)).active
        self.assertEqual(ws.title, "Link")
        self.assertEqual([c.value for c in ws[1]], ["Website", "Đối thủ", "Số"])
        self.assertEqual([c.value for c in ws[2]], ["x.vn", "A, B", 3])
