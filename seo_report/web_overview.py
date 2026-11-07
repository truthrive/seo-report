"""Màn Tổng quan (trang chủ) và Báo cáo tuần/tháng: cùng các khối số. Tổng quan để làm việc hằng ngày (có sức khỏe
dữ liệu, bấm vào khối để đi sâu); Báo cáo là bản gửi người nhận báo cáo (quản lý, khách hàng) của chính các khối đó (thêm nhận xét, xuất Excel). Báo cáo
tháng thêm xu hướng 12 tháng, theo loại trang, top URL và top query.

Số GSC/rank/index đọc từ SQLite nên hiện ngay; số GA4 tải trong luồng nền rồi điền vào khối AI.
"""
import re
from datetime import date, timedelta

from . import ai_format as F
from . import kpi as KP
from .projects import domain
from . import ui_theme as T
from .report import (BUCKETS, build, build_month, change, day_list, day_values, note_key, period_text, rank_summary,
                     save_note)

RANK_TONE = [(3, "green"), (10, "lime"), (30, "amber")]


def _n(v) -> str:
    return F.n(v) if v is not None else "–"


def _short(url, site) -> str:
    return (url or "").replace(site.rstrip("/"), "") or ("/" if url else "")


def _pct_change(now, prev) -> str:
    return F.delta_pct(change(now, prev))


def build_overview_page(ui, cfg, connect, user: str, ctx: dict, mode: str = "overview", kind: str = "week") -> None:
    from nicegui import background_tasks, run

    from . import db
    from .report import ai_block

    site = cfg.site_url
    report = mode == "report"
    with connect() as c:
        compare = ctx.get("compare", "prev") if mode == "report" else "prev"
        rep = (build_month(c, cfg, ctx["group"], ctx["month"], with_ai=False, compare=compare) if kind == "month"
               else build(c, cfg, ctx["group"], ctx["week"], with_ai=False, compare=compare))
    month = kind == "month"
    unit = "tháng" if month else "tuần"
    state = {"rep": rep, "ai_trend": None, "ai_loading": True}
    (ws, we), (ps, pe) = rep.week, rep.prev_week

    # ---- Tiêu đề ----
    right = T.page_header(
        ui, "summarize" if report else "space_dashboard",
        f"Báo cáo tháng {ws:%m/%Y}" if month else
        f"{'Báo cáo tuần' if report else 'Tổng quan'} {ws:%d/%m} – {we:%d/%m/%Y}",
        "So với " + period_text(kind, (ps, pe), ws.year)
        + f" · {domain(site)}")
    with right:
        kpi_slot = ui.row().classes("items-center")  # nhãn KPI gọn khi dự án chưa bắt đầu
        if report:
            from .report_slides import build_report_pptx, slides_filename
            from .report_excel import build_report_excel
            from .web_export import export_menu

            async def with_ai():
                """Xuất trước khi số GA4 / KPI tải xong thì lấy ngay để file luôn đủ."""
                if rep.ai is None or rep.organic is None or state["ai_loading"] or rep.kpi is None:
                    def work():
                        from contextlib import closing

                        from .report import kpi_for_report, organic_block
                        with closing(db.connect(cfg.db_path)) as c:
                            return (ai_block(cfg, c, (ws, we), (ps, pe)), organic_block(cfg, c, (ws, we), (ps, pe),
                                                                              rep.trend_periods),
                                    kpi_for_report(cfg, c, rep))
                    rep.ai, rep.organic, rep.kpi = await run.io_bound(work)

            async def make_xlsx():
                await with_ai()
                return await run.io_bound(lambda: build_report_excel(rep, user))

            async def make_pptx():
                await with_ai()
                return await run.io_bound(lambda: build_report_pptx(rep, user))

            export_menu(ui, cfg, connect, slides_filename(rep), make_xlsx, make_pptx, "Xuất báo cáo", user=user,
                        category="report")
        else:
            ui.button("Bản báo cáo", icon="summarize", on_click=lambda: ui.navigate.to("/report")).props(
                "outline no-caps").classes("sr-head-btn")

    if rep.incomplete_days:
        T.status_chip(ui, f"Còn {rep.incomplete_days} ngày trong {unit} chưa có dữ liệu GSC: số có thể tăng thêm",
                      "amber", "hourglass_top")

    from .access import can_edit
    ed = can_edit(user)
    if report and not ed:  # người chỉ xem: đọc nhận xét, không sửa
        if rep.note or (month and rep.plan):
            with T.section(ui, "Nhận xét", "edit_note"):
                with ui.row().classes("w-full gap-6 no-wrap"):
                    for title, text in [("Nhận xét", rep.note)] + ([("Kế hoạch tháng sau", rep.plan)] if month else []):
                        with ui.column().classes("col gap-1"):
                            ui.label(title).classes("text-xs muted")
                            ui.label(text or "Chưa có").classes("text-sm").style("white-space: pre-line")
    elif report:
        with T.section(ui, "Nhận xét & kết luận", "edit_note", "Hiện ở đầu báo cáo, file Excel và slide"):
            with ui.row().classes("w-full gap-3 no-wrap"):
                note = ui.textarea("Nhận xét tháng" if month else None, value=rep.note,
                                   placeholder="Ví dụ: Traffic giảm 1% do Trang chủ giảm 38 click; nhóm trang "
                                               "danh mục tăng…").props("outlined autogrow").classes("col")
                plan = ui.textarea("Kế hoạch tháng sau", value=rep.plan,
                                   placeholder="Ví dụ: tối ưu 10 bài blog có nhiều impression AI Overviews…").props(
                    "outlined autogrow").classes("col") if month else None

            def save():
                with connect() as c:
                    save_note(c, site, note_key(rep), note.value or "", user)
                    if plan is not None:
                        save_note(c, site, f"plan:{ws.isoformat()}", plan.value or "", user)
                rep.note = note.value or ""
                if plan is not None:
                    rep.plan = plan.value or ""
                ui.notify(f"Đã lưu nhận xét cho {unit} này", type="positive")

            ui.button("Lưu nhận xét", icon="save", on_click=save).props("flat no-caps")
    elif ed:  # tình trạng dữ liệu là việc nội bộ: người chỉ xem không cần
        health_strip(ui, cfg, connect, rep)

    # Thứ tự khối giống nhau ở màn Báo cáo, file Excel và slide: KPI cam kết → SEO → GEO → Thứ hạng → Công việc → Điểm
    # cần chú ý → (tháng) Phụ lục. Tổng quan dùng cùng các khối, thay Công việc / Điểm cần chú ý bằng "Cần xử lý".
    # Biểu đồ khối SEO / GEO: từng ngày của kỳ đang xem (nét liền) và kỳ so sánh (nét đứt, ngày thứ 1 với ngày thứ 1)
    days_cur, days_prev = day_list((ws, we)), day_list((ps, pe))
    wl = [f"{d:%d/%m}" for d in days_cur]
    cl = [f"{d:%d/%m}" for d in days_prev]
    with connect() as c:
        from .report import aio_block
        from .web_dashboard import gsc_daily
        g = gsc_daily(c, site, min(ws, ps), max(we, pe))
        aio_days = (aio_block(c, site, (ws, we), (ps, pe), [(d, d) for d in days_cur]),
                    aio_block(c, site, (ps, pe), (ps, pe), [(d, d) for d in days_prev]))
    gsc_clicks = {d: v[0] for d, v in g.items()}
    gsc_impr = {d: v[1] for d, v in g.items()}
    cmp_label = (f"T{ps.month}/{ps:%y}" if month else f"Tuần {ps:%d/%m}" + (f"/{ps:%Y}" if ps.year != ws.year else ""))
    # ↑ dòng so sánh trong ô (gọn cho vừa ô): "Tuần 14/09: 73 · +15"; đủ ngày ở tiêu đề "So với tuần 14/09 – 20/09"
    trend_note = (f"Biểu đồ: từng ngày {ws:%d/%m} – {we:%d/%m} (nét liền) so với {ps:%d/%m} – {pe:%d/%m} (nét đứt). ")
    prev_label = period_text(kind, (ps, pe), ws.year)

    @ui.refreshable
    def verdict():
        """Một câu trả lời "kỳ này tốt hay xấu" ở đầu trang. Báo cáo đã có nhận xét viết tay thì không cần."""
        if report and rep.note:
            return
        parts = []
        o = rep.organic
        if state["ai_loading"]:
            parts.append(("Lượt truy cập từ Google", None, "…"))
        elif o and not o.get("error") and o.get("prev"):
            parts.append(("Lượt truy cập từ Google", change(o["sessions"], o["prev"]), F.n(o["sessions"])))
        else:
            sk, sp = rep.site_kpi, rep.site_prev
            if not (sk.impressions or sp.impressions):  # dự án mới, chưa lấy dữ liệu GSC
                with ui.element("div").classes("sr-verdict w-full"):
                    ui.icon("hourglass_empty", size="20px").classes("muted")
                    ui.label(f"Chưa có số liệu Google Search Console cho {unit} này.")
                return
            parts.append(("Click từ Google", change(sk.clicks, sp.clicks), F.n(sk.clicks)))
        a = rep.ai
        if a and not a.get("error") and (a.get("prev") or {}).get("sessions"):
            parts.append(("lượt từ AI", change(a["kpi"]["sessions"], a["prev"]["sessions"]),
                          F.n(a["kpi"]["sessions"])))

        def phrase(label, d, value):
            if d is None:
                return f"{label} <b>{value}</b>"
            word, color = ("tăng", T.GREEN) if d > 0 else ("giảm", T.RED) if d < 0 else ("không đổi", T.MUTED)
            pct = f" {abs(d) * 100:.1f}%".replace(".", ",") if d else ""
            return f'{label} <b style="color:{color}">{word}{pct}</b> ({value})'
        text = "; ".join(phrase(*p) for p in parts)
        rs = rank_summary(rep, rep.committed)
        if rs["total"]:
            text += f"; <b>{rs['now'][10]}/{rs['total']}</b> từ khóa {'cam kết ' if rs['committed'] else ''}trong top 10"
        with ui.element("div").classes("sr-verdict w-full"):
            ui.icon("insights", size="20px").style(f"color:{T.GREEN}")
            ui.html(f"<span>{unit.capitalize()} này: {text}.</span>")

    verdict()
    kpi_box = ui.column().classes("w-full")

    @ui.refreshable
    def seo_section():
        sk, sp = rep.site_kpi, rep.site_prev
        o = rep.organic
        with T.section(ui, "Kết quả SEO", "travel_explore", f"Khách đến từ Google · so với {prev_label}",
                       href="/url", link_text="Xem theo trang"):
            if state["ai_loading"]:
                o_metric = {"value": "…", "data": None, "hint": "Đang tải…"}
            elif not o or o.get("error"):
                o_metric = {"value": "chưa có", "data": None,
                            "hint": "Chưa kết nối GA4" if not o else "Lỗi lấy số GA4"}
            else:
                o_metric = {"value": F.n(o["sessions"]), "delta": F.delta_pct(o["change"], o["prev"]),
                            "prev": F.vs_parts(o["sessions"], o["prev"], label=cmp_label),
                            "good": T.good_of(o["change"]), "data": o.get("cur_days"),
                            "compare": o.get("prev_days"), "hint": "Kênh Organic"}
            dc, di = change(sk.clicks, sp.clicks), change(sk.impressions, sp.impressions)
            T.trend_chart(ui, [
                {"key": "sessions", "label": "Lượt truy cập", "color": T.GREEN, "icon": "groups", "on": True,
                 "axis": "traffic", "zero": True, "source": "Nguồn: Google Analytics (GA4)", **o_metric},
                {"key": "clicks", "label": "Click", "color": T.BLUE, "value": F.n(sk.clicks), "delta": F.delta_pct(dc),
                 "prev": F.vs_parts(sk.clicks, sp.clicks, label=cmp_label),
                 "good": T.good_of(dc), "data": [gsc_clicks.get(d) for d in days_cur],
                 "compare": [gsc_clicks.get(d) for d in days_prev], "on": True,
                 "axis": "traffic", "zero": True, "hint": "Click từ Google",
                 "source": "Nguồn: Google Search Console"},
                {"key": "impr", "label": "Lượt hiển thị", "color": "#0E7C86", "value": F.n(sk.impressions),
                 "delta": F.delta_pct(di), "good": T.good_of(di), "data": [gsc_impr.get(d) for d in days_cur],
                 "compare": [gsc_impr.get(d) for d in days_prev],
                 "prev": F.vs_parts(sk.impressions, sp.impressions, label=cmp_label),
                 "zero": True, "hint": "Lần hiện trên Google", "source": "Nguồn: Google Search Console"},
            ], wl, compare_labels=cl)
            ui.label(trend_note + "Bấm ô để bật / tắt đường. Lượt truy cập và click đo bằng hai công cụ khác nhau nên "
                     "số không bằng nhau.").classes("text-xs muted")

    @ui.refreshable
    def geo_section():
        a, aio = rep.ai, rep.aio
        ad, ap = aio_days
        ad, ap = ad or {}, ap or {}
        with T.section(ui, "Kết quả GEO", "auto_awesome", "Có mặt trên ChatGPT, Gemini và câu trả lời AI của Google",
                       href="/ai", link_text="AI Search & GEO"):
            if state["ai_loading"]:
                ai_metric = {"value": "…", "data": None, "hint": "Đang tải…"}
            elif not a or a.get("error"):
                ai_metric = {"value": "chưa có", "data": None,
                             "hint": "Chưa kết nối GA4" if not a else "Lỗi lấy số GA4"}
            else:
                k, dl, pv = a["kpi"], a["deltas"], a["prev"]
                top = a["sources"][0] if a["sources"] else None
                total = sum(x["sessions"] for x in a["sources"]) or 1
                ai_metric = {"value": F.n(k["sessions"]), "delta": F.delta_pct(dl.get("sessions"), pv.get("sessions")),
                             "prev": F.vs_parts(k["sessions"], pv.get("sessions"), label=cmp_label),
                             "good": T.good_of(dl.get("sessions")), "data": (state["ai_trend"] or (None, None))[0],
                             "compare": (state["ai_trend"] or (None, None))[1],
                             "hint": (f"Chủ yếu {F.SOURCE_NAMES.get(top['source'], top['source'])} "
                                      f"{top['sessions'] / total * 100:.0f}%" if top else "ChatGPT, Gemini…")}
            if aio is None:
                aio_metric = {"value": "chưa có", "data": None, "hint": "Chưa có số"}
                share_metric = {"value": "chưa có", "data": None, "hint": "Chưa có số"}
            elif aio["impressions"] is None:
                aio_metric = {"value": "chưa có", "data": ad.get("spark"), "compare": ap.get("spark"),
                              "hint": f"Số tới {_vn_iso(aio['data_until'])}"}
                share_metric = {"value": "chưa có", "data": ad.get("share_spark"), "compare": ap.get("share_spark"),
                                "hint": "Hiển thị trong trả lời AI"}
            else:
                dp = (aio["share"] - aio["prev_share"]) if aio["share"] is not None and \
                    aio.get("prev_share") is not None else None
                aio_metric = {"value": F.n(aio["impressions"]), "delta": F.delta_pct(aio["change"], aio["prev"]),
                              "prev": F.vs_parts(aio["impressions"], aio["prev"], label=cmp_label),
                              "good": T.good_of(aio["change"]), "data": ad.get("spark"), "compare": ap.get("spark"),
                              "hint": "AI Overviews + AI Mode"}
                share_metric = {"value": F.pct(aio["share"], 1), "delta": F.delta_points(dp), "good": T.good_of(dp),
                                "prev": F.vs_parts(aio["share"], aio.get("prev_share"), "pct", label=cmp_label),
                                "data": ad.get("share_spark"), "compare": ap.get("share_spark"),
                                "hint": "Hiển thị trong trả lời AI"}
            T.trend_chart(ui, [
                {"key": "ai", "label": "Truy cập từ AI", "color": "#7C3AED", "icon": "smart_toy", "on": True,
                 "kind": "bar", "source": "ChatGPT, Gemini, Perplexity… · Nguồn: Google Analytics (GA4)", **ai_metric},
                {"key": "share", "label": "Tỷ lệ hiện trong AI", "color": "#B7791F", "icon": "pie_chart",
                 "fmt": "pct", "on": True, "source": "Nguồn: Google Search Console", **share_metric},
                {"key": "aio", "label": "Lượt hiện trong AI", "color": T.BLUE, "icon": "lightbulb",
                 "source": "Câu trả lời AI của Google · Nguồn: Google Search Console", **aio_metric},
            ], wl, compare_labels=cl)
            ui.label("Cột: lượt vào site từ trợ lý AI. Đường: phần lượt hiển thị Google nằm trong câu trả lời AI. "
                     "Hai số đo riêng, không cộng với nhau.").classes("text-xs muted")

    @ui.refreshable
    def rank_block():
        rank_overview(ui, rank_summary(rep, rep.committed), unit, rep.kpi)

    async def load_kpi():
        from .report import kpi_for_report
        from .web_kpi import kpi_block

        def work():
            from contextlib import closing
            with closing(db.connect(cfg.db_path)) as c:
                return kpi_for_report(cfg, c, rep)
        try:
            p = await run.io_bound(work)
        except (Exception, SystemExit):  # noqa: BLE001  (lỗi KPI không làm hỏng màn)
            return
        rep.kpi = p
        rank_block.refresh()  # ô thứ hạng so với cam kết
        if not p:
            return
        if not p.get("start") or not any(m["status"] != "future" for m in p["months"]):
            # Chưa bắt đầu (hoặc chưa nhập ngày): không chiếm khối đầu trang, chỉ một nhãn dẫn tới trang KPI
            if report or (not p.get("start") and not ed):
                return
            first = p["months"][0]["from"] if p.get("start") and p["months"] else None
            with kpi_slot:
                with ui.link(target="/kpi").classes("sr-kpi-chip"):
                    ui.icon("flag", size="16px")
                    ui.label(f"KPI cam kết bắt đầu {_vn_iso(first)}" if first else "KPI: chưa nhập ngày bắt đầu")
            return
        with kpi_box:
            kpi_block(ui, p)

    with ui.element("div").classes("sr-two w-full"):  # màn rộng: SEO | GEO cạnh nhau
        seo_section()
        geo_section()
    rank_block()
    if report:
        work_section(ui, rep, unit)
        notes_section(ui, rep)
        if month:
            with ui.expansion("Phụ lục: chi tiết tháng", icon="table_rows",
                              caption="Thứ hạng từng từ khóa, theo loại trang, top trang và top từ khóa").classes(
                    "w-full sr-card"):
                with ui.column().classes("w-full gap-4 q-pa-sm"):
                    rank_section(ui, rep, site)
                    month_sections(ui, rep, site)
    elif ed:  # "Cần xử lý" là việc của team, người chỉ xem không thấy
        todo_section(ui, cfg, connect, rep, ctx, site)

    async def load_ai():
        def work():
            from contextlib import closing

            from .report import organic_block
            with closing(db.connect(cfg.db_path)) as c:
                a = ai_block(cfg, c, (ws, we), (ps, pe))
                o = organic_block(cfg, c, (ws, we), (ps, pe), rep.trend_periods)
                pts = None
                if a and not a.get("error"):
                    from . import auth, ga4_query
                    from .ai_analytics import AIAnalytics
                    ai = AIAnalytics(ga4_query.GA4Client(
                        auth.build_ga4_data(auth.get_credentials(cfg, need=auth.ALL_SCOPES)), cfg.ga4_property, c))
                    # Phiên AI từng ngày của kỳ đang xem và kỳ so sánh
                    t = ai.trend(min(ws, ps), max(we, pe), interval="day")
                    daily = {date(int(p["date"][:4]), int(p["date"][4:6]), int(p["date"][6:])): p.get("AI Assistants", 0)
                             for p in t["data"].get("points", [])}
                    pts = (day_values(daily, (ws, we)), day_values(daily, (ps, pe)))
                return a, o, pts
        try:
            rep.ai, rep.organic, state["ai_trend"] = await run.io_bound(work)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            rep.ai = rep.organic = {"error": str(e)}
        state["ai_loading"] = False
        verdict.refresh()
        seo_section.refresh()
        geo_section.refresh()

    background_tasks.create(load_kpi())
    background_tasks.create(load_ai())


def _vn_iso(iso) -> str:
    return f"{str(iso)[8:10]}/{str(iso)[5:7]}" if iso else "–"


def _skeleton_tile(ui) -> None:
    with ui.element("div").classes("sr-card sr-kpi q-pa-md"):
        T.skeleton(ui).classes("w-full").style("height: 96px; border-radius: 10px")


def _rank_goal(p: dict | None) -> dict | None:
    """Mức cam kết thứ hạng để so: tháng KPI đang chạy (hoặc tháng vừa chốt); dự án chưa bắt đầu thì tháng 1."""
    if not p or not p.get("start") or not p.get("months"):
        return None
    started = [m for m in p["months"] if m["status"] != "future"]
    m = next((x for x in started if x["status"] == "running"), started[-1] if started else p["months"][0])
    label = (f"Đang so với KPI tháng {m['n']} ({_vn_iso(m['from'])} – {_vn_iso(m['to'])})"
             + ("" if started else " · dự án chưa bắt đầu") + " · % đạt = số từ khóa hiện có / số từ khóa cam kết")
    later = [x for x in p["months"] if x["n"] >= m["n"]]  # tháng này rồi các tháng sau
    return {"m": m, "months": later, "running": m["status"] != "closed", "label": label}


RANK_ICONS = {3: "emoji_events", 5: "workspace_premium", 10: "military_tech"}


def rank_overview(ui, rs: dict, unit: str, kpi: dict | None = None) -> None:
    """Thứ hạng cho người đọc: số từ khóa trong top 3/5/10 (so với lần đo trước, so với cam kết KPI) và 3 từ tăng /
    giảm mạnh nhất."""
    title = "Thứ hạng từ khóa cam kết" if rs["committed"] else "Thứ hạng từ khóa theo dõi"
    sub = "Đo trên Google điện thoại tại Việt Nam · lần đo mới nhất so với lần trước"
    with T.section(ui, title, "leaderboard", (f"{rs['total']} từ khóa · " if rs["total"] else "") + sub, href="/rank",
                   link_text="Thứ hạng"):
        if not rs["total"]:
            ui.label(f"Chưa có lần check rank nào trong {unit} này.").classes("text-sm muted")
            return
        # Ba ô lớn Top 3 / 5 / 10: số từ khóa, so với lần đo trước và mức đạt so với cam kết KPI
        goal = _rank_goal(kpi)
        with ui.element("div").classes("sr-rank-tiles w-full"):
            for n in (3, 5, 10):
                now, prev = rs["now"][n], rs["prev"][n]
                diff = now - prev if rs["has_prev"] else None
                # Tháng hiện tại chưa cam kết hạng (thường 1–2 tháng đầu) thì so với mức cam kết gần nhất sắp tới
                gm = next((x for x in goal["months"] if (x.get("targets") or {}).get(f"top{n}") is not None),
                          None) if goal else None
                line = KP.find_line(kpi, f"top{n}") if gm else None
                need, target = (None, None)
                if line:  # bộ riêng: mẫu số là số từ khóa của bộ đó (tháng đã chấm), không phải cả danh sách
                    pool = ((gm.get("checks") or {}).get(f"top{n}") or {}).get("total") or rs["total"]
                    need, target = KP.rank_need(line, gm["targets"][f"top{n}"], pool)
                ratio = now / need if need else None
                tone = "" if ratio is None else ("good" if ratio >= 1 else
                                                 ("warn" if goal["running"] or gm is not goal["m"] else "bad"))
                # Ô kiểu thẻ xếp hạng: tên + % bộ từ khóa (trên) · số từ khóa / tổng + mức tăng giảm (giữa) ·
                # vạch kẻ · ngày lần check đem so và số lần đó (dưới) · mức cam kết (nếu có)
                with ui.element("div").classes(f"sr-rank-tile {tone}"):
                    with ui.element("div").classes("sr-rank-head"):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.icon(RANK_ICONS[n], size="18px").classes(f"sr-rank-ico t{n}").props(
                                'aria-hidden="true"')
                            ui.label(f"Top {n}").classes("sr-rank-name")
                            T.info_icon(ui, f"Top {n}", (
                                f"Số từ khóa trong bộ đang ở vị trí 1–{n} trên Google.",
                                "Từ khóa càng lên cao càng nhiều click; vào top 3 thường lấy phần lớn click.",
                                "Lần check thứ hạng mới nhất trong kỳ, Google điện thoại tại Việt Nam. % là phần của "
                                "cả bộ từ khóa."))
                        ui.label(f"{now / rs['total'] * 100:.0f}%").classes("sr-rank-share num").props[
                            "title"] = "Phần của cả bộ từ khóa"
                    with ui.element("div").classes("sr-rank-main"):
                        ui.html(f'<div class="sr-rank-num num">{now}<span>/ {rs["total"]} từ khóa</span></div>')
                        if diff is not None:  # lần đo đầu tiên: dòng dưới đã ghi, không thêm nhãn "mới" trùng ý
                            ui.label(f"▲ {diff}" if diff > 0 else f"▼ {-diff}" if diff < 0 else "= 0").classes(
                                "sr-rank-move num " + ("up" if diff > 0 else "down" if diff < 0 else "flat")
                            ).props["title"] = f"So với lần trước: {diff:+d} từ khóa"
                    with ui.element("div").classes("sr-rank-foot"):
                        pd = rs.get("prev_date")
                        ui.label(f"So với {date.fromisoformat(pd):%d/%m}" if pd and diff is not None
                                 else "Lần đo đầu tiên")
                        if diff is not None:
                            ui.html(f'Trước đó <b class="num">{prev}</b>')
                    if need:
                        when = "" if gm is goal["m"] else f" tháng {gm['n']}"
                        pct = f"{target * 100:.0f}% " if target is not None else ""
                        ui.label(f"Cam kết{when}: {pct}({need} từ khóa) · đạt {ratio * 100:.0f}%"
                                 ).classes("sr-rank-goal")
                    else:
                        ui.label("Chưa có cam kết").classes("sr-rank-goal none")
        if goal:
            ui.label(goal["label"]).classes("text-xs muted")
        if not rs["has_prev"]:
            ui.label("Đây là lần đo đầu tiên: từ lần sau sẽ có từ khóa tăng / giảm mạnh nhất.").classes(
                "text-xs muted")
            return
        with ui.element("div").classes("w-full").style(
                "display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin-top:4px"):
            for title_, items, up in (("Tăng mạnh nhất", rs["up"], True), ("Giảm mạnh nhất", rs["down"], False)):
                with ui.element("div").classes("sr-card q-pa-md"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("trending_up" if up else "trending_down", size="18px").style(
                            f"color:{T.GREEN if up else T.RED}")
                        ui.label(title_).classes("text-sm font-semibold")
                    if not items:
                        ui.label("Chưa có lần check trước để so sánh." if not rs["has_prev"] else
                                 ("Không có từ khóa tăng." if up else "Không có từ khóa giảm.")).classes(
                            "text-sm muted q-mt-xs")
                    for m in items:
                        with ui.row().classes("items-center justify-between no-wrap w-full q-mt-xs"):
                            ui.label(m["keyword"]).classes("text-sm ellipsis")
                            frm = m["from"] if m["from"] is not None else f">{m['prev_depth']}"
                            to = m["to"] if m["to"] is not None else f">{m['depth']}"
                            ui.label(f"{frm} → {to}").classes("text-sm num font-semibold").style(
                                f"color:{T.GREEN if up else T.RED}; white-space:nowrap")


def work_section(ui, rep, unit: str) -> None:
    """Công việc đã làm trong kỳ và kế hoạch kỳ sau (OKR)."""
    from . import okr as O
    k = rep.okr
    if not k:
        return
    p, cnt = k["period"], k["counts"]
    pct = cnt[O.DONE] / k["total"] * 100 if k["total"] else 0
    with T.section(ui, "Công việc", "task_alt", f"OKR · hiện có {pct:.0f}% hạng mục đã hoàn thành"
                   + (f" · {len(k['late'])} trễ hạn" if k["late"] else ""), href="/okr", link_text="Công việc & OKR"):
        with ui.element("div").classes("w-full").style(
                "display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px"):
            for title, items, icon, color in ((f"Hoàn thành trong {unit}", p["done"], "task_alt", T.GREEN),
                                              (f"Kế hoạch {unit} sau", p["next"], "east", T.INK)):
                with ui.element("div").classes("sr-card q-pa-md"):
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        ui.icon(icon, size="18px").style(f"color:{color}")
                        ui.label(title).classes("text-sm font-semibold")
                        ui.label(str(len(items))).classes("text-xs muted num")
                    if not items:
                        ui.label("Không có").classes("text-sm muted q-mt-xs")
                    for i in items[:6]:
                        with ui.row().classes("items-center gap-2 no-wrap q-mt-xs"):
                            ui.label(i["code"]).classes("text-xs muted").style("min-width:42px")
                            ui.label(i["title"]).classes("text-sm ellipsis").tooltip(i["title"])
                    if len(items) > 6:
                        ui.label(f"và {len(items) - 6} hạng mục khác").classes("text-xs muted q-mt-xs")


def notes_section(ui, rep) -> None:
    """Tối đa 3 điểm cần chú ý, tính thẳng từ số liệu."""
    from .report import summary
    notes = summary(rep)["seo_notes"][:3]
    if not notes:
        return
    with T.section(ui, "Điểm cần chú ý", "flag_circle"):
        for n in notes:
            icon = {"up": "trending_up", "down": "trending_down", "warn": "warning"}.get(n["tone"], "info")
            color = {"up": T.GREEN, "down": T.RED, "warn": T.AMBER}.get(n["tone"], T.MUTED)
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon(icon, size="18px").style(f"color:{color}")
                ui.label(n["long"]).classes("text-sm")


def todo_rows(cfg, connect, rep, ctx) -> list[tuple]:
    """Việc cần xử lý của team: [(icon, màu, chữ, link)]."""
    from . import indexing as IX
    from . import okr as O
    from . import urls as U
    from .web_okr import _sheet_issues
    with connect() as c:
        members = U.group_members(c, ctx["group"])
        latest = IX.latest(c, [m["id"] for m in members])
        okr_items = O.overview(c, date.today())["items"] if O.sync_info(c) else []
        okr_tasks = O.tasks(c) if okr_items else []
    not_indexed = [m for m in members if m["id"] in latest and not latest[m["id"]]["indexed"]]
    dropped = [m for m in not_indexed if latest[m["id"]]["dropped"]]
    wrong = [r for r in rep.ranks if r["target_url"] and r["ranking_url"] and r["ranking_url"] != r["target_url"]]
    issues = _sheet_issues(okr_items, okr_tasks, date.today()) if okr_items else []
    rows = []
    if dropped:
        rows.append(("error", T.RED, f"{len(dropped)} URL vừa rớt khỏi index", "/index"))
    if len(not_indexed) > len(dropped):
        rows.append(("report", T.AMBER, f"{len(not_indexed) - len(dropped)} URL nhóm {rep.group} chưa được index",
                     "/index"))
    if wrong:
        rows.append(("swap_horiz", T.AMBER, f"{len(wrong)} từ khóa đang xếp hạng bằng trang khác trang mục tiêu", "/rank"))
    if issues:
        rows.append(("rule", T.AMBER, f"{len(issues)} việc OKR quá hạn hoặc chưa cập nhật trạng thái", "/okr"))
    try:  # tốc độ: website chưa đạt Core Web Vitals, trang PageSpeed dưới 50
        from . import cwv as CWV
        with connect() as c:
            phone = CWV.origin_series(c, "PHONE")
            slow = [p for p in CWV.latest_pages(c) if p["perf"] is not None and p["perf"] < 50]
        verdict = CWV.assess(phone[-1]) if phone else "none"
        if verdict in ("poor", "ni"):
            rows.append(("speed", T.RED if verdict == "poor" else T.AMBER,
                         "Website chưa đạt Core Web Vitals trên điện thoại", "/toc-do"))
        if slow:
            rows.append(("speed", T.AMBER, f"{len(slow)} trang quan trọng có điểm tốc độ dưới 50", "/toc-do"))
    except Exception:  # noqa: BLE001  (chưa có bảng / chưa cấu hình: bỏ qua)
        pass
    if rep.incomplete_days:
        rows.append(("hourglass_top", T.MUTED, f"{rep.incomplete_days} ngày trong tuần chưa có dữ liệu GSC",
                     "/ai?tab=chat-luong"))
    return rows


def todo_section(ui, cfg, connect, rep, ctx, site, rows: list | None = None) -> None:
    """Tổng quan (nội bộ): việc cần xử lý. Không đưa vào báo cáo gửi đi. rows: kết quả todo_rows nếu đã tính."""
    if rows is None:
        rows = todo_rows(cfg, connect, rep, ctx)
    with ui.element("div").classes("w-full").props('id="can-xu-ly"'),             T.section(ui, "Cần xử lý", "checklist", "Việc của team · không có trong báo cáo gửi đi"):
        if not rows:
            with ui.row().classes("items-center gap-2"):
                ui.icon("check_circle", size="18px").style(f"color:{T.GREEN}")
                ui.label("Không có việc cần xử lý.").classes("text-sm")
            return
        for icon, color, text, href in rows:
            with ui.link(target=href).classes("sr-todo w-full no-underline"):
                ui.icon(icon, size="18px").style(f"color:{color}")
                ui.label(text).classes("text-sm col")
                ui.icon("chevron_right", size="18px").classes("muted")


def health_strip(ui, cfg, connect, rep) -> None:
    """Một dòng trạng thái dữ liệu (chi tiết ở màn Chất lượng dữ liệu)."""
    from . import ai_quality as Q
    with connect() as c:
        gsc = Q.gsc_status(c, cfg.site_url, date.today())
    daily = Q.daily_job_status(cfg.db_path.parent / "sync.log", date.today())
    tone = {Q.OK: "green", Q.WARN: "amber", Q.ERROR: "red", Q.INFO: "grey"}
    icon = {Q.OK: "check_circle", Q.WARN: "warning", Q.ERROR: "error", Q.INFO: "info"}
    short = {"GSC_FRESHNESS": "GSC", "GSC_GAPS": "GSC thiếu ngày", "GENERATIVE_AI_FRESHNESS": "AI Overviews",
             "NO_GENERATIVE_AI_SOURCE": "AI Overviews: chưa nhập", "DAILY_JOB": "Lịch hằng ngày", "GSC_NO_DATA": "GSC"}
    # Một chỉ báo gọn thay cho hàng nhãn nhỏ: ổn hết thì "Dữ liệu đầy đủ", có vấn đề thì nêu số cảnh báo; chi tiết
    # từng nguồn trong chú thích, bấm để mở màn Chất lượng dữ liệu.
    checks = [c_ for c_ in gsc + [daily] if not (c_["code"] == "GSC_GAPS" and c_["status"] == Q.OK)]
    order = [Q.ERROR, Q.WARN, Q.INFO, Q.OK]
    worst = min((c_["status"] for c_ in checks), key=order.index, default=Q.OK)
    bad = [c_ for c_ in checks if c_["status"] in (Q.ERROR, Q.WARN)]
    text = "Dữ liệu đầy đủ" if not bad else f"Dữ liệu: {len(bad)} cảnh báo"
    link = ui.link(target="/ai?tab=chat-luong").classes("sr-data-ok")
    with link:
        ui.icon(icon[worst], size="16px").style(f"color:{T.TONES[tone[worst]][1]}")
        ui.label(text)
        with ui.tooltip().props("max-width=360px"):
            for chk in checks:
                m = re.search(r"tới (\d{4})-(\d{2})-(\d{2})|cuối (\d{2}/\d{2})", chk["title"])
                when = (f" {m.group(3)}/{m.group(2)}" if m.group(1) else f" {m.group(4)}") if m else ""
                ui.label(f"{'✓' if chk['status'] == Q.OK else '!'} {short.get(chk['code'], chk['title'])}{when}"
                         + (f": {chk['detail']}" if chk["detail"] and chk["status"] != Q.OK else ""))
            ui.label("Bấm để mở màn Chất lượng dữ liệu").classes("muted")
    link.props["aria-label"] = text + ". Mở màn Chất lượng dữ liệu"



def rank_section(ui, rep, site) -> None:
    with T.section(ui, f"Rank thực tế · {len(rep.ranks)} keyword", "leaderboard",
                   "DataForSEO, mobile toàn VN · " + ("lần check cuối trong tháng so với cuối tháng trước"
                                                      if rep.kind == "month" else
                                                      "lần check mới nhất đến hết tuần kế tiếp"), href="/rank"):
        if not rep.ranks:
            T.empty_state(ui, "leaderboard", "Chưa có lần check rank nào trong khoảng này")
            return
        with ui.row().classes("gap-2"):
            tones = {"Top 3": "green", "Top 4–10": "lime", "Top 11–30": "amber", "Ngoài top 30": "grey",
                     "Ngoài độ sâu check": "grey"}
            for b in BUCKETS:
                now_n, prev_n = rep.rank_buckets[b]
                if now_n or prev_n:
                    diff = now_n - prev_n
                    T.status_chip(ui, f"{b}: {now_n}" + (f" ({diff:+d})" if diff else ""), tones[b])
        from .report import rank_change
        rows = []
        for i, r in enumerate(rep.ranks):
            text, color, _ = rank_change(r["date"], r["rank"], r["depth"], r["prev"], r["prev_depth"])
            tone = next((t for lim, t in RANK_TONE if r["rank"] is not None and r["rank"] <= lim), "grey")
            rows.append({"id": i, "keyword": r["keyword"], "rank": r["rank"] if r["rank"] is not None else
                         f">{r['depth']}", "tone": T.TONES[tone][1], "bg": T.TONES[tone][0], "moved": text,
                         "moved_color": color, "date": f"{r['date'][8:10]}/{r['date'][5:7]}",
                         "url": _short(r["ranking_url"], site),
                         "wrong": bool(r["target_url"] and r["ranking_url"] and r["ranking_url"] != r["target_url"])})
        tbl = ui.table(columns=[
            {"name": "keyword", "label": "Keyword", "field": "keyword", "align": "left"},
            {"name": "rank", "label": "Vị trí", "field": "rank", "align": "center"},
            {"name": "moved", "label": "Thay đổi", "field": "moved", "align": "center"},
            {"name": "url", "label": "URL đang xếp hạng", "field": "url", "align": "left"},
        ], rows=rows, row_key="id", pagination=8).classes("w-full").props("flat dense")
        tbl.add_slot("body-cell-rank", """
            <q-td :props="props" class="text-center">
              <span :style="{background: props.row.bg, color: props.row.tone, borderRadius: '6px', padding: '2px 8px',
                             fontWeight: 700}">{{ props.value }}</span>
            </q-td>""")
        tbl.add_slot("body-cell-moved", """
            <q-td :props="props" class="text-center">
              <span :style="{color: props.row.moved_color, fontWeight: 600, whiteSpace: 'nowrap'}">{{ props.value }}</span>
            </q-td>""")
        tbl.add_slot("body-cell-url", """
            <q-td :props="props">
              <span :title="props.value + ' · check ' + props.row.date" class="ellipsis inline-block"
                    style="max-width: 240px; vertical-align: bottom">{{ props.value }}</span>
              <q-icon v-if="props.row.wrong" name="warning" color="orange-8" size="16px" class="q-ml-xs">
                <q-tooltip>Khác URL mục tiêu</q-tooltip></q-icon>
            </q-td>""")



def month_sections(ui, rep, site) -> None:
    """Phần chỉ có ở báo cáo tháng: theo loại trang, top URL, top query."""
    pct = "val => val === null || val === undefined ? '–' : (val > 0 ? '+' : '') + (val * 100).toLocaleString(" \
          "'vi-VN', {maximumFractionDigits: 1}) + '%'"
    num = "val => val === null || val === undefined ? '–' : val.toLocaleString('vi-VN')"

    def change_slot(tbl):
        tbl.add_slot("body-cell-change", """
            <q-td :props="props">
              <span :style="{color: props.row.change > 0 ? '#1E7C31' : (props.row.change < 0 ? '#C2410C' : '#8C8A7E'),
                             fontWeight: 600}">{{ props.value }}</span>
            </q-td>""")

    with T.section(ui, "Theo loại trang", "category", "Click tháng này so với tháng trước · cộng theo URL nên tổng "
                                                     "khác tổng toàn site"):
        tbl = ui.table(columns=[
            {"name": "type", "label": "Loại trang", "field": "type", "align": "left"},
            {"name": "clicks", "label": "Click", "field": "clicks", "align": "right"},
            {"name": "prev_clicks", "label": "Tháng trước", "field": "prev_clicks", "align": "right", ":format": num},
            {"name": "change", "label": "Thay đổi", "field": "change", "align": "right", ":format": pct},
            {"name": "impressions", "label": "Impression", "field": "impressions", "align": "right", ":format": num},
        ], rows=rep.by_type, row_key="type").classes("w-full").props("flat dense")
        T.bar_slot(tbl, "clicks", max((r["clicks"] for r in rep.by_type), default=1))
        change_slot(tbl)
    with ui.row().classes("w-full gap-4 items-stretch"):
        with ui.element("div").style("flex: 1 1 460px; min-width: 0"):
            with T.section(ui, "Top 10 URL của tháng", "star", "Toàn site, theo click"):
                tbl = ui.table(columns=[
                    {"name": "url", "label": "URL", "field": "url", "align": "left", "classes": "ellipsis",
                     "style": "max-width: 260px", "headerStyle": "max-width: 260px"},
                    {"name": "clicks", "label": "Click", "field": "clicks", "align": "right"},
                    {"name": "change", "label": "Thay đổi", "field": "change", "align": "right", ":format": pct},
                ], rows=[{**r, "url": _short(r["url"], site)} for r in rep.top_urls], row_key="url").classes(
                    "w-full").props("flat dense")
                T.bar_slot(tbl, "clicks", max((r["clicks"] for r in rep.top_urls), default=1))
                change_slot(tbl)
        with ui.element("div").style("flex: 1 1 460px; min-width: 0"):
            with T.section(ui, "Top 10 từ khóa của tháng", "search", "Query theo click · GSC ẩn query hiếm"):
                tbl = ui.table(columns=[
                    {"name": "query", "label": "Query", "field": "query", "align": "left", "classes": "ellipsis",
                     "style": "max-width: 260px", "headerStyle": "max-width: 260px"},
                    {"name": "clicks", "label": "Click", "field": "clicks", "align": "right"},
                    {"name": "change", "label": "Thay đổi", "field": "change", "align": "right", ":format": pct},
                ], rows=rep.top_queries, row_key="query").classes("w-full").props("flat dense")
                T.bar_slot(tbl, "clicks", max((r["clicks"] for r in rep.top_queries), default=1))
                change_slot(tbl)
