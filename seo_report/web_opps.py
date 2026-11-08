"""Trang Cơ hội SEO (/co-hoi, nhóm SEO): 4 tab việc nên làm rút từ dữ liệu Search Console đã lưu (opportunities.py).
Không gọi API, không tốn tiền. Team xem (người sửa và người chỉ xem); khách hàng không thấy."""
from datetime import date

from . import access as A
from . import brand_entity as BE
from . import keywords as K
from . import opportunities as O
from . import seo_value as SVL
from . import site_audit as SA
from . import ui_theme as T

TABS = (("audit", "Audit kỹ thuật"), ("du-bao", "Dự báo từ khóa"), ("len-top", "Sắp lên top"), ("giam", "Trang tụt traffic"),
        ("tranh", "Tranh nhau từ khóa"), ("moi", "Trang mới"), ("thuc-the", "Thực thể thương hiệu"))
NUM = "v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN')"
POS = "v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN', {maximumFractionDigits: 1})"
TAB_ICON = {"audit": "fact_check", "du-bao": "query_stats", "len-top": "trending_up", "giam": "trending_down",
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
    T.page_header(ui, "insights", "Cơ hội SEO",
                  f"Từ Search Console: 28 ngày gần nhất ({cur[0]:%d/%m} – {cur[1]:%d/%m/%Y}) so với 28 ngày trước "
                  f"({prev[0]:%d/%m} – {prev[1]:%d/%m}). Tính từ dữ liệu đã có, không tốn chi phí.")
    ed = A.can_edit(user)
    state = {"tab": start if start in dict(TABS) else "audit", "data": None, "strike": "all", "new": "signal",
             "q": ""}

    def pick(v: str) -> None:
        if v == state["tab"]:
            return
        state["tab"] = v
        ui.run_javascript(f"history.replaceState(null, '', '/co-hoi' + ('{v}' === 'audit' ? '' : '?tab={v}'))")
        cards.refresh()
        panel.refresh()

    def _n(v) -> str:
        return f"{v:,.0f}".replace(",", ".")

    def summary(data: dict) -> dict[str, tuple[int, str, str]]:
        """Mỗi thẻ: (số chính, dòng phụ, tông: bad/warn/good/neutral)."""
        au = data["audit"]
        issues = len({p["url_id"] for c in au["checks"] if c["level"] != "info" for p in c["pages"]})
        fc = data["forecast"]
        st = data["striking"]
        dc = data["decay"]
        serious = sum(1 for g in data["cannibal"] if g["serious"])
        new_sig = sum(1 for r in data["new"] if r["impressions"] >= O.NEW_SIGNAL)
        kg_bad = sum(1 for c in data["kg"]["checks"] if c["ok"] is False)
        return {
            "audit": (issues, f"trang cần sửa / {_n(au['pages'])} trang đã quét" if au["pages"] else "chưa quét",
                      "bad" if issues else "good"),
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
        with ui.element("div").classes("sr-op-nav").props('role="tablist" aria-label="Loại cơ hội"'):
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
             "audit": lambda: audit_tab(data["audit"]), "du-bao": lambda: forecast_tab(data["forecast"]),
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

    def explain(title: str, lines: list[str]) -> None:
        """Đầu tab: tên tab + một câu mô tả; cách đọc / việc nên làm gấp lại, bấm "Cách đọc" để mở."""
        name = dict(TABS)[state["tab"]]
        with ui.row().classes("w-full items-start no-wrap gap-3 sr-op-head"):
            ui.icon(TAB_ICON[state["tab"]], size="22px").classes("sr-op-head-ico").props('aria-hidden="true"')
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label(name).classes("sr-op-head-title")
                ui.label(title).classes("text-sm muted")
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
        data = [{**r, "id": i, "path": _path(r["url"], site),
                 "move": None if r["prev_position"] is None else round(r["prev_position"] - r["position"], 1)}
                for i, r in enumerate(shown)]
        tb = ui.table(columns=columns, rows=data, row_key="id", pagination=20).props(
            "flat dense binary-state-sort").classes("w-full sr-bl-table")
        tb.add_slot("body-cell-query", """
            <q-td :props="props"><div class="sr-op-kw">{{ props.value }}
              <span v-if="props.row.tracked" class="sr-bl-type k-url q-ml-xs">đang theo dõi hạng</span>
              <span v-if="props.row.urls > 1" class="sr-bl-type q-ml-xs">{{ props.row.urls }} trang cùng lên
                <q-tooltip>Có {{ props.row.urls }} trang của site cùng nhận lượt hiển thị cho từ khóa này; số liệu là
                  của trang nhận nhiều nhất</q-tooltip></span></div></q-td>""")
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
            "nội bộ từ các trang mạnh về trang này.",
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

    # ---- Audit kỹ thuật ----
    async def scan_now(btn) -> None:
        from contextlib import closing

        from . import db
        from . import notices as N
        key = str(cfg.db_path)
        if not ed or key in SA.running:
            return
        SA.running[key] = {"n": 0, "total": 0, "by": str(user)}
        btn.props("loading")
        note = ui.notification("Đang quét các trang quan trọng (khoảng 5 phút, có thể rời trang)…", spinner=True,
                               timeout=None, type="ongoing", position="bottom-right")

        def prog(n, total):
            SA.running[key].update(n=n, total=total)

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                return SA.run(c, site, end, str(user), progress=prog, log=lambda m: None)
        try:
            r = await run.io_bound(work)
            ui.notify(f"Đã quét {r['pages']} trang" + (f" ({r['errors']} trang không mở được)" if r["errors"]
                                                         else ""), type="positive", position="bottom-right")
        except Exception as ex:  # noqa: BLE001
            ui.notify(f"Quét chưa xong: {ex}", type="warning", position="bottom-right")
        finally:
            SA.running.pop(key, None)
            try:
                note.dismiss()
            except Exception:  # noqa: BLE001 — người dùng đã rời trang
                pass
        N.forget()
        with connect() as c:
            state["data"] = {**state["data"], "audit": SA.cached_findings(c, cfg)}
        body.refresh()

    def audit_tab(au: dict) -> None:
        explain("Tool tự mở các trang quan trọng nhất của website (nhiều click / hiển thị nhất 90 ngày qua, tối đa "
                f"{SA.MAX_PAGES} trang) và kiểm tra lỗi kỹ thuật SEO. Tự quét mỗi tuần, miễn phí.", [
                    "Kiểm tra: trang lỗi / chuyển hướng, noindex, canonical, tiêu đề, mô tả, H1, ảnh thiếu alt, nội "
                    "dung mỏng, tốc độ phản hồi; và từ Search Console: tiêu đề thiếu từ khóa chính, CTR thấp so với "
                    "vị trí. Bấm từng mục để xem trang cần sửa và cách sửa."])
        last = au["run"]
        key = str(cfg.db_path)
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            if last and last["finished_at"]:
                from datetime import datetime
                at = datetime.fromisoformat(last["finished_at"]).astimezone()
                ui.label(f"Quét lần gần nhất {at:%H:%M %d/%m/%Y} · {last['pages']} trang"
                         + (f" · {last['errors']} trang không mở được" if last["errors"] else "")).classes(
                    "text-sm muted")
            elif key not in SA.running:
                ui.label("Chưa quét lần nào.").classes("text-sm muted")
            ui.space()
            if key in SA.running:
                prog = ui.label().classes("text-sm muted")

                def tick():
                    r = SA.running.get(key)
                    prog.text = (f"Đang quét {r['n']}/{r['total'] or '…'} trang" if r
                                 else "Đã quét xong: tải lại trang để xem kết quả")
                tick()
                ui.timer(2, tick)
            elif ed:
                btn = ui.button("Quét ngay", icon="travel_explore").props("unelevated no-caps")
                btn.on_click(lambda: scan_now(btn))
            if au["pages"]:
                from .web_export import export_menu
                stamp = (last["finished_at"] or "")[:10] if last else ""
                export_menu(ui, cfg, connect, f"audit-ky-thuat_{stamp or end}", lambda: audit_xlsx(au, site), user=user,
                            category="audit")
        if not au["pages"]:
            T.empty_state(ui, "fact_check", "Chưa có kết quả audit",
                          "Bấm “Quét ngay” (người có quyền sửa) hoặc chờ lịch quét hằng tuần.")
            return
        lv = {k: sum(len(c["pages"]) for c in au["checks"] if c["level"] == k) for k in SA.LEVELS}
        with ui.element("div").classes("sr-op-audit-sum"):
            with ui.element("div").classes("sr-op-stat"):
                ui.label(f"{au['healthy']}/{au['pages']}").classes("sr-op-stat-num")
                ui.label("trang không có lỗi cần sửa").classes("text-sm muted")
            for k, (name, tone) in SA.LEVELS.items():
                with ui.element("div").classes("sr-op-stat"):
                    ui.label(f"{lv[k]:,}".replace(",", ".")).classes(f"sr-op-stat-num t-{tone}")
                    ui.label(f"{name} (lượt trang)").classes("text-sm muted")
        if not au["checks"]:
            T.empty_state(ui, "check_circle", "Không phát hiện lỗi nào")
            return
        for ch in au["checks"]:
            name, tone = SA.LEVELS[ch["level"]]
            with ui.expansion().classes("w-full sr-op-check").props("dense") as ex:
                with ex.add_slot("header"):
                    with ui.row().classes("w-full items-center no-wrap gap-3"):
                        T.pill(ui, name, tone)
                        ui.label(ch["name"]).classes("text-sm font-semibold col")
                        ui.label(f"{len(ch['pages'])} trang").classes("text-sm num muted")
                ui.label(ch["fix"]).classes("text-sm q-mb-sm")
                rows = [{"id": i, "url": p["url"], "path": _path(p["url"], site), "detail": p["detail"]}
                        for i, p in enumerate(ch["pages"])]
                tb = ui.table(columns=[
                    {"name": "path", "label": "Trang", "field": "path", "align": "left"},
                    {"name": "detail", "label": "Chi tiết", "field": "detail", "align": "left"},
                ], rows=rows, row_key="id", pagination=10).props("flat dense").classes("w-full sr-bl-table")
                tb.add_slot("body-cell-path", """
                    <q-td :props="props"><div class="sr-bl-src"><a :href="props.row.url" target="_blank"
                      rel="noopener" class="sr-bl-link" :title="props.row.url">{{ props.value }}</a></div></q-td>""")
                tb.add_slot("body-cell-detail", """
                    <q-td :props="props"><div class="sr-op-detail">{{ props.value || '–' }}</div></q-td>""")

    # ---- Thực thể thương hiệu (Knowledge Graph) ----
    async def kg_now(btn) -> None:
        from contextlib import closing

        from . import db
        from .cwv import load_key
        if not ed:
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
            ui.label("Điểm: mức Google chắc chắn thực thể khớp tên tìm (càng cao càng nổi). Thực thể “Chưa có” nghĩa "
                     "là Google chưa có thực thể khớp tên và website của thương hiệu.").classes("text-xs muted q-mt-xs")


    # ---- Dự báo từ khóa theo dõi ----
    def forecast_tab(fc: dict) -> None:
        from . import keyword_research as KR
        cur = fc["currency"]
        explain(f"Từ khóa đang theo dõi hạng chưa vào top {fc['target']}: lên được top {fc['target']} thì có thêm bao "
                "nhiêu click và tiền mỗi tháng (volume × tỷ lệ nhấp theo vị trí, × giá thầu Google Ads).", [
                    "Nhiều tiền trước: nên đẩy các từ khóa đầu danh sách. “Sắp vào mùa”: 2 tháng tới người tìm "
                    "nhiều hơn trung bình năm từ 20%, nên đẩy ngay.",
                    f"Không tính {fc['no_volume']} từ khóa gần như không ai tìm (Google Ads không có số)."
                    if fc["no_volume"] else "Ước tính, dùng để xếp thứ tự ưu tiên."])
        if not fc["rows"]:
            T.empty_state(ui, "emoji_events", "Không có từ khóa nào cần đẩy",
                          "Mọi từ khóa có volume đã ở top 3, hoặc chưa có volume / chưa check hạng.")
            return
        with ui.element("div").classes("sr-op-audit-sum"):
            for num, lab in ((f"+{fc['gain']:,}".replace(",", "."), "click / tháng nếu mọi từ khóa lên top 3"),
                             (KR.money(fc["value"], cur), "giá trị / tháng (theo giá thầu Google Ads)"),
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
            {"name": "value", "label": "+ Giá trị / tháng", "field": "value", "align": "right"},
            {"name": "season", "label": "Mùa", "field": "peak", "align": "left"},
        ], rows=data, row_key="id", pagination=20).props("flat dense binary-state-sort").classes(
            "w-full sr-bl-table")
        tb.add_slot("body-cell-keyword", """
            <q-td :props="props"><div class="sr-op-kw">{{ props.value }}</div>
              <div class="sr-bl-sub">{{ props.row.set }}<span v-if="props.row.path"> · {{ props.row.path }}</span>
              </div></q-td>""")
        T.bar_slot(tb, "gain", max(r["gain"] for r in data))
        tb.add_slot("body-cell-value", """
            <q-td :props="props"><span class="num">{{ props.row.value_t }}</span></q-td>""")
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
                return {**O.summary(c, site, end, cfg.keywords), "audit": SA.cached_findings(c, cfg),
                        "kg": BE.latest(c, cfg),
                        "forecast": SVL.forecast(c, cfg, end)}
        try:
            state["data"] = await run.io_bound(work)
        except Exception as ex:  # noqa: BLE001
            state["data"] = {"striking": [], "decay": [], "cannibal": [], "new": [],
                             "audit": {"checks": [], "pages": 0, "healthy": 0, "run": None},
                             "kg": {"at": None, "error": None, "brands": [], "schema": None, "schema_error": None,
                                    "home": site, "checks": []},
                             "forecast": {"rows": [], "gain": 0, "value": 0, "target": 3, "no_volume": 0,
                                          "currency": "VND"}}
            ui.notify(f"Chưa tính được cơ hội SEO: {ex}", type="warning")
        body.refresh()

    background_tasks.create(load())


def audit_xlsx(au: dict, site: str) -> bytes:
    """File audit: Tóm tắt (lần quét, số theo mức, từng lỗi + cách sửa) · Lỗi theo trang (mỗi dòng một lỗi của
    một trang, lọc được) · Theo trang (mỗi trang một dòng, đếm lỗi theo mức)."""
    import io
    from datetime import datetime

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="EEF3E6")
    fills = {"high": "FCE4D6", "medium": "FFF2CC", "info": "DDEBF7"}
    wb = Workbook()

    def table(ws, head, rows, widths, level_col=None):
        ws.append(head)
        for c in ws[ws.max_row]:
            c.font, c.fill = bold, head_fill
        start = ws.max_row
        for r in rows:
            ws.append(r)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for row in ws.iter_rows(min_row=start + 1):
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=True)
            if level_col is not None:
                key = next((k for k, (n, _) in SA.LEVELS.items() if n == row[level_col].value), None)
                if key:
                    row[level_col].fill = PatternFill("solid", fgColor=fills[key])
        ws.auto_filter.ref = f"A{start}:{get_column_letter(len(head))}{ws.max_row}"
        ws.freeze_panes = f"A{start + 1}"

    # 1. Tóm tắt
    ws = wb.active
    ws.title = "Tóm tắt"
    last = au["run"] or {}
    at = ""
    if last.get("finished_at"):
        at = f"{datetime.fromisoformat(last['finished_at']).astimezone():%H:%M %d/%m/%Y}"
    lv = {k: sum(len(c["pages"]) for c in au["checks"] if c["level"] == k) for k in SA.LEVELS}
    for k, v in (("Website", site), ("Quét lúc", at), ("Số trang đã quét", au["pages"]),
                 ("Trang không có lỗi cần sửa", au["healthy"]),
                 ("Trang không mở được", last.get("errors") or 0),
                 *[(f"{name} (lượt trang)", lv[k]) for k, (name, _) in SA.LEVELS.items()]):
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = bold
    ws.append([])
    table(ws, ["Mức", "Lỗi", "Số trang", "Cách sửa"],
          [[SA.LEVELS[c["level"]][0], c["name"], len(c["pages"]), c["fix"]] for c in au["checks"]],
          [30, 44, 10, 90], level_col=0)
    ws.freeze_panes = None

    # 2. Lỗi theo trang
    table(wb.create_sheet("Lỗi theo trang"), ["Mức", "Lỗi", "Trang", "URL", "Chi tiết", "Cách sửa"],
          [[SA.LEVELS[c["level"]][0], c["name"], _path(p["url"], site), p["url"], p["detail"] or "", c["fix"]]
           for c in au["checks"] for p in c["pages"]],
          [12, 36, 40, 50, 50, 70], level_col=0)

    # 3. Theo trang
    per: dict[str, dict] = {}
    for c in au["checks"]:
        for p in c["pages"]:
            d = per.setdefault(p["url"], {k: 0 for k in SA.LEVELS} | {"names": []})
            d[c["level"]] += 1
            d["names"].append(f"[{SA.LEVELS[c['level']][0]}] {c['name']}")
    rows = sorted(per.items(), key=lambda x: (-x[1]["high"], -x[1]["medium"], -x[1]["info"], x[0]))
    table(wb.create_sheet("Theo trang"),
          ["Trang", "URL", *[n for n, _ in SA.LEVELS.values()], "Các lỗi"],
          [[_path(u, site), u, *[d[k] for k in SA.LEVELS], "\n".join(d["names"])] for u, d in rows],
          [40, 50, 10, 10, 10, 70])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _p(v) -> str:
    return f"{v:.1f}".replace(".", ",") if v else "–"
