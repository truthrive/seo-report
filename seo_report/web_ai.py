"""Màn AI Search & GEO (R2): tab Tổng quan và Nguồn AI, dùng chung bộ lọc kỳ / so sánh / nguồn / quốc gia.

Dữ liệu lấy qua `AIAnalytics` (truy vấn GA4 trong luồng nền, có cache). Màn chỉ hiển thị, không tự tính lại rate.
"""
import csv
import io
from datetime import date, timedelta

from . import ai_classifier as C
from . import ai_format as F
from . import ui_theme as T
from .ai_analytics import AIAnalytics, Filters

GREEN, LIME, RED, MUTED, BLUE = "#1E7C31", "#9BB823", "#C2410C", "#6B6A5E", "#2563EB"
# Cột rate trong bảng giữ số (để sắp xếp đúng) và chỉ định dạng khi hiển thị.
PCT_JS = "val => val.toLocaleString('vi-VN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '%'"
PRESETS = {"week": "Tuần đang chọn", "7": "7 ngày", "28": "28 ngày", "90": "90 ngày", "last_month": "Tháng trước",
           "custom": "Tùy chọn"}
KPI_ICONS = {"Phiên AI": ("smart_toy", "green"), "Tỷ lệ AI": ("pie_chart", "blue"),
             "Tỷ lệ AI (nhóm organic)": ("donut_small", "blue"), "Engaged sessions": ("how_to_reg", "lime"),
             "Engagement rate": ("touch_app", "lime"), "Thời gian tương tác TB/phiên": ("timer", "purple"),
             "Key events": ("flag", "amber"), "Session key event rate": ("percent", "amber")}


def preset_range(key: str, today: date) -> tuple[date, date]:
    end = today - timedelta(days=1)
    if key in ("7", "28", "90"):
        return end - timedelta(days=int(key) - 1), end
    if key == "last_week":
        monday = today - timedelta(days=today.weekday() + 7)
        return monday, monday + timedelta(days=6)
    if key == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    return end - timedelta(days=27), end


def _key_event_names(cfg) -> list[str]:
    from . import auth, ga4
    try:
        return ga4.key_events(auth.build_ga4_admin(auth.get_credentials(cfg, need=auth.ALL_SCOPES)), cfg.ga4_property)
    except Exception:  # noqa: BLE001  (Admin API lỗi thì bỏ bảng key event, không chặn cả màn)
        return []


def landing_types(con, site: str, paths: list[str]) -> dict[str, str]:
    """Loại trang (taxonomy của màn Quản lý URL) cho từng landingPage GA4. GA4 trả đường dẫn không có tên miền và
    thường thiếu / cuối, nên thử khớp cả hai dạng; không khớp thì ghi rõ, không đoán."""
    from . import urls as U
    origin = site.rstrip("/")
    out = {}
    for p in paths:
        if p in ("(not set)", ""):
            out[p] = "Không xác định"
            continue
        url_id = U._match_existing(con, site, U.normalize(origin + p))
        row = con.execute("SELECT type FROM urls WHERE id = ?", (url_id,)).fetchone() if url_id else None
        out[p] = (row[0] or "Chờ đọc schema") if row else "Chưa có trong dữ liệu GSC"
    return out


def _make_analytics(cfg, connect_db):
    from . import auth, ga4_query
    creds = auth.get_credentials(cfg, need=auth.ALL_SCOPES)
    client = ga4_query.GA4Client(auth.build_ga4_data(creds), cfg.ga4_property, connect_db())
    return AIAnalytics(client)


TAB_SLUGS = {"tong-quan": "Tổng quan", "nguon": "Nguồn AI", "trang-dich": "Trang đích", "dia-ly": "Nguồn AI", "ai-google": "AI trên Google",
             "co-hoi": "Cơ hội SEO/GEO", "chat-luong": "Chất lượng dữ liệu"}
LAZY = {"Trang đích": "land", "Địa lý": "geo", "Cơ hội SEO/GEO": "opp", "Chất lượng dữ liệu": "dq"}


def state_from_params(params: dict, today: date, week: tuple[date, date] | None = None) -> dict:
    """Bộ lọc lấy từ địa chỉ trang (?preset=…&source=…), để tải lại hoặc gửi link vẫn giữ nguyên. Giá trị sai thì bỏ
    qua, dùng mặc định: tuần đang chọn ở thanh trên cùng (nếu có), không thì 28 ngày."""
    default = "week" if week else "28"
    key = params.get("preset") if params.get("preset") in PRESETS else default
    if key == "week" and not week:
        key = "28"
    start, end = week if key == "week" else preset_range(key, today)
    if key == "custom":
        try:
            s, e = date.fromisoformat(params["from"]), date.fromisoformat(params["to"])
            if s <= e:
                start, end = s, e
        except (KeyError, TypeError, ValueError):
            key = "28"
    return {"preset": key, "start": start, "end": end, "compare": params.get("compare") != "0",
            "source": params.get("source") or None, "country": params.get("country") or None,
            "landing": params.get("landing") or None,
            "tab": TAB_SLUGS.get(params.get("tab"), "Tổng quan")}


def params_from_state(state: dict, tab: str) -> dict:
    out = {"preset": state["preset"]}
    if state["preset"] == "custom":
        out["from"], out["to"] = state["start"].isoformat(), state["end"].isoformat()
    if not state["compare"]:
        out["compare"] = "0"
    for k in ("source", "country", "landing"):
        if state[k]:
            out[k] = state[k]
    slug = next((k for k, v in TAB_SLUGS.items() if v == tab), None)
    if slug and slug != "tong-quan":
        out["tab"] = slug
    return out


def build_ai_page(ui, cfg, connect, user: str, params: dict | None = None,
                  week: tuple[date, date] | None = None) -> None:
    from nicegui import background_tasks, run

    from . import db
    from .access import can_edit
    ed = can_edit(user)  # người chỉ xem: không nhập/ẩn file GSC, không đổi ngưỡng quy tắc

    if not cfg.ga4_property:
        ui.label("AI Search & GEO").classes("text-2xl font-semibold")
        ui.label("Chưa kết nối GA4: gắn GA4 property cho dự án ở màn Dự án (Quản trị → Dự án → Sửa).").classes("text-negative")
        return

    from urllib.parse import urlencode
    init = state_from_params(params or {}, date.today(), week)
    quality = init["tab"] == "Chất lượng dữ liệu"
    start0, end0 = init["start"], init["end"]
    state = {**{k: init[k] for k in ("preset", "start", "end", "compare", "source", "country", "landing")},
             "data": None, "loading": False, "error": None,
             "land": None, "geo": None, "opp": None, "dq": None, "lazy_loading": set(), "events": None}
    client = ui.context.client

    # ---- Bộ lọc chung ----
    if quality:
        T.page_header(ui, "verified", "Chất lượng dữ liệu", "Kết nối, độ mới, đối soát số liệu và cài đặt đang dùng",
                      tone="blue")
    else:
        T.page_header(ui, "auto_awesome", "AI Search & GEO",
                      "Traffic từ AI assistant (GA4) và hiển thị trong AI Overviews / AI Mode (GSC)", tone="purple")
    with ui.element("div").classes("sr-card q-px-md q-py-sm w-full"), \
            ui.row().classes("w-full items-center gap-3"):
        ui.icon("tune", size="18px").classes("muted")
        preset = ui.select(PRESETS, value=state["preset"], label="Kỳ").props("dense outlined").classes("w-44")
        d_from = ui.input("Từ ngày", value=start0.isoformat()).props("dense outlined type=date").classes("w-40")
        d_to = ui.input("Đến ngày", value=end0.isoformat()).props("dense outlined type=date").classes("w-40")
        compare = ui.switch("So với kỳ trước", value=state["compare"]).props("dense")
        ui.space()
        refresh_btn = ui.button(icon="refresh", on_click=lambda: load(force=True)).props("flat round").tooltip(
            "Làm mới dữ liệu (bỏ cache GA4)")
        from .web_export import export_menu
        export_menu(ui, cfg, connect, f"ai-search-geo_{state['start']}_{state['end']}", lambda: export_all(), user=user)
    with ui.row().classes("items-center gap-2"):
        filter_chips = ui.row().classes("gap-2")

    with ui.tabs().props("align=left no-caps dense").classes("w-full sr-tabs q-mt-sm") as tabs:
        t_over = ui.tab("Tổng quan")
        t_src = ui.tab("Nguồn AI")
        t_land = ui.tab("Trang đích")
        t_geo = ui.tab("Địa lý")
        t_gai = ui.tab("AI trên Google")
        t_opp = ui.tab("Cơ hội SEO/GEO")
        t_dq = ui.tab("Chất lượng dữ liệu")
    tab_by_name = {t._props["name"]: t for t in (t_over, t_src, t_land, t_geo, t_gai, t_opp, t_dq)}
    t_geo.set_visibility(False)  # quốc gia hiện ngay trong tab Nguồn AI
    t_dq.set_visibility(False)  # mở từ menu "Chất lượng dữ liệu"
    if quality:
        tabs.set_visibility(False)
    tabs.set_value(tab_by_name[init["tab"]])
    panels = ui.tab_panels(tabs, value=tab_by_name[init["tab"]]).classes("w-full")

    def sync_url():
        """Ghi bộ lọc + tab đang mở lên địa chỉ trang (không tải lại trang)."""
        name = getattr(tabs.value, "_props", {}).get("name", tabs.value)
        q = urlencode(params_from_state(state, name))
        client.run_javascript(f"history.replaceState(null, '', '/ai{'?' + q if q else ''}')")

    # ---- Tải dữ liệu (luồng nền) ----
    async def load(force: bool = False):
        state["loading"], state["error"] = True, None
        render.refresh()
        refresh_btn.props("loading")
        start, end = state["start"], state["end"]
        f = Filters(source=state["source"], country=state["country"], landing_page=state["landing"])
        interval = "week" if (end - start).days > 45 else "day"

        def work():
            ai = _make_analytics(cfg, lambda: db.connect(cfg.db_path))
            if force:
                ai.client.clear_cache()
            if state["events"] is None:
                state["events"] = _key_event_names(cfg)
            return {"summary": ai.summary(start, end, f, compare=state["compare"]),
                    "sources": ai.sources(start, end, Filters(country=state["country"]), compare=state["compare"]),
                    "trend": ai.trend(start, end, f, interval=interval),
                    "key_events": ai.key_events(start, end, state["events"], f) if state["events"] else None}

        state["land"] = state["geo"] = state["opp"] = state["dq"] = None
        sync_url()  # bộ lọc đổi: tab tải sau phải tải lại
        try:
            state["data"] = await run.io_bound(work)
        except (Exception, SystemExit) as e:  # token thiếu quyền, mất mạng…
            state["error"], state["data"] = str(e), None
        finally:
            state["loading"] = False
            refresh_btn.props(remove="loading")
        render.refresh()
        lazy_load(tabs.value)

    def lazy_load(tab):
        name = getattr(tab, "_props", {}).get("name", tab)
        for kind in ([LAZY[name]] if name in LAZY else []) + (["geo"] if name == "Nguồn AI" else []):
            if state[kind] is None:
                background_tasks.create(load_extra(kind))

    async def load_extra(kind: str):
        """Tab Trang đích / Địa lý chỉ tải khi mở tới, để tab Tổng quan không phải chờ thêm truy vấn."""
        if kind in state["lazy_loading"] or state["error"]:
            return
        state["lazy_loading"].add(kind)
        render.refresh()
        start, end = state["start"], state["end"]
        f = Filters(source=state["source"], country=state["country"], landing_page=state["landing"])
        interval = "week" if (end - start).days > 45 else "day"

        def work():
            ai = _make_analytics(cfg, lambda: db.connect(cfg.db_path))
            if kind == "land":
                land = ai.landing_pages(start, end, f, compare=state["compare"], limit=1000)
                organic = ai.organic_by_landing(start, end, Filters(country=state["country"]))
                with connect() as c:
                    types = landing_types(c, cfg.site_url, [r["landingPage"] for r in land["data"].get("rows", [])])
                groups: dict[str, list[str]] = {}
                for path, t in types.items():
                    if path not in ("(not set)", ""):
                        groups.setdefault(t, []).append(path)
                seg = ai.segments(start, end, groups, f, compare=state["compare"])
                return {"pages": land, "organic": organic, "types": types, "segments": seg}
            if kind == "opp":
                return opp_data(ai, start, end)
            if kind == "dq":
                return dq_data(ai, start, end)
            return {"countries": ai.countries(start, end, Filters(source=state["source"]), compare=state["compare"],
                                              limit=250),
                    "matrix": ai.country_sources(start, end, Filters(country=state["country"])),
                    "trend": ai.country_trend(start, end, Filters(source=state["source"]), interval=interval)}

        try:
            state[kind] = await run.io_bound(work)
        except (Exception, SystemExit) as e:
            state[kind] = {"error": str(e)}
        finally:
            state["lazy_loading"].discard(kind)
        render.refresh()

    def set_filter(key, value):
        state[key] = value
        draw_chips()
        background_tasks.create(load())

    def draw_chips():
        filter_chips.clear()
        with filter_chips:
            for key, label in [("source", "Nguồn"), ("country", "Quốc gia"), ("landing", "Trang đích")]:
                if state[key]:
                    ui.chip(f"{label}: {F.SOURCE_NAMES.get(state[key], state[key])}", removable=True,
                            on_value_change=lambda e, k=key: set_filter(k, None) if not e.value else None).props(
                        "color=green-1 text-color=green-10")

    def on_preset(e):
        state["preset"] = e.value
        if e.value == "week" and not week:
            return
        if e.value != "custom":
            s, t = week if e.value == "week" else preset_range(e.value, date.today())
            d_from.value, d_to.value = s.isoformat(), t.isoformat()
            apply_dates()

    def apply_dates():
        try:
            s, t = date.fromisoformat(d_from.value), date.fromisoformat(d_to.value)
        except (TypeError, ValueError):
            return
        if s > t:
            ui.notify("Ngày bắt đầu phải trước ngày kết thúc", type="warning")
            return
        if (s, t) != (state["start"], state["end"]):
            state["start"], state["end"] = s, t
            background_tasks.create(load())

    preset.on_value_change(on_preset)
    d_from.on("change", lambda _: (preset.set_value("custom") if preset.value != "custom" else None, apply_dates()))
    d_to.on("change", lambda _: (preset.set_value("custom") if preset.value != "custom" else None, apply_dates()))
    compare.on_value_change(lambda e: (state.update(compare=e.value), background_tasks.create(load())))

    # ---- Hiển thị ----
    def warnings_box(envs):
        seen, items = set(), []
        for env in envs:
            for w in env.get("warnings", []):
                if (w["code"], w["message"]) not in seen:
                    seen.add((w["code"], w["message"]))
                    items.append(w)
        if not items:
            return
        titles = ", ".join(dict.fromkeys(F.WARNING_TITLES.get(w["code"], w["code"]) for w in items))
        with ui.expansion(f"Lưu ý dữ liệu ({len(items)}): {titles}", icon="info").classes("w-full").props(
                "dense header-class=text-orange-10").style(
                "background: #FFF8E6; border: 1px solid #F2D9A6; border-radius: 10px"):
            for w in items:
                with ui.row().classes("items-start gap-2 no-wrap q-px-sm"):
                    ui.icon("info", color="orange-8", size="16px")
                    ui.label(f"{F.WARNING_TITLES.get(w['code'], w['code'])}: {w['message']}").classes("text-sm")

    def provenance(env):
        meta = env.get("sourceMeta", {})
        cls = env.get("classification", {})
        when = (meta.get("queriedAt") or "")[:16].replace("T", " ")
        ui.label(f"Nguồn: GA4 {meta.get('propertyId')} · phân loại {cls.get('mode')} {cls.get('version')} "
                 "(kênh AI Assistant của GA4 + nhận diện bổ sung theo nguồn; không gồm traffic AI trả phí) · "
                 f"truy vấn lúc {when} UTC{' (cache)' if meta.get('cached') else ''}").classes("text-xs muted")

    def kpi_card(title, value, delta="", good=None, hint=""):
        icon, tone = KPI_ICONS.get(title, ("insights", "green"))
        T.kpi(ui, icon, title, value, delta, good, hint, tone=tone)

    def sign(v):
        return None if v is None or v == 0 else v > 0

    def safe(fn, d):
        """Lỗi khi vẽ hiện ngay trên màn (kèm chi tiết) thay vì để trống."""
        import traceback
        try:
            fn(d)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            ui.label(f"Lỗi hiển thị: {type(e).__name__}: {e}").classes("text-negative text-sm")

    @ui.refreshable
    def render():
        panels.clear()
        with panels:
            with ui.tab_panel(t_over):
                if state["loading"] and not state["data"]:
                    for _ in range(3):
                        T.skeleton(ui).classes("w-full").style("height: 90px")
                elif state["error"]:
                    error_state()
                elif state["data"]:
                    safe(overview, state["data"])
            with ui.tab_panel(t_src):
                if state["loading"] and not state["data"]:
                    T.skeleton(ui).classes("w-full").style("height: 300px")
                elif state["error"]:
                    error_state()
                elif state["data"]:
                    safe(sources_tab, state["data"])
                    ui.separator().classes("q-my-md")
                    ui.label("Theo quốc gia").classes("text-lg font-semibold")
                    if state["geo"] is None or "geo" in state["lazy_loading"]:
                        T.skeleton(ui).classes("w-full").style("height: 200px")
                    elif state["geo"].get("error"):
                        ui.label(f"Không tải được: {state['geo']['error']}").classes("text-negative")
                    else:
                        safe(geo_tab, state["geo"])
            with ui.tab_panel(t_gai):
                safe(lambda _: gai_tab(), None)  # chỉ đọc SQLite, không cần GA4
            for tab, kind, fn in [(t_land, "land", land_tab), (t_opp, "opp", opp_tab),
                                  (t_dq, "dq", dq_tab)]:
                with ui.tab_panel(tab):
                    if state["error"]:
                        error_state()
                    elif state[kind] is None or kind in state["lazy_loading"]:
                        ui.label("Đang tải dữ liệu từ GA4…").classes("text-sm muted")
                        T.skeleton(ui).classes("w-full").style("height: 300px")
                    elif state[kind].get("error"):
                        ui.label(f"Không tải được: {state[kind]['error']}").classes("text-negative")
                    else:
                        safe(fn, state[kind])

    def error_state():
        with ui.card().props("flat bordered").classes("w-full q-pa-lg items-center"):
            ui.icon("cloud_off", size="40px", color="grey-6")
            ui.label("Không tải được dữ liệu GA4").classes("text-base font-semibold")
            ui.label(state["error"]).classes("text-sm muted")
            ui.button("Thử lại", on_click=lambda: load()).props("outline no-caps")

    def overview(d):
        s, tr = d["summary"], d["trend"]
        if s["status"] == "ERROR":
            state["error"] = s["warnings"][0]["message"] if s["warnings"] else "Lỗi GA4"
            error_state()
            return
        if state["loading"]:
            ui.linear_progress(show_value=False).props("indeterminate color=primary")
        warnings_box([s, tr])
        a, dl = s["data"]["ai"], s["data"]["aiDeltas"] or {}

        def prev_of(key):
            return (s["data"]["aiPrev"] or {}).get(key) if s["data"]["aiPrev"] else None
        sh = s["data"]["share"]
        with T.kpi_row(ui):
            kpi_card("Phiên AI", F.n(a["sessions"]), F.delta_pct(dl.get("sessions"), prev_of("sessions")),
                     sign(dl.get("sessions")))
            kpi_card("Tỷ lệ AI", F.pct(sh["ofAllSessions"]), hint=f"trên tổng {F.n(sh['allSessions'])} phiên của site")
            kpi_card("Tỷ lệ AI (nhóm organic)", F.pct(sh["ofOrganicBase"]),
                     hint=f"trên {F.n(sh['organicBase'])} phiên AI + Organic Search + Social")
            kpi_card("Engaged sessions", F.n(a["engagedSessions"]), F.delta_pct(dl.get("engagedSessions"), prev_of("engagedSessions")),
                     sign(dl.get("engagedSessions")))
        with T.kpi_row(ui):
            kpi_card("Engagement rate", F.pct(a["engagementRate"]), F.delta_points(dl.get("engagementRate")),
                     sign(dl.get("engagementRate")))
            kpi_card("Thời gian tương tác TB/phiên", F.mmss(a["avgEngagementTimePerSession"]),
                     F.delta_pct(dl.get("avgEngagementTimePerSession")), sign(dl.get("avgEngagementTimePerSession")))
            kpi_card("Key events", F.n(a["keyEvents"]), F.delta_pct(dl.get("keyEvents"), prev_of("keyEvents")), sign(dl.get("keyEvents")),
                     hint=f"{F.per100(a['keyEventsPer100Sessions'])} key events / 100 phiên")
            kpi_card("Session key event rate", F.pct(a["sessionKeyEventRate"]),
                     F.delta_points(dl.get("sessionKeyEventRate")), sign(dl.get("sessionKeyEventRate")),
                     hint="% phiên có ít nhất 1 key event")
        paid = s["data"]["paidAi"]
        if paid["sessions"]:
            ui.label(f"Ngoài ra {F.n(paid['sessions'])} phiên từ nguồn AI có medium trả phí (ví dụ chatgpt / paid), "
                     f"{paid['keyEvents']} key events: tính là quảng cáo, không cộng vào số trên.").classes(
                "text-xs muted")

        pts = tr["data"].get("points", [])
        key = "week" if tr["data"].get("interval") == "week" else "date"
        labels = [(p[key][8:10] + "/" + p[key][5:7]) if key == "week" else (p["date"][6:] + "/" + p["date"][4:6])
                  for p in pts]
        ui.label("Phiên theo " + ("tuần" if key == "week" else "ngày")).classes("text-lg font-semibold q-mt-md")
        ui.echart({
            "tooltip": {"trigger": "axis"}, "legend": {"bottom": 0, "icon": "roundRect"},
            "grid": {"left": 56, "right": 56, "top": 32, "bottom": 48},
            "xAxis": {"type": "category", "data": labels, "axisTick": {"show": False}},
            "yAxis": [{"type": "value", "name": "Organic", "splitLine": {"lineStyle": {"color": "#EEECE4"}}},
                      {"type": "value", "name": "AI", "splitLine": {"show": False}}],
            "series": [
                {"name": "Organic Search", "type": "line", "smooth": True, "symbol": "none",
                 "data": [p.get("Organic Search", 0) for p in pts], "itemStyle": {"color": "#B8B6A8"},
                 "lineStyle": {"width": 1.5}},
                {"name": "Organic Social", "type": "line", "smooth": True, "symbol": "none",
                 "data": [p.get("Organic Social", 0) for p in pts], "itemStyle": {"color": "#93B4F5"},
                 "lineStyle": {"width": 1.5}},
                {"name": "AI Assistants (trục phải)", "type": "bar", "yAxisIndex": 1, "barWidth": "50%",
                 "data": [p.get("AI Assistants", 0) for p in pts],
                 "itemStyle": {"color": GREEN, "borderRadius": [4, 4, 0, 0]}},
            ],
        }).classes("w-full sr-card q-pa-sm").style("height: 320px")
        partial = [l for l, p in zip(labels, pts) if p.get("partial")]
        note = "AI dùng trục phải vì nhỏ hơn Organic khoảng 100 lần: so xu hướng, không so độ cao hai đường."
        if partial:
            note += f" Tuần không trọn vẹn trong kỳ: {', '.join(partial)}."
        ui.label(note).classes("text-xs muted")

        ui.label("So sánh kênh").classes("text-lg font-semibold q-mt-md")
        rows = [("AI Assistants", a)] + [(k, v) for k, v in s["data"]["channels"].items()]
        ui.table(columns=[
            {"name": "ch", "label": "Kênh", "field": "ch", "align": "left"},
            {"name": "s", "label": "Phiên", "field": "s", "align": "right"},
            {"name": "e", "label": "Engaged", "field": "e", "align": "right"},
            {"name": "er", "label": "Engagement rate", "field": "er", "align": "right"},
            {"name": "t", "label": "TG tương tác TB/phiên", "field": "t", "align": "right"},
            {"name": "k", "label": "Key events", "field": "k", "align": "right"},
            {"name": "kr", "label": "Session key event rate", "field": "kr", "align": "right"},
        ], rows=[{"ch": name, "s": F.n(v["sessions"]), "e": F.n(v["engagedSessions"]), "er": F.pct(v["engagementRate"]),
                  "t": F.mmss(v["avgEngagementTimePerSession"]), "k": F.n(v["keyEvents"]),
                  "kr": F.pct(v["sessionKeyEventRate"])} for name, v in rows],
            row_key="ch").classes("w-full").props("flat bordered dense")
        ke = d.get("key_events")
        if ke and ke.get("data", {}).get("events"):
            ui.label("Key events từ phiên AI, theo từng event").classes("text-lg font-semibold q-mt-md")
            ui.table(columns=[
                {"name": "ev", "label": "Event", "field": "ev", "align": "left"},
                {"name": "k", "label": "Số lần", "field": "k", "align": "right"},
                {"name": "r", "label": "% phiên AI có event này", "field": "r", "align": "right"},
            ], rows=[{"ev": e["event"], "k": F.n(e["keyEvents"]), "r": F.pct(e["sessionKeyEventRate"])}
                     for e in sorted(ke["data"]["events"], key=lambda e: -e["keyEvents"])],
                row_key="ev").classes("w-full").props("flat bordered dense")
            if any(e["sessionKeyEventRate"] is None for e in ke["data"]["events"]):
                ui.label("N/A: GA4 không tính tỷ lệ phiên riêng cho event có dấu cách trong tên (ví dụ 'Click Zalo'); "
                         "số lần vẫn đúng.").classes("text-xs muted")
        with ui.row().classes("gap-2"):
            ui.button("Xem nguồn AI", on_click=lambda: tabs.set_value(t_src)).props("outline no-caps")
            ui.button("Xem trang đích", on_click=lambda: tabs.set_value(t_land)).props("outline no-caps")
        provenance(s)

    def land_tab(d):
        pages, organic, types, seg = d["pages"], d["organic"], d["types"], d["segments"]
        if pages["status"] == "ERROR":
            ui.label(pages["warnings"][0]["message"]).classes("text-negative")
            return
        warnings_box([pages, seg])
        ui.label("Theo loại trang").classes("text-lg font-semibold")
        seg_rows = seg["data"].get("segments", [])
        seg_table = ui.table(columns=[
            {"name": "seg", "label": "Loại trang", "field": "seg", "align": "left"},
            {"name": "p", "label": "Số trang", "field": "p", "align": "right"},
            {"name": "s", "label": "Phiên AI", "field": "s", "align": "right"},
            {"name": "chg", "label": "So với kỳ trước", "field": "chg", "align": "right"},
            {"name": "er", "label": "Engagement rate", "field": "er", "align": "right"},
            {"name": "k", "label": "Key events", "field": "k", "align": "right"},
            {"name": "kr", "label": "Session key event rate", "field": "kr", "align": "right"},
        ], rows=[{"seg": x["segment"], "p": x["pages"], "s": x["sessions"],
                  "chg": F.delta_pct(x["sessionsChange"], x["sessionsPrev"]), "er": F.pct(x["engagementRate"]),
                  "k": F.n(x["keyEvents"]), "kr": F.pct(x["sessionKeyEventRate"])} for x in seg_rows],
            row_key="seg").classes("w-full").props("flat bordered dense")
        T.bar_slot(seg_table, "s", max((x["sessions"] for x in seg_rows), default=1))
        ui.label("Loại trang lấy từ màn Quản lý URL. Tỷ lệ mỗi nhóm do GA4 tính trên đúng các trang của nhóm, không "
                 "cộng từ từng trang.").classes("text-xs muted")

        rows = pages["data"]["rows"]
        type_filter = ui.select(["Tất cả"] + sorted(set(types.values())), value="Tất cả", label="Loại trang").props(
            "dense outlined").classes("w-64 q-mt-md")
        search = ui.input(placeholder="Tìm trang đích").props("dense outlined clearable").classes("w-80")
        table = ui.table(columns=[
            {"name": "page", "label": "Trang đích", "field": "page", "align": "left", "sortable": True},
            {"name": "type", "label": "Loại", "field": "type", "align": "left", "sortable": True},
            {"name": "s", "label": "Phiên AI", "field": "s", "align": "right", "sortable": True},
            {"name": "chg", "label": "So với kỳ trước", "field": "chg", "align": "right"},
            {"name": "er", "label": "Engagement rate", "field": "er", "align": "right", "sortable": True,
             ":format": PCT_JS},
            {"name": "k", "label": "Key events", "field": "k", "align": "right", "sortable": True},
            {"name": "kr", "label": "Session key event rate", "field": "kr", "align": "right", "sortable": True,
             ":format": PCT_JS},
            {"name": "org", "label": "Phiên Organic Search (tham khảo)", "field": "org", "align": "right",
             "sortable": True, ":format": "val => val.toLocaleString('vi-VN')"},
        ], rows=[], row_key="page", pagination=25).classes("w-full cursor-pointer").props("flat bordered dense")
        table.add_slot("body-cell-page", """
            <q-td :props="props">
              <span :title="props.row.full">{{ props.value }}</span>
              <q-badge v-if="props.row.notset" color="orange-2" text-color="orange-10" label="không xác định"
                       class="q-ml-xs" />
            </q-td>""")

        def fill():
            t = type_filter.value
            table.rows = [{
                "page": r["landingPage"], "full": cfg.site_url.rstrip("/") + r["landingPage"]
                if r["landingPage"].startswith("/") else r["landingPage"],
                "type": types.get(r["landingPage"], ""), "s": r["sessions"], "chg": F.delta_pct(r["sessionsChange"], r["sessionsPrev"]),
                "er": round((r["engagementRate"] or 0) * 100, 2), "k": r["keyEvents"],
                "kr": round((r["sessionKeyEventRate"] or 0) * 100, 2), "org": organic.get(r["landingPage"], 0),
                "notset": r["notSet"]} for r in rows if t == "Tất cả" or types.get(r["landingPage"]) == t]

        fill()
        type_filter.on_value_change(lambda _: fill())
        search.bind_value(table, "filter")
        ui.label(f"{len(rows)} trang đích có phiên AI. Bấm một dòng để xem chi tiết trang. "
                 "Cột Organic Search là kênh khác, chỉ để so quy mô, không phải traffic AI.").classes("text-xs muted")
        table.on("rowClick", lambda e: page_detail(e.args[1]["page"]))
        ui.button("Tải CSV trang đích", icon="download", on_click=lambda: download_rows(
            "trang-dich", ["landing_page", "type", "ai_sessions", "ai_sessions_prev", "engagement_rate", "key_events",
                           "session_key_event_rate", "organic_search_sessions"],
            [[r["landingPage"], types.get(r["landingPage"], ""), r["sessions"], r["sessionsPrev"], r["engagementRate"],
              r["keyEvents"], r["sessionKeyEventRate"], organic.get(r["landingPage"], 0)] for r in rows])).props(
            "outline no-caps")
        provenance(pages)

    async def page_detail(path: str):
        if path in ("(not set)", ""):
            ui.notify("Trang đích không xác định: GA4 không ghi nhận trang đầu tiên của phiên.", type="warning")
            return
        start, end = state["start"], state["end"]
        f = Filters(source=state["source"], country=state["country"], landing_page=path)
        interval = "week" if (end - start).days > 45 else "day"
        with ui.dialog() as dialog, ui.card().style("min-width: 720px"):
            ui.label(path).classes("text-base font-semibold")
            body = ui.column().classes("w-full")
            with body:
                T.skeleton(ui).classes("w-full").style("height: 240px")
        dialog.open()

        def work():
            ai = _make_analytics(cfg, lambda: db.connect(cfg.db_path))
            return ai.trend(start, end, f, interval=interval), ai.sources(start, end, f, compare=False)

        try:
            tr, src = await run.io_bound(work)
        except (Exception, SystemExit) as e:
            body.clear()
            with body:
                ui.label(f"Không tải được: {e}").classes("text-negative")
            return
        body.clear()
        with body:
            pts = tr["data"].get("points", [])
            key = "week" if interval == "week" else "date"
            ui.echart({"tooltip": {"trigger": "axis"}, "grid": {"left": 40, "right": 16, "top": 16, "bottom": 32},
                       "xAxis": {"type": "category", "data": [p[key][-2:] + "/" + (p[key][5:7] if key == "week"
                                                                                  else p[key][4:6]) for p in pts]},
                       "yAxis": {"type": "value", "name": "Phiên AI"},
                       "series": [{"type": "bar", "data": [p.get("AI Assistants", 0) for p in pts],
                                   "itemStyle": {"color": GREEN}}]}).classes("w-full").style("height: 220px")
            ui.label("Theo nguồn: " + " · ".join(f"{F.SOURCE_NAMES.get(r['source'], r['source'])} {r['sessions']}"
                                                  for r in src["data"].get("sources", []))).classes("text-sm")
            ui.button("Lọc cả màn theo trang này", on_click=lambda: (dialog.close(),
                                                                     set_filter("landing", path))).props("flat no-caps")

    def geo_tab(d):
        cs, matrix, tr = d["countries"], d["matrix"], d["trend"]
        if cs["status"] == "ERROR":
            ui.label(cs["warnings"][0]["message"]).classes("text-negative")
            return
        warnings_box([cs])
        ui.label("Quốc gia của người truy cập do GA4 ghi nhận (không phải vị trí cửa hàng). Bấm một quốc gia để lọc "
                 "cả màn.").classes("text-xs muted")
        rows = cs["data"]["rows"]
        total = sum(r["sessions"] for r in rows) or 0
        table = ui.table(columns=[
            {"name": "c", "label": "Quốc gia", "field": "c", "align": "left"},
            {"name": "s", "label": "Phiên AI", "field": "s", "align": "right"},
            {"name": "share", "label": "% phiên AI", "field": "share", "align": "right"},
            {"name": "chg", "label": "So với kỳ trước", "field": "chg", "align": "right"},
            {"name": "er", "label": "Engagement rate", "field": "er", "align": "right"},
            {"name": "k", "label": "Key events", "field": "k", "align": "right"},
            {"name": "kr", "label": "Session key event rate", "field": "kr", "align": "right"},
        ], rows=[{"c": r["country"], "s": F.n(r["sessions"]), "share": F.pct(r["sessions"] / total if total else None, 1),
                  "chg": F.delta_pct(r["sessionsChange"], r["sessionsPrev"]), "er": F.pct(r["engagementRate"]), "k": F.n(r["keyEvents"]),
                  "kr": F.pct(r["sessionKeyEventRate"])} for r in rows],
            row_key="c", pagination=15).classes("w-full cursor-pointer").props("flat bordered dense")
        table.on("rowClick", lambda e: set_filter("country", e.args[1]["c"]))

        m = matrix["data"].get("matrix", {})
        subs = sorted({s for row in m.values() for s in row}, key=lambda s: -sum(row.get(s, 0) for row in m.values()))
        top = sorted(m, key=lambda c: -sum(m[c].values()))[:10]
        ui.label("Quốc gia × nguồn AI (top 10 quốc gia)").classes("text-lg font-semibold q-mt-md")
        ui.table(columns=[{"name": "c", "label": "Quốc gia", "field": "c", "align": "left"}] +
                 [{"name": s, "label": F.SOURCE_NAMES.get(s, s), "field": s, "align": "right"} for s in subs],
                 rows=[{"c": c, **{s: F.n(m[c].get(s, 0)) for s in subs}} for c in top],
                 row_key="c").classes("w-full").props("flat bordered dense")

        pts = tr["data"].get("points", [])
        key = "week" if tr["data"].get("interval") == "week" else "date"
        ui.label("Xu hướng top 5 quốc gia").classes("text-lg font-semibold q-mt-md")
        palette = [GREEN, BLUE, LIME, "#9333EA", "#DB2777", "#8C8A7E"]
        ui.echart({"tooltip": {"trigger": "axis"}, "legend": {"bottom": 0},
                   "grid": {"left": 48, "right": 16, "top": 24, "bottom": 48},
                   "xAxis": {"type": "category", "data": [(p[key][8:10] + "/" + p[key][5:7]) if key == "week"
                                                          else (p[key][6:] + "/" + p[key][4:6]) for p in pts]},
                   "yAxis": {"type": "value", "name": "Phiên AI"},
                   "series": [{"name": s, "type": "line", "data": [p.get(s, 0) for p in pts],
                               "itemStyle": {"color": palette[i % len(palette)]}}
                              for i, s in enumerate(tr["data"].get("series", []))]}).classes("w-full").style(
            "height: 260px")
        ui.button("Tải CSV quốc gia", icon="download", on_click=lambda: download_rows(
            "quoc-gia", ["country", "ai_sessions", "ai_sessions_prev", "engagement_rate", "key_events",
                         "session_key_event_rate"],
            [[r["country"], r["sessions"], r["sessionsPrev"], r["engagementRate"], r["keyEvents"],
              r["sessionKeyEventRate"]] for r in rows])).props("outline no-caps")
        provenance(cs)

    def opp_data(ai, start, end):
        """GA4 AI theo trang đích (không lọc trang đích: bảng này là theo từng URL) + GSC Web từ SQLite của tool."""
        from . import ai_opportunities as O
        f = Filters(source=state["source"], country=state["country"])
        widened = (end - start).days + 1 < O.MIN_DAYS
        if widened:  # ngưỡng quy tắc đặt cho kỳ ≥ 28 ngày; kỳ ngắn hơn mẫu quá nhỏ, gợi ý sẽ sai
            start = end - timedelta(days=O.MIN_DAYS - 1)
        land = ai.landing_pages(start, end, f, compare=False, limit=1000)
        if land["status"] == "ERROR":
            return {"error": land["warnings"][0]["message"]}
        summ = ai.summary(start, end, f, compare=False)
        er = summ["data"]["ai"]["engagementRate"] if summ["status"] != "ERROR" else None
        with connect() as c:
            res = O.build(c, cfg.site_url, start, end, land["data"]["rows"], er)
        return {**res, "ai_engagement_rate": er, "ga4": land, "widened": widened}

    def opp_tab(d):
        from . import ai_opportunities as O
        with ui.card().props("flat").classes("w-full q-pa-sm").style("background: #EEF4FF; border: 1px solid #C7D7F5"):
            ui.label("Cột GSC Web là toàn bộ Google Web Search (GSC loại web). Có gồm traffic từ AI Overviews / AI Mode "
                     "nhưng không tách riêng được, nên đây KHÔNG phải số liệu AI. Cột GA4 AI là phiên do AI assistant "
                     "(ChatGPT, Gemini…) dẫn tới. Hai nguồn đặt cạnh nhau để gợi ý việc cần kiểm tra, không cộng hay "
                     "nhân chéo với nhau.").classes("text-sm")
        if d.get("widened"):
            T.status_chip(ui, f"Tab này dùng 28 ngày ({d['period']}) thay cho kỳ đang chọn: ngưỡng các quy tắc đặt "
                              "cho kỳ 28 ngày, kỳ ngắn hơn có quá ít phiên AI để kết luận", "blue", "date_range")
        warnings_box([d, d["ga4"]])
        rows, t = d["rows"], d["thresholds"]

        # ---- Gợi ý ----
        opps_box = ui.column().classes("w-full gap-1")

        def draw_opps():
            opps = O.rules(rows, t, d["ai_engagement_rate"], d["period"])
            d["opportunities"] = opps
            opps_box.clear()
            with opps_box:
                ui.label(f"Gợi ý cần kiểm tra ({len(opps)})").classes("text-lg font-semibold")
                if not opps:
                    ui.label("Không có trang nào chạm ngưỡng trong kỳ này.").classes("text-sm muted")
                sev = {"cao": "red-2", "trung bình": "orange-2", "thấp": "grey-3"}
                groups: dict[str, list] = {}
                for o in opps:
                    groups.setdefault(o["rule_id"], []).append(o)
                for rule_id, items in groups.items():  # một khối mỗi quy tắc: mô tả một lần, bảng các trang bên dưới
                    first = items[0]
                    with ui.expansion(value=first["severity"] != "thấp").classes("w-full").props(
                            "dense switch-toggle-side") as ex:
                        with ex.add_slot("header"):
                            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                                ui.badge(first["severity"], color=sev.get(first["severity"], "grey-3")).props(
                                    "text-color=black")
                                ui.label(f"{first['title']} ({len(items)} trang)").classes("text-sm font-medium")
                        for k, lbl in [("threshold", "Ngưỡng"), ("verification", "Cách kiểm chứng"),
                                       ("action", "Gợi ý"), ("source", "Nguồn"), ("data_period", "Kỳ"),
                                       ("rule_id", "Mã quy tắc")]:
                            with ui.row().classes("gap-2 no-wrap"):
                                ui.label(lbl).classes("text-xs muted").style("min-width: 110px")
                                ui.label(str(first[k])).classes("text-sm")
                        ui.table(columns=[
                            {"name": "path", "label": "URL", "field": "path", "align": "left"},
                            {"name": "type", "label": "Loại", "field": "type", "align": "left"},
                            {"name": "ev", "label": "Bằng chứng", "field": "ev", "align": "left"},
                            {"name": "conf", "label": "Độ tin cậy", "field": "conf", "align": "left"},
                        ], rows=[{"path": o["path"], "type": o["type"], "ev": o["evidence"], "conf": o["confidence"]}
                                 for o in items], row_key="path", pagination=10).classes("w-full").props(
                            "flat bordered dense")

        with ui.expansion("Ngưỡng của các quy tắc (chỉnh được, lưu cho mọi người dùng)", icon="tune").classes("w-full"):
            inputs = {k: ui.number(O.LABELS[k], value=t[k], min=0).props("dense outlined").classes("w-full")
                      for k in O.DEFAULTS}

            def save():
                with connect() as c:
                    t.update(O.set_thresholds(c, cfg.site_url, {k: i.value for k, i in inputs.items()}, user))
                draw_opps()
                ui.notify("Đã lưu ngưỡng", type="positive")

            if ed:
                with ui.row().classes("gap-2"):
                    ui.button("Lưu và áp dụng", on_click=save).props("unelevated no-caps")
                    ui.button("Về mặc định", on_click=lambda: [i.set_value(O.DEFAULTS[k]) for k, i in inputs.items()]
                              ).props("flat no-caps")
            else:
                for i in inputs.values():
                    i.props("readonly")
        draw_opps()

        # ---- Bảng URL hai nguồn ----
        ui.label("URL theo hai nguồn").classes("text-lg font-semibold q-mt-md")
        counts = {m: sum(r["match"] == m for r in rows) for m in (O.MATCHED, O.GA4_ONLY, O.GSC_ONLY)}
        match_opts = {"all": f"Tất cả ({len(rows)})", O.MATCHED: f"Có cả hai nguồn ({counts[O.MATCHED]})",
                      O.GA4_ONLY: f"Chỉ có phiên AI ({counts[O.GA4_ONLY]})",
                      O.GSC_ONLY: f"Chỉ có GSC, không có phiên AI ({counts[O.GSC_ONLY]})"}
        with ui.row().classes("gap-3 items-end"):
            match_f = ui.select(match_opts, value="all", label="Ghép nguồn").props("dense outlined").classes("w-72")
            type_f = ui.select(["Tất cả"] + sorted({r["type"] for r in rows}), value="Tất cả",
                               label="Loại trang").props("dense outlined").classes("w-56")
            search = ui.input(placeholder="Tìm URL").props("dense outlined clearable").classes("w-72")
        ai_h, gsc_h = "bg-green-1", "bg-blue-1"
        pct_or_dash = "val => val === null ? '–' : " + PCT_JS[7:]
        int_vi = "val => val.toLocaleString('vi-VN')"
        table = ui.table(columns=[
            {"name": "path", "label": "URL", "field": "path", "align": "left", "sortable": True},
            {"name": "type", "label": "Loại", "field": "type", "align": "left", "sortable": True,
             "classes": "ellipsis", "style": "max-width: 110px", "headerStyle": "max-width: 110px"},
            {"name": "s", "label": "AI · Phiên", "field": "s", "align": "right", "sortable": True,
             "headerClasses": ai_h},
            {"name": "er", "label": "AI · Engage", "field": "er", "align": "right", "sortable": True,
             "headerClasses": ai_h, ":format": pct_or_dash},
            {"name": "k", "label": "AI · Key ev.", "field": "k", "align": "right", "sortable": True,
             "headerClasses": ai_h},
            {"name": "c", "label": "Web · Click", "field": "c", "align": "right", "sortable": True,
             "headerClasses": gsc_h, ":format": int_vi},
            {"name": "i", "label": "Web · Impr.", "field": "i", "align": "right", "sortable": True,
             "headerClasses": gsc_h, ":format": int_vi},
            {"name": "ctr", "label": "Web · CTR", "field": "ctr", "align": "right", "sortable": True,
             "headerClasses": gsc_h, ":format": pct_or_dash},
            {"name": "pos", "label": "Web · Vị trí", "field": "pos", "align": "right", "sortable": True,
             "headerClasses": gsc_h,
             ":format": "val => val === null ? '–' : val.toLocaleString('vi-VN', {maximumFractionDigits: 1})"},
        ], rows=[], row_key="key", pagination=25).classes("w-full").props("flat bordered dense")
        table.add_slot("body-cell-path", """
            <q-td :props="props">
              <span :title="props.row.full + (props.row.paths ? ' | GA4: ' + props.row.paths : '')"
                    class="ellipsis inline-block" style="max-width: 230px; vertical-align: bottom">{{ props.value }}</span>
              <q-badge v-if="props.row.amb" color="orange-2" text-color="orange-10" label="ghép nhiều đường dẫn"
                       class="q-ml-xs" />
            </q-td>""")

        def fill():
            table.rows = [{
                "key": r["url"], "path": r["path"], "full": r["url"], "paths": ", ".join(r["ga4_paths"]),
                "amb": r["ambiguous"], "type": r["type"], "s": r["ai_sessions"],
                "er": None if r["ai_engagement_rate"] is None else round(r["ai_engagement_rate"] * 100, 2),
                "k": r["ai_key_events"], "c": r["gsc_clicks"], "i": r["gsc_impressions"],
                "ctr": None if r["gsc_ctr"] is None else round(r["gsc_ctr"] * 100, 2),
                "pos": None if r["gsc_position"] is None else round(r["gsc_position"], 1)}
                for r in rows if (match_f.value == "all" or r["match"] == match_f.value)
                and (type_f.value == "Tất cả" or r["type"] == type_f.value)]

        fill()
        match_f.on_value_change(lambda _: fill())
        type_f.on_value_change(lambda _: fill())
        search.bind_value(table, "filter")
        ui.label("AI = phiên từ AI assistant (GA4, nền xanh lá) · Web = Google Web Search (GSC, nền xanh dương). "
                 f"Gồm mọi trang có phiên AI và {O.TOP_GSC_PAGES} trang nhiều impression GSC nhất trong kỳ. Vị trí TB "
                 "của GSC chỉ để tham khảo, thứ hạng nghiệm thu xem ở màn Check rank. Bộ lọc nguồn/quốc gia chỉ áp "
                 "cho cột GA4.").classes("text-xs muted")
        with ui.row().classes("gap-2"):
            ui.button("Tải CSV bảng URL", icon="download", on_click=lambda: download_rows(
                "co-hoi-url", ["url", "type", "match", "ga4_landing_paths", "ai_sessions", "ai_engagement_rate",
                               "ai_key_events", "gsc_web_clicks", "gsc_web_impressions", "gsc_web_ctr",
                               "gsc_web_avg_position"],
                [[r["url"], r["type"], r["match"], " ".join(r["ga4_paths"]), r["ai_sessions"],
                  r["ai_engagement_rate"], r["ai_key_events"], r["gsc_clicks"], r["gsc_impressions"], r["gsc_ctr"],
                  r["gsc_position"]] for r in rows])).props("outline no-caps")
            ui.button("Tải CSV gợi ý", icon="download", on_click=lambda: download_rows(
                "co-hoi-goi-y", list(O.OPP_FIELDS), [[o[k] for k in O.OPP_FIELDS] for o in d["opportunities"]])
                      ).props("outline no-caps")
        ui.label(f"Nguồn: GA4 {cfg.ga4_property} (AI referral, phân loại {C.HYBRID} {C.VERSION}) · GSC Web "
                 f"{cfg.site_url} từ dữ liệu đã đồng bộ của tool · kỳ {d['period']}").classes("text-xs muted")

    def dq_data(ai, start, end):
        """Đối soát trên toàn bộ phiên AI của kỳ (không áp bộ lọc nguồn/quốc gia/trang) + trạng thái kết nối."""
        from . import ai_opportunities as O
        from . import ai_quality as Q
        f = Filters()
        summ = ai.summary(start, end, f, compare=False)
        src = ai.sources(start, end, f, compare=False)
        land = ai.landing_pages(start, end, f, compare=False, limit=1000)
        geo = ai.countries(start, end, f, compare=False, limit=250)
        conn, info = Q.connections(cfg)
        try:
            cands = Q.candidate_sources(ai, start, end)
        except Exception as e:  # noqa: BLE001
            cands = [{"source": "—", "medium": "", "channel": "", "sessions": 0, "reason": f"Không truy vấn được: {e}"}]
        with connect() as c:
            gsc = Q.gsc_status(c, cfg.site_url, date.today())
            cache = Q.cache_status(c)
            thresholds = O.get_thresholds(c)
        fresh = gsc + [Q.daily_job_status(cfg.db_path.parent / "sync.log", date.today())]
        checks = Q.ga4_checks(summ, src, land, geo)
        return {"connections": conn, "info": info, "fresh": fresh, "checks": checks, "cache": cache,
                "inventory": Q.source_inventory(src) if src["status"] != "ERROR" else {},
                "raw": src["data"].get("rawRows", []), "candidates": cands, "allow": ai.allow, "mode": ai.mode,
                "min_sample": ai.min_sample, "thresholds": thresholds}

    def dq_tab(d):
        from . import ai_quality as Q
        icons = {Q.OK: ("check_circle", "green-8"), Q.WARN: ("warning", "orange-8"), Q.ERROR: ("error", "red-8"),
                 Q.INFO: ("info", "blue-8")}
        overall = Q.summarize(d["connections"] + d["fresh"] + d["checks"])
        text = {Q.OK: "Dữ liệu ổn", Q.WARN: "Có điểm cần lưu ý", Q.ERROR: "Có lỗi cần xử lý"}[overall]
        with ui.row().classes("items-center gap-2"):
            ui.icon(icons[overall][0], color=icons[overall][1], size="28px")
            ui.label(text).classes("text-lg font-semibold")
            ui.label(f"Kỳ {state['start']:%d/%m/%Y}–{state['end']:%d/%m/%Y}, toàn bộ phiên AI (bỏ qua bộ lọc nguồn/"
                     "quốc gia/trang đích).").classes("text-sm muted")

        def check_list(title, items):
            ui.label(title).classes("text-base font-semibold q-mt-md")
            with ui.card().props("flat bordered").classes("w-full q-pa-sm gap-1"):
                for c in items:
                    with ui.row().classes("items-start gap-2 no-wrap"):
                        ui.icon(icons[c["status"]][0], color=icons[c["status"]][1], size="18px")
                        with ui.column().classes("gap-0"):
                            ui.label(c["title"]).classes("text-sm font-medium")
                            if c["detail"]:
                                ui.label(c["detail"]).classes("text-xs muted")

        check_list("Kết nối", d["connections"])
        check_list("Độ mới dữ liệu", d["fresh"])
        cache = d["cache"]
        with ui.row().classes("items-center gap-3"):
            ui.label(f"Cache GA4: {cache['entries']} truy vấn đã lưu"
                     + (f", mới nhất {cache['newest'][:16].replace('T', ' ')} UTC" if cache["newest"] else "")
                     + ". Kỳ gần đây giữ 3 giờ, kỳ đã đóng giữ 24 giờ.").classes("text-xs muted")
            ui.button("Xóa cache và tải lại", icon="refresh", on_click=lambda: load(force=True)).props(
                "flat dense no-caps")
        check_list("Đối soát số liệu GA4", d["checks"])

        ui.label("Nguồn AI").classes("text-base font-semibold q-mt-md")
        inv = d["inventory"]
        with T.kpi_row(ui):
            kpi_card("Nhận qua kênh AI Assistant của GA4", F.n(inv.get(C.NATIVE)))
            kpi_card("Nhận bổ sung theo tên nguồn", F.n(inv.get(C.FALLBACK)))
            kpi_card("Kênh AI nhưng nguồn chưa có trong danh sách", F.n(inv.get("UNMAPPED")))
        cands = d["candidates"]
        ui.label("Nguồn có tên giống AI nhưng KHÔNG tính là AI").classes("text-sm font-medium q-mt-sm")
        if cands:
            ui.table(columns=[
                {"name": "src", "label": "sessionSource", "field": "source", "align": "left"},
                {"name": "med", "label": "sessionMedium", "field": "medium", "align": "left"},
                {"name": "ch", "label": "Kênh GA4", "field": "channel", "align": "left"},
                {"name": "s", "label": "Phiên", "field": "sessions", "align": "right"},
                {"name": "r", "label": "Lý do", "field": "reason", "align": "left"},
            ], rows=[{**c, "id": i} for i, c in enumerate(cands)], row_key="id").classes("w-full").props(
                "flat bordered dense")
            ui.label("Nếu một nguồn ở đây thật sự là AI assistant, báo người quản trị để bổ sung vào danh sách. Tool "
                     "không tự cộng.").classes("text-xs muted")
        else:
            ui.label("Không có.").classes("text-sm muted")

        ui.label("Cài đặt đang dùng").classes("text-base font-semibold q-mt-md")
        allow = d["allow"]
        rows = [["Cách phân loại", f"{d['mode']} {C.VERSION}: kênh AI Assistant của GA4, cộng nguồn khớp danh sách "
                                   "bên dưới với medium không trả phí"],
                ["Medium coi là trả phí (không tính AI)", C.PAID_MEDIUM_REGEX],
                ["Tên miền AI (khớp cả subdomain)", ", ".join(f"{h} → {F.SOURCE_NAMES.get(s, s)}"
                                                               for h, s in allow.hosts.items())],
                ["Tên ghi tắt (khớp nguyên tên)", ", ".join(allow.aliases)],
                ["Key events tính vào KPI", ", ".join(d["info"].get("key_events") or []) or "N/A"],
                ["Cảnh báo mẫu nhỏ khi phiên AI dưới", str(d["min_sample"])],
                ["Ẩn % thay đổi khi kỳ trước dưới", f"{F.MIN_BASE} (hiện số kỳ trước thay vì %)"],
                ["Ngưỡng quy tắc cơ hội", "; ".join(f"{k} = {v:g}" for k, v in d["thresholds"].items())
                 + " (chỉnh ở tab Cơ hội SEO/GEO)"]]
        ui.table(columns=[{"name": "k", "label": "Mục", "field": "k", "align": "left"},
                          {"name": "v", "label": "Giá trị", "field": "v", "align": "left",
                           "style": "white-space: normal"}],
                 rows=[{"k": k, "v": v} for k, v in rows], row_key="k").classes("w-full").props("flat bordered dense")
        ui.label("Danh sách nguồn AI và key events hiện chỉ xem được. Sửa trên màn hình sẽ mở khi có đăng nhập và phân "
                 "quyền (bước 7), vì đổi danh sách làm thay đổi số AI của mọi kỳ.").classes("text-xs muted")

    # ---- Tab AI trên Google (nhập file GSC Generative AI) ----
    pending = {"parsed": None, "name": None}

    async def on_upload(e):
        from . import ai_gsc_import as G
        try:
            content, name = await e.file.read(), e.file.name
            parsed = G.parse(name, content, cfg.site_url)
        except G.ImportError_ as err:
            ui.notify(str(err), type="negative", multi_line=True, timeout=10000)
            return
        except Exception as err:  # noqa: BLE001
            ui.notify(f"Không đọc được file: {err}", type="negative", multi_line=True, timeout=10000)
            return
        pending.update(parsed=parsed, name=name)
        st = parsed["stats"]
        with ui.dialog() as dlg, ui.card().style("min-width: 560px"):
            ui.label("Kiểm tra trước khi nhập").classes("text-lg font-semibold")
            for k, v in [("File", name),
                         ("Kỳ (theo ngày trong file)", f"{parsed['period_start']} → {parsed['period_end']} "
                                                        f"({st['days']} ngày, giờ Pacific)"),
                         ("Loại tìm kiếm", parsed["search_type_raw"] or "không ghi"),
                         ("Tổng impression (theo property)", F.n(st["total_chart"])),
                         ("Số dòng", f"{st['pages']} trang · {st['countries']} quốc gia · {st['devices']} thiết bị")]:
                with ui.row().classes("gap-2 no-wrap"):
                    ui.label(k).classes("text-xs muted").style("min-width: 190px")
                    ui.label(v).classes("text-sm")
            notes = []
            if st["pages_capped"]:
                notes.append(f"Bảng trang bị GSC cắt ở {G.PAGE_ROW_LIMIT} dòng: chỉ có các trang từ "
                             f"{st['min_page_impressions']} impression trở lên.")
            if any(st["unknown_zero"].values()):
                notes.append(f"{sum(st['unknown_zero'].values())} ô hiện ~ hoặc - trong GSC (file ghi 0): lưu là "
                             "'không rõ', không tính là 0.")
            with connect() as c:
                earlier = G.imports(c, cfg.site_url)
            overlap = [i for i in earlier
                       if i["search_type"] == parsed["search_type"] and i["period_start"] <= parsed["period_end"]
                       and i["period_end"] >= parsed["period_start"]]
            if overlap:
                notes.append(f"Trùng ngày với {len(overlap)} lần nhập trước: số theo ngày sẽ lấy từ file này.")
            # AI Overviews là một phần của impression Google Web: AI lớn hơn Web là dấu hiệu file/đọc file sai.
            with connect() as c:
                web = G.web_daily(c, cfg.site_url, date.fromisoformat(parsed["period_start"]),
                                  date.fromisoformat(parsed["period_end"]))
            both = [d for d, v in parsed["daily"].items() if v and web.get(d)]
            if both and sum(parsed["daily"][d] for d in both) > sum(web[d] for d in both):
                notes.append("⚠ Tổng impression AI Overviews LỚN HƠN tổng impression Google Web cùng ngày, điều không "
                             "thể xảy ra. Kiểm tra lại file (đúng property, đúng báo cáo Search) trước khi nhập.")
            for t in notes:
                ui.label("• " + t).classes("text-sm")
            with ui.row().classes("gap-2 q-mt-sm"):
                ui.button("Nhập", on_click=lambda: (do_import(), dlg.close())).props("unelevated no-caps")
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
        dlg.open()

    def do_import():
        from . import ai_gsc_import as G
        with connect() as c:
            iid = G.save(c, cfg.site_url, pending["parsed"], pending["name"], user)
        ui.notify(f"Đã nhập (lần #{iid})", type="positive")
        state["dq"] = None
        render.refresh()

    def remove_import(iid):
        from . import ai_gsc_import as G

        def go():
            with connect() as c:
                G.delete(c, cfg.site_url, iid, user)
            dlg.close()
            state["dq"] = None
            render.refresh()

        with ui.dialog() as dlg, ui.card():
            ui.label(f"Ẩn lần nhập #{iid}? Số theo ngày sẽ lấy lại từ lần nhập cũ hơn (nếu có). Lần nhập vẫn được "
                     "giữ trong lịch sử để đối soát.").classes("text-sm")
            with ui.row():
                ui.button("Ẩn lần nhập", on_click=go).props("unelevated color=negative no-caps")
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
        dlg.open()

    def gai_tab():
        from . import ai_gsc_import as G
        from . import ai_opportunities as O
        with ui.card().props("flat").classes("w-full q-pa-sm").style("background: #EEF4FF; border: 1px solid #C7D7F5"):
            ui.label("Số lần trang của site được hiển thị trong AI Overviews và AI Mode của Google, lấy từ báo cáo "
                     "Generative AI của GSC. Chỉ có impression (không có click), chỉ Web dạng chữ. GSC không có API "
                     "cho báo cáo này nên phải xuất file và nhập tay. Đây là kênh khác với phiên từ ChatGPT/Gemini ở "
                     "các tab trước: không cộng hai loại số với nhau.").classes("text-sm")
        with ui.row().classes("items-center gap-3" + ("" if ed else " hidden")):
            if ed:
                ui.upload(label="Nhập file export (.zip CSV hoặc .xlsx)", auto_upload=True, max_files=1,
                          on_upload=on_upload).props('accept=".zip,.xlsx" flat bordered').classes("w-96")
            ui.label("GSC → Hiệu suất → Generative AI (Search) → chọn kỳ → Export → Download CSV. Không lọc thêm "
                     "trang/quốc gia/thiết bị.").classes("text-xs muted")
        with connect() as c:
            imps = G.imports(c, cfg.site_url)
            if not imps:
                with ui.card().props("flat bordered").classes("w-full q-pa-lg items-center"):
                    ui.icon("upload_file", size="40px", color="grey-6")
                    ui.label("Chưa có dữ liệu").classes("text-base font-semibold")
                    ui.label("Chưa nhập file nào, nên tool không biết số impression AI Overviews (không phải bằng 0)."
                             ).classes("text-sm muted")
                return
            start, end = state["start"], state["end"]
            tot = G.period_total(c, cfg.site_url, start, end)
            web = G.web_daily(c, cfg.site_url, start, end)
            ai_d = G.daily(c, cfg.site_url, start, end)
            all_d = G.daily(c, cfg.site_url, date(2000, 1, 1), date(2100, 1, 1))
            web_all = G.web_daily(c, cfg.site_url, min(map(date.fromisoformat, all_d)),
                                  max(map(date.fromisoformat, all_d))) if all_d else {}
            latest = imps[0]
            pages = G.breakdown(c, latest["id"], "page")
            countries = G.breakdown(c, latest["id"], "country")
            devices = G.breakdown(c, latest["id"], "device")
            gsc_pages = O.gsc_by_url(c, cfg.site_url, date.fromisoformat(latest["period_start"]),
                                     date.fromisoformat(latest["period_end"]))
            types = dict(c.execute("SELECT id, type FROM urls WHERE site = ?", (cfg.site_url,)).fetchall())

        # ---- KPI kỳ đang chọn ----
        both = [d for d, v in ai_d.items() if v and web.get(d)]
        share = sum(ai_d[d] for d in both) / sum(web[d] for d in both) if both else None
        last = max(all_d) if all_d else None
        with T.kpi_row(ui):
            if tot["impressions"] is not None:
                kpi_card("Impression AI Overviews / AI Mode", F.n(tot["impressions"]),
                         hint=f"kỳ {start:%d/%m}–{end:%d/%m}, đủ {tot['covered']}/{tot['days']} ngày")
            else:
                kpi_card("Impression AI Overviews / AI Mode", "Thiếu dữ liệu",
                         hint=f"file đã nhập phủ {tot['covered']}/{tot['days']} ngày của kỳ đang chọn")
            kpi_card("Tỷ lệ trên impression GSC Web", F.pct(share),
                     hint=f"tính trên {len(both)} ngày có cả hai số (cùng tính theo property)")
            kpi_card("Dữ liệu tới ngày", (last[8:10] + "/" + last[5:7] + "/" + last[:4]) if last else "N/A",
                     hint=f"lần nhập gần nhất {latest['imported_at'][:10]} · {latest['user']}")
        if tot["status"] == "PARTIAL":
            ui.label("Kỳ đang chọn chưa được file nào phủ hết: không hiện tổng để tránh số thấp hơn thực tế. Nhập file "
                     "mới hơn, hoặc chọn kỳ nằm trong các ngày đã nhập.").classes("text-xs text-orange-9")

        # ---- Xu hướng theo tuần (toàn bộ ngày đã nhập) ----
        weeks: dict[str, list] = {}
        for d, v in sorted(all_d.items()):
            dd = date.fromisoformat(d)
            weeks.setdefault((dd - timedelta(days=dd.weekday())).isoformat(), []).append((d, v))
        labels, bars, line = [], [], []
        for w, items in weeks.items():
            full = len(items) == 7 and all(v is not None for _, v in items)
            labels.append(w[8:10] + "/" + w[5:7] + ("" if full else "*"))
            s = sum(v for _, v in items if v)
            bars.append(s if full else None)
            wv = sum(web_all.get(d, 0) for d, v in items if v)
            line.append(round(s / wv * 100, 2) if full and wv else None)
        ui.label("Theo tuần (thứ Hai)").classes("text-lg font-semibold q-mt-md")
        ui.echart({"tooltip": {"trigger": "axis"}, "legend": {"bottom": 0},
                   "grid": {"left": 64, "right": 56, "top": 32, "bottom": 48},
                   "xAxis": {"type": "category", "data": labels},
                   "yAxis": [{"type": "value", "name": "Impression"},
                             {"type": "value", "name": "% trên Web", "splitLine": {"show": False}}],
                   "series": [{"name": "Impression AI Overviews / AI Mode", "type": "bar", "data": bars,
                               "itemStyle": {"color": GREEN}},
                              {"name": "% trên impression GSC Web (trục phải)", "type": "line", "yAxisIndex": 1,
                               "data": line, "itemStyle": {"color": BLUE}}]}).classes("w-full").style("height: 280px")
        ui.label("* tuần chưa đủ 7 ngày trong các file đã nhập: không vẽ để tránh hiểu nhầm là giảm. Ngày theo giờ "
                 "Pacific như mọi số GSC.").classes("text-xs muted")

        # ---- Theo trang / quốc gia / thiết bị (của một lần nhập) ----
        p0, p1 = latest["period_start"], latest["period_end"]
        ui.label(f"Theo trang · lần nhập #{latest['id']} ({p0} → {p1})").classes("text-lg font-semibold q-mt-md")
        if latest["stats"].get("pages_capped"):
            ui.label(f"GSC chỉ xuất {G.PAGE_ROW_LIMIT} trang nhiều impression nhất (thấp nhất "
                     f"{latest['stats'].get('min_page_impressions')}): trang ít hơn không có trong bảng. Tổng theo trang "
                     "cũng khác tổng site vì GSC tính theo trang, không cộng các dòng để ra tổng.").classes(
                "text-xs text-orange-9")
        prow = []
        for r in pages:
            g = gsc_pages.get(r["url_id"]) if r["url_id"] else None
            wi = g["impressions"] if g else None
            prow.append({"url": r["key"], "path": r["key"].replace(cfg.site_url.rstrip("/"), "") or "/",
                         "type": types.get(r["url_id"]) or ("Chưa có trong dữ liệu GSC" if not r["url_id"]
                                                             else "Chờ đọc schema"),
                         "ai": r["impressions"], "web": wi,
                         "ratio": round(r["impressions"] / wi * 100, 1) if r["impressions"] and wi else None})
        type_f = ui.select(["Tất cả"] + sorted({r["type"] for r in prow}), value="Tất cả", label="Loại trang").props(
            "dense outlined").classes("w-56")
        search = ui.input(placeholder="Tìm URL").props("dense outlined clearable").classes("w-72")
        dash = "val => val === null ? 'N/A' : val.toLocaleString('vi-VN')"
        table = ui.table(columns=[
            {"name": "path", "label": "URL", "field": "path", "align": "left", "sortable": True},
            {"name": "type", "label": "Loại", "field": "type", "align": "left", "sortable": True},
            {"name": "ai", "label": "Impression AI Overviews / AI Mode", "field": "ai", "align": "right",
             "sortable": True, ":format": dash},
            {"name": "web", "label": "Impression GSC Web (cùng kỳ)", "field": "web", "align": "right",
             "sortable": True, ":format": dash},
            {"name": "ratio", "label": "AI / Web", "field": "ratio", "align": "right", "sortable": True,
             ":format": "val => val === null ? 'N/A' : val.toLocaleString('vi-VN') + '%'"},
        ], rows=[], row_key="url", pagination=20).classes("w-full").props("flat bordered dense")

        def fill():
            table.rows = [r for r in prow if type_f.value == "Tất cả" or r["type"] == type_f.value]

        fill()
        type_f.on_value_change(lambda _: fill())
        search.bind_value(table, "filter")
        with ui.row().classes("w-full gap-6 items-start q-mt-md"):
            with ui.column().classes("gap-1").style("flex: 1"):
                ui.label("Theo quốc gia (top 15)").classes("text-base font-semibold")
                ui.table(columns=[{"name": "k", "label": "Quốc gia", "field": "k", "align": "left"},
                                  {"name": "v", "label": "Impression", "field": "v", "align": "right"}],
                         rows=[{"k": r["key"], "v": F.n(r["impressions"])} for r in countries[:15]],
                         row_key="k").classes("w-full").props("flat bordered dense")
            with ui.column().classes("gap-1").style("flex: 1"):
                ui.label("Theo thiết bị").classes("text-base font-semibold")
                names = {"Mobile": "Điện thoại", "Desktop": "Máy tính", "Tablet": "Máy tính bảng"}
                T.donut(ui, [(names.get(r["key"], r["key"]), r["impressions"] or 0) for r in devices],
                        ["#1E7C31", "#2563EB", "#B7791F", "#8C8A7E"], "impression")
        ui.button("Tải CSV theo trang", icon="download", on_click=lambda: download_rows(
            f"aio-trang-{p0}_{p1}", ["url", "type", "aio_impressions", "gsc_web_impressions_same_period"],
            [[r["url"], r["type"], r["ai"], r["web"]] for r in prow])).props("outline no-caps")

        # ---- Lịch sử nhập ----
        with ui.expansion(f"Lịch sử nhập ({len(imps)} lần)", icon="history").classes("w-full q-mt-md"):
            for i in imps:
                with ui.row().classes("items-center gap-3 no-wrap"):
                    ui.label(f"#{i['id']} · {i['period_start']} → {i['period_end']} · "
                             f"{'Web dạng chữ' if i['search_type'] == 'text' else 'Web đa phương thức'} · "
                             f"{F.n(i['stats'].get('total_chart'))} impression · nhập {i['imported_at'][:16]} "
                             f"bởi {i['user']} · {i['file_name']}").classes("text-sm")
                    if ed:
                        ui.button(icon="visibility_off", on_click=lambda _, x=i["id"]: remove_import(x)).props(
                            "flat dense round").tooltip("Ẩn lần nhập này")

    def download_rows(name: str, header: list[str], rows: list[list]):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([f"# AI Search & GEO - {name}", f"{state['start']}..{state['end']}",
                    f"mode={C.HYBRID} {C.VERSION}", f"property={cfg.ga4_property}",
                    f"source={state['source'] or 'all'}", f"country={state['country'] or 'all'}",
                    "rate = phân số 0–1"])
        w.writerow(header)
        w.writerows(rows)
        ui.download.content(("﻿" + buf.getvalue()).encode("utf-8"),
                            f"ai-{name}_{state['start']}_{state['end']}.csv")

    async def export_all() -> bytes:
        """Excel toàn màn theo đúng bộ lọc đang chọn (tải thêm tab chưa mở; dùng cache nên nhanh)."""
        from .ai_export import build_ai_excel
        for kind in ("land", "geo", "opp"):
            if state[kind] is None:
                await load_extra(kind)
        return await run.io_bound(lambda: build_ai_excel(state, cfg, user))

    def sources_tab(d):
        src, tr = d["sources"], d["trend"]
        if src["status"] == "ERROR":
            state["error"] = src["warnings"][0]["message"] if src["warnings"] else "Lỗi GA4"
            error_state()
            return
        warnings_box([src])
        rows = src["data"]["sources"]
        total = src["data"]["totalSessions"] or 0
        top = sorted(rows, key=lambda r: -r["sessions"])
        parts = [(F.SOURCE_NAMES.get(r["source"], r["source"]), r["sessions"]) for r in top[:5]]
        if len(top) > 5:
            parts.append(("Nguồn khác", sum(r["sessions"] for r in top[5:])))
        with ui.element("div").classes("w-full").style(
                "display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 12px"):
            with ui.element("div").classes("sr-card q-pa-md"):
                ui.label("Tỷ lệ phiên theo nguồn AI").classes("sr-section-title")
                T.donut(ui, parts, ["#1E7C31", "#7C3AED", "#2563EB", "#B7791F", "#DB2777", "#8C8A7E"], "phiên AI", 200)
            best = max(rows, key=lambda r: r.get("sessionKeyEventRate") or 0) if rows else None
            with ui.element("div").classes("sr-bento").style("grid-template-columns: repeat(2, minmax(0, 1fr))"):
                for label, value, hint in [
                    ("Phiên AI", F.n(total), "trong kỳ đang chọn"),
                    ("Số nguồn AI", str(len(rows)), "có ít nhất 1 phiên"),
                    ("Nguồn lớn nhất", F.SOURCE_NAMES.get(top[0]["source"], top[0]["source"]) if top else "–",
                     F.pct(top[0]["sessions"] / total, 0) + " phiên AI" if top and total else ""),
                    ("Key events từ AI", F.n(sum(r["keyEvents"] or 0 for r in rows)),
                     f"tỷ lệ cao nhất: {F.SOURCE_NAMES.get(best['source'], best['source'])}"
                     if best and best.get("sessionKeyEventRate") else ""),
                ]:
                    with ui.element("div").classes("sr-bento-tile"):
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.element("span").classes("sr-dot").style(f"background:{T.TONES['purple'][1]}")
                            ui.label(label).classes("text-xs muted")
                        ui.label(value).classes("sr-metric-value num")
                        if hint:
                            ui.label(hint).classes("text-xs muted")
        ui.label("Bấm một nguồn để lọc cả màn theo nguồn đó.").classes("text-xs muted")
        table = ui.table(columns=[
            {"name": "name", "label": "Nguồn AI", "field": "name", "align": "left"},
            {"name": "s", "label": "Phiên", "field": "s", "align": "right"},
            {"name": "share", "label": "% phiên AI", "field": "share", "align": "right"},
            {"name": "chg", "label": "So với kỳ trước", "field": "chg", "align": "right"},
            {"name": "er", "label": "Engagement rate", "field": "er", "align": "right"},
            {"name": "t", "label": "TG tương tác TB/phiên", "field": "t", "align": "right"},
            {"name": "k", "label": "Key events", "field": "k", "align": "right"},
            {"name": "kr", "label": "Session key event rate", "field": "kr", "align": "right"},
            {"name": "m", "label": "Cách nhận diện", "field": "m", "align": "left"},
        ], rows=[{"code": r["source"], "name": F.SOURCE_NAMES.get(r["source"], r["source"]), "s": F.n(r["sessions"]),
                  "share": F.pct(r["sessions"] / total if total else None, 1), "chg": F.delta_pct(r.get("sessionsChange"), r.get("sessionsPrev")),
                  "er": F.pct(r.get("engagementRate")), "t": F.mmss(r.get("avgEngagementTimePerSession")),
                  "k": F.n(r["keyEvents"]), "kr": F.pct(r.get("sessionKeyEventRate")),
                  "m": " + ".join(F.METHOD_NAMES.get(m, m) for m in r["methods"] if m)} for r in rows],
            row_key="code").classes("w-full cursor-pointer").props("flat bordered dense")
        table.on("rowClick", lambda e: set_filter("source", e.args[1]["code"]) if e.args[1]["code"] != "OTHER_AI"
                 else ui.notify("Nguồn chưa nhận diện không lọc riêng được", type="warning"))
        ui.button("Tải CSV bảng nguồn", icon="download", on_click=lambda: download_csv(src)).props("outline no-caps")

        pts = tr["data"].get("points", [])
        key = "week" if tr["data"].get("interval") == "week" else "date"
        labels = [(p[key][8:10] + "/" + p[key][5:7]) if key == "week" else (p["date"][6:] + "/" + p["date"][4:6])
                  for p in pts]
        series = [s for s in tr["data"].get("series", []) if s not in ("AI Assistants", "Organic Search",
                                                                         "Organic Social")]
        palette = [GREEN, LIME, BLUE, "#9333EA", "#DB2777", "#8C8A7E"]
        ui.label("Phiên theo nguồn (top 5 + AI khác)").classes("text-lg font-semibold q-mt-md")
        ui.echart({
            "tooltip": {"trigger": "axis"}, "legend": {"bottom": 0},
            "grid": {"left": 48, "right": 16, "top": 24, "bottom": 48},
            "xAxis": {"type": "category", "data": labels}, "yAxis": {"type": "value", "name": "Phiên"},
            "series": [{"name": F.SOURCE_NAMES.get(s, s), "type": "line", "data": [p.get(s, 0) for p in pts],
                        "itemStyle": {"color": palette[i % len(palette)]}} for i, s in enumerate(series)],
        }).classes("w-full").style("height: 280px")
        if state["source"]:
            ui.label("Biểu đồ đang lọc theo nguồn đã chọn.").classes("text-xs muted")

        with ui.expansion("Chi tiết source / medium / kênh GA4 (để đối soát danh sách nhận diện)",
                          icon="manage_search").classes("w-full"):
            ui.table(columns=[
                {"name": "src", "label": "sessionSource", "field": "src", "align": "left"},
                {"name": "med", "label": "sessionMedium", "field": "med", "align": "left"},
                {"name": "ch", "label": "Kênh GA4", "field": "ch", "align": "left"},
                {"name": "s", "label": "Phiên", "field": "s", "align": "right"},
                {"name": "sub", "label": "Nhận là", "field": "sub", "align": "left"},
                {"name": "m", "label": "Cách nhận diện", "field": "m", "align": "left"},
            ], rows=[{"id": i, "src": r["sessionSource"], "med": r["sessionMedium"], "ch": r["sessionDefaultChannelGroup"],
                      "s": F.n(r["sessions"]), "sub": F.SOURCE_NAMES.get(r["subsource"], r["subsource"]),
                      "m": F.METHOD_NAMES.get(r["method"], r["method"])} for i, r in enumerate(src["data"]["rawRows"])],
                row_key="id", pagination=20).classes("w-full").props("flat dense")
        provenance(src)

    def download_csv(src):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["# AI Search & GEO - Nguồn AI", f"{state['start']}..{state['end']}",
                    f"mode={src['classification']['mode']} {src['classification']['version']}",
                    f"property={src['sourceMeta']['propertyId']}", f"queriedAt={src['sourceMeta']['queriedAt']}",
                    f"country={state['country'] or 'all'}"])
        w.writerow(["source", "sessions", "sessions_prev", "sessions_change", "engaged_sessions", "engagement_rate",
                    "avg_engagement_time_s", "key_events", "session_key_event_rate", "classification_methods"])
        for r in src["data"]["sources"]:
            w.writerow([r["source"], r["sessions"], r.get("sessionsPrev"), r.get("sessionsChange"),
                        r.get("engagedSessions"), r.get("engagementRate"), r.get("avgEngagementTimePerSession"),
                        r["keyEvents"], r.get("sessionKeyEventRate"), "+".join(m for m in r["methods"] if m)])
        ui.download.content(("﻿" + buf.getvalue()).encode("utf-8"),
                            f"ai-nguon_{state['start']}_{state['end']}.csv")

    tabs.on_value_change(lambda e: (lazy_load(e.value), sync_url()))
    draw_chips()
    render()
    ui.timer(0.05, lambda: load(), once=True)
