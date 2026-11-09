"""AI viết nháp nội dung từ số liệu của tool. Việc đầu tiên: đoạn trả lời cho AI Overview (tab Việc nên làm).

- Chọn nhà cung cấp: cái đầu tiên đã nhập khóa theo thứ tự ORDER (Cài đặt tích hợp > Nhà cung cấp AI).
- Chỉ gọi khi người dùng bấm nút; bản nháp lưu vào file dữ liệu dự án (bảng ai_drafts), mở lại xem bản cũ, muốn bản
  mới thì bấm Viết lại.
- Dữ liệu gửi đi: từ khóa, nội dung AI Overview hiện tại, tiêu đề / tên miền các nguồn AI đang trích, đường dẫn trang
  của website, tên thương hiệu. Không gửi email, tài khoản hay số GA4 / GSC.
- AI không được bịa số: chỗ cần số liệu riêng của doanh nghiệp để dạng [điền …] cho người viết điền."""
import json
import re
import sqlite3
from datetime import datetime, timezone

from . import ai_http as AH

ORDER = ("ai", "gateway", "openai", "gemini", "deepseek", "xai", "perplexity")
DEFAULT_MODEL = {"ai": "claude-sonnet-5-5"}  # Anthropic: chưa chọn model thì dùng Sonnet (viết nháp: nhanh, đủ tốt)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, site TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
  content TEXT NOT NULL, provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
  by TEXT NOT NULL DEFAULT '', at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ai_drafts_ref ON ai_drafts (site, kind, ref);
"""


class NoProvider(RuntimeError):
    pass


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def provider(cfg) -> dict:
    """Nhà cung cấp sẽ dùng: {name, style, base, key, model}. Chưa có nhà cung cấp nào đủ khóa + model → NoProvider."""
    from . import integrations as I
    for p in ORDER:
        s = AH.settings_for(cfg, p)
        if not s:
            continue
        s["model"] = s["model"] or DEFAULT_MODEL.get(p, "")
        if s["model"]:
            return {"name": I.BY_KEY[p].name, "key_name": p, **s}
    raise NoProvider("Chưa có nhà cung cấp AI: Owner nhập khóa (và model) ở Quản trị > Cài đặt tích hợp > Nhà cung cấp AI")


def latest(con, site: str, kind: str, ref: str) -> dict | None:
    ensure(con)
    row = con.execute("SELECT content, provider, model, by, at FROM ai_drafts WHERE site = ? AND kind = ? AND ref = ? "
                      "ORDER BY id DESC LIMIT 1", (site, kind, ref)).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row[0])
    except ValueError:
        data = {"answer": row[0]}
    return {**data, "provider": row[1], "model": row[2], "by": row[3], "at": row[4]}


def save(con, site: str, kind: str, ref: str, data: dict, prov: dict, by: str) -> None:
    ensure(con)
    with con:
        con.execute("INSERT INTO ai_drafts (site, kind, ref, content, provider, model, by, at) VALUES (?,?,?,?,?,?,?,?)",
                    (site, kind, ref, json.dumps(data, ensure_ascii=False), prov["name"], prov["model"], by,
                     datetime.now(timezone.utc).isoformat(timespec="seconds")))


# ---------------------------------------------------------------- đoạn trả lời AI Overview

SYSTEM_AIO = (
    "Bạn là biên tập viên SEO tiếng Việt. Nhiệm vụ: viết nội dung để trang của website được Google AI Overview trích "
    "làm nguồn. Viết tự nhiên, rõ ràng, đúng ý định tìm kiếm, không nhồi từ khóa, không quảng cáo lố.\n"
    "Quy tắc bắt buộc:\n"
    "- Không bịa số liệu, giá, thông số, địa chỉ, chính sách. Chỗ cần thông tin riêng của doanh nghiệp thì để dạng "
    "[điền …] để người viết điền.\n"
    "- Được dùng kiến thức phổ thông đã được công nhận; không khẳng định điều không chắc.\n"
    "- Chỉ trả về một đối tượng JSON hợp lệ, không thêm chữ nào ngoài JSON.")


def aio_prompt(keyword: str, brand: str, page: str, aio_text: str, sources: list[dict], issue: str) -> str:
    src = "\n".join(f"- {s.get('domain', '')}: {s.get('title') or ''}" for s in sources[:8]) or "- (không có)"
    return (
        f"Từ khóa: {keyword}\n"
        f"Thương hiệu của website: {brand}\n"
        f"Trang của website đang nhắm từ khóa này: {page or '(chưa có trang xếp hạng)'}\n"
        f"Vấn đề tool phát hiện: {issue}\n\n"
        f"Nội dung Google AI Overview hiện tại:\n\"\"\"\n{(aio_text or '(chưa lưu nội dung chữ)')[:3500]}\n\"\"\"\n\n"
        f"Các nguồn AI Overview đang trích (tên miền: tiêu đề):\n{src}\n\n"
        "Hãy trả về JSON đúng dạng:\n"
        "{\n"
        '  "answer": "đoạn trả lời 40–60 từ, trả lời thẳng câu hỏi của từ khóa, có nhắc tên thương hiệu một lần một '
        'cách tự nhiên, đặt ngay dưới tiêu đề trang",\n'
        '  "headings": ["3–5 tiêu đề H2/H3 dạng câu hỏi người dùng hay hỏi"],\n'
        '  "missing": ["3–5 ý mà các nguồn đang được trích có nhưng trang của website nên bổ sung"],\n'
        '  "faq": [{"q": "câu hỏi", "a": "câu trả lời ngắn 1–2 câu"}]\n'
        "}\n"
        "faq có 2–3 câu. Toàn bộ bằng tiếng Việt.")


def _json(text: str) -> dict:
    """Lấy JSON trong câu trả lời (có model bọc ```json … ``` hoặc thêm chữ trước / sau)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise AH.AIError("AI không trả về đúng định dạng, bấm Viết lại")
    try:
        data = json.loads(m.group(0))
    except ValueError as e:
        raise AH.AIError("AI trả về JSON lỗi, bấm Viết lại") from e
    out = {"answer": str(data.get("answer") or "").strip(),
           "headings": [str(x).strip() for x in data.get("headings") or [] if str(x).strip()][:6],
           "missing": [str(x).strip() for x in data.get("missing") or [] if str(x).strip()][:6],
           "faq": [{"q": str(x.get("q", "")).strip(), "a": str(x.get("a", "")).strip()}
                   for x in data.get("faq") or [] if isinstance(x, dict) and x.get("q")][:4]}
    if not out["answer"]:
        raise AH.AIError("AI chưa viết đoạn trả lời, bấm Viết lại")
    return out


def write_aio(cfg, keyword: str, brand: str, page: str, aio_text: str, sources: list[dict], issue: str,
              prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    """Gọi AI viết đoạn trả lời; trả (bản nháp, nhà cung cấp đã dùng). Lỗi → AH.AIError / NoProvider."""
    prov = prov or provider(cfg)
    text = AH.complete(prov["style"], prov["base"], prov["key"], prov["model"],
                       aio_prompt(keyword, brand, page, aio_text, sources, issue), system=SYSTEM_AIO,
                       max_tokens=1500, timeout=120, opener=opener)
    return _json(text), prov


# ---------------------------------------------------------------- nhận xét báo cáo tuần / tháng

SYSTEM_REPORT = (
    "Bạn là trưởng nhóm SEO viết nhận xét báo cáo cho quản lý / khách hàng, bằng tiếng Việt, giọng chuyên nghiệp, "
    "dễ hiểu với người không làm SEO.\n"
    "Quy tắc bắt buộc:\n"
    "- Chỉ dùng số có trong dữ liệu được cung cấp; không bịa số, không tự tính tỷ lệ mới nếu không chắc.\n"
    "- Nêu nguyên nhân khi dữ liệu cho thấy rõ (trang / truy vấn / từ khóa cụ thể); chưa rõ thì nói là cần theo dõi "
    "thêm, không đoán.\n"
    "- Số liệu ghi 'chưa có' nghĩa là nguồn chưa kết nối: bỏ qua, không nhắc là giảm.\n"
    "- Chỉ trả về một đối tượng JSON hợp lệ, không thêm chữ nào ngoài JSON.")


def _pct(v) -> str:
    return "" if v is None else f"{v * 100:+.0f}%"


def report_facts(rep) -> str:
    """Số liệu của kỳ báo cáo dạng chữ gọn để gửi AI (chỉ số tổng hợp, trang / truy vấn / từ khóa; không có email,
    tài khoản)."""
    from . import report as RP
    s = RP.summary(rep)
    unit = s["unit"]
    out = [f"Website: {rep.site}", f"Kỳ: {RP.period_text(rep.kind, rep.week)} (so với {RP.period_text(rep.kind, rep.prev_week)})"]
    # Top 10 của toàn bộ từ khóa theo dõi bỏ qua: số "+N" có thể do mới thêm từ khóa; dùng dòng Thứ hạng bên dưới
    out.append("Chỉ số SEO: " + "; ".join(f"{x['label']}: {x['value']}" + (f" ({x['delta']})" if x["delta"] else "")
                                          for x in s["seo"] if x["short"] != "Top 10"))
    out.append("Chỉ số GEO / AI: " + "; ".join(f"{x['label']}: {x['value']}" + (f" ({x['delta']})" if x["delta"] else "")
                                               for x in s["geo"]))
    for n in s["seo_notes"] + s["geo_notes"]:
        out.append(f"Điểm tool tự phát hiện: {n['long']}")
    if rep.winners:
        out.append("Trang tăng click nhiều nhất: " + "; ".join(
            f"{RP._path(w['url'], rep.site)} {w['prev']}→{w['clicks']}" for w in rep.winners[:5]))
    if rep.losers:
        out.append("Trang giảm click nhiều nhất: " + "; ".join(
            f"{RP._path(w['url'], rep.site)} {w['prev']}→{w['clicks']}" for w in rep.losers[:5]))
    if rep.top_queries:
        out.append("Truy vấn nhiều click nhất: " + "; ".join(
            f"“{q['query']}” {q['clicks']} click" + (f" ({_pct(q['change'])})" if q.get("change") is not None else "")
            for q in rep.top_queries[:8]))
    if rep.by_type:
        out.append("Click theo loại trang: " + "; ".join(
            f"{t['type']} {t['clicks']}" + (f" ({_pct(t['change'])})" if t.get("change") is not None else "")
            for t in rep.by_type[:6]))
    if rep.ranks:
        rs = RP.rank_summary(rep, rep.committed)
        line = (f"Thứ hạng ({rs['total']} từ khóa" + (", bộ cam kết" if rs["committed"] else "") + "): "
                f"Top 3 {rs['now'][3]}, Top 10 {rs['now'][10]}")
        if rs["has_prev"]:
            line += f" (lần trước Top 3 {rs['prev'][3]}, Top 10 {rs['prev'][10]})"
        out.append(line)
        if rs["up"]:
            out.append("Từ khóa lên mạnh: " + "; ".join(f"{m['keyword']} {m['from'] or 'ngoài'}→{m['to']}"
                                                        for m in rs["up"]))
        if rs["down"]:
            out.append("Từ khóa rớt mạnh: " + "; ".join(f"{m['keyword']} {m['from']}→{m['to'] or 'ngoài độ sâu'}"
                                                        for m in rs["down"]))
    if rep.incomplete_days:
        out.append(f"Lưu ý: còn {rep.incomplete_days} ngày trong {unit} chưa có dữ liệu GSC (số có thể tăng thêm).")
    return "\n".join(out)


def report_prompt(rep) -> str:
    month = rep.kind == "month"
    shape = ('{\n  "note": "nhận xét: 3–5 gạch đầu dòng, mỗi dòng bắt đầu bằng \\"- \\", nêu kết quả chính, nguyên nhân '
             'và điểm cần chú ý"' + (',\n  "plan": "kế hoạch tháng sau: 3–5 gạch đầu dòng, việc cụ thể dựa trên số liệu"'
                                     if month else ',\n  "plan": ""') + "\n}")
    return ("Dữ liệu báo cáo:\n" + report_facts(rep) + "\n\n"
            f"Viết nhận xét cho báo cáo {'tháng' if month else 'tuần'} này. Câu đầu tiên của nhận xét là kết luận "
            "kỳ này tốt hay chưa tốt. Trả về JSON đúng dạng:\n" + shape)


def write_report(cfg, rep, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    prov = prov or provider(cfg)
    text = AH.complete(prov["style"], prov["base"], prov["key"], prov["model"], report_prompt(rep),
                       system=SYSTEM_REPORT, max_tokens=1500, timeout=120, opener=opener)
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        data = None
    if not data or not str(data.get("note") or "").strip():
        raise AH.AIError("AI không trả về đúng định dạng, bấm lại")
    return {"note": str(data["note"]).strip(), "plan": str(data.get("plan") or "").strip()}, prov
