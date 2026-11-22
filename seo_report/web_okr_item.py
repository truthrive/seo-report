"""Popup chi tiết một hạng mục OKR, mở giữa màn hình từ trang Công việc & OKR (bấm vào hạng mục).

Hai cột:
- Thông tin: các ô giống một dòng trên sheet (tên, nhóm, chi tiết, số lượng, đơn vị, tháng, bắt đầu, kết thúc, PIC).
  Admin (lead dự án) sửa trực tiếp, rời ô là lưu; người khác chỉ xem.
- Theo dõi: trạng thái (Chưa bắt đầu / Đang làm / Đang chờ / Tạm hoãn / Hoàn thành), % tiến độ, gia hạn, link bằng
  chứng, nhật ký cập nhật (Admin / Member).
Guest: chỉ xem thông tin, trạng thái và link bằng chứng (nhật ký là ghi chú nội bộ, không hiện).
Tool tự ghi lại tab OKRs trên sheet dự án sau mỗi thay đổi.
"""
from datetime import date, datetime
from urllib.parse import urlsplit

from . import okr as O
from . import ui_theme as T


def _vn(iso: str | None, year: bool = False) -> str:
    if not iso:
        return "–"
    return f"{iso[8:10]}/{iso[5:7]}" + (f"/{iso[:4]}" if year else "")


def _when(iso: str) -> str:
    try:
        return f"{datetime.fromisoformat(iso).astimezone():%H:%M %d/%m}"
    except ValueError:
        return iso


def _who(by: str) -> str:
    return (by or "").split("@")[0] or "tool"


def _link_label(u: str) -> str:
    p = urlsplit(u)
    host = p.netloc.removeprefix("www.")
    if "docs.google.com" in host:
        return {"document": "Google Doc", "spreadsheets": "Google Sheet", "presentation": "Google Slides",
                "forms": "Google Form"}.get(p.path.strip("/").split("/")[0], "Google Docs")
    if "drive.google.com" in host:
        return "Google Drive"
    path = p.path.rstrip("/")
    return host + (path if len(path) <= 40 else path[:38] + "…")


# Ô thông tin (giống cột trên sheet): (trường, nhãn, kiểu, chiếm cả hàng)
FIELDS = (("title", "Hạng mục", "text", True), ("grp", "Nhóm", "text", False), ("pic", "PIC (người phụ trách)", "text",
                                                                                  False),
          ("details", "Chi tiết công việc", "area", True), ("qty", "Số lượng", "text", False),
          ("unit", "Đơn vị", "text", False), ("month_text", "Tháng dự kiến", "text", False),
          ("start", "Bắt đầu", "date", False), ("end", "Kết thúc", "date", False))


def open_item(ui, connect, user, uid: str, on_change, ed: bool) -> None:
    """Mở popup cho hạng mục `uid`. ed: Admin / Member (cập nhật); Admin còn sửa được các ô thông tin."""
    from .access import is_admin
    from .web_okr_edit import STATUS, change_status, extend_menu
    lead = ed and is_admin(user)
    changed = {"any": False}

    def load() -> dict | None:
        with connect() as c:
            every = O.items(c, date.today())
            it = next((i for i in every if i["uid"] == uid), None)
            if it:
                obj = next((i for i in every if i["uid"] == it["objective"]), None)
                it["_obj"] = f"{obj['code']} · {obj['title']}" if obj else ""
                it["_updates"] = O.updates(c, uid) if ed else []
                it["_ext"] = O.extensions(c, uid)
        return it

    def save(**kw) -> bool:
        try:
            with connect() as c:
                O.update_item(c, uid, by=str(user), **kw)
        except ValueError as e:
            ui.notify(str(e), type="warning", position="bottom-right", classes="sr-toast")
            return False
        changed["any"] = True
        return True

    def act(fn, *a, **kw) -> bool:
        try:
            with connect() as c:
                fn(c, *a, **kw)
        except ValueError as e:
            ui.notify(str(e), type="warning", position="bottom-right", classes="sr-toast")
            return False
        changed["any"] = True
        content.refresh()
        return True

    def refreshed():
        changed["any"] = True
        content.refresh()

    with ui.dialog() as dlg, ui.card().classes("sr-oi").style(
            f"width: {1040 if ed else 720}px; max-width: 96vw; max-height: 92vh; border-radius: 16px"):

        @ui.refreshable
        def content() -> None:
            it = load()
            if not it:
                ui.label("Hạng mục không còn (đã xóa?).").classes("text-sm muted")
                ui.button("Đóng", on_click=dlg.close).props("flat no-caps")
                return
            today = date.today()
            late = O.is_late(it, today)
            label, tone, icon = STATUS.get(it["status"], STATUS[O.TODO])
            # ---- đầu popup: mã, mục tiêu, tên, trạng thái, thời gian
            with ui.element("div").classes("sr-oi-head"):
                with ui.row().classes("w-full items-start no-wrap gap-2"):
                    with ui.column().classes("gap-0 col").style("min-width:0"):
                        ui.label(f"{it['code']} · {it['_obj']}").classes("text-xs muted ellipsis")
                        title_l = ui.label(it["title"]).classes("sr-oi-title")
                    ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')
                with ui.row().classes("items-center gap-2 q-mt-xs"):
                    T.pill(ui, label, tone, icon)
                    if late:
                        T.pill(ui, f"Trễ {(today - date.fromisoformat(it['end'])).days} ngày", "red", "event_busy")
                    if it.get("wait"):
                        T.pill(ui, O.wait_text(it["wait"]), "amber", "hourglass_empty")
                    meta = " · ".join(x for x in (
                        f"{_vn(it['start'])} → {_vn(it['end'], True)}" if it["start"] or it["end"] else "Chưa có ngày",
                        it["pic"] or "chưa có PIC", f"gia hạn {len(it['_ext'])} lần" if it["_ext"] else "") if x)
                    ui.label(meta).classes("text-sm muted")
            with ui.element("div").classes("sr-oi-body" + (" one" if not ed else "")):
                # ---- cột trái: thông tin như một dòng sheet
                with ui.element("section").classes("sr-oi-col"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("table_rows", size="18px").classes("sr-oi-hi").props('aria-hidden="true"')
                        ui.label("Thông tin hạng mục").classes("sr-oi-h")
                        if lead:
                            ui.label("sửa ô nào lưu ô đó").classes("text-xs muted")
                    dates = {"start": it["start"], "end": it["end"]}
                    with ui.element("div").classes("sr-oi-grid"):
                        for f, name, kind, full in FIELDS:
                            val = it.get(f) or ""
                            with ui.element("div").classes("sr-oi-f" + (" full" if full else "")):
                                if not lead:
                                    ui.label(name).classes("sr-oi-fl")
                                    shown = _vn(val, True) if kind == "date" and val else (val or "–")
                                    ui.label(shown).classes("sr-oi-fv").style(
                                        "white-space:pre-line" if kind == "area" else "")
                                    continue
                                if kind == "area":
                                    w = ui.textarea(name, value=val).props("outlined dense autogrow stack-label")
                                elif kind == "date":
                                    w = ui.input(name, value=val).props("outlined dense type=date stack-label")
                                else:
                                    w = ui.input(name, value=val).props("outlined dense stack-label")
                                w.classes("w-full")

                                def on_blur(_, f=f, w=w, old={"v": val}):
                                    new = (w.value or "").strip() if f not in ("details",) else (w.value or "")
                                    if new == old["v"]:
                                        return
                                    if f in ("start", "end"):  # gửi cả hai ngày để kiểm bắt đầu không sau kết thúc
                                        dates[f] = new or None
                                        kw = dict(dates)
                                    else:
                                        kw = {f: new}
                                    if f == "title" and not new:
                                        ui.notify("Tên không được để trống", type="warning", position="bottom-right")
                                        w.value = old["v"]
                                        return
                                    if save(**kw):
                                        old["v"] = new
                                        if f == "title":
                                            title_l.text = new
                                        ui.notify("Đã lưu", type="positive", position="bottom-right",
                                                  classes="sr-toast", timeout=900)
                                    else:
                                        w.value = old["v"]
                                w.on("blur", on_blur)
                                if kind == "date":
                                    w.on("change", on_blur)

                # ---- cột phải: theo dõi
                with ui.element("section").classes("sr-oi-col"):
                    if ed:
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("track_changes", size="18px").classes("sr-oi-hi").props('aria-hidden="true"')
                            ui.label("Trạng thái & tiến độ").classes("sr-oi-h")
                        with ui.element("div").classes("sr-oi-status"):
                            for s, (lb, tn, ic) in STATUS.items():
                                on = it["status"] == s
                                bg, fg = T.TONES[tn]
                                b = ui.button(lb, icon=ic).props("no-caps dense flat").classes(
                                    "sr-oi-st" + (" on" if on else "")).style(
                                    f"--st-bg:{bg}; --st-fg:{fg}")
                                b.props(f'aria-pressed="{str(on).lower()}"')
                                if not on or s == O.WAIT:  # đang chờ: bấm lại để sửa chờ ai / ghi chú
                                    b.on_click(lambda _, s=s: change_status(ui, connect, user, [uid], s, refreshed))
                        with ui.row().classes("w-full items-center gap-3 q-mt-sm no-wrap"):
                            ui.label("Tiến độ").classes("text-sm").style("width:62px")
                            pr = ui.slider(min=0, max=100, step=5, value=round(O.progress_of(it))).props(
                                "label color=green-8").classes("col")
                            pr.on("change", lambda e: save(progress=pr.value) and None)
                            ui.label().bind_text_from(pr, "value", lambda v: f"{v:.0f}%").classes(
                                "num text-sm font-semibold").style("width:44px;text-align:right")
                        if it["end"] and it["status"] != O.DONE:
                            with ui.row().classes("items-center gap-2 q-mt-xs"):
                                extend_menu(ui, connect, user, lambda: [uid], refreshed)
                                ui.label("dời hạn, có ghi lý do").classes("text-xs muted")

                    # link bằng chứng
                    urls = O.links(it)
                    with ui.row().classes("items-center gap-2 q-mt-md"):
                        ui.icon("link", size="18px").classes("sr-oi-hi").props('aria-hidden="true"')
                        ui.label(f"Link bằng chứng · {len(urls)}" if urls else "Link bằng chứng").classes("sr-oi-h")
                    if not urls and not ed:
                        ui.label("Chưa có link.").classes("text-sm muted")
                    with ui.column().classes("w-full gap-1"):
                        for u in urls:
                            with ui.row().classes("w-full items-center no-wrap gap-2 sr-oi-link"):
                                ui.icon("description" if "docs.google" in u else "public", size="18px").classes(
                                    "muted").props('aria-hidden="true"')
                                a = ui.element("a").classes("col sr-oi-a")
                                # gán từng thuộc tính dạng giá trị, không ghép vào chuỗi props (link có dấu nháy sẽ
                                # không thoát được khỏi chuỗi để chèn thuộc tính khác)
                                a._props.update({"href": u, "target": "_blank", "rel": "noopener", "title": u})
                                with a:
                                    ui.label(_link_label(u)).classes("text-sm ellipsis")
                                if ed:
                                    rm = ui.button(icon="close", on_click=lambda _, u=u: act(
                                        O.set_links, uid, [x for x in urls if x != u])).props(
                                        "flat round dense size=sm color=grey-7")
                                    rm._props["aria-label"] = f"Bỏ link {_link_label(u)}"
                    if ed:
                        with ui.row().classes("w-full items-center no-wrap gap-2 q-mt-xs"):
                            nl = ui.input(placeholder="Dán link (Google Doc, Sheet, bài đã đăng…)").props(
                                "outlined dense").classes("col")

                            def add_link():
                                if (nl.value or "").strip() and act(O.set_links, uid, urls + [nl.value]):
                                    nl.value = ""
                            nl.on("keydown.enter", add_link)
                            ui.button("Thêm", icon="add", on_click=add_link).props(
                                "outline no-caps dense color=grey-9")

                    # nhật ký cập nhật (nội bộ)
                    if ed:
                        with ui.row().classes("items-center gap-2 q-mt-md"):
                            ui.icon("forum", size="18px").classes("sr-oi-hi").props('aria-hidden="true"')
                            ui.label("Nhật ký cập nhật").classes("sr-oi-h")
                        note = ui.textarea(placeholder="Đã làm gì, vướng gì, bước tiếp theo… (ví dụ: đã gửi bản "
                                                       "nháp cho khách 19/11)").props(
                            "outlined dense autogrow").classes("w-full")

                        def add_note():
                            if act(O.add_update, uid, note.value or "", by=str(user)):
                                ui.notify("Đã ghi cập nhật", type="positive", position="bottom-right",
                                          classes="sr-toast")
                        with ui.row().classes("w-full justify-end"):
                            ui.button("Ghi cập nhật", icon="send", on_click=add_note).props(
                                "unelevated no-caps dense color=primary")
                        log = [{"at": u["at"], "by": u["by"], "text": u["text"], "kind": "note"}
                               for u in it["_updates"]]
                        log += [{"at": x["at"], "by": x["by"], "kind": "ext",
                                 "text": f"Gia hạn {_vn(x['old_end'])} → {_vn(x['new_end'])}"
                                         + (f" · {x['reason']}" if x["reason"] else "")} for x in it["_ext"]]
                        log.sort(key=lambda x: x["at"] or "", reverse=True)
                        if not log:
                            ui.label("Chưa có cập nhật nào.").classes("text-sm muted")
                        with ui.element("div").classes("sr-oi-log"):
                            for x in log[:50]:
                                with ui.element("div").classes("sr-oi-entry" + (" ext" if x["kind"] == "ext" else "")):
                                    with ui.row().classes("items-center gap-1 no-wrap"):
                                        ui.icon("update" if x["kind"] == "ext" else "chat_bubble_outline",
                                                size="14px").classes("muted").props('aria-hidden="true"')
                                        ui.label(f"{_who(x['by'])} · {_when(x['at'])}").classes("text-xs muted")
                                    ui.label(x["text"]).classes("text-sm").style("white-space:pre-line")
        content()

    def closed():
        dlg.delete()
        if changed["any"]:
            on_change()
    dlg.on("hide", closed)
    dlg.open()
