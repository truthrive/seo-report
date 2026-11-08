"""Trang Research từ khóa (/research, nhóm SEO, chỉ team): ý tưởng từ khóa của Google Keyword Planner (Google Ads API,
miễn phí) từ từ khóa gốc, một trang hoặc cả website (của mình / đối thủ); đối chiếu Search Console và danh sách theo
dõi hạng; thêm từ khóa đã chọn vào bộ theo dõi hạng (lúc đó mới tốn tiền check rank); xuất Excel."""
import io
from datetime import datetime

from . import access as A
from . import keyword_research as KR
from . import keywords as K
from . import ui_theme as T

COMP = {"LOW": ("Thấp", "k-new"), "MEDIUM": ("Vừa", "k-kw"), "HIGH": ("Cao", "k-lost")}
HINT = {"keywords": "Mỗi dòng (hoặc cách nhau dấu phẩy) một từ khóa, tối đa 20. Ví dụ: gọng kính cận, tròng kính "
                    "chống ánh sáng xanh",
        "url": "Địa chỉ một trang (của mình hoặc đối thủ): Google gợi ý từ khóa theo nội dung trang đó.",
        "site": "Tên miền (của mình hoặc đối thủ), ví dụ doithu.vn: Google gợi ý từ khóa theo cả website."}


def build_research_page(ui, cfg, connect, user, open_id: int | None = None) -> None:
    from nicegui import run
    site = cfg.site_url
    ed = A.can_edit(user)
    T.page_header(ui, "manage_search", "Research từ khóa",
                  "Ý tưởng từ khóa từ Google Keyword Planner (Google Ads API, miễn phí): volume, xu hướng 12 tháng, "
                  "cạnh tranh, giá thầu; đối chiếu với Search Console để thấy từ khóa site chưa có hạng.")
    state = {"mode": "keywords", "seed": "", "rec": None, "q": "", "gsc": "all", "brand": True, "min": 0,
             "busy": False}
    with connect() as c:
        if open_id:
            state["rec"] = KR.get(c, cfg, open_id)
        from . import aio
        rivals = [b for b in aio.brands(c, cfg) if not b["own"] and b["domains"]]

    async def go(btn=None) -> None:
        if not ed or state["busy"]:
            return
        try:
            KR.parse_seed(state["mode"], state["seed"])
        except ValueError as ex:
            ui.notify(str(ex), type="warning")
            return
        state["busy"] = True
        if btn:
            btn.props("loading")
        from contextlib import closing

        from . import db

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                return KR.research(c, cfg, state["mode"], state["seed"], str(user))
        try:
            state["rec"] = await run.io_bound(work)
            ui.run_javascript(f"history.replaceState(null, '', '/research?id={state['rec']['id']}')")
        except Exception as ex:  # noqa: BLE001
            ui.notify(str(ex), type="warning", multi_line=True)
        finally:
            state["busy"] = False
            if btn:
                btn.props(remove="loading")
        side.refresh()
        results.refresh()

    def open_rec(rid: int) -> None:
        with connect() as c:
            state["rec"] = KR.get(c, cfg, rid)
        ui.run_javascript(f"history.replaceState(null, '', '/research?id={rid}')")
        side.refresh()
        results.refresh()

    def drop_rec(rid: int) -> None:
        with connect() as c:
            KR.delete(c, rid)
        if state["rec"] and state["rec"]["id"] == rid:
            state["rec"] = None
            results.refresh()
        side.refresh()

    def set_mode(m: str) -> None:
        state["mode"] = m
        form.refresh()

    def fill_site(host: str) -> None:
        state["mode"], state["seed"] = "site", host
        form.refresh()

    with ui.element("div").classes("sr-kr-top"):
        with ui.element("div").classes("sr-card q-pa-md"):
            @ui.refreshable
            def form() -> None:
                ui.toggle(KR.MODES, value=state["mode"], on_change=lambda e: set_mode(e.value)).props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                    "sr-seg q-mb-sm")
                if state["mode"] == "keywords":
                    inp = ui.textarea(placeholder="gọng kính cận\ntròng kính đổi màu", value=state["seed"]).props(
                        "outlined dense autogrow").classes("w-full")
                else:
                    inp = ui.input(placeholder="https://…" if state["mode"] == "url" else "doithu.vn",
                                   value=state["seed"]).props("outlined dense").classes("w-full")
                inp.props('aria-label="Nhập từ khóa / URL / website"')
                inp.on_value_change(lambda e: state.update(seed=e.value or ""))
                ui.label(HINT[state["mode"]]).classes("text-xs muted q-mt-xs")
                if state["mode"] == "site":
                    with ui.row().classes("gap-1 q-mt-xs items-center"):
                        from .projects import domain
                        own = domain(site)
                        ui.button(own, on_click=lambda h=own: fill_site(h)).props(
                            "outline dense no-caps size=sm rounded")
                        for b in rivals[:10]:
                            ui.button(b["name"], on_click=lambda h=b["domains"][0]: fill_site(h)).props(
                                "flat dense no-caps size=sm rounded color=grey-8").tooltip(b["domains"][0])
                with ui.row().classes("w-full justify-end q-mt-sm"):
                    if ed:
                        b = ui.button("Tìm ý tưởng", icon="search").props("unelevated no-caps")
                        b.on_click(lambda: go(b))
                    else:
                        ui.label("Chỉ người có quyền sửa chạy research; bạn mở được các lần đã tìm.").classes(
                            "text-xs muted")
            form()

        with ui.element("div").classes("sr-card q-pa-md sr-kr-hist"):
            @ui.refreshable
            def side() -> None:
                ui.label("Đã tìm gần đây").classes("text-sm font-semibold q-mb-xs")
                with connect() as c:
                    hist = KR.history(c)
                if not hist:
                    ui.label("Chưa có.").classes("text-sm muted")
                for h in hist[:12]:
                    on = state["rec"] and state["rec"]["id"] == h["id"]
                    with ui.row().classes("w-full items-center no-wrap gap-1 sr-kr-hrow" + (" on" if on else "")):
                        with ui.column().classes("gap-0 col cursor-pointer").style("min-width:0") as col:
                            ui.label(h["seed"].replace("\n", ", ")).classes("text-sm ellipsis")
                            ui.label(f"{KR.MODES[h['mode']]} · {h['n']} ý tưởng · "
                                     f"{datetime.fromisoformat(h['at']).astimezone():%d/%m %H:%M}").classes(
                                "text-xs muted")
                        col.on("click", lambda i=h["id"]: open_rec(i))
                        if ed:
                            ui.button(icon="close", on_click=lambda i=h["id"]: drop_rec(i)).props(
                                'flat round dense size=xs color=grey-7 aria-label="Xóa lần tìm"')
            side()

    def shown_rows() -> list[dict]:
        rows = state["rec"]["rows"]
        q = K.fold(state["q"]) if state["q"] else ""
        return [r for r in rows
                if (not q or q in K.fold(r["keyword"]))
                and (state["gsc"] == "all" or (state["gsc"] == "none") == (not r["gsc_impr"]))
                and (not state["brand"] or not r["brand"])
                and (r["volume"] or 0) >= state["min"]]

    def export() -> None:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        rows = shown_rows()
        wb = Workbook()
        ws = wb.active
        ws.title = "Research"
        months = rows[0]["monthly"] if rows and rows[0]["monthly"] else []
        head = ["Từ khóa", "Volume/tháng", "Cạnh tranh", "Chỉ số cạnh tranh", f"CPC ({state['rec']['currency']})",
                "Giá thầu thấp", "Giá thầu cao", "Vị trí site (28 ngày)", "Click site", "Hiển thị site", "Trang site",
                "Đang theo dõi hạng"] + [m for m, _ in months]
        ws.append(head)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            mm = dict(r["monthly"])
            ws.append([r["keyword"], r["volume"], COMP.get(r["competition"], ("",))[0], r["competition_index"],
                       r["cpc"], r["low_bid"], r["high_bid"], r["gsc_pos"], r["gsc_clicks"], r["gsc_impr"],
                       r["gsc_page"], "Có" if r["tracked"] else ""] + [mm.get(m) for m, _ in months])
        ws.freeze_panes = "B2"
        ws.column_dimensions["A"].width = 40
        buf = io.BytesIO()
        wb.save(buf)
        ui.download(buf.getvalue(), f"research-tu-khoa-{state['rec']['id']}.xlsx")

    def add_dialog(selected: list[dict]) -> None:
        from . import rank as R
        kws = [r["keyword"] for r in selected]
        with connect() as c:
            sets = [s for s in R.sets(c, site) if s.get("kind") != "kpi"]
        if not sets:
            ui.notify("Chưa có bộ từ khóa nào do team tạo: tạo bộ ở trang Từ khóa & Thứ hạng trước", type="warning")
            return
        with ui.dialog() as d, ui.card().style("min-width: 480px; max-width: 94vw; border-radius: 14px"):
            ui.label(f"Thêm {len(kws)} từ khóa vào bộ theo dõi hạng").classes("text-lg font-semibold")
            sel = ui.select({s["id"]: s["name"] + (" (Nháp)" if s.get("draft") else "") for s in sets},
                            value=sets[0]["id"], label="Bộ từ khóa").props("outlined dense").classes("w-full")
            est = ui.label().classes("text-sm muted")

            def update_est():
                with connect() as c:
                    e = R.estimate_add(c, site, cfg.rank, K.latest_date(c, site), kws, sel.value)
                est.text = (f"{e['new']} từ khóa mới ({e['existing']} đã có trong bộ). Check hạng tốn thêm khoảng "
                            f"{R.usd(e['monthly_add'])} USD/tháng theo lịch của bộ; cả tháng dự kiến "
                            f"{R.usd(e['monthly_total'])}/{e['budget']:.0f} USD. Bộ Nháp chưa tốn tiền đến khi Chốt.")
            sel.on_value_change(lambda _: update_est())
            update_est()

            def do_add():
                with connect() as c:
                    res = R.add_keywords(c, site, cfg.rank, K.latest_date(c, site), [(k, None) for k in kws],
                                         str(user), set_id=sel.value)
                msg = f"Đã thêm {len(res['added'])} từ khóa"
                if res["over_budget"]:
                    msg += f", {len(res['over_budget'])} từ khóa vượt ngân sách chưa thêm"
                ui.notify(msg, type="positive" if res["added"] else "warning")
                d.close()
                with connect() as c:
                    state["rec"] = KR.get(c, cfg, state["rec"]["id"])
                results.refresh()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Thêm vào bộ", icon="add", on_click=do_add).props("unelevated no-caps")
        d.open()

    @ui.refreshable
    def table() -> None:
        rows = shown_rows()
        rec = state["rec"]
        if not rows:
            T.empty_state(ui, "search_off", "Không có từ khóa nào khớp bộ lọc")
            return
        vol = sum(r["volume"] or 0 for r in rows)
        no_rank = sum(1 for r in rows if not r["gsc_impr"])
        ui.label(f"{len(rows):,} từ khóa · tổng {vol:,} lượt tìm / tháng · {no_rank:,} từ khóa site chưa có hạng"
                 .replace(",", ".")).classes("text-sm muted q-mb-xs")
        data = []
        for i, r in enumerate(rows):
            mx = max((n for _, n in r["monthly"]), default=0) or 1
            data.append({"id": i, "keyword": r["keyword"], "volume": r["volume"], "cpc": r["cpc"],
                         "comp": COMP.get(r["competition"], ("–", ""))[0], "comp_cls": COMP.get(r["competition"],
                                                                                              ("", ""))[1],
                         "comp_i": r["competition_index"], "tracked": r["tracked"], "brand": r["brand"],
                         "pos": r["gsc_pos"], "clicks": r["gsc_clicks"], "impr": r["gsc_impr"],
                         "page": (r["gsc_page"] or "").replace(site.rstrip("/"), "") or None,
                         "page_url": r["gsc_page"],
                         "bars": [{"m": f"{m[5:]}/{m[2:4]}", "n": n, "h": max(2, round(22 * n / mx))}
                                  for m, n in r["monthly"]]})
        cur = rec["currency"]
        fmt_money = ("v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN', {maximumFractionDigits: "
                     + ("0" if cur == "VND" else "2") + "})")
        tb = ui.table(columns=[
            {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left"},
            {"name": "volume", "label": "Volume / tháng", "field": "volume", "align": "right",
             ":format": "v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN')"},
            {"name": "trend", "label": "12 tháng", "field": "volume", "align": "left", "sortable": False},
            {"name": "comp", "label": "Cạnh tranh", "field": "comp_i", "align": "left"},
            {"name": "cpc", "label": f"CPC ({cur})", "field": "cpc", "align": "right", ":format": fmt_money},
            {"name": "site", "label": "Site hiện tại (28 ngày)", "field": "pos", "align": "left"},
        ], rows=data, row_key="id", pagination=25,
            selection="multiple" if ed else None).props("flat dense binary-state-sort").classes(
            "w-full sr-bl-table")
        tb.add_slot("body-cell-keyword", """
            <q-td :props="props"><div class="sr-op-kw">{{ props.value }}
              <span v-if="props.row.tracked" class="sr-bl-type k-url q-ml-xs">đang theo dõi hạng</span>
              <span v-if="props.row.brand" class="sr-bl-type q-ml-xs">thương hiệu</span></div></q-td>""")
        tb.add_slot("body-cell-trend", """
            <q-td :props="props"><div class="sr-kr-spark" v-if="props.row.bars.length">
              <div v-for="b in props.row.bars" :key="b.m" class="sr-kr-bar" :style="{height: b.h + 'px'}"></div>
              <q-tooltip><div v-for="b in props.row.bars" :key="b.m">{{ b.m }}: {{ b.n.toLocaleString('vi-VN') }}
              </div></q-tooltip></div><span v-else class="muted">–</span></q-td>""")
        tb.add_slot("body-cell-comp", """
            <q-td :props="props"><span v-if="props.row.comp_cls" class="sr-bl-type" :class="props.row.comp_cls">{{
              props.row.comp }}<q-tooltip>Mức cạnh tranh quảng cáo (0–100): {{ props.value }}</q-tooltip></span>
              <span v-else class="muted">–</span></q-td>""")
        tb.add_slot("body-cell-site", """
            <q-td :props="props"><template v-if="props.row.impr">
              <span class="num"><b>vị trí {{ props.value.toLocaleString('vi-VN') }}</b> ·
                {{ props.row.clicks.toLocaleString('vi-VN') }} click</span>
              <div class="sr-bl-sub"><a :href="props.row.page_url" target="_blank" rel="noopener"
                class="sr-bl-link" style="font-weight:400">{{ props.row.page }}</a></div></template>
              <span v-else class="sr-bl-type k-kw">chưa có hạng</span></q-td>""")
        if ed:
            with ui.row().classes("w-full items-center gap-2 q-mt-sm"):
                lab = ui.label("Chọn từ khóa (ô vuông đầu dòng) để thêm vào bộ theo dõi hạng.").classes(
                    "text-sm muted col")
                add_btn = ui.button("Thêm vào bộ theo dõi hạng", icon="playlist_add").props(
                    "unelevated no-caps disable")

                def picked(_=None):
                    n = len(tb.selected)
                    lab.text = f"Đã chọn {n} từ khóa." if n else "Chọn từ khóa (ô vuông đầu dòng) để thêm vào bộ " \
                                                               "theo dõi hạng."
                    add_btn.props(remove="disable") if n else add_btn.props("disable")
                tb.on_select(picked)
                add_btn.on_click(lambda: add_dialog([rows[s["id"]] for s in tb.selected]))

    @ui.refreshable
    def results() -> None:
        rec = state["rec"]
        if not rec:
            T.empty_state(ui, "manage_search", "Chưa chọn lần research nào",
                          "Nhập từ khóa gốc, một trang, hoặc website đối thủ rồi bấm Tìm ý tưởng.")
            return
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label(rec["seed"].replace("\n", ", ")).classes("text-base font-semibold ellipsis")
                ui.label(f"{KR.MODES[rec['mode']]} · {len(rec['rows'])} ý tưởng · "
                         f"{datetime.fromisoformat(rec['at']).astimezone():%H:%M %d/%m/%Y} · "
                         f"{rec['by'].split('@')[0]}").classes("text-xs muted")
            ui.button("Xuất Excel", icon="download", on_click=export).props("outline no-caps")
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            ui.toggle({"all": "Tất cả", "none": "Site chưa có hạng", "has": "Site đã có hạng"}, value=state["gsc"],
                      on_change=lambda e: (state.update(gsc=e.value), table.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
            ui.select({0: "Mọi volume", 50: "Từ 50", 100: "Từ 100", 500: "Từ 500", 1000: "Từ 1.000"},
                      value=state["min"], on_change=lambda e: (state.update(min=e.value), table.refresh())).props(
                "outlined dense options-dense").classes("sr-kr-min").props('aria-label="Volume tối thiểu"')
            ui.checkbox("Bỏ từ khóa thương hiệu", value=state["brand"],
                        on_change=lambda e: (state.update(brand=e.value), table.refresh())).props("dense")
            ui.space()
            ui.input(placeholder="Lọc từ khóa", value=state["q"],
                     on_change=lambda e: (state.update(q=e.value or ""), table.refresh())).props(
                "outlined dense clearable debounce=300").classes("sr-op-search").props('aria-label="Lọc từ khóa"')
        table()

    results()
