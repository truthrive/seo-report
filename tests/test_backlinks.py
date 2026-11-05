import sqlite3
import unittest
from datetime import date
from types import SimpleNamespace

from seo_report import backlinks as BL
from seo_report import rank as R

SITE = "sc-domain:example.vn"


class FakeClient:
    """DataForSEO giả: không gọi mạng, đếm số lần gọi."""

    def __init__(self, ref=120, backlinks=900):
        self.calls = []
        self.ref, self.backlinks = ref, backlinks

    def summary(self, target):
        self.calls.append(("summary", target))
        return {"backlinks": self.backlinks, "referring_domains": self.ref, "referring_main_domains": 110,
                "referring_domains_nofollow": 20, "rank": 182, "backlinks_spam_score": 7,
                "broken_backlinks": 3}, 0.02

    def history(self, target, date_from):
        self.calls.append(("history", date_from))
        return [{"date": "2026-09-01 00:00:00 +00:00", "backlinks": 800, "referring_domains": 100,
                 "new_backlinks": 40, "lost_backlinks": 10, "new_referring_domains": 5, "lost_referring_domains": 1,
                 "rank": 170},
                {"date": "2026-10-01 00:00:00 +00:00", "backlinks": 850, "referring_domains": 112,
                 "new_backlinks": 60, "lost_backlinks": 12, "new_referring_domains": 14, "lost_referring_domains": 2,
                 "rank": 178}], 0.03


def cfg(budget=5.0, paused=False):
    return SimpleNamespace(rank=SimpleNamespace(paused=paused, monthly_budget_usd=budget),
                           dataforseo_secret="secrets/none.toml")


class BacklinksTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        R.ensure_tables(self.con)

    def test_first_fetch_saves_summary_history_and_cost(self):
        fake = FakeClient()
        self.assertTrue(BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 4), client=fake, log=lambda m: None))
        self.assertEqual([c[0] for c in fake.calls], ["summary", "history"])
        self.assertEqual(fake.calls[0][1], "example.vn")  # tên miền, không kèm sc-domain:
        bl = BL.latest(self.con, SITE)
        self.assertEqual((bl["now"]["referring_domains"], bl["now"]["backlinks"], bl["now"]["rank"]), (120, 900, 182))
        self.assertIsNone(bl["prev"])
        self.assertEqual([h["month"] for h in bl["history"]], ["2026-09", "2026-10"])
        # chi phí tính chung ngân sách DataForSEO của website (cùng check rank, volume)
        self.assertAlmostEqual(R.spent_this_month(self.con, date(2026, 11, 4)), 0.05)
        self.assertAlmostEqual(R.cost_by_month(self.con, ["2026-11"])["2026-11"]["backlinks"], 0.05)

    def test_weekly_refresh_and_compare_with_previous(self):
        BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 4), client=FakeClient(), log=lambda m: None)
        fake = FakeClient(ref=128)
        # trong 7 ngày: không gọi lại (không tốn tiền)
        self.assertFalse(BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 8), client=fake, log=lambda m: None))
        self.assertEqual(fake.calls, [])
        # đủ 7 ngày: lấy số tổng; lịch sử tháng trước đã có nên không hỏi lại
        self.assertTrue(BL.refresh(self.con, SITE, cfg(), today=date(2026, 11, 11), client=fake, log=lambda m: None))
        self.assertEqual([c[0] for c in fake.calls], ["summary"])
        bl = BL.latest(self.con, SITE)
        self.assertEqual((bl["now"]["referring_domains"], bl["prev"]["referring_domains"]), (128, 120))

    def test_paused_or_over_budget_does_not_call(self):
        fake = FakeClient()
        self.assertFalse(BL.refresh(self.con, SITE, cfg(paused=True), today=date(2026, 11, 4), client=fake,
                                    force=True, log=lambda m: None))
        with self.assertRaises(RuntimeError):
            BL.refresh(self.con, SITE, cfg(budget=0.01), today=date(2026, 11, 4), client=fake, force=True,
                       log=lambda m: None)
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
