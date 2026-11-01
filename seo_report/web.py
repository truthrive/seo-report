"""Giao diện web (NiceGUI): khung chung (menu nhóm, thanh trên có tuần + nhóm URL dùng chung) và các trang."""
import getpass
from contextlib import closing
from types import SimpleNamespace

from . import access as A
from . import db
from . import urls as U
from .config import Config
from . import keywords as K
from . import projects as PJ
from . import rank as R
from . import report as RP
from . import ui_theme as T
from .web_ai import build_ai_page
from .web_index import build_index_page
from .web_rank import build_rank_page
from .web_report import build_report_page
from .web_okr import build_okr_page
from .web_kpi import build_kpi_page
from .web_access import build_access_page
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
    ("Quản trị", [("Quản lý URL", "/urls", "folder_open"), ("Chất lượng dữ liệu", "/ai?tab=chat-luong", "verified"),
                  ("Dự án", "/projects", "domain"), ("Phân quyền", "/access", "admin_panel_settings")]),
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

    base = cfg  # cấu hình chung (config.toml); số liệu theo dự án lấy qua project_scope()
    local_name = getpass.getuser()
    with closing(db.connect(base.db_path)) as c:
        PJ.ensure(c, base)
        A.migrate_members(c, base.access, PJ.list_projects(c)[0]["slug"])

    def app_connect():
        """File dữ liệu chính: danh sách dự án, tài khoản, phân quyền."""
        return closing(db.connect(base.db_path))

    def project_scope(acct) -> SimpleNamespace | None:
        """Dự án đang mở trên trình duyệt này (chọn ở thanh trên cùng), chỉ trong các dự án người này được vào: cấu
        hình, website, file dữ liệu và người dùng mang quyền trong dự án đó. None khi chưa được vào dự án nào.

        Đây là chốt chặn ở máy chủ: mọi trang chỉ đọc file dữ liệu của dự án trả về ở đây, nên đổi giá trị lưu trên
        trình duyệt cũng không mở được dự án không được cấp."""
        with app_connect() as c:
            active = PJ.list_projects(c)
            first = active[0]["slug"] if active else None
            allowed = [(p, r) for p in active if (r := A.project_role(c, base.access, acct, p["slug"], first))]
        if not allowed:
            return None
        want = app.storage.user.get("project")
        project, role = next(((p, r) for p, r in allowed if p["slug"] == want), allowed[0])
        pc = PJ.config_for(base, project)
        return SimpleNamespace(project=project, projects=[p for p, _ in allowed], cfg=pc, site=pc.site_url,
                               connect=lambda: closing(db.connect(pc.db_path)), user=A.in_project(acct, role))

    def no_project(acct) -> None:
        ui.add_head_html(T.HEAD)
        with ui.column().classes("absolute-center items-center gap-2 text-center"):
            ui.icon("folder_off", size="40px").classes("muted")
            ui.label("Tài khoản chưa được gắn dự án nào").classes("text-lg font-semibold")
            ui.label(f"{acct} đăng nhập được nhưng chưa được cấp xem website nào. Liên hệ người quản lý tool.").classes(
                "text-sm muted")
            if getattr(acct, "via", "") == "password":
                ui.button("Đăng xuất", on_click=lambda: (app.storage.user.pop("auth", None),
                                                         ui.navigate.to("/login"))).props("flat no-caps")

    def open_page(request: Request, *, client_ok: bool = False, edit: bool = False, admin: bool = False):
        """Mở một trang: đã đăng nhập, có dự án được vào, đủ quyền cho trang này. Trả (người dùng trong dự án, dự án)
        hoặc None (đã chuyển hướng / hiện thông báo, không dựng nội dung trang)."""
        if not (acct := gate(request)):
            return None
        if admin and not A.is_admin(acct):
            ui.navigate.to("/")
            return None
        P = project_scope(acct)
        if P is None:
            no_project(acct)
            return None
        if (edit and not A.can_edit(P.user)) or (A.is_client(P.user) and not client_ok):
            ui.navigate.to("/")  # khách hàng chỉ mở các màn báo cáo; màn sửa chỉ cho người được sửa
            return None
        app.storage.client["only_links"] = list(A.CLIENT_PAGES) if A.is_client(P.user) else None  # T.link_allowed
        return P.user, P

    def gate(request: Request, allow_must_change: bool = False) -> "A.User | None":
        """Người đang mở trang: chủ máy (mở thẳng trên máy này), người đã đăng nhập bằng mật khẩu, hoặc email đã được
        Cloudflare Access / Tailscale xác minh. Chưa đăng nhập thì chuyển sang /login; đang dùng mật khẩu tạm thì
        chuyển sang /doi-mat-khau. Trả về None khi trang không được hiện."""
        with app_connect() as c:  # danh sách trong config.toml + danh sách trên màn Phân quyền
            settings = A.effective(c, base.access)
            host = request.client.host if request.client else None
            who, why = A.identify(request.headers, settings, local_name, host)
            if who is None and not why:
                who = A.from_session(c, settings, app.storage.user.get("auth"))
        if who is not None and who.role == A.LOCAL and app.storage.user.get("as_viewer"):
            # chủ máy xem thử giao diện của người chỉ xem / khách hàng
            mode = A.CLIENT if app.storage.user.get("as_viewer") == A.CLIENT else A.VIEWER
            who = A.User(local_name, mode, preview=True, admin=True)
        if who is None:
            if why:  # lớp đăng nhập phía trước báo email này không có quyền
                ui.add_head_html(T.HEAD)
                with ui.column().classes("absolute-center items-center gap-2 text-center"):
                    ui.icon("lock", size="40px").classes("muted")
                    ui.label("Không có quyền truy cập").classes("text-lg font-semibold")
                    ui.label(f"{why}. Liên hệ người quản lý tool để được thêm email.").classes("text-sm muted")
            else:
                from urllib.parse import quote
                target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
                ui.navigate.to("/login?next=" + quote(target, safe=""))
            return None
        if who.must_change and not allow_must_change:
            ui.navigate.to("/doi-mat-khau")
            return None
        return who

    def group_key(P) -> str:
        return f"group:{P.project['slug']}"  # nhóm URL là của từng dự án

    def page_ctx(P) -> dict:
        """Tuần và nhóm URL dùng chung cho mọi màn (lưu theo trình duyệt): đổi ở thanh trên cùng là mọi màn theo."""
        store = app.storage.user
        with P.connect() as c:
            end = K.latest_date(c, P.site)
            gid = U.ensure_group(c, P.site)  # trước list_groups: dự án mới chưa có nhóm nào
            groups = dict(U.list_groups(c, P.site))
        wks = K.weeks(end, 12)
        starts = [w[0].isoformat() for w in wks]
        mths = RP.months(end, 12)
        mstarts = [m[0].isoformat() for m in mths]
        return {"weeks": wks, "week": starts.index(store["week"]) if store.get("week") in starts else 0,
                "months": mths, "month": mstarts.index(store["month"]) if store.get("month") in mstarts else 0,
                "groups": groups, "group": store[group_key(P)] if store.get(group_key(P)) in groups else gid,
                "end": end}

    def shell(active: str, user, P, ctx: dict | None = None, period: bool | str = True, group: bool = True):
        ui.add_head_html(T.HEAD)
        ui.add_body_html(T.BODY)
        # Nút chính màu đen (phong cách viên thuốc); xanh thương hiệu dùng cho số tốt và thông báo thành công.
        ui.colors(primary=T.INK, secondary=T.LIME, positive=PRIMARY, negative=T.RED, warning=T.AMBER)
        # Menu trái thu gọn được (chỉ còn icon); lựa chọn nhớ theo trình duyệt.
        mini = bool(app.storage.user.get("nav_mini"))
        # Màn rộng: menu mở sẵn, nằm cạnh thanh trên (không bị che logo). Điện thoại / màn hẹp: menu đóng, bấm ☰ để mở.
        drawer = ui.left_drawer(value=None, fixed=True, top_corner=True, bottom_corner=True).props(
            "width=232 mini-width=64" + (" mini" if mini else "")).style(
            f"background:{T.CREAM}; border-right:1px solid #E7E5DC; padding:0")
        with drawer, ui.column().classes("w-full no-wrap gap-0").style(
                "height:100%; padding:12px 8px; overflow-y:auto; overflow-x:hidden"):
            logo = P.project["logo"]
            with ui.column().classes("gap-1 q-px-sm sr-mini-hide"):
                if logo:
                    ui.image(logo).props("fit=contain no-spinner").style("width: 160px; height: 46px")
                else:  # dự án chưa có logo: tên dự án
                    ui.label(P.project["name"]).classes("sr-section-title ellipsis").style("max-width: 200px")
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.icon("insights", size="15px").style(f"color:{T.GREEN}")
                    ui.label("SEO Report").classes("text-xs font-semibold muted").style("letter-spacing: .04em")
            with ui.element("div").classes("sr-mini-only w-full"):
                if logo == "/assets/logo.svg":
                    ui.image("/assets/logo-mark.png").props("fit=contain no-spinner").classes("sr-logo-mark")
                else:
                    ui.avatar(P.project["name"][:1].upper(), color="green-1", text_color="green-10", size="36px",
                              font_size="16px").classes("q-mx-auto")
            with ui.column().classes("sr-nav w-full gap-0 q-mt-sm"):
                for group_name, items in NAV:
                    if not A.can_edit(user) and group_name == "Quản trị":  # người chỉ xem không vào màn quản trị
                        continue
                    items = [(label, href, icon) for label, href, icon in items
                             if (not A.is_client(user) or href.split("?")[0] in A.CLIENT_PAGES)
                             and (href not in ("/projects", "/access") or A.is_admin(user))]
                    if not items:
                        continue
                    if group_name:
                        ui.label(group_name).classes("sr-nav-group")
                    for label, href, icon in items:
                        with ui.link(target=href).classes("active" if label == active else ""):
                            ui.icon(icon, size="19px")
                            ui.label(label).classes("sr-mini-hide")
                            if mini:
                                ui.tooltip(label).props("anchor='center right' self='center left'")
            ui.space()

            @ui.refreshable
            def budget_card():
                with P.connect() as c:
                    st = R.budget_status(c, P.site, P.cfg.rank, K.latest_date(c, P.site))
                warn = st["ratio"] >= R.ALERT_RATIO
                with ui.element("div").classes("sr-card q-pa-sm q-mt-lg w-full sr-mini-hide"):
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

            if A.can_edit(user):  # chi phí check rank là thông tin nội bộ
                budget_card()
            with ui.row().classes("items-center gap-2 q-mt-sm q-px-sm no-wrap").style("flex-shrink:0"):
                ui.avatar(user[:1].upper(), color="green-1", text_color="green-10", size="28px", font_size="13px")
                with ui.column().classes("gap-0 sr-mini-hide").style("min-width:0"):
                    ui.label(user).classes("text-sm ellipsis").tooltip(str(user))
                    if user.role != A.LOCAL:
                        ui.label("Quản trị" if A.is_admin(user) else A.PROJECT_ROLES.get(user.role, "")).classes(
                            "text-xs muted")
                if user.via == "password":
                    def logout():
                        app.storage.user.pop("auth", None)
                        ui.navigate.to("/login")
                    with ui.button(icon="more_vert").props("flat round dense size=sm color=grey-8").classes(
                            "sr-mini-hide"):
                        with ui.menu():
                            ui.menu_item("Đổi mật khẩu", on_click=lambda: ui.navigate.to("/doi-mat-khau"))
                            ui.menu_item("Đăng xuất", on_click=logout)

        def toggle_nav():
            app.storage.user["nav_mini"] = not app.storage.user.get("nav_mini")
            if app.storage.user["nav_mini"]:
                drawer.props("mini")
            else:
                drawer.props(remove="mini")

        # Thanh trên gọn, tự ẩn khi cuộn xuống và hiện lại khi cuộn lên (reveal).
        with ui.header().props("reveal reveal-offset=120").classes("sr-top q-px-md q-py-xs items-center gap-2"):
            async def on_menu(e):
                if await ui.run_javascript("window.innerWidth") < 1024:  # màn hẹp: mở / đóng menu đè lên trang
                    drawer.toggle()
                    return
                toggle_nav()
                e.sender.props(f"icon={'menu' if app.storage.user['nav_mini'] else 'menu_open'}")

            ui.button(icon="menu_open" if not mini else "menu", on_click=on_menu).props(
                "flat round dense color=grey-8").tooltip("Thu gọn / mở rộng menu")
            if len(P.projects) > 1:  # nhiều website: chọn dự án, mở lại đúng màn đang xem của dự án kia
                href = next((h for _, items in NAV for label, h, _ in items if label == active), "/")

                def switch(e):
                    app.storage.user["project"] = e.value
                    ui.navigate.to(href)

                ui.select({p["slug"]: p["name"] for p in P.projects}, value=P.project["slug"], on_change=switch).props(
                    "dense outlined options-dense").classes("w-56").tooltip("Đổi website")
            else:
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.icon("language", size="15px").classes("muted")
                    ui.label(PJ.domain(P.site)).classes("text-sm font-medium")
            ui.space()
            if ctx and (period or group):
                def pick(key, value):
                    app.storage.user[group_key(P) if key == "group" else key] = value
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
                if group and not A.is_client(user):  # nhóm URL là khái niệm nội bộ, khách hàng không cần
                    ui.select(ctx["groups"], value=ctx["group"], on_change=lambda e: pick("group", e.value)).props(
                        "dense outlined options-dense").classes("w-44")
            def set_preview(mode):
                app.storage.user["as_viewer"] = mode
                ui.navigate.to(href if mode != A.CLIENT or href.split("?")[0] in A.CLIENT_PAGES else "/")

            href = next((h for _, items in NAV for label, h, _ in items if label == active), "/")
            if user.preview:
                T.status_chip(ui, "Đang xem thử: " + A.PROJECT_ROLES[user.role].lower(), "amber", "visibility")
                ui.button("Thoát xem thử", icon="close", on_click=lambda: set_preview(False)).props(
                    "flat dense no-caps color=grey-9")
            elif not A.can_edit(user):
                T.status_chip(ui, A.PROJECT_ROLES.get(user.role, "Chỉ xem"), "grey", "visibility")
            elif user.role == A.LOCAL:  # chỉ trên máy chạy tool: xem trước giao diện người khác sẽ thấy
                with ui.button("Xem thử", icon="visibility").props("flat dense no-caps color=grey-8").tooltip(
                        "Xem đúng giao diện người khác thấy khi vào từ máy khác"):
                    with ui.menu():
                        ui.menu_item("Như người chỉ xem (ví dụ quản lý)", on_click=lambda: set_preview(A.VIEWER))
                        ui.menu_item("Như khách hàng (chỉ báo cáo)", on_click=lambda: set_preview(A.CLIENT))
            if ctx:
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.icon("schedule", size="16px").classes("muted")
                    ui.label(f"GSC đến {ctx['end']:%d/%m}").classes("text-xs muted")
        return budget_card

    @ui.page("/")
    def overview_page(request: Request):
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        ctx = page_ctx(P)
        shell("Tổng quan", user, P, ctx)
        build_overview_page(ui, P.cfg, P.connect, user, ctx)

    @ui.page("/ai")
    def ai_page(request: Request):
        params = dict(request.query_params)
        if not (opened := open_page(request, edit=params.get("tab") == "chat-luong")):
            return
        user, P = opened
        ctx = page_ctx(P)
        shell("Chất lượng dữ liệu" if params.get("tab") == "chat-luong" else "AI Search & GEO", user, P, ctx,
              group=False)
        build_ai_page(ui, P.cfg, P.connect, user, params, week=ctx["weeks"][ctx["week"]])

    @ui.page("/report")
    def report_page(request: Request):
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        kind = "month" if request.query_params.get("kind") == "month" else "week"
        ctx = page_ctx(P)
        shell("Báo cáo tháng" if kind == "month" else "Báo cáo tuần", user, P, ctx, period=kind, group=False)
        build_report_page(ui, P.cfg, P.connect, user, ctx, kind)

    @ui.page("/url")
    def url_page(request: Request):
        if not (opened := open_page(request)):
            return
        user, P = opened
        ctx = page_ctx(P)
        budget_card = shell("Hiệu suất URL", user, P, ctx)
        build_url_page(ui, P.cfg, P.connect, user, on_budget_change=budget_card.refresh, ctx=ctx)

    @ui.page("/okr")
    def okr_page(request: Request):
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        ctx = page_ctx(P)
        shell("Công việc & OKR", user, P, ctx, group=False)
        build_okr_page(ui, P.cfg, P.connect, user, ctx)

    @ui.page("/kpi")
    def kpi_page(request: Request):
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        shell("KPI cam kết", user, P, page_ctx(P), period=False, group=False)
        build_kpi_page(ui, P.cfg, P.connect, user)

    @ui.page("/login")
    def login_page(request: Request, next: str = "/"):
        from .web_login import build_login_page, safe_next
        host = request.client.host if request.client else None
        if A.is_local(host, request.headers):  # trên máy chạy tool không cần đăng nhập
            ui.navigate.to(safe_next(next))
            return
        ui.colors(primary=T.INK, secondary=T.LIME, positive=PRIMARY, negative=T.RED, warning=T.AMBER)
        build_login_page(ui, base, app_connect, next)

    @ui.page("/doi-mat-khau")
    def change_password_page(request: Request):
        from .web_login import build_change_password_page
        if not (user := gate(request, allow_must_change=True)):
            return
        if user.via != "password":  # chủ máy / đăng nhập qua Cloudflare, Tailscale: không có mật khẩu trong tool
            ui.navigate.to("/")
            return
        ui.colors(primary=T.INK, secondary=T.LIME, positive=PRIMARY, negative=T.RED, warning=T.AMBER)
        build_change_password_page(ui, base, app_connect, user)

    @ui.page("/access")
    def access_page(request: Request):
        if not (opened := open_page(request, admin=True)):
            return
        user, P = opened
        shell("Phân quyền", user, P, page_ctx(P), period=False, group=False)
        build_access_page(ui, base, app_connect, user, P.project["slug"])

    @ui.page("/projects")
    def projects_page(request: Request):
        from .web_projects import build_projects_page
        if not (opened := open_page(request, admin=True)):
            return
        user, P = opened
        shell("Dự án", user, P, page_ctx(P), period=False, group=False)
        build_projects_page(ui, base, app_connect, user)

    @ui.page("/index")
    def index_page(request: Request):
        if not (opened := open_page(request)):
            return
        user, P = opened
        shell("Index", user, P, page_ctx(P), period=False, group=False)
        build_index_page(ui, P.cfg, P.connect, user)

    @ui.page("/rank")
    def rank_page(request: Request):
        if not (opened := open_page(request)):
            return
        user, P = opened
        budget_card = shell("Từ khóa & rank", user, P, page_ctx(P), period=False, group=False)
        build_rank_page(ui, P.cfg, P.connect, user, on_budget_change=budget_card.refresh)

    @ui.page("/stars")
    def stars_page():
        ui.navigate.to("/rank")

    def url_col(site, name="url", label="URL"):
        """Cột URL chỉ hiện đường dẫn (bỏ tên miền), cắt "…" khi dài."""
        col = _col(name, label)
        col[":format"] = f"val => (val || '').replace('{site.rstrip('/')}', '') || '/'"
        col.update({"classes": "ellipsis", "style": "max-width: 420px", "headerStyle": "max-width: 420px"})
        return col

    @ui.page("/urls")
    def urls_page(request: Request):
        if not (opened := open_page(request, edit=True)):
            return
        user, P = opened
        site, connect = P.site, P.connect
        shell("Quản lý URL", user, P, page_ctx(P), period=False, group=False)
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
                    columns=[url_col(site), _col("type", "Loại"), _col("clicks", "Click 90 ngày", number=True),
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
                paste = ui.textarea(placeholder=f"https://{PJ.domain(site)}/danh-muc/\n{PJ.domain(site)}/bai-viet").props(
                    "outlined autogrow").classes("w-full")
                ui.button("Thêm vào nhóm", icon="playlist_add", on_click=lambda: add_pasted())
                add_result = ui.column().classes("w-full")

            with ui.tab_panel(t_suggest):
                ui.label("URL nhiều click nhất 90 ngày qua chưa có trong nhóm (đã bỏ URL cũ/kỹ thuật).").classes("muted")
                suggest_type = ui.select(["Tất cả"] + U.TYPES, value="Tất cả", label="Loại",
                                         on_change=lambda: refresh()).classes("w-56")
                suggest = ui.table(
                    columns=[url_col(site), _col("type", "Loại"), _col("clicks", "Click 90 ngày", number=True),
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
                    columns=[url_col(site), _col("type", "Loại"), _col("source", "Nguồn phân loại"),
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
                             url_col(site), _col("detail", "Chi tiết")],
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
           storage_secret=_storage_secret(base), favicon=assets / "favicon.png")
