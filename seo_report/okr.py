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


def sync(con: sqlite3.Connection, cfg, today: date | None = None) -> dict:
    today = today or date.today()
    tables, source = fetch_tables(cfg)
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
    cs = cycles(every, today)
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
