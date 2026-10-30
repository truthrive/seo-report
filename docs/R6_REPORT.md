# R6 REPORT — Nhập file GSC Generative AI (AI Overviews / AI Mode)

Ngày: 30/10/2026 · Trạng thái: **xong**. Đã nhập file thật `…Generative-AI-Features-2026-10-30.zip` (lần nhập #1).

## 1. Kiểm chứng trước khi làm

- **GSC vẫn không có API cho báo cáo này.** Tài liệu Search Analytics API, xem ngày 30/10/2026, chỉ có các loại `web`, `image`, `video`, `news`, `discover`, `googleNews`. Vì vậy chỉ có cách nhập file export.
- **Báo cáo đã mở cho mọi site từ 31/08/2026.** Báo cáo gồm AI Overviews và AI Mode, chỉ có impression. Ô "~" hoặc "-" trên giao diện bị xuất thành 0.
- **Cấu trúc file thật:** một file zip gồm 5 CSV (Chart, Pages, Countries, Devices, Filters).
  - **Filters không ghi ngày cụ thể**, chỉ ghi "Last 3 months". Vì vậy kỳ phải lấy từ ngày đầu và ngày cuối của bảng Chart.
  - **Pages bị cắt ở đúng 1.000 dòng.** Trang thấp nhất có 13 impression.
  - **Tổng theo trang (503.383) lớn hơn tổng site (483.217).** GSC tính bảng trang theo từng trang, còn Chart, Countries, Devices tính theo property; ba bảng sau có tổng khớp nhau đúng 483.217.

## 2. File thay đổi

| File | Thay đổi |
|---|---|
| `seo_report/ai_gsc_import.py` | **Mới.** Gồm:<br>• `parse`: đọc file zip CSV hoặc xlsx. Nhận ra từng bảng theo nội dung chứ không theo tên, nên vẫn chạy khi GSC để giao diện tiếng Việt.<br>• `save` / `delete`: lưu và ẩn lần nhập, có nhật ký.<br>• `daily`: số theo ngày, lấy từ lần nhập mới nhất.<br>• `period_total`: trạng thái `NOT_CONNECTED` / `PARTIAL` / `MANUAL_IMPORT`.<br>• `breakdown`, `web_daily`.<br>• 3 bảng SQLite: `gsc_ai_imports`, `gsc_ai_daily`, `gsc_ai_breakdown`. |
| `seo_report/web_ai.py` | Thêm tab **AI trên Google**, gồm:<br>• ô nhập file, có màn kiểm tra trước khi nhập;<br>• KPI của kỳ đang chọn;<br>• biểu đồ tuần: impression và % trên GSC Web;<br>• bảng trang (cạnh GSC Web cùng kỳ), bảng quốc gia, bảng thiết bị;<br>• CSV;<br>• lịch sử nhập, có nút ẩn từng lần nhập. |
| `seo_report/report.py`, `web_report.py`, `report_excel.py` | Báo cáo tuần có thêm khối "Hiển thị trong AI Overviews / AI Mode", trên màn hình và trong Excel. |
| `seo_report/ai_quality.py` | Tab Chất lượng dữ liệu báo file GSC AI có dữ liệu tới ngày nào. Cảnh báo khi đã quá 10 ngày. |
| `seo_report/ai_export.py` | Excel màn AI thêm 2 sheet: AI Overviews theo ngày, AI Overviews theo trang. |
| `README.md` | Hướng dẫn xuất và nhập file mỗi tuần. |
| `tests/test_ai.py` | Thêm 7 test (`R6GenerativeAIImportTest`). |

## 3. Quy tắc dữ liệu

| Tình huống | Cách xử lý |
|---|---|
| Ô "~" / "-" (trong file là 0) | Lưu là "không rõ", không tính là 0. Có đếm và báo số ô như vậy khi nhập |
| Kỳ đang chọn chưa được file nào phủ hết | Không hiện tổng, hiện "Thiếu dữ liệu, file phủ x/y ngày" |
| Chưa nhập file nào | Hiện "Chưa có dữ liệu", không hiện 0. Báo cáo tuần không có khối này |
| Hai lần nhập trùng ngày | Số theo ngày lấy từ lần nhập mới nhất, không cộng dồn. Lý do: số gần đây của GSC còn thay đổi |
| Bảng trang, quốc gia, thiết bị | Mỗi bảng thuộc kỳ của riêng lần nhập đó, không gộp giữa các lần nhập |
| Cộng các trang để ra tổng site | Không làm. Tổng site lấy từ bảng Chart |
| File xuất khi đang lọc trang/quốc gia/thiết bị | Từ chối, yêu cầu xuất lại không lọc. Lý do: số trong file khi đó không phải của toàn site |
| Trang không thuộc matkinhtamduc.com | Từ chối, vì nhiều khả năng xuất nhầm property |
| Web dạng chữ và Web đa phương thức | Lưu riêng, không cộng. Màn hình hiện Web dạng chữ, đúng loại mà GSC chọn mặc định |
| URL có `?page=2`, `?attribute_…` | Giữ nguyên URL gốc. Ghép về URL báo cáo của tool để so với GSC Web |
| Nhập nhầm | Ẩn lần nhập trong "Lịch sử nhập". Dữ liệu vẫn giữ để đối soát |

**Tỷ lệ AI Overviews / GSC Web:** cả hai số đều của GSC, đều tính theo property và theo giờ Pacific. Google ghi rõ báo cáo AI được lấy từ dữ liệu Web, nên phép chia này hợp lệ. Đây không phải phép trộn GA4 với GSC mà spec cấm.

## 4. Kiểm tra trên dữ liệu thật

| Kiểm tra | Kết quả |
|---|---|
| Đọc file | 92 ngày (28/07–27/10), 483.217 impression, 1.000 trang, 157 quốc gia, 3 thiết bị, 0 ô "~" |
| Ghép URL | 1.000/1.000 trang ghép được với URL của tool |
| Đối soát | Tổng Chart = tổng Countries = tổng Devices = 483.217 |
| Tab AI trên Google (tuần 19–25/10) | 48.226 impression, chiếm 26,73% impression GSC Web, đủ 7/7 ngày. Không có lỗi console |
| Báo cáo tuần (màn hình và Excel) | Khối mới: 48.226 impression (+0,8%), 26,73% |
| Test | `python -m unittest` **PASS**, 100 test (93 cũ + 7 mới) |

## 5. Phát hiện cho sếp

**AI Overviews / AI Mode đang chiếm phần ngày càng lớn trong lượt hiển thị Google của site:**

| Tuần (thứ Hai) | Impression AI Overviews / AI Mode | Impression GSC Web | Tỷ lệ |
|---|---|---|---|
| 03/08 | 29.995 | 158.810 | 18,9% |
| 07/09 | 36.239 | 165.142 | 21,9% |
| 05/10 | 43.665 | 166.391 | 26,2% |
| 19/10 | 48.226 | 180.397 | 26,7% |

- **Trong 12 tuần, impression AI tăng 61%**, trong khi impression Web chỉ tăng 14%. Hơn một phần tư lượt hiển thị trên Google của site giờ nằm trong câu trả lời AI.
- **Trang có tỷ lệ AI cao là trang danh mục tròng kính:** "tròng kính siêu mỏng" 44,6%, Chemi 39,6%, Essilor 28,8%. Blog dạng "… là gì" cũng cao: "mắt xếch là gì" 29,9%.
- **Gợi ý theo dõi:** GSC không cho biết click từ AI Overviews. Nếu click Web giảm trong khi tỷ lệ AI tăng, đó là dấu hiệu AI trả lời thay, người dùng không cần bấm vào site. Nên so hai chỉ số này hằng tháng.

## 6. Hạn chế và phản biện

- **Phải nhập tay mỗi tuần.** Nếu không ai làm, tab Chất lượng dữ liệu cảnh báo sau 10 ngày, còn báo cáo tuần hiện "Chưa có số cho tuần này" chứ không hiện 0. Nên giao cố định một người làm việc này, ví dụ mỗi thứ Hai.
- **Tab Cơ hội SEO/GEO không có cột AI Overviews.** Bảng trang trong file là tổng của cả kỳ export (3 tháng), không tách được theo kỳ 28 ngày của tab Cơ hội. Đặt hai kỳ khác nhau cạnh nhau sẽ gây hiểu sai. So sánh theo trang được làm trong tab AI trên Google, với GSC Web cùng kỳ của file.
- **Chỉ có 1.000 trang.** Trang có dưới khoảng 13 impression trong 3 tháng không có trong file.
- Tool chưa kiểm thử với file export ở giao diện GSC tiếng Việt. Bộ đọc nhận bảng theo nội dung nên vẫn chạy, có test mô phỏng. Nếu gặp lỗi, gửi file để tôi chỉnh.

## 7. Bước tiếp theo

Module AI Search & GEO (R0–R6) đã đủ. Việc còn lại của lộ trình chính là **bước 7**: VPS, đăng nhập Google, vai trò Admin/Editor/Viewer, sao lưu. Làm xong bước này thì mở thêm chức năng sửa danh sách nguồn AI trên màn hình.
