"""Backlink của website (DataForSEO Backlinks API, trả tiền theo lần gọi, không có mức tối thiểu hằng tháng).

- Số tổng (`backlinks/summary/live`, khoảng 0,02 USD / lần): số backlink, số website trỏ về, uy tín 0–1000, điểm spam,
  link gãy. Lưu mỗi lần lấy (`backlink_snapshots`) để so tuần này với lần trước.
- Lịch sử theo tháng (`backlinks/history/live`): backlink, website trỏ về, link mới / mất của từng tháng; lấy lại khi sang
  tháng mới (`backlink_history`).
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
EST_COST = 0.05  # ước tính một lượt (số tổng + lịch sử) để chặn trước khi gọi; số trừ thật lấy từ phản hồi

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
    """Lấy số backlink khi lần gần nhất cũ hơn REFRESH_DAYS ngày (force: lấy ngay). Lịch sử theo tháng chỉ lấy lại khi
    chưa có số của tháng trước. Trả True khi đã gọi DataForSEO."""
    ensure_tables(con)
    today = today or date.today()
    if getattr(cfg.rank, "paused", False):  # tạm ngưng check rank = ngưng mọi chi phí DataForSEO của website
        log("Tạm ngưng: không lấy số backlink.")
        return False
    last = con.execute("SELECT MAX(day) FROM backlink_snapshots WHERE site = ?", (site,)).fetchone()[0]
    if not force and last and date.fromisoformat(last) > today - timedelta(days=REFRESH_DAYS):
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
    if not have:  # lịch sử 13 tháng gần nhất (đủ cho biểu đồ 12 tháng + tháng đang chạy)
        start = (today.replace(day=1) - timedelta(days=366)).replace(day=1).isoformat()
        items, hcost = client.history(target, start)
        save_history(con, site, items, hcost)
        cost += hcost
    log(f"Đã lấy số backlink của {target}: {res.get('referring_domains')} website trỏ về, "
        f"{res.get('backlinks')} backlink ({R.usd(cost, 3)} USD).")
    return True
