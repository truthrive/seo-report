# R4 REPORT — Cơ hội SEO/GEO

Ngày: 30/10/2026 · Trạng thái: **xong, đã thử trên dữ liệu thật (GA4 + GSC, 28 ngày, 02/10–29/10)**

## 1. File thay đổi

| File | Thay đổi |
|---|---|
| `seo_report/ai_opportunities.py` | **Mới.** Gồm các phần sau:<br>• Ghép URL GA4 AI với GSC Web: `align`, `_match_ga4_path`.<br>• GSC theo URL, lấy từ SQLite của tool: `gsc_by_url`.<br>• 3 quy tắc: `rules`.<br>• Ngưỡng lưu trong `app_settings`, mỗi lần đổi ghi `change_log`: `get_thresholds` / `set_thresholds`.<br>• `build` trả về các dòng URL, gợi ý, ngưỡng và cảnh báo. |
| `seo_report/web_ai.py` | Thêm tab **Cơ hội SEO/GEO**, chỉ tải khi mở tới. Tab gồm:<br>• thẻ giải thích GSC Web;<br>• gợi ý gom theo quy tắc;<br>• khối chỉnh ngưỡng;<br>• bảng URL hai nhóm cột;<br>• 2 nút tải CSV. |
| `seo_report/ai_export.py` | Excel thêm 2 sheet: **Cơ hội - gợi ý** và **Cơ hội - URL**. |
| `seo_report/ai_format.py` | Thêm 2 tên cảnh báo: `TIMEZONE_MISMATCH`, `URL_MATCH_AMBIGUOUS`. |
| `tests/test_ai.py` | Thêm 6 test, lớp `R4OpportunityTest`. |

## 2. Hợp đồng dữ liệu

**Mỗi dòng URL gồm:**
- **Định danh:** `url`, `type`, `ga4_paths`, `ambiguous`.
- **`match`**, nhận một trong ba giá trị: `matched`, `ga4_only` hoặc `gsc_only`.
- **Nhóm GA4 AI:** `ai_sessions`, `ai_engaged`, `ai_engagement_rate`, `ai_key_events`, `ai_session_key_event_rate`.
- **Nhóm GSC Web:** `gsc_clicks`, `gsc_impressions`, `gsc_ctr`, `gsc_position`.

**Mỗi gợi ý gồm:** `rule_id`, `url`, `type`, `title`, `evidence`, `threshold`, `severity`, `confidence`, `verification`, `action`, `source`, `data_period`.

**Quy tắc ghép và tính số:**
- **Không có phép tính nào trộn hai nguồn.** Số GA4 và số GSC chỉ đặt cạnh nhau.
- **Nhiều đường dẫn GA4 trỏ về cùng một URL** (ví dụ có và không có `/` cuối):
  - các số đếm được cộng lại;
  - engagement rate tính lại từ số đếm;
  - session key event rate để trống, vì không cộng được;
  - dòng đó có nhãn "ghép nhiều đường dẫn".
- **`(not set)` không ghép với GSC.** GA4 không ghi nhận trang đầu tiên của các phiên này.
- **Vị trí TB của GSC là trung bình có trọng số theo impression.** Cột này chỉ để tham khảo; thứ hạng nghiệm thu vẫn xem ở màn Check rank.

## 3. Ba quy tắc và ngưỡng mặc định

Ngưỡng chỉnh được trên màn hình. Mỗi lần lưu, tool ghi lại người sửa.

| Quy tắc | Điều kiện mặc định | Mức | Độ tin cậy |
|---|---|---|---|
| `AI_REFERRAL_WITH_LOW_GSC_VISIBILITY` | ≥ 5 phiên AI và < 100 impression GSC Web | trung bình | theo cỡ mẫu: < 20 thấp, 20–49 trung bình, ≥ 50 cao |
| `AI_ENGAGEMENT_WEAK` | ≥ 20 phiên AI và engagement thấp hơn mức chung của AI từ 15 điểm % | trung bình | theo cỡ mẫu |
| `GSC_HIGH_IMPRESSIONS_LOW_AI_REFERRAL` | ≥ 5.000 impression GSC Web và ≤ 1 phiên AI | thấp | trung bình |

Về cách đặt tên quy tắc thứ ba: tool **không** gọi đây là "thiếu trích dẫn AI Overviews". Tool không đo được lượt trích dẫn. Phần "cách kiểm chứng" của quy tắc này nói rõ điều đó.

## 4. Kiểm tra trên dữ liệu thật (02/10–29/10)

| Kiểm tra | Kết quả |
|---|---|
| Đối soát phiên AI | 196 phiên ghép theo URL + 25 phiên `(not set)` = **221**, khớp tổng KPI ở tab Tổng quan |
| Kết quả ghép | 76 URL có cả hai nguồn (194 phiên AI). 2 URL chỉ có phiên AI (2 trang sản phẩm, mỗi trang 1 phiên, GSC chưa ghi nhận). 452 URL chỉ có GSC (trong 500 URL nhiều impression nhất) |
| Gợi ý | **44** gợi ý, đều thuộc quy tắc `GSC_HIGH_IMPRESSIONS_LOW_AI_REFERRAL`: Blog 36, Danh mục con 5, Danh mục 2, Cửa hàng 1 |
| Engagement AI yếu | 0 gợi ý. Chỉ trang chủ đủ 20 phiên, engagement 73%, cao hơn mức chung 59% |
| Giao diện | Tab tải được, không có lỗi console. Có thẻ giải thích GSC, cảnh báo lệch múi giờ, gợi ý gom theo quy tắc, bảng hai nhóm cột (xanh lá: GA4 AI, xanh dương: GSC Web) |

Test: `python -m unittest` **PASS**, 85 test (79 cũ + 6 mới).

### Lỗi phát hiện nhờ dữ liệu thật, đã sửa

**Triệu chứng:** lần chạy đầu ra 2 gợi ý "AI dẫn tới nhưng ít hiển thị Google" cho `/gong-kinh` và `/bang-gia-trong-kinh-can`. Cả hai đều **sai**.

**Nguyên nhân:**
- Site chuyển hướng 308 từ `/gong-kinh` sang `/gong-kinh/`.
- Trong dữ liệu GSC của tool vẫn còn bản không có `/` cuối, với vài impression.
- Tool đã ghép phiên AI vào bản cũ đó, thay vì vào trang thật có hàng chục nghìn impression.

**Cách sửa:** đường dẫn GA4 không có `/` cuối thì khớp với bản có `/` trước. Đã thêm test cho trường hợp này.

## 5. Phát hiện từ dữ liệu (để báo cáo sếp)

- **Blog là điểm trống lớn nhất về GEO.**
  - 36 bài blog có trên 5.000 impression Google trong 28 ngày nhưng gần như không có phiên nào từ AI assistant. Ví dụ: "cách sửa gọng kính bị gãy" 17.675 impression, "cách đọc kết quả đo mắt" 14.844.
  - Đây là các chủ đề người dùng hay hỏi ChatGPT.
  - Đề xuất: thử hỏi ChatGPT/Gemini 5–10 chủ đề này, xem AI có nhắc tới Tâm Đức không, rồi bổ sung câu trả lời trực tiếp và số liệu cụ thể vào bài.
- **AI dẫn traffic chủ yếu tới trang thương mại**: trang chủ, Cửa hàng, Gọng kính, Bảng giá tròng kính. Tương tác tốt, ví dụ `/gong-kinh/` có engagement 88%.

## 6. Hạn chế

- **Mẫu nhỏ.** Phần lớn trang chỉ có 1–9 phiên AI trong 28 ngày, nên quy tắc engagement gần như chưa kích hoạt. Kỳ 90 ngày sẽ đủ mẫu hơn.
- **GSC Web không tách được AI Overviews / AI Mode.** Đây là giới hạn của API, không phải của tool. Nếu muốn có số impression riêng của AI Overviews thì làm R6 (nhập CSV từ báo cáo Generative AI của GSC).
- **Bộ lọc nguồn/quốc gia chỉ áp cho cột GA4.** Cột GSC luôn là toàn site vì GSC không có các chiều này.
- **Lệch múi giờ.** GSC tính ngày theo giờ Pacific, GA4 theo giờ Việt Nam. Màn hình luôn hiện cảnh báo này.

## 7. Đề xuất R5

Tab **Chất lượng dữ liệu & Cài đặt**, gồm:
- danh sách nguồn AI và allowlist;
- trạng thái kết nối GA4/GSC;
- số phiên `(not set)`;
- ẩn % thay đổi khi kỳ trước có dưới 10 phiên;
- lưu bộ lọc trên URL;
- QA đầu cuối và ảnh màn hình.
