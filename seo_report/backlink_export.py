"""File Excel của trang Backlink: tổng quan + lịch sử 12 tháng, audit (mỗi vấn đề một sheet chi tiết) và bốn danh
sách. Bảng phẳng, có bộ lọc, để lọc / pivot hoặc gửi khách.

which: "all" (cả file), "audit", hoặc một danh sách ("domains" | "changes" | "anchors" | "pages"; kèm các mục
kiểm tra của danh sách đó).
"""
import io
import re

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


from .backlink_links import SB_TYPES  # noqa: E402

# cột đầy đủ của một link (sheet Tất cả backlink và sheet chi tiết của từng mục audit)
LINK_COLS = [("Website", 26, None), ("Nhãn", 18, None), ("Nguồn", 18, None), ("Page ascore (Semrush)", 12, INT), ("Trang đặt link", 60, None), ("Tiêu đề trang", 40, None),
             ("Anchor", 36, None), ("Loại anchor", 12, None), ("Chữ trước anchor", 30, None),
             ("Chữ sau anchor", 30, None), ("Dạng link", 11, None), ("Alt ảnh", 24, None), ("Trang đích", 50, None),
             ("Mã trang đích", 12, INT), ("Chuyển hướng tới", 40, None), ("Link gián tiếp", 11, None),
             ("Loại", 10, None), ("Thuộc tính rel", 18, None), ("Vị trí", 12, None), ("Vị trí (HTML)", 12, None),
             ("Số link giống trên trang", 12, INT), ("Uy tín website", 12, INT), ("Uy tín trang", 11, INT),
             ("Uy tín truyền (rank)", 12, INT), ("Điểm spam", 10, INT), ("Link ra ngoài của trang nguồn", 14, INT),
             ("Từ khóa top 10 của trang nguồn", 14, INT), ("Từ khóa top 100 của trang nguồn", 14, INT),
             ("Loại website (DataForSEO)", 20, None), ("Ngôn ngữ", 9, None), ("Quốc gia", 9, None), ("IP", 15, None),
             ("Mã trang nguồn", 11, INT), ("Google Safe Browsing", 18, None), ("Có từ lần đầu", 11, None),
             ("Thấy lần đầu", 13, None),
             ("Thấy gần nhất", 13, None)]


def _link_row(x: dict, labels: dict, brand_terms: list[str]) -> list:
    from . import link_audit as LA
    from . import site_labels as SL
    src = {"dfs": "DataForSEO", "semrush": "Semrush"}
    return [x["d_from"], ", ".join(SL.lookup(labels, x["d_from"])),
            " + ".join(src.get(s_, s_) for s_ in (x.get("src") or ["dfs"])), x.get("ascore"), x["u_from"], x.get("title") or "",
            x.get("anchor") or "", ANCHOR_TEXT[AU.anchor_type(x.get("anchor") or "", brand_terms)],
            x.get("pre") or "", x.get("post") or "", x.get("type") or "", x.get("alt") or "", x["u_to"],
            x.get("st_to"), x.get("redir") or "", "có" if x.get("indirect") else "",
            "dofollow" if x.get("follow") else "nofollow", ", ".join(x.get("attrs") or []), LA.place(x),
            x.get("loc") or "", x.get("same"), x.get("d_rank"), x.get("p_rank"), x.get("rank"), x.get("spam"),
            x.get("ext"), x.get("kw10"), x.get("kw100"), ", ".join(x.get("platform") or []), x.get("lang") or "",
            x.get("country") or "", x.get("ip") or "", x.get("st_from"),
            (SB_TYPES.get(x["threat"], x["threat"]) if x["threat"] else "an toàn") if "threat" in x else "chưa kiểm tra",
            "có" if x.get("original") else "",
            x.get("first"), x.get("last")]


# mục audit theo link thuộc tab nào (xuất file lẻ của tab kèm các mục đó)
LINK_TAB = {"L_broken": "pages", "L_redirect": "pages", "L_targets": "pages", "L_anchor_page": "anchors",
            "L_img_alt": "anchors", "L_spam": "domains", "L_pbn": "domains", "L_sitewide": "domains",
            "L_farm": "domains", "L_foreign": "domains", "L_quality": "domains", "L_platform": "domains",
            "L_follow": "domains", "L_place": "domains", "L_lost": "changes", "L_new": "changes"}
# file lẻ của tab: sheet link chi tiết xếp theo cột của tab (để lọc / pivot)
TAB_SORT = {"pages": ("Link theo trang đích", lambda x: (x["u_to"], -(x.get("d_rank") or 0))),
            "anchors": ("Link theo anchor", lambda x: ((x.get("anchor") or "").lower(), x["d_from"])),
            "domains": ("Link theo website", lambda x: (x["d_from"], x["u_from"])),
            "changes": ("Tất cả backlink", lambda x: (-(x.get("d_rank") or 0), x["d_from"]))}


def _links(wb, data: dict, labels: dict, brand_terms: list[str], title: str = "Tất cả backlink",
           sort=None, sites: bool = True) -> None:
    """Sheet mỗi link một dòng + sheet tổng hợp theo website (từ chính các link)."""
    items = sorted(data["items"], key=sort) if sort else data["items"]
    _sheet(wb, title, LINK_COLS, [_link_row(x, labels, brand_terms) for x in items])
    if not sites:
        return
    from . import site_labels as SL
    by: dict[str, dict] = {}
    for x in items:
        g = by.setdefault(x["d_from"], {"links": 0, "do": 0, "targets": set(), "anchors": set(), "rank": 0, "spam": 0,
                                        "ip": x.get("ip") or "", "country": x.get("country") or "",
                                        "platform": set(), "places": set(), "first": None})
        g["links"] += 1
        g["do"] += bool(x.get("follow"))
        g["targets"].add(x["u_to"])
        g["anchors"].add(x.get("anchor") or "")
        g["rank"] = max(g["rank"], x.get("d_rank") or 0)
        g["spam"] = max(g["spam"], x.get("spam") or 0)
        g["platform"] |= set(x.get("platform") or [])
        from . import link_audit as LA
        g["places"].add(LA.place(x))
        if x.get("first") and (not g["first"] or x["first"] < g["first"]):
            g["first"] = x["first"]
    _sheet(wb, "Website (từ link)", [
        ("Website", 30, None), ("Nhãn", 18, None), ("Số link", 9, INT), ("Dofollow", 9, INT), ("Nofollow", 9, INT),
        ("Số trang đích", 11, INT), ("Số anchor", 10, INT), ("Vị trí", 24, None), ("Uy tín website", 12, INT),
        ("Điểm spam cao nhất", 12, INT), ("Loại website (DataForSEO)", 20, None), ("Quốc gia", 9, None),
        ("IP", 15, None), ("Thấy lần đầu", 13, None)],
        [[d, ", ".join(SL.lookup(labels, d)), g["links"], g["do"], g["links"] - g["do"], len(g["targets"]),
          len(g["anchors"]), ", ".join(sorted(g["places"])), g["rank"], g["spam"], ", ".join(sorted(g["platform"])),
          g["country"], g["ip"], g["first"]] for d, g in sorted(by.items(), key=lambda kv: -kv[1]["links"])])


def _link_audit(wb, checks: list[dict], labels: dict, brand_terms: list[str]) -> None:
    """Sheet tóm tắt audit theo từng link + mỗi mục một sheet đủ cột link; nhóm PBN một sheet riêng."""
    if not checks:
        return
    _sheet(wb, "Audit backlink", [("Mức", 12, None), ("Mục", 36, None), ("Số lượng", 14, None),
                                  ("Cơ cấu", 50, None), ("Nên làm", 70, None), ("Vì sao", 80, None)],
           [[LEVEL_TEXT[c["level"]], c["title"],
             f"{c['count']}{c['unit']}" if c["unit"].startswith("%") else f"{c['count']} {c['unit']}",
             " · ".join(f"{k} {v}%" for k, v in (c.get("mix") or {}).items()), c["action"], c["why"]]
            for c in checks])
    used = set(wb.sheetnames)
    for c in checks:
        if c["key"] == "L_platform" and c.get("suggest"):
            _sheet(wb, "Gợi ý nhãn", [("Website", 30, None), ("Nhãn gợi ý", 24, None)],
                   [[d, ", ".join(v)] for d, v in sorted(c["suggest"].items())])
            continue
        if c["level"] in ("ok", "info") and c["key"] not in ("L_new", "L_quality") or not c["rows"]:
            continue
        name = re.sub(r"[\\/*?:\[\]]", "-", c["title"])[:28]  # ký tự Excel không cho trong tên sheet
        while name in used:
            name = name[:26] + "_"
        used.add(name)
        _sheet(wb, name, LINK_COLS, [_link_row(x, labels, brand_terms) for x in c["rows"]])
        if c["key"] == "L_pbn" and c.get("groups"):
            _sheet(wb, "Nhóm PBN theo IP", [("Chung", 26, None), ("Số website", 11, INT), ("Website", 100, None)],
                   [[g["where"], len(g["domains"]), ", ".join(g["domains"])] for g in c["groups"]])


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


def _by_source(wb, items: list[dict], latest: dict | None) -> None:
    """Số liệu theo nguồn (DataForSEO / Semrush / Gộp) + độ phủ."""
    from . import backlink_agg as AG
    sm = AG.summary(items)
    has_sr = bool(sm["semrush"]["links"])

    def v(key, f):
        val = sm[key][f]
        if key == "semrush" and not has_sr:
            return "chưa nhập"
        return round(val * 100) if f in ("dofollow", "home") and val is not None else val
    rows = [[lab] + [v(k, f) for k in ("dfs", "semrush", "all")]
            for lab, f in (("Website trỏ về", "domains"), ("Backlink", "links"), ("Trang đích có link", "pages"),
                           ("Tỷ lệ dofollow (%)", "dofollow"), ("Link về trang chủ (%)", "home"), ("Link ảnh", "image"))]
    cov_d, cov_l = sm["cover"]["domains"], sm["cover"]["links"]
    rows += [[""], ["Độ phủ", "Cả hai cùng thấy", "Chỉ DataForSEO", "Chỉ Semrush"],
             ["Website trỏ về", cov_d["both"], cov_d["dfs_only"], cov_d["semrush_only"]],
             ["Backlink", cov_l["both"], cov_l["dfs_only"], cov_l["semrush_only"]]]
    now = (latest or {}).get("now") or {}
    if now:
        rows += [[""], [f"DataForSEO báo tổng {now.get('backlinks')} backlink từ {now.get('referring_domains')} website "
                        f"(số tổng ngày {now.get('day')}); số ở bảng trên đếm từ danh sách link của từng nguồn."]]
    _sheet(wb, "Theo nguồn", [("Chỉ số", 28, None), ("DataForSEO", 14, INT), ("Semrush", 14, INT), ("Gộp", 14, INT)],
           rows)


def _agg_sheets(wb, items: list[dict], labels: dict, brand_terms: list[str], which: str) -> None:
    """Website trỏ về / Trang đích / Anchor text tính từ dữ liệu gộp, cột tách theo nguồn."""
    from . import backlink_agg as AG
    from . import site_labels as SL
    src = lambda ss: " + ".join(AG.SRC.get(x, x) for x in ss)  # noqa: E731
    if which in ("all", "domains"):
        _sheet(wb, "Website trỏ về", [
            ("Website", 30, None), ("Nhãn", 18, None), ("Nguồn", 20, None), ("Số link", 9, INT),
            ("Link DataForSEO", 12, INT), ("Link Semrush", 12, INT), ("Dofollow", 9, INT), ("Uy tín (DFS)", 11, INT),
            ("Ascore", 9, INT), ("Điểm spam", 10, INT), ("Trang đích", 10, INT), ("Số anchor", 10, INT),
            ("Quốc gia", 9, None), ("IP", 15, None), ("Google Safe Browsing", 18, None), ("Thấy lần đầu", 13, None)],
            [[g["domain"], ", ".join(SL.lookup(labels, g["domain"])), src(g["src"]), g["links"], g.get("dfs", 0),
              g.get("semrush", 0), g["dofollow"], g["rank"] or None, g["ascore"], g["spam"], g["targets"],
              g["anchors"], g["country"], g["ip"], SB_TYPES.get(g["threat"], g["threat"]) if g["threat"] else "",
              g["first"]] for g in AG.domains(items)])
    if which in ("all", "pages"):
        _sheet(wb, "Trang đích", [
            ("Trang đích", 70, None), ("Website trỏ về", 13, INT), ("Website DataForSEO", 14, INT),
            ("Website Semrush", 14, INT), ("Backlink", 10, INT), ("Dofollow", 9, INT), ("Mã trạng thái", 12, INT),
            ("Chuyển hướng tới", 50, None)],
            [[r["page"], r["domains"], r["dfs"], r["semrush"], r["links"], r["dofollow"], r["status"], r["redir"]]
             for r in AG.pages(items)])
    if which in ("all", "anchors"):
        rs = AG.anchors(items, brand_terms)
        ws = _sheet(wb, "Anchor text", [
            ("Anchor", 50, None), ("Loại", 13, None), ("Website", 10, INT), ("Website DataForSEO", 14, INT),
            ("Website Semrush", 14, INT), ("Tỷ lệ (%)", 10, None), ("Backlink", 10, INT), ("Thấy lần đầu", 13, None)],
            [[r["anchor"] or "(trống / ảnh)", AG.ANCHOR_TYPE[r["type"]], r["domains"], r["dfs"], r["semrush"],
              round(r["share"] * 100, 1), r["links"], r["first"]] for r in rs])
        mix = AG.anchor_mix(rs)
        ws.cell(row=len(rs) + 3, column=1, value="Cơ cấu (theo số website): " + " · ".join(
            f"{AG.ANCHOR_TYPE.get(k, k)} {v * 100:.0f}%" for k, v in mix.items()))


def _sources(wb, sources: dict) -> None:
    """Nguồn dữ liệu: trạng thái từng nguồn, các file đã nhập, thay đổi giữa hai lần nhập."""
    rows = [["DataForSEO", ""]] + [[k, v] for k, v in (sources.get("dfs") or {}).items()]
    rows += [[""], ["File Semrush đã nhập", ""]]
    for imp in sources.get("imports") or []:
        rows.append([f"{imp['who']} · {imp['kind']}", f"{imp['count']} dòng · nhập {imp['at']}"])
    if not sources.get("imports"):
        rows.append(["(chưa nhập file nào)", ""])
    for title, ch in sources.get("changes") or []:
        rows += [[""], [f"Thay đổi · {title}", f"+{len(ch['new'])} mới · −{len(ch['lost'])} không còn"],
                 ["Mới", ", ".join(ch["new"])], ["Không còn", ", ".join(ch["lost"])]]
    _sheet(wb, "Nguồn dữ liệu", [("Mục", 40, None), ("Giá trị", 100, None)], rows)


VENDOR_NAMES = (  # file cho khách: không nêu tên nhà cung cấp dữ liệu (thứ tự: cụm dài trước)
    (re.compile(r"(nguồn )?DataForSEO Backlinks API"), "nguồn dữ liệu backlink"),
    (re.compile(r"Page ascore \(Semrush\)"), "Điểm trang (nguồn 2)"),
    (re.compile(r"File Semrush đã nhập"), "File nguồn 2 đã nhập"),
    (re.compile(r"DataForSEO"), "nguồn 1"),
    (re.compile(r"\bDFS\b"), "nguồn 1"),
    (re.compile(r"Semrush"), "nguồn 2"),
)


def neutral_text(s: str) -> str:
    for pat, rep in VENDOR_NAMES:
        s = pat.sub(rep, s)
    return "N" + s[1:] if s.startswith("nguồn ") else s  # đầu ô / tên cột viết hoa


def _neutral_vendors(wb) -> None:
    """Đổi tên nhà cung cấp dữ liệu (DataForSEO, Semrush) thành "nguồn 1 / nguồn 2" ở mọi ô và tên sheet."""
    for ws in wb.worksheets:
        ws.title = neutral_text(ws.title)[:31]
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and not cell.value.startswith("="):
                    cell.value = neutral_text(cell.value)


def build(lists: dict, latest: dict | None, brand_terms: list[str], site: str, which: str = "all",
          client: bool = False, links: dict | None = None, labels: dict | None = None,
          sources: dict | None = None) -> bytes:
    """File Excel của trang Backlink, theo các tab: Tổng quan, Theo nguồn, Audit (mỗi mục một sheet link), Tất cả
    backlink, Website trỏ về / Trang đích / Anchor text (gộp DataForSEO + Semrush), Link mới - mất, Nguồn dữ liệu,
    Lịch sử. which: all | audit | links | domains | pages | anchors | changes. client: file cho khách hàng (không
    audit, không cột / dòng điểm spam). Chưa có danh sách link gộp: các sheet danh sách DataForSEO như trước."""
    from . import backlink_agg as AG
    wb = Workbook()
    wb.remove(wb.active)
    labels = labels or {}
    items = (links or {}).get("items") or []
    if which == "all":
        _overview(wb, latest, site)
        if items:
            _by_source(wb, items, latest)
    checks = [] if client else AG.full_audit(links, lists, brand_terms, labels)
    if which in ("all", "audit", "links"):
        if items:
            _link_audit(wb, checks, labels, brand_terms)
        elif not client:  # chưa có danh sách link: audit từ các danh sách tổng DataForSEO như trước
            _audit(wb, AU.audit(lists, brand_terms))
    if which in ("all", "links") and items:
        _links(wb, links, labels, brand_terms, sites=False)
    if items:
        _agg_sheets(wb, items, labels, brand_terms, which)
        if which in ("domains", "pages", "anchors"):  # xuất một tab: kèm các mục audit của tab đó
            _link_audit(wb, [c for c in checks if LINK_TAB.get(c["key"]) == which], labels, brand_terms)
    for kind in LIST_SHEETS:
        if (which in ("all", kind) or (kind == "changes" and which == "domains")) and kind in lists \
                and (not items or kind == "changes"):
            _list(wb, kind, lists[kind], brand_terms)
    if which in LIST_SHEETS and not items and not client:  # xuất một tab (chưa có link gộp): kiểm tra của tab đó
        _audit(wb, [c for c in AU.audit(lists, brand_terms) if AU.CHECK_TAB.get(c["key"]) == which], "Kiểm tra")
    if which == "all" and sources and not client:
        _sources(wb, sources)
    if which == "all" and "Lịch sử 12 tháng" in wb.sheetnames:  # lịch sử để cuối file
        wb.move_sheet("Lịch sử 12 tháng", offset=len(wb.sheetnames) - 1 - wb.sheetnames.index("Lịch sử 12 tháng"))
    if not wb.sheetnames:
        _sheet(wb, "Trống", [("Chưa có dữ liệu", 30, None)], [])
    if client:
        _drop_spam(wb)
        _neutral_vendors(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
