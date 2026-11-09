"""Tổng quan một từ khóa (giống Keyword Overview của Semrush), từ Google Ads API (miễn phí) + dữ liệu đã có:

- Volume Việt Nam, volume toàn cầu và vài nước lớn, xu hướng 12 tháng, giá thầu (CPC), mức cạnh tranh quảng cáo.
- Ý định tìm kiếm (quy tắc, miễn phí).
- Biến thể từ khóa, câu hỏi, nhóm chủ đề (từ ý tưởng Keyword Planner).
- Site đang có hạng không (Search Console 28 ngày).
- Phân tích trang kết quả Google (top 10, ô đặc biệt, AI Overview): lấy từ lần check hạng gần nhất nếu từ khóa đang
  được theo dõi (không gọi thêm DataForSEO).

Mỗi lần xem tốn khoảng 8 lượt Google Ads; kết quả lưu 7 ngày, xem lại không gọi lại."""
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from . import keyword_research as KR
from . import keywords as K

SCHEMA = """
CREATE TABLE IF NOT EXISTS kw_serp_cache (
    key TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kw_overview (
    key TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    data TEXT NOT NULL
);
"""
CACHE_DAYS = 7
COUNTRIES = (("US", "Mỹ", 2840), ("UK", "Anh", 2826), ("AU", "Úc", 2036), ("CA", "Canada", 2124),
             ("DE", "Đức", 2276))
IDEAS = 300
FEATURES = {"ai_overview": "AI Overview", "featured_snippet": "Đoạn trích nổi bật", "people_also_ask": "Mọi người cũng hỏi",
            "people_also_search": "Tìm kiếm liên quan", "images": "Hình ảnh", "video": "Video", "local_pack": "Bản đồ",
            "shopping": "Mua sắm", "top_stories": "Tin nổi bật", "knowledge_graph": "Knowledge Panel",
            "related_searches": "Tìm kiếm liên quan", "twitter": "X / Twitter", "carousel": "Băng chuyền",
            "perspectives": "Góc nhìn", "discussions_and_forums": "Diễn đàn"}


def ensure_tables(con) -> None:
    con.executescript(SCHEMA)


def recent(con, limit: int = 50) -> list[dict]:
    """Từ khóa đã phân tích, mới nhất trước: {keyword, at, volume, cpc}."""
    ensure_tables(con)
    out = []
    for at, data in con.execute("SELECT fetched_at, data FROM kw_overview ORDER BY fetched_at DESC LIMIT ?", (limit,)):
        d = json.loads(data)
        vn = d.get("vn") or {}
        out.append({"keyword": d["keyword"], "at": at, "volume": vn.get("volume"), "cpc": KR.cpc(vn)})
    return out


def _pick(rows: list[dict], kw: str) -> dict:
    """Dòng số của đúng từ khóa (giữ dấu), không có thì dòng đầu (Google gộp biến thể gần giống)."""
    k = KR.ckey(kw)
    return next((r for r in rows if KR.ckey(r["keyword"]) == k), rows[0] if rows else {})


def fetch(con, cfg, kw: str, ads) -> dict:
    """Gọi Google Ads (khoảng 8 lượt) và gom số. Không đọc / ghi cache."""
    from . import google_ads as GA
    loc, lang = cfg.rank.location_code, cfg.rank.language_code
    vn = _pick(GA.metrics(*ads, [kw], loc, lang), kw)
    world = _pick(GA.metrics(*ads, [kw], None, ""), kw)
    countries = []
    for code, name, geo in COUNTRIES:
        r = _pick(GA.metrics(*ads, [kw], geo, ""), kw)
        countries.append({"code": code, "name": name, "volume": r.get("volume")})
    ideas = GA.keyword_ideas(*ads, loc, lang, keywords=[kw], limit=IDEAS)
    KR.save_cpc(con, ideas + ([vn] if vn else []))
    KR.currency(con, cfg, ads)
    return {"keyword": kw, "vn": vn, "world": world, "countries": countries, "ideas": ideas}


def get(con, cfg, kw: str, ads=None, refresh: bool = False) -> dict:
    """Tổng quan từ khóa: số Google Ads (cache 7 ngày) + phần tính từ dữ liệu sẵn có (luôn mới)."""
    ensure_tables(con)
    kw = " ".join((kw or "").split())
    if not kw:
        raise ValueError("Nhập một từ khóa")
    key = KR.ckey(kw)
    row = con.execute("SELECT fetched_at, data FROM kw_overview WHERE key = ?", (key,)).fetchone()
    fresh = row and datetime.fromisoformat(row[0]) > datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)
    if fresh and not refresh:
        raw, at = json.loads(row[1]), row[0]
    else:
        raw = fetch(con, cfg, kw, ads or KR.client(cfg))
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with con:
            con.execute("INSERT OR REPLACE INTO kw_overview VALUES (?, ?, ?)",
                        (key, at, json.dumps(raw, ensure_ascii=False)))
    return build(con, cfg, raw, at)


def build(con, cfg, raw: dict, at: str) -> dict:
    """Ghép số Google Ads đã có với Search Console, check hạng, đối thủ, ý định, nhóm chủ đề."""
    from . import intent as IN
    from .seo_value import season
    kw = raw["keyword"]
    vn = raw.get("vn") or {}
    monthly = [tuple(x) for x in vn.get("monthly") or []]
    ideas = KR.annotate(con, cfg, raw.get("ideas") or [])
    words = [w for w in (K.fold(x) for x in kw.split()) if w]
    variations = [r for r in ideas if all(f" {w} " in f" {' '.join(K.fold(x) for x in r['keyword'].split())} "
                                          for w in words)]
    questions = [r for r in ideas if r.get("question")]
    groups = KR.clusters(ideas, cfg.site_url)
    end = K.latest_date(con, cfg.site_url)
    gsc = KR.gsc_by_query(con, cfg.site_url, end).get(KR.ckey(kw))
    own_terms = list(cfg.keywords.brand_terms)
    return {"keyword": kw, "at": at, "currency": KR.currency(con, cfg),
            "volume": vn.get("volume"), "world": (raw.get("world") or {}).get("volume"),
            "countries": raw.get("countries") or [], "monthly": monthly, "trend": KR.trend(monthly),
            "season": season(monthly, date.today()), "cpc": KR.cpc(vn), "low_bid": vn.get("low_bid"),
            "high_bid": vn.get("high_bid"), "competition": vn.get("competition"),
            "competition_index": vn.get("competition_index"),
            "intent": IN.classify(kw, brand_terms=own_terms)[0], "question": KR.is_question(kw),
            "variations": variations, "variations_volume": sum(r["volume"] or 0 for r in variations),
            "questions": questions, "questions_volume": sum(r["volume"] or 0 for r in questions),
            "groups": groups, "ideas": len(ideas),
            "site": {"clicks": gsc["clicks"], "impressions": gsc["impressions"], "position": gsc["position"],
                     "page": gsc["page"]} if gsc else None,
            "serp": serp(con, cfg, kw, raw.get("serp_live"))}


LIVE_EST_USD = 0.002  # ước tính một lần xem trang kết quả (top 10, chế độ live của DataForSEO)


def fetch_serp(con, cfg, kw: str, user: str, client=None) -> dict:
    """Lấy ngay trang kết quả Google (top 10) cho một từ khóa chưa theo dõi hạng, lưu vào tổng quan 7 ngày. Có tốn
    tiền DataForSEO: kiểm tra tạm ngưng và ngân sách tháng trước khi gọi, ghi chi phí vào nhật ký chi tiền."""
    from . import rank as R
    if getattr(cfg.rank, "paused", False):
        raise RuntimeError("Website đang tạm ngưng mọi chi phí DataForSEO (trang Ngân sách).")
    spent = R.spent_this_month(con)
    if spent + LIVE_EST_USD > cfg.rank.monthly_budget_usd:
        raise RuntimeError(f"Đã dùng {R.usd(spent)} USD tháng này, chạm ngân sách {cfg.rank.monthly_budget_usd:.0f} "
                           "USD: tăng ngân sách ở trang Ngân sách để xem thêm.")
    if client is None:
        creds = R.load_credentials(cfg.dataforseo_secret)
        if not creds:
            raise RuntimeError("Chưa có tài khoản DataForSEO (Cài đặt tích hợp).")
        client = R.DataForSEO(*creds)
    s = cfg.rank
    task = client.live({"keyword": kw, "location_code": s.location_code, "language_code": s.language_code,
                        "device": s.device, "se_domain": s.se_domain, "depth": 10})
    if task.get("status_code") not in (None, 20000):
        raise RuntimeError(f"DataForSEO {task.get('status_code')}: {task.get('status_message')}")
    parsed = R.parse_serp(task, cfg.site_url)
    cost = float(task.get("cost") or LIVE_EST_USD)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.execute(R.SERP_LOOKUP_SCHEMA)
    ensure_tables(con)
    key = KR.ckey(kw)
    row = con.execute("SELECT data FROM kw_overview WHERE key = ?", (key,)).fetchone()
    with con:
        con.execute("INSERT INTO serp_lookups VALUES (?, ?, ?, ?)", (now, kw, cost, user))
        con.execute("INSERT OR REPLACE INTO kw_serp_cache VALUES (?, ?, ?)",
                    (key, now, json.dumps(parsed, ensure_ascii=False)))
        if row:
            data = json.loads(row[0])
            data["serp_live"] = {"at": now, "cost": cost, **parsed}
            con.execute("UPDATE kw_overview SET data = ? WHERE key = ?", (json.dumps(data, ensure_ascii=False), key))
    return {"at": now, "cost": cost, **parsed}


def serp(con, cfg, kw: str, live: dict | None = None) -> dict | None:
    """Trang kết quả Google của lần check hạng gần nhất (nếu từ khóa đang / đã được theo dõi): top kết quả tự nhiên
    (đánh dấu của mình / đối thủ), ô đặc biệt, AI Overview và nguồn được trích, vị trí của site."""
    from . import aio as AO
    try:
        ids = [i for i, t in con.execute("SELECT id, keyword FROM rank_keywords WHERE site = ?", (cfg.site_url,))
               if KR.ckey(t) == KR.ckey(kw)]
    except sqlite3.Error:
        return None
    if not ids:
        return _from_live(con, cfg, live) if live else None
    row = con.execute(
        f"SELECT keyword_id, check_date, aio, aio_cited, aio_refs, features, organic, top10 FROM rank_serp "
        f"WHERE keyword_id IN ({','.join('?' * len(ids))}) AND (organic IS NOT NULL OR top10 IS NOT NULL) "
        f"ORDER BY check_date DESC LIMIT 1", ids).fetchone()
    if not row:
        if live:
            return _from_live(con, cfg, live)
        return {"tracked": True, "date": None, "results": [], "features": [], "aio": None}
    kid, day, aio, cited, refs, feats, organic, top10 = row
    results = json.loads(organic) if organic else json.loads(top10 or "[]")
    brands = AO.brands(con, cfg)
    out = []
    for r in sorted(results, key=lambda x: x["rank"]):
        b = next((b for b in brands if AO.cited([r], b)), None)
        out.append({"rank": r["rank"], "url": r["url"], "domain": r["domain"],
                    "brand": b["name"] if b else None, "own": bool(b and b["own"])})
    own = next((r["rank"] for r in out if r["own"]), None)
    rank_row = con.execute("SELECT depth FROM rank_checks WHERE keyword_id = ? AND check_date = ?",
                           (kid, day)).fetchone()
    return {"tracked": True, "date": day, "results": out, "depth": rank_row[0] if rank_row else None,
            "features": [FEATURES.get(f, f) for f in json.loads(feats or "[]")], "own_rank": own,
            "aio": None if aio is None else {"shown": bool(aio), "cited": bool(cited),
                                             "refs": json.loads(refs or "[]")}}


def _from_live(con, cfg, live: dict) -> dict:
    """Trang kết quả lấy một lần (không theo dõi hạng) theo cùng dạng với kết quả từ check hạng."""
    from . import aio as AO
    brands = AO.brands(con, cfg)
    out = []
    for r in sorted(live.get("organic") or live.get("top10") or [], key=lambda x: x["rank"]):
        b = next((b for b in brands if AO.cited([r], b)), None)
        out.append({"rank": r["rank"], "url": r["url"], "domain": r["domain"],
                    "brand": b["name"] if b else None, "own": bool(b and b["own"])})
    return {"tracked": False, "live": True, "date": live["at"][:10], "at": live["at"], "cost": live.get("cost"),
            "results": out, "depth": 10, "features": [FEATURES.get(f, f) for f in live.get("features") or []],
            "own_rank": next((r["rank"] for r in out if r["own"]), None),
            "aio": {"shown": bool(live.get("aio")), "cited": bool(live.get("aio_cited")),
                    "refs": live.get("aio_refs") or []}}


def check_aio(con, cfg, keywords: list[str], user: str, client=None, progress=None) -> dict:
    """Xem trang kết quả Google một lần cho từng từ khóa chưa có số AI Overview (có tốn tiền DataForSEO, dừng khi
    chạm ngân sách / tạm ngưng). {"done", "skipped", "error"}."""
    known = KR.aio_known(con, cfg.site_url)
    todo = [k for k in keywords if KR.ckey(k) not in known]
    done, error = 0, None
    for i, kw in enumerate(todo, 1):
        try:
            fetch_serp(con, cfg, kw, user, client=client)
            done += 1
        except Exception as e:  # noqa: BLE001 — ngân sách / tạm ngưng / lỗi mạng: dừng, báo lại
            error = str(e)
            break
        if progress:
            progress(i, len(todo))
    return {"done": done, "skipped": len(keywords) - len(todo), "error": error}
