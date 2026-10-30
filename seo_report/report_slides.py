"""Bộ slide báo cáo tuần / tháng (16:9) từ cùng dữ liệu với màn Báo cáo và file Excel. Tải lên Drive thì Google tự
chuyển sang Google Slides; PDF xuất từ chính bộ Slides đó.

Slide: bìa · nhận xét (+ kế hoạch tháng sau) · Google Search · AI · rank · URL tăng/giảm · (tháng) loại trang, top URL,
top query.
"""
import io
from datetime import datetime

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

from . import ai_format as F
from .report import BUCKETS, WeeklyReport, change, rank_change, summary

GREEN, LIME, INK, MUTED, RED, CREAM = "1E7C31", "B8D332", "2A2A24", "6B6A5E", "C2410C", "F4F3EE"
FONT = "Arial"
W, H = Inches(13.333), Inches(7.5)
ASSETS = __import__("pathlib").Path(__file__).parent / "assets"
LOGO_WIDE, LOGO_MARK = ASSETS / "logo-wide.png", ASSETS / "logo-mark.png"


def _rgb(hex_: str) -> RGBColor:
    return RGBColor.from_string(hex_)


def _text(slide, x, y, w, h, text, size=14, bold=False, color=INK, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(str(text).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.size, r.font.bold, r.font.name = Pt(size), bold, FONT
        r.font.color.rgb = _rgb(color)
    return box


def _slide(prs, title: str, subtitle: str = ""):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bar = s.shapes.add_shape(1, 0, 0, W, Inches(0.12))
    bar.fill.solid()
    bar.fill.fore_color.rgb = _rgb(GREEN)
    bar.line.fill.background()
    _text(s, Inches(0.6), Inches(0.35), Inches(11), Inches(0.7), title, 26, True)
    if LOGO_MARK.exists():
        s.shapes.add_picture(str(LOGO_MARK), W - Inches(1.15), Inches(0.35), height=Inches(0.62))
    if subtitle:
        _text(s, Inches(0.6), Inches(0.95), Inches(12), Inches(0.4), subtitle, 12, color=MUTED)
    return s


def _kpi(slide, x, y, label, value, delta="", good=None, w=Inches(2.9), h=Inches(1.45)):
    card = slide.shapes.add_shape(5, x, y, w, h)  # hình chữ nhật bo góc
    card.fill.solid()
    card.fill.fore_color.rgb = _rgb("FFFFFF")
    card.line.color.rgb = _rgb("E7E5DC")
    card.adjustments[0] = 0.08
    _text(slide, x + Inches(0.2), y + Inches(0.12), w - Inches(0.3), Inches(0.35), label, 11, color=MUTED)
    _text(slide, x + Inches(0.2), y + Inches(0.45), w - Inches(0.3), Inches(0.6), value, 26, True)
    if delta:
        _text(slide, x + Inches(0.2), y + Inches(1.0), w - Inches(0.3), Inches(0.35), delta, 12, True,
              MUTED if good is None else (GREEN if good else RED))


def _table(slide, x, y, w, headers, rows, widths=None, font=11, colors=None):
    shape = slide.shapes.add_table(len(rows) + 1, len(headers), x, y, w, Inches(0.32) * (len(rows) + 1))
    t = shape.table
    for j, h in enumerate(headers):
        c = t.cell(0, j)
        c.text = h
        c.fill.solid()
        c.fill.fore_color.rgb = _rgb(CREAM)
    for i, row in enumerate(rows, 1):
        for j, v in enumerate(row):
            c = t.cell(i, j)
            c.text = "" if v is None else str(v)
            c.fill.solid()
            c.fill.fore_color.rgb = _rgb("FFFFFF")
    for i in range(len(rows) + 1):
        for j in range(len(headers)):
            for p in t.cell(i, j).text_frame.paragraphs:
                p.alignment = PP_ALIGN.LEFT if j == 0 or (widths and widths[j] > 3) else PP_ALIGN.RIGHT
                for r in p.runs:
                    r.font.size, r.font.name = Pt(font), FONT
                    r.font.bold = i == 0
                    color = (colors[i - 1][j] if colors and i > 0 and colors[i - 1][j] else
                             (MUTED if i == 0 else INK))
                    r.font.color.rgb = _rgb(color)
    if widths:
        total = sum(widths)
        for j, wj in enumerate(widths):
            t.columns[j].width = Emu(int(w * wj / total))
    return shape


def _pct_delta(now, prev) -> tuple[str, bool | None]:
    d = change(now, prev)
    return F.delta_pct(d), (None if not d else d > 0)


def _short(url, site):
    return (url or "").replace(site.rstrip("/"), "") or ("/" if url else "")


def build_report_pptx(rep: WeeklyReport, user: str) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    month = rep.kind == "month"
    unit = "tháng" if month else "tuần"
    (ws, we), (ps, pe) = rep.week, rep.prev_week
    site = rep.site.split("//")[-1].strip("/")
    period = f"tháng {ws:%m/%Y}" if month else f"tuần {ws:%d/%m} – {we:%d/%m/%Y}"
    prev_text = f"tháng {ps:%m/%Y}" if month else f"tuần {ps:%d/%m} – {pe:%d/%m}"

    # ---- Bìa ----
    s = prs.slides.add_slide(prs.slide_layouts[6])
    if LOGO_WIDE.exists():
        s.shapes.add_picture(str(LOGO_WIDE), Inches(0.9), Inches(0.8), height=Inches(1.25))
    band = s.shapes.add_shape(1, 0, Inches(5.9), W, Inches(1.6))
    band.fill.solid()
    band.fill.fore_color.rgb = _rgb(GREEN)
    band.line.fill.background()
    accent = s.shapes.add_shape(1, Inches(0.9), Inches(2.75), Inches(1.2), Inches(0.08))
    accent.fill.solid()
    accent.fill.fore_color.rgb = _rgb(LIME)
    accent.line.fill.background()
    _text(s, Inches(0.9), Inches(3.0), Inches(11.5), Inches(1.0), f"Báo cáo SEO & GEO {period}", 38, True)
    _text(s, Inches(0.9), Inches(4.05), Inches(11.5), Inches(0.6), f"{site} · nhóm {rep.group} · so với {prev_text}",
          18, color=MUTED)
    _text(s, Inches(0.9), Inches(6.45), Inches(11.5), Inches(0.5),
          f"Xuất lúc {datetime.now():%d/%m/%Y %H:%M} bởi {user}", 12, color="E7F3EA")

    # ---- Tổng quan SEO & GEO ----
    sm = summary(rep)
    s = _slide(prs, "Tổng quan SEO & GEO", f"{period} · so với {prev_text}")
    for col, (title, color, items, notes) in enumerate([
            ("SEO · Google Search", GREEN, sm["seo"], sm["seo_notes"]),
            ("GEO · AI Search", "7C3AED", sm["geo"], sm["geo_notes"])]):
        x = Inches(0.6) + Inches(6.25) * col
        head = s.shapes.add_shape(5, x, Inches(1.45), Inches(6.0), Inches(0.45))
        head.fill.solid()
        head.fill.fore_color.rgb = _rgb(color)
        head.line.fill.background()
        head.adjustments[0] = 0.25
        _text(s, x + Inches(0.15), Inches(1.47), Inches(5.7), Inches(0.4), title, 15, True, "FFFFFF")
        for i, it in enumerate(items[:4]):
            _kpi(s, x + Inches(3.05) * (i % 2), Inches(2.05) + Inches(1.45) * (i // 2), it["short"], it["value"],
                 it["delta"], it["good"], w=Inches(2.95), h=Inches(1.32))
        for j, note in enumerate(notes):
            mark = {"up": "▲", "down": "▼", "warn": "⚠"}.get(note["tone"], "•")
            color = {"up": GREEN, "down": RED, "warn": "B7791F"}.get(note["tone"], MUTED)
            _text(s, x, Inches(5.05) + Inches(0.42) * j, Inches(6.0), Inches(0.4), f"{mark} {note['long']}", 12,
                  color=color)

    # ---- Nhận xét ----
    if rep.note or (month and rep.plan):
        s = _slide(prs, "Nhận xét" + (" và kế hoạch" if month else ""), period)
        _text(s, Inches(0.6), Inches(1.5), Inches(6 if month else 12), Inches(5.5), rep.note or "(Chưa có nhận xét)",
              16)
        if month:
            _text(s, Inches(6.9), Inches(1.5), Inches(5.8), Inches(0.5), "Kế hoạch tháng sau", 16, True, GREEN)
            _text(s, Inches(6.9), Inches(2.0), Inches(5.8), Inches(5), rep.plan or "(Chưa có kế hoạch)", 15)

    # ---- Google Search ----
    s = _slide(prs, "Google Search (GSC)", f"{period} · toàn site theo tổng property; nhóm {rep.group} theo URL")
    sk, sp, gk, gp = rep.site_kpi, rep.site_prev, rep.group_kpi, rep.group_prev
    x0, y0, gap = Inches(0.6), Inches(1.55), Inches(3.08)
    _kpi(s, x0, y0, "Click toàn site", F.n(sk.clicks), *_pct_delta(sk.clicks, sp.clicks))
    _kpi(s, x0 + gap, y0, "Impression toàn site", F.n(sk.impressions), *_pct_delta(sk.impressions, sp.impressions))
    d = (sk.ctr - sp.ctr) if sk.ctr is not None and sp.ctr is not None else None
    _kpi(s, x0 + gap * 2, y0, "CTR toàn site", F.pct(sk.ctr, 1), F.delta_points(d), None if not d else d > 0)
    _kpi(s, x0 + gap * 3, y0, f"Click nhóm {rep.group}", F.n(gk.clicks), *_pct_delta(gk.clicks, gp.clicks))
    data = CategoryChartData()
    data.categories = [t["week"] for t in rep.trend]
    data.add_series("Click toàn site", [t["site_clicks"] for t in rep.trend])
    data.add_series(f"Click nhóm {rep.group}", [t["group_clicks"] for t in rep.trend])
    chart = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(3.25), Inches(12.1), Inches(3.9),
                               data).chart
    chart.has_legend, chart.legend.position, chart.legend.include_in_layout = True, XL_LEGEND_POSITION.BOTTOM, False
    for series, color in zip(chart.series, [GREEN, LIME]):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = _rgb(color)
    chart.font.size, chart.font.name = Pt(11), FONT

    # ---- AI ----
    ai, aio = rep.ai, rep.aio
    if (ai and not ai.get("error")) or aio:
        s = _slide(prs, "AI Search & GEO", "Hai nguồn tách riêng, không cộng với nhau")
        if ai and not ai.get("error"):
            k, dl, pv = ai["kpi"], ai["deltas"], ai["prev"]
            _text(s, Inches(0.6), Inches(1.45), Inches(8), Inches(0.4), "Traffic từ AI assistant (GA4: ChatGPT, "
                  "Gemini…)", 14, True, GREEN)
            _kpi(s, Inches(0.6), Inches(1.95), "Phiên AI", F.n(k["sessions"]),
                 F.delta_pct(dl.get("sessions"), pv.get("sessions")), None if not dl.get("sessions") else
                 dl["sessions"] > 0)
            _kpi(s, Inches(0.6) + gap, Inches(1.95), "Engagement rate", F.pct(k["engagementRate"], 1),
                 F.delta_points(dl.get("engagementRate")))
            _kpi(s, Inches(0.6) + gap * 2, Inches(1.95), "Key events", F.n(k["keyEvents"]),
                 F.delta_pct(dl.get("keyEvents"), pv.get("keyEvents")))
            _kpi(s, Inches(0.6) + gap * 3, Inches(1.95), "Tỷ lệ trên tổng phiên", F.pct(ai["share"]["ofAllSessions"]))
            if ai["sources"]:
                _text(s, Inches(0.6), Inches(3.5), Inches(12), Inches(0.4), "Theo nguồn: " + " · ".join(
                    f"{F.SOURCE_NAMES.get(x['source'], x['source'])} {x['sessions']}" for x in ai["sources"]), 12,
                      color=MUTED)
        if aio:
            y = Inches(4.2)
            _text(s, Inches(0.6), y, Inches(8), Inches(0.4), "Hiển thị trong AI Overviews / AI Mode (GSC, nhập file)",
                  14, True, GREEN)
            if aio["impressions"] is None:
                _text(s, Inches(0.6), y + Inches(0.5), Inches(12), Inches(0.4),
                      f"Chưa có số cho {unit} này: file đã nhập có dữ liệu tới {aio['data_until']}.", 13, color=RED)
            else:
                _kpi(s, Inches(0.6), y + Inches(0.5), "Impression", F.n(aio["impressions"]),
                     F.delta_pct(aio["change"], aio["prev"]), None if not aio["change"] else aio["change"] > 0)
                _kpi(s, Inches(0.6) + gap, y + Inches(0.5), "Trên impression GSC Web", F.pct(aio["share"], 1))
                _text(s, Inches(0.6) + gap * 2, y + Inches(0.7), Inches(6), Inches(1.2),
                      "Chỉ có impression: GSC không cung cấp click riêng cho AI Overviews.", 12, color=MUTED)

    # ---- Rank ----
    s = _slide(prs, f"Rank thực tế · {len(rep.ranks)} keyword", "DataForSEO, Google mobile, Việt Nam")
    if rep.ranks:
        buckets = " · ".join(f"{b}: {rep.rank_buckets[b][0]}" for b in BUCKETS if any(rep.rank_buckets[b]))
        _text(s, Inches(0.6), Inches(1.4), Inches(12), Inches(0.4), buckets, 13, True)
        rows, colors = [], []
        for r in rep.ranks[:12]:
            text, color, _ = rank_change(r["date"], r["rank"], r["depth"], r["prev"], r["prev_depth"])
            wrong = bool(r["target_url"] and r["ranking_url"] and r["ranking_url"] != r["target_url"])
            rows.append([r["keyword"], r["rank"] if r["rank"] is not None else f">{r['depth']}", text,
                         _short(r["ranking_url"], rep.site) + ("  ⚠ khác URL mục tiêu" if wrong else "")])
            colors.append([None, None, color.lstrip("#"), RED if wrong else None])
        _table(s, Inches(0.6), Inches(1.95), Inches(12.1), ["Keyword", "Vị trí", "Thay đổi", "URL đang xếp hạng"],
               rows, [3.2, 1, 1.6, 6.3], 11, colors)
    else:
        _text(s, Inches(0.6), Inches(1.6), Inches(12), Inches(0.5), "Chưa có lần check rank nào trong khoảng này.", 14)

    # ---- URL tăng / giảm ----
    s = _slide(prs, f"URL tăng / giảm click · nhóm {rep.group}", f"So với {prev_text} · URL có từ 20 click")
    for i, (title, items, color) in enumerate([("Tăng click", rep.winners, GREEN), ("Giảm click", rep.losers, RED)]):
        x = Inches(0.6) + Inches(6.2) * i
        _text(s, x, Inches(1.4), Inches(5.8), Inches(0.4), title, 15, True, color)
        if items:
            _table(s, x, Inches(1.9), Inches(5.9), ["URL", f"{unit.capitalize()} này", "Trước", "Chênh"],
                   [[_short(x_["url"], rep.site), F.n(x_["clicks"]), F.n(x_["prev"]), f"{x_['diff']:+,}".replace(
                       ",", ".")] for x_ in items], [5, 1.3, 1.1, 1.1], 10,
                   [[None, None, None, color] for _ in items])

    # ---- Tiến độ công việc (OKR) ----
    if rep.okr:
        from . import okr as O
        k = rep.okr
        p, cnt = k["period"], k["counts"]
        s = _slide(prs, "Tiến độ công việc", "OKR 3 tháng, đọc từ Google Sheet của team")
        pct = f"{cnt[O.DONE] / k['total'] * 100:.0f}%" if k["total"] else "–"
        _kpi(s, Inches(0.6), Inches(1.4), "Hoàn thành OKR", pct, f"{cnt[O.DONE]}/{k['total']} hạng mục")
        _kpi(s, Inches(0.6) + gap, Inches(1.4), f"Xong trong {unit}", str(len(p["done"])),
             f"{len(p['due'])} đến hạn")
        _kpi(s, Inches(0.6) + gap * 2, Inches(1.4), "Đang làm", str(cnt[O.DOING]))
        _kpi(s, Inches(0.6) + gap * 3, Inches(1.4), "Trễ hạn", str(len(k["late"])), "tính đến hôm nay",
             False if k["late"] else None)

        def vn(iso):
            return f"{iso[8:10]}/{iso[5:7]}" if iso else ""

        cols = [(f"Hoàn thành trong {unit}", p["done"], GREEN), ("Trễ hạn", k["late"], RED),
                (f"Kế hoạch {unit} sau", p["next"], INK)]
        for n, (title, its, color) in enumerate(cols):
            x = Inches(0.6) + Inches(4.1) * n
            _text(s, x, Inches(3.15), Inches(3.9), Inches(0.4), f"{title} · {len(its)}", 14, True, color)
            lines = [f"{i['code']}  {i['title']}" + (f" (hạn {vn(i['end'])})" if i["end"] else "") for i in its[:8]]
            if len(its) > 8:
                lines.append(f"và {len(its) - 8} hạng mục khác")
            _text(s, x, Inches(3.6), Inches(3.9), Inches(3.4), "\n".join(lines) or "Không có.", 11)

    # ---- Tháng: loại trang, top URL, top query ----
    if month:
        s = _slide(prs, "Theo loại trang và top của tháng", "Cộng theo URL nên tổng khác tổng toàn site")
        _table(s, Inches(0.6), Inches(1.45), Inches(5.6), ["Loại trang", "Click", "Thay đổi"],
               [[r["type"], F.n(r["clicks"]), F.delta_pct(r["change"])] for r in rep.by_type[:10]], [3, 1.2, 1.2],
               10, [[None, None, (GREEN if (r["change"] or 0) > 0 else RED) if r["change"] else None]
                    for r in rep.by_type[:10]])
        _table(s, Inches(6.6), Inches(1.45), Inches(6.1), ["Top query", "Click", "Thay đổi"],
               [[r["query"], F.n(r["clicks"]), F.delta_pct(r["change"])] for r in rep.top_queries[:10]],
               [3.6, 1.1, 1.2], 10)
        s = _slide(prs, "Top 10 URL của tháng", "Toàn site, theo click")
        _table(s, Inches(0.6), Inches(1.45), Inches(12.1), ["URL", "Loại", "Click", "Thay đổi"],
               [[_short(r["url"], rep.site), r["type"], F.n(r["clicks"]), F.delta_pct(r["change"])]
                for r in rep.top_urls], [7, 2, 1.2, 1.3], 11)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def slides_filename(rep: WeeklyReport) -> str:
    host = rep.site.split("//")[-1].strip("/").split(".")[0]
    if rep.kind == "month":
        return f"bao-cao-seo-thang_{host}_{rep.week[0]:%Y-%m}"
    return f"bao-cao-seo_{host}_{rep.week[0]:%Y-%m-%d}_{rep.week[1]:%Y-%m-%d}"
