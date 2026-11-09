import sqlite3
import unittest
from pathlib import Path

from seo_report import aio as AO

ROOT = Path(__file__).resolve().parents[1] / "seo_report"
MS = (ROOT / "multiselect.js").read_text(encoding="utf-8")
TF = (ROOT / "transfer.js").read_text(encoding="utf-8")


class PickerContractTest(unittest.TestCase):
    """Thuộc tính ARIA bắt buộc của Multi-select và Transfer không bị mất khi sửa sau này."""

    def test_multiselect(self):
        for needle in ('role="listbox"', 'aria-multiselectable="true"', 'role="option"', ":aria-selected=",
                       'aria-haspopup="listbox"', ":aria-expanded=", ':aria-controls="open ? popId : null"',
                       ":aria-activedescendant=", "'Bỏ ' + o.label", 'aria-live="polite"'):
            self.assertIn(needle, MS, needle)

    def test_transfer(self):
        for needle in ('role="listbox"', 'aria-multiselectable="true"', 'role="option"', ":aria-selected=",
                       ':aria-labelledby="titleId"', ':disabled="!canRight"', ':disabled="!canLeft"', "targetKeys"):
            self.assertIn(needle, TF, needle)


class RestoreBrandTest(unittest.TestCase):
    def test_readding_a_removed_rival_keeps_name_and_aliases(self):
        con = sqlite3.connect(":memory:")
        AO.ensure_tables(con)
        site = "https://example.com/"
        bid = AO.save_brand(con, site, "Mắt Việt", "Mắt Việt", "matviet.vn")
        AO.remove_brand(con, site, bid)
        self.assertEqual(AO.competitor_count(con, site), 0)
        again = AO.add_or_restore(con, site, "matviet.vn")
        self.assertEqual(again, bid)
        name, aliases = con.execute("SELECT name, aliases FROM aio_brands WHERE id = ?", (bid,)).fetchone()
        self.assertEqual((name, aliases), ("Mắt Việt", "Mắt Việt"))

    def test_new_domain_is_added(self):
        con = sqlite3.connect(":memory:")
        AO.ensure_tables(con)
        AO.add_or_restore(con, "https://example.com/", "newrival.vn")
        self.assertEqual(AO.competitor_count(con, "https://example.com/"), 1)


if __name__ == "__main__":
    unittest.main()
