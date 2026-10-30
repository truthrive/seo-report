"""Check rank thực tế qua DataForSEO cho danh sách keyword theo dõi.

- Keyword đến từ hai nguồn: gắn ★ ở màn URL (keyword GSC của một URL) hoặc nhập tay ở màn Check rank. Mỗi keyword
  theo dõi một lần; URL mục tiêu là tùy chọn.
- Một lịch chung cho mọi keyword: các thứ trong tuần, một ngày trong tháng, hoặc chỉ khi bấm "Check ngay". Lỡ lịch
  (máy tắt) thì lần chạy sau check bù.
- Độ sâu: "auto" (lần đầu top 30; sau đó theo vị trí check lần trước: ≤ 8 → top 10, ≤ 18 → top 20, còn lại → top 30)
  hoặc cố định 10/20/30/50/100. Giá tính theo từng trang 10 kết quả. Không dùng position GSC: đó là số trung bình,
  không phải rank.
- Ngân sách tháng dùng chung: không cho thêm keyword nếu ước tính vượt 100%, cảnh báo ở 80%, không gửi task nếu tiền đã
  dùng trong tháng vượt ngân sách.
"""
import base64
import calendar
import json
import math
import re
import sqlite3
import time
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import urls as U
from .config import RankSettings

API = "https://api.dataforseo.com/v3/serp/google/organic"
ALERT_RATIO = 0.8
DEPTHS = ["auto", 10, 20, 30, 50, 100]
WEEKDAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
DEFAULT_SCHEDULE = {"type": "weekdays", "weekdays": [1], "day": 1, "depth": "auto"}  # thứ Ba, trước báo cáo thứ Năm

SCHEMA = """
CREATE TABLE IF NOT EXISTS rank_keywords (
    id INTEGER PRIMARY KEY,
    site TEXT NOT NULL,
    keyword TEXT NOT NULL,
    url_id INTEGER,
    source TEXT NOT NULL,
    added_by TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE (site, keyword)
);
CREATE TABLE IF NOT EXISTS rank_tasks (
    task_id TEXT PRIMARY KEY,
    keyword_id INTEGER NOT NULL,
    depth INTEGER NOT NULL,
    check_date TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    cost REAL NOT NULL,
    status TEXT NOT NULL
);
-- rank: vị trí tốt nhất của site; ranking_url: URL của site ở vị trí đó; target_rank: vị trí của URL mục tiêu.
CREATE TABLE IF NOT EXISTS rank_checks (
    keyword_id INTEGER NOT NULL,
    check_date TEXT NOT NULL,
    depth INTEGER NOT NULL,
    rank INTEGER,
    ranking_url TEXT,
    target_rank INTEGER,
    cost REAL NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (keyword_id, check_date)
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def usd(value: float, digits: int = 2) -> str:
    """Số tiền kiểu Việt Nam: 0,02."""
    return f"{value:.{digits}f}".replace(".", ",")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_tables(con: sqlite3.Connection) -> None:
    _migrate_stars(con)
    con.executescript(SCHEMA)


def _migrate_stars(con: sqlite3.Connection) -> None:
    """Bản trước lưu ★ theo (URL, query) trong rank_stars; chuyển sang rank_keywords. Chưa có lần check nào nên bỏ
    rank_tasks/rank_checks kiểu cũ."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'rank_stars'").fetchone():
        return
    old_checks = [c[1] for c in con.execute("PRAGMA table_info(rank_checks)")]
    with con:
        if "url_id" in old_checks:
            con.execute("DROP TABLE rank_checks")
            con.execute("DROP TABLE IF EXISTS rank_tasks")
        con.executescript(SCHEMA)
        con.execute("""INSERT OR IGNORE INTO rank_keywords (site, keyword, url_id, source, added_by, added_at)
                       SELECT u.site, s.query, s.url_id, 'gsc', s.starred_by, s.starred_at
                       FROM rank_stars s JOIN urls u ON u.id = s.url_id""")
        con.execute("DROP TABLE rank_stars")


# ---- Lịch và độ sâu ----

def get_schedule(con: sqlite3.Connection) -> dict:
    ensure_tables(con)
    row = con.execute("SELECT value FROM app_settings WHERE key = 'rank_schedule'").fetchone()
    return {**DEFAULT_SCHEDULE, **(json.loads(row[0]) if row else {})}


def set_schedule(con: sqlite3.Connection, site: str, schedule: dict, user: str) -> None:
    ensure_tables(con)
    with con:
        con.execute("INSERT OR REPLACE INTO app_settings VALUES ('rank_schedule', ?)", (json.dumps(schedule),))
        U.log_change(con, user, site, "Đổi lịch check rank", None, describe_schedule(schedule))


def describe_schedule(s: dict) -> str:
    depth = "độ sâu tự động" if s["depth"] == "auto" else f"top {s['depth']}"
    if s["type"] == "weekdays":
        days = ", ".join(WEEKDAYS[d] for d in sorted(s["weekdays"])) or "chưa chọn thứ nào"
        return f"Hằng tuần vào {days}; {depth}"
    if s["type"] == "monthly":
        return f"Hằng tháng vào ngày {s['day']}; {depth}"
    return f"Chỉ khi bấm Check ngay; {depth}"


def checks_per_month(s: dict) -> float:
    if s["type"] == "weekdays":
        return len(set(s["weekdays"])) * 30 / 7
    return 1.0 if s["type"] == "monthly" else 0.0


def last_scheduled_day(s: dict, today: date) -> date | None:
    """Ngày theo lịch gần nhất ≤ hôm nay; None nếu lịch chỉ chạy tay hoặc chưa chọn thứ."""
    if s["type"] == "weekdays":
        for back in range(7):
            d = today - timedelta(days=back)
            if d.weekday() in s["weekdays"]:
                return d
        return None
    if s["type"] == "monthly":
        y, m = today.year, today.month
        if today.day < min(s["day"], calendar.monthrange(y, m)[1]):
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        return date(y, m, min(s["day"], calendar.monthrange(y, m)[1]))
    return None


def _auto_depth(position: float | None) -> int:
    if position is None:
        return 30
    if position <= 8:
        return 10
    if position <= 18:
        return 20
    return 30


def depth_for(setting, last_rank: int | None, last_depth: int | None) -> int:
    """Chỉ dựa vào kết quả check thật lần trước, không dùng position GSC (là số trung bình, không phải rank)."""
    if setting != "auto":
        return int(setting)
    return _auto_depth(last_rank)  # lần đầu, hoặc lần trước không thấy trong độ sâu → top 30


# ---- Danh sách keyword ----

def keywords(con: sqlite3.Connection, site: str, end: date) -> list[dict]:
    """Mọi keyword theo dõi kèm lần check gần nhất, lần trước, vị trí tốt nhất và độ sâu dự kiến."""
    ensure_tables(con)
    sched = get_schedule(con)
    rows = con.execute(
        """SELECT k.id, k.keyword, k.url_id, u.url, k.source, k.added_by, k.added_at
           FROM rank_keywords k LEFT JOIN urls u ON u.id = k.url_id WHERE k.site = ? ORDER BY k.id""",
        (site,)).fetchall()
    out = []
    for kid, kw, url_id, url, source, by, at in rows:
        checks = con.execute(
            "SELECT check_date, rank, ranking_url, target_rank, depth FROM rank_checks WHERE keyword_id = ? "
            "ORDER BY check_date DESC LIMIT 2", (kid,)).fetchall()
        best = con.execute("SELECT MIN(rank) FROM rank_checks WHERE keyword_id = ?", (kid,)).fetchone()[0]
        last = checks[0] if checks else None
        prev = checks[1] if len(checks) > 1 else None
        out.append({
            "id": kid, "keyword": kw, "url_id": url_id, "target_url": url, "source": source, "added_by": by,
            "added_at": at, "best": best,
            "date": last[0] if last else None, "rank": last[1] if last else None,
            "ranking_url": last[2] if last else None, "target_rank": last[3] if last else None,
            "last_depth": last[4] if last else None, "prev": prev[1] if prev else None,
            "prev_depth": prev[4] if prev else None,
            "depth": depth_for(sched["depth"], last[1] if last else None, last[4] if last else None),
        })
    return out


def history(con: sqlite3.Connection, keyword_id: int) -> list[tuple[str, int | None, int]]:
    ensure_tables(con)
    return con.execute("SELECT check_date, rank, depth FROM rank_checks WHERE keyword_id = ? ORDER BY check_date",
                       (keyword_id,)).fetchall()


def _pages(depth: int) -> int:
    return math.ceil(depth / 10)


def spent_this_month(con: sqlite3.Connection, today: date | None = None) -> float:
    ensure_tables(con)
    today = today or date.today()
    month = today.strftime("%Y-%m")
    from . import volume  # chi phí lấy volume keyword tính chung ngân sách DataForSEO
    return con.execute("SELECT COALESCE(SUM(cost), 0) FROM rank_tasks WHERE substr(check_date, 1, 7) = ?",
                       (month,)).fetchone()[0] + volume.spent_this_month(con, today)


def estimate(con: sqlite3.Connection, s: RankSettings, schedule: dict, depths: list[int]) -> float:
    return sum(_pages(d) for d in depths) * s.price_per_page * checks_per_month(schedule)


def budget_status(con: sqlite3.Connection, site: str, s: RankSettings, end: date, today: date | None = None) -> dict:
    kws = keywords(con, site, end)
    est = estimate(con, s, get_schedule(con), [k["depth"] for k in kws])
    return {"stars": len(kws), "estimate": est, "spent": spent_this_month(con, today),
            "budget": s.monthly_budget_usd, "ratio": est / s.monthly_budget_usd if s.monthly_budget_usd else 0}


def parse_lines(text: str) -> list[tuple[str, str | None]]:
    """Mỗi dòng: keyword, hoặc keyword + URL mục tiêu (cách nhau bởi Tab khi dán từ Excel, hoặc dấu |)."""
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in re.split(r"\t|\|", line) if p.strip()]
        if not parts:
            continue
        kw = " ".join(parts[0].split()).lower()
        url = parts[1] if len(parts) > 1 else None
        if url is None and re.search(r"\s(https?://\S+|\S+\.\w{2,}/\S*)$", parts[0]):  # "keyword https://…"
            kw, url = parts[0].rsplit(None, 1)
            kw = " ".join(kw.split()).lower()
        out.append((kw, url))
    return out


def add_keywords(con: sqlite3.Connection, site: str, s: RankSettings, end: date, items: list[tuple[str, str | None]],
                 user: str, source: str = "manual") -> dict:
    """Thêm keyword (kèm URL mục tiêu nếu có). Từ chối phần vượt ngân sách."""
    ensure_tables(con)
    sched = get_schedule(con)
    current = keywords(con, site, end)
    depths = [k["depth"] for k in current]
    existing = {k["keyword"]: k for k in current}
    res = {"added": [], "updated": [], "exists": [], "over_budget": [], "bad_url": []}
    with con:
        for kw, raw_url in items:
            url_id = None
            if raw_url:
                url = U.normalize(raw_url)
                if url.split("//")[-1].split("/")[0].removeprefix("www.") != \
                        site.split("//")[-1].strip("/").removeprefix("www."):
                    res["bad_url"].append(f"{kw} | {raw_url}")
                    continue
                url_id = U._match_existing(con, site, url) or U._get_or_create_url(con, site, url)
            if kw in existing:
                if url_id and existing[kw]["url_id"] != url_id:
                    con.execute("UPDATE rank_keywords SET url_id = ? WHERE id = ?", (url_id, existing[kw]["id"]))
                    U.log_change(con, user, site, "Đổi URL mục tiêu", raw_url, kw)
                    res["updated"].append(kw)
                else:
                    res["exists"].append(kw)
                continue
            d = depth_for(sched["depth"], None, None)
            if estimate(con, s, sched, depths + [d]) > s.monthly_budget_usd:
                res["over_budget"].append(kw)
                continue
            con.execute("INSERT INTO rank_keywords (site, keyword, url_id, source, added_by, added_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (site, kw, url_id, source, user, _now()))
            U.log_change(con, user, site, "Thêm keyword check rank", raw_url, kw)
            depths.append(d)
            existing[kw] = {"id": None, "url_id": url_id}
            res["added"].append(kw)
    res["estimate"] = estimate(con, s, sched, depths)
    return res


def remove_keywords(con: sqlite3.Connection, site: str, ids: list[int], user: str) -> None:
    """Bỏ theo dõi; lịch sử rank vẫn giữ trong rank_checks."""
    with con:
        for kid in ids:
            kw = con.execute("SELECT keyword FROM rank_keywords WHERE id = ?", (kid,)).fetchone()
            con.execute("DELETE FROM rank_keywords WHERE id = ?", (kid,))
            U.log_change(con, user, site, "Bỏ keyword check rank", None, kw[0] if kw else "")


def toggle_star(con: sqlite3.Connection, site: str, s: RankSettings, end: date, url_id: int, query: str,
                user: str) -> tuple[bool, str]:
    """★ ở màn URL: thêm keyword GSC với URL này làm mục tiêu, hoặc bỏ nếu đã theo dõi."""
    ensure_tables(con)
    row = con.execute("SELECT id FROM rank_keywords WHERE site = ? AND keyword = ?", (site, query)).fetchone()
    if row:
        remove_keywords(con, site, [row[0]], user)
        return True, f"Đã bỏ theo dõi “{query}”"
    url, = con.execute("SELECT url FROM urls WHERE id = ?", (url_id,)).fetchone()
    r = add_keywords(con, site, s, end, [(query, url)], user, source="gsc")
    if r["over_budget"]:
        return False, (f"Không thêm được “{query}”: ước tính chi phí tháng sẽ vượt ngân sách "
                       f"{s.monthly_budget_usd:.0f} USD. Bỏ bớt keyword, giãn lịch check hoặc giảm độ sâu.")
    msg = f"Đã thêm “{query}” vào check rank; tổng ước tính {usd(r['estimate'])} USD/tháng"
    if r["estimate"] >= ALERT_RATIO * s.monthly_budget_usd:
        msg += f". Cảnh báo: đã dùng {r['estimate'] / s.monthly_budget_usd:.0%} ngân sách"
    return True, msg


def tracked_queries(con: sqlite3.Connection, site: str) -> set[str]:
    ensure_tables(con)
    return {r[0] for r in con.execute("SELECT keyword FROM rank_keywords WHERE site = ?", (site,))}


def latest_by_keyword(con: sqlite3.Connection, site: str) -> dict[str, dict]:
    return {k["keyword"]: k for k in keywords(con, site, date.today())}


# ---- Gọi DataForSEO ----

def load_credentials(path: Path) -> tuple[str, str] | None:
    if not path.exists():
        return None
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    login, password = raw.get("login", "").strip(), raw.get("password", "").strip()
    return (login, password) if login and password else None


class DataForSEO:
    def __init__(self, login: str, password: str, timeout: int = 60):
        token = base64.b64encode(f"{login}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
        self.timeout = timeout

    def _call(self, method: str, path: str, body=None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = Request(f"{API}/{path}", data=data, headers=self.headers, method=method)
        try:
            resp = json.loads(urlopen(req, timeout=self.timeout).read())
        except HTTPError as e:  # DataForSEO ghi lý do lỗi trong nội dung trả về, ví dụ 40104: tài khoản chưa xác minh
            try:
                resp = json.loads(e.read())
            except ValueError:
                raise RuntimeError(f"DataForSEO trả lỗi HTTP {e.code}") from e
        if resp.get("status_code") != 20000:
            raise RuntimeError(f"DataForSEO {resp.get('status_code')}: {resp.get('status_message')}")
        return resp

    def post(self, tasks: list[dict]) -> list[dict]:
        out = []
        for i in range(0, len(tasks), 100):
            out += self._call("POST", "task_post", tasks[i:i + 100])["tasks"]
        return out

    def ready_ids(self) -> set[str]:
        return {r["id"] for t in self._call("GET", "tasks_ready")["tasks"] or [] for r in t.get("result") or []}

    def get(self, task_id: str) -> dict:
        return self._call("GET", f"task_get/regular/{task_id}")["tasks"][0]

    def balance(self) -> float | None:
        req = Request("https://api.dataforseo.com/v3/appendix/user_data", headers=self.headers)
        resp = json.loads(urlopen(req, timeout=self.timeout).read())
        return resp["tasks"][0]["result"][0]["money"]["balance"]


def due(con: sqlite3.Connection, site: str, end: date, today: date) -> list[dict]:
    """Keyword cần check theo lịch: chưa có lần check (hoặc task đang chờ) từ ngày theo lịch gần nhất."""
    sched_day = last_scheduled_day(get_schedule(con), today)
    if sched_day is None:
        return []
    out = []
    for k in keywords(con, site, end):
        pending = con.execute("SELECT MAX(check_date) FROM rank_tasks WHERE keyword_id = ? AND status = 'posted'",
                              (k["id"],)).fetchone()[0]
        last = max(filter(None, [k["date"], pending]), default=None)
        if last is None or date.fromisoformat(last) < sched_day:
            out.append(k)
    return out


def post(con, site: str, s: RankSettings, client, todo: list[dict], today: date, log=print) -> int:
    if not todo:
        return 0
    batch_cost = sum(_pages(k["depth"]) for k in todo) * s.price_per_page
    spent = spent_this_month(con, today)
    if spent + batch_cost > s.monthly_budget_usd:
        log(f"Dừng check rank: đã dùng {usd(spent)} USD tháng này, lượt này cần {usd(batch_cost, 3)} USD, "
            f"vượt ngân sách {s.monthly_budget_usd:.0f} USD.")
        return 0
    tasks = [{"keyword": k["keyword"], "location_code": s.location_code, "language_code": s.language_code,
              "device": s.device, "depth": k["depth"], "tag": str(k["id"])} for k in todo]
    posted, errors = 0, {}
    with con:
        for k, t in zip(todo, client.post(tasks)):
            if t.get("status_code") != 20100:
                errors.setdefault(t.get("status_message") or str(t.get("status_code")), []).append(k["keyword"])
                continue
            con.execute("INSERT INTO rank_tasks VALUES (?, ?, ?, ?, ?, ?, 'posted')",
                        (t["id"], k["id"], k["depth"], today.isoformat(), _now(), t.get("cost", 0)))
            posted += 1
    for message, kws in errors.items():  # gộp: thường mọi keyword cùng một lỗi tài khoản
        log(f"Không gửi được {len(kws)} keyword ({', '.join(kws[:3])}{'…' if len(kws) > 3 else ''}): {message}")
    if posted:
        log(f"Đã gửi {posted} keyword để check rank, khoảng {usd(batch_cost, 3)} USD.")
    return posted


def parse_rank(task: dict, site: str, target_url: str | None) -> tuple[int | None, str | None, int | None]:
    """(rank tốt nhất của site, URL đang xếp hạng, rank của URL mục tiêu)."""
    host = site.split("//")[-1].strip("/").removeprefix("www.")
    items = (task.get("result") or [{}])[0].get("items") or []
    best, best_url, target_rank = None, None, None
    for it in items:
        if it.get("type") != "organic" or (it.get("domain") or "").removeprefix("www.") != host:
            continue
        url = U.normalize(it["url"])
        if best is None:
            best, best_url = it["rank_group"], url
        if target_url and target_rank is None and url == target_url:
            target_rank = it["rank_group"]
    return best, best_url, target_rank


def collect(con, site: str, client, log=print) -> int:
    pending = con.execute(
        "SELECT t.task_id, t.keyword_id, t.depth, t.check_date, t.cost, u.url FROM rank_tasks t "
        "JOIN rank_keywords k ON k.id = t.keyword_id LEFT JOIN urls u ON u.id = k.url_id "
        "WHERE t.status = 'posted' AND k.site = ?", (site,)).fetchall()
    if not pending:
        return 0
    ready = client.ready_ids()
    done = 0
    for task_id, kid, depth, check_date, cost, target in pending:
        if task_id not in ready:
            continue
        task = client.get(task_id)
        if task.get("status_code") != 20000:
            log(f"Lỗi kết quả task {task_id}: {task.get('status_message')}")
            continue
        rank, ranking_url, target_rank = parse_rank(task, site, target)
        with con:
            con.execute("INSERT OR REPLACE INTO rank_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (kid, check_date, depth, rank, ranking_url, target_rank, cost, _now()))
            con.execute("UPDATE rank_tasks SET status = 'done' WHERE task_id = ?", (task_id,))
        done += 1
    return done


def wait_and_collect(con, site: str, client, wait_minutes: int, log=print, sleep=time.sleep) -> None:
    deadline = time.monotonic() + wait_minutes * 60
    while con.execute("SELECT COUNT(*) FROM rank_tasks WHERE status = 'posted'").fetchone()[0]:
        got = collect(con, site, client, log)
        if got:
            log(f"Đã nhận kết quả {got} keyword.")
        if time.monotonic() > deadline:
            log("Còn keyword chưa có kết quả, lần chạy sau sẽ lấy tiếp.")
            break
        sleep(30)


def run(con, site: str, s: RankSettings, client, end: date, today: date | None = None, wait_minutes: int = 15,
        only_ids: list[int] | None = None, log=print, sleep=time.sleep) -> None:
    """Lấy kết quả còn tồn, gửi keyword đến hạn theo lịch (hoặc `only_ids` khi bấm Check ngay), rồi chờ kết quả."""
    ensure_tables(con)
    today = today or date.today()
    collect(con, site, client, log)
    if only_ids is not None:
        todo = [k for k in keywords(con, site, end) if k["id"] in set(only_ids)]
    else:
        todo = due(con, site, end, today)
    post(con, site, s, client, todo, today, log)
    wait_and_collect(con, site, client, wait_minutes, log, sleep)
