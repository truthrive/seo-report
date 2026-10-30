@echo off
rem Nhấp đúp để mở giao diện SEO Report trên trình duyệt. Đóng cửa sổ đen này là tắt giao diện.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m seo_report web
