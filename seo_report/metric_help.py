"""Giải thích từng chỉ số cho người đọc báo cáo (khách hàng, quản lý): hiện khi rê chuột vào nút (i) cạnh tên chỉ
số. Mỗi chỉ số ba ý: là gì, cho biết điều gì, đo thế nào. Viết một chỗ để mọi màn (Tổng quan, Báo cáo, AI Search,
Từ khóa & rank, Index, Công việc) dùng cùng một cách giải thích. Tra theo tên hiện trên ô."""

# (là gì, cho biết điều gì, đo thế nào)
_CLICKS = ("Số lần người dùng bấm vào website từ kết quả tìm kiếm Google.",
           "Lượng khách thực sự vào site nhờ SEO. Tăng là tín hiệu tốt nhất của SEO.",
           "Google Search Console đếm. Ngày gần nhất Google có thể còn cập nhật thêm 1–2 ngày.")
_IMPR = ("Số lần một trang của website hiện trong kết quả tìm kiếm Google mà người dùng có thể thấy (kể cả không "
         "bấm).",
         "Độ phủ của website trên Google: hiện cho càng nhiều tìm kiếm thì càng có cơ hội được bấm.",
         "Google Search Console đếm; một lần tìm kiếm hiện 2 trang của site vẫn tính 1.")
_ORGANIC = ("Số phiên truy cập đến từ công cụ tìm kiếm không trả tiền (Google, Bing, Cốc Cốc…).",
            "Lượng khách SEO mang về, đo ngay trên website. Thường lệch với Click của Google vì hai công cụ đếm "
            "khác nhau (chặn cookie, nhiều click trong một phiên…).",
            "Google Analytics 4, kênh Organic Search. Một phiên = một lần vào site, hết sau 30 phút không thao tác.")
_AI = ("Số phiên truy cập đến từ trợ lý AI như ChatGPT, Gemini, Perplexity, Copilot.",
       "Website có được AI nhắc tới và dẫn link cho người dùng hay không.",
       "Google Analytics 4: phiên có nguồn giới thiệu là các trang AI. Chưa tính người đọc câu trả lời AI mà không "
       "bấm link.")
_AI_SHARE = ("Phần lượt hiển thị trên Google nằm trong câu trả lời AI của Google (AI Overviews, AI Mode).",
             "Mức độ website được Google AI chọn làm nguồn trích dẫn, so với toàn bộ lượt hiển thị.",
             "Lấy từ báo cáo AI của Google Search Console nhập vào tool, chia cho tổng lượt hiển thị Web. Google "
             "thường có số trễ vài ngày.")
_AI_IMPR = ("Số lần website hiện làm nguồn trong câu trả lời AI của Google (AI Overviews, AI Mode).",
            "Độ phủ của website trong kết quả AI của Google.",
            "Báo cáo AI của Google Search Console nhập vào tool. Ngày Google chưa có số thì để trống, không tính 0.")

HELP: dict[str, tuple[str, str, str]] = {
    # Google Search Console
    "click": _CLICKS, "click từ google": _CLICKS, "click (gsc)": _CLICKS,
    "lượt hiển thị": _IMPR, "impression (gsc)": _IMPR,
    # Google Analytics 4
    "lượt truy cập": _ORGANIC, "lượt truy cập organic": _ORGANIC, "phiên organic search (ga4)": _ORGANIC,
    "lượt truy cập (mọi kênh)": (
        "Tổng số phiên truy cập website từ mọi nguồn: tìm kiếm, quảng cáo, mạng xã hội, gõ thẳng địa chỉ…",
        "Quy mô truy cập chung của website; SEO là một phần trong số này.",
        "Google Analytics 4. Một phiên = một lần vào site, hết sau 30 phút không thao tác."),
    # AI
    "truy cập từ ai": _AI, "phiên ai": _AI,
    "tỷ lệ hiện trong ai": _AI_SHARE, "tỷ lệ trên impression gsc web": _AI_SHARE,
    "lượt hiện trong ai": _AI_IMPR, "impression ai overviews / ai mode": _AI_IMPR,
    "tỷ lệ ai": ("Phần trăm phiên đến từ trợ lý AI trên tổng phiên của website.",
                 "AI đang mang về bao nhiêu phần lưu lượng của website.",
                 "Phiên từ AI chia cho tổng phiên, đều theo Google Analytics 4."),
    "tỷ lệ ai (nhóm organic)": (
        "Phần trăm phiên từ AI trong nhóm kênh tự nhiên: AI + Organic Search + Social.",
        "So AI với các kênh không trả tiền khác, không bị quảng cáo làm loãng.",
        "Google Analytics 4."),
    "engaged sessions": ("Số phiên có tương tác thật: ở lại trên 10 giây, xem từ 2 trang, hoặc có hành động quan "
                         "trọng.",
                         "Khách từ AI có thật sự đọc nội dung hay vào rồi thoát ngay.",
                         "Google Analytics 4 tự đánh dấu phiên có tương tác."),
    "engagement rate": ("Phần trăm phiên có tương tác trên tổng phiên.",
                        "Chất lượng lượt truy cập: càng cao khách càng quan tâm.",
                        "Engaged sessions chia cho tổng phiên (Google Analytics 4)."),
    "thời gian tương tác tb/phiên": ("Thời gian trung bình người dùng thực sự xem trang trong một phiên.",
                                     "Nội dung có giữ chân người đọc hay không.",
                                     "Google Analytics 4 chỉ đếm lúc tab website đang mở trên màn hình."),
    "key events": ("Số lần người dùng thực hiện hành động quan trọng: gọi điện, gửi form, đặt hàng…",
                   "Lượt truy cập có mang lại kết quả kinh doanh hay không.",
                   "Google Analytics 4 đếm các sự kiện được đánh dấu là key event trong cài đặt GA4."),
    "session key event rate": ("Phần trăm phiên có ít nhất một hành động quan trọng.",
                               "Tỷ lệ chuyển đổi của lượt truy cập.",
                               "Phiên có key event chia cho tổng phiên (Google Analytics 4)."),
    # Từ khóa & rank
    "keyword theo dõi": ("Số từ khóa tool đang check vị trí trên Google.",
                         "Phạm vi theo dõi thứ hạng của dự án.",
                         "Gồm từ khóa cam kết (lấy từ sheet) và từ khóa team thêm."),
    "trong top 10": ("Số từ khóa có website nằm ở trang đầu Google (vị trí 1–10) ở lần check gần nhất.",
                     "Mức hiện diện ở vị trí có nhiều click nhất.",
                     "DataForSEO tìm trên Google theo nơi check của dự án (vùng, thiết bị, thành phố). Đây là vị trí "
                     "thật, không phải vị trí trung bình của Search Console."),
    "tổng volume theo dõi": ("Tổng lượt tìm kiếm mỗi tháng của các từ khóa đang theo dõi.",
                             "Quy mô nhu cầu tìm kiếm mà bộ từ khóa nhắm tới.",
                             "Số trung bình tháng của Google Ads, lấy qua DataForSEO."),
    "sai url mục tiêu": ("Số từ khóa Google đang xếp hạng một trang khác với trang mục tiêu đã gán.",
                         "Có thể trang mục tiêu chưa đủ tốt, hoặc nhiều trang trong site tranh nhau một từ khóa.",
                         "So URL đang xếp hạng ở lần check gần nhất với URL mục tiêu của từ khóa."),
    # Index
    "đã index · toàn site": ("Số trang đã có trong chỉ mục của Google trên số trang tool đã kiểm tra.",
                             "Trang chưa index thì không thể hiện trên Google, dù nội dung tốt.",
                             "Công cụ kiểm tra URL của Google Search Console, lần kiểm tra gần nhất của mỗi URL."),
    "chưa index · cần xem": ("Số trang Google chưa đưa vào chỉ mục mà lẽ ra nên có.",
                             "Việc cần xử lý để trang có cơ hội lên Google.",
                             "Không tính trang cố ý loại trừ (noindex, chuyển hướng, trang trùng đã chọn bản "
                             "chính)."),
    "quota kiểm tra hôm nay": ("Số lần kiểm tra index còn được dùng trong ngày.",
                               "Google giới hạn số URL kiểm tra mỗi ngày cho một website.",
                               "Theo giới hạn của Google Search Console, tính lại mỗi ngày."),
    # Công việc
    "hoàn thành okr 3 tháng": ("Phần trăm hạng mục OKR của quý đã xong.",
                               "Tiến độ kế hoạch 3 tháng.",
                               "Đọc từ sheet OKR của dự án."),
    "đang làm": ("Số hạng mục đang thực hiện.", "Khối lượng việc đang chạy.", "Đọc từ sheet công việc của dự án."),
    "trễ hạn": ("Số hạng mục đã qua hạn mà chưa xong.", "Việc cần ưu tiên hoặc dời hạn.",
                "So hạn trong sheet công việc với ngày hôm nay."),
}
_PREFIX = {"xong trong": ("Số hạng mục hoàn thành trong kỳ đang xem.", "Khối lượng việc đã làm xong trong kỳ.",
                          "Đọc từ sheet công việc của dự án."),
           "nhóm ": ("Số trang của nhóm URL này đã có trên Google.",
                     "Tình trạng index của nhóm trang quan trọng.",
                     "Công cụ kiểm tra URL của Google Search Console.")}


def help_for(label: str) -> tuple[str, str, str] | None:
    """(là gì, cho biết điều gì, đo thế nào) của chỉ số theo tên hiện trên ô; không có thì None."""
    key = " ".join((label or "").split()).lower()
    if key in HELP:
        return HELP[key]
    return next((v for p, v in _PREFIX.items() if key.startswith(p)), None)
