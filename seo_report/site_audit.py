"""Audit kỹ thuật on-page (miễn phí): tool tự mở các trang của website (nhóm URL SEO, trang và sản phẩm nhiều click
nhất 90 ngày qua, mọi trang không phải sản phẩm trong sitemap; không tính URL biến thể có tham số: pick_pages) rồi kiểm tra mã trả về, chuyển hướng, noindex, canonical, tiêu đề, mô tả, H1,
ảnh thiếu alt, nội dung mỏng, tốc độ phản hồi; kèm kiểm tra từ dữ liệu Search Console (tiêu đề không chứa từ khóa
chính, CTR thấp so với vị trí). Mỗi tuần quét một lần (lịch hằng ngày), hoặc bấm Quét ngay."""
import json
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request

from . import keywords as K
from . import safe_fetch as SF
from .crawl import HEADERS

REFRESH_DAYS = 7
TOP_TRAFFIC = 300  # số trang nhiều traffic nhất luôn được quét (mọi loại)
TOP_PRODUCTS = 300  # thêm bấy nhiêu trang sản phẩm nhiều traffic nhất (mẫu đủ lớn để thấy lỗi giao diện sản phẩm)
MAX_PAGES = 1500   # trần số trang mỗi lần quét (nhóm URL SEO luôn quét đủ dù vượt trần)
# Trang không phải sản phẩm trong sitemap luôn được quét: mỗi bài / danh mục là nội dung riêng. Trang sản phẩm dùng
# chung một giao diện nên chỉ quét các trang nhiều traffic: lỗi giao diện thì trang nào cũng có, quét mẫu là đủ thấy.
DELAY = 0.4  # nghỉ giữa hai lần mở trang: không làm nặng server của website
BLOCK_STREAK = 25  # bị chặn bấy nhiêu trang liên tiếp thì dừng quét trang
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
CREATE TABLE IF NOT EXISTS audit_schema_hist (
    run_id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_ignore (
    code TEXT NOT NULL,
    url TEXT NOT NULL,
    at TEXT NOT NULL,
    by TEXT NOT NULL,
    PRIMARY KEY (code, url)
);
CREATE TABLE IF NOT EXISTS audit_findings_hist (
    run_id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_settings (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_fix_log (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    url TEXT NOT NULL,
    at TEXT NOT NULL,
    by TEXT NOT NULL,
    result TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
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
        self.products: list[dict] = []  # tóm tắt các nút Product trong JSON-LD
        self.micro_product = False      # có itemtype schema.org/Product (microdata)
        self.ld_blocks = 0              # số khối <script type="application/ld+json">
        self.ld_bad = 0                 # trong đó bao nhiêu khối sai cú pháp (Google bỏ qua cả khối)
        self.canonicals: list[str] = []  # mọi thẻ canonical (nhiều thẻ khác nhau: Google có thể bỏ qua cả hai)
        self.lang = None                # <html lang="…">
        self.viewport = False           # <meta name="viewport">
        self.nosnippet_blocks = 0       # số phần tử có data-nosnippet
        self.links: dict[str, str] = {}  # link nội bộ cần kiểm (site_checks.clean_link) → anchor đầu tiên
        self._a, self._a_buf = None, []
        self._in, self._skip, self._buf = None, 0, []
        self._ld = False

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if "schema.org/Product" in a.get("itemtype", ""):
            self.micro_product = True
        if "data-nosnippet" in a:
            self.nosnippet_blocks += 1
        if tag == "html" and self.lang is None:
            self.lang = a.get("lang", "").strip()
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
            elif name == "viewport":
                self.viewport = True
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split():
            href = urljoin(self.base, a.get("href", "").strip())
            self.canonicals.append(href)
            if self.canonical is None:
                self.canonical = href
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
            from .site_checks import clean_link
            u = clean_link(a["href"], self.base)
            if u and u not in self.links and len(self.links) < 400:
                self._a, self._a_buf = u, []
                self.links[u] = ""

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
            if tag == "script" and self._ld:
                self._ld = False
                text = "".join(self._buf)
                self.ld_blocks += 1
                try:
                    obj = json.loads(text)
                except ValueError:
                    self.ld_bad += 1
                else:
                    self.schema += _types_of(obj)
                    self.products += _products_of(obj)
            return
        if tag == "a" and self._a:
            self.links[self._a] = " ".join("".join(self._a_buf).split())[:80]
            self._a = None
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
        if self._a:
            self._a_buf.append(data)
        self.words += len(data.split())


def _types_of(obj) -> list[str]:
    """Mọi @type trong một khối JSON-LD đã đọc được."""
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
    walk(obj)
    return [str(t) for t in out]


def _ld_types(text: str) -> list[str]:
    try:
        return _types_of(json.loads(text))
    except ValueError:
        return []


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def _products_of(obj) -> list[dict]:
    """Tóm tắt các nút Product: tên, ảnh, giá, tiền tệ, tình trạng hàng, điểm đánh giá, thương hiệu, sku."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            t = x.get("@type")
            if "Product" in (t if isinstance(t, list) else [t]):
                offers = _first(x.get("offers")) or {}
                if isinstance(offers, dict) and offers.get("@type") == "AggregateOffer":
                    price = offers.get("lowPrice") or offers.get("price")
                else:
                    price = offers.get("price") if isinstance(offers, dict) else None
                    if price is None and isinstance(offers, dict):
                        spec = _first(offers.get("priceSpecification")) or {}
                        price = spec.get("price") if isinstance(spec, dict) else None
                rating = x.get("aggregateRating") or {}
                out.append({
                    "name": bool(str(x.get("name") or "").strip()), "image": bool(x.get("image")),
                    "offers": bool(offers), "price": None if price in (None, "") else str(price),
                    "currency": (offers.get("priceCurrency") if isinstance(offers, dict) else None) or None,
                    "availability": str((offers.get("availability") if isinstance(offers, dict) else "") or "")
                    .rsplit("/", 1)[-1] or None,
                    "rating": rating.get("ratingValue") if isinstance(rating, dict) else None,
                    "reviews": (rating.get("reviewCount") or rating.get("ratingCount")) if isinstance(rating, dict)
                    else None,
                    "review": bool(x.get("review")), "brand": bool(x.get("brand")),
                    "sku": bool(x.get("sku") or x.get("gtin") or x.get("gtin13") or x.get("mpn")),
                    "shipping": bool(isinstance(offers, dict) and offers.get("shippingDetails")),
                    "returns": bool((isinstance(offers, dict) and offers.get("hasMerchantReturnPolicy"))
                                    or x.get("hasMerchantReturnPolicy"))})
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return out


def _ld_products(text: str) -> list[dict]:
    try:
        return _products_of(json.loads(text))
    except ValueError:
        return []


def has_rating(products: list[dict]) -> bool:
    """Product đầu tiên có điểm đánh giá / đánh giá (điều kiện để Google hiện sao)."""
    return bool(products) and (products[0]["rating"] is not None or products[0]["review"])


def merchant_missing(products: list[dict], types: list[str]) -> list[str] | None:
    """Trường Google khuyên có cho Danh sách người bán còn thiếu. Đổi trả / vận chuyển khai ở chỗ khác trên trang
    (ví dụ chính sách đổi trả ở Organization) cũng tính là có. None: trang quét trước khi tool kiểm hai trường này."""
    if not products or "shipping" not in products[0]:
        return None
    p, have = products[0], set(types or [])
    out = []
    if not p["shipping"] and "OfferShippingDetails" not in have:
        out.append("phí vận chuyển (shippingDetails)")
    if not p["returns"] and "MerchantReturnPolicy" not in have:
        out.append("chính sách đổi trả (hasMerchantReturnPolicy)")
    return out


def product_problems(products: list[dict]) -> tuple[list[str], list[str]]:
    """(thiếu bắt buộc cho đoạn trích sản phẩm / danh sách người bán, thiếu nên có) của Product đầu tiên."""
    p = products[0]
    must, nice = [], []
    if not p["name"]:
        must.append("tên (name)")
    if not p["image"]:
        must.append("ảnh (image)")
    if not p["offers"]:
        must.append("offers (giá bán)")
    else:
        try:
            ok = p["price"] is not None and float(str(p["price"]).replace(",", "")) > 0
        except ValueError:
            ok = False
        if not ok:
            must.append("giá (price) trống hoặc bằng 0")
        if not p["currency"]:
            must.append("tiền tệ (priceCurrency)")
        if not p["availability"]:
            must.append("tình trạng hàng (availability)")
    if not p["brand"]:
        nice.append("thương hiệu (brand)")
    if not p["sku"]:
        nice.append("mã sản phẩm (sku / gtin)")
    return must, nice


def parse(html: str, url: str) -> dict:
    p = _Page(url)
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 — HTML hỏng: lấy được tới đâu dùng tới đó
        pass
    return {"title": p.title, "desc": p.desc, "robots": p.robots.strip(), "canonical": p.canonical,
            "h1": p.h1[:5], "h1_count": len(p.h1), "imgs": p.imgs, "noalt": p.noalt, "words": p.words,
            "links_int": p.links_int, "links_ext": p.links_ext, "schema": sorted(set(p.schema))[:40],
            "products": p.products[:3], "micro_product": p.micro_product,
            "ld_blocks": p.ld_blocks, "ld_bad": p.ld_bad,
            "canonicals": list(dict.fromkeys(p.canonicals))[:5], "lang": p.lang, "viewport": p.viewport,
            "nosnippet_blocks": p.nosnippet_blocks, "links": [[u, t] for u, t in p.links.items()]}


# ---- Mở trang ----

MAX_PAGE_BYTES = 5_000_000  # trần dung lượng một trang (cả sau khi giải nén)

# Chỉ tới địa chỉ công khai, không tự theo chuyển hướng (xem safe_fetch)
_opener = SF.OPEN_NO_REDIRECT


# Dấu hiệu trang chặn / thử thách của tường lửa (Cloudflare, Sucuri, Imperva…): server trả trang này thay cho trang thật
BLOCK_MARKS = ("cf-chl", "challenge-platform", "<title>just a moment", "attention required! | cloudflare",
               "cf-browser-verification", "_incapsula_resource", "sucuri website firewall", "access denied | ")
BLOCK_STATUS = {403, 429, 503}  # mã server hay trả khi chặn bot (429: gửi yêu cầu quá nhiều)


def _block_mark(body: str) -> bool:
    low = body[:30000].lower()
    return any(m in low for m in BLOCK_MARKS)


def fetch(url: str, timeout: int = TIMEOUT) -> dict:
    """Mở một trang, không tự theo chuyển hướng (để biết trang có chuyển hướng không). Trả status, final_url (đích
    chuyển hướng), ms, html, x_robots, error."""
    t = time.monotonic()
    try:
        resp = _opener.open(Request(url, headers=HEADERS), timeout=timeout)
        body = SF.read_body(resp, MAX_PAGE_BYTES)
        ctype = resp.headers.get("Content-Type", "")
        html = body.decode("utf-8", "ignore") if "html" in ctype or not ctype else ""
        if html and _block_mark(html):  # trang thử thách trả 200: không phải nội dung thật
            return {"status": resp.status, "final_url": None, "ms": int((time.monotonic() - t) * 1000), "html": "",
                    "x_robots": "", "error": None, "blocked": True}
        return {"status": resp.status, "final_url": None, "ms": int((time.monotonic() - t) * 1000),
                "html": html, "x_robots": (resp.headers.get("X-Robots-Tag") or "").lower(), "error": None,
                "enc": (resp.headers.get("Content-Encoding") or "").lower(), "bytes": len(body)}
    except HTTPError as e:
        loc = e.headers.get("Location") if e.headers else None
        blocked = e.code == 429
        if e.code in BLOCK_STATUS and not blocked:
            try:
                raw = SF.read_body(e, 40000)
                blocked = _block_mark(raw.decode("utf-8", "ignore"))
            except Exception:  # noqa: BLE001
                pass
        out = {"status": e.code, "final_url": urljoin(url, loc) if loc else None,
               "ms": int((time.monotonic() - t) * 1000), "html": "", "x_robots": "", "error": None}
        if blocked:
            out["blocked"] = True
        if e.code == 429:
            out["retry_after"] = e.headers.get("Retry-After") if e.headers else None
        return out
    except (URLError, OSError, HTTPException) as e:
        return {"status": None, "final_url": None, "ms": None, "html": "", "x_robots": "", "error": str(e)[:200]}


# ---- Chọn trang và quét ----

def group_pages(con: sqlite3.Connection, site: str) -> list[tuple[int, str]]:
    """URL trong các nhóm URL SEO (Quản lý URL), theo thứ tự thêm vào nhóm."""
    try:
        rows = con.execute(
            """SELECT u.id, u.url FROM url_group_members m JOIN url_groups g ON g.id = m.group_id
               JOIN urls u ON u.id = m.url_id WHERE g.site = ? AND u.site = ? ORDER BY m.added_at, u.id""",
            (site, site)).fetchall()
    except sqlite3.OperationalError:  # chưa có bảng nhóm URL
        return []
    return list(dict.fromkeys((i, u) for i, u in rows))


def url_groups(con: sqlite3.Connection, site: str) -> dict[int, list[str]]:
    """{url_id: [tên nhóm URL SEO]} để lọc kết quả audit theo nhóm."""
    out: dict[int, list[str]] = {}
    try:
        for uid, name in con.execute(
                """SELECT m.url_id, g.name FROM url_group_members m JOIN url_groups g ON g.id = m.group_id
                   WHERE g.site = ? ORDER BY g.id""", (site,)):
            out.setdefault(uid, []).append(name)
    except sqlite3.OperationalError:
        pass
    return out


def sitemap_pages(con: sqlite3.Connection, site: str) -> list[tuple[int, str]]:
    """Trang không phải sản phẩm trong sitemap (lần đọc gần nhất): trang chủ, danh mục, bài viết, cửa hàng, trang thông
    tin; bỏ URL có tham số."""
    from . import urls as U
    kinds = (U.HOME, U.CATEGORY, U.BRAND, U.STORE, U.INFO, U.BLOG)  # thứ tự: trang khung trước, bài viết sau
    try:
        m = con.execute("SELECT MAX(last_seen) FROM sitemap_urls WHERE site = ?", (site,)).fetchone()[0]
        if not m:
            return []
        rows = con.execute(
            f"""SELECT u.id, u.url, u.type FROM sitemap_urls s JOIN urls u ON u.site = s.site AND u.url = s.url
                WHERE s.site = ? AND s.last_seen = ? AND u.url NOT LIKE '%?%'
                AND u.type IN ({','.join('?' * len(kinds))})""", (site, m, *kinds)).fetchall()
    except sqlite3.OperationalError:  # chưa đọc sitemap lần nào
        return []
    rows.sort(key=lambda r: (kinds.index(r[2]), r[1]))
    return [(i, u) for i, u, _ in rows]


def pick_pages(con: sqlite3.Connection, site: str, end: date, limit: int = MAX_PAGES,
               top: int = TOP_TRAFFIC, top_products: int = TOP_PRODUCTS) -> list[tuple[int, str]]:
    """Trang sẽ quét, theo thứ tự ưu tiên: (1) mọi URL trong nhóm URL SEO (kể cả trang mới chưa có click; nhóm lớn
    hơn `limit` vẫn quét đủ); (2) `top` URL nhiều click (rồi nhiều hiển thị) nhất 90 ngày qua, mọi loại trang; (3)
    `top_products` trang sản phẩm nhiều click nhất; (4) mọi trang không phải sản phẩm trong sitemap. Tối đa `limit`
    trang; bỏ URL có tham số và URL cũ/kỹ thuật."""
    from . import urls as U
    picked = group_pages(con, site)
    have = {i for i, _ in picked}
    cap = max(limit, len(picked))
    since = (end - timedelta(days=89)).isoformat()
    rows = con.execute(
        """SELECT u.id, u.url FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id
           JOIN urls u ON u.id = pu.url_id AND u.site = ?
           WHERE d.date BETWEEN ? AND ? AND u.url NOT LIKE '%?%' AND COALESCE(u.type, '') != ?
           GROUP BY u.id ORDER BY SUM(d.clicks) DESC, SUM(d.impressions) DESC LIMIT ?""",
        (site, since, end.isoformat(), U.LEGACY, min(top, limit))).fetchall()
    prods = con.execute(
        """SELECT u.id, u.url FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id
           JOIN urls u ON u.id = pu.url_id AND u.site = ?
           WHERE d.date BETWEEN ? AND ? AND u.url NOT LIKE '%?%' AND u.type = ?
           GROUP BY u.id ORDER BY SUM(d.clicks) DESC, SUM(d.impressions) DESC LIMIT ?""",
        (site, since, end.isoformat(), U.PRODUCT, top_products)).fetchall() if top_products else []
    for i, u in rows + prods + sitemap_pages(con, site):
        if len(picked) >= cap:
            break
        if i not in have:
            picked.append((i, u))
            have.add(i)
    return picked


def page_clicks(con: sqlite3.Connection, site: str, end: date, url_ids: list[int],
                days: int = 28) -> dict[int, tuple[int, int]]:
    """Click và lượt hiển thị Search Console của từng URL trong `days` ngày tới `end`: {url_id: (click, hiển thị)}."""
    if not url_ids or end is None:
        return {}
    since = (end - timedelta(days=days - 1)).isoformat()
    out: dict[int, tuple[int, int]] = {}
    for i in range(0, len(url_ids), 500):
        part = url_ids[i:i + 500]
        for uid, c, n in con.execute(
                f"""SELECT u.id, SUM(d.clicks), SUM(d.impressions) FROM gsc_page_daily d
                    JOIN page_url pu ON pu.page_id = d.page_id JOIN urls u ON u.id = pu.url_id AND u.site = ?
                    WHERE d.date BETWEEN ? AND ? AND u.id IN ({','.join('?' * len(part))}) GROUP BY u.id""",
                (site, since, end.isoformat(), *part)):
            out[uid] = (c or 0, n or 0)
    return out


def level_pages(au: dict) -> dict[str, int]:
    """Số trang (không phải lượt) có ít nhất một mục ở từng mức: {"high": 2, "medium": 85, "info": 210}."""
    return {k: len({p["url_id"] for c in au["checks"] if c["level"] == k and not c.get("site") for p in c["pages"]})
            for k in LEVELS}


def last_run(con, done: bool = False) -> dict | None:
    """Lần quét mới nhất (done: lần quét xong mới nhất — kết quả hiển thị dựa trên lần này)."""
    ensure_tables(con)
    r = con.execute("SELECT id, started_at, finished_at, pages, errors, created_by FROM audit_runs "
                    + ("WHERE finished_at IS NOT NULL " if done else "") + "ORDER BY id DESC LIMIT 1").fetchone()
    return dict(zip(("id", "started_at", "finished_at", "pages", "errors", "by"), r)) if r else None


STALL = timedelta(minutes=10)  # lần quét đang chạy ghi một trang mỗi vài giây: 10 phút không ghi gì là đã dừng


def stopped(con, now: datetime | None = None) -> dict | None:
    """Lần quét mới nhất bị dừng giữa chừng (máy chủ khởi động lại, máy tắt, lỗi): chưa xong mà đã 10 phút không quét
    thêm trang nào. Trả {"id", "started_at", "pages_done"} hoặc None. Lần quét đang chạy (ở đây hay ở lịch hằng ngày)
    vẫn ghi trang đều nên không bị tính nhầm."""
    last = last_run(con)
    if not last or last["finished_at"]:
        return None
    now = now or datetime.now(timezone.utc)
    started = datetime.fromisoformat(last["started_at"])
    n, latest = con.execute("SELECT COUNT(*), MAX(fetched_at) FROM audit_pages WHERE fetched_at >= ?",
                            (last["started_at"],)).fetchone()
    alive = datetime.fromisoformat(latest) if latest else started
    if now - alive < STALL:
        return None
    return {"id": last["id"], "started_at": last["started_at"], "pages_done": n}


def run(con: sqlite3.Connection, site: str, end: date, user: str = "lịch tự động", limit: int = MAX_PAGES,
        fetcher=fetch, sleep=time.sleep, log=print, progress=None, key: str = "", site_checks: bool = True,
        opener=None, text_get=None, sb_query=None, cfg=None) -> dict:
    """Quét lại các trang quan trọng. Kết quả cũ của trang không còn trong danh sách được xóa."""
    ensure_tables(con)
    pages = pick_pages(con, site, end, limit)
    with con:
        run_id = con.execute("INSERT INTO audit_runs (started_at, created_by) VALUES (?, ?)",
                             (_now(), user)).lastrowid
    errors = blocked = streak = 0
    stopped_early = False
    for n, (uid, url) in enumerate(pages, 1):
        r = fetcher(url)
        if r.get("status") == 429:  # gửi quá nhanh: nghỉ theo server yêu cầu (tối đa 60 giây) rồi thử lại một lần
            try:
                wait = min(60, max(5, int(r.get("retry_after") or 15)))
            except ValueError:
                wait = 15
            sleep(wait)
            r = fetcher(url)
        is_blocked = bool(r.get("blocked")) or r.get("status") == 429
        data = parse(r["html"], url) if r["html"] else {}
        if is_blocked:
            data["blocked"] = 1
            blocked += 1
            streak += 1
        else:
            streak = 0
        data["x_robots"] = r.get("x_robots", "")
        if r.get("html"):
            data["enc"], data["bytes"] = r.get("enc", ""), r.get("bytes", 0)
        if r["error"]:
            errors += 1
        with con:
            con.execute("INSERT OR REPLACE INTO audit_pages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (uid, url, _now(), r["status"], r["final_url"], r["ms"], json.dumps(data, ensure_ascii=False),
                         r["error"]))
        if progress:
            progress(n, len(pages), "pages", url)
        if n % 25 == 0:
            log(f"Audit: {n}/{len(pages)} trang")
        if streak >= BLOCK_STREAK:  # bị chặn liên tục: dừng, mở tiếp chỉ làm tường lửa siết thêm
            log(f"Audit: website chặn bot {streak} trang liên tiếp, dừng quét trang")
            stopped_early = True
            break
        if n < len(pages):
            sleep(DELAY * (4 if streak else 1))  # vừa bị chặn: đi chậm lại
    keep = [uid for uid, _ in pages]
    with con:
        if keep:
            con.execute(f"DELETE FROM audit_pages WHERE url_id NOT IN ({','.join('?' * len(keep))})", keep)
        con.execute("UPDATE audit_runs SET finished_at = ?, pages = ?, errors = ? WHERE id = ?",
                    (_now(), len(pages), errors, run_id))
    snapshot(con, run_id)
    if site_checks:  # robots.txt, bot AI, HTTPS, chuyển hướng, link nội bộ, sitemap, Safe Browsing
        from . import site_checks as SC
        rows = con.execute("SELECT url, status, final_url, data FROM audit_pages").fetchall()
        kw = {k: v for k, v in (("opener", opener), ("text_get", text_get), ("sb_query", sb_query)) if v}
        try:
            SC.collect(con, site, [{"url": u, "status": st, "final_url": f, "data": json.loads(d or "{}")}
                                   for u, st, f, d in rows], key=key, log=log, progress=progress, **kw)
        except Exception as e:  # noqa: BLE001  (phần này lỗi không làm hỏng kết quả quét trang)
            log(f"Audit: kiểm tra cấp website chưa xong: {e}")
    _cache.clear()
    if progress:
        progress(0, 0, "calc")
    if cfg is not None:  # ghi kết quả của lần quét này (xem lại theo tuần), không đợi ai mở trang
        try:
            findings_history(con, findings(con, cfg, end))
        except Exception as e:  # noqa: BLE001
            log(f"Audit: chưa ghi được kết quả tuần: {e}")
    log(f"Audit: xong {len(pages)} trang, {errors} trang không mở được" + (f", {blocked} trang bị chặn" if blocked
                                                                           else ""))
    return {"pages": len(pages), "errors": errors, "blocked": blocked, "stopped_early": stopped_early}


WEEKDAYS = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật")
DEFAULT_SCHEDULE = {"weekday": 0, "hour": 2, "paused": False}  # 2 giờ sáng thứ Hai: website của khách ít người vào


def schedule(con: sqlite3.Connection) -> dict:
    """Lịch tự quét: {"weekday": 0 (thứ Hai)…6, "hour": 0–23 (giờ máy chủ), "paused": bool}."""
    ensure_tables(con)
    r = con.execute("SELECT v FROM audit_settings WHERE k = 'schedule'").fetchone()
    return {**DEFAULT_SCHEDULE, **(json.loads(r[0]) if r else {})}


def save_schedule(con: sqlite3.Connection, weekday: int, hour: int, paused: bool, user: str) -> dict:
    ensure_tables(con)
    v = {"weekday": max(0, min(6, int(weekday))), "hour": max(0, min(23, int(hour))), "paused": bool(paused),
         "by": user, "at": _now()}
    with con:
        con.execute("INSERT OR REPLACE INTO audit_settings VALUES ('schedule', ?)", (json.dumps(v),))
    return v


def last_slot(sch: dict, now: datetime) -> datetime:
    """Mốc quét theo lịch gần nhất đã qua (giờ máy chủ)."""
    slot = now.replace(hour=sch["hour"], minute=0, second=0, microsecond=0)
    slot -= timedelta(days=(now.weekday() - sch["weekday"]) % 7)
    return slot if slot <= now else slot - timedelta(days=7)


def next_slot(sch: dict, now: datetime) -> datetime:
    return last_slot(sch, now) + timedelta(days=7)


def due(con: sqlite3.Connection, now: datetime | None = None) -> bool:
    """Tới lịch quét chưa: đã qua mốc của tuần này mà chưa có lần quét nào bắt đầu sau mốc đó (máy tắt lúc tới mốc
    thì quét bù khi máy chạy lại). Tạm ngưng thì không."""
    sch = schedule(con)
    if sch["paused"]:
        return False
    now = now or datetime.now().astimezone()
    last = last_run(con)
    if not last:
        return True
    if not last["finished_at"]:  # đang quét thì thôi; bị dừng giữa chừng thì quét bù
        return stopped(con, now) is not None
    started = datetime.fromisoformat(last["started_at"]).astimezone(now.tzinfo)
    return started < last_slot(sch, now)


def refresh(con, cfg, today: date | None = None, force: bool = False, log=print, now: datetime | None = None,
            **kw) -> dict | None:
    """Quét theo lịch (thứ + giờ ở Technical Audit › Lịch quét; force: ngay). Gọi từ vòng lịch của máy chủ web (mỗi
    15 phút) và từ lịch hằng ngày: lần nào tới trước thì quét, lần sau thấy đã quét rồi thì thôi."""
    ensure_tables(con)
    if not force and not due(con, now):
        return None
    from .cwv import load_key
    try:
        key = load_key(cfg)
    except Exception:  # noqa: BLE001
        key = ""
    return run(con, cfg.site_url, K.latest_date(con, cfg.site_url), log=log, key=key, cfg=cfg, **kw)


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
    "error": ("medium", "Trang không mở được lúc quét", "Hết giờ chờ hoặc lỗi kết nối lúc tool mở trang (ACC-006): mở "
              "thử trang; vẫn chậm hoặc lỗi thì nhờ dev kiểm tra máy chủ / tường lửa, vì Google cũng có thể gặp."),
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
    "product_no_schema": ("high", "Trang sản phẩm thiếu schema Product", "Thêm dữ liệu cấu trúc Product (JSON-LD) "
                          "có tên, ảnh, giá, tiền tệ, tình trạng hàng: không có thì Google không hiện giá / sao ở "
                          "kết quả tìm kiếm."),
    "product_bad": ("high", "Schema Product thiếu trường bắt buộc", "Bổ sung các trường còn thiếu: Google bỏ đoạn "
                    "trích sản phẩm (giá, tình trạng hàng) và danh sách người bán khi thiếu."),
    "product_no_rating": ("medium", "Sản phẩm chưa có sao đánh giá", "Bật đánh giá của khách trên trang sản "
                          "phẩm (plugin đánh giá của WooCommerce): khi có đánh giá thật, schema có aggregateRating và "
                          "Google có thể hiện sao. Không tự điền số sao khi trang không có đánh giá thật: Google coi là "
                          "spam dữ liệu cấu trúc."),
    "product_merchant": ("info", "Sản phẩm thiếu phí vận chuyển / đổi trả", "Khai báo shippingDetails và "
                         "hasMerchantReturnPolicy trong Offer (hoặc chính sách đổi trả chung ở Organization): Google "
                         "dùng để hiện sản phẩm ở Danh sách người bán kèm phí ship và đổi trả."),
    "product_nice": ("info", "Schema Product nên bổ sung", "Thêm đánh giá (để hiện sao), thương hiệu, mã sản phẩm: "
                     "giúp kết quả nổi bật hơn và đủ điều kiện nhiều dạng hiển thị hơn."),
    "schema_error": ("high", "Dữ liệu cấu trúc lỗi cú pháp (JSON-LD)", "Khối JSON-LD sai cú pháp thì Google bỏ "
                     "qua cả khối: trang mất hết đoạn trích nổi bật. Nhờ dev kiểm tra lại đoạn mã (thường do thiếu "
                     "dấu phẩy, thừa dấu ngoặc, hoặc nội dung chèn vào chưa thoát dấu nháy)."),
    "no_schema": ("info", "Trang chưa có dữ liệu cấu trúc nào", "Thêm JSON-LD hợp loại trang: Article cho bài viết, "
                  "Product cho sản phẩm, BreadcrumbList cho đường dẫn, FAQPage cho trang hỏi đáp. Google hiểu trang "
                  "rõ hơn và có cơ hội hiện đoạn trích nổi bật."),
    "slow": ("info", "Máy chủ phản hồi chậm (trên 3 giây)", "Xem lại cache / hosting; chi tiết tốc độ ở trang Tốc "
             "độ trang."),
    # ---- theo bộ tri thức Technical Search & GEO (mã mục trong ngoặc)
    "robots_blocked": ("high", "Trang bị robots.txt chặn Googlebot", "Trang đang có traffic nhưng robots.txt cấm "
                       "Googlebot vào (ACC-003): sửa hoặc xóa dòng Disallow ghi ở cột Chi tiết, rồi kiểm tra lại bằng "
                       "URL Inspection."),
    "blocked": ("info", "Website chặn bot quét của tool", "Tường lửa / Cloudflare của website trả trang chặn (403, 429, "
                "503 hoặc trang thử thách) cho bot của tool, nên các trang này chưa kiểm được: không phải lỗi SEO. Nhờ "
                "dev cho phép User-Agent “SEOReportBot” (hoặc IP của máy chạy tool) trong tường lửa, rồi quét lại. Nếu "
                "trang đang có traffic, mở Search Console › Kiểm tra URL để chắc Googlebot không bị chặn theo."),
    "unsafe": ("high", "Google Safe Browsing cảnh báo trang", "Google đánh dấu trang là nguy hiểm (ACC-009): nhờ dev "
               "quét mã độc, gỡ mã lạ, đổi mật khẩu quản trị, rồi xin Google xem lại ở Search Console › Bảo mật."),
    "redirect_loop": ("high", "Chuyển hướng vòng lặp", "Trang chuyển hướng vòng tròn, không tới được trang nào (CANON-007): "
                      "sửa quy tắc chuyển hướng cho trỏ thẳng tới trang đích."),
    "redirect_broken": ("high", "Chuyển hướng tới trang lỗi", "Trang chuyển hướng tới URL lỗi hoặc không mở được "
                        "(CANON-007): đổi đích chuyển hướng sang trang còn hoạt động."),
    "redirect_chain": ("medium", "Chuyển hướng qua nhiều bước", "Trang chuyển hướng qua 2 bước trở lên (CANON-007): "
                       "cho chuyển thẳng một bước tới URL cuối."),
    "canonical_multi": ("high", "Nhiều thẻ canonical khác nhau", "Trang có từ 2 thẻ canonical trỏ khác nhau, Google "
                        "có thể bỏ qua tất cả (CANON-003): giữ một thẻ."),
    "canonical_bad_target": ("high", "Canonical trỏ tới trang lỗi", "Canonical trỏ tới URL trả 4xx / 5xx hoặc không mở "
                             "được (CANON-003): trỏ canonical về URL đang hoạt động (thường là chính trang này)."),
    "canonical_redirect": ("medium", "Canonical trỏ tới trang đang chuyển hướng", "Canonical nên trỏ thẳng URL cuối "
                           "trả 200 (CANON-003): sửa thành URL đích của chuyển hướng."),
    "canonical_missing": ("info", "Trang chưa khai báo canonical", "Không bắt buộc, nhưng canonical tự trỏ về chính "
                          "trang giúp Google chọn đúng URL khi có bản trùng (CANON-003)."),
    "link_broken": ("high", "Link nội bộ trỏ tới trang lỗi", "Link trong trang trỏ tới URL 4xx / 5xx (LINK-002): sửa "
                    "link sang trang còn hoạt động hoặc bỏ link. Mỗi dòng là một link: trang chứa link, link đang trỏ "
                    "tới đâu, anchor."),
    "link_redirect": ("medium", "Link nội bộ trỏ tới trang chuyển hướng", "Link nên trỏ thẳng URL cuối (LINK-002): đổi "
                      "link sang URL đích, đỡ một bước chuyển hướng cho Google và người dùng."),
    "nosnippet": ("medium", "Trang chặn Google trích đoạn (nosnippet)", "Thẻ robots có nosnippet / max-snippet:0 "
                  "(INDEX-007): Google và AI không trích được nội dung trang. Bỏ nếu không cố ý."),
    "data_nosnippet": ("info", "Có đoạn không cho trích dẫn (data-nosnippet)", "Các phần gắn data-nosnippet sẽ không "
                       "xuất hiện trong đoạn trích của Google (INDEX-007): kiểm tra có đúng ý không."),
    "no_viewport": ("medium", "Thiếu thẻ viewport cho điện thoại", "Thêm <meta name=\"viewport\" content=\"width="
                    "device-width, initial-scale=1\"> để trang hiển thị đúng trên điện thoại (PERF-007)."),
    "no_lang": ("info", "Thiếu thẻ ngôn ngữ (lang)", "Thêm lang=\"vi\" vào thẻ <html> để máy đọc biết trang viết bằng "
                "tiếng Việt (INTL-001)."),
    "no_gzip": ("info", "Trang không được nén (gzip)", "Bật nén gzip / brotli trên hosting hoặc CDN: trang tải nhanh hơn "
                "(PERF-003)."),
    # cấp website: không tính vào ô số trang, đơn vị là URL / địa chỉ
    "host_dup": ("high", "Website mở được ở nhiều địa chỉ", "Mọi bản http / https, có / không www phải chuyển 301 về "
                 "một địa chỉ chính (ACC-001, CANON-001): nhờ dev thêm chuyển hướng trên hosting / CDN."),
    "host_redirect": ("medium", "Địa chỉ phụ chuyển hướng chưa chuẩn", "Bản http / www nên chuyển 301 thẳng về địa "
                      "chỉ chính (CANON-001)."),
    "robots_error": ("high", "Không đọc được robots.txt", "robots.txt trả lỗi máy chủ hoặc không mở được: Google tạm "
                     "coi như cấm toàn bộ website (ACC-003). Nhờ dev kiểm tra ngay."),
    "ai_search_blocked": ("medium", "Bot tìm kiếm AI bị chặn trong robots.txt", "Bot của ChatGPT Search / Perplexity "
                          "/ Claude / Bing bị cấm thì website khó được các nền tảng đó trích dẫn (AI-001, AI-003). Bỏ "
                          "chặn nếu muốn xuất hiện ở đó. Chặn bot huấn luyện (GPTBot…) là chính sách, không phải lỗi."),
    "sitemap_broken": ("high", "URL trong sitemap trả lỗi", "Sitemap chỉ nên chứa URL trả 200 (DISC-002): bỏ URL lỗi "
                       "khỏi sitemap hoặc khôi phục trang. URL không mở được lúc kiểm (hết giờ chờ) không tính là lỗi."),
    "sitemap_redirect": ("medium", "URL trong sitemap đang chuyển hướng", "Thay bằng URL đích trong sitemap (DISC-002)."),
    "sitemap_noindex": ("medium", "URL trong sitemap bị noindex hoặc canonical sang trang khác", "Sitemap chỉ nên "
                        "chứa URL muốn được index (DISC-002): bỏ khỏi sitemap hoặc gỡ noindex / sửa canonical."),
}
WANT = {
    "error": "mở được trong vài giây", "4xx": "trả 200, hoặc chuyển 301 sang trang thay thế", "5xx": "trả 200",
    "redirect": "link và sitemap trỏ thẳng URL đích", "noindex": "bỏ noindex (nếu muốn có trên Google)",
    "canonical": "canonical về chính trang (nếu đây là trang chính)", "no_title": "có tiêu đề 20–65 ký tự",
    "dup_title": "tiêu đề riêng cho từng trang", "long_title": "tối đa 65 ký tự", "short_title": "ít nhất 20 ký tự",
    "no_desc": "mô tả 70–160 ký tự", "dup_desc": "mô tả riêng cho từng trang", "bad_desc": "70–160 ký tự",
    "no_h1": "một thẻ H1", "multi_h1": "một thẻ H1", "kw_title": "tiêu đề chứa từ khóa chính",
    "low_ctr": "viết lại tiêu đề / mô tả hấp dẫn hơn", "thin": "từ 300 chữ", "noalt": "mọi ảnh có alt",
    "product_no_schema": "JSON-LD Product", "product_bad": "đủ trường bắt buộc",
    "product_nice": "thêm brand / sku", "product_no_rating": "aggregateRating từ đánh giá thật",
    "product_merchant": "shippingDetails + hasMerchantReturnPolicy", "schema_error": "JSON-LD đúng cú pháp",
    "no_schema": "JSON-LD hợp loại trang", "slow": "dưới 3 giây", "robots_blocked": "Googlebot được vào",
    "unsafe": "không bị cảnh báo", "blocked": "tool mở được trang (cho phép SEOReportBot)", "redirect_loop": "chuyển thẳng tới trang đích", "redirect_broken": "đích trả 200",
    "redirect_chain": "một bước tới URL cuối", "canonical_multi": "một thẻ canonical",
    "canonical_bad_target": "canonical tới URL trả 200", "canonical_missing": "canonical về chính trang",
    "link_broken": "link tới trang còn hoạt động", "nosnippet": "bỏ nosnippet / max-snippet:0",
    "data_nosnippet": "chỉ dùng ở phần cố ý ẩn", "no_viewport": "width=device-width, initial-scale=1",
    "no_lang": "lang=\"vi\"", "no_gzip": "nén gzip / brotli", "host_dup": "301 về địa chỉ chính",
    "host_redirect": "301 thẳng về địa chỉ chính", "robots_error": "robots.txt trả 200 hoặc 404",
    "ai_search_blocked": "cho vào (nếu muốn xuất hiện ở đó)", "sitemap_broken": "bỏ khỏi sitemap / khôi phục trang",
    "sitemap_noindex": "bỏ khỏi sitemap hoặc gỡ noindex",
}
SITE_CODES = {"host_dup", "host_redirect", "robots_error", "ai_search_blocked", "sitemap_broken", "sitemap_redirect",
              "sitemap_noindex"}  # mục cấp website: đơn vị là URL, không tính vào ô "trang có mục …"


_cache: dict = {}  # (file dữ liệu, lần quét, ngày GSC) -> kết quả: chuông thông báo không tính lại liên tục
running: dict = {}  # file dữ liệu -> tiến độ lần quét đang chạy (một lần quét mỗi dự án), xem track()

# Các bước của một lần quét, theo thứ tự (tên hiển thị, đơn vị đếm)
STEPS = (("pages", "Quét các trang", "trang"), ("basic", "Kiểm robots.txt, HTTPS, bot AI", ""),
         ("links", "Kiểm link nội bộ, canonical, sitemap", "URL"), ("sb", "Kiểm Google Safe Browsing", ""),
         ("calc", "Tính kết quả", ""))


def track(key: str, by: str):
    """Bắt đầu theo dõi một lần quét: running[key] = {"phase", "n", "total", "url", "by", "t0", "pt0"}; trả hàm
    progress(n, total, phase, url) để truyền cho run()."""
    t = time.time()
    running[key] = {"n": 0, "total": 0, "by": by, "phase": "pages", "url": "", "t0": t, "pt0": t}

    def progress(n, total, phase="pages", url=None):
        r = running.get(key)
        if r is None:
            return
        if r["phase"] != phase:
            r["pt0"] = time.time()
        r.update(n=n, total=total, phase=phase)
        if url:
            r["url"] = url
    return progress


def eta(r: dict, now: float | None = None) -> int | None:
    """Số giây còn lại ước tính của bước đang chạy (theo tốc độ từ đầu bước tới giờ); None khi chưa đủ số để ước."""
    if not r.get("total") or r.get("n", 0) < 5:
        return None
    spent = (now or time.time()) - r["pt0"]
    return int(spent / r["n"] * (r["total"] - r["n"]))


def schema_summary(con: sqlite3.Connection) -> dict:
    """Loại dữ liệu cấu trúc đọc được ở lần quét gần nhất: {"types": [(tên, số trang)], "pages", "with", "bad",
    "unknown"}. unknown: trang quét từ trước khi tool đếm khối JSON-LD."""
    ensure_tables(con)
    rows = con.execute("SELECT data, status, error FROM audit_pages").fetchall()
    types: dict[str, int] = {}
    pages = have = bad = unknown = 0
    prod = rated = 0
    no_ship = no_ret = None  # None: chưa quét lại từ khi kiểm hai trường này
    for data, status, err in rows:
        if err or not status or status >= 300:
            continue
        d = json.loads(data or "{}")
        if d.get("ld_blocks") is None:
            unknown += 1
            continue
        pages += 1
        got = sorted(set(d.get("schema") or []))
        if got:
            have += 1
        for t in got:
            types[t] = types.get(t, 0) + 1
        if d.get("ld_bad"):
            bad += 1
        prods = d.get("products") or []
        if prods:
            prod += 1
            rated += has_rating(prods)
            miss = merchant_missing(prods, got)
            if miss is not None:
                no_ship = (no_ship or 0) + any("vận chuyển" in m for m in miss)
                no_ret = (no_ret or 0) + any("đổi trả" in m for m in miss)
    return {"types": sorted(types.items(), key=lambda kv: (-kv[1], kv[0])), "pages": pages, "with": have,
            "bad": bad, "unknown": unknown, "products": prod, "rated": rated, "no_shipping": no_ship,
            "no_returns": no_ret}


def snapshot(con: sqlite3.Connection, run_id: int | None = None) -> bool:
    """Ghi số schema của lần quét (mặc định: lần xong gần nhất) để theo dõi tiến độ. Đã ghi thì thôi."""
    ensure_tables(con)
    r = con.execute("SELECT id, finished_at FROM audit_runs WHERE finished_at IS NOT NULL "
                    + ("AND id = ? " if run_id else "") + "ORDER BY id DESC LIMIT 1",
                    (run_id,) if run_id else ()).fetchone()
    if not r or con.execute("SELECT 1 FROM audit_schema_hist WHERE run_id = ?", (r[0],)).fetchone():
        return False
    sm = schema_summary(con)
    if not sm["pages"]:  # lần quét cũ chưa ghi dữ liệu cấu trúc
        return False
    sm.pop("types")
    with con:
        con.execute("INSERT INTO audit_schema_hist (run_id, at, data) VALUES (?, ?, ?)",
                    (r[0], r[1], json.dumps(sm)))
    return True


def schema_history(con: sqlite3.Connection, limit: int = 8) -> list[dict]:
    """Số schema các lần quét gần nhất, mới trước: [{"at", "pages", "with", "products", "rated", …}]."""
    ensure_tables(con)
    return [{"at": at, **json.loads(data)} for at, data in con.execute(
        "SELECT at, data FROM audit_schema_hist ORDER BY run_id DESC LIMIT ?", (limit,))]


def ignored(con: sqlite3.Connection) -> set[tuple[str, str]]:
    """(mã mục, URL) người dùng đã đánh dấu "cố ý, bỏ qua": không tính là lỗi ở các lần quét sau."""
    ensure_tables(con)
    return {(c, u) for c, u in con.execute("SELECT code, url FROM audit_ignore")}


def set_ignored(con: sqlite3.Connection, code: str, urls: list[str], on: bool, user: str) -> int:
    ensure_tables(con)
    with con:
        for u in urls:
            if on:
                con.execute("INSERT OR REPLACE INTO audit_ignore VALUES (?, ?, ?, ?)", (code, u, _now(), user))
            else:
                con.execute("DELETE FROM audit_ignore WHERE code = ? AND url = ?", (code, u))
    return len(urls)


def _codes(data: dict) -> dict:
    """Kết quả gọn {mã mục: [URL]} của một bản ghi lịch sử (bản ghi cũ chỉ có phần này)."""
    if "codes" in data:
        return data["codes"]
    return {k: v for k, v in data.items() if isinstance(v, list)}


def findings_history(con: sqlite3.Connection, au: dict) -> tuple[dict | None, str | None]:
    """Ghi kết quả của lần quét mới nhất (nếu chưa ghi): lỗi theo mục, số tiêu chí theo trạng thái, số lỗi mới / đã hết
    so với lần trước. Trả (kết quả gọn lần quét trước, ngày quét lần trước); chưa có lần trước: (None, None)."""
    from . import audit_checklist as AC
    from . import site_checks as SC
    ensure_tables(con)
    last = au.get("run")
    lid = (last or {}).get("id") or 0
    r = con.execute("SELECT at, data FROM audit_findings_hist WHERE run_id < ? ORDER BY run_id DESC LIMIT 1",
                    (lid,)).fetchone()
    prev, prev_at = (_codes(json.loads(r[1])), r[0]) if r else (None, None)
    prev_scanned = set(json.loads(r[1]).get("scanned") or []) or None if r else None
    if not (last and last.get("finished_at")):
        return prev, prev_at
    had = con.execute("SELECT data FROM audit_findings_hist WHERE run_id = ?", (lid,)).fetchone()
    old_d = json.loads(had[0]) if had else {}
    if not had or "status" not in old_d or "scanned" not in old_d:  # lần quét mới, hoặc ghi trước khi có các phần này
        areas = AC.build(au, SC.latest(con), au.get("meta") or {})
        status = {r["name"]: [r["status"], r["count"]] for a_ in areas for r in a_["rows"]}
        if had:
            old = json.loads(had[0])
            data = {**(old if "codes" in old else {"codes": _codes(old)}), "status": status,
                    "scanned": sorted(au.get("scanned") or [])}
        else:
            codes = AC.snapshot(au)
            dif = AC.diff(codes, prev, set(au.get("scanned") or []), prev_scanned)
            data = {"codes": codes, "totals": AC.totals(areas), "pages": au.get("pages", 0), "status": status,
                    "scanned": sorted(au.get("scanned") or []),
                    "new": len(dif["new"]) if dif["has_prev"] else None,
                    "first": len(dif["first"]) if dif["has_prev"] else None,
                    "fixed": len(dif["fixed"]) if dif["has_prev"] else None}
        with con:
            con.execute("INSERT OR REPLACE INTO audit_findings_hist VALUES (?, ?, ?)",
                        (lid, last["finished_at"], json.dumps(data, ensure_ascii=False)))
    return prev, prev_at


def prev_scanned(con: sqlite3.Connection, au: dict) -> set[str] | None:
    """Danh sách trang của lần quét trước lần đang xem (để tách lỗi ở trang lần đầu được quét); None khi lần trước
    chưa ghi danh sách này (bản ghi cũ)."""
    lid = (au.get("run") or {}).get("id") or 0
    r = con.execute("SELECT data FROM audit_findings_hist WHERE run_id < ? ORDER BY run_id DESC LIMIT 1",
                    (lid,)).fetchone()
    return set(json.loads(r[0]).get("scanned") or []) or None if r else None


def history_list(con: sqlite3.Connection, limit: int = 26) -> list[dict]:
    """Các lần quét đã ghi, mới trước: [{"run_id", "at", "pages", "totals", "new", "fixed", "codes"}]."""
    ensure_tables(con)
    out = []
    for rid, at, data in con.execute("SELECT run_id, at, data FROM audit_findings_hist ORDER BY run_id DESC LIMIT ?",
                                     (limit,)):
        d = json.loads(data)
        out.append({"run_id": rid, "at": at, "pages": d.get("pages"), "totals": d.get("totals"),
                    "new": d.get("new"), "first": d.get("first"), "fixed": d.get("fixed"), "codes": _codes(d),
                    "status": d.get("status")})
    return out


# ---- "Đã xử lý" → kiểm lại ngay

GSC_CODES = {"low_ctr"}  # cần số Search Console mới (vài tuần) mới biết đã đỡ chưa: không kiểm lại ngay được


def recheck(con: sqlite3.Connection, cfg, items: list[tuple[str, str]], user: str, fetcher=fetch, opener=None,
            text_get=None, sleep=time.sleep) -> list[dict]:
    """Người dùng báo đã xử lý các dòng (mã mục, URL): mở lại đúng các trang đó (và URL mà link / canonical của trang
    trỏ tới, URL sitemap, địa chỉ http / www, robots.txt khi cần), tính lại kết quả, ghi nhật ký. Trả mỗi dòng
    {"code", "url", "result": "pass" | "fail" | "unknown", "now"}."""
    from . import site_checks as SC
    ensure_tables(con)
    SC.ensure(con)
    opener = opener or SC.head
    site = cfg.site_url
    pages = {u: uid for uid, u in con.execute("SELECT url_id, url FROM audit_pages")}
    urls = list(dict.fromkeys(u for _, u in items if u in pages))
    failed: set[str] = set()
    targets: list[str] = []
    for n, u in enumerate(urls):
        r = fetcher(u)
        data = parse(r["html"], u) if r["html"] else {}
        data["x_robots"] = r.get("x_robots", "")
        if r.get("html"):
            data["enc"], data["bytes"] = r.get("enc", ""), r.get("bytes", 0)
        if r["error"]:
            failed.add(u)
        with con:
            con.execute("INSERT OR REPLACE INTO audit_pages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (pages[u], u, _now(), r["status"], r["final_url"], r["ms"],
                         json.dumps(data, ensure_ascii=False), r["error"]))
        targets += [h for h, _ in data.get("links") or []] + (data.get("canonicals") or [])[:1]
        if n < len(urls) - 1:
            sleep(DELAY)
    # URL cấp website / đích của link, canonical, sitemap: bỏ trạng thái cũ rồi mở lại
    targets += [u for c, u in items if c.startswith("sitemap_") and u.startswith("http")]
    targets = [t for t in dict.fromkeys(targets) if t not in pages]
    if targets:
        with con:
            con.executemany("DELETE FROM audit_url_status WHERE url = ?", [(t,) for t in targets])
        SC.check_statuses(con, targets, budget=len(targets), opener=opener, pause=0.1)
    sc = SC.latest(con) or {}
    changed = False
    if any(c in ("host_dup", "host_redirect") for c, _ in items):
        sc["host"] = SC.host_check(site, opener)
        changed = True
    if any(c in ("robots_error", "robots_blocked", "ai_search_blocked") for c, _ in items):
        r = (text_get or SC.get_text)(urljoin(site, "/robots.txt"))
        if r["error"] or r["status"] is None or r["status"] >= 500:
            sc["robots"] = {"status": r["status"], "error": r["error"] or f"máy chủ trả {r['status']}", "groups": None,
                            "text": ""}
        elif r["status"] >= 400:
            sc["robots"] = {"status": r["status"], "error": None, "groups": [], "text": "", "missing": True}
        else:
            sc["robots"] = {"status": r["status"], "error": None, "groups": SC.parse_robots(r["text"]),
                            "text": r["text"][:20000]}
        ok_urls = [u for (u, st) in con.execute("SELECT url, status FROM audit_pages") if st == 200]
        home = urljoin(site, "/")
        sc["bots"] = SC.bot_policy(sc["robots"], ok_urls, home)
        changed = True
    for u in urls:  # trang đang chuyển hướng: đi lại chuỗi chuyển hướng
        st = con.execute("SELECT status FROM audit_pages WHERE url = ?", (u,)).fetchone()[0]
        if st and 300 <= st < 400:
            sc.setdefault("redirects", {})[u] = SC.follow(u, opener)
            changed = True
    if changed and sc:
        with con:
            con.execute("INSERT OR REPLACE INTO audit_site VALUES ('latest', ?, ?)",
                        (sc.get("at") or _now(), json.dumps(sc, ensure_ascii=False)))
    _cache.clear()
    au = findings(con, cfg)
    now_rows = {(c["code"], p["url"]): p for c in au["checks"] for p in c["pages"]}
    out = []
    for code, u in items:
        if code in GSC_CODES:
            res, now = "unknown", "cần số Search Console mới (vài tuần) mới biết"
        elif u in failed:
            res, now = "unknown", "không mở được trang lúc kiểm lại"
        elif (code, u) in now_rows:
            res, now = "fail", now_rows[(code, u)].get("now") or now_rows[(code, u)].get("detail") or ""
        else:
            res, now = "pass", ""
        out.append({"code": code, "url": u, "result": res, "now": now})
    with con:
        con.executemany("INSERT INTO audit_fix_log (code, url, at, by, result, detail) VALUES (?, ?, ?, ?, ?, ?)",
                        [(r["code"], r["url"], _now(), user, r["result"], r["now"]) for r in out])
    return out


def fix_log(con: sqlite3.Connection, codes: list[str] | None = None, limit: int = 50) -> list[dict]:
    """Nhật ký "Đã xử lý": ai xác nhận, lúc nào, kiểm lại ra sao. Mới trước."""
    ensure_tables(con)
    q, args = "SELECT code, url, at, by, result, detail FROM audit_fix_log", []
    if codes:
        q += f" WHERE code IN ({','.join('?' * len(codes))})"
        args = list(codes)
    q += " ORDER BY id DESC LIMIT ?"
    return [dict(zip(("code", "url", "at", "by", "result", "detail"), r)) for r in con.execute(q, (*args, limit))]


def cached_findings(con, cfg) -> dict:
    last = last_run(con, done=True)
    if not last:
        return {"checks": [], "pages": 0, "healthy": 0, "run": None}
    end = K.latest_date(con, cfg.site_url)
    ensure_tables(con)
    ign = con.execute("SELECT COUNT(*), MAX(at) FROM audit_ignore").fetchone()
    key = (str(cfg.db_path), last["id"] if last else None, last["finished_at"] if last else None, end, tuple(ign))
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

    def add(code, uid, url, detail="", want=None, extra=""):
        """Một dòng kết quả: Đang là (detail) / Nên là (want, mặc định theo mục) / ghi chú thêm (anchor…)."""
        found[code].append({"url_id": uid, "url": url, "detail": detail, "now": detail,
                            "want": WANT.get(code, "") if want is None else want, "extra": extra})

    unknown = {"links": 0, "sitemap": 0, "canonical": 0}  # URL không mở được lúc kiểm: chưa kiểm được, không phải lỗi

    from . import site_checks as SC
    sc = SC.latest(con) or {}
    known = SC.known_statuses(con)
    page_status = {u: (st, f) for _, u, st, f, *_ in rows}
    page_data = {u: json.loads(d or "{}") for _, u, _, _, _, d, *_ in rows}
    rb = (sc.get("robots") or {}).get("groups")
    flagged = (sc.get("safe") or {}).get("flagged") or {}
    chains = sc.get("redirects") or {}

    def state(u):
        """(status, location) của một URL: trang đã quét hoặc URL đã mở để kiểm tra; None khi chưa biết."""
        if u in page_status:
            return page_status[u]
        k = known.get(u)
        return (k["status"], k["location"]) if k else None

    def short(u):
        return urlsplit(u).path or "/"

    # Bị chặn: trang có dấu tường lửa / 429; hoặc nhiều trang cùng trả 403 / 503 (trang thật hiếm khi vậy hàng loạt)
    n_bs = sum(1 for _, _, st, *_ in rows if st in (403, 503))
    blocking = n_bs >= max(5, len(rows) * 0.03)

    def is_blocked(st, d=None) -> bool:
        return bool(d and d.get("blocked")) or st == 429 or (blocking and st in (403, 503))

    ok = []
    for uid, url, status, final, ms, data, err, type_ in rows:
        d = json.loads(data or "{}")
        if is_blocked(status, d):
            add("blocked", uid, url, f"HTTP {status}" + (" · trang chặn của tường lửa" if d.get("blocked") else ""))
            continue
        if url in flagged:
            from .backlink_links import SB_TYPES
            add("unsafe", uid, url, SB_TYPES.get(flagged[url], flagged[url]))
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
            add("redirect", uid, url, f"HTTP {status} → {short(final) if final else '?'}")
            ch = chains.get(url)
            if ch:
                path_ = " → ".join(f"{short(u)} ({st_ or '?'})" for u, st_ in ch["chain"])
                if ch["loop"]:
                    add("redirect_loop", uid, url, path_)
                elif ch["error"] or (ch["status"] or 0) >= 400:
                    add("redirect_broken", uid, url, path_ + (f" · {ch['error']}" if ch["error"] else ""))
                elif len(ch["chain"]) > 2:
                    add("redirect_chain", uid, url, path_)
            continue
        robots = f"{d.get('robots', '')} {d.get('x_robots', '')}"
        if "noindex" in robots:
            add("noindex", uid, url, robots.strip())
        if rb:
            allowed, rule = SC.robots_rule(rb, "Googlebot", url)
            if not allowed:
                add("robots_blocked", uid, url, rule)
        if "nosnippet" in robots or re.search(r"max-snippet\s*:\s*0\b", robots):
            add("nosnippet", uid, url, robots.strip())
        if d.get("nosnippet_blocks"):
            add("data_nosnippet", uid, url, f"{d['nosnippet_blocks']} đoạn")
        if "canonicals" in d:  # trang quét từ khi tool đọc đủ thẻ canonical
            cans = d["canonicals"]
            if len(cans) > 1:
                add("canonical_multi", uid, url, " · ".join(short(c) for c in cans))
            elif not cans and "noindex" not in robots:
                add("canonical_missing", uid, url)
            if cans and _norm(cans[0]) != _norm(url):
                st_ = state(cans[0])
                if st_ and (st_[0] is None or is_blocked(st_[0])):
                    unknown["canonical"] += 1
                elif st_ and st_[0] >= 400:
                    add("canonical_bad_target", uid, url, f"canonical → {short(cans[0])} ({st_[0]})")
                elif st_ and 300 <= st_[0] < 400:
                    add("canonical_redirect", uid, url, f"canonical → {short(cans[0])} ({st_[0]})",
                        want=f"canonical → {short(st_[1] or '')}")
            if "viewport" in d and not d["viewport"]:
                add("no_viewport", uid, url)
            if "lang" in d and not d["lang"]:
                add("no_lang", uid, url)
            if d.get("bytes", 0) > 2000 and "enc" in d and not d["enc"]:
                add("no_gzip", uid, url, f"{d['bytes'] // 1024} KB không nén")
        for href, anchor in d.get("links") or []:
            st_ = state(href)
            if not st_:
                continue
            a = f"anchor “{anchor}”" if anchor else ""
            if st_[0] is None or is_blocked(st_[0]):
                unknown["links"] += 1
            elif st_[0] >= 400:
                add("link_broken", uid, url, f"link tới {short(href)} ({st_[0]})", extra=a)
            elif 300 <= st_[0] < 400:
                add("link_redirect", uid, url, f"link tới {short(href)} ({st_[0]})",
                    want=f"link tới {short(st_[1] or '')}", extra=a)
        can = d.get("canonical")
        if can and _norm(can) != _norm(url):
            add("canonical", uid, url, f"canonical → {short(can)}")
        if ms and ms > SLOW_MS:
            add("slow", uid, url, f"{ms / 1000:.1f} giây".replace(".", ","))
        if d.get("noalt"):
            add("noalt", uid, url, f"{d['noalt']}/{d['imgs']} ảnh")
        if type_ == U.BLOG and d.get("words", 0) < THIN_WORDS:
            add("thin", uid, url, f"khoảng {d.get('words', 0)} chữ")
        if d.get("ld_blocks") is not None:  # trang quét từ khi tool đếm khối JSON-LD
            if d.get("ld_bad"):
                add("schema_error", uid, url,
                    f"{d['ld_bad']}/{d['ld_blocks']} khối JSON-LD không đọc được")
            elif not d.get("schema"):
                add("no_schema", uid, url, "có microdata Product" if d.get("micro_product") else "")
        prods = d.get("products")
        if prods is not None:  # trang quét từ khi có kiểm tra schema Product
            if prods:
                must, nice = product_problems(prods)
                if must:
                    add("product_bad", uid, url, "thiếu " + ", ".join(must))
                elif nice:
                    add("product_nice", uid, url, "nên thêm " + ", ".join(nice))
                if not has_rating(prods):
                    add("product_no_rating", uid, url, "chưa có aggregateRating / review")
                miss = merchant_missing(prods, d.get("schema") or [])
                if miss:
                    add("product_merchant", uid, url, "thiếu " + ", ".join(miss))
            elif type_ == U.PRODUCT:
                add("product_no_schema", uid, url, "có microdata Product, chưa có JSON-LD" if d.get("micro_product")
                    else "không thấy dữ liệu cấu trúc Product")
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

    for h in sc.get("host") or []:
        if h["level"] == "high":
            add("host_dup", None, h["url"], h["problem"])
        elif h["level"] == "medium":
            add("host_redirect", None, h["url"], h["problem"])
    if (sc.get("robots") or {}).get("error"):
        add("robots_error", None, urljoin(cfg.site_url, "/robots.txt"), sc["robots"]["error"])
    for b in sc.get("bots") or []:
        if b["kind"] == "search" and (not b["home"] or b["blocked"]):
            add("ai_search_blocked", None, f"{b['bot']}",
                f"{b['use']}: " + ("chặn cả trang chủ" if not b["home"] else f"chặn {b['blocked']}/{b['total']} trang")
                + (f" ({b['rule']})" if b["rule"] else ""))
    scanned = set(page_status)
    for u in SC.sitemap_urls(con, cfg.site_url):
        st_ = state(u)
        if not st_:
            continue
        if st_[0] is None or is_blocked(st_[0]):
            unknown["sitemap"] += 1
        elif st_[0] >= 400:
            add("sitemap_broken", None, u, f"trả {st_[0]}")
        elif 300 <= st_[0] < 400:
            add("sitemap_redirect", None, u, f"chuyển {st_[0]}", want=f"thay bằng {short(st_[1] or '')}")
        elif u in scanned:
            d_ = page_data.get(u) or {}
            rob = f"{d_.get('robots', '')} {d_.get('x_robots', '')}"
            can = (d_.get("canonicals") or [d_.get("canonical")])[0]
            if "noindex" in rob:
                add("sitemap_noindex", None, u, "noindex")
            elif can and _norm(can) != _norm(u):
                add("sitemap_noindex", None, u, f"canonical → {short(can)}")

    types = {uid_: t for uid_, _, _, _, _, _, _, t in rows}
    ignored_keys = ignored(con)
    checks = []
    for k, v in found.items():
        for p in v:
            p["type"] = types.get(p["url_id"]) or ""
        keep = [p for p in v if (k, p["url"]) not in ignored_keys]
        skip = [p for p in v if (k, p["url"]) in ignored_keys]
        if not keep and not skip:
            continue
        unit = "URL" if k in SITE_CODES else "link" if k in ("link_broken", "link_redirect") else "trang"
        checks.append({"code": k, "level": CHECKS[k][0], "name": CHECKS[k][1], "fix": CHECKS[k][2], "pages": keep,
                       "ignored": skip, "site": k in SITE_CODES, "unit": unit})
    checks = [c for c in checks if c["pages"] or c["ignored"]]
    checks.sort(key=lambda c: (_ORDER[c["level"]], -len(c["pages"])))
    ignored_checks = [c for c in checks if not c["pages"]]  # mọi dòng đã bỏ qua: chỉ còn để xem lại
    checks = [c for c in checks if c["pages"]]
    bad = {p["url_id"] for c in checks if c["level"] == "high" and not c["site"] for p in c["pages"]}
    datas = list(page_data.values())
    meta = {"pages": sum(1 for _, _, st, *_ in rows if st == 200),
            "fmt": any("canonicals" in d for d in datas), "schema": any("ld_blocks" in d for d in datas),
            "products": sum(1 for d in datas if d.get("products")),
            "merchant": any("shipping" in (d.get("products") or [{}])[0] for d in datas if d.get("products")),
            "unknown": unknown}
    return {"checks": checks, "ignored_checks": ignored_checks, "pages": len(rows), "healthy": len(rows) - len(bad),
            "run": last_run(con, done=True), "meta": meta, "scanned": sorted(page_status)}
