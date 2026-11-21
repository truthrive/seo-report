"""Tải URL từ ngoài một cách an toàn (website khách, link do người dùng nhập, sitemap, logo).

Tool chạy trên máy của chủ và có thể chạm tới mạng nội bộ, nên mọi lần tải một địa chỉ do người khác chọn hoặc kiểm soát
đều đi qua đây:
- chỉ http(s); không file:, ftp:, data:; không dùng proxy trong môi trường;
- địa chỉ IP được phân giải MỘT lần, kiểm tra là địa chỉ công khai, rồi nối thẳng tới đúng IP đó (không phân giải lại nên
  DNS rebinding không đổi đích); mọi lần chuyển hướng cũng đi qua cùng kiểm tra vì mỗi chặng là một kết nối mới;
- host phân giải ra bất kỳ IP không công khai nào thì từ chối hết (đóng khi nghi ngờ), kể cả lỗi DNS;
- đọc có trần dung lượng và giải nén gzip có trần (chống "bom" nén).
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.request
import zlib

MAX_BODY = 5_000_000
MAX_REDIRECTS = 5


class NotPublic(OSError):
    """Địa chỉ không phải địa chỉ công khai: tool không tải."""


def is_public_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast


def resolve_public(host: str, port: int) -> list[tuple]:
    """[(family, type, proto, sockaddr)] của host, chỉ khi MỌI địa chỉ phân giải ra đều công khai."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise NotPublic(f"Không phân giải được {host}") from e
    if not infos:
        raise NotPublic(f"Không phân giải được {host}")
    for info in infos:
        if not is_public_ip(info[4][0]):
            raise NotPublic("Địa chỉ không công khai, tool không tải")
    return [(i[0], i[1], i[2], i[4]) for i in infos]


def _connect(host: str, port: int, timeout) -> socket.socket:
    last: OSError | None = None
    for fam, typ, proto, addr in resolve_public(host, port):
        s = socket.socket(fam, typ, proto)
        try:
            if timeout is not None and timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                s.settimeout(timeout)
            s.connect(addr)
            return s
        except OSError as e:
            last = e
            s.close()
    raise last or NotPublic("Không kết nối được")


class _HTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = _connect(self.host, self.port, self.timeout)


class _HTTPS(http.client.HTTPSConnection):
    def connect(self):
        sock = _connect(self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTP, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPS, req, context=self._context)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class _Redirect(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS


def opener(follow: bool = True) -> urllib.request.OpenerDirector:
    """Opener chỉ http(s) tới địa chỉ công khai. follow=False: không tự theo chuyển hướng (để biết trang có chuyển hướng)."""
    op = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler({}), _HTTPHandler(), _HTTPSHandler(), _Redirect() if follow else _NoRedirect(),
              urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor(),
              urllib.request.UnknownHandler()):
        op.add_handler(h)
    return op


OPEN = opener(True)
OPEN_NO_REDIRECT = opener(False)


def read_body(resp, max_bytes: int = MAX_BODY) -> bytes:
    """Đọc thân phản hồi tối đa max_bytes (cắt bớt phần dư), giải nén gzip cũng có trần max_bytes."""
    raw = resp.read(max_bytes + 1)[:max_bytes]
    headers = getattr(resp, "headers", None)
    if headers is not None and (headers.get("Content-Encoding") or "").lower() == "gzip":
        try:
            raw = zlib.decompressobj(31).decompress(raw, max_bytes)
        except zlib.error:
            raw = b""
    return raw
