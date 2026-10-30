# REPO DISCOVERY REPORT — AI Search & GEO Analytics (Phase 0)

Ngày: 29/10/2026 · Repo: `D:\Projects\seo-report` · Trạng thái: **chờ review, chưa viết code tính năng**

## 1. Kết luận chính

1. **Spec giả định sai một điều nền tảng: tool CHƯA có kết nối GA4.** Hiện chỉ có GSC (scope `webmasters.readonly`). GA4 vốn nằm trong lộ trình "giai đoạn 2". Vì vậy cần thêm một bước **R0: kết nối GA4**: thêm scope, bật API, chọn property. Bước này nằm trước R1 của brief.
2. **Tool là app một site, không có khái niệm "Project".** Các yêu cầu về project isolation và endpoint `/api/projects/{id}/…` trong spec không áp dụng nguyên văn. Đề xuất ánh xạ: "project" = cấu hình `config.toml` hiện tại (1 GSC property + 1 GA4 property). Các "endpoint" là hàm Python, vì giao diện NiceGUI gọi trực tiếp phía server, không qua REST.
3. **Có 2 chỗ trong code hiện tại vi phạm quy tắc của spec. Nên sửa trước, độc lập với module AI:**
   - **Số "Toàn site" trong báo cáo tuần đang cộng các dòng theo page** (`report._site_kpi` cộng từ `gsc_page_daily`). Spec §4.2 cấm cách này. Click gần như khớp, nhưng **impression bị thổi phồng**: tuần 19–25/10 ra 327.715, trong khi tổng theo property trên GSC sẽ thấp hơn. Cách sửa: sync thêm bảng tổng theo property (truy vấn `dimensions=[date]`).
   - **Sync GSC đang dùng `dataState: "all"`.** Spec §6.4 đề xuất mặc định `final`. Không cần đổi, vì tool lấy lại 5 ngày gần nhất mỗi sáng, nhưng phải gắn nhãn `provisional` cho các ngày gần đây.
4. **Đã kiểm chứng với tài liệu Google:**
   - Kênh GA4 tên là **"AI Assistant" (số ít)**. Quy tắc: medium = `ai-assistant`, hoặc referrer thuộc danh sách AI assistant của Google. Kênh này **loại trừ AI Overviews và AI Mode**; hai tính năng đó nằm trong Organic Search. ([nguồn](https://support.google.com/analytics/answer/9756891))
   - Báo cáo Generative AI của GSC **chỉ có impressions**, có tab Pages, Countries, Dates (theo giờ Pacific) và Devices. Giới hạn 1.000 dòng. **Chỉ lấy được qua nút Export, tài liệu không nhắc tới API.** Ô hiện "~" hoặc "-" **bị xuất thành 0**. ([nguồn](https://support.google.com/webmasters/answer/16984139))
5. **Còn thiếu tài liệu tham chiếu:** spec nhắc tới `AI_Traffic_Analytics.pdf` (dashboard Looker cũ), nhưng file không có trong `docs/`. Không bắt buộc, vì PDF không phải chuẩn nghiệm thu, nhưng nên bổ sung để đối chiếu bố cục.

## 2. Stack và kiến trúc thực tế

| Thành phần | Thực tế trong repo |
|---|---|
| Ngôn ngữ | Python 3.14, venv `.venv` |
| Giao diện | NiceGUI 3.18 (Quasar/Vue), server-side; chạy `python -m seo_report web`, chỉ nghe `127.0.0.1` |
| Lưu trữ | SQLite `data/seo.db` (WAL), khoảng 230 MB; 19 bảng |
| Lịch chạy | Windows Task Scheduler → `pythonw -m seo_report daily` (sync GSC → rank → index → classify) |
| Auth Google | OAuth Desktop (`auth.py`), token `secrets/token.json`, scope **chỉ** `webmasters.readonly` |
| Client Google | `googleapiclient.discovery.build("searchconsole","v1")` trong `auth.build_service` |
| Đăng nhập người dùng / phân quyền | **Chưa có** (bước 7 của lộ trình) |
| Test | `unittest`, 45 test, chạy `python -m unittest` |
| Excel | openpyxl (`export.py` cho dữ liệu, `report_excel.py` cho báo cáo sếp) |

Bản đồ module (dòng code):

| File | Vai trò | Tái sử dụng cho AI module |
|---|---|---|
| `auth.py` (48) | OAuth, `get_credentials`, `build_service` | **Mở rộng**: thêm scope `analytics.readonly`, thêm `build_ga4_service` dùng chung credentials. Không tạo flow OAuth mới |
| `config.py` (60) | `Config`, `KeywordSettings`, `RankSettings` | Thêm `AISettings` (GA4 property, allowlist, key event, ngưỡng opportunity) |
| `db.py` (183) | Schema GSC, `connect`, `replace_day` | Thêm bảng tổng theo property; cache GA4 |
| `gsc.py` (45) | `query_day` có phân trang + retry 429/5xx | Thêm hàm truy vấn tổng theo property (`dimensions=[date]`) |
| `urls.py` (255) | `normalize`, phân loại loại URL (8 loại), nhóm | **URLNormalizer** + taxonomy cho Landing pages/Opportunities (spec §3.4 cho phép dùng taxonomy thay contentGroup) |
| `keywords.py` (244) | head/phụ, `weeks()` thứ Hai–CN, `url_period` | Dùng lại `weeks()` và `url_period` cho cột GSC Web ở Page E |
| `report.py`, `report_excel.py`, `web_report.py` | Báo cáo tuần | Sau này thêm khối "AI traffic" vào báo cáo sếp (sau R2) |
| `web.py` | Khung menu, `shell()`, routes | Thêm mục menu "AI Search & GEO" |
| `export.py` | Hàm `_sheet` (bảng phẳng Excel) | Dùng cho export (spec yêu cầu CSV; đề xuất xuất **Excel + CSV**, cùng query state) |

## 3. R0 — Kết nối GA4 (bước mới, chặn mọi bước sau)

Việc cần **bạn** làm:
1. Trong Google Cloud project hiện tại: bật **Google Analytics Data API** (và **Google Analytics Admin API** nếu muốn tool tự liệt kê property).
2. Cho biết **GA4 property ID** của matkinhtamduc.com. Tài khoản Google đang đăng nhập tool phải có ít nhất quyền **Viewer** trên property đó.
3. Chạy lại `python -m seo_report login` để cấp thêm quyền đọc GA4. Màn hình đồng ý của Google sẽ hiện thêm dòng "Xem dữ liệu Google Analytics".

Việc tool làm:
- `auth.SCOPES` thêm `https://www.googleapis.com/auth/analytics.readonly`. Token cũ thiếu scope thì báo "cần đăng nhập lại", không lỗi khó hiểu.
- `login` liệt kê GA4 property truy cập được (Admin API `accountSummaries.list`) để chọn, giống cách đang làm với GSC.
- Thư viện: `google-analytics-data` (client chính thức), **hoặc** dùng `googleapiclient.build("analyticsdata","v1beta")` để không thêm dependency. Đề xuất cách thứ hai, vì đã có sẵn `google-api-python-client`.

## 4. Thiết kế dữ liệu GA4

### 4.1. Truy vấn trực tiếp + cache, không sync hằng ngày

- Spec §5.3 bắt buộc lấy rate/average **ở mức nhóm bằng truy vấn tổng hợp trực tiếp**, không cộng các dòng theo nguồn. Nếu lưu dòng theo ngày × nguồn rồi tự cộng (như cách làm với GSC), mọi khoảng ngày và bộ lọc khác nhau sẽ cho rate sai.
- Vì vậy GA4 **truy vấn trực tiếp Data API theo đúng filter người dùng chọn**, kèm cache trong SQLite (bảng mới `ga4_cache`). Key cache gồm: property, khoảng ngày, kỳ so sánh, filter, dimensions, metrics, chế độ phân loại, phiên bản phân loại, phiên bản schema truy vấn. TTL: kỳ có ngày trong 3 ngày gần nhất 3 giờ; kỳ đã đóng 24 giờ. Có nút làm mới.
- Không cần Redis hay queue; SQLite đủ cho 2–5 người dùng.
- Quota: mỗi truy vấn gửi `returnPropertyQuota=true`, lưu token còn lại để hiện ở Page F (Chất lượng dữ liệu).

### 4.2. Phân loại AI (spec §5)

- **Native:** `sessionDefaultChannelGroup` ∈ {`AI Assistant`, `AI Assistants`}. Google dùng số ít; spec liệt kê cả hai, nên tool chấp nhận cả hai.
- **Fallback:** `sessionSource` thuộc allowlist, khớp **đúng host hoặc subdomain** (không khớp chuỗi con, nên `evilchatgpt.com` bị loại), `sessionMedium` không thuộc nhóm paid.
- Allowlist khởi tạo lấy theo spec, nhưng **phải đối chiếu với danh sách nguồn thật của property** (truy vấn `sessionSource` 90 ngày) trước khi chốt.
- Chế độ mặc định `HYBRID`, kèm bảng đối soát native với hybrid.
- Không bao giờ coi `google` hay `google / organic` là AI.
- Chỉ dùng **một biểu thức filter** cho cả KPI tổng, bảng nguồn, landing page và country, nên các con số thống nhất với nhau.

### 4.3. Chỉ số

| Chỉ số trên UI | Cách lấy | Không làm |
|---|---|---|
| AI Sessions, Engaged sessions, Key events | Truy vấn tổng hợp, `dimensions=[]` | Cộng từ bảng nguồn để ra số tổng |
| Engagement rate | Metric gốc `engagementRate` của truy vấn tổng | Cộng các % |
| Thời gian tương tác TB/phiên | `userEngagementDuration / sessions` của **cùng một** truy vấn tổng | Cộng `averageSessionDuration` theo nguồn |
| Session key event rate | Metric gốc `sessionKeyEventRate` | `keyEvents / sessions` |
| Key events / 100 phiên | `100 × keyEvents / sessions`, có nhãn riêng | Gọi là "Conversion rate" |
| AI share | AI sessions / mẫu số ghi rõ (mặc định: tổng sessions của property) | Không ghi mẫu số |

Trước truy vấn phức tạp: gọi `getMetadata` (một lần, cache 24 giờ) và `checkCompatibility`. Trường không tương thích thì trả về `unsupported`, không hiện 0.

## 5. Ranh giới GSC Web và Generative AI

- Mọi số GSC trong module AI dán nhãn **"GSC Web Search (gồm cả nhưng không chỉ AI Overviews/AI Mode)"**. Cấm dán nhãn "AIO impressions".
- **Page E** chỉ đặt hai nhóm cột (GA4 AI referral | GSC Web) cạnh nhau theo URL đã chuẩn hóa (`urls.normalize`), có bộ lọc matched/unmatched. Không nhân chéo hai nguồn với nhau.
- **Lệch múi giờ:** GSC theo giờ Pacific, GA4 theo múi giờ property (cần đọc từ Admin API, nhiều khả năng là Asia/Ho_Chi_Minh). So theo tuần thì lệch không đáng kể; so theo ngày phải có tooltip cảnh báo.
- **Báo cáo Generative AI của GSC (P2):** chỉ nhập file export thủ công. Ô "~" hoặc "-" bị xuất thành 0, nên khi nhập phải đánh dấu `UNKNOWN_ZERO` và không cộng dồn. Giới hạn 1.000 dòng, nên ở scope Pages phải cảnh báo dữ liệu thiếu. Khi chưa nhập file nào, trạng thái là `NOT_CONNECTED`, UI hiện "Chưa có dữ liệu", không hiện 0.

## 6. Kế hoạch triển khai (ánh xạ vào repo)

| Round | Nội dung | File mới / sửa | Điều kiện để qua bước |
|---|---|---|---|
| **R0** | Kết nối GA4 + sửa tổng GSC theo property | `auth.py`, `config.py`, `cli.py` (login), `gsc.py`, `db.py` (bảng `gsc_site_daily`), `report.py` | Đăng nhập lại thành công; tổng site khớp GSC UI |
| R1 | Lõi GA4: client, query builder, phân loại, metadata/compatibility, cache | `ga4.py`, `ai_classifier.py`, `ai_analytics.py` + test | Test bắt buộc §8 đạt; một truy vấn thật khớp GA4 UI |
| R2 | Tổng quan + Nguồn AI | `web_ai.py` (các tab), menu `web.py` | Tổng KPI = truy vấn tổng hợp; có trạng thái loading/empty/error |
| R3 | Trang đích + Địa lý + xuất Excel/CSV | `web_ai.py`, `ai_export.py` | Filter dùng chung; `(not set)` là một dòng riêng |
| R4 | Cơ hội SEO/GEO (GSC Web) | `ai_opportunities.py` | Không có nhãn AI nào gắn vào số GSC |
| R5 | Chất lượng dữ liệu, QA, ảnh chụp | `web_ai.py` (tab F) | Toàn bộ tiêu chí §8 spec |
| R6 | Nhập file GSC Generative AI (tùy chọn) | `ai_import.py` | Có file export thật để đối chiếu cột |

Sau R2 có thể thêm khối "AI traffic" vào báo cáo tuần cho sếp.

## 7. Test sẽ viết (bám theo spec §8)

- **Phân loại:** "AI Assistant" và "AI Assistants"; subdomain hợp lệ; `evilchatgpt.com` bị loại; `google.com` bị loại; paid medium bị loại; một phiên được cả native lẫn fallback nhận diện chỉ tính một lần.
- **Chỉ số:**
  - `0.0243` hiển thị thành `2,43%`;
  - 0 phiên hiển thị `N/A`;
  - 17 key events / 609 phiên ra `2,79 key events / 100 phiên`, không dán nhãn session key event rate;
  - thời gian TB có trọng số: (229×537 + 190×66 + 668×3 + 50×3) / 609 ≈ 226 giây, không phải 1.137 giây.
- **Kỳ so sánh:** độ dài bằng nhau; tuần ISO vắt qua năm; tuần chưa trọn; cảnh báo lệch múi giờ.
- **Truy vấn:** GA4 giả lập kiểm tra phân trang, lỗi 429/403/5xx, metric không tương thích ra `unsupported` (không ra 0), và cùng một filter được dùng cho cả 4 loại truy vấn.
- **GSC:** tổng theo property tách khỏi tổng theo page; nhãn "Web" không bao giờ thành nhãn AI.

## 8. Rủi ro

| Rủi ro | Ảnh hưởng | Giảm thiểu |
|---|---|---|
| Tài khoản Google không có quyền GA4 | Chặn toàn bộ module | Kiểm tra ngay ở R0 |
| App OAuth phải cấp thêm scope | Token cũ hết hiệu lực, cả team phải đăng nhập lại | Làm một lần ở R0; tool báo rõ lý do |
| GA4 thresholding / `(other)` khi chia nhỏ theo landing page × source | Bảng chi tiết không cộng bằng tổng | Hiện cảnh báo; tổng luôn lấy từ truy vấn tổng hợp |
| Số phiên AI nhỏ (PDF tham chiếu: khoảng 609 phiên/90 ngày) | Rate dao động mạnh | Hiện cỡ mẫu, cảnh báo `LOW_SAMPLE_SIZE`, quy tắc AI_ENGAGEMENT_WEAK có ngưỡng mẫu tối thiểu |
| Phạm vi lớn (6 tab, nhiều filter) với một người duy trì không code | Bảo trì khó | Làm theo từng round, mỗi round dùng được ngay |
| Bước 7 (đăng nhập, phân quyền, VPS) chưa làm | Spec yêu cầu permission check | Tạm thời chỉ chạy trên máy (127.0.0.1); phân quyền làm ở bước 7 |

## 8b. Kết quả R0 và quyết định đã chốt (30/10/2026)

- **GA4:** `properties/288379033` ("Tâm Đức – GA4"), múi giờ **Asia/Saigon**, tiền tệ VND. Metadata có đủ mọi dimension và metric ở mục 4.1. Token đã có cả quyền `webmasters.readonly` và `analytics.readonly`.
- **Key events của property:** `purchase`, `Click Messenger`, `add_to_cart`, `Click Zalo`, `booking_success`.
  - **Quyết định:** KPI dùng tổng key events, với rate lấy từ `sessionKeyEventRate` gốc của GA4; kèm một bảng tách riêng từng event.
- **Danh sách nguồn AI thật, 90 ngày (01/08–29/10), tổng 748 sessions.** Kênh native "AI Assistant" có 621 sessions, khớp với khoảng 609 trong dashboard Looker tham chiếu.
- **Quyết định phân loại:**
  - `chatgpt / paid` (113 sessions, kênh Paid Other) là **quảng cáo, không tính vào AI organic**. Hiện thành một dòng "AI trả phí" riêng để tham khảo.
  - Nguồn ghi tắt `gemini`, `perplexity`, `chatgpt`… **được tính là AI** nếu khớp đúng tên (không khớp chuỗi con) và medium không phải trả phí.
  - Thêm `copilot.com` vào allowlist; spec mẫu thiếu tên miền này.
  - `chatgpt.com / zalo` (2 sessions): medium lạ, đưa vào danh sách "cần xem" để đối soát.
- **AI share:** hiện **cả hai** mẫu số, có ghi rõ:
  - trên tổng sessions của site;
  - trên nhóm organic (Organic Search + Organic Social + AI).
- **Tổng GSC theo property:** đã sync 480 ngày vào `gsc_site_daily`; báo cáo tuần đã dùng số này. Tuần 19–25/10: 180.397 impression theo property, so với 327.715 nếu cộng theo page.
- **Còn mở:** R6 (nhập file GSC Generative AI) và file PDF tham chiếu.

## 9. Câu hỏi cần bạn trả lời trước khi sang R0/R1 (đã trả lời 1–3 và 6, xem 8b)

1. **GA4 property ID** của matkinhtamduc.com là gì? Tài khoản đang đăng nhập tool có quyền Viewer trên property đó không?
2. **Key event** nào dùng để đo: tất cả key events, hay một event cụ thể (đặt lịch hẹn, gọi điện, gửi form…)?
3. **Mẫu số của AI share:** tổng sessions của site, hay chỉ nhóm "kênh organic" (Organic Search + Organic Social + AI)? PDF Looker cũ có vẻ so với nhóm organic.
4. Có làm **R6 (nhập file GSC Generative AI)** không? Nếu có, cần một file export thật để xác định đúng các cột.
5. Bổ sung `AI_Traffic_Analytics.pdf` vào `docs/` để đối chiếu bố cục (không bắt buộc).
6. Đồng ý **sửa số "Toàn site" theo tổng property** (mục 1.3) trong R0 không? Sau khi sửa, số impression trong báo cáo tuần sẽ giảm so với các file đã xuất trước đó.
