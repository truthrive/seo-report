"""Sao lưu dữ liệu: mỗi lần chạy tạo một file zip gồm mọi file SQLite trong data/ (chép an toàn bằng backup API của
SQLite, kể cả khi tool đang chạy) và config.toml, giữ lại N bản gần nhất.

Không chép secrets/ (token Google, tài khoản DataForSEO) và các file khóa trong data/: giữ chúng riêng ở nơi an toàn.
"""
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

PREFIX = "seo-report_"


def run(root: Path, data_dir: Path, dest: Path, keep: int = 7, now: datetime | None = None) -> Path:
    """Tạo bản sao lưu trong `dest`, xóa bản cũ chỉ giữ `keep` bản. Trả về đường dẫn file zip."""
    now = now or datetime.now()
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{PREFIX}{now:%Y-%m-%d_%H%M}.zip"
    part = out.with_suffix(".part")  # ghi xong mới đổi tên: lỗi giữa chừng không để lại bản hỏng
    try:
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for i, src in enumerate(sorted(data_dir.rglob("*.db"))):
                if dest.resolve() in src.resolve().parents:
                    continue
                copy = Path(tmp) / f"{i}.db"
                with closing(sqlite3.connect(src.as_uri() + "?mode=ro", uri=True)) as a, \
                        closing(sqlite3.connect(copy)) as b:
                    a.backup(b)
                z.write(copy, src.relative_to(root).as_posix() if root in src.parents else src.name)
                copy.unlink()
            if (root / "config.toml").exists():
                z.write(root / "config.toml", "config.toml")
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)
    for old in sorted(dest.glob(f"{PREFIX}*.zip"))[:-keep]:
        old.unlink()
    return out


def latest(dest: Path) -> Path | None:
    files = sorted(dest.glob(f"{PREFIX}*.zip")) if dest.exists() else []
    return files[-1] if files else None
