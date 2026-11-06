"""Trang Backlink (/backlink): số tổng, xu hướng 12 tháng và bốn danh sách (website trỏ về, link mới / mất 30 ngày,
anchor text, trang được link nhiều nhất), lấy từ DataForSEO Backlinks API (backlinks.py).

Khách hàng xem được; chỉ người sửa được dự án mới bấm "Lấy số mới" (tốn tiền DataForSEO, tính vào ngân sách website).
"""
import re
from datetime import date
from urllib.parse import urlparse

from . import access as A
from . import ai_format as F
from . import backlink_audit as AU
from . import backlinks as BL
from . import ui_theme as T
from .backlink_audit import anchor_type  # noqa: F401  (dùng ở test)
from .backlink_audit import fold as _fold

TABS = (("domains", "Website trỏ về", "language"), ("changes", "Link mới / mất", "swap_vert"),
        ("anchors", "Anchor text", "short_text"), ("pages", "Trang được link nhiều", "description"))


SPAM_FLAG = AU.SPAM_FLAG  # điểm spam của link (0–100) từ mức này thì gắn nhãn "spam"
ANCHOR_TYPES = {"brand": ("Thương hiệu", "k-brand"), "url": ("URL", "k-url"), "keyword": ("Từ khóa", "k-kw"),
                "empty": ("Trống / ảnh", "k-empty")}


def _path(url: str) -> str:
    p = urlparse(url or "")
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def _vn(d: str) -> str:
    try:
        return f"{date.fromisoformat(d):%d/%m/%Y}"
    except (TypeError, ValueError):
        return "–"


PAGE_TABS = (("overview", "Tổng quan"), ("domains", "Website trỏ về"), ("changes", "Link mới / mất"),
             ("anchors", "Anchor text"), ("pages", "Trang được link"))
CHECK_TAB = AU.CHECK_TAB  # mục kiểm tra nào nằm ở tab nào


def build_backlink_page(ui, cfg, connect, user, start: str = "") -> None:
    from nicegui import run

    site = cfg.site_url
    ed = A.can_edit(user)
    right = T.page_header(ui, "add_link", "Backlink",
                          "Ai đang link về website, link mới / mất, anchor và việc cần xử lý. Số của DataForSEO.")

    async def fetch(btn):
        if not ed:  # tốn tiền DataForSEO: chặn ở server, nút bị ẩn chưa đủ
            return
        from contextlib import closing

        from . import db
        btn.props("loading")

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                logs: list[str] = []
                BL.refresh(c, site, cfg, force=True, log=logs.append)
                return logs
        try:
            logs = await run.io_bound(work)
            bad = [m for m in logs if m.startswith("Không lấy được")]
            ui.notify("Đã lấy số backlink mới" + (f" ({len(bad)} danh sách lỗi)" if bad else ""),
                      caption=" · ".join(bad)[:300] or None, type="warning" if bad else "positive",
                      position="bottom-right", classes="sr-toast", multi_line=True)
        except Exception as e:  # noqa: BLE001
            ui.notify("Không lấy được số backlink", caption=str(e)[:200], type="negative", position="bottom-right",
                      classes="sr-toast", timeout=0, close_button="Đóng")
        btn.props(remove="loading")
        body.refresh()

    def schedule_dialog() -> None:
        """Lịch tự lấy: chu kỳ, tạm ngưng tự lấy, danh sách lấy kèm; chi phí tháng ước tính đổi theo lựa chọn."""
        if not ed:
            return
        with connect() as c:
            st = BL.settings(c, site)
        with ui.dialog() as d, ui.card().style("width: 460px; max-width: 94vw; border-radius: 14px"):
            ui.label("Lịch lấy số backlink").classes("text-base font-semibold")
            ui.label("Lượt chạy tự động mỗi sáng sẽ lấy khi đến hạn. Nút “Lấy số mới” luôn lấy ngay, kể cả khi đang "
                     "tạm ngưng.").classes("text-xs muted")
            pause = ui.switch("Tạm ngưng tự lấy (chỉ lấy khi bấm “Lấy số mới”)", value=st["paused"]).props("dense")
            every = ui.radio({k: v for k, v in BL.EVERY_CHOICES.items()}, value=st["every_days"]).props(
                "inline dense")
            ui.label("Lấy kèm danh sách").classes("text-sm font-semibold q-mt-sm")
            names = {k: n for k, n, _ in TABS}
            boxes = {k: ui.checkbox(names[k], value=k in st["lists"]).props("dense") for k in BL.LIST_KINDS}
            est = ui.label().classes("text-sm q-mt-sm")

            def now_st() -> dict:
                return {"every_days": every.value, "paused": pause.value,
                        "lists": [k for k, b_ in boxes.items() if b_.value]}

            def show(_=None) -> None:
                s_ = now_st()
                every.set_enabled(not s_["paused"])
                est.text = ("Không tự lấy: không tốn tiền cho đến khi bấm “Lấy số mới”." if s_["paused"] else
                            f"Ước tính khoảng {BL.monthly_estimate(s_):.2f} USD/tháng".replace(".", ",")
                            + f" (số tổng + {len(s_['lists'])} danh sách, mỗi lần khoảng "
                            + f"{BL.COST_SUMMARY + BL.COST_LIST * len(s_['lists']):.2f} USD)".replace(".", ","))
            for w in (pause, every, *boxes.values()):
                w.on_value_change(show)
            show()

            def save() -> None:
                s_ = now_st()
                with connect() as c:
                    BL.save_settings(c, site, s_["every_days"], s_["paused"], s_["lists"], str(user))
                ui.notify("Đã lưu lịch lấy số backlink", type="positive", position="bottom-right", classes="sr-toast")
                d.close()
                body.refresh()
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Lưu", on_click=save).props("unelevated no-caps color=primary")
        d.open()

    def own_brand(c):
        try:
            from . import aio as AO
            return next((b_ for b_ in AO.brands(c, cfg) if b_["own"]), None)
        except Exception:  # noqa: BLE001
            return None

    def make_xlsx(which: str):
        """Hàm tạo file Excel (cả trang / audit / một danh sách) cho nút Xuất."""
        def build() -> bytes:
            from . import backlink_export as BX
            with connect() as c:
                return BX.build(BL.lists(c, site), BL.latest(c, site), brand_terms_of(own_brand(c)), site, which)
        return build

    def export_btn(which: str, name: str, label: str, icon_only: bool = True) -> None:
        from .web_export import export_menu
        host = (urlparse(site).netloc or site.split(":")[-1]).replace("www.", "")
        export_menu(ui, cfg, connect, f"backlink-{name}_{host}_{date.today():%Y-%m-%d}", make_xlsx(which),
                    label=label, user=user, icon_only=icon_only, category="backlink")

    with right, ui.row().classes("items-center no-wrap gap-2"):
        export_btn("all", "bao-cao", "Xuất báo cáo", icon_only=False)
    if ed and not cfg.rank.paused:
        with right, ui.row().classes("items-center no-wrap gap-2"):
            ui.button("Lịch lấy", icon="event_repeat", on_click=schedule_dialog).props(
                "outline no-caps color=grey-9").tooltip("Đặt chu kỳ tự lấy, tạm ngưng, chọn danh sách lấy kèm")
            b = ui.button("Lấy số mới", icon="refresh").props("unelevated no-caps color=primary")
            b.on_click(lambda _, b=b: fetch(b))
            b.tooltip("Gọi DataForSEO ngay: số tổng + các danh sách đã chọn, khoảng 0,10 USD, tính vào ngân sách "
                      "check rank của website")

    keys = [k for k, _ in PAGE_TABS]
    start = "changes" if start == "audit" else start  # link cũ ?tab=audit
    state = {"tab": start if start in keys else "overview", "q": {k: "" for k in BL.LIST_KINDS},
             "f": {k: None for k in BL.LIST_KINDS}}  # f: mục kiểm tra đang dùng làm bộ lọc của từng tab

    @ui.refreshable
    def body():
        with connect() as c:
            bl = BL.latest(c, site)
            ls = BL.lists(c, site)
            st, due = BL.settings(c, site), BL.next_due(c, site)
            own = own_brand(c)
        if not bl and not ls:
            T.empty_state(ui, "add_link", "Chưa lấy số backlink lần nào",
                          "Bấm “Lấy số mới” để lấy số tổng, lịch sử 12 tháng và 4 danh sách (khoảng 0,15 USD lần đầu)."
                          if ed else "Số backlink sẽ có sau lần lấy đầu tiên.")
            return
        status_line(bl, st, due)
        checks = AU.audit(ls, brand_terms_of(own)) if ls else []
        by_tab = {k: [c_ for c_ in checks if CHECK_TAB.get(c_["key"]) == k] for k in BL.LIST_KINDS}

        def label(k: str, name: str) -> str:
            d_ = ls.get(k)
            return name + (f" · {F.n(d_['total'] or len(d_['items']))}" if d_ else "")
        with ui.tabs(value=state["tab"], on_change=lambda e: pick(e.value)).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs sr-bl-tabs") as tabs:
            for k, name in PAGE_TABS:
                with ui.tab(k, label(k, name)):
                    high = sum(1 for c_ in by_tab.get(k, []) if c_["level"] == "high")
                    if high:  # chấm đỏ: tab có việc cần xử lý
                        ui.badge(str(high), color="red").props("rounded").classes("sr-tab-badge").tooltip(
                            f"{high} việc cần xử lý trong tab này")
        state["tabs"] = tabs
        with ui.tab_panels(tabs, value=state["tab"]).classes("w-full").props("animated=false"):
            with ui.tab_panel("overview").classes("q-px-none"):
                kpis(bl, ls)
                todo(checks)
                trend(bl)
            for k in BL.LIST_KINDS:
                with ui.tab_panel(k).classes("q-px-none"):
                    list_panel(k, ls, own, by_tab[k])

    def pick(v: str) -> None:
        state["tab"] = v
        ui.run_javascript(f"history.replaceState(null, '', '/backlink' + ('{v}' === 'overview' ? '' : '?tab={v}'))")

    def status_line(bl, st, due) -> None:
        now, prev = (bl or {}).get("now"), (bl or {}).get("prev")
        with ui.row().classes("items-center gap-2 q-mb-xs"):
            if now:
                ui.label(f"Lấy ngày {date.fromisoformat(now['day']):%d/%m/%Y}"
                         + (f" · so với lần lấy {date.fromisoformat(prev['day']):%d/%m}" if prev else "")).classes(
                    "text-xs muted")
            if cfg.rank.paused:
                T.status_chip(ui, "Website đang tạm ngưng mọi chi phí DataForSEO", "grey", "pause_circle")
            elif st["paused"]:
                T.status_chip(ui, "Tạm ngưng tự lấy", "grey", "pause_circle")
            else:
                T.status_chip(ui, f"{BL.EVERY_CHOICES[st['every_days']]} · lần tới {due:%d/%m} · ~"
                              + f"{BL.monthly_estimate(st):.2f} USD/tháng".replace(".", ","), "green", "event_repeat")

    def kpis(bl, ls) -> None:
        now, prev = (bl or {}).get("now"), (bl or {}).get("prev")
        if not now:
            return

        def delta(field: str, good_up: bool = True):
            if not prev or now[field] is None or prev[field] is None:
                return "", None, None
            d = now[field] - prev[field]
            if not d:
                return "", None, None
            return (f"{'+' if d > 0 else '−'}{F.n(abs(d))}", (d > 0) == good_up,
                    {"label": f"lần lấy {date.fromisoformat(prev['day']):%d/%m}", "value": F.n(prev[field])})
        with T.kpi_row(ui):
            d, g, _ = delta("referring_domains")
            T.kpi(ui, "language", "Website trỏ về", F.n(now["referring_domains"] or 0), delta=d, good=g, tone="green",
                  info=("Số website (tên miền) khác nhau đang có ít nhất một link về site.",
                        "Chỉ số quan trọng nhất: nhiều website khác nhau link về có giá trị hơn nhiều link từ một "
                        "website."),
                  hint=f"{F.n(now['referring_domains_nofollow'] or 0)} website chỉ có link nofollow")
            d, g, _ = delta("backlinks")
            T.kpi(ui, "link", "Backlink", F.n(now["backlinks"] or 0), delta=d, good=g, tone="blue",
                  info=("Tổng số link đang trỏ về site (một website có thể link nhiều lần).",))
            d, g, _ = delta("rank")
            T.kpi(ui, "military_tech", "Uy tín", f"{now['rank'] if now['rank'] is not None else '–'}/1000", delta=d,
                  good=g, tone="lime",
                  info=("Điểm uy tín của website theo DataForSEO (0–1000), tính từ số và chất lượng link trỏ về.",))
            d, g, _ = delta("spam_score", good_up=False)
            spam = now["spam_score"]
            T.kpi(ui, "gpp_maybe", "Điểm spam", f"{spam if spam is not None else '–'}/100", delta=d, good=g,
                  tone="red" if (spam or 0) >= 30 else "grey",
                  info=("Điểm spam trung bình của các backlink (0–100). Càng thấp càng tốt.",
                        "Từ 30 trở lên nên xem lại các website link về có dấu hiệu spam."),
                  hint=f"{F.n(now['broken_backlinks'] or 0)} link trỏ về trang không còn (link gãy)")
            ch = (ls.get("changes") or {}).get("items")
            if ch is not None:
                new_n = sum(1 for x in ch if not x["lost"])
                card = T.kpi(ui, "swap_vert", f"Link {BL.CHANGE_DAYS} ngày qua", f"+{new_n} / −{len(ch) - new_n}",
                             tone="purple",
                             info=(f"Số backlink mới xuất hiện / vừa mất trong {BL.CHANGE_DAYS} ngày gần nhất.",
                                   "Bấm để xem danh sách."),
                             hint=f"{sum(1 for x in ch if not x['lost'] and (x.get('spam') or 0) >= SPAM_FLAG)} "
                                  "link mới có điểm spam cao")
                card.classes("clickable").on("click", lambda: go("changes"))

    def open_check(tab: str, key: str) -> None:
        """Sang tab chứa mục kiểm tra và bật bộ lọc của mục đó."""
        go(tab)
        f = state.get("setf", {}).get(tab)
        if f:
            f(key, toggle=False)

    def go(tab: str) -> None:
        tabs_ = state.get("tabs")  # thanh tab của lần vẽ trang gần nhất
        if tabs_ is not None:
            tabs_.set_value(tab)

    def todo(checks: list[dict]) -> None:
        """Tổng quan: các việc cần xử lý / nên xem rút gọn, bấm để sang tab Audit."""
        items = [c for c in checks if c["level"] in ("high", "medium")]
        if not checks:
            return
        with T.section(ui, "Việc cần làm", "fact_check",
                       f"{len(items)} việc · bấm để xem ở tab tương ứng" if items else "Không có việc gấp"):
            if not items:
                ui.label("Audit không thấy vấn đề cần xử lý.").classes("text-sm muted")
            with ui.element("div").classes("sr-au-todo"):
                for c in items:
                    label, tone, icon = LEVELS[c["level"]]
                    row = ui.element("button").classes("sr-au-todo-row").props('type="button"')
                    row.on("click", lambda _, t=CHECK_TAB.get(c["key"], "overview"), k=c["key"]: open_check(t, k))
                    with row:
                        T.status_chip(ui, label, tone, icon)
                        ui.label(c["title"]).classes("text-sm font-semibold").style("flex:1 1 0; text-align:left")
                        num = f"{c['count']}{c['unit']}" if c["unit"].startswith("%") else f"{c['count']} {c['unit']}"
                        ui.label(num).classes("num text-sm font-semibold")
                        ui.icon("chevron_right", size="18px").style("color:#8C8A7E")

    def trend(bl) -> None:
        hist = [h for h in (bl or {}).get("history") or [] if h["referring_domains"] is not None]
        if len(hist) < 2:
            return
        labels = [f"{h['month'][5:]}/{h['month'][2:4]}" for h in hist]
        axis = {"axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                "axisLabel": {"color": "#8C8A7E", "fontSize": 11}}
        y = {"type": "value", "splitNumber": 4, "splitLine": {"lineStyle": {"color": "#EEECE4"}},
             "axisLabel": {"color": "#8C8A7E", "fontSize": 11}}
        with ui.element("div").classes("sr-bl-two w-full"):
            with T.section(ui, "Website trỏ về theo tháng", "show_chart", f"{len(hist)} tháng gần nhất"):
                ui.echart({"animation": False, "grid": {"left": 40, "right": 12, "top": 14, "bottom": 26},
                           "tooltip": {"trigger": "axis"},
                           "xAxis": {"type": "category", "data": labels, "boundaryGap": False, **axis},
                           "yAxis": y,
                           "series": [{"type": "line", "name": "Website trỏ về", "symbol": "circle", "symbolSize": 7,
                                       "lineStyle": {"width": 2, "color": "#1E7C31"}, "itemStyle": {"color": "#1E7C31"},
                                       "areaStyle": {"color": "rgba(30,124,49,.08)"},
                                       "data": [h["referring_domains"] for h in hist]}]}
                           ).classes("w-full").style("height:220px")
            with T.section(ui, "Link mới và link mất mỗi tháng", "bar_chart",
                           "Số backlink xuất hiện mới / không còn trong tháng"):
                ui.echart({"animation": False, "grid": {"left": 40, "right": 12, "top": 30, "bottom": 26},
                           "legend": {"top": 0, "right": 0, "icon": "roundRect", "itemWidth": 10, "itemHeight": 10,
                                      "textStyle": {"fontSize": 12, "color": "#4A4A40"}},
                           "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                           "xAxis": {"type": "category", "data": labels, **axis}, "yAxis": y,
                           "series": [{"type": "bar", "name": "Link mới", "barMaxWidth": 14,
                                       "itemStyle": {"color": "#1E7C31", "borderRadius": [3, 3, 0, 0]},
                                       "data": [h["new_backlinks"] or 0 for h in hist]},
                                      {"type": "bar", "name": "Link mất", "barMaxWidth": 14,
                                       "itemStyle": {"color": "#C2410C", "borderRadius": [3, 3, 0, 0]},
                                       "data": [h["lost_backlinks"] or 0 for h in hist]}]}
                           ).classes("w-full").style("height:220px")

    def brand_terms_of(own: dict | None) -> list[str]:
        stem = re.sub(r"^www\.", "", urlparse(site if "://" in site else "https://" + site.split(":")[-1]).netloc or "")
        return [_fold(t) for t in [stem.split(".")[0]] + ([own["name"]] + own.get("aliases", []) if own else []) if t]

    LEVELS = {"high": ("Cần xử lý", "red", "error"), "medium": ("Nên xem", "amber", "warning"),
              "info": ("Tham khảo", "blue", "info"), "ok": ("Ổn", "green", "check_circle")}

    def list_panel(kind: str, ls: dict, own: dict | None, checks: list[dict]) -> None:
        """Một tab danh sách: khối Kiểm tra (mỗi mục là một bộ lọc, bấm thì bảng bên dưới chỉ còn các dòng của mục
        đó và trang cuộn xuống bảng; bấm lại để bỏ lọc), rồi bảng."""
        brand_terms = brand_terms_of(own)
        title = {k: n for k, n, _ in TABS}[kind]
        icon = {k: i for k, _, i in TABS}[kind]
        anchor_id = f"bl-table-{kind}"
        by_key = {c["key"]: c for c in checks}

        def set_filter(key: str | None, toggle: bool = True) -> None:
            state["f"][kind] = None if toggle and state["f"][kind] == key else key
            check_rows.refresh()
            table.refresh()
            if state["f"][kind]:
                ui.run_javascript(f"document.getElementById('{anchor_id}')?.scrollIntoView("
                                  "{behavior: 'smooth', block: 'start'})")

        state.setdefault("setf", {})[kind] = set_filter  # "Việc cần làm" ở Tổng quan bật lọc của tab này

        @ui.refreshable
        def check_rows() -> None:
            for c in checks:
                label, tone, icon_ = LEVELS[c["level"]]
                can = c["key"] == "anchor_mix" or c["count"] > 0
                on = state["f"][kind] == c["key"]
                row = ui.element("button").classes("sr-au-filter" + (" on" if on else "")
                                                   + ("" if can else " off")).props('type="button"')
                if can:
                    row.on("click", lambda _, k=c["key"]: set_filter(k))
                with row:
                    T.status_chip(ui, label, tone, icon_)
                    with ui.column().classes("gap-0").style("min-width:0; flex:1 1 0; text-align:left"):
                        ui.label(c["title"]).classes("text-sm font-semibold")
                        ui.label(c["action"]).classes("text-xs muted")
                    num = f"{c['count']}{c['unit']}" if c["unit"].startswith("%") else f"{c['count']} {c['unit']}"
                    ui.label(num).classes("sr-au-num num")
                    if can:
                        ui.icon("close" if on else "filter_list", size="18px").classes("sr-au-ico")
                row.tooltip(("Bấm lại để bỏ lọc" if on else "Bấm để lọc bảng bên dưới theo mục này. ") + c["why"]
                            if can else c["why"])

        if checks:
            n_high = sum(1 for c in checks if c["level"] == "high")
            n_med = sum(1 for c in checks if c["level"] == "medium")
            sub = (f"{n_high} việc cần xử lý · {n_med} việc nên xem" if n_high or n_med else "Không có vấn đề")
            with T.section(ui, "Kiểm tra", "fact_check", sub + " · bấm một mục để lọc bảng bên dưới"):
                with ui.element("div").classes("sr-au-todo"):
                    check_rows()
                if any(c.get("disavow") for c in checks) and ed:
                    def download(_=None):
                        ui.download.content(AU.disavow(ls, f"{date.today():%d/%m/%Y}"),
                                            f"disavow-{urlparse(site).netloc or 'site'}-{date.today():%Y%m%d}.txt",
                                            "text/plain")
                    ui.button("Tải file disavow (.txt)", icon="download", on_click=download).props(
                        "outline no-caps dense color=grey-9").classes("q-mt-sm").tooltip(
                        "File theo định dạng của Google: một dòng domain:… cho mỗi website có link spam. Xem lại "
                        "trước khi nộp; disavow nhầm website tốt sẽ làm mất giá trị link.")
        sec = T.section(ui, title, icon)
        with sec:
            ui.element("div").props(f'id="{anchor_id}"').style("position:relative; top:-80px")
            with ui.row().classes("items-center gap-2 w-full"):
                note_box = ui.row().classes("items-center gap-2").style("min-width:0; flex:1 1 0")
                ui.input(placeholder="Tìm…", value=state["q"][kind],
                         on_change=lambda e: (state["q"].update({kind: e.value or ""}), table.refresh())).props(
                    "dense outlined clearable debounce=300").classes("w-56").props('aria-label="Tìm trong danh sách"')
                if ls.get(kind):
                    export_btn(kind, kind, f"Xuất {title.lower()} (đủ cột, kể cả URL đầy đủ)")

            @ui.refreshable
            def table():
                data = ls.get(kind)
                if not data:
                    ui.label("Chưa lấy danh sách này. " + ("Bấm “Lấy số mới” ở đầu trang." if ed else "")).classes(
                        "text-sm muted q-py-md")
                    return
                items = data["items"]
                fkey = state["f"][kind]
                if fkey:  # lọc theo mục kiểm tra đang chọn
                    items = [x for x in items if AU.matches(fkey, x, brand_terms)]
                q = _fold(state["q"][kind])
                shown_n = len(items)
                note = (f"Lấy lúc {_vn(data['fetched_at'][:10])} · hiện {shown_n}"
                        + (f" / {F.n(data['total'])}" if data.get("total") and data["total"] > shown_n else "")
                        + " dòng")
                if kind == "domains":
                    cols = [("domain", "Website", "left"), ("rank", "Uy tín", "right"),
                            ("backlinks", "Backlink", "right"), ("dofollow", "Trang dofollow", "right"),
                            ("first_seen", "Thấy lần đầu", "left"), ("spam", "Spam", "right")]
                    rows = [{"domain": x["domain"], "rank": x["rank"], "backlinks": x["backlinks"],
                             "dofollow": f"{x['dofollow_pages']}/{x['pages']}", "first_seen": _vn(x["first_seen"]),
                             "first_iso": x["first_seen"], "spam": x["spam"], "href": f"https://{x['domain']}"}
                            for x in items]
                    note += " · xếp theo uy tín"
                elif kind == "changes":
                    new_n = sum(1 for x in items if not x["lost"])
                    spam_n = sum(1 for x in items if (x.get("spam") or 0) >= SPAM_FLAG)
                    note += f" · {new_n} link mới, {len(items) - new_n} link mất trong {BL.CHANGE_DAYS} ngày" + (
                        f" · {spam_n} link có điểm spam ≥ {SPAM_FLAG}" if spam_n else "")
                    cols = [("status", "", "left"), ("source", "Trang link về", "left"), ("anchor", "Anchor", "left"),
                            ("target", "Trang đích", "left"), ("follow", "Loại", "left"),
                            ("when", "Ngày", "left")]
                    rows = [{"status": "Mất" if x["lost"] else "Mới", "lost": x["lost"],
                             "source": x["domain_from"], "title": x.get("title") or "", "href": x["url_from"],
                             "anchor": x["anchor"] or ("(ảnh)" if x.get("type") == "image" else "(trống)"),
                             "target": _path(x["url_to"]), "follow": "dofollow" if x["dofollow"] else "nofollow",
                             "spam": x.get("spam"), "spammy": (x.get("spam") or 0) >= SPAM_FLAG,
                             "when": _vn(x["last_seen"] if x["lost"] else x["first_seen"]),
                             "first_iso": x["last_seen"] if x["lost"] else x["first_seen"]} for x in items]
                elif kind == "anchors":
                    tot = sum(x["domains"] or 0 for x in items) or 1
                    counts: dict[str, int] = {}
                    rows = []
                    for x in items:
                        t = anchor_type(x["anchor"], brand_terms)
                        counts[t] = counts.get(t, 0) + (x["domains"] or 0)
                        rows.append({"anchor": x["anchor"] or "(trống / ảnh)", "type": ANCHOR_TYPES[t][0],
                                     "tcls": ANCHOR_TYPES[t][1], "domains": x["domains"], "backlinks": x["backlinks"],
                                     "share": f"{(x['domains'] or 0) / tot * 100:.0f}%".replace(".", ","),
                                     "first_seen": _vn(x["first_seen"]), "first_iso": x["first_seen"]})
                    cols = [("anchor", "Anchor text", "left"), ("type", "Loại", "left"),
                            ("domains", "Website dùng", "right"), ("share", "Tỷ lệ", "right"),
                            ("backlinks", "Backlink", "right"), ("first_seen", "Thấy lần đầu", "left")]
                    with ui.element("div").classes("sr-bl-mix q-mt-sm"):
                        for t, (label, cls) in ANCHOR_TYPES.items():
                            v = counts.get(t, 0)
                            ui.html(f"<span class='sr-bl-type {cls}'>{label}</span> "
                                    f"<b class='num'>{v / tot * 100:.0f}%</b>")
                    note += " · tỷ lệ tính trên số website dùng anchor, trong các anchor đã lấy"
                else:
                    cols = [("page", "Trang", "left"), ("domains", "Website trỏ về", "right"),
                            ("backlinks", "Backlink", "right"), ("rank", "Uy tín", "right")]
                    rows = [{"page": _path(x["page"]), "title": x.get("title") or "", "href": x["page"],
                             "domains": x["domains"], "backlinks": x["backlinks"], "rank": x["rank"],
                             "gone": (x.get("status") or 200) >= 400} for x in items]
                    note += " · xếp theo số website trỏ về"
                if q:
                    rows = [r for r in rows if q in _fold(" ".join(str(v) for v in r.values()))]
                for i, r in enumerate(rows):
                    r["id"] = i
                columns = [{"name": n, "label": lab, "field": n, "align": al, "sortable": bool(lab)}
                           for n, lab, al in cols]
                for c_ in columns:
                    if c_["name"] in ("first_seen", "when"):
                        c_[":sort"] = "(a, b, rowA, rowB) => (rowA.first_iso || '').localeCompare(rowB.first_iso || '')"
                note_box.clear()
                with note_box:
                    if fkey and fkey in by_key:
                        chip = ui.element("button").classes("sr-au-chip").props('type="button"')
                        chip.on("click", lambda: set_filter(fkey))
                        with chip:
                            ui.icon("filter_list", size="15px")
                            ui.label(f"Đang lọc: {by_key[fkey]['title']} · {len(items)} dòng")
                            ui.icon("close", size="15px")
                        chip.tooltip("Bỏ lọc")
                    ui.label(note).classes("text-xs muted")
                tb = ui.table(columns=columns, rows=rows, row_key="id", pagination=20).props(
                    "flat dense binary-state-sort").classes("w-full sr-bl-table")
                tb.add_slot("body-cell-domain", """
                    <q-td :props="props"><a :href="props.row.href" target="_blank" rel="noopener"
                       class="sr-bl-link">{{ props.value }}</a></q-td>""")
                tb.add_slot("body-cell-source", """
                    <q-td :props="props"><div class="sr-bl-src">
                      <a :href="props.row.href" target="_blank" rel="noopener" class="sr-bl-link" :title="props.row.href">{{ props.value }}</a>
                      <div v-if="props.row.title" class="sr-bl-sub ellipsis">{{ props.row.title }}</div></div>
                    </q-td>""")
                tb.add_slot("body-cell-anchor", """
                    <q-td :props="props"><div class="sr-bl-anchor" :title="props.value">{{ props.value }}</div>
                    </q-td>""")
                tb.add_slot("body-cell-target", """
                    <q-td :props="props"><div class="sr-bl-anchor" :title="props.value">{{ props.value }}</div>
                    </q-td>""")
                tb.add_slot("body-cell-follow", """
                    <q-td :props="props"><span class="text-xs">{{ props.value }}</span>
                      <span v-if="props.row.spammy" class="sr-bl-type k-lost q-ml-xs">spam {{ props.row.spam }}
                        <q-tooltip>Điểm spam của link này (0–100) theo DataForSEO: trang nguồn có dấu hiệu bán / spam
                          link</q-tooltip></span></q-td>""")
                tb.add_slot("body-cell-status", """
                    <q-td :props="props"><span class="sr-bl-type" :class="props.row.lost ? 'k-lost' : 'k-new'">
                      {{ props.value }}</span></q-td>""")
                tb.add_slot("body-cell-type", """
                    <q-td :props="props"><span class="sr-bl-type" :class="props.row.tcls">{{ props.value }}</span>
                    </q-td>""")
                tb.add_slot("body-cell-page", """
                    <q-td :props="props"><div class="sr-bl-src">
                      <a :href="props.row.href" target="_blank" rel="noopener" class="sr-bl-link" :title="props.row.href">{{ props.value }}</a>
                      <span v-if="props.row.gone" class="sr-bl-type k-lost q-ml-xs">trang lỗi</span>
                      <div v-if="props.row.title" class="sr-bl-sub ellipsis">{{ props.row.title }}</div></div>
                    </q-td>""")
            table()

    body()
