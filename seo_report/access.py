"""Ai đang dùng tool và được làm gì.

Ba cách được nhận là một người dùng:
- Mở thẳng trên máy chạy tool (kết nối từ 127.0.0.1 / ::1, không qua proxy): chủ máy, toàn quyền, không cần đăng
  nhập.
- Đăng nhập bằng email + mật khẩu (màn /login). Email phải được cấp quyền (config.toml hoặc màn Phân quyền). Mật
  khẩu chỉ lưu dạng băm scrypt; sai 5 lần liên tiếp thì khóa 15 phút; mật khẩu tạm do quản trị cấp phải đổi ở lần
  đăng nhập đầu. Phiên đăng nhập lưu trong cookie có ký của trình duyệt và hết hiệu lực ngay khi mật khẩu được đặt lại
  hoặc quyền bị gỡ.
- Lớp đăng nhập phía trước đã xác minh email: Cloudflare Access (chỉ khi đã khai team_domain + aud để kiểm tra chữ
  ký JWT, không tin header email trần) hoặc Tailscale Serve (header Tailscale-User-Login, không qua Cloudflare).

Nhiều dự án (website). Tài khoản có hai loại:
- Chủ tool (`editors` trong config.toml, duy nhất là quản trị): mọi dự án, được sửa, quản lý Dự án, Phân quyền và
  Ngân sách. Chủ máy (mở thẳng trên máy chạy tool) cũng có toàn quyền. Tài khoản tên đăng nhập (không cần email)
  được dùng cho mọi loại trừ Chủ tool.
- Theo dự án (`viewer` trong access_users, hoặc `viewers` trong config.toml): chỉ vào được các dự án được gắn trong
  bảng project_members, mỗi dự án một quyền: `editor` được sửa, `viewer` team xem (mọi màn, không sửa), `client` khách
  hàng (chỉ các màn báo cáo). Email trong `viewers` của config.toml được xem dự án đầu tiên (cách dùng cũ khi tool chỉ có một site).

Quyền trong dự án: `editor` được sửa (check rank tốn tiền, sửa nhóm URL/keyword, nhập file, nhận xét, đồng bộ, xuất
lên Drive); `viewer` chỉ xem và tải file về máy; `client` như viewer nhưng chỉ thấy Tổng quan, Báo cáo, KPI, Công việc.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.request
from dataclasses import dataclass, field

LOCAL, EDITOR, VIEWER, CLIENT = "local", "editor", "viewer", "client"
# Loại tài khoản (cột role của access_users): EDITOR = quản trị mọi dự án, VIEWER = chỉ các dự án được gắn.
ADMIN, MEMBER = EDITOR, VIEWER
PROJECT_ROLES = {CLIENT: "Khách hàng", VIEWER: "Team xem", EDITOR: "Được sửa"}  # quyền trong một dự án
CLIENT_PAGES = ("/", "/report", "/kpi", "/okr", "/tai-khoan")  # màn khách hàng được mở
MAX_FAILED, LOCK_MINUTES, MIN_PASSWORD = 5, 15, 10


@dataclass
class AccessSettings:
    editors: list[str] = field(default_factory=list)
    viewers: list[str] = field(default_factory=list)
    team_domain: str = ""  # ví dụ "congty.cloudflareaccess.com": có thì kiểm tra chữ ký JWT của Access
    aud: str = ""  # Application Audience (AUD) tag của ứng dụng trong Cloudflare Access


class User(str):
    """Tên hiển thị (email hoặc tên tài khoản máy) kèm vai trò; dùng như chuỗi ở mọi chỗ ghi nhật ký."""
    role: str = LOCAL
    preview: bool = False  # chủ máy đang xem thử giao diện của người chỉ xem
    must_change: bool = False  # đang dùng mật khẩu tạm: phải đổi trước khi dùng tool
    via: str = ""  # "password" khi đăng nhập bằng mật khẩu (có nút Đăng xuất)
    admin: bool = False  # quản trị mọi dự án (giữ nguyên khi role đã đổi thành quyền trong một dự án)

    def __new__(cls, name: str, role: str, preview: bool = False, must_change: bool = False, via: str = "",
                admin: bool | None = None):
        obj = super().__new__(cls, name)
        obj.role, obj.preview, obj.must_change, obj.via = role, preview, must_change, via
        obj.admin = role in (LOCAL, EDITOR) if admin is None else admin
        return obj


def can_edit(user) -> bool:
    return getattr(user, "role", LOCAL) in (LOCAL, EDITOR)


def is_admin(user) -> bool:
    """Quản trị mọi dự án: thêm / sửa dự án, phân quyền. Người được sửa trong một dự án không phải quản trị."""
    return bool(getattr(user, "admin", False)) and not getattr(user, "preview", False)


def is_client(user) -> bool:
    return getattr(user, "role", LOCAL) == CLIENT

LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _host_name(host: str) -> str:
    """Tên máy trong header Host, bỏ cổng: '127.0.0.1:8080' → '127.0.0.1', '[::1]:8080' → '::1'."""
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def is_local(client_host: str | None, headers) -> bool:
    """Kết nối thẳng từ chính máy này: địa chỉ loopback, không đi qua proxy (Cloudflare, Tailscale…), và trình duyệt
    đang mở đúng địa chỉ localhost / 127.0.0.1. Kiểm tra Host chặn DNS rebinding: một trang web lạ trỏ tên miền của nó
    về 127.0.0.1 sẽ gửi Host là tên miền đó, nên không được coi là chủ máy."""
    return ((client_host or "") in LOOPBACK and _host_name(headers.get("host", "")) in LOOPBACK and not (
        headers.get("cf-ray") or headers.get("x-forwarded-for") or headers.get("tailscale-user-login")))


def client_ip(client_host: str | None, headers) -> str:
    """IP thật của người truy cập. Qua Cloudflare Tunnel / Tailscale, kết nối luôn đến từ 127.0.0.1: IP thật nằm ở
    header do Cloudflare (cf-connecting-ip) hoặc Tailscale (x-forwarded-for) đặt."""
    return (headers.get("cf-connecting-ip") or (headers.get("x-forwarded-for") or "").split(",")[0].strip()
            or client_host or "")


# Chặn dò mật khẩu theo IP (bổ sung cho khóa theo tài khoản): một IP sai quá nhiều lần, kể cả với email không có
# trong tool, thì tạm không cho thử tiếp. Lưu trong bộ nhớ, tool khởi động lại thì xóa.
IP_MAX_FAILED, IP_WINDOW = 20, 15 * 60
_IP_FAILS: dict[str, list[float]] = {}


def ip_blocked(ip: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    hits = [t for t in _IP_FAILS.get(ip, []) if now - t < IP_WINDOW]
    if hits:
        _IP_FAILS[ip] = hits
    else:
        _IP_FAILS.pop(ip, None)
    return len(hits) >= IP_MAX_FAILED


def note_ip_fail(ip: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    for k in [k for k, v in _IP_FAILS.items() if now - v[-1] >= IP_WINDOW]:  # dọn IP đã hết hạn
        del _IP_FAILS[k]
    _IP_FAILS.setdefault(ip, []).append(now)


# ---- Người dùng: danh sách trong config.toml + danh sách trên màn Phân quyền ----

SCHEMA = """
CREATE TABLE IF NOT EXISTS access_users (
    email TEXT PRIMARY KEY,
    role TEXT NOT NULL,          -- editor | viewer (email có trong config.toml thì quyền theo config)
    note TEXT NOT NULL DEFAULT '',
    added_by TEXT NOT NULL,
    added_at TEXT NOT NULL,
    removed_by TEXT,
    removed_at TEXT              -- gỡ quyền: chỉ đánh dấu, giữ lịch sử
);
"""
PASSWORD_COLS = {"pw_hash": "TEXT", "pw_set_at": "TEXT", "must_change": "INTEGER NOT NULL DEFAULT 0",
                 "failed": "INTEGER NOT NULL DEFAULT 0", "locked_until": "TEXT", "last_login": "TEXT",
                 # chức danh hiển thị (SEO, Content…), không ảnh hưởng quyền
                 "title": "TEXT NOT NULL DEFAULT ''",
                 # Team mọi dự án: quyền (viewer / editor) áp cho mọi website, kể cả website thêm sau
                 "team_role": "TEXT",
                 "last_seen": "TEXT",  # lúc đóng trang tool gần nhất (chấm trạng thái: "offline · lần cuối …")
                 # hồ sơ do chính người dùng sửa ở màn Hồ sơ: tên hiển thị và ảnh đại diện (data URI PNG nhỏ)
                 "display_name": "TEXT NOT NULL DEFAULT ''", "avatar": "TEXT NOT NULL DEFAULT ''"}
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
USERNAME_RE = r"^[a-z0-9][a-z0-9._-]{2,31}$"  # tài khoản không cần email: tên đăng nhập 3–32 ký tự
ROLE_LABEL = {EDITOR: "Chủ tool", VIEWER: "Theo dự án"}  # loại tài khoản
MEMBERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_members (
    email TEXT NOT NULL,
    project TEXT NOT NULL,       -- slug của dự án
    role TEXT NOT NULL,          -- editor | viewer | client
    added_by TEXT NOT NULL,
    added_at TEXT NOT NULL,
    removed_by TEXT,
    removed_at TEXT,             -- gỡ: chỉ đánh dấu, giữ lịch sử
    PRIMARY KEY (email, project)
);
CREATE TABLE IF NOT EXISTS access_log (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    by TEXT NOT NULL,
    email TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""
TEAM_ROLES = {VIEWER: "Team xem", EDITOR: "Được sửa"}  # quyền chung của Team mọi dự án
KEEP = object()  # set_user: giữ nguyên giá trị cũ


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp() -> str:
    """Mốc đặt mật khẩu, chính xác tới micro giây: phiên đăng nhập gắn với mốc này nên đặt lại mật khẩu (dù trong cùng
    giây) là phiên cũ hết hiệu lực."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _ensure(con) -> None:
    con.executescript(SCHEMA + MEMBERS_SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(access_users)")}
    for col, kind in PASSWORD_COLS.items():
        if col not in have:
            with con:
                con.execute(f"ALTER TABLE access_users ADD COLUMN {col} {kind}")


_COLS = ("email, role, note, added_by, added_at, removed_at, pw_hash IS NOT NULL, pw_set_at, must_change, "
         "locked_until, last_login, title, team_role, removed_by, last_seen")


def users(con, settings: AccessSettings) -> list[dict]:
    """Mọi email có quyền, kèm tình trạng mật khẩu.

    - `editors` trong config.toml: luôn là quản trị (chỉ sửa trong file) để không bao giờ bị khóa ngoài.
    - Email thêm trên màn Phân quyền: quyền theo màn đó.
    - `viewers` trong config.toml: chỉ tính khi email chưa có trong tool (cách dùng cũ); adopt_config chuyển chúng
      vào tool một lần, sau đó sửa / gỡ trên màn Phân quyền."""
    _ensure(con)
    rows = {r[0]: r for r in con.execute(f"SELECT {_COLS} FROM access_users")}
    out = {}
    for e in _norm(settings.viewers):
        if e not in rows:
            out[e] = {"email": e, "role": VIEWER, "source": "config", "note": "", "added_by": "config.toml",
                      "added_at": None}
    owners = _norm(settings.editors)
    for e, r in rows.items():
        if r[5] is None:  # chỉ email `editors` trong config.toml là Chủ tool; quản trị thêm trên màn cũ: hạ ở adopt_config
            out[e] = {"email": e, "role": r[1] if e in owners else VIEWER, "source": "tool", "note": r[2],
                      "added_by": r[3], "added_at": r[4]}
    for e in _norm(settings.editors):
        out[e] = {"email": e, "role": EDITOR, "source": "config", "note": out.get(e, {}).get("note", ""),
                  "added_by": "config.toml", "added_at": None}
    for e, u in out.items():
        r = rows.get(e)
        u.update({"has_password": bool(r and r[6]), "pw_set_at": r[7] if r else None,
                  "must_change": bool(r and r[8]), "locked_until": r[9] if r else None,
                  "last_login": r[10] if r else None, "title": (r[11] if r else "") or "",
                  "team_role": (r[12] if r and u["role"] == VIEWER else None),
                  "last_seen": (r[14] if r else None) or (r[10] if r else None)})
    return sorted(out.values(), key=lambda u: (u["role"] != EDITOR, u["email"]))


MAX_NAME = 60


def profiles(con) -> dict[str, dict]:
    """Hồ sơ mọi tài khoản: {email: {"name": tên hiển thị hoặc "", "avatar": data URI hoặc ""}}."""
    _ensure(con)
    return {r[0]: {"name": r[1] or "", "avatar": r[2] or ""}
            for r in con.execute("SELECT email, display_name, avatar FROM access_users")}


def display_name(profile: dict | None, email: str) -> str:
    return (profile or {}).get("name") or str(email)


def set_profile(con, settings: AccessSettings, email: str, name: str, avatar: str) -> None:
    """Người dùng tự sửa tên hiển thị / ảnh đại diện của mình. Tài khoản trong config.toml chưa có dòng thì tạo."""
    email = _clean_email(email)
    name = " ".join((name or "").split())
    if len(name) > MAX_NAME:
        raise ValueError(f"Tên hiển thị tối đa {MAX_NAME} ký tự")
    if avatar and not avatar.startswith("data:image/"):
        raise ValueError("Ảnh đại diện không hợp lệ")
    u = next((x for x in users(con, settings) if x["email"] == email), None)
    if not u:
        raise ValueError("Tài khoản không còn quyền dùng tool")
    with con:
        con.execute("INSERT INTO access_users (email, role, note, added_by, added_at) VALUES (?, ?, '', 'config.toml', ?) "
                    "ON CONFLICT(email) DO NOTHING", (email, u["role"], _now()))
        con.execute("UPDATE access_users SET display_name = ?, avatar = ? WHERE email = ?", (name, avatar, email))


def mark_seen(con, email: str) -> None:
    """Ghi lúc người này đóng trang tool cuối cùng (chỉ email đã có trong tool)."""
    _ensure(con)
    with con:
        con.execute("UPDATE access_users SET last_seen = ? WHERE email = ?", (_now(), str(email).strip().lower()))


def removed_users(con) -> list[dict]:
    """Tài khoản đã gỡ (giữ lịch sử) để cấp lại khi cần."""
    _ensure(con)
    return [{"email": r[0], "role": r[1], "note": r[2], "title": r[11] or "", "removed_at": r[5], "removed_by": r[13]}
            for r in con.execute(f"SELECT {_COLS} FROM access_users WHERE removed_at IS NOT NULL "
                                 "ORDER BY removed_at DESC")]


def kind(u: dict, mine: dict[str, str]) -> str:
    """Nhóm hiển thị: admin (quản trị) · team (người trong team) · client (khách hàng: chỉ có quyền Khách hàng)."""
    if u["role"] == EDITOR:
        return "admin"
    if u.get("team_role") or any(r != CLIENT for r in mine.values()) or (not mine and u["source"] == "config"):
        return "team"
    return "client" if mine else "team"


def _log(con, by, email: str, action: str, detail: str = "") -> None:
    con.execute("INSERT INTO access_log (at, by, email, action, detail) VALUES (?, ?, ?, ?, ?)",
                (_now(), str(by), email, action, detail))


def log_entries(con, limit: int = 300) -> list[dict]:
    _ensure(con)
    return [{"at": r[0], "by": r[1], "email": r[2], "action": r[3], "detail": r[4]} for r in con.execute(
        "SELECT at, by, email, action, detail FROM access_log ORDER BY id DESC LIMIT ?", (limit,))]


def effective(con, settings: AccessSettings) -> AccessSettings:
    """Cấu hình đầy đủ để kiểm tra quyền: danh sách trong config cộng danh sách trên màn Phân quyền."""
    us = users(con, settings)
    return AccessSettings(editors=[u["email"] for u in us if u["role"] == EDITOR],
                          viewers=[u["email"] for u in us if u["role"] == VIEWER],
                          team_domain=settings.team_domain, aud=settings.aud)


def _clean_email(email: str) -> str:
    """Email hoặc tên đăng nhập (chữ thường không dấu, số, . _ -), viết thường."""
    import re
    email = (email or "").strip().lower()
    if not (re.match(EMAIL_RE, email) or re.match(USERNAME_RE, email)):
        raise ValueError("Email hoặc tên đăng nhập không hợp lệ. Tên đăng nhập: 3–32 ký tự gồm chữ không dấu, số, "
                         "dấu . _ -")
    return email


def is_username(login: str) -> bool:
    return "@" not in str(login)


def set_user(con, email: str, role: str, by: str, note: str = "", title=KEEP, team_role=KEEP) -> str:
    """Thêm hoặc sửa tài khoản (loại tài khoản, ghi chú, chức danh, quyền Team mọi dự án). Ghi nhật ký thay đổi."""
    email = _clean_email(email)
    if role not in (EDITOR, VIEWER):
        raise ValueError("Quyền không hợp lệ")
    if team_role is not KEEP and team_role not in (None, *TEAM_ROLES):
        raise ValueError("Quyền Team không hợp lệ")
    _ensure(con)
    old = con.execute("SELECT role, removed_at, title, team_role FROM access_users WHERE email = ?",
                      (email,)).fetchone()
    title = (old[2] if old else "") if title is KEEP else (title or "").strip()
    team_role = (old[3] if old else None) if team_role is KEEP else team_role
    if role == EDITOR:
        team_role = None
    with con:
        con.execute("INSERT INTO access_users (email, role, note, added_by, added_at, title, team_role) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(email) DO UPDATE SET role = excluded.role, note = excluded.note, title = excluded.title, "
                    "team_role = excluded.team_role, removed_by = NULL, removed_at = NULL, "
                    "added_by = CASE WHEN access_users.removed_at IS NULL THEN access_users.added_by "
                    "ELSE excluded.added_by END, "
                    "added_at = CASE WHEN access_users.removed_at IS NULL THEN access_users.added_at "
                    "ELSE excluded.added_at END",
                    (email, role, note.strip(), str(by), _now(), title, team_role))
        label = ROLE_LABEL[role] if not team_role else f"Team mọi dự án · {TEAM_ROLES[team_role]}"
        if not old:
            _log(con, by, email, "Thêm tài khoản", label)
        elif old[1]:
            _log(con, by, email, "Cấp lại tài khoản", label)
        elif (old[0], old[3]) != (role, team_role):
            before = ROLE_LABEL.get(old[0], old[0]) if not old[3] else f"Team mọi dự án · {TEAM_ROLES[old[3]]}"
            _log(con, by, email, "Đổi loại tài khoản", f"{before} → {label}")
    return email


def remove_user(con, email: str, by: str) -> None:
    """Gỡ quyền (đánh dấu, giữ lịch sử). Phiên đăng nhập của người đó hết hiệu lực ngay ở lần mở trang kế tiếp."""
    _ensure(con)
    email = email.strip().lower()
    with con:
        n = con.execute("UPDATE access_users SET removed_by = ?, removed_at = ?, pw_hash = NULL, pw_set_at = NULL "
                        "WHERE email = ? AND removed_at IS NULL", (str(by), _now(), email)).rowcount
        if n:
            _log(con, by, email, "Gỡ tài khoản")


# ---- Quyền theo dự án ----

def members(con) -> dict[str, dict[str, str]]:
    """{email: {slug dự án: quyền}} của mọi quyền đang có hiệu lực (gắn trên màn Phân quyền)."""
    _ensure(con)
    out: dict[str, dict[str, str]] = {}
    for email, project, role in con.execute(
            "SELECT email, project, role FROM project_members WHERE removed_at IS NULL"):
        out.setdefault(email, {})[project] = role
    return out


def set_member(con, email: str, project: str, role: str, by: str) -> None:
    """Gắn (hoặc đổi quyền) một tài khoản vào một dự án."""
    email = _clean_email(email)
    if role not in PROJECT_ROLES:
        raise ValueError("Quyền trong dự án không hợp lệ")
    _ensure(con)
    old = con.execute("SELECT role FROM project_members WHERE email = ? AND project = ? AND removed_at IS NULL",
                      (email, project)).fetchone()
    if old and old[0] == role:
        return
    with con:
        con.execute("INSERT INTO project_members (email, project, role, added_by, added_at) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(email, project) DO UPDATE SET role = excluded.role, added_by = excluded.added_by, "
                    "added_at = excluded.added_at, removed_by = NULL, removed_at = NULL",
                    (email, project, role, str(by), _now()))
        _log(con, by, email, "Đổi quyền dự án" if old else "Gắn dự án",
             f"{project}: {PROJECT_ROLES[old[0]] + ' → ' if old else ''}{PROJECT_ROLES[role]}")


def remove_member(con, email: str, project: str, by: str) -> None:
    """Gỡ một dự án khỏi tài khoản (đánh dấu, giữ lịch sử). Có hiệu lực ở lần mở trang kế tiếp của người đó."""
    _ensure(con)
    email = email.strip().lower()
    with con:
        n = con.execute("UPDATE project_members SET removed_by = ?, removed_at = ? WHERE email = ? AND project = ? "
                        "AND removed_at IS NULL", (str(by), _now(), email, project)).rowcount
        if n:
            _log(con, by, email, "Gỡ dự án", project)


def adopt_config(con, settings: AccessSettings, first_project: str | None) -> int:
    """Chuyển email `viewers` trong config.toml chưa có trong tool vào tool (xem dự án đầu tiên, trừ khi đã được gắn
    quyền riêng ở dự án đó) để quản lý hết trên màn Phân quyền. Chạy mỗi lần mở tool; email đã có trong tool (kể cả
    đã gỡ) không bị đụng tới. `editors` vẫn giữ trong config.toml làm quản trị dự phòng."""
    _ensure(con)
    owners = _norm(settings.editors)
    for (e,) in con.execute("SELECT email FROM access_users WHERE role = ? AND removed_at IS NULL",
                            (EDITOR,)).fetchall():
        if e not in owners:  # chỉ Chủ tool (config.toml) là quản trị: quản trị cũ thành Team mọi website · Được sửa
            with con:
                con.execute("UPDATE access_users SET role = ?, team_role = ? WHERE email = ?", (VIEWER, EDITOR, e))
                _log(con, "tool", e, "Đổi loại tài khoản", "Quản trị → Team mọi dự án · Được sửa (chỉ Chủ tool là "
                                                           "quản trị)")
    have = {r[0] for r in con.execute("SELECT email FROM access_users")}
    n = 0
    for e in sorted(_norm(settings.viewers) - owners):
        if e in have:
            continue
        set_user(con, e, MEMBER, "config.toml")
        if first_project and first_project not in members(con).get(e, {}):
            set_member(con, e, first_project, VIEWER, "config.toml")
        n += 1
    return n


def migrate_members(con, settings: AccessSettings, first_project: str) -> int:
    """Một lần khi chuyển sang nhiều dự án: tài khoản "chỉ xem" thêm trên màn Phân quyền trước đây được xem dự án đầu
    tiên. Chỉ áp cho tài khoản chưa có dự án nào; chạy lại không thêm gì."""
    _ensure(con)
    con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if con.execute("SELECT 1 FROM app_settings WHERE key = 'members_migrated'").fetchone():
        return 0
    have = members(con)
    n = 0
    for u in users(con, settings):
        if u["source"] == "tool" and u["role"] == MEMBER and u["email"] not in have:
            set_member(con, u["email"], first_project, VIEWER, "chuyển sang nhiều dự án")
            n += 1
    with con:
        con.execute("INSERT INTO app_settings VALUES ('members_migrated', ?)", (_now(),))
    return n


def project_role(con, settings: AccessSettings, user, project: str, first_project: str | None) -> str | None:
    """Quyền của một người trong một dự án; None là không được vào dự án đó.

    Quản trị và chủ máy: mọi dự án. Tài khoản theo dự án: quyền gắn riêng cho dự án đó; không có thì quyền Team mọi
    dự án (nếu có). Email `viewers` trong config.toml chưa chuyển vào tool thì xem được dự án đầu tiên."""
    if getattr(user, "admin", False):
        if getattr(user, "preview", False):  # chủ máy xem thử: giữ đúng quyền đang xem thử (chỉ xem / khách hàng)
            return user.role
        return user.role if user.role in (LOCAL, EDITOR) else EDITOR
    email = str(user).strip().lower()
    role = members(con).get(email, {}).get(project)
    if role:
        return role
    _ensure(con)
    row = con.execute("SELECT team_role, removed_at FROM access_users WHERE email = ?", (email,)).fetchone()
    if row and row[1] is None and row[0]:  # Team mọi dự án
        return row[0]
    if (project == first_project and email in _norm(settings.viewers) and not (row and row[1])
            and not members(con).get(email)):  # config.toml, chưa được gắn dự án nào: xem dự án đầu tiên
        return VIEWER
    return None


ROLE_ORDER = {"admin": 0, EDITOR: 1, VIEWER: 2, CLIENT: 3}


def people_in_project(con, settings: AccessSettings, project: str, first_project: str | None) -> list[dict]:
    """Mọi tài khoản vào được một website: [{"email", "title", "role": "admin" | editor | viewer | client}], theo
    thứ tự cố định quản trị → được sửa → chỉ xem → khách hàng, rồi theo email (nhóm avatar trên thanh trên cùng)."""
    mem = members(con)
    out = []
    for u in users(con, settings):
        mine = mem.get(u["email"], {})
        if u["role"] == EDITOR:
            role = "admin"
        else:
            role = (mine.get(project) or u.get("team_role")
                    or (VIEWER if u["source"] == "config" and project == first_project and not mine else None))
        if role:
            out.append({"email": u["email"], "title": u.get("title", ""), "role": role})
    return sorted(out, key=lambda p: (ROLE_ORDER[p["role"]], p["email"]))


def in_project(user, role: str) -> "User":
    """Bản sao người dùng mang quyền trong dự án đang mở; mọi chỗ kiểm tra can_edit dùng bản này."""
    return User(str(user), role, preview=getattr(user, "preview", False), must_change=getattr(user, "must_change", False),
                via=getattr(user, "via", ""), admin=getattr(user, "admin", False))


# ---- Mật khẩu ----

def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def check_password(pw: str, stored: str | None) -> bool:
    try:
        kind, salt, h = (stored or "").split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def temp_password() -> str:
    """Mật khẩu tạm dễ đọc qua điện thoại: 3 nhóm 4 ký tự, bỏ các ký tự dễ nhầm (0/O, 1/l/I)."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def set_password(con, settings: AccessSettings, email: str, pw: str, must_change: bool, by: str = "") -> None:
    """Đặt mật khẩu cho một email đang có quyền (kể cả email trong config.toml)."""
    email = _clean_email(email)
    if len(pw) < MIN_PASSWORD:
        raise ValueError(f"Mật khẩu cần ít nhất {MIN_PASSWORD} ký tự")
    u = next((x for x in users(con, settings) if x["email"] == email), None)
    if not u:
        raise ValueError("Email chưa được cấp quyền")
    with con:
        con.execute("INSERT INTO access_users (email, role, note, added_by, added_at) VALUES (?, ?, '', 'config.toml', ?) "
                    "ON CONFLICT(email) DO NOTHING", (email, u["role"], _now()))
        con.execute("UPDATE access_users SET pw_hash = ?, pw_set_at = ?, must_change = ?, failed = 0, "
                    "locked_until = NULL WHERE email = ?", (hash_password(pw), _stamp(), int(must_change), email))
        if by:
            _log(con, by, email, "Đặt mật khẩu", "gợi ý đổi khi đăng nhập" if must_change else "")


def dismiss_change(con, email: str) -> None:
    """Người dùng chọn giữ mật khẩu được cấp: thôi gợi ý đổi mật khẩu ở các lần đăng nhập sau."""
    with con:
        con.execute("UPDATE access_users SET must_change = 0 WHERE email = ?", (_clean_email(email),))


def login(con, settings: AccessSettings, email: str, pw: str, now=None) -> tuple["User | None", str, dict | None]:
    """(người dùng, lý do lỗi, phiên để lưu vào cookie)."""
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    email = (email or "").strip().lower()
    u = next((x for x in users(con, settings) if x["email"] == email), None)
    generic = "Email hoặc mật khẩu không đúng"
    if not u:
        return None, generic, None
    row = con.execute("SELECT pw_hash, failed, locked_until, must_change, pw_set_at FROM access_users WHERE email = ?",
                      (email,)).fetchone()
    if not row or not row[0]:
        return None, "Tài khoản chưa có mật khẩu: liên hệ người quản lý tool để được cấp", None
    if row[2] and datetime.fromisoformat(row[2]) > now:
        until = datetime.fromisoformat(row[2]).astimezone()
        return None, f"Sai mật khẩu nhiều lần: tạm khóa đến {until:%H:%M}", None
    if not check_password(pw, row[0]):
        failed = row[1] + 1
        locked = (now + timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds") if failed >= MAX_FAILED else None
        with con:
            con.execute("UPDATE access_users SET failed = ?, locked_until = ? WHERE email = ?",
                        (0 if locked else failed, locked, email))
        return None, (f"Sai mật khẩu {MAX_FAILED} lần: tạm khóa {LOCK_MINUTES} phút" if locked else generic), None
    with con:
        con.execute("UPDATE access_users SET failed = 0, locked_until = NULL, last_login = ? WHERE email = ?",
                    (now.isoformat(timespec="seconds"), email))
    return (User(email, u["role"], must_change=bool(row[3]), via="password"), "",
            {"email": email, "pw_set_at": row[4]})


def from_session(con, settings: AccessSettings, sess: dict | None) -> "User | None":
    """Người dùng của phiên đăng nhập đã lưu; None nếu quyền đã bị gỡ hoặc mật khẩu đã được đặt lại sau khi đăng
    nhập."""
    if not sess or not sess.get("email"):
        return None
    u = next((x for x in users(con, settings) if x["email"] == sess["email"]), None)
    if not u or not u["has_password"] or u["pw_set_at"] != sess.get("pw_set_at"):
        return None
    return User(u["email"], u["role"], must_change=u["must_change"], via="password")


# ---- Lớp đăng nhập phía trước (Cloudflare Access / Tailscale) ----

def identify(headers, settings: AccessSettings, local_name: str, client_host: str | None = "127.0.0.1"
             ) -> tuple[User | None, str]:
    """(người dùng, lý do). Không nhận ra ai thì trả None: màn hình sẽ chuyển sang trang đăng nhập."""
    if is_local(client_host, headers):
        return User(local_name, LOCAL), ""
    if headers.get("cf-ray"):
        if not (settings.team_domain and settings.aud):
            return None, ""  # không tin header email khi chưa kiểm tra được chữ ký: đăng nhập bằng mật khẩu
        try:
            email = _verify(headers.get("cf-access-jwt-assertion", ""), settings)
        except Exception as e:  # noqa: BLE001
            return None, f"Phiên Cloudflare không hợp lệ ({e})"
        return _by_email(email, settings)
    ts_login = headers.get("tailscale-user-login", "")
    if ts_login:
        return _by_email(ts_login, settings)
    return None, ""


def _by_email(email: str, settings: AccessSettings) -> tuple[User | None, str]:
    email = email.strip().lower()
    if not email:
        return None, ""
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
