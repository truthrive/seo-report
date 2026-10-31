"""KPI cam kết SEO theo tháng dự án, nhập trên một Google Sheet mẫu (tool chỉ đọc).

Sheet có 2 tab:
- "KPI cam kết": tên dự án, ngày bắt đầu, và bảng theo tháng dự án: giai đoạn, % bộ từ khóa cam kết vào top 3 / 5 /
  10, phiên Organic Search (GA4). Ô trống hoặc "-%" = tháng đó chưa cam kết.
- "Từ khóa cam kết": từ khóa + URL mục tiêu. Đồng bộ thì từ khóa mới được thêm vào danh sách check rank.

Cách tính (đã thống nhất với người dùng):
- Tháng dự án N: từ ngày bắt đầu cộng N-1 tháng đến trước cùng ngày tháng sau (1/11 → 30/11).
- Thứ hạng: lần check DataForSEO cuối cùng trong tháng dự án của từng từ khóa cam kết; xếp hạng bằng URL khác URL
  mục tiêu vẫn tính; chưa có lần check hoặc ngoài độ sâu = chưa đạt. Top 3 nằm trong top 5, top 5 trong top 10.
- Traffic: phiên GA4 kênh Organic Search toàn site, cộng trong tháng dự án; tháng đang chạy có thêm số dự báo cuối
  tháng theo tốc độ hiện tại.
- Mỗi lần nội dung sheet đổi, tool lưu một phiên bản. Tháng đã qua tính theo phiên bản đang có hiệu lực cuối tháng đó,
  nên điều chỉnh KPI về sau không làm đổi kết quả đã chốt.
"""
import calendar
import json
import math
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

KPI_TAB, KW_TAB = "KPI cam kết", "Từ khóa cam kết"
RANK_ROWS = (("top3", 3), ("top5", 5), ("top10", 10))
SCHEMA = """
CREATE TABLE IF NOT EXISTS kpi_versions (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,          -- ngày tool thấy phiên bản này (có hiệu lực từ ngày này)
    synced_at TEXT NOT NULL,
    data TEXT NOT NULL          -- JSON: project, start, months, keywords
);
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _setting(con, key: str, value: str | None = None) -> str | None:
    ensure_tables(con)
    if value is not None:
        with con:
            con.execute("INSERT OR REPLACE INTO app_settings VALUES (?, ?)", (key, value))
        return value
    row = con.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def sheet_id(con) -> str:
    return _setting(con, "kpi_sheet") or ""


def set_sheet(con, link_or_id: str) -> str:
    m = re.search(r"/d/([A-Za-z0-9_-]+)", link_or_id or "")
    sid = m.group(1) if m else (link_or_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", sid):
        raise ValueError("Không nhận ra link Google Sheet")
    return _setting(con, "kpi_sheet", sid)


def sync_info(con) -> dict | None:
    raw = _setting(con, "kpi_synced")
    return json.loads(raw) if raw else None


# ---- Tháng dự án ----

def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_window(start: date, n: int) -> tuple[date, date]:
    return add_months(start, n - 1), add_months(start, n) - timedelta(days=1)


# ---- Đọc sheet ----

def _pct(v) -> float | None:
    """'11%' / 11 / 0.11 → 0.11; trống, '-', '-%' → None."""
    if v is None or (isinstance(v, str) and v.strip().strip("%").strip() in ("", "-")):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v <= 1 else float(v) / 100
    s = str(v).strip().replace(",", ".")
    m = re.search(r"\d+(\.\d+)?", s)
    if not m:
        return None
    x = float(m.group(0))
    return x / 100 if "%" in s or x > 1 else x


def _int(v) -> int | None:
    """'40,348' / '59.348' / 40348 → 40348 (số phiên luôn là số nguyên nên bỏ mọi dấu phân cách)."""
    if v is None or (isinstance(v, str) and v.strip() in ("", "-")):
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    digits = re.sub(r"[^\d]", "", str(v))
    return int(digits) if digits else None


def _label(row) -> str:
    return str(row[0]).strip().lower() if row and row[0] is not None else ""


def parse_kpi(rows: list[list], today: date) -> dict:
    from .okr import parse_date
    out = {"project": "", "start": None, "months": []}
    header = None
    for i, r in enumerate(rows):
        lab = _label(r)
        if lab.startswith("tên dự án") and len(r) > 1:
            out["project"] = str(r[1] or "").strip()
        elif lab.startswith("ngày bắt đầu") and len(r) > 1:
            d = parse_date(r[1], today)
            out["start"] = d.isoformat() if d else None
        elif lab.startswith("tháng thứ"):
            header = i
            break
    if header is None:
        raise ValueError("Không thấy hàng 'Tháng thứ dự án' trong tab KPI cam kết")
    cols = [(j, _int(v)) for j, v in enumerate(rows[header]) if j > 0 and _int(v)]
    months = {n: {"n": n, "phase": "", "top3": None, "top5": None, "top10": None, "sessions": None} for _, n in cols}
    last_phase = ""
    for r in rows[header + 1:]:
        if not any(v not in (None, "") for v in r):
            break  # bảng kết thúc ở dòng trống đầu tiên (bên dưới là ghi chú)
        lab = _label(r)
        key = ("phase" if lab.startswith("giai đoạn") else "top3" if "top 3" in lab else "top5" if "top 5" in lab
               else "top10" if "top 10" in lab else "sessions" if ("phiên" in lab or "session" in lab or
                                                                   "traffic" in lab) else None)
        if not key:
            continue
        for j, n in cols:
            v = r[j] if j < len(r) else None
            if key == "phase":  # ô giai đoạn hay được gộp: ô trống lấy giai đoạn bên trái
                last_phase = str(v).strip() if v not in (None, "") else last_phase
                months[n]["phase"] = last_phase
            elif key == "sessions":
                months[n][key] = _int(v)
            else:
                months[n][key] = _pct(v)
    out["months"] = [months[n] for n in sorted(months)]
    return out


def parse_keywords(rows: list[list]) -> list[dict]:
    out, seen = [], set()
    for r in rows:
        kw = str(r[0]).strip() if r and r[0] is not None else ""
        if not kw or kw.lower() in ("từ khóa", "từ khoá", "keyword") or kw.startswith("#"):
            continue
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        url = str(r[1]).strip() if len(r) > 1 and r[1] not in (None, "") else ""
        out.append({"keyword": kw, "url": url})
    return out


def fetch(cfg, sid: str) -> dict[str, list[list]]:
    from googleapiclient.discovery import build

    from . import auth
    svc = build("sheets", "v4", credentials=auth.get_credentials(cfg, need=(auth.SHEETS_SCOPE,)),
                cache_discovery=False)
    titles = [s["properties"]["title"] for s in
              svc.spreadsheets().get(spreadsheetId=sid, fields="sheets(properties(title))").execute()["sheets"]]
    out = {}
    for want in (KPI_TAB, KW_TAB):
        title = next((t for t in titles if t.strip().lower() == want.lower()), None)
        if title:
            rng = "'" + title.replace("'", "''") + "'!A1:Z1000"
            out[want] = svc.spreadsheets().values().get(
                spreadsheetId=sid, range=rng, valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER").execute().get("values", [])
    if KPI_TAB not in out:
        raise ValueError(f"Sheet không có tab '{KPI_TAB}'")
    return out


# ---- Lưu phiên bản + đồng bộ ----

def save(con, data: dict, today: date) -> bool:
    """Lưu nếu khác phiên bản mới nhất. Trả về True khi có phiên bản mới."""
    ensure_tables(con)
    last = con.execute("SELECT data FROM kpi_versions ORDER BY id DESC LIMIT 1").fetchone()
    body = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if last and last[0] == body:
        return False
    with con:
        con.execute("INSERT INTO kpi_versions (day, synced_at, data) VALUES (?, ?, ?)",
                    (today.isoformat(), datetime.now(timezone.utc).isoformat(timespec="seconds"), body))
    return True


def sync(con, cfg, user: str = "tool", today: date | None = None) -> dict:
    from . import keywords as K
    from . import rank as R
    today = today or date.today()
    sid = sheet_id(con)
    if not sid:
        raise ValueError("Chưa có sheet KPI: tạo sheet mẫu hoặc dán link sheet trên màn Cam kết KPI")
    tables = fetch(cfg, sid)
    data = parse_kpi(tables[KPI_TAB], today)
    data["keywords"] = parse_keywords(tables.get(KW_TAB, []))
    changed = save(con, data, today)
    added = {"added": [], "over_budget": [], "bad_url": []}
    if data["keywords"]:  # từ khóa cam kết phải có trong danh sách check rank
        added = R.add_keywords(con, cfg.site_url, cfg.rank, K.latest_date(con, cfg.site_url),
                               [(k["keyword"], k["url"] or None) for k in data["keywords"]], user, source="kpi")
    info = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "changed": changed,
            "months": len(data["months"]), "keywords": len(data["keywords"]), "added": len(added["added"]),
            "over_budget": added["over_budget"], "bad_url": added["bad_url"]}
    _setting(con, "kpi_synced", json.dumps(info, ensure_ascii=False))
    return info


def versions(con) -> list[dict]:
    ensure_tables(con)
    return [{"id": i, "day": d, "data": json.loads(x)} for i, d, x in
            con.execute("SELECT id, day, data FROM kpi_versions ORDER BY id")]


def version_at(vs: list[dict], day: date) -> dict | None:
    """Phiên bản có hiệu lực vào ngày `day` (mới nhất có ngày ≤ day); trước khi tool thấy phiên bản nào thì dùng
    phiên bản đầu tiên."""
    if not vs:
        return None
    ok = [v for v in vs if v["day"] <= day.isoformat()]
    return (ok[-1] if ok else vs[0])["data"]


# ---- Tính tiến độ ----

def _rank_stats(con, site: str, kws: list[dict], s: date, e: date) -> dict:
    """Lần check cuối trong [s, e] của từng từ khóa cam kết → số từ khóa trong top 3/5/10."""
    from . import rank as R
    R.ensure_tables(con)
    ids = {k.lower(): i for i, k in con.execute("SELECT id, keyword FROM rank_keywords WHERE site = ?", (site,))}
    out = {"total": len(kws), "checked": 0, "top3": 0, "top5": 0, "top10": 0, "missing": []}
    for k in kws:
        kid = ids.get(k["keyword"].lower())
        row = con.execute("SELECT check_date, rank FROM rank_checks WHERE keyword_id = ? AND check_date BETWEEN ? AND ?"
                          " ORDER BY check_date DESC LIMIT 1", (kid, s.isoformat(), e.isoformat())).fetchone() \
            if kid else None
        rank = row[1] if row else None
        if row:
            out["checked"] += 1
        for key, n in RANK_ROWS:
            if rank is not None and rank <= n:
                out[key] += 1
        if rank is None or rank > 10:
            out["missing"].append({"keyword": k["keyword"], "rank": rank, "checked": bool(row)})
    return out


def progress(con, site: str, today: date, organic_sessions=None) -> dict | None:
    """Tiến độ từng tháng dự án. organic_sessions(s, e) -> {ngày iso: phiên} (GA4 Organic Search); None = không lấy
    GA4 (số phiên để trống, không hiện 0)."""
    vs = versions(con)
    cur = version_at(vs, today)
    if not cur:
        return None
    out = {"project": cur["project"], "start": cur["start"], "keywords": len(cur.get("keywords", [])),
           "months": [], "current": None, "state": "no_start"}
    if not cur["start"]:
        out["months"] = cur["months"]
        return out
    start = date.fromisoformat(cur["start"])
    yesterday = today - timedelta(days=1)
    for m in cur["months"]:
        s, e = month_window(start, m["n"])
        row = {**m, "from": s.isoformat(), "to": e.isoformat(), "status": "future" if s > today else
               ("running" if e >= today else "closed")}
        if row["status"] == "running":
            out["current"] = m["n"]
        if row["status"] != "future":
            ver = version_at(vs, min(e, today))  # tháng đã chốt: phiên bản hiệu lực cuối tháng
            target = next((x for x in ver["months"] if x["n"] == m["n"]), m)
            row.update({k: target.get(k) for k in ("top3", "top5", "top10", "sessions", "phase")})
            row["rank"] = _rank_stats(con, site, ver.get("keywords", []), s, min(e, today))
            row["actual_sessions"] = row["forecast"] = None
            if organic_sessions and s <= yesterday:
                daily = organic_sessions(s, min(e, yesterday))
                row["actual_sessions"] = sum(daily.values())
                days_done = (min(e, yesterday) - s).days + 1
                if row["status"] == "running" and days_done >= 3:
                    row["forecast"] = round(row["actual_sessions"] / days_done * ((e - s).days + 1))
            row["checks"] = _judge(row)
        out["months"].append(row)
    first = date.fromisoformat(out["months"][0]["from"]) if out["months"] else start
    last = date.fromisoformat(out["months"][-1]["to"]) if out["months"] else start
    out["state"] = "before" if today < first else ("after" if today > last else "running")
    return out


def _judge(row: dict) -> dict:
    """Mỗi chỉ số: {target, actual, ok, gap, unit}. target None = tháng đó không cam kết (không chấm)."""
    out = {}
    rk = row.get("rank") or {}
    total = rk.get("total") or 0
    for key, _ in RANK_ROWS:
        t = row.get(key)
        actual = rk.get(key, 0) / total if total else None
        need = math.ceil(t * total - 1e-9) if t is not None and total else None
        out[key] = {"target": t, "actual": actual, "count": rk.get(key, 0), "need": need,
                    "ok": None if t is None or actual is None else rk.get(key, 0) >= need,
                    "gap": None if need is None else max(0, need - rk.get(key, 0))}
    t, a = row.get("sessions"), row.get("actual_sessions")
    basis = row.get("forecast") if row.get("status") == "running" and row.get("forecast") is not None else a
    out["sessions"] = {"target": t, "actual": a, "forecast": row.get("forecast"),
                       "ok": None if t is None or basis is None else basis >= t,
                       "gap": None if t is None or basis is None else max(0, t - basis)}
    return out


def ga4_organic(cfg, con):
    """Hàm lấy phiên Organic Search theo ngày (GA4, có cache). None nếu chưa kết nối GA4."""
    if not cfg.ga4_property:
        return None
    from . import ai_classifier as C, auth, ga4_query
    client = ga4_query.GA4Client(auth.build_ga4_data(auth.get_credentials(cfg, need=auth.ALL_SCOPES)),
                                 cfg.ga4_property, con)

    def fn(s: date, e: date) -> dict[str, int]:
        rep = client.run(["date"], ["sessions"], s, e, C.channel_filter("Organic Search"), limit=1000)
        return {r["date"]: r["sessions"] for r in rep.rows}
    return fn


# ---- Sheet mẫu ----

SAMPLE = [  # bảng mẫu người dùng gửi (dự án 6 tháng, khoảng 150 từ khóa)
    ("Review tối ưu nền tảng", None, None, None, 39000), ("Review tối ưu nền tảng", None, None, None, 39000),
    ("Review tối ưu nền tảng", 0.11, 0.19, 0.34, 40348),
    ("Tiếp tục tối ưu nền tảng và thúc đẩy", 0.13, 0.24, 0.40, 49348),
    ("Tiếp tục tối ưu nền tảng và thúc đẩy", 0.15, 0.28, 0.49, 59348),
    ("Tiếp tục tối ưu nền tảng và thúc đẩy", 0.16, 0.32, 0.63, 71228),
]


def template_xlsx(project: str, keywords: list[tuple[str, str]]) -> bytes:
    """File Excel mẫu (Drive chuyển thành Google Sheet). Bảng KPI điền sẵn số của dự án mẫu, ngày bắt đầu để trống:
    điền ngày bắt đầu thì tool mới bắt đầu chấm."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    navy, white = PatternFill("solid", fgColor="1F3A68"), Font(color="FFFFFF", bold=True)
    tint, yellow = PatternFill("solid", fgColor="EEF2F8"), PatternFill("solid", fgColor="FFF6CC")
    thin = Side(style="thin", color="C9CED8")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    wb = Workbook()
    ws = wb.active
    ws.title = KPI_TAB
    ws["A1"] = "KPI cam kết SEO"
    ws["A1"].font = Font(size=16, bold=True)
    info = [("Tên dự án", project), ("Ngày bắt đầu", ""), ("Số từ khóa cam kết", f"=COUNTA('{KW_TAB}'!A2:A1000)")]
    for i, (k, v) in enumerate(info, start=3):
        ws.cell(i, 1, k).font = Font(bold=True)
        c = ws.cell(i, 2, v)
        c.fill, c.border = yellow if k == "Ngày bắt đầu" else tint, box
    ws["C4"] = "dd/mm/yyyy · ví dụ 01/11/2026. Tháng 1 = 01/11 → 30/11, tháng 2 = 01/12 → 31/12…"
    ws["C4"].font = Font(italic=True, color="6B6A5E")
    h = 8
    labels = ["Tháng thứ dự án", "Giai đoạn", "Số lượng từ khóa vào top 3 (cam kết)",
              "Số lượng từ khóa vào top 5 (cam kết)", "Số lượng từ khóa vào top 10 (cam kết)",
              "Traffic Session Organic Search (GA4)"]
    for r, lab in enumerate(labels):
        c = ws.cell(h + r, 1, lab)
        c.font, c.border = Font(bold=True, color="FFFFFF" if r == 0 else "1F221E"), box
        if r == 0:
            c.fill = navy
    for j, (phase, t3, t5, t10, ses) in enumerate(SAMPLE, start=2):
        vals = [j - 1, phase, t3, t5, t10, ses]
        for r, v in enumerate(vals):
            c = ws.cell(h + r, j, v if v is not None else "-")
            c.border, c.alignment = box, Alignment(horizontal="center", wrap_text=r == 1)
            if r == 0:
                c.fill, c.font = navy, white
            elif r in (2, 3, 4) and v is not None:
                c.number_format = "0%"
            elif r == 5:
                c.number_format = "#,##0"
    notes = ["Cách nhập:", "• Ô '-' hoặc để trống = tháng đó chưa cam kết (tool chỉ hiện số thực tế, không chấm).",
             "• % tính trên toàn bộ tab 'Từ khóa cam kết'. Thêm tháng: thêm cột 7, 8… cùng định dạng.",
             "• Đổi KPI hay bộ từ khóa giữa dự án: sửa thẳng ở đây. Tool lưu lại từng phiên bản, tháng đã qua giữ "
             "kết quả theo KPI lúc đó.",
             "• Thứ hạng: lần check DataForSEO cuối trong tháng (Google mobile, Việt Nam). Traffic: phiên GA4 kênh "
             "Organic Search."]
    for i, t in enumerate(notes, start=h + len(labels) + 1):
        ws.cell(i, 1, t).font = Font(bold=i == h + len(labels) + 1, italic=i > h + len(labels) + 1, color="4A4A42")
    ws.column_dimensions["A"].width = 40
    for col in "BCDEFGHIJKLM":
        ws.column_dimensions[col].width = 16
    ws.row_dimensions[h + 1].height = 34

    kw = wb.create_sheet(KW_TAB)
    for j, t in enumerate(["Từ khóa", "URL mục tiêu", "Ghi chú"], start=1):
        c = kw.cell(1, j, t)
        c.fill, c.font, c.border = navy, white, box
    for i, (k, u) in enumerate(keywords, start=2):
        kw.cell(i, 1, k)
        kw.cell(i, 2, u)
    kw.column_dimensions["A"].width, kw.column_dimensions["B"].width, kw.column_dimensions["C"].width = 38, 60, 30
    kw.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def create_template(con, cfg) -> dict:
    """Tạo sheet mẫu trong folder Drive của tool (quyền drive.file), điền sẵn các từ khóa đang check rank."""
    from . import drive as D, keywords as K, rank as R
    svc = D.build_service(cfg)
    folder, _ = D.target_folder(con, svc, cfg.site_url)
    host = cfg.site_url.split("//")[-1].strip("/")
    kws = [(k["keyword"], k["target_url"] or "") for k in R.keywords(con, cfg.site_url, K.latest_date(con, cfg.site_url))]
    f = D.upload(svc, template_xlsx(f"SEO {host}", kws), f"KPI cam kết SEO – {host}", D.XLSX, folder, D.SHEET)
    set_sheet(con, f["id"])
    return f
