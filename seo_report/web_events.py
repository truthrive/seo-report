"""Mốc sự kiện chung của website (Google update, sửa web, đăng loạt bài, đẩy backlink…): xem / thêm / xóa trong một
cửa sổ nhỏ. Lưu chung bảng với mốc của trang Thứ hạng (rank_events, set_id trống = mọi bộ), nên mốc ghi ở đâu cũng hiện
ở biểu đồ Tổng quan, biểu đồ Thứ hạng và màn URL."""
from datetime import date

from . import rank as R


def _vn(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def site_events(con, site: str) -> list[dict]:
    """Chỉ mốc chung của website (không gồm mốc riêng của từng bộ từ khóa), cũ trước."""
    return [e for e in R.events(con, site, None) if e["set_id"] is None]


def marks(evs: list[dict], spans: list[tuple[date, date]], labels: list[str]) -> list[tuple[str, str]]:
    """Mốc thành (nhãn trục X, chữ) cho biểu đồ theo ngày / tuần: mốc rơi vào điểm nào thì gắn ở điểm đó."""
    out: dict[str, list[str]] = {}
    for e in evs:
        d = date.fromisoformat(e["day"])
        for (s, en), lab in zip(spans, labels):
            if s <= d <= en:
                out.setdefault(lab, []).append(f"{d:%d/%m} {e['text']}")
                break
    return [(lab, " · ".join(t)) for lab, t in out.items()]


def mark_line(items: list[tuple[str, str]]) -> dict:
    """markLine ECharts: vạch tím nét đứt, chữ ngắn ở đầu vạch (giống biểu đồ Thứ hạng)."""
    if not items:
        return {}
    return {"markLine": {"symbol": "none", "silent": False, "animation": False,
                         "lineStyle": {"color": "#7C3AED", "type": "dashed", "width": 1},
                         "label": {"position": "insideEndTop", "color": "#5B21B6", "fontSize": 10,
                                   "overflow": "truncate", "width": 140, "backgroundColor": "rgba(255,255,255,.94)",
                                   "padding": [2, 5], "borderRadius": 4},
                         "tooltip": {"show": True},
                         "data": [{"xAxis": x, "name": t, "label": {"formatter": t}} for x, t in items]}}


def events_dialog(ui, connect, site: str, user, can_edit: bool, on_change=None) -> None:
    with ui.dialog() as d, ui.card().style("min-width: 560px; max-width: 94vw; border-radius: 14px"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("Mốc sự kiện của website").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        ui.label("Hiện thành vạch tím trên biểu đồ Click theo ngày (Tổng quan) và biểu đồ Thứ hạng, để biết số tăng / "
                 "giảm sau việc gì: Google cập nhật thuật toán, sửa web, đăng loạt bài, đẩy backlink…").classes(
            "text-sm muted")
        box = ui.column().classes("w-full gap-0")

        def draw():
            box.clear()
            with connect() as c:
                evs = site_events(c, site)
            with box:
                if not evs:
                    ui.label("Chưa có mốc nào.").classes("text-sm muted")
                for e in reversed(evs):
                    with ui.row().classes("w-full items-center no-wrap gap-3 q-py-xs"):
                        ui.label(_vn(e["day"])).classes("text-sm num").style("width: 96px")
                        ui.label(e["text"]).classes("text-sm col")
                        ui.label(e["by"].split("@")[0]).classes("text-xs muted")
                        if can_edit:
                            ui.button(icon="delete_outline", on_click=lambda i=e["id"]: drop(i)).props(
                                'flat round dense size=sm color=negative aria-label="Xóa mốc"').tooltip("Xóa mốc")

        def changed():
            draw()
            if on_change:
                on_change()

        def drop(i: int):
            with connect() as c:
                R.delete_event(c, site, i, str(user))
            changed()
        draw()
        if can_edit:
            ui.separator()
            with ui.row().classes("w-full items-end gap-2"):
                day_in = ui.input("Ngày", value=f"{date.today():%d/%m/%Y}").props("outlined dense").classes("w-36")
                with day_in.add_slot("append"):
                    ui.icon("event").classes("cursor-pointer")
                    with ui.menu():
                        ui.date(mask="DD/MM/YYYY").bind_value(day_in)
                text_in = ui.input("Nội dung", placeholder="ví dụ: Google core update, đăng 10 bài blog").props(
                    "outlined dense maxlength=120").classes("col")

            def add_ev():
                try:
                    dd, mm, yy = (day_in.value or "").strip().split("/")
                    day = date(int(yy), int(mm), int(dd))
                except ValueError:
                    ui.notify("Ngày dạng dd/mm/yyyy", type="warning")
                    return
                try:
                    with connect() as c:
                        R.add_event(c, site, day, text_in.value or "", str(user), None)
                except ValueError as ex:
                    ui.notify(str(ex), type="warning")
                    return
                text_in.value = ""
                changed()
            with ui.row().classes("w-full justify-end"):
                ui.button("Thêm mốc", icon="add", on_click=add_ev).props("unelevated no-caps")
    d.open()
