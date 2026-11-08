import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "seo_report"
JS = (ROOT / "fab.js").read_text(encoding="utf-8")
CSS = (ROOT / "ui_theme.py").read_text(encoding="utf-8")


class FloatGroupContractTest(unittest.TestCase):
    """Nhóm nút nổi: nút + là disclosure, về đầu trang chỉ hiện sau 400px, cả cột trên vùng an toàn, trang chừa chỗ."""

    def test_disclosure(self):
        for needle in (":aria-expanded=", ':aria-controls="open ? dialId : null"', ':aria-label="open ?',
                       '@keydown.esc="closeDial(true)"', 'name="add"'):
            self.assertIn(needle, JS, needle)

    def test_back_to_top_threshold(self):
        self.assertIn("topAfter: { type: Number, default: 400 }", JS)
        self.assertIn("window.scrollY > this.topAfter", JS)
        self.assertIn(":tabindex=\"showTop ? 0 : -1\"", JS)  # ẩn thì không Tab tới được

    def test_layout(self):
        self.assertIn("bottom: calc(24px + env(safe-area-inset-bottom))", CSS)
        self.assertIn("body.sr-has-fab .q-page-container { padding-bottom:", CSS)
        self.assertIn(".sr-fab-group { position: fixed;", CSS)


if __name__ == "__main__":
    unittest.main()
