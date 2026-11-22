"""Số gộp của trang Backlink từ danh sách link gộp (DataForSEO + file Semrush, backlink_links.latest): theo website,
trang đích, anchor; độ phủ của từng nguồn; thay đổi giữa hai lần nhập file Semrush. Không gọi API."""
from . import backlink_links as BLL

SRC = {"dfs": "DataForSEO", "semrush": "Semrush"}


def _srcs(x: dict) -> list[str]:
    return x.get("src") or ["dfs"]


def domains(items: list[dict]) -> list[dict]:
    """Mỗi website trỏ về một dòng: số link theo nguồn, dofollow, uy tín, ascore, spam, IP, quốc gia, thấy lần đầu."""
    out: dict[str, dict] = {}
    for x in items:
        g = out.setdefault(x["d_from"], {
            "domain": x["d_from"], "links": 0, "dfs": 0, "semrush": 0, "dofollow": 0, "rank": 0, "ascore": None,
            "spam": 0, "ip": "", "country": "", "first": None, "targets": set(), "anchors": set(), "src": set(),
            "threat": ""})
        g["links"] += 1
        for s_ in _srcs(x):
            g[s_] = g.get(s_, 0) + 1
            g["src"].add(s_)
        g["dofollow"] += bool(x.get("follow"))
        g["rank"] = max(g["rank"], x.get("d_rank") or 0)
        a = x.get("d_ascore") if x.get("d_ascore") is not None else None
        if a is not None:
            g["ascore"] = max(g["ascore"] or 0, a)
        g["spam"] = max(g["spam"], x.get("spam") or 0)
        g["ip"] = g["ip"] or x.get("ip") or ""
        g["country"] = g["country"] or (x.get("country") or "").upper()
        if x.get("first") and (not g["first"] or x["first"] < g["first"]):
            g["first"] = x["first"]
        g["targets"].add(BLL._page(x["u_to"]))
        g["anchors"].add((x.get("anchor") or "").lower())
        g["threat"] = g["threat"] or x.get("threat") or ""
    rows = []
    for g in out.values():
        g["targets"], g["anchors"] = len(g["targets"]), len(g["anchors"])
        g["src"] = [s_ for s_ in SRC if s_ in g["src"]]
        rows.append(g)
    return sorted(rows, key=lambda g: (-g["rank"], -(g["ascore"] or 0), -g["links"]))


def pages(items: list[dict]) -> list[dict]:
    """Mỗi trang đích một dòng: website / link theo nguồn, mã trạng thái."""
    out: dict[str, dict] = {}
    for x in items:
        k = BLL._page(x["u_to"])
        g = out.setdefault(k, {"page": x["u_to"].split("#")[0], "links": 0, "doms": set(), "doms_dfs": set(),
                               "doms_semrush": set(), "dofollow": 0, "status": None, "redir": ""})
        g["links"] += 1
        g["doms"].add(x["d_from"])
        for s_ in _srcs(x):
            g.setdefault(f"doms_{s_}", set()).add(x["d_from"])
        g["dofollow"] += bool(x.get("follow"))
        if x.get("st_to") and not g["status"]:
            g["status"], g["redir"] = x["st_to"], x.get("redir") or ""
    rows = []
    for g in out.values():
        rows.append({"page": g["page"], "links": g["links"], "domains": len(g["doms"]),
                     "dfs": len(g["doms_dfs"]), "semrush": len(g["doms_semrush"]), "dofollow": g["dofollow"],
                     "status": g["status"], "redir": g["redir"]})
    return sorted(rows, key=lambda r: (-r["domains"], -r["links"]))


def anchors(items: list[dict], brand_terms: list[str]) -> list[dict]:
    """Mỗi anchor một dòng: loại (thương hiệu / URL / từ khóa / trống), website theo nguồn, số link, tỷ lệ."""
    from .backlink_audit import anchor_type
    out: dict[str, dict] = {}
    for x in items:
        text = " ".join(str(x.get("anchor") or "").split())
        g = out.setdefault(text.lower(), {"anchor": text, "doms": set(), "doms_dfs": set(), "doms_semrush": set(),
                                          "links": 0, "first": None})
        g["doms"].add(x["d_from"])
        for s_ in _srcs(x):
            g.setdefault(f"doms_{s_}", set()).add(x["d_from"])
        g["links"] += 1
        if x.get("first") and (not g["first"] or x["first"] < g["first"]):
            g["first"] = x["first"]
    total = sum(len(g["doms"]) for g in out.values()) or 1
    rows = [{"anchor": g["anchor"], "type": anchor_type(g["anchor"], brand_terms), "domains": len(g["doms"]),
             "dfs": len(g["doms_dfs"]), "semrush": len(g["doms_semrush"]), "links": g["links"],
             "share": len(g["doms"]) / total, "first": g["first"]} for g in out.values()]
    return sorted(rows, key=lambda r: (-r["domains"], -r["links"]))


def anchor_mix(rows: list[dict]) -> dict[str, float]:
    tot = sum(r["domains"] for r in rows) or 1
    mix: dict[str, float] = {}
    for r in rows:
        mix[r["type"]] = mix.get(r["type"], 0) + r["domains"] / tot
    return mix


def summary(items: list[dict]) -> dict:
    """Số tổng theo nguồn: {"dfs" | "semrush" | "all": {"links", "domains", "dofollow", "pages", "home", "image"}}
    và độ phủ {"both", "dfs_only", "semrush_only"} theo website và theo link."""
    out = {}
    for key in ("dfs", "semrush", "all"):
        its = items if key == "all" else [x for x in items if key in _srcs(x)]
        n = len(its) or 1
        out[key] = {"links": len(its), "domains": len({x["d_from"] for x in its}),
                    "dofollow": sum(1 for x in its if x.get("follow")) / n if its else None,
                    "pages": len({BLL._page(x["u_to"]) for x in its}),
                    "home": sum(1 for x in its if BLL._page(x["u_to"]).count("/") == 0) / n if its else None,
                    "image": sum(1 for x in its if x.get("type") == "image")}
    d_dfs = {x["d_from"] for x in items if "dfs" in _srcs(x)}
    d_sr = {x["d_from"] for x in items if "semrush" in _srcs(x)}
    l_both = sum(1 for x in items if len(_srcs(x)) > 1)
    out["cover"] = {"domains": {"both": len(d_dfs & d_sr), "dfs_only": len(d_dfs - d_sr), "semrush_only": len(d_sr - d_dfs)},
                    "links": {"both": l_both, "dfs_only": sum(1 for x in items if _srcs(x) == ["dfs"]),
                              "semrush_only": sum(1 for x in items if _srcs(x) == ["semrush"])}}
    return out


def import_changes(cur: list[dict] | None, prev: list[dict] | None, key: str) -> dict | None:
    """So hai lần nhập file Semrush: website mới / không còn. key: "d_from" (Backlinks) hoặc "domain" (Referring
    domains). None khi chưa có lần trước."""
    if cur is None or prev is None:
        return None
    a, b = {x[key] for x in cur}, {x[key] for x in prev}
    return {"new": sorted(a - b), "lost": sorted(b - a)}


ANCHOR_TYPE = {"brand": "Thương hiệu", "url": "URL", "keyword": "Từ khóa", "empty": "Trống / ảnh"}


def full_audit(ld: dict | None, lists: dict, brand_terms: list[str], labels: dict | None = None) -> list[dict]:
    """Mọi mục kiểm tra (tab Audit và file xuất): theo từng link trên dữ liệu gộp + link mất 30 ngày, anchor spam
    (danh sách DataForSEO) + cơ cấu anchor tính lại từ dữ liệu gộp. Mỗi mục có rows là link (xem / xuất file)."""
    from . import backlink_audit as AU
    from . import link_audit as LA
    items = (ld or {}).get("items") or []
    out = LA.audit(items, ld["prev"]["items"] if ld and ld.get("prev") else None, brand_terms, labels or {}) \
        if items else []
    by = {c["key"]: c for c in (AU.audit(lists, brand_terms) if lists else [])}
    lost = by.get("lost")
    if lost and lost["rows"]:
        rows = [{"d_from": x.get("domain_from") or "", "u_from": x.get("url_from") or "", "title": x.get("title") or "",
                 "u_to": x.get("url_to") or "", "anchor": x.get("anchor") or "", "follow": bool(x.get("dofollow")),
                 "attrs": [], "type": x.get("type") or "anchor", "spam": x.get("spam") or 0,
                 "d_rank": x.get("domain_rank") or 0, "first": (x.get("first_seen") or "")[:10] or None,
                 "last": (x.get("last_seen") or "")[:10] or None, "src": ["dfs"]} for x in lost["rows"]]
        out.append({**lost, "rows": rows})
    asp = by.get("anchor_spam")
    if asp and asp["rows"] and items:
        bad = {(x.get("anchor") or "").lower() for x in asp["rows"]}
        # chỉ link DataForSEO có điểm spam (anchor trùng tên miền / thương hiệu không kéo cả link sạch vào)
        out.append({**asp, "rows": [x for x in items if (x.get("anchor") or "").lower() in bad
                                    and "dfs" in (x.get("src") or ["dfs"]) and (x.get("spam") or 0) >= AU.ANCHOR_SPAM]})
    if items:
        mix = anchor_mix(anchors(items, brand_terms))
        kw = mix.get("keyword", 0)
        out.append({"key": "anchor_mix", "level": "medium" if kw > AU.KEYWORD_SHARE else "ok",
                    "title": "Cơ cấu anchor (gộp hai nguồn)", "count": round(kw * 100), "unit": "% từ khóa",
                    "why": "Anchor chứa từ khóa chiếm quá nửa là dấu hiệu tối ưu quá mức; hồ sơ tự nhiên có nhiều "
                           "anchor thương hiệu và URL.",
                    "action": "Link mới nên dùng anchor thương hiệu / URL." if kw > AU.KEYWORD_SHARE else
                              "Ổn: anchor từ khóa chưa chiếm quá nửa.",
                    "mix": {ANCHOR_TYPE.get(k, k): round(v * 100) for k, v in mix.items()}, "rows": []})
    order = {"high": 0, "medium": 1, "info": 2, "ok": 3}
    return sorted(out, key=lambda c: order[c["level"]])
