# SEO Report – Bước 1: lấy dữ liệu GSC về máy

Bước này kết nối Google Search Console, lấy dữ liệu 16 tháng về file SQLite trên máy, và mỗi ngày lấy lại 5 ngày gần nhất.

Dữ liệu được lưu thành 2 bảng:
- `gsc_page_daily`: tổng của từng URL theo ngày, gồm cả các query bị Google ẩn.
- `gsc_query_daily`: từng cặp URL × query theo ngày.

## 1. Chuẩn bị Google Cloud (làm một lần, khoảng 15 phút)

1. Vào https://console.cloud.google.com, tạo project mới, ví dụ `seo-report-tamduc`.
2. Vào **APIs & Services → Library**, tìm **Google Search Console API** và bấm **Enable**.
3. Vào **APIs & Services → OAuth consent screen**:
   - **User type**: chọn **Internal** nếu tài khoản Google bạn dùng cho GSC thuộc Google Workspace của công ty. Nếu là Gmail cá nhân thì chọn **External**.
   - Điền tên app (ví dụ `SEO Report`) và email hỗ trợ.
   - **Scopes**: không cần thêm gì.
   - Nếu chọn **External**: sau khi tạo xong, bấm **Publish app** để chuyển sang **In production**.
     > Quan trọng: app để ở chế độ **Testing** thì Google tự hủy quyền truy cập sau 7 ngày, tool sẽ ngừng lấy dữ liệu. Khi đăng nhập, Google sẽ hiện cảnh báo "ứng dụng chưa xác minh". Đây là bình thường với app nội bộ: bấm **Nâng cao → Tiếp tục**.
4. **Tạo OAuth client**: vào **APIs & Services → Credentials → Create credentials → OAuth client ID**, chọn **Desktop app**. Tải file JSON về, đổi tên thành `client_secret.json`, rồi đặt vào thư mục `secrets/` trong project.

## 2. Cài đặt

Đặt project ở đường dẫn ngắn, ví dụ `D:\Projects\seo-report`. Đường dẫn quá dài sẽ khiến Windows không nạp được thư viện mã hóa (lỗi "The filename or extension is too long").

```powershell
cd D:\Projects\seo-report
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy config.example.toml config.toml
```

## 3. Đăng nhập và kiểm tra quyền

```powershell
.\.venv\Scripts\python -m seo_report login
```

Trình duyệt sẽ mở ra, bạn đăng nhập bằng tài khoản Google có quyền trên GSC. Sau đó lệnh sẽ liệt kê các property bạn truy cập được.

Mở `config.toml` và sửa `site_url` cho khớp chính xác một dòng trong danh sách đó, ví dụ `sc-domain:matkinhtamduc.com` hoặc `https://matkinhtamduc.com/`.

## 4. Lấy dữ liệu

```powershell
.\.venv\Scripts\python -m seo_report sync --backfill   # lần đầu: lấy 16 tháng, khoảng 15–30 phút
.\.venv\Scripts\python -m seo_report sync              # các lần sau: lấy lại 5 ngày gần nhất và bù ngày còn thiếu
.\.venv\Scripts\python -m seo_report stats             # xem tóm tắt dữ liệu và top 10 URL
```

Nếu lệnh bị ngắt giữa chừng, cứ chạy lại: những ngày đã lấy xong sẽ được bỏ qua.

## 5. Chạy tự động mỗi ngày (Windows Task Scheduler)

Đã tạo sẵn task **SEO Report sync**:
- Chạy `pythonw -m seo_report daily` lúc 6:00 mỗi ngày: lấy dữ liệu GSC rồi phân loại tối đa 300 URL mới. Chạy ẩn, không mở cửa sổ nên không lo tắt nhầm.
- Nếu 6:00 máy đang tắt, task chạy bù khi bạn bật máy.
- Nếu lỗi (ví dụ mất mạng), task thử lại tối đa 3 lần, mỗi lần cách 15 phút.

Kết quả mỗi lần chạy được ghi vào `data\sync.log`.

Chạy tay ngay lập tức:

```powershell
Start-ScheduledTask -TaskName "SEO Report sync"
```

Task chỉ chạy khi bạn đã đăng nhập Windows. Muốn xem hoặc tắt task: mở **Task Scheduler**, tìm **SEO Report sync**.

## 6. Quản lý URL (giao diện)

Nhấp đúp file `mo_giao_dien.cmd`, trình duyệt sẽ tự mở trang http://127.0.0.1:8080. Đóng cửa sổ đen là tắt giao diện. Giao diện chỉ mở được trên máy này, vì chưa có đăng nhập.

| Tab | Dùng để |
|---|---|
| Trong nhóm | Xem các URL trong nhóm (mặc định là "SEO chủ lực"), bỏ bớt URL, sửa loại |
| Thêm link | Dán danh sách link, mỗi link một dòng. Tool tự bỏ #mục, ?utm_…, xử lý www và / cuối |
| Gợi ý | Danh sách URL nhiều click nhất 90 ngày qua chưa có trong nhóm; tích chọn rồi thêm vào nhóm |
| Tất cả URL | Tìm kiếm, lọc theo loại, sửa loại khi bị phân loại sai |
| Nhật ký | Xem ai đã thêm, bỏ, sửa gì và lúc nào |

Cách tool phân loại URL:
1. Theo quy tắc đường dẫn. Các quy tắc nằm trong `seo_report/urls.py`.
2. Với trang cấp 1 không khớp quy tắc nào, tool mở trang và đọc schema: `Product` là Sản phẩm, `Article` là Blog, có địa chỉ là Cửa hàng.
3. Sửa tay trên giao diện. Loại đã sửa tay luôn được giữ, không bị ghi đè.

Mỗi sáng, sau khi lấy dữ liệu, tool tự đọc schema cho tối đa 300 URL mới. Muốn chạy tay:

```powershell
.\.venv\Scripts\python -m seo_report classify
```

## 6b. Bố cục chung (từ 30/10/2026)

- **Menu trái chia nhóm:** Tổng quan · Báo cáo tuần · SEO (Hiệu suất URL, Từ khóa & rank, Index) · AI & GEO · Quản trị (Quản lý URL, Chất lượng dữ liệu).
- **Thanh trên cùng có ô chọn tuần và nhóm URL dùng chung cho mọi màn.** Đổi ở đây thì Tổng quan, Báo cáo tuần, Hiệu suất URL và AI Search & GEO cùng theo. Lựa chọn được nhớ theo trình duyệt.
- **Tổng quan (trang chủ):** Google Search, traffic AI (GA4), AI Overviews, rank, index và URL tăng/giảm của tuần trong một màn. Mỗi khối có "Xem chi tiết" để đi sâu.
- **Báo cáo tuần:** cùng các khối đó, thêm nhận xét gửi sếp và nút xuất Excel.
- **Báo cáo tháng** (menu, hoặc nút Tuần | Tháng trong màn Báo cáo): chỉ tháng đã đủ dữ liệu GSC, so với tháng trước. Số tính thẳng từ dữ liệu ngày của tháng (không cộng các tuần). Thêm xu hướng 12 tháng, theo loại trang, top 10 URL, top 10 query, ô Nhận xét tháng + Kế hoạch tháng sau; xuất Excel. GA4 (traffic AI) so với cùng số ngày liền trước.

## 7. Màn URL (Hiệu suất URL)

- **Cột giữa:** danh sách URL của nhóm, gồm click của tuần đang chọn, mức thay đổi so với tuần trước, head KW, và nhãn "lệch target" nếu có.
- **Cột phải:** chi tiết URL đang chọn:
  - 4 chỉ số so với tuần trước;
  - tỷ lệ click nhìn thấy theo keyword;
  - ô gán target KW;
  - head KW và tối đa 5 keyword phụ;
  - cannibalization;
  - danh sách keyword bị loại, kèm lý do;
  - biểu đồ 12 tuần.
- **Head KW và keyword phụ tính trên 28 ngày gần nhất**, còn số liệu hiển thị theo tuần đang chọn. Các ngưỡng nằm trong mục `[keywords]` của `config.toml`.
- **So khớp target KW** không phân biệt dấu, chữ hoa hay khoảng trắng: "trong kinh zeiss" vẫn khớp với "tròng kính zeiss".

## 8. Xuất Excel dữ liệu

Bấm nút **Xuất dữ liệu (Excel)** ở cột trái của màn URL. File xuất theo nhóm và tuần đang chọn, gồm 6 sheet. Mọi sheet là bảng phẳng, cố định dòng tiêu đề, bật sẵn bộ lọc, làm pivot được.

| Sheet | Mỗi dòng là |
|---|---|
| Thông tin | Kỳ dữ liệu, ngưỡng lọc keyword, thời điểm xuất, các lưu ý khi đọc số |
| Tổng quan | Một loại URL, kèm dòng "Tất cả": chỉ số tuần này so với tuần trước |
| URL | Một URL: target KW, head KW, khớp/lệch, chỉ số so với tuần trước, % click nhìn thấy theo keyword |
| URL_Keyword | Một cặp URL × query: vai trò (Head/Phụ/Bị loại), lý do loại, URL mạnh hơn, số liệu 28 ngày, tuần này, tuần trước |
| Cannibalization | Một cặp query × URL cho các query có từ 2 URL cùng nhận |
| URL_Daily | Một URL × một ngày, 12 tuần |

Hai sheet lịch sử rank sẽ được thêm khi làm phần check rank.

## 8b. Báo cáo tuần cho sếp

Màn **Báo cáo tuần**:
1. Chọn tuần (thứ Hai đến Chủ nhật) và nhóm URL ở thanh trên cùng.
2. Xem trước nội dung báo cáo:
   - KPI GSC của toàn site và của nhóm, so với tuần trước;
   - xu hướng click 8 tuần;
   - rank thực tế;
   - top 10 URL tăng và top 10 URL giảm click.
3. Viết **nhận xét** rồi bấm **Lưu nhận xét**. Nhận xét được lưu riêng cho từng tuần.
4. Bấm **Xuất báo cáo (Excel)**. File gồm một sheet định dạng sẵn, có biểu đồ và in vừa một trang ngang. Nhận xét được đặt lên đầu.

Cách tính:
- Top URL tăng/giảm chỉ xét URL có từ 20 click ở một trong hai tuần, xếp theo số click chênh lệch.
- Rank lấy lần check mới nhất từ đầu tuần báo cáo đến hết tuần kế tiếp, vì rank thường được check vào thứ Ba, trước buổi báo cáo. Báo cáo ghi rõ ngày check.
- Position TB (GSC) là số trung bình của GSC, không phải thứ hạng.

## 8c. Kết nối GA4 (module AI Search & GEO)

1. Trong Google Cloud project đang dùng cho GSC, vào **APIs & Services → Library**, bật cả hai API:
   - **Google Analytics Data API**
   - **Google Analytics Admin API**
2. Chạy lại lệnh đăng nhập. Màn hình đồng ý của Google sẽ có thêm dòng "Xem dữ liệu Google Analytics":

```powershell
.\.venv\Scripts\python -m seo_report login
```

3. Lệnh trên in ra danh sách GA4 property. Copy dòng `properties/…` của matkinhtamduc.com, dán vào `ga4_property` trong `config.toml`.
4. Kiểm tra kết nối:

```powershell
.\.venv\Scripts\python -m seo_report ga4-check
```

Lệnh này in ra: múi giờ của property, danh sách key event, các trường mà module AI cần còn thiếu không, và sessions theo kênh, trong đó có kênh "AI Assistant".

Token chỉ có quyền GSC vẫn chạy được lịch lấy dữ liệu hằng ngày. Chỉ các chức năng GA4 mới yêu cầu đăng nhập lại.

**Màn AI Search & GEO** (menu trái) có bảy tab:
- **Tổng quan:** KPI traffic từ AI assistant, tỷ lệ AI, so sánh với Organic Search/Social, biểu đồ xu hướng, key event theo từng event.
- **Nguồn AI:** ChatGPT, Gemini…; bấm một nguồn để lọc cả màn; tải CSV.
- **Trang đích:** phiên AI theo loại trang và theo từng trang; bấm một trang để xem chi tiết.
- **Địa lý:** quốc gia của người truy cập, ma trận quốc gia × nguồn.
- **AI trên Google:** số lần site hiện trong AI Overviews / AI Mode, lấy từ file export của GSC (GSC không có API cho số này). Mỗi tuần: GSC → Hiệu suất → Generative AI (Search) → chọn "3 tháng qua" → Export → Download CSV, rồi kéo file .zip vào ô nhập. Không lọc thêm trang/quốc gia/thiết bị trước khi xuất. Nhập trùng ngày thì số theo ngày lấy từ file mới nhất, không cộng dồn; nhập nhầm thì ẩn lần nhập trong "Lịch sử nhập". Báo cáo tuần tự có khối này khi file phủ đủ 7 ngày của tuần.
- **Cơ hội SEO/GEO:** đặt GA4 AI cạnh GSC Web theo URL. Gợi ý theo 3 quy tắc, ngưỡng chỉnh được. Cột GSC là Google Search tổng, không phải số AI.
- **Chất lượng dữ liệu:** kết nối, độ mới dữ liệu GSC, lịch chạy hằng ngày, đối soát tổng, nguồn có tên giống AI nhưng không được tính, cài đặt đang dùng. Mở tab này đầu tiên khi thấy số liệu lạ.

Bộ lọc (kỳ, nguồn, quốc gia, trang đích, tab) được ghi lên địa chỉ trang: gửi link cho người khác thì họ thấy đúng màn đó. Khi kỳ trước có dưới 10 phiên, cột "so với kỳ trước" hiện số kỳ trước thay vì % (1 → 17 phiên = +1.600% dễ gây hiểu lầm).

Cách tính:
- Mọi tỷ lệ lấy nguyên từ GA4, không tự cộng giữa các nguồn.
- Traffic có medium trả phí (ví dụ `chatgpt / paid`) được tách riêng, không tính là AI.
- AI Overviews/AI Mode của Google không tách được trong GA4, vì GA4 tính phần đó vào Organic Search.

Chi tiết cách tính và đối soát: `docs/R1_REPORT.md` đến `docs/R5_REPORT.md`. In nhanh số liệu: `python -m seo_report ai-summary --days 28`.

## 8d. Xuất Google Sheets / Google Slides / PDF lên Google Drive

Nút **Xuất** (màn Báo cáo, AI, Hiệu suất URL, Từ khóa & rank) có: Tải Excel về máy · Google Sheets · (báo cáo tuần/tháng) Google Slides và PDF · Chọn folder Drive.

Cài đặt một lần:
1. Trong Google Cloud project đang dùng cho GSC, vào **APIs & Services → Library**, bật **Google Drive API**.
2. Đăng nhập lại để cấp thêm quyền Drive. Trên màn hình đồng ý, tích ô cho phép tệp Google Drive:

```powershell
.\.venv\Scripts\python -m seo_report login
```

Cách hoạt động:
- **Quyền tối thiểu (drive.file):** tool chỉ thấy và sửa file/folder do chính nó tạo, không đọc được file khác trong Drive.
- **Folder:** lần đầu, tool tạo folder **"SEO Report – matkinhtamduc.com"** trong Drive. Dùng **Chọn folder Drive…** để chọn hoặc tạo folder con (ví dụ "Báo cáo tháng"). Muốn sếp xem, chia sẻ folder gốc đó trên Drive.
- **Định dạng:** Google Sheets do Drive chuyển từ file Excel, nên nội dung giống hệt file Excel. PDF xuất từ chính bộ Google Slides, nên giống hệt slide. PDF được lưu lên Drive và tải về máy.

## 8e. Công việc & OKR (đọc từ Google Sheet)

Màn **Công việc & OKR** (`/okr`) và khối **Tiến độ công việc** trong báo cáo tuần/tháng (màn, slide, Excel) lấy dữ liệu từ sheet OKR của team. Tool chỉ đọc, mọi cập nhật làm trên sheet.

Cài đặt một lần:
1. Trong `config.toml`, mục `[okr]`: `sheet` = link Google Sheet; `okr_tab` và `weekly_tab` = tên 2 tab (mặc định "OKRs 3 tháng", "Weekly Task Tracker").
2. Trong Google Cloud project, bật **Google Sheets API**, rồi chạy lại `login` và tích quyền xem bảng tính (chỉ đọc).
3. Khi màn OKR không còn hiện chip "Đang đọc qua link công khai", tắt chia sẻ công khai của sheet.

Cách hoạt động:
- Đồng bộ trong lệnh `daily` hoặc bấm **Đồng bộ ngay** trên màn OKR.
- Sheet không có cột ngày hoàn thành. Tool ghi lại trạng thái mỗi ngày đồng bộ. "Hoàn thành trong tuần/tháng" là ngày tool thấy trạng thái đổi sang Hoàn thành. Việc đã xong trước lần đồng bộ đầu tiên chỉ được tính vào kỳ chứa ngày kết thúc.
- "Trễ hạn" là việc đã qua End date mà chưa Hoàn thành, tính đến hôm nay.
- Weekly Task Tracker: cột "Ngày" chỉ cần ghi ở dòng đầu mỗi tuần. Nên nhập ngày có năm (dd/mm/yyyy) để không bị đoán sai năm.

## 9. Check rank (DataForSEO)

**Volume keyword:** cột Volume lấy từ DataForSEO (Google Ads, Việt Nam), mỗi keyword một lần mỗi tháng (lịch hằng ngày tự lấy; keyword mới thêm thì lấy ngay). Chi phí tính chung ngân sách 20 USD (khoảng 0,09 USD mỗi lần cho tới 1.000 keyword). Google gộp các biến thể gần nhau (ví dụ "mắt kính" và "kính mắt") thành cùng một số.

1. Đăng ký tại https://app.dataforseo.com/register. Tài khoản mới có sẵn 1 USD dùng thử.
2. Mở https://app.dataforseo.com/api-access, rồi dán **API login** và **API password** vào file `secrets\dataforseo.toml`. API password **khác** mật khẩu đăng nhập web.
3. Đưa keyword vào danh sách theo một trong hai cách:
   - **Màn Check rank:** dán keyword, mỗi dòng một keyword. Muốn gán URL mục tiêu thì thêm URL sau dấu `|`, hoặc dán 2 cột từ Excel.
   - **Màn URL:** bấm ☆ cạnh keyword. URL đang xem sẽ thành URL mục tiêu.
4. Đặt **lịch chung** ở màn Check rank, chọn một trong ba kiểu:
   - các thứ trong tuần (ví dụ thứ 2 và thứ 5);
   - một ngày trong tháng;
   - chỉ khi bấm **Check ngay**.

   Nếu máy tắt đúng ngày theo lịch, lần chạy sau sẽ check bù.
5. Chọn **độ sâu**:
   - **Tự động:** lần đầu check tới top 30; các lần sau dựa vào vị trí check lần trước (≤ 8 → top 10, ≤ 18 → top 20, còn lại → top 30). Không dùng position GSC, vì đó là số trung bình, không phải rank;
   - hoặc cố định top 10, 20, 30, 50 hoặc 100.

   Mỗi 10 kết quả tính là 1 trang, giá khoảng 0,0006 USD/trang.

Bảng ở màn Check rank có các cột: Vị trí (kèm mũi tên tăng/giảm), Vị trí cũ, Vị trí tốt nhất, Cập nhật, Liên kết (URL của site đang xếp hạng), URL mục tiêu (cảnh báo khi Google xếp hạng URL khác), Biểu đồ lịch sử. Nút **Xuất Excel** xuất toàn bộ bảng kèm lịch sử.

Về ngân sách (mục `[rank]` trong `config.toml`):
- Không cho thêm keyword nếu ước tính chi phí tháng vượt ngân sách.
- Cảnh báo khi ước tính đạt 80%.
- Ngừng gửi yêu cầu khi tiền đã dùng trong tháng chạm ngân sách.

Chạy tay theo lịch:

```powershell
.\.venv\Scripts\python -m seo_report rank
```

## 10. Check index (GSC URL Inspection API)

Mỗi sáng, tool đọc sitemap rồi kiểm tra index tối đa **1.500 URL**. Quota của Google khoảng 2.000 URL/ngày, phần còn lại để dành cho nút "Kiểm tra ngay". Thứ tự ưu tiên:

1. URL trong nhóm (SEO chủ lực…): 7 ngày một lần.
2. URL mới xuất hiện trong sitemap: sau 3, 7 và 14 ngày.
3. URL có impression trong 28 ngày: 30 ngày một lần.
4. Còn lại, kể cả URL cũ/kỹ thuật: xoay vòng, URL chưa kiểm tra lần nào được ưu tiên trước.

Trên màn URL:
- Nhãn **"rớt index"** (đỏ) khi URL trước đó đã index nhưng giờ không còn.
- Nhãn **"chưa index"** (cam) khi URL chưa được index.
- Phần chi tiết hiện trạng thái index, lần crawl gần nhất, và cảnh báo khi Google chọn canonical khác URL.

Sheet URL trong Excel có thêm 5 cột về index.

**Màn Check index** (menu trái): dán URL cần kiểm tra, ví dụ bài mới đăng, mỗi dòng một URL.
- Tool kiểm tra ngay, trong phần quota còn lại của ngày.
- Sau đó tự kiểm tra lại sau 3, 7 và 14 ngày, cho đến khi Google index.
- Quá 14 ngày vẫn chưa index thì trạng thái chuyển đỏ.
- Mỗi URL kèm cột "Có trong sitemap" và link mở thẳng trang kiểm tra URL trong Search Console, để bạn tự bấm "Yêu cầu lập chỉ mục" nếu cần.

Tool **không gửi yêu cầu index** thay bạn. Google Indexing API chỉ được phép dùng cho trang tuyển dụng và livestream; dùng cho trang thường là vi phạm hướng dẫn của Google.

Chạy tay:

```powershell
.\.venv\Scripts\python -m seo_report index --limit 200
```

Phân loại lại toàn bộ URL đang chờ (chạy tay):

```powershell
.\.venv\Scripts\python -m seo_report classify
```

## 8f. KPI cam kết (sheet mẫu)

Màn **KPI cam kết** (`/kpi`) và khối **Tiến độ KPI** trên đầu màn Tổng quan / Báo cáo đọc số cam kết từ một Google Sheet.

**Sheet mẫu:** trên màn KPI cam kết, bấm **Tạo sheet mẫu**. Tool tạo sheet "KPI cam kết SEO – matkinhtamduc.com" trong folder Drive của tool, gồm 2 tab:
- **KPI cam kết**: tên dự án, **ngày bắt đầu** (để trống thì tool chưa chấm), và bảng theo tháng dự án: giai đoạn, % từ khóa top 3 / 5 / 10, phiên Organic Search (GA4). Ô `-` hoặc trống nghĩa là tháng đó không cam kết. Sheet điền sẵn số của dự án mẫu 6 tháng để làm khung.
- **Từ khóa cam kết**: từ khóa + URL mục tiêu (điền sẵn các từ đang check rank). Khi đồng bộ, từ khóa mới được tự thêm vào danh sách check rank.

Có thể dùng sheet khác bằng cách dán link, miễn đúng tên 2 tab.

**Cách tính:**
- Tháng dự án là từ ngày bắt đầu đến trước cùng ngày tháng sau (1/11 → 30/11).
- Thứ hạng lấy theo **lần check DataForSEO cuối trong tháng**. URL khác URL mục tiêu vẫn tính; chưa check hoặc ngoài độ sâu là chưa đạt.
- Phiên là GA4 kênh Organic Search toàn site. Tháng đang chạy có thêm **dự báo cuối tháng** theo tốc độ hiện tại.

**Đồng bộ:** chạy cùng lệnh `daily`, hoặc bấm **Đồng bộ ngay**. Mỗi lần nội dung sheet đổi, tool lưu một phiên bản. Tháng đã qua chấm theo phiên bản có hiệu lực cuối tháng đó, nên điều chỉnh KPI về sau không làm đổi kết quả đã chốt.

## 11. Cho sếp và team dùng từ máy khác

Có hai đường. Cả hai dùng chung phân quyền trong `config.toml`, mục `[access]`:
- `editors`: được sửa. Gồm check rank (tốn tiền), thêm/bỏ keyword, sửa nhóm URL, target KW, nhập file GSC, nhận xét báo cáo, đồng bộ OKR, lưu vào Drive.
- `viewers`: chỉ xem và tải Excel / PowerPoint về máy. Không thấy màn Quản lý URL, không thấy nút sửa.
- Email không có trong hai danh sách bị chặn. Mở thẳng trên máy này (http://127.0.0.1:8080) luôn có quyền sửa.

Hiện tại: `editors = ["bt.thinh2010@gmail.com"]`, `viewers = ["congdat192@gmail.com"]` (sếp).

Cả hai đường đều cần tool chạy nền trên máy này: xem **Bước 4** ở mục 11b.

### 11a. Tailscale (đang dùng, miễn phí, không cần tên miền)

Mỗi người xem cài app Tailscale và đăng nhập bằng Gmail của mình. Tailscale tạo một mạng riêng giữa các máy đó: chỉ người được mời mới thấy tool, không ai trên internet thấy. Gói miễn phí cho tối đa 3 người.

**Trên máy chạy tool (bạn làm):**
1. Tải Tailscale cho Windows tại tailscale.com/download, cài và đăng nhập bằng Google **bt.thinh2010@gmail.com**.
2. Bật HTTPS: trang quản trị login.tailscale.com → **DNS** → bật **MagicDNS** và **HTTPS Certificates**.
3. Mở PowerShell, cho Tailscale chuyển tiếp vào tool (chạy nền, tự bật lại khi khởi động máy):

```powershell
tailscale serve --bg 8080
```

   Lệnh in ra địa chỉ dạng `https://ten-may.ten-mang.ts.net`. Đó là địa chỉ gửi cho sếp.
4. Mời sếp: trang quản trị → **Users → Invite users** → nhập **congdat192@gmail.com**.

**Trên máy / điện thoại của sếp:** mở thư mời, cài app Tailscale, đăng nhập Google congdat192@gmail.com, bật app. Rồi mở địa chỉ `https://ten-may.ten-mang.ts.net`. Thanh trên của tool sẽ có chip **Chỉ xem**.

Nếu sếp thấy màn "Không có quyền truy cập · Chưa đăng nhập Tailscale" thì Tailscale chưa gửi email người dùng sang tool. Tool chặn để an toàn; báo lại để kiểm tra.

### 11b. Cloudflare Tunnel + Access (khi có quyền Cloudflare của matkinhtamduc.com)

Tool vẫn chạy trên máy này, chỉ nghe ở 127.0.0.1. Người ngoài vào qua Cloudflare: Cloudflare bắt đăng nhập bằng mã 6 số gửi qua email, chỉ email trong danh sách mới nhận được mã, rồi mới chuyển yêu cầu về máy này. Không mở cổng nào trên router. Máy phải bật và đã đăng nhập Windows thì người khác mới vào được.

**Bước 1.** Email đã điền ở `[access]` (xem đầu mục 11).

**Bước 2. Tạo ứng dụng Access trước** (để địa chỉ chưa bao giờ mở công khai). Vào dash.cloudflare.com → **Zero Trust**. Lần đầu: đặt tên team và chọn gói **Free** (miễn phí đến 50 người; Cloudflare có thể yêu cầu thêm thẻ, bạn tự nhập).
1. **Access → Applications → Add an application → Self-hosted.**
2. Tên: `SEO Report`. Domain: `seo` . `matkinhtamduc.com`. Session: 24 giờ.
3. Policy: tên `Team`, Action **Allow**, Include → **Emails**: liệt kê đúng các email ở bước 1.
4. Login methods: **One-time PIN**.
5. Lưu xong, mở lại ứng dụng, chép **Application Audience (AUD) Tag**. Chép thêm **team domain** (Settings → Custom Pages, dạng `tenteam.cloudflareaccess.com`). Điền vào `config.toml`:

```toml
team_domain = "tenteam.cloudflareaccess.com"
aud = "chuỗi AUD vừa chép"
```

Có hai dòng này, tool tự kiểm tra chữ ký đăng nhập của Cloudflare, không chỉ tin vào email trong header.

**Bước 3. Tạo Tunnel.** Zero Trust → **Networks → Tunnels → Create a tunnel → Cloudflared**, đặt tên `seo-report`, chọn **Windows**.
1. Cloudflare hiện một lệnh cài có chứa token bí mật. Tự chạy lệnh đó trong PowerShell (Run as Administrator). Không gửi token cho ai, kể cả Claude.
2. **Public hostname**: Subdomain `seo`, Domain `matkinhtamduc.com`, Service **HTTP**, URL `127.0.0.1:8080`.

**Bước 4. Cho tool chạy nền khi đăng nhập Windows** (task **SEO Report web**):

```powershell
$a = New-ScheduledTaskAction -Execute "D:\Projects\seo-report\.venv\Scripts\pythonw.exe" -Argument "-m seo_report web --port 8080 --no-open" -WorkingDirectory "D:\Projects\seo-report"
$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "SEO Report web" -Action $a -Trigger $t -Settings $s
Start-ScheduledTask -TaskName "SEO Report web"
```

Sau khi sửa code hoặc `config.toml`, khởi động lại: `Stop-ScheduledTask -TaskName "SEO Report web"; Start-ScheduledTask -TaskName "SEO Report web"`.

**Bước 5. Kiểm tra** bằng điện thoại dùng 4G (không dùng wifi công ty): mở https://seo.matkinhtamduc.com. Cloudflare sẽ hỏi email và gửi mã 6 số. Người chỉ xem thấy chip **Chỉ xem** ở thanh trên.

Thêm hoặc bớt người: sửa cả **policy trên Cloudflare** lẫn `[access]` trong `config.toml`, rồi khởi động lại tool.

## 12. Bản xem tĩnh trên Vercel (để show nhanh, có mật khẩu)

Lệnh `export-static` chụp số liệu hôm nay thành một trang web chỉ đọc, gồm 4 tab: Báo cáo tuần, Báo cáo tháng, Công việc & OKR, Từ khóa & rank.

Số liệu trong trang được mã hóa bằng mật khẩu bạn đặt (AES-256, khóa sinh từ mật khẩu qua 600.000 vòng PBKDF2). Ai có link mà không có mật khẩu chỉ thấy ô nhập mật khẩu, tải file về cũng không đọc được số. Trang không chứa token Google, khóa DataForSEO hay file dữ liệu.

Bản tĩnh **không** tự cập nhật, **không** đổi tuần/tháng hay check rank được. Muốn số mới thì xuất lại rồi đẩy lại.

**Xuất** (gõ mật khẩu 2 lần, màn hình không hiện chữ; mật khẩu không lưu ở đâu):

```powershell
.\.venv\Scripts\python -m seo_report export-static --out dist
```

**Đẩy lên Vercel** (lần đầu Vercel hỏi đăng nhập và tên project, ví dụ `tamduc-seo-report`, khi đó địa chỉ là `https://tamduc-seo-report.vercel.app`):

```powershell
npx vercel deploy dist --prod
```

Gửi sếp link, còn mật khẩu gửi riêng qua kênh khác (ví dụ Zalo). Muốn đổi mật khẩu: xuất lại với mật khẩu mới rồi đẩy lại, mật khẩu cũ hết tác dụng ngay. Trang có `noindex` nên Google không lập chỉ mục.

## Giới hạn cần biết

- GSC chỉ trả tối đa khoảng 50.000 dòng URL × query mỗi ngày cho một property. Site lớn có thể bị thiếu các query đuôi dài. Bảng tổng theo URL không bị ảnh hưởng.
- Tổng click của các query luôn nhỏ hơn click của URL, vì Google ẩn các query hiếm.
- Token đăng nhập gắn với tài khoản cá nhân của bạn. Nếu bạn đổi mật khẩu, thu hồi quyền, hoặc tài khoản mất quyền GSC, chạy lại lệnh `login`.

## Kiểm tra code

```powershell
.\.venv\Scripts\python -m unittest -v
```
