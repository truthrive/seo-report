"""Ai đang chạy một việc tốn tiền (DataForSEO): người bấm hoặc lịch tự động. Trang gọi việc tốn tiền bọc phần chạy trong
`with runner(email):` (cùng luồng với phần ghi chi phí); không bọc = lịch tự động. Nhật ký chi tiền đọc lại tên này."""
import sqlite3
import threading
from contextlib import contextmanager

SCHEDULE = "lịch"  # giá trị lưu cho việc chạy theo lịch
_LOCAL = threading.local()


@contextmanager
def runner(name: str):
    prev = getattr(_LOCAL, "name", None)
    _LOCAL.name = str(name or "")
    try:
        yield
    finally:
        _LOCAL.name = prev


def current() -> str:
    name = getattr(_LOCAL, "name", None)
    return SCHEDULE if name is None else name


def add_column(con: sqlite3.Connection, table: str, column: str) -> None:
    if column not in {c[1] for c in con.execute(f"PRAGMA table_info({table})")}:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")


def add_by_column(con: sqlite3.Connection, table: str) -> None:
    """Bảng ghi chi phí cũ chưa có cột by_user: thêm (dòng cũ để NULL = không rõ ai chạy)."""
    if "by_user" not in {c[1] for c in con.execute(f"PRAGMA table_info({table})")}:
        con.execute(f"ALTER TABLE {table} ADD COLUMN by_user TEXT")
