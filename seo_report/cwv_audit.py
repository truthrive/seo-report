"""Chấm điểm và kiểm tra tốc độ (trang Tốc độ & Core Web Vitals), chỉ dùng số đã lấy (cwv.py), không gọi thêm API.

Điểm tốc độ 0–100 = 50% người dùng thật trên điện thoại + 20% người dùng thật trên máy tính + 30% điểm PageSpeed trung
bình các trang quan trọng. Mỗi chỉ số người dùng thật (LCP, INP, CLS) chấm liên tục theo ngưỡng của Google: đạt “Tốt”
= 100, ở ngưỡng “Kém” = 50, gấp đôi ngưỡng “Kém” = 0. Phần nào chưa có số thì chia lại trọng số cho phần còn lại.
"""
from . import cwv as C

WEIGHTS = {"phone": 0.5, "desktop": 0.2, "lab": 0.3}
GRADES = ((90, "Rất tốt", "green"), (75, "Tốt", "green"), (50, "Trung bình", "amber"), (0, "Kém", "red"))
NEAR = 0.9            # chỉ số đạt nhưng đã ở trên 90% ngưỡng “Tốt”: sát ngưỡng
WORSE = 0.15          # xấu đi hơn 15% so với khoảng 8 tuần trước
COMMON_PAGES = 3      # việc nên sửa xuất hiện ở từ chừng này trang trở lên: sửa chung cho cả website


def metric_score(metric: str, value) -> float | None:
    if value is None:
        return None
    good, poor = C.THRESHOLDS[metric]
    if value <= good:
        return 100.0
    if value <= poor:
        return 100 - 50 * (value - good) / (poor - good)
    return max(0.0, 50 - 50 * (value - poor) / poor)


def field_score(values: dict) -> float | None:
    s = [metric_score(m, values.get(m)) for m in C.CORE]
    s = [x for x in s if x is not None]
    return sum(s) / len(s) if s else None


def score(phone: list[dict], desktop: list[dict], pages: list[dict]) -> dict:
    """{"score", "grade", "tone", "parts": {phone, desktop, lab}} (phần chưa có số = None)."""
    perfs = [p["perf"] for p in pages if p.get("perf") is not None]
    parts = {"phone": field_score(phone[-1]) if phone else None,
             "desktop": field_score(desktop[-1]) if desktop else None,
             "lab": sum(perfs) / len(perfs) if perfs else None}
    have = {k: v for k, v in parts.items() if v is not None}
    if not have:
        return {"score": None, "grade": "Chưa có số", "tone": "grey", "parts": parts}
    total = sum(WEIGHTS[k] for k in have)
    s = round(sum(v * WEIGHTS[k] for k, v in have.items()) / total)
    grade, tone = next((g, t) for floor, g, t in GRADES if s >= floor)
    return {"score": s, "grade": grade, "tone": tone, "parts": {k: (round(v) if v is not None else None)
                                                                for k, v in parts.items()}}


def audit(phone: list[dict], desktop: list[dict], pages: list[dict]) -> list[dict]:
    """Mục kiểm tra: [{"key", "level", "title", "detail", "pages": [url] (mục theo trang: bấm để lọc bảng)}],
    nặng trước."""
    out = []

    def add(key, level, title, detail, urls=None):
        out.append({"key": key, "level": level, "title": title, "detail": detail, "pages": urls or []})

    for form, series, label in (("phone", phone, "điện thoại"), ("desktop", desktop, "máy tính")):
        if not series:
            continue
        now = series[-1]
        v = C.assess(now)
        if v in ("poor", "ni"):
            bad = [C.NAMES[m] for m in C.CORE if C.rating(m, now.get(m)) in ("poor", "ni")]
            add(f"cwv_{form}", "high" if v == "poor" or form == "phone" else "medium",
                f"Website chưa đạt Core Web Vitals trên {label}",
                f"Chỉ số chưa tốt: {', '.join(bad)}. Google dùng số này khi xếp hạng.")
        elif v == "good":
            add(f"cwv_{form}", "ok", f"Website đạt Core Web Vitals trên {label}",
                " · ".join(f"{m.upper()} {C.fmt(m, now.get(m))}" for m in C.CORE if now.get(m) is not None))
        if form != "phone":
            continue
        for m in C.CORE:
            val, (good, _) = now.get(m), C.THRESHOLDS[m]
            if val is not None and NEAR * good < val <= good:
                add(f"near_{m}", "medium", f"{C.NAMES[m]} sát ngưỡng",
                    f"{C.fmt(m, val)} trên điện thoại, ngưỡng “Tốt” là {C.fmt(m, good)}: chậm thêm một chút là trượt.")
        old = series[-9] if len(series) >= 9 else series[0]
        for m in C.CORE:
            a, b = old.get(m), now.get(m)
            if a and b and b > a * (1 + WORSE) and C.rating(m, b) != "good" or (a and b and b > a * (1 + 2 * WORSE)):
                add(f"worse_{m}", "medium", f"{C.NAMES[m]} đang xấu đi",
                    f"{C.fmt(m, a)} → {C.fmt(m, b)} trong khoảng 8 tuần (điện thoại).")
        for m, level, why in (("ttfb", "medium", "máy chủ / hosting phản hồi chậm: xem bộ nhớ đệm (cache), CDN, gói "
                                                 "hosting"),
                              ("fcp", "info", "nội dung đầu tiên hiện chậm: giảm CSS / JS chặn hiển thị, font")):
            r = C.rating(m, now.get(m))
            if r in ("ni", "poor"):
                add(f"{m}_slow", "high" if r == "poor" else level, f"{C.NAMES[m]} {'kém' if r == 'poor' else 'cần cải thiện'}",
                    f"{C.fmt(m, now.get(m))} trên điện thoại: {why}.")

    ok_pages = [p for p in pages if p.get("perf") is not None]
    low = [p["url"] for p in ok_pages if p["perf"] < 50]
    mid = [p["url"] for p in ok_pages if 50 <= p["perf"] < 90]
    if low:
        add("perf_low", "high", "Trang có điểm hiệu năng dưới 50",
            f"{len(low)} trang quan trọng bị Google chấm “Kém” khi đo thử trên điện thoại.", low)
    if mid:
        add("perf_mid", "info", "Trang có điểm hiệu năng 50–89",
            f"{len(mid)} trang ở mức “Cần cải thiện”: xem việc nên sửa của từng trang.", mid)
    field_bad = [p["url"] for p in pages if C.assess(p.get("field") or {}) in ("poor", "ni")]
    if field_bad:
        add("page_field", "high", "Trang có người dùng thật chưa đạt Core Web Vitals",
            f"{len(field_bad)} trang đủ lượt truy cập để Google đo, nhưng chưa đạt.", field_bad)
    seo = [p["url"] for p in ok_pages if (p.get("seo") or 100) < 90]
    if seo:
        add("seo_low", "medium", "Trang có điểm SEO kỹ thuật dưới 90",
            f"{len(seo)} trang thiếu thẻ / cấu hình SEO cơ bản (tiêu đề, mô tả, link không thu thập được…).", seo)
    a11y = [p["url"] for p in ok_pages if (p.get("a11y") or 100) < 80]
    if a11y:
        add("a11y_low", "info", "Trang có điểm khả năng truy cập dưới 80",
            f"{len(a11y)} trang: thiếu chữ thay ảnh (alt), độ tương phản, nhãn nút…", a11y)
    common: dict[str, list] = {}
    for p in pages:
        for o in p.get("opps") or []:
            common.setdefault(o["title"], []).append((p["url"], o["ms"]))
    for title, hits in sorted(common.items(), key=lambda kv: -len(kv[1])):
        if len(hits) >= COMMON_PAGES:
            add("common_" + title, "medium", f"Sửa chung: {title}",
                f"Gặp ở {len(hits)} trang, tiết kiệm khoảng {sum(ms for _, ms in hits) / len(hits) / 1000:.1f} giây mỗi "
                "trang. Sửa ở giao diện / plugin chung là cả website nhanh lên.".replace(".", ",", 1),
                [u for u, _ in hits])
    failed = [p["url"] for p in pages if p.get("error")]
    if failed:
        add("failed", "info", "Trang chưa đo được lần này", f"{len(failed)} trang, lần kiểm tra sau sẽ thử lại.", failed)
    order = {"high": 0, "medium": 1, "info": 2, "ok": 3}
    return sorted(out, key=lambda c: order[c["level"]])
