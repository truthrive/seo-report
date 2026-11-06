"""Local SEO: Google Business Profile (hồ sơ GMB) của dự án, qua các API chính thức của Google (miễn phí, cần
Google duyệt quyền dùng API và quyền business.manage khi đăng nhập Google).

- Mỗi dự án gắn một hoặc nhiều hồ sơ (chi nhánh) mà tài khoản Google của tool quản lý (`gbp_locations.linked`).
- Hiệu suất theo ngày (`gbp_daily`): lượt xem trên Search / Maps (máy tính, điện thoại), cuộc gọi, chỉ đường, click
  website, tin nhắn, đặt chỗ. Google trả chậm vài ngày; lấy nối tiếp từ ngày cuối đã có (lần đầu 18 tháng).
- Từ khóa tìm thấy hồ sơ theo tháng (`gbp_keywords`): mỗi tháng đã hết lấy một lần. Từ khóa ít lượt Google chỉ cho
  ngưỡng ("dưới 15") thay vì số.
- Kiểm tra hồ sơ (`audit`): thông tin còn thiếu / sai, đọc từ dữ liệu hồ sơ đã lưu.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS gbp_locations (
    name TEXT PRIMARY KEY,         -- locations/123…
    account TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '{}',  -- JSON hồ sơ (Business Information API)
    linked INTEGER NOT NULL DEFAULT 0,  -- 1: gắn vào dự án này
    added_by TEXT,
    added_at TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS gbp_daily (
    location TEXT NOT NULL,
    day TEXT NOT NULL,
    metric TEXT NOT NULL,
    value INTEGER NOT NULL,
    PRIMARY KEY (location, day, metric)
);
CREATE TABLE IF NOT EXISTS gbp_keywords (
    location TEXT NOT NULL,
    month TEXT NOT NULL,           -- YYYY-MM
    keyword TEXT NOT NULL,
    value INTEGER,                 -- số lượt; NULL khi Google chỉ cho ngưỡng
    threshold INTEGER,             -- "dưới N"
    PRIMARY KEY (location, month, keyword)
);
CREATE TABLE IF NOT EXISTS gbp_months (   -- tháng đã lấy từ khóa (kể cả tháng không có từ khóa nào)
    location TEXT NOT NULL,
    month TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (location, month)
);
"""

METRICS = {  # mã của Google → tên trên tool
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": "Xem trên Google Search · điện thoại",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": "Xem trên Google Search · máy tính",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS": "Xem trên Google Maps · điện thoại",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": "Xem trên Google Maps · máy tính",
    "CALL_CLICKS": "Cuộc gọi",
    "BUSINESS_DIRECTION_REQUESTS": "Chỉ đường",
    "WEBSITE_CLICKS": "Click website",
    "BUSINESS_CONVERSATIONS": "Tin nhắn",
    "BUSINESS_BOOKINGS": "Đặt chỗ",
}
VIEWS = [m for m in METRICS if m.startswith("BUSINESS_IMPRESSIONS")]
ACTIONS = ["CALL_CLICKS", "BUSINESS_DIRECTION_REQUESTS", "WEBSITE_CLICKS", "BUSINESS_CONVERSATIONS",
           "BUSINESS_BOOKINGS"]
FIRST_DAYS = 540            # lần đầu: khoảng 18 tháng (giới hạn của Google)
OVERLAP_DAYS = 7            # lấy lại vài ngày cuối (Google còn cập nhật số mấy ngày gần nhất)
KEYWORD_MONTHS = 12
READ_MASK = ("name,title,storeCode,categories,profile,phoneNumbers,websiteUri,regularHours,specialHours,"
             "storefrontAddress,serviceArea,openInfo,metadata,labels,latlng")


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- Google API

class Client:
    """Gọi các API Business Profile bằng token Google của tool (cần quyền business.manage)."""

    def __init__(self, creds):
        from . import auth
        self.acc = auth.build_gbp(creds, "mybusinessaccountmanagement")
        self.info = auth.build_gbp(creds, "mybusinessbusinessinformation")
        self.perf = auth.build_gbp(creds, "businessprofileperformance")

    def accounts(self) -> list[dict]:
        out, token = [], None
        while True:
            r = self.acc.accounts().list(pageSize=20, pageToken=token).execute()
            out += r.get("accounts", [])
            token = r.get("nextPageToken")
            if not token:
                return out

    def locations(self, account: str) -> list[dict]:
        out, token = [], None
        while True:
            r = self.info.accounts().locations().list(parent=account, readMask=READ_MASK, pageSize=100,
                                                      pageToken=token).execute()
            out += r.get("locations", [])
            token = r.get("nextPageToken")
            if not token:
                return out

    def location(self, name: str) -> dict:
        return self.info.locations().get(name=name, readMask=READ_MASK).execute()

    def daily(self, name: str, start: date, end: date) -> dict:
        return self.perf.locations().fetchMultiDailyMetricsTimeSeries(
            location=name, dailyMetrics=list(METRICS),
            dailyRange_startDate_year=start.year, dailyRange_startDate_month=start.month,
            dailyRange_startDate_day=start.day, dailyRange_endDate_year=end.year,
            dailyRange_endDate_month=end.month, dailyRange_endDate_day=end.day).execute()

    def keywords(self, name: str, year: int, month: int) -> list[dict]:
        out, token = [], None
        while True:
            r = self.perf.locations().searchkeywords().impressions().monthly().list(
                parent=name, monthlyRange_startMonth_year=year, monthlyRange_startMonth_month=month,
                monthlyRange_endMonth_year=year, monthlyRange_endMonth_month=month, pageSize=100,
                pageToken=token).execute()
            out += r.get("searchKeywordsCounts", [])
            token = r.get("nextPageToken")
            if not token:
                return out


APIS = {"mybusinessaccountmanagement": "My Business Account Management API",
        "mybusinessbusinessinformation": "My Business Business Information API",
        "businessprofileperformance": "Business Profile Performance API"}


def explain(e: Exception) -> str:
    """Lỗi Google → câu tiếng Việt kèm cách sửa (API chưa bật, chưa được duyệt quota, chưa có quyền)."""
    import re
    text = str(e)
    if "SERVICE_DISABLED" in text or "has not been used in project" in text:
        proj = (re.search(r"project[= ](\d+)", text) or [None, ""])[1]
        return ("Google Cloud project của tool chưa bật API Business Profile. Vào Google Cloud Console"
                + (f" (project {proj})" if proj else "") + " → APIs & Services → Library, bật đủ 3 API: "
                + ", ".join(APIS.values()) + ". Bật xong đợi vài phút rồi thử lại.")
    if "RATE_LIMIT_EXCEEDED" in text or "Quota exceeded" in text or "quota" in text.lower() and "0" in text:
        return ("Google chưa cấp quota cho Business Profile API (project chưa được duyệt hoặc quota đang là 0). "
                "Kiểm tra mục Quotas của các API Business Profile trong Google Cloud Console.")
    if "PERMISSION_DENIED" in text or "403" in text:
        return ("Tài khoản Google của tool không có quyền với hồ sơ này: thêm email tool làm người quản lý hồ sơ "
                "trong Google Business Profile.")
    return text[:300]


def all_locations(client) -> list[dict]:
    """Mọi hồ sơ tài khoản Google của tool quản lý: [{name, account, account_name, title, address, website}]."""
    out = []
    for a in client.accounts():
        for loc in client.locations(a["name"]):
            out.append({"name": loc["name"], "account": a["name"], "account_name": a.get("accountName", ""),
                        "title": loc.get("title", ""), "address": address_text(loc),
                        "website": loc.get("websiteUri", ""), "data": loc})
    return sorted(out, key=lambda x: x["title"].lower())


def address_text(loc: dict) -> str:
    a = loc.get("storefrontAddress") or {}
    parts = list(a.get("addressLines") or []) + [a.get("sublocality", ""), a.get("locality", ""),
                                                  a.get("administrativeArea", "")]
    return ", ".join(p for p in parts if p)


# ---------------------------------------------------------------- lưu / đọc

def link(con, locs: list[dict], user: str) -> None:
    """Gắn các hồ sơ vào dự án (giữ dữ liệu hồ sơ vừa đọc); hồ sơ đã gắn mà không còn trong danh sách thì bỏ gắn."""
    ensure_tables(con)
    keep = {x["name"] for x in locs}
    with con:
        for x in locs:
            con.execute("INSERT INTO gbp_locations (name, account, title, data, linked, added_by, added_at, fetched_at) "
                        "VALUES (?, ?, ?, ?, 1, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET account = excluded.account, "
                        "title = excluded.title, data = excluded.data, linked = 1, fetched_at = excluded.fetched_at",
                        (x["name"], x.get("account", ""), x.get("title", ""),
                         json.dumps(x.get("data") or {}, ensure_ascii=False), str(user), _now(), _now()))
        for (name,) in con.execute("SELECT name FROM gbp_locations WHERE linked = 1").fetchall():
            if name not in keep:
                con.execute("UPDATE gbp_locations SET linked = 0 WHERE name = ?", (name,))


def linked(con) -> list[dict]:
    ensure_tables(con)
    return [{"name": n, "account": a, "title": t, "data": json.loads(d or "{}"), "fetched_at": f}
            for n, a, t, d, f in con.execute("SELECT name, account, title, data, fetched_at FROM gbp_locations "
                                             "WHERE linked = 1 ORDER BY title")]


def save_daily(con, name: str, resp: dict) -> int:
    n = 0
    with con:
        for multi in resp.get("multiDailyMetricTimeSeries", []):
            for ts in multi.get("dailyMetricTimeSeries", []):
                metric = ts.get("dailyMetric")
                for dv in (ts.get("timeSeries") or {}).get("datedValues", []):
                    d = dv.get("date") or {}
                    if not d.get("year"):
                        continue
                    day = date(d["year"], d["month"], d["day"]).isoformat()
                    con.execute("INSERT OR REPLACE INTO gbp_daily VALUES (?, ?, ?, ?)",
                                (name, day, metric, int(dv.get("value") or 0)))
                    n += 1
    return n


def save_keywords(con, name: str, month: str, rows: list[dict]) -> int:
    with con:
        con.execute("DELETE FROM gbp_keywords WHERE location = ? AND month = ?", (name, month))
        for r in rows:
            v = r.get("insightsValue") or {}
            con.execute("INSERT OR REPLACE INTO gbp_keywords VALUES (?, ?, ?, ?, ?)",
                        (name, month, (r.get("searchKeyword") or "").strip().lower(),
                         int(v["value"]) if v.get("value") is not None else None,
                         int(v["threshold"]) if v.get("threshold") is not None else None))
        con.execute("INSERT OR REPLACE INTO gbp_months VALUES (?, ?, ?)", (name, month, _now()))
    return len(rows)


def _months_back(today: date, n: int) -> list[str]:
    """n tháng đã hết gần nhất (cũ → mới), dạng YYYY-MM."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        out.append(f"{y}-{m:02d}")
    return out[::-1]


def last_day(con, name: str | None = None) -> str | None:
    ensure_tables(con)
    q = "SELECT MAX(day) FROM gbp_daily" + (" WHERE location = ?" if name else "")
    return con.execute(q, (name,) if name else ()).fetchone()[0]


def refresh(con, cfg, today: date | None = None, client=None, log=print) -> dict:
    """Lấy số mới cho mọi hồ sơ đã gắn: hồ sơ (để kiểm tra), hiệu suất theo ngày nối tiếp, từ khóa các tháng chưa có.
    API miễn phí. Trả {"locations", "days", "months"}."""
    ensure_tables(con)
    today = today or date.today()
    locs = linked(con)
    if not locs:
        return {"locations": 0, "days": 0, "months": 0}
    if client is None:
        from . import auth
        client = Client(auth.get_credentials(cfg, need=(auth.BUSINESS_SCOPE,)))
    days = months = 0
    end = today - timedelta(days=1)
    for loc in locs:
        name = loc["name"]
        try:
            data = client.location(name)
            with con:
                con.execute("UPDATE gbp_locations SET data = ?, title = ?, fetched_at = ? WHERE name = ?",
                            (json.dumps(data, ensure_ascii=False), data.get("title", loc["title"]), _now(), name))
        except Exception as e:  # noqa: BLE001  (hồ sơ bị gỡ quyền…: vẫn lấy phần khác)
            log(f"Không đọc được hồ sơ {loc['title']}: {explain(e)}")
        last = last_day(con, name)
        start = (date.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)) if last else today - timedelta(days=FIRST_DAYS)
        try:
            days += save_daily(con, name, client.daily(name, start, end))
        except Exception as e:  # noqa: BLE001
            log(f"Không lấy được hiệu suất {loc['title']}: {explain(e)}")
        have = {m for (m,) in con.execute("SELECT month FROM gbp_months WHERE location = ?", (name,))}
        for month in _months_back(today, KEYWORD_MONTHS):
            if month in have:
                continue
            y, m = int(month[:4]), int(month[5:])
            try:
                save_keywords(con, name, month, client.keywords(name, y, m))
                months += 1
            except Exception as e:  # noqa: BLE001
                log(f"Không lấy được từ khóa {loc['title']} tháng {m}/{y}: {explain(e)}")
                break
    log(f"Đã lấy số Google Business Profile của {len(locs)} hồ sơ.")
    return {"locations": len(locs), "days": days, "months": months}


# ---------------------------------------------------------------- tính số cho trang

def totals(con, names: list[str], start: date, end: date) -> dict[str, int]:
    """Tổng từng chỉ số trong khoảng ngày (gồm "views" = cộng 4 loại lượt xem)."""
    ensure_tables(con)
    if not names:
        return {}
    marks = ",".join("?" * len(names))
    out = {m: 0 for m in METRICS}
    for metric, v in con.execute(f"SELECT metric, SUM(value) FROM gbp_daily WHERE location IN ({marks}) "
                                 "AND day BETWEEN ? AND ? GROUP BY metric", (*names, start.isoformat(), end.isoformat())):
        out[metric] = v or 0
    out["views"] = sum(out[m] for m in VIEWS)
    return out


def series(con, names: list[str], start: date, end: date, by: str = "week") -> list[dict]:
    """Chuỗi theo tuần (thứ Hai) hoặc tháng: [{"period", "views", <metric>: số}] (cũ → mới)."""
    ensure_tables(con)
    if not names:
        return []
    marks = ",".join("?" * len(names))
    buckets: dict[str, dict] = {}
    for day, metric, v in con.execute(f"SELECT day, metric, SUM(value) FROM gbp_daily WHERE location IN ({marks}) "
                                      "AND day BETWEEN ? AND ? GROUP BY day, metric",
                                      (*names, start.isoformat(), end.isoformat())):
        d = date.fromisoformat(day)
        key = (d - timedelta(days=d.weekday())).isoformat() if by == "week" else day[:7]
        b = buckets.setdefault(key, {"period": key, "views": 0, **{m: 0 for m in METRICS}})
        b[metric] += v or 0
        if metric in VIEWS:
            b["views"] += v or 0
    return [buckets[k] for k in sorted(buckets)]


def keyword_rows(con, names: list[str], months: list[str]) -> list[dict]:
    """Từ khóa trong các tháng chọn (cộng các chi nhánh), so với cùng số tháng liền trước.
    [{"keyword", "value", "below" (chỉ có ngưỡng), "prev", "prev_below"}] xếp theo lượt giảm dần."""
    ensure_tables(con)
    if not names or not months:
        return []
    first = date.fromisoformat(months[0] + "-01")
    prev_months = []
    y, m = first.year, first.month
    for _ in months:
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        prev_months.append(f"{y}-{m:02d}")

    def agg(ms):
        marks, mm = ",".join("?" * len(names)), ",".join("?" * len(ms))
        out: dict[str, list] = {}
        for kw, v, th in con.execute(f"SELECT keyword, value, threshold FROM gbp_keywords WHERE location IN ({marks}) "
                                     f"AND month IN ({mm})", (*names, *ms)):
            o = out.setdefault(kw, [0, 0])
            if v is not None:
                o[0] += v
            else:
                o[1] = max(o[1], th or 0)
        return out
    now, prev = agg(months), agg(prev_months)
    rows = []
    for kw, (v, th) in now.items():
        p = prev.get(kw)
        rows.append({"keyword": kw, "value": v, "below": th if not v else 0,
                     "prev": p[0] if p else None, "prev_below": (p[1] if p and not p[0] else 0) if p else 0})
    return sorted(rows, key=lambda r: (-(r["value"] or 0), -(r["below"] or 0), r["keyword"]))


def keyword_months(con, names: list[str]) -> list[str]:
    ensure_tables(con)
    if not names:
        return []
    marks = ",".join("?" * len(names))
    return [m for (m,) in con.execute(f"SELECT DISTINCT month FROM gbp_months WHERE location IN ({marks}) "
                                      "ORDER BY month", names)]


# ---------------------------------------------------------------- kiểm tra hồ sơ

def audit(loc: dict, site_url: str) -> list[dict]:
    """Các mục kiểm tra một hồ sơ: [{"key", "level" (high | medium | info | ok), "title", "detail"}], nặng trước."""
    from .projects import domain
    d = loc.get("data") or {}
    meta = d.get("metadata") or {}
    cats = d.get("categories") or {}
    desc = ((d.get("profile") or {}).get("description") or "").strip()
    phones = d.get("phoneNumbers") or {}
    site = (d.get("websiteUri") or "").strip()
    hours = (d.get("regularHours") or {}).get("periods") or []
    out = []

    def add(key, ok, level, title, good, bad):
        out.append({"key": key, "level": "ok" if ok else level, "title": title, "detail": good if ok else bad})
    status = (d.get("openInfo") or {}).get("status", "OPEN")
    add("open", status == "OPEN", "high", "Trạng thái hoạt động", "Đang mở cửa.",
        "Hồ sơ đang ở trạng thái " + {"CLOSED_TEMPORARILY": "tạm đóng cửa", "CLOSED_PERMANENTLY": "đóng cửa vĩnh viễn"}
        .get(status, status) + ": khách thấy là không hoạt động.")
    add("verified", bool(meta.get("hasVoiceOfMerchant")), "high", "Xác minh / quyền quản lý",
        "Hồ sơ đã xác minh, chủ hồ sơ kiểm soát thông tin.",
        "Hồ sơ chưa xác minh hoặc đang bị tạm ngưng: thông tin có thể không hiện, Google có thể tự sửa. Xác minh lại "
        "trong Google Business Profile.")
    add("duplicate", not meta.get("duplicateLocation"), "medium", "Hồ sơ trùng", "Không thấy hồ sơ trùng.",
        "Google đánh dấu hồ sơ này trùng với một hồ sơ khác: gộp hoặc báo trùng để không chia lượt xem.")
    add("google_updated", not meta.get("hasGoogleUpdated"), "medium", "Google đã tự sửa thông tin",
        "Không có thay đổi chờ duyệt từ Google.",
        "Google đã tự cập nhật một số thông tin của hồ sơ: vào Google Business Profile xem lại và chấp nhận / sửa.")
    add("category", bool(cats.get("primaryCategory")), "high", "Danh mục chính",
        f"{(cats.get('primaryCategory') or {}).get('displayName', '')}.",
        "Chưa có danh mục chính: Google không biết hồ sơ thuộc ngành gì.")
    extra = len(cats.get("additionalCategories") or [])
    add("categories", extra >= 2, "medium", "Danh mục phụ", f"{extra} danh mục phụ.",
        f"Mới có {extra} danh mục phụ: thêm 2–4 danh mục sát dịch vụ để hiện ở nhiều lượt tìm hơn.")
    add("description", len(desc) >= 250, "medium", "Mô tả doanh nghiệp", f"{len(desc)} ký tự.",
        "Chưa có mô tả." if not desc else f"Mô tả mới {len(desc)} ký tự: nên viết 250–750 ký tự, nêu dịch vụ chính "
        "và khu vực.")
    add("phone", bool(phones.get("primaryPhone")), "high", "Số điện thoại", phones.get("primaryPhone", ""),
        "Chưa có số điện thoại: mất cuộc gọi từ hồ sơ.")
    want = domain(site_url) if site_url else ""
    if not site:
        add("website", False, "high", "Website", "", "Chưa gắn website: mất lượt click về site.")
    else:
        same = domain(site) == want or domain(site).endswith("." + want)
        add("website", same or not want, "high", "Website", site,
            f"Website của hồ sơ ({domain(site)}) không phải website dự án ({want}).")
    add("hours", bool(hours), "high", "Giờ mở cửa", f"Đã có giờ mở cửa ({len(hours)} khung giờ).",
        "Chưa có giờ mở cửa: Google có thể hiện “Có thể đã đóng cửa”, khách ngại ghé.")
    has_addr = bool((d.get("storefrontAddress") or {}).get("addressLines")) or bool(d.get("serviceArea"))
    add("address", has_addr, "high", "Địa chỉ / khu vực phục vụ", address_text(d) or "Có khu vực phục vụ.",
        "Chưa có địa chỉ cửa hàng hay khu vực phục vụ.")
    special = (d.get("specialHours") or {}).get("specialHourPeriods") or []
    add("special_hours", bool(special), "info", "Giờ ngày lễ", f"Đã khai {len(special)} ngày đặc biệt.",
        "Chưa khai giờ ngày lễ / ngày đặc biệt: nên thêm trước các dịp lễ.")
    order = {"high": 0, "medium": 1, "info": 2, "ok": 3}
    return sorted(out, key=lambda c: order[c["level"]])
