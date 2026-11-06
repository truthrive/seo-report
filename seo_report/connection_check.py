"""Kiểm tra kết nối của dự án với Google Search Console (và GA4, qua ga4.stream_check): property có trong tài khoản
Google của tool không, quyền đủ đọc số không, có đúng website không, có số gần đây không.

Mỗi kết quả: {"status": ok | warn | error, "title": câu ngắn, "message": giải thích / cách sửa}.
"""
from .projects import domain

READ_LEVELS = {"siteOwner": "Chủ sở hữu", "siteFullUser": "Toàn quyền", "siteRestrictedUser": "Quyền hạn chế"}


def gsc_check(site_url: str, sites: list[dict]) -> dict:
    """Đối chiếu property GSC của dự án với danh sách property tài khoản Google đọc được (sites().list()).
    - ok: có property đúng y hệt, quyền đọc được số.
    - error / unverified: có trong danh sách nhưng tài khoản chưa được xác minh / chưa được cấp quyền.
    - error / other_form: không có đúng dạng đã nhập nhưng có property khác của cùng tên miền (sc-domain ↔ https://):
      gợi ý dạng đúng.
    - error / missing: tài khoản Google không thấy property nào của tên miền này."""
    want = domain(site_url)
    exact = next((s for s in sites if s.get("siteUrl") == site_url), None)
    if exact:
        level = exact.get("permissionLevel", "")
        if level in READ_LEVELS:
            return {"status": "ok", "code": "ok", "title": f"Search Console: đúng property ({READ_LEVELS[level]})",
                    "message": f"Tài khoản Google của tool đọc được số của {site_url}."}
        return {"status": "error", "code": "unverified", "title": "Search Console: chưa được cấp quyền",
                "message": f"Property {site_url} có trong tài khoản nhưng ở trạng thái chưa xác minh / chưa có quyền. "
                           "Vào Search Console → Cài đặt → Người dùng và quyền, thêm email tài khoản Google của tool."}
    same = [s["siteUrl"] for s in sites if domain(s.get("siteUrl", "")) == want
            and s.get("permissionLevel") in READ_LEVELS]
    if same:
        return {"status": "error", "code": "other_form", "title": "Search Console: sai dạng property",
                "message": f"Không có property {site_url}, nhưng có {', '.join(same)}. Sửa ô Property Search Console "
                           f"của dự án thành {same[0]}.", "suggest": same[0]}
    return {"status": "error", "code": "missing", "title": "Search Console: không thấy property",
            "message": f"Tài khoản Google của tool không thấy property nào của {want}. Thêm email tài khoản Google của "
                       "tool vào Search Console của website (Cài đặt → Người dùng và quyền)."}


def ga4_stream_result(chk: dict) -> dict:
    """Kết quả ga4.stream_check → một dòng kiểm tra."""
    status = {"ok": "ok", "mixed": "warn"}.get(chk["status"], "error")
    title = {"ok": "GA4: đúng website", "mixed": "GA4: lẫn website khác", "mismatch": "GA4: sai website",
             "no_stream": "GA4: chưa có luồng dữ liệu web"}[chk["status"]]
    return {"status": status, "code": chk["status"], "title": title, "message": chk["message"]}


def ga4_data_check(sessions: int, days: int) -> dict:
    if not sessions:
        return {"status": "warn", "code": "no_data", "title": f"GA4: không có phiên truy cập {days} ngày qua",
                "message": "Đọc được property nhưng chưa có số: mã GA4 chưa gắn lên website, hoặc gắn sai luồng."}
    return {"status": "ok", "code": "ok", "title": f"GA4: có số {days} ngày qua",
            "message": f"{sessions:,} phiên truy cập.".replace(",", ".")}


def run(base, project: dict, today=None) -> list[dict]:
    """Chạy mọi kiểm tra cho một dự án (gọi Google API, vài giây). Lỗi ở bước nào thì ghi thành một dòng lỗi, các
    bước sau vẫn chạy."""
    from datetime import date, timedelta

    from googleapiclient.errors import HttpError

    from . import auth, ga4, gsc
    today = today or date.today()
    out: list[dict] = []
    try:
        creds = auth.get_credentials(base, need=auth.ALL_SCOPES)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        return [{"status": "error", "code": "login", "title": "Chưa đăng nhập Google",
                 "message": f"Tool chưa có quyền Google ({e}). Kết nối lại ở màn Cài đặt tích hợp."}]
    site = project["site_url"]
    # ---- Search Console ----
    try:
        svc = auth.build_service(creds)
        r = gsc_check(site, gsc.list_sites(svc))
        out.append(r)
        if r["status"] == "ok":  # số GSC trễ 2–3 ngày: lấy 7 ngày kết thúc 3 ngày trước
            end = today - timedelta(days=3)
            rows = gsc.query_site_totals(svc, site, (end - timedelta(days=6)).isoformat(), end.isoformat())
            out.append(gsc_data_check(rows, 7))
    except (Exception, SystemExit) as e:  # noqa: BLE001
        out.append({"status": "error", "code": "gsc_error", "title": "Search Console: lỗi khi đọc",
                    "message": str(e)[:300]})
    # ---- GA4 ----
    prop = project.get("ga4_property") or ""
    if not prop:
        out.append({"status": "warn", "code": "no_ga4", "title": "GA4: chưa gắn property",
                    "message": "Gắn property GA4 ở nút Sửa cấu hình để có số truy cập, kênh AI…"})
        return out
    try:
        admin = auth.build_ga4_admin(creds)
        info = ga4.property_info(admin, prop)
        out.append({"status": "ok", "code": "access", "title": f"GA4: đọc được property “{info['name']}”",
                    "message": f"{prop} · múi giờ {info['timezone']}."})
        out.append(ga4_stream_result(ga4.stream_check(site, ga4.web_streams(admin, prop))))
        rows, _ = ga4.channel_overview(auth.build_ga4_data(creds), prop, "7daysAgo", "yesterday")
        out.append(ga4_data_check(sum(v for _, v in rows), 7))
    except HttpError as e:
        out.append({"status": "error", "code": "ga4_access", "title": "GA4: không đọc được property",
                    "message": ga4.explain(e) + " Thêm email tài khoản Google của tool vào property (quyền Người xem)."})
    except (Exception, SystemExit) as e:  # noqa: BLE001
        out.append({"status": "error", "code": "ga4_error", "title": "GA4: lỗi khi đọc", "message": str(e)[:300]})
    return out


def gsc_data_check(rows: list[dict], days: int) -> dict:
    """Có số Search Console gần đây không (rows: kết quả searchanalytics theo ngày)."""
    clicks = sum(r.get("clicks", 0) for r in rows)
    impressions = sum(r.get("impressions", 0) for r in rows)
    if not rows or not impressions:
        return {"status": "warn", "code": "no_data", "title": f"Search Console: không có số {days} ngày qua",
                "message": "Kết nối được nhưng chưa có lượt hiển thị nào: website mới, bị chặn index, hoặc property "
                           "chưa thu số (property mới thêm cần vài ngày)."}
    return {"status": "ok", "code": "ok", "title": f"Search Console: có số {days} ngày qua",
            "message": f"{impressions:,} lượt hiển thị, {clicks:,} click.".replace(",", ".")}
