"""Màn Phân quyền (Quản trị): ai được đăng nhập, vào được website nào, làm được gì.

Người dùng chia hai nhóm: Team nội bộ (Chủ tool, team mọi website, team theo từng website) và Khách hàng (chỉ có quyền
Khách hàng ở website của họ). Thêm / sửa quyền qua một hộp thoại, gắn nhiều website một lần; hạ quyền hoặc gỡ website
phải xác nhận. Mọi thay đổi ghi vào Nhật ký.
"""
from datetime import datetime

from . import access as A
from . import live as LIVE
from . import presence as PR
from . import projects as PJ
from . import ui_theme as T

TITLES = ["SEO", "Content", "SEO Leader", "Dev", "Quản lý", "Khách hàng"]  # gợi ý chức danh (gõ tự do được)
RANK = {A.CLIENT: 0, A.VIEWER: 1, A.EDITOR: 2}  # để nhận ra hạ quyền


def _when(iso: str | None) -> str:
    return f"{datetime.fromisoformat(iso).astimezone():%d/%m/%Y}" if iso else "–"


def _when_time(iso: str | None) -> str:
    return f"{datetime.fromisoformat(iso).astimezone():%d/%m/%Y %H:%M}" if iso else "–"


def _setting(connect, key: str, value: str | None = None) -> str:
    """Giá trị lưu trong app_settings (link tool cho tin mời)."""
    with connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        if value is not None:
            c.execute("INSERT OR REPLACE INTO app_settings VALUES (?, ?)", (key, value.strip()))
            c.commit()
            return value.strip()
        row = c.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else ""


def build_access_page(ui, cfg, connect, user, current: str | None = None, preset_project: str | None = None) -> None:
    """connect: file dữ liệu chính (tài khoản, quyền theo dự án). current: dự án đang mở (chọn sẵn khi thêm người);
    preset_project: lọc sẵn theo dự án (mở từ màn Dự án)."""
    with connect() as c:
        ps = PJ.list_projects(c)
    names = {p["slug"]: p["name"] for p in ps}
    by_slug = {p["slug"]: p for p in ps}
    first = ps[0]["slug"] if ps else None
    view = {"tab": "team", "q": "", "project": preset_project if preset_project in names else ""}

    # Hộp thoại gắn vào khung cố định: mở từ nút trong danh sách thì danh sách làm mới (body.refresh) không xóa mất
    dialogs = ui.element("div")
    right = T.page_header(ui, "admin_panel_settings", "Phân quyền",
                          "Ai được đăng nhập, vào được website nào và làm được gì. Mở thẳng trên máy chạy tool luôn "
                          "có toàn quyền.", eyebrow="Quản trị", tone="grey")
    with right:
        ui.button("Thêm người", icon="person_add", on_click=lambda: edit_dialog(None)).props("unelevated no-caps")

    # ---------------- Mật khẩu + tin mời ----------------

    def invite_text(email: str, pw: str, must_change: bool) -> str:
        url = _setting(connect, "public_url").rstrip("/")
        link = f"{url}/login" if url else "<link tool>"
        return (f"Chào bạn, mời bạn dùng SEO Report để xem báo cáo SEO.\n"
                f"Đăng nhập: {link}\n{'Tên đăng nhập' if A.is_username(email) else 'Email'}: {email}\n"
                f"Mật khẩu: {pw}\n"
                + ("Lần đầu đăng nhập, bạn có thể đặt mật khẩu riêng hoặc bỏ qua và dùng tiếp mật khẩu này. "
                   if must_change else "")
                + "Đổi mật khẩu bất cứ lúc nào: bấm vào tên của bạn ở góc dưới bên trái > Đổi mật khẩu. "
                  "Vui lòng không chia sẻ mật khẩu cho người khác.")

    def show_password(email: str, pw: str, must_change: bool) -> None:
        """Mật khẩu tool tạo chỉ hiện một lần (tool chỉ lưu dạng băm). Kèm tin mời soạn sẵn để dán vào Zalo."""
        with dialogs, ui.dialog() as dlg, ui.card().style("border-radius:16px; min-width:480px; max-width:560px"):
            ui.label(f"Mật khẩu của {email}").classes("text-lg font-semibold ellipsis")
            with ui.row().classes("w-full items-center no-wrap gap-2 q-mt-xs"):
                ui.label(pw).classes("col").style("font-family: var(--mono); font-size: 22px; font-weight: 600; "
                                                  "letter-spacing: .04em; background: #F4F4EF; border-radius: 10px; "
                                                  "padding: 10px 14px")
                ui.button(icon="content_copy", on_click=lambda: (ui.clipboard.write(pw),
                                                                 ui.notify("Đã chép mật khẩu"))).props(
                    "flat round").tooltip("Chép mật khẩu")
            ui.label("Mật khẩu chỉ hiện một lần. Quên thì bấm 🔑 để đặt lại.").classes("text-xs muted")
            ui.separator().classes("q-my-sm")
            ui.label("Tin mời soạn sẵn").classes("text-sm font-semibold")
            link = ui.input("Địa chỉ tool", value=_setting(connect, "public_url"),
                            placeholder="https://report.tenmien.com").props("outlined dense").classes("w-full")
            ui.label("Tin mời dùng địa chỉ này kèm /login. Lưu một lần, dùng cho mọi tin mời sau.").classes(
                "text-xs muted")
            msg = ui.textarea(value=invite_text(email, pw, must_change)).props("outlined autogrow readonly").classes(
                "w-full")

            def on_link(e):
                _setting(connect, "public_url", e.value or "")
                msg.value = invite_text(email, pw, must_change)
            link.on_value_change(on_link)
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Chép tin mời", icon="content_copy",
                          on_click=lambda: (ui.clipboard.write(msg.value), ui.notify("Đã chép tin mời"))).props(
                    "outline no-caps")
                ui.button("Xong", on_click=dlg.close).props("unelevated no-caps")
        dlg.open()

    def issue_password(email: str) -> None:
        """Đặt mật khẩu cho một email: để tool tạo ngẫu nhiên (mặc định) hoặc tự nhập; có thể bắt đổi ở lần đầu."""
        with dialogs, ui.dialog() as dlg, ui.card().style("border-radius:16px; min-width:460px"):
            ui.label(f"Đặt mật khẩu cho {email}").classes("text-lg font-semibold")
            ui.label("Đặt lại mật khẩu sẽ đăng xuất người này khỏi mọi máy.").classes("text-xs muted")
            mode = ui.radio({"auto": "Để tool tạo mật khẩu ngẫu nhiên", "manual": "Tự nhập mật khẩu"},
                            value="auto").props("dense").classes("q-mt-sm")
            pw = ui.input(f"Mật khẩu (ít nhất {A.MIN_PASSWORD} ký tự)", password=True,
                          password_toggle_button=True).props("outlined dense autocomplete=new-password").classes(
                "w-full")
            pw.bind_visibility_from(mode, "value", value="manual")
            force = ui.checkbox("Gợi ý người này đặt mật khẩu riêng ở lần đăng nhập đầu (có nút bỏ qua, không bắt "
                                "buộc)", value=True).classes("q-mt-xs")
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")

            def save():
                value = A.temp_password() if mode.value == "auto" else (pw.value or "")
                try:
                    with connect() as c:
                        A.set_password(c, A.effective(c, cfg.access), email, value, must_change=force.value, by=user)
                    LIVE.kick(email=email, keep=ui.context.client.id)  # đặt lại mật khẩu: ngắt trang đang mở
                except ValueError as e:
                    err.text = str(e)
                    return
                dlg.close()
                body.refresh()
                show_password(email, value, force.value)

            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Để sau", on_click=dlg.close).props("flat no-caps")
                ui.button("Lưu mật khẩu", on_click=save).props("unelevated no-caps")
        dlg.open()

    # ---------------- Thêm / sửa quyền ----------------

    def edit_dialog(u: dict | None, restore: dict | None = None) -> None:
        """Thêm người (u None), sửa quyền một người, hoặc cấp lại tài khoản đã gỡ (restore)."""
        with connect() as c:
            mine = dict(A.members(c).get(u["email"], {})) if u else {}
        base = u or restore or {}
        locked_admin = bool(u and u["source"] == "config" and u["role"] == A.ADMIN)
        if u is None and not restore and current in names:
            mine_default = {current: A.CLIENT}  # thêm mới: chọn sẵn website đang mở, quyền Khách hàng
        else:
            mine_default = mine
        start_kind = ("admin" if base.get("role") == A.ADMIN else "team_all" if base.get("team_role")
                      else "project")
        rows = {slug: {"on": slug in mine_default, "role": mine_default.get(slug, A.CLIENT)} for slug in names}
        team_role = None

        with dialogs, ui.dialog() as dlg, ui.card().style("border-radius:16px; width:640px; max-width:96vw"):
            ui.label("Thêm người" if not u and not restore else
                     f"Cấp lại {base['email']}" if restore else f"Quyền của {u['email']}").classes(
                "text-lg font-semibold")
            with ui.row().classes("w-full no-wrap gap-3 q-mt-xs"):
                email = ui.input("Email hoặc tên đăng nhập", value=base.get("email", ""),
                                 placeholder="ten@congty.com hoặc khach-abc").props(
                    "outlined dense" + (" readonly" if base else "")).classes("col")
                title = ui.select(TITLES, value=base.get("title") or None, label="Chức danh (không bắt buộc)",
                                  with_input=True, new_value_mode="add-unique", clearable=True).props(
                    "outlined dense use-input hide-selected fill-input").classes("col-4")
            note = ui.input("Ghi chú", value=base.get("note", ""),
                            placeholder="ví dụ: khách hàng ABC, phụ trách blog").props("outlined dense").classes(
                "w-full")
            if locked_admin:
                with ui.row().classes("q-mt-sm"):
                    T.status_chip(ui, "Chủ tool: toàn quyền mọi website (khai trong config.toml)", "green", "lock")
                kind = None
            else:
                kind = ui.radio({"project": "Theo từng website", "team_all": "Team · mọi website"},
                                value=start_kind if start_kind != "admin" else "team_all").props(
                    "dense inline").classes("q-mt-sm")
                with ui.row().classes("items-center gap-2") as team_box:
                    ui.label("Quyền chung ở mọi website, kể cả website thêm sau:").classes("text-sm")
                    team_role = ui.select(A.TEAM_ROLES, value=base.get("team_role") or A.VIEWER).props(
                        "outlined dense options-dense").classes("w-36")
                team_box.bind_visibility_from(kind, "value", value="team_all")

                with ui.column().classes("w-full gap-0 q-mt-xs") as proj_box:
                    hint = ui.label().classes("text-xs muted q-mb-xs")

                    def sync_hint():
                        hint.text = ("Quyền riêng ở từng website (không bắt buộc, ưu tiên hơn quyền chung)."
                                     if kind.value == "team_all" else "Chọn website và quyền ở mỗi website.")
                    sync_hint()
                    for slug, p in by_slug.items():
                        r = rows[slug]
                        with ui.row().classes("w-full items-center no-wrap gap-3 sr-access-row").style(
                                "padding:6px 4px"):
                            cb = ui.checkbox(value=r["on"]).props("dense")
                            T.project_icon(ui, p, 26)
                            ui.label(p["name"]).classes("col text-sm ellipsis")
                            sel = ui.select(A.PROJECT_ROLES, value=r["role"]).props(
                                "outlined dense options-dense").classes("w-40")
                            sel.bind_enabled_from(cb, "value")
                            cb.on_value_change(lambda e, s_=slug: rows[s_].update(on=e.value))
                            sel.on_value_change(lambda e, s_=slug: rows[s_].update(role=e.value))
                kind.on_value_change(lambda _: sync_hint())
            with ui.column().classes("gap-0 q-mt-sm"):
                for name, what in (("Khách hàng", "chỉ xem Tổng quan, Báo cáo, KPI cam kết, Công việc & OKR"),
                                   ("Team xem", "người nội bộ: xem thêm mọi màn SEO / AI (URL, từ khóa, index, "
                                                "chất lượng dữ liệu), không sửa"),
                                   ("Được sửa", "thêm check rank (tốn tiền, có trần ngân sách), sửa từ khóa, nhóm "
                                                "URL, nhận xét, lưu Drive")):
                    with ui.row().classes("no-wrap gap-1 items-baseline"):
                        ui.label(name + ":").classes("text-xs font-semibold").style("white-space:nowrap")
                        ui.label(what).classes("text-xs muted")
                ui.label("Dự án, Phân quyền, Ngân sách: chỉ Chủ tool.").classes("text-xs muted q-mt-xs")
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")

            def plan() -> dict:
                """Thay đổi sẽ áp dụng; kèm danh sách gỡ / hạ quyền để hỏi xác nhận."""
                k = kind.value if kind else "admin"
                want = {s_: r["role"] for s_, r in rows.items() if r["on"]} if k != "admin" else dict(mine)
                drops = [names.get(s_, s_) for s_ in mine if s_ not in want]
                downs = [f"{names.get(s_, s_)}: {A.PROJECT_ROLES[mine[s_]]} → {A.PROJECT_ROLES[want[s_]]}"
                         for s_ in want if s_ in mine and RANK[want[s_]] < RANK[mine[s_]]]
                if u and u["role"] == A.ADMIN and k != "admin":
                    downs.append("Quản trị → không còn quản trị")
                if u and u.get("team_role") and (k != "team_all" or RANK[team_role.value] < RANK[u["team_role"]]):
                    downs.append("Quyền Team mọi website: " + A.TEAM_ROLES[u["team_role"]] + " → "
                                 + (A.TEAM_ROLES[team_role.value] if k == "team_all" else "bỏ"))
                return {"kind": k, "want": want, "drops": drops, "downs": downs}

            def apply(pl: dict) -> None:
                k = pl["kind"]
                try:
                    with connect() as c:
                        e = A.set_user(c, email.value, A.ADMIN if k == "admin" else A.MEMBER, user, note.value or "",
                                       title=title.value or "",
                                       team_role=(team_role.value if k == "team_all" else None) if kind else A.KEEP)
                        if k != "admin":
                            for s_, role in pl["want"].items():
                                A.set_member(c, e, s_, role, user)
                            for s_ in mine:
                                if s_ not in pl["want"]:
                                    A.remove_member(c, e, s_, user)
                    LIVE.kick(email=e, keep=ui.context.client.id)  # quyền đổi: trang đang mở của người này dựng lại
                except ValueError as ex:
                    err.text = str(ex)
                    return
                dlg.close()
                ui.notify(f"Đã lưu quyền của {e}", type="positive")
                body.refresh()
                with connect() as c:
                    has_pw = next((x["has_password"] for x in A.users(c, cfg.access) if x["email"] == e), False)
                if not has_pw:
                    issue_password(e)  # người mới / cấp lại: đặt luôn mật khẩu để gửi tin mời

            def save():
                err.text = ""
                if not (email.value or "").strip():
                    err.text = "Chưa nhập email hoặc tên đăng nhập"
                    return
                pl = plan()
                if pl["kind"] == "project" and not pl["want"]:
                    err.text = "Chọn ít nhất một website (hoặc chọn Team · mọi website)"
                    return
                if not (pl["drops"] or pl["downs"]):
                    apply(pl)
                    return
                with ui.dialog() as cf, ui.card().style("border-radius:14px; min-width:420px"):
                    ui.label("Xác nhận giảm quyền").classes("text-base font-semibold")
                    for line in [f"Gỡ website: {d}" for d in pl["drops"]] + [f"Hạ quyền: {d}" for d in pl["downs"]]:
                        ui.label("• " + line).classes("text-sm")
                    ui.label("Có hiệu lực từ lần mở trang kế tiếp của người này.").classes("text-xs muted")
                    with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                        ui.button("Hủy", on_click=cf.close).props("flat no-caps")
                        ui.button("Đồng ý", on_click=lambda: (cf.close(), apply(pl))).props(
                            "unelevated color=negative no-caps")
                cf.open()

            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Lưu", on_click=save).props("unelevated no-caps")
        dlg.open()

    def ask_remove(em: str) -> None:
        with dialogs, ui.dialog() as dlg, ui.card().style("border-radius:14px; min-width:420px"):
            ui.label(f"Gỡ tài khoản {em}?").classes("text-base font-semibold")
            ui.label("Người này không vào được tool nữa và bị đăng xuất. Tài khoản chuyển xuống mục Đã gỡ, cấp lại "
                     "được bất cứ lúc nào.").classes("text-sm muted")
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")

                def go():
                    with connect() as c:
                        A.remove_user(c, em, user)
                    LIVE.kick(email=em, keep=ui.context.client.id)
                    dlg.close()
                    ui.notify(f"Đã gỡ tài khoản {em}", type="positive")
                    body.refresh()
                ui.button("Gỡ tài khoản", on_click=go).props("unelevated color=negative no-caps")
        dlg.open()

    # ---------------- Danh sách ----------------

    def access_chips(u: dict, mine: dict, k: str) -> None:
        with ui.row().classes("items-center gap-1 q-mt-xs").style("padding-left:44px"):
            if k == "admin":
                T.status_chip(ui, "Chủ tool · toàn quyền: mọi website, dự án, phân quyền, ngân sách", "green",
                              "admin_panel_settings")
                return
            if u.get("team_role"):
                T.status_chip(ui, f"Mọi website · {A.TEAM_ROLES[u['team_role']]}", "blue", "public")
            if u["source"] == "config" and not mine and first:  # email config.toml chưa chuyển vào tool
                mine = {first: A.VIEWER}
            for slug, role in mine.items():
                p = by_slug.get(slug)
                with ui.row().classes("items-center no-wrap gap-1").style(
                        "background:#F4F4EF;border-radius:999px;padding:2px 10px 2px 3px"):
                    if p:
                        T.project_icon(ui, p, 20)
                    ui.label(names.get(slug, f"{slug} (đã lưu trữ)")).classes("text-xs font-medium")
                    ui.label("·").classes("text-xs muted")
                    ui.label(A.PROJECT_ROLES[role]).classes("text-xs muted")
            if not mine and not u.get("team_role"):
                ui.label("Chưa gắn website nào: chưa vào được tool").classes("text-xs").style(f"color:{T.RED}")

    # Chấm trạng thái (online / vắng mặt / offline) tự cập nhật mỗi 20 giây, không dựng lại cả danh sách
    @ui.refreshable
    def presence_avatar(email: str, last_seen: str | None, tone: str, name: str = "", photo: str = "") -> None:
        st, text = PR.describe(email, last_seen)
        T.presence_avatar(ui, name or email, st, text, size=32, tone=tone, photo=photo)

    @ui.refreshable
    def presence_text(email: str, last_seen: str | None) -> None:
        st, text = PR.describe(email, last_seen)
        ui.label(text).classes("text-xs").style(
            f"color:{T.GREEN if st == PR.AVAILABLE else T.AMBER_TEXT if st == PR.AWAY else T.MUTED};"
            "font-weight:600" if st != PR.OFFLINE else f"color:{T.MUTED}")

    ui.timer(20, lambda: (presence_avatar.refresh(), presence_text.refresh()))

    def person_row(u: dict, mine: dict, k: str) -> None:
        tone = {"admin": "green", "team": "blue", "client": "amber"}[k]
        with connect() as c:
            pf = A.profiles(c).get(u["email"], {})  # tên / ảnh người dùng tự đặt ở màn Hồ sơ
        with ui.column().classes("sr-access-row w-full gap-0"):
            with ui.row().classes("w-full items-center no-wrap gap-3"):
                presence_avatar(u["email"], u.get("last_seen"), tone, pf.get("name", ""), pf.get("avatar", ""))
                with ui.column().classes("col gap-0").style("min-width:0"):
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        if pf.get("name"):
                            ui.label(pf["name"]).classes("text-sm font-medium ellipsis")
                            ui.label(u["email"]).classes("text-xs muted ellipsis")
                        else:
                            ui.label(u["email"]).classes("text-sm font-medium ellipsis")
                        if u.get("title"):
                            T.status_chip(ui, u["title"], "grey")
                        presence_text(u["email"], u.get("last_seen"))
                    meta = [u["note"]] if u["note"] else []
                    meta.append("trong config.toml" if u["source"] == "config" else
                                f"thêm bởi {u['added_by']} · {_when(u['added_at'])}")
                    meta.append("chưa có mật khẩu" if not u["has_password"] else
                                "đang dùng mật khẩu được cấp" if u["must_change"] else
                                f"đăng nhập lần cuối {_when(u['last_login'])}" if u["last_login"] else
                                "chưa đăng nhập lần nào")
                    ui.label(" · ".join(meta)).classes("text-xs muted ellipsis")
                ui.button(icon="key", on_click=lambda _, em=u["email"]: issue_password(em)).props(
                    "flat round dense color=grey-8").tooltip(
                    "Đặt mật khẩu" if not u["has_password"] else "Đặt lại mật khẩu (đăng xuất người này khỏi mọi máy)")
                ui.button(icon="edit", on_click=lambda _, x=u: edit_dialog(x)).props(
                    "flat round dense color=grey-8").tooltip("Sửa quyền, chức danh, ghi chú")
                if u["source"] == "config" and u["role"] == A.ADMIN:
                    ui.icon("lock", size="18px").classes("muted").style("margin:0 6px").tooltip(
                        "Chủ tool khai trong config.toml (không gỡ được ở đây)")
                else:
                    ui.button(icon="person_remove", on_click=lambda _, em=u["email"]: ask_remove(em)).props(
                        "flat round dense color=grey-8").tooltip("Gỡ tài khoản")
            access_chips(u, mine, k)

    @ui.refreshable
    def body():
        with connect() as c:
            us = A.users(c, cfg.access)
            mem = A.members(c)
            gone = A.removed_users(c)
            log = A.log_entries(c) if view["tab"] == "log" else []
        people = [(u, mem.get(u["email"], {}), A.kind(u, mem.get(u["email"], {}))) for u in us]
        counts = {"team": sum(k != "client" for *_, k in people), "client": sum(k == "client" for *_, k in people)}

        with ui.row().classes("w-full items-center gap-3 q-mb-sm"):
            def tab(e):
                view["tab"] = e.value
                body.refresh()
            ui.toggle({"team": f"Team nội bộ · {counts['team']}", "client": f"Khách hàng · {counts['client']}",
                       "log": "Nhật ký"}, value=view["tab"], on_change=tab).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
            ui.space()
            if view["tab"] != "log":
                def search(e):
                    view["q"] = (e.value or "").strip().lower()
                    body.refresh()
                ui.input(placeholder="Tìm email, chức danh, ghi chú", value=view["q"], on_change=search).props(
                    "outlined dense clearable debounce=400").classes("w-64")

                def pick(e):
                    view["project"] = e.value or ""
                    body.refresh()
                ui.select({"": "Mọi website", **names}, value=view["project"], on_change=pick).props(
                    "outlined dense options-dense").classes("w-52")

        if view["tab"] == "log":
            with T.section(ui, "Nhật ký phân quyền", "history", "300 thay đổi gần nhất: thêm / gỡ tài khoản, gắn / "
                                                               "gỡ website, đổi quyền, đặt mật khẩu"):
                if not log:
                    ui.label("Chưa có thay đổi nào (nhật ký bắt đầu ghi từ 01/11/2026).").classes("text-sm muted")
                for r in log:
                    detail = r["detail"]
                    for slug, n in names.items():  # mã dự án → tên dự án
                        if detail == slug:
                            detail = n
                        elif detail.startswith(slug + ":"):
                            detail = n + detail[len(slug):]
                    with ui.row().classes("sr-access-row w-full items-center no-wrap gap-3"):
                        ui.label(_when_time(r["at"])).classes("text-xs muted num").style("width:118px;flex-shrink:0")
                        ui.label(r["action"]).classes("text-sm font-medium").style("width:150px;flex-shrink:0")
                        ui.label(r["email"]).classes("text-sm ellipsis").style("width:230px;flex-shrink:0")
                        ui.label(detail).classes("col text-sm muted ellipsis")
                        ui.label(f"bởi {r['by']}").classes("text-xs muted ellipsis").style("max-width:220px")
            return

        q, proj = view["q"], view["project"]

        def visible(u, mine, k) -> bool:
            if (k == "client") != (view["tab"] == "client"):
                return False
            if q and not any(q in (u.get(f) or "").lower() for f in ("email", "title", "note")):
                return False
            if proj:  # người vào được website đang lọc (quản trị và team mọi website luôn vào được)
                legacy = u["source"] == "config" and not mine and first == proj
                return k == "admin" or bool(u.get("team_role")) or proj in mine or legacy
            return True

        shown = [x for x in people if visible(*x)]
        client_tab = view["tab"] == "client"
        title = ("Khách hàng" if client_tab else "Team nội bộ") + f" · {len(shown)}"
        sub = (f"Người vào được {names[proj]}" if proj else
               "Người chỉ có quyền Khách hàng ở website của họ" if client_tab else
               "Chủ tool, team mọi website và team theo từng website")
        with T.section(ui, title, "storefront" if client_tab else "groups", sub):
            if not shown:
                ui.label("Không có ai khớp bộ lọc." if (q or proj) else
                         "Chưa có ai. Bấm Thêm người ở góc trên.").classes("text-sm muted")
            order = {"admin": 0, "team": 1, "client": 2}
            for u, mine, k in sorted(shown, key=lambda x: (order[x[2]], x[0]["email"])):
                person_row(u, mine, k)

        if gone:
            with ui.expansion(f"Đã gỡ · {len(gone)}", icon="person_off").classes("w-full sr-card"):
                for g in gone:
                    with ui.row().classes("sr-access-row w-full items-center no-wrap gap-3"):
                        with ui.column().classes("col gap-0").style("min-width:0"):
                            ui.label(g["email"]).classes("text-sm ellipsis")
                            ui.label(f"gỡ {_when(g['removed_at'])} bởi {g['removed_by'] or '–'}"
                                     + (f" · {g['note']}" if g["note"] else "")).classes("text-xs muted ellipsis")
                        ui.button("Cấp lại", icon="restart_alt",
                                  on_click=lambda _, x=g: edit_dialog(None, restore=x)).props("flat dense no-caps")

        with ui.element("div").classes("sr-card q-pa-md w-full").style(f"background:{T.TONES['amber'][0]};"
                                                                       "border-color:#EAD7AE"):
            with ui.row().classes("items-start gap-2 no-wrap"):
                ui.icon("info", size="18px").style(f"color:{T.AMBER}")
                ui.label("Thêm người xong, tool tạo mật khẩu và soạn sẵn tin mời (kèm link đăng nhập) để dán vào Zalo. "
                         "Người được mời dùng luôn mật khẩu đó, đổi sang mật khẩu riêng nếu muốn. Đổi hoặc gỡ quyền "
                         "có hiệu lực từ lần mở trang kế tiếp của người đó.").classes("text-sm")

    body()
