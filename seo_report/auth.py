"""Đăng nhập Google bằng OAuth và lưu token để các lần chạy sau không phải đăng nhập lại.

Một token dùng chung cho GSC và GA4. Mỗi chức năng chỉ đòi đúng quyền nó cần (`need`): token cũ chỉ có quyền GSC vẫn
chạy được lịch lấy dữ liệu GSC, chỉ chức năng GA4 mới yêu cầu đăng nhập lại để cấp thêm quyền.
"""
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import Config

GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"  # chỉ file/folder do tool tạo
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"  # đọc sheet OKR / task (chỉ đọc)
ALL_SCOPES = [GSC_SCOPE, GA4_SCOPE]  # quyền cho các chức năng đọc số liệu
SCOPES = ALL_SCOPES + [DRIVE_SCOPE, SHEETS_SCOPE]  # quyền xin khi đăng nhập


def _save(creds: Credentials, cfg: Config) -> None:
    cfg.token_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.token_path.write_text(creds.to_json(), encoding="utf-8")


def _missing(creds: Credentials, need) -> list[str]:
    granted = set(creds.scopes or [])
    return [s for s in need if s not in granted]


def get_credentials(cfg: Config, interactive: bool = False, need=(GSC_SCOPE,)) -> Credentials:
    creds = None
    if cfg.token_path.exists():
        # Không ép scope khi đọc: token giữ đúng quyền đã được cấp, tránh lỗi invalid_scope khi làm mới.
        creds = Credentials.from_authorized_user_file(str(cfg.token_path))
    if creds and _missing(creds, need):
        if not interactive:
            miss = _missing(creds, need)
            what = ("Google Drive" if DRIVE_SCOPE in miss else "đọc Google Sheets" if SHEETS_SCOPE in miss
                    else "đọc Google Analytics")
            raise SystemExit(f"Tài khoản chưa cấp quyền {what} cho tool. Chạy lại: python -m seo_report login")
        creds = None  # đăng nhập lại để cấp thêm quyền
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds, cfg)
            return creds
        except RefreshError:
            # Token bị thu hồi hoặc app OAuth đang ở chế độ Testing (hết hạn sau 7 ngày).
            if not interactive:
                raise SystemExit(
                    "Token Google hết hạn hoặc bị thu hồi. Chạy lại: python -m seo_report login"
                )
    if not interactive:
        raise SystemExit("Chưa đăng nhập Google. Chạy: python -m seo_report login")
    if not cfg.client_secret.exists():
        raise SystemExit(
            f"Không tìm thấy {cfg.client_secret}. Xem README, mục 'Tạo OAuth client'."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(cfg.client_secret), SCOPES)
    # Người dùng có thể bỏ tích từng quyền trên màn hình đồng ý; oauthlib mặc định coi đó là lỗi, ở đây cho qua
    # rồi báo rõ ở lệnh login.
    import os
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    _save(creds, cfg)
    return creds


def build_service(creds: Credentials):
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def build_ga4_data(creds: Credentials):
    """GA4 Data API (runReport, getMetadata, checkCompatibility)."""
    return build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)


def build_ga4_admin(creds: Credentials):
    """GA4 Admin API (liệt kê property, đọc múi giờ của property)."""
    return build("analyticsadmin", "v1beta", credentials=creds, cache_discovery=False)
