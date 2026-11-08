"""Báo cáo công việc: đọc OKRs và Weekly Task Tracker từ Google Sheet của team (chỉ đọc; sheet vẫn là nơi cập nhật).

Đọc qua Google Sheets API (quyền spreadsheets.readonly). Khi chưa cấp quyền, dùng tạm bản xuất CSV công khai nếu sheet
đang để "ai có link đều xem được".

Mỗi tab có tên bắt đầu bằng "OKRs" là một đợt OKR (ví dụ "OKRs 3 tháng", "OKRs Q1-2027"); thêm đợt mới = thêm tab
mới cùng định dạng. Mã hạng mục trùng giữa hai đợt vẫn được phân biệt (khóa nội bộ uid = "<tên tab>|<mã>").

Dữ liệu chép vào SQLite mỗi lần đồng bộ, kèm ảnh chụp trạng thái theo ngày (okr_status_log). Sheet không có cột ngày
hoàn thành, nên "hoàn thành trong kỳ" lấy ngày đầu tiên tool thấy trạng thái Hoàn thành; việc đã xong trước ngày tool
bắt đầu theo dõi thì không biết ngày xong thật (ghi rõ trên màn).
"""
import csv
import io
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS okr_items (
    uid TEXT PRIMARY KEY,       -- mã hạng mục, thêm "<đợt>|" phía trước khi mã trùng giữa các đợt
    cycle TEXT NOT NULL,        -- tên tab OKR (một đợt 3 tháng)
    code TEXT NOT NULL,
    objective TEXT NOT NULL,    -- uid của mục tiêu cha
    is_objective INTEGER NOT NULL,
    grp TEXT, title TEXT, details TEXT, qty TEXT, unit TEXT, month_text TEXT,
    start TEXT, end TEXT, pic TEXT, status TEXT, status_raw TEXT, progress REAL, link TEXT, note TEXT, sort INTEGER
);
CREATE TABLE IF NOT EXISTS okr_tasks (
    row INTEGER PRIMARY KEY,
    week TEXT, kind TEXT, okr_code TEXT, item TEXT, task TEXT, link TEXT, issue TEXT, pic TEXT, priority TEXT,
    start TEXT, deadline TEXT, status TEXT, status_raw TEXT, progress REAL, note TEXT
);
CREATE TABLE IF NOT EXISTS okr_status_log (
    day TEXT NOT NULL, code TEXT NOT NULL, status TEXT NOT NULL,
    PRIMARY KEY (day, code)
);
CREATE TABLE IF NOT EXISTS okr_extensions (  -- mỗi lần gia hạn một hạng mục: hạn cũ → hạn mới
    id INTEGER PRIMARY KEY, uid TEXT NOT NULL, old_end TEXT, new_end TEXT NOT NULL, at TEXT NOT NULL,
    by TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS okr_cycles (     -- đợt OKR do tool quản lý (khi OKR đã chuyển sang tool)
    name TEXT PRIMARY KEY, start TEXT, end TEXT, sort INTEGER NOT NULL DEFAULT 0
);
"""
DONE, DOING, TODO, OTHER = "done", "doing", "todo", "other"
STATUS_LABEL = {DONE: "Hoàn thành", DOING: "Đang làm", TODO: "Chưa bắt đầu", OTHER: "Khác"}
CODE_RE = re.compile(r"^O\d+(\.\d+)?$")


@dataclass
class OkrSettings:
    sheet: str = ""  # link hoặc ID của Google Sheet
    okr_tab: str = "OKRs 3 tháng"
    weekly_tab: str = "Weekly Task Tracker"


def sheet_id(sheet: str) -> str:
    m = re.search(r"/d/([A-Za-z0-9_-]+)", sheet or "")
    return m.group(1) if m else (sheet or "").strip()


def norm_status(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return TODO
    if "hoàn thành" in t or "xong" in t or "done" in t:
        return DONE
    if "đang" in t or "doing" in t or "progress" in t:
        return DOING
    if "chưa" in t or "todo" in t or "not" in t:
        return TODO
    return OTHER


def parse_date(value, today: date) -> date | None:
    """Ngày từ ô sheet: số serial của Sheets, "dd/mm/yyyy", hoặc "Thứ Ba, 13 /10" (thiếu năm: lấy năm gần hôm nay
    nhất), "Thứ Hai, 12 thg 10,26"."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return date(1899, 12, 30) + timedelta(days=int(value))
    s = str(value).strip()
    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2,4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe(y + 2000 if y < 100 else y, mo, d)
    m = re.search(r"(\d{1,2})\s*thg\s*(\d{1,2})\s*,?\s*(\d{2,4})?", s)
    if not m:
        m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})(?!\s*/)", s)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = m.group(3) if m.lastindex and m.lastindex >= 3 else None
        if y:
            return _safe(int(y) + 2000 if int(y) < 100 else int(y), mo, d)
        cands = [c for c in (_safe(today.year + k, mo, d) for k in (-1, 0, 1)) if c]
        return min(cands, key=lambda c: abs((c - today).days)) if cands else None
    return None


def _safe(y, m, d) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _pct(value) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value) * (100 if value <= 1 else 1)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%?", str(value))
    return float(m.group(1).replace(",", ".")) if m else None


# ---- Đọc sheet ----

def fetch_tables(cfg) -> tuple[dict[str, list[list]], str]:
    """{tên tab: các dòng} và nguồn ("api" / "public"). Thử API trước, không có quyền thì thử bản CSV công khai."""
    sid = sheet_id(cfg.okr.sheet)
    if not sid:
        raise SystemExit("Chưa khai báo sheet OKR: gắn link sheet cho dự án ở màn Dự án")
    try:
        return _fetch_api(cfg, sid), "api"
    except (Exception, SystemExit) as e:  # noqa: BLE001  (chưa cấp quyền / chưa bật API: thử bản công khai)
        api_error = str(e)[:200]
    try:
        return _fetch_public(cfg, sid), "public"
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("Không đọc được sheet. Cần cấp quyền Google Sheets (chạy python -m seo_report login và "
                           "bật Google Sheets API), hoặc để sheet ở chế độ ai có link đều xem được. "
                           f"Lỗi API: {api_error}. Lỗi đọc công khai: {e}") from e


def okr_tab_names(titles: list[str], cfg) -> list[str]:
    """Các tab OKR theo thứ tự trong sheet: tên bắt đầu bằng "OKR" (hoặc đúng tên okr_tab), trừ tab Weekly."""
    weekly = cfg.okr.weekly_tab.strip().lower()
    want = cfg.okr.okr_tab.strip().lower()
    return [t for t in titles if t.strip().lower() != weekly and
            (t.strip().lower() == want or t.strip().lower().startswith("okr"))]


def _fetch_api(cfg, sid: str) -> dict[str, list[list]]:
    from googleapiclient.discovery import build

    from . import auth
    creds = auth.get_credentials(cfg, need=(auth.SHEETS_SCOPE,))
    svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
    meta = svc.spreadsheets().get(spreadsheetId=sid, fields="sheets(properties(title))").execute()
    titles = [s["properties"]["title"] for s in meta["sheets"]]
    out = {}
    weekly = next((t for t in titles if t.strip().lower() == cfg.okr.weekly_tab.strip().lower()), None)
    for title in okr_tab_names(titles, cfg) + ([weekly] if weekly else []):
        rng = "'" + title.replace("'", "''") + "'!A1:Z500"
        resp = svc.spreadsheets().values().get(spreadsheetId=sid, range=rng, valueRenderOption="UNFORMATTED_VALUE",
                                               dateTimeRenderOption="SERIAL_NUMBER").execute()
        out[cfg.okr.weekly_tab if title == weekly else title.strip()] = resp.get("values", [])
    return out


def _fetch_public(cfg, sid: str) -> dict[str, list[list]]:
    """Bản xuất CSV của từng tab (chỉ được khi sheet để công khai). Tìm gid của tab theo tên trong trang htmlview."""
    page = urllib.request.urlopen(f"https://docs.google.com/spreadsheets/d/{sid}/htmlview", timeout=30).read().decode(
        "utf-8", "replace")
    tabs = {name.strip(): gid for name, gid in re.findall(r'name: "([^"]+)", pageUrl: "[^"]*?gid=(\d+)', page)}
    weekly = next((t for t in tabs if t.lower() == cfg.okr.weekly_tab.strip().lower()), None)
    out = {}
    for title in okr_tab_names(list(tabs), cfg) + ([weekly] if weekly else []):
        url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={tabs[title]}"
        text = urllib.request.urlopen(url, timeout=30).read().decode("utf-8")
        out[cfg.okr.weekly_tab if title == weekly else title] = list(csv.reader(io.StringIO(text)))
    if not out:
        raise RuntimeError("không tìm thấy tab hoặc sheet không công khai")
    return out


# ---- Chuẩn hóa ----

def _cols(rows: list[list], must: str) -> tuple[int, dict[str, int]]:
    """Tìm dòng tiêu đề (dòng có ô `must`) và vị trí các cột theo tên."""
    for i, r in enumerate(rows[:10]):
        names = [str(c).strip().lower() for c in r]
        if must in names:
            return i, {n: j for j, n in enumerate(names) if n}
    raise ValueError(f"Không thấy dòng tiêu đề có cột '{must}'")


def _get(row, idx: dict, *names):
    for n in names:
        j = idx.get(n)
        if j is not None and j < len(row) and row[j] not in (None, ""):
            return row[j]
    return None


def parse_okr(rows: list[list], today: date) -> list[dict]:
    h, idx = _cols(rows, "id")
    out, objective = [], None
    for k, r in enumerate(rows[h + 1:]):
        code = str(_get(r, idx, "id") or "").strip()
        if not CODE_RE.match(code):
            continue
        is_obj = "." not in code
        if is_obj:
            objective = code
        start = parse_date(_get(r, idx, "start date"), today)
        end = parse_date(_get(r, idx, "end date"), today)
        status_raw = str(_get(r, idx, "trạng thái") or "").strip()
        out.append({
            "code": code, "objective": code if is_obj else (objective or code.split(".")[0]),
            "is_objective": is_obj, "grp": str(_get(r, idx, "nhóm") or ""),
            "title": str(_get(r, idx, "hạng mục công việc") or ""), "details": str(_get(r, idx, "task details") or ""),
            "qty": str(_get(r, idx, "số lượng") or ""), "unit": str(_get(r, idx, "đơn vị") or ""),
            "month_text": str(_get(r, idx, "tháng dự kiến") or ""),
            "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
            "pic": str(_get(r, idx, "pic") or ""), "status": norm_status(status_raw) if not is_obj else "",
            "status_raw": status_raw, "progress": _pct(_get(r, idx, "% tiến độ")),
            "link": str(_get(r, idx, "link / evidence") or ""), "note": str(_get(r, idx, "cảnh báo") or ""),
            "sort": k,
        })
    return out


def parse_weekly(rows: list[list], today: date) -> list[dict]:
    """Ô "Ngày" chỉ ghi ở dòng đầu mỗi tuần: các dòng dưới dùng lại tuần đó. Dòng mẫu trống (không có task, không có
    mã OKR) bị bỏ."""
    h, idx = _cols(rows, "ngày")
    out, week = [], None
    for k, r in enumerate(rows[h + 1:], start=h + 2):
        d = parse_date(_get(r, idx, "ngày"), today)
        if d:
            week = d - timedelta(days=d.weekday())
        task = str(_get(r, idx, "task tuần / hành động") or "").strip()
        code = str(_get(r, idx, "mã okr") or "").strip()
        if not task and not code:
            continue
        start = parse_date(_get(r, idx, "start date"), today)
        deadline = parse_date(_get(r, idx, "deadline"), today)
        status_raw = str(_get(r, idx, "trạng thái") or "").strip()
        out.append({
            "row": k, "week": week.isoformat() if week else None, "kind": str(_get(r, idx, "loại task") or ""),
            "okr_code": code, "item": str(_get(r, idx, "hạng mục liên kết") or ""), "task": task,
            "link": str(_get(r, idx, "link / evidence") or ""), "issue": str(_get(r, idx, "vướn mắc", "vướng mắc") or ""),
            "pic": str(_get(r, idx, "pic") or ""), "priority": str(_get(r, idx, "ưu tiên") or ""),
            "start": start.isoformat() if start else None, "deadline": deadline.isoformat() if deadline else None,
            "status": norm_status(status_raw), "status_raw": status_raw,
            "progress": _pct(_get(r, idx, "% tiến độ")), "note": str(_get(r, idx, "blocker / ghi chú") or ""),
        })
    return out


# ---- Lưu, đồng bộ ----

def ensure_tables(con: sqlite3.Connection) -> None:
    cols = [r[1] for r in con.execute("PRAGMA table_info(okr_items)")]
    if cols and "uid" not in cols:  # bảng kiểu cũ (một đợt): dữ liệu lấy lại từ sheet mỗi lần đồng bộ nên tạo lại
        con.execute("DROP TABLE okr_items")
    con.executescript(SCHEMA)


def combine(cycles: list[tuple[str, list[dict]]]) -> list[dict]:
    """Gộp hạng mục của nhiều đợt (tab). uid = mã; mã xuất hiện ở hơn một đợt thì uid = "<đợt>|<mã>"."""
    seen: dict[str, int] = {}
    for _, its in cycles:
        for code in {i["code"] for i in its}:
            seen[code] = seen.get(code, 0) + 1
    out, sort = [], 0
    for name, its in cycles:
        uid = {i["code"]: (f"{name}|{i['code']}" if seen[i["code"]] > 1 else i["code"]) for i in its}
        for i in its:
            out.append({**i, "uid": uid[i["code"]], "cycle": name, "sort": sort,
                        "objective": uid.get(i["objective"], i["objective"])})
            sort += 1
    return out


def save(con: sqlite3.Connection, items: list[dict], tasks: list[dict], today: date, source: str) -> None:
    ensure_tables(con)
    if items and "uid" not in items[0]:  # hạng mục của một tab chưa gộp: coi là một đợt
        items = combine([("OKRs 3 tháng", items)])
    with con:
        con.execute("DELETE FROM okr_items")
        con.executemany(
            "INSERT INTO okr_items VALUES (:uid, :cycle, :code, :objective, :is_objective, :grp, :title, :details, :qty, :unit, "
            ":month_text, :start, :end, :pic, :status, :status_raw, :progress, :link, :note, :sort)", items)
        con.execute("DELETE FROM okr_tasks")
        con.executemany(
            "INSERT INTO okr_tasks VALUES (:row, :week, :kind, :okr_code, :item, :task, :link, :issue, :pic, "
            ":priority, :start, :deadline, :status, :status_raw, :progress, :note)", tasks)
        con.executemany("INSERT OR REPLACE INTO okr_status_log VALUES (?, ?, ?)",
                        [(today.isoformat(), i["uid"], i["status"]) for i in items if not i["is_objective"]])
        con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT OR REPLACE INTO app_settings VALUES ('okr_synced', ?)", (json.dumps(
            {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source,
             "items": len(items), "tasks": len(tasks)}),))


def save_tasks(con: sqlite3.Connection, tasks: list[dict], source: str) -> None:
    """Chỉ thay task tuần (OKR đã do tool quản lý: không đụng hạng mục OKR)."""
    ensure_tables(con)
    with con:
        con.execute("DELETE FROM okr_tasks")
        con.executemany(
            "INSERT INTO okr_tasks VALUES (:row, :week, :kind, :okr_code, :item, :task, :link, :issue, :pic, "
            ":priority, :start, :deadline, :status, :status_raw, :progress, :note)", tasks)
        n_items = con.execute("SELECT COUNT(*) FROM okr_items").fetchone()[0]
        con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT OR REPLACE INTO app_settings VALUES ('okr_synced', ?)", (json.dumps(
            {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source,
             "items": n_items, "tasks": len(tasks), "weekly_only": True}),))


def sync(con: sqlite3.Connection, cfg, today: date | None = None) -> dict:
    today = today or date.today()
    tables, source = fetch_tables(cfg)
    if tool_owned(con):  # OKR sửa trên tool: chỉ đọc tab Weekly Task Tracker từ sheet
        weekly = tables.get(cfg.okr.weekly_tab) or []
        tasks = parse_weekly(weekly, today) if weekly else []
        save_tasks(con, tasks, source)
        n_items = con.execute("SELECT COUNT(*) FROM okr_items WHERE is_objective = 0").fetchone()[0]
        return {"items": n_items, "tasks": len(tasks), "source": source, "cycles": [], "weekly_only": True}
    cycles = [(name, parse_okr(rows, today)) for name, rows in tables.items()
               if name != cfg.okr.weekly_tab and rows]
    items = combine(cycles)
    tasks = parse_weekly(tables.get(cfg.okr.weekly_tab, []), today) if tables.get(cfg.okr.weekly_tab) else []
    save(con, items, tasks, today, source)
    return {"items": len(items), "tasks": len(tasks), "source": source, "cycles": [n for n, _ in cycles]}


def sync_info(con: sqlite3.Connection) -> dict | None:
    con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    row = con.execute("SELECT value FROM app_settings WHERE key = 'okr_synced'").fetchone()
    return json.loads(row[0]) if row else None


# ---- Đọc để hiển thị / báo cáo ----

def items(con: sqlite3.Connection) -> list[dict]:
    ensure_tables(con)
    cur = con.execute("SELECT * FROM okr_items ORDER BY sort")
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def tasks(con: sqlite3.Connection) -> list[dict]:
    ensure_tables(con)
    cur = con.execute("SELECT * FROM okr_tasks ORDER BY row")
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def done_dates(con: sqlite3.Connection) -> dict[str, str]:
    """Ngày đầu tiên tool thấy từng hạng mục ở trạng thái Hoàn thành."""
    ensure_tables(con)
    return dict(con.execute("SELECT code, MIN(day) FROM okr_status_log WHERE status = ? GROUP BY code", (DONE,)))


def first_snapshot(con: sqlite3.Connection) -> str | None:
    ensure_tables(con)
    return con.execute("SELECT MIN(day) FROM okr_status_log").fetchone()[0]


def cycles(all_items: list[dict], today: date) -> list[dict]:
    """Các đợt OKR: tên, ngày bắt đầu/kết thúc (theo hạng mục), có phải đợt hiện tại."""
    out = []
    for name in dict.fromkeys(i["cycle"] for i in all_items):
        its = [i for i in all_items if i["cycle"] == name]
        starts = [i["start"] for i in its if i["start"]]
        ends = [i["end"] for i in its if i["end"]]
        out.append({"name": name, "start": min(starts) if starts else None, "end": max(ends) if ends else None})
    return out


def cycle_at(cs: list[dict], day: date) -> str | None:
    """Đợt chứa ngày `day`; không có thì đợt gần nhất đã bắt đầu; chưa đợt nào bắt đầu thì đợt đầu tiên."""
    if not cs:
        return None
    d = day.isoformat()
    inside = [c for c in cs if c["start"] and c["end"] and c["start"] <= d <= c["end"]]
    if inside:
        return inside[-1]["name"]
    started = [c for c in cs if c["start"] and c["start"] <= d]
    return (max(started, key=lambda c: c["start"]) if started else cs[0])["name"]


def is_late(it: dict, today: date) -> bool:
    return bool(it.get("end") and it["status"] != DONE and date.fromisoformat(it["end"]) < today)


def overview(con: sqlite3.Connection, today: date, period: tuple[date, date] | None = None,
             cycle: str | None = None) -> dict:
    """Số tổng, theo mục tiêu, và danh sách cho một kỳ (tuần/tháng): đến hạn trong kỳ, hoàn thành trong kỳ, trễ hạn,
    kỳ tới. Chỉ tính một đợt OKR: `cycle`, mặc định đợt chứa cuối kỳ (hoặc hôm nay)."""
    every = items(con)
    cs = cycle_list(con, every, today)
    cycle = cycle if cycle in {c["name"] for c in cs} else cycle_at(cs, period[1] if period else today)
    all_items = [i for i in every if i["cycle"] == cycle]
    objs = [i for i in all_items if i["is_objective"]]
    leaf = [i for i in all_items if not i["is_objective"]]
    counts = {s: sum(1 for i in leaf if i["status"] == s) for s in (DONE, DOING, TODO, OTHER)}
    late = [i for i in leaf if is_late(i, today)]
    per_obj = []
    for o in objs:
        kids = [i for i in leaf if i["objective"] == o["uid"]]
        done = sum(1 for i in kids if i["status"] == DONE)
        per_obj.append({**o, "total": len(kids), "done": done, "doing": sum(1 for i in kids if i["status"] == DOING),
                        "late": sum(1 for i in kids if is_late(i, today)),
                        "pct": done / len(kids) if kids else None})
    out = {"total": len(leaf), "counts": counts, "late": late, "objectives": per_obj, "items": leaf,
           "cycle": cycle, "cycles": cs}
    if period:
        s, e = period
        dd = done_dates(con)
        first = first_snapshot(con)
        nxt = (e + timedelta(days=1), e + timedelta(days=(e - s).days + 1))

        def overlaps(i, a, b):
            return i["start"] and i["end"] and i["start"] <= b.isoformat() and i["end"] >= a.isoformat()

        out["period"] = {
            "due": [i for i in leaf if i["end"] and s.isoformat() <= i["end"] <= e.isoformat()],
            "active": [i for i in leaf if overlaps(i, s, e)],
            # Xong trước khi tool bắt đầu theo dõi (thấy "Hoàn thành" ngay lần chụp đầu) thì không biết ngày xong:
            # chỉ tính vào kỳ nếu ngày kết thúc kế hoạch nằm trong kỳ.
            "done": [i for i in leaf if i["status"] == DONE and dd.get(i["uid"]) and (
                (dd[i["uid"]] != first and s.isoformat() <= dd[i["uid"]] <= e.isoformat()) or
                (dd[i["uid"]] == first and i["end"] and s.isoformat() <= i["end"] <= e.isoformat()))],
            "next": [i for i in leaf if i["status"] != DONE and overlaps(i, *nxt)],
            "tracking_since": first,
        }
    return out


# ---- OKR do tool quản lý (tạo / sửa trên tool, tool ghi đè tab OKRs trên sheet dự án) ----

STATUSES = (TODO, DOING, DONE)  # trạng thái chọn trên tool
FIELDS = ("grp", "title", "details", "qty", "unit", "month_text", "start", "end", "pic", "status", "progress", "link",
          "note")


def _setting(con, key: str, value: str | None = None) -> str | None:
    con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if value is None:
        row = con.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    with con:
        con.execute("INSERT OR REPLACE INTO app_settings VALUES (?, ?)", (key, value))
    return value


def tool_owned(con) -> bool:
    """OKR đã chuyển sang tool: tạo / sửa trên tool, sheet chỉ là nơi xem (tool ghi đè)."""
    return _setting(con, "okr_source") == "tool"


def changed_at(con) -> str:
    """Mốc đổi gần nhất của OKR trên tool (để biết cần ghi lại tab OKRs lên sheet)."""
    return _setting(con, "okr_changed") or ""


def _touch(con) -> None:
    _setting(con, "okr_changed", datetime.now(timezone.utc).isoformat(timespec="microseconds"))


def take_over(con, today: date | None = None) -> dict:
    """Chuyển OKR sang tool: giữ nguyên hạng mục đã đồng bộ từ sheet làm điểm khởi đầu, tạo danh sách đợt (ngày đợt =
    ngày sớm nhất / muộn nhất của hạng mục). Từ đây đồng bộ chỉ còn đọc task tuần."""
    today = today or date.today()
    ensure_tables(con)
    every = items(con)
    with con:
        for k, c in enumerate(cycles(every, today)):
            con.execute("INSERT OR IGNORE INTO okr_cycles (name, start, end, sort) VALUES (?, ?, ?, ?)",
                        (c["name"], c["start"], c["end"], k))
    _setting(con, "okr_source", "tool")
    _touch(con)
    return {"cycles": len(cycles(every, today)), "items": len(every)}


def cycle_list(con, every: list[dict] | None = None, today: date | None = None) -> list[dict]:
    """Các đợt: OKR do tool quản lý thì lấy từ bảng okr_cycles (có cả đợt chưa có hạng mục), không thì suy từ hạng mục."""
    ensure_tables(con)
    every = items(con) if every is None else every
    if not tool_owned(con):
        return cycles(every, today or date.today())
    rows = con.execute("SELECT name, start, end FROM okr_cycles ORDER BY start IS NULL, start, sort, name").fetchall()
    return [{"name": n, "start": s_, "end": e_} for n, s_, e_ in rows]


def cycle_ids(con) -> dict[str, int]:
    """{tên đợt: mã cố định (rowid)}: đổi tên đợt vẫn ghi đúng tab cũ trên sheet."""
    ensure_tables(con)
    return {n: i for i, n in con.execute("SELECT rowid, name FROM okr_cycles")}


def add_cycle(con, name: str, start: str | None, end: str | None, copy_from: str | None = None) -> None:
    """Thêm đợt; copy_from: chép mục tiêu + hạng mục của đợt đó (trạng thái về Chưa bắt đầu, ngày dời theo đợt mới)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Cần tên đợt")
    if start and end and start > end:
        raise ValueError("Ngày bắt đầu sau ngày kết thúc")
    ensure_tables(con)
    if con.execute("SELECT 1 FROM okr_cycles WHERE lower(name) = lower(?)", (name,)).fetchone():
        raise ValueError(f"Đã có đợt tên “{name}”")
    sort = (con.execute("SELECT MAX(sort) FROM okr_cycles").fetchone()[0] or 0) + 1
    with con:
        con.execute("INSERT INTO okr_cycles (name, start, end, sort) VALUES (?, ?, ?, ?)", (name, start, end, sort))
    if copy_from:
        src = [i for i in items(con) if i["cycle"] == copy_from]
        src_start = con.execute("SELECT start FROM okr_cycles WHERE name = ?", (copy_from,)).fetchone()
        shift = (date.fromisoformat(start) - date.fromisoformat(src_start[0])) if start and src_start and src_start[0] \
            else timedelta(0)

        def moved(d):
            return (date.fromisoformat(d) + shift).isoformat() if d else None
        uid_map: dict[str, str] = {}
        for i in [x for x in src if x["is_objective"]] + [x for x in src if not x["is_objective"]]:
            new_uid = _free_uid(con, name, i["code"])
            uid_map[i["uid"]] = new_uid
            _insert(con, {**i, "uid": new_uid, "cycle": name, "objective": uid_map.get(i["objective"], new_uid),
                          "start": moved(i["start"]), "end": moved(i["end"]),
                          "status": "" if i["is_objective"] else TODO, "status_raw": "", "progress": None})
    _touch(con)


def update_cycle(con, old: str, name: str, start: str | None, end: str | None) -> None:
    name = (name or "").strip()
    if not name:
        raise ValueError("Cần tên đợt")
    if start and end and start > end:
        raise ValueError("Ngày bắt đầu sau ngày kết thúc")
    if name.lower() != old.lower() and con.execute("SELECT 1 FROM okr_cycles WHERE lower(name) = lower(?)",
                                                   (name,)).fetchone():
        raise ValueError(f"Đã có đợt tên “{name}”")
    with con:
        con.execute("UPDATE okr_cycles SET name = ?, start = ?, end = ? WHERE name = ?", (name, start, end, old))
        con.execute("UPDATE okr_items SET cycle = ? WHERE cycle = ?", (name, old))
    _touch(con)


def delete_cycle(con, name: str) -> None:
    with con:
        con.execute("DELETE FROM okr_items WHERE cycle = ?", (name,))
        con.execute("DELETE FROM okr_cycles WHERE name = ?", (name,))
    _touch(con)


def _free_uid(con, cycle: str, code: str) -> str:
    for uid in (code, f"{cycle}|{code}"):
        if not con.execute("SELECT 1 FROM okr_items WHERE uid = ?", (uid,)).fetchone():
            return uid
    k = 2
    while con.execute("SELECT 1 FROM okr_items WHERE uid = ?", (f"{cycle}|{code}#{k}",)).fetchone():
        k += 1
    return f"{cycle}|{code}#{k}"


def _insert(con, it: dict) -> None:
    sort = it.get("sort")
    if sort is None:
        sort = (con.execute("SELECT MAX(sort) FROM okr_items").fetchone()[0] or 0) + 1
    with con:
        con.execute("INSERT INTO okr_items (uid, cycle, code, objective, is_objective, grp, title, details, qty, unit, "
                    "month_text, start, end, pic, status, status_raw, progress, link, note, sort) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (it["uid"], it["cycle"], it["code"], it["objective"], int(bool(it["is_objective"])),
                     it.get("grp") or "", it.get("title") or "", it.get("details") or "", it.get("qty") or "",
                     it.get("unit") or "", it.get("month_text") or "", it.get("start"), it.get("end"),
                     it.get("pic") or "", it.get("status") or "", it.get("status_raw") or "", it.get("progress"),
                     it.get("link") or "", it.get("note") or "", sort))


def _resort(con, cycle: str) -> None:
    """Thứ tự hiển thị: mục tiêu theo số, hạng mục ngay dưới mục tiêu của nó theo số (O1, O1.1, O1.2, O2…)."""
    def key(code: str):
        return tuple(int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", code))
    rows = con.execute("SELECT uid, code, sort FROM okr_items WHERE cycle = ?", (cycle,)).fetchall()
    base = min((s_ for *_, s_ in rows), default=0)
    with con:
        for k, (uid, code, _) in enumerate(sorted(rows, key=lambda r: key(r[1]))):
            con.execute("UPDATE okr_items SET sort = ? WHERE uid = ?", (base + k, uid))


def add_objective(con, cycle: str, title: str) -> str:
    title = (title or "").strip()
    if not title:
        raise ValueError("Cần tên mục tiêu")
    nums = [int(c[1:]) for (c,) in con.execute("SELECT code FROM okr_items WHERE cycle = ? AND is_objective = 1",
                                               (cycle,)) if c[1:].isdigit()]
    code = f"O{max(nums, default=0) + 1}"
    uid = _free_uid(con, cycle, code)
    _insert(con, {"uid": uid, "cycle": cycle, "code": code, "objective": uid, "is_objective": True, "title": title,
                  "status": ""})
    _resort(con, cycle)
    _touch(con)
    return uid


def add_item(con, objective_uid: str, title: str, **fields) -> str:
    title = (title or "").strip()
    if not title:
        raise ValueError("Cần tên hạng mục")
    row = con.execute("SELECT cycle, code FROM okr_items WHERE uid = ? AND is_objective = 1",
                      (objective_uid,)).fetchone()
    if not row:
        raise ValueError("Không thấy mục tiêu")
    cycle, ocode = row
    nums = [int(c.split(".")[1]) for (c,) in con.execute(
        "SELECT code FROM okr_items WHERE objective = ? AND is_objective = 0", (objective_uid,))
        if "." in c and c.split(".")[1].isdigit()]
    code = f"{ocode}.{max(nums, default=0) + 1:02d}"
    uid = _free_uid(con, cycle, code)
    status = fields.get("status") if fields.get("status") in STATUSES else TODO
    if not fields.get("start") and not fields.get("end"):  # chưa có ngày: mặc định cả đợt (sửa sau)
        c = con.execute("SELECT start, end FROM okr_cycles WHERE name = ?", (cycle,)).fetchone()
        if c:
            fields = {**fields, "start": c[0], "end": c[1]}
    _insert(con, {**{k: v for k, v in fields.items() if k in FIELDS}, "uid": uid, "cycle": cycle, "code": code,
                  "objective": objective_uid, "is_objective": False, "title": title, "status": status,
                  "status_raw": STATUS_LABEL[status]})
    _resort(con, cycle)
    _touch(con)
    return uid


def update_item(con, uid: str, today: date | None = None, **fields) -> None:
    """Sửa các trường của mục tiêu / hạng mục. Đổi trạng thái thì ghi nhật ký ngày (để biết ngày hoàn thành)."""
    fields = {k: v for k, v in fields.items() if k in FIELDS}
    if "title" in fields and not (fields["title"] or "").strip():
        raise ValueError("Tên không được để trống")
    if fields.get("start") and fields.get("end") and fields["start"] > fields["end"]:
        raise ValueError("Ngày bắt đầu sau ngày kết thúc")
    if "status" in fields:
        if fields["status"] not in STATUSES:
            raise ValueError("Trạng thái không hợp lệ")
        fields["status_raw"] = STATUS_LABEL[fields["status"]]
        if fields["status"] == DONE and "progress" not in fields:
            fields["progress"] = 100.0
    if "progress" in fields and fields["progress"] not in (None, ""):
        fields["progress"] = max(0.0, min(100.0, float(fields["progress"])))
    if not fields:
        return
    with con:
        con.execute(f"UPDATE okr_items SET {', '.join(f'{k} = ?' for k in fields)} WHERE uid = ?",
                    (*fields.values(), uid))
        if "status" in fields:
            con.execute("INSERT OR REPLACE INTO okr_status_log VALUES (?, ?, ?)",
                        ((today or date.today()).isoformat(), uid, fields["status"]))
    _touch(con)


def delete_item(con, uid: str) -> None:
    """Xóa hạng mục; xóa mục tiêu thì xóa luôn các hạng mục của nó."""
    with con:
        con.execute("DELETE FROM okr_items WHERE uid = ? OR (objective = ? AND is_objective = 0)", (uid, uid))
    _touch(con)


# ---- Tab OKR trên sheet dự án ----

SHEET_HEAD = ["ID", "Nhóm", "Hạng mục công việc", "Task details", "Số lượng", "Đơn vị", "Tháng dự kiến", "Start date",
              "End date", "PIC", "Trạng thái", "% Tiến độ", "Link / Evidence", "Cảnh báo"]


def tab_title(cycle: str) -> str:
    bad = "[]*?/\\:"
    clean = "".join("-" if ch in bad else ch for ch in cycle).strip()
    return (clean if clean.lower().startswith("okr") else f"OKRs {clean}")[:90]


def sheet_rows(con, cycle: str, note: str, stamp: str, today: date | None = None) -> list[list]:
    """Các ô của tab OKR một đợt (cột giống tab OKR cũ của team để đọc / so sánh dễ)."""
    today = today or date.today()

    def vn(d):
        return f"{d[8:10]}/{d[5:7]}/{d[:4]}" if d else ""
    c = next((x for x in cycle_list(con) if x["name"] == cycle), {"start": None, "end": None})
    its = [i for i in items(con) if i["cycle"] == cycle]
    leaf = [i for i in its if not i["is_objective"]]
    done = sum(1 for i in leaf if i["status"] == DONE)
    ext = extension_counts(con)
    rows = [[f"OKR · {cycle}" + (f" · {vn(c['start'])} – {vn(c['end'])}" if c["start"] else "")
             + f" · {done}/{len(leaf)} hạng mục hoàn thành"],
            [f"{note} Cập nhật {stamp}."], [], SHEET_HEAD]
    for i in its:
        late = is_late(i, today)
        rows.append([i["code"], i["grp"] or "", i["title"] or "", i["details"] or "", i["qty"] or "", i["unit"] or "",
                     i["month_text"] or "", vn(i["start"]), vn(i["end"]), i["pic"] or "",
                     "" if i["is_objective"] else STATUS_LABEL.get(i["status"], i["status_raw"] or ""),
                     "" if i["progress"] is None else round(i["progress"]) / 100,
                     i["link"] or "", " · ".join(x for x in (
                         "Trễ hạn" if late else "", f"Gia hạn {ext[i['uid']]} lần" if ext.get(i["uid"]) else "",
                         i["note"] or "") if x)])
    return rows


# ---- Mẫu OKR: tạo cả đợt một lần (chi tiết sửa sau) ----
# Mẫu = {"key", "name", "desc", "objectives": [{"title", "items": [{"title", "grp", "qty", "unit", "pic", "s", "l"}]}]}
# s / l: ngày bắt đầu / độ dài của hạng mục theo tỷ lệ độ dài đợt (0–1), nên áp cho đợt dài ngắn nào cũng được.

def builtin_templates() -> list[dict]:
    from pathlib import Path
    p = Path(__file__).parent / "assets" / "okr_templates.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def saved_templates(app_con) -> list[dict]:
    """Mẫu team tự lưu (dùng chung mọi dự án, lưu trong file dữ liệu chính)."""
    raw = _setting(app_con, "okr_templates")
    return json.loads(raw) if raw else []


def all_templates(app_con=None) -> list[dict]:
    return builtin_templates() + (saved_templates(app_con) if app_con is not None else [])


def save_template(app_con, name: str, tpl: dict) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Cần tên mẫu")
    if not tpl.get("objectives"):
        raise ValueError("Đợt này chưa có mục tiêu nào để lưu làm mẫu")
    mine = [t for t in saved_templates(app_con) if t["name"].lower() != name.lower()]
    t = {**tpl, "key": f"user:{name.lower()}", "name": name, "user": True}
    _setting(app_con, "okr_templates", json.dumps(mine + [t], ensure_ascii=False))
    return t


def delete_template(app_con, key: str) -> None:
    _setting(app_con, "okr_templates", json.dumps([t for t in saved_templates(app_con) if t["key"] != key],
                                                  ensure_ascii=False))


def template_from_cycle(con, cycle: str) -> dict:
    """Mẫu từ một đợt có sẵn: giữ tên, nhóm, số lượng, đơn vị, phụ trách và vị trí thời gian (theo tỷ lệ)."""
    c = next((x for x in cycle_list(con) if x["name"] == cycle), None)
    its = [i for i in items(con) if i["cycle"] == cycle]
    starts = [i["start"] for i in its if i["start"]]
    ends = [i["end"] for i in its if i["end"]]
    s0 = (c or {}).get("start") or (min(starts) if starts else None)
    e0 = (c or {}).get("end") or (max(ends) if ends else None)
    total = (date.fromisoformat(e0) - date.fromisoformat(s0)).days + 1 if s0 and e0 else 0

    def frac(d, base):
        return round(max(0.0, min(1.0, (date.fromisoformat(d) - date.fromisoformat(base)).days / total)), 3) \
            if d and base and total else None
    objs = []
    for o in [i for i in its if i["is_objective"]]:
        kids = []
        for k in [i for i in its if not i["is_objective"] and i["objective"] == o["uid"]]:
            s = frac(k["start"], s0)
            ln = ((date.fromisoformat(k["end"]) - date.fromisoformat(k["start"])).days + 1) / total \
                if k["start"] and k["end"] and total else None
            kids.append({"title": k["title"], "grp": k["grp"], "qty": k["qty"], "unit": k["unit"], "pic": k["pic"],
                         "s": 0.0 if s is None else s, "l": 1.0 if ln is None else round(min(ln, 1.0), 3)})
        objs.append({"title": o["title"], "items": kids})
    return {"objectives": objs, "days": total or None}


def parse_quick(text: str) -> dict:
    """Dán nhanh: dòng thường = mục tiêu; dòng bắt đầu bằng "-", "•", "+" hoặc thụt vào = hạng mục của mục tiêu ngay
    trên. "| người phụ trách" ở cuối dòng hạng mục (không bắt buộc). Hạng mục chưa có mục tiêu thì gom vào "Mục tiêu 1"."""
    objs: list[dict] = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        is_item = raw[:1] in (" ", "\t") or raw.strip()[:1] in "-•+*"
        line = raw.strip().lstrip("-•+*").strip()
        if not line:
            continue
        if is_item:
            title, _, pic = line.partition("|")
            if not objs:
                objs.append({"title": "Mục tiêu 1", "items": []})
            objs[-1]["items"].append({"title": title.strip(), "pic": pic.strip(), "s": 0.0, "l": 1.0})
        else:
            objs.append({"title": line.split("|")[0].strip(), "items": []})
    return {"objectives": objs}


def apply_template(con, cycle: str, tpl: dict, include: list[int] | None = None) -> dict:
    """Tạo mục tiêu + hạng mục của mẫu vào đợt `cycle`; ngày hạng mục tính theo ngày của đợt. include: chỉ số các mục
    tiêu được chọn (None = tất cả). Trả {"objectives": n, "items": n}."""
    c = next((x for x in cycle_list(con) if x["name"] == cycle), None)
    if not c:
        raise ValueError("Không thấy đợt")
    s0 = date.fromisoformat(c["start"]) if c.get("start") else None
    e0 = date.fromisoformat(c["end"]) if c.get("end") else None
    total = (e0 - s0).days + 1 if s0 and e0 else None
    n_o = n_i = 0
    for k, o in enumerate(tpl.get("objectives") or []):
        if include is not None and k not in include:
            continue
        if not (o.get("title") or "").strip():
            continue
        ouid = add_objective(con, cycle, o["title"])
        n_o += 1
        for it in o.get("items") or []:
            if not (it.get("title") or "").strip():
                continue
            fields = {f: it.get(f) or "" for f in ("grp", "qty", "unit", "pic", "details")}
            if total:
                st = s0 + timedelta(days=round((it.get("s") or 0) * total))
                en = st + timedelta(days=max(0, round((it.get("l") or 1) * total) - 1))
                fields.update(start=st.isoformat(), end=min(en, e0).isoformat())
            add_item(con, ouid, it["title"], **fields)
            n_i += 1
    return {"objectives": n_o, "items": n_i}


# ---- Thông báo OKR + gia hạn ----

DUE_SOON_DAYS = 3


def alerts(con, today: date | None = None, cycle: str | None = None) -> dict[str, list[dict]]:
    """Việc cần để ý của một đợt (mặc định đợt đang chạy): trễ hạn, đến hạn trong 3 ngày tới, đã tới ngày bắt đầu mà
    chưa bắt đầu. Hạng mục đã xong thì không báo."""
    today = today or date.today()
    every = items(con)
    cs = cycle_list(con, every, today)
    cycle = cycle if cycle in {c["name"] for c in cs} else cycle_at(cs, today)
    leaf = [i for i in every if i["cycle"] == cycle and not i["is_objective"] and i["status"] != DONE]
    t, soon = today.isoformat(), (today + timedelta(days=DUE_SOON_DAYS)).isoformat()
    ext = extension_counts(con)
    for i in leaf:
        i["extended"] = ext.get(i["uid"], 0)
    late = sorted((i for i in leaf if i["end"] and i["end"] < t), key=lambda i: i["end"])
    due = sorted((i for i in leaf if i["end"] and t <= i["end"] <= soon), key=lambda i: i["end"])
    idle = sorted((i for i in leaf if i["status"] == TODO and i["start"] and i["start"] <= t
                   and not (i["end"] and i["end"] < t)), key=lambda i: i["start"])
    return {"cycle": cycle, "late": late, "due_soon": due, "not_started": idle}


def extend(con, uids: list[str], *, days: int | None = None, new_end: str | None = None, by: str = "",
           reason: str = "", today: date | None = None) -> int:
    """Gia hạn: dời ngày kết thúc thêm `days` ngày (tính từ hạn cũ, hạn cũ đã qua thì tính từ hôm nay) hoặc tới
    `new_end`. Ghi nhật ký gia hạn. Trả số hạng mục đã gia hạn."""
    today = today or date.today()
    if days is None and not new_end:
        raise ValueError("Chọn số ngày hoặc ngày kết thúc mới")
    n = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        for uid in uids:
            row = con.execute("SELECT start, end, is_objective FROM okr_items WHERE uid = ?", (uid,)).fetchone()
            if not row or row[2]:
                continue
            start, old = row[0], row[1]
            if new_end:
                target = new_end
            else:
                base = max(date.fromisoformat(old), today) if old else today
                target = (base + timedelta(days=days)).isoformat()
            if start and target < start:
                raise ValueError("Ngày kết thúc mới trước ngày bắt đầu")
            if target == old:
                continue
            con.execute("UPDATE okr_items SET end = ? WHERE uid = ?", (target, uid))
            con.execute("INSERT INTO okr_extensions (uid, old_end, new_end, at, by, reason) VALUES (?, ?, ?, ?, ?, ?)",
                        (uid, old, target, now, str(by), (reason or "").strip()))
            n += 1
    if n:
        _touch(con)
    return n


def extension_counts(con) -> dict[str, int]:
    ensure_tables(con)
    return dict(con.execute("SELECT uid, COUNT(*) FROM okr_extensions GROUP BY uid"))


def extensions(con, uid: str) -> list[dict]:
    ensure_tables(con)
    return [{"old_end": o, "new_end": n, "at": a, "by": b, "reason": r} for o, n, a, b, r in con.execute(
        "SELECT old_end, new_end, at, by, reason FROM okr_extensions WHERE uid = ? ORDER BY id", (uid,))]


def delete_items(con, uids: list[str]) -> int:
    """Xóa nhiều mục một lần (mục tiêu kéo theo hạng mục của nó)."""
    with con:
        n = 0
        for uid in uids:
            n += con.execute("DELETE FROM okr_items WHERE uid = ? OR (objective = ? AND is_objective = 0)",
                             (uid, uid)).rowcount
        con.execute(f"DELETE FROM okr_extensions WHERE uid NOT IN (SELECT uid FROM okr_items)")
    _touch(con)
    return n


def set_status_many(con, uids: list[str], status: str, today: date | None = None) -> None:
    for uid in uids:
        update_item(con, uid, today=today, status=status)
