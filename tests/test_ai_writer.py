import io
import json
import sqlite3
import unittest

from seo_report import ai_http as AH
from seo_report import ai_writer as AW

PROV = {"name": "Cổng thử", "key_name": "gateway", "style": "chat", "base": "https://gw.example/v1", "key": "k",
        "model": "m"}


def reply(text):
    def open_(req, timeout=0):
        open_.body = json.loads(req.data)
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": text}}]}).encode())
    return open_


class AiWriterTest(unittest.TestCase):
    def test_write_aio_parses_json_in_code_fence(self):
        out = '```json\n{"answer": "Kính râm chính hãng giá từ [điền giá].", "headings": ["Giá bao nhiêu?"], ' \
              '"missing": ["Bảng giá"], "faq": [{"q": "Có bảo hành?", "a": "Có."}]}\n```'
        op = reply(out)
        d, prov = AW.write_aio(None, "kính râm", "Tâm Đức", "https://a.vn/kinh-ram/", "AI nói…",
                               [{"domain": "b.vn", "title": "Kính râm"}], "Top 3 nhưng AI không trích", PROV, op)
        self.assertEqual(d["headings"], ["Giá bao nhiêu?"])
        self.assertEqual(d["faq"][0]["q"], "Có bảo hành?")
        msgs = op.body["messages"]
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("kính râm", msgs[1]["content"])
        self.assertIn("b.vn", msgs[1]["content"])

    def test_bad_reply_raises(self):
        with self.assertRaises(AH.AIError):
            AW.write_aio(None, "x", "", "", "", [], "", PROV, reply("xin lỗi"))
        with self.assertRaises(AH.AIError):
            AW.write_aio(None, "x", "", "", "", [], "", PROV, reply('{"answer": ""}'))

    def test_save_and_latest(self):
        con = sqlite3.connect(":memory:")
        AW.save(con, "a.vn", "aio_answer", "7", {"answer": "v1"}, PROV, "me")
        AW.save(con, "a.vn", "aio_answer", "7", {"answer": "v2"}, PROV, "me")
        d = AW.latest(con, "a.vn", "aio_answer", "7")
        self.assertEqual((d["answer"], d["provider"], d["model"]), ("v2", "Cổng thử", "m"))
        self.assertIsNone(AW.latest(con, "a.vn", "aio_answer", "8"))


class ReportNoteTest(unittest.TestCase):
    def test_write_report_uses_only_given_facts(self):
        from unittest import mock
        rep = mock.Mock(kind="month")
        with mock.patch.object(AW, "report_facts", return_value="Click Google: 5.049 (+1,4%)"):
            op = reply('{"note": "- Tháng này tốt: click +1,4%.", "plan": "- Tối ưu 5 trang giảm click."}')
            d, _ = AW.write_report(None, rep, PROV, op)
        self.assertTrue(d["note"].startswith("- Tháng này tốt"))
        self.assertIn("Tối ưu", d["plan"])
        user_msg = op.body["messages"][1]["content"]
        self.assertIn("5.049", user_msg)
        self.assertIn('"plan"', user_msg)
        with mock.patch.object(AW, "report_facts", return_value="x"):
            with self.assertRaises(AH.AIError):
                AW.write_report(None, rep, PROV, reply('{"note": ""}'))


if __name__ == "__main__":
    unittest.main()
