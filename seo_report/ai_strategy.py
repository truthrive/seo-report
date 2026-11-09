"""AI lập chiến lược SEO cho một nhóm từ khóa (trang Ý tưởng từ khóa, các từ khóa đã tick).

Không phải danh sách bài viết: đầu ra là kế hoạch chiến lược gồm
- nhận định tổng (1–2 câu) và hiện trạng (tool tự tính: tổng lượt tìm, đã top 10, trang 2, chưa có hạng, theo ý định);
- trụ cột chủ đề: vai trò (kéo doanh thu / mở rộng độ phủ / thương hiệu / địa phương), loại trang nên có, trang có sẵn
  để tối ưu hoặc làm trang mới, lý do;
- thắng nhanh: chỉ từ khóa site đang hạng 4–20 (tool lọc theo số GSC), việc cần làm để đẩy lên;
- lộ trình 3 giai đoạn: mục tiêu và việc của từng giai đoạn;
- KPI nên theo dõi và rủi ro / điều kiện.

Kiểm tra đầu ra: chỉ giữ từ khóa có trong danh sách (mỗi từ một trụ cột); URL trang có sẵn phải là trang của site đang
có hạng; số liệu hiện trạng, lượt tìm từng trụ cột, vị trí hiện tại do tool tự tính; thắng nhanh chỉ nhận từ khóa hạng
4–20; cắt độ dài, tối đa 6 trụ cột / 6 thắng nhanh / 3 giai đoạn. Chỉ gọi khi bấm nút; lưu ai_drafts kind "kw_strategy"."""
import hashlib
import json
import re

from . import ai_http as AH
from . import ai_writer as AW
from . import keywords as K

KIND = "kw_strategy"
MAX_KW = 80
ROLES = {"revenue": "Kéo doanh thu", "coverage": "Mở rộng độ phủ", "brand": "Thương hiệu", "local": "Địa phương",
         "authority": "Xây uy tín"}
INTENT_VI = {"transactional": "mua hàng", "commercial": "cân nhắc", "informational": "tìm hiểu",
             "navigational": "thương hiệu", "local": "địa điểm"}

SYSTEM = (
    "Bạn là trưởng nhóm chiến lược SEO. Từ một nhóm từ khóa và hiện trạng của website, lập KẾ HOẠCH CHIẾN LƯỢC cho "
    "quản lý: nên đầu tư chủ đề nào, vì sao, làm gì trước, đo bằng gì. Không liệt kê bài viết cho từng từ khóa.\n"
    "Quy tắc bắt buộc:\n"
    "- Chỉ dùng đúng các từ khóa có trong danh sách (chép nguyên văn); mỗi từ khóa chỉ thuộc một trụ cột.\n"
    "- Trụ cột = một chủ đề lớn có cùng mục tiêu kinh doanh; 2–6 trụ cột. role chọn trong: revenue (kéo doanh thu), "
    "coverage (mở rộng độ phủ), brand (thương hiệu), local (địa phương), authority (xây uy tín).\n"
    "- existing_url chỉ lấy từ cột 'trang của site' trong danh sách; không có thì để trống (cần trang mới).\n"
    "- quick_wins chỉ dùng từ khóa đang hạng 4–20 (ghi trong danh sách).\n"
    "- Không tự đưa ra số lượt tìm / thứ hạng hiện tại: hệ thống tự tính. Mục tiêu trong KPI được phép là mục tiêu "
    "đề xuất (ví dụ 'đưa nhóm X vào top 10'), không được nói như số đã đạt.\n"
    "- Viết tiếng Việt ngắn gọn, cho quản lý đọc.\n"
    "- Chỉ trả về một đối tượng JSON hợp lệ, không thêm chữ nào ngoài JSON.")

SHAPE = """{
  "summary": "1-2 câu nhận định chiến lược",
  "pillars": [{"name": "tên trụ cột", "role": "revenue|coverage|brand|local|authority",
    "page_type": "loại trang nên có: danh mục / sản phẩm / hướng dẫn / so sánh / landing địa phương…",
    "existing_url": "", "keywords": ["..."], "why": "vì sao đầu tư trụ cột này (1 câu)"}],
  "quick_wins": [{"action": "việc cụ thể", "keywords": ["từ khóa hạng 4-20"], "why": "1 câu"}],
  "phases": [{"name": "Giai đoạn 1 · tháng 1", "goal": "mục tiêu", "actions": ["2-4 việc"]}],
  "kpis": ["3-5 chỉ số nên theo dõi"],
  "risks": ["1-3 rủi ro / điều kiện"]
}"""


def _s(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def ref(rows: list[dict]) -> str:
    return hashlib.sha1("\n".join(sorted(K.fold(r["keyword"]) for r in rows)).encode()).hexdigest()[:16]


def _pos(r) -> float | None:
    p = r.get("gsc_pos")
    return float(p) if p else None


def status(rows: list[dict]) -> dict:
    """Hiện trạng do tool tính (không AI): tổng lượt tìm, số từ khóa top 10 / trang 2 / xa hơn / chưa có hạng, theo ý
    định."""
    st = {"n": len(rows), "volume": sum(r.get("volume") or 0 for r in rows), "top10": 0, "page2": 0, "far": 0,
          "none": 0, "intent": {}}
    for r in rows:
        p = _pos(r)
        key = "none" if p is None else "top10" if p <= 10 else "page2" if p <= 20 else "far"
        st[key] += 1
        it = INTENT_VI.get(r.get("intent") or "", r.get("intent") or "khác")
        st["intent"][it] = st["intent"].get(it, 0) + (r.get("volume") or 0)
    return st


def prompt(rows: list[dict], brand: str = "") -> str:
    st = status(rows)
    lines = []
    for r in rows:
        p = _pos(r)
        lines.append(f"- {r['keyword']} | lượt tìm {r.get('volume') or 0}/tháng | ý định: "
                     f"{INTENT_VI.get(r.get('intent') or '', r.get('intent') or '?')} | "
                     + (f"hạng {p:.0f}" if p else "chưa có hạng")
                     + (f" | trang của site: {r['gsc_page']}" if r.get("gsc_page") else ""))
    head = (f"Thương hiệu: {brand}\n" if brand else "") + (
        f"Hiện trạng: {st['n']} từ khóa, tổng {st['volume']} lượt tìm/tháng; {st['top10']} từ khóa đã top 10, "
        f"{st['page2']} ở trang 2 (hạng 11-20), {st['far']} xa hơn, {st['none']} chưa có hạng.\n")
    return head + "Danh sách từ khóa:\n" + "\n".join(lines) + "\n\nTrả về JSON đúng dạng:\n" + SHAPE


def check(raw: dict, rows: list[dict]) -> dict:
    by_key = {K.fold(r["keyword"]): r for r in rows}
    pages = {r["gsc_page"] for r in rows if r.get("gsc_page")}
    used: set[str] = set()
    pillars = []
    for p in raw.get("pillars") or []:
        if not isinstance(p, dict):
            continue
        kws = []
        for k in p.get("keywords") or []:
            fk = K.fold(str(k))
            if fk in by_key and fk not in used:
                used.add(fk)
                kws.append(by_key[fk])
        if not kws:
            continue
        ranked = [_pos(x) for x in kws if _pos(x)]
        url = str(p.get("existing_url") or "").strip()
        role = str(p.get("role") or "").lower()
        pillars.append({
            "name": _s(p.get("name"), 80) or kws[0]["keyword"], "role": role if role in ROLES else "coverage",
            "page_type": _s(p.get("page_type"), 80), "why": _s(p.get("why"), 220),
            "existing_url": url if url in pages else "",
            "keywords": [x["keyword"] for x in sorted(kws, key=lambda x: -(x.get("volume") or 0))],
            "volume": sum(x.get("volume") or 0 for x in kws),
            "best": min(ranked) if ranked else None, "ranked": len(ranked)})
        if len(pillars) >= 6:
            break
    pillars.sort(key=lambda x: -x["volume"])
    wins = []
    for w in raw.get("quick_wins") or []:
        if not isinstance(w, dict):
            continue
        ks = [by_key[K.fold(str(k))] for k in w.get("keywords") or [] if K.fold(str(k)) in by_key]
        ks = [x for x in ks if _pos(x) and 4 <= _pos(x) <= 20]  # quy tắc: chỉ từ khóa hạng 4–20
        if not ks or not _s(w.get("action"), 200):
            continue
        wins.append({"action": _s(w["action"], 200), "why": _s(w.get("why"), 200),
                     "keywords": [{"keyword": x["keyword"], "pos": round(_pos(x)), "volume": x.get("volume") or 0}
                                  for x in ks]})
        if len(wins) >= 6:
            break
    phases = [{"name": _s(p.get("name"), 60) or f"Giai đoạn {i}", "goal": _s(p.get("goal"), 200),
               "actions": [_s(a, 180) for a in p.get("actions") or [] if _s(a, 180)][:5]}
              for i, p in enumerate([p for p in raw.get("phases") or [] if isinstance(p, dict)][:3], 1)]
    return {"summary": _s(raw.get("summary"), 400), "status": status(rows), "pillars": pillars, "quick_wins": wins,
            "phases": [p for p in phases if p["actions"] or p["goal"]],
            "kpis": [_s(x, 160) for x in raw.get("kpis") or [] if _s(x, 160)][:5],
            "risks": [_s(x, 200) for x in raw.get("risks") or [] if _s(x, 200)][:3],
            "unassigned": [r["keyword"] for r in rows if K.fold(r["keyword"]) not in used]}


def write(cfg, rows: list[dict], brand: str = "", prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    rows = rows[:MAX_KW]
    if not rows:
        raise AH.AIError("Chưa chọn từ khóa nào")
    prov = prov or AW.provider(cfg)
    text = AH.complete(prov["style"], prov["base"], prov["key"], prov["model"], prompt(rows, brand), system=SYSTEM,
                       max_tokens=4000, timeout=180, opener=opener)
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        raw = json.loads(m.group(0)) if m else None
    except ValueError:
        raw = None
    if not isinstance(raw, dict):
        raise AH.AIError("AI không trả về đúng định dạng, bấm lại")
    out = check(raw, rows)
    if not out["pillars"]:
        raise AH.AIError("AI chưa lập được trụ cột hợp lệ, bấm lại")
    return out, prov
