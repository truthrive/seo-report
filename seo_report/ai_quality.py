"""Chất lượng dữ liệu cho module AI Search & GEO (spec §3.7, §7.3): kết nối, độ mới dữ liệu, đối soát tổng, kiểm tra
tỷ lệ, danh mục nguồn AI. Chỉ đọc, không sửa dữ liệu. Không hiển thị token hay thông tin đăng nhập.

Mỗi kiểm tra là {code, status, title, detail}; status ∈ ok / warn / error / info.
"""
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from . import ai_classifier as C
from . import ai_format as F

OK, WARN, ERROR, INFO = "ok", "warn", "error", "info"
# Tên nguồn có dáng AI mà danh sách hiện tại có thể bỏ sót (chỉ để rà, không tự cộng vào AI).
AI_HINT_REGEX = r"(gpt|openai|gemini|bard|claude|anthropic|perplexity|copilot|deepseek|grok|mistral|meta\.ai|poe\.com" \
                r"|you\.com|phind|kagi|qwen|kimi|doubao|chatglm)"
RATE_FIELDS = ("engagementRate", "sessionKeyEventRate")


def _check(code, status, title, detail="") -> dict:
    return {"code": code, "status": status, "title": title, "detail": detail}


# ---- GA4: đối soát trên các envelope màn đã tải ----

def ga4_checks(summary: dict, sources: dict, landing: dict | None, countries: dict | None) -> list[dict]:
    out = []
    envs = [e for e in (summary, sources, landing, countries) if e]
    errors = [e for e in envs if e.get("status") == "ERROR"]
    if errors:
        out.append(_check("API_ERROR", ERROR, "Có truy vấn GA4 lỗi",
                          "; ".join(w["message"][:150] for e in errors for w in e.get("warnings", []))))
        return out
    total = summary["data"]["ai"]["sessions"]
    parts = {"Bảng nguồn AI": sum(x["sessions"] for x in sources["data"]["sources"])}
    if landing:
        parts["Bảng trang đích"] = sum(r["sessions"] for r in landing["data"]["rows"])
    if countries:
        parts["Bảng quốc gia"] = sum(r["sessions"] for r in countries["data"]["rows"])
    diffs = {k: v - total for k, v in parts.items() if v != total}
    detail = f"Tổng KPI {total} phiên; " + "; ".join(f"{k} {v}" for k, v in parts.items())
    if not diffs:
        out.append(_check("GA4_TOTAL_DISCREPANCY", OK, "Tổng phiên AI khớp giữa KPI và các bảng", detail))
    else:
        worst = max(abs(d) for d in diffs.values())
        out.append(_check("GA4_TOTAL_DISCREPANCY", WARN if worst / max(total, 1) > 0.01 else INFO,
                          "Tổng các bảng lệch so với KPI",
                          detail + ". Bảng chi tiết có thể thiếu dòng do giới hạn số dòng hoặc thresholding của GA4; "
                                   "KPI là số chuẩn."))
    for name, env in (("trang đích", landing), ("quốc gia", countries)):
        if env and env["data"].get("rowCount", 0) > len(env["data"]["rows"]):
            out.append(_check("ROW_LIMIT", WARN, f"Bảng {name} bị cắt bớt dòng",
                              f"GA4 có {env['data']['rowCount']} dòng, tool tải {len(env['data']['rows'])}."))

    bad = []
    blocks = [("KPI", summary["data"]["ai"])] + [(f"nguồn {x['source']}", x) for x in sources["data"]["sources"]]
    if landing:
        blocks += [(f"trang {r['landingPage']}", r) for r in landing["data"]["rows"]]
    for label, row in blocks:
        for f in RATE_FIELDS:
            v = row.get(f)
            if v is not None and not 0 <= v <= 1:
                bad.append(f"{label}: {f} = {v}")
    out.append(_check("RATE_RANGE", ERROR if bad else OK,
                      "Tỷ lệ nằm ngoài 0–100%" if bad else "Mọi tỷ lệ nằm trong 0–100%",
                      "; ".join(bad[:10]) if bad else f"Đã kiểm {len(blocks)} dòng × {len(RATE_FIELDS)} tỷ lệ."))

    if landing:
        notset = sum(r["sessions"] for r in landing["data"]["rows"] if r["landingPage"] in ("(not set)", ""))
        share = notset / total if total else 0
        out.append(_check("LANDING_NOT_SET", WARN if share > 0.2 else (INFO if notset else OK),
                          f"{notset} phiên AI không xác định trang đích ({share * 100:.1f}%)".replace(".", ","),
                          "GA4 không ghi nhận trang đầu tiên của phiên (thường do phiên bắt đầu bằng sự kiện không "
                          "phải page_view). Các phiên này vẫn tính trong KPI, chỉ không ghép được với URL."))

    seen = set()
    for env in envs:
        for w in env.get("warnings", []):
            if w["code"] in ("GA4_THRESHOLDED", "LOW_SAMPLE_SIZE", "INCOMPLETE_PERIOD", "UNMAPPED_AI_SOURCE") \
                    and w["code"] not in seen:
                seen.add(w["code"])
                out.append(_check(w["code"], WARN if w["code"] != "INCOMPLETE_PERIOD" else INFO,
                                  F.WARNING_TITLES.get(w["code"], w["code"]), w["message"]))
    return out


def source_inventory(sources: dict) -> dict:
    """Phiên AI theo cách nhận diện: native (kênh AI Assistant của GA4), fallback (theo danh sách nguồn), và phần
    native từ nguồn chưa có trong danh sách."""
    inv = {C.NATIVE: 0, C.FALLBACK: 0, "UNMAPPED": 0}
    for r in sources["data"].get("rawRows", []):
        inv[r["method"]] = inv.get(r["method"], 0) + (r["sessions"] or 0)
        if r["subsource"] == "OTHER_AI":
            inv["UNMAPPED"] += r["sessions"] or 0
    return inv


def candidate_sources(ai, start: date, end: date) -> list[dict]:
    """Nguồn có tên giống AI trên toàn bộ traffic nhưng KHÔNG được tính là AI, kèm lý do. Để người phụ trách quyết
    định có bổ sung vào danh sách hay không; tool không tự cộng."""
    f = C._f("sessionSource", stringFilter={"matchType": "PARTIAL_REGEXP", "value": AI_HINT_REGEX,
                                            "caseSensitive": False})
    rep = ai.client.run(["sessionSource", "sessionMedium", "sessionDefaultChannelGroup"], ["sessions"], start, end, f,
                        order_by="sessions", limit=500)
    out = []
    for r in rep.rows:
        label, sub, _ = C.classify(r["sessionSource"], r["sessionMedium"], r["sessionDefaultChannelGroup"], ai.mode,
                                   ai.allow)
        if label == C.AI_ASSISTANTS:
            continue
        if ai.allow.subsource(r["sessionSource"]) and C.is_paid(r["sessionMedium"]):
            reason = "Medium trả phí: tính là quảng cáo (quyết định R0)"
        else:
            reason = "Chưa có trong danh sách nguồn AI"
        out.append({"source": r["sessionSource"], "medium": r["sessionMedium"],
                    "channel": r["sessionDefaultChannelGroup"], "sessions": r["sessions"], "reason": reason})
    return out


# ---- GSC, lịch chạy, cache: đọc SQLite / file của tool ----

def gsc_status(con: sqlite3.Connection, site: str, today: date) -> list[dict]:
    row = con.execute("SELECT MIN(date), MAX(date), MAX(fetched_at) FROM gsc_fetch_log WHERE site = ?",
                      (site,)).fetchone()
    if not row or not row[1]:
        return [_check("GSC_NO_DATA", ERROR, "Chưa có dữ liệu GSC", "Chạy đồng bộ: python -m seo_report sync")]
    first, last, fetched = row
    lag = (today - date.fromisoformat(last)).days
    out = [_check("GSC_FRESHNESS", OK if lag <= 4 else WARN, f"GSC có dữ liệu tới {last} (trễ {lag} ngày)",
                  f"Từ {first}. GSC thường trễ 2–3 ngày. Lần lấy gần nhất {fetched[:16].replace('T', ' ')} UTC.")]
    start = max(today - timedelta(days=30), date.fromisoformat(first))  # trước ngày đầu tiên có dữ liệu thì không tính là thiếu
    have = {r[0] for r in con.execute("SELECT date FROM gsc_fetch_log WHERE site = ? AND date >= ?",
                                      (site, start.isoformat()))}
    missing = [(start + timedelta(days=i)).isoformat() for i in range((date.fromisoformat(last) - start).days + 1)
               if (start + timedelta(days=i)).isoformat() not in have]
    out.append(_check("GSC_GAPS", WARN if missing else OK,
                      f"Thiếu {len(missing)} ngày GSC trong 30 ngày qua" if missing else "GSC đủ ngày trong 30 ngày qua",
                      ", ".join(missing[:10])))
    out.append(generative_ai_status(con, site, today))
    return out


def generative_ai_status(con: sqlite3.Connection, site: str, today: date) -> dict:
    """File GSC Generative AI đã nhập tới ngày nào. Chưa nhập = Not available (không phải 0)."""
    from . import ai_gsc_import as G
    imps = G.imports(con, site)
    if not imps:
        return _check("NO_GENERATIVE_AI_SOURCE", INFO, "Impression AI Overviews / AI Mode: chưa có (Not available)",
                      "Chưa nhập file GSC Generative AI (tab AI trên Google). Mọi cột GSC khác trong tool là Google Web "
                      "Search tổng, không phải số AI.")
    last = max(i["period_end"] for i in imps)
    lag = (today - date.fromisoformat(last)).days
    return _check("GENERATIVE_AI_FRESHNESS", OK if lag <= 10 else WARN,
                  f"File GSC Generative AI có dữ liệu tới {last} (cách đây {lag} ngày)",
                  f"{len(imps)} lần nhập. " + ("" if lag <= 10 else "Nên xuất và nhập file mới mỗi tuần."))


def daily_job_status(log_path: Path, today: date) -> dict:
    if not log_path.exists():
        return _check("DAILY_JOB", WARN, "Chưa thấy nhật ký chạy hằng ngày", str(log_path))
    at = datetime.fromtimestamp(log_path.stat().st_mtime)
    age = (today - at.date()).days
    return _check("DAILY_JOB", OK if age <= 1 else WARN,
                  f"Lịch chạy hằng ngày ghi nhật ký lần cuối {at:%d/%m/%Y %H:%M}",
                  "Lịch 6:00 sáng: đồng bộ GSC → check rank → check index → phân loại URL." +
                  ("" if age <= 1 else f" Đã {age} ngày không chạy: kiểm tra Task Scheduler."))


def cache_status(con: sqlite3.Connection) -> dict:
    con.execute("CREATE TABLE IF NOT EXISTS ga4_cache (key TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
                "payload TEXT NOT NULL)")
    n, oldest, newest = con.execute("SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM ga4_cache").fetchone()
    return {"entries": n, "oldest": oldest, "newest": newest}


def connections(cfg) -> tuple[list[dict], dict]:
    """Kết nối GA4/GSC: quyền đã cấp, property, múi giờ, key events, trường GA4 thiếu. Không đọc/hiện token."""
    from . import auth, ga4
    out, info = [], {"property": cfg.ga4_property, "site": cfg.site_url, "key_events": []}
    try:
        creds = auth.get_credentials(cfg, need=auth.ALL_SCOPES)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        return [_check("API_PERMISSION_DENIED", ERROR, "Token chưa có đủ quyền GSC + GA4", str(e))], info
    out.append(_check("SCOPES", OK, "Đã cấp quyền đọc GSC và GA4",
                      "Chỉ đọc (webmasters.readonly, analytics.readonly). Không có quyền gửi index."))
    try:
        admin = auth.build_ga4_admin(creds)
        p = ga4.property_info(admin, cfg.ga4_property)
        info.update(p)
        out.append(_check("GA4_PROPERTY", OK, f"GA4 {cfg.ga4_property}: {p['name']}",
                          f"Múi giờ {p['timezone']}, tiền tệ {p['currency']}. GSC tính ngày theo giờ Pacific."))
        info["key_events"] = ga4.key_events(admin, cfg.ga4_property)
    except Exception as e:  # noqa: BLE001
        out.append(_check("PROPERTY_NOT_FOUND", ERROR, "Không đọc được property GA4", str(e)[:200]))
    try:
        miss = ga4.metadata_check(auth.build_ga4_data(creds), cfg.ga4_property)
        gone = miss["missing_dimensions"] + miss["missing_metrics"]
        out.append(_check("METRIC_INCOMPATIBLE", WARN if gone else OK,
                          "Property thiếu trường GA4 mà module cần" if gone else "Property có đủ trường GA4 cần dùng",
                          ", ".join(gone)))
    except Exception as e:  # noqa: BLE001
        out.append(_check("METRIC_INCOMPATIBLE", WARN, "Không đọc được metadata GA4", str(e)[:200]))
    out.append(_check("GSC_PROPERTY", OK, f"GSC {cfg.site_url}", "Property dạng URL-prefix, dùng nguyên chuỗi."))
    return out, info


def summarize(checks: list[dict]) -> str:
    """Trạng thái chung: lỗi > cảnh báo > ổn."""
    st = {c["status"] for c in checks}
    return ERROR if ERROR in st else (WARN if WARN in st else OK)
