"""Trang Tốc độ & Core Web Vitals (/toc-do, mục riêng trong nhóm SEO): số người dùng thật của cả website (CrUX, theo tuần) và
điểm PageSpeed của các trang quan trọng kèm việc nên sửa. Dữ liệu ở cwv.py; lấy mỗi tuần, miễn phí."""
import io
from datetime import date, datetime
from urllib.parse import urlparse

from . import access as A
from . import cwv as C
from . import cwv_audit as CA
from . import ui_theme as T

LEVELS = {"high": ("Cần sửa", "red", "error"), "medium": ("Nên sửa", "amber", "warning"),
          "info": ("Tham khảo", "blue", "info"), "ok": ("Ổn", "green", "check_circle")}
RATING = {"good": ("Tốt", "green", "check_circle"), "ni": ("Cần cải thiện", "amber", "warning"),
          "poor": ("Kém", "red", "error"), "none": ("Chưa có số", "grey", "remove")}
COLORS = {"good": "#1E7C31", "ni": "#B7791F", "poor": "#C2410C", "none": "#8C8A7E"}


def _score_tone(s) -> str:
    return "none" if s is None else "good" if s >= 90 else "ni" if s >= 50 else "poor"


TABS = (("overview", "Tổng quan"), ("field", "Người dùng thật"), ("pages", "Từng trang"))


def build_cwv_page(ui, cfg, connect, user, start: str = "") -> None:
    from nicegui import background_tasks, run
    ed = A.can_edit(user)
    cl = A.is_client(user)  # khách hàng: số tốc độ, không danh sách việc cần sửa / nên sửa của team
    right = T.page_header(ui, "speed", "Tốc độ & Core Web Vitals",
                          "Số người dùng Chrome thật (Google dùng để xếp hạng) và điểm PageSpeed của các trang quan "
                          "trọng nhất. Tự kiểm tra mỗi tuần.")
    right.classes("no-wrap")  # nút Kiểm tra ngay + Xuất cùng một hàng
    state = {"form": "PHONE", "metric": "lcp", "running": False, "filter": None,
             "tab": start if start in dict(TABS) else "overview"}
    has_key = bool(C.load_key(cfg))

    async def run_now(btn) -> None:
        if not ed or state["running"]:
            return
        from contextlib import closing

        from . import db
        state["running"] = True
        btn.props("loading")
        note = ui.notification("Đang kiểm tra tốc độ các trang (vài phút)…", spinner=True, timeout=None,
                               type="ongoing", position="bottom-right")

        def work():
            logs: list[str] = []
            with closing(db.connect(cfg.db_path)) as c:
                r = C.refresh(c, cfg, force=True, log=logs.append)
            return r, logs
        try:
            r, logs = await run.io_bound(work)
            note.dismiss()
            if r is None:
                ui.notify(logs[-1] if logs else "Chưa kiểm tra được", type="warning", position="bottom-right")
            else:
                ui.notify(f"Đã kiểm tra {r['pages']} trang" + (f" ({r['errors']} lỗi)" if r["errors"] else ""),
                          type="warning" if r["errors"] else "positive", position="bottom-right", classes="sr-toast")
        except Exception as e:  # noqa: BLE001
            note.dismiss()
            ui.notify("Không kiểm tra được", caption=str(e)[:300], type="negative", position="bottom-right",
                      timeout=0, close_button="Đóng")
        state["running"] = False
        btn.props(remove="loading")
        body.refresh()

    if ed and has_key:
        with right:
            b = ui.button("Kiểm tra ngay", icon="refresh").props("unelevated no-caps color=primary").style(
                "white-space:nowrap")
            b.on_click(lambda _, b=b: background_tasks.create(run_now(b)))
            b.tooltip("Lấy lại số CrUX và chạy PageSpeed cho các trang quan trọng (miễn phí, mất vài phút)")

    @ui.refreshable
    def body():
        if not has_key:
            T.empty_state(ui, "key", "Chưa có Google API key",
                          "Chủ tool vào Cài đặt tích hợp → Google API key (Core Web Vitals) để thêm key miễn phí."
                          if ed else "Số tốc độ sẽ có sau khi tool được cấu hình.")
            return
        with connect() as c:
            series = C.origin_series(c, state["form"])
            phone, desktop = C.origin_series(c, "PHONE"), C.origin_series(c, "DESKTOP")
            pages = C.latest_pages(c)
            last = C.last_run(c)
        if not last:
            T.empty_state(ui, "speed", "Chưa kiểm tra lần nào",
                          "Bấm “Kiểm tra ngay”, hoặc đợi lượt chạy tự động sáng mai." if ed else
                          "Số sẽ có sau lần kiểm tra đầu tiên.")
            return
        ui.label(f"Kiểm tra lúc {datetime.fromisoformat(last).astimezone():%H:%M %d/%m/%Y} · tự kiểm tra lại mỗi tuần") \
            .classes("text-xs muted q-mb-xs")
        checks = [] if cl else CA.audit(phone, desktop, pages)
        site_checks = [c_ for c_ in checks if not c_["pages"]]   # cả website: tab Người dùng thật
        page_checks = [c_ for c_ in checks if c_["pages"]]       # theo trang: tab Từng trang (bấm để lọc)
        badge = {"field": sum(1 for c_ in site_checks if c_["level"] == "high"),
                 "pages": sum(1 for c_ in page_checks if c_["level"] == "high")}
        with ui.tabs(value=state["tab"], on_change=lambda e: pick(e.value)).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs sr-bl-tabs"):
            for k, name in TABS:
                with ui.tab(k, name + (f" · {len(pages)}" if k == "pages" else "")):
                    if badge.get(k):
                        T.count_badge(ui, badge[k], f"{badge[k]} việc cần sửa trong tab này").classes("sr-tab-badge")
        with ui.tab_panels(value=state["tab"]).classes("w-full").props("animated=false") as panels:
            state["panels"] = panels
            with ui.tab_panel("overview").classes("q-px-none"):
                overview_tab(CA.score(phone, desktop, pages), phone, checks)
            with ui.tab_panel("field").classes("q-px-none"):
                checks_list(site_checks, "Kiểm tra cả website", filterable=False)
                site_block(series)
            with ui.tab_panel("pages").classes("q-px-none"):
                checks_list(page_checks, "Kiểm tra từng trang", filterable=True)
                pages_block(pages, checks)

    def pick(v: str) -> None:
        state["tab"] = v
        if state.get("panels") is not None:
            state["panels"].set_value(v)
        ui.run_javascript(f"history.replaceState(null, '', '/toc-do' + ('{v}' === 'overview' ? '' : '?tab={v}'))")

    def go(check: dict) -> None:
        """Từ Việc cần làm ở Tổng quan: sang đúng tab; mục theo trang thì bật luôn bộ lọc."""
        state["tab"] = "pages" if check["pages"] else "field"
        state["filter"] = check["key"] if check["pages"] else None
        body.refresh()
        ui.run_javascript(f"history.replaceState(null, '', '/toc-do?tab={state['tab']}')")

    def overview_tab(sc: dict, phone: list[dict], checks: list[dict]) -> None:
        with ui.element("div").classes("sr-cwv-top w-full"):
            with T.section(ui, "Điểm tốc độ", "speed", "Tổng hợp người dùng thật và PageSpeed"):
                with ui.row().classes("items-baseline gap-2 no-wrap"):
                    ui.html(f"<span class='sr-cwv-big' style='color:{T.TONES[sc['tone']][1]}'>"
                            f"{sc['score'] if sc['score'] is not None else '–'}</span><span class='muted'>/100</span>")
                    T.status_chip(ui, sc["grade"], sc["tone"])
                for k, label in (("phone", "Người dùng thật · điện thoại"), ("desktop", "Người dùng thật · máy tính"),
                                 ("lab", "PageSpeed trung bình các trang")):
                    v = sc["parts"][k]
                    with ui.row().classes("w-full items-center no-wrap gap-2 sr-cwv-part"):
                        ui.label(label).classes("text-sm").style("flex:1 1 0")
                        ui.label(f"{int(CA.WEIGHTS[k] * 100)}%").classes("text-xs muted")
                        ui.label(str(v) if v is not None else "chưa có").classes("num text-sm font-semibold").style(
                            "min-width:52px; text-align:right")
                ui.label("Chỉ số người dùng thật: đạt “Tốt” = 100, đúng ngưỡng “Kém” = 50. Phần chưa có số thì không "
                         "tính.").classes("text-xs muted q-mt-xs")
            todo = [c_ for c_ in checks if c_["level"] in ("high", "medium")]
            if cl:  # khách hàng: thay "Việc cần làm" bằng 3 chỉ số Core Web Vitals hiện tại trên điện thoại
                with T.section(ui, "Core Web Vitals trên điện thoại", "smartphone", "Người dùng Chrome thật, 28 ngày"):
                    now = phone[-1] if phone else {}
                    names = {"good": "Tốt", "ni": "Cần cải thiện", "poor": "Kém", "none": "Chưa có số"}
                    for m in C.CORE:
                        r = C.rating(m, now.get(m))
                        with ui.row().classes("w-full items-center no-wrap gap-2 sr-cwv-part"):
                            ui.label(C.NAMES.get(m, m.upper())).classes("text-sm").style("flex:1 1 0")
                            ui.label(names.get(r, "")).classes("text-xs").style(f"color:{COLORS.get(r, '#8C8A7E')}")
                            ui.label(C.fmt(m, now.get(m))).classes("num text-sm font-semibold").style(
                                f"min-width:64px; text-align:right; color:{COLORS.get(r, '#8C8A7E')}")
                return
            with T.section(ui, "Việc cần làm", "fact_check",
                           f"{len(todo)} việc · bấm để xem ở tab tương ứng" if todo else "Không có việc gấp"):
                if phone:
                    now = phone[-1]
                    with ui.row().classes("items-center gap-3 q-mb-sm"):
                        ui.label("Điện thoại hiện tại:").classes("text-xs muted")
                        for m in C.CORE:
                            r = C.rating(m, now.get(m))
                            ui.html(f"<span class='text-sm'>{m.upper()} <b style='color:{COLORS[r]}'>"
                                    f"{C.fmt(m, now.get(m))}</b></span>")
                if not todo:
                    ui.label("Không có việc cần sửa hoặc nên sửa.").classes("text-sm muted")
                with ui.element("div").classes("sr-au-todo"):
                    for c_ in todo:
                        label, tone, icon = LEVELS[c_["level"]]
                        row = ui.element("button").classes("sr-au-filter").props('type="button"')
                        row.on("click", lambda _, c_=c_: go(c_))
                        with row:
                            T.status_chip(ui, label, tone, icon)
                            ui.label(c_["title"]).classes("text-sm font-semibold").style("flex:1 1 0; text-align:left")
                            if c_["pages"]:
                                ui.label(f"{len(c_['pages'])} trang").classes("sr-au-num num")
                            ui.icon("chevron_right", size="18px").classes("sr-au-ico")

    def checks_list(checks: list[dict], title: str, filterable: bool) -> None:
        if not checks:
            return
        n_high = sum(1 for c_ in checks if c_["level"] == "high")
        n_med = sum(1 for c_ in checks if c_["level"] == "medium")
        sub = f"{n_high} việc cần sửa · {n_med} nên sửa" if n_high or n_med else "Không có vấn đề"
        with T.section(ui, title, "fact_check", sub + (" · bấm một mục để lọc bảng bên dưới" if filterable else "")):
            with ui.element("div").classes("sr-au-todo"):
                for c_ in checks:
                    label, tone, icon = LEVELS[c_["level"]]
                    can = filterable and bool(c_["pages"])
                    on = state["filter"] == c_["key"]
                    row = ui.element("button" if can else "div").classes(
                        "sr-au-filter" + (" on" if on else "") + ("" if can else " off"))
                    if can:
                        row.props('type="button"')
                        row.on("click", lambda _, k=c_["key"]: set_filter(k))
                    with row:
                        T.status_chip(ui, label, tone, icon)
                        with ui.column().classes("gap-0").style("min-width:0; flex:1 1 0; text-align:left"):
                            ui.label(c_["title"]).classes("text-sm font-semibold")
                            ui.label(c_["detail"]).classes("text-xs muted")
                        if can:
                            ui.label(f"{len(c_['pages'])} trang").classes("sr-au-num num")
                            ui.icon("close" if on else "filter_list", size="18px").classes("sr-au-ico")

    def set_filter(key: str) -> None:
        state["filter"] = None if state["filter"] == key else key
        state["tab"] = "pages"
        body.refresh()
        if state["filter"]:
            ui.run_javascript("document.getElementById('cwv-pages')?.scrollIntoView({behavior:'smooth', block:'start'})")

    def site_block(series) -> None:
        with T.section(ui, "Cả website · người dùng thật", "groups",
                       "Chrome UX Report: 75% lượt truy cập nhanh hơn số này, tính trên 28 ngày, cập nhật hằng tuần"):
            with ui.row().classes("items-center gap-2"):
                t_ = ui.toggle({"PHONE": "Điện thoại", "DESKTOP": "Máy tính"}, value=state["form"],
                               on_change=lambda e: (state.update(form=e.value), body.refresh())).props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                    "sr-seg")
                t_.props["aria-label"] = "Thiết bị"
            if not series:
                ui.label("Google chưa có số người dùng thật cho website này trên thiết bị này (cần đủ lượt truy cập "
                         "từ Chrome). Xem điểm PageSpeed ở tab Từng trang.").classes("text-sm muted q-py-sm")
                return
            now = series[-1]
            old = series[-5] if len(series) >= 5 else series[0]
            verdict = C.assess(now)
            label, tone, icon = {"good": ("Đạt Core Web Vitals", "green", "verified"),
                                 "ni": ("Chưa đạt: cần cải thiện", "amber", "warning"),
                                 "poor": ("Chưa đạt Core Web Vitals", "red", "error"),
                                 "none": ("Chưa đủ số", "grey", "remove")}[verdict]
            with ui.row().classes("items-center gap-2 q-mt-sm"):
                T.status_chip(ui, label, tone, icon)
                ui.label(f"kỳ đến {date.fromisoformat(now['period_end']):%d/%m/%Y}").classes("text-xs muted")
            with ui.element("div").classes("sr-cwv-grid q-mt-sm"):
                for m in ("lcp", "inp", "cls", "fcp", "ttfb"):
                    v, p = now.get(m), old.get(m)
                    r = C.rating(m, v)
                    on = state["metric"] == m
                    cell = ui.element("button").classes("sr-cwv-cell" + (" on" if on else "") +
                                                        (" core" if m in C.CORE else "")).props('type="button"')
                    cell.on("click", lambda _, m=m: (state.update(metric=m), body.refresh()))
                    with cell:
                        ui.label(C.NAMES[m]).classes("text-xs muted")
                        ui.html(f"<span class='sr-cwv-num' style='color:{COLORS[r]}'>{C.fmt(m, v)}</span>")
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.label(RATING[r][0]).classes("sr-bl-type").style(
                                f"background:{T.TONES[RATING[r][1]][0]}; color:{T.TONES[RATING[r][1]][1]}")
                            if v is not None and p is not None and abs(v - p) > (0.005 if m == "cls" else 20):
                                better = v < p
                                ui.label(f"{'▼' if better else '▲'} {C.fmt(m, abs(v - p))}").classes("text-xs").style(
                                    f"color:{'#1E7C31' if better else '#C2410C'}; font-weight:600").tooltip(
                                    f"So với kỳ đến {date.fromisoformat(old['period_end']):%d/%m} (giảm là tốt)")
            m = state["metric"]
            good, poor = C.THRESHOLDS[m]
            pts = [(s["period_end"], s.get(m)) for s in series]
            ui.echart({"animation": False, "grid": {"left": 52, "right": 70, "top": 20, "bottom": 26},
                       "tooltip": {"trigger": "axis"},
                       "xAxis": {"type": "category", "data": [f"{d[8:10]}/{d[5:7]}" for d, _ in pts],
                                 "boundaryGap": False, "axisTick": {"show": False},
                                 "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                                 "axisLabel": {"color": "#8C8A7E", "fontSize": 11}},
                       "yAxis": {"type": "value", "min": 0, "splitNumber": 4,
                                 "splitLine": {"lineStyle": {"color": "#EEECE4"}},
                                 "axisLabel": {"color": "#8C8A7E", "fontSize": 11}},
                       "series": [{"type": "line", "name": C.NAMES[m], "symbol": "circle", "symbolSize": 6,
                                   "connectNulls": True, "lineStyle": {"width": 2, "color": "#2a78d6"},
                                   "itemStyle": {"color": "#2a78d6"}, "data": [v for _, v in pts],
                                   "markLine": {"symbol": "none", "silent": True, "data": [
                                       {"yAxis": good, "lineStyle": {"color": "#1E7C31", "type": "dashed"},
                                        "label": {"formatter": "Tốt", "color": "#1E7C31"}},
                                       {"yAxis": poor, "lineStyle": {"color": "#C2410C", "type": "dashed"},
                                        "label": {"formatter": "Kém", "color": "#C2410C"}}]}}]}
                      ).classes("w-full q-mt-sm").style("height:220px")
            ui.label(f"{C.NAMES[m]} theo tuần · dưới vạch “Tốt” là đạt. Bấm ô khác để đổi chỉ số.").classes(
                "text-xs muted")

    def pages_block(pages, checks) -> None:
        if not pages:
            return
        bad = sum(1 for p in pages if p["perf"] is not None and p["perf"] < 50)
        flt = next((c_ for c_ in checks if c_["key"] == state["filter"]), None)
        all_pages = pages
        if flt:
            keep = set(flt["pages"])
            pages = [p for p in pages if p["url"] in keep]
        ui.element("div").props('id="cwv-pages"').style("position:relative; top:-70px")
        with T.section(ui, "Từng trang · PageSpeed trên điện thoại", "description",
                       f"{len(pages)} trang quan trọng (trang chủ + nhiều click nhất)"
                       + (f" · {bad} trang điểm dưới 50" if bad else "") + " · bấm một dòng để xem việc nên sửa"):
            if flt:
                T.filter_chip(ui, f"Đang lọc: {flt['title']} · {len(pages)}/{len(all_pages)} trang",
                              lambda: set_filter(flt["key"])).classes("q-mb-sm")
            rows = []
            for i, p in enumerate(pages):
                path = urlparse(p["url"]).path or "/"
                f = C.assess(p["field"])
                rows.append({"id": i, "url": p["url"], "path": path, "perf": p["perf"], "seo": p["seo"],
                             "tone": _score_tone(p["perf"]),
                             "delta": (p["perf"] - p["prev_perf"]) if p["perf"] is not None and p["prev_perf"] is not None
                             else None,
                             "lcp": C.fmt("lcp", p["lab"].get("lcp")), "lcp_r": C.rating("lcp", p["lab"].get("lcp")),
                             "cls": C.fmt("cls", p["lab"].get("cls")), "cls_r": C.rating("cls", p["lab"].get("cls")),
                             "tbt": C.fmt("inp", p["lab"].get("tbt")),
                             "field": RATING[f][0], "field_r": f, "opps": len(p["opps"]),
                             "error": C.explain_error(p["error"]) if p["error"] else ""})
            cols = [{"name": "path", "label": "Trang", "field": "path", "align": "left", "sortable": True},
                    {"name": "perf", "label": "Hiệu năng", "field": "perf", "align": "center", "sortable": True,
                     "headerStyle": "width:110px"},
                    {"name": "seo", "label": "SEO", "field": "seo", "align": "center", "sortable": True,
                     "headerStyle": "width:70px"},
                    {"name": "lcp", "label": "LCP", "field": "lcp", "align": "right", "headerStyle": "width:80px"},
                    {"name": "cls", "label": "CLS", "field": "cls", "align": "right", "headerStyle": "width:70px"},
                    {"name": "tbt", "label": "TBT", "field": "tbt", "align": "right", "headerStyle": "width:80px"},
                    {"name": "field", "label": "Người thật", "field": "field", "align": "center",
                     "headerStyle": "width:120px"},
                    {"name": "opps", "label": "Việc sửa", "field": "opps", "align": "center", "sortable": True,
                     "headerStyle": "width:80px"}]
            tb = ui.table(columns=cols, rows=rows, row_key="id").props("flat dense binary-state-sort").classes(
                "w-full sr-bl-table")
            tb.add_slot("body", r"""
                <q-tr :props="props" @click="$parent.$emit('pick', props.row)" style="cursor:pointer">
                  <q-td key="path" :props="props"><div class="sr-bl-anchor" style="max-width:300px" :title="props.row.url">
                    {{ props.row.path }}</div>
                    <div v-if="props.row.error" class="text-xs" style="color:#C2410C">Lỗi: {{ props.row.error }}</div></q-td>
                  <q-td key="perf" :props="props">
                    <span v-if="props.row.perf != null" class="sr-cwv-score" :class="props.row.tone">{{ props.row.perf }}</span>
                    <span v-else class="muted">–</span>
                    <span v-if="props.row.delta" class="text-xs q-ml-xs"
                      :style="{color: props.row.delta > 0 ? '#1E7C31' : '#C2410C', fontWeight: 600}">
                      {{ props.row.delta > 0 ? '▲' : '▼' }}{{ Math.abs(props.row.delta) }}</span></q-td>
                  <q-td key="seo" :props="props" class="num">{{ props.row.seo ?? '–' }}</q-td>
                  <q-td key="lcp" :props="props" class="num" :class="'sr-cwv-' + props.row.lcp_r">{{ props.row.lcp }}</q-td>
                  <q-td key="cls" :props="props" class="num" :class="'sr-cwv-' + props.row.cls_r">{{ props.row.cls }}</q-td>
                  <q-td key="tbt" :props="props" class="num">{{ props.row.tbt }}</q-td>
                  <q-td key="field" :props="props"><span class="sr-bl-type" :class="'sr-cwv-chip-' + props.row.field_r">
                    {{ props.row.field }}</span></q-td>
                  <q-td key="opps" :props="props" class="num">{{ props.row.opps || '–' }}</q-td>
                </q-tr>""")
            by_url = {p["url"]: p for p in pages}
            tb.on("pick", lambda e: detail(by_url[e.args["url"]]))
            ui.label("Điểm và LCP / CLS / TBT là số đo thử của Google (Lighthouse, mạng điện thoại chậm); “Người dùng "
                     "thật” là số Chrome của chính trang đó nếu đủ lượt truy cập. TBT gần với INP: càng thấp càng tốt.") \
                .classes("text-xs muted")

    def detail(p: dict) -> None:
        with ui.dialog() as dlg, ui.card().style("border-radius:14px; width:640px; max-width:94vw"):
            ui.label(urlparse(p["url"]).path or "/").classes("text-base font-semibold")
            ui.link(p["url"], p["url"], new_tab=True).classes("text-xs")
            with ui.row().classes("gap-3 q-mt-sm"):
                for k, lab in (("perf", "Hiệu năng"), ("seo", "SEO"), ("a11y", "Truy cập"), ("bp", "Thực hành tốt")):
                    with ui.column().classes("gap-0 items-center"):
                        ui.html(f"<span class='sr-cwv-score {_score_tone(p[k])}'>{p[k] if p[k] is not None else '–'}</span>")
                        ui.label(lab).classes("text-xs muted")
            if p["field"]:
                ui.label("Người dùng thật (28 ngày)").classes("text-sm font-semibold q-mt-md")
                ui.label(" · ".join(f"{m.upper()} {C.fmt(m, v)}" for m, v in p["field"].items())).classes("text-sm")
            ui.label("Việc nên sửa").classes("text-sm font-semibold q-mt-md")
            if not p["opps"]:
                ui.label("Không có việc lớn (tiết kiệm dưới 0,1 giây).").classes("text-sm muted")
            for o in p["opps"]:
                with ui.row().classes("w-full items-center no-wrap gap-2 sr-access-row"):
                    ui.label(o["title"]).classes("text-sm").style("flex:1 1 0")
                    ui.label(f"−{o['ms'] / 1000:.1f} s".replace(".", ",")).classes("num text-sm font-semibold")
            ui.link("Xem báo cáo đầy đủ trên PageSpeed Insights",
                    "https://pagespeed.web.dev/analysis?url=" + p["url"], new_tab=True).classes("text-sm q-mt-sm")
            with ui.row().classes("w-full justify-end"):
                ui.button("Đóng", on_click=dlg.close).props("flat no-caps")
        dlg.open()

    def make_xlsx() -> bytes:
        from openpyxl import Workbook

        from .export import _sheet
        with connect() as c:
            pages = C.latest_pages(c)
            ser = {f: C.origin_series(c, f) for f in ("PHONE", "DESKTOP")}
        wb = Workbook()
        wb.remove(wb.active)
        sc = CA.score(ser["PHONE"], ser["DESKTOP"], pages)
        ws = _sheet(wb, "Kiểm tra", [("Mức", 12, None), ("Mục", 50, None), ("Chi tiết", 90, None), ("Trang", 80, None)],
                    [[LEVELS[c_["level"]][0], c_["title"], c_["detail"], "\n".join(c_["pages"])]
                     for c_ in CA.audit(ser["PHONE"], ser["DESKTOP"], pages)])
        ws.append([])  # điểm ghi ở cuối sheet (đầu sheet là tiêu đề cột có bộ lọc)
        ws.append([f"Điểm tốc độ: {sc['score'] if sc['score'] is not None else '–'}/100 ({sc['grade']})"])
        ws.append([f"Người dùng thật điện thoại {sc['parts']['phone']} (50%) · máy tính {sc['parts']['desktop']} (20%) "
                   f"· PageSpeed trung bình {sc['parts']['lab']} (30%)"])
        _sheet(wb, "Từng trang", [("Trang", 60, None), ("Hiệu năng", 10, None), ("SEO", 8, None),
                                  ("Truy cập", 9, None), ("Thực hành tốt", 12, None), ("LCP (ms)", 10, "#,##0"),
                                  ("CLS", 8, "0.00"), ("TBT (ms)", 10, "#,##0"), ("Người dùng thật", 16, None),
                                  ("Việc nên sửa", 80, None)],
               [[p["url"], p["perf"], p["seo"], p["a11y"], p["bp"], p["lab"].get("lcp"), p["lab"].get("cls"),
                 p["lab"].get("tbt"), RATING[C.assess(p["field"])][0],
                 "; ".join(f"{o['title']} (−{o['ms']} ms)" for o in p["opps"])] for p in pages])
        for f, name in (("PHONE", "Website · điện thoại"), ("DESKTOP", "Website · máy tính")):
            _sheet(wb, name, [("Kỳ đến", 12, None), ("LCP (ms)", 10, "#,##0"), ("INP (ms)", 10, "#,##0"),
                              ("CLS", 8, "0.00"), ("FCP (ms)", 10, "#,##0"), ("TTFB (ms)", 10, "#,##0")],
                   [[s["period_end"], s["lcp"], s["inp"], s["cls"], s["fcp"], s["ttfb"]] for s in ser[f]])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    if has_key:
        from .web_export import export_menu
        with right:
            export_menu(ui, cfg, connect, f"toc-do_{date.today():%Y-%m-%d}", make_xlsx,
                        label="Xuất tốc độ & Core Web Vitals", user=user, icon_only=True, category="url")
    body()
