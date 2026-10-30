"""Phân loại phiên truy cập từ AI assistant (spec AI Search & GEO §5).

Hai chỗ dùng cùng một định nghĩa:
- `classify()` (Python) cho từng dòng nguồn/medium/kênh: dùng ở bảng nguồn, đối soát, test.
- `ga4_filter()` dựng `dimensionFilter` của GA4 Data API để GA4 tự lọc và tự tính KPI tổng (không cộng % ở phía tool).
Test bắt buộc hai cách cho cùng kết quả trên cùng dữ liệu mẫu.

Quyết định đã chốt (docs/REPO_DISCOVERY_REPORT.md §8b): kênh native GA4 là "AI Assistant"; tên ghi tắt (gemini,
perplexity…) được tính khi khớp đúng tên; traffic có medium trả phí (ví dụ chatgpt / paid) không tính là AI organic.
"""
import re
from dataclasses import dataclass, field

VERSION = "v1"

AI_ASSISTANTS, ORGANIC_SEARCH, ORGANIC_SOCIAL, OTHER = "AI_ASSISTANTS", "ORGANIC_SEARCH", "ORGANIC_SOCIAL", "OTHER"
NATIVE, FALLBACK = "NATIVE", "FALLBACK_REFERRER"
HYBRID, NATIVE_ONLY, FALLBACK_ONLY = "HYBRID", "NATIVE", "FALLBACK_ONLY"

# Tên kênh native: Google dùng "AI Assistant"; nhận cả dạng số nhiều như spec.
NATIVE_CHANNELS = ("AI Assistant", "AI Assistants")

# Host → nguồn con. Khớp đúng host hoặc subdomain của host (không khớp chuỗi con: evilchatgpt.com bị loại).
DEFAULT_HOSTS = {
    "chatgpt.com": "CHATGPT", "chat.openai.com": "CHATGPT",
    "gemini.google.com": "GEMINI",
    "claude.ai": "CLAUDE",
    "perplexity.ai": "PERPLEXITY",
    "copilot.microsoft.com": "COPILOT", "copilot.com": "COPILOT",
    "deepseek.com": "DEEPSEEK",
    "grok.com": "GROK",
}
# Tên ghi tắt (UTM utm_source=gemini…): chỉ khớp nguyên tên.
DEFAULT_ALIASES = {"chatgpt": "CHATGPT", "openai": "CHATGPT", "gemini": "GEMINI", "claude": "CLAUDE",
                   "perplexity": "PERPLEXITY", "copilot": "COPILOT", "deepseek": "DEEPSEEK", "grok": "GROK"}
# Medium trả phí theo cách GA4 định nghĩa kênh paid: chứa "cp", hoặc ppc / retargeting / bắt đầu bằng "paid".
PAID_MEDIUM_REGEX = r"^(.*cp.*|ppc|retargeting|paid.*)$"


@dataclass
class Allowlist:
    hosts: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOSTS))
    aliases: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ALIASES))

    def subsource(self, source: str) -> str | None:
        s = (source or "").strip().lower().removeprefix("www.")
        if s in self.aliases:
            return self.aliases[s]
        for host, sub in self.hosts.items():
            if s == host or s.endswith("." + host):
                return sub
        return None


def is_paid(medium: str) -> bool:
    return re.fullmatch(PAID_MEDIUM_REGEX, (medium or "").strip().lower()) is not None


def is_native_ai(channel: str) -> bool:
    return (channel or "").strip().lower() in {c.lower() for c in NATIVE_CHANNELS}


def classify(source: str, medium: str, channel: str, mode: str = HYBRID,
             allow: Allowlist | None = None) -> tuple[str, str | None, str | None]:
    """(nhãn, nguồn con, cách nhận diện). Một phiên chỉ có một nhãn: native được ưu tiên, fallback không cộng thêm."""
    allow = allow or Allowlist()
    sub = allow.subsource(source)
    if mode != FALLBACK_ONLY and is_native_ai(channel):
        return AI_ASSISTANTS, sub or "OTHER_AI", NATIVE
    if mode != NATIVE_ONLY and sub and not is_paid(medium):
        return AI_ASSISTANTS, sub, FALLBACK
    ch = (channel or "").strip().lower()
    if ch == "organic search":
        return ORGANIC_SEARCH, None, None
    if ch == "organic social":
        return ORGANIC_SOCIAL, None, None
    return OTHER, None, None


# ---- Bộ lọc GA4 tương đương ----

def _source_regex(allow: Allowlist, only: str | None = None) -> str:
    hosts = [h for h, s in allow.hosts.items() if only in (None, s)]
    aliases = [a for a, s in allow.aliases.items() if only in (None, s)]
    parts = []
    if hosts:
        parts.append(r"(?:[a-z0-9-]+\.)*(?:" + "|".join(re.escape(h) for h in hosts) + ")")
    if aliases:
        parts.append("(?:" + "|".join(re.escape(a) for a in aliases) + ")")
    return "^(?:" + "|".join(parts) + ")$" if parts else "^$a"  # "^$a" không khớp gì


def _f(field_name: str, **kw) -> dict:
    return {"filter": {"fieldName": field_name, **kw}}


def native_filter() -> dict:
    return _f("sessionDefaultChannelGroup", inListFilter={"values": list(NATIVE_CHANNELS), "caseSensitive": False})


def fallback_filter(allow: Allowlist, only: str | None = None) -> dict:
    return {"andGroup": {"expressions": [
        _f("sessionSource", stringFilter={"value": _source_regex(allow, only), "matchType": "FULL_REGEXP",
                                          "caseSensitive": False}),
        {"notExpression": _f("sessionMedium", stringFilter={"value": PAID_MEDIUM_REGEX, "matchType": "FULL_REGEXP",
                                                             "caseSensitive": False})},
    ]}}


def ga4_filter(mode: str = HYBRID, allow: Allowlist | None = None, only: str | None = None) -> dict:
    """dimensionFilter chọn đúng các phiên AI theo chế độ. `only` = một nguồn con (CHATGPT…) để tính KPI riêng nó."""
    allow = allow or Allowlist()
    if mode == NATIVE_ONLY and only is None:
        return native_filter()
    if mode == FALLBACK_ONLY:
        return fallback_filter(allow, only)
    if only is None:
        return {"orGroup": {"expressions": [native_filter(), fallback_filter(allow)]}}
    # Một nguồn con: phiên native có source thuộc nguồn đó, hoặc phiên fallback của nguồn đó.
    src = _f("sessionSource", stringFilter={"value": _source_regex(allow, only), "matchType": "FULL_REGEXP",
                                            "caseSensitive": False})
    native_of_source = {"andGroup": {"expressions": [native_filter(), src]}}
    if mode == NATIVE_ONLY:
        return native_of_source
    return {"orGroup": {"expressions": [native_of_source, fallback_filter(allow, only)]}}


def paid_ai_filter(allow: Allowlist | None = None) -> dict:
    """Traffic từ nguồn AI nhưng medium trả phí (ví dụ chatgpt / paid): hiện riêng, không tính vào AI organic."""
    allow = allow or Allowlist()
    return {"andGroup": {"expressions": [
        {"notExpression": native_filter()},
        _f("sessionSource", stringFilter={"value": _source_regex(allow), "matchType": "FULL_REGEXP",
                                          "caseSensitive": False}),
        _f("sessionMedium", stringFilter={"value": PAID_MEDIUM_REGEX, "matchType": "FULL_REGEXP",
                                          "caseSensitive": False}),
    ]}}


def channel_filter(*channels: str) -> dict:
    return _f("sessionDefaultChannelGroup", inListFilter={"values": list(channels)})


def and_filters(*exprs: dict | None) -> dict | None:
    exprs = [e for e in exprs if e]
    if not exprs:
        return None
    return exprs[0] if len(exprs) == 1 else {"andGroup": {"expressions": exprs}}
