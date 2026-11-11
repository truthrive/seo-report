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


def gateway_opener(models, chat_status=200, chat_detail=b""):
    """GET /models trả danh sách model; POST (gọi thử model) trả câu trả lời hoặc lỗi."""
    def open_(req, timeout=0):
        if req.get_method() == "POST":
            if chat_status != 200:
                raise HTTPError(req.full_url, chat_status, "x", {}, io.BytesIO(chat_detail))
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode())
        return io.BytesIO(json.dumps({"data": [{"id": m} for m in models]}).encode())
    return open_


class GatewayTest(unittest.TestCase):
    def test_model_call_errors_surface(self):
        v = {"base_url": "https://api.example.com/v1", "api_style": "chat", "model": "m1", "api_key": "k"}
        ok, msg = I._test_gateway(None, v, gateway_opener(["m1"]))
        self.assertTrue(ok)
        self.assertIn("model dùng được", msg)
        body = b'{"error":{"code":"insufficient_quota","message":"The price of this model has changed."}}'
        ok, msg = I._test_gateway(None, v, gateway_opener(["m1"], 402, body))
        self.assertFalse(ok)
        self.assertIn("chấp nhận giá mới", msg)

    def test_quota_error_is_not_retried(self):
        from seo_report import ai_http as AH

        def open_(req, timeout=0):
            raise HTTPError(req.full_url, 402, "x", {}, io.BytesIO(b'{"error":{"code":"insufficient_quota"}}'))
        with self.assertRaises(AH.QuotaError):
            AH.complete("chat", "https://api.example.com/v1", "k", "m1", "hi", opener=open_)

    def test_gateway_check(self):
        v = {"base_url": "https://api.example.com/v1", "api_style": "chat", "model": "m1", "api_key": "k"}
        self.assertTrue(I._test_gateway(None, v, gateway_opener(["m1"]))[0])
        self.assertFalse(I._test_gateway(None, {**v, "base_url": "http://api.example.com"}, opener())[0])
        def ollama(req, timeout=0):
            body = {"response": "OK"} if req.get_method() == "POST" else {"models": [{"name": "m1"}]}
            return io.BytesIO(json.dumps(body).encode())
        self.assertTrue(I._test_gateway(None, {**v, "base_url": "http://localhost:11434", "api_style": "generate"},
                                        ollama)[0])
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


class FallbackTest(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile

        from seo_report import ai_http as AH
        from seo_report import ai_settings as AIS
        AH._DOWN.clear()  # model "đang bị chặn" từ test trước không ảnh hưởng test sau
        self.AIS = AIS
        self.tmp = tempfile.mkdtemp()
        self.old = AIS._APP["path"]
        AIS._APP["path"] = os.path.join(self.tmp, "app.db")  # file dữ liệu tạm: không đụng dữ liệu thật

    def tearDown(self):
        self.AIS._APP["path"] = self.old

    def test_switches_to_fallback_and_reports(self):
        from seo_report import ai_http as AH

        def open_(req, timeout=0):
            body = json.loads(req.data)
            if body["model"] == "main":
                raise HTTPError(req.full_url, 402, "x", {}, io.BytesIO(
                    b'{"error":{"code":"insufficient_quota","message":"The price of this model has changed."}}'))
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": "tu du phong"}}]}).encode())
        fb = {"name": "OpenAI", "key_name": "openai", "style": "chat", "base": "https://b.example/v1", "key": "k2",
              "model": "backup"}
        prov = {"name": "Cổng", "key_name": "gateway", "style": "chat", "base": "https://a.example/v1", "key": "k1",
                "model": "main", "fallback": fb}
        self.assertEqual(AH.ask(prov, "hi", opener=open_), "tu du phong")
        self.assertEqual((prov["model"], prov["name"]), ("backup", "OpenAI (dự phòng)"))  # nhật ký ghi đúng model dùng
        with self.AIS._connect() as c:
            b = self.AIS.block_status(c)
        self.assertEqual((b["model"], b["fallback"]), ("main", "OpenAI · backup"))
        # model chính gọi lại được: bỏ cảnh báo
        ok = {"name": "Cổng", "style": "chat", "base": "https://a.example/v1", "key": "k1", "model": "main"}
        AH.ask(ok, "hi", opener=lambda req, timeout=0: io.BytesIO(
            json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()))
        with self.AIS._connect() as c:
            self.assertIsNone(self.AIS.block_status(c))

    def test_tries_fallbacks_in_order(self):
        from seo_report import ai_http as AH
        seen = []

        def open_(req, timeout=0):
            m = json.loads(req.data)["model"]
            seen.append(m)
            if m in ("main", "fb1"):
                raise HTTPError(req.full_url, 402, "x", {}, io.BytesIO(b'{"error":{"code":"insufficient_quota"}}'))
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok2"}}]}).encode())
        mk = lambda n, m: {"name": n, "key_name": n, "style": "chat", "base": "https://b.example/v1", "key": "k",
                           "model": m}
        prov = {**mk("gateway", "main"), "fallbacks": [mk("deepseek", "fb1"), mk("openai", "fb2")]}
        self.assertEqual(AH.ask(prov, "hi", opener=open_), "ok2")
        self.assertEqual(seen, ["main", "fb1", "fb2"])
        self.assertEqual((prov["model"], prov["key_name"]), ("fb2", "openai"))

    def test_fallback_list_saved_and_migrated(self):
        with self.AIS._connect() as c:
            self.AIS.ensure(c)
            self.AIS._put(c, "", "fallback", {"provider": "openai", "model": "x"})  # bản cũ: một model
            self.assertEqual(self.AIS.fallbacks(c), [{"provider": "openai", "model": "x"}])
            out = self.AIS.set_fallbacks(c, [{"provider": "deepseek", "model": " a "}, {"provider": "", "model": "b"},
                                             {"provider": "deepseek", "model": "a"}, {"provider": "gateway"}])
            self.assertEqual(out, [{"provider": "deepseek", "model": "a"}, {"provider": "gateway", "model": ""}])
            self.assertEqual(self.AIS.fallbacks(c), out)

    def test_removed_model_counts_as_blocked(self):
        from seo_report import ai_http as AH

        def open_(req, timeout=0):
            raise HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b'{"error":"model not found"}'))
        with self.assertRaises(AH.QuotaError):
            AH.complete("chat", "https://a.example/v1", "k", "gone", "hi", opener=open_)

    def test_no_fallback_raises(self):
        from seo_report import ai_http as AH

        def open_(req, timeout=0):
            raise HTTPError(req.full_url, 402, "x", {}, io.BytesIO(b'{"error":{"code":"insufficient_quota"}}'))
        with self.assertRaises(AH.QuotaError):
            AH.ask({"name": "Cổng", "style": "chat", "base": "https://a.example/v1", "key": "k", "model": "m"}, "hi",
                   opener=open_)
        with self.AIS._connect() as c:
            self.assertIsNone(self.AIS.block_status(c)["fallback"])


class MultiGatewayTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        self.dir = Path(tempfile.mkdtemp())
        self.cfg = SimpleNamespace(client_secret=str(self.dir / "client_secret.json"))

    def tearDown(self):
        from types import SimpleNamespace
        I._save_gateways(self.cfg, [])  # bỏ cổng thêm trong test khỏi danh sách trong bộ nhớ
        I.sync_gateways(SimpleNamespace(client_secret=str(self.dir / "none" / "x.json")))

    def test_add_rename_remove(self):
        k = I.add_gateway(self.cfg, "9router")
        self.assertEqual(k, "gw2")
        self.assertIn("gw2", I.AI_PROVIDERS)
        self.assertEqual(I.BY_KEY["gw2"].name, "9router")
        with self.assertRaises(ValueError):
            I.add_gateway(self.cfg, "9ROUTER")  # trùng tên
        I.rename_gateway(self.cfg, "gateway", "ckey.vn")
        self.assertEqual(I.BY_KEY["gateway"].name, "ckey.vn")
        I.save(self.cfg, "gw2", {"base_url": "http://localhost:20128/v1", "api_style": "chat", "model": "combo",
                                 "api_key": "k"})
        from seo_report import ai_http as AH
        self.assertEqual(AH.settings_for(self.cfg, "gw2")["base"], "http://localhost:20128/v1")
        I.remove_gateway(self.cfg, "gw2")
        self.assertNotIn("gw2", I.AI_PROVIDERS)
        self.assertFalse((self.dir / "ai_gw2.toml").exists())
        with self.assertRaises(ValueError):
            I.remove_gateway(self.cfg, "gateway")

    def test_model_list_from_gateway(self):
        I.save(self.cfg, "gateway", {"base_url": "https://gw.example/v1", "api_style": "chat", "model": "m",
                                     "api_key": "k"})
        I._MODELS_CACHE.clear()
        self.assertEqual(I.gateway_models(self.cfg, "gateway", gateway_opener(["b", "a"])), ["a", "b"])


class UpstreamFallbackTest(FallbackTest):
    def test_upstream_down_switches(self):
        from seo_report import ai_http as AH

        def open_(req, timeout=0):
            if json.loads(req.data)["model"] == "main":
                raise HTTPError(req.full_url, 502, "x", {}, io.BytesIO(b'{"error":"upstream unavailable"}'))
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())
        fb = {"name": "Cổng", "key_name": "gateway", "style": "chat", "base": "https://a.example/v1", "key": "k",
              "model": "fb"}
        prov = {**fb, "model": "main", "fallbacks": [fb]}
        self.assertEqual(AH.ask(prov, "hi", opener=open_), "ok")
        self.assertEqual(prov["model"], "fb")


class RobustAskTest(FallbackTest):
    def _prov(self, chain=()):
        mk = lambda m: {"name": m, "key_name": "gateway", "style": "chat", "base": "https://r.example/v1", "key": "k",
                        "model": m}
        return {**mk("main"), "fallbacks": [mk(m) for m in chain]}

    def test_timeout_switches(self):
        from urllib.error import URLError

        from seo_report import ai_http as AH

        def open_(req, timeout=0):
            if json.loads(req.data)["model"] == "main":
                raise URLError(TimeoutError("timed out"))
            return reply('{"a": 1}')
        prov = self._prov(["fb"])
        self.assertEqual(AH.ask(prov, "hi", expect_json=True, opener=open_), '{"a": 1}')
        self.assertEqual(prov["model"], "fb")

    def test_cut_off_retries_with_more_tokens(self):
        from seo_report import ai_http as AH
        seen = []

        def open_(req, timeout=0):
            body = json.loads(req.data)
            seen.append(body["max_tokens"])
            if body["max_tokens"] < 3000:
                return reply('{"a": ', finish="length")
            return reply('{"a": 1}')
        prov = self._prov()
        self.assertEqual(AH.ask(prov, "hi", expect_json=True, max_tokens=1500, opener=open_), '{"a": 1}')
        self.assertEqual(seen, [1500, 3000])

    def test_bad_format_tries_fallback_then_main_skipped(self):
        from seo_report import ai_http as AH
        seen = []

        def open_(req, timeout=0):
            m = json.loads(req.data)["model"]
            seen.append(m)
            return reply("không phải JSON" if m == "main" else '{"ok": true}')
        prov = self._prov(["fb"])
        AH.ask(prov, "hi", expect_json=True, opener=open_)
        self.assertEqual((seen, prov["model"]), (["main", "fb"], "fb"))
        with self.AIS._connect() as c:  # sai định dạng không phải model bị chặn: không báo chuông
            self.assertIsNone(self.AIS.block_status(c))

    def test_blocked_main_is_skipped_for_a_while(self):
        from seo_report import ai_http as AH
        seen = []

        def open_(req, timeout=0):
            m = json.loads(req.data)["model"]
            seen.append(m)
            if m == "main":
                raise HTTPError(req.full_url, 502, "x", {}, io.BytesIO(b"upstream down"))
            return reply('{"ok": 1}')
        AH.ask(self._prov(["fb"]), "hi", expect_json=True, opener=open_)
        AH.ask(self._prov(["fb"]), "hi", expect_json=True, opener=open_)
        self.assertEqual(seen, ["main", "fb", "fb"])  # lần 2 không gọi lại model chính đang sập

    def test_no_fallback_bad_format_retries_main_once(self):
        from seo_report import ai_http as AH
        n = []

        def open_(req, timeout=0):
            n.append(1)
            return reply("{" if len(n) == 1 else '{"x": 2}')
        self.assertEqual(AH.ask(self._prov(), "hi", expect_json=True, opener=open_), '{"x": 2}')
        self.assertEqual(len(n), 2)


def reply(text, finish="stop"):
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": text}, "finish_reason": finish}]}).encode())
