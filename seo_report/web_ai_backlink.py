"""Giao diện AI ở trang Backlink (ai_backlink.py). Chỉ team; chỉ gọi AI khi bấm; Member trừ credit; mọi bản lưu ở
thư viện (ai_drafts) để xem lại.

ctx (SimpleNamespace từ web_backlink): cfg, connect, user, site, ld, bl, ls, checks, brand_terms, refresh()."""
from datetime import date, datetime

from . import ai_backlink as AB
from . import ai_settings as AIS
from . import ai_writer as AW
from . import points as PT
from . import site_labels as SL

LEVEL = {"risk": ("Đáng lo", "risk"), "watch": ("Theo dõi", "watch"), "good": ("Tốt", "good")}
KINDS = {"backlink_insight": "Nhận định", "backlink_classify": "Phân loại website", "backlink_disavow": "Duyệt disavow",
         "backlink_rivals": "Chiến lược đối thủ", "backlink_plan": "Kế hoạch xây link"}
REF = "site"


def _cost(user, action: str) -> str:
    return f" · {PT.cost(action)} credit" if PT.member(user) else ""


def _when(iso) -> str:
    try:
        return f"{datetime.fromisoformat(iso).astimezone():%d/%m %H:%M}"
    except (TypeError, ValueError):
        return ""


async def _run(ui, ctx, action: str, detail: str, fn, data):
    from .web_ai_research import _run as run_ai
    return await run_ai(ui, ctx.user, ctx.cfg, action, detail, fn, data)


def _labels_table() -> tuple[dict, list[str]]:
    try:
        with SL.connect() as c:
            return SL.all_labels(c), [d["name"] for d in SL.defs(c)]
    except Exception:  # noqa: BLE001
        return {}, []


def _save(ctx, kind: str, ref: str, res) -> dict:
    with ctx.connect() as c:
        AW.save(c, ctx.site, kind, ref, res[0], res[1], str(ctx.user))
        return AW.latest(c, ctx.site, kind, ref)


# ---------------------------------------------------------------- 1. nhận định hồ sơ (Tổng quan)

def _profile_body(ui, d: dict) -> None:
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


def profile_box(ui, ctx) -> None:
    """Khối AI nhận định ở đầu tab Tổng quan + nút thư viện AI của trang Backlink."""
    if not AIS.enabled(ctx.site, "backlink_insight"):
        return
    labels, _ = _labels_table()

    def facts() -> dict:
        counts: dict[str, int] = {}
        for g in {x["d_from"] for x in (ctx.ld or {}).get("items") or []}:
            for lb in SL.lookup(labels, g):
                counts[lb] = counts.get(lb, 0) + 1
        return AB.profile_facts(ctx.ld, ctx.bl, ctx.checks, counts)
    with ctx.connect() as c:
        state = {"d": AW.latest(c, ctx.site, "backlink_insight", REF)}
    now_fp = AB.AR.fingerprint(facts())

    @ui.refreshable
    def box() -> None:
        d = state["d"]
        with ui.element("div").classes("sr-rai w-full q-mb-md"):
            with ui.row().classes("w-full items-center gap-2 no-wrap sr-rai-top"):
                ui.icon("auto_awesome", size="18px").classes("sr-br-ico")
                ui.label("AI nhận định hồ sơ backlink").classes("sr-rai-title")
                if d:
                    ui.label(_when(d.get("at"))).classes("sr-br-sub ellipsis")
                    if d.get("fingerprint") != now_fp:
                        ui.label("Đã có số mới, bấm để cập nhật").classes("sr-rai-stale")
                ui.space()
                ui.button(icon="history", on_click=lambda: library_dialog(ui, ctx)).props(
                    "flat round dense color=grey-8").tooltip("Thư viện AI của trang Backlink")
                b = ui.button("AI nhận định" if not d else "Nhận định lại", icon="auto_awesome").props(
                    "unelevated no-caps dense color=deep-purple-1 text-color=deep-purple-9").classes("sr-kg-aibtn")
                b.on_click(lambda _, b=b: go(b))
                b.tooltip("AI đọc số gộp + các mục Audit, viết nhận định và việc nên làm"
                          + _cost(ctx.user, "ai_bl_insight"))
            if d:
                _profile_body(ui, d)
                ui.label("AI đọc số tool đã tính; câu có số không có trong dữ liệu đã bị bỏ. Chỉ để tham khảo.").classes(
                    "sr-kai-note")
            else:
                ui.label("Bấm “AI nhận định” để AI tóm tắt sức khỏe hồ sơ backlink và việc nên làm trước.").classes(
                    "text-xs muted")

    async def go(btn) -> None:
        btn.props("loading")
        try:
            res = await _run(ui, ctx, "ai_bl_insight", "nhận định hồ sơ backlink", AB.write_profile, facts())
        finally:
            btn.props(remove="loading")
        if res:
            state["d"] = _save(ctx, "backlink_insight", REF, res)
            box.refresh()
    box()


# ---------------------------------------------------------------- 2. phân loại website (Audit)

def classify_dialog(ui, ctx) -> None:
    labels, allowed = _labels_table()
    with ctx.connect() as c:
        state = {"d": AW.latest(c, ctx.site, "backlink_classify", REF)}
    pick: dict[str, bool] = {}
    with ui.dialog() as d, ui.card().style("width:860px; max-width:96vw; border-radius:14px"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.icon("auto_awesome", size="20px").classes("sr-br-ico")
            ui.label("AI phân loại website trỏ về").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        ui.label(f"AI xem tối đa {AB.MAX_CLASSIFY} website chưa gắn nhãn (nhiều link trước) và gợi ý một nhãn kèm lý do. "
                 "Tick những gợi ý đúng rồi bấm Gắn nhãn; nhãn dùng chung mọi dự án.").classes("text-xs muted")

        @ui.refreshable
        def body() -> None:
            res = state["d"]
            if not res:
                ui.label("Chưa chạy lần nào.").classes("text-sm muted q-mt-sm")
                return
            ui.label(f"Kết quả lúc {_when(res.get('at'))}").classes("text-xs muted q-mt-sm")
            with ui.column().classes("w-full gap-0 q-mt-xs").style("max-height:55vh; overflow:auto"):
                for x in res.get("items") or []:
                    key = x["website"]
                    pick.setdefault(key, x["label"] != "Khác" and x["confidence"] != "low")
                    with ui.row().classes("w-full items-center no-wrap gap-2 sr-qc-row"):
                        ui.checkbox(value=pick[key], on_change=lambda e, k=key: pick.update({k: e.value})).props(
                            "dense").set_enabled(x["label"] != "Khác")
                        with ui.column().classes("gap-0 col").style("min-width:0"):
                            ui.link(key, f"https://{key}", new_tab=True).classes("text-sm sr-bb-link")
                            ui.label(x["reason"]).classes("text-xs muted ellipsis")
                        ui.label(x["label"]).classes("sr-lbl").style("color:#1D4ED8;border-color:#1D4ED840")
                        ui.label({"high": "chắc", "medium": "khá chắc", "low": "chưa chắc"}[x["confidence"]]).classes(
                            "text-xs muted").style("width:64px")
        body()

        async def run_() -> None:
            b_run.props("loading")
            try:
                f = AB.classify_facts((ctx.ld or {}).get("items") or [], labels, allowed)
                if not f["website"]:
                    ui.notify("Mọi website đã có nhãn", type="info")
                    return
                res = await _run(ui, ctx, "ai_bl_classify", f"phân loại {len(f['website'])} website",
                                 AB.write_classify, f)
            finally:
                b_run.props(remove="loading")
            if res:
                state["d"] = _save(ctx, "backlink_classify", REF, res)
                pick.clear()
                body.refresh()

        def apply_() -> None:
            res = state["d"] or {}
            by_label: dict[str, list[str]] = {}
            for x in res.get("items") or []:
                if pick.get(x["website"]) and x["label"] in allowed:
                    by_label.setdefault(x["label"], []).append(x["website"])
            if not by_label:
                ui.notify("Chưa tick gợi ý nào", type="warning")
                return
            with SL.connect() as c:
                for lab, doms in by_label.items():
                    SL.apply(c, doms, add=[lab], user=str(ctx.user))
            d.close()
            ui.notify(f"Đã gắn nhãn cho {sum(len(v) for v in by_label.values())} website", type="positive",
                      position="bottom-right")
            ctx.refresh()
        with ui.row().classes("w-full justify-end gap-2 q-mt-md"):
            b_run = ui.button(("Chạy lại" if state["d"] else "Chạy AI phân loại") + _cost(ctx.user, "ai_bl_classify"),
                              icon="auto_awesome", on_click=run_).props("outline no-caps")
            ui.button("Gắn nhãn đã tick", icon="sell", on_click=apply_).props("unelevated no-caps")
    d.on("hide", d.delete)
    d.open()


# ---------------------------------------------------------------- 3. duyệt disavow (Audit)

def disavow_dialog(ui, ctx) -> None:
    with ctx.connect() as c:
        state = {"d": AW.latest(c, ctx.site, "backlink_disavow", REF)}
    with ui.dialog() as d, ui.card().style("width:860px; max-width:96vw; border-radius:14px"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.icon("auto_awesome", size="20px").classes("sr-br-ico")
            ui.label("AI duyệt danh sách disavow").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        ui.label("AI xem các website nghi spam (điểm spam cao, Google cảnh báo, chung IP) và đề xuất disavow / giữ / "
                 "xem tay. Google khuyên chỉ disavow khi chắc chắn: xem lại trước khi nộp.").classes("text-xs muted")

        @ui.refreshable
        def body() -> None:
            res = state["d"]
            if not res:
                ui.label("Chưa chạy lần nào.").classes("text-sm muted q-mt-sm")
                return
            items = res.get("items") or []
            n = {k: sum(1 for x in items if x["decision"] == k) for k in AB.DECISIONS}
            ui.label(f"Kết quả lúc {_when(res.get('at'))} · " + " · ".join(f"{AB.DECISIONS[k]} {v}"
                                                                           for k, v in n.items())).classes(
                "text-xs muted q-mt-sm")
            if res.get("note"):
                ui.label(res["note"]).classes("text-sm q-mt-xs")
            tone = {"disavow": "#C2410C", "keep": "#1E7C31", "review": "#B7791F"}
            with ui.column().classes("w-full gap-0 q-mt-xs").style("max-height:55vh; overflow:auto"):
                for x in sorted(items, key=lambda x: list(AB.DECISIONS).index(x["decision"])):
                    with ui.row().classes("w-full items-center no-wrap gap-2 sr-qc-row"):
                        ui.label(AB.DECISIONS[x["decision"]]).classes("text-xs font-semibold").style(
                            f"color:{tone[x['decision']]}; width:64px")
                        ui.link(x["website"], f"https://{x['website']}", new_tab=True).classes(
                            "text-sm sr-bb-link").style("width:220px")
                        ui.label(x["reason"]).classes("text-xs muted col ellipsis")
        body()

        async def run_() -> None:
            b_run.props("loading")
            try:
                f = AB.disavow_facts((ctx.ld or {}).get("items") or [], ctx.checks)
                res = await _run(ui, ctx, "ai_bl_disavow", f"duyệt {len(f['website'])} website", AB.write_disavow, f)
            finally:
                b_run.props(remove="loading")
            if res:
                state["d"] = _save(ctx, "backlink_disavow", REF, res)
                body.refresh()

        def download() -> None:
            res = state["d"] or {}
            if not any(x["decision"] == "disavow" for x in res.get("items") or []):
                ui.notify("AI chưa đề xuất disavow website nào", type="info")
                return
            ui.download.content(AB.disavow_text(res["items"], f"{date.today():%d/%m/%Y}"),
                                f"disavow-ai-{ctx.site.split('//')[-1].strip('/')}-{date.today():%Y%m%d}.txt",
                                "text/plain")
        with ui.row().classes("w-full justify-end gap-2 q-mt-md"):
            b_run = ui.button(("Chạy lại" if state["d"] else "Chạy AI duyệt") + _cost(ctx.user, "ai_bl_disavow"),
                              icon="auto_awesome", on_click=run_).props("outline no-caps")
            ui.button("Tải file disavow (AI đề xuất)", icon="download", on_click=download).props("unelevated no-caps")
    d.on("hide", d.delete)
    d.open()


# ---------------------------------------------------------------- 4. chiến lược đối thủ (Backlink GAP)

def _rivals_body(ui, d: dict) -> None:
    if d.get("summary"):
        ui.label(d["summary"]).classes("sr-rai-headline")
    for r in d.get("rivals") or []:
        with ui.column().classes("gap-0 q-mt-xs"):
            ui.label(r["name"]).classes("text-sm font-semibold")
            ui.label(r["strategy"]).classes("text-sm")
            if r.get("evidence"):
                ui.label(r["evidence"]).classes("text-xs muted")
    if d.get("lessons"):
        ui.label("Website mình nên làm").classes("sr-rai-h q-mt-sm")
        for i, a in enumerate(d["lessons"], 1):
            with ui.row().classes("items-start no-wrap gap-2"):
                ui.label(str(i)).classes("sr-rai-num")
                ui.label(a).classes("text-sm")


def rivals_dialog(ui, ctx) -> None:
    from . import backlink_gap as BG
    labels, _ = _labels_table()
    with ctx.connect() as c:
        state = {"d": AW.latest(c, ctx.site, "backlink_rivals", REF)}
        gap = BG.latest(c, ctx.site)
    with ui.dialog() as d, ui.card().style("width:760px; max-width:96vw; border-radius:14px"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.icon("auto_awesome", size="20px").classes("sr-br-ico")
            ui.label("AI chiến lược backlink đối thủ").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        ui.label("Từ Backlink GAP (DataForSEO + file Semrush) và nhãn website: đối thủ dựa vào loại link nào, website "
                 "mình nên làm gì. Gắn nhãn website trước thì AI phân tích chính xác hơn.").classes("text-xs muted")

        @ui.refreshable
        def body() -> None:
            if not state["d"]:
                ui.label("Chưa chạy lần nào.").classes("text-sm muted q-mt-sm")
                return
            ui.label(f"Kết quả lúc {_when(state['d'].get('at'))}").classes("text-xs muted q-mt-sm")
            with ui.column().classes("w-full gap-1").style("max-height:60vh; overflow:auto"):
                _rivals_body(ui, state["d"])
        body()

        async def run_() -> None:
            b.props("loading")
            try:
                res = await _run(ui, ctx, "ai_bl_rivals", "chiến lược đối thủ", AB.write_rivals,
                                 AB.rivals_facts(gap, labels))
            finally:
                b.props(remove="loading")
            if res:
                state["d"] = _save(ctx, "backlink_rivals", REF, res)
                body.refresh()
        with ui.row().classes("w-full justify-end q-mt-md"):
            b = ui.button(("Phân tích lại" if state["d"] else "Phân tích") + _cost(ctx.user, "ai_bl_rivals"),
                          icon="auto_awesome", on_click=run_).props("unelevated no-caps")
    d.on("hide", d.delete)
    d.open()


# ---------------------------------------------------------------- 5. kế hoạch xây link (Trang đích › Cần thêm link)

def _plan_body(ui, d: dict) -> None:
    for x in d.get("items") or []:
        with ui.column().classes("gap-0 q-mt-sm sr-qc-row"):
            ui.label(f"“{x['keyword']}” → {x['url']}").classes("text-sm font-semibold ellipsis")
            ui.label(f"Anchor nên dùng: {AB.ANCHOR_KINDS.get(x['anchor_kind'], x['anchor_kind'])}"
                     + (" · ví dụ: " + " / ".join(f"“{a}”" for a in x["anchors"]) if x.get("anchors") else "")).classes(
                "text-xs")
            if x.get("sources"):
                ui.label("Nguồn gợi ý: " + ", ".join(x["sources"])).classes("text-xs")
            for s in x.get("steps") or []:
                ui.label(f"• {s}").classes("text-xs muted")


def plan_dialog(ui, ctx, rows: list[dict]) -> None:
    from . import backlink_gap as BG
    labels, _ = _labels_table()
    with ctx.connect() as c:
        gap = BG.latest(c, ctx.site)
        state = {"d": None}
    with ui.dialog() as d, ui.card().style("width:820px; max-width:96vw; border-radius:14px"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.icon("auto_awesome", size="20px").classes("sr-br-ico")
            ui.label(f"AI kế hoạch xây link · {min(len(rows), AB.MAX_PLAN)} trang").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        ui.label("Mỗi trang: kiểu anchor nên dùng (theo cơ cấu anchor hiện có của trang), nguồn link gợi ý từ Backlink "
                 "GAP, việc cụ thể. Kết quả lưu ở thư viện AI.").classes("text-xs muted")

        @ui.refreshable
        def body() -> None:
            if state["d"]:
                with ui.column().classes("w-full gap-0").style("max-height:60vh; overflow:auto"):
                    _plan_body(ui, state["d"])

        async def run_() -> None:
            b.props("loading")
            try:
                data = AB.plan_facts(rows, (ctx.ld or {}).get("items") or [], gap, labels, ctx.brand_terms)
                res = await _run(ui, ctx, "ai_bl_plan", f"kế hoạch {len(data[0]['trang'])} trang", AB.write_plan, data)
            finally:
                b.props(remove="loading")
            if res:
                state["d"] = _save(ctx, "backlink_plan", REF, res)
                body.refresh()
        body()
        with ui.row().classes("w-full justify-end q-mt-md"):
            b = ui.button("Lập kế hoạch" + _cost(ctx.user, "ai_bl_plan"), icon="auto_awesome",
                          on_click=run_).props("unelevated no-caps")
    d.on("hide", d.delete)
    d.open()


# ---------------------------------------------------------------- thư viện

def library_dialog(ui, ctx) -> None:
    with ctx.connect() as c:
        lists = {k: AW.history(c, ctx.site, k, [REF]) for k in KINDS}
    with ui.dialog() as d, ui.card().style("width:880px; max-width:96vw; border-radius:14px"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("Thư viện AI · Backlink").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        with ui.tabs().props("dense no-caps align=left").classes("sr-tabs") as tabs:
            for k, name in KINDS.items():
                ui.tab(k, f"{name} · {len(lists[k])}")
        with ui.tab_panels(tabs, value="backlink_insight").classes("w-full").style("max-height:65vh; overflow:auto"):
            for k in KINDS:
                with ui.tab_panel(k):
                    if not lists[k]:
                        ui.label("Chưa có bản nào.").classes("text-sm muted")
                    for x in lists[k]:
                        with ui.expansion(f"{_when(x.get('at'))} · {x.get('by') or ''}").props("dense").classes(
                                "w-full"):
                            if k == "backlink_insight":
                                _profile_body(ui, x)
                            elif k == "backlink_rivals":
                                _rivals_body(ui, x)
                            elif k == "backlink_plan":
                                _plan_body(ui, x)
                            elif k == "backlink_classify":
                                for it in x.get("items") or []:
                                    ui.label(f"{it['website']} → {it['label']} · {it['reason']}").classes("text-xs")
                            else:
                                for it in x.get("items") or []:
                                    ui.label(f"{AB.DECISIONS.get(it['decision'], '')}: {it['website']} · "
                                             f"{it['reason']}").classes("text-xs")
    d.on("hide", d.delete)
    d.open()
