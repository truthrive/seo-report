"""AI cho trang Thứ hạng từ khóa (chỉ chạy khi bấm nút, Member trừ credit):

1. Nhận định cả bộ (`set_facts` → `write_insight`): biến động lần check vừa rồi, nhóm đáng lo, khả năng đạt cam kết,
   việc nên làm.
2. Chẩn đoán một từ khóa (`kw_facts` → `write_diag`): đọc trang kết quả Google đã lưu lần trước / lần này (ai vượt
   lên, URL xếp hạng có đổi không, AI Overview) → nguyên nhân có thể + cách sửa.
3. Gợi ý URL mục tiêu (`target_facts` → `write_targets`): từ khóa chưa có URL mục tiêu → trang phù hợp nhất trong
   danh sách URL của website (URL SEO + trang đang xếp hạng). AI chỉ được chọn URL có trong danh sách.
4. Việc cần làm theo từ khóa (`actions_facts` → `write_actions`): việc cụ thể (onpage, nội dung, link nội bộ…) cho
   các từ khóa đã chọn.

Tool tính sẵn mọi con số; câu AI viết có số không có trong dữ liệu đưa vào thì bị bỏ (như AI nhận định KPI)."""
import hashlib
import json
import re

from . import ai_http as AH
from . import ai_writer as AW

LEVELS = ("good", "watch", "risk")
ACTION_TYPES = {"onpage": "Onpage", "content": "Nội dung", "internal": "Link nội bộ", "technical": "Kỹ thuật",
                "link": "Backlink", "serp": "SERP / AI Overview"}
MAX_TEXT = 260
MAX_TARGET_KW = 60
MAX_CANDIDATES = 200
MAX_ACTION_KW = 15

BASE_RULES = ("- Chỉ dùng số có trong dữ liệu được đưa; không tự tính số mới, không bịa số.\n"
              "- Tiếng Việt, câu ngắn, không nhắc tên công cụ hay nguồn dữ liệu kỹ thuật.\n"
              "- Viết số nghìn có dấu chấm (25.277), số nguyên không ghi .0.\n"
              "- Chỉ trả về một đối tượng JSON hợp lệ, không thêm chữ nào ngoài JSON.")


def fingerprint(f) -> str:
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


def _allowed(f) -> set[str]:
    return _nums(json.dumps(f, ensure_ascii=False)) | {f"{float(n):g}" for n in range(0, 11)} | {"20", "30", "100"}


def _clean(text, allowed: set[str], limit: int = MAX_TEXT) -> str:
    """Câu gọn; có số lạ (không có trong dữ liệu) thì bỏ cả câu."""
    t = " ".join(str(text or "").split())[:limit]
    return t if t and _nums(t) <= allowed else ""


def _json(out: str) -> dict:
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        raw = json.loads(m.group(0)) if m else None
    except ValueError:
        raw = None
    if not isinstance(raw, dict):
        raise AH.AIError("AI không trả về đúng định dạng, bấm lại")
    return raw


def _ask(prov, prompt: str, system: str, max_tokens: int = 2500, opener=None) -> dict:
    return _json(AH.ask(prov, expect_json=True, prompt=prompt, system=system, max_tokens=max_tokens, timeout=150,
                        opener=opener))


def _pos(rank, depth):
    if not depth:
        return None
    return rank if rank is not None else f">{depth}"


# ---------------------------------------------------------------- 1. nhận định cả bộ

SYSTEM_INSIGHT = ("Bạn là chuyên gia SEO đọc kết quả check thứ hạng một bộ từ khóa và viết nhận định ngắn cho team.\n"
                  "Quy tắc bắt buộc:\n" + BASE_RULES + "\n"
                  "- level: good (tốt lên / đang đạt), watch (cần theo dõi), risk (đáng lo).\n"
                  "- Tối đa 5 ý nhận định, tối đa 5 việc nên làm; việc nên làm phải cụ thể, có tên từ khóa khi được.\n"
                  "- Không lặp cùng một ý ở headline, points và actions: headline là kết luận chung, points là bằng "
                  "chứng (số), actions là việc làm.")
SHAPE_INSIGHT = """{
  "headline": "1 câu tổng quan",
  "points": [{"level": "good|watch|risk", "text": "một ý nhận định"}],
  "actions": ["việc nên làm cụ thể"]
}"""


def set_facts(name: str, kws: list[dict], vols: dict, hist: list[dict], goals: list | None = None) -> dict:
    """Bảng số đưa cho AI. kws: từ khóa của bộ (R.keywords); vols: {id: {volume}}; hist: R.set_history."""
    from .report import rank_change
    checked = [k for k in kws if k["date"]]
    now = {n: sum(1 for k in checked if k["rank"] is not None and k["rank"] <= n) for n in (3, 5, 10)}
    prev = {n: sum(1 for k in checked if k["prev"] is not None and k["prev"] <= n) for n in (3, 5, 10)}
    moves = []
    for k in checked:
        _t, _c, mv = rank_change(k["date"], k["rank"], k["last_depth"], k["prev"], k["prev_depth"])
        vol = (vols.get(k["id"]) or {}).get("volume")
        moves.append({"tu_khoa": k["keyword"], "truoc": _pos(k["prev"], k["prev_depth"]),
                      "nay": _pos(k["rank"], k["last_depth"]), "volume": vol, "mv": mv})
    gains = sorted([m for m in moves if m["mv"] > 0], key=lambda m: -m["mv"])[:8]
    drops = sorted([m for m in moves if m["mv"] < 0], key=lambda m: m["mv"])[:8]
    near = sorted([m for m in moves if isinstance(m["nay"], int) and 4 <= m["nay"] <= 15],
                  key=lambda m: -(m["volume"] or 0))[:8]
    f = {"bo": name, "so_tu_khoa": len(kws), "da_check": len(checked),
         "lan_check_moi_nhat": hist[-1]["label"] if hist else None,
         "lan_check_truoc": hist[-2]["label"] if len(hist) > 1 else None,
         "top_hien_tai": {f"top{n}": now[n] for n in now}, "top_lan_truoc": {f"top{n}": prev[n] for n in prev},
         "so_len_hang": sum(1 for m in moves if 0 < m["mv"] < 100),
         "so_rot_hang": sum(1 for m in moves if -100 < m["mv"] < 0),
         "so_vao_top": sum(1 for m in moves if m["mv"] == 100),
         "so_rot_khoi_top": sum(1 for m in moves if m["mv"] == -100),
         "chua_dat_top_muc_tieu": sum(1 for k in checked if k.get("top_target")
                                      and (k["rank"] is None or k["rank"] > k["top_target"])),
         "sai_url_muc_tieu": sum(1 for k in checked if k["target_url"] and k["ranking_url"]
                                 and k["ranking_url"] != k["target_url"]),
         "chua_co_url_muc_tieu": sum(1 for k in kws if not k["target_url"]),
         "tang_manh": [{k: v for k, v in m.items() if k != "mv"} for m in gains],
         "giam_manh": [{k: v for k, v in m.items() if k != "mv"} for m in drops],
         "sap_len_top3": [{k: v for k, v in m.items() if k != "mv"} for m in near]}
    if goals:
        f["cam_ket"] = [{"ten": g[0], **{f"top{n}": v for n, v in g[1].items()}} for g in goals]
    return f


def check_insight(raw: dict, f: dict) -> dict:
    ok = _allowed(f)
    pts = []
    for p in (raw.get("points") or [])[:6]:
        if not isinstance(p, dict):
            continue
        t = _clean(p.get("text"), ok)
        if t:
            pts.append({"level": p.get("level") if p.get("level") in LEVELS else "watch", "text": t})
    acts = [a for a in (_clean(x, ok) for x in (raw.get("actions") or [])[:6]) if a]
    return {"headline": _clean(raw.get("headline"), ok, 200), "points": pts[:5], "actions": acts[:5]}


def write_insight(cfg, f: dict, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    prov = prov or AW.provider(cfg, "rank_insight")
    raw = _ask(prov, "Dữ liệu thứ hạng của bộ từ khóa (JSON):\n" + json.dumps(f, ensure_ascii=False)
               + "\n\nTrả về JSON đúng dạng:\n" + SHAPE_INSIGHT, SYSTEM_INSIGHT, opener=opener)
    res = check_insight(raw, f)
    if not res["points"] and not res["actions"]:
        raise AH.AIError("AI chưa viết được nhận định hợp lệ, bấm lại")
    res["fingerprint"] = fingerprint(f)
    return res, prov


# ---------------------------------------------------------------- 2. chẩn đoán một từ khóa

SYSTEM_DIAG = ("Bạn là chuyên gia SEO chẩn đoán vì sao một từ khóa đổi thứ hạng trên Google, dựa trên trang kết quả "
               "đã lưu ở lần check trước và lần này.\nQuy tắc bắt buộc:\n" + BASE_RULES + "\n"
               "- Chỉ nêu nguyên nhân có bằng chứng trong dữ liệu (đối thủ vượt lên, URL xếp hạng đổi, AI Overview…); "
               "không đoán thuật toán chung chung.\n"
               "- Tối đa 3 nguyên nhân, tối đa 4 cách sửa cụ thể cho trang của website.")
SHAPE_DIAG = """{
  "summary": "1 câu: chuyện gì đã xảy ra",
  "causes": [{"cause": "nguyên nhân có thể", "evidence": "bằng chứng trong dữ liệu"}],
  "fixes": ["cách sửa cụ thể"]
}"""


def kw_facts(row: dict, serps: list[dict], site_host: str, vol=None) -> dict:
    """row: dòng bảng từ khóa (keyword, pos, prev_pos, best, target_full, link_full); serps: R.serp_history (mới
    trước)."""
    def top(s):
        return [{"hang": x.get("rank"), "website": x.get("domain"), "url": x.get("url")}
                for x in (s.get("organic") or s.get("top10") or [])[:10]]
    now, before = (serps[0] if serps else {}), (serps[1] if len(serps) > 1 else {})
    above_now = {x.get("domain") for x in (now.get("organic") or now.get("top10") or [])
                 if x.get("domain") and not str(x.get("domain")).endswith(site_host)}
    above_before = {x.get("domain") for x in (before.get("organic") or before.get("top10") or [])}
    return {"tu_khoa": row.get("keyword"), "volume": vol, "vi_tri_nay": row.get("pos"),
            "vi_tri_truoc": row.get("prev_pos") or None, "tot_nhat": row.get("best") or None,
            "url_muc_tieu": row.get("target_full") or None, "url_dang_xep_hang": row.get("link_full") or None,
            "ngay_nay": now.get("date"), "ngay_truoc": before.get("date"),
            "co_ai_overview_nay": now.get("aio"), "duoc_trich_ai_nay": now.get("cited"),
            "co_ai_overview_truoc": before.get("aio") if before else None,
            "top10_nay": top(now), "top10_truoc": top(before) if before else [],
            "website_moi_vao_top10": sorted(d for d in above_now - above_before if d)[:6] if before else []}


def check_diag(raw: dict, f: dict) -> dict:
    ok = _allowed(f)
    causes = []
    for c in (raw.get("causes") or [])[:4]:
        if isinstance(c, dict):
            a, b = _clean(c.get("cause"), ok), _clean(c.get("evidence"), ok)
            if a:
                causes.append({"cause": a, "evidence": b})
    fixes = [x for x in (_clean(t, ok) for t in (raw.get("fixes") or [])[:5]) if x]
    return {"summary": _clean(raw.get("summary"), ok, 220), "causes": causes[:3], "fixes": fixes[:4]}


def write_diag(cfg, f: dict, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    if not f.get("top10_nay"):
        raise AH.AIError("Chưa lưu trang kết quả Google của từ khóa này: check lại để có dữ liệu chẩn đoán")
    prov = prov or AW.provider(cfg, "rank_diag")
    raw = _ask(prov, "Dữ liệu từ khóa và trang kết quả Google (JSON):\n" + json.dumps(f, ensure_ascii=False)
               + "\n\nTrả về JSON đúng dạng:\n" + SHAPE_DIAG, SYSTEM_DIAG, opener=opener)
    res = check_diag(raw, f)
    if not res["causes"] and not res["fixes"]:
        raise AH.AIError("AI chưa chẩn đoán được, bấm lại")
    res["fingerprint"] = fingerprint(f)
    return res, prov


# ---------------------------------------------------------------- 3. gợi ý URL mục tiêu

SYSTEM_TARGET = ("Bạn là chuyên gia SEO chọn trang đích (URL mục tiêu) cho từng từ khóa.\nQuy tắc bắt buộc:\n"
                 + BASE_RULES + "\n"
                 "- Chỉ được chọn mã URL có trong danh sách (u1, u2…); không có trang phù hợp thì để null.\n"
                 "- Ưu tiên trang đúng ý định tìm kiếm (trang danh mục / sản phẩm cho từ khóa mua, bài viết cho từ "
                 "khóa thông tin); trang đang xếp hạng cho từ khóa là gợi ý tốt nếu đúng ý định.\n"
                 "- reason: tối đa 15 chữ.")
SHAPE_TARGET = """{
  "items": [{"kw": "từ khóa đúng như danh sách", "url": "u12 hoặc null", "reason": "vì sao chọn"}]
}"""


def target_facts(rows: list[dict], seo: list[dict], site: str) -> tuple[dict, dict]:
    """rows: dòng bảng từ khóa chưa có URL mục tiêu; seo: BB.seo_urls. Trả (dữ liệu cho AI, {mã: URL đầy đủ})."""
    urls: list[str] = []
    for u in [site] + [r.get("link_full") for r in rows] + [s["url"] for s in seo]:
        if u and u not in urls:
            urls.append(u)
    urls = urls[:MAX_CANDIDATES]
    codes = {f"u{i + 1}": u for i, u in enumerate(urls)}
    root = site.rstrip("/")
    groups = {s["url"]: ", ".join(s["groups"]) for s in seo}
    f = {"urls": [{"ma": c, "duong_dan": (u.replace(root, "") or "/"), **({"nhom": groups[u]} if u in groups else {})}
                  for c, u in codes.items()],
         "tu_khoa": [{"kw": r["keyword"], "volume": r.get("volume") if (r.get("volume") or 0) > 0 else None,
                      "y_dinh": r.get("intent") or None,
                      "dang_xep_hang": next((c for c, u in codes.items() if u == r.get("link_full")), None),
                      "vi_tri": r.get("pos") or None} for r in rows[:MAX_TARGET_KW]]}
    return f, codes


def check_targets(raw: dict, f: dict, codes: dict) -> list[dict]:
    names = {x["kw"] for x in f["tu_khoa"]}
    out, seen = [], set()
    for it in (raw.get("items") or [])[:MAX_TARGET_KW + 5]:
        if not isinstance(it, dict):
            continue
        kw, code = str(it.get("kw") or ""), it.get("url")
        if kw not in names or kw in seen:
            continue
        seen.add(kw)
        url = codes.get(str(code)) if code else None
        out.append({"kw": kw, "url": url, "reason": " ".join(str(it.get("reason") or "").split())[:120]})
    return out


def write_targets(cfg, data: tuple, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    f, codes = data
    if not f["tu_khoa"]:
        raise AH.AIError("Không có từ khóa nào thiếu URL mục tiêu")
    prov = prov or AW.provider(cfg, "rank_target")
    raw = _ask(prov, "Danh sách URL của website và các từ khóa cần chọn trang đích (JSON):\n"
               + json.dumps(f, ensure_ascii=False) + "\n\nTrả về JSON đúng dạng:\n" + SHAPE_TARGET, SYSTEM_TARGET,
               max_tokens=4000, opener=opener)
    items = check_targets(raw, f, codes)
    if not items:
        raise AH.AIError("AI chưa gợi ý được URL hợp lệ, bấm lại")
    return {"items": items, "fingerprint": fingerprint(f)}, prov


# ---------------------------------------------------------------- 4. việc cần làm theo từ khóa

SYSTEM_ACTIONS = ("Bạn là chuyên gia SEO lập việc cần làm cho từng từ khóa để lên hạng.\nQuy tắc bắt buộc:\n"
                  + BASE_RULES + "\n"
                  "- Mỗi từ khóa tối đa 3 việc, mỗi việc một câu cụ thể làm được ngay (sửa gì, ở trang nào).\n"
                  "- type: onpage | content | internal | technical | link | serp.\n"
                  "- Sai URL mục tiêu (Google xếp hạng trang khác): việc đầu tiên là xử lý trùng trang.")
SHAPE_ACTIONS = """{
  "items": [{"kw": "từ khóa đúng như danh sách", "actions": [{"type": "onpage", "text": "việc cụ thể"}]}]
}"""


def actions_facts(rows: list[dict]) -> dict:
    return {"tu_khoa": [{"kw": r["keyword"], "vi_tri": r.get("pos") or None, "truoc": r.get("prev_pos") or None,
                         "tot_nhat": r.get("best") or None,
                         "volume": r.get("volume") if (r.get("volume") or 0) > 0 else None,
                         "y_dinh": r.get("intent") or None, "top_muc_tieu": r.get("top_n"),
                         "url_muc_tieu": r.get("target_full") or None, "url_dang_xep_hang": r.get("link_full") or None,
                         "sai_url": bool(r.get("wrong")),
                         "ai_overview": bool(r.get("aio")), "duoc_trich_ai": r.get("aio_cited")}
                        for r in rows[:MAX_ACTION_KW]]}


def check_actions(raw: dict, f: dict) -> list[dict]:
    ok = _allowed(f)
    names = [x["kw"] for x in f["tu_khoa"]]
    out, seen = [], set()
    for it in (raw.get("items") or [])[:MAX_ACTION_KW + 5]:
        if not isinstance(it, dict):
            continue
        kw = str(it.get("kw") or "")
        if kw not in names or kw in seen:
            continue
        seen.add(kw)
        acts = []
        for a in (it.get("actions") or [])[:4]:
            if isinstance(a, dict):
                t = _clean(a.get("text"), ok)
                if t:
                    acts.append({"type": a.get("type") if a.get("type") in ACTION_TYPES else "onpage", "text": t})
        if acts:
            out.append({"kw": kw, "actions": acts[:3]})
    out.sort(key=lambda x: names.index(x["kw"]))
    return out


def write_actions(cfg, f: dict, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    if not f["tu_khoa"]:
        raise AH.AIError("Chọn ít nhất một từ khóa")
    prov = prov or AW.provider(cfg, "rank_actions")
    raw = _ask(prov, "Các từ khóa cần lên hạng (JSON):\n" + json.dumps(f, ensure_ascii=False)
               + "\n\nTrả về JSON đúng dạng:\n" + SHAPE_ACTIONS, SYSTEM_ACTIONS, max_tokens=4000, opener=opener)
    items = check_actions(raw, f)
    if not items:
        raise AH.AIError("AI chưa lập được việc cần làm hợp lệ, bấm lại")
    return {"items": items, "fingerprint": fingerprint(f)}, prov


def actions_text(items: list[dict]) -> str:
    """Bản sao chép: mỗi từ khóa một khối, mỗi việc một dòng (dán vào Công việc / OKR / Sheets)."""
    out = []
    for it in items:
        out.append(it["kw"])
        out += [f"- [{ACTION_TYPES.get(a['type'], a['type'])}] {a['text']}" for a in it["actions"]]
        out.append("")
    return "\n".join(out).strip()
