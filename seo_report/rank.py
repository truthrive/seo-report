"""Check rank thực tế qua DataForSEO cho các bộ từ khóa của dự án.

- Bộ từ khóa (tab ở màn Từ khóa & rank): mỗi bộ có nơi check riêng (vùng Google, thiết bị, vị trí, ngôn ngữ; để trống
  = theo dự án), lịch và độ sâu riêng. Bộ "Cam kết" tự khớp tab Từ khóa cam kết của sheet dự án; các bộ khác team tự
  tạo. Một từ khóa nằm ở nhiều bộ thì mỗi bộ check riêng (mỗi dòng rank_keywords là một từ khóa trong một bộ).
- Keyword đến từ: sheet cam kết, nhập tay, hoặc gắn ★ ở màn URL. URL mục tiêu và Top mục tiêu là tùy chọn.
- Lịch: các thứ trong tuần, một ngày trong tháng, hoặc chỉ khi bấm "Check ngay". Lỡ lịch (máy tắt) thì lần chạy sau
  check bù.
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


DEFAULT_SCHEDULE = {"type": "weekdays", "weekdays": [1], "day": 1, "depth": "auto"}  # thứ Ba, trước báo cáo thứ Năm

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
    UNIQUE (set_id, keyword)
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


def _set_row(r) -> dict:
    sid, site, name, kind, settings, schedule, pos = r
    return {"id": sid, "site": site, "name": name, "kind": kind,
            "settings": json.loads(settings) if settings else None,
            "schedule": {**DEFAULT_SCHEDULE, **json.loads(schedule)}, "position": pos}


def sets(con: sqlite3.Connection, site: str) -> list[dict]:
    """Các bộ của website: bộ Cam kết trước, rồi theo thứ tự tạo. Kèm số từ khóa ("count")."""
    ensure_tables(con)
    rows = con.execute("SELECT id, site, name, kind, settings, schedule, position FROM rank_sets WHERE site = ? "
                       "ORDER BY kind != 'kpi', position, id", (site,)).fetchall()
    counts = dict(con.execute("SELECT set_id, COUNT(*) FROM rank_keywords WHERE site = ? GROUP BY set_id", (site,)))
    return [{**_set_row(r), "count": counts.get(r[0], 0)} for r in rows]


def get_set(con: sqlite3.Connection, set_id: int) -> dict | None:
    ensure_tables(con)
    r = con.execute("SELECT id, site, name, kind, settings, schedule, position FROM rank_sets WHERE id = ?",
                    (set_id,)).fetchone()
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


def create_set(con: sqlite3.Connection, site: str, name: str, user: str, kind: str = "custom",
               settings: dict | None = None, schedule: dict | None = None) -> int:
    ensure_tables(con)
    name = " ".join((name or "").split())[:60]
    if not name:
        raise ValueError("Chưa nhập tên bộ từ khóa")
    if con.execute("SELECT 1 FROM rank_sets WHERE site = ? AND lower(name) = lower(?)", (site, name)).fetchone():
        raise ValueError(f"Đã có bộ tên “{name}”")
    pos = con.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM rank_sets WHERE site = ?", (site,)).fetchone()[0]
    with con:
        cur = con.execute("INSERT INTO rank_sets (site, name, kind, settings, schedule, position, created_by, "
                          "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (site, name, kind, _clean_settings(settings),
                           json.dumps({**DEFAULT_SCHEDULE, **(schedule or {})}), pos, user, _now()))
        U.log_change(con, user, site, "Tạo bộ từ khóa", None, name)
    return cur.lastrowid


def update_set(con: sqlite3.Connection, set_id: int, user: str, name: str | None = None,
               settings: dict | None | bool = False, schedule: dict | None = None) -> None:
    """Đổi tên (bộ Cam kết giữ tên), nơi check (settings=None: theo dự án; False: không đổi), lịch."""
    st = get_set(con, set_id)
    if not st:
        raise ValueError("Không có bộ từ khóa này")
    with con:
        if name is not None and st["kind"] != "kpi":
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
            con.execute("UPDATE rank_sets SET schedule = ? WHERE id = ?",
                        (json.dumps({**DEFAULT_SCHEDULE, **schedule}), set_id))
        U.log_change(con, user, st["site"], "Sửa bộ từ khóa", None, name or st["name"])


def delete_set(con: sqlite3.Connection, set_id: int, user: str) -> None:
    """Xóa một bộ team tạo (bộ Cam kết theo sheet thì không). Từ khóa trong bộ thôi được check; lịch sử rank vẫn
    nằm trong file dữ liệu."""
    st = get_set(con, set_id)
    if not st:
        raise ValueError("Không có bộ từ khóa này")
    if st["kind"] == "kpi":
        raise ValueError("Bộ Cam kết đi theo sheet dự án, không xóa được")
    with con:
        con.execute("DELETE FROM rank_keywords WHERE set_id = ?", (set_id,))
        con.execute("DELETE FROM rank_sets WHERE id = ?", (set_id,))
        U.log_change(con, user, st["site"], "Xóa bộ từ khóa", None, st["name"])


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
    if s["type"] == "weekdays":
        days = ", ".join(WEEKDAYS[d] for d in sorted(s["weekdays"])) or "chưa chọn thứ nào"
        return f"Hằng tuần vào {days}; {depth}"
    if s["type"] == "monthly":
        return f"Hằng tháng vào ngày {s['day']}; {depth}"
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

def keywords(con: sqlite3.Connection, site: str, end: date, set_id: int | None = None) -> list[dict]:
    """Từ khóa theo dõi (mọi bộ, hoặc một bộ) kèm bộ, lần check gần nhất, lần trước, vị trí tốt nhất, độ sâu dự kiến.
    Một từ khóa ở hai bộ là hai dòng (mỗi bộ check riêng)."""
    ensure_tables(con)
    by_set = {x["id"]: x for x in sets(con, site)}
    rows = con.execute(
        """SELECT k.id, k.keyword, k.url_id, u.url, k.source, k.added_by, k.added_at, k.set_id, k.top_target
           FROM rank_keywords k LEFT JOIN urls u ON u.id = k.url_id
           WHERE k.site = ? AND (? IS NULL OR k.set_id = ?) ORDER BY k.id""",
        (site, set_id, set_id)).fetchall()
    out = []
    for kid, kw, url_id, url, source, by, at, sid, top in rows:
        st = by_set.get(sid) or {"id": sid, "name": "", "kind": "custom", "settings": None,
                                 "schedule": DEFAULT_SCHEDULE}
        sched = st["schedule"]
        checks = con.execute(
            "SELECT check_date, rank, ranking_url, target_rank, depth FROM rank_checks WHERE keyword_id = ? "
            "ORDER BY check_date DESC LIMIT 2", (kid,)).fetchall()
        best = con.execute("SELECT MIN(rank) FROM rank_checks WHERE keyword_id = ?", (kid,)).fetchone()[0]
        last = checks[0] if checks else None
        prev = checks[1] if len(checks) > 1 else None
        out.append({
            "id": kid, "keyword": kw, "url_id": url_id, "target_url": url, "source": source, "added_by": by,
            "added_at": at, "best": best, "set_id": sid, "set_name": st["name"], "set_kind": st["kind"],
            "set": st, "top_target": top,
            "date": last[0] if last else None, "rank": last[1] if last else None,
            "ranking_url": last[2] if last else None, "target_rank": last[3] if last else None,
            "last_depth": last[4] if last else None, "prev": prev[1] if prev else None,
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
    from . import volume  # chi phí lấy volume keyword tính chung ngân sách DataForSEO
    return con.execute("SELECT COALESCE(SUM(cost), 0) FROM rank_tasks WHERE substr(check_date, 1, 7) = ?",
                       (month,)).fetchone()[0] + volume.spent_this_month(con, today)


def cost_by_month(con: sqlite3.Connection, months: list[str]) -> dict[str, dict]:
    """Chi phí DataForSEO theo tháng ("YYYY-MM"): {"rank", "volume", "checks" (số lượt check rank), "total"}."""
    ensure_tables(con)
    from . import volume
    volume.ensure_tables(con)
    out = {m: {"rank": 0.0, "volume": 0.0, "checks": 0, "total": 0.0} for m in months}
    for m, cost, n in con.execute("SELECT substr(check_date, 1, 7), SUM(cost), COUNT(*) FROM rank_tasks "
                                  "GROUP BY 1"):
        if m in out:
            out[m].update(rank=cost or 0.0, checks=n)
    for m, cost in con.execute("SELECT substr(run_at, 1, 7), SUM(cost) FROM volume_runs GROUP BY 1"):
        if m in out:
            out[m]["volume"] = cost or 0.0
    for v in out.values():
        v["total"] = v["rank"] + v["volume"]
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
            if total + per_kw > s.monthly_budget_usd:
                res["over_budget"].append(kw)
                continue
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
                                    "set_id != ?", (site, k["keyword"], st["id"])).fetchone()
            if elsewhere:
                con.execute("DELETE FROM rank_keywords WHERE id = ?", (k["id"],))
            else:
                dropped = named_set(con, site, DROPPED_SET_NAME, user, like=st)
                con.execute("UPDATE rank_keywords SET set_id = ?, source = 'manual' WHERE id = ?",
                            (dropped["id"], k["id"]))
            U.log_change(con, user, site, "Bỏ khỏi bộ Cam kết (sheet)", None, k["keyword"])
            res["moved"].append(k["keyword"])
    return res


def set_history(con: sqlite3.Connection, site: str, set_id: int, limit: int = 30) -> list[dict]:
    """Tăng trưởng của một bộ theo từng ngày check: số từ khóa Top 3 / 4–10 / 11–30 / ngoài top 30 (hoặc chưa thấy),
    vị trí trung bình (từ khóa có thứ hạng), số từ khóa lên / xuống / giữ nguyên so với lần check trước, tỷ lệ đạt Top
    mục tiêu. Mỗi ngày lấy lần check gần nhất (≤ ngày đó) của từng từ khóa trong bộ."""
    ensure_tables(con)
    kws = con.execute("SELECT id, top_target FROM rank_keywords WHERE set_id = ? AND site = ?",
                      (set_id, site)).fetchall()
    tops = dict(kws)
    if not tops:
        return []
    marks = ",".join("?" * len(tops))
    checks = con.execute(f"SELECT keyword_id, check_date, rank, depth FROM rank_checks WHERE keyword_id IN ({marks}) "
                         "ORDER BY check_date", list(tops)).fetchall()
    by_day: dict[str, list] = {}
    for kid, d, r, depth in checks:
        by_day.setdefault(d, []).append((kid, r, depth))
    state: dict[int, int | None] = {}
    out = []
    for d in sorted(by_day):
        before = dict(state)
        for kid, r, _ in by_day[d]:
            state[kid] = r
        ranks = list(state.values())
        ranked = [r for r in ranks if r is not None]
        up = down = same = 0
        for kid, r in state.items():
            if kid not in before:
                continue
            a, b = (before[kid] if before[kid] is not None else 999), (r if r is not None else 999)
            up, down, same = up + (b < a), down + (b > a), same + (b == a)
        with_target = [(state[k], t) for k, t in tops.items() if t and k in state]
        out.append({
            "date": d, "checked": len(state),
            "top3": sum(1 for r in ranked if r <= 3), "top10": sum(1 for r in ranked if 3 < r <= 10),
            "top30": sum(1 for r in ranked if 10 < r <= 30), "out": sum(1 for r in ranks if r is None or r > 30),
            "avg": round(sum(ranked) / len(ranked), 1) if ranked else None,
            "up": up, "down": down, "same": same,
            "target_total": len(with_target),
            "target_hit": sum(1 for r, t in with_target if r is not None and r <= t)})
    return out[-limit:]


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
    """Bỏ theo dõi; lịch sử rank vẫn giữ trong rank_checks."""
    with con:
        for kid in ids:
            kw = con.execute("SELECT keyword FROM rank_keywords WHERE id = ?", (kid,)).fetchone()
            con.execute("DELETE FROM rank_keywords WHERE id = ?", (kid,))
            U.log_change(con, user, site, "Bỏ keyword check rank", None, kw[0] if kw else "")


def toggle_star(con: sqlite3.Connection, site: str, s: RankSettings, end: date, url_id: int, query: str,
                user: str) -> tuple[bool, str]:
    """★ ở màn URL: thêm keyword GSC vào bộ team tạo đầu tiên (không tự gán URL mục tiêu: team gán ở màn Quản lý URL,
    hoặc lấy từ sheet cam kết), hoặc bỏ khỏi các bộ team tạo nếu đã theo dõi. Từ khóa cam kết bỏ ở sheet."""
    ensure_tables(con)
    rows = con.execute("SELECT k.id, s.kind FROM rank_keywords k JOIN rank_sets s ON s.id = k.set_id "
                       "WHERE k.site = ? AND lower(k.keyword) = lower(?)", (site, query)).fetchall()
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
    return {r[0].strip().lower() for r in con.execute("SELECT keyword FROM rank_keywords WHERE site = ?", (site,))}


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
        return self._call("GET", f"task_get/regular/{task_id}")["tasks"][0]

    def balance(self) -> float | None:
        req = Request("https://api.dataforseo.com/v3/appendix/user_data", headers=self.headers)
        resp = json.loads(urlopen(req, timeout=self.timeout).read())
        return resp["tasks"][0]["result"][0]["money"]["balance"]


def due(con: sqlite3.Connection, site: str, end: date, today: date) -> list[dict]:
    """Keyword cần check theo lịch của bộ chứa nó: chưa có lần check (hoặc task đang chờ) từ ngày theo lịch gần nhất."""
    out = []
    for k in keywords(con, site, end):
        sched_day = last_scheduled_day(k["set"]["schedule"], today)
        if sched_day is None:
            continue
        pending = con.execute("SELECT MAX(check_date) FROM rank_tasks WHERE keyword_id = ? AND status = 'posted'",
                              (k["id"],)).fetchone()[0]
        last = max(filter(None, [k["date"], pending]), default=None)
        if last is None or date.fromisoformat(last) < sched_day:
            out.append(k)
    return out


def post(con, site: str, s: RankSettings, client, todo: list[dict], today: date, log=print) -> int:
    if not todo:
        return 0
    batch_cost = sum(_pages(k["depth"]) for k in todo) * s.price_per_page
    spent = spent_this_month(con, today)
    if spent + batch_cost > s.monthly_budget_usd:
        log(f"Dừng check rank: đã dùng {usd(spent)} USD tháng này, lượt này cần {usd(batch_cost, 3)} USD, "
            f"vượt ngân sách {s.monthly_budget_usd:.0f} USD.")
        return 0
    tasks = []
    for k in todo:  # mỗi từ khóa check theo nơi check của bộ chứa nó
        w = settings_for(s, k.get("set"))
        tasks.append({"keyword": k["keyword"], "location_code": w.location_code, "language_code": w.language_code,
                      "device": w.device, "se_domain": w.se_domain, "depth": k["depth"], "tag": str(k["id"])})
    posted, errors = 0, {}
    with con:
        for k, t in zip(todo, client.post(tasks)):
            if t.get("status_code") != 20100:
                errors.setdefault(t.get("status_message") or str(t.get("status_code")), []).append(k["keyword"])
                continue
            con.execute("INSERT INTO rank_tasks VALUES (?, ?, ?, ?, ?, ?, 'posted')",
                        (t["id"], k["id"], k["depth"], today.isoformat(), _now(), t.get("cost", 0)))
            posted += 1
    for message, kws in errors.items():  # gộp: thường mọi keyword cùng một lỗi tài khoản
        log(f"Không gửi được {len(kws)} keyword ({', '.join(kws[:3])}{'…' if len(kws) > 3 else ''}): {message}")
    if posted:
        log(f"Đã gửi {posted} keyword để check rank, khoảng {usd(batch_cost, 3)} USD.")
    return posted


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
            con.execute("UPDATE rank_tasks SET status = 'done' WHERE task_id = ?", (task_id,))
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
    changed = 0
    for task_id, kid, check_date, target, old_rank, old_url, old_target in rows:
        try:
            task = client.get(task_id)
        except Exception as e:  # noqa: BLE001
            log(f"Không đọc lại được task {task_id}: {e}")
            continue
        if task.get("status_code") != 20000:
            continue
        new = parse_rank(task, site, target)
        if new != (old_rank, old_url, old_target):
            with con:
                con.execute("UPDATE rank_checks SET rank = ?, ranking_url = ?, target_rank = ? "
                            "WHERE keyword_id = ? AND check_date = ?", (*new, kid, check_date))
            changed += 1
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
    today = today or date.today()
    collect(con, site, client, log)
    if only_ids is not None:
        todo = [k for k in keywords(con, site, end) if k["id"] in set(only_ids)]
    else:
        todo = due(con, site, end, today)
    post(con, site, s, client, todo, today, log)
    wait_and_collect(con, site, client, wait_minutes, log, sleep)
