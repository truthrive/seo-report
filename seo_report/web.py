"""Giao diện web (NiceGUI): khung chung (menu nhóm, thanh trên có tuần + nhóm URL dùng chung) và các trang."""
import getpass
from contextlib import closing

from . import access as A
from . import db
from . import urls as U
from .config import Config
from . import keywords as K
from . import rank as R
from . import report as RP
from . import ui_theme as T
from .web_ai import build_ai_page
from .web_index import build_index_page
from .web_rank import build_rank_page
from .web_report import build_report_page
from .web_okr import build_okr_page
from .web_kpi import build_kpi_page
from .web_overview import build_overview_page
from .web_url import build_url_page

PRIMARY = T.GREEN
NUMBER = "val => val.toLocaleString('vi-VN')"
# Menu chia nhóm: (tên nhóm hoặc None, [(nhãn, đường dẫn, icon)])
NAV = [
    (None, [("Tổng quan", "/", "space_dashboard"), ("Báo cáo tuần", "/report", "summarize"),
            ("Báo cáo tháng", "/report?kind=month", "calendar_month"), ("KPI cam kết", "/kpi", "flag"),
            ("Công việc & OKR", "/okr", "task_alt")]),
    ("SEO", [("Hiệu suất URL", "/url", "link"), ("Từ khóa & rank", "/rank", "leaderboard"),
             ("Index", "/index", "travel_explore")]),
    ("AI & GEO", [("AI Search & GEO", "/ai", "auto_awesome")]),
    ("Quản trị", [("Quản lý URL", "/urls", "folder_open"), ("Chất lượng dữ liệu", "/ai?tab=chat-luong", "verified")]),
]


def _col(name, label, align="left", number=False, sortable=True):
    col = {"name": name, "label": label, "field": name, "align": align, "sortable": sortable}
    if number:
        col[":format"] = NUMBER
        col["align"] = "right"
    return col


def _storage_secret(cfg: Config) -> str:
    """Khóa ký cookie lưu lựa chọn (tuần, nhóm) của từng trình duyệt; tạo một lần, lưu cạnh file dữ liệu."""
    import secrets
    path = cfg.db_path.parent / "ui_secret.txt"
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def run(cfg: Config, port: int = 8080, show: bool = True) -> None:
    from pathlib import Path

    from fastapi import Request
    from nicegui import app, ui

    T.install_table_defaults()
    assets = Path(__file__).parent / "assets"
    app.add_static_files("/assets", assets)  # logo lấy từ matkinhtamduc.com

    site = cfg.site_url
    local_name = getpass.getuser()

    def gate(request: Request) -> "A.User | None":
        """Người đang mở trang (chủ máy, hoặc email đăng nhập qua Cloudflare Access); không có quyền thì hiện màn
        báo chặn và trả về None."""
        who, why = A.identify(request.headers, cfg.access, local_name)
        if who is None:
            ui.add_head_html(T.HEAD)
            with ui.column().classes("absolute-center items-center gap-2 text-center"):
                ui.icon("lock", size="40px").classes("muted")
                ui.label("Không có quyền truy cập").classes("text-lg font-semibold")
                ui.label(f"{why}. Liên hệ người quản lý tool để được thêm email.").classes("text-sm muted")
        return who

    def connect():
        return closing(db.connect(cfg.db_path))

    def page_ctx() -> dict:
        """Tuần và nhóm URL dùng chung cho mọi màn (lưu theo trình duyệt): đổi ở thanh trên cùng là mọi màn theo."""
        store = app.storage.user
        with connect() as c:
            end = K.latest_date(c, site)
            groups = dict(U.list_groups(c, site))
            gid = U.ensure_group(c, site)
        wks = K.weeks(end, 12)
        starts = [w[0].isoformat() for w in wks]
        mths = RP.months(end, 12)
        mstarts = [m[0].isoformat() for m in mths]
        return {"weeks": wks, "week": starts.index(store["week"]) if store.get("week") in starts else 0,
                "months": mths, "month": mstarts.index(store["month"]) if store.get("month") in mstarts else 0,
                "groups": groups, "group": store["group"] if store.get("group") in groups else gid, "end": end}

    def shell(active: str, user, ctx: dict | None = None, period: bool | str = True, group: bool = True):
        ui.add_head_html(T.HEAD)
        ui.add_body_html(T.BODY)
        # Nút chính màu đen (phong cách viên thuốc); xanh thương hiệu dùng cho số tốt và thông báo thành công.
        ui.colors(primary=T.INK, secondary=T.LIME, positive=PRIMARY, negative=T.RED, warning=T.AMBER)
        # Menu trái thu gọn được (chỉ còn icon); lựa chọn nhớ theo trình duyệt.
        mini = bool(app.storage.user.get("nav_mini"))
        drawer = ui.left_drawer(value=True, fixed=True).props(
            "width=232 mini-width=64" + (" mini" if mini else "")).style(
            f"background:{T.CREAM}; border-right:1px solid #E7E5DC; padding:0")
        with drawer, ui.column().classes("w-full no-wrap gap-0").style(
                "height:100%; padding:12px 8px; overflow-y:auto; overflow-x:hidden"):
            with ui.column().classes("gap-1 q-px-sm q-mini-drawer-hide"):
                ui.image("/assets/logo.svg").props("fit=contain no-spinner").style("width: 160px; height: 46px")
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.icon("insights", size="15px").style(f"color:{T.GREEN}")
                    ui.label("SEO Report").classes("text-xs font-semibold muted").style("letter-spacing: .04em")
            with ui.element("div").classes("q-mini-drawer-only w-full"):
                ui.image("/assets/logo-mark.png").props("fit=contain no-spinner").classes("sr-logo-mark")
            with ui.column().classes("sr-nav w-full gap-0 q-mt-sm"):
                for group_name, items in NAV:
                    if not A.can_edit(user):  # người chỉ xem không vào màn quản trị
                        items = [it for it in items if it[1] != "/urls"]
                    if group_name:
                        ui.label(group_name).classes("sr-nav-group")
                    for label, href, icon in items:
                        with ui.link(target=href).classes("active" if label == active else ""):
                            ui.icon(icon, size="19px")
                            ui.label(label).classes("q-mini-drawer-hide")
                            if mini:
                                ui.tooltip(label).props("anchor='center right' self='center left'")
            ui.space()

            @ui.refreshable
            def budget_card():
                with connect() as c:
                    st = R.budget_status(c, site, cfg.rank, K.latest_date(c, site))
                warn = st["ratio"] >= R.ALERT_RATIO
                with ui.element("div").classes("sr-card q-pa-sm q-mt-lg w-full q-mini-drawer-hide"):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon("account_balance_wallet", size="16px").classes("muted")
                        ui.label("Ngân sách check rank").classes("text-xs muted")
                    ui.label(f"{R.usd(st['estimate'])} / {st['budget']:.0f} USD/tháng").classes(
                        "text-sm font-semibold num")
                    ui.linear_progress(min(st["ratio"], 1), show_value=False, size="6px",
                                       color="orange-8" if warn else "primary").classes("rounded-borders")
                    ui.label(f"{st['stars']} keyword · đã dùng {R.usd(st['spent'])} USD tháng này").classes(
                        "text-xs muted")
                    if warn:
                        ui.label("Đã vượt 80% ngân sách").classes("text-xs text-orange-9")

            budget_card()
            with ui.row().classes("items-center gap-2 q-mt-sm q-px-sm no-wrap").style("flex-shrink:0"):
                ui.avatar(user[:1].upper(), color="green-1", text_color="green-10", size="28px", font_size="13px")
                with ui.column().classes("gap-0 q-mini-drawer-hide").style("min-width:0"):
                    ui.label(user).classes("text-sm ellipsis").tooltip(str(user))
                    if user.role != A.LOCAL:
                        ui.label("Được sửa" if A.can_edit(user) else "Chỉ xem").classes("text-xs muted")

        def toggle_nav():
            app.storage.user["nav_mini"] = not app.storage.user.get("nav_mini")
            if app.storage.user["nav_mini"]:
                drawer.props("mini")
            else:
                drawer.props(remove="mini")

        # Thanh trên gọn, tự ẩn khi cuộn xuống và hiện lại khi cuộn lên (reveal).
        with ui.header().props("reveal reveal-offset=120").classes("sr-top q-px-md q-py-xs items-center gap-2"):
            ui.button(icon="menu_open" if not mini else "menu", on_click=lambda e: (
                toggle_nav(), e.sender.props(f"icon={'menu' if app.storage.user['nav_mini'] else 'menu_open'}"))).props(
                "flat round dense color=grey-8").tooltip("Thu gọn / mở rộng menu")
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.icon("language", size="15px").classes("muted")
                ui.label(site.removeprefix("https://").rstrip("/")).classes("text-sm font-medium")
            ui.space()
            if ctx and (period or group):
                def pick(key, value):
                    app.storage.user[key] = value
                    ui.navigate.reload()

                if period == "month":
                    ui.select({m[0].isoformat(): f"Tháng {m[0]:%m/%Y}" for m in ctx["months"]},
                              value=ctx["months"][ctx["month"]][0].isoformat(),
                              on_change=lambda e: pick("month", e.value)).props(
                        "dense outlined options-dense").classes("w-64")
                elif period:
                    ui.select({w[0].isoformat(): f"Tuần {w[0]:%d/%m} – {w[1]:%d/%m/%Y}" for w in ctx["weeks"]},
                              value=ctx["weeks"][ctx["week"]][0].isoformat(),
                              on_change=lambda e: pick("week", e.value)).props(
                        "dense outlined options-dense").classes("w-64")
                if group:
                    ui.select(ctx["groups"], value=ctx["group"], on_change=lambda e: pick("group", e.value)).props(
                        "dense outlined options-dense").classes("w-44")
            if not A.can_edit(user):
                T.status_chip(ui, "Chỉ xem", "grey", "visibility")
            if ctx:
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.icon("schedule", size="16px").classes("muted")
                    ui.label(f"GSC đến {ctx['end']:%d/%m}").classes("text-xs muted")
        return budget_card

    @ui.page("/")
    def overview_page(request: Request):
        if not (user := gate(request)):
            return
        ctx = page_ctx()
        shell("Tổng quan", user, ctx)
        build_overview_page(ui, cfg, connect, user, ctx)

    @ui.page("/ai")
    def ai_page(request: Request):
        if not (user := gate(request)):
            return
        params = dict(request.query_params)
        ctx = page_ctx()
        shell("Chất lượng dữ liệu" if params.get("tab") == "chat-luong" else "AI Search & GEO", user, ctx, group=False)
        build_ai_page(ui, cfg, connect, user, params, week=ctx["weeks"][ctx["week"]])

    @ui.page("/report")
    def report_page(request: Request):
        if not (user := gate(request)):
            return
        kind = "month" if request.query_params.get("kind") == "month" else "week"
        ctx = page_ctx()
        shell("Báo cáo tháng" if kind == "month" else "Báo cáo tuần", user, ctx, period=kind)
        build_report_page(ui, cfg, connect, user, ctx, kind)

    @ui.page("/url")
    def url_page(request: Request):
        if not (user := gate(request)):
            return
        ctx = page_ctx()
        budget_card = shell("Hiệu suất URL", user, ctx)
        build_url_page(ui, cfg, connect, user, on_budget_change=budget_card.refresh, ctx=ctx)

    @ui.page("/okr")
    def okr_page(request: Request):
        if not (user := gate(request)):
            return
        ctx = page_ctx()
        shell("Công việc & OKR", user, ctx, group=False)
        build_okr_page(ui, cfg, connect, user, ctx)

    @ui.page("/kpi")
    def kpi_page(request: Request):
        if not (user := gate(request)):
            return
        shell("KPI cam kết", user, page_ctx(), period=False, group=False)
        build_kpi_page(ui, cfg, connect, user)

    @ui.page("/index")
    def index_page(request: Request):
        if not (user := gate(request)):
            return
        shell("Index", user, page_ctx(), period=False, group=False)
        build_index_page(ui, cfg, connect, user)

    @ui.page("/rank")
    def rank_page(request: Request):
        if not (user := gate(request)):
            return
        budget_card = shell("Từ khóa & rank", user, page_ctx(), period=False, group=False)
        build_rank_page(ui, cfg, connect, user, on_budget_change=budget_card.refresh)

    @ui.page("/stars")
    def stars_page():
        ui.navigate.to("/rank")

    def url_col(name="url", label="URL"):
        """Cột URL chỉ hiện đường dẫn (bỏ tên miền), cắt "…" khi dài."""
        col = _col(name, label)
        col[":format"] = f"val => (val || '').replace('{site.rstrip('/')}', '') || '/'"
        col.update({"classes": "ellipsis", "style": "max-width: 420px", "headerStyle": "max-width: 420px"})
        return col

    @ui.page("/urls")
    def urls_page(request: Request):
        if not (user := gate(request)):
            return
        if not A.can_edit(user):
            ui.navigate.to("/")
            return
        shell("Quản lý URL", user, page_ctx(), period=False, group=False)
        with connect() as c:
            U.assign_urls(c, site)
            state = {"group": U.ensure_group(c, site)}

        header = ui.column().classes("w-full gap-1")
        with ui.row().classes("items-end gap-3"):
            group_select = ui.select({}, label="Nhóm URL").props("dense outlined").classes("w-64")
            ui.button("Nhóm mới", icon="add", on_click=lambda: new_group_dialog.open()).props("flat no-caps")

        with ui.dialog() as new_group_dialog, ui.card():
            name_input = ui.input("Tên nhóm, ví dụ: Campaign Q4").classes("w-72")
            with ui.row():
                ui.button("Tạo", on_click=lambda: create_group(name_input.value))
                ui.button("Hủy", on_click=new_group_dialog.close).props("flat")

        with ui.tabs().classes("w-full sr-tabs q-mt-sm").props("align=left no-caps dense") as tabs:
            t_members = ui.tab("Trong nhóm")
            t_add = ui.tab("Thêm link")
            t_suggest = ui.tab("Gợi ý")
            t_all = ui.tab("Tất cả URL")
            t_log = ui.tab("Nhật ký")

        def type_changer(get_selected, after):
            with ui.row().classes("items-center gap-2"):
                sel = ui.select(U.TYPES, label="Đổi loại thành").classes("w-56")

                def apply():
                    rows = get_selected()
                    if not rows or not sel.value:
                        ui.notify("Chọn URL và loại trước", type="warning")
                        return
                    with connect() as c:
                        U.set_type(c, site, [r["id"] for r in rows], sel.value, user)
                    ui.notify(f"Đã đổi {len(rows)} URL sang {sel.value}", type="positive")
                    after()

                ui.button("Áp dụng", on_click=apply).props("outline")

        with ui.tab_panels(tabs, value=t_members).classes("w-full"):
            with ui.tab_panel(t_members):
                members = ui.table(
                    columns=[url_col(), _col("type", "Loại"), _col("clicks", "Click 90 ngày", number=True),
                             _col("impressions", "Impression 90 ngày", number=True),
                             _col("added_at", "Ngày thêm"), _col("added_by", "Người thêm")],
                    rows=[], row_key="id", selection="multiple", pagination=50,
                ).classes("w-full").props("flat bordered dense")
                with ui.row().classes("items-center gap-4"):
                    ui.button("Bỏ khỏi nhóm", icon="remove_circle_outline",
                              on_click=lambda: remove_selected()).props("outline color=negative")
                    type_changer(lambda: members.selected, lambda: refresh())
                ui.label("Bỏ khỏi nhóm không xóa số liệu hay lịch sử của URL.").classes("text-sm muted")

            with ui.tab_panel(t_add):
                ui.label("Dán danh sách link, mỗi link một dòng. Không cần lo / cuối, www, #mục hay ?utm_…").classes("muted")
                paste = ui.textarea(placeholder="https://matkinhtamduc.com/gong-kinh/\nmatkinhtamduc.com/mat-xech-la-gi").props(
                    "outlined autogrow").classes("w-full")
                ui.button("Thêm vào nhóm", icon="playlist_add", on_click=lambda: add_pasted())
                add_result = ui.column().classes("w-full")

            with ui.tab_panel(t_suggest):
                ui.label("URL nhiều click nhất 90 ngày qua chưa có trong nhóm (đã bỏ URL cũ/kỹ thuật).").classes("muted")
                suggest_type = ui.select(["Tất cả"] + U.TYPES, value="Tất cả", label="Loại",
                                         on_change=lambda: refresh()).classes("w-56")
                suggest = ui.table(
                    columns=[url_col(), _col("type", "Loại"), _col("clicks", "Click 90 ngày", number=True),
                             _col("impressions", "Impression 90 ngày", number=True)],
                    rows=[], row_key="id", selection="multiple", pagination=25,
                ).classes("w-full").props("flat bordered dense")
                ui.button("Thêm URL đã chọn vào nhóm", icon="playlist_add", on_click=lambda: add_suggested())

            with ui.tab_panel(t_all):
                with ui.row().classes("items-end gap-3"):
                    search = ui.input("Tìm URL").props("clearable").classes("w-80")
                    all_type = ui.select(["Tất cả", "Chờ đọc schema"] + U.TYPES, value="Tất cả", label="Loại",
                                         on_change=lambda: refresh()).classes("w-56")
                all_table = ui.table(
                    columns=[url_col(), _col("type", "Loại"), _col("source", "Nguồn phân loại"),
                             _col("note", "Ghi chú"), _col("clicks", "Click 90 ngày", number=True),
                             _col("impressions", "Impression 90 ngày", number=True)],
                    rows=[], row_key="id", selection="multiple", pagination=50,
                ).classes("w-full").props("flat bordered dense")
                search.bind_value(all_table, "filter")
                type_changer(lambda: all_table.selected, lambda: refresh())
                ui.label("Nguồn phân loại: rule = theo đường dẫn, schema = đọc trong trang, manual = sửa tay "
                         "(sửa tay luôn được giữ).").classes("text-sm muted")

            with ui.tab_panel(t_log):
                log_table = ui.table(
                    columns=[_col("at", "Thời gian (UTC)"), _col("user", "Người"), _col("action", "Thao tác"),
                             url_col(), _col("detail", "Chi tiết")],
                    rows=[], row_key="at", pagination=50,
                ).classes("w-full").props("flat bordered dense")

        def refresh():
            with connect() as c:
                groups = dict(U.list_groups(c, site))
                group_select.set_options(groups, value=state["group"])
                member_rows = U.group_members(c, state["group"])
                for r in member_rows:
                    r["added_at"] = r["added_at"][:10]
                members.rows = member_rows
                members.selected = []
                t_members.props(f'label="Trong nhóm ({len(member_rows)})"')
                rows = U.suggestions(c, site, state["group"], limit=300)
                if suggest_type.value != "Tất cả":
                    rows = [r for r in rows if r["type"] == suggest_type.value]
                suggest.rows = rows
                suggest.selected = []
                rows = U.all_urls(c, site)
                if all_type.value != "Tất cả":
                    rows = [r for r in rows if r["type"] == all_type.value]
                all_table.rows = rows
                all_table.selected = []
                log_table.rows = U.recent_changes(c, site)
                summary = U.type_summary(c, site)
            header.clear()
            with header:
                total = sum(n for _, n in summary)
                T.page_header(ui, "folder_open", "Quản lý URL", f"{total:,} URL có dữ liệu GSC, chia theo loại "
                              "trang".replace(",", "."), tone="grey")
                with ui.row().classes("gap-2"):
                    for t, n in summary:
                        T.status_chip(ui, f"{t}: {n:,}".replace(",", "."),
                                      "grey" if t in ("URL cũ/kỹ thuật", "Chờ đọc schema") else "green")

        def on_group_change(e):
            if e.value:
                state["group"] = e.value
                refresh()

        def create_group(name):
            if not (name or "").strip():
                return
            with connect() as c:
                state["group"] = U.ensure_group(c, site, name)
                U.log_change(c, user, site, "Tạo nhóm", None, name.strip())
                c.commit()
            new_group_dialog.close()
            name_input.value = ""
            refresh()

        def remove_selected():
            if not members.selected:
                ui.notify("Chọn URL cần bỏ trước", type="warning")
                return
            with connect() as c:
                U.remove_from_group(c, site, state["group"], [r["id"] for r in members.selected], user)
            ui.notify(f"Đã bỏ {len(members.selected)} URL khỏi nhóm", type="positive")
            refresh()

        def show_result(r):
            add_result.clear()
            with add_result:
                ui.label(f"Đã thêm {len(r['added'])} · Đã có sẵn {len(r['already'])} · "
                         f"Chưa có dữ liệu GSC {len(r['no_data'])} · Không phải link {len(r['invalid'])}")
                for key, title in [("no_data", "Chưa có dữ liệu GSC (sai link, chưa index hoặc chưa có impression)"),
                                   ("invalid", "Không nhận ra là link")]:
                    if r[key]:
                        with ui.expansion(f"{title}: {len(r[key])}").classes("w-full"):
                            for u in r[key]:
                                ui.label(u).classes("text-sm")

        def add_pasted():
            if not (paste.value or "").strip():
                return
            with connect() as c:
                r = U.add_to_group(c, site, state["group"], paste.value, user)
            paste.value = ""
            show_result(r)
            refresh()

        def add_suggested():
            if not suggest.selected:
                ui.notify("Tích chọn URL trước", type="warning")
                return
            with connect() as c:
                r = U.add_to_group(c, site, state["group"], "\n".join(s["url"] for s in suggest.selected), user)
            ui.notify(f"Đã thêm {len(r['added'])} URL vào nhóm", type="positive")
            refresh()

        refresh()
        group_select.on_value_change(on_group_change)

    # Chỉ nghe trên máy này. Người ngoài vào qua Cloudflare Tunnel + Access (access.py), không mở cho mạng LAN.
    ui.run(host="127.0.0.1", port=port, title="SEO Report", reload=False, show=show, language="vi",
           storage_secret=_storage_secret(cfg), favicon=assets / "favicon.png")
