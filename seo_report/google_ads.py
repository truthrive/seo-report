"""Volume tìm kiếm từ Google Ads API (Keyword Planner), miễn phí: thay cho DataForSEO (cùng nguồn Google Ads, nhưng
DataForSEO tính khoảng 0,09 USD mỗi lần lấy).

Cần: developer token (tài khoản người quản lý, mục Trung tâm API, mức Basic trở lên: mức Test không có số thật), mã
tài khoản người quản lý và Customer ID của một tài khoản Google Ads (không cần chạy quảng cáo), ghi trong
secrets/google_ads.toml; tài khoản Google của tool cấp quyền Google Ads (python -m seo_report login).
"""
import json
import re
import tomllib
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API_VERSION = "v26"  # Google bỏ mỗi phiên bản sau khoảng 1 năm: báo lỗi "phiên bản" thì đổi api_version trong file
LANGUAGES = {"vi": 1040, "en": 1000}  # languageConstants của Google Ads
COMPETITION = {"LOW": "LOW", "MEDIUM": "MEDIUM", "HIGH": "HIGH"}
TEMPLATE = """# Google Ads API: lấy volume từ khóa miễn phí (thay DataForSEO). File này chứa mã bí mật: không gửi cho ai.
# developer_token: tài khoản người quản lý (MCC) > Quản trị > Trung tâm API. Cần mức Basic trở lên.
developer_token = ""
# Mã tài khoản người quản lý (MCC), dạng 123-456-7890, ở góc trên bên phải khi đứng trong tài khoản đó
login_customer_id = ""
# Customer ID của một tài khoản Google Ads nằm dưới tài khoản người quản lý (không cần chạy quảng cáo)
customer_id = ""
# api_version = "v26"
"""


def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def load_settings(path: Path) -> dict | None:
    """{developer_token, login_customer_id, customer_id, api_version}; chưa có file / chưa điền đủ thì None."""
    if not path.exists():
        return None
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    s = {"developer_token": str(raw.get("developer_token", "")).strip(),
         "login_customer_id": _digits(raw.get("login_customer_id")), "customer_id": _digits(raw.get("customer_id")),
         "api_version": str(raw.get("api_version") or API_VERSION).strip()}
    return s if s["developer_token"] and s["customer_id"] else None


def write_template(path: Path) -> bool:
    """Tạo file mẫu để người dùng tự điền (không ghi đè file đã có)."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    return True


def _error_text(body: dict, code: int) -> str:
    """Câu lỗi dễ hiểu từ phản hồi lỗi của Google Ads."""
    err = body.get("error") or {}
    reasons = []
    for d in err.get("details") or []:
        for e in d.get("errors") or []:
            reasons += [f"{k}={v}" for k, v in (e.get("errorCode") or {}).items()]
    text = " ".join(reasons) or err.get("message") or f"HTTP {code}"
    details = " ".join(e.get("message") or "" for d in err.get("details") or [] for e in d.get("errors") or [])
    if "explorer access" in details.lower():  # Explorer đọc được tài khoản thật nhưng không dùng được Keyword Planner
        return ("mức Explorer Access chưa dùng được Keyword Planner (lấy volume): cần xin mức Basic ở trang Google Ads "
                "API > Overview của dự án Google Cloud")
    if "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION" in text:  # từ v25: mức quyền theo dự án Google Cloud
        return ("dự án Google Cloud của tool mới có quyền tài khoản thử: vào Google Cloud Console > APIs & Services > "
                "Google Ads API > trang Overview, xin Explorer Access (hoặc Basic)")
    if "DEVELOPER_TOKEN_NOT_APPROVED" in text or "DEVELOPER_TOKEN_PROHIBITED" in text:
        return "developer token chưa được duyệt mức Basic (mức Test không lấy được số thật)"
    if "USER_PERMISSION_DENIED" in text or "CUSTOMER_NOT_FOUND" in text:
        return ("tài khoản Google của tool chưa có quyền vào Customer ID này, hoặc login_customer_id (mã tài khoản "
                "người quản lý) chưa đúng")
    if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in text or code == 403 and "scope" in text.lower():
        return "tài khoản Google chưa cấp quyền Google Ads: chạy python -m seo_report login"
    if code == 404:
        return f"phiên bản Google Ads API không còn: đổi api_version trong file cấu hình ({text})"
    return text


def historical_metrics(creds, settings: dict, keywords: list[str], location: int, language: str,
                       timeout: int = 120, opener=urlopen) -> dict:
    """Volume trung bình 12 tháng của từng keyword. Trả cùng dạng với volume.fetch (DataForSEO) để lưu chung:
    {"cost": 0, "result": [{"keyword", "search_volume", "competition"}]}. Google gộp các biến thể gần giống (có dấu /
    không dấu, số ít / số nhiều) thành một dòng: mọi biến thể trong closeVariants nhận cùng số."""
    if not creds.valid:
        from google.auth.transport.requests import Request as _Req
        creds.refresh(_Req())
    body = {"keywords": keywords, "geoTargetConstants": [f"geoTargetConstants/{int(location)}"],
            "keywordPlanNetwork": "GOOGLE_SEARCH"}
    if language in LANGUAGES:
        body["language"] = f"languageConstants/{LANGUAGES[language]}"
    headers = {"Authorization": f"Bearer {creds.token}", "developer-token": settings["developer_token"],
               "Content-Type": "application/json"}
    if settings.get("login_customer_id"):
        headers["login-customer-id"] = settings["login_customer_id"]
    url = (f"https://googleads.googleapis.com/{settings.get('api_version') or API_VERSION}/customers/"
           f"{settings['customer_id']}:generateKeywordHistoricalMetrics")
    try:
        resp = json.loads(opener(Request(url, data=json.dumps(body).encode(), headers=headers, method="POST"),
                                 timeout=timeout).read() or b"{}")
    except HTTPError as e:
        try:
            err = json.loads(e.read() or b"{}")
        except ValueError:
            err = {}
        raise RuntimeError(f"Google Ads: {_error_text(err, e.code)}") from e
    out = []
    for r in resp.get("results") or []:
        m = r.get("keywordMetrics") or {}
        vol = int(m["avgMonthlySearches"]) if m.get("avgMonthlySearches") not in (None, "") else None
        comp = COMPETITION.get(m.get("competition") or "")
        for text in [r.get("text")] + list(r.get("closeVariants") or []):
            if text:
                out.append({"keyword": text, "search_volume": vol, "competition": comp})
    return {"cost": 0.0, "result": out}


# ---- Keyword Planner đầy đủ: ý tưởng từ khóa, giá thầu, volume từng tháng ----

MONTHS = {m: i for i, m in enumerate(("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
                                       "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"), 1)}


def _call(creds, settings: dict, path: str, body: dict, timeout: int = 120, opener=urlopen) -> dict:
    """POST tới customers/{customer_id}{path}; lỗi thành RuntimeError có câu dễ hiểu."""
    if not creds.valid:
        from google.auth.transport.requests import Request as _Req
        creds.refresh(_Req())
    headers = {"Authorization": f"Bearer {creds.token}", "developer-token": settings["developer_token"],
               "Content-Type": "application/json"}
    if settings.get("login_customer_id"):
        headers["login-customer-id"] = settings["login_customer_id"]
    url = (f"https://googleads.googleapis.com/{settings.get('api_version') or API_VERSION}/customers/"
           f"{settings['customer_id']}{path}")
    try:
        return json.loads(opener(Request(url, data=json.dumps(body).encode(), headers=headers, method="POST"),
                                 timeout=timeout).read() or b"{}")
    except HTTPError as e:
        try:
            err = json.loads(e.read() or b"{}")
        except ValueError:
            err = {}
        raise RuntimeError(f"Google Ads: {_error_text(err, e.code)}") from e


def parse_metrics(m: dict) -> dict:
    """keywordMetrics / keywordIdeaMetrics → volume, cạnh tranh (LOW/MEDIUM/HIGH + chỉ số 0–100), giá thầu đầu trang
    thấp / cao (đơn vị tiền của tài khoản), volume 12 tháng [("2026-01", n), …] cũ trước."""
    def money(k):
        v = m.get(k)
        return round(int(v) / 1_000_000, 2) if v not in (None, "") else None
    monthly = []
    for x in m.get("monthlySearchVolumes") or []:
        mo = MONTHS.get(x.get("month"))
        if mo and x.get("year"):
            monthly.append((f"{int(x['year']):04d}-{mo:02d}", int(x.get("monthlySearches") or 0)))
    monthly.sort()
    vol = m.get("avgMonthlySearches")
    return {"volume": int(vol) if vol not in (None, "") else None,
            "competition": COMPETITION.get(m.get("competition") or ""),
            "competition_index": int(m["competitionIndex"]) if m.get("competitionIndex") not in (None, "") else None,
            "low_bid": money("lowTopOfPageBidMicros"), "high_bid": money("highTopOfPageBidMicros"),
            "monthly": monthly[-12:]}


def _geo_lang(location: int, language: str) -> dict:
    body = {"geoTargetConstants": [f"geoTargetConstants/{int(location)}"], "keywordPlanNetwork": "GOOGLE_SEARCH"}
    if language in LANGUAGES:
        body["language"] = f"languageConstants/{LANGUAGES[language]}"
    return body


def keyword_ideas(creds, settings: dict, location: int, language: str, keywords: list[str] = (),
                  url: str | None = None, site: str | None = None, limit: int = 1000, opener=urlopen) -> list[dict]:
    """Ý tưởng từ khóa của Keyword Planner từ từ khóa gốc (tối đa 20), một URL, từ khóa + URL, hoặc cả website
    (site: tên miền, ví dụ doi-thu.vn). Mỗi dòng: {"keyword", **parse_metrics}. Nhiều volume trước."""
    body = {**_geo_lang(location, language), "includeAdultKeywords": False, "pageSize": min(limit, 1000)}
    kws = [k.strip() for k in keywords if k and k.strip()][:20]
    if site:
        body["siteSeed"] = {"site": site}
    elif kws and url:
        body["keywordAndUrlSeed"] = {"url": url, "keywords": kws}
    elif url:
        body["urlSeed"] = {"url": url}
    elif kws:
        body["keywordSeed"] = {"keywords": kws}
    else:
        raise ValueError("Cần ít nhất một từ khóa, URL hoặc website")
    out: list[dict] = []
    while True:
        resp = _call(creds, settings, ":generateKeywordIdeas", body, opener=opener)
        for r in resp.get("results") or []:
            if r.get("text"):
                out.append({"keyword": r["text"], **parse_metrics(r.get("keywordIdeaMetrics") or {})})
        token = resp.get("nextPageToken")
        if not token or len(out) >= limit:
            break
        body["pageToken"] = token
    out.sort(key=lambda r: -(r["volume"] or 0))
    return out[:limit]


def metrics(creds, settings: dict, keywords: list[str], location: int, language: str, opener=urlopen) -> list[dict]:
    """Số đầy đủ (volume, giá thầu, 12 tháng) của các từ khóa có sẵn (tối đa 10.000 / lần). Biến thể gần giống
    (closeVariants) nhận cùng số."""
    resp = _call(creds, settings, ":generateKeywordHistoricalMetrics",
                 {**_geo_lang(location, language), "keywords": list(keywords)}, opener=opener)
    out = []
    for r in resp.get("results") or []:
        m = parse_metrics(r.get("keywordMetrics") or {})
        for text in [r.get("text")] + list(r.get("closeVariants") or []):
            if text:
                out.append({"keyword": text, **m})
    return out


def currency(creds, settings: dict, opener=urlopen) -> str:
    """Đơn vị tiền của tài khoản Google Ads (giá thầu tính theo đơn vị này), ví dụ VND."""
    resp = _call(creds, settings, "/googleAds:search", {"query": "SELECT customer.currency_code FROM customer"},
                 timeout=30, opener=opener)
    rows = resp.get("results") or []
    return ((rows[0].get("customer") or {}).get("currencyCode") if rows else None) or "VND"
