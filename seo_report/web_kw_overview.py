"""Tab Tổng quan từ khóa của mục Research từ khóa (/tu-khoa?kw=…): giống Keyword Overview của Semrush, số từ Google Ads API (miễn
phí) + Search Console + lần check hạng gần nhất. Gõ từ khóa ở ô trên cùng, chọn từ khóa đã xem gần đây, hoặc bấm vào
từ khóa ở trang Research."""
from datetime import datetime
from urllib.parse import quote

from . import access as A
from . import keyword_overview as KO
from . import keyword_research as KR
from . import ui_theme as T

INTENT = {"I": ("Thông tin", "i-I"), "N": ("Điều hướng", "i-N"), "C": ("Cân nhắc mua", "i-C"),
          "T": ("Mua / giao dịch", "i-T")}
COMP = {"LOW": "Thấp", "MEDIUM": "Vừa", "HIGH": "Cao"}
MONTHS = "Th1 Th2 Th3 Th4 Th5 Th6 Th7 Th8 Th9 Th10 Th11 Th12".split()


def _n(v) -> str:
    return "n/a" if v is None else f"{v:,.0f}".replace(",", ".")


def build_overview_page(ui, cfg, connect, user, kw: str = "") -> None:
    from nicegui import background_tasks, run
    ed = A.can_edit(user)
    site = cfg.site_url
    state = {"kw": " ".join((kw or "").split()), "data": None, "err": "", "loading": bool(kw)}

    def go(text: str) -> None:
        text = " ".join((text or "").split())
        if text:
            ui.navigate.to(f"/tu-khoa?kw={quote(text)}")

    # Tiêu đề theo từ khóa (như Keyword Overview của Semrush), rồi thanh tìm một dòng, rồi các thẻ số
    @ui.refreshable
    def head() -> None:
        d = state["data"] if not state["loading"] and not state["err"] else None
        with ui.row().classes("w-full items-end gap-2 no-wrap"):
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.html('<h1 class="sr-title" style="margin:0">Tổng quan từ khóa'
                        + (f': <span class="soft">{_esc(state["kw"])}</span>' if state["kw"] else "") + "</h1>")
                if d:
                    at = datetime.fromisoformat(d["at"]).astimezone()
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        T.flag(ui)
                        ui.label(f"{d['currency']} · số Google Ads lấy lúc {at:%H:%M %d/%m/%Y} (lưu 7 ngày)").classes(
                            "text-sm muted")
                else:
                    ui.label("Phân tích một từ khóa: volume Việt Nam và thế giới, xu hướng 12 tháng, CPC, mục đích, "
                             "biến thể, câu hỏi, nhóm chủ đề và trang kết quả Google. Số từ Google Ads (miễn phí)."
                             ).classes("text-sm muted")
            if d:
                from .web_export import export_menu
                if ed:
                    ui.button(icon="refresh", on_click=lambda: load(True)).props(
                        'flat round dense aria-label="Lấy số mới từ Google Ads"').tooltip("Lấy số mới từ Google Ads")
                export_menu(ui, cfg, connect, f"tong-quan-tu-khoa_{_slug(d['keyword'])}", make_xlsx, user=user,
                            category="research")

    with ui.column().classes("w-full gap-1 q-mb-md"):
        head()
    with ui.element("div").classes("sr-card q-pa-md w-full q-mb-md"):
        with ui.row().classes("w-full items-center no-wrap gap-2 sr-kr-search"):
            with ui.element("div").classes("sr-ko-db"):
                T.flag(ui, "Số liệu Google Ads cho Việt Nam, tiếng Việt")
            box = ui.input(placeholder="Nhập một từ khóa, ví dụ: gọng kính mắt mèo", value=state["kw"]).props(
                "outlined dense clearable").classes("col").props('aria-label="Từ khóa cần phân tích"')
            box.on("keydown.enter", lambda: go(box.value))
            ui.button("Phân tích", icon="search", on_click=lambda: go(box.value)).props("unelevated no-caps")
            hist = ui.button("Lịch sử", icon="history").props("flat no-caps")
            with hist, ui.menu().classes("sr-kr-fmenu"):
                with ui.column().classes("q-pa-sm gap-0").style("width: 340px; max-height: 420px; overflow-y: auto"):
                    ui.label("Từ khóa đã phân tích gần đây").classes("text-sm font-semibold q-mb-xs")
                    with connect() as c:
                        recent_ = KO.recent(c, 30)
                    if not recent_:
                        ui.label("Chưa có.").classes("text-sm muted")
                    for r in recent_:
                        with ui.row().classes("w-full items-center no-wrap gap-2 sr-kr-hrow cursor-pointer") as row_:
                            ui.label(r["keyword"]).classes("text-sm col ellipsis")
                            ui.label(_n(r["volume"])).classes("text-xs muted num")
                        row_.on("click", lambda k=r["keyword"]: go(k))


    @ui.refreshable
    def body() -> None:
        if not state["kw"]:
            with connect() as c:
                recent = KO.recent(c)
            if not recent:
                T.empty_state(ui, "query_stats", "Gõ một từ khóa rồi bấm Phân tích",
                              "Volume Việt Nam và thế giới, xu hướng, CPC, ý định, biến thể, câu hỏi, nhóm chủ đề và "
                              "trang kết quả Google (khi từ khóa đang được theo dõi hạng).")
                return
            with ui.element("div").classes("sr-card q-pa-md w-full"):
                ui.label("Từ khóa đã phân tích gần đây").classes("text-base font-semibold q-mb-sm")
                rows = [{"id": i, **r, "at_t": datetime.fromisoformat(r["at"]).astimezone().strftime("%d/%m %H:%M")}
                        for i, r in enumerate(recent)]
                tb = ui.table(columns=[
                    {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left"},
                    {"name": "volume", "label": "Volume", "field": "volume", "align": "right",
                     ":format": "v => v === null || v === undefined ? 'n/a' : v.toLocaleString('vi-VN')"},
                    {"name": "cpc", "label": "CPC", "field": "cpc", "align": "right",
                     ":format": "v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN', "
                                "{maximumFractionDigits: 0})"},
                    {"name": "at_t", "label": "Xem lúc", "field": "at", "align": "right"},
                ], rows=rows, row_key="id", pagination=15).props("flat dense").classes("w-full sr-bl-table")
                tb.add_slot("body-cell-keyword", """
                    <q-td :props="props"><a :href="'/tu-khoa?kw=' + encodeURIComponent(props.value)"
                      class="sr-ko-kw">{{ props.value }}</a></q-td>""")
                tb.add_slot("body-cell-at_t", """<q-td :props="props" class="muted">{{ props.row.at_t }}</q-td>""")
            return
        if state["loading"]:
            with ui.element("div").classes("w-full sr-busy").props('aria-busy="true" aria-label="Đang phân tích"'):
                T.bone(ui, "34px", "380px")
                with ui.element("div").classes("sr-ko-grid q-mt-md"):
                    for _ in range(4):
                        T.bone(ui, "220px", radius="14px")
                T.bone(ui, "320px", radius="14px")
            return
        if state["err"]:
            T.empty_state(ui, "error_outline", "Chưa phân tích được", state["err"])
            return
        d = state["data"]
        cur = d["currency"]

        # ---- Một khối chung (nền trắng, màu xanh lá / xanh chanh của tool): số chính · 12 tháng · vị thế · nên làm gì
        name_i, cls_i = INTENT[d["intent"]]
        s = d["site"]
        sp = d["serp"] or {}
        aio = sp.get("aio") or {}
        pos = s["position"] if s else None
        with ui.element("div").classes("sr-card sr-ko-main w-full"):
            with ui.element("div").classes("sr-ko-top"):
                with ui.element("div").classes("sr-ko-hero-main"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"{d['intent']} · {name_i}").classes(f"sr-ko-hchip {cls_i}")
                        if d["question"]:
                            ui.label("dạng câu hỏi").classes("sr-ko-hchip")
                        if d["trend"]:
                            ui.label("▲ đang tăng" if d["trend"] == "up" else "▼ đang giảm").classes(
                                "sr-ko-hchip " + ("up" if d["trend"] == "up" else "down"))
                        if d["season"]["soon"]:
                            ui.label("sắp vào mùa").classes("sr-ko-hchip hot").tooltip(
                                "2 tháng tới người tìm nhiều hơn trung bình năm từ 20%")
                    with ui.row().classes("items-end gap-3 q-mt-sm"):
                        ui.label(_n(d["volume"])).classes("sr-ko-hvol")
                        with ui.column().classes("gap-0 q-pb-xs"):
                            with ui.row().classes("items-center gap-1 no-wrap"):
                                T.flag(ui)
                                ui.label("lượt tìm / tháng").classes("sr-ko-hsub")
                            ui.label(f"toàn cầu {_n(d['world'])}").classes("sr-ko-hsub").tooltip(
                                " · ".join(f"{c['name']} {_n(c['volume'])}" for c in d["countries"]))
                    with ui.element("div").classes("sr-ko-hmetrics"):
                        ci = d["competition_index"]
                        for lab, val, tip in (
                                (f"CPC ({cur})", KR.money(d["cpc"], cur) if d["cpc"] else "n/a",
                                 f"Giá thầu đầu trang: {_n(d['low_bid'])} – {_n(d['high_bid'])} {cur}"),
                                ("Cạnh tranh quảng cáo",
                                 (f"{ci / 100:.2f}".replace(".", ",") + f" · {COMP.get(d['competition'], '')}")
                                 if ci is not None else "n/a",
                                 "Mức các nhà quảng cáo tranh nhau từ khóa này (0–1). Không phải độ khó SEO."),
                                ("Ý tưởng liên quan", f"{d['ideas']}", "Số từ khóa Google Keyword Planner gợi ý")):
                            with ui.column().classes("gap-0 sr-ko-hm"):
                                ui.label(lab).classes("sr-ko-hsub")
                                ui.label(val).classes("sr-ko-hval").tooltip(tip)
                with ui.element("div").classes("sr-ko-hero-chart"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label("12 tháng gần nhất").classes("sr-ko-hsub")
                        if d["season"]["peak"]:
                            ui.label(f"cao điểm {MONTHS[d['season']['peak'] - 1]}").classes("sr-ko-hchip")
                    if d["monthly"]:
                        vals = [n for _, n in d["monthly"]]
                        top = max(vals) if vals else 0
                        ui.echart({
                            "animation": False, "grid": {"left": 2, "right": 2, "top": 8, "bottom": 20},
                            "tooltip": {"trigger": "axis", "backgroundColor": "#fff",
                                        "textStyle": {"color": "#1F221E"}},
                            "xAxis": {"type": "category", "data": [f"{m[5:]}/{m[2:4]}" for m, _ in d["monthly"]],
                                      "axisLabel": {"fontSize": 10, "color": "#6B6A5E"}, "axisTick": {"show": False},
                                      "axisLine": {"lineStyle": {"color": "#E4E3DA"}}},
                            "yAxis": {"type": "value", "show": False},
                            "series": [{"type": "bar", "name": "Lượt tìm", "barMaxWidth": 16,
                                        "data": [{"value": n, "itemStyle": {
                                            "color": "#1E7C31" if n == top else "#B8D332",
                                            "borderRadius": [4, 4, 0, 0]}} for n in vals]}]}).style(
                            "height:140px; width:100%")
                    else:
                        ui.label("Google Ads chưa có số theo tháng.").classes("sr-ko-hsub q-mt-md")

            # hàng dưới, cùng khối: Vị thế của website | Nên làm gì
            with ui.element("div").classes("sr-ko-bottom"):
                with ui.element("div").classes("sr-ko-pos"):
                    ui.label("Vị thế của website").classes("sr-ko-lab")
                    tone = "good" if pos and pos <= 3 else "warn" if pos and pos <= 10 else "bad"
                    with ui.row().classes("items-end gap-3 q-mt-xs"):
                        ui.label(f"#{pos:.1f}".replace(".", ",") if pos else "Chưa có hạng").classes(
                            f"sr-ko-posbig t-{tone}")
                        if s:
                            ui.label(f"{_n(s['clicks'])} click · {_n(s['impressions'])} hiển thị · 28 ngày").classes(
                                "text-sm muted q-pb-xs")
                    if s and s["page"]:
                        ui.link(s["page"].replace(site.rstrip("/"), "") or "/",
                                f"/research?tra={quote(s['page'], safe='')}").classes("sr-ko-path").tooltip(
                            "Xem mọi từ khóa trang này đang có hạng")
                    with ui.column().classes("gap-1 q-mt-sm"):
                        if sp.get("date"):
                            line("leaderboard", "Check hạng" if not sp.get("live") else "Trang kết quả",
                                 f"#{sp['own_rank']}" if sp.get("own_rank") else f"ngoài top {sp.get('depth') or 10}")
                        if aio:
                            line("auto_awesome", "AI Overview",
                                 "được trích" if aio.get("cited") else "có, chưa trích site" if aio.get("shown")
                                 else "không có")
                        gain = _gain(d["volume"], pos)
                        if gain:
                            line("trending_up", "Nếu lên top 3", f"+{_n(gain)} click / tháng (ước tính)")
                with ui.element("div").classes("sr-ko-todo"):
                    ui.label("Nên làm gì").classes("sr-ko-lab")
                    with ui.column().classes("gap-2 q-mt-sm"):
                        for icon, text in _tips(d, pos, aio):
                            with ui.row().classes("items-start no-wrap gap-2"):
                                ui.icon(icon, size="18px").classes("sr-ko-tipico")
                                ui.label(text).classes("text-sm")

        # ---- Ý tưởng: 3 cột Biến thể · Câu hỏi · Nhóm chủ đề, mỗi dòng có thanh volume ----
        kwq = quote(d["keyword"])
        with ui.element("div").classes("sr-card sr-ko-ideas-box w-full q-mt-md"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("Ý tưởng từ khóa").classes("text-base font-semibold col")
                ui.link("Mở tab Ý tưởng →", f"/research?kw={kwq}").classes("sr-ko-more q-mt-none")
            with ui.element("div").classes("sr-ko-ipanels"):
                for icon, title, rows, more, grp in (
                        ("call_split", "Biến thể", d["variations"], f"/research?kw={kwq}&match=broad", False),
                        ("help_outline", "Câu hỏi", d["questions"], f"/research?kw={kwq}&kind=questions", False),
                        ("hub", "Nhóm chủ đề", d["groups"], f"/research?kw={kwq}&view=groups", True)):
                    idea_panel(icon, title, rows, more, grp)

        serp_block(d["serp"])

    def line(icon: str, label: str, value: str) -> None:
        with ui.row().classes("items-center no-wrap gap-2 sr-ko-line"):
            ui.icon(icon, size="16px").classes("muted")
            ui.label(label).classes("text-sm muted")
            ui.label(value).classes("text-sm font-semibold")

    def idea_panel(icon: str, title: str, rows: list[dict], more: str, grp: bool) -> None:
        """Một cột ý tưởng: đầu cột (số lượng · tổng volume), 8 dòng đầu có thanh volume so với dòng lớn nhất."""
        total = sum((r["volume"] or 0) for r in rows)
        top = max(((r["volume"] or 0) for r in rows[:8]), default=0) or 1
        with ui.element("div").classes("sr-ko-ipanel"):
            with ui.row().classes("items-center no-wrap gap-2"):
                ui.icon(icon, size="18px").classes("sr-ko-iico")
                ui.label(title).classes("text-sm font-semibold col")
                ui.label(f"{len(rows)}").classes("sr-ko-icount")
            if not rows:
                with ui.column().classes("items-center gap-1 sr-ko-iempty"):
                    ui.icon("search_off", size="22px").classes("muted")
                    ui.label(f"Không có {title.lower()} cho từ khóa này.").classes("text-xs muted")
                return
            ui.label(f"tổng volume {_n(total)}").classes("text-xs muted")
            with ui.column().classes("gap-0 q-mt-sm w-full"):
                for r in rows[:8]:
                    kw_ = r["name"] if grp else r["keyword"]
                    vol = r["volume"] or 0
                    with ui.element("div").classes("sr-ko-bar-row"):
                        with ui.row().classes("items-center no-wrap gap-2 w-full"):
                            link_kw(kw_)
                            if grp:
                                ui.label(f"{len(r['rows'])} từ").classes("text-xs muted")
                            ui.label(_n(r["volume"])).classes("num text-sm sr-ko-ivol")
                        with ui.element("div").classes("sr-ko-bar-track"):
                            ui.element("div").classes("sr-ko-bar-fill").style(
                                f"width:{max(2, round(100 * vol / top))}%")
            if len(rows) > 8:
                ui.link(f"Xem tất cả {len(rows)} →", more).classes("sr-ko-more")

    def idea_col(title: str, rows: list[dict], total: int, more: str) -> None:
        with ui.column().classes("gap-1 sr-ko-col"):
            ui.label(title).classes("sr-ko-lab")
            with ui.row().classes("items-baseline gap-2"):
                ui.label(f"{len(rows)}").classes("sr-ko-mid sr-ko-count")
                ui.label(f"tổng volume {_n(total)}").classes("text-sm")
            if not rows:
                ui.label("Không có dữ liệu.").classes("text-sm muted q-mt-md")
                return
            with ui.element("table").classes("sr-ko-table"):
                with ui.element("tr"):
                    for h in ("Từ khóa", "Volume", "CPC"):
                        with ui.element("th").classes("text-left" if h == "Từ khóa" else "text-right"):
                            ui.label(h)
                for r in rows[:6]:
                    with ui.element("tr"):
                        with ui.element("td"):
                            link_kw(r["keyword"])
                        with ui.element("td").classes("text-right num"):
                            ui.label(_n(r["volume"]))
                        with ui.element("td").classes("text-right num muted"):
                            ui.label(_n(r["cpc"]) if r["cpc"] else "–")
            ui.link(f"Xem tất cả {len(rows)} →", more).classes("sr-ko-more")

    def make_xlsx() -> bytes:
        """File Tổng quan từ khóa: sheet số chính, biến thể, câu hỏi, nhóm chủ đề, trang kết quả Google."""
        import io

        from openpyxl import Workbook
        from openpyxl.styles import Font
        d = state["data"]
        cur = d["currency"]
        wb = Workbook()
        ws = wb.active
        ws.title = "Tổng quan"
        s_ = d["site"] or {}
        sp = d["serp"] or {}
        for k, v in (("Từ khóa", d["keyword"]), ("Volume Việt Nam", d["volume"]), ("Volume toàn cầu", d["world"]),
                     *[(f"Volume {c['name']}", c["volume"]) for c in d["countries"]],
                     ("Mục đích", INTENT[d["intent"]][0]), (f"CPC ({cur})", d["cpc"]),
                     (f"Giá thầu thấp ({cur})", d["low_bid"]), (f"Giá thầu cao ({cur})", d["high_bid"]),
                     ("Cạnh tranh quảng cáo (0–100)", d["competition_index"]),
                     ("Vị trí site (28 ngày)", s_.get("position")), ("Click site (28 ngày)", s_.get("clicks")),
                     ("Trang site", s_.get("page")), ("Vị trí ở lần check hạng", sp.get("own_rank")),
                     *[(f"Volume {m[5:]}/{m[:4]}", n) for m, n in d["monthly"]]):
            ws.append([k, v])
        for c in ws["A"]:
            c.font = Font(bold=True)
        ws.column_dimensions["A"].width = 32
        ws.column_dimensions["B"].width = 60

        def sheet(title, head, rows):
            w = wb.create_sheet(title)
            w.append(head)
            for c in w[1]:
                c.font = Font(bold=True)
            for r in rows:
                w.append(r)
            w.column_dimensions["A"].width = 44
            w.freeze_panes = "A2"
        idea = lambda r: [r["keyword"], r["volume"], r["cpc"], INTENT.get(r.get("intent"), ("",))[0]]  # noqa: E731
        sheet("Biến thể", ["Từ khóa", "Volume", f"CPC ({cur})", "Mục đích"], [idea(r) for r in d["variations"]])
        sheet("Câu hỏi", ["Từ khóa", "Volume", f"CPC ({cur})", "Mục đích"], [idea(r) for r in d["questions"]])
        sheet("Nhóm chủ đề", ["Nhóm", "Số từ khóa", "Tổng volume", "Trang đích", "Việc nên làm", "Các từ khóa"],
              [[g["name"], len(g["rows"]), g["volume"], g["page"] or "", g["action"],
                ", ".join(r["keyword"] for r in g["rows"])] for g in d["groups"]])
        if sp.get("results"):
            sheet("Kết quả Google", ["Vị trí", "URL", "Tên miền", "Thương hiệu"],
                  [[r["rank"], r["url"], r["domain"], r["brand"] or ""] for r in sp["results"]])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def link_kw(text: str) -> None:
        """Bấm từ khóa: sang tab Ý tưởng từ khóa, tìm ý tưởng cho từ khóa đó."""
        ui.link(text, f"/research?kw={quote(text)}").classes("sr-ko-kw").tooltip("Xem ý tưởng từ khóa")

    logos: dict[str, str] = {}

    def serp_block(sp: dict | None) -> None:
        """Trang kết quả Google: dòng tóm tắt (vị trí của bạn · AI Overview · đối thủ · ô đặc biệt), rồi hai cột cạnh
        nhau: kết quả tự nhiên | AI Overview (nền tím nhạt). Của mình nền xanh nhạt, đối thủ có nhãn tên."""
        from . import aio as AO
        with ui.element("div").classes("sr-card sr-ko-serp w-full q-mt-md"):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                with ui.column().classes("gap-0 col"):
                    ui.label("Trang kết quả Google").classes("text-base font-semibold")
                    if sp and sp.get("live"):
                        at = datetime.fromisoformat(sp["at"]).astimezone()
                        ui.label(f"Lấy một lần lúc {at:%H:%M %d/%m/%Y}").classes("text-xs muted")
                    elif sp and sp.get("date"):
                        ui.label(f"Lần check hạng {sp['date'][8:]}/{sp['date'][5:7]}/{sp['date'][:4]}").classes(
                            "text-xs muted")
                if sp and sp.get("live") and ed:
                    ui.button(icon="refresh", on_click=lambda: live_serp()).props(
                        'flat round dense aria-label="Lấy lại trang kết quả"').tooltip(
                        f"Lấy lại (khoảng {KO.LIVE_EST_USD:.3f} USD)".replace(".", ","))
            if not sp or not sp.get("date"):
                with ui.element("div").classes("sr-ko-serp-empty"):
                    ui.icon("travel_explore", size="28px").classes("muted")
                    with ui.column().classes("gap-1 col"):
                        ui.label("Chưa có trang kết quả Google cho từ khóa này").classes("text-sm font-semibold")
                        ui.label("Xem ngay top 10, AI Overview và các ô đặc biệt (một lần, khoảng "
                                 f"{KO.LIVE_EST_USD:.3f} USD, tính vào ngân sách DataForSEO), hoặc theo dõi hạng để "
                                 "có số mỗi lần check.".replace("0.002", "0,002")).classes("text-sm muted")
                    if ed:
                        with ui.row().classes("gap-2 items-center"):
                            ui.button("Xem kết quả Google", icon="travel_explore", on_click=lambda: live_serp()).props(
                                "unelevated no-caps")
                            if not sp:
                                ui.button("Theo dõi hạng", icon="playlist_add", on_click=add_to_set).props(
                                    "outline no-caps")
                return
            with connect() as c:
                brands = AO.brands(c, cfg)
            logos.clear()
            for b_ in brands:
                if b_.get("logo") and str(b_["logo"]).startswith(("http", "data:", "/")):
                    for dm in b_["domains"]:
                        logos[dm.lower().removeprefix("www.")] = b_["logo"]

            def who(r: dict):
                b = next((b for b in brands if AO.cited([r], b)), None)
                return ("own", b["name"]) if b and b["own"] else ("rival", b["name"]) if b else ("", "")
            top = [r for r in sp["results"] if r["rank"] <= 10]
            rivals = len({r["brand"] for r in top if r["brand"] and not r["own"]})
            aio = sp["aio"] or {}
            refs = aio.get("refs") or []
            own_ref = next((i for i, r in enumerate(refs, 1) if who(r)[0] == "own"), None)
            # Dòng tóm tắt: các ý chính đọc một lượt
            with ui.element("div").classes("sr-ko-serp-sum"):
                fact("emoji_events", "Vị trí của bạn",
                     f"#{sp['own_rank']}" if sp["own_rank"] else f"ngoài top {sp.get('depth') or 10}",
                     "good" if sp["own_rank"] and sp["own_rank"] <= 3 else "warn" if sp["own_rank"] else "bad")
                if aio.get("shown"):
                    fact("auto_awesome", "AI Overview", f"được trích · nguồn #{own_ref}" if own_ref else
                         "có, site chưa được trích", "good" if own_ref else "warn")
                else:
                    fact("auto_awesome", "AI Overview", "không có trên trang này", "muted")
                fact("groups", "Đối thủ trong top 10", str(rivals), "bad" if rivals >= 3 else "muted")
                with ui.element("div").classes("sr-ko-feats"):
                    for f in sp["features"]:
                        T.tag(ui, f, "purple" if f == "AI Overview" else "grey")
            with ui.element("div").classes("sr-ko-serp-grid" + (" one" if not aio.get("shown") else "")):
                with ui.element("div").classes("sr-ko-serp-col"):
                    ui.label(f"Kết quả tự nhiên · {len(top)}").classes("sr-ko-lab q-mb-xs")
                    for r in top:
                        serp_row(r["rank"], r["url"], r["domain"], None, *(("own", r["brand"]) if r["own"] else
                                                                          ("rival", r["brand"]) if r["brand"]
                                                                          else ("", "")))
                if aio.get("shown"):
                    with ui.element("div").classes("sr-ko-serp-col sr-ko-aio"):
                        with ui.row().classes("items-center gap-1 q-mb-xs"):
                            ui.icon("auto_awesome", size="16px").style("color:#5B3FD0")
                            ui.label(f"AI Overview trích {len(refs)} nguồn").classes("sr-ko-lab")
                        if not refs:
                            ui.label("Google chưa tải xong nội dung AI Overview ở lần đọc này.").classes(
                                "text-sm muted")
                        for i, r in enumerate(refs, 1):
                            serp_row(i, r["url"], r.get("domain", ""), r.get("title"), *who(r))

    def fact(icon: str, label: str, value: str, tone: str) -> None:
        with ui.element("div").classes(f"sr-ko-fact t-{tone}"):
            ui.icon(icon, size="18px")
            with ui.column().classes("gap-0"):
                ui.label(label).classes("text-xs muted")
                ui.label(value).classes("text-sm font-semibold")

    def serp_row(n: int, url: str, domain: str, title: str | None, kind: str, name: str) -> None:
        """Một kết quả: số thứ tự · chữ cái tên miền · tên miền (bấm: ý tưởng theo website) + tiêu đề / đường dẫn
        (bấm: từ khóa URL đang có hạng) · nhãn của mình / đối thủ · mở trang."""
        from urllib.parse import urlsplit
        from html import escape
        bg, fg = T.avatar_color(domain or "?")
        path = urlsplit(url).path or "/"
        logo = logos.get(domain) or f"https://www.google.com/s2/favicons?domain={quote(domain)}&sz=64"
        letter = escape((domain or "?")[:1].upper())
        with ui.element("div").classes(f"sr-ko-hit {kind}"):
            ui.label(str(n)).classes("sr-ko-n")
            ui.html(f'<span class="sr-ko-av" style="background:{bg};color:{fg}">{letter}'
                    f'<img src="{escape(logo)}" alt="" loading="lazy" referrerpolicy="no-referrer" '
                    'onerror="this.remove()"></span>')
            with ui.column().classes("gap-0 col").style("min-width:0"):
                with ui.row().classes("items-center no-wrap sr-ko-hit-top").style("gap: 6px; min-width: 0"):
                    ui.link(domain, f"/research?site={quote(domain)}").classes("sr-ko-dom").tooltip(
                        f"Ý tưởng từ khóa theo cả website {domain}")
                    if kind == "own":
                        ui.icon("home", size="16px").classes("sr-ko-kind own").props(
                            'aria-label="Website của bạn"').tooltip("Website của bạn")
                    elif kind == "rival":
                        ui.icon("flag", size="16px").classes("sr-ko-kind rival").props(
                            f'aria-label="Đối thủ"').tooltip(f"Đối thủ: {name}")
                ui.link(title or path, f"/research?tra={quote(url, safe='')}").classes("sr-ko-path").tooltip(
                    f"Xem từ khóa trang này đang có hạng: {url}")
            with ui.link(target=url, new_tab=True).classes("sr-ko-open").props('aria-label="Mở trang"'):
                ui.icon("open_in_new", size="16px")

    async def live_serp() -> None:
        from contextlib import closing

        from . import db
        note = ui.notification("Đang lấy trang kết quả Google…", spinner=True, timeout=None, type="ongoing",
                               position="bottom-right")

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                KO.fetch_serp(c, cfg, state["kw"], str(user))
                return KO.get(c, cfg, state["kw"])
        try:
            state["data"] = await run.io_bound(work)
            body.refresh()
        except Exception as ex:  # noqa: BLE001
            ui.notify(str(ex), type="warning", multi_line=True, position="bottom-right")
        finally:
            note.dismiss()

    def open_research() -> None:
        from contextlib import closing

        from . import db
        try:
            with closing(db.connect(cfg.db_path)) as c:
                rec = KR.research(c, cfg, "keywords", state["kw"], str(user))
            ui.navigate.to(f"/research?id={rec['id']}")
        except Exception as ex:  # noqa: BLE001
            ui.notify(str(ex), type="warning")

    def add_to_set() -> None:
        from . import keywords as K
        from . import rank as R
        with connect() as c:
            sets = [s for s in R.sets(c, site) if s.get("kind") != "kpi"]
        if not sets:
            ui.notify("Chưa có bộ từ khóa nào do team tạo", type="warning")
            return
        with ui.dialog() as dlg, ui.card().style("min-width: 420px; border-radius: 14px"):
            ui.label(f"Theo dõi hạng “{state['kw']}”").classes("text-lg font-semibold")
            sel = ui.select({s["id"]: s["name"] + (" (Nháp)" if s.get("draft") else "") for s in sets},
                            value=sets[0]["id"], label="Bộ từ khóa").props("outlined dense").classes("w-full")

            def do():
                with connect() as c:
                    res = R.add_keywords(c, site, cfg.rank, K.latest_date(c, site), [(state["kw"], None)],
                                         str(user), set_id=sel.value)
                dlg.close()
                ui.notify("Đã thêm vào bộ" if res["added"] else "Từ khóa đã có / vượt ngân sách",
                          type="positive" if res["added"] else "warning")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Thêm", on_click=do).props("unelevated no-caps")
        dlg.open()

    async def load(refresh: bool = False) -> None:
        from contextlib import closing

        from . import db
        state["loading"], state["err"] = True, ""
        head.refresh()
        body.refresh()

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                return KO.get(c, cfg, state["kw"], refresh=refresh)
        try:
            state["data"] = await run.io_bound(work)
        except Exception as ex:  # noqa: BLE001
            state["err"] = str(ex)
        state["loading"] = False
        head.refresh()
        body.refresh()

    body()
    if state["kw"]:
        background_tasks.create(load())


def _esc(s: str) -> str:
    from html import escape
    return escape(s)


def _slug(t: str) -> str:
    from . import keywords as K
    return "-".join(w for w in (K.fold(x) for x in t.split()) if w)[:40] or "tu-khoa"


def _gain(volume: int | None, pos: float | None) -> int | None:
    """Click thêm mỗi tháng nếu lên vị trí 3 (ước tính theo tỷ lệ nhấp trung bình)."""
    from .rank_overview import ctr
    if not volume or (pos is not None and pos <= 3):
        return None
    g = volume * (ctr(3) - ctr(round(pos) if pos else None))
    return round(g) if g >= 1 else None


def _tips(d: dict, pos: float | None, aio: dict) -> list[tuple[str, str]]:
    """Gợi ý việc nên làm, suy ra từ số thật của từ khóa (không thêm số ước đoán ngoài các số đã ghi rõ)."""
    out = []
    page = (d["site"] or {}).get("page")
    if pos is None:
        out.append(("add_circle", "Site chưa có hạng: tạo hoặc chọn một trang đích cho từ khóa này, đặt từ khóa vào "
                                  "tiêu đề / H1 và thêm link nội bộ từ trang mạnh."))
    elif pos > 3:
        out.append(("trending_up", f"Đang ở vị trí {pos:.1f}: tối ưu trang đang lên (nội dung trả lời đúng ý định, "
                                   "tiêu đề, link nội bộ) để vào top 3.".replace(".", ",", 1)))
    else:
        out.append(("verified", "Đã ở top 3: giữ phong độ, cập nhật nội dung định kỳ và theo dõi đối thủ vượt lên."))
    if aio.get("shown") and not aio.get("cited"):
        out.append(("auto_awesome", "AI Overview chưa trích site: thêm đoạn trả lời ngắn, rõ ràng (định nghĩa, "
                                    "bảng giá, các bước) ở đầu trang."))
    if d["season"]["soon"]:
        peak = MONTHS[d["season"]["peak"] - 1] if d["season"]["peak"] else ""
        out.append(("event", "Sắp vào mùa" + (f" (cao điểm {peak})" if peak else "")
                    + ": đẩy nội dung và link ngay từ bây giờ."))
    if d["questions"]:
        out.append(("help", f"Có {len(d['questions'])} câu hỏi liên quan: thêm phần FAQ trả lời các câu hỏi này."))
    if d["intent"] in ("C", "T") and d.get("competition") == "HIGH":
        out.append(("paid", "Giá trị thương mại cao (cạnh tranh quảng cáo cao): ưu tiên trang sản phẩm / danh mục."))
    if not page and pos is None and d["groups"]:
        out.append(("hub", f"Có {len(d['groups'])} nhóm chủ đề liên quan: xem tab Ý tưởng để lên cụm bài."))
    return out[:5]
