import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from seo_report import backup


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data" / "projects").mkdir(parents=True)
        for rel in ("data/seo.db", "data/projects/shop.db"):
            with closing(sqlite3.connect(self.root / rel)) as c:
                c.execute("CREATE TABLE t (x)")
                c.execute("INSERT INTO t VALUES (?)", (rel,))
                c.commit()
        (self.root / "config.toml").write_text('site_url = "x"', encoding="utf-8")
        (self.root / "data" / "ui_secret.txt").write_text("s", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_zip_has_databases_and_config_but_no_secrets(self):
        out = backup.run(self.root, self.root / "data", self.root / "backups")
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            self.assertEqual(names, {"data/seo.db", "data/projects/shop.db", "config.toml"})
            z.extract("data/projects/shop.db", self.root / "check")
        with closing(sqlite3.connect(self.root / "check" / "data" / "projects" / "shop.db")) as c:
            self.assertEqual(c.execute("SELECT x FROM t").fetchone()[0], "data/projects/shop.db")

    def test_keeps_only_latest(self):
        dest = self.root / "backups"
        start = datetime(2026, 11, 1, 6, 0)
        for i in range(5):
            backup.run(self.root, self.root / "data", dest, keep=3, now=start + timedelta(days=i))
        files = sorted(p.name for p in dest.iterdir())
        self.assertEqual(files, [f"seo-report_2026-11-0{d}_0600.zip" for d in (3, 4, 5)])
        self.assertEqual(backup.latest(dest).name, "seo-report_2026-11-05_0600.zip")

    def test_backup_folder_inside_data_is_skipped(self):
        dest = self.root / "data" / "backups"
        dest.mkdir()
        with closing(sqlite3.connect(dest / "stray.db")) as c:
            c.execute("CREATE TABLE t (x)")
        with zipfile.ZipFile(backup.run(self.root, self.root / "data", dest)) as z:
            self.assertNotIn("data/backups/stray.db", z.namelist())


if __name__ == "__main__":
    unittest.main()
