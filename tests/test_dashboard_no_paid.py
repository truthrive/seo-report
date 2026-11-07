"""Màn Tổng quan không được gọi API trả phí (DataForSEO) khi mở trang hay khi bấm trên trang.

Hai lớp kiểm tra:
1. Tĩnh: mã màn Tổng quan (web_dashboard và các hàm nó dựng: health_strip, todo_section, dashboard_lines) không gọi
   hàm gửi yêu cầu nào trên các module trả phí (backlinks, rank, volume, intent).
2. Chạy thật: giả lập API trả phí bằng cách chặn mọi kết nối HTTPS tới *dataforseo* và mọi urlopen của các module đó,
   rồi chạy các hàm đọc số của màn Tổng quan; không có lần gọi nào bị chặn (tức là không hàm nào định gọi).
"""
import ast
import http.client
import inspect
import tempfile
import textwrap
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from seo_report import backlinks as BL
from seo_report import db
from seo_report import dash_widgets, web_aio, web_dashboard, web_overview

PAID = {  # hàm / lớp gửi yêu cầu DataForSEO
    "refresh", "fetch", "fetch_lists", "fetch_missing", "Client", "DataForSEO", "_live", "_call", "summary",
    "referring_domains", "changes", "anchors", "pages",
}
PAID_MODULES = {"BL", "backlinks", "R", "rank", "volume", "V", "intent"}  # tên module trả phí khi import


def _paid_calls(fn) -> set[str]:
    """Hàm trả phí được gọi trên module trả phí (BL.refresh(...)). Bỏ qua .refresh() của ui.refreshable."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id in PAID_MODULES \
                and node.func.attr in PAID:
            out.add(f"{node.func.value.id}.{node.func.attr}")
    return out


class StaticTest(unittest.TestCase):
    def test_dashboard_code_calls_no_paid_function(self):
        for fn in (web_dashboard.build_dashboard_page, web_dashboard.rank_snapshot, web_dashboard.index_snapshot,
                   web_dashboard.kpi_rank_line, web_overview.health_strip, web_overview.todo_section,
                   web_aio.dashboard_lines, web_aio.competitor_line, web_aio.load, dash_widgets.lighthouse_avg, dash_widgets.channel_items):
            self.assertEqual(_paid_calls(fn), set(), f"{fn.__qualname__} gọi hàm trả phí")

    def test_detector_catches_a_paid_call(self):  # đối chứng: bộ dò bắt được lời gọi trả phí thật
        def sample(con):
            BL.refresh(con, "x", None)
        self.assertEqual(_paid_calls(sample), {"BL.refresh"})


class _Ctx:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *a):
        return False


class RuntimeGuardTest(unittest.TestCase):
    def test_read_functions_make_no_paid_connection(self):
        blocked: list[str] = []
        orig = http.client.HTTPSConnection.__init__

        def guard(self, host, *a, **kw):
            if "dataforseo" in str(host):
                blocked.append(str(host))
                raise RuntimeError("paid API blocked")
            return orig(self, host, *a, **kw)

        def no_urlopen(*a, **kw):
            blocked.append("urlopen")
            raise RuntimeError("network blocked")

        site = "sc-domain:a.vn"
        with tempfile.TemporaryDirectory() as d:
            con = db.connect(Path(d) / "t.db")  # đủ bảng như DB thật của một dự án
            try:
                with mock.patch.object(http.client.HTTPSConnection, "__init__", guard), \
                        mock.patch("seo_report.backlinks.urlopen", no_urlopen), \
                        mock.patch("seo_report.rank.urlopen", no_urlopen), \
                        mock.patch("seo_report.volume.urlopen", no_urlopen):
                    BL.ensure_tables(con)
                    web_dashboard.rank_snapshot(con, site, date(2026, 11, 3))
                    web_dashboard.index_snapshot(con, site)
                    BL.latest(con, site)
                    BL.settings(con, site)
                    web_aio.load(lambda: _Ctx(con), mock.Mock(site_url=site))
            finally:
                con.close()
        self.assertEqual(blocked, [])

    def test_guard_blocks_real_paid_client(self):  # đối chứng: nếu có gọi, bộ chặn ghi nhận được
        hits = []

        def no_urlopen(*a, **kw):
            hits.append(1)
            raise RuntimeError("network blocked")
        with mock.patch("seo_report.backlinks.urlopen", no_urlopen):
            client = BL.Client("x", "y")  # chỉ dựng header, chưa gọi mạng
            try:
                client._live("summary", {"target": "a.vn"})
            except Exception:  # noqa: BLE001
                pass
        self.assertEqual(hits, [1])


if __name__ == "__main__":
    unittest.main()
