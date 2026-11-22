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
ADMIN_PAGES = ("/projects", "/access", "/budget", "/cai-dat")  # chỉ Owner / Admin thấy trong menu
OWNER_PAGES = ("/cai-dat", "/quan-tri-ai")  # chỉ Owner
NUMBER = "val => val.toLocaleString('vi-VN')"
# Menu chia nhóm: (tên nhóm hoặc None, [(nhãn, đường dẫn, icon)])
NAV = [
    (None, [("Tổng quan", "/", "space_dashboard"), ("Báo cáo", "/report", "summarize")]),
    ("Kế hoạch", [("KPI cam kết", "/kpi", "flag"), ("Công việc & OKR", "/okr", "task_alt"),
                  ("Yêu cầu hỗ trợ", "/ho-tro", "support_agent"), ("Yêu cầu của tôi", "/yeu-cau", "support_agent")]),
    ("Từ khóa", [("Thứ hạng từ khóa", "/rank", "leaderboard"), ("Keyword Research", "/tu-khoa", "manage_search"),
                 ("Đối thủ", "/doi-thu", "groups"), ("SEO Opportunities", "/co-hoi", "insights")]),
    ("Website", [("URL & Index", "/url", "link"), ("Technical Audit", "/audit", "fact_check"),
                 ("Tốc độ trang", "/toc-do", "speed"),
                 ("Backlink", "/backlink", "add_link")]),
    ("AI & GEO", [("AI Search & GEO", "/ai", "auto_awesome"), ("AI Overview", "/aio", "tips_and_updates")]),
    ("Kênh khác", [("Local SEO", "/local", "storefront"), ("Merchant Center", "/merchant", "shopping_bag")]),
    # Quản trị: một mục, tab con là 4 màn (chỉ Owner / Admin; Cài đặt tích hợp chỉ Owner)
    (None, [("Quản trị", "/projects", "admin_panel_settings")]),
]
ADMIN_TABS = (("Dự án", "/projects"), ("Ngân sách & chi phí", "/budget"), ("Phân quyền", "/access"),
              ("Cài đặt tích hợp", "/cai-dat"), ("AI", "/quan-tri-ai"))
# Mục "URL & Index" (dữ liệu GSC theo URL): một mục trên menu, ba tab = ba màn (link cũ vẫn mở đúng tab)
URL_TABS = (("URL Performance", "/url"), ("Nguồn traffic", "/nguon"), ("Index", "/index"),
            ("Quản lý URL", "/urls"))
RESEARCH_TABS = (("Keyword Overview", "/tu-khoa"), ("Keyword Ideas", "/research"), ("Thư viện AI", "/ai-da-tao"))
# Icon riêng cho từng tab con, dùng ở lối tắt (nút +, menu chuột phải): các tab cùng mục không trùng icon của mục cha.
SUB_ICONS = {
    "/projects": "folder_open", "/budget": "account_balance_wallet", "/access": "manage_accounts",
    "/cai-dat": "extension", "/quan-tri-ai": "smart_toy",
    "/url": "insert_link", "/nguon": "alt_route", "/index": "fact_check", "/urls": "playlist_add",
    "/tu-khoa": "manage_search", "/research": "lightbulb", "/ai-da-tao": "history",
    "/kpi?tab=lo-trinh": "route", "/kpi?tab=tu-khoa": "format_list_numbered", "/kpi?tab=lich-su": "history",
    "/local?tab=reviews": "reviews", "/local?tab=posts": "post_add", "/local?tab=profile": "badge",
    "/backlink?tab=audit": "rule", "/backlink?tab=list": "list", "/backlink?tab=built": "construction",
    "/backlink?tab=gap": "compare_arrows", "/backlink?tab=sources": "source",
    "/audit?tab=trang": "description", "/audit?tab=tuan": "date_range",
    "/toc-do?tab=field": "groups", "/toc-do?tab=pages": "description",
    "/doi-thu?tab=xu-huong": "trending_up", "/doi-thu?tab=tu-khoa": "compare", "/doi-thu?tab=backlink": "link",
    "/doi-thu?tab=danh-sach": "list",
    "/ai?tab=nguon": "hub", "/ai?tab=trang-dich": "description", "/ai?tab=ai-google": "travel_explore",
    "/ai?tab=co-hoi": "lightbulb",
    "/aio?tab=viec": "task_alt", "/aio?tab=tu-khoa": "key", "/aio?tab=ban-ai": "article",
    "/merchant?tab=products": "inventory_2",
}
NAV_PARENT = {title: "URL & Index" for title, _ in URL_TABS}  # màn → mục menu được tô sáng
NAV_PARENT["Keyword Overview"] = NAV_PARENT["Keyword Ideas"] = NAV_PARENT["Thư viện AI"] = "Keyword Research"
NAV_PARENT.update({title: "Quản trị" for title, _ in ADMIN_TABS})
EDIT_PAGES = ("/urls", "/ai?tab=chat-luong")


def href_first(items) -> str:
    return items[0][1] if items else ""


def page_href(title: str) -> str:
    """Địa chỉ của màn theo tên (mục menu hoặc tab của URL & Index); không có thì về Tổng quan."""
    return next((h for t, h in URL_TABS + ADMIN_TABS if t == title),
                next((h for _, items in NAV for label, h, _ in items if label == title), "/"))  # màn làm việc cần quyền sửa: người chỉ xem không thấy trên menu


def _col(name, label, align="left", number=False, sortable=True):
    col = {"name": name, "label": label, "field": name, "align": align, "sortable": sortable}
    if number:
        col[":format"] = NUMBER
        col["align"] = "right"
    return col


def url_format_js(site: str) -> str:
    """Hàm định dạng cột URL. NiceGUI chạy thuộc tính ':format' như JavaScript, nên chuỗi website của dự án được đưa
    vào bằng json.dumps (đúng cú pháp chuỗi JS, thoát nháy và gạch chéo ngược), không ghép thẳng."""
    import json
    return f"val => (val || '').replace({json.dumps(str(site).rstrip('/'))}, '') || '/'"


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
    from . import anti_bot
    anti_bot.install(app, ui)  # chặn bot AI thu thập dữ liệu (robots.txt, X-Robots-Tag, 403 theo User-Agent)
    assets = Path(__file__).parent / "assets"
    app.add_static_files("/assets", assets)  # biểu tượng của tool (logo từng website lưu trong bảng dự án)

    from . import gbp_posts as _GP
    _GP.MEDIA["base"] = cfg.db_path.parent  # ảnh bài đăng GBP: một thư mục chung trong thư mục dữ liệu chính

    @app.get("/gbp-media/{name}")
    def gbp_media(name: str):
        """Ảnh bài đăng Google Business Profile: link công khai cho Google tải (tên ngẫu nhiên, chỉ JPG / PNG)."""
        from fastapi.responses import FileResponse, Response

        from . import gbp_posts as GP
        p = GP.image_file(None, name)
        if not p:
            return Response(status_code=404)
        return FileResponse(p, media_type="image/png" if name.endswith(".png") else "image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})

    base = cfg  # cấu hình chung (config.toml); số liệu theo dự án lấy qua project_scope()
    # Người ngồi ở máy chạy tool là Chủ tool: dùng email Chủ tool (config.toml) để nhật ký / avatar chỉ có một tên
    owners = [e.strip().lower() for e in base.access.editors if e.strip()]
    local_name = owners[0] if owners else getpass.getuser()
    with closing(db.connect(base.db_path)) as c:
        PJ.ensure(c, base)
        first_slug = PJ.list_projects(c)[0]["slug"]
        A.migrate_members(c, base.access, first_slug)
        A.migrate_four_groups(c)  # Team xem cũ → Member
        A.adopt_config(c, base.access, first_slug)  # email viewers trong config.toml → quản lý trên màn Phân quyền
    from . import points as PT
    PT.set_app_db(base.db_path)  # credit của Member nằm ở file dữ liệu chính

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
            allowed = [(p, r) for p in active if (r := A.project_role(c, base.access, acct, p["slug"], first,
                                                                    bool(p["settings"].get("google_owner"))))]
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
            if PR.leave(who, client.id) and getattr(acct, "via", "") in ("password", "google"):
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
            if getattr(acct, "via", "") in ("password", "google"):
                ui.button("Đăng xuất", on_click=lambda: (app.storage.user.pop("auth", None),
                                                         ui.navigate.to("/login"))).props("flat no-caps")

    def open_page(request: Request, *, client_ok: bool = False, edit: bool = False, admin: bool = False,
                  owner: bool = False):
        """Mở một trang: đã đăng nhập, có dự án được vào, đủ quyền cho trang này. Trả (người dùng trong dự án, dự án)
        hoặc None (đã chuyển hướng / hiện thông báo, không dựng nội dung trang)."""
        if not (acct := gate(request)):
            return None
        if (admin and not A.is_admin(acct)) or (owner and not A.is_owner(acct)):
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
        role_label = {"owner": "Owner", "admin": "Admin", **A.PROJECT_ROLES}
        rank = {PR.AVAILABLE: 0, PR.AWAY: 1, PR.OFFLINE: 2}

        @ui.refreshable
        def render():
            with app_connect() as c:
                first = PJ.list_projects(c)[0]["slug"]
                people = A.people_in_project(c, base.access, P.project["slug"], first,
                                             bool(P.project["settings"].get("google_owner")))
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
            box = T.avatar_group(ui, rows, max_shown=4, size=28, ring=T.PAGE_BG,
                                 label=f"{len(rows)} người có quyền ở {P.project['name']}, {online} đang online. "
                                       "Bấm để xem danh sách")
            with box:
                with ui.menu().props('anchor="bottom right" self="top right" :offset="[0, 8]"').classes(
                        "sr-account-menu").style("width: 320px") as menu:
                    with ui.column().classes("gap-0 q-px-md q-pt-md q-pb-xs"):
                        ui.label(f"Người có quyền ở {P.project['name']}").classes("text-sm font-semibold")
                        ui.label(f"{len(rows)} người · {online} đang online").classes("text-xs muted")
                    # chỉ cuộn dọc; mỗi người: tên · vai trò (một dòng, cắt "…") · trạng thái (chấm màu + chữ)
                    with ui.column().classes("gap-0 w-full").style("max-height: 340px; overflow-y: auto; "
                                                                   "overflow-x: hidden"):
                        for r in rows:
                            with ui.row().classes("w-full items-center gap-3 no-wrap q-px-md").style(
                                    "padding-top:7px; padding-bottom:7px; min-width:0"):
                                T.presence_avatar(ui, r["name"], r["status"], r["status_text"], size=30,
                                                  colors=T.avatar_color(r["email"]), photo=r["photo"])
                                with ui.column().classes("gap-0 col").style("min-width:0; overflow:hidden"):
                                    ui.label(r["name"]).classes("text-sm font-semibold ellipsis w-full").props[
                                        "title"] = r["email"]
                                    ui.label(r["who"]).classes("text-xs muted ellipsis w-full").props["title"] = r["who"]
                                    on = r["status"] == PR.AVAILABLE
                                    with ui.row().classes("items-center no-wrap sr-acct-status w-full" + (
                                            " on" if on else "")).style("min-width:0"):
                                        ui.element("span").classes("sr-acct-dot").style("flex:none")
                                        ui.label(r["status_text"]).classes("ellipsis").props["title"] = r["status_text"]
                    if A.is_admin(user):
                        ui.separator()
                        with ui.menu_item(on_click=lambda: ui.navigate.to(f"/access?project={P.project['slug']}")
                                          ).classes("items-center gap-3"):
                            ui.icon("manage_accounts", size="18px").classes("muted")
                            ui.label("Quản lý quyền ở website này").classes("text-sm")
            box.on("keydown.enter", menu.open)

        render()
        ui.timer(30, render.refresh)

    def points_card(user) -> None:
        """Member: credit đã dùng / hạn mức tháng này (mọi tác vụ bấm tay trừ credit, ngày 1 đặt lại)."""
        from . import points as PT
        b = PT.my_balance(user)
        if not b:
            return
        ratio = b["used"] / b["limit"] if b["limit"] else 1
        warn = ratio >= 0.8
        box = ui.element("div").classes("sr-acct-budget clickable" + (" warn" if warn else "")).props(
            'role=link tabindex=0 aria-label="Mở Credit của tôi"')
        box.on("click", lambda: credit_dialog(user))
        box.on("keydown.enter", lambda: credit_dialog(user))
        with box:
            with ui.row().classes("items-center gap-1 no-wrap w-full"):
                ui.icon("toll", size="16px").classes("muted").props('aria-hidden="true"')
                ui.label("Credit tháng này").classes("text-xs muted col ellipsis")
                ui.icon("chevron_right", size="16px").classes("muted").props('aria-hidden="true"')
            with ui.row().classes("items-baseline gap-1 no-wrap"):
                ui.label(f"{b['left']:,}".replace(",", ".")).classes("sr-acct-budget-num num")
                ui.label(f"còn lại / {b['limit']:,} credit".replace(",", ".")).classes("text-xs muted")
            color = "#B7791F" if warn else T.GREEN
            ui.html(f'<div class="sr-kp-bar thin" role="img" aria-label="Đã dùng {min(ratio, 1) * 100:.0f}% credit">'
                    f'<i style="width:{min(ratio, 1) * 100:.1f}%;background:{color}"></i></div>').classes("w-full")
            ui.label(f"Đã dùng {b['used']:,} credit · đặt lại ngày 1".replace(",", ".")).classes("text-xs muted")

    def credit_dialog(user) -> None:
        """Credit của tôi (popup): số dư tháng này + máy tính credit. Mở từ thẻ credit, menu tài khoản, nút +."""
        from . import points as PT
        from . import web_points as WP
        b = PT.my_balance(user)
        if b is None:  # Owner / Admin: không giới hạn, vẫn ghi số đã dùng
            try:
                with app_connect() as c:
                    b = {**PT.balance(c, str(user)), "unlimited": True}
            except Exception:  # noqa: BLE001
                b = None
        with ui.dialog() as dlg, ui.card().classes("sr-pt-dlg q-pa-none"):
            with ui.row().classes("w-full items-center no-wrap gap-2 sr-pt-dlg-head"):
                ui.label("Credit của tôi").classes("text-base font-semibold col")
                ui.button("Lịch sử trừ credit", icon="history", on_click=lambda: ui.navigate.to("/diem")).props(
                    "flat no-caps dense")
                ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')
            with ui.element("div").classes("sr-pt-dlg-body"):
                if b:
                    with ui.element("div").classes("sr-pt-bal"):
                        if b.get("unlimited"):
                            ui.label("Không giới hạn").classes("sr-pt-bal-num")
                            ui.label(f"Owner / Admin · tháng này đã dùng {b['used']:,} credit".replace(",", ".")
                                     ).classes("text-xs muted")
                        else:
                            with ui.row().classes("items-baseline gap-1 no-wrap"):
                                ui.label(f"{b['left']:,}".replace(",", ".")).classes("sr-pt-bal-num num")
                                ui.label(f"còn lại / {b['limit']:,} credit tháng này".replace(",", ".")).classes(
                                    "text-sm muted")
                            ratio = b["used"] / b["limit"] if b["limit"] else 1
                            ui.html(f'<div class="sr-kp-bar thin"><i style="width:{min(ratio, 1) * 100:.1f}%;'
                                    f'background:{"#B7791F" if ratio >= .8 else T.GREEN}"></i></div>').classes("w-full")
                            ui.label(f"Đã dùng {b['used']:,} · đặt lại ngày 1".replace(",", ".")).classes(
                                "text-xs muted")
                ui.label("Máy tính credit").classes("sr-rai-h q-mt-sm")
                WP.calculator(ui, user, framed=False)
        dlg.on("hide", dlg.delete)
        dlg.open()

    def account_menu(user, P, active: str, budget: dict | None = None) -> None:
        """Góc dưới menu trái: avatar + tên + trạng thái; bấm vào mở menu tài khoản (thông tin, hạn mức credit /
        ngân sách, hồ sơ, đăng xuất). Quản trị ở menu trái, đổi website ở thanh trên nên không lặp lại ở đây."""
        st, st_text = PR.describe(user)
        with app_connect() as c:
            prof = A.profiles(c).get(str(user), {})
        name, photo = A.display_name(prof, user), prof.get("avatar", "")
        role_text = ("Owner · trên máy chạy tool" if user.role == A.LOCAL else "Khách hàng" if A.is_client(user) else A.GROUPS[A.group(user)])

        def logout():
            app.storage.user.pop("auth", None)
            ui.navigate.to("/login")

        from .web_profile import profile_dialog
        open_profile = profile_dialog(ui, base, app_connect, user)

        with ui.row().classes("sr-account w-full items-center gap-2 q-mt-sm no-wrap").props(
                'tabindex=0 role=button aria-haspopup=menu aria-label="Tài khoản và cài đặt"').style(
                "flex-shrink:0; min-width:0") as acc_row:  # w-full: email dài thì cắt "…" thay vì tràn khỏi menu
            T.presence_avatar(ui, name, st, st_text, size=28, ring=T.CREAM, colors=T.avatar_color(str(user)),
                              photo=photo)
            with ui.column().classes("gap-0 sr-mini-hide col items-stretch").style("min-width:0"):
                ui.label(name).classes("text-sm ellipsis").props["title"] = str(user)
                ui.label(" · ".join(x for x in (role_text.split(" · ")[0] if user.role != A.LOCAL else "", st_text)
                                    if x)).classes("text-xs muted ellipsis")
            if budget and budget["warn"]:  # ngân sách sắp vượt: chấm cam ngay trên nút tài khoản để không bị bỏ sót
                ui.icon("warning", size="16px").classes("sr-mini-hide").style("color:#B7791F").tooltip(
                    "Ngân sách DataForSEO dự kiến vượt 80%")
            ui.icon("unfold_more", size="18px").classes("muted sr-mini-hide")
            with ui.menu().props('anchor="top left" self="bottom left" :offset="[0, 8]"').classes(
                    "sr-account-menu sr-acct2").style("width: 328px") as acc_menu:
                # đầu menu: ảnh, tên, email, nhóm quyền, trạng thái; nút bút chì mở Hồ sơ
                with ui.element("div").classes("sr-acct-head"):
                    with ui.row().classes("items-center gap-3 no-wrap"):
                        T.presence_avatar(ui, name, st, st_text, size=44, colors=T.avatar_color(str(user)),
                                          photo=photo)
                        with ui.column().classes("gap-0 col").style("min-width:0"):
                            ui.label(name).classes("sr-acct-name ellipsis")
                            if name != str(user):
                                ui.label(str(user)).classes("text-xs muted ellipsis").props["title"] = str(user)
                            with ui.row().classes("items-center gap-2 no-wrap sr-acct-chips"):
                                role_short, _, role_more = role_text.partition(" · ")
                                chip = ui.label(role_short).classes("sr-acct-chip")
                                if role_more:
                                    chip.tooltip(role_text)
                                on = st == PR.AVAILABLE
                                with ui.row().classes("items-center no-wrap sr-acct-status" + (" on" if on else "")):
                                    ui.element("span").classes("sr-acct-dot")
                                    ui.label(st_text)
                        ui.button(icon="edit", on_click=lambda: (acc_menu.close(), open_profile())).props(
                            'flat round dense size=sm aria-label="Sửa hồ sơ"').classes("sr-acct-edit").tooltip(
                            "Sửa hồ sơ")
                if budget:
                    budget["render"]()
                points_card(user)

                # Gọn: chỉ những gì thuộc về tài khoản. Quản trị đã có ở menu trái, đổi website ở thanh trên,
                # máy tính credit ở nút nổi +.
                with ui.element("div").classes("sr-acct-links"):
                    with ui.menu_item(on_click=open_profile).classes("items-center gap-3"):
                        ui.icon("account_circle", size="18px")
                        ui.label("Hồ sơ của tôi").classes("text-sm col")
                    if not A.is_client(user):
                        with ui.menu_item(on_click=lambda: ui.navigate.to("/diem")).classes("items-center gap-3"):
                            ui.icon("toll", size="18px")
                            ui.label("Credit của tôi").classes("text-sm col")
                            ui.label("Lịch sử trừ credit").classes("text-xs muted")
                        from . import google_login as GL
                        if GL.ready(base):
                            with ui.menu_item(on_click=lambda: ui.navigate.to("/google-cua-toi")).classes(
                                    "items-center gap-3"):
                                ui.icon("add_link", size="18px")
                                ui.label("Google của tôi").classes("text-sm col")
                                ui.label("Thêm website của bạn").classes("text-xs muted")
                if user.via in ("password", "google"):
                    with ui.element("div").classes("sr-acct-foot"):
                        with ui.menu_item(on_click=logout).classes("items-center gap-3 sr-acct-logout"):
                            ui.icon("logout", size="18px")
                            ui.label("Đăng xuất").classes("text-sm")
        acc_row.on("keydown.enter", acc_menu.open)

    def client_unlinked(P) -> set[str]:
        """Màn khách hàng không cần thấy trên menu vì dự án chưa gắn nguồn số (Local SEO, Merchant Center)."""
        from . import gbp as G
        from . import merchant as M
        out = set()
        with P.connect() as c:
            for href, linked in (("/local", G.linked), ("/merchant", M.linked)):
                try:
                    if not linked(c):
                        out.add(href)
                except Exception:  # noqa: BLE001 — bảng chưa có / lỗi đọc: coi như chưa gắn
                    out.add(href)
        return out

    def nav_groups(user, skip=frozenset()) -> list:
        """Các nhóm menu người này được thấy: [(tên nhóm | None, [(nhãn, đường dẫn, icon)])] (menu trái + popup Thêm)."""
        out = []
        for group_name, items in NAV:
            if A.is_client(user):
                items = [("Nguồn traffic", "/nguon", "travel_explore") if h == "/url" else (lb, h, ic)
                         for lb, h, ic in items if h not in skip]
            items = [(label, href, icon) for label, href, icon in items
                     if (href != "/yeu-cau" or A.is_client(user))  # trang yêu cầu của khách: chỉ khách
                     and (not A.is_client(user) or href.split("?")[0] in A.CLIENT_PAGES)
                     and (href not in ADMIN_PAGES or A.is_admin(user))
                     and (href not in OWNER_PAGES or A.is_owner(user))
                     and (href not in EDIT_PAGES or A.can_edit(user))]
            if items:
                out.append((group_name, items))
        return out

    def more_popup(user, P):
        """Nút Thêm dưới đáy (điện thoại): mọi mục menu trong một popup dạng lưới (icon + chữ), nhóm theo menu;
        nền phía sau tối và mờ. Trả về hộp thoại để mở."""
        skip = client_unlinked(P) if A.is_client(user) else set()
        try:
            path = ui.context.client.page.path
        except Exception:  # noqa: BLE001
            path = ""
        in_bar = {"/", "/report", "/yeu-cau"} if A.is_client(user) else {"/", "/rank"}  # đã có trên thanh dưới
        with ui.dialog().props('position=bottom transition-show=slide-up transition-hide=slide-down') as dlg,                 ui.card().classes("sr-more-pop"):
            ui.element("div").classes("sr-more-handle").props('aria-hidden="true"')
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label("Tất cả mục").classes("sr-more-title col")
                ui.button(icon="close", on_click=dlg.close).props('flat round dense size=sm aria-label="Đóng"')
            for group_name, items in nav_groups(user, skip):
                items = [x for x in items if x[1] not in in_bar]
                if not items:
                    continue
                if group_name:
                    ui.label(group_name).classes("sr-more-group")
                with ui.element("div").classes("sr-more-grid"):
                    for label, href, icon in items:
                        a = ui.element("a").classes("sr-more-item").props(
                            f'href="{href}"' + (' aria-current="page"' if path == href else ""))
                        with a:
                            with ui.element("span").classes("sr-more-ico"):
                                ui.icon(icon, size="19px").props('aria-hidden="true"')
                            ui.label(label).classes("sr-more-lab")
        return dlg

    def bottom_nav(user, P, drawer) -> None:
        """Điện thoại (< 768px): thanh điều hướng cố định dưới đáy, 4 mục icon + chữ. Team: Tổng quan · Thứ hạng ·
        Thông báo (mở chuông, có số chưa xem) · Thêm (mở menu đầy đủ). Khách hàng: Tổng quan · Báo cáo · Yêu cầu (số
        câu trả lời mới) · Thêm. Mục đang mở tô màu, có aria-current="page"; chừa vùng thanh Home của iPhone."""
        from . import notices as N
        cl = A.is_client(user)
        try:
            with P.connect() as c:
                unseen = N.unseen(N.cached(c, P.cfg, user, P.project["slug"]))
        except Exception:  # noqa: BLE001
            unseen = 0
        try:
            path = ui.context.client.page.path
        except Exception:  # noqa: BLE001
            path = ""
        items = ([("Tổng quan", "space_dashboard", "/"), ("Báo cáo", "article", "/report"),
                  ("Yêu cầu", "forum", "/yeu-cau"), ("Thêm", "menu", "more")] if cl else
                 [("Tổng quan", "space_dashboard", "/"), ("Thứ hạng", "leaderboard", "/rank"),
                  ("Thông báo", "notifications", "bell"), ("Thêm", "menu", "more")])
        ui.add_head_html("<script>(() => { const m = document.querySelector('meta[name=viewport]');"
                         " if (m && !m.content.includes('viewport-fit')) m.content += ', viewport-fit=cover'; })();"
                         "</script>")
        with ui.element("nav").classes("sr-bnav").props('aria-label="Điều hướng chính"'):
            for label, icon, target in items:
                badge = unseen if (target == "bell" or (cl and target == "/yeu-cau")) else 0
                if target.startswith("/"):
                    on = path == target
                    el = ui.element("a").props(f'href="{target}"' + (' aria-current="page"' if on else ""))
                else:
                    on = False
                    el = ui.element("button").props('type="button"')
                    if target == "more":  # mọi mục menu trong một popup lưới (không mở menu trượt)
                        el.props('aria-haspopup="dialog"')
                        more = more_popup(user, P)
                        el.on("click", more.open)
                    else:  # mở cửa sổ thông báo của chuông (chuông trên thanh trên cùng ẩn ở điện thoại)
                        # chạy ngay trên trình duyệt, chờ cú chạm kết thúc (tránh menu tự đóng vì "bấm ra ngoài")
                        el.on("click", js_handler="() => setTimeout(() => "
                                                  "document.querySelector('.sr-bell')?.click(), 80)")
                if badge:
                    el.props(f'aria-label="{label}, {badge} chưa xem"')
                with el:
                    ui.icon(icon if on else f"o_{icon}", size="26px").props('aria-hidden="true"')  # iOS: chọn = đặc
                    ui.label(label)
                    if badge:
                        ui.label(str(badge) if badge < 100 else "99+").classes("sr-bnav-badge").props(
                            'aria-hidden="true"')

    def float_group(user, P, active: str) -> None:
        """Nhóm nút nổi góc dưới phải: nút + mở thao tác nhanh theo vai trò, nút về đầu trang (cuộn quá 400px).
        Khách hàng: ba loại góp ý gửi cho đội SEO. Người được sửa: thêm từ khóa, tra từ khóa, việc cần làm từ Bản tin
        AI, credit của tôi, sửa hồ sơ. Người còn lại: tra từ khóa và credit. Mỗi thao tác mở popup, không rời trang."""
        from .fab import FloatGroup
        if A.is_client(user):
            from .web_feedback import feedback_opener
            open_fb = feedback_opener(ui, P.connect, user, active)
            FloatGroup([{"key": "question", "icon": "help_outline", "label": "Đặt câu hỏi"},
                        {"key": "data", "icon": "report_gmailerrorred", "label": "Báo lỗi số liệu"},
                        {"key": "idea", "icon": "lightbulb_outline", "label": "Gửi đề xuất"}],
                       fab_label="Gửi yêu cầu cho đội SEO", on_action=lambda k: open_fb(k))
        else:
            # Người trong team / tài khoản chỉ xem: nút nhanh do từng người tự chọn (quick_prefs), mục cuối "Tùy chỉnh"
            from . import quick_prefs as QP
            from . import web_quick as Q  # số yêu cầu hỗ trợ mới: nhãn ở mục Yêu cầu hỗ trợ trên menu trái
            from .web_profile import profile_dialog
            ed_ = A.can_edit(user)
            with app_connect() as c:
                items = QP.get(c, str(user), ed_)
            # lối tắt trang đã lưu trước đây mang icon của mục cha: lấy lại icon theo tab con hiện tại
            items = [dict(x, icon=SUB_ICONS.get(x["key"][5:], x["icon"])) if x["key"].startswith("page:") else x
                     for x in items]
            open_profile = profile_dialog(ui, base, app_connect, user)
            run_ = {"kw": lambda: Q.add_keywords(ui, P, user), "look": lambda: Q.lookup_keyword(ui, P, user),
                    "profile": lambda: open_profile(), "credit": lambda: credit_dialog(user),
                    "todo": lambda: Q.brief_todo(ui, P, user), "rival": lambda: Q.add_rival(ui, P, user),
                    "fb": lambda: ui.navigate.to("/ho-tro")}

            def act(k: str) -> None:
                if k == QP.CUSTOM["key"]:
                    quick_custom(user, P, ed_)
                elif k.startswith("page:"):
                    ui.navigate.to(k[5:])
                elif k.startswith("link:"):
                    ui.navigate.to(k[5:], new_tab=k[5:].startswith("http"))
                elif k in run_:
                    run_[k]()
            FloatGroup(items + [QP.CUSTOM], fab_label="Thao tác nhanh", on_action=act)

    def page_choices(user, P) -> list[dict]:
        """Các trang / tab người này mở được, để làm lối tắt: [{"key": "page:/…", "label", "icon"}]."""
        subs = sub_nav(user, P)
        out = []
        for group_name, items in NAV:
            for label, href, icon in items:
                if href == "/yeu-cau" or (href in ADMIN_PAGES and not A.is_admin(user)) or \
                        (href in OWNER_PAGES and not A.is_owner(user)):
                    continue
                tabs = subs.get(href) or []
                if not tabs:
                    out.append({"key": f"page:{href}", "label": label, "icon": icon})
                for tab, h in tabs:
                    if (h in ADMIN_PAGES and not A.is_admin(user)) or (h in OWNER_PAGES and not A.is_owner(user)):
                        continue
                    out.append({"key": f"page:{h}", "label": f"{label} · {tab}" if tab != label else label,
                                "icon": SUB_ICONS.get(h, icon)})
        return out

    def quick_custom(user, P, ed_: bool) -> None:
        """Tùy chỉnh nút nhanh: bật / tắt thao tác có sẵn, thêm lối tắt trang, thêm liên kết riêng, sắp thứ tự."""
        from . import quick_prefs as QP
        with app_connect() as c:
            cur = [dict(x) for x in QP.get(c, str(user), ed_)]
        pages = page_choices(user, P)
        page_by = {x["key"]: x for x in pages}
        avail = [x for x in (QP.builtin(k, ed_) for k in QP.BUILTIN) if x]
        state = {"items": cur}
        with ui.dialog() as dlg, ui.card().style("width: 560px; max-width: 96vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.icon("tune", size="20px").classes("text-primary")
                ui.label("Tùy chỉnh nút nhanh").classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')
            ui.label(f"Chọn tối đa {QP.MAX_ITEMS} nút cho nút + và menu chuột phải. Chỉ áp dụng cho tài khoản của bạn."
                     ).classes("text-xs muted")

            @ui.refreshable
            def chosen() -> None:
                items = state["items"]
                ui.label(f"Đang dùng · {len(items)}/{QP.MAX_ITEMS}").classes("sr-rai-h q-mt-sm")
                if not items:
                    ui.label("Chưa có nút nào.").classes("text-sm muted")
                for i, x in enumerate(items):
                    with ui.row().classes("w-full items-center no-wrap gap-2 sr-qc-row"):
                        ui.icon(x["icon"], size="20px").classes("text-primary")
                        ui.label(x["label"]).classes("text-sm col ellipsis")
                        if x["key"].startswith(("page:", "link:")):
                            ui.label(x["key"][5:]).classes("text-xs muted ellipsis").style("max-width:180px")
                        ui.button(icon="arrow_upward", on_click=lambda _, i=i: move(i, -1)).props(
                            "flat round dense size=sm" + (" disable" if i == 0 else "")).tooltip("Lên trước")
                        ui.button(icon="close", on_click=lambda _, i=i: (items.pop(i), chosen.refresh(), adders.refresh())
                                  ).props("flat round dense size=sm").tooltip("Bỏ")

            def move(i, d):
                it = state["items"]
                j = i + d
                if 0 <= j < len(it):
                    it[i], it[j] = it[j], it[i]
                    chosen.refresh()

            def add(x: dict) -> None:
                if len(state["items"]) >= QP.MAX_ITEMS:
                    ui.notify(f"Tối đa {QP.MAX_ITEMS} nút: bỏ bớt một nút trước", type="warning")
                    return
                if any(y["key"] == x["key"] for y in state["items"]):
                    ui.notify("Nút này đã có", type="warning")
                    return
                state["items"].append(dict(x))
                chosen.refresh()
                adders.refresh()

            @ui.refreshable
            def adders() -> None:
                have = {x["key"] for x in state["items"]}
                free = [x for x in avail if x["key"] not in have]
                ui.label("Thêm nút").classes("sr-rai-h q-mt-md")
                if free:
                    with ui.row().classes("w-full gap-1 wrap"):
                        for x in free:
                            ui.button(x["label"], icon=x["icon"], on_click=lambda _, x=x: add(x)).props(
                                "outline dense no-caps size=sm color=grey-9")
                with ui.row().classes("w-full items-end gap-2 no-wrap q-mt-sm"):
                    opts = {k: v["label"] for k, v in page_by.items() if k not in have}
                    ui.select(opts, label="Thêm lối tắt tới trang / tab (gõ để tìm)", with_input=True,
                              on_change=lambda e: e.value and add(page_by[e.value])).props(
                        "outlined dense options-dense").classes("col")
                with ui.row().classes("w-full items-end gap-2 no-wrap q-mt-sm"):
                    nm = ui.input("Tên liên kết riêng", placeholder="ví dụ: Sheet báo cáo khách").props(
                        "outlined dense").classes("col")
                    url = ui.input("Địa chỉ", placeholder="https://… hoặc /duong-dan").props(
                        "outlined dense").classes("col")

                    def add_link():
                        u = (url.value or "").strip()
                        items = QP.clean([{"key": f"link:{u}", "label": nm.value or u}], ed_)
                        if not items:
                            ui.notify("Địa chỉ phải bắt đầu bằng https:// hoặc /", type="warning")
                            return
                        add(items[0])
                    ui.button("Thêm", icon="add_link", on_click=add_link).props("unelevated dense no-caps")
            chosen()
            adders()

            def save():
                with app_connect() as c:
                    QP.save(c, str(user), state["items"], ed_)
                dlg.close()
                ui.notify("Đã lưu nút nhanh", type="positive")
                ui.navigate.reload()

            def to_default():
                state["items"] = QP.defaults(ed_)
                chosen.refresh()
                adders.refresh()
            with ui.row().classes("w-full justify-between q-mt-md"):
                ui.button("Về mặc định", on_click=to_default).props("flat no-caps color=grey-8")
                with ui.row().classes("gap-2"):
                    ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                    ui.button("Lưu", icon="check", on_click=save).props("unelevated no-caps")
        dlg.on("hide", dlg.delete)
        dlg.open()

    def sub_nav(user, P) -> dict[str, list[tuple[str, str]]]:
        """Tab con của từng mục menu (đúng tab có trên trang, theo quyền): mục → [(tên tab, địa chỉ)].
        Tab đầu là tab mặc định của trang nên không cần ?tab=."""
        from . import web_audit as WAU, web_backlink as WB, web_cwv as WC, web_kpi as WK, web_local as WL, \
            web_merchant as WM, web_opps as WO, web_rivals as WR
        cl = A.is_client(user)

        def q(path, tabs):
            return [(name, path if i == 0 else f"{path}?tab={key}") for i, (key, name, *_) in enumerate(tabs)]
        out = {
            "/url": [(t, h) for t, h in URL_TABS if (h not in EDIT_PAGES or A.can_edit(user))
                     and (not cl or h in A.CLIENT_PAGES)],
            "/tu-khoa": list(RESEARCH_TABS),
            "/projects": [(t, h) for t, h in ADMIN_TABS if h not in OWNER_PAGES or A.is_owner(user)],
            "/toc-do": q("/toc-do", [] if cl else WC.TABS), "/co-hoi": q("/co-hoi", WO.TABS), "/audit": q("/audit", WAU.TABS),
            "/backlink": q("/backlink", [t for t in WB.PAGE_TABS if not (cl and t[0] in WB.TEAM_TABS)]), "/local": q("/local", [] if cl else WL.TABS),
            "/merchant": q("/merchant", WM.TABS),
            "/kpi": q("/kpi", list(WK.TABS)),
            "/doi-thu": q("/doi-thu", WR.TABS),
            "/ai": q("/ai", [("tong-quan", "Tổng quan"), ("nguon", "Nguồn AI"),
                             *([] if cl else [("trang-dich", "Trang đích"), ("ai-google", "AI trên Google"),
                                              ("co-hoi", "Cơ hội SEO/GEO")])]),
            "/aio": q("/aio", [("tong-quan", "Tổng quan"), *([] if cl else [("viec", "Việc nên làm")]),
                               ("tu-khoa", "Từ khóa"), *([] if cl else [("ban-ai", "Bản AI")])]),
        }
        try:
            with P.connect() as c:
                sets_ = [x for x in R.sets(c, P.site) if not x["draft"]]
            out["/rank"] = [("Tổng quan", "/rank")] + [(x["name"], f"/rank?bo={x['id']}") for x in sets_]
        except Exception:  # noqa: BLE001 (dự án mới chưa có bảng bộ từ khóa)
            pass
        return {k: v for k, v in out.items() if len(v) > 1}

    def shell(active: str, user, P, ctx: dict | None = None, period: bool | str = True, group: bool = True):
        ui.add_head_html(T.HEAD)
        ui.add_body_html(T.BODY)
        # Nút chính màu đen (phong cách viên thuốc); xanh thương hiệu dùng cho số tốt và thông báo thành công.
        ui.colors(primary=T.INK, secondary=T.LIME, positive=PRIMARY, negative=T.RED, warning=T.AMBER)
        if app.storage.user.pop("ask_connect", None):  # vừa đăng nhập Google lần đầu: hỏi kết nối GSC / GA4
            from .web_my_google import connect_prompt
            connect_prompt(ui, base, app_connect, user)
        # Menu trái thu gọn được (chỉ còn icon); lựa chọn nhớ theo trình duyệt.
        mini = bool(app.storage.user.get("nav_mini"))
        # Màn rộng: menu mở sẵn, nằm cạnh thanh trên (không bị che logo). Điện thoại / màn hẹp: menu đóng, bấm ☰ để mở.
        drawer = ui.left_drawer(value=None, fixed=True, top_corner=True, bottom_corner=True).props(
            "width=232 mini-width=64" + (" mini" if mini else "")).style(
            f"background:{T.CREAM}; border-right:1px solid #E7E5DC; padding:0")
        with drawer, ui.column().classes("w-full no-wrap gap-0 sr-nav-scroll").style(
                "height:100%; box-sizing:border-box; padding:12px 8px; overflow-y:auto; overflow-x:hidden"):
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
                skip = client_unlinked(P) if A.is_client(user) else set()
                fb_new = 0
                if not A.is_client(user):
                    from . import feedback as FB
                    with P.connect() as c:
                        fb_new = FB.count_new(c)
                subs_of = sub_nav(user, P)
                for group_name, items in nav_groups(user, skip):
                    if group_name:
                        ui.label(group_name).classes("sr-nav-group")
                    elif group_name is None and href_first(items) == "/projects":
                        ui.element("div").classes("sr-nav-sep")  # Quản trị: tách khỏi nhóm trên bằng một vạch
                    for label, href, icon in items:
                        on = label == active or NAV_PARENT.get(active) == label
                        subs = subs_of.get(href) or []
                        item = ui.element("div").classes("sr-nav-item" + (" has-subs" if subs else "")
                                                          + (" is-open" if on and subs else ""))
                        item._props["data-label"] = label
                        with item:
                            with ui.link(target=href).classes("active" if on else ""):
                                ui.icon(icon, size="19px")
                                ui.label(label).classes("sr-mini-hide")
                                if href == "/ho-tro" and fb_new:
                                    T.count_badge(ui, fb_new, f"{fb_new} yêu cầu mới").classes("sr-nav-badge")
                                if subs:
                                    ui.icon("expand_more" if on else "chevron_right", size="16px").classes(
                                        "sr-nav-caret sr-mini-hide").props('aria-hidden="true"')
                                if mini and not subs:
                                    ui.tooltip(label).props("anchor='center right' self='center left'")
                            if subs:  # tab con: hiện ngay dưới mục đang mở; mục khác thì hiện khi rê chuột
                                with ui.element("div").classes("sr-nav-subs").props(
                                        f'aria-label="Các tab của {label}"'):
                                    for t_, u_ in subs:
                                        ui.link(t_, u_).classes("sr-nav-sub")
            ui.space()

            def budget_state() -> dict:
                with P.connect() as c:
                    st = R.budget_status(c, P.site, P.cfg.rank, K.latest_date(c, P.site))
                from datetime import date

                from .web_budget import projected  # cùng cách tính với màn Ngân sách: đã dùng + lịch còn lại
                st["estimate"] = projected(st["spent"], st["estimate"], date.today(), P.cfg.rank.paused)
                st["ratio"] = st["estimate"] / st["budget"] if st["budget"] else 0
                st["warn"] = st["ratio"] >= R.ALERT_RATIO
                return st

            @ui.refreshable
            def budget_card():
                """Ngân sách DataForSEO tháng này của website đang mở, vẽ trong menu tài khoản (thông tin nội bộ)."""
                st = budget_state()
                box = ui.element("div").classes("sr-acct-budget" + (" warn" if st["warn"] else ""))
                if A.is_admin(user):  # quản trị: bấm mở màn Ngân sách & chi phí (mọi website)
                    box.classes("clickable").props('role=link tabindex=0 aria-label="Mở Ngân sách & chi phí"')
                    box.on("click", lambda: ui.navigate.to("/budget"))
                    box.on("keydown.enter", lambda: ui.navigate.to("/budget"))
                with box:
                    with ui.row().classes("items-center gap-1 no-wrap w-full"):
                        ui.icon("account_balance_wallet", size="16px").classes("muted").props('aria-hidden="true"')
                        ui.label("Ngân sách DataForSEO").classes("text-xs muted col ellipsis")
                        if A.is_admin(user):
                            ui.icon("chevron_right", size="16px").classes("muted").props('aria-hidden="true"')
                    with ui.row().classes("items-baseline gap-1 no-wrap"):
                        ui.label(f"{R.usd(st['estimate'])}").classes("sr-acct-budget-num num")
                        ui.label(f"/ {st['budget']:.0f} USD · dự kiến tháng này").classes("text-xs muted")
                    color = "#B7791F" if st["warn"] else T.GREEN
                    ui.html(f'<div class="sr-kp-bar thin" role="img" aria-label="Đã dự kiến '
                            f'{min(st["ratio"], 9.99) * 100:.0f}% ngân sách"><i style="width:'
                            f'{min(st["ratio"], 1) * 100:.1f}%;background:{color}"></i></div>').classes("w-full")
                    ui.label(f"{st['stars']} keyword · đã dùng {R.usd(st['spent'])} USD").classes("text-xs muted")
                    if st["warn"]:
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.icon("warning", size="14px").style("color:#B7791F").props('aria-hidden="true"')
                            ui.label("Dự kiến vượt 80% ngân sách").classes("text-xs").style("color:#9A5B0B")

            budget = None
            if A.is_admin(user):  # ngân sách DataForSEO: chỉ Owner / Admin (Member xem credit của mình)
                budget = {"render": budget_card, "warn": budget_state()["warn"]}
            account_menu(user, P, active, budget)

        def toggle_nav():
            app.storage.user["nav_mini"] = not app.storage.user.get("nav_mini")
            if app.storage.user["nav_mini"]:
                drawer.props("mini")
            else:
                drawer.props(remove="mini")

        float_group(user, P, active)
        bottom_nav(user, P, drawer)

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
                href = page_href(active)

                def switch(slug):
                    app.storage.user["project"] = slug
                    ui.navigate.to(href)

                with ui.row().classes("sr-proj-switch items-center gap-2 no-wrap"):
                    T.project_icon(ui, P.project, 24)
                    ui.label(P.project["name"]).classes("text-sm font-medium ellipsis")
                    ui.icon("expand_more", size="18px").classes("muted")
                    # nhiều dự án: ô tìm ở đầu, danh sách cuộn trong khung cố định (website đang mở luôn trên cùng)
                    with ui.menu().props(':offset="[0, 6]"').classes("sr-proj-menu").style("width: 320px"):
                        rows_ = []
                        ui.label(f"Website · {len(P.projects)}").classes("sr-proj-h")
                        if len(P.projects) > 6:
                            def filt(e) -> None:
                                q_ = (e.value or "").strip().lower()
                                for p_, it in rows_:
                                    it.set_visibility(not q_ or q_ in (p_["name"] + " " + p_["site_url"]).lower())
                            ui.input(placeholder=f"Tìm trong {len(P.projects)} website", on_change=filt).props(
                                "outlined dense clearable autofocus").classes("q-ma-sm sr-proj-search").on(
                                "click", js_handler="e => e.stopPropagation()")
                        with ui.column().classes("gap-0 w-full sr-proj-list"):
                            for p in sorted(P.projects, key=lambda x: x["slug"] != P.project["slug"]):
                                cur = p["slug"] == P.project["slug"]
                                with ui.menu_item(on_click=lambda _, s_=p["slug"]: switch(s_)).classes(
                                        "sr-proj-item no-wrap" + (" sr-current" if cur else "")) as it:
                                    T.project_icon(ui, p, 30)
                                    with ui.column().classes("gap-0 col").style("min-width:0"):
                                        ui.label(p["name"]).classes("sr-proj-name ellipsis")
                                        ui.label(PJ.domain(p["site_url"])).classes("sr-proj-dom ellipsis")
                                    if cur:
                                        ui.label("Đang mở").classes("sr-proj-cur")
                                    else:
                                        ui.icon("arrow_forward", size="16px").classes("sr-proj-go")
                                rows_.append((p, it))
                        if A.is_admin(user):
                            ui.separator().classes("q-my-xs")
                            with ui.menu_item(on_click=lambda: ui.navigate.to("/projects")).classes(
                                    "sr-proj-item sr-proj-manage no-wrap"):
                                ui.icon("tune", size="18px")
                                ui.label("Quản lý dự án").classes("text-sm col")
            else:
                with ui.row().classes("items-center gap-2 no-wrap"):
                    T.project_icon(ui, P.project, 22)
                    ui.label(PJ.domain(P.site)).classes("text-sm font-medium")
            ui.space()
            if ctx and (period or (group and not A.is_client(user))):
                def pick(key, value):
                    app.storage.user[group_key(P) if key == "group" else key] = value
                    ui.navigate.reload()

                def pick_days(e):
                    app.storage.user["dash_days"] = e.value
                    ui.navigate.reload()

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

                def pick_compare(e):
                    app.storage.user["report_compare"] = e.value
                    ui.navigate.reload()

                cur_days = app.storage.user.get("dash_days") if app.storage.user.get("dash_days") in (7, 28, 90) \
                    else 28
                seg = "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"
                show_group = group and not A.is_client(user)  # nhóm URL là khái niệm nội bộ, khách hàng không cần

                def controls(sheet: bool) -> None:
                    """Các ô chọn kỳ / nhóm. sheet=False: trên thanh trên (màn rộng). sheet=True: trong khung trượt từ
                    đáy trên điện thoại, mỗi ô rộng hết khung và có nhãn."""
                    def sel(options, value, on_change, width, label, tip=None):
                        el = ui.select(options, value=value, on_change=on_change, label=label if sheet else None)
                        el.props("outlined options-dense" + ("" if sheet else " dense")).classes(
                            "w-full" if sheet else width)
                        if tip and not sheet:
                            el.tooltip(tip)
                        return el

                    if period == "days":  # Tổng quan: 7 / 28 / 90 ngày gần nhất
                        ui.toggle({7: "7 ngày", 28: "28 ngày", 90: "90 ngày"}, value=cur_days,
                                  on_change=pick_days).props(seg).classes("sr-seg")
                    elif period == "report":  # màn Báo cáo: Tuần | Tháng, kỳ báo cáo, kỳ so sánh
                        ui.toggle({"week": "Tuần", "month": "Tháng"}, value=ctx["kind"], on_change=pick_kind).props(
                            seg).classes("sr-seg")
                        if ctx["kind"] == "month":
                            periods, idx = ctx["months"], ctx["month"]
                            fmt = lambda p_: f"Tháng {p_[0]:%m/%Y}"  # noqa: E731
                        else:
                            periods, idx = ctx["weeks"], ctx["week"]
                            fmt = lambda p_: f"Tuần {p_[0]:%d/%m} – {p_[1]:%d/%m/%Y}"  # noqa: E731
                        sel({p_[0].isoformat(): fmt(p_) for p_ in periods}, periods[idx][0].isoformat(), pick_period,
                            "w-56", "Kỳ báo cáo")
                        options = {"prev": "So với kỳ trước", "yoy": "So với cùng kỳ năm trước"}
                        options.update({p_[0].isoformat(): "So với " + fmt(p_).lower() for p_ in periods[idx + 2:]})
                        sel(options, ctx["compare"] if ctx["compare"] in options else "prev", pick_compare, "w-64",
                            "Kỳ so sánh", "Kỳ so sánh")
                    elif period == "month":
                        sel({m[0].isoformat(): f"Tháng {m[0]:%m/%Y}" for m in ctx["months"]},
                            ctx["months"][ctx["month"]][0].isoformat(), lambda e: pick("month", e.value), "w-64",
                            "Tháng")
                    elif period:
                        sel({w[0].isoformat(): f"Tuần {w[0]:%d/%m} – {w[1]:%d/%m/%Y}" for w in ctx["weeks"]},
                            ctx["weeks"][ctx["week"]][0].isoformat(), lambda e: pick("week", e.value), "w-64", "Tuần")
                    if show_group:
                        sel(ctx["groups"], ctx["group"], lambda e: pick("group", e.value), "w-44", "Nhóm URL")

                # Màn rộng: các ô chọn nằm thẳng trên thanh trên.
                with ui.row().classes("items-center gap-2 no-wrap sr-top-ctrls"):
                    controls(False)
                # Điện thoại: một nút tóm tắt kỳ đang xem ("Tuần 09/11 · SEO chủ lực"), bấm mở khung trượt từ đáy có đủ
                # các ô chọn. Thanh trên chỉ còn một dòng.
                if period == "days":
                    summary = f"{cur_days} ngày"
                elif period == "report":
                    summary = (f"Tháng {ctx['months'][ctx['month']][0]:%m/%Y}" if ctx["kind"] == "month"
                               else f"Tuần {ctx['weeks'][ctx['week']][0]:%d/%m}")
                elif period == "month":
                    summary = f"Tháng {ctx['months'][ctx['month']][0]:%m/%Y}"
                elif period:
                    summary = f"Tuần {ctx['weeks'][ctx['week']][0]:%d/%m}"
                else:
                    summary = ""
                if show_group:
                    gname = (ctx["groups"] or {}).get(ctx["group"], "") if isinstance(ctx["groups"], dict) else ""
                    summary = " · ".join(x for x in (summary, gname) if x)
                with ui.dialog().props("position=bottom transition-show=slide-up transition-hide=slide-down") as \
                        period_dlg, ui.card().classes("sr-more-pop sr-period-pop"):
                    ui.element("div").classes("sr-more-handle").props('aria-hidden="true"')
                    with ui.row().classes("w-full items-center no-wrap"):
                        ui.label("Kỳ dữ liệu" if not (show_group and not period) else "Nhóm URL").classes(
                            "sr-more-title col")
                        ui.button(icon="close", on_click=period_dlg.close).props(
                            'flat round dense size=sm aria-label="Đóng"')
                    with ui.column().classes("w-full gap-3 q-mt-sm"):
                        controls(True)
                chip = ui.button(summary or "Kỳ", icon="event", on_click=period_dlg.open).props(
                    "outline no-caps dense color=grey-9 icon-right=expand_more").classes("sr-top-chip")
                chip.props["aria-label"] = f"Đổi kỳ dữ liệu, đang xem: {summary}"
                chip.props["aria-haspopup"] = "dialog"
            from .web_notices import bell
            bell(ui, P.cfg, P.connect, user, P.project["slug"])
            if not A.is_client(user):  # khách hàng không thấy ai khác có quyền (tránh lộ email team / khách khác)
                people_group(user, P)
            if ctx:  # điện thoại: ẩn (đã có trong chú thích chỉ báo dữ liệu), để thanh đầu trang không xuống 3 dòng
                with ui.row().classes("items-center gap-1 no-wrap gt-xs"):
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

    @ui.page("/backlink")
    def backlink_page(request: Request):
        """Backlink của website (DataForSEO): khách hàng xem được, chỉ người sửa được mới bấm lấy số mới."""
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        shell("Backlink", user, P, page_ctx(P), period=False, group=False)
        from .web_backlink import build_backlink_page
        build_backlink_page(ui, P.cfg, P.connect, user, request.query_params.get("tab", ""),
                            request.query_params.get("xem", ""))

    @ui.page("/aio")
    def aio_page(request: Request):
        """AI Overview của Google trên bộ từ khóa theo dõi (DataForSEO): trang riêng, tách khỏi số GA4 / GSC ở AI Search
        & GEO để khách hàng dễ theo dõi. Khách hàng xem được, không sửa danh sách thương hiệu."""
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        shell("AI Overview", user, P, page_ctx(P), period=False, group=False)
        from .web_aio import build_aio_page
        bo = request.query_params.get("bo", "")  # bộ từ khóa (từ tab bộ ở màn Từ khóa & Thứ hạng)
        build_aio_page(ui, P.cfg, P.connect, user, request.query_params.get("tab", ""),
                       int(bo) if bo.isdigit() else None)

    @ui.page("/ai")
    def ai_page(request: Request):
        params = dict(request.query_params)
        if params.get("tab") == "ai-overview":  # link cũ: AI Overview đã thành trang riêng
            from fastapi.responses import RedirectResponse
            return RedirectResponse("/aio")
        if not (opened := open_page(request, client_ok=True, edit=params.get("tab") == "chat-luong")):
            return
        user, P = opened
        ctx = page_ctx(P)
        shell("AI Search & GEO", user, P, ctx, period=False, group=False)  # trang có ô chọn kỳ riêng
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

    def url_tabs(user, current: str) -> None:
        """Ba tab của mục URL & Index (Hiệu suất URL · Index · Quản lý URL): mỗi tab là một màn, bấm để chuyển."""
        tabs_ = [(t, h) for t, h in URL_TABS if (h not in EDIT_PAGES or A.can_edit(user))
                 and (not A.is_client(user) or h in A.CLIENT_PAGES)]
        if len(tabs_) < 2:  # khách hàng: chỉ còn một màn, không cần thanh tab
            return
        with ui.tabs(value=current, on_change=lambda e: ui.navigate.to(e.value) if e.value != current else None).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs q-mb-sm"):
            for title, href in tabs_:
                ui.tab(href, title)

    def admin_tabs(user, current: str) -> None:
        """Các màn của mục Quản trị (Dự án · Ngân sách & chi phí · Phân quyền · Cài đặt tích hợp · AI) gom thành một thanh
        tab ở đầu màn; Cài đặt tích hợp và AI chỉ Owner thấy."""
        tabs_ = [(t, h) for t, h in ADMIN_TABS if h not in OWNER_PAGES or A.is_owner(user)]
        if len(tabs_) < 2:
            return
        with ui.tabs(value=current, on_change=lambda e: ui.navigate.to(e.value) if e.value != current else None).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs q-mb-sm"):
            for title, href in tabs_:
                ui.tab(href, title)

    def research_tabs(current: str) -> None:
        """Các tab của mục Research từ khóa: Tổng quan từ khóa (/tu-khoa) · Ý tưởng từ khóa (/research) · AI đã tạo."""
        with ui.tabs(value=current, on_change=lambda e: ui.navigate.to(e.value) if e.value != current else None).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs q-mb-sm"):
            for title, href in RESEARCH_TABS:
                ui.tab(href, title)

    @ui.page("/url")
    def url_page(request: Request):
        if not (opened := open_page(request)):
            return
        user, P = opened
        ctx = page_ctx(P)
        focus = missing = None
        u = (request.query_params.get("u") or "").strip()
        if u:  # mở thẳng một URL (vd từ trang Backlink): chuyển sang nhóm chứa URL đó
            with P.connect() as c:
                uid = U._match_existing(c, P.site, U.normalize(u))
                gids = [g for (g,) in c.execute("SELECT group_id FROM url_group_members WHERE url_id = ?",
                                                (uid,))] if uid else []
            if gids:
                if ctx["group"] not in gids:
                    ctx["group"] = gids[0]
                    app.storage.user[group_key(P)] = gids[0]
                focus = uid
            else:
                missing = U.normalize(u)
        budget_card = shell("URL Performance", user, P, ctx)
        url_tabs(user, "/url")
        build_url_page(ui, P.cfg, P.connect, user, on_budget_change=budget_card.refresh, ctx=ctx, focus=focus,
                       missing=missing)

    @ui.page("/ho-tro")
    def requests_page(request: Request):
        """Yêu cầu hỗ trợ gửi từ trang báo cáo (đội SEO đọc, trả lời, đánh dấu đã xử lý). Quyền Khách hàng không
        mở trang này (họ xem yêu cầu của mình ở /yeu-cau)."""
        if not (opened := open_page(request)):
            return
        user, P = opened
        shell("Yêu cầu hỗ trợ", user, P, page_ctx(P), period=False, group=False)
        from .web_feedback import build_feedback_page
        build_feedback_page(ui, P.cfg, P.connect, user)

    @ui.page("/gop-y")
    def old_feedback_page():  # link cũ
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/ho-tro")

    @ui.page("/yeu-cau")
    def my_requests_page(request: Request):
        """Khách hàng: các yêu cầu đã gửi cho đội SEO, trạng thái và câu trả lời."""
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        if not A.is_client(user):
            ui.navigate.to("/ho-tro")
            return
        shell("Yêu cầu của tôi", user, P, page_ctx(P), period=False, group=False)
        from .web_feedback import build_my_requests_page
        build_my_requests_page(ui, P.cfg, P.connect, user)

    @ui.page("/okr/sua")
    def okr_edit_page(request: Request):
        """Tạo / sửa OKR trên tool (người được sửa)."""
        if not (opened := open_page(request, edit=True)):
            return
        user, P = opened
        shell("Công việc & OKR", user, P, page_ctx(P), period=False, group=False)
        from .web_okr_edit import build_okr_edit_page
        build_okr_edit_page(ui, P.cfg, P.connect, user, app_connect=app_connect)

    @ui.page("/okr")
    def okr_page(request: Request):
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        ctx = page_ctx(P)
        shell("Công việc & OKR", user, P, ctx, group=False, period=not A.is_client(user))
        build_okr_page(ui, P.cfg, P.connect, user, ctx, app_connect=app_connect, project=P.project)

    @ui.page("/kpi")
    def kpi_page(request: Request):
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        shell("KPI cam kết", user, P, page_ctx(P), period=False, group=False)
        build_kpi_page(ui, P.cfg, P.connect, user, app_connect, P.project, request.query_params.get("tab", ""))

    @ui.page("/kpi/sua")
    def kpi_edit_page(request: Request):
        if not (opened := open_page(request, edit=True)):
            return
        user, P = opened
        from .web_kpi import build_kpi_edit_page
        shell("KPI cam kết", user, P, page_ctx(P), period=False, group=False)
        build_kpi_edit_page(ui, P.cfg, P.connect, user)

    @ui.page("/login")
    def login_page(request: Request, next: str = "/", xem: str = ""):
        from .web_login import build_login_page, safe_next
        host = request.client.host if request.client else None
        if A.is_local(host, request.headers) and not xem:  # trên máy chạy tool không cần đăng nhập (?xem=1: xem thử)
            ui.navigate.to(safe_next(next))
            return
        ui.colors(primary=T.INK, secondary=T.LIME, positive=PRIMARY, negative=T.RED, warning=T.AMBER)
        build_login_page(ui, base, app_connect, next, A.client_ip(host, request.headers),
                         error=app.storage.user.pop("login_error", ""))

    @ui.page("/cho-duyet")
    def request_page():
        """Đăng nhập Google được nhưng chưa có quyền: báo đã gửi yêu cầu cho Owner / Admin duyệt."""
        from .web_login import build_request_page
        req = app.storage.user.get("request") or {}
        if not req.get("email"):
            ui.navigate.to("/login")
            return
        ui.colors(primary=T.INK, secondary=T.LIME, positive=PRIMARY, negative=T.RED, warning=T.AMBER)

        def approved() -> bool:
            """Đã được duyệt: mở phiên luôn (Google đã xác minh email này trên chính trình duyệt này, trong 24 giờ)."""
            import time as _t
            if _t.time() - float(req.get("at") or 0) > 24 * 3600:
                return False
            with app_connect() as c:
                who, _, sess = A.google_login(c, A.effective(c, base.access), req["email"])
            if not who:
                return False
            app.storage.user["auth"] = sess
            app.storage.user.pop("request", None)
            return True
        build_request_page(ui, req["email"], req.get("status", "pending"),
                           approved if req.get("status") == "pending" else None)

    @ui.page("/login/google")
    def google_login_start(next: str = "/"):
        """Nút "Đăng nhập bằng Google": tạo phiên chờ (state, nonce, PKCE) trong trình duyệt này rồi sang Google."""
        from . import google_login as GL
        from .web_access import _setting
        from .web_login import safe_next
        try:
            url, pending = GL.start(base, _setting(app_connect, "public_url"), safe_next(next))
        except ValueError as e:
            app.storage.user["login_error"] = str(e)
            ui.navigate.to("/login")
            return
        app.storage.user["google_pending"] = pending
        ui.navigate.to(url)

    @ui.page("/auth/google")
    async def google_login_back(request: Request):
        """Google gọi về sau khi chọn tài khoản: kiểm tra (google_login.finish) rồi mở phiên đăng nhập."""
        from nicegui import run as nrun

        from . import google_login as GL
        from .web_access import _setting
        from .web_login import safe_next
        pending = app.storage.user.pop("google_pending", None)
        query = dict(request.query_params)
        email = ""
        try:
            email = await nrun.io_bound(GL.finish, base, _setting(app_connect, "public_url"), pending, query)
            with app_connect() as c:
                who, why, sess = A.google_login(c, A.effective(c, base.access), email)
        except ValueError as e:
            who, why = None, str(e)
        if not who and email:  # Google xác minh được email nhưng chưa có quyền: gửi yêu cầu cho Owner / Admin duyệt
            with app_connect() as c:
                st = A.add_request(c, email)
                admins = [u["email"] for u in A.users(c, A.effective(c, base.access))
                          if u["role"] in (A.EDITOR, A.ADMIN_ACCT)]
            import time as _t
            app.storage.user["request"] = {"email": email, "status": "pending" if st == "new" else st,
                                           "at": _t.time()}
            if st == "new":  # báo ngay Owner / Admin đang mở tool (chưa mở thì hiện ở trang kế tiếp họ mở)
                from . import notices as N
                N.forget()
                for e in admins:
                    LIVE.notify(e, f"{email} xin quyền vào tool", caption="Duyệt ở Quản trị › Phân quyền",
                                type="info", icon="person_add", position="bottom-right", timeout=15000,
                                close_button="Đóng")  # vẫn còn trong chuông thông báo sau khi tự tắt
            ui.navigate.to("/cho-duyet")
            return
        if not who:
            app.storage.user["login_error"] = why
            ui.navigate.to("/login")
            return
        app.storage.user["auth"] = sess
        try:  # lần đăng nhập Google đầu: hỏi có muốn kết nối Google (GSC / GA4) của họ không (hiện ở trang kế)
            from .web_my_google import should_ask
            with app_connect() as c:
                if should_ask(c, base, who):
                    app.storage.user["ask_connect"] = 1
        except Exception:  # noqa: BLE001
            pass
        ui.navigate.to(safe_next((pending or {}).get("next")))

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
        admin_tabs(user, "/access")
        build_access_page(ui, base, app_connect, user, P.project["slug"], request.query_params.get("project"))

    @ui.page("/diem")
    def points_page(request: Request):
        """Credit của tôi: số dư, trừ ở đâu, bao nhiêu (Member / Owner / Admin; khách hàng không có)."""
        from .web_points import build_points_page
        if not (opened := open_page(request)):
            return
        user, P = opened
        shell("Credit của tôi", user, P, page_ctx(P), period=False, group=False)
        build_points_page(ui, app_connect, user)

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
        shell("Ngân sách & chi phí", user, P, page_ctx(P), period=False, group=False)
        admin_tabs(user, "/budget")
        build_budget_page(ui, base, app_connect, user)

    @ui.page("/projects")
    def projects_page(request: Request):
        from .web_projects import build_projects_page
        if not (opened := open_page(request, admin=True)):
            return
        user, P = opened
        shell("Dự án", user, P, page_ctx(P), period=False, group=False)
        admin_tabs(user, "/projects")
        build_projects_page(ui, base, app_connect, user)

    @ui.page("/cai-dat")
    def settings_page(request: Request):
        from .web_settings import build_settings_page
        if not (opened := open_page(request, owner=True)):
            return
        user, P = opened
        shell("Cài đặt tích hợp", user, P, page_ctx(P), period=False, group=False)
        admin_tabs(user, "/cai-dat")
        local = A.is_local(request.client.host if request.client else None, request.headers)
        from . import google_login as GL
        from .web_access import _setting
        public = _setting(app_connect, "public_url").rstrip("/")
        remote_ok = bool(public) and GL.ready(base)  # mở qua tên miền: dùng OAuth client Web của Đăng nhập Google
        build_settings_page(ui, base, app_connect, user, base.config_path, local,
                            google_origin=(f"http://{request.headers.get('host')}" if local else
                                           public if remote_ok else None),
                            google_notice=request.query_params.get("google"))

    @ui.page("/oauth/google")
    def google_callback(request: Request):
        """Google gọi về sau khi Chủ tool đồng ý cấp quyền (nút Kết nối Google ở Cài đặt tích hợp). Trên máy chạy tool,
        hoặc qua tên miền khi người mở là Owner; mã state phải khớp phiên vừa tạo (auth.web_login_finish kiểm tra)."""
        from . import auth
        if not A.is_local(request.client.host if request.client else None, request.headers):
            if not (who := gate(request)):
                return
            if not A.is_owner(who):
                ui.navigate.to("/")
                return
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
        ui.navigate.to(f"/cai-dat?google={result}")

    @ui.page("/google-cua-toi")
    def my_google_page(request: Request):
        """Google của tôi: Member trở lên kết nối Google riêng để thêm website của họ."""
        from .web_my_google import build_my_google_page
        if not (acct := gate(request)):
            return
        if not (opened := open_page(request)):
            return
        user, P = opened
        shell("Google của tôi", user, P, page_ctx(P), period=False, group=False)
        build_my_google_page(ui, base, app_connect, acct, request.query_params.get("google", ""))

    @ui.page("/oauth/google/me")
    async def my_google_callback(request: Request):
        """Google gọi về sau khi một người kết nối Google của họ (user_google.finish kiểm state + đúng người)."""
        from nicegui import run as nrun

        from . import user_google as UG
        if not (acct := gate(request)):
            return
        q = request.query_params
        if q.get("error"):
            result = "cancel" if q["error"] == "access_denied" else "fail"
        else:
            def work():
                with app_connect() as c:
                    return UG.finish(c, base, str(acct), q.get("state", ""), str(request.url))
            try:
                await nrun.io_bound(work)
                result = "ok"
            except Exception as e:  # noqa: BLE001
                print(f"Kết nối Google của người dùng không thành công: {e}")
                result = "expired" if isinstance(e, ValueError) else "fail"
        ui.navigate.to(f"/google-cua-toi?google={result}")

    @ui.page("/toc-do")
    def speed_page(request: Request):
        """Tốc độ & Core Web Vitals: mục riêng trên menu (CrUX + PageSpeed)."""
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        shell("Tốc độ trang", user, P, page_ctx(P), period=False, group=False)
        from .web_cwv import build_cwv_page
        build_cwv_page(ui, P.cfg, P.connect, user, request.query_params.get("tab", ""))

    @ui.page("/co-hoi")
    def opps_page(request: Request):
        """Cơ hội SEO: sắp lên top, trang tụt traffic, tranh nhau từ khóa, trang mới (từ dữ liệu GSC, không tốn tiền).
        Chỉ team: khách hàng không mở."""
        if request.query_params.get("tab") == "audit":  # Technical Audit đã thành mục riêng
            from fastapi.responses import RedirectResponse
            return RedirectResponse("/audit")
        if not (opened := open_page(request)):
            return
        user, P = opened
        shell("SEO Opportunities", user, P, page_ctx(P), period=False, group=False)
        from .web_opps import build_opps_page
        build_opps_page(ui, P.cfg, P.connect, user, request.query_params.get("tab", ""))

    @ui.page("/audit")
    def audit_page(request: Request):
        """Technical Audit: lỗi kỹ thuật SEO, dữ liệu cấu trúc, theo trang (tool tự quét, miễn phí). Chỉ team."""
        if not (opened := open_page(request)):
            return
        user, P = opened
        shell("Technical Audit", user, P, page_ctx(P), period=False, group=False)
        from .web_audit import build_audit_page
        build_audit_page(ui, P.cfg, P.connect, user, request.query_params.get("tab", ""),
                         request.query_params.get("muc", ""))

    @ui.page("/research/tu-khoa")
    def keyword_overview_old(request: Request):
        from urllib.parse import quote

        from fastapi.responses import RedirectResponse
        return RedirectResponse("/tu-khoa?kw=" + quote(request.query_params.get("kw", "")))

    @ui.page("/tu-khoa")
    def keyword_overview_page(request: Request):
        """Tổng quan một từ khóa (giống Keyword Overview của Semrush): mục riêng trên menu. Chỉ team."""
        if not (opened := open_page(request)):
            return
        user, P = opened
        shell("Keyword Overview", user, P, page_ctx(P), period=False, group=False)
        research_tabs("/tu-khoa")
        from .web_kw_overview import build_overview_page
        build_overview_page(ui, P.cfg, P.connect, user, request.query_params.get("kw", ""))

    @ui.page("/research")
    def research_page(request: Request):
        """Research từ khóa (Google Keyword Planner qua Google Ads API, miễn phí). Chỉ team."""
        if not (opened := open_page(request)):
            return
        user, P = opened
        shell("Keyword Ideas", user, P, page_ctx(P), period=False, group=False)
        research_tabs("/research")
        from .web_research import build_research_page
        rid = request.query_params.get("id", "")
        qp = request.query_params
        preset = next(((mode, qp[k]) for k, mode in (("kw", "keywords"), ("site", "site"), ("url", "url"))
                       if qp.get(k)), None)
        build_research_page(ui, P.cfg, P.connect, user, int(rid) if rid.isdigit() else None, qp.get("tra", ""),
                            preset, view={k: qp[k] for k in ("match", "kind", "view") if qp.get(k)})

    @ui.page("/quan-tri-ai")
    def ai_admin_page(request: Request):
        """Quản trị › AI: bật / tắt, model, lịch tự chạy, trần, nhật ký gọi AI. Chỉ Owner."""
        if not (opened := open_page(request, owner=True)):
            return
        user, P = opened
        shell("AI", user, P, page_ctx(P), period=False, group=False)
        admin_tabs(user, "/quan-tri-ai")
        from .web_ai_admin import build_ai_admin
        build_ai_admin(ui, base, app_connect, user,
                       A.is_local(request.client.host if request.client else None, request.headers),
                       open_key=request.query_params.get("gw"))

    @ui.page("/ai-da-tao")
    def ai_library_page(request: Request):
        """AI đã tạo: mọi bản AI viết cho website (tab thứ ba của Research từ khóa). Chỉ team."""
        if not (opened := open_page(request)):
            return
        user, P = opened
        shell("Thư viện AI", user, P, page_ctx(P), period=False, group=False)
        research_tabs("/ai-da-tao")
        from .web_ai_library import build_ai_library
        build_ai_library(ui, P.cfg, P.connect, user)

    @ui.page("/nguon")
    def sources_page(request: Request):
        """Nguồn tìm kiếm: web, hình ảnh, video, tab Tin tức, Discover, Google News (tab của URL & Index)."""
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        shell("Nguồn traffic", user, P, page_ctx(P), period=False, group=False)
        url_tabs(user, "/nguon")
        from .web_sources import build_sources_page
        build_sources_page(ui, P.cfg, P.connect, user)

    @ui.page("/index")
    def index_page(request: Request):
        if not (opened := open_page(request)):
            return
        user, P = opened
        shell("Index", user, P, page_ctx(P), period=False, group=False)
        url_tabs(user, "/index")
        build_index_page(ui, P.cfg, P.connect, user)

    @ui.page("/local")
    def local_page(request: Request):
        """Local SEO: hồ sơ Google Business Profile của dự án. Khách hàng xem được."""
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        shell("Local SEO", user, P, page_ctx(P), period=False, group=False)
        from .web_local import build_local_page
        build_local_page(ui, P.cfg, P.connect, user, request.query_params.get("tab", ""))

    @ui.page("/merchant")
    def merchant_page(request: Request):
        """Merchant Center: sản phẩm trên Google Shopping / hiển thị miễn phí và kiểm tra. Khách hàng xem được."""
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        shell("Merchant Center", user, P, page_ctx(P), period=False, group=False)
        from .web_merchant import build_merchant_page
        build_merchant_page(ui, P.cfg, P.connect, user, request.query_params.get("tab", ""))

    @ui.page("/doi-thu")
    def rivals_page(request: Request):
        """Đối thủ: một nơi quản lý danh sách đối thủ (tối đa 10, dùng chung cho thứ hạng và AI Overview), so sánh
        thị phần hiển thị và vị trí theo từng bộ từ khóa. Khách hàng xem được, không sửa danh sách."""
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        shell("Đối thủ", user, P, page_ctx(P), period=False, group=False)
        T.page_header(ui, "groups", "Đối thủ", "Ai đang cạnh tranh với bạn trên Google và AI Overview, ai đang vượt lên.")
        from .web_rivals import build_rivals_panel
        build_rivals_panel(ui, P.cfg, P.connect, user,
                           lambda i, f=None: ui.navigate.to(f"/rank?bo={i}" if i else "/rank"),
                           start_tab=request.query_params.get("tab", ""))

    @ui.page("/rank")
    def rank_page(request: Request):
        """Khách hàng xem được (chỉ xem: không thêm / check / sửa bộ, không thấy chi phí)."""
        if not (opened := open_page(request, client_ok=True)):
            return
        user, P = opened
        budget_card = shell("Thứ hạng từ khóa", user, P, page_ctx(P), period=False, group=False)
        bo = request.query_params.get("bo", "")  # bộ (tab) đang mở
        if bo == "doi-thu":  # link cũ: Đối thủ đã thành trang riêng
            ui.navigate.to("/doi-thu")
            return
        build_rank_page(ui, P.cfg, P.connect, user, on_budget_change=budget_card.refresh,
                        set_id=int(bo) if bo.isdigit() else None)

    @ui.page("/stars")
    def stars_page():
        ui.navigate.to("/rank")

    def url_col(site, name="url", label="URL"):
        """Cột URL chỉ hiện đường dẫn (bỏ tên miền), cắt "…" khi dài."""
        col = _col(name, label)
        col[":format"] = url_format_js(site)
        col.update({"classes": "ellipsis", "style": "max-width: 420px", "headerStyle": "max-width: 420px"})
        return col

    @ui.page("/urls")
    def urls_page(request: Request):
        if not (opened := open_page(request, edit=True)):
            return
        user, P = opened
        site, connect = P.site, P.connect
        shell("Quản lý URL", user, P, page_ctx(P), period=False, group=False)
        url_tabs(user, "/urls")
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
                ui.label("Trang nhiều click chưa có trong nhóm.").classes("muted")
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
                ui.label("Loại trang được tool tự nhận ra; sửa tay sẽ luôn được giữ.").classes("text-sm muted")

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
    from .web_rank import schedule_loop

    def start_schedule():  # check rank theo lịch (ngày + giờ) của từng bộ, mỗi 15 phút
        from nicegui import background_tasks

        from .ai_auto import auto_loop
        background_tasks.create(schedule_loop(base), name="rank-schedule")
        background_tasks.create(auto_loop(base), name="ai-auto")  # AI tự chạy theo lịch ở Quản trị › AI
        from .web_audit import schedule_loop as audit_loop
        background_tasks.create(audit_loop(base), name="audit-schedule")  # Technical Audit theo lịch thứ + giờ
        from .web_local import post_loop
        background_tasks.create(post_loop(base), name="gbp-post-schedule")  # bài đăng GBP đã lên lịch
    app.on_startup(start_schedule)
    ui.run(host="127.0.0.1", port=port, title="SEO Report", reload=False, show=show, language="vi",
           storage_secret=_storage_secret(base), favicon=assets / "app-icon.svg")
