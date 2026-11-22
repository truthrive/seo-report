"""AI viết đoạn còn thiếu cho trang sắp lên top (SEO Opportunities › Striking Distance)."""
import io
import json
import unittest
from datetime import timedelta

from seo_report import ai_http as AH
from seo_report import ai_page_gap as PG
from seo_report import db
from seo_report import opportunities as O
from tests.test_opportunities import END, Gsc

PROV = {"name": "Cổng thử", "key_name": "gateway", "style": "chat", "base": "https://gw.example/v1", "key": "k",
        "model": "m"}
HTML = """<html><head><title>Cách pha cà phê pour over | X</title>
<meta name="description" content="Hướng dẫn pha pour over tại nhà."></head><body>
<header><nav><a href="/">Trang chủ</a> Menu sản phẩm</nav></header>
<h1>Cách pha cà phê pour over</h1>
<p>Pour over là cách pha thủ công, rót nước nóng chậm qua lớp cà phê xay trong phễu lọc giấy.</p>
<h2>Dụng cụ cần có</h2><ul><li>Phễu V60</li><li>Ấm cổ ngỗng</li><li>Cân điện tử</li></ul>
<h2>Các bước pha</h2><h3>Ủ cà phê</h3><p>Rót một ít nước, chờ khoảng 30 giây cho cà phê nở rồi rót tiếp theo vòng.</p>
<script>var tracking = "không được lẫn vào nội dung";</script>
<aside>Bài viết liên quan quảng cáo</aside>
<footer>Bản quyền công ty X, địa chỉ chân trang</footer></body></html>"""
ROW = {"query": "tỷ lệ pha pour over", "url": "https://x.vn/pour-over/", "url_id": 7, "position": 6.4,
       "impressions": 900, "clicks": 12}
GOOD = {"diagnosis": "Trang chưa nói tỷ lệ cà phê và nước.", "heading": "Tỷ lệ cà phê và nước khi pha pour over",
        "placement": "sau mục Dụng cụ cần có", "section": "Tỷ lệ phổ biến là 1:15 đến 1:17. " * 12,
        "faq": {"q": "Pha 1 ly cần bao nhiêu gram?", "a": "Khoảng 15–20 g cho 250 ml nước."},
        "title": "", "anchors": ["tỷ lệ pha pour over", "công thức pour over"]}


def reply(text):
    def open_(req, timeout=0):
        open_.body = json.loads(req.data)
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": text}}]}).encode())
    return open_


def fetcher(pages: dict):
    """fetch giả: url → kết quả như site_audit.fetch."""
    def fetch(url, timeout=0):
        fetch.seen.append(url)
        return pages[url]
    fetch.seen = []
    return fetch


class OutlineTest(unittest.TestCase):
    def test_outline_keeps_content_drops_chrome(self):
        o = PG.outline(HTML)
        self.assertEqual(o["title"], "Cách pha cà phê pour over | X")
        self.assertEqual(o["desc"], "Hướng dẫn pha pour over tại nhà.")
        self.assertEqual(o["h1"], ["Cách pha cà phê pour over"])
        self.assertEqual(o["headings"], [(2, "Dụng cụ cần có"), (2, "Các bước pha"), (3, "Ủ cà phê")])
        self.assertIn("Ấm cổ ngỗng", o["text"])
        for chrome in ("Menu sản phẩm", "tracking", "quảng cáo", "chân trang"):
            self.assertNotIn(chrome, o["text"])

    def test_text_capped(self):
        o = PG.outline("<p>" + "chữ " * 5000 + "</p>")
        self.assertLessEqual(len(o["text"]), PG.MAX_TEXT)


class ReadPageTest(unittest.TestCase):
    def test_follows_redirect(self):
        f = fetcher({"https://x.vn/a": {"status": 301, "final_url": "/b/", "html": ""},
                     "https://x.vn/b/": {"status": 200, "final_url": None, "html": HTML}})
        p = PG.read_page("https://x.vn/a", fetch=f)
        self.assertTrue(p["ok"])
        self.assertEqual(p["url"], "https://x.vn/b/")
        self.assertEqual(f.seen, ["https://x.vn/a", "https://x.vn/b/"])

    def test_blocked_error_and_js_only(self):
        p = PG.read_page("https://x.vn/a", fetch=fetcher({"https://x.vn/a": {"status": 403, "html": "",
                                                                             "blocked": True}}))
        self.assertFalse(p["ok"])
        self.assertIn("tường lửa", p["error"])
        p = PG.read_page("https://x.vn/a", fetch=fetcher({"https://x.vn/a": {"status": 404, "html": ""}}))
        self.assertEqual(p["error"], "trang trả mã 404")
        p = PG.read_page("https://x.vn/a", fetch=fetcher({"https://x.vn/a": {
            "status": 200, "html": "<html><body><div id=app></div><script>render()</script></body></html>"}}))
        self.assertFalse(p["ok"])
        self.assertIn("JavaScript", p["error"])

    def test_redirect_loop_stops(self):
        f = fetcher({"https://x.vn/a": {"status": 302, "final_url": "https://x.vn/a", "html": ""}})
        p = PG.read_page("https://x.vn/a", fetch=f)
        self.assertFalse(p["ok"])
        self.assertEqual(len(f.seen), PG.MAX_HOPS + 1)


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.page = {**PG.outline(HTML), "ok": True, "url": ROW["url"], "status": 200, "error": None}
        self.queries = [{"query": "tỷ lệ pha pour over", "position": 6.4, "impressions": 900},
                        {"query": "pour over là gì", "position": 3.1, "impressions": 400}]

    def test_prompt_has_page_and_other_queries(self):
        op = reply("```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```")
        d, _ = PG.write(None, ROW, self.queries, self.page, PROV, op)
        user_msg = op.body["messages"][1]["content"]
        self.assertIn("tỷ lệ pha pour over", user_msg)
        self.assertIn("H2: Dụng cụ cần có", user_msg)
        self.assertIn("  H3: Ủ cà phê", user_msg)
        self.assertIn("pour over là gì (vị trí 3,1", user_msg)
        self.assertNotIn("- tỷ lệ pha pour over (vị trí", user_msg)  # từ khóa chính không lặp trong danh sách khác
        self.assertEqual(d["heading"], GOOD["heading"])
        self.assertEqual(d["faq"]["q"], GOOD["faq"]["q"])
        self.assertEqual(d["anchors"], GOOD["anchors"])
        self.assertTrue(d["page_read"])
        self.assertEqual(d["keyword"], ROW["query"])
        self.assertEqual(d["page_title"], "Cách pha cà phê pour over | X")

    def test_page_not_read_is_flagged(self):
        page = {"ok": False, "error": "tường lửa của website chặn tool đọc trang"}
        op = reply(json.dumps(GOOD, ensure_ascii=False))
        d, _ = PG.write(None, ROW, [], page, PROV, op)
        self.assertIn("KHÔNG đọc được nội dung trang", op.body["messages"][1]["content"])
        self.assertFalse(d["page_read"])
        self.assertIn("tường lửa", d["page_error"])

    def test_bad_replies(self):
        for bad in ("xin lỗi, tôi không làm được", '{"heading": "x", "section": ""}', '{"section": "abc"}'):
            with self.assertRaises(AH.AIError):
                PG.write(None, ROW, [], self.page, PROV, reply(bad))

    def test_parse_cleans_shapes(self):
        d = PG.parse(json.dumps({"heading": " H2 ", "section": "Đoạn", "faq": "không phải dict",
                                 "anchors": "không phải list", "title": None}))
        self.assertEqual(d["heading"], "H2")
        self.assertIsNone(d["faq"])
        self.assertEqual(d["anchors"], [])
        self.assertEqual(d["title"], "")

    def test_as_text_and_ref(self):
        d = {**GOOD, "keyword": ROW["query"], "url": ROW["url"], "title": "Tỷ lệ pha pour over chuẩn"}
        t = PG.as_text(d)
        self.assertIn("## Tỷ lệ cà phê và nước khi pha pour over", t)
        self.assertIn("Đặt ở: sau mục Dụng cụ cần có", t)
        self.assertIn("Tiêu đề SEO gợi ý: Tỷ lệ pha pour over chuẩn", t)
        self.assertEqual(PG.ref_of(7, "Tỷ Lệ Pha"), PG.ref_of(7, "tỷ lệ pha"))


class PageQueriesTest(unittest.TestCase):
    def test_top_queries_of_page(self):
        con = db.connect(":memory:")
        g = Gsc(con)
        for i in range(5):
            d = END - timedelta(days=i)
            g.day(d, "/pour-over/", 1, 100, 6.0, "tỷ lệ pha pour over")
            g.day(d, "/pour-over/", 0, 30, 12.0, "phễu v60")
            g.day(d, "/khac/", 5, 500, 2.0, "trang khác")
        uid = g.urls["/pour-over/"][1]
        qs = O.page_queries(con, uid, END)
        self.assertEqual([q["query"] for q in qs], ["tỷ lệ pha pour over", "phễu v60"])
        self.assertEqual(qs[0]["impressions"], 500)
        con.close()


if __name__ == "__main__":
    unittest.main()
