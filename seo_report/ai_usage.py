"""Nhật ký token của mỗi lần gọi AI (để xem chi phí AI trên trang Ngân sách).

Lớp gọi AI (ai_http.complete) đọc số token nhà cung cấp trả kèm câu trả lời; ai_http.ask ghi một dòng cho mỗi lần hỏi
thành công: tác vụ, website, người chạy, cổng (key_name), model, số lượt gọi thật (kể cả gọi lại / dự phòng), token
vào / ra. Lỗi khi ghi không làm hỏng tác vụ AI.

Tiền ước tính tính lúc xem, theo bảng giá cổng ghi kèm từng model (ví dụ "input 1200 / output 4800 VND"): tool coi là
giá cho 1 triệu token. Cổng không ghi rõ đơn vị nên chỉ là ước tính, cần đối chiếu với trang hóa đơn của cổng.
"""
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    month TEXT NOT NULL,
    site TEXT NOT NULL DEFAULT '',
    task TEXT NOT NULL DEFAULT '',
    by_user TEXT NOT NULL DEFAULT '',
    key_name TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    calls INTEGER NOT NULL DEFAULT 1,
    in_tok INTEGER NOT NULL DEFAULT 0,
    out_tok INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ai_usage_month ON ai_usage (month);
"""
PER_TOKENS = 1_000_000            # giá cổng ghi được hiểu là cho chừng này token

_LOCAL = threading.local()


def tokens(style: str, data: dict) -> tuple[int, int]:
    """(token vào, token ra) trong phản hồi của nhà cung cấp; không có thì (0, 0)."""
    try:
        if style == "gemini":
            u = data.get("usageMetadata") or {}
            return int(u.get("promptTokenCount") or 0), int(u.get("candidatesTokenCount") or 0)
        if style in ("ollama", "generate"):
            return int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)
        u = data.get("usage") or {}
        return (int(u.get("prompt_tokens") or u.get("input_tokens") or 0),
                int(u.get("completion_tokens") or u.get("output_tokens") or 0))
    except (TypeError, ValueError, AttributeError):
        return 0, 0


def start() -> None:
    """Bắt đầu đếm cho một lần hỏi (ai_http.ask)."""
    _LOCAL.calls = []


def note(model: str, style: str, data: dict) -> None:
    """Một lần gọi nhà cung cấp có phản hồi (ai_http.complete)."""
    calls = getattr(_LOCAL, "calls", None)
    if calls is not None:
        calls.append((model, *tokens(style, data)))


def finish(prov: dict) -> None:
    """Ghi dòng nhật ký cho lần hỏi vừa xong (không bao giờ ném lỗi)."""
    calls = getattr(_LOCAL, "calls", None) or []
    _LOCAL.calls = None
    if not calls:
        return
    try:
        from . import ai_settings as AIS
        from .spend import current
        now = datetime.now(timezone.utc)
        with AIS._connect() as con:
            con.executescript(SCHEMA)
            with con:
                con.execute("INSERT INTO ai_usage (at, month, site, task, by_user, key_name, model, calls, in_tok, "
                            "out_tok) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (now.isoformat(timespec="seconds"), now.strftime("%Y-%m"), prov.get("site") or "",
                             prov.get("task") or "", current(), prov.get("key_name") or "",
                             prov.get("model") or "", len(calls), sum(c[1] for c in calls),
                             sum(c[2] for c in calls)))
    except Exception:  # noqa: BLE001  (không ghi được nhật ký: bỏ qua, tác vụ AI vẫn chạy)
        pass


def by_task(con, month: str) -> list[dict]:
    """Tổng theo tác vụ trong tháng: [{"task", "uses", "calls", "in_tok", "out_tok", "models": {(key, model): (in, out)}}]."""
    con.executescript(SCHEMA)
    out: dict[str, dict] = {}
    for task, key, model, uses, calls, i, o in con.execute(
            "SELECT task, key_name, model, COUNT(*), SUM(calls), SUM(in_tok), SUM(out_tok) FROM ai_usage "
            "WHERE month = ? GROUP BY task, key_name, model", (month,)):
        r = out.setdefault(task, {"task": task, "uses": 0, "calls": 0, "in_tok": 0, "out_tok": 0, "models": {}})
        r["uses"] += uses
        r["calls"] += calls or 0
        r["in_tok"] += i or 0
        r["out_tok"] += o or 0
        r["models"][(key, model)] = (i or 0, o or 0)
    return sorted(out.values(), key=lambda r: -(r["in_tok"] + r["out_tok"]))


def estimate(models: dict, prices: dict) -> tuple[float | None, str]:
    """Tiền ước tính cho {(cổng, model): (token vào, ra)} theo prices {(cổng, model): {"input", "output", "unit"}}.
    Trả (số tiền hoặc None khi không model nào có giá, đơn vị)."""
    total, unit, known = 0.0, "", False
    for km, (i, o) in models.items():
        p = prices.get(km)
        if not p:
            continue
        try:
            a, b = float(p.get("input") or 0), float(p.get("output") or 0)
        except (TypeError, ValueError):
            continue
        known = True
        unit = unit or str(p.get("unit") or "")
        total += i / PER_TOKENS * a + o / PER_TOKENS * b
    return (total if known else None), unit
