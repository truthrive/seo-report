"""Quản trị AI: cài đặt từng tác vụ AI (bật/tắt, nhà cung cấp / model, lịch tự chạy), trần số lần gọi tự động mỗi
tháng và nhật ký mọi lần gọi AI. Lưu ở file dữ liệu chính (dùng chung mọi dự án):

- ai_settings (scope, key, value): scope "" = mặc định chung; scope = địa chỉ website = riêng dự án đó (chỉ đổi
  "enabled" / "auto" của từng tác vụ, phần còn lại theo chung).
- ai_calls: mỗi lần gọi AI — lúc nào, website, tác vụ, bấm tay hay lịch, ai, nhà cung cấp / model, được hay lỗi, credit.

Trang: web_ai_admin.py (Quản trị › AI, chỉ Owner). Lịch chạy: ai_auto.py."""
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone

# tác vụ -> (tên, mô tả, loại lịch: None = chỉ bấm tay, "weekly" = các ngày trong tuần, "monthly" = ngày trong tháng)
TASKS = {
    "brief": ("Bản tin Tổng quan", "AI chọn tối đa 5 việc nên làm trước từ các tín hiệu của tool, ở đầu trang Tổng quan.",
              "weekly"),
    "report_week": ("Nhận xét báo cáo tuần", "AI viết nháp nhận xét tuần vừa xong; team đọc rồi bấm Dùng bản nháp.",
                    "weekly"),
    "report_month": ("Nhận xét báo cáo tháng", "AI viết nháp nhận xét và kế hoạch tháng sau khi hết tháng.", "monthly"),
    "aio_answer": ("Đoạn trả lời AI Overview", "Viết đoạn trả lời để được AI Overview trích; tự chạy cho từ khóa vừa "
                   "mất trích.", "weekly"),
    "kw_strategy": ("Chiến lược SEO", "Lập chiến lược cho nhóm từ khóa ở Ý tưởng từ khóa.", None),
    "kw_brief": ("Brief từ khóa", "Viết dàn ý bài cho một từ khóa ở Tổng quan từ khóa.", None),
    "kpi_import": ("Đọc sheet cam kết KPI", "AI đọc bảng cam kết trong sheet đã gắn, điền sẵn vào trang Sửa cam kết.",
                   None),
    "kpi_insight": ("Nhận định KPI", "AI nhận định tiến độ từng KPI, dự đoán tháng cam kết kế tiếp và việc nên làm.",
                    None),
}
DAYS = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")
DEFAULTS = {
    "brief": {"enabled": True, "provider": "auto", "model": "", "auto": True, "days": [0, 1, 2, 3, 4, 5], "time": "07:00"},
    "report_week": {"enabled": True, "provider": "auto", "model": "", "auto": True, "days": [0], "time": "08:00"},
    "report_month": {"enabled": True, "provider": "auto", "model": "", "auto": True, "day": 1, "time": "08:00"},
    "aio_answer": {"enabled": True, "provider": "auto", "model": "", "auto": True, "days": [0, 1, 2, 3, 4, 5],
                   "time": "09:00", "limit": 5},
    "kw_strategy": {"enabled": True, "provider": "auto", "model": ""},
    "kw_brief": {"enabled": True, "provider": "auto", "model": ""},
    "kpi_import": {"enabled": True, "provider": "auto", "model": ""},
    "kpi_insight": {"enabled": True, "provider": "auto", "model": ""},
}
CAP_DEFAULT = 300
ACTION_TASK = {"ai_aio": "aio_answer", "ai_report": "report_week", "ai_brief": "brief", "ai_plan": "kw_strategy",
               "ai_kwbrief": "kw_brief", "ai_kpi": "kpi_import",
               "ai_kpi_insight": "kpi_insight"}  # mã credit -> tác vụ

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_settings (scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY (scope, key));
CREATE TABLE IF NOT EXISTS ai_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, month TEXT NOT NULL,
  site TEXT NOT NULL DEFAULT '', task TEXT NOT NULL, trigger TEXT NOT NULL, user TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', ok INTEGER NOT NULL, error TEXT NOT NULL DEFAULT '',
  credits INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ai_calls_month ON ai_calls (month, trigger);
"""
_APP: dict = {"path": None}


def set_app_db(path) -> None:
    _APP["path"] = path


def _connect():
    if not _APP["path"]:
        from . import points as PT  # cùng file dữ liệu chính với credit
        _APP["path"] = PT._APP_DB.get("path")
    if not _APP["path"]:
        raise RuntimeError("chưa đặt file dữ liệu chính cho cài đặt AI")
    from . import db
    return closing(db.connect(_APP["path"]))


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


# ---------------------------------------------------------------- cài đặt

def _get(con, scope: str, key: str):
    row = con.execute("SELECT value FROM ai_settings WHERE scope = ? AND key = ?", (scope, key)).fetchone()
    return json.loads(row[0]) if row else None


def _put(con, scope: str, key: str, value) -> None:
    with con:
        if value is None:
            con.execute("DELETE FROM ai_settings WHERE scope = ? AND key = ?", (scope, key))
        else:
            con.execute("INSERT OR REPLACE INTO ai_settings (scope, key, value) VALUES (?, ?, ?)",
                        (scope, key, json.dumps(value, ensure_ascii=False)))


def task_settings(con, task: str) -> dict:
    """Cài đặt chung của một tác vụ (mặc định + phần Owner đã đổi)."""
    ensure(con)
    return {**DEFAULTS[task], **(_get(con, "", f"task:{task}") or {})}


def save_task(con, task: str, values: dict) -> None:
    ensure(con)
    keep = {k: v for k, v in values.items() if k in DEFAULTS[task]}
    _put(con, "", f"task:{task}", {**task_settings(con, task), **keep})


def override(con, site: str, task: str) -> dict:
    """Phần riêng của dự án: {"enabled": bool?, "auto": bool?} (thiếu = theo chung)."""
    ensure(con)
    return _get(con, site, f"task:{task}") or {}


def save_override(con, site: str, task: str, key: str, value: bool | None) -> None:
    cur = override(con, site, task)
    if value is None:
        cur.pop(key, None)
    else:
        cur[key] = bool(value)
    _put(con, site, f"task:{task}", cur or None)


def effective(con, site: str, task: str) -> dict:
    """Cài đặt áp cho một website: chung + phần riêng của dự án."""
    return {**task_settings(con, task), **override(con, site, task)}


def enabled(site: str, task: str) -> bool:
    """Tác vụ có được dùng ở website này không (nút AI ẩn khi tắt). Lỗi đọc: coi như bật."""
    try:
        with _connect() as con:
            return bool(effective(con, site, task)["enabled"])
    except Exception:  # noqa: BLE001
        return True


def cap(con) -> int:
    ensure(con)
    v = _get(con, "", "cap")
    return CAP_DEFAULT if v is None else int(v)


def set_cap(con, value: int) -> None:
    ensure(con)
    _put(con, "", "cap", max(0, int(value)))


MAX_FALLBACKS = 5


def fallbacks(con) -> list[dict]:
    """Các model dự phòng theo thứ tự thử (chung mọi tác vụ, mọi dự án): [{"provider", "model"}]."""
    ensure(con)
    v = _get(con, "", "fallbacks")
    if v is None:  # bản cũ chỉ lưu một model dự phòng
        old = _get(con, "", "fallback")
        v = [old] if old else []
    return [x for x in v if isinstance(x, dict) and x.get("provider")]


def set_fallbacks(con, items: list[dict]) -> list[dict]:
    """Lưu danh sách (bỏ dòng trống, bỏ dòng trùng, tối đa MAX_FALLBACKS)."""
    ensure(con)
    out, seen = [], set()
    for x in items or []:
        p, m = (x.get("provider") or "").strip(), (x.get("model") or "").strip()
        if not p or (p, m) in seen:
            continue
        seen.add((p, m))
        out.append({"provider": p, "model": m})
    out = out[:MAX_FALLBACKS]
    _put(con, "", "fallbacks", out)
    return out


def fallback(con) -> dict | None:
    """Model dự phòng đầu tiên (giữ cho chỗ cũ)."""
    v = fallbacks(con)
    return v[0] if v else None


def set_fallback(con, provider: str | None, model: str = "") -> None:
    set_fallbacks(con, [{"provider": provider, "model": model}] if provider else [])


def block_status(con) -> dict | None:
    """Lần gần nhất model chính bị chặn (giá mới / hết hạn mức / khóa sai): {"at", "name", "model", "error",
    "fallback"}; None khi model chính đã gọi lại được."""
    ensure(con)
    return _get(con, "", "ai_block")


def note_block(prov: dict, error: str, fb: dict | None) -> None:
    try:
        with _connect() as con:
            ensure(con)
            _put(con, "", "ai_block", {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                       "name": prov.get("name", ""), "model": prov.get("model", ""),
                                       "error": (error or "")[:300],
                                       "fallback": f"{fb['name']} · {fb['model']}" if fb else None})
    except Exception:  # noqa: BLE001
        pass


def clear_block(prov: dict) -> None:
    """Model chính gọi được lại: bỏ cảnh báo (chỉ khi cảnh báo là của chính model này)."""
    try:
        with _connect() as con:
            b = block_status(con)
            if b and b.get("model") == prov.get("model") and b.get("name") == prov.get("name"):
                _put(con, "", "ai_block", None)
    except Exception:  # noqa: BLE001
        pass


def choose_provider(cfg, task: str | None) -> dict | None:
    """Nhà cung cấp / model Owner chọn cho tác vụ; None = để tool tự chọn (thứ tự mặc định)."""
    if not task or task not in DEFAULTS:
        return None
    try:
        with _connect() as con:
            st = task_settings(con, task)
    except Exception:  # noqa: BLE001
        return None
    if st.get("provider", "auto") == "auto" and not st.get("model"):
        return None
    return {"provider": st.get("provider", "auto"), "model": (st.get("model") or "").strip()}


# ---------------------------------------------------------------- nhật ký

def log_call(site: str, task: str, trigger: str, user: str, prov: dict | None, ok: bool, error: str = "",
             credits: int = 0, when: datetime | None = None) -> None:
    """Ghi một lần gọi AI (không làm hỏng tác vụ nếu ghi lỗi)."""
    when = when or datetime.now(timezone.utc)
    try:
        with _connect() as con:
            ensure(con)
            with con:
                con.execute("INSERT INTO ai_calls (at, month, site, task, trigger, user, provider, model, ok, error, "
                            "credits) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (when.isoformat(timespec="seconds"), when.astimezone().strftime("%Y-%m"), site, task,
                             trigger, str(user or ""), (prov or {}).get("name", ""), (prov or {}).get("model", ""),
                             int(bool(ok)), (error or "")[:300], int(credits or 0)))
    except Exception:  # noqa: BLE001
        pass


def auto_used(con, month: str | None = None) -> int:
    """Số lần gọi AI tự động (lịch) trong tháng, mọi dự án: so với trần."""
    ensure(con)
    month = month or date.today().strftime("%Y-%m")
    return con.execute("SELECT COUNT(*) FROM ai_calls WHERE month = ? AND trigger = 'auto'", (month,)).fetchone()[0]


def cap_reached() -> bool:
    try:
        with _connect() as con:
            c = cap(con)
            return c > 0 and auto_used(con) >= c or c == 0
    except Exception:  # noqa: BLE001
        return False


def calls(con, month: str, site: str | None = None, limit: int = 500) -> list[dict]:
    ensure(con)
    q = "SELECT at, site, task, trigger, user, provider, model, ok, error, credits FROM ai_calls WHERE month = ?"
    args: list = [month]
    if site:
        q += " AND site = ?"
        args.append(site)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    keys = ("at", "site", "task", "trigger", "user", "provider", "model", "ok", "error", "credits")
    return [dict(zip(keys, r)) for r in con.execute(q, args)]


def summary(con, month: str) -> dict:
    ensure(con)
    row = con.execute("SELECT COUNT(*), SUM(trigger = 'auto'), SUM(ok = 0), SUM(credits) FROM ai_calls WHERE month = ?",
                      (month,)).fetchone()
    by = {t: n for t, n in con.execute("SELECT task, COUNT(*) FROM ai_calls WHERE month = ? GROUP BY task", (month,))}
    return {"total": row[0] or 0, "auto": row[1] or 0, "errors": row[2] or 0, "credits": row[3] or 0, "by_task": by}
