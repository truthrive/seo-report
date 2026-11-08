"""Thông báo tổng: chuông trên thanh trên cùng, bấm mở cửa sổ nhỏ liệt kê việc cần để ý của dự án (OKR, yêu cầu hỗ
trợ, thứ hạng, dữ liệu & hệ thống). Không có trang riêng."""
from . import notices as N
from . import ui_theme as T

SHOW = 30  # số dòng tối đa trong cửa sổ (nặng trước)


def bell(ui, cfg, connect, user, key) -> None:
    """Chuông + số chưa xem; bấm mở cửa sổ thông báo (nội dung chỉ dựng khi mở, trang vẫn nhẹ)."""
    state = {"kind": "all"}

    def items() -> list[dict]:
        try:
            with connect() as c:
                return N.cached(c, cfg, user, key)
        except Exception:  # noqa: BLE001 — thông báo lỗi không làm hỏng trang
            return []

    def mark(keys: list[str]) -> None:
        with connect() as c:
            N.mark_seen(c, user, keys)
        N.forget(key)

    def open_item(n: dict) -> None:
        mark([n["key"]])
        menu.close()
        if n["href"]:
            ui.navigate.to(n["href"])
        else:
            badge.refresh()

    def mark_all() -> None:
        mark([n["key"] for n in items() if not n["seen"]])
        panel.refresh()
        badge.refresh()

    with ui.button(on_click=lambda: None).props('flat round dense color=grey-8').classes("sr-bell") as btn:
        @ui.refreshable
        def badge() -> None:
            n = N.unseen(items())
            label = f"Thông báo · {n} chưa xem" if n else "Thông báo"
            btn.props(f'icon={"notifications" if n else "notifications_none"} aria-label="{label}"')
            if n:
                ui.badge(str(n) if n < 100 else "99+").props("floating rounded").classes("sr-bell-badge")
        badge()
        with ui.menu().props('anchor="bottom right" self="top right" :offset="[0, 8]"').classes("sr-nt-pop") as menu:
            @ui.refreshable
            def panel() -> None:
                if not state.get("open"):
                    return
                all_ = items()
                new = N.unseen(all_)
                with ui.row().classes("sr-nt-head items-center no-wrap w-full"):
                    ui.label("Thông báo").classes("text-base font-semibold")
                    if new:
                        T.pill(ui, f"{new} chưa xem", "blue")
                    ui.space()
                    if new:
                        ui.button("Đã xem hết", icon="done_all", on_click=mark_all).props(
                            "flat no-caps dense color=grey-9")
                counts = {k: sum(1 for n in all_ if n["kind"] == k) for k in N.KINDS}
                kinds = [k for k in N.KINDS if counts[k]]
                if len(kinds) > 1:
                    with ui.row().classes("sr-nt-chips items-center gap-1 w-full"):
                        for k, lb in [("all", f"Tất cả {len(all_)}")] + [(k, f"{N.KINDS[k][0]} {counts[k]}")
                                                                          for k in kinds]:
                            ui.button(lb, on_click=lambda _, k=k: (state.update(kind=k), panel.refresh())).props(
                                "unelevated no-caps dense rounded size=sm "
                                + ("color=dark" if state["kind"] == k else "color=grey-3 text-color=grey-9"))
                shown = [n for n in all_ if state["kind"] in ("all", n["kind"])]
                with ui.element("div").classes("sr-nt-list"):
                    if not shown:
                        with ui.column().classes("items-center w-full q-pa-lg gap-1"):
                            ui.icon("check_circle", size="28px").style(f"color:{T.GREEN}")
                            ui.label("Không có gì cần để ý").classes("text-sm font-medium")
                            ui.label("Việc trễ hạn, yêu cầu mới hay số liệu bất thường sẽ hiện ở đây.").classes(
                                "text-xs muted text-center")
                    for n in shown[:SHOW]:
                        tone = N.LEVELS[n["level"]][1]
                        row = ui.element("div").classes("sr-nt-row" + ("" if n["seen"] else " new")).props(
                            'role="button" tabindex="0"')
                        row.on("click", lambda _, n=n: open_item(n))
                        row.on("keydown.enter", lambda _, n=n: open_item(n))
                        with row:
                            name, icon = N.KINDS[n["kind"]]
                            ui.icon(icon, size="18px").classes("sr-nt-icon").style(
                                f"color:{T.TONES[tone][1]};background:{T.TONES[tone][0]}").props('aria-hidden="true"')
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                ui.label(n["title"]).classes("text-sm sr-nt-title")
                                ui.label(" · ".join(x for x in (N.LEVELS[n["level"]][0], name, n["detail"]) if x)
                                         ).classes("text-xs muted sr-nt-meta")
                            if not n["seen"]:
                                ui.element("span").classes("sr-nt-unread").props('aria-label="Chưa xem"')
                    if len(shown) > SHOW:
                        ui.label(f"và {len(shown) - SHOW} thông báo khác (nhẹ hơn)").classes(
                            "text-xs muted q-pa-sm")
            panel()
        menu.on("show", lambda: (state.update(open=True), panel.refresh()))
        menu.on("hide", lambda: state.update(open=False))
        ui.tooltip("Thông báo")
