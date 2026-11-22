"""Trang Cơ hội SEO (/co-hoi, nhóm SEO): 4 tab việc nên làm rút từ dữ liệu Search Console đã lưu (opportunities.py).
Không gọi API, không tốn tiền. Team xem (người sửa và người chỉ xem); khách hàng không thấy."""
from datetime import date

from . import points as PT
from . import access as A
from . import ai_page_gap as PG
from . import ai_settings as AIS
from . import web_page_gap as WPG
from . import brand_entity as BE
from . import keywords as K
from . import opportunities as O
from . import seo_value as SVL
from . import ui_theme as T

# trang của team: giữ tên thuật ngữ SEO tiếng Anh quen dùng
TABS = (("du-bao", "Keyword Forecast"), ("len-top", "Striking Distance"),
        ("giam", "Traffic Drops"), ("tranh", "Keyword Cannibalization"), ("moi", "New Pages"),
        ("thuc-the", "Brand Entity"))
NUM = "v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN')"
POS = "v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN', {maximumFractionDigits: 1})"
TAB_ICON = {"du-bao": "query_stats", "len-top": "trending_up", "giam": "trending_down",
            "tranh": "call_split", "moi": "fiber_new", "thuc-the": "hub"}
CAUSES = {"rank": ("Rớt hạng", "k-lost"), "demand": ("Ít người tìm hơn", "k-kw"), "ctr": ("CTR giảm", "k-url"),
          "mixed": ("Giảm chung", "")}
NEW_CAP = 3000  # tab Trang mới, chế độ Tất cả: chỉ gửi bấy nhiêu dòng mới nhất (site bán hàng có hàng nghìn sản phẩm)


def _path(url: str, site: str) -> str:
    return url.replace(site.rstrip("/"), "") or "/"


def _d(d: date | None) -> str:
    return f"{d:%d/%m/%Y}" if d else "–"


def build_opps_page(ui, cfg, connect, user, start: str = "") -> None:
    from nicegui import background_tasks, run
    site = cfg.site_url
    with connect() as c:
        end = K.latest_date(c, site)
    cur, prev = O.window(end), O.window(end, back=1)
    T.page_header(ui, "insights", "SEO Opportunities",
                  f"Việc nên làm để tăng traffic, tính từ Search Console 28 ngày gần nhất ({cur[0]:%d/%m} – {cur[1]:%d/%m/%Y}).")
    ed = A.can_edit(user)
    can_gap = ed and AIS.enabled(site, PG.TASK)
    state = {"tab": start if start in dict(TABS) else TABS[0][0], "data": None, "strike": "all", "new": "signal",
             "q": ""}

    def pick(v: str) -> None:
        if v == state["tab"]:
            return
        state["tab"] = v
        ui.run_javascript(f"history.replaceState(null, '', '/co-hoi' + ('{v}' === '{TABS[0][0]}' ? '' : '?tab={v}'))")
        cards.refresh()
        panel.refresh()

    def _n(v) -> str:
        return f"{v:,.0f}".replace(",", ".")

    def summary(data: dict) -> dict[str, tuple[int, str, str]]:
        """Mỗi thẻ: (số chính, dòng phụ, tông: bad/warn/good/neutral)."""
        fc = data["forecast"]
        st = data["striking"]
        dc = data["decay"]
        serious = sum(1 for g in data["cannibal"] if g["serious"])
        new_sig = sum(1 for r in data["new"] if r["impressions"] >= O.NEW_SIGNAL)
        kg_bad = sum(1 for c in data["kg"]["checks"] if c["ok"] is False)
        return {
            "du-bao": (len(fc["rows"]), f"+{_n(fc['gain'])} click / tháng nếu lên top {fc['target']}"
                       if fc["rows"] else "từ khóa chưa vào top 3", "neutral"),
            "len-top": (len(st), f"+{_n(sum(r['potential'] for r in st))} click / 28 ngày" if st
                        else "từ khóa vị trí 4–15", "neutral"),
            "giam": (len(dc), f"−{_n(sum(r['lost'] for r in dc))} click so với 28 ngày trước" if dc
                     else "không trang nào tụt", "warn" if dc else "good"),
            "tranh": (serious, "từ khóa nên xử lý" + (f" / {len(data['cannibal'])}" if data["cannibal"] else ""),
                      "warn" if serious else "good"),
            "moi": (new_sig, "trang mới đã có tín hiệu", "neutral"),
            "thuc-the": (kg_bad, "việc chưa đạt" if data["kg"]["at"] else "chưa kiểm tra",
                         "warn" if kg_bad else "good" if data["kg"]["at"] else "neutral"),
        }

    @ui.refreshable
    def cards() -> None:
        sm = summary(state["data"])
        with ui.element("div").classes("sr-op-nav").props('role="tablist" aria-label="Loại cơ hội"').style(
                f"--n:{len(TABS)}"):
            for k, name in TABS:
                n, sub, tone = sm[k]
                on = k == state["tab"]
                c = ui.element("div").classes("sr-op-card" + (" on" if on else "")).props(
                    f'role="tab" tabindex="0" aria-selected="{str(on).lower()}"')
                c.on("click", lambda _, k=k: pick(k))
                c.on("keydown.enter", lambda _, k=k: pick(k))
                with c:
                    with ui.row().classes("items-center no-wrap gap-2 w-full"):
                        ui.icon(TAB_ICON[k], size="18px").classes("sr-op-card-ico").props('aria-hidden="true"')
                        ui.label(name).classes("sr-op-card-name col")
                    with ui.row().classes("items-baseline no-wrap gap-2 q-mt-xs"):
                        ui.label(_n(n)).classes(f"sr-op-card-num t-{tone}")
                        if tone == "good" and n == 0:
                            ui.icon("check_circle", size="16px").classes("sr-op-card-ok").props(
                                'aria-label="Ổn"')
                    ui.label(sub).classes("sr-op-card-sub")

    @ui.refreshable
    def panel() -> None:
        data = state["data"]
        with ui.element("div").classes("sr-card sr-op-panel w-full"):
            {"len-top": lambda: striking_tab(data["striking"]), "giam": lambda: decay_tab(data["decay"]),
             "tranh": lambda: cannibal_tab(data["cannibal"]), "moi": lambda: new_tab(data["new"]),
             "du-bao": lambda: forecast_tab(data["forecast"]),
             "thuc-the": lambda: kg_tab(data["kg"])}[state["tab"]]()

    @ui.refreshable
    def body() -> None:
        data = state["data"]
        if data is None:
            with ui.element("div").classes("w-full sr-busy").props('aria-busy="true" aria-label="Đang tính"'):
                with ui.element("div").classes("sr-op-nav"):
                    for _ in TABS:
                        T.bone(ui, "96px", radius="12px")
                T.bone(ui, "420px", radius="14px")
            return
        cards()
        panel()

    def explain(title: str, lines: list[str], extra=None) -> None:
        """Đầu tab: tên tab + một câu mô tả; cách đọc / việc nên làm gấp lại, bấm "Cách đọc" để mở. extra: nút thêm
        (ví dụ Xuất) đặt cạnh "Cách đọc"."""
        name = dict(TABS)[state["tab"]]
        with ui.row().classes("w-full items-start no-wrap gap-3 sr-op-head"):
            ui.icon(TAB_ICON[state["tab"]], size="22px").classes("sr-op-head-ico").props('aria-hidden="true"')
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label(name).classes("sr-op-head-title")
                ui.label(title).classes("text-sm muted")
            if extra:
                extra()
            btn = ui.button("Cách đọc", icon="help_outline").props(
                'flat dense no-caps size=sm aria-expanded="false"').classes("sr-op-howbtn")
        box = ui.element("div").classes("sr-op-explain")
        box.set_visibility(False)
        with box:
            for t in lines:
                with ui.row().classes("items-start no-wrap gap-2"):
                    ui.icon("arrow_right", size="18px").classes("muted").props('aria-hidden="true"')
                    ui.label(t).classes("text-sm")

        def toggle():
            box.set_visibility(not box.visible)
            btn.props(f'aria-expanded="{str(box.visible).lower()}"')
        btn.on_click(toggle)

    # ---- Sắp lên top ----
    @ui.refreshable
    def striking_table(rows: list[dict]) -> None:
        shown = [r for r in rows if state["strike"] == "all" or not r["tracked"]]
        q = K.fold(state["q"]) if state["q"] else ""
        if q:
            shown = [r for r in shown if q in K.fold(r["query"]) or q in K.fold(r["url"])]
        if not shown:
            T.empty_state(ui, "search_off", "Không có từ khóa nào khớp")
            return
        top = shown[:20]
        ui.label(f"{len(shown):,} từ khóa".replace(",", ".") +
                 f" · 20 từ khóa đầu nếu lên vị trí 3: khoảng +{sum(r['potential'] for r in top):,} click / 28 ngày"
                 .replace(",", ".")).classes("text-sm muted q-mb-xs")
        columns = [
            {"name": "query", "label": "Từ khóa", "field": "query", "align": "left"},
            {"name": "path", "label": "Trang đang lên", "field": "path", "align": "left"},
            {"name": "position", "label": "Vị trí", "field": "position", "align": "right", ":format": POS},
            {"name": "impressions", "label": "Hiển thị", "field": "impressions", "align": "right", ":format": NUM},
            {"name": "clicks", "label": "Click", "field": "clicks", "align": "right", ":format": NUM},
            {"name": "potential", "label": "Click có thể thêm", "field": "potential", "align": "right"},
        ]
        drafted = WPG.drafted_refs(connect, site) if can_gap else set()
        data = [{**r, "id": i, "path": _path(r["url"], site),
                 "move": None if r["prev_position"] is None else round(r["prev_position"] - r["position"], 1),
                 "ai": PG.ref_of(r["url_id"], r["query"]) in drafted}
                for i, r in enumerate(shown)]
        tb = ui.table(columns=columns, rows=data, row_key="id", pagination=20).props(
            "flat dense binary-state-sort").classes("w-full sr-bl-table")
        # Ô từ khóa hai tầng: dòng 1 = từ khóa + nút AI dạng icon nhỏ bên phải (không thêm cột: bảng không tràn ngang,
        # trên điện thoại nút ở cột đầu); dòng 2 = chữ phụ 12px "Đang theo dõi hạng · 30 trang cùng lên" thay cho chip.
        # Nút AI chỉ có khi người sửa được dự án và tác vụ đang bật.
        gap_btn = """
                <q-btn flat dense size="sm" :icon="props.row.ai ? 'description' : 'auto_fix_high'"
                  :class="props.row.ai ? 'sr-op-ai done' : 'sr-op-ai'"
                  :aria-label="(props.row.ai ? 'Xem bản nháp đoạn còn thiếu: ' : 'AI viết đoạn còn thiếu cho: ')
                    + props.row.query"
                  @click.stop="$parent.$emit('gap', props.row)">
                  <q-tooltip>{{ props.row.ai ? 'Xem bản nháp AI' : 'AI viết đoạn còn thiếu cho trang' }}</q-tooltip>
                </q-btn>""" if can_gap else ""
        if can_gap:
            by_id = {r["id"]: r for r in data}
            tb.on("gap", lambda e: WPG.gap_dialog(ui, connect, cfg, user, by_id[e.args["id"]], end,
                                                  on_saved=lambda: striking_table.refresh(rows)))
        tb.add_slot("body-cell-query", """
            <q-td :props="props"><div class="sr-op-kwrow">
              <div class="sr-op-kwmain">
                <div class="sr-op-kw">{{ props.value }}</div>
                <div v-if="props.row.tracked || props.row.urls > 1" class="sr-bl-sub">
                  <span v-if="props.row.tracked">Theo dõi hạng</span>
                  <span v-if="props.row.tracked && props.row.urls > 1"> · </span>
                  <span v-if="props.row.urls > 1" class="sr-op-help">{{ props.row.urls }} trang cùng lên
                    <q-tooltip>Có {{ props.row.urls }} trang của site cùng nhận lượt hiển thị cho từ khóa này; số liệu
                      là của trang nhận nhiều nhất</q-tooltip></span>
                </div>
              </div>""" + gap_btn + """
            </div></q-td>""")
        tb.add_slot("body-cell-path", """
            <q-td :props="props"><div class="sr-bl-src"><a :href="props.row.url" target="_blank" rel="noopener"
              class="sr-bl-link" :title="props.row.url">{{ props.value }}</a></div></q-td>""")
        tb.add_slot("body-cell-position", """
            <q-td :props="props"><span class="num">{{ props.value.toLocaleString('vi-VN',
              {maximumFractionDigits: 1}) }}</span>
              <span v-if="props.row.move !== null && Math.abs(props.row.move) >= 0.5" class="sr-op-move"
                :class="props.row.move > 0 ? 'up' : 'down'">{{ props.row.move > 0 ? '▲' : '▼' }}{{
                Math.abs(props.row.move).toLocaleString('vi-VN') }}
                <q-tooltip>28 ngày trước: vị trí {{ props.row.prev_position.toLocaleString('vi-VN') }}</q-tooltip>
              </span></q-td>""")
        T.bar_slot(tb, "potential", max(r["potential"] for r in data))

    def striking_tab(rows: list[dict]) -> None:
        explain("Từ khóa đang ở vị trí 4–15, nhiều lượt hiển thị: đẩy lên top 3 là có thêm click nhanh nhất.", [
            "Việc nên làm: bổ sung nội dung trả lời đúng từ khóa, đưa từ khóa vào tiêu đề / H1 / mô tả, thêm link "
            "nội bộ từ các trang mạnh về trang này."
            + (" Nút “Viết đoạn còn thiếu”: AI đọc trang rồi viết nháp phần cần thêm, team sửa và tự đưa lên trang."
               if can_gap else ""),
            f"“Click có thể thêm” ước tính nếu lên vị trí 3 (CTR khoảng {O.CTR_TOP3:.0%}), trên 28 ngày. Từ khóa "
            "thương hiệu không tính."])
        if not rows:
            T.empty_state(ui, "emoji_events", "Không có từ khóa nào ở vị trí 4–15 đủ lượt hiển thị")
            return
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            ui.toggle({"all": "Tất cả", "untracked": "Chưa theo dõi hạng"}, value=state["strike"],
                      on_change=lambda e: (state.update(strike=e.value), striking_table.refresh(rows))).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
            ui.space()
            ui.input(placeholder="Tìm từ khóa / trang", value=state["q"],
                     on_change=lambda e: (state.update(q=e.value or ""), striking_table.refresh(rows))).props(
                "outlined dense clearable debounce=300").classes("sr-op-search").props(
                'aria-label="Tìm từ khóa hoặc trang"')
        striking_table(rows)

    # ---- Trang tụt traffic ----
    def show_lost(row: dict) -> None:
        with connect() as c:
            qs = O.lost_queries(c, row["url_id"], end)
        with ui.dialog() as d, ui.card().style("min-width: 560px; max-width: 94vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                with ui.column().classes("gap-0 col").style("min-width:0"):
                    ui.label("Từ khóa mất click nhiều nhất").classes("text-lg font-semibold")
                    ui.link(_path(row["url"], site), row["url"], new_tab=True).classes("sr-bl-link text-sm")
                ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
            ui.label(row["cause_text"]).classes("text-sm muted")
            if not qs:
                ui.label("Google không cho biết từ khóa (từ khóa ẩn danh).").classes("text-sm muted")
            else:
                ui.table(columns=[
                    {"name": "query", "label": "Từ khóa", "field": "query", "align": "left"},
                    {"name": "clicks", "label": "Click (trước → nay)", "field": "clicks_t", "align": "right"},
                    {"name": "impr", "label": "Hiển thị (trước → nay)", "field": "impr_t", "align": "right"},
                    {"name": "pos", "label": "Vị trí (trước → nay)", "field": "pos_t", "align": "right"},
                ], rows=[{**q, "clicks_t": f"{q['prev_clicks']} → {q['clicks']}",
                          "impr_t": f"{q['prev_impressions']:,} → {q['impressions']:,}".replace(",", "."),
                          "pos_t": f"{_p(q['prev_position'])} → {_p(q['position'])}"} for q in qs],
                    row_key="query").props("flat dense").classes("w-full")
        d.open()

    def decay_tab(rows: list[dict]) -> None:
        explain("Trang mất nhiều click nhất so với 28 ngày trước (giảm từ 30% và mất từ 10 click).", [
            "Bấm một dòng để xem từ khóa nào mất click. “Rớt hạng”: xem lại nội dung, đối thủ mới vượt lên. "
            "“CTR giảm”: viết lại tiêu đề / mô tả, xem có AI Overview mới không. “Ít người tìm hơn”: có thể do "
            "mùa vụ hoặc mất bớt từ khóa phụ.",
            "“Mùa vụ” nghĩa là cùng kỳ năm trước trang này cũng giảm: chưa chắc là lỗi."])
        if not rows:
            T.empty_state(ui, "check_circle", "Không có trang nào tụt traffic đáng kể",
                          "Không trang nào mất từ 30% click so với 28 ngày trước.")
            return
        columns = [
            {"name": "path", "label": "Trang", "field": "path", "align": "left"},
            {"name": "clicks", "label": "Click", "field": "clicks", "align": "right", ":format": NUM},
            {"name": "lost", "label": "Mất", "field": "lost", "align": "right"},
            {"name": "impr", "label": "Hiển thị", "field": "impr_change", "align": "right"},
            {"name": "pos", "label": "Vị trí", "field": "position", "align": "right"},
            {"name": "cause", "label": "Lý do có thể", "field": "cause_label", "align": "left"},
        ]
        data = [{**r, "id": i, "path": _path(r["url"], site), "pct": round(r["change"] * 100),
                 "impr_change": round((r["impressions"] - r["prev_impressions"]) / r["prev_impressions"] * 100)
                 if r["prev_impressions"] else None,
                 "cause_label": CAUSES[r["cause"]][0], "cause_cls": CAUSES[r["cause"]][1]}
                for i, r in enumerate(rows)]
        tb = ui.table(columns=columns, rows=data, row_key="id", pagination=20).props(
            "flat dense binary-state-sort").classes("w-full sr-bl-table sr-op-click")
        tb.add_slot("body-cell-path", """
            <q-td :props="props"><div class="sr-bl-src"><span class="sr-bl-link" :title="props.row.url">{{
              props.value }}</span></div></q-td>""")
        tb.add_slot("body-cell-clicks", """
            <q-td :props="props"><span class="num">{{ props.row.prev_clicks.toLocaleString('vi-VN') }} →
              {{ props.value.toLocaleString('vi-VN') }}</span></q-td>""")
        tb.add_slot("body-cell-lost", """
            <q-td :props="props"><span class="sr-op-move down">−{{ props.value.toLocaleString('vi-VN') }}
              ({{ props.row.pct }}%)</span></q-td>""")
        tb.add_slot("body-cell-impr", """
            <q-td :props="props"><span v-if="props.value === null" class="muted">–</span>
              <span v-else class="sr-op-move" :class="props.value >= 0 ? 'up' : 'down'">{{ props.value > 0 ? '+' :
                '' }}{{ props.value }}%</span></q-td>""")
        tb.add_slot("body-cell-pos", """
            <q-td :props="props"><span class="num">{{ props.row.prev_position === null ? '–' :
              props.row.prev_position.toLocaleString('vi-VN') }} → {{ props.value === null ? '–' :
              props.value.toLocaleString('vi-VN') }}</span></q-td>""")
        tb.add_slot("body-cell-cause", """
            <q-td :props="props"><span class="sr-bl-type" :class="props.row.cause_cls">{{ props.value }}
              <q-tooltip>{{ props.row.cause_text }}</q-tooltip></span>
              <span v-if="props.row.seasonal" class="sr-bl-type k-kw q-ml-xs">mùa vụ
                <q-tooltip>Cùng kỳ năm trước trang này cũng giảm từ 20%</q-tooltip></span></q-td>""")
        tb.on("rowClick", lambda e: show_lost(e.args[1]))

    # ---- Tranh nhau từ khóa ----
    @ui.refreshable
    def cannibal_table(groups: list[dict], serious_only: dict) -> None:
        shown = [g for g in groups if g["serious"] or not serious_only["on"]]
        if not shown:
            T.empty_state(ui, "check_circle", "Không có từ khóa nào bị tranh nhau nặng")
            return
        columns = [
            {"name": "query", "label": "Từ khóa", "field": "query", "align": "left"},
            {"name": "urls", "label": "Các trang cùng lên (phần lượt hiển thị)", "field": "n", "align": "left"},
            {"name": "impressions", "label": "Hiển thị", "field": "impressions", "align": "right", ":format": NUM},
            {"name": "position", "label": "Vị trí trang chính", "field": "position", "align": "right",
             ":format": POS},
        ]
        data = [{"id": i, "query": g["query"], "n": len(g["urls"]), "impressions": g["impressions"],
                 "position": g["position"], "serious": g["serious"],
                 "urls": [{"url": u["url"], "path": _path(u["url"], site), "share": round(u["share"] * 100),
                           "pos": round(u["position"], 1), "clicks": u["clicks"]} for u in g["urls"]]}
                for i, g in enumerate(shown)]
        tb = ui.table(columns=columns, rows=data, row_key="id", pagination=15).props(
            "flat dense binary-state-sort").classes("w-full sr-bl-table")
        tb.add_slot("body-cell-query", """
            <q-td :props="props"><div class="sr-op-kw">{{ props.value }}</div>
              <span v-if="props.row.serious" class="sr-bl-type k-lost q-mt-xs">nên xử lý
                <q-tooltip>Trang chính chưa vào top 3 và trang khác chiếm từ 25% lượt hiển thị</q-tooltip></span>
            </q-td>""")
        tb.add_slot("body-cell-urls", """
            <q-td :props="props"><div class="sr-op-urls">
              <div v-for="(u, i) in props.row.urls" :key="u.url" class="sr-op-url">
                <div class="sr-op-line">
                  <div class="sr-op-share"><div :style="{width: Math.max(3, u.share) + '%'}"
                    :class="i === 0 ? 'main' : ''"></div></div>
                  <span class="num sr-op-pct">{{ u.share }}%</span>
                  <a :href="u.url" target="_blank" rel="noopener" class="sr-bl-link sr-op-path" :title="u.url">{{
                    u.path }}</a>
                  <span v-if="i === 0" class="sr-bl-type k-url">chính<q-tooltip>Trang nhận nhiều click nhất cho từ
                    khóa này: nên giữ làm trang chính</q-tooltip></span>
                </div>
                <div class="sr-op-meta">vị trí {{ u.pos.toLocaleString('vi-VN') }} · {{ u.clicks }} click</div>
              </div></div></q-td>""")

    def cannibal_tab(groups: list[dict]) -> None:
        explain("Nhiều trang của site cùng lên cho một từ khóa: Google không biết trang nào chính, thứ hạng dễ nhảy "
                "qua lại và cả hai cùng yếu.", [
                    "Việc nên làm: chọn một trang chính (thường là trang đứng đầu). Trang còn lại: đổi tiêu đề / nội "
                    "dung cho khác ý định tìm kiếm, hoặc gộp nội dung rồi chuyển hướng 301, và đặt link nội bộ về "
                    "trang chính với anchor là từ khóa.",
                    "Chỉ tính trang có từ 50 lượt hiển thị trong 28 ngày, bỏ từ khóa thương hiệu (giống màn URL)."])
        if not groups:
            T.empty_state(ui, "check_circle", "Không có từ khóa nào bị nhiều trang tranh nhau")
            return
        serious_only = {"on": any(g["serious"] for g in groups)}
        n_serious = sum(1 for g in groups if g["serious"])
        ui.toggle({True: f"Nên xử lý · {n_serious}", False: f"Tất cả · {len(groups)}"}, value=serious_only["on"],
                  on_change=lambda e: (serious_only.update(on=e.value), cannibal_table.refresh(groups,
                                                                                               serious_only))).props(
            "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
            "sr-seg q-mb-sm")
        cannibal_table(groups, serious_only)

    # ---- Trang mới ----
    @ui.refreshable
    def new_table(rows: list[dict]) -> None:
        shown = [r for r in rows if state["new"] == "all" or r["impressions"] >= O.NEW_SIGNAL]
        capped = state["new"] == "all" and len(shown) > NEW_CAP
        shown = shown[:NEW_CAP]
        if not shown:
            T.empty_state(ui, "fiber_new", "Chưa có trang mới nào có tín hiệu",
                          f"Trang mới cần từ {O.NEW_SIGNAL} lượt hiển thị để hiện ở đây; chọn “Tất cả” để xem hết.")
            return
        if capped:
            ui.label(f"Đang hiện {NEW_CAP:,} trang mới nhất.".replace(",", ".")).classes("text-sm muted q-mb-xs")

        def per(r, n):
            p = r["periods"].get(n)
            if not p or not r["first_seen"]:
                return None
            before = {30: 7, 90: 30}.get(n)
            if before and not r["periods"][before]["done"]:
                return None  # kỳ ngắn hơn còn đang chạy: kỳ dài trùng số, để trống cho dễ đọc
            return {"c": p["clicks"], "i": p["impressions"], "pos": p["position"], "done": p["done"]}
        data = [{"id": i, "url": r["url"], "path": _path(r["url"], site),
                 "first": r["first_seen"].isoformat() if r["first_seen"] else "",
                 "first_t": _d(r["first_seen"]), "age": r["age"], "sitemap": _d(r["sitemap"]) if r["sitemap"] else "",
                 "p7": per(r, 7), "p30": per(r, 30), "p90": per(r, 90),
                 "c7": (per(r, 7) or {}).get("c", -1), "c30": (per(r, 30) or {}).get("c", -1),
                 "c90": (per(r, 90) or {}).get("c", -1),
                 "head": r["head"]["query"] if r["head"] else "",
                 "head_pos": r["head"]["position"] if r["head"] else None} for i, r in enumerate(shown)]
        columns = [
            {"name": "path", "label": "Trang", "field": "path", "align": "left"},
            {"name": "first", "label": "Lên Google từ", "field": "first", "align": "left"},
            {"name": "p7", "label": "7 ngày đầu", "field": "c7", "align": "right"},
            {"name": "p30", "label": "30 ngày đầu", "field": "c30", "align": "right"},
            {"name": "p90", "label": "90 ngày đầu", "field": "c90", "align": "right"},
            {"name": "head", "label": "Từ khóa chính (28 ngày)", "field": "head", "align": "left"},
        ]
        tb = ui.table(columns=columns, rows=data, row_key="id", pagination=20).props(
            "flat dense binary-state-sort").classes("w-full sr-bl-table")
        tb.add_slot("body-cell-path", """
            <q-td :props="props"><div class="sr-bl-src"><a :href="props.row.url" target="_blank" rel="noopener"
              class="sr-bl-link" :title="props.row.url">{{ props.value }}</a>
              <div v-if="props.row.sitemap" class="sr-bl-sub">vào sitemap {{ props.row.sitemap }}</div></div>
            </q-td>""")
        tb.add_slot("body-cell-first", """
            <q-td :props="props"><span v-if="props.row.first">{{ props.row.first_t }}
              <span class="muted text-xs">· {{ props.row.age }} ngày</span></span>
              <span v-else class="sr-bl-type k-kw">chưa lên Google</span></q-td>""")
        for n in (7, 30, 90):
            tb.add_slot(f"body-cell-p{n}", """
            <q-td :props="props"><template v-if="props.row.p%(n)s">
              <div class="num" :class="props.row.p%(n)s.done ? '' : 'muted'">{{ props.row.p%(n)s.c.toLocaleString('vi-VN') }}
                click</div>
              <div class="sr-bl-sub">{{ props.row.p%(n)s.i.toLocaleString('vi-VN') }} hiển thị<span
                v-if="props.row.p%(n)s.pos"> · vị trí {{ props.row.p%(n)s.pos.toLocaleString('vi-VN') }}</span></div>
              <div v-if="!props.row.p%(n)s.done" class="sr-bl-sub">đang chạy<q-tooltip>Chưa đủ %(n)s ngày kể từ
                lúc lên Google: số đến hôm nay</q-tooltip></div></template>
              <span v-else class="muted">–</span></q-td>""" % {"n": n})
        tb.add_slot("body-cell-head", """
            <q-td :props="props"><div v-if="props.value" class="sr-op-kw">{{ props.value }}
              <span v-if="props.row.head_pos" class="muted text-xs">· vị trí {{
                props.row.head_pos.toLocaleString('vi-VN') }}</span></div>
              <span v-else class="muted">–</span></q-td>""")

    def new_tab(rows: list[dict]) -> None:
        explain("Trang lần đầu có lượt hiển thị trên Google trong 90 ngày qua (hoặc mới vào sitemap): theo dõi bài "
                "mới đăng có lên Google, lên với từ khóa nào, sau 7 / 30 / 90 ngày được bao nhiêu click.", [
                    "Trang đã 30 ngày mà vẫn rất ít hiển thị: kiểm tra index ở màn URL & Index, thêm link nội bộ từ "
                    "trang mạnh, xem lại từ khóa mục tiêu.",
                    f"Mặc định chỉ hiện trang đã có từ {O.NEW_SIGNAL} lượt hiển thị; trang sản phẩm mới chỉ vài lượt "
                    "hiển thị nằm trong “Tất cả”."])
        n_sig = sum(1 for r in rows if r["impressions"] >= O.NEW_SIGNAL)
        ui.toggle({"signal": f"Đã có tín hiệu · {n_sig:,}".replace(",", "."),
                   "all": f"Tất cả · {len(rows):,}".replace(",", ".")}, value=state["new"],
                  on_change=lambda e: (state.update(new=e.value), new_table.refresh(rows))).props(
            "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
            "sr-seg q-mb-sm")
        new_table(rows)

    # ---- Thực thể thương hiệu (Knowledge Graph) ----
    async def kg_now(btn) -> None:
        from contextlib import closing

        from . import db
        from .cwv import load_key
        if not ed:
            return
        _pt = PT.take(ui, user, cfg, "kg")
        if _pt is False:
            return
        btn.props("loading")

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                return BE.run(c, cfg, load_key(cfg))
        try:
            r = await run.io_bound(work)
            if r["error"]:
                ui.notify("Đã kiểm tra schema; Knowledge Graph chưa gọi được (xem hướng dẫn trên trang)",
                          type="warning", position="bottom-right")
            else:
                ui.notify(f"{r['found']}/{r['brands']} thương hiệu có thực thể trên Google", type="positive",
                          position="bottom-right")
        except Exception as ex:  # noqa: BLE001
            PT.give_back(_pt)
            ui.notify(f"Chưa kiểm tra được: {ex}", type="warning", position="bottom-right")
        with connect() as c:
            state["data"] = {**state["data"], "kg": BE.latest(c, cfg)}
        body.refresh()

    def kg_tab(kg: dict) -> None:
        explain("Google hiểu thương hiệu là một “thực thể” (Knowledge Graph) thì dễ hiện Knowledge Panel, được AI "
                "Overview / ChatGPT nhắc đúng tên, và tìm tên thương hiệu ra đúng website.", [
                    "Tool hỏi Google Knowledge Graph về thương hiệu của mình và các đối thủ (danh sách ở trang AI "
                    "Overview), và đọc schema thương hiệu ở trang chủ. Tự kiểm tra mỗi tuần, miễn phí."])
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            if kg["at"]:
                from datetime import datetime
                at = datetime.fromisoformat(kg["at"]).astimezone()
                ui.label(f"Kiểm tra lần gần nhất {at:%H:%M %d/%m/%Y}").classes("text-sm muted")
            else:
                ui.label("Chưa kiểm tra lần nào.").classes("text-sm muted")
            ui.space()
            if ed:
                btn = ui.button("Kiểm tra ngay", icon="hub").props("unelevated no-caps")
                btn.on_click(lambda: kg_now(btn))
        if kg["error"]:
            with ui.element("div").classes("sr-op-warn"):
                ui.icon("warning", size="18px").props('aria-hidden="true"')
                ui.label(kg["error"]).classes("text-sm")
        if not kg["at"]:
            T.empty_state(ui, "hub", "Chưa có kết quả", "Bấm “Kiểm tra ngay” (người có quyền sửa) hoặc chờ lịch hằng "
                          "tuần.")
            return
        icons = {True: ("check_circle", "#1E7C31", "Đạt"), False: ("cancel", "#C2410C", "Chưa đạt"),
                 None: ("help_outline", "#8C8A7E", "Chưa biết")}
        with ui.element("div").classes("sr-card q-pa-md w-full q-mb-md"):
            ok = sum(1 for c in kg["checks"] if c["ok"])
            known = sum(1 for c in kg["checks"] if c["ok"] is not None)
            ui.label(f"Việc nên làm · đạt {ok}/{known}").classes("text-base font-semibold q-mb-sm")
            for c in sorted(kg["checks"], key=lambda c: {False: 0, None: 1, True: 2}[c["ok"]]):
                icon, color, word = icons[c["ok"]]
                with ui.row().classes("w-full no-wrap items-start gap-3 sr-op-kgrow"):
                    ui.icon(icon, size="20px").style(f"color:{color}").props(f'aria-label="{word}"')
                    with ui.column().classes("gap-0 col").style("min-width:0"):
                        ui.label(c["title"]).classes("text-sm font-semibold")
                        if c["detail"]:
                            ui.label(c["detail"]).classes("text-sm muted sr-op-detail")
                        if c["ok"] is False:
                            ui.label("Cách làm: " + c["fix"]).classes("text-sm sr-op-fix")
        sch = kg["schema"] or {}
        if sch.get("same_as"):
            with ui.element("div").classes("sr-card q-pa-md w-full q-mb-md"):
                ui.label("Hồ sơ khai báo trong schema (sameAs)").classes("text-base font-semibold q-mb-xs")
                for u in sch["same_as"]:
                    ui.link(u, u, new_tab=True).classes("sr-bl-link text-sm")
        if kg["brands"]:
            ui.label("Thương hiệu và đối thủ trên Knowledge Graph").classes("text-base font-semibold q-mb-xs")
            rows = [{"id": i, "brand": b["name"], "own": b["own"], "found": b["found"],
                     "kg_name": b.get("name") if b["found"] else "", "types": ", ".join(b.get("types", [])[:3]),
                     "desc": (b.get("description") or "") + (" · " + b["detail"][:120] if b.get("detail") else ""),
                     "url": b.get("url", ""), "score": b.get("score")} for i, b in enumerate(kg["brands"])]
            tb = ui.table(columns=[
                {"name": "brand", "label": "Thương hiệu", "field": "brand", "align": "left"},
                {"name": "found", "label": "Thực thể", "field": "found", "align": "left"},
                {"name": "types", "label": "Google hiểu là", "field": "types", "align": "left"},
                {"name": "desc", "label": "Mô tả", "field": "desc", "align": "left"},
                {"name": "url", "label": "Website", "field": "url", "align": "left"},
                {"name": "score", "label": "Điểm", "field": "score", "align": "right"},
            ], rows=rows, row_key="id").props("flat dense").classes("w-full sr-bl-table")
            tb.add_slot("body-cell-brand", """
                <q-td :props="props"><div class="sr-op-kw">{{ props.value }}
                  <span v-if="props.row.own" class="sr-bl-type k-url q-ml-xs">của mình</span></div></q-td>""")
            tb.add_slot("body-cell-found", """
                <q-td :props="props"><span class="sr-bl-type" :class="props.value ? 'k-new' : 'k-lost'">{{
                  props.value ? 'Có' : 'Chưa có' }}</span></q-td>""")
            tb.add_slot("body-cell-desc", """
                <q-td :props="props"><div class="sr-op-detail">{{ props.value || '–' }}</div></q-td>""")
            tb.add_slot("body-cell-url", """
                <q-td :props="props"><a v-if="props.value" :href="props.value" target="_blank" rel="noopener"
                  class="sr-bl-link">{{ props.value.replace(/^https?:\\/\\/(www\\.)?/, '') }}</a>
                  <span v-else class="muted">–</span></q-td>""")
            ui.label("Điểm càng cao: Google càng chắc đây là thương hiệu của bạn.").classes("text-xs muted q-mt-xs")


    # ---- Dự báo từ khóa theo dõi ----
    def forecast_tab(fc: dict) -> None:
        from . import keyword_research as KR
        cur = fc["currency"]
        def export_btn() -> None:  # giá trị theo giá thầu Google Ads: chỉ để đối chiếu, có trong file Excel
            from datetime import date as _d

            from .web_export import export_menu
            export_menu(ui, cfg, connect, f"day-len-top_{_d.today():%Y-%m-%d}", lambda: forecast_xlsx(fc, site),
                        label="Xuất", user=user, category="audit")
        explain(f"Từ khóa đang theo dõi hạng chưa vào top {fc['target']}: lên được top {fc['target']} thì có thêm bao "
                "nhiêu click mỗi tháng.", [
                    "Từ khóa đầu danh sách đáng đẩy nhất. “Sắp vào mùa”: 2 tháng tới người tìm nhiều hơn bình thường, "
                    "nên đẩy ngay.",
                    f"Không tính {fc['no_volume']} từ khóa gần như không ai tìm (Google Ads không có số)."
                    if fc["no_volume"] else "Ước tính, dùng để xếp thứ tự ưu tiên.",
                    *(["Nút Xuất: file Excel có thêm giá trị ước tính của số click tăng thêm theo giá thầu Google Ads "
                       "(chỉ để đối chiếu)."] if fc["rows"] and ed else [])],
                extra=export_btn if fc["rows"] and ed else None)
        if not fc["rows"]:
            T.empty_state(ui, "emoji_events", "Không có từ khóa nào cần đẩy",
                          "Các từ khóa đều đã ở top 3.")
            return
        with ui.element("div").classes("sr-op-audit-sum"):
            for num, lab in ((f"+{fc['gain']:,}".replace(",", "."), "click / tháng nếu mọi từ khóa lên top 3"),
                             (f"{len(fc['rows'])}", "từ khóa chưa vào top 3"),
                             (f"{sum(1 for r in fc['rows'] if r['soon'])}", "từ khóa sắp vào mùa")):
                with ui.element("div").classes("sr-op-stat"):
                    ui.label(num).classes("sr-op-stat-num")
                    ui.label(lab).classes("text-sm muted")
        months = "Th1 Th2 Th3 Th4 Th5 Th6 Th7 Th8 Th9 Th10 Th11 Th12".split()
        data = [{**r, "id": i, "peak_t": months[r["peak"] - 1] if r["peak"] else "",
                 "value_t": KR.money(r["value"], cur) if r["value"] is not None else "–",
                 "path": _path(r["url"], site) if r["url"] else ""} for i, r in enumerate(fc["rows"])]
        tb = ui.table(columns=[
            {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left"},
            {"name": "rank", "label": "Vị trí", "field": "rank", "align": "right",
             ":format": "v => v === null || v === undefined ? 'chưa thấy' : v"},
            {"name": "volume", "label": "Volume / tháng", "field": "volume", "align": "right", ":format": NUM},
            {"name": "gain", "label": "+ Click / tháng", "field": "gain", "align": "right"},
            {"name": "season", "label": "Mùa", "field": "peak", "align": "left"},
        ], rows=data, row_key="id", pagination=20).props("flat dense binary-state-sort").classes(
            "w-full sr-bl-table")
        tb.add_slot("body-cell-keyword", """
            <q-td :props="props"><div class="sr-op-kw">{{ props.value }}</div>
              <div class="sr-bl-sub">{{ props.row.set }}<span v-if="props.row.path"> · {{ props.row.path }}</span>
              </div></q-td>""")
        T.bar_slot(tb, "gain", max(r["gain"] for r in data))
        tb.add_slot("body-cell-season", """
            <q-td :props="props"><span v-if="props.row.soon" class="sr-bl-type k-lost">sắp vào mùa</span>
              <span v-if="props.row.peak_t" class="muted text-xs q-ml-xs">cao điểm {{ props.row.peak_t }}</span>
              <span v-if="!props.row.soon && !props.row.peak_t" class="muted">–</span></q-td>""")

    body()

    async def load() -> None:
        def work():
            from contextlib import closing

            from . import db
            with closing(db.connect(cfg.db_path)) as c:
                return {**O.summary(c, site, end, cfg.keywords),
                        "kg": BE.latest(c, cfg),
                        "forecast": SVL.forecast(c, cfg, end)}
        try:
            state["data"] = await run.io_bound(work)
        except Exception as ex:  # noqa: BLE001
            state["data"] = {"striking": [], "decay": [], "cannibal": [], "new": [],
                             "kg": {"at": None, "error": None, "brands": [], "schema": None, "schema_error": None,
                                    "home": site, "checks": []},
                             "forecast": {"rows": [], "gain": 0, "value": 0, "target": 3, "no_volume": 0,
                                          "currency": "VND"}}
            ui.notify(f"Chưa tính được cơ hội SEO: {ex}", type="warning")
        body.refresh()

    background_tasks.create(load())


def _p(v) -> str:
    return f"{v:.1f}".replace(".", ",") if v else "–"


def forecast_xlsx(fc: dict, site: str) -> bytes:
    """Excel tab Đẩy lên top: mỗi từ khóa + click thêm + giá trị ước tính (click × giá thầu Google Ads, để đối chiếu)."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Đẩy lên top"
    cur = fc.get("currency") or ""
    ws.append(["Từ khóa", "Bộ", "Trang", "Vị trí", "Volume / tháng", "+ Click / tháng",
               f"+ Giá trị ước tính / tháng ({cur})", "Sắp vào mùa"])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="F3F3ED")
    for r in fc["rows"]:
        ws.append([r["keyword"], r.get("set", ""), r.get("url") or "", r.get("rank"), r.get("volume"), r.get("gain"),
                   round(r["value"]) if r.get("value") is not None else None, "Có" if r.get("soon") else ""])
    ws.append([])
    ws.append(["Giá trị ước tính = click thêm × giá thầu Google Ads của từ khóa: chỉ để đối chiếu, không phải doanh thu."])
    for col, w in zip("ABCDEFGH", (34, 18, 50, 8, 14, 14, 22, 12)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
