"""Trang Local SEO (/local): hồ sơ Google Business Profile của dự án (một hoặc nhiều chi nhánh).

Tab Tổng quan (lượt xem, cuộc gọi, chỉ đường, click website, tin nhắn; xu hướng; từng chi nhánh) · Từ khóa (từ khóa
người dùng tìm rồi thấy hồ sơ, theo tháng) · Kiểm tra hồ sơ (thông tin còn thiếu / sai).
Khách hàng xem được; người sửa được mới gắn chi nhánh và bấm lấy số mới (API miễn phí).
"""
import io
from datetime import date, timedelta

from . import points as PT
from . import access as A
from . import ai_format as F
from . import gbp as G
from . import ui_theme as T

PERIODS = {28: "28 ngày", 90: "90 ngày", 365: "12 tháng"}
TABS = (("overview", "Tổng quan"), ("reviews", "Đánh giá"), ("posts", "Bài đăng"), ("profile", "Hồ sơ"))
OLD_TABS = {"branches": "overview", "keywords": "overview", "audit": "profile"}  # link cũ vẫn mở đúng chỗ
VIEW_COLORS = ["#2a78d6", "#8DB8EA", "#0E7C86", "#86C5C0"]  # Search ĐT / MT · Maps ĐT / MT
LOW_COLORS = ["#C2410C", "#E08B5B", "#D99A2B", "#A8805F", "#C9C6B8", "#E4E2D8"]
STAR_COLORS = {5: "#1E7C31", 4: "#7FB77E", 3: "#C9C6B8", 2: "#E08B5B", 1: "#C2410C"}  # xanh → xám (giữa) → đỏ
LEVELS = {"high": ("Cần sửa", "red", "error"), "medium": ("Nên sửa", "amber", "warning"),
          "info": ("Tham khảo", "blue", "info"), "ok": ("Ổn", "green", "check_circle")}


def _short(title: str) -> str:
    from .local_branches import short
    return short(title)


def _vn(d: date) -> str:
    return f"{d:%d/%m/%Y}"


def build_local_page(ui, cfg, connect, user, start: str = "") -> None:
    from nicegui import run

    from . import auth
    site = cfg.site_url
    ed = A.can_edit(user)
    cl = A.is_client(user)  # khách hàng: một màn kết quả Google Maps, không việc vận hành (trả lời, bài đăng, hồ sơ)
    right = T.page_header(ui, "storefront", "Local SEO",
                          "Hồ sơ Google Maps của các chi nhánh")
    right.classes("no-wrap").style("flex:none")  # hai nút không bị ép hẹp (chữ xuống dưới icon)
    start = OLD_TABS.get(start, start)
    state = {"tab": start if start in dict(TABS) else "overview", "loc": "all", "days": 28, "month": "", "q": ""}
    has_scope = not auth.missing_scopes(_scopes(cfg), (auth.BUSINESS_SCOPE,))

    async def fetch(btn) -> None:
        if not ed:
            return
        from contextlib import closing

        from . import db
        _pt = PT.take(ui, user, cfg, "local")
        if _pt is False:
            return
        btn.props("loading")

        def work():
            logs: list[str] = []
            with closing(db.connect(cfg.db_path)) as c:
                r = G.refresh(c, cfg, log=logs.append)
            return r, [m for m in logs if m.startswith("Không")]
        try:
            r, bad = await run.io_bound(work)
            ui.notify(f"Đã lấy số {r['locations']} hồ sơ" + (f" ({len(bad)} lỗi)" if bad else ""),
                      caption=" · ".join(bad)[:300] or None, type="warning" if bad else "positive",
                      position="bottom-right", classes="sr-toast", multi_line=True)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            PT.give_back(_pt)
            ui.notify("Không lấy được số Google Business Profile", caption=G.explain(e), type="negative",
                      position="bottom-right", classes="sr-toast", timeout=0, close_button="Đóng")
        btn.props(remove="loading")
        body.refresh()

    async def link_dialog() -> None:
        """Chọn các hồ sơ (chi nhánh) thuộc dự án này trong danh sách hồ sơ tài khoản Google của tool quản lý.

        Danh sách này là hồ sơ của MỌI khách hàng mà tài khoản Google chung của tool quản lý, nên chỉ Owner / Admin
        được xem và gắn (Member chỉ lấy số của hồ sơ đã gắn)."""
        if not A.is_admin(user):
            return
        with ui.dialog() as dlg, ui.card().style("border-radius:14px; width:620px; max-width:94vw"):
            ui.label("Gắn chi nhánh Google Business Profile").classes("text-base font-semibold")
            ui.label("Chọn chi nhánh của website này.") \
                .classes("text-xs muted")
            box = ui.column().classes("w-full gap-1 q-mt-sm")
            with box:
                T.spinner(ui, "Đang đọc danh sách hồ sơ từ Google…")
            foot = ui.row().classes("w-full justify-end gap-2 q-mt-sm")
        dlg.open()

        def load():
            return G.all_locations(G.Client(auth.get_credentials(cfg, need=(auth.BUSINESS_SCOPE,))))
        try:
            locs = await run.io_bound(load)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            box.clear()
            with box:
                ui.label(f"Không đọc được danh sách hồ sơ. {G.explain(e)}").classes("text-sm").style(
                    f"color:{T.RED}")
            with foot:
                ui.button("Đóng", on_click=dlg.close).props("flat no-caps")
            return
        with connect() as c:
            current = {x["name"] for x in G.linked(c)}
        from .projects import domain
        want = domain(site)
        box.clear()
        checks = {}
        with box:
            if not locs:
                ui.label("Chưa có hồ sơ nào. Thêm email của tool làm người quản lý hồ sơ trên Google Business Profile.").classes("text-sm muted")
            for x in locs:
                match = bool(x["website"]) and (domain(x["website"]) == want or domain(x["website"]).endswith("." + want))
                with ui.row().classes("items-start no-wrap gap-2 w-full sr-access-row"):
                    checks[x["name"]] = ui.checkbox(value=x["name"] in current or (not current and match)).props(
                        "dense")
                    with ui.column().classes("gap-0").style("min-width:0"):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.label(x["title"]).classes("text-sm font-semibold ellipsis")
                            if match:
                                T.status_chip(ui, "Cùng website", "green", "link")
                        ui.label(" · ".join(p for p in (x["address"], x["website"], x["account_name"]) if p)) \
                            .classes("text-xs muted ellipsis")

        def save():
            if not A.is_admin(user):  # chặn cả sự kiện giả từ trình duyệt
                return
            chosen = [x for x in locs if checks[x["name"]].value]
            with connect() as c:
                G.link(c, chosen, str(user))
            dlg.close()
            ui.notify(f"Đã gắn {len(chosen)} chi nhánh. Bấm “Lấy số mới” để lấy số lần đầu.", type="positive",
                      position="bottom-right", classes="sr-toast")
            body.refresh()
        with foot:
            ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
            ui.button("Lưu", on_click=save).props("unelevated no-caps color=primary")

    if ed:
        with right, ui.row().classes("items-center no-wrap gap-2"):
            if A.is_admin(user):
                ui.button("Chi nhánh", icon="storefront", on_click=link_dialog).props(
                    "outline no-caps color=grey-9").tooltip("Gắn / bỏ các hồ sơ Google Business Profile của dự án")
            ui.button("Giờ lễ", icon="event_busy", on_click=lambda: hours_dialog()).props(
                "outline no-caps color=grey-9").tooltip("Đặt giờ lễ / Tết (đóng cửa hoặc giờ khác) cho nhiều chi nhánh "
                                                        "một lần")
            b = ui.button("Lấy số mới", icon="refresh").props("unelevated no-caps color=primary")
            b.on_click(lambda _, b=b: fetch(b))
            b.tooltip("Lấy số mới từ Google (miễn phí)")

    @ui.refreshable
    def body():
        with connect() as c:
            locs = G.linked(c)
            last = G.complete_day(c)
        if not has_scope:
            T.empty_state(ui, "lock", "Tool chưa có quyền Google Business Profile",
                          "Owner kết nối lại Google và cấp quyền Google Business Profile ở Cài đặt tích hợp." if ed else "Số Local SEO sẽ có sau khi tool được cấp quyền.")
            return
        if not locs:
            T.empty_state(ui, "storefront", "Chưa gắn hồ sơ Google Business Profile",
                          "Bấm “Chi nhánh” để chọn hồ sơ của website này." if ed
                          else "Số Local SEO sẽ có sau khi gắn hồ sơ.")
            return
        names_all = [x["name"] for x in locs]
        names = names_all if state["loc"] == "all" else [state["loc"]]
        checks = {x["name"]: G.audit(x, site) for x in locs if x["name"] in names}
        from . import gbp_reviews as GR
        with connect() as c:
            revs = GR.rows(c, names)
        n_low = GR.stats(revs)["low_unanswered"]
        n_high = sum(1 for cs in checks.values() for c_ in cs if c_["level"] == "high")
        n_med = sum(1 for cs in checks.values() for c_ in cs if c_["level"] == "medium")
        if cl:
            if len(locs) > 1:
                with ui.row().classes("items-center gap-2 q-mb-sm"):
                    sel = ui.select({"all": f"Tất cả {len(locs)} chi nhánh",
                                     **{x["name"]: _short(x["title"]) for x in locs}},
                                    value=state["loc"], on_change=lambda e: (state.update(loc=e.value),
                                                                             body.refresh())).props(
                        "dense outlined options-dense").classes("sr-lc-sel")
                    sel.props['aria-label'] = "Chi nhánh"
            overview(locs, names, last, revs)
            return
        with ui.element("div").classes("w-full sr-lc-bar"):
            with ui.tabs(value=state["tab"], on_change=lambda e: pick(e.value)).props(
                    "align=left no-caps dense").classes("sr-tabs sr-bl-tabs sr-lc-tabs"):
                for k, label in TABS:
                    with ui.tab(k, label):
                        if k == "profile" and (n_high or n_med):
                            T.count_badge(ui, n_high + n_med, f"{n_high + n_med} mục cần sửa").classes("sr-tab-badge")
                        if k == "reviews" and n_low:
                            T.count_badge(ui, n_low, f"{n_low} đánh giá 1–3 sao chưa trả lời").classes(
                                "sr-tab-badge")
            with ui.row().classes("items-center gap-2 no-wrap sr-lc-tools"):
                if len(locs) > 1:
                    sel = ui.select({"all": f"Tất cả {len(locs)} chi nhánh",
                                     **{x["name"]: _short(x["title"]) for x in locs}},
                                    value=state["loc"], on_change=lambda e: (state.update(loc=e.value),
                                                                             body.refresh())).props(
                        "dense outlined options-dense").classes("sr-lc-sel")
                    sel.props['aria-label'] = "Chi nhánh"
                from .web_export import export_menu
                export_menu(ui, cfg, connect, f"local-seo_{date.today():%Y-%m-%d}",
                            lambda: make_xlsx(locs, names, last), label="Xuất Local SEO (Excel / Google Sheets)",
                            user=user, icon_only=True, category="local")
        with ui.tab_panels(value=state["tab"]).classes("w-full").props("animated=false") as panels:
            state["panels"] = panels
            with ui.tab_panel("overview").classes("q-px-none"):
                overview(locs, names, last)
            with ui.tab_panel("reviews").classes("q-px-none"):
                reviews_tab(locs, revs)
            with ui.tab_panel("posts").classes("q-px-none"):
                posts_tab(locs)
            with ui.tab_panel("profile").classes("q-px-none"):
                profile_tab(locs, checks)

    # ---------------------------------------------------------------- bài đăng Google Business Profile
    def public_base() -> str:
        """Địa chỉ tool đang được mở (để Google tải ảnh bài đăng qua link công khai)."""
        try:
            from nicegui import context
            req = context.client.request
            proto = req.headers.get("x-forwarded-proto") or req.url.scheme
            host = req.headers.get("x-forwarded-host") or req.headers.get("host") or req.url.netloc
            return f"{proto}://{host}"
        except Exception:  # noqa: BLE001
            return ""
    base_url = public_base()
    local_host = not base_url or any(x in base_url for x in ("localhost", "127.0.0.1", "[::1]", "0.0.0.0"))

    def _when(iso: str | None) -> str:
        from datetime import datetime
        if not iso:
            return ""
        try:
            return f"{datetime.fromisoformat(iso).astimezone():%H:%M %d/%m/%Y}"
        except ValueError:
            return iso

    @ui.refreshable
    def posts_tab(locs) -> None:
        """Bài đăng GBP: soạn (AI viết nháp, ảnh, nút kêu gọi), đăng ngay hoặc đặt lịch; tool tự đăng đúng giờ."""
        from . import gbp_posts as GP
        with connect() as c:
            posts = GP.all_posts(c)
        titles = {x["name"]: x["title"] for x in locs}
        with ui.row().classes("w-full items-center gap-2 q-mb-sm") as toolbar:
            ui.space()
            if ed:
                ui.button("Đọc từ Google", icon="sync", on_click=lambda: sync_posts(locs)).props(
                    "outline no-caps dense color=grey-9").tooltip(
                    "Cập nhật trạng thái bài và lấy bài đăng thẳng trên Google")
                ui.button("Viết bài mới", icon="edit_square", on_click=lambda: post_dialog(locs)).props(
                    "unelevated no-caps color=primary")
        if not posts:
            T.empty_state(ui, "campaign", "Chưa có bài đăng",
                          "Bấm “Viết bài mới” để soạn hoặc để AI viết." if ed else "Bài đăng của các chi nhánh sẽ hiện ở đây.")
            return
        if state["loc"] != "all":
            posts = [p for p in posts if state["loc"] in (p["locations"] or [])]

        def cat(p) -> str:
            if p["status"] in ("scheduled", "draft"):
                return p["status"]
            if p["status"] in ("partial", "failed") or any(r.get("state") == "REJECTED"
                                                            for r in (p["results"] or {}).values()):
                return "error"
            return "posted"
        cats = {"all": "Tất cả", "scheduled": "Đã lên lịch", "draft": "Nháp", "posted": "Đã đăng", "error": "Lỗi"}
        cnt = {k: (len(posts) if k == "all" else sum(1 for p in posts if cat(p) == k)) for k in cats}
        flt = state.setdefault("post_f", "all")
        if not cnt.get(flt):
            flt = state["post_f"] = "all"
        lim = state.setdefault("post_lim", {})
        with toolbar:
            tg = ui.toggle({k: f"{v} · {cnt[k]}" for k, v in cats.items() if k == "all" or cnt[k]}, value=flt,
                           on_change=lambda e: (state.update(post_f=e.value), posts_tab.refresh(locs))).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
            tg.props["aria-label"] = "Lọc bài đăng"
            tg.move(toolbar, 0)
        its = [p for p in posts if flt == "all" or cat(p) == flt]
        its.sort(key=lambda p: (0, p["scheduled_at"] or "") if p["status"] == "scheduled" else (1, ""))
        limit = lim.get(flt, 15)  # bài đọc về từ Google có thể hàng trăm: hiện dần
        if not its:
            ui.label("Không có bài nào").classes("text-sm muted q-py-md")
        with ui.element("div").classes("sr-gp-list"):
            for p in its[:limit]:
                post_row(p, titles, locs)
        if len(its) > limit:
            ui.button(f"Xem thêm ({len(its) - limit} bài nữa)", icon="expand_more",
                      on_click=lambda _, f_=flt, l_=limit: (lim.update({f_: l_ + 30}), posts_tab.refresh(locs))).props(
                "flat no-caps dense color=grey-9").classes("q-mt-xs")

    def post_row(p: dict, titles: dict, locs) -> None:
        from . import gbp_posts as GP
        st, tone = GP.STATUS.get(p["status"], ("", "grey"))
        with ui.element("div").classes("sr-gp-row"):
            if p["image"]:
                ui.image(f"/gbp-media/{p['image']}").classes("sr-gp-thumb")
            elif p.get("source") == "google" and p["image_url"]:
                ui.image(p["image_url"]).classes("sr-gp-thumb")
            else:
                with ui.element("div").classes("sr-gp-thumb empty"):
                    ui.icon("image", size="22px").props('aria-hidden="true"')
            with ui.column().classes("gap-1 col").style("min-width:0"):
                with ui.row().classes("items-center gap-2"):
                    T.pill(ui, st, tone)
                    T.tag(ui, GP.KINDS.get(p["kind"], p["kind"]), "grey")
                    if p.get("source") == "google":
                        T.tag(ui, "Đăng trên Google", "blue").tooltip("Team đăng thẳng trên Google; tool đọc về")
                    rej = [n for n, r in (p["results"] or {}).items() if r.get("state") == "REJECTED"]
                    if rej:
                        T.pill(ui, "Bị từ chối" + (f" · {len(rej)}" if len(p["locations"]) > 1 else ""), "red")
                    when = (f"đăng lúc {_when(p['scheduled_at'])}" if p["status"] == "scheduled" else
                            f"đã đăng {_when(p['posted_at'])}" if p["posted_at"] else
                            f"tạo {_when(p['created_at'])}")
                    ui.label(when).classes("text-xs muted")
                if p["title"]:
                    ui.label(p["title"]).classes("text-sm font-semibold")
                ui.label(p["summary"] or "(chưa có nội dung)").classes("text-sm sr-gp-sum")
                names_ = [titles.get(n, n.rsplit("/", 1)[-1]) for n in p["locations"]]
                ui.label(("Chi nhánh: " + ", ".join(names_)) if len(names_) <= 2 else
                         f"{len(names_)} chi nhánh").classes("text-xs muted").tooltip(", ".join(names_))
                for n, r in (p["results"] or {}).items():
                    if r.get("error"):
                        ui.label(f"{titles.get(n, n)}: {r['error']}").classes("text-xs text-negative")
                    elif r.get("state") == "REJECTED":
                        ui.label(f"{titles.get(n, n)}: Google từ chối bài (xem chính sách nội dung)").classes(
                            "text-xs text-negative")
            with ui.column().classes("gap-1 items-end"):
                links_ = [(titles.get(n, n), r["url"]) for n, r in (p["results"] or {}).items() if r.get("url")]
                if len(links_) == 1:
                    ui.button("Xem trên Google", icon="open_in_new", on_click=lambda _, u=links_[0][1]: ui.navigate.to(
                        u, new_tab=True)).props("flat no-caps dense color=primary")
                elif links_:
                    with ui.button("Xem trên Google", icon="open_in_new").props("flat no-caps dense color=primary"):
                        with ui.menu():
                            for t_, u in links_:
                                ui.menu_item(t_, on_click=lambda _, u=u: ui.navigate.to(u, new_tab=True))
                if ed and p["status"] in ("draft", "scheduled"):
                    ui.button("Sửa", icon="edit", on_click=lambda _, p=p: post_dialog(locs, p)).props(
                        "flat no-caps dense color=grey-9")
                if ed and p["status"] in ("partial", "failed"):
                    ui.button("Đăng lại phần lỗi", icon="refresh", on_click=lambda _, p=p: confirm_publish(
                        locs, p["id"])).props("flat no-caps dense color=primary")
                if ed and p["status"] != "posting" and p.get("source") != "google":
                    ui.button(icon="delete_outline", on_click=lambda _, p=p: delete_post(p)).props(
                        'flat round dense color=grey-7 aria-label="Xóa bài khỏi tool"').tooltip(
                        "Xóa khỏi tool" + (" (bài đã đăng vẫn còn trên Google)" if p["posted_at"] else ""))

    def delete_post(p: dict) -> None:
        from . import gbp_posts as GP
        with ui.dialog() as d, ui.card().style("width:420px; max-width:94vw; border-radius:14px"):
            ui.label("Xóa bài khỏi tool?").classes("text-lg font-semibold")
            ui.label("Bài đã đăng vẫn còn trên Google; xóa trên Google ở trang quản lý hồ sơ." if p["posted_at"] else
                     "Bài chưa đăng sẽ không được đăng nữa.").classes("text-sm muted")

            def go():
                with connect() as c:
                    GP.delete(c, p["id"])
                d.close()
                posts_tab.refresh(G_locs())
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Xóa", icon="delete", on_click=go).props("unelevated no-caps color=negative")
        d.on("hide", d.delete)
        d.open()

    def G_locs():
        with connect() as c:
            return G.linked(c)

    async def sync_posts(locs) -> None:
        from . import gbp_posts as GP
        from nicegui import run as run_

        def work():
            creds = auth.get_credentials(cfg, need=(auth.BUSINESS_SCOPE,))
            with connect() as c:
                return GP.import_from_google(c, locs, GP.Client(creds))
        try:
            r = await run_.io_bound(work)
            ui.notify(f"Đã đọc từ Google: {r['new']} bài mới, {r['updated']} bài đổi trạng thái"
                      if r["new"] or r["updated"] else "Không có bài mới hay thay đổi", type="positive",
                      position="bottom-right")
        except Exception as e:  # noqa: BLE001
            ui.notify(f"Chưa đọc được: {G.explain(e)}", type="negative", position="bottom-right", multi_line=True,
                      timeout=0, close_button="Đóng")
        posts_tab.refresh(locs)

    def confirm_publish(locs, pid: int) -> None:
        from . import gbp_posts as GP
        with connect() as c:
            p = GP.get(c, pid)
        if not p:
            return
        titles = {x["name"]: x["title"] for x in locs}
        with ui.dialog() as d, ui.card().style("width:460px; max-width:94vw; border-radius:14px"):
            ui.label("Đăng bài lên Google ngay?").classes("text-lg font-semibold")
            ui.label("Bài hiện công khai trên Google Maps / Search của: "
                     + ", ".join(titles.get(n, n) for n in p["locations"]) + ".").classes("text-sm")
            ui.label("Google không cho sửa bài qua tool sau khi đăng.").classes("text-xs muted")

            async def go():
                b_go.props("loading")
                await publish_now(locs, pid)
                d.close()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                b_go = ui.button("Đăng ngay", icon="send", on_click=go).props("unelevated no-caps color=primary")
        d.on("hide", d.delete)
        d.open()

    async def publish_now(locs, pid: int) -> None:
        from . import gbp_posts as GP
        from nicegui import run as run_

        def work():
            creds = auth.get_credentials(cfg, need=(auth.BUSINESS_SCOPE,))
            with connect() as c:
                return GP.publish(c, pid, G.linked(c), GP.Client(creds), G.explain)
        try:
            r = await run_.io_bound(work)
            ui.notify(f"Đã đăng lên {r['ok']}/{r['total']} chi nhánh", type="positive" if r["ok"] == r["total"]
                      else "warning", position="bottom-right", multi_line=True,
                      caption=" · ".join(v["error"] for v in r["results"].values() if v.get("error"))[:300] or None)
        except Exception as e:  # noqa: BLE001
            ui.notify(f"Chưa đăng được: {G.explain(e) if not isinstance(e, ValueError) else e}", type="negative",
                      position="bottom-right", multi_line=True, timeout=0, close_button="Đóng")
        posts_tab.refresh(locs)

    def post_dialog(locs, cur: dict | None = None) -> None:
        """Soạn / sửa bài: bên trái các ô (chi nhánh, loại, AI viết, nội dung, nút kêu gọi, ảnh), bên phải xem trước
        và đăng ngay / đặt lịch."""
        from datetime import datetime, timedelta, timezone

        from nicegui import run as run_

        from . import gbp_posts as GP
        cur = cur or {}
        f = {"locations": cur.get("locations") or [x["name"] for x in locs], "kind": cur.get("kind") or "STANDARD",
             "summary": cur.get("summary") or "", "cta": cur.get("cta") or "", "cta_url": cur.get("cta_url") or site,
             "title": cur.get("title") or "", "start": cur.get("start") or "", "end": cur.get("end") or "",
             "coupon": cur.get("coupon") or "", "terms": cur.get("terms") or "",
             "redeem_url": cur.get("redeem_url") or "", "image": cur.get("image") or "",
             "image_url": cur.get("image_url") or ""}
        when0 = (datetime.fromisoformat(cur["scheduled_at"]).astimezone() if cur.get("scheduled_at") else
                 (datetime.now().astimezone() + timedelta(days=1)).replace(hour=9, minute=0))
        with ui.dialog() as d, ui.card().classes("sr-gp-dlg").style(
                "width:1020px; max-width:96vw; max-height:92vh; border-radius:16px; padding:0"):
            with ui.row().classes("w-full items-center no-wrap sr-gp-head"):
                ui.label("Sửa bài đăng" if cur.get("id") else "Bài đăng mới").classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
            with ui.element("div").classes("sr-gp-body"):
                # ---- cột trái: soạn
                with ui.element("section").classes("sr-gp-col"):
                    if len(locs) > 1:
                        ui.select({x["name"]: x["title"] for x in locs}, value=f["locations"], multiple=True,
                                  label="Đăng lên chi nhánh", on_change=lambda e: f.update(locations=e.value or [])
                                  ).props("outlined dense options-dense max-values=20").classes("w-full sr-gp-locs")
                    else:
                        ui.label(f"Chi nhánh: {locs[0]['title']}").classes("text-sm")
                    ui.toggle(GP.KINDS, value=f["kind"], on_change=lambda e: (f.update(kind=e.value), extra.refresh(), cta_box.refresh(),
                                                                              preview.refresh())).props(
                        "unelevated no-caps toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                        "sr-seg")

                    @ui.refreshable
                    def extra() -> None:
                        if f["kind"] not in ("EVENT", "OFFER"):
                            return
                        lab = "ưu đãi" if f["kind"] == "OFFER" else "sự kiện"
                        ui.input(f"Tiêu đề {lab}", value=f["title"], on_change=lambda e: (
                            f.update(title=e.value), preview.refresh())).props("outlined dense").classes("w-full")
                        with ui.row().classes("w-full gap-2 no-wrap"):
                            ui.input("Bắt đầu", value=f["start"], on_change=lambda e: f.update(start=e.value)).props(
                                "outlined dense type=date stack-label").classes("col")
                            ui.input("Kết thúc", value=f["end"], on_change=lambda e: f.update(end=e.value)).props(
                                "outlined dense type=date stack-label").classes("col")
                        if f["kind"] == "OFFER":
                            with ui.row().classes("w-full gap-2 no-wrap"):
                                ui.input("Mã giảm giá (không bắt buộc)", value=f["coupon"],
                                         on_change=lambda e: f.update(coupon=e.value)).props(
                                    "outlined dense").classes("col")
                                ui.input("Link đổi ưu đãi (không bắt buộc)", value=f["redeem_url"],
                                         on_change=lambda e: f.update(redeem_url=e.value)).props(
                                    "outlined dense").classes("col")
                            ui.input("Điều khoản (không bắt buộc)", value=f["terms"],
                                     on_change=lambda e: f.update(terms=e.value)).props("outlined dense").classes(
                                "w-full")
                    extra()

                    # AI viết nháp
                    with ui.element("div").classes("sr-gp-ai"):
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("auto_awesome", size="16px").style("color:#7C3AED")
                            ui.label("AI viết nháp").classes("text-sm font-semibold").style("color:#4C1D95")
                        topic = ui.textarea(placeholder="Chủ đề / thông tin: ví dụ “Giảm 20% gọng kính titan đến 30/11, "
                                                        "đo mắt miễn phí, chi nhánh Tân Bình”").props(
                            "outlined dense autogrow").classes("w-full")

                        async def ai_write():
                            from . import ai_writer as AW
                            if not (topic.value or "").strip():
                                ui.notify("Nhập chủ đề / thông tin để AI viết", type="warning")
                                return
                            entry = PT.take(ui, user, cfg, "ai_gbp_post", detail=(topic.value or "")[:60])
                            if entry is False:
                                return
                            b_ai.props("loading")
                            try:
                                prov = AW.provider(cfg, "gbp_post")
                                biz = (locs[0]["title"] if len(f["locations"]) <= 1 else
                                       locs[0]["title"].split(" - ")[0])
                                kind, tp = f["kind"], topic.value

                                def work():
                                    from .spend import runner
                                    with runner(str(user)):
                                        return GP.draft(prov, biz, kind, tp, f["title"])
                                text.value = await run_.io_bound(work)
                            except Exception as e:  # noqa: BLE001
                                PT.give_back(entry)
                                ui.notify(f"AI chưa viết được: {str(e)[:200]}", type="negative",
                                          position="bottom-right")
                            b_ai.props(remove="loading")
                        b_ai = ui.button("AI viết" + PT.label(user, "ai_gbp_post"), icon="auto_awesome",
                                         on_click=ai_write).props("unelevated no-caps dense color=deep-purple-1 text-color=deep-purple-9").classes("sr-kg-aibtn")

                    text = ui.textarea("Nội dung bài", value=f["summary"]).props(
                        f"outlined autogrow counter maxlength={GP.MAX_CHARS}").classes("w-full")
                    text.on_value_change(lambda e: (f.update(summary=e.value or ""), preview.refresh()))
                    ui.label("Không ghi SĐT / link (Google hay từ chối)").classes("text-xs muted")

                    @ui.refreshable
                    def cta_box() -> None:
                        if f["kind"] == "OFFER":
                            return
                        with ui.row().classes("w-full gap-2 no-wrap"):
                            ui.select(GP.CTAS, value=f["cta"], label="Nút kêu gọi", on_change=lambda e: (
                                f.update(cta=e.value or ""), cta_box.refresh(), preview.refresh())).props(
                                "outlined dense options-dense").classes("w-48")
                            if f["cta"] and f["cta"] != "CALL":
                                ui.input("Link của nút", value=f["cta_url"], on_change=lambda e: f.update(
                                    cta_url=e.value)).props("outlined dense").classes("col")
                    cta_box()

                    # ảnh
                    @ui.refreshable
                    def image_box() -> None:
                        if f["image"]:
                            with ui.row().classes("items-center gap-2"):
                                ui.image(f"/gbp-media/{f['image']}").classes("sr-gp-thumb")
                                ui.button("Bỏ ảnh", icon="close", on_click=lambda: (
                                    f.update(image="", image_url=""), image_box.refresh(), preview.refresh())).props(
                                    "flat no-caps dense color=grey-8")
                            return

                        async def got(e):
                            try:
                                data = e.content.read() if hasattr(e, "content") else await e.file.read()
                                ctype = getattr(e, "type", "") or getattr(getattr(e, "file", None), "content_type", "")
                                name = GP.save_image(None, data, ctype)
                            except ValueError as ex:
                                ui.notify(str(ex), type="warning", position="bottom-right")
                                return
                            f.update(image=name, image_url=f"{base_url}/gbp-media/{name}" if base_url else "")
                            image_box.refresh()
                            preview.refresh()
                        ui.upload(label="Chọn ảnh (JPG / PNG, tối đa 5 MB)", auto_upload=True, max_files=1,
                                  on_upload=got).props('accept="image/jpeg,image/png" flat bordered').classes(
                            "w-full")
                        if local_host:
                            ui.label("Đang mở tool bằng localhost: Google không tải được ảnh. Mở tool bằng tên miền "
                                     "public (vd report…) rồi chèn ảnh.").classes("text-xs text-negative")
                    image_box()

                # ---- cột phải: xem trước + đăng
                with ui.element("section").classes("sr-gp-col side"):
                    ui.label("Xem trước").classes("sr-oi-h")

                    @ui.refreshable
                    def preview() -> None:
                        with ui.element("div").classes("sr-gp-prev"):
                            ui.label(locs[0]["title"] if locs else "").classes("text-xs muted")
                            if f["image"]:
                                ui.image(f"/gbp-media/{f['image']}").classes("sr-gp-prev-img")
                            if f["kind"] in ("EVENT", "OFFER") and f["title"]:
                                ui.label(f["title"]).classes("text-base font-semibold")
                            ui.label(f["summary"] or "Nội dung bài sẽ hiện ở đây…").classes("text-sm").style(
                                "white-space:pre-wrap" + ("" if f["summary"] else ";color:#8C8A7E"))
                            lab = ("Nhận ưu đãi" if f["kind"] == "OFFER" else GP.CTAS.get(f["cta"]) if f["cta"]
                                   else "")
                            if lab:
                                ui.label(lab).classes("sr-gp-cta")
                    preview()

                    ui.label("Đăng").classes("sr-oi-h q-mt-md")
                    with ui.row().classes("w-full gap-2 no-wrap"):
                        dd = ui.input("Ngày", value=f"{when0:%Y-%m-%d}").props(
                            "outlined dense type=date stack-label").classes("col")
                        tt = ui.input("Giờ", value=f"{when0:%H:%M}").props(
                            "outlined dense type=time stack-label").classes("w-28")

                    def collect() -> dict:
                        return {**f, "summary": text.value or ""}

                    def save_as(status: str) -> int | None:
                        data = collect()
                        if status == "scheduled":
                            try:
                                at = datetime.fromisoformat(f"{dd.value}T{tt.value}").astimezone()
                            except ValueError:
                                ui.notify("Chọn ngày giờ đăng", type="warning")
                                return None
                            if at < datetime.now().astimezone():
                                ui.notify("Giờ đăng đã qua: chọn giờ sau bây giờ hoặc bấm Đăng ngay",
                                          type="warning")
                                return None
                            data["scheduled_at"] = at.astimezone(timezone.utc).isoformat(timespec="seconds")
                        try:
                            with connect() as c:
                                return GP.save(c, data, str(user), cur.get("id"), status)
                        except ValueError as e:
                            ui.notify(str(e), type="warning", position="bottom-right")
                            return None

                    def do_draft():
                        if save_as("draft"):
                            ui.notify("Đã lưu nháp", type="positive", position="bottom-right")
                            d.close()
                            posts_tab.refresh(locs)

                    def do_schedule():
                        if save_as("scheduled"):
                            ui.notify(f"Đã đặt lịch đăng {dd.value} {tt.value}", type="positive",
                                      position="bottom-right")
                            d.close()
                            posts_tab.refresh(locs)

                    def do_now():
                        try:
                            GP.validate(collect())
                        except ValueError as e:
                            ui.notify(str(e), type="warning", position="bottom-right")
                            return
                        pid = save_as("draft")
                        if pid:
                            d.close()
                            confirm_publish(locs, pid)
                    ui.button("Đặt lịch đăng", icon="event", on_click=do_schedule).props(
                        "unelevated no-caps color=primary").classes("w-full")
                    ui.label("Máy tắt đúng giờ đó thì đăng bù khi bật lại").classes("text-xs muted")
                    with ui.row().classes("w-full gap-2 no-wrap q-mt-sm"):
                        ui.button("Đăng ngay", icon="send", on_click=do_now).props(
                            "outline no-caps color=grey-9").classes("col")
                        ui.button("Lưu nháp", icon="save", on_click=do_draft).props(
                            "flat no-caps color=grey-9").classes("col")
        d.on("hide", d.delete)
        d.open()

    def reviews_tab(locs, revs) -> None:
        """Đánh giá Google Maps: điểm, phân bố sao, theo tháng; danh sách (lọc chưa trả lời); trả lời + AI viết nháp."""
        from . import gbp_reviews as GR
        from . import table_kit as TK
        if not revs:
            T.empty_state(ui, "reviews", "Chưa có đánh giá nào",
                          "Đánh giá được lấy cùng lượt “Lấy số mới” (miễn phí)." if ed else "Chưa có đánh giá nào.")
            return
        stt = GR.stats(revs)
        titles = {x["name"]: x["title"] for x in locs}
        speed = GR.reply_speed(revs)
        allsp = speed.get("_all") or {}
        low_all = sum(stt["stars"].get(x, 0) for x in (1, 2, 3))
        rated = sum(stt["stars"].values())
        # việc cần làm: số chưa trả lời + nút trả lời ngay trên đầu tab
        todo_tone = "red" if stt["low_unanswered"] else "amber" if stt["unanswered"] else None
        with ui.element("div").classes("sr-card w-full sr-rv-todo" + (f" st-{todo_tone}" if todo_tone else "")):
            with ui.element("div").classes("sr-icon-bubble").style(
                    f"background:{T.TONES['red' if stt['low_unanswered'] else 'green'][0]}"):
                ui.icon("mark_chat_unread" if stt["unanswered"] else "task_alt", size="20px").style(
                    f"color:{T.TONES['red' if stt['low_unanswered'] else 'green'][1]}")
            with ui.column().classes("gap-0 col").style("min-width:0"):
                if stt["unanswered"]:
                    ui.label(f"{F.n(stt['unanswered'])} đánh giá chưa trả lời").classes("text-base font-semibold")
                    if stt["low_unanswered"]:
                        ui.label(f"{stt['low_unanswered']} đánh giá 1–3 sao, nên trả lời trước").classes(
                            "text-sm").style("color:#C2410C")
                else:
                    ui.label("Đã trả lời hết đánh giá").classes("text-base font-semibold")
            if ed:
                with ui.row().classes("items-center gap-2 sr-rv-acts"):
                    ui.button("Mẫu & giọng trả lời", icon="tune", on_click=lambda: voice_dialog()).props(
                        "outline no-caps color=grey-9")
                    if stt["unanswered"]:
                        ui.button("Trả lời hàng loạt", icon="quickreply",
                                  on_click=lambda: bulk_dialog(locs, revs)).props("unelevated no-caps color=primary")
        with T.kpi_row(ui):
            T.kpi(ui, "star", "Điểm trung bình", f"{stt['avg']:.1f}".replace(".", ",") if stt["avg"] else "–",
                  tone="lime", info=("Tính trên các đánh giá đã lấy về (Google Maps có thể làm tròn khác).",))
            T.kpi(ui, "reviews", "Đánh giá", F.n(stt["total"]), tone="blue")
            T.kpi(ui, "sentiment_dissatisfied", "Tỉ lệ 1–3 sao",
                  f"{low_all / rated * 100:.1f}%".replace(".", ",") if rated else "–",
                  tone="red", hint=f"{F.n(low_all)} đánh giá",
                  status="red" if rated and low_all / rated > 0.05 else None)
            med = allsp.get("median_days")
            T.kpi(ui, "schedule", "Trả lời sau",
                  ("trong ngày" if med is not None and med < 1 else f"{med:.0f} ngày".replace(".", ",")) if med is not None
                  else "–", tone="amber", status="amber" if med and med > 3 else None,
                  hint=(f"{allsp['rate'] * 100:.0f}% đã trả lời · 90 ngày" if allsp.get("rate") is not None
                        else ""),
                  info=("Số ngày trung vị từ lúc khách viết tới lúc được trả lời, tính trên đánh giá 90 ngày qua. Nên "
                        "trả lời trong 1–2 ngày, nhất là đánh giá thấp.",))
        with ui.element("div").classes("sr-bl-two w-full"):
            with T.section(ui, "Phân bố sao", "star_half",
                           f"1–3 sao: {F.n(low_all)} ({low_all / rated * 100:.1f}%)".replace(".", ",") if rated
                           else ""):
                T.donut(ui, [(f"{x} sao", stt["stars"].get(x, 0)) for x in (5, 4, 3, 2, 1)],
                        [STAR_COLORS[x] for x in (5, 4, 3, 2, 1)], "đánh giá", height=220)
            months = [m["month"] for m in stt["months"][-12:]]
            if len(months) >= 2:
                per = {m: [0, 0] for m in months}
                for r in revs:
                    m = (r["created"] or "")[:7]
                    if m in per and r["rating"]:
                        per[m][0] += 1
                        per[m][1] += 1 if r["rating"] <= 3 else 0
                with T.section(ui, "Đánh giá theo tháng", "bar_chart"):
                    ui.echart({"animation": False, "grid": {"left": 40, "right": 44, "top": 30, "bottom": 24},
                               "tooltip": {"trigger": "axis"},
                               "legend": {"top": 0, "right": 0, "icon": "roundRect", "itemWidth": 10,
                                          "itemHeight": 10, "textStyle": {"fontSize": 12, "color": "#4A4A40"}},
                               "xAxis": {"type": "category", "data": [f"{m[5:]}/{m[2:4]}" for m in months],
                                         "axisTick": {"show": False}, "axisLabel": {"color": "#8C8A7E"}},
                               "yAxis": [{"type": "value", "min": 0, "splitLine": {"lineStyle": {"color": "#EEECE4"}},
                                          "axisLabel": {"color": "#8C8A7E"}},
                                         {"type": "value", "min": 0, "splitLine": {"show": False},
                                          "axisLabel": {"color": "#C2410C", "formatter": "{value}%"}}],
                               "series": [{"type": "bar", "name": "Đánh giá mới", "barMaxWidth": 16,
                                           "itemStyle": {"color": "#BFD9C2", "borderRadius": [3, 3, 0, 0]},
                                           "data": [per[m][0] for m in months]},
                                          {"type": "line", "name": "% 1–3 sao", "yAxisIndex": 1, "symbolSize": 7,
                                           "symbol": "circle", "lineStyle": {"width": 2, "color": "#C2410C"},
                                           "itemStyle": {"color": "#C2410C"},
                                           "data": [round(per[m][1] / per[m][0] * 100, 1) if per[m][0] else None
                                                    for m in months]}]}
                              ).classes("w-full").style("height:240px")
        insight_card(locs, revs, titles)
        st = state.setdefault("rv", {"view": "todo" if stt["unanswered"] else "all", "kit": TK.new_state()})
        with T.section(ui, "Danh sách đánh giá", "reviews"):
            ui.toggle({"todo": f"Chưa trả lời · {stt['unanswered']}", "all": f"Tất cả · {stt['total']}"},
                      value=st["view"], on_change=lambda e: (st.update(view=e.value), body.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg q-mb-sm")
            shown = [r for r in revs if st["view"] == "all" or not r["reply"]]
            rows = [{"k": f"{r['location']}|{r['id']}", "loc": _short(titles.get(r["location"], "")), "author": r["author"],
                     "rating": r["rating"], "stars_l": f"{r['rating']} sao" if r["rating"] else "",
                     "stars": "★" * r["rating"] + "☆" * (5 - r["rating"]) if r["rating"] else "–",
                     "comment": r["comment"], "reply": r["reply"] or "", "date_iso": (r["created"] or "")[:10],
                     "date": _vn(date.fromisoformat(r["created"][:10])) if r["created"] else "–",
                     "state": "Đã trả lời" if r["reply"] else "Chưa trả lời"} for r in shown]
            cols = [{"name": "date", "label": "Ngày", "field": "date_iso", "align": "left", "sortable": True,
                     "width": 105},
                    {"name": "stars", "label": "Sao", "field": "rating", "align": "left", "sortable": True, "width": 95},
                    {"name": "comment", "label": "Đánh giá", "field": "comment", "align": "left"},
                    {"name": "reply", "label": "Trả lời của bạn", "field": "reply", "align": "left", "width": 280}]
            if len(locs) > 1:
                cols.insert(1, {"name": "loc", "label": "Chi nhánh", "field": "loc", "align": "left", "sortable": True,
                                "width": 150})
            if ed:
                cols.append({"name": "act", "label": "", "field": "k", "align": "right", "width": 100})
            TK.table(ui, columns=cols, rows=rows, row_key="k", st=st["kit"], noun="đánh giá", classes="sr-kw-tbl",
                     page_size=20, selectable=False,
                     filters=[("text", "Nội dung / người viết", ["comment", "author", "reply"]),
                              ("pick", "Số sao", "stars_l"), ("enum", "Trạng thái", "state"),
                              ("date", "Ngày", "date_iso")],
                     copy=[("Ngày", "date_iso"), ("Chi nhánh", "loc"), ("Người viết", "author"), ("Sao", "rating"),
                           ("Đánh giá", "comment"), ("Trả lời", "reply")], export="danh-gia-google-maps",
                     events={"reply": lambda e: reply_dialog(locs, revs, e.args)} if ed else None,
                     slots={
                         "body-cell-date": """<q-td :props="props">{{ props.row.date }}</q-td>""",
                         "body-cell-stars": """
                <q-td :props="props"><span :style="{color: props.row.rating >= 4 ? '#1E7C31' : props.row.rating === 3
                  ? '#B45309' : '#C2410C', letterSpacing: '1px'}">{{ props.row.stars }}</span></q-td>""",
                         "body-cell-comment": """
                <q-td :props="props"><div class="sr-bb-sub" style="font-size:12.5px;color:#1F221E">{{ props.row.author }}
                  </div><div style="white-space:normal; line-height:1.45">{{ props.row.comment || '(không có chữ)' }}
                  </div></q-td>""",
                         "body-cell-reply": """
                <q-td :props="props"><div v-if="props.row.reply" style="white-space:normal; line-height:1.45">
                  {{ props.row.reply }}</div><span v-else class="sr-bl-type k-lost">chưa trả lời</span></q-td>""",
                         "body-cell-act": """
                <q-td :props="props"><q-btn flat dense no-caps size="sm" color="primary"
                  :label="props.row.reply ? 'Sửa trả lời' : 'Trả lời'" @click.stop="$parent.$emit('reply', props.row.k)"/>
                </q-td>"""})

    # ---------------------------------------------------------------- AI phân tích đánh giá
    def insight_card(locs, revs, titles) -> None:
        from . import gbp_reviews as GR
        scope = state["loc"]
        with connect() as c:
            ins = GR.insight(c, scope)
        with T.section(ui, "Khách khen / chê gì", "auto_awesome", tone="purple"):
            if not ins:
                ui.label("Chưa phân tích lần nào." + (" Bấm “Phân tích bằng AI”." if ed else "")).classes(
                    "text-sm muted")
            else:
                from datetime import datetime
                if ins.get("summary"):
                    ui.label(ins["summary"]).classes("sr-st-sum w-full")
                with ui.expansion(f"Chi tiết: {len(ins.get('praise') or [])} điểm khen · {len(ins.get('complaints') or [])} điểm chê · {len(ins.get('actions') or [])} việc nên làm").props("dense switch-toggle-side").classes(
                        "w-full sr-ri-exp"):
                    with ui.element("div").classes("sr-bl-two w-full q-mt-sm"):
                        for key, label, tone, icon in (("praise", "Khách khen", "green", "thumb_up"),
                                                       ("complaints", "Khách chê", "red", "thumb_down")):
                            with ui.element("div").classes(f"sr-ri-box {tone}"):
                                with ui.row().classes("items-center gap-1 q-mb-xs"):
                                    ui.icon(icon, size="16px").props('aria-hidden="true"')
                                    ui.label(label).classes("text-sm font-semibold")
                                if not ins.get(key):
                                    ui.label("Không thấy chủ đề nổi bật.").classes("text-sm muted")
                                for x in ins.get(key) or []:
                                    with ui.element("div").classes("sr-ri-item"):
                                        with ui.row().classes("items-baseline gap-2 no-wrap"):
                                            ui.label(x["topic"]).classes("text-sm font-semibold col")
                                            if x.get("count"):
                                                ui.label(f"~{x['count']} đánh giá").classes("text-xs muted")
                                        if x.get("example"):
                                            ui.label(f"“{x['example']}”").classes("text-xs muted").style(
                                                "font-style:italic")
                                        if x.get("branches"):
                                            ui.label("Hay gặp ở: " + ", ".join(x["branches"])).classes("text-xs").style(
                                                "color:#C2410C")
                    if ins.get("actions"):
                        ui.label("Việc nên làm").classes("text-sm font-semibold q-mt-sm")
                        for a in ins["actions"]:
                            with ui.row().classes("items-start no-wrap gap-2"):
                                ui.icon("check_circle_outline", size="16px").style(f"color:{T.GREEN}; margin-top:2px")
                                ui.label(a).classes("text-sm")
                ui.label(f"AI đọc {ins.get('sample', 0)} đánh giá lúc "
                         f"{datetime.fromisoformat(ins['at']).astimezone():%H:%M %d/%m/%Y}").classes(
                    "text-xs muted q-mt-xs")
            if ed:
                b = ui.button(("Phân tích lại" if ins else "Phân tích bằng AI") + PT.label(user, "ai_review_insight"),
                              icon="auto_awesome").props("unelevated no-caps dense color=deep-purple-1 text-color=deep-purple-9").classes("sr-kg-aibtn q-mt-sm")
                b.on_click(lambda _, b=b: run_insight(b, locs, revs, titles, scope))

    async def run_insight(btn, locs, revs, titles, scope) -> None:
        from nicegui import run as run_

        from . import ai_writer as AW
        from . import gbp_reviews as GR
        entry = PT.take(ui, user, cfg, "ai_review_insight", detail=scope)
        if entry is False:
            return
        btn.props("loading")
        try:
            prov = AW.provider(cfg, "review_insight")
            biz = locs[0]["title"].split(" - ")[0] if locs else site

            def work():
                from .spend import runner
                with runner(str(user)):
                    data = GR.analyze(prov, biz, revs, titles)
                with connect() as c:
                    GR.save_insight(c, scope, data, str(user))
            await run_.io_bound(work)
            body.refresh()
        except Exception as e:  # noqa: BLE001
            PT.give_back(entry)
            ui.notify(f"AI chưa phân tích được: {str(e)[:200]}", type="negative", position="bottom-right")
            btn.props(remove="loading")

    # ---------------------------------------------------------------- mẫu & giọng trả lời
    def voice_dialog() -> None:
        from . import gbp_reviews as GR
        with connect() as c:
            v = GR.voice(c)
            tpls = [dict(t) for t in GR.templates(c)]
        labels = {"brand": ("Tên thương hiệu", "trống: lấy theo tên hồ sơ, vd “Mắt Kính Tâm Đức”"),
                  "self": ("Cửa hàng tự xưng", "trống: tự chọn theo loại (shop / nha khoa / cửa hàng…)"),
                  "customer": ("Gọi khách", "vd: anh/chị / quý khách / bạn"),
                  "tone": ("Tone giọng", "vd: thân thiện, chân thành, chuyên nghiệp"),
                  "contact": ("Kênh liên hệ khi khách không hài lòng", "vd: hotline 1900 xxxx hoặc Zalo OA Tâm Đức"),
                  "sign": ("Câu ký cuối (không bắt buộc)", "vd: — Mắt Kính Tâm Đức"),
                  "avoid": ("AI cần tránh", "vd: không hứa hoàn tiền; không nhắc đối thủ"),
                  "notes": ("Thông tin AI được nhắc", "vd: bảo hành gọng 12 tháng, đo mắt miễn phí")}
        stars_opt = {"5": "5 sao", "4": "4 sao", "3": "3 sao", "low": "1–2 sao", "all": "Mọi mức sao"}
        with ui.dialog() as d, ui.card().classes("sr-gp-dlg").style(
                "width:1040px; max-width:96vw; max-height:92vh; border-radius:16px; padding:0"):
            with ui.row().classes("w-full items-center no-wrap sr-gp-head"):
                with ui.column().classes("gap-0 col"):
                    ui.label("Mẫu & giọng trả lời đánh giá").classes("text-lg font-semibold")
                    ui.label("Dùng chung cả dự án").classes("text-xs muted")
                ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
            with ui.element("div").classes("sr-gp-body"):
                with ui.element("section").classes("sr-gp-col"):
                    ui.label("Giọng thương hiệu cho AI").classes("sr-oi-h")
                    fields = {}
                    for k_, (lab, ph) in labels.items():
                        w = (ui.textarea if k_ in ("tone", "avoid", "notes") else ui.input)(
                            lab, value=v.get(k_, ""), placeholder=ph).props(
                            "outlined dense stack-label" + (" autogrow" if k_ in ("tone", "avoid", "notes") else ""))
                        fields[k_] = w.classes("w-full")
                    with ui.element("div").classes("sr-gp-ai"):
                        ui.label("AI tự áp dụng theo số sao").classes("text-sm font-semibold")
                        for line in ("Xưng bằng tên thương hiệu hoặc shop / nha khoa…, không dùng “chúng tôi”.",
                                     "5★: cảm ơn đúng điều khách khen, mời quay lại; ngắn, ấm áp.",
                                     "4★: cảm ơn, ghi nhận điểm chưa trọn và nói sẽ cải thiện.",
                                     "3★: ghi nhận cụ thể điều chưa tốt, cách cải thiện, mời liên hệ.",
                                     "1–2★: xin lỗi trước, thấu hiểu đúng vấn đề, không cãi / đổ lỗi, không hứa bồi "
                                     "thường, mời liên hệ riêng qua kênh ở trên; không emoji.",
                                     "Theo cách khách viết: chỉ chấm sao → 1–2 câu; viết dài → trả lời từng ý chính; "
                                     "khách viết tiếng nước ngoài → trả lời đúng ngôn ngữ đó."):
                            ui.label("• " + line).classes("text-xs")
                with ui.element("section").classes("sr-gp-col side"):
                    with ui.row().classes("w-full items-center"):
                        ui.label("Mẫu trả lời").classes("sr-oi-h col")
                        ui.button("Khôi phục mặc định", icon="restart_alt", on_click=lambda: (
                            tpls.clear(), tpls.extend(dict(t) for t in GR.DEFAULT_TEMPLATES), tlist.refresh())).props(
                            "flat no-caps dense color=grey-8")
                    ui.label("Chèn được: {khach} · {xung} (shop / nha khoa…) · {thuong_hieu} · {chi_nhanh} · {lien_he}"
                             ).classes("text-xs muted")

                    @ui.refreshable
                    def tlist() -> None:
                        for i, t in enumerate(tpls):
                            with ui.element("div").classes("sr-bq-item"):
                                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                                    ui.input(value=t["name"], on_change=lambda e, t=t: t.update(name=e.value)).props(
                                        "dense borderless").classes("col text-sm font-semibold")
                                    ui.select(stars_opt, value=t["stars"],
                                              on_change=lambda e, t=t: t.update(stars=e.value)).props(
                                        "dense outlined options-dense").classes("w-32")
                                    ui.button(icon="delete_outline", on_click=lambda _, i=i: (
                                        tpls.pop(i), tlist.refresh())).props(
                                        'flat round dense size=sm color=grey-7 aria-label="Xóa mẫu"')
                                ui.textarea(value=t["text"], on_change=lambda e, t=t: t.update(text=e.value)).props(
                                    "outlined dense autogrow").classes("w-full")
                        ui.button("Thêm mẫu", icon="add", on_click=lambda: (
                            tpls.append({"id": "", "name": "Mẫu mới", "stars": "all", "text": ""}),
                            tlist.refresh())).props("outline no-caps dense color=grey-9")
                    tlist()

            def save():
                with connect() as c:
                    GR.save_voice(c, {k_: w.value for k_, w in fields.items()})
                    n = len(GR.save_templates(c, tpls))
                ui.notify(f"Đã lưu giọng trả lời và {n} mẫu", type="positive", position="bottom-right")
                d.close()
            with ui.row().classes("w-full items-center gap-2 sr-rq-foot"):
                ui.space()
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Lưu", icon="save", on_click=save).props("unelevated no-caps color=primary")
        d.on("hide", d.delete)
        d.open()

    # ---------------------------------------------------------------- trả lời hàng loạt
    def open_bulk() -> None:
        """Mở lại hàng chờ (từ chip ở góc màn hình): đọc lại đánh giá + nháp mới nhất."""
        from . import gbp_reviews as GR
        with connect() as c:
            locs_ = G.linked(c)
            names_ = [x["name"] for x in locs_] if state["loc"] == "all" else [state["loc"]]
            revs_ = GR.rows(c, names_)
        bulk_dialog(locs_, revs_)

    def bulk_dialog(locs, revs) -> None:
        """Hàng chờ trả lời: AI viết nháp (chạy nền trên máy chủ, có tiến độ, thu nhỏ được), team sửa / bỏ chọn, gửi
        một lượt (cũng chạy nền, có tiến độ). Nháp được lưu: đóng / thu nhỏ rồi mở lại vẫn còn."""
        from . import gbp_reviews as GR
        titles = {x["name"]: x["title"] for x in locs}
        items = GR.queue(revs)
        with connect() as c:
            saved = GR.drafts(c)
            v = GR.voice(c)
            tpls = GR.templates(c)
        rows = {}
        applied: set = set()  # câu AI viết nền đã đưa vào ô
        with ui.dialog().props("persistent") as d, ui.card().classes("sr-gp-dlg").style(
                "width:900px; max-width:96vw; max-height:92vh; border-radius:16px; padding:0"):
            with ui.row().classes("w-full items-center no-wrap sr-gp-head"):
                with ui.column().classes("gap-0 col"):
                    ui.label(f"Trả lời hàng loạt · {len(items)} đánh giá").classes("text-lg font-semibold")
                    ui.label("1–3 sao xếp trước · nháp tự lưu").classes("text-xs muted")
                ui.button("Thu nhỏ", icon="close_fullscreen", on_click=d.close).props(
                    "flat no-caps dense color=grey-8").tooltip("Ẩn xuống góc màn hình; việc đang chạy vẫn tiếp tục, "
                                                              "xong sẽ báo")
                ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
            with ui.row().classes("w-full items-center gap-2 q-px-md q-pt-sm"):
                b_ai = ui.button("AI viết nháp cho các câu còn trống" + PT.label(user, "ai_review_reply"),
                                 icon="auto_awesome").props("unelevated no-caps dense color=deep-purple-1 text-color=deep-purple-9").classes("sr-kg-aibtn")
                b_fill = ui.button("Điền mẫu cho câu còn trống", icon="text_snippet",
                                   on_click=lambda: fill_all()).props("flat no-caps dense color=grey-9").tooltip(
                    "Chọn mẫu hợp số sao cho các câu còn trống (miễn phí); sửa lại cho hợp từng khách")
            # chọn / bỏ chọn hàng loạt, xóa nội dung đã điền
            with ui.row().classes("w-full items-center gap-1 q-px-md sr-rq-sel"):
                ui.label("Chọn:").classes("text-xs muted")
                ui.button("Tất cả", on_click=lambda: select(lambda x: True)).props("flat no-caps dense size=sm")
                ui.button("Câu có nội dung", on_click=lambda: select(lambda x: bool((x["ta"].value or "").strip()))
                          ).props("flat no-caps dense size=sm")
                with ui.button("Theo số sao").props("flat no-caps dense size=sm icon-right=expand_more"):
                    with ui.menu():
                        for lab_, test_ in (("1–2 sao", lambda st_: 0 < st_ <= 2), ("3 sao", lambda st_: st_ == 3),
                                            ("4–5 sao", lambda st_: st_ >= 4)):
                            ui.menu_item(lab_, on_click=lambda _, t_=test_: select(
                                lambda x, t_=t_: t_(x["r"]["rating"] or 0)))
                ui.button("Bỏ chọn", on_click=lambda: select(lambda x: False)).props("flat no-caps dense size=sm")
                ui.space()
                b_clear = ui.button("Xóa nội dung các câu đã chọn", icon="backspace",
                                    on_click=lambda: confirm_clear()).props(
                    "flat no-caps dense size=sm color=negative").tooltip(
                    "Xóa câu trả lời đã điền (mẫu / AI / tự gõ) của các đánh giá đang tick, để điền lại")
            # tiến độ việc nền (viết nháp / gửi)
            with ui.element("div").classes("sr-rq-prog") as prog_box:
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    prog_l = ui.label("").classes("text-sm font-semibold col")
                    b_stop = ui.button("Dừng", icon="stop", on_click=lambda: stop_job()).props(
                        "flat no-caps dense color=negative")
                prog_bar = ui.linear_progress(value=0, show_value=False, size="8px", color="green-8").props(
                    "rounded track-color=grey-3")
                prog_sub = ui.label("").classes("text-xs muted")
            prog_box.set_visibility(False)
            with ui.element("div").classes("sr-bq-list"):
                for r in items:
                    k = (r["location"], r["id"])
                    with ui.element("div").classes("sr-bq-item") as box:
                        with ui.row().classes("w-full items-start no-wrap gap-2"):
                            cb = ui.checkbox(value=bool(saved.get(k))).props("dense")
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                with ui.row().classes("items-center gap-2"):
                                    color = "#1E7C31" if (r["rating"] or 0) >= 4 else "#B45309" if r["rating"] == 3 \
                                        else "#C2410C"
                                    ui.label("★" * (r["rating"] or 0)).style(f"color:{color}; letter-spacing:1px")
                                    ui.label(r["author"] or "khách").classes("text-sm font-semibold")
                                    ui.label(" · ".join(x for x in (titles.get(r["location"], ""),
                                                                    (r["created"] or "")[:10]) if x)).classes(
                                        "text-xs muted")
                                ui.label(r["comment"] or "(không có chữ)").classes("text-sm").style(
                                    "white-space:pre-wrap")
                                ta = ui.textarea(value=saved.get(k, ""), placeholder="Câu trả lời…").props(
                                    "outlined dense autogrow").classes("w-full q-mt-xs")
                                with ui.row().classes("items-center gap-1"):
                                    with ui.button("Mẫu", icon="text_snippet").props(
                                            "flat no-caps dense size=sm color=grey-8"):
                                        with ui.menu():
                                            for t_ in GR.templates_for(tpls, r["rating"] or 0):
                                                ui.menu_item(t_["name"], on_click=lambda _, t_=t_, r=r, ta=ta, k=k: (
                                                    ta.set_value(GR.fill(t_["text"], r, titles.get(r["location"], ""),
                                                                         v)), keep(k, ta)))
                                    b1 = ui.button("AI viết", icon="auto_awesome").props(
                                        "unelevated no-caps dense size=sm color=deep-purple-1 text-color=deep-purple-9")
                                    st_l = ui.label("").classes("text-xs")

                                def on_blur(_, k=k, ta=ta, cb=cb):
                                    with connect() as c:
                                        GR.save_draft(c, k[0], k[1], ta.value or "", str(user))
                                    if (ta.value or "").strip():
                                        cb.value = True
                                ta.on("blur", on_blur)
                        rows[k] = {"r": r, "ta": ta, "cb": cb, "st": st_l, "box": box}
                        b1.on_click(lambda _, k=k: start_draft([k]))
            with ui.row().classes("w-full items-center gap-2 sr-rq-foot"):
                sel_l = ui.label("").classes("text-xs muted col")
                ui.button("Thu nhỏ", icon="close_fullscreen", on_click=d.close).props("flat no-caps")
                b_send = ui.button("Gửi các câu đã chọn", icon="send", on_click=lambda: confirm_send()).props(
                    "unelevated no-caps color=primary")

        def select(pred) -> None:
            for x in rows.values():
                x["cb"].value = bool(pred(x))

        def confirm_clear() -> None:
            keys = [k for k, x in rows.items() if x["cb"].value and (x["ta"].value or "").strip()]
            if not keys:
                ui.notify("Chưa tick câu nào có nội dung để xóa", type="warning")
                return
            with ui.dialog() as cd, ui.card().style("width:420px; max-width:94vw; border-radius:14px"):
                ui.label(f"Xóa nội dung {len(keys)} câu trả lời đã điền?").classes("text-lg font-semibold")
                ui.label("Chỉ xóa nháp trong tool (chưa gửi lên Google), để điền lại bằng mẫu / AI.").classes(
                    "text-sm muted")

                def go():
                    with connect() as c:
                        for k in keys:
                            GR.save_draft(c, k[0], k[1], "", str(user))
                    for k in keys:
                        rows[k]["ta"].set_value("")
                        rows[k]["cb"].value = False
                        rows[k]["st"].text = ""
                    cd.close()
                    ui.notify(f"Đã xóa nội dung {len(keys)} câu", type="positive", position="bottom-right")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Hủy", on_click=cd.close).props("flat no-caps")
                    ui.button("Xóa", icon="backspace", on_click=go).props("unelevated no-caps color=negative")
            cd.on("hide", cd.delete)
            cd.open()

        def keep(k, ta):
            rows[k]["cb"].value = True
            with connect() as c:
                GR.save_draft(c, k[0], k[1], ta.value or "", str(user))

        def fill_all():
            n = 0
            for k, row_ in rows.items():
                if (row_["ta"].value or "").strip():
                    continue
                cand = GR.templates_for(tpls, row_["r"]["rating"] or 0)
                if not cand:
                    continue
                t_ = cand[n % len(cand)]  # xoay vòng các mẫu cùng nhóm để các câu không giống hệt nhau
                row_["ta"].set_value(GR.fill(t_["text"], row_["r"], titles.get(row_["r"]["location"], ""), v))
                keep(k, row_["ta"])
                n += 1
            ui.notify(f"Đã điền mẫu cho {n} câu; nên đọc lại và sửa cho hợp từng khách" if n else
                      "Không còn câu nào trống", type="positive" if n else "info", position="bottom-right")

        def start_draft(keys: list | None = None) -> None:
            if JOBS.get(job_key, {}).get("running"):
                ui.notify("Đang có việc chạy, đợi xong hoặc bấm Dừng", type="warning")
                return
            todo = [k for k in (keys or rows) if keys or not (rows[k]["ta"].value or "").strip()]
            if not todo:
                ui.notify("Mọi câu đều đã có nội dung", type="info")
                return
            start_job("draft", [rows[k]["r"] for k in todo], titles=titles, voice=v, force=bool(keys))

        def confirm_send():
            chosen = [(k, (x["ta"].value or "").strip()) for k, x in rows.items()
                      if x["cb"].value and (x["ta"].value or "").strip()]
            if not chosen:
                ui.notify("Chưa chọn câu trả lời nào có nội dung", type="warning")
                return
            if JOBS.get(job_key, {}).get("running"):
                ui.notify("Đang có việc chạy, đợi xong hoặc bấm Dừng", type="warning")
                return
            for k, text in chosen:  # lưu nháp lần cuối (ô vừa sửa chưa rời ra)
                with connect() as c:
                    GR.save_draft(c, k[0], k[1], text, str(user))
            with ui.dialog() as cd, ui.card().style("width:420px; max-width:94vw; border-radius:14px"):
                ui.label(f"Gửi {len(chosen)} câu trả lời lên Google Maps?").classes("text-lg font-semibold")
                ui.label("Hiện công khai ngay. Có thể thu nhỏ, xong sẽ báo.").classes("text-sm muted")

                def go():
                    cd.close()
                    start_job("send", [{**rows[k]["r"], "text": t} for k, t in chosen], locs=locs)
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Hủy", on_click=cd.close).props("flat no-caps")
                    ui.button("Gửi", icon="send", on_click=go).props("unelevated no-caps color=primary")
            cd.on("hide", cd.delete)
            cd.open()

        def tick():
            job = JOBS.get(job_key)
            n_sel = sum(1 for x in rows.values() if x["cb"].value and (x["ta"].value or "").strip())
            sel_l.text = f"Đã chọn {n_sel} câu để gửi · tick ô đầu mỗi đánh giá để chọn / bỏ"
            if not job:
                return
            for k, text in list(job.get("results", {}).items()):  # câu AI vừa viết: đưa vào ô (không đè ô đã sửa)
                k = tuple(k)
                if k in rows and (job["id"], k) not in applied:
                    applied.add((job["id"], k))
                    if job["kind"] == "draft" and (job.get("force") or not (rows[k]["ta"].value or "").strip()):
                        rows[k]["ta"].set_value(text)
                        rows[k]["cb"].value = True
            for k, msg in list(job.get("status", {}).items()):
                k = tuple(k)
                if k in rows:
                    ok = msg.startswith("✓")
                    rows[k]["st"].text = msg
                    rows[k]["st"].style(f"color:{'#1E7C31' if ok else '#C2410C' if msg.startswith('✗') else '#6B6A5E'}")
                    if job["kind"] == "send" and ok:
                        rows[k]["cb"].value = False
            running = job.get("running")
            prog_box.set_visibility(bool(running) or bool(job.get("finished") and not job.get("seen_in_dialog")))
            total = job["total"] or 1
            prog_bar.value = job["done"] / total
            verb = "AI đang viết nháp" if job["kind"] == "draft" else "Đang gửi lên Google Maps"
            if running:
                prog_l.text = f"{verb}: {job['done']}/{job['total']}"
                prog_sub.text = (f"Đang làm: {job.get('current') or '…'} · có thể bấm “Thu nhỏ”, xong sẽ báo" +
                                 (f" · {job['errors']} lỗi" if job["errors"] else ""))
            else:
                prog_l.text = (f"{'Đã viết' if job['kind'] == 'draft' else 'Đã gửi'} {job['ok']}/{job['total']}"
                               + (f" · {job['errors']} lỗi" if job["errors"] else "")
                               + (" · đã dừng" if job.get("stopped") else ""))
                prog_sub.text = ("Đọc lại, sửa câu chưa ổn rồi bấm “Gửi các câu đã chọn”." if job["kind"] == "draft"
                                 else "Câu gửi xong đã bỏ chọn; câu lỗi giữ lại để gửi lại.")
            b_stop.set_visibility(bool(running))
            for b_ in (b_ai, b_fill, b_send, b_clear):
                b_.set_enabled(not running)
        timer = ui.timer(0.8, tick)
        tick()
        b_ai.on_click(lambda: start_draft())

        def stop_job():
            if JOBS.get(job_key):
                JOBS[job_key]["stop"] = True

        def closed():
            timer.cancel()
            d.delete()
            job = JOBS.get(job_key)
            if job and not job.get("running"):
                job["seen_in_dialog"] = True
                body.refresh()
        d.on("hide", closed)
        d.open()

    # ---------------------------------------------------------------- việc nền: AI viết nháp / gửi trả lời
    job_key = str(cfg.db_path)

    def start_job(kind: str, its: list[dict], titles: dict | None = None, voice: dict | None = None,
                  locs: list | None = None, force: bool = False) -> None:
        from nicegui import background_tasks
        job = {"id": next(_JOB_IDS), "kind": kind, "total": len(its), "done": 0, "ok": 0, "errors": 0,
               "running": True, "stop": False, "results": {}, "status": {}, "current": "", "by": str(user),
               "finished": False, "force": force}
        JOBS[job_key] = job
        background_tasks.create(_run_job(job, its, cfg, user, titles or {}, voice or {}, locs or []),
                                name=f"review-{kind}")

    @ui.refreshable
    def job_chip() -> None:
        """Góc màn hình: việc nền đang chạy (tiến độ) / vừa xong (mở để kiểm tra)."""
        job = JOBS.get(job_key)
        if not job or job.get("seen_in_dialog") or job.get("by") != str(user):
            return
        verb = "AI viết nháp" if job["kind"] == "draft" else "Gửi trả lời"
        with ui.element("div").classes("sr-job-chip" + (" done" if not job["running"] else "")):
            if job["running"]:
                ui.spinner(size="18px", color="green-8")
                ui.label(f"{verb} {job['done']}/{job['total']}").classes("text-sm font-semibold")
            else:
                ui.icon("check_circle" if not job["errors"] else "error", size="18px").style(
                    f"color:{'#1E7C31' if not job['errors'] else '#C2410C'}")
                ui.label(f"{verb} xong {job['ok']}/{job['total']}" + (f" · {job['errors']} lỗi" if job["errors"]
                                                                       else "")).classes("text-sm font-semibold")
            ui.button("Mở", on_click=lambda: open_bulk()).props("flat no-caps dense color=primary")
            if not job["running"]:
                ui.button(icon="close", on_click=lambda: (job.update(seen_in_dialog=True), job_chip.refresh())).props(
                    'flat round dense size=sm color=grey-7 aria-label="Ẩn"')

    chip_state = {"sig": None}

    def chip_tick():
        job = JOBS.get(job_key)
        sig = (job["id"], job["done"], job["running"], job.get("seen_in_dialog")) if job else None
        if sig != chip_state["sig"]:
            if job and chip_state["sig"] and chip_state["sig"][2] and not job["running"] \
                    and job.get("by") == str(user):  # vừa xong
                ui.notify(("AI đã viết xong " if job["kind"] == "draft" else "Đã gửi xong ")
                          + f"{job['ok']}/{job['total']} câu trả lời" + (f" ({job['errors']} lỗi)" if job["errors"]
                                                                         else "") + ". Bấm “Mở” để kiểm tra.",
                          type="positive" if not job["errors"] else "warning", position="bottom-right",
                          timeout=8000)
                if job["kind"] == "send":
                    body.refresh()
            chip_state["sig"] = sig
            job_chip.refresh()
    with ui.element("div").classes("sr-job-wrap"):
        job_chip()
    ui.timer(1.5, chip_tick)

    # ---------------------------------------------------------------- giờ lễ nhiều chi nhánh
    def hours_dialog() -> None:
        from datetime import date as d_, timedelta as td

        from nicegui import run as run_
        with connect() as c:
            locs = G.linked(c)
        if not locs:
            ui.notify("Chưa gắn hồ sơ Google Business Profile", type="warning")
            return
        f = {"names": [x["name"] for x in locs], "mode": "closed"}
        with ui.dialog() as dlg, ui.card().classes("sr-gp-dlg").style(
                "width:760px; max-width:96vw; max-height:92vh; border-radius:16px; padding:0"):
            with ui.row().classes("w-full items-center no-wrap sr-gp-head"):
                with ui.column().classes("gap-0 col"):
                    ui.label("Giờ lễ / giờ đặc biệt").classes("text-lg font-semibold")
                    ui.label("Áp dụng cho các chi nhánh và ngày đã chọn").classes("text-xs muted")
                ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')
            with ui.element("div").classes("sr-gp-col"):
                if len(locs) > 1:
                    ui.select({x["name"]: x["title"] for x in locs}, value=f["names"], multiple=True,
                              label="Chi nhánh", on_change=lambda e: f.update(names=e.value or [])).props(
                        "outlined dense options-dense").classes("w-full sr-gp-locs")
                with ui.row().classes("w-full gap-2 no-wrap"):
                    s_in = ui.input("Từ ngày", value=(d_.today() + td(days=1)).isoformat()).props(
                        "outlined dense type=date stack-label").classes("col")
                    e_in = ui.input("Đến ngày", value=(d_.today() + td(days=1)).isoformat()).props(
                        "outlined dense type=date stack-label").classes("col")

                @ui.refreshable
                def times() -> None:
                    if f["mode"] != "hours":
                        return
                    with ui.row().classes("w-full gap-2 no-wrap"):
                        f["open"] = ui.input("Mở cửa", value="08:00").props("outlined dense type=time stack-label"
                                                                            ).classes("col")
                        f["close"] = ui.input("Đóng cửa", value="17:00").props("outlined dense type=time stack-label"
                                                                               ).classes("col")
                ui.toggle({"closed": "Đóng cửa", "hours": "Giờ khác", "remove": "Bỏ giờ đặc biệt"}, value=f["mode"],
                          on_change=lambda e: (f.update(mode=e.value), times.refresh())).props(
                    "unelevated no-caps toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                    "sr-seg")
                times()
                ui.label("Giờ đặc biệt sắp tới đang có").classes("sr-oi-h q-mt-sm")
                cur_rows = []
                for x in locs:
                    for p in G.special_periods(x.get("data") or {}):
                        cur_rows.append({"id": f"{x['name']}{p['start']}", "loc": x["title"],
                                         "days": p["start"][8:10] + "/" + p["start"][5:7]
                                         + ("" if p["end"] == p["start"] else
                                            f" – {p['end'][8:10]}/{p['end'][5:7]}"),
                                         "what": "Đóng cửa" if p["closed"] else f"{p['open']} – {p['close']}"})
                if cur_rows:
                    ui.table(columns=[{"name": "loc", "label": "Chi nhánh", "field": "loc", "align": "left"},
                                      {"name": "days", "label": "Ngày", "field": "days", "align": "left"},
                                      {"name": "what", "label": "Giờ", "field": "what", "align": "left"}],
                             rows=cur_rows, row_key="id", pagination=8).props("flat dense").classes(
                        "w-full sr-bl-table")
                else:
                    ui.label("Chưa có (theo lần lấy số gần nhất).").classes("text-sm muted")
                res = ui.column().classes("w-full gap-0")

                async def apply():
                    if not f["names"]:
                        ui.notify("Chọn ít nhất một chi nhánh", type="warning")
                        return
                    try:
                        G.merge_special([], s_in.value, e_in.value, f["mode"],
                                        f["open"].value if f.get("open") and f["mode"] == "hours" else "",
                                        f["close"].value if f.get("close") and f["mode"] == "hours" else "")
                    except ValueError as e:
                        ui.notify(str(e), type="warning")
                        return
                    b_apply.props("loading")
                    names, mode = list(f["names"]), f["mode"]
                    o_t = f["open"].value if mode == "hours" else ""
                    c_t = f["close"].value if mode == "hours" else ""
                    a_, b__ = s_in.value, e_in.value

                    def work():
                        client = G.Client(auth.get_credentials(cfg, need=(auth.BUSINESS_SCOPE,)))
                        with connect() as c:
                            return G.apply_special(c, client, names, a_, b__, mode, o_t, c_t)
                    try:
                        out = await run_.io_bound(work)
                    except Exception as e:  # noqa: BLE001
                        ui.notify(f"Chưa đặt được: {G.explain(e)}", type="negative", multi_line=True)
                        b_apply.props(remove="loading")
                        return
                    b_apply.props(remove="loading")
                    res.clear()
                    titles_ = {x["name"]: x["title"] for x in locs}
                    with res:
                        for n, err in out.items():
                            ui.label(f"{'✓' if not err else '✗'} {titles_.get(n, n)}"
                                     + (f": {err}" if err else "")).classes("text-sm").style(
                                f"color:{'#1E7C31' if not err else '#C2410C'}")
                    ok = sum(1 for v in out.values() if not v)
                    ui.notify(f"Đã cập nhật giờ cho {ok}/{len(out)} chi nhánh", type="positive" if ok == len(out)
                              else "warning", position="bottom-right")

                def confirm():
                    n = len(f["names"])
                    what = {"closed": "đóng cửa", "hours": "giờ khác", "remove": "bỏ giờ đặc biệt"}[f["mode"]]
                    with ui.dialog() as cd, ui.card().style("width:420px; max-width:94vw; border-radius:14px"):
                        ui.label(f"Cập nhật giờ cho {n} chi nhánh?").classes("text-lg font-semibold")
                        ui.label(f"{s_in.value} → {e_in.value}: {what}. Google hiện giờ mới trên Maps / Search sau vài "
                                 "phút.").classes("text-sm")

                        async def go():
                            cd.close()
                            await apply()
                        with ui.row().classes("w-full justify-end gap-2"):
                            ui.button("Hủy", on_click=cd.close).props("flat no-caps")
                            ui.button("Cập nhật", icon="check", on_click=go).props("unelevated no-caps color=primary")
                    cd.on("hide", cd.delete)
                    cd.open()
                with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                    ui.button("Đóng", on_click=dlg.close).props("flat no-caps")
                    b_apply = ui.button("Cập nhật lên Google", icon="cloud_upload", on_click=confirm).props(
                        "unelevated no-caps color=primary")
        dlg.on("hide", dlg.delete)
        dlg.open()

    def reply_dialog(locs, revs, key: str) -> None:
        """Trả lời một đánh giá: AI viết nháp (tùy chọn), sửa, gửi công khai lên Google Maps."""
        from nicegui import run as run_

        from . import gbp_reviews as GR
        loc_name, rid = key.split("|", 1)
        r = next((x for x in revs if x["location"] == loc_name and x["id"] == rid), None)
        loc = next((x for x in locs if x["name"] == loc_name), None)
        if not r or not loc:
            return
        with ui.dialog() as d, ui.card().style("width:620px; max-width:96vw; border-radius:14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label(f"Trả lời đánh giá {r['rating']}★ của {r['author'] or 'khách'}").classes(
                    "text-lg font-semibold col")
                ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
            ui.label(r["comment"] or "(không có chữ)").classes("text-sm q-pa-sm").style(
                "background:#F6F6F1; border-radius:8px; white-space:pre-wrap")
            note = ui.input("Ghi chú cho AI (không bắt buộc)",
                            placeholder="ví dụ: khách đã được đổi tròng miễn phí ngày 10/11").props(
                "dense outlined").classes("w-full q-mt-sm")
            box = ui.textarea("Câu trả lời", value=r["reply"] or "").props("outlined autogrow").classes("w-full")
            with connect() as c:
                v1, tpl1 = GR.voice(c), GR.templates(c)
            with ui.button("Chèn mẫu", icon="text_snippet").props("flat no-caps dense color=grey-8"):
                with ui.menu():
                    for t_ in GR.templates_for(tpl1, r["rating"] or 0):
                        ui.menu_item(t_["name"], on_click=lambda _, t_=t_: box.set_value(
                            GR.fill(t_["text"], r, loc["title"], v1)))

            async def ai_draft():
                from . import ai_writer as AW
                entry = PT.take(ui, user, cfg, "ai_review_reply", detail=r["author"] or "")
                if entry is False:
                    return
                b_ai.props("loading")
                try:
                    prov = AW.provider(cfg, "review_reply")
                    note_ = note.value or ""

                    def work():
                        from .spend import runner
                        with runner(str(user)):  # nhật ký chi phí AI ghi đúng người bấm (chạy trong luồng riêng)
                            return GR.draft(prov, loc["title"].split(" - ")[0], r, note_, v1, loc["title"])
                    box.value = await run_.io_bound(work)
                except Exception as e:  # noqa: BLE001
                    PT.give_back(entry)
                    ui.notify(f"AI chưa viết được: {str(e)[:200]}", type="negative", position="bottom-right")
                b_ai.props(remove="loading")

            async def send():
                text = (box.value or "").strip()
                if not text:
                    ui.notify("Câu trả lời đang trống", type="warning")
                    return
                b_send.props("loading")
                try:
                    def work():
                        creds = auth.get_credentials(cfg, need=(auth.BUSINESS_SCOPE,))
                        GR.Client(creds).reply(loc, rid, text)
                        with connect() as c:
                            GR.mark_replied(c, loc_name, rid, text)
                    await run_.io_bound(work)
                    d.close()
                    ui.notify("Đã gửi câu trả lời lên Google Maps", type="positive", position="bottom-right")
                    body.refresh()
                except Exception as e:  # noqa: BLE001
                    ui.notify(f"Chưa gửi được: {G.explain(e)}", type="negative", position="bottom-right",
                              multi_line=True, timeout=0, close_button="Đóng")
                b_send.props(remove="loading")
            with ui.row().classes("w-full items-center gap-2 q-mt-sm"):
                b_ai = ui.button("AI viết nháp" + PT.label(user, "ai_review_reply"), icon="auto_awesome",
                                 on_click=ai_draft).props("unelevated no-caps dense color=deep-purple-1 text-color=deep-purple-9").classes("sr-kg-aibtn")
                ui.space()
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                b_send = ui.button("Gửi lên Google Maps", icon="send", on_click=send).props("unelevated no-caps")
            ui.label("Gửi là hiện công khai ngay").classes("text-xs muted")
        d.on("hide", d.delete)
        d.open()

    def pick(v: str) -> None:
        state["tab"] = v
        if state.get("panels") is not None:
            state["panels"].set_value(v)
        ui.run_javascript(f"history.replaceState(null, '', '/local' + ('{v}' === 'overview' ? '' : '?tab={v}'))")

    def overview(locs, names, last, revs=None) -> None:
        """Một màn cho quản lý: hiệu suất (theo ngày, so kỳ trước), chi nhánh cần chú ý, đánh giá thấp đến từ đâu,
        bảng so sánh chi nhánh, nguồn lượt xem, từ khóa, bản đồ nhiệt sao thấp theo tháng."""
        from . import local_branches as LB
        if not last:
            T.empty_state(ui, "query_stats", "Chưa có số hiệu suất", "Bấm “Lấy số mới”." if ed else "")
            return
        end = date.fromisoformat(last)
        n = state["days"]
        start = end - timedelta(days=n - 1)
        p_end = start - timedelta(days=1)
        p_start = p_end - timedelta(days=n - 1)
        multi = state["loc"] == "all" and len(locs) > 1
        with connect() as c:
            now, prev = G.totals(c, names, start, end), G.totals(c, names, p_start, p_end)
            cur_d, prev_d = G.daily(c, names, start, end), G.daily(c, names, p_start, p_end)
            cmp_ = LB.compare(c, locs, site, n) if multi else None
            mat = LB.month_matrix(c, locs) if multi else None
            kw_months = G.keyword_months(c, names)
            kw = G.keyword_rows(c, names, kw_months[-1:]) if kw_months else []
        with ui.row().classes("items-center gap-2 q-mb-sm"):
            t_ = ui.toggle(PERIODS, value=n, on_change=lambda e: (state.update(days=e.value), body.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
            t_.props["aria-label"] = "Khoảng thời gian"
            ui.label(f"{_vn(start)} – {_vn(end)}").classes("text-xs muted").tooltip(
                f"So với {_vn(p_start)} – {_vn(p_end)} · Google trả số chậm vài ngày")

        # ---- hiệu suất theo ngày, kiểu Search Console
        days = [start + timedelta(days=i) for i in range(n)]
        pdays = [p_start + timedelta(days=i) for i in range(n)]

        def ser(key, ds, src):
            return [(src.get(d.isoformat()) or {}).get(key) for d in ds]
        defs = [("views", "Lượt xem hồ sơ", T.GREEN, "visibility",
                 "Số lần hồ sơ hiện trên Google Search và Google Maps"),
                ("CALL_CLICKS", "Cuộc gọi", T.BLUE, "call", "Số lần bấm nút gọi trên hồ sơ"),
                ("BUSINESS_DIRECTION_REQUESTS", "Chỉ đường", "#0E7C86", "directions", "Số lần bấm chỉ đường"),
                ("WEBSITE_CLICKS", "Click website", "#7C3AED", "open_in_new", "Số lần bấm vào website"),
                ("BUSINESS_CONVERSATIONS", "Tin nhắn", "#B7791F", "chat", "Số cuộc nhắn tin qua hồ sơ")]
        metrics = []
        for i, (k, lab, col, ic, info) in enumerate(defs):
            v, p = now.get(k, 0), prev.get(k, 0)
            if k == "BUSINESS_CONVERSATIONS" and not v and not p:
                continue  # không dùng tin nhắn: bỏ ô trống
            ch = (v - p) / p if p else None
            metrics.append({"key": k, "label": lab, "color": col, "icon": ic, "value": F.n(v),
                            "delta": F.delta_pct(ch, p), "good": T.good_of(ch),
                            "prev": F.vs_parts(v, p, label=f"{n} ngày trước") if p else None,
                            "data": ser(k, days, cur_d), "compare": ser(k, pdays, prev_d), "zero": True,
                            "on": i < 2, "info": (info,)})
        with T.section(ui, "Hiệu suất hồ sơ", "show_chart"):
            T.trend_chart(ui, metrics, [f"{d:%d/%m}" for d in days],
                          compare_labels=[f"{d:%d/%m}" for d in pdays])
        if cl and revs:  # khách hàng: điểm đánh giá gọn, không danh sách / việc trả lời
            from . import gbp_reviews as GR
            stt = GR.stats(revs)
            new = [r for r in revs if (r.get("created") or "")[:10] >= start.isoformat()]
            with T.kpi_row(ui):
                T.kpi(ui, "star", "Điểm trung bình", f"{stt['avg']:.1f}".replace(".", ",") if stt["avg"] else "–",
                      tone="lime")
                T.kpi(ui, "reviews", "Tổng đánh giá", F.n(stt["total"]), tone="blue")
                T.kpi(ui, "fiber_new", f"Đánh giá mới · {n} ngày", F.n(len(new)), tone="green")

        if multi and not cl:
            rows, rv = cmp_["rows"], cmp_["totals"]["reviews"]
            with ui.element("div").classes("sr-bl-two w-full"):
                # ---- cần chú ý
                attn = [r for r in rows if r["flags"]]
                with T.section(ui, "Chi nhánh cần chú ý", "priority_high"):
                    if not attn:
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("check_circle", size="20px").style(f"color:{T.GREEN}")
                            ui.label("Không chi nhánh nào bất thường trong kỳ").classes("text-sm")
                    with ui.element("div").classes("sr-lb-list"):
                        for r in attn[:5]:
                            worst = "red" if any(t == "red" for t, _ in r["flags"]) else "amber"
                            it = ui.element("div").classes(f"sr-lb-item st-{worst}").props(
                                "role=button tabindex=0")
                            it.on("click", lambda _, r=r: branch_dialog(r, locs))
                            with it:
                                ui.label(r["short"]).classes("sr-lb-name")
                                with ui.element("div").classes("sr-lb-flags"):
                                    for tone, text in r["flags"][:3]:
                                        with ui.element("span").classes(f"sr-lb-flag {tone}"):
                                            ui.label(text)
                                ui.icon("chevron_right", size="18px").classes("muted")
                    if len(attn) > 5:
                        ui.label(f"+{len(attn) - 5} chi nhánh khác: xem bảng so sánh").classes("text-xs muted q-mt-xs")
                # ---- đánh giá 1–3 sao đến từ đâu
                with T.section(ui, "Đánh giá 1–3 sao đến từ đâu", "sentiment_dissatisfied",
                               f"{rv['low']} / {F.n(rv['total'])} đánh giá mới · {_pct(rv['low_share'], 1)}"
                               if rv["total"] else ""):
                    by = sorted(((r["short"], r["reviews"]["low"]) for r in rows if r["reviews"]["low"]),
                                key=lambda x: -x[1])
                    if not by:
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("check_circle", size="20px").style(f"color:{T.GREEN}")
                            ui.label("Không có đánh giá 1–3 sao trong kỳ").classes("text-sm")
                    else:
                        items = by[:5] + ([("Khác", sum(v for _, v in by[5:]))] if len(by) > 5 else [])
                        T.donut(ui, items, LOW_COLORS, "đánh giá", height=220)
            branch_table(rows, rv, locs)

        with ui.element("div").classes("sr-bl-two w-full"):
            views = now.get("views") or 0
            with T.section(ui, "Khách thấy hồ sơ ở đâu", "devices"):
                if views:
                    with ui.element("div").classes("sr-src"):
                        with ui.element("div").classes("sr-src-donut"):
                            T.donut(ui, [(G.METRICS[k].replace("Xem trên Google ", "").replace(" · ", " "),
                                          now.get(k, 0)) for k in G.VIEWS], VIEW_COLORS, "lượt xem", height=200,
                                    legend=False)
                        with ui.element("div").classes("sr-src-list"):
                            for k, col in zip(G.VIEWS, VIEW_COLORS):
                                v, p = now.get(k, 0), prev.get(k, 0)
                                with ui.element("div").classes("sr-src-row"):
                                    ui.element("span").classes("sr-src-dot").style(f"background:{col}")
                                    ui.label(G.METRICS[k].replace("Xem trên Google ", "")).classes("sr-src-name")
                                    ui.label(F.n(v)).classes("num text-sm")
                                    ui.label(f"{v / views * 100:.0f}%").classes("num text-xs muted")
                                    if p:
                                        T.delta_badge(ui, f"{(v - p) / p * 100:+.0f}%", v >= p,
                                                      since=f"{n} ngày trước")
                                    else:
                                        ui.label("")
                else:
                    ui.label("Chưa có lượt xem trong kỳ").classes("text-sm muted")
            with T.section(ui, "Khách tìm gì", "manage_search",
                           f"Tháng {kw_months[-1][5:]}/{kw_months[-1][:4]}" if kw_months else ""):
                if not kw:
                    ui.label("Chưa có từ khóa (Google cho số theo tháng)").classes("text-sm muted")
                else:
                    with ui.element("div").classes("sr-lk-top"):
                        for r in kw[:8]:
                            v, p = r["value"] or 0, r["prev"]
                            with ui.element("div").classes("sr-lk-row"):
                                ui.label(r["keyword"]).classes("sr-lk-k")
                                ui.label(F.n(v) if v else f"< {r['below']}").classes("num text-sm")
                                if v and p:
                                    T.delta_badge(ui, f"{'+' if v >= p else '-'}{F.n(abs(v - p))}", v >= p)
                                else:
                                    ui.label("mới" if p is None else "").classes("text-xs muted")
                    ui.button(f"Xem tất cả {F.n(len(kw))} từ khóa", icon="list",
                              on_click=lambda: keywords_dialog(names)).props(
                        "flat no-caps dense color=primary").classes("q-mt-xs")
        if multi and cl:
            branch_table(cmp_["rows"], cmp_["totals"]["reviews"], locs)
        if multi and not cl:
            low_heatmap(mat)

    def branch_table(rows, rv, all_locs) -> None:
        # ---- bảng so sánh
        with T.section(ui, "So sánh chi nhánh", "table_chart", "" if cl else "Bấm dòng để xem chi tiết"):
            data = []
            for r in rows:
                dv, gv = _delta(r["views"], r["views_prev"])
                da, ga = _delta(r["actions"], r["actions_prev"])
                data.append({"id": r["name"], "branch": r["short"], "views": r["views"], "dv": dv, "gv": gv,
                             "actions": r["actions"], "da": da, "ga": ga,
                             "conv": round(r["conv"] * 100, 1) if r["conv"] is not None else None,
                             "rv": r["reviews"]["total"], "avg": r["reviews"]["avg"],
                             "low": round(r["reviews"]["low_share"] * 100, 1) if r["reviews"]["low_share"] is not None
                             else None, "low_n": r["reviews"]["low"], "lowu": r["low_unanswered"],
                             "reply": r["reply_days"], "posts": r["posts_30"], "audit": r["audit_high"]})
            base_low = (rv["low_share"] or 0) * 100
            cols = [
                {"name": "branch", "label": "Chi nhánh", "field": "branch", "align": "left", "sortable": True},
                {"name": "views", "label": "Lượt xem", "field": "views", "align": "right", "sortable": True},
                {"name": "actions", "label": "Hành động", "field": "actions", "align": "right", "sortable": True},
                {"name": "conv", "label": "Hành động / xem", "field": "conv", "align": "right", "sortable": True},
                {"name": "rv", "label": "Đánh giá mới", "field": "rv", "align": "right", "sortable": True},
                {"name": "avg", "label": "Điểm TB", "field": "avg", "align": "right", "sortable": True},
                {"name": "low", "label": "% 1–3 sao", "field": "low", "align": "right", "sortable": True},
                {"name": "lowu", "label": "Thấp chưa trả lời", "field": "lowu", "align": "right", "sortable": True},
                {"name": "reply", "label": "Trả lời sau (ngày)", "field": "reply", "align": "right", "sortable": True},
                {"name": "posts", "label": "Bài 30 ngày", "field": "posts", "align": "right", "sortable": True},
                {"name": "audit", "label": "Lỗi hồ sơ", "field": "audit", "align": "right", "sortable": True},
            ]
            if cl:  # khách hàng: kết quả, không số vận hành (chưa trả lời, tốc độ trả lời, bài đăng, lỗi hồ sơ)
                cols = [c_ for c_ in cols if c_["name"] in ("branch", "views", "actions", "conv", "rv", "avg")]
            tb = ui.table(columns=cols, rows=data, row_key="id", pagination=0).props("flat dense hide-bottom binary-state-sort").classes(
                "w-full sr-bl-table sr-oi-rows sr-lb-table")
            tb.add_slot("body-cell-views", """<q-td :props="props"><span class="num">
                {{ props.value.toLocaleString('vi-VN') }}</span> <span class="sr-lb-d" :class="props.row.gv">
                {{ props.row.dv }}</span></q-td>""")
            tb.add_slot("body-cell-actions", """<q-td :props="props"><span class="num">
                {{ props.value.toLocaleString('vi-VN') }}</span> <span class="sr-lb-d" :class="props.row.ga">
                {{ props.row.da }}</span></q-td>""")
            tb.add_slot("body-cell-conv", """<q-td :props="props">{{ props.value === null ? '–' :
                String(props.value).replace('.', ',') + '%' }}</q-td>""")
            tb.add_slot("body-cell-avg", """<q-td :props="props">{{ props.value === null ? '–' :
                String(props.value.toFixed(2)).replace('.', ',') }}</q-td>""")
            tb.add_slot("body-cell-low", f"""<q-td :props="props"><span v-if="props.value !== null" class="sr-lb-heat"
                :style="{{background: 'rgba(194,65,12,' + Math.min(0.85, props.value / Math.max({base_low * 2:.1f}, 8))
                + ')', color: props.value > {max(base_low * 1.4, 6):.1f} ? '#fff' : '#3A3D36'}}">
                {{{{ String(props.value).replace('.', ',') }}}}% · {{{{ props.row.low_n }}}}</span><span v-else>–</span>
                </q-td>""")
            tb.add_slot("body-cell-lowu", """<q-td :props="props"><span :style="props.value ? 'color:#C2410C;font-weight:700'
                : 'color:#8C8A7E'">{{ props.value }}</span></q-td>""")
            tb.add_slot("body-cell-reply", """<q-td :props="props"><span :style="props.value > 3 ? 'color:#8F5F14;font-weight:600'
                : ''">{{ props.value === null ? '–' : String(props.value).replace('.', ',') }}</span></q-td>""")
            tb.add_slot("body-cell-audit", """<q-td :props="props"><span :style="props.value ? 'color:#C2410C;font-weight:700'
                : 'color:#8C8A7E'">{{ props.value }}</span></q-td>""")
            by_name = {r["name"]: r for r in rows}
            if not cl:
                tb.on("rowClick", lambda e: branch_dialog(by_name[e.args[1]["id"]], all_locs)
                      if len(e.args) > 1 else None)


    def low_heatmap(mat) -> None:
        # ---- bản đồ nhiệt theo tháng
        with T.section(ui, "Tỉ lệ đánh giá 1–3 sao theo tháng", "grid_on", "Ô xám: không có đánh giá"):
            months = [f"{m[5:]}/{m[2:4]}" for m in mat["months"]]
            pts, maxv = [], 0.0
            for yi, row in enumerate(mat["rows"]):
                for xi, cell in enumerate(row["cells"]):
                    if cell["total"]:
                        v = round(cell["share"] * 100, 1)
                        maxv = max(maxv, v)
                        pts.append({"value": [xi, yi, v], "low": cell["low"], "total": cell["total"],
                                    "avg": cell["avg"]})
                    else:
                        pts.append({"value": [xi, yi, None], "itemStyle": {"color": "#F1F0EA"}})
            ui.echart({"animation": False, "grid": {"left": 90, "right": 20, "top": 10, "bottom": 50},
                       "tooltip": {":formatter": "function (p) { const d = p.data; if (d.value[2] === null) "
                                                "return p.name; return d.value[2] + '% (' + d.low + '/' + d.total + "
                                                "' đánh giá 1–3★) · TB ' + d.avg; }"},
                       "xAxis": {"type": "category", "data": months, "splitArea": {"show": False},
                                 "axisTick": {"show": False}, "axisLabel": {"color": "#8C8A7E", "fontSize": 11}},
                       "yAxis": {"type": "category", "data": [r["short"] for r in mat["rows"]],
                                 "axisTick": {"show": False}, "axisLabel": {"color": "#3A3D36", "fontSize": 12}},
                       "visualMap": {"min": 0, "max": max(10, round(maxv)), "calculable": False, "orient": "horizontal",
                                     "left": "center", "bottom": 0, "itemWidth": 10, "itemHeight": 120,
                                     "text": [f"{max(10, round(maxv))}%", "0%"], "textStyle": {"color": "#6B6A5E"},
                                     "inRange": {"color": ["#F6F1E7", "#F2C063", "#E08B5B", "#C2410C"]}},
                       "series": [{"type": "heatmap", "data": pts, "itemStyle": {"borderColor": "#fff", "borderWidth": 2,
                                                                                  "borderRadius": 3},
                                   "label": {"show": True, "fontSize": 10, "color": "#3A3D36",
                                             ":formatter": "function (p) { return p.data.value[2] === null ? '' : "
                                                          "Math.round(p.data.value[2]) + '%'; }"}}]}
                      ).classes("w-full").style(f"height:{max(220, 34 * len(mat['rows']) + 70)}px")


    def _pct(v, d=0) -> str:
        return "–" if v is None else f"{v * 100:.{d}f}%".replace(".", ",")

    def _delta(now_, prev_) -> tuple[str, str]:
        if not prev_:
            return "", "grey"
        d = (now_ - prev_) / prev_
        return f"{'+' if d >= 0 else '−'}{abs(d) * 100:.0f}%", "green" if d >= 0.02 else "red" if d <= -0.02 else "grey"

    def branch_dialog(r: dict, all_locs) -> None:
        """Chi tiết một chi nhánh: hiệu suất (tuần), phân bố sao, đánh giá thấp gần đây, điều khách chê ở chi nhánh
        này (từ AI phân tích), việc cần làm."""
        from . import gbp_reviews as GR
        from . import local_branches as LB
        n = state["days"]
        with connect() as c:
            last = G.complete_day(c)
            end = date.fromisoformat(last) if last else date.today()
            ser = G.series(c, [r["name"]], end - timedelta(days=n - 1), end, "month" if n > 120 else "week")
            lows = LB.recent_low(c, r["name"])
            ins = GR.insight(c, "all")
        rv = r["reviews"]
        with ui.dialog() as d, ui.card().classes("sr-gp-dlg").style(
                "width:1000px; max-width:96vw; max-height:92vh; border-radius:16px; padding:0"):
            with ui.row().classes("w-full items-center no-wrap sr-gp-head"):
                with ui.column().classes("gap-0 col"):
                    ui.label(r["title"]).classes("text-lg font-semibold")
                    ui.label(f"{n} ngày gần nhất").classes("text-xs muted")
                ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
            with ui.element("div").classes("sr-gp-col"):
                with T.kpi_row(ui):
                    dv, gv = _delta(r["views"], r["views_prev"])
                    T.kpi(ui, "visibility", "Lượt xem", F.n(r["views"]), delta=dv, good=(gv == "green") if dv else None,
                          tone="green")
                    da, ga = _delta(r["actions"], r["actions_prev"])
                    T.kpi(ui, "touch_app", "Hành động", F.n(r["actions"]), delta=da,
                          good=(ga == "green") if da else None, tone="blue",
                          hint=f"gọi {F.n(r['calls'])} · chỉ đường {F.n(r['directions'])} · web {F.n(r['web'])}")
                    T.kpi(ui, "reviews", "Đánh giá mới", F.n(rv["total"]), tone="lime",
                          hint=(f"TB {rv['avg']:.2f}".replace(".", ",") if rv["avg"] else "")
                          + f" · tổng {F.n(r['life']['total'])}")
                    T.kpi(ui, "sentiment_dissatisfied", "1–3 sao", _pct(rv["low_share"], 1), tone="red",
                          status="red" if (rv["low_share"] or 0) > 0.05 else None,
                          hint=f"{rv['low']} đánh giá · {_pct(r['low_part'])} tổng hệ thống")
                    T.kpi(ui, "mark_chat_unread", "Thấp chưa trả lời", F.n(r["low_unanswered"]), tone="red",
                          status="red" if r["low_unanswered"] else None,
                          hint=(f"trả lời sau ~{r['reply_days']:.0f} ngày".replace(".", ",")
                                if r["reply_days"] is not None else ""))
                if r["flags"]:
                    with ui.row().classes("gap-2"):
                        for tone, text in r["flags"]:
                            with ui.row().classes("items-center no-wrap gap-1 sr-lb-flag"):
                                ui.element("span").classes(f"sr-lb-dot {tone}")
                                ui.label(text).classes("text-sm")
                with ui.element("div").classes("sr-bl-two w-full"):
                    labels = [(f"{p[8:10]}/{p[5:7]}" if len(p) == 10 else f"{p[5:7]}/{p[2:4]}")
                              for p in [x_["period"] for x_ in ser]]
                    with T.section(ui, "Lượt xem và hành động", "show_chart"):
                        ui.echart({"animation": False, "grid": {"left": 44, "right": 44, "top": 30, "bottom": 26},
                                   "legend": {"top": 0, "right": 0, "icon": "roundRect", "itemWidth": 10,
                                              "itemHeight": 10, "textStyle": {"fontSize": 11}},
                                   "tooltip": {"trigger": "axis"},
                                   "xAxis": {"type": "category", "data": labels, "axisTick": {"show": False},
                                             "axisLabel": {"color": "#8C8A7E", "fontSize": 11}},
                                   "yAxis": [{"type": "value", "splitLine": {"lineStyle": {"color": "#EEECE4"}},
                                              "axisLabel": {"color": "#8C8A7E", "fontSize": 11}},
                                             {"type": "value", "splitLine": {"show": False},
                                              "axisLabel": {"color": "#8C8A7E", "fontSize": 11}}],
                                   "series": [{"type": "bar", "name": "Lượt xem", "barMaxWidth": 18,
                                               "itemStyle": {"color": "#BFD9C2", "borderRadius": [3, 3, 0, 0]},
                                               "data": [x_["views"] for x_ in ser]},
                                              {"type": "line", "name": "Hành động", "yAxisIndex": 1, "symbolSize": 6,
                                               "lineStyle": {"width": 2, "color": "#2a78d6"},
                                               "itemStyle": {"color": "#2a78d6"},
                                               "data": [x_["CALL_CLICKS"] + x_["BUSINESS_DIRECTION_REQUESTS"]
                                                        + x_["WEBSITE_CLICKS"] + x_["BUSINESS_CONVERSATIONS"]
                                                        for x_ in ser]}]}).classes("w-full").style("height:220px")
                    with T.section(ui, "Phân bố sao trong kỳ", "star_half"):
                        tot_ = rv["total"] or 1
                        for st in (5, 4, 3, 2, 1):
                            k_ = rv["stars"][st]
                            with ui.row().classes("w-full items-center no-wrap gap-2"):
                                ui.label(f"{st} sao").classes("text-sm").style("width:44px")
                                with ui.element("div").style("flex:1; height:8px; background:#EEECE4; "
                                                             "border-radius:4px"):
                                    ui.element("div").style(f"width:{k_ / tot_ * 100:.0f}%; height:8px; "
                                                            f"border-radius:4px; background:{STAR_COLORS[st]}")
                                ui.label(f"{k_} · {k_ / tot_ * 100:.0f}%".replace(".", ",")).classes(
                                    "text-sm num").style("width:70px; text-align:right")
                with ui.element("div").classes("sr-bl-two w-full"):
                    with T.section(ui, "Đánh giá 1–3 sao gần đây", "reviews"):
                        if not lows:
                            ui.label("Không có.").classes("text-sm muted")
                        for x_ in lows:
                            with ui.element("div").classes("sr-ri-item"):
                                with ui.row().classes("items-center gap-2"):
                                    ui.label("★" * (x_["rating"] or 0)).style("color:#C2410C")
                                    ui.label(x_["author"] or "khách").classes("text-sm font-semibold")
                                    ui.label((x_["created"] or "")[:10]).classes("text-xs muted")
                                    T.pill(ui, "Đã trả lời" if x_["reply"] else "Chưa trả lời",
                                           "green" if x_["reply"] else "red")
                                ui.label(x_["comment"] or "(không có chữ)").classes("text-sm").style(
                                    "white-space:pre-wrap")
                    with T.section(ui, "Khách hay chê ở chi nhánh này", "auto_awesome", "Theo AI phân tích",
                                   tone="purple"):
                        mine = [x_ for x_ in (ins or {}).get("complaints") or []
                                if any(r["short"].lower() in b.lower() or b.lower() in r["title"].lower()
                                       for b in x_.get("branches") or [])]
                        if not ins:
                            ui.label("Chưa chạy AI phân tích đánh giá.").classes("text-sm muted")
                        elif not mine:
                            ui.label("AI không thấy chủ đề bị chê nổi bật ở chi nhánh này.").classes("text-sm muted")
                        for x_ in mine:
                            with ui.element("div").classes("sr-ri-item"):
                                ui.label(x_["topic"]).classes("text-sm font-semibold")
                                if x_.get("example"):
                                    ui.label(f"“{x_['example']}”").classes("text-xs muted").style("font-style:italic")
                with ui.row().classes("w-full justify-end gap-2"):
                    def go_reviews():
                        state.update(loc=r["name"], tab="reviews")
                        d.close()
                        body.refresh()
                    ui.button("Xem đánh giá của chi nhánh này", icon="reviews", on_click=go_reviews).props(
                        "unelevated no-caps color=primary")
        d.on("hide", d.delete)
        d.open()

    def keywords_dialog(names) -> None:
        with ui.dialog() as d, ui.card().classes("sr-gp-dlg").style(
                "width:900px; max-width:96vw; max-height:92vh; border-radius:16px; padding:0"):
            with ui.row().classes("w-full items-center no-wrap sr-gp-head"):
                ui.label("Từ khóa tìm thấy hồ sơ").classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
            with ui.element("div").classes("sr-gp-col"):
                keywords_body(names)
        d.on("hide", d.delete)
        d.open()

    @ui.refreshable
    def keywords_body(names) -> None:
        with connect() as c:
            months = G.keyword_months(c, names)
        if not months:
            ui.label("Chưa có từ khóa (Google cho số theo tháng, sau khi tháng kết thúc).").classes(
                "text-sm muted q-py-md")
            return
        opts = {"12": "12 tháng gần nhất", "3": "3 tháng gần nhất",
                **{m: f"Tháng {m[5:]}/{m[:4]}" for m in reversed(months)}}
        if state["month"] not in opts:
            state["month"] = months[-1]
        sel = state["month"]
        chosen = months[-int(sel):] if sel in ("12", "3") else [sel]
        with connect() as c:
            rows = G.keyword_rows(c, names, chosen)
        if True:
            with ui.row().classes("w-full items-center gap-2"):
                ui.select(opts, value=sel, on_change=lambda e: (state.update(month=e.value), keywords_body.refresh(names))).props(
                    "dense outlined options-dense").classes("w-56")
                ui.label(f"{len(rows)} từ khóa").classes("text-xs muted")
                ui.space()
                ui.input(placeholder="Tìm…", value=state["q"],
                         on_change=lambda e: (state.update(q=e.value or ""), table.refresh())).props(
                    "dense outlined clearable debounce=300").classes("w-56")

            @ui.refreshable
            def table():
                q = (state["q"] or "").strip().lower()
                data = []
                for i, r in enumerate(x for x in rows if not q or q in x["keyword"]):
                    v = r["value"] or 0
                    p = r["prev"]
                    data.append({"id": i, "keyword": r["keyword"],
                                 "value": F.n(v) if v else f"dưới {r['below']}", "v": v or 0,
                                 "prev": (F.n(p) if p else (f"dưới {r['prev_below']}" if r["prev_below"] else "–"))
                                 if p is not None else "mới",
                                 "change": (v - p) if v and p else None})
                cols = [{"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
                        {"name": "value", "label": "Lượt xem", "field": "value", "align": "right", "sortable": True,
                         ":sort": "(a, b, rowA, rowB) => rowA.v - rowB.v", "headerStyle": "width:130px"},
                        {"name": "prev", "label": "Kỳ trước", "field": "prev", "align": "right",
                         "headerStyle": "width:130px"},
                        {"name": "change", "label": "Thay đổi", "field": "change", "align": "right", "sortable": True,
                         "headerStyle": "width:110px"}]
                tb = ui.table(columns=cols, rows=data, row_key="id", pagination=25).props(
                    "flat dense binary-state-sort").classes("w-full")
                tb.add_slot("body-cell-change", """
                    <q-td :props="props" class="text-right">
                      <span v-if="props.value" class="num" :style="{color: props.value > 0 ? '#1E7C31' : '#C2410C',
                        fontWeight: 600}">{{ props.value > 0 ? '▲' : '▼' }} {{ Math.abs(props.value) }}</span>
                      <span v-else class="muted">–</span></q-td>""")
            table()

    def profile_tab(locs, checks) -> None:
        """Kiểm tra hồ sơ: các mục cần sửa gom lại (lỗi chung của nhiều chi nhánh chỉ hiện một lần), rồi bảng chi
        nhánh × mục kiểm tra, mỗi ô một dấu; rê chuột xem chi tiết."""
        shown = [x for x in locs if x["name"] in checks]
        if not shown:
            T.empty_state(ui, "fact_check", "Chưa có hồ sơ để kiểm tra")
            return
        is_bad = lambda c_: c_["level"] in ("high", "medium")  # noqa: E731
        issues: dict[str, dict] = {}
        for x in shown:
            for c_ in checks[x["name"]]:
                if is_bad(c_):
                    issues.setdefault(c_["key"], {"c": c_, "locs": []})["locs"].append(x)
        n_ok = sum(1 for x in shown if not any(is_bad(c_) for c_ in checks[x["name"]]))
        maps = {x["name"]: (x["data"].get("metadata") or {}).get("mapsUri") for x in shown}
        with T.section(ui, "Cần sửa", "build",
                       f"{sum(len(g['locs']) for g in issues.values())} chỗ cần sửa · {n_ok}/{len(shown)} hồ sơ đầy đủ"
                       if len(shown) > 1 else ""):
            if not issues:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("check_circle", size="20px").style(f"color:{T.GREEN}")
                    ui.label("Hồ sơ đầy đủ, không có mục cần sửa").classes("text-sm")
            for g in sorted(issues.values(), key=lambda g: (g["c"]["level"] != "high", -len(g["locs"]))):
                c_ = g["c"]
                label, tone, icon = LEVELS[c_["level"]]
                with ui.element("div").classes("sr-pf-issue"):
                    T.pill(ui, label, tone, icon)
                    with ui.column().classes("gap-1 col").style("min-width:0"):
                        ui.label(c_["title"]).classes("text-sm font-semibold")
                        ui.label(c_["detail"]).classes("text-sm muted")
                        with ui.row().classes("items-center gap-1"):
                            ui.label("Cả " + str(len(g["locs"])) + " chi nhánh:" if len(g["locs"]) == len(shown) > 1
                                     else "Ở:").classes("text-xs muted")
                            for x in g["locs"]:
                                u = maps.get(x["name"])
                                if u:
                                    ui.link(_short(x["title"]), u, new_tab=True).classes("sr-pf-loc").tooltip(
                                        "Mở hồ sơ trên Google Maps")
                                else:
                                    ui.label(_short(x["title"])).classes("sr-pf-loc")
        keys = [c_["key"] for c_ in checks[shown[0]["name"]]]
        names_ = {c_["key"]: c_["title"] for x in shown for c_ in checks[x["name"]]}
        icons = {"ok": ("check_circle", "#1E7C31"), "info": ("info", "#5B7FA8"), "medium": ("warning", "#B7791F"),
                 "high": ("error", "#C2410C")}
        with T.section(ui, "Mục kiểm tra theo chi nhánh", "fact_check", "Rê chuột vào ô để xem chi tiết"):
            with ui.element("div").classes("sr-pf-wrap"):
                with ui.element("div").classes("sr-pf-grid").style(f"--n:{len(keys)}"):
                    ui.element("div").classes("sr-pf-h first")
                    for k in keys:
                        ui.label(names_.get(k, k)).classes("sr-pf-h")
                    for x in shown:
                        cs = {c_["key"]: c_ for c_ in checks[x["name"]]}
                        with ui.element("div").classes("sr-pf-b"):
                            u = maps.get(x["name"])
                            if u:
                                ui.link(_short(x["title"]), u, new_tab=True).classes("sr-pf-bn")
                            else:
                                ui.label(_short(x["title"])).classes("sr-pf-bn")
                        for k in keys:
                            c_ = cs.get(k)
                            with ui.element("div").classes("sr-pf-c"):
                                if c_:
                                    ic, col = icons.get(c_["level"], icons["info"])
                                    i_ = ui.icon(ic, size="20px").style(f"color:{col}")
                                    i_.props["aria-label"] = f"{c_['title']}: {LEVELS[c_['level']][0]}"
                                    i_.tooltip(f"{LEVELS[c_['level']][0]} · {c_['detail']}")
                                else:
                                    ui.label("–").classes("muted")

    def make_xlsx(locs, names, last) -> bytes:
        from openpyxl import Workbook

        from .export import INT, _sheet
        with connect() as c:
            end = date.fromisoformat(last) if last else date.today()
            daily = c.execute(f"SELECT location, day, metric, value FROM gbp_daily WHERE location IN "
                              f"({','.join('?' * len(names))}) ORDER BY day", names).fetchall() if names else []
            months = G.keyword_months(c, names)
            kw = G.keyword_rows(c, names, months[-12:]) if months else []
        titles = {x["name"]: x["title"] for x in locs}
        wb = Workbook()
        wb.remove(wb.active)
        by_day: dict[tuple, dict] = {}
        for loc, day, metric, v in daily:
            by_day.setdefault((loc, day), {})[metric] = v
        _sheet(wb, "Hiệu suất theo ngày", [("Ngày", 12, None), ("Chi nhánh", 30, None)]
               + [(G.METRICS[m], 16, INT) for m in G.METRICS],
               [[day, titles.get(loc, loc)] + [vals.get(m, 0) for m in G.METRICS]
                for (loc, day), vals in sorted(by_day.items(), key=lambda kv: (kv[0][1], kv[0][0]))])
        _sheet(wb, "Từ khóa 12 tháng", [("Từ khóa", 40, None), ("Lượt xem", 12, INT), ("Ghi chú", 16, None)],
               [[r["keyword"], r["value"] or None, f"dưới {r['below']}" if not r["value"] else ""] for r in kw])
        _sheet(wb, "Kiểm tra hồ sơ", [("Chi nhánh", 30, None), ("Mức", 12, None), ("Mục", 30, None),
                                      ("Chi tiết", 90, None)],
               [[x["title"], LEVELS[c_["level"]][0], c_["title"], c_["detail"]]
                for x in locs if x["name"] in names for c_ in G.audit(x, site)])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    body()


def _scopes(cfg) -> list[str]:
    """Quyền của token Google hiện tại (không gọi mạng)."""
    from google.oauth2.credentials import Credentials
    try:
        return list(Credentials.from_authorized_user_file(str(cfg.token_path)).scopes or [])
    except (ValueError, OSError):
        return []


async def post_loop(base) -> None:
    """Bài đăng GBP đã lên lịch: mỗi 2 phút xem dự án nào có bài tới giờ thì đăng (đăng bù khi máy vừa bật lại)."""
    import asyncio
    import traceback
    from contextlib import closing

    from nicegui import run

    from . import auth
    from . import db
    from . import gbp_posts as GP
    from . import projects as PJ
    await asyncio.sleep(60)
    while True:
        try:
            with closing(db.connect(base.db_path)) as c:
                projects = PJ.list_projects(c)
            for p in projects:
                cfg = PJ.config_for(base, p)

                def work(cfg=cfg):
                    with closing(db.connect(cfg.db_path)) as c:
                        ids = GP.due(c)
                        if not ids:
                            return 0
                        creds = auth.get_credentials(cfg, need=(auth.BUSINESS_SCOPE,))
                        client, locs = GP.Client(creds), G.linked(c)
                        for pid in ids:
                            try:
                                GP.publish(c, pid, locs, client, G.explain)
                            except Exception as e:  # noqa: BLE001  (bài lỗi: ghi lỗi, không chặn bài khác)
                                GP.mark_failed(c, pid, G.explain(e))
                        return len(ids)
                await run.io_bound(work)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(120)


# ---------------------------------------------------------------- việc nền trả lời đánh giá (một việc mỗi dự án)
import itertools as _it

JOBS: dict[str, dict] = {}  # file dữ liệu dự án -> việc đang chạy / vừa xong (xem start_job trong trang)
_JOB_IDS = _it.count(1)


def _charge(cfg, user, detail: str):
    """Trừ credit một câu AI (không cần màn hình). False: Member hết credit."""
    try:
        with PT._connect() as con:
            return PT.spend(con, user, PT._project(cfg), "ai_review_reply", PT.cost("ai_review_reply"), detail)
    except PT.NotEnough:
        return False
    except RuntimeError:
        return None


async def _run_job(job: dict, its: list[dict], cfg, user, titles: dict, voice: dict, locs: list) -> None:
    """Chạy lần lượt từng câu trong luồng nền: viết nháp AI (lưu nháp ngay) hoặc gửi lên Google Maps (ghi đã trả lời).
    Cập nhật job để màn hình (hộp / chip góc) đọc tiến độ; bấm Dừng thì dừng sau câu đang làm."""
    from contextlib import closing

    from nicegui import run

    from . import auth
    from . import db
    from . import gbp_reviews as GR
    from .spend import runner
    try:
        prov = client = None
        by_loc = {x["name"]: x for x in locs}
        for r in its:
            if job["stop"]:
                job["stopped"] = True
                break
            k = (r["location"], r["id"])
            job["current"] = f"{r.get('author') or 'khách'} ({r.get('rating') or 0}★)"
            job["status"][k] = "Đang viết…" if job["kind"] == "draft" else "Đang gửi…"
            if job["kind"] == "draft":
                entry = _charge(cfg, user, r.get("author") or "")
                if entry is False:
                    job["status"][k] = "✗ Hết credit"
                    job["errors"] += 1
                    job["stopped"] = True
                    break
                if prov is None:
                    from . import ai_writer as AW
                    prov = AW.provider(cfg, "review_reply")
                br = titles.get(r["location"], "")

                def work(r=r, br=br):
                    with runner(str(user)):
                        text = GR.draft(prov, br.split(" - ")[0] or br, r, "", voice, br)
                    with closing(db.connect(cfg.db_path)) as c:
                        GR.save_draft(c, r["location"], r["id"], text, str(user))
                    return text
                try:
                    job["results"][k] = await run.io_bound(work)
                    job["status"][k] = "✓ AI vừa viết, đọc lại trước khi gửi"
                    job["ok"] += 1
                except Exception as e:  # noqa: BLE001
                    PT.give_back(entry)
                    job["status"][k] = f"✗ AI chưa viết được: {str(e)[:100]}"
                    job["errors"] += 1
            else:
                loc = by_loc.get(r["location"])

                def send(r=r, loc=loc):
                    nonlocal client
                    if client is None:
                        client = GR.Client(auth.get_credentials(cfg, need=(auth.BUSINESS_SCOPE,)))
                    client.reply(loc, r["id"], r["text"])
                    with closing(db.connect(cfg.db_path)) as c:
                        GR.mark_replied(c, r["location"], r["id"], r["text"])
                try:
                    if not loc:
                        raise RuntimeError("Chi nhánh không còn gắn với dự án")
                    await run.io_bound(send)
                    job["status"][k] = "✓ Đã gửi lên Google Maps"
                    job["ok"] += 1
                except Exception as e:  # noqa: BLE001
                    job["status"][k] = f"✗ Chưa gửi được: {G.explain(e)[:120]}"
                    job["errors"] += 1
            job["done"] += 1
    finally:
        job["running"] = False
        job["finished"] = True
        job["current"] = ""
