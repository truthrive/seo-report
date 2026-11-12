import io
import json
import os
import tempfile
import unittest

from seo_report import ai_http as AH
from seo_report import ai_settings as AIS
from seo_report import ai_usage as AU
from seo_report import db


class AiUsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = AIS._APP.get("path")
        AIS._APP["path"] = os.path.join(self.tmp, "app.db")

    def tearDown(self):
        AIS._APP["path"] = self.old

    def test_tokens_by_style(self):
        self.assertEqual(AU.tokens("chat", {"usage": {"prompt_tokens": 10, "completion_tokens": 3}}), (10, 3))
        self.assertEqual(AU.tokens("messages", {"usage": {"input_tokens": 7, "output_tokens": 2}}), (7, 2))
        self.assertEqual(AU.tokens("gemini", {"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1}}),
                         (5, 1))
        self.assertEqual(AU.tokens("chat", {}), (0, 0))

    def test_ask_logs_usage_and_estimate(self):
        def opener(req, timeout=0):
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                                          "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}).encode())
        prov = {"name": "Cổng", "key_name": "gateway", "style": "chat", "base": "https://a.example/v1", "key": "k",
                "model": "m1", "task": "brief", "site": "https://s.vn/"}
        self.assertEqual(AH.ask(prov, "hi", opener=opener), "ok")
        con = db.connect(AIS._APP["path"])
        rows = AU.by_task(con, __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                          .strftime("%Y-%m"))
        self.assertEqual((rows[0]["task"], rows[0]["calls"], rows[0]["in_tok"], rows[0]["out_tok"]),
                         ("brief", 1, 1000, 500))
        money, unit = AU.estimate(rows[0]["models"], {("gateway", "m1"): {"input": 1200, "output": 4800,
                                                                         "unit": "VND"}})
        self.assertAlmostEqual(money, 1000 / 1e6 * 1200 + 500 / 1e6 * 4800)
        self.assertEqual(unit, "VND")
        self.assertEqual(AU.estimate(rows[0]["models"], {}), (None, ""))
