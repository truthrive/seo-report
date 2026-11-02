"""Màn Hồ sơ của tôi: mỗi người tự sửa tên hiển thị, ảnh đại diện và mật khẩu của mình (khách hàng cũng mở được)."""
from . import access as A
from . import presence as PR
from . import ui_theme as T

MAX_PHOTO_BYTES = 5_000_000


def photo_uri(content: bytes, size: int = 128) -> str:
    """Ảnh tải lên → PNG vuông size×size (cắt giữa) dạng data URI, đủ nét cho avatar mà trang vẫn nhẹ."""
    import base64
    import io

    from PIL import Image, ImageOps
    if not content or len(content) > MAX_PHOTO_BYTES:
        raise ValueError(f"Ảnh phải nhỏ hơn {MAX_PHOTO_BYTES // 1_000_000} MB")
    try:
        img = Image.open(io.BytesIO(content))
        img = ImageOps.exif_transpose(img).convert("RGBA")
    except Exception as e:  # noqa: BLE001
        raise ValueError("File không phải ảnh (dùng PNG, JPG hoặc WEBP)") from e
    img = ImageOps.fit(img, (size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def build_profile_page(ui, cfg, connect, user) -> None:
    from nicegui import app

    email = str(user)
    with connect() as c:
        settings = A.effective(c, cfg.access)
        prof = A.profiles(c).get(email, {"name": "", "avatar": ""})
        row = next((u for u in A.users(c, settings) if u["email"] == email), None)
    state = {"avatar": prof["avatar"]}
    role_text = ("Chủ tool · toàn quyền" if A.is_admin(user) or user.role == A.LOCAL
                 else A.PROJECT_ROLES.get(user.role, "Theo từng website"))

    T.page_header(ui, "account_circle", "Hồ sơ của tôi", "Tên và ảnh hiện ở menu, nhóm avatar và màn Phân quyền. "
                  "Đổi mật khẩu đăng nhập ở khung bên dưới.", tone="grey")

    # ---- Hồ sơ ----
    with T.section(ui, "Thông tin", "badge"):
        with ui.row().classes("items-center gap-4 no-wrap w-full"):
            @ui.refreshable
            def avatar_box():
                st, st_text = PR.describe(email)
                T.presence_avatar(ui, name.value or email, st, st_text, size=72, colors=T.avatar_color(email),
                                  photo=state["avatar"])

            box = ui.element("div")  # chỗ avatar: vẽ sau khi có ô tên (chữ cái đầu theo tên đang gõ)
            with ui.column().classes("gap-1"):
                async def uploaded(e):
                    try:
                        state["avatar"] = photo_uri(await e.file.read())
                    except ValueError as ex:
                        ui.notify(str(ex), type="warning")
                        return
                    avatar_box.refresh()

                up = ui.upload(on_upload=uploaded, auto_upload=True, max_file_size=MAX_PHOTO_BYTES).props(
                    'accept="image/*" flat dense hide-upload-btn').classes("hidden")
                with ui.row().classes("gap-1"):
                    ui.button("Tải ảnh lên", icon="upload", on_click=lambda: up.run_method("pickFiles")).props(
                        "outline dense no-caps")

                    def drop_photo():
                        state["avatar"] = ""
                        avatar_box.refresh()
                    ui.button("Bỏ ảnh", icon="hide_image", on_click=drop_photo).props("flat dense no-caps")
                ui.label("PNG, JPG hoặc WEBP, tối đa 5 MB. Tool tự cắt vuông và thu nhỏ.").classes("text-xs muted")
        with ui.element("div").classes("w-full q-mt-md").style(
                "display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px"):
            name = ui.input("Tên hiển thị", value=prof["name"], placeholder="ví dụ: Trường Thịnh").props(
                f"outlined dense counter maxlength={A.MAX_NAME}")
            ui.input("Email / tên đăng nhập", value=email).props("outlined dense readonly").tooltip(
                "Dùng để đăng nhập; Chủ tool đổi được ở màn Phân quyền")
            ui.input("Quyền", value=role_text + (f" · {row['title']}" if row and row.get("title") else "")).props(
                "outlined dense readonly")
        with box:
            avatar_box()
        name.on_value_change(lambda _: avatar_box.refresh())

        def save_profile():
            try:
                with connect() as c:
                    A.set_profile(c, A.effective(c, cfg.access), email, name.value or "", state["avatar"])
            except ValueError as e:
                ui.notify(str(e), type="warning")
                return
            ui.notify("Đã lưu hồ sơ", type="positive")
            ui.navigate.reload()  # menu, avatar trên thanh trên cùng cập nhật theo

        with ui.row().classes("w-full justify-end q-mt-sm"):
            ui.button("Lưu hồ sơ", icon="check", on_click=save_profile).props("unelevated no-caps")

    # ---- Mật khẩu ----
    with T.section(ui, "Mật khẩu", "key"):
        if user.via != "password" and user.role != A.LOCAL:
            ui.label("Bạn đăng nhập qua Cloudflare Access / Tailscale nên không có mật khẩu trong tool.").classes(
                "text-sm muted")
            return
        local = user.role == A.LOCAL  # ngồi ở máy chạy tool: đặt mật khẩu không cần mật khẩu cũ
        ui.label(("Mật khẩu để đăng nhập khi mở tool từ máy khác (qua tên miền). " if local else "")
                 + f"Mật khẩu mới ít nhất {A.MIN_PASSWORD} ký tự. Đổi xong, các máy khác đang đăng nhập bằng mật "
                   "khẩu cũ sẽ phải đăng nhập lại.").classes("text-sm muted")
        with ui.element("div").classes("w-full").style(
                "display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px"):
            cur = None if local else ui.input("Mật khẩu hiện tại", password=True, password_toggle_button=True).props(
                "outlined dense autocomplete=current-password")
            new = ui.input("Mật khẩu mới", password=True, password_toggle_button=True).props(
                "outlined dense autocomplete=new-password")
            again = ui.input("Nhập lại mật khẩu mới", password=True, password_toggle_button=True).props(
                "outlined dense autocomplete=new-password")
        err = ui.label().classes("text-sm").style(f"color:{T.RED}")

        def change_password():
            err.text = ""
            if (new.value or "") != (again.value or ""):
                err.text = "Hai lần nhập mật khẩu mới không khớp"
                return
            with connect() as c:
                settings = A.effective(c, cfg.access)
                if cur is not None:
                    ok, why, _ = A.login(c, settings, email, cur.value or "")
                    if not ok:
                        err.text = "Mật khẩu hiện tại không đúng" if "không đúng" in why else why
                        return
                try:
                    A.set_password(c, settings, email, new.value or "", must_change=False,
                                   by=email if local else "")
                except ValueError as e:
                    err.text = str(e)
                    return
                if not local:  # phiên mới gắn với mật khẩu mới (máy này không bị đăng xuất)
                    _, _, sess = A.login(c, settings, email, new.value)
                    app.storage.user["auth"] = sess
            for f in (cur, new, again):
                if f is not None:
                    f.value = ""
            from .live import kick
            kick(email=str(user), keep=ui.context.client.id)  # trang ở máy khác (mật khẩu cũ): ngắt
            ui.notify("Đã đổi mật khẩu", type="positive")

        with ui.row().classes("w-full justify-end"):
            ui.button("Đổi mật khẩu", icon="key", on_click=change_password).props("outline no-caps")
