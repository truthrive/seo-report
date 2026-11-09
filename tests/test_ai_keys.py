import io
import json
import unittest
from urllib.error import HTTPError

from seo_report import integrations as I


def opener(status=200, body=None):
    def open_(req, timeout=0):
        if status != 200:
            raise HTTPError(req.full_url, status, "x", {}, io.BytesIO(b""))
        return io.BytesIO(json.dumps(body or {}).encode())
    return open_


class AiKeysTest(unittest.TestCase):
    def test_providers_listed_as_ai_group(self):
        self.assertEqual(I.AI_PROVIDERS, ["ai", "openai", "gemini", "perplexity", "xai", "deepseek", "gateway"])
        for k in I.AI_PROVIDERS:
            it = I.BY_KEY[k]
            self.assertTrue(any(f.secret and f.key == "api_key" for f in it.fields))
            self.assertIn(k, I.TESTS)

    def test_key_check(self):
        ok, msg = I._test_key("openai", opener(body={"data": [{"id": "m1"}, {"id": "m2"}]}))(None, {"api_key": "k"})
        self.assertTrue(ok)
        self.assertIn("2 model", msg)
        ok, msg = I._test_key("gemini", opener(body={"models": [{"name": "models/g1"}]}))(
            None, {"api_key": "k", "model": "g2"})
        self.assertTrue(ok)
        self.assertIn("g2", msg)
        self.assertFalse(I._test_key("xai", opener(401))(None, {"api_key": "k"})[0])
        self.assertTrue(I._test_key("perplexity", opener(404))(None, {"api_key": "k"})[0])


class GatewayTest(unittest.TestCase):
    def test_gateway_check(self):
        v = {"base_url": "https://api.example.com/v1", "api_style": "chat", "model": "m1", "api_key": "k"}
        self.assertTrue(I._test_gateway(None, v, opener(body={"data": [{"id": "m1"}]}))[0])
        self.assertFalse(I._test_gateway(None, {**v, "base_url": "http://api.example.com"}, opener())[0])
        self.assertTrue(I._test_gateway(None, {**v, "base_url": "http://localhost:11434", "api_style": "generate"},
                                        opener(body={"models": [{"name": "m1"}]}))[0])
        self.assertFalse(I._test_gateway(None, v, opener(401))[0])
        self.assertTrue(I._test_gateway(None, v, opener(404))[0])


class AiHttpTest(unittest.TestCase):
    def test_request_and_parse_every_style(self):
        from seo_report import ai_http as AH
        replies = {"chat": {"choices": [{"message": {"content": "ok"}}]}, "completions": {"choices": [{"text": "ok"}]},
                   "messages": {"content": [{"type": "text", "text": "ok"}]}, "responses": {"output_text": "ok"},
                   "gemini": {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
                   "ollama": {"message": {"content": "ok"}}, "generate": {"response": "ok"}}
        for style, body in replies.items():
            seen = {}

            def open_(req, timeout=0, body=body, seen=seen):
                seen["url"], seen["h"] = req.full_url, dict(req.header_items())
                return io.BytesIO(json.dumps(body).encode())
            out = AH.complete(style, "https://gw.example/v1", "SECRET", "m", "hi", system="s", opener=open_)
            self.assertEqual(out, "ok", style)
            self.assertNotIn("SECRET", seen["url"])  # khóa không nằm trong URL
        url, _, _ = AH.request_parts("generate", "https://gw.example/v1", "k", "m", "hi")
        self.assertEqual(url, "https://gw.example/api/generate")
        self.assertNotIn("SECRET", AH.curl_example("chat", "https://gw.example/v1", "m"))

    def test_errors_are_readable(self):
        from seo_report import ai_http as AH
        with self.assertRaises(AH.AIError):
            AH.complete("chat", "https://gw.example/v1", "k", "m", "hi", opener=opener(401))
        with self.assertRaises(AH.AIError):
            AH.complete("chat", "https://gw.example/v1", "k", "m", "hi", opener=opener(body={"x": 1}))


if __name__ == "__main__":
    unittest.main()
