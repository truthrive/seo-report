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
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"  # file/folder do tool tạo (xuất báo cáo, sheet mẫu)
DRIVE_FULL_SCOPE = "https://www.googleapis.com/auth/drive"  # copy sheet mẫu gốc của người dùng thành sheet dự án
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"  # đọc sheet OKR / KPI
SHEETS_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"  # ghi tab KPI cam kết vào sheet dự án
ADS_SCOPE = "https://www.googleapis.com/auth/adwords"  # Google Ads API: chỉ đọc Keyword Planner (volume từ khóa)
# Google Business Profile (hồ sơ GMB): Google chỉ có một quyền chung (đọc + sửa); tool chỉ đọc
BUSINESS_SCOPE = "https://www.googleapis.com/auth/business.manage"
CONTENT_SCOPE = "https://www.googleapis.com/auth/content"  # Merchant API (sản phẩm Merchant Center)
ALL_SCOPES = [GSC_SCOPE, GA4_SCOPE]  # quyền cho các chức năng đọc số liệu
SCOPES = ALL_SCOPES + [DRIVE_FULL_SCOPE, SHEETS_WRITE_SCOPE, ADS_SCOPE, BUSINESS_SCOPE, CONTENT_SCOPE]  # quyền xin khi đăng nhập
# Quyền rộng hơn bao luôn quyền hẹp: token đã cấp drive (đầy đủ) thì không cần drive.file, spreadsheets thì đọc được.
COVERS = {DRIVE_SCOPE: {DRIVE_FULL_SCOPE}, SHEETS_SCOPE: {SHEETS_WRITE_SCOPE, DRIVE_FULL_SCOPE},
          SHEETS_WRITE_SCOPE: {DRIVE_FULL_SCOPE}}


def _save(creds: Credentials, cfg: Config) -> None:
    cfg.token_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.token_path.write_text(creds.to_json(), encoding="utf-8")


def _missing(creds: Credentials, need) -> list[str]:
    return missing_scopes(creds.scopes or [], need)


def missing_scopes(granted, need) -> list[str]:
    """Quyền trong `need` mà token chưa có (quyền rộng hơn tính là đã có)."""
    granted = set(granted)
    return [s for s in need if s not in granted and not (COVERS.get(s, set()) & granted)]


def account_email(cfg: Config) -> str:
    """Email tài khoản Google tool đang dùng (để khách thêm vào GSC / GA4). Đọc qua Google Drive với quyền
    drive.file đã cấp sẵn (không cần thêm quyền); không đọc được thì trả chuỗi rỗng."""
    from googleapiclient.discovery import build
    try:
        creds = get_credentials(cfg, need=())
        about = build("drive", "v3", credentials=creds, cache_discovery=False).about()
        return about.get(fields="user(emailAddress)").execute()["user"]["emailAddress"]
    except (Exception, SystemExit):  # noqa: BLE001
        return ""


def get_credentials(cfg: Config, interactive: bool = False, need=(GSC_SCOPE,)) -> Credentials:
    creds = None
    if cfg.token_path.exists():
        # Không ép scope khi đọc: token giữ đúng quyền đã được cấp, tránh lỗi invalid_scope khi làm mới.
        creds = Credentials.from_authorized_user_file(str(cfg.token_path))
    if creds and _missing(creds, need):
        if not interactive:
            miss = _missing(creds, need)
            what = ("Google Business Profile (trang Local SEO)" if BUSINESS_SCOPE in miss
                    else "Google Merchant Center (trang Merchant Center)" if CONTENT_SCOPE in miss
                    else "Google Ads (lấy volume từ khóa)" if ADS_SCOPE in miss
                    else "Google Drive đầy đủ (copy sheet mẫu gốc)" if DRIVE_FULL_SCOPE in miss
                    else "ghi Google Sheets" if SHEETS_WRITE_SCOPE in miss
                    else "Google Drive" if DRIVE_SCOPE in miss else "đọc Google Sheets" if SHEETS_SCOPE in miss
                    else "đọc Google Analytics")
            raise SystemExit(f"Tài khoản chưa cấp quyền {what} cho tool. Chạy lại: python -m seo_report login "
                             "(đăng nhập Google lại một lần, tích đủ các ô quyền)")
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


def build_gbp(creds: Credentials, api: str, version: str = "v1"):
    """Google Business Profile: mybusinessaccountmanagement (tài khoản), mybusinessbusinessinformation (hồ sơ),
    businessprofileperformance (lượt xem, hành động, từ khóa)."""
    return build(api, version, credentials=creds, cache_discovery=False)


def build_ga4_admin(creds: Credentials):
    """GA4 Admin API (liệt kê property, đọc múi giờ của property)."""
    return build("analyticsadmin", "v1beta", credentials=creds, cache_discovery=False)


# ---- Đăng nhập Google ngay trong tool (nút Kết nối Google ở màn Dự án) ----
# OAuth client hiện có là loại "ứng dụng máy tính": Google chỉ cho quay về địa chỉ localhost, nên chỉ chạy khi mở tool
# trên chính máy chạy tool (web.py kiểm tra). Mỗi lần bấm tạo một phiên chờ có mã state riêng, dùng một lần, hết hạn
# sau 10 phút; mã đổi token kèm PKCE.
_WEB_FLOWS: dict[str, tuple[object, float]] = {}
FLOW_TTL = 600


def web_login_url(cfg: Config, redirect_uri: str, switch_account: bool = False) -> str:
    """Link trang đăng nhập Google xin đủ quyền của tool. switch_account: cho chọn tài khoản Google khác."""
    import time

    from google_auth_oauthlib.flow import Flow
    if not cfg.client_secret.exists():
        raise ValueError(f"Không tìm thấy {cfg.client_secret}. Xem README, mục 'Tạo OAuth client'.")
    flow = Flow.from_client_secrets_file(str(cfg.client_secret), scopes=SCOPES, redirect_uri=redirect_uri,
                                         autogenerate_code_verifier=True)
    url, state = flow.authorization_url(access_type="offline",
                                        prompt="select_account consent" if switch_account else "consent")
    now = time.monotonic()
    for k, (_, t) in list(_WEB_FLOWS.items()):  # dọn phiên cũ
        if now - t > FLOW_TTL:
            _WEB_FLOWS.pop(k, None)
    _WEB_FLOWS[state] = (flow, now)
    return url


def web_login_finish(cfg: Config, state: str, callback_url: str) -> Credentials:
    """Google gọi lại sau khi người dùng đồng ý: đổi mã lấy token và lưu (thay token cũ, kể cả khi đổi tài khoản)."""
    import os
    import time
    item = _WEB_FLOWS.pop(state or "", None)
    if not item or time.monotonic() - item[1] > FLOW_TTL:
        raise ValueError("Phiên đăng nhập Google đã hết hạn hoặc không hợp lệ. Bấm Kết nối Google lại.")
    flow = item[0]
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")  # người dùng có thể bỏ tích vài quyền: báo sau
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # quay về http://localhost (chỉ trên máy chạy tool)
    flow.fetch_token(authorization_response=callback_url)
    creds = flow.credentials
    if not creds.refresh_token:
        raise ValueError("Google không trả mã làm mới token. Bấm Kết nối Google lại.")
    _save(creds, cfg)
    return creds


SCOPE_NAMES = {GSC_SCOPE: "Search Console", GA4_SCOPE: "Google Analytics", DRIVE_FULL_SCOPE: "Google Drive",
               SHEETS_WRITE_SCOPE: "Google Sheets", ADS_SCOPE: "Google Ads",
               BUSINESS_SCOPE: "Google Business Profile", CONTENT_SCOPE: "Google Merchant Center"}


def granted_status(cfg: Config) -> dict:
    """Token hiện tại có quyền nào: {"connected", "missing": [tên quyền chưa cấp]}."""
    if not cfg.token_path.exists():
        return {"connected": False, "missing": list(SCOPE_NAMES.values())}
    try:
        creds = Credentials.from_authorized_user_file(str(cfg.token_path))
    except (ValueError, OSError):
        return {"connected": False, "missing": list(SCOPE_NAMES.values())}
    return {"connected": True, "missing": [SCOPE_NAMES[s] for s in missing_scopes(creds.scopes or [], SCOPES)]}
