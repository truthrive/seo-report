"""Chấm trạng thái: online khi có trang mở và có thao tác, vắng mặt khi không thao tác quá 5 phút, offline khi đóng."""
import time
import unittest

from seo_report import presence as PR


class PresenceTest(unittest.TestCase):
    def setUp(self):
        PR.reset()

    def test_lifecycle(self):
        self.assertEqual(PR.status("a@x.vn")[0], PR.OFFLINE)
        PR.connect("A@x.vn", "c1")  # không phân biệt hoa thường
        self.assertEqual(PR.status("a@x.vn")[0], PR.AVAILABLE)
        later = time.time() + PR.IDLE_SECONDS + 60
        self.assertEqual(PR.status("a@x.vn", later)[0], PR.AWAY)
        self.assertTrue(PR.describe("a@x.vn", now=later)[1].startswith("Vắng mặt · không thao tác"))
        PR.connect("a@x.vn", "c2")  # mở thêm tab
        self.assertFalse(PR.leave("a@x.vn", "c1"))  # còn tab kia: chưa offline
        self.assertTrue(PR.leave("a@x.vn", "c2"))
        st, text = PR.describe("a@x.vn")
        self.assertEqual(st, PR.OFFLINE)
        self.assertIn("lần cuối", text)

    def test_activity_keeps_available(self):
        PR.connect("b@x.vn", "c1")
        PR.active("b@x.vn")
        self.assertEqual(PR.status("b@x.vn", time.time() + PR.IDLE_SECONDS - 5)[0], PR.AVAILABLE)

    def test_offline_text_from_saved_last_seen(self):
        self.assertEqual(PR.describe("c@x.vn", "2026-11-01T10:00:00+00:00")[1][:20], "Offline · lần cuối 0")
        self.assertEqual(PR.describe("c@x.vn"), (PR.OFFLINE, "Offline"))
