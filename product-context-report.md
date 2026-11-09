# Product Context Report: SEO Report

> Viết để một AI khác hiểu sản phẩm trước khi review UX/UI màn **Tổng quan (Dashboard)**.
> Nguồn: mã nguồn nhánh `multi-site` (gồm cả phần chưa commit tại ngày 06/11/2026) và `README.md`.
> Ký hiệu: **[Đã xác minh]** đọc trực tiếp trong code · **[Giả định]** suy luận, chưa có trong code/tài liệu · **[Thiếu]** không tìm thấy thông tin.

---

## 1. Tổng quan sản phẩm

**SEO Report** là tool báo cáo SEO và GEO tự host (self-hosted) cho người làm SEO hoặc agency quản lý nhiều website ([README.md](README.md)). Toàn bộ giao diện bằng tiếng Việt.

**Mục đích chính:**
- Gom số liệu từ Google Search Console (GSC), Google Analytics 4 (GA4) và DataForSEO vào một chỗ, lưu trên máy của người dùng (SQLite).
- Theo dõi hằng ngày: màn Tổng quan.
- Báo cáo định kỳ: tuần hoặc tháng, xuất ra Excel, Google Sheets, Slides, PDF.
- Chấm **KPI cam kết** với khách hàng: thứ hạng top N, phiên Organic hoặc AI theo tháng dự án.
- Cho khách hàng một tài khoản riêng, chỉ xem website của mình.

**Vấn đề nó giải quyết** [Đã xác minh qua tính năng, diễn giải là của người viết]:
- Không phải mở nhiều công cụ (GSC, GA4, tool check rank, sheet OKR, sheet KPI) mới biết website đang ra sao.
- Báo cáo cho khách mất công làm tay.
- Khó chứng minh tiến độ so với KPI đã cam kết trong hợp đồng.
- Chưa đo được "GEO": traffic từ ChatGPT, Gemini…; tỷ lệ hiện trong AI Overviews; website có được trích trong AI Overview không.

---

## 2. Người dùng mục tiêu

Phân quyền: [access.py](seo_report/access.py), [README.md](README.md) mục 4.

| Vai trò | Ai | Thấy / làm được gì | Luồng việc chính |
|---|---|---|---|
| **Chủ tool** (`local` / admin) | Chủ agency, người cài tool | Mọi website, mọi màn, Quản trị (Dự án, Phân quyền, Ngân sách, Cài đặt tích hợp) | Thêm website, kết nối Google / DataForSEO, đặt ngân sách check rank, cấp quyền |
| **Được sửa** (`editor`) | SEO in-house / SEO của agency | Mọi màn của website được gắn; check rank (tốn tiền), sửa từ khóa, nhóm URL, nhận xét báo cáo, lưu Drive | Theo dõi hằng ngày → xử lý "Cần xử lý" → check rank → viết nhận xét → xuất báo cáo |
| **Team xem** (`viewer`) | Content, sếp | Xem các màn nội bộ, không sửa | Đọc số, xem việc |
| **Khách hàng** (`client`) | Chủ website thuê dịch vụ | Chỉ các trang trong `CLIENT_PAGES`: `/`, `/report`, `/kpi`, `/okr`, `/rank`, `/doi-thu`, `/aio`, `/backlink`, `/local`, `/merchant`, `/tai-khoan` | Mở Tổng quan / Báo cáo xem kết quả, đối chiếu KPI cam kết |

Ghi chú:
- Ai mở tool ngay trên máy đang chạy tool thì vào thẳng với quyền Chủ tool. Người truy cập từ xa phải đăng nhập bằng email + mật khẩu.
- [Lệch tài liệu] README ghi "Khách hàng chỉ thấy Tổng quan, Báo cáo, KPI, OKR", nhưng code hiện cho khách xem thêm Thứ hạng, Đối thủ, AI Overview, Backlink, Local SEO, Merchant Center.

---

## 3. Tính năng & module

Menu `NAV` trong [web.py](seo_report/web.py).

### Đã triển khai [Đã xác minh]

| Nhóm | Màn (đường dẫn) | Chức năng |
|---|---|---|
| — | **Tổng quan** `/` | Màn chính của review này (mục 4) |
| — | **Báo cáo** `/report` | Bản chốt theo tuần hoặc tháng, so với kỳ trước / cùng kỳ năm trước / kỳ tùy chọn. Gồm nhận xét viết tay, Tiến độ KPI, Kết quả SEO, Kết quả GEO, Thứ hạng từ khóa cam kết, Công việc, Điểm cần chú ý. Xuất Excel / Sheets / Slides / PDF ([web_overview.py](seo_report/web_overview.py), [report.py](seo_report/report.py)) |
| — | **KPI cam kết** `/kpi` | Mỗi cam kết một dòng (Top N, mức phiên theo tháng, tăng thêm cộng dồn), có wizard tạo sheet và form sửa cam kết ([web_kpi.py](seo_report/web_kpi.py), [kpi.py](seo_report/kpi.py)) |
| — | **Công việc & OKR** `/okr` | OKR và Weekly Task đọc từ Google Sheet, Gantt, việc trễ hạn ([web_okr.py](seo_report/web_okr.py)) |
| SEO | **URL & Index** (4 tab: Hiệu suất URL `/url`, Nguồn tìm kiếm `/nguon`, Index `/index`, Quản lý URL `/urls`) | Hiệu suất từng URL, head keyword, cannibalization; click theo nguồn (web, ảnh, video, tin tức, Discover, Google News); kiểm tra index (URL Inspection) và sitemap; nhóm URL, loại trang |
| SEO | **Tốc độ trang** `/toc-do` | CrUX + PageSpeed, chấm điểm, audit, chia tab ([web_cwv.py](seo_report/web_cwv.py)) |
| SEO | **Từ khóa & Thứ hạng** `/rank` | Check rank qua DataForSEO theo lịch, bộ từ khóa (nháp / chốt), lịch sử vị trí, ngân sách |
| SEO | **Đối thủ** `/doi-thu` | Tối đa 10 đối thủ, thị phần hiển thị, ai đang vượt |
| SEO | **Backlink** `/backlink` | DataForSEO, chia tab, audit theo từng tab, lịch tự lấy / tạm ngưng |
| SEO | **Local SEO** `/local` | Google Business Profile: hiệu suất, từ khóa, kiểm tra hồ sơ |
| SEO | **Merchant Center** `/merchant` | Sản phẩm Google Shopping, trạng thái, kiểm tra ([web_merchant.py](seo_report/web_merchant.py)) |
| AI & GEO | **AI Search & GEO** `/ai` | Traffic AI theo nguồn / trang / quốc gia (GA4), AI Overviews / AI Mode (file CSV nhập từ GSC), cơ hội, chất lượng dữ liệu |
| AI & GEO | **AI Overview** `/aio` | Website / đối thủ được trích trong AI Overview trên bộ từ khóa theo dõi (từ kết quả SERP của DataForSEO) |
| Quản trị | Dự án, Ngân sách & chi phí, Phân quyền, Cài đặt tích hợp | Nhiều website, xóa dự án vĩnh viễn, kiểm tra kết nối GSC / GA4, chi phí DataForSEO theo API và theo dự án |

### Đã viết code nhưng chưa chạy với dữ liệu thật [Đã xác minh]
- **Local SEO:** code xong, nhưng Google chưa cấp quota Business Profile API cho Google Cloud project của tool, nên chưa có số.
- **Merchant Center:** code xong (chưa commit), cần đăng ký Google Cloud project với tài khoản Merchant Center trước.
- **Nguồn tìm kiếm (`/nguon`) và mục Sitemap:** đã chạy với số thật nhưng chưa commit.

### Dự kiến / đề xuất [Giả định, chỉ có trong trao đổi, không có trong code]
- Bing Webmaster Tools API, Safe Browsing, Knowledge Graph.
- DataForSEO Labs.

---

## 4. Dashboard (màn Tổng quan `/`)

Code: [web_dashboard.py](seo_report/web_dashboard.py) `build_dashboard_page`, gọi `health_strip` và `todo_section` trong [web_overview.py](seo_report/web_overview.py). Đăng ký trang: [web.py](seo_report/web.py) `overview_page`.

### 4.1 Khung thời gian
- Ngày cuối của kỳ = ngày mới nhất có số GSC (`K.latest_date`), không phải hôm nay. GSC thường trễ khoảng 2–3 ngày.
- Chọn **7 / 28 / 90 ngày** ở thanh trên cùng (`shell(period="days")`). Lựa chọn được nhớ theo trình duyệt (`app.storage.user["dash_days"]`), mặc định 28.
- Kỳ so sánh = cùng số ngày liền trước (`windows()`).
- Biểu đồ nhỏ (sparkline): theo ngày với 7 và 28 ngày, theo tuần với 90 ngày (`buckets()`). Kỳ trước vẽ nét đứt. Phía trên các ô có chú thích chung "Kỳ này / N ngày trước đó".

### 4.2 Thứ tự hiển thị (từ trên xuống)

| # | Khối | Ai thấy | Dữ liệu / cách tính | Tương tác |
|---|---|---|---|---|
| 1 | **Tiêu đề trang** | Mọi người | "Tổng quan" + khoảng ngày kỳ này và kỳ trước | — |
| 2 | **Chỉ báo dữ liệu** (`health_strip`) | Chỉ người sửa được (`can_edit`) | GSC còn mới không, GSC thiếu ngày, file AI Overviews, job hằng ngày (`ai_quality`). Một dòng "Dữ liệu đầy đủ" hoặc "Dữ liệu: N cảnh báo" | Rê chuột xem chi tiết; bấm mở `/ai?tab=chat-luong` |
| 3 | **Cần xử lý** (`todo_section`) | Chỉ người sửa được | URL vừa rớt index; URL trong nhóm chưa index; từ khóa xếp hạng bằng trang khác trang mục tiêu; việc OKR quá hạn hoặc chưa cập nhật; website chưa đạt Core Web Vitals trên điện thoại; trang có điểm PageSpeed dưới 50; số ngày GSC còn thiếu. Ghi rõ "không có trong báo cáo gửi đi" | Mỗi dòng dẫn tới màn tương ứng |
| 4 | **6 ô nhịp số liệu** (lưới 3 cột → 2 → 1) | Mọi người | Xem bảng 4.3 | Ô có `href` bấm được; rê chuột trên sparkline xem số |
| 5 | **Thứ hạng** | Mọi người | `rank_snapshot`: Top 3 / 5 / 10 trên tổng số từ khóa. Lấy mỗi từ khóa một lần, ưu tiên bộ Cam kết, bỏ bộ Nháp. Kèm số từ khóa lên / rớt hạng so với lần check trước của chính từ khóa đó. Thêm 2 dòng từ `web_aio.dashboard_lines`: tỷ lệ website được trích trong AI Overview 4 tuần và "Đối thủ hay gặp" | Link "Thứ hạng" → `/rank`; dòng AI Overview → `/aio` |
| 6 | **Index** | **Không hiện cho khách hàng** | `index_snapshot`: lần kiểm tra mới nhất của mỗi URL. Đã index (verdict PASS) / tổng; "Chưa index · cần xem" (bỏ các lý do cố ý, ví dụ noindex); 3 lý do chưa index nhiều nhất | Link → `/index` |
| 7 | **Backlink** | Mọi người | DataForSEO (`backlinks.latest`): website trỏ về (± so với lần lấy trước), backlink, uy tín /1000; link mới / mất của tháng trọn gần nhất; sparkline website trỏ về theo tháng (tối đa 12); điểm spam, link gãy | Link → `/backlink`; nút "Lấy số mới" (chỉ người sửa được; khoảng 0,02 USD) |
| 8 | **Công việc & OKR** | Mọi người | Sheet OKR (`okr.overview`): % hoàn thành, số việc trễ hạn, 3 objective đầu kèm thanh tiến độ | Link → `/okr` |
| 9 | **Tiến độ KPI cam kết** | Mọi người (nếu dự án có sheet KPI) | `web_kpi.load_progress` + `kpi_block`, tải nền: tháng dự án đang chạy, mỗi cam kết một ô (giá trị, thanh tiến độ, trạng thái, gợi ý) | Link "Xem N tháng" → `/kpi` |

Khối 5–8 nằm trong lưới `sr-dash-three` (tự xuống cột, mỗi cột tối thiểu 420px). Khối 9 hiện cuối trang sau khi tải nền xong.

### 4.3 Sáu ô nhịp số liệu (`pulse()`)

| Ô | Nguồn | Cách tính | Bấm tới |
|---|---|---|---|
| Click từ Google | GSC (`gsc_site_daily`) | Tổng click trong kỳ, % thay đổi so với kỳ trước, số kỳ trước | `/url` |
| Lượt hiển thị | GSC | Như trên với impressions | `/url` |
| Lượt truy cập (mọi kênh) | GA4 Data API, tải nền | Tổng `sessions` theo ngày | — |
| Lượt truy cập Organic | GA4 | `sessions` với `sessionDefaultChannelGroup = "Organic Search"` | — |
| Truy cập từ AI | GA4 (`AIAnalytics.trend`, nhóm "AI Assistants") | Phiên từ ChatGPT, Gemini, Perplexity… theo cách phân loại trong `ai_classifier` | — |
| Tỷ lệ hiện trong AI | File CSV "Generative AI" xuất từ GSC (`report.aio_block`) | Phần lượt hiển thị nằm trong câu trả lời AI (%), thay đổi tính bằng điểm %. File thường về trễ: khi đó tính trên cùng số ngày nhưng kết thúc ở ngày cuối có số, và ghi "Số đến dd/mm" | `/ai` |

Trạng thái của ô GA4: "…" khi đang tải, "chưa có" kèm lý do khi chưa gắn GA4 hoặc lỗi. Thẻ dùng chung `T.kpi` ([ui_theme.py](seo_report/ui_theme.py)): icon, tên, nút (i) giải thích, số lớn, nhãn tăng / giảm xanh-đỏ, sparkline, dòng so sánh, dòng nguồn.

### 4.4 Khác biệt với màn Báo cáo [Đã xác minh]
- **Tổng quan:** nhịp theo ngày (7 / 28 / 90 ngày tính lùi), có việc nội bộ. Số GSC / rank / index / OKR đọc từ SQLite nên hiện ngay; GA4, AI và KPI tải sau.
- **Báo cáo:** bản chốt theo tuần hoặc tháng để gửi đi, chỉ gồm chỉ số người đọc cần. Index, CTR, vị trí GSC, nhóm URL không đưa vào.
- Tổng quan **không** có khối Kết quả SEO / GEO dạng ô bật/tắt đường và biểu đồ lớn như Báo cáo; chỉ có 6 ô với sparkline.

---

## 5. Dữ liệu & tích hợp

| Nguồn | Lấy thế nào | Dùng ở đâu |
|---|---|---|
| **GSC** | Search Analytics API; job hằng ngày lấy bù tới 16 tháng; URL Inspection để kiểm tra index; sitemap; số theo từng nguồn tìm kiếm | Click / hiển thị (Tổng quan, Báo cáo, URL), Index, Nguồn tìm kiếm |
| **GSC Generative AI** | **Nhập tay** file CSV / zip mỗi tuần (GSC chưa có API) | Tỷ lệ hiện trong AI |
| **GA4** | Data API, gọi khi mở trang (có cache trong `ga4_query`) | Lượt truy cập, Organic, AI; KPI phiên Organic / AI Assistant |
| **Rank** | DataForSEO SERP, theo lịch từng bộ từ khóa, có trần ngân sách theo website | Thứ hạng, KPI Top N, Đối thủ, AI Overview (trích nguồn trong SERP) |
| **Volume** | Google Ads Keyword Planner hoặc DataForSEO, chỉ lấy một lần khi thêm từ khóa | Màn từ khóa |
| **Backlink** | DataForSEO Backlinks, tự lấy lại theo lịch (mặc định 7 ngày), có tạm ngưng | Backlink, Tổng quan |
| **KPI** | Google Sheet dự án (tab "KPI cam kết", "Từ khóa cam kết"); tool lưu phiên bản, tháng đã chốt không đổi | Tiến độ KPI (Tổng quan, Báo cáo, `/kpi`): Top N lấy từ rank, phiên lấy từ GA4 |
| **OKR** | Cùng sheet dự án (các tab "OKRs…", "Weekly Task Tracker") | OKR, Cần xử lý |
| **PageSpeed / CrUX, Business Profile, Merchant API** | API miễn phí của Google | Tốc độ, Local SEO, Merchant Center |

Cách các nguồn ghép với nhau [Đã xác minh]:
- **KPI** là nơi ghép GA4 (phiên) với Rank (Top N) theo **tháng dự án**, tính từ ngày bắt đầu trong sheet.
- **Cần xử lý** ghép Index + Rank (trang xếp hạng khác trang mục tiêu) + OKR + Tốc độ + chất lượng GSC.
- **AI / GEO** có 3 nguồn độc lập, không cộng với nhau: GA4 (traffic từ trợ lý AI), file GSC (tỷ lệ hiện trong AI), SERP DataForSEO (được trích trong AI Overview).

Lịch tự động: `cli._daily_one`, chạy 6:00 qua Windows Task Scheduler. Lần lượt: GSC → volume từ khóa → nguồn tìm kiếm + sitemap → Core Web Vitals → Business Profile → Merchant → backlink → OKR / KPI (ghi lại sheet) → index → phân loại URL; sao lưu ở cuối lệnh `daily`. **Check rank không nằm trong job này:** máy chủ web tự check theo ngày và giờ đã đặt cho từng bộ từ khóa (`web_rank.schedule_loop`).

---

## 6. Kiến trúc sản phẩm

- **Công nghệ:**
  - Python, NiceGUI 3.x (Quasar / Vue chạy phía server qua websocket), ECharts.
  - Mỗi website một file SQLite (`data/seo.db` cho website đầu tiên, `data/projects/*.db` cho các website sau).
  - Gọi Google qua `google-api-python-client`; xuất file bằng openpyxl và python-pptx.
- **Triển khai:**
  - Chạy nền trên một máy Windows (Scheduled Task "SEO Report web", cổng 8080).
  - Ra ngoài qua Cloudflare Tunnel hoặc Tailscale, hoặc chạy trên VPS.
  - Một token Google OAuth (của Chủ tool) dùng chung cho mọi website.
- **Điều hướng:**
  - Thanh bên chia nhóm: (không tên) / SEO / AI & GEO / Quản trị.
  - Thanh trên cùng: đổi dự án (giữ nguyên màn đang xem), chọn kỳ (Tổng quan: số ngày; Báo cáo: tuần / tháng), ngày dữ liệu GSC mới nhất.
  - Nhiều màn chia tab, tab giữ trong URL (`?tab=`).
- **Quản lý dự án:**
  - Mỗi website là một dự án, cấu hình riêng (GSC, GA4, từ khóa thương hiệu, ngân sách rank, sheet OKR / KPI).
  - Lưu trữ được, hoặc xóa vĩnh viễn (chỉ Chủ tool).
  - File xuất trên Drive xếp theo thư mục hạng mục (`drive.CATEGORIES`).
- **Ràng buộc quan trọng:**
  - Số GSC trễ 2–3 ngày; file AI Overviews trễ hơn và phải nhập tay.
  - Thứ hạng chỉ lấy từ DataForSEO và tốn tiền: có trần ngân sách, cảnh báo ở 80%, tạm ngưng theo website. Vị trí trung bình của GSC không dùng làm thứ hạng.
  - Dữ liệu GA4 lấy lúc mở trang nên ô GA4 hiện chậm hơn ô GSC.
  - Khách hàng bị chặn ở server, không chỉ ẩn menu.
  - Máy chạy tool tắt thì tool ngừng.
- **Quy ước UI** (bộ nhớ dự án + [ui_theme.py](seo_report/ui_theme.py)):
  - Một font Be Vietnam Pro; nền kem `#F4F4EF`, thẻ trắng bo 12–14px; màu nhấn xanh lá `#1E7C31`.
  - Không dùng viền nhấn một bên.
  - Không giấu thông tin sau hover.
  - Hiệu ứng hover chỉ bật trên thiết bị có chuột.

---

## 7. Ưu tiên sản phẩm: 30 giây đầu trên Dashboard

[Giả định, suy ra từ thứ tự và nội dung đang code; chưa có tài liệu nào nêu rõ mục tiêu này]

1. **Website đang tốt lên hay xấu đi?**
   - Click và lượt hiển thị Google, lượt truy cập Organic so với kỳ trước.
   - Đây là 6 ô nhịp số liệu; code xếp chúng làm khối số đầu tiên.
2. **Có việc gì phải xử lý ngay không?** (chỉ team)
   - Đọc từ khối "Cần xử lý" và chỉ báo dữ liệu.
   - Hai khối này cố ý đặt **trên** các ô số (comment trong code: "thấy ngay trước khi đọc số").
3. **Có đang đạt KPI cam kết không?**
   - Đây là điều khách hàng và quản lý quan tâm nhất.
   - Hiện khối này **tải sau và nằm cuối trang**. Đây là điểm cần review.
4. **Thứ hạng từ khóa chủ lực:** Top 3 / 5 / 10, số lên / rớt hạng.
5. **Hiện diện trên AI:** truy cập từ AI, tỷ lệ hiện trong AI, được trích trong AI Overview.
6. **Số liệu có tin được không:** số tính đến ngày nào; GA4 / AI đã tải xong chưa.

**Thiếu thông tin [Thiếu]:**
- Không có tài liệu nào xác định người dùng chính của Tổng quan là team hay khách hàng.
- Không có số liệu sử dụng thực tế (analytics của chính tool).
- Không có mục tiêu UX được viết ra cho màn này.

Hai bản của Tổng quan khác nhau đáng kể:
- **Khách hàng:** không có Cần xử lý, chỉ báo dữ liệu, Index.
- **Team:** có đủ cả ba khối trên.
