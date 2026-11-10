"""AI nhận định KPI và dự đoán: đọc tiến độ cam kết (số tool đã tính) rồi viết ngắn từng KPI đang ở đâu, dự đoán tháng
cam kết kế tiếp và việc nên làm.

Tool tính trước mọi con số AI được dùng (số hiện tại, cam kết, còn thiếu, tốc độ tăng mỗi tháng, dự báo theo tốc độ đó)
để AI không phải tự tính. Kiểm tra đầu ra:
- KPI phải là một trong các KPI đang có; mức chỉ good / watch / risk.
- Mọi con số trong câu AI viết phải có trong bảng số tool đưa (hoặc là số tháng của dự án); câu có số lạ thì bỏ câu đó.
- Tối đa 6 KPI, mỗi câu tối đa 240 ký tự."""
import hashlib
import json
import re

from . import ai_http as AH
from . import ai_writer as AW
from . import kpi as KP

KIND = "kpi_insight"
LEVELS = ("good", "watch", "risk")
MAX_TEXT = 240

SYSTEM = (
    "Bạn là chuyên gia SEO đọc tiến độ cam kết KPI của một dự án và viết nhận định ngắn cho team.\n"
    "Quy tắc bắt buộc:\n"
    "- Chỉ dùng số có trong dữ liệu được đưa; không tự tính số mới, không bịa số.\n"
    "- Dự đoán dựa trên 'tốc độ mỗi tháng' và 'dự báo' tool đã tính; nếu chưa đủ dữ liệu (ít hơn 2 tháng có số) thì nói "
    "rõ là chưa đủ dữ liệu để dự đoán.\n"
    "- Mỗi KPI: level = good (đang đạt / sẽ kịp), watch (sát, cần theo dõi), risk (khó kịp hoặc bộ từ khóa không đủ).\n"
    "- Câu ngắn (tối đa 25 chữ), tiếng Việt, không nhắc tên công cụ hay nguồn dữ liệu kỹ thuật.\n"
    "- Viết số nghìn có dấu chấm (25.277), số nguyên không ghi .0, không viết số âm cho số từ khóa.\n"
    "- Không lặp lại cùng một ý ở insight, forecast và action.\n"
    "- Chỉ trả về một đối tượng JSON hợp lệ, không thêm chữ nào ngoài JSON.")

SHAPE = """{
  "headline": "1 câu tổng quan tình hình cam kết",
  "items": [
    {"kpi": "mã KPI trong dữ liệu", "level": "good|watch|risk",
     "insight": "đang ở đâu so với cam kết", "forecast": "dự đoán tháng cam kết kế tiếp", "action": "việc nên làm"}
  ]
}"""


def _val(line: dict, ch: dict | None, running: bool):
    """Số cùng đơn vị cam kết (rank: số từ khóa / % ; traffic: phiên, tháng đang chạy dùng dự báo cuối tháng)."""
    if not ch:
        return None
    if line["kind"] == "rank":
        if not ch.get("checked") or not ch.get("total"):
            return None
        return round(ch["actual"] * 100, 1) if line.get("unit") == "pct" else ch["count"]
    if line["kind"] == "level":
        return ch.get("forecast") if running else ch.get("actual")
    return ch.get("cum")


def _num(v):
    """Số gọn: 9.0 → 9, 9.25 → 9.2."""
    if v is None:
        return None
    v = round(float(v), 1)
    return int(v) if v == int(v) else v


def _tgt(line: dict, t):
    if t is None:
        return None
    return round(t * 100, 1) if line["kind"] == "rank" and line.get("unit") == "pct" else t


def _name(line: dict) -> str:
    if line["kind"] == "rank" and line.get("name"):
        return f"{line['name']} (Top {line['top']})"
    if line["kind"] == "rank":
        return "Đạt Top mục tiêu" if line.get("mode") == "own" else f"Top {line['top']}"
    return {"organic": "Organic traffic", "ai": "AI traffic"}.get(line.get("source"), KP.line_label(line))


def facts(p: dict) -> dict:
    """Bảng số đưa cho AI (và dùng để kiểm tra đầu ra)."""
    months = p["months"]
    live = next((m for m in months if m["status"] == "running"), None) or \
        next((m for m in reversed(months) if m["status"] == "closed"), None)
    if not live:
        return {}
    out = {"thang_hien_tai": live["n"], "tong_so_thang": len(months), "kpi": []}
    if live["status"] == "running" and live.get("days_total"):
        out["ngay_da_qua"] = live.get("days_done")
        out["so_ngay_thang"] = live["days_total"]
    for line in p["lines"]:
        lid = KP.line_id(line)
        unit = ("%" if line.get("unit") == "pct" else "từ khóa") if line["kind"] == "rank" else "phiên/tháng"
        hist = []
        live_total = ((live.get("checks") or {}).get(lid) or {}).get("total")
        for m in months:
            if m["status"] == "future":
                continue
            mch = (m.get("checks") or {}).get(lid)
            if line["kind"] == "rank" and mch and mch.get("total") != live_total:
                continue  # tháng chấm theo bộ từ khóa khác (số từ khóa khác): không so được với bộ hiện tại
            v = _val(line, mch, m["status"] == "running")
            t = _tgt(line, (m.get("targets") or {}).get(lid))
            if v is not None or t is not None:
                hist.append({"thang": m["n"], "thuc_te": _num(v), "cam_ket": _num(t)})
        now = next((h["thuc_te"] for h in reversed(hist) if h["thuc_te"] is not None), None)
        if line["kind"] == "rank":  # từ khóa: chỉ số của bộ hiện tại
            now = _val(line, (live.get("checks") or {}).get(lid), live["status"] == "running")
        now = _num(now)
        plan = [{"thang": m["n"], "cam_ket": _num(_tgt(line, (m.get("targets") or {}).get(lid)))}
                for m in months if m["n"] > live["n"] and (m.get("targets") or {}).get(lid) is not None]
        item = {"ma": lid, "ten": _name(line), "don_vi": unit, "hien_tai": now, "lich_su": hist,
                "cam_ket_cac_thang_sau": plan[:6], "co_cam_ket": bool(plan) or any(h["cam_ket"] is not None
                                                                                   for h in hist)}
        ch = (live.get("checks") or {}).get(lid) or {}
        if line["kind"] == "rank":
            item["so_tu_khoa_trong_bo"] = ch.get("total")
        pts = [h["thuc_te"] for h in hist if h["thuc_te"] is not None]
        if len(pts) >= 2:
            pace = _num((pts[-1] - pts[0]) / (len(pts) - 1))
            item["toc_do_moi_thang"] = pace
            if plan and now is not None:
                nxt = plan[0]
                gap = nxt["thang"] - live["n"]
                item["du_bao_thang_" + str(nxt["thang"])] = _num(max(0, now + pace * gap))
        if plan and now is not None:
            item["con_thieu_den_cam_ket_ke_tiep"] = _num(max(0, plan[0]["cam_ket"] - now))
            if line["kind"] == "rank" and ch.get("total") is not None and plan[-1]["cam_ket"] > ch["total"]:
                item["bo_tu_khoa_khong_du"] = True
        out["kpi"].append(item)
    return out


def fingerprint(f: dict) -> str:
    return hashlib.sha1(json.dumps(f, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _nums(text: str) -> set[str]:
    out = set()
    for m in re.findall(r"\d[\d.,]*", text or ""):
        m = m.rstrip(".,")
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", m):
            m = re.sub(r"[.,]", "", m)
        else:
            m = m.replace(",", ".")
        try:
            out.add(f"{float(m):g}")
        except ValueError:
            continue
    return out


def check(raw: dict, f: dict) -> dict:
    """Áp quy tắc kiểm tra; trả {headline, items: [{kpi, name, level, insight, forecast, action}], dropped}."""
    allowed = _nums(json.dumps(f, ensure_ascii=False)) | {f"{float(n):g}" for n in range(0, 37)}
    allowed |= {"3", "5", "10", "100"}
    names = {k["ma"]: k["ten"] for k in f.get("kpi", [])}
    dropped = 0

    def ok(text) -> str:
        nonlocal dropped
        t = " ".join(str(text or "").split())[:MAX_TEXT]
        if t and not _nums(t) <= allowed:
            dropped += 1
            return ""
        return t
    items, seen = [], set()
    for it in (raw.get("items") or [])[:8]:
        if not isinstance(it, dict):
            continue
        k = str(it.get("kpi") or "")
        if k not in names or k in seen:
            dropped += 1
            continue
        insight = ok(it.get("insight"))
        if not insight:
            continue
        seen.add(k)
        lv = it.get("level") if it.get("level") in LEVELS else "watch"
        items.append({"kpi": k, "name": names[k], "level": lv, "insight": insight,
                      "forecast": ok(it.get("forecast")), "action": ok(it.get("action"))})
    order = list(names)
    items.sort(key=lambda x: order.index(x["kpi"]))
    return {"headline": ok(raw.get("headline")), "items": items[:6], "dropped": dropped}


def write(cfg, f: dict, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    prov = prov or AW.provider(cfg, "kpi_insight")
    out = AH.complete(prov["style"], prov["base"], prov["key"], prov["model"],
                      "Dữ liệu tiến độ KPI (JSON):\n" + json.dumps(f, ensure_ascii=False)
                      + "\n\nTrả về JSON đúng dạng:\n" + SHAPE, system=SYSTEM, max_tokens=2500, timeout=150,
                      opener=opener)
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        raw = json.loads(m.group(0)) if m else None
    except ValueError:
        raw = None
    if not isinstance(raw, dict):
        raise AH.AIError("AI không trả về đúng định dạng, bấm lại")
    res = check(raw, f)
    if not res["items"]:
        raise AH.AIError("AI chưa viết được nhận định hợp lệ, bấm lại")
    res["fingerprint"] = fingerprint(f)
    return res, prov
