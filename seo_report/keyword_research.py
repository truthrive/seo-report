"""Research từ khóa và giá trị traffic SEO, từ Google Ads API (Keyword Planner, miễn phí ở mức Basic):

- research(): ý tưởng từ khóa từ từ khóa gốc / một trang / cả website (của mình hoặc đối thủ), kèm volume, xu hướng
  12 tháng, cạnh tranh, giá thầu; đối chiếu Search Console (site đã có hạng chưa) và danh sách đang theo dõi hạng.
  Mỗi lần research được lưu lại để team mở lại.
- refresh_cpc() / traffic_value(): giá thầu (CPC) của các từ khóa mang click SEO về, để quy click SEO ra số tiền
  tương đương nếu phải mua bằng Google Ads.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import keywords as K

SCHEMA = """
CREATE TABLE IF NOT EXISTS kw_research (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    mode TEXT NOT NULL,          -- keywords / url / site
    seed TEXT NOT NULL,
    n INTEGER NOT NULL,
    results TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kw_cpc (
    fold TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    volume INTEGER,
    competition TEXT,
    low_bid REAL,
    high_bid REAL,
    monthly TEXT NOT NULL DEFAULT '[]',
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kw_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
MODES = {"keywords": "Từ khóa gốc", "url": "Một trang (URL)", "site": "Cả website"}
HISTORY = 30  # số lần research giữ lại
LIMIT = 1000  # ý tưởng tối đa mỗi lần
CPC_MAX_AGE = 30  # ngày: giá thầu cũ hơn thì lấy lại
CPC_TOP = 2000  # từ khóa nhiều click nhất cần giá thầu (phủ gần hết click SEO)
CPC_BATCH = 1000


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cpc(r: dict) -> float | None:
    """CPC ước tính: trung bình giá thầu đầu trang thấp và cao."""
    lo, hi = r.get("low_bid"), r.get("high_bid")
    if lo is None and hi is None:
        return None
    return round(((lo or hi) + (hi or lo)) / 2, 2)


def client(cfg):
    """(creds, settings) của Google Ads; chưa cấu hình / chưa cấp quyền: RuntimeError có câu dễ hiểu."""
    from . import auth
    from . import google_ads as GA
    settings = GA.load_settings(getattr(cfg, "google_ads_secret", Path("secrets/google_ads.toml")))
    if not settings:
        raise RuntimeError("Chưa cấu hình Google Ads API (Cài đặt tích hợp → Google Ads).")
    try:
        return auth.get_credentials(cfg, need=(auth.ADS_SCOPE,)), settings
    except SystemExit:
        raise RuntimeError("Tài khoản Google của tool chưa cấp quyền Google Ads (Cài đặt tích hợp → Kết nối "
                           "Google).") from None


def currency(con, cfg, ads=None) -> str:
    """Đơn vị tiền của tài khoản Google Ads (lưu lại, hỏi một lần)."""
    ensure_tables(con)
    row = con.execute("SELECT value FROM kw_meta WHERE key = 'currency'").fetchone()
    if row:
        return row[0]
    if ads is None:
        return "VND"
    from . import google_ads as GA
    cur = GA.currency(*ads)
    with con:
        con.execute("INSERT OR REPLACE INTO kw_meta VALUES ('currency', ?)", (cur,))
    return cur


def save_cpc(con, rows: list[dict]) -> int:
    """Lưu số Keyword Planner theo từ khóa (bỏ dấu) để dùng lại cho giá trị traffic."""
    ensure_tables(con)
    at = _now()
    with con:
        for r in rows:
            f = K.fold(r["keyword"])
            if f:
                con.execute("INSERT OR REPLACE INTO kw_cpc VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (f, r["keyword"], r.get("volume"), r.get("competition"), r.get("low_bid"),
                             r.get("high_bid"), json.dumps(r.get("monthly") or []), at))
    return len(rows)


# ---- Đối chiếu Search Console + danh sách theo dõi ----

def gsc_by_query(con, site: str, end: date, days: int = 28) -> dict[str, dict]:
    """Số GSC theo từ khóa (bỏ dấu) trong `days` ngày: click, hiển thị, vị trí, trang nhận nhiều nhất."""
    s = (end - timedelta(days=days - 1)).isoformat()
    out: dict[str, dict] = {}
    for text, page, c, i, pw in con.execute(
            """SELECT q.text, p.url, SUM(d.clicks), SUM(d.impressions), SUM(d.position * d.impressions)
               FROM gsc_query_daily d JOIN queries q ON q.id = d.query_id
               JOIN pages p ON p.id = d.page_id AND p.site = ?
               WHERE d.date BETWEEN ? AND ? GROUP BY d.query_id, d.page_id""", (site, s, end.isoformat())):
        f = K.fold(text)
        o = out.setdefault(f, {"clicks": 0, "impressions": 0, "pw": 0.0, "page": None, "page_impr": -1})
        o["clicks"] += c or 0
        o["impressions"] += i or 0
        o["pw"] += pw or 0
        if (i or 0) > o["page_impr"]:
            o["page"], o["page_impr"] = page, i or 0
    for o in out.values():
        o["position"] = round(o.pop("pw") / o["impressions"], 1) if o["impressions"] else None
        o.pop("page_impr")
    return out


def annotate(con, cfg, rows: list[dict], end: date | None = None) -> list[dict]:
    """Thêm cho mỗi ý tưởng: số GSC 28 ngày (site đã có hạng chưa), đang theo dõi hạng chưa, thương hiệu, CPC."""
    from .opportunities import _tracked
    site = cfg.site_url
    end = end or K.latest_date(con, site)
    gsc = gsc_by_query(con, site, end)
    tracked = _tracked(con, site)
    brand = cfg.keywords.brand_terms
    out = []
    for r in rows:
        f = K.fold(r["keyword"])
        g = gsc.get(f)
        out.append({**r, "cpc": cpc(r), "tracked": f in tracked, "brand": K.is_brand(r["keyword"], brand),
                    "gsc_clicks": g["clicks"] if g else 0, "gsc_impr": g["impressions"] if g else 0,
                    "gsc_pos": g["position"] if g else None, "gsc_page": g["page"] if g else None})
    return out


# ---- Research ----

def parse_seed(mode: str, text: str) -> dict:
    """Chữ người dùng nhập → tham số keyword_ideas."""
    text = (text or "").strip()
    if mode == "site":
        host = text.replace("https://", "").replace("http://", "").split("/")[0].removeprefix("www.")
        if "." not in host:
            raise ValueError("Nhập tên miền, ví dụ doithu.vn")
        return {"site": host}
    if mode == "url":
        if not text.startswith("http"):
            raise ValueError("Nhập đầy đủ địa chỉ trang, bắt đầu bằng https://")
        return {"url": text.split()[0]}
    kws = [k.strip() for k in text.replace(",", "\n").splitlines() if k.strip()]
    if not kws:
        raise ValueError("Nhập ít nhất một từ khóa")
    if len(kws) > 20:
        raise ValueError("Tối đa 20 từ khóa gốc mỗi lần")
    return {"keywords": kws}


def research(con, cfg, mode: str, seed: str, user: str, ads=None, limit: int = LIMIT) -> dict:
    """Gọi Keyword Planner, đối chiếu, lưu thành một lần research. Trả bản ghi (như get())."""
    from . import google_ads as GA
    if mode not in MODES:
        raise ValueError("Chế độ không hợp lệ")
    params = parse_seed(mode, seed)
    ads = ads or client(cfg)
    rows = GA.keyword_ideas(*ads, cfg.rank.location_code, cfg.rank.language_code, limit=limit, **params)
    save_cpc(con, rows)
    currency(con, cfg, ads)
    ensure_tables(con)
    with con:
        rid = con.execute("INSERT INTO kw_research (created_at, created_by, mode, seed, n, results) VALUES "
                          "(?, ?, ?, ?, ?, ?)", (_now(), user, mode, seed.strip()[:500], len(rows),
                                                 json.dumps(rows, ensure_ascii=False))).lastrowid
        con.execute("DELETE FROM kw_research WHERE id NOT IN (SELECT id FROM kw_research ORDER BY id DESC LIMIT ?)",
                    (HISTORY,))
    return get(con, cfg, rid)


def history(con) -> list[dict]:
    ensure_tables(con)
    return [{"id": i, "at": a, "by": b, "mode": m, "seed": s, "n": n} for i, a, b, m, s, n in con.execute(
        "SELECT id, created_at, created_by, mode, seed, n FROM kw_research ORDER BY id DESC")]


def get(con, cfg, rid: int) -> dict | None:
    ensure_tables(con)
    r = con.execute("SELECT id, created_at, created_by, mode, seed, results FROM kw_research WHERE id = ?",
                    (rid,)).fetchone()
    if not r:
        return None
    return {"id": r[0], "at": r[1], "by": r[2], "mode": r[3], "seed": r[4],
            "rows": annotate(con, cfg, json.loads(r[5])), "currency": currency(con, cfg)}


def delete(con, rid: int) -> None:
    with con:
        con.execute("DELETE FROM kw_research WHERE id = ?", (rid,))


# ---- Giá trị traffic SEO ----

def _queries(con, site: str, start: date, end: date) -> list[tuple[str, int]]:
    return con.execute(
        """SELECT q.text, SUM(d.clicks) FROM gsc_query_daily d JOIN queries q ON q.id = d.query_id
           JOIN pages p ON p.id = d.page_id AND p.site = ?
           WHERE d.date BETWEEN ? AND ? GROUP BY d.query_id HAVING SUM(d.clicks) > 0
           ORDER BY SUM(d.clicks) DESC""", (site, start.isoformat(), end.isoformat())).fetchall()


def refresh_cpc(con, cfg, end: date | None = None, top: int = CPC_TOP, force: bool = False, ads=None,
                log=print) -> int:
    """Lấy giá thầu cho các từ khóa (không phải thương hiệu) mang nhiều click SEO nhất 90 ngày qua mà chưa có hoặc đã
    cũ hơn 30 ngày. Trả số từ khóa đã hỏi."""
    from . import google_ads as GA
    ensure_tables(con)
    site = cfg.site_url
    end = end or K.latest_date(con, site)
    brand = cfg.keywords.brand_terms
    fresh_since = (datetime.now(timezone.utc) - timedelta(days=CPC_MAX_AGE)).isoformat()
    fresh = {f for f, in con.execute("SELECT fold FROM kw_cpc WHERE fetched_at >= ?", (fresh_since,))} \
        if not force else set()
    want, seen = [], set()
    for text, _ in _queries(con, site, end - timedelta(days=89), end):
        f = K.fold(text)
        if f in seen or K.is_brand(text, brand) or len(text) > 80 or len(text.split()) > 10:
            continue
        seen.add(f)
        if f not in fresh:
            want.append(text)
        if len(seen) >= top:
            break
    if not want:
        return 0
    ads = ads or client(cfg)
    currency(con, cfg, ads)
    asked = 0
    for i in range(0, len(want), CPC_BATCH):
        chunk = want[i:i + CPC_BATCH]
        rows = GA.metrics(*ads, chunk, cfg.rank.location_code, cfg.rank.language_code)
        got = {K.fold(r["keyword"]) for r in rows}
        # từ khóa Google không có số: lưu dòng trống để tháng này không hỏi lại
        rows += [{"keyword": t} for t in chunk if K.fold(t) not in got]
        save_cpc(con, rows)
        asked += len(chunk)
    log(f"Giá thầu Google Ads: đã lấy cho {asked} từ khóa (miễn phí).")
    return asked


def traffic_value(con, cfg, start: date, end: date) -> dict:
    """Click SEO (không tính từ khóa thương hiệu) × CPC ước tính. Chỉ tính từ khóa GSC cho biết và đã có giá thầu:
    là mức tối thiểu. {"value", "currency", "clicks", "priced_clicks", "top": [...]}."""
    ensure_tables(con)
    prices = {f: (t, cpc({"low_bid": lo, "high_bid": hi})) for f, t, lo, hi in con.execute(
        "SELECT fold, text, low_bid, high_bid FROM kw_cpc")}
    brand = cfg.keywords.brand_terms
    value, clicks, priced = 0.0, 0, 0
    per: dict[str, list] = {}
    for text, c in _queries(con, cfg.site_url, start, end):
        if K.is_brand(text, brand):
            continue
        clicks += c
        f = K.fold(text)
        p = prices.get(f, (None, None))[1]
        if p:
            value += c * p
            priced += c
            row = per.setdefault(f, [text, 0, p])
            row[1] += c
    top = sorted(per.values(), key=lambda r: -r[1] * r[2])[:20]
    return {"value": round(value), "currency": currency(con, cfg), "clicks": clicks, "priced_clicks": priced,
            "has_prices": bool(prices),
            "top": [{"query": q, "clicks": c, "cpc": p, "value": round(c * p)} for q, c, p in top]}


def money(v: float | None, cur: str = "VND") -> str:
    """Số tiền gọn: 12,3 triệu ₫ / 1,2 tỷ ₫ / 850 nghìn ₫; tiền khác: 1.234 USD."""
    if v is None:
        return "–"
    if cur != "VND":
        return f"{v:,.0f} {cur}".replace(",", ".")
    for div, unit in ((1e9, "tỷ"), (1e6, "triệu"), (1e3, "nghìn")):
        if abs(v) >= div:
            return f"{v / div:,.1f}".replace(",", " ").replace(".", ",").replace(" ", ".").replace(",0", "") \
                + f" {unit} ₫"
    return f"{v:,.0f} ₫".replace(",", ".")


def refresh(con, cfg, log=print) -> int:
    """Lịch hằng ngày: bổ sung giá thầu còn thiếu / đã cũ (không gọi gì khi chưa cấu hình Google Ads)."""
    try:
        ads = client(cfg)
    except RuntimeError:
        return 0
    return refresh_cpc(con, cfg, ads=ads, log=log)
