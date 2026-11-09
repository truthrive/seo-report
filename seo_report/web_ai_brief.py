"""Khối "Bản tin AI" ở đầu trang Tổng quan (chỉ người có quyền sửa): AI xếp ưu tiên tối đa 5 việc từ các tín hiệu tool
đã tìm thấy (ai_brief.py). Thay cho khối "Cần xử lý" cũ. Mở trang chỉ đọc bản đã lưu, không gọi AI; bấm Phân tích /
Cập nhật mới gọi. Chưa phân tích lần nào: hiện 5 tín hiệu nặng nhất theo quy tắc để không thiếu việc.

Gọn: mỗi việc một dòng (mức · tiêu đề · nhóm), dòng phụ là việc làm ngay; vì sao + số tool đo được nằm trong ô (i)."""
from datetime import datetime

from . import access as A
from . import ai_brief as B
from . import ai_http as AH
from . import ai_writer as AW
from . import points as PT
from . import ui_theme as T

PR_TEXT = {"high": "Cần xử lý", "medium": "Nên làm", "low": "Theo dõi"}


def brief_block(ui, cfg, connect, user, rep, todo: list) -> None:
    if not A.can_edit(user):
        return
    site = cfg.site_url
    with connect() as c:
        sigs = B.signals(c, cfg, user, rep, todo)
        saved = AW.latest(c, site, B.KIND, "overview")
    state = {"brief": saved}
    cost = PT.cost("ai_brief")
    box = ui.element("div").classes("w-full sr-br")

    def item_row(i: int, pr: str, title: str, action: str, area: str, href: str, tip: list[str]) -> None:
        with ui.link(target=href or "#").classes(f"sr-br-item {pr} no-underline"):
            ui.element("span").classes(f"sr-br-dot {pr}").props(f'aria-label="{PR_TEXT[pr]}"')
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label(title).classes("sr-br-title ellipsis").props["title"] = title
                if action:
                    ui.label("→ " + action).classes("sr-br-act ellipsis").props["title"] = action
            ui.label(area).classes("sr-br-area gt-xs")
            if tip:
                with ui.icon("info_outline", size="17px").classes("sr-br-info"):
                    with ui.tooltip().props("max-width=380px"):
                        for t in tip:
                            ui.label(t)
            ui.icon("chevron_right", size="18px").classes("sr-br-go")

    def render() -> None:
        box.clear()
        b = state["brief"]
        counts = {k: sum(1 for s in sigs if s["level"] == k) for k in PR_TEXT}
        with box:
            # ---- đầu khối: tiêu đề, đếm tín hiệu theo mức, nút ----
            with ui.row().classes("w-full items-center no-wrap gap-3 sr-br-head"):
                ui.icon("auto_awesome", size="20px").classes("sr-br-ico")
                with ui.column().classes("gap-0 col").style("min-width:0"):
                    ui.label("Bản tin AI").classes("sr-br-h")
                    if b:
                        at = datetime.fromisoformat(b["at"]).astimezone() if b.get("at") else None
                        stale = b.get("fingerprint") != B.fingerprint(sigs)
                        ui.label((f"{at:%d/%m %H:%M} · " if at else "") + f"từ {b.get('n_signals', '?')} tín hiệu"
                                 + (" · có tín hiệu mới" if stale else "")).classes("sr-br-sub" + (
                                     " stale" if stale else ""))
                    else:
                        ui.label("Chưa phân tích: đang hiện tín hiệu nặng nhất theo quy tắc của tool").classes(
                            "sr-br-sub")
                with ui.row().classes("items-center gap-1 no-wrap gt-sm"):
                    for k in PR_TEXT:
                        if counts[k]:
                            ui.html(f'<span class="sr-br-count {k}"><i></i>{counts[k]} {PR_TEXT[k].lower()}</span>')
                label = ("Cập nhật" if b else "AI phân tích") + (f" · {cost} credit" if PT.member(user) else "")
                btn = ui.button(label, icon="auto_fix_high", on_click=lambda: go(btn)).props(
                    "unelevated no-caps dense color=deep-purple-1 text-color=deep-purple-9").classes("sr-br-btn")
                if not sigs:
                    btn.disable()
            if not sigs:
                ui.label("Không có việc cần xử lý.").classes("text-sm q-px-md q-pb-md")
                return
            if b and b.get("headline"):
                ui.label(b["headline"]).classes("sr-br-headline")
            # ---- danh sách việc ----
            with ui.element("div").classes("sr-br-list"):
                if b:
                    for i, it in enumerate(b["items"], 1):
                        item_row(i, it["priority"], it["title"], it.get("action", ""), it["area"], it["href"],
                                 [x for x in (it.get("why"), f"Tool đo được: {it['fact']}") if x])
                else:
                    for i, s in enumerate(sigs[:5], 1):
                        item_row(i, s["level"], s["fact"].split(" · ")[0], "", s["area"], s["href"],
                                 [s["fact"]] if " · " in s["fact"] else [])
            # ---- tín hiệu gốc ----
            with ui.expansion(f"{len(sigs)} tín hiệu tool tìm thấy", icon="list").classes("sr-br-sig w-full").props(
                    "dense"):
                ui.label("AI chỉ chọn trong các tín hiệu này, không tự thêm việc.").classes("text-xs muted q-mb-xs")
                for s in sigs:
                    with ui.link(target=s["href"] or "#").classes("sr-br-srow no-underline"):
                        ui.element("span").classes(f"sr-br-dot {s['level']}")
                        ui.label(s["area"]).classes("text-xs muted")
                        ui.label(s["fact"]).classes("text-sm").props["title"] = s["fact"]

    async def go(btn) -> None:
        from nicegui import run
        try:
            prov = AW.provider(cfg)
        except AW.NoProvider as e:
            ui.notify(str(e), type="warning", multi_line=True)
            return
        entry = PT.take(ui, user, cfg, "ai_brief", detail=f"{len(sigs)} tín hiệu")
        if entry is False:
            return
        btn.props("loading")
        try:
            out, used = await run.io_bound(B.run, cfg, sigs, prov)
        except AH.AIError as e:
            PT.give_back(entry)
            btn.props(remove="loading")
            ui.notify(f"AI chưa phân tích được: {e}", type="warning", multi_line=True)
            return
        with connect() as c:
            AW.save(c, site, B.KIND, "overview", out, used, str(user))
            state["brief"] = AW.latest(c, site, B.KIND, "overview")
        render()

    render()

