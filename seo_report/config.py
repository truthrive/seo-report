"""Đọc cấu hình từ config.toml."""
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .access import AccessSettings
from .okr import OkrSettings


@dataclass
class KeywordSettings:
    """Ngưỡng chọn head KW và keyword phụ (spec, mục Logic keyword)."""
    window_days: int = 28
    min_impressions: int = 50
    max_position: float = 30.0
    max_secondary: int = 5
    brand_terms: tuple[str, ...] = ()


@dataclass
class RankSettings:
    """Check rank qua DataForSEO (spec, mục Check rank & ngân sách)."""
    monthly_budget_usd: float = 20.0
    price_per_page: float = 0.0006  # chế độ standard, mỗi trang 10 kết quả
    location_code: int = 2704  # Việt Nam
    language_code: str = "vi"
    device: str = "mobile"
    se_domain: str = "google.com.vn"  # tên miền Google dùng để tìm (vùng Google)
    paused: bool = False  # tạm ngưng: không gửi yêu cầu DataForSEO nào (check rank, volume) cho website này


@dataclass
class Config:
    site_url: str
    db_path: Path
    client_secret: Path
    token_path: Path
    backfill_months: int = 16
    refetch_days: int = 5
    keywords: KeywordSettings = field(default_factory=KeywordSettings)
    rank: RankSettings = field(default_factory=RankSettings)
    dataforseo_secret: Path = Path("secrets/dataforseo.toml")
    google_ads_secret: Path = Path("secrets/google_ads.toml")  # developer token + Customer ID: volume miễn phí
    ga4_property: str = ""  # dạng properties/123456789; để trống khi chưa kết nối GA4
    okr: OkrSettings = field(default_factory=OkrSettings)  # sheet OKR / Weekly Task Tracker (báo cáo công việc)
    access: AccessSettings = field(default_factory=AccessSettings)  # ai được vào / sửa khi mở qua Cloudflare
    logo: str = ""  # logo của website (data URI) cho báo cáo Excel / slide / bản tĩnh; đặt theo dự án
    backup_dir: Path = Path("backups")  # nơi lưu bản sao lưu hằng ngày ([backup] dir)
    drive_parent: str = ""  # ID folder Drive của bạn chứa mọi folder / file tool tạo ([drive] parent_folder); trống = My Drive
    backup_keep: int = 7  # số bản sao lưu giữ lại ([backup] keep)


def load_config(path: str | Path = "config.toml") -> Config:
    p = Path(path)
    if not p.exists():
        raise SystemExit(
            f"Không tìm thấy {p}. Sao chép config.example.toml thành config.toml rồi điền thông tin."
        )
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    base = p.resolve().parent
    return Config(
        site_url=raw["site_url"],
        db_path=base / raw.get("db_path", "data/seo.db"),
        client_secret=base / raw.get("client_secret", "secrets/client_secret.json"),
        token_path=base / raw.get("token_path", "secrets/token.json"),
        backfill_months=int(raw.get("backfill_months", 16)),
        refetch_days=int(raw.get("refetch_days", 5)),
        keywords=KeywordSettings(**{
            k: tuple(v) if k == "brand_terms" else v for k, v in raw.get("keywords", {}).items()
        }),
        rank=RankSettings(**raw.get("rank", {})),
        dataforseo_secret=base / raw.get("dataforseo_secret", "secrets/dataforseo.toml"),
        google_ads_secret=base / raw.get("google_ads_secret", "secrets/google_ads.toml"),
        ga4_property=_ga4_property(raw.get("ga4_property", "")),
        okr=OkrSettings(**raw.get("okr", {})),
        access=AccessSettings(**raw.get("access", {})),
        backup_dir=base / raw.get("backup", {}).get("dir", "backups"),
        backup_keep=max(1, int(raw.get("backup", {}).get("keep", 7))),
        drive_parent=_folder_id(raw.get("drive", {}).get("parent_folder", "")),
    )


def _ga4_property(value) -> str:
    """Chấp nhận '123456789' hoặc 'properties/123456789'."""
    value = str(value).strip()
    return value if not value or value.startswith("properties/") else f"properties/{value}"


def _folder_id(value) -> str:
    """Link folder Drive (https://drive.google.com/drive/folders/<id>) hoặc ID → ID; trống → ''."""
    v = str(value or "").strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", v)
    return m.group(1) if m else v.split("?")[0]
