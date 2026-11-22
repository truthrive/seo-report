"""Trang Backlink (/backlink): số tổng, xu hướng 12 tháng và bốn danh sách (website trỏ về, link mới / mất 30 ngày,
anchor text, trang được link nhiều nhất), lấy từ DataForSEO Backlinks API (backlinks.py).

Khách hàng xem được; chỉ người sửa được dự án mới bấm "Lấy số mới" (tốn tiền DataForSEO, tính vào ngân sách website).
"""
import re
from datetime import date
from urllib.parse import quote, urlparse

from . import table_kit as TK
from . import web_labels as WL
from . import backlink_links as BLL
from . import web_backlink_links as WBL
from . import web_backlink_v2 as WV2
from . import spend as SP
from . import points as PT
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


# "Trang đích" gộp Trang được link + Trang cần link (bộ lọc); "Website trỏ về" gộp Link mới / mất (bộ lọc)
PAGE_TABS = (("overview", "Tổng quan"), ("audit", "Audit"), ("list", "Danh sách"), ("built", "Link đã xây"),
             ("gap", "Backlink GAP"), ("sources", "Nguồn dữ liệu"))
# Bốn cách xem cùng một kho link: gộp trong tab "Danh sách", chọn bằng thanh ngay dưới tab (link cũ ?tab=… vẫn chạy)
LIST_VIEWS = (("links", "Tất cả backlink"), ("domains", "Website trỏ về"), ("pages", "Trang đích"),
              ("anchors", "Anchor text"))
# có danh sách toàn bộ backlink: "Việc cần làm" ở Tổng quan dùng mục audit theo từng link thay cho các mục này
REPLACED = ("spam", "broken", "redirect", "heavy")
TEAM_TABS = ("built", "gap", "audit", "sources")  # việc của team / nguồn dữ liệu nội bộ: khách hàng không thấy
# link cũ ?tab=… → (tab, bộ lọc của tab)
OLD_TABS = {"needs": ("pages", "need"), "changes": ("domains", "moi")}
VIEWS = {"pages": ("all", "need"), "domains": ("all", "moi", "mat")}
CHECK_TAB = AU.CHECK_TAB  # mục kiểm tra nào nằm ở tab nào


COL_W = {"rank": 90, "backlinks": 100, "dofollow": 130, "first_seen": 120, "spam": 80, "status": 70,
         "anchor": 180, "target": 200, "follow": 130, "when": 100, "type": 120, "domains": 130, "share": 80}
KIT_NOUN = {"domains": "website", "changes": "link", "anchors": "anchor", "pages": "trang"}


def build_backlink_page(ui, cfg, connect, user, start: str = "", view: str = "") -> None:
    from nicegui import run

    site = cfg.site_url
    ed = A.can_edit(user)
    cl = A.is_client(user)  # khách hàng: không chi phí / lịch lấy, không điểm spam, không việc cần làm của team
    right = T.page_header(ui, "add_link", "Backlink",
                          "Ai đang link về website, link mới / mất, anchor" + ("." if cl else " và việc cần xử lý. Số của DataForSEO "
                          "và file Semrush đã nhập."))

    async def fetch(btn, points_ok: bool = False):
        if not ed:  # tốn tiền DataForSEO: chặn ở server, nút bị ẩn chưa đủ
            return
        if PT.member(user) and not points_ok:  # Member: báo số credit trước khi lấy
            bal = PT.my_balance(user) or {"left": 0, "limit": 0}
            need = PT.cost("backlink")
            with ui.dialog() as d, ui.card().style("max-width: 440px; border-radius: 14px"):
                ui.label("Lấy số backlink mới?").classes("text-lg font-semibold")
                with ui.row().classes("items-start no-wrap gap-2 sr-kr-paid"):
                    ui.icon("toll", size="18px")
                    ui.label(f"Trừ {need} credit (số tổng, lịch sử và các danh sách). Còn {bal['left']:,} / "
                             f"{bal['limit']:,} credit tháng này.".replace(",", ".")).classes("text-sm")
                with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                    ui.button("Hủy", on_click=d.close).props("flat no-caps")

                    async def ok():
                        d.close()
                        await fetch(btn, points_ok=True)
                    b_ok = ui.button("Lấy số", icon="refresh", on_click=ok).props("unelevated no-caps")
                    if need > bal["left"]:
                        b_ok.disable()
            d.open()
            return
        from contextlib import closing

        from . import db
        _pt = PT.take(ui, user, cfg, "backlink")
        if _pt is False:
            return
        btn.props("loading")

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                logs: list[str] = []
                with SP.runner(str(user)):
                    BL.refresh(c, site, cfg, force=True, log=logs.append)
                return logs
        try:
            logs = await run.io_bound(work)
            bad = [m for m in logs if m.startswith("Không lấy được")]
            ui.notify("Đã lấy số backlink mới" + (f" ({len(bad)} danh sách lỗi)" if bad else ""),
                      caption=" · ".join(bad)[:300] or None, type="warning" if bad else "positive",
                      position="bottom-right", classes="sr-toast", multi_line=True)
        except Exception as e:  # noqa: BLE001
            PT.give_back(_pt)
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
            ui.label("Tool tự lấy theo lịch. Bấm \"Lấy số mới\" để lấy ngay.").classes("text-xs muted")
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
                est.text = ("Không tự lấy: chỉ lấy khi bấm “Lấy số mới”." if s_["paused"] else
                            "Lấy tự động theo lịch, tính vào ngân sách dự án (không trừ credit của bạn)."
                            if PT.member(user) else
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
            from . import site_labels as SL
            try:
                with SL.connect() as c:
                    labels = SL.all_labels(c)
            except Exception:  # noqa: BLE001
                labels = {}
            with connect() as c:
                ld_ = BLL.latest(c, site)
                return BX.build(BL.lists(c, site), BL.latest(c, site), brand_terms_of(own_brand(c)), site, which,
                                client=cl, links=ld_, labels=labels,
                                sources=sources_info(c, ld_) if which == "all" and not cl else None)
        return build

    def sources_info(c, ld_) -> dict:
        """Phần Nguồn dữ liệu của file xuất: trạng thái DataForSEO, file Semrush đã nhập, thay đổi giữa hai lần nhập."""
        from . import backlink_agg as AG
        from . import semrush as SR
        now = (BL.latest(c, site) or {}).get("now") or {}
        dfs_items = [x for x in ((ld_ or {}).get("items") or []) if "dfs" in (x.get("src") or ["dfs"])]
        own_ = SR.host(site)
        nm = SR.names(c, site)
        out = {"dfs": {"Lần lấy gần nhất": now.get("day") or "chưa lấy",
                       "Số tổng": f"{now.get('backlinks')} backlink · {now.get('referring_domains')} website" if now
                       else "", "Danh sách link": f"{len(dfs_items)} link · {len({x['d_from'] for x in dfs_items})} website"},
               "imports": [], "changes": []}
        for o in SR.owners(c, site):
            who = own_ if o["owner"] == own_ else f"Đối thủ {nm.get(o['owner'], o['owner'])}"
            out["imports"].append({"who": who, "kind": SR.KINDS[o["kind"]], "count": o["count"] or 0,
                                   "at": (o["imported_at"] or "")[:10]})
            d = SR.latest(c, site, o["owner"], o["kind"])
            ch = AG.import_changes(d["items"], d["prev_items"], "domain" if o["kind"] == "refdomains" else "d_from")
            if ch:
                out["changes"].append((f"{SR.KINDS[o['kind']]} của {who}", ch))
        return out

    def export_btn(which: str, name: str, label: str, icon_only: bool = True) -> None:
        from .web_export import export_menu
        host = (urlparse(site).netloc or site.split(":")[-1]).replace("www.", "")
        export_menu(ui, cfg, connect, f"backlink-{name}_{host}_{date.today():%Y-%m-%d}", make_xlsx(which),
                    label=label, user=user, icon_only=icon_only, category="backlink")

    with right, ui.row().classes("items-center gap-2 justify-end"):
        export_btn("all", "bao-cao", "Xuất báo cáo", icon_only=False)
    if ed and not cfg.rank.paused:
        with right, ui.row().classes("items-center gap-2 justify-end"):
            ui.button("Nhập dữ liệu", icon="upload_file",
                      on_click=lambda: WBL.import_dialog(ui, cfg, user, body.refresh)).props(
                "outline no-caps color=grey-9").tooltip("Nhập file Backlinks / Referring Domains xuất từ Semrush "
                                                        "(website mình và đối thủ), miễn phí")
            ui.button("Lịch lấy", icon="event_repeat", on_click=schedule_dialog).props(
                "outline no-caps color=grey-9").tooltip("Đặt chu kỳ tự lấy, tạm ngưng, chọn danh sách lấy kèm")
            b = ui.button("Lấy số mới", icon="refresh").props("unelevated no-caps color=primary")
            b.on_click(lambda _, b=b: fetch(b))
            b.tooltip(f"Lấy ngay số tổng + các danh sách đã chọn · {PT.cost('backlink')} credit" if PT.member(user)
                      else "Lấy ngay số backlink mới (tốn phí dữ liệu)")

    page_tabs = [t for t in PAGE_TABS if not (cl and t[0] in TEAM_TABS)]  # khách hàng: không thấy tab việc của team
    keys = [k for k, _ in page_tabs]
    list_keys = [k for k, _ in LIST_VIEWS]
    start, view = OLD_TABS.get(start, (start, view))
    in_list = start in list_keys  # link cũ tới một danh sách: mở tab Danh sách, chọn sẵn cách xem đó
    state = {"list": start if in_list else "links",
             "tab": "list" if in_list else (start if start in keys else "overview"),
             "q": {k: "" for k in BL.LIST_KINDS},
             "f": {k: None for k in BL.LIST_KINDS},  # f: mục kiểm tra đang dùng làm bộ lọc của từng tab
             "view": {t: (view if start == t and view in vs else "all") for t, vs in VIEWS.items()},
             "redraw": {}}
    if cl:
        state["view"]["pages"] = "all"  # Trang cần link: việc của team

    from . import web_backlink_build as WBB

    def set_url(tab: str) -> None:
        key = state["list"] if tab == "list" else tab  # địa chỉ giữ tên danh sách cũ để link đã chia sẻ vẫn mở đúng
        v = state["view"].get(key, "all")
        q = "" if key == "overview" else f"?tab={key}" + ("" if v == "all" else f"&xem={v}")
        ui.run_javascript(f"history.replaceState(null, '', '/backlink{q}')")

    @ui.refreshable
    def body():
        with connect() as c:
            bl = BL.latest(c, site)
            ls = BL.lists(c, site)
            st, due = BL.settings(c, site), BL.next_due(c, site)
            own = own_brand(c)
            ld = BLL.latest(c, site)
        state["ld"] = ld
        if not bl and not ls and not ld:
            T.empty_state(ui, "add_link", "Chưa lấy số backlink lần nào",
                          (f"Bấm “Lấy số mới” để lấy số tổng, lịch sử 12 tháng và 4 danh sách ({PT.cost('backlink')} "
                           "credit)." if PT.member(user) else
                           "Bấm “Lấy số mới” để lấy số tổng, lịch sử 12 tháng và 4 danh sách (khoảng 0,15 USD lần "
                           "đầu).") if ed else "Số backlink sẽ có sau lần lấy đầu tiên.")
            if not cl:  # ghi link đã xây không cần số DataForSEO
                WBB.built_panel(ui, cfg, connect, user)
            return
        status_line(bl, st, due)
        checks = AU.audit(ls, brand_terms_of(own)) if ls and not cl else []
        lchecks = []
        if ld and not cl:
            from . import link_audit as LA
            from . import site_labels as SL
            try:
                with SL.connect() as c:
                    labels_ = SL.all_labels(c)
            except Exception:  # noqa: BLE001
                labels_ = {}
            lchecks = LA.audit(ld["items"], ld["prev"]["items"] if ld.get("prev") else None, brand_terms_of(own),
                               labels_)
        by_tab = {k: [c_ for c_ in checks if CHECK_TAB.get(c_["key"]) == k] for k in BL.LIST_KINDS}
        by_tab["links"] = lchecks
        audit_checks = audit_list(ld, ls, checks, lchecks, brand_terms_of(own)) if not cl else []
        badge_of = {"audit": audit_checks}
        from types import SimpleNamespace

        from . import ai_settings as AIS
        from . import backlink_agg as AG_
        from . import web_ai_backlink as WAB
        actx = SimpleNamespace(cfg=cfg, connect=connect, user=user, site=site, ld=ld, bl=bl, ls=ls,
                               checks=audit_checks, brand_terms=brand_terms_of(own), refresh=body.refresh)
        ai_on = (lambda task: not cl and AIS.enabled(site, task))

        def ai_btn(label_: str, tip: str, fn) -> None:
            ui.button(label_, icon="auto_awesome", on_click=fn).props(
                "unelevated no-caps dense color=deep-purple-1 text-color=deep-purple-9").classes(
                "sr-kg-aibtn").tooltip(tip)
        items_all = (ld or {}).get("items") or []
        kits = state.setdefault("kits", {k: TK.new_state() for k in ("domains", "pages", "anchors")})

        def open_links(kind: str, key: str) -> None:
            if kind == "domain":
                sel_, title_ = BLL.for_site(items_all, key), f"Link từ {key}"
            elif kind == "anchor":
                sel_, title_ = BLL.for_anchor(items_all, key), f"Link dùng anchor “{key or '(trống)'}”"
            else:
                sel_, title_ = BLL.for_page(items_all, key), f"Link trỏ về {_path(key)}"
            WBL.dialog(ui, user, title_, f"{len(sel_)} link" + ("" if cl else " · DataForSEO + file Semrush"), sel_, on_label=body.refresh)

        n_dom = len({x["d_from"] for x in items_all})

        def label(k: str, name: str) -> str:
            """Nhãn một cách xem trong tab Danh sách: luôn kèm số dòng để so được với các cách xem khác."""
            if items_all:
                n_ = {"links": len(items_all), "domains": n_dom,
                      "pages": len(AG_.pages(items_all)),
                      "anchors": len(AG_.anchors(items_all, brand_terms_of(own)))}.get(k)
                return name + (f" · {F.n(n_)}" if n_ is not None else "")
            d_ = ls.get(k)
            return name + (f" · {F.n(d_['total'] or len(d_['items']))}" if d_ else "")

        def view_toggle(tab: str, options: dict) -> None:
            def change(e):
                state["view"][tab] = e.value
                set_url(tab)
                state["redraw"][tab].refresh()
            ui.toggle(options, value=state["view"][tab], on_change=change).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg q-mb-sm")

        @ui.refreshable
        def pages_tab() -> None:
            if not cl:
                view_toggle("pages", {"all": label("pages", "Tất cả trang"), "need": "Cần thêm link"})
            if state["view"]["pages"] == "need" and not cl:
                WBB.needs_panel(ui, cfg, connect, ls,
                                on_plan=(lambda rows: WAB.plan_dialog(ui, actx, rows) if rows else None)
                                if ai_on("backlink_plan") else None)
            elif items_all:
                WV2.pages_panel(ui, user, items_all, kits["pages"], open_links)
            else:
                list_panel("pages", ls, own, [])

        @ui.refreshable
        def domains_tab() -> None:
            ch = (ls.get("changes") or {}).get("items") or []
            n_new = sum(1 for x in ch if not x["lost"])
            view_toggle("domains", {"all": label("domains", "Tất cả website"),
                                    "moi": f"Mới {BL.CHANGE_DAYS} ngày · {F.n(n_new)}",
                                    "mat": f"Mất {BL.CHANGE_DAYS} ngày · {F.n(len(ch) - n_new)}"})
            v = state["view"]["domains"]
            if v == "all" and items_all:
                WV2.domains_panel(ui, user, items_all, kits["domains"], body.refresh, open_links)
            elif v == "all":
                list_panel("domains", ls, own, [])
            else:
                list_panel("changes", ls, own, [], only_lost=v == "mat")
        @ui.refreshable
        def list_tab() -> None:
            """Tab Danh sách: bốn cách xem cùng một kho link (link / website / trang đích / anchor)."""
            def pick_view(e) -> None:
                state["list"] = e.value
                set_url("list")
                list_tab.refresh()
            ui.toggle({k: label(k, n) for k, n in LIST_VIEWS}, value=state["list"], on_change=pick_view).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg sr-seg-main q-mb-sm")
            v = state["list"]
            if v == "links":
                WBL.panel(ui, cfg, user, ld, [], state, body.refresh,
                          export=lambda: export_btn("links", "tat-ca-backlink",
                                                    "Xuất tất cả backlink kèm audit (mỗi mục một sheet)"))
            elif v == "domains":
                domains_tab()
            elif v == "pages":
                pages_tab()
            elif items_all:
                WV2.anchors_panel(ui, items_all, brand_terms_of(own), kits["anchors"], open_links, client=cl)
            else:
                list_panel("anchors", ls, own, [])
        state["redraw"] = {"pages": pages_tab, "domains": domains_tab, "list": list_tab}
        with ui.tabs(value=state["tab"], on_change=lambda e: pick(e.value)).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs sr-bl-tabs") as tabs:
            for k, name in page_tabs:
                with ui.tab(k, name):
                    high = sum(1 for c_ in badge_of.get(k, []) if c_["level"] == "high")  # chỉ tab Audit
                    if high:  # chấm đỏ: tab có việc cần xử lý
                        T.count_badge(ui, high, f"{high} việc cần xử lý trong tab này").classes("sr-tab-badge")
        state["tabs"] = tabs
        with ui.tab_panels(tabs, value=state["tab"]).classes("w-full").props("animated=false"):
            with ui.tab_panel("overview").classes("q-px-none"):
                kpis(bl, ls, ld)
                if not cl:
                    WAB.profile_box(ui, actx)
                if not cl:  # khách hàng: không bảng so nguồn dữ liệu, không việc cần làm của team
                    WV2.overview(ui, ld, bl, audit_checks, open_check,
                                 on_import=(lambda: WBL.import_dialog(ui, cfg, user, body.refresh)) if ed else None)
                trend(bl)
            with ui.tab_panel("audit").classes("q-px-none"):
                if cl:
                    ui.label("Audit là việc của team.").classes("text-sm muted")
                else:
                    if ai_on("backlink_classify") or ai_on("backlink_disavow"):
                        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
                            ui.label("AI hỗ trợ:").classes("text-xs muted")
                            if ai_on("backlink_classify") and items_all:
                                ai_btn("AI phân loại website", "AI gợi ý nhãn cho website trỏ về chưa gắn nhãn",
                                       lambda: WAB.classify_dialog(ui, actx))
                            if ai_on("backlink_disavow") and items_all:
                                ai_btn("AI duyệt disavow", "AI xem website nghi spam: nên disavow, giữ hay xem tay",
                                       lambda: WAB.disavow_dialog(ui, actx))
                    WBL.panel(ui, cfg, user, ld, audit_checks, state, body.refresh, mode="audit")
            with ui.tab_panel("list").classes("q-px-none"):
                list_tab()
            if not cl:
                with ui.tab_panel("built").classes("q-px-none"):
                    WBB.built_panel(ui, cfg, connect, user)
                with ui.tab_panel("gap").classes("q-px-none"):
                    if ai_on("backlink_rivals"):  # cùng kiểu với hàng AI ở tab Audit
                        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
                            ui.label("AI hỗ trợ:").classes("text-xs muted")
                            ai_btn("AI chiến lược đối thủ", "AI đọc Backlink GAP + nhãn website: đối thủ dựa vào loại "
                                   "link nào, website mình nên làm gì", lambda: WAB.rivals_dialog(ui, actx))
                    WBB.gap_panel(ui, cfg, connect, user)
            with ui.tab_panel("sources").classes("q-px-none"):
                WV2.sources(ui, cfg, user, connect, ld, bl, st if not cl else None, due, body.refresh, None)

    def audit_list(ld, ls, checks, lchecks, brand_terms) -> list[dict]:
        """Mọi mục kiểm tra cho tab Audit (dùng chung với file xuất: backlink_agg.full_audit)."""
        from . import backlink_agg as AG
        from . import site_labels as SL
        try:
            with SL.connect() as c:
                labels_ = SL.all_labels(c)
        except Exception:  # noqa: BLE001
            labels_ = {}
        return AG.full_audit(ld, ls, brand_terms, labels_)

    def pick(v: str) -> None:
        state["tab"] = v
        set_url(v)

    def status_line(bl, st, due) -> None:
        now, prev = (bl or {}).get("now"), (bl or {}).get("prev")
        with ui.row().classes("items-center gap-2 q-mb-xs"):
            if now:
                ui.label(f"Lấy ngày {date.fromisoformat(now['day']):%d/%m/%Y}"
                         + (f" · so với lần lấy {date.fromisoformat(prev['day']):%d/%m}" if prev else "")).classes(
                    "text-xs muted")
            if cl:
                return
            if cfg.rank.paused:
                T.status_chip(ui, "Website đang tạm ngưng mọi chi phí DataForSEO", "grey", "pause_circle")
            elif st["paused"]:
                T.status_chip(ui, "Tạm ngưng tự lấy", "grey", "pause_circle")
            else:
                T.status_chip(ui, f"{BL.EVERY_CHOICES[st['every_days']]} · lần tới {due:%d/%m}"
                              + ("" if PT.member(user) else
                                 " · ~" + f"{BL.monthly_estimate(st):.2f} USD/tháng".replace(".", ",")),
                              "green", "event_repeat")

    def kpis(bl, ls, ld=None) -> None:
        from . import backlink_agg as AG
        now, prev = (bl or {}).get("now"), (bl or {}).get("prev")
        if not now:
            return
        sm = AG.summary((ld or {}).get("items") or [])
        merged = sm["semrush"]["links"] > 0  # có file Semrush: số website / backlink theo dữ liệu gộp

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
            if merged and cl:  # khách hàng: số gộp, không tách nguồn dữ liệu
                T.kpi(ui, "language", "Website trỏ về", F.n(sm["all"]["domains"]), tone="green",
                      info=("Số website (tên miền) khác nhau đang có ít nhất một link về site.",))
            elif merged:
                T.kpi(ui, "language", "Website trỏ về · gộp", F.n(sm["all"]["domains"]), tone="green",
                      info=("Số website khác nhau đang link về site, gộp DataForSEO và file Semrush (bỏ trùng).",
                            "Số dưới thẻ đếm từ danh sách link của từng nguồn nên khớp bảng Số liệu theo nguồn; "
                            f"riêng DataForSEO còn báo số tổng {F.n(now['referring_domains'] or 0)} website"
                            + (f" ({d} so với lần lấy trước)" if d else "") + ".",
                            "Chi tiết từng nguồn: bảng Số liệu theo nguồn bên dưới, tab Nguồn dữ liệu."),
                      hint=f"DataForSEO {F.n(sm['dfs']['domains'])} · Semrush {F.n(sm['semrush']['domains'])}"
                      + " · đếm từ danh sách link")
            else:
                T.kpi(ui, "language", "Website trỏ về", F.n(now["referring_domains"] or 0), delta=d, good=g,
                      tone="green",
                      info=("Số website (tên miền) khác nhau đang có ít nhất một link về site.",
                            "Chỉ số quan trọng nhất: nhiều website khác nhau link về có giá trị hơn nhiều link từ một "
                            "website."),
                      hint="" if cl else f"{F.n(now['referring_domains_nofollow'] or 0)} website chỉ có link nofollow")
            d, g, _ = delta("backlinks")
            ch = (ls.get("changes") or {}).get("items")
            moves = (f"+{sum(1 for x in ch if not x['lost'])} / −{sum(1 for x in ch if x['lost'])} trong "
                     f"{BL.CHANGE_DAYS} ngày" + ("" if cl else " (DataForSEO)")) if ch is not None else ""
            card = T.kpi(ui, "link", "Backlink · gộp" if merged and not cl else "Backlink",
                         F.n(sm["all"]["links"]) if merged else F.n(now["backlinks"] or 0),
                         delta="" if merged else d, good=None if merged else g, tone="blue",
                         info=("Tổng số link đang trỏ về site (một website có thể link nhiều lần).",
                               "Bấm để xem link mới / mất 30 ngày."),
                         hint=moves)
            if ch is not None:
                card.classes("clickable").on("click", lambda: go("changes"))
            d, g, _ = delta("rank")
            T.kpi(ui, "military_tech", "Uy tín" if cl else "Uy tín (DataForSEO)",
                  f"{now['rank'] if now['rank'] is not None else '–'}/1000", delta=d,
                  good=g, tone="lime",
                  info=("Điểm uy tín của website (0–1000), tính từ số và chất lượng link trỏ về.",) if cl else
                  ("Điểm uy tín của website theo DataForSEO (0–1000), tính từ số và chất lượng link trỏ về.",))
            d, g, _ = delta("spam_score", good_up=False)
            spam = now["spam_score"]
            if not cl:  # điểm spam: số kiểm soát nội bộ, không đưa cho khách
                T.kpi(ui, "gpp_maybe", "Điểm spam (DataForSEO)", f"{spam if spam is not None else '–'}/100", delta=d,
                      good=g,
                      tone="red" if (spam or 0) >= 30 else "grey",
                      info=("Điểm spam trung bình của các backlink (0–100). Càng thấp càng tốt.",
                            "Từ 30 trở lên nên xem lại các website link về có dấu hiệu spam."),
                      hint=f"{F.n(now['broken_backlinks'] or 0)} link trỏ về trang không còn (link gãy)")

    def open_check(tab: str, key: str) -> None:
        """Sang tab chứa mục kiểm tra và bật bộ lọc của mục đó."""
        go(tab, key)
        f = state.get("setf", {}).get(tab)
        if f:
            f(key, toggle=False)

    def go(tab: str, key: str = "") -> None:
        """Mở tab; danh sách đã gộp vào tab khác (Link mới / mất) thì mở tab đó với bộ lọc tương ứng."""
        if tab == "changes":
            tab, v = "domains", ("mat" if key == "lost" else "moi")
        else:
            v = "all" if tab in VIEWS else None
        if v and state["view"].get(tab) != v:
            state["view"][tab] = v
            if tab in state["redraw"]:
                state["redraw"][tab].refresh()
        if tab in [k for k, _ in LIST_VIEWS]:  # bốn danh sách nằm chung tab "Danh sách"
            state["list"] = tab
            tab = "list"
            if "list" in state["redraw"]:
                state["redraw"]["list"].refresh()
        state["tab"] = tab
        set_url(tab)
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
                    row.on("click", lambda _, t=("links" if c["key"].startswith("L_") else
                                                 CHECK_TAB.get(c["key"], "overview")), k=c["key"]: open_check(t, k))
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

    def kit_filters(kind: str) -> list[tuple]:
        """Bộ lọc của từng bảng (điểm spam: chỉ team thấy)."""
        spam = [] if cl else [("num", "Điểm spam", "spam")]
        tech = (lambda *f: [] if cl else list(f))  # dofollow / nofollow: chỉ team thấy
        return {
            "domains": [("text", "Website", ["domain"]), ("num", "Uy tín", "rank"), ("num", "Backlink", "backlinks"),
                        *tech(("num", "Trang dofollow", "dofollow_n")), *spam, *tech(("enum", "Loại link", "df")),
                        ("date", "Thấy lần đầu", "first_iso")],
            "changes": [("text", "Trang link về / anchor / trang đích", ["source", "title", "anchor", "target"]),
                        *spam, *tech(("enum", "Loại link", "follow")), ("date", "Ngày", "first_iso")],
            "anchors": [("text", "Anchor", ["anchor"]), ("num", "Website dùng", "domains"),
                        ("num", "Backlink", "backlinks"), ("enum", "Loại anchor", "type"),
                        ("date", "Thấy lần đầu", "first_iso")],
            "pages": [("text", "Trang / tiêu đề", ["page", "title"]), ("num", "Website trỏ về", "domains"),
                      ("num", "Backlink", "backlinks"), ("num", "Uy tín", "rank"),
                      *tech(("enum", "Tình trạng trang", "state"))],
        }[kind]

    def kit_copy(kind: str) -> list[tuple[str, str]]:
        spam = [] if cl else [("Điểm spam", "spam")]
        return {
            "domains": [("Website", "domain"), ("Uy tín", "rank"), ("Backlink", "backlinks"),
                        *([] if cl else [("Trang dofollow", "dofollow_n")]), ("Số trang", "pages_n"),
                        ("Thấy lần đầu", "first_iso"), *spam],
            "changes": [("Trạng thái", "status"), ("Trang link về", "href"), ("Tiêu đề trang link về", "title"),
                        ("Anchor", "anchor"), ("Trang đích", "to_url"), *([] if cl else [("Loại", "follow")]),
                        ("Ngày", "first_iso"), *spam],
            "anchors": [("Anchor", "anchor"), ("Loại", "type"), ("Website dùng", "domains"), ("Tỷ lệ", "share"),
                        ("Backlink", "backlinks"), ("Thấy lần đầu", "first_iso")],
            "pages": [("Trang", "href"), ("Tiêu đề", "title"), ("Website trỏ về", "domains"), ("Backlink", "backlinks"),
                      ("Uy tín", "rank"), ("Tình trạng", "state")],
        }[kind]

    def list_panel(kind: str, ls: dict, own: dict | None, checks: list[dict], only_lost: bool | None = None) -> None:
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
                T.scroll_to(ui, anchor_id)

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
                    # Công cụ disavow của Google, mở sẵn đúng property Search Console của dự án
                    disavow_url = ("https://search.google.com/search-console/disavow-links?resource_id="
                                   + quote(site, safe=""))
                    with ui.row().classes("items-center gap-2 q-mt-sm"):
                        ui.button("Tải file disavow (.txt)", icon="download", on_click=download).props(
                            "outline no-caps dense color=grey-9").tooltip(
                            "Tải file để báo Google bỏ qua link spam. Xem lại trước khi nộp.")
                        ui.button("Mở trang disavow của Google", icon="open_in_new",
                                  on_click=lambda: ui.navigate.to(disavow_url, new_tab=True)).props(
                            "outline no-caps dense color=grey-9").tooltip(
                            "Mở công cụ Disavow của Google để nộp file")
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
                if kind == "changes" and only_lost is not None:  # bộ lọc Mới / Mất của tab Website trỏ về
                    items = [x for x in items if bool(x["lost"]) == only_lost]
                fkey = state["f"][kind]
                if fkey:  # lọc theo mục kiểm tra đang chọn
                    items = [x for x in items if AU.matches(fkey, x, brand_terms)]
                q = _fold(state["q"][kind])
                shown_n = len(items)
                cut = kind == "changes" and only_lost is not None  # đang lọc Mới / Mất: không so với tổng
                note = (f"Lấy lúc {_vn(data['fetched_at'][:10])} · hiện {shown_n}"
                        + (f" / {F.n(data['total'])}" if not cut and data.get("total") and data["total"] > shown_n
                           else "") + " dòng")
                if kind == "domains":
                    cols = [("domain", "Website", "left"), ("rank", "Uy tín", "right"),
                            ("backlinks", "Backlink", "right"), ("dofollow", "Trang dofollow", "right"),
                            ("first_seen", "Thấy lần đầu", "left")] + ([] if cl else [("spam", "Spam", "right")])
                    rows = [{"k": x["domain"], "domain": x["domain"], "rank": x["rank"], "backlinks": x["backlinks"],
                             "dofollow": f"{x['dofollow_pages']}/{x['pages']}", "first_seen": _vn(x["first_seen"]),
                             "first_iso": x["first_seen"], "spam": x["spam"], "href": f"https://{x['domain']}",
                             "dofollow_n": x["dofollow_pages"], "pages_n": x["pages"],
                             "df": "Có trang dofollow" if x["dofollow_pages"] else "Chỉ nofollow"} for x in items]
                    note += " · xếp theo uy tín"
                elif kind == "changes":
                    new_n = sum(1 for x in items if not x["lost"])
                    spam_n = sum(1 for x in items if (x.get("spam") or 0) >= SPAM_FLAG)
                    note += (f" · link {'mất' if only_lost else 'mới'} trong {BL.CHANGE_DAYS} ngày" if cut else
                             f" · {new_n} link mới, {len(items) - new_n} link mất trong {BL.CHANGE_DAYS} ngày") + (
                        f" · {spam_n} link có điểm spam ≥ {SPAM_FLAG}" if spam_n and not cl else "")
                    cols = [("status", "", "left"), ("source", "Trang link về", "left"), ("anchor", "Anchor", "left"),
                            ("target", "Trang đích", "left"), ("follow", "Loại", "left"),
                            ("when", "Ngày", "left")]
                    rows = [{"k": f"{x['url_from']}|{x['url_to']}|{x['lost']}", "to_url": x["url_to"],
                             "status": "Mất" if x["lost"] else "Mới", "lost": x["lost"],
                             "source": x["domain_from"], "title": x.get("title") or "", "href": x["url_from"],
                             "anchor": x["anchor"] or ("(ảnh)" if x.get("type") == "image" else "(trống)"),
                             "target": _path(x["url_to"]), "follow": "dofollow" if x["dofollow"] else "nofollow",
                             "spam": x.get("spam"), "spammy": (x.get("spam") or 0) >= SPAM_FLAG and not cl,
                             "when": _vn(x["last_seen"] if x["lost"] else x["first_seen"]),
                             "first_iso": x["last_seen"] if x["lost"] else x["first_seen"]} for x in items]
                elif kind == "anchors":
                    tot = sum(x["domains"] or 0 for x in items) or 1
                    counts: dict[str, int] = {}
                    rows = []
                    for x in items:
                        t = anchor_type(x["anchor"], brand_terms)
                        counts[t] = counts.get(t, 0) + (x["domains"] or 0)
                        rows.append({"k": x["anchor"] or "", "anchor": x["anchor"] or "(trống / ảnh)",
                                     "type": ANCHOR_TYPES[t][0],
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
                    rows = [{"k": x["page"], "page": _path(x["page"]), "title": x.get("title") or "",
                             "href": x["page"], "domains": x["domains"], "backlinks": x["backlinks"], "rank": x["rank"],
                             "gone": (x.get("status") or 200) >= 400 and not cl,
                             "state": "Trang lỗi" if (x.get("status") or 200) >= 400 else (
                                 "Chuyển hướng" if 300 <= (x.get("status") or 200) < 400 else "Bình thường")}
                            for x in items]
                    note += " · xếp theo số website trỏ về"
                if cl:  # khách hàng: không cột dofollow / nofollow
                    cols = [c_ for c_ in cols if c_[0] not in ("dofollow", "follow")]
                if kind in ("domains", "changes") and not cl:  # nhãn website (dùng chung mọi dự án): việc của team
                    WL.enrich(rows, "domain" if kind == "domains" else "source", user)
                    cols.insert(1, ("labels", "Nhãn", "left"))
                if q:
                    rows = [r for r in rows if q in _fold(" ".join(str(v) for v in r.values()))]
                flex = {"domains": "domain", "changes": "source", "anchors": "anchor", "pages": "page"}[kind]
                columns = [{"name": n, "label": lab, "field": "labels_t" if n == "labels" else n, "align": al,
                            "sortable": bool(lab), "width": None if n == flex else (150 if n == "labels" else
                                                                                   COL_W.get(n, 120))}
                           for n, lab, al in cols]
                for c_ in columns:
                    if c_["name"] in ("first_seen", "when"):
                        c_[":sort"] = "(a, b, rowA, rowB) => (rowA.first_iso || '').localeCompare(rowB.first_iso || '')"
                note_box.clear()
                with note_box:
                    if fkey and fkey in by_key:
                        T.filter_chip(ui, f"Đang lọc: {by_key[fkey]['title']} · {len(items)} dòng",
                                      lambda: set_filter(fkey))
                    ui.label(note).classes("text-xs muted")
                kit = state.setdefault("kit", {}).setdefault(kind, TK.new_state())
                lab_kind = kind in ("domains", "changes") and not cl
                ld_ = state.get("ld")
                drill = ld_ is not None and kind in ("domains", "anchors", "pages")
                if drill:
                    columns.append({"name": "drill", "label": "Link", "field": "k", "align": "left", "width": 96,
                                    "sortable": False})

                def open_links(e, kind=kind):
                    k_ = e.args
                    its = ld_["items"]
                    if kind == "domains":
                        sel_, title_ = BLL.for_site(its, k_), f"Link từ {k_}"
                    elif kind == "anchors":
                        sel_, title_ = BLL.for_anchor(its, k_), f"Link dùng anchor “{k_ or '(trống)'}”"
                    else:
                        sel_, title_ = BLL.for_page(its, k_), f"Link trỏ về {_path(k_)}"
                    WBL.dialog(ui, user, title_, f"{len(sel_)} link · lấy lúc {_vn(ld_['fetched_at'][:10])}", sel_,
                               on_label=body.refresh)
                TK.table(ui, columns=columns, rows=rows, row_key="k", st=kit,
                         filters=kit_filters(kind) + ([WL.FILTER] if lab_kind else []),
                         copy=kit_copy(kind)[:1] + ([WL.COPY] if lab_kind else []) + kit_copy(kind)[1:],
                         actions=WL.action(ui, user, "domain" if kind == "domains" else "source", table.refresh)
                         if lab_kind else None,
                         noun=KIT_NOUN[kind], classes="sr-bl-table",
                         events={**({"drill": open_links} if drill else {}),
                                 **WL.events(ui, user, table.refresh)}, slots={
                    "body-cell-labels": WL.SLOT,
                    "body-cell-drill": """
                    <q-td :props="props" style="overflow:visible"><q-btn flat dense no-caps size="sm" color="primary"
                      label="Xem link" class="q-px-xs" @click.stop="$parent.$emit('drill', props.row.k)"/></q-td>""",
                    "body-cell-domain": """
                    <q-td :props="props"><a :href="props.row.href" target="_blank" rel="noopener"
                       class="sr-bl-link">{{ props.value }}</a></q-td>""",
                    "body-cell-source": """
                    <q-td :props="props"><div class="sr-bl-src">
                      <a :href="props.row.href" target="_blank" rel="noopener" class="sr-bl-link" :title="props.row.href">{{ props.value }}</a>
                      <div v-if="props.row.title" class="sr-bl-sub ellipsis">{{ props.row.title }}</div></div>
                    </q-td>""",
                    "body-cell-anchor": """
                    <q-td :props="props"><div class="sr-bl-anchor" :title="props.value">{{ props.value }}</div>
                    </q-td>""",
                    "body-cell-target": """
                    <q-td :props="props"><div class="sr-bl-anchor" :title="props.value">{{ props.value }}</div>
                    </q-td>""",
                    "body-cell-follow": """
                    <q-td :props="props"><span class="text-xs">{{ props.value }}</span>
                      <span v-if="props.row.spammy" class="sr-bl-type k-lost q-ml-xs">spam {{ props.row.spam }}
                        <q-tooltip>Điểm spam (0–100): trang nguồn có dấu hiệu bán / spam link</q-tooltip></span></q-td>""",
                    "body-cell-status": """
                    <q-td :props="props"><span class="sr-bl-type" :class="props.row.lost ? 'k-lost' : 'k-new'">
                      {{ props.value }}</span></q-td>""",
                    "body-cell-type": """
                    <q-td :props="props"><span class="sr-bl-type" :class="props.row.tcls">{{ props.value }}</span>
                    </q-td>""",
                    "body-cell-page": """
                    <q-td :props="props"><div class="sr-bl-src">
                      <a :href="props.row.href" target="_blank" rel="noopener" class="sr-bl-link" :title="props.row.href">{{ props.value }}</a>
                      <span v-if="props.row.gone" class="sr-bl-type k-lost q-ml-xs">trang lỗi</span>
                      <div v-if="props.row.title" class="sr-bl-sub ellipsis">{{ props.row.title }}</div></div>
                    </q-td>""",
                })
            table()

    body()
