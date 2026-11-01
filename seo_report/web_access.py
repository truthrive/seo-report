"""Màn Phân quyền (Quản trị): ai được vào tool khi mở từ máy khác, được sửa hay chỉ xem."""
from datetime import datetime

from . import access as A
from . import projects as PJ
from . import ui_theme as T


def _when(iso: str | None) -> str:
    return f"{datetime.fromisoformat(iso).astimezone():%d/%m/%Y}" if iso else "–"


def build_access_page(ui, cfg, connect, user, current: str | None = None) -> None:
    """connect: file dữ liệu chính (tài khoản, quyền theo dự án). current: dự án đang mở, chọn sẵn khi thêm người."""
    T.page_header(ui, "admin_panel_settings", "Phân quyền",
                  "Ai được đăng nhập, vào được website nào và làm được gì. Mở thẳng trên máy chạy tool luôn có toàn "
                  "quyền.",
                  eyebrow="Quản trị", tone="grey")

    def show_password(email: str, pw: str, must_change: bool) -> None:
        """Mật khẩu tool tạo chỉ hiện một lần: tool chỉ lưu dạng băm, không xem lại được."""
        with ui.dialog() as dlg, ui.card().style("border-radius:16px; min-width:440px"):
            ui.label("Mật khẩu tạm" if must_change else "Mật khẩu").classes("text-lg font-semibold")
            ui.label(f"Gửi riêng cho {email} (ví dụ qua Zalo)."
                     + (" Người dùng phải đổi sang mật khẩu riêng ở lần đăng nhập đầu." if must_change else "")
                     ).classes("text-sm muted")
            with ui.row().classes("w-full items-center no-wrap gap-2 q-mt-sm"):
                ui.label(pw).classes("col").style("font-family: var(--mono); font-size: 22px; font-weight: 600; "
                                                  "letter-spacing: .04em; background: #F4F4EF; border-radius: 10px; "
                                                  "padding: 10px 14px")
                ui.button(icon="content_copy", on_click=lambda: (ui.clipboard.write(pw),
                                                                 ui.notify("Đã chép mật khẩu"))).props(
                    "flat round").tooltip("Chép")
            ui.label("Mật khẩu này chỉ hiện một lần. Quên thì bấm 🔑 để đặt lại.").classes("text-xs muted q-mt-xs")
            ui.button("Đã chép, đóng", on_click=dlg.close).props("unelevated no-caps").classes("self-end q-mt-sm")
        dlg.open()

    def issue_password(email: str) -> None:
        """Đặt mật khẩu cho một email: để tool tạo ngẫu nhiên (mặc định) hoặc tự nhập; có thể bắt đổi ở lần đầu."""
        with ui.dialog() as dlg, ui.card().style("border-radius:16px; min-width:460px"):
            ui.label(f"Đặt mật khẩu cho {email}").classes("text-lg font-semibold")
            ui.label("Đặt lại mật khẩu sẽ đăng xuất người này khỏi mọi máy.").classes("text-xs muted")
            mode = ui.radio({"auto": "Để tool tạo mật khẩu ngẫu nhiên", "manual": "Tự nhập mật khẩu"},
                            value="auto").props("dense").classes("q-mt-sm")
            pw = ui.input(f"Mật khẩu (ít nhất {A.MIN_PASSWORD} ký tự)", password=True,
                          password_toggle_button=True).props("outlined dense autocomplete=new-password").classes(
                "w-full")
            pw.bind_visibility_from(mode, "value", value="manual")
            force = ui.checkbox("Bắt đổi mật khẩu ở lần đăng nhập đầu (nên bật: chỉ người dùng biết mật khẩu cuối "
                                "cùng của họ)", value=True).classes("q-mt-xs")
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")

            def save():
                value = A.temp_password() if mode.value == "auto" else (pw.value or "")
                try:
                    with connect() as c:
                        A.set_password(c, A.effective(c, cfg.access), email, value, must_change=force.value)
                except ValueError as e:
                    err.text = str(e)
                    return
                dlg.close()
                body.refresh()
                if mode.value == "auto":
                    show_password(email, value, force.value)
                else:
                    ui.notify(f"Đã đặt mật khẩu cho {email}" + (": người dùng sẽ phải đổi ở lần đăng nhập đầu"
                                                                 if force.value else ""), type="positive")

            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Lưu mật khẩu", on_click=save).props("unelevated no-caps")
        dlg.open()

    def projects() -> list[dict]:
        with connect() as c:
            return PJ.list_projects(c)

    @ui.refreshable
    def body():
        ps = projects()
        names = {p["slug"]: p["name"] for p in ps}
        first = ps[0]["slug"] if ps else None
        with connect() as c:
            us = A.users(c, cfg.access)
            mem = A.members(c)
        with T.section(ui, "Thêm người dùng", "person_add",
                       "Quản trị: mọi dự án, được sửa, quản lý dự án và phân quyền. Theo dự án: chỉ vào được các "
                       "website được gắn, mỗi website một quyền."):
            with ui.row().classes("w-full items-start gap-3"):
                email = ui.input("Email", placeholder="ten@congty.com").props("outlined dense").classes("col-3")
                kind = ui.select({A.MEMBER: "Theo dự án", A.ADMIN: "Quản trị (mọi dự án)"}, value=A.MEMBER,
                                 label="Loại tài khoản").props("outlined dense").classes("col-2")
                proj = ui.select(names, value=current if current in names else first, label="Dự án").props(
                    "outlined dense").classes("col-2")
                prole = ui.select(A.PROJECT_ROLES, value=A.CLIENT, label="Quyền trong dự án").props(
                    "outlined dense").classes("col-2")
                proj.bind_visibility_from(kind, "value", value=A.MEMBER)
                prole.bind_visibility_from(kind, "value", value=A.MEMBER)
                note = ui.input("Ghi chú", placeholder="ví dụ: khách hàng ABC").props("outlined dense").classes("col")

                def add():
                    try:
                        with connect() as c:
                            e = A.set_user(c, email.value, kind.value, user, note.value or "")
                            if kind.value == A.MEMBER:
                                A.set_member(c, e, proj.value, prole.value, user)
                    except ValueError as ex:
                        ui.notify(str(ex), type="warning")
                        return
                    email.value = note.value = ""
                    issue_password(e)  # đặt luôn mật khẩu để người đó đăng nhập được

                ui.button("Thêm", icon="add", on_click=add).props("unelevated no-caps").style("margin-top:2px")
            with ui.row().classes("items-start gap-2 no-wrap q-mt-xs"):
                ui.icon("info", size="16px").classes("muted")
                ui.label("Khách hàng: chỉ thấy Tổng quan, Báo cáo tuần / tháng, KPI cam kết, Công việc của website "
                         "đó. Chỉ xem: thêm các màn SEO / AI (không sửa). Được sửa: check rank (tốn tiền), sửa từ "
                         "khóa, nhóm URL, nhận xét, đồng bộ, lưu lên Drive.").classes("text-xs muted")

        admins = [u for u in us if u["role"] == A.ADMIN]
        others = [u for u in us if u["role"] != A.ADMIN]
        with T.section(ui, f"Người có quyền · {len(us)}", "group",
                       f"{len(admins)} quản trị · {len(others)} theo dự án"):
            if not us:
                ui.label("Chưa có ai. Thêm email ở trên.").classes("text-sm muted")
            for u in admins + others:
                person_row(u, mem.get(u["email"], {}), names, first)

        with ui.element("div").classes("sr-card q-pa-md w-full").style(f"background:{T.TONES['amber'][0]};"
                                                                       "border-color:#EAD7AE"):
            with ui.row().classes("items-start gap-2 no-wrap"):
                ui.icon("info", size="18px").style(f"color:{T.AMBER}")
                ui.label("Bấm 🔑 để đặt mật khẩu (tự nhập hoặc để tool tạo) rồi gửi riêng cho người đó; họ đăng "
                         "nhập bằng email + mật khẩu đó và chỉ thấy các website được gắn. Đổi hoặc gỡ quyền có hiệu "
                         "lực từ lần mở trang kế tiếp của họ. Người khác chỉ vào được khi tool được mở ra ngoài "
                         "(tên miền, Tailscale hoặc VPS), xem README mục 11.").classes("text-sm")

    def person_row(u: dict, mine: dict, names: dict, first: str | None) -> None:
        admin = u["role"] == A.ADMIN
        with ui.column().classes("sr-access-row w-full gap-1"):
            with ui.row().classes("w-full items-center no-wrap gap-3"):
                with ui.element("div").classes("sr-icon-bubble").style(
                        f"background:{T.TONES['green' if admin else 'blue'][0]}"):
                    ui.icon("admin_panel_settings" if admin else "person", size="16px").style(
                        f"color:{T.GREEN if admin else T.BLUE}")
                with ui.column().classes("col gap-0").style("min-width:0"):
                    ui.label(u["email"]).classes("text-sm font-medium ellipsis")
                    meta = [u["note"]] if u["note"] else []
                    meta.append("trong config.toml" if u["source"] == "config" else
                                f"thêm bởi {u['added_by']} · {_when(u['added_at'])}")
                    meta.append("chưa có mật khẩu" if not u["has_password"] else
                                "đang dùng mật khẩu tạm" if u["must_change"] else
                                f"đăng nhập lần cuối {_when(u['last_login'])}" if u["last_login"] else
                                "đã đặt mật khẩu")
                    ui.label(" · ".join(meta)).classes("text-xs muted ellipsis")
                ui.button(icon="key", on_click=lambda _, em=u["email"]: issue_password(em)).props(
                    "flat round dense color=grey-8").tooltip(
                    "Đặt mật khẩu" if not u["has_password"] else "Đặt lại mật khẩu (đăng xuất người này khỏi "
                                                                 "mọi máy)")
                if u["source"] == "config":
                    T.status_chip(ui, A.ROLE_LABEL[u["role"]], "green" if admin else "blue")
                    ui.icon("lock", size="16px").classes("muted").tooltip(
                        "Loại tài khoản khai báo trong config.toml: sửa hoặc gỡ trong file đó")
                else:
                    def change(e, em=u["email"], nt=u["note"], has=bool(mine)):
                        with connect() as c:
                            A.set_user(c, em, e.value, user, nt)
                        if e.value == A.MEMBER and not has:
                            ui.notify(f"{em} chưa được gắn dự án nào: gắn ít nhất một dự án để người này vào được",
                                      type="warning")
                        body.refresh()

                    ui.select({A.MEMBER: "Theo dự án", A.ADMIN: "Quản trị"}, value=u["role"],
                              on_change=change).props("outlined dense options-dense").classes("w-36")
                    ui.button(icon="person_remove", on_click=lambda _, em=u["email"]: ask_remove(em)).props(
                        "flat round dense").tooltip("Gỡ tài khoản")
            if admin:
                return
            with ui.row().classes("items-center gap-2 q-pl-xl").style("padding-left:44px"):
                legacy = u["source"] == "config" and first and first not in mine
                if legacy:  # email chỉ xem trong config.toml luôn xem được dự án đầu tiên
                    ui.label(f"{names.get(first, first)} · Chỉ xem (theo config.toml)").classes("text-xs muted")
                elif not mine:
                    ui.label("Chưa gắn dự án nào: chưa vào được tool").classes("text-xs").style(f"color:{T.RED}")
                for slug, role in mine.items():
                    with ui.row().classes("items-center no-wrap gap-1").style(
                            "background:#F4F4EF;border-radius:999px;padding:2px 4px 2px 12px"):
                        ui.label(names.get(slug, f"{slug} (đã lưu trữ)")).classes("text-xs font-medium")

                        def set_role(e, em=u["email"], sl=slug):
                            with connect() as c:
                                A.set_member(c, em, sl, e.value, user)
                            ui.notify(f"{em}: {A.PROJECT_ROLES[e.value].lower()} ở {names.get(sl, sl)}",
                                      type="positive")

                        ui.select(A.PROJECT_ROLES, value=role, on_change=set_role).props(
                            "dense borderless options-dense").classes("text-xs").style("min-width:96px")

                        def drop(_, em=u["email"], sl=slug):
                            with connect() as c:
                                A.remove_member(c, em, sl, user)
                            ui.notify(f"Đã gỡ {names.get(sl, sl)} khỏi {em}", type="positive")
                            body.refresh()

                        ui.button(icon="close", on_click=drop).props("flat round dense size=xs color=grey-7").tooltip(
                            "Gỡ dự án này")
                rest = {s_: n for s_, n in names.items() if s_ not in mine}
                if rest:
                    def attach(e, em=u["email"]):
                        if not e.value:
                            return
                        with connect() as c:
                            A.set_member(c, em, e.value, A.CLIENT, user)
                        ui.notify(f"Đã gắn {names[e.value]} cho {em} (quyền khách hàng, đổi được ngay bên cạnh)",
                                  type="positive")
                        body.refresh()

                    ui.select(rest, label="+ Gắn dự án", on_change=attach).props(
                        "dense outlined options-dense").classes("w-44")

    def ask_remove(em: str) -> None:
        with ui.dialog() as dlg, ui.card().style("border-radius:14px; min-width:420px"):
            ui.label(f"Gỡ tài khoản {em}?").classes("text-base font-semibold")
            ui.label("Người này sẽ không vào được tool nữa. Có thể thêm lại bất cứ lúc nào.").classes(
                "text-sm muted")
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")

                def go():
                    with connect() as c:
                        A.remove_user(c, em, user)
                    dlg.close()
                    ui.notify(f"Đã gỡ tài khoản {em}", type="positive")
                    body.refresh()
                ui.button("Gỡ tài khoản", on_click=go).props("unelevated color=negative no-caps")
        dlg.open()

    body()
