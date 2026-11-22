"""Màn "Google của tôi": Member trở lên kết nối tài khoản Google của chính mình để thêm website riêng vào tool (đọc
Search Console / GA4 bằng quyền của họ). Logic: user_google.py."""
from datetime import datetime

from . import access as A
from . import ui_theme as T
from . import user_google as UG


def can_connect(con, settings, acct) -> bool:
    """Member trở lên (Guest: không)."""
    if getattr(acct, "admin", False):
        return True
    u = next((x for x in A.users(con, settings) if x["email"] == str(acct).lower()), None)
    return bool(u) and A.kind(u, A.members(con).get(u["email"], {})) != "client"


def should_ask(con, base, acct) -> bool:
    """Hỏi một lần sau lần đăng nhập Google đầu: Member trở lên, đã cài Đăng nhập Google, chưa kết nối, chưa hỏi."""
    from . import google_login as GL
    email = str(acct).lower()
    if not GL.ready(base) or UG.status(con, email) or not can_connect(con, base.access, acct):
        return False
    A.users(con, base.access)  # bảo đảm có cột google_asked
    row = con.execute("SELECT google_asked FROM access_users WHERE email = ?", (email,)).fetchone()
    return not (row and row[0])


def mark_asked(con, email: str) -> None:
    from datetime import timezone
    with con:
        con.execute("UPDATE access_users SET google_asked = ? WHERE email = ?",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(email).lower()))


def connect_prompt(ui, base, app_connect, acct) -> None:
    """Hộp xin phép (một lần): nói rõ tool đọc gì, ai thấy gì; người dùng chọn Đồng ý hoặc Để sau."""
    from .web_access import _setting
    email = str(acct).lower()
    with app_connect() as c:
        mark_asked(c, email)

    def agree():
        try:
            url = UG.start(base, _setting(app_connect, "public_url"), email)
        except ValueError as e:
            ui.notify(str(e), type="warning")
            return
        d.close()
        ui.navigate.to(url)

    with ui.dialog() as d, ui.card().style("max-width: 480px; border-radius: 16px"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['blue'][0]}"):
                ui.icon("add_link", size="18px").style(f"color:{T.TONES['blue'][1]}")
            ui.label("Kết nối Google của bạn?").classes("text-lg font-semibold")
        ui.label("Kết nối để thêm vào tool các website bạn quản lý trên Search Console / GA4.").classes("text-sm")
        for icon, text in (("visibility", "Tool chỉ đọc số liệu Search Console và Analytics, không sửa gì."),
                           ("checklist", "Bạn tự chọn website nào đưa vào tool; website khác không ai thấy."),
                           ("group", "Website bạn thêm: bạn và Owner / Admin xem được số liệu."),
                           ("link_off", "Gỡ kết nối bất cứ lúc nào ở menu tài khoản › Google của tôi.")):
            with ui.row().classes("items-start gap-2 no-wrap"):
                ui.icon(icon, size="16px").classes("muted").style("margin-top: 2px")
                ui.label(text).classes("text-sm")
        with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
            ui.button("Để sau", on_click=d.close).props("flat no-caps")
            ui.button("Đồng ý, kết nối Google", icon="link", on_click=agree).props("unelevated no-caps")
    d.open()


def _when(iso: str | None) -> str:
    return f"{datetime.fromisoformat(iso).astimezone():%d/%m/%Y}" if iso else "–"


def build_my_google_page(ui, base, app_connect, acct, notice: str = "") -> None:
    from nicegui import app, run

    from . import google_login as GL
    from . import projects as PJ
    from .web_access import _setting
    email = str(acct).lower()
    T.page_header(ui, "add_link", "Google của tôi",
                  "Kết nối Google của bạn để thêm website bạn quản lý trên Search Console / GA4.", tone="grey")
    with app_connect() as c:
        ok = can_connect(c, base.access, acct)
    if not ok:
        ui.label("Tài khoản Guest chỉ xem website được cấp.").classes("text-sm muted")
        return
    public = _setting(app_connect, "public_url")
    if not (GL.ready(base) and public):
        ui.label("Owner chưa cài Đăng nhập bằng Google ở Cài đặt tích hợp nên chưa kết nối được.").classes(
            "text-sm muted")
        return
    page = ui.column().classes("w-full gap-3").style("max-width: 760px")

    def connect():
        try:
            ui.navigate.to(UG.start(base, public, email))
        except ValueError as e:
            ui.notify(str(e), type="warning")

    @ui.refreshable
    def body():
        with app_connect() as c:
            st = UG.status(c, email)
            mine = UG.my_sites(c, email)
        # ---- trạng thái kết nối ----
        with ui.element("div").classes("sr-card q-pa-md w-full"):
            with ui.row().classes("w-full items-center gap-3 no-wrap"):
                with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['blue'][0]}"):
                    ui.icon("account_circle", size="18px").style(f"color:{T.TONES['blue'][1]}")
                with ui.column().classes("col gap-0").style("min-width:0"):
                    ui.label(st["google_email"] or "Đã kết nối" if st else "Chưa kết nối Google").classes(
                        "text-sm font-semibold ellipsis")
                    ui.label(f"Kết nối ngày {_when(st['connected_at'])} · tool chỉ đọc Search Console và Analytics"
                             if st else "Tool chỉ xin quyền đọc Search Console và Analytics của bạn").classes(
                        "text-xs muted")
                if st:
                    ui.button("Kết nối lại", on_click=connect).props("flat dense no-caps")
                    ui.button("Gỡ", on_click=ask_disconnect).props("flat dense no-caps color=grey-8").tooltip(
                        "Gỡ kết nối: website đã thêm ngừng cập nhật số")
                else:
                    ui.button("Kết nối Google", icon="link",
                              on_click=lambda: connect_prompt(ui, base, app_connect, acct)).props(
                        "unelevated no-caps")
        if st:
            add_box()
        # ---- website đã thêm ----
        if mine:
            ui.label("Website bạn đã thêm").classes("sr-nav-group q-mt-sm")
            for p in mine:
                with ui.element("div").classes("sr-card sr-set-row w-full"):
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        T.project_icon(ui, p, 32)
                        with ui.column().classes("col gap-0").style("min-width:0"):
                            ui.label(p["name"]).classes("text-sm font-semibold ellipsis")
                            ui.label(p["site_url"] + (" · GA4 " + p["ga4_property"].split("/")[-1]
                                                      if p["ga4_property"] else "")).classes("text-xs muted ellipsis")
                        paid = p["settings"].get("paid_ok")
                        T.status_chip(ui, "Đã bật tính năng tốn phí" if paid else "Tính năng tốn phí: chờ duyệt",
                                      "green" if paid else "grey", "check_circle" if paid else "schedule").tooltip(
                            "Check rank, AI… tốn tiền: Owner / Admin bật ở màn Dự án" if not paid else
                            "Trừ vào credit của bạn")

                        def open_(slug=p["slug"]):
                            app.storage.user["project"] = slug
                            ui.navigate.to("/")
                        ui.button("Mở", on_click=open_).props("flat dense no-caps")

    def add_box():
        box = ui.element("div").classes("sr-card q-pa-md w-full")
        with box:
            ui.label("Thêm website").classes("text-sm font-semibold")
            holder = ui.column().classes("w-full gap-2")
            with holder:
                T.spinner(ui, "Đang lấy danh sách property từ Google của bạn…", size="16px")

        async def load():
            try:
                gsc_opts, ga4_opts = await run.io_bound(UG.my_properties, base, email)
            except (Exception, SystemExit) as e:  # noqa: BLE001
                holder.clear()
                with holder:
                    ui.label(f"Không đọc được danh sách từ Google ({str(e)[:160]}). Bấm Kết nối lại.").classes(
                        "text-sm").style(f"color:{T.RED}")
                return
            with app_connect() as c:
                taken = {p["site_url"] for p in PJ.list_projects(c)}
            free = {k: v for k, v in gsc_opts.items() if k not in taken}
            holder.clear()
            with holder:
                if not gsc_opts:
                    ui.label("Tài khoản Google này chưa có website nào trên Search Console.").classes("text-sm muted")
                    return
                if not free:
                    ui.label("Mọi website trên Search Console của bạn đã có trong tool. Nhờ Owner / Admin cấp quyền "
                             "nếu bạn chưa thấy.").classes("text-sm muted")
                    return
                site = ui.select(free, label="Property Search Console", with_input=True).props(
                    "outlined dense").classes("w-full")
                ga4 = ui.select(ga4_opts, label="GA4 property (không bắt buộc)", clearable=True,
                                with_input=True).props("outlined dense").classes("w-full")
                name = ui.input("Tên dự án", placeholder="ví dụ: Công ty ABC").props("outlined dense").classes(
                    "w-full")
                site.on_value_change(lambda e: setattr(name, "value", name.value or PJ.domain(e.value or "")))
                ui.label(f"{len(gsc_opts) - len(free)} website khác đã có trong tool nên không hiện ở đây."
                         if len(free) < len(gsc_opts) else "").classes("text-xs muted")

                def add():
                    if not site.value:
                        ui.notify("Chọn property Search Console", type="warning")
                        return
                    try:
                        with app_connect() as c:
                            p = UG.add_site(c, base, email, (name.value or PJ.domain(site.value)).strip(),
                                            site.value, ga4.value or "")
                    except ValueError as e:
                        ui.notify(str(e), type="warning")
                        return
                    ui.notify(f"Đã thêm {p['name']}. Tool đang lấy số lần đầu (vài phút).", type="positive")
                    start_sync(p)
                    body.refresh()
                with ui.row().classes("w-full justify-end"):
                    ui.button("Thêm vào tool", icon="add", on_click=add).props("unelevated no-caps")
        ui.timer(0.1, load, once=True)

    def start_sync(p: dict) -> None:
        """Lấy số GSC / GA4 lần đầu ở nền (miễn phí), như lịch hằng ngày."""
        import threading

        from .cli import _daily_one
        cfg = PJ.config_for(base, p)
        threading.Thread(target=lambda: _safe(_daily_one, cfg), daemon=True).start()

    def ask_disconnect():
        with ui.dialog() as d, ui.card().style("max-width: 440px; border-radius: 14px"):
            ui.label("Gỡ kết nối Google?").classes("text-lg font-semibold")
            ui.label("Website bạn đã thêm vẫn giữ trong tool nhưng ngừng cập nhật số cho đến khi kết nối lại.").classes(
                "text-sm")

            def go():
                with app_connect() as c:
                    UG.disconnect(c, base, email)
                d.close()
                ui.notify("Đã gỡ kết nối Google", type="positive")
                body.refresh()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Gỡ kết nối", on_click=go).props("unelevated no-caps color=negative")
        d.open()

    with page:
        body()
    if notice:
        kind, text = NOTICES.get(notice, ("warning", ""))
        if text:
            ui.notify(text, type=kind)


def _safe(fn, *a) -> None:
    import traceback
    try:
        fn(*a)
    except (Exception, SystemExit):  # noqa: BLE001
        traceback.print_exc()


NOTICES = {"ok": ("positive", "Đã kết nối Google của bạn"), "fail": ("negative", "Kết nối Google không thành công"),
           "expired": ("warning", "Phiên kết nối đã hết hạn: bấm Kết nối lại"),
           "cancel": ("warning", "Đã hủy kết nối Google")}
