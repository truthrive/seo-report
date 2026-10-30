"""Phân tích traffic AI từ GA4 (spec AI Search & GEO §5.3, §6): tổng quan, nguồn, xu hướng, trang đích, quốc gia,
key event. Mọi hàm trả về cùng một "phong bì" (period, filters, classification, data, status, warnings, sourceMeta).

Quy tắc không được vi phạm:
- KPI tổng và mọi rate lấy từ truy vấn tổng hợp GA4 (dimensions rỗng) với đúng bộ lọc; không cộng rate/average giữa
  các dòng nguồn. Đếm (sessions, key events) thì cộng được.
- Session key event rate dùng metric gốc `sessionKeyEventRate`; `keyEvents / sessions` chỉ hiện dưới tên
  "key events / 100 phiên".
- None = không có số (không có mẫu số, GA4 không trả, không tương thích); 0 chỉ khi GA4 trả đúng 0.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from googleapiclient.errors import HttpError

from . import ai_classifier as C
from .ga4_query import GA4Client, Report, error_code

KPI_METRICS = ["sessions", "engagedSessions", "engagementRate", "userEngagementDuration", "averageSessionDuration",
               "keyEvents", "sessionKeyEventRate"]
ROW_METRICS = ["sessions", "engagedSessions", "engagementRate", "keyEvents", "sessionKeyEventRate"]
ORGANIC = ("Organic Search", "Organic Social")


@dataclass
class Filters:
    source: str | None = None        # nguồn con: CHATGPT, GEMINI…
    country: str | None = None
    landing_page: str | None = None

    def expression(self) -> dict | None:
        exprs = []
        if self.country:
            exprs.append(C._f("country", stringFilter={"value": self.country, "matchType": "EXACT"}))
        if self.landing_page:
            exprs.append(C._f("landingPage", stringFilter={"value": self.landing_page, "matchType": "EXACT"}))
        return C.and_filters(*exprs)


def previous_period(start: date, end: date) -> tuple[date, date]:
    """Khoảng liền trước, cùng số ngày (tính cả hai đầu)."""
    n = (end - start).days + 1
    return start - timedelta(days=n), start - timedelta(days=1)


def change(now, prev) -> float | None:
    """% thay đổi; None khi kỳ trước bằng 0 hoặc không có số (NO_BASELINE), không bao giờ ±∞."""
    if now is None or prev in (None, 0):
        return None
    return (now - prev) / prev


def diff(now, prev) -> float | None:
    """Chênh lệch tuyệt đối (dùng cho rate: điểm phần trăm)."""
    return None if now is None or prev is None else now - prev


def kpi(rep: Report) -> dict:
    """Khối KPI từ một truy vấn tổng hợp. Không có dòng nào = GA4 xác nhận 0 phiên: đếm = 0, rate = None."""
    r = rep.rows[0] if rep.rows else {}
    sessions = r.get("sessions") or 0
    out = {
        "sessions": sessions,
        "engagedSessions": r.get("engagedSessions") or 0 if rep.rows else 0,
        "keyEvents": r.get("keyEvents") or 0 if rep.rows else 0,
        "engagementRate": r.get("engagementRate") if sessions else None,
        "sessionKeyEventRate": r.get("sessionKeyEventRate") if sessions else None,
        "userEngagementDuration": r.get("userEngagementDuration") if sessions else None,
        "averageSessionDuration": r.get("averageSessionDuration") if sessions else None,
    }
    ued = out["userEngagementDuration"]
    out["avgEngagementTimePerSession"] = ued / sessions if sessions and ued is not None else None
    out["keyEventsPer100Sessions"] = 100 * out["keyEvents"] / sessions if sessions else None
    return out


@dataclass
class AIAnalytics:
    client: GA4Client
    mode: str = C.HYBRID
    allow: C.Allowlist = field(default_factory=C.Allowlist)
    min_sample: int = 30
    today: date = field(default_factory=date.today)
    _reports: list = field(default_factory=list, init=False)
    _warnings: list = field(default_factory=list, init=False)

    # ---- tiện ích chung ----

    def _ai(self, filters: Filters, only: str | None = None) -> dict | None:
        return C.and_filters(C.ga4_filter(self.mode, self.allow, only or filters.source), filters.expression())

    def _run(self, *args, **kw) -> Report:
        rep = self.client.run(*args, **kw)
        self._reports.append(rep)
        return rep

    def _warn(self, code: str, message: str) -> None:
        if not any(w["code"] == code and w["message"] == message for w in self._warnings):
            self._warnings.append({"code": code, "message": message})

    def _envelope(self, start, end, compare, filters: Filters, data: dict, error: str | None = None) -> dict:
        if end >= self.today - timedelta(days=1):
            self._warn("INCOMPLETE_PERIOD", "Kỳ có ngày hôm qua/hôm nay: GA4 còn đang xử lý, số có thể tăng thêm.")
        if any(r.thresholded for r in self._reports):
            self._warn("GA4_THRESHOLDED", "GA4 áp dụng ngưỡng ẩn dữ liệu (thresholding): bảng chi tiết có thể thiếu dòng.")
        env = {
            "period": {"startDate": start.isoformat(), "endDate": end.isoformat()},
            "comparisonPeriod": {"startDate": compare[0].isoformat(), "endDate": compare[1].isoformat()}
            if compare else None,
            "filters": {"channel": C.AI_ASSISTANTS, "source": filters.source, "country": filters.country,
                        "landingPage": filters.landing_page},
            "classification": {"mode": self.mode, "version": C.VERSION},
            "data": data,
            "status": "ERROR" if error else ("PARTIAL" if self._warnings else "OK"),
            "warnings": list(self._warnings),
            "sourceMeta": {"provider": "GA4", "propertyId": self.client.prop,
                           "queriedAt": max((r.queried_at for r in self._reports), default=None),
                           "cached": bool(self._reports) and all(r.cached for r in self._reports),
                           "thresholded": any(r.thresholded for r in self._reports)},
        }
        self._reports, self._warnings = [], []
        return env

    def _guard(self, start, end, compare, filters, fn) -> dict:
        try:
            return self._envelope(start, end, compare, filters, fn())
        except HttpError as e:
            self._warn(error_code(e), str(e)[:300])
            return self._envelope(start, end, compare, filters, {}, error=error_code(e))

    # ---- Page A: tổng quan ----

    def summary(self, start: date, end: date, filters: Filters | None = None, compare: bool = True) -> dict:
        filters = filters or Filters()
        prev = previous_period(start, end) if compare else None

        def build():
            g = filters.expression()
            ai = kpi(self._run([], KPI_METRICS, start, end, self._ai(filters)))
            ai_prev = kpi(self._run([], KPI_METRICS, *prev, self._ai(filters))) if prev else None
            ch = self._run(["sessionDefaultChannelGroup"], KPI_METRICS, start, end,
                           C.and_filters(C.channel_filter(*ORGANIC), g))
            ch_prev = self._run(["sessionDefaultChannelGroup"], ["sessions"], *prev,
                                C.and_filters(C.channel_filter(*ORGANIC), g)) if prev else None
            channels = {r["sessionDefaultChannelGroup"]: kpi(Report(rows=[r])) for r in ch.rows}
            for name in ORGANIC:
                channels.setdefault(name, kpi(Report()))
                prev_s = next((r["sessions"] for r in ch_prev.rows if r["sessionDefaultChannelGroup"] == name), 0) \
                    if ch_prev else None
                channels[name]["sessionsPrev"] = prev_s
                channels[name]["sessionsChange"] = change(channels[name]["sessions"], prev_s)
            total = kpi(self._run([], ["sessions"], start, end, g))["sessions"]
            # Mẫu số nhóm organic: đếm phiên duy nhất (AI hoặc Organic Search/Social) bằng một truy vấn, không cộng
            # hai con số có thể trùng nhau.
            base = kpi(self._run([], ["sessions"], start, end, C.and_filters(
                {"orGroup": {"expressions": [C.ga4_filter(self.mode, self.allow), C.channel_filter(*ORGANIC)]}},
                g)))["sessions"]
            paid = kpi(self._run([], ["sessions", "keyEvents"], start, end,
                                 C.and_filters(C.paid_ai_filter(self.allow), g)))
            if ai["sessions"] < self.min_sample:
                self._warn("LOW_SAMPLE_SIZE", f"Chỉ có {ai['sessions']} phiên AI (< {self.min_sample}): "
                                              "các tỷ lệ dao động mạnh, không nên kết luận.")
            if prev and not (ai_prev or {}).get("sessions"):
                self._warn("NO_BASELINE", "Kỳ trước không có phiên AI nào: không tính % thay đổi.")
            deltas = None
            if ai_prev:
                deltas = {
                    "sessions": change(ai["sessions"], ai_prev["sessions"]),
                    "engagedSessions": change(ai["engagedSessions"], ai_prev["engagedSessions"]),
                    "keyEvents": change(ai["keyEvents"], ai_prev["keyEvents"]),
                    "engagementRate": diff(ai["engagementRate"], ai_prev["engagementRate"]),
                    "sessionKeyEventRate": diff(ai["sessionKeyEventRate"], ai_prev["sessionKeyEventRate"]),
                    "avgEngagementTimePerSession": change(ai["avgEngagementTimePerSession"],
                                                          ai_prev["avgEngagementTimePerSession"]),
                }
            return {
                "ai": ai, "aiPrev": ai_prev, "aiDeltas": deltas,
                "channels": channels,
                "share": {
                    "ofAllSessions": ai["sessions"] / total if total else None, "allSessions": total,
                    "ofOrganicBase": ai["sessions"] / base if base else None, "organicBase": base,
                    "organicBaseDefinition": "Phiên AI + Organic Search + Organic Social (không trùng)",
                },
                "paidAi": {"sessions": paid["sessions"], "keyEvents": paid["keyEvents"],
                           "note": "Nguồn AI có medium trả phí (ví dụ chatgpt / paid): không tính vào AI organic"},
            }

        return self._guard(start, end, prev, filters, build)

    # ---- Page B: nguồn AI ----

    def sources(self, start: date, end: date, filters: Filters | None = None, compare: bool = True) -> dict:
        filters = filters or Filters()
        prev = previous_period(start, end) if compare else None

        def build():
            raw = self._run(["sessionSource", "sessionMedium", "sessionDefaultChannelGroup"],
                            ["sessions", "engagedSessions", "keyEvents"], start, end, self._ai(filters),
                            order_by="sessions", limit=1000)
            raw_rows, by_sub = [], {}
            for r in raw.rows:
                label, sub, method = C.classify(r["sessionSource"], r["sessionMedium"],
                                                r["sessionDefaultChannelGroup"], self.mode, self.allow)
                raw_rows.append({**r, "subsource": sub, "method": method})
                agg = by_sub.setdefault(sub, {"sessions": 0, "keyEvents": 0, "methods": set()})
                agg["sessions"] += r["sessions"] or 0
                agg["keyEvents"] += r["keyEvents"] or 0
                agg["methods"].add(method)
            out = []
            for sub, agg in sorted(by_sub.items(), key=lambda kv: -kv[1]["sessions"]):
                if sub == "OTHER_AI":
                    # Kênh native nhưng host chưa có trong danh sách: không dựng được bộ lọc riêng nên không có rate.
                    self._warn("UNMAPPED_AI_SOURCE", "Có phiên kênh AI Assistant từ nguồn chưa có trong danh sách; "
                                                     "xem bảng nguồn chi tiết để bổ sung.")
                    out.append({"source": sub, "sessions": agg["sessions"], "keyEvents": agg["keyEvents"],
                                "engagementRate": None, "sessionKeyEventRate": None,
                                "avgEngagementTimePerSession": None, "sessionsChange": None,
                                "methods": sorted(agg["methods"])})
                    continue
                k = kpi(self._run([], KPI_METRICS, start, end, self._ai(filters, only=sub)))
                k_prev = kpi(self._run([], ["sessions"], *prev, self._ai(filters, only=sub))) if prev else None
                out.append({"source": sub, **k, "sessionsPrev": k_prev["sessions"] if k_prev else None,
                            "sessionsChange": change(k["sessions"], k_prev["sessions"]) if k_prev else None,
                            "methods": sorted(agg["methods"])})
            total = kpi(self._run([], ["sessions"], start, end, self._ai(filters)))["sessions"]
            parts = sum(x["sessions"] for x in out)
            if parts != total:
                self._warn("GA4_TOTAL_DISCREPANCY", f"Tổng các nguồn ({parts}) khác tổng AI ({total}); "
                                                    "thường do thresholding hoặc một phiên khớp nhiều nguồn.")
            return {"sources": out, "rawRows": raw_rows, "totalSessions": total}

        return self._guard(start, end, prev, filters, build)

    # ---- Xu hướng ----

    def trend(self, start: date, end: date, filters: Filters | None = None, interval: str = "day") -> dict:
        filters = filters or Filters()

        def build():
            g = filters.expression()
            ai = {r["date"]: r["sessions"] for r in self._run(["date"], ["sessions"], start, end,
                                                               self._ai(filters), limit=1000).rows}
            org = {}
            for r in self._run(["date", "sessionDefaultChannelGroup"], ["sessions"], start, end,
                               C.and_filters(C.channel_filter(*ORGANIC), g), limit=5000).rows:
                org.setdefault(r["sessionDefaultChannelGroup"], {})[r["date"]] = r["sessions"]
            by_src = {}
            for r in self._run(["date", "sessionSource"], ["sessions"], start, end, self._ai(filters),
                               limit=10000).rows:
                sub = self.allow.subsource(r["sessionSource"]) or "OTHER_AI"
                by_src.setdefault(sub, {}).setdefault(r["date"], 0)
                by_src[sub][r["date"]] += r["sessions"]
            days = [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range((end - start).days + 1)]
            series = {"AI Assistants": ai, **{k: org.get(k, {}) for k in ORGANIC}}
            top = sorted(by_src, key=lambda s: -sum(by_src[s].values()))
            for s in top[:5]:
                series[s] = by_src[s]
            if len(top) > 5:
                series["Other AI"] = {d: sum(by_src[s].get(d, 0) for s in top[5:]) for d in days}
            points = _bucket(days, series, interval, start, end)
            return {"interval": interval, "points": points, "series": list(series)}

        return self._guard(start, end, None, filters, build)

    # ---- Page C/D: trang đích, quốc gia ----

    def _breakdown(self, dimension: str, start, end, filters: Filters, compare: bool, limit: int, offset: int):
        prev = previous_period(start, end) if compare else None

        def build():
            rep = self._run([dimension], ROW_METRICS, start, end, self._ai(filters), order_by="sessions",
                            limit=limit, offset=offset)
            prev_map = {}
            if prev:
                prev_map = {r[dimension]: r["sessions"] for r in self._run(
                    [dimension], ["sessions"], *prev, self._ai(filters), order_by="sessions", limit=10000).rows}
            rows = []
            for r in rep.rows:
                p = prev_map.get(r[dimension], 0) if prev else None
                rows.append({**r, "sessionsPrev": p, "sessionsChange": change(r["sessions"], p) if prev else None,
                             "keyEventsPer100Sessions": 100 * r["keyEvents"] / r["sessions"] if r["sessions"] else None,
                             "notSet": r[dimension] in ("(not set)", "")})
            if any(x["notSet"] for x in rows):
                self._warn("DATA_NOT_AVAILABLE", f"Có phiên AI không xác định được {dimension} ('(not set)'): "
                                                 "giữ thành một dòng riêng.")
            return {"rows": rows, "rowCount": rep.row_count, "limit": limit, "offset": offset}

        return self._guard(start, end, prev, filters, build)

    def landing_pages(self, start: date, end: date, filters: Filters | None = None, compare: bool = True,
                      limit: int = 50, offset: int = 0) -> dict:
        return self._breakdown("landingPage", start, end, filters or Filters(), compare, limit, offset)

    def countries(self, start: date, end: date, filters: Filters | None = None, compare: bool = True,
                  limit: int = 50, offset: int = 0) -> dict:
        return self._breakdown("country", start, end, filters or Filters(), compare, limit, offset)

    def organic_by_landing(self, start: date, end: date, filters: Filters | None = None) -> dict[str, int]:
        """Phiên Organic Search theo trang đích (cột tham khảo bên cạnh AI; không phải traffic AI)."""
        filters = filters or Filters()
        rep = self._run(["landingPage"], ["sessions"], start, end,
                        C.and_filters(C.channel_filter("Organic Search"), filters.expression()), limit=10000)
        self._reports.clear()
        return {r["landingPage"]: r["sessions"] for r in rep.rows}

    def segments(self, start: date, end: date, groups: dict[str, list[str]], filters: Filters | None = None,
                 compare: bool = True) -> dict:
        """KPI AI theo nhóm trang đích (taxonomy loại URL của tool). Mỗi nhóm là một truy vấn tổng hợp với bộ lọc
        landingPage ∈ danh sách trang của nhóm, nên rate là của GA4, không cộng từ các trang."""
        filters = filters or Filters()
        prev = previous_period(start, end) if compare else None

        def build():
            out = []
            for name, pages in groups.items():
                if not pages:
                    continue
                f = C.and_filters(self._ai(filters), C._f("landingPage", inListFilter={"values": pages}))
                k = kpi(self._run([], KPI_METRICS, start, end, f))
                p = kpi(self._run([], ["sessions"], *prev, f))["sessions"] if prev else None
                out.append({"segment": name, "pages": len(pages), **k, "sessionsPrev": p,
                            "sessionsChange": change(k["sessions"], p) if prev else None})
            return {"segments": sorted(out, key=lambda x: -x["sessions"])}

        return self._guard(start, end, prev, filters, build)

    def country_sources(self, start: date, end: date, filters: Filters | None = None) -> dict:
        """Ma trận quốc gia × nguồn AI (chỉ số đếm phiên)."""
        filters = filters or Filters()

        def build():
            matrix: dict[str, dict[str, int]] = {}
            for r in self._run(["country", "sessionSource"], ["sessions"], start, end, self._ai(filters),
                               limit=10000).rows:
                sub = self.allow.subsource(r["sessionSource"]) or "OTHER_AI"
                matrix.setdefault(r["country"], {}).setdefault(sub, 0)
                matrix[r["country"]][sub] += r["sessions"]
            return {"matrix": matrix}

        return self._guard(start, end, None, filters, build)

    def country_trend(self, start: date, end: date, filters: Filters | None = None, top: int = 5,
                      interval: str = "day") -> dict:
        """Xu hướng phiên AI của top quốc gia, còn lại gộp "Quốc gia khác"."""
        filters = filters or Filters()

        def build():
            by_c: dict[str, dict[str, int]] = {}
            for r in self._run(["date", "country"], ["sessions"], start, end, self._ai(filters), limit=20000).rows:
                by_c.setdefault(r["country"], {})[r["date"]] = r["sessions"]
            ranked = sorted(by_c, key=lambda c: -sum(by_c[c].values()))
            days = [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range((end - start).days + 1)]
            series = {c: by_c[c] for c in ranked[:top]}
            if len(ranked) > top:
                series["Quốc gia khác"] = {d: sum(by_c[c].get(d, 0) for c in ranked[top:]) for d in days}
            return {"interval": interval, "points": _bucket(days, series, interval, start, end),
                    "series": list(series)}

        return self._guard(start, end, None, filters, build)

    # ---- Key event tách theo từng event ----

    def key_events(self, start: date, end: date, events: list[str], filters: Filters | None = None) -> dict:
        filters = filters or Filters()

        def build():
            counts = {r["eventName"]: r["keyEvents"] for r in self._run(
                ["eventName"], ["keyEvents"], start, end,
                C.and_filters(self._ai(filters), C._f("eventName", inListFilter={"values": events})), limit=100).rows}
            out = []
            for ev in events:
                rate = None
                try:
                    # Kèm "sessions": GA4 bỏ hẳn dòng khi mọi metric bằng 0, nên rate 0% thật sẽ thành "không có số".
                    rep = self._run([], ["sessions", f"sessionKeyEventRate:{ev}"], start, end, self._ai(filters))
                    rate = rep.rows[0].get(f"sessionKeyEventRate:{ev}") if rep.rows and rep.rows[0]["sessions"] \
                        else None
                except HttpError as e:
                    if e.resp.status != 400:
                        raise
                    self._warn("METRIC_INCOMPATIBLE", f"GA4 không tính được tỷ lệ phiên riêng cho event '{ev}'.")
                out.append({"event": ev, "keyEvents": counts.get(ev, 0), "sessionKeyEventRate": rate})
            return {"events": out}

        return self._guard(start, end, None, filters, build)


def _bucket(days: list[str], series: dict[str, dict], interval: str, start: date, end: date) -> list[dict]:
    """Gộp số đếm theo ngày thành ngày hoặc tuần ISO (thứ Hai); đánh dấu tuần không trọn vẹn trong kỳ."""
    if interval == "day":
        return [{"date": d, **{s: v.get(d, 0) for s, v in series.items()}} for d in days]
    weeks: dict[str, dict] = {}
    for d in days:
        dt = date(int(d[:4]), int(d[4:6]), int(d[6:]))
        monday = dt - timedelta(days=dt.weekday())
        w = weeks.setdefault(monday.isoformat(), {"week": monday.isoformat(), **{s: 0 for s in series},
                                                  "partial": monday < start or monday + timedelta(days=6) > end})
        for s, v in series.items():
            w[s] += v.get(d, 0)
    return list(weeks.values())
