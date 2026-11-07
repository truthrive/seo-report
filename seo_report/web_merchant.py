"""Trang Merchant Center (/merchant): sản phẩm của dự án trên Google Shopping / hiển thị miễn phí (Merchant API).

Tab Tổng quan (số sản phẩm theo trạng thái, click / lượt hiển thị, sản phẩm nhiều click, vấn đề tài khoản) · Sản phẩm
(khối Kiểm tra: mỗi mục là một bộ lọc cho bảng sản phẩm bên dưới). Khách hàng xem được; người sửa được mới gắn tài
khoản và bấm lấy số mới (API miễn phí).
"""
import io
from datetime import date, timedelta

from . import access as A
from . import ai_format as F
from . import merchant as M
from . import ui_theme as T

PERIODS = {28: "28 ngày", 90: "90 ngày"}
TABS = (("overview", "Tổng quan"), ("products", "Sản phẩm"))
LEVELS = {"high": ("Cần sửa", "red", "error"), "medium": ("Nên sửa", "amber", "warning"),
          "info": ("Tham khảo", "blue", "info")}
METHODS = {"ORGANIC": "Hiển thị miễn phí", "ADS": "Quảng cáo Shopping", "AFFILIATE": "Liên kết"}


def _vn(d: date) -> str:
    return f"{d:%d/%m/%Y}"


def build_merchant_page(ui, cfg, connect, user, start: str = "") -> None:
    from nicegui import run

    from . import auth
    from .web_local import _scopes
    ed = A.can_edit(user)
    right = T.page_header(ui, "shopping_bag", "Merchant Center",
                          "Sản phẩm trên Google Shopping và hiển thị miễn phí: bao nhiêu sản phẩm được hiện, sản phẩm "
                          "nào bị từ chối / hạn chế và vì sao, click từ Google. Số của Google, tự lấy mỗi ngày.")
    state = {"tab": start if start in dict(TABS) else "overview", "days": 28, "method": "ORGANIC", "f": None,
             "q": "", "status": "all"}
    has_scope = not auth.missing_scopes(_scopes(cfg), (auth.CONTENT_SCOPE,))

    async def fetch(btn) -> None:
        if not ed:
            return
        from contextlib import closing

        from . import db
        btn.props("loading")

        def work():
            logs: list[str] = []
            with closing(db.connect(cfg.db_path)) as c:
                r = M.refresh(c, cfg, log=logs.append)
            return r, logs
        try:
            r, bad = await run.io_bound(work)
            ui.notify(f"Đã lấy {r.get('products') or 0} sản phẩm" + (f" ({len(bad)} lỗi)" if bad else ""),
                      caption=" · ".join(bad)[:400] or None, type="warning" if bad else "positive",
                      position="bottom-right", classes="sr-toast", multi_line=True, timeout=0 if bad else 4500,
                      close_button="Đóng" if bad else None)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify("Không lấy được số Merchant Center", caption=M.explain(e), type="negative",
                      position="bottom-right", classes="sr-toast", timeout=0, close_button="Đóng")
        btn.props(remove="loading")
        body.refresh()

    def register_form(box, foot, dlg) -> None:
        """Merchant API bắt buộc đăng ký Google Cloud project của tool với tài khoản Merchant Center một lần. Người
        dùng tự nhập ID tài khoản và email liên hệ rồi bấm Đăng ký (thay đổi cài đặt trên tài khoản Merchant Center)."""
        with box:
            ui.label("Cần đăng ký tool với tài khoản Merchant Center (làm một lần)").classes("text-sm font-semibold")
            ui.label("Google yêu cầu Google Cloud project của tool được đăng ký với tài khoản Merchant Center trước khi "
                     "đọc số. Tài khoản Google đang kết nối với tool phải là quản trị viên của tài khoản Merchant "
                     "Center đó.").classes("text-xs muted")
            acc_in = ui.input("ID tài khoản Merchant Center",
                              placeholder="Số ở góc trên bên phải Merchant Center, ví dụ 123456789").props(
                "dense outlined").classes("w-full q-mt-sm")
            mail_in = ui.input("Email liên hệ về API", placeholder="email công ty của người phụ trách").props(
                "dense outlined").classes("w-full")
            ui.label("Email này nhận vai trò “API developer” trong Merchant Center (chỉ nhận thông báo về API, quyền "
                     "rất hạn chế). Chưa là người dùng của tài khoản thì Google gửi lời mời tới email này.").classes(
                "text-xs muted")
            msg = ui.label("").classes("text-sm")

        async def do_register(btn) -> None:
            acc_id = "".join(ch for ch in (acc_in.value or "") if ch.isdigit())
            email = (mail_in.value or "").strip()
            if not acc_id or "@" not in email:
                msg.set_text("Nhập ID tài khoản (chỉ gồm số) và một email hợp lệ.")
                msg.style(f"color:{T.RED}")
                return
            btn.props("loading")
            try:
                await run.io_bound(lambda: M.Client(auth.get_credentials(cfg, need=(auth.CONTENT_SCOPE,))).register(
                    acc_id, email))
            except (Exception, SystemExit) as e:  # noqa: BLE001
                btn.props(remove="loading")
                msg.set_text(f"Không đăng ký được. {M.explain(e) if isinstance(e, Exception) else e}")
                msg.style(f"color:{T.RED}")
                return
            btn.props(remove="loading")
            msg.set_text("Đã đăng ký. Google cần khoảng 5 phút để áp dụng: sau đó bấm “Tài khoản” lần nữa để chọn tài "
                         "khoản.")
            msg.style(f"color:{T.GREEN}")
            btn.disable()
        with foot:
            ui.button("Đóng", on_click=dlg.close).props("flat no-caps")
            rb = ui.button("Đăng ký", icon="how_to_reg").props("unelevated no-caps color=primary")
            rb.on_click(lambda _, b=rb: do_register(b))

    async def link_dialog() -> None:
        """Chọn tài khoản Merchant Center của dự án trong các tài khoản Google của tool có quyền."""
        if not ed:
            return
        with ui.dialog() as dlg, ui.card().style("border-radius:14px; width:620px; max-width:94vw"):
            ui.label("Gắn tài khoản Merchant Center").classes("text-base font-semibold")
            ui.label("Các tài khoản Merchant Center mà tài khoản Google của tool có quyền. Chọn tài khoản của website "
                     "này.").classes("text-xs muted")
            box = ui.column().classes("w-full gap-1 q-mt-sm")
            with box, ui.row().classes("items-center gap-2"):
                ui.spinner(size="20px")
                ui.label("Đang đọc danh sách tài khoản từ Google…").classes("text-sm muted")
            foot = ui.row().classes("w-full justify-end gap-2 q-mt-sm")
        dlg.open()

        def load():
            return M.Client(auth.get_credentials(cfg, need=(auth.CONTENT_SCOPE,))).accounts()
        try:
            accs = await run.io_bound(load)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            box.clear()
            if isinstance(e, Exception) and M.needs_registration(e):
                register_form(box, foot, dlg)
                return
            with box:
                ui.label(f"Không đọc được danh sách tài khoản. {M.explain(e)}").classes("text-sm").style(
                    f"color:{T.RED}")
            with foot:
                ui.button("Đóng", on_click=dlg.close).props("flat no-caps")
            return
        with connect() as c:
            cur = M.linked(c)
        from .projects import domain
        want = domain(cfg.site_url)

        def home(a):
            return a.get("homepageUri") or a.get("homePageUri") or ""

        def match(a):
            h = home(a)
            return bool(h) and (domain(h) == want or domain(h).endswith("." + want))
        box.clear()
        if not accs:
            with box:
                ui.label("Tài khoản Google của tool chưa có quyền với tài khoản Merchant Center nào. Trong Merchant "
                         "Center → Cài đặt → Người dùng, thêm email tool.").classes("text-sm muted")
            with foot:
                ui.button("Đóng", on_click=dlg.close).props("flat no-caps")
            return
        default = (cur or {}).get("account") or next((a["name"] for a in accs if match(a)), accs[0]["name"])
        with box:
            radio = ui.radio({a["name"]: a.get("accountName") or a["name"] for a in accs}, value=default).props(
                "dense").classes("w-full")
            for a in accs:
                ui.label(f"{a.get('accountName') or a['name']}: ID {a.get('accountId') or a['name'].split('/')[-1]}"
                         + (f" · {home(a)}" if home(a) else "") + (" · cùng website" if match(a) else "")).classes(
                    "text-xs muted")

        def save():
            a = next(x for x in accs if x["name"] == radio.value)
            with connect() as c:
                M.link(c, a, str(user))
            dlg.close()
            ui.notify(f"Đã gắn {a.get('accountName') or a['name']}. Bấm “Lấy số mới” để lấy số lần đầu.",
                      type="positive", position="bottom-right", classes="sr-toast")
            body.refresh()
        with foot:
            ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
            ui.button("Lưu", on_click=save).props("unelevated no-caps color=primary")

    right.classes("no-wrap").style("flex:none")  # hai nút không bị ép hẹp (chữ xuống dưới icon)
    if ed and has_scope:  # chưa có quyền: nút không dùng được, thân trang đã hướng dẫn cấp quyền
        with right, ui.row().classes("items-center no-wrap gap-2"):
            ui.button("Tài khoản", icon="storefront", on_click=link_dialog).props(
                "outline no-caps color=grey-9").style("white-space:nowrap").tooltip(
                "Gắn / đổi tài khoản Merchant Center của dự án")
            b = ui.button("Lấy số mới", icon="refresh").props("unelevated no-caps color=primary").style(
                "white-space:nowrap")
            b.on_click(lambda _, b=b: fetch(b))
            b.tooltip("Lấy lại sản phẩm, hiệu suất 90 ngày và vấn đề tài khoản từ Google (miễn phí)")

    @ui.refreshable
    def body():
        with connect() as c:
            acc = M.linked(c)
        if not has_scope:
            T.empty_state(ui, "lock", "Tool chưa có quyền Google Merchant Center",
                          "Chủ tool vào Cài đặt tích hợp → Kết nối Google, đăng nhập lại và tích ô quyền quản lý sản "
                          "phẩm Google Shopping." if ed else "Số Merchant Center sẽ có sau khi tool được cấp quyền.")
            return
        if not acc:
            T.empty_state(ui, "shopping_bag", "Chưa gắn tài khoản Merchant Center",
                          "Bấm “Tài khoản” để chọn tài khoản Merchant Center của website này." if ed
                          else "Số Merchant Center sẽ có sau khi gắn tài khoản.")
            return
        with connect() as c:
            prods = M.products(c)
            acc_issues = M.account_issues(c)
            last = M.last_day(c)
            ms = M.methods(c)
        if state["method"] not in ms and ms:
            state["method"] = "ORGANIC" if "ORGANIC" in ms else ms[0]
        end = date.fromisoformat(last) if last else date.today() - timedelta(days=1)
        with connect() as c:
            perf28 = M.per_product(c, end - timedelta(days=27), end, "ORGANIC") if last else None
        checks = M.audit(prods, acc_issues, perf28)
        with ui.row().classes("w-full items-center gap-2 q-mb-xs"):
            ui.label(f"{acc['name'] or acc['account']} · ID {acc['account'].split('/')[-1]}").classes(
                "text-sm font-semibold")
            ui.label(("Lấy số lần cuối " + acc["fetched_at"][:10].split("-")[2] + "/" + acc["fetched_at"][5:7]
                      if acc.get("fetched_at") else "Chưa lấy số lần nào" + (": bấm “Lấy số mới”." if ed else "."))
                     ).classes("text-xs muted")
            ui.space()
            from .web_export import export_menu
            export_menu(ui, cfg, connect, f"merchant-center_{date.today():%Y-%m-%d}",
                        lambda: make_xlsx(prods, checks), label="Xuất Merchant Center (Excel / Google Sheets)",
                        user=user, icon_only=True, category="merchant")
        n_high = sum(1 for c_ in checks if c_["level"] == "high" and c_["ids"])
        with ui.tabs(value=state["tab"], on_change=lambda e: pick(e.value)).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs sr-bl-tabs"):
            for k, label in TABS:
                with ui.tab(k, label):
                    if k == "products" and n_high:
                        ui.badge(str(n_high), color="red").props("rounded").classes("sr-tab-badge")
        with ui.tab_panels(value=state["tab"]).classes("w-full").props("animated=false") as panels:
            state["panels"] = panels
            with ui.tab_panel("overview").classes("q-px-none"):
                overview(prods, acc_issues, checks, last, ms)
            with ui.tab_panel("products").classes("q-px-none"):
                products_tab(prods, checks, perf28 or {})

    def pick(v: str) -> None:
        state["tab"] = v
        if state.get("panels") is not None:
            state["panels"].set_value(v)
        ui.run_javascript(f"history.replaceState(null, '', '/merchant' + ('{v}' === 'overview' ? '' : '?tab={v}'))")

    def overview(prods, acc_issues, checks, last, ms) -> None:
        n = len(prods)
        by = {k: sum(1 for p in prods if p["status"] == k) for k in M.STATUS}
        with T.kpi_row(ui):
            T.kpi(ui, "inventory_2", "Sản phẩm", F.n(n), tone="grey",
                  hint=f"{sum(1 for p in prods if p['availability'] == 'IN_STOCK')} còn hàng",
                  info=("Số sản phẩm trong tài khoản Merchant Center (mọi nguồn dữ liệu, mọi kênh).",))
            for key, icon, tone in (("ELIGIBLE", "check_circle", "green"), ("ELIGIBLE_LIMITED", "error_outline", "amber"),
                                    ("NOT_ELIGIBLE_OR_DISAPPROVED", "block", "red")):
                T.kpi(ui, icon, M.STATUS[key][0], F.n(by[key]), tone=tone,
                      hint=f"{by[key] / n * 100:.0f}% sản phẩm" if n else "",
                      info=({"ELIGIBLE": "Được hiện đầy đủ trên Google.",
                             "ELIGIBLE_LIMITED": "Vẫn hiện nhưng ít hơn hoặc chỉ ở một số nơi / quốc gia.",
                             "NOT_ELIGIBLE_OR_DISAPPROVED": "Không được hiện: cần sửa vấn đề rồi Google xét lại."}[key],))
        if acc_issues:
            with T.section(ui, "Vấn đề tài khoản", "report", f"{len(acc_issues)} vấn đề ở cấp tài khoản: ảnh hưởng tới "
                           "mọi sản phẩm"):
                with ui.element("div").classes("sr-au-todo"):
                    for i in acc_issues:
                        label, tone, icon = LEVELS[M.ACC_SEVERITY.get(i["severity"], "medium")]
                        with ui.element("div").classes("sr-au-filter off").style("cursor:default"):
                            T.status_chip(ui, label, tone, icon)
                            with ui.column().classes("gap-0").style("min-width:0; flex:1 1 0"):
                                ui.label(i["title"]).classes("text-sm font-semibold")
                                if i["detail"]:
                                    ui.label(i["detail"]).classes("text-xs muted")
                            if i["uri"]:
                                ui.link("Hướng dẫn", i["uri"], new_tab=True).classes("text-xs")
        todo = sorted([c_ for c_ in checks if c_["ids"] and c_["level"] in ("high", "medium")],
                      key=lambda c_: c_["level"] != "high")  # cần sửa trước, giữ thứ tự trong cùng mức
        if todo:
            with T.section(ui, "Việc cần làm với sản phẩm", "fact_check",
                           "Bấm một mục để mở tab Sản phẩm, lọc đúng các sản phẩm đó"):
                with ui.element("div").classes("sr-au-todo"):
                    for c_ in todo[:6]:
                        label, tone, icon = LEVELS[c_["level"]]
                        row = ui.element("button").classes("sr-au-todo-row").props('type="button"')
                        row.on("click", lambda _, k=c_["key"]: (state.update(f=k), pick("products"), body.refresh()))
                        with row:
                            T.status_chip(ui, label, tone, icon)
                            ui.label(c_["title"]).classes("text-sm font-semibold").style("flex:1 1 0; min-width:0")
                            ui.icon("chevron_right", size="18px").classes("sr-au-ico")
        if not last:
            ui.label("Chưa có số click / lượt hiển thị.").classes("text-sm muted q-py-md")
            return
        end = date.fromisoformat(last)
        n_days = state["days"]
        start, p_end = end - timedelta(days=n_days - 1), end - timedelta(days=n_days)
        p_start = p_end - timedelta(days=n_days - 1)
        method = state["method"]
        with ui.row().classes("items-center gap-2 q-mt-sm q-mb-sm"):
            t_ = ui.toggle(PERIODS, value=n_days, on_change=lambda e: (state.update(days=e.value), body.refresh())
                           ).props("unelevated no-caps dense toggle-color=white toggle-text-color=dark "
                                   "text-color=grey-8").classes("sr-seg")
            t_.props["aria-label"] = "Khoảng thời gian"
            if len(ms) > 1:
                ui.select({m: METHODS.get(m, m) for m in ms}, value=method,
                          on_change=lambda e: (state.update(method=e.value), body.refresh())).props(
                    "dense outlined options-dense").classes("w-56")
            ui.label(f"{_vn(start)} – {_vn(end)} · so với {n_days} ngày liền trước").classes("text-xs muted")
        with connect() as c:
            now, prev = M.totals(c, start, end, method), M.totals(c, p_start, p_end, method)
            ser = M.series(c, end - timedelta(days=PERF_WEEKS * 7), end, method)
            per = M.per_product(c, start, end, method)
        with T.kpi_row(ui):
            for key, icon, label, tone in (("clicks", "ads_click", "Click", "blue"),
                                           ("impressions", "visibility", "Lượt hiển thị", "green")):
                v, p = now[key], prev[key]
                d = v - p
                T.kpi(ui, icon, label, F.n(v), delta=(f"{'+' if d > 0 else '−'}{F.n(abs(d))}" if d and p else ""),
                      good=(d > 0) if d else None, tone=tone, hint=METHODS.get(method, method),
                      prev={"label": f"{n_days} ngày trước", "value": F.n(p)} if p else None)
            ctr = now["clicks"] / now["impressions"] if now["impressions"] else None
            T.kpi(ui, "percent", "Tỷ lệ click (CTR)", f"{ctr * 100:.2f}%".replace(".", ",") if ctr else "–",
                  tone="grey", hint="Click / lượt hiển thị")
        with ui.element("div").classes("sr-bl-two w-full"):
            with T.section(ui, "Click theo tuần", "bar_chart", f"{METHODS.get(method, method)} · rê chuột xem lượt "
                           "hiển thị"):
                if not ser:
                    ui.label("Chưa đủ một tuần số liệu.").classes("text-sm muted")
                else:
                    ui.echart({"animation": False, "grid": {"left": 44, "right": 12, "top": 14, "bottom": 26},
                               "tooltip": {"trigger": "axis", ":formatter": (
                                   "ps => 'Tuần ' + ps[0].axisValue + '<br/>' + ps[0].marker + 'Click: <b>' + "
                                   "ps[0].value.toLocaleString('vi-VN') + '</b><br/>Hiển thị: ' + "
                                   f"{[s['impressions'] for s in ser]}[ps[0].dataIndex].toLocaleString('vi-VN')")},
                               "xAxis": {"type": "category", "data": [f"{s['week'][8:10]}/{s['week'][5:7]}" for s in ser],
                                         "axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                                         "axisLabel": {"color": "#8C8A7E", "fontSize": 11}},
                               "yAxis": {"type": "value", "splitNumber": 4,
                                         "splitLine": {"lineStyle": {"color": "#EEECE4"}},
                                         "axisLabel": {"color": "#8C8A7E", "fontSize": 11}},
                               "series": [{"type": "bar", "barMaxWidth": 16, "data": [s["clicks"] for s in ser],
                                           "itemStyle": {"color": "#2a78d6", "borderRadius": [3, 3, 0, 0]}}]}
                              ).classes("w-full").style("height:220px")
            with T.section(ui, "Sản phẩm nhiều click", "star", f"{n_days} ngày gần nhất"):
                top = sorted(per.items(), key=lambda kv: (-kv[1]["clicks"], -kv[1]["impressions"]))[:8]
                if not top:
                    ui.label("Chưa có click.").classes("text-sm muted")
                for offer, v in top:
                    with ui.row().classes("w-full items-center no-wrap gap-2 sr-cwv-part"):
                        ui.label(v["title"] or offer).classes("text-sm ellipsis").style("flex:1 1 0; min-width:0") \
                            .props["title"] = v["title"] or offer
                        ui.label(f"{F.n(v['clicks'])} click").classes("num text-sm font-semibold")
                        ui.label(f"{F.n(v['impressions'])} hiển thị").classes("num text-xs muted").style(
                            "width:96px; text-align:right")

    def products_tab(prods, checks, perf28) -> None:
        if not prods:
            ui.label("Chưa có sản phẩm nào (hoặc chưa lấy số).").classes("text-sm muted q-py-md")
            return
        pchecks = [c_ for c_ in checks if c_["ids"]]
        anchor = "mc-table"

        def set_filter(key: str | None) -> None:
            state["f"] = None if state["f"] == key else key
            check_rows.refresh()
            table.refresh()
            if state["f"]:
                ui.run_javascript(f"document.getElementById('{anchor}')?.scrollIntoView({{behavior: 'smooth', "
                                  "block: 'start'}})")

        @ui.refreshable
        def check_rows() -> None:
            for c_ in pchecks:
                label, tone, icon = LEVELS[c_["level"]]
                on = state["f"] == c_["key"]
                row = ui.element("button").classes("sr-au-filter" + (" on" if on else "")).props('type="button"')
                row.on("click", lambda _, k=c_["key"]: set_filter(k))
                with row:
                    T.status_chip(ui, label, tone, icon)
                    with ui.column().classes("gap-0").style("min-width:0; flex:1 1 0; text-align:left"):
                        ui.label(c_["title"]).classes("text-sm font-semibold")
                        ui.label(c_["detail"]).classes("text-xs muted")
                    ui.icon("close" if on else "filter_list", size="18px").classes("sr-au-ico")
                row.tooltip("Bấm lại để bỏ lọc" if on else "Bấm để lọc bảng sản phẩm theo mục này")

        if pchecks:
            n_high = sum(1 for c_ in pchecks if c_["level"] == "high")
            n_med = sum(1 for c_ in pchecks if c_["level"] == "medium")
            with T.section(ui, "Kiểm tra", "fact_check",
                           (f"{n_high} việc cần sửa · {n_med} việc nên sửa" if n_high or n_med else "Không có vấn đề "
                            "nặng") + " · bấm một mục để lọc bảng bên dưới"):
                with ui.element("div").classes("sr-au-todo"):
                    check_rows()
        else:
            with T.section(ui, "Kiểm tra", "fact_check", "Không có vấn đề nào"):
                ui.label("Mọi sản phẩm đủ điều kiện, không có cảnh báo.").classes("text-sm muted")

        by_key = {c_["key"]: c_ for c_ in pchecks}
        with T.section(ui, "Sản phẩm", "inventory_2", "Click / lượt hiển thị: hiển thị miễn phí, 28 ngày gần nhất"):
            ui.element("div").props(f'id="{anchor}"')
            with ui.row().classes("w-full items-center gap-2"):
                ui.select({"all": "Mọi trạng thái", **{k: v[0] for k, v in M.STATUS.items()}}, value=state["status"],
                          on_change=lambda e: (state.update(status=e.value), table.refresh())).props(
                    "dense outlined options-dense").classes("w-48")
                ui.input(placeholder="Tìm tên / mã sản phẩm…", value=state["q"],
                         on_change=lambda e: (state.update(q=e.value or ""), table.refresh())).props(
                    "dense outlined clearable debounce=300").classes("w-64")

            @ui.refreshable
            def table() -> None:
                f = by_key.get(state["f"])
                ids = set(f["ids"]) if f else None
                q = (state["q"] or "").strip().lower()
                rows = []
                for p in prods:
                    if ids is not None and p["id"] not in ids:
                        continue
                    if state["status"] != "all" and p["status"] != state["status"]:
                        continue
                    if q and q not in p["title"].lower() and q not in p["offer_id"].lower():
                        continue
                    pf = perf28.get(p["offer_id"]) or {}
                    st = M.STATUS.get(p["status"], (p["status"] or "–", "grey"))
                    issues = [i for i in p["issues"] if (i.get("resolution") or "") != "PENDING_PROCESSING"]
                    rows.append({"id": p["id"], "title": p["title"] or p["offer_id"], "offer": p["offer_id"],
                                 "thumb": p["thumbnail"], "status": st[0], "tone": st[1],
                                 "issues": " · ".join(sorted({M.issue_label(i) for i in issues})) or "–",
                                 "n_issues": len(issues), "clicks": pf.get("clicks", 0),
                                 "impressions": pf.get("impressions", 0),
                                 "price": (F.n(round(p["price"])) + (" " + p["currency"] if p["currency"] else ""))
                                 if p["price"] is not None else "–",
                                 "avail": M.AVAIL.get(p["availability"], p["availability"] or "–")})
                ui.label(f"{len(rows)} / {len(prods)} sản phẩm" + (f" · đang lọc: {f['title']}" if f else "")).classes(
                    "text-xs muted q-mt-xs")
                cols = [{"name": "title", "label": "Sản phẩm", "field": "title", "align": "left", "sortable": True},
                        {"name": "status", "label": "Trạng thái", "field": "status", "align": "left", "sortable": True,
                         "headerStyle": "width:120px"},
                        {"name": "issues", "label": "Vấn đề", "field": "issues", "align": "left",
                         "headerStyle": "width:30%"},
                        {"name": "clicks", "label": "Click", "field": "clicks", "align": "right", "sortable": True,
                         "headerStyle": "width:80px"},
                        {"name": "impressions", "label": "Hiển thị", "field": "impressions", "align": "right",
                         "sortable": True, "headerStyle": "width:90px"},
                        {"name": "price", "label": "Giá", "field": "price", "align": "right",
                         "headerStyle": "width:110px"},
                        {"name": "avail", "label": "Tồn kho", "field": "avail", "align": "left",
                         "headerStyle": "width:100px"}]
                tb = ui.table(columns=cols, rows=rows, row_key="id", pagination=25).props(
                    "flat dense binary-state-sort").classes("w-full")
                tb.add_slot("body-cell-title", """
                    <q-td :props="props"><div style="display:flex; align-items:center; gap:10px; min-width:0">
                      <img v-if="props.row.thumb" :src="props.row.thumb" alt="" loading="lazy"
                        style="width:36px; height:36px; object-fit:cover; border-radius:6px; flex:none; background:#F1F0EA">
                      <div style="min-width:0"><div class="text-sm" style="white-space:normal">{{ props.value }}</div>
                        <div class="text-xs muted">{{ props.row.offer }}</div></div></div></q-td>""")
                tb.add_slot("body-cell-status", """
                    <q-td :props="props"><span class="sr-pill" :style="{
                      background: {green:'#E7F3EA', amber:'#FBF0DC', red:'#FCEDE6', blue:'#E8EFFD'}[props.row.tone] || '#EFEFE8',
                      color: {green:'#1E7C31', amber:'#8F5F14', red:'#C2410C', blue:'#2a5bab'}[props.row.tone] || '#6B6A5E'
                      }">{{ props.value }}</span></q-td>""")
                tb.add_slot("body-cell-issues", """
                    <q-td :props="props"><div class="text-xs" style="white-space:normal">{{ props.value }}</div></q-td>""")
            table()

    def make_xlsx(prods, checks) -> bytes:
        from openpyxl import Workbook

        from .export import INT, _sheet
        with connect() as c:
            last = M.last_day(c)
            end = date.fromisoformat(last) if last else date.today()
            perf = M.per_product(c, end - timedelta(days=27), end, "ORGANIC")
            daily = c.execute("SELECT day, method, SUM(clicks), SUM(impressions) FROM merchant_perf GROUP BY day, "
                              "method ORDER BY day").fetchall()
        wb = Workbook()
        wb.remove(wb.active)
        _sheet(wb, "Sản phẩm", [("Mã", 18, None), ("Tên", 60, None), ("Thương hiệu", 18, None), ("Trạng thái", 14, None),
                                ("Vấn đề", 70, None), ("Click 28 ngày", 12, INT), ("Hiển thị 28 ngày", 14, INT),
                                ("Giá", 12, INT), ("Tồn kho", 12, None), ("GTIN", 16, None)],
               [[p["offer_id"], p["title"], p["brand"], M.STATUS.get(p["status"], (p["status"],))[0],
                 " · ".join(sorted({M.issue_label(i) for i in p["issues"]})),
                 (perf.get(p["offer_id"]) or {}).get("clicks", 0), (perf.get(p["offer_id"]) or {}).get("impressions", 0),
                 p["price"], M.AVAIL.get(p["availability"], p["availability"]), p["gtin"]] for p in prods])
        _sheet(wb, "Kiểm tra", [("Mức", 12, None), ("Mục", 60, None), ("Chi tiết", 90, None), ("Số sản phẩm", 12, INT)],
               [[LEVELS[c_["level"]][0], c_["title"], c_["detail"], len(c_["ids"])] for c_ in checks])
        _sheet(wb, "Theo ngày", [("Ngày", 12, None), ("Kênh", 20, None), ("Click", 10, INT), ("Hiển thị", 12, INT)],
               [[d, METHODS.get(m, m), c_, i] for d, m, c_, i in daily])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    body()


PERF_WEEKS = 13
