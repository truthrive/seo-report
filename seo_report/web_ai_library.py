"""Tab "AI đã tạo" (Research từ khóa): tổng hợp mọi bản AI đã viết cho website — chiến lược SEO, brief từ khóa, đoạn
trả lời AI Overview, nhận xét báo cáo, bản tin Tổng quan. Mỗi bản lấy lần viết mới nhất; bấm để xem lại và sao chép
(không gọi AI, không tốn credit). Viết lại thì làm ở trang gốc."""
import json
from datetime import datetime
from html import escape

from . import ai_writer as AW
from . import ui_theme as T

KINDS = {"kw_strategy": ("Chiến lược SEO", "view_module", "/research"),
         "kw_brief": ("Brief từ khóa", "article", "/tu-khoa"),
         "aio_answer": ("Đoạn trả lời AIO", "tips_and_updates", "/aio?tab=viec"),
         "report_note": ("Nhận xét báo cáo", "summarize", "/report"),
         "brief": ("Bản tin Tổng quan", "auto_awesome", "/")}


def _rows(con, cfg) -> list[dict]:
    """Bản mới nhất của mỗi (loại, mã)."""
    AW.ensure(con)
    out = []
    for kind, ref, content, at in con.execute(
            "SELECT kind, ref, content, at FROM ai_drafts d WHERE site = ? AND id = (SELECT MAX(id) FROM ai_drafts "
            "x WHERE x.site = d.site AND x.kind = d.kind AND x.ref = d.ref) ORDER BY at DESC", (cfg.site_url,)):
        if kind not in KINDS:
            continue
        try:
            data = json.loads(content)
        except ValueError:
            continue
        out.append({"kind": kind, "ref": ref, "data": data, "at": at})
    names = {}
    ids = [int(r["ref"]) for r in out if r["kind"] == "aio_answer" and str(r["ref"]).isdigit()]
    if ids:
        try:
            names = {i: k for i, k in con.execute(
                f"SELECT id, keyword FROM rank_keywords WHERE id IN ({','.join('?' * len(ids))})", ids)}
        except Exception:  # noqa: BLE001
            names = {}
    for r in out:
        r["title"], r["snippet"] = _describe(r, names)
    return out


def _describe(r: dict, names: dict) -> tuple[str, str]:
    d, k = r["data"], r["kind"]
    if k == "kw_strategy":
        title = d.get("title") or " · ".join(p["name"] for p in d.get("pillars", [])[:3])
        return title, d.get("summary", "")
    if k == "kw_brief":
        return (d.get("keyword"), d.get("title", "")) if d.get("keyword") else (d.get("title") or r["ref"],
                                                                               d.get("intent", ""))
    if k == "aio_answer":
        return names.get(int(r["ref"]) if str(r["ref"]).isdigit() else -1, f"Từ khóa #{r['ref']}"), d.get("answer", "")
    if k == "report_note":
        ref = str(r["ref"])
        if ref.startswith("month:"):
            title = f"Báo cáo tháng {ref[11:13]}/{ref[6:10]}"
        else:
            title = f"Báo cáo tuần {ref[8:10]}/{ref[5:7]}/{ref[:4]}" if len(ref) >= 10 else "Báo cáo"
        return title, (d.get("note") or "").lstrip("- ").split("\n")[0]
    if k == "brief":
        return "Bản tin Tổng quan", d.get("headline", "")
    return r["ref"], ""


def _text(r: dict) -> str:
    """Bản chữ để sao chép."""
    from .web_ai_research import brief_text, strategy_text
    from .web_ai_write import _as_text
    d, k = r["data"], r["kind"]
    if k == "kw_strategy":
        return strategy_text(d)
    if k == "kw_brief":
        return brief_text(r["title"], d)
    if k == "aio_answer":
        return _as_text(d, r["title"])
    if k == "report_note":
        return d.get("note", "") + (("\n\nKế hoạch tháng sau:\n" + d["plan"]) if d.get("plan") else "")
    if k == "brief":
        return "\n".join([d.get("headline", "")] + [f"- {i['title']}: {i.get('action', '')}" for i in d.get("items", [])])
    return ""


def _view(ui, r: dict) -> None:
    """Popup xem lại một bản (chỉ đọc)."""
    from .web_ai_research import _frame, render_brief, render_strategy
    name, _, href = KINDS[r["kind"]]
    at = datetime.fromisoformat(r["at"]).astimezone()
    dlg, body, foot = _frame(ui, f"{name}: {r['title']}", f"AI viết lúc {at:%d/%m %H:%M}",
                             width=920 if r["kind"] == "kw_strategy" else 760)
    d = r["data"]
    with body:
        if r["kind"] == "kw_strategy":
            render_strategy(ui, d)
        elif r["kind"] == "kw_brief":
            render_brief(ui, d)
        elif r["kind"] == "aio_answer":
            with ui.element("div").classes("sr-aw-answer w-full"):
                ui.label("Đoạn trả lời").classes("sr-aw-h")
                ui.label(d.get("answer", "")).classes("sr-aw-text")
            for title, items in (("Tiêu đề H2 / H3 gợi ý", d.get("headings")), ("Ý nên bổ sung", d.get("missing"))):
                if items:
                    ui.label(title).classes("sr-aw-h")
                    ui.html("<ul class='sr-aw-list'>" + "".join(f"<li>{escape(x)}</li>" for x in items) + "</ul>")
            for f in d.get("faq") or []:
                with ui.element("div").classes("sr-aw-faq w-full"):
                    ui.label(f["q"]).classes("text-sm font-medium")
                    ui.label(f["a"]).classes("text-sm")
        elif r["kind"] == "report_note":
            for title, v in (("Nhận xét", d.get("note")), ("Kế hoạch tháng sau", d.get("plan"))):
                if v:
                    ui.label(title).classes("sr-aw-h")
                    ui.label(v).classes("text-sm w-full").style("white-space: pre-line")
            ui.label("Đây là bản AI viết nháp; bản đã sửa và lưu nằm ở trang Báo cáo.").classes("text-xs muted")
        elif r["kind"] == "brief":
            if d.get("headline"):
                ui.label(d["headline"]).classes("sr-st-sum w-full")
            for i in d.get("items", []):
                with ui.element("div").classes("sr-st-win w-full"):
                    ui.element("span").classes(f"sr-br-dot {i['priority']} q-mt-xs")
                    with ui.column().classes("gap-0 col"):
                        ui.label(i["title"]).classes("text-sm font-medium")
                        if i.get("action"):
                            ui.label("→ " + i["action"]).classes("text-sm muted")
    with foot:
        ui.link("Mở trang gốc", href).classes("text-sm col").style("color:#5B21B6")
        ui.button("Sao chép", icon="content_copy", on_click=lambda: (
            ui.clipboard.write(_text(r)), ui.notify("Đã sao chép", type="positive"))).props("flat no-caps")
    dlg.open()


RESEARCH_KINDS = ("kw_strategy", "kw_brief")
AIO_KINDS = ("aio_answer",)


def delete(con, site: str, kind: str, ref: str) -> int:
    """Xóa hẳn mọi lần viết của một bản (loại + mã). Trả số dòng đã xóa."""
    AW.ensure(con)
    with con:
        return con.execute("DELETE FROM ai_drafts WHERE site = ? AND kind = ? AND ref = ?", (site, kind, ref)).rowcount


def build_ai_library(ui, cfg, connect, user, kinds: tuple = RESEARCH_KINDS, header: bool = True) -> None:
    """Danh sách bản AI của một công cụ (kinds): Research từ khóa = chiến lược + brief; AI Overview = đoạn trả lời.
    Người có quyền sửa xóa được (có hỏi lại)."""
    from . import access as A
    can_del = A.can_edit(user)
    if header:
        T.page_header(ui, "auto_awesome", "Thư viện AI", "Chiến lược SEO và brief AI đã viết cho website này.",
                      eyebrow="Research")
    state = {"kind": "all", "q": ""}

    def load() -> list[dict]:
        with connect() as c:
            return [r for r in _rows(c, cfg) if r["kind"] in kinds]

    def ask_delete(r: dict) -> None:
        with ui.dialog() as d, ui.card().style("max-width: 420px; border-radius: 14px"):
            ui.label("Xóa bản AI này?").classes("text-lg font-semibold")
            ui.label(f"{KINDS[r['kind']][0]}: {r['title']}").classes("text-sm")
            ui.label("Xóa hẳn, không khôi phục được. Muốn có lại thì cho AI viết lại ở trang gốc.").classes(
                "text-sm muted")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")

                def go():
                    with connect() as c:
                        delete(c, cfg.site_url, r["kind"], r["ref"])
                    d.close()
                    ui.notify("Đã xóa", type="positive", position="bottom-right")
                    body.refresh()
                ui.button("Xóa", icon="delete_outline", on_click=go).props("unelevated no-caps color=negative")
        d.on("hide", d.delete)
        d.open()

    @ui.refreshable
    def body() -> None:
        rows = load()
        if not rows:
            T.empty_state(ui, "auto_awesome", "Chưa có bản AI nào",
                          "Bản AI viết sẽ hiện ở đây để xem lại và sao chép.")
            return
        counts = {k: sum(1 for r in rows if r["kind"] == k) for k in kinds}
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            if len([k for k in kinds if counts[k]]) > 1:
                ui.toggle({"all": f"Tất cả · {len(rows)}",
                           **{k: f"{KINDS[k][0]} · {counts[k]}" for k in kinds if counts[k]}},
                          value=state["kind"], on_change=lambda e: (state.update(kind=e.value), grid.refresh())).props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                    "sr-seg")
            else:
                ui.label(f"{len(rows)} bản").classes("text-sm muted")
            ui.space()
            ui.input(placeholder="Tìm", value=state["q"],
                     on_change=lambda e: (state.update(q=(e.value or "").lower()), grid.refresh())).props(
                "outlined dense clearable debounce=250").classes("sr-aa-search")

        @ui.refreshable
        def grid() -> None:
            items = [r for r in rows if (state["kind"] == "all" or r["kind"] == state["kind"])
                     and (not state["q"] or state["q"] in (r["title"] + " " + r["snippet"]).lower())]
            if not items:
                ui.label("Không có bản nào khớp.").classes("text-sm muted")
                return
            with ui.element("div").classes("sr-lib-grid"):
                for r in items:
                    name, icon, _ = KINDS[r["kind"]]
                    at = datetime.fromisoformat(r["at"]).astimezone()
                    with ui.element("div").classes("sr-lib-card"):
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            ui.icon(icon, size="16px").classes("sr-br-ico")
                            ui.label(name).classes("sr-lib-kind col")
                            ui.label(f"{at:%d/%m %H:%M}").classes("text-xs muted num")
                            if can_del:
                                ui.button(icon="delete_outline", on_click=lambda _, r=r: ask_delete(r)).props(
                                    'flat round dense size=sm aria-label="Xóa bản này"').classes(
                                    "sr-lib-del").tooltip("Xóa")
                        main = ui.element("div").classes("sr-lib-main").props('role=button tabindex=0')
                        with main:
                            ui.label(r["title"]).classes("sr-lib-title")
                            if r["snippet"]:
                                ui.label(r["snippet"]).classes("sr-lib-snip")
                        main.on("click", lambda _, r=r: _view(ui, r))
                        main.on("keydown.enter", lambda _, r=r: _view(ui, r))
        grid()
    body()
