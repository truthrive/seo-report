"""Nút "Xuất" dùng chung: tải Excel về máy, lưu Google Sheets lên Drive, và (với báo cáo) Google Slides + PDF.

Mọi thao tác chạy ngay trong sự kiện bấm nút (không qua background_tasks), vì ui.download / ui.notify cần biết trang
nào đang bấm. Việc nặng (tạo file, gọi Drive) chạy bằng run.io_bound.
"""
from typing import Callable


def export_menu(ui, cfg, connect, name: str, make_xlsx: Callable[[], bytes] | Callable,
                make_pptx: Callable | None = None, label: str = "Xuất", user=None) -> None:
    """name: tên file (không đuôi). make_xlsx / make_pptx: hàm (có thể async) trả về bytes. Người chỉ xem (user) chỉ
    tải file về máy, không lưu vào Drive của chủ tool."""
    import inspect

    from nicegui import run

    from . import drive as D
    from .access import can_edit

    async def produce(fn):
        res = fn()
        if inspect.isawaitable(res):
            res = await res
        return res

    async def busy(coro):
        btn.props("loading")
        note = ui.notification("Đang tạo file…", spinner=True, timeout=None, type="ongoing", position="bottom-right")
        try:
            return await coro
        finally:
            btn.props(remove="loading")
            note.dismiss()

    async def download_excel():
        try:
            data = await busy(produce(make_xlsx))
            ui.download.content(data, f"{name}.xlsx")
        except Exception as e:  # noqa: BLE001
            ui.notify(f"Không xuất được: {e}", type="negative", multi_line=True)

    async def download_pptx():
        try:
            data = await busy(produce(make_pptx))
            ui.download.content(data, f"{name}.pptx")
        except Exception as e:  # noqa: BLE001
            ui.notify(f"Không xuất được: {e}", type="negative", multi_line=True)

    def done(links: list[tuple[str, str]], folder: str):
        with ui.dialog() as dlg, ui.card().style("min-width: 460px; border-radius: 14px"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("cloud_done", color="positive", size="24px")
                ui.label(f"Đã lưu vào Drive · folder {folder}").classes("text-base font-semibold")
            for title, url in links:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("open_in_new", size="16px").classes("muted")
                    ui.link(title, url, new_tab=True).classes("text-sm")
            ui.button("Đóng", on_click=dlg.close).props("flat no-caps").classes("self-end")
        dlg.open()

    async def to_drive(kind: str):
        try:
            async def work():
                xlsx = await produce(make_xlsx) if kind == "sheet" else None
                pptx = await produce(make_pptx) if kind in ("slides", "pdf") else None

                def upload():
                    svc = D.build_service(cfg)
                    with connect() as c:
                        folder, folder_name = D.target_folder(c, svc, cfg.site_url)
                    if kind == "sheet":
                        f = D.upload(svc, xlsx, name, D.XLSX, folder, D.SHEET)
                        return [("Mở Google Sheets", f["webViewLink"])], folder_name, None
                    f = D.upload(svc, pptx, name, D.PPTX, folder, D.SLIDES)
                    links = [("Mở Google Slides", f["webViewLink"])]
                    pdf = None
                    if kind == "pdf":
                        pdf = D.export_pdf(svc, f["id"])
                        p = D.upload(svc, pdf, f"{name}.pdf", D.PDF, folder)
                        links.append(("Mở file PDF trên Drive", p["webViewLink"]))
                    return links, folder_name, pdf
                return await run.io_bound(upload)

            links, folder_name, pdf = await busy(work())
            if pdf:
                ui.download.content(pdf, f"{name}.pdf")
            done(links, folder_name)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không lưu được lên Drive: {D.explain(e)}", type="negative", multi_line=True, timeout=12000,
                      close_button="Đóng")

    async def choose_folder():
        def load():
            svc = D.build_service(cfg)
            with connect() as c:
                root = D.root_folder(c, svc, cfg.site_url)
                current, _ = D.target_folder(c, svc, cfg.site_url)
            return svc, root, current, D.list_folders(svc, root)

        try:
            svc, root, current, folders = await busy(run.io_bound(load))
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không mở được Drive: {D.explain(e)}", type="negative", multi_line=True, timeout=12000,
                      close_button="Đóng")
            return
        options = {root: "📁 Folder gốc của tool", **{f["id"]: f"   └ {f['name']}" for f in folders}}
        with ui.dialog() as dlg, ui.card().style("min-width: 460px; border-radius: 14px"):
            ui.label("Chọn folder Drive để lưu").classes("text-lg font-semibold")
            ui.label("Tool chỉ thấy folder do chính nó tạo (quyền tối thiểu). Bạn có thể chia sẻ hoặc di chuyển "
                     "folder gốc trên Drive.").classes("text-xs muted")
            sel = ui.select(options, value=current if current in options else root).props("outlined dense").classes(
                "w-full")
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                new_name = ui.input(placeholder="Tên folder mới, ví dụ: Báo cáo tháng").props(
                    "outlined dense").classes("col")

                async def create():
                    if not (new_name.value or "").strip():
                        return
                    fid = await run.io_bound(lambda: D.create_folder(svc, new_name.value, root))
                    options[fid] = f"   └ {new_name.value.strip()}"
                    sel.set_options(options, value=fid)
                    new_name.value = ""

                ui.button("Tạo", icon="create_new_folder", on_click=create).props("flat no-caps")

            def save():
                with connect() as c:
                    D.set_target_folder(c, sel.value)
                ui.notify("Đã chọn folder lưu", type="positive")
                dlg.close()

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Lưu", on_click=save).props("unelevated no-caps")
        dlg.open()

    with ui.dropdown_button(label, icon="ios_share", auto_close=True).props(
            "unelevated no-caps") as btn:
        with ui.list().props("dense").style("min-width: 240px"):
            def item(icon, text, handler, caption=""):
                with ui.item(on_click=handler):
                    with ui.item_section().props("avatar"):
                        ui.icon(icon, size="20px").classes("muted")
                    with ui.item_section():
                        ui.item_label(text)
                        if caption:
                            ui.item_label(caption).props("caption")

            item("download", "Tải Excel về máy", download_excel)
            if not can_edit(user):
                if make_pptx:
                    item("slideshow", "Tải PowerPoint về máy", download_pptx, "bộ slide báo cáo")
                return
            item("table_view", "Google Sheets", lambda: to_drive("sheet"), "lưu vào folder Drive")
            if make_pptx:
                item("slideshow", "Google Slides", lambda: to_drive("slides"), "bộ slide báo cáo")
                item("picture_as_pdf", "PDF", lambda: to_drive("pdf"), "từ bộ slide, lưu Drive + tải về")
            ui.separator()
            item("folder_open", "Chọn folder Drive…", choose_folder)
