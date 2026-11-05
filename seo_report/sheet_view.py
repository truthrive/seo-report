"""Sheet dự án là nơi XEM: tool ghi (đè) các tab, sửa trên sheet sẽ bị ghi đè ở lần ghi sau.

- "KPI cam kết": các dòng cam kết theo tháng (phiên bản KPI mới nhất trên tool).
- "Bộ – <tên bộ>": mỗi bộ từ khóa một tab: từ khóa, URL / Top mục tiêu, ghi chú, hạng mới nhất, mỗi lần check một cột.
- "Dữ liệu check": mỗi dòng là một từ khóa trong một lần check (để lọc, làm pivot).

Tool nhớ mã tab (sheetId) của từng tab nên khách đổi tên tab vẫn ghi đúng chỗ; bộ bị xóa thì tab của bộ bị xóa theo.
Tab được khóa ở chế độ "cảnh báo khi sửa". Không tốn tiền (Google Sheets API miễn phí).
"""
import json
from datetime import date, datetime, timezone

from . import kpi as KP
from . import rank as R

DATA_TAB = "Dữ liệu check"
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


def plan(con, site: str, end: date, today: date | None = None) -> dict[str, tuple[str, list[list]]]:
    """Các tab cần ghi: {khóa: (tên tab, các ô)}. Khóa "kpi", "data", "set:<id>"."""
    stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
    out: dict[str, tuple[str, list[list]]] = {}
    ver = KP.version_at(KP.versions(con), today or date.today())
    if ver:
        out["kpi"] = (KP.KPI_TAB, KP.kpi_grid(ver))
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
    want = plan(con, site, K.latest_date(con, site), today)
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
        if key.startswith("set:") and key not in want and gid in props and gid not in ids.values():
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
        else:
            fmt += _format(gid, rows, header_row=3 if key.startswith("set:") else 1)
        if not any(p.get("description") == PROTECT_TAG for p in props.get(gid, {}).get("protectedRanges") or []):
            fmt.append({"addProtectedRange": {"protectedRange": {"range": {"sheetId": gid}, "warningOnly": True,
                                                                 "description": PROTECT_TAG}}})
    if fmt:
        sh.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": fmt}).execute()
    info = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tabs": len(want),
            "rows": len(want["data"][1]) - 2, "deleted": deleted}
    KP._setting(con, "sheet_view_published", json.dumps(info))
    return info


def _format(gid: int, rows: list[list], header_row: int) -> list[dict]:
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
    if header_row > 1:  # tab bộ
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
                         "WHERE site = ?", (site,)).fetchone()]
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
