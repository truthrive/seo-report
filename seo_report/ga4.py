"""Kết nối GA4 (R0 của module AI Search & GEO): liệt kê property, đọc múi giờ, kiểm tra metadata và key events.

Truy vấn phân tích AI (R1 trở đi) dùng lại các client ở đây. Mọi lỗi trả về dạng dễ hiểu, không lộ token.
"""
from googleapiclient.errors import HttpError

from .gsc import _execute

# Trường spec AI Search & GEO cần (mục 4.1). Kiểm tra trên property thật trước khi dùng.
REQUIRED_DIMENSIONS = ["date", "sessionSource", "sessionMedium", "sessionDefaultChannelGroup", "landingPage",
                       "country"]
REQUIRED_METRICS = ["sessions", "engagedSessions", "engagementRate", "averageSessionDuration",
                    "userEngagementDuration", "keyEvents", "sessionKeyEventRate"]


def explain(e: HttpError) -> str:
    """Lỗi Google API → câu tiếng Việt kèm cách xử lý."""
    text = str(e)
    if "has not been used" in text or "is disabled" in text or "SERVICE_DISABLED" in text:
        api = "Google Analytics Admin API" if "analyticsadmin" in text else "Google Analytics Data API"
        return (f"{api} chưa được bật trong Google Cloud project. Vào https://console.cloud.google.com/apis/library, "
                f"tìm '{api}', bấm Enable, chờ 1–2 phút rồi chạy lại.")
    if e.resp.status == 403:
        return "Tài khoản đang đăng nhập không có quyền trên GA4 property này (cần ít nhất quyền Viewer)."
    if e.resp.status == 404:
        return "Không tìm thấy GA4 property. Kiểm tra ga4_property trong config.toml (dạng properties/123456789)."
    return f"Lỗi GA4 API {e.resp.status}: {text[:300]}"


def list_properties(admin) -> list[dict]:
    """Mọi GA4 property tài khoản truy cập được: [{property, name, account}]."""
    out, token = [], None
    while True:
        resp = _execute(admin.accountSummaries().list(pageSize=200, pageToken=token))
        for acc in resp.get("accountSummaries", []):
            for p in acc.get("propertySummaries", []):
                out.append({"property": p["property"], "name": p.get("displayName", ""),
                            "account": acc.get("displayName", "")})
        token = resp.get("nextPageToken")
        if not token:
            return out


def property_info(admin, prop: str) -> dict:
    p = _execute(admin.properties().get(name=prop))
    return {"name": p.get("displayName"), "timezone": p.get("timeZone"), "currency": p.get("currencyCode")}


def key_events(admin, prop: str) -> list[str]:
    resp = _execute(admin.properties().keyEvents().list(parent=prop, pageSize=200))
    return [k["eventName"] for k in resp.get("keyEvents", [])]


def metadata_check(data, prop: str) -> dict:
    """Trường nào spec cần mà property không hỗ trợ."""
    meta = _execute(data.properties().getMetadata(name=f"{prop}/metadata"))
    dims = {d["apiName"] for d in meta.get("dimensions", [])}
    mets = {m["apiName"] for m in meta.get("metrics", [])}
    return {"missing_dimensions": [d for d in REQUIRED_DIMENSIONS if d not in dims],
            "missing_metrics": [m for m in REQUIRED_METRICS if m not in mets]}


def channel_overview(data, prop: str, start: str, end: str) -> tuple[list[tuple[str, int]], dict]:
    """Sessions theo kênh mặc định (để xác nhận tên kênh AI thật của property) và quota còn lại."""
    body = {"dateRanges": [{"startDate": start, "endDate": end}],
            "dimensions": [{"name": "sessionDefaultChannelGroup"}], "metrics": [{"name": "sessions"}],
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}], "returnPropertyQuota": True}
    resp = _execute(data.properties().runReport(property=prop, body=body))
    rows = [(r["dimensionValues"][0]["value"], int(r["metricValues"][0]["value"])) for r in resp.get("rows", [])]
    return rows, resp.get("propertyQuota", {})
