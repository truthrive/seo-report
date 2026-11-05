"""Check rank thực tế qua DataForSEO cho các bộ từ khóa của dự án.

- Bộ từ khóa (tab ở màn Từ khóa & rank): tên tự đặt, loại Cam kết (làm nguồn cho dòng KPI) hoặc Theo dõi; mỗi bộ có
  nơi check riêng (vùng Google, thiết bị, vị trí, ngôn ngữ; để trống = theo dự án), lịch (ngày + giờ) và độ sâu riêng.
  Bộ mới ở dạng Nháp (không check, không tốn tiền) đến khi bấm Chốt. Mỗi dòng rank_keywords là một từ khóa trong một
  bộ; cùng từ khóa, cùng nơi check, cùng ngày ở bộ khác thì dùng lại kết quả (không trả tiền lần hai).
- Keyword đến từ: sheet cam kết, nhập tay, hoặc gắn ★ ở màn URL. URL mục tiêu và Top mục tiêu là tùy chọn.
- Lịch: các thứ trong tuần hoặc một ngày trong tháng, kèm giờ; hoặc chỉ khi bấm "Check ngay". Lỡ lịch (máy tắt)
  thì lần chạy sau check bù.
- Độ sâu: "auto" (lần đầu top 30; sau đó theo vị trí check lần trước: ≤ 8 → top 10, ≤ 18 → top 20, còn lại → top 30)
  hoặc cố định 10/20/30/50/100. Giá tính theo từng trang 10 kết quả. Không dùng position GSC: đó là số trung bình,
  không phải rank.
- Ngân sách tháng dùng chung: không cho thêm keyword nếu ước tính vượt 100%, cảnh báo ở 80%, không gửi task nếu tiền đã
  dùng trong tháng vượt ngân sách.
"""
import base64
import calendar
import json
import math
import re
import sqlite3
import time
import tomllib
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import urls as U
from .projects import domain
from .config import RankSettings

API = "https://api.dataforseo.com/v3/serp/google/organic"
ALERT_RATIO = 0.8
DEPTHS = ["auto", 10, 20, 30, 50, 100]
WEEKDAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
# Nơi check rank (đặt theo dự án ở màn Từ khóa & rank): như người dùng tìm trên Google ở vùng / thiết bị đó
SE_DOMAINS = {"google.com.vn": "google.com.vn (Việt Nam)", "google.com": "google.com (quốc tế)"}
DEVICES = {"mobile": "Điện thoại", "desktop": "Máy tính"}
LANGUAGES = {"vi": "Tiếng Việt", "en": "Tiếng Anh"}
_LOCATIONS: dict[int, str] = {}


def locations() -> dict[int, str]:
    """Vị trí tìm kiếm ở Việt Nam theo danh sách của DataForSEO: {mã: tên hiện}. Toàn quốc đứng đầu, rồi thành phố
    lớn, tỉnh, thành phố khác."""
    if not _LOCATIONS:
        rows = json.loads((Path(__file__).parent / "assets" / "rank_locations_vn.json").read_text(encoding="utf-8"))
        order = {"Country": 0, "Municipality": 1, "Province": 2, "City": 3}
        for r in sorted(rows, key=lambda r: (order[r["type"]], r["name"])):
            parts = r["name"].split(",")  # "Ho Chi Minh City,Ho Chi Minh,Vietnam" / "Dong Thap,Vietnam"
            if r["type"] == "Country":
                name = "Toàn quốc (Việt Nam)"
            elif r["type"] == "Municipality":  # thành phố trực thuộc TW: cả thành phố, hoặc nội thành
                name = f"{parts[0]} (toàn thành phố)" if len(parts) == 2 else f"{parts[0]} (nội thành)"
            elif r["type"] == "Province":
                name = f"Tỉnh {parts[0]}"
            else:
                name = f"{parts[0]}, {parts[-2]}" if parts[-2] != parts[0] else parts[0]
            _LOCATIONS[r["code"]] = name
    return _LOCATIONS


def describe_target(s) -> str:
    """'google.com.vn · Điện thoại · Ho Chi Minh City · Tiếng Việt'."""
    loc = locations().get(s.location_code, str(s.location_code))
    return (f"{s.se_domain} · {DEVICES.get(s.device, s.device)} · {loc} · "
            f"{LANGUAGES.get(s.language_code, s.language_code)}")


DEFAULT_SCHEDULE = {"type": "weekdays", "weekdays": [1], "day": 1, "depth": "auto", "time": "07:00"}  # thứ Ba 7:00,
# trước báo cáo thứ Năm
SET_STATES = {"draft": "Nháp", "active": "Đã chốt"}
SET_KINDS = {"kpi": "Cam kết", "custom": "Theo dõi"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS rank_sets (
    id INTEGER PRIMARY KEY,
    site TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,          -- 'kpi': bộ Cam kết (theo sheet); 'custom': team tự tạo
    settings TEXT,               -- JSON {se_domain, device, location_code, language_code}; NULL = theo dự án
    schedule TEXT NOT NULL,      -- JSON lịch + độ sâu
    position INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rank_keywords (
    id INTEGER PRIMARY KEY,
    site TEXT NOT NULL,
    keyword TEXT NOT NULL,
    url_id INTEGER,
    source TEXT NOT NULL,
    added_by TEXT NOT NULL,
    added_at TEXT NOT NULL,
    set_id INTEGER NOT NULL,
    top_target INTEGER,          -- Top mục tiêu (3, 5, 10…); bộ Cam kết lấy theo sheet
    paused INTEGER NOT NULL DEFAULT 0,  -- tạm dừng: không check, không tính tiền
    note TEXT,                   -- ghi chú của team ("đã viết lại bài 05/11")
    removed_at TEXT,             -- đã bỏ theo dõi (thùng rác, khôi phục được kèm lịch sử)
    removed_by TEXT,
    UNIQUE (set_id, keyword)
);
-- Mốc sự kiện trên biểu đồ tăng trưởng (Google update, đẩy backlink…); set_id NULL = mọi bộ của website
CREATE TABLE IF NOT EXISTS rank_events (
    id INTEGER PRIMARY KEY,
    site TEXT NOT NULL,
    set_id INTEGER,
    day TEXT NOT NULL,
    text TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rank_tasks (
    task_id TEXT PRIMARY KEY,
    keyword_id INTEGER NOT NULL,
    depth INTEGER NOT NULL,
    check_date TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    cost REAL NOT NULL,
    status TEXT NOT NULL
);
-- rank: vị trí tốt nhất của site; ranking_url: URL của site ở vị trí đó; target_rank: vị trí của URL mục tiêu.
CREATE TABLE IF NOT EXISTS rank_checks (
    keyword_id INTEGER NOT NULL,
    check_date TEXT NOT NULL,
    depth INTEGER NOT NULL,
    rank INTEGER,
    ranking_url TEXT,
    target_rank INTEGER,
    cost REAL NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (keyword_id, check_date)
);
-- Trang kết quả Google của mỗi lần check (đọc thêm từ kết quả đã trả tiền): AI Overview có không, site có được trích
-- không, các nguồn AI trích (JSON [{domain, url, title}]), 10 kết quả tự nhiên đầu (JSON [{rank, domain, url}]), các
-- loại ô đặc biệt (JSON [type]). aio NULL = lần check cũ chưa đọc phần này.
CREATE TABLE IF NOT EXISTS rank_serp (
    keyword_id INTEGER NOT NULL,
    check_date TEXT NOT NULL,
    aio INTEGER,
    aio_cited INTEGER,
    aio_refs TEXT,
    top10 TEXT,
    features TEXT,
    PRIMARY KEY (keyword_id, check_date)
);
-- Từ khóa dùng lại kết quả của một task đã gửi (cùng từ khóa, cùng nơi check, cùng ngày, ở bộ khác): không trả tiền
-- lần hai. status 'posted' → 'done' khi đã ghi kết quả cho từ khóa này.
CREATE TABLE IF NOT EXISTS rank_task_links (
    task_id TEXT NOT NULL,
    keyword_id INTEGER NOT NULL,
    check_date TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (task_id, keyword_id)
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def usd(value: float, digits: int = 2) -> str:
    """Số tiền kiểu Việt Nam: 0,02."""
    return f"{value:.{digits}f}".replace(".", ",")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_tables(con: sqlite3.Connection) -> None:
    _migrate_stars(con)
    con.executescript(SCHEMA)
    _migrate_sets(con)
    _add_columns(con)


def _add_columns(con: sqlite3.Connection) -> None:
    """Cột thêm sau: tạm dừng, ghi chú, thùng rác (từ khóa); tạm dừng (bộ)."""
    have = {c[1] for c in con.execute("PRAGMA table_info(rank_keywords)")}
    for col, typ in (("paused", "INTEGER NOT NULL DEFAULT 0"), ("note", "TEXT"), ("removed_at", "TEXT"),
                     ("removed_by", "TEXT")):
        if col not in have:
            con.execute(f"ALTER TABLE rank_keywords ADD COLUMN {col} {typ}")
    set_cols = {c[1] for c in con.execute("PRAGMA table_info(rank_sets)")}
    if "paused" not in set_cols:
        con.execute("ALTER TABLE rank_sets ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
    if "state" not in set_cols:  # bộ đã có trước đây coi như đã chốt
        con.execute("ALTER TABLE rank_sets ADD COLUMN state TEXT NOT NULL DEFAULT 'active'")
    serp_cols = {c[1] for c in con.execute("PRAGMA table_info(rank_serp)")}
    if "aio_text" not in serp_cols:  # nội dung chữ AI Overview
        con.execute("ALTER TABLE rank_serp ADD COLUMN aio_text TEXT")
    if "organic" not in serp_cols:  # mọi kết quả tự nhiên trong độ sâu đã check (top10 chỉ giữ 10 đầu)
        con.execute("ALTER TABLE rank_serp ADD COLUMN organic TEXT")
    con.commit()


def _committed_texts(con: sqlite3.Connection) -> dict[str, int | None] | None:
    """{từ khóa: Top target} của tab Từ khóa cam kết (phiên bản sheet mới nhất đã đồng bộ); chưa có sheet: None."""
    try:
        from . import kpi as KP
        ver = KP.version_at(KP.versions(con), date.today())
    except sqlite3.Error:
        return None
    return {k["keyword"].strip().lower(): k.get("target") for k in ver.get("keywords", [])} if ver else None


def _migrate_sets(con: sqlite3.Connection) -> None:
    """Bản trước: một danh sách từ khóa chung cho cả dự án, một lịch chung (app_settings 'rank_schedule'). Chuyển sang
    bộ: từ khóa có trong sheet cam kết → bộ "Cam kết", còn lại → bộ "Từ khóa chính". Giữ nguyên id nên lịch sử rank
    (rank_checks, rank_tasks) không đổi."""
    if "set_id" in [c[1] for c in con.execute("PRAGMA table_info(rank_keywords)")]:
        return
    row = con.execute("SELECT value FROM app_settings WHERE key = 'rank_schedule'").fetchone()
    sched = json.dumps({**DEFAULT_SCHEDULE, **(json.loads(row[0]) if row else {})})
    committed = _committed_texts(con)
    with con:
        con.execute("ALTER TABLE rank_keywords RENAME TO rank_keywords_old")
        con.executescript(SCHEMA)
        old = con.execute("SELECT id, site, keyword, url_id, source, added_by, added_at FROM rank_keywords_old "
                          "ORDER BY id").fetchall()
        sets_by_site: dict[tuple[str, str], int] = {}

        def set_for(site_: str, kind: str) -> int:
            if (site_, kind) not in sets_by_site:
                name = KPI_SET_NAME if kind == "kpi" else DEFAULT_SET_NAME
                cur = con.execute("INSERT INTO rank_sets (site, name, kind, settings, schedule, position, created_by, "
                                  "created_at) VALUES (?, ?, ?, NULL, ?, ?, 'tool', ?)",
                                  (site_, name, kind, sched, 0 if kind == "kpi" else 1, _now()))
                sets_by_site[(site_, kind)] = cur.lastrowid
            return sets_by_site[(site_, kind)]
        for kid, site_, kw, url_id, source, by, at in old:
            key = kw.strip().lower()
            kind = "kpi" if committed is not None and key in committed else "custom"
            con.execute("INSERT INTO rank_keywords (id, site, keyword, url_id, source, added_by, added_at, set_id, "
                        "top_target) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (kid, site_, kw, url_id, source, by, at, set_for(site_, kind),
                         committed.get(key) if kind == "kpi" else None))
        con.execute("DROP TABLE rank_keywords_old")


# ---- Bộ từ khóa ----

SET_SETTING_KEYS = ("se_domain", "device", "location_code", "language_code")
KPI_SET_NAME, DROPPED_SET_NAME, DEFAULT_SET_NAME = "Cam kết", "Ngoài cam kết", "Từ khóa chính"


_SET_COLS = "id, site, name, kind, settings, schedule, position, paused, state"


def _set_row(r) -> dict:
    sid, site, name, kind, settings, schedule, pos, paused, state = r
    return {"id": sid, "site": site, "name": name, "kind": kind,
            "settings": json.loads(settings) if settings else None,
            "schedule": {**DEFAULT_SCHEDULE, **json.loads(schedule)}, "position": pos, "paused": bool(paused),
            "state": state or "active", "draft": state == "draft"}


def sets(con: sqlite3.Connection, site: str) -> list[dict]:
    """Các bộ của website: bộ Cam kết trước, rồi theo thứ tự tạo. Kèm số từ khóa ("count")."""
    ensure_tables(con)
    rows = con.execute(f"SELECT {_SET_COLS} FROM rank_sets WHERE site = ? ORDER BY kind != 'kpi', position, id",
                       (site,)).fetchall()
    counts = dict(con.execute("SELECT set_id, COUNT(*) FROM rank_keywords WHERE site = ? AND removed_at IS NULL "
                              "GROUP BY set_id", (site,)))
    return [{**_set_row(r), "count": counts.get(r[0], 0)} for r in rows]


def get_set(con: sqlite3.Connection, set_id: int) -> dict | None:
    ensure_tables(con)
    r = con.execute(f"SELECT {_SET_COLS} FROM rank_sets WHERE id = ?", (set_id,)).fetchone()
    return _set_row(r) if r else None


def _clean_settings(settings: dict | None) -> str | None:
    if not settings:
        return None
    out = {}
    for k in SET_SETTING_KEYS:
        v = settings.get(k)
        if v in (None, ""):
            continue
        if k == "location_code":
            v = int(v)
            if v not in locations():
                raise ValueError("Vị trí tìm kiếm không hợp lệ")
        elif v not in {"se_domain": SE_DOMAINS, "device": DEVICES, "language_code": LANGUAGES}[k]:
            raise ValueError("Cài đặt check rank không hợp lệ")
        out[k] = v
    return json.dumps(out) if out else None


def _clean_schedule(schedule: dict) -> str:
    out = {**DEFAULT_SCHEDULE, **schedule}
    try:
        h, m = (int(x) for x in str(out.get("time") or "07:00").split(":")[:2])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except ValueError:
        raise ValueError("Giờ check không hợp lệ (dạng 07:00)") from None
    out["time"] = f"{h:02d}:{m:02d}"
    return json.dumps(out)


def create_set(con: sqlite3.Connection, site: str, name: str, user: str, kind: str = "custom",
               settings: dict | None = None, schedule: dict | None = None, state: str = "active") -> int:
    """Bộ mới. Team tạo trên màn rank thì state="draft" (Nháp: chưa check, chưa tốn tiền đến khi Chốt); bộ tool tự
    tạo (đồng bộ sheet, ★ ở màn URL) chạy ngay."""
    ensure_tables(con)
    if kind not in SET_KINDS or state not in SET_STATES:
        raise ValueError("Loại / trạng thái bộ không hợp lệ")
    name = " ".join((name or "").split())[:60]
    if not name:
        raise ValueError("Chưa nhập tên bộ từ khóa")
    if con.execute("SELECT 1 FROM rank_sets WHERE site = ? AND lower(name) = lower(?)", (site, name)).fetchone():
        raise ValueError(f"Đã có bộ tên “{name}”")
    pos = con.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM rank_sets WHERE site = ?", (site,)).fetchone()[0]
    with con:
        cur = con.execute("INSERT INTO rank_sets (site, name, kind, settings, schedule, position, created_by, "
                          "created_at, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (site, name, kind, _clean_settings(settings), _clean_schedule(schedule or {}), pos, user,
                           _now(), state))
        U.log_change(con, user, site, "Tạo bộ từ khóa", None, name)
    return cur.lastrowid


def update_set(con: sqlite3.Connection, set_id: int, user: str, name: str | None = None,
               settings: dict | None | bool = False, schedule: dict | None = None,
               paused: bool | None = None, kind: str | None = None) -> None:
    """Đổi tên, loại (Cam kết / Theo dõi), nơi check (settings=None: theo dự án; False: không đổi), lịch, tạm dừng cả
    bộ (không check, không tính tiền; lịch sử vẫn giữ)."""
    st = get_set(con, set_id)
    if not st:
        raise ValueError("Không có bộ từ khóa này")
    if kind is not None and kind not in SET_KINDS:
        raise ValueError("Loại bộ không hợp lệ")
    with con:
        if kind is not None and kind != st["kind"]:
            con.execute("UPDATE rank_sets SET kind = ? WHERE id = ?", (kind, set_id))
        if name is not None:
            name = " ".join(name.split())[:60]
            if not name:
                raise ValueError("Chưa nhập tên bộ từ khóa")
            if con.execute("SELECT 1 FROM rank_sets WHERE site = ? AND lower(name) = lower(?) AND id != ?",
                           (st["site"], name, set_id)).fetchone():
                raise ValueError(f"Đã có bộ tên “{name}”")
            con.execute("UPDATE rank_sets SET name = ? WHERE id = ?", (name, set_id))
        if settings is not False:
            con.execute("UPDATE rank_sets SET settings = ? WHERE id = ?", (_clean_settings(settings), set_id))
        if schedule is not None:
            con.execute("UPDATE rank_sets SET schedule = ? WHERE id = ?", (_clean_schedule(schedule), set_id))
        if paused is not None and bool(paused) != st["paused"]:
            con.execute("UPDATE rank_sets SET paused = ? WHERE id = ?", (int(bool(paused)), set_id))
            U.log_change(con, user, st["site"], "Tạm dừng bộ từ khóa" if paused else "Chạy lại bộ từ khóa", None,
                         st["name"])
        U.log_change(con, user, st["site"], "Sửa bộ từ khóa", None, name or st["name"])


def lock_set(con: sqlite3.Connection, set_id: int, user: str) -> None:
    """Chốt bộ Nháp: từ đây bộ chạy theo lịch (tốn tiền check)."""
    st = get_set(con, set_id)
    if not st:
        raise ValueError("Không có bộ từ khóa này")
    if not st["draft"]:
        return
    with con:
        con.execute("UPDATE rank_sets SET state = 'active' WHERE id = ?", (set_id,))
        U.log_change(con, user, st["site"], "Chốt bộ từ khóa", None, st["name"])


def delete_set(con: sqlite3.Connection, set_id: int, user: str) -> dict:
    """Xóa vĩnh viễn một bộ: từ khóa, mọi lần check, kết quả Google, mốc sự kiện riêng của bộ. Không khôi phục được.
    Tiền đã trả vẫn tính vào chi phí tháng. Trả số liệu đã xóa (purge_stats)."""
    st = get_set(con, set_id)
    if not st:
        raise ValueError("Không có bộ từ khóa này")
    ids = [r[0] for r in con.execute("SELECT id FROM rank_keywords WHERE set_id = ?", (set_id,))]
    stats = purge_stats(con, ids)
    _purge(con, ids)
    with con:
        con.execute("DELETE FROM rank_events WHERE set_id = ?", (set_id,))
        con.execute("DELETE FROM rank_sets WHERE id = ?", (set_id,))
        U.log_change(con, user, st["site"], "Xóa vĩnh viễn bộ từ khóa", None,
                     f"{st['name']}: {len(ids)} từ khóa, {stats['checks']} lần check")
    return stats


def purge_stats(con: sqlite3.Connection, ids: list[int]) -> dict:
    """Những gì sẽ mất khi xóa vĩnh viễn các từ khóa: số lần check, tiền đã trả cho các lần check đó."""
    if not ids:
        return {"keywords": 0, "checks": 0, "cost": 0.0}
    marks = ",".join("?" * len(ids))
    checks = con.execute(f"SELECT COUNT(*) FROM rank_checks WHERE keyword_id IN ({marks})", ids).fetchone()[0]
    cost = con.execute(f"SELECT COALESCE(SUM(cost), 0) FROM rank_tasks WHERE keyword_id IN ({marks})",
                       ids).fetchone()[0]
    return {"keywords": len(ids), "checks": checks, "cost": cost}


def _purge(con: sqlite3.Connection, ids: list[int]) -> None:
    """Xóa hẳn dữ liệu của các từ khóa. Dòng rank_tasks giữ lại (keyword_id = 0) để chi phí tháng vẫn đúng; task đang
    chờ mà có từ khóa khác dùng chung thì giao cho từ khóa đó nhận kết quả."""
    from . import volume
    volume.ensure_tables(con)
    with con:
        for kid in ids:
            for task_id, status in con.execute("SELECT task_id, status FROM rank_tasks WHERE keyword_id = ?",
                                               (kid,)).fetchall():
                heir = con.execute("SELECT keyword_id FROM rank_task_links WHERE task_id = ? AND status = 'posted' "
                                   "AND keyword_id != ? ORDER BY posted_at LIMIT 1", (task_id, kid)).fetchone()
                if status == "posted" and heir:
                    con.execute("UPDATE rank_tasks SET keyword_id = ? WHERE task_id = ?", (heir[0], task_id))
                    con.execute("DELETE FROM rank_task_links WHERE task_id = ? AND keyword_id = ?", (task_id, heir[0]))
                else:
                    con.execute("UPDATE rank_tasks SET keyword_id = 0, status = CASE status WHEN 'posted' THEN "
                                "'deleted' ELSE status END WHERE task_id = ?", (task_id,))
            for table in ("rank_task_links", "rank_checks", "rank_serp", "keyword_volume"):
                con.execute(f"DELETE FROM {table} WHERE keyword_id = ?", (kid,))
            con.execute("DELETE FROM rank_keywords WHERE id = ?", (kid,))


def purge_keywords(con: sqlite3.Connection, site: str, ids: list[int], user: str) -> dict:
    """Xóa vĩnh viễn từ khóa (cả lịch sử rank). Không khôi phục được. Trả số liệu đã xóa."""
    rows = con.execute(f"SELECT id, keyword FROM rank_keywords WHERE site = ? AND id IN ({','.join('?' * len(ids))})",
                       (site, *ids)).fetchall() if ids else []
    stats = purge_stats(con, [r[0] for r in rows])
    _purge(con, [r[0] for r in rows])
    with con:
        for _, kw in rows:
            U.log_change(con, user, site, "Xóa vĩnh viễn keyword", None, kw)
    return stats


def kpi_set(con: sqlite3.Connection, site: str, create: bool = False, user: str = "tool") -> dict | None:
    st = next((x for x in sets(con, site) if x["kind"] == "kpi"), None)
    if st is None and create:
        st = get_set(con, create_set(con, site, KPI_SET_NAME, user, kind="kpi", schedule=get_schedule(con)))
    return st


def named_set(con: sqlite3.Connection, site: str, name: str, user: str = "tool", like: dict | None = None) -> dict:
    """Bộ team tạo theo tên; chưa có thì tạo (cùng nơi check / lịch với bộ `like` nếu có)."""
    st = next((x for x in sets(con, site) if x["kind"] != "kpi" and x["name"].lower() == name.lower()), None)
    if st is None:
        st = get_set(con, create_set(con, site, name, user, settings=(like or {}).get("settings"),
                                     schedule=(like or {}).get("schedule") or get_schedule(con)))
    return st


def default_set(con: sqlite3.Connection, site: str, user: str = "tool") -> dict:
    """Bộ nhận từ khóa thêm từ màn URL (★): bộ team tạo đầu tiên, chưa có thì tạo "Từ khóa chính"."""
    st = next((x for x in sets(con, site) if x["kind"] != "kpi"), None)
    return st or named_set(con, site, DEFAULT_SET_NAME, user, like=kpi_set(con, site))


def settings_for(base: RankSettings, st: dict | None) -> RankSettings:
    """Nơi check của một bộ: cài đặt riêng của bộ, phần trống lấy theo dự án."""
    from dataclasses import replace
    return replace(base, **((st or {}).get("settings") or {}))


def _migrate_stars(con: sqlite3.Connection) -> None:
    """Bản trước lưu ★ theo (URL, query) trong rank_stars; chuyển sang rank_keywords. Chưa có lần check nào nên bỏ
    rank_tasks/rank_checks kiểu cũ."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'rank_stars'").fetchone():
        return
    old_checks = [c[1] for c in con.execute("PRAGMA table_info(rank_checks)")]
    with con:
        if "url_id" in old_checks:
            con.execute("DROP TABLE rank_checks")
            con.execute("DROP TABLE IF EXISTS rank_tasks")
        con.executescript(SCHEMA)
        for site_, in con.execute("SELECT DISTINCT u.site FROM rank_stars s JOIN urls u ON u.id = s.url_id").fetchall():
            sid = con.execute("INSERT INTO rank_sets (site, name, kind, settings, schedule, position, created_by, "
                              "created_at) VALUES (?, ?, 'custom', NULL, ?, 1, 'tool', ?)",
                              (site_, DEFAULT_SET_NAME, json.dumps(DEFAULT_SCHEDULE), _now())).lastrowid
            con.execute("""INSERT OR IGNORE INTO rank_keywords (site, keyword, url_id, source, added_by, added_at,
                           set_id) SELECT u.site, s.query, s.url_id, 'gsc', s.starred_by, s.starred_at, ?
                           FROM rank_stars s JOIN urls u ON u.id = s.url_id WHERE u.site = ?""", (sid, site_))
        con.execute("DROP TABLE rank_stars")


# ---- Lịch và độ sâu ----

def get_schedule(con: sqlite3.Connection, set_id: int | None = None) -> dict:
    """Lịch của một bộ; không chỉ bộ thì lịch mặc định cho bộ mới (lịch chung trước khi có bộ)."""
    ensure_tables(con)
    if set_id is not None:
        st = get_set(con, set_id)
        if st:
            return st["schedule"]
    row = con.execute("SELECT value FROM app_settings WHERE key = 'rank_schedule'").fetchone()
    return {**DEFAULT_SCHEDULE, **(json.loads(row[0]) if row else {})}


def set_schedule(con: sqlite3.Connection, site: str, schedule: dict, user: str, set_id: int | None = None) -> None:
    ensure_tables(con)
    if set_id is not None:
        update_set(con, set_id, user, schedule=schedule)
        return
    with con:
        con.execute("INSERT OR REPLACE INTO app_settings VALUES ('rank_schedule', ?)", (json.dumps(schedule),))
        U.log_change(con, user, site, "Đổi lịch check rank", None, describe_schedule(schedule))


def describe_schedule(s: dict) -> str:
    depth = "độ sâu tự động" if s["depth"] == "auto" else f"top {s['depth']}"
    at = f" lúc {s.get('time') or DEFAULT_SCHEDULE['time']}"
    if s["type"] == "weekdays":
        days = ", ".join(WEEKDAYS[d] for d in sorted(s["weekdays"])) or "chưa chọn thứ nào"
        return f"Hằng tuần vào {days}{at}; {depth}"
    if s["type"] == "monthly":
        return f"Hằng tháng vào ngày {s['day']}{at}; {depth}"
    return f"Chỉ khi bấm Check ngay; {depth}"


def describe_sets(con: sqlite3.Connection, site: str) -> str:
    """Lịch của mọi bộ, một dòng: "Cam kết: Hằng tuần vào Thứ 3; top 20 · Blog: Hằng tháng vào ngày 1; …"."""
    rows = sets(con, site)
    if not rows:
        return describe_schedule(get_schedule(con))
    return " · ".join(f"{x['name']}: {describe_schedule(x['schedule'])}" for x in rows)


def checks_per_month(s: dict) -> float:
    if s["type"] == "weekdays":
        return len(set(s["weekdays"])) * 30 / 7
    return 1.0 if s["type"] == "monthly" else 0.0


def last_scheduled_day(s: dict, today: date) -> date | None:
    """Ngày theo lịch gần nhất ≤ hôm nay; None nếu lịch chỉ chạy tay hoặc chưa chọn thứ."""
    if s["type"] == "weekdays":
        for back in range(7):
            d = today - timedelta(days=back)
            if d.weekday() in s["weekdays"]:
                return d
        return None
    if s["type"] == "monthly":
        y, m = today.year, today.month
        if today.day < min(s["day"], calendar.monthrange(y, m)[1]):
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        return date(y, m, min(s["day"], calendar.monthrange(y, m)[1]))
    return None


def schedule_time(s: dict) -> dtime:
    try:
        h, m = (int(x) for x in str(s.get("time") or DEFAULT_SCHEDULE["time"]).split(":")[:2])
        return dtime(h, m)
    except (ValueError, TypeError):
        return dtime(7, 0)


def last_scheduled_at(s: dict, now: datetime) -> datetime | None:
    """Lúc theo lịch gần nhất ≤ bây giờ (ngày + giờ check của bộ); None nếu chỉ chạy tay."""
    t = schedule_time(s)
    day = last_scheduled_day(s, now.date())
    if day == now.date() and now.time() < t:  # hôm nay có lịch nhưng chưa tới giờ: lấy lần trước
        day = last_scheduled_day(s, now.date() - timedelta(days=1))
    return datetime.combine(day, t) if day else None


def next_scheduled_day(s: dict, today: date) -> date | None:
    """Ngày theo lịch kế tiếp sau hôm nay; None nếu lịch chỉ chạy tay."""
    for ahead in range(1, 63):
        d = today + timedelta(days=ahead)
        if last_scheduled_day(s, d) == d:
            return d
    return None


def _auto_depth(position: float | None) -> int:
    if position is None:
        return 30
    if position <= 8:
        return 10
    if position <= 18:
        return 20
    return 30


def depth_for(setting, last_rank: int | None, last_depth: int | None) -> int:
    """Chỉ dựa vào kết quả check thật lần trước, không dùng position GSC (là số trung bình, không phải rank)."""
    if setting != "auto":
        return int(setting)
    return _auto_depth(last_rank)  # lần đầu, hoặc lần trước không thấy trong độ sâu → top 30


# ---- Danh sách keyword ----

def keywords(con: sqlite3.Connection, site: str, end: date, set_id: int | None = None,
             removed: bool = False) -> list[dict]:
    """Từ khóa theo dõi (mọi bộ, hoặc một bộ) kèm bộ, lần check gần nhất, lần trước, vị trí tốt nhất, độ sâu dự kiến,
    tạm dừng (của từ khóa hoặc cả bộ), ghi chú. Một từ khóa ở hai bộ là hai dòng (mỗi bộ check riêng).
    removed: chỉ lấy từ khóa trong thùng rác (đã bỏ theo dõi)."""
    ensure_tables(con)
    by_set = {x["id"]: x for x in sets(con, site)}
    rows = con.execute(
        f"""SELECT k.id, k.keyword, k.url_id, u.url, k.source, k.added_by, k.added_at, k.set_id, k.top_target,
                  k.paused, k.note, k.removed_at, k.removed_by
           FROM rank_keywords k LEFT JOIN urls u ON u.id = k.url_id
           WHERE k.site = ? AND (? IS NULL OR k.set_id = ?) AND k.removed_at IS {"NOT " if removed else ""}NULL
           ORDER BY k.id""",
        (site, set_id, set_id)).fetchall()
    out = []
    for kid, kw, url_id, url, source, by, at, sid, top, kpaused, note, rm_at, rm_by in rows:
        st = by_set.get(sid) or {"id": sid, "name": "", "kind": "custom", "settings": None,
                                 "schedule": DEFAULT_SCHEDULE}
        sched = st["schedule"]
        checks = con.execute(
            "SELECT check_date, rank, ranking_url, target_rank, depth, checked_at FROM rank_checks WHERE keyword_id = ? "
            "ORDER BY check_date DESC LIMIT 2", (kid,)).fetchall()
        best = con.execute("SELECT MIN(rank) FROM rank_checks WHERE keyword_id = ?", (kid,)).fetchone()[0]
        last = checks[0] if checks else None
        prev = checks[1] if len(checks) > 1 else None
        out.append({
            "id": kid, "keyword": kw, "url_id": url_id, "target_url": url, "source": source, "added_by": by,
            "added_at": at, "best": best, "set_id": sid, "set_name": st["name"], "set_kind": st["kind"],
            "set": st, "top_target": top, "own_paused": bool(kpaused),
            "paused": bool(kpaused) or bool(st.get("paused")), "draft": bool(st.get("draft")),
            "note": note or "", "removed_at": rm_at,
            "removed_by": rm_by,
            "date": last[0] if last else None, "rank": last[1] if last else None,
            "ranking_url": last[2] if last else None, "target_rank": last[3] if last else None,
            "last_depth": last[4] if last else None, "checked_at": last[5] if last else None,
            "prev": prev[1] if prev else None, "prev_date": prev[0] if prev else None,
            "prev_depth": prev[4] if prev else None,
            "depth": depth_for(sched["depth"], last[1] if last else None, last[4] if last else None),
        })
    return out


def primary_keywords(con: sqlite3.Connection, site: str, end: date) -> list[dict]:
    """Mỗi từ khóa một dòng (báo cáo, Tổng quan, KPI, màn URL): ưu tiên dòng ở bộ Cam kết, rồi bộ tạo trước."""
    seen, out = set(), []
    order = {x["id"]: i for i, x in enumerate(sets(con, site))}
    for k in sorted(keywords(con, site, end), key=lambda k: (order.get(k["set_id"], 99), k["id"])):
        key = k["keyword"].strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(k)
    return sorted(out, key=lambda k: k["id"])


def history(con: sqlite3.Connection, keyword_id: int) -> list[tuple[str, int | None, int]]:
    ensure_tables(con)
    return con.execute("SELECT check_date, rank, depth FROM rank_checks WHERE keyword_id = ? ORDER BY check_date",
                       (keyword_id,)).fetchall()


def _pages(depth: int) -> int:
    return math.ceil(depth / 10)


def spent_this_month(con: sqlite3.Connection, today: date | None = None) -> float:
    ensure_tables(con)
    today = today or date.today()
    month = today.strftime("%Y-%m")
    from . import backlinks, intent, volume  # volume, backlink, ý định từ khóa: chung ngân sách DataForSEO
    return (con.execute("SELECT COALESCE(SUM(cost), 0) FROM rank_tasks WHERE substr(check_date, 1, 7) = ?",
                        (month,)).fetchone()[0] + volume.spent_this_month(con, today)
            + backlinks.spent_this_month(con, today) + intent.spent_this_month(con, today))


def cost_by_month(con: sqlite3.Connection, months: list[str]) -> dict[str, dict]:
    """Chi phí DataForSEO theo tháng ("YYYY-MM"): {"rank", "volume", "backlinks", "checks" (số lượt check rank),
    "total"}."""
    ensure_tables(con)
    from . import backlinks, intent, volume
    volume.ensure_tables(con)
    backlinks.ensure_tables(con)
    intent.ensure_tables(con)
    out = {m: {"rank": 0.0, "volume": 0.0, "backlinks": 0.0, "intent": 0.0, "checks": 0, "total": 0.0}
           for m in months}
    for m, cost, n in con.execute("SELECT substr(check_date, 1, 7), SUM(cost), COUNT(*) FROM rank_tasks "
                                  "GROUP BY 1"):
        if m in out:
            out[m].update(rank=cost or 0.0, checks=n)
    for m, cost in con.execute("SELECT substr(run_at, 1, 7), SUM(cost) FROM volume_runs GROUP BY 1"):
        if m in out:
            out[m]["volume"] = cost or 0.0
    for m, cost in con.execute("SELECT substr(run_at, 1, 7), SUM(cost) FROM backlink_runs GROUP BY 1"):
        if m in out:
            out[m]["backlinks"] = cost or 0.0
    for m, cost in con.execute("SELECT substr(run_at, 1, 7), SUM(cost) FROM intent_runs GROUP BY 1"):
        if m in out:
            out[m]["intent"] = cost or 0.0
    for v in out.values():
        v["total"] = v["rank"] + v["volume"] + v["backlinks"] + v["intent"]
    return out


def last_months(today: date, n: int = 6) -> list[str]:
    """n tháng gần nhất, cũ trước mới sau, dạng "YYYY-MM"."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def estimate(con: sqlite3.Connection, s: RankSettings, schedule: dict, depths: list[int]) -> float:
    return sum(_pages(d) for d in depths) * s.price_per_page * checks_per_month(schedule)


def estimate_all(con: sqlite3.Connection, site: str, s: RankSettings, end: date,
                 extra: dict[int, list[int]] | None = None) -> float:
    """Tiền dự kiến mỗi tháng của mọi bộ (mỗi bộ theo lịch của nó); extra: {bộ: [độ sâu của từ khóa sắp thêm]}."""
    depths: dict[int, list[int]] = {}
    for k in keywords(con, site, end):
        if not k["paused"]:  # tạm dừng: không check, không tính tiền
            depths.setdefault(k["set_id"], []).append(k["depth"])
    for sid, ds in (extra or {}).items():
        depths.setdefault(sid, []).extend(ds)
    return sum(estimate(con, s, get_schedule(con, sid), ds) for sid, ds in depths.items())


def budget_status(con: sqlite3.Connection, site: str, s: RankSettings, end: date, today: date | None = None) -> dict:
    kws = keywords(con, site, end)
    est = estimate_all(con, site, s, end)
    return {"stars": len(kws), "estimate": est, "spent": spent_this_month(con, today),
            "budget": s.monthly_budget_usd, "ratio": est / s.monthly_budget_usd if s.monthly_budget_usd else 0}


def parse_lines(text: str) -> list[tuple[str, str | None]]:
    """Mỗi dòng: keyword, hoặc keyword + URL mục tiêu (cách nhau bởi Tab khi dán từ Excel, hoặc dấu |)."""
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in re.split(r"\t|\|", line) if p.strip()]
        if not parts:
            continue
        kw = " ".join(parts[0].split()).lower()
        url = parts[1] if len(parts) > 1 else None
        if url is None and re.search(r"\s(https?://\S+|\S+\.\w{2,}/\S*)$", parts[0]):  # "keyword https://…"
            kw, url = parts[0].rsplit(None, 1)
            kw = " ".join(kw.split()).lower()
        out.append((kw, url))
    return out


def _target_url_id(con, site: str, raw_url: str | None):
    """(url_id, lỗi): URL mục tiêu phải thuộc website."""
    if not raw_url:
        return None, None
    url = U.normalize(raw_url)
    if domain(url) != domain(site):
        return None, "bad"
    return U._match_existing(con, site, url) or U._get_or_create_url(con, site, url), None


def add_keywords(con: sqlite3.Connection, site: str, s: RankSettings, end: date, items: list[tuple],
                 user: str, source: str = "manual", set_id: int | None = None) -> dict:
    """Thêm keyword vào một bộ (mặc định: bộ team tạo đầu tiên). items: (keyword, URL mục tiêu) hoặc (keyword, URL,
    Top mục tiêu). Keyword đã có trong bộ: cập nhật URL / Top nếu có. Từ chối phần vượt ngân sách."""
    ensure_tables(con)
    st = get_set(con, set_id) if set_id is not None else default_set(con, site, user)
    if not st:
        raise ValueError("Không có bộ từ khóa này")
    sched = st["schedule"]
    current = keywords(con, site, end, st["id"])
    existing = {k["keyword"].strip().lower(): k for k in current}
    total = estimate_all(con, site, s, end)
    per_kw = estimate(con, s, sched, [depth_for(sched["depth"], None, None)])
    res = {"added": [], "updated": [], "exists": [], "over_budget": [], "bad_url": []}
    free = st["draft"] or bool(getattr(s, "paused", False))
    with con:
        for item in items:
            kw, raw_url, top = (list(item) + [None, None])[:3]
            kw = " ".join(str(kw).split())
            url_id, err = _target_url_id(con, site, raw_url)
            if err:
                res["bad_url"].append(f"{kw} | {raw_url}")
                continue
            old = existing.get(kw.lower())
            if old:
                changes = []
                if url_id and old["url_id"] != url_id:
                    con.execute("UPDATE rank_keywords SET url_id = ? WHERE id = ?", (url_id, old["id"]))
                    U.log_change(con, user, site, "Đổi URL mục tiêu", raw_url, kw)
                    changes.append("url")
                if top and old.get("top_target") != top:
                    con.execute("UPDATE rank_keywords SET top_target = ? WHERE id = ?", (top, old["id"]))
                    changes.append("top")
                res["updated" if changes else "exists"].append(kw)
                continue
            # Bộ Nháp hoặc dự án đang tạm ngưng check: chưa tốn tiền nên không chặn (chặn lúc Chốt bộ / lúc check)
            if not free and total + per_kw > s.monthly_budget_usd:
                res["over_budget"].append(kw)
                continue
            gone = con.execute("SELECT id, url_id, top_target FROM rank_keywords WHERE set_id = ? AND "
                               "lower(keyword) = lower(?) AND removed_at IS NOT NULL", (st["id"], kw)).fetchone()
            if gone:  # đã bỏ theo dõi trước đây: lấy lại cùng lịch sử
                con.execute("UPDATE rank_keywords SET removed_at = NULL, removed_by = NULL, url_id = ?, "
                            "top_target = ? WHERE id = ?", (url_id or gone[1], top or gone[2], gone[0]))
            else:
                con.execute("INSERT INTO rank_keywords (site, keyword, url_id, source, added_by, added_at, set_id, "
                            "top_target) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (site, kw, url_id, source, user, _now(), st["id"], top))
            U.log_change(con, user, site, f"Thêm keyword check rank ({st['name']})", raw_url, kw)
            total += per_kw
            existing[kw.lower()] = {"id": None, "url_id": url_id, "top_target": top}
            res["added"].append(kw)
    res["estimate"] = total
    return res


def estimate_add(con: sqlite3.Connection, site: str, s: RankSettings, end: date, keywords_in: list[str],
                 set_id: int | None = None) -> dict:
    """Ước tính chi phí trước khi thêm keyword vào một bộ: số keyword mới (bỏ trùng và keyword đã có trong bộ), tiền
    mỗi lần check thêm, tiền thêm mỗi tháng theo lịch của bộ, tổng dự kiến cả tháng (mọi bộ) so với ngân sách.
    Keyword mới check lần đầu ở độ sâu của lịch (tự động: top 30)."""
    ensure_tables(con)
    st = get_set(con, set_id) if set_id is not None else default_set(con, site)
    sched = st["schedule"]
    have = {k["keyword"].strip().lower() for k in keywords(con, site, end, st["id"])}
    new = list(dict.fromkeys(" ".join(k.split()).lower() for k in keywords_in if k.strip()))
    fresh = [k for k in new if k not in have]
    d = depth_for(sched["depth"], None, None)
    before = estimate_all(con, site, s, end)
    after = estimate_all(con, site, s, end, {st["id"]: [d] * len(fresh)})
    return {"new": len(fresh), "existing": len(new) - len(fresh), "depth": d,
            "per_check": _pages(d) * len(fresh) * s.price_per_page, "checks_per_month": checks_per_month(sched),
            "monthly_add": after - before, "monthly_total": after, "budget": s.monthly_budget_usd,
            "ratio": after / s.monthly_budget_usd if s.monthly_budget_usd else 0.0, "schedule": sched}


def set_top_target(con: sqlite3.Connection, site: str, keyword_id: int, top: int | None, user: str) -> None:
    """Top mục tiêu của một từ khóa (bộ team tạo; bộ Cam kết sửa qua sheet: kpi.sheet_keyword_op)."""
    row = con.execute("SELECT keyword FROM rank_keywords WHERE id = ? AND site = ?", (keyword_id, site)).fetchone()
    if not row:
        raise ValueError("Không có từ khóa này")
    if top is not None and not 1 <= int(top) <= 100:
        raise ValueError("Top mục tiêu từ 1 đến 100")
    with con:
        con.execute("UPDATE rank_keywords SET top_target = ? WHERE id = ?", (top, keyword_id))
        U.log_change(con, user, site, "Đổi Top mục tiêu", None, f"{row[0]}: {f'Top {top}' if top else 'bỏ'}")


def sync_kpi_set(con: sqlite3.Connection, site: str, s: RankSettings, end: date, sheet_keywords: list[dict],
                 user: str = "tool") -> dict:
    """Bộ Cam kết khớp tab Từ khóa cam kết: thêm từ khóa mới (kèm URL, Top), cập nhật URL / Top theo sheet; từ khóa
    đã bỏ khỏi sheet chuyển sang bộ "Ngoài cam kết" (vẫn check, giữ lịch sử), hoặc thôi theo dõi nếu đã có ở bộ khác."""
    st = kpi_set(con, site, create=bool(sheet_keywords), user=user)
    if not st:
        return {"added": [], "updated": [], "exists": [], "over_budget": [], "bad_url": [], "moved": []}
    res = add_keywords(con, site, s, end, [(k["keyword"], k.get("url") or None, k.get("target"))
                                           for k in sheet_keywords], user, source="kpi", set_id=st["id"])
    want = {k["keyword"].strip().lower(): k for k in sheet_keywords}
    res["moved"] = []
    with con:
        for k in keywords(con, site, end, st["id"]):
            sk = want.get(k["keyword"].strip().lower())
            if sk is not None:
                if k.get("top_target") != sk.get("target"):  # sheet bỏ Top: tool bỏ theo
                    con.execute("UPDATE rank_keywords SET top_target = ? WHERE id = ?", (sk.get("target"), k["id"]))
                continue
            elsewhere = con.execute("SELECT 1 FROM rank_keywords WHERE site = ? AND lower(keyword) = lower(?) AND "
                                    "set_id != ? AND removed_at IS NULL", (site, k["keyword"], st["id"])).fetchone()
            if elsewhere:
                con.execute("DELETE FROM rank_keywords WHERE id = ?", (k["id"],))
            else:
                dropped = named_set(con, site, DROPPED_SET_NAME, user, like=st)
                con.execute("UPDATE rank_keywords SET set_id = ?, source = 'manual' WHERE id = ?",
                            (dropped["id"], k["id"]))
            U.log_change(con, user, site, "Bỏ khỏi bộ Cam kết (sheet)", None, k["keyword"])
            res["moved"].append(k["keyword"])
    return res


PERIODS = {"check": "Lần check", "week": "Tuần", "month": "Tháng"}
BANDS = (("top3", 1, 3), ("top5", 4, 5), ("top10", 6, 10))  # nhóm Top: (khóa, từ hạng, đến hạng); hạng 11+ là "top30"


def band_labels(h: dict | None) -> tuple[str, str]:
    """Tên hai nhóm cuối theo độ sâu thật của lần check: (thấy ở hạng 11 trở đi, không thấy trong độ sâu). Cùng một độ
    sâu D thì "Hạng 11–D" / "Ngoài top D"; độ sâu khác nhau thì không ghi số giả."""
    deps = (h or {}).get("depths") or []
    miss = (h or {}).get("out_depths") or []
    deep = f"Hạng 11–{deps[0]}" if len(deps) == 1 and deps[0] > 10 else "Hạng 11 trở đi"
    out = f"Ngoài top {miss[0]}" if len(miss) == 1 else "Không thấy trong độ sâu check"
    return deep, out


def _periods(first: date, last: date, period: str) -> list[tuple[date, date, str]]:
    """Các kỳ liền nhau từ kỳ chứa `first` tới kỳ chứa `last`: (đầu kỳ, cuối kỳ, nhãn trục)."""
    out = []
    if period == "week":
        s = first - timedelta(days=first.weekday())
        while s <= last:
            out.append((s, s + timedelta(days=6), f"Tuần {s:%d/%m}"))
            s += timedelta(days=7)
    else:
        y, m = first.year, first.month
        while (y, m) <= (last.year, last.month):
            out.append((date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1]), f"T{m}/{y}"))
            y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out


def set_history(con: sqlite3.Connection, site: str, set_id: int, limit: int = 30, period: str = "check",
                today: date | None = None) -> list[dict]:
    """Tăng trưởng của một bộ theo lần check, tuần hoặc tháng: số từ khóa Top 3 / 4–5 / 6–10 / 11–30 / ngoài top 30
    (hoặc chưa thấy), vị trí trung bình (từ khóa có thứ hạng), số từ khóa lên / xuống / giữ nguyên so với điểm trước,
    tỷ lệ đạt Top mục tiêu. Mỗi điểm lấy lần check gần nhất (≤ cuối kỳ) của từng từ khóa; tuần / tháng không có lần
    check nào vẫn có điểm (giữ số kỳ trước) để timeline liền mạch. Mỗi điểm có "label" (nhãn trục), "date" (đầu kỳ /
    ngày check), "end" (cuối kỳ)."""
    ensure_tables(con)
    kws = con.execute("SELECT id, top_target FROM rank_keywords WHERE set_id = ? AND site = ? AND removed_at IS NULL",
                      (set_id, site)).fetchall()
    return history_of(con, dict(kws), limit, period, today)


def history_of(con: sqlite3.Connection, tops: dict[int, int | None], limit: int = 30, period: str = "check",
               today: date | None = None) -> list[dict]:
    """Như set_history nhưng cho một nhóm từ khóa bất kỳ ({keyword_id: Top mục tiêu}), ví dụ cả dự án."""
    if not tops:
        return []
    marks = ",".join("?" * len(tops))
    checks = con.execute(f"SELECT keyword_id, check_date, rank, depth FROM rank_checks WHERE keyword_id IN ({marks}) "
                         "ORDER BY check_date", list(tops)).fetchall()
    by_day: dict[str, list] = {}
    depth_of: dict[tuple, int] = {}
    for kid, d, r, dep in checks:
        by_day.setdefault(d, []).append((kid, r))
        depth_of[(kid, d)] = dep
    snaps, state, seen = [], {}, {}  # (ngày check, trạng thái sau ngày đó, độ sâu lần check đó của từng từ khóa)
    for d in sorted(by_day):
        for kid, r in by_day[d]:
            state[kid] = r
            seen[kid] = depth_of[(kid, d)]
        snaps.append((d, dict(state), dict(seen)))
    if not snaps:
        return []
    if period == "check":
        points = [(d, d, _vn_short(d), st, dep) for d, st, dep in snaps]
    else:
        first, last = date.fromisoformat(snaps[0][0]), max(date.fromisoformat(snaps[-1][0]), today or date.today())
        points = []
        for s0, e0, label in _periods(first, last, period):
            snap = next(((st, dep) for d, st, dep in reversed(snaps) if d <= e0.isoformat()), None)
            if snap is not None:
                points.append((s0.isoformat(), e0.isoformat(), label, *snap))
    out, before = [], {}
    for d, e, label, st, dep in points:
        ranks = list(st.values())
        ranked = [r for r in ranks if r is not None]
        up = down = same = 0
        for kid, r in st.items():
            if kid not in before:
                continue
            a, b = (before[kid] if before[kid] is not None else 999), (r if r is not None else 999)
            up, down, same = up + (b < a), down + (b > a), same + (b == a)
        with_target = [(st[k], t) for k, t in tops.items() if t and k in st]
        # Nhóm loại trừ nhau, cộng lại = số từ khóa đã check: Top 3 / 4–5 / 6–10 / thấy ở hạng 11 trở đi ("top30",
        # tên khóa giữ cho file xuất cũ) / không thấy trong độ sâu đã check ("out": chỉ biết là ngoài top <độ sâu>,
        # không phải ngoài top 30 nếu chỉ check top 10 / 20). Từ khóa chưa check lần nào: "unchecked".
        miss = sorted({dep[k] for k, r in st.items() if r is None})
        row = {"date": d, "end": e, "label": label, "checked": len(st), "unchecked": len(tops) - len(st),
               "out": sum(1 for r in ranks if r is None), "out_depths": miss,
               "depths": sorted(set(dep[k] for k in st)),
               "avg": round(sum(ranked) / len(ranked), 1) if ranked else None,
               "up": up, "down": down, "same": same, "target_total": len(with_target),
               "target_hit": sum(1 for r, t in with_target if r is not None and r <= t)}
        for key, lo, hi in BANDS:
            row[key] = sum(1 for r in ranked if lo <= r <= hi)
        row["top30"] = sum(1 for r in ranked if r > 10)
        out.append(row)
        before = st
    return out[-limit:]


def _vn_short(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


def set_target_url(con: sqlite3.Connection, site: str, keyword_id: int, raw_url: str | None, user: str) -> str | None:
    """Gán (hoặc bỏ, raw_url trống) URL mục tiêu cho một keyword check rank. Trả URL đã chuẩn hóa."""
    ensure_tables(con)
    row = con.execute("SELECT keyword FROM rank_keywords WHERE id = ? AND site = ?", (keyword_id, site)).fetchone()
    if not row:
        raise ValueError("Không có từ khóa này")
    url, url_id = None, None
    if (raw_url or "").strip():
        url = U.normalize(raw_url)
        if domain(url) != domain(site):
            raise ValueError(f"URL phải thuộc {domain(site)}")
    with con:
        if url:
            url_id = U._match_existing(con, site, url) or U._get_or_create_url(con, site, url)
        con.execute("UPDATE rank_keywords SET url_id = ? WHERE id = ?", (url_id, keyword_id))
        U.log_change(con, user, site, "Đổi URL mục tiêu" if url else "Bỏ URL mục tiêu", url, row[0])
    return url


def url_suggestions(con: sqlite3.Connection, site: str, keyword: str, end: date, days: int = 90,
                    limit: int = 5) -> list[dict]:
    """Trang của site có click / hiển thị cho đúng từ khóa này trên GSC trong `days` ngày: gợi ý URL mục tiêu."""
    rows = con.execute(
        """SELECT u.url, SUM(d.clicks), SUM(d.impressions) FROM gsc_query_daily d
           JOIN queries q ON q.id = d.query_id JOIN page_url pu ON pu.page_id = d.page_id
           JOIN urls u ON u.id = pu.url_id
           WHERE q.text = ? AND u.site = ? AND d.date BETWEEN ? AND ?
           GROUP BY u.url ORDER BY 2 DESC, 3 DESC LIMIT ?""",
        (keyword.strip().lower(), site, (end - timedelta(days=days - 1)).isoformat(), end.isoformat(), limit)).fetchall()
    return [{"url": u, "clicks": c, "impressions": i} for u, c, i in rows]


def remove_keywords(con: sqlite3.Connection, site: str, ids: list[int], user: str) -> None:
    """Bỏ theo dõi: từ khóa vào thùng rác (thôi check, không tính tiền), khôi phục được kèm lịch sử."""
    with con:
        for kid in ids:
            kw = con.execute("SELECT keyword FROM rank_keywords WHERE id = ? AND site = ?", (kid, site)).fetchone()
            if not kw:
                continue
            con.execute("UPDATE rank_keywords SET removed_at = ?, removed_by = ? WHERE id = ?", (_now(), user, kid))
            U.log_change(con, user, site, "Bỏ keyword check rank", None, kw[0])


def restore_keywords(con: sqlite3.Connection, site: str, ids: list[int], user: str) -> int:
    """Lấy từ khóa ra khỏi thùng rác (cùng lịch sử rank). Trả số từ khóa đã khôi phục."""
    n = 0
    with con:
        for kid in ids:
            kw = con.execute("SELECT keyword FROM rank_keywords WHERE id = ? AND site = ? AND removed_at IS NOT NULL",
                             (kid, site)).fetchone()
            if kw:
                con.execute("UPDATE rank_keywords SET removed_at = NULL, removed_by = NULL WHERE id = ?", (kid,))
                U.log_change(con, user, site, "Khôi phục keyword check rank", None, kw[0])
                n += 1
    return n


def _keyword_rows(con, site: str, ids: list[int]) -> list[tuple]:
    if not ids:
        return []
    return con.execute(f"SELECT id, keyword, set_id, url_id, top_target, note, source FROM rank_keywords WHERE site = ? "
                       f"AND removed_at IS NULL AND id IN ({','.join('?' * len(ids))})", (site, *ids)).fetchall()


def set_paused(con: sqlite3.Connection, site: str, ids: list[int], paused: bool, user: str) -> int:
    """Tạm dừng / chạy lại từng từ khóa: tạm dừng thì giữ trong bộ nhưng không check, không tính tiền."""
    rows = _keyword_rows(con, site, ids)
    with con:
        for kid, kw, *_ in rows:
            con.execute("UPDATE rank_keywords SET paused = ? WHERE id = ?", (int(paused), kid))
            U.log_change(con, user, site, "Tạm dừng keyword" if paused else "Chạy lại keyword", None, kw)
    return len(rows)


def set_note(con: sqlite3.Connection, site: str, ids: list[int], note: str, user: str) -> int:
    """Ghi chú cho một hay nhiều từ khóa (trống = xóa ghi chú)."""
    note = " ".join((note or "").split())[:300]
    rows = _keyword_rows(con, site, ids)
    with con:
        for kid, kw, *_ in rows:
            con.execute("UPDATE rank_keywords SET note = ? WHERE id = ?", (note or None, kid))
            U.log_change(con, user, site, "Ghi chú keyword", None, f"{kw}: {note or '(xóa)'}")
    return len(rows)


def move_keywords(con: sqlite3.Connection, site: str, ids: list[int], to_set: int, user: str) -> dict:
    """Chuyển từ khóa sang bộ khác, giữ nguyên lịch sử (cùng dòng). Bộ đích đã có từ khóa đó thì bỏ qua."""
    dest = get_set(con, to_set)
    if not dest or dest["site"] != site:
        raise ValueError("Không có bộ từ khóa này")
    res = {"moved": [], "skipped": []}
    with con:
        for kid, kw, sid, *_ in _keyword_rows(con, site, ids):
            if sid == to_set:
                continue
            if con.execute("SELECT 1 FROM rank_keywords WHERE set_id = ? AND lower(keyword) = lower(?)",
                           (to_set, kw)).fetchone():
                res["skipped"].append(kw)
                continue
            con.execute("UPDATE rank_keywords SET set_id = ?, source = CASE WHEN source = 'kpi' AND ? != 'kpi' THEN "
                        "'manual' ELSE source END WHERE id = ?", (to_set, dest["kind"], kid))
            U.log_change(con, user, site, f"Chuyển keyword sang bộ {dest['name']}", None, kw)
            res["moved"].append(kw)
    return res


def copy_keywords(con: sqlite3.Connection, site: str, s: RankSettings, end: date, ids: list[int], to_set: int,
                  user: str) -> dict:
    """Chép từ khóa (kèm URL / Top mục tiêu, ghi chú) sang bộ khác: bộ đích check riêng theo nơi check của nó, lịch sử
    bắt đầu từ lần check đầu ở bộ đó."""
    rows = _keyword_rows(con, site, ids)
    urls = dict(con.execute("SELECT id, url FROM urls WHERE id IN (%s)" % ",".join("?" * len(rows)),
                            [r[3] for r in rows]).fetchall()) if rows else {}
    res = add_keywords(con, site, s, end, [(kw, urls.get(url_id), top) for _, kw, _, url_id, top, _, _ in rows],
                       user, source="manual", set_id=to_set)
    notes = {kw.lower(): note for _, kw, _, _, _, note, _ in rows if note}
    if notes:
        with con:
            for kw, note in notes.items():
                con.execute("UPDATE rank_keywords SET note = COALESCE(note, ?) WHERE set_id = ? AND lower(keyword) = ?",
                            (note, to_set, kw))
    return res


def keyword_log(con: sqlite3.Connection, site: str, keyword: str, limit: int = 50) -> list[dict]:
    """Nhật ký của một từ khóa: ai thêm, đổi URL / Top, ghi chú, tạm dừng, chuyển bộ… (mới nhất trước)."""
    rows = con.execute("SELECT at, user, action, url, detail FROM change_log WHERE site = ? AND "
                       "(lower(detail) = lower(?) OR lower(detail) LIKE lower(?) || ':%') ORDER BY at DESC LIMIT ?",
                       (site, keyword, keyword, limit)).fetchall()
    return [{"at": a, "user": u, "action": ac, "url": url, "detail": d} for a, u, ac, url, d in rows]


def delete_check(con: sqlite3.Connection, site: str, keyword_id: int, check_date: str, user: str) -> bool:
    """Xóa một lần check sai (ví dụ Google trả kết quả lạ). Chỉ Chủ tool: web kiểm tra quyền. Có ghi nhật ký."""
    row = con.execute("SELECT k.keyword, c.rank FROM rank_checks c JOIN rank_keywords k ON k.id = c.keyword_id "
                      "WHERE c.keyword_id = ? AND c.check_date = ? AND k.site = ?",
                      (keyword_id, check_date, site)).fetchone()
    if not row:
        return False
    with con:
        con.execute("DELETE FROM rank_checks WHERE keyword_id = ? AND check_date = ?", (keyword_id, check_date))
        U.log_change(con, user, site, "Xóa một lần check rank", None,
                     f"{row[0]}: {check_date} (vị trí {row[1] if row[1] is not None else 'ngoài độ sâu'})")
    return True


# ---- Mốc sự kiện trên biểu đồ tăng trưởng ----

def events(con: sqlite3.Connection, site: str, set_id: int | None = None) -> list[dict]:
    """Mốc của một bộ và mốc chung (mọi bộ), cũ trước."""
    ensure_tables(con)
    return [{"id": i, "set_id": sid, "day": d, "text": t, "by": by} for i, sid, d, t, by in con.execute(
        "SELECT id, set_id, day, text, created_by FROM rank_events WHERE site = ? AND (set_id IS NULL OR set_id = ?) "
        "ORDER BY day, id", (site, set_id))]


def add_event(con: sqlite3.Connection, site: str, day: date, text: str, user: str, set_id: int | None = None) -> int:
    ensure_tables(con)
    text = " ".join((text or "").split())[:120]
    if not text:
        raise ValueError("Chưa nhập nội dung mốc")
    with con:
        cur = con.execute("INSERT INTO rank_events (site, set_id, day, text, created_by, created_at) VALUES "
                          "(?, ?, ?, ?, ?, ?)", (site, set_id, day.isoformat(), text, user, _now()))
        U.log_change(con, user, site, "Thêm mốc sự kiện", None, f"{day:%d/%m/%Y}: {text}")
    return cur.lastrowid


def delete_event(con: sqlite3.Connection, site: str, event_id: int, user: str) -> None:
    row = con.execute("SELECT day, text FROM rank_events WHERE id = ? AND site = ?", (event_id, site)).fetchone()
    if row:
        with con:
            con.execute("DELETE FROM rank_events WHERE id = ?", (event_id,))
            U.log_change(con, user, site, "Xóa mốc sự kiện", None, f"{row[0]}: {row[1]}")


def toggle_star(con: sqlite3.Connection, site: str, s: RankSettings, end: date, url_id: int, query: str,
                user: str) -> tuple[bool, str]:
    """★ ở màn URL: thêm keyword GSC vào bộ team tạo đầu tiên (không tự gán URL mục tiêu: team gán ở màn Quản lý URL,
    hoặc lấy từ sheet cam kết), hoặc bỏ khỏi các bộ team tạo nếu đã theo dõi. Từ khóa cam kết bỏ ở sheet."""
    ensure_tables(con)
    rows = con.execute("SELECT k.id, s.kind FROM rank_keywords k JOIN rank_sets s ON s.id = k.set_id "
                       "WHERE k.site = ? AND lower(k.keyword) = lower(?) AND k.removed_at IS NULL",
                       (site, query)).fetchall()
    custom = [kid for kid, kind in rows if kind != "kpi"]
    if custom:
        remove_keywords(con, site, custom, user)
        return True, f"Đã bỏ theo dõi “{query}”"
    if rows:
        return False, f"“{query}” là từ khóa cam kết: bỏ ở tab Từ khóa cam kết của sheet dự án"
    r = add_keywords(con, site, s, end, [(query, None)], user, source="gsc")
    if r["over_budget"]:
        return False, (f"Không thêm được “{query}”: ước tính chi phí tháng sẽ vượt ngân sách "
                       f"{s.monthly_budget_usd:.0f} USD. Bỏ bớt keyword, giãn lịch check hoặc giảm độ sâu.")
    msg = f"Đã thêm “{query}” vào check rank; tổng ước tính {usd(r['estimate'])} USD/tháng"
    if r["estimate"] >= ALERT_RATIO * s.monthly_budget_usd:
        msg += f". Cảnh báo: đã dùng {r['estimate'] / s.monthly_budget_usd:.0%} ngân sách"
    return True, msg


def tracked_queries(con: sqlite3.Connection, site: str) -> set[str]:
    ensure_tables(con)
    return {r[0].strip().lower() for r in con.execute("SELECT keyword FROM rank_keywords WHERE site = ? AND "
                                                      "removed_at IS NULL", (site,))}


def latest_by_keyword(con: sqlite3.Connection, site: str) -> dict[str, dict]:
    return {k["keyword"].strip().lower(): k for k in primary_keywords(con, site, date.today())}


# ---- Gọi DataForSEO ----

def load_credentials(path: Path) -> tuple[str, str] | None:
    if not path.exists():
        return None
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    login, password = raw.get("login", "").strip(), raw.get("password", "").strip()
    return (login, password) if login and password else None


class DataForSEO:
    def __init__(self, login: str, password: str, timeout: int = 60):
        token = base64.b64encode(f"{login}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
        self.timeout = timeout

    def _call(self, method: str, path: str, body=None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = Request(f"{API}/{path}", data=data, headers=self.headers, method=method)
        try:
            resp = json.loads(urlopen(req, timeout=self.timeout).read())
        except HTTPError as e:  # DataForSEO ghi lý do lỗi trong nội dung trả về, ví dụ 40104: tài khoản chưa xác minh
            try:
                resp = json.loads(e.read())
            except ValueError:
                raise RuntimeError(f"DataForSEO trả lỗi HTTP {e.code}") from e
        if resp.get("status_code") != 20000:
            raise RuntimeError(f"DataForSEO {resp.get('status_code')}: {resp.get('status_message')}")
        return resp

    def post(self, tasks: list[dict]) -> list[dict]:
        out = []
        for i in range(0, len(tasks), 100):
            out += self._call("POST", "task_post", tasks[i:i + 100])["tasks"]
        return out

    def ready_ids(self) -> set[str]:
        return {r["id"] for t in self._call("GET", "tasks_ready")["tasks"] or [] for r in t.get("result") or []}

    def get(self, task_id: str) -> dict:
        """Kết quả bản đầy đủ (advanced): có AI Overview và các ô đặc biệt bên cạnh kết quả tự nhiên. DataForSEO chỉ
        tính tiền lúc gửi task, đọc kết quả (regular hay advanced) trong 30 ngày không tốn thêm."""
        return self._call("GET", f"task_get/advanced/{task_id}")["tasks"][0]

    def balance(self) -> float | None:
        req = Request("https://api.dataforseo.com/v3/appendix/user_data", headers=self.headers)
        resp = json.loads(urlopen(req, timeout=self.timeout).read())
        return resp["tasks"][0]["result"][0]["money"]["balance"]


def _local_dt(iso_utc: str | None) -> datetime:
    """Giờ máy (giờ Việt Nam) của một mốc lưu dạng ISO UTC; lỗi / trống thì coi như rất cũ."""
    try:
        return datetime.fromisoformat(iso_utc).astimezone().replace(tzinfo=None)
    except (TypeError, ValueError):
        return datetime.min


def due(con: sqlite3.Connection, site: str, end: date, today: date, now: datetime | None = None) -> list[dict]:
    """Keyword cần check theo lịch của bộ chứa nó: chưa có lần check (hoặc task đang chờ) từ lần theo lịch gần nhất.
    now: tính cả giờ check của bộ (chưa tới giờ thì chưa đến hạn); không có thì chỉ xét ngày. Bộ Nháp không check."""
    out = []
    for k in keywords(con, site, end):
        if k["paused"] or k["draft"]:
            continue
        if now is not None:
            at = last_scheduled_at(k["set"]["schedule"], now)
            sched_day = at.date() if at else None
            if at and k["date"] is None and _local_dt(k["added_at"]) > at:
                continue  # từ khóa mới thêm sau lần theo lịch gần nhất: chờ tới giờ của lần sau, không check ngay
        else:
            sched_day = last_scheduled_day(k["set"]["schedule"], today)
        if sched_day is None:
            continue
        pending = con.execute(
            "SELECT MAX(d) FROM (SELECT check_date d FROM rank_tasks WHERE keyword_id = ? AND status = 'posted' "
            "UNION ALL SELECT check_date FROM rank_task_links WHERE keyword_id = ? AND status = 'posted')",
            (k["id"], k["id"])).fetchone()[0]
        last = max(filter(None, [k["date"], pending]), default=None)
        if last is None or date.fromisoformat(last) < sched_day:
            out.append(k)
    return out


def _where_key(s: RankSettings, k: dict) -> tuple:
    """Hai dòng từ khóa cho cùng một trang kết quả Google khi cùng chữ và cùng nơi check."""
    w = settings_for(s, k.get("set"))
    return (k["keyword"].strip().lower(), w.se_domain, w.device, w.location_code, w.language_code)


def post(con, site: str, s: RankSettings, client, todo: list[dict], today: date, log=print) -> int:
    """Gửi DataForSEO các từ khóa cần check. Cùng từ khóa + cùng nơi check: chỉ gửi một task (độ sâu lớn nhất), các
    dòng còn lại nhận chung kết quả; đã có task hôm nay ở bộ khác (đủ sâu) thì dùng lại, không trả tiền lần hai.
    Trả số dòng từ khóa đã gửi hoặc đã gắn vào task dùng chung."""
    todo = [k for k in todo if not k.get("draft")]
    if not todo:
        return 0
    day = today.isoformat()
    groups: dict[tuple, list[dict]] = {}
    for k in todo:
        groups.setdefault(_where_key(s, k), []).append(k)
    need = {key: max(k["depth"] for k in ks) for key, ks in groups.items()}
    reuse: dict[tuple, tuple[str, str]] = {}  # key → (task_id, status) của task hôm nay dùng lại được
    by_set = {x["id"]: x for x in sets(con, site)}
    for task_id, depth, status, kid, kw, sid in con.execute(
            "SELECT t.task_id, t.depth, t.status, k.id, k.keyword, k.set_id FROM rank_tasks t "
            "JOIN rank_keywords k ON k.id = t.keyword_id WHERE t.check_date = ? AND t.status IN ('posted', 'done') "
            "AND k.site = ? ORDER BY t.status = 'done' DESC, t.posted_at DESC", (day, site)).fetchall():
        key = _where_key(s, {"keyword": kw, "set": by_set.get(sid)})
        if key in groups and key not in reuse and depth >= need[key] and \
                all(k["id"] != kid for k in groups[key]):  # check lại chính dòng đó trong ngày: gửi mới
            reuse[key] = (task_id, status)
    to_post = [(key, ks) for key, ks in groups.items() if key not in reuse]
    batch_cost = sum(_pages(need[key]) for key, _ in to_post) * s.price_per_page
    spent = spent_this_month(con, today)
    if to_post and spent + batch_cost > s.monthly_budget_usd:
        log(f"Dừng check rank: đã dùng {usd(spent)} USD tháng này, lượt này cần {usd(batch_cost, 3)} USD, "
            f"vượt ngân sách {s.monthly_budget_usd:.0f} USD.")
        to_post = []
        if not reuse:
            return 0
    linked = 0
    with con:
        for key, (task_id, _) in reuse.items():
            for k in groups[key]:
                con.execute("INSERT OR REPLACE INTO rank_task_links VALUES (?, ?, ?, ?, 'posted')",
                            (task_id, k["id"], day, _now()))
                linked += 1
    for task_id, status in reuse.values():  # task đã có kết quả: đọc lại (miễn phí) và ghi luôn
        if status == "done":
            try:
                task = client.get(task_id)
                if task.get("status_code") == 20000:
                    with con:
                        _save_links(con, site, task_id, task)
            except Exception as e:  # noqa: BLE001  (lần chạy sau đọc lại)
                log(f"Chưa đọc lại được kết quả dùng chung: {e}")
    posted, errors = 0, {}
    if to_post:
        tasks = []
        for key, ks in to_post:  # mỗi nhóm check theo nơi check của bộ chứa nó
            w = settings_for(s, ks[0].get("set"))
            tasks.append({"keyword": ks[0]["keyword"], "location_code": w.location_code,
                          "language_code": w.language_code, "device": w.device, "se_domain": w.se_domain,
                          "depth": need[key], "tag": str(ks[0]["id"]),
                          # tải cả AI Overview hiện chậm (+0,0006 USD, hoàn lại nếu từ khóa không có AI Overview)
                          "load_async_ai_overview": True})
        with con:
            for (key, ks), t in zip(to_post, client.post(tasks)):
                if t.get("status_code") != 20100:
                    errors.setdefault(t.get("status_message") or str(t.get("status_code")), []).extend(
                        k["keyword"] for k in ks)
                    continue
                con.execute("INSERT INTO rank_tasks VALUES (?, ?, ?, ?, ?, ?, 'posted')",
                            (t["id"], ks[0]["id"], need[key], day, _now(), t.get("cost", 0)))
                for k in ks[1:]:
                    con.execute("INSERT OR REPLACE INTO rank_task_links VALUES (?, ?, ?, ?, 'posted')",
                                (t["id"], k["id"], day, _now()))
                posted += len(ks)
    for message, kws in errors.items():  # gộp: thường mọi keyword cùng một lỗi tài khoản
        log(f"Không gửi được {len(kws)} keyword ({', '.join(kws[:3])}{'…' if len(kws) > 3 else ''}): {message}")
    if posted:
        log(f"Đã gửi {posted} keyword để check rank, khoảng {usd(batch_cost, 3)} USD.")
    if linked:
        log(f"Dùng lại kết quả hôm nay cho {linked} keyword trùng ở bộ khác (không tính thêm tiền).")
    return posted + linked


def _save_links(con, site: str, task_id: str, task: dict) -> int:
    """Ghi kết quả của một task cho các dòng từ khóa dùng chung (mỗi dòng theo URL mục tiêu của nó), chi phí 0."""
    row = con.execute("SELECT depth FROM rank_tasks WHERE task_id = ?", (task_id,)).fetchone()
    depth = row[0] if row else 10
    rows = con.execute("SELECT l.keyword_id, l.check_date, u.url FROM rank_task_links l JOIN rank_keywords k ON "
                       "k.id = l.keyword_id LEFT JOIN urls u ON u.id = k.url_id WHERE l.task_id = ? AND "
                       "l.status = 'posted'", (task_id,)).fetchall()
    serp = parse_serp(task, site) if rows else None
    for kid, day, target in rows:
        rank, ranking_url, target_rank = parse_rank(task, site, target)
        con.execute("INSERT OR REPLACE INTO rank_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (kid, day, depth, rank, ranking_url, target_rank, 0, _now()))
        save_serp(con, kid, day, serp)
        con.execute("UPDATE rank_task_links SET status = 'done' WHERE task_id = ? AND keyword_id = ?",
                    (task_id, kid))
    return len(rows)


def _is_goto(url: str) -> bool:
    return bool(re.match(r"^https?://(www\.)?google\.[a-z.]+/goto\?", url or ""))


def resolve_goto(url: str, timeout: int = 15) -> str | None:
    """URL thật sau link chuyển hướng google.com/goto?url=… (Google mobile giấu link một số kết quả sau link này).
    Hỏi Google một lần, không đi theo chuyển hướng; lỗi thì None."""
    from urllib.error import HTTPError as _HTTPError
    from urllib.request import HTTPRedirectHandler, build_opener

    class _Stop(HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    url = re.sub(r"^https?://google\.", "https://www.google.", url)
    try:
        build_opener(_Stop).open(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout)
    except _HTTPError as e:
        loc = e.headers.get("Location") or ""
        if e.code in (301, 302, 303, 307, 308) and loc:
            return None if _is_goto(loc) else loc
    except Exception:  # noqa: BLE001  (mất mạng: vẫn tính rank, chỉ thiếu URL)
        pass
    return None


def parse_rank(task: dict, site: str, target_url: str | None,
               resolve=resolve_goto) -> tuple[int | None, str | None, int | None]:
    """(rank tốt nhất của site, URL đang xếp hạng, rank của URL mục tiêu).
    Kết quả Google giấu sau link google.com/goto?url=… thì nhận site qua breadcrumb (tên miền thật) và hỏi Google URL
    thật; trước đây các kết quả này bị tính là của google.com nên site bị báo "ngoài top" dù đang đứng đầu."""
    host = domain(site)
    items = (task.get("result") or [{}])[0].get("items") or []
    best, best_url, target_rank = None, None, None
    for it in items:
        if it.get("type") != "organic":
            continue
        raw = it.get("url") or ""
        hidden = _is_goto(raw)
        item_host = domain(it.get("breadcrumb") or "") if hidden else (it.get("domain") or "").removeprefix("www.")
        if item_host != host:
            continue
        if hidden:
            real = resolve(raw)
            raw = real if real and domain(real) == host else ""
        url = U.normalize(raw) if raw else None
        if best is None:
            best, best_url = it["rank_group"], url
        if target_url and target_rank is None and url == target_url:
            target_rank = it["rank_group"]
    return best, best_url, target_rank


def _host_match(host: str, site_host: str) -> bool:
    host = (host or "").lower().removeprefix("www.")
    return bool(host) and (host == site_host or host.endswith("." + site_host))


def parse_serp(task: dict, site: str) -> dict:
    """Phần còn lại của trang kết quả (ngoài vị trí của site): AI Overview (có / không, site có được trích, các nguồn
    được trích), 10 kết quả tự nhiên đầu, các loại ô đặc biệt. aio_cited None khi có AI Overview nhưng DataForSEO
    không tải được nội dung (AI Overview hiện chậm)."""
    host = domain(site)
    items = (task.get("result") or [{}])[0].get("items") or []
    aio, cited, refs, top10, features, text, organic = False, None, [], [], set(), [], []
    for it in items:
        t = it.get("type") or ""
        if t and t != "organic":
            features.add(t)
        if t == "ai_overview":
            aio = True
            found = list(it.get("references") or [])
            for el in it.get("items") or []:
                found += el.get("references") or []
                for part in (el.get("title"), el.get("text") or el.get("markdown")):
                    if part:
                        text.append(str(part))
            seen = set()
            for r in found:
                d = (r.get("domain") or domain(r.get("url") or "")).lower().removeprefix("www.")
                key = (d, r.get("url"))
                if d and key not in seen:
                    seen.add(key)
                    refs.append({"domain": d, "url": r.get("url") or "", "title": r.get("title") or r.get("source") or ""})
            if refs:
                cited = any(_host_match(r["domain"], host) for r in refs)
            elif not it.get("asynchronous_ai_overview"):
                cited = False
        elif t == "organic" and it.get("rank_group"):
            row = {"rank": it.get("rank_group"), "domain": (it.get("domain") or "").lower().removeprefix("www."),
                   "url": it.get("url") or ""}
            organic.append(row)
            if row["rank"] <= 10:
                top10.append(row)
    return {"aio": aio, "aio_cited": cited if aio else False, "aio_refs": refs, "top10": top10, "organic": organic,
            "features": sorted(features), "aio_text": "\n".join(text) if aio else ""}


def save_serp(con, keyword_id: int, check_date: str, serp: dict) -> None:
    con.execute("INSERT OR REPLACE INTO rank_serp (keyword_id, check_date, aio, aio_cited, aio_refs, top10, features, "
                "aio_text, organic) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (keyword_id, check_date, int(serp["aio"]),
                 None if serp["aio_cited"] is None else int(serp["aio_cited"]),
                 json.dumps(serp["aio_refs"], ensure_ascii=False), json.dumps(serp["top10"], ensure_ascii=False),
                 json.dumps(serp["features"]), serp.get("aio_text") or None,
                 json.dumps(serp["organic"], ensure_ascii=False) if serp.get("organic") is not None else None))


def collect(con, site: str, client, log=print) -> int:
    pending = con.execute(
        "SELECT t.task_id, t.keyword_id, t.depth, t.check_date, t.cost, u.url FROM rank_tasks t "
        "JOIN rank_keywords k ON k.id = t.keyword_id LEFT JOIN urls u ON u.id = k.url_id "
        "WHERE t.status = 'posted' AND k.site = ?", (site,)).fetchall()
    if not pending:
        return 0
    ready = client.ready_ids()
    done = 0
    for task_id, kid, depth, check_date, cost, target in pending:
        if task_id not in ready:
            continue
        task = client.get(task_id)
        if task.get("status_code") != 20000:
            log(f"Lỗi kết quả task {task_id}: {task.get('status_message')}")
            continue
        rank, ranking_url, target_rank = parse_rank(task, site, target)
        with con:
            con.execute("INSERT OR REPLACE INTO rank_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (kid, check_date, depth, rank, ranking_url, target_rank, cost, _now()))
            save_serp(con, kid, check_date, parse_serp(task, site))
            con.execute("UPDATE rank_tasks SET status = 'done' WHERE task_id = ?", (task_id,))
            _save_links(con, site, task_id, task)
        done += 1
    return done


def reparse(con, site: str, client, since: date, log=print) -> int:
    """Đọc lại kết quả các lần check đã xong từ `since` (DataForSEO giữ kết quả task 30 ngày, đọc lại không tốn tiền)
    và tính lại rank. Dùng khi sửa cách đọc kết quả. Trả số lần check có số thay đổi."""
    rows = con.execute(
        "SELECT t.task_id, t.keyword_id, t.check_date, u.url, c.rank, c.ranking_url, c.target_rank FROM rank_tasks t "
        "JOIN rank_keywords k ON k.id = t.keyword_id LEFT JOIN urls u ON u.id = k.url_id "
        "JOIN rank_checks c ON c.keyword_id = t.keyword_id AND c.check_date = t.check_date "
        "WHERE t.status = 'done' AND k.site = ? AND t.check_date >= ?", (site, since.isoformat())).fetchall()
    changed, skipped = 0, {}
    for task_id, kid, check_date, target, old_rank, old_url, old_target in rows:
        try:
            task = client.get(task_id)
        except Exception as e:  # noqa: BLE001
            log(f"Không đọc lại được task {task_id}: {e}")
            continue
        if task.get("status_code") != 20000:  # ví dụ 40001: task của tài khoản DataForSEO khác
            msg = f"{task.get('status_code')}: {task.get('status_message')}"
            skipped[msg] = skipped.get(msg, 0) + 1
            continue
        new = parse_rank(task, site, target)
        with con:  # đọc lại cũng lưu AI Overview / đối thủ (lần check cũ chưa có phần này)
            save_serp(con, kid, check_date, parse_serp(task, site))
        if new != (old_rank, old_url, old_target):
            with con:
                con.execute("UPDATE rank_checks SET rank = ?, ranking_url = ?, target_rank = ? "
                            "WHERE keyword_id = ? AND check_date = ?", (*new, kid, check_date))
            changed += 1
    for msg, n in skipped.items():  # trước đây bỏ qua im lặng: đổi tài khoản DataForSEO thì không biết vì sao trống
        log(f"Không đọc lại được {n}/{len(rows)} lần check (DataForSEO {msg}). Kết quả của tài khoản DataForSEO cũ "
            "không đọc được bằng tài khoản mới." if msg.startswith("40001") else
            f"Không đọc lại được {n}/{len(rows)} lần check (DataForSEO {msg}).")
    return changed


def wait_and_collect(con, site: str, client, wait_minutes: int, log=print, sleep=time.sleep) -> None:
    deadline = time.monotonic() + wait_minutes * 60
    while con.execute("SELECT COUNT(*) FROM rank_tasks WHERE status = 'posted'").fetchone()[0]:
        got = collect(con, site, client, log)
        if got:
            log(f"Đã nhận kết quả {got} keyword.")
        if time.monotonic() > deadline:
            log("Còn keyword chưa có kết quả, lần chạy sau sẽ lấy tiếp.")
            break
        sleep(30)


def run(con, site: str, s: RankSettings, client, end: date, today: date | None = None, wait_minutes: int = 15,
        only_ids: list[int] | None = None, log=print, sleep=time.sleep) -> None:
    """Lấy kết quả còn tồn, gửi keyword đến hạn theo lịch (hoặc `only_ids` khi bấm Check ngay), rồi chờ kết quả."""
    if s.paused:
        log("Tạm ngưng check rank cho website này: không gửi yêu cầu nào.")
        return
    ensure_tables(con)
    now = datetime.now() if today is None else None  # chạy thật: tính cả giờ check của từng bộ
    today = today or date.today()
    collect(con, site, client, log)
    if only_ids is not None:
        todo = [k for k in keywords(con, site, end) if k["id"] in set(only_ids)]
    else:
        todo = due(con, site, end, today, now)
    post(con, site, s, client, todo, today, log)
    wait_and_collect(con, site, client, wait_minutes, log, sleep)


def serp_latest(con: sqlite3.Connection, site: str, end: date, set_id: int | None = None) -> list[dict]:
    """Mỗi từ khóa (mỗi từ khóa một dòng, như Tổng quan; set_id: chỉ một bộ) kèm phần trang kết quả của lần check
    gần nhất có đọc phần đó: aio, aio_cited, aio_refs, top10, ngày; và lần trước đó (để so)."""
    ensure_tables(con)
    kws = keywords(con, site, end, set_id) if set_id else primary_keywords(con, site, end)
    out = []
    for k in kws:
        rows = con.execute("SELECT check_date, aio, aio_cited, aio_refs, top10 FROM rank_serp WHERE keyword_id = ? "
                           "AND aio IS NOT NULL ORDER BY check_date DESC LIMIT 2", (k["id"],)).fetchall()
        cur = rows[0] if rows else None
        prev = rows[1] if len(rows) > 1 else None
        out.append({"id": k["id"], "keyword": k["keyword"], "rank": k["rank"], "depth": k["last_depth"],
                    "date": cur[0] if cur else None, "aio": bool(cur[1]) if cur else None,
                    "cited": (None if cur[2] is None else bool(cur[2])) if cur else None,
                    "refs": json.loads(cur[3] or "[]") if cur else [], "top10": json.loads(cur[4] or "[]") if cur else [],
                    "prev_aio": bool(prev[1]) if prev else None,
                    "prev_cited": (None if prev[2] is None else bool(prev[2])) if prev else None})
    return out


def aio_summary(rows: list[dict], site: str) -> dict:
    """Tổng hợp AI Overview trên bộ từ khóa: có AIO, site được trích (lần này / lần trước), nguồn AI hay trích, đối thủ
    hay gặp ở top 10 (không tính site)."""
    host = domain(site)
    have = [r for r in rows if r["aio"] is not None]
    with_aio = [r for r in have if r["aio"]]
    cited = [r for r in with_aio if r["cited"]]
    prev = [r for r in have if r["prev_aio"] is not None]
    ref_count: dict[str, int] = {}
    for r in with_aio:
        for d in {x["domain"] for x in r["refs"]}:
            if not _host_match(d, host):
                ref_count[d] = ref_count.get(d, 0) + 1
    comp: dict[str, list[int]] = {}
    for r in have:
        for x in r["top10"]:
            if x["domain"] and not _host_match(x["domain"], host):
                comp.setdefault(x["domain"], []).append(x["rank"] or 0)
    return {"total": len(rows), "checked": len(have), "aio": len(with_aio), "cited": len(cited),
            "prev_aio": sum(1 for r in prev if r["prev_aio"]) if prev else None,
            "prev_cited": sum(1 for r in prev if r["prev_cited"]) if prev else None,
            "last": max((r["date"] for r in have), default=None),
            "top_refs": sorted(ref_count.items(), key=lambda x: (-x[1], x[0]))[:10],
            "competitors": sorted(((d, len(v), sum(v) / len(v)) for d, v in comp.items()),
                                  key=lambda x: (-x[1], x[2]))[:10]}


def serp_history(con: sqlite3.Connection, keyword_id: int) -> list[dict]:
    """Các lần check có đọc trang kết quả của một từ khóa, mới trước: ngày, có AIO, được trích, nguồn AI trích, top 10."""
    ensure_tables(con)
    out = []
    for d, aio, cited, refs, top10, organic, depth in con.execute(
            "SELECT s.check_date, s.aio, s.aio_cited, s.aio_refs, s.top10, s.organic, c.depth FROM rank_serp s "
            "LEFT JOIN rank_checks c ON c.keyword_id = s.keyword_id AND c.check_date = s.check_date "
            "WHERE s.keyword_id = ? AND s.aio IS NOT NULL ORDER BY s.check_date DESC", (keyword_id,)):
        t10 = json.loads(top10 or "[]")
        out.append({"date": d, "aio": bool(aio), "cited": None if cited is None else bool(cited),
                    "refs": json.loads(refs or "[]"), "top10": t10,
                    # organic: mọi kết quả trong độ sâu (lần check cũ chỉ có 10 đầu: depth_seen = 10)
                    "organic": json.loads(organic) if organic else t10,
                    "depth_seen": (depth or 10) if organic else min(depth or 10, 10)})
    return out


def serp_flags(con: sqlite3.Connection, ids: list[int]) -> dict[int, tuple[bool, bool | None]]:
    """(có AI Overview, site được trích) ở lần check gần nhất có đọc trang kết quả, cho bảng từ khóa."""
    ensure_tables(con)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out = {}
    for kid, aio, cited in con.execute(
            f"SELECT s.keyword_id, s.aio, s.aio_cited FROM rank_serp s JOIN (SELECT keyword_id, MAX(check_date) m "
            f"FROM rank_serp WHERE aio IS NOT NULL AND keyword_id IN ({marks}) GROUP BY keyword_id) l "
            "ON l.keyword_id = s.keyword_id AND l.m = s.check_date", list(ids)):
        out[kid] = (bool(aio), None if cited is None else bool(cited))
    return out


def compare_top10(cur: list[dict], prev: list[dict] | None) -> list[dict]:
    """Top 10 lần này kèm thay đổi so với lần trước theo tên miền: move > 0 lên hạng, "new" mới vào top 10."""
    before = {}
    for x in prev or []:
        before.setdefault(x["domain"], x["rank"])
    out = []
    for x in cur:
        b = before.get(x["domain"])
        out.append({**x, "move": None if prev is None else ("new" if b is None else b - x["rank"])})
    return out


def where_short(s: RankSettings) -> str:
    """Nơi check gọn cho nhãn số liệu: "Điện thoại · Toàn quốc (Việt Nam)"."""
    return f"{DEVICES.get(s.device, s.device)} · {locations().get(s.location_code, str(s.location_code))}"


def aio_window(con: sqlite3.Connection, site: str, end: date, today: date, weeks: int = 4,
               set_id: int | None = None) -> list[dict]:
    """AI Overview của từng từ khóa trong `weeks` tuần gần nhất (mỗi tuần lấy lần check cuối của tuần đó): số tuần có
    số, số tuần có AI Overview, số tuần website được trích (trong các tuần biết được), và lần mới nhất (nguồn trích,
    ngày). AI Overview thay đổi giữa các lần tìm, nên đo theo nhiều tuần thay vì một lần chụp."""
    ensure_tables(con)
    since = (today - timedelta(days=7 * weeks - 1)).isoformat()
    kws = keywords(con, site, end, set_id) if set_id else primary_keywords(con, site, end)
    out = []
    for k in kws:
        by_week: dict[str, tuple] = {}
        for d, aio, cited, refs in con.execute(
                "SELECT check_date, aio, aio_cited, aio_refs FROM rank_serp WHERE keyword_id = ? AND aio IS NOT NULL "
                "AND check_date >= ? ORDER BY check_date", (k["id"], since)):
            wk = (date.fromisoformat(d) - timedelta(days=date.fromisoformat(d).weekday())).isoformat()
            by_week[wk] = (d, bool(aio), None if cited is None else bool(cited), refs)
        rows = sorted(by_week.values(), key=lambda r: r[0], reverse=True)
        last = rows[0] if rows else None
        out.append({"id": k["id"], "keyword": k["keyword"], "rank": k["rank"], "depth": k["last_depth"],
                    "target_url": k.get("target_url"), "weeks": len(rows),
                    "aio_weeks": sum(1 for r in rows if r[1]),
                    "cited_weeks": sum(1 for r in rows if r[1] and r[2]),
                    "known_weeks": sum(1 for r in rows if r[1] and r[2] is not None),
                    "date": last[0] if last else None, "aio": last[1] if last else None,
                    "cited": last[2] if last else None, "refs": json.loads(last[3] or "[]") if last else []})
    return out


def aio_stats(rows: list[dict]) -> dict:
    """Ba số chính trên cửa sổ nhiều tuần: tỷ lệ có AI Overview (trên các lần kiểm tra), tỷ lệ được trích (trên các lần
    có AI Overview biết được nội dung), số từ khóa đã có số / tổng."""
    checks = sum(r["weeks"] for r in rows)
    aio = sum(r["aio_weeks"] for r in rows)
    known = sum(r["known_weeks"] for r in rows)
    cited = sum(r["cited_weeks"] for r in rows)
    return {"total": len(rows), "checked": sum(1 for r in rows if r["weeks"]), "checks": checks, "aio": aio,
            "known": known, "cited": cited, "aio_rate": aio / checks if checks else None,
            "cited_rate": cited / known if known else None,
            "last": max((r["date"] for r in rows if r["date"]), default=None)}


def aio_weekly(con: sqlite3.Connection, site: str, end: date, today: date, weeks: int = 12,
               set_id: int | None = None) -> list[dict]:
    """Theo từng tuần (thứ Hai đầu tuần): số từ khóa có số, có AI Overview, được trích; để vẽ xu hướng."""
    ensure_tables(con)
    kws = keywords(con, site, end, set_id) if set_id else primary_keywords(con, site, end)
    ids = [k["id"] for k in kws]
    if not ids:
        return []
    since = (today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)).isoformat()
    marks = ",".join("?" * len(ids))
    per: dict[tuple, tuple] = {}
    for kid, d, aio, cited in con.execute(
            f"SELECT keyword_id, check_date, aio, aio_cited FROM rank_serp WHERE aio IS NOT NULL AND check_date >= ? "
            f"AND keyword_id IN ({marks}) ORDER BY check_date", [since, *ids]):
        wk = (date.fromisoformat(d) - timedelta(days=date.fromisoformat(d).weekday())).isoformat()
        per[(wk, kid)] = (bool(aio), None if cited is None else bool(cited))
    weeks_out: dict[str, dict] = {}
    for (wk, _), (aio, cited) in per.items():
        w = weeks_out.setdefault(wk, {"week": wk, "checked": 0, "aio": 0, "known": 0, "cited": 0})
        w["checked"] += 1
        w["aio"] += aio
        w["known"] += aio and cited is not None
        w["cited"] += bool(aio and cited)
    return [weeks_out[k] for k in sorted(weeks_out)]
