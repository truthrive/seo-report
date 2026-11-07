"""Tab Nguồn tìm kiếm (/nguon, mục URL & Index): click / hiển thị từ tìm kiếm web, hình ảnh, video, tab Tin tức,
Google Discover và Google News (Search Console, gsc_types.py). Chọn một nguồn để xem xu hướng theo tuần và trang
hàng đầu của nguồn đó."""
import io
from datetime import date, timedelta
from urllib.parse import urlparse

from . import access as A
from . import ai_format as F
from . import gsc_types as GT
from . import ui_theme as T

PERIODS = {28: "28 ngày", 90: "90 ngày", 365: "12 tháng"}
ICONS = {"web": "search", "image": "image", "video": "smart_display", "news": "newspaper",
         "discover": "explore", "googleNews": "feed"}


def build_sources_page(ui, cfg, connect, user) -> None:
    from nicegui import run
    site = cfg.site_url
    ed = A.can_edit(user)
    right = T.page_header(ui, "travel_explore", "Nguồn tìm kiếm",
                          "Khách đến từ đâu trên Google: tìm kiếm web, hình ảnh, video, tab Tin tức, Discover, Google "
                          "News. Số của Search Console, tự lấy mỗi ngày.")
    right.classes("no-wrap")
    state = {"type": "web", "days": 28}

    async def fetch(btn) -> None:
        if not ed:
            return
        from contextlib import closing

        from . import auth, db
        btn.props("loading")

        def work():
            logs: list[str] = []
            svc = auth.build_service(auth.get_credentials(cfg))
            with closing(db.connect(cfg.db_path)) as c:
                GT.refresh(c, site, svc, log=logs.append)
            return logs
        try:
            logs = await run.io_bound(work)
            ui.notify("Đã lấy số mới" + (f" ({len(logs)} lỗi)" if logs else ""), caption=" · ".join(logs)[:300] or None,
                      type="warning" if logs else "positive", position="bottom-right", classes="sr-toast",
                      multi_line=True)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify("Không lấy được số Search Console", caption=str(e)[:300], type="negative",
                      position="bottom-right", timeout=0, close_button="Đóng")
        btn.props(remove="loading")
        body.refresh()

    if ed:
        with right:
            b = ui.button("Lấy số mới", icon="refresh").props("unelevated no-caps color=primary").style(
                "white-space:nowrap")
            b.on_click(lambda _, b=b: fetch(b))
            b.tooltip("Lấy lại số các nguồn tìm kiếm và sitemap từ Search Console")

    @ui.refreshable
    def body():
        with connect() as c:
            last = GT.last_date(c, site)
        if not last:
            T.empty_state(ui, "travel_explore", "Chưa lấy số các nguồn tìm kiếm",
                          "Bấm “Lấy số mới”, hoặc đợi lượt chạy tự động sáng mai." if ed else
                          "Số sẽ có sau lượt lấy đầu tiên.")
            return
        end = date.fromisoformat(last)
        n = state["days"]
        start, p_end = end - timedelta(days=n - 1), end - timedelta(days=n)
        p_start = p_end - timedelta(days=n - 1)
        with connect() as c:
            now, prev = GT.totals(c, site, start, end), GT.totals(c, site, p_start, p_end)
            ser = GT.series(c, site, state["type"], end - timedelta(days=364), end)
            pages, period = GT.top_pages(c, site, state["type"])
        with ui.row().classes("items-center gap-2 q-mb-sm"):
            t_ = ui.toggle(PERIODS, value=n, on_change=lambda e: (state.update(days=e.value), body.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
            t_.props["aria-label"] = "Khoảng thời gian"
            ui.label(f"{start:%d/%m/%Y} – {end:%d/%m/%Y} · so với {n} ngày liền trước · bấm một nguồn để xem chi tiết") \
                .classes("text-xs muted")
        total_clicks = sum(v["clicks"] for v in now.values()) or 1
        with ui.element("div").classes("sr-src-grid w-full"):
            for t, name in GT.TYPES.items():
                v, p = now[t], prev[t]
                on = state["type"] == t
                cell = ui.element("button").classes("sr-cwv-cell" + (" on" if on else "")).props('type="button"')
                cell.on("click", lambda _, t=t: (state.update(type=t), body.refresh()))
                with cell:
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon(ICONS[t], size="16px").classes("muted")
                        ui.label(name).classes("text-xs muted")
                    ui.html(f"<span class='sr-cwv-num'>{F.n(v['clicks'])}</span> <span class='text-xs muted'>click"
                            f"</span>")
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        d = v["clicks"] - p["clicks"]
                        if p["clicks"] and d:
                            pct = abs(d) / p["clicks"] * 100
                            ui.label(f"{'▲' if d > 0 else '▼'} {pct:.0f}%" if pct >= 1 else
                                     f"{'▲' if d > 0 else '▼'} <1%").classes(
                                "text-xs").style(f"color:{'#1E7C31' if d > 0 else '#C2410C'}; font-weight:600")
                        elif not p["clicks"] and v["clicks"]:
                            ui.label("mới").classes("text-xs muted")
                        ui.label(f"{F.n(v['impressions'])} hiển thị · {v['clicks'] / total_clicks * 100:.0f}% click") \
                            .classes("text-xs muted")
        t = state["type"]
        cur = now[t]
        with ui.element("div").classes("sr-bl-two w-full"):
            with T.section(ui, f"{GT.TYPES[t]} theo tuần", ICONS[t], "Click, 12 tháng gần nhất (rê chuột xem hiển thị)"):
                if not ser:
                    ui.label("Chưa có số cho nguồn này: website chưa xuất hiện ở đây.").classes("text-sm muted")
                else:
                    ui.echart({"animation": False, "grid": {"left": 44, "right": 12, "top": 14, "bottom": 26},
                               "tooltip": {"trigger": "axis", ":formatter": (
                                   "ps => ps[0].axisValue + '<br/>' + ps[0].marker + 'Click: <b>' + "
                                   "ps[0].value.toLocaleString('vi-VN') + '</b><br/>Hiển thị: ' + "
                                   f"{[s['impressions'] for s in ser]}[ps[0].dataIndex].toLocaleString('vi-VN')")},
                               "xAxis": {"type": "category", "data": [f"{s['week'][8:10]}/{s['week'][5:7]}" for s in ser],
                                         "axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                                         "axisLabel": {"color": "#8C8A7E", "fontSize": 11}},
                               "yAxis": {"type": "value", "splitNumber": 4, "splitLine": {"lineStyle": {"color": "#EEECE4"}},
                                         "axisLabel": {"color": "#8C8A7E", "fontSize": 11}},
                               "series": [{"type": "bar", "barMaxWidth": 14, "data": [s["clicks"] for s in ser],
                                           "itemStyle": {"color": "#2a78d6", "borderRadius": [3, 3, 0, 0]}}]}
                              ).classes("w-full").style("height:220px")
            with T.section(ui, "Chỉ số", "insights", f"{n} ngày gần nhất"):
                for label, val in (("Click", F.n(cur["clicks"])), ("Hiển thị", F.n(cur["impressions"])),
                                   ("Tỷ lệ click (CTR)", f"{cur['ctr'] * 100:.1f}%".replace(".", ",") if cur["ctr"] else "–"),
                                   ("Vị trí trung bình", f"{cur['position']:.1f}".replace(".", ",") if cur["position"]
                                    else ("Google không trả" if t in GT.NO_POSITION else "–"))):
                    with ui.row().classes("w-full items-center no-wrap sr-cwv-part"):
                        ui.label(label).classes("text-sm").style("flex:1 1 0")
                        ui.label(val).classes("num text-sm font-semibold")
        with T.section(ui, f"Trang hàng đầu · {GT.TYPES[t]}", "description",
                       (f"{date.fromisoformat(period[0]):%d/%m} – {date.fromisoformat(period[1]):%d/%m}, so với 28 ngày "
                        "trước" if period else "Chưa có trang nào")):
            if not pages:
                ui.label("Không có trang nào có số ở nguồn này.").classes("text-sm muted")
                return
            rows = [{"id": i, "page": urlparse(r["page"]).path or "/", "url": r["page"], "clicks": r["clicks"],
                     "impressions": r["impressions"],
                     "ctr": f"{r['ctr'] * 100:.1f}%".replace(".", ",") if r["ctr"] else "–",
                     "position": f"{r['position']:.1f}".replace(".", ",") if r["position"] else "–",
                     "change": (r["clicks"] - r["prev_clicks"]) if r["prev_clicks"] is not None else None}
                    for i, r in enumerate(pages)]
            cols = [{"name": "page", "label": "Trang", "field": "page", "align": "left", "sortable": True},
                    {"name": "clicks", "label": "Click", "field": "clicks", "align": "right", "sortable": True,
                     "headerStyle": "width:90px"},
                    {"name": "change", "label": "So với trước", "field": "change", "align": "right", "sortable": True,
                     "headerStyle": "width:120px"},
                    {"name": "impressions", "label": "Hiển thị", "field": "impressions", "align": "right",
                     "sortable": True, "headerStyle": "width:100px"},
                    {"name": "ctr", "label": "CTR", "field": "ctr", "align": "right", "headerStyle": "width:80px"}]
            if t not in GT.NO_POSITION:
                cols.append({"name": "position", "label": "Vị trí", "field": "position", "align": "right",
                             "headerStyle": "width:80px"})
            tb = ui.table(columns=cols, rows=rows, row_key="id", pagination=20).props(
                "flat dense binary-state-sort").classes("w-full")
            tb.add_slot("body-cell-page", """
                <q-td :props="props"><a :href="props.row.url" target="_blank" rel="noopener" class="sr-bl-link"
                  :title="props.row.url"><span class="sr-bl-anchor" style="max-width:520px; display:inline-block">
                  {{ props.value }}</span></a></q-td>""")
            tb.add_slot("body-cell-change", """
                <q-td :props="props" class="text-right">
                  <span v-if="props.value === null" class="text-xs muted">mới</span>
                  <span v-else-if="props.value" class="num" :style="{color: props.value > 0 ? '#1E7C31' : '#C2410C',
                    fontWeight: 600}">{{ props.value > 0 ? '▲' : '▼' }} {{ Math.abs(props.value) }}</span>
                  <span v-else class="muted">–</span></q-td>""")

    def make_xlsx() -> bytes:
        from openpyxl import Workbook

        from .export import INT, _sheet
        wb = Workbook()
        wb.remove(wb.active)
        with connect() as c:
            daily = c.execute("SELECT date, type, clicks, impressions, position FROM gsc_type_daily WHERE site = ? "
                              "ORDER BY date, type", (site,)).fetchall()
            tops = {t: GT.top_pages(c, site, t)[0] for t in GT.TYPES}
        _sheet(wb, "Theo ngày", [("Ngày", 12, None), ("Nguồn", 18, None), ("Click", 10, INT), ("Hiển thị", 12, INT),
                                 ("Vị trí", 9, "0.0")],
               [[d, GT.TYPES.get(t, t), c, i, p] for d, t, c, i, p in daily])
        _sheet(wb, "Trang hàng đầu", [("Nguồn", 18, None), ("Trang", 70, None), ("Click", 10, INT),
                                      ("Click 28 ngày trước", 16, INT), ("Hiển thị", 12, INT), ("Vị trí", 9, "0.0")],
               [[GT.TYPES[t], r["page"], r["clicks"], r["prev_clicks"], r["impressions"], r["position"]]
                for t, rs in tops.items() for r in rs])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    from .web_export import export_menu
    with right:
        export_menu(ui, cfg, connect, f"nguon-tim-kiem_{date.today():%Y-%m-%d}", make_xlsx,
                    label="Xuất nguồn tìm kiếm (Excel / Google Sheets)", user=user, icon_only=True, category="url")
    body()
