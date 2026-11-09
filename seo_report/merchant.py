"""Google Merchant Center của dự án, qua Merchant API (merchantapi.googleapis.com, miễn phí, quyền
https://www.googleapis.com/auth/content khi đăng nhập Google; không cần Google duyệt như Business Profile).

- Mỗi dự án gắn một tài khoản Merchant Center (`merchant_account`).
- Sản phẩm (`merchant_products`): trạng thái hiển thị (đủ điều kiện / hạn chế / bị từ chối / đang xét), vấn đề của
  từng sản phẩm, thuộc tính chính (thương hiệu, GTIN, giá, tình trạng hàng). Ghi đè mỗi lần lấy.
- Hiệu suất (`merchant_perf`): click / lượt hiển thị theo ngày, từng sản phẩm, tách hiển thị miễn phí (ORGANIC) và
  quảng cáo (ADS). Lấy lại 90 ngày gần nhất mỗi lần (Google còn cập nhật vài ngày cuối).
- Vấn đề tài khoản (`merchant_account_issues`).
- Kiểm tra (`audit`): gom vấn đề tài khoản, sản phẩm bị từ chối / hạn chế, vấn đề theo thuộc tính, thiếu thuộc tính,
  sắp hết hạn, không có lượt hiển thị.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

BASE = "https://merchantapi.googleapis.com"
PERF_DAYS = 90

SCHEMA = """
CREATE TABLE IF NOT EXISTS merchant_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    account TEXT NOT NULL,          -- accounts/123
    name TEXT NOT NULL DEFAULT '',
    home TEXT NOT NULL DEFAULT '',
    linked_by TEXT,
    linked_at TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS merchant_products (
    id TEXT PRIMARY KEY,            -- channel~language~feedLabel~offerId
    offer_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    brand TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    availability TEXT NOT NULL DEFAULT '',
    condition TEXT NOT NULL DEFAULT '',
    price REAL,
    currency TEXT NOT NULL DEFAULT '',
    gtin TEXT NOT NULL DEFAULT '',
    thumbnail TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    click_potential TEXT NOT NULL DEFAULT '',
    expires TEXT,
    issues TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS merchant_perf (
    day TEXT NOT NULL,
    offer_id TEXT NOT NULL,
    method TEXT NOT NULL,           -- ORGANIC (miễn phí) | ADS | …
    title TEXT NOT NULL DEFAULT '',
    clicks INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    PRIMARY KEY (day, offer_id, method)
);
CREATE TABLE IF NOT EXISTS merchant_account_issues (
    name TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    severity TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    uri TEXT NOT NULL DEFAULT ''
);
"""

STATUS = {  # aggregatedReportingContextStatus → (tên, tông màu)
    "ELIGIBLE": ("Đủ điều kiện", "green"),
    "ELIGIBLE_LIMITED": ("Hạn chế", "amber"),
    "NOT_ELIGIBLE_OR_DISAPPROVED": ("Bị từ chối", "red"),
    "PENDING": ("Đang xét", "blue"),
}
SEVERITY = {"DISAPPROVED": "Bị từ chối", "DEMOTED": "Giảm hiển thị", "PENDING": "Đang xét"}
ATTRS = {  # thuộc tính sản phẩm (canonicalAttribute) → tên dễ hiểu
    "gtin": "Mã GTIN (mã vạch)", "brand": "Thương hiệu", "mpn": "Mã MPN", "image_link": "Ảnh chính",
    "additional_image_link": "Ảnh phụ", "price": "Giá", "sale_price": "Giá khuyến mãi", "availability": "Tình trạng hàng",
    "title": "Tên sản phẩm", "description": "Mô tả", "link": "Đường dẫn trang sản phẩm", "mobile_link": "Đường dẫn di động",
    "shipping": "Phí vận chuyển", "shipping_weight": "Khối lượng giao hàng", "google_product_category": "Danh mục Google",
    "product_type": "Loại sản phẩm", "condition": "Tình trạng (mới / cũ)", "identifier_exists": "Mã nhận dạng",
    "item_group_id": "Nhóm biến thể", "color": "Màu", "size": "Kích cỡ", "gender": "Giới tính", "age_group": "Độ tuổi",
    "material": "Chất liệu", "tax": "Thuế", "n:landing_page": "Trang đích", "landing_page": "Trang đích",
}
AVAIL = {"IN_STOCK": "Còn hàng", "OUT_OF_STOCK": "Hết hàng", "PREORDER": "Đặt trước", "BACKORDER": "Chờ nhập hàng",
         "LIMITED_AVAILABILITY": "Còn ít"}
ACC_SEVERITY = {"CRITICAL": "high", "ERROR": "high", "SUGGESTION": "info"}


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- Google API

class Client:
    """Gọi Merchant API (REST) bằng token Google của tool (cần quyền content)."""

    def __init__(self, creds):
        from google.auth.transport.requests import AuthorizedSession
        self.s = AuthorizedSession(creds)

    def _get(self, path: str, **params) -> dict:
        r = self.s.get(f"{BASE}/{path}", params=params, timeout=60)
        _raise(r)
        return r.json()

    def accounts(self) -> list[dict]:
        out, token = [], None
        while True:
            r = self._get("accounts/v1/accounts", pageSize=250, **({"pageToken": token} if token else {}))
            out += r.get("accounts", [])
            token = r.get("nextPageToken")
            if not token:
                return out

    def register(self, account_id: str, email: str) -> dict:
        """Đăng ký Google Cloud project của tool với tài khoản Merchant Center (Merchant API bắt buộc, làm một lần).
        Người đăng nhập Google của tool phải là quản trị viên tài khoản; email nhận vai trò API_DEVELOPER (liên hệ
        về API, quyền rất hạn chế) hoặc được gửi lời mời nếu chưa là người dùng của tài khoản."""
        r = self.s.post(f"{BASE}/accounts/v1/accounts/{account_id}/developerRegistration:registerGcp",
                        json={"developerEmail": email}, timeout=60)
        _raise(r)
        return r.json()

    def account(self, account_id: str) -> dict:
        return self._get(f"accounts/v1/accounts/{account_id}")

    def account_issues(self, account: str) -> list[dict]:
        out, token = [], None
        while True:
            r = self._get(f"accounts/v1/{account}/issues", pageSize=100, languageCode="vi",
                          timeZone="Asia/Ho_Chi_Minh", **({"pageToken": token} if token else {}))
            out += r.get("accountIssues", [])
            token = r.get("nextPageToken")
            if not token:
                return out

    def search(self, account: str, query: str) -> list[dict]:
        out, token = [], None
        while True:
            body = {"query": query, "pageSize": 5000, **({"pageToken": token} if token else {})}
            r = self.s.post(f"{BASE}/reports/v1/{account}/reports:search", json=body, timeout=120)
            _raise(r)
            data = r.json()
            out += data.get("results", [])
            token = data.get("nextPageToken")
            if not token:
                return out


class ApiError(Exception):
    pass


def _raise(r) -> None:
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
            msg = f"{r.status_code} {err.get('status', '')}: {err.get('message', '')}"
        except ValueError:
            msg = f"{r.status_code}: {r.text[:300]}"
        raise ApiError(msg)


def needs_registration(e: Exception) -> bool:
    return "not registered with the merchant account" in str(e)


def explain(e: Exception) -> str:
    """Lỗi Google → câu tiếng Việt kèm cách sửa."""
    import re
    text = str(e)
    if "SERVICE_DISABLED" in text or "has not been used in project" in text:
        proj = (re.search(r"project[= ](\d+)", text) or [None, ""])[1]
        return ("Google Cloud project của tool chưa bật Merchant API. Vào Google Cloud Console"
                + (f" (project {proj})" if proj else "") + " → APIs & Services → Library, bật “Merchant API”, "
                "đợi vài phút rồi thử lại.")
    if "not registered with the merchant account" in text:
        return ("Google Cloud project của tool chưa đăng ký với tài khoản Merchant Center (Merchant API bắt buộc, làm "
                "một lần). Nhập ID tài khoản Merchant Center và email liên hệ rồi bấm “Đăng ký”; tài khoản Google "
                "của tool phải là quản trị viên của tài khoản Merchant Center đó.")
    if "PERMISSION_DENIED" in text or text.startswith("403"):
        return ("Tài khoản Google của tool không có quyền với tài khoản Merchant Center này: trong Merchant Center → "
                "Cài đặt → Người dùng, thêm email tool (quyền Tiêu chuẩn hoặc Quản trị).")
    if ("UNAUTHENTICATED" in text or text.startswith("401")) and "registered" not in text:
        return "Token Google hết hạn hoặc thiếu quyền Merchant Center: kết nối Google lại ở Cài đặt tích hợp."
    if "RESOURCE_EXHAUSTED" in text or text.startswith("429"):
        return "Merchant API đang hết lượt gọi trong ngày (quota). Thử lại sau."
    return text[:300]


PRODUCT_QUERY = ("SELECT id, offer_id, title, brand, availability, condition, gtin, price, thumbnail_link, channel, "
                 "click_potential, expiration_date, aggregated_reporting_context_status, item_issues FROM product_view")


def perf_query(start: date, end: date) -> str:
    return ("SELECT date, offer_id, title, marketing_method, clicks, impressions FROM product_performance_view "
            f"WHERE date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'")


# ---------------------------------------------------------------- lưu / đọc

def link(con, account: dict, user: str) -> None:
    """Gắn một tài khoản Merchant Center vào dự án; đổi tài khoản thì xóa số của tài khoản cũ."""
    ensure_tables(con)
    old = linked(con)
    with con:
        if old and old["account"] != account["name"]:
            for t in ("merchant_products", "merchant_perf", "merchant_account_issues"):
                con.execute(f"DELETE FROM {t}")
        con.execute("INSERT INTO merchant_account (id, account, name, home, linked_by, linked_at) VALUES "
                    "(1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET account = excluded.account, name = excluded.name, "
                    "home = excluded.home, linked_by = excluded.linked_by, linked_at = excluded.linked_at, "
                    "fetched_at = CASE WHEN merchant_account.account = excluded.account THEN merchant_account.fetched_at "
                    "END",
                    (account["name"], account.get("accountName", ""), account.get("homepageUri")
                     or account.get("homePageUri", ""), str(user), _now()))


def unlink(con) -> None:
    ensure_tables(con)
    with con:
        for t in ("merchant_account", "merchant_products", "merchant_perf", "merchant_account_issues"):
            con.execute(f"DELETE FROM {t}")


def linked(con) -> dict | None:
    ensure_tables(con)
    r = con.execute("SELECT account, name, home, fetched_at FROM merchant_account WHERE id = 1").fetchone()
    return {"account": r[0], "name": r[1], "home": r[2], "fetched_at": r[3]} if r else None


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def save_products(con, rows: list[dict]) -> int:
    with con:
        con.execute("DELETE FROM merchant_products")
        for row in rows:
            p = row.get("productView") or {}
            if not p.get("id"):
                continue
            price = p.get("price") or {}
            exp = p.get("expirationDate")
            if isinstance(exp, dict):  # Date {year, month, day}
                exp = f"{exp.get('year', 0):04d}-{exp.get('month', 0):02d}-{exp.get('day', 0):02d}" \
                    if exp.get("year") else None
            con.execute("INSERT OR REPLACE INTO merchant_products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (p["id"], p.get("offerId", ""), p.get("title", ""), p.get("brand", ""),
                         p.get("aggregatedReportingContextStatus", ""), p.get("availability", ""),
                         p.get("condition", ""),
                         _int(price.get("amountMicros")) / 1e6 if price.get("amountMicros") is not None else None,
                         price.get("currencyCode", ""), ",".join(p.get("gtin") or []), p.get("thumbnailLink", ""),
                         p.get("channel", ""), p.get("clickPotential", ""), (exp or "")[:10] or None,
                         json.dumps(p.get("itemIssues") or [], ensure_ascii=False)))
    return len(rows)


def save_perf(con, rows: list[dict], start: date, end: date) -> int:
    with con:
        con.execute("DELETE FROM merchant_perf WHERE day BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))
        for row in rows:
            p = row.get("productPerformanceView") or {}
            d = p.get("date")
            if isinstance(d, dict):
                d = f"{d.get('year', 0):04d}-{d.get('month', 0):02d}-{d.get('day', 0):02d}"
            if not d:
                continue
            con.execute("INSERT INTO merchant_perf VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(day, offer_id, method) DO "
                        "UPDATE SET clicks = clicks + excluded.clicks, impressions = impressions + excluded.impressions",
                        (d[:10], p.get("offerId", ""), p.get("marketingMethod", "") or "", p.get("title", ""),
                         _int(p.get("clicks")), _int(p.get("impressions"))))
    return len(rows)


def save_account_issues(con, issues: list[dict]) -> int:
    with con:
        con.execute("DELETE FROM merchant_account_issues")
        for i in issues:
            con.execute("INSERT OR REPLACE INTO merchant_account_issues VALUES (?, ?, ?, ?, ?)",
                        (i.get("name", ""), i.get("title", ""), i.get("severity", ""), i.get("detail", ""),
                         i.get("documentationUri", "")))
    return len(issues)


def refresh(con, cfg, today: date | None = None, client=None, log=print) -> dict:
    """Lấy lại sản phẩm, hiệu suất 90 ngày và vấn đề tài khoản của tài khoản đã gắn. Mỗi phần lỗi riêng không chặn
    phần khác. Trả {"products", "perf_rows", "issues"} (None ở phần lỗi); chưa gắn tài khoản thì {}."""
    ensure_tables(con)
    acc = linked(con)
    if not acc:
        return {}
    if client is None:
        from . import auth
        client = Client(auth.get_credentials(cfg, need=(auth.CONTENT_SCOPE,)))
    today = today or date.today()
    out: dict = {"products": None, "perf_rows": None, "issues": None}
    try:
        out["products"] = save_products(con, client.search(acc["account"], PRODUCT_QUERY))
    except Exception as e:  # noqa: BLE001
        log(f"Không lấy được sản phẩm Merchant Center: {explain(e)}")
    start, end = today - timedelta(days=PERF_DAYS), today - timedelta(days=1)
    try:
        out["perf_rows"] = save_perf(con, client.search(acc["account"], perf_query(start, end)), start, end)
    except Exception as e:  # noqa: BLE001
        log(f"Không lấy được hiệu suất Merchant Center: {explain(e)}")
    try:
        out["issues"] = save_account_issues(con, client.account_issues(acc["account"]))
    except Exception as e:  # noqa: BLE001
        log(f"Không lấy được vấn đề tài khoản Merchant Center: {explain(e)}")
    if any(v is not None for v in out.values()):
        with con:
            con.execute("UPDATE merchant_account SET fetched_at = ? WHERE id = 1", (_now(),))
    return out


def products(con) -> list[dict]:
    ensure_tables(con)
    cols = ["id", "offer_id", "title", "brand", "status", "availability", "condition", "price", "currency", "gtin",
            "thumbnail", "channel", "click_potential", "expires", "issues"]
    out = []
    for r in con.execute(f"SELECT {', '.join(cols)} FROM merchant_products ORDER BY title"):
        d = dict(zip(cols, r))
        d["issues"] = json.loads(d["issues"] or "[]")
        out.append(d)
    return out


def account_issues(con) -> list[dict]:
    ensure_tables(con)
    return [{"name": n, "title": t, "severity": s, "detail": d, "uri": u} for n, t, s, d, u in con.execute(
        "SELECT name, title, severity, detail, uri FROM merchant_account_issues "
        "ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'ERROR' THEN 1 ELSE 2 END, title")]


def last_day(con) -> str | None:
    ensure_tables(con)
    return con.execute("SELECT MAX(day) FROM merchant_perf").fetchone()[0]


def totals(con, start: date, end: date, method: str | None = "ORGANIC") -> dict:
    ensure_tables(con)
    q = "SELECT SUM(clicks), SUM(impressions) FROM merchant_perf WHERE day BETWEEN ? AND ?"
    args: list = [start.isoformat(), end.isoformat()]
    if method:
        q += " AND method = ?"
        args.append(method)
    c, i = con.execute(q, args).fetchone()
    return {"clicks": c or 0, "impressions": i or 0}


def series(con, start: date, end: date, method: str | None = "ORGANIC") -> list[dict]:
    """Theo tuần (thứ Hai), bỏ tuần đầu / cuối chưa đủ 7 ngày: [{"week", "clicks", "impressions"}]."""
    ensure_tables(con)
    q = "SELECT day, SUM(clicks), SUM(impressions) FROM merchant_perf WHERE day BETWEEN ? AND ?"
    args: list = [start.isoformat(), end.isoformat()]
    if method:
        q += " AND method = ?"
        args.append(method)
    b: dict[str, dict] = {}
    for day, c, i in con.execute(q + " GROUP BY day ORDER BY day", args):
        d = date.fromisoformat(day)
        k = (d - timedelta(days=d.weekday())).isoformat()
        x = b.setdefault(k, {"week": k, "clicks": 0, "impressions": 0, "days": 0})
        x["clicks"] += c or 0
        x["impressions"] += i or 0
        x["days"] += 1
    out = [b[k] for k in sorted(b)]
    while out and out[-1]["days"] < 7:
        out.pop()
    while out and out[0]["days"] < 7:
        out.pop(0)
    return out


def per_product(con, start: date, end: date, method: str | None = "ORGANIC") -> dict[str, dict]:
    """{offer_id: {"clicks", "impressions", "title"}} trong khoảng ngày."""
    ensure_tables(con)
    q = ("SELECT offer_id, MAX(title), SUM(clicks), SUM(impressions) FROM merchant_perf WHERE day BETWEEN ? AND ?")
    args: list = [start.isoformat(), end.isoformat()]
    if method:
        q += " AND method = ?"
        args.append(method)
    return {o: {"title": t, "clicks": c or 0, "impressions": i or 0}
            for o, t, c, i in con.execute(q + " GROUP BY offer_id", args)}


def methods(con) -> list[str]:
    ensure_tables(con)
    return [m for (m,) in con.execute("SELECT DISTINCT method FROM merchant_perf ORDER BY method")]


# ---------------------------------------------------------------- kiểm tra

def issue_key(i: dict) -> str:
    t = i.get("type") or {}
    return f"{t.get('code', '')}|{t.get('canonicalAttribute', '')}"


def issue_label(i: dict) -> str:
    t = i.get("type") or {}
    attr = t.get("canonicalAttribute", "")
    code = (t.get("code") or "").replace("_", " ").strip()
    name = ATTRS.get(attr, attr.replace("_", " ")) if attr else ""
    return f"{name}: {code}" if name and code else (name or code or "Vấn đề khác")


def issue_level(i: dict) -> str:
    sev = ((i.get("severity") or {}).get("aggregatedSeverity") or "")
    return "high" if sev == "DISAPPROVED" else "medium" if sev == "DEMOTED" else "info"


def audit(prods: list[dict], acc_issues: list[dict], perf: dict[str, dict] | None = None,
          today: date | None = None) -> list[dict]:
    """Danh sách mục kiểm tra, nặng trước: [{"key", "level" (high | medium | info), "title", "detail", "ids"
    (id sản phẩm liên quan, để lọc bảng), "attr"}]. Không có vấn đề gì thì trả []."""
    today = today or date.today()
    out: list[dict] = []
    for i in acc_issues:
        out.append({"key": "acc:" + i["name"], "level": ACC_SEVERITY.get(i["severity"], "medium"),
                    "title": f"Tài khoản: {i['title']}", "detail": i["detail"] or "Vấn đề ở cấp tài khoản Merchant "
                    "Center: ảnh hưởng tới mọi sản phẩm.", "ids": [], "uri": i.get("uri", "")})
    n = len(prods)
    if not n:
        return out
    dis = [p["id"] for p in prods if p["status"] == "NOT_ELIGIBLE_OR_DISAPPROVED"]
    lim = [p["id"] for p in prods if p["status"] == "ELIGIBLE_LIMITED"]
    pend = [p["id"] for p in prods if p["status"] == "PENDING"]
    if dis:
        out.append({"key": "st:dis", "level": "high", "title": f"{len(dis)} sản phẩm bị từ chối",
                    "detail": "Không hiện trên Google Shopping / hiển thị miễn phí. Sửa các vấn đề “Bị từ chối” bên "
                              "dưới rồi đợi Google xét lại.", "ids": dis})
    if lim:
        out.append({"key": "st:lim", "level": "medium", "title": f"{len(lim)} sản phẩm bị hạn chế hiển thị",
                    "detail": "Vẫn hiện nhưng ít hơn hoặc ở một số nơi. Thường do thiếu GTIN, thương hiệu, ảnh chưa "
                              "đạt.", "ids": lim})
    if pend:
        out.append({"key": "st:pend", "level": "info", "title": f"{len(pend)} sản phẩm đang chờ Google xét",
                    "detail": "Sản phẩm mới hoặc vừa sửa: thường xong trong 3 ngày.", "ids": pend})
    # vấn đề theo loại (mã + thuộc tính), nhiều sản phẩm trước
    groups: dict[str, dict] = {}
    for p in prods:
        for i in p["issues"]:
            if (i.get("resolution") or "") == "PENDING_PROCESSING":
                continue  # Google đang xử lý, chưa cần làm gì
            g = groups.setdefault(issue_key(i), {"issue": i, "ids": [], "level": issue_level(i)})
            g["ids"].append(p["id"])
            if issue_level(i) == "high":
                g["level"] = "high"
    order = {"high": 0, "medium": 1, "info": 2}
    for k, g in sorted(groups.items(), key=lambda kv: (order[kv[1]["level"]], -len(kv[1]["ids"]))):
        sev = (g["issue"].get("severity") or {}).get("aggregatedSeverity", "")
        out.append({"key": "is:" + k, "level": g["level"], "title": f"{issue_label(g['issue'])} · {len(g['ids'])} sản "
                    "phẩm", "detail": f"Google: {SEVERITY.get(sev, 'cảnh báo')}. Sửa trong nguồn dữ liệu sản phẩm (feed / "
                    "website) rồi đợi Google cập nhật.", "ids": sorted(set(g["ids"]))})
    # thuộc tính nên có
    no_brand = [p["id"] for p in prods if not p["brand"]]
    no_gtin = [p["id"] for p in prods if not p["gtin"]]
    if no_brand:
        out.append({"key": "at:brand", "level": "medium", "title": f"{len(no_brand)} sản phẩm thiếu thương hiệu",
                    "detail": "Thương hiệu giúp Google ghép đúng truy vấn có tên hãng (ví dụ “kính Rayban”).",
                    "ids": no_brand})
    if no_gtin:
        out.append({"key": "at:gtin", "level": "info", "title": f"{len(no_gtin)} sản phẩm không có GTIN",
                    "detail": "Hàng có mã vạch của hãng nên khai GTIN; hàng tự sản xuất không có mã thì khai "
                              "identifier_exists = no để không bị hạn chế.", "ids": no_gtin})
    oos = [p["id"] for p in prods if p["availability"] == "OUT_OF_STOCK"]
    if oos:
        out.append({"key": "at:oos", "level": "info", "title": f"{len(oos)} sản phẩm đang hết hàng",
                    "detail": "Hàng hết vẫn hiện nhưng khó có click; kiểm tra lại tồn kho trên website.", "ids": oos})
    soon = [p["id"] for p in prods if p["expires"] and date.fromisoformat(p["expires"]) <= today + timedelta(days=7)]
    if soon:
        out.append({"key": "at:exp", "level": "medium", "title": f"{len(soon)} sản phẩm sắp hết hạn trong 7 ngày",
                    "detail": "Sản phẩm không được cập nhật sẽ hết hạn sau 30 ngày và biến mất: kiểm tra lịch cập "
                              "nhật feed.", "ids": soon})
    if perf is not None:
        live = [p for p in prods if p["status"] in ("ELIGIBLE", "ELIGIBLE_LIMITED")]
        zero = [p["id"] for p in live if not (perf.get(p["offer_id"]) or {}).get("impressions")]
        if zero and len(zero) < len(live):
            out.append({"key": "pf:zero", "level": "info", "title": f"{len(zero)} sản phẩm không có lượt hiển thị "
                        "miễn phí trong 28 ngày", "detail": "Đủ điều kiện nhưng Google không cho hiện: xem lại tên, "
                        "ảnh, giá so với đối thủ.", "ids": zero})
    return out
