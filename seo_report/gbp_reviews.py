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
CREATE TABLE IF NOT EXISTS gbp_review_drafts (  -- nháp câu trả lời (AI viết / team sửa), chờ duyệt rồi gửi
    location TEXT NOT NULL, review_id TEXT NOT NULL, text TEXT NOT NULL, by TEXT NOT NULL DEFAULT '', at TEXT NOT NULL,
    PRIMARY KEY (location, review_id)
);
CREATE TABLE IF NOT EXISTS gbp_review_insight (  -- AI phân tích đánh giá (lần gần nhất theo phạm vi chi nhánh)
    scope TEXT PRIMARY KEY, at TEXT NOT NULL, by TEXT NOT NULL DEFAULT '', data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gbp_reply_settings (  -- giọng thương hiệu + mẫu trả lời của dự án (JSON)
    k TEXT PRIMARY KEY, v TEXT NOT NULL
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


def clean(comment: str | None) -> str:
    """Bỏ phần Google tự dịch thêm vào cuối ("(Translated by Google) …" / "(Original) …"): giữ lời gốc của khách."""
    import re
    c = comment or ""
    m = re.search(r"\(Original\)\s*(.+)$", c, re.S)  # khách viết tiếng khác: Google để bản dịch trước, gốc sau
    if m:
        return m.group(1).strip()
    return re.split(r"\s*\(Translated by Google\)", c, maxsplit=1)[0].strip()


def rows(con, locations: list[str]) -> list[dict]:
    ensure_tables(con)
    if not locations:
        return []
    marks = ",".join("?" * len(locations))
    return [{"location": l_, "id": i, "author": a, "rating": r, "comment": clean(c), "created": cr, "updated": u,
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
        con.execute("DELETE FROM gbp_review_drafts WHERE location = ? AND review_id = ?", (location, review_id))


# ---------------------------------------------------------------- nháp trả lời (trả lời hàng loạt)

def save_draft(con, location: str, review_id: str, text: str, by: str = "") -> None:
    ensure_tables(con)
    with con:
        if (text or "").strip():
            con.execute("INSERT OR REPLACE INTO gbp_review_drafts VALUES (?, ?, ?, ?, ?)",
                        (location, review_id, text.strip(), str(by), _now()))
        else:
            con.execute("DELETE FROM gbp_review_drafts WHERE location = ? AND review_id = ?", (location, review_id))


def drafts(con) -> dict[tuple[str, str], str]:
    ensure_tables(con)
    return {(l_, r): t for l_, r, t in con.execute("SELECT location, review_id, text FROM gbp_review_drafts")}


def queue(rs: list[dict], limit: int = 60) -> list[dict]:
    """Hàng chờ trả lời: đánh giá chưa trả lời, 1–3 sao trước, mới trước."""
    todo = [r for r in rs if not r["reply"]]
    low = [r for r in todo if 0 < (r["rating"] or 0) <= 3]
    rest = [r for r in todo if not (0 < (r["rating"] or 0) <= 3)]
    low.sort(key=lambda r: r["created"] or "", reverse=True)
    rest.sort(key=lambda r: r["created"] or "", reverse=True)
    return (low + rest)[:limit]


def reply_speed(rs: list[dict], today=None, days: int = 90) -> dict:
    """Tốc độ trả lời đánh giá gần đây (theo chi nhánh và tổng): số ngày trung vị từ lúc khách viết tới lúc trả lời,
    % đã trả lời. {location | "_all": {"median_days", "replied", "total", "rate"}}"""
    from datetime import date, timedelta
    today = today or date.today()
    since = (today - timedelta(days=days)).isoformat()
    groups: dict[str, list[dict]] = {}
    for r in rs:
        if (r["created"] or "") >= since:
            groups.setdefault(r["location"], []).append(r)
            groups.setdefault("_all", []).append(r)
    out = {}
    for k, items in groups.items():
        waits = []
        for r in items:
            if r["reply"] and r.get("reply_at") and r["created"]:
                try:
                    a = datetime.fromisoformat(r["created"].replace("Z", "+00:00"))
                    b = datetime.fromisoformat(r["reply_at"].replace("Z", "+00:00"))
                    waits.append(max(0.0, (b - a).total_seconds() / 86400))
                except ValueError:
                    continue
        waits.sort()
        med = waits[len(waits) // 2] if waits else None
        replied = sum(1 for r in items if r["reply"])
        out[k] = {"median_days": round(med, 1) if med is not None else None, "replied": replied, "total": len(items),
                  "rate": replied / len(items) if items else None}
    return out


# ---------------------------------------------------------------- AI phân tích đánh giá

def insight_prompt(business: str, rs: list[dict], titles: dict[str, str]) -> str:
    lines = []
    for r in rs:
        if not (r["comment"] or "").strip():
            continue
        lines.append(f"[{titles.get(r['location'], '')}] {r['rating']}★ {(r['created'] or '')[:7]}: "
                     f"{r['comment'].strip()[:400]}")
    body = "\n".join(lines)
    return (
        f"Bạn phân tích đánh giá Google Maps của “{business}” để tìm điều khách khen / chê lặp lại.\n"
        f"Dữ liệu ({len(lines)} đánh giá có chữ, dạng [chi nhánh] sao tháng: nội dung):\n{body}\n\n"
        "Trả về JSON đúng dạng sau, tiếng Việt, không thêm chữ ngoài JSON:\n"
        '{"summary": "2–3 câu tổng quan",\n'
        ' "praise": [{"topic": "chủ đề khách khen", "count": số đánh giá nhắc tới, "example": "trích ngắn"}],\n'
        ' "complaints": [{"topic": "chủ đề khách chê", "count": số đánh giá nhắc tới, "example": "trích ngắn", '
        '"branches": ["chi nhánh hay bị chê điều này"]}],\n'
        ' "actions": ["việc nên làm cụ thể cho vận hành / marketing"]}\n'
        "praise và complaints mỗi loại tối đa 6 mục, xếp nhiều trước; count là ước lượng từ dữ liệu, không bịa; "
        "actions 3–5 việc. Chỉ dựa trên dữ liệu.")


def analyze(prov: dict, business: str, rs: list[dict], titles: dict[str, str], limit: int = 400) -> dict:
    """AI đọc tối đa `limit` đánh giá có chữ gần nhất (ưu tiên đủ các mức sao) và tóm tắt khen / chê / việc nên làm."""
    import json
    import re

    from . import ai_http as AH
    with_text = [r for r in rs if (r["comment"] or "").strip()]
    with_text.sort(key=lambda r: r["created"] or "", reverse=True)
    low = [r for r in with_text if 0 < (r["rating"] or 0) <= 3][: limit // 2]
    high = [r for r in with_text if (r["rating"] or 0) >= 4][: limit - len(low)]
    sample = low + high
    text = AH.ask(prov, insight_prompt(business, sample, titles), expect_json=True, max_tokens=1800)
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise AH.AIError("AI không trả về đúng định dạng, bấm Phân tích lại")
    try:
        data = json.loads(m.group(0))
    except ValueError as e:
        raise AH.AIError("AI trả về JSON lỗi, bấm Phân tích lại") from e

    def items(key, extra=()):
        out = []
        for x in data.get(key) or []:
            if isinstance(x, dict) and str(x.get("topic") or "").strip():
                d = {"topic": str(x["topic"]).strip(), "count": int(x.get("count") or 0) if str(
                    x.get("count") or "0").isdigit() else 0, "example": str(x.get("example") or "").strip()}
                if "branches" in extra:
                    d["branches"] = [str(b) for b in x.get("branches") or []][:5]
                out.append(d)
        return out[:6]
    return {"summary": str(data.get("summary") or "").strip(), "praise": items("praise"),
            "complaints": items("complaints", ("branches",)),
            "actions": [str(a).strip() for a in data.get("actions") or [] if str(a).strip()][:5],
            "sample": len(sample), "low": len(low)}


def save_insight(con, scope: str, data: dict, by: str = "") -> None:
    import json
    ensure_tables(con)
    with con:
        con.execute("INSERT OR REPLACE INTO gbp_review_insight VALUES (?, ?, ?, ?)",
                    (scope, _now(), str(by), json.dumps(data, ensure_ascii=False)))


def insight(con, scope: str) -> dict | None:
    import json
    ensure_tables(con)
    r = con.execute("SELECT at, by, data FROM gbp_review_insight WHERE scope = ?", (scope,)).fetchone()
    return {"at": r[0], "by": r[1], **json.loads(r[2])} if r else None


# ---------------------------------------------------------------- giọng thương hiệu + mẫu trả lời

DEFAULT_VOICE = {
    "brand": "",            # tên thương hiệu ký cuối / nhắc trong câu (trống: tên hồ sơ)
    "self": "",             # cửa hàng tự xưng (trống: tự chọn theo loại cửa hàng: shop / nha khoa / cửa hàng…)
    "customer": "anh/chị",  # cách gọi khách (dùng tên khách khi có)
    "tone": "thân thiện, gần gũi như nhân viên thật nhắn với khách; ngắn gọn, không văn mẫu",
    "contact": "",          # kênh để khách không hài lòng liên hệ (hotline / Zalo / email)
    "sign": "",             # câu ký cuối (không bắt buộc)
    "avoid": "không hứa bồi thường / hoàn tiền cụ thể; không đổ lỗi cho khách; không nhắc đối thủ",
    "notes": "",            # điều riêng của thương hiệu (chính sách bảo hành, dịch vụ nổi bật…)
}
# Cửa hàng tự xưng theo loại (không dùng "chúng tôi": nghe như văn bản hành chính). Khớp từ đầu danh sách.
UNITS = (("nha khoa", "nha khoa"), ("phòng khám", "phòng khám"), ("bệnh viện", "bệnh viện"), ("spa", "spa"),
         ("salon", "salon"), ("thẩm mỹ", "viện"), ("nhà hàng", "nhà hàng"), ("quán", "quán"), ("cafe", "quán"),
         ("cà phê", "quán"), ("khách sạn", "khách sạn"), ("homestay", "homestay"), ("trung tâm", "trung tâm"),
         ("kính", "shop"), ("shop", "shop"), ("store", "shop"), ("thời trang", "shop"), ("mỹ phẩm", "shop"))
OLD_SELF = {"chúng tôi", "chung toi"}  # mặc định cũ: coi như để trống (tự chọn)

# stars: "5" | "4" | "3" | "low" (1–2 sao) | "all" — mẫu hợp với đánh giá bao nhiêu sao.
# Mẫu dùng được cho mọi ngành (nói "sản phẩm / dịch vụ", không nói "kính"); {xung} là cách cửa hàng tự xưng.
DEFAULT_TEMPLATES = [
    {"id": "t5", "name": "5★ khen chung", "stars": "5",
     "text": "{thuong_hieu} cảm ơn {khach} nhiều ạ! Được {khach} hài lòng là niềm vui lớn nhất của cả team "
             "{chi_nhanh}. Hẹn sớm gặp lại {khach} nhé!"},
    {"id": "t5s", "name": "5★ khen nhân viên", "stars": "5",
     "text": "Cảm ơn {khach} đã dành lời khen cho các bạn ở {chi_nhanh} ạ! {xung} sẽ gửi lời khen này đến bạn đã hỗ "
             "trợ {khach}, chắc bạn ấy vui lắm. Lần sau ghé {xung}, {khach} cứ tìm bạn ấy nhé!"},
    {"id": "t5p", "name": "5★ khen sản phẩm / dịch vụ", "stars": "5",
     "text": "Vui quá khi {khach} ưng ý ạ! {xung} luôn chọn kỹ từng sản phẩm, dịch vụ để khách yên tâm khi đến. "
             "Cảm ơn {khach} đã tin tưởng {thuong_hieu}."},
    {"id": "t5r", "name": "5★ khách quen", "stars": "5",
     "text": "Cảm ơn {khach} đã luôn đồng hành cùng {thuong_hieu}! Có những khách như {khach} là động lực để {xung} "
             "làm tốt hơn mỗi ngày. Hẹn gặp {khach} lần tới ạ."},
    {"id": "t5n", "name": "5★ không có chữ", "stars": "5",
     "text": "{thuong_hieu} cảm ơn {khach} đã dành 5 sao ạ! Chúc {khach} một ngày thật vui."},
    {"id": "t5m", "name": "5★ không có chữ (ngắn)", "stars": "5",
     "text": "Cảm ơn {khach} nhiều nha! {xung} hẹn gặp lại {khach} ở {chi_nhanh} ạ."},
    {"id": "t4", "name": "4★ hài lòng", "stars": "4",
     "text": "Cảm ơn {khach} đã ghé {chi_nhanh} và dành 4 sao cho {xung} ạ! Nếu còn điểm nào chưa trọn vẹn, {khach} "
             "cứ chia sẻ thêm để lần sau {xung} phục vụ chu đáo hơn nhé."},
    {"id": "t4g", "name": "4★ có góp ý", "stars": "4",
     "text": "{thuong_hieu} cảm ơn {khach} vì lời khen và cả góp ý rất thật ạ. {xung} đã ghi lại để cải thiện, mong "
             "lần tới {khach} sẽ hài lòng trọn 5 sao."},
    {"id": "t3", "name": "3★ chưa như mong đợi", "stars": "3",
     "text": "Cảm ơn {khach} đã chia sẻ thật lòng ạ. {xung} rất tiếc vì lần này chưa được như {khach} mong đợi. "
             "{khach} nhắn {lien_he} kể thêm giúp {xung} nhé, {xung} muốn hỗ trợ {khach} kỹ hơn."},
    {"id": "t3c", "name": "3★ có chê cụ thể", "stars": "3",
     "text": "{thuong_hieu} ghi nhận góp ý của {khach} ạ. Những điểm {khach} nêu, {xung} đã chuyển quản lý {chi_nhanh} "
             "xem lại để chỉnh ngay. Cảm ơn {khach} đã giúp {xung} tốt hơn."},
    {"id": "tq", "name": "1–2★ chất lượng sản phẩm", "stars": "low",
     "text": "{thuong_hieu} thành thật xin lỗi {khach} vì sản phẩm chưa được như mong đợi ạ. {khach} ghé {chi_nhanh} "
             "hoặc nhắn {lien_he} giúp {xung} nhé, {xung} sẽ kiểm tra và hỗ trợ {khach} theo chính sách bảo hành."},
    {"id": "ts", "name": "1–2★ thái độ phục vụ", "stars": "low",
     "text": "{xung} thật sự xin lỗi {khach} vì cách phục vụ ở {chi_nhanh} đã làm {khach} không vui ạ. Đây không phải "
             "điều {thuong_hieu} muốn khách nhận được. {xung} đã báo quản lý chi nhánh xem lại, mong {khach} nhắn "
             "{lien_he} để {xung} được nghe và hỗ trợ trực tiếp."},
    {"id": "tw", "name": "1–2★ bảo hành / sau bán", "stars": "low",
     "text": "Xin lỗi {khach} vì việc bảo hành chưa làm {khach} yên tâm ạ. {thuong_hieu} muốn xem lại cụ thể trường hợp "
             "của {khach}; {khach} nhắn {lien_he} giúp {xung} nhé, quản lý sẽ liên hệ lại sớm nhất."},
    {"id": "tt", "name": "1–2★ chờ lâu", "stars": "low",
     "text": "Xin lỗi {khach} vì đã phải chờ lâu ở {chi_nhanh} ạ. {xung} đang sắp xếp thêm người vào giờ đông khách để "
             "không ai phải đợi như vậy nữa. Cảm ơn {khach} đã góp ý thẳng thắn."},
    {"id": "tp", "name": "1–2★ giá / chi phí", "stars": "low",
     "text": "{xung} xin lỗi vì phần chi phí chưa được giải thích rõ khiến {khach} chưa thoải mái ạ. {khach} nhắn "
             "{lien_he} để {xung} rà lại chi tiết cùng {khach} nhé."},
    {"id": "tl", "name": "1–2★ chung", "stars": "low",
     "text": "{thuong_hieu} rất tiếc khi {khach} chưa hài lòng ạ. {xung} muốn hiểu rõ chuyện đã xảy ra để sửa cho đúng, "
             "mong {khach} nhắn {lien_he} giúp {xung} nhé."},
    {"id": "ta", "name": "Cảm ơn chung (mọi mức sao)", "stars": "all",
     "text": "Cảm ơn {khach} đã dành thời gian đánh giá {thuong_hieu} – {chi_nhanh} ạ. Mỗi chia sẻ của {khach} đều giúp "
             "{xung} làm tốt hơn."},
    {"id": "ta2", "name": "Mời quay lại (mọi mức sao)", "stars": "all",
     "text": "Cảm ơn {khach} đã ghé {thuong_hieu}! {xung} luôn sẵn sàng hỗ trợ khi {khach} cần, hẹn gặp lại {khach} ạ."},
]
STAR_GROUP = {5: "5", 4: "4", 3: "3", 2: "low", 1: "low"}


def _setting(con, k: str, default):
    import json
    ensure_tables(con)
    r = con.execute("SELECT v FROM gbp_reply_settings WHERE k = ?", (k,)).fetchone()
    return json.loads(r[0]) if r else default


def _put_setting(con, k: str, v) -> None:
    import json
    ensure_tables(con)
    with con:
        con.execute("INSERT OR REPLACE INTO gbp_reply_settings VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))


def voice(con) -> dict:
    v = {**DEFAULT_VOICE, **(_setting(con, "voice", {}) or {})}
    if (v.get("self") or "").strip().lower() in OLD_SELF:
        v["self"] = ""
    return v


def self_name(v: dict, business: str = "") -> str:
    """Cách cửa hàng tự xưng: theo ô "Cửa hàng tự xưng" nếu đã điền, không thì đoán theo tên (nha khoa → "nha khoa",
    mắt kính / thời trang → "shop", còn lại "cửa hàng")."""
    own = (v.get("self") or "").strip()
    if own and own.lower() not in OLD_SELF:
        return own
    name = f"{v.get('brand') or ''} {business}".lower()
    return next((u for key, u in UNITS if key in name), "cửa hàng")


def save_voice(con, v: dict) -> dict:
    out = {k: str(v.get(k) or "").strip()[:500] for k in DEFAULT_VOICE}
    if out["self"].lower() in OLD_SELF:
        out["self"] = ""
    out["customer"] = out["customer"] or DEFAULT_VOICE["customer"]
    _put_setting(con, "voice", out)
    return out


def templates(con) -> list[dict]:
    return _setting(con, "templates", None) or [dict(t) for t in DEFAULT_TEMPLATES]


def save_templates(con, items: list[dict]) -> list[dict]:
    import secrets
    out = []
    for t in items:
        text = str(t.get("text") or "").strip()
        if not text:
            continue
        out.append({"id": str(t.get("id") or secrets.token_hex(4)), "name": str(t.get("name") or "Mẫu").strip()[:60],
                    "stars": t.get("stars") if t.get("stars") in ("5", "4", "3", "low", "all") else "all",
                    "text": text[:1500]})
    _put_setting(con, "templates", out)
    return out


def templates_for(items: list[dict], rating: int) -> list[dict]:
    """Mẫu hợp với số sao (mẫu cùng nhóm trước, mẫu "mọi mức sao" sau)."""
    g = STAR_GROUP.get(rating or 0, "all")
    return [t for t in items if t["stars"] == g] + [t for t in items if t["stars"] == "all"]


def fill(text: str, review: dict, branch: str, v: dict) -> str:
    """Điền mẫu: {khach} (tên khách hoặc cách gọi chung), {chi_nhanh}, {thuong_hieu}, {xung} (cửa hàng tự xưng),
    {lien_he}. Chữ đầu mỗi câu viết hoa (vd "{xung} xin lỗi" → "Shop xin lỗi")."""
    import re
    name = (review.get("author") or "").strip()
    who = f"{v.get('customer') or 'anh/chị'} {name.split()[-1]}" if name and len(name) < 40 else (
        v.get("customer") or "anh/chị")
    brand = v.get("brand") or (branch.split(" - ")[0] if branch else "") or "cửa hàng"
    me = self_name(v, brand)
    parts = [x.strip() for x in (branch or "").split(" - ") if x.strip()]
    where = f"chi nhánh {parts[-1]}" if len(parts) > 1 else (branch or brand)  # "Mắt Kính Tâm Đức - Gò Vấp" → "chi nhánh Gò Vấp"
    out = (text.replace("{khach}", who).replace("{chi_nhanh}", where).replace("{thuong_hieu}", brand)
           .replace("{xung}", me).replace("{lien_he}", v.get("contact") or "fanpage / hotline"))
    out = re.sub(r"(^|[.!?]\s+)(\w)", lambda m: m.group(1) + m.group(2).upper(), out)
    if v.get("sign") and v["sign"] not in out:
        out += "\n" + v["sign"]
    return out


# ---------------------------------------------------------------- AI viết câu trả lời

STAR_RULES = {
    5: "Khách rất hài lòng: cảm ơn chân thành, nhắc lại đúng điều khách khen (nhân viên, sản phẩm, dịch vụ cụ thể), "
       "mời quay lại. Ngắn, ấm áp; không quảng cáo dài.",
    4: "Khách hài lòng nhưng còn chút chưa trọn: cảm ơn, ghi nhận điểm khách khen; nếu khách nêu điểm chưa tốt thì "
       "nhận và nói sẽ cải thiện; mời góp ý thêm.",
    3: "Khách trung lập / có chê: cảm ơn, ghi nhận cụ thể điều chưa tốt, nói cách cải thiện (không hứa suông), mời "
       "liên hệ để hỗ trợ thêm.",
    2: "Khách không hài lòng: mở đầu bằng xin lỗi chân thành và thấu hiểu đúng vấn đề khách gặp; không cãi, không đổ "
       "lỗi, không giải thích dài dòng; nói đã ghi nhận / sẽ kiểm tra; mời khách liên hệ trực tiếp (kênh liên hệ) để "
       "xử lý riêng. Không hứa bồi thường / hoàn tiền cụ thể.",
    1: "Khách rất bức xúc: mở đầu bằng xin lỗi chân thành về trải nghiệm và thấu hiểu đúng vấn đề; giọng điềm tĩnh, "
       "tôn trọng; không cãi, không đổ lỗi, không giải thích dài, không thừa nhận lỗi pháp lý chi tiết; nói đã ghi nhận "
       "/ sẽ kiểm tra; mời khách liên hệ trực tiếp (kênh liên hệ) để xử lý riêng; tuyệt đối không tranh luận công khai; "
       "không hứa bồi thường / hoàn tiền cụ thể.",
}


def _style_hint(review: dict) -> str:
    """Gợi ý theo cách khách viết: không chữ / rất ngắn / dài; tiếng Việt hay tiếng nước ngoài."""
    import re
    text = (review.get("comment") or "").strip()
    words = len(text.split())
    hints = []
    if not text:
        hints.append("Khách chỉ chấm sao, không viết chữ: trả lời 1–2 câu ngắn, cảm ơn, không đoán nội dung.")
    elif words <= 8:
        hints.append("Khách viết rất ngắn: trả lời 1–2 câu.")
    elif words >= 80:
        hints.append("Khách viết dài, chi tiết: trả lời 3–5 câu, phản hồi đúng từng ý chính (tối đa 2–3 ý).")
    else:
        hints.append("Độ dài vừa: trả lời 2–4 câu.")
    if text and not re.search(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", text.lower()):
        hints.append("Đánh giá không phải tiếng Việt: trả lời bằng đúng ngôn ngữ khách dùng.")
    if text.isupper() or text.count("!") >= 3:
        hints.append("Khách đang rất bức xúc: giọng điềm tĩnh, xin lỗi trước.")
    return " ".join(hints)


def draft_prompt(business: str, review: dict, note: str = "", v: dict | None = None, branch: str = "") -> str:
    v = {**DEFAULT_VOICE, **(v or {})}
    stars = review.get("rating") or 0
    rule = STAR_RULES.get(stars, STAR_RULES[3])
    brand = v.get("brand") or business
    me = self_name(v, brand)
    return (
        f"Bạn là quản lý cửa hàng “{brand}”" + (f" (chi nhánh {branch})" if branch else "")
        + " trả lời một đánh giá trên Google Maps. Câu trả lời hiện công khai, khách khác cũng đọc.\n"
        f"Đánh giá {stars}/5 sao của {review.get('author') or 'khách'}:\n"
        f"\"\"\"{review.get('comment') or '(không có chữ)'}\"\"\"\n"
        + (f"Ghi chú của team cho đánh giá này: {note}\n" if note else "")
        + "\nGiọng thương hiệu:\n"
        f"- Cửa hàng tự xưng là “{me}” hoặc bằng tên “{brand}” (đổi qua lại cho tự nhiên, vd “{me} xin lỗi…”, "
        f"“{brand} cảm ơn…”). KHÔNG dùng “chúng tôi”, “bên em”, “quý khách”.\n"
        f"- Gọi khách là “{v['customer']}” kèm tên nếu tự nhiên (vd “anh/chị An”; biết rõ giới tính thì “anh An” / "
        "“chị An”).\n"
        f"- Tone: {v['tone']}.\n"
        + (f"- Kênh liên hệ để hỗ trợ riêng: {v['contact']}.\n" if v.get("contact") else
           "- Chưa có kênh liên hệ: mời khách nhắn tin / đến cửa hàng, không bịa số điện thoại.\n")
        + (f"- Thông tin thương hiệu được phép nhắc: {v['notes']}.\n" if v.get("notes") else "")
        + (f"- Tránh: {v['avoid']}.\n" if v.get("avoid") else "")
        + (f"- Ký cuối: {v['sign']}\n" if v.get("sign") else "")
        + f"\nCách trả lời cho mức {stars} sao: {rule}\n"
        f"Theo cách khách viết: {_style_hint(review)}\n"
        "\nQuy tắc chung:\n"
        "- Viết như nhân viên thật nhắn với khách: câu ngắn, dễ đọc; dùng “ạ”, “nhé”, “nha” vừa phải (tối đa 2 lần).\n"
        "- Không văn mẫu, không từ sáo rỗng (“vô cùng trân trọng”, “hân hạnh”, “rất lấy làm tiếc”, “quý khách”); câu mở "
        "đầu khác nhau, không lần nào cũng bắt đầu bằng “Cảm ơn”.\n"
        "- Nhắc đúng chi tiết khách nêu; không bịa thông tin (giá, chương trình, địa chỉ, số điện thoại, tên nhân viên) "
        "không có trong đánh giá / ghi chú / thông tin thương hiệu.\n"
        "- Không nhồi từ khóa SEO, tối đa 1 emoji (đánh giá 1–3 sao: không emoji), không hashtag, không link.\n"
        "Chỉ trả về nội dung câu trả lời.")


def draft(prov: dict, business: str, review: dict, note: str = "", v: dict | None = None, branch: str = "") -> str:
    from . import ai_http as AH
    return AH.ask(prov, draft_prompt(business, review, note, v, branch), max_tokens=500).strip().strip('"')
