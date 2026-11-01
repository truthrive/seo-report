"""Màn Cam kết KPI (Quản trị) và khối "Tiến độ KPI" trên Tổng quan / báo cáo. Số cam kết đọc từ Google Sheet mẫu."""
from contextlib import closing
from datetime import date

from . import ai_format as F
from . import kpi as KP
from . import ui_theme as T

LABELS = {"top3": "Từ khóa top 3", "top5": "Từ khóa top 5", "top10": "Từ khóa top 10",
          "sessions": "Phiên Organic (GA4)"}


def _vn(iso) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso else "–"


def _pct(v) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def load_progress(cfg, today: date | None = None) -> dict | None:
    """Tính tiến độ (gọi GA4 nên chạy trong run.io_bound)."""
    from . import db
    today = today or date.today()
    with closing(db.connect(cfg.db_path)) as c:
        if not KP.versions(c):
            return None
        try:
            ga4 = KP.ga4_organic(cfg, c)
        except (Exception, SystemExit):  # noqa: BLE001  (chưa đăng nhập GA4: vẫn hiện phần thứ hạng)
            ga4 = None
        p = KP.progress(c, cfg.site_url, today, ga4)
        if p is not None:
            p["ga4"] = ga4 is not None
        return p


def _status(ch: dict, running: bool) -> tuple[str, str, str]:
    """(chữ, tone, icon) cho một chỉ số."""
    if ch["target"] is None:
        return "Không cam kết", "grey", "remove"
    if ch["ok"] is None:
        return "Chưa có số", "grey", "hourglass_empty"
    if ch["ok"]:
        return ("Đang đạt" if running else "Đạt"), "green", "check_circle"
    gap = ch["gap"]
    if "need" in ch:
        return f"Thiếu {gap} từ khóa", "red" if not running else "amber", "error_outline"
    return f"Thiếu {F.n(gap)} phiên", "red" if not running else "amber", "error_outline"


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
    sub = (f"{_vn(m['from'])} – {_vn(m['to'])}" + (f" · {m['phase']}" if m.get("phase") else "")
           + f" · {m['rank']['total']} từ khóa cam kết" + (" · đang chạy, số còn thay đổi" if running else " · đã chốt"))
    with T.section(ui, f"Tiến độ KPI · Tháng {m['n']}/{total}" + (f" · {p['project']}" if p.get("project") else ""),
                   "flag", sub, href="/kpi" if compact else None, link_text="Xem 6 tháng"):
        with T.kpi_row(ui):
            for key in ("top3", "top5", "top10", "sessions"):
                ch = m["checks"][key]
                text, tone, icon = _status(ch, running)
                if key == "sessions":
                    if not p.get("ga4"):
                        value, hint = "chưa có", "Chưa kết nối GA4"
                    else:
                        value = F.n(ch["actual"]) if ch["actual"] is not None else "chưa có"
                        hint = (f"Cam kết {F.n(ch['target'])}" if ch["target"] is not None else "Tháng này không cam kết")
                        if running and ch.get("forecast") is not None:
                            hint += f" · dự báo cuối tháng {F.n(ch['forecast'])}"
                else:
                    value = f"{_pct(ch['actual'])}"
                    hint = (f"{ch['count']}/{m['rank']['total']} từ khóa · cam kết {_pct(ch['target'])}"
                            if ch["target"] is not None else f"{ch['count']}/{m['rank']['total']} từ khóa")
                with ui.element("div").classes("sr-card sr-kpi q-pa-md"):
                    ui.label(LABELS[key]).classes("text-xs muted")
                    ui.label(value).classes("sr-kpi-value num")
                    if ch["target"] and ch["actual"] is not None:  # thanh tiến độ so với cam kết
                        done = min(ch["actual"] / ch["target"], 1)
                        fc = ch.get("forecast")
                        ahead = min(fc / ch["target"], 1) if running and fc else done
                        color = T.TONES[tone][1]
                        ui.html(
                            f'<div title="Đạt {done * 100:.0f}% cam kết" style="position:relative;height:6px;'
                            f'border-radius:3px;background:#ECEAE2;overflow:hidden;margin:4px 0 6px">'
                            f'<div style="position:absolute;inset:0 auto 0 0;width:{ahead * 100:.1f}%;'
                            f'background:{color};opacity:.28"></div>'
                            f'<div style="position:absolute;inset:0 auto 0 0;width:{done * 100:.1f}%;'
                            f'background:{color}"></div></div>').classes("w-full")
                    T.status_chip(ui, text, tone, icon)
                    ui.label(hint).classes("text-xs muted sr-kpi-hint")
        notes = []
        if m["rank"].get("target_set"):
            notes.append(f"{m['rank']['target_ok']}/{m['rank']['target_set']} từ khóa đạt top target riêng")
        if m["rank"]["checked"] < m["rank"]["total"]:
            notes.append(f"{m['rank']['total'] - m['rank']['checked']} từ khóa chưa có lần check nào trong tháng "
                         "này: tính là chưa đạt")
        if notes:
            ui.label(" · ".join(notes)).classes("text-xs muted")


def full_table(ui, p: dict) -> None:
    """Bảng cả dự án giống sheet: mỗi tháng một cột, mỗi chỉ số hai dòng (cam kết / thực tế)."""
    months = p["months"]
    head = "".join(f'<th>Tháng {m["n"]}<div class="d">{_vn(m.get("from"))} – {_vn(m.get("to"))}</div></th>'
                   for m in months)
    rows = [("Giai đoạn", [f'<span class="ph">{m.get("phase") or ""}</span>' for m in months])]
    for key in ("top3", "top5", "top10", "sessions"):
        tgt, act = [], []
        for m in months:
            t = m.get(key)
            tgt.append(("–" if t is None else (F.n(t) if key == "sessions" else _pct(t))))
            ch = (m.get("checks") or {}).get(key)
            if not ch or m["status"] == "future":
                act.append('<span class="mut">·</span>')
                continue
            if key == "sessions":
                val = F.n(ch["actual"]) if ch["actual"] is not None else "chưa có"
                if m["status"] == "running" and ch.get("forecast") is not None:
                    val += f'<div class="d">dự báo {F.n(ch["forecast"])}</div>'
            else:
                val = f"{_pct(ch['actual'])}<div class=\"d\">{ch['count']} từ</div>"
            cls = "" if ch["ok"] is None else ("ok" if ch["ok"] else ("warn" if m["status"] == "running" else "bad"))
            act.append(f'<span class="{cls}">{val}</span>')
        rows.append((LABELS[key] + " · cam kết", tgt))
        rows.append(("Thực tế", act))
    body = "".join(f'<tr class="{"sub" if lab == "Thực tế" else ""}"><td class="lab">{lab}</td>'
                   + "".join(f"<td>{c}</td>" for c in cells) + "</tr>" for lab, cells in rows)
    cur = next((i for i, m in enumerate(months) if m.get("status") == "running"), None)
    style = (".sr-kt{width:100%;border-collapse:collapse;font-size:13px}.sr-kt th{background:#1F221E;color:#fff;"
             "font-weight:600;padding:8px;text-align:center}.sr-kt th .d{font-weight:400;font-size:11px;opacity:.75}"
             ".sr-kt td{padding:7px 8px;border-bottom:1px solid #EEECE4;text-align:center}.sr-kt td.lab{text-align:left;"
             "font-weight:600;white-space:nowrap}.sr-kt tr.sub td{background:#FAFAF7}.sr-kt tr.sub td.lab{font-weight:400;"
             "color:#6B6A5E;padding-left:20px}.sr-kt td .d{font-size:11px;color:#6B6A5E}.sr-kt th .d{color:#D9D8CF}.sr-kt .ok{color:#1E7C31;"
             "font-weight:700}.sr-kt .bad{color:#C2410C;font-weight:700}.sr-kt .warn{color:#8F5F14;font-weight:700}"
             ".sr-kt .mut{color:#B8B6A8}.sr-kt .ph{font-size:12px;color:#4A4A42}")
    if cur is not None:
        style += f".sr-kt tr td:nth-child({cur + 2}){{box-shadow:inset 2px 0 #1E7C31,inset -2px 0 #1E7C31}}"
    ui.add_head_html(f"<style>{style}</style>")  # ui.html lọc bỏ thẻ <style> nên đặt ở <head>
    ui.html(f'<div style="overflow-x:auto"><table class="sr-kt"><thead><tr><th style="text-align:'
            f'left">Chỉ số</th>{head}</tr></thead><tbody>{body}</tbody></table></div>').classes("w-full")


def build_kpi_page(ui, cfg, connect, user) -> None:
    from nicegui import run

    from .access import can_edit
    ed = can_edit(user)
    with connect() as c:
        sid = KP.sheet_id(c)
    right = T.page_header(ui, "flag", "Cam kết KPI",
                          "Thứ hạng bộ từ khóa cam kết và phiên Organic theo từng tháng dự án, nhập trên Google Sheet",
                          eyebrow="Quản trị")
    with right:
        if sid and ed:  # người chỉ xem không mở được sheet nội bộ
            ui.button("Mở sheet", icon="open_in_new", on_click=lambda: ui.navigate.to(
                f"https://docs.google.com/spreadsheets/d/{sid}/edit", new_tab=True)).props("outline no-caps")
        if sid and ed:
            sync_btn = ui.button("Đồng bộ ngay", icon="sync", on_click=lambda: do_sync()).props("unelevated no-caps")

    async def do_sync():
        sync_btn.props("loading")
        try:
            def work():
                with connect() as c:
                    return KP.sync(c, cfg, user)
            r = await run.io_bound(work)
            msg = (f"Đã đồng bộ: {r['months']} tháng, {r['keywords']} từ khóa cam kết"
                   + (f", thêm {r['added']} từ khóa vào check rank" if r["added"] else "")
                   + ("" if r["changed"] else " · KPI không đổi"))
            ui.notify(msg, type="positive")
            if r["over_budget"]:
                ui.notify(f"{len(r['over_budget'])} từ khóa chưa thêm được vì vượt ngân sách check rank",
                          type="warning", multi_line=True)
            if r["bad_url"]:
                ui.notify(f"{len(r['bad_url'])} dòng có URL mục tiêu không thuộc site: {r['bad_url'][0]}",
                          type="warning", multi_line=True)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không đồng bộ được: {e}", type="negative", multi_line=True)
        finally:
            sync_btn.props(remove="loading")
        ui.navigate.reload()

    if not sid:
        _setup(ui, cfg, connect, ed)
        return

    with connect() as c:
        info, vs = KP.sync_info(c), KP.versions(c)
    if info:
        T.status_chip(ui, f"Đồng bộ lúc {_local(info['at'])} · {info['months']} tháng · {info['keywords']} từ khóa",
                      "grey", "schedule")
    if not vs:
        T.empty_state(ui, "sync", "Chưa đồng bộ lần nào", "Bấm Đồng bộ ngay để đọc KPI từ sheet.")
        return

    box = ui.column().classes("w-full gap-4")
    with box:
        T.skeleton(ui).classes("w-full").style("height: 220px; border-radius: 14px")

    async def load():
        try:
            p = await run.io_bound(lambda: load_progress(cfg))
        except (Exception, SystemExit) as e:  # noqa: BLE001
            box.clear()
            with box:
                T.status_chip(ui, f"Không tính được tiến độ: {str(e)[:160]}", "red", "error")
            return
        box.clear()
        with box:
            kpi_block(ui, p, compact=False)
            if p and p.get("start"):
                with T.section(ui, "Cả dự án", "table_chart", "Ô xanh: đạt · đỏ: không đạt (tháng đã chốt) · vàng: "
                                                              "đang chạy, chưa đạt · khung xanh: tháng hiện tại"):
                    full_table(ui, p)
                cur = next((m for m in p["months"] if m["status"] == "running"), None) or \
                    next((m for m in reversed(p["months"]) if m["status"] == "closed"), None)
                if cur or p.get("baseline"):
                    keyword_table(ui, cur or p["baseline"], cfg.site_url)
            with ui.expansion(f"Lịch sử phiên bản KPI ({len(vs)})", icon="history").classes("w-full sr-card"):
                for v in reversed(vs):
                    d = v["data"]
                    ui.label(f"Từ {_vn(v['day'])}/{v['day'][:4]} · {len(d['months'])} tháng · "
                             f"{len(d.get('keywords', []))} từ khóa · bắt đầu {d['start'] or 'chưa nhập'}").classes(
                        "text-sm")
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
    with T.section(ui, f"Từ khóa cam kết · {rk['total']}", "search", sub, href="/rank", link_text="Từ khóa & rank"):
        if not items:
            ui.label("Tab 'Từ khóa cam kết' chưa có từ khóa nào.").classes("text-sm muted")
            return
        rows = []
        for x in items:
            pos = ("chưa check" if x["date"] is None else
                   (str(x["rank"]) if x["rank"] is not None else f">{x['depth']}"))
            st = ("Không đặt" if x["ok"] is None else "Đạt" if x["ok"] else "Chưa đạt")
            rows.append({"keyword": x["keyword"], "target": f"Top {x['target']}" if x["target"] else "–",
                         "pos": pos, "status": st, "date": _vn(x["date"]),
                         "url": (x["url"] or "").replace(site.rstrip("/"), "") or "–"})
        tbl = ui.table(columns=[
            {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left"},
            {"name": "target", "label": "Top target", "field": "target", "align": "center"},
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


def _setup(ui, cfg, connect, ed: bool) -> None:
    from nicegui import run
    with T.section(ui, "Chưa có sheet KPI", "table_view",
                   "Tool tạo một Google Sheet mẫu trong folder Drive của tool, giống bảng KPI cam kết 6 tháng"):
        ui.label("Sheet gồm 2 tab: 'KPI cam kết' (ngày bắt đầu, % từ khóa top 3/5/10 và phiên Organic theo tháng) và "
                 "'Từ khóa cam kết' (từ khóa + URL mục tiêu). Điền số rồi bấm Đồng bộ là tool hiện tiến độ.").classes(
            "text-sm")
        if not ed:
            ui.label("Chỉ người được sửa mới tạo được sheet.").classes("text-sm muted")
            return

        async def create():
            btn.props("loading")
            try:
                def work():
                    with connect() as c:
                        return KP.create_template(c, cfg)
                f = await run.io_bound(work)
                ui.notify("Đã tạo sheet mẫu trong folder Drive của tool", type="positive")
                ui.navigate.to(f["webViewLink"], new_tab=True)
                ui.navigate.reload()
            except (Exception, SystemExit) as e:  # noqa: BLE001
                from . import drive as D
                ui.notify(f"Không tạo được sheet: {D.explain(e)}", type="negative", multi_line=True)
            finally:
                btn.props(remove="loading")

        def use_link():
            try:
                with connect() as c:
                    KP.set_sheet(c, link.value)
                ui.navigate.reload()
            except ValueError as e:
                ui.notify(str(e), type="warning")

        with ui.row().classes("items-center gap-3 q-mt-sm"):
            btn = ui.button("Tạo sheet mẫu", icon="add_chart", on_click=create).props("unelevated no-caps")
            ui.label("hoặc").classes("muted")
            link = ui.input(placeholder="Dán link Google Sheet đã có").props("outlined dense").classes("w-96")
            ui.button("Dùng sheet này", on_click=use_link).props("outline no-caps")
