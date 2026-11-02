"""Dựng sheet mẫu gốc cho dự án mới từ bản xlsx của một sheet dự án đang chạy (xuất từ Google Sheets), rồi tải lên Drive
bằng tài khoản Google của tool và cài làm sheet mẫu gốc.

    python scripts/tao-sheet-mau-goc.py <file.xlsx> [--upload] [--config config.toml]

Giữ: kế hoạch OKRs (mã, hạng mục, chi tiết, số lượng, PIC), công thức, định dạng có điều kiện, dropdown, Weekly Task
Tracker (hàng mẫu), Đề xuất chi phí (các gói chuẩn). Xóa: ngày, trạng thái, % tiến độ, link bằng chứng, logo, task tuần,
Content của dự án cũ. Gantt đổi sang ngày tính từ ô 'Bắt đầu →' để tool điền ngày bắt đầu là tự chạy. Hai tab KPI thay
bằng bố cục mới (tool ghi lại cho từng dự án khi tạo sheet).
"""
import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import load_workbook  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from seo_report import kpi as KP  # noqa: E402

STATUS_TODO = "Chưa bắt đầu"


def _norm(t: str) -> str:
    return KP._norm_tab(t)


def clear(cell) -> None:
    """Xóa cả giá trị lẫn hyperlink (ô link giữ hyperlink thì lưu lại vẫn còn link)."""
    cell.value = None
    cell.hyperlink = None


def build_master(xlsx: bytes) -> bytes:
    wb = load_workbook(io.BytesIO(xlsx))
    okr = next(ws for ws in wb.worksheets if _norm(ws.title).startswith("okr"))
    # ---- OKRs: giữ kế hoạch, xóa chi tiết dự án ----
    okr["A1"] = None  # logo của dự án cũ
    okr["D1"] = ('=IF(N1="","SEO OKRs 3 Tháng","SEO OKRs 3 Tháng"&CHAR(10)&TEXT(N1,"d/m/yyyy")&" - "'
                 '&TEXT(EDATE(N1,3),"d/m/yyyy"))')
    start_cell = None
    for c in okr[1]:
        if isinstance(c.value, str) and "bắt đầu" in c.value.lower():
            start_cell = okr.cell(1, c.column + 1)
            start_cell.value = None
            break
    if start_cell is None:
        raise SystemExit("Không thấy ô 'Bắt đầu →' ở hàng 1 tab OKRs")
    # Gantt: cột ngày tính từ ngày bắt đầu (trước đây là ngày cố định)
    first_day_col = None
    for c in okr[2]:
        if c.column > 14 and c.value is not None:
            first_day_col = c.column
            break
    last_col = okr.max_column
    if first_day_col:
        for col in range(first_day_col, last_col + 1):
            c = okr.cell(2, col)
            if c.value is None and col > first_day_col:
                break
            ref = f"${start_cell.column_letter}$1"
            c.value = (f'=IF({ref}="","",{ref})' if col == first_day_col
                       else f'=IF({get_column_letter(col - 1)}2="","",{get_column_letter(col - 1)}2+1)')
    for r in range(3, okr.max_row + 1):
        if okr.cell(r, 1).value is None and okr.cell(r, 3).value is None:
            continue
        objective = (okr.cell(r, 2).value or "") == "MỤC TIÊU"
        for col in (8, 9):  # Start / End Date
            if not objective and not str(okr.cell(r, col).value or "").startswith("="):
                okr.cell(r, col).value = None
        if not objective:
            okr.cell(r, 11).value = STATUS_TODO
            if not str(okr.cell(r, 12).value or "").startswith("="):
                okr.cell(r, 12).value = None
        clear(okr.cell(r, 13))  # Link / Evidence
    # ---- Weekly Task Tracker: xóa task, giữ công thức và giá trị mặc định ----
    weekly = next((ws for ws in wb.worksheets if "weekly" in _norm(ws.title)), None)
    if weekly is not None:
        for r in range(2, weekly.max_row + 1):
            for col in (1, 3, 5, 6, 7, 8, 10, 11, 13, 14):
                v = weekly.cell(r, col).value
                if v is not None and not (isinstance(v, str) and v.startswith("=")):
                    clear(weekly.cell(r, col))
            if weekly.cell(r, 12).value not in (None, ""):
                weekly.cell(r, 12).value = STATUS_TODO
    # ---- Content: xóa hết dòng dữ liệu ----
    content = next((ws for ws in wb.worksheets if _norm(ws.title) == "content"), None)
    if content is not None:
        for r in range(2, content.max_row + 1):
            for col in range(1, content.max_column + 1):
                clear(content.cell(r, col))
    # ---- Đề xuất chi phí: giữ các gói chuẩn, bỏ trạng thái duyệt và link ----
    cost = next((ws for ws in wb.worksheets if "chi phí" in _norm(ws.title)), None)
    if cost is not None:
        for r in range(2, cost.max_row + 1):
            if cost.cell(r, 3).value is None:
                continue
            cost.cell(r, 8).value = "Đang lên kế hoạch"
            clear(cost.cell(r, 9))
    # ---- Hai tab KPI theo bố cục mới (ví dụ 6 tháng; tool ghi lại khi tạo sheet dự án) ----
    KP.fill_workbook(wb, KP.sample_data("SEO <tên miền>"), [])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--out", default="")
    ap.add_argument("--upload", action="store_true", help="Tải lên Drive của tool và cài làm sheet mẫu gốc")
    ap.add_argument("--config", default="config.toml")
    args = ap.parse_args()
    data = build_master(Path(args.xlsx).read_bytes())
    out = Path(args.out or (Path(args.xlsx).with_name("sheet-mau-goc.xlsx")))
    out.write_bytes(data)
    print("Đã dựng", out)
    if not args.upload:
        return
    from contextlib import closing

    from seo_report import db, drive as D, projects as PJ
    from seo_report.config import load_config
    cfg = load_config(args.config)
    svc = D.build_service(cfg)
    q = f"name = 'SEO Report – Sheet mẫu' and mimeType = '{D.FOLDER}' and trashed = false"
    found = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
    folder = found[0]["id"] if found else svc.files().create(
        body={"name": "SEO Report – Sheet mẫu", "mimeType": D.FOLDER}, fields="id").execute()["id"]
    f = D.upload(svc, data, "Sheet mẫu gốc – dự án SEO", D.XLSX, folder, D.SHEET)
    with closing(db.connect(cfg.db_path)) as con:
        PJ.set_master_sheet(con, f["id"])
    print("Đã tải lên và cài làm sheet mẫu gốc:", f["webViewLink"])


if __name__ == "__main__":
    main()
