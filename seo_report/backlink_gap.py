"""Backlink GAP so với đối thủ: website đang link về đối thủ nhưng chưa link về mình (DataForSEO Backlinks
API `domain_intersection`, tốn phí: chỉ gọi khi bấm nút có ghi giá).

Mỗi đối thủ một lần gọi (targets = đối thủ, exclude_targets = website mình, chỉ link dofollow), rồi gộp theo website
trỏ về: website link về càng nhiều đối thủ càng dễ xin link. Đối thủ lấy từ danh sách đối thủ của dự án (trang Đối thủ).
Giá DataForSEO Backlinks Live: 0,024 USD mỗi lần gọi + 0,000036 USD mỗi dòng.
"""
import json
import re
import sqlite3
from datetime import datetime, timezone

from . import backlinks as BL
from . import rank as R
from .projects import domain

LIMIT = 100                      # website trỏ về lấy cho mỗi đối thủ (uy tín cao trước)
COST_TASK, COST_ROW = 0.024, 0.000036
COST_PER_RIVAL = COST_TASK + COST_ROW * LIMIT
SPAM_HIDE = 30                   # mặc định ẩn website có điểm spam từ mức này
MAX_RIVALS = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS backlink_gap (
    site TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    fetched_by TEXT,
    rivals TEXT NOT NULL,          -- JSON [{"name", "domain", "total"}]
    items TEXT NOT NULL,           -- JSON [{"domain", "rank", "rivals": [tên], "backlinks", "spam", "first_seen"}]
    cost REAL NOT NULL
);
-- link cụ thể của một website trong GAP (lấy khi bấm "Xem link", lưu lại để xem lần sau không tốn phí)
CREATE TABLE IF NOT EXISTS backlink_gap_links (
    site TEXT NOT NULL,
    domain TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    fetched_by TEXT,
    links TEXT NOT NULL,           -- JSON [{"rival", "url_from", "title", "url_to", "anchor", "first_seen", "page_rank"}]
    cost REAL NOT NULL,
    PRIMARY KEY (site, domain)
);
-- kết quả riêng từng đối thủ: lấy lại một đối thủ không mất kết quả các đối thủ khác; bảng backlink_gap là bản gộp
CREATE TABLE IF NOT EXISTS backlink_gap_rivals (
    site TEXT NOT NULL,
    domain TEXT NOT NULL,
    name TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    fetched_by TEXT,
    total INTEGER,                 -- tổng website trỏ về đối thủ mà chưa trỏ về mình (DataForSEO total_count)
    items TEXT NOT NULL,           -- JSON [{"domain", "rank", "backlinks", "spam", "first_seen"}]
    cost REAL NOT NULL,
    PRIMARY KEY (site, domain)
);
-- chế độ rẻ: một lần gọi gộp mọi đối thủ (intersection_mode partial), chỉ ra website trỏ về từ 2 đối thủ trở lên
CREATE TABLE IF NOT EXISTS backlink_gap_multi (
    site TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    fetched_by TEXT,
    rivals TEXT NOT NULL,          -- JSON [{"name", "domain"}]
    items TEXT NOT NULL,           -- JSON [{"rival", "domain", "rank", "backlinks", "spam", "first_seen"}]
    cost REAL NOT NULL
);
-- đối thủ nhập tay riêng cho Backlink GAP (không thêm vào trang Đối thủ)
CREATE TABLE IF NOT EXISTS backlink_gap_extra (
    site TEXT NOT NULL,
    domain TEXT NOT NULL,
    added_by TEXT,
    added_at TEXT NOT NULL,
    PRIMARY KEY (site, domain)
);
"""
MAX_EXTRA = 20
MULTI_LIMIT = 500                # chế độ rẻ: tối đa số website trả về (một lần gọi)
MULTI_MAX_RIVALS = 20            # DataForSEO nhận tối đa 20 tên miền mỗi lần gọi
FRESH_DAYS = 30                  # backlink đổi chậm: đối thủ lấy chưa tới chừng này ngày thì nhắc chưa cần lấy lại
LINK_ATTRS = ("nofollow", "sponsored", "ugc")  # thuộc tính rel đáng ghi của link
LINK_LIMIT = 100                 # link lấy cho mỗi đối thủ khi xem link của một website


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    BL.ensure_tables(con)


def rivals(con, cfg) -> list[dict]:
    """Đối thủ của dự án có tên miền: [{"id", "name", "domain"}] (tối đa 10, theo thứ tự đã thêm)."""
    from . import aio as AO
    out = []
    for b in AO.brands(con, cfg):
        if b["own"] or not b["domains"]:
            continue
        out.append({"id": b["id"], "name": b["name"], "domain": domain(b["domains"][0])})
    return out[:MAX_RIVALS]


_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")


def clean_domain(text: str) -> str | None:
    """'https://www.abc.vn/x' → 'abc.vn'; None nếu không phải tên miền."""
    d = domain(str(text or "").strip())
    return d if _DOMAIN.match(d) else None


def extras(con, site: str) -> list[dict]:
    """Đối thủ nhập tay cho GAP: [{"id": "x:abc.vn", "name": "abc.vn", "domain": "abc.vn", "extra": True}]."""
    ensure_tables(con)
    return [{"id": f"x:{d}", "name": d, "domain": d, "extra": True} for (d,) in con.execute(
        "SELECT domain FROM backlink_gap_extra WHERE site = ? ORDER BY added_at, domain", (site,))]


def all_rivals(con, cfg) -> list[dict]:
    """Đối thủ ở trang Đối thủ + đối thủ nhập tay riêng cho GAP (bỏ trùng tên miền)."""
    base = rivals(con, cfg)
    have = {r["domain"] for r in base}
    return base + [x for x in extras(con, cfg.site_url) if x["domain"] not in have]


def add_extra(con, cfg, text: str, user: str = "") -> dict:
    """Thêm một tên miền đối thủ cho GAP. Lỗi (RuntimeError) khi sai tên miền / là website mình / đã có / quá nhiều."""
    d = clean_domain(text)
    if not d:
        raise RuntimeError("Tên miền không hợp lệ, ví dụ đúng: kinhmatabc.vn")
    own = domain(cfg.site_url)
    if d == own or d.endswith("." + own):
        raise RuntimeError("Đây là website của mình")
    if any(r["domain"] == d for r in all_rivals(con, cfg)):
        raise RuntimeError(f"{d} đã có trong danh sách đối thủ")
    if len(extras(con, cfg.site_url)) >= MAX_EXTRA:
        raise RuntimeError(f"Tối đa {MAX_EXTRA} tên miền nhập tay: bỏ bớt trước")
    with con:
        con.execute("INSERT INTO backlink_gap_extra VALUES (?, ?, ?, ?)",
                    (cfg.site_url, d, user or "", datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return {"id": f"x:{d}", "name": d, "domain": d, "extra": True}


def remove_extra(con, site: str, d: str) -> None:
    ensure_tables(con)
    with con:
        con.execute("DELETE FROM backlink_gap_extra WHERE site = ? AND domain = ?", (site, d))
    remove_result(con, site, d)


def estimate(n: int) -> float:
    return round(COST_PER_RIVAL * max(0, n), 4)


def _normalize(items: list[dict], own: str) -> list[dict]:
    """Kết quả thô domain_intersection của một đối thủ → [{"domain", "rank", "backlinks", "spam", "first_seen"}]."""
    out: dict[str, dict] = {}
    for it in items:
        d = ((it.get("domain_intersection") or {}).get("1") or {})
        name = (d.get("target") or "").lower().removeprefix("www.")
        if not name or name == own or name.endswith("." + own):
            continue
        g = out.setdefault(name, {"domain": name, "rank": 0, "backlinks": 0, "spam": 0, "first_seen": None})
        g["rank"] = max(g["rank"], d.get("rank") or 0)
        g["backlinks"] += d.get("backlinks") or 0
        g["spam"] = max(g["spam"], d.get("backlinks_spam_score") or 0)
        fs = (d.get("first_seen") or "")[:10] or None
        if fs and (not g["first_seen"] or fs < g["first_seen"]):
            g["first_seen"] = fs
    return list(out.values())


def _merge(per_rival: list[tuple[str, list[dict]]]) -> list[dict]:
    """Gộp kết quả từng đối thủ theo website trỏ về. backlinks None (dữ liệu cũ chưa tách theo đối thủ): dùng
    "legacy" (tổng cũ) khi mọi phần đều chưa tách, còn lại cộng phần biết được và đánh dấu "partial"."""
    out: dict[str, dict] = {}
    for rv_name, items in per_rival:
        for it in items:
            g = out.setdefault(it["domain"], {"domain": it["domain"], "rank": 0, "rivals": [], "backlinks": 0,
                                              "spam": 0, "first_seen": None, "_unknown": 0, "_legacy": 0})
            if rv_name not in g["rivals"]:
                g["rivals"].append(rv_name)
            g["rank"] = max(g["rank"], it.get("rank") or 0)
            if it.get("backlinks") is None:
                g["_unknown"] += 1
                g["_legacy"] = max(g["_legacy"], it.get("legacy") or 0)
            else:
                g["backlinks"] += it["backlinks"]
            g["spam"] = max(g["spam"], it.get("spam") or 0)
            fs = it.get("first_seen")
            if fs and (not g["first_seen"] or fs < g["first_seen"]):
                g["first_seen"] = fs
    for g in out.values():
        unknown, legacy = g.pop("_unknown"), g.pop("_legacy")
        if unknown and unknown == len(g["rivals"]):
            g["backlinks"] = legacy
        elif unknown:
            g["partial"] = True
    return sorted(out.values(), key=lambda g: (-len(g["rivals"]), -g["rank"]))


def _migrate(con, site: str) -> None:
    """Kết quả gộp cũ (trước khi lưu riêng từng đối thủ) → tách ra bảng riêng một lần. Số link của website trỏ về
    nhiều đối thủ không tách được theo đối thủ: để None, giữ tổng cũ ở "legacy"."""
    if con.execute("SELECT 1 FROM backlink_gap_rivals WHERE site = ? LIMIT 1", (site,)).fetchone():
        return
    row = con.execute("SELECT fetched_at, fetched_by, rivals, items FROM backlink_gap WHERE site = ?",
                      (site,)).fetchone()
    if not row:
        return
    rivals_, items = json.loads(row[2]), json.loads(row[3])
    with con:
        for r in rivals_:
            mine = [{"domain": it["domain"], "rank": it.get("rank") or 0, "spam": it.get("spam") or 0,
                     "first_seen": it.get("first_seen"), "legacy": it.get("backlinks") or 0,
                     "backlinks": (it.get("backlinks") or 0) if len(it.get("rivals") or []) == 1 else None}
                    for it in items if r.get("name") in (it.get("rivals") or [])]
            con.execute("INSERT OR IGNORE INTO backlink_gap_rivals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (site, domain(r.get("domain") or r.get("name") or ""), r.get("name") or "", row[0], row[1],
                         r.get("total"),
                         json.dumps(mine, ensure_ascii=False), 0.0))


def pairs(con, site: str) -> dict[str, dict[str, dict]]:
    """Kết quả GAP theo từng đối thủ: {tên đối thủ: {website: số liệu}} (gộp đầy đủ + chế độ nhanh, lấy số mới hơn)."""
    ensure_tables(con)
    _migrate(con, site)
    out: dict[str, dict[str, tuple[str, dict]]] = {}
    for name, at, items in con.execute("SELECT name, fetched_at, items FROM backlink_gap_rivals WHERE site = ?",
                                       (site,)):
        out[name] = {it["domain"]: (at, it) for it in json.loads(items)}
    multi = con.execute("SELECT fetched_at, items FROM backlink_gap_multi WHERE site = ?", (site,)).fetchone()
    if multi:
        for it in json.loads(multi[1]):
            cur = out.setdefault(it["rival"], {}).get(it["domain"])
            if cur is None or cur[0] <= multi[0]:
                out[it["rival"]][it["domain"]] = (multi[0], it)
    return {rv: {d: v[1] for d, v in items.items()} for rv, items in out.items()}


def rebuild(con, site: str) -> None:
    """Viết lại bản gộp (bảng backlink_gap) từ kết quả riêng từng đối thủ + kết quả chế độ rẻ. Cùng một cặp
    (đối thủ, website) có ở cả hai: lấy số của lần lấy mới hơn."""
    rows = con.execute("SELECT domain, name, fetched_at, fetched_by, total, items, cost FROM backlink_gap_rivals "
                       "WHERE site = ? ORDER BY rowid", (site,)).fetchall()
    multi = con.execute("SELECT fetched_at, fetched_by, rivals, items, cost FROM backlink_gap_multi WHERE site = ?",
                        (site,)).fetchone()
    with con:
        if not rows and not multi:
            con.execute("DELETE FROM backlink_gap WHERE site = ?", (site,))
            return
        rivals_ = [{"name": r[1], "domain": r[0], "total": r[4], "fetched_at": r[2]} for r in rows]
        pairs: dict[str, dict[str, tuple[str, dict]]] = {}  # tên đối thủ → website → (ngày lấy, số liệu)
        for r in rows:
            pairs[r[1]] = {it["domain"]: (r[2], it) for it in json.loads(r[5])}
        stamps = [(r[2], r[3]) for r in rows]
        if multi:
            stamps.append((multi[0], multi[1]))
            have = {x["domain"] for x in rivals_}
            for rv in json.loads(multi[2]):
                if rv["domain"] not in have:  # đối thủ chỉ có trong chế độ rẻ: chưa biết tổng
                    rivals_.append({"name": rv["name"], "domain": rv["domain"], "total": None,
                                    "fetched_at": multi[0], "multi_only": True})
            for it in json.loads(multi[3]):
                cur = pairs.setdefault(it["rival"], {}).get(it["domain"])
                if cur is None or cur[0] <= multi[0]:
                    pairs[it["rival"]][it["domain"]] = (multi[0], {k: v for k, v in it.items() if k != "rival"})
        merged = _merge([(name, [v[1] for v in items.values()]) for name, items in pairs.items()])
        newest = max(stamps)
        con.execute("INSERT OR REPLACE INTO backlink_gap VALUES (?, ?, ?, ?, ?, ?)",
                    (site, newest[0], newest[1], json.dumps(rivals_, ensure_ascii=False),
                     json.dumps(merged, ensure_ascii=False),
                     sum(r[6] or 0 for r in rows) + (multi[4] if multi else 0)))


def estimate_multi() -> float:
    """Giá ước tính chế độ rẻ (một lần gọi; tiền dòng tính theo khoảng 100 website, thường ít hơn)."""
    return round(COST_TASK + COST_ROW * 100, 4)


def fetch_multi(con, cfg, chosen: list[dict], user: str = "", client=None) -> dict:
    """Chế độ rẻ: một lần gọi domain_intersection cho mọi đối thủ đã chọn (2–20), lấy website dofollow trỏ về từ 2
    đối thủ trở lên mà chưa trỏ về mình. Lưu riêng, gộp vào bảng GAP cùng kết quả từng đối thủ."""
    ensure_tables(con)
    if getattr(cfg.rank, "paused", False):
        raise RuntimeError("Website đang tạm ngưng mọi chi phí DataForSEO")
    if not 2 <= len(chosen) <= MULTI_MAX_RIVALS:
        raise RuntimeError(f"Chế độ này cần chọn từ 2 tới {MULTI_MAX_RIVALS} đối thủ")
    spent = R.spent_this_month(con)
    worst = COST_TASK + COST_ROW * MULTI_LIMIT
    if spent + worst > cfg.rank.monthly_budget_usd:
        raise RuntimeError(f"Đã dùng {R.usd(spent)} USD tháng này, thêm lượt này có thể vượt ngân sách "
                           f"{cfg.rank.monthly_budget_usd:.0f} USD")
    if client is None:
        creds = R.load_credentials(cfg.dataforseo_secret)
        if not creds:
            raise RuntimeError("Chưa có API key DataForSEO")
        client = BL.Client(*creds)
    _migrate(con, cfg.site_url)
    own = domain(cfg.site_url)
    body = {"targets": {str(i + 1): r["domain"] for i, r in enumerate(chosen)}, "exclude_targets": [own],
            "intersection_mode": "partial", "limit": MULTI_LIMIT, "order_by": ["1.rank,desc"],
            "backlinks_filters": [["dofollow", "=", True]], "include_subdomains": True,
            "rank_scale": "one_thousand", "internal_list_limit": 1}
    res, cost = client._live("domain_intersection", body)
    items = []
    for it in res.get("items") or []:
        for k, d in (it.get("domain_intersection") or {}).items():
            if not d or not k.isdigit() or not 1 <= int(k) <= len(chosen):
                continue
            name = (d.get("target") or "").lower().removeprefix("www.")
            if not name or name == own or name.endswith("." + own):
                continue
            items.append({"rival": chosen[int(k) - 1]["name"], "domain": name, "rank": d.get("rank") or 0,
                          "backlinks": d.get("backlinks") or 0, "spam": d.get("backlinks_spam_score") or 0,
                          "first_seen": (d.get("first_seen") or "")[:10] or None})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        con.execute("INSERT INTO backlink_runs (run_at, site, kind, cost, by_user) VALUES (?, ?, 'gap_multi', ?, ?)",
                    (now, cfg.site_url, cost, user or ""))
        con.execute("INSERT OR REPLACE INTO backlink_gap_multi VALUES (?, ?, ?, ?, ?, ?)",
                    (cfg.site_url, now, user, json.dumps([{"name": r["name"], "domain": r["domain"]} for r in chosen],
                                                         ensure_ascii=False),
                     json.dumps(items, ensure_ascii=False), cost))
    rebuild(con, cfg.site_url)
    return {"sites": len({x["domain"] for x in items}), "cost": cost, "total": res.get("total_count")}


def fetched(con, site: str) -> dict[str, str]:
    """Ngày lấy gần nhất của từng đối thủ: {tên miền: ISO}."""
    ensure_tables(con)
    _migrate(con, site)
    return {d: at for d, at in con.execute("SELECT domain, fetched_at FROM backlink_gap_rivals WHERE site = ?",
                                           (site,))}


def remove_result(con, site: str, d: str) -> None:
    """Bỏ kết quả của một đối thủ khỏi bảng GAP (không gọi API)."""
    ensure_tables(con)
    _migrate(con, site)
    with con:
        con.execute("DELETE FROM backlink_gap_rivals WHERE site = ? AND domain = ?", (site, d))
        row = con.execute("SELECT rivals, items FROM backlink_gap_multi WHERE site = ?", (site,)).fetchone()
        if row:  # bỏ luôn phần của đối thủ này trong kết quả chế độ rẻ
            rv = [r for r in json.loads(row[0]) if r["domain"] != d]
            gone = {r["name"] for r in json.loads(row[0]) if r["domain"] == d}
            its = [x for x in json.loads(row[1]) if x["rival"] not in gone]
            con.execute("UPDATE backlink_gap_multi SET rivals = ?, items = ? WHERE site = ?",
                        (json.dumps(rv, ensure_ascii=False), json.dumps(its, ensure_ascii=False), site))
    rebuild(con, site)


def fetch(con, cfg, chosen: list[dict], user: str = "", client=None, log=print) -> dict:
    """Gọi DataForSEO cho từng đối thủ đã chọn rồi lưu kết quả gộp. Chặn khi vượt ngân sách tháng của dự án."""
    ensure_tables(con)
    if getattr(cfg.rank, "paused", False):
        raise RuntimeError("Website đang tạm ngưng mọi chi phí DataForSEO")
    if not chosen:
        raise RuntimeError("Chưa chọn đối thủ nào")
    spent = R.spent_this_month(con)
    if spent + estimate(len(chosen)) > cfg.rank.monthly_budget_usd:
        raise RuntimeError(f"Đã dùng {R.usd(spent)} USD tháng này, thêm lượt này sẽ vượt ngân sách "
                           f"{cfg.rank.monthly_budget_usd:.0f} USD")
    if client is None:
        creds = R.load_credentials(cfg.dataforseo_secret)
        if not creds:
            raise RuntimeError("Chưa có API key DataForSEO")
        client = BL.Client(*creds)
    own = domain(cfg.site_url)
    _migrate(con, cfg.site_url)
    per, total_cost = [], 0.0
    for rv in chosen:
        body = {"targets": {"1": rv["domain"]}, "exclude_targets": [own], "limit": LIMIT,
                "order_by": ["1.rank,desc"], "backlinks_filters": [["dofollow", "=", True]],
                "include_subdomains": True, "rank_scale": "one_thousand", "internal_list_limit": 1}
        try:
            try:
                res, cost = client._live("domain_intersection", body)
            except RuntimeError:  # sắp xếp theo uy tín không được nhận: dùng cách sắp xếp có trong tài liệu
                res, cost = client._live("domain_intersection", {**body, "order_by": ["1.backlinks,desc"]})
        except Exception as e:  # noqa: BLE001
            log(f"Không lấy được backlink GAP của {rv['name']}: {e}")
            continue
        total_cost += cost
        per.append((rv, res.get("total_count"), _normalize(res.get("items") or [], own), cost))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        BL.ensure_tables(con)
        con.execute("INSERT INTO backlink_runs (run_at, site, kind, cost, by_user) VALUES (?, ?, 'gap', ?, ?)",
                    (now, cfg.site_url, total_cost, user or ""))
        for rv, total, items, cost in per:  # chỉ thay kết quả các đối thủ vừa lấy, đối thủ khác giữ nguyên
            con.execute("INSERT OR REPLACE INTO backlink_gap_rivals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (cfg.site_url, rv["domain"], rv["name"], now, user, total,
                         json.dumps(items, ensure_ascii=False), cost))
    if per:
        rebuild(con, cfg.site_url)
    if not per:
        raise RuntimeError("Không lấy được dữ liệu đối thủ nào")
    return {"rivals": len(per), "cost": total_cost}


def by_rival(con, cfg) -> dict:
    """Khoảng trống backlink theo từng đối thủ đang theo dõi (từ lần chạy GAP gần nhất, không gọi API):
    {"fetched_at", "rows": [{"name", "domain", "total"}] (nhiều trước), "missing": [tên đối thủ chưa có số],
    "shared": số website uy tín (không spam) trỏ về từ 2 đối thủ trở lên}; chưa chạy lần nào: None."""
    last = latest(con, cfg.site_url)
    if not last:
        return None
    got = {domain(r.get("domain") or ""): r for r in last["rivals"]}
    rows, missing = [], []
    for rv in rivals(con, cfg):
        r = got.get(rv["domain"])
        if r is None or r.get("total") is None:
            missing.append(rv["name"])
        else:
            rows.append({"name": rv["name"], "domain": rv["domain"], "total": int(r.get("total") or 0)})
    rows.sort(key=lambda r: -r["total"])
    shared = sum(1 for it in last["items"] if len(it.get("rivals") or []) >= 2 and (it.get("spam") or 0) < SPAM_HIDE)
    return {"fetched_at": last["fetched_at"], "rows": rows, "missing": missing, "shared": shared}


def latest(con, site: str) -> dict | None:
    ensure_tables(con)
    _migrate(con, site)
    row = con.execute("SELECT fetched_at, fetched_by, rivals, items, cost FROM backlink_gap WHERE site = ?",
                      (site,)).fetchone()
    if not row:
        return None
    return {"fetched_at": row[0], "by": row[1], "rivals": json.loads(row[2]), "items": json.loads(row[3]),
            "cost": row[4]}


# ---------------------------------------------------------------- link cụ thể của một website

def _item(gap: dict | None, dom: str) -> dict | None:
    return next((g for g in (gap or {}).get("items") or [] if g["domain"] == dom), None)


def link_targets(con, cfg, dom: str) -> list[dict]:
    """Đối thủ mà website `dom` đang trỏ về (theo lần tìm GAP gần nhất): [{"name", "domain"}]."""
    it = _item(latest(con, cfg.site_url), dom)
    if not it:
        return []
    by_name = {r["name"]: r for r in (latest(con, cfg.site_url) or {}).get("rivals") or []}
    return [{"name": n, "domain": by_name[n]["domain"]} for n in it["rivals"] if n in by_name]


def links_estimate(con, cfg, dom: str) -> float:
    it = _item(latest(con, cfg.site_url), dom) or {}
    n = len(link_targets(con, cfg, dom))
    rows = min(it.get("backlinks") or 0, n * LINK_LIMIT)
    return round(n * COST_TASK + rows * COST_ROW, 4)


def _same_site(host: str, dom: str) -> bool:
    host = (host or "").lower().removeprefix("www.")
    return host == dom or host.endswith("." + dom)


def fetch_links(con, cfg, dom: str, user: str = "", client=None) -> dict:
    """Lấy các link dofollow còn sống từ website `dom` tới từng đối thủ nó đang trỏ về (một lần gọi mỗi đối thủ,
    DataForSEO Backlinks `backlinks`, tốn phí). Lưu lại; trả {"links": [...], "cost"}."""
    ensure_tables(con)
    if getattr(cfg.rank, "paused", False):
        raise RuntimeError("Website đang tạm ngưng mọi chi phí DataForSEO")
    targets = link_targets(con, cfg, dom)
    if not targets:
        raise RuntimeError("Website này không còn trong kết quả Backlink GAP")
    spent = R.spent_this_month(con)
    est = links_estimate(con, cfg, dom)
    if spent + est > cfg.rank.monthly_budget_usd:
        raise RuntimeError(f"Đã dùng {R.usd(spent)} USD tháng này, thêm lượt này sẽ vượt ngân sách "
                           f"{cfg.rank.monthly_budget_usd:.0f} USD")
    if client is None:
        creds = R.load_credentials(cfg.dataforseo_secret)
        if not creds:
            raise RuntimeError("Chưa có API key DataForSEO")
        client = BL.Client(*creds)
    links, total, errors = [], 0.0, []
    for rv in targets:
        body = {"target": rv["domain"], "mode": "as_is", "limit": LINK_LIMIT, "backlinks_status_type": "live",
                "include_subdomains": True, "rank_scale": "one_thousand", "order_by": ["page_from_rank,desc"],
                "filters": [["domain_from", "like", f"%{dom}"]]}  # lấy cả nofollow, ghi loại từng link
        try:
            res, cost = client._live("backlinks", body)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{rv['name']}: {e}")
            continue
        total += cost
        for x in res.get("items") or []:
            if not _same_site(x.get("domain_from") or "", dom):
                continue
            links.append({"rival": rv["name"], "url_from": x.get("url_from") or "",
                          "title": " ".join(str(x.get("page_from_title") or "").split())[:200],
                          "url_to": x.get("url_to") or "", "anchor": " ".join(str(x.get("anchor") or "").split()),
                          "first_seen": (x.get("first_seen") or "")[:10] or None,
                          "page_rank": x.get("page_from_rank") or 0, "dofollow": bool(x.get("dofollow")),
                          "attrs": [a for a in (x.get("attributes") or []) if a in LINK_ATTRS]})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        con.execute("INSERT INTO backlink_runs (run_at, site, kind, cost, by_user) VALUES (?, ?, 'gap_links', ?, ?)",
                    (now, cfg.site_url, total, user or ""))
        if len(errors) < len(targets):
            con.execute("INSERT OR REPLACE INTO backlink_gap_links VALUES (?, ?, ?, ?, ?, ?)",
                        (cfg.site_url, dom, now, user, json.dumps(links, ensure_ascii=False), total))
    if len(errors) == len(targets):
        raise RuntimeError("Không lấy được link: " + "; ".join(errors)[:200])
    return {"links": links, "cost": total, "errors": errors}


def saved_links(con, site: str) -> dict[str, dict]:
    """Link đã lấy theo website: {domain: {"fetched_at", "links"}}."""
    ensure_tables(con)
    return {d: {"fetched_at": at, "links": json.loads(js)} for d, at, js in con.execute(
        "SELECT domain, fetched_at, links FROM backlink_gap_links WHERE site = ?", (site,))}
