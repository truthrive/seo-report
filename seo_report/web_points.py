"""Trang Credit của tôi (/diem): credit tháng này còn bao nhiêu, bị trừ ở tác vụ nào, lúc nào, ở website nào; bảng credit
từng tác vụ. Member có hạn mức; Owner / Admin không giới hạn nhưng vẫn xem được các tác vụ mình đã chạy."""
from datetime import date, datetime, timedelta

from . import access as A
from . import points as PT
from . import ui_theme as T

UNIT = {"rank": "mỗi từ khóa", "aio": "mỗi từ khóa", "serp": "mỗi từ khóa", "volume": "mỗi lần thêm"}
NOTE = {"rank": "Bấm Check ngay. Check theo lịch của bộ không trừ credit.",
        "aio": "Trang Ý tưởng từ khóa; từ khóa đã có số không tính.",
        "serp": "Trang Tổng quan từ khóa.",
        "backlink": "Bấm Lấy số mới: số tổng, lịch sử và các danh sách. Lịch tự lấy không trừ credit.",
        "research": "Mỗi lần tìm ở trang Ý tưởng từ khóa.",
        "overview": "Chỉ khi phải gọi Google Ads; xem lại từ khóa đã phân tích trong 7 ngày không tính.",
        "volume": "Khi thêm từ khóa vào bộ theo dõi hạng.",
        "audit": "Bấm Quét ngay ở Cơ hội SEO. Lịch quét hằng tuần không trừ credit.",
        "pagespeed": "Bấm kiểm tra ở trang Tốc độ trang.",
        "local": "Bấm Lấy số mới ở trang Local SEO.",
        "merchant": "Bấm Lấy số mới ở trang Merchant Center.",
        "kg": "Bấm Kiểm tra ngay ở tab Brand Entity (SEO Opportunities).",
        "sheets": "Lưu file lên Google Sheets / Drive. Tải Excel về máy không tính.",
        "ai_aio": "Bấm Viết bằng AI / Viết lại ở AI Overview > Việc nên làm. Xem lại bản đã viết không tính.",
        "ai_page_gap": "Bấm Viết đoạn còn thiếu ở SEO Opportunities › Striking Distance. Xem lại bản đã viết không tính.",
        "ai_report": "Bấm AI viết nháp ở khối Nhận xét & kết luận của trang Báo cáo.",
        "ai_brief": "Bấm AI phân tích / Cập nhật ở Bản tin AI đầu trang Tổng quan. Mở trang xem bản đã có không tính.",
        "ai_plan": "Tick từ khóa ở Ý tưởng từ khóa rồi bấm AI lập chiến lược (tối đa 80 từ khóa một lần).",
        "ai_kwbrief": "Bấm AI viết brief ở Tổng quan từ khóa. Xem lại brief đã viết không tính.",
        "ai_kpi": "Bấm AI đọc sheet cam kết ở trang Sửa cam kết KPI.",
        "ai_kpi_insight": "Bấm AI nhận định ở đầu trang Cam kết KPI. Xem lại bản đã viết không tính.",
        "ai_rank_insight": "Bấm AI nhận định ở một bộ của trang Thứ hạng từ khóa. Xem lại bản đã viết không tính.",
        "ai_rank_diag": "Bấm AI chẩn đoán trong chi tiết một từ khóa (trang Thứ hạng).",
        "ai_rank_target": "Bấm AI gợi ý URL mục tiêu ở bảng từ khóa (tối đa 60 từ khóa một lần).",
        "ai_rank_actions": "Tick từ khóa rồi bấm AI việc cần làm (tối đa 15 từ khóa một lần).",
        "backlink_gap": "Mỗi đối thủ một lần khi bấm Tìm backlink GAP ở trang Backlink. Xem lại kết quả không tính.",
        "backlink_gap_multi": "Một lần cho cả nhóm đối thủ khi tìm Backlink GAP ở chế độ Nhanh.",
        "backlink_gap_links": "Mỗi đối thủ một lần khi bấm Lấy link của một website trong Backlink GAP. Xem lại không tính."}


def _n(v) -> str:
    return f"{v:,}".replace(",", ".")


def _months(n: int = 6) -> list[str]:
    d = date.today().replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    return out


def build_points_page(ui, app_connect, user) -> None:
    member = A.is_member(user)
    T.page_header(ui, "toll", "Credit của tôi",
                  "Credit còn lại tháng này và những việc đã dùng credit. Ngày 1 hằng tháng đặt lại." if member else
                  "Các việc bạn đã chạy trong tháng (Owner / Admin không giới hạn credit).",
                  eyebrow="Tài khoản")
    months = _months()
    state = {"month": months[0]}

    @ui.refreshable
    def body() -> None:
        m = state["month"]
        with app_connect() as c:
            PT.ensure(c)
            bal = PT.balance(c, str(user), m)
            rows = PT.history(c, str(user), m)
            gr = PT.grants(c, str(user), m)
        acts = PT.by_action(rows)
        spent = sum(r["points"] for r in rows)

        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            ui.toggle({x: f"Th{int(x[5:])}/{x[:4]}" for x in months}, value=m,
                      on_change=lambda e: (state.update(month=e.value), body.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")

        with T.kpi_row(ui):
            if member:
                ratio = bal["used"] / bal["limit"] if bal["limit"] else 1
                tone = "red" if ratio >= 1 else "amber" if ratio >= 0.8 else "green"
                T.kpi(ui, "toll", "Còn lại", _n(bal["left"]), hint=f"trên {_n(bal['limit'])} credit", tone=tone)
                T.kpi(ui, "bolt", "Đã dùng", _n(bal["used"]), hint=f"{ratio * 100:.0f}% hạn mức", tone="blue")
                T.kpi(ui, "event_repeat", "Hạn mức tháng", _n(bal["monthly"]),
                      hint=(f"+ {_n(bal['granted'])} credit cấp thêm" if bal["granted"] else "đặt lại ngày 1"),
                      tone="lime")
            else:
                T.kpi(ui, "all_inclusive", "Hạn mức", "Không giới hạn", hint=A.GROUPS[A.group(user)], tone="lime")
                T.kpi(ui, "bolt", "Đã chạy", _n(spent) + " credit", hint=f"{len(rows)} tác vụ", tone="blue")
            T.kpi(ui, "receipt_long", "Số lần trừ", _n(len(rows)), hint=f"{len(acts)} loại tác vụ", tone="grey")

        with T.section(ui, "Theo tác vụ", "donut_small", "Credit đã dùng tháng này, tách theo loại tác vụ"):
            if not acts:
                ui.label("Tháng này chưa dùng credit nào.").classes("text-sm muted")
            else:
                ui.table(columns=[
                    {"name": "name", "label": "Tác vụ", "field": "name", "align": "left"},
                    {"name": "times", "label": "Số lần", "field": "times", "align": "right"},
                    {"name": "points", "label": "Credit", "field": "points", "align": "right", "sortable": True,
                     ":format": "v => v.toLocaleString('vi-VN')"},
                    {"name": "pct", "label": "Tỷ lệ", "field": "pct", "align": "right"},
                ], rows=[{**a, "pct": f"{a['points'] / spent * 100:.0f}%" if spent else "–"} for a in acts],
                    row_key="action").props("flat dense").classes("w-full sr-bl-table")

        with T.section(ui, "Lịch sử trừ credit", "history", "Từng lần trừ credit, mới nhất trước"):
            if not rows:
                ui.label("Chưa có.").classes("text-sm muted")
            else:
                data = [{"id": i, "at": f"{datetime.fromisoformat(r['at']).astimezone():%d/%m %H:%M}",
                         "name": r["name"], "project": r["project"], "detail": r["detail"] or "–",
                         "points": r["points"]} for i, r in enumerate(rows)]
                ui.table(columns=[
                    {"name": "at", "label": "Lúc", "field": "at", "align": "left"},
                    {"name": "name", "label": "Tác vụ", "field": "name", "align": "left"},
                    {"name": "project", "label": "Website", "field": "project", "align": "left"},
                    {"name": "detail", "label": "Chi tiết", "field": "detail", "align": "left"},
                    {"name": "points", "label": "Credit", "field": "points", "align": "right",
                     ":format": "v => '−' + v.toLocaleString('vi-VN')"},
                ], rows=data, row_key="id", pagination=20).props("flat dense").classes("w-full sr-bl-table")

        if gr:
            with T.section(ui, "Credit cấp thêm", "add_card", "Owner / Admin cấp thêm trong tháng này"):
                for g in gr:
                    ui.label(f"+{_n(g['points'])} credit · {datetime.fromisoformat(g['at']).astimezone():%d/%m %H:%M} "
                             + (f"· {g['note']}" if g["note"] else "")).classes("text-sm")

        with T.section(ui, "Bảng credit", "price_change", "Mỗi tác vụ trừ bao nhiêu credit"):
            ui.table(columns=[
                {"name": "name", "label": "Tác vụ", "field": "name", "align": "left"},
                {"name": "points", "label": "Credit", "field": "points", "align": "right"},
                {"name": "unit", "label": "Tính theo", "field": "unit", "align": "left"},
                {"name": "note", "label": "Khi nào trừ", "field": "note", "align": "left"},
            ], rows=[{"action": k, "name": v[0], "points": PT.rank_points([20]) if k == "rank" else v[1],
                      "unit": UNIT.get(k, "mỗi lần"),
                      "note": NOTE.get(k, "")} for k, v in PT.COSTS.items()],
                row_key="action").props("flat dense").classes("w-full sr-bl-table")
            ui.label("Việc lỗi được hoàn credit. Hết credit: nhờ Owner hoặc Admin cấp thêm.").classes("text-xs muted q-mt-xs")

    body()
    calculator(ui, user)


CALC_GROUPS = (
    ("Từ khóa", (("aio", "Check AIO", "từ khóa"), ("serp", "Xem kết quả Google", "từ khóa"),
                 ("research", "Research từ khóa", "lần"), ("overview", "Tổng quan từ khóa mới", "từ khóa"),
                 ("volume", "Thêm từ khóa vào bộ", "lần"), ("ai_aio", "AI viết đoạn trả lời AIO", "lần"),
                 ("ai_page_gap", "AI viết đoạn còn thiếu cho trang", "lần"),
                 ("ai_plan", "AI lập chiến lược SEO", "lần"), ("ai_kwbrief", "AI viết brief từ khóa", "lần"),
                 ("ai_kpi_insight", "AI nhận định KPI", "lần"), ("ai_rank_insight", "AI nhận định thứ hạng", "lần"),
                 ("ai_rank_diag", "AI chẩn đoán từ khóa", "lần"), ("ai_rank_target", "AI gợi ý URL mục tiêu", "lần"),
                 ("ai_rank_actions", "AI việc cần làm theo từ khóa", "lần"))),
    ("Website và báo cáo", (("backlink", "Lấy số backlink", "lần"), ("audit", "Quét audit kỹ thuật", "lần"),
                            ("pagespeed", "Lấy số tốc độ trang", "lần"), ("local", "Lấy số Local SEO", "lần"),
                            ("merchant", "Lấy số Merchant Center", "lần"), ("kg", "Kiểm tra Knowledge Graph", "lần"),
                            ("sheets", "Lưu Google Sheets / Drive", "lần"),
                            ("ai_report", "AI viết nhận xét báo cáo", "lần"),
                            ("ai_brief", "AI bản tin Tổng quan", "lần"))),
)
CALC_ROWS = tuple(r for _, rows in CALC_GROUPS for r in rows)


def _summary_html(r: dict, member: bool, bal: dict | None) -> str:
    """Khối Dự tính bên phải: tổng, thanh hạn mức (đã dùng + lần này), các dòng có số, còn lại / thiếu."""
    total = r["total"]
    names = {k: n for k, n, _ in CALC_ROWS} | {"rank": "Check rank"}
    lines = "".join(f'<div class="sr-pt-sline"><span>{names[k]}</span><span class="num">{_n(p)}</span></div>'
                    for k, _, _, p in r["lines"] if p)
    if not lines:
        lines = '<div class="sr-pt-sempty">Nhập số từ khóa hoặc số lần ở bên trái.</div>'
    if member and bal:
        lim, used = max(bal["limit"], 1), bal["used"]
        left = bal["left"] - total
        over = left < 0
        u = min(used / lim, 1) * 100
        t = min(total / lim, 1 - u / 100) * 100 if not over else 100 - u
        bar = (f'<div class="sr-pt-bar" role="img" aria-label="Đã dùng {_n(used)}, lần này {_n(total)}, '
               f'hạn mức {_n(bal["limit"])} credit"><i class="used" style="width:{u:.1f}%"></i>'
               f'<i class="now{" over" if over else ""}" style="left:{u:.1f}%;width:{t:.1f}%"></i></div>'
               f'<div class="sr-pt-legend"><span><b class="used"></b>Đã dùng {_n(used)}</span>'
               f'<span><b class="now{" over" if over else ""}"></b>Lần này {_n(total)}</span>'
               f'<span>Hạn mức {_n(bal["limit"])}</span></div>')
        foot = (f'<div class="sr-pt-after bad">Thiếu {_n(-left)} credit. Tháng này còn {_n(bal["left"])} credit; '
                'bớt số lượng hoặc nhờ Owner / Admin cấp thêm.</div>' if over else
                f'<div class="sr-pt-after">Còn lại sau khi chạy<span class="num">{_n(left)}</span></div>')
    else:
        bar = ""
        usd = f"{total * PT.POINT_USD:.3f}".replace(".", ",")
        foot = (f'<div class="sr-pt-after">Owner / Admin không giới hạn credit<span class="num">≈ {usd} USD</span>'
                '</div>' if total else
                '<div class="sr-pt-after">Owner / Admin không giới hạn credit</div>')
    return (f'<div class="sr-pt-slabel">Dự tính</div>'
            f'<div class="sr-pt-big"><span class="num">{_n(total)}</span> credit</div>{bar}'
            f'<div class="sr-pt-slines">{lines}</div>{foot}')


def calculator(ui, user, framed: bool = True) -> None:
    """Máy tính credit: nhập số từ khóa / số lần để biết trước bị trừ bao nhiêu credit và còn lại bao nhiêu."""
    member = A.is_member(user)
    blank = {"rank_keywords": 0, "rank_depth": 20, "rank_times": 1, **{k: 0 for k, _, _ in CALC_ROWS}}
    st = dict(blank)
    inputs, subs = {}, {}

    def num(key, value, suffix, step=1):
        return ui.number(value=value, min=0, step=step, format="%.0f",
                         on_change=lambda e: upd(key, e.value)).props(
            f'outlined dense hide-bottom-space suffix="{suffix}" input-class="text-right"').classes("sr-pt-in")

    from contextlib import nullcontext
    with (T.section(ui, "Máy tính credit", "calculate", "Biết trước một việc trừ bao nhiêu credit.")
          if framed else nullcontext()):
        with ui.element("div").classes("sr-pt-wrap"):
            with ui.element("div").classes("sr-pt-main"):
                with ui.element("div").classes("sr-pt-rank"):
                    with ui.row().classes("w-full items-start no-wrap gap-2"):
                        ui.icon("leaderboard", size="20px").classes("sr-pt-rico")
                        with ui.column().classes("gap-0 col"):
                            ui.label("Check rank").classes("sr-pt-rname")
                            ui.label("Bấm Check ngay · 1 credit mỗi 10 kết quả của độ sâu").classes("text-xs muted")
                        subs["rank"] = ui.label("0").classes("num sr-pt-sub")
                    with ui.element("div").classes("sr-pt-rgrid"):
                        with ui.column().classes("gap-1"):
                            ui.label("Số từ khóa").classes("sr-pt-flabel")
                            inputs["rank_keywords"] = num("rank_keywords", 0, "từ khóa", 10)
                        with ui.column().classes("gap-1"):
                            ui.label("Độ sâu").classes("sr-pt-flabel")
                            inputs["rank_depth"] = ui.toggle(
                                {d: f"Top {d}" for d in PT.DEPTHS}, value=20,
                                on_change=lambda e: upd("rank_depth", e.value)).props(
                                "unelevated no-caps dense toggle-color=white toggle-text-color=dark "
                                "text-color=grey-8").classes("sr-seg")
                        with ui.column().classes("gap-1"):
                            ui.label("Số lần check").classes("sr-pt-flabel")
                            inputs["rank_times"] = num("rank_times", 1, "lần")
                    formula = ui.label().classes("text-xs muted sr-pt-formula")
                for title, rows in CALC_GROUPS:
                    ui.label(title).classes("sr-pt-gtitle")
                    with ui.element("div").classes("sr-pt-list"):
                        for k, name, unit in rows:
                            with ui.element("div").classes("sr-pt-row"):
                                with ui.column().classes("gap-0 sr-pt-name"):
                                    ui.label(name).classes("text-sm")
                                    ui.label(f"{PT.COSTS[k][1]} credit / {unit}").classes("text-xs muted")
                                inputs[k] = num(k, 0, unit)
                                subs[k] = ui.label("0").classes("num sr-pt-sub")
            with ui.element("div").classes("sr-pt-side"):
                summary = ui.html().classes("sr-pt-sum")
                ui.button("Đặt lại", icon="restart_alt", on_click=lambda: reset()).props(
                    "flat no-caps dense").classes("sr-pt-reset")

    def reset() -> None:
        for k, el in inputs.items():
            el.value = blank[k]
        st.update(blank)
        render()

    def upd(key, value) -> None:
        st[key] = int(value or 0) if key != "rank_depth" else int(value or 20)
        render()

    def render() -> None:
        r = PT.calc(**st)
        got = {x[0]: x[3] for x in r["lines"]}
        for k, lab in subs.items():
            v = got.get(k, 0)
            lab.text = _n(v)
            lab.classes(remove="zero") if v else lab.classes(add="zero")
        per = PT.rank_points([st["rank_depth"]])
        formula.text = (f"{_n(st['rank_keywords'])} từ khóa × {per} credit (Top {st['rank_depth']}) × "
                        f"{_n(st['rank_times'])} lần = {_n(got.get('rank', 0))} credit")
        summary.content = _summary_html(r, member, PT.my_balance(user) if member else None)
    render()
