"""AI cho trang Backlink (chỉ chạy khi bấm nút, Member trừ credit, lưu thư viện ai_drafts):

1. Nhận định hồ sơ backlink (`profile_facts` → `write_profile`): sức khỏe hồ sơ, rủi ro, việc nên làm trước.
2. Phân loại website, gợi ý nhãn (`classify_facts` → `write_classify`): Báo PR / Textlink / PBN / Web 2.0 / Danh bạ…
   kèm lý do; chỉ được chọn nhãn có sẵn, chỉ website có trong dữ liệu.
3. Duyệt danh sách disavow (`disavow_facts` → `write_disavow`): website nghi spam / nguy hiểm → disavow / giữ / xem tay.
4. Chiến lược backlink đối thủ (`rivals_facts` → `write_rivals`): đối thủ dựa vào loại link nào, bài học.
5. Kế hoạch xây link theo từ khóa (`plan_facts` → `write_plan`): trang đích, kiểu anchor, nguồn link (chỉ website
   có trong danh sách gợi ý), việc cụ thể.

Tool tính sẵn số; câu AI viết có số không có trong dữ liệu thì bị bỏ (dùng chung bộ kiểm của ai_rank)."""
import json

from . import ai_http as AH
from . import ai_rank as AR
from . import ai_writer as AW

MAX_CLASSIFY = 60
MAX_DISAVOW = 80
MAX_PLAN = 10
DECISIONS = {"disavow": "Disavow", "keep": "Giữ", "review": "Xem tay"}
ANCHOR_KINDS = {"brand": "Thương hiệu", "url": "URL", "keyword": "Từ khóa", "generic": "Chung chung"}
RULES = AR.BASE_RULES


def _dom_brief(g: dict, items: list[dict]) -> dict:
    """Tóm tắt một website cho AI: tiêu đề / anchor mẫu, số liệu."""
    mine = [x for x in items if x["d_from"] == g["domain"]]
    titles = list(dict.fromkeys(x.get("title") for x in mine if x.get("title")))[:2]
    anchors = list(dict.fromkeys(x.get("anchor") for x in mine if x.get("anchor")))[:3]
    plat = sorted({p for x in mine for p in x.get("platform") or []})
    lang = next((x.get("lang") for x in mine if x.get("lang")), "")
    ext = max((x.get("ext") or 0 for x in mine), default=0)
    return {"website": g["domain"], "so_link": g["links"], "dofollow": g["dofollow"], "uy_tin": g["rank"] or None,
            "ascore": g["ascore"], "diem_spam": g["spam"] or None, "quoc_gia": g["country"] or None,
            "ngon_ngu": lang or None, "link_ra_ngoai_max": ext or None, "loai_website": plat or None,
            "google_canh_bao": g["threat"] or None, "tieu_de_trang": titles, "anchor": anchors}


# ---------------------------------------------------------------- 1. nhận định hồ sơ

SYSTEM_PROFILE = ("Bạn là chuyên gia SEO đánh giá hồ sơ backlink của một website và viết nhận định ngắn cho team.\n"
                  "Quy tắc bắt buộc:\n" + RULES + "\n"
                  "- Ưu tiên rủi ro (spam, nguy hiểm, PBN, link về trang lỗi) và cơ hội rõ ràng; tối đa 5 ý, 5 việc.\n"
                  "- Việc nên làm phải cụ thể, làm được trong tool (disavow, redirect 301, xin link, đổi anchor…).")
SHAPE_PROFILE = """{
  "headline": "1 câu tổng kết sức khỏe hồ sơ backlink",
  "points": [{"level": "good|watch|risk", "text": "nhận định ngắn, có số từ dữ liệu"}],
  "actions": ["việc nên làm trước"]
}"""


def profile_facts(ld: dict | None, bl: dict | None, checks: list[dict], labels_count: dict) -> dict:
    from . import backlink_agg as AG
    items = (ld or {}).get("items") or []
    sm = AG.summary(items)
    now = (bl or {}).get("now") or {}

    def pct(v):
        return None if v is None else round(v * 100)
    return {
        "theo_nguon": {k: {"website": sm[k]["domains"], "backlink": sm[k]["links"],
                           "ty_le_dofollow_pct": pct(sm[k]["dofollow"]), "ve_trang_chu_pct": pct(sm[k]["home"])}
                       for k in ("dfs", "semrush", "all")},
        "do_phu_website": sm["cover"]["domains"],
        "uy_tin_dataforseo": now.get("rank"), "diem_spam_trung_binh": now.get("spam_score"),
        "muc_kiem_tra": [{"muc": c["title"], "muc_do": c["level"], "so": c["count"], "don_vi": c["unit"],
                          **({"co_cau_pct": c["mix"]} if c.get("mix") else {})}
                         for c in checks if c["level"] != "ok"],
        "nhan_website": labels_count}


def write_profile(cfg, f: dict, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    prov = prov or AW.provider(cfg, "backlink_insight")
    raw = AR._ask(prov, "Dữ liệu hồ sơ backlink (JSON):\n" + json.dumps(f, ensure_ascii=False)
                  + "\n\nTrả về JSON đúng dạng:\n" + SHAPE_PROFILE, SYSTEM_PROFILE, opener=opener)
    res = AR.check_insight(raw, f)
    if not res["points"] and not res["actions"]:
        raise AH.AIError("AI chưa viết được nhận định hợp lệ, bấm lại")
    res["fingerprint"] = AR.fingerprint(f)
    return res, prov


# ---------------------------------------------------------------- 2. phân loại website

SYSTEM_CLASSIFY = ("Bạn là chuyên gia SEO phân loại website đang đặt link về một website bán hàng tại Việt Nam.\n"
                   "Quy tắc bắt buộc:\n" + RULES + "\n"
                   "- Mỗi website chọn đúng một nhãn trong danh sách nhãn được phép; không chắc thì chọn \"Khác\".\n"
                   "- Dựa vào tiêu đề trang, anchor, loại website, quốc gia / ngôn ngữ, số link ra ngoài, điểm spam.\n"
                   "- Lý do ngắn (dưới 20 từ), nêu dấu hiệu cụ thể.")
SHAPE_CLASSIFY = """{
  "items": [{"website": "tên miền trong dữ liệu", "label": "một nhãn được phép", "confidence": "high|medium|low",
             "reason": "dấu hiệu cụ thể"}]
}"""


def classify_facts(items: list[dict], labels_table: dict, allowed: list[str], only_unlabeled: bool = True) -> dict:
    from . import backlink_agg as AG
    from . import site_labels as SL
    doms = [g for g in AG.domains(items) if not (only_unlabeled and SL.lookup(labels_table, g["domain"]))]
    doms.sort(key=lambda g: (-g["links"], -(g["ascore"] or 0), -g["rank"]))
    return {"nhan_duoc_phep": allowed + ["Khác"], "website": [_dom_brief(g, items) for g in doms[:MAX_CLASSIFY]]}


def check_classify(raw: dict, f: dict) -> list[dict]:
    doms = {d["website"] for d in f["website"]}
    ok_labels = set(f["nhan_duoc_phep"])
    out, seen = [], set()
    for x in raw.get("items") or []:
        if not isinstance(x, dict):
            continue
        d, lab = str(x.get("website") or "").strip().lower(), str(x.get("label") or "").strip()
        if d not in doms or d in seen or lab not in ok_labels:
            continue
        seen.add(d)
        out.append({"website": d, "label": lab,
                    "confidence": x.get("confidence") if x.get("confidence") in ("high", "medium", "low") else "low",
                    "reason": " ".join(str(x.get("reason") or "").split())[:160]})
    return out


def write_classify(cfg, f: dict, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    prov = prov or AW.provider(cfg, "backlink_classify")
    raw = AR._ask(prov, "Danh sách website cần phân loại (JSON):\n" + json.dumps(f, ensure_ascii=False)
                  + "\n\nTrả về JSON đúng dạng:\n" + SHAPE_CLASSIFY, SYSTEM_CLASSIFY, max_tokens=5000, opener=opener)
    items = check_classify(raw, f)
    if not items:
        raise AH.AIError("AI chưa phân loại được website nào, bấm lại")
    return {"items": items, "fingerprint": AR.fingerprint(f)}, prov


# ---------------------------------------------------------------- 3. duyệt disavow

SYSTEM_DISAVOW = ("Bạn là chuyên gia SEO duyệt danh sách website nghi spam trước khi đưa vào file disavow của Google.\n"
                  "Quy tắc bắt buộc:\n" + RULES + "\n"
                  "- disavow: rõ là spam / bán link hàng loạt / trang độc hại / mạng PBN không liên quan.\n"
                  "- keep: website thật, liên quan ngành hoặc báo / diễn đàn uy tín dù điểm spam cao.\n"
                  "- review: chưa đủ dấu hiệu, cần người mở trang xem.\n"
                  "- Google khuyên chỉ disavow khi chắc chắn; nghi ngờ thì chọn review. Lý do dưới 20 từ.")
SHAPE_DISAVOW = """{
  "items": [{"website": "tên miền trong dữ liệu", "decision": "disavow|keep|review", "reason": "dấu hiệu cụ thể"}],
  "note": "1 câu lưu ý chung"
}"""


def disavow_facts(items: list[dict], checks: list[dict]) -> dict:
    from . import backlink_agg as AG
    by = {c["key"]: c for c in checks}
    pbn = {d for g in (by.get("L_pbn") or {}).get("groups") or [] for d in g["domains"]}
    doms = []
    for g in AG.domains(items):
        flags = []
        if (g["spam"] or 0) >= 50:
            flags.append("điểm spam cao")
        if g["threat"]:
            flags.append("Google Safe Browsing cảnh báo")
        if g["domain"] in pbn:
            flags.append("chung IP với nhiều website khác")
        if flags:
            doms.append((g, flags))
    doms.sort(key=lambda t: (-len(t[1]), -(t[0]["spam"] or 0)))
    return {"website": [{**_dom_brief(g, items), "dau_hieu": flags} for g, flags in doms[:MAX_DISAVOW]]}


def check_disavow(raw: dict, f: dict) -> list[dict]:
    doms = {d["website"] for d in f["website"]}
    out, seen = [], set()
    for x in raw.get("items") or []:
        if not isinstance(x, dict):
            continue
        d = str(x.get("website") or "").strip().lower()
        if d not in doms or d in seen:
            continue
        seen.add(d)
        out.append({"website": d, "decision": x.get("decision") if x.get("decision") in DECISIONS else "review",
                    "reason": " ".join(str(x.get("reason") or "").split())[:160]})
    return out


def write_disavow(cfg, f: dict, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    if not f["website"]:
        raise AH.AIError("Không có website nào nghi spam / nguy hiểm để duyệt")
    prov = prov or AW.provider(cfg, "backlink_disavow")
    raw = AR._ask(prov, "Website nghi spam (JSON):\n" + json.dumps(f, ensure_ascii=False)
                  + "\n\nTrả về JSON đúng dạng:\n" + SHAPE_DISAVOW, SYSTEM_DISAVOW, max_tokens=6000, opener=opener)
    items = check_disavow(raw, f)
    if not items:
        raise AH.AIError("AI chưa duyệt được website nào, bấm lại")
    return {"items": items, "note": AR._clean(raw.get("note"), AR._allowed(f), 240),
            "fingerprint": AR.fingerprint(f)}, prov


def disavow_text(items: list[dict], generated: str = "") -> str:
    doms = sorted(x["website"] for x in items if x["decision"] == "disavow")
    head = [f"# Disavow do SEO Report tạo {generated} (AI duyệt, team đã xem lại)".rstrip(),
            "# Chỉ các website AI đề xuất disavow. Xem lại trước khi nộp cho Google."]
    return "\n".join(head + [f"domain:{d}" for d in doms]) + "\n"


# ---------------------------------------------------------------- 4. chiến lược đối thủ

SYSTEM_RIVALS = ("Bạn là chuyên gia SEO phân tích chiến lược backlink của các đối thủ từ dữ liệu website trỏ về họ "
                 "(mà chưa trỏ về website của mình).\nQuy tắc bắt buộc:\n" + RULES + "\n"
                 "- Mỗi đối thủ: họ dựa vào loại link nào (báo PR, textlink, PBN, web 2.0…), mạnh ở đâu.\n"
                 "- Bài học: 3–5 việc website mình nên làm, cụ thể.")
SHAPE_RIVALS = """{
  "summary": "1–2 câu tổng quan",
  "rivals": [{"name": "tên đối thủ trong dữ liệu", "strategy": "chiến lược chính", "evidence": "bằng chứng có số"}],
  "lessons": ["việc website mình nên làm"]
}"""


def rivals_facts(gap: dict | None, labels_table: dict) -> dict:
    from . import link_audit as LA
    from . import site_labels as SL
    items = (gap or {}).get("items") or []
    out = []
    for rv in (gap or {}).get("rivals") or []:
        mine = [g for g in items if rv["name"] in g["rivals"]]
        if not mine:
            continue
        lab: dict[str, int] = {}
        for g in mine:
            for lb in SL.lookup(labels_table, g["domain"]) or ["chưa gắn nhãn"]:
                lab[lb] = lab.get(lb, 0) + 1
        top = sorted(mine, key=lambda g: (-(g.get("ascore") or 0), -(g.get("rank") or 0)))[:8]
        groups = LA.pbn_groups([{"d_from": g["domain"], "ip": g.get("ip") or ""} for g in mine if g.get("ip")])
        out.append({"name": rv["name"], "website_gap": len(mine),
                    "website_viet_nam": sum(1 for g in mine if (g.get("country") or "").upper() == "VN"),
                    "website_spam": sum(1 for g in mine if (g.get("spam") or 0) >= 30),
                    "theo_nhan": lab, "nhom_chung_ip": len(groups),
                    "website_manh": [{"website": g["domain"], "ascore": g.get("ascore"), "uy_tin": g.get("rank") or None,
                                      "so_link": g.get("backlinks")} for g in top]})
    return {"doi_thu": out, "website_tro_ve_tu_2_doi_thu": sum(1 for g in items if len(g["rivals"]) >= 2)}


def write_rivals(cfg, f: dict, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    if not f["doi_thu"]:
        raise AH.AIError("Chưa có dữ liệu Backlink GAP của đối thủ")
    prov = prov or AW.provider(cfg, "backlink_rivals")
    raw = AR._ask(prov, "Dữ liệu backlink đối thủ (JSON):\n" + json.dumps(f, ensure_ascii=False)
                  + "\n\nTrả về JSON đúng dạng:\n" + SHAPE_RIVALS, SYSTEM_RIVALS, max_tokens=4000, opener=opener)
    ok = AR._allowed(f)
    names = {r["name"] for r in f["doi_thu"]}
    rivals = []
    for x in raw.get("rivals") or []:
        if isinstance(x, dict) and x.get("name") in names:
            s, e = AR._clean(x.get("strategy"), ok), AR._clean(x.get("evidence"), ok)
            if s:
                rivals.append({"name": x["name"], "strategy": s, "evidence": e})
    res = {"summary": AR._clean(raw.get("summary"), ok, 300), "rivals": rivals,
           "lessons": [a for a in (AR._clean(t, ok) for t in (raw.get("lessons") or [])[:6]) if a],
           "fingerprint": AR.fingerprint(f)}
    if not res["rivals"] and not res["lessons"]:
        raise AH.AIError("AI chưa phân tích được, bấm lại")
    return res, prov


# ---------------------------------------------------------------- 5. kế hoạch xây link theo từ khóa

SYSTEM_PLAN = ("Bạn là chuyên gia SEO lập kế hoạch xây backlink cho các trang đang có từ khóa ở vị trí 4–20 trên "
               "Google.\nQuy tắc bắt buộc:\n" + RULES + "\n"
               "- Mỗi trang: kiểu anchor nên dùng (thương hiệu / URL / từ khóa / chung chung) kèm 2–3 anchor mẫu "
               "tự nhiên, tránh dồn anchor từ khóa nếu trang đã nhiều anchor từ khóa.\n"
               "- Nguồn link: chỉ chọn website có trong danh sách nguồn gợi ý (tối đa 4 mỗi trang).\n"
               "- Việc cụ thể: 2–4 việc (bài PR, guest post, link nội bộ…).")
SHAPE_PLAN = """{
  "items": [{"url": "mã trang p1…", "anchor_kind": "brand|url|keyword|generic", "anchors": ["anchor mẫu"],
             "sources": ["tên miền trong danh sách nguồn"], "steps": ["việc cụ thể"]}]
}"""


def plan_facts(rows: list[dict], items: list[dict], gap: dict | None, labels_table: dict,
               brand_terms: list[str]) -> tuple[dict, dict]:
    """rows: trang cần link [{"url", "best": {"q", "pos"}, "domains", "impr"}]. Trả (dữ kiện, {mã: url})."""
    from . import backlink_agg as AG
    from . import backlink_links as BLL
    from . import site_labels as SL
    codes, pages = {}, []
    for i, r in enumerate(rows[:MAX_PLAN], 1):
        code = f"p{i}"
        codes[code] = r["url"]
        mine = BLL.for_page(items, r["url"])
        mix = AG.anchor_mix(AG.anchors(mine, brand_terms)) if mine else {}
        pages.append({"ma": code, "tu_khoa": r["best"]["q"], "vi_tri": r["best"]["pos"], "hien_thi": r.get("impr"),
                      "website_tro_ve": len({x["d_from"] for x in mine}) or r.get("domains"),
                      "co_cau_anchor_pct": {k: round(v * 100) for k, v in mix.items()} or None})
    srcs = []
    for g in sorted((gap or {}).get("items") or [], key=lambda g: (-len(g["rivals"]), -(g.get("ascore") or 0),
                                                                  -(g.get("rank") or 0))):
        if (g.get("spam") or 0) >= 30:
            continue
        srcs.append({"website": g["domain"], "nhan": SL.lookup(labels_table, g["domain"]) or None,
                     "tro_ve_doi_thu": len(g["rivals"]), "ascore": g.get("ascore")})
        if len(srcs) >= 30:
            break
    return {"trang": pages, "nguon_goi_y": srcs}, codes


def write_plan(cfg, data: tuple, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    f, codes = data
    if not f["trang"]:
        raise AH.AIError("Chọn ít nhất một trang")
    prov = prov or AW.provider(cfg, "backlink_plan")
    raw = AR._ask(prov, "Trang cần link và nguồn gợi ý (JSON):\n" + json.dumps(f, ensure_ascii=False)
                  + "\n\nTrả về JSON đúng dạng:\n" + SHAPE_PLAN, SYSTEM_PLAN, max_tokens=5000, opener=opener)
    ok = AR._allowed(f)
    srcs = {s["website"] for s in f["nguon_goi_y"]}
    kw = {p["ma"]: p["tu_khoa"] for p in f["trang"]}
    out = []
    for x in raw.get("items") or []:
        if not isinstance(x, dict) or x.get("url") not in codes:
            continue
        out.append({"url": codes[x["url"]], "keyword": kw[x["url"]],
                    "anchor_kind": x.get("anchor_kind") if x.get("anchor_kind") in ANCHOR_KINDS else "generic",
                    "anchors": [" ".join(str(a).split())[:80] for a in (x.get("anchors") or [])[:3] if str(a).strip()],
                    "sources": [s for s in (x.get("sources") or []) if s in srcs][:4],
                    "steps": [s for s in (AR._clean(t, ok) for t in (x.get("steps") or [])[:4]) if s]})
    if not out:
        raise AH.AIError("AI chưa lập được kế hoạch, bấm lại")
    return {"items": out, "fingerprint": AR.fingerprint(f)}, prov
