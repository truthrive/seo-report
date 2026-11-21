"""Bản tin AI ở đầu trang Tổng quan: AI xếp ưu tiên và giải thích các tín hiệu TOOL đã tìm thấy (không tự thêm việc).

Hai lớp, để AI không đưa ra findings sai:
1. Tín hiệu (quy tắc cố định, không AI): gom từ thông báo của dự án (OKR, thứ hạng, audit, trang tụt traffic, dữ
   liệu / hệ thống, ngân sách), khối Cần xử lý, số của kỳ (click, trang giảm click, thứ hạng bộ cam kết) và gợi ý
   audit AI Overview. Mỗi tín hiệu có mã (S1, S2…), mức tối đa do quy tắc đặt, câu sự thật có số, link.
2. AI chỉ được chọn tối đa 5 tín hiệu theo mã, xếp ưu tiên, viết tiêu đề / vì sao / nên làm. Kiểm tra đầu ra:
   - mã không có trong danh sách → bỏ; trùng mã → bỏ; quá 2 mục cùng nhóm (trừ mức high) → bỏ;
   - mức AI đặt cao hơn mức tối đa của tín hiệu → hạ xuống mức tối đa;
   - câu có con số không có trong câu sự thật của tín hiệu đó → bỏ câu đó (tiêu đề thay bằng câu của tool);
   - link luôn lấy từ tín hiệu, không lấy từ AI.
Chỉ gọi AI khi bấm nút; kết quả lưu (ai_drafts, kind "brief") để mở trang không tốn tiền."""
import hashlib
import json
import re
from datetime import date

from . import ai_http as AH
from . import ai_writer as AW

KIND = "brief"
RANK = {"high": 0, "medium": 1, "low": 2}
LEVEL_FROM_NOTICE = {"high": "high", "medium": "medium", "info": "low"}
MAX_SIGNALS = 30
MAX_ITEMS = 5


def _sig(area: str, level: str, fact: str, href: str = "") -> dict:
    return {"area": area, "level": level, "fact": fact.strip(), "href": href}


def _pct(v) -> str:
    return f"{v * 100:+.0f}%".replace(".", ",")


def signals(con, cfg, user, rep=None, todo: list | None = None, today: date | None = None) -> list[dict]:
    """Danh sách tín hiệu có bằng chứng, nặng trước. Mỗi tín hiệu: id, area, level (high/medium/low = mức tối đa AI
    được đặt), fact (câu sự thật có số), href."""
    from . import notices as N
    out: list[dict] = []
    try:
        for n in N.collect(con, cfg, user, today=today):
            fact = n["title"] + (f" · {n['detail']}" if n.get("detail") else "")
            out.append(_sig(N.KINDS.get(n["kind"], (n["kind"],))[0], LEVEL_FROM_NOTICE[n["level"]], fact,
                            n.get("href") or ""))
    except Exception:  # noqa: BLE001 — thiếu bảng: bỏ qua nguồn này
        pass
    seen = {s["fact"].split(" · ")[0].lower() for s in out}
    from . import ui_theme as T
    for icon, color, text, href in todo or []:
        if text.lower() in seen:
            continue
        lvl = "high" if color == T.RED else "medium" if color == T.AMBER else "low"
        out.append(_sig("Cần xử lý", lvl, text, href))
    if rep is not None:
        from . import report as RP
        unit = "tháng" if rep.kind == "month" else "tuần"
        sk, sp = rep.site_kpi, rep.site_prev
        ch = RP.change(sk.clicks, sp.clicks)
        if ch is not None:
            lvl = "high" if ch <= -0.25 else "medium" if ch <= -0.1 else "low"
            out.append(_sig("Traffic", lvl, f"Click Google cả site {unit} này {sp.clicks} → {sk.clicks} ({_pct(ch)})", "/url"))
        for lo in rep.losers[:2]:
            if lo["diff"] <= -30:
                out.append(_sig("Traffic", "medium",
                                f"Trang giảm click mạnh {unit} này: {RP._path(lo['url'], rep.site)} "
                                f"{lo['prev']} → {lo['clicks']} click", "/url"))
        if rep.ranks:
            rs = RP.rank_summary(rep, rep.committed)
            if rs["has_prev"] and rs["now"][10] != rs["prev"][10]:
                d = rs["now"][10] - rs["prev"][10]
                out.append(_sig("Thứ hạng", "medium" if d < 0 else "low",
                                f"Từ khóa {'cam kết ' if rs['committed'] else ''}trong top 10: {rs['prev'][10]} → "
                                f"{rs['now'][10]} / {rs['total']}", "/rank"))
            down = rs["down"][:3]
            if down:  # gộp các từ khóa rớt mạnh thành một tín hiệu (để AI không chọn trùng)
                parts = [f"“{m['keyword']}” {m['from']} → " + (str(m["to"]) if m["to"] else "ngoài độ sâu")
                         for m in down]
                out.append(_sig("Thứ hạng", "medium",
                                f"{len(down)} từ khóa {'cam kết ' if rs['committed'] else ''}rớt mạnh nhất: "
                                + "; ".join(parts), "/rank"))
    try:  # Local SEO: chi nhánh cần chú ý, hồ sơ cần sửa, tín hiệu chéo Maps ↔ Search Console / thứ hạng / GA4
        from . import local_signals as LS
        for area, lvl, fact, href in LS.brief_signals(con, cfg.site_url, today, rep):
            out.append(_sig(area, lvl, fact, href))
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import aio as AO
        a = AO.audit(con, cfg)
        for g in a["groups"]:
            if g["items"] and g["severity"] == "high":
                out.append(_sig("AI Overview", "medium",
                                f"AI Overview: {g['title']} · {len(g['items'])} từ khóa (trong {a['aio']} từ khóa có "
                                "AI Overview)", "/aio?tab=viec"))
    except Exception:  # noqa: BLE001
        pass
    out.sort(key=lambda s: RANK[s["level"]])
    # Đủ chỗ thì giữ hết; quá MAX_SIGNALS thì giữ mọi tín hiệu nặng / vừa trước, phần còn lại chia lượt cho từng nhóm
    # (không để một nhóm nhiều tín hiệu nhẹ như thông báo audit đẩy mất tín hiệu của nhóm khác, vd Local SEO).
    if len(out) > MAX_SIGNALS:
        keep = [s for s in out if s["level"] != "low"][:MAX_SIGNALS]
        lows: dict[str, list] = {}
        for s in out:
            if s["level"] == "low":
                lows.setdefault(s["area"], []).append(s)
        while len(keep) < MAX_SIGNALS and any(lows.values()):
            for area in list(lows):
                if lows[area] and len(keep) < MAX_SIGNALS:
                    keep.append(lows[area].pop(0))
        out = keep
    for i, s in enumerate(out, 1):
        s["id"] = f"S{i}"
    return out


def fingerprint(sigs: list[dict]) -> str:
    """Dấu vân tay của bộ tín hiệu: đổi khi có tín hiệu mới / số đổi (để báo bản tin đã cũ)."""
    return hashlib.sha1("\n".join(sorted(s["fact"] for s in sigs)).encode()).hexdigest()[:16]


SYSTEM = (
    "Bạn là trưởng nhóm SEO. Đọc danh sách TÍN HIỆU do hệ thống đo được và chọn những việc team cần làm trước.\n"
    "Quy tắc bắt buộc:\n"
    f"- Chỉ chọn tối đa {MAX_ITEMS} tín hiệu, dùng đúng mã (S1, S2…) trong danh sách. Không tạo việc không có trong "
    "danh sách, không gộp hai mã vào một.\n"
    "- Ưu tiên: việc ảnh hưởng trực tiếp tới traffic / doanh thu / cam kết với khách (mất index, tụt traffic, rớt "
    "hạng từ khóa cam kết, lỗi kỹ thuật nặng) trước việc vận hành nội bộ; việc cũ đang trễ hạn trước việc mới.\n"
    "- Mức (priority) không được cao hơn mức tối đa ghi ở tín hiệu.\n"
    "- Đa dạng: không chọn quá 2 tín hiệu cùng một nhóm (cột thứ ba), trừ tín hiệu mức tối đa high. Nhiều tín hiệu "
    "giống nhau (ví dụ nhiều từ khóa cùng rớt hạng) thì chọn cái nặng nhất và nhắc trong 'why' là còn các mục tương "
    "tự.\n"
    "- Chỉ dùng con số có trong chính tín hiệu đó; không tự tính, không ước lượng, không đoán nguyên nhân khi tín "
    "hiệu không nói rõ.\n"
    "- Viết tiếng Việt ngắn gọn, cụ thể; 'action' là bước làm ngay được.\n"
    "- Chỉ trả về một đối tượng JSON hợp lệ, không thêm chữ nào ngoài JSON.")


def prompt(sigs: list[dict]) -> str:
    lines = [f"{s['id']} | mức tối đa: {s['level']} | {s['area']} | {s['fact']}" for s in sigs]
    return ("TÍN HIỆU:\n" + "\n".join(lines) + "\n\nTrả về JSON đúng dạng:\n"
            '{\n  "headline": "1 câu tóm tắt tình hình (không có số nếu không chắc)",\n'
            '  "items": [{"id": "S1", "priority": "high|medium|low", "title": "≤ 80 ký tự", '
            '"why": "≤ 160 ký tự: vì sao quan trọng", "action": "≤ 140 ký tự: việc làm ngay"}]\n}')


_NUM = re.compile(r"\d[\d.,]*")


def _nums(text: str) -> set[str]:
    """Các con số trong câu, chuẩn hoá (5.049 / 5,049 → 5049; 1,4 → 1.4; bỏ số 0 vô nghĩa)."""
    out = set()
    for m in _NUM.findall(text or ""):
        m = m.rstrip(".,")
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", m):
            m = re.sub(r"[.,]", "", m)
        else:
            m = m.replace(",", ".")
        out.add(m.lstrip("0") or "0")
    return out


def _clean(text: str, allowed: set[str], limit: int) -> str | None:
    """Câu AI viết: quá dài thì cắt; có số lạ (không có trong tín hiệu) thì trả None."""
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    if not _nums(text) <= allowed:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def validate(raw: dict, sigs: list[dict]) -> dict:
    """Áp các quy tắc kiểm tra đầu ra (xem đầu file). Trả {"headline", "items": [...], "dropped": số mục bị bỏ}."""
    by_id = {s["id"]: s for s in sigs}
    all_nums = set().union(*(_nums(s["fact"]) for s in sigs)) if sigs else set()
    items, used, dropped = [], set(), 0
    for it in (raw.get("items") or [])[: MAX_ITEMS * 2]:
        if not isinstance(it, dict):
            dropped += 1
            continue
        sid = str(it.get("id") or "").strip().upper()
        s = by_id.get(sid)
        if not s or sid in used:
            dropped += 1
            continue
        if s["level"] != "high" and sum(1 for x in items if x["area"] == s["area"]) >= 2:  # quá 2 mục cùng nhóm
            dropped += 1
            continue
        allowed = _nums(s["fact"])
        pr = str(it.get("priority") or s["level"]).lower()
        pr = pr if pr in RANK else s["level"]
        if RANK[pr] < RANK[s["level"]]:  # AI đặt cao hơn mức tối đa: hạ xuống
            pr = s["level"]
        title = _clean(it.get("title"), allowed, 90)
        why = _clean(it.get("why"), allowed, 180)
        action = _clean(it.get("action"), allowed, 160)
        items.append({"id": sid, "priority": pr, "title": title or s["fact"], "why": why or "",
                      "action": action or "", "fact": s["fact"], "href": s["href"], "area": s["area"],
                      "checked": title is not None and why is not None and action is not None})
        used.add(sid)
        if len(items) >= MAX_ITEMS:
            break
    items.sort(key=lambda x: RANK[x["priority"]])
    headline = _clean(raw.get("headline"), all_nums, 200) or ""
    return {"headline": headline, "items": items, "dropped": dropped}


def run(cfg, sigs: list[dict], prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    """Gọi AI rồi kiểm tra đầu ra. Lỗi → AH.AIError / AW.NoProvider."""
    prov = prov or AW.provider(cfg)
    text = AH.ask(prov, expect_json=True, prompt=prompt(sigs), system=SYSTEM,
                       max_tokens=1500, timeout=120, opener=opener)
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        raw = json.loads(m.group(0)) if m else None
    except ValueError:
        raw = None
    if not isinstance(raw, dict):
        raise AH.AIError("AI không trả về đúng định dạng, bấm lại")
    out = validate(raw, sigs)
    if not out["items"]:
        raise AH.AIError("AI không chọn được việc hợp lệ từ các tín hiệu, bấm lại")
    out["fingerprint"] = fingerprint(sigs)
    out["n_signals"] = len(sigs)
    return out, prov
