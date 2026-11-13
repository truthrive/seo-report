"""Audit backlink theo từng link (dữ liệu backlink_links), không gọi thêm API.

Mỗi mục: {"key", "level" (high | medium | info | ok), "title", "count", "unit", "why", "action", "rows" (các link
thuộc mục), "mix" (cơ cấu %, chỉ mục tham khảo), "suggest" (gợi ý nhãn)}. Ngưỡng là quy ước hay dùng, không phải quy
định của Google; "spam" là chấm điểm của DataForSEO.
"""
import ipaddress

from .backlink_audit import anchor_type

SPAM = 50                  # điểm spam của một link
PBN_MIN = 3                # số website khác nhau cùng IP / cùng dải /24 để nghi PBN
FARM = 100                 # số link ra ngoài của trang nguồn
ANCHOR_PAGE_MIN = 5        # trang đích có từ chừng này link mới xét cơ cấu anchor
ANCHOR_PAGE_SHARE = 0.5
OUTSIDE = {"footer", "nav", "aside"}          # vị trí ngoài nội dung bài
# "header" không tính là ngoài bài: thường là phần đầu của chính bài viết (<article><header>…)
INSIDE = {"article", "main", "section", "p", "summary", "blockquote", "figure", "details", "header"}
QUALITY_RANK = 100         # uy tín website tối thiểu của "link chất lượng" (thang 0–1000)
LANGS_OK = {"vi", ""}
# dải IP của CDN / hosting dùng chung lớn: nhiều website không liên quan cùng IP, không tính là PBN
CDN_NETS = [ipaddress.ip_network(n) for n in (
    "104.16.0.0/13", "172.64.0.0/13", "162.158.0.0/15", "188.114.96.0/20", "141.101.64.0/18", "108.162.192.0/18",
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "190.93.240.0/20", "197.234.240.0/22",
    "198.41.128.0/17", "131.0.72.0/22",  # Cloudflare
    "151.101.0.0/16", "199.232.0.0/16",  # Fastly
    "13.32.0.0/15", "13.224.0.0/14", "18.64.0.0/14", "52.84.0.0/15", "54.230.0.0/16", "99.84.0.0/16",  # CloudFront
    "185.199.108.0/22", "192.0.78.0/23", "192.0.64.0/18",  # GitHub Pages, WordPress.com
    "216.239.32.0/19", "142.250.0.0/15", "172.217.0.0/16",  # Google (Blogger, Sites)
)]
PLATFORM_LABEL = {"news": "Báo PR", "message-boards": "Diễn đàn", "blogs": "Web 2.0", "wikis": "Web 2.0"}
LOC_NAME = {"article": "trong bài", "main": "trong bài", "section": "trong bài", "p": "trong bài",
            "summary": "trong bài", "blockquote": "trong bài", "figure": "trong bài", "details": "trong bài",
            "header": "đầu bài / trang", "footer": "chân trang", "nav": "menu", "aside": "thanh bên"}


def _cdn(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return a.is_private or any(a in n for n in CDN_NETS)


def _subnet(ip: str) -> str:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    return str(ipaddress.ip_network(f"{ip}/24", strict=False)) if a.version == 4 else ""


def place(x: dict) -> str:
    """Vị trí đặt link dễ đọc."""
    return LOC_NAME.get((x.get("loc") or "").lower(), "khác" if x.get("loc") else "không rõ")


def pbn_groups(items: list[dict]) -> list[dict]:
    """Nhóm website cùng IP (hoặc cùng dải /24) mà từ PBN_MIN website khác nhau trở lên; bỏ IP CDN / hosting chung."""
    by_ip: dict[str, set] = {}
    by_net: dict[str, set] = {}
    for x in items:
        ip = x.get("ip") or ""
        if not ip or _cdn(ip):
            continue
        by_ip.setdefault(ip, set()).add(x["d_from"])
        net = _subnet(ip)
        if net:
            by_net.setdefault(net, set()).add(x["d_from"])
    out, seen = [], set()
    for ip, doms in sorted(by_ip.items(), key=lambda kv: -len(kv[1])):
        if len(doms) >= PBN_MIN:
            out.append({"where": f"IP {ip}", "domains": sorted(doms)})
            seen |= doms
    for net, doms in sorted(by_net.items(), key=lambda kv: -len(kv[1])):
        if len(doms) >= PBN_MIN and not doms <= seen:
            out.append({"where": f"dải IP {net}", "domains": sorted(doms)})
            seen |= doms
    return out


def audit(items: list[dict], prev: list[dict] | None, brand_terms: list[str], labels: dict | None = None) -> list[dict]:
    """items: danh sách link lần mới nhất; prev: lần trước (None khi chưa có); labels: {tên miền: [nhãn]} để gợi ý."""
    from . import backlink_links as BLL
    from . import site_labels as SL
    out = []

    def add(key, level, title, rows, unit, why, action, **kw):
        out.append({"key": key, "level": level if rows else "ok", "title": title, "count": kw.pop("count", len(rows)),
                    "unit": unit, "why": why, "action": action, "rows": rows, **kw})

    broken = [x for x in items if x.get("broken") or (x.get("st_to") or 0) >= 400]
    add("L_broken", "high", "Link trỏ về trang lỗi", broken, "link",
        "Website khác link về trang đang trả lỗi (404…): giá trị của link bị mất.",
        "Đặt redirect 301 từ trang lỗi về trang gần nhất, hoặc xin chủ website sửa link.")
    if items and all("threat" in x for x in items):  # đã hỏi Google Safe Browsing
        bad = [x for x in items if x.get("threat")]
        add("L_threat", "high", "Website nguồn bị Google đánh dấu nguy hiểm", bad, "link",
            "Google Safe Browsing đánh dấu trang / website đặt link là mã độc, lừa đảo hoặc phần mềm có hại: link từ "
            "đây gây hại cho uy tín website.", "Đưa các website này vào file disavow ngay.", disavow=True)
    toxic = sorted([x for x in items if (x.get("spam") or 0) >= SPAM], key=lambda x: -(x.get("spam") or 0))
    add("L_spam", "high", "Link spam", toxic, "link",
        f"Điểm spam của link từ {SPAM}/100 (DataForSEO): thường từ trang bán backlink hàng loạt.",
        "Xem lại từng website; website rõ là spam thì đưa vào file disavow nộp ở Google Search Console.", disavow=True)
    groups = pbn_groups(items)
    pbn_doms = {d for g in groups for d in g["domains"]}
    add("L_pbn", "high", "Nghi ngờ mạng PBN", [x for x in items if x["d_from"] in pbn_doms], "website",
        f"Từ {PBN_MIN} website khác nhau dùng chung IP máy chủ hoặc chung dải IP trỏ về site: dấu hiệu mạng blog vệ "
        "tinh. Đã bỏ qua IP của CDN / hosting dùng chung lớn, nhưng hosting nhỏ dùng chung vẫn có thể báo nhầm.",
        "Mở từng website kiểm tra; đúng là PBN thì gắn nhãn PBN và cân nhắc disavow.",
        count=len(pbn_doms), groups=groups)

    # cơ cấu anchor theo từng trang đích
    by_page: dict[str, list[dict]] = {}
    for x in items:
        by_page.setdefault(BLL._page(x["u_to"]), []).append(x)
    heavy_pages = []
    for p, xs in by_page.items():
        if len(xs) >= ANCHOR_PAGE_MIN:
            kw = sum(1 for x in xs if anchor_type(x["anchor"], brand_terms) == "keyword")
            if kw / len(xs) > ANCHOR_PAGE_SHARE:
                heavy_pages.append((p, xs))
    add("L_anchor_page", "medium", "Anchor từ khóa dồn vào một trang", [x for _, xs in heavy_pages for x in xs],
        "trang", f"Trang đích có trên {int(ANCHOR_PAGE_SHARE * 100)}% link dùng anchor là từ khóa: dấu hiệu tối ưu quá "
        "mức với chính trang đó.", "Link mới về các trang này nên dùng anchor thương hiệu / URL / chữ chung chung.",
        count=len(heavy_pages))
    outside = [x for x in items if (x.get("loc") or "").lower() in OUTSIDE or (x.get("same") or 1) > 1
               or x.get("sitewide")]  # Semrush đánh dấu sitewide
    add("L_sitewide", "medium", "Link sitewide / ngoài bài viết", outside, "link",
        "Link ở chân trang, menu, thanh bên hoặc lặp nhiều lần trên cùng trang: thường là link đặt trên mọi trang, "
        "giá trị thấp và dễ bị coi là mua bán.", "Đối tác thật thì nên để nofollow; không rõ nguồn thì xem xét disavow.")
    farm = [x for x in items if (x.get("ext") or 0) > FARM]
    add("L_farm", "info", "Trang nguồn có quá nhiều link ra ngoài", farm, "website",
        f"Trang đặt link có hơn {FARM} link ra website khác: kiểu trang “trại link”, giá trị mỗi link rất thấp.",
        "Không nên mua / xin thêm link từ các trang này; trang spam thì đưa vào disavow.",
        count=len({x["d_from"] for x in farm}))
    foreign = [x for x in items if (x.get("lang") or "") not in LANGS_OK
               and (x.get("country") or "").upper() not in ("", "VN")]
    add("L_foreign", "medium", "Nguồn khác ngôn ngữ / quốc gia", foreign, "link",
        "Trang không phải tiếng Việt, website ở nước ngoài: với website bán hàng tại Việt Nam, loại link này thường "
        "đến từ spam hoặc dịch vụ backlink giá rẻ.", "Xem lại; website spam thì đưa vào disavow.")
    bad_ids = {id(x) for x in broken}
    redirect = [x for x in items if id(x) not in bad_ids and (300 <= (x.get("st_to") or 0) < 400 or x.get("redir"))]
    add("L_redirect", "medium", "Link trỏ về trang đang chuyển hướng", redirect, "link",
        "Trang đích đã chuyển (301 / 308): link vẫn được tính nhưng qua một bước chuyển.",
        "Với website quan trọng, xin họ đổi link sang URL mới.")
    no_alt = [x for x in items if x.get("type") == "image" and not (x.get("alt") or "").strip()]
    add("L_img_alt", "medium", "Link ảnh thiếu alt", no_alt, "link",
        "Link là ảnh nhưng không có alt: Google không có chữ để hiểu link nói về gì.",
        "Khi đặt link ảnh, xin thêm alt mô tả (tên thương hiệu / chủ đề trang đích).")
    if prev is not None:
        new, lost = BLL.diff(items, prev)
        add("L_lost", "medium", "Link mất so với lần lấy trước", sorted(lost, key=lambda x: -(x.get("d_rank") or 0)),
            "link", "Link có ở lần lấy trước nhưng lần này không còn: trang nguồn đã xóa link, đổi link hoặc bị gỡ.",
            "Link từ website tốt (uy tín cao, không spam): liên hệ xin đặt lại.")
        add("L_new", "info", "Link mới so với lần lấy trước", new, "link",
            "Link lần này mới thấy, lần lấy trước chưa có.", "Xem nhanh: link lạ / spam thì xử lý sớm.")

    # tham khảo
    n = len(items) or 1
    follow = {"dofollow": sum(1 for x in items if x["follow"])}
    follow["nofollow"] = len(items) - follow["dofollow"]
    for a in ("sponsored", "ugc"):
        follow[a] = sum(1 for x in items if a in (x.get("attrs") or []))
    add("L_follow", "info", "Tỷ lệ dofollow / nofollow", items, "% dofollow",
        "Hồ sơ tự nhiên có cả dofollow và nofollow; link sponsored / ugc là link quảng cáo / người dùng đăng.",
        "Tham khảo.", count=round(follow["dofollow"] / n * 100), mix={k: round(v / n * 100) for k, v in follow.items()})
    places: dict[str, int] = {}
    for x in items:
        places[place(x)] = places.get(place(x), 0) + 1
    add("L_place", "info", "Vị trí đặt link", items, "% trong bài",
        "Link nằm trong nội dung bài có giá trị hơn link ở chân trang / menu / thanh bên.", "Tham khảo.",
        count=round(places.get("trong bài", 0) / n * 100), mix={k: round(v / n * 100) for k, v in places.items()})
    good = [x for x in items if x["follow"] and (x.get("loc") or "").lower() in INSIDE and (x.get("spam") or 0) < 30
            and ((x.get("kw100") or 0) > 0 or (x.get("d_rank") or 0) >= QUALITY_RANK)]
    add("L_quality", "info", "Link chất lượng", good, "link",
        f"Dofollow, nằm trong bài, điểm spam dưới 30, và website nguồn có uy tín từ {QUALITY_RANK}/1000 hoặc trang "
        "nguồn có từ khóa trong top 100 Google: nhóm link nên giữ.",
        "Giữ quan hệ với các website này; xin thêm bài / link.")
    sugg: dict[str, set] = {}
    table = labels or {}
    for x in items:
        if SL.lookup(table, x["d_from"]):
            continue
        for p_ in x.get("platform") or []:
            lab = PLATFORM_LABEL.get(p_)
            if lab:
                sugg.setdefault(x["d_from"], set()).add(lab)
    add("L_platform", "info", "Gợi ý nhãn theo loại website", [x for x in items if x["d_from"] in sugg], "website",
        "DataForSEO phân loại website nguồn (báo, diễn đàn, blog, wiki). Chỉ là gợi ý: bấm xác nhận thì mới gắn nhãn.",
        "Xem và xác nhận nhãn gợi ý.", count=len(sugg), suggest={d: sorted(v) for d, v in sugg.items()})
    homes = sum(1 for x in items if BLL._page(x["u_to"]).count("/") == 0)
    add("L_targets", "info", "Phân bố trang đích", items, "% về trang chủ",
        "Link dồn hết vào trang chủ thì các trang danh mục / sản phẩm ít được đẩy.", "Tham khảo.",
        count=round(homes / n * 100), mix={"trang chủ": round(homes / n * 100),
                                         "trang khác": 100 - round(homes / n * 100)})
    order = {"high": 0, "medium": 1, "info": 2, "ok": 3}
    return sorted(out, key=lambda c: order[c["level"]])


def disavow(items: list[dict], generated: str = "") -> str:
    """File disavow: website có link điểm spam từ SPAM."""
    doms = sorted({x["d_from"] for x in items if ((x.get("spam") or 0) >= SPAM or x.get("threat")) and x.get("d_from")})
    head = [f"# Disavow do SEO Report tạo {generated}".rstrip(),
            f"# Website có link điểm spam >= {SPAM} (DataForSEO) hoặc bị Google Safe Browsing đánh dấu nguy hiểm.",
            "# Xem lại từng dòng trước khi nộp cho Google."]
    return "\n".join(head + [f"domain:{d}" for d in doms]) + "\n"
