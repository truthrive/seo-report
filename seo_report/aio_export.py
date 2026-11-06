"""File Excel của trang AI Overview: số theo tuần, từng từ khóa (lần check mới nhất) và thay đổi so với lần trước.
Áp theo bộ từ khóa đang chọn (set_id None = mọi bộ)."""
import io

from openpyxl import Workbook

from . import aio as AO
from .export import INT, _sheet

CHANGE_TEXT = {"new_mention": "Mới được nhắc tên", "lost_mention": "Mất nhắc tên", "new_cite": "Mới được trích",
               "lost_cite": "Mất trích"}


def _ref(r) -> str:
    if isinstance(r, dict):
        return r.get("url") or r.get("domain") or r.get("title") or ""
    return str(r)


def build(con, cfg, set_id: int | None = None, weeks: int = 26) -> bytes:
    d = AO.dashboard(con, cfg, weeks=weeks, set_id=set_id)
    bs, own = d["brands"], d["own"]
    wb = Workbook()
    wb.remove(wb.active)
    cols = [("Tuần (bắt đầu)", 14, None), ("Đã check", 10, INT), ("Có AI Overview", 14, INT),
            ("Đọc được chữ", 13, INT), ("Có nguồn trích", 14, INT), (f"{own['name']} được nhắc", 16, INT),
            (f"{own['name']} được trích", 16, INT)]
    others = [b for b in bs if not b["own"]]
    cols += [(f"{b['name']} được trích", 16, INT) for b in others]
    _sheet(wb, "Theo tuần", cols,
           [[str(w["week"]), w["checked"], w["aio"], w["texted"], w["reffed"], w["brands"][own["id"]]["mention"],
             w["brands"][own["id"]]["cite"], *[w["brands"][b["id"]]["cite"] for b in others]] for w in d["weeks"]])
    rows = AO.keyword_rows(con, cfg, set_id)

    def yn(v):
        return "" if v is None else ("Có" if v else "Không")
    _sheet(wb, "Từ khóa", [("Từ khóa", 34, None), ("Vị trí", 8, INT), ("Ngày check", 12, None),
                           ("Có AI Overview", 14, None), (f"{own['name']} được nhắc", 16, None),
                           (f"{own['name']} được trích", 16, None), ("Thương hiệu được nhắc", 34, None),
                           ("Thương hiệu được trích", 34, None), ("Nguồn AI trích", 70, None),
                           ("Nội dung AI Overview", 90, None)],
           [[r["keyword"], r["rank"], r["date"] or "", yn(r["aio"]) if r["date"] else "", yn(r["own_mentioned"]),
             yn(r["own_cited"]) if r["aio"] else "", ", ".join(r["mentioned"]), ", ".join(r["cited"]),
             "\n".join(_ref(x) for x in r["refs"]), (r["text"] or "")[:32000]] for r in rows])
    ch = AO.changes(con, cfg, set_id)
    _sheet(wb, "Thay đổi", [("Thay đổi", 20, None), ("Từ khóa", 34, None), ("Lần check này", 14, None),
                            ("Lần trước", 14, None)],
           [[CHANGE_TEXT[k], x["keyword"], x["date"], x["prev_date"]] for k in CHANGE_TEXT for x in ch[k]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
