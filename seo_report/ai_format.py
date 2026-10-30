"""Định dạng số cho module AI Search & GEO (spec §3.8): đếm là số nguyên, rate 0–1 hiện %, thời lượng mm:ss,
None hiện "N/A", thay đổi có dấu. Dùng chung cho giao diện, Excel và báo cáo."""


def n(v) -> str:
    return "N/A" if v is None else f"{v:,.0f}".replace(",", ".")


def pct(v, digits: int = 2) -> str:
    return "N/A" if v is None else f"{v * 100:.{digits}f}%".replace(".", ",")


def mmss(seconds) -> str:
    if seconds is None:
        return "N/A"
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


MIN_BASE = 10  # kỳ trước nhỏ hơn mức này thì % thay đổi dễ gây hiểu lầm (1 → 17 phiên = +1.600%)


def delta_pct(v, base=None) -> str:
    """% thay đổi; None (không có mốc so sánh) hiện trống. Có `base` (số kỳ trước) mà < MIN_BASE thì hiện số kỳ trước
    thay vì %."""
    if base is not None and base < MIN_BASE:
        return f"kỳ trước {n(base)}"
    return "" if v is None else f"{v * 100:+.1f}%".replace(".", ",")


def delta_points(v) -> str:
    """Thay đổi của một tỷ lệ, tính bằng điểm phần trăm."""
    return "" if v is None else f"{v * 100:+.2f} điểm".replace(".", ",")


def per100(v) -> str:
    return "N/A" if v is None else f"{v:.2f}".replace(".", ",")


SOURCE_NAMES = {"CHATGPT": "ChatGPT", "GEMINI": "Gemini", "CLAUDE": "Claude", "PERPLEXITY": "Perplexity",
                "COPILOT": "Copilot", "DEEPSEEK": "DeepSeek", "GROK": "Grok", "OTHER_AI": "AI khác (chưa nhận diện)",
                "Other AI": "AI khác"}

METHOD_NAMES = {"NATIVE": "Kênh AI Assistant của GA4", "FALLBACK_REFERRER": "Nhận diện bổ sung theo nguồn"}

WARNING_TITLES = {
    "INCOMPLETE_PERIOD": "Kỳ chưa trọn", "GA4_THRESHOLDED": "GA4 ẩn bớt dữ liệu", "LOW_SAMPLE_SIZE": "Mẫu nhỏ",
    "NO_BASELINE": "Không có mốc so sánh", "UNMAPPED_AI_SOURCE": "Nguồn AI chưa nhận diện",
    "GA4_TOTAL_DISCREPANCY": "Tổng không khớp", "DATA_NOT_AVAILABLE": "Thiếu dữ liệu",
    "METRIC_INCOMPATIBLE": "Chỉ số không tính được", "API_PERMISSION_DENIED": "Không có quyền GA4",
    "PROPERTY_NOT_FOUND": "Không tìm thấy property", "QUOTA_EXCEEDED": "Hết quota GA4",
    "TIMEZONE_MISMATCH": "Lệch múi giờ GA4/GSC", "URL_MATCH_AMBIGUOUS": "Ghép URL chưa trọn",
}
