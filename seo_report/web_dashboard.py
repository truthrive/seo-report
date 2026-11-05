"""Màn Tổng quan: nhịp số liệu của website theo khoảng 7 / 28 / 90 ngày gần nhất (so với cùng số ngày liền trước).

Khác Báo cáo (bản chốt theo tuần / tháng để gửi đi): Tổng quan gom mọi nguồn vào một màn để theo dõi hằng ngày:
GSC (click, lượt hiển thị), GA4 (lượt truy cập toàn site, Organic, từ AI), GEO (tỷ lệ hiện trong AI của Google),
thứ hạng, index, KPI cam kết, OKR. Số GSC / rank / index / OKR đọc từ SQLite nên hiện ngay; GA4 và KPI tải nền.
"""
from datetime import date, timedelta

from . import access as A
from . import ai_format as F
from . import keywords as K
from . import rank as R
from . import ui_theme as T
from .projects import domain
from .report import change

WINDOWS = (7, 28, 90)
AI_PURPLE = "#7C3AED"


def windows(end: date, days: int) -> tuple[tuple[date, date], tuple[date, date]]:
    """(kỳ này, kỳ trước): `days` ngày đến hết `end`, và cùng số ngày liền trước."""
    cur = (end - timedelta(days=days - 1), end)
    return cur, (cur[0] - timedelta(days=days), cur[0] - timedelta(days=1))


def buckets(cur: tuple[date, date], days: int) -> list[tuple[date, date]]:
    """Các đoạn cho biểu đồ nhỏ: 7 ngày → từng ngày; 28 ngày → từng ngày; 90 ngày → từng tuần (13 cột)."""
    step = 7 if days > 31 else 1
    out, s = [], cur[0]
    while s <= cur[1]:
        e = min(s + timedelta(days=step - 1), cur[1])
        out.append((s, e))
        s = e + timedelta(days=1)
    return out


def gsc_daily(con, site: str, lo: date, hi: date) -> dict[date, tuple[int, int]]:
    rows = con.execute("SELECT date, clicks, impressions FROM gsc_site_daily WHERE site = ? AND date BETWEEN ? AND ?",
                       (site, lo.isoformat(), hi.isoformat())).fetchall()
    return {date.fromisoformat(d): (c or 0, i or 0) for d, c, i in rows}


def rank_snapshot(con, site: str, end: date) -> dict:
    """Ô Thứ hạng ở Tổng quan, tính giống màn Thứ hạng: Top 3 / 5 / 10 trên tổng số từ khóa (mỗi từ khóa một lần,
    ưu tiên bộ Cam kết); lên / rớt hạng so với lần check trước của chính từ khóa đó, kể cả khi một phía nằm ngoài độ
    sâu check (vào top N / rớt khỏi top N). Không có "Top 30": từ khóa chỉ check top 10 mà không thấy thì không biết
    có trong top 30 hay không."""
    from .report import rank_change
    kws = [k for k in R.primary_keywords(con, site, end) if not k.get("draft")]  # bộ Nháp chưa tính
    checked = [k for k in kws if k["date"]]
    ranked = [k["rank"] for k in checked if k["rank"] is not None]
    moves = [rank_change(k["date"], k["rank"], k["last_depth"], k["prev"], k["prev_depth"])[2] for k in checked]
    return {"total": len(kws), "checked": len(checked), "last": max((k["date"] for k in checked), default=None),
            "top3": sum(r <= 3 for r in ranked), "top5": sum(r <= 5 for r in ranked),
            "top10": sum(r <= 10 for r in ranked),
            "up": sum(m > 0 for m in moves), "down": sum(m < 0 for m in moves)}


def index_snapshot(con, site: str) -> dict:
    """Lần kiểm tra mới nhất của mỗi URL: số đã index (verdict PASS) và các lý do chưa index nhiều nhất."""
    from . import indexing as IX
    IX.ensure_tables(con)
    rows = con.execute(
        """SELECT c.verdict = 'PASS', c.coverage, COUNT(*) FROM index_checks c JOIN urls u ON u.id = c.url_id
           JOIN (SELECT url_id, MAX(checked_at) m FROM index_checks GROUP BY url_id) l
             ON l.url_id = c.url_id AND l.m = c.checked_at
           WHERE u.site = ? GROUP BY 1, 2 ORDER BY 3 DESC""", (site,)).fetchall()
    bad = [(cov, n) for ok, cov, n in rows if not ok]
    return {"total": sum(n for *_, n in rows), "ok": sum(n for ok, _, n in rows if ok),
            "fix": sum(n for cov, n in bad if not IX.intentional(cov)),  # cùng cách chia với màn Index
            "rows": [(cov, n) for cov, n in bad if not IX.intentional(cov)][:3]}


def build_dashboard_page(ui, cfg, connect, user, ctx: dict, days: int) -> None:
    from nicegui import background_tasks, run

    from .web_overview import health_strip, todo_section
    site = cfg.site_url
    with connect() as c:
        end = K.latest_date(c, site)
        cur, prev = windows(end, days)
        daily = gsc_daily(c, site, prev[0], cur[1])
        rank = rank_snapshot(c, site, end)
        idx = index_snapshot(c, site) if not A.is_client(user) else None
        from . import okr as O
        try:
            okr = O.overview(c, date.today()) if O.items(c) else None
        except Exception:  # noqa: BLE001  (sheet OKR chưa đồng bộ)
            okr = None
    bks = buckets(cur, days)
    labels = [f"{s:%d/%m}" for s, _ in bks]
    pbks = buckets(prev, days)  # kỳ so sánh, cùng số điểm: vẽ nét đứt trên cùng biểu đồ nhỏ
    plabels = [f"{s:%d/%m}" for s, _ in pbks]
    ed = A.can_edit(user)

    T.page_header(ui, "space_dashboard", "Tổng quan",
                  f"{days} ngày gần nhất ({cur[0]:%d/%m} – {cur[1]:%d/%m/%Y}) so với {days} ngày trước đó "
                  f"({prev[0]:%d/%m} – {prev[1]:%d/%m})")
    if ed:
        health_strip(ui, cfg, connect, None)
        # Việc cần làm lên đầu: thấy ngay trước khi đọc số
        from .report import build
        with connect() as c:
            rep = build(c, cfg, ctx["group"], 0, with_ai=False)
        todo_section(ui, cfg, connect, rep, ctx, site)

    def total(s, e, i):
        return sum(v[i] for d, v in daily.items() if s <= d <= e)

    clicks, clicks_prev = total(*cur, 0), total(*prev, 0)
    impr, impr_prev = total(*cur, 1), total(*prev, 1)
    state = {"ga4": None, "loading": True}
    prev_label = f"{days} ngày trước đó"  # dòng so sánh trong ô: "28 ngày trước đó: 20.558 · −594"

    # ---- Nhịp số liệu: GSC + GA4 + GEO ----
    with ui.element("div").classes("sr-spark-key").props('aria-hidden="true"'):  # chú thích chung cho đường nhỏ
        ui.html("<span><i></i>Kỳ này</span>")
        ui.html(f"<span><i class='dash'></i>{days} ngày trước đó</span>")

    @ui.refreshable
    def pulse():
        g = state["ga4"] or {}
        loading = state["loading"]

        def ga4_tile(icon, label, key, tone, hint):
            if loading:
                return T.kpi(ui, icon, label, "…", hint="Đang lấy số GA4", spark=[], tone=tone, source=hint)
            if g.get("error") or key not in g:
                return T.kpi(ui, icon, label, "chưa có", hint="Chưa kết nối GA4" if not cfg.ga4_property
                             else "Không lấy được số GA4", spark=[], tone=tone, source=hint)
            now, before, spark, spark_prev = g[key]
            d = change(now, before)
            return T.kpi(ui, icon, label, F.n(now), F.delta_pct(d, before), T.good_of(d), source=hint, spark=spark,
                         tone=tone, spark_kind="line", spark_labels=labels, prev=F.vs_parts(now, before, label=prev_label),
                         spark_compare=spark_prev, spark_compare_labels=plabels)

        with ui.element("div").classes("sr-dash-grid w-full"):
            dc, di = change(clicks, clicks_prev), change(impr, impr_prev)
            T.kpi(ui, "ads_click", "Click từ Google", F.n(clicks), F.delta_pct(dc, clicks_prev), T.good_of(dc),
                  source="Google Search Console", spark=[total(s, e, 0) for s, e in bks], tone="blue", spark_kind="line",
                  spark_labels=labels, href="/url", prev=F.vs_parts(clicks, clicks_prev, label=prev_label),
                  spark_compare=[total(s, e, 0) for s, e in pbks], spark_compare_labels=plabels)
            T.kpi(ui, "visibility", "Lượt hiển thị", F.n(impr), F.delta_pct(di, impr_prev), T.good_of(di),
                  source="Google Search Console: số lần site hiện trên Google", spark=[total(s, e, 1) for s, e in bks], tone="blue",
                  spark_kind="line", spark_labels=labels, href="/url", prev=F.vs_parts(impr, impr_prev, label=prev_label),
                  spark_compare=[total(s, e, 1) for s, e in pbks], spark_compare_labels=plabels)
            ga4_tile("groups", "Lượt truy cập (mọi kênh)", "all", "green", "Google Analytics 4")
            ga4_tile("travel_explore", "Lượt truy cập Organic", "organic", "green", "Kênh Organic Search (GA4)")
            ga4_tile("smart_toy", "Truy cập từ AI", "ai", "purple", "ChatGPT, Gemini, Perplexity… (GA4)")
            aio = g.get("aio") if not loading else None
            if aio and aio.get("share") is not None:
                dp = (aio["share"] - aio["prev_share"]) if aio.get("prev_share") is not None else None
                T.kpi(ui, "lightbulb", "Tỷ lệ hiện trong AI", F.pct(aio["share"], 1), F.delta_points(dp),
                      T.good_of(dp), (f"Số đến {aio['until']:%d/%m} (file AI Overviews về trễ)"
                                      if aio.get("until") else ""),
                      source="Phần lượt hiển thị Google nằm trong câu trả lời AI (file Generative AI của GSC)",
                      spark=aio.get("share_spark") or [], tone="amber", spark_kind="line", spark_labels=labels,
                      spark_fmt="pct", href="/ai", prev=F.vs_parts(aio["share"], aio.get("prev_share"), "pct", label=prev_label),
                      spark_compare=aio.get("share_spark_prev"), spark_compare_labels=aio.get("prev_labels"))
            else:
                T.kpi(ui, "lightbulb", "Tỷ lệ hiện trong AI", "…" if loading else "chưa có",
                      hint="Cần nhập file Generative AI từ GSC" if not loading else "Đang tính", spark=[],
                      tone="amber", href="/ai")

    pulse()

    # ---- Backlink (DataForSEO): website trỏ về, backlink, uy tín; link mới / mất của tháng; xu hướng 12 tháng ----
    from . import backlinks as BL

    async def fetch_backlinks(btn):
        if not ed:  # tốn tiền DataForSEO: chặn ở server, nút bị ẩn chưa đủ
            return
        from contextlib import closing

        from . import db
        btn.props("loading")

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                logs: list[str] = []
                BL.refresh(c, site, cfg, force=True, log=logs.append)
                return " ".join(logs)
        try:
            msg = await run.io_bound(work)
            ui.notify(msg or "Đã lấy số backlink", type="positive", position="bottom-right", classes="sr-toast")
        except Exception as e:  # noqa: BLE001
            ui.notify("Không lấy được số backlink", caption=str(e)[:200], type="negative", position="bottom-right",
                      classes="sr-toast", timeout=0, close_button="Đóng")
        btn.props(remove="loading")
        backlink_card.refresh()

    @ui.refreshable
    def backlink_card():
        with connect() as c:
            bl = BL.latest(c, site)
        now = (bl or {}).get("now")
        sub = (f"DataForSEO · lấy ngày {date.fromisoformat(now['day']):%d/%m}, tự lấy lại mỗi tuần" if now
               else "Chưa lấy số lần nào")
        with T.section(ui, "Backlink", "link", sub):
            if now:
                prev = bl["prev"]
                with ui.element("div").classes("sr-mini-stats"):
                    with ui.column().classes("gap-0"):
                        ui.label("Website trỏ về").classes("text-xs muted")
                        with ui.row().classes("items-baseline gap-2 no-wrap"):
                            ui.html(f'<div class="sr-mini-num num">{F.n(now["referring_domains"] or 0)}</div>')
                            if prev and prev["referring_domains"] is not None and now["referring_domains"] is not None:
                                d = now["referring_domains"] - prev["referring_domains"]
                                T.delta_badge(ui, f"{'+' if d > 0 else '-' if d < 0 else ''}{F.n(abs(d))}" if d
                                              else "", T.good_of(d),
                                              since=f"lần lấy {date.fromisoformat(prev['day']):%d/%m}")
                    with ui.column().classes("gap-0"):
                        ui.label("Backlink").classes("text-xs muted")
                        ui.html(f'<div class="sr-mini-num num">{F.n(now["backlinks"] or 0)}</div>')
                    with ui.column().classes("gap-0").tooltip(
                            "Điểm uy tín của website theo DataForSEO (0–1000), tính từ số và chất lượng link trỏ về"):
                        ui.label("Uy tín").classes("text-xs muted")
                        ui.html(f'<div class="sr-mini-num num">{now["rank"] if now["rank"] is not None else "–"}'
                                '<span>/1000</span></div>')
                hist = [h for h in bl["history"] if h["referring_domains"] is not None]
                last_full = next((h for h in reversed(hist) if h["month"] < date.today().strftime("%Y-%m")), None)
                if last_full and (last_full["new_backlinks"] or last_full["lost_backlinks"]):
                    m = f"{last_full['month'][5:]}/{last_full['month'][:4]}"
                    ui.html(f"Tháng {m}: <b>+{F.n(last_full['new_backlinks'] or 0)}</b> link mới · "
                            f"<b>−{F.n(last_full['lost_backlinks'] or 0)}</b> link mất").classes("sr-cmp-note")
                if len(hist) >= 2:
                    with ui.element("div").classes("w-full"):
                        T.sparkline(ui, [h["referring_domains"] for h in hist], T.GREEN,
                                    labels=[f"{h['month'][5:]}/{h['month'][2:4]}" for h in hist])
                    ui.label(f"Website trỏ về, {len(hist)} tháng gần nhất").classes("sr-kpi-hint")
                if now["spam_score"] is not None or now["broken_backlinks"]:
                    ui.label(f"Điểm spam {now['spam_score'] or 0}/100 · {F.n(now['broken_backlinks'] or 0)} "
                             "link gãy").classes("sr-kpi-hint").tooltip(
                        "Điểm spam trung bình của backlink (càng thấp càng tốt) và số link trỏ về trang không còn")
            else:
                ui.label("Số website trỏ về, số backlink, uy tín và link mới / mất mỗi tháng, lấy từ DataForSEO. "
                         "Lần đầu khoảng 0,05 USD (kèm lịch sử 12 tháng), sau đó tự lấy mỗi tuần khoảng 0,02 USD."
                         ).classes("text-sm muted")
            if ed and not cfg.rank.paused:
                b = ui.button("Lấy số mới" if now else "Lấy số backlink", icon="refresh").props(
                    "flat dense no-caps size=sm color=primary").classes("sr-link-btn")
                b.on_click(lambda _, b=b: fetch_backlinks(b))
                b.tooltip("Gọi DataForSEO ngay (khoảng 0,02 USD, tính vào ngân sách check rank của website)")

    # ---- Thứ hạng · Index · Backlink · OKR ----
    with ui.element("div").classes("sr-dash-three w-full"):
        sub = (f"{rank['checked']}/{rank['total']} từ khóa đã check · lần mới nhất "
               f"{date.fromisoformat(rank['last']):%d/%m}" if rank["last"] else "Chưa có lần check nào")
        with T.section(ui, "Thứ hạng", "leaderboard", sub, href="/rank", link_text="Thứ hạng"):
            if rank["checked"]:
                with ui.element("div").classes("sr-mini-stats"):
                    for label, v in (("Top 3", rank["top3"]), ("Top 5", rank["top5"]), ("Top 10", rank["top10"])):
                        with ui.column().classes("gap-0"):
                            ui.label(label).classes("text-xs muted")
                            ui.html(f'<div class="sr-mini-num num">{v}<span>/{rank["total"]}</span></div>')
                with ui.row().classes("gap-2 q-mt-xs"):
                    T.status_chip(ui, f"{rank['up']} lên hạng", "green", "trending_up")
                    T.status_chip(ui, f"{rank['down']} rớt hạng", "red" if rank["down"] else "grey",
                                  "trending_down")
                from .web_aio import dashboard_lines
                dashboard_lines(ui, connect, cfg)  # AI Overview + đối thủ hay gặp (từ kết quả check rank)
            else:
                ui.label("Thêm từ khóa và đặt lịch check ở màn Từ khóa & Thứ hạng.").classes("text-sm muted")
            if cfg.rank.paused:
                T.status_chip(ui, "Đang tạm ngưng check rank", "amber", "pause_circle")

        if idx is not None:
            with T.section(ui, "Index", "travel_explore", f"{idx['total']} URL đã kiểm tra (lần mới nhất)",
                           href="/index", link_text="Index"):
                if idx["total"]:
                    with ui.element("div").classes("sr-mini-stats"):
                        with ui.column().classes("gap-0"):
                            ui.label("Đã index").classes("text-xs muted")
                            ui.html(f'<div class="sr-mini-num num">{idx["ok"]}<span>/{idx["total"]}</span></div>')
                        with ui.column().classes("gap-0"):
                            ui.label("Chưa index · cần xem").classes("text-xs muted")
                            ui.html(f'<div class="sr-mini-num num" style="color:{T.RED if idx["fix"] else T.INK}">'
                                    f'{idx["fix"]}</div>')
                    for cov, n in idx["rows"]:
                        with ui.row().classes("w-full justify-between no-wrap"):
                            ui.label(cov or "Không rõ").classes("text-xs ellipsis")
                            ui.label(F.n(n)).classes("text-xs muted num")
                else:
                    ui.label("Chưa kiểm tra index lần nào.").classes("text-sm muted")

        backlink_card()

        with T.section(ui, "Công việc & OKR", "task_alt", (f"Đợt {okr['cycle']}" if okr else "Chưa có sheet OKR"),
                       href="/okr", link_text="Công việc & OKR"):
            if okr and okr["total"]:
                done = okr["counts"].get(O.DONE, 0)
                with ui.element("div").classes("sr-mini-stats"):
                    with ui.column().classes("gap-0"):
                        ui.label("Hoàn thành").classes("text-xs muted")
                        ui.html(f'<div class="sr-mini-num num">{done / okr["total"] * 100:.0f}%'
                                f'<span> · {done}/{okr["total"]}</span></div>')
                    with ui.column().classes("gap-0"):
                        ui.label("Trễ hạn").classes("text-xs muted")
                        n_late = len(okr["late"])
                        ui.html(f'<div class="sr-mini-num num" style="color:{T.RED if n_late else T.INK}">{n_late}'
                                '</div>')
                for o in okr["objectives"][:3]:
                    pct = o["pct"] or 0
                    with ui.column().classes("w-full gap-0 q-mt-xs"):
                        with ui.row().classes("w-full justify-between no-wrap"):
                            ui.label(o["title"]).classes("text-xs ellipsis")
                            ui.label(f"{pct * 100:.0f}%").classes("text-xs muted num")
                        ui.linear_progress(pct, show_value=False, size="5px", color="primary").classes(
                            "rounded-borders")
            else:
                ui.label("Gắn link sheet OKR ở màn Dự án để theo dõi tiến độ công việc.").classes("text-sm muted")

    # ---- KPI cam kết (tải nền, có GA4) ----
    kpi_box = ui.column().classes("w-full")


    async def load():
        def work():
            from contextlib import closing

            from . import auth, db, ga4_query
            from . import ai_classifier as C
            from .ai_analytics import AIAnalytics
            from .report import aio_block
            out = {}
            with closing(db.connect(cfg.db_path)) as c:
                out["aio"] = aio = aio_block(c, site, cur, prev, bks)
                if aio and aio["share"] is None and aio.get("data_until"):
                    # File AI Overviews thường trễ vài ngày so với GSC: tính trên cùng số ngày, kết thúc ở ngày cuối
                    # file có số, và ghi rõ ngày đó
                    until = date.fromisoformat(str(aio["data_until"])[:10])
                    c2, p2 = windows(until, days)
                    out["aio"] = aio_block(c, site, c2, p2, buckets(c2, days))
                    if out["aio"]:
                        out["aio"]["until"] = until
                else:
                    c2, p2 = cur, prev
                if out["aio"]:  # đường nét đứt của kỳ so sánh trên biểu đồ nhỏ
                    pa = aio_block(c, site, p2, p2, buckets(p2, days))
                    out["aio"]["share_spark_prev"] = (pa or {}).get("share_spark")
                    out["aio"]["prev_labels"] = [f"{s_:%d/%m}" for s_, _ in buckets(p2, days)]
                if not cfg.ga4_property:
                    return out
                try:
                    client = ga4_query.GA4Client(auth.build_ga4_data(auth.get_credentials(cfg, need=auth.ALL_SCOPES)),
                                                 cfg.ga4_property, c)
                    rows = client.run(["date", "sessionDefaultChannelGroup"], ["sessions"], prev[0], cur[1],
                                      limit=20000).rows
                    by_day: dict[date, list[int]] = {}
                    for r in rows:
                        d = date(int(r["date"][:4]), int(r["date"][4:6]), int(r["date"][6:]))
                        v = by_day.setdefault(d, [0, 0])
                        v[0] += r["sessions"]
                        if r["sessionDefaultChannelGroup"] == "Organic Search":
                            v[1] += r["sessions"]
                    ai = AIAnalytics(client).trend(prev[0], cur[1], interval="day")
                    ai_day = {date(int(p["date"][:4]), int(p["date"][4:6]), int(p["date"][6:])):
                              p.get("AI Assistants", 0) for p in ai["data"].get("points", [])}

                    def tot(src, s, e, i=None):
                        return sum((v[i] if i is not None else v) for d, v in src.items() if s <= d <= e)
                    for key, src, i in (("all", by_day, 0), ("organic", by_day, 1), ("ai", ai_day, None)):
                        out[key] = (tot(src, *cur, i), tot(src, *prev, i), [tot(src, s, e, i) for s, e in bks],
                                    [tot(src, s, e, i) for s, e in pbks])
                except (Exception, SystemExit) as e:  # noqa: BLE001
                    out["error"] = str(e)
            return out
        try:
            state["ga4"] = await run.io_bound(work)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            state["ga4"] = {"error": str(e)}
        state["loading"] = False
        pulse.refresh()

    async def load_kpi():
        from .web_kpi import kpi_block, load_progress
        try:
            p = await run.io_bound(load_progress, cfg)
        except (Exception, SystemExit):  # noqa: BLE001
            return
        if p:
            with kpi_box:
                kpi_block(ui, p)

    background_tasks.create(load())
    background_tasks.create(load_kpi())
