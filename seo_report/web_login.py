"""Màn Đăng nhập (email + mật khẩu) và Đổi mật khẩu. Kiểm tra mật khẩu, khóa tạm, phiên: xem access.py."""
from . import access as A
from . import ui_theme as T


def safe_next(target: str | None) -> str:
    """Chỉ cho quay về đường dẫn trong tool (chặn chuyển hướng ra trang ngoài)."""
    t = (target or "/").strip()
    return t if t.startswith("/") and not t.startswith("//") and "\\" not in t else "/"


def _card(ui, title: str, sub: str):
    ui.add_head_html(T.HEAD)
    page = ui.column().classes("w-full items-center justify-center").style("min-height: 92vh")
    with page:
        card = ui.element("div").classes("sr-card q-pa-lg column gap-3").style(
            "width: 100%; max-width: 400px; border-radius: 18px")
        with card:
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.image("/assets/app-icon.svg").props("fit=contain no-spinner").style("width: 40px; height: 40px")
                ui.label("SEO Report").classes("sr-section-title").style("font-size: 20px")
            ui.label(title).classes("sr-section-title").style("font-size: 20px; margin-top: 4px")
            ui.label(sub).classes("text-sm muted")
    return card


GOOGLE_SVG = ('<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 '
              '0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.6 5.4 2.7 13.3l7.9 6.1C12.5 13.6 17.8 9.5 24 '
              '9.5z"/><path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.4 '
              '5.7c4.3-4 6.9-9.9 6.9-17.1z"/><path fill="#FBBC05" d="M10.5 28.6c-.5-1.4-.8-3-.8-4.6s.3-3.2.8-4.6l-7.9'
              '-6.1C1 16.6 0 20.2 0 24s1 7.4 2.7 10.7l7.8-6.1z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-'
              '5.8l-7.4-5.7c-2.1 1.4-4.8 2.3-8.5 2.3-6.2 0-11.5-4.1-13.4-9.8l-7.9 6.1C6.6 42.6 14.6 48 24 48z"/></svg>')


LOGIN_CSS = """
.sr-login-card { width: 100%; max-width: 400px; border-radius: 20px; padding: 32px 28px 24px; }
.sr-login-brand { display: flex; flex-direction: column; align-items: center; gap: 10px; text-align: center; }
.sr-login-title { font-size: 22px; font-weight: 700; letter-spacing: -.01em; margin-top: 6px; }
.sr-login-google.q-btn { height: 48px; border-radius: 12px; font-size: 15px; font-weight: 600; }
.sr-login-google .sr-g-dot { width: 26px; height: 26px; border-radius: 50%; background: #fff; display: flex;
  align-items: center; justify-content: center; }
.sr-login-or { display: flex; align-items: center; gap: 12px; color: #8A8A80; font-size: 12px; }
.sr-login-or::before, .sr-login-or::after { content: ""; flex: 1; height: 1px; background: #E7E5DC; }
.sr-login-err { display: flex; gap: 8px; align-items: flex-start; background: #FCEDE6; border: 1px solid #F2CDBC;
  border-radius: 10px; padding: 10px 12px; font-size: 13px; color: #9A3412; }
.sr-login-link.q-btn { font-size: 13px; color: #55554E; min-height: 32px; }
.sr-login-foot { font-size: 12px; color: #8A8A80; text-align: center; }
@media (max-width: 480px) { .sr-login-card { padding: 24px 18px 20px; border-radius: 16px; } }
"""


def build_login_page(ui, cfg, connect, next_url: str, ip: str = "", error: str = "") -> None:
    from urllib.parse import quote

    from nicegui import app

    from . import google_login as GL
    from .web_access import _setting
    with connect() as c:
        only = A.google_only(c)
    google = GL.ready(cfg) and bool(_setting(connect, "public_url"))
    only = only and google  # chưa cài xong Google thì vẫn cho mọi người dùng mật khẩu
    ui.add_head_html(T.HEAD)
    ui.add_css(LOGIN_CSS)
    with ui.column().classes("w-full items-center justify-center q-px-md").style("min-height: 94vh"):
        card = ui.element("div").classes("sr-card sr-login-card column gap-4")
    with card:
        with ui.element("div").classes("sr-login-brand"):
            ui.image("/assets/app-icon.svg").props("fit=contain no-spinner").style("width: 48px; height: 48px")
            with ui.column().classes("items-center gap-1"):
                ui.label("Đăng nhập SEO Report").classes("sr-login-title")
                ui.label("Dùng tài khoản Google đã được cấp quyền" if google else
                         "Dùng email (hoặc tên đăng nhập) và mật khẩu được cấp").classes("text-sm muted")
        if error:
            with ui.element("div").classes("sr-login-err w-full"):
                ui.icon("error_outline", size="18px")
                ui.label(error)
        if google:
            g = ui.button(on_click=lambda: ui.navigate.to(
                "/login/google?next=" + quote(safe_next(next_url), safe="")))
            g.props("unelevated no-caps").classes("w-full sr-login-google")
            with g, ui.row().classes("items-center gap-3 no-wrap"):
                with ui.element("span").classes("sr-g-dot"):
                    ui.html(GOOGLE_SVG)
                ui.label("Tiếp tục với Google")
            with ui.element("div").classes("sr-login-or w-full"):
                ui.label("hoặc")
            toggle = ui.button("Owner: đăng nhập bằng mật khẩu" if only else "Đăng nhập bằng mật khẩu",
                               icon="key").props("flat no-caps dense").classes("sr-login-link self-center")
        # Form thật (<form>): Enter gửi form, trình quản lý mật khẩu nhận ra ô tên đăng nhập / mật khẩu để tự điền
        form = ui.element("form").classes("w-full column gap-3").props('method="post" action="/login" novalidate')
        if google:
            form.set_visibility(False)

            def show_form():
                form.set_visibility(True)
                toggle.set_visibility(False)
                email.run_method("focus")
            toggle.on_click(show_form)
        with form:
            # type="text" + inputmode email: vẫn nhận tên đăng nhập (tài khoản không phải email)
            email = ui.input("Email hoặc tên đăng nhập").props(
                'outlined name=username autocomplete=username inputmode=email autocapitalize=none spellcheck=false'
                + ("" if google else " autofocus")).classes("w-full")
            pw = ui.input("Mật khẩu", password=True).props(
                "outlined name=password autocomplete=current-password").classes("w-full")
            shown = {"on": False}
            with pw.add_slot("append"):
                eye = ui.button(icon="visibility").props(
                    'flat round dense type=button color=grey-7 aria-label="Hiện mật khẩu" aria-pressed="false"')

            def toggle_pw():
                shown["on"] = not shown["on"]
                pw.props(f"type={'text' if shown['on'] else 'password'}")
                eye.props(f'icon={"visibility_off" if shown["on"] else "visibility"} '
                          f'aria-label="{"Ẩn mật khẩu" if shown["on"] else "Hiện mật khẩu"}" '
                          f'aria-pressed="{str(shown["on"]).lower()}"')
            eye.on_click(toggle_pw)
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")
            err.set_visibility(False)

            def fail(text: str) -> None:
                err.text = text
                err.set_visibility(True)
                pw.value = ""

            def submit():
                if A.ip_blocked(ip):
                    fail(f"Thử sai quá nhiều lần từ mạng này: thử lại sau {A.IP_WINDOW // 60} phút")
                    return
                with connect() as c:
                    settings = A.effective(c, cfg.access)
                    user, why, sess = A.login(c, settings, email.value or "", pw.value or "")
                if not user:
                    A.note_ip_fail(ip)
                    fail(why)
                    return
                app.storage.user["auth"] = sess
                if user.must_change:  # mật khẩu được cấp: gợi ý đặt mật khẩu riêng, có nút bỏ qua
                    ui.navigate.to("/doi-mat-khau?next=" + quote(safe_next(next_url), safe=""))
                else:
                    ui.navigate.to(safe_next(next_url))

            form.on("submit.prevent", submit)  # Enter ở bất kỳ ô nào hoặc bấm nút: một đường gửi duy nhất
            ui.button("Đăng nhập").props(
                ("outline" if google else "unelevated") + " no-caps type=submit").classes("w-full").style(
                "height: 44px; border-radius: 12px")
        ui.label("Chưa có quyền truy cập? Liên hệ người quản lý tool.").classes("sr-login-foot w-full")


def build_request_page(ui, email: str, status: str, approved=None) -> None:
    """Sau khi đăng nhập Google mà email chưa có quyền: đã gửi yêu cầu cho Owner / Admin duyệt. approved(): hỏi lại
    mỗi 10 giây; được duyệt thì báo và tự vào tool."""
    ui.add_head_html(T.HEAD)
    ui.add_css(LOGIN_CSS)
    title, text, icon, tone = {
        "pending": ("Đã gửi yêu cầu truy cập",
                    "Owner / Admin sẽ xem và duyệt. Cứ để trang này mở: được duyệt là tool tự đưa bạn vào. Nếu đã "
                    "đóng trang, quay lại và bấm Tiếp tục với Google.", "hourglass_top", "amber"),
        "rejected": ("Yêu cầu truy cập chưa được duyệt",
                     "Tài khoản này đã bị từ chối. Liên hệ người quản lý tool nếu bạn cần vào.", "block", "red"),
        "full": ("Chưa gửi được yêu cầu",
                 "Đang có quá nhiều yêu cầu chờ duyệt. Liên hệ trực tiếp người quản lý tool.", "error_outline",
                 "red")}.get(status, ("Đã gửi yêu cầu truy cập", "", "hourglass_top", "amber"))
    with ui.column().classes("w-full items-center justify-center q-px-md").style("min-height: 94vh"):
        with ui.element("div").classes("sr-card sr-login-card column gap-4"):
            with ui.element("div").classes("sr-login-brand"):
                with ui.element("div").classes("sr-icon-bubble").style(
                        f"background:{T.TONES[tone][0]}; width:48px; height:48px"):
                    ui.icon(icon, size="24px").style(f"color:{T.TONES[tone][1]}")
                with ui.column().classes("items-center gap-1"):
                    ui.label(title).classes("sr-login-title")
                    ui.label(email).classes("text-sm font-medium")
            ui.label(text).classes("text-sm muted text-center")
            ui.button("Dùng tài khoản Google khác", icon="switch_account",
                      on_click=lambda: ui.navigate.to("/login/google")).props("outline no-caps").classes(
                "w-full").style("height: 44px; border-radius: 12px")
            ui.button("Về trang đăng nhập", on_click=lambda: ui.navigate.to("/login")).props(
                "flat no-caps dense").classes("sr-login-link self-center")
    if approved:
        def check():
            if approved():
                timer.deactivate()
                ui.notify("Bạn đã được duyệt. Đang vào tool…", type="positive", position="top")
                ui.timer(1.5, lambda: ui.navigate.to("/"), once=True)
        timer = ui.timer(10, check)


def build_change_password_page(ui, cfg, connect, user, next_url: str = "/") -> None:
    from nicegui import app
    issued = user.must_change  # đang dùng mật khẩu được cấp: chỉ gợi ý đổi, không bắt buộc
    target = safe_next(next_url)
    card = _card(ui, "Đặt mật khẩu riêng?" if issued else "Đổi mật khẩu",
                 ("Bạn đang dùng mật khẩu được cấp. Có thể đặt mật khẩu riêng ngay, hoặc bỏ qua và đổi sau trong "
                  "menu tài khoản. " if issued else "") + f"Mật khẩu mới ít nhất {A.MIN_PASSWORD} ký tự.")
    with card:
        ui.label(str(user)).classes("text-sm font-medium")
        cur = ui.input("Mật khẩu được cấp" if issued else "Mật khẩu hiện tại", password=True,
                       password_toggle_button=True).props("outlined autocomplete=current-password").classes("w-full")
        new = ui.input("Mật khẩu mới", password=True, password_toggle_button=True).props(
            "outlined autocomplete=new-password").classes("w-full")
        again = ui.input("Nhập lại mật khẩu mới", password=True, password_toggle_button=True).props(
            "outlined autocomplete=new-password").classes("w-full")
        err = ui.label().classes("text-sm").style(f"color:{T.RED}; min-height: 20px")

        def submit():
            if (new.value or "") != (again.value or ""):
                err.text = "Hai lần nhập mật khẩu mới không khớp"
                return
            if (new.value or "") == (cur.value or ""):
                err.text = "Mật khẩu mới phải khác mật khẩu hiện tại"
                return
            with connect() as c:
                settings = A.effective(c, cfg.access)
                ok, why, _ = A.login(c, settings, str(user), cur.value or "")
                if not ok:
                    err.text = "Mật khẩu hiện tại không đúng" if "không đúng" in why else why
                    return
                try:
                    A.set_password(c, settings, str(user), new.value or "", must_change=False)
                except ValueError as e:
                    err.text = str(e)
                    return
                _, _, sess = A.login(c, settings, str(user), new.value)
            app.storage.user["auth"] = sess  # phiên mới gắn với mật khẩu mới
            from .live import kick
            kick(email=str(user), keep=ui.context.client.id)  # trang ở máy khác (mật khẩu cũ): ngắt
            ui.notify("Đã đổi mật khẩu", type="positive")
            ui.navigate.to(target)

        def skip():
            if issued:  # bỏ qua: không gợi ý lại ở lần đăng nhập sau (vẫn đổi được trong menu tài khoản)
                with connect() as c:
                    A.dismiss_change(c, str(user))
            ui.navigate.to(target)

        again.on("keydown.enter", submit)
        ui.button("Lưu mật khẩu", on_click=submit).props("unelevated no-caps").classes("w-full")
        ui.button("Để sau, vào tool" if issued else "Quay lại", on_click=skip).props("flat no-caps").classes("w-full")
