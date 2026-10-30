"""Ai đang dùng tool và được làm gì.

Tool chỉ nghe ở 127.0.0.1. Người ngoài vào bằng một trong hai đường:
- Tailscale Serve: người xem cài app Tailscale, đăng nhập Google; Tailscale chuyển yêu cầu về máy này kèm header
  Tailscale-User-Login (email) và X-Forwarded-For (IP trong mạng Tailscale).
- Cloudflare Tunnel + Access: Access bắt đăng nhập (mã gửi qua email) rồi chuyển yêu cầu về, kèm email và một JWT có
  chữ ký; luôn có header Cf-Ray.
Yêu cầu không có các header trên là mở thẳng trên máy này, được coi là chủ máy (quyền sửa). Yêu cầu từ ngoài mà không
nhận ra người dùng thì bị chặn.

Quyền: email trong `editors` được sửa (check rank tốn tiền, sửa nhóm URL/keyword, nhập file, nhận xét, đồng bộ, xuất
lên Drive); email trong `viewers` chỉ xem và tải file về máy; email khác bị chặn (dù Access đã cho qua).
"""
import json
import time
import urllib.request
from dataclasses import dataclass, field

LOCAL, EDITOR, VIEWER = "local", "editor", "viewer"


@dataclass
class AccessSettings:
    editors: list[str] = field(default_factory=list)
    viewers: list[str] = field(default_factory=list)
    team_domain: str = ""  # ví dụ "tamduc.cloudflareaccess.com": có thì kiểm tra chữ ký JWT của Access
    aud: str = ""  # Application Audience (AUD) tag của ứng dụng trong Cloudflare Access


class User(str):
    """Tên hiển thị (email hoặc tên tài khoản máy) kèm vai trò; dùng như chuỗi ở mọi chỗ ghi nhật ký."""
    role: str = LOCAL

    def __new__(cls, name: str, role: str):
        obj = super().__new__(cls, name)
        obj.role = role
        return obj


def can_edit(user) -> bool:
    return getattr(user, "role", LOCAL) in (LOCAL, EDITOR)


def identify(headers, settings: AccessSettings, local_name: str) -> tuple[User | None, str]:
    """(người dùng, lý do bị chặn). `headers` là header của yêu cầu (không phân biệt hoa thường)."""
    ts_login = headers.get("tailscale-user-login", "")
    if not headers.get("cf-ray"):
        if not ts_login and not headers.get("x-forwarded-for"):
            return User(local_name, LOCAL), ""
        return _by_email(ts_login, settings, "Chưa đăng nhập Tailscale")
    token = headers.get("cf-access-jwt-assertion", "")
    email = ""
    if settings.team_domain and settings.aud:
        try:
            email = _verify(token, settings)
        except Exception as e:  # noqa: BLE001
            return None, f"Phiên đăng nhập Cloudflare không hợp lệ ({e})"
    else:
        email = headers.get("cf-access-authenticated-user-email", "")
    return _by_email(email, settings, "Chưa đăng nhập qua Cloudflare Access")


def _by_email(email: str, settings: AccessSettings, missing: str) -> tuple[User | None, str]:
    email = email.strip().lower()
    if not email:
        return None, missing
    if email in _norm(settings.editors):
        return User(email, EDITOR), ""
    if email in _norm(settings.viewers):
        return User(email, VIEWER), ""
    return None, f"{email} chưa được cấp quyền dùng tool"


def _norm(emails) -> set[str]:
    return {e.strip().lower() for e in emails if e.strip()}


_CERTS: dict = {"at": 0.0, "keys": {}}


def _verify(token: str, s: AccessSettings) -> str:
    """Kiểm tra JWT của Cloudflare Access (RS256, khóa công khai lấy từ <team>/cdn-cgi/access/certs, đúng AUD, còn
    hạn) và trả về email trong đó."""
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    def b64(part: str) -> bytes:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

    if token.count(".") != 2:
        raise ValueError("thiếu token")
    head_b, body_b, sig_b = token.split(".")
    head, body = json.loads(b64(head_b)), json.loads(b64(body_b))
    if head.get("alg") != "RS256":
        raise ValueError("thuật toán lạ")
    if time.time() - _CERTS["at"] > 3600 or head.get("kid") not in _CERTS["keys"]:
        url = f"https://{s.team_domain.strip().removeprefix('https://').strip('/')}/cdn-cgi/access/certs"
        data = json.loads(urllib.request.urlopen(url, timeout=10).read())
        _CERTS["keys"] = {k["kid"]: k for k in data.get("keys", [])}
        _CERTS["at"] = time.time()
    jwk = _CERTS["keys"].get(head.get("kid"))
    if not jwk:
        raise ValueError("không thấy khóa ký")
    key = rsa.RSAPublicNumbers(int.from_bytes(b64(jwk["e"]), "big"), int.from_bytes(b64(jwk["n"]), "big")).public_key()
    key.verify(b64(sig_b), f"{head_b}.{body_b}".encode(), padding.PKCS1v15(), hashes.SHA256())
    aud = body.get("aud")
    if s.aud not in (aud if isinstance(aud, list) else [aud]):
        raise ValueError("sai AUD")
    if body.get("exp", 0) < time.time():
        raise ValueError("hết hạn")
    return body.get("email", "")
