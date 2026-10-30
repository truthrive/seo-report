# R5 REPORT — Chất lượng dữ liệu, QA, hoàn thiện

Ngày: 30/10/2026 · Trạng thái: **xong, đã thử trên dữ liệu thật**

## 1. File thay đổi

| File | Thay đổi |
|---|---|
| `seo_report/ai_quality.py` | **Mới.** Gồm:<br>• `connections`: quyền đã cấp, property GA4, múi giờ, key events, trường GA4 còn thiếu. Không đọc hay hiện token.<br>• `ga4_checks`: đối soát tổng KPI với tổng của bảng nguồn, trang đích và quốc gia; kiểm tỷ lệ nằm trong 0–1; đếm phiên `(not set)`; phát hiện bảng bị cắt dòng; gom các cảnh báo GA4.<br>• `source_inventory`: phiên AI theo cách nhận diện (native / fallback / nguồn chưa có trong danh sách).<br>• `candidate_sources`: nguồn có tên giống AI trên toàn bộ traffic nhưng không được tính là AI, kèm lý do.<br>• `gsc_status`: GSC có dữ liệu tới ngày nào, ngày bị thiếu trong 30 ngày, trạng thái AI Overviews "Not available".<br>• `daily_job_status`: lần chạy gần nhất của lịch hằng ngày.<br>• `cache_status`: tình trạng cache GA4. |
| `seo_report/web_ai.py` | • Thêm tab **Chất lượng dữ liệu**.<br>• Bộ lọc và tab đang mở được ghi lên địa chỉ trang (`state_from_params` / `params_from_state`); giá trị sai thì quay về mặc định.<br>• Gom phần tải chậm của các tab vào bảng `LAZY`. |
| `seo_report/web.py` | Trang `/ai` đọc tham số trên địa chỉ trang. |
| `seo_report/ai_format.py` | `delta_pct(v, base)`: khi kỳ trước < `MIN_BASE` (10) thì hiện "kỳ trước N" thay vì %. |
| `seo_report/report.py`, `web_report.py`, `report_excel.py` | Báo cáo tuần (màn hình và Excel) áp dụng cùng quy tắc ẩn %. |
| `README.md` | Hướng dẫn sáu tab của màn AI, link giữ bộ lọc, quy tắc ẩn %. |
| `tests/test_ai.py` | Thêm 8 test (lớp `R5QualityTest`). FakeGA4 hỗ trợ thêm `PARTIAL_REGEXP`. |

## 2. Quyết định và phản biện so với spec

- **Danh sách nguồn AI và key event chỉ cho xem, chưa cho sửa trên màn hình.**
  - Spec §3.7 chỉ cho sửa "khi đã có hạ tầng cài đặt và phân quyền". Tool chưa có đăng nhập và vai trò (bước 7).
  - Sửa danh sách này làm thay đổi số AI của mọi kỳ, kể cả các báo cáo đã gửi sếp.
  - Ngưỡng của quy tắc cơ hội vẫn sửa được ở tab Cơ hội (từ R4), vì chỉ ảnh hưởng tới gợi ý, không ảnh hưởng số liệu.
- **Tab Chất lượng dữ liệu luôn đối soát trên toàn bộ phiên AI của kỳ**, bỏ qua bộ lọc nguồn, quốc gia và trang. Mục đích là để biết số gốc có đúng không, chứ không phải kiểm tra một lát cắt.
- **Tiêu chí "Không có dữ liệu AI trên Google Search thì không được hiện 0"** (spec §8, mục 5) đã đạt: tab hiện dòng "Impression AI Overviews / AI Mode: chưa có (Not available)". Mọi cột GSC đều ghi là Google Web Search tổng.

## 3. Kiểm tra trên dữ liệu thật

Kỳ 02/10–29/10:

| Kiểm tra | Kết quả |
|---|---|
| Kết nối | Đủ quyền đọc. GA4 "Tâm Đức – GA4", giờ Asia/Saigon, VND. Đủ trường GA4. GSC URL-prefix |
| Độ mới | GSC có tới 29/10 (trễ 1 ngày), đủ ngày trong 30 ngày qua. Lịch hằng ngày chạy lúc 08:55 ngày 30/10. Cache 123 truy vấn |
| Đối soát tổng | KPI 221 = bảng nguồn 221 = bảng trang đích 221. Bảng quốc gia 222 (lệch 1, mức "thông tin") |
| Tỷ lệ | 84 dòng × 2 tỷ lệ, đều nằm trong 0–100% |
| Trang đích không xác định | 25 phiên (11,3%) |
| Nguồn AI | 221 phiên qua kênh native, 0 qua fallback, 0 từ nguồn chưa có trong danh sách |
| Nguồn giống AI nhưng không tính | Chỉ có `chatgpt / paid` 115 phiên (quảng cáo, theo quyết định R0). Không có nguồn AI nào bị bỏ sót |
| Link giữ bộ lọc | Mở `/ai?preset=90&source=GEMINI&tab=nguon` thì màn hiện đúng kỳ 90 ngày, nhãn "Nguồn: Gemini" và tab Nguồn AI. Đổi bộ lọc hay tab thì địa chỉ trang tự cập nhật |
| Ẩn % khi kỳ trước nhỏ | Bảng nguồn 90 ngày: Perplexity "kỳ trước 4", Claude "kỳ trước 2". Báo cáo tuần: Key events "kỳ trước 0" |
| Báo cáo tuần | Vẫn hiện đủ: KPI GSC, khối AI, rank, top tăng/giảm |

**Vì sao bảng quốc gia ra 222 khi KPI là 221:** GA4 có thể ghi một phiên ở hai quốc gia, ví dụ khi người dùng đổi mạng giữa phiên. KPI là số chuẩn. Tool không cộng hay sửa số từ bảng chi tiết.

**Test:** `python -m unittest` **PASS**, 93 test. Trong đó 8 test mới:
- tổng khớp;
- phát hiện lệch tổng và tỷ lệ sai (ví dụ 73,08 thay vì 0,7308);
- lỗi API hiện thành lỗi, không hiện thành 0;
- danh mục nguồn và nguồn giống AI;
- GSC thiếu ngày và trạng thái "Not available";
- cache tách riêng theo từng property GA4;
- ẩn % khi kỳ trước nhỏ;
- link giữ bộ lọc, kể cả khi tham số sai.

### Lỗi gặp khi kiểm tra giao diện, đã sửa

- **Tab Chất lượng hiện "Lỗi hiển thị: TypeError".** Nguyên nhân: gọi `ui.icon` sai kiểu tham số. Nhờ có lớp `safe()` nên lỗi hiện ra trên màn thay vì để trống trang.
- **Kiểm tra ngày GSC bị thiếu báo nhầm cả những ngày trước khi tool bắt đầu lấy dữ liệu.** Giờ chỉ tính từ ngày đầu tiên có dữ liệu.

## 4. Đối chiếu tiêu chí hoàn thành (spec §8)

| # | Tiêu chí | Trạng thái |
|---|---|---|
| 1 | Ít nhất 5 màn P0, mở được từ menu | **Đạt.** 6 tab trong màn AI Search & GEO, cộng khối AI trong báo cáo tuần |
| 2 | Kết nối GSC/GA4 cũ không bị ảnh hưởng, test cũ pass | **Đạt.** 93/93 test. Lịch hằng ngày vẫn chạy |
| 3 | Bảng nguồn, biểu đồ và KPI dùng cùng một định nghĩa kênh, có ghi nguồn gốc số liệu | **Đạt.** Một bộ lọc phân loại HYBRID v1; mỗi bảng ghi property, phân loại và thời điểm truy vấn |
| 4 | Không cộng `sessionKeyEventRate` / thời lượng giữa các nguồn | **Đạt.** Có test theo ví dụ của spec (226 giây, không phải 1.137 giây) |
| 5 | AI trên Google Search không hiện 0 khi chưa có dữ liệu | **Đạt.** Hiện "Not available" |
| 6 | Xử lý lỗi và quyền, xuất file, tách dữ liệu giữa các property | **Đạt.** Có thêm test cache theo property |
| 7 | Báo cáo QA có danh mục nguồn, các kiểm tra, hạn chế, ảnh màn hình | **Đạt.** Các file R1–R5. Ảnh màn hình chụp trong lúc kiểm tra, chưa lưu thành file |

## 5. Hạn chế còn lại

- Chưa có đăng nhập và phân quyền (bước 7). Vì vậy danh sách nguồn AI chỉ xem được, và nhật ký thay đổi ghi tên người dùng Windows.
- Excel chưa có sheet Chất lượng dữ liệu. Sheet Thông tin đã ghi các cảnh báo. Có thể bổ sung nếu sếp cần.
- Trạng thái lịch hằng ngày dựa vào thời điểm file nhật ký được ghi lần cuối. Tool chưa đọc trạng thái từ Task Scheduler.
- Không còn ảnh tham chiếu PDF. Số liệu trong spec chỉ dùng để thiết kế test, không dùng để nghiệm thu.

## 6. Bước tiếp theo (cần quyết định)

- **R6, không bắt buộc:** nhập CSV báo cáo Generative AI của GSC để có impression AI Overviews / AI Mode.
  - Chỉ có impression, chỉ xuất được bằng tay từ giao diện GSC.
  - Trong file xuất, ô "~" và "-" bị ghi thành 0; tool phải coi đó là "không có số", không phải 0.
- **Bước 7 của lộ trình chính:** đưa lên VPS, đăng nhập Google, vai trò Admin/Editor/Viewer, sao lưu. Làm xong bước này thì mới mở sửa danh sách nguồn AI trên màn hình.
