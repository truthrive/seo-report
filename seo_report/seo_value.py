"""Giá trị từ khóa: ghép số check rank (vị trí của mình và đối thủ trong top kết quả đã lưu) với số Google Ads
(volume, giá thầu, volume 12 tháng). Không gọi API: chỉ dùng dữ liệu đã có.

- share_of_voice / sov_trend: thị phần lượt click ước tính (volume × CTR theo vị trí) của mình và từng đối thủ,
  quy ra tiền theo CPC.
- forecast: mỗi từ khóa đang theo dõi nếu lên top 3 thì thêm bao nhiêu click và bao nhiêu tiền mỗi tháng, kèm mùa.
- check_advice: từ khóa có thể check thưa hơn (hằng tháng) mà không mất thông tin, và số tiền check rank tiết kiệm.
"""
import json
import sqlite3
from datetime import date

from . import aio as AO
from . import keyword_research as KR
from . import keywords as K
from . import rank as R
from . import rank_overview as RO

TOP10_CTR = sum(RO.CTR.values())  # tổng CTR 10 vị trí đầu: phần click tự nhiên chia nhau trên trang 1
STABLE_CHECKS = 4  # số lần check gần nhất dùng để coi là "đứng yên"
LOW_VOLUME = 20  # dưới mức này Google Ads gần như không có người tìm
MONTHLY_SET = "Check thưa (hằng tháng)"


def kw_metrics(con: sqlite3.Connection, kws: list[dict]) -> dict[int, dict]:
    """{keyword_id: {volume, cpc, monthly}}: volume ưu tiên số đã lưu khi lấy volume (bảng keyword_volume), thiếu thì
    lấy từ bảng giá thầu Google Ads; CPC và 12 tháng từ bảng giá thầu."""
    from . import volume as V
    vols = V.latest(con)
    KR.ensure_tables(con)
    cp = {f: (vol, lo, hi, mo) for f, vol, lo, hi, mo in con.execute(
        "SELECT fold, volume, low_bid, high_bid, monthly FROM kw_cpc")}
    out = {}
    for k in kws:
        c = cp.get(KR.ckey(k["keyword"]))
        v = (vols.get(k["id"]) or {}).get("volume")
        if v is None and c:
            v = c[0]
        if v is None and (k["id"] in vols or c):  # đã hỏi Google Ads mà không có số: gần như không ai tìm
            v = 0
        out[k["id"]] = {"volume": v, "cpc": KR.cpc({"low_bid": c[1], "high_bid": c[2]}) if c else None,
                        "monthly": [tuple(x) for x in json.loads(c[3] or "[]")] if c else []}
    return out


# ---- Thị phần tìm kiếm ----

def share_of_voice(con, cfg, end: date, set_id: int | None = None) -> dict:
    """Mỗi thương hiệu (mình + đối thủ): click ước tính / tháng trên bộ từ khóa = Σ volume × CTR(vị trí) ở lần check
    gần nhất, phần trăm trên tổng click trang 1 của bộ (Σ volume × tổng CTR top 10), giá trị = click × CPC, và
    thị phần lần check trước (cùng tập từ khóa) để so."""
    kws = RO._scope(con, cfg, end, set_id)
    m = kw_metrics(con, kws)
    serps = RO._latest_serps(con, kws)
    brands = AO.brands(con, cfg)
    acc = {b["id"]: {"brand": b, "clicks": 0.0, "value": 0.0, "kws": 0, "prev": 0.0, "now_cmp": 0.0} for b in brands}
    market = market_cmp = 0.0
    used = no_vol = n_cmp = 0
    for kid, (organic, _seen, before) in serps.items():
        vol = m[kid]["volume"] or 0
        if not vol:
            no_vol += 1
            continue
        used += 1
        price = m[kid]["cpc"] or 0
        market += vol * TOP10_CTR
        now = AO.brand_ranks(organic, brands)
        old = AO.brand_ranks(before, brands) if before is not None else None
        if old is not None:
            market_cmp += vol * TOP10_CTR
            n_cmp += 1
        for b in brands:
            a = acc[b["id"]]
            p = now.get(b["id"])
            c = vol * RO.ctr(p["rank"]) if p else 0.0
            a["clicks"] += c
            a["value"] += c * price
            a["kws"] += bool(p)
            if old is not None:
                a["now_cmp"] += c
                q = old.get(b["id"])
                a["prev"] += vol * RO.ctr(q["rank"]) if q else 0.0
    rows = []
    for a in acc.values():
        rows.append({"brand": a["brand"], "clicks": round(a["clicks"]), "value": round(a["value"]),
                     "share": a["clicks"] / market if market else 0.0, "keywords": a["kws"],
                     # so lần check trước trên cùng tập từ khóa; ít hơn nửa bộ có lần trước thì không so (dễ nhiễu)
                     "change": (a["now_cmp"] - a["prev"]) / market_cmp if market_cmp and n_cmp * 2 >= used else None})
    rows.sort(key=lambda r: (-r["clicks"], not r["brand"]["own"]))
    return {"rows": rows, "market": round(market), "keywords": used, "no_volume": no_vol, "total": len(kws),
            "compared": n_cmp,
            "currency": KR.currency(con, cfg)}


def sov_trend(con, cfg, end: date, set_id: int | None = None, limit: int = 12) -> list[dict]:
    """Thị phần click ước tính theo ngày check: [{date, n, share: {brand_id: 0–1}}]; chỉ từ khóa có volume."""
    kws = RO._scope(con, cfg, end, set_id)
    m = kw_metrics(con, kws)
    ids = [k["id"] for k in kws if m[k["id"]]["volume"]]
    if not ids:
        return []
    brands = AO.brands(con, cfg)
    by_day: dict[str, list[tuple[int, list]]] = {}
    for kid, d, organic, top10 in con.execute(
            f"SELECT keyword_id, check_date, organic, top10 FROM rank_serp WHERE keyword_id IN "
            f"({','.join('?' * len(ids))}) AND (organic IS NOT NULL OR top10 IS NOT NULL) ORDER BY check_date", ids):
        by_day.setdefault(d, []).append((kid, json.loads(organic) if organic else json.loads(top10 or "[]")))
    out = []
    for d, items in sorted(by_day.items())[-limit:]:
        clicks = {b["id"]: 0.0 for b in brands}
        market = 0.0
        for kid, organic in items:
            vol = m[kid]["volume"]
            market += vol * TOP10_CTR
            for bid, p in AO.brand_ranks(organic, brands).items():
                if p:
                    clicks[bid] += vol * RO.ctr(p["rank"])
        out.append({"date": d, "n": len(items), "share": {b: c / market for b, c in clicks.items()} if market else {}})
    return out


# ---- Dự báo khi lên top ----

def season(monthly: list[tuple[str, int]], today: date) -> dict:
    """Tháng cao điểm (theo 12 tháng gần nhất) và có sắp vào mùa không (2 tháng tới cao hơn trung bình năm 20%)."""
    if len(monthly) < 6:
        return {"peak": None, "soon": False}
    avg = sum(n for _, n in monthly) / len(monthly)
    by_month: dict[int, int] = {}
    for m, n in monthly:
        by_month[int(m[5:7])] = n
    peak = max(by_month, key=by_month.get)
    nxt = [by_month.get((today.month + i - 1) % 12 + 1) for i in (1, 2)]
    nxt = [n for n in nxt if n is not None]
    soon = bool(avg and nxt and sum(nxt) / len(nxt) >= avg * 1.2)
    return {"peak": peak if by_month[peak] >= avg * 1.2 else None, "soon": soon}


def forecast(con, cfg, end: date, target: int = 3, today: date | None = None) -> dict:
    """Từ khóa đang theo dõi chưa ở top `target`: click / tháng thêm được nếu lên vị trí `target` = volume ×
    (CTR(target) − CTR(hiện tại)), giá trị = click × CPC. Nhiều tiền trước (không có CPC thì theo click)."""
    today = today or date.today()
    kws = RO.active_keywords(con, cfg.site_url, end)
    m = kw_metrics(con, kws)
    rows = []
    for k in kws:
        v = m[k["id"]]
        if not v["volume"] or (k["rank"] is not None and k["rank"] <= target):
            continue
        gain = v["volume"] * (RO.ctr(target) - RO.ctr(k["rank"]))
        if gain <= 0:
            continue
        s = season(v["monthly"], today)
        rows.append({"id": k["id"], "keyword": k["keyword"], "rank": k["rank"], "set": k["set_name"],
                     "volume": v["volume"], "cpc": v["cpc"], "gain": round(gain),
                     "value": round(gain * v["cpc"]) if v["cpc"] else None, "peak": s["peak"], "soon": s["soon"],
                     "url": k.get("ranking_url") or k.get("target_url")})
    rows.sort(key=lambda r: (-(r["value"] or 0), -r["gain"]))
    no_vol = sum(1 for k in kws if not m[k["id"]]["volume"])
    return {"rows": rows, "gain": sum(r["gain"] for r in rows), "value": sum(r["value"] or 0 for r in rows),
            "target": target, "no_volume": no_vol, "currency": KR.currency(con, cfg)}


# ---- Gợi ý giảm chi phí check rank ----

def _why(ranks: list[int | None], vol: int | None) -> str | None:
    """Lý do có thể check thưa: đứng yên ở top 3, ở quá xa (ngoài top 50 / không thấy) nhiều lần liền, hoặc gần như
    không ai tìm."""
    if vol is not None and vol < LOW_VOLUME:
        return "low"
    last = ranks[-STABLE_CHECKS:]
    if len(last) < STABLE_CHECKS:
        return None
    if all(r is not None and r <= 3 for r in last) and max(last) - min(last) <= 1:
        return "stable"
    if all(r is None or r > 50 for r in last):
        return "far"
    return None


WHY = {"stable": "Đứng yên ở top 3 nhiều lần check liền", "far": "Không thấy trong độ sâu check (hoặc ngoài top 50) nhiều lần liền",
       "low": f"Gần như không ai tìm (volume dưới {LOW_VOLUME}/tháng)"}


def check_advice(con, cfg, end: date) -> dict:
    """Theo từng bộ team tạo (không gồm bộ Cam kết, bộ Nháp, bộ tạm dừng, bộ đã check hằng tháng): từ khóa nên chuyển
    sang check hằng tháng và tiền tiết kiệm mỗi tháng. {"sets": [...], "saving": USD/tháng}."""
    site = cfg.site_url
    out = []
    all_kws = R.keywords(con, site, end)
    m = kw_metrics(con, all_kws)
    for st in R.sets(con, site):
        sched = st["schedule"]
        per_month = R.checks_per_month(sched)
        if st["kind"] == "kpi" or st["draft"] or st["paused"] or per_month <= 1:
            continue
        items = []
        for k in all_kws:
            if k["set_id"] != st["id"] or k["paused"]:
                continue
            ranks = [r for _, r, _ in R.history(con, k["id"])]
            why = _why(ranks, m[k["id"]]["volume"])
            if not why:
                continue
            cost = R._pages(k["depth"]) * cfg.rank.price_per_page
            items.append({"id": k["id"], "keyword": k["keyword"], "rank": k["rank"], "why": why,
                          "volume": m[k["id"]]["volume"], "saving": cost * (per_month - 1)})
        if items:
            out.append({"set": st, "per_month": per_month, "items": items,
                        "saving": sum(i["saving"] for i in items),
                        "by_why": {w: sum(1 for i in items if i["why"] == w) for w in WHY}})
    return {"sets": out, "saving": sum(s["saving"] for s in out)}


def apply_advice(con, cfg, keyword_ids: list[int], user: str) -> dict:
    """Chuyển các từ khóa sang bộ "Check thưa (hằng tháng)" (tạo nếu chưa có, cùng độ sâu và nơi check với bộ cũ đầu
    tiên). Giữ nguyên lịch sử."""
    site = cfg.site_url
    dest = next((s for s in R.sets(con, site) if s["name"] == MONTHLY_SET), None)
    if not dest:
        src = next((s for s in R.sets(con, site) if s["kind"] != "kpi"), None)
        base = dict(src["schedule"]) if src else {"depth": 20, "time": "07:00"}
        schedule = {**base, "type": "monthly", "day": 1, "weekdays": []}
        sid = R.create_set(con, site, MONTHLY_SET, user, settings=(src or {}).get("settings"), schedule=schedule,
                           state="active")
    else:
        sid = dest["id"]
    return R.move_keywords(con, site, keyword_ids, sid, user)
