"""Thông báo tổng của một dự án: gom việc cần để ý từ mọi màn (OKR, yêu cầu hỗ trợ, thứ hạng, ngân sách, dữ liệu GSC,
sitemap) vào một danh sách, có đánh dấu đã xem theo từng người.

Chỉ đọc dữ liệu đã có trong file dữ liệu dự án: không gọi API nào (không tốn tiền, mở trang nhanh).
Mỗi thông báo có `key` ổn định; key đổi khi nội dung đổi hẳn (ví dụ hạng mục được gia hạn rồi lại trễ) để thông báo
hiện lại là chưa xem."""
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone

from . import access as A

KINDS = {"okr": ("Công việc & OKR", "task_alt"), "support": ("Yêu cầu hỗ trợ", "support_agent"),
         "rank": ("Thứ hạng", "leaderboard"), "seo": ("Cơ hội SEO", "insights"), "system": ("Dữ liệu & hệ thống", "dns")}
LEVELS = {"high": ("Cần xử lý", "red"), "medium": ("Nên xem", "amber"), "info": ("Thông tin", "blue")}
_ORDER = {"high": 0, "medium": 1, "info": 2}
STALE_DAYS = 5  # GSC thường chậm 2–3 ngày; quá 5 ngày chưa có ngày mới là có vấn đề kết nối
SCHEMA = """
CREATE TABLE IF NOT EXISTS notice_seen (
    user TEXT NOT NULL,
    key TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (user, key)
);
"""
_cache: dict = {}  # (file dữ liệu, vai trò, người) -> (lúc tính, danh sách): chuông ở mọi màn không tính lại liên tục
CACHE_SECONDS = 60


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _vn(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso else "–"


def _n(kind, level, key, title, detail="", href="", at="") -> dict:
    return {"kind": kind, "level": level, "key": key, "title": title, "detail": detail, "href": href, "at": at}


# ---- Từng nguồn ----

def _okr(con, today: date) -> list[dict]:
    from . import okr as O
    try:
        a = O.alerts(con, today)
    except sqlite3.Error:
        return []
    if not a["cycle"]:
        return []
    out = []
    for i in a["late"]:
        late = (today - date.fromisoformat(i["end"])).days
        out.append(_n("okr", "high", f"okr-late:{i['uid']}:{i['end']}", f"{i['code']} trễ hạn {late} ngày: {i['title']}",
                      " · ".join(x for x in (f"hạn {_vn(i['end'])}", i["pic"] or "chưa có PIC",
                                             f"đã gia hạn {i['extended']} lần" if i["extended"] else "") if x),
                      "/okr", i["end"]))
    for i in a["due_soon"]:
        left = (date.fromisoformat(i["end"]) - today).days
        out.append(_n("okr", "medium", f"okr-due:{i['uid']}:{i['end']}",
                      f"{i['code']} {'đến hạn hôm nay' if not left else f'còn {left} ngày'}: {i['title']}",
                      f"hạn {_vn(i['end'])} · {i['pic'] or 'chưa có PIC'}", "/okr", i["end"]))
    for i in a["not_started"]:
        out.append(_n("okr", "info", f"okr-idle:{i['uid']}:{i['start']}", f"{i['code']} tới ngày mà chưa bắt đầu: "
                      f"{i['title']}", f"bắt đầu {_vn(i['start'])} · {i['pic'] or 'chưa có PIC'}", "/okr", i["start"]))
    try:
        tasks = O.tasks(con)
    except sqlite3.Error:
        tasks = []
    for t in tasks:
        if t["status"] != O.DONE and t["deadline"] and t["deadline"] < today.isoformat():
            out.append(_n("okr", "medium", f"task-late:{t['row']}:{t['deadline']}",
                          f"Task tuần quá deadline: {t['task'] or t['item']}",
                          f"task tuần {_vn(t['week'])} · hạn {_vn(t['deadline'])} · {t['pic'] or 'chưa có PIC'} · "
                          "cập nhật trên sheet", "/okr", t["deadline"]))
    return out


def _support(con, user) -> list[dict]:
    from . import feedback as FB
    out = []
    if A.is_client(user):  # khách hàng: yêu cầu của mình đã có câu trả lời
        for f in FB.list_mine(con, str(user), limit=30):
            if f["reply"]:
                out.append(_n("support", "info", f"fb-reply:{f['id']}:{f['replied_at']}",
                              f"Đội SEO đã trả lời: {f['body'][:80]}", f["reply"][:140], "/yeu-cau",
                              (f["replied_at"] or "")[:10]))
        return out
    for f in FB.list_all(con, "new", limit=50):
        out.append(_n("support", "high" if f["category"] == "data" else "medium", f"fb:{f['id']}",
                      f"{FB.CATEGORIES.get(f['category'], 'Yêu cầu')} mới từ {f['author']}", f["body"][:140], "/ho-tro",
                      f["created_at"][:10]))
    return out


def _rank(con, cfg, end: date, today: date) -> list[dict]:
    from . import rank as R
    from . import rank_overview as RO
    out = []
    try:
        sets = R.sets(con, cfg.site_url)
    except sqlite3.Error:
        return []
    for st in sets:
        if st["paused"]:
            continue
        kws = [k for k in R.keywords(con, cfg.site_url, end, st["id"]) if not k["own_paused"]]
        if not kws:
            continue
        at = RO._attention(con, cfg.site_url, st, kws, today)
        if not at or at["tone"] not in ("red", "amber"):
            continue
        last = max((k["date"] for k in kws if k["date"]), default="")
        out.append(_n("rank", "high" if at["tone"] == "red" else "medium" if not st["draft"] else "info",
                      f"rank:{st['id']}:{at['filter']}:{last}", f"Bộ “{st['name']}”: {at['text']}",
                      f"check gần nhất {_vn(last)}" if last else "chưa check", f"/rank?bo={st['id']}", last))
    return out


DECAY_NOTICE_MIN = 30  # chỉ báo trang mất từ 30 click / 28 ngày (ít hơn xem ở trang Cơ hội SEO)


def _seo(con, cfg) -> list[dict]:
    """Lỗi nặng của audit kỹ thuật, trang tụt traffic mạnh (không phải mùa vụ) và từ khóa bị nhiều trang tranh nhau
    nặng: từ dữ liệu đã lưu.
    Key theo tuần của ngày GSC chốt: tuần sau còn tụt thì báo lại."""
    from . import keywords as K
    from . import opportunities as OP
    if not _has(con, "gsc_fetch_log"):
        return []
    end = K.latest_date(con, cfg.site_url)
    out = []
    try:
        from . import site_audit as SA
        au = SA.cached_findings(con, cfg)
        run_id = (au["run"] or {}).get("id")
        for ch in [c for c in au["checks"] if c["level"] == "high"]:
            out.append(_n("seo", "high", f"audit:{run_id}:{ch['code']}:{len(ch['pages'])}",
                          f"Audit: {ch['name']} · {len(ch['pages'])} trang", ch["fix"], "/co-hoi?tab=audit",
                          ((au["run"] or {}).get("finished_at") or "")[:10]))
    except Exception:  # noqa: BLE001 — chưa quét lần nào / thiếu bảng
        pass
    data = OP.peek_summary(cfg)  # chưa tính xong thì lần sau mới có: không bắt trang chờ
    if not data:
        return out
    week = f"{end.isocalendar()[0]}w{end.isocalendar()[1]}"
    site = cfg.site_url.rstrip("/")
    for r in [r for r in data["decay"] if r["lost"] >= DECAY_NOTICE_MIN and not r["seasonal"]][:5]:
        path = r["url"].replace(site, "") or "/"
        out.append(_n("seo", "high" if r["change"] <= -0.5 else "medium", f"decay:{r['url']}:{week}",
                      f"Trang tụt traffic: {path}",
                      f"{r['prev_clicks']} → {r['clicks']} click (28 ngày, −{-r['change']:.0%}) · {r['cause_text']}",
                      "/co-hoi?tab=giam", end.isoformat()))
    serious = [g for g in data["cannibal"] if g["serious"]]
    if serious:
        out.append(_n("seo", "info", f"cannibal:{week}:{len(serious)}",
                      f"{len(serious)} từ khóa bị nhiều trang của site tranh nhau",
                      "Ví dụ: " + ", ".join(f"“{g['query']}”" for g in serious[:3]), "/co-hoi?tab=tranh",
                      end.isoformat()))
    return out


def _system(con, cfg, user, today: date) -> list[dict]:
    out = []
    d = con.execute("SELECT MAX(date) FROM gsc_fetch_log WHERE site = ?", (cfg.site_url,)).fetchone()[0] \
        if _has(con, "gsc_fetch_log") else None
    if d and (today - date.fromisoformat(d)).days > STALE_DAYS:
        out.append(_n("system", "high", f"gsc-stale:{d}", f"Search Console chưa có số mới từ {_vn(d)}",
                      f"Đã {(today - date.fromisoformat(d)).days} ngày không lấy được dữ liệu mới: kiểm tra kết nối "
                      "Search Console.", "/projects" if A.is_admin(user) else "", d))
    if _has(con, "gsc_sitemaps"):
        from . import gsc_types as G
        maps = G.sitemaps(con, cfg.site_url)
        for c in G.sitemap_checks(maps, today) if maps else []:
            if c["level"] == "high":
                out.append(_n("system", "medium", f"sitemap:{c['path']}:{c['text'][:20]}",
                              f"Sitemap lỗi: {c['path']}", c["text"], "/index", ""))
    if A.can_edit(user):  # chi phí check rank là thông tin nội bộ
        try:
            from . import keywords as K
            from . import rank as R
            from .web_budget import projected
            st = R.budget_status(con, cfg.site_url, cfg.rank, K.latest_date(con, cfg.site_url))
            est = projected(st["spent"], st["estimate"], today, cfg.rank.paused)
            ratio = est / st["budget"] if st["budget"] else 0
            if ratio >= R.ALERT_RATIO:
                out.append(_n("system", "high" if ratio >= 1 else "medium", f"budget:{today:%Y-%m}:{ratio >= 1}",
                              f"Ngân sách DataForSEO dự kiến dùng {ratio:.0%} tháng này",
                              f"Dự kiến {R.usd(est)} / {st['budget']:.0f} USD · đã dùng {R.usd(st['spent'])} USD",
                              "/budget" if A.is_admin(user) else "/rank", today.isoformat()))
        except Exception:  # noqa: BLE001 — chưa cài check rank / thiếu bảng: bỏ qua
            pass
    return out


def _has(con, table: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone())


# ---- Tổng hợp ----

def collect(con, cfg, user, end: date | None = None, today: date | None = None) -> list[dict]:
    """Mọi thông báo của dự án cho người này (theo quyền), nặng trước rồi mới nhất trước. Mỗi mục có `seen`."""
    today = today or date.today()
    end = end or today
    out = _support(con, user)
    if not A.is_client(user):  # khách hàng chỉ nhận câu trả lời cho yêu cầu của mình
        for src in (lambda: _okr(con, today), lambda: _rank(con, cfg, end, today),
                    lambda: _seo(con, cfg), lambda: _system(con, cfg, user, today)):
            try:
                out += src()
            except Exception:  # noqa: BLE001 — một nguồn lỗi không làm mất cả trang thông báo
                pass
    seen = seen_keys(con, user)
    for n in out:
        n["seen"] = n["key"] in seen
    out.sort(key=lambda n: n["at"] or "", reverse=True)
    out.sort(key=lambda n: _ORDER[n["level"]])
    return out


def cached(con, cfg, user, path, end: date | None = None) -> list[dict]:
    k = (str(path), str(user), getattr(user, "role", ""))
    hit = _cache.get(k)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    out = collect(con, cfg, user, end)
    _cache[k] = (time.monotonic(), out)
    return out


def forget(path=None) -> None:
    """Bỏ bộ nhớ tạm (sau khi đánh dấu đã xem / xử lý xong) để chuông cập nhật ngay."""
    for k in [k for k in _cache if path is None or k[0] == str(path)]:
        _cache.pop(k, None)


def unseen(items: list[dict]) -> int:
    return sum(1 for n in items if not n["seen"])


def seen_keys(con, user) -> set[str]:
    ensure_tables(con)
    return {r[0] for r in con.execute("SELECT key FROM notice_seen WHERE user = ?", (str(user).lower(),))}


def mark_seen(con, user, keys: list[str]) -> None:
    if not keys:
        return
    ensure_tables(con)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        con.executemany("INSERT OR IGNORE INTO notice_seen (user, key, seen_at) VALUES (?, ?, ?)",
                        [(str(user).lower(), k, now) for k in keys])
        # dọn key cũ hơn 120 ngày (thông báo đó đã hết từ lâu)
        old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat(timespec="seconds")
        con.execute("DELETE FROM notice_seen WHERE seen_at < ?", (old,))
