import asyncio
import unittest

from seo_report import anti_bot as AB


async def inner(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": [(b"x-robots-tag", b"all")]})
    await send({"type": "http.response.body", "body": b"ok"})


def call(ua, scope_type="http"):
    out = []

    async def send(m):
        out.append(m)

    scope = {"type": scope_type, "headers": [(b"user-agent", ua.encode())] if ua else []}
    asyncio.run(AB.AIBotBlocker(inner)(scope, None, send))
    return out


class AntiBotTest(unittest.TestCase):
    def test_detects_ai_bots(self):
        for ua in ("Mozilla/5.0 AppleWebKit/537.36; compatible; GPTBot/1.1; +https://openai.com/gptbot",
                   "ClaudeBot/1.0", "CCBot/2.0", "Mozilla/5.0 (compatible; PerplexityBot/1.0)",
                   "Bytespider", "Google-Extended"):
            self.assertTrue(AB.is_ai_bot(ua), ua)

    def test_detects_search_engine_bots(self):
        for ua in ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
                   "Mozilla/5.0 (Linux; Android 6.0.1) Chrome/120 Mobile Safari/537.36 (compatible; Googlebot/2.1)",
                   "Mozilla/5.0 (compatible; bingbot/2.0)", "Mozilla/5.0 (compatible; AhrefsBot/7.0)",
                   "Mozilla/5.0 (compatible; Google-InspectionTool/1.0)"):
            self.assertTrue(AB.is_ai_bot(ua), ua)

    def test_normal_browsers_and_empty_pass(self):
        self.assertFalse(AB.is_ai_bot("Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537.36"))
        self.assertFalse(AB.is_ai_bot(""))
        self.assertFalse(AB.is_ai_bot(None))

    def test_bot_gets_403(self):
        out = call("GPTBot/1.1")
        self.assertEqual(out[0]["status"], 403)
        self.assertEqual(out[1]["body"], b"Forbidden")

    def test_human_passes_and_tag_is_replaced(self):
        out = call("Mozilla/5.0 Chrome/120")
        self.assertEqual(out[0]["status"], 200)
        tags = [v for k, v in out[0]["headers"] if k == b"x-robots-tag"]
        self.assertEqual(tags, [AB.ROBOT_TAGS.encode()])

    def test_websocket_bot_closed(self):
        out = call("ClaudeBot", "websocket")
        self.assertEqual(out[0]["type"], "websocket.close")

    def test_robots_txt_blocks_all(self):
        self.assertIn("User-agent: GPTBot\nDisallow: /", AB.ROBOTS_TXT)
        self.assertIn("User-agent: *\nDisallow: /", AB.ROBOTS_TXT)


if __name__ == "__main__":
    unittest.main()
