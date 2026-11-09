"""Ai đang dùng tool (chấm trạng thái trên avatar).

Lấy từ hoạt động thật, giữ trong bộ nhớ của máy chủ:
- available (đang online): có ít nhất một trang tool đang mở và có thao tác (chuột, phím, cuộn) trong 5 phút gần nhất;
- away (vắng mặt): trang vẫn mở nhưng không thao tác quá 5 phút;
- offline: không mở trang nào. "Lần cuối" lấy từ lúc đóng trang gần nhất (lưu vào access_users.last_seen), nếu chưa
  có thì từ lần đăng nhập cuối.
Không có trạng thái "bận" vì tool không có lịch hay chat để biết điều đó. Khởi động lại máy chủ thì mọi người về
offline cho tới khi mở lại trang.
"""
import threading
import time

AVAILABLE, AWAY, BUSY, OFFLINE = "available", "away", "busy", "offline"
IDLE_SECONDS = 5 * 60
LABEL = {AVAILABLE: "Đang online", AWAY: "Vắng mặt", BUSY: "Bận", OFFLINE: "Offline"}

_lock = threading.Lock()
_people: dict[str, dict] = {}  # tên người dùng → {"clients": {client_id}, "active": giờ thao tác cuối, "seen": giờ}


def _key(user) -> str:
    return str(user).strip().lower()


def connect(user, client_id: str) -> None:
    with _lock:
        p = _people.setdefault(_key(user), {"clients": set(), "active": 0.0, "seen": 0.0})
        p["clients"].add(client_id)
        p["active"] = p["seen"] = time.time()


def active(user) -> None:
    """Có thao tác trên một trang đang mở (trình duyệt báo tối đa mỗi phút một lần)."""
    with _lock:
        p = _people.get(_key(user))
        if p:
            p["active"] = p["seen"] = time.time()


def leave(user, client_id: str) -> bool:
    """Một trang đã đóng hẳn. True khi người này không còn trang nào mở (vừa chuyển sang offline)."""
    with _lock:
        p = _people.get(_key(user))
        if not p:
            return False
        p["clients"].discard(client_id)
        p["seen"] = time.time()
        return not p["clients"]


def status(user, now: float | None = None) -> tuple[str, float | None]:
    """(trạng thái, giờ có hoạt động cuối trong phiên chạy này hoặc None)."""
    now = now or time.time()
    with _lock:
        p = _people.get(_key(user))
        if not p:
            return OFFLINE, None
        if not p["clients"]:
            return OFFLINE, p["seen"]
        return (AVAILABLE if now - p["active"] <= IDLE_SECONDS else AWAY), p["active"]


def describe(user, last_seen_iso: str | None = None, now: float | None = None) -> tuple[str, str]:
    """(trạng thái, chữ hiển thị) ví dụ ("away", "Vắng mặt · không thao tác 12 phút")."""
    from datetime import datetime
    now = now or time.time()
    st, at = status(user, now)
    if st == AVAILABLE:
        return st, LABEL[st]
    if st == AWAY:
        return st, f"{LABEL[st]} · không thao tác {int((now - at) // 60)} phút"
    when = datetime.fromtimestamp(at) if at else (datetime.fromisoformat(last_seen_iso).astimezone()
                                                  if last_seen_iso else None)
    return st, LABEL[st] + (f" · lần cuối {when:%d/%m %H:%M}" if when else "")


def reset() -> None:
    """Chỉ dùng trong test."""
    with _lock:
        _people.clear()
