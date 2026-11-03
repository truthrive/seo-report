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
