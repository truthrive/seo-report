"""Tiến trình theo bước (T.Steps) và khối chi phí tách dòng (T.cost_lines, web_ai_write.ai_cost_box)."""
import unittest
from unittest import mock

from seo_report import points as PT
from seo_report import ui_theme as T
from seo_report import web_ai_write as WAW


class El:
    """Phần tử giả tối giản: ghi lại class, chữ, con; dùng được với `with`."""
    stack: list = []

    def __init__(self, kind="div", text=""):
        self.kind, self.text, self.cls, self.kids, self.props_ = kind, text, set(), [], ""
        if El.stack:
            El.stack[-1].kids.append(self)

    def classes(self, add="", replace=None):
        if replace is not None:
            self.cls = set(replace.split())
        else:
            self.cls |= set(add.split())
        return self

    def props(self, p=""):
        self.props_ += p
        return self

    def style(self, _s=""):
        return self

    def clear(self):
        self.kids = []

    def __enter__(self):
        El.stack.append(self)
        return self

    def __exit__(self, *a):
        El.stack.pop()

    def all_text(self) -> str:
        return " ".join([self.text] + [k.all_text() for k in self.kids]).strip()


class Ui:
    def element(self, tag="div"):
        return El(tag)

    def label(self, text=""):
        return El("label", text)

    def icon(self, name, size=""):
        return El("icon", name)

    def spinner(self, size="", color=""):
        return El("spinner")

    def html(self, s):
        return El("html", s)


class StepsTest(unittest.TestCase):
    def setUp(self):
        El.stack = []
        self.now = [100.0]
        self.ui = Ui()

    def steps(self, labels):
        s = T.Steps(self.ui, labels)
        s._time = lambda: self.now[0]
        return s

    def state(self, s, i):
        row, icon, note = s.rows[i]
        return (row.cls - {"sr-step"}).pop(), icon.kids[0].kind, icon.kids[0].text, note.text

    def test_flow_and_real_elapsed(self):
        s = self.steps(["Đọc trang", "AI viết", "Lưu"])
        self.assertEqual([self.state(s, i)[0] for i in range(3)], ["wait", "wait", "wait"])
        s.run(0)
        self.assertEqual(self.state(s, 0)[:2], ("run", "spinner"))
        self.now[0] += 4.2
        s.done(0, "2.140 chữ")
        self.assertEqual(self.state(s, 0), ("done", "icon", "check_circle", "2.140 chữ · 4 giây"))
        s.run(1)
        self.now[0] += 125
        s.done(1, "lỗi", state="fail")
        self.assertEqual(self.state(s, 1)[2:], ("error", "lỗi · 2,1 phút"))
        s.done(2, state="skip")  # chưa chạy thì không có thời gian
        self.assertEqual(self.state(s, 2)[2:], ("remove_circle_outline", ""))

    def test_elapsed_formats(self):
        s = self.steps(["a"])
        s.run(0)
        self.assertEqual(s.elapsed(0), "dưới 1 giây")
        self.now[0] += 59.6
        self.assertEqual(s.elapsed(0), "60 giây")

    def test_closed_dialog_is_ignored(self):
        s = self.steps(["a"])

        class Gone(El):
            def classes(self, *a, **k):
                raise RuntimeError("client deleted")
        s.rows[0] = (Gone(), s.rows[0][1], s.rows[0][2])
        s.run(0)
        s.done(0)  # không văng lỗi

    def test_accessible_markup(self):
        s = self.steps(["a"])
        self.assertIn('aria-live="polite"', s.box.props_)
        self.assertIn('role="listitem"', s.rows[0][0].props_)


class CostTest(unittest.TestCase):
    def setUp(self):
        El.stack = []
        self.ui = Ui()
        self.root = El()

    def box(self, balance):
        with self.root, mock.patch.object(PT, "my_balance", return_value=balance), \
                mock.patch.object(PT, "cost", return_value=5):
            ok = WAW.ai_cost_box(self.ui, "u", "ai_page_gap", before=[("Đọc trang", "miễn phí")])
        b = self.root.kids[-1]
        return ok, (b.cls - {"sr-cost-box", "w-full"}).pop(), b.all_text()

    def test_owner_not_charged(self):
        ok, tone, text = self.box(None)
        self.assertTrue(ok)
        self.assertEqual(tone, "neutral")
        self.assertIn("miễn phí", text)
        self.assertIn("1 lần gọi AI", text)
        self.assertIn("không trừ credit", text)

    def test_member_tones(self):
        ok, tone, text = self.box({"left": 1000, "limit": 2000})
        self.assertEqual((ok, tone), (True, "neutral"))
        self.assertIn("995 / 2.000 credit", text)
        self.assertIn("5 credit", text)
        ok, tone, _ = self.box({"left": 150, "limit": 2000})  # còn 145 < 10%
        self.assertEqual((ok, tone), (True, "amber"))
        ok, tone, text = self.box({"left": 3, "limit": 2000})
        self.assertEqual((ok, tone), (False, "red"))
        self.assertIn("Không đủ credit", text)

    def test_cost_lines_rows_are_plain_text(self):
        with self.root:
            T.cost_lines(self.ui, [("<b>x</b>", "1")], total=("Tổng", "1"))
        rows = self.root.kids[-1].kids
        self.assertEqual([k.kind for k in rows[0].kids], ["label", "label"])  # chữ thường, không chèn HTML
        self.assertEqual(rows[0].kids[0].text, "<b>x</b>")
        self.assertIn("total", rows[1].cls)


if __name__ == "__main__":
    unittest.main()
