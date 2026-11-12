"""Nhãn website (Textlink, Báo PR, Web 2.0, PBN…) dùng chung mọi dự án, ở file dữ liệu chính.

- Một website có thể có nhiều nhãn. Gắn cho tên miền gốc (bỏ www); website con (m.abc.vn) nhận nhãn của tên miền cha
  khi chính nó chưa được gắn.
- Danh sách nhãn: có sẵn vài nhãn thường gặp, team thêm nhãn mới (kèm màu) ngay khi gắn.
- Dùng ở mọi bảng phần Backlink (GAP, Website trỏ về, Link đã xây) và trang Đối thủ.
"""
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

DEFAULTS = [("Textlink", "#B45309"), ("Báo PR", "#1D4ED8"), ("Web 2.0", "#7C3AED"), ("PBN", "#B91C1C"),
            ("Diễn đàn", "#0F766E"), ("Danh bạ", "#4B5563")]
PALETTE = ["#B45309", "#1D4ED8", "#7C3AED", "#B91C1C", "#0F766E", "#4B5563", "#1E7C31", "#BE185D", "#0369A1",
           "#A16207"]
MAX_NAME = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_label_defs (
    name TEXT PRIMARY KEY,
    color TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS site_labels (
    domain TEXT NOT NULL,
    label TEXT NOT NULL,
    by_user TEXT,
    at TEXT,
    PRIMARY KEY (domain, label)
);
"""
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM site_label_defs LIMIT 1").fetchone():
        with con:
            for i, (n, c) in enumerate(DEFAULTS):
                con.execute("INSERT OR IGNORE INTO site_label_defs (name, color, position) VALUES (?, ?, ?)",
                            (n, c, i))


def connect():
    """File dữ liệu chính (cùng file với tài khoản / credit)."""
    from . import points as PT
    if not PT._APP_DB["path"]:
        raise RuntimeError("chưa đặt file dữ liệu chính")
    con = sqlite3.connect(PT._APP_DB["path"], timeout=15)
    ensure(con)
    return closing(con)


def norm(domain: str) -> str:
    d = re.sub(r"^https?://", "", str(domain or "").strip().lower()).split("/")[0].split(":")[0]
    return d.removeprefix("www.")


def defs(con) -> list[dict]:
    ensure(con)
    return [{"name": n, "color": c} for n, c in con.execute(
        "SELECT name, color FROM site_label_defs ORDER BY position, name")]


def add_def(con, name: str, color: str = "", user: str = "") -> dict:
    """Thêm nhãn mới (tên đã có: trả nhãn đó, không lỗi)."""
    ensure(con)
    name = " ".join(str(name or "").split())[:MAX_NAME]
    if not name:
        raise ValueError("Tên nhãn trống")
    have = {d["name"].lower(): d for d in defs(con)}
    if name.lower() in have:
        return have[name.lower()]
    color = color if _COLOR.match(color or "") else PALETTE[len(have) % len(PALETTE)]
    pos = (con.execute("SELECT MAX(position) FROM site_label_defs").fetchone()[0] or 0) + 1
    with con:
        con.execute("INSERT INTO site_label_defs VALUES (?, ?, ?, ?, ?)",
                    (name, color, pos, user, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return {"name": name, "color": color}


def remove_def(con, name: str) -> None:
    """Xóa hẳn một nhãn (gỡ khỏi mọi website)."""
    ensure(con)
    with con:
        con.execute("DELETE FROM site_labels WHERE label = ?", (name,))
        con.execute("DELETE FROM site_label_defs WHERE name = ?", (name,))


def all_labels(con) -> dict[str, list[str]]:
    """{tên miền: [nhãn]} theo thứ tự nhãn."""
    ensure(con)
    order = {d["name"]: i for i, d in enumerate(defs(con))}
    out: dict[str, list[str]] = {}
    for d, label in con.execute("SELECT domain, label FROM site_labels"):
        out.setdefault(d, []).append(label)
    for v in out.values():
        v.sort(key=lambda n: order.get(n, 999))
    return out


def lookup(table: dict[str, list[str]], domain: str) -> list[str]:
    """Nhãn của một website: của chính nó, không có thì của tên miền cha gần nhất."""
    d = norm(domain)
    while d:
        if d in table:
            return table[d]
        if "." not in d:
            break
        d = d.split(".", 1)[1]
        if "." not in d:  # tới đuôi (vn, com): dừng
            break
    return []


def apply(con, domains: list[str], add: list[str] = (), remove: list[str] = (), user: str = "") -> int:
    """Gắn / gỡ nhãn cho các website. Trả số website đã đổi."""
    ensure(con)
    known = {d["name"] for d in defs(con)}
    doms = sorted({norm(d) for d in domains if norm(d)})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        for d in doms:
            for lab in add:
                if lab in known:
                    con.execute("INSERT OR IGNORE INTO site_labels VALUES (?, ?, ?, ?)", (d, lab, user, now))
            for lab in remove:
                con.execute("DELETE FROM site_labels WHERE domain = ? AND label = ?", (d, lab))
    return len(doms)


def by_rival(pairs: dict[str, dict[str, dict]], table: dict[str, list[str]]) -> dict[str, dict[str, list]]:
    """pairs {đối thủ: {website: {"backlinks"…}}} (Backlink GAP theo từng đối thủ) → {đối thủ: {nhãn: [số website,
    số link]}}; số link None khi dữ liệu cũ chưa tách được theo đối thủ. Website nhiều nhãn: tính ở mỗi nhãn."""
    out: dict[str, dict[str, list]] = {}
    for rv, items in pairs.items():
        for dom, it in items.items():
            for lab in lookup(table, dom):
                c = out.setdefault(rv, {}).setdefault(lab, [0, 0])
                c[0] += 1
                b = it.get("backlinks")
                c[1] = None if b is None or c[1] is None else c[1] + b
    return out
