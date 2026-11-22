"""Popup AI cho Research từ khóa: "AI lập chiến lược" (Ý tưởng từ khóa, từ các từ khóa đã tick) và "AI viết brief"
(Tổng quan từ khóa, một từ khóa). Tông tím nhạt cho nội dung AI; lưu bản đã viết; chỉ gọi khi bấm."""
from datetime import datetime
from html import escape

from . import access as A
from . import ai_http as AH
from . import ai_research as AR
from . import ai_writer as AW
from . import points as PT
from . import ui_theme as T



def _n(v) -> str:
    return f"{v:,}".replace(",", ".")


def _path(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url or "")
    return (p.path or "/") if url else ""


def _brand(connect, cfg) -> str:
    from . import aio as AO
    try:
        with connect() as c:
            bs = AO.brands(c, cfg)
        return bs[0]["name"] if bs else ""
    except Exception:  # noqa: BLE001
        return ""


def _frame(ui, title: str, sub: str, width: int = 860):
    dlg = ui.dialog()
    with dlg, ui.card().classes("sr-ar-dlg q-pa-none").style(f"width:{width}px"):
        with ui.row().classes("w-full items-start no-wrap gap-3 sr-ar-head"):
            ui.icon("auto_awesome", size="20px").classes("sr-br-ico q-mt-xs")
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label(title).classes("sr-br-h")
                ui.label(sub).classes("sr-br-sub ellipsis")
            ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')
        body = ui.column().classes("w-full gap-3 sr-ar-body")
        foot = ui.row().classes("w-full items-center gap-2 sr-ar-foot")
    dlg.on("hide", dlg.delete)
    return dlg, body, foot


def _meta(d: dict) -> str:
    at = d.get("at")
    when = f"{datetime.fromisoformat(at).astimezone():%d/%m %H:%M}" if at else ""
    return f"AI viết lúc {when}" if when else ""


async def _run(ui, user, cfg, action: str, detail: str, fn, *args):
    """Trừ credit, gọi AI trong luồng phụ, hoàn credit khi lỗi. Trả (kết quả, nhà cung cấp) hoặc None."""
    from nicegui import run

    from . import ai_settings as AIS
    task = AIS.ACTION_TASK.get(action, action)
    try:
        prov = AW.provider(cfg, task)
    except AW.NoProvider as e:
        ui.notify(str(e), type="warning", multi_line=True)
        return None
    entry = PT.take(ui, user, cfg, action, detail=detail)
    if entry is False:
        return None
    try:
        res = await run.io_bound(fn, cfg, *args, prov)
    except AH.AIError as e:
        PT.give_back(entry)
        AIS.log_call(cfg.site_url, task, "manual", str(user), prov, False, str(e))
        ui.notify(f"AI chưa viết được: {e}", type="warning", multi_line=True, position="bottom-right")
        return None
    AIS.log_call(cfg.site_url, task, "manual", str(user), res[1], True,
                 credits=PT.cost(action) if PT.member(user) else 0)
    return res


# ---------------------------------------------------------------- chiến lược cho nhóm từ khóa

def strategy_title(rows: list[dict]) -> str:
    """Tên ngắn để nhận ra bản chiến lược trong thư viện AI: từ khóa nhiều lượt tìm nhất + số từ khóa."""
    top = max(rows, key=lambda r: r.get("volume") or 0)["keyword"] if rows else ""
    return f"{top} + {len(rows) - 1} từ khóa" if len(rows) > 1 else top


def strategy_text(p: dict) -> str:
    from . import ai_strategy as S
    st = p["status"]
    out = ["CHIẾN LƯỢC SEO", p.get("summary", ""), "",
           f"Hiện trạng: {st['n']} từ khóa · {_n(st['volume'])} lượt tìm/tháng · top 10: {st['top10']} · trang 2: "
           f"{st['page2']} · xa hơn: {st['far']} · chưa có hạng: {st['none']}", "", "TRỤ CỘT CHỦ ĐỀ"]
    for i, c in enumerate(p["pillars"], 1):
        out.append(f"{i}. {c['name']} · {S.ROLES[c['role']]} · {_n(c['volume'])} lượt tìm/tháng"
                   + (f" · tốt nhất hạng {c['best']:.0f}" if c["best"] else " · chưa có hạng"))
        out.append("   Trang: " + (f"tối ưu {c['existing_url']}" if c["existing_url"] else "cần trang mới")
                   + (f" ({c['page_type']})" if c["page_type"] else ""))
        if c["why"]:
            out.append(f"   Vì sao: {c['why']}")
        out.append("   Từ khóa: " + ", ".join(c["keywords"]))
    if p["quick_wins"]:
        out += ["", "THẮNG NHANH (đang hạng 4–20)"]
        for w in p["quick_wins"]:
            out.append(f"- {w['action']}: " + ", ".join(f"{k['keyword']} (hạng {k['pos']})" for k in w["keywords"]))
    if p["phases"]:
        out += ["", "LỘ TRÌNH"]
        for ph in p["phases"]:
            out.append(f"{ph['name']}: {ph['goal']}")
            out += [f"   - {a}" for a in ph["actions"]]
    if p["kpis"]:
        out += ["", "KPI THEO DÕI"] + [f"- {k}" for k in p["kpis"]]
    if p["risks"]:
        out += ["", "RỦI RO / ĐIỀU KIỆN"] + [f"- {r}" for r in p["risks"]]
    return "\n".join(out).strip()


def stat_strip(ui, st: dict) -> None:
    tot = max(st["n"], 1)
    bar = "".join(f'<i class="{k}" style="width:{st[k] / tot * 100:.1f}%"></i>'
                  for k in ("top10", "page2", "far", "none") if st[k])
    ui.html(f"""<div class="sr-st-strip">
      <div><b class="num">{_n(st['volume'])}</b><span>lượt tìm / tháng</span></div>
      <div><b class="num">{st['top10']}</b><span><i class="d top10"></i>đã top 10</span></div>
      <div><b class="num">{st['page2']}</b><span><i class="d page2"></i>trang 2</span></div>
      <div><b class="num">{st['far'] + st['none']}</b><span><i class="d none"></i>xa hơn / chưa có hạng</span></div>
    </div><div class="sr-st-bar" role="img" aria-label="Top 10 {st['top10']}, trang 2 {st['page2']}, xa hơn
      {st['far']}, chưa có hạng {st['none']}">{bar}</div>""").classes("w-full")


def render_strategy(ui, p: dict) -> None:
    """Nội dung một bản chiến lược (dùng ở popup và thư viện AI): 3 tab Tổng quan · Trụ cột · Lộ trình & KPI."""
    from . import ai_strategy as S
    with ui.tabs().props("dense no-caps align=left inline-label active-color=deep-purple-9 "
                         "indicator-color=deep-purple-6").classes("w-full sr-st-tabs") as tabs:
        t1 = ui.tab("Tổng quan", icon="insights")
        t2 = ui.tab(f"Trụ cột · {len(p['pillars'])}", icon="view_module")
        t3 = ui.tab("Lộ trình & KPI", icon="timeline")
    with ui.tab_panels(tabs, value=t1).props("animated=false").classes("w-full sr-st-panels"):
        # ---- Tổng quan: nhận định · hiện trạng · thứ tự trụ cột · thắng nhanh ----
        with ui.tab_panel(t1).classes("q-pa-none column gap-3"):
            if p.get("summary"):
                ui.label(p["summary"]).classes("sr-st-sum")
            stat_strip(ui, p["status"])
            top = max((c["volume"] for c in p["pillars"]), default=1) or 1
            ui.label("Thứ tự đầu tư").classes("sr-st-h")
            with ui.element("div").classes("sr-st-rank"):
                for i, c in enumerate(p["pillars"], 1):
                    with ui.element("div").classes("sr-st-rrow"):
                        ui.label(str(i)).classes("sr-br-n num")
                        ui.label(c["name"]).classes("sr-st-rname ellipsis").props["title"] = c["name"]
                        ui.label(S.ROLES[c["role"]]).classes(f"sr-st-role {c['role']}")
                        ui.html(f"<div class='sr-st-vbar'><i style='width:{c['volume'] / top * 100:.0f}%'></i></div>")
                        ui.label(_n(c["volume"])).classes("num sr-st-vnum")
            if p["quick_wins"]:
                ui.label("Thắng nhanh · từ khóa đang hạng 4–20").classes("sr-st-h")
                with ui.element("div").classes("sr-st-wins"):
                    for w in p["quick_wins"]:
                        with ui.element("div").classes("sr-st-win"):
                            ui.icon("bolt", size="18px").classes("sr-st-bolt")
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                ui.label(w["action"]).classes("text-sm font-medium")
                                if w["why"]:
                                    ui.label(w["why"]).classes("text-xs muted")
                                ui.html("<div class='sr-ar-kws q-mt-xs'>" + "".join(
                                    f"<span>{escape(k['keyword'])} · <b>#{k['pos']}</b></span>"
                                    for k in w["keywords"]) + "</div>")
        # ---- Trụ cột: mỗi trụ cột một khối rộng, chữ không bị cắt ----
        with ui.tab_panel(t2).classes("q-pa-none"):
            with ui.element("div").classes("sr-st-plist"):
                for c in p["pillars"]:
                    with ui.element("div").classes("sr-st-prow"):
                        with ui.row().classes("w-full items-center gap-2"):
                            ui.label(c["name"]).classes("sr-st-pname")
                            ui.label(S.ROLES[c["role"]]).classes(f"sr-st-role {c['role']}")
                            ui.space()
                            ui.html(f"<span class='sr-st-kpi'><b class='num'>{_n(c['volume'])}</b> lượt tìm</span>"
                                    f"<span class='sr-st-kpi'>tốt nhất <b class='num'>"
                                    f"{'#' + format(c['best'], '.0f') if c['best'] else '–'}</b></span>"
                                    f"<span class='sr-st-kpi'><b class='num'>{c['ranked']}/{len(c['keywords'])}</b>"
                                    " có hạng</span>")
                        if c["why"]:
                            ui.label(c["why"]).classes("text-sm").style("color:#3A3A33")
                        with ui.row().classes("items-center gap-2 no-wrap").style("min-width:0"):
                            if c["existing_url"]:
                                ui.icon("link", size="16px").classes("sr-br-ico")
                                lk = ui.link("Tối ưu " + _path(c["existing_url"]), c["existing_url"], new_tab=True
                                             ).classes("sr-ar-page")
                                lk.props["title"] = c["existing_url"]
                            else:
                                ui.icon("add_circle_outline", size="16px").style("color:#1E7C31")
                                ui.label("Cần trang mới").classes("text-sm").style("color:#1E7C31")
                            if c["page_type"]:
                                ui.label("· " + c["page_type"]).classes("text-sm muted ellipsis")
                        ui.html(f"<details class='sr-st-kw'><summary>{len(c['keywords'])} từ khóa</summary>"
                                "<div class='sr-ar-kws'>" + "".join(f"<span>{escape(k)}</span>"
                                                                   for k in c["keywords"]) + "</div></details>")
            if p.get("unassigned"):
                ui.label("Chưa xếp vào trụ cột: " + ", ".join(p["unassigned"])).classes("text-xs muted q-mt-sm")
        # ---- Lộ trình & KPI ----
        with ui.tab_panel(t3).classes("q-pa-none column gap-3"):
            if p["phases"]:
                with ui.element("div").classes("sr-st-timeline"):
                    for i, ph in enumerate(p["phases"], 1):
                        with ui.element("div").classes("sr-st-step"):
                            ui.label(str(i)).classes("sr-st-dot num")
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                ui.label(ph["name"]).classes("text-sm font-semibold")
                                if ph["goal"]:
                                    ui.label(ph["goal"]).classes("text-sm").style("color:#5B21B6")
                                ui.html("<ul class='sr-aw-list'>" + "".join(f"<li>{escape(a)}</li>"
                                                                           for a in ph["actions"]) + "</ul>")
            with ui.element("div").classes("sr-st-two"):
                for title, items, icon in (("KPI theo dõi", p["kpis"], "flag"),
                                           ("Rủi ro / điều kiện", p["risks"], "report")):
                    if items:
                        with ui.element("div").classes("sr-st-box"):
                            with ui.row().classes("items-center gap-1 no-wrap"):
                                ui.icon(icon, size="16px").classes("sr-br-ico")
                                ui.label(title).classes("text-sm font-semibold")
                            ui.html("<ul class='sr-aw-list'>" + "".join(f"<li>{escape(x)}</li>" for x in items)
                                    + "</ul>")
            ui.label("Mục tiêu trong KPI là gợi ý, team cân nhắc trước khi chốt.").classes("text-xs muted")


def plan_dialog(ui, connect, cfg, user, rows: list[dict], picked: bool = True) -> None:
    """AI lập chiến lược SEO cho các từ khóa (đã tick, hoặc danh sách đang xem)."""
    from . import ai_strategy as S
    if not A.can_edit(user) or not rows:
        return
    rows = rows[:S.MAX_KW]
    key = S.ref(rows)
    with connect() as c:
        saved = AW.latest(c, cfg.site_url, S.KIND, key)
    state = {"p": saved}
    cost = PT.cost("ai_plan")
    dlg, body, foot = _frame(ui, "AI lập chiến lược SEO",
                             f"{len(rows)} " + ("từ khóa đã chọn" if picked else "từ khóa nhiều lượt tìm nhất đang xem")
                             + f" · {_n(sum(r.get('volume') or 0 for r in rows))} lượt tìm / tháng", width=920)

    def render() -> None:
        body.clear()
        foot.clear()
        p = state["p"]
        with body:
            if not p:
                stat_strip(ui, S.status(rows))
                with ui.element("div").classes("sr-st-intro"):
                    for icon, t in (("view_module", "Trụ cột chủ đề nên đầu tư và vai trò của từng trụ cột"),
                                    ("bolt", "Việc thắng nhanh cho từ khóa đang ở trang 1–2"),
                                    ("timeline", "Lộ trình 3 giai đoạn, KPI theo dõi và rủi ro")):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.icon(icon, size="18px").classes("sr-br-ico")
                            ui.label(t).classes("text-sm")
            else:
                render_strategy(ui, p)
        with foot:
            ui.label(_meta(p) if p else "Số liệu do tool tính từ Google; AI phân tích và đề xuất.").classes(
                "text-xs muted col ellipsis")
            if p:
                ui.button("Sao chép", icon="content_copy", on_click=lambda: (
                    ui.clipboard.write(strategy_text(state["p"])), ui.notify("Đã sao chép", type="positive"))).props(
                    "flat no-caps")
            lbl = ("Lập lại" if p else "Lập chiến lược") + (f" · {cost} credit" if PT.member(user) else "")
            b = ui.button(lbl, icon="auto_fix_high", on_click=lambda: go(b)).props(
                "unelevated no-caps color=deep-purple-1 text-color=deep-purple-9")

    async def go(b) -> None:
        b.props("loading")
        res = await _run(ui, user, cfg, "ai_plan", f"{len(rows)} từ khóa", S.write, rows, _brand(connect, cfg))
        b.props(remove="loading")
        if not res:
            return
        out, used = res
        out["title"] = strategy_title(rows)
        with connect() as c:
            AW.save(c, cfg.site_url, S.KIND, key, out, used, str(user))
            state["p"] = AW.latest(c, cfg.site_url, S.KIND, key)
        render()

    render()
    dlg.open()


# ---------------------------------------------------------------- brief một từ khóa

def brief_text(keyword: str, b: dict) -> str:
    out = [f"Brief: {keyword}", "", f"Ý định: {b['intent']}", f"Dạng bài: {b['format']}", f"Title: {b['title']}",
           f"Meta: {b['meta']}", "", "Dàn ý:"]
    for o in b["outline"]:
        out.append(f"H2: {o['h2']}" + (f"  ({o['note']})" if o["note"] else ""))
        out += [f"   H3: {h}" for h in o["h3"]]
    if b["must_cover"]:
        out += ["", "Bắt buộc có:"] + [f"- {x}" for x in b["must_cover"]]
    if b["faq"]:
        out += ["", "FAQ:"] + [f"- {x}" for x in b["faq"]]
    return "\n".join(out)


def render_brief(ui, b: dict) -> None:
    with ui.element("div").classes("sr-ar-brief"):
        for lb, v, n in (("Title", b["title"], 60), ("Meta", b["meta"], 155)):
            with ui.row().classes("w-full items-start no-wrap gap-2"):
                ui.label(lb).classes("sr-ar-lb")
                ui.label(v).classes("text-sm col")
                ui.label(f"{len(v)}/{n}").classes("text-xs num").style(
                    f"color:{T.AMBER_TEXT if len(v) > n else T.MUTED}")
        for lb, v in (("Ý định", b["intent"]), ("Dạng bài", b["format"])):
            if v:
                with ui.row().classes("w-full items-start no-wrap gap-2"):
                    ui.label(lb).classes("sr-ar-lb")
                    ui.label(v).classes("text-sm col")
    ui.label("Dàn ý").classes("sr-aw-h")
    with ui.element("div").classes("sr-ar-outline"):
        for o in b["outline"]:
            with ui.element("div").classes("sr-ar-h2"):
                ui.label(o["h2"]).classes("text-sm font-medium")
                if o["note"]:
                    ui.label(o["note"]).classes("text-xs muted")
                for h in o["h3"]:
                    ui.label(h).classes("sr-ar-h3")
    for title, items in (("Bắt buộc có", b["must_cover"]), ("Câu hỏi nên trả lời (FAQ)", b["faq"])):
        if items:
            ui.label(title).classes("sr-aw-h")
            ui.html("<ul class='sr-aw-list'>" + "".join(f"<li>{escape(x)}</li>" for x in items) + "</ul>")
    ui.label("AI viết nháp: kiểm tra lại với trang kết quả Google trước khi giao cho người viết.").classes(
        "text-xs muted")


def brief_dialog(ui, connect, cfg, user, d: dict) -> None:
    if not A.can_edit(user) or not d:
        return
    from . import keywords as K
    ref = K.fold(d["keyword"])
    with connect() as c:
        saved = AW.latest(c, cfg.site_url, "kw_brief", ref)
    state = {"b": saved}
    cost = PT.cost("ai_kwbrief")
    sp = d.get("serp") or {}
    dlg, body, foot = _frame(ui, f"AI viết brief: {d['keyword']}",
                             f"Dựa trên ý định, {len(d.get('questions') or [])} câu hỏi, biến thể"
                             + (f", top {min(len(sp.get('results') or []), 10)} Google" if sp.get("results") else
                                " (chưa có trang kết quả Google: brief sẽ kém chính xác hơn)"), width=760)

    def render() -> None:
        body.clear()
        foot.clear()
        b = state["b"]
        with body:
            if not b:
                ui.label("AI viết dàn ý bài: title, meta, các mục H2 / H3, ý bắt buộc phải có và câu hỏi nên trả lời. "
                         "Chỗ cần số liệu riêng của doanh nghiệp để [điền …].").classes("text-sm")
            else:
                render_brief(ui, b)
        with foot:
            ui.label(_meta(b) if b else "").classes("text-xs muted col ellipsis")
            if b:
                ui.button("Sao chép", icon="content_copy", on_click=lambda: (
                    ui.clipboard.write(brief_text(d["keyword"], state["b"])),
                    ui.notify("Đã sao chép", type="positive"))).props("flat no-caps")
            lbl = ("Viết lại" if b else "Viết brief") + (f" · {cost} credit" if PT.member(user) else "")
            btn = ui.button(lbl, icon="auto_fix_high", on_click=lambda: go(btn)).props(
                "unelevated no-caps color=deep-purple-1 text-color=deep-purple-9")

    async def go(btn) -> None:
        btn.props("loading")
        res = await _run(ui, user, cfg, "ai_kwbrief", d["keyword"], AR.write_brief, d, _brand(connect, cfg))
        btn.props(remove="loading")
        if not res:
            return
        out, used = res
        out["keyword"] = d["keyword"]
        with connect() as c:
            AW.save(c, cfg.site_url, "kw_brief", ref, out, used, str(user))
            state["b"] = AW.latest(c, cfg.site_url, "kw_brief", ref)
        render()

    render()
    dlg.open()
