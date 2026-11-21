"""Bài đăng Google Business Profile (GMB post) soạn và đăng từ tool (My Business API v4 · localPosts, miễn phí, cùng
quyền business.manage và cùng API “Google My Business API” với phần đánh giá).

- Soạn bài: loại (Cập nhật / Ưu đãi / Sự kiện), nội dung (AI viết nháp được), nút kêu gọi, ảnh.
- Đăng ngay hoặc đặt lịch: Google không có hẹn giờ, nên tool giữ bài và tự đăng đúng giờ (vòng lịch của máy chủ web;
  máy tắt lúc tới giờ thì đăng bù khi chạy lại).
- Một bài đăng lên một hoặc nhiều chi nhánh; mỗi chi nhánh ghi kết quả riêng (đã đăng / Google từ chối / lỗi).
- Ảnh: Google tải ảnh qua một link công khai, nên ảnh lưu trong thư mục gbp_media và phục vụ ở /gbp-media/<tên ngẫu
  nhiên> (không đoán được tên, không cần đăng nhập).
"""
import json
import re
import secrets
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from .gbp_reviews import BASE, _path

KINDS = {"STANDARD": "Cập nhật", "OFFER": "Ưu đãi", "EVENT": "Sự kiện"}
CTAS = {"": "Không có nút", "LEARN_MORE": "Tìm hiểu thêm", "BOOK": "Đặt lịch", "ORDER": "Đặt hàng",
        "SHOP": "Mua hàng", "SIGN_UP": "Đăng ký", "CALL": "Gọi ngay"}
STATUS = {"draft": ("Nháp", "grey"), "scheduled": ("Đã lên lịch", "blue"), "posting": ("Đang đăng", "blue"),
          "posted": ("Đã đăng", "green"), "partial": ("Đăng một phần", "amber"), "failed": ("Lỗi", "red")}
MAX_CHARS = 1500
IMG_EXT = {"image/jpeg": ".jpg", "image/png": ".png"}
MAX_IMG = 5 * 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}\.(jpg|png)$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS gbp_posts (
    id INTEGER PRIMARY KEY,
    locations TEXT NOT NULL,        -- JSON: ["locations/…", …]
    kind TEXT NOT NULL DEFAULT 'STANDARD',
    summary TEXT NOT NULL DEFAULT '',
    cta TEXT NOT NULL DEFAULT '',
    cta_url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '', -- tiêu đề sự kiện / ưu đãi
    start TEXT, end TEXT,           -- ngày sự kiện / ưu đãi (YYYY-MM-DD)
    coupon TEXT NOT NULL DEFAULT '', terms TEXT NOT NULL DEFAULT '', redeem_url TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT '', -- tên tệp trong gbp_media
    image_url TEXT NOT NULL DEFAULT '', -- link công khai Google tải ảnh
    scheduled_at TEXT,              -- UTC ISO; NULL: nháp / đăng ngay
    status TEXT NOT NULL DEFAULT 'draft',
    results TEXT NOT NULL DEFAULT '{}', -- JSON: {location: {"name", "state", "url", "error"}}
    created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, posted_at TEXT
);
"""
FIELDS = ("locations", "kind", "summary", "cta", "cta_url", "title", "start", "end", "coupon", "terms", "redeem_url",
          "image", "image_url", "scheduled_at")


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(gbp_posts)")}
    if "source" not in cols:  # tool: soạn trên tool · google: bài team đăng thẳng trên Google, tool đọc về
        with con:
            con.execute("ALTER TABLE gbp_posts ADD COLUMN source TEXT NOT NULL DEFAULT 'tool'")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- ảnh

MEDIA = {"base": None}  # thư mục dữ liệu chính, máy chủ web gán lúc khởi động (route /gbp-media đọc ở đây)


def media_dir(base_dir: Path | None = None) -> Path:
    d = Path(base_dir or MEDIA["base"] or "data") / "gbp_media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_image(base_dir: Path | None, data: bytes, content_type: str) -> str:
    """Lưu ảnh tải lên (JPG / PNG, tối đa 5 MB), trả tên tệp ngẫu nhiên."""
    ext = IMG_EXT.get((content_type or "").split(";")[0].strip().lower())
    if not ext:
        if data[:3] == b"\xff\xd8\xff":
            ext = ".jpg"
        elif data[:8] == b"\x89PNG\r\n\x1a\n":
            ext = ".png"
        else:
            raise ValueError("Chỉ nhận ảnh JPG hoặc PNG")
    if len(data) > MAX_IMG:
        raise ValueError("Ảnh lớn hơn 5 MB (Google chỉ nhận ảnh tới 5 MB)")
    if len(data) < 10 * 1024:
        raise ValueError("Ảnh quá nhỏ (Google cần ảnh từ 10 KB, cạnh ngắn từ 250 px)")
    name = secrets.token_urlsafe(18) + ext
    (media_dir(base_dir) / name).write_bytes(data)
    return name


def image_file(base_dir: Path | None, name: str) -> Path | None:
    """Đường dẫn tệp ảnh cho route công khai; None khi tên không hợp lệ / không có tệp."""
    if not NAME_RE.match(name or ""):
        return None
    p = media_dir(base_dir) / name
    return p if p.is_file() else None


# ---------------------------------------------------------------- lưu / đọc

def _row(r, names) -> dict:
    d = dict(zip(names, r))
    d["locations"] = json.loads(d["locations"] or "[]")
    d["results"] = json.loads(d["results"] or "{}")
    return d


def get(con, pid: int) -> dict | None:
    ensure_tables(con)
    cur = con.execute("SELECT * FROM gbp_posts WHERE id = ?", (pid,))
    r = cur.fetchone()
    return _row(r, [x[0] for x in cur.description]) if r else None


def all_posts(con) -> list[dict]:
    ensure_tables(con)
    cur = con.execute("SELECT * FROM gbp_posts ORDER BY COALESCE(posted_at, scheduled_at, created_at) DESC, id DESC")
    names = [x[0] for x in cur.description]
    return [_row(r, names) for r in cur.fetchall()]


def validate(p: dict) -> None:
    """Kiểm tra trước khi lên lịch / đăng (nháp thì không cần đủ)."""
    if not p.get("locations"):
        raise ValueError("Chọn ít nhất một chi nhánh")
    text = (p.get("summary") or "").strip()
    if not text:
        raise ValueError("Nội dung bài đang trống")
    if len(text) > MAX_CHARS:
        raise ValueError(f"Nội dung dài {len(text)} ký tự; Google cho tối đa {MAX_CHARS}")
    kind = p.get("kind") or "STANDARD"
    if kind not in KINDS:
        raise ValueError("Loại bài không hợp lệ")
    if kind in ("EVENT", "OFFER"):
        if not (p.get("title") or "").strip():
            raise ValueError("Bài " + KINDS[kind].lower() + " cần tiêu đề")
        if not p.get("start") or not p.get("end"):
            raise ValueError("Bài " + KINDS[kind].lower() + " cần ngày bắt đầu và kết thúc")
        if p["start"] > p["end"]:
            raise ValueError("Ngày bắt đầu sau ngày kết thúc")
    if p.get("cta") and kind != "OFFER":
        if p["cta"] not in CTAS:
            raise ValueError("Nút kêu gọi không hợp lệ")
        if p["cta"] != "CALL" and not re.match(r"^https?://", p.get("cta_url") or ""):
            raise ValueError("Nút kêu gọi cần link bắt đầu bằng http:// hoặc https://")
    if p.get("image") and not re.match(r"^https://", p.get("image_url") or ""):
        raise ValueError("Ảnh cần link công khai https (mở tool bằng tên miền public, không phải localhost)")


def save(con, data: dict, user: str = "", pid: int | None = None, status: str = "draft") -> int:
    """Lưu bài (mới hoặc sửa). status: draft | scheduled. Bài đã đăng thì không sửa được."""
    ensure_tables(con)
    row = {k: data.get(k) for k in FIELDS}
    row["locations"] = json.dumps(list(dict.fromkeys(row.get("locations") or [])))
    for k in ("kind", "summary", "cta", "cta_url", "title", "coupon", "terms", "redeem_url", "image", "image_url"):
        row[k] = (row.get(k) or "").strip() if k != "summary" else (row.get(k) or "").strip()
    row["kind"] = row["kind"] or "STANDARD"
    if status == "scheduled":
        validate({**data, "summary": row["summary"]})
        if not row.get("scheduled_at"):
            raise ValueError("Chọn ngày giờ đăng")
    else:
        row["scheduled_at"] = None
    with con:
        if pid:
            cur = con.execute("SELECT status FROM gbp_posts WHERE id = ?", (pid,)).fetchone()
            if not cur:
                raise ValueError("Không thấy bài")
            if cur[0] in ("posted", "partial", "posting"):
                raise ValueError("Bài đã đăng, không sửa được (Google không cho sửa qua tool); tạo bài mới")
            con.execute(f"UPDATE gbp_posts SET {', '.join(f'{k} = ?' for k in row)}, status = ? WHERE id = ?",
                        (*row.values(), status, pid))
            return pid
        return con.execute(
            f"INSERT INTO gbp_posts ({', '.join(row)}, status, created_by, created_at) "
            f"VALUES ({', '.join('?' * len(row))}, ?, ?, ?)", (*row.values(), status, str(user), _now())).lastrowid


def delete(con, pid: int) -> None:
    with con:
        con.execute("DELETE FROM gbp_posts WHERE id = ? AND status NOT IN ('posting')", (pid,))


def due(con, now: datetime | None = None) -> list[int]:
    """Bài đã lên lịch tới giờ đăng."""
    ensure_tables(con)
    now = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return [r[0] for r in con.execute("SELECT id FROM gbp_posts WHERE status = 'scheduled' AND scheduled_at <= ? "
                                      "ORDER BY scheduled_at", (now,))]


# ---------------------------------------------------------------- gọi API

def _ymd(iso: str) -> dict:
    d = date.fromisoformat(iso)
    return {"year": d.year, "month": d.month, "day": d.day}


def body(p: dict) -> dict:
    """Bài → nội dung gửi lên API localPosts."""
    kind = p.get("kind") or "STANDARD"
    b = {"languageCode": "vi", "summary": (p.get("summary") or "").strip(), "topicType": kind}
    if kind in ("EVENT", "OFFER"):
        b["event"] = {"title": p["title"].strip(),
                      "schedule": {"startDate": _ymd(p["start"]), "endDate": _ymd(p["end"])}}
    if kind == "OFFER":
        offer = {k2: (p.get(k1) or "").strip() for k1, k2 in (("coupon", "couponCode"), ("redeem_url", "redeemOnlineUrl"),
                                                              ("terms", "termsConditions")) if (p.get(k1) or "").strip()}
        if offer:
            b["offer"] = offer
    elif p.get("cta"):
        b["callToAction"] = {"actionType": p["cta"], **({"url": p["cta_url"]} if p["cta"] != "CALL" else {})}
    if p.get("image_url"):
        b["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": p["image_url"]}]
    return b


class Client:
    def __init__(self, creds, session=None):
        if session is None:
            from google.auth.transport.requests import AuthorizedSession
            session = AuthorizedSession(creds)
        self.s = session

    def _check(self, r) -> dict:
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code} {r.text[:400]}")
        return r.json() if r.content else {}

    def create(self, loc: dict, b: dict) -> dict:
        return self._check(self.s.post(f"{BASE}/{_path(loc)}/localPosts", json=b, timeout=60))

    def list(self, loc: dict) -> list[dict]:
        out, token = [], None
        while True:
            params = {"pageSize": 100, **({"pageToken": token} if token else {})}
            d = self._check(self.s.get(f"{BASE}/{_path(loc)}/localPosts", params=params, timeout=60))
            out += d.get("localPosts") or []
            token = d.get("nextPageToken")
            if not token:
                return out


def publish(con, pid: int, locs: list[dict], client, explain=str) -> dict:
    """Đăng một bài lên các chi nhánh của nó. Chi nhánh đã đăng thành công trước đó thì bỏ qua (đăng lại phần lỗi)."""
    p = get(con, pid)
    if not p:
        raise ValueError("Không thấy bài")
    validate(p)
    by_name = {x["name"]: x for x in locs}
    with con:
        con.execute("UPDATE gbp_posts SET status = 'posting' WHERE id = ?", (pid,))
    results = dict(p["results"])
    b = body(p)
    for name in p["locations"]:
        if (results.get(name) or {}).get("name"):
            continue
        loc = by_name.get(name)
        if not loc:
            results[name] = {"error": "Chi nhánh không còn gắn với dự án"}
            continue
        try:
            r = client.create(loc, b)
            results[name] = {"name": r.get("name", ""), "state": r.get("state", ""), "url": r.get("searchUrl", ""),
                             "error": ""}
        except Exception as e:  # noqa: BLE001
            results[name] = {"error": explain(e)}
    ok = sum(1 for v in results.values() if v.get("name"))
    status = "posted" if ok == len(p["locations"]) else "partial" if ok else "failed"
    with con:
        con.execute("UPDATE gbp_posts SET status = ?, results = ?, posted_at = ? WHERE id = ?",
                    (status, json.dumps(results, ensure_ascii=False), _now() if ok else None, pid))
    return {"status": status, "ok": ok, "total": len(p["locations"]), "results": results}


def mark_failed(con, pid: int, error: str) -> None:
    with con:
        con.execute("UPDATE gbp_posts SET status = 'failed', results = ? WHERE id = ?",
                    (json.dumps({"_": {"error": (error or "")[:300]}}, ensure_ascii=False), pid))


def _date_iso(d: dict | None) -> str | None:
    try:
        return date(d["year"], d["month"], d["day"]).isoformat() if d else None
    except (KeyError, TypeError, ValueError):
        return None


def import_from_google(con, locs: list[dict], client, log=print) -> dict:
    """Đọc mọi bài trên Google của các chi nhánh: bài do tool đăng thì cập nhật trạng thái (đã hiện / bị từ chối);
    bài team đăng thẳng trên Google thì thêm vào danh sách (nguồn "google"). Cùng nội dung, cùng loại, cùng ngày ở nhiều
    chi nhánh gộp thành một bài. Trả {"new", "updated"}."""
    ensure_tables(con)
    known: dict[str, tuple[int, str]] = {}  # tên bài trên Google -> (id bài trong tool, chi nhánh)
    for p in all_posts(con):
        for loc_name, v in p["results"].items():
            if v.get("name"):
                known[v["name"]] = (p["id"], loc_name)
    groups: dict[tuple, dict] = {}
    updated: set[int] = set()
    for loc in locs:
        try:
            items = client.list(loc)
        except Exception as e:  # noqa: BLE001
            from .gbp import explain
            log(f"Không đọc được bài đăng {loc.get('title', loc['name'])}: {explain(e)}")
            continue
        for lp in items:
            gname = lp.get("name") or ""
            if gname in known:
                pid, loc_name = known[gname]
                p = get(con, pid)
                v = p["results"].get(loc_name) or {}
                if lp.get("state") and lp["state"] != v.get("state"):
                    v.update(state=lp["state"], url=lp.get("searchUrl") or v.get("url", ""))
                    p["results"][loc_name] = v
                    with con:
                        con.execute("UPDATE gbp_posts SET results = ? WHERE id = ?",
                                    (json.dumps(p["results"], ensure_ascii=False), pid))
                    updated.add(pid)
                continue
            ev = lp.get("event") or {}
            sch = ev.get("schedule") or {}
            media = (lp.get("media") or [{}])[0]
            key = ((lp.get("summary") or "").strip(), lp.get("topicType") or "STANDARD", (lp.get("createTime") or "")[:10],
                   ev.get("title") or "")
            g = groups.setdefault(key, {
                "kind": lp.get("topicType") if lp.get("topicType") in KINDS else "STANDARD",
                "summary": key[0], "title": ev.get("title") or "", "start": _date_iso(sch.get("startDate")),
                "end": _date_iso(sch.get("endDate")),
                "cta": (lp.get("callToAction") or {}).get("actionType", "") if (lp.get("callToAction") or {}).get(
                    "actionType") in CTAS else "", "cta_url": (lp.get("callToAction") or {}).get("url", ""),
                "coupon": (lp.get("offer") or {}).get("couponCode", ""),
                "terms": (lp.get("offer") or {}).get("termsConditions", ""),
                "redeem_url": (lp.get("offer") or {}).get("redeemOnlineUrl", ""),
                "image_url": media.get("googleUrl") or media.get("sourceUrl") or "",
                "posted_at": lp.get("createTime"), "locations": [], "results": {}})
            g["locations"].append(loc["name"])
            g["results"][loc["name"]] = {"name": gname, "state": lp.get("state", ""), "url": lp.get("searchUrl", ""),
                                         "error": ""}
    with con:
        for g in groups.values():
            con.execute(
                "INSERT INTO gbp_posts (locations, kind, summary, cta, cta_url, title, start, end, coupon, terms, "
                "redeem_url, image, image_url, scheduled_at, status, results, created_by, created_at, posted_at, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, NULL, 'posted', ?, 'Google', ?, ?, 'google')",
                (json.dumps(g["locations"]), g["kind"], g["summary"], g["cta"], g["cta_url"], g["title"], g["start"],
                 g["end"], g["coupon"], g["terms"], g["redeem_url"], g["image_url"],
                 json.dumps(g["results"], ensure_ascii=False), _now(), g["posted_at"]))
    return {"new": len(groups), "updated": len(updated)}


def sync_states(con, locs: list[dict], client) -> int:
    """Đọc lại trạng thái bài đã đăng trên Google (LIVE / REJECTED / PROCESSING) để báo bài bị từ chối."""
    states: dict[str, dict] = {}
    for loc in locs:
        try:
            for lp in client.list(loc):
                states[lp.get("name", "")] = lp
        except Exception:  # noqa: BLE001
            continue
    n = 0
    for p in all_posts(con):
        changed = False
        for v in p["results"].values():
            lp = states.get(v.get("name") or "")
            if lp and lp.get("state") and lp["state"] != v.get("state"):
                v["state"] = lp["state"]
                v["url"] = lp.get("searchUrl") or v.get("url", "")
                changed = True
        if changed:
            n += 1
            with con:
                con.execute("UPDATE gbp_posts SET results = ? WHERE id = ?",
                            (json.dumps(p["results"], ensure_ascii=False), p["id"]))
    return n


# ---------------------------------------------------------------- AI viết nháp

def draft_prompt(business: str, kind: str, topic: str, extra: str = "") -> str:
    return (
        f"Bạn viết bài đăng Google Business Profile (bài hiện trên Google Maps / Search) cho “{business}”.\n"
        f"Loại bài: {KINDS.get(kind, 'Cập nhật')}.\nChủ đề / thông tin team đưa: {topic}\n"
        + (f"Ghi chú thêm: {extra}\n" if extra else "") +
        "Yêu cầu:\n"
        "- Tiếng Việt tự nhiên, 80–180 từ, câu đầu thu hút (hiện trong bản xem trước), 1 lời kêu gọi cuối bài.\n"
        "- Lồng tự nhiên 1–2 từ khóa địa phương (dịch vụ + khu vực) nếu có trong thông tin; không nhồi từ khóa.\n"
        "- KHÔNG ghi số điện thoại, link, mã giảm giá trong nội dung (Google hay từ chối; nút / mã nhập riêng).\n"
        "- Không bịa giá, thời gian, chương trình không có trong thông tin. Tối đa 2 emoji, không hashtag.\n"
        "Chỉ trả về nội dung bài.")


def draft(prov: dict, business: str, kind: str, topic: str, extra: str = "") -> str:
    from . import ai_http as AH
    text = AH.ask(prov, draft_prompt(business, kind, topic, extra), max_tokens=700).strip().strip('"')
    return text[:MAX_CHARS]
