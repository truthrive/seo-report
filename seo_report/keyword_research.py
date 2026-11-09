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
from urllib.parse import urlsplit

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
MODES = {"keywords": "Từ khóa gốc", "list": "Danh sách từ khóa", "url": "Một trang (URL)", "site": "Cả website",
         "rank_url": "Tra URL (từ khóa đang có hạng)"}
HISTORY = 30  # số lần research giữ lại
LIMIT = 1000  # ý tưởng tối đa mỗi lần
CPC_MAX_AGE = 30  # ngày: giá thầu cũ hơn thì lấy lại
CPC_TOP = 2000  # từ khóa nhiều click nhất cần giá thầu (phủ gần hết click SEO)
CPC_BATCH = 1000


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM kw_meta WHERE key = 'cpc_key'").fetchone():
        rows = con.execute("SELECT fold, text, volume, competition, low_bid, high_bid, monthly, fetched_at FROM kw_cpc "
                           "ORDER BY fetched_at").fetchall()
        with con:
            con.execute("DELETE FROM kw_cpc")
            con.executemany("INSERT OR REPLACE INTO kw_cpc VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            [(ckey(t), t, *rest) for _, t, *rest in rows])
            con.execute("INSERT OR REPLACE INTO kw_meta VALUES ('cpc_key', 'v2')")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ckey(text: str) -> str:
    """Khóa so khớp từ khóa giữa Google Ads và Search Console: chữ thường, gọn khoảng trắng, GIỮ dấu (bỏ dấu thì
    "kính cận" và "kinh can" — hai từ khóa có volume khác hẳn — bị gộp làm một)."""
    return " ".join((text or "").lower().split())


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
            f = ckey(r["keyword"])
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
        f = ckey(text)
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


def trend(monthly: list) -> str:
    """Xu hướng 3 tháng gần nhất so với 3 tháng trước đó: "up" (tăng ≥ 20%), "down" (giảm ≥ 20%), "" (đi ngang /
    chưa đủ số)."""
    if len(monthly) < 6:
        return ""
    last = sum(n for _, n in monthly[-3:])
    before = sum(n for _, n in monthly[-6:-3])
    if not before:
        return "up" if last else ""
    ratio = last / before
    return "up" if ratio >= 1.2 else "down" if ratio <= 0.8 else ""


QUESTION = ("la gi", "cach", "tai sao", "vi sao", "the nao", "bao nhieu", "bao lau", "o dau", "co nen", "nao tot",
            "loai nao", "lam sao", "khi nao", "hang nao")


def is_question(keyword: str) -> bool:
    """Từ khóa dạng câu hỏi: có dấu ?, có cụm hỏi (là gì, cách, bao nhiêu, ở đâu…) hoặc kết thúc bằng không / chưa."""
    words = [w for w in (K.fold(x) for x in keyword.lower().split()) if w]
    k = " " + " ".join(words) + " "
    return "?" in keyword or any(f" {q} " in k for q in QUESTION) or bool(words and words[-1] in ("khong", "ko",
                                                                                                "chua"))


def annotate(con, cfg, rows: list[dict], end: date | None = None) -> list[dict]:
    """Thêm cho mỗi ý tưởng: số GSC 28 ngày (site đã có hạng chưa), đang theo dõi hạng chưa, thương hiệu của mình /
    đối thủ, ý định tìm kiếm (quy tắc, miễn phí; có số DataForSEO đã lưu thì dùng), số từ, câu hỏi, xu hướng, mùa,
    CPC."""
    from . import aio as AO
    from . import intent as IN
    from .opportunities import _tracked
    from .seo_value import season
    site = cfg.site_url
    end = end or K.latest_date(con, site)
    gsc = gsc_by_query(con, site, end)
    tracked = _tracked(con, site)
    brand = cfg.keywords.brand_terms
    try:
        bs = AO.brands(con, cfg)
    except sqlite3.Error:
        bs = []
    own_terms = list(brand) + [t for b in bs if b["own"] for t in [b["name"], *b["aliases"]]]
    rival_terms = [t for b in bs if not b["own"] for t in [b["name"], *b["aliases"],
                                                           *[d.split(".")[0] for d in b["domains"]]] if len(t) > 2]
    try:
        stored = IN.stored(con, cfg.rank.language_code)
    except (sqlite3.Error, AttributeError):
        stored = {}
    today = date.today()
    aio = aio_known(con, site)
    out = []
    for r in rows:
        kw = r["keyword"]
        f = K.fold(kw)
        g = gsc.get(ckey(kw))
        known = stored.get(IN._key(kw)) if stored else None
        intent = (IN.CODES.get(known["intent"]) if known else None) or IN.classify(
            kw, brand_terms=own_terms + rival_terms)[0]
        monthly = r.get("monthly") or []
        out.append({**r, "cpc": cpc(r), "tracked": f in tracked, "brand": K.is_brand(kw, own_terms),
                    "rival": K.is_brand(kw, rival_terms), "intent": intent, "words": len(kw.split()),
                    "question": is_question(kw), "trend": trend(monthly), "aio": aio.get(ckey(kw)),
                    "soon": season([tuple(x) for x in monthly], today)["soon"],
                    "gsc_clicks": g["clicks"] if g else 0, "gsc_impr": g["impressions"] if g else 0,
                    "gsc_pos": g["position"] if g else None, "gsc_page": g["page"] if g else None})
    set_pillars(out)
    return out


def set_pillars(rows: list[dict]) -> None:
    """Pillar (từ khóa chính) của mỗi từ khóa: các từ khóa cùng lên một URL (Search Console) nhận chung từ khóa có
    thứ hạng cao nhất trên URL đó (bằng nhau thì nhiều volume hơn). Từ khóa chưa có hạng: không có pillar."""
    best: dict[str, dict] = {}
    for r in rows:
        page, pos = r.get("gsc_page"), r.get("gsc_pos")
        if not page or pos is None:
            continue
        b = best.get(page)
        if b is None or (pos, -(r.get("volume") or 0)) < (b["gsc_pos"], -(b.get("volume") or 0)):
            best[page] = r
    for r in rows:
        b = best.get(r.get("gsc_page")) if r.get("gsc_pos") is not None else None
        r["pillar"] = b["keyword"] if b else None
        r["is_pillar"] = bool(b and b is r)


def aio_known(con, site: str) -> dict[str, dict]:
    """AI Overview đã biết của từng từ khóa (giữ dấu): lần check hạng gần nhất, hoặc lần xem / check AIO một lần
    (mới hơn thì lấy). {ckey: {"shown", "cited", "at"}}."""
    out: dict[str, dict] = {}
    try:
        for kw, a, c, d in con.execute(
                "SELECT k.keyword, s.aio, s.aio_cited, s.check_date FROM rank_serp s JOIN rank_keywords k "
                "ON k.id = s.keyword_id WHERE k.site = ? AND s.aio IS NOT NULL ORDER BY s.check_date", (site,)):
            out[ckey(kw)] = {"shown": bool(a), "cited": bool(c), "at": d, "src": "rank"}
    except sqlite3.Error:
        pass
    try:
        for key, at, data in con.execute("SELECT key, at, data FROM kw_serp_cache ORDER BY at"):
            if key not in out or out[key]["at"] <= at[:10]:
                d = json.loads(data)
                out[key] = {"shown": bool(d.get("aio")), "cited": bool(d.get("aio_cited")), "at": at[:10],
                            "src": "live"}
    except sqlite3.Error:
        pass
    return out


# ---- Bộ lọc (kiểu Semrush) ----

FILTER_DEFAULT = {"vol": [None, None], "comp": [], "intent": [], "cpc": [None, None], "inc": [], "inc_all": False,
                  "exc": [], "exc_tracked": False, "exc_brand": False, "exc_rival": False, "words": [None, None],
                  "site": "all", "trend": "all", "question": False}
SITE_FILTERS = {"all": "Mọi vị trí", "none": "Site chưa có hạng", "has": "Site đã có hạng", "top10": "Site trong top 10",
                "11_30": "Site ở vị trí 11–30", "gt30": "Site ngoài top 30"}
TREND_FILTERS = {"all": "Mọi xu hướng", "up": "Đang tăng (3 tháng gần nhất +20%)",
                 "down": "Đang giảm (3 tháng gần nhất −20%)", "soon": "Sắp vào mùa (2 tháng tới cao hơn TB năm)"}


def _in_range(v, lo, hi) -> bool:
    if lo is None and hi is None:
        return True
    if v is None:
        return False
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def apply_filters(rows: list[dict], f: dict) -> list[dict]:
    """Lọc các dòng đã annotate theo bộ lọc `f` (khóa như FILTER_DEFAULT)."""
    f = {**FILTER_DEFAULT, **(f or {})}
    inc = [K.fold(w) for w in f["inc"] if K.fold(w)]
    exc = [K.fold(w) for w in f["exc"] if K.fold(w)]
    out = []
    for r in rows:
        k = K.fold(r["keyword"])
        if not _in_range(r.get("volume"), *f["vol"]) or not _in_range(r.get("cpc"), *f["cpc"]) \
                or not _in_range(r.get("words"), *f["words"]):
            continue
        if f["comp"] and r.get("competition") not in f["comp"]:
            continue
        if f["intent"] and r.get("intent") not in f["intent"]:
            continue
        if inc and not (all if f["inc_all"] else any)(w in k for w in inc):
            continue
        if exc and any(w in k for w in exc):
            continue
        if (f["exc_tracked"] and r.get("tracked")) or (f["exc_brand"] and r.get("brand")) \
                or (f["exc_rival"] and r.get("rival")):
            continue
        pos, ranked = r.get("gsc_pos"), bool(r.get("gsc_impr"))
        site = f["site"]
        if (site == "none" and ranked) or (site == "has" and not ranked) \
                or (site == "top10" and not (ranked and pos and pos <= 10)) \
                or (site == "11_30" and not (ranked and pos and 10 < pos <= 30)) \
                or (site == "gt30" and not (ranked and pos and pos > 30)):
            continue
        t = f["trend"]
        if (t in ("up", "down") and r.get("trend") != t) or (t == "soon" and not r.get("soon")):
            continue
        if f["question"] and not r.get("question"):
            continue
        out.append(r)
    return out


def _seeds(seed: str) -> list[list[str]]:
    return [[K.fold(w) for w in x.split() if K.fold(w)] for x in (seed or "").replace(",", "\n").splitlines()
            if x.strip()]


def word_set(keyword: str) -> set[str]:
    """Các từ (bỏ dấu) của một từ khóa."""
    return {w for w in (K.fold(x) for x in keyword.lower().split()) if w}


def match_rows(rows: list[dict], seed: str, kind: str) -> list[dict]:
    """Kiểu khớp với từ khóa gốc (như Semrush): "broad" = chứa đủ các từ của một từ khóa gốc, thứ tự bất kỳ;
    "phrase" = chứa đúng cụm từ khóa gốc liền nhau."""
    seeds = _seeds(seed)
    if not seeds or kind not in ("broad", "phrase"):
        return rows
    out = []
    for r in rows:
        words = [w for w in (K.fold(x) for x in r["keyword"].lower().split()) if w]
        line = " " + " ".join(words) + " "
        if any((set(sd) <= set(words)) if kind == "broad" else (f" {' '.join(sd)} " in line) for sd in seeds):
            out.append(r)
    return out


WORD_STOP = {"la", "gi", "cua", "va", "cho", "co", "khong", "o", "dau", "bao", "nhieu", "nao", "nhu", "the", "voi",
             "mot", "cac", "nhung", "tai", "o", "de", "thi", "va", "hay"}


def word_groups(rows: list[dict], seed: str = "", by: str = "count") -> list[dict]:
    """Cột trái kiểu Semrush: các từ hay gặp trong danh sách (bỏ từ của từ khóa gốc và từ phụ), mỗi từ: số từ khóa
    chứa nó và tổng volume. by = "count" | "volume"."""
    skip = {w for sd in _seeds(seed) for w in sd} | WORD_STOP
    acc: dict[str, list] = {}
    shown: dict[str, str] = {}
    for r in rows:
        for x in r["keyword"].lower().split():
            w = K.fold(x)
            if not w or w in skip or len(w) < 2:
                continue
            shown.setdefault(w, x)
        for w in word_set(r["keyword"]) - skip:
            if len(w) < 2:
                continue
            a = acc.setdefault(w, [0, 0])
            a[0] += 1
            a[1] += r.get("volume") or 0
    out = [{"word": w, "label": shown.get(w, w), "count": c, "volume": v} for w, (c, v) in acc.items() if c >= 2]
    out.sort(key=lambda g: (-(g["count"] if by == "count" else g["volume"]), g["word"]))
    return out


def active_filters(f: dict) -> int:
    """Số bộ lọc đang bật (để hiện trên nút Xóa bộ lọc)."""
    f = {**FILTER_DEFAULT, **(f or {})}
    return sum(1 for k, v in f.items() if k != "inc_all" and v != FILTER_DEFAULT[k])


# ---- Tra URL: từ khóa một trang đang có hạng ----

def url_key(u: str | None) -> str:
    """So khớp URL bỏ qua http/https, www, dấu / cuối, #mục và mọi tham số (?srsltid=…, ?màu=…)."""
    from . import urls as U
    if not u:
        return ""
    n = urlsplit(U.normalize(u))
    return (n.netloc.removeprefix("www.") + (n.path.rstrip("/") or "/")).lower()


def _same_site(u: str, site: str) -> bool:
    host = lambda x: urlsplit(x if "//" in x else "https://" + x).netloc.lower().removeprefix("www.")  # noqa: E731
    site_host = site.split(":", 1)[1] if site.startswith("sc-domain:") else host(site)
    h = host(u)
    return h == site_host or h.endswith("." + site_host)


def url_keywords(con, cfg, url: str, ads=None, end: date | None = None, days: int = 28) -> list[dict]:
    """Từ khóa một URL đang có hạng.
    - URL của site: mọi từ khóa Search Console ghi nhận cho trang đó trong `days` ngày (click, hiển thị, vị trí).
    - URL khác (đối thủ): từ khóa trong các bộ theo dõi hạng mà URL đó có mặt ở lần check gần nhất (vị trí, ngày).
    Kèm volume / cạnh tranh / giá thầu / 12 tháng: lấy từ số đã lưu, thiếu thì hỏi Google Ads (miễn phí) khi có."""
    from . import google_ads as GA
    from . import rank_overview as RO
    site = cfg.site_url
    end = end or K.latest_date(con, site)
    key = url_key(url)
    found: dict[str, dict] = {}
    if _same_site(url, site):
        ids = [i for i, u in con.execute("SELECT id, url FROM pages WHERE site = ?", (site,)) if url_key(u) == key]
        if ids:
            s_ = (end - timedelta(days=days - 1)).isoformat()
            for text, c, i, pw in con.execute(
                    f"""SELECT q.text, SUM(d.clicks), SUM(d.impressions), SUM(d.position * d.impressions)
                        FROM gsc_query_daily d JOIN queries q ON q.id = d.query_id
                        WHERE d.page_id IN ({','.join('?' * len(ids))}) AND d.date BETWEEN ? AND ?
                        GROUP BY d.query_id""", (*ids, s_, end.isoformat())):
                found[text] = {"url_clicks": c or 0, "url_impr": i or 0,
                               "url_pos": round(pw / i, 1) if i else None, "source": "gsc"}
    else:
        kws = RO.active_keywords(con, site, end)
        by_id = {k["id"]: k for k in kws}
        for kid, (organic, _seen, _before) in RO._latest_serps(con, kws).items():
            hit = next((x for x in sorted(organic, key=lambda x: x["rank"]) if url_key(x.get("url")) == key), None)
            if hit:
                found[by_id[kid]["keyword"]] = {"url_clicks": None, "url_impr": None, "url_pos": hit["rank"],
                                                "source": "serp", "checked": by_id[kid]["date"]}
    if not found:
        return []
    ensure_tables(con)
    known = {f: (t, v, comp, lo, hi, mo) for f, t, v, comp, lo, hi, mo in con.execute(
        "SELECT fold, text, volume, competition, low_bid, high_bid, monthly FROM kw_cpc")}
    missing = [t for t in found if ckey(t) not in known]
    if missing and ads:
        for i in range(0, len(missing), CPC_BATCH):
            chunk = missing[i:i + CPC_BATCH]
            got = GA.metrics(*ads, chunk, cfg.rank.location_code, cfg.rank.language_code)
            seen = {ckey(r["keyword"]) for r in got}
            save_cpc(con, got + [{"keyword": t} for t in chunk if ckey(t) not in seen])
        known = {f: (t, v, comp, lo, hi, mo) for f, t, v, comp, lo, hi, mo in con.execute(
            "SELECT fold, text, volume, competition, low_bid, high_bid, monthly FROM kw_cpc")}
    rows = []
    for text, u in found.items():
        k = known.get(ckey(text))
        rows.append({"keyword": text, "volume": k[1] if k else None, "competition": k[2] if k else None,
                     "competition_index": None, "low_bid": k[3] if k else None, "high_bid": k[4] if k else None,
                     "monthly": [tuple(x) for x in json.loads(k[5] or "[]")] if k else [], **u})
    rows.sort(key=lambda r: (-(r["url_clicks"] or 0), -(r["url_impr"] or 0), r["url_pos"] or 999))
    return rows


# ---- Research ----

def parse_seed(mode: str, text: str) -> dict:
    """Chữ người dùng nhập → tham số keyword_ideas."""
    text = (text or "").strip()
    if mode == "site":
        host = text.replace("https://", "").replace("http://", "").split("/")[0].removeprefix("www.")
        if "." not in host:
            raise ValueError("Nhập tên miền, ví dụ doithu.vn")
        return {"site": host}
    if mode == "list":
        mode = "keywords"  # cùng cách đọc: mỗi dòng / dấu phẩy một từ khóa, tối đa 100
    if mode == "rank_url":
        u = text.split()[0] if text else ""
        if "." not in u:
            raise ValueError("Dán địa chỉ trang, ví dụ https://site.vn/trang/")
        return {"rank_url": u if u.startswith("http") else "https://" + u}
    if mode == "url":
        if not text.startswith("http"):
            raise ValueError("Nhập đầy đủ địa chỉ trang, bắt đầu bằng https://")
        return {"url": text.split()[0]}
    kws = split_keywords(text)
    if not kws:
        raise ValueError("Nhập ít nhất một từ khóa")
    if len(kws) > MAX_SEEDS:
        raise ValueError(f"Tối đa {MAX_SEEDS} từ khóa mỗi lần (đang có {len(kws)})")
    return {"keywords": kws}


MAX_SEEDS = 100  # từ khóa gốc mỗi lần tìm (Google nhận 20 / lần gọi: tool tự chia)
SEED_BATCH = 20


def split_keywords(text: str) -> list[str]:
    """Danh sách dán từ sheet / Excel / văn bản: mỗi dòng, dấu phẩy, chấm phẩy hoặc Tab là một từ khóa; bỏ trùng
    (không phân biệt hoa thường), giữ thứ tự."""
    import re
    seen, out = set(), []
    for k in re.split(r"[\n\r,;\t]+", text or ""):
        k = " ".join(k.split())
        if k and ckey(k) not in seen:
            seen.add(ckey(k))
            out.append(k)
    return out


def research(con, cfg, mode: str, seed: str, user: str, ads=None, limit: int = LIMIT) -> dict:
    """Gọi Keyword Planner, đối chiếu, lưu thành một lần research. Trả bản ghi (như get())."""
    from . import google_ads as GA
    if mode not in MODES:
        raise ValueError("Chế độ không hợp lệ")
    params = parse_seed(mode, seed)
    if mode == "list":
        # Danh sách nhập vào: chỉ lấy số của đúng các từ khóa đó (giữ thứ tự), không thêm ý tưởng
        ads = ads or client(cfg)
        kws = params["keywords"]
        got = GA.metrics(*ads, kws, cfg.rank.location_code, cfg.rank.language_code)
        by = {ckey(r["keyword"]): r for r in got}
        empty = {"volume": None, "competition": None, "competition_index": None, "low_bid": None, "high_bid": None,
                 "monthly": []}
        rows = [{**(by.get(ckey(k)) or empty), "keyword": k} for k in kws]
        save_cpc(con, got + [{"keyword": k} for k in kws if ckey(k) not in by])
    elif mode == "rank_url":
        try:
            ads = ads or client(cfg)
        except RuntimeError:  # chưa cấu hình Google Ads: vẫn tra được, chỉ thiếu volume / giá thầu chưa lưu
            ads = None
        rows = url_keywords(con, cfg, params["rank_url"], ads)
    else:
        ads = ads or client(cfg)
        if mode == "keywords" and len(params["keywords"]) > SEED_BATCH:
            # Google nhận tối đa 20 từ khóa gốc mỗi lần: chia nhóm, gộp ý tưởng (bỏ trùng), nhiều volume trước
            merged: dict[str, dict] = {}
            seeds = params["keywords"]
            for i in range(0, len(seeds), SEED_BATCH):
                for r in GA.keyword_ideas(*ads, cfg.rank.location_code, cfg.rank.language_code, limit=limit,
                                          keywords=seeds[i:i + SEED_BATCH]):
                    merged.setdefault(ckey(r["keyword"]), r)
            rows = sorted(merged.values(), key=lambda r: -(r["volume"] or 0))[:limit * 2]
        else:
            rows = GA.keyword_ideas(*ads, cfg.rank.location_code, cfg.rank.language_code, limit=limit, **params)
        save_cpc(con, rows)
    if ads:
        currency(con, cfg, ads)
    ensure_tables(con)
    with con:
        rid = con.execute("INSERT INTO kw_research (created_at, created_by, mode, seed, n, results) VALUES "
                          "(?, ?, ?, ?, ?, ?)", (_now(), user, mode, seed.strip()[:10000], len(rows),
                                                 json.dumps(rows, ensure_ascii=False))).lastrowid
        con.execute("DELETE FROM kw_research WHERE id NOT IN (SELECT id FROM kw_research ORDER BY id DESC LIMIT ?)",
                    (HISTORY,))
    return get(con, cfg, rid)


def find_recent(con, mode: str, seed: str, hours: int = 24) -> int | None:
    """Lần research cùng cách tìm và cùng nội dung (không phân biệt hoa thường / khoảng trắng) trong `hours` giờ."""
    ensure_tables(con)
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    key = " ".join((seed or "").lower().split())
    for rid, s in con.execute("SELECT id, seed FROM kw_research WHERE mode = ? AND created_at >= ? ORDER BY id DESC",
                              (mode, since)):
        if " ".join(s.lower().split()) == key:
            return rid
    return None


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
    """Lấy giá thầu (kèm volume, 12 tháng) cho từ khóa đang theo dõi hạng và các từ khóa (không phải thương hiệu) mang
    nhiều click SEO nhất 90 ngày qua, khi chưa có hoặc đã cũ hơn 30 ngày. Trả số từ khóa đã hỏi."""
    from . import google_ads as GA
    ensure_tables(con)
    site = cfg.site_url
    end = end or K.latest_date(con, site)
    brand = cfg.keywords.brand_terms
    fresh_since = (datetime.now(timezone.utc) - timedelta(days=CPC_MAX_AGE)).isoformat()
    fresh = {f for f, in con.execute("SELECT fold FROM kw_cpc WHERE fetched_at >= ?", (fresh_since,))} \
        if not force else set()
    want, seen = [], set()
    try:  # từ khóa đang theo dõi hạng trước (thị phần, dự báo cần volume + giá thầu của chúng)
        tracked = [t for t, in con.execute("SELECT DISTINCT keyword FROM rank_keywords WHERE site = ? AND "
                                            "removed_at IS NULL", (site,))]
    except sqlite3.Error:
        tracked = []
    for text in tracked:
        f = ckey(text)
        if f and f not in seen:
            seen.add(f)
            if f not in fresh:
                want.append(text)
    top += len(seen)
    for text, _ in _queries(con, site, end - timedelta(days=89), end):
        f = ckey(text)
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
        got = {ckey(r["keyword"]) for r in rows}
        # từ khóa Google không có số: lưu dòng trống để tháng này không hỏi lại
        rows += [{"keyword": t} for t in chunk if ckey(t) not in got]
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
        f = ckey(text)
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


# ---- Nhóm chủ đề ----
# Gom ý tưởng thành cụm, mỗi cụm một trang đích: (1) từ khóa site đã có hạng nhóm theo trang đang nhận nhiều hiển thị
# nhất (Google đã coi chúng cùng một trang); (2) từ khóa còn lại nhập vào cụm có từ khóa chính giống nhất (trùng từ
# ≥ 60%, bỏ các từ phụ như giá / mua / tốt / ở đâu), không giống cụm nào thì thành cụm mới. Không gọi API.

STOP = {"la", "gi", "cua", "va", "cho", "co", "khong", "nao", "o", "dau", "bao", "nhieu", "tot", "nhat", "gia", "mua",
        "loai", "cach", "cac", "nhung", "nen", "hay", "re", "dep", "tai", "hcm", "tphcm", "tp", "hn", "the", "mot",
        "nhu", "voi", "duoc", "ban", "online", "chinh", "hang", "2024", "2025", "2026", "2027"}
SIMILAR = 0.6


def _syllables(text: str) -> frozenset[str]:
    words = {K.fold(w) for w in text.split()}
    core = {w for w in words if w and w not in STOP}
    return frozenset(core or {w for w in words if w})


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def clusters(rows: list[dict], site: str = "") -> list[dict]:
    """Gom các dòng research (đã annotate) thành cụm chủ đề, nhiều volume trước. Mỗi cụm: name (từ khóa chính =
    nhiều volume nhất), rows, volume, cpc (bình quân theo volume), ranked (số từ khóa site đã có hạng), best (vị trí
    tốt nhất), page (trang đích hiện có hoặc None = cần trang mới), action."""
    groups: list[dict] = []
    by_page: dict[str, dict] = {}
    ordered = sorted(rows, key=lambda r: -(r.get("volume") or 0))
    for r in ordered:  # bước 1: theo trang đang lên
        if r.get("gsc_page"):
            g = by_page.get(r["gsc_page"])
            if not g:
                g = by_page[r["gsc_page"]] = {"page": r["gsc_page"], "rows": [], "sig": _syllables(r["keyword"])}
                groups.append(g)
            g["rows"].append(r)
    for r in ordered:  # bước 2: phần còn lại theo độ giống từ khóa chính của cụm
        if r.get("gsc_page"):
            continue
        sig = _syllables(r["keyword"])
        best, score = None, 0.0
        for g in groups:
            s = _jaccard(sig, g["sig"])
            if s > score:
                best, score = g, s
        if best is not None and score >= SIMILAR:
            best["rows"].append(r)
        else:
            groups.append({"page": None, "rows": [r], "sig": sig})
    out = []
    for g in groups:
        rs = sorted(g["rows"], key=lambda r: -(r.get("volume") or 0))
        vol = sum(r.get("volume") or 0 for r in rs)
        priced = [(r["cpc"], r.get("volume") or 0) for r in rs if r.get("cpc")]
        wsum = sum(v for _, v in priced)
        ranked = [r for r in rs if r.get("gsc_impr")]
        best = min((r["gsc_pos"] for r in ranked if r.get("gsc_pos")), default=None)
        missing = len(rs) - len(ranked)
        if not g["page"]:
            action = "Cần trang mới"
        elif missing:
            action = f"Bổ sung {missing} từ khóa vào trang"
        elif best and best > 10:
            action = "Tối ưu trang (chưa vào top 10)"
        else:
            action = "Đang có trang tốt"
        out.append({"name": rs[0]["keyword"], "rows": rs, "volume": vol,
                    "cpc": round(sum(c * v for c, v in priced) / wsum, 2) if wsum else None,
                    "ranked": len(ranked), "best": best, "page": g["page"],
                    "path": (g["page"] or "").replace(site.rstrip("/"), "") or ("/" if g["page"] else None),
                    "action": action, "new": not g["page"]})
    out.sort(key=lambda g: -g["volume"])
    return out
