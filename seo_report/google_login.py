"""Đăng nhập vào tool bằng tài khoản Google (OpenID Connect, chỉ xin quyền đọc email).

Khác với "Kết nối Google" ở màn Cài đặt (tool đọc Search Console, GA4… bằng một tài khoản chung), đây chỉ là cách người
dùng chứng minh họ là ai. Cần một OAuth client loại "Web application" (Google Cloud Console) có Authorized redirect
URI = <Địa chỉ tool>/auth/google; Client ID và Client secret lưu ở màn Cài đặt tích hợp (secrets/google_login.toml).

Bảo vệ:
- state ngẫu nhiên lưu trong phiên của chính trình duyệt đó (chặn gắn đăng nhập của người khác vào trình duyệt mình);
- PKCE (code_verifier) và nonce gắn với ID token;
- ID token kiểm chữ ký, aud = Client ID, iss là Google, còn hạn (google.oauth2.id_token); email phải đã xác minh.
- Địa chỉ quay về lấy từ cài đặt "Địa chỉ tool", không lấy từ header Host của yêu cầu.
"""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

from . import integrations as I

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALLBACK = "/auth/google"
TTL = 600  # giây: bấm nút xong phải đăng nhập Google trong 10 phút


def creds(cfg) -> dict:
    return I.load(cfg, "google_login")


def ready(cfg) -> bool:
    return I.configured(cfg, "google_login")


def redirect_uri(public_url: str) -> str:
    return (public_url or "").strip().rstrip("/") + CALLBACK


def start(cfg, public_url: str, next_url: str = "/") -> tuple[str, dict]:
    """(link trang đăng nhập Google, phiên chờ để lưu vào app.storage.user)."""
    c = creds(cfg)
    if not c.get("client_id") or not public_url:
        raise ValueError("Đăng nhập Google chưa được cài đặt")
    pending = {"state": secrets.token_urlsafe(24), "nonce": secrets.token_urlsafe(24),
               "verifier": secrets.token_urlsafe(48), "at": time.time(), "next": next_url or "/"}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(pending["verifier"].encode()).digest()).decode().rstrip("=")
    q = {"client_id": c["client_id"], "redirect_uri": redirect_uri(public_url), "response_type": "code",
         "scope": "openid email", "state": pending["state"], "nonce": pending["nonce"],
         "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"}
    return AUTH_URL + "?" + urlencode(q), pending


def _post(url: str, data: dict) -> dict:
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    req = Request(url, data=urlencode(data).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")
    except HTTPError as e:
        try:
            return json.loads(e.read() or b"{}") | {"_status": e.code}
        except ValueError:
            return {"error": f"http_{e.code}", "_status": e.code}


def _verify(token: str, client_id: str) -> dict:
    from google.auth.transport import requests as gr
    from google.oauth2 import id_token
    return id_token.verify_oauth2_token(token, gr.Request(), client_id)


def finish(cfg, public_url: str, pending: dict | None, query: dict, post=_post, verify=_verify) -> str:
    """Google gọi về: kiểm state, đổi mã lấy ID token, kiểm token; trả email đã xác minh. Lỗi: ValueError (câu cho
    người dùng)."""
    if query.get("error"):
        raise ValueError("Bạn đã hủy đăng nhập Google" if query["error"] == "access_denied"
                         else "Google báo lỗi khi đăng nhập")
    if not pending or not query.get("state") or not secrets.compare_digest(str(pending.get("state", "")),
                                                                           str(query["state"])):
        raise ValueError("Phiên đăng nhập không khớp. Bấm “Đăng nhập bằng Google” lại.")
    if time.time() - float(pending.get("at") or 0) > TTL:
        raise ValueError("Phiên đăng nhập đã hết hạn. Bấm “Đăng nhập bằng Google” lại.")
    c = creds(cfg)
    tok = post(TOKEN_URL, {"code": query.get("code", ""), "client_id": c.get("client_id", ""),
                           "client_secret": c.get("client_secret", ""), "redirect_uri": redirect_uri(public_url),
                           "grant_type": "authorization_code", "code_verifier": pending["verifier"]})
    if not tok.get("id_token"):
        print(f"Đăng nhập Google: đổi mã không thành công ({tok.get('error')})")
        raise ValueError("Không đăng nhập được bằng Google. Thử lại hoặc báo người quản lý tool.")
    try:
        info = verify(tok["id_token"], c.get("client_id", ""))
    except Exception as e:  # noqa: BLE001
        print(f"Đăng nhập Google: ID token không hợp lệ ({e})")
        raise ValueError("Không đăng nhập được bằng Google. Thử lại hoặc báo người quản lý tool.") from None
    if info.get("nonce") != pending.get("nonce"):
        raise ValueError("Phiên đăng nhập không khớp. Bấm “Đăng nhập bằng Google” lại.")
    if not info.get("email") or not info.get("email_verified"):
        raise ValueError("Tài khoản Google này chưa xác minh email")
    return str(info["email"]).strip().lower()


def test_client(cfg, v: dict, post=_post) -> tuple[bool, str]:
    """Kiểm tra Client ID / secret mà không cần người dùng đăng nhập: đổi một mã giả. Google trả invalid_grant khi
    client đúng (mã giả bị từ chối), invalid_client khi Client ID / secret sai."""
    cid = (v.get("client_id") or "").strip()
    if not cid.endswith(".apps.googleusercontent.com"):
        return False, "Client ID phải có dạng …apps.googleusercontent.com"
    if not (v.get("client_secret") or "").strip():
        return False, "Chưa nhập Client secret"
    # Làm mới bằng refresh token giả: Google kiểm Client ID / secret trước (sai → invalid_client), đúng thì mới báo
    # token giả (invalid_grant). Không dùng mã đăng nhập giả: Google chặn theo chính sách (invalid_request).
    r = post(TOKEN_URL, {"refresh_token": "1//kiem-tra", "client_id": cid,
                         "client_secret": v.get("client_secret", "").strip(), "grant_type": "refresh_token"})
    err = r.get("error", "")
    if err == "invalid_client" or err == "unauthorized_client":
        return False, "Client ID hoặc Client secret không đúng"
    if err == "invalid_grant":
        return True, "Client ID và Client secret dùng được"
    return False, f"Google báo lỗi: {err or 'không rõ'}"
