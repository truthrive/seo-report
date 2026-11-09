"""Trang Điểm của tôi (/diem): điểm tháng này còn bao nhiêu, bị trừ ở tác vụ nào, lúc nào, ở website nào; bảng điểm
từng tác vụ. Member có hạn mức; Owner / Admin không giới hạn nhưng vẫn xem được các tác vụ mình đã chạy."""
from datetime import date, datetime, timedelta

from . import access as A
from . import points as PT
from . import ui_theme as T

UNIT = {"rank": "mỗi từ khóa", "aio": "mỗi từ khóa", "serp": "mỗi từ khóa", "volume": "mỗi lần thêm"}
NOTE = {"rank": "Bấm Check ngay. Check theo lịch của bộ không trừ điểm.",
        "aio": "Trang Ý tưởng từ khóa; từ khóa đã có số không tính.",
        "serp": "Trang Tổng quan từ khóa.",
        "backlink": "Bấm Lấy số mới: số tổng, lịch sử và các danh sách. Lịch tự lấy không trừ điểm.",
        "research": "Mỗi lần tìm ở trang Ý tưởng từ khóa.",
        "overview": "Chỉ khi phải gọi Google Ads; xem lại từ khóa đã phân tích trong 7 ngày không tính.",
        "volume": "Khi thêm từ khóa vào bộ theo dõi hạng.",
        "audit": "Bấm Quét ngay ở Cơ hội SEO. Lịch quét hằng tuần không trừ điểm.",
        "pagespeed": "Bấm kiểm tra ở trang Tốc độ trang.",
        "local": "Bấm Lấy số mới ở trang Local SEO.",
        "merchant": "Bấm Lấy số mới ở trang Merchant Center.",
        "kg": "Bấm Kiểm tra ngay ở tab Thực thể thương hiệu.",
        "sheets": "Lưu file lên Google Sheets / Drive. Tải Excel về máy không tính."}


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
    T.page_header(ui, "toll", "Điểm của tôi",
                  "Mỗi tác vụ bạn bấm (tìm, check, lấy số, lưu Drive…) trừ điểm trong hạn mức tháng; ngày 1 đặt lại. "
                  "Việc tool tự chạy theo lịch không trừ điểm của bạn." if member else
                  "Owner / Admin không giới hạn điểm; trang này ghi lại các tác vụ bạn đã chạy để đối chiếu.",
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
                T.kpi(ui, "toll", "Còn lại", _n(bal["left"]), hint=f"trên {_n(bal['limit'])} điểm", tone=tone)
                T.kpi(ui, "bolt", "Đã dùng", _n(bal["used"]), hint=f"{ratio * 100:.0f}% hạn mức", tone="blue")
                T.kpi(ui, "event_repeat", "Hạn mức tháng", _n(bal["monthly"]),
                      hint=(f"+ {_n(bal['granted'])} điểm cấp thêm" if bal["granted"] else "đặt lại ngày 1"),
                      tone="lime")
            else:
                T.kpi(ui, "all_inclusive", "Hạn mức", "Không giới hạn", hint=A.GROUPS[A.group(user)], tone="lime")
                T.kpi(ui, "bolt", "Đã chạy", _n(spent) + " điểm", hint=f"{len(rows)} tác vụ", tone="blue")
            T.kpi(ui, "receipt_long", "Số lần trừ", _n(len(rows)), hint=f"{len(acts)} loại tác vụ", tone="grey")

        with T.section(ui, "Theo tác vụ", "donut_small", "Điểm đã dùng tháng này, tách theo loại tác vụ"):
            if not acts:
                ui.label("Tháng này chưa dùng điểm nào.").classes("text-sm muted")
            else:
                ui.table(columns=[
                    {"name": "name", "label": "Tác vụ", "field": "name", "align": "left"},
                    {"name": "times", "label": "Số lần", "field": "times", "align": "right"},
                    {"name": "points", "label": "Điểm", "field": "points", "align": "right", "sortable": True,
                     ":format": "v => v.toLocaleString('vi-VN')"},
                    {"name": "pct", "label": "Tỷ lệ", "field": "pct", "align": "right"},
                ], rows=[{**a, "pct": f"{a['points'] / spent * 100:.0f}%" if spent else "–"} for a in acts],
                    row_key="action").props("flat dense").classes("w-full sr-bl-table")

        with T.section(ui, "Lịch sử trừ điểm", "history", "Từng lần trừ điểm, mới nhất trước"):
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
                    {"name": "points", "label": "Điểm", "field": "points", "align": "right",
                     ":format": "v => '−' + v.toLocaleString('vi-VN')"},
                ], rows=data, row_key="id", pagination=20).props("flat dense").classes("w-full sr-bl-table")

        if gr:
            with T.section(ui, "Điểm cấp thêm", "add_card", "Owner / Admin cấp thêm trong tháng này"):
                for g in gr:
                    ui.label(f"+{_n(g['points'])} điểm · {datetime.fromisoformat(g['at']).astimezone():%d/%m %H:%M} "
                             f"· bởi {g['by']}" + (f" · {g['note']}" if g["note"] else "")).classes("text-sm")

        with T.section(ui, "Bảng điểm", "price_change", "Mỗi tác vụ trừ bao nhiêu điểm"):
            ui.table(columns=[
                {"name": "name", "label": "Tác vụ", "field": "name", "align": "left"},
                {"name": "points", "label": "Điểm", "field": "points", "align": "right"},
                {"name": "unit", "label": "Tính theo", "field": "unit", "align": "left"},
                {"name": "note", "label": "Khi nào trừ", "field": "note", "align": "left"},
            ], rows=[{"action": k, "name": v[0], "points": PT.rank_points([20]) if k == "rank" else v[1],
                      "unit": UNIT.get(k, "mỗi lần"),
                      "note": NOTE.get(k, "")} for k, v in PT.COSTS.items()],
                row_key="action").props("flat dense").classes("w-full sr-bl-table")
            ui.label("Tác vụ không chạy được (lỗi, mất mạng…) thì điểm được hoàn lại. Hết điểm: nhờ Owner hoặc Admin cấp "
                     "thêm ở trang Phân quyền.").classes("text-xs muted q-mt-xs")

    body()
