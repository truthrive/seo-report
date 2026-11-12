"""Cấu hình tích hợp (màn Cài đặt tích hợp, chỉ Chủ tool): DataForSEO, Google Ads, Google API, nhà cung cấp AI. Mỗi tích hợp khai báo các ô,
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
    group: str = "service"  # "service": dịch vụ số liệu; "ai": nhà cung cấp AI


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
    Integration("ai", "Anthropic (Claude)", "auto_awesome",
                "Nhà cung cấp AI chính của tool: viết nhận xét báo cáo, đoạn trả lời AI Overview, brief nội dung… "
                "Lấy khóa ở platform.claude.com > API keys.",
                [Field("api_key", "Khóa API", secret=True, placeholder="sk-ant-…"),
                 Field("model", "Model", options=AI_MODELS)],
                default_path="secrets/ai.toml", required=("api_key",), group="ai"),
    *[Integration(key, name, "smart_toy", about,
                  [Field("api_key", "Khóa API", secret=True, placeholder=ph),
                   Field("model", "Model mặc định (không bắt buộc)", placeholder="để trống: tool tự chọn",
                         hint="Ghi đúng tên model theo trang của nhà cung cấp")],
                  default_path=f"secrets/ai_{key}.toml", required=("api_key",), group="ai")
      for key, name, about, ph in (
          ("openai", "OpenAI (ChatGPT)",
           "Dùng để xem ChatGPT trả lời gì về thương hiệu (GEO) hoặc thay Claude cho một số việc. Lấy khóa ở "
           "platform.openai.com > API keys.", "sk-…"),
          ("gemini", "Google Gemini",
           "Dùng để xem Gemini trả lời gì về thương hiệu (GEO). Lấy khóa ở aistudio.google.com > Get API key.",
           "AIza…"),
          ("perplexity", "Perplexity",
           "Dùng để xem Perplexity trả lời và trích nguồn nào cho từ khóa (GEO). Lấy khóa ở perplexity.ai > Settings "
           "> API.", "pplx-…"),
          ("xai", "xAI (Grok)", "Dùng để xem Grok trả lời gì về thương hiệu (GEO). Lấy khóa ở console.x.ai.",
           "xai-…"),
          ("deepseek", "DeepSeek", "Nhà cung cấp AI giá rẻ cho việc đơn giản (phân loại, gom nhóm từ khóa). Lấy "
           "khóa ở platform.deepseek.com > API keys.", "sk-…"))],
]
from .ai_http import STYLES as _AI_STYLES  # noqa: E402

GATEWAY_NAME = "Cổng API tùy chỉnh"


def _gateway(key: str, name: str) -> Integration:
    """Một cổng API (proxy / router như 9router, Ollama, nhà bán lại…): key "gateway" là cổng đầu tiên, các cổng thêm
    sau có key gw2, gw3…; mỗi cổng một file khóa riêng."""
    return Integration(
        key, name, "hub",
        "Dùng cổng AI riêng (proxy / router như 9router, Ollama, nhà bán lại…) bằng gọi API trực tiếp: nhập Base URL, "
        "chọn kiểu route mà cổng hỗ trợ và khóa. Chọn model ở mục Combo AI. Thông tin này có trong trang hướng dẫn của "
        "cổng.",
        [Field("base_url", "Base URL", placeholder="https://api.example.com/v1",
               hint="Phần đứng trước route, thường kết thúc bằng /v1"),
         Field("api_style", "Kiểu route", options=_AI_STYLES),
         Field("api_key", "Khóa API", secret=True, placeholder="sk-…")],
        default_path=f"secrets/ai_{key}.toml", required=("base_url", "api_key"), group="ai")


INTEGRATIONS.append(_gateway("gateway", GATEWAY_NAME))
AI_PROVIDERS = [x.key for x in INTEGRATIONS if x.group == "ai"]
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
    """Giá trị mới: ô bí mật bỏ trống (hoặc còn dạng che) = giữ mã cũ. Giá trị đã lưu không còn ô nhập (ví dụ model
    cũ của cổng) thì giữ nguyên."""
    it, cur = BY_KEY[key], load(cfg, key)
    known = {f.key for f in it.fields}
    out = {k: v for k, v in cur.items() if k not in known}
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


# Nhà cung cấp AI khác: gọi danh sách model (miễn phí, không tốn lượt) để biết khóa còn dùng được.
_MODEL_LIST = {"openai": "https://api.openai.com/v1/models", "xai": "https://api.x.ai/v1/models",
               "deepseek": "https://api.deepseek.com/models", "perplexity": "https://api.perplexity.ai/models",
               "gemini": "https://generativelanguage.googleapis.com/v1beta/models"}


def _test_key(provider: str, opener=None):
    def run(cfg, v: dict) -> tuple[bool, str]:
        from urllib.error import HTTPError, URLError
        from urllib.request import Request, urlopen
        key = v["api_key"]
        head = {"x-goog-api-key": key} if provider == "gemini" else {"Authorization": f"Bearer {key}"}
        try:
            with (opener or urlopen)(Request(_MODEL_LIST[provider], headers={**head, "User-Agent": "seo-report"}),
                                     timeout=20) as r:
                data = json.loads(r.read() or b"{}")
        except HTTPError as e:
            if e.code in (401, 403):
                return False, "Khóa API không đúng, đã bị thu hồi hoặc chưa được cấp quyền"
            if e.code == 404:  # nhà cung cấp không có trang danh sách model: chưa kiểm tra được, vẫn cho lưu
                return True, "Đã nhận khóa; nhà cung cấp này không cho kiểm tra miễn phí, lần dùng đầu sẽ biết"
            if e.code == 429:
                return True, "Khóa nhận được nhưng đang bị giới hạn lượt gọi"
            return False, f"Nhà cung cấp báo lỗi {e.code}"
        except URLError:
            return False, "Không kết nối được tới nhà cung cấp (kiểm tra mạng)"
        ids = [m.get("id") or m.get("name", "").removeprefix("models/") for m in
               (data.get("data") or data.get("models") or [])]
        model = (v.get("model") or "").strip()
        if model and ids and model not in ids:
            return True, f"Khóa dùng được, nhưng không thấy model “{model}” trong tài khoản"
        return True, "Khóa dùng được" + (f", có {len(ids)} model" if ids else "")
    return run


def _test_gateway(cfg, v: dict, opener=None) -> tuple[bool, str]:
    """Cổng tùy chỉnh: kiểm tra Base URL rồi xin danh sách model (miễn phí). Cổng không có trang danh sách model
    thì vẫn cho lưu và ghi rõ chưa kiểm tra được."""
    from urllib.error import HTTPError, URLError
    from urllib.parse import urlparse
    from urllib.request import Request, urlopen
    base = (v.get("base_url") or "").strip().rstrip("/")
    u = urlparse(base)
    local = u.hostname in ("localhost", "127.0.0.1", "::1")
    if u.scheme not in ("https", "http") or not u.hostname or (u.scheme == "http" and not local):
        return False, "Base URL phải bắt đầu bằng https:// (http:// chỉ dùng cho máy này, ví dụ Ollama)"
    style = v.get("api_style") or "chat"
    root = base[:-3] if base.endswith("/v1") else base
    url = f"{root}/api/tags" if style in ("ollama", "generate") else f"{base}/models"
    key = v.get("api_key", "")
    head = {"Authorization": f"Bearer {key}", "x-api-key": key, "User-Agent": "seo-report"}
    if style == "gemini":
        head = {"x-goog-api-key": key, "User-Agent": "seo-report"}
    try:
        with (opener or urlopen)(Request(url, headers=head), timeout=20) as r:
            data = json.loads(r.read() or b"{}")
    except HTTPError as e:
        if e.code in (401, 403):
            return False, "Cổng báo khóa API không đúng hoặc không có quyền"
        if e.code in (404, 405):
            return True, "Kết nối được cổng; cổng không có trang danh sách model nên chưa kiểm tra được khóa"
        return False, f"Cổng báo lỗi {e.code}"
    except (URLError, ValueError):
        return False, "Không kết nối được tới Base URL (kiểm tra địa chỉ và mạng)"
    ids = [m.get("id") or m.get("name", "").removeprefix("models/") for m in
           (data.get("data") or data.get("models") or [])]
    model = (v.get("model") or "").strip()
    if model and ids and model not in ids:
        return True, f"Khóa dùng được, nhưng cổng không liệt kê model “{model}”: kiểm tra lại tên model"
    if model:  # gọi thử một câu rất ngắn: lộ ra lỗi chỉ có khi gọi model (hết hạn mức, đổi giá, model tắt…)
        from . import ai_http as AH
        try:
            AH.complete(style, base, key, model, "Trả lời: OK", max_tokens=5, timeout=40, opener=opener,
                        allow_cut=True)
        except AH.AIError as e:
            return False, f"Khóa dùng được nhưng gọi model lỗi: {e}"
        return True, "Khóa và model dùng được" + (f" (cổng có {len(ids)} model)" if ids else "")
    return True, "Khóa dùng được" + (f", cổng có {len(ids)} model" if ids else "")


TESTS = {"dataforseo": _test_dataforseo, "google_ads": _test_google_ads, "ai": _test_ai,
         "google_api": _test_google_api, "gateway": _test_gateway, **{k: _test_key(k) for k in _MODEL_LIST}}


def test(cfg, key: str, values: dict) -> tuple[bool, str]:
    if is_gateway(key):
        return _test_gateway(cfg, values)
    return TESTS[key](cfg, values)


# ---- Nhiều cổng API: danh sách cổng (tên, key) lưu ở secrets/ai_gateways.json; khóa từng cổng ở file riêng ----
MAX_GATEWAYS = 8


def is_gateway(key: str | None) -> bool:
    return bool(key) and (key == "gateway" or (key.startswith("gw") and key[2:].isdigit()))


def _gw_file(cfg) -> Path:
    return Path(cfg.client_secret).parent / "ai_gateways.json"


def _host(cfg, key: str) -> str:
    """Tên tự đặt của cổng theo Base URL đã lưu: api.xah.io, localhost:20128…"""
    from urllib.parse import urlparse
    try:
        u = urlparse((load(cfg, key).get("base_url") or "").strip())
    except (KeyError, ValueError):
        return ""
    if not u.hostname:
        return ""
    return u.hostname + (f":{u.port}" if u.port else "")


def gateways(cfg) -> list[dict]:
    """[{key, name, custom}] theo thứ tự; cổng "gateway" luôn đứng đầu. Chưa đặt tên riêng thì tên = Base URL."""
    try:
        rows = json.loads(_gw_file(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    out = [{"key": "gateway", "name": ""}]
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not is_gateway(r.get("key")):
            continue
        name = " ".join(str(r.get("name") or "").split())[:40]
        if r["key"] == "gateway":
            out[0]["name"] = "" if name == GATEWAY_NAME else name  # tên mặc định cũ: coi như chưa đặt tên
        elif all(x["key"] != r["key"] for x in out):
            out.append({"key": r["key"], "name": name})
    for x in out:
        x["custom"] = bool(x["name"])
        if not x["name"]:
            x["name"] = _host(cfg, x["key"]) if x["key"] in BY_KEY else ""
            x["name"] = x["name"] or ("Cổng API mới" if x["key"] != "gateway" else GATEWAY_NAME)
    return out


def _save_gateways(cfg, rows: list[dict]) -> None:
    p = _gw_file(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    rows = [{"key": r["key"], "name": r["name"] if r.get("custom", True) else ""} for r in rows]
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    sync_gateways(cfg)


def sync_gateways(cfg) -> None:
    """Đăng ký các cổng trong danh sách vào INTEGRATIONS / BY_KEY / AI_PROVIDERS (bỏ cổng đã xóa)."""
    try:
        rows = gateways(cfg)
    except (AttributeError, TypeError):  # cấu hình không có thư mục khóa (test)
        return
    want = {r["key"]: r["name"] for r in rows}
    for it in [x for x in INTEGRATIONS if is_gateway(x.key)]:
        if it.key not in want:
            INTEGRATIONS.remove(it)
            BY_KEY.pop(it.key, None)
    for key, name in want.items():
        it = BY_KEY.get(key)
        if it is None:
            it = _gateway(key, name)
            INTEGRATIONS.append(it)
            BY_KEY[key] = it
    for r in gateways(cfg):  # tên theo Base URL cần cổng đã đăng ký
        BY_KEY[r["key"]].name = r["name"]
    AI_PROVIDERS[:] = [x.key for x in INTEGRATIONS if x.group == "ai"]


def add_gateway(cfg, name: str = "") -> str:
    """Thêm một cổng; không đặt tên thì tên tự lấy theo Base URL khi lưu."""
    rows = gateways(cfg)
    if len(rows) >= MAX_GATEWAYS:
        raise ValueError(f"Tối đa {MAX_GATEWAYS} cổng API")
    name = " ".join((name or "").split())[:40]
    if name and any(r["custom"] and r["name"].lower() == name.lower() for r in rows):
        raise ValueError("Đã có cổng trùng tên")
    n = 2
    while any(r["key"] == f"gw{n}" for r in rows):
        n += 1
    rows.append({"key": f"gw{n}", "name": name, "custom": bool(name)})
    _save_gateways(cfg, rows)
    return f"gw{n}"


def rename_gateway(cfg, key: str, name: str) -> None:
    """Đặt tên riêng cho cổng; để trống = tên theo Base URL."""
    rows = gateways(cfg)
    name = " ".join((name or "").split())[:40]
    if name and any(r["custom"] and r["name"].lower() == name.lower() and r["key"] != key for r in rows):
        raise ValueError("Đã có cổng trùng tên")
    for r in rows:
        if r["key"] == key:
            r["name"], r["custom"] = name, bool(name)
    _save_gateways(cfg, rows)


def remove_gateway(cfg, key: str) -> None:
    """Xóa một cổng thêm sau (cả file khóa của cổng). Cổng đầu tiên chỉ xóa được khóa, không xóa khỏi danh sách."""
    if key == "gateway" or not is_gateway(key):
        raise ValueError("Không xóa được cổng này")
    it = BY_KEY.get(key)
    if it:
        p = path_of(cfg, it)
        if p.exists():
            p.unlink()
    _save_gateways(cfg, [r for r in gateways(cfg) if r["key"] != key])


_MODELS_CACHE: dict = {}


def gateway_models(cfg, key: str, opener=None) -> list[str]:
    """Tên các model nhà cung cấp / cổng liệt kê (gọi trang danh sách model, miễn phí); nhớ 10 phút."""
    return [m["id"] for m in model_catalog(cfg, key, opener)]


def _price(m: dict) -> str:
    """Giá cổng ghi kèm model (nếu có): "455 / 260 VND" (vào / ra)."""
    p = m.get("pricing")
    if not isinstance(p, dict):
        return ""

    def num(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return f"{v:,.0f}".replace(",", ".") if v >= 10 or v == int(v) else f"{v:g}".replace(".", ",")
    a = num(p.get("input", p.get("prompt")))
    b = num(p.get("output", p.get("completion")))
    if a is None and b is None:
        return ""
    return f"{a or '–'} / {b or '–'} {p.get('unit') or ''}".strip()


def model_catalog(cfg, key: str, opener=None) -> list[dict]:
    """[{id, price}] các model nhà cung cấp / cổng liệt kê, xếp theo tên; nhớ 10 phút."""
    import time
    from urllib.request import Request, urlopen

    from . import ai_http as AH
    s = AH.settings_for(cfg, key)
    if not s or not s.get("base"):
        return []
    base, style, k = s["base"].strip().rstrip("/"), s["style"], s["key"]
    hit = _MODELS_CACHE.get((key, base))
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    root = base[:-3] if base.endswith("/v1") else base
    url = f"{root}/api/tags" if style in ("ollama", "generate") else f"{base}/models"
    head = {"Authorization": f"Bearer {k}", "x-api-key": k, "User-Agent": "seo-report"}
    if style == "gemini":
        head = {"x-goog-api-key": k, "User-Agent": "seo-report"}
    elif style == "messages":
        head = {"x-api-key": k, "anthropic-version": "2023-06-01", "User-Agent": "seo-report"}
    try:
        with (opener or urlopen)(Request(url, headers=head), timeout=20) as r:
            data = json.loads(r.read() or b"{}")
    except Exception:  # noqa: BLE001
        return []
    seen, out = set(), []
    for m in data.get("data") or data.get("models") or []:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or (m.get("name") or "").removeprefix("models/")
        if mid and mid not in seen:
            seen.add(mid)
            p = m.get("pricing") if isinstance(m.get("pricing"), dict) else None
            out.append({"id": mid, "price": _price(m), "pricing": {
                "input": p.get("input", p.get("prompt")), "output": p.get("output", p.get("completion")),
                "unit": p.get("unit") or ""} if p else None})
    out.sort(key=lambda x: x["id"].lower())
    _MODELS_CACHE[(key, base)] = (time.time(), out)
    return out


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
