"""Số liệu báo cáo tuần / tháng gửi quản lý / khách hàng (spec, mục Xuất Excel → Xuất báo cáo). Dùng chung cho màn Báo cáo và file Excel.

- KPI 4 chỉ số GSC của toàn site và của nhóm URL (mặc định SEO chủ lực), so với tuần trước, kèm xu hướng 8 tuần.
- Top 10 URL tăng và top 10 URL giảm trong nhóm, theo số click tuyệt đối; chỉ xét URL có ≥ 20 click ở một trong hai tuần
  để tránh nhiễu kiểu "4 lên 12 click = +200%".
- Rank thực tế (DataForSEO): lần check gần nhất trong tuần so với lần check gần nhất trước tuần.
"""
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import keywords as K
from . import rank as R
from . import urls as U

MIN_CLICKS_FOR_MOVERS = 20
TOP_MOVERS = 10
TREND_WEEKS = 8
TREND_MONTHS = 12

NOTES_SCHEMA = """
CREATE TABLE IF NOT EXISTS report_notes (
    site TEXT NOT NULL,
    week_start TEXT NOT NULL,
    text TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site, week_start)
);
"""


@dataclass
class Kpi:
    clicks: int = 0
    impressions: int = 0
    position: float | None = None  # trung bình có trọng số theo impression (số của GSC, không phải rank)

    @property
    def ctr(self) -> float | None:
        return self.clicks / self.impressions if self.impressions else None


@dataclass
class WeeklyReport:
    site: str
    group: str
    week: tuple[date, date]
    prev_week: tuple[date, date]
    data_until: date
    site_kpi: Kpi
    site_prev: Kpi
    group_kpi: Kpi
    group_prev: Kpi
    trend: list[dict] = field(default_factory=list)  # [{week, site_clicks, group_clicks}], cũ → mới
    trend_periods: list = field(default_factory=list)  # [(từ ngày, đến ngày)] của từng kỳ trong trend
    winners: list[dict] = field(default_factory=list)
    losers: list[dict] = field(default_factory=list)
    ranks: list[dict] = field(default_factory=list)
    rank_buckets: dict = field(default_factory=dict)
    note: str = ""
    incomplete_days: int = 0
    ai: dict | None = None  # khối traffic AI từ GA4; None khi chưa kết nối GA4
    aio: dict | None = None  # impression AI Overviews / AI Mode (file GSC nhập tay); None khi chưa nhập file nào
    kind: str = "week"  # "week" | "month"; `week`/`prev_week` là kỳ này/kỳ trước của báo cáo
    plan: str = ""  # kế hoạch tháng sau (chỉ báo cáo tháng)
    by_type: list[dict] = field(default_factory=list)
    top_urls: list[dict] = field(default_factory=list)
    top_queries: list[dict] = field(default_factory=list)
    index: dict | None = None  # {"ok", "bad", "total"}: index của URL trong nhóm (lần kiểm tra mới nhất)
    okr: dict | None = None  # tiến độ công việc từ sheet OKR; None khi chưa khai báo sheet / chưa đồng bộ
    organic: dict | None = None  # phiên Organic Search (GA4) kỳ này / kỳ trước / xu hướng; None khi chưa có GA4
    kpi: dict | None = None  # tiến độ KPI cam kết tại cuối kỳ (kpi.progress); None khi chưa có sheet KPI
    committed: set | None = None  # bộ từ khóa cam kết (sheet KPI) có hiệu lực cuối kỳ; None = tính mọi từ đang theo dõi


def ai_block(cfg, con, week: tuple[date, date]) -> dict | None:
    """Traffic từ AI assistant trong tuần (GA4, múi giờ property). Lỗi GA4 không làm hỏng báo cáo: trả về {"error"}."""
    if not cfg.ga4_property:
        return None
    try:
        from . import auth, ga4_query
        from .ai_analytics import AIAnalytics

        creds = auth.get_credentials(cfg, need=auth.ALL_SCOPES)
        ai = AIAnalytics(ga4_query.GA4Client(auth.build_ga4_data(creds), cfg.ga4_property, con))
        s, src = ai.summary(*week), ai.sources(*week)
        if s["status"] == "ERROR":
            return {"error": s["warnings"][0]["message"] if s["warnings"] else "Lỗi GA4"}
        return {"kpi": s["data"]["ai"], "deltas": s["data"]["aiDeltas"] or {}, "prev": s["data"]["aiPrev"] or {},
                "share": s["data"]["share"],
                "paid": s["data"]["paidAi"], "sources": src["data"].get("sources", [])[:5],
                "warnings": [w["code"] for w in s["warnings"] + src["warnings"]]}
    except (Exception, SystemExit) as e:  # token thiếu quyền GA4, mất mạng…
        return {"error": str(e)}


def organic_block(cfg, con, cur: tuple[date, date], prev: tuple[date, date],
                  trend_periods: list[tuple[date, date]]) -> dict | None:
    """Phiên GA4 kênh Organic Search toàn site: kỳ này, kỳ trước, % thay đổi, xu hướng theo kỳ. Một truy vấn theo ngày
    cho cả khoảng rồi cộng theo kỳ. Lỗi GA4 không làm hỏng báo cáo: trả về {"error"}."""
    if not cfg.ga4_property:
        return None
    try:
        from . import ai_classifier as C, auth, ga4_query
        client = ga4_query.GA4Client(auth.build_ga4_data(auth.get_credentials(cfg, need=auth.ALL_SCOPES)),
                                     cfg.ga4_property, con)
        periods = list(trend_periods) + [cur, prev]
        lo, hi = min(p[0] for p in periods), max(p[1] for p in periods)
        rep = client.run(["date"], ["sessions"], lo, hi, C.channel_filter("Organic Search"), limit=5000)
        daily = {date(int(r["date"][:4]), int(r["date"][4:6]), int(r["date"][6:])): r["sessions"] for r in rep.rows}

        def total(s, e):
            return sum(v for d, v in daily.items() if s <= d <= e)
        now, before = total(*cur), total(*prev)
        return {"sessions": now, "prev": before, "change": change(now, before),
                "spark": [total(s, e) for s, e in trend_periods]}
    except (Exception, SystemExit) as e:  # noqa: BLE001
        return {"error": str(e)}


def committed_keywords(con, day: date) -> set[str] | None:
    """Bộ từ khóa cam kết (sheet KPI) có hiệu lực vào ngày `day`; None khi chưa có sheet KPI."""
    from . import kpi as KP
    try:
        ver = KP.version_at(KP.versions(con), day)
    except sqlite3.Error:
        return None
    if not ver or not ver.get("keywords"):
        return None
    return {k["keyword"].lower() for k in ver["keywords"]}


def rank_summary(rep: "WeeklyReport", committed: set[str] | None = None) -> dict:
    """Thứ hạng cho người đọc báo cáo: số từ khóa trong top 3/5/10 lần check này và lần trước, 3 từ tăng / giảm mạnh
    nhất. Chỉ tính bộ từ khóa cam kết nếu có. Ngoài độ sâu check coi như hạng (độ sâu + 1) khi so sánh."""
    ranks = [r for r in rep.ranks if not committed or r["keyword"].lower() in committed]

    def pos(rank, depth):
        return rank if rank is not None else (depth or 100) + 1

    now = {n: sum(1 for r in ranks if r["rank"] is not None and r["rank"] <= n) for n in (3, 5, 10)}
    with_prev = [r for r in ranks if r["prev_depth"] is not None]
    prev = {n: sum(1 for r in with_prev if r["prev"] is not None and r["prev"] <= n) for n in (3, 5, 10)}
    moves = [{"keyword": r["keyword"], "from": r["prev"], "to": r["rank"], "depth": r["depth"],
              "prev_depth": r["prev_depth"], "diff": pos(r["prev"], r["prev_depth"]) - pos(r["rank"], r["depth"])}
             for r in with_prev]
    def dist(pairs):  # số từ khóa theo nhóm vị trí: top 3 / 4–10 / 11–30 / ngoài top 30 (kể cả ngoài độ sâu check)
        out = [0, 0, 0, 0]
        for rank in pairs:
            out[0 if rank is not None and rank <= 3 else 1 if rank is not None and rank <= 10 else
                2 if rank is not None and rank <= 30 else 3] += 1
        return out

    return {"total": len(ranks), "committed": bool(committed), "now": now, "prev": prev, "has_prev": bool(with_prev),
            "dist": {"now": dist(r["rank"] for r in ranks), "prev": dist(r["prev"] for r in with_prev)},
            "up": sorted([m for m in moves if m["diff"] > 0], key=lambda m: -m["diff"])[:3],
            "down": sorted([m for m in moves if m["diff"] < 0], key=lambda m: m["diff"])[:3]}


def kpi_for_report(cfg, con, rep: "WeeklyReport", with_ga4: bool = True) -> dict | None:
    """Tiến độ KPI nhìn từ cuối kỳ báo cáo (tháng dự án chứa ngày cuối kỳ)."""
    from . import kpi as KP
    try:
        if not KP.versions(con):
            return None
        day = min(date.today(), rep.week[1] + timedelta(days=1))
        ga4 = None
        if with_ga4:
            try:
                ga4 = KP.ga4_organic(cfg, con)
            except (Exception, SystemExit):  # noqa: BLE001
                ga4 = None
        p = KP.progress(con, cfg.site_url, day, ga4)
        if p is not None:
            p["ga4"] = ga4 is not None
        return p
    except sqlite3.Error:
        return None


def _site_kpi(con, site: str, start: date, end: date) -> Kpi:
    """Tổng theo property (khớp GSC UI). Không cộng từ các dòng page: impression sẽ bị thổi phồng."""
    c, i, p = con.execute(
        """SELECT COALESCE(SUM(clicks), 0), COALESCE(SUM(impressions), 0),
                  SUM(position * impressions) / NULLIF(SUM(impressions), 0)
           FROM gsc_site_daily WHERE site = ? AND date BETWEEN ? AND ?""",
        (site, start.isoformat(), end.isoformat())).fetchone()
    return Kpi(c, i, p)


def _group_kpi(period: dict[int, tuple]) -> Kpi:
    c = sum(v[0] for v in period.values())
    i = sum(v[1] for v in period.values())
    wp = sum((v[2] or 0) * v[1] for v in period.values())
    return Kpi(c, i, wp / i if i else None)


def _rank_at(con, keyword_id: int, before: date) -> tuple | None:
    """Lần check gần nhất có ngày ≤ `before`: (ngày, rank, URL xếp hạng, độ sâu)."""
    return con.execute(
        "SELECT check_date, rank, ranking_url, depth FROM rank_checks WHERE keyword_id = ? AND check_date <= ? "
        "ORDER BY check_date DESC LIMIT 1", (keyword_id, before.isoformat())).fetchone()


def _bucket(rank: int | None) -> str:
    if rank is None:
        return "Ngoài độ sâu check"
    if rank <= 3:
        return "Top 3"
    if rank <= 10:
        return "Top 4–10"
    return "Top 11–30" if rank <= 30 else "Ngoài top 30"


BUCKETS = ["Top 3", "Top 4–10", "Top 11–30", "Ngoài top 30", "Ngoài độ sâu check"]


def get_note(con, site: str, key: date | str) -> str:
    """Ghi chú theo khóa: ngày đầu tuần (báo cáo tuần), "month:YYYY-MM-01" (nhận xét tháng), "plan:YYYY-MM-01"
    (kế hoạch tháng sau)."""
    con.executescript(NOTES_SCHEMA)
    row = con.execute("SELECT text FROM report_notes WHERE site = ? AND week_start = ?",
                      (site, key.isoformat() if isinstance(key, date) else key)).fetchone()
    return row[0] if row else ""


def save_note(con, site: str, key: date | str, text: str, user: str) -> None:
    con.executescript(NOTES_SCHEMA)
    with con:
        con.execute("INSERT OR REPLACE INTO report_notes VALUES (?, ?, ?, ?, ?)",
                    (site, key.isoformat() if isinstance(key, date) else key, text, user,
                     datetime.now(timezone.utc).isoformat(timespec="seconds")))


def months(end: date, count: int = 13) -> list[tuple[date, date]]:
    """Các tháng dương lịch đã trọn dữ liệu GSC tính đến `end` (ngày cuối có dữ liệu), tháng mới nhất trước."""
    first = end.replace(day=1)
    last_full = end if (end + timedelta(days=1)).day == 1 else first - timedelta(days=1)
    out = []
    m_end = last_full
    for _ in range(count):
        m_start = m_end.replace(day=1)
        out.append((m_start, m_end))
        m_end = m_start - timedelta(days=1)
    return out


def build(con: sqlite3.Connection, cfg, group_id: int, week_index: int = 0, with_ai: bool = True) -> WeeklyReport:
    end = K.latest_date(con, cfg.site_url)
    wks = K.weeks(end, max(TREND_WEEKS, week_index + 2) + week_index)
    trend = list(reversed(wks[week_index:week_index + TREND_WEEKS]))
    return _build(con, cfg, group_id, wks[week_index], wks[week_index + 1], trend, "week", with_ai)


def build_month(con: sqlite3.Connection, cfg, group_id: int, month_index: int = 0,
                with_ai: bool = True) -> WeeklyReport:
    """Báo cáo tháng: cùng khối với báo cáo tuần, số tính thẳng từ dữ liệu ngày của tháng (không cộng các tuần), so với
    tháng trước; thêm xu hướng 12 tháng, theo loại trang, top URL / query của tháng."""
    end = K.latest_date(con, cfg.site_url)
    ms = months(end, max(TREND_MONTHS, month_index + 2) + month_index)
    trend = list(reversed(ms[month_index:month_index + TREND_MONTHS]))
    rep = _build(con, cfg, group_id, ms[month_index], ms[month_index + 1], trend, "month", with_ai)
    s, e = rep.week
    ps, pe = rep.prev_week
    rep.plan = get_note(con, cfg.site_url, f"plan:{s.isoformat()}")
    rep.by_type = _by_type(con, cfg.site_url, (s, e), (ps, pe))
    rep.top_urls = _top_urls(con, cfg.site_url, (s, e), (ps, pe))
    rep.top_queries = _top_queries(con, cfg.site_url, (s, e), (ps, pe))
    return rep


def note_key(rep) -> str | date:
    return rep.week[0] if rep.kind == "week" else f"month:{rep.week[0].isoformat()}"


def _build(con, cfg, group_id, cur, prev, trend_periods, kind, with_ai) -> WeeklyReport:
    site = cfg.site_url
    end = K.latest_date(con, site)
    (ws, we), (ps, pe) = cur, prev
    group = dict(U.list_groups(con, site))[group_id]
    members = U.group_members(con, group_id)
    ids = [m["id"] for m in members]
    now, before = K.url_period(con, ids, ws, we), K.url_period(con, ids, ps, pe)

    fetched = {r[0] for r in con.execute("SELECT date FROM gsc_fetch_log WHERE site = ? AND date BETWEEN ? AND ?",
                                         (site, ws.isoformat(), we.isoformat()))}
    rep = WeeklyReport(
        site=site, group=group, week=(ws, we), prev_week=(ps, pe), data_until=end,
        site_kpi=_site_kpi(con, site, ws, we), site_prev=_site_kpi(con, site, ps, pe),
        group_kpi=_group_kpi(now), group_prev=_group_kpi(before), kind=kind,
        incomplete_days=(we - ws).days + 1 - len(fetched),
    )
    rep.note = get_note(con, site, note_key(rep))

    rep.trend_periods = list(trend_periods)
    for s, e in trend_periods:
        sk, gk = _site_kpi(con, site, s, e), _group_kpi(K.url_period(con, ids, s, e))
        rep.trend.append({"week": f"{s:%d/%m}" if kind == "week" else f"T{s.month}/{s:%y}",
                          "site_clicks": sk.clicks, "group_clicks": gk.clicks,
                          "site_impressions": sk.impressions, "site_ctr": sk.ctr, "site_position": sk.position,
                          "group_impressions": gk.impressions})

    movers = []
    for m in members:
        c = now.get(m["id"], (0, 0, None))[0]
        pc = before.get(m["id"], (0, 0, None))[0]
        if max(c, pc) >= MIN_CLICKS_FOR_MOVERS:
            movers.append({"url": m["url"], "type": m["type"] or "", "clicks": c, "prev": pc, "diff": c - pc})
    rep.winners = sorted([x for x in movers if x["diff"] > 0], key=lambda x: -x["diff"])[:TOP_MOVERS]
    rep.losers = sorted([x for x in movers if x["diff"] < 0], key=lambda x: x["diff"])[:TOP_MOVERS]

    # Tuần: báo cáo thường xuất giữa tuần sau, sau lần check rank (mặc định thứ Ba), nên lấy lần check mới nhất từ đầu
    # tuần đến hết tuần kế tiếp, so với lần check liền trước nó. Tháng: lần check cuối trong tháng so với lần check cuối
    # của tháng trước.
    rank_cutoff = we + timedelta(days=7) if kind == "week" else we
    counts = {b: [0, 0] for b in BUCKETS}  # [lần check này, lần check trước]
    for k in R.keywords(con, site, end):
        cur_check = _rank_at(con, k["id"], rank_cutoff)
        if not cur_check or cur_check[0] < ws.isoformat():
            continue  # không có lần check nào trong khoảng này
        old = _rank_at(con, k["id"], (date.fromisoformat(cur_check[0]) if kind == "week" else ws) - timedelta(days=1))
        rep.ranks.append({
            "keyword": k["keyword"], "rank": cur_check[1], "depth": cur_check[3], "date": cur_check[0],
            "prev": old[1] if old else None, "prev_depth": old[3] if old else None, "prev_date": old[0] if old else None,
            "ranking_url": cur_check[2], "target_url": k["target_url"],
        })
        counts[_bucket(cur_check[1])][0] += 1
        if old:
            counts[_bucket(old[1])][1] += 1
    rep.ranks.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["keyword"]))
    rep.committed = committed_keywords(con, we)
    rep.rank_buckets = counts
    from . import indexing as IX
    latest = IX.latest(con, ids)
    rep.index = {"ok": sum(1 for i in ids if i in latest and latest[i]["indexed"]),
                 "bad": sum(1 for i in ids if i in latest and not latest[i]["indexed"]), "total": len(ids)}
    if with_ai:
        rep.ai = ai_block(cfg, con, (ws, we))
        rep.organic = organic_block(cfg, con, (ws, we), rep.prev_week, trend_periods)
        rep.kpi = kpi_for_report(cfg, con, rep)
    rep.aio = aio_block(con, cfg.site_url, (ws, we), rep.prev_week, trend_periods)
    rep.okr = okr_block(con, cfg, (ws, we))
    return rep


def okr_block(con: sqlite3.Connection, cfg, period: tuple[date, date], today: date | None = None) -> dict | None:
    """Tiến độ OKR cho kỳ báo cáo + task Weekly Task Tracker của các tuần nằm trong kỳ. Trạng thái là trạng thái
    hiện tại trên sheet (sheet không lưu lịch sử), nên 'Trễ hạn' tính đến hôm nay."""
    from . import okr as O
    okr_cfg = getattr(cfg, "okr", None)
    if not okr_cfg or not O.sheet_id(okr_cfg.sheet):
        return None
    info = O.sync_info(con)
    if not info:
        return None
    s, e = period
    ov = O.overview(con, today or date.today(), period)
    ov["tasks"] = [t for t in O.tasks(con) if t["week"] and s.isoformat() <= t["week"] <= e.isoformat()]
    ov["synced"] = info["at"]
    return ov


def _by_type(con, site: str, cur: tuple[date, date], prev: tuple[date, date]) -> list[dict]:
    """Click/impression theo loại trang. Cộng theo URL (GSC tính theo trang), nên tổng khác tổng toàn site."""
    def q(s, e):
        return {t: (c, i) for t, c, i in con.execute(
            """SELECT COALESCE(u.type, 'Chờ đọc schema'), SUM(d.clicks), SUM(d.impressions)
               FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id JOIN urls u ON u.id = pu.url_id
               WHERE u.site = ? AND d.date BETWEEN ? AND ? GROUP BY 1""", (site, s.isoformat(), e.isoformat()))}
    now, old = q(*cur), q(*prev)
    rows = [{"type": t, "clicks": c, "impressions": i, "prev_clicks": old.get(t, (0, 0))[0],
             "change": change(c, old.get(t, (0, 0))[0])} for t, (c, i) in now.items()]
    return sorted(rows, key=lambda r: -r["clicks"])


def _top_urls(con, site: str, cur, prev, limit: int = 10) -> list[dict]:
    def q(s, e):
        return con.execute(
            """SELECT u.url, u.type, SUM(d.clicks), SUM(d.impressions)
               FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id JOIN urls u ON u.id = pu.url_id
               WHERE u.site = ? AND d.date BETWEEN ? AND ? GROUP BY u.id ORDER BY 3 DESC LIMIT ?""",
            (site, s.isoformat(), e.isoformat(), limit * 5)).fetchall()
    old = {u: c for u, _, c, _ in q(*prev)}
    return [{"url": u, "type": t or "", "clicks": c, "impressions": i, "prev": old.get(u), "change": change(c, old.get(u))}
            for u, t, c, i in q(*cur)[:limit]]


def _top_queries(con, site: str, cur, prev, limit: int = 10) -> list[dict]:
    """Query nhiều click nhất (cộng qua các URL). GSC ẩn phần lớn query hiếm, nên tổng nhỏ hơn click toàn site."""
    def q(s, e, n):
        return con.execute(
            """SELECT qq.text, SUM(d.clicks), SUM(d.impressions)
               FROM gsc_query_daily d JOIN pages p ON p.id = d.page_id JOIN queries qq ON qq.id = d.query_id
               WHERE p.site = ? AND d.date BETWEEN ? AND ? GROUP BY d.query_id ORDER BY 2 DESC LIMIT ?""",
            (site, s.isoformat(), e.isoformat(), n)).fetchall()
    old = {t: c for t, c, _ in q(*prev, limit * 20)}
    return [{"query": t, "clicks": c, "impressions": i, "prev": old.get(t), "change": change(c, old.get(t))}
            for t, c, i in q(*cur, limit)]


def aio_block(con: sqlite3.Connection, site: str, week: tuple[date, date], prev: tuple[date, date],
              trend_periods: list | None = None) -> dict | None:
    """Impression AI Overviews / AI Mode trong kỳ, từ file GSC Generative AI đã nhập. Kỳ chưa được file nào phủ hết
    thì không có số (không hiện 0)."""
    from . import ai_gsc_import as G
    if not G.imports(con, site):
        return None
    cur, old = G.period_total(con, site, *week), G.period_total(con, site, *prev)
    web = sum(G.web_daily(con, site, *week).values())
    web_prev = sum(G.web_daily(con, site, *prev).values())
    last = max(G.daily(con, site, date(2000, 1, 1), date(2100, 1, 1)), default=None)
    periods = trend_periods or [(week[0] - timedelta(days=7 * i), week[1] - timedelta(days=7 * i))
                                for i in range(7, -1, -1)]
    spark = [G.period_total(con, site, s, e)["impressions"] for s, e in periods]  # kỳ chưa đủ ngày là None
    webs = [sum(G.web_daily(con, site, s, e).values()) for s, e in periods]
    share_spark = [v / w if v is not None and w else None for v, w in zip(spark, webs)]
    return {"impressions": cur["impressions"], "prev": old["impressions"], "covered": cur["covered"], "spark": spark,
            "share_spark": share_spark,
            "share": cur["impressions"] / web if cur["impressions"] is not None and web else None,
            "prev_share": old["impressions"] / web_prev if old["impressions"] is not None and web_prev else None,
            "change": change(cur["impressions"], old["impressions"]), "data_until": last}


def summary(rep: "WeeklyReport") -> dict:
    """Tổng quan SEO + GEO của kỳ (trang đầu báo cáo). Mỗi bên 4 chỉ số và tối đa 2 điểm nổi bật, đều tính thẳng từ số
    liệu, không suy diễn.

    Chỉ số: {"short": nhãn ngắn để hiển thị, "label": nhãn đầy đủ (Excel/tooltip), "value", "delta", "good"}.
    Điểm nổi bật: {"short": chữ ngắn, "long": câu đầy đủ, "tone": up/down/info}. Thiếu nguồn thì value = "chưa có".
    """
    from . import ai_format as F
    unit = "tháng" if rep.kind == "month" else "tuần"

    def item(short, label, value, delta="", good=None):
        return {"short": short, "label": label, "value": value, "delta": delta, "good": good}

    def pct_item(short, label, now, prev, fmt=F.n):
        d = change(now, prev)
        return item(short, label, fmt(now), F.delta_pct(d, prev), None if not d else d > 0)

    sk, sp = rep.site_kpi, rep.site_prev
    top3, top3_prev = rep.rank_buckets.get("Top 3", [0, 0])
    top10 = top3 + rep.rank_buckets.get("Top 4–10", [0, 0])[0]
    top10_prev = top3_prev + rep.rank_buckets.get("Top 4–10", [0, 0])[1]
    has_prev = any(r["prev_depth"] for r in rep.ranks)
    idx = rep.index or {}
    seo = [
        pct_item("Click", "Click Google (toàn site, GSC)", sk.clicks, sp.clicks),
        pct_item("Impression", "Impression Google (toàn site, GSC)", sk.impressions, sp.impressions),
        # Lần check đầu tiên (chưa có lần trước) thì không ghi "+N": không phải tăng thật.
        item("Top 10", f"Keyword SEO trong top 10 / {len(rep.ranks)} keyword theo dõi",
             f"{top10}/{len(rep.ranks)}" if rep.ranks else "chưa có",
             f"{top10 - top10_prev:+d}" if has_prev and top10 != top10_prev else ("lần đầu" if rep.ranks and not has_prev
                                                                                  else ""),
             None if not has_prev or top10 == top10_prev else top10 > top10_prev),
        item("Index", f"URL nhóm {rep.group} đã index", f"{idx.get('ok', 0)}/{idx.get('total', 0)}" if idx
             else "chưa có", f"{idx['bad']} chưa" if idx.get("bad") else "", False if idx.get("bad") else None),
    ]

    ai = rep.ai if rep.ai and not rep.ai.get("error") else None
    aio = rep.aio if rep.aio and rep.aio["impressions"] is not None else None
    if ai:
        k, pv = ai["kpi"], ai.get("prev") or {}
        geo = [pct_item("Phiên AI", "Phiên từ AI assistant (GA4: ChatGPT, Gemini…)", k["sessions"], pv.get("sessions")),
               pct_item("Key events AI", "Key events từ phiên AI (GA4)", k["keyEvents"], pv.get("keyEvents"))]
    else:
        geo = [item("Phiên AI", "Phiên từ AI assistant (GA4)", "chưa có", ""),
               item("Key events AI", "Key events từ phiên AI (GA4)", "chưa có", "")]
    if aio:
        geo += [pct_item("AI Overviews", "Impression trong AI Overviews / AI Mode (GSC, nhập file)",
                         aio["impressions"], aio["prev"]),
                item("% trên Google", "Tỷ lệ impression AI Overviews trên impression Google Web",
                     F.pct(aio["share"], 1),
                     F.delta_points(aio["share"] - aio["prev_share"])
                     if aio.get("prev_share") is not None and aio["share"] is not None else "",
                     None if aio.get("prev_share") is None or aio["share"] is None
                     else aio["share"] > aio["prev_share"])]
    else:
        geo += [item("AI Overviews", "Impression trong AI Overviews / AI Mode (GSC, nhập file)", "chưa có", ""),
                item("% trên Google", "Tỷ lệ impression AI Overviews trên impression Google Web", "chưa có", "")]

    def note(short, long, tone):
        return {"short": short, "long": long, "tone": tone}

    seo_notes, geo_notes = [], []
    if rep.winners:
        w = rep.winners[0]
        seo_notes.append(note(f"{_path(w['url'], rep.site)} +{w['diff']}",
                              f"Trang tăng click nhiều nhất: {_path(w['url'], rep.site)} (+{w['diff']} click)", "up"))
    if rep.losers:
        lo = rep.losers[0]
        seo_notes.append(note(f"{_path(lo['url'], rep.site)} {lo['diff']}",
                              f"Trang giảm click nhiều nhất: {_path(lo['url'], rep.site)} ({lo['diff']} click)", "down"))
    wrong = sum(1 for r in rep.ranks if r["target_url"] and r["ranking_url"] and r["ranking_url"] != r["target_url"])
    if wrong:
        seo_notes.append(note(f"{wrong} từ khóa sai trang", f"{wrong} từ khóa đang xếp hạng bằng trang khác trang mục tiêu",
                              "warn"))
    if ai and ai["sources"]:
        top = ai["sources"][0]
        total = sum(x["sessions"] for x in ai["sources"]) or 1
        name = F.SOURCE_NAMES.get(top["source"], top["source"])
        share = f"{top['sessions'] / total * 100:.0f}%"
        geo_notes.append(note(f"{name} {share}", f"Nguồn AI lớn nhất: {name} ({share} phiên AI)", "info"))
    if ai and ai["share"]["ofAllSessions"] is not None:
        geo_notes.append(note(f"AI = {F.pct(ai['share']['ofAllSessions'])} tổng phiên",
                              f"AI assistant chiếm {F.pct(ai['share']['ofAllSessions'])} tổng phiên của site", "info"))
    return {"unit": unit, "seo": seo, "geo": geo, "seo_notes": seo_notes[:3], "geo_notes": geo_notes[:2]}


def _path(url: str, site: str) -> str:
    p = (url or "").replace(site.rstrip("/"), "") or "/"
    return "Trang chủ" if p == "/" else p


def rank_change(date_, rank, depth, prev, prev_depth) -> tuple[str, str, int]:
    """(chữ, màu, điểm để sắp xếp) cho thay đổi vị trí so với lần check trước; dùng chung cho màn rank, trang chủ và
    Excel. Vị trí nhỏ hơn là tốt hơn; ngoài độ sâu check thì nói rõ vào/rớt khỏi top N thay vì một con số giả."""
    green, red, grey = "#1E7C31", "#C2410C", "#8C8A7E"
    if not date_:
        return "", grey, 0
    if not prev_depth:
        return "Mới", "#2563EB", 0
    if rank is not None and prev is not None:
        d = prev - rank
        return ("–", grey, 0) if d == 0 else ((f"▲ {d}", green, d) if d > 0 else (f"▼ {-d}", red, d))
    if rank is not None:
        return f"▲ vào top {prev_depth}", green, 100
    if prev is not None:
        return f"▼ rớt khỏi top {depth}", red, -100
    return "–", grey, 0


def change(now, prev) -> float | None:
    if now is None or prev in (None, 0):
        return None
    return (now - prev) / prev
