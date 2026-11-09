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


def web_streams(admin, prop: str) -> list[dict]:
    """Luồng dữ liệu web của property: [{name, url, measurement_id}]."""
    resp = _execute(admin.properties().dataStreams().list(parent=prop, pageSize=50))
    return [{"name": s.get("displayName", ""), "url": (s.get("webStreamData") or {}).get("defaultUri", ""),
             "measurement_id": (s.get("webStreamData") or {}).get("measurementId", "")}
            for s in resp.get("dataStreams", []) if s.get("type", "WEB_DATA_STREAM") == "WEB_DATA_STREAM"]


def stream_check(site_url: str, streams: list[dict]) -> dict:
    """Property GA4 có đúng là của website dự án không, đối chiếu tên miền của các luồng dữ liệu web.
    {"status": ok | mixed | mismatch | no_stream, "domains": [tên miền các luồng], "message": câu tiếng Việt}.
    - mismatch: không luồng nào là website dự án → số GA4 là của website khác.
    - mixed: có luồng của website dự án nhưng kèm luồng website khác → số GA4 bị cộng lẫn.
    Tên miền con (www., m.) coi như cùng website."""
    from .projects import domain
    want = domain(site_url)
    doms = list(dict.fromkeys(domain(s["url"]) for s in streams if s.get("url")))

    def same(d: str) -> bool:
        return d == want or d.endswith("." + want) or want.endswith("." + d)
    mine = [d for d in doms if same(d)]
    others = [d for d in doms if not same(d)]
    if not doms:
        return {"status": "no_stream", "domains": [],
                "message": "Property GA4 này chưa có luồng dữ liệu web nào: sẽ không có số truy cập."}
    if not mine:
        return {"status": "mismatch", "domains": doms,
                "message": f"Property GA4 này thu số cho {', '.join(others)}, không phải {want}: số truy cập hiện "
                           "trên tool sẽ là của website khác."}
    if others:
        return {"status": "mixed", "domains": doms,
                "message": f"Property GA4 này có thêm luồng của {', '.join(others)}: số truy cập của {want} bị cộng "
                           "lẫn. Nên xóa luồng thừa trong Google Analytics."}
    return {"status": "ok", "domains": doms, "message": f"Đúng website {want}."}


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
