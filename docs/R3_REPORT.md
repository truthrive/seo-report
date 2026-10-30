# R3 REPORT — Trang đích, Địa lý, xuất file

Ngày: 30/10/2026 · Trạng thái: **xong, đã thử trên dữ liệu GA4 thật (28 ngày, 02/10–29/10)**

## 1. File thay đổi

| File | Thay đổi |
|---|---|
| `seo_report/ai_analytics.py` | Thêm 4 hàm: `organic_by_landing` (cột Organic Search để tham khảo); `segments` (KPI theo nhóm loại trang, mỗi nhóm một truy vấn tổng hợp với `landingPage ∈ danh sách trang của nhóm`); `country_sources` (ma trận quốc gia × nguồn); `country_trend` (top 5 quốc gia, còn lại gộp "Quốc gia khác") |
| `seo_report/web_ai.py` | Thêm 2 tab Trang đích và Địa lý, chỉ tải khi mở tới. Thêm bộ lọc quốc gia và trang đích (dạng nhãn có thể bấm ✕ để bỏ). Thêm bảng key event theo từng event ở tab Tổng quan, cửa sổ chi tiết một trang đích, CSV cho từng bảng, nút **Xuất Excel** toàn màn. Thêm `landing_types()` để ghép đường dẫn GA4 với loại trang của tool |
| `seo_report/ai_export.py` | **Mới.** Excel 11 sheet theo đúng bộ lọc đang chọn |
| `tests/test_ai.py` | Thêm 5 test |

## 2. Giao diện

**Tab Trang đích:**
- **Bảng theo loại trang** (Trang chủ, Cửa hàng, Sản phẩm, Danh mục con, Blog…). Loại trang lấy từ màn Quản lý URL, không dùng `contentGroup` của GA4 (spec §3.4). Tỷ lệ của mỗi nhóm do GA4 tính.
- **Bảng từng trang:**
  - lọc theo loại, tìm kiếm, sắp xếp, phân trang 25 dòng;
  - di chuột lên đường dẫn để xem URL đầy đủ;
  - `(not set)` là một dòng riêng có nhãn "không xác định";
  - có cột Organic Search để tham khảo quy mô, ghi rõ đây không phải traffic AI.
- **Bấm một trang** để xem biểu đồ phiên AI theo thời gian và phân theo nguồn; có nút lọc cả màn theo trang đó.

**Tab Địa lý:**
- Bảng quốc gia; bấm một quốc gia để lọc cả màn.
- Ma trận top 10 quốc gia × nguồn.
- Xu hướng top 5 quốc gia.
- Ghi chú: đây là quốc gia của người truy cập do GA4 ghi nhận, không phải vị trí cửa hàng.

**Tổng quan:** thêm bảng key event theo từng event, có giải thích vì sao một số ô hiện N/A.

**Xuất file:**
- **Xuất Excel** toàn màn, 11 sheet: Thông tin, Tổng quan, Kênh, Nguồn AI, Nguồn chi tiết, Key events, Xu hướng, Loại trang, Trang đích, Quốc gia, Quốc gia × nguồn. Sheet Thông tin ghi rõ kỳ, bộ lọc, cách phân loại, property, thời điểm truy vấn và các cảnh báo.
- **CSV** cho từng bảng nguồn, trang đích, quốc gia. Dòng đầu ghi kỳ, bộ lọc, chế độ phân loại, property.

## 3. Kiểm tra trên dữ liệu thật

| Kịch bản | Kết quả |
|---|---|
| Tab Trang đích | Trang chủ 52 phiên · Cửa hàng 36 (10 trang) · Sản phẩm 28 (25 trang) · Danh mục con 25 · Danh mục 17 · Trang thông tin 11 · Blog 8 |
| Bảng key event | add_to_cart 4 (0,90% phiên) · Click Zalo 3 (N/A) · booking_success 1 (0,45%) · purchase 0 (0,00%) |
| Tab Địa lý | Việt Nam 206 (92,8%) · Trung Quốc 4 · Mỹ 4 · Nhật 2… |
| Ma trận quốc gia × nguồn | Việt Nam: ChatGPT 177, Gemini 24, Perplexity 4, Claude 1 |
| Bấm Việt Nam để lọc | Tab Tổng quan còn 206 phiên, khớp bảng quốc gia |
| Xuất Excel | Tải về `ai-search-geo_2026-10-02_2026-10-29.xlsx` |

Test: `python -m unittest` **PASS**, 79 test.

## 4. Phát hiện từ dữ liệu (để báo cáo sếp)

- **Phiên AI vào trang Cửa hàng và trang Sản phẩm chuyển đổi tốt nhất.** Session key event rate lần lượt là **5,56%** và **7,14%**, so với 1,92% của trang chủ. Người dùng đến từ ChatGPT thường đã có ý định cụ thể: tìm cửa hàng gần nhà, hoặc một mẫu kính cụ thể.
- **AI đang dẫn traffic tới 25 trang sản phẩm khác nhau.** Nghĩa là ChatGPT đang gợi ý sản phẩm cụ thể của Tâm Đức, đây là tín hiệu GEO tốt.
- **Blog chỉ nhận 8 phiên AI**, dù blog chiếm phần lớn traffic Organic Search. Nội dung blog hiện chưa được AI trích dẫn nhiều. Đây là gợi ý để phân tích ở R4, chưa phải kết luận.

## 5. Hạn chế

- **% thay đổi rất lớn khi kỳ trước gần bằng 0**, ví dụ Danh mục +1.600% (1 lên 17 phiên). Con số đúng nhưng dễ gây hiểu lầm. Đề xuất ở R5: ẩn % khi kỳ trước có dưới 10 phiên, chỉ hiện số tuyệt đối.
- 10 trang đích AI có loại "Chờ đọc schema": các trang này chưa được tool phân loại. Lịch chạy hằng ngày sẽ dần xử lý hết.
- Bộ lọc vẫn chưa lưu trên URL. Tải lại trang thì mất bộ lọc.

## 6. Đề xuất R4

Tab **Cơ hội SEO/GEO**:
- ghép URL theo hai nguồn: GA4 AI referral và GSC Web, đặt hai nhóm cột riêng, có lọc khớp / không khớp;
- 3 quy tắc theo spec, ngưỡng chỉnh được: `AI_REFERRAL_WITH_LOW_GSC_VISIBILITY`, `GSC_HIGH_IMPRESSIONS_LOW_AI_REFERRAL`, `AI_ENGAGEMENT_WEAK`;
- mỗi gợi ý kèm bằng chứng, ngưỡng, độ tin cậy và cách kiểm chứng.
