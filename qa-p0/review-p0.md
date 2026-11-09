# Gói review: Dashboard P0 (B1–B5)

Ngày 06/11/2026 · nhánh `multi-site` · **chưa commit, chưa push, chưa làm P1**.

## 1. Tóm tắt theo hạng mục

| ID | Kết quả | Ghi chú |
|---|---|---|
| **B1** KPI lên đầu + khung giữ chỗ | Đạt | KPI nằm ngay dưới "Cần xử lý" (khách: đứng đầu trang). Trong lúc chờ có khung giữ chỗ đúng số ô (4 ô = 4 cam kết). Đo chiều cao khối lúc chờ và lúc có số: 216px → 216px, trang không nhảy. Không có KPI: người sửa được thấy thẻ "Tạo KPI cam kết", khách / Team xem không thấy gì. KPI lỗi: "Chưa tính được tiến độ KPI lúc này." |
| **B2** Nhãn loại thời gian | Đạt | Kỳ cuộn: "Hiệu suất · N ngày gần nhất (…) so với N ngày trước đó". Tháng dự án: "Tiến độ KPI · Tháng dự án n/N". Snapshot: Thứ hạng "Lần check mới nhất dd/mm", Index "Lần kiểm tra mới nhất của N URL đã kiểm tra (không phải toàn site)", Backlink "Lần lấy mới nhất … thay đổi so với lần lấy dd/mm", OKR "Đợt … · tính đến hôm nay". Không ô snapshot nào ghi "so với N ngày trước". |
| **B3** Mẫu số thứ hạng | Đạt (có sửa thêm) | Ghi "đã check X/Y", "Trên Y từ khóa theo dõi", báo số từ khóa chưa check nếu có. Có thêm dòng Top N theo KPI. **Sửa trong vòng review:** dòng KPI ghi sai "lần check cuối tháng" khi tháng dự án còn đang chạy; nay ghi "lần check mới nhất trong tháng, tháng đang chạy" (tháng đã chốt mới ghi "lần check cuối tháng"). |
| **B4** Biểu đồ nhỏ 90 ngày | **Làm lại** | Bản trước bỏ 6 ngày đầu, nên biểu đồ chỉ còn 84 ngày trong khi số tổng tính 90 ngày. Bản mới: **mỗi ngày một điểm ở cả 7 / 28 / 90 ngày**. Lý do không gộp tuần: 90 không chia hết cho 7, nên gộp tuần thì hoặc có tuần thiếu ngày (cột thấp giả), hoặc phải chia trung bình theo ngày, khiến đơn vị trên trục lệch với số tổng. Điểm theo ngày giữ đủ 90 ngày, khớp số tổng, và tooltip đã ghi đúng ngày. Kỳ so sánh cũng 90 điểm, điểm thứ i của hai kỳ cách nhau đúng 90 ngày. |
| **B5** Bỏ nút trả phí | Đạt | Đã xóa `fetch_backlinks` và nút "Lấy số mới" của Backlink trên Tổng quan. Câu khi chưa có số chuyển người dùng sang màn Backlink. Có test tĩnh và test chặn kết nối (mục 3). |

**Sửa thêm ngoài P0, phát hiện khi QA:** trên điện thoại, khối Thứ hạng làm trang tràn ngang: trang rộng 749px trên màn 375px. Nguyên nhân là dòng KPI mới (700px) và dòng AI Overview đã có từ trước (444px), cả hai không xuống dòng. Đã cho xuống dòng, chỉ áp dụng trong khối này.

## 2. File và hàm đã đổi (chỉ phần P0)

| File | Thay đổi |
|---|---|
| `seo_report/web_dashboard.py` | `buckets()` làm lại (mỗi ngày một điểm). Thêm `kpi_rank_line(p)`. Trong `build_dashboard_page`: khối KPI và khung giữ chỗ đưa lên sau `todo_section`; thêm `kstate`; thêm `rank_card()` dạng refreshable thay cho khối thứ hạng cũ; tiêu đề "Hiệu suất · …"; dòng phụ Index, Backlink, OKR; bỏ `fetch_backlinks` và nút; `load_kpi()` thay khung giữ chỗ bằng số thật / thông báo lỗi rồi gọi `rank_card.refresh()`; xóa `kpi_box` cũ ở cuối trang; thêm khung `sr-wrap-notes` |
| `seo_report/web_kpi.py` | `kpi_block`: tiêu đề "Tháng" → "Tháng dự án" (đổi cả ở màn Báo cáo và KPI cam kết) |
| `seo_report/ui_theme.py` | Thêm `.sr-wrap-notes` (2 dòng CSS) |
| `tests/test_report.py` | `test_windows_and_buckets`: 90 ngày phải có đủ 90 điểm, từ ngày đầu đến ngày cuối kỳ |
| `tests/test_dashboard_buckets.py` (mới) | Mỗi kỳ 7 / 28 / 90 ngày phủ đúng từng ngày, không thiếu / thừa / trùng; kỳ trước thẳng hàng 1–1 và liền kỳ này; `kpi_rank_line` cho tháng đang chạy, tháng đã chốt, không có số |
| `tests/test_dashboard_no_paid.py` (mới) | Kiểm tra tĩnh và chạy thật: không gọi API trả phí (mục 3) |

**Lưu ý khi đọc `git diff`:** cây làm việc còn nhiều thay đổi chưa commit từ các việc **trước P0**: mở rộng Search Console, Merchant Center, hiệu ứng rê chuột, thẻ báo cáo, thẻ thứ hạng… `web_kpi.py` có 2 thay đổi cũ trong `_tile` (số mờ, nhãn `sr-tile-label`) thuộc đợt đồng bộ thẻ trước đó, không phải P0. `ui_theme.py` có khoảng 160 dòng thay đổi, P0 chỉ chiếm 2 dòng `.sr-wrap-notes`. Nên commit P0 riêng: `git add -p` hoặc commit theo nhóm file.

`git diff --numstat` (4 file đã theo dõi có phần P0):

| File | Thêm / bớt | Phần thuộc P0 |
|---|---|---|
| `web_dashboard.py` | +99 / −53 | Toàn bộ |
| `web_kpi.py` | +6 / −6 | 1 dòng đổi tiêu đề |
| `ui_theme.py` | +138 / −23 | 2 dòng thêm |
| `tests/test_report.py` | +2 / −1 | Toàn bộ |

Thêm 2 file test mới chưa theo dõi: `test_dashboard_buckets.py`, `test_dashboard_no_paid.py`.

## 3. Kết quả test

- `python -m unittest discover -s tests`: **357 test, OK, 0 bỏ qua, 0 lỗi**.
- Các test mới / sửa liên quan P0:
  - `test_dashboard_buckets`: 4 test (phủ ngày 7 / 28 / 90, thẳng hàng kỳ trước, `kpi_rank_line` 2 test).
  - `test_report.DashboardWindowTest`: viết lại theo hành vi mong muốn (đủ 90 ngày).
  - `test_dashboard_no_paid`: 4 test.
    - Tĩnh: `build_dashboard_page`, `rank_snapshot`, `index_snapshot`, `kpi_rank_line`, `health_strip`, `todo_section`, `dashboard_lines`, `web_aio.load` không gọi hàm trả phí nào trên module `backlinks / rank / volume / intent`.
    - Đối chứng: bộ dò bắt được `BL.refresh`.
    - Chạy thật: chặn mọi kết nối HTTPS tới `*dataforseo*` và mọi `urlopen` của các module trả phí, rồi chạy các hàm đọc số trên DB tạm. Kết quả: 0 lần gọi.
    - Đối chứng: `backlinks.Client._live` bị bộ chặn ghi nhận đúng 1 lần.

## 4. QA trên trình duyệt

Bản QA riêng ở cổng 8092. Dữ liệu là **bản sao** của `data/seo.db` (Tâm Đức), DB thật không bị ghi. Có tham số giả lập vai trò, độ trễ KPI, KPI thiếu / lỗi, GA4 thiếu / lỗi. Mọi kết nối HTTPS tới `*dataforseo*` bị chặn và ghi lại ở trang `/calls`.

### 4.1 Vai trò (đọc tiêu đề các khối trên trang)

| Vai trò | Khối hiển thị | Chỉ báo dữ liệu | Nút |
|---|---|---|---|
| Chủ tool (`local`) | Cần xử lý · KPI · Hiệu suất · Thứ hạng · Index · Backlink · OKR | Có | Không có nút nào trong nội dung |
| Được sửa (`editor`) | Giống Chủ tool | Có | Không |
| Team xem (`viewer`) | KPI · Hiệu suất · Thứ hạng · Index · Backlink · OKR | Không | Không |
| Khách hàng (`client`) | KPI · Hiệu suất · Thứ hạng · Backlink · OKR (**không Index**) | Không | Không |

Không có KPI: Chủ tool thấy thẻ "Tạo KPI cam kết"; khách hàng không thấy khối KPI.

### 4.2 Số liệu và khung thời gian

Đối chiếu tổng các điểm biểu đồ (đọc từ biểu đồ đang hiển thị) với số chính và số kỳ trước trên ô:

| Kỳ | Số điểm (kỳ này / kỳ trước) | Khoảng ngày trên trục | Tổng biểu đồ = số trên ô |
|---|---|---|---|
| 7 ngày | 7 / 7 | 28/10–03/11 | Click 5.068 = 5.068; kỳ trước 5.000 = 5.000; đủ 5 ô |
| 28 ngày | 28 / 28 | 07/10–03/11 | Click 20.144; Hiển thị 716.869; Mọi kênh 62.939; Organic 23.434; AI 225: đều khớp, cả kỳ trước |
| 90 ngày | 90 / 90 | 06/08–03/11 (đúng khoảng trên tiêu đề) | Click 66.153; Hiển thị 2.132.517; Mọi kênh 185.737; Organic 70.407; AI 653: đều khớp, cả kỳ trước |

- **Mẫu số thứ hạng**, đối chiếu riêng bằng một script đọc DB, không dùng `rank_snapshot`: 69 từ khóa không trùng, không có bộ nháp. Khớp "đã check 69/69", "Top 3 10/69 · Top 5 12/69 · Top 10 20/69".
- **Dòng KPI**: Top 3 9/50 · Top 5 11/50 · Top 10 15/50 (bộ cam kết 50 từ). Khớp các ô KPI 18% (9/50), 22% (11/50), 30% (15/50).

### 4.3 Trạng thái đang tải / trống / lỗi

| Trạng thái | Kết quả |
|---|---|
| KPI trễ 10 giây | Khung giữ chỗ 4 ô (12 thanh skeleton). Sau khi số về: 4 ô thật, chiều cao khối 216px → 216px |
| KPI không cấu hình | Chủ tool: thẻ "KPI cam kết · Dự án chưa có KPI cam kết · Tạo KPI cam kết →". Khách: không có khối |
| KPI lỗi | "Tiến độ KPI cam kết · Tháng dự án · Chưa tính được tiến độ KPI lúc này." Dòng KPI trong khối Thứ hạng ẩn |
| GA4 chưa gắn | 3 ô GA4 "chưa có · Chưa kết nối GA4". KPI vẫn hiện phần thứ hạng, ô phiên ghi "Chưa kết nối GA4" |
| GA4 lỗi (property sai) | 3 ô GA4 "chưa có · Không lấy được số GA4". **KPI chuyển sang "Chưa tính được tiến độ"** (xem rủi ro R1) |

### 4.4 Bố cục

`scrollWidth = clientWidth` (không tràn ngang) ở 375 (giả lập điện thoại), 800, 1100, 1440px. Lưới 6 ô số: 1 / 2 / 2 / 3 cột tương ứng.

### 4.5 Màn Báo cáo và KPI cam kết (bản thật, cổng 8080)

- `/report`: tiêu đề "Tiến độ KPI · Tháng dự án 2/6 · SEO matkinhtamduc.com", 4 ô, không có lỗi console.
- `/kpi`: tiêu đề "Tiến độ KPI · Tháng dự án 1/12", 4 ô, bảng cả dự án hiện đủ, không có lỗi console.

### 4.6 Lần gọi DataForSEO

Trang `/calls` của bản QA ghi **0** lần, sau khi đã mở trang khoảng 15 lần với đủ vai trò, kỳ, trạng thái, và bấm mọi phần tử bấm được trên trang (3 ô có link).

### 4.7 Ảnh chụp (thư mục `qa-p0/`)

Chụp bằng Edge chạy ẩn trên bản QA. Lưu ý: Edge chạy ẩn không chờ server trả số nên **vài ảnh chụp lúc GA4 / KPI còn đang tải**; tên file ghi rõ khi đó là trạng thái đang tải. Trạng thái lỗi được xác minh bằng chữ đọc từ trang (mục 4.3), không có ảnh.

| File | Nội dung |
|---|---|
| `team-28d-1440.png` | Chủ tool, 28 ngày, đã tải đủ |
| `team-90d-1440.png` | Chủ tool, 90 ngày |
| `viewer-7d-1100.png` | Team xem, 7 ngày, 1100px |
| `client-28d-kpidangtai-1440.png` | Khách hàng: không có Cần xử lý / Index / chỉ báo dữ liệu; KPI đang tải |
| `team-kpi-loading-1440.png` | Khung giữ chỗ KPI (KPI trễ 60 giây) |
| `team-no-kpi-1440.png` | Không có KPI: thẻ "Tạo KPI cam kết" |
| `team-ga4dangtai-1440.png` | Ô GA4 lúc đang tải |

Không có ảnh điện thoại: cửa sổ Edge chạy ẩn không thu nhỏ được dưới khoảng 500px nên ảnh 375px bị cắt, mình đã xóa. Bố cục điện thoại được kiểm tra bằng đo DOM (mục 4.4).

## 5. Vấn đề còn lại và rủi ro

| # | Vấn đề | Mức | Đề xuất |
|---|---|---|---|
| R1 | Khi GA4 lỗi (khác với chưa gắn GA4), `KP.progress` lỗi cả khối nên mất luôn phần thứ hạng của KPI. Đây là **lỗi có từ trước**: trước P0 khối KPI im lặng biến mất, giờ hiện thông báo | Trung bình | Bắt lỗi GA4 bên trong `KP.ga4_sessions` / `progress` để vẫn chấm phần thứ hạng (ngoài P0) |
| R2 | Màn Báo cáo ghi "Tháng dự án 2/6", màn KPI ghi "Tháng dự án 1/12" cho cùng dự án. Có vẻ Báo cáo dùng phiên bản KPI có hiệu lực ở cuối kỳ báo cáo, còn màn KPI dùng phiên bản hiện hành. **Có từ trước P0** (P0 chỉ đổi chữ "Tháng" → "Tháng dự án") | Cần xác minh | Kiểm tra `version_at` theo ngày ở `web_overview` / `web_kpi` |
| R3 | Biểu đồ theo ngày ở chế độ 90 ngày nhìn nhiễu hơn (thấy rõ nhịp ngày thường / cuối tuần) | Thấp (đổi lấy độ chính xác) | Nếu cần mượt hơn: làm đường trung bình 7 ngày làm lớp phụ, vẫn giữ đủ 90 điểm. Để P1 quyết định |
| R4 | Ô "Tỷ lệ hiện trong AI" vẫn có thể dùng cửa sổ ngày khác các ô cùng hàng khi file AI về trễ. Đã ghi "Số đến dd/mm" | Có từ trước | Mục #6 trong spec, để P1 |
| R5 | QA vai trò chạy trên bản QA (gọi trực tiếp `build_dashboard_page` với người dùng giả), chưa đăng nhập bằng tài khoản Khách hàng thật trên cổng 8080. Phần chặn quyền ở server (`open_page`) không đổi trong P0 | Thấp | Nếu cần: thử bằng một tài khoản khách thử nghiệm trên localhost |
| R6 | Nhánh "có từ khóa chưa check" (mẫu số lớn hơn số đã check) chưa gặp với dữ liệu thật (69/69 đã check). Logic hiển thị đơn giản, chưa có test giao diện | Thấp | Thêm dữ liệu mẫu khi làm P1 |

## 6. Việc chưa làm (theo yêu cầu)

- Không commit, không push.
- Chưa bắt đầu P1.
- Thư mục `qa-p0/` và 2 file đặc tả `.md` ở thư mục gốc chưa được theo dõi bởi git. Bỏ khỏi commit nếu không muốn đưa vào repo.
