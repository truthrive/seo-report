"""Audit backlink: việc cần xử lý, rút ra từ các danh sách đã lấy (backlinks.lists), không gọi thêm API.

Mỗi mục: {"key", "level" (high | medium | info | ok), "title", "count", "why", "action", "cols", "rows"}.
- Link spam mới (điểm spam của link ≥ SPAM_FLAG) → xuất file disavow cho Google.
- Link trỏ về trang lỗi (404 / 410…) → đặt redirect 301 để giữ giá trị link.
- Link vừa mất trong 30 ngày → liên hệ xin đặt lại.
- Anchor có điểm spam cao; cơ cấu anchor (từ khóa chiếm quá nửa là dấu hiệu tối ưu quá mức).
- Website link quá dày (≥ HEAVY_LINKS backlink: thường là link đặt trên mọi trang).
- Link trỏ về trang đang chuyển hướng (301 / 308): vẫn được tính, nên đổi link sang URL mới nếu xin được.
Ngưỡng là quy ước hay dùng, không phải quy định của Google.
"""
import re
import unicodedata

SPAM_FLAG = 50        # điểm spam của một link (0–100)
ANCHOR_SPAM = 30      # điểm spam trung bình của một anchor
HEAVY_LINKS = 20      # số backlink từ một website
KEYWORD_SHARE = 0.5   # anchor từ khóa chiếm quá tỷ lệ này (tính theo số website dùng)
# mục kiểm tra nằm ở danh sách (tab) nào: audit đi theo dữ liệu của chính danh sách đó
CHECK_TAB = {"spam": "changes", "lost": "changes", "broken": "pages", "redirect": "pages",
             "anchor_spam": "anchors", "anchor_mix": "anchors", "heavy": "domains"}


def matches(key: str, item: dict, brand_terms: list[str] | None = None) -> bool:
    """Dòng của danh sách có thuộc mục kiểm tra `key` không (bấm mục kiểm tra = lọc bảng của tab theo điều kiện này)."""
    status = item.get("status") or 200
    return {
        "spam": lambda: not item.get("lost") and (item.get("spam") or 0) >= SPAM_FLAG,
        "lost": lambda: bool(item.get("lost")),
        "broken": lambda: status >= 400,
        "redirect": lambda: 300 <= status < 400,
        "anchor_spam": lambda: (item.get("spam") or 0) >= ANCHOR_SPAM,
        "anchor_mix": lambda: anchor_type(item.get("anchor") or "", brand_terms or []) == "keyword",
        "heavy": lambda: (item.get("backlinks") or 0) >= HEAVY_LINKS,
    }.get(key, lambda: True)()


def fold(text: str) -> str:
    """Bỏ dấu, chữ thường: "Tâm Đức" → "tam duc"."""
    t = unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower().strip()


def anchor_type(anchor: str, brand_terms: list[str]) -> str:
    """Loại anchor: url | brand | empty | keyword. brand_terms đã bỏ dấu."""
    a = fold(anchor)
    if not a:
        return "empty"
    if re.match(r"^(https?://|www\.)", a) or re.search(r"\.(com|vn|net|org)(\.vn)?(/|$)", a):
        return "url"
    flat = a.replace(" ", "")
    if any(t and (t in a or t.replace(" ", "") in flat) for t in brand_terms):
        return "brand"
    return "keyword"


def disavow(lists: dict, generated: str = "") -> str:
    """Nội dung file disavow (định dạng của Google): một dòng "domain:..." cho mỗi website có link spam."""
    doms = sorted({x["domain_from"] for x in (lists.get("changes") or {}).get("items", [])
                   if not x["lost"] and (x.get("spam") or 0) >= SPAM_FLAG and x.get("domain_from")})
    head = [f"# Disavow do SEO Report tạo {generated}".rstrip(),
            f"# Website có link điểm spam >= {SPAM_FLAG} (DataForSEO). Xem lại từng dòng trước khi nộp cho Google."]
    return "\n".join(head + [f"domain:{d}" for d in doms]) + "\n"


def audit(lists: dict, brand_terms: list[str]) -> list[dict]:
    changes = (lists.get("changes") or {}).get("items", [])
    domains = (lists.get("domains") or {}).get("items", [])
    anchors = (lists.get("anchors") or {}).get("items", [])
    pages = (lists.get("pages") or {}).get("items", [])
    out = []

    if "changes" in lists:
        spam = [x for x in changes if not x["lost"] and (x.get("spam") or 0) >= SPAM_FLAG]
        out.append({
            "key": "spam", "level": "high" if spam else "ok", "title": "Link spam mới",
            "count": len(spam), "unit": "link", "disavow": bool(spam),
            "why": f"Link mới trong 30 ngày có điểm spam từ {SPAM_FLAG}/100: thường từ trang bán backlink hàng loạt, "
                   "có thể bị Google coi là thao túng.",
            "action": "Xem lại từng website; website rõ là spam thì đưa vào file disavow và nộp ở công cụ Disavow "
                      "của Google Search Console.",
            "cols": [("domain_from", "Website"), ("anchor", "Anchor"), ("spam", "Spam"), ("first_seen", "Thấy ngày")],
            "rows": sorted(spam, key=lambda x: -(x.get("spam") or 0))})
        lost = [x for x in changes if x["lost"]]
        out.append({
            "key": "lost", "level": "medium" if lost else "ok", "title": "Link vừa mất", "count": len(lost),
            "unit": "link",
            "why": "Link không còn trong 30 ngày qua: trang nguồn đã xóa link, đổi link hoặc trang bị gỡ.",
            "action": "Link từ website tốt (uy tín cao, không spam): liên hệ chủ website xin đặt lại link.",
            "cols": [("domain_from", "Website"), ("anchor", "Anchor"), ("url_to", "Trang đích"),
                     ("last_seen", "Mất ngày")],
            "rows": sorted(lost, key=lambda x: -(x.get("domain_rank") or 0))})

    if "pages" in lists:
        broken = [x for x in pages if (x.get("status") or 200) >= 400]
        out.append({
            "key": "broken", "level": "high" if broken else "ok", "title": "Link trỏ về trang lỗi",
            "count": len(broken), "unit": "trang",
            "why": "Website khác vẫn link về các trang này nhưng trang trả lỗi (404…): giá trị của link bị mất.",
            "action": "Đặt redirect 301 từ từng trang lỗi về trang đang có nội dung gần nhất.",
            "cols": [("page", "Trang lỗi"), ("status", "Mã lỗi"), ("domains", "Website trỏ về"),
                     ("backlinks", "Backlink")],
            "rows": sorted(broken, key=lambda x: -(x.get("domains") or 0))})
        moved = [x for x in pages if 300 <= (x.get("status") or 200) < 400]
        out.append({
            "key": "redirect", "level": "info" if moved else "ok", "title": "Link trỏ về trang đang chuyển hướng",
            "count": len(moved), "unit": "trang",
            "why": "Trang cũ đã chuyển (301 / 308) sang URL mới: link vẫn được tính nhưng qua một bước chuyển.",
            "action": "Không gấp. Với website quan trọng, xin họ đổi link sang URL mới.",
            "cols": [("page", "Trang cũ"), ("status", "Mã"), ("domains", "Website trỏ về"),
                     ("backlinks", "Backlink")],
            "rows": sorted(moved, key=lambda x: -(x.get("domains") or 0))})

    if "anchors" in lists:
        bad = [x for x in anchors if (x.get("spam") or 0) >= ANCHOR_SPAM]
        out.append({
            "key": "anchor_spam", "level": "medium" if bad else "ok", "title": "Anchor có điểm spam cao",
            "count": len(bad), "unit": "anchor",
            "why": f"Anchor có điểm spam trung bình từ {ANCHOR_SPAM}/100: thường là mẫu link spam hàng loạt "
                   "(ví dụ “Backlinks for …”).",
            "action": "Xem website dùng các anchor này ở danh sách Link mới / mất; website spam thì đưa vào disavow.",
            "cols": [("anchor", "Anchor"), ("domains", "Website dùng"), ("spam", "Spam")],
            "rows": sorted(bad, key=lambda x: -(x.get("domains") or 0))})
        tot = sum(x.get("domains") or 0 for x in anchors)
        mix: dict[str, int] = {}
        for x in anchors:
            t = anchor_type(x["anchor"], brand_terms)
            mix[t] = mix.get(t, 0) + (x.get("domains") or 0)
        kw = mix.get("keyword", 0) / tot if tot else 0
        out.append({
            "key": "anchor_mix", "level": "medium" if kw > KEYWORD_SHARE else "ok",
            "title": "Cơ cấu anchor", "count": round(kw * 100), "unit": "% từ khóa",
            "why": "Anchor chứa từ khóa chiếm quá nửa là dấu hiệu tối ưu quá mức; hồ sơ tự nhiên có nhiều anchor "
                   "thương hiệu và URL.",
            "action": "Link mới nên dùng anchor thương hiệu / URL nhiều hơn." if kw > KEYWORD_SHARE else
                      "Ổn: anchor từ khóa chưa chiếm quá nửa.",
            "mix": {k: round(v / tot * 100) if tot else 0 for k, v in mix.items()}, "cols": [], "rows": []})

    if "domains" in lists:
        heavy = [x for x in domains if (x.get("backlinks") or 0) >= HEAVY_LINKS]
        out.append({
            "key": "heavy", "level": "info" if heavy else "ok", "title": "Website link quá dày",
            "count": len(heavy), "unit": "website",
            "why": f"Một website có từ {HEAVY_LINKS} backlink về site: thường là link đặt ở chân trang / thanh bên "
                   "trên mọi trang.",
            "action": "Nếu là đối tác thật thì giữ, nên để nofollow; nếu không rõ nguồn thì xem xét disavow.",
            "cols": [("domain", "Website"), ("backlinks", "Backlink"), ("rank", "Uy tín"), ("spam", "Spam")],
            "rows": sorted(heavy, key=lambda x: -(x.get("backlinks") or 0))})

    order = {"high": 0, "medium": 1, "info": 2, "ok": 3}
    return sorted(out, key=lambda c: order[c["level"]])
