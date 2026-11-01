"""Check index bằng GSC URL Inspection API, theo hàng đợi ưu tiên (spec, mục Check index).

Quota khoảng 2.000 URL/ngày mỗi property; tool dùng tối đa `daily_limit` (mặc định 1.500), chừa phần còn lại cho nút
"Kiểm tra ngay". Mỗi lần gọi mất 7–8 giây nên chạy song song vài luồng (dưới giới hạn 600 lượt/phút).

Thứ tự ưu tiên:
1. URL thuộc nhóm (chủ lực…): 7 ngày một lần.
2. URL mới trong sitemap: sau 3, 7 và 14 ngày kể từ lúc xuất hiện.
3. URL có impression trong 28 ngày: 30 ngày một lần.
4. Còn lại (kể cả URL cũ/kỹ thuật): URL chưa kiểm tra trước, rồi URL kiểm tra lâu nhất.
"""
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

from googleapiclient.errors import HttpError

from . import urls as U
from .projects import domain

NEW_URL_MILESTONES = (3, 7, 14)
OLD = "2000-01-01"  # first_seen của URL đã có trong sitemap ngay lần đọc đầu tiên: không coi là URL mới

SCHEMA = """
CREATE TABLE IF NOT EXISTS sitemap_urls (
    site TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (site, url)
);
CREATE TABLE IF NOT EXISTS index_checks (
    url_id INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    verdict TEXT,
    coverage TEXT,
    indexing_state TEXT,
    robots TEXT,
    page_fetch TEXT,
    last_crawl TEXT,
    google_canonical TEXT,
    user_canonical TEXT,
    crawled_as TEXT,
    PRIMARY KEY (url_id, checked_at)
);
CREATE INDEX IF NOT EXISTS idx_index_checks_url ON index_checks (url_id, checked_at);
-- URL người dùng tự nhập để theo dõi (bài mới…): check lại sau 3, 7, 14 ngày đến khi được index.
CREATE TABLE IF NOT EXISTS index_watch (
    url_id INTEGER PRIMARY KEY,
    added_at TEXT NOT NULL,
    added_by TEXT NOT NULL,
    indexed_at TEXT
);
"""

DAILY_QUOTA = 2000  # quota URL Inspection của Google cho mỗi property mỗi ngày
WATCH_OVERDUE_DAYS = 14


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    # Đến micro giây: hai lần kiểm tra cùng một URL trong cùng giây không ghi đè nhau.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# ---- Sitemap ----

def read_sitemap(url: str, fetch=None, depth: int = 0) -> list[str]:
    """Đọc sitemap, kể cả sitemap index (sitemap chứa các sitemap con)."""
    fetch = fetch or (lambda u: urlopen(Request(u, headers={"User-Agent": "SEOReportBot/1.0", "Accept-Encoding": "identity"}),
                                         timeout=60).read().decode("utf-8", "ignore"))
    xml = fetch(url)
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    if "<sitemapindex" in xml and depth < 2:
        return [u for sub in locs for u in read_sitemap(sub, fetch, depth + 1)]
    return locs


def sync_sitemap(con: sqlite3.Connection, site: str, today: date, fetch=None) -> int:
    """Cập nhật danh sách URL trong sitemap; trả về số URL mới xuất hiện."""
    ensure_tables(con)
    first_run = not con.execute("SELECT 1 FROM sitemap_urls WHERE site = ?", (site,)).fetchone()
    found = {U.normalize(u) for u in read_sitemap(site.rstrip("/") + "/sitemap.xml", fetch)}
    new = 0
    with con:
        for url in found:
            cur = con.execute("UPDATE sitemap_urls SET last_seen = ? WHERE site = ? AND url = ?",
                              (today.isoformat(), site, url))
            if not cur.rowcount:
                con.execute("INSERT INTO sitemap_urls VALUES (?, ?, ?, ?)",
                            (site, url, OLD if first_run else today.isoformat(), today.isoformat()))
                new += 0 if first_run else 1
            U._get_or_create_url(con, site, url)
    return new


# ---- Hàng đợi ----

def queue(con: sqlite3.Connection, site: str, today: date, limit: int) -> list[tuple[int, str, str]]:
    """Danh sách (url_id, url, lý do) cần kiểm tra hôm nay, theo thứ tự ưu tiên."""
    ensure_tables(con)
    last = dict(con.execute("SELECT url_id, MAX(checked_at) FROM index_checks GROUP BY url_id"))
    counts = dict(con.execute("SELECT url_id, COUNT(*) FROM index_checks GROUP BY url_id"))
    all_urls = con.execute("SELECT id, url, COALESCE(type, '') FROM urls WHERE site = ?", (site,)).fetchall()
    by_id = {r[0]: r for r in all_urls}

    def age(url_id) -> float:
        return (today - date.fromisoformat(last[url_id][:10])).days if url_id in last else 1e9

    picked: dict[int, str] = {}

    def take(ids, reason):
        for i in ids:
            if len(picked) >= limit:
                return
            if i not in picked and i in by_id:
                picked[i] = reason

    members = [r[0] for r in con.execute(
        "SELECT DISTINCT m.url_id FROM url_group_members m JOIN url_groups g ON g.id = m.group_id WHERE g.site = ?",
        (site,))]
    take(sorted((i for i in members if age(i) >= 7), key=age, reverse=True), "URL trong nhóm")

    new_urls = [(con.execute("SELECT id FROM urls WHERE site = ? AND url = ?", (site, url)).fetchone()[0], first_seen,
                 "URL mới") for url, first_seen in con.execute(
                     "SELECT url, first_seen FROM sitemap_urls WHERE site = ? AND first_seen > ?", (site, OLD))]
    new_urls += [(url_id, added_at[:10], "Đang theo dõi") for url_id, added_at in con.execute(
        "SELECT w.url_id, w.added_at FROM index_watch w JOIN urls u ON u.id = w.url_id "
        "WHERE u.site = ? AND w.indexed_at IS NULL", (site,))]
    for url_id, since_day, label in new_urls:
        days = (today - date.fromisoformat(since_day)).days
        needed = 1 + sum(1 for m in NEW_URL_MILESTONES if days >= m) if label == "Đang theo dõi" else \
            sum(1 for m in NEW_URL_MILESTONES if days >= m)
        if counts.get(url_id, 0) < needed and age(url_id) >= 1:
            take([url_id], f"{label} ({days} ngày)")

    since = (today - timedelta(days=28)).isoformat()
    active = [r[0] for r in con.execute(
        """SELECT pu.url_id FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id
           WHERE d.date >= ? GROUP BY pu.url_id HAVING SUM(d.impressions) > 0""", (since,))]
    take(sorted((i for i in active if age(i) >= 30), key=age, reverse=True), "Có impression 28 ngày")

    rest = sorted((r[0] for r in all_urls), key=lambda i: (-age(i), by_id[i][2] == U.LEGACY))
    take(rest, "Xoay vòng")
    return [(i, by_id[i][1], reason) for i, reason in picked.items()]


# ---- Gọi API ----

def inspect(service, site: str, url: str) -> dict:
    body = {"inspectionUrl": url, "siteUrl": site, "languageCode": "vi"}
    r = service.urlInspection().index().inspect(body=body).execute()
    return r.get("inspectionResult", {}).get("indexStatusResult", {})


def save(con: sqlite3.Connection, url_id: int, r: dict) -> None:
    with con:
        if r.get("verdict") == "PASS":
            con.execute("UPDATE index_watch SET indexed_at = ? WHERE url_id = ? AND indexed_at IS NULL",
                        (_now(), url_id))
        con.execute(
            "INSERT OR REPLACE INTO index_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (url_id, _now(), r.get("verdict"), r.get("coverageState"), r.get("indexingState"),
             r.get("robotsTxtState"), r.get("pageFetchState"), r.get("lastCrawlTime"), r.get("googleCanonical"),
             r.get("userCanonical"), r.get("crawledAs")))


def checked_today(con: sqlite3.Connection, today: date) -> int:
    ensure_tables(con)
    # checked_at là giờ UTC; đếm theo ngày UTC như quota của Google.
    return con.execute("SELECT COUNT(*) FROM index_checks WHERE substr(checked_at, 1, 10) = ?",
                       (today.isoformat(),)).fetchone()[0]


def run(con: sqlite3.Connection, site: str, make_service, daily_limit: int = 1500, workers: int = 8,
        today: date | None = None, log=print) -> int:
    """Kiểm tra index theo hàng đợi. `make_service` tạo một client GSC cho mỗi luồng (client không dùng chung luồng được)."""
    today = today or datetime.now(timezone.utc).date()
    budget = daily_limit - checked_today(con, today)
    if budget <= 0:
        log(f"Đã dùng đủ {daily_limit} lượt kiểm tra index hôm nay.")
        return 0
    todo = queue(con, site, today, budget)
    if not todo:
        return 0
    log(f"Kiểm tra index {len(todo)} URL…")
    stop = {"quota": False}
    services = {}

    def work(item):
        url_id, url, reason = item
        if stop["quota"]:
            return None
        tid = threading.get_ident()
        if tid not in services:
            services[tid] = make_service()
        try:
            return url_id, url, inspect(services[tid], site, url)
        except HttpError as e:
            if e.resp.status == 429:
                stop["quota"] = True
            return url_id, url, e

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(work, todo):
            if res is None:
                continue
            url_id, url, r = res
            if isinstance(r, Exception):
                log(f"Lỗi {url}: {r}")
                continue
            save(con, url_id, r)
            done += 1
            if done % 100 == 0:
                log(f"  đã kiểm tra {done}/{len(todo)}")
    if stop["quota"]:
        log("Google báo hết quota URL Inspection hôm nay; lần sau làm tiếp.")
    log(f"Xong: kiểm tra index {done} URL.")
    return done


# ---- URL nhập tay ----

def add_watch(con: sqlite3.Connection, site: str, text: str, user: str) -> tuple[list[tuple[int, str]], list[str]]:
    """Thêm các link dán vào danh sách theo dõi. Trả về ([(url_id, url)], [dòng không phải link])."""
    ensure_tables(con)
    picked, invalid, seen = [], [], set()
    host = domain(site)
    with con:
        for raw in re.split(r"\s+", text.strip()):
            if not raw:
                continue
            url = U.normalize(raw)
            if domain(url) != host:
                invalid.append(raw)  # URL Inspection chỉ kiểm tra được URL thuộc property này
                continue
            url_id = U._match_existing(con, site, url) or U._get_or_create_url(con, site, url)
            if url_id in seen:
                continue
            seen.add(url_id)
            canonical = con.execute("SELECT url FROM urls WHERE id = ?", (url_id,)).fetchone()[0]
            if con.execute("INSERT OR IGNORE INTO index_watch VALUES (?, ?, ?, NULL)",
                           (url_id, _now(), user)).rowcount:
                U.log_change(con, user, site, "Theo dõi index", canonical)
            picked.append((url_id, canonical))
    return picked, invalid


def check_now(con: sqlite3.Connection, site: str, items: list[tuple[int, str]], make_service,
              workers: int = 8, today: date | None = None) -> tuple[int, int]:
    """Kiểm tra ngay các URL đã chọn, trong phần quota còn lại của ngày. Trả về (đã kiểm tra, bị bỏ vì hết quota)."""
    today = today or datetime.now(timezone.utc).date()
    room = max(DAILY_QUOTA - checked_today(con, today), 0)
    todo, skipped = items[:room], len(items) - min(len(items), room)
    services = {}

    def work(item):
        tid = threading.get_ident()
        if tid not in services:
            services[tid] = make_service()
        try:
            return item[0], inspect(services[tid], site, item[1])
        except HttpError as e:
            return item[0], e

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for url_id, r in pool.map(work, todo):
            if not isinstance(r, Exception):
                save(con, url_id, r)
                done += 1
    return done, skipped


def watch_list(con: sqlite3.Connection, site: str, today: date | None = None) -> list[dict]:
    ensure_tables(con)
    today = today or date.today()
    rows = con.execute(
        """SELECT w.url_id, u.url, w.added_at, w.added_by, w.indexed_at,
                  EXISTS (SELECT 1 FROM sitemap_urls s WHERE s.site = u.site AND s.url = u.url)
           FROM index_watch w JOIN urls u ON u.id = w.url_id WHERE u.site = ? ORDER BY w.added_at DESC""",
        (site,)).fetchall()
    checks = latest(con, [r[0] for r in rows])
    counts = dict(con.execute("SELECT url_id, COUNT(*) FROM index_checks GROUP BY url_id"))
    out = []
    for url_id, url, added_at, by, indexed_at, in_sitemap in rows:
        days = (today - date.fromisoformat(added_at[:10])).days
        ix = checks.get(url_id)
        out.append({"url_id": url_id, "url": url, "added_at": added_at, "added_by": by, "days": days,
                    "indexed": bool(indexed_at) or bool(ix and ix["indexed"]), "check": ix,
                    "checks": counts.get(url_id, 0), "in_sitemap": bool(in_sitemap),
                    "overdue": not indexed_at and not (ix and ix["indexed"]) and days >= WATCH_OVERDUE_DAYS})
    return out


def remove_watch(con: sqlite3.Connection, site: str, url_ids: list[int], user: str) -> None:
    with con:
        for url_id in url_ids:
            url, = con.execute("SELECT url FROM urls WHERE id = ?", (url_id,)).fetchone()
            con.execute("DELETE FROM index_watch WHERE url_id = ?", (url_id,))
            U.log_change(con, user, site, "Bỏ theo dõi index", url)


def gsc_inspect_link(site: str, url: str) -> str:
    from urllib.parse import quote
    return f"https://search.google.com/search-console/inspect?resource_id={quote(site, safe='')}&id={quote(url, safe='')}"


# ---- Đọc kết quả ----

def latest(con: sqlite3.Connection, url_ids: list[int]) -> dict[int, dict]:
    """Kết quả gần nhất của từng URL, kèm `dropped` = trước đó đã index (PASS) mà giờ không còn."""
    ensure_tables(con)
    out: dict[int, dict] = {}
    if not url_ids:
        return out
    keys = ["url_id", "checked_at", "verdict", "coverage", "indexing_state", "robots", "page_fetch", "last_crawl",
            "google_canonical", "user_canonical", "crawled_as"]
    for i in range(0, len(url_ids), 900):
        chunk = url_ids[i:i + 900]
        for row in con.execute(
                f"SELECT * FROM index_checks WHERE url_id IN ({','.join('?' * len(chunk))}) "
                "ORDER BY url_id, checked_at DESC", chunk):
            d = dict(zip(keys, row))
            cur = out.get(d["url_id"])
            if cur is None:
                d["indexed"] = d["verdict"] == "PASS"
                d["dropped"] = False
                out[d["url_id"]] = d
            elif "prev_seen" not in cur:
                cur["prev_seen"] = True
                cur["dropped"] = not cur["indexed"] and d["verdict"] == "PASS"
    return out


def canonical_mismatch(check: dict | None, url: str) -> bool:
    return bool(check and check.get("google_canonical") and U.normalize(check["google_canonical"]) != url)


def summary(con: sqlite3.Connection, site: str) -> list[tuple[str, int]]:
    ensure_tables(con)
    return con.execute(
        """SELECT c.coverage, COUNT(*) FROM index_checks c JOIN urls u ON u.id = c.url_id
           JOIN (SELECT url_id, MAX(checked_at) m FROM index_checks GROUP BY url_id) l
             ON l.url_id = c.url_id AND l.m = c.checked_at
           WHERE u.site = ? GROUP BY c.coverage ORDER BY 2 DESC""", (site,)).fetchall()
