"""Search Console ngoài tìm kiếm web: Google Discover, tìm kiếm hình ảnh / video, tab Tin tức, ứng dụng Google
News; và danh sách sitemap. Cùng quyền Search Console đang có, miễn phí.

- Tổng theo ngày của từng loại (`gsc_type_daily`): lần đầu ~16 tháng, sau đó nối tiếp (lấy lại 3 ngày cuối vì GSC
  còn cập nhật).
- Trang hàng đầu của từng loại (`gsc_type_pages`): 28 ngày gần nhất và 28 ngày trước đó để so, ghi đè mỗi lần lấy.
- Sitemap (`gsc_sitemaps`): đường dẫn, lần gửi / Google đọc gần nhất, số URL đã gửi, lỗi, cảnh báo.
Discover và Google News không có vị trí trung bình (Google không trả).
- Loại kết quả (`gsc_appearance`, chiều searchAppearance): click / hiển thị theo dạng hiển thị trên Google (đoạn trích
  sản phẩm, đánh giá sao, FAQ, video…), 28 ngày gần nhất và 28 ngày trước đó.
- Số theo giờ (`gsc_hourly`, dataState hourly_all): click / hiển thị từng giờ của mấy ngày gần nhất để thấy sớm khi
  traffic tụt (Google trả theo giờ Thái Bình Dương; lưu theo UTC, hiện theo giờ Việt Nam).
"""
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

TYPES = {"web": "Tìm kiếm web", "image": "Hình ảnh", "video": "Video", "news": "Tab Tin tức",
         "discover": "Google Discover", "googleNews": "Google News"}
NO_POSITION = {"discover", "googleNews"}
FIRST_DAYS = 486          # ~16 tháng (giới hạn của Search Console)
OVERLAP_DAYS = 3
PAGE_DAYS = 28
PAGE_ROWS = 100
HOURLY_DAYS = 3           # Google giữ số theo giờ vài ngày gần nhất
HOURLY_KEEP = 10          # giữ số theo giờ bao nhiêu ngày (để so cùng giờ hôm trước / tuần trước)
HOURLY_EVERY_H = 3        # lịch tự lấy số theo giờ
APPEARANCE = {
    "PRODUCT_SNIPPETS": "Đoạn trích sản phẩm (giá, tình trạng)", "MERCHANT_LISTINGS": "Danh sách người bán",
    "REVIEW_SNIPPET": "Đánh giá sao", "FAQ_RICH_RESULT": "Câu hỏi thường gặp (FAQ)", "VIDEO": "Video",
    "AMP_BLUE_LINK": "AMP", "AMP_TOP_STORIES": "AMP · Tin nổi bật", "TRANSLATED_RESULT": "Kết quả được dịch",
    "RECIPE_FEATURE": "Công thức", "RECIPE_RICH_SNIPPET": "Công thức (rich)", "EVENT": "Sự kiện",
    "JOB_LISTING": "Việc làm", "JOB_DETAILS": "Chi tiết việc làm", "EDUCATION_Q_AND_A": "Hỏi đáp giáo dục",
    "PRACTICE_PROBLEMS": "Bài tập", "SPECIAL_ANNOUNCEMENT": "Thông báo đặc biệt", "WEBLITE": "Web Light",
    "ORGANIC_SHOPPING": "Mua sắm tự nhiên", "LEARNING_VIDEOS": "Video học tập"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS gsc_type_daily (
    site TEXT NOT NULL,
    type TEXT NOT NULL,
    date TEXT NOT NULL,
    clicks INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    position REAL,
    PRIMARY KEY (site, type, date)
);
CREATE TABLE IF NOT EXISTS gsc_type_pages (
    site TEXT NOT NULL,
    type TEXT NOT NULL,
    period TEXT NOT NULL,          -- now | prev
    page TEXT NOT NULL,
    clicks INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    position REAL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    PRIMARY KEY (site, type, period, page)
);
CREATE TABLE IF NOT EXISTS gsc_appearance (
    site TEXT NOT NULL,
    period TEXT NOT NULL,          -- now | prev
    appearance TEXT NOT NULL,
    clicks INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    position REAL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    PRIMARY KEY (site, period, appearance)
);
CREATE TABLE IF NOT EXISTS gsc_hourly (
    site TEXT NOT NULL,
    hour TEXT NOT NULL,            -- UTC, YYYY-MM-DDTHH:00
    clicks INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    position REAL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (site, hour)
);
CREATE TABLE IF NOT EXISTS gsc_sitemaps (
    site TEXT NOT NULL,
    path TEXT NOT NULL,
    data TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (site, path)
);
"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pages(service, site: str, search_type: str, start: date, end: date) -> list[dict]:
    from .gsc import _execute
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": ["page"], "type": search_type,
            "dataState": "all", "rowLimit": PAGE_ROWS}
    return _execute(service.searchanalytics().query(siteUrl=site, body=body)).get("rows", [])


def refresh(con, site: str, service, today: date | None = None, log=print) -> dict:
    """Lấy số mọi loại tìm kiếm + sitemap. Trả {type: số ngày đã lưu}."""
    from .gsc import _execute, query_site_totals
    ensure_tables(con)
    today = today or date.today()
    end = today - timedelta(days=1)
    out = {}
    p_end = today - timedelta(days=3)  # số trang: bỏ mấy ngày cuối còn thiếu
    p_start = p_end - timedelta(days=PAGE_DAYS - 1)
    q_end, q_start = p_start - timedelta(days=1), p_start - timedelta(days=PAGE_DAYS)
    for t in TYPES:
        last = con.execute("SELECT MAX(date) FROM gsc_type_daily WHERE site = ? AND type = ?", (site, t)).fetchone()[0]
        start = (date.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)) if last else today - timedelta(days=FIRST_DAYS)
        try:
            rows = query_site_totals(service, site, start.isoformat(), end.isoformat(), search_type=t)
            pos = t not in NO_POSITION
            with con:
                for r in rows:
                    con.execute("INSERT OR REPLACE INTO gsc_type_daily VALUES (?, ?, ?, ?, ?, ?)",
                                (site, t, r["keys"][0], int(r.get("clicks", 0)), int(r.get("impressions", 0)),
                                 r.get("position") if pos else None))
            out[t] = len(rows)
            now_rows = _pages(service, site, t, p_start, p_end)
            prev_rows = _pages(service, site, t, q_start, q_end)
            with con:
                con.execute("DELETE FROM gsc_type_pages WHERE site = ? AND type = ?", (site, t))
                for period, rs, a, b in (("now", now_rows, p_start, p_end), ("prev", prev_rows, q_start, q_end)):
                    for r in rs:
                        con.execute("INSERT OR REPLACE INTO gsc_type_pages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                    (site, t, period, r["keys"][0], int(r.get("clicks", 0)),
                                     int(r.get("impressions", 0)), r.get("position") if pos else None,
                                     a.isoformat(), b.isoformat()))
        except Exception as e:  # noqa: BLE001  (một loại lỗi không chặn loại khác)
            log(f"Search Console {TYPES[t]}: {str(e)[:200]}")
    try:  # loại kết quả (chiều searchAppearance chỉ dùng một mình, không ghép với page / date)
        with con:
            con.execute("DELETE FROM gsc_appearance WHERE site = ?", (site,))
            for period, a, b in (("now", p_start, p_end), ("prev", q_start, q_end)):
                body = {"startDate": a.isoformat(), "endDate": b.isoformat(), "dimensions": ["searchAppearance"],
                        "type": "web", "dataState": "all"}
                for r in _execute(service.searchanalytics().query(siteUrl=site, body=body)).get("rows", []):
                    con.execute("INSERT OR REPLACE INTO gsc_appearance VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (site, period, r["keys"][0], int(r.get("clicks", 0)), int(r.get("impressions", 0)),
                                 r.get("position"), a.isoformat(), b.isoformat()))
        out["appearance"] = True
    except Exception as e:  # noqa: BLE001
        log(f"Search Console loại kết quả: {str(e)[:200]}")
    try:
        out["hourly"] = refresh_hourly(con, site, service, today)
    except Exception as e:  # noqa: BLE001
        log(f"Search Console số theo giờ: {str(e)[:200]}")
    try:
        maps = _execute(service.sitemaps().list(siteUrl=site)).get("sitemap", [])
        with con:
            con.execute("DELETE FROM gsc_sitemaps WHERE site = ?", (site,))
            for m in maps:
                con.execute("INSERT OR REPLACE INTO gsc_sitemaps VALUES (?, ?, ?, ?)",
                            (site, m.get("path", ""), json.dumps(m, ensure_ascii=False), _now()))
        out["sitemaps"] = len(maps)
    except Exception as e:  # noqa: BLE001
        log(f"Search Console sitemap: {str(e)[:200]}")
    return out


def _utc_hour(key: str) -> str:
    """'2026-11-11T00:00:00-08:00' → '2026-11-11T08:00' (UTC)."""
    return datetime.fromisoformat(key).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")


def refresh_hourly(con, site: str, service, today: date | None = None) -> int:
    """Số theo giờ HOURLY_DAYS ngày gần nhất (ghi đè giờ đã có: giờ gần đây Google còn cập nhật)."""
    from .gsc import _execute
    ensure_tables(con)
    today = today or date.today()
    body = {"startDate": (today - timedelta(days=HOURLY_DAYS)).isoformat(), "endDate": today.isoformat(),
            "dimensions": ["hour"], "type": "web", "dataState": "hourly_all", "rowLimit": 1000}
    resp = _execute(service.searchanalytics().query(siteUrl=site, body=body))
    rows = resp.get("rows", [])
    cut_partial = (resp.get("metadata") or {}).get("firstIncompleteHour")  # từ giờ này Google chưa có đủ số
    if cut_partial:
        cut_utc = _utc_hour(cut_partial)
        rows = [r for r in rows if _utc_hour(r["keys"][0]) < cut_utc]
    now = _now()
    with con:
        if cut_partial:  # giờ dở dang đã lưu ở lần trước: bỏ, chờ số đủ
            con.execute("DELETE FROM gsc_hourly WHERE site = ? AND hour >= ?", (site, cut_utc))
        for r in rows:
            con.execute("INSERT OR REPLACE INTO gsc_hourly VALUES (?, ?, ?, ?, ?, ?)",
                        (site, _utc_hour(r["keys"][0]), int(r.get("clicks", 0)), int(r.get("impressions", 0)),
                         r.get("position"), now))
        cut = (datetime.now(timezone.utc) - timedelta(days=HOURLY_KEEP)).strftime("%Y-%m-%dT%H:00")
        con.execute("DELETE FROM gsc_hourly WHERE site = ? AND hour < ?", (site, cut))
    return len(rows)


def hourly_due(con, site: str, now: datetime | None = None) -> bool:
    ensure_tables(con)
    last = con.execute("SELECT MAX(fetched_at) FROM gsc_hourly WHERE site = ?", (site,)).fetchone()[0]
    now = now or datetime.now(timezone.utc)
    return not last or datetime.fromisoformat(last) < now - timedelta(hours=HOURLY_EVERY_H)


def hourly(con, site: str, hours: int = 48) -> list[dict]:
    """Giờ gần nhất có số (theo giờ Việt Nam), kèm số cùng giờ hôm trước: [{"hour" (VN), "clicks", "impressions",
    "prev_clicks", "prev_impressions"}]."""
    ensure_tables(con)
    rows = {h: (c, i) for h, c, i in con.execute(
        "SELECT hour, clicks, impressions FROM gsc_hourly WHERE site = ? ORDER BY hour", (site,))}
    if not rows:
        return []
    vn = timezone(timedelta(hours=7))
    keys = sorted(rows)[-hours:]
    out = []
    for h in keys:
        t = datetime.strptime(h, "%Y-%m-%dT%H:00").replace(tzinfo=timezone.utc)
        p = (t - timedelta(days=1)).strftime("%Y-%m-%dT%H:00")
        out.append({"hour": t.astimezone(vn).strftime("%Y-%m-%d %H:00"), "clicks": rows[h][0],
                    "impressions": rows[h][1], "prev_clicks": rows.get(p, (None, None))[0],
                    "prev_impressions": rows.get(p, (None, None))[1]})
    return out


def appearance(con, site: str) -> tuple[list[dict], tuple[str, str] | None]:
    """[{"key", "name", "clicks", "impressions", "position", "prev_clicks", "prev_impressions"}], (từ, đến)."""
    ensure_tables(con)
    cur, prev, period = {}, {}, None
    for per, k, c, i, pos, a, b in con.execute(
            "SELECT period, appearance, clicks, impressions, position, start, end FROM gsc_appearance WHERE site = ?",
            (site,)):
        (cur if per == "now" else prev)[k] = (c, i, pos)
        if per == "now":
            period = (a, b)
    out = [{"key": k, "name": APPEARANCE.get(k, k.replace("_", " ").title()), "clicks": v[0], "impressions": v[1],
            "position": v[2], "prev_clicks": (prev.get(k) or (None,))[0],
            "prev_impressions": (prev.get(k) or (None, None))[1]}
           for k, v in cur.items()]
    for k, v in prev.items():
        if k not in cur:
            out.append({"key": k, "name": APPEARANCE.get(k, k), "clicks": 0, "impressions": 0, "position": None,
                        "prev_clicks": v[0], "prev_impressions": v[1]})
    return sorted(out, key=lambda r: -(r["impressions"] or 0)), period


# ---------------------------------------------------------------- đọc cho trang

def last_date(con, site: str) -> str | None:
    ensure_tables(con)
    return con.execute("SELECT MAX(date) FROM gsc_type_daily WHERE site = ?", (site,)).fetchone()[0]


def totals(con, site: str, start: date, end: date) -> dict[str, dict]:
    """{type: {clicks, impressions, ctr, position}} trong khoảng ngày (vị trí = trung bình theo lượt hiển thị)."""
    ensure_tables(con)
    out = {t: {"clicks": 0, "impressions": 0, "ctr": None, "position": None} for t in TYPES}
    for t, c, i, pw in con.execute(
            "SELECT type, SUM(clicks), SUM(impressions), SUM(position * impressions) FROM gsc_type_daily "
            "WHERE site = ? AND date BETWEEN ? AND ? GROUP BY type", (site, start.isoformat(), end.isoformat())):
        if t in out:
            out[t] = {"clicks": c or 0, "impressions": i or 0, "ctr": (c / i) if i else None,
                      "position": (pw / i) if i and pw is not None else None}
    return out


def series(con, site: str, search_type: str, start: date, end: date) -> list[dict]:
    """Theo tuần (thứ Hai): [{"week", "clicks", "impressions"}] cũ → mới."""
    ensure_tables(con)
    b: dict[str, dict] = {}
    for day, c, i in con.execute("SELECT date, clicks, impressions FROM gsc_type_daily WHERE site = ? AND type = ? "
                                 "AND date BETWEEN ? AND ? ORDER BY date",
                                 (site, search_type, start.isoformat(), end.isoformat())):
        d = date.fromisoformat(day)
        k = (d - timedelta(days=d.weekday())).isoformat()
        x = b.setdefault(k, {"week": k, "clicks": 0, "impressions": 0, "days": 0})
        x["clicks"] += c
        x["impressions"] += i
        x["days"] += 1
    out = [b[k] for k in sorted(b)]
    # tuần đầu / cuối chưa đủ 7 ngày (đầu khoảng, tuần đang chạy): bỏ để cột không thấp giả
    while out and out[-1]["days"] < 7:
        out.pop()
    while out and out[0]["days"] < 7:
        out.pop(0)
    return out


def top_pages(con, site: str, search_type: str) -> tuple[list[dict], tuple | None]:
    """Trang hàng đầu 28 ngày gần nhất kèm số 28 ngày trước: ([{page, clicks, impressions, ctr, position,
    prev_clicks, prev_impressions}], (start, end))."""
    ensure_tables(con)
    prev = {p: (c, i) for p, c, i in con.execute(
        "SELECT page, clicks, impressions FROM gsc_type_pages WHERE site = ? AND type = ? AND period = 'prev'",
        (site, search_type))}
    rows, period = [], None
    for p, c, i, pos, a, b in con.execute(
            "SELECT page, clicks, impressions, position, start, end FROM gsc_type_pages WHERE site = ? AND type = ? "
            "AND period = 'now' ORDER BY clicks DESC, impressions DESC", (site, search_type)):
        period = (a, b)
        pc, pi = prev.get(p, (None, None))
        rows.append({"page": p, "clicks": c, "impressions": i, "ctr": (c / i) if i else None, "position": pos,
                     "prev_clicks": pc, "prev_impressions": pi})
    return rows, period


def sitemaps(con, site: str) -> list[dict]:
    ensure_tables(con)
    return [json.loads(d) | {"fetched_at": f} for d, f in con.execute(
        "SELECT data, fetched_at FROM gsc_sitemaps WHERE site = ? ORDER BY path", (site,))]


def sitemap_checks(maps: list[dict], today: date | None = None) -> list[dict]:
    """Vấn đề của sitemap: [{"path", "level" (high | medium | info), "text"}]."""
    today = today or date.today()
    out = []
    if not maps:
        return [{"path": "", "level": "medium", "text": "Chưa gửi sitemap nào cho Search Console: gửi sitemap giúp "
                                                        "Google tìm trang mới nhanh hơn."}]
    for m in maps:
        path = m.get("path", "")
        if int(m.get("errors") or 0):
            out.append({"path": path, "level": "high", "text": f"{m['errors']} lỗi: Google không đọc được một phần "
                                                              "sitemap. Mở Search Console → Sitemap để xem chi tiết."})
        if int(m.get("warnings") or 0):
            out.append({"path": path, "level": "medium", "text": f"{m['warnings']} cảnh báo."})
        if m.get("isPending"):
            out.append({"path": path, "level": "info", "text": "Google chưa xử lý xong lần gửi gần nhất."})
        last = (m.get("lastDownloaded") or "")[:10]
        if last and date.fromisoformat(last) < today - timedelta(days=30):
            out.append({"path": path, "level": "medium",
                        "text": f"Google đọc lần cuối {date.fromisoformat(last):%d/%m/%Y}, đã hơn 30 ngày."})
    return out
