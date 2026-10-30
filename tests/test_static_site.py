import unittest

from seo_report import static_site as S


class EncryptTest(unittest.TestCase):
    def test_roundtrip_and_wrong_password(self):
        S.ITERATIONS, old = 1000, S.ITERATIONS  # nhanh cho test; bản thật dùng 600.000 vòng
        try:
            blob = S.encrypt({"html": "<b>Click 4.981</b>"}, "mat-khau-dung-123")
            self.assertNotIn("4.981", blob["ct"])
            self.assertEqual(S.decrypt(blob, "mat-khau-dung-123"), {"html": "<b>Click 4.981</b>"})
            with self.assertRaises(Exception):
                S.decrypt(blob, "mat-khau-sai-123")
        finally:
            S.ITERATIONS = old

    def test_fixed_salt_gives_same_key_new_iv(self):
        S.ITERATIONS, old = 1000, S.ITERATIONS
        try:
            a = S.encrypt({"x": 1}, "mat-khau-dung-123", b"s" * 16)
            b = S.encrypt({"x": 2}, "mat-khau-dung-123", b"s" * 16)
            self.assertEqual(a["salt"], b["salt"])  # khóa nhớ trong trình duyệt mở được bản xuất mới
            self.assertNotEqual(a["iv"], b["iv"])
            self.assertEqual(S.decrypt(b, "mat-khau-dung-123"), {"x": 2})
        finally:
            S.ITERATIONS = old

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            S.export(None, "x", "ngan")


if __name__ == "__main__":
    unittest.main()
