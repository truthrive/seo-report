"""Volume tìm kiếm của keyword SEO (keyword theo dõi rank) từ DataForSEO Keywords Data (Google Ads), Việt Nam.

Google Ads chỉ cập nhật volume theo tháng, nên mỗi keyword lấy một lần mỗi tháng (lịch hằng ngày tự lấy cho keyword
chưa có số của tháng này; keyword mới thêm thì lấy ngay). Chi phí thật do DataForSEO trả về được cộng vào ngân sách
check rank chung.
"""
import json
import sqlite3
from datetime import date, datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import rank as R

ENDPOINT = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
BATCH = 1000  # tối đa keyword mỗi lần gọi
EST_COST_PER_CALL = 0.075  # ước tính để chặn trước khi gọi; số trừ thật lấy từ phản hồi

SCHEMA = """
CREATE TABLE IF NOT EXISTS keyword_volume (
    keyword_id INTEGER NOT NULL,
    month TEXT NOT NULL,
    volume INTEGER,
    competition TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (keyword_id, month)
);
CREATE TABLE IF NOT EXISTS volume_runs (
    run_at TEXT NOT NULL,
    keywords INTEGER NOT NULL,
    cost REAL NOT NULL
);
"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def spent_this_month(con: sqlite3.Connection, today: date) -> float:
    ensure_tables(con)
    return con.execute("SELECT COALESCE(SUM(cost), 0) FROM volume_runs WHERE substr(run_at, 1, 7) = ?",
                       (today.strftime("%Y-%m"),)).fetchone()[0]


def latest(con: sqlite3.Connection) -> dict[int, dict]:
    """Volume mới nhất của từng keyword: {keyword_id: {volume, month, competition}}. volume None = Google Ads không có
    số (keyword quá ít tìm kiếm), khác với chưa lấy (không có trong dict)."""
    ensure_tables(con)
    out = {}
    for kid, month, vol, comp in con.execute(
            "SELECT keyword_id, month, volume, competition FROM keyword_volume ORDER BY keyword_id, month"):
        out[kid] = {"volume": vol, "month": month, "competition": comp}
    return out


def missing(con: sqlite3.Connection, site: str, end: date, today: date, only_ids: list[int] | None = None) -> list[dict]:
    """Keyword đang theo dõi chưa có volume của tháng này."""
    ensure_tables(con)
    month = today.strftime("%Y-%m")
    have = {r[0] for r in con.execute("SELECT keyword_id FROM keyword_volume WHERE month = ?", (month,))}
    return [k for k in R.keywords(con, site, end)
            if k["id"] not in have and (only_ids is None or k["id"] in only_ids)]


def fetch(login: str, password: str, keywords: list[str], location: int, language: str, timeout: int = 120) -> dict:
    import base64
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    body = [{"keywords": keywords, "location_code": location, "language_code": language}]
    req = Request(ENDPOINT, data=json.dumps(body).encode(), method="POST",
                  headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"})
    try:
        resp = json.loads(urlopen(req, timeout=timeout).read())
    except HTTPError as e:
        try:
            resp = json.loads(e.read())
        except ValueError:
            raise RuntimeError(f"DataForSEO trả lỗi HTTP {e.code}") from e
    if resp.get("status_code") != 20000:
        raise RuntimeError(f"DataForSEO {resp.get('status_code')}: {resp.get('status_message')}")
    task = resp["tasks"][0]
    if task.get("status_code") != 20000:
        raise RuntimeError(f"DataForSEO {task.get('status_code')}: {task.get('status_message')}")
    return {"cost": task.get("cost") or resp.get("cost") or 0, "result": task.get("result") or []}


def save(con: sqlite3.Connection, todo: list[dict], result: dict, today: date) -> int:
    """Lưu kết quả; keyword Google Ads không trả về thì lưu volume None để không hỏi lại trong tháng."""
    month = today.strftime("%Y-%m")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    by_kw = {(r.get("keyword") or "").strip().lower(): r for r in result["result"]}
    with con:
        for k in todo:
            r = by_kw.get(k["keyword"].strip().lower())
            con.execute("INSERT OR REPLACE INTO keyword_volume VALUES (?, ?, ?, ?, ?)",
                        (k["id"], month, r.get("search_volume") if r else None, r.get("competition") if r else None,
                         now))
        con.execute("INSERT INTO volume_runs VALUES (?, ?, ?)", (now, len(todo), float(result["cost"])))
    return len(todo)


def refresh(con: sqlite3.Connection, site: str, cfg, end: date, today: date | None = None,
            only_ids: list[int] | None = None, log=print, fetcher=fetch) -> int:
    """Lấy volume cho keyword chưa có số tháng này (hoặc chỉ `only_ids`). Trả về số keyword đã lưu."""
    today = today or date.today()
    todo = missing(con, site, end, today, only_ids)
    if not todo:
        return 0
    creds = R.load_credentials(cfg.dataforseo_secret)
    if not creds:
        log(f"Chưa có API key DataForSEO trong {cfg.dataforseo_secret}: bỏ qua lấy volume.")
        return 0
    calls = (len(todo) + BATCH - 1) // BATCH
    spent = R.spent_this_month(con, today)
    if spent + calls * EST_COST_PER_CALL > cfg.rank.monthly_budget_usd:
        log(f"Bỏ qua lấy volume: đã dùng {R.usd(spent)} USD, vượt ngân sách {cfg.rank.monthly_budget_usd:.0f} USD.")
        return 0
    saved = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        res = fetcher(*creds, [k["keyword"] for k in chunk], cfg.rank.location_code, cfg.rank.language_code)
        saved += save(con, chunk, res, today)
    log(f"Đã lấy volume cho {saved} keyword.")
    return saved
