"""Giao diện web (NiceGUI): khung chung (menu nhóm, thanh trên có tuần + nhóm URL dùng chung) và các trang."""
import getpass
from contextlib import closing
from types import SimpleNamespace

from . import access as A
from . import live as LIVE
from . import db
from . import urls as U
from .config import Config
from . import keywords as K
from . import presence as PR
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
from .web_url import build_url_page

PRIMARY = T.GREEN
ADMIN_PAGES = ("/projects", "/access", "/budget", "/cai-dat")  # chỉ quản trị thấy trong menu
NUMBER = "val => val.toLocaleString('vi-VN')"
# Menu chia nhóm: (tên nhóm hoặc None, [(nhãn, đường dẫn, icon)])
NAV = [
    (None, [("Tổng quan", "/", "space_dashboard"), ("Báo cáo", "/report", "summarize"),
            ("KPI cam kết", "/kpi", "flag"), ("Công việc & OKR", "/okr", "task_alt")]),
    ("SEO", [("Hiệu suất URL", "/url", "link"), ("Từ khóa & rank", "/rank", "leaderboard"),
             ("Index", "/index", "travel_explore"), ("Quản lý URL", "/urls", "folder_open")]),
    ("AI & GEO", [("AI Search & GEO", "/ai", "auto_awesome"),
                  ("Chất lượng dữ liệu", "/ai?tab=chat-luong", "verified")]),
    ("Quản trị", [("Dự án", "/projects", "domain"), ("Ngân sách check rank", "/budget", "account_balance_wallet"),
                  ("Phân quyền", "/access", "admin_panel_settings"),
                  ("Cài đặt tích hợp", "/cai-dat", "settings")]),  # chỉ Chủ tool
]
EDIT_PAGES = ("/urls", "/ai?tab=chat-luong")  # màn làm việc cần quyền sửa: người chỉ xem không thấy trên menu


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
    app.add_static_files("/assets", assets)  # biểu tượng của tool (logo từng website lưu trong bảng dự án)

    base = cfg  # cấu hình chung (config.toml); số liệu theo dự án lấy qua project_scope()
    # Người ngồi ở máy chạy tool là Chủ tool: dùng email Chủ tool (config.toml) để nhật ký / avatar chỉ có một tên
    owners = [e.strip().lower() for e in base.access.editors if e.strip()]
    local_name = owners[0] if owners else getpass.getuser()
    with closing(db.connect(base.db_path)) as c:
        PJ.ensure(c, base)
        first_slug = PJ.list_projects(c)[0]["slug"]
        A.migrate_members(c, base.access, first_slug)
        A.adopt_config(c, base.access, first_slug)  # email viewers trong config.toml → quản lý trên màn Phân quyền

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
                               connect=lambda: closing(db.connect(pc.db_path)), user=A.in_project(acct, role),
                               roles={p["slug"]: r for p, r in allowed})

    def track_presence(acct) -> None:
        """Chấm trạng thái: trang này đang mở; trình duyệt báo khi có thao tác (tối đa mỗi phút một lần); trang đóng
        hẳn thì bỏ, người không còn trang nào mở thì ghi lúc rời đi."""
        client = ui.context.client
        who = str(acct)
        PR.connect(who, client.id)

        def gone():
            if PR.leave(who, client.id) and getattr(acct, "via", "") == "password":
                with app_connect() as c:
                    A.mark_seen(c, who)
        client.on_delete(gone)
        ui.on("sr_active", lambda: PR.active(who))
        ui.add_body_html("""<script>(() => { let last = 0;
          const ping = () => { const n = Date.now(); if (n - last > 60000) { last = n; try { emitEvent('sr_active'); }
            catch (e) {} } };
          ['pointermove', 'keydown', 'click', 'scroll', 'touchstart'].forEach(t =>
            window.addEventListener(t, ping, {passive: true, capture: true})); })();</script>""")

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
        track_presence(acct)
        LIVE.register(ui.context.client, str(acct), P.project["slug"])  # đổi quyền / tạm ngưng: ngắt trang này
        return P.user, P

    def gate(request: Request) -> "A.User | None":
        """Người đang mở trang: chủ máy (mở thẳng trên máy này), người đã đăng nhập bằng mật khẩu, hoặc email đã được
        Cloudflare Access / Tailscale xác minh. Chưa đăng nhập thì chuyển sang /login. Trả về None khi trang không
        được hiện."""
        with app_connect() as c:  # danh sách trong config.toml + danh sách trên màn Phân quyền
            settings = A.effective(c, base.access)
            host = request.client.host if request.client else None
            who, why = A.identify(request.headers, settings, local_name, host)
            if who is None and not why:
                who = A.from_session(c, settings, app.storage.user.get("auth"))
        app.storage.user.pop("as_viewer", None)  # chế độ xem thử đã bỏ: xóa lựa chọn cũ còn lưu trên trình duyệt
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
        return who  # mật khẩu được cấp vẫn dùng tiếp được: đổi mật khẩu là tùy chọn (gợi ý sau lần đăng nhập)

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
                "end": end, "kind": "month" if store.get("report_kind") == "month" else "week",
                "compare": store.get("report_compare") or "prev"}

    def people_group(user, P) -> None:
        """Nhóm avatar trên thanh trên cùng: mọi người vào được website đang mở (trừ chính mình), người đang online
        xếp trước, rồi theo thứ tự cố định quản trị → được sửa → chỉ xem → khách hàng → email. Bấm mở danh sách đầy đủ.
        Tự cập nhật trạng thái mỗi 30 giây."""
        role_label = {"admin": "Chủ tool", **A.PROJECT_ROLES}
        rank = {PR.AVAILABLE: 0, PR.AWAY: 1, PR.OFFLINE: 2}

        @ui.refreshable
        def render():
            with app_connect() as c:
                first = PJ.list_projects(c)[0]["slug"]
                people = A.people_in_project(c, base.access, P.project["slug"], first)
                seen = {u["email"]: u.get("last_seen") for u in A.users(c, base.access)}
                profs = A.profiles(c)
            me = str(user).strip().lower()
            rows = []
            for p in people:
                if p["email"] == me:
                    continue
                st, st_text = PR.describe(p["email"], seen.get(p["email"]))
                who = role_label[p["role"]] + (f" · {p['title']}" if p.get("title") else "")
                pf = profs.get(p["email"], {})
                name = A.display_name(pf, p["email"])
                rows.append({"name": name, "email": p["email"], "photo": pf.get("avatar", ""), "status": st,
                             "status_text": st_text, "who": who, "text": f"{name} · {who} · {st_text}"})
            rows.sort(key=lambda r: rank[r["status"]])  # sắp xếp ổn định: giữ thứ tự quyền / email trong từng nhóm
            if not rows:
                return
            online = sum(r["status"] != PR.OFFLINE for r in rows)
            box = T.avatar_group(ui, rows, max_shown=4, size=28, ring="#F4F4EF",
                                 label=f"{len(rows)} người có quyền ở {P.project['name']}, {online} đang online. "
                                       "Bấm để xem danh sách")
            with box:
                with ui.menu().props('anchor="bottom right" self="top right" :offset="[0, 8]"').classes(
                        "sr-account-menu").style("width: 320px") as menu:
                    with ui.column().classes("gap-0 q-px-md q-pt-md q-pb-xs"):
                        ui.label(f"Người có quyền ở {P.project['name']}").classes("text-sm font-semibold")
                        ui.label(f"{len(rows)} người · {online} đang online").classes("text-xs muted")
                    with ui.column().classes("gap-0 w-full").style("max-height: 340px; overflow-y: auto"):
                        for r in rows:
                            with ui.row().classes("items-center gap-3 no-wrap q-px-md").style("padding-top:6px;"
                                                                                               "padding-bottom:6px"):
                                T.presence_avatar(ui, r["name"], r["status"], r["status_text"], size=30,
                                                  colors=T.avatar_color(r["email"]), photo=r["photo"])
                                with ui.column().classes("gap-0 col").style("min-width:0"):
                                    ui.label(r["name"]).classes("text-sm ellipsis").props["title"] = r["email"]
                                    ui.label(f"{r['who']} · {r['status_text']}").classes("text-xs muted ellipsis")
                    if A.is_admin(user):
                        ui.separator()
                        with ui.menu_item(on_click=lambda: ui.navigate.to(f"/access?project={P.project['slug']}")
                                          ).classes("items-center gap-3"):
                            ui.icon("manage_accounts", size="18px").classes("muted")
                            ui.label("Quản lý quyền ở website này").classes("text-sm")
            box.on("keydown.enter", menu.open)

        render()
        ui.timer(30, render.refresh)

    def account_menu(user, P, active: str) -> None:
        """Góc dưới menu trái: avatar + tên + trạng thái; bấm vào mở menu tài khoản (thông tin, website của tôi, đổi
        mật khẩu / đăng xuất, lối tắt quản trị)."""
        st, st_text = PR.describe(user)
        with app_connect() as c:
            prof = A.profiles(c).get(str(user), {})
        name, photo = A.display_name(prof, user), prof.get("avatar", "")
        href = next((h for _, items in NAV for label, h, _ in items if label == active), "/")
        role_text = ("Chủ tool · trên máy chạy tool" if user.role == A.LOCAL else
                     "Chủ tool · toàn quyền" if A.is_admin(user) else A.PROJECT_ROLES.get(user.role, ""))

        def go_project(slug: str) -> None:
            app.storage.user["project"] = slug
            ui.navigate.to(href)

        def logout():
            app.storage.user.pop("auth", None)
            ui.navigate.to("/login")

        from .web_profile import profile_dialog
        open_profile = profile_dialog(ui, base, app_connect, user)
        full = user.role == A.LOCAL or A.is_admin(user)  # toàn quyền mọi website: không ghi quyền từng dòng

        with ui.row().classes("sr-account w-full items-center gap-2 q-mt-sm no-wrap").props(
                'tabindex=0 role=button aria-haspopup=menu aria-label="Tài khoản và cài đặt"').style(
                "flex-shrink:0; min-width:0") as acc_row:  # w-full: email dài thì cắt "…" thay vì tràn khỏi menu
            T.presence_avatar(ui, name, st, st_text, size=28, ring=T.CREAM, colors=T.avatar_color(str(user)),
                              photo=photo)
            with ui.column().classes("gap-0 sr-mini-hide col items-stretch").style("min-width:0"):
                ui.label(name).classes("text-sm ellipsis").props["title"] = str(user)
                ui.label(" · ".join(x for x in (role_text.split(" · ")[0] if user.role != A.LOCAL else "", st_text)
                                    if x)).classes("text-xs muted ellipsis")
            ui.icon("unfold_more", size="18px").classes("muted sr-mini-hide")
            with ui.menu().props('anchor="top left" self="bottom left" :offset="[0, 8]"').classes(
                    "sr-account-menu").style("width: 300px") as acc_menu:
                with ui.row().classes("items-center gap-3 no-wrap sr-acct-head"):
                    T.presence_avatar(ui, name, st, st_text, size=40, colors=T.avatar_color(str(user)), photo=photo)
                    with ui.column().classes("gap-0 col").style("min-width:0"):
                        ui.label(name).classes("text-sm font-semibold ellipsis")
                        if name != str(user):
                            ui.label(str(user)).classes("text-xs muted ellipsis")
                        with ui.row().classes("items-center gap-1").style("row-gap:0"):  # dài thì xuống dòng
                            ui.label(role_text).classes("text-xs muted")
                            ui.label("·").classes("text-xs muted")
                            ui.label(st_text).classes("text-xs").style(
                                f"color:{T.GREEN if st == PR.AVAILABLE else T.MUTED}; white-space:nowrap")
                ui.separator()
                ui.label(f"Website của tôi · {len(P.projects)}").classes("sr-nav-group sr-acct-group")
                with ui.column().classes("gap-0 w-full").style("max-height: 260px; overflow-y: auto"):
                    for p in P.projects:
                        cur = p["slug"] == P.project["slug"]
                        with ui.menu_item(on_click=lambda _, s_=p["slug"]: go_project(s_)).classes(
                                "items-center gap-3 no-wrap" + (" sr-current" if cur else "")):
                            T.project_icon(ui, p, 26)
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                ui.label(p["name"]).classes("text-sm ellipsis" + (" font-semibold" if cur else ""))
                                if not full:
                                    r = P.roles.get(p["slug"], "")
                                    ui.label(A.PROJECT_ROLES.get(r, "")).classes("text-xs muted")
                            if cur:
                                ui.icon("check", size="16px").style(f"color:{T.GREEN}")
                if A.is_admin(user):
                    ui.separator()
                    for label, to, icon in (("Phân quyền", "/access", "admin_panel_settings"),
                                            ("Dự án", "/projects", "domain"),
                                            ("Ngân sách check rank", "/budget", "account_balance_wallet"),
                                            ("Cài đặt tích hợp", "/cai-dat", "settings")):
                        with ui.menu_item(on_click=lambda _, t=to: ui.navigate.to(t)).classes("items-center gap-3"):
                            ui.icon(icon, size="18px").classes("muted")
                            ui.label(label).classes("text-sm")
                ui.separator()
                with ui.menu_item(on_click=open_profile).classes("items-center gap-3"):
                    ui.icon("account_circle", size="18px").classes("muted")
                    ui.label("Hồ sơ của tôi").classes("text-sm")
                if user.via == "password":
                    with ui.menu_item(on_click=logout).classes("items-center gap-3"):
                        ui.icon("logout", size="18px").style(f"color:{T.RED}")
                        ui.label("Đăng xuất").classes("text-sm").style(f"color:{T.RED}")
        acc_row.on("keydown.enter", acc_menu.open)

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
            # Logo + tên website của dự án đang mở (menu thu gọn: chỉ logo)
            with ui.row().classes("items-center gap-2 no-wrap q-px-sm sr-mini-hide").style("min-width:0"):
                T.project_icon(ui, P.project, 36)
                with ui.column().classes("gap-0").style("min-width:0"):
                    ui.label(P.project["name"]).classes("sr-section-title ellipsis").style("max-width: 160px")
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon("insights", size="13px").style(f"color:{T.GREEN}")
                        ui.label("SEO Report").classes("text-xs font-semibold muted").style("letter-spacing: .04em")
            with ui.element("div").classes("sr-mini-only w-full"):
                T.project_icon(ui, P.project, 36).classes("q-mx-auto")
            with ui.column().classes("sr-nav w-full gap-0 q-mt-sm"):
                for group_name, items in NAV:
                    items = [(label, href, icon) for label, href, icon in items
                             if (not A.is_client(user) or href.split("?")[0] in A.CLIENT_PAGES)
                             and (href not in ADMIN_PAGES or A.is_admin(user))
                             and (href not in EDIT_PAGES or A.can_edit(user))]
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
                from datetime import date

                from .web_budget import projected  # cùng cách tính với màn Ngân sách: đã dùng + lịch còn lại
                st["estimate"] = projected(st["spent"], st["estimate"], date.today(), P.cfg.rank.paused)
                st["ratio"] = st["estimate"] / st["budget"] if st["budget"] else 0
                warn = st["ratio"] >= R.ALERT_RATIO
                card = ui.element("div").classes("sr-card q-pa-sm q-mt-lg w-full sr-mini-hide")
                if A.is_admin(user):  # quản trị: bấm mở màn Ngân sách check rank (mọi website)
                    card.classes("cursor-pointer").on("click", lambda: ui.navigate.to("/budget"))
                    card.tooltip("Xem ngân sách check rank của mọi website")
                with card:
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon("account_balance_wallet", size="16px").classes("muted")
                        ui.label("Ngân sách check rank").classes("text-xs muted")
                    ui.label(f"Dự kiến {R.usd(st['estimate'])} / {st['budget']:.0f} USD").classes(
                        "text-sm font-semibold num")
                    ui.linear_progress(min(st["ratio"], 1), show_value=False, size="6px",
                                       color="orange-8" if warn else "primary").classes("rounded-borders")
                    ui.label(f"{st['stars']} keyword · đã dùng {R.usd(st['spent'])} USD tháng này").classes(
                        "text-xs muted")
                    if warn:
                        ui.label("Dự kiến vượt 80% ngân sách").classes("text-xs text-orange-9")

            if A.can_edit(user):  # chi phí check rank là thông tin nội bộ
                budget_card()
            account_menu(user, P, active)

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

                def switch(slug):
                    app.storage.user["project"] = slug
                    ui.navigate.to(href)

                with ui.row().classes("sr-proj-switch items-center gap-2 no-wrap"):
                    T.project_icon(ui, P.project, 24)
                    ui.label(P.project["name"]).classes("text-sm font-medium ellipsis")
                    ui.icon("expand_more", size="18px").classes("muted")
                    with ui.menu().props("auto-close"):
                        for p in P.projects:
                            with ui.menu_item(on_click=lambda _, s_=p["slug"]: switch(s_)).classes(
                                    "items-center gap-2" + (" text-weight-bold" if p["slug"] == P.project["slug"]
                                                            else "")):
                                T.project_icon(ui, p, 24)
                                with ui.column().classes("gap-0"):
                                    ui.label(p["name"]).classes("text-sm")
                                    ui.label(PJ.domain(p["site_url"])).classes("text-xs muted")
                                if p["slug"] == P.project["slug"]:
                                    ui.space()
                                    ui.icon("check", size="16px").style(f"color:{T.GREEN}")
            else:
                with ui.row().classes("items-center gap-2 no-wrap"):
                    T.project_icon(ui, P.project, 22)
                    ui.label(PJ.domain(P.site)).classes("text-sm font-medium")
            ui.space()
            if ctx and (period or group):
                def pick(key, value):
                    app.storage.user[group_key(P) if key == "group" else key] = value
                    ui.navigate.reload()

                if period == "days":  # Tổng quan: 7 / 28 / 90 ngày gần nhất
                    def pick_days(e):
                        app.storage.user["dash_days"] = e.value
                        ui.navigate.reload()
                    cur_days = app.storage.user.get("dash_days") if app.storage.user.get("dash_days") in (7, 28, 90)                         else 28
                    ui.toggle({7: "7 ngày", 28: "28 ngày", 90: "90 ngày"}, value=cur_days, on_change=pick_days).props(
                        "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"
                    ).classes("sr-seg")
                elif period == "report":  # màn Báo cáo: Tuần | Tháng, kỳ báo cáo, kỳ so sánh
                    def pick_kind(e):
                        app.storage.user["report_kind"] = e.value
                        app.storage.user["report_compare"] = "prev"  # kỳ tự chọn của tuần không dùng cho tháng
                        ui.navigate.reload()

                    def pick_period(e):
                        app.storage.user["week" if ctx["kind"] == "week" else "month"] = e.value
                        app.storage.user["report_compare"] = (app.storage.user.get("report_compare")
                                                              if app.storage.user.get("report_compare") in ("prev", "yoy")
                                                              else "prev")
                        ui.navigate.reload()

                    ui.toggle({"week": "Tuần", "month": "Tháng"}, value=ctx["kind"], on_change=pick_kind).props(
                        "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"
                    ).classes("sr-seg")
                    if ctx["kind"] == "month":
                        periods, idx = ctx["months"], ctx["month"]
                        fmt = lambda p_: f"Tháng {p_[0]:%m/%Y}"  # noqa: E731
                    else:
                        periods, idx = ctx["weeks"], ctx["week"]
                        fmt = lambda p_: f"Tuần {p_[0]:%d/%m} – {p_[1]:%d/%m/%Y}"  # noqa: E731
                    ui.select({p_[0].isoformat(): fmt(p_) for p_ in periods}, value=periods[idx][0].isoformat(),
                              on_change=pick_period).props("dense outlined options-dense").classes("w-56")
                    options = {"prev": "So với kỳ trước", "yoy": "So với cùng kỳ năm trước"}
                    options.update({p_[0].isoformat(): "So với " + fmt(p_).lower() for p_ in periods[idx + 2:]})
                    cmp_value = ctx["compare"] if ctx["compare"] in options else "prev"

                    def pick_compare(e):
                        app.storage.user["report_compare"] = e.value
                        ui.navigate.reload()
                    ui.select(options, value=cmp_value, on_change=pick_compare).props(
                        "dense outlined options-dense").classes("w-64").tooltip("Kỳ so sánh")
                elif period == "month":
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
            if not A.is_client(user):  # khách hàng không thấy ai khác có quyền (tránh lộ email team / khách khác)
                people_group(user, P)
            if not A.can_edit(user):
                T.status_chip(ui, A.PROJECT_ROLES.get(user.role, "Team xem"), "grey", "visibility")
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
        from .web_dashboard import WINDOWS, build_dashboard_page
        ctx = page_ctx(P)
        days = app.storage.user.get("dash_days") if app.storage.user.get("dash_days") in WINDOWS else 28
        shell("Tổng quan", user, P, ctx, period="days", group=False)
        build_dashboard_page(ui, P.cfg, P.connect, user, ctx, days)

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
        if request.query_params.get("kind") in ("week", "month"):  # link cũ /report?kind=month vẫn mở đúng
            app.storage.user["report_kind"] = request.query_params["kind"]
        ctx = page_ctx(P)
        shell("Báo cáo", user, P, ctx, period="report", group=False)
        build_report_page(ui, P.cfg, P.connect, user, ctx, ctx["kind"])

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
        build_kpi_page(ui, P.cfg, P.connect, user, app_connect, P.project)

    @ui.page("/kpi/sua")
    def kpi_edit_page(request: Request):
        if not (opened := open_page(request, edit=True)):
            return
        user, P = opened
        from .web_kpi import build_kpi_edit_page
        shell("KPI cam kết", user, P, page_ctx(P), period=False, group=False)
        build_kpi_edit_page(ui, P.cfg, P.connect, user)

    @ui.page("/login")
    def login_page(request: Request, next: str = "/"):
        from .web_login import build_login_page, safe_next
        host = request.client.host if request.client else None
        if A.is_local(host, request.headers):  # trên máy chạy tool không cần đăng nhập
            ui.navigate.to(safe_next(next))
            return
        ui.colors(primary=T.INK, secondary=T.LIME, positive=PRIMARY, negative=T.RED, warning=T.AMBER)
        build_login_page(ui, base, app_connect, next, A.client_ip(host, request.headers))

    @ui.page("/doi-mat-khau")
    def change_password_page(request: Request, next: str = "/"):
        from .web_login import build_change_password_page
        if not (user := gate(request)):
            return
        if user.via != "password":  # chủ máy / đăng nhập qua Cloudflare, Tailscale: không có mật khẩu trong tool
            ui.navigate.to("/")
            return
        ui.colors(primary=T.INK, secondary=T.LIME, positive=PRIMARY, negative=T.RED, warning=T.AMBER)
        build_change_password_page(ui, base, app_connect, user, next)

    @ui.page("/access")
    def access_page(request: Request):
        if not (opened := open_page(request, admin=True)):
            return
        user, P = opened
        shell("Phân quyền", user, P, page_ctx(P), period=False, group=False)
        build_access_page(ui, base, app_connect, user, P.project["slug"], request.query_params.get("project"))

    @ui.page("/tai-khoan")
    def profile_page(request: Request):
        from .web_profile import build_profile_page
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        shell("Hồ sơ của tôi", user, P, page_ctx(P), period=False, group=False)
        build_profile_page(ui, base, app_connect, user)

    @ui.page("/budget")
    def budget_page(request: Request):
        from .web_budget import build_budget_page
        if not (opened := open_page(request, admin=True)):
            return
        user, P = opened
        shell("Ngân sách check rank", user, P, page_ctx(P), period=False, group=False)
        build_budget_page(ui, base, app_connect, user)

    @ui.page("/projects")
    def projects_page(request: Request):
        from .web_projects import build_projects_page
        if not (opened := open_page(request, admin=True)):
            return
        user, P = opened
        shell("Dự án", user, P, page_ctx(P), period=False, group=False)
        build_projects_page(ui, base, app_connect, user)

    @ui.page("/cai-dat")
    def settings_page(request: Request):
        from .web_settings import build_settings_page
        if not (opened := open_page(request, admin=True)):
            return
        user, P = opened
        shell("Cài đặt tích hợp", user, P, page_ctx(P), period=False, group=False)
        local = A.is_local(request.client.host if request.client else None, request.headers)
        build_settings_page(ui, base, app_connect, user, base.config_path, local,
                            google_origin=f"http://{request.headers.get('host')}" if local else None,
                            google_notice=request.query_params.get("google"))

    @app.get("/oauth/google")
    def google_callback(request: Request):
        """Google gọi về sau khi Chủ tool đồng ý cấp quyền (nút Kết nối Google ở màn Dự án). Chỉ nhận trên máy chạy
        tool; mã state phải khớp phiên vừa tạo (auth.web_login_finish kiểm tra)."""
        from fastapi.responses import RedirectResponse

        from . import auth
        if not A.is_local(request.client.host if request.client else None, request.headers):
            return RedirectResponse("/cai-dat", status_code=303)
        q = request.query_params
        if q.get("error"):
            result = "cancel" if q["error"] == "access_denied" else "fail"
        else:
            try:
                creds = auth.web_login_finish(base, q.get("state", ""), str(request.url))
                miss = auth.missing_scopes(creds.scopes or [], auth.SCOPES)
                result = "missing" if miss else "ok"
                with app_connect() as c:  # email hiện ở màn Dự án: đọc lại theo tài khoản mới
                    c.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                    c.execute("DELETE FROM app_settings WHERE key = 'tool_google_email'")
                    c.commit()
            except Exception as e:  # noqa: BLE001
                print(f"Kết nối Google không thành công: {e}")
                result = "expired" if isinstance(e, ValueError) else "fail"
        # chỉ mã ngắn, không đưa chữ từ đường dẫn lên trang
        return RedirectResponse(f"/cai-dat?google={result}", status_code=303)

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
        bo = request.query_params.get("bo", "")  # bộ (tab) đang mở
        build_rank_page(ui, P.cfg, P.connect, user, on_budget_change=budget_card.refresh,
                        set_id=int(bo) if bo.isdigit() else None)

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
            t_target = ui.tab("URL mục tiêu của từ khóa")
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

            with ui.tab_panel(t_target):
                from .web_targets import build_target_panel
                build_target_panel(ui, P.cfg, connect, user, site)

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
                T.page_header(ui, "folder_open", "Quản lý URL", f"{total:,}".replace(",", ".") + " URL có dữ liệu GSC, chia theo loại trang",
                              tone="grey")
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
           storage_secret=_storage_secret(base), favicon=assets / "app-icon.svg")
