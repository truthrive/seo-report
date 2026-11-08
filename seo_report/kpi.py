"""KPI cam kết SEO theo tháng dự án, nhập trên một Google Sheet (tool đọc, lưu phiên bản và chấm).

Sheet có 2 tab:
- "KPI cam kết": khối thông tin (tên dự án, ngày bắt đầu, số tháng, baseline Organic Search / AI Assistant) và bảng cam
  kết. Mỗi dòng là một cam kết: Loại | Nguồn / Bộ | Đơn vị | một cột cho mỗi tháng dự án. Ba loại dòng:
    · "Top N": % hoặc số từ khóa vào top N. "Bộ chung" = tính trên toàn bộ tab từ khóa (top 3 nằm trong top 5);
      "Bộ riêng" = chỉ các từ khóa có Top target = N, mỗi bộ chấm độc lập.
    · "Mức tháng": phiên GA4 của nguồn (Organic Search hoặc AI Assistant) phải đạt trong tháng.
    · "Tăng thêm cộng dồn": mức tăng so với baseline hoạch định cho tháng. Thực tế = phiên tháng − baseline, cộng dồn
      qua các tháng (tháng thấp hơn baseline trừ vào lũy kế). Tổng các ô = cam kết tích lũy cả dự án.
  Ô trống hoặc "-" = tháng đó không cam kết. Mẫu cũ (hàng "Tháng thứ dự án", 3 hàng top + hàng traffic) vẫn đọc được và
  quy về cùng mô hình dòng.
- "Từ khóa cam kết": từ khóa + URL mục tiêu + Top target. Đồng bộ thì từ khóa mới được thêm vào danh sách check rank.

Cách tính (đã thống nhất với người dùng):
- Tháng dự án N: từ ngày bắt đầu cộng N-1 tháng đến trước cùng ngày tháng sau (1/11 → 30/11).
- Thứ hạng: lần check DataForSEO cuối cùng trong tháng dự án của từng từ khóa; xếp hạng bằng URL khác URL mục tiêu vẫn
  tính; chưa có lần check hoặc ngoài độ sâu = chưa đạt. Báo cáo luôn hiện cả % lẫn số từ khóa.
- Traffic: phiên GA4 của kênh, cộng trong tháng dự án; tháng đang chạy chấm theo dự báo cuối tháng (từ ngày thứ 3).
- Mỗi lần nội dung sheet đổi, tool lưu một phiên bản. Tháng đã qua tính theo phiên bản đang có hiệu lực cuối tháng đó,
  nên điều chỉnh KPI về sau không làm đổi kết quả đã chốt.
"""
import calendar
import json
import math
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

from .projects import domain

KPI_TAB, KW_TAB = "KPI cam kết", "Từ khóa cam kết"
SOURCES = {"organic": "Organic Search", "ai": "AI Assistant"}
KIND_LABEL = {"level": "Mức tháng", "cum": "Tăng thêm cộng dồn"}
UNIT_LABEL = {"pct": "%", "count": "số từ khóa"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS kpi_versions (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,          -- ngày tool thấy phiên bản này (có hiệu lực từ ngày này)
    synced_at TEXT NOT NULL,
    data TEXT NOT NULL,         -- JSON: project, start, months, baseline, lines, keywords
    sheet TEXT                  -- sheet đọc ra phiên bản này: chỉ dùng phiên bản của sheet đang chọn
);
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    if "sheet" not in [r[1] for r in con.execute("PRAGMA table_info(kpi_versions)")]:
        with con:
            con.execute("ALTER TABLE kpi_versions ADD COLUMN sheet TEXT")


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


def unlink_sheet(con) -> str:
    """Gỡ sheet đang gắn (để tạo sheet dự án mới hoặc dán link khác). Phiên bản đã lưu của sheet cũ vẫn giữ, gắn lại
    link cũ là dùng tiếp. Trả về ID vừa gỡ."""
    old = sheet_id(con)
    _setting(con, "kpi_sheet", "")
    _setting(con, "kpi_synced", "")
    return old


def sync_info(con) -> dict | None:
    raw = _setting(con, "kpi_synced")
    return json.loads(raw) if raw else None


# ---- Dòng cam kết ----

def line_id(line: dict) -> str:
    """Khóa ổn định của một dòng: top3 / top5 / top10 (top3@12: chỉ tính bộ 12), level:organic, cum:ai…"""
    if line["kind"] == "rank":
        return f"top{line['top']}" + (f"@{line['set']}" if line.get("set") else "")
    return f"{line['kind']}:{line['source']}"


def rank_pool(line: dict, items: list[dict]) -> list[dict]:
    """Từ khóa chấm cho một dòng Top N: theo bộ của dòng (nếu chọn), rồi theo Top target nếu là bộ riêng."""
    pool = [x for x in items if not line.get("set") or x.get("set") == line["set"]]
    return pool if line.get("mode") != "per_tier" else [x for x in pool if x["target"] == line["top"]]


def line_label(line: dict) -> str:
    if line["kind"] == "rank":
        return f"Từ khóa top {line['top']}" + (" · bộ riêng" if line.get("mode") == "per_tier" else "")
    src = SOURCES[line["source"]]
    return f"Phiên {src}" if line["kind"] == "level" else f"{src} tăng thêm cộng dồn"


def find_line(p: dict, lid: str) -> dict | None:
    return next((ln for ln in p.get("lines", []) if line_id(ln) == lid), None)


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
    """'40,348' / '59.348' / 40348 / '+500' → 40348 (số phiên luôn là số nguyên nên bỏ mọi dấu phân cách)."""
    if v is None or (isinstance(v, str) and v.strip() in ("", "-")):
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    s = str(v).strip()
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    return -int(digits) if s.startswith("-") else int(digits)


def _label(row) -> str:
    return str(row[0]).strip().lower() if row and row[0] is not None else ""


def _cell(row, j) -> str:
    return str(row[j]).strip().lower() if len(row) > j and row[j] is not None else ""


def _source(text: str) -> str:
    return "ai" if re.search(r"\bai\b", text.lower()) else "organic"


def _line_of(lab: str, row: list, fmt: str) -> dict | None:
    """Định nghĩa dòng từ nhãn cột A (và cột B, C ở mẫu mới); None = dòng không phải cam kết (ghi chú, giai đoạn…)."""
    m = re.search(r"top\s*(\d+)", lab)
    if fmt == "old":
        if m:
            return {"kind": "rank", "top": int(m.group(1)), "mode": "shared", "unit": "pct"}
        if "phiên" in lab or "session" in lab or "traffic" in lab:
            return {"kind": "level", "source": "organic"}
        return None
    b, u = _cell(row, 1), _cell(row, 2)
    if m and lab.startswith("top"):
        return {"kind": "rank", "top": int(m.group(1)),
                "mode": "per_tier" if "riêng" in b or re.search(r"top\s*\d", b) else "shared",
                "unit": "count" if ("số" in u or "từ" in u) and "%" not in u else "pct"}
    if lab.startswith("mức"):
        return {"kind": "level", "source": _source(b)}
    if "cộng dồn" in lab or "tích lũy" in lab or "tích luỹ" in lab or lab.startswith("tăng"):
        return {"kind": "cum", "source": _source(b)}
    return None


def parse_kpi(rows: list[list], today: date) -> dict:
    """Tab KPI cam kết → {project, start, months: [n…], baseline: {organic, ai}, lines: [{kind…, targets: {n: v}}]}.
    Nhận cả mẫu mới (hàng tiêu đề 'Loại') lẫn mẫu cũ (hàng 'Tháng thứ dự án')."""
    from .okr import parse_date
    out = {"project": "", "start": None, "months": [], "baseline": {"organic": None, "ai": None}, "lines": []}
    header = fmt = None
    for i, r in enumerate(rows):
        lab = _label(r)
        v = r[1] if len(r) > 1 else None
        if lab.startswith("tên dự án"):
            out["project"] = str(v or "").strip()
        elif lab.startswith("ngày bắt đầu"):
            d = parse_date(v, today)
            out["start"] = d.isoformat() if d else None
        elif lab.startswith("baseline"):
            out["baseline"][_source(lab)] = _int(v)
        elif lab.startswith("tháng thứ"):
            header, fmt = i, "old"
            break
        elif lab.startswith("loại"):
            header, fmt = i, "new"
            break
    if header is None:
        raise ValueError("Không thấy bảng cam kết (hàng 'Loại' hoặc 'Tháng thứ dự án') trong tab KPI cam kết")
    first = 1 if fmt == "old" else 3
    cols = [(j, _int(v)) for j, v in enumerate(rows[header]) if j >= first and _int(v)]
    out["months"] = [n for _, n in cols]
    for r in rows[header + 1:]:
        if not any(v not in (None, "") for v in r):
            break  # bảng kết thúc ở dòng trống đầu tiên (bên dưới là ghi chú)
        line = _line_of(_label(r), r, fmt)
        if not line:
            continue
        pct = line["kind"] == "rank" and line["unit"] == "pct"
        line["targets"] = {}
        for j, n in cols:
            v = r[j] if j < len(r) else None
            line["targets"][str(n)] = _pct(v) if pct else _int(v)
        out["lines"].append(line)
    return out


def _top(v) -> int | None:
    """'Top 3' / 3 / 'top10' → 3 / 10; trống hoặc lạ → None."""
    m = re.search(r"\d+", str(v)) if v not in (None, "") else None
    return int(m.group(0)) if m and 0 < int(m.group(0)) <= 100 else None


def _kw_columns(rows: list[list]) -> tuple[dict, int]:
    """Vị trí cột (Từ khóa, URL mục tiêu, Top target) theo dòng tiêu đề và dòng dữ liệu đầu tiên."""
    col = {"kw": 0, "url": 1, "target": None}
    start = 0
    for i, r in enumerate(rows[:5]):
        names = [str(c).strip().lower() for c in r]
        if any(n in ("từ khóa", "từ khoá", "keyword") for n in names):
            for j, n in enumerate(names):
                if n in ("từ khóa", "từ khoá", "keyword"):
                    col["kw"] = j
                elif "url" in n:
                    col["url"] = j
                elif "top" in n or "mục tiêu" in n:
                    col["target"] = j
            start = i + 1
            break
    return col, start


def parse_keywords(rows: list[list]) -> list[dict]:
    """Đọc theo tên cột ở dòng tiêu đề (Từ khóa, URL mục tiêu, Top target), nên thêm hay đổi thứ tự cột vẫn đúng."""
    col, start = _kw_columns(rows)

    def cell(r, j):
        return r[j] if j is not None and j < len(r) and r[j] not in (None, "") else None

    out, seen = [], set()
    for r in rows[start:]:
        kw = str(cell(r, col["kw"]) or "").strip()
        if not kw or kw.startswith("#") or kw.lower() in seen:
            continue
        seen.add(kw.lower())
        out.append({"keyword": kw, "url": str(cell(r, col["url"]) or "").strip(),
                    "target": _top(cell(r, col["target"]))})
    return out


def fetch(cfg, sid: str) -> dict[str, list[list]]:
    from googleapiclient.discovery import build

    from . import auth
    svc = build("sheets", "v4", credentials=auth.get_credentials(cfg, need=(auth.SHEETS_SCOPE,)),
                cache_discovery=False)
    props = [s["properties"] for s in svc.spreadsheets().get(
        spreadsheetId=sid, fields="sheets(properties(sheetId,title))").execute()["sheets"]]
    saved = _saved_ids(cfg, sid)
    found = {want: resolve_tab(props, want, saved) for want in (KPI_TAB, KW_TAB)}
    if found[KPI_TAB] is None:
        raise TabNotFound(KPI_TAB, [x["title"] for x in props])
    _remember(cfg, sid, found)
    out = {}
    for want, p in found.items():
        if p is None:  # chưa có tab từ khóa (hoặc đổi tên khó đoán): sync() không đụng bộ Cam kết
            continue
        rng = "'" + p["title"].replace("'", "''") + "'!A1:AZ1000"
        out[want] = svc.spreadsheets().values().get(
            spreadsheetId=sid, range=rng, valueRenderOption="UNFORMATTED_VALUE",
            dateTimeRenderOption="SERIAL_NUMBER").execute().get("values", [])
    return out


# ---- Lưu phiên bản + đồng bộ ----

def _upgrade(d: dict) -> dict:
    """Phiên bản lưu theo cấu trúc cũ (months = danh sách {n, top3, top5, top10, sessions}) → cấu trúc dòng."""
    if "lines" in d:
        return d
    months = d.get("months") or []
    lines = [{"kind": "rank", "top": n, "mode": "shared", "unit": "pct",
              "targets": {str(m["n"]): m.get(f"top{n}") for m in months}} for n in (3, 5, 10)]
    lines.append({"kind": "level", "source": "organic", "targets": {str(m["n"]): m.get("sessions") for m in months}})
    return {"project": d.get("project", ""), "start": d.get("start"), "months": [m["n"] for m in months],
            "baseline": {"organic": None, "ai": None}, "lines": lines, "keywords": d.get("keywords", [])}


def save(con, data: dict, today: date) -> bool:
    """Lưu nếu khác phiên bản mới nhất. Trả về True khi có phiên bản mới."""
    ensure_tables(con)
    sid = sheet_id(con) or None
    last = con.execute("SELECT data FROM kpi_versions WHERE sheet IS ? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    body = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if last and json.dumps(_upgrade(json.loads(last[0])), ensure_ascii=False, sort_keys=True) == body:
        return False
    with con:
        con.execute("INSERT INTO kpi_versions (day, synced_at, data, sheet) VALUES (?, ?, ?, ?)",
                    (today.isoformat(), datetime.now(timezone.utc).isoformat(timespec="seconds"), body, sid))
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
    # bộ Cam kết ở màn Từ khóa & rank khớp tab Từ khóa cam kết (thêm mới, cập nhật URL / Top, chuyển từ khóa đã bỏ).
    # Không thấy tab từ khóa thì KHÔNG đồng bộ: nếu coi như danh sách rỗng, mọi từ khóa cam kết bị chuyển ra ngoài.
    if KW_TAB in tables:
        added = R.sync_kpi_set(con, cfg.site_url, cfg.rank, K.latest_date(con, cfg.site_url), data["keywords"], user)
    else:
        added = {"added": [], "over_budget": False, "bad_url": [], "missing_tab": True}
    info = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "changed": changed,
            "months": len(data["months"]), "lines": len(data["lines"]), "keywords": len(data["keywords"]),
            "added": len(added["added"]), "over_budget": added["over_budget"], "bad_url": added["bad_url"],
            "keyword_tab_missing": bool(added.get("missing_tab"))}
    _setting(con, "kpi_synced", json.dumps(info, ensure_ascii=False))
    return info


def commitment_keywords(con, site: str) -> list[dict]:
    """Từ khóa cam kết lấy từ tool: mọi từ khóa trong các bộ loại Cam kết đã chốt (kể cả đang tạm dừng: vẫn là cam
    kết). Một từ khóa ở nhiều bộ Cam kết thì lấy dòng ở bộ đứng trước."""
    from . import rank as R
    out, seen = [], set()
    for st in R.sets(con, site):
        if st["kind"] != "kpi" or st["draft"]:
            continue
        for kid, kw, url, top in con.execute(
                "SELECT k.id, k.keyword, u.url, k.top_target FROM rank_keywords k LEFT JOIN urls u ON u.id = k.url_id "
                "WHERE k.set_id = ? AND k.removed_at IS NULL ORDER BY k.id", (st["id"],)):
            if kw.lower() in seen:
                continue
            seen.add(kw.lower())
            out.append({"keyword": kw, "url": url or "", "target": top, "set": st["id"]})
    return out


def snapshot_keywords(con, site: str, today: date) -> bool:
    """Tool là nơi quản lý từ khóa cam kết: khi danh sách trên tool khác phiên bản KPI mới nhất thì lưu phiên bản mới
    (cùng các dòng cam kết, từ khóa mới). Tháng đã qua vẫn chấm theo phiên bản hiệu lực cuối tháng đó.
    Dự án chưa có bộ Cam kết nào mà phiên bản KPI có từ khóa (đọc từ sheet trước đây): tạo bộ Cam kết từ đó trước."""
    from . import rank as R
    vs = versions(con)
    if not vs:
        return False
    cur = vs[-1]["data"]
    if not any(st["kind"] == "kpi" for st in R.sets(con, site)):
        if not cur.get("keywords"):
            return False
        from .config import RankSettings
        R.sync_kpi_set(con, site, RankSettings(monthly_budget_usd=1e9), today, cur["keywords"], "tool (chuyển đổi)")
    kws = commitment_keywords(con, site)
    if kws == cur.get("keywords"):
        return False
    return save(con, {**cur, "keywords": kws}, today)


def versions(con) -> list[dict]:
    """Các phiên bản KPI của sheet đang chọn (đổi sang sheet khác thì phiên bản cũ vẫn giữ nhưng không dùng)."""
    ensure_tables(con)
    return [{"id": i, "day": d, "data": _upgrade(json.loads(x))} for i, d, x in
            con.execute("SELECT id, day, data FROM kpi_versions WHERE sheet IS ? ORDER BY id", (sheet_id(con) or None,))]


def version_at(vs: list[dict], day: date) -> dict | None:
    """Phiên bản có hiệu lực vào ngày `day` (mới nhất có ngày ≤ day); trước khi tool thấy phiên bản nào thì dùng
    phiên bản chốt cuối cùng của ngày đầu tiên (ngày đó có thể đã lưu nhiều lần khi đang nhập / sửa)."""
    if not vs:
        return None
    ok = [v for v in vs if v["day"] <= day.isoformat()]
    if ok:
        return ok[-1]["data"]
    return [v for v in vs if v["day"] == vs[0]["day"]][-1]["data"]


# ---- Tính tiến độ ----

def _rank_items(con, site: str, kws: list[dict], s: date, e: date) -> dict:
    """Lần check cuối trong [s, e] của từng từ khóa cam kết."""
    from . import rank as R
    R.ensure_tables(con)
    ids = {}  # dòng ở bộ Cam kết thắng dòng cùng từ khóa ở bộ khác (nơi check có thể khác)
    for i, k, kind in con.execute("SELECT k.id, k.keyword, s.kind FROM rank_keywords k JOIN rank_sets s ON "
                                  "s.id = k.set_id WHERE k.site = ? ORDER BY s.kind = 'kpi', k.id", (site,)):
        ids[k.lower()] = i
    out = {"total": len(kws), "checked": 0, "missing": [], "items": [], "target_set": 0, "target_ok": 0}
    for k in kws:
        kid = ids.get(k["keyword"].lower())
        row = con.execute("SELECT check_date, rank, depth FROM rank_checks WHERE keyword_id = ? AND check_date "
                          "BETWEEN ? AND ? ORDER BY check_date DESC LIMIT 1",
                          (kid, s.isoformat(), e.isoformat())).fetchone() if kid else None
        rank = row[1] if row else None
        if row:
            out["checked"] += 1
        if rank is None or rank > 10:
            out["missing"].append({"keyword": k["keyword"], "rank": rank, "checked": bool(row)})
        target = k.get("target")  # top target riêng của từ khóa (cột "Top target" trong sheet)
        ok = None if target is None else (rank is not None and rank <= target)
        out["target_set"] += target is not None
        out["target_ok"] += bool(ok)
        out["items"].append({"keyword": k["keyword"], "url": k.get("url", ""), "target": target, "rank": rank,
                             "set": k.get("set"),
                             "depth": row[2] if row else None, "date": row[0] if row else None, "ok": ok})
    return out


def rank_need(line: dict, target, total: int) -> tuple[int | None, float | None]:
    """(số từ khóa cần có, tỷ lệ cam kết) của một dòng Top N với bộ `total` từ khóa; (None, None) = không cam kết."""
    if target is None:
        return None, None
    if line.get("unit") == "count":
        return int(target), (target / total if total else None)
    return (math.ceil(target * total - 1e-9) if total else None), target


def _judge(line: dict, row: dict, prior: tuple[int, bool] = (0, True)) -> dict:
    """Chấm một dòng trong một tháng: {kind, target, actual, ok, gap, …}. target None = tháng đó không cam kết.
    `prior` = (lũy kế thực tế các tháng đã chốt, đủ số liệu?) cho dòng tích lũy."""
    n, running = row["n"], row["status"] == "running"
    t = line["targets"].get(str(n))
    if line["kind"] == "rank":
        items = row["rank"]["items"]
        pool = rank_pool(line, items)
        total = len(pool)
        count = sum(1 for x in pool if x["rank"] is not None and x["rank"] <= line["top"])
        need, target_pct = rank_need(line, t, total)
        return {"kind": "rank", "unit": line["unit"], "target": t, "target_pct": target_pct, "need": need,
                "count": count, "total": total, "checked": sum(1 for x in pool if x["date"] is not None),
                "actual": count / total if total else None,
                "ok": None if need is None else count >= need, "gap": None if need is None else max(0, need - count)}
    src = line["source"]
    a, fc = row["sessions"].get(src), row["forecast"].get(src)
    if line["kind"] == "level":
        # Tháng đang chạy chỉ chấm theo dự báo cuối tháng (cần ít nhất 3 ngày số liệu); chưa đủ ngày thì chưa chấm
        basis = fc if running else a
        expected = (round(t * row["days_done"] / row["days_total"]) if running and t is not None
                    and row.get("days_total") else None)  # số phiên cần có tới hôm qua nếu đi đều theo cam kết
        return {"kind": "level", "source": src, "target": t, "actual": a, "forecast": fc, "expected": expected,
                "days_done": row.get("days_done"), "ok": None if t is None or basis is None else basis >= t,
                "gap": None if t is None or basis is None else max(0, t - basis)}
    base = (row.get("baseline") or {}).get(src)
    inc = None if a is None or base is None else a - base            # tăng thêm so với baseline (tháng này, tới hôm qua)
    basis = None if base is None else ((fc - base) if running and fc is not None else (None if running else inc))
    prev_sum, complete = prior
    cum = prev_sum + basis if complete and basis is not None else None
    plan = {int(k): v for k, v in line["targets"].items() if v is not None}
    plan_cum = sum(v for k, v in plan.items() if k <= n)
    return {"kind": "cum", "source": src, "baseline": base, "target": t, "actual": inc, "sessions": a, "forecast": fc,
            "forecast_inc": basis if running else None, "cum": cum, "cum_prev": prev_sum if complete else None,
            "plan_cum": plan_cum, "total": sum(plan.values()),
            "ok": None if t is None or cum is None else cum >= plan_cum,
            "gap": None if t is None or cum is None else max(0, plan_cum - cum)}


def progress(con, site: str, today: date, sessions=None) -> dict | None:
    """Tiến độ từng tháng dự án. sessions(source, s, e) -> {ngày iso: phiên} (GA4; source = organic / ai); None =
    không lấy GA4 (số phiên để trống, không hiện 0)."""
    vs = versions(con)
    cur = version_at(vs, today)
    if not cur:
        return None
    lines: dict[str, dict] = {}

    def reg(ver):
        for ln in ver["lines"]:
            lines.setdefault(line_id(ln), {k: v for k, v in ln.items() if k != "targets"})

    def targets_of(ver, n):
        return {line_id(ln): ln["targets"].get(str(n)) for ln in ver["lines"]}

    reg(cur)
    out = {"project": cur["project"], "start": cur["start"], "keywords": len(cur.get("keywords", [])),
           "baseline": cur.get("baseline") or {}, "lines": [], "months": [], "current": None, "state": "no_start"}
    if not cur["start"]:
        out["months"] = [{"n": n, "status": "future", "targets": targets_of(cur, n)} for n in cur["months"]]
        out["lines"] = list(lines.values())
        return out
    start = date.fromisoformat(cur["start"])
    yesterday = today - timedelta(days=1)
    cum: dict[str, tuple[int, bool]] = {}  # dòng tích lũy → (lũy kế thực tế các tháng đã chốt, đủ số liệu?)
    for n in cur["months"]:
        s, e = month_window(start, n)
        row = {"n": n, "from": s.isoformat(), "to": e.isoformat(), "status": "future" if s > today else
               ("running" if e >= today else "closed")}
        if row["status"] == "future":
            row["targets"] = targets_of(cur, n)
            out["months"].append(row)
            continue
        if row["status"] == "running":
            out["current"] = n
        ver = version_at(vs, min(e, today))  # tháng đã chốt: phiên bản hiệu lực cuối tháng
        reg(ver)
        row["targets"], row["baseline"] = targets_of(ver, n), ver.get("baseline") or {}
        row["rank"] = _rank_items(con, site, ver.get("keywords", []), s, min(e, today))
        row["days_done"] = max(0, (min(e, yesterday) - s).days + 1)
        row["days_total"] = (e - s).days + 1
        row["sessions"], row["forecast"] = {}, {}
        if sessions and s <= yesterday:
            for src in sorted({ln["source"] for ln in ver["lines"] if ln["kind"] != "rank"}):
                row["sessions"][src] = _period_sessions(sessions, src, s, min(e, yesterday))
                if row["status"] == "running" and row["days_done"] >= 3:
                    row["forecast"][src] = round(row["sessions"][src] / row["days_done"] * row["days_total"])
        row["checks"] = {}
        for ln in ver["lines"]:
            lid = line_id(ln)
            ch = row["checks"][lid] = _judge(ln, row, cum.get(lid, (0, True)))
            if ln["kind"] == "cum" and row["status"] == "closed":
                prev_sum, complete = cum.get(lid, (0, True))
                cum[lid] = (prev_sum + (ch["actual"] or 0), complete and ch["actual"] is not None)
        out["months"].append(row)
    out["lines"] = list(lines.values())
    first = date.fromisoformat(out["months"][0]["from"]) if out["months"] else start
    last = date.fromisoformat(out["months"][-1]["to"]) if out["months"] else start
    out["state"] = "before" if today < first else ("after" if today > last else "running")
    if out["state"] == "before":  # mốc trước dự án: vị trí mới nhất của từng từ khóa cam kết
        out["pre"] = {"n": 0, "rank": _rank_items(con, site, cur.get("keywords", []), date(2000, 1, 1), today)}
    return out


def rank_kpi_now(con, site: str, today: date, set_id: int | None = None) -> dict | None:
    """Tiến độ các dòng cam kết Top N của tháng dự án hiện tại và quý dự án (3 tháng: 1–3, 4–6…) cho màn Từ khóa &
    rank. Số hiện có = cách chấm của màn KPI cam kết (lần check cuối trong tháng); mục tiêu quý = mục tiêu tháng cuối
    quý. Trước khi dự án bắt đầu: so vị trí mới nhất với mục tiêu tháng 1. None khi chưa có sheet KPI / dòng Top N."""
    snapshot_keywords(con, site, today)  # từ khóa cam kết mới nhất trên tool
    p = progress(con, site, today)
    if not p or not p["months"]:
        return None
    rank_lines = [ln for ln in p["lines"] if ln["kind"] == "rank" and (set_id is None or ln.get("set") in (None, set_id))]
    if not rank_lines:
        return None
    months = {m["n"]: m for m in p["months"]}
    if p["state"] == "running":
        n = p["current"]
    elif p["state"] == "after":
        n = max(months)
    else:
        n = min(months)
    row = months[n]
    items = (row.get("rank") or (p.get("pre") or {}).get("rank") or {"items": []})["items"]
    q = math.ceil(n / 3)
    q_last = min(q * 3, max(months))
    q_targets = months[q_last].get("targets") or {}
    out = {"state": p["state"], "month": n, "from": row.get("from"), "to": row.get("to"), "quarter": q,
           "q_months": (q * 3 - 2, q_last), "q_to": months[q_last].get("to"), "rows": []}
    for ln in rank_lines:
        lid = line_id(ln)
        pool = rank_pool(ln, items)
        total = len(pool)
        count = sum(1 for x in pool if x["rank"] is not None and x["rank"] <= ln["top"])

        def goal(t):
            need, pct = rank_need(ln, t, total)
            return {"target": t, "need": need, "target_pct": pct,
                    "done": (min(count / need, 1.0) if need else (1.0 if need == 0 else None)),
                    "gap": None if need is None else max(0, need - count)}
        out["rows"].append({"label": line_label(ln), "top": ln["top"], "unit": ln.get("unit"), "total": total,
                            "count": count, "month": goal((row.get("targets") or {}).get(lid)),
                            "quarter": goal(q_targets.get(lid))})
    return out


def ga4_sessions(cfg, con):
    """Hàm lấy phiên GA4 theo ngày của một nguồn (organic = kênh Organic Search, ai = kênh AI Assistant), có cache.
    None nếu chưa kết nối GA4."""
    if not cfg.ga4_property:
        return None
    from . import ai_classifier as C, auth, ga4_query
    client = ga4_query.GA4Client(auth.build_ga4_data(auth.get_credentials(cfg, need=auth.ALL_SCOPES)),
                                 cfg.ga4_property, con)
    filters = {"organic": C.channel_filter("Organic Search"), "ai": C.channel_filter(*C.NATIVE_CHANNELS)}

    def fn(source: str, s: date, e: date) -> dict[str, int]:
        rep = client.run(["date"], ["sessions"], s, e, filters[source], limit=1000)
        return {r["date"]: r["sessions"] for r in rep.rows}

    def total(source: str, s: date, e: date) -> int:
        """Tổng phiên cả kỳ, khớp giao diện GA4 (cộng theo ngày thì đếm trùng phiên qua nửa đêm, cao hơn 1–2%)."""
        rows = client.run([], ["sessions"], s, e, filters[source]).rows
        return rows[0]["sessions"] if rows else 0
    fn.total = total
    return fn


def _period_sessions(sessions, source: str, s: date, e: date) -> int:
    """Tổng phiên một kỳ: dùng tổng kỳ của GA4 nếu hàm lấy số có (ga4_sessions), không thì cộng theo ngày."""
    total = getattr(sessions, "total", None)
    return total(source, s, e) if total else sum(sessions(source, s, e).values())


# ---- Chữ cho màn hình và báo cáo ----

def _n(v) -> str:
    return "–" if v is None else f"{v:,.0f}".replace(",", ".")


def _signed(v) -> str:
    return "–" if v is None else ("+" if v >= 0 else "−") + _n(abs(v))


def _p(v) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def status(ch: dict, running: bool) -> tuple[str, str]:
    """(chữ, tone) của một ô chấm; tone: grey / green / amber / red."""
    kind = ch["kind"]
    if ch["target"] is None:
        return "Tháng này không cam kết", "grey"
    if kind == "rank" and not ch["checked"] and running:
        return "Chờ lần check đầu", "grey"
    if ch["ok"] is None:
        if kind == "rank":
            return ("Chưa có từ khóa trong bộ" if not ch["total"] else "Chưa có số"), "grey"
        if kind == "cum" and ch["baseline"] is None:
            return "Chưa nhập baseline", "grey"
        have = ch["sessions"] if kind == "cum" else ch["actual"]
        if running and have is not None and ch["forecast"] is None:
            return "Chưa đủ ngày để dự báo", "grey"
        return "Chưa có số", "grey"
    if ch["ok"]:
        return ("Đang đạt" if running else "Đạt"), "green"
    tone, gap = ("amber" if running else "red"), ch["gap"]
    if kind == "rank":
        return f"Thiếu {gap} từ khóa", tone
    if kind == "level":
        return (f"Dự báo thiếu {_n(gap)} phiên" if running else f"Thiếu {_n(gap)} phiên"), tone
    return f"Lũy kế thiếu {_n(gap)} phiên", tone


def fmt_target(line: dict, t) -> str:
    """Ô cam kết ngắn: '11%', '12 từ khóa', '40.348', '+500'."""
    if t is None:
        return "–"
    if line["kind"] == "rank":
        return _p(t) if line["unit"] == "pct" else f"{int(t)} từ khóa"
    return _n(t) if line["kind"] == "level" else _signed(t)


def fmt_actual(ch: dict) -> str:
    """Ô thực tế ngắn (cùng đơn vị với ô cam kết)."""
    if ch["kind"] == "rank":
        return _p(ch["actual"]) if ch["total"] else "–"
    if ch["kind"] == "level":
        return _n(ch["actual"]) if ch["actual"] is not None else "–"
    return _signed(ch["actual"])


def describe(line: dict, ch: dict, running: bool) -> dict:
    """Chữ đầy đủ cho báo cáo (Excel, slide): {label, target, actual, status, good, note}. Thứ hạng luôn ghi cả % lẫn
    số từ khóa dù cam kết nhập theo đơn vị nào."""
    kind, t = ch["kind"], ch["target"]
    text, tone = status(ch, running)
    out = {"label": line_label(line), "target": "không cam kết", "actual": "–", "status": text, "good": ch["ok"],
           "note": ""}
    if kind == "rank":
        if t is not None:
            out["target"] = (f"{_p(ch['target_pct'])} ({ch['need']} từ khóa)" if ch["unit"] == "pct"
                             else f"{int(t)} từ khóa" + (f" ({_p(ch['target_pct'])})" if ch["target_pct"] is not None
                                                        else ""))
        out["actual"] = (f"{_p(ch['actual'])} ({ch['count']}/{ch['total']} từ khóa)" if ch["total"]
                         else "chưa có từ khóa")
        if ch["checked"] < ch["total"]:
            out["note"] = f"{ch['total'] - ch['checked']} từ khóa chưa check trong tháng"
    elif kind == "level":
        if t is not None:
            out["target"] = f"{_n(t)} phiên"
        out["actual"] = f"{_n(ch['actual'])} phiên" if ch["actual"] is not None else "chưa có"
        if running and ch.get("forecast") is not None:
            out["note"] = f"dự báo cuối tháng {_n(ch['forecast'])}"
    else:
        if t is not None:
            out["target"] = f"{_signed(t)} phiên · lũy kế cần {_n(ch['plan_cum'])}/{_n(ch['total'])}"
        if ch["actual"] is not None:
            out["actual"] = (f"{_signed(ch['actual'])} phiên · lũy kế {'dự báo ' if running else ''}"
                             f"{_n(ch['cum']) if ch['cum'] is not None else '–'}")
        elif ch["baseline"] is None:
            out["actual"] = "chưa có baseline"
        else:
            out["actual"] = "chưa có"
        if running and ch.get("forecast_inc") is not None:
            out["note"] = f"dự báo tháng này {_signed(ch['forecast_inc'])}"
    return out


# ---- Sheet mẫu ----

NOTES = [
    "Cách nhập:",
    "• Mỗi dòng là một cam kết. Ô '-' hoặc để trống = tháng đó không cam kết (tool chỉ hiện số thực tế, không chấm).",
    "• Top N · Bộ chung: % hoặc số từ khóa của toàn bộ tab 'Từ khóa cam kết' vào top N. Bộ riêng: chỉ các từ khóa có "
    "Top target = N, mỗi bộ chấm độc lập. Báo cáo luôn hiện cả % lẫn số từ khóa.",
    "• Mức tháng: phiên GA4 của kênh phải đạt trong tháng. Tăng thêm cộng dồn: mức tăng so với baseline hoạch định cho "
    "tháng; thực tế = phiên tháng − baseline, cộng dồn qua các tháng; tổng các ô = cam kết tích lũy cả dự án.",
    "• Thêm tháng: thêm cột cùng định dạng. Thêm cam kết: thêm dòng cùng cách ghi. Tool lưu từng phiên bản; tháng đã "
    "qua giữ kết quả theo KPI lúc đó.",
    "• Thứ hạng: lần check DataForSEO cuối trong tháng (Google mobile, Việt Nam). Traffic: phiên GA4 kênh Organic "
    "Search / AI Assistant (GA4 gom ChatGPT, Gemini, Claude… vào kênh AI Assistant; click từ AI Overviews nằm "
    "trong Organic Search).",
]
SAMPLE = {  # bảng mẫu người dùng gửi (dự án 6 tháng, khoảng 150 từ khóa)
    "top3": [None, None, 0.11, 0.13, 0.15, 0.16], "top5": [None, None, 0.19, 0.24, 0.28, 0.32],
    "top10": [None, None, 0.34, 0.40, 0.49, 0.63], "level:organic": [39000, 39000, 40348, 49348, 59348, 71228],
}


def _col(j: int) -> str:
    """Số thứ tự cột (1 = A) → chữ cột."""
    s = ""
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


def kpi_grid(d: dict) -> list[list]:
    """Các ô của tab KPI cam kết theo bố cục mới (file mẫu và ghi lên sheet đều dùng). Dòng tích lũy có ô Tổng là
    công thức SUM. parse_kpi(kpi_grid(d)) trả lại đúng d."""
    months, base = d["months"], d.get("baseline") or {}
    start = d.get("start") or ""
    rows = [["KPI cam kết SEO"], [],
            ["Tên dự án", d.get("project", "")],
            ["Ngày bắt đầu", f"{start[8:10]}/{start[5:7]}/{start[:4]}" if start else "",
             "dd/mm/yyyy · ví dụ 01/11/2026. Tháng 1 = 01/11 → 30/11, tháng 2 = 01/12 → 31/12…"],
            ["Số tháng", len(months)],
            ["Baseline Organic Search", base.get("organic") if base.get("organic") is not None else "",
             "phiên/tháng trước khi bắt đầu (trung bình 3 tháng) · mốc của dòng 'Tăng thêm cộng dồn'"],
            ["Baseline AI Assistant", base.get("ai") if base.get("ai") is not None else "",
             "phiên/tháng kênh AI Assistant của GA4"],
            [],
            ["Loại", "Nguồn / Bộ", "Đơn vị", *months, "Tổng"]]
    for ln in d["lines"]:
        if ln["kind"] == "rank":
            a, b, u = (f"Top {ln['top']}", "Bộ chung" if ln.get("mode") != "per_tier" else f"Bộ riêng Top {ln['top']}",
                       UNIT_LABEL[ln["unit"]])
        else:
            a, b, u = KIND_LABEL[ln["kind"]], SOURCES[ln["source"]], "phiên"
        cells = [ln["targets"].get(str(n)) for n in months]
        r = len(rows) + 1
        total = f"=SUM(D{r}:{_col(3 + len(months))}{r})" if ln["kind"] == "cum" and months else ""
        rows.append([a, b, u, *[("-" if v is None else v) for v in cells], total])
    rows.append([])
    rows += [[t] for t in NOTES]
    return rows


def sample_data(project: str) -> dict:
    lines = []
    for lid, vals in SAMPLE.items():
        ln = ({"kind": "rank", "top": int(lid[3:]), "mode": "shared", "unit": "pct"} if lid.startswith("top")
              else {"kind": "level", "source": "organic"})
        ln["targets"] = {str(i): v for i, v in enumerate(vals, start=1)}
        lines.append(ln)
    return {"project": project, "start": None, "months": list(range(1, 7)), "baseline": {"organic": None, "ai": None},
            "lines": lines}


def fill_workbook(wb, data: dict, keywords: list[tuple]) -> None:
    """Tạo (hoặc thay) hai tab KPI trong một workbook openpyxl: tab KPI cam kết theo bố cục mới và tab Từ khóa cam
    kết. Dùng cho file mẫu, cho sheet dự án dựng từ sheet mẫu gốc (xuất xlsx) khi tool chưa có quyền ghi Sheets."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    navy, white = PatternFill("solid", fgColor="1F3A68"), Font(color="FFFFFF", bold=True)
    tint, yellow = PatternFill("solid", fgColor="EEF2F8"), PatternFill("solid", fgColor="FFF6CC")
    thin = Side(style="thin", color="C9CED8")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    for t in [x.title for x in wb.worksheets if _norm_tab(x.title) in (KPI_TAB.lower(), KW_TAB.lower())]:
        del wb[t]
    ws = wb.create_sheet(KPI_TAB)
    grid = kpi_grid(data)
    header = next(i for i, r in enumerate(grid) if r and r[0] == "Loại")
    n_lines = len(data["lines"])
    for i, r in enumerate(grid, start=1):
        for j, v in enumerate(r, start=1):
            ws.cell(i, j, v)
    ws["A1"].font = Font(size=16, bold=True)
    for i in range(3, header):  # khối thông tin
        if ws.cell(i, 1).value:
            ws.cell(i, 1).font = Font(bold=True)
            c = ws.cell(i, 2)
            c.fill, c.border = (yellow if ws.cell(i, 1).value == "Ngày bắt đầu" else tint), box
            ws.cell(i, 3).font = Font(italic=True, color="6B6A5E")
    for j in range(1, len(grid[header]) + 1):
        c = ws.cell(header + 1, j)
        c.fill, c.font, c.border, c.alignment = navy, white, box, Alignment(horizontal="center" if j > 3 else "left")
    for k, ln in enumerate(data["lines"]):
        i = header + 2 + k
        for j in range(1, len(grid[header]) + 1):
            c = ws.cell(i, j)
            c.border = box
            if j <= 3:
                c.font = Font(bold=j == 1)
            else:
                c.alignment = Alignment(horizontal="center")
                c.number_format = "0%" if ln["kind"] == "rank" and ln["unit"] == "pct" else "#,##0"
    first_note = header + 2 + n_lines + 1
    for i in range(first_note, first_note + len(NOTES)):
        ws.cell(i, 1).font = Font(bold=i == first_note, italic=i > first_note, color="4A4A42")
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 12
    for j in range(4, len(grid[header]) + 1):
        ws.column_dimensions[_col(j)].width = 12

    kw = wb.create_sheet(KW_TAB)
    for j, t in enumerate(["Từ khóa", "URL mục tiêu", "Top target", "Ghi chú"], start=1):
        c = kw.cell(1, j, t)
        c.fill, c.font, c.border = navy, white, box
    for i, row in enumerate(keywords, start=2):
        for j, v in enumerate(row[:4], start=1):
            kw.cell(i, j, v if v is not None else "")
    for col, w in zip("ABCD", (38, 60, 14, 30)):
        kw.column_dimensions[col].width = w
    kw.freeze_panes = "A2"


def template_xlsx(project: str, keywords: list[tuple], data: dict | None = None) -> bytes:
    """File Excel chỉ có hai tab KPI (Drive chuyển thành Google Sheet). Không có `data` thì điền số của dự án mẫu,
    ngày bắt đầu để trống: điền ngày bắt đầu thì tool mới bắt đầu chấm."""
    import io

    from openpyxl import Workbook
    wb = Workbook()
    del wb[wb.active.title]
    fill_workbook(wb, data or sample_data(project), keywords)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def workbook_from_master(xlsx: bytes, data: dict, keywords: list[tuple]) -> bytes:
    """Sheet dự án dựng từ bản xlsx của sheet mẫu gốc: thay hai tab KPI, điền ngày bắt đầu vào ô cạnh nhãn 'Bắt đầu'
    của tab OKRs. Đường này chỉ cần quyền drive.file (xuất rồi tải lên lại), nên chạy được với token cũ."""
    import io

    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(xlsx))
    fill_workbook(wb, data, keywords)
    start = data.get("start")
    okr = next((x for x in wb.worksheets if _norm_tab(x.title).startswith("okr")), None)
    if okr is not None and start:
        for row in okr.iter_rows(min_row=1, max_row=5, max_col=26):
            for c in row:
                if isinstance(c.value, str) and "bắt đầu" in c.value.lower():
                    okr.cell(c.row, c.column + 1, date.fromisoformat(start)).number_format = "dd/mm/yyyy"
                    break
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def create_template(con, cfg) -> dict:
    """Tạo sheet mẫu trong folder Drive của tool (quyền drive.file), điền sẵn các từ khóa đang check rank."""
    from . import drive as D, keywords as K, rank as R
    svc = D.build_service(cfg)
    folder, _ = D.target_folder(con, svc, cfg.site_url, cfg.drive_parent)
    host = domain(cfg.site_url)
    kws = [(k["keyword"], k["target_url"] or "")
           for k in R.primary_keywords(con, cfg.site_url, K.latest_date(con, cfg.site_url))]
    f = D.upload(svc, template_xlsx(f"SEO {host}", kws), f"KPI cam kết SEO – {host}", D.XLSX, folder, D.SHEET)
    set_sheet(con, f["id"])
    return f


# ---- Thiết lập cam kết (wizard) và tạo sheet dự án ----

def spread(final: float, count: int, start_value: float = 0.0, integer: bool = False) -> list:
    """`count` giá trị tăng tuyến tính từ start_value tới final (giá trị cuối đúng bằng final), làm gợi ý theo tháng."""
    if count <= 0:
        return []
    out = [start_value + (final - start_value) * (k + 1) / count for k in range(count)]
    return [int(round(v)) for v in out] if integer else [round(v, 2) for v in out]


def split_total(total: int, count: int) -> list[int]:
    """Chia tổng thành count phần nguyên gần bằng nhau; phần cuối nhận phần dư."""
    if count <= 0:
        return []
    base = int(total) // count
    out = [base] * count
    out[-1] += int(total) - base * count
    return out


def plan(spec: dict) -> dict:
    """Dữ liệu tab KPI từ lựa chọn trên wizard. spec = {project, start, months (số tháng), baseline: {organic, ai},
    rank: {tops: [3, 5, 10], mode: shared|per_tier, unit: pct|count, from: tháng bắt đầu chấm, finals: {top: mốc cuối}},
    traffic: {organic: {level: mức tăng cuối dự án | None, cum: tổng tăng thêm | None}, ai: {…}}}.
    Chỉ tiêu từng tháng chỉ là gợi ý chia đều; sửa trên sheet hoặc trên tool sau."""
    n = max(1, int(spec.get("months") or 1))
    months = list(range(1, n + 1))
    base = spec.get("baseline") or {}
    lines = []
    rk = spec.get("rank") or {}
    finals = {int(k): v for k, v in (rk.get("finals") or {}).items() if v is not None}
    frm = max(1, min(n, int(rk.get("from") or 1)))
    for top in sorted(int(t) for t in rk.get("tops") or []):
        vals = spread(finals[top], n - frm + 1, 0, integer=rk.get("unit") == "count") if top in finals else []
        targets = {str(m): None for m in months}
        for k, m in enumerate(range(frm, n + 1)):
            targets[str(m)] = vals[k] if vals else None
        lines.append({"kind": "rank", "top": top, "mode": rk.get("mode") or "shared", "unit": rk.get("unit") or "pct",
                      "targets": targets})
    for src in ("organic", "ai"):
        t = (spec.get("traffic") or {}).get(src) or {}
        if t.get("level") is not None:
            b = base.get(src) or 0
            vals = spread(b + int(t["level"]), n, b, integer=True)
            lines.append({"kind": "level", "source": src, "targets": {str(m): vals[m - 1] for m in months}})
        if t.get("cum") is not None:
            vals = split_total(int(t["cum"]), n)
            lines.append({"kind": "cum", "source": src, "targets": {str(m): vals[m - 1] for m in months}})
    return {"project": spec.get("project") or "", "start": spec.get("start") or None, "months": months,
            "baseline": {"organic": base.get("organic"), "ai": base.get("ai")}, "lines": lines}


def baseline_suggest(sessions, start: date, n_months: int = 3) -> dict:
    """Baseline gợi ý = trung bình phiên/tháng của n_months tháng lịch trọn vẹn trước tháng bắt đầu, từng nguồn.
    sessions(source, s, e) -> {ngày: phiên} (ga4_sessions)."""
    first = start.replace(day=1)
    windows = []
    for _ in range(n_months):
        end = first - timedelta(days=1)
        first = end.replace(day=1)
        windows.append((first, end))
    windows.reverse()
    out = {"months": []}
    for s, e in windows:
        row = {"label": f"{s:%m/%Y}"}
        for src in SOURCES:
            row[src] = _period_sessions(sessions, src, s, e)
        out["months"].append(row)
    for src in SOURCES:
        out[src] = int(round(sum(m[src] for m in out["months"]) / len(out["months"]))) if out["months"] else None
    return out


def parse_keyword_text(text: str) -> list[tuple[str, str, int | None]]:
    """Từ khóa dán trong wizard, mỗi dòng một từ: 'từ khóa | URL mục tiêu | Top 3' (URL và Top không bắt buộc, thứ tự
    tùy ý; cũng nhận dấu tab)."""
    out, seen = [], set()
    for raw in (text or "").splitlines():
        parts = [x.strip() for x in re.split(r"\||\t", raw) if x.strip()]
        if not parts or parts[0].startswith("#"):
            continue
        kw, url, target = parts[0], "", None
        for x in parts[1:]:
            if x.lower().startswith("http"):
                url = x
            elif re.fullmatch(r"(?i)top\s*\d+|\d+", x):
                target = _top(x)
        if kw.lower() in seen:
            continue
        seen.add(kw.lower())
        out.append((kw, url, target))
    return out


def sheet_values(data: dict, keywords: list[tuple]) -> dict[str, list[list]]:
    """Các ô của hai tab KPI để ghi lên Google Sheet (hoặc file mẫu)."""
    kw_rows = [["Từ khóa", "URL mục tiêu", "Top target", "Ghi chú"]]
    for row in keywords:
        kw, url, target = (list(row) + [None, None])[:3]
        kw_rows.append([kw, url or "", f"Top {target}" if target else "", ""])
    return {KPI_TAB: kpi_grid(data), KW_TAB: kw_rows}


def _norm_tab(t: str) -> str:
    t = t.strip().lower()
    for p in ("bản sao của ", "copy of "):
        t = t.removeprefix(p)
    return t


class TabNotFound(ValueError):
    """Không tìm được tab KPI / Từ khóa cam kết trong sheet (thường do đổi tên mà tên mới không đoán được)."""

    def __init__(self, want: str, titles: list[str]):
        self.want, self.titles = want, titles
        super().__init__(f"Sheet không có tab '{want}' (có thể đã đổi tên). Các tab đang có: "
                         + ", ".join(f"'{t}'" for t in titles) + ". Đổi lại tên tab, hoặc chọn tab ở màn KPI cam kết.")


def _plain(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", _norm_tab(t).replace("đ", "d"))
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def _looks_like(want: str, title: str) -> bool:
    """Tên tab mới có còn giống tab cần tìm không (khách hay thêm số thứ tự / chữ: "2. KPI SEO 12 tháng")."""
    t = _plain(title)
    if want == KPI_TAB:
        return "kpi" in t and "okr" not in t
    return "cam ket" in t and ("tu khoa" in t or "keyword" in t)


def tab_ids(con, sid: str) -> dict[str, int]:
    """Mã tab (sheetId, không đổi khi đổi tên tab) đã nhận ra của sheet này: {KPI_TAB: …, KW_TAB: …}."""
    raw = _setting(con, "kpi_tab_ids")
    return {k: int(v) for k, v in (json.loads(raw).get(sid, {}) if raw else {}).items()}


def set_tab_id(con, sid: str, want: str, gid: int) -> None:
    raw = _setting(con, "kpi_tab_ids")
    allv = json.loads(raw) if raw else {}
    allv.setdefault(sid, {})[want] = int(gid)
    _setting(con, "kpi_tab_ids", json.dumps(allv))


def resolve_tab(props: list[dict], want: str, saved: dict[str, int]) -> dict | None:
    """Tab cần tìm trong danh sách tab của sheet: mã tab đã lưu (đổi tên vẫn đúng) → tên chuẩn ("Bản sao của …" vẫn
    nhận) → tên gần giống, chỉ khi có đúng một tab khớp (không đoán bừa khi có nhiều tab giống nhau)."""
    gid = saved.get(want)
    hit = next((p for p in props if gid is not None and p.get("sheetId") == gid), None)
    if hit:
        return hit
    hit = next((p for p in props if _norm_tab(p["title"]) == want.lower()), None)
    if hit:
        return hit
    like = [p for p in props if _looks_like(want, p["title"])]
    return like[0] if len(like) == 1 else None


def _saved_ids(cfg, sid: str) -> dict[str, int]:
    from contextlib import closing

    from . import db
    try:
        with closing(db.connect(cfg.db_path)) as c:
            return tab_ids(c, sid)
    except Exception:  # noqa: BLE001  (test / không có DB)
        return {}


def _remember(cfg, sid: str, found: dict[str, dict]) -> None:
    from contextlib import closing

    from . import db
    try:
        with closing(db.connect(cfg.db_path)) as c:
            have = tab_ids(c, sid)
            for want, p in found.items():
                if p and have.get(want) != p["sheetId"]:
                    set_tab_id(c, sid, want, p["sheetId"])
    except Exception:  # noqa: BLE001
        pass


def _format_requests(tab: dict, rows: list[list], is_kpi: bool) -> list[dict]:
    """Định dạng tab vừa ghi: tiêu đề đậm nền xanh, % cho dòng Top theo %, số có dấu phân cách, độ rộng cột."""
    sid = tab["sheetId"]

    def cell_fmt(r0, r1, c0, c1, fmt, fields):
        return {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                                         "startColumnIndex": c0, "endColumnIndex": c1},
                               "cell": {"userEnteredFormat": fmt}, "fields": fields}}

    def width(c0, c1, px):
        return {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c0,
                                                        "endIndex": c1}, "properties": {"pixelSize": px},
                                              "fields": "pixelSize"}}

    navy = {"red": 0.12, "green": 0.23, "blue": 0.41}
    head = {"backgroundColor": navy, "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}
    if not is_kpi:
        return [cell_fmt(0, 1, 0, 4, head, "userEnteredFormat(backgroundColor,textFormat)"),
                width(0, 1, 280), width(1, 2, 420), width(2, 3, 100), width(3, 4, 220)]
    h = next(i for i, r in enumerate(rows) if r and r[0] == "Loại")
    ncol = len(rows[h])
    out = [cell_fmt(0, 1, 0, 1, {"textFormat": {"bold": True, "fontSize": 14}}, "userEnteredFormat.textFormat"),
           cell_fmt(2, h, 0, 1, {"textFormat": {"bold": True}}, "userEnteredFormat.textFormat"),
           cell_fmt(h, h + 1, 0, ncol, head, "userEnteredFormat(backgroundColor,textFormat)"),
           width(0, 1, 180), width(1, 2, 160), width(2, 3, 90), width(3, ncol, 90)]
    for i in range(h + 1, len(rows)):
        r = rows[i]
        if not r:
            break
        pct = len(r) > 2 and r[2] == "%"
        out.append(cell_fmt(i, i + 1, 3, ncol, {"numberFormat": {"type": "PERCENT" if pct else "NUMBER",
                                                                  "pattern": "0%" if pct else "#,##0"},
                                                 "horizontalAlignment": "CENTER"},
                            "userEnteredFormat(numberFormat,horizontalAlignment)"))
        out.append(cell_fmt(i, i + 1, 0, 1, {"textFormat": {"bold": True}}, "userEnteredFormat.textFormat"))
    return out


def write_tabs(sh, sid: str, values: dict[str, list[list]], saved_ids: dict[str, int] | None = None) -> None:
    """Ghi (đè) các tab KPI vào sheet dự án: tab chưa có thì thêm; tab 'Bản sao của …' vẫn nhận ra."""
    meta = sh.spreadsheets().get(spreadsheetId=sid, fields="sheets(properties(sheetId,title))").execute()
    props = [x["properties"] for x in meta["sheets"]]
    saved = saved_ids if saved_ids is not None else {}
    tabs = {_norm_tab(p["title"]): p for p in props}
    for want in values:  # tab đã đổi tên (nhận theo mã tab / tên gần giống): ghi vào đó, không thêm tab mới
        hit = resolve_tab(props, want, saved)
        if hit:
            tabs[_norm_tab(want)] = hit
    reqs = [{"addSheet": {"properties": {"title": t}}} for t in values if _norm_tab(t) not in tabs]
    if reqs:
        resp = sh.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": reqs}).execute()
        for r in resp.get("replies", []):
            p = r["addSheet"]["properties"]
            tabs[_norm_tab(p["title"])] = p
    fmt = []
    for title, rows in values.items():
        tab = tabs[_norm_tab(title)]
        rng = "'" + tab["title"].replace("'", "''") + "'"
        sh.spreadsheets().values().clear(spreadsheetId=sid, range=rng, body={}).execute()
        sh.spreadsheets().values().update(spreadsheetId=sid, range=rng + "!A1", valueInputOption="USER_ENTERED",
                                          body={"values": rows}).execute()
        fmt += _format_requests(tab, rows, title == KPI_TAB)
    if fmt:
        sh.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": fmt}).execute()


def set_okr_start(sh, sid: str, start: str | None) -> bool:
    """Điền ngày bắt đầu dự án vào ô cạnh nhãn 'Bắt đầu' ở tab OKRs (nếu có); lỗi gì cũng bỏ qua."""
    if not start:
        return False
    try:
        meta = sh.spreadsheets().get(spreadsheetId=sid, fields="sheets(properties(title))").execute()
        title = next((x["properties"]["title"] for x in meta["sheets"]
                      if _norm_tab(x["properties"]["title"]).startswith("okr")), None)
        if not title:
            return False
        rng = "'" + title.replace("'", "''") + "'"
        rows = sh.spreadsheets().values().get(spreadsheetId=sid, range=rng + "!A1:Z5").execute().get("values", [])
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                if "bắt đầu" in str(v).lower() and j + 1 < 26:
                    cell = f"{rng}!{_col(j + 2)}{i + 1}"
                    sh.spreadsheets().values().update(spreadsheetId=sid, range=cell, valueInputOption="USER_ENTERED",
                                                      body={"values": [[f"{start[8:10]}/{start[5:7]}/{start[:4]}"]]}
                                                      ).execute()
                    return True
    except Exception:  # noqa: BLE001  (tab OKR khác mẫu: không sao, người dùng tự điền)
        return False
    return False


def create_project_sheet(con, cfg, data: dict, keywords: list[tuple], master: str = "") -> dict:
    """Tạo sheet dự án trong folder Drive của dự án: copy sheet mẫu gốc (OKRs, Weekly Task, Chi phí, Content…) rồi ghi
    hai tab KPI; chưa có sheet mẫu gốc thì tạo file chỉ có hai tab KPI. Gắn luôn làm sheet KPI của dự án."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    from . import auth
    from . import drive as D
    name = f"Sheet dự án – {domain(cfg.site_url)}"
    creds = auth.get_credentials(cfg, need=(auth.DRIVE_SCOPE,))
    drv = build("drive", "v3", credentials=creds, cache_discovery=False)
    folder = D.root_folder(con, drv, cfg.site_url, cfg.drive_parent)
    if not master:
        f = D.upload(drv, template_xlsx(data["project"], keywords, data), name, D.XLSX, folder, D.SHEET)
    elif not auth.missing_scopes(creds.scopes or [], (auth.DRIVE_FULL_SCOPE, auth.SHEETS_WRITE_SCOPE)):
        # Đủ quyền: copy trên Drive (giữ nguyên mọi thứ) rồi ghi hai tab KPI bằng Sheets API
        f = drv.files().copy(fileId=master, body={"name": name, "parents": [folder]},
                             fields="id, name, webViewLink").execute()
        sh = build("sheets", "v4", credentials=creds, cache_discovery=False)
        write_tabs(sh, f["id"], sheet_values(data, keywords))
        set_okr_start(sh, f["id"], data.get("start"))
    else:
        # Token cũ (drive.file): chỉ xuất được sheet mẫu gốc do tool tạo; dựng xlsx rồi tải lên thành Google Sheet
        try:
            xlsx = drv.files().export(fileId=master, mimeType=D.XLSX).execute()
        except HttpError as e:
            if e.resp.status in (403, 404):
                raise SystemExit("Tool chưa có quyền Google Drive đầy đủ để copy sheet mẫu gốc này. Chạy lại: python "
                                 "-m seo_report login (đăng nhập Google lại một lần, tích đủ các ô quyền)") from e
            raise
        f = D.upload(drv, workbook_from_master(xlsx, data, keywords), name, D.XLSX, folder, D.SHEET)
    set_sheet(con, f["id"])
    return f


# ---- Sửa cam kết trên tool (ghi ngược vào sheet) ----

def _a1(col: int) -> str:
    out = ""
    col += 1
    while col:
        col, r = divmod(col - 1, 26)
        out = chr(65 + r) + out
    return out


def keyword_row_plan(rows: list[list], op: str, keyword: str, url: str | None = None,
                     target: int | None = None) -> dict:
    """Cách sửa đúng một dòng của tab Từ khóa cam kết (giữ nguyên các cột khác như Ghi chú):
    {"action": "update", "row": i, "cells": {cột: giá trị}} | {"action": "append", "values": [...]} |
    {"action": "delete", "row": i} | {"action": "header", "col": j} (thêm cột Top target trước) | {"action": "none"}.
    row / col tính từ 0."""
    col, start = _kw_columns(rows)
    key = " ".join(keyword.split()).lower()
    idx = next((i for i in range(start, len(rows)) if col["kw"] < len(rows[i]) and
                " ".join(str(rows[i][col["kw"]]).split()).lower() == key), None)
    if op == "delete":
        return {"action": "delete", "row": idx} if idx is not None else {"action": "none"}
    if col["target"] is None and target is not None:
        width = max([len(r) for r in rows[:max(start, 1)]] + [2])
        return {"action": "header", "col": width, "header_row": max(start - 1, 0)}
    cells = {col["url"]: url or ""}
    if col["target"] is not None:
        cells[col["target"]] = f"Top {target}" if target else ""
    if idx is None:
        width = max(cells) + 1
        values = [""] * max(width, col["kw"] + 1)
        values[col["kw"]] = keyword
        for j, v in cells.items():
            values[j] = v
        return {"action": "append", "values": values}
    return {"action": "update", "row": idx, "cells": cells}


def sheet_keyword_op(cfg, sid: str, op: str, keyword: str, url: str | None = None, target: int | None = None) -> None:
    """Sửa một từ khóa cam kết ngay trên Google Sheet: op 'upsert' (thêm / sửa URL mục tiêu + Top target) hoặc
    'delete'. Chỉ đụng dòng của từ khóa đó; đọc sheet ngay trước khi ghi nên không đè sửa của người khác ở dòng
    khác. Cần quyền ghi Google Sheets. Sau đó gọi sync() để tool đọc lại."""
    from googleapiclient.discovery import build

    from . import auth
    sh = build("sheets", "v4", credentials=auth.get_credentials(cfg, need=(auth.SHEETS_WRITE_SCOPE,)),
               cache_discovery=False)
    meta = sh.spreadsheets().get(spreadsheetId=sid, fields="sheets(properties(sheetId,title))").execute()
    props = [x["properties"] for x in meta["sheets"]]
    tab = resolve_tab(props, KW_TAB, _saved_ids(cfg, sid))
    if tab is None:
        # Có tab KPI (sheet đã dùng) mà không thấy tab từ khóa: có thể đã đổi tên khó đoán → không tự tạo tab trùng
        if resolve_tab(props, KPI_TAB, _saved_ids(cfg, sid)) is not None or op == "delete":
            raise TabNotFound(KW_TAB, [p["title"] for p in props])
        write_tabs(sh, sid, {KW_TAB: [["Từ khóa", "URL mục tiêu", "Top target", "Ghi chú"]]})
        return sheet_keyword_op(cfg, sid, op, keyword, url, target)
    _remember(cfg, sid, {KW_TAB: tab})
    name = "'" + tab["title"].replace("'", "''") + "'"
    for _ in range(2):  # lần đầu có thể chỉ thêm cột Top target
        rows = sh.spreadsheets().values().get(spreadsheetId=sid, range=name + "!A1:Z2000",
                                              valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
        plan = keyword_row_plan(rows, "delete" if op == "delete" else "upsert", keyword, url, target)
        if plan["action"] != "header":
            break
        sh.spreadsheets().values().update(
            spreadsheetId=sid, range=f"{name}!{_a1(plan['col'])}{plan['header_row'] + 1}",
            valueInputOption="USER_ENTERED", body={"values": [["Top target"]]}).execute()
    if plan["action"] == "update":
        data = [{"range": f"{name}!{_a1(j)}{plan['row'] + 1}", "values": [[v]]} for j, v in plan["cells"].items()]
        sh.spreadsheets().values().batchUpdate(spreadsheetId=sid, body={"valueInputOption": "USER_ENTERED",
                                                                        "data": data}).execute()
    elif plan["action"] == "append":
        sh.spreadsheets().values().append(spreadsheetId=sid, range=name + "!A1", valueInputOption="USER_ENTERED",
                                          insertDataOption="INSERT_ROWS", body={"values": [plan["values"]]}).execute()
    elif plan["action"] == "delete":
        sh.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [{"deleteDimension": {"range": {
            "sheetId": tab["sheetId"], "dimension": "ROWS", "startIndex": plan["row"],
            "endIndex": plan["row"] + 1}}}]}).execute()


class SheetChanged(Exception):
    """Sheet đã bị sửa từ lúc mở form: không ghi đè khi chưa hỏi lại."""


def fingerprint(tables: dict[str, list[list]]) -> str:
    """Dấu vân nội dung hai tab KPI, để biết sheet có bị sửa trong lúc form đang mở không."""
    import hashlib
    raw = json.dumps({k: tables.get(k, []) for k in (KPI_TAB, KW_TAB)}, ensure_ascii=False, sort_keys=True,
                     default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def keyword_text(keywords: list) -> str:
    """Từ khóa cam kết → chữ dán được vào ô nhập (ngược với parse_keyword_text)."""
    lines = []
    for k in keywords:
        kw, url, target = (k["keyword"], k.get("url"), k.get("target")) if isinstance(k, dict) else \
            (list(k) + [None, None])[:3]
        parts = [kw] + ([url] if url else []) + ([f"Top {target}"] if target else [])
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def load_for_edit(cfg, sid: str, today: date | None = None) -> dict:
    """Đọc sheet để sửa trên tool: {data, keywords (tuple), fingerprint, old_format}."""
    tables = fetch(cfg, sid)
    data = parse_kpi(tables[KPI_TAB], today or date.today())
    kws = [(k["keyword"], k["url"], k["target"]) for k in parse_keywords(tables.get(KW_TAB, []))]
    old = not any(_label(r).startswith("loại") for r in tables[KPI_TAB])
    return {"data": data, "keywords": kws, "fingerprint": fingerprint(tables), "old_format": old}


def write_sheet(cfg, sid: str, data: dict, keywords: list, expect: str | None = None, force: bool = False) -> str:
    """Ghi hai tab KPI (bố cục mới) vào sheet đang gắn. Khi `expect` (dấu vân lúc mở form) khác sheet hiện tại và
    không `force` thì raise SheetChanged. Cần quyền ghi Google Sheets. Trả về dấu vân mới."""
    from googleapiclient.discovery import build

    from . import auth
    creds = auth.get_credentials(cfg, need=(auth.SHEETS_WRITE_SCOPE,))
    if expect and not force and fingerprint(fetch(cfg, sid)) != expect:
        raise SheetChanged("Sheet đã bị sửa từ lúc bạn mở form")
    sh = build("sheets", "v4", credentials=creds, cache_discovery=False)
    write_tabs(sh, sid, sheet_values(data, keywords), _saved_ids(cfg, sid))
    return fingerprint(fetch(cfg, sid))
