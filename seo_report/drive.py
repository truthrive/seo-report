"""Lưu báo cáo lên Google Drive: Google Sheets (từ file Excel), Google Slides (từ file .pptx) và PDF (xuất từ chính bộ
Slides nên nội dung giống hệt).

Quyền chỉ là drive.file: tool chỉ thấy và sửa file/folder do chính nó tạo. Tool tạo một folder gốc
"SEO Report – <site>" và các folder con; người dùng chọn folder con để lưu, tự chia sẻ hoặc di chuyển folder đó.
Chuyển đổi định dạng do Google Drive làm (upload kèm mimeType đích), không cần bật Sheets/Slides API.
"""
import io
import sqlite3

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

FOLDER = "application/vnd.google-apps.folder"
SHEET = "application/vnd.google-apps.spreadsheet"
SLIDES = "application/vnd.google-apps.presentation"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PDF = "application/pdf"


def _setting(con: sqlite3.Connection, key: str, value: str | None = None) -> str | None:
    con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if value is not None:
        with con:
            con.execute("INSERT OR REPLACE INTO app_settings VALUES (?, ?)", (key, value))
        return value
    row = con.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def build_service(cfg):
    from googleapiclient.discovery import build

    from . import auth
    return build("drive", "v3", credentials=auth.get_credentials(cfg, need=(auth.DRIVE_SCOPE,)), cache_discovery=False)


def explain(e: Exception) -> str:
    """Lỗi thường gặp → hướng dẫn ngắn bằng tiếng Việt."""
    text = str(e)
    if isinstance(e, SystemExit) or "quyền" in text:
        return ("Tool chưa có quyền Google Drive. Chạy lại đăng nhập: python -m seo_report login "
                "(tích ô cho phép Google Drive).")
    if isinstance(e, HttpError) and ("accessNotConfigured" in text or "has not been used" in text or
                                     "SERVICE_DISABLED" in text):
        return "Google Drive API chưa bật trong Google Cloud project của tool (xem README mục Google Drive)."
    return text[:300]


def _exists(svc, file_id: str) -> bool:
    try:
        f = svc.files().get(fileId=file_id, fields="id, trashed").execute()
        return not f.get("trashed")
    except HttpError:
        return False


def root_folder(con, svc, site: str) -> str:
    """Folder gốc của tool trên Drive (tạo nếu chưa có hoặc đã bị xóa)."""
    fid = _setting(con, "drive_root")
    if fid and _exists(svc, fid):
        return fid
    name = f"SEO Report – {site.split('//')[-1].strip('/')}"
    fid = svc.files().create(body={"name": name, "mimeType": FOLDER}, fields="id").execute()["id"]
    return _setting(con, "drive_root", fid)


def list_folders(svc, root: str) -> list[dict]:
    q = f"'{root}' in parents and mimeType = '{FOLDER}' and trashed = false"
    resp = svc.files().list(q=q, fields="files(id, name)", orderBy="name", pageSize=200).execute()
    return resp.get("files", [])


def create_folder(svc, name: str, parent: str) -> str:
    return svc.files().create(body={"name": name.strip(), "mimeType": FOLDER, "parents": [parent]},
                              fields="id").execute()["id"]


def target_folder(con, svc, site: str) -> tuple[str, str]:
    """(id, tên) folder đang chọn để lưu; mặc định là folder gốc."""
    root = root_folder(con, svc, site)
    fid = _setting(con, "drive_folder")
    if fid and fid != root and _exists(svc, fid):
        return fid, svc.files().get(fileId=fid, fields="name").execute()["name"]
    return root, svc.files().get(fileId=root, fields="name").execute()["name"]


def set_target_folder(con, folder_id: str) -> None:
    _setting(con, "drive_folder", folder_id)


def upload(svc, data: bytes, name: str, src_mime: str, folder: str, convert_to: str | None = None) -> dict:
    """Tải file lên folder; convert_to = mimeType Google (Sheets/Slides) thì Drive tự chuyển đổi."""
    body = {"name": name, "parents": [folder]}
    if convert_to:
        body["mimeType"] = convert_to
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=src_mime, resumable=False)
    return svc.files().create(body=body, media_body=media, fields="id, name, webViewLink").execute()


def export_pdf(svc, file_id: str) -> bytes:
    return svc.files().export(fileId=file_id, mimeType=PDF).execute()
