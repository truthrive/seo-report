"""Màn Dự án (Quản trị): mỗi dự án là một website có GSC, GA4, ngân sách check rank, sheet OKR và file dữ liệu riêng."""
from datetime import datetime

from . import projects as PJ
from . import ui_theme as T

_syncing: set[str] = set()  # dự án đang lấy dữ liệu GSC (không cho bấm lấy hai lần cùng lúc)


def _when(iso: str | None) -> str:
    return f"{datetime.fromisoformat(iso).astimezone():%d/%m/%Y}" if iso else "–"


def _vn_date(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "–"


def build_projects_page(ui, base, app_connect, user) -> None:
    from nicegui import app, run

    T.page_header(ui, "domain", "Dự án", "Mỗi dự án là một website: số liệu, từ khóa, KPI và báo cáo tách riêng. "
                                        "Đổi dự án ở ô chọn trên thanh trên cùng.", eyebrow="Quản trị", tone="grey")

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

    async def edit_dialog(project: dict | None) -> None:
        """Thêm dự án (project None) hoặc sửa cấu hình một dự án."""
        s = project["settings"] if project else PJ.DEFAULTS
        with ui.dialog() as dlg, ui.card().style("border-radius:16px; min-width:560px; max-width:640px"):
            ui.label(f"Sửa dự án {project['name']}" if project else "Thêm dự án").classes("text-lg font-semibold")
            loading = ui.label("Đang lấy danh sách property từ Google…").classes("text-xs muted")
            name = ui.input("Tên dự án", value=project["name"] if project else "",
                            placeholder="ví dụ: Mắt Kính Tâm Đức").props("outlined dense").classes("w-full")
            site = ui.select({}, label="Property Search Console", value=None, with_input=True, new_value_mode="add-unique"
                             ).props("outlined dense use-input hide-selected fill-input").classes("w-full")
            ga4 = ui.select({}, label="GA4 property (để trống nếu chưa có)", value=None, clearable=True,
                            with_input=True, new_value_mode="add-unique").props(
                "outlined dense use-input hide-selected fill-input").classes("w-full")
            brand = ui.input("Từ khóa thương hiệu (cách nhau dấu phẩy)", value=", ".join(s["brand_terms"]),
                             placeholder="ví dụ: tâm đức, matkinhtamduc").props("outlined dense").classes("w-full")
            ui.label("Query chứa các từ này được tách khỏi từ khóa SEO (không tính là head keyword).").classes(
                "text-xs muted")
            with ui.row().classes("w-full no-wrap gap-3"):
                budget = ui.number("Ngân sách check rank (USD/tháng)", value=s["rank_budget_usd"], min=0,
                                   step=5).props("outlined dense").classes("col")
                device = ui.select({"mobile": "Điện thoại", "desktop": "Máy tính"}, value=s["device"],
                                   label="Thiết bị check rank").props("outlined dense").classes("col")
            okr = ui.input("Link Google Sheet OKR / Weekly Task (không bắt buộc)", value=s["okr_sheet"]).props(
                "outlined dense").classes("w-full")
            ui.label("Sheet KPI cam kết gắn ở màn KPI cam kết của từng dự án.").classes("text-xs muted")
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")

            async def save():
                fields = {"name": name.value, "site_url": site.value or "", "ga4_property": ga4.value or "",
                          "brand_terms": brand.value or "", "rank_budget_usd": budget.value, "device": device.value,
                          "okr_sheet": okr.value or "",
                          **({k: s[k] for k in ("location_code", "language_code", "okr_tab", "weekly_tab")})}
                try:
                    with app_connect() as c:
                        p = (PJ.update(c, project["slug"], fields, user) if project
                             else PJ.create(c, base, fields, user))
                except ValueError as e:
                    err.text = str(e)
                    return
                dlg.close()
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
        loading.text = warn or ("Chọn trong danh sách property tài khoản Google của tool truy cập được. Khách hàng "
                                "cần thêm email đó vào GSC / GA4 (quyền đọc) trước.")

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
                    except ValueError as e:
                        ui.notify(str(e), type="warning")
                        return
                    if app.storage.user.get("project") == p["slug"]:
                        app.storage.user.pop("project", None)
                    dlg.close()
                    ui.notify(f"Đã lưu trữ {p['name']}", type="positive")
                    body.refresh()
                ui.button("Lưu trữ", on_click=go).props("unelevated color=negative no-caps")
        dlg.open()

    def open_project(slug: str) -> None:
        app.storage.user["project"] = slug
        ui.navigate.to("/")

    @ui.refreshable
    def body():
        with app_connect() as c:
            active, all_ = PJ.list_projects(c), PJ.list_projects(c, archived=True)
            current = PJ.get(c, app.storage.user.get("project"))
        archived = [p for p in all_ if p["archived_at"]]
        with T.section(ui, f"Dự án đang chạy · {len(active)}", "domain"):
            with ui.row().classes("w-full justify-end"):
                ui.button("Thêm dự án", icon="add", on_click=lambda: edit_dialog(None)).props("unelevated no-caps")
            for p in active:
                st = PJ.status(base, p)
                with ui.row().classes("sr-access-row w-full items-center no-wrap gap-3"):
                    with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['green'][0]}"):
                        ui.icon("language", size="16px").style(f"color:{T.GREEN}")
                    with ui.column().classes("col gap-0").style("min-width:0"):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.label(p["name"]).classes("text-sm font-semibold ellipsis")
                            if current and p["slug"] == current["slug"]:
                                T.status_chip(ui, "Đang mở", "green")
                        meta = [p["site_url"], "GA4 " + p["ga4_property"].split("/")[-1] if p["ga4_property"]
                                else "chưa gắn GA4", f"check rank {p['settings']['rank_budget_usd']:g} USD/tháng"]
                        ui.label(" · ".join(meta)).classes("text-xs muted ellipsis")
                        ui.label(("Đang lấy dữ liệu GSC…" if p["slug"] in _syncing else
                                  f"GSC: {st['days']} ngày, mới nhất {_vn_date(st['last'])}" if st["days"] else
                                  "Chưa có dữ liệu GSC") + f" · tạo {_when(p['created_at'])}").classes(
                            "text-xs muted")
                    if p["slug"] in _syncing:
                        ui.spinner(size="20px")
                    elif not st["days"]:
                        ui.button("Lấy dữ liệu", icon="cloud_download", on_click=lambda _, p=p: start_sync(p)).props(
                            "outline dense no-caps")
                    if not current or p["slug"] != current["slug"]:
                        ui.button("Mở", on_click=lambda _, s=p["slug"]: open_project(s)).props("flat dense no-caps")
                    ui.button(icon="edit", on_click=lambda _, p=p: edit_dialog(p)).props(
                        "flat round dense color=grey-8").tooltip("Sửa cấu hình")
                    if len(active) > 1:
                        ui.button(icon="inventory_2", on_click=lambda _, p=p: ask_archive(p)).props(
                            "flat round dense color=grey-8").tooltip("Lưu trữ (ẩn, không xóa dữ liệu)")
        if archived:
            with T.section(ui, f"Đã lưu trữ · {len(archived)}", "inventory_2"):
                for p in archived:
                    with ui.row().classes("sr-access-row w-full items-center no-wrap gap-3"):
                        with ui.column().classes("col gap-0").style("min-width:0"):
                            ui.label(p["name"]).classes("text-sm font-medium ellipsis")
                            ui.label(f"{p['site_url']} · lưu trữ {_when(p['archived_at'])} bởi {p['archived_by']}"
                                     ).classes("text-xs muted ellipsis")

                        def restore(_, s=p["slug"], n=p["name"]):
                            with app_connect() as c:
                                PJ.restore(c, s, user)
                            ui.notify(f"Đã khôi phục {n}", type="positive")
                            body.refresh()
                        ui.button("Khôi phục", icon="unarchive", on_click=restore).props("flat dense no-caps")
        with ui.element("div").classes("sr-card q-pa-md w-full").style(f"background:{T.TONES['amber'][0]};"
                                                                       "border-color:#EAD7AE"):
            with ui.row().classes("items-start gap-2 no-wrap"):
                ui.icon("info", size="18px").style(f"color:{T.AMBER}")
                ui.label("Thêm website của khách: khách thêm email Google của tool vào Search Console và GA4 với quyền "
                         "đọc, rồi chọn property ở đây. Mỗi dự án có file dữ liệu riêng nên số liệu các khách không "
                         "lẫn vào nhau. Phân quyền khách hàng theo từng dự án sẽ làm ở giai đoạn 2; hiện ai đăng "
                         "nhập được đều xem được mọi dự án.").classes("text-sm")

    body()
