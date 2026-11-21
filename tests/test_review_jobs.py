import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from seo_report import gbp_reviews as GR
from seo_report import web_local as WL


async def _io(fn, *a, **kw):
    return fn(*a, **kw)


def job(kind, n):
    return {"id": 1, "kind": kind, "total": n, "done": 0, "ok": 0, "errors": 0, "running": True, "stop": False,
            "results": {}, "status": {}, "current": "", "by": "an", "finished": False}


class ReviewJobTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = SimpleNamespace(db_path=Path(os.path.join(self.dir, "p.db")), site_url="https://x.vn/")
        con = sqlite3.connect(self.cfg.db_path)
        GR.ensure_tables(con)
        for i in range(3):
            con.execute("INSERT INTO gbp_reviews VALUES ('L', ?, 'A', 2, 'tệ', '2026-11-01', 'x', NULL, NULL, 'x')",
                        (str(i),))
        con.commit()
        con.close()
        self.revs = [{"location": "L", "id": str(i), "author": f"Khách {i}", "rating": 2, "comment": "tệ"}
                     for i in range(3)]

    def run_job(self, j, its, **kw):
        with mock.patch("nicegui.run.io_bound", _io), mock.patch.object(WL, "_charge", return_value=None), \
                mock.patch("seo_report.ai_writer.provider", return_value={}):
            asyncio.run(WL._run_job(j, its, self.cfg, "an", {"L": "Tâm Đức - Gò Vấp"}, {}, kw.get("locs", [])))

    def test_draft_job_saves_drafts_and_reports(self):
        calls = []

        def fake_draft(prov, biz, r, note, v, br):
            calls.append(r["id"])
            if r["id"] == "1":
                raise RuntimeError("model lỗi")
            return f"Xin lỗi {r['author']}"
        j = job("draft", 3)
        with mock.patch.object(GR, "draft", fake_draft):
            self.run_job(j, self.revs)
        self.assertEqual((j["done"], j["ok"], j["errors"], j["running"], j["finished"]), (3, 2, 1, False, True))
        self.assertEqual(j["results"][("L", "0")], "Xin lỗi Khách 0")
        self.assertTrue(j["status"][("L", "1")].startswith("✗"))
        con = sqlite3.connect(self.cfg.db_path)
        self.assertEqual(len(GR.drafts(con)), 2)  # nháp lưu ngay (đóng hộp mở lại vẫn còn)

    def test_stop_after_current(self):
        j = job("draft", 3)

        def fake_draft(prov, biz, r, note, v, br):
            j["stop"] = True  # người dùng bấm Dừng trong lúc câu đầu đang viết
            return "ok"
        with mock.patch.object(GR, "draft", fake_draft):
            self.run_job(j, self.revs)
        self.assertEqual((j["done"], j.get("stopped")), (1, True))

    def test_send_job(self):
        sent = []

        class C:
            def reply(self, loc, rid, text):
                if rid == "2":
                    raise RuntimeError("403 PERMISSION_DENIED")
                sent.append((rid, text))
        its = [{**r, "text": f"Trả lời {r['id']}"} for r in self.revs]
        j = job("send", 3)
        with mock.patch.object(GR, "Client", lambda creds: C()), \
                mock.patch("seo_report.auth.get_credentials", return_value=None):
            self.run_job(j, its, locs=[{"name": "L", "account": "accounts/1", "title": "Gò Vấp"}])
        self.assertEqual((j["ok"], j["errors"]), (2, 1))
        self.assertEqual(sent[0], ("0", "Trả lời 0"))
        con = sqlite3.connect(self.cfg.db_path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM gbp_reviews WHERE reply IS NOT NULL").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
