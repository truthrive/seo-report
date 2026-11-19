"""Thông báo tổng của một dự án: gom việc cần để ý từ mọi màn (OKR, yêu cầu hỗ trợ, thứ hạng, ngân sách, dữ liệu GSC,
sitemap) vào một danh sách, có đánh dấu đã xem theo từng người.

Chỉ đọc dữ liệu đã có trong file dữ liệu dự án: không gọi API nào (không tốn tiền, mở trang nhanh).
Mỗi thông báo có `key` ổn định; key đổi khi nội dung đổi hẳn (ví dụ hạng mục được gia hạn rồi lại trễ) để thông báo
hiện lại là chưa xem."""
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone

from . import access as A

KINDS = {"okr": ("Công việc & OKR", "task_alt"), "support": ("Yêu cầu hỗ trợ", "support_agent"),
         "rank": ("Thứ hạng", "leaderboard"), "seo": ("Cơ hội SEO", "insights"),
         "backlink": ("Backlink", "add_link"), "traffic": ("Traffic", "trending_down"),
         "local": ("Local SEO", "storefront"), "system": ("Dữ liệu & hệ thống", "dns")}
# ngưỡng cảnh báo tự động (từ dữ liệu đã lấy, không gọi API)
DROP_HOURLY = 0.3          # click 24 giờ gần nhất giảm từ 30% so với 24 giờ trước đó
DROP_HOURLY_MIN = 50       # chỉ báo khi 24 giờ trước có từ chừng này click (site nhỏ dao động mạnh)
DROP_RICH = 0.3            # click của một loại kết quả (đoạn trích sản phẩm…) giảm từ 30% so với 28 ngày trước
DROP_RICH_MIN = 50
REVIEW_DAYS = 30           # đánh giá 1–3 sao chưa trả lời trong chừng này ngày gần nhất
LEVELS = {"high": ("Cần xử lý", "red"), "medium": ("Nên xem", "amber"), "info": ("Thông tin", "blue")}
_ORDER = {"high": 0, "medium": 1, "info": 2}
STALE_DAYS = 5  # GSC thường chậm 2–3 ngày; quá 5 ngày chưa có ngày mới là có vấn đề kết nối
SCHEMA = """
CREATE TABLE IF NOT EXISTS notice_popup (   -- ngày đã hiện bảng tóm tắt đầu ngày cho người này
    user TEXT NOT NULL,
    day TEXT NOT NULL,
    PRIMARY KEY (user, day)
);
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
    for i in a.get("waiting") or []:  # chờ bên ngoài lâu: nhắc người phụ trách đi hỏi (không phải trễ hạn)
        w = i.get("wait") or {}
        if w.get("days", 0) < O.WAIT_REMIND_DAYS:
            continue
        out.append(_n("okr", "medium", f"okr-wait:{i['uid']}:{w.get('start')}:{w['days'] // 7}",
                      f"{i['code']} đã chờ {w['who_label']} {w['days']} ngày: nên nhắc · {i['title']}",
                      " · ".join(x for x in (w.get("note") or "", i["pic"] or "chưa có PIC",
                                             "không tính trễ hạn trong lúc chờ") if x), "/okr", w.get("start")))
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


def _ai_block(user) -> list[dict]:
    """Model AI chính bị chặn (cổng đổi giá, hết hạn mức, khóa sai): báo Owner / Admin để vào xử lý."""
    from . import ai_settings as AIS
    if not A.is_admin(user):
        return []
    try:
        with AIS._connect() as c:
            b = AIS.block_status(c)
    except Exception:  # noqa: BLE001
        return []
    if not b:
        return []
    title = ("Model AI chính bị chặn, đang chạy bằng model kế tiếp trong combo" if b.get("fallback") else
             "Các tính năng AI đang dừng: model chính bị chặn")  # tên model: xem ở Quản trị › AI
    return [_n("system", "medium" if b.get("fallback") else "high", f"ai_block:{b['model']}:{b['at'][:10]}", title,
               re.sub(r"Model “[^”]*”", "Model chính", b.get("error", "")), "/quan-tri-ai", b["at"])]


def _backlink(con, cfg) -> list[dict]:
    """Mất link từ website mạnh, link spam mới tăng, link đã xây bị mất / đổi: từ dữ liệu đã lưu, không gọi API."""
    from . import backlink_build as BB
    from . import backlinks as BL
    if not _has(con, "backlink_lists") and not _has(con, "backlink_built"):
        return []
    ls = BL.lists(con, cfg.site_url) if _has(con, "backlink_lists") else {}
    at = max(((v or {}).get("fetched_at") or "" for v in ls.values()), default="")
    alerts = BB.alerts(con, cfg.site_url, ls)
    if _has(con, "backlink_link_runs") and _has(con, "backlink_built"):  # đối chiếu với danh sách toàn bộ backlink
        from . import backlink_links as BLL
        alerts += BB.dfs_alerts(con, cfg.site_url, BLL.latest(con, cfg.site_url))
    return [_n("backlink", a["level"], a["key"], a["title"], a["detail"], a["href"], at) for a in alerts]


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
                          f"Audit: {ch['name']} · {len(ch['pages'])} trang", ch["fix"], "/audit",
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


def _traffic(con, cfg) -> list[dict]:
    """Click tụt theo giờ (24 giờ gần nhất so với 24 giờ trước đó) và loại kết quả trên Google tụt (28 ngày)."""
    from . import gsc_types as GT
    out = []
    if _has(con, "gsc_hourly"):
        hrs = GT.hourly(con, cfg.site_url)
        last = hrs[-24:]
        if len(last) == 24 and all(h["prev_clicks"] is not None for h in last):
            now, prev = sum(h["clicks"] for h in last), sum(h["prev_clicks"] for h in last)
            if prev >= DROP_HOURLY_MIN and now <= prev * (1 - DROP_HOURLY):
                end = last[-1]["hour"]
                out.append(_n("traffic", "high", f"hourly:{end[:13]}",
                              f"Click tụt {(prev - now) / prev:.0%} trong 24 giờ gần nhất",
                              f"{now:,} click so với {prev:,} của 24 giờ trước đó (tới {end[11:16]} "
                              f"{end[8:10]}/{end[5:7]}, giờ VN). Kiểm tra web có lỗi, bị chặn index hay rớt hạng."
                              .replace(",", "."), "/nguon", end[:10]))
    if _has(con, "gsc_appearance"):
        apps, period = GT.appearance(con, cfg.site_url)
        for a in apps:
            pc = a["prev_clicks"] or 0
            if pc >= DROP_RICH_MIN and a["clicks"] <= pc * (1 - DROP_RICH):
                out.append(_n("traffic", "high", f"appearance:{a['key']}:{(period or ('', ''))[1]}",
                              f"“{a['name']}” tụt {(pc - a['clicks']) / pc:.0%} click",
                              f"{a['clicks']:,} click 28 ngày gần nhất so với {pc:,} kỳ trước. Thường do dữ liệu cấu "
                              "trúc bị lỗi / thiếu: xem tab Schema ở Technical Audit.".replace(",", "."),
                              "/audit?tab=schema", (period or ("", ""))[1]))
    return out


def _links(con, cfg) -> list[dict]:
    """Từ danh sách toàn bộ backlink: website bị Google đánh dấu nguy hiểm, link spam mới so với lần lấy trước,
    backlink trỏ về trang lỗi."""
    from . import backlink_links as BLL
    from . import link_audit as LA
    if not _has(con, "backlink_link_runs"):
        return []
    d = BLL.latest(con, cfg.site_url)
    if not d:
        return []
    items, at = d["items"], d["fetched_at"]
    out = []
    bad = sorted({x["d_from"] for x in items if x.get("threat")})
    if bad:
        out.append(_n("backlink", "high", f"links-threat:{at}:{len(bad)}",
                      f"{len(bad)} website đặt link bị Google đánh dấu nguy hiểm",
                      ", ".join(bad[:3]) + (" …" if len(bad) > 3 else "") + " · đưa vào file disavow",
                      "/backlink?tab=links", at[:10]))
    if d.get("prev"):
        new, _ = BLL.diff(items, d["prev"]["items"])
        spam = [x for x in new if (x.get("spam") or 0) >= LA.SPAM]
        if spam:
            out.append(_n("backlink", "medium", f"links-spam-new:{at}:{len(spam)}",
                          f"{len(spam)} link spam mới so với lần lấy trước",
                          ", ".join(sorted({x['d_from'] for x in spam})[:3]), "/backlink?tab=links", at[:10]))
    broken = [x for x in items if x.get("broken") or (x.get("st_to") or 0) >= 400]
    if broken:
        pages = sorted({BLL._page(x["u_to"]) for x in broken})
        out.append(_n("backlink", "medium", f"links-broken:{at}:{len(pages)}",
                      f"{len(broken)} backlink trỏ về {len(pages)} trang lỗi",
                      "Đặt redirect 301 để giữ giá trị link", "/backlink?tab=links", at[:10]))
    return out


def _local(con, today: date) -> list[dict]:
    """Đánh giá Google Maps 1–3 sao chưa trả lời (30 ngày gần nhất)."""
    if not _has(con, "gbp_reviews"):
        return []
    since = (today - timedelta(days=REVIEW_DAYS)).isoformat()
    out = []
    for rid, author, rating, comment, created in con.execute(
            "SELECT review_id, author, rating, comment, created FROM gbp_reviews WHERE rating BETWEEN 1 AND 3 AND "
            "(reply IS NULL OR reply = '') AND created >= ? ORDER BY created DESC LIMIT 10", (since,)):
        out.append(_n("local", "high", f"review:{rid}", f"Đánh giá {rating}★ chưa trả lời: {author or 'khách'}",
                      (comment or "(không có chữ)")[:140], "/local?tab=reviews", (created or "")[:10]))
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
                    lambda: _seo(con, cfg), lambda: _backlink(con, cfg), lambda: _ai_block(user),
                    lambda: _traffic(con, cfg), lambda: _links(con, cfg), lambda: _local(con, today),
                    lambda: _system(con, cfg, user, today)):
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


POPUP_MAX = 6  # số việc hiện trong bảng tóm tắt đầu ngày


def _vn_today() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=7)).date().isoformat()


def popup_items(con, user, items: list[dict], day: str | None = None) -> list[dict]:
    """Lần mở tool đầu tiên trong ngày (giờ VN): các thông báo chưa xem mức Cần xử lý / Nên xem để hiện bảng tóm tắt;
    đã hiện hôm nay hoặc không có gì đáng báo: []. Gọi là ghi nhận đã hiện (mỗi ngày một lần)."""
    ensure_tables(con)
    day = day or _vn_today()
    if con.execute("SELECT 1 FROM notice_popup WHERE user = ? AND day = ?", (str(user), day)).fetchone():
        return []
    todo = [n for n in items if not n["seen"] and n["level"] in ("high", "medium")]
    if todo:
        with con:
            con.execute("INSERT OR IGNORE INTO notice_popup VALUES (?, ?)", (str(user), day))
    return todo


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
