import io
import json
import sqlite3
import unittest
from datetime import date, datetime, timezone

from seo_report import backlink_links as BLL
from seo_report import gbp_reviews as GR
from seo_report import gsc_types as GT
from seo_report import link_audit as LA


class Resp:
    def __init__(self, data, code=200):
        self.data, self.status_code = data, code
        self.content = json.dumps(data).encode()
        self.text = self.content.decode()

    def json(self):
        return self.data


class Session:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=0):
        self.calls.append(("get", url, params))
        if not params.get("pageToken"):
            return Resp({"reviews": [{"reviewId": "r1", "reviewer": {"displayName": "An"}, "starRating": "FIVE",
                                      "comment": "Tốt", "createTime": "2026-10-02T01:00:00Z",
                                      "reviewReply": {"comment": "Cảm ơn", "updateTime": "2026-10-03T01:00:00Z"}}],
                         "averageRating": 4.5, "totalReviewCount": 2, "nextPageToken": "p2"})
        return Resp({"reviews": [{"reviewId": "r2", "reviewer": {"displayName": "Bình"}, "starRating": "TWO",
                                  "comment": "Chờ lâu", "createTime": "2026-11-01T01:00:00Z"}]})

    def put(self, url, json=None, timeout=0):
        self.calls.append(("put", url, json))
        return Resp({"comment": json["comment"]})


class ReviewsTest(unittest.TestCase):
    def test_fetch_stats_reply(self):
        con = sqlite3.connect(":memory:")
        s = Session()
        cl = GR.Client(None, session=s)
        loc = {"name": "locations/9", "account": "accounts/1", "title": "Tâm Đức Q1"}
        self.assertEqual(GR.refresh(con, [loc], cl, log=lambda m: None), 2)
        self.assertIn("accounts/1/locations/9/reviews", s.calls[0][1])
        rs = GR.rows(con, ["locations/9"])
        st = GR.stats(rs)
        self.assertEqual((st["total"], st["avg"], st["unanswered"], st["low_unanswered"]), (2, 3.5, 1, 1))
        cl.reply(loc, "r2", "Xin lỗi anh/chị")
        self.assertEqual(s.calls[-1][0], "put")
        self.assertTrue(s.calls[-1][1].endswith("/reviews/r2/reply"))
        GR.mark_replied(con, "locations/9", "r2", "Xin lỗi anh/chị")
        self.assertEqual(GR.stats(GR.rows(con, ["locations/9"]))["unanswered"], 0)
        p = GR.draft_prompt("Tâm Đức", rs[0])
        self.assertIn("2/5 sao", p)


class Svc:
    def __init__(self, rows):
        self.rows, self.bodies = rows, []

    def searchanalytics(self):
        return self

    def query(self, siteUrl, body):
        self.bodies.append(body)
        return self

    def execute(self):
        return {"rows": self.rows}


class GscTest(unittest.TestCase):
    def test_hourly_utc_and_prev_day(self):
        con = sqlite3.connect(":memory:")
        rows = [{"keys": [f"2026-11-11T{h:02d}:00:00-08:00"], "clicks": h, "impressions": 10 * h} for h in range(24)]
        rows += [{"keys": [f"2026-11-12T{h:02d}:00:00-08:00"], "clicks": 2 * h, "impressions": 0} for h in range(3)]
        svc = Svc(rows)
        self.assertEqual(GT.refresh_hourly(con, "s", svc, date(2026, 11, 12)), 27)
        self.assertEqual(svc.bodies[0]["dataState"], "hourly_all")
        self.assertEqual(GT._utc_hour("2026-11-11T00:00:00-08:00"), "2026-11-11T08:00")
        hs = GT.hourly(con, "s")
        self.assertEqual(hs[-1]["hour"], "2026-11-12 17:00")  # 02:00 PST = 10:00 UTC = 17:00 giờ VN
        self.assertEqual((hs[-1]["clicks"], hs[-1]["prev_clicks"]), (4, 2))
        self.assertFalse(GT.hourly_due(con, "s"))
        self.assertTrue(GT.hourly_due(con, "s", datetime.now(timezone.utc).replace(year=2030)))

    def test_appearance_read(self):
        con = sqlite3.connect(":memory:")
        GT.ensure_tables(con)
        con.executemany("INSERT INTO gsc_appearance VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            ("s", "now", "PRODUCT_SNIPPETS", 50, 1000, 5.1, "2026-10-13", "2026-11-09"),
            ("s", "prev", "PRODUCT_SNIPPETS", 40, 900, 5.5, "2026-09-15", "2026-10-12"),
            ("s", "prev", "FAQ_RICH_RESULT", 3, 30, 4.0, "2026-09-15", "2026-10-12")])
        rows, period = GT.appearance(con, "s")
        self.assertEqual(rows[0]["name"], "Đoạn trích sản phẩm (giá, tình trạng)")
        self.assertEqual((rows[0]["clicks"], rows[0]["prev_clicks"]), (50, 40))
        self.assertEqual(rows[1]["clicks"], 0)  # mất hẳn so với kỳ trước vẫn hiện
        self.assertEqual(period, ("2026-10-13", "2026-11-09"))


class SafeBrowsingTest(unittest.TestCase):
    def test_flag_and_audit(self):
        con = sqlite3.connect(":memory:")
        BLL.ensure_tables(con)
        items = [BLL.slim({"domain_from": "bad.vn", "url_from": "https://bad.vn/a", "url_to": "https://s.vn/"}),
                 BLL.slim({"domain_from": "ok.vn", "url_from": "https://ok.vn/b", "url_to": "https://s.vn/"})]
        con.execute("INSERT INTO backlink_link_runs VALUES ('s', '2026-11-12T00:00:00+00:00', 2, 0, ?)",
                    (json.dumps(items),))
        sent = []

        def opener(req, timeout=0):
            body = json.loads(req.data)
            sent.append(body)
            return io.BytesIO(json.dumps({"matches": [{"threatType": "SOCIAL_ENGINEERING",
                                                       "threat": {"url": "http://bad.vn/"}}]}).encode())
        r = BLL.safe_check(con, "s", "k", opener=opener)
        self.assertEqual(r["flagged"], 1)
        self.assertEqual(len(sent[0]["threatInfo"]["threatEntries"]), 4)
        d = BLL.latest(con, "s")
        got = {c["key"]: c for c in LA.audit(d["items"], None, [], {})}
        self.assertEqual([x["d_from"] for x in got["L_threat"]["rows"]], ["bad.vn"])
        self.assertIn("domain:bad.vn", LA.disavow(d["items"]))
        self.assertNotIn("L_threat", {c["key"] for c in LA.audit(items, None, [], {})})  # chưa kiểm tra: không báo
