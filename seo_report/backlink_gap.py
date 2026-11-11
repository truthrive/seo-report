"""Backlink GAP so với đối thủ: website đang link về đối thủ nhưng chưa link về mình (DataForSEO Backlinks
API `domain_intersection`, tốn phí: chỉ gọi khi bấm nút có ghi giá).

Mỗi đối thủ một lần gọi (targets = đối thủ, exclude_targets = website mình, chỉ link dofollow), rồi gộp theo website
trỏ về: website link về càng nhiều đối thủ càng dễ xin link. Đối thủ lấy từ danh sách đối thủ của dự án (trang Đối thủ).
Giá DataForSEO Backlinks Live: 0,024 USD mỗi lần gọi + 0,000036 USD mỗi dòng.
"""
import json
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
"""


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


def estimate(n: int) -> float:
    return round(COST_PER_RIVAL * max(0, n), 4)


def _merge(per_rival: list[tuple[dict, list[dict]]], own: str) -> list[dict]:
    """Gộp kết quả từng đối thủ theo website trỏ về."""
    out: dict[str, dict] = {}
    for rv, items in per_rival:
        for it in items:
            d = ((it.get("domain_intersection") or {}).get("1") or {})
            name = (d.get("target") or "").lower().removeprefix("www.")
            if not name or name == own or name.endswith("." + own):
                continue
            g = out.setdefault(name, {"domain": name, "rank": 0, "rivals": [], "backlinks": 0, "spam": 0,
                                      "first_seen": None})
            if rv["name"] not in g["rivals"]:
                g["rivals"].append(rv["name"])
            g["rank"] = max(g["rank"], d.get("rank") or 0)
            g["backlinks"] += d.get("backlinks") or 0
            g["spam"] = max(g["spam"], d.get("backlinks_spam_score") or 0)
            fs = (d.get("first_seen") or "")[:10] or None
            if fs and (not g["first_seen"] or fs < g["first_seen"]):
                g["first_seen"] = fs
    return sorted(out.values(), key=lambda g: (-len(g["rivals"]), -g["rank"]))


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
    per, total_cost, done = [], 0.0, []
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
        per.append((rv, res.get("items") or []))
        done.append({"name": rv["name"], "domain": rv["domain"], "total": res.get("total_count")})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        con.execute("INSERT INTO backlink_runs VALUES (?, ?, 'gap', ?)", (now, cfg.site_url, total_cost))
        if per:
            con.execute("INSERT OR REPLACE INTO backlink_gap VALUES (?, ?, ?, ?, ?, ?)",
                        (cfg.site_url, now, user, json.dumps(done, ensure_ascii=False),
                         json.dumps(_merge(per, own), ensure_ascii=False), total_cost))
    if not per:
        raise RuntimeError("Không lấy được dữ liệu đối thủ nào")
    return {"rivals": len(per), "cost": total_cost}


def latest(con, site: str) -> dict | None:
    ensure_tables(con)
    row = con.execute("SELECT fetched_at, fetched_by, rivals, items, cost FROM backlink_gap WHERE site = ?",
                      (site,)).fetchone()
    if not row:
        return None
    return {"fetched_at": row[0], "by": row[1], "rivals": json.loads(row[2]), "items": json.loads(row[3]),
            "cost": row[4]}
