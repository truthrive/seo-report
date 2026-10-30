"""Head KW, keyword phụ, cannibalization và số liệu theo kỳ cho từng URL báo cáo.

Vai trò của keyword (head/phụ/bị loại) tính trên cửa sổ cố định (mặc định 28 ngày) để không đổi qua đổi lại
mỗi tuần; số liệu hiển thị thì theo kỳ đang xem.
"""
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .config import KeywordSettings
from .urls import log_change

# Lý do loại, ghi ra Excel ở bước sau.
R_BRAND = "Thương hiệu"
R_LOW_IMPR = "Impression thấp"
R_FAR = "Position quá xa"
R_OTHER_URL = "URL khác mạnh hơn"
R_OVER_LIMIT = "Ngoài top keyword phụ"


def fold(text: str) -> str:
    """Bỏ dấu, chữ hoa, khoảng trắng và ký tự đặc biệt: 'Mắt kính Tâm Đức' → 'matkinhtamduc'."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in text if unicodedata.category(c) != "Mn"))


def is_brand(query: str, terms) -> bool:
    q = fold(query)
    return any(fold(t) and fold(t) in q for t in terms)


@dataclass
class Kw:
    query_id: int
    query: str
    clicks: int
    impressions: int
    position: float
    role: str = ""  # "Head", "Phụ" hoặc "Bị loại"
    reason: str = ""
    stronger_url: str | None = None

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions else 0.0


@dataclass
class UrlKeywords:
    url_id: int
    head: Kw | None = None
    head_basis: str = ""  # "click", hoặc "impression" khi không query nào có click
    secondary: list[Kw] = field(default_factory=list)
    excluded: list[Kw] = field(default_factory=list)
    cannibal: list[Kw] = field(default_factory=list)


def latest_date(con: sqlite3.Connection, site: str) -> date:
    d = con.execute("SELECT MAX(date) FROM gsc_fetch_log WHERE site = ?", (site,)).fetchone()[0]
    return date.fromisoformat(d) if d else date.today() - timedelta(days=3)


def weeks(end: date, count: int = 12) -> list[tuple[date, date]]:
    """Các tuần thứ Hai–Chủ nhật đã trọn vẹn tính đến `end`, tuần mới nhất trước."""
    last_sunday = end - timedelta(days=(end.weekday() + 1) % 7)
    return [(last_sunday - timedelta(days=6 + 7 * i), last_sunday - timedelta(days=7 * i)) for i in range(count)]


def _query_stats(con, site, start: date, end: date):
    """Số liệu 28 ngày của mọi cặp (query, URL báo cáo) trên site."""
    return con.execute(
        """SELECT d.query_id, pu.url_id, SUM(d.clicks), SUM(d.impressions),
                  SUM(d.position * d.impressions) / NULLIF(SUM(d.impressions), 0)
           FROM gsc_query_daily d JOIN page_url pu ON pu.page_id = d.page_id
           JOIN urls u ON u.id = pu.url_id AND u.site = ?
           WHERE d.date BETWEEN ? AND ? GROUP BY d.query_id, pu.url_id""",
        (site, start.isoformat(), end.isoformat()),
    ).fetchall()


def analyze(con: sqlite3.Connection, site: str, url_ids: list[int], end: date,
            settings: KeywordSettings) -> dict[int, UrlKeywords]:
    start = end - timedelta(days=settings.window_days - 1)
    rows = _query_stats(con, site, start, end)
    by_query: dict[int, list[tuple]] = {}
    for qid, uid, c, i, p in rows:
        by_query.setdefault(qid, []).append((uid, c, i, p or 0.0))
    wanted = set(url_ids)
    needed_qids = {qid for qid, uid, *_ in rows if uid in wanted}
    texts = _texts(con, "queries", "text", needed_qids)
    url_texts = _texts(con, "urls", "url", {uid for qid in needed_qids for uid, *_ in by_query[qid]})

    result = {uid: UrlKeywords(uid) for uid in url_ids}
    for qid in needed_qids:
        competitors = by_query[qid]
        best = max(competitors, key=lambda r: (r[1], r[2]))
        strong_enough = [r for r in competitors if r[2] >= settings.min_impressions]
        for uid, c, i, p in competitors:
            if uid not in wanted:
                continue
            kw = Kw(qid, texts[qid], c, i, p)
            if best[0] != uid:
                kw.stronger_url = url_texts[best[0]]
                if len(strong_enough) >= 2 and i >= settings.min_impressions \
                        and not is_brand(texts[qid], settings.brand_terms):
                    result[uid].cannibal.append(kw)
            result[uid].excluded.append(kw)  # tạm để hết vào đây, chọn head/phụ ở dưới

    for uk in result.values():
        _assign_roles(uk, settings)
    return result


def cannibal_rows(con: sqlite3.Connection, site: str, url_ids: list[int], end: date,
                  settings: KeywordSettings) -> list[dict]:
    """Mọi URL cùng nhận các query bị cannibalization có dính tới nhóm URL đang xem, URL mạnh nhất đứng đầu."""
    start = end - timedelta(days=settings.window_days - 1)
    by_query: dict[int, list[tuple]] = {}
    for qid, uid, c, i, p in _query_stats(con, site, start, end):
        by_query.setdefault(qid, []).append((uid, c, i, p or 0.0))
    wanted = set(url_ids)
    picked = {}
    for qid, comps in by_query.items():
        strong = [r for r in comps if r[2] >= settings.min_impressions]
        if len(strong) >= 2 and wanted & {r[0] for r in strong}:
            picked[qid] = sorted(strong, key=lambda r: (-r[1], -r[2]))
    texts = _texts(con, "queries", "text", set(picked))
    url_texts = _texts(con, "urls", "url", {r[0] for rs in picked.values() for r in rs})
    out = []
    for qid, comps in sorted(picked.items(), key=lambda kv: -sum(r[2] for r in kv[1])):
        if is_brand(texts[qid], settings.brand_terms):
            continue
        for rank, (uid, c, i, p) in enumerate(comps):
            out.append({"query": texts[qid], "url": url_texts[uid], "in_group": uid in wanted,
                        "strongest": rank == 0, "clicks": c, "impressions": i, "position": p})
    return out


def _texts(con, table: str, column: str, ids: set[int]) -> dict[int, str]:
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        out.update(con.execute(f"SELECT id, {column} FROM {table} WHERE id IN ({','.join('?' * len(chunk))})",
                               chunk).fetchall())
    return out


def _assign_roles(uk: UrlKeywords, s: KeywordSettings) -> None:
    candidates = sorted(uk.excluded, key=lambda k: (-k.clicks, -k.impressions, k.query))
    non_brand = [k for k in candidates if not is_brand(k.query, s.brand_terms)]
    if non_brand:
        uk.head = non_brand[0]
        uk.head.role = "Head"
        uk.head_basis = "click" if uk.head.clicks > 0 else "impression"
    for k in candidates:
        if k is uk.head:
            continue
        k.role = "Bị loại"
        if is_brand(k.query, s.brand_terms):
            k.reason = R_BRAND
        elif k.impressions < s.min_impressions:
            k.reason = R_LOW_IMPR
        elif k.position > s.max_position:
            k.reason = R_FAR
        elif k.stronger_url:
            k.reason = R_OTHER_URL
        elif len(uk.secondary) >= s.max_secondary:
            k.reason = R_OVER_LIMIT
        else:
            k.role = "Phụ"
            uk.secondary.append(k)
    uk.excluded = [k for k in candidates if k.role == "Bị loại"]


def url_period(con: sqlite3.Connection, url_ids: list[int], start: date, end: date) -> dict[int, tuple]:
    """(clicks, impressions, position) của từng URL báo cáo trong kỳ; gồm cả query bị Google ẩn."""
    if not url_ids:
        return {}
    q = f"""SELECT pu.url_id, SUM(d.clicks), SUM(d.impressions),
                   SUM(d.position * d.impressions) / NULLIF(SUM(d.impressions), 0)
            FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id
            WHERE pu.url_id IN ({','.join('?' * len(url_ids))}) AND d.date BETWEEN ? AND ?
            GROUP BY pu.url_id"""
    return {r[0]: (r[1] or 0, r[2] or 0, r[3]) for r in con.execute(q, (*url_ids, start.isoformat(), end.isoformat()))}


def query_period(con: sqlite3.Connection, url_id: int, start: date, end: date) -> dict[int, tuple]:
    """(clicks, impressions, position) của từng query của một URL trong kỳ."""
    q = """SELECT d.query_id, SUM(d.clicks), SUM(d.impressions),
                  SUM(d.position * d.impressions) / NULLIF(SUM(d.impressions), 0)
           FROM gsc_query_daily d JOIN page_url pu ON pu.page_id = d.page_id
           WHERE pu.url_id = ? AND d.date BETWEEN ? AND ? GROUP BY d.query_id"""
    return {r[0]: r[1:] for r in con.execute(q, (url_id, start.isoformat(), end.isoformat()))}


def weekly_series(con: sqlite3.Connection, url_id: int, wks: list[tuple[date, date]]) -> list[dict]:
    out = []
    for start, end in reversed(wks):
        c, i, p = url_period(con, [url_id], start, end).get(url_id, (0, 0, None))
        out.append({"week": f"{start:%d/%m}", "clicks": c, "impressions": i, "position": round(p, 1) if p else None})
    return out


# ---- Target KW do người dùng gán ----

def ensure_tables(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS url_targets (
        url_id INTEGER PRIMARY KEY, keyword TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)""")


def targets(con: sqlite3.Connection, url_ids: list[int]) -> dict[int, str]:
    ensure_tables(con)
    return dict(_texts_where(con, url_ids))


def _texts_where(con, url_ids):
    if not url_ids:
        return []
    return con.execute(f"SELECT url_id, keyword FROM url_targets WHERE url_id IN ({','.join('?' * len(url_ids))})",
                       url_ids).fetchall()


def set_target(con: sqlite3.Connection, site: str, url_id: int, keyword: str, user: str) -> None:
    ensure_tables(con)
    keyword = " ".join(keyword.split()).lower()
    url, = con.execute("SELECT url FROM urls WHERE id = ?", (url_id,)).fetchone()
    old = con.execute("SELECT keyword FROM url_targets WHERE url_id = ?", (url_id,)).fetchone()
    with con:
        if keyword:
            con.execute("INSERT OR REPLACE INTO url_targets VALUES (?, ?, ?, ?)",
                        (url_id, keyword, datetime.now(timezone.utc).isoformat(timespec="seconds"), user))
        else:
            con.execute("DELETE FROM url_targets WHERE url_id = ?", (url_id,))
        log_change(con, user, site, "Sửa target KW", url, f"{old[0] if old else '(trống)'} → {keyword or '(trống)'}")


def head_matches_target(head: Kw | None, target: str | None) -> bool | None:
    """None khi chưa gán target hoặc chưa có head; so sánh không phân biệt dấu và khoảng trắng."""
    if not target or not head:
        return None
    return fold(head.query) == fold(target)
