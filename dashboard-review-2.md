# Review lần 2 màn Tổng quan: ui-ux-pro-max + dataviz

Ngày 07/11/2026 · bố cục mới: 3 hàng đầu Thứ hạng → Search Console → GA4 · chưa commit.
Đo trực tiếp trên trang ở 1440px và 375px, cùng bộ tiêu chí với lần 1.

## 1. So với lần 1

| Lần 1 | Trạng thái |
|---|---|
| D1 cột thứ hạng tăng giả (P0) | **Đã sửa:** tính theo % trên số đã check, ẩn lần check thiếu từ khóa; khi chưa đủ 2 điểm thì hiện thanh phân đoạn |
| D2 màu nhóm hạng không phân biệt với người mù màu | **Đã sửa:** một tông xanh đậm → nhạt + xám, đạt cả 4 bước kiểm tra `--ordinal` |
| D3 trục không từ 0 | **Đã sửa:** trục bắt đầu từ 0, có số trên trục |
| D4 donut kênh | **Đã sửa:** thanh ngang xếp hạng, Organic tô nổi bật, số và % ghi sẵn |
| D5 vòng Uy tín không mục tiêu | **Đã sửa:** đổi thành ô số kèm mức thay đổi |
| D6 Lighthouse chỉ có màu | **Đã sửa:** thêm chữ Tốt / Cần cải thiện / Kém |
| D8 chữ số đều độ rộng trên số lớn | **Đã sửa** |
| A1 thẻ bấm được không dùng bàn phím | **Đã sửa:** 24 phần tử tới được bằng Tab, thẻ có link là thẻ `<a>` |
| A3 vùng bấm | **Gần đạt:** link nhóm 28px (đạt); nút (i) 23×23px (thiếu 1px so với 24) |
| L1 trang nhảy khi GA4 tải xong | **Đã sửa:** khu biểu đồ của 3 hàng đều cao 290px, bên trái và bên phải bằng nhau |
| L2 cột lệch chiều cao (hàng 1) | **Đã sửa ở 3 hàng đầu;** vẫn còn ở hàng Tốc độ / Backlink (mục 2, U4) |
| D9, A2 không có bảng số / mô tả biểu đồ | **Còn một phần** (A2 ở mục 2) |

Bố cục mới không tràn ngang ở 375px và 1440px.

## 2. Vấn đề còn lại

| # | Mức | Vấn đề | Bằng chứng | Đề xuất |
|---|---|---|---|---|
| U1 | **P1** | **Việc cần xử lý và KPI bị đẩy xuống thấp.** Ba hàng SEO cao khoảng 1.130px, nên "Cần xử lý" bắt đầu ở khoảng 1.360px và KPI ở 1.556px, tức là dưới 1,5 màn hình. Team mở trang không thấy ngay việc gấp; khách hàng không thấy ngay KPI cam kết | Đo vị trí các khối trên trang | Giữ thứ tự bạn đã chọn, nhưng thêm **một dòng tóm tắt dưới tiêu đề**: "2 việc cần xử lý ↓ · KPI tháng 1: 3/4 đang đạt ↓", bấm thì cuộn xuống khối tương ứng |
| U2 | **P1** | **Nút (i) mờ quá:** độ tương phản 2,6:1, dưới mức 3:1 cho biểu tượng | Đo màu | Đổi màu icon sang `#6B6A5E` (5,3:1); nới vùng bấm thêm 1px lên 24px |
| U3 | **P1** | **4 ô GA4 cùng ghi "Đang lấy số GA4…"** khi đang tải: lặp 4 lần, trông như lỗi | Ảnh chụp lúc tải | Ô đang tải dùng khung giữ chỗ (skeleton), chỉ ghi chữ trạng thái **một lần** ở thanh tiêu đề nhóm |
| U4 | **P2** | **Hàng Tốc độ / Backlink lệch chiều cao:** khối Tốc độ cao 473px, Backlink 331px, để lại khoảng trống khoảng 140px | Đo chiều cao nhóm | Xếp 4 vòng Lighthouse thành 1 hàng ngang × 4 ở khổ rộng (thấp hơn khoảng 200px), hoặc cho thẻ biểu đồ Backlink giãn cho bằng |
| U5 | **P2** | **"Lên / rớt hạng ▲4 · ▼5" không có màu**, trong khi mọi chỗ khác ▲ xanh, ▼ đỏ | Ảnh chụp | Tô ▲4 xanh, ▼5 đỏ, giữ chữ để không chỉ dựa vào màu |
| U6 | **P2** | **Các dòng ghi chú trong thẻ thứ hạng chữ 11,5px**, dày 4–5 dòng (KPI, AI Overview, đối thủ, dòng ẩn điểm) làm thẻ rối | Đo cỡ chữ: 6 chữ 11,5px | Lên 12px; gom thành danh sách 3 dòng có icon, hoặc chuyển "AI Overview / đối thủ" xuống dòng tóm tắt dưới hàng |
| U7 | **P2** | **Khoảng thời gian lặp 4 lần** (tiêu đề trang + 3 thanh nhóm), mỗi lần là một câu dài | Ảnh chụp | Thanh GSC / GA4 chỉ ghi "Kỳ đang chọn · 28 ngày"; khoảng ngày đầy đủ giữ ở tiêu đề trang |
| U8 | **P2** | **Link của hàng GA4 ghi "AI Search & GEO"**, không khớp nội dung hàng (phiên, kênh) | Ảnh chụp | Đổi chữ thành "Traffic & AI" hoặc "Xem nguồn truy cập" (cùng trang `/ai`) |
| U9 | **P2** | **Mô tả biểu đồ cho trình đọc màn hình còn thiếu:** 4 vòng Lighthouse và biểu đồ link mới / mất chưa có | 1/6 biểu đồ (ECharts) có mô tả, chưa kể thanh phân đoạn (đã có) | Thêm mô tả ("Hiệu năng 65/100, cần cải thiện"; "Link mới / mất 12 tháng, tháng 09/2026 +221 / −14") |
| U10 | **P2** | **Ô Top 3 / Top 10 còn nhiều khoảng trống** vì cao bằng biểu đồ bên cạnh (290px, mỗi ô khoảng 140px, nội dung chỉ khoảng 70px) | Đo chiều cao | Ghi thêm dòng "So với lần check trước: +1" (đã có trong dữ liệu `rank_snapshot` qua lên / rớt), hoặc giảm chiều cao biểu đồ xuống 240px |
| U11 | **P2** | **Chú thích thanh phân đoạn**: "Ngoài độ sâu check" xuống 2 dòng làm lệch hàng chú thích | Ảnh chụp | Đổi chữ thành "Ngoài top check", hoặc cho chú thích xếp 2 cột |

## 3. Kiểm tra màu (dataviz, chạy script)

| Biểu đồ | Kết quả |
|---|---|
| Nhóm hạng (xanh đậm → nhạt + xám) | Đạt `--ordinal`: tông màu tăng dần, khoảng cách đủ, đầu nhạt 2,04:1 |
| Phiên theo kênh (1 màu nhấn + xám) | Đạt theo dạng "nhấn một, còn lại xám": không cần bảng màu nhiều sắc |
| Link mới / mất (xanh nhạt / đỏ) | Đạt; xanh nhạt 2,1:1 nên cần số ghi sẵn (đã có dòng "Tháng 09/2026: +221 · −14") |
| Lighthouse (xanh / vàng / đỏ) | Màu trạng thái đúng chỗ, có chữ kèm theo |

## 4. Thứ tự sửa đề xuất

1. **P1:** U1 (dòng tóm tắt cuộn xuống), U2 (màu nút i), U3 (khung giữ chỗ GA4).
2. **P2:** U5, U6, U4, U7, U8, U9, U10, U11.

Lần này chỉ review, chưa sửa code.
