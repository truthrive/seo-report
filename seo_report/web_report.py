"""Màn Báo cáo (tab Tuần | Tháng): bản gửi quản lý / khách hàng của màn Tổng quan, thêm nhận xét và nút xuất Excel."""
from .web_overview import build_overview_page


def build_report_page(ui, cfg, connect, user: str, ctx: dict, kind: str = "week") -> None:
    build_overview_page(ui, cfg, connect, user, ctx, mode="report", kind=kind)
