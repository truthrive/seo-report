# R1 REPORT — Lõi phân tích GA4 + bộ phân loại AI

Ngày: 30/10/2026 · Trạng thái: **xong; chưa có giao diện (thuộc R2)**

## 1. File thay đổi

| File | Thay đổi |
|---|---|
| `seo_report/ai_classifier.py` | **Mới.** Có 3 phần: (1) `classify()` phân loại từng dòng nguồn/medium/kênh; (2) `ga4_filter()` dựng bộ lọc GA4 tương đương; (3) `paid_ai_filter()` lọc riêng traffic AI trả phí. Danh sách host, tên ghi tắt và regex medium trả phí đều có số phiên bản (`v1`) |
| `seo_report/ga4_query.py` | **Mới.** `GA4Client`: chạy runReport, giữ None khi không có số, cache SQLite (bảng `ga4_cache`, TTL 3 giờ hoặc 24 giờ), `incompatible()` gọi checkCompatibility. `error_code()` trả mã chẩn đoán theo §7.3 |
| `seo_report/ai_analytics.py` | **Mới.** `AIAnalytics` gồm `summary`, `sources`, `trend`, `landing_pages`, `countries`, `key_events`. Mỗi hàm trả về cùng một kiểu kết quả theo §6.1 |
| `seo_report/cli.py` | Thêm lệnh `ai-summary --days N` để đối soát nhanh |
| `tests/test_ai.py` | **Mới.** 19 test, dùng một GA4 giả lập ở mức từng phiên |

## 2. Truy vấn GA4 đang dùng

Mọi truy vấn dùng **cùng một bộ lọc AI** (`ga4_filter`, chế độ HYBRID), ghép thêm bằng AND với bộ lọc chung (quốc gia, trang đích).

| Mục đích | Dimensions | Metrics |
|---|---|---|
| KPI tổng AI (Q0) | *(rỗng)* | sessions, engagedSessions, engagementRate, userEngagementDuration, averageSessionDuration, keyEvents, sessionKeyEventRate |
| KPI từng nguồn con | *(rỗng)*, bộ lọc `only=<nguồn>` | như trên |
| Bảng nguồn chi tiết (Q1) | sessionSource, sessionMedium, sessionDefaultChannelGroup | sessions, engagedSessions, keyEvents (chỉ số đếm) |
| Kênh organic | sessionDefaultChannelGroup (lọc Organic Search/Social) | như Q0 (mỗi dòng là một kênh nên dùng rate gốc) |
| Mẫu số | *(rỗng)* | sessions: toàn site; và nhóm (AI OR organic) đếm phiên không trùng |
| AI trả phí | *(rỗng)*, `paid_ai_filter` | sessions, keyEvents |
| Xu hướng (Q2) | date; date + sessionDefaultChannelGroup; date + sessionSource | sessions |
| Trang đích (Q3) / Quốc gia (Q4) | landingPage / country | sessions, engagedSessions, engagementRate, keyEvents, sessionKeyEventRate |
| Key event theo từng event | eventName; và *(rỗng)* | keyEvents; sessions + `sessionKeyEventRate:<event>` |

## 3. Test

Lệnh: `python -m unittest`. Kết quả: **PASS**, 72 test (19 test mới của R1).

Các điểm spec §8 đã có test:
- **Phân loại:**
  - "AI Assistant" và "AI Assistants" đều được nhận;
  - subdomain hợp lệ được nhận; `evilchatgpt.com` và `geminiapp` bị loại;
  - `google`, `google.com` không bao giờ là AI;
  - 5 kiểu medium trả phí bị loại;
  - các chế độ NATIVE và FALLBACK_ONLY hoạt động đúng;
  - **bộ lọc GA4 và `classify()` chọn đúng cùng một tập phiên** ở cả 3 chế độ.
- **Chỉ số, dùng bộ số ví dụ của spec (609 phiên, 17 key events):**
  - thời lượng tương tác TB = 137.667 / 609 ≈ **226 giây**, không phải 1.137;
  - key events/100 phiên = 2,79;
  - **session key event rate = 15/609 = 2,46%**, khác với 17/609.
- **Không có số và lỗi:**
  - 0 phiên thì rate = None;
  - kỳ trước bằng 0 thì báo `NO_BASELINE` thay vì ±∞;
  - mẫu nhỏ thì báo `LOW_SAMPLE_SIZE`;
  - lỗi 403 cho trạng thái `ERROR` với dữ liệu rỗng, không trả về 0;
  - metric không tương thích thì báo `METRIC_INCOMPATIBLE`;
  - rate bằng 0 thật vẫn là 0, không bị đổi thành None (đây là lỗi GA4 bỏ dòng toàn số 0, đã sửa).
- **Khác:** bộ lọc quốc gia được gắn vào mọi truy vấn; `(not set)` giữ thành dòng riêng; khoảng so sánh dài bằng khoảng chính; tuần ISO vắt qua năm và tuần chưa trọn; cache trả kết quả đúng và đổi bộ lọc thì tạo key mới.

## 4. Chạy thật và đối soát (GA4 `properties/288379033`, 01/08–29/10/2026)

| Kiểm tra | Kết quả |
|---|---|
| Phiên AI (HYBRID) | **635** = 621 native + 12 nguồn ghi tắt + 2 `chatgpt.com/zalo`, khớp danh sách nguồn ở R0 |
| Tổng các nguồn = tổng AI | 546 + 81 + 4 + 3 + 1 = **635**, không có `GA4_TOTAL_DISCREPANCY` |
| AI trả phí (loại khỏi AI) | 113 phiên |
| Session key event rate với key events/100 phiên | **2,20%** với **2,83**, khác nhau đúng như spec cảnh báo (Looker cũ gọi con số 2,8 là "conversion rate") |
| Tỷ lệ AI | 0,34% tổng site (188.382 phiên) · 0,80% nhóm organic (79.116 phiên) |
| So với 90 ngày trước | +63,66% |

## 5. Hạn chế và việc còn mở

- **Event có dấu cách ("Click Zalo", "Click Messenger") không lấy được tỷ lệ phiên riêng**: GA4 không nhận tên metric `sessionKeyEventRate:Click Zalo`. Số lần event vẫn đếm được (Click Zalo: 12). Muốn có tỷ lệ phiên thì phải đổi tên event trong GTM thành `click_zalo`, nhưng làm vậy lịch sử sẽ bị tách đôi theo tên cũ và mới.
- **Trang đích `(not set)`: 49 phiên AI, engagement 6%.** Nhiều khả năng là phiên không có page_view đầu tiên. Cần kiểm tra cấu hình tag trước khi kết luận.
- **Trang đích trong GA4 không có `/` cuối** (`/gong-kinh`), còn GSC thì có (`/gong-kinh/`). R4 sẽ chuẩn hóa để ghép hai nguồn, nhưng vẫn giữ URL gốc của từng nguồn.
- **GA4 theo giờ Asia/Saigon, GSC theo giờ Pacific.** Chưa ghép dữ liệu theo ngày; sẽ xử lý ở R4.
- Chưa dùng `checkCompatibility` trước mỗi truy vấn. Các trường đã được kiểm tra một lần bằng metadata ở R0, và lỗi 400 được bắt riêng thành `unsupported`.

## 6. Đề xuất R2

Màn **AI Search & GEO** gồm tab Tổng quan và tab Nguồn AI:
- dùng chung bộ lọc kỳ và kỳ so sánh, lưu trên URL;
- có thẻ KPI, biểu đồ AI so với Organic, bảng nguồn và bảng nguồn chi tiết;
- có đủ các trạng thái loading/empty/error, cảnh báo và thông tin nguồn dữ liệu;
- thêm khối "AI traffic" vào báo cáo tuần cho sếp.
