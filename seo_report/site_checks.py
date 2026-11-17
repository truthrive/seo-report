"""Kiểm tra cấp website cho Technical Audit, theo bộ tri thức "Technical Search & GEO Audit" (mã mục trong ngoặc):

- robots.txt chặn trang quan trọng (ACC-003) và chính sách bot AI (AI-001, AI-002, AI-003);
- HTTPS và một địa chỉ chính cho website (ACC-001, CANON-001);
- chuỗi chuyển hướng, vòng lặp, chuyển hướng tới trang lỗi (CANON-007);
- trạng thái URL mà link nội bộ, canonical và sitemap trỏ tới (LINK-002, CANON-003, DISC-002);
- Google Safe Browsing cho chính website (ACC-009).

Nguyên tắc (theo bộ tri thức): chỉ kết luận lỗi khi có bằng chứng; không lấy được dữ liệu thì ghi "chưa kiểm được" chứ
không coi là lỗi; chặn bot huấn luyện AI (GPTBot…) là chính sách của website, không phải lỗi, và không đồng nghĩa với
chặn ChatGPT Search. Miễn phí; mở URL chậm rãi (ít luồng, có nghỉ) để không làm nặng server của website.
"""
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request

from .crawl import HEADERS

STATUS_BUDGET = 1500   # số URL tối đa được mở mỗi lần quét (link nội bộ + canonical + sitemap), kiểm dần qua các tuần
STATUS_TTL_DAYS = 7    # trạng thái URL đã kiểm còn dùng được bao lâu
WORKERS = 3            # số luồng mở URL song song
PAUSE = 0.2            # mỗi luồng nghỉ giữa hai lần mở
MAX_HOPS = 6           # theo chuyển hướng tối đa bấy nhiêu bước
TIMEOUT = 15

# Bot AI: (tên trong robots.txt, dùng để làm gì, loại). "search": bot lấy nội dung để trả lời / trích dẫn khi người dùng
# tìm kiếm (chặn thì website khó xuất hiện ở đó); "train": bot lấy dữ liệu huấn luyện mô hình (chặn là chính sách).
AI_BOTS = (
    ("OAI-SearchBot", "ChatGPT Search", "search"),
    ("ChatGPT-User", "ChatGPT mở trang khi người dùng yêu cầu", "search"),
    ("PerplexityBot", "Perplexity", "search"),
    ("Claude-SearchBot", "Claude (tìm kiếm)", "search"),
    ("Bingbot", "Bing và Copilot", "search"),
    ("GPTBot", "OpenAI huấn luyện mô hình", "train"),
    ("ClaudeBot", "Anthropic huấn luyện mô hình", "train"),
    ("Google-Extended", "Gemini huấn luyện (không ảnh hưởng Google Search)", "train"),
    ("Applebot-Extended", "Apple Intelligence huấn luyện", "train"),
    ("CCBot", "Common Crawl (bộ dữ liệu huấn luyện)", "train"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_url_status (
    url TEXT PRIMARY KEY,
    status INTEGER,
    location TEXT,
    error TEXT,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_site (
    k TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    data TEXT NOT NULL
);
"""

SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|webp|avif|svg|ico|bmp|pdf|zip|rar|css|js|json|xml|txt|mp4|mp3|webm|woff2?|ttf)$",
                      re.I)
SKIP_PATH = ("/wp-admin", "/wp-login", "/wp-json", "/xmlrpc", "/feed", "/cdn-cgi/")


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def host_of(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


# ---------------------------------------------------------------- robots.txt (cách Google đọc)

def parse_robots(text: str) -> list[dict]:
    """[{"agents": [tên bot viết thường], "rules": [(cho phép?, mẫu đường dẫn)]}]. Nhiều dòng User-agent liền nhau
    chung một nhóm; "Disallow:" trống nghĩa là không cấm gì."""
    groups: list[dict] = []
    cur, last_ua = None, False
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if cur is None or not last_ua:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(v.lower())
            last_ua = True
        elif k in ("allow", "disallow"):
            last_ua = False
            if cur is not None and (v or k == "allow"):
                cur["rules"].append((k == "allow", v))
        else:  # Sitemap, Crawl-delay…: không thuộc nhóm nào
            last_ua = False
    return groups


def _rx(pattern: str) -> re.Pattern:
    """Mẫu robots.txt → regex: `*` là chuỗi bất kỳ, `$` ở cuối là hết URL."""
    end = pattern.endswith("$")
    body = re.escape(pattern[:-1] if end else pattern).replace(r"\*", ".*")
    return re.compile(body + ("$" if end else ""))


def robots_rule(groups: list[dict], agent: str, url: str) -> tuple[bool, str]:
    """(được phép?, dòng quyết định). Như Google: dùng nhóm ghi đúng tên bot (không có thì nhóm `*`); trong các dòng
    khớp, dòng dài nhất thắng, dài bằng nhau thì Allow thắng."""
    a = agent.lower()
    sel = [g for g in groups if a in g["agents"]] or [g for g in groups if "*" in g["agents"]]
    s = urlsplit(url)
    path = (s.path or "/") + (f"?{s.query}" if s.query else "")
    best = None  # (độ dài mẫu, cho phép?, dòng)
    for g in sel:
        for allow, pat in g["rules"]:
            if pat and _rx(pat).match(path):
                cand = (len(pat), allow, f"{'Allow' if allow else 'Disallow'}: {pat}")
                if best is None or cand[:2] > best[:2]:
                    best = cand
    return (True, "") if best is None or best[1] else (False, best[2])


def bot_policy(robots: dict, urls: list[str], home: str) -> list[dict]:
    """Từng bot AI: bị chặn ở trang chủ không, bị chặn bao nhiêu trang trong số trang đã quét."""
    if robots.get("groups") is None:
        return []
    out = []
    for name, use, kind in AI_BOTS:
        named = any(name.lower() in g["agents"] for g in robots["groups"])
        home_ok, rule = robots_rule(robots["groups"], name, home)
        blocked = [u for u in urls if not robots_rule(robots["groups"], name, u)[0]]
        out.append({"bot": name, "use": use, "kind": kind, "named": named, "home": home_ok, "rule": rule,
                    "blocked": len(blocked), "total": len(urls)})
    return out


# ---------------------------------------------------------------- mở URL

def _opener():
    from .site_audit import _opener as op  # mở không tự theo chuyển hướng
    return op


def head(url: str, timeout: int = TIMEOUT) -> dict:
    """Trạng thái một URL, không theo chuyển hướng: {"status", "location", "error"}. HEAD trước; server không nhận
    HEAD (405 / 501) thì mở bằng GET."""
    for method in ("HEAD", "GET"):
        try:
            with _opener().open(Request(url, method=method, headers=HEADERS), timeout=timeout) as r:
                return {"status": r.status, "location": None, "error": None}
        except HTTPError as e:
            if method == "HEAD" and e.code in (405, 501):
                continue
            loc = e.headers.get("Location") if e.headers else None
            return {"status": e.code, "location": urljoin(url, loc) if loc else None, "error": None}
        except (URLError, OSError, ValueError) as e:
            return {"status": None, "location": None, "error": str(getattr(e, "reason", e))[:160]}
    return {"status": None, "location": None, "error": "không mở được"}


def follow(url: str, opener=head, max_hops: int = MAX_HOPS) -> dict:
    """Đi theo chuyển hướng: {"chain": [(url, status)], "final", "status", "loop", "error"}."""
    chain, seen, cur = [], set(), url
    for _ in range(max_hops + 1):
        if cur in seen:
            return {"chain": chain, "final": cur, "status": None, "loop": True, "error": None}
        seen.add(cur)
        r = opener(cur)
        chain.append((cur, r["status"]))
        if r["error"] or r["status"] is None:
            return {"chain": chain, "final": cur, "status": None, "loop": False, "error": r["error"]}
        if 300 <= r["status"] < 400 and r["location"]:
            cur = r["location"]
            continue
        return {"chain": chain, "final": cur, "status": r["status"], "loop": False, "error": None}
    return {"chain": chain, "final": cur, "status": None, "loop": False, "error": f"quá {max_hops} bước chuyển hướng"}


def get_text(url: str, timeout: int = TIMEOUT) -> dict:
    """Nội dung chữ của một URL (robots.txt): {"status", "text", "error"}, theo chuyển hướng."""
    from urllib.request import urlopen
    try:
        with urlopen(Request(url, headers={**HEADERS, "Accept": "text/plain,*/*"}), timeout=timeout) as r:
            body = r.read(500_000)
            if r.headers.get("Content-Encoding") == "gzip":
                import gzip
                body = gzip.decompress(body)
            return {"status": r.status, "text": body.decode("utf-8", "ignore"), "error": None}
    except HTTPError as e:
        return {"status": e.code, "text": "", "error": None}
    except (URLError, OSError, ValueError) as e:
        return {"status": None, "text": "", "error": str(getattr(e, "reason", e))[:160]}


# ---------------------------------------------------------------- HTTPS và địa chỉ chính

def host_check(site: str, opener=head) -> list[dict]:
    """Bốn bản http / https × có / không www của trang chủ: bản chính phải trả 200, ba bản kia phải chuyển 301 / 308
    về bản chính. [{"url", "main", "chain", "final", "status", "error", "problem", "level"}]."""
    s = urlsplit(site)
    bare = host_of(site)
    main = urlunsplit((s.scheme or "https", s.netloc.lower(), "/", "", ""))
    out = []
    for scheme in ("https", "http"):
        for host in (bare, f"www.{bare}"):
            url = f"{scheme}://{host}/"
            r = follow(url, opener)
            first = r["chain"][0][1] if r["chain"] else None
            is_main = url == main
            problem, level = "", ""
            if r["error"] and not r["chain"][:-1]:
                if is_main or scheme == "https" and host == urlsplit(main).netloc:
                    problem, level = f"không mở được: {r['error']}", "high"
                # bản www / không www không tồn tại (không có DNS): không phải lỗi
            elif r["loop"]:
                problem, level = "chuyển hướng vòng lặp", "high"
            elif is_main:
                if first != 200:
                    problem, level = (f"địa chỉ chính trả {first}" + (f" → {r['final']}" if r["final"] != url else "")), \
                        "info" if r["status"] == 200 else "high"
            elif first == 200:
                problem, level = f"mở được trực tiếp (200), không chuyển về {main}", "high"
            elif first in (302, 303, 307):
                problem, level = f"chuyển hướng tạm thời ({first}); nên dùng 301", "medium"
            elif r["final"] != main:
                problem, level = f"chuyển về {r['final']} thay vì {main}", "medium"
            elif len(r["chain"]) > 2:
                problem, level = f"qua {len(r['chain']) - 1} bước chuyển hướng", "info"
            out.append({"url": url, "main": is_main, "chain": r["chain"], "final": r["final"], "status": r["status"],
                        "error": r["error"], "problem": problem, "level": level})
    return out


# ---------------------------------------------------------------- trạng thái URL (link nội bộ, canonical, sitemap)

def clean_link(href: str, base: str) -> str | None:
    """URL link nội bộ cần kiểm, hoặc None: bỏ link ra ngoài, link có tham số (thêm giỏ hàng, lọc…), file, trang quản
    trị; bỏ #mục."""
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
        return None
    u = urljoin(base, href.strip())
    s = urlsplit(u)
    if s.scheme not in ("http", "https") or host_of(u) != host_of(base) or s.query:
        return None
    path = s.path or "/"
    if SKIP_EXT.search(path) or path.startswith(SKIP_PATH):
        return None
    return urlunsplit((s.scheme, s.netloc.lower(), path, "", ""))


def known_statuses(con: sqlite3.Connection) -> dict[str, dict]:
    """Trạng thái đã kiểm còn hạn: {url: {"status", "location", "error"}}."""
    ensure(con)
    since = (datetime.now(timezone.utc) - timedelta(days=STATUS_TTL_DAYS)).isoformat(timespec="seconds")
    return {u: {"status": s, "location": loc, "error": err} for u, s, loc, err in con.execute(
        "SELECT url, status, location, error FROM audit_url_status WHERE checked_at >= ?", (since,))}


def check_statuses(con: sqlite3.Connection, urls: list[str], budget: int = STATUS_BUDGET, opener=head,
                   workers: int = WORKERS, pause: float = PAUSE, progress=None) -> int:
    """Mở các URL chưa có trạng thái còn hạn (theo thứ tự ưu tiên của `urls`, tối đa `budget`), lưu lại. Trả số URL
    đã mở."""
    have = known_statuses(con)
    todo = [u for u in dict.fromkeys(urls) if u not in have][:budget]
    if not todo:
        return 0

    def one(u):
        r = opener(u)
        if pause:
            time.sleep(pause)
        return u, r
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for u, r in ex.map(one, todo):
            with con:
                con.execute("INSERT OR REPLACE INTO audit_url_status VALUES (?, ?, ?, ?, ?)",
                            (u, r["status"], r["location"], r["error"], _now()))
            done += 1
            if progress and done % 25 == 0:
                progress(done, len(todo))
    return done


def sitemap_urls(con: sqlite3.Connection, site: str) -> list[str]:
    """URL trong sitemap ở lần đọc gần nhất (indexing.sync_sitemap)."""
    try:
        m = con.execute("SELECT MAX(last_seen) FROM sitemap_urls WHERE site = ?", (site,)).fetchone()[0]
    except sqlite3.OperationalError:
        return []
    if not m:
        return []
    return [u for (u,) in con.execute("SELECT url FROM sitemap_urls WHERE site = ? AND last_seen = ? ORDER BY url",
                                      (site, m))]


# ---------------------------------------------------------------- gom lại sau mỗi lần quét

def collect(con: sqlite3.Connection, site: str, pages: list[dict], key: str = "", opener=head, text_get=get_text,
            sb_query=None, log=print, progress=None) -> dict:
    """Chạy các kiểm tra cấp website sau khi đã quét xong các trang. pages: [{"url", "status", "final_url", "data"}]
    của lần quét. Lưu vào audit_site và trả về."""
    ensure(con)
    home = urlunsplit((urlsplit(site).scheme or "https", urlsplit(site).netloc.lower(), "/", "", ""))
    out: dict = {"at": _now()}

    # robots.txt
    r = text_get(urljoin(home, "/robots.txt"))
    if r["error"] or r["status"] is None or r["status"] >= 500:
        out["robots"] = {"status": r["status"], "error": r["error"] or f"máy chủ trả {r['status']}", "groups": None,
                         "text": ""}
    elif r["status"] >= 400:  # không có robots.txt: Google coi như được crawl tất cả
        out["robots"] = {"status": r["status"], "error": None, "groups": [], "text": "", "missing": True}
    else:
        out["robots"] = {"status": r["status"], "error": None, "groups": parse_robots(r["text"]),
                         "text": r["text"][:20000]}
    ok_urls = [p["url"] for p in pages if p.get("status") == 200]
    out["bots"] = bot_policy(out["robots"], ok_urls, home)
    log(f"Audit: robots.txt {out['robots']['status']}")

    # HTTPS và địa chỉ chính
    out["host"] = host_check(site, opener)

    # chuỗi chuyển hướng của các trang đã quét đang chuyển hướng
    out["redirects"] = {p["url"]: follow(p["url"], opener) for p in pages if p.get("status") and
                        300 <= p["status"] < 400}

    # trạng thái URL: link nội bộ (nhiều trang trỏ tới trước), canonical, rồi sitemap (kiểm dần qua các tuần)
    scanned = {p["url"] for p in pages}
    refs: dict[str, int] = {}
    for p in pages:
        for href, _ in (p["data"].get("links") or []):
            if href not in scanned:
                refs[href] = refs.get(href, 0) + 1
    canon = [c for p in pages for c in (p["data"].get("canonicals") or [])[:1]
             if c and c not in scanned and host_of(c) == host_of(site)]
    sm = sitemap_urls(con, site)
    queue = sorted(refs, key=lambda u: -refs[u]) + canon + [u for u in sm if u not in scanned]
    n = check_statuses(con, queue, opener=opener, progress=progress)
    known = known_statuses(con)
    out["links"] = {"targets": len(refs), "checked": sum(1 for u in refs if u in known)}
    out["sitemap"] = {"urls": len(sm), "checked": sum(1 for u in sm if u in known or u in scanned)}
    log(f"Audit: đã mở thêm {n} URL (link nội bộ / canonical / sitemap)")

    # Google Safe Browsing
    if key and ok_urls:
        try:
            if sb_query is None:
                from .backlink_links import _sb_query as sb_query
            flagged: dict[str, str] = {}
            urls = [home] + ok_urls
            for i in range(0, len(urls), 500):
                flagged.update(sb_query(key, urls[i:i + 500]))
            out["safe"] = {"checked": len(urls), "flagged": flagged, "error": None}
        except Exception as e:  # noqa: BLE001  (API chưa bật / khóa bị giới hạn: ghi "chưa kiểm được")
            out["safe"] = {"checked": 0, "flagged": {}, "error": str(e)[:300]}
    else:
        out["safe"] = {"checked": 0, "flagged": {}, "error": "chưa có Google API key" if not key else None}

    with con:
        con.execute("INSERT OR REPLACE INTO audit_site VALUES ('latest', ?, ?)",
                    (out["at"], json.dumps(out, ensure_ascii=False)))
    return out


def latest(con: sqlite3.Connection) -> dict | None:
    ensure(con)
    r = con.execute("SELECT data FROM audit_site WHERE k = 'latest'").fetchone()
    return json.loads(r[0]) if r else None
