"""Popup "Đoạn trả lời cho AI Overview": AI viết nháp đoạn trả lời 40–60 từ, tiêu đề H2/H3, ý nên bổ sung, FAQ cho một
từ khóa (mở từ tab Việc nên làm hoặc popup nội dung AI Overview). Bản nháp lưu theo từ khóa; Viết lại = bản mới."""
from datetime import datetime
from html import escape

from . import access as A
from . import ai_http as AH
from . import ai_settings as AIS
from . import ai_writer as AW
from . import points as PT
from . import ui_theme as T

KIND = "aio_answer"


def _path(url: str) -> str:
    from urllib.parse import urlparse
    if not url:
        return ""
    p = urlparse(url)
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def _as_text(d: dict, keyword: str) -> str:
    out = [f"Từ khóa: {keyword}", "", "Đoạn trả lời (đặt ngay dưới tiêu đề):", d["answer"], ""]
    if d.get("headings"):
        out += ["Tiêu đề H2 / H3 gợi ý:"] + [f"- {h}" for h in d["headings"]] + [""]
    if d.get("missing"):
        out += ["Ý nên bổ sung:"] + [f"- {m}" for m in d["missing"]] + [""]
    if d.get("faq"):
        out += ["Hỏi đáp:"] + [f"H: {f['q']}\nĐ: {f['a']}" for f in d["faq"]]
    return "\n".join(out).strip()


def ai_cost_box(ui, user, action: str, before: list[tuple[str, str]] | None = None) -> bool:
    """Khối chi phí trước khi bấm viết (DESIGN.md mục 8): các bước miễn phí đi trước, rồi lượt AI. Member thấy credit
    và số còn lại sau lần này; Owner / Admin thấy là không trừ credit. Trả False khi Member không đủ credit."""
    lines = list(before or [])
    cost = PT.cost(action)
    bal = PT.my_balance(user)
    if bal is None:
        lines.append(("AI viết", "1 lần gọi AI"))
        T.cost_lines(ui, lines, note="Owner / Admin không trừ credit; tiền AI tính vào Quản trị › Ngân sách & chi phí.")
        return True
    lines.append(("AI viết", f"{cost} credit"))
    after = bal["left"] - cost
    enough = after >= 0
    tone = "red" if not enough else "amber" if bal["limit"] and after < bal["limit"] * 0.1 else "neutral"
    T.cost_lines(ui, lines, total=("Còn lại sau lần này", f"{max(after, 0):,} / {bal['limit']:,} credit".replace(
        ",", ".")), note="AI lỗi thì hoàn credit." if enough else
        f"Không đủ credit: còn {bal['left']} credit tháng này, cần {cost}. Nhờ Owner / Admin cấp thêm.", tone=tone)
    return enough


def answer_dialog(ui, connect, cfg, user, keyword_id: int, keyword: str, page_url: str, aio_text: str,
                  sources: list[dict], issue: str = "", on_saved=None) -> None:
    if not A.can_edit(user):
        return
    from . import aio as AO
    site = cfg.site_url
    ref = str(keyword_id)
    with connect() as c:
        bs = AO.brands(c, cfg)
        saved = AW.latest(c, site, KIND, ref)
    brand = bs[0]["name"] if bs else ""
    cost = PT.cost("ai_aio")
    try:
        prov = AW.provider(cfg, "aio_answer")
    except AW.NoProvider as e:
        prov, no_prov = None, str(e)
    else:
        no_prov = ""

    with ui.dialog() as dlg, ui.card().classes("sr-aw-dlg q-pa-none"):
        with ui.row().classes("w-full items-start no-wrap gap-3 sr-aw-head"):
            with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['purple'][0]}"):
                ui.icon("auto_fix_high", size="20px").style(f"color:{T.TONES['purple'][1]}")
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label("Đoạn trả lời cho AI Overview").classes("text-xs muted")
                ui.label(keyword).classes("text-base font-semibold ellipsis")
                ui.label(" · ".join(x for x in (
                    f"Trang: {_path(page_url)}" if page_url else "Chưa có trang xếp hạng", issue) if x)).classes(
                    "text-xs muted")
            ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')
        body = ui.column().classes("w-full gap-3 sr-aw-body")
        foot = ui.row().classes("w-full items-center gap-2 sr-aw-foot")
    dlg.on("hide", dlg.delete)

    state = {"draft": saved}

    def meta_text(d: dict) -> str:
        at = d.get("at")
        when = f"{datetime.fromisoformat(at).astimezone():%d/%m %H:%M}" if at else ""
        return f"AI viết lúc {when}" if when else ""

    def render() -> None:
        body.clear()
        foot.clear()
        d = state["draft"]
        with body:
            if not d:
                with ui.element("div").classes("sr-aw-intro"):
                    ui.label("AI sẽ đọc nội dung AI Overview hiện tại và các nguồn đang được trích, rồi viết nháp:"
                             ).classes("text-sm")
                    ui.html("<ul><li>Đoạn trả lời 40–60 từ đặt ngay dưới tiêu đề trang</li>"
                            "<li>3–5 tiêu đề H2 / H3 dạng câu hỏi</li><li>Các ý nên bổ sung so với nguồn đang được "
                            "trích</li><li>2–3 câu hỏi đáp (FAQ)</li></ul>")
                    ui.label("AI không bịa số: chỗ cần số liệu riêng sẽ để [điền …].").classes("text-xs muted")
                state["enough"] = ai_cost_box(ui, user, "ai_aio")
                if no_prov:
                    ui.label(no_prov).classes("text-sm").style(f"color:{T.RED}")
            else:
                words = len(d["answer"].split())
                with ui.element("div").classes("sr-aw-answer"):
                    with ui.row().classes("w-full items-center no-wrap gap-2"):
                        ui.label("Đoạn trả lời").classes("sr-aw-h col")
                        ui.label(f"{words} từ").classes("text-xs" + (" muted" if 35 <= words <= 70 else "")).style(
                            "" if 35 <= words <= 70 else f"color:{T.AMBER_TEXT}")
                    ui.label(d["answer"]).classes("sr-aw-text")
                if d.get("headings"):
                    ui.label("Tiêu đề H2 / H3 gợi ý").classes("sr-aw-h")
                    ui.html("<ul class='sr-aw-list'>" + "".join(f"<li>{escape(h)}</li>" for h in d["headings"])
                            + "</ul>")
                if d.get("missing"):
                    ui.label("Ý nên bổ sung so với nguồn đang được trích").classes("sr-aw-h")
                    ui.html("<ul class='sr-aw-list'>" + "".join(f"<li>{escape(m)}</li>" for m in d["missing"])
                            + "</ul>")
                if d.get("faq"):
                    ui.label("Hỏi đáp (FAQ)").classes("sr-aw-h")
                    for f in d["faq"]:
                        with ui.element("div").classes("sr-aw-faq"):
                            ui.label(f["q"]).classes("text-sm font-medium")
                            ui.label(f["a"]).classes("text-sm")
                ui.label("AI viết nháp: đọc lại và điền các chỗ [điền …] trước khi đăng."
                         ).classes("text-xs muted")
        with foot:
            if d:
                ui.label(meta_text(d)).classes("text-xs muted col ellipsis")
                ui.button("Sao chép", icon="content_copy",
                          on_click=lambda: (ui.clipboard.write(_as_text(state["draft"], keyword)),
                                            ui.notify("Đã sao chép", type="positive", position="bottom-right"))
                          ).props("flat no-caps")
            else:
                ui.space()
            label = ("Viết lại" if d else "Viết bằng AI") + (f" · {cost} credit" if PT.member(user) else "")
            btn = ui.button(label, icon="auto_fix_high", on_click=lambda: go(btn)).props(
                "unelevated no-caps color=primary")
            if not prov or not state.get("enough", True):
                btn.disable()

    async def go(btn) -> None:
        from nicegui import run
        entry = PT.take(ui, user, cfg, "ai_aio", detail=keyword)
        if entry is False:
            return
        btn.disable()
        body.clear()
        with body:
            steps = T.Steps(ui, ["AI viết đoạn trả lời, tiêu đề, ý còn thiếu, FAQ", "Lưu vào Thư viện AI"])
            ui.label("Có thể đóng hộp thoại: bản nháp vẫn được lưu, mở lại từ tab Việc nên làm hoặc Thư viện AI."
                     ).classes("text-xs muted")
        steps.run(0)
        try:
            draft, used = await run.io_bound(AW.write_aio, cfg, keyword, brand, page_url, aio_text, sources, issue,
                                             prov)
        except (AH.AIError, AW.NoProvider) as e:
            PT.give_back(entry)
            AIS.log_call(site, "aio_answer", "manual", str(user), prov, False, str(e))
            steps.done(0, "lỗi" + (", đã hoàn credit" if entry else ""), state="fail")
            btn.enable()
            ui.notify(f"AI chưa viết được: {e}", type="warning", position="bottom-right", multi_line=True)
            return
        steps.done(0)
        steps.run(1)
        AIS.log_call(site, "aio_answer", "manual", str(user), used, True, credits=PT.cost("ai_aio") if PT.member(user) else 0)
        with connect() as c:
            AW.save(c, site, KIND, ref, draft, used, str(user))
            state["draft"] = AW.latest(c, site, KIND, ref)
        steps.done(1)
        try:
            render()
            if on_saved:
                on_saved()
        except Exception:  # noqa: BLE001 — hộp thoại / trang đã đóng: bản nháp đã lưu
            pass

    render()
    dlg.open()


def has_draft(connect, cfg, ids) -> set[int]:
    """Từ khóa đã có bản nháp đoạn trả lời (để đánh dấu trên bảng)."""
    with connect() as c:
        AW.ensure(c)
        return {int(r[0]) for r in c.execute("SELECT DISTINCT ref FROM ai_drafts WHERE site = ? AND kind = ?",
                                             (cfg.site_url, KIND)) if str(r[0]).isdigit()} & set(ids)
