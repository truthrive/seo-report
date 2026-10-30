"""Lưu dữ liệu GSC vào SQLite.

gsc_page_daily lưu tổng của URL (gồm cả query bị Google ẩn);
gsc_query_daily lưu từng cặp URL × query. Tổng của bảng thứ hai luôn nhỏ hơn bảng thứ nhất.

URL và query được lưu một lần trong bảng pages/queries; bảng theo ngày chỉ giữ mã số,
nên 16 tháng dữ liệu nhỏ hơn khoảng 10 lần so với lưu nguyên chuỗi ở mỗi dòng.
CTR không lưu, tính từ clicks / impressions trong các view v_page_daily, v_query_daily.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    site TEXT NOT NULL,
    url TEXT NOT NULL,
    UNIQUE (site, url)
);
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS gsc_page_daily (
    date TEXT NOT NULL,
    page_id INTEGER NOT NULL,
    clicks INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    position REAL NOT NULL,
    PRIMARY KEY (date, page_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS gsc_query_daily (
    date TEXT NOT NULL,
    page_id INTEGER NOT NULL,
    query_id INTEGER NOT NULL,
    clicks INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    position REAL NOT NULL,
    PRIMARY KEY (date, page_id, query_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_query_daily_page ON gsc_query_daily (page_id, date);
-- Tổng theo property (GSC tính gộp cả site), dùng cho mọi số "toàn site". Không cộng từ gsc_page_daily.
CREATE TABLE IF NOT EXISTS gsc_site_daily (
    site TEXT NOT NULL,
    date TEXT NOT NULL,
    clicks INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    position REAL NOT NULL,
    PRIMARY KEY (site, date)
);
CREATE TABLE IF NOT EXISTS gsc_fetch_log (
    site TEXT NOT NULL,
    date TEXT NOT NULL,
    page_rows INTEGER NOT NULL,
    query_rows INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (site, date)
);
CREATE VIEW IF NOT EXISTS v_page_daily AS
    SELECT p.site, d.date, p.url AS page, d.clicks, d.impressions,
           CASE WHEN d.impressions > 0 THEN 1.0 * d.clicks / d.impressions END AS ctr, d.position
    FROM gsc_page_daily d JOIN pages p ON p.id = d.page_id;
CREATE VIEW IF NOT EXISTS v_query_daily AS
    SELECT p.site, d.date, p.url AS page, q.text AS query, d.clicks, d.impressions,
           CASE WHEN d.impressions > 0 THEN 1.0 * d.clicks / d.impressions END AS ctr, d.position
    FROM gsc_query_daily d JOIN pages p ON p.id = d.page_id JOIN queries q ON q.id = d.query_id;

-- URL đã chuẩn hóa (bỏ #mục, ?utm_…): một URL gom nhiều dòng GSC. Đây là đơn vị để báo cáo.
CREATE TABLE IF NOT EXISTS urls (
    id INTEGER PRIMARY KEY,
    site TEXT NOT NULL,
    url TEXT NOT NULL,
    type TEXT,
    type_source TEXT,
    note TEXT,
    checked_at TEXT,
    UNIQUE (site, url)
);
CREATE TABLE IF NOT EXISTS page_url (
    page_id INTEGER PRIMARY KEY,
    url_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_page_url ON page_url (url_id);
CREATE TABLE IF NOT EXISTS url_groups (
    id INTEGER PRIMARY KEY,
    site TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE (site, name)
);
CREATE TABLE IF NOT EXISTS url_group_members (
    group_id INTEGER NOT NULL,
    url_id INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    added_by TEXT NOT NULL,
    PRIMARY KEY (group_id, url_id)
);
CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    user TEXT NOT NULL,
    site TEXT NOT NULL,
    action TEXT NOT NULL,
    url TEXT,
    detail TEXT
);
-- Position gộp theo trung bình có trọng số impression, như cách GSC tính.
CREATE VIEW IF NOT EXISTS v_url_daily AS
    SELECT u.site, d.date, u.id AS url_id, u.url, SUM(d.clicks) AS clicks, SUM(d.impressions) AS impressions,
           SUM(d.position * d.impressions) / NULLIF(SUM(d.impressions), 0) AS position
    FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id JOIN urls u ON u.id = pu.url_id
    GROUP BY u.id, d.date;
"""


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    version, = con.execute("PRAGMA user_version").fetchone()
    has_tables = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'gsc_page_daily'").fetchone()
    if has_tables and version < 2:
        raise SystemExit(f"{path} dùng cách lưu cũ. Chạy: python -m seo_report migrate")
    con.executescript(SCHEMA)
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return con


def _metrics(row: dict) -> tuple:
    return (int(row["clicks"]), int(row["impressions"]), float(row["position"]))


def replace_day(con: sqlite3.Connection, site: str, day: str, page_rows: list, query_rows: list) -> None:
    """Thay toàn bộ dữ liệu của một ngày, để lấy lại nhiều lần vẫn không bị trùng."""
    with con:
        con.execute("CREATE TEMP TABLE IF NOT EXISTS _p (url TEXT, clicks INT, impressions INT, position REAL)")
        con.execute("CREATE TEMP TABLE IF NOT EXISTS _q (url TEXT, query TEXT, clicks INT, impressions INT, position REAL)")
        con.execute("DELETE FROM _p")
        con.execute("DELETE FROM _q")
        con.executemany("INSERT INTO _p VALUES (?, ?, ?, ?)", [(r["keys"][0], *_metrics(r)) for r in page_rows])
        con.executemany("INSERT INTO _q VALUES (?, ?, ?, ?, ?)",
                        [(r["keys"][0], r["keys"][1], *_metrics(r)) for r in query_rows])
        con.execute("INSERT OR IGNORE INTO pages (site, url) SELECT ?, url FROM _p UNION SELECT ?, url FROM _q",
                    (site, site))
        con.execute("INSERT OR IGNORE INTO queries (text) SELECT DISTINCT query FROM _q")
        site_pages = "SELECT id FROM pages WHERE site = ?"
        con.execute(f"DELETE FROM gsc_page_daily WHERE date = ? AND page_id IN ({site_pages})", (day, site))
        con.execute(f"DELETE FROM gsc_query_daily WHERE date = ? AND page_id IN ({site_pages})", (day, site))
        con.execute(
            """INSERT INTO gsc_page_daily
               SELECT ?, p.id, t.clicks, t.impressions, t.position
               FROM _p t JOIN pages p ON p.site = ? AND p.url = t.url""",
            (day, site),
        )
        con.execute(
            """INSERT INTO gsc_query_daily
               SELECT ?, p.id, q.id, t.clicks, t.impressions, t.position
               FROM _q t JOIN pages p ON p.site = ? AND p.url = t.url JOIN queries q ON q.text = t.query""",
            (day, site),
        )
        con.execute(
            "INSERT OR REPLACE INTO gsc_fetch_log VALUES (?, ?, ?, ?, ?)",
            (site, day, len(page_rows), len(query_rows), datetime.now(timezone.utc).isoformat()),
        )


def save_site_totals(con: sqlite3.Connection, site: str, rows: list) -> None:
    with con:
        con.executemany("INSERT OR REPLACE INTO gsc_site_daily VALUES (?, ?, ?, ?, ?)",
                        [(site, r["keys"][0], *_metrics(r)) for r in rows])


def fetched_days(con: sqlite3.Connection, site: str) -> set[str]:
    return {r[0] for r in con.execute("SELECT date FROM gsc_fetch_log WHERE site = ?", (site,))}


def migrate_v1(old_path: Path, new_path: Path) -> None:
    """Chuyển file dữ liệu cách lưu cũ (URL/query lặp ở mỗi dòng) sang cách lưu mới."""
    con = connect(new_path)
    con.execute("ATTACH DATABASE ? AS old", (str(old_path),))
    with con:
        con.execute("""INSERT OR IGNORE INTO pages (site, url)
                       SELECT DISTINCT site, page FROM old.gsc_page_daily
                       UNION SELECT DISTINCT site, page FROM old.gsc_query_daily""")
        con.execute("INSERT OR IGNORE INTO queries (text) SELECT DISTINCT query FROM old.gsc_query_daily")
        con.execute("""INSERT INTO gsc_page_daily
                       SELECT o.date, p.id, o.clicks, o.impressions, o.position
                       FROM old.gsc_page_daily o JOIN pages p ON p.site = o.site AND p.url = o.page""")
        con.execute("""INSERT INTO gsc_query_daily
                       SELECT o.date, p.id, q.id, o.clicks, o.impressions, o.position
                       FROM old.gsc_query_daily o JOIN pages p ON p.site = o.site AND p.url = o.page
                       JOIN queries q ON q.text = o.query""")
        con.execute("INSERT INTO gsc_fetch_log SELECT * FROM old.gsc_fetch_log")
    con.execute("DETACH DATABASE old")
    con.close()
