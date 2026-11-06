"""Tab Tổng quan ở màn Từ khóa & Thứ hạng: dashboard đọc trong 10 giây (Tổng quan → Điều đáng chú ý → Mở chi tiết).

A. Tổng quan SEO — đang ở đâu (từ khóa, bộ, Top 3 / 5 / 10, biến động)
B. Xu hướng — tốt lên hay xấu đi (% Top 3 / 5 / 10 theo lần check / tuần / tháng)
C. Đối thủ — vị thế cạnh tranh (thị phần, hạng, đối thủ dẫn đầu, bị vượt)
D. Điều cần chú ý — tối đa 5 mục, bấm để xem từ khóa
E. Bộ từ khóa — mở bộ nào (bảng gọn, bộ cần chú ý trước; xem tất cả trong hộp thoại)

Một bộ lọc phạm vi (Tất cả bộ / Cam kết / Theo dõi / một bộ) đổi mọi khu cùng lúc. Quy tắc số: xem rank_dashboard.
"""
from datetime import date

from . import keywords as K
from . import rank as R
from . import rank_dashboard as D

TONE_COLORS = {"good": "#1E7C31", "bad": "#C2410C", "warn": "#B7791F", "grey": "#8C8A7E"}
SHOW_SETS = 6  # số bộ hiện trên dashboard; còn lại trong "Xem tất cả bộ từ khóa"


def _vn(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso else ""


def build_dashboard(ui, cfg, connect, user, open_set, new_set) -> None:
    from . import ui_theme as T
    site = cfg.site_url
    with connect() as c:
        end = K.latest_date(c, site)
        all_sets = [x for x in R.sets(c, site) if not x["draft"]]
    state = {"scope": "all", "period": "check"}

    # ---------------------------------------------------------------- thanh phạm vi + tạo bộ
    with ui.row().classes("w-full items-center gap-2 q-mb-sm sr-rd-bar"):
        ui.label("Phạm vi").classes("text-sm muted")
        kind_t = ui.toggle(D.KIND_SCOPES, value="all", on_change=lambda e: pick(e.value)).props(
            "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes("sr-seg")
        one = ui.select({x["id"]: x["name"] for x in all_sets}, label="Hoặc một bộ", clearable=True,
                        on_change=lambda e: pick(e.value or "all", from_select=True)).props(
            "dense outlined options-dense").classes("w-56")
        # tạo bộ mới: dùng nút "+" ở thanh tab (có ở mọi tab), không lặp nút ở đây

    def pick(value, from_select: bool = False):
        """Đổi phạm vi; đặt lại ô còn lại mà không kích hoạt đổi lần hai."""
        if state.get("busy") or value is None:
            return
        state["busy"] = True
        try:
            state["scope"] = value
            if from_select:
                kind_t.value = None if value != "all" else "all"
            elif value in D.KIND_SCOPES:
                one.value = None
            body.refresh()
        finally:
            state["busy"] = False

    @ui.refreshable
    def body():
        scope = state["scope"]
        with connect() as c:
            kws, rows = D.scope_keywords(c, site, end, scope)
            n_sets = len(D.scope_sets(c, site, scope))
            if not n_sets:
                T.empty_state(ui, "folder_off", "Chưa có bộ từ khóa nào trong phạm vi này",
                              "Tạo bộ bằng nút + ở thanh tab, hoặc chọn phạm vi khác.")
                return
            k = D.kpis(kws)
            try:
                comp = D.competitor_snapshot(c, cfg, end, scope, kws)
            except Exception as e:  # noqa: BLE001
                comp = {"invalid": f"Không tính được số đối thủ: {str(e)[:120]}"}
            tr = D.trend(c, kws, state["period"], 12)
            ins = D.insights(kws, comp if "invalid" not in comp else None)
            sets_ = D.set_list(c, cfg, end, scope)
        section_a(k, n_sets, rows)
        with ui.element("div").classes("sr-rd-row two"):
            section_b(tr, scope)
            section_c(comp)
        with ui.element("div").classes("sr-rd-row two rev"):
            section_d(ins, k)
            section_e(sets_)

    # ---------------------------------------------------------------- A. Tổng quan SEO
    def section_a(k: dict, n_sets: int, rows: int):
        tot = k["total"]
        with ui.element("div").classes("sr-rd-kpis"):
            with ui.element("div").classes("sr-rd-kpi"):
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.label("Từ khóa theo dõi").classes("sr-rd-lab")
                    T.info_icon(ui, "Từ khóa theo dõi", (
                        "Số từ khóa duy nhất trong phạm vi: một từ khóa nằm ở nhiều bộ chỉ tính một lần (ưu tiên bộ "
                        "Cam kết). Không tính bộ Nháp và từ khóa tạm dừng.",
                        "Lượt theo dõi = tổng số dòng từ khóa của các bộ."))
                ui.label(f"{tot:,}".replace(",", ".")).classes("sr-rd-num")
                ui.label(f"{n_sets} bộ · {rows} lượt theo dõi").classes("sr-rd-sub")
                if k["new"] or k["unchecked"]:
                    ui.label(" · ".join(x for x in (f"{k['new']} mới kiểm tra" if k["new"] else "",
                                                     f"{k['unchecked']} chưa check" if k["unchecked"] else "")
                                        if x)).classes("sr-rd-sub neutral")
            for n in (3, 5, 10):
                t = k["tiers"][n]
                with ui.element("div").classes("sr-rd-kpi"):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.label(f"Top {n}").classes("sr-rd-lab")
                        T.info_icon(ui, f"Top {n}", (
                            f"Số từ khóa đang ở hạng 1–{n} (cộng dồn: Top {n} gồm cả nhóm cao hơn), % trên {tot} từ "
                            "khóa của phạm vi.",
                            "Vào / rời: so với lần check trước của từng từ khóa có lịch sử. Từ khóa mới kiểm tra không "
                            "tính là tăng."))
                    with ui.row().classes("w-full items-baseline gap-2 no-wrap"):
                        delta = t["enter"] - t["leave"] + t["new"]  # số chính tăng: xanh, giảm: đỏ
                        ui.label(str(t["count"])).classes(
                            "sr-rd-num" + ("" if not delta else (" good" if delta > 0 else " bad")))
                        ui.label(f"{t['count'] / tot * 100:.0f}%" if tot else "").classes("sr-rd-pct")
                        if delta:
                            ui.label(f"{'▲' if delta > 0 else '▼'} {abs(delta)}").classes(
                                "sr-kc-delta " + ("good" if delta > 0 else "bad")).tooltip(
                                f"{'Tăng' if delta > 0 else 'Giảm'} {abs(delta)} từ khóa so với lần check trước")
                    with ui.row().classes("items-center gap-2 no-wrap sr-rd-sub"):
                        if k["history"]:
                            ui.label(f"+{t['enter']} vào").classes("good" if t["enter"] else "zero")
                            ui.label(f"−{t['leave']} rời").classes("bad" if t["leave"] else "zero")
                        if t["new"]:
                            ui.label(f"+{t['new']} mới").classes("neutral")
            with ui.element("div").classes("sr-rd-kpi"):
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.label("Biến động thứ hạng").classes("sr-rd-lab")
                    T.info_icon(ui, "Biến động thứ hạng", (
                        "Số từ khóa lên / rớt vị trí so với lần check trước của chính nó (khác với vào / rời Top N).",
                        f"Chỉ tính {k['history']} từ khóa có lần check trước."))
                if k["history"]:
                    with ui.row().classes("items-baseline gap-3 no-wrap"):
                        ui.html(f"<span class='sr-rd-num {'good' if k['up'] else 'zero'}'>↗ {k['up']}</span>")
                        ui.html(f"<span class='sr-rd-num {'bad' if k['down'] else 'zero'}'>↘ {k['down']}</span>")
                    ui.label(f"lên · rớt trên {k['history']} từ khóa có lịch sử"
                             + (f" · so với {_vn(k['prev_date'])}" if k["prev_date"] else "")).classes("sr-rd-sub")
                else:
                    ui.label("–").classes("sr-rd-num zero")
                    ui.label("Chưa có lần check thứ hai để so").classes("sr-rd-sub neutral")

    # ---------------------------------------------------------------- B. Xu hướng
    def section_b(tr: list[dict], scope):
        with ui.element("div").classes("sr-card sr-rd-card"):
            with ui.row().classes("w-full items-center gap-2 no-wrap q-mb-xs"):
                ui.label("Xu hướng thứ hạng").classes("sr-bx-title")
                T.info_icon(ui, "Xu hướng thứ hạng", (
                    "% từ khóa ở Top 3 / 5 / 10 trên số từ khóa đã có số đến thời điểm đó: thêm từ khóa mới không "
                    "làm đường đi lên giả.",
                    "Tuần / tháng không có lần check nào để trống (không nối đường qua). Rê chuột để xem số từ khóa và "
                    "ngày."))
                ui.space()
                ui.toggle({"check": "Lần check", "week": "Tuần", "month": "Tháng"}, value=state["period"],
                          on_change=lambda e: (state.update(period=e.value), body.refresh())).props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                    "sr-seg")
            if not [p for p in tr if p["has_data"]]:
                ui.label("Chưa có lần check nào trong phạm vi này.").classes("text-sm muted q-py-md")
            else:
                trend_chart(tr)
                thin = sum(1 for p in tr if p["has_data"] and p["thin"])
                if thin:
                    ui.label(f"Không vẽ {thin} kỳ có dưới một nửa số từ khóa đã có số (tỷ lệ % chưa đại diện)."
                             ).classes("sr-rd-sub neutral")
            target = scope if isinstance(scope, int) else (all_sets[0]["id"] if all_sets else None)
            if target:
                ui.button("Xem phân tích chi tiết →", on_click=lambda: open_set(target)).props(
                    "flat dense no-caps color=primary").classes("sr-rd-link q-mt-xs")

    def trend_chart(tr: list[dict]):
        colors = {3: "#1E7C31", 5: "#5E9C2E", 10: "#9BB823"}
        dashes = {3: "solid", 5: "dashed", 10: "dotted"}
        series = []
        for n in (10, 5, 3):
            series.append({"name": f"Top {n}", "type": "line", "connectNulls": False, "symbolSize": 7,
                           "data": [p[f"pct{n}"] for p in tr],
                           "lineStyle": {"width": 2.25, "type": dashes[n], "color": colors[n]},
                           "itemStyle": {"color": colors[n]}})
        vals = [p[f"pct{n}"] for p in tr for n in (3, 5, 10) if p[f"pct{n}"] is not None]
        top = min(100, max(10, int((max(vals) if vals else 10) / 10 + 1) * 10))
        info = [{"c": p["checked"], "n": p["new"], "t3": p["top3"], "t5": p["top5"], "t10": p["top10"],
                 "f": _vn(p["from"]), "e": _vn(p["to"])} for p in tr]
        import json
        ui.echart({
            "animation": False,
            "grid": {"left": 40, "right": 14, "top": 30, "bottom": 24},
            "legend": {"top": 0, "left": 0, "itemWidth": 22, "itemHeight": 8, "data": ["Top 3", "Top 5", "Top 10"],
                       "textStyle": {"fontSize": 12, "color": "#4A4A40"}},
            "tooltip": {"trigger": "axis", "confine": True, ":formatter": (
                f"ps => {{ const I = {json.dumps(info)}; const i = ps[0].dataIndex; const x = I[i]; "
                "const when = x.f === x.e ? 'Ngày ' + x.f : x.f + ' – ' + x.e; "
                "if (x.t3 === null) return when + '<br/><span style=\"color:#8C8A7E\">Không có lần check</span>'; "
                "if (ps[0].value == null) return when + '<br/><span style=\"color:#8C8A7E\">Mới ' + x.c + "
                "' từ khóa có số: chưa đại diện</span>'; "
                "return when + '<br/>' + ps.map(p => p.marker + p.seriesName + ': <b>' + "
                "({'Top 3': x.t3, 'Top 5': x.t5, 'Top 10': x.t10}[p.seriesName]) + ' từ khóa</b> (' + "
                "String(p.value).replace('.', ',') + '%)').join('<br/>') + "
                "'<br/><span style=\"color:#6B6A5E\">Trên ' + x.c + ' từ khóa đã có số' + "
                "(x.n ? ' · ' + x.n + ' mới kiểm tra' : '') + '</span>'; }")},
            "xAxis": {"type": "category", "data": [p["label"] for p in tr], "boundaryGap": False,
                      "axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                      "axisLabel": {"color": "#6B6A5E", "fontSize": 11, "hideOverlap": True}},
            "yAxis": {"type": "value", "min": 0, "max": top, "splitNumber": 4,
                      "axisLabel": {"color": "#6B6A5E", "fontSize": 11, "formatter": "{value}%"},
                      "splitLine": {"lineStyle": {"color": "#F0EEE6"}}},
            "series": series}).classes("w-full").style("height: 220px")

    # ---------------------------------------------------------------- C. Đối thủ
    def section_c(comp: dict):
        with ui.element("div").classes("sr-card sr-rd-card"):
            with ui.row().classes("w-full items-center gap-2 no-wrap q-mb-sm"):
                ui.label("Vị thế cạnh tranh").classes("sr-bx-title")
                T.info_icon(ui, "Vị thế cạnh tranh", (
                    "Thị phần hiển thị: phần của website dự án trong tổng độ hiển thị (tỷ lệ nhấp ước tính theo vị trí) "
                    "của các thương hiệu đang theo dõi.",
                    "Đối thủ vừa vượt: từ khóa mà lần check trước đối thủ chưa đứng trên website dự án, lần này đứng "
                    "trên."))
                ui.space()
                ui.button("Tab Đối thủ →", on_click=lambda: open_set(-1)).props(
                    "flat dense no-caps color=primary").classes("sr-rd-link")
            if "invalid" in comp:
                with ui.row().classes("items-start no-wrap gap-2 sr-rd-note"):
                    ui.icon("info", size="18px").classes("muted")
                    ui.label(comp["invalid"]).classes("text-sm")
                return
            own, lead = comp["own"], comp["leader"]
            with ui.element("div").classes("sr-rd-comp"):
                with ui.column().classes("gap-0"):
                    ui.label("Thị phần hiển thị").classes("sr-rd-lab")
                    ui.label(f"{own['share'] * 100:.0f}%" if own else "–").classes("sr-rd-num")
                    ui.label(f"Hạng {own['place']}/{comp['brands']} thương hiệu" if own else "").classes(
                        "sr-rd-sub")
                with ui.column().classes("gap-0"):
                    ui.label("Dẫn đầu").classes("sr-rd-lab")
                    if lead and lead is not own:
                        ui.label(lead["brand"]["name"]).classes("sr-rd-lead ellipsis")
                        ui.label(f"{lead['share'] * 100:.0f}% thị phần").classes("sr-rd-sub")
                    else:
                        ui.label("Website dự án").classes("sr-rd-lead good")
            fresh = comp["overtaken"]
            with ui.row().classes("items-center no-wrap gap-2 sr-rd-line"):
                ui.label("Đối thủ vừa vượt").classes("sr-rd-lab col")
                if fresh is None:
                    ui.label("chưa đủ dữ liệu so sánh").classes("sr-rd-sub neutral")
                else:
                    n_kw = len({x["kid"] for x in fresh})
                    ui.label(f"{n_kw} từ khóa" if n_kw else "0").classes("sr-rd-v " + ("bad" if n_kw else "zero"))
            ui.label(f"Trên {comp['keywords']}/{comp['total']} từ khóa có kết quả Google"
                     + (f" · so sánh được {comp['compared']}" if comp["compared"] else "")).classes(
                "sr-rd-sub neutral q-mt-xs")

    # ---------------------------------------------------------------- D. Điều cần chú ý
    def section_d(ins: list[dict], k: dict):
        with ui.element("div").classes("sr-card sr-rd-card"):
            with ui.row().classes("w-full items-center gap-2 no-wrap q-mb-sm"):
                ui.label("Điều cần chú ý").classes("sr-bx-title")
                T.info_icon(ui, "Điều cần chú ý", (
                    "Tối đa 5 điều quan trọng nhất so với lần check trước, nặng trước. Bấm để xem danh sách từ khóa.",
                    "Chỉ tính từ khóa có lần check trước."))
            if not k["history"]:
                ui.label("Chưa có lần check thứ hai để so: điều cần chú ý sẽ hiện sau lần check tới.").classes(
                    "text-sm muted")
                return
            if not ins:
                with ui.row().classes("items-center no-wrap gap-2"):
                    ui.icon("check_circle", size="20px").style(f"color:{TONE_COLORS['good']}")
                    ui.label("Không có biến động đáng chú ý so với lần check trước.").classes("text-sm")
                return
            for it in ins:
                row = ui.element("button").classes("sr-rd-ins").props('type="button"')
                with row:
                    ui.element("i").classes("dot").style(f"background:{TONE_COLORS[it['tone']]}")
                    with ui.column().classes("gap-0 col"):
                        ui.label(it["title"]).classes("t")
                        ui.label(it["detail"]).classes("d")
                    ui.icon("chevron_right", size="18px").classes("muted")
                row.on("click", lambda _, it=it: keyword_dialog(it))

    def keyword_dialog(it: dict):
        with ui.dialog() as d, ui.card().style("min-width: 560px; max-width: 94vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label(it["title"]).classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=d.close).props("flat round dense")
            cols = [{"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
                    {"name": "set", "label": "Bộ", "field": "set", "align": "left", "sortable": True},
                    {"name": "prev", "label": "Đối thủ" if it.get("rival") else "Trước", "field": "prev",
                     "align": "center"},
                    {"name": "now", "label": "Hạng đối thủ" if it.get("rival") else "Nay", "field": "now",
                     "align": "center"}]
            t = ui.table(columns=cols, rows=[{**x, "_i": i} for i, x in enumerate(it["keywords"])], row_key="_i",
                         pagination=12).classes("w-full").props("flat dense")
            t.on("rowClick", lambda e: (d.close(), open_set(int(e.args[1]["set_id"]))))
            ui.label("Bấm một dòng để mở bộ chứa từ khóa.").classes("text-xs muted")
        d.open()

    # ---------------------------------------------------------------- E. Bộ từ khóa
    def section_e(sets_: list[dict]):
        with ui.element("div").classes("sr-card sr-rd-card"):
            with ui.row().classes("w-full items-center gap-2 no-wrap q-mb-sm"):
                ui.label(f"Bộ từ khóa · {len(sets_)}").classes("sr-bx-title")
                ui.space()
                ui.button(f"Xem tất cả bộ từ khóa ({len(sets_)}) →", on_click=lambda: all_sets_dialog(sets_)).props(
                    "flat dense no-caps color=primary").classes("sr-rd-link")
            set_table(sets_[:SHOW_SETS])
            if len(sets_) > SHOW_SETS:
                ui.label(f"Đang hiện {SHOW_SETS} bộ cần chú ý trước.").classes("sr-rd-sub neutral q-mt-xs")

    def set_table(sets_: list[dict], filter_bind=None):
        cols = [{"name": "name", "label": "Bộ", "field": "name", "align": "left", "sortable": True},
                {"name": "total", "label": "Từ khóa", "field": "total", "align": "right", "sortable": True},
                {"name": "top3", "label": "Top 3", "field": "top3", "align": "right", "sortable": True},
                {"name": "top5", "label": "Top 5", "field": "top5", "align": "right", "sortable": True},
                {"name": "top10", "label": "Top 10", "field": "top10", "align": "right", "sortable": True},
                {"name": "alert", "label": "Cần chú ý", "field": "alert", "align": "left"}]
        rows = [{**s, "alert": (s["attention"] or {}).get("text", ""),
                 "tone": (s["attention"] or {}).get("tone", "grey"),
                 "kind_cls": "kpi" if s["kind"] == "Cam kết" else "track"} for s in sets_]
        t = ui.table(columns=cols, rows=rows, row_key="id", pagination=0 if len(rows) <= 15 else 15).classes(
            "w-full sr-rd-sets").props("flat dense" + (" hide-bottom" if len(rows) <= 15 else ""))
        t.add_slot("body-cell-name", r"""<q-td :props="props"><div class="row no-wrap items-center" style="gap:6px">
            <b class="ellipsis">{{ props.row.name }}</b>
            <span :class="'sr-set-tag ' + props.row.kind_cls">{{ props.row.kind }}</span></div></q-td>""")
        t.add_slot("body-cell-alert", r"""<q-td :props="props">
            <span :class="'sr-rd-alert ' + props.row.tone">{{ props.value }}</span></q-td>""")
        t.on("rowClick", lambda e: open_set(int(e.args[1]["id"])))
        if filter_bind is not None:
            filter_bind.bind_value(t, "filter")
        return t

    def all_sets_dialog(sets_: list[dict]):
        with ui.dialog() as d, ui.card().style("min-width: 760px; max-width: 96vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.label(f"Tất cả bộ từ khóa · {len(sets_)}").classes("text-lg font-semibold col")
                q = ui.input(placeholder="Tìm bộ…").props("dense outlined clearable").classes("w-56")
                ui.button(icon="close", on_click=d.close).props("flat round dense")
            set_table(sets_, filter_bind=q)
        d.open()

    body()
