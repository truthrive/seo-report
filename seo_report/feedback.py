"""Yêu cầu hỗ trợ: người xem báo cáo (quyền "Khách hàng": quản lý, team nội bộ của bên dự án…) gửi câu hỏi / báo lỗi
số liệu / đề xuất ngay trên trang đang xem; đội SEO đọc, trả lời và đánh dấu đã xử lý.

Lưu trong file dữ liệu của từng dự án (bảng client_feedback). Trạng thái: new (mới) → seen (team đã xem) → done
(đã xử lý). Người gửi thấy lại yêu cầu của chính mình kèm trạng thái và câu trả lời.
"""
import sqlite3
from datetime import datetime, timezone

CATEGORIES = {"question": "Câu hỏi", "data": "Báo lỗi số liệu", "idea": "Đề xuất", "other": "Khác"}
STATUS = {"new": ("Mới", "amber"), "seen": ("Đã tiếp nhận", "blue"), "done": ("Đã xử lý", "green")}
MAX_LEN = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS client_feedback (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    author TEXT NOT NULL,
    page TEXT NOT NULL DEFAULT '',      -- tên màn (Tổng quan, Thứ hạng…)
    path TEXT NOT NULL DEFAULT '',      -- địa chỉ màn lúc gửi, để team mở đúng chỗ
    category TEXT NOT NULL DEFAULT 'question',
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    reply TEXT NOT NULL DEFAULT '',
    replied_by TEXT NOT NULL DEFAULT '',
    replied_at TEXT,
    seen_at TEXT,
    done_at TEXT
);
CREATE INDEX IF NOT EXISTS client_feedback_status ON client_feedback (status, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def add(con, author: str, body: str, page: str = "", path: str = "", category: str = "question") -> int:
    body = (body or "").strip()
    if not body:
        raise ValueError("Cần nhập nội dung yêu cầu")
    if len(body) > MAX_LEN:
        raise ValueError(f"Nội dung tối đa {MAX_LEN} ký tự")
    ensure_tables(con)
    with con:
        cur = con.execute("INSERT INTO client_feedback (created_at, author, page, path, category, body) "
                          "VALUES (?, ?, ?, ?, ?, ?)",
                          (_now(), str(author).strip().lower(), page[:80], path[:300],
                           category if category in CATEGORIES else "other", body))
    return cur.lastrowid


def _rows(con, where: str = "", args: tuple = (), limit: int = 200) -> list[dict]:
    ensure_tables(con)
    cols = ("id", "created_at", "author", "page", "path", "category", "body", "status", "reply", "replied_by",
            "replied_at", "seen_at", "done_at")
    q = f"SELECT {', '.join(cols)} FROM client_feedback {where} ORDER BY created_at DESC, id DESC LIMIT ?"
    return [dict(zip(cols, r)) for r in con.execute(q, (*args, limit))]


def list_all(con, status: str | None = None, limit: int = 200) -> list[dict]:
    """Cho đội SEO: mọi yêu cầu (mới nhất trước), lọc theo trạng thái nếu có."""
    return _rows(con, "WHERE status = ?", (status,), limit) if status else _rows(con, limit=limit)


def list_mine(con, author: str, limit: int = 10) -> list[dict]:
    """Cho người gửi: yêu cầu của chính người này."""
    return _rows(con, "WHERE author = ?", (str(author).strip().lower(),), limit)


def count_new(con) -> int:
    ensure_tables(con)
    return con.execute("SELECT COUNT(*) FROM client_feedback WHERE status = 'new'").fetchone()[0]


def mark_seen(con, ids: list[int]) -> None:
    """Đội SEO mở trang Yêu cầu hỗ trợ: yêu cầu mới đang hiện chuyển sang "Đã tiếp nhận" (người gửi thấy đã được đọc)."""
    if not ids:
        return
    ensure_tables(con)
    with con:
        con.executemany("UPDATE client_feedback SET status = 'seen', seen_at = ? WHERE id = ? AND status = 'new'",
                        [(_now(), i) for i in ids])


def reply(con, fid: int, text: str, who: str, done: bool = False) -> None:
    text = (text or "").strip()
    if not text:
        raise ValueError("Cần nhập câu trả lời")
    ensure_tables(con)
    now = _now()
    with con:
        con.execute("UPDATE client_feedback SET reply = ?, replied_by = ?, replied_at = ?, "
                    "seen_at = COALESCE(seen_at, ?), status = ?, done_at = CASE WHEN ? THEN ? ELSE done_at END "
                    "WHERE id = ?",
                    (text[:MAX_LEN], str(who), now, now, "done" if done else "seen", done, now, fid))


def set_status(con, fid: int, status: str) -> None:
    if status not in STATUS:
        raise ValueError("Trạng thái không hợp lệ")
    ensure_tables(con)
    now = _now()
    with con:
        con.execute("UPDATE client_feedback SET status = ?, seen_at = COALESCE(seen_at, ?), "
                    "done_at = CASE WHEN ? = 'done' THEN ? ELSE NULL END WHERE id = ?",
                    (status, now, status, now, fid))
