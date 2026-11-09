# Review màn Tổng quan: ui-ux-pro-max + dataviz

Ngày 07/11/2026 · bản đang chạy ở localhost:8080 (bố cục nhóm mới, chưa commit).

**Cách review:**
- Bộ quy tắc ưu tiên của skill **ui-ux-pro-max** (trợ năng → tương tác → hiệu năng → bố cục → chữ và màu → biểu đồ), cùng tra cứu `ux` / `chart` của skill.
- Quy trình 7 bước và danh mục lỗi hay gặp (anti-patterns) của skill **dataviz**. Phần màu sắc chạy bằng script `validate_palette.js`, không đánh giá bằng mắt.
- Đo trực tiếp trên trang ở 1440px: độ tương phản chữ, cỡ chữ, khả năng dùng bằng bàn phím, kích thước vùng bấm.

Mức độ: **P0** sai số liệu hoặc chặn người dùng · **P1** dễ đọc sai / trợ năng · **P2** hoàn thiện.

---

## 1. Số liệu và cách biểu diễn (dataviz)

| # | Mức | Khối | Vấn đề | Bằng chứng | Đề xuất |
|---|---|---|---|---|---|
| D1 | **P0** | Phân bố thứ hạng | **Chiều cao cột tăng giả.** Mỗi cột là trạng thái cộng dồn của các từ khóa đã từng được check, nên tổng mỗi cột tăng dần (khoảng 1 → 20 → 20 → 69) dù số từ khóa theo dõi không đổi. Người xem sẽ đọc thành "thứ hạng tăng mạnh" | `R.history_of`: `state` cộng dồn theo ngày check | Vẽ **100% chồng** (tỷ lệ trên số từ khóa đã có số), hoặc chỉ vẽ các lần check đủ bộ. Ghi "trên N từ khóa đã check" dưới mỗi cột (tooltip + bảng) |
| D2 | **P1** | Phân bố thứ hạng | **Màu nhóm hạng không phân biệt được với người mù màu đỏ–lục.** Đây là thang có thứ tự nhưng đang dùng màu trạng thái (xanh / vàng / đỏ) như màu phân loại | Script: **FAIL**, vàng #E0A93B ↔ xanh nhạt #8DBF3F lệch màu ΔE 2,6 (mù đỏ–lục) và 12,6 (mắt thường), dưới ngưỡng 15. Độ tương phản với nền 2,06–2,12 | Dùng **một thang xanh lá đậm → nhạt** cho Top 1–3 / 4–10 / 11+, và **xám** cho "ngoài độ sâu check". Kiểm lại bằng `--ordinal`. Dành màu đỏ / vàng cho trạng thái |
| D3 | **P1** | Lượt hiển thị (Search Console) | **Trục Y ẩn và không bắt đầu từ 0** (`scale: true`): dao động nhỏ trông như biến động lớn. Không có số nào trên trục, chỉ đọc được qua tooltip | `dash_widgets.line_chart` | Bắt đầu trục từ 0, hoặc hiện nhãn min / max. Thêm dòng "cao nhất dd/mm: X" |
| D4 | **P1** | Phiên theo kênh | **Donut** khó so các phần gần nhau (Paid Social 14% vs Paid Search 11% vs Direct 9%). Skill khuyên dùng **thanh xếp hạng** khi cần so sánh. Bảng màu cũng chưa đạt | Script: **FAIL**, Paid Social #b35c2e ↔ Organic #1E7C31 lệch ΔE 3,0 (mù đỏ–lục); xám "Khác" dưới ngưỡng độ đậm màu. Tra cứu `chart` của ui-ux-pro-max: donut "risk:high", tối đa 5–6 phần | Đổi sang **thanh ngang xếp hạng** cùng một màu, kênh Organic tô màu nhấn (emphasis), các kênh khác xám. Hoặc giữ donut nhưng chỉ 2 phần: Organic và phần còn lại |
| D5 | **P1** | Uy tín (backlink) | **Vòng điểm không có mục tiêu hay ngưỡng.** Màu hồng không mang nghĩa gì; thang 0–1000 không có mốc so sánh nên vòng chỉ là trang trí | Tra cứu `chart`: gauge, "When NOT: no target" | Đổi thành **ô số** (238/1000, thay đổi so với lần lấy trước) kèm thanh mảnh 0–1000. Bỏ màu hồng |
| D6 | **P2** | Vòng Lighthouse | Ổn: dùng ngưỡng chuẩn 90 / 50 và có số ở giữa. Nhưng ngưỡng chỉ thể hiện bằng màu | Tra cứu: "red/yellow/green alone is insufficient" | Thêm chữ trạng thái dưới số ("Tốt" / "Cần cải thiện" / "Kém") |
| D7 | **P2** | Link mới / mất | Bảng màu đạt. Nhưng màu xanh nhạt #8DBF3F có độ tương phản 2,1 với nền, nên bắt buộc phải có nhãn hoặc bảng số | Script: cảnh báo độ tương phản | Ghi số tháng gần nhất ngay trên biểu đồ ("T10: +221 / −14") |
| D8 | **P2** | Mọi số lớn | Số lớn đứng riêng đang dùng chữ số đều độ rộng (class `num` = `tabular-nums`) nên trông thưa | Anti-pattern "tabular-nums on a large standalone number" | Bỏ `num` ở `.sr-db-num` / `.sr-db-big`; giữ ở bảng và trục |
| D9 | **P2** | Mọi biểu đồ | Không có bảng số thay thế; nhiều giá trị chỉ đọc được qua tooltip (rê chuột) | Anti-pattern "tooltip as the only way" | Thêm nút "Xem bảng" hoặc xuất số; tối thiểu ghi số cuối kỳ trên biểu đồ |

## 2. Trợ năng và tương tác (ui-ux-pro-max: ưu tiên 1–2)

| # | Mức | Vấn đề | Bằng chứng (đo trên trang) | Đề xuất |
|---|---|---|---|---|
| A1 | **P1** | **Thẻ bấm được nhưng bàn phím không tới được.** Thẻ "Click từ Google" và "Tỷ lệ hiện trong AI" là `div` có bắt sự kiện click | `tabIndex = -1`, không có `role` | Đổi thành `<a href>`, hoặc thêm `role="link"`, `tabindex=0` và xử lý phím Enter. Thêm dấu hiệu nhìn thấy là bấm được (mũi tên ›) |
| A2 | **P1** | **Biểu đồ không có mô tả cho trình đọc màn hình** | 9/9 biểu đồ không có `aria-label` | Thêm `aria-label` tóm tắt, ví dụ "Phân bố thứ hạng 5 lần check gần nhất: Top 1–3 từ 1 lên 9…" |
| A3 | **P1** | **Vùng bấm quá nhỏ** | Nút (i): 15×15px, độ tương phản 2,6. Link tiêu đề nhóm: cao 21px | Vùng bấm tối thiểu 24×24px (WCAG 2.2), trên điện thoại 44px; tăng padding cho link |
| A4 | **P2** | Một số chữ dưới 12px | 6 chữ 11,5px; nhãn trục / chú thích ECharts 11px | Tối thiểu 12px |
| A5 | OK | Độ tương phản chữ | Ngoài nút (i), không có chữ nào dưới 4,5:1 | Không cần sửa |

## 3. Bố cục và thứ bậc thông tin (ui-ux-pro-max: ưu tiên 3 và 5)

| # | Mức | Vấn đề | Đề xuất |
|---|---|---|---|
| L1 | **P1** | **Trang nhảy khi GA4 tải xong**: thẻ "Phiên theo kênh" từ một dòng chữ nở ra thành donut cao khoảng 300px (vi phạm quy tắc giữ chỗ để tránh nhảy bố cục, CLS < 0.1) | Giữ chỗ đúng chiều cao (skeleton) như đã làm cho khối KPI |
| L2 | **P1** | **Cột hàng 1 cao lệch nhau**: Thứ hạng cao hơn hẳn GA và Tốc độ, để lại khoảng trống lớn. Hàng 2 cũng vậy: Search Console cao hơn Backlink | Kéo các thẻ cuối mỗi cột cho bằng đáy (`align-items: stretch` + thẻ cuối `flex: 1`), hoặc đưa ghi chú AI Overview / đối thủ của Thứ hạng sang hàng dưới |
| L3 | **P2** | Thanh tiêu đề nhóm là một thẻ riêng, cách thẻ dưới 10px, tốn chiều cao. Khi trống còn lặp tên ("Thứ hạng" trên thanh và "Thứ hạng" trong thẻ) | Gộp thanh tiêu đề vào đầu khung nhóm (một khối nền nhạt chứa các thẻ), giống ảnh mẫu; bỏ tên trùng |
| L4 | **P2** | "Thay đổi thứ hạng ▼1" là số ròng (4 lên − 5 rớt), che mất việc có 9 từ khóa biến động | Hiện hai số "▲4 · ▼5" làm số chính, số ròng để dòng phụ |
| L5 | **P2** | Khoảng thời gian lặp lại 3 lần (tiêu đề trang, thanh GA, thanh Search Console) | Giữ ở tiêu đề trang; thanh nhóm chỉ ghi loại thời gian ("kỳ đang chọn" / "lần check" / "lần đo") |
| L6 | OK | Không tràn ngang ở 375 / 1100 / 1440px; thứ tự ưu tiên (Cần xử lý → KPI → số liệu) đúng spec | Không cần sửa |

## 4. Đã đạt

- Không gọi API trả phí khi mở trang (có test).
- Mỗi kênh GA4 giữ cố định một màu dù thứ tự thay đổi.
- Không có biểu đồ hai trục Y.
- Biểu đồ link mới (trên trục) / mất (dưới trục) đúng dạng cho dữ liệu hai chiều, và bảng màu đạt mọi bước kiểm tra.
- Kỳ trước vẽ nét đứt trên cùng trục với kỳ này.
- Mọi khối ghi loại thời gian và có link đi sâu.

## 5. Thứ tự sửa đề xuất

1. **P0:** D1 (cột thứ hạng tăng giả).
2. **P1 về số liệu:** D2, D3, D4, D5.
3. **P1 trợ năng / bố cục:** A1, A2, A3, L1, L2.
4. **P2:** D6–D9, A4, L3–L5.

Bản này chỉ review, chưa sửa code.
