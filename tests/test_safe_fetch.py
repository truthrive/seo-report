"""Tải URL ngoài chỉ tới địa chỉ công khai, đọc có trần; robots.txt khớp tuyến tính; nhóm URL chỉ nhận trang của website."""
import gzip
import socket
import sqlite3
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock
from urllib.request import Request

from seo_report import indexing as IX
from seo_report import safe_fetch as SF
from seo_report import site_checks as SC
from seo_report import urls as U


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


class PublicIpTest(unittest.TestCase):
    def test_public_and_private_ranges(self):
        for ok in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"):
            self.assertTrue(SF.is_public_ip(ok), ok)
        for bad in ("127.0.0.1", "10.0.0.5", "172.16.1.1", "192.168.1.10", "169.254.169.254", "0.0.0.0", "::1", "fe80::1",
                    "fc00::1", "224.0.0.1", "::ffff:127.0.0.1", "100.64.0.1", "not-an-ip"):
            self.assertFalse(SF.is_public_ip(bad), bad)

    def test_mixed_answer_is_rejected_and_dns_failure_fails_closed(self):
        def fake(host, port, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
        with mock.patch("socket.getaddrinfo", fake), self.assertRaises(SF.NotPublic):
            SF.resolve_public("evil.example", 80)
        with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror), self.assertRaises(SF.NotPublic):
            SF.resolve_public("nonexistent.example", 80)

    def test_only_public_answers_are_returned(self):
        def fake(host, port, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]
        with mock.patch("socket.getaddrinfo", fake):
            self.assertEqual(SF.resolve_public("ok.example", 443)[0][3], ("8.8.8.8", 443))


class LoopbackBlockedTest(unittest.TestCase):
    def setUp(self):
        self.srv = HTTPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_loopback_server_is_not_reachable_through_the_opener(self):
        for op in (SF.OPEN, SF.OPEN_NO_REDIRECT):
            with self.assertRaises(OSError):  # URLError và NotPublic đều là OSError
                op.open(Request(self.url), timeout=3)

    def test_non_http_schemes_are_refused(self):
        for u in ("file:///C:/Windows/win.ini", "ftp://example.com/x", "data:text/plain,hi"):
            with self.assertRaises(OSError):
                SF.OPEN.open(Request(u), timeout=3)


class ReadBodyTest(unittest.TestCase):
    class _R:
        def __init__(self, data, enc=""):
            self._d, self.headers = data, ({"Content-Encoding": enc} if enc else {})

        def read(self, n=-1):
            return self._d if n < 0 else self._d[:n]

    def test_plain_body_is_capped(self):
        self.assertEqual(len(SF.read_body(self._R(b"a" * 5000), 100)), 100)

    def test_gzip_bomb_is_capped_after_decompression(self):
        bomb = gzip.compress(b"\0" * 50_000_000)
        self.assertLess(len(bomb), 100_000)
        out = SF.read_body(self._R(bomb, "gzip"), 1_000_000)
        self.assertEqual(len(out), 1_000_000)

    def test_bad_gzip_gives_empty(self):
        self.assertEqual(SF.read_body(self._R(b"not gzip", "gzip"), 1000), b"")


class RobotsMatchTest(unittest.TestCase):
    def test_matches_like_the_old_regex(self):
        cases = [("/", "/anything", True), ("/a", "/ab", True), ("/a", "/b", False), ("/a$", "/a", True),
                 ("/a$", "/ab", False), ("/*.pdf", "/x/y.pdf", True), ("/*.pdf$", "/x/y.pdf?v=1", False),
                 ("/*.pdf$", "/x/y.pdf", True), ("/a*b*c", "/a1b2c", True), ("/a*b*c", "/a1c2b", False),
                 ("/*?", "/p?x=1", True), ("/p*", "/p", True), ("/*", "/", True), ("/x*$", "/xyz", True)]
        for pat, path, want in cases:
            self.assertEqual(SC._robots_match(pat, path), want, (pat, path))

    def test_many_wildcards_do_not_blow_up(self):
        pat = "/" + "*a" * 40 + "*b"
        t = time.monotonic()
        self.assertFalse(SC._robots_match(pat, "/" + "a" * 5000))
        self.assertLess(time.monotonic() - t, 1.0)

    def test_rule_count_is_capped(self):
        txt = "User-agent: *\n" + "\n".join(f"Disallow: /p{i}" for i in range(SC.MAX_RULES + 500))
        self.assertEqual(len(SC.parse_robots(txt)[0]["rules"]), SC.MAX_RULES)


class SitemapChildTest(unittest.TestCase):
    def test_index_children_must_be_http_and_same_host(self):
        pages = {
            "https://abc.com/sitemap.xml": "<sitemapindex><loc>https://abc.com/s1.xml</loc><loc>file:///C:/x.xml</loc>"
                                           "<loc>http://evil.example/s2.xml</loc><loc>https://www.abc.com/s3.xml</loc>"
                                           "</sitemapindex>",
            "https://abc.com/s1.xml": "<urlset><loc>https://abc.com/a</loc></urlset>",
            "https://www.abc.com/s3.xml": "<urlset><loc>https://abc.com/b</loc></urlset>",
        }
        got = IX.read_sitemap("https://abc.com/sitemap.xml", lambda u: pages[u])  # KeyError nếu có lần tải ngoài danh sách
        self.assertEqual(got, ["https://abc.com/a", "https://abc.com/b"])


class UrlGroupHostTest(unittest.TestCase):
    SITE = "https://abc.com/"

    def test_same_site(self):
        self.assertTrue(U.same_site("https://abc.com/x", self.SITE))
        self.assertTrue(U.same_site("https://www.abc.com/x", self.SITE))
        for bad in ("http://127.0.0.1:8080/", "http://169.254.169.254/latest", "https://evil.example/x"):
            self.assertFalse(U.same_site(bad, self.SITE), bad)

    def test_group_rejects_foreign_hosts(self):
        from seo_report import db
        con = db.connect(":memory:")
        gid = U.ensure_group(con, self.SITE)
        r = U.add_to_group(con, self.SITE, gid, "https://abc.com/a http://127.0.0.1:8080/x https://evil.example/y", "t")
        self.assertEqual(r["added"], ["https://abc.com/a"])
        self.assertEqual(sorted(r["invalid"]), ["http://127.0.0.1:8080/x", "https://evil.example/y"])


if __name__ == "__main__":
    unittest.main()
