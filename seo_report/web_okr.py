"""Màn Công việc & OKR: tiến độ OKR 3 tháng và Weekly Task Tracker đọc từ Google Sheet của team (chỉ đọc)."""
import json
from datetime import date, datetime, timedelta

from . import access as A
from . import okr as O
from . import ui_theme as T

STATUS_TONE = {O.DONE: "green", O.DOING: "blue", O.WAIT: "amber", O.PAUSE: "purple", O.TODO: "grey",
               O.OTHER: "amber"}
STATUS_COLOR = {O.DONE: "#1E7C31", O.DOING: "#2563EB", O.WAIT: "#D9A441", O.PAUSE: "#8B5CF6", O.TODO: "#B8B6A8",
                O.OTHER: "#B7791F"}


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
                sync_btn.tooltip("Đọc lại task tuần từ sheet dự án")
        if ed and owned and (not project_sheet or A.is_admin(user)):
            ui.button("Sheet dự án", icon="add_to_drive", on_click=lambda: sheet_dialog()).props(
                "outline no-caps").tooltip("Xem, đổi hoặc gắn sheet dự án" if project_sheet else
                                           "Tạo hoặc gắn sheet dự án")
        if ed and owned:
            ui.button("Sửa OKR", icon="edit_note", on_click=lambda: ui.navigate.to("/okr/sua")).props(
                "unelevated no-caps color=primary")
        elif ed and has_sheet:  # chưa có sheet: thân trang đã có nút "Tạo OKR trên tool"
            ui.button("Chuyển OKR sang tool", icon="move_down", on_click=lambda: take_over_dialog()).props(
                "unelevated no-caps color=primary").tooltip("Tạo và sửa OKR ngay trên tool")

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
            ui.label("Tool tự ghi các tab của tool lên sheet; tab của team giữ nguyên.").classes(
                "text-sm muted")
            if project_sheet:
                cur_url = f"https://docs.google.com/spreadsheets/d/{project_sheet}/edit"
                with ui.element("div").classes("sr-card q-pa-md w-full q-mt-sm"):
                    ui.label("Đang gắn").classes("text-sm font-semibold")
                    with ui.row().classes("w-full items-center no-wrap gap-2"):
                        ui.label(cur_url).classes("text-xs muted ellipsis col").tooltip(cur_url)
                        ui.button("Mở", icon="open_in_new", on_click=lambda: ui.navigate.to(cur_url, new_tab=True)
                                  ).props("outline no-caps dense color=grey-9")
                        ui.button(icon="content_copy", on_click=lambda: (
                            ui.clipboard.write(cur_url), ui.notify("Đã chép link sheet", position="bottom-right"))
                                  ).props('flat round dense color=grey-8 aria-label="Chép link sheet"')
            create_box = ui.element("div").classes("sr-card q-pa-md w-full q-mt-sm")
            create_box.set_visibility(not project_sheet)  # đã có sheet: chỉ đổi bằng cách gắn sheet khác
            with create_box:
                ui.label("Tạo sheet mới").classes("text-sm font-semibold")
                ui.label(("Tạo từ sheet mẫu, lưu trong thư mục Drive của dự án." if master else
                          "Chưa có sheet mẫu gốc: tạo sheet trống có sẵn tab Weekly Task Tracker.")).classes(
                    "text-xs muted")
                create_btn = ui.button("Tạo sheet dự án", icon="add").props("unelevated no-caps color=primary").classes(
                    "q-mt-sm")
            can_attach = A.is_admin(user)  # gắn sheet có sẵn dùng token Google chung của chủ: chỉ Owner / Admin
            if can_attach:
                with ui.element("div").classes("sr-card q-pa-md w-full"):
                    ui.label("Gắn sheet khác" if project_sheet else "Hoặc gắn sheet đã có").classes(
                        "text-sm font-semibold")
                    if project_sheet:
                        ui.label("Tool ghi các tab của tool lên sheet mới; sheet cũ giữ nguyên.").classes(
                            "text-xs muted")
                    link = ui.input(placeholder="Dán link Google Sheet").props("outlined dense").classes(
                        "w-full q-mt-xs")
                    attach_btn = ui.button("Gắn sheet", icon="link").props("outline no-caps color=grey-9").classes(
                        "q-mt-sm")
            else:
                ui.label("Gắn sheet đã có: nhờ Admin hoặc Owner.").classes("text-xs muted q-mt-sm")
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
                if not A.is_admin(user):  # chặn cả sự kiện giả từ trình duyệt
                    err.text = "Chỉ Owner hoặc Admin gắn được sheet có sẵn"
                    return
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
            if can_attach:
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
                      "Tạo OKR ngay trên tool để theo dõi tiến độ.")
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
    view = {"gantt": "all", "cycle": None, "obj": None, "open": set(), "tab": "muctieu", "wk": None,
            "f_pic": None, "f_status": None, "f_obj": None, "q": "", "closed": {"later", "nodate", "pause", "done"}}
    STARTED = "#D99A2B"  # tới ngày bắt đầu mà chưa bắt đầu

    def open_it(uid: str) -> None:
        from .web_okr_item import open_item
        open_item(ui, connect, user, uid, render.refresh, ed and owned)

    def go_alerts() -> None:
        if view["tab"] != "viec":
            view["tab"] = "viec"
            render.refresh()
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
        if cl:  # khách hàng: một câu kết luận + danh sách mục tiêu; task tuần xem trong Báo cáo tuần / tháng
            client_summary(ov)
            client_plan(ov)
            return
        progress_block(ov, overdue_tasks, bool(issues) or bool(ov["late"]))

        # ---- 4 tab: OKRs · Việc cần làm · Tuần · Task tuần (tiến độ đợt luôn ở trên; mở trang vào OKRs) ----
        tabs_def = (("muctieu", "OKRs"), ("viec", "Việc cần làm"), ("tuan", f"Tuần {ws:%d/%m}"),
                    ("task", "Task tuần"))
        if view["tab"] not in dict(tabs_def):
            view["tab"] = "muctieu"
        n_late = len(ov["late"])
        with ui.tabs(value=view["tab"], on_change=lambda e: view.update(tab=e.value)).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs sr-bl-tabs") as tabs:
            for k, name in tabs_def:
                with ui.tab(k, name):
                    if k == "viec" and n_late:
                        T.count_badge(ui, n_late, f"{n_late} hạng mục trễ hạn").classes("sr-tab-badge")
                    if k == "task" and tasks:
                        T.count_badge(ui, len(tasks), f"{len(tasks)} task tuần", "grey").classes("sr-tab-badge")
        with ui.tab_panels(tabs, value=view["tab"]).classes("w-full").props("animated=false"):
            with ui.tab_panel("viec").classes("q-px-none column gap-4"):
                # Thông báo (trễ hạn / sắp đến hạn / chưa bắt đầu + task tuần cần cập nhật) + bảng theo dõi
                if owned and not cl:
                    from .web_okr_edit import alerts_panel
                    alerts_panel(ui, connect, user, ed, render.refresh, ov["cycle"], limit=3,
                                 tasks=[x for x in issues if x["kind"] == "task"], on_open=open_it,
                                 note="" if ed else "Người phụ trách (PIC) và quản lý dự án cập nhật các việc này; "
                                                    "bạn đang ở chế độ chỉ xem.")
                elif issues:
                    sheet_issues_block(issues)
                track_block(ov)
            with ui.tab_panel("muctieu").classes("q-px-none"):
                plan_block(ov)
            with ui.tab_panel("tuan").classes("q-px-none"):
                week_block(tasks, ov["late"], info)
            with ui.tab_panel("task").classes("q-px-none"):
                if not tasks:
                    T.empty_state(ui, "event_note", "Chưa có task tuần",
                                  "Task tuần đọc từ tab Weekly Task Tracker trên sheet dự án." if has_sheet else
                                  "Dự án chưa gắn sheet nên chưa có task tuần.")
                else:
                    with ui.element("div").classes("sr-card q-pa-md w-full"):
                        ui.label("Đọc từ tab Weekly Task Tracker trên sheet dự án (cập nhật trên sheet).").classes(
                            "text-xs muted q-mb-xs")
                        ui.table(columns=[
                            {"name": "week", "label": "Tuần", "field": "wk", "align": "left"},
                            {"name": "okr", "label": "Mã OKR", "field": "okr_code", "align": "left"},
                            {"name": "task", "label": "Việc", "field": "task", "align": "left",
                             "style": "white-space: normal; min-width: 260px"},
                            {"name": "pic", "label": "PIC", "field": "pic", "align": "left"},
                            {"name": "dl", "label": "Deadline", "field": "dl", "align": "center"},
                            {"name": "st", "label": "Trạng thái", "field": "st", "align": "left"},
                        ], rows=[{**t, "wk": _vn(t["week"]), "dl": _vn(t["deadline"]),
                                  "st": O.STATUS_LABEL[t["status"]]}
                                 for t in sorted(tasks, key=lambda t: t["week"] or "", reverse=True)],
                            row_key="row", pagination=50).classes("w-full").props("flat dense")

    # ------------------------------------------------------------ bảng theo dõi hạng mục (thao tác tại chỗ)
    @ui.refreshable
    def track_block(ov: dict) -> None:
        """Hạng mục của đợt, nhóm theo hạn (Quá hạn · Đang chờ · Tuần này · Tuần sau · Sau đó · Chưa có ngày · Đã xong),
        lọc theo người phụ trách / trạng thái / mục tiêu. Admin / Member đổi trạng thái và % ngay trên dòng; bấm tên
        mở khung chi tiết (ghi chú, link, gia hạn). Khách chỉ xem."""
        from .web_okr_edit import STATUS, change_status
        can = ed and owned
        with connect() as c:
            last = O.last_updates(c) if can else {}
        objs = {o["uid"]: o for o in ov["objectives"]}
        its = ov["items"]
        pics = sorted({p.strip() for i in its for p in (i["pic"] or "").split(",") if p.strip()})
        mon = today - timedelta(days=today.weekday())
        wk_end, nxt_end = mon + timedelta(days=6), mon + timedelta(days=13)

        def group(i) -> str:
            if i["status"] == O.DONE:
                return "done"
            if i["status"] == O.WAIT:
                return "wait"
            if i["status"] == O.PAUSE:
                return "pause"
            if O.is_late(i, today):
                return "late"
            if not i["end"]:
                return "nodate"
            e = date.fromisoformat(i["end"])
            return "week" if e <= wk_end else "next" if e <= nxt_end else "later"
        groups = (("late", "Quá hạn", "red", "event_busy"), ("wait", "Đang chờ bên ngoài", "amber", "hourglass_empty"),
                  ("week", f"Tuần này · hạn tới {wk_end:%d/%m}", "blue", "today"),
                  ("next", f"Tuần sau · {mon + timedelta(days=7):%d/%m} – {nxt_end:%d/%m}", "grey", "date_range"),
                  ("later", "Sau đó", "grey", "event"), ("nodate", "Chưa có ngày", "grey", "help_outline"),
                  ("pause", "Tạm hoãn (không tính vào % hoàn thành)", "purple", "pause_circle"),
                  ("done", "Đã xong", "green", "check_circle"))

        def keep(i) -> bool:
            if view["f_pic"] and view["f_pic"] not in [p.strip() for p in (i["pic"] or "").split(",")]:
                return False
            if view["f_status"] and i["status"] != view["f_status"]:
                return False
            if view["f_obj"] and i["objective"] != view["f_obj"]:
                return False
            q = (view["q"] or "").strip().lower()
            return not q or q in f"{i['code']} {i['title']} {i['pic'] or ''}".lower()
        shown = [i for i in its if keep(i)]

        def set_f(k, v):
            view[k] = v
            track_block.refresh(ov)

        def toggle_group(k):
            view["closed"] ^= {k}
            track_block.refresh(ov)

        def change(uid, **kw):
            try:
                with connect() as c:
                    O.update_item(c, uid, by=str(user), **kw)
            except ValueError as e:
                ui.notify(str(e), type="warning", position="bottom-right", classes="sr-toast")
                return
            render.refresh()

        with T.section(ui, "Theo dõi hạng mục", "checklist",
                       "Nhóm theo hạn; " + ("đổi trạng thái, % ngay trên dòng, bấm tên để ghi chú / thêm link"
                                            if can else "bấm tên để xem chi tiết và link bằng chứng")):
            with ui.row().classes("w-full items-center gap-2 q-mb-sm sr-ot-filters"):
                ui.input(placeholder="Tìm mã, tên, người phụ trách", value=view["q"]).props(
                    "outlined dense clearable debounce=300").classes("sr-ot-q").on_value_change(
                    lambda e: set_f("q", e.value or ""))
                ui.select({None: "Mọi người phụ trách", **{p: p for p in pics}}, value=view["f_pic"],
                          on_change=lambda e: set_f("f_pic", e.value)).props("outlined dense options-dense").classes(
                    "sr-ot-sel")
                ui.select({None: "Mọi trạng thái", **{s: lb for s, (lb, _, _) in STATUS.items()}},
                          value=view["f_status"], on_change=lambda e: set_f("f_status", e.value)).props(
                    "outlined dense options-dense").classes("sr-ot-sel")
                ui.select({None: "Mọi mục tiêu", **{u: f"{o['code']} · {o['title']}" for u, o in objs.items()}},
                          value=view["f_obj"], on_change=lambda e: set_f("f_obj", e.value)).props(
                    "outlined dense options-dense").classes("sr-ot-sel wide")
                if any(view[k] for k in ("f_pic", "f_status", "f_obj", "q")):
                    ui.button("Bỏ lọc", on_click=lambda: (view.update(f_pic=None, f_status=None, f_obj=None, q=""),
                                                         track_block.refresh(ov))).props(
                        "flat no-caps dense color=negative")
                ui.space()
                ui.label(f"{len(shown)} / {len(its)} hạng mục").classes("text-xs muted")
            if not shown:
                ui.label("Không có hạng mục nào khớp bộ lọc.").classes("text-sm muted")
            for key, name, tone, icon in groups:
                rows = sorted((i for i in shown if group(i) == key),
                              key=lambda i: (i["end"] or "9999", i["code"]))
                if not rows:
                    continue
                closed = key in view["closed"]
                with ui.element("button").classes(f"sr-ot-gh {tone}").props(
                        f'type="button" aria-expanded="{str(not closed).lower()}"').on(
                        "click", lambda _, k=key: toggle_group(k)):
                    ui.icon("chevron_right" if closed else "expand_more", size="18px").props('aria-hidden="true"')
                    ui.icon(icon, size="17px").classes("sr-ot-gi").props('aria-hidden="true"')
                    ui.label(name).classes("text-sm font-semibold")
                    ui.label(str(len(rows))).classes("sr-ot-n")
                if closed:
                    continue
                with ui.element("div").classes("sr-ot-list"):
                    for i in rows:
                        track_row(i, objs, last, can, STATUS, change_status, change)

    def track_row(i, objs, last, can, STATUS, change_status, change) -> None:
        uid = i["uid"]
        label, tone, icon = STATUS.get(i["status"], STATUS[O.TODO])
        bg, fg = T.TONES[tone]
        late = O.is_late(i, today)
        days = (date.fromisoformat(i["end"]) - today).days if i["end"] else None
        when = ("" if days is None else f"trễ {-days} ngày" if late else
                "hạn hôm nay" if days == 0 and i["status"] != O.DONE else
                f"còn {days} ngày" if days > 0 and i["status"] not in (O.DONE, O.WAIT) else "")
        with ui.element("div").classes("sr-ot-row" + (" done" if i["status"] == O.DONE else "")):
            ui.label(i["code"]).classes("sr-ot-code")
            with ui.column().classes("gap-0 sr-ot-main"):
                t = ui.label(i["title"]).classes("sr-ot-title")
                t.on("click", lambda _, u=uid: open_it(u))
                t.props('role="button" tabindex="0"').on("keydown.enter", lambda _, u=uid: open_it(u))
                o = objs.get(i["objective"])
                ui.label(f"{o['code']} · {o['title']}" if o else "").classes("text-xs muted ellipsis")
            ui.label(i["pic"] or "–").classes("sr-ot-pic text-sm ellipsis").tooltip(i["pic"] or "Chưa có PIC")
            with ui.column().classes("gap-0 sr-ot-due"):
                ui.label(_vn(i["end"]) if i["end"] else "–").classes("text-sm num")
                if i["status"] == O.WAIT and i.get("wait"):
                    ui.label(f"chờ {i['wait']['who_label']} {i['wait']['days']}n").classes("text-xs").style(
                        "color:#6B4A10")
                elif when:
                    ui.label(when).classes("text-xs" + (" text-negative" if late else " muted"))
            # trạng thái
            with ui.element("div").classes("sr-ot-st"):
                pill = ui.button().props(f'flat dense no-caps aria-label="Trạng thái {i["code"]}: {label}'
                                         + ('. Bấm để đổi"' if can else '"')).classes("sr-oe-pill").style(
                    f"background:{bg}; color:{fg}" + ("" if can else "; cursor: default"))
                with pill:
                    ui.icon(icon, size="15px").props('aria-hidden="true"')
                    ui.label(label)
                    if can:
                        ui.icon("expand_more", size="14px").props('aria-hidden="true"')
                        with ui.menu():
                            for s, (lb, tn, ic) in STATUS.items():
                                pick = (lambda _, s=s: change_status(ui, connect, user, [uid], s, render.refresh))
                                with ui.menu_item(on_click=pick).classes("items-center gap-2"):
                                    ui.icon(ic, size="16px").style(f"color:{T.TONES[tn][1]}")
                                    ui.label(lb).classes("text-sm")
            # % tiến độ
            pct = O.progress_of(i)
            if can:
                with ui.button(f"{pct:.0f}%").props(
                        f'flat dense no-caps aria-label="Tiến độ {i["code"]}: {pct:.0f}%. Bấm để đổi"').classes(
                        "sr-ot-pct"):
                    with ui.menu():
                        with ui.row().classes("q-pa-sm gap-1 no-wrap"):
                            for v in (0, 25, 50, 75, 100):
                                ui.button(f"{v}%", on_click=lambda _, v=v: change(uid, progress=v)).props(
                                    ("unelevated" if round(pct) == v else "outline color=grey-9")
                                    + " no-caps dense")
            else:
                ui.label(f"{pct:.0f}%").classes("sr-ot-pct num text-sm")
            # link + cập nhật gần nhất
            urls = O.links(i)
            with ui.element("div").classes("sr-ot-link"):
                if urls:
                    b = ui.button(str(len(urls)), icon="link").props(
                        f'flat dense no-caps color=primary aria-label="{len(urls)} link bằng chứng"')
                    if len(urls) == 1:
                        b.on_click(lambda _, u=urls[0]: ui.navigate.to(u, new_tab=True))
                        b.tooltip("Mở link bằng chứng")
                    else:
                        b.on_click(lambda _, u=uid: open_it(u))
                        b.tooltip("Xem các link bằng chứng")
            if can:
                lu = last.get(uid)
                with ui.element("div").classes("sr-ot-last"):
                    if lu:
                        from .web_okr_item import _when, _who
                        ui.label(lu["text"]).classes("text-xs ellipsis").tooltip(lu["text"])
                        ui.label(f"{_who(lu['by'])} · {_when(lu['at'])}").classes("text-xs muted")
                    else:
                        ui.button("Ghi cập nhật", icon="edit_note", on_click=lambda _, u=uid: open_it(u)).props(
                            "flat no-caps dense color=grey-7").classes("sr-ot-add")

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
                f"</div>" for s in (O.DONE, O.DOING, O.WAIT, O.PAUSE, O.TODO, O.OTHER) if cnt[s])
            mark = (f'<div title="Thời gian đã qua: {time_pct:.0f}%" style="position:absolute;top:-4px;bottom:-4px;'
                    f'left:calc({time_pct:.1f}% - 1px);width:2px;background:#1F221E;border-radius:1px"></div>'
                    if time_pct is not None and 0 < time_pct < 100 else "")
            ui.html(f'<div style="position:relative"><div style="display:flex;gap:3px;height:12px;border-radius:6px;'
                    f'overflow:hidden;background:#EEECE4">{seg}</div>{mark}</div>').classes("w-full")
            with ui.row().classes("items-center gap-x-4 gap-y-1 w-full"):
                for s in (O.DONE, O.DOING, O.WAIT, O.PAUSE, O.TODO, O.OTHER):
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
                    f" · {len(ov['waiting'])} đang chờ bên ngoài" if ov.get("waiting") else "") + (
                    f" · {overdue_tasks} task tuần quá deadline" if overdue_tasks else "")
                if (late or overdue_tasks) and has_alerts:
                    ui.button(text, icon="warning", on_click=go_alerts).props(
                        "flat no-caps dense color=negative").tooltip("Xem trong Thông báo OKR")
                else:
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon("check_circle", size="16px").style(f"color:{T.GREEN}").props('aria-hidden="true"')
                        ui.label(text).classes("text-sm muted")

    def client_summary(ov: dict) -> None:
        """Khách hàng: kế hoạch 3 tháng đang nhanh / đúng / chậm, nói bằng một câu, kèm thanh tiến độ và chú thích."""
        cnt, n = ov["counts"], ov["total"]
        cyc = next((c for c in ov["cycles"] if c["name"] == ov["cycle"]), None) or {}
        done_pct = cnt[O.DONE] / n * 100 if n else 0
        verdict, tone, detail = "", "grey", ""
        if cyc.get("start") and cyc.get("end"):
            d0, d1 = date.fromisoformat(cyc["start"]), date.fromisoformat(cyc["end"])
            span = (d1 - d0).days + 1
            time_pct = min(max((today - d0).days + 1, 0), span) / span * 100
            if today < d0:
                verdict, detail = "Kế hoạch sắp bắt đầu", f"Bắt đầu {_vn(cyc['start'])}, kết thúc {_vn(cyc['end'])}"
            elif today > d1:
                verdict, tone = "Kế hoạch đã kết thúc", "green" if done_pct >= 100 else "amber"
                detail = f"Kết thúc {_vn(cyc['end'])}"
            else:
                if done_pct + 10 < time_pct:
                    verdict, tone = "Chậm hơn kế hoạch", "amber"
                elif done_pct > time_pct + 10:
                    verdict, tone = "Nhanh hơn kế hoạch", "green"
                else:
                    verdict, tone = "Đúng tiến độ", "green"
                detail = f"Đã qua {time_pct:.0f}% thời gian ({_vn(cyc['start'])} – {_vn(cyc['end'])})"
        with ui.element("section").classes("sr-card q-pa-md w-full").props('aria-label="Tiến độ kế hoạch"'):
            with ui.row().classes("w-full items-center justify-between gap-2"):
                with ui.column().classes("gap-0"):
                    ui.label("Kế hoạch SEO 3 tháng").classes("text-xs muted font-medium")
                    with ui.row().classes("items-baseline gap-2"):
                        ui.label(f"{done_pct:.0f}%").classes("sr-bento-hero num")
                        ui.label(f"đã hoàn thành · {cnt[O.DONE]}/{n} việc").classes("text-sm muted")
                if verdict:
                    with ui.column().classes("items-end gap-0"):
                        T.status_chip(ui, verdict, tone, "trending_up" if tone == "green" else "schedule")
                        ui.label(detail).classes("text-xs muted q-mt-xs")
            seg = "".join(
                f'<div title="{O.STATUS_LABEL[s_]}: {cnt[s_]}" style="flex:{cnt[s_]};background:{STATUS_COLOR[s_]}">'
                f"</div>" for s_ in (O.DONE, O.DOING, O.WAIT, O.PAUSE, O.TODO, O.OTHER) if cnt[s_])
            ui.html(f'<div style="display:flex;gap:3px;height:10px;border-radius:5px;overflow:hidden;'
                    f'background:#EEECE4;margin-top:10px">{seg}</div>').classes("w-full")
            with ui.row().classes("items-center gap-x-4 gap-y-1 w-full q-mt-xs"):
                for s_ in (O.DONE, O.DOING, O.WAIT, O.TODO):
                    if cnt[s_]:
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.element("span").classes("sr-dot").style(f"background:{STATUS_COLOR[s_]}")
                            ui.label(f"{O.STATUS_LABEL[s_]} {cnt[s_]}").classes("text-sm")

    def client_plan(ov: dict) -> None:
        """Khách hàng: mục tiêu theo thời gian; mỗi dòng có nhãn trạng thái rõ (không hiện 0% cho mục chưa bắt đầu),
        bấm để xem các việc bên trong."""
        objs = sorted(ov["objectives"], key=lambda o: (o["start"] or "", o["end"] or ""))
        with T.section(ui, "Các mục tiêu", "flag", "Bấm một mục tiêu để xem các việc bên trong",
                       href="/report", link_text="Báo cáo tuần / tháng"):
            for o in objs:
                pct = o["pct"] or 0
                kids = [i for i in ov["items"] if i["objective"] == o["uid"]]
                not_started = bool(o["start"]) and o["start"] > today.isoformat()
                if pct >= 1:
                    label, tone = "Hoàn thành", "green"
                elif not_started:
                    label, tone = f"Sắp bắt đầu {_vn(o['start'])}", "grey"
                else:
                    label, tone = f"Đang làm · {o['done']}/{o['total']} việc xong", "blue"
                exp = ui.expansion().props("dense switch-toggle-side=false").classes("w-full sr-card q-mb-sm").style(
                    "border-radius:12px")
                with exp.add_slot("header"):
                    with ui.column().classes("w-full gap-1 q-py-xs"):
                        with ui.row().classes("items-center gap-2 no-wrap w-full"):
                            ui.label(o["title"]).classes("text-sm font-semibold col").style(
                                "display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden")
                            T.status_chip(ui, label, tone)
                        if not not_started:
                            ui.linear_progress(pct, show_value=False, size="6px",
                                               color="positive").classes("rounded-borders")
                        with ui.row().classes("items-center gap-2"):
                            ui.label(f"{_vn(o['start'])} – {_vn(o['end'])}").classes("text-xs muted")
                            if o["late"]:
                                T.status_chip(ui, f"{o['late']} việc trễ hạn", "red", "warning")
                            if o.get("waiting"):
                                T.status_chip(ui, f"{o['waiting']} việc chờ phản hồi", "amber", "hourglass_empty")
                with exp:
                    for i in kids:
                        late = O.is_late(i, today)
                        with ui.row().classes("items-center gap-2 no-wrap w-full q-py-xs"):
                            ui.element("span").classes("sr-dot").style(
                                f"background:{T.RED if late else STATUS_COLOR[i['status']]}")
                            ui.label(i["title"] or i["code"]).classes("text-sm col ellipsis").tooltip(i["title"] or "")
                            ui.label("Trễ hạn" if late else O.STATUS_LABEL[i["status"]]).classes("text-xs muted")
                            ui.label(_vn(i["end"]) if i["end"] else "").classes("text-xs muted num")

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
                    "display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px"):
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
                        if o["late"] or o.get("waiting"):
                            with ui.row().classes("gap-1"):
                                if o["late"]:
                                    T.status_chip(ui, f"{o['late']} việc trễ", "red", "warning")
                                if o.get("waiting"):
                                    T.status_chip(ui, f"{o['waiting']} đang chờ", "amber", "hourglass_empty")

        all_dated = [i for i in ov["items"] if i["start"] and i["end"]]
        if not all_dated:
            return
        with T.section(ui, "Lịch triển khai", "view_timeline",
                       "Bấm mục tiêu để xem hạng mục."):
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
        labels, uid_of, item_of = {}, {}, {}
        for k, r in zip(keys, rows):
            if r["kind"] == "obj":
                o = r["o"]
                uid_of[k] = o["uid"]
                arrow = "▾" if r["open"] else "▸"
                labels[k] = (f"{{oa|{arrow}}} {{oc|{o['code']}}} {{ot|{short(o['title'], 28)}}} "
                             f"{{op|{(o['pct'] or 0) * 100:.0f}%}}")
            else:
                i = r["i"]
                item_of[k] = i["uid"]
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
                      html.escape(O.wait_text(i.get("wait"))) if i["status"] == O.WAIT else
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
            if k in item_of and owned:  # thanh hạng mục: mở khung cập nhật
                open_it(item_of[k])
                return
            u = uid_of.get(k)
            if not u or u == sel:
                return
            view["open"] = view["open"] ^ {u}
            plan_block.refresh()
        chart.on("componentClick", clicked, ["componentType", "value", "dataIndex"])

    @ui.refreshable
    def week_block(tasks, late, info):
        # tuần đang xem: mặc định tuần chọn ở thanh trên cùng; bấm một dòng ở "Các tuần của đợt" để xem lại tuần cũ
        with connect() as c:
            hist = O.week_history(c, today, cycle=view["cycle"])
        ps, pe = view["wk"] or (ws, we)
        h = next((x for x in hist if x["start"] == ps), None)
        if h:
            p, late_ = h, h["late"]
        else:
            with connect() as c:
                p = O.overview(c, today, (ps, pe), cycle=view["cycle"])["period"]
            late_ = late
        week_tasks = [t for t in tasks if t["week"] == ps.isoformat()]
        sub = ("Đang xem lại tuần cũ · trễ hạn tính đến cuối tuần đó" if view["wk"] and pe < today else
               "Đổi tuần ở thanh chọn tuần phía trên hoặc bấm một tuần ở bảng bên dưới") + (
            " · đang là tuần này" if (ps, pe) == cur_week else "")
        with T.section(ui, f"Tuần {ps:%d/%m} – {pe:%d/%m}", "date_range", sub):
            if view["wk"]:
                ui.button("Về tuần đang chọn ở thanh trên", icon="undo", on_click=lambda: (
                    view.update(wk=None), week_block.refresh(tasks, late, info))).props(
                    "flat no-caps dense color=primary").classes("q-mb-xs")
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
                            ui.tooltip("Sheet đang công khai cho ai có link. Nên tắt chia sẻ công khai.")
            period_lists(ui, p, late_, "tuần", past=bool(h) and pe < today)
            if has_sheet:
                task_table(ui, week_tasks, today, "tuần")
            elif not cl:
                ui.label("Dự án chưa gắn sheet nên chưa có task tuần.").classes(
                    "text-sm muted q-mt-md")
        # ---- lịch sử: các tuần của đợt
        if hist:
            with T.section(ui, "Các tuần của đợt", "history", "Bấm một tuần để xem lại số liệu tuần đó"):
                rows = [{"id": x["start"].isoformat(), "wk": f"{x['start']:%d/%m} – {x['end']:%d/%m}"
                         + (" (tuần này)" if x["current"] else ""), "due": len(x["due"]), "done": len(x["done"]),
                         "late": len(x["late"]), "tasks": x["tasks"],
                         "on": "Đang xem" if x["start"] == ps else ""} for x in hist]
                tb = ui.table(columns=[
                    {"name": "wk", "label": "Tuần", "field": "wk", "align": "left"},
                    {"name": "due", "label": "Đến hạn", "field": "due", "align": "right"},
                    {"name": "done", "label": "Hoàn thành", "field": "done", "align": "right"},
                    {"name": "late", "label": "Trễ cuối tuần", "field": "late", "align": "right"},
                    {"name": "tasks", "label": "Task tuần", "field": "tasks", "align": "right"},
                    {"name": "on", "label": "", "field": "on", "align": "left"},
                ], rows=rows, row_key="id", pagination=0).props("flat dense hide-bottom").classes(
                    "w-full sr-bl-table sr-oi-rows")
                tb.add_slot("body-cell-late", """
                    <q-td :props="props"><span :style="props.value ? 'color:#C2410C;font-weight:600' : ''">
                    {{ props.value }}</span></q-td>""")
                tb.add_slot("body-cell-on", """
                    <q-td :props="props"><span v-if="props.value" class="sr-status"
                      style="background:#E7F3EA;color:#1E7C31">{{ props.value }}</span></q-td>""")

                def pick_week(e):
                    r = e.args[1] if len(e.args) > 1 else None
                    if not r:
                        return
                    s_ = date.fromisoformat(r["id"])
                    view["wk"] = None if s_ == ws else (s_, s_ + timedelta(days=6))
                    week_block.refresh(tasks, late, info)
                    ui.run_javascript("window.scrollTo({top: 0, behavior: 'smooth'})")
                tb.on("rowClick", pick_week)


    with body:
        render()


def period_lists(ui, p: dict, late: list[dict], unit: str, past: bool = False) -> None:
    """Bốn ô: đến hạn / hoàn thành trong kỳ, trễ hạn, kế hoạch kỳ sau (dùng ở màn OKR và báo cáo tuần/tháng)."""
    with ui.element("div").classes("w-full").style(
            "display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px"):
        note = (f"Sheet không có cột ngày hoàn thành: tính theo ngày tool thấy trạng thái đổi sang Hoàn thành "
                f"(theo dõi từ {_vn(p['tracking_since'])}).") if p["tracking_since"] else ""
        lists = [("Đến hạn", p["due"], "event", ""), ("Hoàn thành", p["done"], "task_alt", note),
                 ("Trễ hạn", late, "warning", "Quá ngày kết thúc, chưa Hoàn thành "
                  + ("(tính đến cuối tuần đó, theo hạn lúc đó)" if past else "(tính đến hôm nay)")),
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
                  hint="Tính đến hôm nay" + (f" · {len(k['waiting'])} đang chờ bên ngoài (không tính)"
                                             if k.get("waiting") else ""))
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
