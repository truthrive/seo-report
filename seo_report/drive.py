"""Lưu báo cáo lên Google Drive: Google Sheets (từ file Excel), Google Slides (từ file .pptx) và PDF (xuất từ chính bộ
Slides nên nội dung giống hệt).

Tool tạo một folder gốc "SEO Report – <site>" cho mỗi dự án (trong folder của người dùng nếu config.toml có
[drive] parent_folder) và các folder con; người dùng chọn folder con để lưu, tự chia sẻ. Với quyền drive.file tool chỉ
thấy file/folder do chính nó tạo; ghi vào folder của người dùng cần quyền Drive đầy đủ (đăng nhập lại một lần).
Chuyển đổi định dạng do Google Drive làm (upload kèm mimeType đích), không cần bật Sheets/Slides API.
"""
import io
import sqlite3

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from .projects import domain

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


def root_folder(con, svc, site: str, parent: str = "") -> str:
    """Folder gốc của dự án trên Drive (tạo nếu chưa có hoặc đã bị xóa). `parent` = folder của người dùng
    ([drive] parent_folder): folder dự án được tạo trong đó; folder đã có ở chỗ khác thì chuyển vào (khi tool có
    quyền Drive đầy đủ; thiếu quyền thì giữ nguyên chỗ cũ)."""
    fid = _setting(con, "drive_root")
    if fid and _exists(svc, fid):
        if parent:
            _ensure_parent(svc, fid, parent)
        return fid
    body = {"name": f"SEO Report – {domain(site)}", "mimeType": FOLDER}
    if parent:
        body["parents"] = [parent]
    try:
        fid = svc.files().create(body=body, fields="id").execute()["id"]
    except HttpError as e:
        if parent and e.resp.status in (403, 404):
            raise SystemExit("Tool chưa vào được folder Drive đã cài ở config.toml ([drive] parent_folder). Kiểm tra "
                             "link folder và chạy lại: python -m seo_report login (cấp quyền Google Drive đầy "
                             "đủ)") from e
        raise
    return _setting(con, "drive_root", fid)


def _ensure_parent(svc, fid: str, parent: str) -> bool:
    """Chuyển folder/file vào `parent` nếu đang nằm chỗ khác. Không có quyền thì bỏ qua (trả False)."""
    try:
        cur = svc.files().get(fileId=fid, fields="parents").execute().get("parents", [])
        if parent in cur:
            return True
        svc.files().update(fileId=fid, addParents=parent, removeParents=",".join(cur), fields="id").execute()
        return True
    except HttpError:
        return False


def list_folders(svc, root: str) -> list[dict]:
    q = f"'{root}' in parents and mimeType = '{FOLDER}' and trashed = false"
    resp = svc.files().list(q=q, fields="files(id, name)", orderBy="name", pageSize=200).execute()
    return resp.get("files", [])


def create_folder(svc, name: str, parent: str) -> str:
    return svc.files().create(body={"name": name.strip(), "mimeType": FOLDER, "parents": [parent]},
                              fields="id").execute()["id"]


def target_folder(con, svc, site: str, parent: str = "") -> tuple[str, str]:
    """(id, tên) folder đang chọn để lưu; mặc định là folder gốc."""
    root = root_folder(con, svc, site, parent)
    fid = _setting(con, "drive_folder")
    if fid and fid != root and _exists(svc, fid):
        return fid, svc.files().get(fileId=fid, fields="name").execute()["name"]
    return root, svc.files().get(fileId=root, fields="name").execute()["name"]


def set_target_folder(con, folder_id: str) -> None:
    _setting(con, "drive_folder", folder_id)


# Thư mục theo hạng mục (trong folder dự án): file xuất của mỗi màn tự vào đúng thư mục, tạo ở lần lưu đầu tiên.
# Số thứ tự để Drive xếp đúng thứ tự; đổi tên / di chuyển thư mục trên Drive vẫn được (tool nhớ theo id).
CATEGORIES = {"report": "01. Báo cáo định kỳ", "rank": "02. Từ khóa & Thứ hạng", "rivals": "03. Đối thủ",
              "backlink": "04. Backlink", "aio": "05. AI Overview", "ai": "06. AI Search & GEO",
              "url": "07. Hiệu suất URL", "budget": "08. Ngân sách DataForSEO"}


def category_folder(con, svc, site: str, parent: str, category: str) -> tuple[str, str]:
    """(id, đường dẫn hiển thị) thư mục của hạng mục, nằm trong folder đang chọn để lưu (mặc định folder dự án).
    Đã có (tool nhớ id) thì dùng lại; chưa có thì tìm theo tên rồi mới tạo, để không sinh thư mục trùng."""
    base, base_name = target_folder(con, svc, site, parent)
    name = CATEGORIES[category]
    key = f"drive_cat_{category}_{base}"
    fid = _setting(con, key)
    if not (fid and _exists(svc, fid)):
        fid = next((f["id"] for f in list_folders(svc, base) if f["name"] == name), None) or create_folder(svc, name,
                                                                                                          base)
        _setting(con, key, fid)
    shown = svc.files().get(fileId=fid, fields="name").execute()["name"]
    return fid, f"{base_name} / {shown}"


def upload(svc, data: bytes, name: str, src_mime: str, folder: str, convert_to: str | None = None) -> dict:
    """Tải file lên folder; convert_to = mimeType Google (Sheets/Slides) thì Drive tự chuyển đổi."""
    body = {"name": name, "parents": [folder]}
    if convert_to:
        body["mimeType"] = convert_to
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=src_mime, resumable=False)
    return svc.files().create(body=body, media_body=media, fields="id, name, webViewLink").execute()


def export_pdf(svc, file_id: str) -> bytes:
    return svc.files().export(fileId=file_id, mimeType=PDF).execute()
