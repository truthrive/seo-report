# Dashboard UX Architecture & Redesign Specification: SEO Report

> Phạm vi: màn **Tổng quan** (`/`). Tài liệu này chỉ đặc tả, chưa sửa code.
> Căn cứ:
> - [web_dashboard.py](seo_report/web_dashboard.py), [web_overview.py](seo_report/web_overview.py) (`health_strip`, `todo_section`, `rank_overview`), [web_kpi.py](seo_report/web_kpi.py), [kpi.py](seo_report/kpi.py), [ui_theme.py](seo_report/ui_theme.py), [web.py](seo_report/web.py)
> - [README.md](README.md), [product-context-report.md](product-context-report.md)
>
> Nhãn:
> - **[HIỆN TẠI]**: hành vi đã xác minh trong code.
> - **[ĐỀ XUẤT]**: thay đổi đề nghị.
> - **[RỦI RO]**: rủi ro người xem hiểu sai số liệu.

Định vị sản phẩm: nền tảng tự host, nhiều website, để theo dõi hiệu suất SEO/GEO, theo dõi KPI cam kết, vận hành SEO và báo cáo cho khách. Không phải chỉ là tool check rank.

---

## 0. Ba loại thời gian (bắt buộc tách bạch trên giao diện)

| Loại | Định nghĩa [HIỆN TẠI] | Dùng cho | Cách ghi trên UI [ĐỀ XUẤT] |
|---|---|---|---|
| **Kỳ cuộn** (rolling) | 7 / 28 / 90 ngày kết thúc ở **ngày GSC mới nhất** (`K.latest_date`), so với cùng số ngày liền trước (`windows()`) | Click, Hiển thị, Lượt truy cập, Truy cập từ AI, Tỷ lệ hiện trong AI | Nhãn kỳ: "28 ngày · 07/10 – 03/11 so với 09/09 – 06/10" |
| **Tháng dự án** | Từ ngày bắt đầu dự án trong sheet KPI đến trước cùng ngày tháng sau; thứ hạng lấy **lần check cuối trong tháng** (`KP.progress`) | Tiến độ KPI cam kết | "Tháng dự án 2/6 · 01/11 – 30/11 · đang chạy" |
| **Ảnh chụp** (snapshot) | Lần đo / lần lấy mới nhất, **không theo kỳ cuộn**: rank (lần check gần nhất của mỗi từ khóa), index (lần kiểm tra gần nhất của mỗi URL), backlink (lần lấy gần nhất), OKR (hôm nay) | Thứ hạng, Index, Backlink, OKR | "Lần check 04/11", "Lấy ngày 01/11", "so với lần lấy 25/10" |

Quy tắc [ĐỀ XUẤT]:
- Mỗi khối ghi đúng loại thời gian của nó, ngay ở dòng phụ dưới tiêu đề.
- Không đặt ô snapshot chung một hàng với ô kỳ cuộn mà không có nhãn phân biệt.

---

## 1. Mục tiêu & thứ bậc thông tin

### 1.1 Mục tiêu theo đối tượng

| Đối tượng | Câu hỏi trong 30 giây đầu (theo thứ tự) |
|---|---|
| **Team nội bộ** (Chủ tool, Được sửa, Team xem) | 1. Có việc gì phải xử lý ngay không? 2. Số liệu có đủ và mới không? 3. KPI tháng này đang đạt hay thiếu? 4. Traffic tìm kiếm tăng hay giảm, vì sao? 5. Thứ hạng / index / backlink có biến động lớn không? |
| **Khách hàng** | 1. KPI cam kết đang đạt hay thiếu? 2. Traffic từ Google và AI tăng hay giảm? 3. Từ khóa chủ lực đang ở đâu? 4. Team đang làm gì (OKR)? 5. Số liệu tính đến ngày nào? |

### 1.2 Thứ bậc thông tin [ĐỀ XUẤT]

| Cấp | Nội dung |
|---|---|
| **Cấp 1 · Trạng thái** | Cần xử lý (chỉ team) · trạng thái dữ liệu · KPI cam kết tháng dự án |
| **Cấp 2 · Hiệu suất kỳ cuộn** | Nhóm SEO (Click, Hiển thị, Organic) · nhóm GEO (Truy cập từ AI, Tỷ lệ hiện trong AI) · Lượt truy cập mọi kênh (bối cảnh) |
| **Cấp 3 · Ảnh chụp vận hành** | Thứ hạng · Index (chỉ team) · Backlink · Công việc & OKR |

So với hiện tại [HIỆN TẠI], thứ tự đang là: Cần xử lý → 6 ô → Thứ hạng / Index / Backlink / OKR → **KPI ở cuối**, tải nền và chèn vào sau. Đề xuất đưa KPI lên cấp 1.

---

## 2. Thứ tự khối, lưới 12 cột, responsive

### 2.1 Thứ tự & lưới desktop (≥ 1280px) [ĐỀ XUẤT]

| Hàng | Khối | Cột (12) | Ai thấy |
|---|---|---|---|
| R0 | Tiêu đề + nhãn kỳ cuộn + **chip "Số đến dd/mm"** | 12 | Mọi người |
| R1 | **Cần xử lý** · **Trạng thái dữ liệu** | 8 · 4 | Chỉ `can_edit` (giữ như hiện tại) |
| R2 | **Tiến độ KPI cam kết** (tháng dự án) | 12; bên trong mỗi ô 3 cột (tối đa 4 ô / hàng) | Mọi người, nếu dự án có sheet KPI |
| R3 | **Hiệu suất tìm kiếm** (kỳ cuộn): nhóm SEO · nhóm GEO | 3 ô SEO × 3 cột = 9 · 1 ô "Mọi kênh" 3 cột; hàng 2: 2 ô GEO × 3 cột + chỗ trống / ghi chú nguồn | Mọi người |
| R4 | **Thứ hạng** (snapshot) · **Index** (snapshot) | 8 · 4 (khách: Thứ hạng 12) | Index chỉ team |
| R5 | **Backlink** · **Công việc & OKR** | 6 · 6 | Mọi người |

Ghi chú:
- R3 tách hai nhóm bằng nhãn nhóm nhỏ, không cần hai card riêng: "Tìm kiếm Google (GSC / GA4)" và "AI & GEO".
- Ô "Lượt truy cập (mọi kênh)" là bối cảnh, xếp cuối nhóm SEO.
- Lưới thực hiện bằng CSS grid 12 cột (`sr-dash-12`), thay `sr-dash-grid` (3 cột) và `sr-dash-three` (auto-fit 420px) hiện tại.

### 2.2 Responsive [ĐỀ XUẤT]

| Độ rộng | Hành vi |
|---|---|
| ≥ 1280px | Như bảng trên |
| 1024–1279px | R1: 12 / 12 (xếp chồng). R2: 2 ô / hàng. R3: 3 ô / hàng (4 cột mỗi ô). R4 / R5: 6 · 6 |
| 640–1023px | R2, R3: 2 ô / hàng. R4, R5: 1 cột |
| < 640px | 1 cột. Ô số giữ đủ thông tin (không ẩn dòng so sánh); sparkline cao tối thiểu 36px; số chính 20px (khớp quy tắc mobile đang có trong `ui_theme`) |

Mọi chiều rộng: không cắt số, không đổi bố cục theo trạng thái bấm. Đây là bài học từ ô xu hướng của màn Báo cáo, nay dùng một bố cục duy nhất.

---

## 3. Đặc tả widget

Mọi khối dùng `T.section` (tiêu đề, icon, dòng phụ, link "Xem …"). Ô số dùng `T.kpi`. Chip trạng thái dùng `T.status_chip`.

### W0 · Thanh tiêu đề & kỳ
- **[HIỆN TẠI]**
  - Chọn 7 / 28 / 90 ngày ở thanh trên (`shell(period="days")`), nhớ trong `app.storage.user["dash_days"]`.
  - Tiêu đề có ghi khoảng ngày kỳ này và kỳ trước.
  - Thanh trên có "GSC đến dd/mm".
- **[ĐỀ XUẤT]** Thêm chip "Số đến dd/mm" cạnh tiêu đề cho **cả khách hàng**: dùng `ctx["end"]` đã có, không gọi API.

### W1 · Cần xử lý (chỉ team)
- **Mục đích:** việc phải làm hôm nay.
- **Nguồn [HIỆN TẠI] `todo_section`:**
  - Index: URL vừa rớt index, URL trong nhóm chưa index.
  - Rank: từ khóa xếp hạng bằng trang khác trang mục tiêu.
  - OKR: việc quá hạn hoặc chưa cập nhật trạng thái.
  - Core Web Vitals điện thoại chưa đạt; trang có điểm PageSpeed dưới 50.
  - Số ngày GSC còn thiếu.
- **Thời gian:** snapshot.
- **Tương tác:** mỗi dòng dẫn tới màn tương ứng.
- **[ĐỀ XUẤT]**
  - Mỗi dòng có mức độ bằng `status_chip` (Cần sửa / Nên xem) và số lượng căn phải, giống các khối Kiểm tra ở Backlink / Merchant.
  - Tối đa 6 dòng, còn lại gom vào "và N việc khác".
  - Không có việc nào: một dòng "Không có việc cần xử lý" như hiện tại.

### W2 · Trạng thái dữ liệu (chỉ team)
- **[HIỆN TẠI] `health_strip`:** GSC còn mới không, GSC thiếu ngày, file AI Overviews, job hằng ngày. Hiện một dòng "Dữ liệu đầy đủ" hoặc "Dữ liệu: N cảnh báo"; bấm mở `/ai?tab=chat-luong`.
- **[ĐỀ XUẤT]** Đổi thành card nhỏ ở R1, liệt kê từng nguồn kèm ngày mới nhất, không chỉ hiện trong tooltip:
  - GSC đến dd/mm
  - GA4: hôm qua
  - File AI Overviews đến dd/mm
  - Rank: lần check dd/mm
  - Backlink: lấy dd/mm
  - Job 6:00: ok / lỗi

  Tất cả lấy từ dữ liệu đã có (`ai_quality`, `rank_snapshot.last`, `backlinks.latest`). Không thêm gọi API.

### W3 · Tiến độ KPI cam kết (tháng dự án)
- **Mục đích:** trả lời "đang đạt cam kết không".
- **Nguồn [HIỆN TẠI]:**
  - `load_progress` (đọc DB + `KP.ga4_sessions`, có gọi GA4 nên chạy nền) rồi `kpi_block` → mỗi dòng cam kết một ô `_tile`.
  - Trạng thái lấy từ `KP.status`.
  - Phần thứ hạng tính trên bộ cam kết, lần check cuối trong tháng.
- **Thời gian:** tháng dự án đang chạy, hoặc tháng gần nhất đã chốt.
- **Tương tác:** link "Xem N tháng" → `/kpi`.
- **[ĐỀ XUẤT]**
  - Đưa lên R2.
  - Dựng **khung giữ chỗ** (skeleton đúng số ô, lấy từ `KP.versions` đọc DB) ngay khi mở trang, để khối không chèn vào làm trang nhảy.
  - Nhãn thời gian ghi rõ "Tháng dự án".

### W4 · Hiệu suất tìm kiếm (kỳ cuộn)

| Ô | Metric [HIỆN TẠI] | Nguồn | Link |
|---|---|---|---|
| Click từ Google | Tổng click kỳ này, % so với kỳ trước, số kỳ trước | `gsc_site_daily` | `/url` |
| Lượt hiển thị | Tổng impressions | `gsc_site_daily` | `/url` |
| Lượt truy cập Organic | `sessions`, kênh "Organic Search" | GA4, tải nền | **[ĐỀ XUẤT]** `/ai` hoặc không link (hiện không có link) |
| Lượt truy cập (mọi kênh) | Tổng `sessions` | GA4 | — |
| Truy cập từ AI | Phiên nhóm "AI Assistants" (`AIAnalytics`) | GA4 | **[ĐỀ XUẤT]** `/ai` |
| Tỷ lệ hiện trong AI | Phần trăm lượt hiển thị nằm trong câu trả lời AI, đổi theo điểm %. File trễ thì cửa sổ kết thúc ở ngày cuối có số và ghi "Số đến dd/mm" | File GSC Generative AI (`aio_block`) | `/ai` |

- **Tương tác [HIỆN TẠI]:** rê chuột trên sparkline xem từng điểm; kỳ trước vẽ nét đứt; nút (i) giải thích.
- **[ĐỀ XUẤT]**
  - Giữ nguyên `T.kpi` và cách tính.
  - Thêm nhãn nhóm "Tìm kiếm Google" / "AI & GEO".
  - Ô GA4 lúc đang tải dùng `T.skeleton` trong ô thay cho dấu "…".

### W5 · Thứ hạng (snapshot)
- **[HIỆN TẠI] `rank_snapshot`:**
  - Số từ khóa Top 3 / 5 / 10 trên **tổng số từ khóa** (`primary_keywords`: bỏ bộ Nháp, ưu tiên bộ Cam kết).
  - Số từ khóa lên / rớt hạng so với lần check trước **của từng từ khóa**.
  - Dòng AI Overview 4 tuần ("được trích x%") và "Đối thủ hay gặp" (`web_aio.dashboard_lines`).
  - Tất cả đọc DB, không gọi DataForSEO.
- **[ĐỀ XUẤT]**
  - Dùng lại **thẻ xếp hạng mới** của màn Báo cáo (`sr-rank-tile`: icon, tên, % bộ từ khóa, số / tổng, ▲▼, "So với dd/mm · Trước đó N").
  - Thêm số đã check / tổng.
  - Dòng phụ: "Lần check mới nhất dd/mm · bộ Cam kết".

### W6 · Index (chỉ team, snapshot)
- **[HIỆN TẠI] `index_snapshot`:**
  - Đã index / số URL **đã kiểm tra**.
  - "Chưa index · cần xem" (bỏ các lý do cố ý).
  - 3 lý do chưa index nhiều nhất.
  - Ẩn với khách hàng.
- **[ĐỀ XUẤT]** Dòng phụ ghi rõ "trên N URL đã kiểm tra, không phải toàn site".

### W7 · Backlink (snapshot)
- **[HIỆN TẠI]**
  - Số liệu: website trỏ về (± so với **lần lấy trước**), backlink, uy tín /1000 (rank của DataForSEO), link mới / mất của tháng trọn gần nhất, sparkline 12 tháng, điểm spam, link gãy.
  - Nút "Lấy số mới" (chỉ người sửa được, khoảng 0,02 USD).
- **[ĐỀ XUẤT]**
  - **Bỏ nút trả phí khỏi Tổng quan**: chỉ để link sang `/backlink`, nơi có lịch và tạm ngưng.
  - Ghi "so với lần lấy dd/mm" cạnh mức thay đổi.

### W8 · Công việc & OKR (snapshot)
- **[HIỆN TẠI]** % hoàn thành (số việc xong / tổng), số việc trễ hạn, 3 objective đầu kèm thanh tiến độ. Nguồn: sheet OKR đã đồng bộ.
- **[ĐỀ XUẤT]**
  - Ghi "Đợt …" và ngày đồng bộ sheet.
  - Số trễ hạn lớn hơn 0 thì hiện chip đỏ, giữ màu số như hiện tại.

---

## 4. Trạng thái

### 4.1 Trạng thái KPI [HIỆN TẠI `KP.status`, giữ nguyên]

| Tone | Chữ hiển thị | Khi nào |
|---|---|---|
| green | "Đang đạt" (tháng đang chạy) / "Đạt" (đã chốt) | `ok` = True |
| amber | "Thiếu N từ khóa", "Dự báo thiếu N phiên", "Lũy kế thiếu N phiên" | Chưa đạt, tháng đang chạy |
| red | "Thiếu N từ khóa", "Thiếu N phiên", "Lũy kế thiếu N phiên" | Chưa đạt, tháng đã chốt |
| grey | "Tháng này không cam kết", "Chờ lần check đầu", "Chưa nhập baseline", "Chưa đủ ngày để dự báo", "Chưa có số" | Chưa đủ dữ liệu để chấm |

### 4.2 Độ mới dữ liệu [ĐỀ XUẤT, dựa trên dữ liệu đã có]
- GSC: chip "Số đến dd/mm". Tông amber khi trễ hơn 4 ngày (cùng ngưỡng `lag <= 4` của `ai_quality.gsc_status`).
- File AI Overviews: ô Tỷ lệ hiện trong AI luôn ghi "Số đến dd/mm" khi khác ngày GSC (hiện đã làm).
- Snapshot: mỗi khối ghi ngày đo / lấy ở dòng phụ.

### 4.3 Cảnh báo
- **Chỉ team:**
  - W1 (việc cần làm) và W2 (dữ liệu).
  - Không đưa cảnh báo vận hành lên giao diện của khách (giữ nguyên quy tắc "không có trong báo cáo gửi đi").
- **Khách hàng:**
  - Chỉ thấy trạng thái KPI và độ mới dữ liệu.

### 4.4 Đang tải / trống / lỗi

| Trạng thái | [HIỆN TẠI] | [ĐỀ XUẤT] |
|---|---|---|
| Đang tải GA4 | Ô hiện "…", dòng phụ "Đang lấy số GA4" | `T.skeleton` trong ô, giữ đúng chiều cao |
| Đang tải KPI | Không có gì; khối chèn vào cuối trang sau khi tải | Khung giữ chỗ ở R2 |
| Chưa gắn GA4 | "chưa có" + "Chưa kết nối GA4" | Giữ nguyên. Người sửa được thấy thêm link "Gắn GA4" → `/projects` |
| Lỗi GA4 | "chưa có" + "Không lấy được số GA4" | Thêm tooltip lỗi ngắn (đã có `explain`); không làm đỏ cả trang |
| Chưa nhập file AI | "Cần nhập file Generative AI từ GSC" | Giữ nguyên; người sửa được thấy link "Nhập file" → `/ai` |
| Rank trống | "Thêm từ khóa và đặt lịch check…" | Giữ nguyên |
| Backlink trống | Câu giải thích + chi phí | Bỏ nút trả phí, giữ link sang `/backlink` |
| OKR trống | "Gắn link sheet OKR ở màn Dự án…" | Giữ nguyên |
| Không có sheet KPI | Khối KPI không hiện | Người sửa được thấy card mời "Tạo KPI cam kết" → `/kpi` (wizard đã có). Khách không thấy |

---

## 5. Ràng buộc phải giữ nguyên

| Hạng mục | Quy định |
|---|---|
| **Cách tính** | Giữ nguyên `windows`, `buckets`, `change`, `rank_snapshot`, `index_snapshot`, `aio_block`, `KP.progress`, `KP.status`. Thay đổi phần tính toán nào (ví dụ B4) phải có test riêng |
| **Quyền** | Giữ `can_edit` cho W1 / W2 và mọi nút hành động. Index tiếp tục ẩn với `is_client`. Quyền tiếp tục được chặn ở server qua `open_page` |
| **Chi phí** | Không gọi DataForSEO khi mở Tổng quan. Hiện tại chỉ gọi khi bấm nút Backlink; đề xuất bỏ cả nút này khỏi Tổng quan. GA4 / Sheets là API miễn phí, tiếp tục chạy nền |
| **Tích hợp** | Không thêm metric hay nguồn mới. Không đưa Local SEO / Merchant lên Tổng quan khi chưa có dữ liệu thật |
| **Nhận diện hình ảnh** | Font Be Vietnam Pro; nền `#F4F4EF`; thẻ trắng bo 12–14px; xanh `#1E7C31`; tông green / amber / red / blue / grey (`T.TONES`); không dùng viền nhấn một bên; không giấu thông tin sau hover; hover chỉ bật khi có chuột |

---

## 6. Điểm chưa nhất quán & rủi ro hiểu sai (từ code hiện tại)

| # | Vấn đề | Loại | Bằng chứng |
|---|---|---|---|
| 1 | **KPI cam kết nằm cuối trang và chèn vào sau** → thứ quan trọng nhất với khách lại xuất hiện muộn nhất, trang bị nhảy bố cục | UX | `kpi_box` tạo sau `sr-dash-three`; `load_kpi` chạy nền |
| 2 | **Thứ hạng ở Tổng quan khác thứ hạng trong KPI**: Tổng quan đếm theo lần check mới nhất trên mọi từ khóa (bỏ bộ Nháp); KPI đếm theo bộ cam kết, lần check cuối tháng dự án. Cùng "Top 3" mà hai số khác nhau | RỦI RO | `rank_snapshot` và `KP.progress`; đã thấy thực tế "50% · 2/4" (KPI) khác "1/2" (thứ hạng) ở màn Báo cáo |
| 3 | **Mẫu số Top N gồm cả từ khóa chưa check**: "Top 3: 2/10" khi mới check 4 từ | RỦI RO | `total = len(kws)`, `top3` chỉ đếm từ khóa đã check |
| 4 | **Lên / rớt hạng mỗi từ khóa so với một mốc khác nhau** (lần check trước của chính từ khóa đó), không khớp kỳ cuộn ở trên | RỦI RO | `rank_change` theo từng từ khóa |
| 5 | **Cột cuối của sparkline 90 ngày là tuần thiếu ngày**: 90 ngày chia 13 đoạn, đoạn cuối chỉ 6 ngày nên cột thấp hơn, trông như giảm. Màn Nguồn tìm kiếm đã sửa lỗi tương tự | RỦI RO | `buckets()` step 7 với 90 ngày |
| 6 | **Tỷ lệ hiện trong AI có thể dùng cửa sổ ngày khác** các ô cùng hàng (kết thúc ở ngày cuối file) | RỦI RO (đã ghi chú một phần) | `load()` → `windows(until, days)` |
| 7 | **Backlink: mức ± so với lần lấy trước**, không theo kỳ 7 / 28 / 90 đang chọn ở đầu trang | RỦI RO | `delta_badge(... since="lần lấy …")` |
| 8 | **Index chỉ tính trên URL đã kiểm tra**, dễ đọc thành "x% toàn site đã index" | RỦI RO | `index_snapshot` |
| 9 | **"Uy tín /1000" là rank của DataForSEO**, không phải DR / DA quen thuộc | RỦI RO | tooltip đã giải thích, nhưng chỉ khi rê chuột |
| 10 | **Truy cập từ AI và Organic có thể bị hiểu là cộng dồn**: click từ AI Overviews nằm trong Organic | RỦI RO | README mục KPI |
| 11 | **Ba kiểu ô khác nhau cho cùng loại số**: Tổng quan dùng `T.kpi`; Báo cáo dùng `trend_chart` (đã chuẩn hóa cấu trúc); thứ hạng ở Tổng quan dùng mini-stats, còn Báo cáo dùng `sr-rank-tile` mới | UX | `web_dashboard.py` và `web_overview.py` |
| 12 | **Nút trả phí (Backlink) nằm trên màn tổng hợp**: dễ bấm nhầm, lệch nguyên tắc "Tổng quan chỉ để đọc" | UX / chi phí | `fetch_backlinks` |
| 13 | **Khách hàng không có tín hiệu độ mới dữ liệu ngoài "GSC đến"**: `health_strip` chỉ cho người sửa được | UX | `if ed: health_strip(...)` |
| 14 | **"Lượt truy cập (mọi kênh)" đứng ngang hàng chỉ số SEO**: không phải kết quả SEO, làm loãng câu trả lời "SEO đang ra sao" | UX | thứ tự trong `pulse()` |
| 15 | **Ô GA4 không có link đi sâu**, trong khi ô GSC có | UX | `ga4_tile` không truyền `href` |

---

## 7. Backlog ưu tiên

### P0: sửa rủi ro số liệu và thứ bậc chính

| ID | Việc | Tiêu chí chấp nhận |
|---|---|---|
| B1 | Đưa **KPI cam kết** lên R2, có khung giữ chỗ | Mở trang: khung KPI hiện trong vòng 1 khung hình đầu, đúng số ô của phiên bản KPI hiện hành. Khi số về, chiều cao khối không đổi quá 8px. Dự án không có sheet KPI: khách không thấy khối; người sửa được thấy card "Tạo KPI cam kết" |
| B2 | **Nhãn loại thời gian** cho mọi khối (kỳ cuộn / tháng dự án / snapshot kèm ngày) | Mỗi khối có dòng phụ ghi đúng loại và ngày. Không ô snapshot nào dùng cụm "so với N ngày trước" |
| B3 | **Thứ hạng: mẫu số rõ ràng** | Hiện "đã check X/Y"; Top N ghi "trên Y từ khóa". Nếu dự án có KPI thì thêm dòng "KPI tháng dự án: …" lấy từ cùng `KP.progress`, kèm nhãn để không nhầm với ảnh chụp |
| B4 | **Sparkline 90 ngày bỏ tuần thiếu ngày** | Đoạn cuối dưới 7 ngày thì không vẽ, hoặc vẽ khác kiểu kèm chú thích "tuần chưa đủ". Có test cho `buckets` / logic cắt |
| B5 | **Bỏ nút "Lấy số mới" (DataForSEO) khỏi Tổng quan** | Không còn đường gọi DataForSEO nào từ `/`. Kiểm tra bằng grep `BL.refresh` trong `web_dashboard.py` và test hiện có |

### P1: nhất quán & trạng thái

| ID | Việc | Tiêu chí chấp nhận |
|---|---|---|
| B6 | **Lưới 12 cột** thay `sr-dash-grid` / `sr-dash-three` | Đúng bảng 2.1 / 2.2 ở 1440 / 1100 / 800 / 375px. Không tràn ngang, không cắt số (kiểm tra bằng script đo phần tử tràn) |
| B7 | **Thứ hạng dùng thẻ `sr-rank-tile`** của Báo cáo | Cùng bố cục với Báo cáo (icon, %, số/tổng, ▲▼, so với ngày, trước đó). Số tính từ `rank_snapshot` không đổi |
| B8 | **Trạng thái dữ liệu thành card** (W2), chip "Số đến" cho mọi người | Card liệt kê từng nguồn kèm ngày. Khách thấy chip "Số đến dd/mm". Không thêm gọi API |
| B9 | **Skeleton cho ô GA4** | Không còn "…" trơn. Chiều cao ô không đổi khi số về |
| B10 | **Cần xử lý có mức độ + số lượng** | Mỗi dòng có chip mức độ và số. Tối đa 6 dòng + "và N việc khác". Thứ tự: Cần sửa trước |
| B11 | **Nhóm ô SEO / GEO**, "Mọi kênh" về cuối nhóm SEO | Có nhãn nhóm. Thứ tự ô đúng 2.1 |

### P2: hoàn thiện

| ID | Việc | Tiêu chí chấp nhận |
|---|---|---|
| B12 | Link đi sâu cho ô GA4 (Organic, AI → `/ai`) | Bấm ô mở đúng màn / tab. Có `aria-label` |
| B13 | Ghi chú "không cộng dồn" cho Organic và Truy cập từ AI | Có trong (i) của hai ô và chú thích nhóm GEO |
| B14 | Index ghi rõ "trên N URL đã kiểm tra"; Backlink ghi "so với lần lấy dd/mm" ngay cạnh mức thay đổi | Chữ hiện sẵn, không chỉ có trong tooltip |
| B15 | Rà nút (i) theo `metric_help` cho mọi ô | Ô nào cũng có nút (i), nội dung đúng 3 phần "Là gì / Cho biết / Đo thế nào" |

**Kiểm thử chung cho mọi hạng mục:**
- Bộ test `unittest` hiện có phải qua hết.
- Kiểm tra giao diện ở 4 độ rộng, với 3 vai trò: Chủ tool, Team xem, Khách hàng.
- Mở `/` không phát sinh request DataForSEO: kiểm tra log ngân sách không tăng.
