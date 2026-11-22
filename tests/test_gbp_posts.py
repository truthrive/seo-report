import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from seo_report import gbp as G
from seo_report import gbp_posts as GP

LOCS = [{"name": "locations/1", "account": "accounts/9", "title": "Tâm Đức - Tân Bình"},
        {"name": "locations/2", "account": "accounts/9", "title": "Tâm Đức - Bình Thạnh"}]


class FakeClient:
    def __init__(self, fail=()):
        self.sent, self.fail = [], set(fail)

    def create(self, loc, body):
        if loc["name"] in self.fail:
            raise RuntimeError("400 bad")
        self.sent.append((loc["name"], body))
        return {"name": f"{loc['account']}/{loc['name']}/localPosts/{len(self.sent)}", "state": "LIVE",
                "searchUrl": "https://g.page/x"}

    def list(self, loc):
        return [{"name": f"{loc['account']}/{loc['name']}/localPosts/1", "state": "REJECTED"}]


class GbpPostsTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.base = {"locations": ["locations/1", "locations/2"], "kind": "STANDARD",
                     "summary": "Đo mắt miễn phí cả tuần này.", "cta": "LEARN_MORE", "cta_url": "https://x.vn/"}

    def test_validate(self):
        GP.validate(self.base)
        with self.assertRaises(ValueError):
            GP.validate({**self.base, "locations": []})
        with self.assertRaises(ValueError):
            GP.validate({**self.base, "summary": "x" * 1501})
        with self.assertRaises(ValueError):
            GP.validate({**self.base, "kind": "EVENT"})  # sự kiện cần tiêu đề + ngày
        with self.assertRaises(ValueError):
            GP.validate({**self.base, "cta_url": "x.vn"})
        with self.assertRaises(ValueError):  # ảnh cần link https công khai
            GP.validate({**self.base, "image": "a.jpg", "image_url": "http://localhost:8080/gbp-media/a.jpg"})

    def test_body_offer_and_event(self):
        b = GP.body({**self.base, "kind": "OFFER", "title": "Giảm 20%", "start": "2026-11-20", "end": "2026-11-30",
                     "coupon": "TD20", "image_url": "https://r.vn/gbp-media/a.jpg"})
        self.assertEqual(b["topicType"], "OFFER")
        self.assertEqual(b["event"]["schedule"]["endDate"], {"year": 2026, "month": 11, "day": 30})
        self.assertEqual(b["offer"], {"couponCode": "TD20"})
        self.assertNotIn("callToAction", b)  # ưu đãi dùng nút "Nhận ưu đãi" của Google
        self.assertEqual(b["media"][0]["sourceUrl"], "https://r.vn/gbp-media/a.jpg")
        call = GP.body({**self.base, "cta": "CALL"})
        self.assertEqual(call["callToAction"], {"actionType": "CALL"})

    def test_publish_partial_then_retry(self):
        pid = GP.save(self.con, self.base, "an")
        r = GP.publish(self.con, pid, LOCS, FakeClient(fail={"locations/2"}), str)
        self.assertEqual((r["status"], r["ok"]), ("partial", 1))
        c2 = FakeClient()
        r = GP.publish(self.con, pid, LOCS, c2, str)  # chỉ đăng lại chi nhánh lỗi
        self.assertEqual(r["status"], "posted")
        self.assertEqual([n for n, _ in c2.sent], ["locations/2"])
        with self.assertRaises(ValueError):
            GP.save(self.con, self.base, "an", pid)  # đã đăng: không sửa được
        GP.sync_states(self.con, LOCS, FakeClient())
        p = GP.get(self.con, pid)
        self.assertEqual(p["results"]["locations/1"]["state"], "REJECTED")

    def test_schedule_due(self):
        with self.assertRaises(ValueError):
            GP.save(self.con, {**self.base, "summary": ""}, "an", status="scheduled")
        soon = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
        pid = GP.save(self.con, {**self.base, "scheduled_at": soon}, "an", status="scheduled")
        self.assertEqual(GP.due(self.con), [])
        self.assertEqual(GP.due(self.con, datetime.now(timezone.utc) + timedelta(hours=2)), [pid])
        draft = GP.save(self.con, {**self.base, "scheduled_at": soon}, "an")
        self.assertIsNone(GP.get(self.con, draft)["scheduled_at"])  # nháp không có giờ đăng

    def test_image_save_and_serve(self):
        d = Path(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            GP.save_image(d, b"GIF89a" + b"0" * 20000, "image/gif")
        with self.assertRaises(ValueError):
            GP.save_image(d, b"\xff\xd8\xff" + b"0" * 100, "image/jpeg")  # quá nhỏ
        with self.assertRaises(ValueError):
            GP.save_image(d, b"\xff\xd8\xff" + b"0" * 20000, "image/jpeg")  # đầu JPG nhưng không phải ảnh
        name = GP.save_image(d, _noisy_image("JPEG"), "image/jpeg")
        self.assertTrue(name.endswith(".jpg"))
        self.assertIsNotNone(GP.image_file(d, name))
        self.assertIsNone(GP.image_file(d, "../app.db"))
        self.assertIsNone(GP.image_file(d, "abc.jpg"))  # tên ngắn: không phải tên tool tạo

    def test_image_metadata_removed(self):
        """Ảnh phục vụ công khai không còn GPS / máy chụp / phần mềm (EXIF) hay chú thích PNG."""
        from PIL import Image
        d = Path(tempfile.mkdtemp())
        name = GP.save_image(d, _noisy_image("JPEG", exif=True), "image/jpeg")
        raw = GP.image_file(d, name).read_bytes()
        self.assertNotIn(b"Exif", raw)
        self.assertNotIn(b"Pixel 9 Pro", raw)
        with Image.open(GP.image_file(d, name)) as im:
            self.assertEqual(len(im.getexif()), 0)
            self.assertEqual(im.size, (300, 400))  # Orientation=6: ảnh được xoay thật trước khi bỏ EXIF
        name = GP.save_image(d, _noisy_image("PNG", exif=True), "")  # không có content type: nhận diện từ nội dung
        self.assertTrue(name.endswith(".png"))
        raw = GP.image_file(d, name).read_bytes()
        self.assertNotIn(b"c2pa-made-with", raw)
        self.assertNotIn(b"eXIf", raw)


def _noisy_image(fmt: str, exif: bool = False) -> bytes:
    """Ảnh 400x300 nhiễu ngẫu nhiên (nén không nhỏ đi dưới 10 KB), có thể kèm EXIF GPS + máy chụp + chiều xoay."""
    import io
    import os

    from PIL import Image, PngImagePlugin
    img = Image.frombytes("RGB", (400, 300), os.urandom(400 * 300 * 3))
    kw = {}
    if exif:
        ex = Image.Exif()
        ex[0x0110] = "Pixel 9 Pro"  # Model
        ex[0x0131] = "Photoshop"  # Software
        ex[0x0112] = 6  # Orientation: xoay 90°
        ex[0x8825] = {1: "N", 2: (10.0, 48.0, 0.0)}  # GPSInfo
        kw["exif"] = ex
        if fmt == "PNG":
            info = PngImagePlugin.PngInfo()
            info.add_text("c2pa-made-with", "AI image model")
            kw["pnginfo"] = info
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()

    def test_import_from_google(self):
        class G2:
            def list(self, loc):
                base = {"summary": "Khai trương chi nhánh mới", "topicType": "STANDARD", "state": "LIVE",
                        "createTime": "2026-11-10T03:00:00Z", "searchUrl": "https://g.page/p",
                        "media": [{"googleUrl": "https://lh3.googleusercontent.com/x"}]}
                out = [{**base, "name": f"{loc['account']}/{loc['name']}/localPosts/9"}]
                if loc["name"] == "locations/1":  # bài tool đã đăng: chỉ cập nhật trạng thái
                    out.append({"name": "accounts/9/locations/1/localPosts/1", "state": "REJECTED",
                                "summary": "x", "topicType": "STANDARD", "createTime": "2026-11-12T00:00:00Z"})
                return out
        pid = GP.save(self.con, {**self.base, "locations": ["locations/1"]}, "an")
        GP.publish(self.con, pid, LOCS, FakeClient(), str)  # tạo bài accounts/9/locations/1/localPosts/1
        r = GP.import_from_google(self.con, LOCS, G2())
        self.assertEqual(r, {"new": 1, "updated": 1})  # cùng nội dung ở 2 chi nhánh: gộp một bài
        imp = [p for p in GP.all_posts(self.con) if p["source"] == "google"]
        self.assertEqual(len(imp), 1)
        self.assertEqual(sorted(imp[0]["locations"]), ["locations/1", "locations/2"])
        self.assertEqual(imp[0]["image_url"], "https://lh3.googleusercontent.com/x")
        self.assertEqual(GP.get(self.con, pid)["results"]["locations/1"]["state"], "REJECTED")
        self.assertEqual(GP.import_from_google(self.con, LOCS, G2()), {"new": 0, "updated": 0})  # không nhập trùng

    def test_explain_names_v4_api(self):
        e = RuntimeError("403 SERVICE_DISABLED Google My Business API has not been used in project 851747918142 "
                         "mybusiness.googleapis.com")
        self.assertIn("Google My Business API", G.explain(e))
        self.assertIn("851747918142", G.explain(e))


if __name__ == "__main__":
    unittest.main()
