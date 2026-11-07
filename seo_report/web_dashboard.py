"""Màn Tổng quan: nhịp số liệu của website theo khoảng 7 / 28 / 90 ngày gần nhất (so với cùng số ngày liền trước).

Khác Báo cáo (bản chốt theo tuần / tháng để gửi đi): Tổng quan gom mọi nguồn vào một màn để theo dõi hằng ngày:
GSC (click, lượt hiển thị), GA4 (lượt truy cập toàn site, Organic, từ AI), GEO (tỷ lệ hiện trong AI của Google),
thứ hạng, index, KPI cam kết, OKR. Số GSC / rank / index / OKR đọc từ SQLite nên hiện ngay; GA4 và KPI tải nền.
"""
import re
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
    """Các điểm của biểu đồ nhỏ: mỗi ngày một điểm, phủ đúng cả kỳ (7 / 28 / 90 điểm). Không gộp theo tuần: 90 ngày
    không chia hết cho 7, gộp tuần thì hoặc có một tuần thiếu ngày (cột thấp giả), hoặc phải bỏ bớt ngày (biểu đồ lệch
    với số tổng). Kỳ so sánh cùng số ngày nên điểm thứ i của hai kỳ là hai ngày cách nhau đúng `days` ngày.
    `days` giữ trong chữ ký cho các chỗ gọi cũ."""
    out, d = [], cur[0]
    while d <= cur[1]:
        out.append((d, d))
        d += timedelta(days=1)
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


def kpi_rank_line(p: dict | None) -> str:
    """Dòng Top N theo KPI (bộ cam kết, lần check cuối của tháng dự án) cho ô Thứ hạng, để người xem không lẫn với
    Top N theo lần check mới nhất ở trên. Trả "" khi không có KPI thứ hạng."""
    from . import kpi as KP
    if not p or not p.get("months"):
        return ""
    months = [m for m in p["months"] if m["status"] != "future"]
    if not months:
        return ""
    m = next((x for x in months if x["status"] == "running"), months[-1])
    parts = []
    for line in p["lines"]:
        ch = (m.get("checks") or {}).get(KP.line_id(line))
        if line["kind"] != "rank" or not ch or not ch.get("checked") or not ch.get("total"):
            continue
        name = f"Top {line['top']}" + (" (bộ riêng)" if line.get("mode") == "per_tier" else "")
        parts.append(f"{name} <b>{ch['count']}/{ch['total']}</b>")
    if not parts:
        return ""
    when = "lần check mới nhất trong tháng, tháng đang chạy" if m["status"] == "running" else "lần check cuối tháng"
    return f"Theo KPI tháng dự án {m['n']} (bộ cam kết, {when}): " + " · ".join(parts)


def kpi_rank_value(p: dict | None) -> tuple[str, str] | None:
    """(nhãn, số) gọn cho dòng KPI thứ hạng: ("KPI tháng 1", "Top 3 <b>9/50</b> · Top 10 <b>15/50</b>")."""
    line = kpi_rank_line(p)
    if not line:
        return None
    m = re.search(r"tháng dự án (\d+)", line)
    return (f"KPI tháng {m.group(1)}" if m else "KPI"), line.split("): ", 1)[-1]


def kpi_counts(p: dict | None) -> tuple[int, int, int, bool] | None:
    """(số cam kết đang đạt / đã đạt, số cam kết có mục tiêu tháng này, số tháng dự án, tháng đang chạy?) của tháng
    dự án đang chạy (hoặc tháng gần nhất đã chốt), cùng cách chấm với khối KPI (KP.status). None khi chưa có KPI."""
    from . import kpi as KP
    if not p or not p.get("months"):
        return None
    months = [m for m in p["months"] if m["status"] != "future"]
    if not months:
        return None
    m = next((x for x in months if x["status"] == "running"), months[-1])
    running = m["status"] == "running"
    ok = total = 0
    for line in p["lines"]:
        ch = (m.get("checks") or {}).get(KP.line_id(line))
        if not ch or ch.get("target") is None:
            continue
        total += 1
        ok += KP.status(ch, running)[1] == "green"
    return ok, total, m["n"], running


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
        from .report import build
        from .web_overview import todo_rows
        with connect() as c:
            rep = build(c, cfg, ctx["group"], 0, with_ai=False)
        todos = todo_rows(cfg, connect, rep, ctx)

    def total(s, e, i):
        return sum(v[i] for d, v in daily.items() if s <= d <= e)

    clicks, clicks_prev = total(*cur, 0), total(*prev, 0)
    impr, impr_prev = total(*cur, 1), total(*prev, 1)
    state = {"ga4": None, "loading": True}
    kstate: dict = {"p": None}
    prev_label = f"{days} ngày trước đó"
    from . import backlinks as BL
    from . import cwv as CWV
    from . import dash_widgets as W
    from . import kpi as KP
    with connect() as c:
        kws = [k for k in R.primary_keywords(c, site, end) if not k.get("draft")]
        tops = {k["id"]: k.get("top_target") for k in kws}
        rank_hist = R.history_of(c, tops, limit=12, period="week")
        rank_by = "tuần"
        if len(rank_hist) < 4:  # mới check vài tuần: mỗi lần check một cột cho đủ nhịp
            rank_hist, rank_by = R.history_of(c, tops, limit=12, period="check"), "lần check"
        # Điểm có quá ít từ khóa đã có số (dưới ngưỡng của màn Thứ hạng) thì tỷ lệ không đại diện (vd 1 từ khóa Top 3
        # = 100%): không vẽ, ghi chú số điểm đã ẩn
        from .rank_dashboard import MIN_COVERAGE
        thin = [h for h in rank_hist if (h["checked"] or 0) < MIN_COVERAGE * len(tops)]
        rank_hist = [h for h in rank_hist if h not in thin]
        bl = BL.latest(c, site)
        bst = BL.settings(c, site)
        try:
            lh = W.lighthouse_avg(CWV.latest_pages(c, "mobile"))
        except Exception:  # noqa: BLE001  (chưa có bảng tốc độ)
            lh = {"n": 0}
        kv = KP.version_at(KP.versions(c), date.today())
        from . import rank_overview as RO
        try:
            comp = RO.competitors(c, cfg, end)
        except Exception:  # noqa: BLE001  (chưa có trang kết quả nào)
            comp = {"rows": [], "keywords": 0, "total": 0}
    from .web_aio import WEEKS as AIO_WEEKS
    from .web_aio import load as aio_load
    aio_rows, aio_s = aio_load(connect, cfg)

    def delta(now, before):
        d = change(now, before)
        return F.delta_pct(d, before), T.good_of(d)

    from .rank_dashboard import kpis as rank_tiers
    tiers = rank_tiers(kws)["tiers"]  # vào / rời Top N so với lần check trước

    def jump(text: str, icon: str, tone: str, target: str):
        b = ui.element("button").classes(f"sr-db-jump {tone}").props('type="button"')
        b.on("click", lambda: ui.run_javascript(
            f"document.getElementById('{target}')?.scrollIntoView({{behavior: 'smooth', block: 'start'}})"))
        with b:
            ui.icon(icon, size="16px").props('aria-hidden="true"')
            ui.label(text)
            ui.icon("south", size="14px").props('aria-hidden="true"')

    @ui.refreshable
    def summary():
        """Một dòng dưới tiêu đề: việc cần xử lý (team) và KPI tháng dự án (khi có), bấm để cuộn xuống khối đó. Hai
        khối này nằm sau 3 hàng chỉ số SEO nên cần một lối tắt ngay đầu trang."""
        if not ed and not kv:
            return
        with ui.element("div").classes("sr-db-summary"):
            if ed:
                n_todo = len(todos)
                jump(f"{n_todo} việc cần xử lý" if n_todo else "Không có việc cần xử lý",
                     "checklist" if n_todo else "check_circle", "warn" if n_todo else "good", "can-xu-ly")
            if kv:
                kc = kpi_counts(kstate["p"])
                if kc is None:
                    jump("KPI cam kết: đang tính…", "flag", "", "kpi-cam-ket")
                else:
                    ok, total_, n_m, running = kc
                    tone = "good" if ok == total_ else ("warn" if running else "bad")
                    jump(f"KPI tháng dự án {n_m}: " + (f"{ok}/{total_} " + ("đang đạt" if running else "đạt")
                                                       if total_ else "tháng này không cam kết"), "flag",
                         tone if total_ else "", "kpi-cam-ket")

    summary()

    def pct_text(x):
        return f"{x * 100:.1f}%".replace(".", ",") if x is not None else "–"

    # ================= 3 hàng đầu: chỉ số SEO theo nguồn (Thứ hạng · Search Console · Google Analytics) ==============
    # Mỗi nguồn một hàng ngang: 4 ô số bên trái, biểu đồ bên phải.
    @ui.refreshable
    def rank_row():
        """Thứ hạng (lần check mới nhất của mỗi từ khóa, không theo kỳ cuộn). Top N trên mọi từ khóa theo dõi (bỏ bộ
        Nháp), ghi rõ số đã check; có KPI thì thêm dòng Top N theo KPI (bộ cam kết, tháng dự án) để không lẫn."""
        sub = (f"Lần check mới nhất {date.fromisoformat(rank['last']):%d/%m} · đã check {rank['checked']}/"
               f"{rank['total']} từ khóa · không theo kỳ ngày đang chọn" if rank["last"] else "Chưa có lần check nào")
        W.group_head(ui, "Thứ hạng từ khóa", "leaderboard", sub, "/rank", "Thứ hạng")
        if not rank["checked"]:
            with W.card(ui, "Thứ hạng", "leaderboard"):
                ui.label("Thêm từ khóa và đặt lịch check ở màn Từ khóa & Thứ hạng.").classes("text-sm muted")
            return
        n = rank["total"]
        with ui.element("div").classes("sr-db-rank3"):
            with W.card(ui, "Chỉ số chính", "insights", extra="sr-db-minicard"):
                W.mini_row(ui, "emoji_events", "green", "Top 3", f"{rank['top3']}/{n}",
                           sub=f"vào {tiers[3]['enter']} · rời {tiers[3]['leave']}", ratio=rank["top3"] / n,
                           info=("Số từ khóa ở vị trí 1–3 trên Google, lần check mới nhất của mỗi từ khóa.",))
                W.mini_row(ui, "format_list_numbered", "lime", "Top 10", f"{rank['top10']}/{n}",
                           sub=f"vào {tiers[10]['enter']} · rời {tiers[10]['leave']}", ratio=rank["top10"] / n,
                           info=("Số từ khóa ở trang 1 Google (vị trí 1–10).",))
                W.mini_row(ui, "swap_vert", "amber", "Lên / rớt", sub="so với lần check trước",
                           value_html=(f"<span style='color:{T.GREEN}'>▲{rank['up']}</span> "
                                       f"<span style='color:{T.RED if rank['down'] else T.MUTED}'>▼{rank['down']}"
                                       "</span>"), split=(rank["up"], rank["down"]),
                           info=("Số từ khóa lên hạng và rớt hạng so với lần check liền trước của chính từ khóa "
                                 "đó.",))
                W.mini_row(ui, "fact_check", "grey", "Đã check", f"{rank['checked']}/{n}",
                           sub=(f"{n - rank['checked']} chưa check" if rank["checked"] < n else "đủ cả bộ"),
                           ratio=rank["checked"] / n,
                           info=("Từ khóa đã có ít nhất một lần check. Top N tính trên tổng số từ khóa theo dõi.",))
            with W.card(ui, "", extra="sr-db-chartcard"):
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.icon("bar_chart", size="15px").classes("sr-db-card-ico")
                    ui.label(f"Phân bổ thứ hạng theo {rank_by}" if len(rank_hist) >= 2 else "Phân bổ thứ hạng"
                             ).classes("sr-db-card-title")
                if len(rank_hist) >= 2:
                    W.rank_share_chart(ui, rank_hist)
                elif rank_hist:
                    W.rank_segment_bar(ui, rank_hist[-1])
                if thin and len(rank_hist) >= 2:
                    ui.label(f"Ẩn {len(thin)} {rank_by} có quá ít từ khóa đã check").classes("sr-db-note")
                # AI Overview ở lần check mới nhất của từng từ khóa: được trích / có nhưng chưa / không có
                known = [r for r in aio_rows if r["aio"] is not None]
                if known:
                    has = [r for r in known if r["aio"]]
                    cited = sum(1 for r in has if r["cited"])
                    with ui.row().classes("items-center gap-1 no-wrap sr-db-subrow"):
                        ui.icon("auto_awesome", size="15px").classes("sr-db-card-ico")
                        ui.label("AI Overview").classes("sr-db-card-title")
                    W.segment_bar(ui, [(W.AIO_PARTS[0][0], W.AIO_PARTS[0][1], cited),
                                       (W.AIO_PARTS[1][0], W.AIO_PARTS[1][1], len(has) - cited),
                                       (W.AIO_PARTS[2][0], W.AIO_PARTS[2][1], len(known) - len(has))],
                                  "AI Overview lần check mới nhất", total=len(known), compact=True)
                    opp = [r for r in has if r["cited"] is False and r["rank"] and r["rank"] <= 10]
                    with ui.element("div").classes("sr-db-facts"):
                        W.fact(ui, "bolt", "purple", "Cơ hội AI Overview",
                               f"<b>{len(opp)}</b> từ khóa top 10 chưa được trích", "/aio",
                               "Từ khóa đã ở top 10 và có AI Overview nhưng website chưa được trích: "
                               + (", ".join(r["keyword"] for r in opp[:8]) + ("…" if len(opp) > 8 else "")
                                  if opp else "không có"))
                        if aio_s.get("known"):
                            W.fact(ui, "lightbulb", "purple", f"Được trích {AIO_WEEKS} tuần",
                                   f"<b>{aio_s['cited_rate'] * 100:.0f}%</b> ({aio_s['cited']}/{aio_s['known']} lượt)",
                                   "/aio", f"Tỷ lệ lần có AI Overview mà website được trích, {AIO_WEEKS} tuần gần nhất "
                                           "(mỗi tuần lấy lần check cuối)")
                        kv_ = kpi_rank_value(kstate["p"])
                        if kv_:
                            W.fact(ui, "flag", "green", kv_[0], kv_[1], "/kpi",
                                   re.sub("<[^>]+>", "", kpi_rank_line(kstate["p"])))
                if cfg.rank.paused:
                    T.status_chip(ui, "Đang tạm ngưng check rank", "amber", "pause_circle")
            rows_c = comp.get("rows") or []
            vis_sum = sum(r["vis"] for r in rows_c)
            with W.card(ui, "Thị phần hiển thị", "pie_chart", extra="sr-db-sharecard"):
                if not vis_sum or not any(not r["brand"]["own"] for r in rows_c):
                    ui.label("Thêm đối thủ ở màn Đối thủ để so thị phần hiển thị.").classes("sr-db-note")
                else:
                    from .web_rank import share_donut
                    with ui.link(target="/doi-thu").classes("sr-db-donutlink no-underline"):
                        share_donut(ui, rows_c, vis_sum, next((r["brand"]["name"] for r in rows_c
                                                               if r["brand"]["own"]), "dự án"), size=220)
                    ui.label(f"Trên {comp['keywords']}/{comp['total']} từ khóa").classes("sr-db-note text-center")

    @ui.refreshable
    def gsc_row():
        g = state["ga4"] or {}
        W.group_head(ui, "Google Search Console", "travel_explore",
                     f"Kỳ đang chọn · {days} ngày, so với {days} ngày trước đó", "/url", "Hiệu suất URL")
        with ui.element("div").classes("sr-db-split"):
            with ui.element("div").classes("sr-db-quad"):
                dl, good = delta(clicks, clicks_prev)
                W.stat(ui, "Click", F.n(clicks), "ads_click", dl, good, sub=f"{prev_label}: {F.n(clicks_prev)}",
                       href="/url", tone="blue")
                dl, good = delta(impr, impr_prev)
                W.stat(ui, "Lượt hiển thị", F.n(impr), "visibility", dl, good, sub=f"{prev_label}: {F.n(impr_prev)}",
                       href="/url", tone="blue")
                ctr, ctr_p = (clicks / impr if impr else None), (clicks_prev / impr_prev if impr_prev else None)
                dp = (ctr - ctr_p) if ctr is not None and ctr_p is not None else None
                W.stat(ui, "CTR", pct_text(ctr), "percent", F.delta_points(dp), T.good_of(dp), tone="amber",
                       sub=f"{prev_label}: {pct_text(ctr_p)}", info=("Click / lượt hiển thị trong kỳ.",))
                aio = g.get("aio") if not state["loading"] else None
                if aio and aio.get("share") is not None:
                    dpa = (aio["share"] - aio["prev_share"]) if aio.get("prev_share") is not None else None
                    W.stat(ui, "Tỷ lệ hiện trong AI", F.pct(aio["share"], 1), "lightbulb", F.delta_points(dpa),
                           T.good_of(dpa), tone="purple", ratio=aio["share"], sub=(f"Số đến {aio['until']:%d/%m} (file AI Overviews về trễ)"
                                                if aio.get("until") else "Phần lượt hiển thị nằm trong câu trả lời AI"),
                           href="/ai")
                else:
                    W.stat(ui, "Tỷ lệ hiện trong AI", "–", "lightbulb", sub="Cần nhập file Generative AI từ GSC",
                           href="/ai", loading=state["loading"], tone="purple")
            with W.card(ui, "Click theo ngày", "show_chart", extra="sr-db-chartcard"):
                W.daily_line(ui, [total(s, e, 0) for s, e in bks], [total(s, e, 0) for s, e in pbks], labels, plabels,
                             "Click")

    @ui.refreshable
    def ga_row():
        g = state["ga4"] or {}
        loading = state["loading"]
        bad = (not loading) and bool(g.get("error") or "all" not in g)
        msg = ("Đang lấy số GA4…" if loading else "Chưa kết nối GA4" if not cfg.ga4_property
               else "Không lấy được số GA4")
        W.group_head(ui, "Google Analytics 4", "insights",
                     f"Kỳ đang chọn · {days} ngày, so với {days} ngày trước đó"
                     + (f" · {msg}" if loading or bad else ""), "/ai", "Nguồn truy cập")
        ok_all = not (loading or bad) and "all" in g and g["all"][0]
        with ui.element("div").classes("sr-db-split"):
            with ui.element("div").classes("sr-db-quad"):
                for key, label, icon, tone, info in (
                        ("organic", "Phiên Organic", "travel_explore", "green", ("Phiên từ kênh Organic Search (GA4).",)),
                        ("ai", "Truy cập từ AI", "smart_toy", "purple",
                         ("Phiên từ ChatGPT, Gemini, Perplexity… (GA4). Không cộng với Organic: click từ AI Overviews "
                          "nằm trong Organic.",))):
                    if loading or bad or key not in g:
                        W.stat(ui, label, "–", icon, sub=msg, info=info, loading=loading, tone=tone)
                    else:
                        now, before = g[key][0], g[key][1]
                        dl, good = delta(now, before)
                        W.stat(ui, label, F.n(now), icon, dl, good, sub=f"{prev_label}: {F.n(before)}", info=info,
                               tone=tone)
                for key, label, icon, tone, info in (
                        ("organic", "Tỷ lệ Organic", "pie_chart", "green", ("Phiên Organic / tổng phiên website.",)),
                        ("ai", "Tỷ lệ truy cập từ AI", "donut_small", "purple", ("Phiên từ AI / tổng phiên website.",))):
                    if not ok_all or key not in g:
                        W.stat(ui, label, "–", icon, sub=msg, loading=loading, tone=tone, info=info)
                        continue
                    sh = g[key][0] / g["all"][0]
                    shp = g[key][1] / g["all"][1] if g["all"][1] else None
                    dp = (sh - shp) if shp is not None else None
                    W.stat(ui, label, pct_text(sh), icon, F.delta_points(dp), T.good_of(dp), tone=tone, ratio=sh,
                           sub=f"{prev_label}: {pct_text(shp)}", info=info)
            with W.card(ui, "Phiên Organic theo ngày", "show_chart", extra="sr-db-chartcard"):
                if loading:
                    ui.skeleton("rect").style("height:140px; border-radius:8px")
                elif bad or "organic" not in g:
                    ui.label(msg).classes("text-sm muted q-py-lg")
                else:
                    W.daily_line(ui, g["organic"][2], g["organic"][3], labels, plabels, "Organic", color=T.GREEN,
                                 height=150)
                ui.label("Truy cập từ AI theo nguồn").classes("sr-db-subhead")
                if loading:
                    for w in (70, 40, 20):
                        ui.skeleton("rect").style(f"height:12px; width:{w}%; border-radius:6px; margin:6px 0")
                elif not bad:
                    srcs = sorted((g.get("ai_sources") or {}).items(), key=lambda kv: -kv[1])
                    W.source_bars(ui, [(F.SOURCE_NAMES.get(k, k.replace("_", " ").title()), v) for k, v in srcs[:5]],
                                  empty="Chưa có lượt truy cập từ AI trong kỳ")

    with ui.element("div").classes("sr-db w-full q-mt-sm"):
        for fn in (rank_row, gsc_row, ga_row):
            with ui.element("div").classes("sr-db-group sr-db-12"):
                fn()

    # ================= Việc cần làm (team) và KPI cam kết (tháng dự án) =================
    if ed:
        todo_section(ui, cfg, connect, rep, ctx, site, rows=todos)
    # Số KPI cần GA4 nên tải nền; trong lúc chờ giữ chỗ đúng số ô của phiên bản KPI hiện hành để trang không nhảy.
    kpi_box = ui.column().classes("w-full").props('id="kpi-cam-ket"')
    if kv:
        n_lines = len((kv.get("data") or {}).get("lines") or []) or 4
        with kpi_box, T.section(ui, "Tiến độ KPI cam kết", "flag", "Tháng dự án · đang tính tiến độ…"):
            with T.kpi_row(ui):
                for _ in range(n_lines):
                    with ui.element("div").classes("sr-card sr-kpi"):
                        ui.skeleton("text").style("width:60%")
                        ui.skeleton("rect").style("height:28px; width:45%; margin:6px 0")
                        ui.skeleton("text").style("width:80%")
    elif ed:
        with kpi_box, T.section(ui, "KPI cam kết", "flag", "Dự án chưa có KPI cam kết", href="/kpi",
                                link_text="Tạo KPI cam kết"):
            ui.label("Tạo bộ cam kết (thứ hạng, phiên Organic / AI theo tháng dự án) để tool tự chấm tiến độ mỗi "
                     "ngày.").classes("text-sm muted")

    # ================= Tốc độ · Backlink · Index · OKR =================
    with ui.element("div").classes("sr-db sr-db-eq w-full q-mt-sm"):
        with ui.element("div").classes("sr-db-group sr-db-4"):
            at = lh.get("at")
            sub = (f"Trung bình {lh['n']} trang quan trọng · điện thoại · đo {at[8:10]}/{at[5:7]}"
                   if lh.get("n") and at else "Chưa đo tốc độ")
            W.group_head(ui, "Tốc độ trang", "speed", sub, "/toc-do", "Tốc độ")
            with ui.element("div").classes("sr-db-gauges"):
                for key, label in (("perf", "Hiệu năng"), ("seo", "SEO"), ("a11y", "Trợ năng"),
                                   ("bp", "Thực hành tốt")):
                    with W.card(ui, label, extra="sr-db-gauge"):
                        W.gauge(ui, lh.get(key), label, height=100)
                        v = lh.get(key)
                        ui.label("–" if v is None else "Tốt" if v >= 90 else "Cần cải thiện" if v >= 50
                                 else "Kém").classes("sr-db-note text-center")

        with ui.element("div").classes("sr-db-group sr-db-8"):
            now_bl = (bl or {}).get("now")
            sub = ((f"Lần lấy mới nhất {date.fromisoformat(now_bl['day']):%d/%m} (DataForSEO) · "
                    + ("tạm ngưng tự lấy" if bst["paused"] else BL.EVERY_CHOICES[bst["every_days"]].lower()
                       + " tự lấy lại")
                    + (f" · thay đổi so với lần lấy {date.fromisoformat(bl['prev']['day']):%d/%m}"
                       if bl.get("prev") else "")) if now_bl else "Chưa lấy số lần nào")
            W.group_head(ui, "Backlink", "link", sub, "/backlink", "Backlink")
            if not now_bl:
                with W.card(ui, "Backlink", "link"):
                    ui.label("Chưa lấy số backlink lần nào. Lấy số (tốn phí DataForSEO) và đặt lịch tự lấy ở màn "
                             "Backlink.").classes("text-sm muted")
            else:
                pv = bl["prev"] or {}
                hist = [h for h in bl["history"] if h["referring_domains"] is not None]

                def d_of(k):
                    a, b = now_bl.get(k), pv.get(k)
                    return (a - b) if a is not None and b is not None else None

                with ui.element("div").classes("sr-db-trio"):
                    d = d_of("referring_domains")
                    W.stat(ui, "Website trỏ về", F.n(now_bl["referring_domains"] or 0), "public",
                           (f"{'+' if d > 0 else '−'}{F.n(abs(d))}" if d else ""), T.good_of(d), tone="blue",
                           sub="So với lần lấy trước")
                    d = d_of("rank")
                    W.stat(ui, "Uy tín", f"{now_bl['rank'] if now_bl['rank'] is not None else '–'}/1000", "verified",
                           (f"{'+' if d > 0 else '−'}{abs(d)}" if d else ""), T.good_of(d), tone="amber",
                           ratio=(now_bl["rank"] or 0) / 1000, sub="Thang 0–1000 (DataForSEO)",
                           info=("Điểm uy tín của website theo DataForSEO (0–1000), tính từ số và chất lượng link "
                                 "trỏ về.",))
                    d = d_of("backlinks")
                    W.stat(ui, "Backlink", F.n(now_bl["backlinks"] or 0), "link",
                           (f"{'+' if d > 0 else '−'}{F.n(abs(d))}" if d else ""), T.good_of(d), tone="green",
                           sub=f"Điểm spam {now_bl['spam_score'] if now_bl['spam_score'] is not None else '–'}/100")
                with W.card(ui, "Link mới / mất theo tháng", "stacked_bar_chart"):
                    if hist:
                        W.new_lost_chart(ui, hist, height=200)
                        last = next((h for h in reversed(hist) if h["month"] < date.today().strftime("%Y-%m")), None)
                        if last:
                            ui.html(f"Tháng {last['month'][5:]}/{last['month'][:4]}: <b>+{F.n(last['new_backlinks'] or 0)}"
                                    f"</b> link mới · <b>−{F.n(last['lost_backlinks'] or 0)}</b> link mất").classes(
                                "sr-db-note")

        if idx is not None:
            with ui.element("div").classes("sr-db-group sr-db-6"):
                W.group_head(ui, "Index", "fact_check", f"Lần kiểm tra mới nhất của {idx['total']} URL đã kiểm tra "
                             "(không phải toàn site)", "/index", "Index")
                with W.card(ui, "Trạng thái index", "fact_check"):
                    if idx["total"]:
                        with ui.element("div").classes("sr-mini-stats"):
                            with ui.column().classes("gap-0"):
                                ui.label("Đã index").classes("text-xs muted")
                                ui.html(f'<div class="sr-mini-num num">{idx["ok"]}<span>/{idx["total"]}</span></div>')
                            with ui.column().classes("gap-0"):
                                ui.label("Chưa index · cần xem").classes("text-xs muted")
                                ui.html(f'<div class="sr-mini-num num" style="color:'
                                        f'{T.RED if idx["fix"] else T.INK}">{idx["fix"]}</div>')
                        for cov, n_ in idx["rows"]:
                            with ui.row().classes("w-full justify-between no-wrap"):
                                ui.label(cov or "Không rõ").classes("text-xs ellipsis")
                                ui.label(F.n(n_)).classes("text-xs muted num")
                    else:
                        ui.label("Chưa kiểm tra index lần nào.").classes("text-sm muted")
        with ui.element("div").classes("sr-db-group " + ("sr-db-6" if idx is not None else "sr-db-12")):
            W.group_head(ui, "Công việc & OKR", "task_alt", (f"Đợt {okr['cycle']} · tính đến hôm nay" if okr
                                                             else "Chưa có sheet OKR"), "/okr", "Công việc & OKR")
            with W.card(ui, "Tiến độ", "checklist"):
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
                            ui.html(f'<div class="sr-mini-num num" style="color:{T.RED if n_late else T.INK}">'
                                    f'{n_late}</div>')
                    for o in okr["objectives"][:3]:
                        pct = o["pct"] or 0
                        with ui.column().classes("w-full gap-0 q-mt-xs"):
                            with ui.row().classes("w-full justify-between no-wrap"):
                                ui.label(o["title"]).classes("text-xs ellipsis")
                                ui.label(f"{pct * 100:.0f}%").classes("text-xs muted num")
                            ui.linear_progress(pct, show_value=False, size="5px", color="primary").classes(
                                "rounded-borders")
                else:
                    ui.label("Gắn link sheet OKR ở màn Dự án để theo dõi tiến độ công việc.").classes(
                        "text-sm muted")

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
                    channels: dict[str, int] = {}
                    for r in rows:
                        d = date(int(r["date"][:4]), int(r["date"][4:6]), int(r["date"][6:]))
                        v = by_day.setdefault(d, [0, 0])
                        v[0] += r["sessions"]
                        if cur[0] <= d <= cur[1]:  # donut: chỉ kỳ này
                            ch = r["sessionDefaultChannelGroup"] or "Unassigned"
                            channels[ch] = channels.get(ch, 0) + r["sessions"]
                        if r["sessionDefaultChannelGroup"] == "Organic Search":
                            v[1] += r["sessions"]
                    ai = AIAnalytics(client).trend(prev[0], cur[1], interval="day")
                    ai_day = {date(int(p["date"][:4]), int(p["date"][4:6]), int(p["date"][6:])):
                              p.get("AI Assistants", 0) for p in ai["data"].get("points", [])}
                    from .ai_analytics import ORGANIC as ORG
                    skip = {"AI Assistants", *ORG}
                    src_tot: dict[str, int] = {}
                    for pt in ai["data"].get("points", []):
                        d = date(int(pt["date"][:4]), int(pt["date"][4:6]), int(pt["date"][6:]))
                        if cur[0] <= d <= cur[1]:
                            for k in ai["data"].get("series", []):
                                if k not in skip:
                                    src_tot[k] = src_tot.get(k, 0) + (pt.get(k) or 0)
                    out["ai_sources"] = src_tot

                    def tot(src, s, e, i=None):
                        return sum((v[i] if i is not None else v) for d, v in src.items() if s <= d <= e)
                    out["channels"] = channels
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
        ga_row.refresh()
        gsc_row.refresh()

    async def load_kpi():
        from .web_kpi import kpi_block, load_progress
        try:
            p = await run.io_bound(load_progress, cfg)
        except (Exception, SystemExit):  # noqa: BLE001
            p = None
        if not kv:
            return  # không có KPI: khung mời tạo (nếu có) giữ nguyên
        kpi_box.clear()
        if p:
            with kpi_box:
                kpi_block(ui, p)
            kstate["p"] = p
            rank_row.refresh()
            summary.refresh()
        else:
            with kpi_box, T.section(ui, "Tiến độ KPI cam kết", "flag", "Tháng dự án", href="/kpi",
                                    link_text="Cam kết KPI"):
                ui.label("Chưa tính được tiến độ KPI lúc này.").classes("text-sm muted")

    background_tasks.create(load())
    background_tasks.create(load_kpi())
