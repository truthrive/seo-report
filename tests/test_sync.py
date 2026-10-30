import unittest
from datetime import date
from pathlib import Path

from seo_report import db, gsc
from seo_report.config import Config
from seo_report.sync import days_to_fetch, sync

SITE = "sc-domain:example.com"


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeService:
    """Giả lập GSC: mỗi ngày có `pages` URL, mỗi URL có `queries` query."""

    def __init__(self, pages=3, queries=2):
        self.pages, self.queries = pages, queries
        self.calls = []

    def searchanalytics(self):
        return self

    def query(self, siteUrl, body):
        self.calls.append(body)
        if body["dimensions"] == ["date"]:
            from datetime import date, timedelta
            d0, d1 = date.fromisoformat(body["startDate"]), date.fromisoformat(body["endDate"])
            rows = [{"keys": [(d0 + timedelta(days=i)).isoformat()], "clicks": 25, "impressions": 200, "ctr": 0.1,
                     "position": 4.0} for i in range((d1 - d0).days + 1)]
        elif body["dimensions"] == ["page"]:
            rows = [{"keys": [f"/p{i}"], "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 3.0}
                    for i in range(self.pages)]
        else:
            rows = [{"keys": [f"/p{i}", f"q{j}"], "clicks": 4, "impressions": 40, "ctr": 0.1, "position": 3.0}
                    for i in range(self.pages) for j in range(self.queries)]
        start = body["startRow"]
        return FakeRequest({"rows": rows[start:start + body["rowLimit"]]})


def make_cfg(**kw):
    return Config(site_url=SITE, db_path=Path(":memory:"), client_secret=Path("x"),
                  token_path=Path("y"), **kw)


class SyncTest(unittest.TestCase):
    def test_pagination_reads_all_rows(self):
        svc = FakeService(pages=30000, queries=1)
        rows = gsc.query_day(svc, SITE, "2026-10-01", ["page"])
        self.assertEqual(len(rows), 30000)
        self.assertEqual([c["startRow"] for c in svc.calls], [0, 25000])

    def test_first_sync_backfills_and_refetch_is_idempotent(self):
        cfg = make_cfg(backfill_months=1, refetch_days=5)
        con = db.connect(":memory:")
        today = date(2026, 10, 28)
        n = sync(cfg, FakeService(), con, today=today, log=lambda *_: None)
        self.assertEqual(n, 30)  # 30 ngày lịch sử, đến hết hôm qua
        n2 = sync(cfg, FakeService(), con, today=today, log=lambda *_: None)
        self.assertEqual(n2, 5)  # chỉ lấy lại 5 ngày gần nhất
        rows, = con.execute("SELECT COUNT(*) FROM gsc_query_daily WHERE date = '2026-10-27'").fetchone()
        self.assertEqual(rows, 6)  # không bị nhân đôi sau khi lấy lại

    def test_site_totals_stored_separately(self):
        cfg = make_cfg(backfill_months=1, refetch_days=5)
        con = db.connect(":memory:")
        sync(cfg, FakeService(pages=3, queries=1), con, today=date(2026, 10, 28), log=lambda *_: None)
        clicks, = con.execute("SELECT clicks FROM gsc_site_daily WHERE date = '2026-10-27'").fetchone()
        page_sum, = con.execute("SELECT SUM(clicks) FROM gsc_page_daily WHERE date = '2026-10-27'").fetchone()
        self.assertEqual((clicks, page_sum), (25, 30))  # hai nguồn khác nhau, không lấy cái này thay cái kia
        self.assertEqual(con.execute("SELECT COUNT(*) FROM gsc_site_daily").fetchone()[0], 30)

    def test_missing_old_days_are_filled(self):
        cfg = make_cfg(backfill_months=1, refetch_days=5)
        today = date(2026, 10, 28)
        done = {"2026-10-10", "2026-10-11"}
        days = days_to_fetch(cfg, done | {"2026-10-12"}, today, backfill=False)
        self.assertEqual(days[0], "2026-10-23")
        days = days_to_fetch(cfg, done, today, backfill=True)
        self.assertIn("2026-10-12", days)
        self.assertNotIn("2026-10-10", days)

    def test_page_totals_kept_separately_from_queries(self):
        con = db.connect(":memory:")
        sync(make_cfg(backfill_months=1), FakeService(pages=1, queries=2), con,
             today=date(2026, 10, 28), log=lambda *_: None)
        page_clicks, = con.execute("SELECT SUM(clicks) FROM gsc_page_daily WHERE date='2026-10-27'").fetchone()
        query_clicks, = con.execute("SELECT SUM(clicks) FROM gsc_query_daily WHERE date='2026-10-27'").fetchone()
        self.assertEqual((page_clicks, query_clicks), (10, 8))


class StorageTest(unittest.TestCase):
    def test_refetch_updates_numbers_and_reuses_ids(self):
        con = db.connect(":memory:")
        row = lambda c: {"keys": ["/a", "q"], "clicks": c, "impressions": 10, "ctr": 0, "position": 2.0}
        page = lambda c: {"keys": ["/a"], "clicks": c, "impressions": 10, "ctr": 0, "position": 2.0}
        db.replace_day(con, SITE, "2026-10-01", [page(3)], [row(3)])
        db.replace_day(con, SITE, "2026-10-01", [page(5)], [row(5)])
        self.assertEqual(con.execute("SELECT clicks, ctr FROM v_query_daily").fetchall(), [(5, 0.5)])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM pages").fetchone(), (1,))

    def test_sites_do_not_overwrite_each_other(self):
        con = db.connect(":memory:")
        page = {"keys": ["/a"], "clicks": 1, "impressions": 10, "ctr": 0, "position": 2.0}
        db.replace_day(con, "site-a", "2026-10-01", [page], [])
        db.replace_day(con, "site-b", "2026-10-01", [page], [])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM v_page_daily").fetchone(), (2,))

    def test_migrate_from_v1(self):
        import sqlite3
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        old = sqlite3.connect(tmp / "old.db")
        old.executescript("""
            CREATE TABLE gsc_page_daily (site, date, page, clicks, impressions, ctr, position);
            CREATE TABLE gsc_query_daily (site, date, page, query, clicks, impressions, ctr, position);
            CREATE TABLE gsc_fetch_log (site, date, page_rows, query_rows, fetched_at);
            INSERT INTO gsc_page_daily VALUES ('s', '2026-01-01', '/a', 7, 70, 0.1, 3.0);
            INSERT INTO gsc_query_daily VALUES ('s', '2026-01-01', '/a', 'q1', 4, 40, 0.1, 3.0);
            INSERT INTO gsc_fetch_log VALUES ('s', '2026-01-01', 1, 1, 'x');
        """)
        old.commit()
        old.close()
        db.migrate_v1(tmp / "old.db", tmp / "new.db")
        new = db.connect(tmp / "new.db")
        self.assertEqual(new.execute("SELECT page, query, clicks FROM v_query_daily").fetchall(), [("/a", "q1", 4)])
        self.assertEqual(db.fetched_days(new, "s"), {"2026-01-01"})
        new.close()


if __name__ == "__main__":
    unittest.main()
