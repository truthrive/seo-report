"""Cơ hội SEO/GEO (spec AI Search & GEO §2 P1, §3.6): đặt GA4 AI referral và GSC Web cạnh nhau theo URL, rồi áp các
quy tắc có ngưỡng chỉnh được.

Ranh giới bắt buộc:
- Cột GSC là **Google Web Search tổng** (gồm cả nhưng không chỉ AI Overviews/AI Mode). Không bao giờ gọi là số AI.
- Không nhân/chia chéo hai nguồn (không suy ra "AI conversions" từ click GSC).
- Quy tắc chỉ là gợi ý để kiểm chứng, không kết luận nhân quả; mỗi gợi ý ghi bằng chứng, ngưỡng, độ tin cậy.
"""
import json
import sqlite3
from datetime import date, timedelta

from . import urls as U

GA4_ONLY, GSC_ONLY, MATCHED = "ga4_only", "gsc_only", "matched"

DEFAULTS = {
    "low_gsc_min_ai_sessions": 5,      # AI_REFERRAL_WITH_LOW_GSC_VISIBILITY: tối thiểu phiên AI
    "low_gsc_max_impressions": 100,    # …và impression GSC Web dưới mức này
    "high_gsc_min_impressions": 5000,  # GSC_HIGH_IMPRESSIONS_LOW_AI_REFERRAL: impression GSC Web từ mức này
    "high_gsc_max_ai_sessions": 1,     # …và phiên AI không quá mức này
    "weak_min_sessions": 20,           # AI_ENGAGEMENT_WEAK: cỡ mẫu tối thiểu
    "weak_gap_points": 15,             # …engagement thấp hơn mức chung của AI từ ngần này điểm %
}
LABELS = {
    "low_gsc_min_ai_sessions": "Trang AI dẫn tới nhưng ít hiển thị Google: tối thiểu phiên AI",
    "low_gsc_max_impressions": "… và impression GSC Web dưới",
    "high_gsc_min_impressions": "Trang hiển thị nhiều trên Google nhưng ít AI dẫn tới: impression GSC Web từ",
    "high_gsc_max_ai_sessions": "… và phiên AI không quá",
    "weak_min_sessions": "Engagement AI yếu: cỡ mẫu tối thiểu (phiên AI)",
    "weak_gap_points": "… thấp hơn engagement AI chung từ (điểm %)",
}
TOP_GSC_PAGES = 500
MIN_DAYS = 28  # ngưỡng mặc định đặt cho kỳ 28 ngày: màn hình tự nới kỳ ngắn hơn lên 28 ngày
OPP_FIELDS = ("rule_id", "url", "type", "title", "evidence", "threshold", "severity", "confidence", "verification",
              "action", "source", "data_period")


def get_thresholds(con: sqlite3.Connection) -> dict:
    con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    row = con.execute("SELECT value FROM app_settings WHERE key = 'ai_opportunity_thresholds'").fetchone()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def set_thresholds(con: sqlite3.Connection, site: str, values: dict, user: str) -> dict:
    clean = {k: float(values[k]) for k in DEFAULTS if values.get(k) is not None}
    con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    with con:
        con.execute("INSERT OR REPLACE INTO app_settings VALUES ('ai_opportunity_thresholds', ?)", (json.dumps(clean),))
        U.log_change(con, user, site, "Đổi ngưỡng cơ hội SEO/GEO", None, json.dumps(clean, ensure_ascii=False))
    return get_thresholds(con)


def gsc_by_url(con: sqlite3.Connection, site: str, start: date, end: date) -> dict[int, dict]:
    """Click/impression/position GSC Web theo URL báo cáo (đã gộp #mục, ?utm…), theo ngày GSC (giờ Pacific)."""
    rows = con.execute(
        """SELECT pu.url_id, SUM(d.clicks), SUM(d.impressions),
                  SUM(d.position * d.impressions) / NULLIF(SUM(d.impressions), 0)
           FROM gsc_page_daily d JOIN page_url pu ON pu.page_id = d.page_id JOIN urls u ON u.id = pu.url_id
           WHERE u.site = ? AND d.date BETWEEN ? AND ? GROUP BY pu.url_id""",
        (site, start.isoformat(), end.isoformat())).fetchall()
    return {uid: {"clicks": c, "impressions": i, "ctr": c / i if i else None, "position": p} for uid, c, i, p in rows}


def gsc_missing_days(con: sqlite3.Connection, site: str, start: date, end: date) -> int:
    have = {r[0] for r in con.execute("SELECT date FROM gsc_fetch_log WHERE site = ? AND date BETWEEN ? AND ?",
                                      (site, start.isoformat(), end.isoformat()))}
    return (end - start).days + 1 - len(have)


def _match_ga4_path(con: sqlite3.Connection, site: str, origin: str, path: str) -> int | None:
    """Site chuyển hướng 308 `/x` → `/x/`, nên bản có / cuối là URL thật; bản thiếu / trong GSC chỉ là URL cũ còn sót.
    Vì vậy thử bản có / trước, không có mới dùng đúng đường dẫn GA4."""
    url = U.normalize(origin + path)
    if not url.endswith("/") and "?" not in url:
        row = con.execute("SELECT id FROM urls WHERE site = ? AND url = ?", (site, url + "/")).fetchone()
        if row:
            return row[0]
    return U._match_existing(con, site, url)


def align(con: sqlite3.Connection, site: str, ai_rows: list[dict], gsc: dict[int, dict]) -> list[dict]:
    """Một dòng mỗi URL báo cáo. GA4 cho đường dẫn (thường thiếu / cuối); nhiều đường dẫn về cùng một URL thì cộng
    các số đếm (sessions, engagedSessions, keyEvents) và tính lại engagement rate từ số đếm; session key event rate
    không ghép được nên để None và đánh dấu."""
    origin = site.rstrip("/")
    merged: dict = {}
    for r in ai_rows:
        path = r["landingPage"]
        if path in ("(not set)", ""):
            continue  # không xác định được trang: không ghép với GSC
        url_id = _match_ga4_path(con, site, origin, path) if path.startswith("/") else None
        key = url_id if url_id else f"ga4:{path}"
        m = merged.setdefault(key, {"url_id": url_id, "paths": [], "ai_sessions": 0, "ai_engaged": 0,
                                    "ai_key_events": 0, "ai_ker": r.get("sessionKeyEventRate")})
        m["paths"].append(path)
        m["ai_sessions"] += r["sessions"] or 0
        m["ai_engaged"] += r.get("engagedSessions") or 0
        m["ai_key_events"] += r.get("keyEvents") or 0
        if len(m["paths"]) > 1:
            m["ai_ker"] = None
    top_gsc = sorted(gsc.items(), key=lambda kv: -kv[1]["impressions"])[:TOP_GSC_PAGES]
    for uid, _ in top_gsc:
        merged.setdefault(uid, {"url_id": uid, "paths": [], "ai_sessions": 0, "ai_engaged": 0, "ai_key_events": 0,
                                "ai_ker": None})
    info = {uid: (url, typ) for uid, url, typ in con.execute("SELECT id, url, type FROM urls WHERE site = ?", (site,))}
    out = []
    for key, m in merged.items():
        uid = m["url_id"]
        g = gsc.get(uid) if uid else None
        has_ai, has_gsc = m["ai_sessions"] > 0, bool(g and g["impressions"])
        url, typ = info[uid] if uid in info else (origin + m["paths"][0], None)
        out.append({
            "url_id": uid, "url": url, "path": url.replace(origin, "") or "/", "type": typ or
            ("Chưa có trong dữ liệu GSC" if not uid else "Chờ đọc schema"),
            "match": MATCHED if has_ai and has_gsc else (GA4_ONLY if has_ai else GSC_ONLY),
            "ga4_paths": m["paths"], "ambiguous": len(m["paths"]) > 1,
            "ai_sessions": m["ai_sessions"], "ai_engaged": m["ai_engaged"],
            "ai_engagement_rate": m["ai_engaged"] / m["ai_sessions"] if m["ai_sessions"] else None,
            "ai_key_events": m["ai_key_events"], "ai_session_key_event_rate": m["ai_ker"] if has_ai else None,
            "gsc_clicks": g["clicks"] if g else 0, "gsc_impressions": g["impressions"] if g else 0,
            "gsc_ctr": g["ctr"] if g else None, "gsc_position": g["position"] if g else None,
        })
    return sorted(out, key=lambda r: (-r["ai_sessions"], -r["gsc_impressions"]))


def _confidence(sessions: int) -> str:
    return "cao" if sessions >= 50 else ("trung bình" if sessions >= 20 else "thấp")


def rules(rows: list[dict], t: dict, ai_engagement_rate: float | None, period: str) -> list[dict]:
    """Áp 3 quy tắc theo spec. Mỗi gợi ý có bằng chứng, ngưỡng, độ tin cậy, cách kiểm chứng, gợi ý hành động."""
    out = []
    for r in rows:
        base = {"url": r["url"], "path": r["path"], "type": r["type"], "data_period": period}
        if r["ai_sessions"] >= t["low_gsc_min_ai_sessions"] and r["gsc_impressions"] < t["low_gsc_max_impressions"]:
            out.append({**base, "rule_id": "AI_REFERRAL_WITH_LOW_GSC_VISIBILITY",
                        "title": "AI dẫn tới nhưng ít hiển thị trên Google Search",
                        "evidence": f"{r['ai_sessions']} phiên AI (GA4); {r['gsc_impressions']} impression GSC Web",
                        "threshold": f"phiên AI ≥ {t['low_gsc_min_ai_sessions']:g} và impression GSC < "
                                     f"{t['low_gsc_max_impressions']:g}",
                        "severity": "trung bình", "confidence": _confidence(r["ai_sessions"]),
                        "verification": "Xem trạng thái index/canonical (màn Check index) và các query GSC của trang "
                                        "(màn URL).",
                        "action": "Trang có giá trị với người dùng AI: kiểm tra index, title/meta, liên kết nội bộ, "
                                  "cân nhắc tối ưu cho keyword liên quan.",
                        "source": "GA4 AI referral + GSC Web"})
        if r["gsc_impressions"] >= t["high_gsc_min_impressions"] and r["ai_sessions"] <= t["high_gsc_max_ai_sessions"]:
            out.append({**base, "rule_id": "GSC_HIGH_IMPRESSIONS_LOW_AI_REFERRAL",
                        "title": "Hiển thị nhiều trên Google nhưng ít được AI assistant dẫn tới",
                        "evidence": f"{r['gsc_impressions']:,} impression GSC Web; {r['ai_sessions']} phiên AI".replace(
                            ",", "."),
                        "threshold": f"impression GSC ≥ {t['high_gsc_min_impressions']:g} và phiên AI ≤ "
                                     f"{t['high_gsc_max_ai_sessions']:g}",
                        "severity": "thấp", "confidence": "trung bình",
                        "verification": "Không có phiên AI chưa chắc là AI không nhắc tới trang: tool không đo được "
                                        "lượt trích dẫn. Thử hỏi ChatGPT/Gemini chủ đề của trang để kiểm tra.",
                        "action": "Bổ sung câu trả lời trực tiếp, số liệu cụ thể (giá, địa chỉ, thông số), dữ liệu cấu "
                                  "trúc; theo dõi phiên AI các tuần sau.",
                        "source": "GSC Web + GA4 AI referral"})
        er = r["ai_engagement_rate"]
        if (ai_engagement_rate is not None and er is not None and r["ai_sessions"] >= t["weak_min_sessions"]
                and er < ai_engagement_rate - t["weak_gap_points"] / 100):
            out.append({**base, "rule_id": "AI_ENGAGEMENT_WEAK",
                        "title": "Người dùng từ AI tương tác kém trên trang này",
                        "evidence": f"engagement {er * 100:.1f}% trên {r['ai_sessions']} phiên AI, so với "
                                    f"{ai_engagement_rate * 100:.1f}% của toàn bộ phiên AI".replace(".", ","),
                        "threshold": f"cỡ mẫu ≥ {t['weak_min_sessions']:g} phiên và thấp hơn ≥ "
                                     f"{t['weak_gap_points']:g} điểm %",
                        "severity": "trung bình", "confidence": _confidence(r["ai_sessions"]),
                        "verification": "Mở trang như người dùng đến từ ChatGPT: nội dung có đúng điều AI mô tả không, "
                                        "tốc độ tải trên mobile.",
                        "action": "Đưa thông tin người dùng AI cần (giá, địa chỉ, nút liên hệ) lên đầu trang.",
                        "source": "GA4 AI referral"})
    order = {"AI_REFERRAL_WITH_LOW_GSC_VISIBILITY": 0, "AI_ENGAGEMENT_WEAK": 1,
             "GSC_HIGH_IMPRESSIONS_LOW_AI_REFERRAL": 2}
    return sorted(out, key=lambda o: (order[o["rule_id"]], o["path"]))


def build(con: sqlite3.Connection, site: str, start: date, end: date, ai_landing_rows: list[dict],
          ai_engagement_rate: float | None) -> dict:
    gsc = gsc_by_url(con, site, start, end)
    rows = align(con, site, ai_landing_rows, gsc)
    t = get_thresholds(con)
    period = f"{start:%d/%m/%Y}–{end:%d/%m/%Y}"
    warnings = [{"code": "TIMEZONE_MISMATCH",
                 "message": "GSC tính ngày theo giờ Pacific (Mỹ), GA4 theo giờ Việt Nam: hai nhóm cột lệch nhau "
                            "khoảng nửa ngày ở đầu và cuối kỳ. Chỉ so sánh tương đối, không đối soát từng số."}]
    missing = gsc_missing_days(con, site, start, end)
    if missing:
        warnings.append({"code": "INCOMPLETE_PERIOD",
                         "message": f"GSC chưa có dữ liệu {missing} ngày cuối kỳ (GSC trễ 2–3 ngày): cột GSC thiếu."})
    if any(r["ambiguous"] for r in rows):
        warnings.append({"code": "URL_MATCH_AMBIGUOUS",
                         "message": "Có URL ghép từ nhiều đường dẫn GA4 (ví dụ có và không có / cuối): số đếm đã cộng, "
                                    "session key event rate để trống."})
    unmatched_ga4 = [r for r in rows if r["match"] == GA4_ONLY and not r["url_id"]]
    if unmatched_ga4:
        warnings.append({"code": "URL_MATCH_AMBIGUOUS",
                         "message": f"{len(unmatched_ga4)} trang đích GA4 không có trong dữ liệu GSC của tool."})
    return {"rows": rows, "opportunities": rules(rows, t, ai_engagement_rate, period), "thresholds": t,
            "warnings": warnings, "period": period}
