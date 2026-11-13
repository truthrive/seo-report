"""Toàn bộ backlink đang còn của website, mỗi link một dòng (DataForSEO Backlinks `backlinks`, mode as_is).

- Lấy cùng lượt "Lấy số backlink" (tự động theo lịch hoặc bấm "Lấy số mới"): mỗi lượt gọi tối đa 1.000 link, lấy tới
  CAP link (uy tín cao trước). Giá: 0,024 USD mỗi lượt gọi + 0,000036 USD mỗi link.
- Giữ KEEP lần lấy gần nhất: so hai lần để ra link mới / link mất của từng link (không tốn thêm tiền).
- Các bảng tổng (website, anchor, trang đích) và mục audit lọc từ danh sách này để xem link cụ thể.
- Nhập thêm file backlink xuất từ Semrush (`backlink_imports`): gộp với danh sách DataForSEO (link trùng giữ một dòng,
  ghi cả hai nguồn), dùng chung bảng, audit, xuất file. Link mới / mất giữa hai lần lấy chỉ tính trên DataForSEO.
"""
import json
import sqlite3
from datetime import datetime, timezone

PAGE = 1000                     # link mỗi lượt gọi (tối đa của DataForSEO)
CAP = 5000                      # tối đa link mỗi lần lấy
KEEP = 6                        # số lần lấy giữ lại
COST_TASK, COST_ROW = 0.024, 0.000036

SCHEMA = """
CREATE TABLE IF NOT EXISTS backlink_link_runs (
    site TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    total INTEGER,                 -- tổng backlink DataForSEO có (có thể hơn số đã lấy khi vượt CAP)
    cost REAL NOT NULL,
    items TEXT NOT NULL,           -- JSON [link đã rút gọn, xem slim()]
    PRIMARY KEY (site, fetched_at)
);
CREATE TABLE IF NOT EXISTS backlink_imports (
    site TEXT NOT NULL,
    source TEXT NOT NULL,          -- semrush
    imported_at TEXT NOT NULL,
    file_name TEXT,
    by_user TEXT,
    lost INTEGER NOT NULL DEFAULT 0,   -- số link file ghi là đã mất (không đưa vào danh sách)
    items TEXT NOT NULL,           -- JSON [link dạng slim(), thêm "src", "ascore", "sitewide"]
    PRIMARY KEY (site, source)
);
"""
SOURCES = {"dfs": "DataForSEO", "semrush": "Semrush"}


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def estimate(n_links: int | None) -> float:
    """Giá ước tính một lần lấy (n_links: số backlink lần trước / số tổng; chưa biết: coi như 1.000)."""
    n = min(max(n_links or PAGE, 1), CAP)
    return round(-(-n // PAGE) * COST_TASK + n * COST_ROW, 4)


def key(x: dict) -> str:
    return f"{x.get('u_from')}|{x.get('u_to')}|{x.get('type') or ''}"


def slim(it: dict) -> dict:
    """Một link của DataForSEO → các trường tool dùng (tên ngắn để file nhỏ)."""
    kw = it.get("ranked_keywords_info") or {}
    host = (it.get("domain_from") or "").lower().removeprefix("www.")
    return {
        "u_from": it.get("url_from") or "", "d_from": host, "title": " ".join(str(it.get("page_from_title") or "")
                                                                           .split())[:200],
        "u_to": it.get("url_to") or "", "anchor": " ".join(str(it.get("anchor") or "").split())[:300],
        "pre": " ".join(str(it.get("text_pre") or "").split())[-120:],
        "post": " ".join(str(it.get("text_post") or "").split())[:120],
        "follow": bool(it.get("dofollow")),
        "attrs": [a for a in (it.get("attributes") or []) if a in ("nofollow", "sponsored", "ugc", "noopener",
                                                                   "noreferrer", "external")],
        "type": it.get("item_type") or "anchor", "alt": it.get("alt") or "",
        "loc": it.get("semantic_location") or "", "same": it.get("links_count") or 1,
        "rank": it.get("rank") or 0, "p_rank": it.get("page_from_rank") or 0, "d_rank": it.get("domain_from_rank") or 0,
        "spam": it.get("backlink_spam_score") or 0, "lang": it.get("page_from_language") or "",
        "country": it.get("domain_from_country") or "", "ip": it.get("domain_from_ip") or "",
        "platform": list(it.get("domain_from_platform_type") or []),
        "ext": it.get("page_from_external_links"), "st_from": it.get("page_from_status_code"),
        "st_to": it.get("url_to_status_code"), "redir": it.get("url_to_redirect_target") or "",
        "broken": bool(it.get("is_broken")), "indirect": bool(it.get("is_indirect_link")),
        "kw10": kw.get("page_from_keywords_count_top_10") or 0, "kw100": kw.get("page_from_keywords_count_top_100") or 0,
        "first": (it.get("first_seen") or "")[:10] or None, "last": (it.get("last_seen") or "")[:10] or None,
        "original": bool(it.get("original")),
    }


def fetch(con, site: str, client, target: str, log=print) -> float:
    """Lấy toàn bộ backlink đang còn (tới CAP), lưu một lần lấy, bỏ lần cũ quá KEEP. Trả chi phí."""
    from .backlinks import _by
    ensure_tables(con)
    items, cost, total, offset = [], 0.0, None, 0
    while offset < CAP:
        res, c = client._live("backlinks", {
            "target": target, "mode": "as_is", "limit": min(PAGE, CAP - offset), "offset": offset,
            "backlinks_status_type": "live", "include_subdomains": True, "rank_scale": "one_thousand",
            "order_by": ["rank,desc"]})
        cost += c
        total = res.get("total_count") if total is None else total
        got = res.get("items") or []
        items += [slim(x) for x in got]
        offset += len(got)
        if len(got) < PAGE or (total is not None and offset >= total):
            break
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        con.execute("INSERT OR REPLACE INTO backlink_link_runs VALUES (?, ?, ?, ?, ?)",
                    (site, now, total, cost, json.dumps(items, ensure_ascii=False)))
        con.execute("INSERT INTO backlink_runs (run_at, site, kind, cost, by_user) VALUES (?, ?, 'links', ?, ?)",
                    (now, site, cost, _by()))
        old = [r[0] for r in con.execute("SELECT fetched_at FROM backlink_link_runs WHERE site = ? "
                                         "ORDER BY fetched_at DESC", (site,)).fetchall()[KEEP:]]
        for at in old:
            con.execute("DELETE FROM backlink_link_runs WHERE site = ? AND fetched_at = ?", (site, at))
    log(f"Đã lấy {len(items)} backlink cụ thể" + (f" / {total}" if total and total > len(items) else "") + ".")
    return cost


def latest(con, site: str) -> dict | None:
    """Danh sách link đang dùng: lần lấy DataForSEO mới nhất gộp với file đã nhập (Semrush).
    {"fetched_at", "total", "items" (mỗi link có "src": ["dfs"] / ["semrush"] / cả hai), "prev": lần DataForSEO
    trước | None, "imports": [{"source", "imported_at", "file_name", "count", "lost"}]}."""
    cur = _dfs_latest(con, site)
    imps = imports(con, site)
    if not imps:
        return _enrich(con, site, cur)
    if cur is None:
        cur = {"fetched_at": imps[0]["imported_at"], "total": None, "items": [], "prev": None}
    for x in cur["items"]:
        x.setdefault("src", ["dfs"])
    by_key = {(_norm_url(x["u_from"]), _page(x["u_to"])): x for x in cur["items"]}
    for imp in imps:
        for x in imp.pop("items"):
            k = (_norm_url(x["u_from"]), _page(x["u_to"]))
            if k in by_key:  # cùng link ở cả hai nguồn: giữ số DataForSEO, ghi thêm nguồn + điểm Semrush
                y = by_key[k]
                if imp["source"] not in y["src"]:
                    y["src"] = y["src"] + [imp["source"]]
                y.setdefault("ascore", x.get("ascore"))
                if x.get("sitewide"):
                    y["sitewide"] = True
            else:
                by_key[k] = x
                cur["items"].append(x)
    cur["imports"] = imps
    return _enrich(con, site, cur)


def _enrich(con, site: str, cur: dict | None) -> dict | None:
    """Bổ sung IP / quốc gia / ascore website cho link còn thiếu, từ file Referring domains (Semrush) của website."""
    if not cur:
        return cur
    try:
        from . import semrush as SR
        info = SR.own_domain_info(con, site)
    except sqlite3.Error:
        return cur
    if not info:
        return cur
    for x in cur["items"]:
        d = info.get(x["d_from"])
        if d is None:
            continue
        if not x.get("ip") and d.get("ip"):
            x["ip"] = d["ip"]
        if not x.get("country") and d.get("country"):
            x["country"] = d["country"]
        x.setdefault("d_ascore", d.get("ascore"))
    return cur


def _norm_url(u: str) -> str:
    u = (u or "").split("#")[0]
    for p_ in ("https://", "http://"):
        u = u.removeprefix(p_)
    return u.removeprefix("www.").rstrip("/").lower()


def _dfs_latest(con, site: str) -> dict | None:
    """Lần lấy DataForSEO mới nhất: {"fetched_at", "total", "items", "prev": {"fetched_at", "items"} | None}."""
    ensure_tables(con)
    rows = con.execute("SELECT fetched_at, total, items FROM backlink_link_runs WHERE site = ? "
                       "ORDER BY fetched_at DESC LIMIT 2", (site,)).fetchall()
    if not rows:
        return None
    cur = {"fetched_at": rows[0][0], "total": rows[0][1], "items": json.loads(rows[0][2]), "prev": None}
    if len(rows) > 1:
        cur["prev"] = {"fetched_at": rows[1][0], "items": json.loads(rows[1][2])}
    return cur


def diff(cur: list[dict], prev: list[dict] | None) -> tuple[list[dict], list[dict]]:
    """(link mới so với lần trước, link mất so với lần trước); chưa có lần trước: ([], [])."""
    if prev is None:
        return [], []
    cur = [x for x in cur if "dfs" in (x.get("src") or ["dfs"])]  # link nhập từ file: không so giữa các lần lấy
    a, b = {key(x) for x in cur}, {key(x) for x in prev}
    return [x for x in cur if key(x) not in b], [x for x in prev if key(x) not in a]


def _page(u: str) -> str:
    u = (u or "").split("#")[0]
    for p in ("https://", "http://"):
        u = u.removeprefix(p)
    return u.removeprefix("www.").rstrip("/").lower()


def for_page(items: list[dict], url: str) -> list[dict]:
    """Link trỏ về một trang đích (bỏ http/https, www, dấu / cuối)."""
    p = _page(url)
    return [x for x in items if _page(x["u_to"]) == p]


def for_site(items: list[dict], dom: str) -> list[dict]:
    d = (dom or "").lower().removeprefix("www.")
    return [x for x in items if x["d_from"] == d or x["d_from"].endswith("." + d)]


def for_anchor(items: list[dict], anchor: str) -> list[dict]:
    a = " ".join(str(anchor or "").split()).lower()
    return [x for x in items if x["anchor"].lower() == a]


# ---------------------------------------------------------------- Google Safe Browsing (miễn phí, Google API key)

SB_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find?key="
SB_BATCH = 500                  # tối đa URL mỗi lần hỏi
SB_TYPES = {"MALWARE": "Mã độc", "SOCIAL_ENGINEERING": "Lừa đảo (phishing)",
            "UNWANTED_SOFTWARE": "Phần mềm không mong muốn", "POTENTIALLY_HARMFUL_APPLICATION": "Ứng dụng có hại"}


def _sb_query(key: str, urls: list[str], opener=None) -> dict[str, str]:
    """{url: loại nguy hiểm} cho các URL Google Safe Browsing đánh dấu."""
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    body = {"client": {"clientId": "seo-report", "clientVersion": "1.0"},
            "threatInfo": {"threatTypes": list(SB_TYPES), "platformTypes": ["ANY_PLATFORM"],
                           "threatEntryTypes": ["URL"], "threatEntries": [{"url": u} for u in urls]}}
    req = Request(SB_URL + key, data=json.dumps(body).encode(), method="POST",
                  headers={"Content-Type": "application/json"})
    try:
        with (opener or urlopen)(req, timeout=60) as r:
            data = json.loads(r.read() or b"{}")
    except HTTPError as e:
        try:
            msg = (json.loads(e.read()).get("error") or {}).get("message", "")
        except ValueError:
            msg = ""
        if e.code == 403:  # API chưa bật trong project, hoặc khóa bị giới hạn chỉ dùng cho vài API
            raise RuntimeError("Google API key chưa được dùng Safe Browsing. Vào Google Cloud Console của project chứa "
                               "khóa: (1) APIs & Services → Library → bật “Safe Browsing API”; (2) Credentials → mở "
                               "API key → phần API restrictions, thêm “Safe Browsing API” vào danh sách được phép. Đợi "
                               "vài phút rồi bấm “Kiểm tra Safe Browsing” ở tab Tất cả backlink.") from e
        raise RuntimeError(f"Safe Browsing lỗi {e.code}: {msg[:200]}") from e
    return {m["threat"]["url"]: m.get("threatType", "") for m in data.get("matches") or []}


def safe_check(con, site: str, key: str, opener=None) -> dict:
    """Hỏi Google Safe Browsing cho trang đặt link + trang chủ website nguồn của lần lấy mới nhất; ghi "threat" vào
    từng link (rỗng: sạch). Trả {"checked", "flagged"}."""
    ensure_tables(con)
    lists = []  # (bảng, khóa, link)
    row = con.execute("SELECT fetched_at, items FROM backlink_link_runs WHERE site = ? ORDER BY fetched_at DESC "
                      "LIMIT 1", (site,)).fetchone()
    if row:
        lists.append(("run", row[0], json.loads(row[1])))
    for src, items in con.execute("SELECT source, items FROM backlink_imports WHERE site = ?", (site,)).fetchall():
        lists.append(("imp", src, json.loads(items)))
    if not lists:
        return {"checked": 0, "flagged": 0}
    all_items = [x for _, _, its in lists for x in its]
    urls = sorted({x["u_from"] for x in all_items if x.get("u_from")} | {f"http://{x['d_from']}/" for x in all_items})
    hits: dict[str, str] = {}
    for i in range(0, len(urls), SB_BATCH):
        hits.update(_sb_query(key, urls[i:i + SB_BATCH], opener))
    for x in all_items:
        x["threat"] = hits.get(x["u_from"]) or hits.get(f"http://{x['d_from']}/") or ""
    with con:
        for kind, k, its in lists:
            if kind == "run":
                con.execute("UPDATE backlink_link_runs SET items = ? WHERE site = ? AND fetched_at = ?",
                            (json.dumps(its, ensure_ascii=False), site, k))
            else:
                con.execute("UPDATE backlink_imports SET items = ? WHERE site = ? AND source = ?",
                            (json.dumps(its, ensure_ascii=False), site, k))
    return {"checked": len(urls), "flagged": sum(1 for x in all_items if x["threat"])}


# ---------------------------------------------------------------- nhập file backlink (Semrush)

SEMRUSH_COLS = {"Source url", "Target url", "Anchor"}


def _bool(v) -> bool:
    return str(v or "").strip().lower() in ("true", "1", "yes")


def _int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def detect(header: list[str]) -> str | None:
    """Nhận loại file theo dòng tiêu đề: "semrush" hoặc None."""
    cols = {h.strip() for h in header}
    if SEMRUSH_COLS <= cols and ("Page ascore" in cols or "Nofollow" in cols):
        return "semrush"
    return None


def parse_semrush(rows: list[dict], site: str) -> tuple[list[dict], int]:
    """Dòng CSV Semrush → (link còn dạng slim(), số link file ghi đã mất). Chỉ giữ link trỏ về website."""
    from urllib.parse import urlparse
    own = (urlparse(site if "://" in site else "https://" + site).netloc or site).lower().removeprefix("www.")
    out, lost = [], 0
    for r in rows:
        u_from, u_to = (r.get("Source url") or "").strip(), (r.get("Target url") or "").strip()
        host_to = (urlparse(u_to).netloc or "").lower().removeprefix("www.")
        if not u_from.startswith("http") or not (host_to == own or host_to.endswith("." + own)):
            continue
        if _bool(r.get("Lost link")):
            lost += 1
            continue
        attrs = [a for a, c in (("nofollow", "Nofollow"), ("sponsored", "Sponsored"), ("ugc", "Ugc")) if _bool(r.get(c))]
        x = slim({"domain_from": urlparse(u_from).netloc, "url_from": u_from, "url_to": u_to,
                  "page_from_title": r.get("Source title"), "anchor": r.get("Anchor"),
                  "dofollow": not _bool(r.get("Nofollow")), "attributes": attrs,
                  "item_type": "image" if _bool(r.get("Image")) else ("redirect" if _bool(r.get("Frame")) else "anchor"),
                  "page_from_external_links": _int(r.get("External links")),
                  "page_from_internal_links": _int(r.get("Internal links")),
                  "first_seen": (r.get("First seen") or "").strip() or None,
                  "last_seen": (r.get("Last seen") or "").strip() or None})
        x.update({"src": ["semrush"], "ascore": _int(r.get("Page ascore")), "sitewide": _bool(r.get("Sitewide")),
                  "new_mark": _bool(r.get("New link"))})
        out.append(x)
    return out, lost


def import_file(con, site: str, data: bytes, file_name: str = "", user: str = "") -> dict:
    """Đọc file CSV, nhận loại, lưu (thay lần nhập trước cùng nguồn). Trả {"source", "count", "lost", "domains",
    "new_domains" (website chưa có trong DataForSEO)}. Lỗi định dạng: ValueError."""
    import csv
    import io
    ensure_tables(con)
    text = None
    for enc in ("utf-8-sig", "utf-16", "cp1258", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = (text or "")[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text or ""), dialect=dialect)
    source = detect(reader.fieldnames or [])
    if source != "semrush":
        raise ValueError("Chưa nhận ra định dạng file: cần file CSV backlink xuất từ Semrush (Backlink Analytics → "
                         "Backlinks → Export), có các cột Source url, Target url, Anchor.")
    items, lost = parse_semrush(list(reader), site)
    if not items and not lost:
        raise ValueError("File không có link nào trỏ về website của dự án này.")
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    with con:
        con.execute("INSERT OR REPLACE INTO backlink_imports VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (site, source, _dt.now(_tz.utc).isoformat(timespec="seconds"), file_name, user, lost,
                     json.dumps(items, ensure_ascii=False)))
    dfs = {x["d_from"] for x in ((_dfs_latest(con, site) or {}).get("items") or [])}
    doms = {x["d_from"] for x in items}
    return {"source": source, "count": len(items), "lost": lost, "domains": len(doms),
            "new_domains": len(doms - dfs)}


def imports(con, site: str) -> list[dict]:
    ensure_tables(con)
    return [{"source": s_, "imported_at": at, "file_name": fn, "by": by, "lost": lost, "items": json.loads(its),
             "count": len(json.loads(its))}
            for s_, at, fn, by, lost, its in con.execute(
                "SELECT source, imported_at, file_name, by_user, lost, items FROM backlink_imports WHERE site = ?",
                (site,))]


def remove_import(con, site: str, source: str) -> None:
    ensure_tables(con)
    with con:
        con.execute("DELETE FROM backlink_imports WHERE site = ? AND source = ?", (site, source))


def check_targets(con, site: str, source: str = "semrush", fetcher=None, sleep=None, progress=None) -> dict:
    """Mã trạng thái các trang đích của link đã nhập (file Semrush không có): mở từng trang của website (không theo
    chuyển hướng), dùng lại số DataForSEO nếu đã có. Ghi st_to / redir / broken vào link. Trả {"pages", "broken",
    "redirect"}."""
    import time as _time
    from . import site_audit as SA
    fetcher = fetcher or SA.fetch
    sleep = sleep or _time.sleep
    ensure_tables(con)
    row = con.execute("SELECT items FROM backlink_imports WHERE site = ? AND source = ?", (site, source)).fetchone()
    if not row:
        return {"pages": 0, "broken": 0, "redirect": 0}
    items = json.loads(row[0])
    known = {}
    for x in ((_dfs_latest(con, site) or {}).get("items") or []):
        if x.get("st_to"):
            known[_page(x["u_to"])] = (x["st_to"], x.get("redir") or "")
    todo = sorted({x["u_to"].split("#")[0] for x in items if _page(x["u_to"]) not in known})
    for i, u in enumerate(todo, 1):
        r = fetcher(u)
        known[_page(u)] = (r.get("status"), r.get("final_url") or "")
        if progress:
            progress(i, len(todo))
        if i < len(todo):
            sleep(0.3)  # không làm nặng máy chủ website
    for x in items:
        st, redir = known.get(_page(x["u_to"]), (None, ""))
        x["st_to"], x["redir"] = st, redir if st and 300 <= st < 400 else ""
        x["broken"] = bool(st and st >= 400)
    with con:
        con.execute("UPDATE backlink_imports SET items = ? WHERE site = ? AND source = ?",
                    (json.dumps(items, ensure_ascii=False), site, source))
    pages = {_page(x["u_to"]): x["st_to"] for x in items}
    return {"pages": len(pages), "broken": sum(1 for v in pages.values() if v and v >= 400),
            "redirect": sum(1 for v in pages.values() if v and 300 <= v < 400)}
