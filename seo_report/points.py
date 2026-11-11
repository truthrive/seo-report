"""Hạn mức credit hằng tháng của Member: mọi tác vụ bấm tay (tốn phí hoặc miễn phí) trừ credit theo bảng COSTS.

1 credit ≈ 0,001 USD. Tác vụ tốn phí DataForSEO tính theo giá thật; tác vụ miễn phí tính theo lượt Google (quota) hoặc
tải máy chủ. Owner / Admin không giới hạn (vẫn ghi nhật ký để xem ai dùng gì). Việc tool tự chạy theo lịch không trừ
credit của ai (tính vào ngân sách dự án như cũ). Ngày 1 hằng tháng credit tự đặt lại: hạn mức tính theo tháng của nhật ký.

Dữ liệu nằm ở file dữ liệu chính (cùng chỗ tài khoản), dùng chung mọi dự án: credit là của người, không của dự án.
"""
import math
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone

from . import access as A

DEFAULT_MONTHLY = 2000
POINT_USD = 0.001
# tác vụ → (tên, credit mỗi lần / mỗi từ khóa). Check rank: 1 credit mỗi 10 kết quả của độ sâu (xem rank_points).
COSTS = {
    "rank": ("Check rank", 1),
    "aio": ("Check AIO", 2),
    "serp": ("Xem kết quả Google", 2),
    "backlink": ("Lấy backlink", 150),
    "research": ("Research từ khóa", 2),
    "overview": ("Tổng quan từ khóa", 1),
    "volume": ("Lấy volume từ khóa", 1),
    "audit": ("Quét audit kỹ thuật", 10),
    "pagespeed": ("Lấy số tốc độ trang", 2),
    "local": ("Lấy số Local SEO", 1),
    "merchant": ("Lấy số Merchant Center", 1),
    "kg": ("Kiểm tra Knowledge Graph", 1),
    "sheets": ("Lưu Google Sheets / Drive", 1),
    "ai_aio": ("AI viết đoạn trả lời AIO", 5),
    "ai_report": ("AI viết nhận xét báo cáo", 10),
    "ai_brief": ("AI bản tin Tổng quan", 5),
    "ai_plan": ("AI lập chiến lược SEO", 10),
    "ai_kwbrief": ("AI viết brief từ khóa", 5),
    "ai_kpi": ("AI đọc sheet cam kết KPI", 10),
    "ai_kpi_insight": ("AI nhận định KPI", 5),
    "backlink_gap": ("Backlink GAP đối thủ", 30),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS points_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, month TEXT NOT NULL, email TEXT NOT NULL,
  project TEXT NOT NULL DEFAULT '', action TEXT NOT NULL, points INTEGER NOT NULL, detail TEXT NOT NULL DEFAULT '',
  member INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS points_log_month ON points_log (month, email);
CREATE TABLE IF NOT EXISTS points_limits (email TEXT PRIMARY KEY, monthly INTEGER NOT NULL, by TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS points_grants (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, month TEXT NOT NULL, email TEXT NOT NULL,
  points INTEGER NOT NULL, by TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
"""

_APP_DB: dict = {"path": None}


def set_app_db(path) -> None:
    """web.py gọi lúc khởi động: file dữ liệu chính (tài khoản, phân quyền, credit)."""
    _APP_DB["path"] = str(path)


def _connect():
    if not _APP_DB["path"]:
        raise RuntimeError("chưa đặt file dữ liệu chính cho credit")
    con = sqlite3.connect(_APP_DB["path"], timeout=15)
    ensure(con)
    return closing(con)


def ensure(con) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def month_of(today: date | None = None) -> str:
    return (today or date.today()).strftime("%Y-%m")


def rank_points(depths) -> int:
    """Check rank: 1 credit mỗi 10 kết quả (độ sâu 20 = 2 credit), cộng cho mọi từ khóa."""
    return sum(max(1, math.ceil((d or 10) / 10)) for d in depths)


def cost(action: str, n: int = 1) -> int:
    return COSTS[action][1] * max(0, int(n))


# ---------------------------------------------------------------- hạn mức

def monthly_limit(con, email: str) -> int:
    ensure(con)
    row = con.execute("SELECT monthly FROM points_limits WHERE email = ?", (str(email).lower(),)).fetchone()
    return int(row[0]) if row else DEFAULT_MONTHLY


def granted(con, email: str, month: str | None = None) -> int:
    ensure(con)
    return int(con.execute("SELECT COALESCE(SUM(points), 0) FROM points_grants WHERE email = ? AND month = ?",
                           (str(email).lower(), month or month_of())).fetchone()[0])


def used(con, email: str, month: str | None = None) -> int:
    ensure(con)
    return int(con.execute("SELECT COALESCE(SUM(points), 0) FROM points_log WHERE email = ? AND month = ? "
                           "AND member = 1", (str(email).lower(), month or month_of())).fetchone()[0])


def balance(con, email: str, month: str | None = None) -> dict:
    """{"limit": hạn mức tháng + cấp thêm, "monthly", "granted", "used", "left"}."""
    m = monthly_limit(con, email)
    g = granted(con, email, month)
    u = used(con, email, month)
    return {"monthly": m, "granted": g, "limit": m + g, "used": u, "left": max(0, m + g - u)}


def set_limit(con, email: str, monthly: int, by: str) -> None:
    monthly = int(monthly)
    if monthly < 0 or monthly > 1_000_000:
        raise ValueError("Hạn mức không hợp lệ")
    ensure(con)
    with con:
        con.execute("INSERT INTO points_limits VALUES (?, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET "
                    "monthly = excluded.monthly, by = excluded.by, at = excluded.at",
                    (str(email).lower(), monthly, str(by), _now()))


def grant(con, email: str, points: int, by: str, note: str = "", today: date | None = None) -> None:
    """Cấp thêm credit cho tháng này (chỉ tháng này)."""
    points = int(points)
    if points <= 0 or points > 1_000_000:
        raise ValueError("Số credit cấp thêm không hợp lệ")
    ensure(con)
    with con:
        con.execute("INSERT INTO points_grants (at, month, email, points, by, note) VALUES (?, ?, ?, ?, ?, ?)",
                    (_now(), month_of(today), str(email).lower(), points, str(by), note.strip()))


# ---------------------------------------------------------------- trừ credit

class NotEnough(Exception):
    pass


def spend(con, user, project: str, action: str, points: int, detail: str = "",
          today: date | None = None) -> int | None:
    """Ghi một tác vụ; Member không đủ credit thì NotEnough (không ghi). Trả id dòng nhật ký (để hoàn khi lỗi), None
    khi không tính credit (Guest / 0 credit)."""
    points = int(points)
    if points <= 0 or A.is_client(user):
        return None
    member = A.is_member(user)
    email = str(user).lower()
    month = month_of(today)
    ensure(con)
    with con:
        if member:
            b = balance(con, email, month)
            if points > b["left"]:
                raise NotEnough(f"Cần {points:,} credit, còn {b['left']:,} / {b['limit']:,} credit tháng này. Nhờ Owner "
                                f"hoặc Admin cấp thêm.".replace(",", "."))
        cur = con.execute("INSERT INTO points_log (at, month, email, project, action, points, detail, member) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (_now(), month, email, project, action, points, detail[:300], int(member)))
    return cur.lastrowid


def refund(con, entry_id: int | None) -> None:
    """Hoàn credit khi tác vụ không chạy được."""
    if entry_id:
        with con:
            con.execute("DELETE FROM points_log WHERE id = ?", (entry_id,))


def usage(con, month: str | None = None) -> list[dict]:
    """Ai đã dùng bao nhiêu credit tháng này, tách theo tác vụ: [{"email", "member", "points", "by_action": {}}]."""
    ensure(con)
    out: dict[str, dict] = {}
    for email, member, action, pts in con.execute(
            "SELECT email, MAX(member), action, SUM(points) FROM points_log WHERE month = ? GROUP BY email, action",
            (month or month_of(),)):
        u = out.setdefault(email, {"email": email, "member": bool(member), "points": 0, "by_action": {}})
        u["points"] += pts
        u["by_action"][action] = pts
        u["member"] = u["member"] or bool(member)
    return sorted(out.values(), key=lambda u: -u["points"])


# ---------------------------------------------------------------- dùng ở các trang

def _project(cfg) -> str:
    from urllib.parse import urlsplit
    u = getattr(cfg, "site_url", "") or ""
    return (urlsplit(u).netloc or u).removeprefix("www.")


def take(ui, user, cfg, action: str, points: int | None = None, n: int = 1, detail: str = "") -> int | None | bool:
    """Trừ credit trước khi chạy tác vụ: trả id (hoặc None nếu không tính credit) để hoàn khi lỗi; False khi Member
    không đủ credit (đã báo trên màn hình, không chạy tác vụ)."""
    pts = cost(action, n) if points is None else int(points)
    try:
        with _connect() as con:
            return spend(con, user, _project(cfg), action, pts, detail)
    except NotEnough as e:
        ui.notify(f"{COSTS[action][0]}: {e}", type="warning", position="bottom-right", multi_line=True)
        return False
    except RuntimeError:
        return None


def give_back(entry_id) -> None:
    if entry_id:
        with _connect() as con:
            refund(con, entry_id)


def my_balance(user) -> dict | None:
    """Số dư của Member đang mở trang; None với Owner / Admin / Guest."""
    if not A.is_member(user):
        return None
    try:
        with _connect() as con:
            return balance(con, str(user))
    except RuntimeError:
        return None


def member(user) -> bool:
    """Member: thấy giá bằng credit thay cho USD, không thấy ngân sách DataForSEO của dự án."""
    return A.is_member(user)


def label(user, action: str, n: int = 1, points: int | None = None) -> str:
    """Chữ " · N credit" gắn vào nút / gợi ý, chỉ hiện với Member."""
    if not A.is_member(user):
        return ""
    pts = cost(action, n) if points is None else int(points)
    return f" · {pts:,} credit".replace(",", ".") if pts else ""


# ---------------------------------------------------------------- trang Credit của tôi

def history(con, email: str, month: str | None = None) -> list[dict]:
    """Từng lần trừ credit của một người trong tháng, mới nhất trước."""
    ensure(con)
    return [{"at": r[0], "project": r[1], "action": r[2], "name": COSTS.get(r[2], (r[2],))[0], "points": r[3],
             "detail": r[4]}
            for r in con.execute("SELECT at, project, action, points, detail FROM points_log WHERE email = ? AND "
                                 "month = ? ORDER BY id DESC", (str(email).lower(), month or month_of()))]


def grants(con, email: str, month: str | None = None) -> list[dict]:
    ensure(con)
    return [{"at": r[0], "points": r[1], "by": r[2], "note": r[3]}
            for r in con.execute("SELECT at, points, by, note FROM points_grants WHERE email = ? AND month = ? "
                                 "ORDER BY id DESC", (str(email).lower(), month or month_of()))]


def by_action(rows: list[dict]) -> list[dict]:
    """Gộp lịch sử theo tác vụ: [{"action", "name", "times", "points"}], nhiều credit trước."""
    out: dict[str, dict] = {}
    for r in rows:
        a = out.setdefault(r["action"], {"action": r["action"], "name": r["name"], "times": 0, "points": 0})
        a["times"] += 1
        a["points"] += r["points"]
    return sorted(out.values(), key=lambda a: -a["points"])


DEPTHS = (10, 20, 30, 50, 100)


def calc(rank_keywords: int = 0, rank_depth: int = 20, rank_times: int = 1, **counts) -> dict:
    """Máy tính credit: check rank (số từ khóa × số lần, theo độ sâu) + số lần / số từ khóa của các tác vụ khác.
    Trả {"lines": [(tác vụ, tên, số lượng, credit)], "total"}."""
    lines = []
    if rank_keywords and rank_times:
        n = int(rank_keywords) * int(rank_times)
        lines.append(("rank", COSTS["rank"][0], n, rank_points([rank_depth]) * n))
    for k, v in counts.items():
        if k in COSTS and k != "rank" and v:
            lines.append((k, COSTS[k][0], int(v), cost(k, int(v))))
    return {"lines": lines, "total": sum(x[3] for x in lines)}
