"""Nhập file xuất từ Semrush (miễn phí, không gọi API): tự nhận loại file và tên miền, dùng cho website mình và đối thủ.

Loại file nhận được (theo dòng tiêu đề):
- backlinks  (Backlink Analytics → Backlinks → Export): mỗi link một dòng.
- refdomains (Backlink Analytics → Referring Domains → Export): mỗi website trỏ về một dòng, có IP, quốc gia.

Dùng ở đâu:
- Website mình · backlinks  → gộp vào "Tất cả backlink" (backlink_links.import_file), chạy audit.
- Website mình · refdomains → bổ sung IP / quốc gia cho link (phát hiện PBN, nguồn nước ngoài cả với link Semrush).
- Đối thủ · refdomains      → Backlink GAP: website trỏ về đối thủ mà chưa trỏ về mình.
- Đối thủ · backlinks       → Backlink GAP (website) + link cụ thể của đối thủ từ file (xem miễn phí).
Mỗi (tên miền, loại file) giữ KEEP lần nhập gần nhất để so lần trước / lần này.
"""
import csv
import io
import json
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

KINDS = {"backlinks": "Backlinks", "refdomains": "Referring domains"}
KEEP = 6
SCHEMA = """
CREATE TABLE IF NOT EXISTS semrush_imports (
    site TEXT NOT NULL,
    owner TEXT NOT NULL,           -- tên miền của file (website mình hoặc đối thủ)
    kind TEXT NOT NULL,            -- backlinks | refdomains
    imported_at TEXT NOT NULL,
    file_name TEXT,
    by_user TEXT,
    lost INTEGER NOT NULL DEFAULT 0,
    items TEXT NOT NULL,
    PRIMARY KEY (site, owner, kind, imported_at)
);
CREATE TABLE IF NOT EXISTS semrush_names (   -- tên đối thủ đặt cho tên miền khi nhập (để GAP hiện đúng tên)
    site TEXT NOT NULL,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (site, owner)
);
"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def host(u: str) -> str:
    u = (u or "").strip()
    h = urlparse(u if "://" in u else "https://" + u).netloc or u
    return h.lower().split(":")[0].removeprefix("www.")


def _int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def read_csv(data: bytes) -> tuple[list[str], list[dict]]:
    text = None
    for enc in ("utf-8-sig", "utf-16", "cp1258", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff((text or "")[:4000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    r = csv.DictReader(io.StringIO(text or ""), dialect=dialect)
    rows = list(r)
    return [h.strip() for h in (r.fieldnames or [])], rows


def detect(header: list[str]) -> str | None:
    cols = set(header)
    if {"Source url", "Target url"} <= cols:
        return "backlinks"
    if {"Domain", "Backlinks"} <= cols and ("Domain ascore" in cols or "IP Address" in cols):
        return "refdomains"
    return None


def guess_owner(file_name: str, kind: str, rows: list[dict]) -> str | None:
    """Tên miền của file: theo tên file Semrush ("matkinhshady.com-backlinks…"), không có thì theo trang đích."""
    m = re.match(r"^(?:www\.)?([a-z0-9.-]+\.[a-z]{2,})(?:-|_|\.csv)", (file_name or "").lower())
    if m:
        return m.group(1)
    if kind == "backlinks":
        from collections import Counter
        c = Counter(host(r.get("Target url")) for r in rows[:2000] if r.get("Target url"))
        if c:
            d = c.most_common(1)[0][0]
            parts = d.split(".")
            return ".".join(parts[-3:]) if parts[-2:] == ["com", "vn"] else ".".join(parts[-2:])
    return None


def parse_refdomains(rows: list[dict]) -> list[dict]:
    out = {}
    for r in rows:
        d = host(r.get("Domain"))
        if not d:
            continue
        out[d] = {"domain": d, "ascore": _int(r.get("Domain ascore")), "backlinks": _int(r.get("Backlinks")) or 0,
                  "ip": (r.get("IP Address") or "").strip(), "country": (r.get("Country") or "").strip().upper(),
                  "first": (r.get("First seen") or "").strip()[:10] or None,
                  "last": (r.get("Last seen") or "").strip()[:10] or None}
    return list(out.values())


def preview(data: bytes, file_name: str, site: str, rivals: list[dict]) -> dict:
    """Đọc thử: {"kind", "owner", "role" (own | rival | new), "rival" (tên đối thủ nếu có), "rows", "error"}."""
    header, rows = read_csv(data)
    kind = detect(header)
    if not kind:
        return {"error": "Chưa nhận ra định dạng: cần file Backlinks hoặc Referring Domains xuất từ Semrush"}
    owner = guess_owner(file_name, kind, rows)
    own = host(site)
    if owner and (owner == own or owner.endswith("." + own)):
        role, rv = "own", None
    else:
        rv = next((r for r in rivals if owner and (r["domain"] == owner or owner.endswith("." + r["domain"]))), None)
        role = "rival" if rv else "new"
    return {"kind": kind, "owner": owner, "role": role, "rival": (rv or {}).get("name"), "rows": len(rows),
            "error": None if owner else "Không đoán được tên miền của file: chọn ở cột Website"}


def save(con, site: str, owner: str, kind: str, data: bytes, file_name: str = "", user: str = "") -> dict:
    """Lưu một file. Website mình · backlinks đi qua backlink_links.import_file (gộp vào Tất cả backlink)."""
    from . import backlink_links as BLL
    ensure_tables(con)
    header, rows = read_csv(data)
    kind_ = detect(header)
    if kind_ != kind:
        raise ValueError("Loại file không khớp")
    own = host(site)
    res = None
    if kind == "backlinks" and (owner == own or owner.endswith("." + own)):
        owner = own
        res = {"kind": kind, "owner": owner, **BLL.import_file(con, site, data, file_name, user)}
        items, lost = BLL.parse_semrush(rows, site)  # giữ lịch sử để so lần nhập trước / lần này
    elif kind == "refdomains":
        items, lost = parse_refdomains(rows), 0
    else:  # backlinks của đối thủ: chỉ link trỏ về đối thủ
        items, lost = BLL.parse_semrush(rows, owner)
    now = _now()
    with con:
        con.execute("INSERT OR REPLACE INTO semrush_imports VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (site, owner, kind, now, file_name, user, lost, json.dumps(items, ensure_ascii=False)))
        old = [r[0] for r in con.execute("SELECT imported_at FROM semrush_imports WHERE site = ? AND owner = ? AND "
                                         "kind = ? ORDER BY imported_at DESC", (site, owner, kind)).fetchall()[KEEP:]]
        for at in old:
            con.execute("DELETE FROM semrush_imports WHERE site = ? AND owner = ? AND kind = ? AND imported_at = ?",
                        (site, owner, kind, at))
    return res or {"kind": kind, "owner": owner, "count": len(items), "lost": lost,
                   "domains": len({x.get("domain") or x.get("d_from") for x in items})}


def latest(con, site: str, owner: str, kind: str) -> dict | None:
    """Lần nhập mới nhất + lần trước: {"imported_at", "file_name", "items", "prev_items"}."""
    ensure_tables(con)
    rows = con.execute("SELECT imported_at, file_name, items FROM semrush_imports WHERE site = ? AND owner = ? AND "
                       "kind = ? ORDER BY imported_at DESC LIMIT 2", (site, owner, kind)).fetchall()
    if not rows:
        return None
    return {"imported_at": rows[0][0], "file_name": rows[0][1], "items": json.loads(rows[0][2]),
            "prev_items": json.loads(rows[1][2]) if len(rows) > 1 else None}


def owners(con, site: str) -> list[dict]:
    """Các lần nhập (mới nhất mỗi tên miền / loại): [{"owner", "kind", "imported_at", "count"}]."""
    ensure_tables(con)
    return [{"owner": o, "kind": k, "imported_at": at, "count": n}
            for o, k, at, n in con.execute(
                "SELECT owner, kind, MAX(imported_at), json_array_length(items) FROM semrush_imports WHERE site = ? "
                "GROUP BY owner, kind ORDER BY owner, kind", (site,))]


def remove(con, site: str, owner: str, kind: str | None = None) -> None:
    ensure_tables(con)
    with con:
        con.execute("DELETE FROM semrush_imports WHERE site = ? AND owner = ?" + (" AND kind = ?" if kind else ""),
                    (site, owner, *([kind] if kind else [])))


def own_domain_info(con, site: str) -> dict[str, dict]:
    """IP / quốc gia / ascore của website trỏ về mình (file Referring domains của website mình)."""
    d = latest(con, site, host(site), "refdomains")
    return {x["domain"]: x for x in (d or {}).get("items") or []}


def rival_data(con, site: str) -> dict[str, dict]:
    """Đối thủ đã nhập file: {tên miền: {"refdomains": [...] | None, "backlinks": [...] | None, "imported_at"}}."""
    own = host(site)
    out: dict[str, dict] = {}
    for o in owners(con, site):
        if o["owner"] == own:
            continue
        d = latest(con, site, o["owner"], o["kind"])
        g = out.setdefault(o["owner"], {"refdomains": None, "backlinks": None, "imported_at": ""})
        g[o["kind"]] = d["items"]
        g["imported_at"] = max(g["imported_at"], d["imported_at"])
    return out


def set_name(con, site: str, owner: str, name: str) -> None:
    ensure_tables(con)
    with con:
        con.execute("INSERT OR REPLACE INTO semrush_names VALUES (?, ?, ?)", (site, owner, name))


def names(con, site: str) -> dict[str, str]:
    ensure_tables(con)
    return dict(con.execute("SELECT owner, name FROM semrush_names WHERE site = ?", (site,)).fetchall())


def rival_links(con, site: str, dom: str) -> list[dict]:
    """Link cụ thể từ website `dom` trỏ về các đối thủ, lấy từ file Backlinks của đối thủ đã nhập (miễn phí), theo
    dạng của Backlink GAP › Link đã lấy."""
    nm = names(con, site)
    out = []
    for owner, g in rival_data(con, site).items():
        for x in g["backlinks"] or []:
            if x["d_from"] == dom or x["d_from"].endswith("." + dom):
                out.append({"rival": nm.get(owner, owner), "url_from": x["u_from"], "title": x.get("title") or "",
                            "url_to": x["u_to"], "anchor": x.get("anchor") or "", "first_seen": x.get("first"),
                            "page_rank": 0, "dofollow": x.get("follow", True), "attrs": x.get("attrs") or [],
                            "src": "semrush"})
    return out
