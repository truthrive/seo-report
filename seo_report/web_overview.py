"""Màn Tổng quan (trang chủ) và Báo cáo tuần/tháng: cùng các khối số. Tổng quan để làm việc hằng ngày (có sức khỏe
dữ liệu, bấm vào khối để đi sâu); Báo cáo là bản gửi người nhận báo cáo (quản lý, khách hàng) của chính các khối đó (thêm nhận xét, xuất Excel). Báo cáo
tháng thêm xu hướng 12 tháng, theo loại trang, top URL và top query.

Số GSC/rank/index đọc từ SQLite nên hiện ngay; số GA4 tải trong luồng nền rồi điền vào khối AI.
"""
import math
import re
from datetime import date, timedelta

from . import ai_format as F
from .projects import domain
from . import ui_theme as T
from .report import BUCKETS, build, build_month, change, note_key, rank_summary, save_note

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
        rep = (build_month(c, cfg, ctx["group"], ctx["month"], with_ai=False) if kind == "month"
               else build(c, cfg, ctx["group"], ctx["week"], with_ai=False))
    month = kind == "month"
    unit = "tháng" if month else "tuần"
    state = {"rep": rep, "ai_trend": None, "ai_loading": True}
    (ws, we), (ps, pe) = rep.week, rep.prev_week

    # ---- Tiêu đề ----
    right = T.page_header(
        ui, "summarize" if report else "space_dashboard",
        f"Báo cáo tháng {ws:%m/%Y}" if month else
        f"{'Báo cáo tuần' if report else 'Tổng quan'} {ws:%d/%m} – {we:%d/%m/%Y}",
        (f"So với tháng {ps:%m/%Y}" if month else f"So với tuần {ps:%d/%m} – {pe:%d/%m}")
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
                            return (ai_block(cfg, c, (ws, we)), organic_block(cfg, c, (ws, we), (ps, pe),
                                                                              rep.trend_periods),
                                    kpi_for_report(cfg, c, rep))
                    rep.ai, rep.organic, rep.kpi = await run.io_bound(work)

            async def make_xlsx():
                await with_ai()
                return await run.io_bound(lambda: build_report_excel(rep, user))

            async def make_pptx():
                await with_ai()
                return await run.io_bound(lambda: build_report_pptx(rep, user))

            export_menu(ui, cfg, connect, slides_filename(rep), make_xlsx, make_pptx, "Xuất báo cáo", user=user)
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
                                   placeholder="Ví dụ: Traffic giảm 1% do Trang chủ giảm 38 click; danh mục tròng "
                                               "kính tăng…").props("outlined autogrow").classes("col")
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
    wl = [t["week"] for t in rep.trend]
    prev_label = f"tháng {ps:%m/%Y}" if month else f"tuần {ps:%d/%m} – {pe:%d/%m}"

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
                            "hint": "Chưa kết nối GA4" if not o else "Không lấy được số GA4"}
            else:
                o_metric = {"value": F.n(o["sessions"]), "delta": F.delta_pct(o["change"], o["prev"]),
                            "good": T.good_of(o["change"]), "data": o["spark"], "hint": "Kênh Organic Search"}
            dc, di = change(sk.clicks, sp.clicks), change(sk.impressions, sp.impressions)
            T.trend_chart(ui, [
                {"key": "sessions", "label": "Lượt truy cập", "color": T.GREEN, "icon": "groups", "on": True,
                 "axis": "traffic", "zero": True, "source": "Nguồn: Google Analytics (GA4)", **o_metric},
                {"key": "clicks", "label": "Click", "color": T.BLUE, "value": F.n(sk.clicks), "delta": F.delta_pct(dc),
                 "good": T.good_of(dc), "data": [t["site_clicks"] for t in rep.trend], "on": True,
                 "axis": "traffic", "zero": True, "hint": "Lượt bấm vào site trên Google",
                 "source": "Nguồn: Google Search Console"},
                {"key": "impr", "label": "Lượt hiển thị", "color": "#0E7C86", "value": F.n(sk.impressions),
                 "delta": F.delta_pct(di), "good": T.good_of(di), "data": [t.get("site_impressions") for t in rep.trend],
                 "zero": True, "hint": "Số lần site hiện trên Google", "source": "Nguồn: Google Search Console"},
            ], wl)
            ui.label("Bấm ô để bật / tắt đường. Lượt truy cập và click đo bằng hai công cụ khác nhau nên số không "
                     "bằng nhau.").classes("text-xs muted")

    @ui.refreshable
    def geo_section():
        a, aio = rep.ai, rep.aio
        with T.section(ui, "Kết quả GEO", "auto_awesome", "Có mặt trên ChatGPT, Gemini và câu trả lời AI của Google",
                       href="/ai", link_text="AI Search & GEO"):
            if state["ai_loading"]:
                ai_metric = {"value": "…", "data": None, "hint": "Đang tải…"}
            elif not a or a.get("error"):
                ai_metric = {"value": "chưa có", "data": None,
                             "hint": "Chưa kết nối GA4" if not a else "Không lấy được số GA4"}
            else:
                k, dl, pv = a["kpi"], a["deltas"], a["prev"]
                top = a["sources"][0] if a["sources"] else None
                total = sum(x["sessions"] for x in a["sources"]) or 1
                ai_metric = {"value": F.n(k["sessions"]), "delta": F.delta_pct(dl.get("sessions"), pv.get("sessions")),
                             "good": T.good_of(dl.get("sessions")), "data": state["ai_trend"],
                             "hint": (f"Nhiều nhất: {F.SOURCE_NAMES.get(top['source'], top['source'])} "
                                      f"{top['sessions'] / total * 100:.0f}%" if top else "ChatGPT, Gemini, Perplexity…")}
            if aio is None:
                aio_metric = {"value": "chưa có", "data": None, "hint": "Chưa có số"}
                share_metric = {"value": "chưa có", "data": None, "hint": "Chưa có số"}
            elif aio["impressions"] is None:
                aio_metric = {"value": "chưa có", "data": aio.get("spark"),
                              "hint": f"Google mới có số tới {_vn_iso(aio['data_until'])}"}
                share_metric = {"value": "chưa có", "data": aio.get("share_spark"),
                                "hint": "Phần lượt hiển thị Google nằm trong câu trả lời AI"}
            else:
                dp = (aio["share"] - aio["prev_share"]) if aio["share"] is not None and \
                    aio.get("prev_share") is not None else None
                aio_metric = {"value": F.n(aio["impressions"]), "delta": F.delta_pct(aio["change"], aio["prev"]),
                              "good": T.good_of(aio["change"]), "data": aio.get("spark"),
                              "hint": "AI Overviews và AI Mode"}
                share_metric = {"value": F.pct(aio["share"], 1), "delta": F.delta_points(dp), "good": T.good_of(dp),
                                "data": aio.get("share_spark"),
                                "hint": "Phần lượt hiển thị Google nằm trong câu trả lời AI"}
            T.trend_chart(ui, [
                {"key": "ai", "label": "Truy cập từ AI", "color": "#7C3AED", "icon": "smart_toy", "on": True,
                 "kind": "bar", "source": "ChatGPT, Gemini, Perplexity… · Nguồn: Google Analytics (GA4)", **ai_metric},
                {"key": "share", "label": "Tỷ lệ hiện trong AI", "color": "#B7791F", "icon": "pie_chart",
                 "fmt": "pct", "on": True, "source": "Nguồn: Google Search Console", **share_metric},
                {"key": "aio", "label": "Lượt hiện trong AI", "color": T.BLUE, "icon": "lightbulb",
                 "source": "Câu trả lời AI của Google · Nguồn: Google Search Console", **aio_metric},
            ], wl)
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
                a = ai_block(cfg, c, (ws, we))
                o = organic_block(cfg, c, (ws, we), (ps, pe), rep.trend_periods)
                pts = None
                if a and not a.get("error"):
                    from . import auth, ga4_query
                    from .ai_analytics import AIAnalytics
                    ai = AIAnalytics(ga4_query.GA4Client(
                        auth.build_ga4_data(auth.get_credentials(cfg, need=auth.ALL_SCOPES)), cfg.ga4_property, c))
                    # Phiên AI theo đúng các kỳ của biểu đồ (8 tuần / 12 tháng): lấy theo ngày rồi cộng theo kỳ
                    periods = rep.trend_periods
                    t = ai.trend(periods[0][0], periods[-1][1], interval="day")
                    daily = {p["date"]: p.get("AI Assistants", 0) for p in t["data"].get("points", [])}
                    pts = [sum(v for d, v in daily.items() if s_.strftime("%Y%m%d") <= d <= e_.strftime("%Y%m%d"))
                           for s_, e_ in periods]
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


def rank_overview(ui, rs: dict, unit: str, kpi: dict | None = None) -> None:
    """Thứ hạng cho người đọc: số từ khóa trong top 3/5/10 (so với lần đo trước, so với cam kết KPI) và 3 từ tăng /
    giảm mạnh nhất."""
    title = "Thứ hạng từ khóa cam kết" if rs["committed"] else "Thứ hạng từ khóa theo dõi"
    sub = "Đo trên Google điện thoại tại Việt Nam · lần đo mới nhất so với lần trước"
    with T.section(ui, title, "leaderboard", (f"{rs['total']} từ khóa · " if rs["total"] else "") + sub, href="/rank",
                   link_text="Từ khóa & rank"):
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
                gm = next((x for x in goal["months"] if x.get(f"top{n}")), None) if goal else None
                target = gm.get(f"top{n}") if gm else None
                need = math.ceil(target * rs["total"] - 1e-9) if target else None
                ratio = now / need if need else None
                tone = "" if ratio is None else ("good" if ratio >= 1 else
                                                 ("warn" if goal["running"] or gm is not goal["m"] else "bad"))
                with ui.element("div").classes(f"sr-rank-tile {tone}"):
                    ui.label(f"Top {n}").classes("sr-rank-name")
                    ui.html(f'<div class="sr-rank-num num">{now}<span>/{rs["total"]}</span></div>')
                    ui.label(f"{now / rs['total'] * 100:.0f}% bộ từ khóa · " + (
                        "lần đo đầu tiên" if diff is None else f"lần trước {prev} ({diff:+d})" if diff
                        else f"lần trước {prev} (không đổi)")).classes("sr-rank-sub")
                    if need:
                        when = "" if gm is goal["m"] else f" tháng {gm['n']}"
                        ui.label(f"Cam kết{when}: {target * 100:.0f}% ({need} từ khóa) · đạt {ratio * 100:.0f}%"
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


def todo_section(ui, cfg, connect, rep, ctx, site) -> None:
    """Tổng quan (nội bộ): việc cần xử lý. Không đưa vào báo cáo gửi đi."""
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
    if rep.incomplete_days:
        rows.append(("hourglass_top", T.MUTED, f"{rep.incomplete_days} ngày trong tuần chưa có dữ liệu GSC",
                     "/ai?tab=chat-luong"))
    with T.section(ui, "Cần xử lý", "checklist", "Việc của team · không có trong báo cáo gửi đi"):
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
    with ui.row().classes("w-full items-center gap-2"):
        ui.label("Dữ liệu:").classes("text-xs muted")
        for chk in gsc + [daily]:
            if chk["code"] == "GSC_GAPS" and chk["status"] == Q.OK:
                continue
            m = re.search(r"tới (\d{4})-(\d{2})-(\d{2})|cuối (\d{2}/\d{2})", chk["title"])
            when = (f" {m.group(3)}/{m.group(2)}" if m.group(1) else f" {m.group(4)}") if m else ""
            with ui.element("div"):
                T.status_chip(ui, short.get(chk["code"], chk["title"]) + when, tone[chk["status"]],
                              icon[chk["status"]])
                ui.tooltip(chk["title"] + (". " + chk["detail"] if chk["detail"] else ""))
        ui.link("Chất lượng dữ liệu →", "/ai?tab=chat-luong").classes("text-xs no-underline q-ml-sm").style(
            f"color:{T.GREEN}")



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
