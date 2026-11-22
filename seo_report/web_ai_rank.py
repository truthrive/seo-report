"""Giao diện AI ở trang Thứ hạng từ khóa (ai_rank.py): nhận định cả bộ, chẩn đoán một từ khóa, gợi ý URL mục tiêu,
việc cần làm theo từ khóa. Chỉ team (không phải khách); chỉ gọi AI khi bấm, Member trừ credit như các tác vụ AI khác.

ctx (SimpleNamespace từ web_rank): cfg, connect, user, site, sid, set_name, end, goals() -> [(nhãn, {N: cần})],
save_keyword(row, url, top, sync), sync_sheet(), is_kpi, refresh()."""
from datetime import datetime

from . import ai_rank as AR
from . import ai_settings as AIS
from . import ai_writer as AW
from . import points as PT

LEVEL = {"risk": ("Đáng lo", "#C2410C"), "watch": ("Theo dõi", "#B7791F"), "good": ("Tốt", "#1E7C31")}


def _cost(user, action: str) -> str:
    return f" · {PT.cost(action)} credit" if PT.member(user) else ""


def _when(iso: str | None) -> str:
    try:
        return f"{datetime.fromisoformat(iso).astimezone():%d/%m %H:%M}"
    except (TypeError, ValueError):
        return ""


async def _run(ui, ctx, action: str, detail: str, fn, data):
    from .web_ai_research import _run as run_ai
    return await run_ai(ui, ctx.user, ctx.cfg, action, detail, fn, data)


# ---------------------------------------------------------------- 1. nhận định cả bộ

def _set_facts(ctx) -> dict:
    from . import rank as R
    from . import volume as V
    with ctx.connect() as c:
        kws = R.keywords(c, ctx.site, ctx.end, ctx.sid)
        vols = V.latest(c)
        hist = R.set_history(c, ctx.site, ctx.sid)
    return AR.set_facts(ctx.set_name, kws, vols, hist, ctx.goals())


def _insight_body(ui, d: dict) -> None:
    """Nội dung một bản nhận định (dùng ở khối trên trang và trong thư viện)."""
    if d.get("headline"):
        ui.label(d["headline"]).classes("sr-rai-headline")
    with ui.element("div").classes("sr-rai-grid"):
        with ui.column().classes("gap-2"):
            ui.label("Nhận định").classes("sr-rai-h")
            for p in sorted(d.get("points") or [], key=lambda x: list(LEVEL).index(
                    x.get("level") if x.get("level") in LEVEL else "watch")):
                lv = p.get("level") if p.get("level") in LEVEL else "watch"
                with ui.row().classes("items-start no-wrap gap-2"):
                    ui.label(LEVEL[lv][0]).classes(f"sr-rai-lv {lv}")
                    ui.label(p.get("text") or "").classes("text-sm")
        with ui.column().classes("gap-2"):
            ui.label("Nên làm").classes("sr-rai-h")
            for i, a in enumerate(d.get("actions") or [], 1):
                with ui.row().classes("items-start no-wrap gap-2"):
                    ui.label(str(i)).classes("sr-rai-num")
                    ui.label(a).classes("text-sm")


def insight_button(ui, ctx, box) -> None:
    """Nút "AI nhận định" + nút thư viện ở thanh đầu bộ; bản nhận định mới nhất trong `box` (thu gọn được)."""
    if not AIS.enabled(ctx.site, "rank_insight"):
        return
    ref = f"set:{ctx.sid}"
    try:
        from nicegui import app as _app
        open0 = _app.storage.user.get("rank_ai_open", True)
    except Exception:  # noqa: BLE001
        _app, open0 = None, True
    with ctx.connect() as c:
        state = {"d": AW.latest(c, ctx.site, "rank_insight", ref), "open": open0,
                 "n": len(AW.history(c, ctx.site, "rank_insight", [ref]))}
    now_fp = AR.fingerprint(_set_facts(ctx))

    def toggle() -> None:
        state["open"] = not state["open"]
        if _app:
            try:
                _app.storage.user["rank_ai_open"] = state["open"]
            except Exception:  # noqa: BLE001
                pass
        paint()

    def paint() -> None:
        box.clear()
        d = state["d"]
        if not d:
            return
        stale = d.get("fingerprint") != now_fp
        with box, ui.element("div").classes("sr-rai"):
            with ui.row().classes("w-full items-center gap-2 no-wrap sr-rai-top"):
                ui.icon("auto_awesome", size="18px").classes("sr-br-ico")
                ui.label("AI nhận định").classes("sr-rai-title")
                ui.label(_when(d.get("at"))).classes("sr-br-sub ellipsis")  # model AI chỉ hiện ở Quản trị › AI
                if stale:
                    ui.label("Đã có số mới, bấm AI nhận định để cập nhật").classes("sr-rai-stale")
                ui.space()
                ui.button(f"Thư viện · {state['n']}", icon="history", on_click=lambda: library_dialog(ui, ctx)).props(
                    "flat dense no-caps size=sm color=grey-8")
                ui.button(icon="expand_less" if state["open"] else "expand_more", on_click=toggle).props(
                    "flat round dense size=sm color=grey-7").tooltip("Thu gọn" if state["open"] else "Mở")
            if not state["open"]:
                if d.get("headline"):
                    ui.label(d["headline"]).classes("sr-rai-headline ellipsis")
                return
            _insight_body(ui, d)
            ui.label("AI đọc số tool đã tính ở lần check gần nhất; câu có số không có trong dữ liệu đã bị bỏ. Chỉ để "
                     "tham khảo.").classes("sr-kai-note")

    async def go(btn) -> None:
        btn.props("loading")
        try:
            facts = _set_facts(ctx)
            res = await _run(ui, ctx, "ai_rank_insight", f"nhận định bộ {ctx.set_name}", AR.write_insight, facts)
        finally:
            btn.props(remove="loading")
        if not res:
            return
        with ctx.connect() as c:
            AW.save(c, ctx.site, "rank_insight", ref, res[0], res[1], str(ctx.user))
            state["d"] = AW.latest(c, ctx.site, "rank_insight", ref)
            state["n"] = len(AW.history(c, ctx.site, "rank_insight", [ref]))
        state["open"] = True
        paint()

    b = ui.button("AI nhận định", icon="auto_awesome").props(
        "unelevated no-caps dense color=deep-purple-1 text-color=deep-purple-9").classes("sr-br-btn sr-kg-aibtn")
    b.on_click(lambda _, b=b: go(b))
    b.tooltip("AI tóm tắt biến động của bộ và việc nên làm" + _cost(ctx.user, "ai_rank_insight"))
    if not state["d"]:  # chưa có bản nào: thư viện vẫn mở được (chẩn đoán / việc cần làm cũ)
        ui.button(icon="history", on_click=lambda: library_dialog(ui, ctx)).props(
            "flat round dense color=grey-8").tooltip("Thư viện AI của bộ")
    paint()


def library_dialog(ui, ctx) -> None:
    """Thư viện AI của bộ: các bản nhận định, chẩn đoán từ khóa, việc cần làm, gợi ý URL đã viết (mới trước)."""
    from . import rank as R
    with ctx.connect() as c:
        names = {k["id"]: k["keyword"] for k in R.keywords(c, ctx.site, ctx.end, ctx.sid)}
        ref = f"set:{ctx.sid}"
        lists = {"insight": AW.history(c, ctx.site, "rank_insight", [ref]),
                 "diag": AW.history(c, ctx.site, "rank_diag", [f"kw:{i}" for i in names]),
                 "actions": AW.history(c, ctx.site, "rank_actions", [ref]),
                 "target": AW.history(c, ctx.site, "rank_target", [ref])}
    root = ctx.site.rstrip("/")

    def meta(x: dict) -> str:
        return _when(x.get("at")) + (f" · {x['by']}" if x.get("by") else "")  # không hiện model AI

    with ui.dialog() as d, ui.card().style("width: 860px; max-width: 96vw; border-radius: 14px"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.icon("history", size="20px").classes("sr-br-ico")
            ui.label(f"Thư viện AI · {ctx.set_name}").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props("flat round dense")
        with ui.tabs().props("align=left no-caps dense").classes("w-full sr-tabs") as tabs:
            t1 = ui.tab(f"Nhận định · {len(lists['insight'])}")
            t2 = ui.tab(f"Chẩn đoán từ khóa · {len(lists['diag'])}")
            t3 = ui.tab(f"Việc cần làm · {len(lists['actions'])}")
            t4 = ui.tab(f"Gợi ý URL · {len(lists['target'])}")
        with ui.tab_panels(tabs, value=t1).classes("w-full sr-rai-lib").props("animated=false"):
            with ui.tab_panel(t1).classes("q-px-none"):
                if not lists["insight"]:
                    ui.label("Chưa có bản nhận định nào.").classes("text-sm muted")
                for i, x in enumerate(lists["insight"]):
                    with ui.expansion(value=i == 0).classes("w-full sr-rai-libitem").props("dense") as ex:
                        with ex.add_slot("header"):
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                ui.label(x.get("headline") or "(không có tiêu đề)").classes("text-sm ellipsis")
                                ui.label(meta(x)).classes("text-xs muted")
                        _insight_body(ui, x)
            with ui.tab_panel(t2).classes("q-px-none"):
                if not lists["diag"]:
                    ui.label("Chưa chẩn đoán từ khóa nào (bấm vào một từ khóa → AI chẩn đoán).").classes(
                        "text-sm muted")
                for x in lists["diag"]:
                    kw_name = names.get(int(x["ref"].split(":")[1]), x["ref"])
                    with ui.expansion().classes("w-full sr-rai-libitem").props("dense") as ex:
                        with ex.add_slot("header"):
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                ui.label(kw_name).classes("text-sm font-medium ellipsis")
                                ui.label((x.get("summary") or "") + " · " + meta(x)).classes("text-xs muted ellipsis")
                        for cz in x.get("causes") or []:
                            ui.label("• " + cz["cause"] + (f" ({cz['evidence']})" if cz.get("evidence") else "")
                                     ).classes("text-sm")
                        for t in x.get("fixes") or []:
                            ui.label("→ " + t).classes("text-sm")
            with ui.tab_panel(t3).classes("q-px-none"):
                if not lists["actions"]:
                    ui.label("Chưa lập việc cần làm (tick từ khóa → AI việc cần làm).").classes("text-sm muted")
                for x in lists["actions"]:
                    items = x.get("items") or []
                    with ui.expansion().classes("w-full sr-rai-libitem").props("dense") as ex:
                        with ex.add_slot("header"):
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                ui.label(", ".join(it["kw"] for it in items[:4])
                                         + (f" + {len(items) - 4} từ khóa" if len(items) > 4 else "")).classes(
                                    "text-sm ellipsis")
                                ui.label(meta(x)).classes("text-xs muted")
                        for it in items:
                            ui.label(it["kw"]).classes("text-sm font-medium q-mt-xs")
                            for a in it["actions"]:
                                ui.label(f"[{AR.ACTION_TYPES.get(a['type'], a['type'])}] {a['text']}").classes(
                                    "text-sm")
                        ui.button("Sao chép", icon="content_copy", on_click=lambda it_=items: (
                            ui.clipboard.write(AR.actions_text(it_)), ui.notify("Đã sao chép", type="positive"))
                        ).props("flat dense no-caps size=sm color=primary")
            with ui.tab_panel(t4).classes("q-px-none"):
                if not lists["target"]:
                    ui.label("Chưa có lần gợi ý URL mục tiêu nào.").classes("text-sm muted")
                for x in lists["target"]:
                    items = x.get("items") or []
                    with ui.expansion().classes("w-full sr-rai-libitem").props("dense") as ex:
                        with ex.add_slot("header"):
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                ui.label(f"{sum(1 for it in items if it.get('url'))} / {len(items)} từ khóa có gợi ý"
                                         ).classes("text-sm")
                                ui.label(meta(x)).classes("text-xs muted")
                        for it in items:
                            ui.label(f"{it['kw']} → {(it.get('url') or '').replace(root, '') or ('/' if it.get('url') else '–')}"
                                     ).classes("text-sm")
    d.open()


# ---------------------------------------------------------------- 2. chẩn đoán một từ khóa

def diag_section(ui, ctx, row: dict, serps: list[dict]) -> None:
    """Trong hộp chi tiết từ khóa: nút "AI chẩn đoán" + bản đã lưu của từ khóa này."""
    if not AIS.enabled(ctx.site, "rank_diag"):
        return
    from .projects import domain
    ref = f"kw:{row['id']}"
    with ctx.connect() as c:
        state = {"d": AW.latest(c, ctx.site, "rank_diag", ref)}
    vol = row.get("volume") if (row.get("volume") or 0) > 0 else None
    facts = AR.kw_facts(row, serps, domain(ctx.site), vol)
    wrap = ui.element("div").classes("w-full sr-rai-diag")

    def paint() -> None:
        wrap.clear()
        with wrap:
            d = state["d"]
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("auto_awesome", size="17px").classes("sr-br-ico")
                ui.label("AI chẩn đoán").classes("text-sm font-semibold")
                if d:
                    stale = d.get("fingerprint") != AR.fingerprint(facts)
                    ui.label(_when(d.get("at")) + (" · đã có lần check mới" if stale else "")).classes(
                        "sr-br-sub" + (" stale" if stale else ""))
                ui.space()
                b = ui.button("Chẩn đoán lại" if d else "AI chẩn đoán", icon="psychology").props(
                    "unelevated no-caps dense color=deep-purple-1 text-color=deep-purple-9").classes("sr-br-btn")
                b.on_click(lambda _, b=b: go(b))
                b.tooltip("AI đọc trang kết quả Google lần trước / lần này: vì sao đổi hạng, sửa gì"
                          + _cost(ctx.user, "ai_rank_diag"))
                if not facts.get("top10_nay"):
                    b.disable()
                    b.tooltip("Chưa lưu trang kết quả Google của từ khóa này")
            if not d:
                return
            if d.get("summary"):
                ui.label(d["summary"]).classes("text-sm q-mt-xs")
            for x in d.get("causes") or []:
                with ui.row().classes("items-start no-wrap gap-2 q-mt-xs"):
                    ui.icon("search", size="16px").classes("muted")
                    with ui.column().classes("gap-0"):
                        ui.label(x["cause"]).classes("text-sm font-medium")
                        if x.get("evidence"):
                            ui.label(x["evidence"]).classes("text-xs muted")
            if d.get("fixes"):
                ui.label("Cách sửa").classes("sr-rai-h q-mt-sm")
                for t in d["fixes"]:
                    with ui.row().classes("items-start no-wrap gap-1"):
                        ui.icon("arrow_forward", size="15px").classes("sr-rai-arrow")
                        ui.label(t).classes("text-sm")

    async def go(btn) -> None:
        btn.props("loading")
        try:
            res = await _run(ui, ctx, "ai_rank_diag", f"chẩn đoán “{row['keyword']}”", AR.write_diag, facts)
        finally:
            btn.props(remove="loading")
        if not res:
            return
        with ctx.connect() as c:
            AW.save(c, ctx.site, "rank_diag", ref, res[0], res[1], str(ctx.user))
            state["d"] = AW.latest(c, ctx.site, "rank_diag", ref)
        paint()
    paint()


# ---------------------------------------------------------------- 3. gợi ý URL mục tiêu

def target_dialog(ui, ctx, rows: list[dict]) -> None:
    """rows: dòng bảng chưa có URL mục tiêu. Gọi AI, cho duyệt từng dòng rồi áp dụng các dòng đã tick."""
    from . import backlink_build as BB
    if not rows:
        ui.notify("Mọi từ khóa đã có URL mục tiêu", position="bottom-right")
        return
    with ctx.connect() as c:
        seo = BB.seo_urls(c, ctx.site)
    data = AR.target_facts(rows, seo, ctx.site)
    by_kw = {r["keyword"]: r for r in rows}
    with ui.dialog() as d, ui.card().style("width: 760px; max-width: 96vw; border-radius: 14px"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("AI gợi ý URL mục tiêu").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props("flat round dense")
        n = min(len(rows), AR.MAX_TARGET_KW)
        ui.label(f"{n} từ khóa chưa có URL mục tiêu" + (f" (lấy {n} / {len(rows)} đầu tiên)" if len(rows) > n else "")
                 + f" · chọn trong {len(data[1])} URL của website (URL SEO và trang đang xếp hạng)").classes(
            "text-sm muted")
        body = ui.column().classes("w-full gap-1")
        foot = ui.row().classes("w-full items-center justify-end gap-2")
        picks: dict[str, bool] = {}

        def show(items: list[dict]) -> None:
            body.clear()
            with body:
                root = ctx.site.rstrip("/")
                with ui.element("div").classes("sr-rai-tlist"):
                    for it in items:
                        has = bool(it["url"])
                        picks[it["kw"]] = has
                        with ui.element("div").classes("sr-rai-trow" + ("" if has else " none")):
                            cb = ui.checkbox(value=has, on_change=lambda e, k=it["kw"]: picks.update({k: e.value}))
                            cb.props("dense")
                            if not has:
                                cb.disable()
                            ui.label(it["kw"]).classes("text-sm ellipsis")
                            with ui.column().classes("gap-0").style("min-width:0"):
                                ui.label((it["url"] or "").replace(root, "") or ("/" if has else "Chưa có trang phù hợp")
                                         ).classes("text-sm ellipsis" + ("" if has else " muted"))
                                if it.get("reason"):
                                    ui.label(it["reason"]).classes("text-xs muted ellipsis")
            foot.clear()
            with foot:
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Áp dụng các dòng đã tick", icon="check", on_click=lambda: apply(items)).props(
                    "unelevated no-caps")

        async def apply(items: list[dict]) -> None:
            chosen = [it for it in items if picks.get(it["kw"]) and it["url"]]
            if not chosen:
                ui.notify("Chưa tick dòng nào", position="bottom-right")
                return
            done = 0
            for it in chosen:
                r = by_kw.get(it["kw"])
                if not r:
                    continue
                try:
                    await ctx.save_keyword(r, it["url"], r.get("top_n"), sync=False)
                    done += 1
                except Exception as e:  # noqa: BLE001
                    ui.notify(f"{it['kw']}: {e}", type="warning", position="bottom-right")
            if ctx.is_kpi:
                from nicegui import run
                await run.io_bound(ctx.sync_sheet)
            d.close()
            ctx.refresh()
            ui.notify(f"Đã gán URL mục tiêu cho {done} từ khóa", type="positive", position="bottom-right")

        async def go(btn) -> None:
            btn.props("loading")
            try:
                res = await _run(ui, ctx, "ai_rank_target", f"gợi ý URL cho {n} từ khóa", AR.write_targets, data)
            finally:
                btn.props(remove="loading")
            if res:
                with ctx.connect() as c:
                    AW.save(c, ctx.site, "rank_target", f"set:{ctx.sid}", res[0], res[1], str(ctx.user))
                show(res[0]["items"])
        with foot:
            ui.button("Hủy", on_click=d.close).props("flat no-caps")
            b = ui.button("AI gợi ý" + _cost(ctx.user, "ai_rank_target"), icon="auto_awesome").props(
                "unelevated no-caps color=deep-purple-1 text-color=deep-purple-9")
            b.on_click(lambda _, b=b: go(b))
    d.open()


# ---------------------------------------------------------------- 4. việc cần làm theo từ khóa

def actions_dialog(ui, ctx, rows: list[dict]) -> None:
    if not rows:
        ui.notify("Tick ít nhất một từ khóa", position="bottom-right")
        return
    rows = rows[:AR.MAX_ACTION_KW]
    f = AR.actions_facts(rows)
    with ui.dialog() as d, ui.card().style("width: 760px; max-width: 96vw; border-radius: 14px"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("AI việc cần làm").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props("flat round dense")
        ui.label(f"{len(rows)} từ khóa đã chọn" + (f" (tối đa {AR.MAX_ACTION_KW} một lần)"
                                                   if len(rows) == AR.MAX_ACTION_KW else "")).classes("text-sm muted")
        body = ui.column().classes("w-full gap-2")
        foot = ui.row().classes("w-full items-center justify-end gap-2")

        def show(items: list[dict]) -> None:
            body.clear()
            with body:
                for it in items:
                    with ui.element("div").classes("sr-rai-act"):
                        ui.label(it["kw"]).classes("text-sm font-semibold")
                        for a in it["actions"]:
                            with ui.row().classes("items-start no-wrap gap-2"):
                                ui.label(AR.ACTION_TYPES.get(a["type"], a["type"])).classes("sr-rai-tag")
                                ui.label(a["text"]).classes("text-sm")
            foot.clear()
            with foot:
                ui.button("Sao chép", icon="content_copy", on_click=lambda: (
                    ui.clipboard.write(AR.actions_text(items)),
                    ui.notify("Đã sao chép: dán vào Công việc / OKR / Sheets", type="positive"))).props(
                    "flat no-caps color=primary")
                ui.button("Đóng", on_click=d.close).props("unelevated no-caps")

        async def go(btn) -> None:
            btn.props("loading")
            try:
                res = await _run(ui, ctx, "ai_rank_actions", f"việc cần làm cho {len(rows)} từ khóa", AR.write_actions,
                                 f)
            finally:
                btn.props(remove="loading")
            if res:
                with ctx.connect() as c:
                    AW.save(c, ctx.site, "rank_actions", f"set:{ctx.sid}", res[0], res[1], str(ctx.user))
                show(res[0]["items"])
        with foot:
            ui.button("Hủy", on_click=d.close).props("flat no-caps")
            b = ui.button("AI lập việc" + _cost(ctx.user, "ai_rank_actions"), icon="auto_awesome").props(
                "unelevated no-caps color=deep-purple-1 text-color=deep-purple-9")
            b.on_click(lambda _, b=b: go(b))
    d.open()

