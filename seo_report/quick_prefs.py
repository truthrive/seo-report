"""Nút nhanh (nút + / chuột phải) do từng người tự chọn: các thao tác có sẵn của tool, lối tắt tới một trang / tab,
liên kết riêng. Lưu theo email ở file dữ liệu chính (đổi máy / trình duyệt vẫn giữ). Chưa chọn = mặc định theo quyền.

Mục: {"key", "label", "icon"}; key là mã thao tác có sẵn (BUILTIN), "page:/duong-dan" hoặc "link:https://…"."""
import json
import re
import sqlite3

MAX_ITEMS = 7                     # + mục "Tùy chỉnh" luôn ở cuối = tối đa 8 nút trên vòng
# mã → (tên, icon, chỉ người được sửa?)
BUILTIN = {
    "kw": ("Thêm từ khóa theo dõi", "playlist_add", True),
    "look": ("Tra từ khóa", "manage_search", False),
    "todo": ("Việc cần làm (Bản tin AI)", "checklist", True),
    "credit": ("Credit của tôi", "toll", False),
    "profile": ("Sửa hồ sơ", "account_circle", False),
    "rival": ("Thêm đối thủ", "group_add", True),
    "fb": ("Xử lý yêu cầu hỗ trợ", "support_agent", True),
}
DEFAULT_EDIT = ["kw", "look", "todo", "credit", "profile"]
DEFAULT_VIEW = ["look", "credit", "profile"]
CUSTOM = {"key": "__custom", "label": "Tùy chỉnh nút nhanh", "icon": "tune"}

SCHEMA = "CREATE TABLE IF NOT EXISTS quick_actions (email TEXT PRIMARY KEY, items TEXT NOT NULL, at TEXT)"
_ICON = re.compile(r"^[a-z0-9_]{2,40}$")


def ensure(con: sqlite3.Connection) -> None:
    con.execute(SCHEMA)


def builtin(key: str, can_edit: bool) -> dict | None:
    b = BUILTIN.get(key)
    if not b or (b[2] and not can_edit):
        return None
    return {"key": key, "label": b[0], "icon": b[1]}


def defaults(can_edit: bool) -> list[dict]:
    return [x for x in (builtin(k, can_edit) for k in (DEFAULT_EDIT if can_edit else DEFAULT_VIEW)) if x]


def clean(items: list, can_edit: bool) -> list[dict]:
    """Bỏ mục không hợp lệ / trùng / không có quyền; tối đa MAX_ITEMS."""
    out, seen = [], set()
    for x in items or []:
        if not isinstance(x, dict):
            continue
        key = str(x.get("key") or "").strip()
        if not key or key in seen:
            continue
        if key in BUILTIN:
            item = builtin(key, can_edit)
        elif key.startswith("page:"):
            path = key[5:]
            ok = path.startswith("/") and not path.startswith("//") and len(path) <= 200 and " " not in path
            item = {"key": key, "label": _label(x, path), "icon": _icon(x, "bookmark")} if ok else None
        elif key.startswith("link:"):
            url = key[5:]
            ok = (re.match(r"^https?://[^\s]{3,300}$", url) is not None
                  or (url.startswith("/") and not url.startswith("//") and len(url) <= 200 and " " not in url))
            item = {"key": key, "label": _label(x, url), "icon": _icon(x, "open_in_new")} if ok else None
        else:
            item = None
        if item:
            seen.add(key)
            out.append(item)
    return out[:MAX_ITEMS]


def _label(x: dict, fallback: str) -> str:
    return " ".join(str(x.get("label") or fallback).split())[:40] or fallback[:40]


def _icon(x: dict, fallback: str) -> str:
    ic = str(x.get("icon") or "")
    return ic if _ICON.match(ic) else fallback


def get(con, email: str, can_edit: bool) -> list[dict]:
    """Các nút của người này (chưa tự chọn: mặc định theo quyền)."""
    ensure(con)
    row = con.execute("SELECT items FROM quick_actions WHERE email = ?", (str(email).lower(),)).fetchone()
    if not row:
        return defaults(can_edit)
    try:
        return clean(json.loads(row[0]), can_edit)
    except ValueError:
        return defaults(can_edit)


def save(con, email: str, items: list, can_edit: bool) -> list[dict]:
    from datetime import datetime, timezone
    ensure(con)
    items = clean(items, can_edit)
    with con:
        con.execute("INSERT INTO quick_actions VALUES (?, ?, ?) ON CONFLICT(email) DO UPDATE SET items = excluded.items, "
                    "at = excluded.at", (str(email).lower(), json.dumps(items, ensure_ascii=False),
                                         datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return items


def reset(con, email: str) -> None:
    ensure(con)
    with con:
        con.execute("DELETE FROM quick_actions WHERE email = ?", (str(email).lower(),))
