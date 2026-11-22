"""Local SEO trong các phần phân tích chung của tool (không gọi AI, chỉ tính số):

1. Tín hiệu cho Bản tin AI (trang Tổng quan): chi nhánh cần chú ý (cờ của local_branches), mục hồ sơ cần sửa.
   Đánh giá thấp chưa trả lời đã vào qua chuông thông báo nên không lặp lại ở đây.
2. Dòng số liệu Google Maps cho nhận xét báo cáo tuần / tháng (AI viết nhận xét chỉ dùng số trong các dòng này).
3. Tín hiệu chéo Maps ↔ phần khác của tool:
   - từ khóa khách hay tìm thấy trên Maps chưa có trong bộ theo dõi thứ hạng;
   - tìm tên thương hiệu giảm cùng lúc trên Maps và Google Search (Search Console);
   - click website từ Maps lệch chiều với phiên Organic Search (GA4).
Mỗi tín hiệu: (nhóm, mức tối đa high | medium | low, câu sự thật có số, link)."""
import unicodedata
from datetime import date, timedelta

from . import gbp as G
from . import local_branches as LB

GENERIC = ("mắt kính", "kính mắt", "nha khoa", "cửa hàng", "shop", "spa", "phòng khám", "công ty", "thẩm mỹ viện",
           "salon", "nhà hàng", "quán")
PLACES = ("quan", "phuong", "duong", "huyen", "thanhpho", "tp")


def fold(s) -> str:
    """Chữ thường, bỏ dấu, bỏ khoảng trắng: "Tâm Đức" / "tam duc" / "tamduc" so khớp được với nhau."""
    s = unicodedata.normalize("NFD", str(s or "").lower()).replace("đ", "d")
    return "".join(c for c in s if unicodedata.category(c) != "Mn" and not c.isspace())


def _pct(now, before) -> str:
    return f"{(now - before) / before * 100:+.0f}%".replace(".", ",") if before else ""


def _n(v) -> str:
    return f"{v:,.0f}".replace(",", ".")


def brand_tokens(con, site: str, locs: list[dict]) -> list[str]:
    """Tên thương hiệu đã bỏ dấu: thương hiệu của mình ở AI Overview (tên + cách gọi khác), không có thì lấy phần
    chung của tên hồ sơ, bỏ chữ chung chung ("Mắt Kính Tâm Đức" → "tamduc")."""
    names: list[str] = []
    try:
        for name, aliases in con.execute("SELECT name, aliases FROM aio_brands WHERE site = ? AND own = 1", (site,)):
            names += [name] + [a for a in (aliases or "").splitlines() if a.strip()]
    except Exception:  # noqa: BLE001 (chưa có bảng)
        pass
    if not names and locs:
        base = (locs[0].get("title") or "").split(" - ")[0].strip().lower()
        for g in GENERIC:
            base = base.replace(g, " ")
        names = [base]
    out = []
    for n in names:
        f = fold(n)
        for g in GENERIC:
            f = f.replace(fold(g), "") if f != fold(g) else f
        if len(f) >= 4 and f not in out:
            out.append(f)
    return out


# ---------------------------------------------------------------- 1. chi nhánh + hồ sơ
def branch_signals(con, site: str, locs: list[dict], days: int = 28, today: date | None = None) -> list[tuple]:
    if len(locs) < 2:
        return []
    out = []
    rows = LB.compare(con, locs, site, days, today=today)["rows"]
    for r in rows:
        flags = [(t, x) for t, x in r["flags"] if "chưa trả lời" not in x]  # đã có ở chuông thông báo
        if not flags:
            continue
        lvl = "medium" if any(t == "red" for t, _ in flags) else "low"
        out.append(("Local SEO", lvl, f"Chi nhánh {r['short']} ({days} ngày): " + "; ".join(x for _, x in flags[:3]),
                    "/local"))
        if len(out) >= 4:
            break
    return out


def profile_signals(locs: list[dict], site: str) -> list[tuple]:
    issues: dict[str, dict] = {}
    for x in locs:
        if not x.get("data"):
            continue
        for c in G.audit(x, site):
            if c["level"] in ("high", "medium"):
                issues.setdefault(c["key"], {"c": c, "n": []})["n"].append(LB.short(x["title"]))
    out = []
    for g in sorted(issues.values(), key=lambda g: (g["c"]["level"] != "high", -len(g["n"]))):
        where = (f"cả {len(g['n'])} chi nhánh" if len(g["n"]) == len(locs) > 1 else
                 f"{len(g['n'])} chi nhánh: " + ", ".join(g["n"][:4]) + ("…" if len(g["n"]) > 4 else "")
                 if len(g["n"]) > 1 else g["n"][0])
        out.append(("Local SEO", "medium" if g["c"]["level"] == "high" else "low",
                    f"Hồ sơ Google Maps: {g['c']['title']} · {where}", "/local?tab=profile"))
    return out[:3]


# ---------------------------------------------------------------- 3. tín hiệu chéo
def _months(con, names) -> list[str]:
    return G.keyword_months(con, names)


def _maps_keywords(con, names: list[str], month: str) -> dict[str, int]:
    marks = ",".join("?" * len(names))
    return {k: v for k, v in con.execute(
        f"SELECT keyword, SUM(value) FROM gbp_keywords WHERE location IN ({marks}) AND month = ? AND value IS NOT NULL "
        "GROUP BY keyword", (*names, month))}


def untracked_keywords(con, site: str, names: list[str], brands: list[str], limit: int = 3) -> tuple | None:
    """Từ khóa khách tìm rồi thấy hồ sơ trên Maps (tháng gần nhất), nhiều lượt, không phải tên thương hiệu / địa chỉ,
    chưa có trong bộ theo dõi thứ hạng."""
    ms = _months(con, names)
    if not ms:
        return None
    cur = _maps_keywords(con, names, ms[-1])
    try:
        tracked = {fold(k) for (k,) in con.execute("SELECT keyword FROM rank_keywords WHERE site = ? AND removed_at "
                                                   "IS NULL", (site,))}
    except Exception:  # noqa: BLE001
        tracked = set()
    try:  # tên đối thủ đã khai ở AI Overview: khách tìm tên đối thủ thì không phải từ khóa nên theo dõi
        rivals = [fold(x) for n_, a_ in con.execute("SELECT name, aliases FROM aio_brands WHERE site = ? AND own = 0",
                                                    (site,)) for x in [n_] + (a_ or "").splitlines() if x.strip()]
    except Exception:  # noqa: BLE001
        rivals = []
    skip = [x for x in brands + rivals if len(x) >= 4]
    pick = [(k, v) for k, v in sorted(cur.items(), key=lambda x: -x[1])
            if v >= 100 and "," not in k and len(fold(k)) > 4 and fold(k) not in tracked
            and not (fold(k).startswith(PLACES) and len(k.split()) <= 3)  # "quận 11", "đường 3/2": tên địa điểm
            and not any(b in fold(k) for b in skip)]
    if not pick:
        return None
    pick = pick[:limit]
    return ("Local SEO", "low", f"{len(pick)} từ khóa khách hay tìm thấy hồ sơ trên Maps (tháng {ms[-1][5:]}/"
            f"{ms[-1][:4]}) chưa có trong bộ theo dõi thứ hạng: "
            + "; ".join(f"“{k}” {_n(v)} lượt" for k, v in pick), "/rank")


def _gsc_brand(con, site: str, brands: list[str], month: str) -> int | None:
    """Lượt hiển thị Google Search của truy vấn chứa tên thương hiệu trong tháng (YYYY-MM)."""
    y, m = int(month[:4]), int(month[5:])
    a = date(y, m, 1)
    b = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    try:
        rows = con.execute(
            "SELECT q.text, SUM(d.impressions) FROM gsc_query_daily d JOIN pages p ON p.id = d.page_id "
            "JOIN queries q ON q.id = d.query_id WHERE p.site = ? AND d.date BETWEEN ? AND ? GROUP BY d.query_id",
            (site, a.isoformat(), b.isoformat())).fetchall()
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    return sum(v for t, v in rows if any(br in fold(t) for br in brands))


def brand_drop(con, site: str, names: list[str], brands: list[str], drop: float = 0.15) -> tuple | None:
    """Tìm tên thương hiệu giảm cùng lúc trên Maps và Google Search (tháng gần nhất có số Maps so với tháng trước)."""
    ms = _months(con, names)
    if len(ms) < 2 or not brands:
        return None
    m1, m0 = ms[-1], ms[-2]
    maps1 = sum(v for k, v in _maps_keywords(con, names, m1).items() if any(b in fold(k) for b in brands))
    maps0 = sum(v for k, v in _maps_keywords(con, names, m0).items() if any(b in fold(k) for b in brands))
    if not maps0 or maps1 > maps0 * (1 - drop):
        return None
    g1, g0 = _gsc_brand(con, site, brands, m1), _gsc_brand(con, site, brands, m0)
    if not g0 or g1 is None or g1 > g0 * (1 - drop):
        return None
    return ("Local SEO", "medium", f"Tìm tên thương hiệu giảm cả hai nơi tháng {m1[5:]}/{m1[:4]}: Maps {_n(maps0)} → "
            f"{_n(maps1)} lượt ({_pct(maps1, maps0)}), Google Search {_n(g0)} → {_n(g1)} lượt hiển thị "
            f"({_pct(g1, g0)})", "/local")


def web_vs_organic(con, names: list[str], cur: tuple[date, date], prev: tuple[date, date],
                   organic: dict | None) -> tuple | None:
    """Click website từ Maps và phiên Organic Search (GA4) cùng kỳ báo cáo đi ngược chiều / cùng giảm mạnh."""
    if not organic or organic.get("error") or not organic.get("prev"):
        return None
    last = G.complete_day(con)
    if not last or date.fromisoformat(last) < cur[1]:
        return None  # số Maps của kỳ chưa đủ
    w1 = G.totals(con, names, *cur).get("WEBSITE_CLICKS", 0)
    w0 = G.totals(con, names, *prev).get("WEBSITE_CLICKS", 0)
    s1, s0 = organic["sessions"], organic["prev"]
    if w0 < 30:
        return None
    wc, sc = (w1 - w0) / w0, (s1 - s0) / s0
    fact = (f"Click website từ Maps {_n(w0)} → {_n(w1)} ({_pct(w1, w0)}); phiên Organic Search (GA4) {_n(s0)} → "
            f"{_n(s1)} ({_pct(s1, s0)})")
    if wc >= 0.2 and sc <= 0:
        return ("Local SEO", "low", fact + ": khách từ Maps vào web nhiều hơn mà phiên Organic không tăng", "/local")
    if wc <= -0.2 and sc <= -0.1:
        return ("Local SEO", "medium", fact + ": cả hai cùng giảm", "/local")
    return None


def cross_signals(con, site: str, locs: list[dict], rep=None) -> list[tuple]:
    names = [x["name"] for x in locs]
    brands = brand_tokens(con, site, locs)
    out = [untracked_keywords(con, site, names, brands), brand_drop(con, site, names, brands)]
    if rep is not None:
        out.append(web_vs_organic(con, names, rep.week, rep.prev_week, getattr(rep, "organic", None)))
    return [x for x in out if x]


_CACHE: dict = {}  # tính mất ~1 giây (đọc Search Console theo tháng): giữ lại tới khi số đổi hoặc quá 30 phút


def _stamp(con) -> tuple:
    """Dấu thay đổi dữ liệu: đổi khi lấy số Maps mới, có đánh giá / trả lời mới, đổi bộ theo dõi thứ hạng."""
    def one(q):
        try:
            return con.execute(q).fetchone()[0]
        except Exception:  # noqa: BLE001
            return None
    return (one("SELECT MAX(fetched_at) FROM gbp_locations"), one("SELECT MAX(day) FROM gbp_daily"),
            one("SELECT COUNT(*) FROM gbp_reviews WHERE reply IS NULL OR reply = ''"),
            one("SELECT COUNT(*) FROM rank_keywords WHERE removed_at IS NULL"))


def brief_signals(con, site: str, today: date | None = None, rep=None) -> list[tuple]:
    """Mọi tín hiệu Local SEO cho Bản tin AI."""
    import time
    locs = G.linked(con)
    if not locs:
        return []
    org = getattr(rep, "organic", None) or {}
    key = (site, str(today or date.today()), _stamp(con), getattr(rep, "week", None), org.get("sessions"))
    hit = _CACHE.get(site)
    if hit and hit[0] == key and time.time() - hit[1] < 1800:
        return hit[2]
    out = branch_signals(con, site, locs, today=today) + profile_signals(locs, site) + cross_signals(
        con, site, locs, rep)
    _CACHE[site] = (key, time.time(), out)
    return out


# ---------------------------------------------------------------- 2. dòng số cho nhận xét báo cáo
def report_lines(con, site: str, rep) -> list[str]:
    """Số Google Maps của kỳ báo cáo (cùng kỳ / kỳ trước với báo cáo) + chi nhánh cần chú ý + tín hiệu chéo."""
    locs = G.linked(con)
    if not locs:
        return []
    names = [x["name"] for x in locs]
    (a, b), (pa, pb) = rep.week, rep.prev_week
    out = []
    last = G.complete_day(con)
    if last and date.fromisoformat(last) >= a:
        end = min(b, date.fromisoformat(last))
        pend = pb - (b - end)
        now, pre = G.totals(con, names, a, end), G.totals(con, names, pa, pend)

        def item(label, k):
            return f"{label} {_n(now.get(k, 0))}" + (f" ({_pct(now.get(k, 0), pre.get(k, 0))})" if pre.get(k) else "")
        line = (f"Google Maps / Local SEO ({len(locs)} hồ sơ): " + "; ".join(
            item(lab, k) for lab, k in (("lượt xem hồ sơ", "views"), ("cuộc gọi", "CALL_CLICKS"),
                                        ("chỉ đường", "BUSINESS_DIRECTION_REQUESTS"), ("click website", "WEBSITE_CLICKS"))))
        if end < b:
            line += f" (số Maps tới {end:%d/%m}, Google trả chậm vài ngày)"
        out.append(line)
    rs = [r for r in LB.GR.rows(con, names)]
    cur = LB.review_block(rs, a, b)
    pre = LB.review_block(rs, pa, pb)
    if cur["total"] or pre["total"]:
        low_un = sum(1 for r in rs if not r["reply"] and (r["rating"] or 0) in LB.LOW)
        out.append(f"Đánh giá Google Maps trong kỳ: {cur['total']} mới (kỳ trước {pre['total']})"
                   + (f", điểm TB {cur['avg']:.2f}".replace(".", ",") if cur["avg"] else "")
                   + f", 1–3 sao {cur['low']}" + (f" ({cur['low_share'] * 100:.1f}%)".replace(".", ",")
                                                 if cur["low_share"] is not None else "")
                   + f"; đánh giá 1–3 sao còn chưa trả lời: {low_un}")
    days = (b - a).days + 1
    for _, _, fact, _ in branch_signals(con, site, locs, days=days, today=b) + profile_signals(locs, site):
        out.append(f"Điểm tool tự phát hiện (Local SEO): {fact}")
    for _, _, fact, _ in cross_signals(con, site, locs, rep):
        out.append(f"Điểm tool tự phát hiện (Local SEO): {fact}")
    return out
