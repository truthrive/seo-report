"""Gọi AI trực tiếp bằng HTTP (không cần SDK riêng của từng hãng): một hàm `complete` cho mọi kiểu API phổ biến.

Kiểu API (route) và định dạng gửi / nhận:
- chat          POST {base}/chat/completions   OpenAI và các cổng tương thích OpenAI (xAI, DeepSeek, Perplexity…)
- completions   POST {base}/completions        kiểu cũ của OpenAI (prompt → text)
- messages      POST {base}/messages           Anthropic (x-api-key + anthropic-version)
- responses     POST {base}/responses          OpenAI Responses API
- gemini        POST {base}/models/{model}:generateContent   Google Gemini
- ollama        POST {gốc}/api/chat            Ollama (gốc = base bỏ /v1 ở cuối)
- generate      POST {gốc}/api/generate        Ollama / cổng kiểu /api/generate (prompt → response)

Khóa chỉ đi trong header, không bao giờ nằm trong URL. Gọi AI tốn tiền: chỉ gọi khi người dùng bấm nút."""
import json
import time
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STYLES = {"chat": "/chat/completions (OpenAI và tương thích)", "completions": "/completions",
          "messages": "/messages (Anthropic)", "responses": "/responses (OpenAI Responses)",
          "gemini": "Gemini generateContent", "ollama": "/api/chat (Ollama)", "generate": "/api/generate"}

# Nhà cung cấp có sẵn trong Cài đặt tích hợp → (kiểu API, base URL)
PRESETS = {"ai": ("messages", "https://api.anthropic.com/v1"), "openai": ("chat", "https://api.openai.com/v1"),
           "xai": ("chat", "https://api.x.ai/v1"), "deepseek": ("chat", "https://api.deepseek.com"),
           "perplexity": ("chat", "https://api.perplexity.ai"),
           "gemini": ("gemini", "https://generativelanguage.googleapis.com/v1beta")}


class AIError(RuntimeError):
    pass


class QuotaError(AIError):
    """Lỗi không tự hết khi gọi lại: hết hạn mức / hết tiền / cần chấp nhận giá mới / khóa sai. Lịch tự động không gọi
    lại cho tới khi đổi cài đặt."""


class UpstreamError(AIError):
    """Máy chủ phía trên tạm sập (502 / 503 / 504), hết giờ chờ, mất kết nối: gọi lại sau có thể được; có model dự
    phòng thì chuyển ngay."""


class TruncatedError(AIError):
    """Câu trả lời bị cắt cụt vì hết hạn mức chữ (max_tokens)."""


class FormatError(AIError):
    """Cần JSON mà câu trả lời không đọc được."""


MAX_TOKENS_CAP = 16000


def _root(base: str) -> str:
    base = base.rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def request_parts(style: str, base: str, key: str, model: str, prompt: str, system: str = "",
                  max_tokens: int = 1024) -> tuple[str, dict, dict]:
    """(URL, header, body) cho một lần gọi; tách riêng để test và để hiện ví dụ cURL."""
    base = base.rstrip("/")
    bearer = {"Authorization": f"Bearer {key}"}
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    if style == "chat":
        return f"{base}/chat/completions", bearer, {"model": model, "messages": msgs, "max_tokens": max_tokens}
    if style == "completions":
        return f"{base}/completions", bearer, {"model": model, "prompt": (system + "\n\n" if system else "") + prompt,
                                               "max_tokens": max_tokens}
    if style == "messages":
        body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        return f"{base}/messages", {"x-api-key": key, "anthropic-version": "2023-06-01"}, body
    if style == "responses":
        body = {"model": model, "input": prompt, "max_output_tokens": max_tokens}
        if system:
            body["instructions"] = system
        return f"{base}/responses", bearer, body
    if style == "gemini":
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return f"{base}/models/{model}:generateContent", {"x-goog-api-key": key}, body
    if style == "ollama":
        return f"{_root(base)}/api/chat", bearer, {"model": model, "messages": msgs, "stream": False}
    if style == "generate":
        body = {"model": model, "prompt": prompt, "stream": False}
        if system:
            body["system"] = system
        return f"{_root(base)}/api/generate", bearer, body
    raise AIError(f"Kiểu API không hỗ trợ: {style}")


def parse(style: str, data: dict) -> str:
    """Lấy phần chữ AI trả lời từ JSON của từng kiểu API."""
    try:
        if style == "chat":
            return data["choices"][0]["message"]["content"] or ""
        if style == "completions":
            return data["choices"][0]["text"] or ""
        if style == "messages":
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        if style == "responses":
            if data.get("output_text"):
                return data["output_text"]
            return "".join(c.get("text", "") for o in data.get("output", []) for c in o.get("content", []) or []
                           if c.get("type") in ("output_text", "text"))
        if style == "gemini":
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        if style == "ollama":
            return data["message"]["content"] or ""
        if style == "generate":
            return data["response"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"Không đọc được câu trả lời ({style}): {str(data)[:200]}") from e
    raise AIError(f"Kiểu API không hỗ trợ: {style}")


def cut_off(style: str, data: dict) -> bool:
    """Câu trả lời bị dừng vì hết hạn mức chữ."""
    try:
        if style in ("chat", "completions"):
            return data["choices"][0].get("finish_reason") == "length"
        if style == "messages":
            return data.get("stop_reason") == "max_tokens"
        if style == "gemini":
            return data["candidates"][0].get("finishReason") == "MAX_TOKENS"
        if style == "responses":
            return data.get("status") == "incomplete"
        if style in ("ollama", "generate"):
            return data.get("done_reason") == "length"
    except (KeyError, IndexError, TypeError, AttributeError):
        return False
    return False


def complete(style: str, base: str, key: str, model: str, prompt: str, system: str = "", max_tokens: int = 1024,
             timeout: int = 120, opener=None, allow_cut: bool = False) -> str:
    """Gửi một câu hỏi, trả về chữ AI trả lời. Lỗi → AIError với câu dễ hiểu (không chứa khóa). allow_cut: chấp nhận
    câu trả lời bị cắt cụt (gọi thử vài chữ); mặc định bị cắt cụt → TruncatedError."""
    url, head, body = request_parts(style, base, key, model, prompt, system, max_tokens)
    req = Request(url, data=json.dumps(body).encode(), method="POST",
                  headers={**head, "Content-Type": "application/json", "User-Agent": "seo-report"})
    try:
        with (opener or urlopen)(req, timeout=timeout) as r:
            data = json.loads(r.read() or b"{}")
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            detail = ""
        # câu lỗi hiện cho người dùng: không kèm tên model (model chỉ xem ở Quản trị › AI, nhật ký có cột riêng)
        detail = re.sub(r'"model"\s*:\s*"[^"]*"\s*,?\s*', "", detail)
        low = detail.lower()
        if e.code == 403 and "upstream" in low:
            raise QuotaError("Model AI chính đang bị phía người bán trên cổng từ chối (lỗi của họ, không phải khóa): "
                             "chọn model khác hoặc thêm model dự phòng ở Quản trị › AI") from e
        if e.code in (401, 403):
            raise QuotaError("Khóa API không đúng hoặc không có quyền") from e
        if e.code == 402 or "insufficient_quota" in low:
            if "price" in low:
                raise QuotaError("Cổng AI đã đổi giá model đang dùng: vào trang quản lý của cổng để chấp nhận giá mới, "
                                 "hoặc chọn model khác ở Quản trị › AI") from e
            raise QuotaError("Tài khoản AI hết hạn mức / hết tiền: nạp thêm ở trang của nhà cung cấp hoặc đổi model") from e
        if e.code == 404 or (e.code == 400 and "model" in low and ("not found" in low or "not exist" in low
                                                                      or "invalid" in low)):
            raise QuotaError("Model đang dùng không còn trên nhà cung cấp (bị gỡ hoặc sai tên): chọn model khác ở "
                             "Quản trị › AI") from e
        if e.code in (502, 503, 504):
            raise UpstreamError(f"Model AI tạm thời không phản hồi (lỗi {e.code} phía nhà cung cấp), thử lại sau "
                                "hoặc thêm model dự phòng ở Quản trị › AI") from e
        if e.code == 429:
            raise AIError("Nhà cung cấp đang giới hạn lượt gọi hoặc hết hạn mức, thử lại sau") from e
        raise AIError(f"Nhà cung cấp báo lỗi {e.code}: {detail}") from e
    except URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise UpstreamError(f"Model AI không trả lời sau {timeout} giây (hết giờ chờ)") from e
        raise UpstreamError("Không kết nối được tới nhà cung cấp AI (kiểm tra Base URL và mạng)") from e
    except TimeoutError as e:
        raise UpstreamError(f"Model AI không trả lời sau {timeout} giây (hết giờ chờ)") from e
    except (OSError, ValueError) as e:  # mất kết nối giữa chừng / trả về không phải JSON
        raise UpstreamError(f"Nhà cung cấp trả lời hỏng giữa chừng: {type(e).__name__}") from e
    from . import ai_usage as AU
    AU.note(model, style, data)  # đếm token (nhật ký chi phí AI)
    out = parse(style, data)
    if not allow_cut and cut_off(style, data):
        raise TruncatedError(f"Câu trả lời của AI bị cắt cụt (hết {max_tokens} chữ)")
    return out


DOWN_MINUTES = 20  # model chính vừa bị chặn / sập: trong khoảng này gọi thẳng model dự phòng
_DOWN: dict[tuple, float] = {}


def _sig(p: dict) -> tuple:
    return (p.get("base"), p.get("model"))


def is_down(p: dict) -> bool:
    t = _DOWN.get(_sig(p))
    return bool(t and t > time.time())


def _mark_down(p: dict) -> None:
    _DOWN[_sig(p)] = time.time() + DOWN_MINUTES * 60


def json_ok(text: str) -> bool:
    """Câu trả lời có một đối tượng JSON đọc được (model có thể bọc ```json … ``` hoặc thêm chữ trước / sau)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return False
    try:
        return isinstance(json.loads(m.group(0)), dict)
    except ValueError:
        return False


def _one(p: dict, prompt: str, expect_json: bool, kw: dict) -> str:
    """Gọi một model. Bị cắt cụt (hết hạn mức chữ) thì gọi lại một lần với hạn mức gấp đôi; cần JSON mà không đọc
    được thì FormatError."""
    try:
        out = complete(p["style"], p["base"], p["key"], p["model"], prompt, **kw)
    except TruncatedError:
        more = {**kw, "max_tokens": min(int(kw.get("max_tokens") or 1024) * 2, MAX_TOKENS_CAP)}
        out = complete(p["style"], p["base"], p["key"], p["model"], prompt, **more)
    if expect_json and not json_ok(out):
        raise FormatError("AI không trả về đúng định dạng")
    return out


def ask(prov: dict, prompt: str, expect_json: bool = False, **kw) -> str:
    """Gọi model của `prov` (dict từ ai_writer.provider), có dự phòng:
    - Model chính lỗi (bị chặn, sập, hết giờ chờ, bị cắt cụt, sai định dạng…) thì lần lượt thử các model dự phòng
      (prov["fallbacks"]). Không có dự phòng mà sai định dạng thì gọi lại model chính một lần.
    - Model chính bị chặn / sập thì DOWN_MINUTES phút sau gọi thẳng model dự phòng (không chờ model hỏng mỗi lần).
    - prov được đổi theo model thực dùng (để nhật ký / bản lưu ghi đúng). Lần bị chặn được báo lên chuông."""
    from . import ai_usage as AU
    AU.start()
    try:
        return _ask(prov, prompt, expect_json, **kw)
    finally:
        AU.finish(prov)  # ghi token của mọi lần gọi thật (kể cả gọi lại / dự phòng); lỗi ghi không ảnh hưởng


def _ask(prov: dict, prompt: str, expect_json: bool = False, **kw) -> str:
    from . import ai_settings as AIS
    chain = prov.get("fallbacks") or ([prov["fallback"]] if prov.get("fallback") else [])
    main = {k: prov.get(k) for k in ("name", "key_name", "style", "base", "key", "model")}
    skip_main = bool(chain) and is_down(main)
    main_err: AIError | None = None
    if not skip_main:
        tries = 1 if chain else 2
        for n in range(tries):
            try:
                out = _one(main, prompt, expect_json, kw)
            except FormatError as e:
                main_err = e
                continue  # không có dự phòng: gọi lại một lần
            except (QuotaError, UpstreamError) as e:
                main_err = e
                _mark_down(main)
                break
            except AIError as e:
                main_err = e
                break
            _DOWN.pop(_sig(main), None)
            AIS.clear_block(main)
            return out
        if not chain:
            if isinstance(main_err, (QuotaError, UpstreamError)):
                AIS.note_block(main, str(main_err), None)
            raise main_err
    blocked = skip_main or isinstance(main_err, (QuotaError, UpstreamError))
    reason = str(main_err) if main_err else "Model chính vừa lỗi, tạm dùng model dự phòng"  # không ghi tên model
    ups = [fb for fb in chain if not is_down(fb)] + [fb for fb in chain if is_down(fb)]
    for fb in ups:
        try:
            out = _one(fb, prompt, expect_json, kw)
        except AIError as e:
            if isinstance(e, (QuotaError, UpstreamError)):
                _mark_down(fb)
            continue  # model dự phòng này cũng lỗi: thử model kế tiếp
        _DOWN.pop(_sig(fb), None)
        if blocked:
            AIS.note_block(main, reason, fb)
        prov.update({k: fb[k] for k in ("style", "base", "key", "model", "key_name") if k in fb})
        prov["name"] = f"{fb['name']} (dự phòng)"
        prov["fell_back"] = reason
        return out
    if blocked:
        AIS.note_block(main, reason, None)
    if main_err is None:  # đã bỏ qua model chính mà mọi model dự phòng đều lỗi: thử lại model chính
        return _one(main, prompt, expect_json, kw)
    raise main_err


def curl_example(style: str, base: str, model: str, prompt: str = "Hello") -> str:
    """Ví dụ cURL để thử ở terminal; khóa để dạng $API_KEY (không in khóa thật lên trang)."""
    url, head, body = request_parts(style, base or "https://…", "$API_KEY", model or "MODEL", prompt)
    lines = [f"curl {url} \\"] + [f'  -H "{k}: {v}" \\' for k, v in head.items()]
    lines += ['  -H "Content-Type: application/json" \\', f"  -d '{json.dumps(body, ensure_ascii=False)}'"]
    return "\n".join(lines)


def settings_for(cfg, provider: str) -> dict | None:
    """Cấu hình gọi của một nhà cung cấp đã nhập khóa: {style, base, key, model}; chưa có khóa → None."""
    from . import integrations as I
    I.sync_gateways(cfg)
    if provider not in I.BY_KEY:
        return None
    v = I.load(cfg, provider)
    if not v.get("api_key"):
        return None
    if I.is_gateway(provider):
        return {"style": v.get("api_style") or "chat", "base": v.get("base_url", ""), "key": v["api_key"],
                "model": v.get("model", "")}
    style, base = PRESETS[provider]
    return {"style": style, "base": base, "key": v["api_key"], "model": v.get("model", "")}
