"""Đánh giá Google Maps của các hồ sơ Business Profile đã gắn (My Business API v4, miễn phí, cùng quyền
business.manage và cùng đơn xin dùng API với phần Local SEO).

- Lấy toàn bộ đánh giá mỗi lần lấy số Local SEO (`gbp_reviews`), kèm câu trả lời của chủ hồ sơ.
- Trả lời một đánh giá: gửi lên Google ngay khi người dùng bấm Gửi (công khai trên Google Maps).
- AI viết nháp câu trả lời (người dùng sửa / duyệt trước khi gửi).
"""
import sqlite3
from datetime import datetime, timezone

BASE = "https://mybusiness.googleapis.com/v4"
STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
SCHEMA = """
CREATE TABLE IF NOT EXISTS gbp_reviews (
    location TEXT NOT NULL,        -- locations/123…
    review_id TEXT NOT NULL,
    author TEXT,
    rating INTEGER,                -- 1–5 (0: không rõ)
    comment TEXT,
    created TEXT,
    updated TEXT,
    reply TEXT,
    reply_at TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (location, review_id)
);
CREATE TABLE IF NOT EXISTS gbp_review_stats (
    location TEXT PRIMARY KEY,
    average REAL,
    total INTEGER,
    fetched_at TEXT NOT NULL
);
"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(loc: dict) -> str:
    """accounts/A/locations/L (API v4 cần cả tài khoản)."""
    return f"{loc['account']}/{loc['name']}"


class Client:
    def __init__(self, creds, session=None):
        if session is None:
            from google.auth.transport.requests import AuthorizedSession
            session = AuthorizedSession(creds)
        self.s = session

    def _check(self, r) -> dict:
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    def reviews(self, loc: dict) -> dict:
        """{"reviews": [...], "averageRating", "totalReviewCount"} (gộp mọi trang)."""
        out, token, head = [], None, {}
        while True:
            params = {"pageSize": 50, **({"pageToken": token} if token else {})}
            d = self._check(self.s.get(f"{BASE}/{_path(loc)}/reviews", params=params, timeout=60))
            head = head or d
            out += d.get("reviews") or []
            token = d.get("nextPageToken")
            if not token:
                return {"reviews": out, "averageRating": head.get("averageRating"),
                        "totalReviewCount": head.get("totalReviewCount")}

    def reply(self, loc: dict, review_id: str, text: str) -> dict:
        return self._check(self.s.put(f"{BASE}/{_path(loc)}/reviews/{review_id}/reply", json={"comment": text},
                                      timeout=60))


def save(con, location: str, data: dict) -> int:
    ensure_tables(con)
    now = _now()
    with con:
        for r in data.get("reviews") or []:
            rep = r.get("reviewReply") or {}
            con.execute("INSERT OR REPLACE INTO gbp_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (location, r.get("reviewId") or r.get("name", "").rsplit("/", 1)[-1],
                         (r.get("reviewer") or {}).get("displayName") or "", STARS.get(r.get("starRating"), 0),
                         r.get("comment") or "", r.get("createTime"), r.get("updateTime"), rep.get("comment"),
                         rep.get("updateTime"), now))
        con.execute("INSERT OR REPLACE INTO gbp_review_stats VALUES (?, ?, ?, ?)",
                    (location, data.get("averageRating"), data.get("totalReviewCount"), now))
    return len(data.get("reviews") or [])


def refresh(con, locs: list[dict], client, log=print) -> int:
    n = 0
    for loc in locs:
        try:
            n += save(con, loc["name"], client.reviews(loc))
        except Exception as e:  # noqa: BLE001
            from .gbp import explain
            log(f"Không lấy được đánh giá {loc['title']}: {explain(e)}")
    return n


def rows(con, locations: list[str]) -> list[dict]:
    ensure_tables(con)
    if not locations:
        return []
    marks = ",".join("?" * len(locations))
    return [{"location": l_, "id": i, "author": a, "rating": r, "comment": c or "", "created": cr, "updated": u,
             "reply": rp, "reply_at": ra}
            for l_, i, a, r, c, cr, u, rp, ra in con.execute(
                f"SELECT location, review_id, author, rating, comment, created, updated, reply, reply_at FROM "
                f"gbp_reviews WHERE location IN ({marks}) ORDER BY created DESC", locations)]


def stats(rs: list[dict]) -> dict:
    """Điểm trung bình, tổng, chưa trả lời, phân bố sao, theo tháng (số đánh giá, điểm TB)."""
    rated = [r for r in rs if r["rating"]]
    months: dict[str, list[int]] = {}
    for r in rated:
        months.setdefault((r["created"] or "")[:7], []).append(r["rating"])
    return {"total": len(rs), "avg": round(sum(r["rating"] for r in rated) / len(rated), 2) if rated else None,
            "unanswered": sum(1 for r in rs if not r["reply"]),
            "low_unanswered": sum(1 for r in rs if not r["reply"] and 0 < r["rating"] <= 3),
            "stars": {s: sum(1 for r in rated if r["rating"] == s) for s in range(5, 0, -1)},
            "months": [{"month": m, "count": len(v), "avg": round(sum(v) / len(v), 2)}
                       for m, v in sorted(months.items()) if m]}


def mark_replied(con, location: str, review_id: str, text: str) -> None:
    with con:
        con.execute("UPDATE gbp_reviews SET reply = ?, reply_at = ? WHERE location = ? AND review_id = ?",
                    (text, _now(), location, review_id))


def draft_prompt(business: str, review: dict, note: str = "") -> str:
    stars = review.get("rating") or 0
    return (
        f"Bạn là chủ cửa hàng “{business}” trả lời một đánh giá trên Google Maps.\n"
        f"Đánh giá {stars}/5 sao của {review.get('author') or 'khách'}:\n\"\"\"{review.get('comment') or '(không có chữ)'}\"\"\"\n"
        + (f"Ghi chú của team: {note}\n" if note else "") +
        "Viết câu trả lời tiếng Việt, 2–4 câu, lịch sự, tự nhiên, xưng “chúng tôi” / gọi khách là “anh/chị”.\n"
        "- Cảm ơn cụ thể theo nội dung khách nhắc (không chung chung).\n"
        "- Đánh giá 1–3 sao: xin lỗi, không cãi, mời khách liên hệ để hỗ trợ; không hứa bồi thường cụ thể.\n"
        "- Không bịa thông tin (giá, chương trình, địa chỉ, số điện thoại) không có trong đánh giá / ghi chú.\n"
        "- Không nhồi từ khóa, không dùng emoji quá 1 cái.\n"
        "Chỉ trả về nội dung câu trả lời.")


def draft(prov: dict, business: str, review: dict, note: str = "") -> str:
    from . import ai_http as AH
    return AH.ask(prov, draft_prompt(business, review, note), max_tokens=400).strip().strip('"')
