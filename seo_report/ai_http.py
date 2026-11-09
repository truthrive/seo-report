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


def complete(style: str, base: str, key: str, model: str, prompt: str, system: str = "", max_tokens: int = 1024,
             timeout: int = 120, opener=None) -> str:
    """Gửi một câu hỏi, trả về chữ AI trả lời. Lỗi → AIError với câu dễ hiểu (không chứa khóa)."""
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
        if e.code in (401, 403):
            raise AIError("Khóa API không đúng hoặc không có quyền") from e
        if e.code == 429:
            raise AIError("Nhà cung cấp đang giới hạn lượt gọi hoặc hết hạn mức, thử lại sau") from e
        raise AIError(f"Nhà cung cấp báo lỗi {e.code}: {detail}") from e
    except URLError as e:
        raise AIError("Không kết nối được tới nhà cung cấp AI (kiểm tra Base URL và mạng)") from e
    return parse(style, data)


def curl_example(style: str, base: str, model: str, prompt: str = "Hello") -> str:
    """Ví dụ cURL để thử ở terminal; khóa để dạng $API_KEY (không in khóa thật lên trang)."""
    url, head, body = request_parts(style, base or "https://…", "$API_KEY", model or "MODEL", prompt)
    lines = [f"curl {url} \\"] + [f'  -H "{k}: {v}" \\' for k, v in head.items()]
    lines += ['  -H "Content-Type: application/json" \\', f"  -d '{json.dumps(body, ensure_ascii=False)}'"]
    return "\n".join(lines)


def settings_for(cfg, provider: str) -> dict | None:
    """Cấu hình gọi của một nhà cung cấp đã nhập khóa: {style, base, key, model}; chưa có khóa → None."""
    from . import integrations as I
    v = I.load(cfg, provider)
    if not v.get("api_key"):
        return None
    if provider == "gateway":
        return {"style": v.get("api_style") or "chat", "base": v.get("base_url", ""), "key": v["api_key"],
                "model": v.get("model", "")}
    style, base = PRESETS[provider]
    return {"style": style, "base": base, "key": v["api_key"], "model": v.get("model", "")}
