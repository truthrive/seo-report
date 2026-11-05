"""Dashboard Tổng quan ở màn Từ khóa & Thứ hạng: số liệu theo phạm vi (mọi bộ / Cam kết / Theo dõi / một bộ).

Quy tắc số liệu (thống nhất mọi khu):
- Từ khóa duy nhất: mỗi chữ từ khóa tính một lần trong phạm vi, ưu tiên dòng ở bộ Cam kết rồi bộ tạo trước. "Lượt theo
  dõi" = số dòng từ khóa theo bộ (một từ khóa ở 2 bộ = 2 lượt). Bỏ bộ Nháp và từ khóa tạm dừng.
- Top 3 / 5 / 10 cộng dồn (Top 5 gồm Top 3), % trên số từ khóa duy nhất của phạm vi.
- Biến động chỉ tính trên từ khóa có lần check trước ("có lịch sử"); từ khóa mới kiểm tra đếm riêng, không là tăng.
- Đối thủ chỉ tổng hợp khi mọi bộ trong phạm vi check cùng nơi (vùng Google, thiết bị, vị trí, ngôn ngữ). "Đối thủ vừa
  vượt": từ khóa mà ở lần check trước đối thủ chưa đứng trên website dự án, lần này đứng trên.
"""
from datetime import date, timedelta

from . import rank as R
from . import rank_overview as RO

KIND_SCOPES = {"all": "Tất cả bộ", "kpi": "Cam kết", "custom": "Theo dõi"}
MIN_COVERAGE = 0.5  # xu hướng: chỉ vẽ kỳ có ít nhất một nửa số từ khóa của phạm vi đã có số


def scope_sets(con, site: str, scope) -> list[dict]:
    sets_ = [x for x in R.sets(con, site) if not x["draft"]]
    if scope in ("kpi", "custom"):
        return [x for x in sets_ if x["kind"] == scope]
    if isinstance(scope, int):
        return [x for x in sets_ if x["id"] == scope]
    return sets_


def scope_keywords(con, site: str, end: date, scope) -> tuple[list[dict], int]:
    """(từ khóa duy nhất đang chạy của phạm vi, số lượt theo dõi)."""
    sets_ = scope_sets(con, site, scope)
    order = {x["id"]: i for i, x in enumerate(sets_)}  # bộ Cam kết đứng trước (R.sets đã xếp)
    rows = [k for k in R.keywords(con, site, end) if k["set_id"] in order and not k["paused"]]
    seen, out = set(), []
    for k in sorted(rows, key=lambda k: (order[k["set_id"]], k["id"])):
        key = k["keyword"].strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(k)
    return out, len(rows)


def kpis(kws: list[dict]) -> dict:
    checked = [k for k in kws if k["date"]]
    hist = [k for k in checked if k["prev_depth"]]
    tiers = {}
    for n in (3, 5, 10):
        def now_in(k, n=n):
            return k["rank"] is not None and k["rank"] <= n

        def was_in(k, n=n):
            return k["prev"] is not None and k["prev"] <= n
        tiers[n] = {"count": sum(1 for k in checked if now_in(k)),
                    "enter": sum(1 for k in hist if now_in(k) and not was_in(k)),
                    "leave": sum(1 for k in hist if was_in(k) and not now_in(k)),
                    "new": sum(1 for k in checked if not k["prev_depth"] and now_in(k))}
    up = down = 0
    for k in hist:
        a = k["prev"] if k["prev"] is not None else 999
        b = k["rank"] if k["rank"] is not None else 999
        up, down = up + (b < a), down + (b > a)
    return {"total": len(kws), "checked": len(checked), "unchecked": len(kws) - len(checked),
            "history": len(hist), "new": len(checked) - len(hist), "tiers": tiers, "up": up, "down": down,
            "same": len(hist) - up - down, "last": max((k["date"] for k in checked), default=None),
            "prev_date": max((k.get("prev_date") or "" for k in hist), default=None)}


def _periods(today: date, period: str, n: int) -> list[tuple[date, date, str]]:
    out = []
    if period == "week":
        start = today - timedelta(days=today.weekday())
        for i in range(n - 1, -1, -1):
            s = start - timedelta(weeks=i)
            out.append((s, s + timedelta(days=6), f"{s:%d/%m}"))
    else:  # tháng
        y, m = today.year, today.month
        for i in range(n - 1, -1, -1):
            yy, mm = y, m - i
            while mm <= 0:
                yy, mm = yy - 1, mm + 12
            s = date(yy, mm, 1)
            e = (date(yy + (mm == 12), mm % 12 + 1, 1) - timedelta(days=1))
            out.append((s, e, f"{mm:02d}/{yy}"))
    return out


def trend(con, kws: list[dict], period: str = "week", n: int = 12, today: date | None = None) -> list[dict]:
    """Xu hướng Top 3 / 5 / 10 theo tuần hoặc tháng, tính theo % trên số từ khóa đã có số đến kỳ đó (thêm từ khóa mới
    không làm đường đi lên giả). Kỳ không có lần check nào: giá trị None (không nối đường qua). Mỗi điểm: {label,
    from, to, has_data, checked, new, top3/5/10 (số), pct3/5/10}."""
    today = today or date.today()
    ids = [k["id"] for k in kws]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    checks = con.execute(f"SELECT keyword_id, check_date, rank FROM rank_checks WHERE keyword_id IN ({marks}) "
                         "ORDER BY check_date", ids).fetchall()
    first: dict[int, str] = {}
    for kid, d, _ in checks:
        first.setdefault(kid, d)
    out = []
    if period == "check":  # mỗi ngày có check là một điểm
        days = sorted({d for _, d, _ in checks})[-30:]
        spans = [(date.fromisoformat(d), date.fromisoformat(d), f"{d[8:10]}/{d[5:7]}") for d in days]
    else:
        spans = _periods(today, period, n)
    for s, e, label in spans:
        s_iso, e_iso = s.isoformat(), e.isoformat()
        state: dict[int, int | None] = {}
        has = False
        for kid, d, r in checks:
            if d > e_iso:
                break
            state[kid] = r
            has = has or d >= s_iso
        if not state:
            continue
        # Kỳ có quá ít từ khóa có số (dưới MIN_COVERAGE tổng từ khóa của phạm vi): % không đại diện (vd 2 từ khóa
        # đều Top 3 = 100%) → không vẽ, ghi chú riêng
        thin = len(state) < MIN_COVERAGE * len(ids)
        row = {"label": label, "from": s_iso, "to": e_iso, "has_data": has, "checked": len(state), "thin": thin,
               "new": sum(1 for kid, d in first.items() if s_iso <= d <= e_iso)}
        for t in (3, 5, 10):
            c = sum(1 for r in state.values() if r is not None and r <= t)
            row[f"top{t}"] = c if has else None
            row[f"pct{t}"] = round(c / len(state) * 100, 1) if has and not thin else None
        out.append(row)
    return out


def place_key(cfg, st: dict) -> tuple:
    w = R.settings_for(cfg.rank, st)
    return (w.se_domain, w.device, w.location_code, w.language_code)


def competitor_snapshot(con, cfg, end: date, scope, kws: list[dict]) -> dict:
    """Tóm tắt đối thủ cho phạm vi, hoặc {"invalid": lý do} khi không tổng hợp hợp lệ được."""
    sets_ = scope_sets(con, cfg.site_url, scope)
    if len({place_key(cfg, st) for st in sets_}) > 1:
        return {"invalid": "Các bộ trong phạm vi này check ở nơi khác nhau (vùng Google / thiết bị / vị trí), nên "
                           "không gộp số đối thủ. Chọn một bộ để xem."}
    comp = RO.competitors(con, cfg, end, kws=kws)
    rows = comp["rows"]
    rivals = [r for r in rows if not r["brand"]["own"]]
    if not rivals:
        return {"invalid": "Chưa có đối thủ nào. Thêm ở tab Đối thủ.", "no_rivals": True}
    if not comp["keywords"]:
        return {"invalid": "Chưa có kết quả Google của từ khóa nào trong phạm vi này."}
    own = next((r for r in rows if r["brand"]["own"]), None)
    leader = rows[0] if rows[0] is not own else (rivals[0] if rivals else None)
    fresh = RO.overtaken(comp) if comp["compared"] else None
    return {"own": own, "leader": leader, "brands": len(rows), "keywords": comp["keywords"], "total": comp["total"],
            "compared": comp["compared"], "overtaken": fresh}


def insights(kws: list[dict], comp: dict | None, limit: int = 5) -> list[dict]:
    """Tối đa `limit` điều cần chú ý, nặng trước. Mỗi mục: {tone, title, detail, keywords: [{keyword, set, set_id,
    prev, now}]}. Chỉ tính từ khóa có lần check trước; không có gì thì danh sách rỗng."""
    hist = [k for k in kws if k["date"] and k["prev_depth"]]

    def item(k):
        return {"keyword": k["keyword"], "set": k["set_name"], "set_id": k["set_id"],
                "prev": k["prev"] if k["prev"] is not None else f">{k['prev_depth']}",
                "now": k["rank"] if k["rank"] is not None else f">{k['last_depth']}"}
    out = []
    lost = [k for k in hist if k.get("top_target") and k["prev"] is not None and k["prev"] <= k["top_target"]
            and (k["rank"] is None or k["rank"] > k["top_target"])]
    if lost:
        out.append({"sev": 5, "tone": "bad", "title": f"{len(lost)} từ khóa mất Top mục tiêu",
                    "detail": "Trước đó đạt mục tiêu, lần này không còn đạt.", "keywords": [item(k) for k in lost]})
    for n, sev in ((3, 4), (10, 3)):
        left = [k for k in hist if k["prev"] is not None and k["prev"] <= n and (k["rank"] is None or k["rank"] > n)]
        if left:
            out.append({"sev": sev, "tone": "bad", "title": f"{len(left)} từ khóa rời Top {n}",
                        "detail": f"Lần check trước ở Top {n}, lần này ra ngoài.", "keywords": [item(k) for k in left]})
    if comp and comp.get("overtaken"):
        fresh = comp["overtaken"]
        names = sorted({x["brand"] for x in fresh})
        out.append({"sev": 3, "tone": "bad", "title": f"Đối thủ vừa vượt ở {len({x['kid'] for x in fresh})} từ khóa",
                    "detail": ", ".join(names[:3]) + (f" và {len(names) - 3} đối thủ khác" if len(names) > 3 else ""),
                    "keywords": [{"keyword": x["keyword"], "set": x["set"], "set_id": x["set_id"],
                                  "prev": x["brand"], "now": x["rank"]} for x in fresh], "rival": True})
    drops = [k for k in hist if k["prev"] is not None and k["rank"] is not None and k["rank"] - k["prev"] >= 10]
    if drops:
        out.append({"sev": 2, "tone": "warn", "title": f"{len(drops)} từ khóa tụt từ 10 bậc trở lên",
                    "detail": "Biến động lớn bất thường so với lần check trước.", "keywords": [item(k) for k in drops]})
    gains = [k for k in hist if k["rank"] is not None and k["rank"] <= 10 and (k["prev"] is None or k["prev"] > 10)]
    if gains:
        out.append({"sev": 1, "tone": "good", "title": f"{len(gains)} từ khóa vào Top 10",
                    "detail": "Lần check trước chưa ở trang đầu.", "keywords": [item(k) for k in gains]})
    return sorted(out, key=lambda x: -x["sev"])[:limit]


def set_list(con, cfg, end: date, scope) -> list[dict]:
    """Bộ trong phạm vi: tên, loại, số từ khóa đang chạy, Top 3 / 5 / 10, một cảnh báo quan trọng nhất. Bộ cần chú ý
    (đỏ) đứng trước, rồi bộ Cam kết."""
    out = []
    today = date.today()
    for st in scope_sets(con, cfg.site_url, scope):
        kws = [k for k in R.keywords(con, cfg.site_url, end, st["id"]) if not k["own_paused"]]
        ranked = [k["rank"] for k in kws if k["date"] and k["rank"] is not None]
        at = RO._attention(con, cfg.site_url, st, kws, today) if not st["paused"] else \
            {"text": "Tạm dừng", "tone": "grey", "filter": None}
        out.append({"id": st["id"], "name": st["name"], "kind": R.SET_KINDS.get(st["kind"], st["kind"]),
                    "paused": st["paused"], "total": len(kws), "top3": sum(r <= 3 for r in ranked),
                    "top5": sum(r <= 5 for r in ranked), "top10": sum(r <= 10 for r in ranked), "attention": at})
    rank_ = {"red": 0, "amber": 1, "grey": 2, "green": 3}
    return sorted(out, key=lambda x: (rank_.get((x["attention"] or {}).get("tone"), 3), x["kind"] != "Cam kết"))
