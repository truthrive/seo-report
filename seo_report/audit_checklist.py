"""Checklist của Technical Audit: các tiêu chí theo 10 hạng mục của bộ tiêu chuẩn "Technical Search & GEO Audit"
(mã mục ACC-003, LINK-002…), mỗi tiêu chí gom một hay nhiều mục kiểm tra của site_audit.

Trạng thái một tiêu chí (theo bộ tiêu chuẩn: PASS / FAIL / WARNING / UNKNOWN / NOT_APPLICABLE):
- "high" / "medium" / "info": có trang vướng mục kiểm tra ở mức đó (lấy mức nặng nhất);
- "ok": đã kiểm được và không trang nào vướng;
- "unknown": chưa kiểm được (chưa quét lại từ khi có mục này, thiếu dữ liệu, chưa có API key…);
- "na": không áp dụng (website không có trang sản phẩm…).
Không gọi mạng, không đọc DB: chỉ tính từ kết quả site_audit.findings và site_checks.latest."""

AREAS = (
    ("access", "Truy cập và robots"),
    ("index", "Index"),
    ("canon", "Canonical và chuyển hướng"),
    ("link", "Link nội bộ"),
    ("sitemap", "Sitemap"),
    ("content", "Tiêu đề và nội dung"),
    ("schema", "Schema"),
    ("perf", "Tốc độ và hạ tầng"),
    ("media", "Ảnh"),
    ("ai", "AI Search"),
)

# (hạng mục, mã, tên tiêu chí viết theo trạng thái đạt, các mục kiểm tra, điều kiện để kiểm được)
# điều kiện: "pages" (đã quét trang), "fmt" (lần quét có đủ dữ liệu mới: canonical, link, viewport…), "schema"
# (lần quét có đọc JSON-LD), "products" (có trang sản phẩm), "merchant" (đã đọc phí ship / đổi trả), "robots",
# "host", "links", "sitemap", "safe", "bots", "gsc" (có số Search Console)
CRITERIA = (
    ("access", "ACC-001", "HTTPS và một địa chỉ chính", ("host_dup", "host_redirect"), "host"),
    ("access", "ACC-003", "robots.txt không chặn trang quan trọng", ("robots_blocked", "robots_error"), "robots"),
    ("access", "ACC-006", "Máy chủ trả lời ổn định (không 5xx, không hết giờ chờ)", ("5xx", "error"), "pages"),
    ("access", "ACC-007", "Trang có traffic không trả lỗi 4xx", ("4xx",), "pages"),
    ("access", "ACC-009", "Google Safe Browsing không cảnh báo", ("unsafe",), "safe"),
    ("access", "", "Tool quét được website (không bị tường lửa chặn)", ("blocked",), "pages"),
    ("index", "INDEX-001", "Trang có traffic cho phép index", ("noindex",), "pages"),
    ("index", "INDEX-007", "Không chặn Google trích đoạn ngoài ý muốn", ("nosnippet", "data_nosnippet"), "fmt"),
    ("canon", "CANON-003", "Canonical đúng và trỏ tới trang hoạt động",
     ("canonical", "canonical_multi", "canonical_bad_target", "canonical_redirect", "canonical_missing"), "fmt"),
    ("canon", "CANON-007", "Chuyển hướng đi thẳng một bước tới trang hoạt động",
     ("redirect", "redirect_loop", "redirect_broken", "redirect_chain"), "pages"),
    ("link", "LINK-002", "Link nội bộ trỏ thẳng tới trang 200", ("link_broken", "link_redirect"), "links"),
    ("sitemap", "DISC-002", "Sitemap chỉ chứa URL 200, cho phép index",
     ("sitemap_broken", "sitemap_redirect", "sitemap_noindex"), "sitemap"),
    ("content", "RETR-004", "Tiêu đề có, riêng từng trang, độ dài hợp lý",
     ("no_title", "dup_title", "short_title", "long_title"), "pages"),
    ("content", "RETR-004", "Tiêu đề chứa từ khóa chính", ("kw_title",), "gsc"),
    ("content", "", "CTR không thấp bất thường so với vị trí", ("low_ctr",), "gsc"),
    ("content", "RETR-005", "Mô tả có, riêng từng trang, độ dài hợp lý", ("no_desc", "dup_desc", "bad_desc"), "pages"),
    ("content", "RETR-003", "Mỗi trang một thẻ H1", ("no_h1", "multi_h1"), "pages"),
    ("content", "RETR-001", "Bài viết đủ nội dung", ("thin",), "pages"),
    ("content", "INTL-001", "Khai báo ngôn ngữ trang (lang)", ("no_lang",), "fmt"),
    ("schema", "ENTITY-001", "Dữ liệu cấu trúc đúng cú pháp", ("schema_error",), "schema"),
    ("schema", "ENTITY-003", "Trang có dữ liệu cấu trúc phù hợp", ("no_schema",), "schema"),
    ("schema", "ENTITY-003", "Trang sản phẩm có schema Product đủ trường",
     ("product_no_schema", "product_bad", "product_nice"), "products"),
    ("schema", "", "Sản phẩm có sao đánh giá", ("product_no_rating",), "products"),
    ("schema", "", "Sản phẩm khai báo phí ship và đổi trả", ("product_merchant",), "merchant"),
    ("perf", "PERF-002", "Máy chủ phản hồi dưới 3 giây", ("slow",), "pages"),
    ("perf", "PERF-003", "Trang được nén (gzip / brotli)", ("no_gzip",), "fmt"),
    ("perf", "PERF-007", "Có thẻ viewport cho điện thoại", ("no_viewport",), "fmt"),
    ("media", "MEDIA-001", "Ảnh có mô tả (alt)", ("noalt",), "pages"),
    ("ai", "AI-001", "Bot tìm kiếm AI được vào (ChatGPT, Perplexity, Claude, Bing)", ("ai_search_blocked",), "bots"),
)

UNKNOWN_WHY = {
    "pages": "chưa quét lần nào",
    "fmt": "lần quét gần nhất chạy trước khi có mục này: quét lại để có số",
    "schema": "lần quét gần nhất chưa đọc dữ liệu cấu trúc: quét lại để có số",
    "merchant": "lần quét gần nhất chưa đọc phí ship / đổi trả: quét lại để có số",
    "robots": "chưa đọc được robots.txt",
    "host": "chưa kiểm: quét lại để có số",
    "links": "chưa kiểm link nội bộ: quét lại để có số",
    "sitemap": "chưa có danh sách URL trong sitemap (đọc ở URL & Index) hoặc chưa kiểm URL nào",
    "safe": "chưa kiểm được",
    "bots": "chưa đọc được robots.txt",
    "gsc": "chưa có số Search Console",
}
_RANK = {"high": 0, "medium": 1, "info": 2, "unknown": 3, "ok": 4, "na": 5}
LABEL = {"high": ("Cần sửa", "red"), "medium": ("Nên sửa", "amber"), "info": ("Tham khảo", "blue"),
         "ok": ("Đạt", "green"), "unknown": ("Chưa kiểm", "grey"), "na": ("Không áp dụng", "grey")}


def _ready(need: str, meta: dict, sc: dict) -> bool | None:
    """Kiểm được chưa: True / False (chưa kiểm) / None (không áp dụng)."""
    if need == "pages":
        return meta.get("pages", 0) > 0
    if need == "fmt":
        return bool(meta.get("fmt"))
    if need == "schema":
        return bool(meta.get("schema"))
    if need == "products":
        return None if meta.get("schema") and not meta.get("products") else bool(meta.get("products"))
    if need == "merchant":
        if meta.get("schema") and not meta.get("products"):
            return None
        return bool(meta.get("merchant"))
    if need == "gsc":
        return meta.get("pages", 0) > 0
    if not sc:
        return False
    if need == "robots":
        return (sc.get("robots") or {}).get("groups") is not None or bool((sc.get("robots") or {}).get("error"))
    if need == "host":
        return bool(sc.get("host"))
    if need == "links":
        return "links" in sc
    if need == "sitemap":
        s = sc.get("sitemap") or {}
        return bool(s.get("urls")) and bool(s.get("checked"))
    if need == "safe":
        return not (sc.get("safe") or {}).get("error")
    if need == "bots":
        return bool(sc.get("bots"))
    return False


def build(au: dict, sc: dict | None, meta: dict) -> list[dict]:
    """[{"key", "name", "rows": [{"code", "name", "status", "checks": [check…], "count", "why"}], "counts"}]."""
    by = {c["code"]: c for c in au.get("checks") or []}
    sc = sc or {}
    areas = []
    for key, name in AREAS:
        rows = []
        for area, code, title, checks, need in CRITERIA:
            if area != key:
                continue
            hit = [by[c] for c in checks if c in by]
            ready = _ready(need, meta, sc)
            if hit:
                status = min((c["level"] for c in hit), key=lambda lv: _RANK[lv])
            elif ready is None:
                status = "na"
            elif ready:
                status = "ok"
            else:
                status = "unknown"
            if need == "safe" and status == "unknown" and (sc.get("safe") or {}).get("error"):
                why = f"chưa kiểm được: {(sc['safe']['error'])[:140]}"
            else:
                why = UNKNOWN_WHY.get(need, "") if status == "unknown" else ""
            pages = {(p.get("url_id"), p["url"]) for c in hit for p in c["pages"]}
            rows.append({"code": code, "name": title, "status": status, "checks": hit, "codes": checks,
                         "count": len(pages),
                         "unit": hit[0].get("unit", "trang") if hit else "trang", "why": why, "need": need})
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        areas.append({"key": key, "name": name, "rows": rows, "counts": counts})
    return areas


def totals(areas: list[dict]) -> dict[str, int]:
    """Đếm tiêu chí theo trạng thái trên cả checklist."""
    out = {k: 0 for k in LABEL}
    for a in areas:
        for k, v in a["counts"].items():
            out[k] += v
    out["checked"] = sum(out[k] for k in ("high", "medium", "info", "ok"))
    return out


def priorities(au: dict, clicks: dict, limit: int = 5) -> list[dict]:
    """Việc nên làm trước: mục Cần sửa rồi Nên sửa, trong cùng mức thì mục ảnh hưởng nhiều click hơn trước (bộ tiêu
    chuẩn: mức nặng khác ưu tiên; ưu tiên tính cả phạm vi và độ quan trọng của trang)."""
    out = []
    for c in au.get("checks") or []:
        if c["level"] not in ("high", "medium"):
            continue
        ids = {p.get("url_id") for p in c["pages"] if p.get("url_id") is not None}
        cl = sum((clicks.get(i) or (0, 0))[0] for i in ids)
        out.append({"code": c["code"], "name": c["name"], "level": c["level"], "count": len(c["pages"]),
                    "unit": c.get("unit", "trang"), "clicks": cl})
    out.sort(key=lambda x: (_RANK[x["level"]], -x["clicks"], -x["count"]))
    return out[:limit]


def snapshot(au: dict) -> dict[str, list[str]]:
    """Kết quả gọn để so giữa hai lần quét: {mã mục: [URL]}."""
    return {c["code"]: sorted({p["url"] for p in c["pages"]}) for c in au.get("checks") or []}


def diff(cur: dict[str, list[str]], prev: dict[str, list[str]] | None, scanned: set[str],
         prev_scanned: set[str] | None = None) -> dict:
    """So với lần quét trước, đơn vị là dòng (trang × vấn đề):
    - "new": lỗi mới ở trang lần trước cũng được quét (thay đổi thật);
    - "first": lỗi ở trang lần đầu được quét (lần trước không có trong danh sách quét, không phải lỗi mới phát sinh) —
      chỉ tách được khi biết danh sách trang lần trước (prev_scanned);
    - "fixed": lỗi đã hết, chỉ tính trang vẫn được quét lần này (trang bỏ khỏi danh sách thì chưa biết đã sửa chưa).
    "first_pages": số trang lần đầu được quét."""
    if prev is None:
        return {"new": [], "first": [], "fixed": [], "first_pages": 0, "has_prev": False}
    new, first, fixed = [], [], []
    for code in set(cur) | set(prev):
        a, b = set(cur.get(code) or []), set(prev.get(code) or [])
        for u in sorted(a - b):
            (first if prev_scanned is not None and u in scanned and u not in prev_scanned else new).append((code, u))
        fixed += [(code, u) for u in sorted(b - a) if u in scanned or not u.startswith("http")]
    first_pages = len(scanned - prev_scanned) if prev_scanned is not None else 0
    return {"new": new, "first": first, "fixed": fixed, "first_pages": first_pages, "has_prev": True}
