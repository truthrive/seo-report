import inspect
import unittest

from seo_report import ui_theme as T
from seo_report import web_dashboard, web_kpi


class LoadingStatesTest(unittest.TestCase):
    """Quy ước trạng thái đang tải: vùng chờ mang aria-busy và được tắt khi xong; khung xám ẩn với trình đọc màn hình;
    vòng xoay (chờ không có hình dạng) là role="status" kèm chữ."""

    def test_spinner_is_status_with_label(self):
        src = inspect.getsource(T.spinner)
        self.assertIn('role="status"', src)
        self.assertIn('aria-hidden="true"', src)  # vòng xoay chỉ để nhìn; chữ mới là thứ được đọc

    def test_skeleton_bones_hidden(self):
        self.assertIn('aria-hidden="true"', inspect.getsource(T.bone))
        self.assertIn('aria-busy="true"', inspect.getsource(T.skeleton))

    def test_kpi_regions_cleared(self):
        page = inspect.getsource(web_kpi.build_kpi_page)
        self.assertIn('aria-busy="true"', page)
        self.assertIn("T.busy(box, False)", page)
        dash = inspect.getsource(web_dashboard.build_dashboard_page)
        self.assertIn("T.busy(kpi_box, True)", dash)
        self.assertIn("T.busy(kpi_box, False)", dash)
        self.assertIn("T.busy(groups[key], False)", dash)


if __name__ == "__main__":
    unittest.main()
