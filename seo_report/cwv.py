"""Tốc độ & Core Web Vitals (miễn phí, cần Google API key ở Cài đặt tích hợp):

- CrUX History API: số đo của người dùng Chrome thật trên toàn website (origin), theo từng kỳ 28 ngày lùi dần mỗi
  tuần (khoảng 6 tháng), cho điện thoại và máy tính → `cwv_origin`.
- PageSpeed Insights API: chấm điểm Lighthouse (hiệu năng, SEO, khả năng truy cập, thực hành tốt) cho các trang
  quan trọng nhất (nhiều click GSC nhất + trang chủ), số đo người dùng thật của từng trang nếu Google có, và các việc
  nên sửa kèm thời gian tiết kiệm → `cwv_pages` (giữ lịch sử mỗi lần kiểm tra).
Ngưỡng tốt / cần cải thiện / kém theo Google (web.dev/vitals).
"""
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCHEMA = """
CREATE TABLE IF NOT EXISTS cwv_origin (
    form TEXT NOT NULL,            -- PHONE | DESKTOP
    period_end TEXT NOT NULL,      -- ngày cuối kỳ 28 ngày
    lcp REAL, inp REAL, cls REAL, fcp REAL, ttfb REAL,   -- p75 (ms; CLS không đơn vị)
    PRIMARY KEY (form, period_end)
);
CREATE TABLE IF NOT EXISTS cwv_pages (
    url TEXT NOT NULL,
    strategy TEXT NOT NULL,        -- mobile | desktop
    fetched_at TEXT NOT NULL,
    perf INTEGER, seo INTEGER, a11y INTEGER, bp INTEGER,  -- điểm 0–100
    lab TEXT NOT NULL DEFAULT '{}',    -- số đo phòng thí nghiệm: lcp, cls, tbt, fcp, si
    field TEXT NOT NULL DEFAULT '{}',  -- số người dùng thật của trang (nếu có): lcp, inp, cls, fcp, ttfb (p75)
    opps TEXT NOT NULL DEFAULT '[]',   -- việc nên sửa: [{title, ms}]
    error TEXT,
    PRIMARY KEY (url, strategy, fetched_at)
);
CREATE TABLE IF NOT EXISTS cwv_runs (
    run_at TEXT NOT NULL,
    pages INTEGER NOT NULL,
    errors INTEGER NOT NULL
);
"""

# (tốt nếu ≤, kém nếu >) theo Google; ms trừ CLS
THRESHOLDS = {"lcp": (2500, 4000), "inp": (200, 500), "cls": (0.1, 0.25), "fcp": (1800, 3000), "ttfb": (800, 1800)}
NAMES = {"lcp": "LCP · tải nội dung chính", "inp": "INP · phản hồi khi bấm", "cls": "CLS · ổn định bố cục",
         "fcp": "FCP · hiện nội dung đầu", "ttfb": "TTFB · máy chủ phản hồi"}
CORE = ("lcp", "inp", "cls")
CRUX_METRICS = {"largest_contentful_paint": "lcp", "interaction_to_next_paint": "inp",
                "cumulative_layout_shift": "cls", "first_contentful_paint": "fcp",
                "experimental_time_to_first_byte": "ttfb"}
PSI_FIELD = {"LARGEST_CONTENTFUL_PAINT_MS": "lcp", "INTERACTION_TO_NEXT_PAINT": "inp",
             "CUMULATIVE_LAYOUT_SHIFT_SCORE": "cls", "FIRST_CONTENTFUL_PAINT_MS": "fcp",
             "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "ttfb"}
TOP_PAGES = 15
REFRESH_DAYS = 7


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rating(metric: str, value) -> str:
    """good | ni (cần cải thiện) | poor | none."""
    if value is None:
        return "none"
    good, poor = THRESHOLDS[metric]
    return "good" if value <= good else "poor" if value > poor else "ni"


def fmt(metric: str, value) -> str:
    if value is None:
        return "–"
    if metric == "cls":
        return f"{value:.2f}".replace(".", ",")
    return f"{value / 1000:.1f} s".replace(".", ",") if value >= 1000 else f"{value:.0f} ms"


# ---------------------------------------------------------------- Google API

class Client:
    def __init__(self, api_key: str, timeout: int = 90):
        self.key, self.timeout = api_key, timeout

    def _json(self, req) -> dict:
        from urllib.error import HTTPError
        try:
            return json.loads(urlopen(req, timeout=self.timeout).read())
        except HTTPError as e:
            try:
                body = json.loads(e.read())
            except ValueError:
                body = {}
            err = body.get("error") or {}
            raise RuntimeError(f"{e.code} {err.get('status', '')}: {err.get('message', '')}".strip()) from e

    def crux_history(self, origin: str, form: str) -> dict:
        body = {"origin": origin, "formFactor": form, "metrics": list(CRUX_METRICS)}
        req = Request("https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord?key=" + self.key,
                      data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        return self._json(req)

    def psi(self, url: str, strategy: str = "mobile") -> dict:
        q = [("url", url), ("strategy", strategy), ("locale", "vi"), ("key", self.key)] + [
            ("category", c) for c in ("PERFORMANCE", "SEO", "ACCESSIBILITY", "BEST_PRACTICES")]
        return self._json(Request("https://www.googleapis.com/pagespeedonline/v5/runPagespeed?" + urlencode(q)))


def load_key(cfg) -> str:
    from . import integrations as I
    return I.load(cfg, "google_api").get("api_key", "")


# ---------------------------------------------------------------- đọc kết quả

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN → None


def parse_history(resp: dict) -> list[dict]:
    """CrUX History → [{"period_end", lcp, inp, cls, fcp, ttfb}] (cũ → mới)."""
    rec = resp.get("record") or {}
    periods = rec.get("collectionPeriods") or []
    out = [{"period_end": date(p["lastDate"]["year"], p["lastDate"]["month"], p["lastDate"]["day"]).isoformat()}
           for p in periods]
    for name, key in CRUX_METRICS.items():
        p75s = (((rec.get("metrics") or {}).get(name) or {}).get("percentilesTimeseries") or {}).get("p75s") or []
        for i, v in enumerate(p75s[:len(out)]):
            out[i][key] = _num(v)
    return out


def parse_psi(resp: dict) -> dict:
    """PageSpeed → {perf, seo, a11y, bp, lab, field, opps}."""
    lh = resp.get("lighthouseResult") or {}
    cats, audits = lh.get("categories") or {}, lh.get("audits") or {}

    def score(k):
        s = (cats.get(k) or {}).get("score")
        return round(s * 100) if s is not None else None

    def num(a):
        return _num((audits.get(a) or {}).get("numericValue"))
    lab = {"lcp": num("largest-contentful-paint"), "cls": num("cumulative-layout-shift"),
           "tbt": num("total-blocking-time"), "fcp": num("first-contentful-paint"), "si": num("speed-index")}
    field = {}
    le = resp.get("loadingExperience") or {}
    if le.get("origin_fallback"):  # trang chưa đủ lượt truy cập: Google trả số cả website, không phải của trang
        le = {}
    for k, v in (le.get("metrics") or {}).items():
        if k in PSI_FIELD:
            p = _num(v.get("percentile"))
            field[PSI_FIELD[k]] = p / 100 if p is not None and k == "CUMULATIVE_LAYOUT_SHIFT_SCORE" else p
    opps = []
    for a in audits.values():
        d = a.get("details") or {}
        if d.get("type") == "opportunity" and (a.get("score") is None or a["score"] < 0.9):
            ms = _num(d.get("overallSavingsMs")) or 0
            if ms >= 100:
                opps.append({"title": a.get("title", ""), "ms": round(ms)})
    opps.sort(key=lambda o: -o["ms"])
    return {"perf": score("performance"), "seo": score("seo"), "a11y": score("accessibility"),
            "bp": score("best-practices"), "lab": lab, "field": field, "opps": opps[:8]}


# ---------------------------------------------------------------- chọn trang, lấy số

def top_pages(con, site: str, today: date, n: int = TOP_PAGES) -> list[str]:
    """Trang chủ + các trang nhiều click GSC nhất 28 ngày gần nhất."""
    from .projects import domain
    home = site if site.startswith("http") else f"https://{domain(site)}/"
    rows = con.execute(
        "SELECT p.url, SUM(d.clicks) c FROM gsc_page_daily d JOIN pages p ON p.id = d.page_id WHERE p.site = ? "
        "AND d.date >= ? GROUP BY p.url ORDER BY c DESC LIMIT ?",
        (site, (today - timedelta(days=28)).isoformat(), n + 5)).fetchall()
    urls = [home] + [u for u, _ in rows if "#" not in u and u.rstrip("/") != home.rstrip("/")]
    return list(dict.fromkeys(urls))[:n]


def save_origin(con, form: str, points: list[dict]) -> int:
    with con:
        for p in points:
            con.execute("INSERT OR REPLACE INTO cwv_origin VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (form, p["period_end"], p.get("lcp"), p.get("inp"), p.get("cls"), p.get("fcp"), p.get("ttfb")))
    return len(points)


def save_page(con, url: str, strategy: str, res: dict | None, error: str = "", at: str | None = None) -> None:
    res = res or {}
    with con:
        con.execute("INSERT OR REPLACE INTO cwv_pages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (url, strategy, at or _now(), res.get("perf"), res.get("seo"), res.get("a11y"), res.get("bp"),
                     json.dumps(res.get("lab") or {}), json.dumps(res.get("field") or {}),
                     json.dumps(res.get("opps") or [], ensure_ascii=False), error or None))


def last_run(con) -> str | None:
    ensure_tables(con)
    return con.execute("SELECT MAX(run_at) FROM cwv_runs").fetchone()[0]


def refresh(con, cfg, today: date | None = None, force: bool = False, client=None, log=print,
            workers: int = 4) -> dict | None:
    """Lấy CrUX của website + PageSpeed các trang quan trọng (mỗi tuần một lần; force: ngay). None khi chưa đến hạn
    hoặc chưa có API key."""
    ensure_tables(con)
    today = today or date.today()
    last = last_run(con)
    if not force and last and datetime.fromisoformat(last).date() > today - timedelta(days=REFRESH_DAYS):
        return None
    if client is None:
        key = load_key(cfg)
        if not key:
            log("Chưa có Google API key (Cài đặt tích hợp): bỏ qua Core Web Vitals.")
            return None
        client = Client(key)
    from .projects import domain
    origin = f"https://{domain(cfg.site_url)}"
    got = 0
    for form in ("PHONE", "DESKTOP"):
        try:
            got += save_origin(con, form, parse_history(client.crux_history(origin, form)))
        except Exception as e:  # noqa: BLE001  (404: website chưa đủ lượt truy cập để Google có số)
            log(f"CrUX {form}: {e}")
    urls = top_pages(con, cfg.site_url, today)
    at = _now()
    from concurrent.futures import ThreadPoolExecutor

    def one(url):
        err = ""
        for _ in range(2):  # lỗi mạng / máy chủ tạm thời: thử lại một lần
            try:
                return url, parse_psi(client.psi(url, "mobile")), ""
            except Exception as e:  # noqa: BLE001
                err = str(e)[:300]
        return url, None, err
    errors = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:  # PageSpeed mất 10–30 giây mỗi trang: chạy song song
        for url, res, err in ex.map(one, urls):
            save_page(con, url, "mobile", res, err, at)
            errors += bool(err)
    with con:
        con.execute("INSERT INTO cwv_runs VALUES (?, ?, ?)", (at, len(urls), errors))
    log(f"Core Web Vitals: {got} kỳ CrUX, {len(urls)} trang PageSpeed ({errors} lỗi).")
    return {"origin_points": got, "pages": len(urls), "errors": errors}


# ---------------------------------------------------------------- đọc cho trang

def origin_series(con, form: str) -> list[dict]:
    ensure_tables(con)
    cols = ("period_end", "lcp", "inp", "cls", "fcp", "ttfb")
    return [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {', '.join(cols)} FROM cwv_origin WHERE form = ? ORDER BY period_end", (form,))]


def latest_pages(con, strategy: str = "mobile") -> list[dict]:
    """Lần kiểm tra mới nhất của từng trang, kèm điểm lần trước để so."""
    ensure_tables(con)
    rows = con.execute("SELECT url, fetched_at, perf, seo, a11y, bp, lab, field, opps, error FROM cwv_pages "
                       "WHERE strategy = ? ORDER BY url, fetched_at DESC", (strategy,)).fetchall()
    out: dict[str, dict] = {}
    for url, at, perf, seo, a11y, bp, lab, field, opps, err in rows:
        if url in out:
            if out[url].get("prev_perf") is None and perf is not None:
                out[url]["prev_perf"] = perf
            continue
        out[url] = {"url": url, "fetched_at": at, "perf": perf, "seo": seo, "a11y": a11y, "bp": bp,
                    "lab": json.loads(lab or "{}"), "field": json.loads(field or "{}"),
                    "opps": json.loads(opps or "[]"), "error": err, "prev_perf": None}
    return sorted(out.values(), key=lambda p: (p["perf"] is None, p["perf"] or 0))


def explain_error(err: str) -> str:
    """Lỗi PageSpeed → câu ngắn tiếng Việt."""
    e = (err or "").lower()
    if "ssl" in e or "eof" in e or "timed out" in e or "timeout" in e or "urlopen" in e:
        return "lỗi kết nối tạm thời, lần kiểm tra sau sẽ thử lại"
    if "500" in e or "internal" in e or "lighthouse" in e:
        return "Google không chạy được PageSpeed cho trang này lần này"
    if "403" in e or "api key" in e or "permission" in e:
        return "API key không có quyền PageSpeed (kiểm tra ở Cài đặt tích hợp)"
    if "429" in e or "quota" in e:
        return "vượt giới hạn lượt gọi của Google, thử lại sau"
    return err[:120]


def assess(values: dict) -> str:
    """Đạt Core Web Vitals khi cả LCP, INP, CLS (p75) đều tốt (như Google). good | poor | ni | none."""
    rs = [rating(m, values.get(m)) for m in CORE]
    if all(r == "none" for r in rs):
        return "none"
    if "poor" in rs:
        return "poor"
    return "good" if all(r == "good" for r in rs if r != "none") else "ni"
