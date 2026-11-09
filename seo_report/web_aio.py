"""Trang AI Overview (/aio): AI Overview của Google trên bộ từ khóa theo dõi, đọc từ kết quả check rank (DataForSEO).
Trang riêng, tách khỏi số GA4 / GSC ở AI Search & GEO để khách hàng dễ theo dõi; dòng tóm tắt ở Tổng quan.

Khác số của GSC (lượt hiển thị thật trong AI của Google): đây là ảnh chụp mỗi lần check. AI Overview hiện lúc có lúc
không và đổi nguồn trích giữa các lần tìm, nên các số chính tính theo tuần (lần check cuối của tuần), không so từng lần
với nhau. Mọi số ghi rõ nơi check (thiết bị, vùng) và đã kiểm tra bao nhiêu / tổng số từ khóa."""
from datetime import date, timedelta

from . import points as PT
from . import keywords as K
from . import rank as R
from . import ui_theme as T

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


def tab(ui, connect, cfg, ed: bool, header=None, start: str = "", set_id: int | None = None, user_=None,
        cl: bool = False) -> None:
    """cl: khách hàng: không chi phí, không tab Việc nên làm, không hướng dẫn sửa đối thủ."""
    """Nội dung trang AI Overview: dòng phạm vi + tab (Tổng quan · Việc nên làm · Từ khóa · Thương hiệu). Nút chọn
    khoảng thời gian đặt ở đầu trang (header) vì nó áp cho cả 4 thẻ và biểu đồ. Số từ kết quả check rank (DataForSEO),
    mỗi tuần lấy lần check cuối của tuần."""

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
                          "Lần check rank tới sẽ có." if cl or PT.member(user_) else
                          "Lần check rank tới sẽ có.")
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
                    # Tên thương hiệu do Member nhập: bắt buộc mã hoá HTML trước khi đưa vào tooltip (ECharts chèn chuỗi
                    # trả về từ formatter như HTML).
                    "tooltip": {"trigger": "axis", ":formatter": (
                        "ps => { const esc = s => String(s).replace(/[&<>\"']/g, "
                        "c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;'}[c])); "
                        "return esc(ps[0].axisValueLabel) + '<br/>' + ps.map(p => p.marker + esc(p.seriesName) + "
                        "': <b>' + (p.value == null ? '–' : p.value + '%') + '</b> (' + p.data.n + '/' + p.data.d + ')')"
                        ".join('<br/>'); }")},
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
                    for b in sorted(d["brands"], key=lambda b: (not b["own"], -(point(last, b)["value"] or 0))):
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
                    ui.label("Biểu đồ vẽ thương hiệu của bạn và các đối thủ chính."
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
            ui.label("So lần check mới nhất với lần trước."
                     ).classes("text-xs muted")
            items = ch[state["change"]]
            if not items:
                ui.label("Không có từ khóa nào." if len(d["weeks"]) > 1 else
                         "Cần ít nhất 2 lần check của cùng từ khóa để so sánh.").classes("text-sm muted q-mt-sm")
            for x in items:
                with ui.row().classes("w-full items-center no-wrap gap-3 sr-opp-row"):
                    ui.label(x["keyword"]).classes("text-sm col ellipsis sr-kw-link").props(
                        'role=button tabindex=0').on("click", lambda _, k=x["keyword"]: open_kw(k))
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
        flt = {"all": ("Tất cả", lambda r: True), "aio": ("Có AI Overview", lambda r: r["aio"]),
               "nocite": ("Chưa được trích", lambda r: r["aio"] and not r["own_cited"]),
               "rival": ("Đối thủ được trích", lambda r: r["aio"] and len(r["cited"]) > (1 if r["own_cited"] else 0)),
               "cited": ("Đang được trích", lambda r: r["own_cited"])}
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            ui.toggle({k: f"{v[0]} · {sum(1 for r in rows if v[1](r))}" for k, v in flt.items()},
                      value=state.get("kw_f", "all"),
                      on_change=lambda e: (state.update(kw_f=e.value), keywords_view.refresh())).props(SEG).classes(
                "sr-seg")
            ui.space()
            kq = ui.input(placeholder="Tìm từ khóa").props("outlined dense clearable").classes("sr-aa-search")
        rows = [r for r in rows if flt[state.get("kw_f", "all")][1](r)]
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
        ], rows=trows, row_key="id", pagination=25).classes("w-full sr-aio-table").props("flat dense")
        kq.bind_value_to(t, "filter")
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
            if r["aio"]:
                with ui.element("div").classes("sr-aa-facts"):
                    for lb, names in (("AI nhắc tên", r["mentioned"]), ("AI trích link", r["cited"])):
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.label(lb).classes("text-xs muted").style("min-width:84px")
                            with ui.element("div").classes("sr-aa-chips"):
                                for n_ in names:
                                    ui.label(n_).classes("sr-aa-chip")
                                if not names:
                                    ui.label("không thương hiệu nào đã khai báo").classes("text-xs muted")
            if not r["aio"]:
                ui.label("Google không hiện AI Overview cho từ khóa này.").classes("text-sm muted")
            else:
                _h2(ui, "Nội dung AI trả lời").style("font-size:14px")
                if r["text"]:
                    ui.label(r["text"]).classes("sr-aio-text")
                else:
                    ui.label("Lần check này chưa lưu nội dung chữ (lần check tới sẽ có).").classes("text-sm muted")
                if ed and not cl:
                    def write_it(r=r):
                        from .web_ai_write import answer_dialog
                        with connect() as c:
                            k = next((x for x in R.keywords(c, cfg.site_url, K.latest_date(c, cfg.site_url))
                                      if x["id"] == r["id"]), {})
                        answer_dialog(ui, connect, cfg, user_, r["id"], r["keyword"],
                                      k.get("ranking_url") or k.get("target_url") or "", r.get("text", ""),
                                      r.get("refs", []))
                    ui.button("AI viết đoạn trả lời", icon="auto_fix_high", on_click=write_it).props(
                        "unelevated no-caps dense").classes("sr-aw-btn q-mt-xs")
                ui.label(f"Nguồn AI trích · {len(r['refs'])}").classes("sr-section-title q-mt-sm").style(
                    "font-size:14px")
                for x in r["refs"]:
                    me = R._host_match(x["domain"], host)
                    with ui.row().classes("w-full items-center no-wrap gap-2 sr-serp-row" + (" me" if me else "")):
                        ui.label(x["domain"]).classes("text-sm font-medium").style("min-width:160px")
                        lk = ui.link(x["title"] or x["url"], x["url"], new_tab=True).classes("text-sm ellipsis col")
                        lk.props["title"] = x["url"]
        dlg.open()

    def open_kw(keyword: str) -> None:
        with connect() as c:
            r = next((x for x in AO.keyword_rows(c, cfg, state["set"]) if x["keyword"] == keyword), None)
        if r:
            show_text(r)

    def avatar(b: dict) -> None:
        """Logo website (tự lấy khi thêm); chưa có logo: chữ cái đầu theo màu thương hiệu."""
        with ui.element("span").classes("sr-brand-logo"):
            if b.get("logo"):
                ui.html(f'<img src="{b["logo"]}" alt="">')
            else:
                ui.label((b["name"] or "?")[:1].upper()).style(f"color:{b['color']}")

    def refresh_all():
        overview.refresh()
        keywords_view.refresh()
        if state.get("audit_refresh"):
            state["audit_refresh"]()

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
        if cl:  # việc của team SEO, không đưa cho khách
            s_todo.set_visibility(False)
        s_kw = ui.tab("Từ khóa")
        s_ai = ui.tab("Bản AI")
        if cl:  # bản AI viết là việc của team
            s_ai.set_visibility(False)
    # Thương hiệu & đối thủ (tên, cách gọi, tên miền) quản lý ở trang Đối thủ, dùng chung với thứ hạng
    first = {"viec": None if cl else s_todo, "tu-khoa": s_kw, "ban-ai": None if cl else s_ai}.get(start) or s_over  # ?tab= (từ menu trái)
    sub.set_value(first)
    with ui.tab_panels(sub, value=first).classes("w-full").props("animated=false"):
        with ui.tab_panel(s_over).classes("q-px-none"):
            overview()
        with ui.tab_panel(s_todo).classes("q-px-none"):
            if not cl:
                audit_view(ui, connect, cfg, state, show_text, user_)
        with ui.tab_panel(s_kw).classes("q-px-none"):
            keywords_view()
        with ui.tab_panel(s_ai).classes("q-px-none"):
            if not cl:
                from .web_ai_library import AIO_KINDS, build_ai_library
                ui.label("Đoạn trả lời AI Overview đã viết: xem lại, sao chép hoặc xóa.").classes(
                    "text-sm muted q-mb-sm")
                build_ai_library(ui, cfg, connect, user_, kinds=AIO_KINDS, header=False)


SEV_ICON = {"high": "priority_high", "medium": "error_outline", "low": "info_outline"}


def _path(url: str) -> str:
    from urllib.parse import urlparse
    if not url:
        return ""
    p = urlparse(url)
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def audit_xlsx(a: dict, site: str) -> bytes:
    """Excel gợi ý audit: mỗi dòng một từ khóa, kèm mức, vấn đề, việc nên làm."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from . import aio as AO
    wb = Workbook()
    ws = wb.active
    ws.title = "Gợi ý audit AIO"
    head = ["Mức", "Vấn đề", "Từ khóa", "Volume", "Vị trí", "Trang của website", "Đối thủ được trích",
            "Nguồn AI trích", "Nên làm"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="F3F3ED")
    for g in a["groups"]:
        todo = " | ".join(g["actions"])
        for x in g["items"]:
            ws.append([AO.SEVERITY[g["severity"]], g["title"], x["keyword"], x["volume"],
                       x["rank"] if x["rank"] is not None else (f">{x['depth']}" if x["depth"] else ""),
                       x["url"], ", ".join(x["rivals_cited"]), ", ".join(x["sources"][:5]), todo])
    for col, w in zip("ABCDEFGHI", (11, 34, 34, 10, 8, 50, 30, 46, 80)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def audit_view(ui, connect, cfg, state: dict, show_text, user_=None) -> None:
    """Tab Việc nên làm: gợi ý audit AI Overview. Thanh sức khỏe (bao nhiêu từ khóa ổn / cần sửa theo mức), thẻ từng
    nhóm vấn đề (bấm để xem), khung chi tiết: vì sao, nên làm gì, danh sách từ khóa (bấm xem AI trả lời)."""
    from . import aio as AO
    from . import access as A_
    from . import web_ai_write as WW
    ui_state = {"key": None, "q": ""}
    can_write = A_.can_edit(user_)

    @ui.refreshable
    def view() -> None:
        with connect() as c:
            a = AO.audit(c, cfg, state["set"])
        groups = a["groups"]
        if not a["aio"]:
            T.empty_state(ui, "auto_awesome", "Chưa có số AI Overview", "Lần check rank tới sẽ có.")
            return
        by_sev = {s: sum(len(g["items"]) for g in groups if g["severity"] == s) for s in AO.SEVERITY}
        if ui_state["key"] not in {g["key"] for g in groups if g["items"]}:
            ui_state["key"] = next((g["key"] for g in groups if g["items"]), None)

        # ---- thanh sức khỏe: từ khóa có AI Overview chia theo ổn / mức vấn đề ----
        with ui.element("div").classes("sr-card q-pa-md w-full"):
            with ui.row().classes("w-full items-end no-wrap gap-3"):
                with ui.column().classes("gap-0 col"):
                    _h2(ui, "Sức khỏe AI Overview")
                    ui.label(f"{a['aio']} từ khóa có AI Overview ở lần check mới nhất · {where_text(connect, cfg)}"
                             ).classes("text-xs muted")
                ui.html(f'<div class="sr-aa-big num">{a["good"]}<span>/{a["aio"]} ổn</span></div>')
            parts = [("good", a["good"], "Được trích và nhắc tên")] + [
                (s, by_sev[s], f"Mức {AO.SEVERITY[s].lower()}") for s in AO.SEVERITY]
            tot = max(a["aio"], 1)
            bar = "".join(f'<i class="{k}" style="width:{n / tot * 100:.2f}%"></i>' for k, n, _ in parts if n)
            ui.html(f'<div class="sr-aa-bar" role="img" aria-label="'
                    + "; ".join(f"{lb}: {n}" for _, n, lb in parts) + f'">{bar}</div>')
            with ui.row().classes("gap-4 sr-aa-legend"):
                for k, n, lb in parts:
                    ui.html(f'<span><b class="{k}"></b>{lb} <span class="num">{n}</span></span>')

        # ---- thẻ nhóm vấn đề ----
        with ui.element("div").classes("sr-aa-cards q-mt-md"):
            for g in groups:
                n = len(g["items"])
                on = g["key"] == ui_state["key"]
                card = ui.element("div").classes(f"sr-aa-card {g['severity']}" + (" on" if on else "")
                                                 + ("" if n else " empty")).props(
                    f'role=button tabindex=0 aria-pressed={"true" if on else "false"}')
                with card:
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon(SEV_ICON[g["severity"]], size="15px").classes("sr-aa-ico")
                        ui.label(AO.SEVERITY[g["severity"]]).classes("sr-aa-sev")
                    ui.label(f"{n:,}".replace(",", ".")).classes("sr-aa-num num")
                    ui.label(g["title"]).classes("sr-aa-title")
                if n:
                    card.on("click", lambda _, k=g["key"]: pick(k))
                    card.on("keydown.enter", lambda _, k=g["key"]: pick(k))

        g = next((x for x in groups if x["key"] == ui_state["key"]), None)
        if not g:
            with ui.element("div").classes("sr-card q-pa-md q-mt-md w-full"):
                ui.label("Không còn vấn đề nào: mọi từ khóa có AI Overview đều đang trích và nhắc tên website."
                         ).classes("text-sm")
            return
        detail(g)

    def detail(g: dict) -> None:
        from . import aio as AO
        with ui.element("div").classes(f"sr-card q-mt-md w-full sr-aa-detail {g['severity']}"):
            with ui.element("div").classes("sr-aa-dhead"):
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.label(AO.SEVERITY[g["severity"]]).classes(f"sr-aa-pill {g['severity']}")
                    _h2(ui, f"{g['title']} · {len(g['items'])} từ khóa")
                ui.label(g["why"]).classes("text-sm q-mt-xs").style("color:#3A3A33")
                ui.label("Nên làm").classes("sr-aa-todo-h")
                ui.html('<ol class="sr-aa-todo">' + "".join(f"<li>{t_}</li>" for t_ in g["actions"]) + "</ol>")
            with ui.row().classes("w-full items-center gap-2 q-px-md q-pt-md"):
                q = ui.input(placeholder="Tìm từ khóa", value=ui_state["q"]).props(
                    "outlined dense clearable debounce=250").classes("sr-aa-search")
                q.on_value_change(lambda e: (ui_state.update(q=e.value or ""), table.refresh()))
                ui.space()
                ui.label("Bấm từ khóa để xem AI Overview trả lời gì và trích những ai").classes("text-xs muted gt-sm")

            def write(x: dict) -> None:
                from .web_ai_write import answer_dialog
                answer_dialog(ui, connect, cfg, user_, x["id"], x["keyword"], x["url"], x["row"].get("text", ""),
                              x["row"].get("refs", []), g["title"], on_saved=table.refresh)

            @ui.refreshable
            def table() -> None:
                qq = ui_state["q"].strip().lower()
                drafted = WW.has_draft(connect, cfg, [x["id"] for x in g["items"]]) if can_write else set()
                items = [x for x in g["items"] if not qq or qq in x["keyword"].lower()]
                rows = [{"id": x["id"], "keyword": x["keyword"],
                         "volume": x["volume"] if x["volume"] is not None else -1,
                         "pos": x["rank"] if x["rank"] is not None else 999,
                         "pos_t": str(x["rank"]) if x["rank"] is not None else
                         (f">{x['depth']}" if x["depth"] else "–"),
                         "page": _path(x["url"]), "url": x["url"],
                         "rivals": x["rivals_cited"] or x["rivals_mentioned"],
                         "rivals_kind": "trích" if x["rivals_cited"] else ("nhắc" if x["rivals_mentioned"] else ""),
                         "sources": ", ".join(x["sources"][:4]) or "–", "n_src": len(x["sources"]),
                         "drafted": x["id"] in drafted}
                        for x in items]
                t = ui.table(columns=[
                    {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
                    {"name": "volume", "label": "Volume", "field": "volume", "align": "right", "sortable": True,
                     "headerStyle": "width:90px"},
                    {"name": "pos", "label": "Vị trí", "field": "pos", "align": "right", "sortable": True,
                     "headerStyle": "width:72px"},
                    {"name": "page", "label": "Trang của website", "field": "page", "align": "left"},
                    {"name": "rivals", "label": "Đối thủ AI trích / nhắc", "field": "rivals", "align": "left"},
                    {"name": "sources", "label": "Nguồn AI trích", "field": "sources", "align": "left"},
                    *([{"name": "ai", "label": "", "field": "drafted", "align": "right",
                        "headerStyle": "width:150px"}] if can_write else []),
                ], rows=rows, row_key="id", pagination={"rowsPerPage": 15, "sortBy": "volume", "descending": True}
                ).props("flat dense").classes("w-full sr-aa-table")
                t.add_slot("body-cell-keyword", """
                    <q-td :props="props"><span class="sr-kw-link" role="button" tabindex="0"
                      @click="$parent.$emit('open', props.row)" @keydown.enter="$parent.$emit('open', props.row)">
                      {{ props.value }}</span></q-td>""")
                t.add_slot("body-cell-volume", """
                    <q-td :props="props" class="num">{{ props.value < 0 ? '–' :
                      props.value.toLocaleString('vi-VN') }}</q-td>""")
                t.add_slot("body-cell-pos", """
                    <q-td :props="props" class="num">{{ props.row.pos_t }}</q-td>""")
                t.add_slot("body-cell-page", """
                    <q-td :props="props"><a v-if="props.row.url" :href="props.row.url" target="_blank"
                      class="sr-aa-page ellipsis" :title="props.row.url">{{ props.value }}</a>
                      <span v-else class="muted">Chưa có trang xếp hạng</span></q-td>""")
                t.add_slot("body-cell-rivals", """
                    <q-td :props="props"><div class="sr-aa-chips">
                      <span v-for="r in props.value.slice(0, 2)" :key="r" class="sr-aa-chip">{{ r }}</span>
                      <span v-if="props.value.length > 2" class="muted text-xs"
                        :title="props.value.join(', ')">+{{ props.value.length - 2 }}</span>
                      <span v-if="!props.value.length" class="muted">–</span>
                      <span v-else class="muted text-xs">{{ props.row.rivals_kind }}</span></div></q-td>""")
                t.add_slot("body-cell-sources", """
                    <q-td :props="props"><div class="ellipsis sr-aa-src" :title="props.value">{{ props.value }}
                      </div></q-td>""")
                by_id = {x["id"]: x["row"] for x in items}
                t.on("open", lambda e: show_text(by_id[e.args["id"]]))
                if can_write:
                    t.add_slot("body-cell-ai", """
                        <q-td :props="props">
                          <q-btn dense no-caps unelevated size="sm" :icon="props.value ? 'description' : 'auto_fix_high'"
                            :label="props.value ? 'Xem bản nháp' : 'Viết đoạn trả lời'"
                            :class="props.value ? 'sr-aw-btn done' : 'sr-aw-btn'"
                            @click="$parent.$emit('write', props.row)" /></q-td>""")
                    items_by = {x["id"]: x for x in items}
                    t.on("write", lambda e: write(items_by[e.args["id"]]))
                if not rows:
                    ui.label("Không có từ khóa khớp.").classes("text-sm muted q-pa-md")
            with ui.element("div").classes("q-px-md q-pb-md"):
                table()

    def pick(k: str) -> None:
        ui_state.update(key=k, q="")
        view.refresh()

    with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
        ui.label("Mỗi từ khóa nằm ở nhóm vấn đề quan trọng nhất của nó.").classes(
            "text-xs muted col")
        from datetime import date as _d

        from .web_export import export_menu

        def make_xlsx() -> bytes:
            from . import aio as AO
            with connect() as c:
                return audit_xlsx(AO.audit(c, cfg, state["set"]), cfg.site_url)
        export_menu(ui, cfg, connect, f"aio-goi-y-audit_{_d.today():%Y-%m-%d}", make_xlsx,
                    label="Xuất gợi ý audit AI Overview", user=user_, category="aio")
    view()
    state["audit_refresh"] = view.refresh


def dashboard_lines(ui, connect, cfg) -> None:
    """Hai dòng cho ô Thứ hạng ở Tổng quan: AI Overview (4 tuần, có ghi đã kiểm tra bao nhiêu) và đối thủ hay gặp."""
    rows, s = load(connect, cfg)
    if not s["checked"]:
        return
    from . import dash_widgets as W
    W.fact(ui, "lightbulb", "purple", f"AI Overview {WEEKS} tuần",
           f"được trích <b>{_pct(s['cited_rate'])}</b> ({s['cited']}/{s['known']})", "/aio",
           f"Website được trích trong câu trả lời AI Overview: {s['cited']}/{s['known']} từ khóa có AI Overview · đã "
           f"kiểm tra {s['checked']}/{s['total']} từ khóa · {where_text(connect, cfg)}")
    competitor_line(ui, connect, cfg)


def competitor_line(ui, connect, cfg) -> None:
    """Đối thủ hay gặp trong top 10 của bộ từ khóa. Đã khai báo đối thủ (màn Đối thủ) thì đếm theo danh sách đó; chưa
    khai báo thì lấy tên miền hay gặp nhưng bỏ các nền tảng (Facebook, Shopee, YouTube…: không phải đối thủ)."""
    from . import aio as AO
    from .rank_overview import PLATFORMS
    with connect() as c:
        rows = R.serp_latest(c, cfg.site_url, K.latest_date(c, cfg.site_url))
        rivals = [b for b in AO.brands(c, cfg) if not b["own"] and b["domains"]]
    host = R.domain(cfg.site_url) if hasattr(R, "domain") else ""
    checked = [r for r in rows if r.get("top10")]
    if not checked:
        return
    if rivals:
        count = []
        for b in rivals:
            n = sum(1 for r in checked if any(R._host_match(x["domain"] or "", d) for x in r["top10"]
                                               for d in b["domains"]))
            if n:
                count.append((b["name"], n))
        count.sort(key=lambda x: -x[1])
        from . import dash_widgets as W
        W.fact(ui, "groups", "amber", "Đối thủ trong top 10",
               " · ".join(f"<b>{name}</b> {n}" for name, n in count[:2]) if count else "chưa có",
               "/doi-thu", f"Số từ khóa (trên {len(checked)} từ khóa, lần check mới nhất) có đối thủ trong top 10: "
               + (", ".join(f"{name} {n}" for name, n in count) if count
                  else f"chưa đối thủ nào trong {len(rivals)} đối thủ đã khai báo"))
        return
    count: dict[str, int] = {}
    for r in checked:
        for d in {x["domain"] for x in r["top10"] if x["domain"]}:
            if (host and R._host_match(d, host)) or any(R._host_match(d, p) for p in PLATFORMS):
                continue
            count[d] = count.get(d, 0) + 1
    top = sorted(count.items(), key=lambda x: (-x[1], x[0]))[:3]
    if top:
        from . import dash_widgets as W
        W.fact(ui, "groups", "amber", "Hay gặp trong top 10", " · ".join(f"<b>{d}</b> {n}" for d, n in top[:2]),
               "/doi-thu", "Chưa khai báo đối thủ; đã bỏ các nền tảng (Facebook, Shopee, YouTube…). Số từ khóa có "
               "mặt ở top 10: " + ", ".join(f"{d} {n}" for d, n in top))


def build_aio_page(ui, cfg, connect, user, start: str = "", set_id: int | None = None) -> None:
    """Trang AI Overview: tiêu đề + tab (Tổng quan · Việc nên làm · Từ khóa · Thương hiệu & đối thủ)."""
    from .access import can_edit, is_client
    right = T.page_header(ui, "tips_and_updates", "AI Overview",
                          "Thương hiệu của bạn và đối thủ được AI của Google nhắc tên, trích link bao nhiêu.")
    tab(ui, connect, cfg, can_edit(user), header=right, start=start, set_id=set_id, user_=user,
        cl=is_client(user))
