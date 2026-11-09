"""Popup thao tác nhanh mở từ nút nổi (+) góc dưới phải: thêm từ khóa theo dõi, thêm đối thủ, tra từ khóa.
Mỗi popup làm xong tại chỗ, không phải rời trang đang xem."""
from urllib.parse import quote

from . import access as A
from . import aio as AO
from . import keywords as K
from . import points as PT
from . import rank as R
from . import ui_theme as T


def _frame(ui, title: str, icon: str, sub: str = ""):
    """Khung popup chung: tiêu đề có icon, dòng mô tả, nút đóng. Trả (dialog, thân)."""
    dlg = ui.dialog()
    with dlg, ui.card().classes("sr-qk-dlg q-pa-none"):
        with ui.row().classes("w-full items-start no-wrap gap-3 sr-qk-head"):
            with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['green'][0]}"):
                ui.icon(icon, size="20px").style(f"color:{T.TONES['green'][1]}")
            with ui.column().classes("gap-0 col"):
                ui.label(title).classes("text-base font-semibold")
                if sub:
                    ui.label(sub).classes("text-xs muted")
            ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')
        body = ui.column().classes("w-full gap-3 sr-qk-body")
        dlg.foot = ui.row().classes("w-full justify-end gap-2 sr-qk-foot")
    dlg.on("hide", dlg.delete)
    return dlg, body


def _actions(ui, dlg, label: str, on_ok):
    with dlg.foot:
        ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
        return ui.button(label, on_click=on_ok).props("unelevated no-caps color=primary")


def add_keywords(ui, P, user) -> None:
    """Thêm từ khóa vào một bộ theo dõi hạng (không gồm bộ Cam kết: bộ đó sửa trên sheet ở trang Thứ hạng)."""
    if not A.can_edit(user):
        return
    with P.connect() as c:
        sets_ = [s for s in R.sets(c, P.site) if s["kind"] != "kpi"]
    dlg, body = _frame(ui, "Thêm từ khóa theo dõi", "playlist_add",
                       "Mỗi dòng một từ khóa. Muốn gắn URL mục tiêu: từ khóa | URL")
    with body:
        if not sets_:
            ui.label("Website chưa có bộ từ khóa nào. Tạo bộ ở trang Thứ hạng trước.").classes("text-sm")
            with ui.row().classes("w-full justify-end"):
                ui.button("Mở Thứ hạng", on_click=lambda: ui.navigate.to("/rank")).props(
                    "unelevated no-caps color=primary")
            dlg.open()
            return
        pick = ui.select({s["id"]: f"{s['name']}" + (" (Nháp)" if s["draft"] else "") + f" · {s['count']} từ khóa"
                          for s in sets_}, value=sets_[0]["id"], label="Thêm vào bộ").props(
            "outlined dense").classes("w-full")
        paste = ui.textarea(placeholder="giày chạy bộ nam\ngiày chạy bộ nữ | https://…").props(
            "outlined autogrow input-style='min-height:120px'").classes("w-full")
        hint = ui.label().classes("text-xs muted")
        if PT.member(user):
            hint.text = f"Thêm vào bộ: {PT.cost('volume')} credit mỗi lần thêm. Check theo lịch của bộ không trừ credit."

        async def ok():
            from nicegui import run

            from . import kpi as KP
            from . import volume as V
            items = [(kw.lower(), url or None, t) for kw, url, t in KP.parse_keyword_text(paste.value or "")]
            if not items:
                ui.notify("Chưa có từ khóa nào", type="warning", position="bottom-right")
                return
            if PT.take(ui, user, P.cfg, "volume", detail=f"thêm {len(items)} từ khóa") is False:
                return
            btn.props("loading")
            try:
                with P.connect() as c:
                    end = K.latest_date(c, P.site)
                    r = R.add_keywords(c, P.site, P.cfg.rank, end, items, str(user), set_id=pick.value)
                if r["added"]:
                    def fetch():
                        with P.connect() as c:
                            return V.refresh(c, P.site, P.cfg, end, log=lambda m: None)
                    try:
                        await run.io_bound(fetch)
                    except Exception:  # noqa: BLE001 (từ khóa vẫn được thêm; lượt chạy hằng ngày lấy bù volume)
                        pass
            except ValueError as e:
                ui.notify(str(e), type="warning", position="bottom-right")
                return
            finally:
                btn.props(remove="loading")
            parts = [f"Đã thêm {len(r['added'])} từ khóa"]
            if r["exists"]:
                parts.append(f"đã có sẵn {len(r['exists'])}")
            if r["over_budget"]:
                parts.append(f"không thêm {len(r['over_budget'])} vì vượt ngân sách check rank")
            if r["bad_url"]:
                parts.append(f"bỏ qua {len(r['bad_url'])} dòng có URL không thuộc website")
            msg = " · ".join(parts)
            if r["over_budget"] or r["bad_url"]:
                hint.text = msg
                hint.style(f"color:{T.RED}")
                return
            dlg.close()
            ui.notify(msg, type="positive", position="bottom-right", classes="sr-toast")
    btn = _actions(ui, dlg, "Thêm từ khóa", ok)
    dlg.open()


def add_rival(ui, P, user) -> None:
    """Thêm một đối thủ (tên + tên miền) để so sánh ở thứ hạng và AI Overview."""
    if not A.can_edit(user):
        return
    dlg, body = _frame(ui, "Thêm đối thủ", "group_add", "Dùng để so sánh thứ hạng và lượt nhắc trong AI Overview")
    with body:
        domains = ui.textarea("Tên miền", placeholder="doithu.vn\nshop.doithu.vn").props(
            "outlined autogrow").classes("w-full")
        name = ui.input("Tên thương hiệu (không bắt buộc)").props("outlined dense").classes("w-full")
        ui.label("Mỗi dòng một tên miền. Bỏ trống tên thì lấy theo tên miền đầu tiên.").classes("text-xs muted")

    def ok():
        doms = (domains.value or "").strip()
        if not doms:
            ui.notify("Nhập ít nhất một tên miền", type="warning", position="bottom-right")
            return
        try:
            with P.connect() as c:
                AO.save_brand(c, P.site, (name.value or "").strip() or doms.split()[0], "", doms)
        except ValueError as e:
            ui.notify(str(e), type="warning", position="bottom-right")
            return
        dlg.close()
        ui.notify("Đã thêm đối thủ", type="positive", position="bottom-right", classes="sr-toast")
    _actions(ui, dlg, "Thêm đối thủ", ok)
    dlg.open()


def lookup_keyword(ui, P, user) -> None:
    """Tra nhanh một từ khóa: mở trang Tổng quan từ khóa với từ khóa đó."""
    dlg, body = _frame(ui, "Tra từ khóa", "manage_search", "Volume, độ khó, ý định tìm kiếm và top 10 Google")

    def ok():
        kw = (box.value or "").strip()
        if kw:
            ui.navigate.to("/tu-khoa?kw=" + quote(kw))
    with body:
        box = ui.input("Từ khóa", placeholder="ví dụ: giày chạy bộ nam").props("outlined dense autofocus").classes(
            "w-full")
        box.on("keydown.enter", ok)
        if PT.member(user):
            ui.label(f"Từ khóa mới: {PT.cost('overview')} credit. Từ khóa đã tra trong 7 ngày không trừ.").classes(
                "text-xs muted")
    _actions(ui, dlg, "Tra", ok)
    dlg.open()
