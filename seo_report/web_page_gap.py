"""Popup "Đoạn còn thiếu" (SEO Opportunities › Striking Distance): AI đọc trang đang ở vị trí 4–15 cho một từ khóa và
viết phần còn thiếu để chèn vào trang (H2 + đoạn 120–180 từ, chỗ đặt, FAQ, tiêu đề SEO gợi ý, anchor link nội bộ).
Bản nháp lưu theo trang + từ khóa; mở lại xem bản cũ, Viết lại = bản mới. Team tự đưa lên website."""
from datetime import date, datetime
from html import escape

from . import access as A
from . import ai_http as AH
from . import ai_page_gap as PG
from . import ai_settings as AIS
from . import ai_writer as AW
from . import opportunities as O
from . import points as PT
from . import ui_theme as T
from . import web_ai_write as WAW


def _path(url: str, site: str) -> str:
    return url.replace(site.rstrip("/"), "") or "/"


def render_draft(ui, d: dict) -> None:
    """Nội dung một bản nháp (dùng ở popup và ở Thư viện AI)."""
    if not d.get("page_read"):
        ui.label("Chưa đọc được nội dung trang" + (f" ({d['page_error']})" if d.get("page_error") else "")
                 + ": AI chỉ dựa vào từ khóa và đường dẫn, nên đọc kỹ trước khi dùng.").classes("text-sm").style(
            f"color:{T.AMBER_TEXT}")
    if d.get("diagnosis"):
        ui.label(d["diagnosis"]).classes("sr-st-sum w-full")
    if d.get("placement"):
        with ui.row().classes("items-center gap-1 no-wrap text-sm"):
            ui.icon("place", size="16px").classes("muted").props('aria-hidden="true"')
            ui.label(f"Đặt ở: {d['placement']}").classes("muted")
    n = PG.words(d.get("section", ""))
    lo, hi = PG.SECTION_WORDS
    ok = lo - 20 <= n <= hi + 30
    with ui.element("div").classes("sr-aw-answer w-full"):
        with ui.row().classes("w-full items-start no-wrap gap-2"):
            ui.label("H2").classes("sr-bl-type q-mt-xs").style("flex:none").tooltip("Tiêu đề cấp 2 (H2) mới")
            ui.label(d.get("heading", "")).classes("sr-aw-h col").style("font-size:14px; padding-top:2px")
            ui.label(f"{n} từ").classes("text-xs q-mt-xs" + (" muted" if ok else "")).style(
                "flex:none" + ("" if ok else f"; color:{T.AMBER_TEXT}")).tooltip(f"Nên khoảng {lo}–{hi} từ")
            ui.button(icon="content_copy", on_click=lambda: (
                ui.clipboard.write(f"{d.get('heading', '')}\n\n{d.get('section', '')}"),
                ui.notify("Đã sao chép tiêu đề H2 và đoạn bổ sung", type="positive", position="bottom-right"))
            ).props('flat round dense size=sm aria-label="Sao chép tiêu đề H2 và đoạn bổ sung"').style(
                "flex:none; margin-top:-4px").tooltip("Sao chép H2 + đoạn này")
        ui.label(d.get("section", "")).classes("sr-aw-text")
    if d.get("faq"):
        ui.label("Hỏi đáp (FAQ)").classes("sr-aw-h")
        with ui.element("div").classes("sr-aw-faq w-full"):
            ui.label(d["faq"]["q"]).classes("text-sm font-medium")
            ui.label(d["faq"]["a"]).classes("text-sm")
    if d.get("title"):
        n_title = len(d["title"])
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.label("Tiêu đề SEO gợi ý").classes("sr-aw-h col")
            ui.label(f"{n_title} ký tự").classes("text-xs" + (" muted" if n_title <= 60 else "")).style(
                "" if n_title <= 60 else f"color:{T.AMBER_TEXT}").tooltip("Google thường hiện trọn khoảng 60 ký tự")
        cur = d.get("page_title")
        ui.label(d["title"]).classes("text-sm")
        if cur:
            ui.label(f"Hiện tại: {cur}").classes("text-xs muted")
    if d.get("anchors"):
        ui.label("Anchor để đặt link nội bộ về trang này").classes("sr-aw-h")
        ui.html("<ul class='sr-aw-list'>" + "".join(f"<li>{escape(a)}</li>" for a in d["anchors"]) + "</ul>")
    ui.label("AI viết nháp: đọc lại, điền các chỗ [điền …] rồi mới đưa lên trang.").classes("text-xs muted")


def gap_dialog(ui, connect, cfg, user, row: dict, end: date, on_saved=None) -> None:
    """row: một dòng Striking Distance (query, url, url_id, position, impressions, clicks)."""
    if not A.can_edit(user):
        return
    site = cfg.site_url
    ref = PG.ref_of(row["url_id"], row["query"])
    with connect() as c:
        saved = AW.latest(c, site, PG.KIND, ref)
        queries = O.page_queries(c, row["url_id"], end)
    cost = PT.cost(PG.ACTION)
    try:
        prov = AW.provider(cfg, PG.TASK)
    except AW.NoProvider as e:
        prov, no_prov = None, str(e)
    else:
        no_prov = ""

    with ui.dialog() as dlg, ui.card().classes("sr-aw-dlg q-pa-none"):
        with ui.row().classes("w-full items-start no-wrap gap-3 sr-aw-head"):
            with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['purple'][0]}"):
                ui.icon("auto_fix_high", size="20px").style(f"color:{T.TONES['purple'][1]}")
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label("Đoạn còn thiếu cho trang").classes("text-xs muted")
                # từ khóa là thông tin chính: xuống dòng, không cắt "…" trên điện thoại
                ui.label(row["query"]).classes("text-base font-semibold").style("overflow-wrap:anywhere")
                with ui.row().classes("items-center gap-1 no-wrap text-xs muted w-full").style("min-width:0"):
                    ui.link(_path(row["url"], site), row["url"], new_tab=True).classes("sr-bl-link ellipsis").props(
                        f'title="{escape(row["url"])}" aria-label="Mở trang {escape(_path(row["url"], site))} '
                        f'(tab mới)"')
                    ui.label(f"· vị trí {str(row['position']).replace('.', ',')}").style("flex:none")
            ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')
        body = ui.column().classes("w-full gap-3 sr-aw-body")
        foot = ui.row().classes("w-full items-center gap-2 sr-aw-foot")
    dlg.on("hide", dlg.delete)
    state = {"draft": saved}

    def render() -> None:
        body.clear()
        foot.clear()
        d = state["draft"]
        with body:
            if not d:
                with ui.element("div").classes("sr-aw-intro"):
                    ui.label("AI sẽ đọc nội dung hiện tại của trang và các từ khóa khác trang đang lên, rồi viết đúng "
                             "phần còn thiếu để chèn vào trang (không viết bài mới):").classes("text-sm")
                    ui.html(f"<ul><li>Một tiêu đề H2 và đoạn bổ sung {PG.SECTION_WORDS[0]}–{PG.SECTION_WORDS[1]} "
                            "từ, kèm gợi ý đặt sau mục nào</li><li>Một câu hỏi đáp (FAQ)</li><li>Tiêu đề SEO gợi ý "
                            "khi tiêu đề hiện tại chưa nói tới từ khóa</li><li>Anchor để đặt link nội bộ về trang"
                            "</li></ul>")
                    ui.label("AI không bịa số: chỗ cần thông tin riêng sẽ để [điền …].").classes("text-xs muted")
                state["enough"] = WAW.ai_cost_box(ui, user, PG.ACTION, before=[
                    ("Đọc trang và từ khóa Search Console", "miễn phí")])
                if no_prov:
                    ui.label(no_prov).classes("text-sm").style(f"color:{T.RED}")
            else:
                render_draft(ui, d)
        with foot:
            if d:
                at = d.get("at")
                ui.label(f"AI viết lúc {datetime.fromisoformat(at).astimezone():%d/%m %H:%M}" if at else ""
                         ).classes("text-xs muted col ellipsis")
                ui.button("Sao chép", icon="content_copy", on_click=lambda: (
                    ui.clipboard.write(PG.as_text(state["draft"])),
                    ui.notify("Đã sao chép", type="positive", position="bottom-right"))).props("flat no-caps")
            else:
                ui.space()
            label = ("Viết lại" if d else "Viết bằng AI") + (f" · {cost} credit" if PT.member(user) else "")
            btn = ui.button(label, icon="auto_fix_high", on_click=lambda: go(btn)).props(
                "unelevated no-caps color=primary")
            if not prov or not state.get("enough", True):
                btn.disable()

    async def go(btn) -> None:
        from nicegui import run
        entry = PT.take(ui, user, cfg, PG.ACTION, detail=row["query"])
        if entry is False:
            return
        btn.disable()
        body.clear()
        with body:
            steps = T.Steps(ui, [f"Đọc trang {_path(row['url'], site)}",
                                 "AI viết phần còn thiếu", "Lưu vào Thư viện AI"])
            ui.label("Có thể đóng hộp thoại: bản nháp vẫn được lưu, mở lại bằng nút Xem bản nháp hoặc Thư viện AI."
                     ).classes("text-xs muted")
        steps.run(0)
        page = await run.io_bound(PG.read_page, row["url"])
        if page.get("ok"):
            n_words = f"{page.get('words', 0):,}".replace(",", ".")
            steps.done(0, f"{n_words} chữ, {len(page.get('headings') or [])} tiêu đề")
        else:  # vẫn viết được từ từ khóa + đường dẫn; bản nháp có cảnh báo
            steps.done(0, f"không đọc được: {page.get('error') or 'lỗi'}", state="warn")
        steps.run(1)
        try:
            draft, used = await run.io_bound(PG.write, cfg, row, queries, page, prov)
        except (AH.AIError, AW.NoProvider) as e:
            PT.give_back(entry)
            AIS.log_call(site, PG.TASK, "manual", str(user), prov, False, str(e))
            steps.done(1, "lỗi" + (", đã hoàn credit" if entry else ""), state="fail")
            btn.enable()
            ui.notify(f"AI chưa viết được: {e}", type="warning", position="bottom-right", multi_line=True)
            return
        steps.done(1)
        steps.run(2)
        AIS.log_call(site, PG.TASK, "manual", str(user), used, True,
                     credits=cost if PT.member(user) else 0)
        with connect() as c:
            AW.save(c, site, PG.KIND, ref, draft, used, str(user))
            state["draft"] = AW.latest(c, site, PG.KIND, ref)
        steps.done(2)
        try:
            render()
            if on_saved:
                on_saved()
        except Exception:  # noqa: BLE001 — hộp thoại / trang đã đóng: bản nháp đã lưu
            pass

    render()
    dlg.open()


def drafted_refs(connect, site: str) -> set[str]:
    """Mã (trang|từ khóa) đã có bản nháp, để đánh dấu trên bảng."""
    with connect() as c:
        AW.ensure(c)
        return {r[0] for r in c.execute("SELECT DISTINCT ref FROM ai_drafts WHERE site = ? AND kind = ?",
                                        (site, PG.KIND))}
