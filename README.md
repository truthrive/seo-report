# SEO Report

Tool báo cáo SEO và GEO tự chạy (self-hosted) cho người làm SEO và agency quản lý nhiều website. Số liệu lấy thẳng từ Google Search Console, Google Analytics 4 và DataForSEO, lưu trên máy của bạn. Mỗi khách hàng có tài khoản riêng và chỉ thấy báo cáo của website mình.

**Tính năng chính**
- **Nhiều website:** mỗi website là một dự án có cấu hình và file dữ liệu riêng. Đổi website ở thanh trên cùng.
- **Báo cáo tuần / tháng** cho quản lý hoặc khách hàng: kết luận, KPI cam kết, kết quả SEO, kết quả GEO, thứ hạng, công việc. Xuất Excel, Google Sheets, Google Slides, PDF.
- **SEO:** hiệu suất từng URL (head keyword, keyword phụ, cannibalization), check rank qua DataForSEO có trần ngân sách, check index (URL Inspection API), nhóm URL, phân loại loại trang.
- **GEO / AI Search:** traffic từ ChatGPT, Gemini, Perplexity… (GA4), mức hiện diện trong AI Overviews / AI Mode (file export GSC), cơ hội SEO/GEO theo URL.
- **KPI cam kết và OKR** đọc từ Google Sheet, chấm theo tháng dự án.
- **Phân quyền:** Quản trị, Team (mọi website hoặc từng website), Khách hàng. Đăng nhập bằng email + mật khẩu, nhật ký phân quyền, trạng thái online.

---

## 1. Cài đặt

### 1.1 Google Cloud (làm một lần, khoảng 15 phút)

1. Vào https://console.cloud.google.com, tạo project mới, ví dụ `seo-report`.
2. **APIs & Services → Library**, bật các API:
   - Google Search Console API
   - Google Analytics Data API và Google Analytics Admin API (phần GEO, lượt truy cập)
   - Google Drive API (lưu báo cáo lên Drive, copy sheet mẫu gốc) và Google Sheets API (đọc sheet OKR / KPI, ghi tab KPI vào sheet dự án)
3. **APIs & Services → OAuth consent screen**:
   - **User type**: **Internal** nếu tài khoản Google thuộc Google Workspace của công ty; Gmail cá nhân thì **External**.
   - Điền tên app (ví dụ `SEO Report`) và email hỗ trợ.
   - Nếu chọn **External**: bấm **Publish app** để chuyển sang **In production**. Để ở **Testing** thì Google tự hủy quyền sau 7 ngày. Khi đăng nhập, Google báo "ứng dụng chưa xác minh": bấm **Nâng cao → Tiếp tục**.
4. **Credentials → Create credentials → OAuth client ID → Desktop app**. Tải file JSON, đổi tên thành `client_secret.json`, đặt vào thư mục `secrets/`.

### 1.2 Cài tool

Đặt project ở đường dẫn ngắn, ví dụ `D:\Projects\seo-report` (đường dẫn quá dài làm Windows không nạp được thư viện mã hóa).

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy config.example.toml config.toml
```

### 1.3 Đăng nhập Google

```powershell
.\.venv\Scripts\python -m seo_report login
```

Trình duyệt mở ra; đăng nhập bằng tài khoản Google có quyền trên GSC / GA4 của các website, tích đủ các quyền được hỏi. Lệnh in ra danh sách property GSC và GA4 truy cập được.

Mở `config.toml`, điền `site_url` (và `ga4_property` nếu có) của **website đầu tiên** đúng như danh sách vừa in. Các website sau thêm trên giao diện (mục 2).

### 1.4 Lấy dữ liệu lần đầu và mở giao diện

```powershell
.\.venv\Scripts\python -m seo_report sync     # lần đầu tự lấy bù 16 tháng, khoảng 15–30 phút
.\.venv\Scripts\python -m seo_report web      # mở http://127.0.0.1:8080
```

Khi đã cài tool chạy nền (mục 3): nhấp đúp `mo_giao_dien.cmd` để mở trình duyệt vào http://127.0.0.1:8080 (tool chưa chạy thì file tự bật lên). Đây là cùng một bản với bản trên tên miền, dữ liệu dùng chung. Mở thẳng trên máy chạy tool thì vào luôn với toàn quyền, không cần đăng nhập.

---

## 2. Website (dự án)

Màn **Quản trị → Dự án**. Mỗi website là một dự án; website đầu tiên được tạo tự động từ `config.toml` và dùng file `data/seo.db`.

**Thêm website của khách:**
1. Khách thêm email Google của tool vào Search Console và GA4 (quyền đọc).
2. Bấm **Thêm dự án**, chọn property GSC / GA4 trong danh sách (tool tự lấy từ Google), điền từ khóa thương hiệu, ngân sách check rank, link sheet OKR (nếu có).
3. Bấm **Lấy dữ liệu ngay**: lần đầu lấy bù 16 tháng, có thể dùng tool bình thường trong lúc chờ. Logo website được tự lấy.

**Mỗi dự án có:**
- File dữ liệu riêng `data/projects/<mã>.db`: số liệu các khách không bao giờ nằm chung một file.
- Cấu hình riêng (sửa bằng ✏️): GSC, GA4, từ khóa thương hiệu, ngân sách và thiết bị check rank, sheet OKR, logo, quy tắc phân loại URL.
- Sheet dự án (OKRs, Weekly Task Tracker, KPI cam kết trong một file): dự án chưa có thì màn **KPI cam kết** có wizard tạo từ **sheet mẫu gốc** (cài ở cuối màn Dự án).

**Lưu trữ** một dự án: ẩn khỏi danh sách, job hằng ngày bỏ qua, dữ liệu vẫn giữ, khôi phục được. Tool không có nút xóa dự án.

### Phân loại URL

Mỗi URL được gán một loại (Trang chủ, Danh mục, Danh mục con, Sản phẩm, Blog, Cửa hàng, Trang thông tin, URL cũ/kỹ thuật) theo thứ tự ưu tiên:
1. **Sửa tay** trên màn Quản lý URL (luôn được giữ).
2. **Quy tắc chung:** có tham số → URL cũ; `/` → Trang chủ; đường dẫn kiểu WordPress cũ (`/2021/09/…`, `/tag/`, `/page/2/`…) → URL cũ; `/lien-he/`, `/gioi-thieu/`, `/chinh-sach-…`… → Trang thông tin.
3. **Quy tắc riêng của website** (Sửa dự án → Phân loại URL theo đường dẫn), mỗi dòng `mẫu = Loại`, dấu `*` thay cho chuỗi bất kỳ, dòng đầu tiên khớp được dùng:

   ```
   /danh-muc/ = Danh mục
   /danh-muc/* = Danh mục con
   /blog/* = Blog
   /cua-hang* = Cửa hàng
   ```

   Có thể bật "Đường dẫn nhiều cấp không khớp quy tắc nào là URL cũ/kỹ thuật". Lưu quy tắc là tool chạy lại cho các URL đang phân loại theo quy tắc.
4. **Đọc schema** của trang (mỗi sáng tối đa 300 URL mới): `Product` → Sản phẩm, `Article` → Blog, có địa chỉ → Cửa hàng.

---

## 3. Chạy tự động mỗi ngày

Lệnh `daily` làm lần lượt cho **từng website đang hoạt động**: lấy dữ liệu GSC, check rank theo lịch, cập nhật volume keyword, đồng bộ sheet OKR / KPI, check index, phân loại URL mới. Website lỗi (ví dụ mất quyền GSC) được ghi vào `data/sync.log` và không chặn website sau.

Cuối mỗi lần `daily`, tool **sao lưu** mọi file dữ liệu (`data/*.db`, `data/projects/*.db`) và `config.toml` thành một file zip trong thư mục `backups/`, giữ 7 bản gần nhất. Sao lưu chạy được cả khi giao diện đang mở. Chạy tay: `python -m seo_report backup`. Đổi nơi lưu / số bản trong `config.toml`:

```toml
[backup]
dir = "C:/Users/<tên>/OneDrive/SEO Report backup"   # nên là ổ khác hoặc thư mục đồng bộ lên mạng
keep = 7
```

Bản sao lưu **không** gồm `secrets/` (token Google, tài khoản DataForSEO): tự giữ một bản riêng ở nơi an toàn. Khôi phục: tắt tool, giải nén file zip đè vào thư mục tool.

Trên Windows, tạo task trong Task Scheduler chạy lúc 6:00:

```powershell
$a = New-ScheduledTaskAction -Execute "$PWD\.venv\Scripts\pythonw.exe" -Argument "-m seo_report daily" -WorkingDirectory "$PWD"
$t = New-ScheduledTaskTrigger -Daily -At 6am
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "SEO Report sync" -Action $a -Trigger $t -Settings $s
```

**Cho giao diện chạy nền** (tự bật khi đăng nhập Windows, dùng máy này làm máy chủ):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\cai-dat-may-chu.ps1
```

Gỡ: `.\scripts\go-may-chu.ps1`. Rời máy thì khóa màn hình (Win + L), đừng Sign out.

Sửa code hoặc `config.toml` xong: nhấp đúp `khoi_dong_lai.cmd` để bản chạy nền (và bản trên tên miền) dùng code mới. Dữ liệu mới (sync, check rank, cài đặt sửa trên giao diện) hiện ngay, không cần khởi động lại.

---

## 4. Phân quyền và đăng nhập

Màn **Quản trị → Phân quyền** (chỉ Chủ tool).

**Loại tài khoản**
- **Chủ tool:** toàn quyền: mọi website, được sửa, quản lý Dự án, Phân quyền, Ngân sách. Chỉ email trong `editors` của `config.toml` (và người ngồi ở chính máy chạy tool); không tạo thêm trên màn này, không gỡ được.
- **Team · mọi website:** một quyền chung (Team xem / Được sửa) ở mọi website, kể cả website thêm sau.
- **Theo từng website:** chỉ vào các website được gắn, mỗi website một quyền:
  - **Khách hàng:** chỉ Tổng quan, Báo cáo tuần/tháng, KPI cam kết, Công việc & OKR. Không thấy nhóm URL, các màn chi tiết, người khác có quyền.
  - **Team xem:** người nội bộ: thêm các màn SEO / AI (URL, từ khóa, index, chất lượng dữ liệu), không sửa.
  - **Được sửa:** check rank (tốn tiền, có trần ngân sách từng website), sửa từ khóa, nhóm URL, nhận xét, đồng bộ, lưu Drive.

Gợi ý: Content, sếp dùng **Team xem**, SEO dùng **Được sửa**. **Chức danh** (SEO, Content…) chỉ để hiển thị.

**Thêm người:** bấm **Thêm người**, nhập **email hoặc tên đăng nhập** (ví dụ `khach-abc`: 3–32 ký tự chữ không dấu, số, `. _ -`), chức danh, chọn loại, tick các website và quyền. Lưu xong tool tạo mật khẩu (chỉ hiện một lần) và **tin mời soạn sẵn** (link đăng nhập + tên đăng nhập / email + mật khẩu) để gửi qua Zalo / email. Lần đầu đăng nhập, người dùng được gợi ý đặt mật khẩu riêng, có nút bỏ qua để dùng tiếp mật khẩu được cấp.

**Khác:**
- Danh sách chia **Team nội bộ** / **Khách hàng**, tìm theo email, lọc theo website. Hạ quyền hoặc gỡ website phải xác nhận. Tài khoản đã gỡ nằm ở mục **Đã gỡ**, cấp lại được.
- Tab **Nhật ký** ghi mọi thay đổi quyền và đặt mật khẩu: ai làm, lúc nào.
- Chấm trạng thái trên avatar: xanh = đang online, vàng = vắng mặt (không thao tác quá 5 phút), xám = offline kèm lần cuối.
- Mật khẩu lưu dạng băm (scrypt); sai 5 lần liên tiếp khóa 15 phút; đặt lại mật khẩu hoặc gỡ quyền là người đó bị đăng xuất ở lần mở trang kế tiếp.
- **Chặn ở máy chủ:** mỗi lần mở trang tool kiểm tra lại quyền và chỉ mở dữ liệu của website được phép.

---

## 5. Các màn chính

| Màn | Dùng để |
|---|---|
| Tổng quan | Nhịp số liệu 7 / 28 / 90 ngày gần nhất so với cùng số ngày trước: click, lượt hiển thị (GSC), lượt truy cập mọi kênh / Organic / từ AI (GA4), tỷ lệ hiện trong AI; thứ hạng, index, OKR, KPI cam kết, việc cần xử lý (team) |
| Báo cáo | Bản chốt gửi người nhận, chọn **Tuần** hoặc **Tháng** và kỳ so sánh (kỳ trước, cùng kỳ năm trước, hoặc một tuần / tháng bất kỳ trước đó): nhận xét, KPI, SEO, GEO, thứ hạng, công việc; xuất Excel / Sheets / Slides / PDF |
| KPI cam kết | Mỗi cam kết một dòng: từ khóa top 3/5/10 (% hoặc số, bộ chung hay bộ riêng), phiên Organic Search / AI Assistant theo mức tháng hoặc tăng thêm cộng dồn; đọc từ sheet dự án |
| Công việc & OKR | OKR và Weekly Task từ Google Sheet, Gantt, việc trễ hạn |
| Hiệu suất URL | Từng URL: click, head KW, keyword phụ, target KW, cannibalization, index, xu hướng 12 tuần |
| Từ khóa & rank | Check rank DataForSEO, lịch check, độ sâu, lịch sử vị trí, ngân sách |
| Index | Kiểm tra index URL mới (kiểm tra lại sau 3, 7, 14 ngày). Tool không gửi yêu cầu index |
| AI Search & GEO | Traffic AI theo nguồn, trang đích, quốc gia; AI Overviews; cơ hội; chất lượng dữ liệu |
| Quản lý URL | Nhóm URL (ví dụ "SEO chủ lực"), sửa loại trang, nhật ký |

Báo cáo gửi đi chỉ có chỉ số người đọc cần; chỉ số vận hành (index, CTR, position GSC, nhóm URL) để ở các màn chi tiết.

---

## 6. Kết nối thêm

**GA4:** chọn GA4 property khi thêm / sửa dự án. Kiểm tra: `python -m seo_report ga4-check`.

**AI Overviews / AI Mode:** GSC chưa có API cho số này. Mỗi tuần: GSC → Hiệu suất → Generative AI (Search) → 3 tháng qua → Export → Download CSV, rồi kéo file .zip vào tab **AI trên Google** của màn AI Search & GEO.

**Google Drive:** nút **Xuất** lưu Google Sheets / Slides / PDF vào folder "SEO Report – <tên miền>" do tool tạo (quyền `drive.file`: tool chỉ thấy file nó tạo).

**KPI cam kết:** dự án chưa có sheet → màn KPI cam kết hiện wizard 4 bước (thông tin và số tháng → thứ hạng → traffic, baseline lấy từ GA4 → xem lại). Tool copy **sheet mẫu gốc** (dán link ở cuối màn Dự án). Sheet mẫu gốc do tool tải lên (`python scripts/tao-sheet-mau-goc.py <file.xlsx> --upload`, dựng từ bản xuất xlsx của một sheet dự án đang chạy: giữ kế hoạch OKRs, công thức, Gantt theo ngày bắt đầu, xóa chi tiết dự án cũ) thì dùng được ngay với quyền hiện có; sheet mẫu do bạn tự đặt link thì cần quyền Drive đầy đủ, chạy lại `login` một lần thành "Sheet dự án – <tên miền>" trong folder Drive của dự án, ghi 2 tab "KPI cam kết" và "Từ khóa cam kết" và gắn luôn cho cả màn OKR. Chưa cài sheet mẫu gốc thì tool tạo file chỉ có 2 tab KPI. Cũng có thể dán link sheet đã có.

**Sửa cam kết trên tool:** nút **Sửa cam kết** ở màn KPI cam kết mở form (thông tin, baseline, mỗi cam kết một dòng với ô theo tháng, thêm / bỏ dòng, từ khóa). **Lưu vào sheet** ghi lại hai tab KPI cam kết và Từ khóa cam kết theo bố cục mới rồi đồng bộ; các tab khác không đụng tới. Trước khi ghi, tool so sheet với lúc mở form: ai đó vừa sửa trên sheet thì hỏi Tải lại hay Ghi đè. Cần quyền ghi Google Sheets (chạy lại `login` một lần nếu tool báo thiếu quyền). Sheet mẫu cũ bấm Lưu là chuyển sang bố cục mới.

Tab KPI cam kết: khối thông tin (tên, ngày bắt đầu, số tháng, baseline Organic / AI Assistant) và bảng mỗi cam kết một dòng `Loại | Nguồn / Bộ | Đơn vị | tháng 1, 2, …`: **Top N** (% hoặc số từ khóa; *Bộ chung* tính trên cả danh sách, *Bộ riêng* chỉ từ khóa có Top target = N), **Mức tháng** (phiên phải đạt trong tháng), **Tăng thêm cộng dồn** (mức tăng so với baseline hoạch định cho tháng; thực tế = phiên − baseline, cộng dồn; tổng các ô = cam kết cả dự án). Nguồn: Organic Search hoặc kênh AI Assistant của GA4 (ChatGPT, Gemini, Claude…; click từ AI Overviews nằm trong Organic). Mẫu cũ (hàng "Tháng thứ dự án") vẫn đọc được. Tháng dự án tính từ ngày bắt đầu đến trước cùng ngày tháng sau; thứ hạng lấy lần check cuối trong tháng, báo cáo luôn hiện cả % lẫn số từ khóa; mỗi lần sheet đổi tool lưu một phiên bản, tháng đã chốt không bị đổi.

**OKR:** link sheet dự án ở cấu hình dự án (wizard KPI tự điền). Mỗi tab tên bắt đầu bằng "OKRs" là một đợt; tab "Weekly Task Tracker" dùng chung.

**DataForSEO (check rank, volume):**
1. Đăng ký tại https://app.dataforseo.com/register.
2. Dán **API login** và **API password** (khác mật khẩu web) vào `secrets/dataforseo.toml`:
   ```toml
   login = "..."
   password = "..."
   ```
3. Ngân sách đặt theo từng website. Tool không cho thêm keyword nếu ước tính vượt ngân sách, cảnh báo ở 80%, ngừng gửi yêu cầu khi chạm trần.
4. **Tạm ngưng** một website (công tắc ở màn Ngân sách check rank): ngưng mọi yêu cầu DataForSEO của website đó (check rank theo lịch, nút Check ngay, volume keyword). Dữ liệu cũ vẫn giữ; bật lại là chạy theo lịch.
5. Màn **Quản trị → Ngân sách check rank** (chỉ Chủ tool): đã dùng tháng này, dự kiến cả tháng (đã dùng + các lần check còn lại theo lịch), tổng ngân sách và số dư tài khoản DataForSEO; từng website có thanh đã dùng / dự kiến so với ngân sách, trạng thái (trong ngân sách / gần trần / vượt), đổi ngân sách ngay trên dòng; biểu đồ chi phí 6 tháng theo website.

---

## 7. Cho người khác truy cập

Mặc định tool chỉ nghe ở `127.0.0.1` (chỉ máy này mở được). Để team / khách vào từ nơi khác, chọn một cách:

- **Tailscale** (miễn phí, không cần tên miền): cài Tailscale trên máy chạy tool, bật MagicDNS + HTTPS, chạy `tailscale serve --bg 8080`, mời người xem vào mạng Tailscale. Email Tailscale đã xác minh được nhận thẳng.
- **Cloudflare Tunnel + subdomain riêng** (nên dùng khi có khách; cần tên miền đã trỏ nameserver về tài khoản Cloudflare của bạn). Máy này mở kết nối ra Cloudflare nên không cần mở cổng router hay IP tĩnh, có sẵn HTTPS:
  1. Chạy `scripts\cai-dat-may-chu.ps1` (tool chạy nền, việc hằng ngày, không cho máy ngủ).
  2. Cài cloudflared: `winget install --id Cloudflare.cloudflared`.
  3. Cloudflare → **Zero Trust → Networks → Tunnels → Create tunnel** (Cloudflared). Chép lệnh `cloudflared.exe service install <mã>` Cloudflare đưa, chạy trong PowerShell *Run as administrator*. Mã này là khóa của tunnel: không gửi cho ai.
  4. Tab **Public hostname**: subdomain (ví dụ `seo.tenmien.com`) → Type `HTTP` → URL `localhost:8080`.
  5. Mở thử subdomain từ điện thoại (tắt Wi-Fi): phải thấy trang Đăng nhập. Điền subdomain vào ô "Link tool" ở màn Phân quyền.

  Người vào qua tunnel luôn phải đăng nhập bằng email + mật khẩu do bạn cấp (chỉ người ngồi ở chính máy này được vào thẳng). Sai 5 lần một tài khoản thì khóa tài khoản đó 15 phút; một IP sai 20 lần trong 15 phút thì chặn IP đó 15 phút. Muốn thêm lớp nữa cho team (không cho khách): tạo ứng dụng Cloudflare Access (One-time PIN, danh sách email) rồi điền `team_domain` và `aud` vào `[access]` của `config.toml`.
- **VPS:** chạy tool trên máy chủ riêng, đặt sau reverse proxy có HTTPS. Người dùng đăng nhập bằng email + mật khẩu do bạn cấp.

Sau khi có địa chỉ, điền vào ô "Link tool" ở hộp thoại mật khẩu để tin mời có link đúng.

---

## 8. Bản xem tĩnh có mật khẩu (tùy chọn)

`export-static` chụp số liệu hiện tại thành một trang web chỉ đọc (báo cáo tuần, tháng, OKR, rank), mã hóa bằng mật khẩu (AES-256, PBKDF2 600.000 vòng), để đưa lên hosting tĩnh như Vercel:

```powershell
.\.venv\Scripts\python -m seo_report --project <mã> export-static --out dist
npx vercel deploy dist --prod
```

Bản tĩnh không tự cập nhật. Gửi link và mật khẩu qua hai kênh khác nhau.

---

## Lệnh dòng lệnh

Mọi lệnh chạy cho website đầu tiên; thêm `--project <mã>` (xem ở màn Dự án) để chọn website khác.

| Lệnh | Việc |
|---|---|
| `login` | Đăng nhập Google, liệt kê property GSC / GA4 |
| `sync` | Lấy dữ liệu GSC (lần đầu tự lấy bù 16 tháng) |
| `daily` | Việc hằng ngày cho mọi website |
| `backup` | Sao lưu dữ liệu thành file zip (`daily` đã tự làm) |
| `rank`, `index`, `classify` | Check rank đến hạn, check index, đọc schema URL chưa phân loại |
| `stats`, `ga4-check`, `ai-summary` | Xem tóm tắt dữ liệu, kiểm tra GA4, in số traffic AI |
| `web` | Mở giao diện (`--port`, `--no-open`) |
| `export-static` | Xuất bản xem tĩnh có mật khẩu |

## Giới hạn cần biết

- GSC trả tối đa khoảng 50.000 dòng URL × query mỗi ngày cho một property; site lớn có thể thiếu query đuôi dài. Tổng theo URL không bị ảnh hưởng.
- Tổng click của các query nhỏ hơn click của URL vì Google ẩn query hiếm.
- Thứ hạng chỉ lấy từ DataForSEO; position của GSC là số trung bình, không dùng làm thứ hạng.
- Token Google gắn với tài khoản đã đăng nhập; mất quyền hoặc đổi mật khẩu thì chạy lại `login`.
- Trạng thái online giữ trong bộ nhớ; khởi động lại tool thì mọi người tạm hiện offline.
- Chạy trên máy cá nhân: máy tắt, mất điện hay mất mạng thì khách thấy trang lỗi của Cloudflare. Cần chạy ổn định 24/7 thì chuyển lên VPS (cách dùng tunnel giữ nguyên).

## Phát triển

```powershell
.\.venv\Scripts\python -m unittest
```
