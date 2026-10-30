"""Lệnh dòng lệnh: login, sync, stats."""
import argparse
import sys

from . import db
from .config import load_config


def cmd_login(cfg) -> None:
    from . import auth, gsc

    from googleapiclient.errors import HttpError

    from . import ga4

    creds = auth.get_credentials(cfg, interactive=True, need=auth.SCOPES)
    sites = gsc.list_sites(auth.build_service(creds))
    print("Đăng nhập thành công. Search Console property truy cập được:")
    for s in sites:
        print(f"  {s['siteUrl']}  ({s['permissionLevel']})")
    if not any(s["siteUrl"] == cfg.site_url for s in sites):
        print(f"\nCảnh báo: site_url = '{cfg.site_url}' không có trong danh sách trên. "
              "Sửa config.toml cho đúng một dòng ở trên.")
    if auth.DRIVE_SCOPE not in (creds.scopes or []):
        print("\nCHƯA có quyền Google Drive (để lưu Google Sheets / Slides / PDF): ô 'Xem, sửa, tạo và xóa các tệp "
              "Google Drive mà bạn dùng với ứng dụng này' chưa được tích. Chạy lại lệnh login nếu cần chức năng này.")
    if auth.GA4_SCOPE not in (creds.scopes or []):
        print("\nCHƯA có quyền đọc Google Analytics: trên màn hình đồng ý của Google, ô 'Xem dữ liệu Google "
              "Analytics' chưa được tích. Chạy lại lệnh login và tích đủ cả hai ô.")
        return
    try:
        props = ga4.list_properties(auth.build_ga4_admin(creds))
    except HttpError as e:
        print(f"\nChưa liệt kê được GA4 property: {ga4.explain(e)}")
        return
    print("\nGA4 property truy cập được (dán dòng properties/… vào ga4_property trong config.toml):")
    for p in props:
        print(f"  {p['property']}  {p['name']}  (tài khoản: {p['account']})")
    if cfg.ga4_property and not any(p["property"] == cfg.ga4_property for p in props):
        print(f"\nCảnh báo: ga4_property = '{cfg.ga4_property}' không có trong danh sách trên.")


def cmd_ga4_check(cfg) -> None:
    """Kiểm tra kết nối GA4 cho module AI Search & GEO: quyền, múi giờ, trường cần dùng, tên kênh AI, key events."""
    from datetime import date, timedelta

    from googleapiclient.errors import HttpError

    from . import auth, ga4

    if not cfg.ga4_property:
        raise SystemExit("Chưa có ga4_property trong config.toml. Chạy login để xem danh sách property.")
    creds = auth.get_credentials(cfg, need=auth.ALL_SCOPES)
    admin, data = auth.build_ga4_admin(creds), auth.build_ga4_data(creds)
    try:
        info = ga4.property_info(admin, cfg.ga4_property)
        print(f"Property: {info['name']} ({cfg.ga4_property}) · múi giờ {info['timezone']} · tiền tệ {info['currency']}")
        print("Key events đang đánh dấu:", ", ".join(ga4.key_events(admin, cfg.ga4_property)) or "(chưa có)")
        missing = ga4.metadata_check(data, cfg.ga4_property)
        if missing["missing_dimensions"] or missing["missing_metrics"]:
            print("THIẾU trường spec cần:", missing)
        else:
            print("Metadata: đủ mọi dimension và metric spec cần.")
        end = date.today() - timedelta(days=1)
        rows, quota = ga4.channel_overview(data, cfg.ga4_property, (end - timedelta(days=27)).isoformat(),
                                           end.isoformat())
        print(f"Sessions theo kênh, 28 ngày đến {end:%d/%m/%Y}:")
        for name, n in rows:
            mark = "  ← kênh AI" if name.lower().startswith("ai assistant") else ""
            print(f"  {n:>8,}  {name}{mark}".replace(",", "."))
        tokens = quota.get("tokensPerDay", {})
        if tokens:
            print(f"Quota GA4 hôm nay: đã dùng {tokens.get('consumed')} token, còn {tokens.get('remaining')}.")
    except HttpError as e:
        raise SystemExit(ga4.explain(e))


def cmd_sync(cfg, backfill: bool) -> None:
    from googleapiclient.errors import HttpError

    from . import auth
    from .sync import sync

    service = auth.build_service(auth.get_credentials(cfg))
    con = db.connect(cfg.db_path)
    try:
        n = sync(cfg, service, con, backfill=backfill)
    except HttpError as e:
        if e.resp.status == 403:
            raise SystemExit(
                f"Tài khoản không có quyền trên '{cfg.site_url}'. Chạy lệnh login để xem danh sách "
                "property đúng, rồi sửa site_url trong config.toml."
            )
        raise
    print(f"Xong: đã lấy {n} ngày.")
    from . import urls
    new = urls.assign_urls(con, cfg.site_url)
    if new:
        print(f"Đã gắn {new} dòng GSC mới vào URL báo cáo.")


def cmd_classify(cfg, limit: int | None) -> None:
    from . import crawl, urls

    con = db.connect(cfg.db_path)
    urls.assign_urls(con, cfg.site_url)
    n = crawl.classify_pending(con, cfg.site_url, limit=limit)
    print(f"Xong: đã phân loại {n} URL bằng schema.")
    for type_, count in urls.type_summary(con, cfg.site_url):
        print(f"  {count:>6}  {type_}")


def cmd_rank(cfg, wait_minutes: int) -> None:
    from . import keywords, rank

    creds = rank.load_credentials(cfg.dataforseo_secret)
    if not creds:
        print(f"Bỏ qua check rank: chưa điền API login/password trong {cfg.dataforseo_secret}.")
        return
    client = rank.DataForSEO(*creds)
    con = db.connect(cfg.db_path)
    end = keywords.latest_date(con, cfg.site_url)
    try:
        rank.run(con, cfg.site_url, cfg.rank, client, end, wait_minutes=wait_minutes,
                 log=lambda m: print(m, flush=True))
    except RuntimeError as e:
        hint = " Vào https://app.dataforseo.com/ để xác minh tài khoản." if "40104" in str(e) else ""
        raise SystemExit(f"Check rank thất bại: {e}{hint}")
    st = rank.budget_status(con, cfg.site_url, cfg.rank, end)
    print(f"Lịch: {rank.describe_schedule(rank.get_schedule(con))}. Ngân sách: đã dùng {rank.usd(st['spent'], 3)} USD "
          f"tháng này; {st['stars']} keyword ước tính {rank.usd(st['estimate'])}/{st['budget']:.0f} USD/tháng. "
          f"Số dư DataForSEO: {client.balance()} USD.")


def cmd_index(cfg, limit: int) -> None:
    from datetime import date

    from . import auth, indexing

    creds = auth.get_credentials(cfg)
    con = db.connect(cfg.db_path)
    new = indexing.sync_sitemap(con, cfg.site_url, date.today())
    print(f"Sitemap: {new} URL mới.")
    indexing.run(con, cfg.site_url, lambda: auth.build_service(creds), daily_limit=limit,
                 log=lambda m: print(m, flush=True))
    for coverage, n in indexing.summary(con, cfg.site_url):
        print(f"  {n:>6}  {coverage}")


def cmd_ai_summary(cfg, days: int) -> None:
    """In nhanh số liệu traffic AI (để đối soát với GA4 UI); giao diện đầy đủ ở màn AI Search & GEO."""
    from datetime import date, timedelta

    from . import ai_analytics, auth, ga4, ga4_query

    if not cfg.ga4_property:
        raise SystemExit("Chưa có ga4_property trong config.toml.")
    creds = auth.get_credentials(cfg, need=auth.ALL_SCOPES)
    con = db.connect(cfg.db_path)
    client = ga4_query.GA4Client(auth.build_ga4_data(creds), cfg.ga4_property, con)
    ai = ai_analytics.AIAnalytics(client)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    pct = lambda v: "N/A" if v is None else f"{v * 100:.2f}%".replace(".", ",")
    n = lambda v: f"{v:,}".replace(",", ".")

    s = ai.summary(start, end)
    print(f"AI Search & GEO · {start:%d/%m/%Y}–{end:%d/%m/%Y} · chế độ {s['classification']['mode']} "
          f"· trạng thái {s['status']}")
    if s["status"] == "ERROR":
        raise SystemExit(s["warnings"][0]["message"])
    a, d = s["data"]["ai"], s["data"]["aiDeltas"] or {}
    t = a["avgEngagementTimePerSession"]
    print(f"  Phiên AI: {n(a['sessions'])} ({pct(d.get('sessions'))} so với kỳ trước) · engaged {n(a['engagedSessions'])}"
          f" · engagement rate {pct(a['engagementRate'])}")
    print(f"  Thời gian tương tác TB/phiên: {'N/A' if t is None else f'{int(t // 60):02d}:{int(t % 60):02d}'}"
          f" · key events {a['keyEvents']} · session key event rate {pct(a['sessionKeyEventRate'])}"
          f" · key events/100 phiên {a['keyEventsPer100Sessions'] or 0:.2f}".replace(".", ","))
    sh = s["data"]["share"]
    print(f"  Tỷ lệ AI: {pct(sh['ofAllSessions'])} tổng site ({n(sh['allSessions'])} phiên) · "
          f"{pct(sh['ofOrganicBase'])} nhóm organic ({n(sh['organicBase'])} phiên)")
    print(f"  AI trả phí (không tính): {n(s['data']['paidAi']['sessions'])} phiên")
    for name, c in s["data"]["channels"].items():
        print(f"  {name}: {n(c['sessions'])} phiên · engagement {pct(c['engagementRate'])} · "
              f"key event rate {pct(c['sessionKeyEventRate'])}")
    for w in s["warnings"]:
        print(f"  ⚠ {w['code']}: {w['message']}")

    src = ai.sources(start, end)
    print("\nNguồn AI:")
    for r in src["data"]["sources"]:
        print(f"  {r['source']:<11} {n(r['sessions']):>6} phiên · engagement {pct(r['engagementRate'])} · "
              f"key events {r['keyEvents']} · {'/'.join(r['methods'])}")
    events = ga4.key_events(auth.build_ga4_admin(creds), cfg.ga4_property)
    print("\nKey events từ phiên AI:")
    for e in ai.key_events(start, end, events)["data"]["events"]:
        print(f"  {e['event']:<16} {e['keyEvents']:>4} · tỷ lệ phiên {pct(e['sessionKeyEventRate'])}")
    print("\nTop 10 trang đích:")
    for r in ai.landing_pages(start, end, limit=10)["data"]["rows"]:
        print(f"  {r['sessions']:>5}  {pct(r['engagementRate']):>7}  {r['landingPage']}")
    print("\nTop 5 quốc gia:", ", ".join(f"{r['country']} {r['sessions']}"
                                          for r in ai.countries(start, end, limit=5)["data"]["rows"]))


def cmd_daily(cfg) -> None:
    """Chạy bởi Task Scheduler qua pythonw (không có cửa sổ): lấy dữ liệu rồi phân loại URL mới, ghi log ra file."""
    import traceback
    from datetime import datetime

    log = open(cfg.db_path.parent / "sync.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    print(f"===== {datetime.now():%Y-%m-%d %H:%M} =====")
    try:
        cmd_sync(cfg, backfill=False)
        try:
            cmd_rank(cfg, wait_minutes=15)
        except (Exception, SystemExit):  # lỗi check rank không được chặn các việc sau
            traceback.print_exc()
        try:
            from . import keywords, volume
            with db.connect(cfg.db_path) as con:
                volume.refresh(con, cfg.site_url, cfg, keywords.latest_date(con, cfg.site_url),
                               log=lambda m: print(m, flush=True))
        except Exception:
            traceback.print_exc()
        try:  # báo cáo công việc: chép sheet OKR / Weekly Task về, ghi trạng thái hôm nay
            from . import okr
            if okr.sheet_id(cfg.okr.sheet):
                with db.connect(cfg.db_path) as con:
                    print("OKR:", okr.sync(con, cfg), flush=True)
        except (Exception, SystemExit):
            traceback.print_exc()
        try:
            cmd_index(cfg, limit=1500)
        except Exception:
            traceback.print_exc()
        cmd_classify(cfg, limit=300)
    except SystemExit as e:
        print(e)
        raise
    except Exception:
        traceback.print_exc()
        raise


def cmd_web(cfg, port: int, show: bool) -> None:
    from .web import run

    run(cfg, port, show)


def _ask_secret(prompt: str) -> str:
    """Gõ mật khẩu, mỗi ký tự hiện thành *. Backspace xóa, Enter xong, Ctrl+C hủy. Ngoài Windows dùng getpass."""
    try:
        import msvcrt
    except ImportError:
        import getpass
        return getpass.getpass(prompt)
    print(prompt, end="", flush=True)
    chars = []
    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            print()
            return "".join(chars)
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\b":
            if chars:
                chars.pop()
                print("\b \b", end="", flush=True)
        elif ch in ("\x00", "\xe0"):
            msvcrt.getwch()  # phím mũi tên / chức năng: bỏ qua
        else:
            chars.append(ch)
            print("*", end="", flush=True)


def cmd_export_static(cfg, out: str) -> None:
    """Bản xem tĩnh để đưa lên Vercel. Mật khẩu gõ ở đây (không hiện ra màn hình, không lưu ở đâu); biến môi trường
    SEO_STATIC_PASSWORD chỉ dùng khi chạy tự động."""
    import os
    from pathlib import Path

    from . import static_site

    pw = os.environ.get("SEO_STATIC_PASSWORD") or ""
    if not pw:
        print("Mỗi ký tự gõ vào hiện thành *. Gõ xong bấm Enter.")
        pw = _ask_secret("Đặt mật khẩu xem báo cáo (ít nhất 10 ký tự): ")
        if len(pw) < 10:
            raise SystemExit(f"Mật khẩu mới có {len(pw)} ký tự, cần ít nhất 10. Chưa xuất gì, chạy lại lệnh.")
        if _ask_secret("Gõ lại mật khẩu: ") != pw:
            raise SystemExit("Hai lần gõ không khớp. Chưa xuất gì, chạy lại lệnh.")
    print("Đang lấy số liệu (GSC, GA4, rank, OKR)…")
    path = static_site.export(cfg, Path(out), pw)
    print(f"Xong: {path}")
    print(f"Đẩy lên Vercel:  npx vercel deploy {out} --prod")


def cmd_stats(cfg) -> None:
    con = db.connect(cfg.db_path)
    site = cfg.site_url
    first, last, days = con.execute(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM gsc_fetch_log WHERE site = ?", (site,)
    ).fetchone()
    if not days:
        print("Chưa có dữ liệu. Chạy: python -m seo_report sync")
        return
    pages, = con.execute("SELECT COUNT(*) FROM pages WHERE site = ?", (site,)).fetchone()
    queries, = con.execute(
        "SELECT COUNT(*) FROM gsc_query_daily WHERE page_id IN (SELECT id FROM pages WHERE site = ?)", (site,)
    ).fetchone()
    print(f"Site: {site}")
    print(f"Dữ liệu từ {first} đến {last} ({days} ngày)")
    print(f"{pages:,} URL có impression; {queries:,} dòng URL × query".replace(",", "."))
    print("\nTop 10 URL theo click, 7 ngày gần nhất:")
    rows = con.execute(
        """SELECT page, SUM(clicks) c, SUM(impressions) i FROM v_page_daily
           WHERE site = ? AND date > date(?, '-7 day') GROUP BY page ORDER BY c DESC LIMIT 10""",
        (site, last),
    )
    for page, c, i in rows:
        print(f"  {c:>7,}  {i:>9,}  {page}".replace(",", "."))


def cmd_migrate(cfg) -> None:
    import sqlite3

    new = cfg.db_path
    old = new.with_name(new.stem + "_v1" + new.suffix)
    if old.exists():
        raise SystemExit(f"Đã có {old}. Kiểm tra lại rồi xóa file đó trước khi chuyển lần nữa.")
    new.rename(old)
    print(f"Đang chuyển {old.name} sang cách lưu mới, có thể mất vài phút...")
    db.migrate_v1(old, new)

    def totals(path, page_table, query_table):
        c = sqlite3.connect(path)
        r = (c.execute(f"SELECT COUNT(*), SUM(clicks) FROM {page_table}").fetchone()
             + c.execute(f"SELECT COUNT(*), SUM(clicks) FROM {query_table}").fetchone())
        c.close()
        return r

    before = totals(old, "gsc_page_daily", "gsc_query_daily")
    after = totals(new, "gsc_page_daily", "gsc_query_daily")
    print(f"Trước: {before}\nSau:   {after}")
    if before != after:
        raise SystemExit(f"Số dòng hoặc tổng click không khớp. Giữ nguyên {old} để kiểm tra.")
    old.unlink()
    for suffix in ("-wal", "-shm"):
        old.with_name(old.name + suffix).unlink(missing_ok=True)
    print(f"Khớp. Đã xóa file cũ. Dung lượng mới: {new.stat().st_size / 1024 / 1024:.0f} MB")


def main(argv=None) -> None:
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m seo_report")
    p.add_argument("--config", default="config.toml")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="Đăng nhập Google, liệt kê property GSC và GA4")
    sub.add_parser("ga4-check", help="Kiểm tra kết nối GA4 cho module AI Search & GEO")
    ais = sub.add_parser("ai-summary", help="In số liệu traffic AI từ GA4 (đối soát)")
    ais.add_argument("--days", type=int, default=28)
    s = sub.add_parser("sync", help="Lấy dữ liệu GSC về máy")
    s.add_argument("--backfill", action="store_true", help="Lấy bù toàn bộ lịch sử (tối đa 16 tháng)")
    sub.add_parser("stats", help="Xem tóm tắt dữ liệu đã lưu")
    sub.add_parser("migrate", help="Chuyển file dữ liệu cách lưu cũ sang cách lưu mới")
    c = sub.add_parser("classify", help="Mở các trang chưa phân loại và đọc schema để biết loại trang")
    c.add_argument("--limit", type=int, help="Số trang tối đa cho lần chạy này")
    sub.add_parser("daily", help="Việc hằng ngày: sync + check rank + phân loại URL mới (dùng cho Task Scheduler)")
    ix = sub.add_parser("index", help="Đọc sitemap và check index các URL đến hạn (URL Inspection API)")
    ix.add_argument("--limit", type=int, default=1500, help="Số URL tối đa mỗi ngày (quota Google ~2.000)")
    r = sub.add_parser("rank", help="Check rank các keyword ★ đến hạn")
    r.add_argument("--wait", type=int, default=15, help="Số phút tối đa chờ kết quả")
    w = sub.add_parser("web", help="Mở giao diện trên trình duyệt")
    w.add_argument("--port", type=int, default=8080)
    w.add_argument("--no-open", action="store_true", help="Không tự mở trình duyệt")
    st = sub.add_parser("export-static", help="Xuất bản xem tĩnh có mật khẩu để đưa lên Vercel")
    st.add_argument("--out", default="dist", help="Thư mục xuất (bị xóa và tạo lại)")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    if args.cmd == "login":
        cmd_login(cfg)
    elif args.cmd == "ga4-check":
        cmd_ga4_check(cfg)
    elif args.cmd == "ai-summary":
        cmd_ai_summary(cfg, args.days)
    elif args.cmd == "sync":
        cmd_sync(cfg, args.backfill)
    elif args.cmd == "migrate":
        cmd_migrate(cfg)
    elif args.cmd == "classify":
        cmd_classify(cfg, args.limit)
    elif args.cmd == "index":
        cmd_index(cfg, args.limit)
    elif args.cmd == "rank":
        cmd_rank(cfg, args.wait)
    elif args.cmd == "daily":
        cmd_daily(cfg)
    elif args.cmd == "web":
        cmd_web(cfg, args.port, not args.no_open)
    elif args.cmd == "export-static":
        cmd_export_static(cfg, args.out)
    else:
        cmd_stats(cfg)
