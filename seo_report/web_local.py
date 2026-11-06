"""Trang Local SEO (/local): hồ sơ Google Business Profile của dự án (một hoặc nhiều chi nhánh).

Tab Tổng quan (lượt xem, cuộc gọi, chỉ đường, click website, tin nhắn; xu hướng; từng chi nhánh) · Từ khóa (từ khóa
người dùng tìm rồi thấy hồ sơ, theo tháng) · Kiểm tra hồ sơ (thông tin còn thiếu / sai).
Khách hàng xem được; người sửa được mới gắn chi nhánh và bấm lấy số mới (API miễn phí).
"""
import io
from datetime import date, timedelta

from . import access as A
from . import ai_format as F
from . import gbp as G
from . import ui_theme as T

PERIODS = {28: "28 ngày", 90: "90 ngày", 365: "12 tháng"}
TABS = (("overview", "Tổng quan"), ("keywords", "Từ khóa"), ("audit", "Kiểm tra hồ sơ"))
LEVELS = {"high": ("Cần sửa", "red", "error"), "medium": ("Nên sửa", "amber", "warning"),
          "info": ("Tham khảo", "blue", "info"), "ok": ("Ổn", "green", "check_circle")}


def _vn(d: date) -> str:
    return f"{d:%d/%m/%Y}"


def build_local_page(ui, cfg, connect, user, start: str = "") -> None:
    from nicegui import run

    from . import auth
    site = cfg.site_url
    ed = A.can_edit(user)
    right = T.page_header(ui, "storefront", "Local SEO",
                          "Hồ sơ Google Business Profile: khách thấy hồ sơ bao nhiêu lần, gọi, chỉ đường, vào website; "
                          "từ khóa tìm thấy hồ sơ và thông tin còn thiếu. Số của Google, tự lấy mỗi ngày.")
    state = {"tab": start if start in dict(TABS) else "overview", "loc": "all", "days": 28, "month": "", "q": ""}
    has_scope = not auth.missing_scopes(_scopes(cfg), (auth.BUSINESS_SCOPE,))

    async def fetch(btn) -> None:
        if not ed:
            return
        from contextlib import closing

        from . import db
        btn.props("loading")

        def work():
            logs: list[str] = []
            with closing(db.connect(cfg.db_path)) as c:
                r = G.refresh(c, cfg, log=logs.append)
            return r, [m for m in logs if m.startswith("Không")]
        try:
            r, bad = await run.io_bound(work)
            ui.notify(f"Đã lấy số {r['locations']} hồ sơ" + (f" ({len(bad)} lỗi)" if bad else ""),
                      caption=" · ".join(bad)[:300] or None, type="warning" if bad else "positive",
                      position="bottom-right", classes="sr-toast", multi_line=True)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify("Không lấy được số Google Business Profile", caption=G.explain(e), type="negative",
                      position="bottom-right", classes="sr-toast", timeout=0, close_button="Đóng")
        btn.props(remove="loading")
        body.refresh()

    async def link_dialog() -> None:
        """Chọn các hồ sơ (chi nhánh) thuộc dự án này trong danh sách hồ sơ tài khoản Google của tool quản lý."""
        if not ed:
            return
        with ui.dialog() as dlg, ui.card().style("border-radius:14px; width:620px; max-width:94vw"):
            ui.label("Gắn chi nhánh Google Business Profile").classes("text-base font-semibold")
            ui.label("Danh sách hồ sơ tài khoản Google của tool đang quản lý. Chọn các chi nhánh của website này.") \
                .classes("text-xs muted")
            box = ui.column().classes("w-full gap-1 q-mt-sm")
            with box, ui.row().classes("items-center gap-2"):
                ui.spinner(size="20px")
                ui.label("Đang đọc danh sách hồ sơ từ Google…").classes("text-sm muted")
            foot = ui.row().classes("w-full justify-end gap-2 q-mt-sm")
        dlg.open()

        def load():
            return G.all_locations(G.Client(auth.get_credentials(cfg, need=(auth.BUSINESS_SCOPE,))))
        try:
            locs = await run.io_bound(load)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            box.clear()
            with box:
                ui.label(f"Không đọc được danh sách hồ sơ. {G.explain(e)}").classes("text-sm").style(
                    f"color:{T.RED}")
            with foot:
                ui.button("Đóng", on_click=dlg.close).props("flat no-caps")
            return
        with connect() as c:
            current = {x["name"] for x in G.linked(c)}
        from .projects import domain
        want = domain(site)
        box.clear()
        checks = {}
        with box:
            if not locs:
                ui.label("Tài khoản Google của tool chưa quản lý hồ sơ nào. Thêm email tool làm người quản lý hồ sơ "
                         "trong Google Business Profile.").classes("text-sm muted")
            for x in locs:
                match = bool(x["website"]) and (domain(x["website"]) == want or domain(x["website"]).endswith("." + want))
                with ui.row().classes("items-start no-wrap gap-2 w-full sr-access-row"):
                    checks[x["name"]] = ui.checkbox(value=x["name"] in current or (not current and match)).props(
                        "dense")
                    with ui.column().classes("gap-0").style("min-width:0"):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.label(x["title"]).classes("text-sm font-semibold ellipsis")
                            if match:
                                T.status_chip(ui, "Cùng website", "green", "link")
                        ui.label(" · ".join(p for p in (x["address"], x["website"], x["account_name"]) if p)) \
                            .classes("text-xs muted ellipsis")

        def save():
            chosen = [x for x in locs if checks[x["name"]].value]
            with connect() as c:
                G.link(c, chosen, str(user))
            dlg.close()
            ui.notify(f"Đã gắn {len(chosen)} chi nhánh. Bấm “Lấy số mới” để lấy số lần đầu.", type="positive",
                      position="bottom-right", classes="sr-toast")
            body.refresh()
        with foot:
            ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
            ui.button("Lưu", on_click=save).props("unelevated no-caps color=primary")

    if ed:
        with right, ui.row().classes("items-center no-wrap gap-2"):
            ui.button("Chi nhánh", icon="storefront", on_click=link_dialog).props(
                "outline no-caps color=grey-9").tooltip("Gắn / bỏ các hồ sơ Google Business Profile của dự án")
            b = ui.button("Lấy số mới", icon="refresh").props("unelevated no-caps color=primary")
            b.on_click(lambda _, b=b: fetch(b))
            b.tooltip("Lấy lại hồ sơ, hiệu suất và từ khóa từ Google (miễn phí)")

    @ui.refreshable
    def body():
        with connect() as c:
            locs = G.linked(c)
            last = G.last_day(c)
        if not has_scope:
            T.empty_state(ui, "lock", "Tool chưa có quyền Google Business Profile",
                          "Chủ tool vào Cài đặt tích hợp → Kết nối Google, đăng nhập lại và tích ô quyền Google "
                          "Business Profile." if ed else "Số Local SEO sẽ có sau khi tool được cấp quyền.")
            return
        if not locs:
            T.empty_state(ui, "storefront", "Chưa gắn hồ sơ Google Business Profile",
                          "Bấm “Chi nhánh” để chọn hồ sơ của website này." if ed
                          else "Số Local SEO sẽ có sau khi gắn hồ sơ.")
            return
        names_all = [x["name"] for x in locs]
        names = names_all if state["loc"] == "all" else [state["loc"]]
        with ui.row().classes("w-full items-center gap-2 q-mb-xs"):
            if len(locs) > 1:
                ui.select({"all": f"Tất cả {len(locs)} chi nhánh", **{x["name"]: x["title"] for x in locs}},
                          value=state["loc"], on_change=lambda e: (state.update(loc=e.value), body.refresh())).props(
                    "dense outlined options-dense").classes("w-64")
            if last:
                ui.label(f"Số đến ngày {_vn(date.fromisoformat(last))} (Google trả chậm vài ngày)").classes(
                    "text-xs muted")
            else:
                ui.label("Chưa lấy số lần nào" + (": bấm “Lấy số mới”." if ed else ".")).classes("text-xs muted")
            ui.space()
            from .web_export import export_menu
            export_menu(ui, cfg, connect, f"local-seo_{date.today():%Y-%m-%d}", lambda: make_xlsx(locs, names, last),
                        label="Xuất Local SEO (Excel / Google Sheets)", user=user, icon_only=True, category="local")
        checks = {x["name"]: G.audit(x, site) for x in locs if x["name"] in names}
        n_high = sum(1 for cs in checks.values() for c_ in cs if c_["level"] == "high")
        with ui.tabs(value=state["tab"], on_change=lambda e: pick(e.value)).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs sr-bl-tabs"):
            for k, label in TABS:
                with ui.tab(k, label):
                    if k == "audit" and n_high:
                        ui.badge(str(n_high), color="red").props("rounded").classes("sr-tab-badge")
        with ui.tab_panels(value=state["tab"]).classes("w-full").props("animated=false") as panels:
            state["panels"] = panels
            with ui.tab_panel("overview").classes("q-px-none"):
                overview(locs, names, last)
            with ui.tab_panel("keywords").classes("q-px-none"):
                keywords(names)
            with ui.tab_panel("audit").classes("q-px-none"):
                audit_tab(locs, checks)

    def pick(v: str) -> None:
        state["tab"] = v
        if state.get("panels") is not None:
            state["panels"].set_value(v)
        ui.run_javascript(f"history.replaceState(null, '', '/local' + ('{v}' === 'overview' ? '' : '?tab={v}'))")

    def overview(locs, names, last) -> None:
        if not last:
            ui.label("Chưa có số hiệu suất.").classes("text-sm muted q-py-md")
            return
        end = date.fromisoformat(last)
        n = state["days"]
        start, p_end = end - timedelta(days=n - 1), end - timedelta(days=n)
        p_start = p_end - timedelta(days=n - 1)
        with ui.row().classes("items-center gap-2 q-mb-sm"):
            t_ = ui.toggle(PERIODS, value=n, on_change=lambda e: (state.update(days=e.value), body.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
            t_.props["aria-label"] = "Khoảng thời gian"
            ui.label(f"{_vn(start)} – {_vn(end)} · so với {n} ngày liền trước").classes("text-xs muted")
        with connect() as c:
            now, prev = G.totals(c, names, start, end), G.totals(c, names, p_start, p_end)
            ser = G.series(c, names, start, end, "month" if n > 120 else "week")
            per = [(x, G.totals(c, [x["name"]], start, end)) for x in locs if x["name"] in names]

        def card(icon, label, key, tone, info):
            v, p = now.get(key, 0), prev.get(key, 0)
            d = v - p
            T.kpi(ui, icon, label, F.n(v), delta=(f"{'+' if d > 0 else '−'}{F.n(abs(d))}" if d and p else ""),
                  good=(d > 0) if d else None, tone=tone, info=info,
                  prev={"label": f"{n} ngày trước", "value": F.n(p)} if p else None)
        with T.kpi_row(ui):
            card("visibility", "Lượt xem hồ sơ", "views", "green",
                 ("Số người thấy hồ sơ trên Google Search và Google Maps (một người xem nhiều lần trong ngày tính một).",))
            card("call", "Cuộc gọi", "CALL_CLICKS", "blue", ("Số lần bấm nút gọi trên hồ sơ.",))
            card("directions", "Chỉ đường", "BUSINESS_DIRECTION_REQUESTS", "lime", ("Số lần bấm chỉ đường đến cửa hàng.",))
            card("open_in_new", "Click website", "WEBSITE_CLICKS", "purple", ("Số lần bấm vào website từ hồ sơ.",))
            card("chat", "Tin nhắn", "BUSINESS_CONVERSATIONS", "grey", ("Số cuộc trò chuyện nhắn qua hồ sơ.",))
        labels = [(f"{p[8:10]}/{p[5:7]}" if len(p) == 10 else f"{p[5:7]}/{p[2:4]}") for p in [s["period"] for s in ser]]
        axis = {"axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                "axisLabel": {"color": "#8C8A7E", "fontSize": 11}}
        y = {"type": "value", "splitNumber": 4, "splitLine": {"lineStyle": {"color": "#EEECE4"}},
             "axisLabel": {"color": "#8C8A7E", "fontSize": 11}}
        legend = {"top": 0, "right": 0, "icon": "roundRect", "itemWidth": 10, "itemHeight": 10,
                  "textStyle": {"fontSize": 12, "color": "#4A4A40"}}
        unit = "tháng" if n > 120 else "tuần"
        with ui.element("div").classes("sr-bl-two w-full"):
            with T.section(ui, "Lượt xem hồ sơ", "show_chart", f"Theo {unit}, tách Search / Maps"):
                ui.echart({"animation": False, "grid": {"left": 44, "right": 12, "top": 30, "bottom": 26},
                           "legend": legend, "tooltip": {"trigger": "axis"},
                           "xAxis": {"type": "category", "data": labels, **axis}, "yAxis": y,
                           "series": [{"type": "bar", "name": "Google Search", "stack": "v", "barMaxWidth": 22,
                                       "itemStyle": {"color": "#2a78d6"},
                                       "data": [s["BUSINESS_IMPRESSIONS_MOBILE_SEARCH"]
                                                + s["BUSINESS_IMPRESSIONS_DESKTOP_SEARCH"] for s in ser]},
                                      {"type": "bar", "name": "Google Maps", "stack": "v", "barMaxWidth": 22,
                                       "itemStyle": {"color": "#1a9e8f", "borderRadius": [3, 3, 0, 0]},
                                       "data": [s["BUSINESS_IMPRESSIONS_MOBILE_MAPS"]
                                                + s["BUSINESS_IMPRESSIONS_DESKTOP_MAPS"] for s in ser]}]}
                           ).classes("w-full").style("height:240px")
            with T.section(ui, "Hành động từ hồ sơ", "touch_app", f"Theo {unit}"):
                lines = [("CALL_CLICKS", "Cuộc gọi", "#2a78d6", "solid"),
                         ("BUSINESS_DIRECTION_REQUESTS", "Chỉ đường", "#1a9e8f", "dashed"),
                         ("WEBSITE_CLICKS", "Click website", "#6250d6", "dotted")]
                ui.echart({"animation": False, "grid": {"left": 40, "right": 12, "top": 30, "bottom": 26},
                           "legend": legend, "tooltip": {"trigger": "axis"},
                           "xAxis": {"type": "category", "data": labels, "boundaryGap": False, **axis}, "yAxis": y,
                           "series": [{"type": "line", "name": nm, "symbol": "circle", "symbolSize": 6,
                                       "lineStyle": {"width": 2, "color": col, "type": dash},
                                       "itemStyle": {"color": col}, "data": [s[k] for s in ser]}
                                      for k, nm, col, dash in lines]}).classes("w-full").style("height:240px")
        # nguồn lượt xem
        views = now.get("views") or 0
        with T.section(ui, "Khách thấy hồ sơ ở đâu", "devices"):
            with ui.element("div").classes("sr-local-split"):
                for k in G.VIEWS:
                    v = now.get(k, 0)
                    with ui.column().classes("gap-0"):
                        ui.label(G.METRICS[k].replace("Xem trên ", "")).classes("text-xs muted")
                        ui.html(f"<b class='num' style='font-size:18px'>{F.n(v)}</b> "
                                f"<span class='muted text-xs'>{v / views * 100:.0f}%</span>" if views else
                                "<b class='num'>0</b>")
        if len(per) > 1:
            with T.section(ui, "Theo chi nhánh", "storefront"):
                cols = [{"name": "title", "label": "Chi nhánh", "field": "title", "align": "left", "sortable": True}] + [
                    {"name": k, "label": lab, "field": k, "align": "right", "sortable": True,
                     "headerStyle": "width:120px"}
                    for k, lab in (("views", "Lượt xem"), ("CALL_CLICKS", "Cuộc gọi"),
                                   ("BUSINESS_DIRECTION_REQUESTS", "Chỉ đường"), ("WEBSITE_CLICKS", "Click website"),
                                   ("BUSINESS_CONVERSATIONS", "Tin nhắn"))]
                ui.table(columns=cols, rows=[{"id": x["name"], "title": x["title"], **t} for x, t in per],
                         row_key="id").props("flat dense binary-state-sort").classes("w-full")

    def keywords(names) -> None:
        with connect() as c:
            months = G.keyword_months(c, names)
        if not months:
            ui.label("Chưa có từ khóa (Google cho số theo tháng, sau khi tháng kết thúc).").classes(
                "text-sm muted q-py-md")
            return
        opts = {"12": "12 tháng gần nhất", "3": "3 tháng gần nhất",
                **{m: f"Tháng {m[5:]}/{m[:4]}" for m in reversed(months)}}
        if state["month"] not in opts:
            state["month"] = months[-1]
        sel = state["month"]
        chosen = months[-int(sel):] if sel in ("12", "3") else [sel]
        with connect() as c:
            rows = G.keyword_rows(c, names, chosen)
        with T.section(ui, "Từ khóa tìm thấy hồ sơ", "manage_search",
                       "Từ khóa người dùng tìm trên Google Search / Maps rồi thấy hồ sơ. So với cùng số tháng liền "
                       "trước. Từ khóa ít lượt Google chỉ cho “dưới 15”."):
            with ui.row().classes("w-full items-center gap-2"):
                ui.select(opts, value=sel, on_change=lambda e: (state.update(month=e.value), body.refresh())).props(
                    "dense outlined options-dense").classes("w-56")
                ui.label(f"{len(rows)} từ khóa").classes("text-xs muted")
                ui.space()
                ui.input(placeholder="Tìm…", value=state["q"],
                         on_change=lambda e: (state.update(q=e.value or ""), table.refresh())).props(
                    "dense outlined clearable debounce=300").classes("w-56")

            @ui.refreshable
            def table():
                q = (state["q"] or "").strip().lower()
                data = []
                for i, r in enumerate(x for x in rows if not q or q in x["keyword"]):
                    v = r["value"] or 0
                    p = r["prev"]
                    data.append({"id": i, "keyword": r["keyword"],
                                 "value": F.n(v) if v else f"dưới {r['below']}", "v": v or 0,
                                 "prev": (F.n(p) if p else (f"dưới {r['prev_below']}" if r["prev_below"] else "–"))
                                 if p is not None else "mới",
                                 "change": (v - p) if v and p else None})
                cols = [{"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
                        {"name": "value", "label": "Lượt xem", "field": "value", "align": "right", "sortable": True,
                         ":sort": "(a, b, rowA, rowB) => rowA.v - rowB.v", "headerStyle": "width:130px"},
                        {"name": "prev", "label": "Kỳ trước", "field": "prev", "align": "right",
                         "headerStyle": "width:130px"},
                        {"name": "change", "label": "Thay đổi", "field": "change", "align": "right", "sortable": True,
                         "headerStyle": "width:110px"}]
                tb = ui.table(columns=cols, rows=data, row_key="id", pagination=25).props(
                    "flat dense binary-state-sort").classes("w-full")
                tb.add_slot("body-cell-change", """
                    <q-td :props="props" class="text-right">
                      <span v-if="props.value" class="num" :style="{color: props.value > 0 ? '#1E7C31' : '#C2410C',
                        fontWeight: 600}">{{ props.value > 0 ? '▲' : '▼' }} {{ Math.abs(props.value) }}</span>
                      <span v-else class="muted">–</span></q-td>""")
            table()

    def audit_tab(locs, checks) -> None:
        for x in locs:
            if x["name"] not in checks:
                continue
            cs = checks[x["name"]]
            bad = sum(1 for c_ in cs if c_["level"] in ("high", "medium"))
            maps = (x["data"].get("metadata") or {}).get("mapsUri")
            with T.section(ui, x["title"], "storefront",
                           (f"{bad} mục cần sửa" if bad else "Hồ sơ đầy đủ") + (" · " + G.address_text(x["data"])
                                                                                if G.address_text(x["data"]) else "")):
                if maps:
                    ui.link("Mở trên Google Maps", maps, new_tab=True).classes("text-sm")
                with ui.element("div").classes("sr-au-todo"):
                    for c_ in cs:
                        label, tone, icon = LEVELS[c_["level"]]
                        with ui.element("div").classes("sr-au-filter off").style("cursor:default"):
                            T.status_chip(ui, label, tone, icon)
                            with ui.column().classes("gap-0").style("min-width:0; flex:1 1 0"):
                                ui.label(c_["title"]).classes("text-sm font-semibold")
                                ui.label(c_["detail"]).classes("text-xs muted")

    def make_xlsx(locs, names, last) -> bytes:
        from openpyxl import Workbook

        from .export import INT, _sheet
        with connect() as c:
            end = date.fromisoformat(last) if last else date.today()
            daily = c.execute(f"SELECT location, day, metric, value FROM gbp_daily WHERE location IN "
                              f"({','.join('?' * len(names))}) ORDER BY day", names).fetchall() if names else []
            months = G.keyword_months(c, names)
            kw = G.keyword_rows(c, names, months[-12:]) if months else []
        titles = {x["name"]: x["title"] for x in locs}
        wb = Workbook()
        wb.remove(wb.active)
        by_day: dict[tuple, dict] = {}
        for loc, day, metric, v in daily:
            by_day.setdefault((loc, day), {})[metric] = v
        _sheet(wb, "Hiệu suất theo ngày", [("Ngày", 12, None), ("Chi nhánh", 30, None)]
               + [(G.METRICS[m], 16, INT) for m in G.METRICS],
               [[day, titles.get(loc, loc)] + [vals.get(m, 0) for m in G.METRICS]
                for (loc, day), vals in sorted(by_day.items(), key=lambda kv: (kv[0][1], kv[0][0]))])
        _sheet(wb, "Từ khóa 12 tháng", [("Từ khóa", 40, None), ("Lượt xem", 12, INT), ("Ghi chú", 16, None)],
               [[r["keyword"], r["value"] or None, f"dưới {r['below']}" if not r["value"] else ""] for r in kw])
        _sheet(wb, "Kiểm tra hồ sơ", [("Chi nhánh", 30, None), ("Mức", 12, None), ("Mục", 30, None),
                                      ("Chi tiết", 90, None)],
               [[x["title"], LEVELS[c_["level"]][0], c_["title"], c_["detail"]]
                for x in locs if x["name"] in names for c_ in G.audit(x, site)])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    body()


def _scopes(cfg) -> list[str]:
    """Quyền của token Google hiện tại (không gọi mạng)."""
    from google.oauth2.credentials import Credentials
    try:
        return list(Credentials.from_authorized_user_file(str(cfg.token_path)).scopes or [])
    except (ValueError, OSError):
        return []
