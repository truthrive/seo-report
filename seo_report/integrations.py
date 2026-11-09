"""Cấu hình tích hợp (màn Cài đặt tích hợp, chỉ Chủ tool): DataForSEO, Google Ads, AI. Mỗi tích hợp khai báo các ô,
ô nào là mã bí mật, file lưu và cách kiểm tra; thêm tích hợp mới = thêm một mục trong INTEGRATIONS.

- Lưu vào các file trong secrets/ như trước (lịch chạy hằng ngày, lệnh terminal đọc thẳng), không vào git.
- Mã bí mật không bao giờ gửi lại trình duyệt: chỉ hiện dạng ••••a1b2; ô bỏ trống khi lưu = giữ mã cũ.
- Kiểm tra trước khi lưu: mã mới không chạy thì không thay mã cũ.
"""
import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Field:
    key: str
    label: str
    secret: bool = False
    placeholder: str = ""
    options: dict | None = None  # ô chọn
    hint: str = ""


@dataclass
class Integration:
    key: str
    name: str
    icon: str
    about: str
    fields: list[Field] = field(default_factory=list)
    path_attr: str = ""  # thuộc tính Config chứa đường dẫn file; trống thì dùng default_path
    default_path: str = ""
    required: tuple = ()


AI_MODELS = {"claude-opus-5-5": "Claude Opus 5.5 (mặc định, mạnh nhất)",
             "claude-sonnet-5-5": "Claude Sonnet 5.5 (nhanh, rẻ hơn)",
             "claude-haiku-5-5": "Claude Haiku 5.5 (rẻ nhất, việc đơn giản)",
             "claude-fable-5-1": "Claude Fable 5.1 (cao cấp nhất, đắt nhất)"}

INTEGRATIONS = [
    Integration("dataforseo", "DataForSEO", "leaderboard",
                "Check rank thật trên Google và volume từ khóa (khi chưa dùng Google Ads). Lấy ở app.dataforseo.com > "
                "API Access.",
                [Field("login", "API login", placeholder="email đăng ký DataForSEO"),
                 Field("password", "API password", secret=True, hint="Không phải mật khẩu đăng nhập web")],
                path_attr="dataforseo_secret", required=("login", "password")),
    Integration("google_ads", "Google Ads API", "ads_click",
                "Volume từ khóa miễn phí từ Keyword Planner (thay DataForSEO). Developer token cần mức Basic trở lên.",
                [Field("developer_token", "Developer token", secret=True,
                       hint="Tài khoản người quản lý > Quản trị > Trung tâm API"),
                 Field("login_customer_id", "Mã tài khoản người quản lý (MCC)", placeholder="123-456-7890"),
                 Field("customer_id", "Customer ID", placeholder="111-222-3333",
                       hint="Tài khoản Google Ads nằm dưới MCC, không cần chạy quảng cáo"),
                 Field("api_version", "Phiên bản API", placeholder="v26",
                       hint="Chỉ đổi khi tool báo phiên bản API không còn")],
                path_attr="google_ads_secret", required=("developer_token", "customer_id")),
    Integration("google_api", "Google API key (Core Web Vitals)", "speed",
                "Tốc độ trang và Core Web Vitals (miễn phí): PageSpeed Insights và Chrome UX Report. Tạo ở Google Cloud "
                "Console > APIs & Services > Credentials > Create credentials > API key, rồi bật 2 API “PageSpeed "
                "Insights API” và “Chrome UX Report API” trong Library. Nên giới hạn key chỉ dùng cho 2 API này.",
                [Field("api_key", "API key", secret=True, placeholder="AIza…")],
                default_path="secrets/google_api.toml", required=("api_key",)),
    Integration("ai", "AI (Claude)", "auto_awesome",
                "Chuẩn bị cho các tính năng AI sau này (viết nhận xét báo cáo, gợi ý nội dung…). Lấy khóa ở "
                "platform.claude.com > API keys.",
                [Field("api_key", "Khóa API", secret=True, placeholder="sk-ant-…"),
                 Field("model", "Model", options=AI_MODELS)],
                default_path="secrets/ai.toml", required=("api_key",)),
]
BY_KEY = {x.key: x for x in INTEGRATIONS}


def path_of(cfg, it: Integration) -> Path:
    if it.path_attr:
        return Path(getattr(cfg, it.path_attr))
    return Path(cfg.client_secret).parent / Path(it.default_path).name


def load(cfg, key: str) -> dict:
    """Giá trị đang lưu (kể cả mã bí mật: chỉ dùng phía server)."""
    p = path_of(cfg, BY_KEY[key])
    if not p.exists():
        return {}
    try:
        return {k: str(v) for k, v in tomllib.loads(p.read_text(encoding="utf-8")).items()}
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def mask(value: str) -> str:
    """'abcdef123456' → '••••3456' (ngắn quá thì chỉ chấm)."""
    value = value or ""
    return ("••••" + value[-4:]) if len(value) > 8 else ("••••" if value else "")


def view(cfg, key: str) -> dict:
    """Giá trị gửi lên trình duyệt: ô thường hiện nguyên, ô bí mật chỉ hiện dạng che."""
    it, cur = BY_KEY[key], load(cfg, key)
    return {f.key: (mask(cur.get(f.key, "")) if f.secret else cur.get(f.key, "")) for f in it.fields}


def configured(cfg, key: str) -> bool:
    cur = load(cfg, key)
    return all(cur.get(k) for k in BY_KEY[key].required)


def merge(cfg, key: str, values: dict) -> dict:
    """Giá trị mới: ô bí mật bỏ trống (hoặc còn dạng che) = giữ mã cũ."""
    it, cur = BY_KEY[key], load(cfg, key)
    out = {}
    for f in it.fields:
        v = (values.get(f.key) or "").strip()
        if f.secret and (not v or v.startswith("••••")):
            v = cur.get(f.key, "")
        out[f.key] = v
    missing = [f.label for f in it.fields if f.key in it.required and not out.get(f.key)]
    if missing:
        raise ValueError("Chưa điền: " + ", ".join(missing))
    return out


def _toml(values: dict, header: str) -> str:
    lines = [f"# {header}. File chứa mã bí mật: không gửi cho ai, không đưa lên git."]
    lines += [f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in values.items() if v != ""]
    return "\n".join(lines) + "\n"


def save(cfg, key: str, values: dict) -> None:
    """Ghi file (ghi file tạm rồi thay, để không bao giờ còn file ghi dở)."""
    it = BY_KEY[key]
    p = path_of(cfg, it)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(_toml(values, f"{it.name}: sửa ở màn Cài đặt tích hợp của tool"), encoding="utf-8")
    os.replace(tmp, p)


# ---- Kiểm tra kết nối: (được hay không, câu hiện cho người dùng) ----

def _test_dataforseo(cfg, v: dict) -> tuple[bool, str]:
    from . import rank as R
    try:
        bal = R.DataForSEO(v["login"], v["password"], timeout=30).balance()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            msg = "login hoặc API password không đúng"
        return False, f"Không kết nối được DataForSEO: {msg}"
    return True, (f"Kết nối được. Số dư DataForSEO: {R.usd(float(bal))} USD" if bal is not None
                  else "Kết nối được")


def _test_google_ads(cfg, v: dict) -> tuple[bool, str]:
    from . import auth
    from . import google_ads as GA
    s = {"developer_token": v["developer_token"], "login_customer_id": GA._digits(v.get("login_customer_id")),
         "customer_id": GA._digits(v["customer_id"]), "api_version": v.get("api_version") or GA.API_VERSION}
    try:
        creds = auth.get_credentials(cfg, need=(auth.ADS_SCOPE,))
    except SystemExit:
        return False, "Tài khoản Google của tool chưa cấp quyền Google Ads: bấm Kết nối Google ở trên"
    try:
        res = GA.historical_metrics(creds, s, ["seo"], cfg.rank.location_code, cfg.rank.language_code, timeout=30)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    vol = next((r["search_volume"] for r in res["result"]), None)
    return True, "Kết nối được, lấy được volume" + (f" (thử “seo”: {vol:,}/tháng)".replace(",", ".") if vol else "")


def _test_ai(cfg, v: dict) -> tuple[bool, str]:
    import anthropic
    try:
        client = anthropic.Anthropic(api_key=v["api_key"], timeout=30.0, max_retries=1)
        ids = [m.id for m in client.models.list(limit=50)]
    except anthropic.AuthenticationError:
        return False, "Khóa API không đúng hoặc đã bị thu hồi"
    except anthropic.PermissionDeniedError:
        return False, "Khóa API không có quyền gọi API"
    except anthropic.APIConnectionError:
        return False, "Không kết nối được tới Anthropic (kiểm tra mạng)"
    except anthropic.APIStatusError as e:
        return False, f"Anthropic báo lỗi {e.status_code}"
    model = v.get("model") or "claude-opus-5-5"
    if ids and model not in ids:
        return True, f"Khóa dùng được, nhưng tài khoản chưa có model {model}"
    return True, "Khóa dùng được" + (f", model {model} sẵn sàng" if model else "")


def _test_google_api(cfg, v: dict) -> tuple[bool, str]:
    """Gọi thử CrUX (website của dự án gốc) và PageSpeed (trang chủ, nhanh: chỉ hạng mục SEO)."""
    from . import cwv as C
    from .projects import domain
    c = C.Client(v["api_key"], timeout=60)
    origin = f"https://{domain(cfg.site_url)}"
    try:
        c.crux_history(origin, "PHONE")
        crux = "có số CrUX của website"
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "404" in msg:
            crux = "CrUX chưa có số cho website này (ít lượt truy cập Chrome), key vẫn dùng được"
        elif "403" in msg or "400" in msg:
            return False, f"Chrome UX Report API: {msg[:200]}. Kiểm tra key và đã bật “Chrome UX Report API”"
        else:
            return False, f"Chrome UX Report API lỗi: {msg[:200]}"
    try:
        from urllib.parse import urlencode
        from urllib.request import Request
        c._json(Request("https://www.googleapis.com/pagespeedonline/v5/runPagespeed?" + urlencode(
            [("url", origin + "/"), ("category", "SEO"), ("key", v["api_key"])])))
    except Exception as e:  # noqa: BLE001
        return False, f"PageSpeed Insights API: {str(e)[:200]}. Kiểm tra đã bật “PageSpeed Insights API”"
    return True, f"Key dùng được: PageSpeed chạy được, {crux}"


TESTS = {"dataforseo": _test_dataforseo, "google_ads": _test_google_ads, "ai": _test_ai,
         "google_api": _test_google_api}


def test(cfg, key: str, values: dict) -> tuple[bool, str]:
    return TESTS[key](cfg, values)


# ---- Thư mục Google Drive (config.toml [drive] parent_folder) ----

def set_drive_folder(config_path: Path, folder_id: str) -> None:
    """Ghi [drive] parent_folder vào config.toml (giữ nguyên các dòng khác, kể cả ghi chú)."""
    import re
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    line = f'parent_folder = {json.dumps(folder_id)}'
    sec = re.search(r"(?m)^\[drive\]\s*$", text)
    if not sec:
        text = text.rstrip("\n") + f"\n\n[drive]\n{line}\n"
    else:
        nxt = re.search(r"(?m)^\[", text[sec.end():])
        end = sec.end() + (nxt.start() if nxt else len(text) - sec.end())
        body = text[sec.end():end]
        if re.search(r"(?m)^[ \t]*parent_folder[ \t]*=", body):
            body = re.sub(r"(?m)^[ \t]*parent_folder[ \t]*=.*$", line, body, count=1)
        else:
            body = "\n" + line + body
        text = text[:sec.end()] + body + text[end:]
    tmp = config_path.with_suffix(".toml.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, config_path)
