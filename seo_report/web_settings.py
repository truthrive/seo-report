"""Màn Cài đặt tích hợp (chỉ Chủ tool): tài khoản Google của tool, thư mục Drive + sheet mẫu gốc, DataForSEO, Google
Ads, AI. Mã bí mật chỉ hiện dạng che; kiểm tra kết nối trước khi lưu; sửa từ xa (qua tên miền) thì hỏi lại mật khẩu
đăng nhập; mọi lần đổi đều ghi nhật ký (không ghi giá trị mã)."""
from . import access as A
from . import integrations as I
from . import projects as PJ
from . import ui_theme as T
from . import urls as U

GOOGLE_NOTICES = {"ok": ("positive", "Đã kết nối Google với đủ quyền"),
                  "missing": ("warning", "Đã kết nối Google nhưng còn thiếu quyền: bấm Kết nối Google lại và tích đủ "
                                         "các ô"),
                  "cancel": ("warning", "Đã hủy kết nối Google"),
                  "expired": ("warning", "Phiên kết nối Google đã hết hạn: bấm Kết nối Google lại"),
                  "fail": ("negative", "Kết nối Google không thành công: thử lại sau ít phút")}


def build_settings_page(ui, base, app_connect, user, config_path, local: bool, google_origin: str | None,
                        google_notice: str | None = None) -> None:
    """local: đang mở trên máy chạy tool (không hỏi lại mật khẩu). google_origin: địa chỉ localhost để Google quay
    về sau khi đăng nhập (None khi mở qua tên miền)."""
    from nicegui import run

    owner = A.is_admin(user) or getattr(user, "role", None) == A.LOCAL
    T.page_header(ui, "settings", "Cài đặt tích hợp",
                  "Tài khoản và mã API tool dùng chung cho mọi website. Chỉ Chủ tool thấy màn này.", eyebrow="Quản trị",
                  tone="grey")
    if not owner:
        ui.label("Chỉ Chủ tool sửa được cài đặt tích hợp.").classes("text-sm muted")
        return
    if not local:
        T.status_chip(ui, "Đang mở qua tên miền: lưu mã API sẽ hỏi lại mật khẩu đăng nhập của bạn", "amber", "lock")

    async def confirm_identity() -> bool:
        """Sửa từ xa: hỏi lại mật khẩu đăng nhập (đếm sai như màn đăng nhập). Tại máy chạy tool thì không hỏi."""
        if local:
            return True
        import asyncio
        done: asyncio.Future = asyncio.get_running_loop().create_future()
        with ui.dialog() as d, ui.card().style("min-width: 400px; border-radius: 14px"):
            ui.label("Xác nhận mật khẩu").classes("text-lg font-semibold")
            ui.label("Nhập mật khẩu đăng nhập tool của bạn để lưu mã API.").classes("text-sm muted")
            pw = ui.input("Mật khẩu", password=True, password_toggle_button=True).props(
                "outlined dense autofocus autocomplete=current-password").classes("w-full")
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")

            def ok():
                with app_connect() as c:
                    good, why, _ = A.login(c, A.effective(c, base.access), str(user), pw.value or "")
                if not good:
                    err.text = why
                    return
                d.close()
                done.set_result(True) if not done.done() else None

            def cancel():
                d.close()
                done.set_result(False) if not done.done() else None
            pw.on("keydown.enter", ok)
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=cancel).props("flat no-caps")
                ui.button("Xác nhận", on_click=ok).props("unelevated no-caps")
        d.on("hide", lambda: done.set_result(False) if not done.done() else None)
        d.open()
        return await done

    def log(action: str, detail: str = "") -> None:
        with app_connect() as c:
            U.log_change(c, str(user), "tool", action, None, detail)

    # ---- Một thẻ tích hợp: trạng thái, ô nhập, Kiểm tra, Lưu ----
    def integration_card(it):
        with ui.element("div").classes("sr-card q-pa-md"):
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                ui.icon(it.icon, size="20px").style(f"color:{T.GREEN}")
                ui.label(it.name).classes("sr-section-title col")
                chip_box = ui.row()
            ui.label(it.about).classes("text-sm muted")
            cur = I.view(base, it.key)
            inputs, saved_labels = {}, {}
            for f in it.fields:
                if f.options:
                    inputs[f.key] = ui.select(f.options, value=cur.get(f.key) or next(iter(f.options)),
                                              label=f.label).props("outlined dense").classes("w-full")
                else:
                    inp = ui.input(f.label, value="" if f.secret else cur.get(f.key, ""),
                                   placeholder="nhập mã mới để thay" if f.secret and cur.get(f.key) else f.placeholder,
                                   password=f.secret, password_toggle_button=f.secret).props(
                        "outlined dense autocomplete=off").classes("w-full")
                    inputs[f.key] = inp
                notes = ([f"Đã lưu: {cur[f.key]} (để trống = giữ mã này)"] if f.secret and cur.get(f.key) else [])                     + ([f.hint] if f.hint else [])
                if notes:
                    saved_labels[f.key] = ui.label(" · ".join(notes)).classes("text-xs muted q-mb-xs")
            result = ui.label().classes("text-sm")

            def chip():
                chip_box.clear()
                with chip_box:
                    if I.configured(base, it.key):
                        T.status_chip(ui, "Đã cấu hình", "green", "check_circle")
                    else:
                        T.status_chip(ui, "Chưa cấu hình", "grey", "radio_button_unchecked")
            chip()

            async def check(save_after: bool):
                result.text = ""
                try:
                    values = I.merge(base, it.key, {k: v.value for k, v in inputs.items()})
                except ValueError as e:
                    result.text = str(e)
                    result.style(f"color:{T.RED}")
                    return
                btns = (test_btn, save_btn)
                for b in btns:
                    b.props("loading")
                try:
                    ok, msg = await run.io_bound(I.test, base, it.key, values)
                finally:
                    for b in btns:
                        b.props(remove="loading")
                result.text = msg
                result.style(f"color:{T.GREEN if ok else T.RED}")
                if not save_after:
                    return
                if not ok:  # mã mới không chạy: giữ mã cũ
                    result.text = msg + ". Chưa lưu: mã cũ vẫn giữ nguyên."
                    return
                if not await confirm_identity():
                    result.text = "Chưa lưu: chưa xác nhận mật khẩu."
                    result.style(f"color:{T.AMBER_TEXT}")
                    return
                I.save(base, it.key, values)
                changed = [f.label for f in it.fields if f.secret and (inputs[f.key].value or "").strip()]
                log(f"Đổi cấu hình {it.name}", ("đổi " + ", ".join(changed)) if changed else "đổi thông tin")
                for f in it.fields:  # không giữ mã trên trang sau khi lưu
                    if f.secret:
                        inputs[f.key].value = ""
                        if f.key in saved_labels:
                            saved_labels[f.key].text = (f"Đã lưu: {I.mask(values[f.key])} (để trống = giữ mã này)"
                                                        + (f" · {f.hint}" if f.hint else ""))
                result.text = msg + ". Đã lưu."
                chip()
                ui.notify(f"Đã lưu cấu hình {it.name}", type="positive")

            with ui.row().classes("w-full justify-end gap-2"):
                test_btn = ui.button("Kiểm tra kết nối", icon="wifi_tethering",
                                     on_click=lambda: check(False)).props("flat no-caps")
                save_btn = ui.button("Kiểm tra & lưu", icon="save", on_click=lambda: check(True)).props(
                    "unelevated no-caps")

    # ---- Trạng thái Google + nút Kết nối / Đổi tài khoản ----
    def google_status():
        from . import auth
        st = auth.granted_status(base)
        with ui.row().classes("items-center gap-2 w-full"):
            if not st["connected"]:
                T.status_chip(ui, "Chưa kết nối Google", "red", "link_off")
            elif st["missing"]:
                T.status_chip(ui, "Thiếu quyền: " + ", ".join(st["missing"]), "amber", "warning")
            else:
                T.status_chip(ui, "Đủ quyền Google", "green", "verified")
            ui.space()
            connect_btn = ui.button("Kết nối Google" if not st["connected"] or st["missing"] else "Cấp lại quyền",
                                    icon="login", on_click=lambda: go_google(False)).props("outline dense no-caps")
            switch_btn = ui.button("Đổi tài khoản", icon="switch_account",
                                   on_click=lambda: switch_dialog.open()).props("flat dense no-caps")
            if not google_origin:
                for b in (connect_btn, switch_btn):
                    b.disable()
                    b.tooltip("Mở tool trên máy chạy tool (http://localhost:8080) để kết nối Google: ứng dụng "
                              "Google của tool chỉ cho quay về địa chỉ localhost")

    def go_google(switch: bool):
        from . import auth
        if not google_origin or not owner:
            return
        try:
            url = auth.web_login_url(base, f"{google_origin}/oauth/google", switch_account=switch)
        except ValueError as e:
            ui.notify(str(e), type="negative")
            return
        ui.navigate.to(url)

    with ui.dialog() as switch_dialog, ui.card().style("max-width: 480px; border-radius: 14px"):
        ui.label("Đổi tài khoản Google của tool?").classes("text-lg font-semibold")
        ui.label("Mọi dự án dùng chung một tài khoản Google để đọc Search Console, Analytics, Sheets, Drive và Google "
                 "Ads. Tài khoản mới phải có quyền vào property GSC / GA4 và sheet của các website, nếu không lịch lấy "
                 "số sẽ báo lỗi.").classes("text-sm")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Hủy", on_click=switch_dialog.close).props("flat no-caps")
            ui.button("Chọn tài khoản khác", icon="switch_account",
                      on_click=lambda: (switch_dialog.close(), go_google(True))).props("unelevated no-caps")

    # ---- Dựng màn: Google, Drive, rồi từng tích hợp ----
    grid = ui.element("div").classes("w-full").style(
        "display:grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 12px; align-items: start")

    # ---- Tài khoản Google + Drive ----
    with grid:
        with ui.element("div").classes("sr-card q-pa-md"):
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon("account_circle", size="20px").style(f"color:{T.BLUE}")
                ui.label("Tài khoản Google").classes("sr-section-title")
            ui.label("Một tài khoản Google đọc Search Console, Analytics, Sheets, Drive và Google Ads cho mọi website. "
                     "Khách thêm email này vào GSC / GA4 với quyền đọc.").classes("text-sm muted")
            email_lab = ui.label("đang đọc email…").classes("text-sm").style("font-family: var(--mono)")
            google_status()

        with ui.element("div").classes("sr-card q-pa-md"):
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon("folder", size="20px").style(f"color:{T.AMBER}")
                ui.label("Google Drive").classes("sr-section-title")
            ui.label("Thư mục chứa mọi file tool tạo (báo cáo xuất lên Drive, sheet dự án). Trống = My Drive.").classes(
                "text-sm muted")
            folder = ui.input("Link hoặc ID thư mục", value=(f"https://drive.google.com/drive/folders/"
                                                             f"{base.drive_parent}" if base.drive_parent else "")).props(
                "outlined dense clearable").classes("w-full")

            def save_folder():
                from .config import _folder_id
                fid = _folder_id(folder.value or "")
                if (folder.value or "").strip() and not fid:
                    ui.notify("Link thư mục Drive chưa đúng", type="warning")
                    return
                I.set_drive_folder(config_path, fid)
                base.drive_parent = fid  # trang mở sau dùng ngay; lịch hằng ngày đọc config.toml
                log("Đổi thư mục Google Drive", fid or "My Drive")
                ui.notify("Đã lưu thư mục Drive", type="positive")
            with ui.row().classes("w-full justify-end"):
                ui.button("Lưu thư mục", on_click=save_folder).props("outline no-caps")
            ui.separator().classes("q-my-sm")
            with app_connect() as c:
                master_now = PJ.master_sheet(c)
            master_in = ui.input("Sheet mẫu gốc cho dự án mới", value=(
                f"https://docs.google.com/spreadsheets/d/{master_now}/edit" if master_now else ""),
                placeholder="Link Google Sheet mẫu (OKRs, Weekly Task, Chi phí…)").props(
                "outlined dense clearable").classes("w-full")
            ui.label("Wizard ở màn KPI cam kết copy file này thành sheet của dự án mới.").classes("text-xs muted")

            def save_master():
                try:
                    with app_connect() as c:
                        sid = PJ.set_master_sheet(c, master_in.value or "")
                except ValueError as e:
                    ui.notify(str(e), type="warning")
                    return
                log("Đổi sheet mẫu gốc", sid or "(bỏ)")
                ui.notify("Đã lưu sheet mẫu gốc" if sid else "Đã bỏ sheet mẫu gốc", type="positive")
            with ui.row().classes("w-full justify-end"):
                ui.button("Lưu sheet mẫu", on_click=save_master).props("outline no-caps")

        for it in I.INTEGRATIONS:
            integration_card(it)

    if google_notice in GOOGLE_NOTICES:
        kind, text = GOOGLE_NOTICES[google_notice]
        ui.notify(text, type=kind, multi_line=True)

    async def load_email():
        from . import auth
        found = await run.io_bound(auth.account_email, base)
        email_lab.text = found or "chưa đọc được email (kiểm tra kết nối Google)"
        if found:
            with app_connect() as c:
                c.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                c.execute("INSERT OR REPLACE INTO app_settings VALUES ('tool_google_email', ?)", (found,))
                c.commit()
    from nicegui import background_tasks
    background_tasks.create(load_email())
