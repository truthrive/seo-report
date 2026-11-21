"""Xây link chủ động (không tốn phí DataForSEO):

- needs(): "Trang cần link" — trang có từ khóa đang ở vị trí 4–20 (GSC 28 ngày, kèm từ khóa đang check rank) mà ít
  website trỏ về (theo danh sách "Trang được link" đã lấy). Thêm vài link là dễ lên Top nhất.
- Link đã xây: team ghi từng link đã đặt / mua (trang đặt link, trang đích, anchor, ngày, chi phí); tool tự tải trang
  đặt link để kiểm tra link còn không, có nofollow không, anchor còn đúng không (check_link / check_due).
- alerts(): cảnh báo cho chuông thông báo (mất link từ website mạnh, link spam mới tăng, link đã xây bị mất / đổi).

Tải trang bằng HTTP thường (miễn phí). Chỉ tải địa chỉ http(s) công khai (chặn localhost / mạng nội bộ).
"""
import ipaddress
import re
import socket
import sqlite3
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request

from . import safe_fetch as SF

SCHEMA = """
CREATE TABLE IF NOT EXISTS backlink_built (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    url_from TEXT NOT NULL,        -- trang đặt link
    url_to TEXT NOT NULL,          -- trang đích trên website
    anchor TEXT,                   -- anchor mong muốn (trống: không kiểm tra anchor)
    placed_on TEXT,                -- ngày đặt link (YYYY-MM-DD)
    cost REAL,                     -- chi phí (VNĐ)
    note TEXT,
    added_by TEXT,
    added_at TEXT NOT NULL,
    checked_at TEXT,
    http_status INTEGER,
    state TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | nofollow | anchor | lost | error
    rel TEXT,
    anchor_seen TEXT,
    detail TEXT,
    lost_at TEXT                   -- lần đầu thấy mất (để cảnh báo / biết mất từ khi nào)
);
CREATE INDEX IF NOT EXISTS idx_backlink_built_site ON backlink_built (site);
"""
STATES = {"pending": ("Chưa kiểm tra", "grey"), "ok": ("Còn link", "green"), "nofollow": ("Nofollow", "amber"),
          "anchor": ("Anchor khác", "amber"), "lost": ("Mất link", "red"), "error": ("Không tải được trang", "grey")}
CHECK_EVERY_DAYS = 7
NEED_WINDOW = 28        # ngày GSC
NEED_MIN_IMPR = 20      # lượt hiển thị tối thiểu của một từ khóa trong 28 ngày
NEED_POS = (4, 20)      # vùng vị trí "sắp lên Top"
STRONG_RANK = 300       # website trỏ về có uy tín (DataForSEO 0–1000) từ mức này là "website mạnh"
SPAM_FLAG = 50
SPAM_SPIKE = 5          # từ số link spam mới này (30 ngày) thì báo
MAX_BYTES = 3_000_000
UA = "Mozilla/5.0 (compatible; SEO-Report-LinkCheck/1.0)"


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(url: str) -> str:
    """So sánh URL: bỏ http(s), www., dấu / cuối, phần #; giữ ?query."""
    p = urlparse((url or "").strip())
    host = (p.netloc or "").lower().removeprefix("www.")
    path = (p.path or "/").rstrip("/") or "/"
    return host + path + (f"?{p.query}" if p.query else "")


def _host(url: str) -> str:
    return (urlparse(url or "").netloc or "").lower().removeprefix("www.")


def _date(text: str) -> str | None:
    text = (text or "").strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    try:
        return date.fromisoformat(text).isoformat() if text else None
    except ValueError:
        return None


def _cost(text) -> float | None:
    if text in (None, ""):
        return None
    t = re.sub(r"[^\d,.]", "", str(text))
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", t):
        t = re.sub(r"[.,]", "", t)
    try:
        return float(t.replace(",", ".")) if t else None
    except ValueError:
        return None


# ---------------------------------------------------------------- link đã xây: lưu
def parse_rows(text: str) -> list[dict]:
    """Mỗi dòng: trang đặt link | trang đích | anchor | ngày (dd/mm/yyyy) | chi phí — chỉ 2 cột đầu là bắt buộc."""
    out = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        parts = [x.strip() for x in line.split("|")] + [""] * 5
        out.append({"url_from": parts[0], "url_to": parts[1], "anchor": parts[2], "placed_on": parts[3],
                    "cost": parts[4]})
    return out


def add_links(con, site: str, rows: list[dict], user: str) -> dict:
    """Thêm link đã xây. Trả {"added": n, "bad": [lý do…]}. Trang đích phải thuộc website."""
    ensure_tables(con)
    own = _host(site)
    have = {(norm(a), norm(b)) for a, b in con.execute(
        "SELECT url_from, url_to FROM backlink_built WHERE site = ?", (site,))}
    res = {"added": 0, "bad": []}
    with con:
        for r in rows:
            uf, ut = (r.get("url_from") or "").strip(), (r.get("url_to") or "").strip()
            if not uf.startswith(("http://", "https://")) or not _host(uf):
                res["bad"].append(f"{uf or '(trống)'}: trang đặt link phải là địa chỉ http(s)")
                continue
            if ut and not ut.startswith(("http://", "https://")):
                ut = site.rstrip("/") + "/" + ut.lstrip("/")
            if not ut or _host(ut) != own:
                res["bad"].append(f"{uf}: trang đích phải thuộc {own}")
                continue
            if (norm(uf), norm(ut)) in have:
                res["bad"].append(f"{uf}: đã có trong danh sách")
                continue
            placed = _date(r.get("placed_on") or "")
            if (r.get("placed_on") or "").strip() and not placed:
                res["bad"].append(f"{uf}: ngày đặt chưa đúng (dd/mm/yyyy)")
                continue
            con.execute("INSERT INTO backlink_built (site, url_from, url_to, anchor, placed_on, cost, note, added_by, "
                        "added_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (site, uf, ut, (r.get("anchor") or "").strip() or None, placed, _cost(r.get("cost")),
                         (r.get("note") or "").strip() or None, user, _now()))
            have.add((norm(uf), norm(ut)))
            res["added"] += 1
    return res


def links(con, site: str) -> list[dict]:
    ensure_tables(con)
    cols = ("id", "url_from", "url_to", "anchor", "placed_on", "cost", "note", "added_by", "added_at", "checked_at",
            "http_status", "state", "rel", "anchor_seen", "detail", "lost_at")
    return [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {', '.join(cols)} FROM backlink_built WHERE site = ? ORDER BY id DESC", (site,))]


def delete_link(con, site: str, link_id: int) -> None:
    with con:
        con.execute("DELETE FROM backlink_built WHERE site = ? AND id = ?", (site, link_id))


def summary(rows: list[dict]) -> dict:
    by = {k: sum(1 for r in rows if r["state"] == k) for k in STATES}
    return {"total": len(rows), "cost": sum(r["cost"] or 0 for r in rows), "by": by,
            "alive": by["ok"] + by["nofollow"] + by["anchor"]}


# ---------------------------------------------------------------- link đã xây: kiểm tra
class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self._cur: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._cur = {"href": a.get("href") or "", "rel": (a.get("rel") or "").lower(), "text": ""}
            self.links.append(self._cur)
        elif tag == "img" and self._cur is not None and not self._cur["text"].strip():
            self._cur["text"] = a.get("alt") or ""

    def handle_endtag(self, tag):
        if tag == "a":
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur["text"] += data


def _public(url: str) -> bool:
    """Chỉ tải địa chỉ công khai: chặn localhost, IP nội bộ / link-local (tránh tool bị dùng để dò mạng trong)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except OSError:
        return True  # không phân giải được: để bước tải báo lỗi
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _fold(s: str) -> str:
    return " ".join((s or "").lower().split())


def find_link(html: str, base: str, url_to: str, anchor: str | None) -> dict:
    """Tìm link trỏ về url_to trong html: {"found", "rel", "anchor_seen", "state"}."""
    p = _Links()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 — HTML hỏng vẫn lấy được phần đã đọc
        pass
    want = norm(url_to)
    hits = [x for x in p.links if norm(urljoin(base, x["href"])) == want]
    if not hits:
        return {"found": False, "rel": "", "anchor_seen": "", "state": "lost"}
    # nhiều link cùng trỏ về: ưu tiên link dofollow, rồi link đúng anchor
    def follow(x):
        return not any(t in x["rel"].split() for t in ("nofollow", "ugc", "sponsored"))
    hits.sort(key=lambda x: (not follow(x), bool(anchor) and _fold(x["text"]) != _fold(anchor)))
    h = hits[0]
    state = "ok"
    if not follow(h):
        state = "nofollow"
    elif anchor and _fold(h["text"]) != _fold(anchor):
        state = "anchor"
    return {"found": True, "rel": h["rel"], "anchor_seen": " ".join(h["text"].split())[:200], "state": state}


def check_link(url_from: str, url_to: str, anchor: str | None = None, opener=None) -> dict:
    """Tải trang đặt link rồi tìm link. Trả {"state", "http_status", "rel", "anchor_seen", "detail"}."""
    if opener is None and not _public(url_from):
        return {"state": "error", "http_status": None, "rel": "", "anchor_seen": "",
                "detail": "Địa chỉ không công khai, tool không tải"}
    req = Request(url_from, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.5"})
    try:
        with (opener or SF.OPEN.open)(req, timeout=20) as r:  # mặc định: chỉ tới địa chỉ công khai, mọi chặng chuyển hướng
            status = getattr(r, "status", 200)
            raw = r.read(MAX_BYTES)
            ctype = r.headers.get("Content-Type", "") if hasattr(r, "headers") else ""
            final = r.geturl() if hasattr(r, "geturl") else url_from
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        if code and code >= 400:
            return {"state": "lost", "http_status": code, "rel": "", "anchor_seen": "",
                    "detail": f"Trang đặt link trả lỗi {code}"}
        return {"state": "error", "http_status": None, "rel": "", "anchor_seen": "",
                "detail": f"Không tải được trang: {str(e)[:120]}"}
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    html = raw.decode(m.group(1) if m else "utf-8", errors="replace")
    res = find_link(html, final, url_to, anchor)
    detail = {"ok": "Link còn, dofollow", "nofollow": f"Link còn nhưng rel=\"{res['rel']}\"",
              "anchor": f"Link còn nhưng anchor là “{res['anchor_seen']}”",
              "lost": "Không thấy link trên trang"}[res["state"]]
    return {"state": res["state"], "http_status": status, "rel": res["rel"], "anchor_seen": res["anchor_seen"],
            "detail": detail}


def save_check(con, link_id: int, res: dict) -> None:
    row = con.execute("SELECT state, lost_at FROM backlink_built WHERE id = ?", (link_id,)).fetchone()
    lost_at = row[1] if row else None
    if res["state"] == "lost" and not lost_at:
        lost_at = _now()
    elif res["state"] in ("ok", "nofollow", "anchor"):
        lost_at = None
    with con:
        con.execute("UPDATE backlink_built SET checked_at = ?, http_status = ?, state = ?, rel = ?, anchor_seen = ?, "
                    "detail = ?, lost_at = ? WHERE id = ?",
                    (_now(), res["http_status"], res["state"], res["rel"], res["anchor_seen"], res["detail"],
                     lost_at, link_id))


def check_due(con, site: str, every_days: int = CHECK_EVERY_DAYS, limit: int = 40, opener=None) -> int:
    """Kiểm tra các link chưa kiểm tra / đã quá `every_days` ngày. Trả số link đã kiểm tra."""
    ensure_tables(con)
    cut = (datetime.now(timezone.utc) - timedelta(days=every_days)).isoformat(timespec="seconds")
    rows = con.execute("SELECT id, url_from, url_to, anchor FROM backlink_built WHERE site = ? AND "
                       "(checked_at IS NULL OR checked_at < ?) ORDER BY checked_at IS NOT NULL, checked_at LIMIT ?",
                       (site, cut, limit)).fetchall()
    for lid, uf, ut, an in rows:
        save_check(con, lid, check_link(uf, ut, an, opener))
    return len(rows)


# ---------------------------------------------------------------- URL SEO (nhóm URL ở Quản lý URL)
def seo_urls(con, site: str) -> list[dict]:
    """URL thuộc các nhóm URL SEO: [{"url", "groups": [tên nhóm], "group_ids": [id]}], URL nhiều nhóm gộp một dòng."""
    out: dict[str, dict] = {}
    try:
        rows = con.execute("SELECT u.url, g.id, g.name FROM url_group_members m JOIN urls u ON u.id = m.url_id "
                           "JOIN url_groups g ON g.id = m.group_id WHERE g.site = ? ORDER BY g.id, u.url",
                           (site,)).fetchall()
    except sqlite3.Error:
        return []
    for url, gid, name in rows:
        r = out.setdefault(url, {"url": url, "groups": [], "group_ids": []})
        r["groups"].append(name)
        r["group_ids"].append(gid)
    return list(out.values())


def url_info(con, site: str, url: str, lists: dict, end: date) -> dict:
    """Backlink của một URL: website trỏ về (danh sách Trang được link), link đã xây trỏ vào, có phải trang cần link."""
    key = norm(url)
    pl = (lists or {}).get("pages") or {}
    dom = next((x.get("domains") for x in pl.get("items") or [] if norm(x.get("page") or "") == key), None)
    complete = bool(pl) and (pl.get("total") or 0) <= len(pl.get("items") or [])
    built = [r for r in links(con, site) if norm(r["url_to"]) == key]
    need = next((r for r in needs(con, site, lists, end, limit=10_000)["rows"] if norm(r["url"]) == key), None)
    return {"domains": dom if dom is not None else (0 if complete else None), "known": bool(pl),
            "built": built, "need": need}


# ---------------------------------------------------------------- trang cần link
def needs(con, site: str, lists: dict, end: date, limit: int = 40, only: set | None = None) -> dict:
    """Trang có từ khóa ở vị trí 4–20 (GSC 28 ngày + từ khóa đang check rank) xếp theo cơ hội: nhiều lượt hiển thị
    ở vùng 4–20 mà ít website trỏ về thì lên đầu. Trả {"rows", "complete", "window"}."""
    start = end - timedelta(days=NEED_WINDOW - 1)
    pages: dict[str, dict] = {}

    def page(url: str) -> dict:
        k = norm(url)
        return pages.setdefault(k, {"url": url, "impr": 0, "queries": [], "tracked": []})
    lo, hi = NEED_POS
    try:
        q = con.execute(
            "SELECT p.url, qq.text, SUM(d.impressions), SUM(d.clicks), SUM(d.position * d.impressions) / "
            "SUM(d.impressions) FROM gsc_query_daily d JOIN pages p ON p.id = d.page_id AND p.site = ? "
            "JOIN queries qq ON qq.id = d.query_id WHERE d.date BETWEEN ? AND ? GROUP BY d.page_id, d.query_id "
            "HAVING SUM(d.impressions) >= ?", (site, start.isoformat(), end.isoformat(), NEED_MIN_IMPR)).fetchall()
    except sqlite3.Error:
        q = []
    for url, text, impr, clicks, pos in q:
        if pos is not None and lo <= pos <= hi:
            pg = page(url)
            pg["impr"] += impr
            pg["queries"].append({"q": text, "pos": round(pos, 1), "impr": impr})
    try:  # từ khóa đang check rank: vị trí mới nhất 4–20, trang đang xếp hạng
        for kw, rank, rurl in con.execute(
                "SELECT k.keyword, c.rank, c.ranking_url FROM rank_keywords k JOIN rank_checks c ON c.keyword_id = k.id "
                "WHERE k.site = ? AND k.removed_at IS NULL AND c.check_date = (SELECT MAX(check_date) FROM rank_checks "
                "WHERE keyword_id = k.id)", (site,)):
            if rank is not None and lo <= rank <= hi and rurl:
                page(rurl)["tracked"].append({"q": kw, "pos": rank})
    except sqlite3.Error:
        pass
    pl = (lists or {}).get("pages") or {}
    linked = {norm(x.get("page") or ""): x.get("domains") or 0 for x in pl.get("items") or []}
    complete = bool(pl) and (pl.get("total") or 0) <= len(pl.get("items") or [])
    rows = []
    for k, pg in pages.items():
        if only is not None and k not in only:  # lọc theo nhóm URL SEO
            continue
        dom = linked.get(k)
        if dom is None and complete:
            dom = 0
        pg["queries"].sort(key=lambda x: -x["impr"])
        pg["tracked"].sort(key=lambda x: x["pos"])
        best = (pg["tracked"] or pg["queries"])[0]
        score = (pg["impr"] or 50 * len(pg["tracked"])) / (1 + (dom or 0))
        rows.append({"url": pg["url"], "domains": dom, "impr": pg["impr"], "n": len(pg["queries"]),
                     "tracked": len(pg["tracked"]), "best": best, "score": score})
    rows.sort(key=lambda r: -r["score"])
    return {"rows": rows[:limit], "total": len(rows), "complete": complete, "known": bool(pl),
            "window": (start, end)}


# ---------------------------------------------------------------- cảnh báo
def alerts(con, site: str, lists: dict) -> list[dict]:
    """[{level, key, title, detail, href}] cho chuông thông báo, từ dữ liệu đã lưu (không gọi API)."""
    out = []
    ch = (lists or {}).get("changes") or {}
    items = ch.get("items") or []
    stamp = (ch.get("fetched_at") or "")[:10]
    strong = [x for x in items if x.get("lost") and (x.get("domain_rank") or 0) >= STRONG_RANK]
    if strong:
        doms = sorted({x["domain_from"] for x in strong if x.get("domain_from")})
        out.append({"level": "high", "key": f"bl:strong_lost:{stamp}:{len(strong)}",
                    "title": f"Mất {len(strong)} link từ website mạnh",
                    "detail": ", ".join(doms[:3]) + (f" và {len(doms) - 3} website khác" if len(doms) > 3 else ""),
                    "href": "/backlink?tab=domains&xem=mat"})
    spam = [x for x in items if not x.get("lost") and (x.get("spam") or 0) >= SPAM_FLAG]
    if len(spam) >= SPAM_SPIKE:
        out.append({"level": "medium", "key": f"bl:spam:{stamp}:{len(spam)}",
                    "title": f"{len(spam)} link spam mới trong 30 ngày",
                    "detail": "Có thể bị đặt link xấu: xem lại và cân nhắc file disavow",
                    "href": "/backlink?tab=domains&xem=moi"})
    try:
        ensure_tables(con)
        bad = con.execute("SELECT id, url_from, state, checked_at FROM backlink_built WHERE site = ? AND "
                          "state IN ('lost', 'nofollow', 'anchor')", (site,)).fetchall()
    except sqlite3.Error:
        bad = []
    lost = [b for b in bad if b[2] == "lost"]
    changed = [b for b in bad if b[2] != "lost"]
    if lost:
        out.append({"level": "high", "key": "bl:built_lost:" + ",".join(str(b[0]) for b in lost),
                    "title": f"{len(lost)} link đã xây bị mất",
                    "detail": ", ".join(_host(b[1]) for b in lost[:3]), "href": "/backlink?tab=built"})
    if changed:
        out.append({"level": "medium", "key": "bl:built_changed:" + ",".join(f"{b[0]}{b[2]}" for b in changed),
                    "title": f"{len(changed)} link đã xây bị đổi (nofollow / anchor khác)",
                    "detail": ", ".join(_host(b[1]) for b in changed[:3]), "href": "/backlink?tab=built"})
    return out


# ---------------------------------------------------------------- link nội bộ
_STOP = {"có", "là", "gì", "và", "của", "cho", "không", "nào", "bao", "nhiêu", "nên", "the", "a", "ở", "đâu", "tại",
         "với", "được", "các", "những", "một", "khi", "thì"}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", (text or "").lower()) if len(w) > 1 and w not in _STOP}


def _query_rows(con, site: str, end: date, min_impr: int = 5) -> list[tuple]:
    start = end - timedelta(days=NEED_WINDOW - 1)
    try:
        return con.execute(
            "SELECT p.url, qq.text, SUM(d.impressions), SUM(d.clicks), SUM(d.position * d.impressions) / "
            "SUM(d.impressions) FROM gsc_query_daily d JOIN pages p ON p.id = d.page_id AND p.site = ? "
            "JOIN queries qq ON qq.id = d.query_id WHERE d.date BETWEEN ? AND ? GROUP BY d.page_id, d.query_id "
            "HAVING SUM(d.impressions) >= ?", (site, start.isoformat(), end.isoformat(), min_impr)).fetchall()
    except sqlite3.Error:
        return []


def internal_suggestions(con, site: str, target: str, end: date, k: int = 6) -> dict:
    """Trang của chính website nên đặt link nội bộ sang `target`: trang có click và hiện cho truy vấn cùng chủ đề với
    từ khóa của target. Độ liên quan tính theo từ chung, chữ càng hiếm trên site càng nặng (chữ có ở hầu hết truy vấn
    như "kính" gần như không tính). Trả {"anchor", "topic", "rows": [{"url", "clicks", "match", "score"}]}."""
    import math
    rows = _query_rows(con, site, end)
    tk = norm(target)
    agg: dict[str, list] = {}
    for url, q, imp, clicks, pos in rows:
        if norm(url) == tk:
            a = agg.setdefault(q, [0, 0.0])
            a[0] += imp
            a[1] += (pos or 0) * imp
    if not agg:
        return {"anchor": "", "topic": [], "rows": []}
    mine = sorted(((q, imp, pw / imp if imp else None) for q, (imp, pw) in agg.items()), key=lambda x: -x[1])
    lo, hi = NEED_POS
    near = [m for m in mine if m[2] is not None and lo <= m[2] <= hi] or mine
    anchor = near[0][0]
    topic = [m[0] for m in near[:5]]
    df: dict[str, int] = {}
    texts = {r[1] for r in rows}
    for t in texts:
        for w in _tokens(t):
            df[w] = df.get(w, 0) + 1
    n = max(len(texts), 1)

    def wt(w: str) -> float:
        return math.log(n / (1 + df.get(w, 0))) if df.get(w, 0) < n else 0.0
    want = []
    for q, imp, _ in near[:5]:
        tok = _tokens(q)
        tot = sum(wt(w) for w in tok)
        if tot > 0:
            want.append((tok, tot))
    pages: dict[str, dict] = {}
    for url, q, imp, clicks, pos in rows:
        if norm(url) == tk:
            continue
        pg = pages.setdefault(norm(url), {"url": url, "clicks": 0, "rel": 0.0, "match": ""})
        pg["clicks"] += clicks or 0
        qt = _tokens(q)
        for tok, tot in want:
            r = sum(wt(w) for w in qt & tok) / tot
            if r > pg["rel"]:
                pg["rel"], pg["match"] = r, q
    cands = [p for p in pages.values() if p["rel"] >= 0.45 and p["clicks"]]
    cands.sort(key=lambda p: -(p["rel"] * math.log(2 + p["clicks"])))
    return {"anchor": anchor, "topic": topic,
            "rows": [{"url": p["url"], "clicks": p["clicks"], "match": p["match"], "score": round(p["rel"], 2)}
                     for p in cands[:k]]}


def has_link(source: str, target: str, opener=None) -> bool | None:
    """Trang `source` (của website) đã có link sang `target` chưa (tải trang, miễn phí). None: không tải được."""
    res = check_link(source, target, None, opener)
    if res["state"] == "error" or (res["http_status"] or 200) >= 400:
        return None
    return res["state"] != "lost"


# ---------------------------------------------------------------- hiệu quả link đã xây
EFFECT_DAYS = 28        # so 28 ngày trước và sau ngày đặt link
EFFECT_MIN_DAYS = 14    # sau ngày đặt chưa đủ 14 ngày số liệu: chưa kết luận


def _page_ids(con, site: str, url: str) -> list[int]:
    key = norm(url)
    try:
        return [i for i, u in con.execute("SELECT id, url FROM pages WHERE site = ?", (site,)) if norm(u) == key]
    except sqlite3.Error:
        return []


def _page_period(con, ids: list[int], s: date, e: date) -> dict | None:
    if not ids or e < s:
        return None
    marks = ",".join("?" * len(ids))
    try:
        cl, im, pw, days = con.execute(
            f"SELECT SUM(clicks), SUM(impressions), SUM(position * impressions), COUNT(DISTINCT date) "
            f"FROM gsc_page_daily WHERE page_id IN ({marks}) AND date BETWEEN ? AND ?",
            (*ids, s.isoformat(), e.isoformat())).fetchone()
    except sqlite3.Error:
        return None
    n = (e - s).days + 1
    return {"clicks_day": (cl or 0) / n, "impr_day": (im or 0) / n, "pos": (pw / im) if im else None,
            "days": days or 0}


def effect(con, site: str, link: dict, end: date) -> dict:
    """Trang đích trước và sau ngày đặt link (GSC): {"status": wait | no_date | no_data | ok, "before", "after",
    "days_after", "pos_change" (dương = lên hạng), "clicks_change" (click/ngày)}. Số là của cả trang đích, có thể do
    nhiều nguyên nhân chứ không riêng link này."""
    if not link.get("placed_on"):
        return {"status": "no_date"}
    d0 = date.fromisoformat(link["placed_on"])
    ids = _page_ids(con, site, link["url_to"])
    after_end = min(end, d0 + timedelta(days=EFFECT_DAYS))
    days_after = (after_end - d0).days
    if days_after < EFFECT_MIN_DAYS:
        return {"status": "wait", "days_after": max(0, days_after), "ready_on": d0 + timedelta(days=EFFECT_MIN_DAYS)}
    before = _page_period(con, ids, d0 - timedelta(days=EFFECT_DAYS), d0 - timedelta(days=1))
    after = _page_period(con, ids, d0 + timedelta(days=1), after_end)
    if not before or not after or not before["impr_day"] or not after["impr_day"]:
        return {"status": "no_data"}
    pos_change = (before["pos"] - after["pos"]) if before["pos"] and after["pos"] else None
    return {"status": "ok", "before": before, "after": after, "days_after": days_after,
            "pos_change": pos_change, "clicks_change": after["clicks_day"] - before["clicks_day"]}


def effects_by_source(con, site: str, rows: list[dict], end: date) -> list[dict]:
    """Gộp theo website đặt link: số link, chi phí, số link đã đủ ngày đo, vị trí / click tăng trung bình."""
    out: dict[str, dict] = {}
    for r in rows:
        h = _host(r["url_from"])
        g = out.setdefault(h, {"host": h, "links": 0, "cost": 0.0, "measured": 0, "pos": 0.0, "clicks": 0.0})
        g["links"] += 1
        g["cost"] += r.get("cost") or 0
        ef = effect(con, site, r, end)
        if ef["status"] == "ok":
            g["measured"] += 1
            g["pos"] += ef["pos_change"] or 0
            g["clicks"] += ef["clicks_change"] * 30  # click / tháng
    for g in out.values():
        if g["measured"]:
            g["pos"] /= g["measured"]
            g["cost_per_click"] = (g["cost"] / g["clicks"]) if g["cost"] and g["clicks"] > 0 else None
    return sorted(out.values(), key=lambda g: -g["links"])


# ---------------------------------------------------------------- đối chiếu với danh sách toàn bộ backlink (DataForSEO)

DFS_GRACE_DAYS = 45      # sau chừng này ngày từ lúc đặt mà DataForSEO vẫn chưa thấy link: báo
DFS_STATES = {"found": ("Đã ghi nhận", "green"), "found_nofollow": ("Ghi nhận · nofollow", "amber"),
              "lost": ("Mất so với lần trước", "red"), "missing": ("Chưa ghi nhận", "amber"),
              "waiting": ("Chờ ghi nhận", "grey"), "none": ("Chưa có dữ liệu", "grey")}
UNRECORDED_LABELS = ("Textlink", "Báo PR", "PBN", "Web 2.0")  # link mới từ website gắn các nhãn này: có thể do team đặt
UNRECORDED_DAYS = 90
UNRECORDED_MAX_SPAM = 30
SPAM_TEXT = re.compile(r"backlink|telegram|tg @|casino|cbd|crosslink|seo rank|link build", re.I)


def dfs_match(rows: list[dict], data: dict | None, today: date | None = None) -> dict[int, dict]:
    """Đối chiếu link đã xây với danh sách backlink lần lấy gần nhất: {id: {"state", "first", "anchor", "dofollow"}}.
    state: found | found_nofollow | lost (có ở lần trước, lần này mất) | missing (đặt quá DFS_GRACE_DAYS ngày vẫn
    chưa thấy) | waiting (mới đặt, DataForSEO chưa kịp ghé) | none (chưa có danh sách)."""
    today = today or date.today()
    if not data:
        return {r["id"]: {"state": "none"} for r in rows}

    def index(items):
        out = {}
        for x in items:
            out.setdefault((norm(x["u_from"]), norm(x["u_to"])), x)
            out.setdefault((norm(x["u_from"]), _host(x["u_to"])), x)  # trang đích có thể khác chút (dấu ?, /)
        return out
    cur = index(data["items"])
    prev = index(data["prev"]["items"]) if data.get("prev") else {}
    seen_at = data["fetched_at"][:10]
    out = {}
    for r in rows:
        k1, k2 = (norm(r["url_from"]), norm(r["url_to"])), (norm(r["url_from"]), _host(r["url_to"]))
        x = cur.get(k1) or cur.get(k2)
        if x:
            out[r["id"]] = {"state": "found" if x["follow"] else "found_nofollow", "first": x.get("first"),
                            "anchor": x.get("anchor") or "", "dofollow": x["follow"], "at": seen_at}
        elif prev.get(k1) or prev.get(k2):
            out[r["id"]] = {"state": "lost", "at": seen_at}
        else:
            placed = date.fromisoformat(r["placed_on"]) if r.get("placed_on") else None
            old = placed is None or (date.fromisoformat(seen_at) - placed).days >= DFS_GRACE_DAYS
            out[r["id"]] = {"state": "missing" if old else "waiting", "at": seen_at}
    return out


def unrecorded(rows: list[dict], data: dict | None, labels: dict, today: date | None = None) -> list[dict]:
    """Link mới (thấy lần đầu trong UNRECORDED_DAYS ngày) từ website gắn nhãn Textlink / Báo PR / PBN / Web 2.0 mà
    chưa có trong Link đã xây: có thể team đặt mà quên ghi."""
    from . import site_labels as SL
    if not data:
        return []
    today = today or date.today()
    since = (today - timedelta(days=UNRECORDED_DAYS)).isoformat()
    have = {norm(r["url_from"]) for r in rows}
    out = []
    for x in data["items"]:
        labs = [lb for lb in SL.lookup(labels, x["d_from"]) if lb in UNRECORDED_LABELS]
        spammy = ((x.get("spam") or 0) >= UNRECORDED_MAX_SPAM or x.get("threat")  # link spam không phải team đặt
                  or (x.get("lang") or "vi") != "vi"  # team đặt link cho website Việt: trang nguồn tiếng Việt
                  or SPAM_TEXT.search(f"{x.get('anchor') or ''} {x.get('title') or ''}"))
        if labs and not spammy and (x.get("first") or "") >= since and norm(x["u_from"]) not in have:
            out.append({**x, "labels": labs})
    return sorted(out, key=lambda x: x.get("first") or "", reverse=True)


def dfs_alerts(con, site: str, data: dict | None) -> list[dict]:
    """Cảnh báo chuông: link đã xây mất trong dữ liệu DataForSEO, hoặc đặt lâu mà vẫn chưa được ghi nhận."""
    rows = links(con, site)
    if not rows or not data:
        return []
    m = dfs_match(rows, data)
    out = []
    lost = [r for r in rows if m[r["id"]]["state"] == "lost"]
    missing = [r for r in rows if m[r["id"]]["state"] == "missing"]
    if lost:
        out.append({"level": "high", "key": f"bl:built_dfs_lost:{data['fetched_at'][:10]}:{len(lost)}",
                    "title": f"{len(lost)} link đã xây không còn trong dữ liệu backlink",
                    "detail": ", ".join(_host(r["url_from"]) for r in lost[:3]) + " · có ở lần lấy trước, lần này mất",
                    "href": "/backlink?tab=built"})
    if missing:
        out.append({"level": "medium", "key": f"bl:built_dfs_missing:{data['fetched_at'][:10]}:{len(missing)}",
                    "title": f"{len(missing)} link đã xây đặt hơn {DFS_GRACE_DAYS} ngày vẫn chưa được ghi nhận",
                    "detail": ", ".join(_host(r["url_from"]) for r in missing[:3])
                    + " · trang đặt link có thể chưa được index hoặc link bị chặn",
                    "href": "/backlink?tab=built"})
    return out
