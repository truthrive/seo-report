"""Hai tab xây link trên trang Backlink: "Trang cần link" và "Link đã xây" (backlink_build.py). Không tốn phí."""
from datetime import date
from urllib.parse import quote, urlparse

from . import access as A
from . import ai_format as F
from . import backlink_build as BB
from . import ui_theme as T


def _path(url: str) -> str:
    p = urlparse(url or "")
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def _vn(iso) -> str:
    try:
        return f"{date.fromisoformat(str(iso)[:10]):%d/%m/%Y}"
    except (TypeError, ValueError):
        return "–"


def _url_href() -> str:
    """Biểu thức Vue: link sang trang chi tiết URL trong tool."""
    return "'/url?u=' + encodeURIComponent(props.row.url)"


def internal_dialog(ui, cfg, connect, target: str) -> None:
    """Gợi ý trang của website nên đặt link nội bộ sang `target`, kèm anchor; tự tải các trang nguồn để biết đã có
    link chưa (miễn phí)."""
    from nicegui import background_tasks, run

    from . import keywords as K
    with connect() as c:
        sg = BB.internal_suggestions(c, cfg.site_url, target, K.latest_date(c, cfg.site_url))
    with ui.dialog() as d, ui.card().classes("sr-ar-dlg q-pa-none").style("width:720px"):
        with ui.row().classes("w-full items-start no-wrap gap-2 sr-ar-head"):
            ui.icon("alt_route", size="20px").classes("q-mt-xs").style("color:#1E7C31")
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label("Gợi ý link nội bộ").classes("sr-br-h")
                ui.label(f"Đặt link từ các trang dưới sang {_path(target)}").classes("sr-br-sub ellipsis")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        with ui.column().classes("w-full gap-2 sr-ar-body"):
            if not sg["rows"]:
                ui.label("Chưa tìm được trang cùng chủ đề có click trong 28 ngày.").classes("text-sm muted")
            else:
                with ui.row().classes("items-baseline gap-2"):
                    ui.label("Anchor nên dùng:").classes("text-sm muted")
                    ui.label(f"“{sg['anchor']}”").classes("text-sm font-semibold")
                if len(sg["topic"]) > 1:
                    ui.label("Hoặc: " + " · ".join(f"“{t}”" for t in sg["topic"][1:4])).classes("text-xs muted")
                marks = {}
                with ui.element("div").classes("sr-bb-ilist"):
                    for r in sg["rows"]:
                        with ui.element("div").classes("sr-bb-irow"):
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                with ui.row().classes("items-center no-wrap gap-1"):
                                    ui.link(_path(r["url"]), "/url?u=" + quote(r["url"], safe="")).classes(
                                        "sr-bb-link ellipsis")
                                    ui.link("", r["url"], new_tab=True).classes("sr-bb-ext").props(
                                        'aria-label="Mở trang trên site"').style("text-decoration:none")
                                ui.label(f"{F.n(r['clicks'])} click 28 ngày · cũng hiện cho “{r['match']}”").classes(
                                    "sr-bb-sub ellipsis")
                            marks[r["url"]] = ui.label("đang kiểm tra…").classes("sr-bb-st grey")
                ui.label("Tool tải từng trang nguồn để xem đã có link sang trang đích chưa. Đặt link ở đoạn nội dung "
                         "liên quan, không đặt ở chân trang.").classes("text-xs muted")

                async def scan():
                    for r in sg["rows"]:
                        ok = await run.io_bound(BB.has_link, r["url"], target)
                        lab = marks[r["url"]]
                        lab.text, cls = (("Đã có link", "green") if ok else ("Chưa có link", "red") if ok is False
                                         else ("Không tải được", "grey"))
                        lab.classes(replace=f"sr-bb-st {cls}")
                background_tasks.create(scan())
        with ui.row().classes("w-full justify-end sr-ar-foot"):
            ui.button("Đóng", on_click=d.close).props("flat no-caps")
    d.on("hide", d.delete)
    d.open()


def needs_panel(ui, cfg, connect, lists: dict) -> None:
    from . import urls as U
    with connect() as c:
        groups = dict(U.list_groups(c, cfg.site_url))
        seo = BB.seo_urls(c, cfg.site_url)
    state = {"g": 0}

    @ui.refreshable
    def panel() -> None:
        _needs(ui, cfg, connect, lists, state, groups, seo, panel)
    panel()


def _needs(ui, cfg, connect, lists: dict, state: dict, groups: dict, seo: list, panel) -> None:
    from . import keywords as K
    only = None
    if state["g"]:
        only = {BB.norm(r["url"]) for r in seo if state["g"] in r["group_ids"]}
    with connect() as c:
        res = BB.needs(c, cfg.site_url, lists, K.latest_date(c, cfg.site_url), only=only)
    seo_keys = {BB.norm(r["url"]): r["groups"] for r in seo}
    s, e = res["window"]
    with T.section(ui, "Trang cần link", "trending_up",
                   f"Trang có từ khóa ở vị trí {BB.NEED_POS[0]}–{BB.NEED_POS[1]} (Search Console {_vn(s.isoformat())} – "
                   f"{_vn(e.isoformat())} và từ khóa đang check rank) nhưng ít website trỏ về: thêm vài link là dễ lên "
                   "Top nhất"):
        if groups:
            with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
                ui.label("Xét trang:").classes("text-xs muted")

                def pick(e):
                    state["g"] = e.value
                    panel.refresh()
                ui.select({0: "Mọi trang có số", **{k: f"Nhóm {v}" for k, v in groups.items()}}, value=state["g"],
                          on_change=pick).props("dense outlined options-dense").classes("sr-bb-gsel")
        if not res["rows"]:
            ui.label("Chưa có trang nào có từ khóa ở vị trí 4–20" + (" trong nhóm này." if state["g"] else ".")
                     ).classes("text-sm muted")
            return
        if not res["known"]:
            ui.label("Chưa lấy danh sách “Trang được link” nên chưa biết số website trỏ về từng trang.").classes(
                "text-xs muted q-mb-sm")
        elif not res["complete"]:
            ui.label(f"Danh sách “Trang được link” chỉ giữ {len((lists.get('pages') or {}).get('items') or [])} trang "
                     "nhiều link nhất; trang ngoài danh sách ghi là “ít”.").classes("text-xs muted q-mb-sm")
        rows = []
        for r in res["rows"]:
            b = r["best"]
            dom = r["domains"]
            rows.append({"url": r["url"], "path": _path(r["url"]), "best": b["q"], "pos": b["pos"],
                         "seo": ", ".join(seo_keys.get(BB.norm(r["url"]), [])),
                         "src": "check rank" if "impr" not in b else "",
                         "n": r["n"] + r["tracked"], "impr": r["impr"], "impr_t": F.n(r["impr"]) if r["impr"] else "–",
                         "dom": dom if dom is not None else 9999,
                         "dom_t": str(dom) if dom is not None else "ít"})
        cols = [{"name": "path", "label": "Trang", "field": "path", "align": "left"},
                {"name": "best", "label": "Từ khóa sắp lên Top", "field": "best", "align": "left"},
                {"name": "n", "label": "Số từ khóa 4–20", "field": "n", "align": "right", "sortable": True},
                {"name": "impr", "label": "Lượt hiển thị", "field": "impr", "align": "right", "sortable": True},
                {"name": "dom", "label": "Website trỏ về", "field": "dom", "align": "right", "sortable": True},
                {"name": "act", "label": "", "field": "url", "align": "right"}]
        tbl = ui.table(columns=cols, rows=rows, row_key="url", pagination=15).classes("w-full sr-kw-tbl").props(
            "flat dense")
        tbl.add_slot("body-cell-act", """
            <q-td :props="props"><q-btn flat dense no-caps size="sm" icon="alt_route" label="Link nội bộ"
              color="grey-8" @click="$parent.$emit('internal', props.row.url)">
              <q-tooltip>Gợi ý trang của website nên đặt link sang trang này</q-tooltip></q-btn></q-td>""")
        tbl.on("internal", lambda e: internal_dialog(ui, cfg, connect, e.args))
        tbl.add_slot("body-cell-path", """
            <q-td :props="props"><a :href=" """ + _url_href() + """ " class="sr-bb-link ellipsis"
              :title="'Mở chi tiết URL: ' + props.row.url">{{ props.row.path }}</a>
              <a :href="props.row.url" target="_blank" rel="noopener" class="sr-bb-ext" aria-label="Mở trang trên site">
                <q-icon name="open_in_new" size="13px" /></a>
              <div v-if="props.row.seo" class="sr-bb-sub">URL SEO · {{ props.row.seo }}</div></q-td>""")
        tbl.add_slot("body-cell-best", """
            <q-td :props="props"><span class="sr-bb-q">{{ props.row.best }}</span>
              <span class="sr-bb-pos">vị trí {{ props.row.pos }}</span></q-td>""")
        tbl.add_slot("body-cell-impr", """<q-td :props="props">{{ props.row.impr_t }}</q-td>""")
        tbl.add_slot("body-cell-dom", """
            <q-td :props="props"><span :class="props.row.dom_t === 'ít' || props.row.dom < 3 ? 'sr-bb-low' : ''">
              {{ props.row.dom_t }}</span></q-td>""")
        if res["total"] > len(rows):
            ui.label(f"Hiện {len(rows)} / {res['total']} trang có cơ hội cao nhất.").classes("text-xs muted q-mt-xs")


def url_block(ui, cfg, connect, user, url: str) -> None:
    """Khối Backlink ở trang chi tiết URL: website trỏ về, link đã xây trỏ vào, có đang là trang cần link không."""
    from . import backlinks as BL
    from . import keywords as K
    with connect() as c:
        info = BB.url_info(c, cfg.site_url, url, BL.lists(c, cfg.site_url), K.latest_date(c, cfg.site_url))
    built = info["built"]
    alive = sum(1 for b in built if b["state"] in ("ok", "nofollow", "anchor"))
    with T.section(ui, "Backlink", "add_link", "Website trỏ về trang này và link team đã xây",
                   href="/backlink?tab=built", link_text="Link đã xây"):
        with ui.element("div").classes("sr-bb-facts"):
            with ui.element("div"):
                ui.label("Website trỏ về").classes("sr-kg-sk")
                d = info["domains"]
                ui.label(F.n(d) if d is not None else ("ít" if info["known"] else "chưa lấy số")).classes(
                    "sr-kg-sv num" + (" none" if d is None else ""))
            with ui.element("div"):
                ui.label("Link đã xây").classes("sr-kg-sk")
                ui.html(f'<div class="sr-kg-sv num">{alive}<span>/{len(built)} còn</span></div>' if built else
                        '<div class="sr-kg-sv none">Chưa có</div>')
            with ui.element("div"):
                ui.label("Cần thêm link?").classes("sr-kg-sk")
                n = info["need"]
                if n:
                    ui.label(f"Có · {n['n'] + n['tracked']} từ khóa ở vị trí 4–20").classes("sr-kg-sv none sr-bb-low")
                else:
                    ui.label("Chưa cần (không có từ khóa ở 4–20)").classes("sr-kg-sv none")
        if built:
            for b in built[:8]:
                lab, tone = BB.STATES.get(b["state"], ("–", "grey"))
                with ui.row().classes("w-full items-center no-wrap gap-2 sr-bb-urow"):
                    ui.html(f'<span class="sr-bb-st {tone}">{lab}</span>')
                    ui.link(urlparse(b["url_from"]).netloc, b["url_from"], new_tab=True).classes(
                        "sr-bb-link ellipsis col")
                    if b["anchor"]:
                        ui.label(f"“{b['anchor']}”").classes("sr-bb-sub ellipsis")
        with ui.row().classes("items-center gap-2 q-mt-xs"):
            ui.button("Gợi ý link nội bộ", icon="alt_route", on_click=lambda: internal_dialog(ui, cfg, connect, url)
                      ).props("flat no-caps dense size=sm color=grey-8")
            if A.can_edit(user):
                ui.link("Thêm link đã xây cho trang này", "/backlink?tab=built").classes("text-xs")


def gap_panel(ui, cfg, connect, user) -> None:
    """Website link về đối thủ nhưng chưa link về mình (DataForSEO, tốn phí: chỉ lấy khi bấm, hiện giá trước)."""
    from nicegui import run

    from . import backlink_gap as BG
    from . import points as PT
    site = cfg.site_url
    ed = A.can_edit(user)
    cl = A.is_client(user)
    state = {"multi": False, "spam": True, "q": "", "pick": None}

    @ui.refreshable
    def body() -> None:
        with connect() as c:
            rv = BG.rivals(c, cfg)
            gap = BG.latest(c, site)
        if state["pick"] is None:
            state["pick"] = {r["id"] for r in rv}
        with T.section(ui, "Backlink GAP", "group_add",
                       "Website đang đặt link (dofollow) về đối thủ nhưng chưa link về mình: danh sách nên đi xin link. "
                       "Website link về càng nhiều đối thủ càng dễ xin"):
            if not rv:
                ui.label("Chưa có đối thủ nào có tên miền.").classes("text-sm muted")
                ui.link("Thêm đối thủ ở trang Đối thủ", "/doi-thu").classes("text-sm")
                return
            if ed and not cl:
                with ui.row().classes("w-full items-center gap-2 q-mb-sm sr-bg-pick"):
                    ui.label("Đối thủ:").classes("text-xs muted")
                    for r in rv:
                        ui.checkbox(r["name"], value=r["id"] in state["pick"],
                                    on_change=lambda e, i=r["id"]: toggle(i, e.value)).props("dense").tooltip(
                            r["domain"])
                    ui.space()
                    n = len(state["pick"])
                    price = (f"{PT.cost('backlink_gap', n)} credit" if PT.member(user) else
                             f"~{BG.estimate(n):.2f} USD".replace(".", ","))
                    btn = ui.button(f"{'Tìm lại' if gap else 'Tìm backlink GAP'} · {price}", icon="travel_explore",
                                    on_click=lambda: confirm(btn)).props("unelevated no-caps")
                    if not n or cfg.rank.paused:
                        btn.disable()
            if not gap:
                ui.label("Chưa tìm lần nào." + (" Chọn đối thủ rồi bấm Tìm backlink GAP (tốn phí dữ liệu, chỉ chạy khi "
                                                 "bấm)." if ed else "")).classes("text-sm muted")
                return
            ui.label(f"Lấy ngày {_vn(gap['fetched_at'])} · {len(gap['rivals'])} đối thủ: "
                     + ", ".join(r["name"] for r in gap["rivals"])).classes("text-xs muted q-mb-xs")
            items = gap["items"]
            with ui.row().classes("w-full items-center gap-3 q-mb-sm"):
                ui.switch("Chỉ website trỏ về từ 2 đối thủ", value=state["multi"],
                          on_change=lambda e: (state.update(multi=e.value), body.refresh())).props("dense")
                if not cl:
                    ui.switch(f"Ẩn website điểm spam ≥ {BG.SPAM_HIDE}", value=state["spam"],
                              on_change=lambda e: (state.update(spam=e.value), body.refresh())).props("dense")
                ui.space()
                ui.input(placeholder="Tìm website", value=state["q"],
                         on_change=lambda e: (state.update(q=e.value or ""), body.refresh())).props(
                    "dense outlined clearable debounce=300").classes("sr-kw-q")
            q = state["q"].strip().lower()
            shown = [g for g in items if (not state["multi"] or len(g["rivals"]) >= 2)
                     and (cl or not state["spam"] or (g["spam"] or 0) < BG.SPAM_HIDE) and (not q or q in g["domain"])]
            n2 = sum(1 for g in items if len(g["rivals"]) >= 2)
            ui.label(f"{len(shown)} / {len(items)} website · {n2} website trỏ về từ 2 đối thủ trở lên").classes(
                "text-xs muted q-mb-xs")
            rows = [{"domain": g["domain"], "rank": g["rank"], "n": len(g["rivals"]), "rivals": ", ".join(g["rivals"]),
                     "links": F.n(g["backlinks"]), "spam": g["spam"], "first": _vn(g["first_seen"]) if g["first_seen"]
                     else "–"} for g in shown]
            cols = [{"name": "domain", "label": "Website", "field": "domain", "align": "left", "sortable": True},
                    {"name": "rank", "label": "Uy tín", "field": "rank", "align": "right", "sortable": True},
                    {"name": "n", "label": "Trỏ về đối thủ", "field": "n", "align": "left", "sortable": True},
                    {"name": "links", "label": "Link về đối thủ", "field": "links", "align": "right"}]
            if not cl:
                cols.append({"name": "spam", "label": "Spam", "field": "spam", "align": "right", "sortable": True})
            tbl = ui.table(columns=cols, rows=rows, row_key="domain", pagination=25).classes(
                "w-full sr-kw-tbl").props("flat dense" + (" hide-bottom" if len(rows) <= 25 else ""))
            tbl.add_slot("body-cell-domain", """
                <q-td :props="props"><a :href="'https://' + props.row.domain" target="_blank" rel="noopener"
                  class="sr-bb-link">{{ props.row.domain }}</a></q-td>""")
            tbl.add_slot("body-cell-n", """
                <q-td :props="props"><b class="num">{{ props.row.n }}</b>
                  <span class="sr-bb-sub" style="margin-left:6px">{{ props.row.rivals }}</span></q-td>""")
            ui.label("Uy tín: 0–1000 theo DataForSEO. Chỉ tính link dofollow; mỗi đối thủ lấy tối đa "
                     f"{BG.LIMIT} website uy tín nhất.").classes("text-xs muted q-mt-xs")

    def toggle(i: int, on: bool) -> None:
        (state["pick"].add if on else state["pick"].discard)(i)
        body.refresh()

    def confirm(btn) -> None:
        with connect() as c:
            chosen = [r for r in BG.rivals(c, cfg) if r["id"] in state["pick"]]
        n = len(chosen)
        with ui.dialog() as d, ui.card().style("width:440px; max-width:94vw; border-radius:14px"):
            ui.label("Tìm backlink GAP?").classes("text-lg font-semibold")
            with ui.row().classes("items-start no-wrap gap-2 sr-kr-paid"):
                ui.icon("toll", size="18px")
                ui.label((f"Trừ {PT.cost('backlink_gap', n)} credit" if PT.member(user) else
                          f"Tốn khoảng {BG.estimate(n):.2f} USD dữ liệu".replace(".", ","))
                         + f" ({n} đối thủ × {BG.LIMIT} website).").classes("text-sm")
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")

                async def go():
                    d.close()
                    await run_gap(btn, chosen)
                ui.button("Tìm", icon="travel_explore", on_click=go).props("unelevated no-caps")
        d.on("hide", d.delete)
        d.open()

    async def run_gap(btn, chosen: list[dict]) -> None:
        if not ed:
            return
        entry = PT.take(ui, user, cfg, "backlink_gap", n=len(chosen), detail=f"{len(chosen)} đối thủ")
        if entry is False:
            return
        btn.props("loading")
        logs: list[str] = []

        def work():
            with connect() as c:
                return BG.fetch(c, cfg, chosen, str(user), log=logs.append)
        try:
            res = await run.io_bound(work)
            ui.notify(f"Đã tìm backlink GAP với {res['rivals']} đối thủ" + (f" ({len(logs)} đối thủ lỗi)" if logs
                                                                             else ""),
                      caption=" · ".join(logs)[:300] or None, type="warning" if logs else "positive",
                      position="bottom-right", multi_line=True)
        except Exception as e:  # noqa: BLE001
            PT.give_back(entry)
            ui.notify(f"Chưa tìm được: {str(e)[:200]}", type="negative", position="bottom-right", multi_line=True)
        btn.props(remove="loading")
        body.refresh()

    body()


def _effect_cells(ef: dict | None) -> dict:
    """Ô "trước → sau" của một link đã xây."""
    if not ef:
        return {"eff": "–", "eff_sub": "", "eff_tone": "", "eff_sort": 0}
    st = ef["status"]
    if st == "no_date":
        return {"eff": "Cần ngày đặt", "eff_sub": "để so trước / sau", "eff_tone": "mut", "eff_sort": -999}
    if st == "wait":
        return {"eff": "Chờ đủ số", "eff_sub": f"đo được từ {ef['ready_on']:%d/%m}", "eff_tone": "mut",
                "eff_sort": -998}
    if st == "no_data":
        return {"eff": "Chưa có số", "eff_sub": "trang đích ít hiển thị", "eff_tone": "mut", "eff_sort": -997}
    b, a = ef["before"], ef["after"]
    pos = (f"vị trí {b['pos']:.1f} → {a['pos']:.1f}".replace(".", ",") if b["pos"] and a["pos"] else "")
    clk = f"click/ngày {b['clicks_day']:.1f} → {a['clicks_day']:.1f}".replace(".", ",")
    pc = ef["pos_change"] or 0
    tone = "up" if pc >= 1 or ef["clicks_change"] > 0.5 else ("down" if pc <= -1 else "")
    return {"eff": pos or clk, "eff_sub": clk if pos else "", "eff_tone": tone, "eff_sort": pc}


def built_panel(ui, cfg, connect, user) -> None:
    from nicegui import run
    site = cfg.site_url
    ed = A.can_edit(user)
    cl = A.is_client(user)  # khách hàng: không xem chi phí

    @ui.refreshable
    def body() -> None:
        from . import keywords as K
        with connect() as c:
            rows = BB.links(c, site)
            end = K.latest_date(c, site)
            effects = {r["id"]: BB.effect(c, site, r, end) for r in rows}
            by_src = BB.effects_by_source(c, site, rows, end) if rows else []
        sm = BB.summary(rows)
        with T.section(ui, "Link đã xây", "add_link",
                       "Link team đã đặt / mua. Tool tự tải trang đặt link mỗi tuần để kiểm tra link còn, dofollow và "
                       "đúng anchor; link mất hay bị đổi sẽ báo ở chuông thông báo"):
            with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
                if rows:
                    ui.html(f'<span class="sr-bb-sum"><b>{sm["alive"]}</b>/{sm["total"]} link còn</span>')
                    if sm["by"]["lost"]:
                        ui.html(f'<span class="sr-bb-sum bad"><b>{sm["by"]["lost"]}</b> mất</span>')
                    ch = sm["by"]["nofollow"] + sm["by"]["anchor"]
                    if ch:
                        ui.html(f'<span class="sr-bb-sum warn"><b>{ch}</b> bị đổi</span>')
                    if not cl and sm["cost"]:
                        ui.html(f'<span class="sr-bb-sum">Chi phí <b>{F.n(sm["cost"])}</b> đ</span>')
                ui.space()
                if ed and rows:
                    btn = ui.button("Kiểm tra lại tất cả", icon="radar", on_click=lambda: check_all(btn)).props(
                        "flat no-caps dense color=grey-8")
                if ed:
                    ui.button("Thêm link", icon="add", on_click=add_dialog).props("unelevated no-caps")
            if not rows:
                ui.label("Chưa có link nào. Bấm “Thêm link” để ghi các link team đã đặt / mua." if ed else
                         "Chưa có link nào.").classes("text-sm muted")
                return
            data = []
            for r in rows:
                lab, tone = BB.STATES.get(r["state"], ("–", "grey"))
                data.append({"id": r["id"], "from": r["url_from"], "from_host": urlparse(r["url_from"]).netloc,
                             "from_path": _path(r["url_from"]), "to": r["url_to"], "to_path": _path(r["url_to"]),
                             "anchor": r["anchor"] or "", "placed": _vn(r["placed_on"]) if r["placed_on"] else "–",
                             "cost": F.n(r["cost"]) if r["cost"] else "–", "state": lab, "tone": tone,
                             "detail": r["detail"] or "", "checked": _vn(r["checked_at"]) if r["checked_at"] else "chưa",
                             "rank": {"lost": 0, "error": 1, "nofollow": 2, "anchor": 3, "pending": 4, "ok": 5}.get(
                                 r["state"], 9), **_effect_cells(effects.get(r["id"]))})
            data.sort(key=lambda x: x["rank"])
            cols = [{"name": "from", "label": "Trang đặt link", "field": "from_host", "align": "left",
                     "sortable": True},
                    {"name": "to", "label": "Trang đích · anchor", "field": "to_path", "align": "left"},
                    {"name": "placed", "label": "Ngày đặt", "field": "placed", "align": "left"}]
            if not cl:
                cols.append({"name": "cost", "label": "Chi phí", "field": "cost", "align": "right"})
            cols += [{"name": "state", "label": "Tình trạng", "field": "rank", "align": "left", "sortable": True},
                     {"name": "eff", "label": "Trang đích trước → sau", "field": "eff_sort", "align": "left",
                      "sortable": True}]
            if ed:
                cols.append({"name": "act", "label": "", "field": "id", "align": "right"})
            tbl = ui.table(columns=cols, rows=data, row_key="id", pagination=20).classes("w-full sr-kw-tbl").props(
                "flat dense" + (" hide-bottom" if len(data) <= 20 else ""))
            tbl.add_slot("body-cell-from", """
                <q-td :props="props"><a :href="props.row.from" target="_blank" rel="noopener" class="sr-bb-link">
                  {{ props.row.from_host }}</a><div class="sr-bb-sub ellipsis" :title="props.row.from">
                  {{ props.row.from_path }}</div></q-td>""")
            tbl.add_slot("body-cell-to", """
                <q-td :props="props"><a :href="'/url?u=' + encodeURIComponent(props.row.to)" class="sr-bb-link ellipsis"
                  :title="'Mở chi tiết URL: ' + props.row.to">{{ props.row.to_path }}</a>
                  <div v-if="props.row.anchor" class="sr-bb-sub">“{{ props.row.anchor }}”</div></q-td>""")
            tbl.add_slot("body-cell-state", """
                <q-td :props="props"><span class="sr-bb-st" :class="props.row.tone">{{ props.row.state }}</span>
                  <div class="sr-bb-sub" :title="props.row.detail">kiểm tra {{ props.row.checked }}</div>
                  <q-tooltip v-if="props.row.detail">{{ props.row.detail }}</q-tooltip></q-td>""")
            tbl.add_slot("body-cell-eff", """
                <q-td :props="props"><span :class="'sr-bb-eff ' + props.row.eff_tone">{{ props.row.eff }}</span>
                  <div v-if="props.row.eff_sub" class="sr-bb-sub">{{ props.row.eff_sub }}</div></q-td>""")
            if ed:
                tbl.add_slot("body-cell-act", """
                    <q-td :props="props">
                      <q-btn flat round dense size="sm" icon="radar" color="grey-7" aria-label="Kiểm tra lại"
                        @click="$parent.$emit('check', props.row.id)"><q-tooltip>Kiểm tra lại</q-tooltip></q-btn>
                      <q-btn flat round dense size="sm" icon="delete_outline" color="grey-7" aria-label="Xóa"
                        @click="$parent.$emit('drop', props.row.id)"><q-tooltip>Xóa</q-tooltip></q-btn>
                    </q-td>""")
                tbl.on("check", lambda e: check_one(int(e.args)))
                tbl.on("drop", lambda e: ask_drop(int(e.args)))
            ui.label(f"Trước → sau: vị trí trung bình và click mỗi ngày của trang đích trong {BB.EFFECT_DAYS} ngày "
                     "trước và sau ngày đặt link (Search Console). Là số của cả trang, có thể do nhiều nguyên nhân chứ "
                     "không riêng link này.").classes("text-xs muted q-mt-xs")
        measured = [g for g in by_src if g["measured"]]
        if measured:
            with T.section(ui, "Hiệu quả theo nguồn link", "insights",
                           "Trung bình các link đã đủ ngày đo của từng website: để biết nguồn nào đáng tiền"):
                cols2 = [{"name": "host", "label": "Website", "field": "host", "align": "left"},
                         {"name": "links", "label": "Link", "field": "links", "align": "right"},
                         {"name": "pos", "label": "Vị trí tăng TB", "field": "pos_t", "align": "right"},
                         {"name": "clicks", "label": "Click tăng / tháng", "field": "clicks_t", "align": "right"}]
                if not cl:
                    cols2 += [{"name": "cost", "label": "Chi phí", "field": "cost_t", "align": "right"},
                              {"name": "cpc", "label": "Chi phí / click tăng", "field": "cpc_t", "align": "right"}]
                data2 = [{"host": g["host"], "links": f"{g['measured']}/{g['links']}",
                          "pos_t": f"{g['pos']:+.1f}".replace(".", ","),
                          "clicks_t": f"{g['clicks']:+,.0f}".replace(",", "."),
                          "cost_t": F.n(g["cost"]) if g["cost"] else "–",
                          "cpc_t": F.n(g["cost_per_click"]) if g.get("cost_per_click") else "–"} for g in measured]
                ui.table(columns=cols2, rows=data2, row_key="host").classes("w-full sr-kw-tbl").props(
                    "flat dense hide-bottom")
                ui.label("Vị trí tăng: số dương là lên hạng. Link: số link đã đủ ngày đo / tổng link của website."
                         ).classes("text-xs muted q-mt-xs")

    async def check_one(lid: int) -> None:
        def work():
            with connect() as c:
                r = next((x for x in BB.links(c, site) if x["id"] == lid), None)
                if r:
                    BB.save_check(c, lid, BB.check_link(r["url_from"], r["url_to"], r["anchor"]))
        ui.notify("Đang kiểm tra link…", position="bottom-right")
        await run.io_bound(work)
        _forget()
        body.refresh()

    async def check_all(btn) -> None:
        btn.props("loading")

        def work():
            with connect() as c:
                return BB.check_due(c, site, every_days=0, limit=500)
        try:
            n = await run.io_bound(work)
            ui.notify(f"Đã kiểm tra {n} link", type="positive", position="bottom-right")
        finally:
            btn.props(remove="loading")
        _forget()
        body.refresh()

    def ask_drop(lid: int) -> None:
        with ui.dialog() as d, ui.card().style("width:420px; max-width:94vw; border-radius:14px"):
            ui.label("Xóa link này khỏi danh sách?").classes("text-lg font-semibold")
            ui.label("Chỉ xóa khỏi danh sách theo dõi của tool, không ảnh hưởng link trên website kia.").classes(
                "text-sm muted")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")

                def go():
                    with connect() as c:
                        BB.delete_link(c, site, lid)
                    d.close()
                    _forget()
                    body.refresh()
                ui.button("Xóa", on_click=go).props("unelevated no-caps color=red-8")
        d.on("hide", d.delete)
        d.open()

    def add_dialog() -> None:
        with ui.dialog() as d, ui.card().classes("sr-ar-dlg q-pa-none").style("width:640px"):
            with ui.row().classes("w-full items-center no-wrap gap-2 sr-ar-head"):
                ui.icon("add_link", size="20px").style("color:#1E7C31")
                with ui.column().classes("gap-0 col"):
                    ui.label("Thêm link đã xây").classes("sr-br-h")
                    ui.label("Tool kiểm tra ngay sau khi thêm, rồi tự kiểm tra lại mỗi tuần").classes("sr-br-sub")
                ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
            with ui.column().classes("w-full gap-2 sr-ar-body"):
                mode = ui.toggle({"one": "Một link", "many": "Dán nhiều link"}, value="one").props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                    "sr-seg")
                one = ui.column().classes("w-full gap-2")
                with one:
                    uf = ui.input("Trang đặt link", placeholder="https://bao-x.vn/bai-viet…").props(
                        "outlined dense").classes("w-full")
                    with connect() as c:
                        seo = BB.seo_urls(c, site)
                    opts = {r["url"]: f"{_path(r['url'])}  ·  {', '.join(r['groups'])}" for r in seo}
                    ut = ui.select(opts, label="Trang đích trên website (chọn URL SEO hoặc dán URL khác)",
                                   with_input=True, new_value_mode="add-unique", clearable=True).props(
                        "outlined dense options-dense input-debounce=0 hide-dropdown-icon=false").classes("w-full")
                    with ui.row().classes("w-full gap-2 no-wrap"):
                        an = ui.input("Anchor (nếu cần kiểm tra)").props("outlined dense").classes("col")
                        pd = ui.input("Ngày đặt", placeholder="dd/mm/yyyy").props(
                            'outlined dense mask="##/##/####"').style("width:140px")
                        co = ui.input("Chi phí (đ)").props("outlined dense").style("width:140px")
                        co.set_visibility(not cl)
                many = ui.column().classes("w-full gap-1")
                with many:
                    ui.label("Mỗi dòng một link: trang đặt link | trang đích | anchor | ngày đặt | chi phí "
                             "(chỉ 2 cột đầu bắt buộc)").classes("text-xs muted")
                    bulk = ui.textarea(placeholder="https://bao-x.vn/bai | https://website.vn/trang | kính cận | "
                                                   "05/11/2026 | 1.500.000").props(
                        "outlined autogrow input-style='min-height:140px'").classes("w-full")
                many.set_visibility(False)
                mode.on_value_change(lambda e: (one.set_visibility(e.value == "one"),
                                                many.set_visibility(e.value == "many")))
            with ui.row().classes("w-full justify-end gap-2 sr-ar-foot"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")

                async def save():
                    rows = (BB.parse_rows(bulk.value) if mode.value == "many" else
                            [{"url_from": uf.value, "url_to": ut.value, "anchor": an.value, "placed_on": pd.value,
                              "cost": co.value}])
                    with connect() as c:
                        res = BB.add_links(c, site, rows, str(user))
                    if res["bad"]:
                        ui.notify(("Đã thêm " + str(res["added"]) + " link; " if res["added"] else "")
                                  + f"{len(res['bad'])} dòng chưa thêm: " + "; ".join(res["bad"][:3]),
                                  type="warning", multi_line=True, timeout=8000)
                    if not res["added"]:
                        return
                    d.close()
                    ui.notify(f"Đã thêm {res['added']} link, đang kiểm tra…", type="positive", position="bottom-right")
                    body.refresh()

                    def work():
                        with connect() as c:
                            BB.check_due(c, site, limit=res["added"])
                    await run.io_bound(work)
                    _forget()
                    body.refresh()
                ui.button("Thêm", icon="check", on_click=save).props("unelevated no-caps")
        d.on("hide", d.delete)
        d.open()

    def _forget() -> None:
        from . import notices as N
        N.forget()

    body()
