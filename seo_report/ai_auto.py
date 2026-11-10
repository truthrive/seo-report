"""Lịch AI tự chạy (chạy nền trong máy chủ web, mỗi 10 phút kiểm tra), theo cài đặt ở Quản trị › AI:

- brief          Bản tin Tổng quan: các ngày / giờ đã chọn (mặc định 7:00 thứ 2–7).
- report_week    Nhận xét báo cáo tuần vừa xong: bản nháp chờ duyệt (mặc định thứ Hai 8:00). Team đã viết nhận xét
                 cho tuần đó thì thôi.
- report_month   Nhận xét + kế hoạch tháng vừa xong: bản nháp chờ duyệt (mặc định ngày 1, 8:00; máy tắt thì chạy bù
                 các ngày sau trong tháng).
- aio_answer     Đoạn trả lời AI Overview cho từ khóa vừa mất trích, chưa có bản nháp; tối đa N từ khóa mỗi lượt.

Quy tắc chung: lỡ giờ (máy tắt) thì chạy bù trong vòng 5 giờ (lịch tuần); AI lỗi thì thử lại sau 1 giờ, tối đa 3 lần;
chạm trần số lần gọi tự động của tháng thì dừng (bấm tay vẫn chạy); không trừ credit của ai; mỗi lần gọi ghi nhật ký
(Quản trị › AI). Lần chạy của từng tác vụ ghi ở bảng ai_auto_runs của file dữ liệu dự án."""
import logging
import time as _time
from contextlib import closing
from datetime import date, datetime, timedelta

from . import ai_settings as AIS

log = logging.getLogger(__name__)

EVERY = 10 * 60
CATCH_UP = timedelta(hours=5)
RETRY_AFTER = 60 * 60
MAX_TRIES = 3
BY = "Lịch tự động"
AUTO_TASKS = ("brief", "report_week", "report_month", "aio_answer")
_FAILS: dict[tuple[str, str, str], tuple[int, float]] = {}


def _hm(s: str) -> tuple[int, int]:
    try:
        h, m = (s or "07:00").split(":")
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except ValueError:
        return 7, 0


def due(now: datetime, st: dict, kind: str, last: str | None) -> bool:
    """Đến lượt chưa. kind "weekly": hôm nay thuộc các ngày đã chọn, đã qua giờ hẹn và chưa quá 5 giờ, hôm nay chưa
    chạy. "monthly": từ ngày đã chọn của tháng (đã qua giờ hẹn nếu đúng ngày đó), tháng này chưa chạy."""
    h, m = _hm(st.get("time", "07:00"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if kind == "monthly":
        day = max(1, min(28, int(st.get("day", 1))))
        if (last or "")[:7] == now.strftime("%Y-%m") or now.day < day:
            return False
        return now.day > day or now >= at
    return (now.weekday() in (st.get("days") or []) and at <= now < at + CATCH_UP
            and last != now.date().isoformat())


def _ensure(con) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS ai_auto_runs (task TEXT NOT NULL, day TEXT NOT NULL, at TEXT NOT NULL, "
                "result TEXT NOT NULL, PRIMARY KEY (task, day))")


def last_run(con, task: str) -> str | None:
    _ensure(con)
    return con.execute("SELECT MAX(day) FROM ai_auto_runs WHERE task = ?", (task,)).fetchone()[0]


def mark(con, task: str, today: date, result: str) -> None:
    _ensure(con)
    with con:
        con.execute("INSERT OR REPLACE INTO ai_auto_runs (task, day, at, result) VALUES (?, ?, ?, ?)",
                    (task, today.isoformat(), datetime.now().astimezone().isoformat(timespec="seconds"), result))


def runs(con, limit: int = 30) -> list[dict]:
    _ensure(con)
    return [{"task": t, "day": d, "at": a, "result": r} for t, d, a, r in con.execute(
        "SELECT task, day, at, result FROM ai_auto_runs ORDER BY at DESC LIMIT ?", (limit,))]


class CapReached(RuntimeError):
    pass


def _call(cfg, task: str, fn, *args):
    """Một lần gọi AI tự động: kiểm tra trần, chọn nhà cung cấp theo tác vụ, ghi nhật ký. Trả (kết quả, prov)."""
    from . import ai_writer as AW
    if AIS.cap_reached():
        raise CapReached("chạm trần số lần gọi AI tự động của tháng")
    prov = AW.provider(cfg, task)
    try:
        out = fn(*args, prov)
    except Exception as e:
        AIS.log_call(cfg.site_url, task, "auto", BY, prov, False, str(e))
        raise
    AIS.log_call(cfg.site_url, task, "auto", BY, out[1] if isinstance(out, tuple) else prov, True)
    return out


# ---------------------------------------------------------------- từng tác vụ (chạy trong luồng phụ)

def _rep(cfg, connect, month: bool):
    from . import report as RP
    from . import urls as U
    with connect() as c:
        gid = U.ensure_group(c, cfg.site_url)
        rep = RP.build_month(c, cfg, gid, 0, with_ai=False) if month else RP.build(c, cfg, gid, 0, with_ai=False)
    return gid, rep


def run_brief(cfg, connect) -> str:
    from . import access as A
    from . import ai_brief as B
    from . import ai_writer as AW
    from .web_overview import todo_rows
    gid, rep = _rep(cfg, connect, False)
    todo = todo_rows(cfg, connect, rep, {"group": gid})
    with connect() as c:
        sigs = B.signals(c, cfg, A.User(BY, A.LOCAL), rep, todo)
        saved = AW.latest(c, cfg.site_url, B.KIND, "overview")
    if not sigs:
        return "không có tín hiệu"
    if saved and saved.get("fingerprint") == B.fingerprint(sigs):
        return "tín hiệu không đổi"
    out, used = _call(cfg, "brief", lambda p: B.run(cfg, sigs, p))
    with connect() as c:
        AW.save(c, cfg.site_url, B.KIND, "overview", out, used, BY)
    return f"đã cập nhật ({len(out['items'])} việc)"


def run_report(cfg, connect, month: bool) -> str:
    from . import ai_writer as AW
    from . import report as RP
    _, rep = _rep(cfg, connect, month)
    key = str(RP.note_key(rep))
    with connect() as c:
        if RP.get_note(c, cfg.site_url, RP.note_key(rep)):
            return "team đã viết nhận xét"
        if AW.latest(c, cfg.site_url, "report_note", key):
            return "đã có bản nháp"
    task = "report_month" if month else "report_week"
    out, used = _call(cfg, task, lambda p: AW.write_report(cfg, rep, p))
    with connect() as c:
        AW.save(c, cfg.site_url, "report_note", key, out, used, BY)
    return f"đã viết nháp ({RP.period_text(rep.kind, rep.week)})"


def run_aio(cfg, connect, limit: int) -> str:
    from . import aio as AO
    from . import ai_writer as AW
    with connect() as c:
        a = AO.audit(c, cfg)
        AW.ensure(c)
        have = {r[0] for r in c.execute("SELECT DISTINCT ref FROM ai_drafts WHERE site = ? AND kind = 'aio_answer'",
                                        (cfg.site_url,))}
        bs = AO.brands(c, cfg)
    lost = next((g for g in a["groups"] if g["key"] == "lost_cite"), {"items": [], "title": ""})
    todo = [x for x in lost["items"] if str(x["id"]) not in have][:max(0, int(limit))]
    if not todo:
        return "không có từ khóa mới mất trích"
    brand = bs[0]["name"] if bs else ""
    done = 0
    for x in todo:
        r = x["row"]
        out, used = _call(cfg, "aio_answer", lambda p, x=x, r=r: AW.write_aio(
            cfg, x["keyword"], brand, x["url"], r.get("text", ""), r.get("refs", []), lost["title"], p))
        with connect() as c:
            AW.save(c, cfg.site_url, "aio_answer", str(x["id"]), out, used, BY)
        done += 1
    return f"đã viết {done} đoạn trả lời"


def run_task(task: str, cfg, connect, st: dict) -> str:
    if task == "brief":
        return run_brief(cfg, connect)
    if task in ("report_week", "report_month"):
        return run_report(cfg, connect, task == "report_month")
    if task == "aio_answer":
        return run_aio(cfg, connect, st.get("limit", 5))
    return "không hỗ trợ"


# ---------------------------------------------------------------- vòng lặp

async def auto_loop(base) -> None:
    import asyncio

    from nicegui import run

    from . import db
    from . import projects as PJ
    await asyncio.sleep(90)  # để máy chủ khởi động xong
    while True:
        now = datetime.now()
        try:
            with closing(db.connect(base.db_path)) as c:
                projects = PJ.list_projects(c)
            for p in projects:
                cfg = PJ.config_for(base, p)

                def connect(cfg=cfg):
                    return closing(db.connect(cfg.db_path))
                for task in AUTO_TASKS:
                    try:
                        with AIS._connect() as ac:
                            st = AIS.effective(ac, cfg.site_url, task)
                    except Exception:  # noqa: BLE001
                        continue
                    if not (st.get("enabled") and st.get("auto")):
                        continue
                    kind = AIS.TASKS[task][2]
                    with connect() as c:
                        if not due(now, st, kind, last_run(c, task)):
                            continue
                    key = (cfg.site_url, task, now.date().isoformat())
                    n, at = _FAILS.get(key, (0, 0.0))
                    if n and _time.time() - at < RETRY_AFTER:
                        continue
                    try:
                        res = await run.io_bound(run_task, task, cfg, connect, st)
                        _FAILS.pop(key, None)
                        with connect() as c:
                            mark(c, task, now.date(), res)
                        log.info("AI tự chạy %s %s: %s", cfg.site_url, task, res)
                    except CapReached as e:
                        log.info("AI tự chạy %s %s: %s", cfg.site_url, task, e)
                    except Exception as e:  # noqa: BLE001 — lỗi một tác vụ không dừng các tác vụ khác
                        log.warning("AI tự chạy %s %s lỗi (lần %d): %s", cfg.site_url, task, n + 1, e)
                        _FAILS[key] = (n + 1, _time.time())
                        if n + 1 >= MAX_TRIES:
                            with connect() as c:
                                mark(c, task, now.date(), f"lỗi: {str(e)[:200]}")
        except Exception as e:  # noqa: BLE001
            log.warning("Lịch AI lỗi: %s", e)
        await asyncio.sleep(EVERY)
