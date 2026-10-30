"""Chạy truy vấn GA4 Data API (runReport), kiểm tra tương thích, cache trong SQLite.

- Số trả về giữ nguyên nghĩa: rate là phân số 0–1, thời lượng là giây, đếm là số nguyên. Trường GA4 không trả về thì
  là None (không có số), không bao giờ tự đổi thành 0.
- Cache key gồm property, toàn bộ body truy vấn và phiên bản phân loại/schema, nên đổi bộ lọc hay đổi cách phân loại
  là ra key khác.
"""
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from googleapiclient.errors import HttpError

from . import ai_classifier
from .gsc import _execute

QUERY_SCHEMA_VERSION = "q1"
RECENT_TTL_HOURS = 3   # khoảng ngày chạm 3 ngày gần nhất: GA4 còn cập nhật
CLOSED_TTL_HOURS = 24

CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ga4_cache (
    key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""

INT_METRICS = {"sessions", "engagedSessions", "keyEvents", "totalUsers", "activeUsers", "screenPageViews"}


@dataclass
class Report:
    rows: list[dict] = field(default_factory=list)  # {dimension: str, metric: số hoặc None}
    row_count: int = 0
    totals: dict | None = None
    thresholded: bool = False
    sampled: bool = False
    quota: dict = field(default_factory=dict)
    cached: bool = False
    queried_at: str = ""


def _num(name: str, value: str | None):
    if value is None or value == "":
        return None
    try:
        return int(float(value)) if name in INT_METRICS else float(value)
    except ValueError:
        return None


def parse(resp: dict) -> Report:
    dims = [h["name"] for h in resp.get("dimensionHeaders", [])]
    mets = [h["name"] for h in resp.get("metricHeaders", [])]

    def row(r):
        out = {d: v.get("value") for d, v in zip(dims, r.get("dimensionValues", []))}
        out.update({m: _num(m, v.get("value")) for m, v in zip(mets, r.get("metricValues", []))})
        return out

    meta = resp.get("metadata", {})
    totals = resp.get("totals")
    return Report(
        rows=[row(r) for r in resp.get("rows", [])], row_count=int(resp.get("rowCount", 0) or 0),
        totals=row(totals[0]) if totals else None,
        thresholded=bool(meta.get("subjectToThresholding")), sampled=bool(meta.get("samplingMetadatas")),
        quota=resp.get("propertyQuota", {}),
    )


class GA4Client:
    """Bọc GA4 Data API cho một property, có cache SQLite (con=None thì không cache)."""

    def __init__(self, data, prop: str, con: sqlite3.Connection | None = None, today: date | None = None):
        self.data, self.prop, self.con = data, prop, con
        self.today = today or date.today()
        if con is not None:
            con.executescript(CACHE_SCHEMA)

    def _key(self, body: dict) -> str:
        raw = json.dumps({"p": self.prop, "b": body, "c": ai_classifier.VERSION, "q": QUERY_SCHEMA_VERSION},
                         sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _ttl(self, body: dict) -> timedelta:
        last = max(date.fromisoformat(r["endDate"]) for r in body["dateRanges"])
        recent = last >= self.today - timedelta(days=3)
        return timedelta(hours=RECENT_TTL_HOURS if recent else CLOSED_TTL_HOURS)

    def run(self, dimensions: list[str], metrics: list[str], start: date, end: date, dim_filter: dict | None = None,
            order_by: str | None = None, limit: int = 10000, offset: int = 0, use_cache: bool = True) -> Report:
        body = {"dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
                "dimensions": [{"name": d} for d in dimensions], "metrics": [{"name": m} for m in metrics],
                "limit": limit, "offset": offset, "returnPropertyQuota": True, "keepEmptyRows": False}
        if dim_filter:
            body["dimensionFilter"] = dim_filter
        if order_by:
            body["orderBys"] = [{"metric": {"metricName": order_by}, "desc": True}]
        key = self._key(body)
        if use_cache and self.con is not None:
            row = self.con.execute("SELECT created_at, payload FROM ga4_cache WHERE key = ?", (key,)).fetchone()
            if row and datetime.now(timezone.utc) - datetime.fromisoformat(row[0]) < self._ttl(body):
                rep = parse(json.loads(row[1]))
                rep.cached, rep.queried_at = True, row[0]
                return rep
        resp = _execute(self.data.properties().runReport(property=self.prop, body=body))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if self.con is not None:
            with self.con:
                self.con.execute("INSERT OR REPLACE INTO ga4_cache VALUES (?, ?, ?)",
                                 (key, now, json.dumps(resp, ensure_ascii=False)))
        rep = parse(resp)
        rep.queried_at = now
        return rep

    def incompatible(self, dimensions: list[str], metrics: list[str], dim_filter: dict | None = None) -> list[str]:
        """Tên các trường GA4 báo không dùng chung được trong một truy vấn (rỗng = dùng được)."""
        body = {"dimensions": [{"name": d} for d in dimensions], "metrics": [{"name": m} for m in metrics],
                "compatibilityFilter": "INCOMPATIBLE"}
        if dim_filter:
            body["dimensionFilter"] = dim_filter
        resp = _execute(self.data.properties().checkCompatibility(property=self.prop, body=body))
        return [d["dimensionMetadata"]["apiName"] for d in resp.get("dimensionCompatibilities", [])] + \
               [m["metricMetadata"]["apiName"] for m in resp.get("metricCompatibilities", [])]

    def clear_cache(self) -> None:
        if self.con is not None:
            with self.con:
                self.con.execute("DELETE FROM ga4_cache")


def error_code(e: HttpError) -> str:
    """Mã chẩn đoán theo spec §7.3."""
    status = e.resp.status
    if status == 403:
        return "API_PERMISSION_DENIED"
    if status == 404:
        return "PROPERTY_NOT_FOUND"
    if status == 400 and "compatib" in str(e).lower():
        return "METRIC_INCOMPATIBLE"
    if status == 429:
        return "QUOTA_EXCEEDED"
    return "DATA_NOT_AVAILABLE"
