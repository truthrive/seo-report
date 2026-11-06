"""Dự án = một website. Tool chạy cho nhiều website; mỗi dự án có cấu hình riêng (GSC, GA4, từ khóa thương hiệu, ngân
sách check rank, sheet OKR) và một file dữ liệu SQLite riêng.

Mỗi dự án một file dữ liệu để số liệu các khách hàng không bao giờ lẫn vào nhau: mọi truy vấn có sẵn chỉ thấy đúng file
của dự án đang mở. Danh sách dự án (và tài khoản, phân quyền) nằm trong file dữ liệu chính `db_path` của config.toml;
dự án đầu tiên tạo từ config.toml và dùng luôn file đó, nên dữ liệu đang có không phải chuyển đi đâu.
"""
import json
import re
import sqlite3
import unicodedata
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, _ga4_property

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    site_url TEXT NOT NULL,
    ga4_property TEXT NOT NULL DEFAULT '',
    db_file TEXT NOT NULL,
    settings TEXT NOT NULL DEFAULT '{}',
    logo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    updated_at TEXT,
    updated_by TEXT,
    archived_at TEXT,
    archived_by TEXT
);
"""

# Cấu hình riêng từng dự án ngoài GSC / GA4 (lưu dạng JSON trong cột settings).
DEFAULTS = {"brand_terms": [], "rank_budget_usd": 20.0, "location_code": 2704, "language_code": "vi",
            "device": "mobile", "se_domain": "google.com.vn", "okr_sheet": "", "okr_tab": "OKRs 3 tháng", "weekly_tab": "Weekly Task Tracker",
            "rank_paused": False}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure(con: sqlite3.Connection, base: Config, user: str = "config.toml") -> None:
    """Tạo bảng dự án; lần đầu tạo dự án số 1 từ config.toml, dùng luôn file dữ liệu hiện có."""
    con.executescript(SCHEMA)
    # Logo cũ trỏ tới file ảnh trong tool (đã bỏ): để trống, lấy lại logo từ website ở màn Dự án
    con.execute("UPDATE projects SET logo = '' WHERE logo LIKE '/assets/%'")
    con.commit()
    if con.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
        return
    settings = {"brand_terms": list(base.keywords.brand_terms), "rank_budget_usd": base.rank.monthly_budget_usd,
                "location_code": base.rank.location_code, "language_code": base.rank.language_code,
                "device": base.rank.device, "okr_sheet": base.okr.sheet, "okr_tab": base.okr.okr_tab,
                "weekly_tab": base.okr.weekly_tab}
    logo = ""  # tool tự lấy logo của website ở màn Dự án
    con.execute("INSERT INTO projects (slug, name, site_url, ga4_property, db_file, settings, logo, created_at, "
                "created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (slugify(domain(base.site_url)), domain(base.site_url), base.site_url, base.ga4_property,
                 base.db_path.name, json.dumps(settings, ensure_ascii=False), logo, _now(), user))
    con.commit()


def domain(site_url: str) -> str:
    """'sc-domain:abc.com' / 'https://www.abc.com/' → 'abc.com'."""
    s = site_url.strip().removeprefix("sc-domain:")
    s = re.sub(r"^https?://", "", s).split("/")[0]
    return s.removeprefix("www.").lower()


def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "du-an"


def valid_site_url(site_url: str) -> bool:
    """Đúng cách Search Console ghi property: 'sc-domain:abc.com' hoặc 'https://abc.com/' (có / cuối)."""
    s = site_url.strip()
    return bool(re.fullmatch(r"sc-domain:[a-z0-9.-]+\.[a-z]{2,}", s)
                or re.fullmatch(r"https?://[^\s/]+\.[^\s/]+/(\S*/)?", s))


def _row(r: sqlite3.Row | tuple, cols: list[str]) -> dict:
    d = dict(zip(cols, r))
    d["settings"] = {**DEFAULTS, **json.loads(d["settings"] or "{}")}
    return d


def _select(con, where: str = "", args: tuple = ()) -> list[dict]:
    cur = con.execute(f"SELECT * FROM projects {where} ORDER BY id", args)
    cols = [c[0] for c in cur.description]
    return [_row(r, cols) for r in cur.fetchall()]


def list_projects(con: sqlite3.Connection, archived: bool = False) -> list[dict]:
    return _select(con, "" if archived else "WHERE archived_at IS NULL")


def get(con: sqlite3.Connection, slug: str | None) -> dict | None:
    """Dự án theo slug; slug không có / đã lưu trữ thì trả dự án đầu tiên đang hoạt động."""
    rows = list_projects(con)
    return next((p for p in rows if p["slug"] == slug), rows[0] if rows else None)


def db_path(base: Config, project: dict) -> Path:
    return base.db_path.parent / project["db_file"]


def config_for(base: Config, project: dict) -> Config:
    """Cấu hình của một dự án: chung phần tài khoản Google, DataForSEO, phân quyền; riêng website và dữ liệu."""
    s = project["settings"]
    return replace(
        base, site_url=project["site_url"], ga4_property=project["ga4_property"], db_path=db_path(base, project),
        logo=project.get("logo") or "",
        keywords=replace(base.keywords, brand_terms=tuple(s["brand_terms"])),
        rank=replace(base.rank, monthly_budget_usd=float(s["rank_budget_usd"]), location_code=int(s["location_code"]),
                     language_code=s["language_code"], device=s["device"],
                     se_domain=s.get("se_domain") or DEFAULTS["se_domain"], paused=bool(s.get("rank_paused"))),
        okr=replace(base.okr, sheet=s["okr_sheet"], okr_tab=s["okr_tab"], weekly_tab=s["weekly_tab"]))


def init_db(path: Path) -> None:
    """Tạo đủ các bảng cho file dữ liệu của dự án mới, để mọi màn mở được ngay cả khi chưa có số liệu."""
    from contextlib import closing

    from . import ai_gsc_import, db, indexing, keywords, kpi, okr, rank, volume
    from .ga4_query import CACHE_SCHEMA
    from .report import NOTES_SCHEMA
    with closing(db.connect(path)) as con:
        for ensure_fn in (indexing.ensure_tables, kpi.ensure_tables, okr.ensure_tables, rank.ensure_tables,
                          volume.ensure_tables, keywords.ensure_tables, ai_gsc_import.init):
            ensure_fn(con)
        con.executescript(NOTES_SCHEMA + CACHE_SCHEMA)
        con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.commit()


def _clean(fields: dict) -> dict:
    """Kiểm tra và chuẩn hóa dữ liệu nhập ở màn Dự án. Sai thì báo lỗi bằng câu dễ hiểu."""
    out = {}
    name = (fields.get("name") or "").strip()
    if not name:
        raise ValueError("Chưa nhập tên dự án")
    out["name"] = name
    site = (fields.get("site_url") or "").strip()
    if site and not site.startswith("sc-domain:") and not site.endswith("/"):
        site += "/"
    if not valid_site_url(site):
        raise ValueError("Property Search Console chưa đúng. Dạng đúng: sc-domain:tenmien.com hoặc https://tenmien.com/")
    out["site_url"] = site
    out["ga4_property"] = _ga4_property(fields.get("ga4_property") or "")
    s = dict(DEFAULTS)
    terms = fields.get("brand_terms", [])
    if isinstance(terms, str):
        terms = [t.strip() for t in terms.split(",")]
    s["brand_terms"] = [t for t in terms if t]
    try:
        s["rank_budget_usd"] = float(fields.get("rank_budget_usd", DEFAULTS["rank_budget_usd"]))
    except (TypeError, ValueError):
        raise ValueError("Ngân sách check rank phải là số (USD/tháng)")
    if s["rank_budget_usd"] < 0:
        raise ValueError("Ngân sách check rank không được âm")
    s["rank_paused"] = bool(fields.get("rank_paused", False))
    for k in ("location_code", "language_code", "device", "se_domain", "okr_tab", "weekly_tab"):
        if fields.get(k) not in (None, ""):
            s[k] = int(fields[k]) if k == "location_code" else str(fields[k]).strip()
    s["okr_sheet"] = (fields.get("okr_sheet") or "").strip()
    out["settings"] = s
    return out


def create(con: sqlite3.Connection, base: Config, fields: dict, user: str) -> dict:
    """Thêm dự án mới và tạo file dữ liệu riêng cho nó. Một property GSC chỉ thuộc một dự án đang hoạt động."""
    f = _clean(fields)
    if any(p["site_url"] == f["site_url"] for p in list_projects(con)):
        raise ValueError(f"Property {f['site_url']} đã có dự án")
    old = next((p for p in list_projects(con, archived=True)
                if p["archived_at"] and domain(p["site_url"]) == domain(f["site_url"])), None)
    if old:  # tránh hai dự án cùng website (số liệu tách làm hai file)
        raise ValueError(f"Website này đã có dự án lưu trữ \"{old['name']}\": bấm Khôi phục ở mục Đã lưu trữ thay "
                         "vì tạo dự án mới")
    slug = base_slug = slugify(domain(f["site_url"]))
    n = 2
    while con.execute("SELECT 1 FROM projects WHERE slug = ?", (slug,)).fetchone():  # kể cả dự án đã lưu trữ
        slug, n = f"{base_slug}-{n}", n + 1
    db_file = f"projects/{slug}.db"
    init_db(base.db_path.parent / db_file)
    con.execute("INSERT INTO projects (slug, name, site_url, ga4_property, db_file, settings, created_at, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (slug, f["name"], f["site_url"], f["ga4_property"], db_file,
                 json.dumps(f["settings"], ensure_ascii=False), _now(), user))
    con.commit()
    return get(con, slug)


def update(con: sqlite3.Connection, slug: str, fields: dict, user: str) -> dict:
    """Sửa cấu hình. Đổi property GSC thì số liệu cũ (của property cũ) vẫn nằm trong file, không bị xóa."""
    f = _clean(fields)
    if any(p["site_url"] == f["site_url"] and p["slug"] != slug for p in list_projects(con)):
        raise ValueError(f"Property {f['site_url']} đã thuộc dự án khác")
    con.execute("UPDATE projects SET name = ?, site_url = ?, ga4_property = ?, settings = ?, updated_at = ?, "
                "updated_by = ? WHERE slug = ?",
                (f["name"], f["site_url"], f["ga4_property"], json.dumps(f["settings"], ensure_ascii=False), _now(),
                 user, slug))
    con.commit()
    return get(con, slug)


def archive(con: sqlite3.Connection, slug: str, user: str) -> None:
    """Lưu trữ (ẩn) dự án: không xóa file dữ liệu, job hằng ngày bỏ qua. Không lưu trữ được dự án cuối cùng."""
    if len(list_projects(con)) <= 1:
        raise ValueError("Phải còn ít nhất một dự án đang hoạt động")
    con.execute("UPDATE projects SET archived_at = ?, archived_by = ? WHERE slug = ? AND archived_at IS NULL",
                (_now(), user, slug))
    con.commit()


def is_root(base: Config, project: dict) -> bool:
    """Dự án gốc: dữ liệu nằm chung file với cấu hình của tool (không xóa vĩnh viễn được)."""
    return db_path(base, project).resolve() == base.db_path.resolve()


def delete(con: sqlite3.Connection, base: Config, slug: str, user: str) -> Path | None:
    """Xóa vĩnh viễn dự án: bỏ dòng dự án, mọi quyền gắn với dự án, và file dữ liệu riêng của nó (rank, từ khóa,
    backlink, báo cáo…). File dữ liệu được chuyển vào data/da-xoa/ (bản cuối, phòng xóa nhầm; tự xóa thư mục đó khi
    chắc chắn) rồi trả về đường dẫn. File trên Google Drive / sheet dự án không bị đụng tới.
    Không xóa được: dự án cuối cùng đang hoạt động, và dự án gốc (dữ liệu nằm chung file với cấu hình của tool)."""
    import shutil
    p = next((x for x in list_projects(con, archived=True) if x["slug"] == slug), None)
    if not p:
        raise ValueError("Không tìm thấy dự án")
    if not p["archived_at"] and len(list_projects(con)) <= 1:
        raise ValueError("Phải còn ít nhất một dự án đang hoạt động")
    path = db_path(base, p)
    if path.resolve() == base.db_path.resolve():
        raise ValueError("Đây là dự án gốc: dữ liệu nằm chung file với cấu hình của tool nên không xóa được. Lưu trữ "
                         "dự án nếu không dùng nữa.")
    moved = None
    if path.exists():
        trash = base.db_path.parent / "da-xoa"
        trash.mkdir(exist_ok=True)
        moved = trash / f"{slug}_{datetime.now():%Y%m%d-%H%M%S}.db"
        try:
            shutil.move(str(path), str(moved))
        except PermissionError as e:  # file đang mở (job đang chạy): không xóa dở dang
            raise ValueError("File dữ liệu của dự án đang được dùng (có thể đang check rank): thử lại sau ít phút") \
                from e
        for extra in ("-wal", "-shm", "-journal"):
            side = path.with_name(path.name + extra)
            if side.exists():
                side.unlink()
    with con:
        con.execute("DELETE FROM projects WHERE slug = ?", (slug,))
        if con.execute("SELECT 1 FROM sqlite_master WHERE name = 'project_members'").fetchone():
            con.execute("DELETE FROM project_members WHERE project = ?", (slug,))
        if con.execute("SELECT 1 FROM sqlite_master WHERE name = 'access_log'").fetchone():
            con.execute("INSERT INTO access_log (at, by, email, action, detail) VALUES (?, ?, '', ?, ?)",
                        (_now(), str(user), "Xóa vĩnh viễn dự án", f"{p['name']} ({p['site_url']})"))
    return moved


def restore(con: sqlite3.Connection, slug: str, user: str) -> None:
    con.execute("UPDATE projects SET archived_at = NULL, archived_by = NULL, updated_at = ?, updated_by = ? "
                "WHERE slug = ?", (_now(), user, slug))
    con.commit()


# ---- Logo của website (hiện ở menu, ô đổi dự án, màn Dự án) ----
# Lưu thẳng trong bảng dự án dạng data URI (ảnh nhỏ): không cần thư mục ảnh công khai, không lộ danh sách khách.
MAX_LOGO_BYTES = 300_000
LOGO_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
              "svg": "image/svg+xml", "ico": "image/x-icon"}


def icon_of(project: dict) -> str:
    """Ảnh vuông đại diện của dự án ('' nếu chưa có: giao diện hiện chữ cái đầu)."""
    return project.get("logo") or ""


def logo_bytes(uri: str) -> bytes | None:
    """Ảnh PNG / JPEG trong data URI (để chèn vào Excel / slide); None nếu không có hoặc là SVG / ICO."""
    import base64
    if not uri or not uri.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")):
        return None
    try:
        return base64.b64decode(uri.split(",", 1)[1])
    except ValueError:
        return None


def data_uri(content: bytes, mime: str, size: int = 192) -> str:
    """Ảnh → data URI. Ảnh bitmap được thu về tối đa 192×192 PNG (đủ nét cho bìa slide, trang vẫn nhẹ); SVG giữ
    nguyên."""
    import base64
    import io
    if not content or len(content) > MAX_LOGO_BYTES:
        raise ValueError(f"Ảnh logo phải nhỏ hơn {MAX_LOGO_BYTES // 1000} KB")
    if not mime.startswith("image/"):
        raise ValueError("File logo phải là ảnh (PNG, JPG, SVG, WEBP, ICO)")
    if mime == "image/svg+xml":  # SVG giữ nguyên nhưng phải đúng là SVG (không lưu file bất kỳ dưới tên ảnh)
        head = content[:4096].lower()
        if b"<svg" not in head:
            raise ValueError("File SVG không hợp lệ")
    else:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(content))
            if getattr(img, "n_frames", 1) > 1 and mime == "image/x-icon":  # .ico nhiều cỡ: lấy cỡ lớn nhất
                img.size = max(img.ico.sizes())
            img = img.convert("RGBA")
            img.thumbnail((size, size))
            out = io.BytesIO()
            img.save(out, "PNG", optimize=True)
            content, mime = out.getvalue(), "image/png"
        except Exception as e:  # noqa: BLE001  (không đọc được như ảnh: từ chối, không lưu byte gốc)
            raise ValueError("Không đọc được file ảnh logo") from e
    return f"data:{mime};base64,{base64.b64encode(content).decode()}"


def fetch_logo(site_url: str, timeout: int = 10) -> str | None:
    """Lấy biểu tượng của website: apple-touch-icon (thường 180px, nét) → icon lớn nhất khai trong trang → /favicon.ico.
    Trả data URI, hoặc None khi không lấy được."""
    import urllib.request
    from html import unescape
    from urllib.parse import urljoin, urlsplit

    home = f"https://{domain(site_url)}/"
    headers = {"User-Agent": "Mozilla/5.0 (SEO Report logo fetch)"}
    # Chỉ HTTP(S): trang chủ của website (do khách kiểm soát) không được khiến tool đọc file trên máy (file:) hay FTP
    opener = urllib.request.OpenerDirector()
    for h in (urllib.request.HTTPHandler, urllib.request.HTTPSHandler, urllib.request.HTTPRedirectHandler,
              urllib.request.HTTPDefaultErrorHandler, urllib.request.HTTPErrorProcessor):
        opener.add_handler(h())

    def get(url: str) -> tuple[bytes, str]:
        if urlsplit(url).scheme not in ("http", "https"):
            raise ValueError("chỉ tải logo qua http(s)")
        with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return r.read(MAX_LOGO_BYTES + 1), r.headers.get("Content-Type", "").split(";")[0].strip().lower()

    candidates = []
    try:
        html, _ = get(home)
        page = html.decode("utf-8", "ignore")
        for tag in re.findall(r"<link\b[^>]*>", page, re.I):
            rel = (re.search(r'rel\s*=\s*["\']([^"\']+)', tag, re.I) or [None, ""])[1].lower()
            href = re.search(r'href\s*=\s*["\']([^"\']+)', tag, re.I)
            if not href or "icon" not in rel or "mask-icon" in rel:
                continue
            sizes = re.search(r'sizes\s*=\s*["\'](\d+)', tag, re.I)
            score = (2 if "apple-touch-icon" in rel else 1, int(sizes.group(1)) if sizes else 0)
            candidates.append((score, urljoin(home, unescape(href.group(1)))))
    except Exception:  # noqa: BLE001  (trang chủ không mở được: thử /favicon.ico)
        pass
    urls = [u for _, u in sorted(candidates, reverse=True)] + [urljoin(home, "/favicon.ico")]
    for url in urls:
        try:
            content, mime = get(url)
        except Exception:  # noqa: BLE001
            continue
        if not mime.startswith("image/"):
            ext = urlsplit(url).path.rsplit(".", 1)[-1].lower()  # theo đường dẫn, bỏ ?query và #fragment
            mime = LOGO_TYPES.get(ext, "")
        if mime.startswith("image/") and 0 < len(content) <= MAX_LOGO_BYTES:
            try:
                return data_uri(content, mime)
            except ValueError:  # không phải ảnh thật: thử ứng viên tiếp theo
                continue
    return None


def set_paused(con: sqlite3.Connection, slug: str, paused: bool, user: str) -> None:
    """Tạm ngưng / chạy lại check rank (và mọi chi phí DataForSEO) của một dự án."""
    p = get(con, slug)
    if not p or p["slug"] != slug:
        raise ValueError("Không có dự án này")
    s = {**p["settings"], "rank_paused": bool(paused)}
    con.execute("UPDATE projects SET settings = ?, updated_at = ?, updated_by = ? WHERE slug = ?",
                (json.dumps(s, ensure_ascii=False), _now(), user, slug))
    con.commit()


def set_budget(con: sqlite3.Connection, slug: str, usd: float, user: str) -> None:
    """Đổi ngân sách check rank (USD/tháng) của một dự án (màn Ngân sách check rank)."""
    if usd is None or usd < 0:
        raise ValueError("Ngân sách phải là số không âm (USD/tháng)")
    p = get(con, slug)
    if not p or p["slug"] != slug:
        raise ValueError("Không có dự án này")
    s = {**p["settings"], "rank_budget_usd": float(usd)}
    con.execute("UPDATE projects SET settings = ?, updated_at = ?, updated_by = ? WHERE slug = ?",
                (json.dumps(s, ensure_ascii=False), _now(), user, slug))
    con.commit()


def set_rank_target(con: sqlite3.Connection, slug: str, fields: dict, user: str) -> dict:
    """Đổi nơi check rank của dự án: vùng Google, thiết bị, vị trí tìm kiếm, ngôn ngữ (màn Từ khóa & rank)."""
    from . import rank as R
    p = get(con, slug)
    if not p or p["slug"] != slug:
        raise ValueError("Không có dự án này")
    new = {"se_domain": fields.get("se_domain"), "device": fields.get("device"),
           "location_code": int(fields.get("location_code") or 0), "language_code": fields.get("language_code")}
    if new["se_domain"] not in R.SE_DOMAINS or new["device"] not in R.DEVICES or             new["language_code"] not in R.LANGUAGES or new["location_code"] not in R.locations():
        raise ValueError("Cài đặt check rank không hợp lệ")
    s = {**p["settings"], **new}
    con.execute("UPDATE projects SET settings = ?, updated_at = ?, updated_by = ? WHERE slug = ?",
                (json.dumps(s, ensure_ascii=False), _now(), user, slug))
    con.commit()
    return s


# ---- Cài đặt chung của tool (file dữ liệu chính) ----

def setting(con: sqlite3.Connection, key: str, value: str | None = None) -> str:
    con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if value is not None:
        con.execute("INSERT OR REPLACE INTO app_settings VALUES (?, ?)", (key, value))
        con.commit()
        return value
    row = con.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else ""


def master_sheet(con: sqlite3.Connection) -> str:
    """ID Google Sheet mẫu gốc (OKRs, Weekly Task Tracker, Chi phí, Content…): tool copy thành sheet của dự án mới."""
    return setting(con, "master_sheet")


def set_master_sheet(con: sqlite3.Connection, link_or_id: str) -> str:
    from .okr import sheet_id
    sid = sheet_id((link_or_id or "").strip())
    if sid and not re.fullmatch(r"[A-Za-z0-9_-]{20,}", sid):
        raise ValueError("Không nhận ra link Google Sheet")
    return setting(con, "master_sheet", sid or "")


def set_sheet_link(con: sqlite3.Connection, slug: str, sheet: str, user: str) -> None:
    """Gắn sheet dự án (OKRs + Weekly Task + KPI) cho một dự án: màn OKR đọc từ đây."""
    p = get(con, slug)
    if not p or p["slug"] != slug:
        raise ValueError("Không có dự án này")
    s = {**p["settings"], "okr_sheet": sheet}
    con.execute("UPDATE projects SET settings = ?, updated_at = ?, updated_by = ? WHERE slug = ?",
                (json.dumps(s, ensure_ascii=False), _now(), user, slug))
    con.commit()


def set_logo(con: sqlite3.Connection, slug: str, logo: str, user: str) -> None:
    con.execute("UPDATE projects SET logo = ?, updated_at = ?, updated_by = ? WHERE slug = ?", (logo, _now(), user, slug))
    con.commit()


def setup_steps(base: Config, project: dict, st: dict, people: int) -> list[tuple[str, bool]]:
    """Các bước cài đặt một dự án (để nhắc việc còn thiếu ở màn Dự án): (tên bước, đã xong)."""
    from contextlib import closing

    from . import db
    from . import kpi as KP
    kpi_sheet = False
    path = db_path(base, project)
    if path.exists():
        with closing(db.connect(path)) as con:
            kpi_sheet = bool(KP.sheet_id(con))
    s = project["settings"]
    return [("Dữ liệu Search Console", bool(st["days"])), ("Gắn GA4", bool(project["ga4_property"])),
            ("Ngân sách check rank", bool(s.get("rank_budget_usd")) or bool(s.get("rank_paused"))),
            ("Sheet dự án (KPI cam kết)", kpi_sheet), ("Cấp tài khoản khách / team", people > 0)]


def status(base: Config, project: dict) -> dict:
    """Tình trạng dữ liệu để hiện ở màn Dự án: ngày GSC mới nhất, số ngày đã lấy."""
    from contextlib import closing

    from . import db
    path = db_path(base, project)
    if not path.exists():
        return {"days": 0, "last": None}
    with closing(db.connect(path)) as con:
        days, last = con.execute("SELECT COUNT(*), MAX(date) FROM gsc_fetch_log WHERE site = ?",
                                 (project["site_url"],)).fetchone()
    return {"days": days, "last": last}
