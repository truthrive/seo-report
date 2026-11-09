import unittest

from seo_report import dash_widgets as W


class ChannelItemsTest(unittest.TestCase):
    def test_top_channels_and_other_with_fixed_colors(self):
        items, colors = W.channel_items({"Organic Search": 500, "Direct": 300, "Referral": 50, "Paid Search": 40,
                                         "Organic Social": 30, "Email": 20, "Display": 10, "": 5, "Cross-network": 0})
        self.assertEqual([n for n, _ in items], ["Organic Search", "Direct", "Referral", "Paid Search",
                                                 "Organic Social", "Khác"])
        self.assertEqual(items[-1][1], 35)                       # Email 20 + Display 10 + (trống) 5
        self.assertEqual(sum(v for _, v in items), 955)          # không mất phiên nào
        self.assertEqual(colors[0], W.CHANNEL_COLORS["Organic Search"])  # màu theo kênh, không theo thứ tự
        self.assertEqual(len(colors), len(items))


class LighthouseAvgTest(unittest.TestCase):
    def test_average_skips_missing(self):
        out = W.lighthouse_avg([{"perf": 40, "seo": 90, "a11y": None, "bp": 80, "fetched_at": "2026-11-01T01:00"},
                                {"perf": 60, "seo": 100, "a11y": 70, "bp": None, "fetched_at": "2026-11-03T01:00"},
                                {"perf": None, "seo": None, "a11y": None, "bp": None, "fetched_at": "2026-11-04"}])
        self.assertEqual((out["perf"], out["seo"], out["a11y"], out["bp"]), (50, 95, 70, 80))
        self.assertEqual((out["n"], out["at"]), (2, "2026-11-03T01:00"))  # trang lỗi (không số) không tính

    def test_empty(self):
        self.assertEqual(W.lighthouse_avg([])["n"], 0)


if __name__ == "__main__":
    unittest.main()
