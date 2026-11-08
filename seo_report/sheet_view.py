"""Sheet dự án là nơi XEM: tool ghi (đè) các tab, sửa trên sheet sẽ bị ghi đè ở lần ghi sau.

Ai sửa tab nào (chốt 2026-11-07):
- Tool ghi đè + khóa: "Thông tin dự án", "KPI cam kết", "OKRs <đợt>" (khi OKR đã chuyển sang tool), "Bộ – <tên bộ>",
  "Dữ liệu check".
- Team sửa trên sheet, tool chỉ đọc: "Weekly Task Tracker" (tool chỉ khóa hàng tiêu đề cột).
- Team sửa, tool không đụng: "Content", "Đề xuất chi phí" và mọi tab khác.

- "KPI cam kết": các dòng cam kết theo tháng (phiên bản KPI mới nhất trên tool).
- "Bộ – <tên bộ>": mỗi bộ từ khóa một tab: từ khóa, URL / Top mục tiêu, ghi chú, hạng mới nhất, mỗi lần check một cột.
- "Dữ liệu check": mỗi dòng là một từ khóa trong một lần check (để lọc, làm pivot).

Tool nhớ mã tab (sheetId) của từng tab nên khách đổi tên tab vẫn ghi đúng chỗ; bộ bị xóa thì tab của bộ bị xóa theo.
Tab được khóa ở chế độ "cảnh báo khi sửa". Không tốn tiền (Google Sheets API miễn phí).
"""
import json
from datetime import date, datetime, timezone

from . import kpi as KP
from . import okr as O
from . import rank as R
from .projects import domain

DATA_TAB = "Dữ liệu check"
INFO_TAB = "Thông tin dự án"
HEADER_TAG = "seo-report-header"  # khóa (cảnh báo) hàng tiêu đề tab Weekly Task Tracker: tool đọc theo tên cột
SET_PREFIX = "Bộ – "
NOTE = "Tab do tool SEO Report ghi tự động: thêm / sửa trên tool. Sửa ở đây sẽ bị ghi đè ở lần cập nhật sau."
MAX_DATE_COLS = 26  # tab bộ: tối đa 26 lần check gần nhất (khoảng nửa năm nếu check hằng tuần)
PROTECT_TAG = "seo-report"
_SETTING = "sheet_view_tabs"  # {sheet id: {"kpi": gid, "data": gid, "set:<id>": gid}}


def set_title(name: str) -> str:
    bad = "[]*?/\\:"
    clean = "".join("-" if ch in bad else ch for ch in name).strip()
    return (SET_PREFIX + clean)[:90]


def _vn(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def _rank_cell(rank, depth):
    if rank is not None:
        return rank
    return f">{depth}" if depth else ""


def set_rows(con, site: str, end: date, st: dict, stamp: str) -> list[list]:
    kws = R.keywords(con, site, end, st["id"])
    ids = [k["id"] for k in kws]
    dates, cells = [], {}
    if ids:
        marks = ",".join("?" * len(ids))
        dates = [d for (d,) in con.execute(f"SELECT DISTINCT check_date FROM rank_checks WHERE keyword_id IN ({marks}) "
                                           f"ORDER BY check_date DESC LIMIT {MAX_DATE_COLS}", ids)]
        if dates:
            for kid, d, rank, depth in con.execute(
                    f"SELECT keyword_id, check_date, rank, depth FROM rank_checks WHERE keyword_id IN ({marks}) "
                    f"AND check_date >= ?", (*ids, dates[-1])):
                cells[(kid, d)] = _rank_cell(rank, depth)
    kind = R.SET_KINDS.get(st["kind"], st["kind"])
    state = "Nháp (chưa check)" if st.get("draft") else ("Tạm dừng" if st.get("paused") else "Đang chạy")
    rows = [[f"Bộ {st['name']} · {kind} · {state} · {R.describe_schedule(st['schedule'])}"],
            [f"{NOTE} Cập nhật {stamp}."], [],
            ["Từ khóa", "URL mục tiêu", "Top mục tiêu", "Ghi chú", "Tạm dừng", "Hạng mới nhất", "Ngày check",
             "URL đang xếp hạng"] + [_vn(d) for d in dates]]
    for k in kws:
        rows.append([k["keyword"], k["target_url"] or "", f"Top {k['top_target']}" if k["top_target"] else "",
                     k["note"] or "", "Có" if k["own_paused"] else "",
                     _rank_cell(k["rank"], k["last_depth"]) if k["date"] else "",
                     _vn(k["date"]) if k["date"] else "", k["ranking_url"] or ""]
                    + [cells.get((k["id"], d), "") for d in dates])
    return rows


def data_rows(con, site: str, stamp: str) -> list[list]:
    """Mỗi từ khóa của mỗi bộ trong mỗi lần check: mới trước."""
    rows = [[f"{NOTE} Cập nhật {stamp}."],
            ["Ngày check", "Bộ", "Từ khóa", "Hạng", "Độ sâu", "URL đang xếp hạng", "URL mục tiêu",
             "Hạng URL mục tiêu", "AI Overview", "Website được AI trích"]]
    q = con.execute(
        """SELECT c.check_date, s.name, k.keyword, c.rank, c.depth, c.ranking_url, u.url, c.target_rank, sp.aio,
                  sp.aio_cited
           FROM rank_checks c JOIN rank_keywords k ON k.id = c.keyword_id JOIN rank_sets s ON s.id = k.set_id
           LEFT JOIN urls u ON u.id = k.url_id
           LEFT JOIN rank_serp sp ON sp.keyword_id = c.keyword_id AND sp.check_date = c.check_date
           WHERE k.site = ? AND k.removed_at IS NULL ORDER BY c.check_date DESC, s.position, s.id, k.keyword""",
        (site,))
    for d, set_name, kw, rank, depth, rurl, turl, trank, aio, cited in q:
        rows.append([_vn(d), set_name, kw, _rank_cell(rank, depth), depth, rurl or "", turl or "",
                     trank if trank is not None else "",
                     "" if aio is None else ("Có" if aio else "Không"),
                     "" if not aio or cited is None else ("Có" if cited else "Không")])
    return rows


def _saved(con, sid: str) -> dict[str, int]:
    raw = KP._setting(con, _SETTING)
    return {k: int(v) for k, v in (json.loads(raw).get(sid, {}) if raw else {}).items()}


def _save(con, sid: str, ids: dict[str, int]) -> None:
    raw = KP._setting(con, _SETTING)
    allv = json.loads(raw) if raw else {}
    allv[sid] = ids
    KP._setting(con, _SETTING, json.dumps(allv))


def info_rows(con, site: str, stamp: str, weekly_tab: str, ver: dict | None) -> tuple[list[list], int]:
    """Tab Thông tin dự án: thông tin chung + bảng quy ước tab nào sửa ở đâu. Trả (các ô, chỉ số hàng tiêu đề bảng)."""
    start = (ver or {}).get("start")
    months = len((ver or {}).get("months") or [])
    rows = [[f"Thông tin dự án · {domain(site)}"], [f"{NOTE} Cập nhật {stamp}."], [],
            ["Website", site],
            ["Bắt đầu dự án", _vn(start) if start else "Chưa đặt (đặt ở KPI cam kết trên tool)"],
            ["Thời gian cam kết", f"{months} tháng" if months else "Chưa có KPI cam kết"],
            ["Sheet này", "Do tool SEO Report quản lý. Tab của tool được ghi lại mỗi khi dữ liệu trên tool đổi."], [],
            ["Tab", "Ai sửa", "Ghi chú"]]
    head = len(rows) - 1
    rows += [[INFO_TAB, "Tool", "Tool ghi, không sửa ở đây."],
             [KP.KPI_TAB, "Tool", "Sửa trên tool: KPI cam kết → Sửa cam kết."],
             ["OKRs <đợt>", "Tool", "Sửa trên tool: Công việc & OKR → Sửa OKR. Mỗi đợt một tab."],
             [f"{SET_PREFIX}<tên bộ>", "Tool", "Từ khóa và thứ hạng của từng bộ; sửa trên tool: Từ khóa & Thứ hạng."],
             [DATA_TAB, "Tool", "Mỗi từ khóa trong mỗi lần check, để lọc / làm pivot."],
             [weekly_tab, "Team, trên sheet", "Tool chỉ đọc. Không đổi tên cột ở hàng tiêu đề (tool đọc theo tên cột)."],
             ["Content", "Team, trên sheet", "Tool không đụng vào."],
             ["Đề xuất chi phí", "Team, trên sheet", "Tool không đụng vào."],
             ["Tab khác", "Team, trên sheet", "Tool không đụng vào."]]
    return rows, head


def plan(con, site: str, end: date, today: date | None = None,
         weekly_tab: str = "Weekly Task Tracker") -> dict[str, tuple[str, list[list]]]:
    """Các tab cần ghi: {khóa: (tên tab, các ô)}. Khóa "info", "kpi", "okr:<mã đợt>", "set:<id>", "data"."""
    stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
    out: dict[str, tuple[str, list[list]]] = {}
    ver = KP.version_at(KP.versions(con), today or date.today())
    out["info"] = (INFO_TAB, info_rows(con, site, stamp, weekly_tab, ver)[0])
    if ver:
        out["kpi"] = (KP.KPI_TAB, KP.kpi_grid(ver))
    if O.tool_owned(con):  # OKR sửa trên tool: mỗi đợt một tab (khóa theo mã đợt, đổi tên đợt vẫn đúng tab)
        ids = O.cycle_ids(con)
        for c in O.cycle_list(con):
            out[f"okr:{ids[c['name']]}"] = (O.tab_title(c["name"]), O.sheet_rows(con, c["name"], NOTE, stamp, today))
    for st in R.sets(con, site):
        out[f"set:{st['id']}"] = (set_title(st["name"]), set_rows(con, site, end, st, stamp))
    out[DATA_TAB] = (DATA_TAB, data_rows(con, site, stamp))
    return out


def publish(con, cfg, today: date | None = None, sh=None) -> dict:
    """Ghi các tab xem lên sheet dự án. Không có sheet: bỏ qua. Trả {"tabs": n, "rows": n, "deleted": n}."""
    from . import keywords as K
    sid = KP.sheet_id(con)
    if not sid:
        return {"skipped": "Dự án chưa gắn sheet"}
    if sh is None:
        from googleapiclient.discovery import build

        from . import auth
        sh = build("sheets", "v4", credentials=auth.get_credentials(cfg, need=(auth.SHEETS_WRITE_SCOPE,)),
                   cache_discovery=False)
    site = cfg.site_url
    KP.snapshot_keywords(con, site, today or date.today())
    weekly_tab = getattr(getattr(cfg, "okr", None), "weekly_tab", "Weekly Task Tracker")
    want = plan(con, site, K.latest_date(con, site), today, weekly_tab)
    want = {("data" if k == DATA_TAB else k): v for k, v in want.items()}
    meta = sh.spreadsheets().get(spreadsheetId=sid, fields="sheets(properties(sheetId,title),protectedRanges("
                                                           "protectedRangeId,description,range))").execute()
    props = {x["properties"]["sheetId"]: x for x in meta["sheets"]}
    by_title = {x["properties"]["title"].strip().lower(): x["properties"]["sheetId"] for x in meta["sheets"]}
    saved = _saved(con, sid)
    old_ids = KP.tab_ids(con, sid)  # tab KPI / Từ khóa cam kết tool đã nhận ra trước đây (đổi tên vẫn đúng)
    linked = (R.kpi_set(con, site) or {}).get("id")
    # Tab KPI: chỉ ghi vào tab tool tự tạo (tên đúng "KPI cam kết" hoặc đã ghi trước đây). KHÔNG nhận tab KPI khách
    # tự thiết kế (đọc trước đây, vd "2. KPI SEO 12 tháng": có ghi chú, công thức) — tool tạo tab riêng bên cạnh.
    if linked and f"set:{linked}" not in saved and old_ids.get(KP.KW_TAB) in props:
        saved[f"set:{linked}"] = old_ids[KP.KW_TAB]  # tab Từ khóa cam kết cũ thành tab của bộ Cam kết
    reqs, ids, final = [], {}, {}  # final: tên tab thật sau khi ghi (đổi tên trùng tab khác thì giữ tên cũ)
    for key, (title, _) in want.items():
        gid = saved.get(key)
        if gid not in props:
            gid = by_title.get(title.strip().lower())
        if gid in props and gid not in ids.values():
            ids[key] = gid
            now_title = props[gid]["properties"]["title"]
            final[key] = now_title
            # tab KPI giữ tên khách đặt ("2. KPI SEO 12 tháng"); tab bộ đổi theo tên bộ
            if key != "kpi" and now_title != title and title.strip().lower() not in {t for t, g in by_title.items() if g != gid}:
                reqs.append({"updateSheetProperties": {"properties": {"sheetId": gid, "title": title},
                                                       "fields": "title"}})
                final[key] = title
        else:
            if title.strip().lower() in by_title:  # tên đã có ở tab khác của khách: thêm hậu tố
                title = f"{title} (tool)"
            want[key] = (title, want[key][1])
            final[key] = title
            reqs.append({"addSheet": {"properties": {"title": title}}})
    deleted = 0
    for key, gid in saved.items():  # bộ đã xóa: xóa tab của bộ
        if key.startswith(("set:", "okr:")) and key not in want and gid in props and gid not in ids.values():
            reqs.append({"deleteSheet": {"sheetId": gid}})
            deleted += 1
    if reqs:
        resp = sh.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": reqs}).execute()
        added = [r["addSheet"]["properties"] for r in resp.get("replies", []) if r.get("addSheet")]
        for key, (title, _) in want.items():
            if key not in ids:
                p = next(x for x in added if x["title"] == title)
                ids[key] = p["sheetId"]
                props[p["sheetId"]] = {"properties": p, "protectedRanges": []}
    _save(con, sid, ids)
    ranges = ["'" + final[k].replace("'", "''") + "'" for k in want]
    sh.spreadsheets().values().batchClear(spreadsheetId=sid, body={"ranges": ranges}).execute()
    sh.spreadsheets().values().batchUpdate(spreadsheetId=sid, body={
        "valueInputOption": "RAW",
        "data": [{"range": r + "!A1", "values": want[k][1]} for k, r in zip(want, ranges)]}).execute()
    fmt = []
    for key, (title, rows) in want.items():
        gid = ids[key]
        tab = {"sheetId": gid, "title": final[key]}
        if key == "kpi":
            fmt += KP._format_requests(tab, rows, True)
        elif key.startswith("okr:"):
            fmt += _format(gid, rows, header_row=3, widths="okr")
        elif key == "info":
            fmt += _format(gid, rows, header_row=info_rows(con, site, "", weekly_tab, None)[1], widths="info")
        else:
            fmt += _format(gid, rows, header_row=3 if key.startswith("set:") else 1)
        if not any(p.get("description") == PROTECT_TAG for p in props.get(gid, {}).get("protectedRanges") or []):
            fmt.append({"addProtectedRange": {"protectedRange": {"range": {"sheetId": gid}, "warningOnly": True,
                                                                 "description": PROTECT_TAG}}})
    fmt += _weekly_header_lock(sh, sid, meta, weekly_tab, set(ids.values()))
    if fmt:
        sh.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": fmt}).execute()
    info = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tabs": len(want),
            "rows": len(want["data"][1]) - 2, "deleted": deleted}
    KP._setting(con, "sheet_view_published", json.dumps(info))
    return info


def _weekly_header_lock(sh, sid: str, meta: dict, weekly_tab: str, ours: set[int]) -> list[dict]:
    """Tab Weekly Task Tracker của team: chỉ khóa (cảnh báo) hàng tiêu đề cột, một lần; không ghi gì vào tab."""
    tab = next((x for x in meta["sheets"] if x["properties"]["title"].strip().lower() == weekly_tab.strip().lower()
                and x["properties"]["sheetId"] not in ours), None)
    if not tab or any(p.get("description") == HEADER_TAG for p in tab.get("protectedRanges") or []):
        return []
    title = tab["properties"]["title"]
    vals = sh.spreadsheets().values().get(spreadsheetId=sid, range="'" + title.replace("'", "''") + "'!A1:Z10").execute()
    for i, r in enumerate(vals.get("values", [])):
        if "ngày" in [str(c).strip().lower() for c in r]:
            return [{"addProtectedRange": {"protectedRange": {
                "range": {"sheetId": tab["properties"]["sheetId"], "startRowIndex": i, "endRowIndex": i + 1},
                "warningOnly": True, "description": HEADER_TAG}}}]
    return []


def _format(gid: int, rows: list[list], header_row: int, widths: str = "") -> list[dict]:
    ncol = max((len(r) for r in rows), default=1)
    navy = {"red": 0.12, "green": 0.23, "blue": 0.41}
    head = {"backgroundColor": navy, "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}

    def width(c0, c1, px):
        return {"updateDimensionProperties": {"range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": c0,
                                                        "endIndex": c1}, "properties": {"pixelSize": px},
                                              "fields": "pixelSize"}}
    out = [{"repeatCell": {"range": {"sheetId": gid, "startRowIndex": header_row, "endRowIndex": header_row + 1,
                                     "startColumnIndex": 0, "endColumnIndex": ncol},
                           "cell": {"userEnteredFormat": head}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
           {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
                           "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                           "fields": "userEnteredFormat.textFormat"}},
           {"updateSheetProperties": {"properties": {"sheetId": gid, "gridProperties": {
               "frozenRowCount": header_row + 1, "frozenColumnCount": 1 if header_row > 1 else 0}},
               "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}}]
    if widths == "okr":  # ID · Nhóm · Hạng mục · Task details · SL · ĐV · Tháng · Start · End · PIC · TT · % · Link · CB
        out += [width(0, 1, 64), width(1, 2, 110), width(2, 3, 320), width(3, 4, 260), width(4, 7, 80),
                width(7, 9, 96), width(9, 10, 120), width(10, 11, 110), width(11, 12, 80), width(12, 14, 200),
                {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": header_row + 1, "startColumnIndex": 11,
                                          "endColumnIndex": 12},
                                "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                                "fields": "userEnteredFormat.numberFormat"}}]
    elif widths == "info":
        out += [width(0, 1, 190), width(1, 2, 160), width(2, 3, 520)]
    elif header_row > 1:  # tab bộ
        out += [width(0, 1, 260), width(1, 2, 300), width(2, 5, 100), width(5, 7, 100), width(7, 8, 300),
                width(8, ncol, 78)]
    else:
        out += [width(0, 2, 110), width(2, 3, 260), width(3, 5, 70), width(5, 7, 300), width(7, 10, 120)]
    return out


def published(con) -> dict | None:
    raw = KP._setting(con, "sheet_view_published")
    return json.loads(raw) if raw else None


def fingerprint(con, site: str) -> str:
    """Đổi khi dữ liệu cần ghi lên sheet đổi (check mới, sửa từ khóa / bộ, phiên bản KPI mới)."""
    R.ensure_tables(con)
    KP.ensure_tables(con)
    parts = [con.execute("SELECT MAX(checked_at), COUNT(*) FROM rank_checks").fetchone(),
             con.execute("SELECT MAX(at), COUNT(*) FROM change_log WHERE site = ?", (site,)).fetchone(),
             con.execute("SELECT MAX(id) FROM kpi_versions").fetchone(),
             con.execute("SELECT COUNT(*), MAX(id), GROUP_CONCAT(name || state || schedule) FROM rank_sets "
                         "WHERE site = ?", (site,)).fetchone(),
             O.changed_at(con), O.tool_owned(con)]
    return json.dumps(parts, default=str)


def publish_if_changed(con, cfg) -> dict | None:
    """Ghi lên sheet khi dữ liệu đổi từ lần ghi trước (gọi định kỳ bởi máy chủ web)."""
    if not KP.sheet_id(con):
        return None
    fp = fingerprint(con, cfg.site_url)
    if KP._setting(con, "sheet_view_fp") == fp:
        return None
    info = publish(con, cfg)
    KP._setting(con, "sheet_view_fp", fingerprint(con, cfg.site_url))
    return info


# ---- Tạo / gắn sheet dự án ----

WEEKLY_HEAD = ["Ngày", "Loại task", "Mã OKR", "Hạng mục liên kết", "Task tuần / hành động", "Link / Evidence",
               "Vướng mắc", "PIC", "Ưu tiên", "Start date", "Deadline", "Trạng thái", "% Tiến độ", "Blocker / Ghi chú"]


def _template_tabs(titles: list[str]) -> list[str]:
    """Tab mẫu trong bản chép của sheet mẫu gốc mà tool sẽ tự ghi bản của nó: bỏ đi để sheet mới không có hai bản."""
    tool = {KP.KPI_TAB.lower(), KP.KW_TAB.lower()}
    return [t for t in titles if t.strip().lower() in tool or t.strip().lower().startswith("okr")]


def create_project_sheet(con, cfg, master: str = "") -> dict:
    """Tạo sheet dự án trong folder Drive của dự án rồi gắn làm sheet dự án và ghi các tab của tool.
    Có sheet mẫu gốc: chép nguyên (Weekly Task Tracker, Content, Đề xuất chi phí…), bỏ các tab mẫu tool sẽ tự ghi.
    Chưa có sheet mẫu gốc: tạo sheet trống có sẵn tab Weekly Task Tracker (đúng tên cột tool đọc).
    Trả {"id", "name", "webViewLink"}."""
    from googleapiclient.discovery import build

    from . import auth
    from . import drive as D
    creds = auth.get_credentials(cfg, need=(auth.SHEETS_WRITE_SCOPE,))
    if auth.missing_scopes(creds.scopes or [], (auth.DRIVE_FULL_SCOPE if master else auth.DRIVE_SCOPE,
                                                 auth.SHEETS_WRITE_SCOPE)):
        raise SystemExit("Tool chưa đủ quyền Google Drive / Sheets để tạo sheet dự án. Chủ tool vào Cài đặt tích hợp → "
                         "Kết nối Google, đăng nhập lại và tích đủ các ô quyền.")
    drv = build("drive", "v3", credentials=creds, cache_discovery=False)
    sh = build("sheets", "v4", credentials=creds, cache_discovery=False)
    name = f"Sheet dự án – {domain(cfg.site_url)}"
    folder = D.root_folder(con, drv, cfg.site_url, getattr(cfg, "drive_parent", ""))
    weekly = getattr(getattr(cfg, "okr", None), "weekly_tab", "Weekly Task Tracker")
    if master:
        f = drv.files().copy(fileId=master, body={"name": name, "parents": [folder]},
                             fields="id, name, webViewLink").execute()
        meta = sh.spreadsheets().get(spreadsheetId=f["id"], fields="sheets(properties(sheetId,title))").execute()
        tabs = {x["properties"]["title"]: x["properties"]["sheetId"] for x in meta["sheets"]}
        drop = _template_tabs(list(tabs))
        if drop and len(drop) < len(tabs):  # sheet phải còn ít nhất một tab
            sh.spreadsheets().batchUpdate(spreadsheetId=f["id"], body={"requests": [
                {"deleteSheet": {"sheetId": tabs[t]}} for t in drop]}).execute()
    else:
        f = drv.files().create(body={"name": name, "mimeType": D.SHEET, "parents": [folder]},
                               fields="id, name, webViewLink").execute()
        meta = sh.spreadsheets().get(spreadsheetId=f["id"], fields="sheets(properties(sheetId,title))").execute()
        first = meta["sheets"][0]["properties"]["sheetId"]
        sh.spreadsheets().batchUpdate(spreadsheetId=f["id"], body={"requests": [
            {"updateSheetProperties": {"properties": {"sheetId": first, "title": weekly}, "fields": "title"}}]}).execute()
        sh.spreadsheets().values().update(spreadsheetId=f["id"], range=f"'{weekly}'!A1", valueInputOption="RAW",
                                          body={"values": [[f"{weekly} · team cập nhật task tuần ở đây"],
                                                           WEEKLY_HEAD]}).execute()
    KP.set_sheet(con, f["id"])
    publish(con, cfg, sh=sh)
    KP._setting(con, "sheet_view_fp", fingerprint(con, cfg.site_url))
    return f


def attach_sheet(con, cfg, link: str) -> dict:
    """Gắn sheet dự án đã có: chỉ thêm / ghi các tab của tool, không đụng tab của team."""
    KP.set_sheet(con, link)
    info = publish(con, cfg)
    KP._setting(con, "sheet_view_fp", fingerprint(con, cfg.site_url))
    return info
