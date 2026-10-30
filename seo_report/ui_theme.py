"""Bộ giao diện chung: màu thương hiệu, CSS, và các khối dùng lại (tiêu đề trang, thẻ KPI có sparkline, khung mục,
nhãn trạng thái, ô số có thanh). Mọi màn dùng chung để nhìn đồng bộ.

Màu theo matkinhtamduc.com: xanh lá #1E7C31, xanh chanh #B8D332. Phong cách (nền kem ấm, tiêu đề đậm hai tông, nhãn
mono in hoa, thẻ trắng bo lớn, nút viên thuốc đen) tham khảo lucianlabs.dev theo yêu cầu.
"""
import re
from html import escape
from contextlib import contextmanager

GREEN, LIME, CREAM, INK, MUTED = "#1E7C31", "#B8D332", "#EDEDE5", "#1F221E", "#6B6A5E"
RED, AMBER, BLUE, GREY = "#C2410C", "#B7791F", "#2563EB", "#8C8A7E"
PAGE_BG = "#F4F4EF"

HEAD = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Be+Vietnam+Pro:wght@600;700;800&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  /* Phong cách tham khảo lucianlabs.dev: nền kem ấm, tiêu đề đậm, nhãn mono in hoa, thẻ trắng bo lớn, nút viên thuốc. */
  :root { --ink: #1F221E; --muted: #6B6A5E; --soft: #8E8D80; --line: #E4E3DA; --green: #1E7C31; --lime: #C5E063;
          --bg: #F4F4EF; --head: 'Be Vietnam Pro', Inter, sans-serif; --mono: 'JetBrains Mono', ui-monospace, monospace; }
  body { font-family: Inter, 'Segoe UI', sans-serif; background: var(--bg); color: var(--ink);
         font-feature-settings: 'tnum' 1, 'cv11' 1; letter-spacing: -0.006em; }
  .muted { color: var(--muted); }
  .num { font-variant-numeric: tabular-nums; }
  .sr-head { font-family: var(--head); }
  /* tiêu đề trang: nhãn mono + tiêu đề lớn hai tông */
  .sr-eyebrow { font-family: var(--mono); font-size: 11.5px; font-weight: 600; letter-spacing: .08em;
                text-transform: uppercase; color: var(--muted); display: flex; align-items: center; gap: 8px; }
  .sr-eyebrow::before { content: ''; width: 8px; height: 8px; border-radius: 50%; background: var(--lime);
                        box-shadow: 0 0 0 3px rgba(197,224,99,.28); }
  .sr-title { font-family: var(--head); font-size: 28px; font-weight: 800; letter-spacing: -0.03em;
              line-height: 1.15; color: var(--ink); }
  .sr-title .soft { color: var(--soft); }
  /* thẻ và khung */
  .q-card { border-radius: 12px; }
  .q-card.q-card--bordered, .q-card--flat.q-card--bordered { border-color: var(--line); }
  .sr-card { background: #fff; border: 1px solid var(--line); border-radius: 14px; }
  .sr-section-title { font-family: var(--head); font-size: 16px; font-weight: 700; letter-spacing: -0.015em; }
  .sr-link { color: var(--ink) !important; font-size: 13.5px; font-weight: 600; text-decoration: none;
             border-bottom: 1.5px solid var(--ink); padding-bottom: 1px; white-space: nowrap; }
  .sr-link:hover { color: var(--green) !important; border-color: var(--green); }
  .sr-kpi { transition: box-shadow .15s, transform .15s; flex: 1 1 0; min-width: 160px; align-self: stretch;
            display: flex; flex-direction: column; border-radius: 12px !important; }
  .sr-kpi-hint { margin-top: auto; padding-top: 6px; line-height: 1.3; }
  .sr-kpi-row { display: flex; flex-wrap: wrap; gap: 12px; width: 100%; align-items: stretch; }
  .sr-kpi.clickable:hover { box-shadow: 0 6px 18px rgba(31,34,30,.08); transform: translateY(-1px); cursor: pointer; }
  .sr-kpi-value { font-family: var(--head); font-size: 22px; font-weight: 700; letter-spacing: -0.025em;
                  line-height: 1.15; }
  .sr-icon-bubble { width: 32px; height: 32px; border-radius: 10px; display: flex; align-items: center;
                    justify-content: center; }
  .sr-delta { font-size: 12px; font-weight: 650; padding: 1px 7px; border-radius: 999px; white-space: nowrap; }
  .sr-delta.up { color: #1E7C31; background: #E7F3EA; }
  .sr-delta.down { color: #C2410C; background: #FCEDE6; }
  .sr-delta.flat { color: #6B6A5E; background: #EFEFE8; }
  /* nút viên thuốc: chính = đen đặc, phụ = viền */
  .q-btn { border-radius: 999px !important; font-weight: 650; letter-spacing: -0.01em; }
  .q-btn.bg-primary { background: var(--ink) !important; color: #F6F7F1 !important; }
  .q-btn--outline { color: var(--ink) !important; background: #fff !important; }
  .q-btn--outline:before { border-color: #D6D5CB !important; }
  .q-btn-group { border-radius: 999px !important; }
  .q-btn-dropdown--split .q-btn-dropdown__arrow-container { border-left: 1px solid rgba(255,255,255,.25) !important; }
  .q-field--outlined .q-field__control { border-radius: 10px; background: #fff; }
  .q-field--outlined .q-field__control:before { border-color: var(--line); }
  .q-menu { border-radius: 12px !important; box-shadow: 0 12px 32px rgba(31,34,30,.12) !important; }
  .q-dialog .q-card { border-radius: 14px !important; }
  /* bảng */
  .q-table__container { border-radius: 12px; border-color: var(--line) !important; }
  .q-table thead th { font-family: var(--mono); font-size: 10.5px; font-weight: 600; text-transform: uppercase;
                      letter-spacing: .07em; color: var(--muted); background: #FAFAF6; }
  .q-table tbody td { font-size: 13px; font-variant-numeric: tabular-nums; }
  .q-table tbody tr:nth-child(even) td { background: #FAFAF6; }
  .q-table tbody tr:hover td { background: #F0F2E8; }
  .q-table th.sortable .q-table__sort-icon { font-size: 14px; }
  .sr-busy { display: contents; }
  /* danh sách URL (màn Hiệu suất URL) */
  .sr-url-item { width: 100%; flex-shrink: 0; padding: 7px 10px; border-radius: 8px; cursor: pointer;
                 display: flex; flex-direction: column; gap: 1px; border: 1px solid transparent; }
  .sr-url-item:hover { background: #F3F3EC; }
  .sr-url-item.selected { background: #EEF6EF; border-color: #CFE6D4; }
  .sr-url-item:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
  .sr-url-line { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; min-width: 0; }
  .sr-url-path { font-size: 13px; font-weight: 550; color: var(--ink); overflow: hidden; text-overflow: ellipsis;
                 white-space: nowrap; min-width: 0; }
  .sr-url-item.selected .sr-url-path { color: var(--green); }
  .sr-url-clicks { font-size: 13px; font-weight: 650; }
  .sr-url-meta { display: flex; align-items: center; gap: 5px; min-width: 0; font-size: 11.5px; color: var(--muted); }
  .sr-url-delta { font-size: 11.5px; font-weight: 600; white-space: nowrap; }
  /* bento: một hộp bo tròn, các ô cùng bán kính, nền đặc, một khoảng cách chung */
  .sr-bento { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); grid-auto-rows: minmax(92px, auto);
              gap: 6px; padding: 6px; background: #E9E9E1; border-radius: 16px; }
  .sr-bento-tile { background: #fff; border-radius: 11px; padding: 12px 14px; display: flex; flex-direction: column;
                   gap: 4px; min-width: 0; }
  .sr-bento-tile.big { grid-column: span 2; grid-row: span 2; gap: 6px; }
  .sr-bento-tile.wide { grid-column: span 2; }
  .sr-bento-eyebrow { font-family: var(--mono); font-size: 10.5px; font-weight: 600; letter-spacing: .08em;
                      text-transform: uppercase; }
  .sr-bento-hero { font-family: var(--head); font-size: 32px; font-weight: 800; letter-spacing: -0.035em;
                   line-height: 1.05; }
  .sr-seg { background: #EEECE4; border-radius: 999px; padding: 3px; gap: 2px; box-shadow: none; }
  .sr-seg .q-btn { border-radius: 999px !important; padding: 2px 12px; min-height: 26px; font-size: 12.5px; }
  .sr-seg .q-btn.bg-white { box-shadow: 0 1px 2px rgba(31,34,30,.12); font-weight: 600; }
  .sr-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
  .sr-bento-tile .sr-delta, .sr-metric .sr-delta { align-self: flex-start; }
  @media (max-width: 1100px) { .sr-bento { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  #sr-top { position: fixed; right: 24px; bottom: calc(24px + env(safe-area-inset-bottom)); z-index: 2000;
            width: 44px; height: 44px; border-radius: 50%; border: 1px solid var(--line); background: #fff;
            color: var(--ink); box-shadow: 0 6px 18px rgba(31,34,30,.14); cursor: pointer; display: flex;
            align-items: center; justify-content: center; opacity: 0; transform: translateY(8px);
            pointer-events: none; transition: opacity .2s, transform .2s; }
  #sr-top.show { opacity: 1; transform: none; pointer-events: auto; }
  #sr-top:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .q-notifications__list--bottom { padding-bottom: 76px; }  /* chừa chỗ nút về đầu trang */
  .q-notification { border-radius: 14px !important; }
  .q-table--dense .q-table th, .q-table--dense .q-table td { padding: 7px 10px; }
  .sr-bar { position: relative; display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
  .sr-bar-fill { height: 6px; border-radius: 3px; background: #CFE6D4; }
  /* tab dạng viên thuốc như nhãn chủ đề */
  .sr-tabs .q-tab { border: 1px solid var(--line); border-radius: 8px; min-height: 32px; margin-right: 6px;
                    padding: 0 14px; background: #fff; color: var(--ink); }
  .sr-tabs .q-tab--active { background: var(--ink); border-color: var(--ink); color: #F6F7F1; }
  .sr-tabs .q-tab__label { font-weight: 600; }
  .sr-tabs .q-tab__indicator { display: none; }
  /* menu trái */
  .sr-nav a { display: flex; align-items: center; gap: 10px; padding: 7px 12px; border-radius: 8px;
              color: #3A3B35; text-decoration: none; font-size: 14px; }
  .sr-nav a:hover { background: #E8E8E0; }
  .sr-nav a.active { background: #fff; color: var(--ink); font-weight: 650; box-shadow: 0 1px 2px rgba(31,34,30,.08); }
  .sr-nav a.active .q-icon { color: var(--green); }
  .sr-nav-group { font-family: var(--mono); font-size: 10.5px; font-weight: 600; text-transform: uppercase;
                  letter-spacing: .09em; color: #9A998C; padding: 16px 12px 5px; }
  .sr-summary { display: flex; flex-wrap: wrap; padding: 0; }
  .sr-summary-half { flex: 1 1 460px; min-width: 0; padding: 18px 20px; display: flex; flex-direction: column;
                     gap: 12px; }
  .sr-summary-half.geo { border-left: 1px solid var(--line); background: #FBFAFD; border-radius: 0 14px 14px 0; }
  .sr-metric-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .sr-metric { padding: 2px 14px; border-left: 1px solid var(--line); display: flex; flex-direction: column;
               gap: 3px; align-items: flex-start; min-width: 0; }
  .sr-metric:first-child { border-left: none; padding-left: 0; }
  .sr-metric-value { font-family: var(--head); font-size: 20px; font-weight: 700; letter-spacing: -0.025em;
                     line-height: 1.2; }
  .q-header.sr-top .q-field--dense .q-field__control { min-height: 34px; height: 34px; }
  .q-header.sr-top .q-field--dense .q-field__marginal { height: 34px; }
  .q-header.sr-top .q-field--dense .q-field__native { min-height: 34px; padding: 0; }
  .q-drawer--mini .q-mini-drawer-hide { display: none !important; }
  .q-drawer:not(.q-drawer--mini) .q-mini-drawer-only { display: none !important; }
  /* menu thu gọn: mỗi mục là một ô vuông 40px căn giữa; nhóm ngăn bằng vạch mảnh thay cho chữ */
  .sr-nav { align-items: stretch !important; }
  .sr-nav a { width: 100%; }
  .q-drawer--mini .sr-nav { align-items: center !important; }
  .q-drawer--mini .sr-nav a { width: 40px; height: 40px; padding: 0; margin: 2px 0; justify-content: center;
                              border-radius: 10px; gap: 0; }
  .q-drawer--mini .sr-nav-group { font-size: 0; padding: 0; width: 24px; height: 1px; margin: 10px 0;
                                  background: #D9D8CE; }
  .q-drawer--mini .sr-logo-mark { display: block !important; width: 36px; height: 36px; margin: 2px auto 6px; }
  .q-header.sr-top { background: rgba(244,244,239,.9); backdrop-filter: blur(10px); color: var(--ink);
                     border-bottom: 1px solid var(--line); }
</style>
"""

TONES = {"green": ("#E7F3EA", GREEN), "lime": ("#F2F7DC", "#5E7414"), "blue": ("#E8EFFD", BLUE),
         "amber": ("#FBF1DE", AMBER), "red": ("#FCEDE6", RED), "grey": ("#F1F0EA", MUTED),
         "purple": ("#F1EAFB", "#7C3AED")}


EYEBROWS = {"space_dashboard": "Tổng quan", "summarize": "Báo cáo", "travel_explore": "SEO", "leaderboard": "SEO",
            "link": "SEO", "auto_awesome": "AI & GEO", "verified": "Quản trị", "folder_open": "Quản trị"}


def page_header(ui, icon: str, title: str, subtitle: str = "", tone: str = "green", eyebrow: str | None = None):
    """Tiêu đề trang: nhãn mono nhỏ ở trên, tiêu đề lớn hai tông (phần số/ngày màu nhạt). Trả về row bên phải để đặt
    nút/bộ lọc."""
    m = re.search(r"\d", title)
    strong, soft = (title[:m.start()], title[m.start():]) if m and m.start() > 0 else (title, "")
    with ui.row().classes("w-full items-end gap-3 no-wrap q-mb-md q-mt-xs"):
        with ui.column().classes("gap-1").style("min-width: 0"):
            ui.label(f"SEO Report — {eyebrow or EYEBROWS.get(icon, 'matkinhtamduc.com')}").classes("sr-eyebrow")
            ui.html(f'<div class="sr-title">{escape(strong)}<span class="soft">{escape(soft)}</span></div>')
            if subtitle:
                ui.label(subtitle).classes("text-sm muted q-mt-xs")
        ui.space()
        right = ui.row().classes("items-center gap-2")
    return right


def delta_badge(ui, text: str, good: bool | None):
    if not text:
        return
    cls = "flat" if good is None else ("up" if good else "down")
    arrow = "" if good is None else ("▲ " if text.lstrip().startswith("+") else "▼ " if text.lstrip().startswith(
        "-") else "")
    ui.label(arrow + text).classes(f"sr-delta {cls}")


def sparkline(ui, values: list, color: str = GREEN, height: int = 40, labels: list | None = None,
              fmt: str = "num", **_):
    """Cột nhỏ theo kỳ (cũ → mới), cột cuối (kỳ đang xem) tô đậm, rê chuột hiện số. Trục từ 0 để chiều cao đúng tỷ lệ:
    không phóng đại -0,6% thành một cú tụt; muốn xem chênh lệch chính xác thì xem nhãn % cạnh số lớn."""
    vals = list(values)
    if not any(v for v in vals if v is not None):
        ui.element("div").style(f"height:{height}px")  # giữ chỗ để các thẻ cùng hàng thẳng nhau
        return
    data = [{"value": v, "itemStyle": {"color": color, "opacity": 1 if i == len(vals) - 1 else 0.35,
                                       "borderRadius": [2, 2, 0, 0]}} for i, v in enumerate(vals)]
    value_js = ("v => v == null ? 'chưa có' : (v * 100).toLocaleString('vi-VN', {maximumFractionDigits: 2}) + '%'"
                if fmt == "pct" else "v => v == null ? 'chưa có' : v.toLocaleString('vi-VN', "
                                     "{maximumFractionDigits: 1})")
    ui.echart({"animation": False, "grid": {"left": 0, "right": 0, "top": 2, "bottom": 0},
               "tooltip": {"trigger": "axis", "confine": True, "axisPointer": {"type": "none"},
                           "textStyle": {"fontSize": 11}, "padding": [4, 8], ":valueFormatter": value_js},
               "xAxis": {"type": "category", "show": False, "data": labels or [str(i) for i in range(len(vals))]},
               "yAxis": {"type": "value", "show": False, "min": 0},
               "series": [{"type": "bar", "data": data, "barWidth": "62%", "name": ""}]}).style(
        f"height:{height}px; width:100%")


def kpi(ui, icon: str, label: str, value: str, delta: str = "", good: bool | None = None, hint: str = "",
        spark: list | None = None, tone: str = "green", href: str | None = None, spark_kind: str = "bar",
        spark_labels: list | None = None, spark_fmt: str = "num"):
    """Thẻ KPI: icon + nhãn, số lớn, nhãn thay đổi (xanh/đỏ), sparkline, dòng phụ. Có href thì bấm để đi sâu.
    Bố cục cố định để mọi thẻ cùng hàng cao bằng nhau: spark=[] giữ chỗ biểu đồ dù không có số, dòng phụ luôn có
    chỗ (để trống nếu không có)."""
    bg, fg = TONES[tone]
    card = ui.element("div").classes("sr-card sr-kpi q-pa-md" + (" clickable" if href else ""))
    if href:
        card.on("click", lambda: ui.navigate.to(href))
    with card:
        with ui.row().classes("items-center gap-2 no-wrap"):
            with ui.element("div").classes("sr-icon-bubble").style(f"background:{bg}"):
                ui.icon(icon, size="18px").style(f"color:{fg}")
            ui.label(label).classes("text-sm muted").style("line-height:1.2")
        with ui.row().classes("items-baseline gap-2 q-mt-sm no-wrap"):
            ui.label(value).classes("sr-kpi-value num")
            delta_badge(ui, delta, good)
        if spark is not None:
            with ui.element("div").classes("q-mt-xs w-full"):
                sparkline(ui, spark, fg, labels=spark_labels, fmt=spark_fmt)
        ui.label(hint or " ").classes("text-xs muted sr-kpi-hint")
    return card


@contextmanager
def section(ui, title: str, icon: str | None = None, subtitle: str = "", href: str | None = None,
            link_text: str = "Xem chi tiết"):
    """Khung trắng có tiêu đề mục; nội dung đặt trong `with`."""
    with ui.element("div").classes("sr-card q-pa-md w-full"):
        with ui.row().classes("w-full items-center gap-2 no-wrap q-mb-sm"):
            if icon:
                with ui.element("div").classes("sr-icon-bubble").style(f"background:{TONES['green'][0]}"):
                    ui.icon(icon, size="18px").style(f"color:{GREEN}")
            with ui.column().classes("gap-0"):
                ui.label(title).classes("sr-section-title")
                if subtitle:
                    ui.label(subtitle).classes("text-xs muted")
            ui.space()
            if href:
                ui.link(link_text + " →", href).classes("sr-link")
        body = ui.column().classes("w-full gap-2")
        with body:
            yield body


def status_chip(ui, text: str, tone: str = "grey", icon: str | None = None):
    bg, fg = TONES[tone]
    with ui.row().classes("items-center gap-1 no-wrap").style(
            f"background:{bg}; color:{fg}; border-radius:999px; padding:2px 10px; font-size:12px; font-weight:600"):
        if icon:
            ui.icon(icon, size="14px")
        ui.label(text)


def bar_slot(table, column: str, max_value: float, fmt: str = "toLocaleString('vi-VN')"):
    """Ô số kèm thanh ngang tỷ lệ với giá trị lớn nhất của cột (dễ nhìn thứ tự hơn số trần)."""
    mx = max(max_value, 1)
    table.add_slot(f"body-cell-{column}", f"""
        <q-td :props="props">
          <div class="sr-bar">
            <div class="sr-bar-fill" :style="{{width: Math.max(2, 48 * (props.value || 0) / {mx}) + 'px'}}"></div>
            <span>{{{{ props.value === null || props.value === undefined ? 'N/A' : props.value.{fmt} }}}}</span>
          </div>
        </q-td>""")


def empty_state(ui, icon: str, title: str, text: str = ""):
    with ui.element("div").classes("sr-card q-pa-xl w-full").style("text-align:center"):
        ui.icon(icon, size="40px").style("color:#B8B6A8")
        ui.label(title).classes("text-base font-semibold q-mt-sm")
        if text:
            ui.label(text).classes("text-sm muted")


def kpi_row(ui):
    """Hàng thẻ KPI: các thẻ cao bằng nhau, tự xuống hàng khi màn hẹp."""
    return ui.element("div").classes("sr-kpi-row")


def good_of(value) -> bool | None:
    return None if value is None or value == 0 else value > 0


# ---- Bảng: mặc định chung cho mọi ui.table ----
# Số trong bảng thường đã định dạng kiểu Việt ("4.981", "53,85%", "–"), sắp xếp chữ sẽ sai thứ tự (9 > 10). Cột căn
# phải (cột số) dùng hàm so sánh đọc lại con số; giá trị không phải số ("–", "chờ check") xếp cuối.
NUM_SORT = ("(a, b) => { const p = v => { if (v === null || v === undefined || v === '') return -Infinity;"
            " if (typeof v === 'number') return v; const s = String(v).replace(/[^0-9,.\\-]/g, '')"
            ".replace(/\\./g, '').replace(',', '.'); const n = parseFloat(s); return isNaN(n) ? -Infinity : n; };"
            " return p(a) - p(b); }")
NO_SORT = {"chart", "star", "gsc", "id"}


def _polish_column(col: dict) -> dict:
    col = dict(col)
    if col.get("name") in NO_SORT or not col.get("label"):
        return col
    col.setdefault("sortable", True)
    if col.get("align") == "right" and ":sort" not in col and "sort" not in col:
        col[":sort"] = NUM_SORT
    return col


def install_table_defaults() -> None:
    """Mọi bảng: cột nào cũng sắp xếp được (sắp trên toàn bộ dữ liệu, không chỉ trang đang xem), cột số sắp theo giá trị.
    Sọc xen kẽ và aria-sort làm bằng CSS/JS trong HEAD."""
    from nicegui.elements.table import Table
    if getattr(Table, "_sr_defaults", False):
        return
    original = Table.__init__

    def init(self, *, columns=None, **kwargs):
        original(self, columns=[_polish_column(c) for c in columns] if columns else columns, **kwargs)

    Table.__init__ = init
    Table._sr_defaults = True


def skeleton(ui):
    """Khung xám chờ dữ liệu, đặt trong vùng aria-busy để trình đọc màn hình biết đang tải."""
    with ui.element("div").classes("sr-busy").props('aria-busy="true" aria-label="Đang tải dữ liệu"'):
        return ui.skeleton()


BODY = """
<button id="sr-top" type="button" aria-label="Về đầu trang" title="Về đầu trang"
        onclick="window.scrollTo({top: 0, behavior: 'smooth'})">
  <span class="material-icons" aria-hidden="true">arrow_upward</span>
</button>
<script>
(() => {
  // Nút về đầu trang: chỉ hiện khi đã cuộn quá 400px.
  const top = () => document.getElementById('sr-top');
  addEventListener('scroll', () => { const b = top(); if (b) b.classList.toggle('show', scrollY > 400); },
                   {passive: true});

  // aria-sort cho tiêu đề cột đang sắp xếp (Quasar chỉ đổi class).
  let queued = false;
  const syncSort = () => {
    queued = false;
    document.querySelectorAll('th.sortable').forEach(th => {
      const v = th.classList.contains('sorted') ? (th.classList.contains('sort-desc') ? 'descending' : 'ascending')
                                                : 'none';
      if (th.getAttribute('aria-sort') !== v) th.setAttribute('aria-sort', v);
    });
  };
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(syncSort); } })
    .observe(document.documentElement, {subtree: true, childList: true, attributes: true, attributeFilter: ['class']});

  // Toast: một góc cố định (dưới phải), role="status"; thông báo thường tự tắt sau 4,5 giây và dừng đếm khi rê
  // chuột hoặc focus vào; lỗi và thông báo đang chạy giữ đến khi bấm Đóng / xong việc.
  const patch = () => {
    if (!window.Quasar || !Quasar.Notify || Quasar.Notify._sr) return !!(window.Quasar && Quasar.Notify);
    const create = Quasar.Notify.create.bind(Quasar.Notify);
    Quasar.Notify.create = (opts) => {
      if (typeof opts === 'string') opts = {message: opts};
      opts = {position: 'bottom-right', ...opts};
      if (opts.position === 'bottom') opts.position = 'bottom-right';
      const error = opts.type === 'negative';
      const ongoing = opts.type === 'ongoing' || opts.spinner;
      if (error && !opts.closeBtn) opts.closeBtn = 'Đóng';
      if (error || ongoing || opts.timeout === 0 || opts.closeBtn) {
        opts.timeout = ongoing ? opts.timeout : 0;
        opts.attrs = {...(opts.attrs || {}), role: error ? 'alert' : 'status'};
        return create(opts);
      }
      const id = 't' + Math.random().toString(36).slice(2);
      let left = opts.timeout || 4500, start = Date.now(), timer;
      const dismiss = create({...opts, timeout: 0, attrs: {...(opts.attrs || {}), role: 'status', 'data-toast': id}});
      const run = () => { start = Date.now(); timer = setTimeout(dismiss, Math.max(left, 800)); };
      const pause = () => { clearTimeout(timer); left -= Date.now() - start; };
      run();
      setTimeout(() => {
        const el = document.querySelector(`[data-toast="${id}"]`);
        if (!el) return;
        el.addEventListener('mouseenter', pause); el.addEventListener('mouseleave', run);
        el.addEventListener('focusin', pause); el.addEventListener('focusout', run);
      }, 60);
      return dismiss;
    };
    Quasar.Notify._sr = true;
    return true;
  };
  const wait = setInterval(() => { if (patch()) clearInterval(wait); }, 100);
})();
</script>
"""


def donut(ui, items: list[tuple[str, float]], colors: list[str], unit: str, height: int = 230):
    """Donut cho các phần của một tổng (tối đa 6 phần, phần nhỏ nên gộp "Khác" trước khi gọi): khe đều giữa các
    lát, tổng ở giữa, chú thích cùng màu và cùng thứ tự. Rê chuột vào lát hoặc dòng chú thích thì lát đó nhô ra và
    giá trị hiện ở giữa (che phần tổng)."""
    import json
    pairs = [(n, v, c) for (n, v), c in zip(items, colors) if v][:6]  # bỏ phần bằng 0 mà vẫn giữ đúng màu
    items, colors = [(n, v) for n, v, _ in pairs], [c for _, _, c in pairs]
    total = sum(v for _, v in items)
    if not total:
        return None
    vi = {n: f"{v:,.0f}".replace(",", ".") + f"  ·  {v / total * 100:.0f}%" for n, v in items}
    # Tổng ở giữa là nhãn của lát đầu tiên; lát khác không có nhãn. Rê chuột vào một lát: lát đó hiện giá trị của nó,
    # các lát còn lại chuyển trạng thái "blur" và ẩn nhãn, nên ở giữa luôn chỉ có một dòng chữ (không chồng nhau).
    total_text = f"{total:,.0f}".replace(",", ".")
    return ui.echart({
        "animation": True,
        "tooltip": {"show": False},
        "legend": {"orient": "vertical", "left": "60%", "top": "middle", "icon": "circle", "itemWidth": 9,
                   "itemHeight": 9, "itemGap": 12, "textStyle": {"fontSize": 12, "color": INK},
                   ":formatter": f"name => name + '   ' + ({json.dumps(vi, ensure_ascii=False)})[name]"},
        "series": [{
            "type": "pie", "radius": ["58%", "80%"], "center": ["30%", "50%"], "padAngle": 2,
            "avoidLabelOverlap": False, "labelLine": {"show": False},
            "itemStyle": {"borderRadius": 4, "borderColor": "#fff", "borderWidth": 1},
            "label": {"show": True, "position": "center", "color": INK,
                      ":formatter": f"p => p.dataIndex === 0 ? '{{t|{total_text}}}\\n{{u|{unit}}}' : ''",
                      "rich": {"t": {"fontSize": 22, "fontWeight": 800, "lineHeight": 26, "color": INK},
                               "u": {"fontSize": 11, "color": MUTED, "lineHeight": 16}}},
            "emphasis": {"focus": "self", "scale": True, "scaleSize": 6, "label": {
                "show": True,
                ":formatter": "p => '{n|' + p.name + '}\\n{t|' + p.value.toLocaleString('vi-VN') + '}\\n{u|' + "
                              "p.percent.toLocaleString('vi-VN', {maximumFractionDigits: 0}) + '%}'",
                "rich": {"n": {"fontSize": 11, "color": MUTED, "lineHeight": 16},
                         "t": {"fontSize": 20, "fontWeight": 800, "lineHeight": 24, "color": INK},
                         "u": {"fontSize": 11, "color": MUTED, "lineHeight": 16}}}},
            "blur": {"label": {"show": False}, "itemStyle": {"opacity": 0.35}},
            "data": [{"name": n, "value": v, "itemStyle": {"color": c}} for (n, v), c in zip(items, colors)],
        }],
    }).style(f"height: {height}px; width: 100%")
