"""Gọi GSC Search Analytics API, tự lật trang và thử lại khi bị giới hạn tốc độ."""
import time

from googleapiclient.errors import HttpError

ROW_LIMIT = 25000
RETRY_STATUSES = {429, 500, 502, 503}


def _execute(request, retries: int = 5, sleep=time.sleep):
    for attempt in range(retries):
        try:
            return request.execute()
        except HttpError as e:
            if e.resp.status in RETRY_STATUSES and attempt < retries - 1:
                sleep(2 ** attempt * 2)
                continue
            raise


def query_day(service, site: str, day: str, dimensions: list[str], sleep=time.sleep) -> list[dict]:
    """Lấy toàn bộ dòng của một ngày cho các chiều đã chọn (page, hoặc page + query)."""
    rows: list[dict] = []
    start = 0
    while True:
        body = {
            "startDate": day,
            "endDate": day,
            "dimensions": dimensions,
            "type": "web",
            # "all" lấy cả dữ liệu mới chưa chốt; các ngày gần đây được lấy lại nên sẽ được cập nhật.
            "dataState": "all",
            "rowLimit": ROW_LIMIT,
            "startRow": start,
        }
        resp = _execute(service.searchanalytics().query(siteUrl=site, body=body), sleep=sleep)
        batch = resp.get("rows", [])
        rows.extend(batch)
        if len(batch) < ROW_LIMIT:
            return rows
        start += ROW_LIMIT


def query_site_totals(service, site: str, start: str, end: str, sleep=time.sleep) -> list[dict]:
    """Tổng theo property từng ngày (chỉ chiều date). Khác tổng cộng từ các dòng page: impression theo page đếm
    mỗi URL hiển thị một lần nên lớn hơn; số của GSC UI là số này."""
    body = {"startDate": start, "endDate": end, "dimensions": ["date"], "type": "web", "dataState": "all",
            "rowLimit": ROW_LIMIT, "startRow": 0}  # tối đa ~480 dòng (16 tháng), không cần lật trang
    return _execute(service.searchanalytics().query(siteUrl=site, body=body), sleep=sleep).get("rows", [])


def list_sites(service) -> list[dict]:
    return _execute(service.sites().list()).get("siteEntry", [])
