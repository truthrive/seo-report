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
            ui.image("/assets/logo.svg").props("fit=contain no-spinner").style("width: 170px; height: 48px")
            ui.label(title).classes("sr-section-title").style("font-size: 20px; margin-top: 4px")
            ui.label(sub).classes("text-sm muted")
    return card


def build_login_page(ui, cfg, connect, next_url: str) -> None:
    from nicegui import app
    card = _card(ui, "Đăng nhập", "Dùng email và mật khẩu được cấp. Chưa có tài khoản: liên hệ người quản lý tool.")
    with card:
        email = ui.input("Email").props("outlined autofocus autocomplete=username").classes("w-full")
        pw = ui.input("Mật khẩu", password=True, password_toggle_button=True).props(
            "outlined autocomplete=current-password").classes("w-full")
        err = ui.label().classes("text-sm").style(f"color:{T.RED}; min-height: 20px")

        def submit():
            with connect() as c:
                settings = A.effective(c, cfg.access)
                user, why, sess = A.login(c, settings, email.value or "", pw.value or "")
            if not user:
                err.text = why
                pw.value = ""
                return
            app.storage.user["auth"] = sess
            ui.navigate.to("/doi-mat-khau" if user.must_change else safe_next(next_url))

        pw.on("keydown.enter", submit)
        email.on("keydown.enter", lambda: pw.run_method("focus"))
        ui.button("Đăng nhập", on_click=submit).props("unelevated no-caps size=md").classes("w-full")


def build_change_password_page(ui, cfg, connect, user) -> None:
    from nicegui import app
    forced = user.must_change
    card = _card(ui, "Đặt mật khẩu mới" if forced else "Đổi mật khẩu",
                 ("Bạn đang dùng mật khẩu tạm: đặt mật khẩu riêng để tiếp tục. " if forced else "")
                 + f"Ít nhất {A.MIN_PASSWORD} ký tự.")
    with card:
        ui.label(str(user)).classes("text-sm font-medium")
        cur = ui.input("Mật khẩu hiện tại" + (" (mật khẩu tạm)" if forced else ""), password=True,
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
            ui.notify("Đã đổi mật khẩu", type="positive")
            ui.navigate.to("/")

        again.on("keydown.enter", submit)
        ui.button("Lưu mật khẩu", on_click=submit).props("unelevated no-caps").classes("w-full")
        if not forced:
            ui.button("Quay lại", on_click=lambda: ui.navigate.to("/")).props("flat no-caps").classes("w-full")
