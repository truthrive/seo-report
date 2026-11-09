"""AI viết brief một từ khóa (Tổng quan từ khóa). Chiến lược cho nhóm từ khóa: ai_strategy.py.

Kiểm tra đầu ra:
- Brief: câu hỏi FAQ lấy từ danh sách câu hỏi người dùng hay tìm; không bịa số (chỗ cần số ghi [điền …]); cắt độ dài.
Chỉ gọi khi bấm nút; kết quả lưu ai_drafts (kind "kw_brief")."""
import json
import re

from . import ai_http as AH
from . import ai_writer as AW
from . import keywords as K


SYSTEM_BRIEF = (
    "Bạn là biên tập viên SEO tiếng Việt, viết brief (dàn ý) để người viết làm một bài có thể lên top Google và được "
    "AI Overview trích.\n"
    "Quy tắc bắt buộc:\n"
    "- Bám ý định tìm kiếm và những gì trang kết quả Google đang cho thấy; câu hỏi FAQ lấy từ danh sách được cung cấp.\n"
    "- Không bịa số liệu, giá, thông số; chỗ cần thông tin riêng của doanh nghiệp ghi [điền …].\n"
    "- Chỉ trả về một đối tượng JSON hợp lệ, không thêm chữ nào ngoài JSON.")

BRIEF_SHAPE = """{
  "intent": "1 câu: người tìm muốn gì",
  "title": "tiêu đề SEO tối đa 60 ký tự",
  "meta": "meta description tối đa 155 ký tự",
  "outline": [{"h2": "...", "h3": ["..."], "note": "cần nói gì ở mục này"}],
  "must_cover": ["3-6 ý bắt buộc phải có"],
  "faq": ["3-5 câu hỏi nên trả lời, lấy từ danh sách câu hỏi"],
  "format": "dạng bài gợi ý (hướng dẫn / so sánh / danh sách / trang sản phẩm…)"
}"""


def _s(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def brief_prompt(d: dict, brand: str = "") -> str:
    sp = d.get("serp") or {}
    top = "\n".join(f"- {r['rank']}. {r['domain']} {r['url']}" for r in (sp.get("results") or [])[:10])
    aio = sp.get("aio") or {}
    refs = "\n".join(f"- {x.get('domain', '')}: {x.get('title') or ''}" for x in (aio.get("refs") or [])[:8])
    qs = "\n".join(f"- {q['keyword']}" for q in sorted(d.get("questions") or [],
                                                       key=lambda q: -(q.get("volume") or 0))[:12])
    vs = ", ".join(v["keyword"] for v in sorted(d.get("variations") or [], key=lambda v: -(v.get("volume") or 0))[:12])
    site = d.get("site") or {}
    lines = [f"Từ khóa: {d['keyword']}"]
    if brand:
        lines.append(f"Thương hiệu: {brand}")
    lines.append(f"Ý định (tool phân loại): {d.get('intent')}")
    if site.get("page") and site.get("position"):
        lines.append(f"Trang của site đang có hạng: {site['page']} (vị trí trung bình {site['position']:.0f})")
    else:
        lines.append("Site chưa có trang xếp hạng cho từ khóa này")
    lines.append(f"Biến thể hay được tìm: {vs or '(không có)'}")
    lines.append("Câu hỏi người dùng hay tìm:\n" + (qs or "- (không có)"))
    lines.append("Top kết quả Google:\n" + (top or "- (chưa có)"))
    if sp.get("features"):
        lines.append("Ô đặc biệt trên trang kết quả: " + ", ".join(sp["features"]))
    if refs:
        lines.append("AI Overview đang trích:\n" + refs)
    return "\n".join(lines) + "\n\nTrả về JSON đúng dạng:\n" + BRIEF_SHAPE


def check_brief(raw: dict) -> dict:
    out = {"intent": _s(raw.get("intent"), 240), "title": _s(raw.get("title"), 90), "meta": _s(raw.get("meta"), 200),
           "format": _s(raw.get("format"), 80),
           "outline": [{"h2": _s(o.get("h2"), 120),
                        "h3": [_s(x, 120) for x in (o.get("h3") or []) if _s(x, 120)][:6],
                        "note": _s(o.get("note"), 200)}
                       for o in raw.get("outline") or [] if isinstance(o, dict) and _s(o.get("h2"), 120)][:12],
           "must_cover": [_s(x, 160) for x in raw.get("must_cover") or [] if _s(x, 160)][:8],
           "faq": [_s(x, 160) for x in raw.get("faq") or [] if _s(x, 160)][:6]}
    return out


def write_brief(cfg, d: dict, brand: str = "", prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    prov = prov or AW.provider(cfg)
    text = AH.complete(prov["style"], prov["base"], prov["key"], prov["model"], brief_prompt(d, brand),
                       system=SYSTEM_BRIEF, max_tokens=2500, timeout=150, opener=opener)
    raw = _json(text)
    if raw is None:
        raise AH.AIError("AI không trả về đúng định dạng, bấm lại")
    out = check_brief(raw)
    if not out["outline"]:
        raise AH.AIError("AI chưa viết được dàn ý, bấm lại")
    return out, prov
