"""Audit kỹ thuật on-page (miễn phí): tool tự mở các trang quan trọng của website (nhiều click / hiển thị nhất 90 ngày
qua, không tính URL biến thể có tham số) rồi kiểm tra mã trả về, chuyển hướng, noindex, canonical, tiêu đề, mô tả, H1,
ảnh thiếu alt, nội dung mỏng, tốc độ phản hồi; kèm kiểm tra từ dữ liệu Search Console (tiêu đề không chứa từ khóa
chính, CTR thấp so với vị trí). Mỗi tuần quét một lần (lịch hằng ngày), hoặc bấm Quét ngay."""
import gzip
import json
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import keywords as K
from .crawl import HEADERS

REFRESH_DAYS = 7
MAX_PAGES = 300  # trang quan trọng nhất; site bán hàng có hàng nghìn sản phẩm không cần quét hết mỗi tuần
DELAY = 0.4  # nghỉ giữa hai lần mở trang: không làm nặng server của website
TIMEOUT = 25
SLOW_MS = 3000
TITLE_MIN, TITLE_MAX = 20, 65
DESC_MIN, DESC_MAX = 70, 160
THIN_WORDS = 300
LEVELS = {"high": ("Cần sửa", "red"), "medium": ("Nên sửa", "amber"), "info": ("Tham khảo", "blue")}
_ORDER = {"high": 0, "medium": 1, "info": 2}

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_pages (
    url_id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status INTEGER,
    final_url TEXT,
    ms INTEGER,
    data TEXT NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS audit_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    pages INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL
);
"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- Đọc HTML ----

class _Page(HTMLParser):
    """Gom những gì audit cần từ một trang, không cần thư viện ngoài."""
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.title, self.desc, self.robots, self.canonical = None, None, "", None
        self.h1: list[str] = []
        self.imgs = self.noalt = 0
        self.links_int = self.links_ext = 0
        self.words = 0
        self.schema: list[str] = []
        self._in, self._skip, self._buf = None, 0, []
        self._ld = False

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in self.SKIP:
            self._skip += 1
            if tag == "script" and "ld+json" in a.get("type", ""):
                self._ld, self._buf = True, []
            return
        if tag == "title" and self.title is None:
            self._in, self._buf = "title", []
        elif tag == "h1":
            self._in, self._buf = "h1", []
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name == "description" and self.desc is None:
                self.desc = a.get("content", "").strip()
            elif name in ("robots", "googlebot"):
                self.robots += " " + a.get("content", "").lower()
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split() and self.canonical is None:
            self.canonical = urljoin(self.base, a.get("href", "").strip())
        elif tag == "img":
            self.imgs += 1
            if not a.get("alt", "").strip():
                self.noalt += 1
        elif tag == "a" and a.get("href"):
            href = urljoin(self.base, a["href"])
            if href.startswith("http"):
                same = urlsplit(href).netloc.removeprefix("www.") == urlsplit(self.base).netloc.removeprefix("www.")
                if same:
                    self.links_int += 1
                else:
                    self.links_ext += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
            if tag == "script" and self._ld:
                self._ld = False
                self.schema += _ld_types("".join(self._buf))
            return
        if tag == self._in:
            text = " ".join("".join(self._buf).split())
            if self._in == "title":
                self.title = text
            else:
                self.h1.append(text)
            self._in = None

    def handle_data(self, data):
        if self._ld:
            self._buf.append(data)
            return
        if self._skip:
            return
        if self._in:
            self._buf.append(data)
        self.words += len(data.split())


def _ld_types(text: str) -> list[str]:
    out = []

    def walk(x):
        if isinstance(x, dict):
            t = x.get("@type")
            out.extend(t if isinstance(t, list) else [t] if t else [])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    try:
        walk(json.loads(text))
    except ValueError:
        pass
    return [str(t) for t in out]


def parse(html: str, url: str) -> dict:
    p = _Page(url)
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 — HTML hỏng: lấy được tới đâu dùng tới đó
        pass
    return {"title": p.title, "desc": p.desc, "robots": p.robots.strip(), "canonical": p.canonical,
            "h1": p.h1[:5], "h1_count": len(p.h1), "imgs": p.imgs, "noalt": p.noalt, "words": p.words,
            "links_int": p.links_int, "links_ext": p.links_ext, "schema": sorted(set(p.schema))[:10]}


# ---- Mở trang ----

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = build_opener(_NoRedirect)


def fetch(url: str, timeout: int = TIMEOUT) -> dict:
    """Mở một trang, không tự theo chuyển hướng (để biết trang có chuyển hướng không). Trả status, final_url (đích
    chuyển hướng), ms, html, x_robots, error."""
    t = time.monotonic()
    try:
        resp = _opener.open(Request(url, headers=HEADERS), timeout=timeout)
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        ctype = resp.headers.get("Content-Type", "")
        return {"status": resp.status, "final_url": None, "ms": int((time.monotonic() - t) * 1000),
                "html": body.decode("utf-8", "ignore") if "html" in ctype or not ctype else "",
                "x_robots": (resp.headers.get("X-Robots-Tag") or "").lower(), "error": None}
    except HTTPError as e:
        loc = e.headers.get("Location") if e.headers else None
        return {"status": e.code, "final_url": urljoin(url, loc) if loc else None,
                "ms": int((time.monotonic() - t) * 1000), "html": "", "x_robots": "", "error": None}
    except (URLError, OSError, HTTPException) as e:
        return {"status": None, "final_url": None, "ms": None, "html": "", "x_robots": "", "error": str(e)[:200]}


# ---- Chọn trang và quét ----

def pick_pages(con: sqlite3.Connection, site: str, end: date, limit: int = MAX_PAGES) -> list[tuple[int, str]]:
    """URL nhiều click (rồi nhiều hiển thị) nhất 90 ngày qua, bỏ URL biến thể có tham số và URL cũ/kỹ thuật."""
    from . import urls as U
    since = (end - timedelta(days=89)).isoformat()
    rows = con.execute(
        """SELECT u.id, u.url FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id
           JOIN urls u ON u.id = pu.url_id AND u.site = ?
           WHERE d.date BETWEEN ? AND ? AND u.url NOT LIKE '%?%' AND COALESCE(u.type, '') != ?
           GROUP BY u.id ORDER BY SUM(d.clicks) DESC, SUM(d.impressions) DESC LIMIT ?""",
        (site, since, end.isoformat(), U.LEGACY, limit)).fetchall()
    return [(i, u) for i, u in rows]


def last_run(con) -> dict | None:
    ensure_tables(con)
    r = con.execute("SELECT id, started_at, finished_at, pages, errors, created_by FROM audit_runs "
                    "ORDER BY id DESC LIMIT 1").fetchone()
    return dict(zip(("id", "started_at", "finished_at", "pages", "errors", "by"), r)) if r else None


def run(con: sqlite3.Connection, site: str, end: date, user: str = "lịch tự động", limit: int = MAX_PAGES,
        fetcher=fetch, sleep=time.sleep, log=print, progress=None) -> dict:
    """Quét lại các trang quan trọng. Kết quả cũ của trang không còn trong danh sách được xóa."""
    ensure_tables(con)
    pages = pick_pages(con, site, end, limit)
    with con:
        run_id = con.execute("INSERT INTO audit_runs (started_at, created_by) VALUES (?, ?)",
                             (_now(), user)).lastrowid
    errors = 0
    for n, (uid, url) in enumerate(pages, 1):
        r = fetcher(url)
        data = parse(r["html"], url) if r["html"] else {}
        data["x_robots"] = r.get("x_robots", "")
        if r["error"]:
            errors += 1
        with con:
            con.execute("INSERT OR REPLACE INTO audit_pages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (uid, url, _now(), r["status"], r["final_url"], r["ms"], json.dumps(data, ensure_ascii=False),
                         r["error"]))
        if progress:
            progress(n, len(pages))
        if n % 25 == 0:
            log(f"Audit: {n}/{len(pages)} trang")
        if n < len(pages):
            sleep(DELAY)
    keep = [uid for uid, _ in pages]
    with con:
        if keep:
            con.execute(f"DELETE FROM audit_pages WHERE url_id NOT IN ({','.join('?' * len(keep))})", keep)
        con.execute("UPDATE audit_runs SET finished_at = ?, pages = ?, errors = ? WHERE id = ?",
                    (_now(), len(pages), errors, run_id))
    log(f"Audit: xong {len(pages)} trang, {errors} trang không mở được")
    return {"pages": len(pages), "errors": errors}


def refresh(con, cfg, today: date | None = None, force: bool = False, log=print) -> dict | None:
    """Lịch hằng ngày: quét khi lần gần nhất đã cũ hơn 7 ngày (force: ngay)."""
    ensure_tables(con)
    today = today or date.today()
    last = last_run(con)
    if not force and last and last["finished_at"] and \
            datetime.fromisoformat(last["finished_at"]).date() > today - timedelta(days=REFRESH_DAYS):
        return None
    return run(con, cfg.site_url, K.latest_date(con, cfg.site_url), log=log)


# ---- Kiểm tra ----

def _query_rows(con, url_ids: list[int], end: date) -> dict[int, list[tuple[str, int, int, float]]]:
    """Từ khóa 28 ngày của từng URL: (từ khóa, click, hiển thị, vị trí)."""
    s = (end - timedelta(days=27)).isoformat()
    rows: dict[int, list[tuple]] = {}
    for chunk in (url_ids[i:i + 900] for i in range(0, len(url_ids), 900)):
        for uid, qid, c, i, pw in con.execute(
                f"""SELECT pu.url_id, d.query_id, SUM(d.clicks), SUM(d.impressions), SUM(d.position * d.impressions)
                    FROM gsc_query_daily d JOIN page_url pu ON pu.page_id = d.page_id
                    WHERE pu.url_id IN ({','.join('?' * len(chunk))}) AND d.date BETWEEN ? AND ?
                    GROUP BY pu.url_id, d.query_id""", (*chunk, s, end.isoformat())):
            rows.setdefault(uid, []).append((qid, c or 0, i or 0, pw / i if i else 0.0))
    texts = K._texts(con, "queries", "text", {r[0] for rs in rows.values() for r in rs})
    return {u: [(texts[q], c, i, p) for q, c, i, p in rs] for u, rs in rows.items()}


def _words(text: str) -> set[str]:
    return {K.fold(w) for w in re.split(r"[\s\-–|:,.!?/]+", text) if K.fold(w)}


def title_covers(query: str, title: str) -> bool:
    """Tiêu đề có ít nhất một nửa số từ của từ khóa (không phân biệt dấu): đủ để Google hiểu trang nói về gì."""
    q = _words(query)
    return not q or len(q & _words(title)) / len(q) >= 0.5


LOW_CTR_IMPR = 300  # từ khóa cần từng này lượt hiển thị / 28 ngày thì CTR mới đáng tin


EXPECTED_CTR = {1: 0.25, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05}  # CTR thận trọng theo vị trí (trung bình ngành)


def _norm(u: str | None) -> str:
    if not u:
        return ""
    s = urlsplit(u)
    return (s.netloc.removeprefix("www.") + (s.path.rstrip("/") or "/")).lower()


CHECKS = {  # mã: (mức, tên, cách sửa)
    "error": ("high", "Trang không mở được", "Kiểm tra server / tường lửa: Google cũng có thể không mở được."),
    "4xx": ("high", "Trang lỗi 4xx (không tồn tại)", "Trang vẫn có lượt hiển thị trên Google nhưng đã hỏng: khôi "
            "phục, hoặc chuyển hướng 301 về trang thay thế gần nhất."),
    "5xx": ("high", "Trang lỗi máy chủ 5xx", "Báo đội kỹ thuật kiểm tra lỗi máy chủ của trang."),
    "redirect": ("medium", "Trang có traffic nhưng đang chuyển hướng", "Sửa link nội bộ và sitemap trỏ thẳng tới "
                 "trang đích để không mất sức mạnh qua chuyển hướng."),
    "noindex": ("high", "Bị chặn index (noindex)", "Trang đang có traffic mà gắn noindex: bỏ noindex nếu muốn giữ "
                "trang trên Google."),
    "canonical": ("high", "Canonical trỏ sang trang khác", "Google có thể bỏ trang này để index trang được trỏ "
                  "tới. Nếu trang này là trang chính, sửa canonical trỏ về chính nó."),
    "no_title": ("high", "Thiếu thẻ tiêu đề (title)", "Thêm tiêu đề có từ khóa chính, 20–65 ký tự."),
    "dup_title": ("medium", "Tiêu đề trùng với trang khác", "Mỗi trang một tiêu đề riêng, nêu rõ nội dung khác "
                  "nhau, tránh tranh nhau từ khóa."),
    "long_title": ("info", "Tiêu đề dài quá 65 ký tự", "Google cắt bớt tiêu đề dài: đưa từ khóa chính lên đầu."),
    "short_title": ("medium", "Tiêu đề quá ngắn (dưới 20 ký tự)", "Viết tiêu đề đầy đủ hơn: từ khóa chính + lợi "
                    "ích / thương hiệu."),
    "no_desc": ("medium", "Thiếu mô tả (meta description)", "Thêm mô tả 70–160 ký tự có từ khóa và lời mời bấm."),
    "dup_desc": ("info", "Mô tả trùng với trang khác", "Viết mô tả riêng cho từng trang."),
    "bad_desc": ("info", "Mô tả quá ngắn hoặc quá dài", "Giữ mô tả trong khoảng 70–160 ký tự."),
    "no_h1": ("medium", "Thiếu thẻ H1", "Thêm một H1 nêu chủ đề chính của trang."),
    "multi_h1": ("info", "Nhiều thẻ H1", "Giữ một H1, các tiêu đề phụ dùng H2/H3."),
    "kw_title": ("medium", "Tiêu đề không chứa từ khóa chính", "Từ khóa mang nhiều click nhất cho trang (theo "
                 "Search Console) chưa có trong tiêu đề: thêm vào, càng gần đầu càng tốt."),
    "low_ctr": ("medium", "CTR thấp so với vị trí", "Trang ở top 5 mà ít người bấm: viết lại tiêu đề / mô tả hấp "
                "dẫn hơn, kiểm tra trang kết quả có AI Overview hay đối thủ nổi bật không."),
    "thin": ("info", "Nội dung mỏng (dưới 300 chữ)", "Bài viết ít chữ khó lên top: bổ sung nội dung trả lời đầy "
             "đủ câu hỏi của người tìm."),
    "noalt": ("info", "Ảnh thiếu mô tả (alt)", "Thêm alt mô tả ảnh: giúp lên Google Hình ảnh và người dùng trình "
              "đọc màn hình."),
    "slow": ("info", "Máy chủ phản hồi chậm (trên 3 giây)", "Xem lại cache / hosting; chi tiết tốc độ ở trang Tốc "
             "độ trang."),
}


_cache: dict = {}  # (file dữ liệu, lần quét, ngày GSC) -> kết quả: chuông thông báo không tính lại liên tục
running: dict = {}  # file dữ liệu -> {"n", "total", "by"} khi đang quét (một lần quét mỗi dự án)


def cached_findings(con, cfg) -> dict:
    last = last_run(con)
    if not last:
        return {"checks": [], "pages": 0, "healthy": 0, "run": None}
    end = K.latest_date(con, cfg.site_url)
    key = (str(cfg.db_path), last["id"] if last else None, last["finished_at"] if last else None, end)
    if key not in _cache:
        _cache.clear()
        _cache[key] = findings(con, cfg, end)
    return _cache[key]


def findings(con: sqlite3.Connection, cfg, end: date | None = None) -> dict:
    """Kết quả audit lần quét gần nhất: {"checks": [{code, level, name, fix, pages: [...]}], "pages": n, "run": …}.
    Mỗi trang trong check có url, url_id, detail (giá trị cụ thể để sửa)."""
    from . import urls as U
    ensure_tables(con)
    site = cfg.site_url
    end = end or K.latest_date(con, site)
    rows = con.execute("SELECT a.url_id, a.url, a.status, a.final_url, a.ms, a.data, a.error, u.type "
                       "FROM audit_pages a LEFT JOIN urls u ON u.id = a.url_id").fetchall()
    found: dict[str, list[dict]] = {k: [] for k in CHECKS}

    def add(code, uid, url, detail=""):
        found[code].append({"url_id": uid, "url": url, "detail": detail})

    ok = []
    for uid, url, status, final, ms, data, err, type_ in rows:
        d = json.loads(data or "{}")
        if err or status is None:
            add("error", uid, url, err or "")
            continue
        if 400 <= status < 500:
            add("4xx", uid, url, f"HTTP {status}")
            continue
        if status >= 500:
            add("5xx", uid, url, f"HTTP {status}")
            continue
        if 300 <= status < 400:
            add("redirect", uid, url, f"HTTP {status} → {final or '?'}")
            continue
        robots = f"{d.get('robots', '')} {d.get('x_robots', '')}"
        if "noindex" in robots:
            add("noindex", uid, url, robots.strip())
        can = d.get("canonical")
        if can and _norm(can) != _norm(url):
            add("canonical", uid, url, can)
        if ms and ms > SLOW_MS:
            add("slow", uid, url, f"{ms / 1000:.1f} giây".replace(".", ","))
        if d.get("noalt"):
            add("noalt", uid, url, f"{d['noalt']}/{d['imgs']} ảnh")
        if type_ == U.BLOG and d.get("words", 0) < THIN_WORDS:
            add("thin", uid, url, f"khoảng {d.get('words', 0)} chữ")
        h1 = d.get("h1_count", 0)
        if h1 == 0:
            add("no_h1", uid, url)
        elif h1 > 1:
            add("multi_h1", uid, url, f"{h1} thẻ H1")
        title, desc = (d.get("title") or "").strip(), (d.get("desc") or "").strip()
        if not title:
            add("no_title", uid, url)
        elif len(title) > TITLE_MAX:
            add("long_title", uid, url, f"{len(title)} ký tự: {title}")
        elif len(title) < TITLE_MIN:
            add("short_title", uid, url, f"{len(title)} ký tự: {title}")
        if not desc:
            add("no_desc", uid, url)
        elif not DESC_MIN <= len(desc) <= DESC_MAX:
            add("bad_desc", uid, url, f"{len(desc)} ký tự")
        ok.append((uid, url, title, desc))

    for idx, code in ((2, "dup_title"), (3, "dup_desc")):
        groups: dict[str, list] = {}
        for r in ok:
            if r[idx]:
                groups.setdefault(r[idx].lower(), []).append(r)
        for text, rs in groups.items():
            if len(rs) > 1:
                for uid, url, *_ in rs:
                    add(code, uid, url, f"trùng với {len(rs) - 1} trang khác: {rs[0][idx]}")

    qrows = _query_rows(con, [r[0] for r in ok], end)
    brand = cfg.keywords.brand_terms
    for uid, url, title, _ in ok:
        qs = [q for q in qrows.get(uid, []) if not K.is_brand(q[0], brand)]
        if not qs:
            continue
        h = max(qs, key=lambda q: (q[1], q[2]))
        if title and h[1] >= 3 and not title_covers(h[0], title):
            add("kw_title", uid, url, f"từ khóa “{h[0]}” ({h[1]} click) · tiêu đề: {title}")
        worst = None
        for q, c, i, pos in qs:  # theo từng từ khóa: CTR cả trang bị các từ khóa dài, ít người bấm làm loãng
            if i >= LOW_CTR_IMPR and pos <= 5.5:
                exp = EXPECTED_CTR[max(1, min(5, round(pos)))]
                miss = i * exp - c
                if c / i < exp / 2 and (worst is None or miss > worst[0]):
                    worst = (miss, q, c, i, pos, exp)
        if worst:
            _, q, c, i, pos, exp = worst
            vn = lambda t: t.replace(".", ",")  # noqa: E731
            add("low_ctr", uid, url, f"từ khóa “{q}”: vị trí {vn(f'{pos:.1f}')}, CTR {vn(f'{c / i:.1%}')} "
                                     f"(thường ~{exp:.0%}), {f'{i:,}'.replace(',', '.')} hiển thị")

    checks = [{"code": k, "level": CHECKS[k][0], "name": CHECKS[k][1], "fix": CHECKS[k][2], "pages": v}
              for k, v in found.items() if v]
    checks.sort(key=lambda c: (_ORDER[c["level"]], -len(c["pages"])))
    bad = {p["url_id"] for c in checks if c["level"] == "high" for p in c["pages"]}
    return {"checks": checks, "pages": len(rows), "healthy": len(rows) - len(bad), "run": last_run(con)}
