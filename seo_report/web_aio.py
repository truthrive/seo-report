"""Trang AI Overview (/aio): AI Overview của Google trên bộ từ khóa theo dõi, đọc từ kết quả check rank (DataForSEO).
Trang riêng, tách khỏi số GA4 / GSC ở AI Search & GEO để khách hàng dễ theo dõi; dòng tóm tắt ở Tổng quan.

Khác số của GSC (lượt hiển thị thật trong AI của Google): đây là ảnh chụp mỗi lần check. AI Overview hiện lúc có lúc
không và đổi nguồn trích giữa các lần tìm, nên các số chính tính theo tuần (lần check cuối của tuần), không so từng lần
với nhau. Mọi số ghi rõ nơi check (thiết bị, vùng) và đã kiểm tra bao nhiêu / tổng số từ khóa."""
from datetime import date, timedelta

from . import keywords as K
from . import rank as R
from . import ui_theme as T
from .web_rank import icon_btn

WEEKS = 4


def where_text(connect, cfg) -> str:
    """Nơi check của các bộ có từ khóa: một nơi thì ghi thẳng, nhiều nơi thì liệt kê."""
    with connect() as c:
        places = list(dict.fromkeys(R.where_short(R.settings_for(cfg.rank, x)) for x in R.sets(c, cfg.site_url)
                                    if x["count"]))
    return " / ".join(places) or R.where_short(cfg.rank)


def load(connect, cfg, weeks: int = WEEKS) -> tuple[list[dict], dict]:
    with connect() as c:
        rows = R.aio_window(c, cfg.site_url, K.latest_date(c, cfg.site_url), date.today(), weeks)
    return rows, R.aio_stats(rows)


def _vn(iso: str | None) -> str:
    return f"{date.fromisoformat(iso):%d/%m/%Y}" if iso else ""


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def _stat(ui, label: str, value: str, detail: str, tip: str):
    with ui.column().classes("gap-0").tooltip(tip):
        ui.label(label).classes("text-xs muted")
        ui.html(f'<div class="sr-mini-num num">{value}</div>')
        ui.label(detail).classes("text-xs muted")


def _rate(pair) -> float | None:
    n, d = pair or (0, 0)
    return n / d if d else None


def _pp(now, prev) -> tuple[str, bool | None]:
    """Chênh lệch điểm phần trăm cho nhãn ▲▼ ("+2 điểm"), hoặc "±0"."""
    a, b = _rate(now), _rate(prev)
    if a is None or b is None:
        return "", None
    d = round((a - b) * 100)
    return (f"{d:+d} điểm" if d else "±0"), (None if not d else d > 0)


def next_check(connect, cfg) -> date | None:
    """Ngày check theo lịch sớm nhất của các bộ đang chạy (có từ khóa, không tạm dừng)."""
    with connect() as c:
        days = [R.next_scheduled_day(x["schedule"], date.today()) for x in R.sets(c, cfg.site_url)
                if x["count"] and not x["paused"]]
    days = [d for d in days if d]
    return min(days) if days else None


def _h2(ui, text: str, cls: str = "sr-section-title"):
    """Tiêu đề khối, đánh dấu cấp 2 cho trình đọc màn hình."""
    lab = ui.label(text).classes(cls)
    lab.props["role"] = "heading"
    lab.props["aria-level"] = "2"
    return lab


SEG = "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"


def tab(ui, connect, cfg, ed: bool, header=None, start: str = "", set_id: int | None = None, user_=None) -> None:
    """Nội dung trang AI Overview: dòng phạm vi + tab (Tổng quan · Việc nên làm · Từ khóa · Thương hiệu). Nút chọn
    khoảng thời gian đặt ở đầu trang (header) vì nó áp cho cả 4 thẻ và biểu đồ. Số từ kết quả check rank (DataForSEO),
    mỗi tuần lấy lần check cuối của tuần."""
    from nicegui import background_tasks

    from . import aio as AO
    state = {"weeks": 12, "metric": "mention", "change": "new_mention", "set": set_id}
    where = where_text(connect, cfg)
    if header is not None:
        with header:
            t_ = ui.toggle({4: "4 tuần", 12: "12 tuần", 26: "26 tuần"}, value=state["weeks"],
                           on_change=lambda e: (state.update(weeks=e.value), overview.refresh())).props(SEG).classes(
                "sr-seg")
            t_.props["aria-label"] = "Khoảng thời gian của thẻ và biểu đồ"
            from datetime import date as _d

            from .web_export import export_menu

            def make_xlsx() -> bytes:  # theo bộ và khoảng tuần đang chọn trên trang
                from . import aio_export as AX
                with connect() as c:
                    return AX.build(c, cfg, state["set"], state["weeks"])
            export_menu(ui, cfg, connect, f"ai-overview_{_d.today():%Y-%m-%d}", make_xlsx,
                        label="Xuất AI Overview (theo tuần, từng từ khóa, thay đổi)", user=user_, icon_only=True,
                        category="aio")

    # ------------------------------------------------------------------ Tổng quan
    @ui.refreshable
    def overview():
        with connect() as c:
            d = AO.dashboard(c, cfg, weeks=state["weeks"], set_id=state["set"])
            ch = AO.changes(c, cfg, state["set"])
        own, now, prev = d["own"], d["now"], d["prev"]
        last = d["weeks"][-1] if d["weeks"] else None
        # ---- dòng phạm vi: tuần, nơi check, đã kiểm tra bao nhiêu, lần check tới ----
        nxt = next_check(connect, cfg)
        parts = []
        if last:
            w0 = date.fromisoformat(d["last_week"])
            parts.append(f"Tuần {w0:%d/%m} – {w0 + timedelta(days=6):%d/%m}")
        parts.append(where)
        parts.append(f"đã kiểm tra {last['checked'] if last else 0}/{d['total']} từ khóa")
        if nxt:
            parts.append(f"lần check tới: {R.WEEKDAYS[nxt.weekday()]}, {nxt:%d/%m}")
        ui.label(" · ".join(parts)).classes("sr-aio-scope")
        if not last:
            T.empty_state(ui, "auto_awesome", "Chưa có số AI Overview",
                          "Lần check rank tới sẽ có (mỗi từ khóa thêm tối đa 0,0006 USD).")
            return

        # ---- 4 thẻ: một hàng ngang trên cùng, cùng chiều cao, cùng đơn vị % ----
        with ui.element("div").classes("sr-aio-kpis"):
            for k_, icon, label, tip, tone in (
                    ("visibility", "visibility", "Được nhắc tên",
                     f"{own['name']} được nhắc trong {{n}}/{{d}} AI Overview đọc được nội dung", "amber"),
                    ("citations", "link", "Được trích",
                     "Website được trích link trong {n}/{d} AI Overview", "green"),
                    ("presence", "auto_awesome", "Có AI Overview",
                     "Google hiện câu trả lời AI ở {n}/{d} từ khóa đã kiểm tra", "purple"),
                    ("organic", "leaderboard", "Top 10 thường",
                     "Website ở top 10 trên {n}/{d} từ khóa đã kiểm tra", "blue")):
                n_, d_ = now.get(k_, (0, 0))
                delta, good = _pp(now.get(k_), prev.get(k_))
                if k_ == "presence":
                    good = None  # nhiều hay ít AI Overview không phải tốt hay xấu
                value, hint = _pct(_rate(now.get(k_))), tip.format(n=n_, d=d_)
                if k_ == "visibility" and not d_:  # lần check cũ chưa lưu nội dung chữ AI Overview
                    value, hint = "–", "Chưa có nội dung chữ AI Overview: lần check tới sẽ có"
                T.kpi(ui, icon, label, value, delta, good, hint, tone=tone)

        # ---- Thương hiệu trong AI Overview (rộng hết khung) ----
        key, base = ("mention", "texted") if state["metric"] == "mention" else ("cite", "reffed")

        def point(w, b):
            n = w["brands"].get(b["id"], {}).get(key, 0)
            return {"value": round(n / w[base] * 100) if w[base] else None, "n": n, "d": w[base]}
        with ui.element("div").classes("sr-card q-pa-md q-mt-md w-full"):
            with ui.row().classes("w-full items-center gap-2"):
                with ui.column().classes("gap-0"):
                    _h2(ui, "Thương hiệu trong AI Overview")
                    ui.label("Tỷ lệ AI Overview " + ("nhắc tên" if key == "mention" else "trích link")
                             + " từng thương hiệu, theo tuần").classes("text-xs muted")
                ui.space()
                m_ = ui.toggle({"mention": "Được nhắc", "cite": "Được trích"}, value=state["metric"],
                               on_change=lambda e: (state.update(metric=e.value), overview.refresh())).props(
                    SEG).classes("sr-seg")
                m_.props["aria-label"] = "Xem tỷ lệ được nhắc tên hoặc được trích link"
            charted = [b for b in d["brands"] if b["charted"]]
            if len(d["weeks"]) >= 2:
                labels = [f"{date.fromisoformat(w['week']):%d/%m}" for w in d["weeks"]]
                series = [{"type": "line", "name": b["name"], "data": [point(w, b) for w in d["weeks"]],
                           "symbol": "circle", "symbolSize": 8 if b["own"] else 6, "z": 3 if b["own"] else 2,
                           "lineStyle": {"width": 3.25 if b["own"] else 2, "color": b["color"]},
                           "itemStyle": {"color": b["color"]}} for b in charted]
                chart = ui.echart({
                    "animation": False, "grid": {"left": 44, "right": 16, "top": 16, "bottom": 26},
                    "legend": {"show": False},
                    "tooltip": {"trigger": "axis", ":formatter": (
                        "ps => ps[0].axisValueLabel + '<br/>' + ps.map(p => p.marker + p.seriesName + ': <b>' + "
                        "(p.value == null ? '–' : p.value + '%') + '</b> (' + p.data.n + '/' + p.data.d + ')')"
                        ".join('<br/>')")},
                    "xAxis": {"type": "category", "data": labels, "axisTick": {"show": False},
                              "axisLabel": {"color": "#6B6A5E", "fontSize": 11}},
                    "yAxis": {"type": "value", "min": 0, "max": 100,
                              "axisLabel": {"formatter": "{value}%", "color": "#6B6A5E", "fontSize": 11},
                              "splitLine": {"lineStyle": {"color": "#F0EEE6"}}},
                    "series": series}).classes("w-full").style("height: 260px")
                chart.props["role"] = "img"
                chart.props["aria-label"] = "Tỷ lệ tuần mới nhất: " + "; ".join(
                    f"{b['name']} {point(last, b)['value']}%" for b in charted)
            else:  # chưa đủ 2 tuần: so sánh các thương hiệu trong tuần hiện có, không để ô trống
                with ui.element("div").classes("sr-aio-bars"):
                    for b in d["brands"]:
                        p_ = point(last, b)
                        with ui.element("div").classes("sr-aio-bar" + (" own" if b["own"] else "")):
                            ui.label(b["name"]).classes("ellipsis")
                            with ui.element("div").classes("track"):
                                ui.element("div").classes("fill").style(
                                    f"width:{p_['value'] or 0}%; background:{b['color']}")
                            ui.label("–" if p_["value"] is None else f"{p_['value']}% ({p_['n']}/{p_['d']})").classes(
                                "v")
                ui.label("Biểu đồ xu hướng hiện từ tuần thứ 2.").classes("sr-kpi-hint")
            if len(d["weeks"]) >= 2:  # nhãn thương hiệu: % tuần mới nhất + thay đổi (thay cho chú thích biểu đồ)
                pw = d["weeks"][-2]
                with ui.element("div").classes("sr-brand-chips"):
                    for b in d["brands"]:
                        v, pv = point(last, b)["value"], point(pw, b)["value"]
                        with ui.element("span").classes("sr-brand-chip" + (" own" if b["own"] else "")):
                            avatar(b)
                            ui.label(b["name"])
                            ui.label("–" if v is None else f"{v}%").classes("v")
                            if v is not None and pv is not None and v != pv:
                                T.delta_badge(ui, f"{v - pv:+d}", v > pv, since="tuần trước")
                if len(charted) < len(d["brands"]):
                    ui.label(f"Biểu đồ vẽ thương hiệu dự án và {len(AO.COLORS)} đối thủ đầu; các thương hiệu còn lại chỉ có trong nhãn."
                             ).classes("sr-kpi-hint")
            if len(d["brands"]) == 1:
                ui.label("Thêm đối thủ ở tab Thương hiệu để so sánh.").classes("sr-kpi-hint")

        # ---- Thay đổi so với lần check trước ----
        names = {"new_mention": "Mới được nhắc", "lost_mention": "Mất nhắc", "new_cite": "Mới được trích",
                 "lost_cite": "Mất trích"}
        opts = {k: f"{v} · {len(ch[k])}" for k, v in names.items()}

        def pick(v):
            state.update(change=v)
            overview.refresh()
        with ui.element("div").classes("sr-card q-pa-md q-mt-md w-full"):
            with ui.row().classes("w-full items-center gap-2"):
                _h2(ui, "Thay đổi so với lần check trước")
                ui.space()
                ui.toggle(opts, value=state["change"], on_change=lambda e: pick(e.value)).props(SEG).classes(
                    "sr-seg gt-sm")
                ui.select(opts, value=state["change"], on_change=lambda e: pick(e.value)).props(
                    "dense outlined options-dense").classes("lt-md w-full")
            ui.label(f"Mỗi từ khóa so lần check mới nhất với lần trước của chính nó · thương hiệu {own['name']}"
                     ).classes("text-xs muted")
            items = ch[state["change"]]
            if not items:
                ui.label("Không có từ khóa nào." if len(d["weeks"]) > 1 else
                         "Cần ít nhất 2 lần check của cùng từ khóa để so sánh.").classes("text-sm muted q-mt-sm")
            for x in items:
                with ui.row().classes("w-full items-center no-wrap gap-3 sr-opp-row"):
                    ui.label(x["keyword"]).classes("text-sm font-medium col ellipsis")
                    ui.label(f"{_vn(x['prev_date'])[:5]} → {_vn(x['date'])[:5]}").classes("text-xs muted num")

    # ------------------------------------------------------------------ Từ khóa
    @ui.refreshable
    def keywords_view():
        with connect() as c:
            rows = AO.keyword_rows(c, cfg, state["set"])
        if not rows:
            T.empty_state(ui, "auto_awesome", "Chưa có số AI Overview", "Lần check rank tới sẽ có.")
            return
        host = R.domain(cfg.site_url)
        trows = []
        for r in rows:
            others = list(dict.fromkeys(x["domain"] for x in r["refs"] if not R._host_match(x["domain"], host)))
            trows.append({
                "id": r["id"], "keyword": r["keyword"],
                "pos": "" if r["depth"] is None else (str(r["rank"]) if r["rank"] is not None else f">{r['depth']}"),
                "sort_pos": r["rank"] or 999, "aio": "Có" if r["aio"] else "Không",
                "mention": "–" if not r["aio"] else ("Có" if r["own_mentioned"] else
                                                     "Chưa" if r["own_mentioned"] is False else "Không rõ"),
                "cite": "–" if not r["aio"] else ("Có" if r["own_cited"] else "Chưa"),
                "brands": ", ".join(r["mentioned"]) or "–", "refs": ", ".join(others) or "–",
                "date": _vn(r["date"])[:5]})
        t = ui.table(columns=[
            {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
            {"name": "pos", "label": "Vị trí", "field": "pos", "align": "right", "sortable": True,
             ":sort": "(a, b, rowA, rowB) => rowA.sort_pos - rowB.sort_pos", "headerStyle": "width:72px"},
            {"name": "aio", "label": "AI Overview", "field": "aio", "align": "center", "sortable": True,
             "headerStyle": "width:110px"},
            {"name": "mention", "label": "Được nhắc", "field": "mention", "align": "center", "sortable": True,
             "headerStyle": "width:110px"},
            {"name": "cite", "label": "Được trích", "field": "cite", "align": "center", "sortable": True,
             "headerStyle": "width:110px"},
            {"name": "brands", "label": "Thương hiệu AI nhắc", "field": "brands", "align": "left"},
            {"name": "refs", "label": "Website AI trích", "field": "refs", "align": "left"},
            {"name": "date", "label": "Ngày check", "field": "date", "align": "center", "headerStyle": "width:96px"},
        ], rows=trows, row_key="id", pagination=25).classes("w-full sr-aio-table").props("flat bordered dense")
        for col in ("mention", "cite"):
            t.add_slot(f"body-cell-{col}", """
                <q-td :props="props" class="text-center">
                  <span v-if="props.value === 'Có'" style="color:#1E7C31;font-weight:600">✓ Có</span>
                  <span v-else-if="props.value === 'Chưa'" style="color:#B3401A;font-weight:600">✗ Chưa</span>
                  <span v-else class="muted">{{ props.value }}</span>
                </q-td>""")
        for col in ("brands", "refs"):
            t.add_slot(f"body-cell-{col}", """
                <q-td :props="props"><div class="ellipsis" :title="props.value">{{ props.value }}</div></q-td>""")
        t.add_slot("body-cell-keyword", """
            <q-td :props="props"><span class="sr-kw-link" role="button" tabindex="0"
              @click="$parent.$emit('open', props.row)" @keydown.enter="$parent.$emit('open', props.row)">
              {{ props.value }}</span></q-td>""")
        by_id = {r["id"]: r for r in rows}
        t.on("open", lambda e: show_text(by_id[e.args["id"]]))
        ui.label("Bấm vào từ khóa để xem nội dung AI Overview và các nguồn AI trích.").classes("sr-kpi-hint")

    def show_text(r: dict):
        host = R.domain(cfg.site_url)
        with ui.dialog() as dlg, ui.card().style("min-width: 620px; max-width: 94vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label(r["keyword"]).classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=dlg.close).props("flat round dense")
            ui.label(f"Lần check {_vn(r['date'])} · {where}").classes("text-xs muted")
            if not r["aio"]:
                ui.label("Google không hiện AI Overview cho từ khóa này.").classes("text-sm muted")
            else:
                _h2(ui, "Nội dung AI trả lời").style("font-size:14px")
                if r["text"]:
                    ui.label(r["text"]).classes("sr-aio-text")
                else:
                    ui.label("Lần check này chưa lưu nội dung chữ (lần check tới sẽ có).").classes("text-sm muted")
                ui.label(f"Nguồn AI trích · {len(r['refs'])}").classes("sr-section-title q-mt-sm").style(
                    "font-size:14px")
                for x in r["refs"]:
                    me = R._host_match(x["domain"], host)
                    with ui.row().classes("w-full items-center no-wrap gap-2 sr-serp-row" + (" me" if me else "")):
                        ui.label(x["domain"]).classes("text-sm font-medium").style("min-width:160px")
                        lk = ui.link(x["title"] or x["url"], x["url"], new_tab=True).classes("text-sm ellipsis col")
                        lk.props["title"] = x["url"]
        dlg.open()

    # ------------------------------------------------------------------ Thương hiệu & đối thủ
    @ui.refreshable
    def brands_view():
        with connect() as c:
            bs = AO.brands(c, cfg)
            sug = AO.suggestions(c, cfg)
        if any(b.get("logo") is None and not b["own"] for b in bs):  # thương hiệu thêm trước khi có logo
            background_tasks.create(load_logos())
        n_comp = len(bs) - 1
        full = n_comp >= AO.MAX_COMPETITORS
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            _h2(ui, f"Thương hiệu & đối thủ · {n_comp}/{AO.MAX_COMPETITORS} đối thủ")
            T.info_icon(ui, "Cách tính", (
                "Thương hiệu được nhắc khi nội dung AI Overview có tên, cách gọi khác hoặc tên miền của nó.",
                "So sánh thương hiệu dự án với đối thủ trong câu trả lời AI của Google.",
                "Không phân biệt hoa thường, có dấu hay không dấu, phải khớp trọn từ. Được trích khi nguồn AI trích "
                "có link về tên miền của thương hiệu."))
            ui.space()
            if n_comp > len(AO.COLORS):
                ui.label(f"Biểu đồ vẽ {len(AO.COLORS)} đối thủ đầu, còn lại chỉ có trong nhãn").classes(
                    "text-xs muted")
        with ui.element("div").classes("sr-brand-list w-full"):
            for b in bs:
                with ui.element("div").classes("sr-card sr-brand-card" + (" own" if b["own"] else "")):
                    with ui.row().classes("w-full items-center no-wrap gap-2"):
                        avatar(b)
                        ui.element("i").classes("sr-brand-dot").style(f"background:{b['color']}").tooltip(
                            "Màu của thương hiệu trên biểu đồ" if b["charted"] else
                            f"Không vẽ trên biểu đồ (biểu đồ vẽ {len(AO.COLORS)} đối thủ đầu), vẫn có trong nhãn và bảng")
                        ui.label(b["name"]).classes("sr-brand-name col ellipsis").props(f'title="{b["name"]}"')
                        if False:  # sửa ở tab Đối thủ (màn Từ khóa & Thứ hạng)
                            icon_btn(ui, "edit", f"Sửa {b['name']}", lambda _, b=b: edit_brand(b))
                            if not b["own"]:
                                icon_btn(ui, "delete_outline", f"Bỏ theo dõi {b['name']}",
                                         lambda _, b=b: drop_brand(b), color="negative")
                    with ui.element("dl").classes("sr-brand-meta"):
                        ui.html("<dt>Cách gọi</dt>")
                        ui.html("<dd>" + (", ".join(b["aliases"]) or "<span class='muted'>Chưa thêm</span>")
                                + "</dd>")
                        ui.html("<dt>Tên miền</dt>")
                        ui.html("<dd>" + (", ".join(b["domains"]) or "<span class='muted'>Chưa thêm</span>")
                                + "</dd>")
            if False:  # thêm ở tab Đối thủ (màn Từ khóa & Thứ hạng)
                add = ui.element("button").classes("sr-brand-add").props('type="button"')
                add.on("click", lambda: edit_brand(None))
                with add:
                    ui.icon("add", size="20px")
                    ui.label("Thêm đối thủ")
        with ui.row().classes("items-center gap-2 q-mt-sm"):
            ui.label("Danh sách dùng chung với thứ hạng. Thêm, sửa, bỏ đối thủ ở").classes("text-sm muted")
            ui.link("Từ khóa & Thứ hạng → Đối thủ", "/rank?bo=doi-thu").classes("text-sm")
        if False:  # gợi ý thêm đối thủ: ở tab Đối thủ
            with ui.column().classes("w-full gap-1 q-mt-md"):
                ui.label("Gợi ý: website AI hay trích, chưa có trong danh sách").classes("text-sm muted")
                with ui.element("div").classes("sr-sug-list"):
                    for d_, n in sug:
                        bt = ui.element("button").classes("sr-sug").props('type="button"')
                        bt.on("click", lambda _, d_=d_: quick_add(d_))
                        with bt:
                            ui.icon("add", size="15px")
                            ui.label(d_)
                            ui.label(f"{n} từ khóa").classes("n")
                        bt.tooltip(f"Thêm {d_} làm đối thủ")

    def avatar(b: dict) -> None:
        """Logo website (tự lấy khi thêm); chưa có logo: chữ cái đầu theo màu thương hiệu."""
        with ui.element("span").classes("sr-brand-logo"):
            if b.get("logo"):
                ui.html(f'<img src="{b["logo"]}" alt="">')
            else:
                ui.label((b["name"] or "?")[:1].upper()).style(f"color:{b['color']}")

    async def load_logos() -> None:
        """Lấy logo cho thương hiệu chưa có (chạy nền, không chặn trang), xong thì vẽ lại."""
        from contextlib import closing

        from nicegui import run

        from . import db

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                return AO.fill_logos(c, cfg)
        try:
            if await run.io_bound(work):
                brands_view.refresh()
                overview.refresh()
        except Exception:  # noqa: BLE001  (website không mở được: giữ chữ cái đầu)
            pass

    def quick_add(d_: str):
        if not ed:
            return
        try:
            with connect() as c:
                AO.save_brand(c, cfg.site_url, d_, "", d_)  # tên = tên miền (đúng chính tả); sửa lại sau nếu cần
        except ValueError as e:
            ui.notify(str(e), type="warning")
            return
        refresh_all()
        background_tasks.create(load_logos())

    def drop_brand(b: dict):
        if not ed:
            return
        with connect() as c:
            AO.remove_brand(c, cfg.site_url, b["id"])
        ui.notify(f"Đã bỏ theo dõi {b['name']}", type="info", position="bottom-right", classes="sr-toast")
        refresh_all()

    def edit_brand(b: dict | None):
        if not ed:
            return
        with ui.dialog() as dlg, ui.card().style("min-width: 460px; max-width: 94vw; border-radius: 14px"):
            ui.label("Sửa thương hiệu" if b else "Thêm đối thủ").classes("text-lg font-semibold")
            name = ui.input("Tên", value=b["name"] if b else "").props("outlined dense").classes("w-full")
            aliases = ui.textarea("Cách gọi khác (mỗi dòng một cách)", value="\n".join(b["aliases"]) if b else ""
                                  ).props("outlined dense autogrow").classes("w-full")
            domains = ui.textarea("Tên miền (mỗi dòng một tên miền)", value="\n".join(b["domains"]) if b else ""
                                  ).props("outlined dense autogrow").classes("w-full")

            def save():
                try:
                    with connect() as c:
                        AO.save_brand(c, cfg.site_url, name.value or "", aliases.value or "", domains.value or "",
                                      b["id"] if b else None)
                except ValueError as e:
                    ui.notify(str(e), type="warning", position="bottom-right", classes="sr-toast")
                    return
                dlg.close()
                refresh_all()
                background_tasks.create(load_logos())
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Lưu", on_click=save).props("unelevated no-caps color=primary")
        dlg.open()

    def refresh_all():
        overview.refresh()
        keywords_view.refresh()
        brands_view.refresh()

    # ---- chọn bộ từ khóa: AI Overview đi theo bộ (cùng lần check rank) ----
    with connect() as c:
        from . import rank as R
        sets_ = [x for x in R.sets(c, cfg.site_url) if not x["draft"]]
    if state["set"] not in [x["id"] for x in sets_]:
        state["set"] = None
    if len(sets_) > 1:
        def pick_set(v):
            state["set"] = v or None
            refresh_all()
            ui.run_javascript(f"history.replaceState(null, '', '/aio' + ({v or 0} ? '?bo={v}' : ''))")
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            ui.label("Tính trên").classes("text-sm muted")
            ui.toggle({0: "Mọi bộ", **{x["id"]: x["name"] for x in sets_}}, value=state["set"] or 0,
                      on_change=lambda e: pick_set(e.value)).props(SEG).classes("sr-seg")

    # dựng sau khi đã định nghĩa các phần trên
    with ui.tabs().props("align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs") as sub:
        s_over = ui.tab("Tổng quan")
        s_todo = ui.tab("Việc nên làm")
        s_kw = ui.tab("Từ khóa")
        s_br = ui.tab("Thương hiệu & đối thủ")
    with ui.tab_panels(sub, value=s_br if start == "brands" else s_over).classes("w-full").props("animated=false"):
        with ui.tab_panel(s_over).classes("q-px-none"):
            overview()
        with ui.tab_panel(s_todo).classes("q-px-none"):
            opportunities(ui, connect, cfg)
        with ui.tab_panel(s_kw).classes("q-px-none"):
            keywords_view()
        with ui.tab_panel(s_br).classes("q-px-none"):
            brands_view()


def opportunities(ui, connect, cfg) -> None:
    """Việc nên làm: từ khóa có AI Overview mà website chưa được trích ở lần mới nhất; từ khóa top 10 trước."""
    site = cfg.site_url
    rows, s = load(connect, cfg)
    if not s["checked"]:
        T.empty_state(ui, "auto_awesome", "Chưa có số AI Overview", "Lần check rank tới sẽ có.")
        return
    todo = [r for r in rows if r["aio"] and r["cited"] is False]
    todo.sort(key=lambda r: (r["rank"] is None, r["rank"] or 999))
    with T.section(ui, f"AI Overview chưa trích website · {len(todo)} từ khóa", "auto_awesome",
                   f"{where_text(connect, cfg)} · lần check mới nhất. Từ khóa đang ở top 10 xếp trước: dễ được trích "
                   "nhất. Xem nội dung các website đang được trích để bổ sung trang của website dự án."):
        if not todo:
            ui.label("Không có: mọi từ khóa có AI Overview đều đang trích website.").classes("text-sm muted")
            return
        host = R.domain(site)
        for r in todo[:15]:
            others = list(dict.fromkeys(x["domain"] for x in r["refs"] if not R._host_match(x["domain"], host)))
            with ui.row().classes("w-full items-center no-wrap gap-3 sr-opp-row"):
                pos = (str(r["rank"]) if r["rank"] is not None else f">{r['depth']}") if r["depth"] else "–"
                ui.label(pos).classes("sr-mv-num sr-mv-now").style("min-width:36px").tooltip("Vị trí hiện tại")
                ui.label(r["keyword"]).classes("text-sm font-medium col ellipsis")
                if r["known_weeks"]:
                    ui.label(f"trích {r['cited_weeks']}/{r['known_weeks']} tuần").classes("text-xs muted").tooltip(
                        f"Trong {WEEKS} tuần gần nhất")
                ui.label(", ".join(others[:3]) or "–").classes("text-sm muted ellipsis").style(
                    "max-width:40%").tooltip("Website AI đang trích: " + (", ".join(others) or "–"))
        if len(todo) > 15:
            ui.label(f"+{len(todo) - 15} từ khóa khác ở tab Từ khóa").classes("text-xs muted")


def dashboard_lines(ui, connect, cfg) -> None:
    """Hai dòng cho ô Thứ hạng ở Tổng quan: AI Overview (4 tuần, có ghi đã kiểm tra bao nhiêu) và đối thủ hay gặp."""
    rows, s = load(connect, cfg)
    if not s["checked"]:
        return
    link = ui.link(target="/aio").classes("sr-cmp-note no-underline").style("color:inherit")
    with link:
        ui.html(f"AI Overview {WEEKS} tuần: website được trích <b>{_pct(s['cited_rate'])}</b> "
                f"({s['cited']}/{s['known']}) · đã kiểm tra {s['checked']}/{s['total']} từ khóa")
    link.tooltip(f"{where_text(connect, cfg)}. Bấm để mở trang AI Overview")
    with connect() as c:
        s2 = R.aio_summary(R.serp_latest(c, cfg.site_url, K.latest_date(c, cfg.site_url)), cfg.site_url)
    if s2["competitors"]:
        names = [d for d, *_ in s2["competitors"]]
        ui.html("Đối thủ hay gặp: " + ", ".join(f"<b>{d}</b>" for d in names[:2])).classes(
            "sr-cmp-note").tooltip("Top 10 trên bộ từ khóa: " + ", ".join(names))


def build_aio_page(ui, cfg, connect, user, start: str = "", set_id: int | None = None) -> None:
    """Trang AI Overview: tiêu đề + tab (Tổng quan · Việc nên làm · Từ khóa · Thương hiệu & đối thủ)."""
    from .access import can_edit
    right = T.page_header(ui, "tips_and_updates", "AI Overview",
                          "Thương hiệu trong câu trả lời AI của Google trên bộ từ khóa theo dõi. Lượt hiển thị và truy "
                          "cập từ AI (GSC, GA4) xem ở trang AI Search & GEO.")
    tab(ui, connect, cfg, can_edit(user), header=right, start=start, set_id=set_id, user_=user)
