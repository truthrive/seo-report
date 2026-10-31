"""Màn Tổng quan (trang chủ) và Báo cáo tuần/tháng: cùng các khối số. Tổng quan để làm việc hằng ngày (có sức khỏe
dữ liệu, bấm vào khối để đi sâu); Báo cáo là bản gửi sếp của chính các khối đó (thêm nhận xét, xuất Excel). Báo cáo
tháng thêm xu hướng 12 tháng, theo loại trang, top URL và top query.

Số GSC/rank/index đọc từ SQLite nên hiện ngay; số GA4 tải trong luồng nền rồi điền vào khối AI.
"""
import re
from datetime import date, timedelta

from . import ai_format as F
from . import ui_theme as T
from .report import BUCKETS, build, build_month, change, note_key, save_note

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
        + f" · nhóm {rep.group} · {site.split('//')[-1].strip('/')}")
    with right:
        if report:
            from .report_slides import build_report_pptx, slides_filename
            from .report_excel import build_report_excel
            from .web_export import export_menu

            async def with_ai():
                """Xuất trước khi khối AI tải xong thì lấy số GA4 ngay để file luôn đủ."""
                if rep.ai is None or state["ai_loading"]:
                    def work():
                        from contextlib import closing
                        with closing(db.connect(cfg.db_path)) as c:
                            return ai_block(cfg, c, (ws, we))
                    rep.ai = await run.io_bound(work)

            async def make_xlsx():
                await with_ai()
                return await run.io_bound(lambda: build_report_excel(rep, user))

            async def make_pptx():
                await with_ai()
                return await run.io_bound(lambda: build_report_pptx(rep, user))

            export_menu(ui, cfg, connect, slides_filename(rep), make_xlsx, make_pptx, "Xuất báo cáo", user=user)
        else:
            ui.button("Bản gửi sếp", icon="summarize", on_click=lambda: ui.navigate.to("/report")).props(
                "outline no-caps")

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
        with T.section(ui, "Nhận xét gửi sếp", "edit_note", "Hiện ở đầu file Excel"):
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
    else:
        health_strip(ui, cfg, connect, rep)

    @ui.refreshable
    def summary_section():
        """Khối đầu trang Báo cáo = trang 2 của slide/PDF, dạng bento: một hộp bo tròn chia ô to nhỏ. Hai ô lớn cho số
        chính (Click, Phiên AI) kèm biểu đồ nhỏ; ô nhỏ cho các số còn lại; một ô "cần xem" gom các điểm nổi bật."""
        if not report:
            return
        from .report import summary
        sm = summary(rep)
        seo = {it["short"]: it for it in sm["seo"]}
        geo = {it["short"]: it for it in sm["geo"]}
        loading = state["ai_loading"]

        def eyebrow(text, tone):
            ui.label(text).classes("sr-bento-eyebrow").style(f"color:{T.TONES[tone][1]}")

        def big(it, tone, area, spark, notes, labels):
            with ui.element("div").classes("sr-bento-tile big"):
                eyebrow(area, tone)
                ui.label(it["label"]).classes("text-sm muted").style("line-height:1.3")
                with ui.row().classes("items-baseline gap-2 no-wrap"):
                    ui.label(it["value"]).classes("sr-bento-hero num")
                    if it["delta"]:
                        T.delta_badge(ui, it["delta"], it["good"])
                with ui.element("div").classes("w-full").style("margin-top:auto"):
                    T.sparkline(ui, spark or [], T.TONES[tone][1], height=56, labels=labels)
                if notes:
                    with ui.row().classes("gap-2"):
                        for n in notes:
                            with ui.element("div"):
                                T.status_chip(ui, n["short"], "grey", "insights")
                                ui.tooltip(n["long"])

        def small(it, tone):
            with ui.element("div").classes("sr-bento-tile"):
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.element("span").classes("sr-dot").style(f"background:{T.TONES[tone][1]}")
                    ui.label(it["short"]).classes("text-xs muted ellipsis").tooltip(it["label"])
                ui.label(it["value"]).classes("sr-metric-value num")
                if it["delta"]:
                    T.delta_badge(ui, it["delta"], it["good"])

        def skeleton_tile(cls=""):
            with ui.element("div").classes(f"sr-bento-tile {cls}"):
                T.skeleton(ui).classes("w-full").style("height: 100%; min-height: 70px; border-radius: 12px")

        wl = [t["week"] for t in rep.trend]
        with ui.element("div").classes("sr-bento w-full"):
            big(seo["Click"], "green", "SEO · Google Search", [t["site_clicks"] for t in rep.trend], [], wl)
            if loading:
                skeleton_tile("big")
            else:
                ai_weeks = [f"{we - timedelta(days=7 * i + 6):%d/%m}" for i in range(7, -1, -1)]  # 8 tuần GA4
                big(geo["Phiên AI"], "purple", "GEO · AI Search", state["ai_trend"], sm["geo_notes"], ai_weeks)
            for key in ("Impression", "Top 10", "Index"):
                small(seo[key], "green")
            if loading:
                skeleton_tile()
                skeleton_tile()
                skeleton_tile()
            else:
                for key in ("Key events AI", "AI Overviews", "% trên Google"):
                    small(geo[key], "purple")
            with ui.element("div").classes("sr-bento-tile wide"):
                eyebrow("Cần xem", "amber")
                if not sm["seo_notes"]:
                    ui.label("Không có điểm bất thường.").classes("text-sm muted")
                for n in sm["seo_notes"]:
                    icon = {"up": "trending_up", "down": "trending_down", "warn": "warning"}.get(n["tone"], "info")
                    color = {"up": T.GREEN, "down": T.RED, "warn": T.AMBER}.get(n["tone"], T.MUTED)
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        ui.icon(icon, size="16px").style(f"color:{color}")
                        ui.label(n["long"]).classes("text-sm ellipsis").tooltip(n["long"])

    # ---- Tiến độ KPI cam kết (sheet KPI; chỉ hiện khi đã có) ----
    kpi_box = ui.column().classes("w-full")

    async def load_kpi():
        from .web_kpi import kpi_block, load_progress
        try:
            p = await run.io_bound(lambda: load_progress(cfg))
        except (Exception, SystemExit):  # noqa: BLE001  (lỗi KPI không làm hỏng màn tổng quan)
            return
        with kpi_box:
            kpi_block(ui, p)

    background_tasks.create(load_kpi())

    summary_section()

    # ---- Google Search ----
    tr = rep.trend
    wl = [t["week"] for t in tr]
    sk, sp, gk, gp = rep.site_kpi, rep.site_prev, rep.group_kpi, rep.group_prev
    with T.section(ui, "Google Search (GSC)", "travel_explore", "Toàn site theo tổng của property; nhóm theo URL "
                                                               "trong nhóm", href="/url", link_text="Xem theo URL"):
        with T.kpi_row(ui):
            d = change(sk.clicks, sp.clicks)
            T.kpi(ui, "ads_click", "Click toàn site", _n(sk.clicks), F.delta_pct(d), T.good_of(d),
                  spark=[t["site_clicks"] for t in tr], spark_labels=wl, hint=f"{len(tr)} {unit} gần nhất")
            d = change(sk.impressions, sp.impressions)
            T.kpi(ui, "visibility", "Impression toàn site", _n(sk.impressions), F.delta_pct(d), T.good_of(d),
                  spark=[t.get("site_impressions") for t in tr], spark_labels=wl, tone="blue")
            d = (sk.ctr - sp.ctr) if sk.ctr is not None and sp.ctr is not None else None
            T.kpi(ui, "percent", "CTR toàn site", F.pct(sk.ctr, 1), F.delta_points(d),
                  T.good_of(d), spark=[t.get("site_ctr") for t in tr], spark_labels=wl, spark_fmt="pct", tone="lime")
            d = change(gk.clicks, gp.clicks)
            T.kpi(ui, "folder_special", f"Click nhóm {rep.group}", _n(gk.clicks), F.delta_pct(d), T.good_of(d),
                  spark=[t["group_clicks"] for t in tr], spark_labels=wl, tone="purple",
                  hint=f"{gk.clicks / sk.clicks * 100:.0f}% click toàn site".replace(".", ",") if sk.clicks else "")
        ui.echart({
            "tooltip": {"trigger": "axis"}, "legend": {"bottom": 0, "icon": "roundRect"},
            "grid": {"left": 56, "right": 56, "top": 24, "bottom": 40},
            "xAxis": {"type": "category", "data": [t["week"] for t in tr], "axisTick": {"show": False}},
            "yAxis": [{"type": "value", "name": "Click", "splitLine": {"lineStyle": {"color": "#EEECE4"}}},
                      {"type": "value", "name": "Impression", "splitLine": {"show": False}}],
            "series": [
                {"name": "Click toàn site", "type": "bar", "data": [t["site_clicks"] for t in tr], "barWidth": "38%",
                 "itemStyle": {"color": T.GREEN, "borderRadius": [4, 4, 0, 0]}},
                {"name": f"Click nhóm {rep.group}", "type": "bar", "data": [t["group_clicks"] for t in tr],
                 "barWidth": "38%", "itemStyle": {"color": T.LIME, "borderRadius": [4, 4, 0, 0]}},
                {"name": "Impression toàn site (trục phải)", "type": "line", "yAxisIndex": 1, "smooth": True,
                 "symbol": "circle", "symbolSize": 5, "data": [t.get("site_impressions") for t in tr],
                 "itemStyle": {"color": T.BLUE}},
            ]}).classes("w-full q-mt-md").style("height: 260px")
        ui.label("Position TB của GSC là trung bình, không phải thứ hạng thực tế: thứ hạng xem ở khối Rank.").classes(
            "text-xs muted")

    # ---- AI: hai nguồn tách riêng ----
    with ui.row().classes("w-full gap-4 items-stretch"):
        with ui.element("div").style("flex: 3 1 520px; min-width: 0"):
            ai_box = ui.element("div").classes("w-full")
        with ui.element("div").style("flex: 2 1 380px; min-width: 0"):
            aio_section(ui, rep, unit)

    @ui.refreshable
    def ai_section():
        a = rep.ai
        with T.section(ui, "Traffic từ AI assistant (GA4)", "auto_awesome", "ChatGPT, Gemini, Claude… · không gồm "
                                                                           "AI Overviews", href="/ai"):
            if state["ai_loading"]:
                with ui.row().classes("w-full gap-3"):
                    for _ in range(3):
                        T.skeleton(ui).classes("col").style("height: 110px; border-radius: 12px")
                return
            if a is None:
                ui.label("Chưa kết nối GA4.").classes("text-sm muted")
                return
            if a.get("error"):
                T.status_chip(ui, f"Chưa lấy được số liệu GA4: {a['error'][:120]}", "red", "cloud_off")
                return
            k, dl, pv = a["kpi"], a["deltas"], a["prev"]
            pts = state["ai_trend"] or []
            with T.kpi_row(ui):
                T.kpi(ui, "smart_toy", "Phiên AI", F.n(k["sessions"]), F.delta_pct(dl.get("sessions"),
                                                                                 pv.get("sessions")),
                      T.good_of(dl.get("sessions")), spark=pts, spark_kind="bar",
                      hint=f"{F.pct(a['share']['ofAllSessions'])} tổng phiên site · biểu đồ 8 tuần"
                      + (f" · so với {(we - ws).days + 1} ngày liền trước" if month else ""))
                T.kpi(ui, "touch_app", "Engagement rate", F.pct(k["engagementRate"], 1),
                      F.delta_points(dl.get("engagementRate")), T.good_of(dl.get("engagementRate")),
                      tone="blue", spark=[])
                T.kpi(ui, "flag", "Key events", F.n(k["keyEvents"]), F.delta_pct(dl.get("keyEvents"),
                                                                                 pv.get("keyEvents")),
                      T.good_of(dl.get("keyEvents")), tone="amber", spark=[],
                      hint=f"{F.pct(k['sessionKeyEventRate'])} phiên có key event")
            if a["sources"]:
                with ui.row().classes("gap-2 items-center"):
                    for x in a["sources"]:
                        T.status_chip(ui, f"{F.SOURCE_NAMES.get(x['source'], x['source'])} {F.n(x['sessions'])}",
                                      "grey")

    with ai_box:
        ai_section()

    async def load_ai():
        def work():
            from contextlib import closing
            with closing(db.connect(cfg.db_path)) as c:
                a = ai_block(cfg, c, (ws, we))
                pts = None
                if a and not a.get("error"):
                    from . import auth, ga4_query
                    from .ai_analytics import AIAnalytics
                    ai = AIAnalytics(ga4_query.GA4Client(
                        auth.build_ga4_data(auth.get_credentials(cfg, need=auth.ALL_SCOPES)), cfg.ga4_property, c))
                    t = ai.trend(we - timedelta(days=7 * 8 - 1), we, interval="week")
                    pts = [p.get("AI Assistants", 0) for p in t["data"].get("points", [])]
                return a, pts
        try:
            rep.ai, state["ai_trend"] = await run.io_bound(work)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            rep.ai = {"error": str(e)}
        state["ai_loading"] = False
        ai_section.refresh()
        summary_section.refresh()

    background_tasks.create(load_ai())

    # ---- Rank + Index ----
    with ui.row().classes("w-full gap-4 items-stretch"):
        with ui.element("div").style("flex: 3 1 520px; min-width: 0"):
            rank_section(ui, rep, site)
        with ui.element("div").style("flex: 2 1 380px; min-width: 0"):
            index_section(ui, connect, rep, ctx, site)

    # ---- URL tăng / giảm ----
    with ui.row().classes("w-full gap-4 items-stretch"):
        for title, icon, items, tone in [("URL tăng click", "trending_up", rep.winners, "up"),
                                         ("URL giảm click", "trending_down", rep.losers, "down")]:
            with ui.element("div").style("flex: 1 1 460px; min-width: 0"):
                with T.section(ui, f"Top {len(items)} {title}", icon, f"Nhóm {rep.group} · URL có từ 20 click"):
                    if not items:
                        ui.label("Không có URL nào.").classes("text-sm muted")
                        continue
                    tbl = ui.table(columns=[
                        {"name": "url", "label": "URL", "field": "url", "align": "left", "classes": "ellipsis", "style": "max-width: 210px", "headerStyle": "max-width: 210px"},
                        {"name": "clicks", "label": f"{unit.capitalize()} này", "field": "clicks", "align": "right"},
                        {"name": "prev", "label": "Trước", "field": "prev", "align": "right",
                         ":format": "val => val.toLocaleString('vi-VN')"},
                        {"name": "diff", "label": "Chênh", "field": "diff", "align": "right"},
                    ], rows=[{"url": _short(x["url"], site), "clicks": x["clicks"], "prev": x["prev"],
                              "diff": x["diff"]} for x in items], row_key="url").classes("w-full").props(
                        "flat dense")
                    T.bar_slot(tbl, "clicks", max(x["clicks"] for x in items))
                    color = T.GREEN if tone == "up" else T.RED
                    tbl.add_slot("body-cell-diff", f"""
                        <q-td :props="props"><span style="color:{color}; font-weight:600">
                          {{{{ (props.value > 0 ? '+' : '') + props.value.toLocaleString('vi-VN') }}}}</span></q-td>""")

    if report:
        from .web_okr import okr_report_section
        okr_report_section(ui, rep)

    if month:
        month_sections(ui, rep, site)



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


def aio_section(ui, rep, unit: str = "tuần") -> None:
    a = rep.aio
    with T.section(ui, "AI Overviews / AI Mode", "lightbulb", "Hiển thị trong câu trả lời AI của Google · GSC, nhập file",
                   href="/ai?tab=ai-google"):
        if a is None:
            T.empty_state(ui, "upload_file", "Chưa có dữ liệu", "Xuất báo cáo Generative AI từ GSC rồi nhập ở tab "
                                                               "AI trên Google")
            return
        if a["impressions"] is None:
            T.status_chip(ui, f"Chưa có số cho {unit} này · file tới {a['data_until']}", "amber", "hourglass_top")
            ui.label("Xuất file mới từ GSC và nhập ở tab AI trên Google.").classes("text-xs muted")
            return
        with T.kpi_row(ui):
            T.kpi(ui, "lightbulb", "Impression", F.n(a["impressions"]), F.delta_pct(a["change"], a["prev"]),
                  T.good_of(a["change"]), tone="amber", spark=a.get("spark"), spark_kind="bar")
            T.kpi(ui, "pie_chart", "Trên impression Web", F.pct(a["share"], 1), tone="blue", spark=[],
                  hint="phần lượt hiển thị Google nằm trong câu trả lời AI")
        ui.label("Chỉ có impression, GSC không cung cấp click riêng cho AI Overviews.").classes("text-xs muted")


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


def index_section(ui, connect, rep, ctx, site) -> None:
    from . import indexing as IX
    from . import urls as U
    with connect() as c:
        members = U.group_members(c, ctx["group"])
        latest = IX.latest(c, [m["id"] for m in members])
    total = len(members)
    checked = [latest[m["id"]] for m in members if m["id"] in latest]
    ok = sum(1 for x in checked if x["indexed"])
    dropped = sum(1 for x in checked if x["dropped"])
    bad = [m for m in members if m["id"] in latest and not latest[m["id"]]["indexed"]]
    with T.section(ui, f"Index · nhóm {rep.group}", "fact_check", "GSC URL Inspection, kiểm tra hằng ngày",
                   href="/index"):
        with T.kpi_row(ui):
            T.kpi(ui, "task_alt", "Đã index", f"{ok}/{total}", tone="green",
                  hint=f"{len(checked)} URL đã kiểm tra" if len(checked) < total else "")
            T.kpi(ui, "report" if bad else "verified", "Chưa index", F.n(len(bad)), tone="red" if bad else "green",
                  hint=f"{dropped} URL vừa rớt index" if dropped else "")
        if total:
            ui.linear_progress(ok / total, show_value=False, size="8px", color="positive").classes("rounded-borders")
        for m in bad[:5]:
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon("error_outline", size="16px").style(f"color:{T.RED}")
                ui.label(_short(m["url"], site)).classes("text-sm ellipsis")


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
