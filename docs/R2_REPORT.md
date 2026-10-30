# R2 REPORT — Màn AI Search & GEO: Tổng quan + Nguồn AI

Ngày: 30/10/2026 · Trạng thái: **xong, đã thử trên dữ liệu GA4 thật**

## 1. File thay đổi

| File | Thay đổi |
|---|---|
| `seo_report/web_ai.py` | **Mới.** Màn `/ai` có 2 tab, dùng chung bộ lọc. Dữ liệu tải ở luồng nền. Có trạng thái đang tải (skeleton), lỗi (kèm nút "Thử lại") và cảnh báo |
| `seo_report/ai_format.py` | **Mới.** Định dạng số: đếm là số nguyên; rate hiện % với 2 chữ số thập phân; thời lượng hiện mm:ss; thiếu số hiện "N/A"; thay đổi % và thay đổi điểm có dấu. Có tên hiển thị cho nguồn, cách nhận diện và mã cảnh báo |
| `seo_report/web.py` | Thêm mục menu "AI Search & GEO" và route `/ai` |
| `seo_report/report.py` | Thêm `ai_block()`: lấy traffic AI của tuần báo cáo. Lỗi GA4 không làm hỏng báo cáo, chỉ trả về `{"error"}` |
| `seo_report/web_report.py`, `report_excel.py` | Thêm khối "Traffic từ AI assistant (GA4)" vào màn Báo cáo và file Excel gửi sếp |
| `tests/test_report.py` | Thêm 2 test: không có GA4 thì không hiện khối AI; khối AI và trường hợp lỗi trong Excel |

## 2. Giao diện

**Bộ lọc chung:**
- Kỳ: 7, 28, 90 ngày, tuần trước, tháng trước, hoặc tự chọn ngày.
- Bật/tắt so với kỳ trước.
- Lọc theo nguồn: bấm một dòng ở bảng nguồn; hiện thành nhãn có thể bấm ✕ để bỏ.
- Nút **Làm mới dữ liệu**: xóa cache rồi gọi lại GA4.

**Tab Tổng quan:**
- 8 thẻ KPI: Phiên AI, Tỷ lệ AI theo 2 mẫu số (có ghi rõ mẫu số), Engaged sessions, Engagement rate, Thời gian tương tác TB/phiên, Key events (kèm số key events/100 phiên), Session key event rate.
- Một dòng riêng cho "AI trả phí" (không tính vào AI organic).
- Biểu đồ AI so với Organic Search/Social. AI dùng trục phải vì nhỏ hơn Organic khoảng 100 lần; có ghi chú để không ai so độ cao hai đường. Kỳ dài hơn 45 ngày thì gộp theo tuần và đánh dấu tuần không trọn vẹn.
- Bảng so sánh kênh.
- Dòng ghi nguồn dữ liệu: property, chế độ phân loại, thời điểm truy vấn, có dùng cache hay không.

**Tab Nguồn AI:**
- Bảng nguồn: phiên, % phiên AI, thay đổi so với kỳ trước, engagement, thời gian TB, key events, session key event rate, cách nhận diện.
- Bấm một nguồn để lọc cả màn.
- Nút **Tải CSV** (có dòng đầu ghi kỳ, chế độ phân loại, property, thời điểm truy vấn, bộ lọc).
- Biểu đồ top 5 nguồn + "AI khác".
- Bảng chi tiết source / medium / kênh để đối soát danh sách nhận diện.

## 3. Kiểm tra trên dữ liệu thật

| Kịch bản | Kết quả |
|---|---|
| Mở `/ai`, kỳ mặc định 28 ngày | 221 phiên AI (−0,5%); tỷ lệ 0,36% site / 0,87% organic; session key event rate 2,26% (Organic Search 0,44%) |
| Tab Nguồn AI | ChatGPT 191 · Gemini 25 · Perplexity 4 · Claude 1 |
| Bấm Gemini để lọc | Có nhãn "Nguồn: Gemini"; tab Tổng quan còn 25 phiên, khớp với bảng nguồn |
| Bỏ nhãn lọc | Về lại 221 phiên |
| Tự chọn ngày 01/08–29/10 | 635 phiên (+63,7%), khớp đối soát ở R1; biểu đồ theo tuần; đánh dấu 2 tuần không trọn vẹn (27/07, 26/10) |
| Báo cáo tuần 19–25/10 | Khối AI: 65 phiên (+91,2%), ChatGPT 60 · Gemini 5; loại 33 phiên quảng cáo AI |

Test: `python -m unittest` **PASS**, 74 test.

## 4. Lỗi tìm ra trong lúc thử và đã sửa

- **Bấm lọc nguồn làm màn trống.** Lệnh tải lại được gắn vào bảng; khi vẽ lại, bảng bị xóa nên lệnh tải bị hủy theo. Đã chuyển sang chạy độc lập (`background_tasks`).
- **Lỗi khi vẽ trước đây làm trang trống, không có thông báo.** Giờ lỗi hiện ngay trên màn ("Lỗi hiển thị: …") và được ghi vào log.

## 5. Hạn chế

- **Bộ lọc chưa lưu trên URL** (spec §3.1 chỉ yêu cầu khi codebase đã hỗ trợ sẵn). Tải lại trang thì về kỳ mặc định 28 ngày.
- Chưa có bộ lọc quốc gia trên giao diện, dù phần xử lý đã hỗ trợ. Sẽ thêm ở R3 cùng tab Địa lý: bấm một quốc gia để lọc.
- **Tuần báo cáo dùng múi giờ Asia/Saigon cho GA4, nhưng Pacific cho GSC.** Hai nguồn đang nằm ở hai khối riêng trong báo cáo, không cộng chung, nên không sai số. Lệch ngày chỉ đáng kể khi so theo từng ngày.
- **Tuần 19–25/10 chỉ có 65 phiên**, nên engagement dao động mạnh (−28,5 điểm). Báo cáo đã có cảnh báo khi mẫu nhỏ.

## 6. Đề xuất R3

- Tab **Trang đích**: bảng có phân trang, sắp xếp, tìm kiếm; `(not set)` là một dòng riêng có cảnh báo; nhóm trang theo loại URL đã có từ Quản lý URL; biểu đồ theo thời gian cho trang đang chọn.
- Tab **Địa lý**: bảng quốc gia, quốc gia × nguồn, bấm để lọc.
- **Xuất Excel/CSV** cho cả ba tab, theo đúng bộ lọc đang chọn.
