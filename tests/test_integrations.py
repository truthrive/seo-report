"""Cài đặt tích hợp: lưu mã vào secrets/, che mã khi hiện, giữ mã cũ khi ô bỏ trống, ghi [drive] vào config.toml."""
import tempfile
import tomllib
import unittest
from pathlib import Path

from seo_report import integrations as I
from seo_report.config import Config


def cfg(tmp: Path) -> Config:
    sec = tmp / "secrets"
    sec.mkdir()
    return Config(site_url="https://x.vn/", db_path=tmp / "seo.db", client_secret=sec / "client_secret.json",
                  token_path=sec / "token.json", dataforseo_secret=sec / "dataforseo.toml",
                  google_ads_secret=sec / "google_ads.toml")


class IntegrationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.c = cfg(self.tmp)

    def test_save_mask_and_keep_old_secret(self):
        self.assertFalse(I.configured(self.c, "dataforseo"))
        I.save(self.c, "dataforseo", I.merge(self.c, "dataforseo", {"login": "a@b.vn", "password": "secret-pass-1234"}))
        self.assertEqual(tomllib.loads(self.c.dataforseo_secret.read_text(encoding="utf-8")),
                         {"login": "a@b.vn", "password": "secret-pass-1234"})
        self.assertEqual(I.view(self.c, "dataforseo"), {"login": "a@b.vn", "password": "••••1234"})
        self.assertTrue(I.configured(self.c, "dataforseo"))
        kept = I.merge(self.c, "dataforseo", {"login": "khac@b.vn", "password": ""})  # bỏ trống = giữ mã cũ
        self.assertEqual(kept["password"], "secret-pass-1234")
        self.assertEqual(I.merge(self.c, "dataforseo", {"login": "x", "password": "••••1234"})["password"],
                         "secret-pass-1234")

    def test_required_fields(self):
        with self.assertRaises(ValueError):
            I.merge(self.c, "google_ads", {"developer_token": "t", "customer_id": ""})

    def test_ai_file_sits_next_to_other_secrets(self):
        I.save(self.c, "ai", {"api_key": "sk-ant-xyz-123456789", "model": "claude-opus-5-5"})
        self.assertTrue((self.tmp / "secrets" / "ai.toml").exists())
        self.assertEqual(I.load(self.c, "ai")["model"], "claude-opus-5-5")

    def test_drive_folder_written_into_config(self):
        p = self.tmp / "config.toml"
        p.write_text('site_url = "x"\n# ghi chú\n\n[rank]\nmonthly_budget_usd = 1\n', encoding="utf-8")
        I.set_drive_folder(p, "abc123")
        self.assertEqual(tomllib.loads(p.read_text(encoding="utf-8"))["drive"]["parent_folder"], "abc123")
        I.set_drive_folder(p, "def456")
        text = p.read_text(encoding="utf-8")
        self.assertEqual(tomllib.loads(text)["drive"]["parent_folder"], "def456")
        self.assertIn("# ghi chú", text)
        self.assertEqual(tomllib.loads(text)["rank"]["monthly_budget_usd"], 1)

    def test_mask(self):
        self.assertEqual(I.mask(""), "")
        self.assertEqual(I.mask("short"), "••••")
        self.assertEqual(I.mask("abcdefghij"), "••••ghij")
