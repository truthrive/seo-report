"""Chặn bot AI thu thập dữ liệu để huấn luyện / học từ tool.

Ba lớp, lớp sau đỡ cho lớp trước:
1. /robots.txt cấm các bot AI đã công bố tên (bot tử tế sẽ tự dừng) và cấm mọi bot vào toàn bộ tool.
2. Header X-Robots-Tag + thẻ meta: không index, không lưu bản sao, không dùng cho AI.
3. Middleware trả 403 ngay khi User-Agent là bot AI (bot không nghe robots.txt vẫn bị chặn).

Chỉ chặn được bot khai đúng tên. Bot giả User-Agent trình duyệt thì dựa vào lớp đăng nhập (access.py) và
Cloudflare Access ở phía trước tool."""
from __future__ import annotations

# Tên (viết thường) xuất hiện trong User-Agent của crawler AI / thu thập dữ liệu huấn luyện đã công bố.
AI_BOTS = (
    "gptbot", "chatgpt-user", "oai-searchbot", "openai",
    "claudebot", "claude-web", "claude-user", "claude-searchbot", "anthropic-ai",
    "google-extended", "googleother", "google-cloudvertexbot", "gemini-deep-research",
    "perplexitybot", "perplexity-user",
    "ccbot", "bytespider", "amazonbot", "applebot-extended", "facebookbot", "meta-externalagent",
    "meta-externalfetcher", "cohere-ai", "cohere-training-data-crawler", "diffbot", "omgili", "omgilibot",
    "imagesiftbot", "timpibot", "youbot", "duckassistbot", "mistralai-user", "petalbot", "ai2bot",
    "ai2bot-dolma", "friendlycrawler", "img2dataset", "scrapy", "semrushbot-ocob", "webzio",
    "kangaroo bot", "velenpublicwebcrawler", "iaskspider", "panscient", "sidetrade",
)

BLOCKED_BODY = b"Forbidden"
ROBOT_TAGS = "noindex, nofollow, noarchive, nosnippet, noimageindex, noai, noimageai"

ROBOTS_TXT = (
    "\n".join(f"User-agent: {name}\nDisallow: /\n" for name in (
        "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-Web", "Claude-User", "Claude-SearchBot",
        "anthropic-ai", "Google-Extended", "GoogleOther", "PerplexityBot", "Perplexity-User", "CCBot", "Bytespider",
        "Amazonbot", "Applebot-Extended", "FacebookBot", "meta-externalagent", "meta-externalfetcher", "cohere-ai",
        "Diffbot", "Omgilibot", "ImagesiftBot", "Timpibot", "YouBot", "DuckAssistBot", "PetalBot", "img2dataset"))
    + "\nUser-agent: *\nDisallow: /\n"
)


def is_ai_bot(user_agent: str | None) -> bool:
    ua = (user_agent or "").lower()
    return any(name in ua for name in AI_BOTS)


class AIBotBlocker:
    """Middleware ASGI thuần (không dùng BaseHTTPMiddleware để không làm hỏng websocket của NiceGUI)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        ua = ""
        for k, v in scope.get("headers") or []:
            if k == b"user-agent":
                ua = v.decode("latin-1")
                break
        if is_ai_bot(ua):
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            await send({"type": "http.response.start", "status": 403, "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(BLOCKED_BODY)).encode()),
                (b"x-robots-tag", ROBOT_TAGS.encode())]})
            return await send({"type": "http.response.body", "body": BLOCKED_BODY})
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_tagged(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-robots-tag"]
                headers.append((b"x-robots-tag", ROBOT_TAGS.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_tagged)


# Răn đe mở DevTools từ bàn phím / menu chuột phải. Trình duyệt luôn cho người dùng mở được DevTools, nên đây chỉ là
# rào cản nhẹ; dữ liệu thật được bảo vệ ở máy chủ (access.py). Ô nhập liệu vẫn giữ menu sao chép / dán.
DEVTOOLS_JS = """<script>(() => {
  const editable = t => t && t.closest && t.closest('input, textarea, select, [contenteditable]');
  document.addEventListener('contextmenu', e => { if (!editable(e.target)) e.preventDefault(); }, true);
  document.addEventListener('keydown', e => {
    const mod = e.ctrlKey || e.metaKey;
    const tools = e.code === 'F12'
      || (mod && e.shiftKey && ['KeyI', 'KeyJ', 'KeyC', 'KeyK'].includes(e.code))
      || (e.metaKey && e.altKey && ['KeyI', 'KeyJ', 'KeyC', 'KeyU'].includes(e.code))
      || (e.ctrlKey && !e.shiftKey && e.code === 'KeyU');
    if (tools) { e.preventDefault(); e.stopPropagation(); }
  }, true);
})();</script>"""


def install(app, ui) -> None:
    """Gắn vào ứng dụng NiceGUI: middleware, /robots.txt và thẻ meta cho mọi trang."""
    from fastapi.responses import PlainTextResponse

    app.add_middleware(AIBotBlocker)

    @app.get("/robots.txt")
    def robots_txt():
        return PlainTextResponse(ROBOTS_TXT)

    ui.add_head_html(f'<meta name="robots" content="{ROBOT_TAGS}">', shared=True)
    ui.add_head_html(DEVTOOLS_JS, shared=True)
