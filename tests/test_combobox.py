import re
import unittest
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "seo_report" / "combobox.js").read_text(encoding="utf-8")


class ComboboxContractTest(unittest.TestCase):
    """Các thuộc tính ARIA bắt buộc của combobox (mẫu ARIA 1.2 combobox + listbox) không bị mất khi sửa sau này."""

    def test_aria_roles_and_states(self):
        for needle in ('role="combobox"', 'role="listbox"', 'role="option"', ":aria-expanded=", ":aria-controls=",
                       ":aria-activedescendant=", ":aria-selected=", ':aria-labelledby="labelId"',
                       ':for="inputId"', 'aria-live="polite"'):
            self.assertIn(needle, JS, needle)

    def test_controls_only_when_open(self):
        # danh sách chỉ có trong DOM khi mở, nên aria-controls cũng chỉ trỏ tới nó khi mở
        self.assertIn(":aria-controls=\"open ? listId : null\"", JS)
        self.assertIn('<ul v-if="open"', JS)

    def test_keys_handled(self):
        for key in ("ArrowDown", "ArrowUp", "Enter", "Escape", "Home", "End", "Tab"):
            self.assertRegex(JS, rf'case "{key}"')

    def test_no_autofocus_on_mount(self):
        mounted = re.search(r"mounted\(\) \{(.*?)\n    \},", JS, re.S).group(1)
        self.assertNotIn("focus(", mounted)
        self.assertNotIn("autofocus", JS)


if __name__ == "__main__":
    unittest.main()
