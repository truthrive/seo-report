"""Thực thể thương hiệu (Knowledge Graph), miễn phí:

- Google Knowledge Graph Search API (dùng Google API key ở Cài đặt tích hợp, 100.000 lượt / ngày miễn phí): thương
  hiệu của mình và đối thủ (danh sách thương hiệu ở trang AI Overview) đã là "thực thể" Google biết chưa, loại gì,
  mô tả gì, trỏ về website nào.
- Schema thương hiệu trên trang chủ (JSON-LD Organization / LocalBusiness): tên, logo, sameAs (hồ sơ mạng xã hội,
  Wikidata…), địa chỉ, điện thoại — tín hiệu để Google nối website với thực thể.
- Danh sách việc nên làm để thực thể mạnh hơn (hiện Knowledge Panel, được AI nhắc đúng tên).

Kiểm tra mỗi tuần (lịch hằng ngày) hoặc bấm Kiểm tra ngay."""
import gzip
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .crawl import HEADERS, JSONLD

API = "https://kgsearch.googleapis.com/v1/entities:search"
REFRESH_DAYS = 7
ORG_TYPES = {"Organization", "Corporation", "LocalBusiness", "Store", "Optician", "OnlineStore", "Brand",
             "Corporation", "MedicalBusiness", "HealthAndBeautyBusiness", "ProfessionalService"}
SOCIAL = (("facebook.com", "Facebook"), ("youtube.com", "YouTube"), ("tiktok.com", "TikTok"),
          ("instagram.com", "Instagram"), ("linkedin.com", "LinkedIn"), ("zalo.me", "Zalo"),
          ("shopee.vn", "Shopee"), ("wikidata.org", "Wikidata"), ("wikipedia.org", "Wikipedia"),
          ("x.com", "X"), ("twitter.com", "X"), ("pinterest.", "Pinterest"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS kg_checks (
    id INTEGER PRIMARY KEY,
    checked_at TEXT NOT NULL,
    brand_id INTEGER,
    brand TEXT NOT NULL,
    own INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,          -- found / none / error
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS kg_schema (
    id INTEGER PRIMARY KEY,
    checked_at TEXT NOT NULL,
    url TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    error TEXT
);
"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _host(u: str | None) -> str:
    return urlsplit(u or "").netloc.lower().removeprefix("www.")


def explain(e: Exception) -> str:
    """Lỗi API thành chữ dễ hiểu + cách sửa."""
    text = str(getattr(e, "body", "") or e)
    if "API_KEY_SERVICE_BLOCKED" in text or "are blocked" in text:
        return ("Knowledge Graph Search API đã bật nhưng Google API key của tool chưa được phép gọi nó. Vào Google "
                "Cloud Console → APIs & Services → Credentials → bấm đúng API key tool đang dùng (key có “PageSpeed "
                "Insights API” trong phần giới hạn) → API restrictions → mở danh sách, tích thêm “Knowledge Graph "
                "Search API” → OK → Save. Đợi vài phút rồi bấm Kiểm tra ngay.")
    if "has not been used" in text or "SERVICE_DISABLED" in text:
        return ("Google API key chưa được dùng Knowledge Graph Search API. Vào Google Cloud Console → APIs & "
                "Services → Library, tìm “Knowledge Graph Search API” → Enable; rồi Credentials → bấm API key "
                "đang dùng → API restrictions → thêm “Knowledge Graph Search API” → Save. Xong bấm Kiểm tra ngay.")
    if "API key not valid" in text or "API_KEY_INVALID" in text:
        return "Google API key không hợp lệ: kiểm tra lại ở Cài đặt tích hợp → Google API key."
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return "Đã hết lượt gọi Knowledge Graph hôm nay: thử lại ngày mai."
    return f"Chưa gọi được Knowledge Graph: {text[:200]}"


class ApiError(Exception):
    def __init__(self, code: int, body: str):
        super().__init__(f"HTTP {code}: {body[:300]}")
        self.code, self.body = code, body


def search(key: str, query: str, limit: int = 5, opener=urlopen) -> list[dict]:
    """Kết quả Knowledge Graph cho một tên: [{score, id, name, types, description, detail, detail_url, url,
    image}]."""
    url = f"{API}?" + urlencode({"query": query, "key": key, "limit": limit, "languages": "vi,en"})
    try:
        d = json.load(opener(url, timeout=20))
    except HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "ignore")) from None
    out = []
    for it in d.get("itemListElement", []):
        r = it.get("result", {})
        t = r.get("@type") or []
        det = r.get("detailedDescription") or {}
        out.append({"score": round(it.get("resultScore", 0) or 0, 1), "id": r.get("@id", ""), "name": r.get("name", ""),
                    "types": t if isinstance(t, list) else [t], "description": r.get("description", ""),
                    "detail": det.get("articleBody", ""), "detail_url": det.get("url", ""),
                    "url": r.get("url", ""), "image": (r.get("image") or {}).get("contentUrl", "")})
    return out


def pick(results: list[dict], brand: dict) -> dict | None:
    """Thực thể khớp thương hiệu: website trùng tên miền của thương hiệu, hoặc là tổ chức / cửa hàng có tên chứa tên
    thương hiệu. Không khớp thì None (Google chưa biết thương hiệu này, hoặc trùng tên thứ khác)."""
    from .keywords import fold
    domains = {d.lower().removeprefix("www.") for d in brand.get("domains", [])}
    names = {fold(n) for n in [brand["name"], *brand.get("aliases", [])] if fold(n)}
    for r in results:
        if _host(r["url"]) and _host(r["url"]) in domains:
            return {**r, "match": "domain"}
    for r in results:
        if set(r["types"]) & ORG_TYPES and any(n in fold(r["name"]) or fold(r["name"]) in n for n in names):
            return {**r, "match": "name"}
    return None


# ---- Schema trang chủ ----

def _objects(x) -> list[dict]:
    out = []
    if isinstance(x, dict):
        out.append(x)
        for v in x.values():
            out += _objects(v)
    elif isinstance(x, list):
        for v in x:
            out += _objects(v)
    return out


def _types(o: dict) -> set[str]:
    t = o.get("@type") or []
    return set(t if isinstance(t, list) else [t])


def _text(v) -> str:
    if isinstance(v, dict):
        return v.get("url") or v.get("contentUrl") or v.get("@id") or v.get("name") or ""
    if isinstance(v, list):
        return _text(v[0]) if v else ""
    return str(v or "")


def org_schema(html: str) -> dict:
    """Gộp các đối tượng Organization / LocalBusiness trong JSON-LD của trang thành một bản tóm tắt."""
    objs = []
    for block in JSONLD.findall(html):
        try:
            objs += _objects(json.loads(block.strip()))
        except ValueError:
            continue
    orgs = [o for o in objs if _types(o) & ORG_TYPES]
    out = {"found": bool(orgs), "types": sorted({t for o in orgs for t in _types(o)}), "name": "", "url": "",
           "logo": "", "same_as": [], "address": "", "telephone": "", "description": ""}
    for o in orgs:
        for k, field in (("name", "name"), ("url", "url"), ("logo", "logo"), ("telephone", "telephone"),
                         ("description", "description")):
            if not out[k] and o.get(field):
                out[k] = _text(o[field])
        if not out["address"] and o.get("address"):
            a = o["address"]
            a = a[0] if isinstance(a, list) and a else a
            out["address"] = ", ".join(str(a.get(f)) for f in ("streetAddress", "addressLocality", "addressRegion")
                                       if isinstance(a, dict) and a.get(f)) if isinstance(a, dict) else str(a)
        s = o.get("sameAs") or []
        out["same_as"] += [u for u in (s if isinstance(s, list) else [s]) if isinstance(u, str)]
    out["same_as"] = sorted(set(out["same_as"]))
    return out


def fetch_home(url: str, timeout: int = 25) -> str:
    resp = urlopen(Request(url, headers=HEADERS), timeout=timeout)
    body = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        body = gzip.decompress(body)
    return body.decode("utf-8", "ignore")


def social(same_as: list[str]) -> list[str]:
    names = []
    for u in same_as:
        for host, name in SOCIAL:
            if host in u.lower() and name not in names:
                names.append(name)
    return names


# ---- Chạy ----

def last_checked(con) -> str | None:
    ensure_tables(con)
    r = con.execute("SELECT MAX(checked_at) FROM kg_checks").fetchone()
    return r[0] if r else None


def run(con: sqlite3.Connection, cfg, key: str, opener=urlopen, home_fetch=fetch_home) -> dict:
    """Kiểm tra mọi thương hiệu trên Knowledge Graph và schema trang chủ. Trả {"brands", "found", "error"}."""
    from . import aio
    ensure_tables(con)
    at = _now()
    error = None
    found = 0
    bs = aio.brands(con, cfg)
    for b in bs:
        if not key:
            error = "Chưa có Google API key (Cài đặt tích hợp → Google API key)."
            break
        try:
            hit = pick(search(key, b["name"], opener=opener), b)
        except (ApiError, URLError, OSError, ValueError) as e:
            error = explain(e)
            break
        found += bool(hit)
        with con:
            con.execute("INSERT INTO kg_checks (checked_at, brand_id, brand, own, status, data) VALUES (?, ?, ?, ?, ?, ?)",
                        (at, b["id"], b["name"], int(b["own"]), "found" if hit else "none",
                         json.dumps(hit or {}, ensure_ascii=False)))
    if error:
        with con:
            con.execute("INSERT INTO kg_checks (checked_at, brand, status, data) VALUES (?, '', 'error', ?)",
                        (at, json.dumps({"error": error}, ensure_ascii=False)))
    home = cfg.site_url if cfg.site_url.startswith("http") else f"https://{cfg.site_url.split(':')[-1]}/"
    try:
        sch, err = org_schema(home_fetch(home)), None
    except (HTTPError, URLError, OSError, ValueError) as e:
        sch, err = {}, str(e)[:200]
    with con:
        con.execute("INSERT INTO kg_schema (checked_at, url, data, error) VALUES (?, ?, ?, ?)",
                    (at, home, json.dumps(sch, ensure_ascii=False), err))
    return {"brands": len(bs), "found": found, "error": error}


def refresh(con, cfg, today: date | None = None, force: bool = False, log=print) -> dict | None:
    """Lịch hằng ngày: kiểm tra khi lần gần nhất cũ hơn 7 ngày."""
    from .cwv import load_key
    ensure_tables(con)
    today = today or date.today()
    last = last_checked(con)
    if not force and last and datetime.fromisoformat(last).date() > today - timedelta(days=REFRESH_DAYS):
        return None
    r = run(con, cfg, load_key(cfg))
    log(f"Knowledge Graph: {r['found']}/{r['brands']} thương hiệu có thực thể" + (f" · {r['error']}" if r["error"] else ""))
    return r


# ---- Đọc kết quả ----

def latest(con, cfg) -> dict:
    """Lần kiểm tra gần nhất: {"at", "error", "brands": [...], "schema", "schema_error", "checks": [...]}."""
    ensure_tables(con)
    at = last_checked(con)
    rows = con.execute("SELECT brand_id, brand, own, status, data FROM kg_checks WHERE checked_at = ? "
                       "ORDER BY own DESC, id", (at,)).fetchall() if at else []
    error = next((json.loads(d).get("error") for _, _, _, s, d in rows if s == "error"), None)
    brands = [{"id": bid, "name": n, "own": bool(o), "found": s == "found", **json.loads(d or "{}")}
              for bid, n, o, s, d in rows if s != "error"]
    srow = con.execute("SELECT checked_at, url, data, error FROM kg_schema ORDER BY id DESC LIMIT 1").fetchone()
    schema = json.loads(srow[2]) if srow else None
    out = {"at": at, "error": error, "brands": brands, "schema": schema, "schema_error": srow[3] if srow else None,
           "home": srow[1] if srow else cfg.site_url}
    out["checks"] = checklist(con, cfg, out)
    return out


def checklist(con, cfg, r: dict) -> list[dict]:
    """Việc nên làm để thực thể thương hiệu mạnh: ok True / False / None (chưa biết)."""
    own = next((b for b in r["brands"] if b["own"]), None)
    sch = r["schema"] or {}
    site_host = _host(r["home"])
    nets = social(sch.get("same_as", []))
    try:
        gbp = con.execute("SELECT COUNT(*) FROM gbp_locations WHERE linked = 1").fetchone()[0]
    except sqlite3.Error:
        gbp = 0
    kg_known = None if r["error"] or own is None else own["found"]
    items = [
        ("kg", kg_known, "Google đã nhận ra thương hiệu là một thực thể (Knowledge Graph)",
         (f"{own.get('name')} · {', '.join(own.get('types', [])[:3])}" if own and own["found"] else
          "Chưa tìm thấy thực thể khớp tên / website của thương hiệu" if kg_known is False else
          "Chưa kiểm tra được Knowledge Graph (xem hướng dẫn phía trên)"),
         "Xây tín hiệu thực thể: schema Organization đầy đủ ở trang chủ, hồ sơ Google Business, mạng xã hội cùng tên "
         "và cùng link website, được báo / trang uy tín nhắc tên kèm link, tạo mục Wikidata."),
        ("kg_url", None if not (own and own["found"]) else _host(own.get("url")) == site_host,
         "Thực thể trỏ đúng website", own.get("url") or "Thực thể chưa có website" if own and own["found"] else "",
         "Đặt cùng một link website ở mọi hồ sơ (Google Business, Facebook, Wikidata…) và trong schema (url)."),
        ("kg_desc", None if not (own and own["found"]) else bool(own.get("description") or own.get("detail")),
         "Thực thể có mô tả", (own.get("detail") or own.get("description") or "Chưa có mô tả")[:160]
         if own and own["found"] else "",
         "Mô tả thường lấy từ Wikipedia / Wikidata: tạo mục Wikidata có mô tả tiếng Việt, liên kết website."),
        ("schema", bool(sch.get("found")) if r["schema"] is not None else None,
         "Trang chủ có schema Organization / LocalBusiness",
         ", ".join(sch.get("types", [])) or (r["schema_error"] or "Không thấy JSON-LD tổ chức"),
         "Thêm JSON-LD Organization (hoặc LocalBusiness / Optician cho cửa hàng) vào trang chủ."),
        ("schema_core", None if not sch.get("found") else bool(sch.get("name") and sch.get("logo") and sch.get("url")),
         "Schema có tên, logo, link website",
         " · ".join(f"{k}: {'có' if sch.get(k) else 'thiếu'}" for k in ("name", "logo", "url")) if sch.get("found")
         else "",
         "Điền đủ name (đúng tên thương hiệu), logo (ảnh vuông ≥ 112px) và url (trang chủ)."),
        ("same_as", None if not sch.get("found") else len(nets) >= 3, "Schema liệt kê hồ sơ mạng xã hội (sameAs)",
         (", ".join(nets) if nets else "Chưa có sameAs") if sch.get("found") else "",
         "Thêm sameAs: link Facebook, YouTube, TikTok, Instagram, LinkedIn… chính thức của thương hiệu (ít nhất 3)."),
        ("wikidata", None if not sch.get("found") else any(n in nets for n in ("Wikidata", "Wikipedia")),
         "Có Wikidata / Wikipedia", ", ".join(n for n in nets if n in ("Wikidata", "Wikipedia")) or "Chưa có",
         "Tạo mục Wikidata cho doanh nghiệp (tên, website, mạng xã hội, năm thành lập) rồi thêm vào sameAs: nguồn "
         "Google và AI hay dùng để hiểu thương hiệu."),
        ("nap", None if not sch.get("found") else bool(sch.get("address") and sch.get("telephone")),
         "Schema có địa chỉ và số điện thoại",
         " · ".join(x for x in (sch.get("address"), sch.get("telephone")) if x) or "Thiếu" if sch.get("found") else "",
         "Thêm address và telephone giống hệt hồ sơ Google Business (tên – địa chỉ – điện thoại thống nhất)."),
        ("gbp", gbp > 0 if gbp or _has_gbp(con) else None, "Đã gắn hồ sơ Google Business",
         f"{gbp} hồ sơ" if gbp else "Chưa gắn hồ sơ ở trang Local SEO",
         "Gắn hồ sơ Google Business ở trang Local SEO: hồ sơ đã xác minh là tín hiệu thực thể mạnh nhất cho cửa "
         "hàng."),
    ]
    return [{"code": c, "ok": ok, "title": t, "detail": d, "fix": f} for c, ok, t, d, f in items]


def _has_gbp(con) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE name = 'gbp_locations'").fetchone())
