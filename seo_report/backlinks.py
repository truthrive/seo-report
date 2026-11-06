"""Backlink của website (DataForSEO Backlinks API, trả tiền theo lần gọi, không có mức tối thiểu hằng tháng).

- Số tổng (`backlinks/summary/live`, khoảng 0,02 USD / lần): số backlink, số website trỏ về, uy tín 0–1000, điểm spam,
  link gãy. Lưu mỗi lần lấy (`backlink_snapshots`) để so tuần này với lần trước.
- Lịch sử theo tháng (`backlinks/history/live`): backlink, website trỏ về, link mới / mất của từng tháng; lấy lại khi sang
  tháng mới (`backlink_history`).
- Bốn danh sách cho trang Backlink (`backlink_lists`, mỗi lần lấy ghi đè): website trỏ về (`referring_domains`), link
  mới / mất 30 ngày (`backlinks`), anchor text (`anchors`), trang được link nhiều nhất (`domain_pages`); mỗi danh sách
  khoảng 0,02 USD / lần, lấy cùng lúc với số tổng.
- Chi phí ghi vào `backlink_runs`, tính chung ngân sách DataForSEO của website (cùng check rank và volume); website tạm
  ngưng check rank thì không gọi.
Lịch: việc chạy hằng ngày lấy lại khi lần gần nhất đã cũ hơn REFRESH_DAYS ngày; nút ở Tổng quan lấy ngay.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import rank as R
from .projects import domain

BASE = "https://api.dataforseo.com/v3/backlinks"
REFRESH_DAYS = 7
EST_COST = 0.15  # ước tính một lượt (số tổng + lịch sử + 4 danh sách) để chặn trước khi gọi; số thật lấy từ phản hồi
LIST_KINDS = ("domains", "changes", "anchors", "pages")
CHANGE_DAYS = 30  # link mới / mất trong bao nhiêu ngày gần nhất

SCHEMA = """
CREATE TABLE IF NOT EXISTS backlink_snapshots (
    site TEXT NOT NULL,
    day TEXT NOT NULL,
    backlinks INTEGER,
    referring_domains INTEGER,
    referring_main_domains INTEGER,
    referring_domains_nofollow INTEGER,
    rank INTEGER,
    spam_score INTEGER,
    broken_backlinks INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (site, day)
);
CREATE TABLE IF NOT EXISTS backlink_history (
    site TEXT NOT NULL,
    month TEXT NOT NULL,          -- YYYY-MM
    backlinks INTEGER,
    referring_domains INTEGER,
    new_backlinks INTEGER,
    lost_backlinks INTEGER,
    new_referring_domains INTEGER,
    lost_referring_domains INTEGER,
    rank INTEGER,
    PRIMARY KEY (site, month)
);
CREATE TABLE IF NOT EXISTS backlink_lists (
    site TEXT NOT NULL,
    kind TEXT NOT NULL,           -- domains | changes | anchors | pages
    fetched_at TEXT NOT NULL,
    total INTEGER,                -- tổng số dòng DataForSEO có (danh sách chỉ giữ phần đầu)
    items TEXT NOT NULL,          -- JSON, chỉ các cột trang Backlink dùng
    PRIMARY KEY (site, kind)
);
CREATE TABLE IF NOT EXISTS backlink_settings (
    site TEXT PRIMARY KEY,
    every_days INTEGER NOT NULL,  -- tự lấy lại sau bao nhiêu ngày (7 / 14 / 30)
    paused INTEGER NOT NULL,      -- 1: không tự lấy, chỉ lấy khi bấm "Lấy số mới"
    lists TEXT NOT NULL,          -- danh sách lấy kèm, cách nhau dấu phẩy (rỗng: chỉ số tổng)
    updated_by TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS backlink_runs (
    run_at TEXT NOT NULL,
    site TEXT NOT NULL,
    kind TEXT NOT NULL,           -- summary | history
    cost REAL NOT NULL
);
"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def spent_this_month(con: sqlite3.Connection, today: date) -> float:
    ensure_tables(con)
    return con.execute("SELECT COALESCE(SUM(cost), 0) FROM backlink_runs WHERE substr(run_at, 1, 7) = ?",
                       (today.strftime("%Y-%m"),)).fetchone()[0]


class Client:
    """Gọi DataForSEO Backlinks API bằng tài khoản DataForSEO đang dùng cho check rank."""

    def __init__(self, login: str, password: str, timeout: int = 60):
        self._rank = R.DataForSEO(login, password, timeout)

    def _live(self, endpoint: str, body: dict) -> tuple[dict, float]:
        req = Request(f"{BASE}/{endpoint}/live", data=json.dumps([body]).encode(), method="POST",
                      headers=self._rank.headers)
        try:
            resp = json.loads(urlopen(req, timeout=self._rank.timeout).read())
        except HTTPError as e:
            try:
                resp = json.loads(e.read())
            except ValueError:
                raise RuntimeError(f"DataForSEO trả lỗi HTTP {e.code}") from e
        if resp.get("status_code") != 20000:
            raise RuntimeError(f"DataForSEO {resp.get('status_code')}: {resp.get('status_message')}")
        task = resp["tasks"][0]
        if task.get("status_code") != 20000:  # ví dụ 40204: tài khoản chưa bật Backlinks API
            raise RuntimeError(f"DataForSEO {task.get('status_code')}: {task.get('status_message')}")
        return (task.get("result") or [{}])[0] or {}, float(task.get("cost") or 0)

    def summary(self, target: str) -> tuple[dict, float]:
        return self._live("summary", {"target": target, "include_subdomains": True, "internal_list_limit": 1,
                                      "backlinks_status_type": "live", "rank_scale": "one_thousand"})

    def history(self, target: str, date_from: str) -> tuple[list[dict], float]:
        res, cost = self._live("history", {"target": target, "date_from": date_from, "rank_scale": "one_thousand"})
        return res.get("items") or [], cost

    def referring_domains(self, target: str, limit: int = 100) -> tuple[dict, float]:
        return self._live("referring_domains", {"target": target, "limit": limit, "order_by": ["rank,desc"],
                                                "backlinks_status_type": "live", "include_subdomains": True,
                                                "internal_list_limit": 1, "rank_scale": "one_thousand"})

    def changes(self, target: str, since: str, limit: int = 200) -> tuple[dict, float]:
        """Backlink mới thấy (first_seen) hoặc vừa mất (is_lost, last_seen) từ ngày `since`."""
        stamp = f"{since} 00:00:00 +00:00"
        return self._live("backlinks", {
            "target": target, "mode": "as_is", "limit": limit, "backlinks_status_type": "all",
            "include_subdomains": True, "rank_scale": "one_thousand", "order_by": ["first_seen,desc"],
            "filters": [["first_seen", ">", stamp], "or", [["is_lost", "=", True], "and", ["last_seen", ">", stamp]]]})

    def anchors(self, target: str, limit: int = 100) -> tuple[dict, float]:
        return self._live("anchors", {"target": target, "limit": limit, "order_by": ["referring_domains,desc"],
                                      "backlinks_status_type": "live", "include_subdomains": True,
                                      "internal_list_limit": 1, "rank_scale": "one_thousand"})

    def pages(self, target: str, limit: int = 50) -> tuple[dict, float]:
        return self._live("domain_pages", {"target": target, "limit": limit,
                                           "order_by": ["page_summary.referring_domains,desc"],
                                           "backlinks_status_type": "live", "include_subdomains": True,
                                           "internal_list_limit": 1, "rank_scale": "one_thousand"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def latest(con: sqlite3.Connection, site: str) -> dict | None:
    """Lần lấy mới nhất và lần trước đó (để so): {now, prev, history: [tháng cũ → mới]}. None khi chưa lấy lần nào."""
    ensure_tables(con)
    cols = ("day", "backlinks", "referring_domains", "referring_main_domains", "referring_domains_nofollow", "rank",
            "spam_score", "broken_backlinks")
    rows = [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {', '.join(cols)} FROM backlink_snapshots WHERE site = ? ORDER BY day DESC LIMIT 2", (site,))]
    if not rows:
        return None
    hcols = ("month", "backlinks", "referring_domains", "new_backlinks", "lost_backlinks", "new_referring_domains",
             "lost_referring_domains", "rank")
    hist = [dict(zip(hcols, r)) for r in con.execute(
        f"SELECT {', '.join(hcols)} FROM backlink_history WHERE site = ? ORDER BY month DESC LIMIT 12", (site,))]
    return {"now": rows[0], "prev": rows[1] if len(rows) > 1 else None, "history": hist[::-1]}


def _day(v) -> str:
    """"2026-10-02 08:11:41 +00:00" → "2026-10-02"."""
    return str(v or "")[:10]


def _slim(kind: str, it: dict) -> dict:
    """Chỉ giữ các cột trang Backlink dùng (kết quả DataForSEO rất nhiều trường)."""
    if kind == "domains":
        pages, nofollow = it.get("referring_pages") or 0, it.get("referring_pages_nofollow") or 0
        return {"domain": it.get("domain"), "rank": it.get("rank"), "backlinks": it.get("backlinks"),
                "pages": pages, "dofollow_pages": max(pages - nofollow, 0), "first_seen": _day(it.get("first_seen")),
                "spam": it.get("backlinks_spam_score")}
    if kind == "changes":
        return {"lost": bool(it.get("is_lost")), "domain_from": it.get("domain_from"), "url_from": it.get("url_from"),
                "title": it.get("page_from_title"), "url_to": it.get("url_to"), "anchor": it.get("anchor"),
                "dofollow": bool(it.get("dofollow")), "type": it.get("item_type"),
                "domain_rank": it.get("domain_from_rank"), "spam": it.get("backlink_spam_score"),
                "first_seen": _day(it.get("first_seen")),
                "last_seen": _day(it.get("last_seen"))}
    if kind == "anchors":
        return {"anchor": it.get("anchor"), "backlinks": it.get("backlinks"),
                "domains": it.get("referring_domains"), "first_seen": _day(it.get("first_seen")),
                "spam": it.get("backlinks_spam_score")}
    ps = it.get("page_summary") or {}
    return {"page": it.get("page"), "title": (it.get("meta") or {}).get("title"), "backlinks": ps.get("backlinks"),
            "domains": ps.get("referring_domains"), "rank": ps.get("rank"), "status": it.get("status_code")}


def save_list(con: sqlite3.Connection, site: str, kind: str, res: dict, cost: float) -> int:
    items = [_slim(kind, it) for it in (res.get("items") or [])]
    with con:
        con.execute("INSERT OR REPLACE INTO backlink_lists VALUES (?, ?, ?, ?, ?)",
                    (site, kind, _now(), res.get("total_count"), json.dumps(items, ensure_ascii=False)))
        con.execute("INSERT INTO backlink_runs VALUES (?, ?, ?, ?)", (_now(), site, kind, cost))
    return len(items)


def lists(con: sqlite3.Connection, site: str) -> dict[str, dict]:
    """Bốn danh sách đã lấy: {kind: {"fetched_at", "total", "items"}}; danh sách chưa lấy thì không có khóa."""
    ensure_tables(con)
    return {kind: {"fetched_at": at, "total": total, "items": json.loads(items)}
            for kind, at, total, items in con.execute(
                "SELECT kind, fetched_at, total, items FROM backlink_lists WHERE site = ?", (site,))}


EVERY_CHOICES = {7: "Mỗi tuần", 14: "2 tuần một lần", 30: "Mỗi tháng"}
COST_SUMMARY, COST_LIST = 0.025, 0.027  # USD mỗi lần (theo hóa đơn thật 06/11/2026), để ước tính chi phí tháng


def settings(con: sqlite3.Connection, site: str) -> dict:
    """Lịch tự lấy của website: {"every_days", "paused", "lists"}. Chưa đặt: mỗi tuần, đủ 4 danh sách."""
    ensure_tables(con)
    row = con.execute("SELECT every_days, paused, lists FROM backlink_settings WHERE site = ?", (site,)).fetchone()
    if not row:
        return {"every_days": REFRESH_DAYS, "paused": False, "lists": list(LIST_KINDS)}
    return {"every_days": row[0], "paused": bool(row[1]), "lists": [k for k in row[2].split(",") if k in LIST_KINDS]}


def save_settings(con: sqlite3.Connection, site: str, every_days: int, paused: bool, lists: list[str],
                  user: str = "") -> None:
    if every_days not in EVERY_CHOICES:
        raise ValueError("Chu kỳ lấy không hợp lệ")
    ensure_tables(con)
    with con:
        con.execute("INSERT OR REPLACE INTO backlink_settings VALUES (?, ?, ?, ?, ?, ?)",
                    (site, every_days, int(paused), ",".join(k for k in LIST_KINDS if k in lists), user, _now()))


def monthly_estimate(st: dict) -> float:
    """Chi phí ước tính mỗi tháng theo lịch (0 khi tạm ngưng tự lấy)."""
    if st["paused"]:
        return 0.0
    return (COST_SUMMARY + COST_LIST * len(st["lists"])) * 30 / st["every_days"]


def next_due(con: sqlite3.Connection, site: str, today: date | None = None) -> date | None:
    """Ngày tự lấy lần tới (None: đang tạm ngưng). Chưa lấy lần nào: hôm nay (lượt chạy sáng mai)."""
    st = settings(con, site)
    if st["paused"]:
        return None
    last = con.execute("SELECT MAX(day) FROM backlink_snapshots WHERE site = ?", (site,)).fetchone()[0]
    today = today or date.today()
    return max(date.fromisoformat(last) + timedelta(days=st["every_days"]), today) if last else today


def fetch_lists(con: sqlite3.Connection, site: str, client, target: str, today: date, log=print,
                kinds: list[str] | None = None) -> float:
    """Lấy lại các danh sách (mặc định cả bốn); danh sách nào lỗi thì giữ bản cũ và báo, không chặn các danh sách
    khác."""
    since = (today - timedelta(days=CHANGE_DAYS)).isoformat()
    calls = {"domains": lambda: client.referring_domains(target), "changes": lambda: client.changes(target, since),
             "anchors": lambda: client.anchors(target), "pages": lambda: client.pages(target)}
    if kinds is not None:
        calls = {k: v for k, v in calls.items() if k in kinds}
    total = 0.0
    for kind, call in calls.items():
        try:
            res, cost = call()
        except Exception as e:  # noqa: BLE001
            log(f"Không lấy được danh sách {kind}: {e}")
            continue
        save_list(con, site, kind, res, cost)
        total += cost
    return total


def save_summary(con: sqlite3.Connection, site: str, res: dict, day: date, cost: float) -> None:
    with con:
        con.execute("INSERT OR REPLACE INTO backlink_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (site, day.isoformat(), res.get("backlinks"), res.get("referring_domains"),
                     res.get("referring_main_domains"), res.get("referring_domains_nofollow"), res.get("rank"),
                     res.get("backlinks_spam_score"), res.get("broken_backlinks"), _now()))
        con.execute("INSERT INTO backlink_runs VALUES (?, ?, 'summary', ?)", (_now(), site, cost))


def save_history(con: sqlite3.Connection, site: str, items: list[dict], cost: float) -> int:
    with con:
        for it in items:
            month = str(it.get("date") or "")[:7]
            if len(month) != 7:
                continue
            con.execute("INSERT OR REPLACE INTO backlink_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (site, month, it.get("backlinks"), it.get("referring_domains"), it.get("new_backlinks"),
                         it.get("lost_backlinks"), it.get("new_referring_domains"), it.get("lost_referring_domains"),
                         it.get("rank")))
        con.execute("INSERT INTO backlink_runs VALUES (?, ?, 'history', ?)", (_now(), site, cost))
    return len(items)


def refresh(con: sqlite3.Connection, site: str, cfg, today: date | None = None, force: bool = False, log=print,
            client: Client | None = None) -> bool:
    """Lấy số backlink theo lịch của website (settings: mỗi 7 / 14 / 30 ngày, hoặc tạm ngưng tự lấy); force: lấy ngay
    (nút "Lấy số mới", kể cả khi đang tạm ngưng tự lấy). Chỉ lấy các danh sách đã chọn. Lịch sử theo tháng lấy tối đa
    một lần mỗi tháng. Trả True khi đã gọi DataForSEO."""
    ensure_tables(con)
    today = today or date.today()
    if getattr(cfg.rank, "paused", False):  # tạm ngưng check rank = ngưng mọi chi phí DataForSEO của website
        log("Tạm ngưng: không lấy số backlink.")
        return False
    st = settings(con, site)
    if not force and st["paused"]:
        return False
    last = con.execute("SELECT MAX(day) FROM backlink_snapshots WHERE site = ?", (site,)).fetchone()[0]
    if not force and last and date.fromisoformat(last) > today - timedelta(days=st["every_days"]):
        return False
    if client is None:
        creds = R.load_credentials(cfg.dataforseo_secret)
        if not creds:
            log(f"Chưa có API key DataForSEO trong {cfg.dataforseo_secret}: bỏ qua backlink.")
            return False
        client = Client(*creds)
    spent = R.spent_this_month(con, today)
    if spent + EST_COST > cfg.rank.monthly_budget_usd:
        raise RuntimeError(f"Đã dùng {R.usd(spent)} USD tháng này, vượt ngân sách "
                           f"{cfg.rank.monthly_budget_usd:.0f} USD: không lấy số backlink.")
    target = domain(site)
    res, cost = client.summary(target)
    save_summary(con, site, res, today, cost)
    prev_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    have = con.execute("SELECT 1 FROM backlink_history WHERE site = ? AND month = ?", (site, prev_month)).fetchone()
    # DataForSEO có thể chưa có số tháng trước: đã hỏi trong tháng này rồi thì thôi, không trả tiền hỏi lại mỗi tuần
    asked = con.execute("SELECT 1 FROM backlink_runs WHERE site = ? AND kind = 'history' AND substr(run_at, 1, 7) = ?",
                        (site, datetime.now(timezone.utc).strftime("%Y-%m"))).fetchone()
    if not have and not asked:  # lịch sử 13 tháng gần nhất (đủ cho biểu đồ 12 tháng + tháng đang chạy)
        start = (today.replace(day=1) - timedelta(days=366)).replace(day=1).isoformat()
        items, hcost = client.history(target, start)
        save_history(con, site, items, hcost)
        cost += hcost
    cost += fetch_lists(con, site, client, target, today, log, kinds=st["lists"])
    log(f"Đã lấy số backlink của {target}: {res.get('referring_domains')} website trỏ về, "
        f"{res.get('backlinks')} backlink ({R.usd(cost, 3)} USD).")
    return True
