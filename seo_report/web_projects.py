"""Màn Dự án (Quản trị): mỗi dự án là một website có GSC, GA4, ngân sách check rank, sheet OKR và file dữ liệu riêng."""
from datetime import datetime

from . import access as A
from . import live as LIVE
from . import projects as PJ
from . import ui_theme as T

_syncing: set[str] = set()  # dự án đang lấy dữ liệu GSC (không cho bấm lấy hai lần cùng lúc)


def _when(iso: str | None) -> str:
    return f"{datetime.fromisoformat(iso).astimezone():%d/%m/%Y}" if iso else "–"


def _vn_date(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "–"


def build_projects_page(ui, base, app_connect, user) -> None:
    from nicegui import app, run

    right = T.page_header(ui, "domain", "Dự án", "Mỗi dự án là một website: số liệu, từ khóa, KPI và báo cáo tách "
                                                "riêng. Đổi dự án ở ô chọn trên thanh trên cùng.", eyebrow="Quản trị",
                          tone="grey")
    with right:
        ui.button("Thêm dự án", icon="add", on_click=lambda: edit_dialog(None)).props("unelevated no-caps")
    tool_email = {"value": None}  # email Google của tool (đọc nền, lưu lại để lần sau hiện ngay)

    async def google_options() -> tuple[dict, dict, str]:
        """Property GSC và GA4 tài khoản Google của tool truy cập được, để chọn thay vì gõ tay."""
        def work():
            from . import auth, ga4, gsc
            creds = auth.get_credentials(base, need=auth.ALL_SCOPES)
            sites = gsc.list_sites(auth.build_service(creds))
            props = ga4.list_properties(auth.build_ga4_admin(creds))
            return ({s["siteUrl"]: s["siteUrl"] for s in sorted(sites, key=lambda s: PJ.domain(s["siteUrl"]))},
                    {p["property"]: f"{p['name']} · {p['account']} ({p['property'].split('/')[-1]})" for p in props})
        try:
            gsc_opts, ga4_opts = await run.io_bound(work)
            return gsc_opts, ga4_opts, ""
        except (Exception, SystemExit) as e:  # noqa: BLE001  (không lấy được danh sách thì cho gõ tay)
            return {}, {}, f"Không lấy được danh sách từ Google ({e}). Gõ tay property."

    ga4_state: dict[str, dict] = {}  # property → kết quả đối chiếu luồng dữ liệu (cho danh sách dự án)

    async def check_ga4(prop: str, site_url: str) -> dict | None:
        """Đối chiếu luồng dữ liệu của property GA4 với website dự án; None khi không đọc được (thiếu quyền…)."""
        def work():
            from . import auth, ga4
            admin = auth.build_ga4_admin(auth.get_credentials(base, need=auth.ALL_SCOPES))
            return ga4.stream_check(site_url, ga4.web_streams(admin, prop))
        try:
            return await run.io_bound(work)
        except (Exception, SystemExit):  # noqa: BLE001
            return None

    async def confirm_ga4(message: str) -> bool:
        with ui.dialog() as d, ui.card().style("border-radius:14px; max-width:480px"):
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon("warning", size="22px").style(f"color:{T.AMBER}")
                ui.label("GA4 không khớp website").classes("text-base font-semibold")
            ui.label(message).classes("text-sm")
            ui.label("Chọn property khác, hoặc để trống ô GA4 đến khi có property đúng.").classes("text-xs muted")
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Chọn lại", on_click=lambda: d.submit(False)).props("unelevated no-caps")
                ui.button("Vẫn lưu", on_click=lambda: d.submit(True)).props("flat no-caps color=grey-8")
        return bool(await d)

    async def edit_dialog(project: dict | None) -> None:
        """Thêm dự án (project None) hoặc sửa cấu hình một dự án."""
        s = project["settings"] if project else PJ.DEFAULTS
        with ui.dialog() as dlg, ui.card().style("border-radius:16px; min-width:560px; max-width:640px"):
            ui.label(f"Sửa dự án {project['name']}" if project else "Thêm dự án").classes("text-lg font-semibold")
            loading = ui.element("div").classes("w-full")  # vòng xoay khi đang hỏi Google → dòng hướng dẫn khi xong
            with loading:
                T.spinner(ui, "Đang lấy danh sách property từ Google…", size="16px")
            name = ui.input("Tên dự án", value=project["name"] if project else "",
                            placeholder="ví dụ: Công ty ABC").props("outlined dense").classes("w-full")
            site = ui.select({}, label="Property Search Console", value=None, with_input=True, new_value_mode="add-unique"
                             ).props("outlined dense use-input hide-selected fill-input").classes("w-full")
            ga4 = ui.select({}, label="GA4 property (để trống nếu chưa có)", value=None, clearable=True,
                            with_input=True, new_value_mode="add-unique").props(
                "outlined dense use-input hide-selected fill-input").classes("w-full")
            brand = ui.input("Từ khóa thương hiệu (cách nhau dấu phẩy)", value=", ".join(s["brand_terms"]),
                             placeholder="ví dụ: abc, congtyabc").props("outlined dense").classes("w-full")
            ui.label("Query chứa các từ này được tách khỏi từ khóa SEO (không tính là head keyword).").classes(
                "text-xs muted")
            with ui.row().classes("w-full no-wrap gap-3"):
                budget = ui.number("Ngân sách check rank (USD/tháng)", value=s["rank_budget_usd"], min=0,
                                   step=5).props("outlined dense").classes("col")
                device = ui.select({"mobile": "Điện thoại", "desktop": "Máy tính"}, value=s["device"],
                                   label="Thiết bị check rank").props("outlined dense").classes("col")
            okr = ui.input("Link Sheet dự án: OKRs, Weekly Task Tracker, KPI cam kết (không bắt buộc)",
                           value=s["okr_sheet"]).props("outlined dense").classes("w-full")
            if project:  # logo: tự lấy từ website hoặc tải ảnh lên (dự án mới: tool tự lấy sau khi lưu)
                logo = {"value": project["logo"]}

                @ui.refreshable
                def logo_row():
                    with ui.row().classes("w-full items-center gap-3 no-wrap q-mt-xs"):
                        T.project_icon(ui, {**project, "logo": logo["value"]}, 40)
                        with ui.column().classes("col gap-0"):
                            ui.label("Logo").classes("text-sm font-medium")
                            ui.label("Hiện ở menu và ô đổi website. Ảnh vuông, dưới 300 KB.").classes(
                                "text-xs muted")

                        async def from_site():
                            ui.notify("Đang lấy logo từ website…")
                            uri = await run.io_bound(PJ.fetch_logo, site.value or project["site_url"])
                            if not uri:
                                ui.notify("Không lấy được logo từ website. Tải ảnh lên thay thế.", type="warning")
                                return
                            logo["value"] = uri
                            logo_row.refresh()

                        async def uploaded(e):
                            try:
                                logo["value"] = PJ.data_uri(await e.file.read(), e.file.content_type or "")
                            except ValueError as ex:
                                ui.notify(str(ex), type="warning")
                                return
                            logo_row.refresh()

                        ui.button("Lấy từ website", icon="travel_explore", on_click=from_site).props(
                            "flat dense no-caps")
                        up = ui.upload(on_upload=uploaded, auto_upload=True, max_file_size=PJ.MAX_LOGO_BYTES).props(
                            'accept="image/*" flat dense hide-upload-btn').classes("hidden")
                        ui.button("Tải ảnh lên", icon="upload", on_click=lambda: up.run_method("pickFiles")).props(
                            "flat dense no-caps")
                        if logo["value"]:
                            ui.button(icon="close", on_click=lambda: (logo.update(value=""), logo_row.refresh())
                                      ).props("flat round dense color=grey-7").tooltip("Bỏ logo")

                logo_row()

                # Quy tắc phân loại URL theo đường dẫn: lưu trong file dữ liệu của chính website này
                from contextlib import closing

                from . import db as DB
                from . import urls as U
                with closing(DB.connect(PJ.config_for(base, project).db_path)) as pc:
                    cur_rules = U.get_rules(pc)
                with ui.expansion("Phân loại URL theo đường dẫn", icon="rule",
                                  caption=f"{len(cur_rules['rules'])} quy tắc").classes("w-full q-mt-xs").props(
                        "dense"):
                    ui.label("Mỗi dòng: mẫu đường dẫn = loại trang. Dấu * thay cho bất kỳ chuỗi nào; dòng đầu tiên "
                             "khớp được dùng. Loại: " + ", ".join(U.TYPES) + ". URL không khớp quy tắc nào thì tool "
                             "đọc schema của trang.").classes("text-xs muted")
                    rules_box = ui.textarea(value=U.rules_text(cur_rules),
                                            placeholder="/danh-muc/ = Danh mục\n/danh-muc/* = Danh mục con\n"
                                                        "/blog/* = Blog\n/cua-hang* = Cửa hàng").props(
                        "outlined autogrow").classes("w-full").style("font-family: var(--mono); font-size: 12.5px")
                    deep = ui.checkbox("Đường dẫn nhiều cấp không khớp quy tắc nào là URL cũ/kỹ thuật",
                                       value=cur_rules["deep_legacy"]).props("dense")
            ui.label("Dự án chưa có sheet: màn KPI cam kết có wizard tạo sheet dự án từ sheet mẫu gốc. Dán link ở "
                     "đây thì tab KPI cam kết trong cùng file (nếu có) cũng được dùng.").classes("text-xs muted")
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")

            async def save():
                new_ga4 = ga4.value or ""
                if new_ga4 and new_ga4 != (project or {}).get("ga4_property") and (site.value or ""):
                    # gắn / đổi GA4: đối chiếu luồng dữ liệu với website (tránh gắn nhầm property website khác)
                    err.text = "Đang kiểm tra property GA4…"
                    from .config import _ga4_property
                    chk = await check_ga4(_ga4_property(new_ga4), site.value)
                    err.text = ""
                    if chk and chk["status"] in ("mismatch", "no_stream") and not await confirm_ga4(chk["message"]):
                        return
                    if chk and chk["status"] == "mixed":
                        ui.notify(chk["message"], type="warning", multi_line=True, timeout=10000, close_button="Đóng")
                    if chk is None:
                        ui.notify("Không đọc được luồng dữ liệu của property GA4 để đối chiếu (thiếu quyền?). Vẫn lưu.",
                                  type="info")
                fields = {"name": name.value, "site_url": site.value or "", "ga4_property": ga4.value or "",
                          "brand_terms": brand.value or "", "rank_budget_usd": budget.value, "device": device.value,
                          "okr_sheet": okr.value or "",
                          **({k: s.get(k) for k in ("location_code", "language_code", "se_domain", "okr_tab",
                                                     "weekly_tab",
                                                     "rank_paused")})}
                try:
                    with app_connect() as c:
                        p = (PJ.update(c, project["slug"], fields, user) if project
                             else PJ.create(c, base, fields, user))
                        if project and logo["value"] != project["logo"]:
                            PJ.set_logo(c, p["slug"], logo["value"], user)
                    if okr.value and okr.value != s.get("okr_sheet"):  # sheet dự án mới: dùng luôn cho KPI nếu chưa có
                        from contextlib import closing as _closing

                        from . import db as _DB
                        from . import kpi as KP
                        with _closing(_DB.connect(PJ.config_for(base, p).db_path)) as pc:
                            if not KP.sheet_id(pc):
                                try:
                                    KP.set_sheet(pc, okr.value)
                                except ValueError:
                                    pass
                    if project and (rules_box.value or "", deep.value) != (U.rules_text(cur_rules),
                                                                          cur_rules["deep_legacy"]):
                        with closing(DB.connect(PJ.config_for(base, p).db_path)) as pc:
                            changed = U.set_rules(pc, p["site_url"], rules_box.value or "", deep.value, user)
                        ui.notify(f"Đã lưu quy tắc phân loại URL · {changed} URL đổi loại", type="info")
                except ValueError as e:
                    err.text = str(e)
                    return
                dlg.close()
                if project:  # cấu hình đổi (GSC, GA4, ngân sách…): trang đang mở dự án này dựng lại
                    LIVE.kick(project=project["slug"], keep=ui.context.client.id)
                if not project:  # dự án mới: tự lấy logo của website (chạy nền)
                    fetch_logo_bg(p)
                ui.notify(f"Đã lưu dự án {p['name']}", type="positive")
                body.refresh()
                if not project:  # dự án mới: hỏi lấy dữ liệu GSC ngay
                    ask_sync(p)

            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Lưu dự án" if project else "Thêm dự án", on_click=save).props("unelevated no-caps")
        dlg.open()
        gsc_opts, ga4_opts, warn = await google_options()
        cur_site = project["site_url"] if project else None
        cur_ga4 = project["ga4_property"] if project else None
        with app_connect() as c:  # property đã có dự án khác thì không hiện trong danh sách chọn
            taken = {p["site_url"] for p in PJ.list_projects(c) if not project or p["slug"] != project["slug"]}
        gsc_opts = {k: v for k, v in gsc_opts.items() if k not in taken}
        if cur_site:
            gsc_opts.setdefault(cur_site, cur_site)
        if cur_ga4:
            ga4_opts.setdefault(cur_ga4, cur_ga4)
        site.set_options(gsc_opts, value=cur_site)
        ga4.set_options(ga4_opts, value=cur_ga4 or None)
        loading.clear()
        with loading:
            ui.label(warn or ("Chọn trong danh sách property tài khoản Google của tool truy cập được. Khách hàng "
                              "cần thêm email đó vào GSC / GA4 (quyền đọc) trước.")).classes("text-xs muted")

    def fetch_logo_bg(p: dict) -> None:
        from nicegui import background_tasks

        async def task():
            uri = await run.io_bound(PJ.fetch_logo, p["site_url"])
            if uri:
                with app_connect() as c:
                    PJ.set_logo(c, p["slug"], uri, user)
                try:
                    body.refresh()
                except Exception:  # noqa: BLE001  (người dùng đã rời trang)
                    pass
        background_tasks.create(task())

    def ask_sync(p: dict) -> None:
        with ui.dialog() as dlg, ui.card().style("border-radius:14px; min-width:440px"):
            ui.label(f"Lấy dữ liệu cho {p['name']}?").classes("text-base font-semibold")
            ui.label("Lần đầu tool lấy bù 16 tháng số liệu Search Console, có thể mất 10–30 phút. Cứ dùng tool "
                     "bình thường trong lúc chờ. Sau đó job hằng ngày tự cập nhật.").classes("text-sm muted")
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Để sau", on_click=dlg.close).props("flat no-caps")
                ui.button("Lấy dữ liệu ngay", on_click=lambda: (dlg.close(), start_sync(p))).props(
                    "unelevated no-caps")
        dlg.open()

    def start_sync(p: dict) -> None:
        """Lấy dữ liệu GSC cho một dự án trong luồng nền (không chặn giao diện)."""
        from nicegui import background_tasks
        if p["slug"] in _syncing:
            ui.notify("Dự án này đang lấy dữ liệu", type="info")
            return
        _syncing.add(p["slug"])
        body.refresh()
        ui.notify(f"Bắt đầu lấy dữ liệu cho {p['name']}. Có thể đóng trang này.", type="info")

        def work():
            from contextlib import closing

            from . import auth, db, urls
            from .sync import sync
            cfg = PJ.config_for(base, p)
            service = auth.build_service(auth.get_credentials(cfg))
            with closing(db.connect(cfg.db_path)) as con:
                n = sync(cfg, service, con, log=lambda m: None)
                urls.assign_urls(con, cfg.site_url)
            return n

        async def task():
            try:
                n = await run.io_bound(work)
                msg, kind = f"{p['name']}: đã lấy {n} ngày dữ liệu GSC", "positive"
            except (Exception, SystemExit) as e:  # noqa: BLE001
                msg, kind = f"{p['name']}: lấy dữ liệu lỗi ({e})", "negative"
            finally:
                _syncing.discard(p["slug"])
            try:  # người dùng có thể đã rời trang
                ui.notify(msg, type=kind)
                body.refresh()
            except Exception:  # noqa: BLE001
                pass
        background_tasks.create(task())

    def ask_archive(p: dict) -> None:
        with ui.dialog() as dlg, ui.card().style("border-radius:14px; min-width:440px"):
            ui.label(f"Lưu trữ dự án {p['name']}?").classes("text-base font-semibold")
            ui.label("Dự án bị ẩn khỏi ô chọn và job hằng ngày dừng lấy số liệu. Dữ liệu vẫn giữ nguyên; khôi phục "
                     "được bất cứ lúc nào.").classes("text-sm muted")
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")

                def go():
                    try:
                        with app_connect() as c:
                            PJ.archive(c, p["slug"], user)
                        LIVE.kick(project=p["slug"], keep=ui.context.client.id)
                    except ValueError as e:
                        ui.notify(str(e), type="warning")
                        return
                    if app.storage.user.get("project") == p["slug"]:
                        app.storage.user.pop("project", None)
                    dlg.close()
                    ui.notify(f"Đã lưu trữ {p['name']}", type="positive")
                    body.refresh()
                if not PJ.is_root(base, p):
                    ui.button("Xóa vĩnh viễn…", on_click=lambda: (dlg.close(), ask_delete(p))).props(
                        "flat color=negative no-caps").tooltip("Xóa hẳn dự án và dữ liệu, không khôi phục được")
                ui.button("Lưu trữ", on_click=go).props("unelevated color=negative no-caps")
        dlg.open()

    def ask_delete(p: dict) -> None:
        """Xóa vĩnh viễn (không hoàn tác được trên tool): hộp cảnh báo, bấm nút đỏ để xóa."""
        with ui.dialog() as dlg, ui.card().style("border-radius:14px; min-width:460px; max-width:94vw"):
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon("delete_forever", size="22px").style(f"color:{T.RED}")
                ui.label(f"Xóa vĩnh viễn dự án {p['name']}?").classes("text-base font-semibold")
            ui.label("Xóa hẳn dự án khỏi tool: số liệu GSC / GA4 đã lấy, từ khóa và lịch sử thứ hạng, backlink, KPI, "
                     "báo cáo, cùng mọi quyền của người được gắn vào dự án. Không khôi phục được trên tool.").classes(
                "text-sm")
            ui.label("File dữ liệu được chuyển vào thư mục data/da-xoa trên máy chạy tool (bản cuối, phòng xóa nhầm); "
                     "file trên Google Drive và sheet dự án giữ nguyên.").classes("text-xs muted")
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")

                def go():
                    try:
                        with app_connect() as c:
                            PJ.delete(c, base, p["slug"], user)
                        LIVE.kick(project=p["slug"], keep=ui.context.client.id)
                    except ValueError as e:
                        err.text = str(e)
                        return
                    if app.storage.user.get("project") == p["slug"]:
                        app.storage.user.pop("project", None)
                    dlg.close()
                    ui.notify(f"Đã xóa vĩnh viễn dự án {p['name']}", type="positive")
                    body.refresh()
                ui.button("Xóa vĩnh viễn", icon="delete_forever", on_click=go).props(
                    "unelevated color=negative no-caps")
        dlg.open()

    async def check_dialog(p: dict) -> None:
        """Kiểm tra kết nối GSC + GA4 của một dự án (gọi Google, vài giây) và hiện từng kết quả."""
        from . import connection_check as CC
        icons = {"ok": ("check_circle", T.GREEN), "warn": ("warning", T.AMBER), "error": ("error", T.RED)}
        with ui.dialog() as dlg, ui.card().style("border-radius:14px; width:560px; max-width:94vw"):
            ui.label(f"Kiểm tra kết nối · {p['name']}").classes("text-base font-semibold")
            ui.label(p["site_url"] + (" · " + p["ga4_property"] if p["ga4_property"] else "")).classes(
                "text-xs muted")
            box = ui.column().classes("w-full gap-2 q-mt-sm")
            with box:
                T.spinner(ui, "Đang hỏi Search Console và Google Analytics…")
            with ui.row().classes("w-full justify-end q-mt-sm"):
                ui.button("Đóng", on_click=dlg.close).props("flat no-caps")
        dlg.open()
        results = await run.io_bound(CC.run, base, p)
        box.clear()
        with box:
            for r in results:
                icon, color = icons[r["status"]]
                with ui.row().classes("items-start gap-2 no-wrap w-full"):
                    ui.icon(icon, size="20px").style(f"color:{color}; margin-top:1px")
                    with ui.column().classes("gap-0").style("min-width:0"):
                        ui.label(r["title"]).classes("text-sm font-semibold")
                        ui.label(r["message"]).classes("text-xs muted")
            bad = sum(1 for r in results if r["status"] == "error")
            warn = sum(1 for r in results if r["status"] == "warn")
            ui.label("Kết nối đúng, có số." if not bad and not warn else
                     f"{bad} lỗi cần sửa · {warn} điểm nên xem").classes("text-sm font-semibold q-mt-sm").style(
                f"color:{T.GREEN if not bad and not warn else T.RED if bad else T.AMBER}")

    def open_project(slug: str) -> None:
        app.storage.user["project"] = slug
        ui.navigate.to("/")

    @ui.refreshable
    def body():
        from . import access as A
        with app_connect() as c:
            active, all_ = PJ.list_projects(c), PJ.list_projects(c, archived=True)
            current = PJ.get(c, app.storage.user.get("project"))
            mem = A.members(c)
            team_all = sum(1 for u in A.users(c, base.access) if u.get("team_role"))
        archived = [p for p in all_ if p["archived_at"]]
        with T.section(ui, f"Dự án đang chạy · {len(active)}", "domain"):
            for p in active:
                st = PJ.status(base, p)
                n_clients = sum(1 for m in mem.values() if m.get(p["slug"]) == A.CLIENT)
                n_team = sum(1 for m in mem.values() if m.get(p["slug"]) in (A.VIEWER, A.EDITOR)) + team_all
                steps = PJ.setup_steps(base, p, st, n_clients + n_team)
                todo = [name for name, done in steps if not done]
                with ui.element("div").classes("sr-access-row sr-proj-row w-full"):
                    T.project_icon(ui, p, 36)
                    with ui.column().classes("col gap-0").style("min-width:0"):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.label(p["name"]).classes("text-sm font-semibold ellipsis")
                            if current and p["slug"] == current["slug"]:
                                T.status_chip(ui, "Đang mở", "green")
                            chk = ga4_state.get(p["ga4_property"]) if p["ga4_property"] else None
                            if chk and chk["status"] != "ok":  # GA4 gắn nhầm / lẫn website khác
                                with ui.element("span").tooltip(chk["message"]):
                                    T.status_chip(ui, "GA4 sai website" if chk["status"] == "mismatch"
                                                  else "GA4 lẫn website khác" if chk["status"] == "mixed"
                                                  else "GA4 chưa có luồng web", "red" if chk["status"] == "mismatch"
                                                  else "amber", "report")
                            if todo:  # status_chip không trả về phần tử: bọc để gắn chú thích
                                with ui.element("span").tooltip("Còn thiếu: " + ", ".join(todo)):
                                    T.status_chip(ui, f"Cài đặt {len(steps) - len(todo)}/{len(steps)}", "amber",
                                                  "checklist")
                        meta = [p["site_url"], "GA4 " + p["ga4_property"].split("/")[-1] if p["ga4_property"]
                                else "chưa gắn GA4", f"check rank {p['settings']['rank_budget_usd']:g} USD/tháng"]
                        ui.label(" · ".join(meta)).classes("text-xs muted ellipsis")
                        ui.label(("Đang lấy dữ liệu GSC…" if p["slug"] in _syncing else
                                  f"GSC: {st['days']} ngày, mới nhất {_vn_date(st['last'])}" if st["days"] else
                                  "Chưa có dữ liệu GSC") + f" · tạo {_when(p['created_at'])}").classes(
                            "text-xs muted")
                    ui.link(f"{n_team} team · {n_clients} khách", f"/access?project={p['slug']}").classes(
                        "sr-link text-xs").tooltip("Người vào được website này (chưa tính quản trị). Bấm để xem / sửa")
                    # Cột nút cố định (ô trống khi không có nút) để các dòng thẳng hàng
                    icon_btn = "flat round dense color=grey-8"
                    with ui.element("div").classes("sr-icon-slot"):
                        if p["slug"] in _syncing:
                            T.spinner(ui, "Đang lấy dữ liệu Search Console", visible_label=False).tooltip(
                                "Đang lấy dữ liệu Search Console")
                        elif not st["days"]:
                            ui.button(icon="cloud_download", on_click=lambda _, p=p: start_sync(p)).props(
                                icon_btn).tooltip("Lấy dữ liệu Search Console")
                        elif not current or p["slug"] != current["slug"]:
                            ui.button(icon="open_in_browser", on_click=lambda _, s=p["slug"]: open_project(s)).props(
                                icon_btn).tooltip("Mở website này")
                    with ui.element("div").classes("sr-icon-slot"):
                        ui.button(icon="fact_check", on_click=lambda _, p=p: check_dialog(p)).props(icon_btn).tooltip(
                            "Kiểm tra kết nối: Search Console và GA4 có đúng website, đọc được số không")
                    with ui.element("div").classes("sr-icon-slot"):
                        ui.button(icon="edit", on_click=lambda _, p=p: edit_dialog(p)).props(icon_btn).tooltip(
                            "Sửa cấu hình: GSC, GA4, ngân sách, logo, quy tắc URL")
                    with ui.element("div").classes("sr-icon-slot"):
                        if len(active) > 1:
                            ui.button(icon="inventory_2", on_click=lambda _, p=p: ask_archive(p)).props(
                                icon_btn).tooltip("Lưu trữ hoặc xóa vĩnh viễn dự án")
        if archived:
            with T.section(ui, f"Đã lưu trữ · {len(archived)}", "inventory_2"):
                for p in archived:
                    with ui.row().classes("sr-access-row w-full items-center no-wrap gap-3"):
                        with ui.column().classes("col gap-0").style("min-width:0"):
                            with ui.row().classes("items-center gap-2 no-wrap"):
                                ui.label(p["name"]).classes("text-sm font-medium ellipsis")
                                twin = next((a for a in active if PJ.domain(a["site_url"]) == PJ.domain(p["site_url"])),
                                            None)
                                if twin:
                                    T.status_chip(ui, f"Trùng website với {twin['name']}", "amber", "content_copy")
                            ui.label(f"{p['site_url']} · lưu trữ {_when(p['archived_at'])} bởi {p['archived_by']}"
                                     ).classes("text-xs muted ellipsis")

                        def restore(_, s=p["slug"], n=p["name"]):
                            with app_connect() as c:
                                PJ.restore(c, s, user)
                            ui.notify(f"Đã khôi phục {n}", type="positive")
                            body.refresh()
                        ui.button(icon="unarchive", on_click=restore).props("flat round dense color=grey-8").tooltip(
                            "Khôi phục dự án")
                        if not PJ.is_root(base, p):
                            ui.button(icon="delete_forever", on_click=lambda _, p=p: ask_delete(p)).props(
                                "flat round dense color=negative").tooltip("Xóa vĩnh viễn dự án")
        with ui.element("div").classes("sr-card q-pa-md w-full").style(f"background:{T.TONES['amber'][0]};"
                                                                       "border-color:#EAD7AE"):
            with ui.row().classes("items-start gap-2 no-wrap"):
                ui.icon("info", size="18px").style(f"color:{T.AMBER}")
                with ui.column().classes("gap-2"):
                    ui.label("Thêm website của khách: khách thêm email Google dưới đây vào Search Console và GA4 với "
                             "quyền đọc, rồi bấm Thêm dự án và chọn property. Mỗi dự án có file dữ liệu riêng nên số "
                             "liệu các khách không lẫn vào nhau. Cấp tài khoản cho khách ở màn Phân quyền: khách chỉ "
                             "thấy website được gắn.").classes("text-sm")
                    email = tool_email["value"]
                    with ui.row().classes("items-center gap-2"):
                        ui.label("Email Google của tool:").classes("text-sm font-semibold")
                        if email:
                            ui.label(email).classes("text-sm").style("font-family: var(--mono)")
                            ui.button(icon="content_copy", on_click=lambda e=email: (
                                ui.clipboard.write(e), ui.notify("Đã chép email"))).props(
                                "flat round dense color=grey-8").tooltip("Chép email")
                        elif email is None:
                            ui.label("đang đọc…").classes("text-sm muted")
                        else:
                            ui.label("chưa đọc được (kiểm tra đăng nhập Google của tool)").classes("text-sm muted")
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("settings", size="16px").classes("muted")
                        ui.link("Kết nối Google, thư mục Drive, sheet mẫu gốc, mã API: màn Cài đặt tích hợp",
                                "/cai-dat").classes("text-sm")

    body()

    async def load_ga4_checks():
        """Sau khi vẽ trang: đối chiếu GA4 của từng dự án với website, có lệch thì hiện nhãn đỏ / vàng ở dòng dự án."""
        with app_connect() as c:
            todo = [(p["ga4_property"], p["site_url"]) for p in PJ.list_projects(c) if p["ga4_property"]]
        for prop, site_url in todo:
            chk = await check_ga4(prop, site_url)
            if chk:
                ga4_state[prop] = chk
        if any(v["status"] != "ok" for v in ga4_state.values()):
            try:
                body.refresh()
            except Exception:  # noqa: BLE001  (người dùng đã rời trang)
                pass
    from nicegui import background_tasks as _bt
    _bt.create(load_ga4_checks())

    async def load_email():
        from . import auth
        with app_connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = c.execute("SELECT value FROM app_settings WHERE key = 'tool_google_email'").fetchone()
        if row and row[0]:
            tool_email["value"] = row[0]
            body.refresh()
        found = await run.io_bound(auth.account_email, base)
        if found and found != tool_email["value"]:
            with app_connect() as c:
                c.execute("INSERT OR REPLACE INTO app_settings VALUES ('tool_google_email', ?)", (found,))
                c.commit()
        tool_email["value"] = found or tool_email["value"] or ""
        body.refresh()

    from nicegui import background_tasks
    background_tasks.create(load_email())
