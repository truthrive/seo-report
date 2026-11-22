# DESIGN.md — Chuẩn thiết kế SEO Report

Đọc file này trước khi sửa hoặc thêm bất kỳ màn nào. Mọi quy tắc ở đây **đã được chốt và đang chạy trong tool**; chỗ
nào chưa thống nhất được ghi rõ ở mục [Nợ thiết kế](#12-nợ-thiết-kế-chưa-làm).

- Mã nguồn chuẩn: [seo_report/ui_theme.py](seo_report/ui_theme.py) — hằng số màu, CSS toàn tool, các hàm vẽ thành
  phần dùng chung (`T.section`, `T.kpi`, `T.pill`…). Bảng: [seo_report/table_kit.py](seo_report/table_kit.py).
- Giao diện: NiceGUI 3 (Quasar / Vue), biểu đồ ECharts. Toàn bộ chữ trên giao diện bằng **tiếng Việt**.
- Khi thêm class CSS mới: tìm trong `ui_theme.py` xem tên đã có chưa. Một lần trùng tên `.sr-seg` từng làm hỏng nút
  gạt của cả tool. Class mới đặt tiền tố `sr-` + tên màn (`sr-kr-…` Keyword Research, `sr-bl-…` Backlink…).

---

## 1. Màu

Hằng số ở đầu `ui_theme.py`; biến CSS ở `:root`. **Không tự đặt màu mới** — chọn trong bảng dưới.

### Màu thương hiệu và nền

| Tên | Mã | Hằng / biến | Dùng cho |
|---|---|---|---|
| Xanh chủ đạo | `#1E7C31` | `GREEN`, `--green` | Số tốt, link nhấn, trạng thái đạt, nút xác nhận |
| Lime | `#B8D332` (CSS `#C5E063`) | `LIME`, `--lime` | Điểm nhấn nhỏ (chấm eyebrow, thanh tiến độ). Không dùng làm nền lớn |
| Mực | `#1F221E` | `INK`, `--ink` | Chữ chính; **màu `primary` của Quasar** (nút chính nền mực) |
| Chữ phụ | `#6B6A5E` | `MUTED`, `--muted` | Chú thích, nhãn phụ (`.muted`) |
| Chữ nhạt | `#8E8D80` | `--soft` | Phần số / ngày trong tiêu đề trang, icon phụ |
| Nền trang | `#ECEBE4` | `PAGE_BG`, `--bg` | Nền kem ấm, đậm hơn thẻ một bậc để thẻ trắng nổi lên |
| Kem | `#EDEDE5` | `CREAM` | Nền khối phụ |
| Đường kẻ | `#E4E3DA` / `#E4E2D8` | `--line` | Viền thẻ, viền bảng, đường ngăn |

### Màu trạng thái — `TONES` (nền nhạt, chữ đậm)

Dùng qua `T.pill`, `T.tag`, `T.count_badge`. Mỗi tone là một cặp (nền, chữ) đã đạt tương phản 4,5:1.

| Tone | Nền | Chữ | Nghĩa |
|---|---|---|---|
| `green` | `#E7F3EA` | `#1E7C31` | Tốt, đạt, ổn |
| `lime` | `#F2F7DC` | `#5E7414` | Tích cực nhẹ |
| `amber` | `#FBF1DE` | `#8F5F14` (`AMBER_TEXT`) | Nên xem, cảnh báo |
| `red` | `#FCEDE6` | `#C2410C` (`RED`) | Cần sửa, lỗi, giảm |
| `blue` | `#E8EFFD` | `#1D4ED8` | Tham khảo, thông tin, đang chọn |
| `grey` | `#F1F0EA` | `#6B6A5E` | Trung tính, tạm ngưng |
| `purple` | `#F1EAFB` | `#7C3AED` | AI |

### Màu thẻ

Màu trên thẻ chỉ dùng để **nói trạng thái**, để thẻ cần nhìn nổi lên giữa các thẻ trắng.

| Loại thẻ | Nền | Viền | Ví dụ |
|---|---|---|---|
| Thẻ thường (khung nội dung, ô KPI bình thường) | trắng `#fff` | `--line` | Phần lớn thẻ |
| Thẻ lồng trong thẻ | `#F6F6F1` | không | Ô trong khung, dòng danh sách |
| Cần sửa / xấu (`st-red`) | `#FCEDE6` (nền tone red) | `#F2CDBC` | Ô "Tỉ lệ 1–3 sao" vượt 5%, thẻ "còn đánh giá thấp chưa trả lời" |
| Nên xem / cảnh báo (`st-amber`) | `#FBF1DE` (nền tone amber) | `#EED9B0` | Trả lời chậm hơn 3 ngày, còn đánh giá chưa trả lời |
| Đang chọn (ô bật / tắt đường) | màu của chỉ số pha 7% với trắng | màu chỉ số pha 45% | Ô trong `T.trend_chart` |

- Thẻ **tốt không tô nền xanh**: để trắng, cái tốt thể hiện bằng số / pill màu xanh. Tô xanh khắp nơi thì thẻ đỏ,
  vàng không còn nổi.
- Ô KPI: `T.kpi(..., status="red" | "amber")` để tô nền; `tone` chỉ là màu icon, cố định theo ý nghĩa chỉ số (không
  đổi theo số).
- Mỗi màn có tối đa **một thẻ việc cần làm** có nền màu, đặt trên cùng.
- **Không** gradient, không bóng đổ khi đứng yên, không vạch màu bên trái, không nền mực đậm.

- Chữ màu hổ phách luôn dùng `AMBER_TEXT #8F5F14`, **không** dùng `AMBER #B7791F` cho chữ (không đủ tương phản).
- Ba mức kiểm tra (audit, backlink…) luôn là: **Cần sửa** = red · **Nên sửa / Nên xem** = amber ·
  **Tham khảo** = blue · **Ổn** = green.
- Nút AI: `color=deep-purple-1 text-color=deep-purple-9` + icon `auto_awesome` + class `sr-kg-aibtn`.
- **Mọi nội dung AI dùng tím** để người xem biết ngay phần nào do AI viết: khối AI `T.section(..., "auto_awesome",
  tone="purple")` (icon tím), đoạn tóm tắt AI `.sr-st-sum` (nền `#F1EAFB`), khung nhập cho AI viết nền `#F6F1FD`
  viền `#E4D8F7`, link mở chi tiết của khối AI màu `#6D28D9`. Nút AI nhỏ trong dòng: thêm `size=sm`, cùng màu.

---

## 2. Chữ

- **Một họ chữ cho cả tool: Be Vietnam Pro** (giao diện, biểu đồ, báo cáo tĩnh) — dấu tiếng Việt chuẩn. Biến `--font`;
  `--head` / `--mono` chỉ còn là tên cũ trỏ về cùng font.
- Số luôn dùng chữ số đều cột: `font-feature-settings: 'tnum'` đã bật cho `body`; class `.num` khi cần ép.

| Vai trò | Cỡ / độ đậm | Class |
|---|---|---|
| Tiêu đề trang | 28px / 800, giãn chữ -0.03em | `.sr-title` (phần số / ngày tô `--soft`) |
| Tiêu đề khối | 16px / 700 | `.sr-section-title` |
| Số lớn trên ô KPI / ô thống kê | 22px / 700 | `.sr-op-stat-num`, trong `T.kpi` |
| Chữ thường | 13–14px / 400 | — |
| Chú thích | 12px, màu `--muted` | `text-xs muted` |
| Ô trong bảng | 13px / 400 | mặc định của bảng |

- **Không in đậm dữ liệu trong bảng** (từ khóa, số): đậm nhiều thì rối mắt. Nhấn bằng màu và cỡ chữ, tối đa 500.
- **Không dùng nhãn nhỏ in hoa kiểu mono** làm chữ trang trí. Ngoại lệ đang có: tiêu đề nhóm trong tab Audit
  (`.sr-au-group-h`) và tiêu đề hàng của bảng tự dựng.
- Ngày phải trông khác số: ngày dạng `dd/mm/yyyy`, màu nhạt hơn hoặc nằm trong chip.

---

## 3. Bố cục trang

```
T.page_header  ── tiêu đề + mô tả một câu · nút hành động bên phải (nút chính cuối cùng)
dòng trạng thái ── "Lấy ngày … · so với …" + chip lịch tự lấy
thanh tab       ── ui.tabs (class sr-tabs), mỗi tab là một màn; địa chỉ ?tab=… để chia sẻ được
nội dung        ── T.section (thẻ trắng bo 14px) xếp dọc, hoặc lưới thẻ
```

- **Thẻ:** `.sr-card` nền trắng, viền `--line`, bo 14px, **không bóng đổ**. Thẻ lồng trong thẻ đổi sang nền `#F6F6F1`,
  bỏ viền; phần tử nằm trong thẻ lồng (ô số nhỏ, viên %) lại đổi về nền trắng để vẫn tách lớp.
- **Thẻ hẹp không rớt dòng:** các số phụ dưới số chính chia thành lưới ô (nhãn nhỏ ở trên, số ở dưới, mỗi ô một mốc),
  câu kết luận viết ngắn một dòng (`white-space: nowrap` + `…`). Bỏ thông tin đã có ngay cạnh số chính.
- **Khối có tiêu đề:** `with T.section(ui, "Tên", "icon", "mô tả một câu"):` — dùng cho mọi khối nội dung.
- **Ô thống kê:** lưới `.sr-op-audit-sum` gồm các `.sr-op-stat` (số lớn + nhãn một dòng).
- **Ô KPI có biểu đồ nhỏ:** `T.kpi(...)` trong `T.kpi_row(ui)`.
- **Gom vào một khung (bento)** thay vì mỗi biểu đồ một thẻ riêng; các tab cùng màn có kích thước như nhau.
- **Thanh tab phải vừa một hàng ở 375px**, không bắt người dùng bấm mũi tên mới thấy tab cuối. Nhiều tab quá thì gộp
  các cách xem cùng một dữ liệu vào một tab với thanh chọn bên trong (Backlink đã gộp từ 9 xuống 6 tab: Danh sách =
  Tất cả backlink / Website trỏ về / Trang đích / Anchor text).
- Nhãn tab: hoặc mọi mục cùng loại đều có số đếm, hoặc không mục nào có. Số trên nhãn tab phải **khớp** số bên trong
  tab (đã từng lệch: tab ghi 116 nhưng bên trong ghi 2).
- **Đúng nhóm menu:** việc kỹ thuật website nằm ở nhóm *Website*, cơ hội từ khóa ở nhóm *Từ khóa* (Technical Audit
  đã được tách khỏi SEO Opportunities vì lý do này).

### Phân cấp thông tin

- Thông tin chính hiện ngay; thông tin phụ cho vào tooltip, nút (i) (`T.info_icon`) hoặc menu `···`.
- **Không bày nhiều mục nhỏ ngang hàng** ("quá tải thông tin vụn").
- **Không lặp một thông tin ở hai chỗ.** Ví dụ: Tổng quan Backlink chỉ nêu 4 việc nặng nhất kèm nút "Xem N việc còn
  lại ở tab Audit", không chép lại cả danh sách Audit.
- Không để khoảng trống lớn, nhưng cũng không nhét số liệu cho đầy chỗ.
- Danh sách mục kiểm tra chia nhóm theo mức (Cần sửa → Nên xem → Chỉ số hồ sơ thu gọn), không xếp phẳng.
- **Audit dạng checklist** (Technical Audit): chia theo hạng mục của bộ tiêu chuẩn, mỗi tiêu chí một dòng có
  trạng thái **Đạt / Cần sửa / Nên sửa / Tham khảo / Chưa kiểm / Không áp dụng** — hiện cả tiêu chí đạt để đọc như
  một checklist. Mã quy tắc chỉ hiện khi mở tiêu chí (không đặt cạnh tên). Không lấy được dữ liệu (hết giờ chờ, thiếu
  API key) thì là *Chưa kiểm*, không phải lỗi. Bảng chi tiết có cột **Đang là / Nên là**; trường hợp cố ý thì đánh
  dấu "Cố ý, bỏ qua" chứ không xóa khỏi kết quả; đã sửa thì "Đã xử lý, kiểm tra lại" (kiểm ngay, ghi nhật ký).
- **Cột hạng mục**: checklist dài chia cột trái "Tổng quan" + từng hạng mục, mỗi lần hiện một mục (màn hẹp: thanh
  trượt ngang, tự cuộn tới mục đang chọn). Dưới tên mỗi mục là một dòng chữ nhỏ ghi trạng thái ("1 cần sửa · 1
  nên sửa", "✓ Đạt hết", "Chưa kiểm") thay cho chấm số màu; không đánh số mục; mỗi mục có icon riêng; mục đang chọn tô nền xanh nhạt
  (không dùng vạch màu bên cạnh). Tổng quan không lặp lại danh sách hạng mục.
- **Theo thời gian**: so qua các lần quét bằng bảng *tiêu chí × lần quét* (mới nhất bên trái, cột tên dính bên trái),
  không bằng danh sách từng lần quét.
- Thống kê mô tả (tỷ lệ dofollow, phân bố trang đích…) không đặt lẫn trong danh sách việc phải làm.
- **Thông tin phụ không làm tab riêng** (lịch sử phiên bản, nhật ký sửa, cấu hình ít xem): một dòng chữ nhỏ cuối màn
  dạng "🕘 Cam kết sửa lần cuối 12/11/2026 · Xem các lần sửa", bấm mở hộp thoại. Trong hộp thoại gộp các bản giống hệt
  nhau ("lưu 6 lần"), bản đang dùng có nhãn, cuối có một câu nói vì sao cần giữ lịch sử. Khách hàng không thấy.
- **Mốc / tháng chưa tới không tô như đã đạt.** Chỉ hiện số cần đạt (xám); số hiện tại đã đủ thì thêm ✓ nhỏ cạnh số,
  không tô nền xanh cả ô. "Đạt / Không đạt" chỉ dùng cho tháng đã chốt.
- **Tab đầu của một màn là tab nhận định / tổng quan** (đang ở đâu, AI nhận định, cảnh báo); thẻ chi tiết và bảng
  theo tháng nằm ở tab sau (mẫu: KPI cam kết › Tổng quan · Lộ trình · Từ khóa cam kết).

---

## 4. Thành phần dùng chung

### Nút

| Loại | Cách viết | Khi nào |
|---|---|---|
| Nút chính | `.props("unelevated no-caps")` (nền mực) | Một hành động chính mỗi khối; **luôn có chữ** |
| Nút phụ | `.props("outline no-caps color=grey-9")` | Hành động thứ cấp có chữ |
| Nút icon | `.props('flat round dense aria-label="…"')` + `.tooltip("…")` | Hành động phụ; **bắt buộc có tooltip và aria-label**, không có mũi tên xổ xuống |
| Nút chữ nhẹ | `.props("flat no-caps dense color=primary")` | "Xem thêm", "Bỏ chọn" |
| Nút AI | xem mục 1 | Mọi tính năng gọi AI |

- **Xóa** nằm trong menu `···`, luôn có bước xác nhận.
- Nút tốn phí ghi rõ giá ngay trên nút hoặc tooltip (xem [mục 8](#8-chi-phí-ai-và-dữ-liệu-trả-phí)).
- Hàng nút đầu trang **tự xuống dòng** ở màn hẹp, không dùng `no-wrap`.

### Nút gạt (chọn một trong vài)

Mọi nút gạt dùng **chung một kiểu `.sr-seg`**:

```python
ui.toggle({...}, value=...).props(
    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes("sr-seg")
```

Thanh chọn chính phía trên thanh chọn phụ thêm class `sr-seg-main` (to hơn).

### Pill, tag, badge, chip

| Hàm | Hình | Dùng cho |
|---|---|---|
| `T.pill(ui, text, tone, icon)` | Viên thuốc bo tròn hẳn | **Trạng thái**: Đang đạt, Cần sửa, Tạm ngưng |
| `T.tag(ui, text, tone)` | Bo góc nhỏ 6px | **Phân loại**: loại trang, nhóm |
| `T.count_badge(ui, n, label)` | Số tròn nhỏ | Số việc trên nhãn tab; `label` là câu đầy đủ cho trình đọc màn hình |
| `T.filter_chip(ui, text, on_remove)` | Chip có nút ✕ | Bộ lọc đang bật |
| Nhãn website (`web_labels`) | Chip màu riêng, có ✕ để gỡ | Nhãn người dùng tự đặt |

- **Không đánh dấu dòng / thẻ đang chọn bằng vạch màu bên trái** (`border-left`, `box-shadow: inset 3px 0 …`). Dùng
  nền nhạt (`#EEF3FB` cho đang chọn, `#F7F6F1` khi rê chuột).

### Thẻ chỉ số (Top N, KPI)

Mọi thẻ đếm từ khóa theo mốc Top (trang Thứ hạng, KPI cam kết…) dùng **một kiểu**: icon trơn 16px + tiêu đề
(`.sr-bx-title`) + viên % bên phải (`.sr-kc-pct`), số lớn (`.sr-kc-num`, xanh khi tăng / đỏ khi giảm) + "/ 76 từ khóa"
(`.sr-kc-of`), viên ▲▼ so với lần trước (`.sr-kc-delta`, có tooltip nói so với khi nào). Không chế kiểu thẻ mới cho
cùng loại số.

### Icon

- **Cùng khái niệm thì cùng icon ở mọi màn**, lấy từ chỗ đã có: menu trái (`NAV` trong `web.py`) và `CELL_ICONS` (trang
  Thứ hạng). Top 3 `emoji_events`, Top 5 `workspace_premium`, Top 10 `military_tech`, lượt truy cập Organic
  `travel_explore`, AI traffic `smart_toy`.
- Ô icon chuẩn: `.sr-icon-bubble` (32px, bo 10px, icon 18px, nền / màu lấy từ `TONES`). Trong thẻ số dùng icon trơn
  16px như thẻ Top N. Không tự đặt cỡ / bo / mã màu riêng.
- `auto_awesome` và màu tím dành cho nội dung AI viết; chỉ số liên quan AI nhưng không do AI viết (AI traffic) dùng icon
  khác, tông xanh dương.

### Thông báo nổi và lớp phủ

- `ui.notify`: thẻ trắng bo 14px, icon trong vòng tròn màu theo loại (xanh lá thành công · hổ phách cảnh báo · đỏ lỗi
  · xanh dương thông tin), chữ màu mực, nút ("Đóng") là viên thuốc nhỏ màu mực. Nội dung chính **một dòng ngắn**, phần
  hướng dẫn đưa vào `caption` ("mkt…@gmail.com xin quyền vào tool" + "Duyệt ở Quản trị › Phân quyền"). CSS chung trong
  `ui_theme.py`, không tô nền màu đặc.
- Thông báo cần người khác xử lý (người xin quyền…) gửi ngay tới trang đang mở của Owner / Admin (`live.notify`), đồng
  thời có mục ở chuông.
- Mở popup nổi (thông báo, nút +, hộp "Tất cả mục") thì **làm tối + mờ nền phía sau** (`rgba(31,34,30,.38)` + blur 3px),
  bấm ra ngoài để đóng.

### Trạng thái trống, đang tải, đang chạy

- Trống: `T.empty_state(ui, "icon", "Tiêu đề", "Bấm … để …")` — luôn chỉ cách làm tiếp.
- Đang tải: khung xám `T.bone(...)` giữ đúng chỗ nội dung sắp hiện, trong vùng có `aria-busy="true"`.
- Việc chạy lâu (quét, lấy số): dòng tiến độ ngay dưới thanh công cụ với **số thật** ("Đang quét 120/300 trang");
  thông báo gọn ở góc dưới phải (`position="bottom-right"`). Không biết tiến độ thì dùng thanh chạy vô định, không bịa %.

---

## 5. Bảng

Mọi bảng trong tool cùng một kiểu (CSS chung `.q-table__container` trong `ui_theme.py`):

| Thuộc tính | Giá trị |
|---|---|
| Khung | viền `#E4E2D8`, bo 12px, nền trắng, không bóng |
| Hàng tiêu đề | nền `#F3F3ED`, chữ 12px / 600, màu `#4A4A40` |
| Dòng | chữ 13px, đệm trên dưới **9px**, dòng chẵn nền `#FAFAF6`, rê chuột `#F0F2E8` |
| Phân trang | nền `#FAFAF6`, "Dòng mỗi trang" |

- **Bảng có lọc / chọn / xuất dùng `table_kit.table(...)`.** Bộ lọc, số dòng, Sao chép, Xuất Excel và bảng nằm
  **chung một khung** (`.sr-tk-box` › `.sr-tk-tools` + bảng). Tick chọn dòng thì thanh công cụ chuyển nền xanh nhạt và
  hiện thao tác cho phần đã chọn.
- Nút lọc đang bật ghi rõ **đang lọc trường nào** ("Khoảng số: Số link"), kèm chip từng điều kiện và nút "Xóa lọc".
- **Cột không có dữ liệu ở mọi dòng thì ẩn**, ghi chú "Đã ẩn cột …" dưới bảng; nút chọn cột vẫn bật lại được.
- Bề rộng tối thiểu của bảng tính theo số cột đang hiện, để bảng không cuộn ngang vô cớ.
- Bảng dài: tiêu đề cột dính khi cuộn.
- Ô có hai tầng (website + nguồn, trang + đường dẫn): dòng phụ dùng class `.sr-bb-sub` / `.sr-bl-sub`.
- Mỗi bảng có nút xuất Excel; file xuất **đủ cột** kể cả cột đang ẩn trên màn hình.
- **Bảng theo tháng / lộ trình** (cột = tháng): không tô nền từng ô; trạng thái bằng màu chữ (xanh đạt, đỏ không đạt,
  hổ phách đang thiếu). Trạng thái tháng ghi bằng nhãn nhỏ dưới tên cột ("Đang chạy 14/30", "Bắt đầu cam kết"), không
  thêm một dòng timeline riêng. Cột tháng đang chạy nền xanh rất nhạt; tháng đã qua chữ xám. Chú thích dưới bảng dùng
  ví dụ thật ("**16** thực tế · / 6 cam kết tháng đó").

---

## 6. Số liệu

### Trung thực dữ liệu

- **Không bịa số hay phần trăm.** Không có số thì ghi "chưa có", "chưa kiểm", "–".
- Nhãn theo đúng độ sâu đã kiểm ("Ngoài top 20", không ghi "Ngoài top 100" khi chỉ check 20).
- **Ghi rõ nguồn số** khi có nhiều nguồn: "DataForSEO 261 · Semrush 1.477 · đếm từ danh sách link". Hai số cùng tên
  nhưng khác cách tính (số tổng API và số đếm từ danh sách) không được đặt cạnh nhau mà không giải thích.
- **Đơn vị chung để so mức nặng:** danh sách mục kiểm tra lấy *số website* làm số chính, đơn vị riêng (link / trang /
  anchor) ở dòng dưới.
- AI chỉ được dùng số tool đã tính; câu nào có số không có trong dữ liệu thì bỏ.

### Cách trình bày

- Tỷ lệ: **x / tổng kèm %** ("2/82 sản phẩm có sao").
- Thay đổi: `▲` / `▼` thay cho dấu +/− (không viết "▼ -123"), màu theo tốt / xấu, **có tooltip** nói so với kỳ nào
  (`T.delta_badge`, `T.change_text` → "+177 (+3,3%)").
- Giá trị kỳ trước: chip ngày + số, khác màu số hiện tại.
- Số dùng dấu chấm ngăn nghìn, dấu phẩy thập phân (`1.619`, `3,3%`); tiền VND không có số lẻ.

---

## 7. Biểu đồ

- Phân bố một tổng: **donut** (`T.donut`, tối đa 6 phần, phần nhỏ gộp "Khác"), rê chuột thì lát nhô ra.
- Xu hướng: `T.trend_chart` (kiểu Search Console: mỗi chỉ số một ô bật / tắt đường), `T.sparkline` cho ô KPI.
- **Trục bắt đầu từ 0** để độ dốc không phóng đại.
- Nhiều đường: khác nhau bằng **kiểu nét** (liền / đứt), không chỉ bằng màu. Kỳ trước = nét đứt.
- Nhãn trên biểu đồ có nền để không đè lên đường.
- Ít điểm dữ liệu thì hiện bảng, có nút gạt bảng / biểu đồ.
- Đã bỏ: so sánh dạng thanh ngang (bar comparison), dải thống kê nhỏ (stat strip), biểu đồ mini rải khắp trang.

---

## 8. Chi phí, AI và dữ liệu trả phí

- **Không gọi API trả phí khi mở trang.** Chỉ gọi khi người dùng bấm nút, và nút ghi giá trước ("~0,15 USD",
  "8 credit"). Member thấy giá bằng credit; Owner / Admin thấy USD.
- Việc tốn phí có lịch tự động thì hiện chip lịch kèm ước tính tháng ("Mỗi tháng · lần tới 12/12 · ~0,18 USD/tháng").
- Tính năng AI: chỉ chạy khi bấm, lưu vào thư viện (nút đồng hồ `history` mở "Thư viện AI"), ghi chi phí. Kết quả cũ
  hơn số liệu hiện tại thì báo "Đã có số mới, bấm để cập nhật".
- Bật / tắt và chọn model AI ở **Quản trị › AI**. **Tên model chỉ hiện ở trang đó**, không hiện ở nơi khác.
- Khách hàng (Guest) không thấy nút tốn phí, nút AI, điểm spam, việc nội bộ của team.
- **Giao diện khách = kết quả, không phải vận hành.** Không lộ USD / credit, tên nhà cung cấp dữ liệu (DataForSEO,
  Semrush), bộ từ khóa nháp / tạm dừng, lịch check, lỗi kỹ thuật. Câu hướng dẫn cài đặt cho admin ("gắn GA4 ở Quản
  trị…") với khách đổi thành "Đội SEO đang chuẩn bị số liệu này." Khách chỉ tải báo cáo ở trang Báo cáo
  (`export_menu(..., report=True)`); nút tải / CSV ở trang chi tiết dùng `T.team_button`. Trang chi tiết rút còn một
  màn kết quả (Local SEO, OKR theo mục tiêu, Tốc độ trang…); task tuần nằm trong Báo cáo tuần / tháng.

---

## 9. Từ ngữ

- Tiếng Việt thống nhất cho cùng một khái niệm ở mọi chỗ (cột, bộ lọc, file xuất):

| Dùng | Không dùng |
|---|---|
| Lượt tìm / tháng | Volume |
| Từ khóa trụ | Pillar |
| Website trỏ về | Referring domains |
| Số từ khóa · Lượt tìm (nút gạt) | Số lượng · Volume |
| Nên xin link | Không spam |
| Tất cả, gồm cả spam | Cả website spam |

- Tên tính năng của bên thứ ba giữ nguyên khi người dùng quen gọi: Search Console, DataForSEO, Semrush, Technical
  Audit, Backlink GAP.
- Chữ viết tắt (C, I, N, T của "Mục đích") phải có chú thích hiện trên màn hình, không chỉ trong tooltip.
- Thông báo nói việc đã xảy ra và con số: "Đã gỡ nhãn Web 2.0 khỏi 99ranks.com", "Đã quét 300 trang (2 trang không mở
  được)".
- Hướng dẫn sửa lỗi viết thành việc làm được: "Đặt redirect 301 từ trang lỗi về trang gần nhất", không viết chung chung.

---

## 10. Trợ năng và màn hẹp

- **Không cuộn ngang cả trang ở 375px.** Bảng rộng được cuộn ngang **bên trong khung bảng**; thanh tab dùng
  `mobile-arrows outside-arrows`.
- Mọi nút chỉ có icon: `aria-label` + tooltip.
- Vùng bấm tự dựng (`ui.element("button")`, thẻ bấm được): `type="button"`, `tabindex=0`, xử lý `keydown.enter`, có
  viền khi focus (`outline: 2px solid …`).
- Màu không phải cách duy nhất truyền nghĩa: pill có chữ, ▲▼ có tooltip, đường biểu đồ khác kiểu nét.
- Biểu đồ nhỏ có `role="img"` và `aria-label` mô tả ("Đang tăng").
- Hàng nút / nút gạt **không dùng `no-wrap` trên điện thoại**; nhãn `.ellipsis` trong cột flex luôn bị giới hạn bề
  rộng (CSS chung). Bố cục hai cột cố định (danh sách + chi tiết) dưới 768px chuyển thành danh sách → chi tiết, có nút
  quay lại (mẫu: Hiệu suất URL, `.sr-url-split`).
- Ô nhập chữ trên điện thoại cỡ **16px** (iOS tự phóng to trang nếu nhỏ hơn). Ô chọn không mở bàn phím thì không cần.
- Màn cảm ứng (`pointer: coarse`): nút `dense` cao tối thiểu 40px, nút gạt 36px, nút phân trang bảng 40×40.
- Chữ phụ trên điện thoại tối thiểu 12px.
- Điện thoại: không có nút về đầu trang; chạm lại mục đang mở trên thanh dưới đáy thì về đầu trang. Nút + lùi đi khi
  cuộn xuống, hiện lại khi cuộn lên. Thông báo nằm trên thanh dưới đáy.
- Bảng `table_kit` trên điện thoại: cột đầu dính bên trái khi cuộn ngang.
- Thanh trên điện thoại **chỉ một dòng**: ☰ · tên website · nút kỳ ("Tuần 09/11 · SEO chủ lực"). Ô chọn kỳ / nhóm
  nằm trong khung trượt từ đáy khi bấm nút kỳ; avatar người có quyền và "GSC đến …" ẩn. Ô chọn mới cho thanh trên thêm
  vào `controls()` trong `web.shell` để cả hai bản cùng có.
- Sửa giao diện xong: đo mọi trang ở 375px, `document.documentElement.scrollWidth` phải bằng 375.
- **Thanh điều hướng dưới đáy (điện thoại):** viên thuốc nổi kính mờ, 4 mục bằng nhau icon trên chữ; mục đang mở icon
  đặc màu xanh và `aria-current="page"`, mục khác icon viền xám; chừa `env(safe-area-inset-bottom)`. Mục "Thêm" mở popup
  lưới 2 cột (icon + tên), không lặp mục đã có trên thanh.
- **Form đăng nhập:** `<form>` thật, Enter gửi form, ô có `name` + `autocomplete` (`username`, `current-password`) để
  trình quản lý mật khẩu tự điền; nút hiện mật khẩu là `<button type="button">` có tên đọc được ("Hiện mật khẩu");
  nút đăng nhập bằng Google ở trên, đường kẻ "hoặc", mật khẩu ẩn sau một nút.

---

## 11. Những kiểu đã bỏ — không làm lại

| Kiểu | Lý do |
|---|---|
| Vạch màu bên trái để đánh dấu dòng / thẻ | Người dùng không thích; dùng nền nhạt |
| Khối nền mực đậm làm điểm nhấn (hero tối) | "Không theo màu thiết kế của tool" |
| In đậm dữ liệu trong bảng | Rối mắt |
| So sánh dạng thanh, dải thống kê nhỏ, biểu đồ mini rải rác | Nhiều thông tin vụn ngang hàng |
| Nhãn mono in hoa nhỏ trang trí | Một font, không chữ trang trí |
| 9 tab ngang hàng trên một màn | Khó tìm; gộp các cách xem cùng dữ liệu |
| Bộ lọc và bảng là hai khối rời | Gộp chung một khung |
| Liệt kê tên miền thành đoạn chữ dài | Dùng bảng có lọc / xuất |

---

## 12. Nợ thiết kế (chưa làm)

- `ui_theme.py` còn **khoảng 245 mã màu viết cứng**, riêng `#1E7C31` lặp hơn 120 lần thay vì dùng `var(--green)`.
  Cần gom về biến CSS / hằng số (việc riêng, làm dần khi sửa từng màn).
- `--line` khai báo `#E4E3DA` nhưng chuẩn bảng dùng `#E4E2D8` (gần như trùng) — nên gộp một giá trị.
- `LIME` ở Python (`#B8D332`) khác `--lime` ở CSS (`#C5E063`).
- Một số bảng cũ còn tự dựng bằng `ui.table` thay vì `table_kit` nên chưa có khung lọc chung; chuyển dần khi sửa màn đó.
- Chưa có chế độ tối.
