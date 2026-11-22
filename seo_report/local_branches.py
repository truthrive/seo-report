"""Local SEO · so sánh chi nhánh: hiệu suất hồ sơ, đánh giá (sao thấp đến từ đâu, tỉ lệ), tốc độ trả lời, bài đăng,
lỗi hồ sơ của từng chi nhánh trong cùng một kỳ, kèm lý do "cần chú ý" để quản lý biết vào chi nhánh nào trước.

Kỳ hiệu suất kết thúc ở ngày Google có số gần nhất (trễ vài ngày); kỳ đánh giá kết thúc hôm nay (đánh giá về ngay).
"""
import json
from datetime import date, datetime, timedelta, timezone

from . import gbp as G
from . import gbp_reviews as GR

LOW = (1, 2, 3)  # "sao thấp": 1–3 sao (cùng nghĩa với thẻ "Chưa trả lời" và chuông)


def short(title: str) -> str:
    """“Mắt Kính Tâm Đức - Gò Vấp” → “Gò Vấp” (tên chi nhánh ngắn cho bảng / biểu đồ)."""
    parts = [p.strip() for p in (title or "").split(" - ") if p.strip()]
    return parts[-1] if len(parts) > 1 else (title or "")


def _in(iso: str | None, a: date, b: date) -> bool:
    return bool(iso) and a.isoformat() <= iso[:10] <= b.isoformat()


def review_block(rs: list[dict], a: date, b: date) -> dict:
    """Đánh giá viết trong [a, b]: số, phân bố sao, điểm TB, số / tỉ lệ sao thấp."""
    got = [r for r in rs if _in(r["created"], a, b) and r["rating"]]
    stars = {s: sum(1 for r in got if r["rating"] == s) for s in range(5, 0, -1)}
    low = sum(stars[s] for s in LOW)
    return {"total": len(got), "stars": stars, "avg": round(sum(r["rating"] for r in got) / len(got), 2) if got else None,
            "low": low, "low_share": low / len(got) if got else None}


def _posts_by_location(con) -> dict[str, list[str]]:
    """Ngày đăng (YYYY-MM-DD) của các bài đã hiện trên Google, theo chi nhánh."""
    try:
        rows = con.execute("SELECT locations, results, posted_at FROM gbp_posts WHERE posted_at IS NOT NULL").fetchall()
    except Exception:  # noqa: BLE001 (chưa có bảng bài đăng)
        return {}
    out: dict[str, list[str]] = {}
    for locs, results, at in rows:
        res = json.loads(results or "{}")
        for loc in json.loads(locs or "[]"):
            if (res.get(loc) or {}).get("name"):
                out.setdefault(loc, []).append((at or "")[:10])
    return out


def compare(con, locs: list[dict], site: str, days: int, today: date | None = None) -> dict:
    """Số của từng chi nhánh trong kỳ `days` ngày (và kỳ liền trước để so):
    {"rows": [...], "totals": {...}, "perf_period", "review_period"}. Mỗi dòng có "flags" (lý do cần chú ý) và
    "score" (càng cao càng cần xem trước)."""
    today = today or date.today()
    names = [x["name"] for x in locs]
    last = G.complete_day(con)
    p_end = min(date.fromisoformat(last), today) if last else today  # kỳ báo cáo cũ: không lấy số sau ngày cuối kỳ
    p_start = p_end - timedelta(days=days - 1)
    pp_end, pp_start = p_start - timedelta(days=1), p_start - timedelta(days=days)
    r_end, r_start = today, today - timedelta(days=days - 1)
    rp_end, rp_start = r_start - timedelta(days=1), r_start - timedelta(days=days)
    all_reviews = GR.rows(con, names)
    by_loc: dict[str, list[dict]] = {}
    for r in all_reviews:
        by_loc.setdefault(r["location"], []).append(r)
    speed = GR.reply_speed(all_reviews, today=today)
    posts = _posts_by_location(con)
    rows = []
    for x in locs:
        n = x["name"]
        now, prev = G.totals(con, [n], p_start, p_end), G.totals(con, [n], pp_start, pp_end)
        acts = sum(now.get(k, 0) for k in ("CALL_CLICKS", "BUSINESS_DIRECTION_REQUESTS", "WEBSITE_CLICKS",
                                           "BUSINESS_CONVERSATIONS"))
        acts_p = sum(prev.get(k, 0) for k in ("CALL_CLICKS", "BUSINESS_DIRECTION_REQUESTS", "WEBSITE_CLICKS",
                                              "BUSINESS_CONVERSATIONS"))
        rs = by_loc.get(n, [])
        rv, rv_p, life = review_block(rs, r_start, r_end), review_block(rs, rp_start, rp_end), review_block(
            rs, date(2000, 1, 1), today)
        unans = [r for r in rs if not r["reply"]]
        sp = speed.get(n) or {}
        pdays = sorted(posts.get(n, []))
        audit = G.audit(x, site) if x.get("data") else []
        rows.append({
            "name": n, "title": x["title"], "short": short(x["title"]),
            "views": now.get("views", 0), "views_prev": prev.get("views", 0),
            "calls": now.get("CALL_CLICKS", 0), "directions": now.get("BUSINESS_DIRECTION_REQUESTS", 0),
            "web": now.get("WEBSITE_CLICKS", 0), "actions": acts, "actions_prev": acts_p,
            "conv": acts / now["views"] if now.get("views") else None,
            "reviews": rv, "reviews_prev": rv_p, "life": life,
            "unanswered": len(unans), "low_unanswered": sum(1 for r in unans if (r["rating"] or 0) in LOW),
            "reply_days": sp.get("median_days"), "reply_rate": sp.get("rate"),
            "posts_30": sum(1 for d in pdays if d >= (today - timedelta(days=29)).isoformat()),
            "last_post": pdays[-1] if pdays else None,
            "audit_high": sum(1 for c in audit if c["level"] == "high"),
            "audit_medium": sum(1 for c in audit if c["level"] == "medium"),
        })
    tot_rv = review_block([r for rs in by_loc.values() for r in rs], r_start, r_end)
    low_all = sum(r["reviews"]["low"] for r in rows)
    for r in rows:
        r["low_part"] = r["reviews"]["low"] / low_all if low_all else None  # phần trong tổng đánh giá thấp
    _flags(rows, tot_rv, today, days)
    rows.sort(key=lambda r: (-r["score"], r["short"]))
    totals = {"views": sum(r["views"] for r in rows), "views_prev": sum(r["views_prev"] for r in rows),
              "actions": sum(r["actions"] for r in rows), "actions_prev": sum(r["actions_prev"] for r in rows),
              "reviews": tot_rv, "low_unanswered": sum(r["low_unanswered"] for r in rows),
              "unanswered": sum(r["unanswered"] for r in rows), "branches": len(rows)}
    return {"rows": rows, "totals": totals, "perf_period": (p_start, p_end), "review_period": (r_start, r_end)}


def _flags(rows: list[dict], tot: dict, today: date, days: int) -> None:
    """Lý do cần chú ý của từng chi nhánh (so với cả hệ thống) + điểm ưu tiên."""
    base = tot["low_share"] or 0
    for r in rows:
        f, score = [], 0.0
        rv = r["reviews"]
        if rv["total"] >= 5 and rv["low_share"] is not None and base and rv["low_share"] >= max(base * 1.5,
                                                                                               base + 0.05):
            f.append(("red", f"Sao thấp {rv['low_share'] * 100:.0f}% (cả hệ thống {base * 100:.0f}%)"))
            score += 3 + rv["low"] / 5
        elif rv["low"] >= 3:
            f.append(("amber", f"{rv['low']} đánh giá 1–3 sao trong kỳ"))
            score += 1 + rv["low"] / 10
        if r["low_unanswered"]:
            f.append(("red", f"{r['low_unanswered']} đánh giá thấp chưa trả lời"))
            score += 2 + r["low_unanswered"] / 3
        if r["views_prev"] >= 100 and r["views"] < r["views_prev"] * 0.8:
            f.append(("amber", f"Lượt xem giảm {(1 - r['views'] / r['views_prev']) * 100:.0f}%"))
            score += 1.5
        if r["actions_prev"] >= 30 and r["actions"] < r["actions_prev"] * 0.8:
            f.append(("amber", f"Hành động giảm {(1 - r['actions'] / r['actions_prev']) * 100:.0f}%"))
            score += 1.5
        if r["reply_days"] is not None and r["reply_days"] > 3:
            f.append(("amber", f"Trả lời đánh giá sau ~{r['reply_days']:.0f} ngày"))
            score += 1
        if not r["last_post"] or r["last_post"] < (today - timedelta(days=14)).isoformat():
            f.append(("grey", "Chưa có bài đăng 14 ngày qua" if r["last_post"] else "Chưa có bài đăng"))
            score += 0.5
        if r["audit_high"]:
            f.append(("red", f"Hồ sơ có {r['audit_high']} lỗi cần sửa"))
            score += 2
        r["flags"], r["score"] = f, round(score, 2)


def month_matrix(con, locs: list[dict], months: int = 12, today: date | None = None) -> dict:
    """Bản đồ nhiệt chi nhánh × tháng: số đánh giá, số / tỉ lệ 1–3 sao, điểm TB mỗi ô.
    {"months": ["2026-01", …], "rows": [{"name", "short", "cells": [{"total", "low", "share", "avg"}]}]}"""
    today = today or date.today()
    ms = []
    y, m = today.year, today.month
    for _ in range(months):
        ms.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    ms.reverse()
    rs = GR.rows(con, [x["name"] for x in locs])
    cells: dict[tuple, list[int]] = {}
    for r in rs:
        if r["rating"] and (r["created"] or "")[:7] in ms:
            cells.setdefault((r["location"], r["created"][:7]), []).append(r["rating"])
    out = []
    for x in locs:
        row = []
        for mm in ms:
            v = cells.get((x["name"], mm), [])
            low = sum(1 for s in v if s in LOW)
            row.append({"total": len(v), "low": low, "share": low / len(v) if v else None,
                        "avg": round(sum(v) / len(v), 2) if v else None})
        out.append({"name": x["name"], "short": short(x["title"]), "cells": row})
    return {"months": ms, "rows": out}


def recent_low(con, name: str, limit: int = 6) -> list[dict]:
    rs = [r for r in GR.rows(con, [name]) if (r["rating"] or 0) in LOW]
    return rs[:limit]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
