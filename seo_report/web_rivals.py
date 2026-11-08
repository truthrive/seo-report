"""Trang Đối thủ (/doi-thu, nhóm SEO): quản lý danh sách đối thủ (tối đa 10, dùng chung với AI Overview) và tổng
quan đối thủ trên bộ từ khóa: thị phần hiển thị, xu hướng, so sánh theo từng từ khóa, đối thủ vừa vượt mình.

Mọi số lấy từ trang kết quả Google đã lưu khi check rank (không tốn thêm phí), trong độ sâu đã check.
"""
from . import aio as AO
from . import keywords as K
from . import rank as R
from . import intent as IN
from . import rank_overview as RO

DASHES = ["solid", "dashed", "dotted"]  # đường của mình liền; đối thủ khác nhau cả kiểu nét, không chỉ màu


def _vn(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def build_rivals_panel(ui, cfg, connect, user, open_set) -> None:
    from nicegui import background_tasks

    from . import ui_theme as T
    from .access import can_edit
    from .web_rank import _competitors_block, icon_btn
    ed = can_edit(user)
    site = cfg.site_url
    with connect() as c:
        end = K.latest_date(c, site)
        sets_ = [x for x in R.sets(c, site) if not x["draft"]]
    state = {"set": 0, "only_ahead": False, "mx_set": 0, "mx_hide": set()}

    # hộp thoại đặt ở đây, ngoài các khối vẽ lại (roster / overview): vẽ lại khối không làm đóng hộp thoại đang mở
    dialog_host = ui.element("div").classes("hidden")

    # ------------------------------------------------------------------ danh sách đối thủ
    @ui.refreshable
    def roster():
        with connect() as c:
            bs = AO.brands(c, cfg)
            sug = RO.rank_suggestions(c, cfg, end)
        n_comp = len(bs) - 1
        full = n_comp >= AO.MAX_COMPETITORS
        if any(b.get("logo") is None and not b["own"] for b in bs):
            background_tasks.create(load_logos())
        with ui.element("div").classes("sr-card q-pa-md w-full"):
            with ui.row().classes("w-full items-center gap-2 no-wrap q-mb-sm"):
                with ui.element("span").classes("sr-bx-icon").style("background:#EEF2FB"):
                    ui.icon("groups", size="16px").style("color:#2a78d6").props('aria-hidden="true"')
                ui.label(f"Đối thủ theo dõi · {n_comp}/{AO.MAX_COMPETITORS}").classes("sr-bx-title")
                T.info_icon(ui, "Đối thủ theo dõi", (
                    "Một danh sách cho cả dự án, dùng chung cho thứ hạng và trang AI Overview.",
                    "Nhận đối thủ theo tên miền trong kết quả Google; cách gọi khác dùng để nhận tên trong câu trả "
                    "lời AI Overview (số \"Được nhắc\").",
                    "Rê chuột lên từng tên để xem cách gọi và tên miền."))
                ui.space()
                if ed and not full:
                    ui.button("Thêm đối thủ", icon="add", on_click=lambda: edit(None)).props(
                        "unelevated no-caps color=primary")
            with ui.element("div").classes("sr-rival-list"):
                for b in bs:
                    with ui.element("div").classes("sr-rival" + (" own" if b["own"] else "")) as chip:
                        with ui.element("span").classes("sr-brand-logo sr-logo-sm"):
                            if b.get("logo"):
                                ui.html(f'<img src="{b["logo"]}" alt="">')
                            else:
                                ui.label((b["name"] or "?")[:1].upper())
                        ui.element("i").classes("sr-brand-dot").style(
                            f"background:{b['color'] if b['own'] or b['charted'] else AO.OTHER_COLOR}")
                        ui.label(b["name"]).classes("ellipsis")
                        if ed and not b["aliases"]:  # thiếu cách gọi: AI Overview chỉ nhận ra tên miền, "Được nhắc" thấp
                            ui.icon("error_outline", size="16px").classes("sr-rival-warn").props(
                                'aria-label="Chưa có cách gọi"')
                        if ed:
                            icon_btn(ui, "edit", f"Sửa {b['name']}", lambda _, b=b: edit(b))
                            if not b["own"]:
                                icon_btn(ui, "close", f"Bỏ theo dõi {b['name']}", lambda _, b=b: drop(b))
                    chip.tooltip("Cách gọi: " + (", ".join(b["aliases"]) or "chưa thêm"
                                                 + (" (AI Overview chỉ nhận ra tên miền, bấm ✏️ để thêm)" if ed else ""))
                                 + " · Tên miền: " + (", ".join(b["domains"]) or "chưa có"))
            if full:
                ui.label(f"Đã đủ {AO.MAX_COMPETITORS} đối thủ: bỏ bớt một đối thủ để thêm mới.").classes(
                    "text-xs muted q-mt-sm")
            if ed and (sug or n_comp):
                with ui.row().classes("items-center gap-2 q-mt-md"):
                    ui.button("Chọn đối thủ từ gợi ý", icon="swap_horiz", on_click=lambda: transfer_dialog()).props(
                        "outline no-caps color=grey-9")
                    if sug:
                        ui.label(f"{len(sug)} website hay vào top 10 của bộ từ khóa chưa được theo dõi").classes(
                            "text-xs muted")

    async def load_logos() -> None:
        from contextlib import closing

        from nicegui import run

        from . import db

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                return AO.fill_logos(c, cfg)
        try:
            if await run.io_bound(work):
                roster.refresh()
        except Exception:  # noqa: BLE001  (website không mở được: giữ chữ cái đầu)
            pass

    def changed():
        roster.refresh()
        overview.refresh()
        background_tasks.create(load_logos())

    def transfer_data(con) -> tuple[list[dict], list[str]]:
        """Khung trái: website hay vào top 10 (chưa theo dõi). Khung phải: đối thủ đang theo dõi."""
        bs = [b for b in AO.brands(con, cfg) if not b["own"]]
        sug = RO.rank_suggestions(con, cfg, end, limit=30)
        data = [{"key": f"b:{b['id']}", "title": b["name"], "description": ", ".join(b["domains"])} for b in bs]
        data += [{"key": f"d:{d_}", "title": d_, "description": f"Có mặt ở top 10 của {n} từ khóa"} for d_, n in sug]
        return data, [f"b:{b['id']}" for b in bs]

    def transfer_dialog():
        from .pickers import Transfer
        with connect() as c:
            data, keys = transfer_data(c)
        with dialog_host, ui.dialog() as dlg, ui.card().style("width: 760px; max-width: 96vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label("Chọn đối thủ theo dõi").classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')
            ui.label(f"Đánh dấu website rồi bấm Thêm / Bỏ. Tối đa {AO.MAX_COMPETITORS} đối thủ; danh sách dùng chung cho "
                     "Thứ hạng và AI Overview.").classes("text-sm muted")

            def apply(direction: str, move_keys: list, _target: list) -> None:
                if direction == "right":
                    added = []
                    with connect() as c:
                        for k in move_keys:
                            try:
                                if k.startswith("d:"):
                                    AO.add_or_restore(c, site, k[2:])
                                    added.append(k[2:])
                            except ValueError as e:
                                ui.notify(str(e), type="warning", position="bottom-right", classes="sr-toast")
                                break
                    if added:
                        ui.notify(f"Đã thêm {len(added)} đối thủ", type="positive", position="bottom-right",
                                  classes="sr-toast")
                    refresh()
                    return
                ids = [int(k[2:]) for k in move_keys if k.startswith("b:")]
                names = [x["title"] for x in tf._props["data"] if x["key"] in move_keys]
                with dialog_host, ui.dialog() as cd, ui.card().style("max-width: 440px; border-radius: 14px"):
                    ui.label(f"Bỏ theo dõi {len(ids)} đối thủ?").classes("text-lg font-semibold")
                    ui.label(", ".join(names)).classes("text-sm")
                    ui.label("Thôi so sánh ở thứ hạng và AI Overview. Thêm lại lúc nào cũng được: tên và cách gọi đã "
                             "sửa vẫn được giữ.").classes("text-sm muted")
                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button("Hủy", on_click=cd.close).props("flat no-caps")

                        def go():
                            with connect() as c:
                                for i in ids:
                                    AO.remove_brand(c, site, i)
                            cd.close()
                            ui.notify(f"Đã bỏ {len(ids)} đối thủ", type="info", position="bottom-right",
                                      classes="sr-toast")
                            refresh()
                        ui.button("Bỏ theo dõi", on_click=go).props("unelevated no-caps color=negative")
                cd.open()

            def refresh():
                with connect() as c:
                    d2, k2 = transfer_data(c)
                tf.set_data(d2, k2)
                changed()

            tf = Transfer(data, keys, titles=("Gợi ý từ top 10", "Đang theo dõi"), operations=("Thêm", "Bỏ"),
                          empty_text=("Không còn website gợi ý", "Chưa theo dõi đối thủ nào"), unit="website",
                          max_target=AO.MAX_COMPETITORS, on_change=apply).classes("w-full q-mt-sm")
        dlg.on("hide", lambda: dlg.delete())
        dlg.open()

    def quick_add(d_: str):
        if not ed:
            return
        try:
            with connect() as c:
                AO.save_brand(c, site, d_, "", d_)
        except ValueError as e:
            ui.notify(str(e), type="warning")
            return
        ui.notify(f"Đã thêm {d_}", type="positive", position="bottom-right", classes="sr-toast")
        changed()

    def drop(b: dict):
        if not ed:
            return
        with ui.dialog() as d, ui.card().style("max-width: 420px; border-radius: 14px"):
            ui.label(f"Bỏ theo dõi {b['name']}?").classes("text-lg font-semibold")
            ui.label("Thôi so sánh đối thủ này ở thứ hạng và AI Overview. Thêm lại lúc nào cũng được, số liệu tính lại "
                     "từ kết quả đã lưu.").classes("text-sm")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")

                def go():
                    with connect() as c:
                        AO.remove_brand(c, site, b["id"])
                    d.close()
                    changed()
                ui.button("Bỏ theo dõi", on_click=go).props("unelevated no-caps color=negative")
        d.open()

    def edit(b: dict | None):
        if not ed:
            return
        with ui.dialog() as d, ui.card().style("min-width: 460px; max-width: 94vw; border-radius: 14px"):
            ui.label("Sửa thương hiệu" if b else "Thêm đối thủ").classes("text-lg font-semibold")
            name = ui.input("Tên", value=b["name"] if b else "").props("outlined dense").classes("w-full")
            domains = ui.textarea("Tên miền (mỗi dòng một tên miền)", value="\n".join(b["domains"]) if b else ""
                                  ).props("outlined dense autogrow").classes("w-full")
            aliases = ui.textarea("Cách gọi khác (mỗi dòng một cách, dùng cho AI Overview)",
                                  value="\n".join(b["aliases"]) if b else "").props(
                "outlined dense autogrow").classes("w-full")

            def save():
                try:
                    with connect() as c:
                        AO.save_brand(c, site, name.value or "", aliases.value or "", domains.value or "",
                                      b["id"] if b else None)
                except ValueError as e:
                    ui.notify(str(e), type="warning", position="bottom-right", classes="sr-toast")
                    return
                d.close()
                changed()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Lưu", on_click=save).props("unelevated no-caps color=primary")
        d.open()

    roster()

    # ------------------------------------------------------------------ chọn phạm vi (đặt trong khung đối thủ)
    def scope_toggle():
        if len(sets_) < 2:
            return
        ui.label("Tính trên").classes("text-sm muted")
        ui.toggle({0: "Mọi bộ", **{x["id"]: x["name"] for x in sets_}}, value=state["set"],
                  on_change=lambda e: (state.update(set=e.value, mx_set=e.value), overview.refresh())).props(
            "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes("sr-seg")

    # ------------------------------------------------------------------ tổng quan, xu hướng, so sánh
    @ui.refreshable
    def overview():
        sid = state["set"] or None
        with connect() as c:
            comp = RO.competitors(c, cfg, end, set_id=sid)
            trend = RO.visibility_trend(c, cfg, end, set_id=sid)
            cards = RO.set_rows(c, site, end, cfg.rank)
        _competitors_block(ui, comp, cards, lambda i: open_set(i), header_extra=scope_toggle,
                           empty_hint="Thêm tối đa 10 đối thủ ở phần bên trên." if ed else
                           "Danh sách đối thủ sẽ hiện ở đây khi được thêm.")
        if len([r for r in comp["rows"] if not r["brand"]["own"]]) == 0:
            return
        sov_card(sid)
        trend_card(trend, comp)
        matrix_view()

    def sov_card(sid) -> None:
        """Thị phần lượt click ước tính (volume × CTR theo vị trí) và giá trị quy ra tiền Google Ads."""
        from . import keyword_research as KR
        from . import seo_value as SV
        with connect() as c:
            sov = SV.share_of_voice(c, cfg, end, set_id=sid)
            trend = SV.sov_trend(c, cfg, end, set_id=sid)
        if not sov["keywords"]:
            return
        cur = sov["currency"]
        with ui.element("div").classes("sr-card q-pa-md w-full q-mt-md"):
            with ui.row().classes("w-full items-center gap-2 no-wrap q-mb-xs"):
                with ui.element("span").classes("sr-bx-icon").style("background:#EEF6EF"):
                    ui.icon("pie_chart", size="16px").style("color:#1E7C31").props('aria-hidden="true"')
                ui.label("Thị phần lượt click ước tính").classes("sr-bx-title")
                T.info_icon(ui, "Thị phần lượt click ước tính", (
                    "Phần lượt click (từ kết quả tự nhiên trang 1) mỗi thương hiệu nhận được trên bộ từ khóa.",
                    "Khác độ hiển thị ở trên: từ khóa nhiều người tìm nặng ký hơn từ khóa ít người tìm.",
                    "Click ước tính = volume tháng (Google Ads) × tỷ lệ nhấp theo vị trí ở lần check gần nhất. "
                    "Giá trị = click × giá thầu Google Ads của từ khóa."))
            ui.label(f"Tính trên {sov['keywords']}/{sov['total']} từ khóa có volume · tổng khoảng "
                     f"{sov['market']:,} click trang 1 mỗi tháng".replace(",", ".")
                     + (f" · {sov['no_volume']} từ khóa gần như không ai tìm nên không tính" if sov["no_volume"]
                        else "")).classes("text-xs muted q-mb-sm")
            rows = [{"id": i, "name": r["brand"]["name"], "own": r["brand"]["own"], "clicks": r["clicks"],
                     "share": round(r["share"] * 100, 1), "value": r["value"], "value_t": KR.money(r["value"], cur),
                     "kws": r["keywords"], "chg": None if r["change"] is None else round(r["change"] * 100, 1),
                     "color": r["brand"]["color"]} for i, r in enumerate(sov["rows"])]
            mx = max((r["share"] for r in rows), default=1) or 1
            tb = ui.table(columns=[
                {"name": "name", "label": "Thương hiệu", "field": "name", "align": "left"},
                {"name": "share", "label": "Thị phần click", "field": "share", "align": "left"},
                {"name": "clicks", "label": "Click ước tính / tháng", "field": "clicks", "align": "right",
                 ":format": "v => v.toLocaleString('vi-VN')"},
                {"name": "value", "label": "Giá trị / tháng", "field": "value", "align": "right"},
                {"name": "kws", "label": "Số từ khóa có mặt", "field": "kws", "align": "right"},
            ], rows=rows, row_key="id").props("flat dense").classes("w-full sr-bl-table")
            tb.add_slot("body-cell-name", """
                <q-td :props="props"><span class="sr-kr-dot" :style="{background: props.row.color}"></span>
                  <b v-if="props.row.own">{{ props.value }}</b><span v-else>{{ props.value }}</span></q-td>""")
            tb.add_slot("body-cell-share", """
                <q-td :props="props"><div class="sr-bar"><div class="sr-bar-fill"
                  :style="{width: Math.max(2, 120 * props.value / %s) + 'px', background: props.row.color}"></div>
                  <span class="num">{{ props.value.toLocaleString('vi-VN') }}%%</span>
                  <span v-if="props.row.chg !== null && Math.abs(props.row.chg) >= 0.1" class="sr-op-move"
                    :class="props.row.chg > 0 ? 'up' : 'down'">{{ props.row.chg > 0 ? '▲' : '▼' }}{{
                    Math.abs(props.row.chg).toLocaleString('vi-VN') }}<q-tooltip>So với lần check trước, cùng tập từ
                    khóa (điểm phần trăm)</q-tooltip></span></div></q-td>""" % mx)
            tb.add_slot("body-cell-value", """
                <q-td :props="props"><span class="num">{{ props.row.value_t }}</span></q-td>""")
            most = max((p["n"] for p in trend), default=0)
            trend = [p for p in trend if p["n"] * 2 >= most]
            if len(trend) >= 2:
                brands = [r["brand"] for r in sov["rows"]]
                ui.echart({
                    "tooltip": {"trigger": "axis", "valueFormatter": None},
                    "legend": {"type": "scroll", "bottom": 0},
                    "grid": {"left": 40, "right": 16, "top": 16, "bottom": 48},
                    "xAxis": {"type": "category", "data": [_vn(p["date"])[:5] for p in trend],
                              "axisLabel": {"color": "#6B6A5E"}},
                    "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%", "color": "#6B6A5E"},
                              "splitLine": {"lineStyle": {"color": "#EEECE4"}}},
                    "series": [{"name": b["name"], "type": "line", "symbol": "circle", "symbolSize": 6,
                                "lineStyle": {"width": 3 if b["own"] else 2,
                                              "type": "solid" if b["own"] else DASHES[i % len(DASHES)],
                                              "color": b["color"]}, "itemStyle": {"color": b["color"]},
                                "data": [round(p["share"].get(b["id"], 0) * 100, 1) for p in trend]}
                               for i, b in enumerate(brands)]}).classes("w-full q-mt-sm").style("height: 260px")

    def trend_card(trend: list[dict], comp: dict):
        with ui.element("div").classes("sr-card q-pa-md w-full q-mt-md"):
            with ui.row().classes("w-full items-center gap-2 no-wrap q-mb-sm"):
                with ui.element("span").classes("sr-bx-icon").style("background:#EEF6EF"):
                    ui.icon("show_chart", size="16px").style("color:#1E7C31").props('aria-hidden="true"')
                ui.label("Xu hướng độ hiển thị").classes("sr-bx-title")
            # lần check quá ít từ khóa (ví dụ check thử vài từ) làm % nhảy vọt: bỏ, chỉ giữ lần có ≥ nửa số từ khóa
            most = max((p["n"] for p in trend), default=0)
            trend = [p for p in trend if p["n"] * 2 >= most]
            if len(trend) < 2:
                ui.label("Biểu đồ hiện khi có từ 2 lần check đủ bộ từ khóa có kết quả Google.").classes(
                    "text-sm muted")
                return
            brands = sorted((r["brand"] for r in comp["rows"]), key=lambda b: not b["own"])  # dự án trước
            series = []
            for i, b in enumerate(brands):
                color = b["color"] if b["own"] or b["charted"] else AO.OTHER_COLOR
                series.append({"name": b["name"], "type": "line", "symbol": "circle", "symbolSize": 7,
                               "lineStyle": {"width": 3 if b["own"] else 2,
                                             "type": "solid" if b["own"] else DASHES[(i - 1) % len(DASHES)],
                                             "color": color},
                               "itemStyle": {"color": color},
                               "emphasis": {"focus": "series"},
                               "data": [round(p["vis"].get(b["id"], 0) * 100, 1) for p in trend]})
            ui.echart({
                "tooltip": {"trigger": "axis"},
                "legend": {"type": "scroll", "bottom": 0},
                "grid": {"left": 40, "right": 16, "top": 16, "bottom": 48},
                "xAxis": {"type": "category", "data": [f"{_vn(p['date'])[:5]} ({p['n']} từ khóa)" for p in trend],
                          "axisLabel": {"color": "#6B6A5E"}},
                "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%", "color": "#6B6A5E"},
                          "splitLine": {"lineStyle": {"color": "#EEECE4"}}},
                "series": series}).classes("w-full").style("height: 300px")
            ui.label("Mỗi điểm chỉ tính các từ khóa có kết quả Google ở lần check đó (số trong ngoặc).").classes(
                "text-xs muted")

    @ui.refreshable
    def matrix_view():
        """Bảng so sánh có tab nhỏ theo bộ (độc lập với phần trên) và nút xuất dữ liệu để nghiên cứu."""
        from .web_export import export_menu
        sid = state["mx_set"] or None
        with connect() as c:
            matrix = RO.keyword_matrix(c, cfg, end, set_id=sid)
        brands = matrix["brands"]
        own_name = next((b["name"] for b in brands if b["own"]), "dự án")
        rows = [r for r in matrix["rows"] if r["ahead"] or not state["only_ahead"]]
        with ui.element("div").classes("sr-card q-pa-md w-full q-mt-md"):
            with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
                with ui.element("span").classes("sr-bx-icon").style("background:#FBF1DE"):
                    ui.icon("table_rows", size="16px").style("color:#B7791F").props('aria-hidden="true"')
                ui.label("So sánh theo từ khóa").classes("sr-bx-title")
                ui.space()
                ui.switch(f"Chỉ từ khóa đối thủ xếp trên {own_name}", value=state["only_ahead"],
                          on_change=lambda e: (state.update(only_ahead=e.value), matrix_view.refresh())).props("dense")
                export_menu(ui, cfg, connect, f"vi-tri-doi-thu_tat-ca-bo_{end}", export_xlsx,
                            label="Xuất vị trí mọi bộ (Excel)", user=user, icon_only=True,
                            category="rivals")
            tools = ui.element("div").classes("sr-mx-tools w-full")  # một thanh: bộ từ khóa (trái) · đối thủ (phải)
            with tools:
                if len(sets_) > 1:
                    ui.toggle({0: "Mọi bộ", **{x["id"]: x["name"] for x in sets_}}, value=state["mx_set"],
                              on_change=lambda e: (state.update(mx_set=e.value), matrix_view.refresh())).props(
                        "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                        "sr-seg")
                else:
                    ui.element("span")
            if not matrix["rows"]:
                ui.label("Chưa có từ khóa nào có kết quả Google.").classes("text-sm muted")
                return
            cols = [{"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
                    {"name": "volume", "label": "Volume", "field": "volume", "align": "right", "sortable": True},
                    {"name": "intent", "label": "Ý định", "field": "intent", "align": "center", "sortable": True}]
            for b in brands:
                cols.append({"name": f"b{b['id']}", "label": b["name"], "field": f"b{b['id']}", "align": "center",
                             "sortable": True, "headerClasses": "sr-mx-head"})
            data = []
            for r in rows:
                row = {"id": r["id"], "keyword": r["keyword"], "set": r["set"], "set_id": r["set_id"],
                       "seen": r["seen"], "volume": r["volume"] if r["volume"] is not None else -1,
                       "intent": r["intent"][0],
                       "intent2": [c_ for c_, _ in (r["intent"][2] if len(r["intent"]) > 2 else [])],
                       "intent_tip": IN.tip(r["intent"]),
                       "aio": r["aio"], "aio_own": r["aio_own"],
                       "aio_tip": ("Có AI Overview · trích: " + ", ".join(r["aio_brands"])) if r["aio_brands"]
                       else ("Có AI Overview, chưa trích thương hiệu nào đang theo dõi" if r["aio"] else "")}
                for b in brands:
                    v = r["ranks"].get(b["id"])
                    row[f"b{b['id']}"] = v if v is not None else 999
                data.append(row)
            rivals_ = [b for b in brands if not b["own"]]
            own_key = next((f"b{b['id']}" for b in brands if b["own"]), "")

            def visible(hidden: set) -> list[str]:
                return [c_["name"] for c_ in cols if not (c_["name"].startswith("b") and c_["name"] != own_key
                                                          and int(c_["name"][1:]) in hidden)]

            def pick_cols(e) -> None:
                state["mx_hide"] = {b["id"] for b in rivals_} - set(e.value or [])
                t.props["visible-columns"] = visible(state["mx_hide"])
                t.update()
            if rivals_:
                from .pickers import MultiSelect
                with tools:
                    MultiSelect({b["id"]: b["name"] for b in rivals_}, label="Cột đối thủ",
                                value=[b["id"] for b in rivals_ if b["id"] not in state["mx_hide"]],
                                placeholder="Gõ tên đối thủ", chips_when_all=False, inline=True, pop_right=True,
                                on_change=pick_cols)
            t = ui.table(columns=cols, rows=data, row_key="id", pagination=20).classes(
                "w-full sr-matrix").props("flat dense")
            t.props["visible-columns"] = visible(state["mx_hide"])
            t.add_slot("body-cell", r"""
              <q-td :props="props" :class="props.col.name === '""" + own_key + r"""' ? 'mx-own' : ''">
                <template v-if="props.col.name === 'keyword'">
                  <div class="row items-center no-wrap" style="gap:6px">
                    <span class="text-weight-medium">{{ props.row.keyword }}</span>
                    <q-icon v-if="props.row.aio" name="auto_awesome" size="16px"
                            :class="props.row.aio_own ? 'mx-aio own' : 'mx-aio'">
                      <q-tooltip>{{ props.row.aio_tip }}</q-tooltip></q-icon></div>
                  <div class="text-caption muted">{{ props.row.set }}</div></template>
                <template v-else-if="props.col.name === 'intent'"><span v-if="props.row.intent"
                    :class="'sr-intent ' + props.row.intent">{{ props.row.intent }}<q-tooltip>{{ {'I': 'Informational (Thông tin)', 'N': 'Navigational (Điều hướng)', 'C': 'Commercial (Cân nhắc mua)', 'T': 'Transactional (Mua / giao dịch)'}[props.row.intent] }}</q-tooltip></span></template>
                <template v-else-if="props.col.name === 'volume'">
                  <span v-if="props.value >= 0" class="num">{{ props.value.toLocaleString('vi-VN') }}</span>
                  <span v-else class="muted">–</span></template>
                <span v-else-if="props.value === 999" class="muted">–</span>
                <span v-else :class="'mx-rank ' + (props.value <= 3 ? 'r3' : props.value <= 10 ? 'r10' : 'r20')">
                  {{ props.value }}</span>
              </q-td>""")
            t.on("rowClick", lambda e: open_set(int(e.args[1]["set_id"])))
            ui.label("Số = vị trí trên Google ở lần check gần nhất; – = không có trong độ sâu đã check. ✦ = từ khóa có "
                     "AI Overview (tím đậm: website dự án được trích). Volume: lượt tìm mỗi tháng (Google Ads). Bấm một "
                     "dòng để mở bộ chứa từ khóa. Ý định tìm kiếm: I thông tin · N tìm đúng thương hiệu / website · "
                     "C cân nhắc mua · T sẵn sàng mua.").classes("text-xs muted")

    def export_xlsx() -> bytes:
        with connect() as c:
            return RO.competitor_workbook(c, cfg, end)

    overview()
