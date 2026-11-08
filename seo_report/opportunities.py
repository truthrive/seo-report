"""Cơ hội SEO từ dữ liệu Search Console đã lưu (không gọi API, không tốn tiền):

- Sắp lên top: từ khóa đang ở vị trí 4–15 với nhiều lượt hiển thị — đẩy lên top 3 là có thêm nhiều click nhất.
- Trang tụt traffic: click 28 ngày gần nhất giảm mạnh so với 28 ngày trước, kèm lý do có thể (rớt hạng / ít người tìm
  / CTR giảm) và so cùng kỳ năm trước để nhận ra mùa vụ.
- Tranh nhau từ khóa: hai URL trở lên cùng nhận lượt hiển thị đáng kể cho một từ khóa (quy tắc như màn URL).
- Trang mới: URL mới xuất hiện trên Google (hoặc mới vào sitemap) trong 90 ngày, số 7 / 30 / 90 ngày đầu.

Mọi kỳ tính tới ngày GSC đã chốt (keywords.latest_date)."""
import sqlite3
import time
from datetime import date, timedelta

from . import keywords as K
from .config import KeywordSettings

WINDOW = 28
CTR_TOP3 = 0.11  # CTR thận trọng của vị trí 3 (đường CTR phổ biến 10–12%): ước số click thêm khi lên top 3
STRIKE_LO, STRIKE_HI = 4.0, 15.0
DECAY_MIN_PREV = 20  # dưới 20 click / 28 ngày: dao động ngẫu nhiên, không báo
DECAY_RATIO = 0.3  # giảm từ 30% …
DECAY_MIN_LOST = 10  # … và mất ít nhất 10 click
NEW_DAYS = 90
NEW_SIGNAL = 20  # trang mới có từ 20 lượt hiển thị: đã có tín hiệu, tìm từ khóa chính
SITEMAP_SEED = "2000-01-01"  # URL có sẵn trong sitemap lúc tool đọc lần đầu: không biết ngày đăng

_cache: dict = {}  # (file dữ liệu, loại, ngày chốt) -> (lúc tính, kết quả): chuông thông báo không tính lại liên tục
CACHE_SECONDS = 3600  # GSC chỉ có ngày mới mỗi ngày một lần


def window(end: date, days: int = WINDOW, back: int = 0) -> tuple[date, date]:
    """Kỳ `days` ngày kết thúc ở `end`, lùi `back` kỳ."""
    e = end - timedelta(days=days * back)
    return e - timedelta(days=days - 1), e


def _db_key(con) -> str:
    try:
        return con.execute("PRAGMA database_list").fetchone()[2] or str(id(con))
    except sqlite3.Error:
        return str(id(con))


def cached(con, kind: str, end: date, fn):
    k = (_db_key(con), kind, end)
    hit = _cache.get(k)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    val = fn()
    _cache[k] = (time.time(), val)
    return val


_warming: set = set()


def peek_summary(cfg) -> dict | None:
    """Kết quả summary đã tính (kể cả hơi cũ) để chuông thông báo dùng mà không bắt trang chờ tính (vài giây với site
    lớn). Chưa có hoặc đã cũ: tính lại ở luồng nền, lần mở sau mới có."""
    import threading
    from contextlib import closing

    from . import db
    path = str(cfg.db_path)
    hit = next(((t, v) for (k, kind, _), (t, v) in _cache.items()
                if kind == "summary" and _same(k, path)), None)
    if (hit is None or time.time() - hit[0] >= CACHE_SECONDS) and path not in _warming:
        _warming.add(path)

        def work():
            try:
                with closing(db.connect(cfg.db_path)) as con:
                    summary(con, cfg.site_url, K.latest_date(con, cfg.site_url), cfg.keywords)
            except Exception:  # noqa: BLE001 — thông báo phụ, lỗi thì thôi
                pass
            finally:
                _warming.discard(path)
        threading.Thread(target=work, daemon=True).start()
    return hit[1] if hit else None


def _same(a: str, b: str) -> bool:
    import os
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def forget() -> None:
    _cache.clear()


def _tracked(con, site: str) -> set[str]:
    """Từ khóa đang theo dõi thứ hạng (mọi bộ, trừ đã gỡ), dạng bỏ dấu."""
    try:
        return {K.fold(k) for k, in con.execute(
            "SELECT keyword FROM rank_keywords WHERE site = ? AND removed_at IS NULL", (site,))}
    except sqlite3.Error:
        return set()


def _by_query(rows) -> dict[int, list[tuple]]:
    out: dict[int, list[tuple]] = {}
    for qid, uid, c, i, p in rows:
        out.setdefault(qid, []).append((uid, c or 0, i or 0, p or 0.0))
    return out


# ---- Sắp lên top ----

def potential(impressions: int, clicks: int) -> int:
    """Click có thể có thêm mỗi 28 ngày nếu lên vị trí 3 (không âm)."""
    return max(0, round(impressions * CTR_TOP3 - clicks))


def striking(con: sqlite3.Connection, site: str, end: date, settings: KeywordSettings,
             lo: float = STRIKE_LO, hi: float = STRIKE_HI) -> list[dict]:
    """Từ khóa (không phải thương hiệu) có URL chính đang ở vị trí lo–hi, đủ lượt hiển thị, nhiều click tiềm năng
    trước. URL chính = URL nhận nhiều lượt hiển thị nhất cho từ khóa đó; số liệu lấy của URL đó."""
    s, e = window(end)
    ps, pe = window(end, back=1)
    cur = _by_query(K._query_stats(con, site, s, e))
    prev = _by_query(K._query_stats(con, site, ps, pe))
    picked = []
    for qid, comps in cur.items():
        uid, c, i, p = max(comps, key=lambda r: (r[2], r[1]))
        if i < settings.min_impressions or not lo <= p <= hi:
            continue
        before = {r[0]: r for r in prev.get(qid, [])}.get(uid)
        picked.append((qid, uid, c, i, p, before[3] if before and before[2] else None, len(comps)))
    texts = K._texts(con, "queries", "text", {r[0] for r in picked})
    urls = K._texts(con, "urls", "url", {r[1] for r in picked})
    tracked = _tracked(con, site)
    out = []
    for qid, uid, c, i, p, pp, n_urls in picked:
        q = texts[qid]
        if K.is_brand(q, settings.brand_terms):
            continue
        out.append({"query": q, "url": urls[uid], "url_id": uid, "clicks": c, "impressions": i,
                    "position": round(p, 1), "prev_position": round(pp, 1) if pp else None,
                    "potential": potential(i, c), "tracked": K.fold(q) in tracked, "urls": n_urls})
    out.sort(key=lambda r: (-r["potential"], -r["impressions"]))
    return out


# ---- Trang tụt traffic ----

def _url_stats(con, site: str, s: date, e: date) -> dict[int, tuple]:
    q = """SELECT pu.url_id, SUM(d.clicks), SUM(d.impressions),
                  SUM(d.position * d.impressions) / NULLIF(SUM(d.impressions), 0)
           FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id
           JOIN urls u ON u.id = pu.url_id AND u.site = ?
           WHERE d.date BETWEEN ? AND ? GROUP BY pu.url_id"""
    return {r[0]: (r[1] or 0, r[2] or 0, r[3]) for r in con.execute(q, (site, s.isoformat(), e.isoformat()))}


def has_data(con, site: str, day: date) -> bool:
    row = con.execute("SELECT MIN(date) FROM gsc_fetch_log WHERE site = ?", (site,)).fetchone()
    return bool(row and row[0] and row[0] <= day.isoformat())


def cause(now: tuple, prev: tuple) -> tuple[str, str]:
    """Lý do có thể của mức giảm click: (mã, chữ). now / prev = (click, hiển thị, vị trí)."""
    c, i, p = now
    pc, pi, pp = prev
    if p and pp and p - pp >= 2:
        return "rank", f"Rớt hạng: vị trí {pp:.1f} → {p:.1f}".replace(".", ",")
    if pi and i < pi * 0.75:
        return "demand", "Ít lượt hiển thị hơn (ít người tìm hơn hoặc mất bớt từ khóa)"
    if pi and pc and i and c / i < pc / pi * 0.75:
        return "ctr", "Vẫn hiển thị nhưng ít người bấm (CTR giảm: tiêu đề, AI Overview, đối thủ…)"
    return "mixed", "Giảm nhẹ ở nhiều mặt"


def decay(con: sqlite3.Connection, site: str, end: date) -> list[dict]:
    """URL mất nhiều click nhất 28 ngày gần nhất so với 28 ngày trước đó."""
    cur_w, prev_w = window(end), window(end, back=1)
    cur, prev = _url_stats(con, site, *cur_w), _url_stats(con, site, *prev_w)
    yoy_ok = has_data(con, site, prev_w[0] - timedelta(days=364))
    ya_cur = _url_stats(con, site, *(d - timedelta(days=364) for d in cur_w)) if yoy_ok else {}
    ya_prev = _url_stats(con, site, *(d - timedelta(days=364) for d in prev_w)) if yoy_ok else {}
    picked = []
    for uid, pv in prev.items():
        nw = cur.get(uid, (0, 0, None))
        lost = pv[0] - nw[0]
        if pv[0] < DECAY_MIN_PREV or lost < max(DECAY_MIN_LOST, pv[0] * DECAY_RATIO):
            continue
        seasonal = None
        if yoy_ok:
            a, b = ya_cur.get(uid, (0, 0, None))[0], ya_prev.get(uid, (0, 0, None))[0]
            seasonal = bool(b >= DECAY_MIN_PREV / 2 and a <= b * (1 - DECAY_RATIO * 0.66))  # năm ngoái cũng giảm ≥20%
        picked.append((uid, nw, pv, lost, seasonal))
    urls = K._texts(con, "urls", "url", {r[0] for r in picked})
    out = []
    for uid, nw, pv, lost, seasonal in picked:
        code, text = cause(nw, pv)
        out.append({"url": urls[uid], "url_id": uid, "clicks": nw[0], "prev_clicks": pv[0], "lost": lost,
                    "change": -lost / pv[0], "impressions": nw[1], "prev_impressions": pv[1],
                    "position": round(nw[2], 1) if nw[2] else None,
                    "prev_position": round(pv[2], 1) if pv[2] else None,
                    "cause": code, "cause_text": text, "seasonal": seasonal})
    out.sort(key=lambda r: -r["lost"])
    return out


def lost_queries(con: sqlite3.Connection, url_id: int, end: date, limit: int = 8) -> list[dict]:
    """Từ khóa của một URL mất nhiều click nhất (28 ngày gần nhất so với 28 ngày trước)."""
    cur = K.query_period(con, url_id, *window(end))
    prev = K.query_period(con, url_id, *window(end, back=1))
    rows = []
    for qid in set(cur) | set(prev):
        c, i, p = cur.get(qid, (0, 0, None))
        pc, pi, pp = prev.get(qid, (0, 0, None))
        if (pc or 0) - (c or 0) > 0:
            rows.append((qid, c or 0, pc or 0, i or 0, pi or 0, p, pp))
    rows.sort(key=lambda r: -(r[2] - r[1]))
    rows = rows[:limit]
    texts = K._texts(con, "queries", "text", {r[0] for r in rows})
    return [{"query": texts[q], "clicks": c, "prev_clicks": pc, "impressions": i, "prev_impressions": pi,
             "position": round(p, 1) if p else None, "prev_position": round(pp, 1) if pp else None}
            for q, c, pc, i, pi, p, pp in rows]


# ---- Tranh nhau từ khóa ----

def cannibal(con: sqlite3.Connection, site: str, end: date, settings: KeywordSettings) -> list[dict]:
    """Mỗi từ khóa bị nhiều URL cùng nhận: danh sách URL (mạnh nhất trước) kèm phần lượt hiển thị. Nặng trước:
    URL mạnh nhất chưa vào top 3 và URL phụ chiếm phần lớn."""
    ids = [i for i, in con.execute("SELECT id FROM urls WHERE site = ?", (site,))]
    rows = K.cannibal_rows(con, site, ids, end, settings)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["query"], []).append(r)
    out = []
    for q, us in groups.items():
        total = sum(u["impressions"] for u in us) or 1
        for u in us:
            u["share"] = u["impressions"] / total
        best = us[0]
        second = max(u["share"] for u in us[1:])
        out.append({"query": q, "urls": us, "impressions": sum(u["impressions"] for u in us),
                    "clicks": sum(u["clicks"] for u in us), "position": round(best["position"], 1),
                    "split": second, "serious": best["position"] > 3 and second >= 0.25})
    out.sort(key=lambda g: (not g["serious"], -g["impressions"]))
    return out


# ---- Trang mới ----

def new_pages(con: sqlite3.Connection, site: str, end: date, days: int = NEW_DAYS) -> list[dict]:
    """URL lần đầu có lượt hiển thị trên Google (hoặc lần đầu vào sitemap) trong `days` ngày qua, mới nhất trước,
    kèm số của 7 / 30 / 90 ngày kể từ lúc xuất hiện. URL có từ đầu dữ liệu GSC không tính là mới."""
    first_data = con.execute("SELECT MIN(date) FROM gsc_fetch_log WHERE site = ?", (site,)).fetchone()[0]
    if not first_data:
        return []
    since = end - timedelta(days=days - 1)
    floor = date.fromisoformat(first_data) + timedelta(days=14)  # 2 tuần đầu dữ liệu: chưa biết là mới hay cũ
    seen = {uid: date.fromisoformat(d) for uid, d in con.execute(
        """SELECT pu.url_id, MIN(d.date) FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id
           JOIN urls u ON u.id = pu.url_id AND u.site = ? WHERE d.impressions > 0 AND d.date <= ?
           GROUP BY pu.url_id""", (site, end.isoformat()))}
    sm: dict[str, date] = {}
    try:
        for url, d in con.execute("SELECT url, first_seen FROM sitemap_urls WHERE site = ? AND first_seen > ?",
                                  (site, SITEMAP_SEED)):
            sm[url] = date.fromisoformat(d[:10])
    except sqlite3.Error:
        pass
    url_ids = dict(con.execute("SELECT url, id FROM urls WHERE site = ?", (site,)))
    cand: dict = {}  # url_id, hoặc "sm:<url>" cho URL sitemap chưa có trong danh sách URL
    variants = {i for i, u in con.execute("SELECT id, url FROM urls WHERE site = ? AND url LIKE '%?%'", (site,))}
    for uid, d in seen.items():
        if d >= max(since, floor) and uid not in variants:  # bỏ URL có tham số (biến thể màu / size sản phẩm)
            cand[uid] = {"first_seen": d, "sitemap": None}
    for url, d in sm.items():
        uid = url_ids.get(url)
        if d < since or (uid in seen and seen[uid] < d - timedelta(days=3)):
            continue  # trang cũ mới được thêm lại vào sitemap
        key = uid if uid is not None else f"sm:{url}"
        cand.setdefault(key, {"first_seen": seen.get(uid), "sitemap": None, "url": url})["sitemap"] = d
    ids = [k for k, m in cand.items() if isinstance(k, int) and m["first_seen"]]
    # Số theo ngày của mọi URL mới trong một lần đọc rồi cộng theo 7 / 30 / 90 ngày đầu của từng URL
    daily: dict[int, list[tuple]] = {}
    for chunk in (ids[i:i + 900] for i in range(0, len(ids), 900)):
        for uid, d, c, i, pw in con.execute(
                f"""SELECT pu.url_id, d.date, SUM(d.clicks), SUM(d.impressions), SUM(d.position * d.impressions)
                    FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id
                    WHERE pu.url_id IN ({','.join('?' * len(chunk))}) AND d.date BETWEEN ? AND ?
                    GROUP BY pu.url_id, d.date""", (*chunk, since.isoformat(), end.isoformat())):
            daily.setdefault(uid, []).append((date.fromisoformat(d), c or 0, i or 0, pw or 0.0))
    urls = K._texts(con, "urls", "url", {u for u in cand if isinstance(u, int)})
    out = []
    for key, m in cand.items():
        uid = key if isinstance(key, int) else None
        start = m["first_seen"]
        row = {"url": m.get("url") or urls.get(uid), "url_id": uid, "first_seen": start, "sitemap": m["sitemap"],
               "age": (end - start).days + 1 if start else None, "periods": {}, "head": None,
               "clicks": 0, "impressions": 0}
        for n in (7, 30, 90):
            last = start + timedelta(days=n - 1) if start else None
            pts = [x for x in daily.get(uid, []) if last and x[0] <= last]
            c, i, pw = sum(x[1] for x in pts), sum(x[2] for x in pts), sum(x[3] for x in pts)
            row["periods"][n] = {"clicks": c, "impressions": i, "position": round(pw / i, 1) if i else None,
                                 "done": bool(last and last <= end)}
        pts = daily.get(uid, [])
        row["clicks"], row["impressions"] = sum(x[1] for x in pts), sum(x[2] for x in pts)
        out.append(row)
    heads(con, [r for r in out if r["impressions"] >= NEW_SIGNAL], end)
    out.sort(key=lambda r: (r["first_seen"] or r["sitemap"]), reverse=True)
    return out


def heads(con, rows: list[dict], end: date) -> None:
    """Gắn từ khóa nhiều click nhất (28 ngày gần nhất) vào từng dòng trang mới, một lần đọc."""
    ids = [r["url_id"] for r in rows if r["url_id"]]
    best: dict[int, tuple] = {}
    s, e = window(end)
    for chunk in (ids[i:i + 900] for i in range(0, len(ids), 900)):
        for uid, qid, c, i, pw in con.execute(
                f"""SELECT pu.url_id, d.query_id, SUM(d.clicks), SUM(d.impressions), SUM(d.position * d.impressions)
                    FROM gsc_query_daily d JOIN page_url pu ON pu.page_id = d.page_id
                    WHERE pu.url_id IN ({','.join('?' * len(chunk))}) AND d.date BETWEEN ? AND ?
                    GROUP BY pu.url_id, d.query_id""", (*chunk, s.isoformat(), e.isoformat())):
            if uid not in best or (c, i) > best[uid][1:3]:
                best[uid] = (qid, c, i, pw / i if i else None)
    texts = K._texts(con, "queries", "text", {b[0] for b in best.values()})
    for r in rows:
        b = best.get(r["url_id"])
        if b:
            r["head"] = {"query": texts[b[0]], "clicks": b[1], "impressions": b[2],
                         "position": round(b[3], 1) if b[3] else None}


def summary(con, site: str, end: date, settings: KeywordSettings) -> dict:
    """Số đếm cho tab và thông báo (có cache)."""
    return cached(con, "summary", end, lambda: {
        "striking": striking(con, site, end, settings),
        "decay": decay(con, site, end),
        "cannibal": cannibal(con, site, end, settings),
        "new": new_pages(con, site, end),
    })
