"""File Excel báo cáo tuần cho sếp: một sheet định dạng sẵn, đọc từ trên xuống, có biểu đồ xu hướng.

Khác file "Xuất dữ liệu" (bảng phẳng để kiểm tra/pivot): file này để đọc và gửi đi, nên chỉ có số đã chọn lọc.
"""
import io
from pathlib import Path
from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .report import BUCKETS, MIN_CLICKS_FOR_MOVERS, WeeklyReport, change, rank_change, summary

GREEN = "1E7C31"
RED = "C2410C"
INK = "2A2A24"
MUTED = "6B6A5E"
TINT = "E4EFDC"
CREAM = "F4F3EE"
THIN = Side(style="thin", color="E6E4DC")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _vn(d) -> str:
    return f"{d:%d/%m/%Y}"


def _short(url: str | None, site: str) -> str:
    return (url or "").replace(site.rstrip("/"), "") or ("/" if url else "")


def _pos_text(rank, depth) -> str:
    return str(rank) if rank is not None else (f">{depth}" if depth else "")


class _Sheet:
    """Ghi lần lượt từng khối xuống dưới."""

    def __init__(self, ws):
        self.ws, self.row = ws, 1

    def title(self, text, size=16, color=INK):
        c = self.ws.cell(self.row, 1, text)
        c.font = Font(size=size, bold=True, color=color)
        self.row += 1

    def text(self, text, color=MUTED, italic=False):
        c = self.ws.cell(self.row, 1, text)
        c.font = Font(color=color, italic=italic, size=10)
        self.row += 1

    def gap(self, n=1):
        self.row += n

    def section(self, text):
        self.gap()
        c = self.ws.cell(self.row, 1, text)
        c.font = Font(size=12, bold=True, color=GREEN)
        self.row += 1

    def table(self, header: list[str], rows: list[list], formats: list[str | None] | None = None,
              colors: list[list[str | None]] | None = None):
        for j, h in enumerate(header, 1):
            c = self.ws.cell(self.row, j, h)
            c.font = Font(bold=True, color=INK)
            c.fill = PatternFill("solid", fgColor=TINT)
            c.alignment = Alignment(horizontal="center" if j > 1 else "left", vertical="center", wrap_text=True)
            c.border = BOX
        self.row += 1
        for i, r in enumerate(rows):
            for j, v in enumerate(r, 1):
                c = self.ws.cell(self.row, j, v)
                c.border = BOX
                if formats and formats[j - 1]:
                    c.number_format = formats[j - 1]
                if j > 1:
                    c.alignment = Alignment(horizontal="right" if isinstance(v, (int, float)) else "left")
                color = colors[i][j - 1] if colors else None
                if color:
                    c.font = Font(color=color, bold=True)
            self.row += 1


def _unit(rep: WeeklyReport) -> str:
    return "tháng" if rep.kind == "month" else "tuần"


def _delta_color(value, lower_is_better=False):
    if value is None or value == 0:
        return None
    good = value < 0 if lower_is_better else value > 0
    return GREEN if good else RED


def _aio_section(s: "_Sheet", rep: WeeklyReport) -> None:
    from . import ai_format as F

    s.section("Hiển thị trong AI Overviews / AI Mode của Google (GSC Generative AI, nhập file)")
    a = rep.aio
    if a["impressions"] is None:
        s.text(f"Chưa có số cho {_unit(rep)} này: file đã nhập có dữ liệu tới {a['data_until']}.", color=RED)
        return
    prev = a["prev"]
    s.table(["Chỉ số", f"{_unit(rep).capitalize()} này", f"So với {_unit(rep)} trước"], [
        ["Impression AI Overviews / AI Mode", a["impressions"],
         f"{_unit(rep)} trước {prev}" if prev is not None and prev < F.MIN_BASE else a["change"]],
        ["Tỷ lệ trên impression GSC Web", a["share"], None],
    ], None, [[None, None, _delta_color(a["change"])], [None, None, None]])
    ws, r0 = s.ws, s.row - 2
    ws.cell(r0, 2).number_format, ws.cell(r0 + 1, 2).number_format = "#,##0", "0.00%"
    ws.cell(r0, 3).number_format = "+0.0%;-0.0%;0.0%"
    s.text("Chỉ có impression, GSC không cung cấp click riêng cho AI Overviews. Không cộng với traffic ChatGPT/Gemini.",
           italic=True)


def _okr_section(s: "_Sheet", rep: WeeklyReport) -> None:
    from . import okr as O

    k, unit = rep.okr, _unit(rep)
    p, cnt = k["period"], k["counts"]
    s.section("Tiến độ công việc (OKR 3 tháng, đọc từ Google Sheet của team)")
    s.table(["Chỉ số", "Số"], [
        ["Hạng mục OKR hoàn thành", f"{cnt[O.DONE]} / {k['total']}"],
        [f"Hoàn thành trong {unit}", len(p["done"])],
        [f"Đến hạn trong {unit}", len(p["due"])],
        ["Đang làm", cnt[O.DOING]],
        ["Trễ hạn (tính đến hôm nay)", len(k["late"])],
    ], colors=[[None, None]] * 4 + [[None, RED if k["late"] else None]])

    def vn(iso):
        return f"{iso[8:10]}/{iso[5:7]}" if iso else ""

    rows, colors = [], []
    for title, its in [(f"Hoàn thành trong {unit}", p["done"]), ("Trễ hạn", k["late"]),
                       (f"Kế hoạch {unit} sau", p["next"])]:
        for i in its:
            rows.append([title, i["code"], i["title"], f"{vn(i['start'])} – {vn(i['end'])}", i["pic"] or "",
                         O.STATUS_LABEL[i["status"]]])
            colors.append([GREEN if title.startswith("Hoàn") else RED if title == "Trễ hạn" else None] + [None] * 5)
    if rows:
        s.gap()
        s.table(["Nhóm", "ID", "Hạng mục", "Thời gian", "PIC", "Trạng thái"], rows, colors=colors)
    if k["tasks"]:
        s.gap()
        s.table(["Mã OKR", f"Việc {unit} (Weekly Task Tracker)", "PIC", "Deadline", "Trạng thái"],
                [[t["okr_code"] or "", t["task"] or t["item"] or "", t["pic"] or "", vn(t["deadline"]),
                  O.STATUS_LABEL[t["status"]]] for t in k["tasks"]])
    if p["tracking_since"]:
        s.text(f"Sheet không có cột ngày hoàn thành: 'Hoàn thành trong {unit}' tính theo ngày tool thấy trạng thái đổi "
               f"sang Hoàn thành (theo dõi từ {vn(p['tracking_since'])}).", italic=True)


def _ai_section(s: "_Sheet", rep: WeeklyReport) -> None:
    from . import ai_format as F

    s.section("Traffic từ AI assistant (GA4: ChatGPT, Gemini…; không gồm AI Overviews của Google)")
    ai = rep.ai
    if ai.get("error"):
        s.text(f"Chưa lấy được số liệu GA4: {ai['error']}", color=RED)
        return
    k, d, sh = ai["kpi"], ai["deltas"], ai["share"]

    def chg(key):  # tuần trước quá nhỏ thì ghi số tuần trước, không ghi % (1 → 17 phiên = +1.600%)
        prev = ai.get("prev", {}).get(key)
        return f"{_unit(rep)} trước {prev}" if prev is not None and prev < F.MIN_BASE else d.get(key)

    s.table(["Chỉ số", f"{_unit(rep).capitalize()} này", f"So với {_unit(rep)} trước"], [
        ["Phiên từ AI", k["sessions"], chg("sessions")],
        ["Tỷ lệ trên tổng phiên site", sh["ofAllSessions"], None],
        ["Engagement rate", k["engagementRate"], d.get("engagementRate")],
        ["Key events", k["keyEvents"], chg("keyEvents")],
        ["Session key event rate (% phiên có key event)", k["sessionKeyEventRate"], d.get("sessionKeyEventRate")],
    ], None, [[None, None, _delta_color(d.get(x))] for x in
              ("sessions", "_", "engagementRate", "keyEvents", "sessionKeyEventRate")])
    ws, r0 = s.ws, s.row - 5
    for i, fmt in enumerate(["#,##0", "0.00%", "0.00%", "#,##0", "0.00%"]):
        ws.cell(r0 + i, 2).number_format = fmt
        ws.cell(r0 + i, 3).number_format = "+0.0%;-0.0%;0.0%" if i in (0, 3) else '+0.00" điểm";-0.00" điểm"'
        if i in (2, 4) and ws.cell(r0 + i, 3).value is not None:
            ws.cell(r0 + i, 3).value = ws.cell(r0 + i, 3).value * 100  # điểm phần trăm
    if ai["sources"]:
        s.text("Theo nguồn: " + " · ".join(f"{F.SOURCE_NAMES.get(x['source'], x['source'])} {x['sessions']}"
                                           for x in ai["sources"]))
    if ai["paid"]["sessions"]:
        s.text(f"Không tính {ai['paid']['sessions']} phiên từ quảng cáo trên nền tảng AI (ví dụ chatgpt / paid).",
               italic=True)
    if "LOW_SAMPLE_SIZE" in ai.get("warnings", []):
        s.text(f"Số phiên AI trong {_unit(rep)} còn nhỏ: tỷ lệ dao động mạnh, nên xem xu hướng nhiều kỳ.",
               italic=True)


def build_report_excel(rep: WeeklyReport, user: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Báo cáo"
    ws.sheet_view.showGridLines = False
    for col, width in zip("ABCDEFGH", [44, 16, 16, 14, 16, 16, 14, 30]):
        ws.column_dimensions[col].width = width
    s = _Sheet(ws)
    site_name = rep.site.split("//")[-1].strip("/")
    (ws_, we), (ps, pe) = rep.week, rep.prev_week

    unit = _unit(rep)
    month = rep.kind == "month"
    logo = Path(__file__).parent / "assets" / "logo-wide.png"
    if logo.exists():
        from openpyxl.drawing.image import Image as XLImage
        img = XLImage(str(logo))
        img.height, img.width = 44, int(44 * img.width / img.height)
        ws.add_image(img, "F1")
    if month:
        s.title(f"Báo cáo SEO & GEO tháng {ws_:%m/%Y}")
        s.text(f"{site_name} · so với tháng {ps:%m/%Y} · xuất lúc {datetime.now():%d/%m/%Y %H:%M} bởi {user}")
    else:
        s.title(f"Báo cáo SEO & GEO tuần {_vn(ws_)} – {_vn(we)}")
        s.text(f"{site_name} · so với tuần {_vn(ps)} – {_vn(pe)} · xuất lúc {datetime.now():%d/%m/%Y %H:%M} bởi {user}")
    if rep.incomplete_days:
        s.text(f"Lưu ý: còn {rep.incomplete_days} ngày trong {unit} chưa có dữ liệu GSC; số có thể tăng thêm.",
               color=RED)

    # Nhận xét lên đầu: sếp đọc kết luận trước.
    for title, text, empty in [("Nhận xét", rep.note, "(Chưa có nhận xét)")] + (
            [("Kế hoạch tháng sau", rep.plan, "(Chưa có kế hoạch)")] if month else []):
        s.section(title)
        ws.merge_cells(start_row=s.row, start_column=1, end_row=s.row + 3, end_column=8)
        c = ws.cell(s.row, 1, text or empty)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.fill = PatternFill("solid", fgColor=CREAM)
        c.font = Font(color=INK if text else MUTED, italic=not text)
        s.gap(4)

    sm = summary(rep)
    s.section("Tổng quan SEO & GEO")
    rows, colors = [], []
    for area, items in [("SEO", sm["seo"]), ("GEO", sm["geo"])]:
        for it in items:
            rows.append([area, it["label"], it["value"], it["delta"]])
            colors.append([GREEN if area == "SEO" else "7C3AED", None, None,
                           None if it["good"] is None else (GREEN if it["good"] else RED)])
    s.table(["Mảng", "Chỉ số", "Giá trị", f"So với {unit} trước"], rows, None, colors)
    for note in sm["seo_notes"] + sm["geo_notes"]:
        s.text("• " + note["long"])
    s.gap()

    s.section("Chỉ số chính (Google Search Console)")
    rows, colors = [], []
    for name, now, prev in [("Toàn site", rep.site_kpi, rep.site_prev),
                            (f"Nhóm {rep.group}", rep.group_kpi, rep.group_prev)]:
        dc, di = change(now.clicks, prev.clicks), change(now.impressions, prev.impressions)
        dctr = (now.ctr - prev.ctr) if now.ctr is not None and prev.ctr is not None else None
        dpos = (now.position - prev.position) if now.position and prev.position else None
        rows.append([name, now.clicks, dc, now.impressions, di, now.ctr, dctr, now.position])
        colors.append([None, None, _delta_color(dc), None, _delta_color(di), None, _delta_color(dctr), None])
    s.table(["Phạm vi", "Click", f"% so với {unit} trước", "Impression", f"% so với {unit} trước", "CTR",
             "CTR thay đổi (điểm)", "Position TB (GSC)"], rows,
            [None, "#,##0", "+0.0%;-0.0%;0.0%", "#,##0", "+0.0%;-0.0%;0.0%", "0.0%", "+0.0%;-0.0%;0.0%", "0.0"],
            colors)
    s.text("Position TB là trung bình của GSC trên mọi lượt hiển thị, không phải thứ hạng thực tế. Thứ hạng thực tế "
           "xem ở phần Rank bên dưới.", italic=True)

    if rep.ai:
        _ai_section(s, rep)
    if rep.aio:
        _aio_section(s, rep)

    s.section(f"Click {len(rep.trend)} {unit} gần nhất")
    trend_top = s.row
    s.table(["Tháng" if month else "Tuần (bắt đầu)", "Toàn site", f"Nhóm {rep.group}"],
            [[t["week"], t["site_clicks"], t["group_clicks"]] for t in rep.trend], [None, "#,##0", "#,##0"])
    chart = LineChart()
    chart.title, chart.y_axis.title, chart.height, chart.width = None, "Click", 7, 16
    chart.add_data(Reference(ws, min_col=2, max_col=3, min_row=trend_top, max_row=trend_top + len(rep.trend)),
                   titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=trend_top + 1, max_row=trend_top + len(rep.trend)))
    for series, color in zip(chart.series, [GREEN, "9BB823"]):
        series.graphicalProperties.line.solidFill = color
        series.graphicalProperties.line.width = 28000
        series.smooth = False
    ws.add_chart(chart, f"E{trend_top}")
    s.gap(max(0, 15 - len(rep.trend) - 1))

    s.section(f"Rank thực tế keyword theo dõi ({len(rep.ranks)} keyword · DataForSEO, mobile, Việt Nam)")
    if rep.ranks:
        s.table(["Nhóm vị trí", f"{unit.capitalize()} này", "Lần check trước"],
                [[b, rep.rank_buckets[b][0], rep.rank_buckets[b][1]] for b in BUCKETS if any(rep.rank_buckets[b])],
                [None, "#,##0", "#,##0"])
        s.gap()
        rows, colors = [], []
        for r in rep.ranks:
            text, _, move = rank_change(r["date"], r["rank"], r["depth"], r["prev"], r["prev_depth"])
            wrong = bool(r["target_url"] and r["ranking_url"] and r["ranking_url"] != r["target_url"])
            rows.append([r["keyword"], f"{_pos_text(r['rank'], r['depth'])} ({r['date'][8:10]}/{r['date'][5:7]})",
                         f"{_pos_text(r['prev'], r['prev_depth'])} ({r['prev_date'][8:10]}/{r['prev_date'][5:7]})"
                         if r["prev_date"] else "",
                         text,
                         _short(r["ranking_url"], rep.site), "Sai URL mục tiêu" if wrong else ""])
            colors.append([None, None, None, _delta_color(move or None), None, RED if wrong else None])
        s.table(["Keyword", "Vị trí (ngày check)", "Lần check trước", "Thay đổi", "URL đang xếp hạng", "Ghi chú"],
                rows, None, colors)
    else:
        s.text("Chưa có lần check rank nào trong khoảng này.")

    for title, items in [(f"Top {len(rep.winners)} URL tăng click (nhóm {rep.group})", rep.winners),
                         (f"Top {len(rep.losers)} URL giảm click (nhóm {rep.group})", rep.losers)]:
        s.section(title)
        if items:
            s.table(["URL", "Loại", f"Click {unit} này", f"Click {unit} trước", "Chênh lệch"],
                    [[_short(x["url"], rep.site), x["type"], x["clicks"], x["prev"], x["diff"]] for x in items],
                    [None, None, "#,##0", "#,##0", "+#,##0;-#,##0"],
                    [[None, None, None, None, _delta_color(x["diff"])] for x in items])
        else:
            s.text("Không có URL nào.")
    s.text(f"Chỉ xét URL có từ {MIN_CLICKS_FOR_MOVERS} click ở một trong hai {unit}, xếp theo số click chênh lệch.",
           italic=True)

    if rep.okr:
        _okr_section(s, rep)

    if month:
        s.section("Theo loại trang (cộng theo URL)")
        s.table(["Loại trang", "Click", "Click tháng trước", "% thay đổi", "Impression"],
                [[r["type"], r["clicks"], r["prev_clicks"], r["change"], r["impressions"]] for r in rep.by_type],
                [None, "#,##0", "#,##0", "+0.0%;-0.0%;0.0%", "#,##0"],
                [[None, None, None, _delta_color(r["change"]), None] for r in rep.by_type])
        s.text("Cộng theo từng URL nên tổng khác tổng toàn site (GSC tính toàn site theo property).", italic=True)
        s.section("Top 10 URL nhiều click nhất tháng (toàn site)")
        s.table(["URL", "Loại", "Click", "Click tháng trước", "% thay đổi"],
                [[_short(r["url"], rep.site), r["type"], r["clicks"], r["prev"], r["change"]] for r in rep.top_urls],
                [None, None, "#,##0", "#,##0", "+0.0%;-0.0%;0.0%"],
                [[None, None, None, None, _delta_color(r["change"])] for r in rep.top_urls])
        s.section("Top 10 từ khóa (query) nhiều click nhất tháng")
        s.table(["Query", "Click", "Impression", "Click tháng trước", "% thay đổi"],
                [[r["query"], r["clicks"], r["impressions"], r["prev"], r["change"]] for r in rep.top_queries],
                [None, "#,##0", "#,##0", "#,##0", "+0.0%;-0.0%;0.0%"],
                [[None, None, None, None, _delta_color(r["change"])] for r in rep.top_queries])
        s.text("GSC ẩn các query hiếm, nên tổng click theo query nhỏ hơn click toàn site.", italic=True)

    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def report_filename(rep: WeeklyReport) -> str:
    host = rep.site.split("//")[-1].strip("/").split(".")[0]
    if rep.kind == "month":
        return f"bao-cao-seo-thang_{host}_{rep.week[0]:%Y-%m}.xlsx"
    return f"bao-cao-seo_{host}_{rep.week[0]:%Y-%m-%d}_{rep.week[1]:%Y-%m-%d}.xlsx"
