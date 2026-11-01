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
            "device": "mobile", "okr_sheet": "", "okr_tab": "OKRs 3 tháng", "weekly_tab": "Weekly Task Tracker"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure(con: sqlite3.Connection, base: Config, user: str = "config.toml") -> None:
    """Tạo bảng dự án; lần đầu tạo dự án số 1 từ config.toml, dùng luôn file dữ liệu hiện có."""
    con.executescript(SCHEMA)
    if con.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
        return
    settings = {"brand_terms": list(base.keywords.brand_terms), "rank_budget_usd": base.rank.monthly_budget_usd,
                "location_code": base.rank.location_code, "language_code": base.rank.language_code,
                "device": base.rank.device, "okr_sheet": base.okr.sheet, "okr_tab": base.okr.okr_tab,
                "weekly_tab": base.okr.weekly_tab}
    logo = "/assets/logo.svg" if "matkinhtamduc" in base.site_url else ""
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
        keywords=replace(base.keywords, brand_terms=tuple(s["brand_terms"])),
        rank=replace(base.rank, monthly_budget_usd=float(s["rank_budget_usd"]), location_code=int(s["location_code"]),
                     language_code=s["language_code"], device=s["device"]),
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
    for k in ("location_code", "language_code", "device", "okr_tab", "weekly_tab"):
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


def restore(con: sqlite3.Connection, slug: str, user: str) -> None:
    con.execute("UPDATE projects SET archived_at = NULL, archived_by = NULL, updated_at = ?, updated_by = ? "
                "WHERE slug = ?", (_now(), user, slug))
    con.commit()


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
