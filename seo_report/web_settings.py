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
    # Chất lượng dữ liệu (kiểm tra số GA4 / GSC của dự án đang mở) không còn trên menu: lối tắt ở đây
    with ui.row().classes("items-center gap-1 q-mb-sm"):
        ui.icon("verified", size="16px").classes("muted")
        ui.link("Chất lượng dữ liệu của dự án đang mở (kiểm tra số GA4 / Search Console)",
                "/ai?tab=chat-luong").classes("text-sm")

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

    # ---- Một dòng cài đặt: biểu tượng · tên · tóm tắt · trạng thái · nút; bấm Sửa mới mở phần nhập ----
    def setting_row(icon: str, tone: str, title: str):
        """Trả (ô tóm tắt, chỗ trạng thái, chỗ nút, phần sửa ẩn sẵn)."""
        with ui.element("div").classes("sr-card sr-set-row w-full"):
            with ui.row().classes("w-full items-center gap-3 no-wrap"):
                with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES[tone][0]}"):
                    ui.icon(icon, size="18px").style(f"color:{T.TONES[tone][1]}")
                with ui.column().classes("gap-0 col").style("min-width:0"):
                    ui.label(title).classes("text-sm font-semibold")
                    summary = ui.label().classes("text-xs muted ellipsis")
                status = ui.row().classes("items-center no-wrap")
                actions = ui.row().classes("items-center gap-1 no-wrap")
            editor = ui.column().classes("w-full gap-2 sr-set-editor")
            editor.set_visibility(False)
        return summary, status, actions, editor

    def chip(box, ok: bool, text_ok: str, text_no: str, tone_no: str = "grey"):
        box.clear()
        with box:
            T.status_chip(ui, text_ok if ok else text_no, "green" if ok else tone_no,
                          "check_circle" if ok else "radio_button_unchecked")

    def toggle(editor, btn):
        editor.set_visibility(not editor.visible)
        btn.text = "Đóng" if editor.visible else "Sửa"

    def summary_of(it) -> str:
        v = I.view(base, it.key)
        if it.key == "dataforseo":
            return f"{v.get('login') or 'chưa có login'} · password {v.get('password') or 'chưa có'}"
        if it.key == "google_ads":
            return (f"MCC {v.get('login_customer_id') or '–'} · Customer ID {v.get('customer_id') or '–'} · "
                    f"token {v.get('developer_token') or 'chưa có'}")
        if it.key == "google_api":
            return (f"key {v['api_key']} · PageSpeed Insights, Chrome UX Report" if v.get("api_key")
                    else "Chưa có: trang Tốc độ & Core Web Vitals chưa lấy được số")
        if it.key == "ai":
            return (I.AI_MODELS.get(v.get("model") or "", v.get("model") or "") + f" · khóa {v['api_key']}"
                    if v.get("api_key") else "Chuẩn bị cho tính năng AI sau này")
        return ""

    def integration_card(it):
        summary, status, actions, editor = setting_row(it.icon, "green" if it.key != "ai" else "purple", it.name)

        def paint():
            summary.text = summary_of(it)
            on = I.configured(base, it.key)
            chip(status, on, "Đã cấu hình", "Chưa dùng" if it.key == "ai" else "Chưa cấu hình",
                 "grey" if it.key == "ai" else "amber")
        paint()
        with actions:
            edit_btn = ui.button("Sửa", icon="edit", on_click=lambda: toggle(editor, edit_btn)).props(
                "flat dense no-caps")
        with editor:
            ui.label(it.about).classes("text-xs muted")
            cur = I.view(base, it.key)
            inputs = {}
            with ui.element("div").classes("w-full").style(
                    "display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px"):
                for f in it.fields:
                    if f.options:
                        inputs[f.key] = ui.select(f.options, value=cur.get(f.key) or next(iter(f.options)),
                                                  label=f.label).props("outlined dense").classes("w-full")
                        continue
                    ph = (f"Đã lưu {cur[f.key]} · để trống giữ nguyên" if f.secret and cur.get(f.key)
                          else f.placeholder)
                    inp = ui.input(f.label, value="" if f.secret else cur.get(f.key, ""), placeholder=ph,
                                   password=f.secret, password_toggle_button=f.secret).props(
                        "outlined dense stack-label autocomplete=off hide-hint").classes("w-full")
                    if f.hint:
                        inp.props["hint"] = f.hint  # hiện khi đang gõ vào ô
                    inputs[f.key] = inp
            result = ui.label().classes("text-sm")

            async def check(save_after: bool):
                result.text = ""
                try:
                    values = I.merge(base, it.key, {k: v.value for k, v in inputs.items()})
                except ValueError as e:
                    result.text = str(e)
                    result.style(f"color:{T.RED}")
                    return
                for b in (test_btn, save_btn):
                    b.props("loading")
                try:
                    ok, msg = await run.io_bound(I.test, base, it.key, values)
                finally:
                    for b in (test_btn, save_btn):
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
                        inputs[f.key].props["placeholder"] = f"Đã lưu {I.mask(values[f.key])} · để trống giữ nguyên"
                        inputs[f.key].update()
                paint()
                toggle(editor, edit_btn)
                ui.notify(f"Đã lưu {it.name}. {msg}", type="positive", multi_line=True)

            with ui.row().classes("w-full items-center justify-end gap-2"):
                test_btn = ui.button("Kiểm tra", on_click=lambda: check(False)).props(
                    "flat dense no-caps color=grey-8").tooltip("Thử kết nối, chưa lưu")
                ui.button("Hủy", on_click=lambda: toggle(editor, edit_btn)).props("flat no-caps")
                save_btn = ui.button("Lưu", icon="check", on_click=lambda: check(True)).props(
                    "unelevated no-caps").tooltip("Tool thử kết nối trước; không chạy thì không lưu")

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

    # ---- Dựng màn: nhóm Tài khoản Google (Google, Drive), nhóm Mã API dịch vụ ----
    page = ui.column().classes("w-full gap-2").style("max-width: 920px")
    with page:
        ui.label("Tài khoản Google").classes("sr-nav-group q-mt-sm")
        g_summary, g_status, g_actions, _ = setting_row("account_circle", "blue", "Tài khoản Google")
        g_summary.text = "đang đọc email…"
        from . import auth
        st = auth.granted_status(base)
        g_status.clear()
        with g_status:
            if not st["connected"]:
                T.status_chip(ui, "Chưa kết nối", "red", "link_off")
            elif st["missing"]:
                T.status_chip(ui, "Thiếu quyền: " + ", ".join(st["missing"]), "amber", "warning")
            else:
                T.status_chip(ui, "Đủ quyền", "green", "verified")
        with g_actions:
            connect_btn = ui.button("Kết nối" if not st["connected"] or st["missing"] else "Cấp lại quyền",
                                    on_click=lambda: go_google(False)).props("flat dense no-caps")
            switch_btn = ui.button("Đổi tài khoản", on_click=lambda: switch_dialog.open()).props(
                "flat dense no-caps color=grey-8")
            if not google_origin:
                for b in (connect_btn, switch_btn):
                    b.disable()
                    b.tooltip("Mở tool trên máy chạy tool (http://localhost:8080) để kết nối Google: ứng dụng "
                              "Google của tool chỉ cho quay về địa chỉ localhost")

        d_summary, d_status, d_actions, d_editor = setting_row("folder", "amber", "Google Drive")
        with app_connect() as c:
            master_now = PJ.master_sheet(c)

        def d_paint():
            with app_connect() as c:
                m = PJ.master_sheet(c)
            d_summary.text = (f"Thư mục: {'…' + base.drive_parent[-8:] if base.drive_parent else 'My Drive'} · "
                              f"Sheet mẫu gốc: {'đã gắn' if m else 'chưa gắn'}")
            chip(d_status, bool(base.drive_parent), "Đã chọn thư mục", "Đang dùng My Drive")
        d_paint()
        with d_actions:
            d_btn = ui.button("Sửa", icon="edit", on_click=lambda: toggle(d_editor, d_btn)).props("flat dense no-caps")
        with d_editor:
            ui.label("Mọi file tool tạo (báo cáo xuất lên Drive, sheet dự án) nằm trong thư mục này. Sheet mẫu gốc: "
                     "wizard ở màn KPI cam kết copy file này thành sheet của dự án mới.").classes("text-xs muted")
            folder = ui.input("Thư mục Google Drive (link hoặc ID)", value=(
                f"https://drive.google.com/drive/folders/{base.drive_parent}" if base.drive_parent else ""),
                placeholder="để trống = My Drive").props("outlined dense stack-label clearable").classes("w-full")
            master_in = ui.input("Sheet mẫu gốc cho dự án mới", value=(
                f"https://docs.google.com/spreadsheets/d/{master_now}/edit" if master_now else ""),
                placeholder="link Google Sheet mẫu (OKRs, Weekly Task, Chi phí…)").props(
                "outlined dense stack-label clearable").classes("w-full")

            def save_drive():
                from .config import _folder_id
                fid = _folder_id(folder.value or "")
                if (folder.value or "").strip() and not fid:
                    ui.notify("Link thư mục Drive chưa đúng", type="warning")
                    return
                try:
                    with app_connect() as c:
                        sid = PJ.set_master_sheet(c, master_in.value or "")
                except ValueError as e:
                    ui.notify(str(e), type="warning")
                    return
                if fid != base.drive_parent:
                    I.set_drive_folder(config_path, fid)
                    base.drive_parent = fid  # trang mở sau dùng ngay; lịch hằng ngày đọc config.toml
                    log("Đổi thư mục Google Drive", fid or "My Drive")
                if sid != master_now:
                    log("Đổi sheet mẫu gốc", sid or "(bỏ)")
                d_paint()
                toggle(d_editor, d_btn)
                ui.notify("Đã lưu cài đặt Google Drive", type="positive")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=lambda: toggle(d_editor, d_btn)).props("flat no-caps")
                ui.button("Lưu", icon="check", on_click=save_drive).props("unelevated no-caps")

        ui.label("Mã API dịch vụ").classes("sr-nav-group q-mt-md")
        for it in I.INTEGRATIONS:
            integration_card(it)
        ui.label("Mã lưu trong thư mục secrets/ của máy chạy tool, không đưa lên git; trang chỉ hiện 4 ký tự cuối. "
                 "Mỗi lần đổi đều ghi nhật ký.").classes("text-xs muted q-mt-sm")

    if google_notice in GOOGLE_NOTICES:
        kind, text = GOOGLE_NOTICES[google_notice]
        ui.notify(text, type=kind, multi_line=True)

    async def load_email():
        from . import auth
        found = await run.io_bound(auth.account_email, base)
        g_summary.text = (f"{found} · khách thêm email này vào Search Console / GA4 với quyền đọc" if found
                          else "chưa đọc được email (kiểm tra kết nối Google)")
        if found:
            with app_connect() as c:
                c.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                c.execute("INSERT OR REPLACE INTO app_settings VALUES ('tool_google_email', ?)", (found,))
                c.commit()
    from nicegui import background_tasks
    background_tasks.create(load_email())
