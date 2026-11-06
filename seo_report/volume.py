"""Volume tìm kiếm của keyword SEO (keyword theo dõi rank), số của Google Ads (Keyword Planner). Lấy thẳng từ Google
Ads API khi đã cấu hình (miễn phí, xem google_ads.py); chưa cấu hình hoặc lỗi thì qua DataForSEO Keywords Data.

Mỗi keyword chỉ lấy volume MỘT lần duy nhất: ngay khi thêm (cả lượt thêm đi chung một lần gọi), không lấy lại theo
tháng. Lượt chạy hằng ngày chỉ bù cho keyword chưa từng có số (lần thêm bị lỗi, keyword đến từ sheet). Cùng từ khóa đã
có số ở bộ khác thì chép sang, không gọi. Chi phí thật do DataForSEO trả về được cộng vào ngân sách check rank chung.
"""
import json
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import rank as R

ENDPOINT = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
BATCH = 1000  # tối đa keyword mỗi lần gọi DataForSEO
GA_BATCH = 10000  # tối đa keyword mỗi lần gọi Google Ads (Keyword Planner)
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
    """Keyword đang theo dõi chưa từng có volume (đã lấy một lần thì không lấy lại, kể cả sang tháng mới)."""
    ensure_tables(con)
    have = {r[0] for r in con.execute("SELECT DISTINCT keyword_id FROM keyword_volume")}
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


def _texts(rows: list[dict]) -> list[str]:
    """Từ khóa không trùng (một từ khóa ở hai bộ là hai dòng nhưng chỉ hỏi volume một lần)."""
    return list(dict.fromkeys(k["keyword"].strip().lower() for k in rows))


def _copy_known(con: sqlite3.Connection, todo: list[dict], today: date) -> list[dict]:
    """Dòng có cùng từ khóa với dòng khác đã có volume (bất kỳ tháng nào): chép số sang (giữ tháng đã lấy), trả các
    dòng còn phải hỏi."""
    known = {}
    for kw, month, vol, comp, at in con.execute(
            "SELECT lower(k.keyword), v.month, v.volume, v.competition, v.fetched_at FROM keyword_volume v "
            "JOIN rank_keywords k ON k.id = v.keyword_id ORDER BY v.month"):
        known[kw.strip()] = (month, vol, comp, at)  # tháng mới nhất ghi đè
    rest = []
    with con:
        for k in todo:
            hit = known.get(k["keyword"].strip().lower())
            if hit:
                con.execute("INSERT OR REPLACE INTO keyword_volume VALUES (?, ?, ?, ?, ?)", (k["id"], *hit))
            else:
                rest.append(k)
    return rest


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


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(site: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(site, threading.Lock())


def refresh(con: sqlite3.Connection, site: str, cfg, end: date, today: date | None = None,
            only_ids: list[int] | None = None, log=print, fetcher=fetch) -> int:
    """Lấy volume cho keyword chưa có số tháng này (hoặc chỉ `only_ids`). Trả về số keyword đã lưu.
    Hai lần lấy cùng lúc cho một website (ví dụ Lấy từ sheet và thêm keyword) chạy lần lượt; lần sau thấy keyword đã
    có số thì không gọi lại (trước đây cả hai cùng gọi và bị tính tiền hai lần)."""
    with _lock_for(site):
        return _refresh(con, site, cfg, end, today, only_ids, log, fetcher)


def _google_ads(cfg):
    """(creds, settings) khi dùng được Google Ads API để lấy volume (miễn phí); chưa cấu hình / chưa cấp quyền: None."""
    from . import auth
    from . import google_ads as GA
    settings = GA.load_settings(getattr(cfg, "google_ads_secret", Path("secrets/google_ads.toml")))
    if not settings:
        return None
    try:
        return auth.get_credentials(cfg, need=(auth.ADS_SCOPE,)), settings
    except (Exception, SystemExit):  # noqa: BLE001  (chưa cấp quyền Google Ads: dùng DataForSEO)
        return None


def _refresh(con, site, cfg, end, today, only_ids, log, fetcher) -> int:
    if getattr(cfg.rank, "paused", False):  # tạm ngưng check rank = ngưng mọi chi phí DataForSEO của website
        log("Tạm ngưng: không lấy volume keyword.")
        return 0
    today = today or date.today()
    todo = missing(con, site, end, today, only_ids)
    todo = _copy_known(con, todo, today)  # cùng từ khóa ở bộ khác đã có số tháng này: chép, không hỏi lại
    if not todo:
        return 0
    ads = _google_ads(cfg) if fetcher is fetch else None  # test truyền fetcher riêng: không gọi Google Ads
    if ads:
        from . import google_ads as GA
        saved = 0
        try:
            for i in range(0, len(todo), GA_BATCH):
                chunk = todo[i:i + GA_BATCH]
                res = GA.historical_metrics(*ads, _texts(chunk), cfg.rank.location_code, cfg.rank.language_code)
                saved += save(con, chunk, res, today)
            log(f"Đã lấy volume cho {saved} keyword (Google Ads, miễn phí).")
            return saved
        except Exception as e:  # noqa: BLE001
            log(f"Không lấy được volume từ Google Ads ({e}); dùng DataForSEO.")
            todo = missing(con, site, end, today, only_ids)
            if not todo:
                return saved
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
        res = fetcher(*creds, _texts(chunk), cfg.rank.location_code, cfg.rank.language_code)
        saved += save(con, chunk, res, today)
    log(f"Đã lấy volume cho {saved} keyword.")
    return saved
