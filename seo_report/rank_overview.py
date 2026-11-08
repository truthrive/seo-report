"""Tổng quan dự án ở màn Từ khóa & Thứ hạng: gộp mọi bộ (mỗi từ khóa một lần), bảng các bộ, tổng quan đối thủ.

Số liệu chỉ lấy từ dữ liệu check đã có (không tốn thêm tiền). Bộ Nháp không tính vào số của dự án.
Đối thủ: vị trí trong các kết quả tự nhiên của lần check gần nhất của từng từ khóa, trong độ sâu đã check (lần check
cũ trước 03/11 chỉ lưu 10 kết quả đầu).
"""
import json
from datetime import date

from . import aio as AO
from . import rank as R
from .report import rank_change

# Tỷ lệ nhấp ước tính theo vị trí (đường cong CTR phổ biến cho kết quả tự nhiên): dùng tính độ hiển thị
CTR = {1: .28, 2: .15, 3: .10, 4: .07, 5: .05, 6: .04, 7: .03, 8: .025, 9: .02, 10: .018}


def ctr(rank: int | None) -> float:
    if rank is None:
        return 0.0
    return CTR.get(rank, 0.01 if rank <= 20 else 0.005)


def project_keywords(con, site: str, end: date) -> list[dict]:
    """Mỗi từ khóa một dòng (ưu tiên bộ Cam kết, rồi bộ tạo trước), bỏ bộ Nháp."""
    return [k for k in R.primary_keywords(con, site, end) if not k.get("draft")]


def active_keywords(con, site: str, end: date) -> list[dict]:
    """Từ khóa của dự án (mẫu số của các số Top N ở Tổng quan dự án). Tạm dừng chỉ là ngừng check: từ khóa tạm dừng
    đã có số vẫn tính theo lần check gần nhất; tạm dừng mà chưa check lần nào thì bỏ."""
    return [k for k in project_keywords(con, site, end) if not k["paused"] or k["date"]]


def project_history(con, site: str, end: date, limit: int = 30, period: str = "check") -> list[dict]:
    """Tăng trưởng của cả dự án (mỗi từ khóa đang chạy một lần), cùng cấu trúc set_history để dùng chung bento."""
    return R.history_of(con, {k["id"]: k["top_target"] for k in active_keywords(con, site, end)}, limit, period)


def _moves(kws: list[dict]) -> tuple[int, int]:
    ms = [rank_change(k["date"], k["rank"], k["last_depth"], k["prev"], k["prev_depth"])[2] for k in kws if k["date"]]
    return sum(m > 0 for m in ms), sum(m < 0 for m in ms)


def summary(con, site: str, end: date) -> dict:
    kws = project_keywords(con, site, end)
    checked = [k for k in kws if k["date"]]
    ranked = [k["rank"] for k in checked if k["rank"] is not None]
    up, down = _moves(kws)
    return {"total": len(kws), "checked": len(checked), "paused": sum(k["paused"] for k in kws),
            "top3": sum(r <= 3 for r in ranked), "top10": sum(r <= 10 for r in ranked),
            "deep": sum(r > 10 for r in ranked), "out": len(checked) - len(ranked),
            "unchecked": len(kws) - len(checked), "up": up, "down": down,
            "last": max((k["date"] for k in checked), default=None)}


def set_rows(con, site: str, end: date, s) -> list[dict]:
    """Một dòng mỗi bộ: số từ khóa, Top 3 / 10, lên / rớt, lần check gần nhất, lần theo lịch kế tiếp, chi phí ước tính."""
    out = []
    today = date.today()
    for st in R.sets(con, site):
        kws = R.keywords(con, site, end, st["id"])
        active = [k for k in kws if not k["own_paused"]]
        ranked = [k["rank"] for k in kws if k["date"] and k["rank"] is not None]
        up, down = _moves(kws)
        run = not st["draft"] and not st["paused"]
        out.append({"id": st["id"], "name": st["name"], "kind": R.SET_KINDS.get(st["kind"], st["kind"]),
                    "draft": st["draft"], "paused": st["paused"], "count": len(kws),
                    "checked": sum(1 for k in kws if k["date"]), "top3": sum(r <= 3 for r in ranked),
                    "top10": sum(r <= 10 for r in ranked), "up": up, "down": down,
                    "last": max((k["date"] for k in kws if k["date"]), default=None),
                    "next": R.next_scheduled_day(st["schedule"], today) if run else None,
                    "time": st["schedule"].get("time"),
                    "cost": R.estimate(con, R.settings_for(s, st), st["schedule"], [k["depth"] for k in active])
                    if run else 0.0})
    return out


def _latest_serps(con, kws: list[dict]) -> dict[int, tuple[list[dict], int, list[dict] | None]]:
    """{keyword_id: (kết quả tự nhiên, độ sâu đã thấy, kết quả tự nhiên lần trước hoặc None)} của lần check gần nhất
    có lưu trang kết quả."""
    out = {}
    for k in kws:
        if not k["date"]:
            continue
        rows = con.execute("SELECT s.organic, s.top10, c.depth FROM rank_serp s LEFT JOIN rank_checks c ON "
                           "c.keyword_id = s.keyword_id AND c.check_date = s.check_date WHERE s.keyword_id = ? AND "
                           "s.check_date <= ? AND (s.organic IS NOT NULL OR s.top10 IS NOT NULL) "
                           "ORDER BY s.check_date DESC LIMIT 2", (k["id"], k["date"])).fetchall()
        if not rows:
            continue

        def parse(row):
            return json.loads(row[0]) if row[0] else json.loads(row[1] or "[]")
        seen = (rows[0][2] or 10) if rows[0][0] else min(rows[0][2] or 10, 10)
        out[k["id"]] = (parse(rows[0]), seen, parse(rows[1]) if len(rows) > 1 else None)
    return out


def competitors(con, cfg, end: date, limit_ahead: int = 50, set_id: int | None = None,
                kws: list[dict] | None = None) -> dict:
    """Mình và từng đối thủ trên các từ khóa của dự án: số từ khóa có mặt, Top 3, Top 10, vị trí trung bình (khi có
    mặt), độ hiển thị (tổng CTR ước tính / mức tối đa nếu đứng đầu mọi từ khóa), các từ khóa đối thủ đứng trên mình."""
    site = cfg.site_url
    kws = kws if kws is not None else _scope(con, cfg, end, set_id)
    brands = AO.brands(con, cfg)
    serps = _latest_serps(con, kws)
    by_id = {k["id"]: k for k in kws}
    rows = {b["id"]: {"brand": b, "present": 0, "top3": 0, "top5": 0, "top10": 0, "ranks": [], "vis": 0.0,
                      "ahead": [], "new_ahead": [], "behind": [],
                      # so với lần check trước, chỉ trên các từ khóa có cả hai lần (cùng tập từ khóa)
                      "cmp": {"now": {3: 0, 5: 0, 10: 0, "vis": 0.0}, "prev": {3: 0, 5: 0, 10: 0, "vis": 0.0}}}
            for b in brands}
    n_cmp = 0
    own = next((b for b in brands if b["own"]), None)
    for kid, (organic, seen, before) in serps.items():
        pos = AO.brand_ranks(organic, brands)
        mine = (pos.get(own["id"]) or {}).get("rank") if own else None
        old = AO.brand_ranks(before, brands) if before is not None else None
        old_mine = (old.get(own["id"]) or {}).get("rank") if old and own else None
        if old is not None:
            n_cmp += 1
            for b in brands:
                for side, src in (("now", pos), ("prev", old)):
                    rk = (src.get(b["id"]) or {}).get("rank")
                    c_ = rows[b["id"]]["cmp"][side]
                    if rk is not None:
                        for t in (3, 5, 10):
                            c_[t] += rk <= t
                        c_["vis"] += ctr(rk)
        for b in brands:
            p = pos[b["id"]]
            r = rows[b["id"]]
            if not p:
                if not b["own"] and mine is not None:
                    r["behind"].append({"keyword": by_id[kid]["keyword"], "rank": None, "mine": mine, "seen": seen,
                                        "url": "", "set": by_id[kid]["set_name"], "kid": kid,
                                        "set_id": by_id[kid]["set_id"]})
                continue
            rank = p["rank"]
            r["present"] += 1
            r["top3"] += rank <= 3
            r["top5"] += rank <= 5
            r["top10"] += rank <= 10
            r["ranks"].append(rank)
            r["vis"] += ctr(rank)
            if not b["own"] and mine is not None and rank > mine:  # dự án đứng trên đối thủ này
                r["behind"].append({"keyword": by_id[kid]["keyword"], "rank": rank, "mine": mine, "seen": seen,
                                    "url": p["url"], "set": by_id[kid]["set_name"], "kid": kid,
                                    "set_id": by_id[kid]["set_id"]})
            if not b["own"] and (mine is None or rank < mine):
                item = {"keyword": by_id[kid]["keyword"], "rank": rank, "mine": mine, "seen": seen,
                        "url": p["url"], "set": by_id[kid]["set_name"], "kid": kid, "set_id": by_id[kid]["set_id"]}
                r["ahead"].append(item)
                was = (old or {}).get(b["id"])
                if old is not None and (not was or (old_mine is not None and was["rank"] > old_mine)):
                    r["new_ahead"].append(item)  # lần trước chưa đứng trên mình
    ai_n = 0  # từ khóa có AI Overview đọc được nguồn (lần gần nhất)
    for k in kws:
        row = con.execute("SELECT aio_refs FROM rank_serp WHERE keyword_id = ? AND aio = 1 ORDER BY check_date DESC "
                          "LIMIT 1", (k["id"],)).fetchone()
        refs = json.loads(row[0] or "[]") if row else []
        if refs:
            ai_n += 1
            for b in brands:
                rows[b["id"]]["ai_cited"] = rows[b["id"]].get("ai_cited", 0) + AO.cited(refs, b)
    n = len(serps)
    out = []
    for b in brands:
        r = rows[b["id"]]
        r.setdefault("ai_cited", 0)
        r["avg"] = round(sum(r["ranks"]) / len(r["ranks"]), 1) if r["ranks"] else None
        r["visibility"] = r["vis"] / (n * CTR[1]) if n else 0.0
        r["ahead_count"] = len(r["ahead"])
        r["behind_count"] = len(r["behind"])
        r["behind"] = sorted(r["behind"], key=lambda x: (x["mine"], x["keyword"]))[:limit_ahead]
        r["ahead"] = sorted(r["ahead"], key=lambda x: (x["rank"], x["keyword"]))[:limit_ahead]
        c_ = r.pop("cmp")
        r["delta"] = {t: c_["now"][t] - c_["prev"][t] for t in (3, 5, 10)} if n_cmp else None
        r["_vis_now"], r["_vis_prev"] = c_["now"]["vis"], c_["prev"]["vis"]
        out.append(r)
    # Bảng xếp hạng theo thị phần hiển thị (cả website dự án); "move": số bậc lên (+) / xuống (−) so với lần check
    # trước, xếp trên cùng tập từ khóa có cả hai lần check
    out.sort(key=lambda r: (-r["visibility"], not r["brand"]["own"], r["brand"]["name"]))
    for i, r in enumerate(out, 1):
        r["place"] = i
    if n_cmp:
        def order(key):
            ranked = sorted(out, key=lambda r: (-r[key], not r["brand"]["own"], r["brand"]["name"]))
            return {r["brand"]["id"]: i for i, r in enumerate(ranked, 1)}
        for r in out:  # độ hiển thị lần trước = phần từ khóa có lần trước thay bằng số lần trước
            r["_vis_before"] = r["vis"] - r["_vis_now"] + r["_vis_prev"]
        prev_o = order("_vis_before")
        for r in out:
            r["move"] = prev_o[r["brand"]["id"]] - r["place"]
    for r in out:
        r.setdefault("move", None)
        r.pop("_vis_now"), r.pop("_vis_prev"), r.pop("_vis_before", None)
    vis_sum = sum(r["vis"] for r in out)
    for r in out:
        r["share"] = r["vis"] / vis_sum if vis_sum else 0.0
    return {"keywords": n, "total": len(kws), "ai_n": ai_n, "rows": out, "compared": n_cmp,
            "own": own, "full_depth": sum(1 for k in serps.values() if k[1] > 10)}


def overtaken(comp: dict) -> list[dict]:
    """Từ khóa đối thủ vừa vượt mình (lần check trước chưa đứng trên): [{keyword, brand, rank, mine, ...}]."""
    out = []
    for r in comp["rows"]:
        for x in r.get("new_ahead", []):
            out.append({**x, "brand": r["brand"]["name"]})
    return sorted(out, key=lambda x: (x["rank"], x["keyword"]))


# ---- Thẻ từng bộ ở tab Tổng quan ----

def _attention(con, site: str, st: dict, kws: list[dict], today: date) -> dict | None:
    """Việc cần chú ý nhất của một bộ (một dòng): KPI đang chậm → rớt khỏi top 10 → sai URL mục tiêu → chưa check →
    ổn định. {"text", "tone" (red/amber/grey/green), "filter" (bộ lọc bảng khi bấm) }."""
    if st["draft"]:
        return {"text": "Nháp: chưa check, chưa tốn tiền. Bấm để chốt bộ", "tone": "amber", "filter": "lock"}
    if st["kind"] == "kpi":
        try:
            from . import kpi as KP
            kn = KP.rank_kpi_now(con, site, today, st["id"])
        except Exception:  # noqa: BLE001  (KPI lỗi không làm hỏng tổng quan)
            kn = None
        if kn and kn["rows"]:
            due = [r for r in kn["rows"] if r["month"]["need"] is not None]
            late = [r for r in due if r["month"]["gap"]]
            if late:
                r = late[0]
                return {"text": f"KPI tháng {kn['month']}: Top {r['top']} cần {r['month']['need']}, đang {r['count']}",
                        "tone": "red", "filter": "miss"}
            if due:
                return {"text": f"KPI tháng {kn['month']}: đạt", "tone": "green", "filter": None}
    dropped = sum(1 for k in kws if k["prev"] is not None and k["prev"] <= 10 and (k["rank"] is None or k["rank"] > 10))
    if dropped:
        return {"text": f"{dropped} từ khóa rớt khỏi top 10", "tone": "red", "filter": "down"}
    wrong = sum(1 for k in kws if k["target_url"] and k["ranking_url"] and k["ranking_url"] != k["target_url"])
    if wrong:
        return {"text": f"{wrong} từ khóa xếp hạng sai URL mục tiêu", "tone": "amber", "filter": "wrong"}
    unchecked = sum(1 for k in kws if not k["date"] and not k["paused"])
    if unchecked:
        return {"text": f"{unchecked} từ khóa chưa check, lần tới sẽ check", "tone": "grey", "filter": "unchecked"}
    return {"text": "Ổn định", "tone": "green", "filter": None}


def set_cards(con, cfg, end: date, today: date | None = None) -> list[dict]:
    """Một thẻ mỗi bộ: Top 10 / tổng (từ khóa đang chạy) · %, thay đổi so với lần check trước, Top 3, ngoài top N,
    chưa check, một dòng cần chú ý, lần check gần nhất / tới, chi phí. Bộ Cam kết trước, Nháp và tạm dừng cuối."""
    today = today or date.today()
    site = cfg.site_url
    rows = {r["id"]: r for r in set_rows(con, site, end, cfg.rank)}
    out = []
    for st in R.sets(con, site):
        kws = [k for k in R.keywords(con, site, end, st["id"]) if not k["own_paused"]]
        hist = R.history_of(con, {k["id"]: k["top_target"] for k in kws}, limit=2)
        last, prev = (hist[-1] if hist else None), (hist[-2] if len(hist) > 1 else None)

        def top10(h):
            return (h["top3"] + h["top5"] + h["top10"]) if h else None
        _, out_label = R.band_labels(last)
        r = rows[st["id"]]
        out.append({**r, "active": len(kws), "aio": aio_for(con, cfg, kws), "top10_now": top10(last), "top3_now": last["top3"] if last else None,
                    "delta": (top10(last) - top10(prev)) if last and prev else None,
                    "prev_date": prev["date"] if prev else None,
                    "out_n": last["out"] if last else 0, "out_label": out_label,
                    "unchecked_n": sum(1 for k in kws if not k["date"]),
                    "attention": _attention(con, site, st, kws, today)})
    return sorted(out, key=lambda c: (c["draft"] or c["paused"], c["kind"] != R.SET_KINDS["kpi"]))


# ---- Tab Đối thủ ----

def keyword_matrix(con, cfg, end: date, set_id: int | None = None) -> dict:
    """Mỗi từ khóa một dòng: vị trí của mình và từng đối thủ ở lần check gần nhất (trong độ sâu đã check)."""
    kws = _scope(con, cfg, end, set_id)
    brands = AO.brands(con, cfg)
    serps = _latest_serps(con, kws)
    own = next((b for b in brands if b["own"]), None)
    from . import intent as IN
    from . import volume as V
    vols = V.latest(con)
    intents = IN.for_keywords(con, cfg, kws)
    rows = []
    for k in kws:
        if k["id"] not in serps:
            continue
        a = con.execute("SELECT aio, aio_refs FROM rank_serp WHERE keyword_id = ? AND aio IS NOT NULL "
                        "ORDER BY check_date DESC LIMIT 1", (k["id"],)).fetchone()
        refs = json.loads(a[1] or "[]") if a and a[0] else []
        organic, seen, _ = serps[k["id"]]
        pos = AO.brand_ranks(organic, brands)
        ranks = {b["id"]: (pos[b["id"]] or {}).get("rank") for b in brands}
        mine = ranks.get(own["id"]) if own else None
        ahead = any(r is not None and (mine is None or r < mine) for bid, r in ranks.items() if not own or bid != own["id"])
        rows.append({"id": k["id"], "keyword": k["keyword"], "set": k["set_name"], "set_id": k["set_id"],
                     "seen": seen, "ranks": ranks, "mine": mine, "ahead": ahead,
                     "volume": (vols.get(k["id"]) or {}).get("volume"),
                     "aio": bool(a and a[0]), "aio_own": bool(own and refs and AO.cited(refs, own)),
                     "aio_brands": [b["name"] for b in brands if refs and AO.cited(refs, b)],
                     "intent": intents.get(k["id"], ("", "", [], None))})
    return {"brands": brands, "rows": sorted(rows, key=lambda r: (not r["ahead"], r["mine"] or 999, r["keyword"]))}


def visibility_trend(con, cfg, end: date, set_id: int | None = None, limit: int = 12) -> list[dict]:
    """Độ hiển thị (0–1) của mình và từng đối thủ theo ngày check: mỗi ngày chỉ tính các từ khóa có trang kết quả
    ngày đó. [{date, n, vis: {brand_id: v}}]."""
    kws = _scope(con, cfg, end, set_id)
    ids = [k["id"] for k in kws]
    if not ids:
        return []
    brands = AO.brands(con, cfg)
    marks = ",".join("?" * len(ids))
    by_day: dict[str, list[list[dict]]] = {}
    for d, organic, top10 in con.execute(
            f"SELECT check_date, organic, top10 FROM rank_serp WHERE keyword_id IN ({marks}) AND "
            f"(organic IS NOT NULL OR top10 IS NOT NULL) ORDER BY check_date", ids):
        by_day.setdefault(d, []).append(json.loads(organic) if organic else json.loads(top10 or "[]"))
    out = []
    for d, lists in sorted(by_day.items())[-limit:]:
        vis = {b["id"]: 0.0 for b in brands}
        for organic in lists:
            for bid, p in AO.brand_ranks(organic, brands).items():
                vis[bid] += ctr(p["rank"]) if p else 0.0
        n = len(lists)
        out.append({"date": d, "n": n, "vis": {bid: v / (n * CTR[1]) for bid, v in vis.items()}})
    return out


# Nền tảng (mạng xã hội, sàn TMĐT, bách khoa, video…) hay có mặt trong top 10 nhưng không phải đối thủ cạnh tranh
PLATFORMS = ("facebook.com", "youtube.com", "tiktok.com", "shopee.vn", "lazada.vn", "tiki.vn", "wikipedia.org",
             "instagram.com", "google.com", "reddit.com", "pinterest.com", "sendo.vn", "zalo.me", "twitter.com",
             "x.com", "linkedin.com", "threads.net", "quora.com", "amazon.com")


def rank_suggestions(con, cfg, end: date, limit: int = 8) -> list[tuple[str, int]]:
    """Website hay có mặt trong top 10 của bộ từ khóa mà chưa có trong danh sách: (tên miền, số từ khóa)."""
    kws = active_keywords(con, cfg.site_url, end)
    have = {d for b in AO.brands(con, cfg) for d in b["domains"]}
    skip = PLATFORMS
    count: dict[str, int] = {}
    for organic, _, _ in _latest_serps(con, kws).values():
        for d in {x["domain"] for x in organic if x["rank"] <= 10}:
            if d and not any(R._host_match(d, h) for h in have) and not any(R._host_match(d, s) for s in skip):
                count[d] = count.get(d, 0) + 1
    return sorted(count.items(), key=lambda x: (-x[1], x[0]))[:limit]


def _scope(con, cfg, end: date, set_id: int | None) -> list[dict]:
    if set_id is None:
        return active_keywords(con, cfg.site_url, end)
    return [k for k in R.keywords(con, cfg.site_url, end, set_id) if not k["paused"] or k["date"]]


# ---- AI Overview theo bộ ----

def aio_for(con, cfg, kws: list[dict]) -> dict:
    """Số AI Overview của một nhóm từ khóa (lần check gần nhất có đọc AIO của từng từ khóa) và lần trước đó:
    có AIO, website được trích (trên số AIO đọc được nguồn), được nhắc tên (trên số AIO có chữ), đối thủ được trích
    nhiều nhất."""
    brands = AO.brands(con, cfg)
    own = next(b for b in brands if b["own"])
    rivals = [b for b in brands if not b["own"]]
    cur, prev = [], []
    for k in kws:
        rows = con.execute("SELECT aio, aio_refs, aio_text FROM rank_serp WHERE keyword_id = ? AND aio IS NOT NULL "
                           "ORDER BY check_date DESC LIMIT 2", (k["id"],)).fetchall()
        if rows:
            cur.append(rows[0])
        if len(rows) > 1:
            prev.append(rows[1])

    def measure(rows):
        with_aio = [(json.loads(refs or "[]"), text) for aio, refs, text in rows if aio]
        reffed = [r for r in with_aio if r[0]]
        texted = [r for r in with_aio if r[1]]
        return {"checked": len(rows), "aio": len(with_aio), "reffed": len(reffed), "texted": len(texted),
                "cited": sum(AO.cited(refs, own) for refs, _ in reffed),
                "mentioned": sum(AO.mentioned(AO.norm(text), own) for _, text in texted),
                "rivals": {b["id"]: sum(AO.cited(refs, b) for refs, _ in reffed) for b in rivals}}
    now = measure(cur)
    best = max(rivals, key=lambda b: now["rivals"][b["id"]], default=None)
    return {**now, "total": len(kws), "prev": measure(prev) if prev else None,
            "top_rival": (best, now["rivals"][best["id"]]) if best and now["rivals"][best["id"]] else None}


def _vn_full(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def competitor_workbook(con, cfg, end: date) -> bytes:
    """File Excel để nghiên cứu, luôn gồm MỌI từ khóa của MỌI bộ (bỏ bộ Nháp; từ khóa tạm dừng vẫn có, đánh dấu):
    vị trí của mình và từng đối thủ theo từ khóa (kèm AI Overview), toàn bộ kết quả Google của lần check gần nhất
    (mọi website trong độ sâu đã check), tổng quan đối thủ, ghi chú cách đọc. Cùng từ khóa ở hai bộ: hai dòng."""
    import io
    import json

    from openpyxl import Workbook

    from .export import INT, PCT, _sheet
    CHG = "+0;-0;0"  # ± so với lần check trước: số dương có dấu +
    site = cfg.site_url
    comp = competitors(con, cfg, end)
    order = {x["id"]: i for i, x in enumerate(R.sets(con, site))}
    all_kws = sorted((k for k in R.keywords(con, site, end) if not k.get("draft")),
                     key=lambda k: (order.get(k["set_id"], 99), k["keyword"]))
    kws = {k["id"]: k for k in all_kws}
    serps = _latest_serps(con, all_kws)
    from . import intent as IN
    intents = IN.for_keywords(con, cfg, all_kws)
    aio_rows = {kid: con.execute("SELECT check_date, aio, aio_refs FROM rank_serp WHERE keyword_id = ? AND aio "
                                 "IS NOT NULL ORDER BY check_date DESC LIMIT 1", (kid,)).fetchone() for kid in kws}
    brands = AO.brands(con, cfg)
    own = next(b for b in brands if b["own"])
    wb = Workbook()
    wb.remove(wb.active)
    rows = []
    for k in all_kws:
        sp = serps.get(k["id"])
        pos = AO.brand_ranks(sp[0], brands) if sp else {}
        mine = k["rank"] if k["date"] else None  # vị trí của mình theo lần check (có cả khi chưa lưu trang kết quả)
        ranks = [mine if b["own"] else ((pos.get(b["id"]) or {}).get("rank") if sp else None) for b in brands]
        ahead = bool(sp) and any(r is not None and (mine is None or r < mine)
                                 for b, r in zip(brands, ranks) if not b["own"])
        a = aio_rows.get(k["id"])
        refs = json.loads(a[2] or "[]") if a else []
        rows.append([k["keyword"], *IN.excel_cells(intents.get(k["id"])), k["set_name"],
                     "Có" if k["paused"] else "", _vn_full(k["date"]),
                     k["last_depth"], "Có" if sp else "Chưa"] + ranks
                    + ["Có" if ahead else "", "" if not a else ("Có" if a[1] else "Không"),
                       ", ".join(b["name"] for b in brands if refs and AO.cited(refs, b)),
                       k["ranking_url"] or "", k["target_url"] or ""])
    _sheet(wb, "Vị trí theo từ khóa",
           [("Từ khóa", 34, None), ("Ý định chính", 30, None), ("Ý định khác", 40, None), ("Bộ", 16, None),
            ("Tạm dừng", 9, None),
            ("Ngày check", 12, None),
            ("Độ sâu đã check", 10, INT), ("Có kết quả Google", 10, None)]
           + [(b["name"], 14, INT) for b in brands]
           + [(f"Đối thủ xếp trên {own['name']}", 12, None), ("Có AI Overview", 10, None),
              ("Được AI trích", 40, None),
              ("URL đang xếp hạng", 60, None), ("URL mục tiêu", 60, None)],
           rows)
    full = []
    for kid, (organic, seen, _) in serps.items():
        k = kws[kid]
        for x in sorted(organic, key=lambda x: x["rank"]):
            who = next((b["name"] for b in brands if AO.cited([x], b)), "")
            full.append([k["keyword"], k["set_name"], _vn_full(k.get("date")), x["rank"], x["domain"], x["url"], who])
    _sheet(wb, "Kết quả Google", [("Từ khóa", 34, None), ("Bộ", 16, None), ("Ngày check", 12, None),
                                  ("Hạng", 7, INT), ("Tên miền", 26, None), ("URL", 70, None),
                                  ("Thương hiệu theo dõi", 18, None)], full)
    _sheet(wb, "Tổng quan đối thủ",
           [("Hạng", 6, INT), ("± Hạng", 7, CHG), ("Thương hiệu", 24, None), ("Thị phần hiển thị", 11, PCT),
            ("Độ hiển thị", 11, PCT), ("Có mặt", 9, INT), ("Top 3", 7, INT), ("± Top 3", 8, CHG),
            ("Top 5", 7, INT), ("± Top 5", 8, CHG), ("Top 10", 7, INT), ("± Top 10", 8, CHG),
            ("Được AI trích", 11, INT)],
           [[r["place"], r.get("move"), r["brand"]["name"], r["share"], r["visibility"], r["present"],
             r["top3"], (r.get("delta") or {}).get(3), r["top5"], (r.get("delta") or {}).get(5),
             r["top10"], (r.get("delta") or {}).get(10), r.get("ai_cited", 0)] for r in comp["rows"]])
    ws = wb.create_sheet("Ghi chú")
    for line in ("Vị trí = hạng trên Google ở lần check gần nhất của từng từ khóa (DataForSEO, cùng nơi check "
                 "của bộ). Ô trống = không có trong độ sâu đã check.",
                 "Lần check trước 03/11 chỉ lưu 10 kết quả đầu (độ sâu đã check ghi 10).",
                 "Phạm vi: mọi từ khóa của mọi bộ (trừ bộ Nháp), kể cả từ khóa tạm dừng. Cột vị trí của website dự án "
                 "lấy theo lần check gần nhất; vị trí đối thủ chỉ có khi lần check đó lưu trang kết quả (cột Có kết "
                 "quả Google). Tổng quan đối thủ tính trên từ khóa đang chạy, mỗi từ khóa một lần."):
        ws.append([line])
    ws.column_dimensions["A"].width = 120
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

