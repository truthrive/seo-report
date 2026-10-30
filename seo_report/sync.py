"""Đồng bộ dữ liệu GSC về SQLite: lấy bù lịch sử và lấy lại các ngày gần đây."""
import time
from datetime import date, timedelta

from . import db, gsc
from .config import Config


def days_to_fetch(cfg: Config, done: set[str], today: date, backfill: bool) -> list[str]:
    end = today - timedelta(days=1)
    refetch_from = today - timedelta(days=cfg.refetch_days)
    # GSC giữ khoảng 16 tháng; ngày cũ hơn API trả về rỗng, không lỗi.
    start = today - timedelta(days=cfg.backfill_months * 30) if backfill else refetch_from
    days = []
    d = start
    while d <= end:
        # Ngày gần đây luôn lấy lại vì GSC còn cập nhật số liệu; ngày cũ chỉ lấy nếu chưa có (bù ngày máy tắt).
        if d >= refetch_from or d.isoformat() not in done:
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def sync(cfg: Config, service, con, backfill: bool = False, today: date | None = None,
         log=print, sleep=time.sleep) -> int:
    today = today or date.today()
    done = db.fetched_days(con, cfg.site_url)
    if not backfill and not done:
        log("Chưa có dữ liệu lịch sử, chuyển sang lấy bù toàn bộ.")
        backfill = True
    days = days_to_fetch(cfg, done, today, backfill)
    for i, day in enumerate(days, 1):
        page_rows = gsc.query_day(service, cfg.site_url, day, ["page"], sleep=sleep)
        query_rows = gsc.query_day(service, cfg.site_url, day, ["page", "query"], sleep=sleep)
        db.replace_day(con, cfg.site_url, day, page_rows, query_rows)
        log(f"[{i}/{len(days)}] {day}: {len(page_rows)} URL, {len(query_rows)} URL × query")
    # Tổng theo property: một lần gọi cho cả khoảng. Lần đầu (bảng trống) lấy toàn bộ 16 tháng.
    has_totals = con.execute("SELECT 1 FROM gsc_site_daily WHERE site = ? LIMIT 1", (cfg.site_url,)).fetchone()
    start = min(days) if days and has_totals else (today - timedelta(days=cfg.backfill_months * 30)).isoformat()
    totals = gsc.query_site_totals(service, cfg.site_url, start, (today - timedelta(days=1)).isoformat(), sleep=sleep)
    db.save_site_totals(con, cfg.site_url, totals)
    log(f"Tổng theo property: {len(totals)} ngày.")
    return len(days)
