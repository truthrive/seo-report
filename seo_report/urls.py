"""Chuẩn hóa, phân loại và gom nhóm URL.

Một URL báo cáo gom mọi dòng GSC chỉ khác nhau ở #mục hoặc tham số theo dõi (utm_…, gclid…).
Loại URL lấy theo thứ tự ưu tiên: sửa tay > đọc schema trong trang > quy tắc đường dẫn.
"""
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

HOME = "Trang chủ"
CATEGORY = "Danh mục"
BRAND = "Danh mục con"  # thương hiệu (trong-kinh-zeiss) hoặc tính năng (kinh-da-trong)
PRODUCT = "Sản phẩm"
BLOG = "Blog"
STORE = "Cửa hàng"
INFO = "Trang thông tin"
LEGACY = "URL cũ/kỹ thuật"
TYPES = [HOME, CATEGORY, BRAND, PRODUCT, BLOG, STORE, INFO, LEGACY]

DEFAULT_GROUP = "SEO chủ lực"

TRACKING_PARAMS = {"gclid", "fbclid", "gbraid", "wbraid", "srsltid", "msclkid", "_gl"}

# Quy tắc riêng cho matkinhtamduc.com. Trang cấp 1 không khớp quy tắc nào thì đọc schema để phân loại.
CATEGORY_ROOTS = {"gong-kinh", "kinh-mat", "trong-kinh-chinh-hang", "kinh-ap-trong-chinh-hang"}
COLLECTION_ROOT = "bo-suu-tap"
INFO_PAGES = {
    "lien-he", "gioi-thieu", "dat-lich-hen", "tuyen-dung", "cart", "profile", "huong-dan-mua-hang",
    "tich-diem-thanh-vien", "chuong-trinh-khuyen-mai-thang", "disclaimer", "do-pd",
    "chon-kinh-theo-khuon-mat", "quiz", "tin-tuc",
}
INFO_PREFIXES = ("chinh-sach-", "dieu-khoan-", "mo-phong-")
LEGACY_PATH = re.compile(r"^/(\d{4}/\d{2}/|category/|tag/|author/|wp-|feed/)|/page/\d+/?$")


def normalize(raw: str) -> str:
    """Bỏ #mục và tham số theo dõi; giữ nguyên các tham số khác và cách mã hóa của chúng."""
    raw = raw.strip()
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw.lstrip("/")
    s = urlsplit(raw)
    kept = [
        part for part in s.query.split("&")
        if part and not (k := part.split("=", 1)[0].lower()).startswith("utm_") and k not in TRACKING_PARAMS
    ]
    return urlunsplit((s.scheme.lower(), s.netloc.lower(), s.path or "/", "&".join(kept), ""))


def classify_by_rules(url: str) -> tuple[str | None, str]:
    """Trả về (loại, ghi chú); loại None nghĩa là cần đọc schema của trang."""
    s = urlsplit(url)
    if s.query:
        return LEGACY, "Có tham số"
    path = s.path or "/"
    if path == "/":
        return HOME, ""
    if LEGACY_PATH.search(path):
        return LEGACY, "Đường dẫn kiểu WordPress cũ"
    parts = [p for p in path.split("/") if p]
    first = parts[0]
    if first == COLLECTION_ROOT:
        return CATEGORY, ""
    if first in CATEGORY_ROOTS:
        return (CATEGORY, "") if len(parts) == 1 else (BRAND, "")
    if first.startswith("cua-hang") or path.startswith("/ve-tam-duc/he-thong-cua-hang"):
        return STORE, ""
    if first == "ve-tam-duc":
        return INFO, ""
    if first in INFO_PAGES or first.startswith(INFO_PREFIXES):
        return INFO, ""
    if len(parts) > 1:
        return LEGACY, "Đường dẫn nhiều cấp không thuộc danh mục"
    return None, ""


def reapply_rules(con: sqlite3.Connection, site: str) -> int:
    """Chạy lại quy tắc cho URL đang phân loại theo quy tắc (sau khi sửa quy tắc). Không đụng loại sửa tay hay từ schema."""
    changed = 0
    with con:
        for url_id, url, old in con.execute(
                "SELECT id, url, type FROM urls WHERE site = ? AND type_source = 'rule'", (site,)).fetchall():
            type_, note = classify_by_rules(url)
            if type_ != old:
                con.execute("UPDATE urls SET type = ?, type_source = ?, note = ? WHERE id = ?",
                            (type_, "rule" if type_ else None, note, url_id))
                changed += 1
    return changed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_change(con: sqlite3.Connection, user: str, site: str, action: str, url: str | None, detail: str = "") -> None:
    con.execute("INSERT INTO change_log (at, user, site, action, url, detail) VALUES (?, ?, ?, ?, ?, ?)",
                (_now(), user, site, action, url, detail))


def _get_or_create_url(con: sqlite3.Connection, site: str, url: str) -> int:
    row = con.execute("SELECT id FROM urls WHERE site = ? AND url = ?", (site, url)).fetchone()
    if row:
        return row[0]
    type_, note = classify_by_rules(url)
    cur = con.execute("INSERT INTO urls (site, url, type, type_source, note) VALUES (?, ?, ?, ?, ?)",
                      (site, url, type_, "rule" if type_ else None, note))
    return cur.lastrowid


def assign_urls(con: sqlite3.Connection, site: str) -> int:
    """Gắn mỗi dòng GSC chưa gắn vào URL báo cáo tương ứng. Chạy sau mỗi lần sync."""
    pending = con.execute(
        "SELECT p.id, p.url FROM pages p LEFT JOIN page_url pu ON pu.page_id = p.id "
        "WHERE p.site = ? AND pu.page_id IS NULL", (site,)
    ).fetchall()
    with con:
        for page_id, raw in pending:
            con.execute("INSERT INTO page_url VALUES (?, ?)", (page_id, _get_or_create_url(con, site, normalize(raw))))
    return len(pending)


def ensure_group(con: sqlite3.Connection, site: str, name: str = DEFAULT_GROUP) -> int:
    with con:
        con.execute("INSERT OR IGNORE INTO url_groups (site, name) VALUES (?, ?)", (site, name.strip()))
    return con.execute("SELECT id FROM url_groups WHERE site = ? AND name = ?", (site, name.strip())).fetchone()[0]


def list_groups(con: sqlite3.Connection, site: str) -> list[tuple[int, str]]:
    return con.execute("SELECT id, name FROM url_groups WHERE site = ? ORDER BY id", (site,)).fetchall()


def _match_existing(con: sqlite3.Connection, site: str, url: str) -> int | None:
    """Tìm URL đã có, thử thêm các biến thể hay gặp khi copy link: thiếu / cuối, có www, http."""
    s = urlsplit(url)
    host = s.netloc.removeprefix("www.")
    paths = [s.path] if s.path.endswith("/") or s.query else [s.path, s.path + "/"]
    for path in paths:
        candidate = urlunsplit(("https", host, path, s.query, ""))
        row = con.execute("SELECT id FROM urls WHERE site = ? AND url = ?", (site, candidate)).fetchone()
        if row:
            return row[0]
    return None


def add_to_group(con: sqlite3.Connection, site: str, group_id: int, text: str, user: str) -> dict:
    """Thêm các link dán vào (mỗi dòng hoặc cách nhau bởi khoảng trắng) vào nhóm."""
    result = {"added": [], "already": [], "no_data": [], "invalid": []}
    seen = set()
    with con:
        for raw in re.split(r"\s+", text.strip()):
            if not raw:
                continue
            if "." not in raw:
                result["invalid"].append(raw)
                continue
            url = normalize(raw)
            url_id = _match_existing(con, site, url)
            if url_id is None:
                url_id = _get_or_create_url(con, site, url)
                result["no_data"].append(url)
            if url_id in seen:  # cùng một link dán hai lần, chỉ khác / cuối, www…
                continue
            seen.add(url_id)
            canonical = con.execute("SELECT url FROM urls WHERE id = ?", (url_id,)).fetchone()[0]
            cur = con.execute("INSERT OR IGNORE INTO url_group_members VALUES (?, ?, ?, ?)",
                              (group_id, url_id, _now(), user))
            if cur.rowcount:
                result["added"].append(canonical)
                log_change(con, user, site, "Thêm vào nhóm", canonical, _group_name(con, group_id))
            else:
                result["already"].append(canonical)
    return result


def _group_name(con: sqlite3.Connection, group_id: int) -> str:
    return con.execute("SELECT name FROM url_groups WHERE id = ?", (group_id,)).fetchone()[0]


def remove_from_group(con: sqlite3.Connection, site: str, group_id: int, url_ids: list[int], user: str) -> None:
    """Chỉ bỏ khỏi nhóm; số liệu và lịch sử của URL vẫn giữ nguyên."""
    with con:
        for url_id in url_ids:
            url = con.execute("SELECT url FROM urls WHERE id = ?", (url_id,)).fetchone()[0]
            con.execute("DELETE FROM url_group_members WHERE group_id = ? AND url_id = ?", (group_id, url_id))
            log_change(con, user, site, "Bỏ khỏi nhóm", url, _group_name(con, group_id))


def set_type(con: sqlite3.Connection, site: str, url_ids: list[int], type_: str, user: str) -> None:
    if type_ not in TYPES:
        raise ValueError(type_)
    with con:
        for url_id in url_ids:
            url, old = con.execute("SELECT url, type FROM urls WHERE id = ?", (url_id,)).fetchone()
            con.execute("UPDATE urls SET type = ?, type_source = 'manual', note = '' WHERE id = ?", (type_, url_id))
            log_change(con, user, site, "Đổi loại", url, f"{old or 'chưa phân loại'} → {type_}")


def _since(days: int, today: date | None = None) -> str:
    return ((today or date.today()) - timedelta(days=days)).isoformat()


_METRICS_90D = """
    LEFT JOIN (
        SELECT pu.url_id, SUM(d.clicks) AS clicks, SUM(d.impressions) AS impressions
        FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id
        WHERE d.date >= ? GROUP BY pu.url_id
    ) m ON m.url_id = u.id
"""


def group_members(con: sqlite3.Connection, group_id: int, days: int = 90) -> list[dict]:
    rows = con.execute(
        f"""SELECT u.id, u.url, u.type, COALESCE(m.clicks, 0), COALESCE(m.impressions, 0), g.added_at, g.added_by
            FROM url_group_members g JOIN urls u ON u.id = g.url_id {_METRICS_90D}
            WHERE g.group_id = ? ORDER BY COALESCE(m.clicks, 0) DESC""",
        (_since(days), group_id),
    ).fetchall()
    keys = ["id", "url", "type", "clicks", "impressions", "added_at", "added_by"]
    return [dict(zip(keys, r)) for r in rows]


def suggestions(con: sqlite3.Connection, site: str, group_id: int, days: int = 90, limit: int = 100) -> list[dict]:
    """URL nhiều click nhất chưa có trong nhóm, bỏ qua URL cũ/kỹ thuật."""
    rows = con.execute(
        f"""SELECT u.id, u.url, u.type, m.clicks, m.impressions FROM urls u {_METRICS_90D}
            WHERE u.site = ? AND m.clicks > 0 AND COALESCE(u.type, '') != ?
              AND u.id NOT IN (SELECT url_id FROM url_group_members WHERE group_id = ?)
            ORDER BY m.clicks DESC LIMIT ?""",
        (_since(days), site, LEGACY, group_id, limit),
    ).fetchall()
    return [dict(zip(["id", "url", "type", "clicks", "impressions"], r)) for r in rows]


def all_urls(con: sqlite3.Connection, site: str, days: int = 90) -> list[dict]:
    rows = con.execute(
        f"""SELECT u.id, u.url, COALESCE(u.type, 'Chờ đọc schema'), COALESCE(u.type_source, ''), COALESCE(u.note, ''),
                   COALESCE(m.clicks, 0), COALESCE(m.impressions, 0)
            FROM urls u {_METRICS_90D} WHERE u.site = ? ORDER BY COALESCE(m.clicks, 0) DESC, u.url""",
        (_since(days), site),
    ).fetchall()
    return [dict(zip(["id", "url", "type", "source", "note", "clicks", "impressions"], r)) for r in rows]


def type_summary(con: sqlite3.Connection, site: str) -> list[tuple[str, int]]:
    return con.execute(
        "SELECT COALESCE(type, 'Chờ đọc schema'), COUNT(*) FROM urls WHERE site = ? GROUP BY 1 ORDER BY 2 DESC",
        (site,),
    ).fetchall()


def recent_changes(con: sqlite3.Connection, site: str, limit: int = 200) -> list[dict]:
    rows = con.execute(
        "SELECT at, user, action, url, detail FROM change_log WHERE site = ? ORDER BY id DESC LIMIT ?", (site, limit)
    ).fetchall()
    return [dict(zip(["at", "user", "action", "url", "detail"], r)) for r in rows]
