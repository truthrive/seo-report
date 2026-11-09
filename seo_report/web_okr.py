"""Màn Công việc & OKR: tiến độ OKR 3 tháng và Weekly Task Tracker đọc từ Google Sheet của team (chỉ đọc)."""
import json
from datetime import date, datetime, timedelta

from . import okr as O
from . import ui_theme as T

STATUS_TONE = {O.DONE: "green", O.DOING: "blue", O.TODO: "grey", O.OTHER: "amber"}
STATUS_COLOR = {O.DONE: "#1E7C31", O.DOING: "#2563EB", O.TODO: "#B8B6A8", O.OTHER: "#B7791F"}


def _vn(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso else "–"


def build_okr_page(ui, cfg, connect, user: str, ctx: dict, app_connect=None, project: dict | None = None) -> None:
    from nicegui import run

    today = date.today()
    ws, we = ctx["weeks"][ctx["week"]]
    sheet_url = cfg.okr.sheet if cfg.okr.sheet.startswith("http") else \
        f"https://docs.google.com/spreadsheets/d/{O.sheet_id(cfg.okr.sheet)}/edit"

    from .access import can_edit, is_client
    cl = is_client(user)  # khách hàng: không chip đồng bộ, không danh sách "cần cập nhật", không hướng dẫn
    ed = can_edit(user)
    from . import kpi as KP
    with connect() as c:
        owned = O.tool_owned(c)  # OKR tạo / sửa trên tool (tab OKRs trên sheet do tool ghi); task tuần vẫn đọc từ sheet
        project_sheet = O.sheet_id(cfg.okr.sheet) or KP.sheet_id(c)
    has_sheet = bool(O.sheet_id(cfg.okr.sheet))
    right = T.page_header(ui, "task_alt", "Công việc & OKR",
                          "Tiến độ công việc và OKR của dự án" if cl else
                          (("OKR tạo và cập nhật trên tool · task tuần đọc từ sheet dự án" if has_sheet else
                            "OKR tạo và cập nhật trên tool") if owned else
                           "Đọc từ Google Sheet của team · cập nhật trên sheet" if has_sheet else
                           "Tạo OKR trên tool, theo dõi tiến độ từng mục tiêu"), eyebrow="Báo cáo công việc")
    with right:
        # Người chỉ xem không mở được sheet (đã đóng link) và không đồng bộ; chưa khai báo sheet thì không có nút
        # (do_sync chỉ được định nghĩa khi có sheet: bấm nút lúc đó sẽ lỗi NameError)
        if ed and has_sheet:
            ui.button("Mở sheet", icon="open_in_new", on_click=lambda: ui.navigate.to(sheet_url, new_tab=True)).props(
                "outline no-caps")
            sync_btn = ui.button("Đọc task tuần" if owned else "Đồng bộ ngay", icon="sync",
                                 on_click=lambda: do_sync()).props("outline no-caps" if owned else "unelevated no-caps")
            if owned:
                sync_btn.tooltip("Đọc lại tab Weekly Task Tracker trên sheet dự án (OKR sửa trên tool)")
        if ed and owned and not project_sheet:
            ui.button("Sheet dự án", icon="add_to_drive", on_click=lambda: sheet_dialog()).props(
                "outline no-caps").tooltip("Tạo sheet dự án mới hoặc gắn sheet đã có; tool ghi tab OKRs lên đó")
        if ed and owned:
            ui.button("Sửa OKR", icon="edit_note", on_click=lambda: ui.navigate.to("/okr/sua")).props(
                "unelevated no-caps color=primary")
        elif ed and has_sheet:  # chưa có sheet: thân trang đã có nút "Tạo OKR trên tool"
            ui.button("Chuyển OKR sang tool", icon="move_down", on_click=lambda: take_over_dialog()).props(
                "unelevated no-caps color=primary").tooltip("Tạo và sửa OKR ngay trên tool; tool ghi tab OKRs lên sheet")

    def remember_link(sid: str) -> None:
        """Gắn sheet làm sheet dự án ở cả hai chỗ: KPI (tool ghi tab) và Dự án (đọc Weekly Task Tracker)."""
        if app_connect and project:
            from . import projects as PJ
            with app_connect() as ac:
                PJ.set_sheet_link(ac, project["slug"], sid, str(user))

    def sheet_dialog() -> None:
        from nicegui import run as nrun

        from . import projects as PJ
        from . import sheet_view as SV
        master = ""
        if app_connect:
            with app_connect() as ac:
                master = PJ.master_sheet(ac) or ""
        with ui.dialog() as dlg, ui.card().style("width: 560px; max-width: 94vw; border-radius: 14px"):
            ui.label("Sheet dự án").classes("text-lg font-semibold")
            ui.label("Tool ghi các tab của tool (Thông tin dự án, KPI cam kết, OKRs, bộ từ khóa, Dữ liệu check) và khóa "
                     "chúng. Tab của team (Weekly Task Tracker, Content, Đề xuất chi phí…) tool không ghi.").classes(
                "text-sm muted")
            with ui.element("div").classes("sr-card q-pa-md w-full q-mt-sm"):
                ui.label("Tạo sheet mới").classes("text-sm font-semibold")
                ui.label(("Chép từ sheet mẫu gốc (giữ Weekly Task Tracker, Content, Đề xuất chi phí), lưu trong folder "
                          "Drive của dự án." if master else
                          "Chưa có sheet mẫu gốc: tạo sheet trống có sẵn tab Weekly Task Tracker.")).classes(
                    "text-xs muted")
                create_btn = ui.button("Tạo sheet dự án", icon="add").props("unelevated no-caps color=primary").classes(
                    "q-mt-sm")
            with ui.element("div").classes("sr-card q-pa-md w-full"):
                ui.label("Hoặc gắn sheet đã có").classes("text-sm font-semibold")
                link = ui.input(placeholder="Dán link Google Sheet").props("outlined dense").classes("w-full q-mt-xs")
                attach_btn = ui.button("Gắn sheet", icon="link").props("outline no-caps color=grey-9").classes("q-mt-sm")
            err = ui.label("").classes("text-sm text-negative")
            err.props["role"] = "alert"

            async def create():
                create_btn.props("loading")
                err.text = ""
                try:
                    def work():
                        with connect() as c:
                            return SV.create_project_sheet(c, cfg, master)
                    f = await nrun.io_bound(work)
                    remember_link(f["id"])
                    ui.notify("Đã tạo sheet dự án và ghi các tab của tool", type="positive",
                              position="bottom-right", classes="sr-toast")
                    dlg.close()
                    ui.navigate.reload()
                except (Exception, SystemExit) as e:  # noqa: BLE001
                    err.text = f"Không tạo được: {e}"
                finally:
                    create_btn.props(remove="loading")

            async def attach():
                attach_btn.props("loading")
                err.text = ""
                try:
                    def work():
                        with connect() as c:
                            SV.attach_sheet(c, cfg, link.value or "")
                            return KP.sheet_id(c)
                    sid = await nrun.io_bound(work)
                    remember_link(sid)
                    ui.notify("Đã gắn sheet dự án và ghi các tab của tool", type="positive",
                              position="bottom-right", classes="sr-toast")
                    dlg.close()
                    ui.navigate.reload()
                except (Exception, SystemExit) as e:  # noqa: BLE001
                    err.text = f"Không gắn được: {e}"
                finally:
                    attach_btn.props(remove="loading")
            create_btn.on_click(create)
            attach_btn.on_click(attach)
            with ui.row().classes("w-full justify-end"):
                ui.button("Đóng", on_click=dlg.close).props("flat no-caps")
        dlg.on("hide", lambda: dlg.delete())
        dlg.open()

    def take_over_dialog() -> None:
        with ui.dialog() as dlg, ui.card().style("max-width: 520px; border-radius: 14px"):
            ui.label("Chuyển OKR sang tool").classes("text-lg font-semibold")
            for line in ("Từ giờ tạo, sửa OKR và cập nhật trạng thái / % tiến độ ngay trên tool.",
                         "OKR đang có (đã đồng bộ từ sheet) được giữ nguyên làm điểm bắt đầu.",
                         "Tool ghi tab OKRs của tool lên sheet dự án và khóa tab đó. Tab OKR cũ của team trên sheet "
                         "không bị sửa; xóa đi khi không cần nữa.",
                         "Weekly Task Tracker vẫn cập nhật trên sheet như cũ, tool chỉ đọc."):
                with ui.row().classes("no-wrap items-start gap-2"):
                    ui.icon("check", size="18px").style(f"color:{T.GREEN}").props('aria-hidden="true"')
                    ui.label(line).classes("text-sm")

            def go():
                with connect() as c:
                    O.take_over(c)
                dlg.close()
                ui.navigate.to("/okr/sua")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Chuyển sang tool", on_click=go).props("unelevated no-caps color=primary")
        dlg.on("hide", lambda: dlg.delete())
        dlg.open()

    def _take():
        with connect() as c:
            O.take_over(c)

    if not has_sheet and not owned:
        if cl or not ed:
            T.empty_state(ui, "table_view", "Chưa có OKR", "Tiến độ OKR sẽ hiện ở đây khi được cập nhật.")
            return
        T.empty_state(ui, "flag", "Chưa có OKR",
                      "Tạo OKR ngay trên tool (đề xuất), hoặc gắn sheet dự án ở màn KPI cam kết / Quản trị → Dự án.")
        ui.button("Tạo OKR trên tool", icon="add", on_click=lambda: (_take(), ui.navigate.to("/okr/sua"))).props(
            "unelevated no-caps color=primary")
        return

    body = ui.column().classes("w-full gap-4")

    async def do_sync():
        sync_btn.props("loading")
        try:
            def work():
                with connect() as c:
                    return O.sync(c, cfg)
            res = await run.io_bound(work)
            ui.notify(f"Đã đọc {res['tasks']} task tuần từ sheet" if res.get("weekly_only") else
                      f"Đã đồng bộ {res['items']} hạng mục OKR và {res['tasks']} task tuần", type="positive")
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không đồng bộ được: {e}", type="negative", multi_line=True)
        finally:
            sync_btn.props(remove="loading")
        render.refresh()

    cur_week = (today - timedelta(days=today.weekday()), today - timedelta(days=today.weekday()) + timedelta(days=6))
    # obj: mục tiêu đang chọn (bấm thẻ ở "Theo mục tiêu" để lọc lịch); open: mục tiêu đang mở rộng trên lịch
    view = {"gantt": "all", "cycle": None, "obj": None, "open": set()}
    STARTED = "#D99A2B"  # tới ngày bắt đầu mà chưa bắt đầu

    def go_alerts() -> None:
        ui.run_javascript("document.getElementById('okr-alerts')?.scrollIntoView({behavior:'smooth',block:'start'})")

    @ui.refreshable
    def render():
        with connect() as c:
            info = O.sync_info(c)
            ov = O.overview(c, today, cycle=view["cycle"]) if (info or owned) else None
            tasks = O.tasks(c) if (info or owned) else []
        if not info and not owned:
            T.empty_state(ui, "sync", "Chưa có OKR" if cl else "Chưa đồng bộ lần nào",
                          "Tiến độ OKR sẽ hiện ở đây khi được cập nhật." if cl else
                          "Bấm Đồng bộ ngay để lấy dữ liệu từ sheet.")
            return
        if owned and not ov["total"] and not ov["objectives"]:
            T.empty_state(ui, "flag", "Chưa có OKR", "Tiến độ OKR sẽ hiện ở đây khi được cập nhật." if not ed else
                          "Bấm “Sửa OKR” để tạo đợt, mục tiêu và hạng mục.")
            return

        # ---- Chọn đợt OKR ----
        if len(ov["cycles"]) > 1:
            def pick(e):
                view.update(cycle=e.value, gantt="all", obj=None, open=set())
                render.refresh()
            ui.toggle({c["name"]: f"{c['name']} · {_vn(c['start'])} – {_vn(c['end'])}" for c in ov["cycles"]},
                      value=ov["cycle"], on_change=pick).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg sr-seg-wrap")

        issues = [] if cl else _sheet_issues([] if owned else ov["items"], tasks, today)
        overdue_tasks = sum(1 for x in issues if x["kind"] == "task" and x["reason"] == "Quá deadline")
        progress_block(ov, overdue_tasks, bool(issues) or bool(ov["late"]))

        # ---- Thông báo (trễ hạn / sắp đến hạn / chưa bắt đầu + task tuần cần cập nhật) ----
        if owned and not cl:
            from .web_okr_edit import alerts_panel
            alerts_panel(ui, connect, user, ed, render.refresh, ov["cycle"], limit=3,
                         tasks=[x for x in issues if x["kind"] == "task"],
                         note="" if ed else "Người phụ trách (PIC) và quản lý dự án cập nhật các việc này; "
                                            "bạn đang ở chế độ chỉ xem.")
        elif issues:
            sheet_issues_block(issues)

        plan_block(ov)

        # ---- Tuần ----
        week_block(tasks, ov["late"], info)

        # ---- Toàn bộ hạng mục / task ----
        with ui.expansion("Danh sách đầy đủ", icon="list", caption=f"{ov['total']} hạng mục OKR · {len(tasks)} task tuần"
                          ).classes("w-full sr-card"):
            with ui.tabs().props("dense no-caps align=left active-color=primary indicator-color=primary") as tabs:
                t_items = ui.tab(f"Hạng mục OKR · {ov['total']}")
                t_tasks = ui.tab(f"Task tuần · {len(tasks)}")
            if ed and owned:
                ui.button("Sửa trong trang Sửa OKR", icon="edit_note", on_click=lambda: ui.navigate.to("/okr/sua")).props(
                    "flat no-caps dense color=primary").classes("q-mt-xs")
            with ui.tab_panels(tabs, value=t_items).classes("w-full"):
                with ui.tab_panel(t_items).classes("q-pa-none"):
                    ui.table(columns=[
                        {"name": "code", "label": "ID", "field": "code", "align": "left"},
                        {"name": "grp", "label": "Nhóm", "field": "grp", "align": "left"},
                        {"name": "title", "label": "Hạng mục", "field": "title", "align": "left",
                         "style": "white-space: normal; min-width: 240px"},
                        {"name": "time", "label": "Thời gian", "field": "time", "align": "left"},
                        {"name": "pic", "label": "PIC", "field": "pic", "align": "left"},
                        {"name": "st", "label": "Trạng thái", "field": "st", "align": "left"},
                    ], rows=[{**i, "time": f"{_vn(i['start'])} – {_vn(i['end'])}",
                              "st": ("Trễ hạn · " if O.is_late(i, today) else "") + O.STATUS_LABEL[i["status"]]}
                             for i in ov["items"]], row_key="code", pagination=50).classes("w-full").props(
                        "flat dense")
                with ui.tab_panel(t_tasks).classes("q-pa-none"):
                    ui.table(columns=[
                        {"name": "week", "label": "Tuần", "field": "wk", "align": "left"},
                        {"name": "okr", "label": "Mã OKR", "field": "okr_code", "align": "left"},
                        {"name": "task", "label": "Việc", "field": "task", "align": "left",
                         "style": "white-space: normal; min-width: 260px"},
                        {"name": "pic", "label": "PIC", "field": "pic", "align": "left"},
                        {"name": "dl", "label": "Deadline", "field": "dl", "align": "center"},
                        {"name": "st", "label": "Trạng thái", "field": "st", "align": "left"},
                    ], rows=[{**t, "wk": _vn(t["week"]), "dl": _vn(t["deadline"]), "st": O.STATUS_LABEL[t["status"]]}
                             for t in sorted(tasks, key=lambda t: t["week"] or "", reverse=True)],
                        row_key="row", pagination=50).classes("w-full").props("flat dense")

    def progress_block(ov: dict, overdue_tasks: int, has_alerts: bool) -> None:
        """Tiến độ đợt: % xong, thanh 4 màu kèm chú thích có số, vạch thời gian đã trôi qua, trễ hạn bấm tới thông báo."""
        cnt, n = ov["counts"], ov["total"]
        cyc = next((c for c in ov["cycles"] if c["name"] == ov["cycle"]), None) or {}
        done_pct = cnt[O.DONE] / n * 100 if n else 0
        time_pct, time_line = None, ""
        if cyc.get("start") and cyc.get("end"):
            d0, d1 = date.fromisoformat(cyc["start"]), date.fromisoformat(cyc["end"])
            span = (d1 - d0).days + 1
            day = min(max((today - d0).days + 1, 0), span)
            time_pct = day / span * 100
            if today < d0:
                time_line = f"Đợt bắt đầu {_vn(cyc['start'])} · {span} ngày"
            elif today > d1:
                time_line = f"Đợt đã kết thúc {_vn(cyc['end'])} · {done_pct:.0f}% hạng mục xong"
            else:
                time_line = f"Ngày {day}/{span} · {time_pct:.0f}% thời gian · {done_pct:.0f}% hạng mục xong"
        with ui.element("section").classes("sr-card sr-okr-prog").props('aria-label="Tiến độ OKR"'):
            with ui.row().classes("w-full items-end justify-between gap-2"):
                with ui.column().classes("gap-0"):
                    ui.label(f"Tiến độ {ov['cycle'] or 'OKR'}").classes("sr-bento-eyebrow").style(
                        f"color:{T.GREEN}")
                    with ui.row().classes("items-baseline gap-2"):
                        ui.label(f"{done_pct:.0f}%").classes("sr-bento-hero num")
                        ui.label(f"{cnt[O.DONE]} / {n} hạng mục hoàn thành").classes("text-sm muted")
                if time_line:
                    behind = time_pct is not None and 0 < time_pct <= 100 and done_pct + 10 < time_pct
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon("schedule", size="16px").classes("muted").props('aria-hidden="true"')
                        ui.label(time_line).classes("text-sm" + ("" if behind else " muted")).style(
                            f"color:{T.AMBER}" if behind else "")
            seg = "".join(
                f'<div title="{O.STATUS_LABEL[s]}: {cnt[s]}" style="flex:{cnt[s]};background:{STATUS_COLOR[s]}">'
                f"</div>" for s in (O.DONE, O.DOING, O.TODO, O.OTHER) if cnt[s])
            mark = (f'<div title="Thời gian đã qua: {time_pct:.0f}%" style="position:absolute;top:-4px;bottom:-4px;'
                    f'left:calc({time_pct:.1f}% - 1px);width:2px;background:#1F221E;border-radius:1px"></div>'
                    if time_pct is not None and 0 < time_pct < 100 else "")
            ui.html(f'<div style="position:relative"><div style="display:flex;gap:3px;height:12px;border-radius:6px;'
                    f'overflow:hidden;background:#EEECE4">{seg}</div>{mark}</div>').classes("w-full")
            with ui.row().classes("items-center gap-x-4 gap-y-1 w-full"):
                for s in (O.DONE, O.DOING, O.TODO, O.OTHER):
                    if cnt[s]:
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.element("span").classes("sr-dot").style(f"background:{STATUS_COLOR[s]}")
                            ui.label(f"{O.STATUS_LABEL[s]} {cnt[s]}").classes("text-sm")
                if mark:
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.element("span").style("width:2px;height:12px;background:#1F221E")
                        ui.label("Hôm nay").classes("text-xs muted")
                ui.space()
                late = len(ov["late"])
                text = (f"{late} hạng mục trễ hạn" if late else "Không có hạng mục trễ") + (
                    f" · {overdue_tasks} task tuần quá deadline" if overdue_tasks else "")
                if (late or overdue_tasks) and has_alerts:
                    ui.button(text, icon="warning", on_click=go_alerts).props(
                        "flat no-caps dense color=negative").tooltip("Xem trong Thông báo OKR")
                else:
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon("check_circle", size="16px").style(f"color:{T.GREEN}").props('aria-hidden="true"')
                        ui.label(text).classes("text-sm muted")

    def sheet_issues_block(issues: list[dict]) -> None:
        """OKR còn trên sheet: dòng cần người phụ trách sửa trên sheet (3 dòng đầu, còn lại trong danh sách)."""
        with ui.element("div").classes("q-pa-md w-full").props('id="okr-alerts"').style(
                f"border-radius:12px;background:{T.TONES['amber'][0]};border:1px solid #EAD7AE"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("rule", size="18px").style(f"color:{T.AMBER}")
                ui.label(f"Cần cập nhật trên sheet · {len(issues)}").classes("text-sm font-semibold")
            for x in issues[:3]:
                with ui.row().classes("items-center gap-2 no-wrap w-full"):
                    T.status_chip(ui, x["reason"], "red" if "Quá" in x["reason"] else "amber")
                    ui.label(x["code"] or "–").classes("text-xs muted").style("min-width:40px")
                    ui.label(x["text"]).classes("text-sm ellipsis col").tooltip(x["text"])
                    ui.label(x["where"]).classes("text-xs muted gt-xs")
            if len(issues) > 3:
                ui.label(f"và {len(issues) - 3} dòng khác (xem trên sheet)").classes("text-xs muted")

    @ui.refreshable
    def plan_block(ov: dict) -> None:
        """Thẻ mục tiêu (bấm để lọc lịch) + lịch triển khai."""
        sel = view["obj"] if view["obj"] in {o["uid"] for o in ov["objectives"]} else None
        with T.section(ui, "Theo mục tiêu", "flag", "Bấm một mục tiêu để xem lịch riêng của nó"):
            with ui.element("div").classes("w-full").style(
                    "display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px"):
                for o in ov["objectives"]:
                    pct = o["pct"] or 0

                    def choose(_=None, u=o["uid"]):
                        view["obj"] = None if view["obj"] == u else u
                        plan_block.refresh()
                    card = ui.element("div").classes("sr-card sr-okr-obj q-pa-md column no-wrap" + (
                        " on" if sel == o["uid"] else "")).style("border-radius:12px").props(
                        f'role="button" tabindex="0" aria-pressed="{str(sel == o["uid"]).lower()}"')
                    card.on("click", choose)
                    card.on("keydown.enter", choose)
                    with card:
                        with ui.row().classes("items-center justify-between no-wrap w-full"):
                            T.status_chip(ui, o["code"], "green" if pct >= 1 else "grey")
                            ui.label(f"{pct * 100:.0f}%").classes("text-sm font-semibold num")
                        ui.label(o["title"]).classes("text-sm font-medium q-mt-xs").style(
                            "display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;"
                            "line-height:1.35;min-height:2.7em").tooltip(o["title"])
                        ui.label(f"{_vn(o['start'])} – {_vn(o['end'])} · {o['done']}/{o['total']} xong"
                                 + (f" · {o['doing']} đang làm" if o["doing"] else "")).classes("text-xs muted")
                        ui.linear_progress(pct, show_value=False, size="8px",
                                           color="positive").classes("rounded-borders q-mt-sm")
                        if o["late"]:
                            T.status_chip(ui, f"{o['late']} việc trễ", "red", "warning")

        all_dated = [i for i in ov["items"] if i["start"] and i["end"]]
        if not all_dated:
            return
        with T.section(ui, "Lịch triển khai", "view_timeline",
                       "Bấm vào mục tiêu trên lịch để mở / thu gọn các hạng mục"):
            with ui.row().classes("items-center gap-2 q-mb-sm w-full"):
                ui.toggle({"all": "Tất cả", "open": "Chưa xong"}, value=view["gantt"],
                          on_change=lambda e: (view.update(gantt=e.value), plan_block.refresh())).props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                    "sr-seg")
                if sel:
                    code = next(o["code"] for o in ov["objectives"] if o["uid"] == sel)
                    ui.button(f"Đang xem {code}", icon="close",
                              on_click=lambda: (view.update(obj=None), plan_block.refresh())).props(
                        "outline no-caps dense color=primary").tooltip("Bỏ lọc, xem mọi mục tiêu")
                else:
                    every_open = len(view["open"]) >= len(ov["objectives"])
                    ui.button("Thu gọn tất cả" if every_open else "Mở tất cả",
                              icon="unfold_less" if every_open else "unfold_more",
                              on_click=lambda: (view.update(open=set() if every_open else
                                                            {o["uid"] for o in ov["objectives"]}),
                                                plan_block.refresh())).props("flat no-caps dense color=grey-9")
            with ui.row().classes("items-center gap-x-4 gap-y-1 q-mb-xs"):
                for color, text in (("#D6E4D2", "Mục tiêu (phần đậm = % đã xong)"), ("#1E7C31", "Hoàn thành"), ("#2563EB", "Đang làm (đậm = phần đã làm)"),
                                    ("#B8B6A8", "Chưa tới ngày bắt đầu"), (STARTED, "Tới ngày, chưa bắt đầu"),
                                    ("#C2410C", "Trễ hạn")):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.element("span").style(f"width:18px;height:8px;border-radius:4px;background:{color}")
                        ui.label(text).classes("text-xs muted")
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.element("span").style("width:2px;height:12px;background:#C2410C")
                    ui.label("Hôm nay").classes("text-xs muted")
            with ui.element("div").classes("w-full").style("overflow-x:auto"):
                gantt(all_dated, [o for o in ov["objectives"] if not sel or o["uid"] == sel], sel)

    def gantt(all_dated, objectives, sel):
        """Lịch triển khai: mỗi mục tiêu một dòng (thanh = thời gian của cả mục tiêu, phần đậm = % xong); mục tiêu đang mở
        thì hiện các hạng mục bên dưới. Màu theo trạng thái, nền xen kẽ theo tháng, vạch đỏ là hôm nay."""
        import html
        items = [i for i in all_dated if view["gantt"] == "all" or i["status"] != O.DONE]
        d0 = date.fromisoformat(min(i["start"] for i in all_dated))  # trục thời gian giữ nguyên khi lọc
        d1 = date.fromisoformat(max(i["end"] for i in all_dated))
        days = (d1 - d0).days + 2

        def x(iso):
            return (date.fromisoformat(iso) - d0).days

        def short(t, k):
            return t if len(t) <= k else t[:k - 1].rstrip() + "…"

        top = []
        for o in objectives:
            mine = [i for i in all_dated if i["objective"] == o["uid"]]
            its = [i for i in items if i["objective"] == o["uid"]]
            if not mine or (not its and view["gantt"] == "open"):
                continue
            opened = o["uid"] == sel or o["uid"] in view["open"]
            top.append({"kind": "obj", "o": o, "open": opened, "start": min(i["start"] for i in mine),
                        "end": max(i["end"] for i in mine)})
            if opened:
                top += [{"kind": "item", "i": i} for i in its]
        if not top:
            ui.label("Không có hạng mục nào.").classes("text-sm muted")
            return
        rows = top[::-1]  # trục danh mục vẽ từ dưới lên
        keys = [f"r{k}" for k in range(len(rows))]
        labels, uid_of = {}, {}
        for k, r in zip(keys, rows):
            if r["kind"] == "obj":
                o = r["o"]
                uid_of[k] = o["uid"]
                arrow = "▾" if r["open"] else "▸"
                labels[k] = (f"{{oa|{arrow}}} {{oc|{o['code']}}} {{ot|{short(o['title'], 28)}}} "
                             f"{{op|{(o['pct'] or 0) * 100:.0f}%}}")
            else:
                i = r["i"]
                labels[k] = f"{{ic|{i['code'][-5:]}}} {{it|{short(i['title'], 36)}}}"

        none = "-"
        off_i, len_i, off_p, len_p = [], [], [], []
        for r in rows:
            if r["kind"] == "obj":
                o = r["o"]
                s, ln = x(r["start"]), x(r["end"]) - x(r["start"]) + 1
                tip = (f"<b>{html.escape(o['code'])} · {html.escape(o['title'])}</b><br/>{_vn(r['start'])} – "
                       f"{_vn(r['end'])}<br/>{o['done']}/{o['total']} hạng mục xong"
                       + (f" · {o['late']} trễ hạn" if o["late"] else "")
                       + f"<br/><i>Bấm để {'thu gọn' if r['open'] else 'xem từng hạng mục'}</i>")
                off_i.append(s)
                len_i.append({"value": ln, "tip": tip, "itemStyle": {"color": "#D6E4D2" if not o["late"] else
                                                                     "#F3D9CC"}})
                if o["pct"]:
                    off_p.append(s)
                    len_p.append({"value": max(1, round(ln * o["pct"])), "tip": tip,
                                  "itemStyle": {"color": "#1E7C31"}})
                else:
                    off_p.append(none), len_p.append(none)
                continue
            i = r["i"]
            s, ln = x(i["start"]), x(i["end"]) - x(i["start"]) + 1
            late = O.is_late(i, today)
            doing = i["status"] == O.DOING and not late
            started = i["status"] == O.TODO and not late and i["start"] <= today.isoformat()
            prog = i.get("progress")
            color = ("#C2410C" if late else "#BFD3FB" if doing else STARTED if started else STATUS_COLOR[i["status"]])
            status = ("Trễ hạn · " + O.STATUS_LABEL[i["status"]] if late else
                      "Tới ngày bắt đầu, chưa bắt đầu" if started else O.STATUS_LABEL[i["status"]])
            tip = (f"<b>{html.escape(i['code'])} · {html.escape(i['title'])}</b><br/>{_vn(i['start'])} – "
                   f"{_vn(i['end'])} · {ln} ngày<br/>{status}" + (f" · {prog:.0f}%" if prog is not None else "")
                   + f"<br/>PIC: {html.escape(i['pic'] or 'chưa có')}")
            off_i.append(s)
            len_i.append({"value": ln, "tip": tip, "itemStyle": {"color": color}})
            if doing and prog:  # phần đã làm của thanh "đang làm"
                off_p.append(s)
                len_p.append({"value": max(1, round(ln * min(prog, 100) / 100)), "tip": tip,
                              "itemStyle": {"color": "#2563EB"}})
            else:
                off_p.append(none), len_p.append(none)

        bands, m = [], date(d0.year, d0.month, 1)
        while m <= d1:
            nm = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
            a, b = max(0, (m - d0).days), min(days, (nm - d0).days)
            bands.append([{"xAxis": a, "name": f"Tháng {m.month}",
                           "itemStyle": {"color": "rgba(31,34,30,0.035)" if m.month % 2 else "rgba(0,0,0,0)"}},
                          {"xAxis": b}])
            m = nm
        today_x = (today - d0).days
        ticks = [(d0 + timedelta(days=k)).strftime("%d/%m") for k in range(days)]
        hidden = {"color": "transparent"}
        bar = {"type": "bar", "barWidth": 12, "barGap": "-100%"}
        chart = ui.echart({
            "animation": False,
            "grid": {"left": 300, "right": 28, "top": 46, "bottom": 20},
            "tooltip": {"trigger": "item", "confine": True, "backgroundColor": "#fff", "borderColor": "#E7E5DC",
                        "textStyle": {"color": "#1F221E", "fontSize": 12},
                        ":formatter": "p => (p.data && p.data.tip) || ''"},
            "xAxis": {"type": "value", "min": 0, "max": days, "interval": 7, "position": "top",
                      "splitLine": {"lineStyle": {"color": "#EEECE4"}}, "axisLine": {"show": False},
                      "axisTick": {"show": False},
                      "axisLabel": {"color": "#8C8A7E", "fontSize": 10,
                                    ":formatter": f"v => ({json.dumps(ticks)})[v] || ''"}},
            "yAxis": {"type": "category", "data": keys, "axisTick": {"show": False}, "triggerEvent": True,
                      "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                      "axisLabel": {":formatter": f"v => ({json.dumps(labels, ensure_ascii=False)})[v] || ''",
                                    "align": "left", "margin": 290,
                                    "rich": {"oa": {"fontSize": 11, "color": "#6B6A5E"},
                                             "oc": {"fontWeight": 700, "fontSize": 12, "color": "#1E7C31"},
                                             "ot": {"fontWeight": 700, "fontSize": 12, "color": "#1F221E"},
                                             "op": {"fontSize": 11, "color": "#6B6A5E", "padding": [0, 0, 0, 4]},
                                             "ic": {"fontSize": 11, "color": "#8C8A7E", "padding": [0, 0, 0, 14]},
                                             "it": {"fontSize": 11.5, "color": "#3A3B35"}}}},
            "series": [
                {**bar, "stack": "i", "data": off_i, "itemStyle": hidden, "silent": True, "tooltip": {"show": False},
                 "markArea": {"silent": True, "data": bands,
                              "label": {"show": True, "position": "insideTop", "color": "#6B6A5E", "fontSize": 11,
                                        "fontWeight": 600, "offset": [0, -40]}},
                 "markLine": {"silent": True, "symbol": "none",
                              "lineStyle": {"color": "#C2410C", "width": 1.5, "type": "solid"},
                              "label": {"formatter": f"Hôm nay {today:%d/%m}", "color": "#C2410C", "fontSize": 10,
                                        "position": "start"},
                              "data": [{"xAxis": today_x}]} if 0 <= today_x <= days else {}},
                {**bar, "stack": "i", "data": len_i, "itemStyle": {"borderRadius": 6}, "cursor": "pointer"},
                {**bar, "stack": "p", "data": off_p, "itemStyle": hidden, "silent": True, "tooltip": {"show": False}},
                {**bar, "stack": "p", "data": len_p, "itemStyle": {"borderRadius": 6}},
            ],
        }).classes("w-full").style(f"min-width:720px;height:{max(160, 26 * len(rows) + 70)}px")

        def clicked(e) -> None:
            a = e.args or {}
            k = a.get("value") if a.get("componentType") == "yAxis" else (
                keys[a["dataIndex"]] if isinstance(a.get("dataIndex"), int) and a["dataIndex"] < len(keys) else None)
            u = uid_of.get(k)
            if not u or u == sel:
                return
            view["open"] = view["open"] ^ {u}
            plan_block.refresh()
        chart.on("componentClick", clicked, ["componentType", "value", "dataIndex"])

    @ui.refreshable
    def week_block(tasks, late, info):
        # tuần = tuần đang chọn ở thanh trên cùng (đổi tuần ở đó), giống mọi màn khác
        ps, pe = ws, we
        with connect() as c:
            p = O.overview(c, today, (ps, pe), cycle=view["cycle"])["period"]
        week_tasks = [t for t in tasks if t["week"] == ps.isoformat()]
        sub = "Đổi tuần ở thanh chọn tuần phía trên" + (" · đang là tuần này" if (ps, pe) == cur_week else "")
        with T.section(ui, f"Tuần {ps:%d/%m} – {pe:%d/%m}", "date_range", sub):
            if info and not cl:
                synced = datetime.fromisoformat(info["at"]).astimezone()
                with ui.row().classes("items-center gap-2 q-mb-sm"):
                    T.status_chip(ui, (f"Đọc task tuần từ sheet lúc {synced:%H:%M %d/%m} · {info['tasks']} task"
                                       if owned else
                                       f"Đồng bộ lúc {synced:%H:%M %d/%m} · {info['items']} hạng mục · "
                                       f"{info['tasks']} task tuần"), "grey", "schedule")
                    if info["source"] == "public":
                        with ui.element("div"):
                            T.status_chip(ui, "Đang đọc qua link công khai", "amber", "public")
                            ui.tooltip("Sheet đang để ai có link đều xem được. Sau khi cấp quyền Google Sheets cho "
                                       "tool (đăng nhập lại), nên tắt chia sẻ công khai.")
            period_lists(ui, p, late, "tuần")
            if has_sheet:
                task_table(ui, week_tasks, today, "tuần")
            elif not cl:
                ui.label("Task tuần đọc từ tab Weekly Task Tracker của sheet dự án: dự án này chưa gắn sheet.").classes(
                    "text-sm muted q-mt-md")


    with body:
        render()


def period_lists(ui, p: dict, late: list[dict], unit: str) -> None:
    """Bốn ô: đến hạn / hoàn thành trong kỳ, trễ hạn, kế hoạch kỳ sau (dùng ở màn OKR và báo cáo tuần/tháng)."""
    with ui.element("div").classes("w-full").style(
            "display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px"):
        note = (f"Sheet không có cột ngày hoàn thành: tính theo ngày tool thấy trạng thái đổi sang Hoàn thành "
                f"(theo dõi từ {_vn(p['tracking_since'])}).") if p["tracking_since"] else ""
        lists = [("Đến hạn", p["due"], "event", ""), ("Hoàn thành", p["done"], "task_alt", note),
                 ("Trễ hạn", late, "warning", "Quá ngày kết thúc, chưa Hoàn thành (tính đến hôm nay)"),
                 (f"{unit.capitalize()} sau", p["next"], "east", "")]
        for title, its, icon, tip in lists:
            with ui.element("div").classes("sr-card q-pa-md").style("border-radius:12px"):
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.icon(icon, size="18px").classes("muted")
                    ui.label(title).classes("text-sm font-semibold")
                    ui.label(str(len(its))).classes("text-xs muted num")
                    if tip:
                        ui.icon("info", size="14px").classes("muted").tooltip(tip)
                if not its:
                    ui.label("Không có").classes("text-sm muted")
                for i in its[:8]:
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        ui.element("span").classes("sr-dot").style(f"background:{STATUS_COLOR[i['status']]}")
                        ui.label(i["code"]).classes("text-xs muted").style("min-width:40px")
                        ui.label(i["title"]).classes("text-sm ellipsis").tooltip(
                            f"{i['title']} · {_vn(i['start'])} – {_vn(i['end'])} · {O.STATUS_LABEL[i['status']]}")
                if len(its) > 8:
                    ui.label(f"và {len(its) - 8} hạng mục khác").classes("text-xs muted")


def task_table(ui, rows: list[dict], today: date, unit: str) -> None:
    ui.label(f"Task {unit} · {len(rows)}").classes("text-sm font-semibold q-mt-md")
    if not rows:
        ui.label(f"Chưa có task trong {unit} này").classes("text-sm muted")
        return
    tbl = ui.table(columns=[
        {"name": "okr", "label": "Mã OKR", "field": "okr_code", "align": "left"},
        {"name": "task", "label": "Việc", "field": "task", "align": "left",
         "style": "white-space: normal; min-width: 260px"},
        {"name": "prio", "label": "Ưu tiên", "field": "priority", "align": "center"},
        {"name": "pic", "label": "PIC", "field": "pic", "align": "left"},
        {"name": "dl", "label": "Deadline", "field": "dl", "align": "center"},
        {"name": "st", "label": "Trạng thái", "field": "st", "align": "left"},
        {"name": "warn", "label": "Lưu ý", "field": "warn", "align": "left"},
    ], rows=[{**t, "dl": _vn(t["deadline"]), "st": O.STATUS_LABEL[t["status"]], "warn": _task_warning(t, today)}
             for t in rows], row_key="row").classes("w-full").props("flat bordered dense")
    tbl.add_slot("body-cell-warn", """
        <q-td :props="props"><span style="color:#C2410C; font-weight:600">{{ props.value }}</span></q-td>""")


def okr_report_section(ui, rep) -> None:
    """Khối 'Tiến độ công việc' trong báo cáo tuần/tháng."""
    k = rep.okr
    if not k:
        return
    unit = "tháng" if rep.kind == "month" else "tuần"
    today = date.today()
    cnt, total = k["counts"], k["total"]
    with T.section(ui, "Tiến độ công việc (OKR)", "task_alt",
                   f"Đọc từ Google Sheet của team · đồng bộ {k['synced'][8:10]}/{k['synced'][5:7]}",
                   href="/okr", link_text="Xem chi tiết"):
        with T.kpi_row(ui):
            T.kpi(ui, "flag", "Hoàn thành OKR 3 tháng",
                  f"{cnt[O.DONE] / total * 100:.0f}%" if total else "–", "", None,
                  hint=f"{cnt[O.DONE]} / {total} hạng mục")
            T.kpi(ui, "task_alt", f"Xong trong {unit}", str(len(k["period"]["done"])), "", None, tone="green",
                  hint=f"{len(k['period']['due'])} hạng mục đến hạn trong {unit}")
            T.kpi(ui, "autorenew", "Đang làm", str(cnt[O.DOING]), "", None, tone="blue")
            T.kpi(ui, "warning", "Trễ hạn", str(len(k["late"])), "", None, tone="amber" if k["late"] else "grey",
                  hint="Tính đến hôm nay")
        period_lists(ui, k["period"], k["late"], unit)
        task_table(ui, k["tasks"], today, unit)


def _sheet_issues(items: list[dict], tasks: list[dict], today: date) -> list[dict]:
    """Dòng trên sheet cần người phụ trách cập nhật: quá hạn mà chưa xong, hoặc % tiến độ không khớp trạng thái."""
    out = []
    for i in items:
        if O.is_late(i, today):
            out.append({"kind": "item", "code": i["code"], "text": i["title"], "reason": "Quá hạn",
                        "where": f"OKR · hạn {_vn(i['end'])}"})
        elif i["progress"] is not None and i["progress"] >= 100 and i["status"] != O.DONE:
            out.append({"kind": "item", "code": i["code"], "text": i["title"], "reason": "100% chưa Hoàn thành",
                        "where": "OKR"})
    for t in tasks:
        w = _task_warning(t, today)
        if w and w != "Chưa có deadline":
            out.append({"kind": "task", "code": t["okr_code"], "text": t["task"] or t["item"], "reason": w,
                        "where": f"Task tuần {_vn(t['week'])}" + (f" · hạn {_vn(t['deadline'])}" if t["deadline"]
                                                                    else "")})
    return out


def _task_warning(t: dict, today: date) -> str:
    """Điểm bất thường trong dòng task để người cập nhật sheet sửa."""
    if t["status"] != O.DONE and t["deadline"] and date.fromisoformat(t["deadline"]) < today:
        return "Quá deadline"
    if t["progress"] is not None and t["progress"] >= 100 and t["status"] != O.DONE:
        return "100% nhưng chưa đánh Hoàn thành"
    if not t["deadline"]:
        return "Chưa có deadline"
    return ""
