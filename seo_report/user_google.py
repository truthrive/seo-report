"""Kết nối Google của từng người (Member trở lên): tool đọc Search Console / GA4 bằng chính tài khoản Google của họ để
thêm website riêng vào tool.

- Dùng chung OAuth client "Web application" của Đăng nhập bằng Google (secrets/google_login.toml). Địa chỉ quay về:
  <Địa chỉ tool>/oauth/google/me.
- Chỉ xin quyền đọc: Search Console, Google Analytics, email (biết đã kết nối tài khoản nào).
- Token mỗi người một file trong secrets/user_tokens/ (tên file là mã băm email, không lộ email).
- Website người đó thêm: dự án có settings.google_owner = email tool của họ. projects.config_for đổi token_path sang
  token của người đó, nên mọi chỗ lấy số (lịch hằng ngày, trang) tự dùng đúng tài khoản Google.
- Tính năng tốn tiền (DataForSEO, AI) trên website đó tắt cho đến khi Owner / Admin bật (settings.paid_ok).
"""
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from . import google_login as GL

CALLBACK = "/oauth/google/me"
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email",
          "https://www.googleapis.com/auth/webmasters.readonly",
          "https://www.googleapis.com/auth/analytics.readonly"]
_FLOWS: dict[str, tuple[object, float, str]] = {}  # state → (Flow, lúc tạo, email tool của người bấm)

SCHEMA = """CREATE TABLE IF NOT EXISTS user_google (
  email TEXT PRIMARY KEY, google_email TEXT NOT NULL DEFAULT '', connected_at TEXT NOT NULL);"""


def token_path(base, email: str) -> Path:
    h = hashlib.sha256(str(email).strip().lower().encode()).hexdigest()[:20]
    return Path(base.client_secret).parent / "user_tokens" / f"{h}.json"


def client_config(base) -> dict:
    c = GL.creds(base)
    if not (c.get("client_id") and c.get("client_secret")):
        raise ValueError("Chưa cài Đăng nhập bằng Google (Client ID / secret) ở Cài đặt tích hợp")
    return {"web": {"client_id": c["client_id"], "client_secret": c["client_secret"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"}}


def ensure(con) -> None:
    con.executescript(SCHEMA)


def status(con, email: str) -> dict | None:
    ensure(con)
    r = con.execute("SELECT google_email, connected_at FROM user_google WHERE email = ?",
                    (str(email).lower(),)).fetchone()
    return {"google_email": r[0], "connected_at": r[1]} if r else None


def start(base, public_url: str, email: str) -> str:
    from google_auth_oauthlib.flow import Flow
    if not public_url:
        raise ValueError("Chưa có Địa chỉ tool ở Cài đặt tích hợp")
    flow = Flow.from_client_config(client_config(base), scopes=SCOPES,
                                   redirect_uri=public_url.rstrip("/") + CALLBACK, autogenerate_code_verifier=True)
    url, state = flow.authorization_url(access_type="offline", prompt="select_account consent",
                                        state=secrets.token_urlsafe(24))
    now = time.monotonic()
    for k, (_, t, _e) in list(_FLOWS.items()):
        if now - t > GL.TTL:
            _FLOWS.pop(k, None)
    _FLOWS[state] = (flow, now, str(email).lower())
    return url


def finish(con, base, email: str, state: str, callback_url: str) -> str:
    """Đổi mã lấy token, lưu file token của người này; trả email Google đã kết nối."""
    import os
    item = _FLOWS.pop(state or "", None)
    if not item or time.monotonic() - item[1] > GL.TTL:
        raise ValueError("Phiên kết nối Google đã hết hạn. Bấm Kết nối lại.")
    if item[2] != str(email).lower():  # phiên bắt đầu bởi người khác (không cùng tài khoản tool)
        raise ValueError("Phiên kết nối không khớp tài khoản đang đăng nhập.")
    flow = item[0]
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    if callback_url.startswith("http://"):  # sau proxy (Cloudflare) yêu cầu đến máy là http
        callback_url = "https://" + callback_url.removeprefix("http://")
    flow.fetch_token(authorization_response=callback_url)
    creds = flow.credentials
    if not creds.refresh_token:
        raise ValueError("Google không trả mã làm mới. Bấm Kết nối lại.")
    granted = set(creds.scopes or [])
    if not {SCOPES[2], SCOPES[3]} & granted:
        raise ValueError("Bạn chưa tích quyền Search Console / Analytics. Bấm Kết nối lại và tích đủ các ô.")
    g_email = ""
    if getattr(creds, "id_token", None):
        from google.auth.transport import requests as gr
        from google.oauth2 import id_token
        try:
            g_email = str(id_token.verify_oauth2_token(creds.id_token, gr.Request(),
                                                       client_config(base)["web"]["client_id"]).get("email", ""))
        except Exception:  # noqa: BLE001
            g_email = ""
    p = token_path(base, email)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(creds.to_json())
    data["scopes"] = [s for s in SCOPES[2:] if s in granted] or data.get("scopes")
    p.write_text(json.dumps(data), encoding="utf-8")
    ensure(con)
    with con:
        con.execute("INSERT OR REPLACE INTO user_google VALUES (?, ?, ?)",
                    (str(email).lower(), g_email.lower(), datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return g_email


def disconnect(con, base, email: str) -> None:
    """Gỡ kết nối: xóa token (thu hồi bên Google nếu được). Website đã thêm giữ lại nhưng ngừng cập nhật số."""
    p = token_path(base, email)
    if p.exists():
        try:
            tok = json.loads(p.read_text(encoding="utf-8")).get("refresh_token")
            if tok:
                from urllib.parse import urlencode
                from urllib.request import Request, urlopen
                urlopen(Request("https://oauth2.googleapis.com/revoke", data=urlencode({"token": tok}).encode()),
                        timeout=10).close()
        except Exception:  # noqa: BLE001  (thu hồi không được thì vẫn xóa file)
            pass
        p.unlink(missing_ok=True)
    ensure(con)
    with con:
        con.execute("DELETE FROM user_google WHERE email = ?", (str(email).lower(),))


def user_config(base, email: str):
    """Cấu hình dùng token Google của người này (liệt kê property, lấy số)."""
    from dataclasses import replace
    return replace(base, token_path=token_path(base, email))


def my_properties(base, email: str) -> tuple[dict, dict]:
    """(property GSC, property GA4) tài khoản Google của người này xem được."""
    from . import auth, ga4, gsc
    from . import projects as PJ
    creds = auth.get_credentials(user_config(base, email), need=(auth.GSC_SCOPE,))
    sites = gsc.list_sites(auth.build_service(creds))
    try:
        props = ga4.list_properties(auth.build_ga4_admin(creds))
    except Exception:  # noqa: BLE001  (không cấp quyền GA4: vẫn thêm được website chỉ có GSC)
        props = []
    return ({s["siteUrl"]: s["siteUrl"] for s in sorted(sites, key=lambda s: PJ.domain(s["siteUrl"]))},
            {p["property"]: f"{p['name']} · {p['account']} ({p['property'].split('/')[-1]})" for p in props})


def add_site(con, base, email: str, name: str, site_url: str, ga4_property: str = "") -> dict:
    """Thêm website của người này: dự án riêng (người thêm + Owner / Admin thấy), tính năng tốn tiền tắt."""
    from . import access as A
    from . import projects as PJ
    p = PJ.create(con, base, {"name": name, "site_url": site_url, "ga4_property": ga4_property,
                              "rank_budget_usd": 0, "rank_paused": True}, str(email))
    s = {**p["settings"], "google_owner": str(email).lower(), "paid_ok": False}
    con.execute("UPDATE projects SET settings = ? WHERE slug = ?", (json.dumps(s, ensure_ascii=False), p["slug"]))
    con.commit()
    A.set_member(con, str(email).lower(), p["slug"], A.EDITOR, str(email))
    return PJ.get(con, p["slug"])


def my_sites(con, email: str) -> list[dict]:
    from . import projects as PJ
    return [p for p in PJ.list_projects(con) if p["settings"].get("google_owner") == str(email).lower()]


def set_paid(con, slug: str, on: bool, by: str) -> None:
    """Owner / Admin cho phép (hoặc tắt) tính năng tốn tiền trên website người dùng tự thêm."""
    from . import projects as PJ
    p = PJ.get(con, slug)
    if not p or p["slug"] != slug:
        raise ValueError("Không có dự án này")
    s = {**p["settings"], "paid_ok": bool(on)}
    con.execute("UPDATE projects SET settings = ?, updated_at = ?, updated_by = ? WHERE slug = ?",
                (json.dumps(s, ensure_ascii=False), datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 str(by), slug))
    con.commit()


# Tác vụ tốn tiền (DataForSEO / AI): website người dùng tự thêm chỉ chạy khi Owner / Admin cho phép
PAID_ACTIONS = {"rank", "aio", "serp", "backlink", "research", "overview", "volume", "kg", "backlink_gap",
                "backlink_gap_links", "backlink_gap_multi"}


def is_paid(action: str) -> bool:
    return action in PAID_ACTIONS or action.startswith("ai_")


def blocked(cfg, action: str) -> bool:
    return bool(getattr(cfg, "google_owner", "")) and not getattr(cfg, "paid_ok", True) and is_paid(action)
