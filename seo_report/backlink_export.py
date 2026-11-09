"""File Excel của trang Backlink: tổng quan + lịch sử 12 tháng, audit (mỗi vấn đề một sheet chi tiết) và bốn danh
sách. Bảng phẳng, có bộ lọc, để lọc / pivot hoặc gửi khách.

which: "all" (cả file), "audit", hoặc một danh sách ("domains" | "changes" | "anchors" | "pages"; kèm các mục
kiểm tra của danh sách đó).
"""
import io

from openpyxl import Workbook

from . import backlink_audit as AU
from .export import INT, _sheet

LEVEL_TEXT = {"high": "Cần xử lý", "medium": "Nên xem", "info": "Tham khảo", "ok": "Ổn"}
ANCHOR_TEXT = {"brand": "Thương hiệu", "url": "URL", "keyword": "Từ khóa", "empty": "Trống / ảnh"}
LIST_SHEETS = {"domains": "Website trỏ về", "changes": "Link mới - mất", "anchors": "Anchor text",
               "pages": "Trang được link"}


def _overview(wb, latest: dict | None, site: str) -> None:
    now, prev = (latest or {}).get("now"), (latest or {}).get("prev")
    fields = [("referring_domains", "Website trỏ về"), ("referring_domains_nofollow", "Website chỉ có link nofollow"),
              ("backlinks", "Backlink"), ("rank", "Uy tín (0–1000)"), ("spam_score", "Điểm spam (0–100)"),
              ("broken_backlinks", "Link gãy")]
    rows = [[label, (now or {}).get(f), (prev or {}).get(f) if prev else None,
             (now[f] - prev[f]) if now and prev and now.get(f) is not None and prev.get(f) is not None else None]
            for f, label in fields]
    ws = _sheet(wb, "Tổng quan", [("Chỉ số", 30, None), (f"Lấy ngày {(now or {}).get('day', '')}", 16, INT),
                                  (f"Lần trước {(prev or {}).get('day', '')}", 16, INT), ("Thay đổi", 12, INT)], rows)
    ws.cell(row=len(rows) + 3, column=1, value=f"Website: {site} · nguồn DataForSEO Backlinks API")
    hist = (latest or {}).get("history") or []
    if hist:
        _sheet(wb, "Lịch sử 12 tháng", [("Tháng", 10, None), ("Website trỏ về", 14, INT), ("Backlink", 12, INT),
                                         ("Link mới", 10, INT), ("Link mất", 10, INT), ("Website mới", 12, INT),
                                         ("Website mất", 12, INT), ("Uy tín", 10, INT)],
               [[h["month"], h["referring_domains"], h["backlinks"], h["new_backlinks"], h["lost_backlinks"],
                 h["new_referring_domains"], h["lost_referring_domains"], h["rank"]] for h in hist])


def _audit(wb, checks: list[dict], title: str = "Audit") -> None:
    if not checks:
        return
    _sheet(wb, title, [("Mức", 12, None), ("Mục", 34, None), ("Số lượng", 10, None), ("Nên làm", 70, None),
                         ("Vì sao", 70, None)],
           [[LEVEL_TEXT[c["level"]], c["title"], f"{c['count']} {c['unit']}".replace(" %", "%"), c["action"], c["why"]]
            for c in checks])
    for c in checks:
        if not c["rows"]:
            continue
        name = f"Audit - {c['title']}"[:31]
        _sheet(wb, name, [(lab, 40 if k in ("anchor", "page", "url_to", "domain_from", "domain") else 14,
                           INT if k in ("domains", "backlinks", "spam", "rank", "status") else None)
                          for k, lab in c["cols"]],
               [[x.get(k) for k, _ in c["cols"]] for x in c["rows"]])


def _list(wb, kind: str, data: dict | None, brand_terms: list[str]) -> None:
    items = (data or {}).get("items", [])
    title = LIST_SHEETS[kind]
    if kind == "domains":
        _sheet(wb, title, [("Website", 34, None), ("Uy tín", 9, INT), ("Backlink", 10, INT), ("Trang link về", 12, INT),
                           ("Trang dofollow", 13, INT), ("Thấy lần đầu", 13, None), ("Điểm spam", 10, INT)],
               [[x["domain"], x["rank"], x["backlinks"], x["pages"], x["dofollow_pages"], x["first_seen"], x["spam"]]
                for x in items])
    elif kind == "changes":
        _sheet(wb, title, [("Trạng thái", 10, None), ("Website", 28, None), ("Trang link về", 60, None),
                           ("Tiêu đề trang", 40, None), ("Anchor", 40, None), ("Trang đích", 50, None),
                           ("Loại", 10, None), ("Điểm spam", 10, INT), ("Uy tín website", 13, INT),
                           ("Thấy lần đầu", 13, None), ("Thấy lần cuối", 13, None)],
               [["Mất" if x["lost"] else "Mới", x["domain_from"], x["url_from"], x.get("title") or "", x["anchor"] or "",
                 x["url_to"], "dofollow" if x["dofollow"] else "nofollow", x.get("spam"), x.get("domain_rank"),
                 x["first_seen"], x["last_seen"]] for x in items])
    elif kind == "anchors":
        _sheet(wb, title, [("Anchor", 50, None), ("Loại", 13, None), ("Website dùng", 13, INT), ("Backlink", 10, INT),
                           ("Điểm spam", 10, INT), ("Thấy lần đầu", 13, None)],
               [[x["anchor"] or "", ANCHOR_TEXT[AU.anchor_type(x["anchor"], brand_terms)], x["domains"],
                 x["backlinks"], x["spam"], x["first_seen"]] for x in items])
    else:
        _sheet(wb, title, [("Trang", 70, None), ("Tiêu đề", 50, None), ("Mã trạng thái", 13, INT),
                           ("Website trỏ về", 14, INT), ("Backlink", 10, INT), ("Uy tín", 9, INT)],
               [[x["page"], x.get("title") or "", x.get("status"), x["domains"], x["backlinks"], x["rank"]]
                for x in items])


def _drop_spam(wb) -> None:
    """File cho khách: bỏ cột / dòng có chữ "spam"."""
    for ws in wb.worksheets:
        head = [c.value for c in ws[1]] if ws.max_row else []
        for idx in sorted((i + 1 for i, v in enumerate(head) if v and "spam" in str(v).lower()), reverse=True):
            ws.delete_cols(idx)
        for r in range(ws.max_row, 1, -1):  # dòng "Điểm spam" của sheet Tổng quan
            v = ws.cell(row=r, column=1).value
            if v and "spam" in str(v).lower():
                ws.delete_rows(r)
        if ws.auto_filter and ws.auto_filter.ref:
            ws.auto_filter.ref = ws.dimensions


def build(lists: dict, latest: dict | None, brand_terms: list[str], site: str, which: str = "all",
          client: bool = False) -> bytes:
    """client: file cho khách hàng: không sheet audit (việc của team), không cột / dòng điểm spam."""
    wb = Workbook()
    wb.remove(wb.active)
    if which == "all":
        _overview(wb, latest, site)
    checks = [] if client else AU.audit(lists, brand_terms)
    if which in ("all", "audit"):
        _audit(wb, checks)
    for kind in LIST_SHEETS:
        if which in ("all", kind) and kind in lists:
            _list(wb, kind, lists[kind], brand_terms)
    if which in LIST_SHEETS:  # xuất một tab: kèm các mục kiểm tra của tab đó
        _audit(wb, [c for c in checks if AU.CHECK_TAB.get(c["key"]) == which], "Kiểm tra")
    if not wb.sheetnames:
        _sheet(wb, "Trống", [("Chưa có dữ liệu", 30, None)], [])
    if client:
        _drop_spam(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
