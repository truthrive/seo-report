"""Mở từng trang chưa phân loại được bằng quy tắc và đọc schema (JSON-LD) để biết loại trang."""
import gzip
import re
import sqlite3
import time
from datetime import date, timedelta
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import urls as U

# Phải xin bản nén như trình duyệt: CDN của site chỉ lưu sẵn bản nén. Không xin nén thì server phải dựng
# lại trang, có trang mất hơn 30 giây.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SEOReportBot/1.0; noi-bo)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip",
    "Accept-Language": "vi-VN,vi;q=0.9",
}
JSONLD = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
TYPE = re.compile(r'"@type"\s*:\s*"([A-Za-z]+)"')


def type_from_html(html: str) -> tuple[str, str]:
    types = set(TYPE.findall(" ".join(JSONLD.findall(html))))
    if "Product" in types:
        return U.PRODUCT, ""
    if types & {"Article", "BlogPosting", "NewsArticle"}:
        return U.BLOG, ""
    if types & {"PostalAddress", "LocalBusiness", "Store", "Optician"}:
        return U.STORE, ""
    return U.CATEGORY, "Không có schema Product/Article, nên kiểm tra lại"


def detect(url: str, timeout: int = 20) -> tuple[str | None, str]:
    """Trả về (loại, ghi chú); loại None nghĩa là lỗi mạng, để lần sau thử lại."""
    try:
        resp = urlopen(Request(url, headers=HEADERS), timeout=timeout)
        final = U.normalize(resp.geturl())
        if final != url:
            return U.LEGACY, f"Chuyển hướng tới {final}"
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        html = body.decode("utf-8", "ignore")
    except HTTPError as e:
        return U.LEGACY, f"HTTP {e.code}"
    except (URLError, OSError, HTTPException) as e:  # hết thời gian chờ, mất kết nối giữa chừng…
        return None, str(e)
    return type_from_html(html)


def classify_pending(con: sqlite3.Connection, site: str, limit: int | None = None, delay: float = 0.3,
                     log=print, fetch=detect, sleep=time.sleep) -> int:
    """Phân loại các URL chưa có loại, URL nhiều click trước. Dừng giữa chừng thì lần sau làm tiếp."""
    since = (date.today() - timedelta(days=90)).isoformat()
    pending = con.execute(
        """SELECT u.id, u.url FROM urls u
           LEFT JOIN (SELECT pu.url_id, SUM(d.clicks) c FROM gsc_page_daily d
                      JOIN page_url pu ON pu.page_id = d.page_id WHERE d.date >= ? GROUP BY pu.url_id) m
             ON m.url_id = u.id
           WHERE u.site = ? AND u.type IS NULL ORDER BY COALESCE(m.c, 0) DESC""",
        (since, site),
    ).fetchall()
    if limit:
        pending = pending[:limit]
    done = 0
    for i, (url_id, url) in enumerate(pending, 1):
        type_, note = fetch(url)
        if type_ is not None:
            with con:
                con.execute("UPDATE urls SET type = ?, type_source = 'schema', note = ?, checked_at = ? WHERE id = ?",
                            (type_, note, U._now(), url_id))
            done += 1
        log(f"[{i}/{len(pending)}] {type_ or 'lỗi, thử lại sau'}: {url}", flush=True)
        sleep(delay)
    return done
