"""Tab Nguồn tìm kiếm (/nguon, mục URL & Index): click / hiển thị từ tìm kiếm web, hình ảnh, video, tab Tin tức,
Google Discover và Google News (Search Console, gsc_types.py). Chọn một nguồn để xem xu hướng theo tuần và trang
hàng đầu của nguồn đó."""
import io
from datetime import date, timedelta
from urllib.parse import urlparse

from . import access as A
from . import ai_format as F
from . import gsc_types as GT
from . import keywords as K
from . import ui_theme as T

PERIODS = {28: "28 ngày", 90: "90 ngày", 365: "12 tháng"}
ICONS = {"web": "search", "image": "image", "video": "smart_display", "news": "newspaper",
         "discover": "explore", "googleNews": "feed"}


SOURCE_TONES = {"web": "blue", "image": "purple", "video": "red", "news": "amber", "discover": "green",
                "googleNews": "lime"}


def _delta_chip(cur: int, prev: int) -> str:
    """Nhãn % thay đổi so với kỳ trước (xanh tăng / đỏ giảm); kỳ trước bằng 0 thì "mới" hoặc không có gì."""
    if not prev:
        return "<span class='sr-src-delta new'>mới</span>" if cur else ""
    d = (cur - prev) / prev * 100
    if abs(d) < 0.5:
        return "<span class='sr-src-delta flat'>≈ 0%</span>"
    txt = f"{abs(d):.1f}".replace(".", ",") if abs(d) < 10 else f"{abs(d):.0f}"
    return f"<span class='sr-src-delta {'up' if d > 0 else 'down'}'>{'▲' if d > 0 else '▼'} {txt}%</span>"


def _points_chip(d: float | None, unit: str = " điểm", good_up: bool = True, value: float | None = None) -> str:
    """Nhãn thay đổi theo điểm (CTR: điểm %, vị trí: số bậc; d > 0 là tốt)."""
    if d is None or abs(d) < 0.05:
        return "" if d is None else "<span class='sr-src-delta flat'>≈ 0</span>"
    good = d > 0 if good_up else d < 0
    v = abs(d) if value is None else value
    return (f"<span class='sr-src-delta {'up' if good else 'down'}'>{'▲' if d > 0 else '▼'} "
            f"{f'{v:.1f}'.replace('.', ',')}{unit}</span>")


def _metric(ui, label: str, value: str, chip: str, note: str = "") -> None:
    with ui.element("div").classes("sr-src-metric"):
        ui.label(label).classes("sr-src-mlabel")
        with ui.row().classes("items-center no-wrap").style("gap:8px"):
            ui.label(value).classes("sr-src-mnum num")
            if chip:
                ui.html(chip)
        if note:
            ui.label(note).classes("sr-src-sub")


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
        # Chỉ tính tới ngày Google đã chốt số (giống mọi màn khác, "GSC đến …" trên thanh trên cùng); ngày sơ bộ
        # sau đó vẫn được lấy về nhưng chưa đưa vào tổng.
        with connect() as c:
            end = min(date.fromisoformat(last), K.latest_date(c, site))
        n = state["days"]
        start, p_end = end - timedelta(days=n - 1), end - timedelta(days=n)
        p_start = p_end - timedelta(days=n - 1)
        wk_end = K.weeks(end, 1)[0][1]  # biểu đồ tuần: chỉ tuần đã trọn (tuần dở dang làm cột cuối thấp giả)
        with connect() as c:
            now, prev = GT.totals(c, site, start, end), GT.totals(c, site, p_start, p_end)
            active = [t for t in GT.TYPES if now[t]["impressions"] or prev[t]["impressions"]] or ["web"]
            if state["type"] not in active:
                state["type"] = active[0]
            t = state["type"]
            ser = GT.series(c, site, t, wk_end - timedelta(days=7 * 52 - 1), wk_end)
            pages, period = GT.top_pages(c, site, t)
        with ui.row().classes("items-center gap-2 q-mb-sm"):
            t_ = ui.toggle(PERIODS, value=n, on_change=lambda e: (state.update(days=e.value), body.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
            t_.props["aria-label"] = "Khoảng thời gian"
            ui.label(f"{start:%d/%m} – {end:%d/%m/%Y} · so với {n} ngày liền trước").classes("text-xs muted")

        # ---- Thẻ nguồn: nguồn có số (bấm để xem chi tiết), nguồn chưa có lượt gom thành một dòng ----
        total_clicks = sum(v["clicks"] for v in now.values()) or 1
        with ui.element("div").classes("sr-src-cards w-full"):
            for t_k in active:
                v, pv = now[t_k], prev[t_k]
                tone = SOURCE_TONES.get(t_k, "grey")
                bg, fg = T.TONES[tone]
                cell = ui.element("button").classes("sr-src-card" + (" on" if t_k == t else "")).props(
                    f'type="button" aria-pressed="{str(t_k == t).lower()}"')
                cell.on("click", lambda _, t_k=t_k: (state.update(type=t_k), body.refresh()))
                share = v["clicks"] / total_clicks
                with cell:
                    with ui.row().classes("items-center no-wrap w-full").style("gap:8px"):
                        with ui.element("div").classes("sr-db-bubble").style(f"background:{bg}"):
                            ui.icon(ICONS[t_k], size="15px").style(f"color:{fg}").props('aria-hidden="true"')
                        ui.label(GT.TYPES[t_k]).classes("sr-src-name col ellipsis")
                        ui.html(_delta_chip(v["clicks"], pv["clicks"]))
                    with ui.row().classes("items-baseline no-wrap").style("gap:6px; margin-top:6px"):
                        ui.label(F.n(v["clicks"])).classes("sr-src-num num")
                        ui.label("click").classes("sr-src-unit")
                    ui.html(f'<div class="sr-kp-bar"><i style="width:{share * 100:.1f}%;background:{fg}"></i></div>'
                            ).classes("w-full")
                    ui.label(f"{share * 100:.0f}% tổng click · {F.n(v['impressions'])} hiển thị").classes(
                        "sr-src-sub")
        idle = [GT.TYPES[x] for x in GT.TYPES if x not in active]
        if idle:
            ui.label("Chưa có lượt nào từ: " + " · ".join(idle)).classes("text-xs muted q-mt-xs")

        cur, before = now[t], prev[t]
        with ui.element("div").classes("sr-src-main w-full"):
            with T.section(ui, f"{GT.TYPES[t]} theo tuần", ICONS[t], "Click mỗi tuần (thứ Hai – Chủ nhật), 12 tháng "
                                                                   "gần nhất · rê chuột xem lượt hiển thị"):
                if not ser:
                    ui.label("Chưa có số cho nguồn này: website chưa xuất hiện ở đây.").classes("text-sm muted")
                else:
                    tone_fg = T.TONES[SOURCE_TONES.get(t, "grey")][1]
                    imps = [x["impressions"] for x in ser]
                    ui.echart({"animation": False, "grid": {"left": 44, "right": 12, "top": 14, "bottom": 26},
                               "tooltip": {"trigger": "axis", ":formatter": (
                                   "ps => 'Tuần ' + ps[0].axisValue + '<br/>' + ps[0].marker + 'Click: <b>' + "
                                   "ps[0].value.toLocaleString('vi-VN') + '</b><br/>Hiển thị: ' + "
                                   f"{imps}[ps[0].dataIndex].toLocaleString('vi-VN')")},
                               "xAxis": {"type": "category",
                                         "data": [f"{x['week'][8:10]}/{x['week'][5:7]}" for x in ser],
                                         "axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                                         "axisLabel": {"color": "#8C8A7E", "fontSize": 11, "hideOverlap": True}},
                               "yAxis": {"type": "value", "splitNumber": 4,
                                         "splitLine": {"lineStyle": {"color": "#EEECE4"}},
                                         "axisLabel": {"color": "#8C8A7E", "fontSize": 11,
                                                       ":formatter": "v => v.toLocaleString('vi-VN')"}},
                               "series": [{"type": "bar", "barMaxWidth": 12, "data": [x["clicks"] for x in ser],
                                           "itemStyle": {"color": tone_fg, "borderRadius": [4, 4, 0, 0]}}]}
                              ).classes("w-full").style("height:240px")
            with T.section(ui, "Chỉ số", "insights", f"{n} ngày · so với {n} ngày liền trước"):
                with ui.element("div").classes("sr-src-metrics"):
                    _metric(ui, "Click", F.n(cur["clicks"]), _delta_chip(cur["clicks"], before["clicks"]))
                    _metric(ui, "Hiển thị", F.n(cur["impressions"]),
                            _delta_chip(cur["impressions"], before["impressions"]))
                    ctr_d = ((cur["ctr"] - before["ctr"]) * 100 if cur["ctr"] is not None and before["ctr"] is not None
                             else None)
                    _metric(ui, "Tỷ lệ click (CTR)",
                            f"{cur['ctr'] * 100:.1f}%".replace(".", ",") if cur["ctr"] else "–",
                            _points_chip(ctr_d))
                    if t in GT.NO_POSITION:
                        _metric(ui, "Vị trí trung bình", "–", "", note="Google không trả vị trí cho nguồn này")
                    else:
                        pos_d = (before["position"] - cur["position"] if cur["position"] and before["position"]
                                 else None)  # vị trí: số nhỏ hơn là tốt hơn
                        _metric(ui, "Vị trí trung bình",
                                f"{cur['position']:.1f}".replace(".", ",") if cur["position"] else "–",
                                _points_chip(pos_d, unit="", good_up=True, value=abs(pos_d) if pos_d else None))
        with T.section(ui, f"Trang hàng đầu · {GT.TYPES[t]}", "description",
                       (f"{date.fromisoformat(period[0]):%d/%m} – {date.fromisoformat(period[1]):%d/%m}, so với 28 ngày "
                        "trước · bấm tên trang để mở" if period else "Chưa có trang nào")):
            if not pages:
                ui.label("Không có trang nào có số ở nguồn này.").classes("text-sm muted")
                return
            rows = [{"id": i, "page": urlparse(r["page"]).path or "/", "url": r["page"], "clicks": r["clicks"],
                     "impressions": r["impressions"],
                     "ctr": f"{r['ctr'] * 100:.1f}%".replace(".", ",") if r["ctr"] else "–",
                     "position": f"{r['position']:.1f}".replace(".", ",") if r["position"] else "–",
                     "change": (r["clicks"] - r["prev_clicks"]) if r["prev_clicks"] is not None else None}
                    for i, r in enumerate(pages)]
            num = "val => val == null ? '–' : val.toLocaleString('vi-VN')"
            cols = [{"name": "page", "label": "Trang", "field": "page", "align": "left", "sortable": True},
                    {"name": "clicks", "label": "Click", "field": "clicks", "align": "right", "sortable": True,
                     ":format": num, "headerStyle": "width:90px"},
                    {"name": "change", "label": "So với trước", "field": "change", "align": "right", "sortable": True,
                     "headerStyle": "width:120px"},
                    {"name": "impressions", "label": "Hiển thị", "field": "impressions", "align": "right",
                     "sortable": True, ":format": num, "headerStyle": "width:110px"},
                    {"name": "ctr", "label": "CTR", "field": "ctr", "align": "right", "headerStyle": "width:80px"}]
            if t not in GT.NO_POSITION:
                cols.append({"name": "position", "label": "Vị trí", "field": "position", "align": "right",
                             "headerStyle": "width:80px"})
            tb = ui.table(columns=cols, rows=rows, row_key="id", pagination=20).props(
                "flat dense binary-state-sort").classes("w-full sr-src-table")
            tb.add_slot("body-cell-page", """
                <q-td :props="props"><a :href="props.row.url" target="_blank" rel="noopener" class="sr-bl-link"
                  :title="props.row.url"><span class="sr-bl-anchor" style="max-width:520px; display:inline-block">
                  {{ props.value }}</span></a></q-td>""")
            tb.add_slot("body-cell-change", """
                <q-td :props="props" class="text-right">
                  <span v-if="props.value === null" class="text-xs muted">mới</span>
                  <span v-else-if="props.value" class="num" :style="{color: props.value > 0 ? '#1E7C31' : '#C2410C',
                    fontWeight: 600}">{{ props.value > 0 ? '▲' : '▼' }}
                    {{ Math.abs(props.value).toLocaleString('vi-VN') }}</span>
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
