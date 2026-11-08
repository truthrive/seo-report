"""Màn Cam kết KPI (Quản trị) và khối "Tiến độ KPI" trên Tổng quan / báo cáo. Số cam kết đọc từ Google Sheet; mỗi cam
kết là một dòng (kpi.py), màn hình vẽ một ô cho mỗi dòng."""
from contextlib import closing
from datetime import date

from . import ai_format as F
from . import kpi as KP
from . import ui_theme as T

ICONS = {"green": "check_circle", "amber": "error_outline", "red": "error_outline", "grey": "hourglass_empty"}
KT_STYLE = (".sr-kt{width:100%;border-collapse:collapse;font-size:13px}.sr-kt th{background:#1F221E;color:#fff;"
            "font-weight:600;padding:8px;text-align:center}.sr-kt th .d{font-weight:400;font-size:11px;opacity:.75}"
            ".sr-kt td{padding:7px 8px;border-bottom:1px solid #EEECE4;text-align:center}.sr-kt td.lab{text-align:left;"
            "font-weight:600;white-space:nowrap}.sr-kt tr.sub td{background:#FAFAF7}.sr-kt tr.sub td.lab{font-weight:400;"
            "color:#6B6A5E;padding-left:20px}.sr-kt td .d{font-size:11px;color:#6B6A5E}.sr-kt th .d{color:#D9D8CF}.sr-kt .ok{color:#1E7C31;"
            "font-weight:700}.sr-kt .bad{color:#C2410C;font-weight:700}.sr-kt .warn{color:#8F5F14;font-weight:700}"
            ".sr-kt .mut{color:#B8B6A8}")


def _vn(iso) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso else "–"


def _pct(v) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def _signed(v) -> str:
    return "–" if v is None else ("+" if v >= 0 else "−") + F.n(abs(v))


def load_progress(cfg, today: date | None = None) -> dict | None:
    """Tính tiến độ (gọi GA4 nên chạy trong run.io_bound)."""
    from . import db
    today = today or date.today()
    with closing(db.connect(cfg.db_path)) as c:
        if not KP.versions(c):
            return None
        try:
            ga4 = KP.ga4_sessions(cfg, c)
        except (Exception, SystemExit):  # noqa: BLE001  (chưa đăng nhập GA4: vẫn hiện phần thứ hạng)
            ga4 = None
        p = KP.progress(c, cfg.site_url, today, ga4)
        if p is not None:
            p["ga4"] = ga4 is not None
        return p


def _rank_target(ch: dict) -> str:
    """Cam kết thứ hạng ghi cả hai cách: '40% (16 từ khóa)' hoặc '16 từ khóa (40%)'."""
    if ch["unit"] == "pct":
        return _pct(ch["target_pct"]) + (f" ({ch['need']} từ khóa)" if ch["need"] is not None else "")
    return f"{int(ch['target'])} từ khóa" + (f" ({_pct(ch['target_pct'])})" if ch["target_pct"] is not None else "")


TILE_LOOK = {3: ("emoji_events", "green"), 5: ("workspace_premium", "blue"), 10: ("format_list_numbered", "lime")}


def _tile(ui, line: dict, ch: dict, running: bool, has_ga4: bool) -> None:
    """Một ô tiến độ: icon + tên + trạng thái, số lớn kèm đơn vị, thanh tiến độ (vạch đen = mức cam kết), gợi ý."""
    text, tone = KP.status(ch, running)
    committed = ch["target"] is not None
    icon, look = (TILE_LOOK.get(line.get("top"), ("leaderboard", "green")) if ch["kind"] == "rank"
                  else ("trending_up", "purple"))
    unit = ""
    fill = ahead = mark = None  # thanh: phần đậm / phần nhạt (dự báo) / vạch cam kết, cùng thang 0–1
    if ch["kind"] == "rank":
        value = "chưa check" if not ch["checked"] else (_pct(ch["actual"]) if ch["total"] else "–")
        unit = f"{ch['count']}/{ch['total']} từ khóa" if ch["checked"] and ch["total"] else ""
        hint = f"Cam kết {_rank_target(ch)}" if committed else "Tháng này không cam kết"
        if not ch["checked"]:
            hint = "Chưa có lần check nào trong tháng này" + (f" · cam kết {_rank_target(ch)}" if committed else "")
        if ch["total"] and ch["checked"]:
            fill = ch["count"] / ch["total"]
            if committed and ch["need"]:
                mark = min(ch["need"] / ch["total"], 1)
    elif not has_ga4:
        value, hint = "chưa có", "Chưa kết nối GA4"
    elif ch["kind"] == "level":
        value = F.n(ch["actual"]) if ch["actual"] is not None else "chưa có"
        unit = "phiên"
        parts = [f"Cam kết {F.n(ch['target'])}" if committed else "Tháng này không cam kết"]
        if running and ch.get("forecast") is not None:
            parts.append(f"dự báo cuối tháng {F.n(ch['forecast'])}")
        elif running and ch.get("expected") is not None and ch["actual"] is not None:
            parts.append(f"{ch['days_done']} ngày đầu cần khoảng {F.n(ch['expected'])}")
        hint = " · ".join(parts)
        if ch["actual"] is not None:
            top = max(ch["target"] or 0, ch.get("forecast") or 0, ch["actual"]) or 1
            fill = ch["actual"] / top
            ahead = (ch["forecast"] / top) if running and ch.get("forecast") else None
            mark = (ch["target"] / top) if committed and ch["target"] else None
    else:  # tích lũy: số lớn là lũy kế
        cum = ch["cum"]
        value = _signed(cum) if cum is not None else (_signed(ch["actual"]) if ch["actual"] is not None else "chưa có")
        unit = "lũy kế"
        if ch["baseline"] is None:
            hint = "Chưa có số gốc để so"
        else:
            hint = f"Cam kết cả dự án {F.n(ch['total'])} · tháng này {_signed(ch['actual'])}"
            if running and ch.get("forecast_inc") is not None:
                hint += f" · dự báo {_signed(ch['forecast_inc'])}"
        if ch["total"] and cum is not None:
            fill = min(max(cum, 0) / ch["total"], 1)
            mark = min(ch["plan_cum"] / ch["total"], 1) if ch.get("plan_cum") is not None else None
    muted_value = value in ("chưa check", "chưa có")
    bar = T.TONES[tone][1] if committed and tone != "grey" else T.TONES[look][1]
    bg_icon, fg_icon = T.TONES[look]
    with ui.element("div").classes("sr-kp-tile"):
        with ui.row().classes("items-center no-wrap w-full").style("gap:8px"):
            with ui.element("div").classes("sr-db-bubble").style(f"background:{bg_icon}"):
                ui.icon(icon, size="15px").style(f"color:{fg_icon}").props('aria-hidden="true"')
            ui.label(KP.line_label(line)).classes("sr-kp-label col ellipsis")
            if committed:  # tháng không cam kết: đã đếm ở dòng đầu khối, không lặp chip trên từng ô
                with ui.element("span").classes(f"sr-kp-chip {tone}"):
                    ui.icon(ICONS.get(tone, "remove"), size="13px").props('aria-hidden="true"')
                    ui.label(text)
        with ui.row().classes("items-baseline no-wrap").style("gap:8px; margin-top:6px"):
            ui.label(value).classes("sr-kp-value num" + (" muted" if muted_value else ""))
            if unit and not muted_value:
                ui.label(unit).classes("sr-kp-unit")
        if fill is not None:
            title = f"Đạt {fill / mark * 100:.0f}% mức cam kết" if mark else ""
            html = (f'<div class="sr-kp-bar" title="{title}">'
                    + (f'<i style="width:{min(ahead, 1) * 100:.1f}%;background:{bar};opacity:.25"></i>'
                       if ahead else "")
                    + f'<i style="width:{min(fill, 1) * 100:.1f}%;background:{bar}"></i>'
                    + (f'<b style="left:{mark * 100:.1f}%"></b>' if mark else "") + "</div>")
            ui.html(html).classes("w-full")
        ui.label(hint).classes("sr-kp-hint")


def kpi_skeleton(ui, n_lines: int = 4) -> None:
    """Khung chờ cùng hình dạng khối Tiến độ KPI (dòng ngày + chip, lưới ô: icon · tên, số lớn, thanh, gợi ý)."""
    with T.section(ui, "Tiến độ KPI cam kết", "flag", "Đang tính tiến độ…"):
        with ui.element("div").classes("sr-kp-strip"):
            T.bone(ui, "14px", "240px")
            T.bone(ui, "22px", "120px", "999px")
        with ui.element("div").classes("sr-kp-grid"):
            for _ in range(n_lines):
                with ui.element("div").classes("sr-kp-tile"):
                    with ui.row().classes("items-center no-wrap w-full").style("gap:8px"):
                        T.bone(ui, "28px", "28px", "50%")
                        T.bone(ui, "14px", "55%")
                    T.bone(ui, "30px", "45%").style("margin-top:8px")
                    T.bone(ui, "7px", "100%", "4px").style("margin:8px 0 6px")
                    T.bone(ui, "12px", "75%")
                    T.bone(ui, "12px", "45%").style("margin-top:4px")  # gợi ý thường dài hai dòng
        T.bone(ui, "12px", "40%").style("margin-top:2px")  # dòng chú thích dưới lưới


def _month_strip(ui, m: dict, running: bool, p: dict, free: list[str]) -> None:
    """Dòng đầu khối: tháng đã trôi bao nhiêu ngày (thanh mảnh) + đếm trạng thái các cam kết."""
    d0, d1 = date.fromisoformat(m["from"]), date.fromisoformat(m["to"])
    days = (d1 - d0).days + 1
    done = days if not running else max(0, min(days, (date.today() - d0).days + 1))
    counts = {"green": 0, "amber": 0, "red": 0}
    for line in p["lines"]:
        ch = m["checks"].get(KP.line_id(line))
        if ch and ch["target"] is not None:
            _, tone = KP.status(ch, running)
            if tone in counts:
                counts[tone] += 1
    with ui.element("div").classes("sr-kp-strip"):
        with ui.element("div").classes("sr-kp-days"):
            ui.label(f"Ngày {done}/{days}" if running else f"Đã chốt · {days} ngày").classes("sr-kp-days-text")
            ui.html(f'<div class="sr-kp-bar thin"><i style="width:{done / days * 100:.1f}%;background:#1F221E">'
                    "</i></div>").classes("col")
        with ui.row().classes("items-center gap-2"):
            for tone, label in (("green", "Đang đạt" if running else "Đạt"), ("amber", "Đang thiếu"),
                                ("red", "Không đạt")):
                if counts[tone]:
                    with ui.element("span").classes(f"sr-kp-chip {tone}"):
                        ui.icon(ICONS[tone], size="13px").props('aria-hidden="true"')
                        ui.label(f"{label} {counts[tone]}")
            if free:
                with ui.element("span").classes("sr-kp-chip grey") as chip:
                    ui.icon("remove", size="13px").props('aria-hidden="true"')
                    ui.label(f"Không cam kết {len(free)}")
                chip.tooltip("Tháng này không cam kết: " + ", ".join(free))


def kpi_block(ui, p: dict | None, compact: bool = True) -> None:
    """Khối tiến độ của tháng dự án đang chạy (hoặc tháng gần nhất đã chốt)."""
    if not p:
        return
    if not p.get("start"):
        with T.section(ui, "Tiến độ KPI cam kết", "flag", "Chưa nhập ngày bắt đầu dự án trong sheet KPI",
                       href="/kpi" if compact else None, link_text="Mở Cam kết KPI"):
            ui.label("Điền 'Ngày bắt đầu' trong sheet KPI cam kết rồi bấm Đồng bộ để tool bắt đầu chấm.").classes(
                "text-sm muted")
        return
    months = [m for m in p["months"] if m["status"] != "future"]
    if not months:
        first = p["months"][0] if p["months"] else None
        with T.section(ui, "Tiến độ KPI cam kết", "flag", f"Dự án bắt đầu {_vn(first['from']) if first else '–'}",
                       href="/kpi" if compact else None, link_text="Mở Cam kết KPI"):
            ui.label("Dự án chưa bắt đầu.").classes("text-sm muted")
        return
    m = next((x for x in months if x["status"] == "running"), months[-1])
    running = m["status"] == "running"
    total = len(p["months"])
    free = [KP.line_label(ln).replace("Từ khóa top", "Top") for ln in p["lines"]
            if (m["checks"].get(KP.line_id(ln)) or {}).get("target", 0) is None]
    sub = (f"{_vn(m['from'])} – {_vn(m['to'])} · {m['rank']['total']} từ khóa cam kết"
           + (" · đang chạy, số còn thay đổi" if running else " · đã chốt"))
    with T.section(ui, f"Tiến độ KPI · Tháng dự án {m['n']}/{total}" + (f" · {p['project']}" if p.get("project") else ""),
                   "flag", sub, href="/kpi" if compact else None, link_text=f"Xem {total} tháng"):
        _month_strip(ui, m, running, p, free)
        with ui.element("div").classes("sr-kp-grid"):
            for line in p["lines"]:
                ch = m["checks"].get(KP.line_id(line))
                if ch:
                    _tile(ui, line, ch, running, bool(p.get("ga4")))
        notes = []
        if m["rank"].get("target_set"):
            notes.append(f"{m['rank']['target_ok']}/{m['rank']['target_set']} từ khóa đạt Top mục tiêu riêng "
                         "của từng từ khóa")
        if m["rank"]["checked"] < m["rank"]["total"]:
            left = m["rank"]["total"] - m["rank"]["checked"]
            notes.append(f"{left} từ khóa chưa có lần check nào trong tháng này" + (
                (": lịch check tự động sẽ cập nhật" if T.client_view() else
                 ": lịch check tự động sẽ cập nhật, hoặc bấm Kiểm tra thứ hạng ở màn Từ khóa & Thứ hạng") if running
                else ": tính là chưa đạt"))
        if notes:
            ui.label(" · ".join(notes)).classes("text-xs muted")


def _target_cell(line: dict, t, n: int) -> str:
    if t is None:
        return "–"
    if line["kind"] == "rank":
        return KP.fmt_target(line, t)
    if line["kind"] == "level":
        return F.n(t)
    plan_cum = sum(v for k, v in line["targets"].items() if v is not None and int(k) <= n)
    return f'{_signed(t)}<div class="d">lũy kế {F.n(plan_cum)}</div>'


def _actual_cell(ch: dict, m: dict) -> str:
    if ch["kind"] == "rank":
        if not ch["checked"] and m["status"] == "running":
            return '<span class="mut">chưa check</span>'
        val = f'{_pct(ch["actual"]) if ch["total"] else "–"}<div class="d">{ch["count"]}/{ch["total"]} từ khóa</div>'
    elif ch["kind"] == "level":
        val = F.n(ch["actual"]) if ch["actual"] is not None else "chưa có"
        if m["status"] == "running" and ch.get("forecast") is not None:
            val += f'<div class="d">dự báo {F.n(ch["forecast"])}</div>'
    else:
        if ch["baseline"] is None:
            return '<span class="mut">chưa có baseline</span>'
        val = _signed(ch["actual"]) if ch["actual"] is not None else "chưa có"
        if ch["cum"] is not None:
            val += f'<div class="d">lũy kế {"dự báo " if m["status"] == "running" else ""}{F.n(ch["cum"])}</div>'
        if m["status"] == "running" and ch.get("forecast_inc") is not None:
            val += f'<div class="d">dự báo {_signed(ch["forecast_inc"])}</div>'
    cls = "" if ch["ok"] is None else ("ok" if ch["ok"] else ("warn" if m["status"] == "running" else "bad"))
    return f'<span class="{cls}">{val}</span>'


def full_table(ui, p: dict) -> None:
    """Bảng cả dự án giống sheet: mỗi tháng một cột, mỗi cam kết hai dòng (cam kết / thực tế)."""
    months = p["months"]
    head = "".join(f'<th>Tháng {m["n"]}<div class="d">{_vn(m.get("from"))} – {_vn(m.get("to"))}</div></th>'
                   for m in months)
    rows = []
    for line in p["lines"]:
        lid = KP.line_id(line)
        full = {**line, "targets": {str(m["n"]): (m.get("targets") or {}).get(lid) for m in months}}
        tgt = [_target_cell(full, full["targets"][str(m["n"])], m["n"]) for m in months]
        act = []
        for m in months:
            ch = (m.get("checks") or {}).get(lid)
            act.append(_actual_cell(ch, m) if ch and m["status"] != "future" else '<span class="mut">·</span>')
        rows.append((KP.line_label(line) + " · cam kết", tgt))
        rows.append(("Thực tế", act))
    body = "".join(f'<tr class="{"sub" if lab == "Thực tế" else ""}"><td class="lab">{lab}</td>'
                   + "".join(f"<td>{c}</td>" for c in cells) + "</tr>" for lab, cells in rows)
    cur = next((i for i, m in enumerate(months) if m.get("status") == "running"), None)
    style = KT_STYLE
    if cur is not None:
        style += f".sr-kt tr td:nth-child({cur + 2}){{box-shadow:inset 2px 0 #1E7C31,inset -2px 0 #1E7C31}}"
    ui.add_head_html(f"<style>{style}</style>")  # ui.html lọc bỏ thẻ <style> nên đặt ở <head>
    ui.html(f'<div style="overflow-x:auto"><table class="sr-kt"><thead><tr><th style="text-align:'
            f'left">Cam kết</th>{head}</tr></thead><tbody>{body}</tbody></table></div>').classes("w-full")
    base = p.get("baseline") or {}
    if any(ln["kind"] == "cum" for ln in p["lines"]):
        ui.label("Baseline: " + " · ".join(
            f"{KP.SOURCES[k]} {F.n(base.get(k)) if base.get(k) is not None else 'chưa nhập'} phiên/tháng"
            for k in ("organic", "ai") if any(ln["kind"] == "cum" and ln["source"] == k for ln in p["lines"]))
                 + " · tăng thêm = phiên tháng − baseline, cộng dồn qua các tháng").classes("text-xs muted q-mt-sm")


def build_kpi_page(ui, cfg, connect, user, app_connect=None, project: dict | None = None) -> None:
    from nicegui import run

    from .access import can_edit, is_client
    ed = can_edit(user)
    cl = is_client(user)  # khách hàng: chỉ tiến độ KPI; không trạng thái sheet, lịch sử phiên bản, lỗi kỹ thuật
    with connect() as c:
        sid = KP.sheet_id(c)
    with connect() as c:
        has_versions = bool(KP.versions(c)) if sid else False
    right = T.page_header(ui, "flag", "Cam kết KPI",
                          "Thứ hạng bộ từ khóa cam kết và phiên Organic / AI Assistant theo từng tháng dự án."
                          + ("" if cl else " Sửa trên tool; sheet dự án để xem (tool tự ghi)."), eyebrow="KPI")
    with right:
        if sid and ed:  # người chỉ xem không mở được sheet nội bộ
            ui.button("Mở sheet", icon="open_in_new", on_click=lambda: ui.navigate.to(
                f"https://docs.google.com/spreadsheets/d/{sid}/edit", new_tab=True)).props("outline no-caps")
        if sid and ed and has_versions:
            ui.button("Sửa cam kết", icon="edit", on_click=lambda: ui.navigate.to("/kpi/sua")).props(
                "outline no-caps")
            sync_btn = ui.button("Ghi lên sheet", icon="upload", on_click=lambda: do_publish()).props(
                "unelevated no-caps").tooltip("Ghi ngay tab KPI cam kết, tab từng bộ từ khóa và tab Dữ liệu check "
                                              "(tool cũng tự ghi khi dữ liệu đổi)")
        elif sid and ed:  # sheet vừa gắn: nhập một lần từ sheet, sau đó tool là nơi quản lý
            sync_btn = ui.button("Nhập từ sheet", icon="download", on_click=lambda: do_sync()).props(
                "unelevated no-caps")
        if sid and ed:
            with ui.button(icon="more_vert").props("flat round dense color=grey-8"):
                with ui.menu():
                    ui.menu_item("Đổi sheet / tạo sheet dự án mới", on_click=lambda: ask_unlink())

    def ask_unlink():
        with ui.dialog() as dlg, ui.card().style("border-radius:16px; max-width:520px"):
            ui.label("Gỡ sheet đang gắn?").classes("text-lg font-semibold")
            ui.label("Tool thôi đọc sheet này; file trên Drive vẫn còn. Sau đó màn KPI hiện wizard tạo sheet dự án "
                     "mới (hoặc ô dán link sheet khác). Phiên bản KPI đã lưu của sheet này vẫn giữ: dán lại link cũ "
                     "là dùng tiếp.").classes("text-sm")

            def go():
                with connect() as c:
                    KP.unlink_sheet(c)
                dlg.close()
                ui.navigate.reload()

            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Gỡ sheet", on_click=go).props("unelevated no-caps color=negative")
        dlg.open()

    async def do_publish():
        from . import sheet_view as SV
        sync_btn.props("loading")
        try:
            def work():
                with connect() as c:
                    info = SV.publish(c, cfg)
                    KP._setting(c, "sheet_view_fp", SV.fingerprint(c, cfg.site_url))
                    return info
            r = await run.io_bound(work)
            ui.notify(f"Đã ghi {r['tabs']} tab lên sheet ({r['rows']} dòng dữ liệu check)", type="positive")
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không ghi được lên sheet: {e}", type="negative", multi_line=True)
        finally:
            sync_btn.props(remove="loading")

    async def do_sync():
        sync_btn.props("loading")
        try:
            def work():
                with connect() as c:
                    return KP.sync(c, cfg, user)
            r = await run.io_bound(work)
            msg = (f"Đã đồng bộ: {r['months']} tháng, {r.get('lines', 0)} cam kết, {r['keywords']} từ khóa cam kết"
                   + (f", thêm {r['added']} từ khóa vào check rank" if r["added"] else "")
                   + ("" if r["changed"] else " · KPI không đổi"))
            ui.notify(msg, type="positive")
            if r["over_budget"]:
                ui.notify(f"{len(r['over_budget'])} từ khóa chưa thêm được vì vượt ngân sách check rank",
                          type="warning", multi_line=True)
            if r["bad_url"]:
                ui.notify(f"{len(r['bad_url'])} dòng có URL mục tiêu không thuộc site: {r['bad_url'][0]}",
                          type="warning", multi_line=True)
        except KP.TabNotFound as e:  # tab đổi tên mà không đoán được: cho chọn tab, tool nhớ theo mã tab
            sync_btn.props(remove="loading")
            pick_tab(e)
            return
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không đồng bộ được: {e}", type="negative", multi_line=True)
        finally:
            sync_btn.props(remove="loading")
        ui.navigate.reload()

    def pick_tab(err) -> None:
        """Chọn tab thay cho tab không tìm thấy; tool lưu mã tab (không đổi khi đổi tên) rồi đồng bộ lại."""
        if not ed:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        label = {KP.KPI_TAB: "tab KPI cam kết", KP.KW_TAB: "tab Từ khóa cam kết"}.get(err.want, err.want)
        with ui.dialog() as dlg, ui.card().style("min-width: 460px; max-width: 94vw; border-radius: 14px"):
            ui.label(f"Không tìm thấy {label}").classes("text-lg font-semibold")
            ui.label("Có thể tab đã được đổi tên trên Google Sheets. Chọn đúng tab, tool sẽ nhớ tab này kể cả khi đổi "
                     "tên lần sau.").classes("text-sm muted")
            sel = ui.select(err.titles, label="Tab trong sheet").props("outlined dense").classes("w-full")

            async def go():
                if not sel.value:
                    return

                def work():
                    from googleapiclient.discovery import build

                    from . import auth
                    svc = build("sheets", "v4", credentials=auth.get_credentials(cfg, need=(auth.SHEETS_SCOPE,)),
                                cache_discovery=False)
                    meta = svc.spreadsheets().get(spreadsheetId=sid,
                                                  fields="sheets(properties(sheetId,title))").execute()
                    gid = next(x["properties"]["sheetId"] for x in meta["sheets"]
                               if x["properties"]["title"] == sel.value)
                    with connect() as c:
                        KP.set_tab_id(c, sid, err.want, gid)
                await run.io_bound(work)
                dlg.close()
                await do_sync()

            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Dùng tab này", on_click=go).props("unelevated no-caps color=primary")
        dlg.open()

    if not sid:
        if cl:
            T.empty_state(ui, "flag", "Chưa có KPI cam kết", "Tiến độ KPI sẽ hiện ở đây khi cam kết được thiết lập.")
            return
        _setup(ui, cfg, connect, ed, user, app_connect, project)
        return

    from . import sheet_view as SV
    with connect() as c:
        KP.snapshot_keywords(c, cfg.site_url, date.today())  # từ khóa cam kết theo bộ Cam kết trên tool
        vs, pub = KP.versions(c), SV.published(c)
    if pub and not cl:
        T.status_chip(ui, f"Ghi lên sheet lúc {_local(pub['at'])} · {pub['tabs']} tab", "grey", "schedule")
    if not vs:
        if cl:
            T.empty_state(ui, "flag", "Chưa có KPI cam kết", "Tiến độ KPI sẽ hiện ở đây khi cam kết được thiết lập.")
        else:
            T.empty_state(ui, "download", "Chưa có KPI trên tool", "Bấm Nhập từ sheet để lấy KPI cam kết và từ khóa "
                          "từ sheet một lần; sau đó sửa trên tool.")
        return

    box = ui.column().classes("w-full gap-4").props('aria-busy="true"')
    with box:
        kpi_skeleton(ui, len((vs[-1]["data"] or {}).get("lines") or []) or 4)

    async def load():
        try:
            p = await run.io_bound(lambda: load_progress(cfg))
        except (Exception, SystemExit) as e:  # noqa: BLE001
            box.clear()
            with box:
                T.status_chip(ui, "Chưa tải được tiến độ KPI, vui lòng thử lại sau" if cl else
                              f"Không tính được tiến độ: {str(e)[:160]}", "red", "error")
            T.busy(box, False)
            return
        box.clear()
        T.busy(box, False)
        with box:
            kpi_block(ui, p, compact=False)
            if p and p.get("start"):
                with T.section(ui, "Cả dự án", "table_chart", "Ô xanh: đạt · đỏ: không đạt (tháng đã chốt) · vàng: "
                                                              "đang chạy, chưa đạt · khung xanh: tháng hiện tại"):
                    full_table(ui, p)
                cur = next((m for m in p["months"] if m["status"] == "running"), None) or \
                    next((m for m in reversed(p["months"]) if m["status"] == "closed"), None)
                if cur or p.get("pre"):
                    keyword_table(ui, cur or p["pre"], cfg.site_url)
            with ui.expansion(f"Lịch sử phiên bản KPI ({len(vs)})", icon="history").classes(
                    "w-full sr-card" + (" hidden" if cl else "")):
                for v in reversed(vs):
                    d = v["data"]
                    ui.label(f"Từ {_vn(v['day'])}/{v['day'][:4]} · {len(d['months'])} tháng · {len(d['lines'])} cam "
                             f"kết · {len(d.get('keywords', []))} từ khóa · bắt đầu {d['start'] or 'chưa nhập'}"
                             ).classes("text-sm")
                ui.label("Tháng đã qua được chấm theo phiên bản có hiệu lực cuối tháng đó.").classes("text-xs muted")

    from nicegui import background_tasks
    background_tasks.create(load())


def keyword_table(ui, m: dict, site: str) -> None:
    """Từng từ khóa cam kết: top target riêng, vị trí lần check cuối trong tháng, đạt hay chưa. Chưa đạt lên đầu."""
    rk = m["rank"]
    items = sorted(rk["items"], key=lambda x: (x["ok"] is not False, x["ok"] is None, x["rank"] is None,
                                               x["rank"] or 0, x["keyword"]))
    sub = ((f"Theo lần check cuối trong tháng {m['n']}" if m["n"] else "Mốc trước dự án: lần check mới nhất")
           + (f" · {rk['target_ok']}/{rk['target_set']} đạt top target" if rk["target_set"] else ""))
    with T.section(ui, f"Từ khóa cam kết · {rk['total']}", "search", sub, href="/rank", link_text="Thứ hạng"):
        if not items:
            ui.label("Tab 'Từ khóa cam kết' chưa có từ khóa nào.").classes("text-sm muted")
            return
        rows = []
        for x in items:
            pos = ("chưa check" if x["date"] is None else
                   (str(x["rank"]) if x["rank"] is not None else f">{x['depth']}"))
            st = ("Chưa check" if x["date"] is None and m.get("status") != "closed" else
                  "Không có mục tiêu" if x["ok"] is None else "Đạt" if x["ok"] else "Chưa đạt")
            rows.append({"keyword": x["keyword"], "target": f"Top {x['target']}" if x["target"] else "–",
                         "pos": pos, "status": st, "date": _vn(x["date"]),
                         "url": (x["url"] or "").replace(site.rstrip("/"), "") or "–"})
        tbl = ui.table(columns=[
            {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left"},
            {"name": "target", "label": "Top mục tiêu", "field": "target", "align": "center"},
            {"name": "pos", "label": "Vị trí", "field": "pos", "align": "center"},
            {"name": "status", "label": "Trạng thái", "field": "status", "align": "left"},
            {"name": "date", "label": "Check", "field": "date", "align": "center"},
            {"name": "url", "label": "URL mục tiêu", "field": "url", "align": "left", "classes": "ellipsis",
             "style": "max-width: 320px"},
        ], rows=rows, row_key="keyword", pagination=50).classes("w-full").props("flat dense")
        tbl.add_slot("body-cell-status", """
            <q-td :props="props"><span :style="{fontWeight: 600, color: props.value === 'Đạt' ? '#1E7C31' :
              (props.value === 'Chưa đạt' ? '#C2410C' : '#6B6A5E')}">{{ props.value }}</span></q-td>""")


def _local(iso: str) -> str:
    from datetime import datetime
    return f"{datetime.fromisoformat(iso).astimezone():%H:%M %d/%m}"


def _setup(ui, cfg, connect, ed: bool, user: str, app_connect=None, project: dict | None = None) -> None:
    """Dự án chưa có sheet: wizard thiết lập cam kết rồi tạo sheet dự án trên Drive, hoặc dán link sheet đã có."""
    from nicegui import run

    from . import projects as PJ
    from .okr import parse_date
    from .projects import domain
    host = domain(cfg.site_url)
    master = ""
    if app_connect:
        with app_connect() as c:
            master = PJ.master_sheet(c)
    if not ed:
        with T.section(ui, "Chưa có sheet KPI", "table_view"):
            ui.label("Chỉ người được sửa mới thiết lập được cam kết.").classes("text-sm muted")
        return

    def months_value() -> int:
        return int(months_other.value or 0) if months_pick.value == 0 else int(months_pick.value)

    def spec() -> dict:
        d = parse_date(start.value, date.today())
        if not d:
            raise ValueError("Ngày bắt đầu chưa đúng (dd/mm/yyyy)")
        n = months_value()
        if n < 1 or n > 36:
            raise ValueError("Số tháng phải từ 1 đến 36")
        tops = [t for t, box in top_boxes.items() if box.value]
        finals = {}
        for t in tops:
            v = top_finals[t].value
            if v not in (None, ""):
                finals[t] = float(v) / 100 if unit.value == "pct" else int(v)
        traffic, baseline = {}, {}
        for src, w in src_widgets.items():
            traffic[src] = {
                "level": int(w["level_v"].value) if w["level"].value and w["level_v"].value not in (None, "") else None,
                "cum": int(w["cum_v"].value) if w["cum"].value and w["cum_v"].value not in (None, "") else None}
            baseline[src] = int(w["base"].value) if w["base"].value not in (None, "") else None
        return {"project": (name.value or "").strip() or f"SEO {host}", "start": d.isoformat(), "months": n,
                "baseline": baseline, "rank": {"tops": tops, "mode": mode.value, "unit": unit.value,
                                               "from": int(rank_from.value or 1), "finals": finals},
                "traffic": traffic}

    with T.section(ui, "Thiết lập cam kết KPI", "flag", "Chọn thời gian và các cam kết của dự án. Tool tạo sheet dự "
                                                        "án trên Drive (copy từ sheet mẫu gốc), điền sẵn các dòng cam "
                                                        "kết; chỉ tiêu từng tháng sửa tiếp trên sheet."):
        with ui.stepper().props("flat animated header-nav").classes("w-full") as stepper:
            with ui.step("Thông tin", icon="info"):
                name = ui.input("Tên dự án", value=f"SEO {host}").props("outlined dense").classes("w-96")
                with ui.row().classes("items-end gap-4"):
                    start = ui.input("Ngày bắt đầu (dd/mm/yyyy)", value=f"{date.today():%d/%m/%Y}").props(
                        "outlined dense").classes("w-56")
                    with ui.column().classes("gap-1"):
                        ui.label("Thời gian triển khai").classes("text-xs muted")
                        months_pick = ui.toggle({3: "3 tháng", 6: "6 tháng", 9: "9 tháng", 12: "12 tháng", 0: "Khác"},
                                                value=6).props("unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes("sr-seg")
                    months_other = ui.number("Số tháng", value=6, min=1, max=36, step=1).props(
                        "outlined dense").classes("w-32")
                    months_other.bind_visibility_from(months_pick, "value", backward=lambda v: v == 0)
                ui.label("Tháng dự án tính từ ngày bắt đầu đến trước cùng ngày tháng sau (01/11 → 30/11).").classes(
                    "text-xs muted")
                with ui.stepper_navigation():
                    ui.button("Tiếp", on_click=stepper.next).props("unelevated no-caps")
            with ui.step("Thứ hạng", icon="leaderboard"):
                ui.label("Cam kết từ khóa vào top. Bỏ tích hết nếu dự án không cam kết thứ hạng.").classes("text-sm")
                top_boxes, top_finals = {}, {}
                with ui.row().classes("items-center gap-6"):
                    for t in (3, 5, 10):
                        top_boxes[t] = ui.checkbox(f"Top {t}", value=True)
                mode = ui.radio({"shared": "Bộ chung: mọi mốc top tính trên toàn bộ từ khóa cam kết (top 3 nằm trong "
                                           "top 5)",
                                 "per_tier": "Bộ riêng: mỗi mốc top có danh sách từ khóa riêng (cột Top target), chấm "
                                             "độc lập"}, value="shared").props("dense")
                with ui.row().classes("items-end gap-4"):
                    unit = ui.radio({"pct": "Cam kết theo % bộ từ khóa", "count": "Cam kết theo số từ khóa"},
                                    value="pct").props("dense inline")
                    rank_from = ui.number("Chấm từ tháng", value=3, min=1, max=36, step=1).props(
                        "outlined dense").classes("w-36")
                ui.label("Mốc cuối dự án (tool chia đều ra các tháng làm gợi ý; sửa trên sheet sau):").classes(
                    "text-xs muted")
                with ui.row().classes("items-end gap-4"):
                    for t in (3, 5, 10):
                        top_finals[t] = ui.number(f"Top {t} cuối dự án", value=None, min=0, step=1).props(
                            "outlined dense").classes("w-40")
                        top_finals[t].bind_visibility_from(top_boxes[t], "value")
                    ui.label("").bind_text_from(unit, "value", backward=lambda v: "% bộ từ khóa" if v == "pct"
                                                else "số từ khóa").classes("text-sm muted q-pb-sm")
                kw_text = ui.textarea("Từ khóa cam kết (không bắt buộc, điền sau trên sheet cũng được)",
                                      placeholder="mỗi dòng một từ khóa · thêm | URL mục tiêu | Top 3 nếu có\n"
                                                  "ví dụ: tròng kính zeiss | https://site.vn/trong-kinh/ | Top 3"
                                      ).props("outlined autogrow").classes("w-full")
                with ui.stepper_navigation():
                    ui.button("Quay lại", on_click=stepper.previous).props("flat no-caps")
                    ui.button("Tiếp", on_click=stepper.next).props("unelevated no-caps")
            with ui.step("Traffic", icon="trending_up"):
                ui.label("Cam kết phiên GA4 cho từng nguồn. Baseline = phiên/tháng trước khi bắt đầu, dùng cho dòng "
                         "tăng thêm cộng dồn và để chia mức tháng.").classes("text-sm")
                src_widgets = {}
                base_note = ui.label("").classes("text-xs muted")
                for src, label in KP.SOURCES.items():
                    w = {}
                    with ui.element("div").classes("sr-card q-pa-md w-full"):
                        ui.label(f"Phiên {label}" + (" (GEO traffic: ChatGPT, Gemini, Claude… theo kênh AI Assistant "
                                                      "của GA4)" if src == "ai" else " (kênh Organic Search của GA4)")
                                 ).classes("text-sm font-semibold")
                        w["base"] = ui.number("Baseline (phiên/tháng)", value=None, min=0, step=1).props(
                            "outlined dense").classes("w-48")
                        with ui.row().classes("items-end gap-4"):
                            w["level"] = ui.checkbox("Mức tháng (tăng tiến)", value=src == "organic")
                            w["level_v"] = ui.number("Tăng thêm phiên/tháng ở tháng cuối", value=None, min=0,
                                                     step=100).props("outlined dense").classes("w-64")
                            w["level_v"].bind_visibility_from(w["level"], "value")
                        with ui.row().classes("items-end gap-4"):
                            w["cum"] = ui.checkbox("Tăng thêm cộng dồn (tích lũy)", value=False)
                            w["cum_v"] = ui.number("Tổng phiên tăng thêm cả dự án", value=None, min=0,
                                                   step=100).props("outlined dense").classes("w-64")
                            w["cum_v"].bind_visibility_from(w["cum"], "value")
                    src_widgets[src] = w

                async def fill_baseline():
                    d = parse_date(start.value, date.today())
                    if not d:
                        ui.notify("Nhập ngày bắt đầu ở bước 1 trước", type="warning")
                        return
                    if not cfg.ga4_property:
                        ui.notify("Dự án chưa gắn GA4: nhập baseline tay", type="warning")
                        return
                    base_btn.props("loading")
                    try:
                        def work():
                            with connect() as c:
                                return KP.baseline_suggest(KP.ga4_sessions(cfg, c), d)
                        b = await run.io_bound(work)
                        for src, w in src_widgets.items():
                            w["base"].value = b[src]
                        base_note.text = "GA4 3 tháng trước khi bắt đầu: " + " · ".join(
                            f"{m['label']}: Organic {F.n(m['organic'])}, AI {F.n(m['ai'])}" for m in b["months"])
                    except (Exception, SystemExit) as e:  # noqa: BLE001
                        ui.notify(f"Không lấy được từ GA4: {str(e)[:200]}", type="negative", multi_line=True)
                    finally:
                        base_btn.props(remove="loading")

                base_btn = ui.button("Lấy baseline từ GA4 (trung bình 3 tháng trước)", icon="query_stats",
                                     on_click=fill_baseline).props("outline no-caps")
                with ui.stepper_navigation():
                    ui.button("Quay lại", on_click=stepper.previous).props("flat no-caps")
                    ui.button("Xem lại", on_click=lambda: (preview.refresh(), stepper.next())).props(
                        "unelevated no-caps")
            with ui.step("Xem lại và tạo", icon="check"):
                @ui.refreshable
                def preview():
                    try:
                        sp = spec()
                    except ValueError as e:
                        ui.label(str(e)).classes("text-sm").style(f"color:{T.RED}")
                        return
                    data = KP.plan(sp)
                    kws = KP.parse_keyword_text(kw_text.value)
                    if not data["lines"]:
                        ui.label("Chưa chọn cam kết nào: sheet sẽ chỉ có khối thông tin, thêm dòng trên sheet sau."
                                 ).classes("text-sm muted")
                    head = "".join(f"<th>T{n}</th>" for n in data["months"])
                    body = ""
                    for ln in data["lines"]:
                        cells = "".join(f"<td>{KP.fmt_target(ln, ln['targets'][str(n)])}</td>" for n in data["months"])
                        body += f'<tr><td class="lab">{KP.line_label(ln)}</td>{cells}</tr>'
                    base = data["baseline"]
                    ui.add_head_html(f"<style>{KT_STYLE}</style>")
                    ui.html(f'<table class="sr-kt"><thead><tr><th style="text-align:left">Cam kết</th>{head}</tr>'
                            f'</thead><tbody>{body}</tbody></table>').classes("w-full")
                    ui.label(f"{data['project']} · bắt đầu {_vn(data['start'])}/{data['start'][:4]} · "
                             f"{len(data['months'])} tháng · baseline Organic "
                             f"{F.n(base['organic']) if base['organic'] is not None else 'chưa nhập'}, AI "
                             f"{F.n(base['ai']) if base['ai'] is not None else 'chưa nhập'} · {len(kws)} từ khóa dán sẵn"
                             ).classes("text-xs muted")
                    if master:
                        ui.label("Tool copy sheet mẫu gốc (OKRs, Weekly Task Tracker, Chi phí, Content…) vào folder "
                                 f"Drive của dự án, đặt tên 'Sheet dự án – {host}', rồi ghi 2 tab KPI.").classes(
                            "text-sm")
                    else:
                        ui.label("Chưa cài sheet mẫu gốc (màn Dự án): tool tạo file chỉ có 2 tab KPI cam kết và Từ "
                                 "khóa cam kết.").classes("text-sm").style(f"color:{T.AMBER}")

                preview()

                async def create():
                    try:
                        sp = spec()
                    except ValueError as e:
                        ui.notify(str(e), type="warning")
                        return
                    data, kws = KP.plan(sp), KP.parse_keyword_text(kw_text.value)
                    create_btn.props("loading")
                    try:
                        def work():
                            with connect() as c:
                                f = KP.create_project_sheet(c, cfg, data, kws, master)
                                KP.sync(c, cfg, user)
                            if app_connect and project:  # một link sheet dự án: màn OKR đọc cùng file
                                with app_connect() as ac:
                                    if master or not project["settings"].get("okr_sheet"):
                                        PJ.set_sheet_link(ac, project["slug"], f["id"], user)
                            return f
                        f = await run.io_bound(work)
                        ui.notify("Đã tạo sheet dự án trên Drive và đồng bộ", type="positive")
                        ui.navigate.to(f["webViewLink"], new_tab=True)
                        ui.navigate.reload()
                    except (Exception, SystemExit) as e:  # noqa: BLE001
                        from . import drive as D
                        ui.notify(f"Không tạo được sheet: {D.explain(e)}", type="negative", multi_line=True)
                    finally:
                        create_btn.props(remove="loading")

                with ui.stepper_navigation():
                    ui.button("Quay lại", on_click=stepper.previous).props("flat no-caps")
                    create_btn = ui.button("Tạo sheet dự án", icon="add_chart", on_click=create).props(
                        "unelevated no-caps")

    def use_link():
        try:
            with connect() as c:
                KP.set_sheet(c, link.value)
            ui.navigate.reload()
        except ValueError as e:
            ui.notify(str(e), type="warning")

    with T.section(ui, "Đã có sheet", "link", "Sheet có 2 tab 'KPI cam kết' và 'Từ khóa cam kết' (mẫu cũ hay mới "
                                              "đều đọc được)"):
        with ui.row().classes("items-center gap-3"):
            link = ui.input(placeholder="Dán link Google Sheet đã có").props("outlined dense").classes("w-96")
            ui.button("Dùng sheet này", on_click=use_link).props("outline no-caps")


# ---- Sửa cam kết trên tool ----

LINE_CHOICES = {  # khóa chọn khi thêm dòng → định nghĩa dòng
    "top3": "Top 3", "top5": "Top 5", "top10": "Top 10",
    "level:organic": "Mức tháng · Organic Search", "cum:organic": "Tăng thêm cộng dồn · Organic Search",
    "level:ai": "Mức tháng · AI Assistant", "cum:ai": "Tăng thêm cộng dồn · AI Assistant",
}


def _new_line(lid: str, mode: str, unit: str) -> dict:
    if lid.startswith("top"):
        return {"kind": "rank", "top": int(lid[3:]), "mode": mode, "unit": unit, "targets": {}}
    kind, src = lid.split(":")
    return {"kind": kind, "source": src, "targets": {}}


def build_kpi_edit_page(ui, cfg, connect, user) -> None:
    """Form sửa cam kết: khối thông tin, mỗi cam kết một dòng với ô theo tháng. Lưu = phiên bản KPI mới trên tool, rồi
    tool ghi lại tab KPI cam kết lên sheet (nơi xem). Từ khóa cam kết quản lý ở màn Từ khóa & Thứ hạng."""
    from nicegui import run

    from .okr import parse_date
    with connect() as c:
        sid = KP.sheet_id(c)
    right = T.page_header(ui, "edit", "Sửa cam kết KPI",
                          "Sửa trên tool rồi Lưu: tool lưu phiên bản mới và ghi lại tab KPI cam kết lên sheet dự án.",
                          eyebrow="KPI")
    with right:
        ui.button("Quay lại", icon="arrow_back", on_click=lambda: ui.navigate.to("/kpi")).props("flat no-caps")
    with connect() as c:
        cur = KP.version_at(KP.versions(c), date.today())
    if not cur:
        T.empty_state(ui, "flag", "Chưa có KPI cam kết", "Thiết lập cam kết ở màn KPI cam kết trước.")
        return
    _edit_form(ui, cfg, connect, user, sid, {"data": cur, "keywords": [], "fingerprint": None, "old_format": False})


def _edit_form(ui, cfg, connect, user, sid: str, loaded: dict) -> None:
    from nicegui import run

    from .okr import parse_date
    data = loaded["data"]
    state = {"months": list(data["months"]) or [1], "lines": [dict(ln, targets=dict(ln["targets"])) for ln in
                                                             data["lines"]], "fp": loaded["fingerprint"]}
    if loaded["old_format"]:
        T.status_chip(ui, "Sheet đang ở mẫu cũ: bấm Lưu thì tab KPI cam kết được ghi lại theo bố cục mới (mỗi cam "
                         "kết một dòng)", "amber", "info")
    with T.section(ui, "Thông tin dự án", "info"):
        with ui.row().classes("items-end gap-4 wrap"):
            name = ui.input("Tên dự án", value=data["project"]).props("outlined dense").classes("w-72")
            start = ui.input("Ngày bắt đầu (dd/mm/yyyy)", value=(f"{data['start'][8:10]}/{data['start'][5:7]}/"
                                                               f"{data['start'][:4]}" if data["start"] else "")
                             ).props("outlined dense").classes("w-52")
            n_months = ui.number("Số tháng", value=len(state["months"]), min=1, max=36, step=1).props(
                "outlined dense").classes("w-28")
            base_org = ui.number("Baseline Organic (phiên/tháng)", value=data["baseline"].get("organic"), min=0,
                                 step=1).props("outlined dense").classes("w-60")
            base_ai = ui.number("Baseline AI Assistant", value=data["baseline"].get("ai"), min=0, step=1).props(
                "outlined dense").classes("w-52")
        from . import rank as R
        with connect() as c:
            kpi_sets = {x["id"]: x["name"] for x in R.sets(c, cfg.site_url) if x["kind"] == "kpi"}
        first_set = next((ln.get("set") for ln in state["lines"] if ln["kind"] == "rank"), None)
        set_pick = ui.select({0: "Mọi bộ Cam kết", **kpi_sets}, value=first_set if first_set in kpi_sets else 0,
                             label="Thứ hạng tính trên bộ").props("outlined dense").classes("w-72")
        with ui.row().classes("items-center gap-4"):
            mode = ui.radio({"shared": "Bộ chung (top 3 nằm trong top 5, tính trên cả danh sách)",
                             "per_tier": "Bộ riêng theo mốc (từ khóa có Top target = N, chấm độc lập)"},
                            value=next((ln.get("mode") for ln in state["lines"] if ln["kind"] == "rank"), "shared")
                            ).props("dense inline")
            unit = ui.radio({"pct": "Thứ hạng theo %", "count": "Thứ hạng theo số từ khóa"},
                            value=next((ln.get("unit") for ln in state["lines"] if ln["kind"] == "rank"), "pct")
                            ).props("dense inline")

        def resize():
            n = int(n_months.value or 1)
            state["months"] = list(range(1, max(1, min(36, n)) + 1))
            grid.refresh()

        n_months.on("change", lambda _: resize())
        unit.on("change", lambda _: grid.refresh())

    cells: dict[tuple[int, int], object] = {}

    with T.section(ui, "Các cam kết", "flag", "Ô trống = tháng đó không cam kết. % nhập số 0–100; phiên và số từ khóa "
                                               "nhập số nguyên; dòng tích lũy nhập mức tăng thêm so với baseline của "
                                               "từng tháng."):
        @ui.refreshable
        def grid():
            cells.clear()
            months = state["months"]
            if not state["lines"]:
                ui.label("Chưa có cam kết nào. Thêm dòng bên dưới.").classes("text-sm muted")
            for i, ln in enumerate(state["lines"]):
                pct = ln["kind"] == "rank" and unit.value == "pct"
                with ui.row().classes("items-center gap-2 no-wrap w-full").style("overflow-x:auto"):
                    ui.label(KP.line_label({**ln, "mode": mode.value} if ln["kind"] == "rank" else ln)).classes(
                        "text-sm font-semibold").style("min-width: 190px")
                    ui.label("%" if pct else ("từ" if ln["kind"] == "rank" else "phiên")).classes(
                        "text-xs muted").style("min-width: 36px")
                    for n in months:
                        v = ln["targets"].get(str(n))
                        if v is not None and pct and ln.get("unit", "pct") == "pct":
                            v = round(v * 100, 1)
                        cells[(i, n)] = ui.number(value=v, step=1 if pct or ln["kind"] == "rank" else 100).props(
                            "outlined dense").classes("w-24").tooltip(f"Tháng {n}")

                    def remove(_, i=i):
                        state["lines"].pop(i)
                        grid.refresh()

                    ui.button(icon="delete", on_click=remove).props("flat round dense color=grey-7").tooltip(
                        "Bỏ cam kết này")
            with ui.row().classes("items-center gap-1 no-wrap q-ml-xs"):
                ui.label("").style("min-width: 230px")
                for n in months:
                    ui.label(f"T{n}").classes("text-xs muted text-center").style("width: 96px")

        grid()
        with ui.row().classes("items-center gap-3 q-mt-sm"):
            pick = ui.select(LINE_CHOICES, value="top3", label="Thêm cam kết").props("outlined dense").classes(
                "w-80")

            def add():
                lid = pick.value
                if any(KP.line_id(ln) == lid for ln in state["lines"]):
                    ui.notify("Đã có dòng này", type="warning")
                    return
                _collect_targets()
                state["lines"].append(_new_line(lid, mode.value, unit.value))
                grid.refresh()

            ui.button("Thêm dòng", icon="add", on_click=add).props("outline no-caps")

    def _collect_targets() -> None:
        """Đọc ô tháng vào state (trước khi vẽ lại lưới)."""
        for (i, n), w in cells.items():
            if i >= len(state["lines"]):
                continue
            ln = state["lines"][i]
            v = w.value
            if v in (None, ""):
                ln["targets"][str(n)] = None
            elif ln["kind"] == "rank" and unit.value == "pct":
                ln["targets"][str(n)] = round(float(v) / 100, 4)
            else:
                ln["targets"][str(n)] = int(v)
            if ln["kind"] == "rank":
                ln["unit"], ln["mode"] = unit.value, mode.value
        for ln in state["lines"]:  # bộ từ khóa của các dòng Top N (0 = mọi bộ Cam kết)
            if ln["kind"] == "rank":
                ln.pop("set", None)
                if set_pick.value:
                    ln["set"] = int(set_pick.value)

    with T.section(ui, "Từ khóa cam kết", "search"):
        with ui.row().classes("items-center gap-3"):
            ui.label("Từ khóa cam kết là các từ khóa trong bộ loại Cam kết (đã chốt) ở màn Từ khóa & Thứ hạng. Thêm / "
                     "bớt / đổi Top mục tiêu ở đó.").classes("text-sm")
            ui.button("Mở Từ khóa & Thứ hạng", icon="leaderboard", on_click=lambda: ui.navigate.to("/rank")).props(
                "outline no-caps")

    def build() -> tuple[dict, list]:
        d = parse_date(start.value, date.today())
        if start.value and not d:
            raise ValueError("Ngày bắt đầu chưa đúng (dd/mm/yyyy)")
        _collect_targets()
        months = state["months"]
        lines = []
        for ln in state["lines"]:
            out = {k: v for k, v in ln.items() if k != "targets"}
            out["targets"] = {str(n): ln["targets"].get(str(n)) for n in months}
            lines.append(out)
        new = {"project": (name.value or "").strip(), "start": d.isoformat() if d else None, "months": months,
               "baseline": {"organic": int(base_org.value) if base_org.value not in (None, "") else None,
                            "ai": int(base_ai.value) if base_ai.value not in (None, "") else None},
               "lines": lines}
        return new, []

    async def save(force: bool = False):
        try:
            new, kws = build()
        except ValueError as e:
            ui.notify(str(e), type="warning")
            return
        save_btn.props("loading")
        try:
            def work():
                from . import sheet_view as SV
                with connect() as c:
                    KP.save(c, {**new, "keywords": KP.commitment_keywords(c, cfg.site_url)}, date.today())
                    try:  # sheet chỉ để xem: ghi lỗi (thiếu quyền, mạng) thì lượt tự động sau ghi lại
                        SV.publish(c, cfg)
                        return None
                    except (Exception, SystemExit) as e:  # noqa: BLE001
                        return str(e)
            err = await run.io_bound(work)
            ui.notify("Đã lưu cam kết" + ("" if not err else f"; chưa ghi được lên sheet: {err[:160]}"),
                      type="positive" if not err else "warning", multi_line=True)
            ui.navigate.to("/kpi")
        except KP.SheetChanged:
            with ui.dialog() as dlg, ui.card().style("border-radius:16px; max-width:520px"):
                ui.label("Sheet đã bị sửa từ lúc bạn mở form").classes("text-lg font-semibold")
                ui.label("Ai đó vừa đổi tab KPI cam kết hoặc Từ khóa cam kết trên Google Sheet. Tải lại để xem bản "
                         "mới (mất phần bạn vừa sửa ở đây), hoặc ghi đè bằng bản trên tool.").classes("text-sm")
                with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                    ui.button("Tải lại", on_click=lambda: ui.navigate.reload()).props("flat no-caps")
                    ui.button("Ghi đè", on_click=lambda: (dlg.close(), save(force=True))).props(
                        "unelevated no-caps color=negative")
            dlg.open()
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không ghi được: {str(e)[:300]}", type="negative", multi_line=True)
        finally:
            save_btn.props(remove="loading")

    with ui.row().classes("items-center gap-3 q-mt-sm"):
        save_btn = ui.button("Lưu", icon="save", on_click=lambda: save()).props("unelevated no-caps")
        ui.button("Hủy", on_click=lambda: ui.navigate.to("/kpi")).props("flat no-caps")
        ui.label("Tool lưu phiên bản mới (tháng đã qua vẫn chấm theo phiên bản cũ) và ghi lại tab KPI cam kết lên "
                 "sheet dự án; các tab khác của khách không đụng tới.").classes("text-xs muted")
