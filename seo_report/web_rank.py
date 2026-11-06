"""Màn Từ khóa & rank: mỗi bộ từ khóa một tab (bộ Cam kết theo sheet + các bộ team tạo), mỗi bộ nơi check / lịch
riêng. Trong một bộ: thêm / sửa (Top mục tiêu, URL mục tiêu) / bỏ từ khóa, check ngay, biểu đồ tăng trưởng, phân bố vị
trí, bảng và lịch sử từng từ khóa. Sửa từ khóa ở bộ Cam kết thì tool ghi thẳng lên tab Từ khóa cam kết của sheet."""
import io
import math
from datetime import date
from types import SimpleNamespace

from . import keywords as K
from . import rank as R
from .projects import domain


def _vn(iso: str | None) -> str:
    if not iso:
        return ""
    y, m, d = iso[:10].split("-")
    return f"{d}/{m}/{y}"


def _local(iso_utc: str) -> str:
    """Thời điểm lưu theo UTC → giờ Việt Nam "05/11/2026 14:30"."""
    from datetime import datetime, timedelta
    try:
        t = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return iso_utc or ""
    return (t.replace(tzinfo=None) + timedelta(hours=7) if t.tzinfo else t).strftime("%d/%m/%Y %H:%M")


def _short_change(text: str) -> str:
    """Chữ thay đổi gọn cho bảng: "▲ 4" → "4", "▼ rớt khỏi top 20" → "rớt", "▲ vào top 20" → "vào top 20"."""
    t = (text or "").replace("▲", "").replace("▼", "").strip()
    if t.startswith("rớt khỏi"):
        return "rớt"
    return t


def _pos(rank, depth) -> str:
    if depth is None:
        return ""
    return str(rank) if rank is not None else f">{depth}"


# Check ngay chạy nền phía server, không gắn với trang đã bấm: đổi trang / đóng tab vẫn check tiếp, xong thì báo trên
# trang người bấm đang mở và làm mới bảng ở mọi trang Từ khóa & rank của website đó.
_RUNNING: set[str] = set()  # website đang check
_VIEWS: dict[str, dict[str, object]] = {}  # website → {client id: hàm làm mới bảng}
# Tiến độ lượt Check ngay đang chạy: website → {set, total, posted, done, stop}. Trang đang mở đọc mỗi giây.
_PROGRESS: dict[str, dict] = {}
# Từ khóa chưa gửi khi bấm Tạm dừng: (website, id bộ) → [id từ khóa] — nút "Tiếp tục" check nốt (không check lại
# từ khóa đã có kết quả).
_PAUSED: dict[tuple[str, int], list[int]] = {}
CHECK_CHUNK = 10  # gửi DataForSEO từng nhóm 10 từ khóa: bấm Tạm dừng thì nhóm chưa gửi không tốn tiền

GOOGLE_NAMES = {"google.com.vn": "Google Việt Nam", "google.com": "Google quốc tế", "google.co.th": "Google Thái Lan",
                "google.com.sg": "Google Singapore", "google.co.jp": "Google Nhật Bản", "google.com.au": "Google Úc",
                "google.co.uk": "Google Anh"}
SOURCES = {"kpi": "Cam kết", "manual": "Nhập tay", "gsc": "Từ GSC (★)"}
TOPS = [1, 3, 5, 10, 20, 30]

# Bộ lọc bảng: (tên, điều kiện trên một dòng của rank.keywords)
FILTERS = {
    "all": ("Tất cả", lambda k: True),
    "top3": ("Top 3", lambda k: k["rank"] is not None and k["rank"] <= 3),
    "top10": ("Top 4–10", lambda k: k["rank"] is not None and 3 < k["rank"] <= 10),
    "top30": ("Hạng 11 trở đi", lambda k: k["rank"] is not None and k["rank"] > 10),
    "out": ("Không thấy trong độ sâu check", lambda k: k["date"] and k["rank"] is None),
    "unchecked": ("Chưa check", lambda k: not k["date"]),
    "miss": ("Chưa đạt Top mục tiêu", lambda k: k.get("top_target") and (k["rank"] is None
                                                                          or k["rank"] > k["top_target"])),
    "wrong": ("Sai URL mục tiêu", lambda k: k["target_url"] and k["ranking_url"]
              and k["ranking_url"] != k["target_url"]),
    "down": ("Rớt hạng lần vừa rồi", lambda k: change_text(k)[2] < 0),
    "up": ("Lên hạng lần vừa rồi", lambda k: change_text(k)[2] > 0),
    "notarget": ("Chưa có URL mục tiêu", lambda k: not k["target_url"]),
    "paused": ("Đang tạm dừng", lambda k: k["paused"]),
    "note": ("Có ghi chú", lambda k: bool(k["note"])),
}

def icon_btn(ui, icon: str, tip: str, on_click=None, kind: str = "flat", color: str = "", badge=None):
    """Nút tròn chỉ có icon; tip hiện khi rê chuột và là tên đọc cho trình đọc màn hình. badge: số nhỏ ở góc."""
    b = ui.button(icon=icon, on_click=on_click).props(
        f"{kind} round dense" + (f" color={color}" if color else "")).tooltip(tip)
    b.props["aria-label"] = tip
    if badge:
        with b:
            ui.badge(str(badge)).props("floating rounded color=grey-7")
    return b


RANK_TONES = [(3, ("#E7F3EA", "#1E7C31")), (10, ("#F2F7DC", "#5E7414")), (30, ("#FBF1DE", "#B7791F"))]


def change_text(k: dict) -> tuple[str, str, int]:
    from .report import rank_change
    return rank_change(k["date"], k["rank"], k["last_depth"], k["prev"], k["prev_depth"])


def event_marks(hist: list[dict], evs: list[dict], time: bool = False) -> dict:
    """Mốc sự kiện thành vạch dọc trên biểu đồ tăng trưởng: đặt ở lần check đầu tiên từ ngày sự kiện trở đi (trục là
    các ngày check). Mốc sau lần check cuối thì chưa vẽ."""
    labels: dict[str, list[str]] = {}
    for e in evs:
        h = next((h for h in hist if h.get("end", h["date"]) >= e["day"]), None)
        if h:
            x = h["date"] if time else (h.get("label") or _vn(h["date"])[:5])  # trục thời gian: theo ngày thật
            labels.setdefault(x, []).append(f"{_vn(e['day'])[:5]} {e['text']}")
    if not labels:
        return {}
    return {"markLine": {"symbol": "none", "silent": True, "animation": False,
                         "lineStyle": {"color": "#7C3AED", "type": "dashed", "width": 1},
                         "label": {"position": "insideEndTop", "color": "#5B21B6", "fontSize": 10,
                                   "overflow": "truncate", "width": 140, "backgroundColor": "rgba(255,255,255,.94)",
                                   "padding": [2, 5], "borderRadius": 4},
                         "data": [{"xAxis": x, "label": {"formatter": " · ".join(t)}} for x, t in labels.items()]}}


TIER_COLORS = {3: "#1E7C31", 5: "#4E9A2F", 10: "#9BB823"}
# Icon của từng ô bento: (icon Material, màu icon, nền vòng tròn)
CELL_ICONS = {"t3": ("emoji_events", "#B7791F", "#FBF1DE"), "t5": ("workspace_premium", "#1E7C31", "#E7F3EA"),
              "t10": ("military_tech", "#5E7414", "#F2F7DC"), "o10": ("trending_down", "#C2410C", "#FCEBE3"),
              "cov": ("donut_large", "#2563EB", "#E8EFFD"), "hit": ("flag", "#8F5F14", "#FBF1DE"),
              "mov": ("swap_vert", "#7C3AED", "#F1EAFB"), "gr": ("show_chart", "#1E7C31", "#E7F3EA"),
              "aio": ("auto_awesome", "#6250d6", "#EEEDFE")}


def _tops(h: dict | None) -> dict[int, int]:
    """Số từ khóa trong Top 3 / Top 5 / Top 10 (cộng dồn các nhóm) của một điểm set_history."""
    return {3: h["top3"], 5: h["top3"] + h["top5"], 10: h["top3"] + h["top5"] + h["top10"]} if h else {}


def _move(ui, d: int, good_up: bool = True) -> None:
    """Nhãn thay đổi theo tốt / xấu: tăng ▲ xanh, giảm ▼ đỏ, không đổi xám."""
    if not d:
        ui.label("±0").classes("sr-delta flat")  # gọn: chữ "không đổi" làm vỡ dòng số trong thẻ hẹp
        return
    good = (d > 0) == good_up
    ui.label(("▲ " if d > 0 else "▼ ") + str(abs(d))).classes(f"sr-delta {'up' if good else 'down'}")


def _kw_move(k: dict) -> dict | None:
    """Biến động của một từ khóa so với lần check trước của chính nó, nói bằng chữ (không dùng con số giả khi một
    phía nằm ngoài độ sâu check). None: chưa có hai lần check để so."""
    if not k["date"] or not k["prev_depth"]:
        return None
    rank, prev, t = k["rank"], k["prev"], k.get("top_target")
    before = str(prev) if prev is not None else f">{k['prev_depth']}"
    now = str(rank) if rank is not None else f">{k['last_depth']}"
    if rank is not None and prev is not None:
        d = prev - rank
        text = "Không đổi" if not d else (f"Tăng {d} bậc" if d > 0 else f"Giảm {-d} bậc")
    elif rank is not None:
        d, text = 100, f"Vào top {k['prev_depth']} (trước đó ngoài top {k['prev_depth']})"
    elif prev is not None:
        d, text = -100, f"Rớt khỏi top {k['last_depth']}, chưa rõ hạng mới"
    else:
        d, text = 0, "Vẫn ngoài độ sâu check"
    hit_now = bool(t and rank is not None and rank <= t)
    hit_before = bool(t and prev is not None and prev <= t)
    return {"k": k, "d": d, "text": text, "before": before, "now": now,
            "lost": hit_before and not hit_now, "gained": hit_now and not hit_before}


def _sr(ui, text: str) -> None:
    """Chữ chỉ dành cho trình đọc màn hình (ẩn khỏi mắt)."""
    ui.label(text).classes("sr-only")


def bento(ui, kws: list[dict], hist: list[dict], evs: list[dict], load, state: dict, on_events, on_open,
          on_filter=None, short_url=lambda u: u or "", kpi_now: dict | None = None, aio: dict | None = None,
          aio_link: str = "/aio") -> None:
    """Tổng quan một bộ, một khung bento 5 cột cùng khe, cùng bo góc:
    hàng 1 — 5 thẻ KPI: Top 3 · Top 5 · Top 10 (cộng dồn) · Ngoài top 10 · Đạt Top mục tiêu (theo mục tiêu riêng của
    từng từ khóa); mỗi thẻ: số / tổng, %, thay đổi so với lần check trước và ngày + số của lần đó.
    hàng 2 — Xu hướng thứ hạng (3 cột) · Phân bổ thứ hạng (2 cột, nhóm loại trừ nhau theo độ sâu check thật).
    hàng 3 — Biến động đáng chú ý (cả hàng): mất mục tiêu, rớt hạng, lên hạng; bấm để xem lịch sử từ khóa.
    Mọi số lấy từ cùng một điểm set_history (lần check mới nhất của từng từ khóa) và điểm trước đó."""
    from . import ui_theme as T
    total = len(kws)
    last, prev = (hist[-1] if hist else None), (hist[-2] if len(hist) > 1 else None)
    now_t, prev_t = _tops(last), _tops(prev)
    d_prev = _vn(prev["date"])[:5] if prev else ""
    deep_label, out_label = R.band_labels(last)

    def aio_cell(a: dict) -> None:
        """Hàng AI Overview của bộ: có AIO · website được trích · được nhắc tên · đối thủ được trích nhiều nhất."""
        pv = a.get("prev")
        with cell("aio", "AI Overview", (
                "Từ lần check gần nhất có đọc AI Overview của từng từ khóa trong bộ (không tốn thêm phí).",
                "Được trích: AI Overview có link về website. Được nhắc: câu trả lời AI có tên thương hiệu (cần nội dung "
                "chữ, có từ lần check 08/11).",
                "▲▼ so với lần check trước đó của các từ khóa.")) as box:
            head = box.default_slot.children[0]
            with head:
                ui.space()
                ui.link("Xem chi tiết →", aio_link).classes("text-sm")
            if not a["checked"]:
                ui.label("Chưa có số AI Overview: lần check tới của bộ sẽ có.").classes("text-sm muted")
                return

            def stat(label, val, of, prev_val=None, tip=""):
                with ui.column().classes("gap-0 sr-aio-stat") as col:
                    ui.label(label).classes("sr-aio-lab")
                    with ui.row().classes("items-baseline no-wrap gap-2"):
                        ui.label(str(val) if val is not None else "–").classes("sr-bx-num")
                        if of is not None:
                            ui.label(f"/ {of}").classes("sr-bx-of")
                        if prev_val is not None and val is not None and val != prev_val:
                            _move(ui, val - prev_val, True)
                if tip:
                    col.tooltip(tip)
            with ui.element("div").classes("sr-aio-row"):
                stat("Có AI Overview", a["aio"], a["checked"], pv and pv["aio"], "Số từ khóa Google hiện câu trả lời AI")
                stat("Website được trích", a["cited"], a["reffed"] or None, pv and pv["cited"],
                     "Trên số từ khóa có AI Overview đọc được nguồn")
                stat("Được nhắc tên", a["mentioned"] if a["texted"] else None, a["texted"] or None,
                     pv and pv["texted"] and pv["mentioned"], "Trên số AI Overview có nội dung chữ")
                with ui.column().classes("gap-0 sr-aio-stat"):
                    ui.label("Đối thủ được trích nhiều nhất").classes("sr-aio-lab")
                    if a["top_rival"]:
                        b, n = a["top_rival"]
                        with ui.row().classes("items-center no-wrap gap-2"):
                            ui.element("i").classes("sr-brand-dot").style(f"background:{b['color']}")
                            ui.label(b["name"]).classes("text-weight-bold ellipsis")
                            ui.label(f"{n} từ khóa").classes("muted text-sm")
                    else:
                        ui.label("Chưa có").classes("muted")

    def cell(area: str, title: str, info: tuple | None = None):
        box = ui.element("section").classes("sr-bx-cell").style(f"grid-area:{area}")
        box.props["aria-label"] = title
        with box:
            with ui.row().classes("w-full items-center gap-2 no-wrap sr-bx-head"):
                icon, fg, bg = CELL_ICONS.get(area, ("circle", "#6B6A5E", "#F1F0EA"))
                plain = area in ("t3", "t5", "t10", "o10", "hit")  # thẻ KPI: icon trơn, số là phần nổi bật
                with ui.element("span").classes("sr-bx-icon" + (" plain" if plain else "")).style(
                        "" if plain else f"background:{bg}"):
                    ui.icon(icon, size="16px").style(f"color:{fg}").props('aria-hidden="true"')
                ui.label(title).classes("sr-bx-title")
                if info:
                    T.info_icon(ui, title, info)
        return box

    def figure(value, of, d, good_up=True):
        """Số chính / tổng, %, nhãn thay đổi (▲ ▼ + số, kèm câu đầy đủ cho trình đọc màn hình và khi rê chuột)."""
        with ui.row().classes("w-full items-baseline gap-2 no-wrap"):
            ui.label(f"{value}" if value is not None else "–").classes("sr-bx-num")
            ui.label(f"/ {of}").classes("sr-bx-of")
            if value is not None and of:
                ui.label(f"{value / of * 100:.0f}%").classes("sr-bx-pct")
            ui.space()
            if d is not None:
                words = "không đổi" if not d else f"{'tăng' if d > 0 else 'giảm'} {abs(d)}"
                with ui.element("span").classes("row no-wrap"):
                    _move(ui, d, good_up)
                    _sr(ui, f"{words} so với lần check {d_prev}")
                    ui.tooltip(f"{words.capitalize()} so với lần check {d_prev}")

    def prev_line(before, best: str = ""):
        """Ngày (nhãn xám có icon lịch) + số của lần check trước, màu nhạt. Mức cao nhất: trong chú thích."""
        if not prev:
            ui.label("Lần check đầu tiên, chưa có lần trước để so").classes("sr-cmp-note")
            return
        with ui.row().classes("items-center no-wrap sr-fromto"):
            with ui.element("span").classes("sr-day"):
                ui.icon("event", size="12px").props('aria-hidden="true"')
                ui.label(d_prev)
            ui.label("–" if before is None else str(before)).classes("sr-ft-val")
            _sr(ui, f"Lần check trước ngày {d_prev}: {'–' if before is None else before} từ khóa")
            ui.tooltip(f"Lần check trước ({_vn(prev['date'])}): {'–' if before is None else before} từ khóa"
                       + (f". {best}" if best else ""))

    def moves(up: int, down: int, up_word: str = "lên hạng", down_word: str = "rớt hạng"):
        """Hàng nhãn dưới thẻ (cùng kiểu nhãn ô Thứ hạng ở Tổng quan), chia 2 cột đều: "1 lên hạng" (xanh), "1 rớt
        hạng" (đỏ); không đổi thì "Giữ nguyên". So với lần check trước của chính từng từ khóa."""
        if not prev:
            return None
        box = ui.element("div").classes("sr-tier-chips")
        with box:
            if up:
                T.status_chip(ui, f"{up} {up_word}", "green", "trending_up")
            if down:
                T.status_chip(ui, f"{down} {down_word}", "red", "trending_down")
            if not up and not down:
                T.status_chip(ui, "Giữ nguyên", "grey", "remove")
        box.tooltip("So với lần check trước của từng từ khóa")
        return box

    def kcard(area: str, title: str, info: tuple, inside, was_inside, of: int, good_up: bool = True,
              extra=None, words: tuple | None = None) -> None:
        """Thẻ KPI: số chính / tổng (+ % tổng từ khóa ở góc), rồi một cụm so sánh: "So với 04/11 · Giảm 2 từ khóa"
        (thay đổi số từ khóa trong nhóm) và "Trước đó · 11 từ khóa". inside(k) / was_inside(k): từ khóa có trong
        nhóm ở lần check này / lần trước. Luôn khớp: hiện tại = trước đó + vào − rời + check lần đầu."""
        checked = [k for k in kws if k["date"]]
        value = sum(1 for k in checked if inside(k))
        with_prev = [k for k in checked if k["prev_depth"]]
        before = sum(1 for k in with_prev if was_inside(k))
        enter = sum(1 for k in with_prev if inside(k) and not was_inside(k))
        leave = sum(1 for k in with_prev if was_inside(k) and not inside(k))
        new_in = sum(1 for k in checked if not k["prev_depth"] and inside(k))
        with cell(area, title, info) as box:
            head = box.default_slot.children[0]
            with head:
                ui.space()
                if of:
                    ui.label(f"{value / of * 100:.0f}%").classes("sr-kc-pct").tooltip(
                        f"{value / of * 100:.0f}% tổng số từ khóa")
            delta = value - before  # = vào − rời + mới kiểm tra: số chính tăng là xanh (giảm là đỏ), thẻ "Ngoài
            # top 20" ngược lại. Phần chi tiết bên dưới vẫn tách riêng từ khóa mới kiểm tra.
            tone = "" if not delta else (" good" if (delta > 0) == good_up else " bad")
            with ui.row().classes("w-full items-baseline no-wrap gap-2 sr-kc-main"):
                ui.label(str(value) if checked else "–").classes("sr-kc-num" + tone)
                ui.label(f"/ {of} từ khóa").classes("sr-kc-of")
                if with_prev and delta:  # nhãn nhỏ: tăng / giảm bao nhiêu so với "Trước đó"
                    in_word, out_word = words or (f"Vào {title}", f"Rời {title}")
                    ui.label(f"{'▲' if delta > 0 else '▼'} {abs(delta)}").classes("sr-kc-delta" + tone).tooltip(
                        f"{'Tăng' if delta > 0 else 'Giảm'} {abs(delta)} từ khóa so với trước đó ({before}): "
                        f"{in_word.lower()} {enter}, {out_word.lower()} {leave}, mới kiểm tra {new_in}.")

            if not with_prev:
                ui.label("Lần check đầu tiên, chưa có lần trước để so").classes("sr-kc-note")
                return
            with ui.element("div").classes("sr-kc-foot") as foot:
                # gọn: chỉ so với / trước đó (chi tiết vào · rời · mới kiểm tra nằm trong chú thích của nhãn ▲▼)
                ui.label(f"So với {d_prev}" if d_prev else "So với lần trước").classes("sr-kc-lab")
                ui.html(f"<span class='sr-kc-lab'>Trước đó</span> <b class='sr-kc-prev{' zero' if not before else ''}'>"
                        f"{before}</b>").classes("sr-kc-r")
                if extra:  # thẻ Đạt mục tiêu: thêm dòng "Chưa đạt"
                    extra()
            foot.tooltip(f"Hiện tại {value} = trước đó {before} + vào {enter} − rời {leave} + mới kiểm tra {new_in}. "
                         f"Vào / rời: so với lần check trước của chính từng từ khóa (phần lớn ngày {d_prev}). Mới "
                         "kiểm tra: từ khóa check lần đầu, chưa có lịch sử để so.")

    def tier(n: int) -> tuple[int, int]:
        """(vào, rời) Top n: so vị trí lần này với lần trước của từng từ khóa (ngoài độ sâu = không ở trong nhóm)."""
        enter = leave = 0
        for k in kws:
            if not k["date"] or not k["prev_depth"]:
                continue
            now_in = k["rank"] is not None and k["rank"] <= n
            was_in = k["prev"] is not None and k["prev"] <= n
            enter += now_in and not was_in
            leave += was_in and not now_in
        return enter, leave

    def best_text(values: list) -> str:
        pts = [(v, h) for v, h in zip(values, hist) if v is not None]
        if len(pts) < 2:
            return ""
        top = max(v for v, _ in pts)
        return f"Cao nhất: {top} từ khóa, ngày {_vn(next(h for v, h in pts if v == top)['date'])[:5]}"

    with ui.element("div").classes("sr-bx w-full"):
        # ---- Hàng 1: KPI ----
        for n, area in ((3, "t3"), (5, "t5"), (10, "t10")):
            kcard(area, f"Top {n}", (
                f"Số từ khóa của bộ đang ở hạng 1–{n} trên Google (cộng dồn: Top {n} gồm cả các nhóm cao hơn), trên "
                "tổng số từ khóa của bộ.",
                f"“Tăng / Giảm”: số từ khóa trong Top {n} thay đổi bao nhiêu so với lần check trước của từng từ khóa "
                "(vào nhóm trừ rời nhóm). Khác với “lên / rớt hạng” trong bảng (đổi vị trí của từng từ khóa).",
                "“Trước đó”: số từ khóa trong nhóm ở lần check trước. Từ khóa check lần đầu ghi riêng, không tính là "
                "tăng."),
                lambda k, n=n: k["rank"] is not None and k["rank"] <= n,
                lambda k, n=n: k["prev"] is not None and k["prev"] <= n, total)

        kcard("o10", "Ngoài top 20", (
            "Số từ khóa chưa vào top 20 Google: thấy ở hạng 21 trở đi, hoặc không thấy trong độ sâu đã check.",
            "Số này giảm là tốt. “Rớt khỏi top 20”: lần trước trong top 20, lần này ra ngoài. “Lên top 20”: lần "
            "trước ngoài top 20, lần này vào.",
            "Mọi lần check đều xem ít nhất top 20, nên “ngoài top 20” là chắc chắn. Riêng các lần check cũ chỉ xem "
            "top 10: không thấy thì tạm tính là ngoài top 20."),
            lambda k: k["rank"] is None or k["rank"] > 20,
            lambda k: k["prev"] is None or k["prev"] > 20, total, good_up=False,
            words=("Rớt khỏi top 20", "Lên top 20"))

        targeted = [k for k in kws if k.get("top_target")]
        if targeted:
            kcard("hit", "Đạt mục tiêu", (
                "Số từ khóa đã đạt Top mục tiêu của chính nó (mỗi từ khóa một mục tiêu, ví dụ mục tiêu Top 3 và đang "
                "hạng 2), trên số từ khóa có đặt mục tiêu.",
                "Trả lời câu hỏi: bộ từ khóa đã đạt cam kết chưa. Lọc “Chưa đạt Top mục tiêu” ở bảng để xem các từ "
                "khóa còn lại."),
                lambda k: bool(k.get("top_target")) and k["rank"] is not None and k["rank"] <= k["top_target"],
                lambda k: bool(k.get("top_target")) and k["prev"] is not None and k["prev"] <= k["top_target"],
                len(targeted), words=("Đạt thêm", "Mất mục tiêu"))
        else:
            with cell("hit", "Đạt Top mục tiêu", ("Chưa có từ khóa nào đặt Top mục tiêu.",)):
                ui.label("Chưa đặt Top mục tiêu").classes("text-sm muted q-mt-sm")
                ui.label("Đặt ở nút ✏️ trên từng từ khóa trong bảng").classes("sr-cmp-note")

        # ---- Hàng 2: Xu hướng thứ hạng (bảng hoặc biểu đồ, kèm mục tiêu cam kết của bộ Cam kết) ----
        unit = {"check": "lần check", "week": "tuần", "month": "tháng"}
        goals = []  # (nhãn, {N: số từ khóa cần}, đạt?) — mục tiêu cam kết Top N của tháng / quý dự án hiện tại
        if kpi_now:
            for key, name in (("month", f"Cam kết tháng {kpi_now['month']}"),
                              ("quarter", f"Cam kết quý {kpi_now['quarter']}")):
                need = {r["top"]: r[key]["need"] for r in kpi_now["rows"] if r[key]["need"] is not None}
                if need:
                    goals.append((name, need))
        state.setdefault("view", "chart" if len(load(state["period"])) >= 4 else "table")
        with cell("gr", "Xu hướng thứ hạng", (
                "Số từ khóa của bộ ở Top 3 / Top 5 / Top 10 qua từng lần check, tuần hoặc tháng (trục dọc là số từ "
                "khóa, không phải vị trí: đường đi lên là tốt). Dòng “Hiện tại” là lần mới nhất.",
                "Vạch xám “+N từ khóa check lần đầu”: số tăng ở điểm đó có thể do thêm từ khóa có số, chưa chắc do lên "
                "hạng. Rê chuột lên điểm để xem đã check bao nhiêu từ khóa.",
                "Bộ Cam kết: dòng “Cam kết” là số từ khóa phải đạt theo KPI (tháng / quý dự án hiện tại); trên "
                "biểu đồ là đường nét đứt cùng màu.",
                "Lần check: trục là ngày thật. Tuần / tháng: lần check cuối của từng từ khóa tính đến cuối kỳ; kỳ "
                "không check giữ số kỳ trước. Vạch tím là mốc sự kiện.")) as gr:
            head = gr.default_slot.children[0]
            with head:
                ui.space()
                tg = ui.toggle(dict(R.PERIODS), value=state["period"],
                               on_change=lambda e: (state.update(period=e.value), line.refresh())).props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes("sr-seg")
                tg.props['aria-label'] = "Xem theo lần check, tuần hoặc tháng"
                vw = ui.toggle({"table": "Bảng", "chart": "Biểu đồ"}, value=state["view"],
                               on_change=lambda e: (state.update(view=e.value), line.refresh())).props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes("sr-seg")
                vw.props['aria-label'] = "Xem dạng bảng hoặc biểu đồ"
                icon_btn(ui, "flag", "Mốc sự kiện: đánh dấu Google update, đẩy backlink, viết lại bài… lên biểu đồ",
                         on_events, color="deep-purple-7", badge=len(evs) if evs else None)

            def avg_chart(h, time_axis: bool, marks: dict, period: str) -> None:
                """Vị trí trung bình của các từ khóa có hạng ở từng lần check / tuần / tháng. Trục đảo: hạng 1 ở trên
                cùng nên đường đi lên là tốt. Vạch xám: lần có nhiều từ khóa check lần đầu (trung bình có thể nhảy vì
                thêm từ khóa, không phải vì đổi hạng)."""
                pts = [(x, x["avg"]) for x in h]
                vals = [v for _, v in pts if v is not None]
                if not vals:
                    ui.label("Chưa có từ khóa nào có hạng trong độ sâu đã check.").classes("text-sm muted q-py-md")
                    return
                top_y = max(10, int(math.ceil(max(vals) / 5.0) * 5))
                ranked = [x["checked"] - x["out"] for x in h]
                firsts = []
                for i in range(1, len(h)):
                    added = h[i]["checked"] - h[i - 1]["checked"]
                    if added > 0:
                        firsts.append({"xAxis": h[i]["date"] if time_axis else h[i]["label"],
                                       "label": {"formatter": f"+{added} từ khóa check lần đầu"}})
                series = [{"type": "line", "name": "Vị trí trung bình", "symbol": "circle", "symbolSize": 8,
                           "smooth": False, "connectNulls": True,
                           "data": [[x["date"], v] for x, v in pts] if time_axis else [v for _, v in pts],
                           "lineStyle": {"width": 2.5, "color": "#2a78d6"}, "itemStyle": {"color": "#2a78d6"},
                           **marks}]
                if firsts:
                    series.append({"type": "line", "name": "_first", "data": [], "silent": True, "markLine": {
                        "symbol": "none", "silent": True, "animation": False,
                        "lineStyle": {"color": "#B8B6A8", "type": [3, 3], "width": 1},
                        "label": {"position": "start", "distance": 4, "align": "right", "color": "#6B6A5E",
                                  "fontSize": 11, "backgroundColor": "rgba(255,255,255,.94)", "padding": [2, 6],
                                  "borderRadius": 4}, "data": firsts}})  # trục đảo: "start" là đỉnh biểu đồ
                x_axis = ({"type": "time", "minInterval": 86400000,
                           "axisLabel": {"color": "#6B6A5E", "fontSize": 11, "hideOverlap": True,
                                         "formatter": "{dd}/{MM}"}}
                          if time_axis else
                          {"type": "category", "data": [x["label"] for x in h], "boundaryGap": False,
                           "axisLabel": {"color": "#6B6A5E", "fontSize": 11, "hideOverlap": True}})
                x_axis.update({"axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                               "splitLine": {"show": True, "lineStyle": {"color": "#F4F3EE"}}})
                ranked_js = "[" + ",".join(str(r) for r in ranked) + "]"
                checked_js = "[" + ",".join(str(x["checked"]) for x in h) + "]"
                chart = ui.echart({
                    "animation": False,
                    "grid": {"left": 40, "right": 18, "top": 36, "bottom": 26},
                    "tooltip": {"trigger": "axis", "confine": True, ":formatter": (
                        "ps => { const p = ps.find(q => q.seriesName[0] !== '_'); if (!p) return ''; "
                        "const v = Array.isArray(p.value) ? p.value[1] : p.value; "
                        "return (Array.isArray(p.value) ? new Date(p.value[0]).toLocaleDateString('vi-VN') "
                        ": p.axisValueLabel) + '<br/>' + p.marker + 'Vị trí trung bình: <b>' + "
                        "(v == null ? '–' : String(v).replace('.', ',')) + '</b><br/><span style=\"color:#6B6A5E\">"
                        f"Tính trên ' + {ranked_js}[p.dataIndex] + ' từ khóa có hạng · đã check ' + "
                        f"{checked_js}[p.dataIndex] + ' / {total}</span>'; }}")},
                    "xAxis": x_axis,
                    "yAxis": {"type": "value", "inverse": True, "min": 1, "max": top_y, "splitNumber": 5,
                              "name": "Vị trí (1 = đầu trang)", "nameLocation": "start", "nameGap": 10,
                              "nameTextStyle": {"color": "#6B6A5E", "fontSize": 11, "align": "left"},
                              "splitLine": {"lineStyle": {"color": "#F0EEE6"}},
                              "axisLabel": {"color": "#6B6A5E", "fontSize": 11}},
                    "series": series}).classes("w-full").style("height: 240px")
                chart.props["role"] = "img"
                last_v = next((v for _, v in reversed(pts) if v is not None), None)
                chart.props["aria-label"] = (f"Biểu đồ vị trí trung bình, {len(h)} {unit[period]} từ {h[0]['label']} "
                                             f"đến {h[-1]['label']}. Hiện tại: {last_v}.")

            @ui.refreshable
            def line():
                period = state["period"]
                h = load(period)
                if not h:
                    ui.label("Chưa có lần check nào.").classes("text-sm muted q-py-md")
                    return
                view = state["view"]
                ui.label(f"{h[0]['label']} – {h[-1]['label']} · {len(h)} {unit[period]}"
                         if len(h) > 1 else f"{h[0]['label']} · 1 {unit[period]}").classes("sr-cmp-note").style(
                    "margin-top: 2px")
                tiers = (3, 5, 10)
                now = _tops(h[-1])
                if view == "table" or len(h) < 2:
                    body = ""
                    for name, need in goals:  # mục tiêu cam kết: một dòng, trạng thái ngay cạnh số
                        cells = ""
                        for n in tiers:
                            if n in need:
                                ok = now[n] >= need[n]
                                st = ("<span class='sr-goal-s up' title='Đang đạt'>✓ đạt</span>" if ok else
                                      f"<span class='sr-goal-s down'>thiếu {need[n] - now[n]}</span>")
                                cells += (f"<td title='Cần ít nhất {need[n]} từ khóa Top {n}'>"
                                          f"<span class='sr-goal-v'>≥ {need[n]}</span>{st}</td>")
                            else:
                                cells += "<td class='muted'>–</td>"
                        body += (f"<tr class='sr-goal'><th scope='row'><i class='q-icon material-icons sr-goal-ico' aria-hidden='true'>flag</i>{name}"
                                 f"</th>{cells}</tr>")
                    rows_ = list(reversed(h))
                    for i, x in enumerate(rows_):
                        cur = i == 0
                        tag = "<span class='sr-now-tag'>Hiện tại</span>" if cur else ""
                        cells = ""
                        for n in tiers:
                            v = _tops(x)[n]
                            chip = ""
                            if cur and len(rows_) > 1:  # dòng hiện tại: tăng / giảm so với lần trước
                                d = v - _tops(rows_[1])[n]
                                chip = (f"<span class='sr-delta {'up' if d > 0 else 'down'}' title='So với "
                                        f"{rows_[1]['label']}'>{'▲' if d > 0 else '▼'} {abs(d)}</span>") if d else ""
                            cells += f"<td><b>{v}</b><span class='sr-of'>/{total}</span>{chip}</td>"
                        body += f"<tr class='{'sr-now' if cur else ''}'><th scope='row'>{x['label']}{tag}</th>{cells}</tr>"
                    ui.html(f"<table class='sr-snap'><caption class='sr-only'>Số từ khóa Top 3 / 5 / 10 theo "
                            f"{unit[period]}{', kèm mục tiêu cam kết' if goals else ''}</caption>"
                            "<colgroup><col style='width:31%'><col style='width:23%'><col style='width:23%'><col style='width:23%'>"
                            "</colgroup>"
                            f"<thead><tr><th scope='col'>{unit[period].capitalize()}</th><th scope='col'>Top 3</th>"
                            "<th scope='col'>Top 5</th><th scope='col'>Top 10</th></tr></thead>"
                            f"<tbody>{body}</tbody></table>").classes("w-full")
                    return
                time_axis = period == "check"
                marks = event_marks(h, evs or [], time=time_axis)
                goal_now = goals[0][1] if goals else {}
                metric = state.setdefault("metric", "avg")
                with ui.row().classes("items-center gap-2 q-mt-xs"):
                    mt = ui.toggle({"avg": "Vị trí trung bình", "top": "Số từ khóa Top 3 / 5 / 10"}, value=metric,
                                   on_change=lambda e: (state.update(metric=e.value), line.refresh())).props(
                        "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"
                    ).classes("sr-seg")
                    mt.props["aria-label"] = "Chỉ số trên biểu đồ"
                series = []
                if metric == "avg":
                    avg_chart(h, time_axis, marks, period)
                    return
                for i, (n, dash, sym) in enumerate(((10, "dotted", "triangle"), (5, "dashed", "rect"),
                                                    (3, "solid", "circle"))):
                    vals = [_tops(x)[n] for x in h]
                    s_ = {"type": "line", "name": f"Top {n}", "symbol": sym, "symbolSize": 7, "smooth": False,
                          "data": [[x["date"], v] for x, v in zip(h, vals)] if time_axis else vals,
                          "lineStyle": {"width": 2.25, "type": dash, "color": TIER_COLORS[n]},
                          "itemStyle": {"color": TIER_COLORS[n]}, **(marks if i == 0 else {})}
                    series.append(s_)
                if goal_now:  # mục tiêu cam kết: gộp các Top cùng một mức thành một đường, nhãn có nền
                    by_val: dict[int, list[int]] = {}
                    for n_, v_ in sorted(goal_now.items()):
                        by_val.setdefault(v_, []).append(n_)
                    series.append({"type": "line", "name": "_goals", "data": [], "silent": True, "markLine": {
                        "symbol": "none", "silent": True, "animation": False, "data": [{
                            "yAxis": v_, "lineStyle": {"color": "#6B6A5E", "type": [6, 4], "width": 1.25},
                            "label": {"formatter": f"Cam kết {', '.join(f'Top {n_}' for n_ in ns)}: {v_}",
                                      "position": "insideStartTop", "color": "#3A3A32", "fontSize": 11,
                                      "backgroundColor": "rgba(255,255,255,.94)", "padding": [2, 6],
                                      "borderRadius": 4, "borderColor": "#E4E2D9", "borderWidth": 1}}
                            for v_, ns in by_val.items()]}})
                x_axis = ({"type": "time", "minInterval": 86400000,
                           "axisLabel": {"color": "#6B6A5E", "fontSize": 11, "hideOverlap": True,
                                         "formatter": "{dd}/{MM}"}}
                          if time_axis else
                          {"type": "category", "data": [x["label"] for x in h], "boundaryGap": False,
                           "axisLabel": {"color": "#6B6A5E", "fontSize": 11, "hideOverlap": True}})
                x_axis.update({"axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": "#E7E5DC"}}})
                summary = "; ".join(f"Top {n}: {now[n]}/{total}" for n in tiers)
                # Điểm có nhiều từ khóa được check lần đầu: số Top N tăng vì có thêm từ khóa có số, không phải vì lên
                # hạng → đánh dấu bằng vạch dọc có nhãn để không đọc nhầm là tăng trưởng
                firsts = []
                for i in range(1, len(h)):
                    added = h[i]["checked"] - h[i - 1]["checked"]
                    if added > 0:
                        firsts.append({"xAxis": h[i]["date"] if time_axis else h[i]["label"],
                                       "label": {"formatter": f"+{added} từ khóa check lần đầu"}})
                if firsts:
                    series.append({"type": "line", "name": "_first", "data": [], "silent": True, "markLine": {
                        "symbol": "none", "silent": True, "animation": False,
                        "lineStyle": {"color": "#B8B6A8", "type": [3, 3], "width": 1},
                        "label": {"position": "end", "distance": 4, "align": "right", "color": "#6B6A5E", "fontSize": 11,
                                  "backgroundColor": "rgba(255,255,255,.94)", "padding": [2, 6], "borderRadius": 4},
                        "data": firsts}})
                checked_js = "[" + ",".join(str(x["checked"]) for x in h) + "]"
                chart = ui.echart({
                    "animation": False,
                    "grid": {"left": 34, "right": 18, "top": 44, "bottom": 26},
                    "legend": {"top": 0, "left": 0, "itemWidth": 22, "itemHeight": 8,
                               "data": ["Top 3", "Top 5", "Top 10"], "textStyle": {"fontSize": 12, "color": "#4A4A40"}},
                    "tooltip": {"trigger": "axis", "confine": True, ":formatter": (
                        "ps => (Array.isArray(ps[0].value) ? new Date(ps[0].value[0]).toLocaleDateString('vi-VN') "
                        ": ps[0].axisValueLabel) + '<br/>' + ps.filter(p => p.seriesName[0] !== '_').map(p => "
                        "p.marker + p.seriesName + ': <b>' + (Array.isArray(p.value) ? p.value[1] : p.value) + "
                        f"'</b> / {total} từ khóa').join('<br/>') + '<br/><span style=\"color:#6B6A5E\">Đã check: ' + "
                        f"{checked_js}[ps[0].dataIndex] + ' / {total} từ khóa</span>'")},
                    "xAxis": x_axis,
                    "yAxis": {"type": "value", "min": 0, "max": max(total, 1), "minInterval": 1, "splitNumber": 4,
                              "name": f"Số từ khóa nằm trong Top (trên {total}) · đường đi lên = tốt",
                              "nameLocation": "end", "nameGap": 10,
                              "nameTextStyle": {"color": "#6B6A5E", "fontSize": 11, "align": "left"},
                              "splitLine": {"lineStyle": {"color": "#F0EEE6"}},
                              "axisLabel": {"color": "#6B6A5E", "fontSize": 11}},
                    "series": series}).classes("w-full").style("height: 240px")
                chart.props["role"] = "img"
                chart.props["aria-label"] = (f"Biểu đồ xu hướng thứ hạng, {len(h)} {unit[period]} từ "
                                             f"{h[0]['label']} đến {h[-1]['label']}. Hiện tại: {summary}."
                                             + (f" {goals[0][0]}: " + ", ".join(f"Top {n} cần {v}"
                                                                                 for n, v in goal_now.items())
                                                if goals else ""))
            line()

        # ---- Hàng 2: Phân bổ thứ hạng (vòng tròn, nhóm loại trừ nhau) ----
        with cell("cov", "Phân bổ thứ hạng", (
                "Mỗi từ khóa của bộ nằm đúng một nhóm theo lần check gần nhất; cộng các nhóm = tổng số từ khóa.",
                "Phần xanh càng lớn thì bộ càng phủ trang đầu Google. Rê chuột vào lát hoặc chú thích để xem số.",
                "Nhóm cuối ghi theo độ sâu check thật (ví dụ chỉ check top 20 thì ghi “Ngoài top 20”, không ghi ngoài "
                "top 30). Từ khóa mới thêm chưa check đứng riêng.")):
            if not last:
                ui.label("Chưa có lần check nào").classes("text-sm muted q-mt-sm")
            else:
                groups = [(name, v, color) for name, v, color in (
                    ("Top 1–3", last["top3"], "#1E7C31"), ("Top 4–5", last["top5"], "#5FA33B"),
                    ("Top 6–10", last["top10"], "#9BB823"), (deep_label, last["top30"], "#D9A441"),
                    (out_label, last["out"], "#B9B6A8"), ("Chưa check", last.get("unchecked", 0), "#E4E2D9"))
                    if v]
                n_all = sum(v for _, v, _ in groups) or 1
                ch = T.donut(ui, [(name, v) for name, v, _ in groups], [c for _, _, c in groups], "từ khóa", 220)
                if ch:
                    ch.props["role"] = "img"
                    ch.props["aria-label"] = "Phân bổ thứ hạng: " + "; ".join(
                        f"{name} {v} từ khóa ({v / n_all * 100:.0f}%)" for name, v, _ in groups)


        # ---- Hàng 3: Biến động đáng chú ý ----
        if aio is not None:
            aio_cell(aio)
        moved = [m for m in (_kw_move(k) for k in kws) if m and (m["d"] or m["lost"] or m["gained"])]
        moved.sort(key=lambda m: (not m["lost"], m["d"] >= 0, -abs(m["d"])))
        n_up, n_down = sum(1 for m in moved if m["d"] > 0), sum(1 for m in moved if m["d"] < 0)
        n_lost = sum(1 for m in moved if m["lost"])
        with cell("mov", "Biến động đáng chú ý", (
                "Từ khóa đổi hạng so với lần check trước của chính nó. Xếp: mất Top mục tiêu trước, rồi rớt hạng (rớt "
                "khỏi độ sâu check trước), rồi lên hạng.",
                "Đây là danh sách cần xem trước: bấm một dòng để mở lịch sử vị trí của từ khóa.",
                "Khi một phía nằm ngoài độ sâu check, tool ghi “rớt khỏi top N / vào top N” thay vì một con số không "
                "chắc chắn.")) as mv:
            head = mv.default_slot.children[0]
            with head:
                ui.space()
                if moved:
                    ui.html(f"<span class='sr-delta down'>▼ {n_down} rớt</span> "
                            f"<span class='sr-delta up'>▲ {n_up} lên</span>"
                            + (f" <span class='sr-delta down'>{n_lost} mất mục tiêu</span>" if n_lost else ""))
            if not moved:
                ui.label("Không có từ khóa nào đổi hạng so với lần check trước." if prev
                         else "Chưa có lần check trước để so sánh.").classes("text-sm muted q-mt-sm")
            else:
                with ui.element("div").classes("sr-mv").props('role="table" aria-label="Biến động đáng chú ý"'):
                    with ui.element("div").classes("sr-mv-row sr-mv-h").props('role="row"'):
                        for h_ in ("Từ khóa", "Trước", "Nay", "Thay đổi", "Mục tiêu", "URL đang xếp hạng"):
                            ui.label(h_).props('role="columnheader"')
                    for m in moved[:6]:
                        k = m["k"]
                        row = ui.element("button").classes("sr-mv-row").props(
                            f'type="button" role="row" aria-label="Xem lịch sử vị trí: {k["keyword"]}"')
                        row.on("click", lambda _, k=k: on_open(k))
                        tone = "up" if m["d"] > 0 else ("down" if m["d"] < 0 else "flat")
                        with row:
                            ui.label(k["keyword"]).classes("ellipsis sr-mv-kw").props('role="cell"')
                            ui.label(m["before"]).classes("sr-mv-num").props('role="cell"')
                            ui.label(m["now"]).classes("sr-mv-num sr-mv-now").props('role="cell"')
                            with ui.element("span").classes(f"sr-mv-chg {tone}").props('role="cell"'):
                                ui.label(("▲ " if m["d"] > 0 else "▼ " if m["d"] < 0 else "") + m["text"])
                            with ui.element("span").props('role="cell"').classes("ellipsis"):
                                t = k.get("top_target")
                                if not t:
                                    ui.label("–").classes("muted")
                                elif m["lost"]:
                                    ui.label(f"Top {t} · mất mục tiêu").classes("sr-mv-tag down")
                                elif m["gained"]:
                                    ui.label(f"Top {t} · vừa đạt").classes("sr-mv-tag up")
                                else:
                                    ok = k["rank"] is not None and k["rank"] <= t
                                    ui.label(f"Top {t} · {'đạt' if ok else 'chưa đạt'}").classes("muted")
                            ui.label(short_url(k["ranking_url"]) or "–").classes("ellipsis muted").props(
                                f'role="cell" title="{k["ranking_url"] or ""}"')
                if on_filter and len(moved) > 6:
                    with ui.row().classes("items-center gap-2 q-mt-xs"):
                        ui.label(f"+{len(moved) - 6} từ khóa khác.").classes("sr-cmp-note").style("margin-top:0")
                        if n_down:
                            ui.button("Xem tất cả từ khóa rớt hạng", on_click=lambda: on_filter("down")).props(
                                "flat dense no-caps size=sm color=primary")
                        if n_up:
                            ui.button("Xem tất cả từ khóa lên hạng", on_click=lambda: on_filter("up")).props(
                                "flat dense no-caps size=sm color=primary")


def build_rank_page(ui, cfg, connect, user: str, on_budget_change=None, set_id: int | None = None) -> None:
    """Tiêu đề + tab bộ từ khóa theo chuẩn truy cập (role tablist / tab / tabpanel, aria-selected, aria-controls,
    aria-labelledby; chỉ tab đang chọn có tabindex 0; phím ← → Home End chuyển tab) + một vùng nội dung dùng chung:
    đổi bộ thì dựng lại vùng đó ngay trong trang, không tải lại (địa chỉ ?bo= cập nhật để chép link / tải lại vẫn
    đúng bộ). set_id: bộ mở đầu; không có / không còn thì bộ đầu tiên."""
    from .access import can_edit
    from . import ui_theme as T
    site = cfg.site_url
    with connect() as c:
        all_sets = R.sets(c, site)
        if not all_sets:
            R.default_set(c, site, str(user))
            all_sets = R.sets(c, site)
    ids = [0, -1] + [x["id"] for x in all_sets]  # 0 = Tổng quan (mặc định), -1 = Đối thủ, rồi từng bộ
    state = {"sid": set_id if set_id in ids else 0, "hooks": {}}

    right = T.page_header(ui, "leaderboard", "Từ khóa & Thứ hạng",
                          "Vị trí thật trên Google của từng bộ từ khóa: đạt mục tiêu chưa, từ khóa nào vừa lên / xuống.")
    with right:
        if cfg.rank.paused:
            T.status_chip(ui, "Đang tạm ngưng check rank", "amber", "pause_circle")

    tabs = {}
    with ui.row().classes("w-full items-end no-wrap gap-2"):
        with ui.element("div").classes("sr-a11y-tabs col") as tablist:
            tablist.props["role"] = "tablist"
            tablist.props["aria-label"] = "Bộ từ khóa"
            t = ui.element("button").classes("sr-a11y-tab")
            t.props.update({"role": "tab", "id": "rk-tab-0", "aria-controls": "rk-panel", "type": "button"})
            with t:
                ui.icon("dashboard", size="16px")
                ui.label("Tổng quan")
            t.on("click", lambda _: select(0))
            t.on("keydown", lambda e: on_key(0, e.args.get("key")), ["key"])
            tabs[0] = t
            t = ui.element("button").classes("sr-a11y-tab")
            t.props.update({"role": "tab", "id": "rk-tab--1", "aria-controls": "rk-panel", "type": "button"})
            with t:
                ui.icon("groups", size="16px")
                ui.label("Đối thủ")
            t.on("click", lambda _: select(-1))
            t.on("keydown", lambda e: on_key(-1, e.args.get("key")), ["key"])
            tabs[-1] = t
            for x in all_sets:
                t = ui.element("button").classes("sr-a11y-tab")
                t.props.update({"role": "tab", "id": f"rk-tab-{x['id']}", "aria-controls": "rk-panel",
                                "type": "button"})
                with t:
                    if x["draft"] or x["paused"] or x["kind"] == "kpi":
                        ui.icon("edit_note" if x["draft"] else "pause_circle" if x["paused"] else "verified",
                                size="16px")
                    ui.label(f"{x['name']} · {x['count']}")
                t.on("click", lambda _, i=x["id"]: select(i))
                t.on("keydown", lambda e, i=x["id"]: on_key(i, e.args.get("key")), ["key"])
                tabs[x["id"]] = t
        if can_edit(user):
            icon_btn(ui, "add", "Tạo bộ từ khóa mới", lambda: new_set())
    panel = ui.element("div").classes("w-full sr-a11y-panel")
    panel.props.update({"role": "tabpanel", "id": "rk-panel", "tabindex": "0"})

    def new_set() -> None:
        if state["sid"] <= 0:  # hộp thoại tạo bộ nằm trong vùng của một bộ: mở bộ đầu rồi mở hộp thoại
            select(ids[2])
        state["hooks"].get("new_set", lambda: None)()

    def open_set(i: int | None, filt: str | None = None) -> None:
        """Mở một bộ (từ thẻ ở Tổng quan), lọc sẵn bảng; filt="new": mở hộp thoại tạo bộ."""
        if filt == "new":
            new_set()
            return
        select(i)
        if filt == "lock":
            state["hooks"].get("lock", lambda: None)()
        elif filt:
            state["hooks"].get("filter", lambda _: None)(filt)

    def panel_for(i: int) -> None:
        if i == 0:
            from .web_rank_dash import build_dashboard
            build_dashboard(ui, cfg, connect, user, lambda j, f=None: open_set(j, f), new_set)
        elif i == -1:
            from .web_rivals import build_rivals_panel
            build_rivals_panel(ui, cfg, connect, user, open_set)
        else:
            _set_panel(ui, cfg, connect, user, on_budget_change, i, state["hooks"])

    def mark() -> None:
        for i, t in tabs.items():
            on = i == state["sid"]
            t.props["aria-selected"] = "true" if on else "false"
            t.props["tabindex"] = "0" if on else "-1"
            t.classes(add="active") if on else t.classes(remove="active")
            t.update()
        panel.props["aria-labelledby"] = f"rk-tab-{state['sid']}"
        panel.update()

    def select(i: int, focus: bool = False) -> None:
        if i == state["sid"] and panel.default_slot.children:
            return
        state["sid"] = i
        mark()
        panel.clear()
        with panel:
            panel_for(i)
        with tablist:  # gọi từ nút trong vùng vừa xóa (bảng các bộ): chạy JS trong ngữ cảnh còn sống
            q = "" if i == 0 else ("?bo=doi-thu" if i == -1 else f"?bo={i}")
            ui.run_javascript(f"history.replaceState(null, '', '/rank{q}')"
                              + (f";document.getElementById('rk-tab-{i}').focus()" if focus else ""))

    def on_key(i: int, key: str | None) -> None:
        pos = ids.index(i)
        nxt = {"ArrowRight": (pos + 1) % len(ids), "ArrowLeft": (pos - 1) % len(ids), "Home": 0,
               "End": len(ids) - 1}.get(key or "")
        if nxt is not None:
            select(ids[nxt], focus=True)

    mark()
    with panel:
        panel_for(state["sid"])


def _project_panel(ui, cfg, connect, user, select, open_set) -> None:
    """Tổng quan dự án: một dòng tóm tắt + mỗi bộ một thẻ gọn (bấm để mở bộ). Biểu đồ chi tiết nằm trong tab từng bộ,
    nên thêm bao nhiêu bộ thì chỉ thêm thẻ."""
    from . import rank_overview as RO
    from .access import can_edit
    site = cfg.site_url
    with connect() as c:
        end = K.latest_date(c, site)
        kws = RO.active_keywords(c, site, end)
        cards = RO.set_cards(c, cfg, end)
    ranked = [k["rank"] for k in kws if k["date"] and k["rank"] is not None]
    t10 = sum(r <= 10 for r in ranked)
    up, down = RO._moves(kws)
    nxt = min(((c_["next"], c_["time"]) for c_ in cards if c_["next"]), default=None)

    # ---- dòng tóm tắt dự án ----
    with ui.element("div").classes("sr-proj-strip w-full"):
        with ui.element("span"):
            ui.html(f"<b>{len(kws)}</b> từ khóa đang chạy · {len(cards)} bộ")
        with ui.element("span"):
            ui.html(f"Top 10 <b>{t10}/{len(kws)}</b> · {t10 / len(kws) * 100:.0f}%" if kws else "Top 10 –")
        if up:
            ui.label(f"↗ {up} lên hạng").classes("sr-mini-move up")
        if down:
            ui.label(f"↘ {down} rớt hạng").classes("sr-mini-move down")
        if nxt:
            with ui.element("span").classes("muted"):
                ui.label(f"Check tới {_vn(nxt[0].isoformat())[:5]} lúc {nxt[1] or '07:00'}")

    # ---- mỗi bộ một thẻ ----
    with ui.element("div").classes("sr-set-grid w-full"):
        for cd in cards:
            muted = cd["draft"] or cd["paused"]
            card = ui.element("div").classes("sr-set-card" + (" muted" if muted else ""))
            card.props.update({"role": "button", "tabindex": "0", "aria-label": f"Mở bộ {cd['name']}"})
            card.on("click", lambda _, i=cd["id"]: select(i))
            card.on("keydown.enter", lambda _, i=cd["id"]: select(i))
            with card:
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    ui.label(cd["name"]).classes("sr-set-card-name ellipsis")
                    tone = "draft" if cd["draft"] else ("paused" if cd["paused"] else
                                                        ("kpi" if cd["kind"] == "Cam kết" else "track"))
                    ui.label("Nháp" if cd["draft"] else ("Tạm dừng" if cd["paused"] else cd["kind"])).classes(
                        f"sr-set-tag {tone}")
                    ui.space()
                    ui.icon("chevron_right", size="20px").classes("muted").props('aria-hidden="true"')
                with ui.row().classes("w-full items-baseline no-wrap gap-2 q-mt-sm"):
                    ui.label("–" if cd["top10_now"] is None else str(cd["top10_now"])).classes("sr-set-card-num")
                    ui.label(f"/ {cd['active']} vào Top 10"
                             + (f" · {cd['top10_now'] / cd['active'] * 100:.0f}%" if cd["top10_now"] is not None
                                and cd["active"] else "")).classes("sr-bx-of")
                    ui.space()
                    if cd["delta"]:
                        lb = ui.label(("▲ " if cd["delta"] > 0 else "▼ ") + str(abs(cd["delta"]))).classes(
                            "sr-delta " + ("up" if cd["delta"] > 0 else "down"))
                        lb.tooltip(f"So với lần check {_vn(cd['prev_date'])[:5]}")
                with ui.row().classes("w-full gap-1 q-mt-xs"):
                    if cd["top3_now"] is not None:
                        ui.label(f"Top 3 · {cd['top3_now']}").classes("sr-chip-soft")
                    if cd["out_n"]:
                        ui.label(f"{cd['out_label']} · {cd['out_n']}").classes("sr-chip-soft")
                    if cd["unchecked_n"]:
                        ui.label(f"Chưa check · {cd['unchecked_n']}").classes("sr-chip-soft")
                a = cd["aio"]
                with ui.element("div").classes("sr-aio-line"):
                    ui.icon("auto_awesome", size="16px").style("color:#6250d6").props('aria-hidden="true"')
                    if a["checked"]:
                        ui.html(f"AI Overview · <b>{a['aio']}/{a['checked']}</b> từ khóa có · <b>{a['cited']}</b> được trích")
                    else:
                        ui.label("Chưa có số AI Overview").classes("muted")
                at = cd["attention"]
                if at:
                    note = ui.element("button").classes(f"sr-attn {at['tone']} w-full").props('type="button"')
                    with note:
                        ui.label(at["text"]).classes("col")
                        if at["filter"] or cd["draft"]:
                            ui.icon("arrow_forward", size="16px").props('aria-hidden="true"')
                    note.on("click.stop", lambda _, i=cd["id"], f=at["filter"]: open_set(i, f))
                bits = [f"Check {_vn(cd['last'])[:5]}" if cd["last"] else "Chưa check lần nào"]
                if cd["next"]:
                    bits.append(f"tới {_vn(cd['next'].isoformat())[:5]} {cd['time'] or ''}".strip())
                if cd["cost"]:
                    bits.append(f"≈ {R.usd(cd['cost'])} USD/tháng")
                ui.label(" · ".join(bits)).classes("sr-set-card-foot")
        if can_edit(user):
            add = ui.element("button").classes("sr-set-card add").props('type="button"')
            add.on("click", lambda: open_set(None, "new"))
            with add:
                ui.icon("add", size="20px")
                ui.label("Tạo bộ mới")


def _competitors_block(ui, comp: dict, sets_: list[dict], select, manage_link: bool = False,
                       header_extra=None) -> None:
    """Đối thủ trên bộ từ khóa: donut thị phần hiển thị + bảng số (không dùng thanh so sánh); cảnh báo khi mới có ít
    từ khóa có dữ liệu; danh sách từ khóa đối thủ vừa vượt mình."""
    from . import rank_overview as RO
    from . import ui_theme as T
    rows_c = comp["rows"]
    rivals = [r for r in rows_c if not r["brand"]["own"]]
    with ui.element("div").classes("sr-card q-pa-md w-full q-mt-md"):
        with ui.row().classes("w-full items-center gap-2 q-mb-sm sr-comp-head"):
            with ui.element("span").classes("sr-bx-icon").style("background:#EEF2FB"):
                ui.icon("groups", size="16px").style("color:#2a78d6").props('aria-hidden="true"')
            ui.label("Đối thủ trên bộ từ khóa").classes("sr-bx-title")
            T.info_icon(ui, "Đối thủ", (
                "Độ hiển thị: tổng tỷ lệ nhấp ước tính theo vị trí (hạng 1 ≈ 28%, hạng 2 ≈ 15%, hạng 3 ≈ 10%…) trên các "
                "từ khóa, so với mức tối đa nếu đứng hạng 1 ở tất cả. Thị phần: phần của từng thương hiệu trong tổng "
                "độ hiển thị.",
                "Lấy từ lần check gần nhất của từng từ khóa đang chạy, trong độ sâu đã check. Không tốn thêm phí.",
                "Xếp trên dự án: đối thủ đứng trên website dự án, hoặc có mặt khi website dự án không có.",
                "▲▼ ở hạng và ở Top 3 / 5 / 10: so với lần check trước, trên các từ khóa có cả hai lần check."))
            if manage_link or header_extra:
                ui.space()
            if header_extra:  # ví dụ nút "Tính trên: Mọi bộ / từng bộ" của tab Đối thủ
                header_extra()
            if manage_link:
                ui.link("Quản lý đối thủ", "/rank?bo=doi-thu").classes("text-sm")
        if not rivals:
            T.empty_state(ui, "group_add", "Chưa có đối thủ nào", "Thêm tối đa 10 đối thủ ở phần bên trên.")
            return
        n, total = comp["keywords"], comp["total"]
        thin = not total or n / total < 0.3
        if thin:
            nxt = min((r["next"] for r in sets_ if r["next"]), default=None)
            with ui.element("div").classes("sr-thin-note w-full"):
                ui.icon("hourglass_top", size="18px").props('aria-hidden="true"')
                ui.label(f"Mới có kết quả Google của {n}/{total} từ khóa: số dưới đây chưa đại diện cho cả bộ"
                         + (f", sẽ đủ dần sau lần check {_vn(nxt.isoformat())[:5]}" if nxt else "") + ".")
        vis_sum = sum(r["vis"] for r in rows_c)
        own_b = comp.get("own") or {}
        own_name = own_b.get("name", "dự án")
        with ui.element("div").classes("sr-comp-grid w-full" + (" thin" if thin else "")):
            # ---- donut thị phần hiển thị ----
            with ui.element("div").classes("sr-comp-donut"):
                slices, logos, other = [], [], 0.0
                for r in rows_c:
                    b = r["brand"]
                    if not r["vis"]:
                        continue
                    if b["own"] or b["charted"]:
                        pct = round(r["vis"] / vis_sum * 100, 1)
                        slices.append({"name": b["name"], "value": pct, "itemStyle": {"color": b["color"]}})
                        logos.append(b.get("logo") or "")
                    else:
                        other += r["vis"]
                if other:
                    slices.append({"name": "Đối thủ khác", "value": round(other / vis_sum * 100, 1),
                                   "itemStyle": {"color": "#A9A79B"}})
                    logos.append("")
                own = next((r for r in rows_c if r["brand"]["own"]), None)
                share = (own["vis"] / vis_sum * 100) if own and vis_sum else 0
                with ui.element("div").classes("sr-comp-chartbox"):
                    ui.echart({
                        "tooltip": {"trigger": "item", "formatter": "{b}: {c}%"},
                        "series": [{"type": "pie", "radius": ["50%", "74%"], "center": ["50%", "50%"],
                                    "label": {"show": False}, "labelLine": {"show": False},
                                    "itemStyle": {"borderColor": "#fff", "borderWidth": 2},
                                    "emphasis": {"scale": True, "scaleSize": 5}, "data": slices}],
                        "graphic": [{"type": "text", "left": "center", "top": "41%",
                                     "style": {"text": f"{share:.0f}%", "fontSize": 28, "fontWeight": 700,
                                               "fill": "#1F221E", "textAlign": "center"}},
                                    {"type": "text", "left": "center", "top": "54%",
                                     "style": {"text": f"thị phần {own_name}", "fontSize": 12, "fill": "#6B6A5E",
                                               "textAlign": "center", "width": 130, "overflow": "truncate"}}]}
                    ).classes("sr-comp-chart")
                    # Logo đặt bằng HTML ở giữa cung của từng phần (ECharts không chắc vẽ được ảnh trong nhãn):
                    # vòng ngoài 74% của bán kính 155px, chip logo cách mép vòng 20px. Phần quá nhỏ (< 12°) bỏ logo
                    # để các chip không đè nhau; bảng bên cạnh vẫn có logo.
                    tot = sum(x["value"] for x in slices) or 1
                    cum = 0.0
                    for x, logo in zip(slices, logos):
                        deg = x["value"] / tot * 360
                        mid = math.radians(90 - (cum + deg / 2))
                        cum += deg
                        if not logo or deg < 12:
                            continue
                        cx, cy = 155 + 135 * math.cos(mid), 155 - 135 * math.sin(mid)
                        with ui.element("span").classes("sr-donut-logo").style(
                                f"left:{cx - 14:.0f}px;top:{cy - 14:.0f}px"):
                            ui.html(f'<img src="{logo}" alt="">')
                        ui.tooltip(f"{x['name']}: {x['value']:g}%")
            # ---- bảng số ----
            with ui.element("div").classes("sr-comp-table"):
                with ui.element("div").classes("sr-comp-row head"):
                    for h in ("#", "Thương hiệu", "Hiển thị", "Có mặt", "Top 3", "Top 5", "Top 10", "AI trích dẫn"):
                        ui.label(h)

                def num_move(value, d, tip_word: str):
                    """Số và mũi tên ở hai ô cố định: số các dòng luôn thẳng hàng."""
                    with ui.element("div").classes("sr-nm"):
                        ui.label(str(value)).classes("v")
                        if d:
                            ui.label(("▲" if d > 0 else "▼") + str(abs(d))).classes(
                                "m " + ("up" if d > 0 else "down")).tooltip(tip_word.format(abs(d)))
                        else:
                            ui.label("").classes("m")
                def frac(v, of):
                    return ui.html(f"<b>{v}</b><span class='of'>/{of}</span>" if of else "–").classes("num")
                for r in rows_c:
                    b = r["brand"]
                    color = b["color"] if b["own"] or b["charted"] else "#A9A79B"
                    with ui.element("div").classes("sr-comp-row" + (" own" if b["own"] else "")):
                        mv = r.get("move")
                        with ui.element("div").classes("sr-nm place"):
                            tier = "g" if r["place"] <= 3 else ("s" if r["place"] <= 5 else "")
                            with ui.element("span").classes(f"v sr-place-badge p{r['place']} {tier}"):
                                if r["place"] <= 3:  # hạng 1 cúp, hạng 2 huy chương, hạng 3 huân chương
                                    ui.icon({1: "emoji_events", 2: "workspace_premium", 3: "military_tech"}[r["place"]],
                                            size="13px").props('aria-hidden="true"')
                                ui.label(str(r["place"]))
                            if mv:
                                ui.label(("▲" if mv > 0 else "▼") + str(abs(mv))).classes(
                                    "m " + ("up" if mv > 0 else "down")).tooltip(
                                    f"{'Lên' if mv > 0 else 'Xuống'} {abs(mv)} bậc so với lần check trước")
                            elif mv == 0:
                                ui.label("=").classes("m same").tooltip("Giữ nguyên hạng so với lần check trước")
                            else:
                                ui.label("").classes("m")
                        with ui.row().classes("items-center no-wrap gap-2 sr-comp-name"):
                            ui.element("i").classes("sr-brand-dot").style(f"background:{color}")
                            with ui.element("span").classes("sr-brand-logo sr-logo-sm"):
                                if b.get("logo"):
                                    ui.html(f'<img src="{b["logo"]}" alt="">')
                                else:
                                    ui.label((b["name"] or "?")[:1].upper())
                            ui.label(b["name"]).classes("ellipsis")
                        ui.label(f"{r['visibility'] * 100:.0f}%").classes("num strong")
                        frac(r["present"], n)
                        for t in (3, 5, 10):
                            d = (r.get("delta") or {}).get(t)
                            num_move(r[f"top{t}"], d, ("Tăng" if (d or 0) > 0 else "Giảm") + " {} từ khóa Top "
                                     + str(t) + " so với lần check trước")
                        with ui.element("div").classes("num"):
                            if comp.get("ai_n"):
                                with ui.element("span").classes("sr-ai-chip" + (" zero" if not r["ai_cited"] else "")):
                                    ui.icon("auto_awesome", size="14px").props('aria-hidden="true"')
                                    ui.html(f"<b>{r['ai_cited']}</b><span class='of'>/{comp['ai_n']}</span>")
                                ui.tooltip(f"Được AI Overview trích link ở {r['ai_cited']} trên {comp['ai_n']} từ khóa có "
                                           "AI Overview")
                            else:
                                ui.label("–").classes("muted")

        cmp_n = comp.get("compared") or 0
        ui.label(("▲▼ so với lần check trước, tính trên " + f"{cmp_n}/{n} từ khóa đã có ít nhất 2 lần check (từ khóa "
                  "mới check 1 lần chưa so được)") if cmp_n else
                 "▲▼ sẽ hiện từ lần check thứ hai của các từ khóa (hiện mỗi từ khóa mới có 1 lần check có kết quả "
                 "Google).").classes("text-xs muted q-mt-sm")
        # ---- vừa vượt mình ----
        fresh = RO.overtaken(comp)
        if fresh:
            with ui.element("div").classes("sr-overtake w-full"):
                ui.label(f"Đối thủ vừa vượt {own_name} · {len(fresh)} từ khóa").classes("sr-overtake-title")
                for x in fresh[:6]:
                    with ui.row().classes("w-full items-center no-wrap gap-2 sr-overtake-row") as row_:
                        ui.label(x["keyword"]).classes("font-medium ellipsis col")
                        ui.label(f"{x['brand']} hạng {x['rank']}").classes("text-sm")
                        ui.label(f"{own_name} {x['mine'] if x['mine'] is not None else '>' + str(x['seen'])}").classes(
                            "text-sm muted")
                    row_.on("click", lambda _, x=x: select(x["set_id"]))
                    row_.tooltip("Mở bộ chứa từ khóa này")

    def list_dialog(r: dict, side: str) -> None:
        items = r[side]
        n_all = r["ahead_count"] if side == "ahead" else r["behind_count"]
        title = (f"{r['brand']['name']} đứng trên {own_name} · {n_all} từ khóa" if side == "ahead" else
                 f"{own_name} đứng trên {r['brand']['name']} · {n_all} từ khóa")
        with ui.dialog() as d, ui.card().style("min-width: 560px; max-width: 94vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label(title).classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=d.close).props("flat round dense")
            ui.table(columns=[
                {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
                {"name": "set", "label": "Bộ", "field": "set", "align": "left"},
                {"name": "rank", "label": "Đối thủ", "field": "rank", "align": "center", "sortable": True},
                {"name": "mine", "label": own_name, "field": "mine", "align": "center"},
            ], rows=[{**x, "mine": x["mine"] if x["mine"] is not None else f">{x['seen']}",
                      "rank": x["rank"] if x["rank"] is not None else f">{x['seen']}"} for x in items],
                row_key="keyword", pagination=15).classes("w-full").props("flat dense")
            if n_all > len(items):
                ui.label(f"Hiện {len(items)} từ khóa đầu.").classes("text-xs muted")
        d.open()


def _set_panel(ui, cfg, connect, user: str, on_budget_change, set_id: int, hooks: dict) -> None:
    """Nội dung một bộ (vùng tabpanel): thẻ bộ + nút, bento tổng quan, bảng từ khóa và các hộp thoại."""
    from . import access as A
    from .access import can_edit
    from . import kpi as KP
    from . import ui_theme as T
    site = cfg.site_url
    ed = can_edit(user)  # người chỉ xem: không thêm/bỏ keyword, không check (tốn tiền), không sửa bộ
    owner = A.is_admin(user) or getattr(user, "role", None) == A.LOCAL  # xóa lần check sai: chỉ Chủ tool
    with connect() as c:
        end = K.latest_date(c, site)
        all_sets = R.sets(c, site)
        if not all_sets:
            R.default_set(c, site, str(user))
            all_sets = R.sets(c, site)
        sheet = KP.sheet_id(c)
        linked = (R.kpi_set(c, site) or {}).get("id")
    cur = next((x for x in all_sets if x["id"] == set_id), all_sets[0])
    hooks["new_set"] = lambda: set_dialog(None)
    hooks["filter"] = lambda v: filt.set_value(v)  # thẻ ở Tổng quan mở bộ và lọc sẵn bảng
    hooks["lock"] = lambda: lock_dialog()
    sid = cur["id"]
    # Tool là nơi quản lý từ khóa: không bộ nào còn ghi / đọc từng dòng trên sheet (sheet là nơi xem, tool ghi đè).
    is_kpi = False
    commit_set = cur["kind"] == "kpi"
    draft = cur["draft"]
    sched = cur["schedule"]
    where = R.settings_for(cfg.rank, cur)

    def stat(icon: str, text: str, tip: str = "", tone: str = "") -> None:
        """Một mục trạng thái ở hàng 2 của thanh bộ: icon nhỏ + chữ; tooltip cho phần chi tiết."""
        with ui.element("span").classes("sr-st" + (f" {tone}" if tone else "")) as it:
            ui.icon(icon, size="16px").props('aria-hidden="true"')
            ui.label(text)
        if tip:
            it.tooltip(tip)

    def status_running() -> None:
        """Đang check: trạng thái nằm ở hàng tiến độ dưới thanh, hàng thông tin giữ số của lần check gần nhất."""
        tick()

    # ---- Thanh bộ đang mở: hàng 1 = môi trường check + thao tác, hàng 2 = trạng thái check ----
    # Chi tiết ít dùng (tên miền, chi phí ước tính, cài đặt theo dự án, xóa bộ) nằm trong tooltip / menu ···.
    when, _, depth_txt = R.describe_schedule(sched).partition("; ")
    engine = GOOGLE_NAMES.get(where.se_domain, where.se_domain)
    device = R.DEVICES.get(where.device, where.device)
    loc = R.locations().get(where.location_code, str(where.location_code))
    lang = R.LANGUAGES.get(where.language_code, where.language_code)
    with ui.element("div").classes("sr-card sr-setbar w-full"):
        with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['green'][0]}"):
            ui.icon("smartphone" if where.device == "mobile" else "computer", size="18px").style(
                f"color:{T.GREEN}").props('aria-hidden="true"')
        with ui.column().classes("gap-0 sr-setbar-info"):
            primary = ui.label(f"{engine} · {device}").classes("sr-setbar-title")
            primary.tooltip(f"Tìm trên {where.se_domain}, thiết bị {device.lower()}"
                            + ("; theo cài đặt chung của dự án" if not cur["settings"] else "; cài đặt riêng của bộ"))
            ui.label(f"{lang} · {loc} · {depth_txt.capitalize()}").classes("sr-setbar-sub")
            status_row = ui.element("div").classes("sr-setbar-status")
            status_row.props["aria-live"] = "polite"
        with ui.row().classes("items-center gap-1 no-wrap sr-setbar-actions"):
            if ed:
                icon_btn(ui, "add", "Thêm từ khóa vào bộ này", lambda: add_dialog.open(), kind="outline")
            if ed:
                resume_btn = ui.button("Tiếp tục", icon="play_arrow", on_click=lambda: resume_check()).props(
                    "outline no-caps color=primary").classes("sr-setbar-cta")
                resume_btn.set_visibility(False)
                check_btn = ui.button("Kiểm tra thứ hạng", icon="play_arrow", on_click=lambda: check_now()).props(
                    "unelevated no-caps color=primary").classes("sr-setbar-cta").tooltip(
                    "Check ngay các từ khóa đã chọn, hoặc cả bộ. Đổi trang vẫn check tiếp, xong sẽ báo.")
                check_btn.set_enabled(site not in _RUNNING and not cfg.rank.paused)
                if draft:  # Nháp: chưa check, chưa tốn tiền; bấm Chốt để bắt đầu chạy theo lịch
                    check_btn.set_visibility(False)
                    ui.button("Chốt bộ", icon="lock", on_click=lambda: lock_dialog()).props(
                        "unelevated no-caps color=primary").classes("sr-setbar-cta").tooltip(
                        "Chốt bộ: bắt đầu check theo lịch và tính tiền")
                if cfg.rank.paused:  # tạm ngưng: không gửi yêu cầu DataForSEO nào; quản trị bật lại ở màn Ngân sách
                    check_btn.disable()
                    check_btn.tooltip("Website đang tạm ngưng check rank. Quản trị bật lại ở màn Ngân sách check "
                                      "rank")
            from .web_export import export_menu
            export_menu(ui, cfg, connect, f"check-rank_{cur['name']}_{date.today():%Y-%m-%d}", lambda: export(),
                        label="Xuất file", user=user, icon_only=True)
            more = ui.button(icon="more_horiz").props("flat round dense color=grey-8").tooltip("Thêm")
            more.props["aria-label"] = "Thêm thao tác và thông tin của bộ"
            with more, ui.menu().props("anchor='bottom right' self='top right'").classes("sr-more-menu"):
                with ui.column().classes("gap-0 q-px-md q-py-sm"):
                    ui.label("Chi phí ước tính").classes("sr-more-cap")
                    cost_label = ui.label("…").classes("sr-more-val")
                if ed:
                    ui.separator()
                    with ui.item(on_click=lambda: set_dialog(cur)).props("clickable"):
                        with ui.item_section().props("avatar"):
                            ui.icon("tune")
                        with ui.item_section():
                            ui.label("Cài đặt bộ")
                            ui.label("Tên, loại, nơi check, lịch, độ sâu, tạm dừng").classes("text-xs muted")
                if owner:
                    ui.separator()
                    with ui.item(on_click=lambda: delete_set_dialog()).props("clickable").classes(
                            "text-negative"):
                        with ui.item_section().props("avatar"):
                            ui.icon("delete_forever", color="negative")
                        with ui.item_section():
                            ui.label("Xóa vĩnh viễn bộ này…")

        # Hàng tiến độ (chỉ khi đang check): trạng thái + số đã gửi / có kết quả bên trên, thanh mảnh rộng hết bên
        # dưới. Thanh chỉ tính từ khóa đã có kết quả thật; chưa có số thì chạy dạng chờ (không phần trăm giả).
        with ui.element("div").classes("sr-run") as run_box:
            run_box.props["role"] = "status"
            run_box.props["aria-live"] = "polite"
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.spinner(size="14px", color="primary")
                run_label = ui.label("Đang chuẩn bị…").classes("sr-run-label")
                ui.space()
                run_stats = ui.label("").classes("sr-run-stats")
                if ed:
                    stop_btn = ui.button("Dừng gửi", icon="pause", on_click=lambda: stop_check()).props(
                        "flat dense no-caps size=sm color=grey-9").classes("sr-run-stop").tooltip(
                        "Không gửi thêm từ khóa nào. Từ khóa đã gửi vẫn chạy và vẫn tính phí; từ khóa chưa gửi giữ "
                        "lại, bấm Tiếp tục để check nốt.")
            run_bar = ui.linear_progress(0, show_value=False).props(
                "rounded size=4px color=primary track-color=grey-3").classes("sr-run-bar")
        run_box.set_visibility(site in _RUNNING)

    def delete_set_dialog():
        """Xóa vĩnh viễn cả bộ: phải gõ đúng tên bộ. Chỉ Admin."""
        if not owner:
            return
        with connect() as c:
            ids = [k["id"] for k in R.keywords(c, site, end, sid)] + [
                k["id"] for k in R.keywords(c, site, end, sid, removed=True)]
            stats = R.purge_stats(c, ids)
        with ui.dialog() as d, ui.card().style("max-width: 480px; border-radius: 14px"):
            with ui.row().classes("items-center no-wrap gap-2"):
                ui.icon("warning", color="negative", size="24px")
                ui.label(f"Xóa vĩnh viễn bộ “{cur['name']}”?").classes("text-lg font-semibold")
            lost(stats, "bộ này")
            ui.label("Gõ tên bộ để xác nhận:").classes("text-sm q-mt-sm")
            typed = ui.input(placeholder=cur["name"]).props("outlined dense").classes("w-full")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")

                async def go():
                    from nicegui import run
                    if typed.value.strip().lower() != cur["name"].strip().lower():
                        ui.notify("Tên bộ chưa đúng", type="warning")
                        return
                    if is_kpi and sheet:  # bộ gắn sheet: xóa các dòng trên tab Từ khóa cam kết trước
                        try:
                            with connect() as c:
                                kws = [k["keyword"] for k in R.keywords(c, site, end, sid)]
                            for kw in kws:
                                await run.io_bound(KP.sheet_keyword_op, cfg, sheet, "delete", kw)
                        except Exception as e:  # noqa: BLE001
                            ui.notify(f"Không xóa được trên sheet: {e}", type="negative", multi_line=True)
                            return
                    with connect() as c:
                        R.delete_set(c, sid, str(user))
                    d.close()
                    ui.notify(f"Đã xóa vĩnh viễn bộ {cur['name']}", type="positive")
                    ui.navigate.to("/rank")
                btn = ui.button("Xóa vĩnh viễn", icon="delete_forever", on_click=go).props(
                    "unelevated no-caps color=negative")
                btn.bind_enabled_from(typed, "value",
                                      backward=lambda v: (v or "").strip().lower() == cur["name"].strip().lower())
        d.open()

    def lost(stats: dict, what: str) -> None:
        """Khung cảnh báo: những gì mất khi xóa vĩnh viễn."""
        with ui.element("div").classes("sr-danger-box w-full"):
            ui.label(f"Sẽ xóa hẳn {stats['keywords']} từ khóa của {what} cùng {stats['checks']} lần check "
                     f"(lịch sử thứ hạng, kết quả Google, AI Overview).").classes("text-sm")
            ui.label(f"Dữ liệu đã trả {R.usd(stats['cost'], 3)} USD. Không khôi phục được; muốn giữ lịch sử thì "
                     "dùng Tạm dừng.").classes("text-sm font-semibold")

    def lock_dialog():
        """Chốt bộ Nháp: báo chi phí ước tính mỗi tháng trước khi bắt đầu chạy theo lịch."""
        if not ed:
            return
        with connect() as c:
            kws = [k for k in R.keywords(c, site, end, sid) if not k["own_paused"]]
            per_month = R.estimate(c, cfg.rank, sched, [k["depth"] for k in kws])
            total = R.estimate_all(c, site, cfg.rank, end) + per_month
        budget = cfg.rank.monthly_budget_usd
        with ui.dialog() as d, ui.card().style("max-width: 460px; border-radius: 14px"):
            ui.label(f"Chốt bộ “{cur['name']}”?").classes("text-lg font-semibold")
            ui.label(f"{len(kws)} từ khóa · {R.describe_schedule(sched)}").classes("text-sm")
            ui.label(f"Ước tính khoảng {R.usd(per_month)} USD/tháng. Cả dự án: {R.usd(total)} / {budget:.0f} USD.")\
                .classes("text-sm")
            if budget and total > budget:
                ui.label("Vượt ngân sách check rank của dự án: lượt check vượt sẽ bị dừng. Tăng ngân sách ở màn Ngân "
                         "sách check rank, hoặc bớt từ khóa / giãn lịch.").classes("text-sm").style(
                    f"color:{T.RED}")
            if not kws:
                ui.label("Bộ chưa có từ khóa nào.").classes("text-sm muted")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")

                def go():
                    with connect() as c:
                        R.lock_set(c, sid, str(user))
                    d.close()
                    ui.notify(f"Đã chốt bộ {cur['name']}: check theo lịch từ bây giờ", type="positive")
                    ui.navigate.to(f"/rank?bo={sid}")
                ui.button("Chốt bộ", icon="lock", on_click=go).props("unelevated no-caps")
        d.open()

    # ---- Hộp thoại tạo / sửa bộ: tên, nơi check, lịch, độ sâu ----
    def set_dialog(st: dict | None):
        if not ed:
            return
        sc = (st or {}).get("schedule") or sched
        own = (st or {}).get("settings") or {}
        w = R.settings_for(cfg.rank, st)
        with ui.dialog() as d, ui.card().style("min-width: 560px; max-width: 94vw; border-radius: 14px"):
            ui.label("Cài đặt bộ từ khóa" if st else "Bộ từ khóa mới").classes("text-lg font-semibold")
            name = ui.input("Tên bộ", value=(st or {}).get("name", ""),
                            placeholder="ví dụ: Hà Nội, Blog, Sản phẩm, Desktop").props("outlined dense").classes(
                "w-full")
            ui.label("Loại bộ").classes("text-sm font-semibold q-mt-sm")
            kind_t = ui.toggle({"kpi": "Cam kết", "custom": "Theo dõi"}, value=(st or {}).get("kind", "custom")).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
            ui.label("Cam kết: dùng làm nguồn cho dòng KPI. Theo dõi: bộ bổ trợ, nghiên cứu, đối thủ…").classes(
                "text-xs muted")
            ui.label("Nơi check").classes("text-sm font-semibold q-mt-sm")
            follow = ui.switch("Theo nơi check của dự án", value=not own).props("dense")
            box = ui.column().classes("w-full gap-2")
            with box:
                t_domain = ui.select(R.SE_DOMAINS, value=w.se_domain, label="Vùng Google").props(
                    "outlined dense").classes("w-full")
                t_device = ui.select(R.DEVICES, value=w.device, label="Thiết bị").props("outlined dense").classes(
                    "w-full")
                t_loc = ui.select(R.locations(), value=w.location_code, label="Vị trí tìm kiếm",
                                  with_input=True).props("outlined dense").classes("w-full")
                t_lang = ui.select(R.LANGUAGES, value=w.language_code, label="Ngôn ngữ").props(
                    "outlined dense").classes("w-full")
            box.bind_visibility_from(follow, "value", backward=lambda v: not v)
            ui.label("Lịch check").classes("text-sm font-semibold q-mt-sm")
            kind = ui.toggle({"weekdays": "Hằng tuần", "monthly": "Hằng tháng", "manual": "Thủ công"},
                             value=sc["type"]).props("unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes("sr-seg")
            days_box = ui.row().classes("gap-1")
            with days_box:
                day_checks = [ui.chip(n.replace("Thứ ", "T").replace("Chủ nhật", "CN"), selectable=True,
                                      selected=i in sc["weekdays"]).props("outline color=primary")
                              for i, n in enumerate(R.WEEKDAYS)]
            with ui.row().classes("items-center gap-3"):
                month_day = ui.number("Ngày trong tháng", value=sc["day"], min=1, max=31, step=1,
                                      format="%d").props("dense outlined").classes("w-40")
                # Ô giờ gốc của trình duyệt (<input type="time">): chia giờ / phút / SA-CH, phím mũi tên lên-xuống
                # đổi từng phần, trái-phải chuyển phần. Trên điện thoại trình duyệt tự mở bánh xe (iOS) / mặt đồng
                # hồ (Android). Giá trị luôn là 24 giờ "HH:mm"; kiểu hiển thị 12/24 giờ theo ngôn ngữ máy người dùng.
                at_time = ui.input("Giờ check", value=sc.get("time") or R.DEFAULT_SCHEDULE["time"],
                                   validation={"Chọn giờ check": lambda v: bool(v)}).props(
                    'dense outlined type=time step=60 hide-bottom-space').classes("w-40")
                at_time.props["aria-label"] = "Giờ check theo giờ Việt Nam"
            depth = ui.select({x: ("Tự động" if x == "auto" else f"Top {x}") for x in R.DEPTHS}, value=sc["depth"],
                              label="Độ sâu check").props("dense outlined").classes("w-48")
            ui.label("Tự động: lần đầu check top 30; sau đó theo vị trí lần trước (≤ 18 → top 20, còn "
                     "lại top 30). Check sâu hơn tốn tiền hơn.").classes("text-xs muted")
            if st:
                ui.label("Đổi nơi check thì các lần check sau có thể lệch so với trước (Google trả kết quả khác theo "
                         "nơi tìm), không phải do website lên / xuống hạng.").classes("text-xs").style(
                    f"color:{T.AMBER_TEXT}")

            pause_sw = ui.switch("Tạm dừng cả bộ (không check, không tính tiền; lịch sử vẫn giữ)",
                                 value=bool((st or {}).get("paused"))).props("dense") if st else None
            est_box = ui.element("div").classes("sr-cost-box w-full")
            if not st:
                ui.label("Bộ mới ở dạng Nháp: thêm từ khóa thoải mái, chưa check và chưa tốn tiền. Bấm Chốt bộ khi "
                         "sẵn sàng.").classes("text-xs muted")

            def sched_now() -> dict:
                return {"type": kind.value, "weekdays": [i for i, cb in enumerate(day_checks) if cb.selected],
                        "day": int(month_day.value or 1), "depth": depth.value, "time": at_time.value or "07:00"}

            def show_est():
                """Chi phí mỗi tháng của bộ theo lịch đang chọn; cảnh báo nếu cả dự án vượt ngân sách."""
                est_box.clear()
                if not st:
                    return
                with connect() as c:
                    kws = [k for k in R.keywords(c, site, end, st["id"]) if not k["own_paused"]]
                    mine = R.estimate(c, cfg.rank, sched_now(), [k["depth"] for k in kws])
                    old = 0 if st["draft"] or st["paused"] else R.estimate(c, cfg.rank, st["schedule"],
                                                                            [k["depth"] for k in kws])
                    total = R.estimate_all(c, site, cfg.rank, end) - old + (0 if st["draft"] else mine)
                budget = cfg.rank.monthly_budget_usd
                with est_box:
                    ui.label(f"Ước tính bộ này: {R.usd(mine)} USD/tháng ({len(kws)} từ khóa)"
                             + (", tính khi Chốt bộ" if st["draft"] else "")
                             + f" · cả dự án {R.usd(total)} / {budget:.0f} USD").classes("text-sm")
                    if budget and total > budget:
                        ui.label("Vượt ngân sách check rank của dự án: lượt check vượt sẽ bị dừng.").classes(
                            "text-sm").style(f"color:{T.RED}")

            def view():
                days_box.set_visibility(kind.value == "weekdays")
                month_day.set_visibility(kind.value == "monthly")
                at_time.set_visibility(kind.value != "manual")
                show_est()
            kind.on_value_change(lambda _: view())
            depth.on_value_change(lambda _: show_est())
            for cb in day_checks:
                cb.on_value_change(lambda _: show_est())
            view()

            def save():
                s_new = sched_now()
                if s_new["type"] == "weekdays" and not s_new["weekdays"]:
                    ui.notify("Chọn ít nhất một thứ trong tuần", type="warning")
                    return
                if s_new["type"] != "manual" and not at_time.value:  # ô giờ bị xóa trống: không tự đặt 07:00
                    at_time.validate()
                    ui.notify("Chọn giờ check", type="warning")
                    return
                settings = None if follow.value else {"se_domain": t_domain.value, "device": t_device.value,
                                                      "location_code": t_loc.value, "language_code": t_lang.value}
                try:
                    with connect() as c:
                        if st:
                            R.update_set(c, st["id"], str(user), name=name.value, settings=settings,
                                         schedule=s_new, paused=pause_sw.value, kind=kind_t.value)
                            new_id = st["id"]
                        else:
                            new_id = R.create_set(c, site, name.value, str(user), settings=settings,
                                                  schedule=s_new, kind=kind_t.value, state="draft")
                except ValueError as e:
                    ui.notify(str(e), type="warning")
                    return
                d.close()
                ui.navigate.to(f"/rank?bo={new_id}")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Lưu" if st else "Tạo bộ", on_click=save).props("unelevated no-caps")
        d.open()

    # ---- Thêm keyword vào bộ đang mở ----
    with ui.dialog() as add_dialog, ui.card().style("min-width: 620px; max-width: 94vw; border-radius: 14px"):
        ui.label(f"Thêm keyword vào bộ {cur['name']}").classes("text-lg font-semibold")
        ui.label("Mỗi dòng một keyword. Thêm URL mục tiêu và / hoặc Top mục tiêu sau dấu |, ví dụ: "
                 "tròng kính | https://… | Top 3 (hoặc dán các cột từ Excel)."
                 + (" Bộ Cam kết: tool thêm luôn vào tab Từ khóa cam kết của sheet." if is_kpi else "")).classes(
            "text-sm muted")
        paste = ui.textarea(placeholder=f"từ khóa 1\ntừ khóa 2 | https://{domain(cfg.site_url)}/trang-muc-tieu/ | "
                                        "Top 3").props("outlined autogrow").classes("w-full")
        cost_box = ui.element("div").classes("sr-cost-box w-full")  # ước tính chi phí, cập nhật khi dán / gõ
        cost_box.set_visibility(False)
        paste.on("update:model-value", lambda e: show_cost(e.args or ""), throttle=0.5)
        add_result = ui.label().classes("text-sm")
        if is_kpi and sheet:  # đọc lại toàn bộ tab Từ khóa cam kết (thêm, cập nhật, bỏ)
            ui.separator()
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.label("Hoặc đồng bộ lại cả bộ theo tab Từ khóa cam kết của sheet (thêm mới, cập nhật URL / Top; "
                         "từ khóa đã bỏ khỏi sheet chuyển sang bộ Ngoài cam kết).").classes("text-sm col")
                sheet_btn = ui.button("Đồng bộ sheet", icon="sync", on_click=lambda: from_sheet()).props(
                    "outline no-caps")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Đóng", on_click=add_dialog.close).props("flat no-caps")
            add_btn = ui.button("Thêm vào bộ", icon="playlist_add", on_click=lambda: add()).props(
                "unelevated no-caps")
    if is_kpi and not sheet:
        add_btn.disable()
        add_btn.tooltip("Dự án chưa gắn sheet: tạo / gắn sheet ở màn KPI cam kết")

    # ---- Bộ Nháp: nhắc chưa check, chưa tốn tiền ----
    if draft:
        with ui.element("div").classes("sr-draft-note w-full"):
            ui.icon("edit_note", size="22px").props('aria-hidden="true"')
            with ui.column().classes("gap-0 col"):
                ui.label("Bộ đang ở dạng Nháp").classes("font-semibold")
                ui.label("Chưa check và chưa tốn tiền. Thêm / sửa từ khóa thoải mái, xong bấm Chốt bộ để bắt đầu "
                         f"check theo lịch ({R.describe_schedule(sched)}).").classes("text-sm")
            if ed:
                ui.button("Chốt bộ", icon="lock", on_click=lambda: lock_dialog()).props("unelevated no-caps")
    # ---- Bento tổng quan của bộ ----
    bento_box = ui.element("div").classes("w-full")
    view_state = {"period": "check"}  # kỳ đang xem ở biểu đồ tăng trưởng

    # ---- Bảng: tìm, lọc, thùng rác; chọn nhiều thì hiện thanh thao tác hàng loạt ----
    with ui.row().classes("w-full items-center gap-2 q-mt-sm"):
        ui.label(f"Danh sách keyword · {cur['name']}").classes("sr-section-title")
        ui.space()
        search = ui.input(placeholder="Tìm từ khóa, URL, ghi chú…").props("dense outlined clearable").classes(
            "w-64")
        search.props["prepend-icon"] = "search"
        from .web_export import export_menu as _export_menu
        _export_menu(ui, cfg, connect, f"tu-khoa_{cur['name']}_{date.today():%Y-%m-%d}", lambda: export(),
                     label="Xuất bảng (Excel)", user=user, icon_only=True)
        filt = ui.select({k: v[0] for k, v in FILTERS.items()}, value="all", label="Lọc",
                         on_change=lambda: refresh()).props("dense outlined options-dense").classes("w-56")
        trash_slot = ui.row()  # nút thùng rác (có số), vẽ lại khi làm mới
    wrong_box = ui.row().classes("w-full")
    selection_bar = ui.row().classes("w-full items-center gap-2 sr-bulk-bar")
    with selection_bar:
        selected_label = ui.label().classes("text-sm font-medium")
        if ed:
            icon_btn(ui, "play_arrow", "Check các keyword đã chọn", lambda: check_now())
            with icon_btn(ui, "edit_note", "Sửa hàng loạt: Top, URL, ghi chú, tạm dừng, chuyển / chép bộ"):
                with ui.menu():
                    for label, icon, fn in (("Đặt Top mục tiêu…", "flag", lambda: bulk_top()),
                                            ("Gán URL mục tiêu…", "link", lambda: bulk_url()),
                                            ("Ghi chú…", "sticky_note_2", lambda: bulk_note()),
                                            ("Tạm dừng check", "pause_circle", lambda: bulk_pause(True)),
                                            ("Chạy lại", "play_circle", lambda: bulk_pause(False)),
                                            ("Chuyển sang bộ khác…", "drive_file_move", lambda: bulk_set("move")),
                                            ("Chép sang bộ khác…", "content_copy", lambda: bulk_set("copy"))):
                        with ui.menu_item(on_click=fn).classes("items-center gap-3"):
                            ui.icon(icon, size="18px").classes("muted")
                            ui.label(label).classes("text-sm")
        if owner:
            icon_btn(ui, "delete_forever", "Xóa vĩnh viễn (cả lịch sử, không khôi phục được)", lambda: remove(),
                     color="negative")
        ui.space()
        icon_btn(ui, "close", "Bỏ chọn", lambda: (table.selected.clear(), table.update(), on_select()),
                 color="grey-8")
    selection_bar.set_visibility(False)
    # Cùng một bộ cột, cùng độ rộng cho mọi bộ từ khóa (bảng table-layout: fixed): từ khóa và URL chia phần còn lại.
    def w(px):
        return {"headerStyle": f"width:{px}px", "style": f"width:{px}px"}
    # Thứ tự cột theo mức quan trọng: từ khóa → vị trí, thay đổi → AI Overview → ý định, volume, mục tiêu → URL.
    # Ngày check không thành cột (thường giống nhau): nằm trong chú thích ô Vị trí, cũ hơn bộ thì có chấm vàng.
    def rank_sort(field: str) -> str:  # sắp theo hạng: ">20" (ngoài độ sâu) sau mọi số, ô trống cuối cùng
        return (f"(a, b, rowA, rowB) => (rowA.{field}_n ?? 9999) - (rowB.{field}_n ?? 9999)")
    cols = [
        {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True, **w(230)},
        {"name": "pos", "label": "Vị trí", "field": "pos", "align": "center", "sortable": True,
         ":sort": "(a, b, rowA, rowB) => rowA.sort_pos - rowB.sort_pos", **w(72)},
        {"name": "change", "label": "Thay đổi", "field": "change", "align": "center", "sortable": True,
         ":sort": "(a, b, rowA, rowB) => rowA.move - rowB.move", **w(100)},
        {"name": "prev_pos", "label": "Trước", "field": "prev_pos", "align": "center", "sortable": True,
         ":sort": rank_sort("prev_pos"), **w(56)},
        {"name": "best", "label": "Tốt nhất", "field": "best", "align": "center", "sortable": True,
         ":sort": rank_sort("best"), **w(68)},
        {"name": "first_pos", "label": "Ban đầu", "field": "first_pos", "align": "center", "sortable": True,
         ":sort": rank_sort("first_pos"), **w(72)},
        {"name": "aio", "label": "AIO", "field": "aio_rank", "align": "center", "sortable": True, **w(42)},
        {"name": "intent", "label": "Ý định", "field": "intent", "align": "center", "sortable": True, **w(56)},
        {"name": "volume", "label": "Volume", "field": "volume", "align": "center", "sortable": True, **w(66)},
        {"name": "top", "label": "Mục tiêu", "field": "top", "align": "center", "sortable": True, **w(74),
         ":sort": "(a, b, rowA, rowB) => (rowA.top_n || 999) - (rowB.top_n || 999)"},
        {"name": "checked_at", "label": "Check lúc", "field": "checked_at", "align": "center", "sortable": True,
         **w(84), ":sort": "(a, b, rowA, rowB) => (rowA.checked_iso || '').localeCompare(rowB.checked_iso || '')"},
        {"name": "link", "label": "URL", "field": "link", "align": "left", "sortable": False,
         "headerStyle": "min-width:150px"},  # cột co giãn: nhận phần rộng còn lại thay cho cột Từ khóa
        {"name": "chart", "label": "", "field": "id", "align": "center", **w(60)},
    ]
    table = ui.table(columns=cols, rows=[], row_key="id", selection="multiple" if ed else "none",
                     pagination=50).classes("w-full sr-kw-table").props("flat bordered dense binary-state-sort")
    # Tìm theo từ khóa, URL đang xếp hạng, URL mục tiêu, ghi chú. Hàm Python bên dưới lọc giống hệt để ô "chọn tất
    # cả" biết đúng các dòng đang khớp tìm kiếm (trên mọi trang, không chỉ trang đang xem).
    SEARCH_FIELDS = ("keyword", "link_full", "target_full", "note")
    table.props[":filter-method"] = (
        "(rows, terms) => { const q = (terms || '').toLowerCase(); return rows.filter(r => "
        + " || ".join(f"(r.{f} || '').toLowerCase().includes(q)" for f in SEARCH_FIELDS) + "); }")
    search.bind_value(table, "filter")
    # Tiêu đề cột: bấm (hoặc Enter / Space khi đang chọn bằng Tab) để sắp xếp tăng / giảm trên toàn bộ dữ liệu; mũi
    # tên nhỏ chỉ chiều; aria-sort cho trình đọc màn hình.
    table.add_slot("header-cell", """
        <q-th :props="props"
              :aria-sort="props.col.sortable ? ((props.col.__thClass || '').includes('sorted')
                ? ((props.col.__thClass || '').includes('sort-desc') ? 'descending' : 'ascending') : 'none') : undefined"
              :tabindex="props.col.sortable ? 0 : undefined"
              @keydown.enter.prevent="props.col.sortable && props.sort(props.col)"
              @keydown.space.prevent="props.col.sortable && props.sort(props.col)">{{ props.col.label }}</q-th>""")
    # Ô chọn ở tiêu đề: chọn / bỏ chọn mọi dòng khớp tìm kiếm trên mọi trang; chọn một phần thì hiện dấu gạch.
    table.add_slot("header-selection", """
        <q-checkbox dense :model-value="props.colsMap.keyword.all_state === 'all' ? true
                      : (props.colsMap.keyword.all_state === 'some' ? null : false)"
                    aria-label="Chọn tất cả từ khóa" @update:model-value="() => $parent.$emit('toggle_all')" />""")
    table.add_slot("body-cell-keyword", """
        <q-td :props="props">
          <div class="row no-wrap items-center" style="gap: 4px">
            <span class="sr-kw-link" role="button" tabindex="0" :style="{opacity: props.row.paused ? 0.55 : 1}"
                  @click="$parent.$emit('chart', props.row)" @keydown.enter="$parent.$emit('chart', props.row)"
                  :title="'Xem chi tiết: ' + props.value">{{ props.value }}</span>
            <q-icon v-if="props.row.note" name="sticky_note_2" size="15px" color="amber-8">
              <q-tooltip max-width="320px">{{ props.row.note }}</q-tooltip></q-icon>
          </div>
        </q-td>""")
    table.add_slot("body-cell-intent", """
        <q-td :props="props" class="text-center"><span v-if="props.row.intent" :class="'sr-intent ' + props.row.intent">{{ props.row.intent }}
                      <q-tooltip>{{ {'I': 'Informational (Thông tin)', 'N': 'Navigational (Điều hướng)', 'C': 'Commercial (Cân nhắc mua)', 'T': 'Transactional (Mua / giao dịch)'}[props.row.intent] }}</q-tooltip></span></q-td>""")
    table.add_slot("body-cell-pos", """
        <q-td :props="props" class="text-center">
          <span v-if="props.row.paused" class="sr-pill grey"><q-icon name="pause" size="13px" /> dừng</span>
          <span v-else-if="props.row.checked" class="sr-pos">
            <q-icon class="medal" :name="props.row.medal_icon || 'circle'" size="15px"
                    :style="{color: props.row.medal || 'transparent'}" />
            <span class="chip" :style="{background: props.row.bg, color: props.row.fg}">{{ props.value }}</span>
            <i v-if="props.row.date_old" class="old"></i>
            <q-tooltip>Lần check gần nhất: {{ props.row.date_full }}<template v-if="props.row.date_old"><br/>Cũ hơn
              lần check mới nhất của bộ</template></q-tooltip></span>
          <span v-else class="muted">chờ check</span>
        </q-td>""")
    table.add_slot("body-cell-aio", """
        <q-td :props="props" class="text-center">
          <q-icon v-if="props.row.aio" name="auto_awesome" size="18px"
                  :style="{color: props.row.aio_cited ? '#6250d6' : '#C9C7BC'}">
            <q-tooltip>{{ props.row.aio_cited ? 'Có AI Overview, website được trích'
              : (props.row.aio_cited === false ? 'Có AI Overview, website chưa được trích'
              : 'Có AI Overview (không tải được nội dung)') }}</q-tooltip></q-icon>
          <span v-else class="muted">–</span>
        </q-td>""")
    table.add_slot("body-cell-first_pos", """
        <q-td :props="props" class="text-center">
          <span v-if="props.value" class="row inline no-wrap items-center" style="gap:2px">
            <span :class="'sr-rk ' + (props.row.first_pos_n <= 3 ? 'r3' : props.row.first_pos_n <= 10 ? 'r10'
                  : props.row.first_pos_n < 999 ? 'r20' : 'out')">{{ props.value }}</span>
            <q-icon v-if="props.row.since_first" :name="props.row.since_first > 0 ? 'trending_up' : 'trending_down'"
                    size="15px" :style="{color: props.row.since_first > 0 ? '#1E7C31' : '#C2410C'}">
              <q-tooltip>{{ props.row.since_first > 0 ? 'Tốt hơn' : 'Kém hơn' }} so với lần check đầu tiên
              </q-tooltip></q-icon></span>
          <span v-else class="muted">–</span>
        </q-td>""")
    for name_ in ("prev_pos", "best"):  # vị trí phụ: số mờ hơn, cùng màu nhóm hạng
        table.add_slot(f"body-cell-{name_}", """
        <q-td :props="props" class="text-center">
          <span v-if="props.value" :class="'sr-rk ' + (props.row['""" + "{0}" + """_n'] <= 3 ? 'r3'
                : props.row['""" + "{0}" + """_n'] <= 10 ? 'r10' : props.row['""" + "{0}" + """_n'] < 999 ? 'r20' : 'out')">
            {{ props.value }}</span>
          <span v-else class="muted">–</span>
        </q-td>""".replace("{0}", name_))
    table.add_slot("body-cell-checked_at", """
        <q-td :props="props" class="text-center">
          <span v-if="props.value" :class="props.row.date_old ? 'muted' : ''" style="white-space: nowrap;
                font-size: 12.5px">{{ props.value }}<q-tooltip v-if="props.row.date_old">Cũ hơn lần check mới nhất
                của bộ</q-tooltip></span>
          <span v-else class="muted">–</span>
        </q-td>""")
    table.add_slot("body-cell-volume", """
        <q-td :props="props" class="text-right">
          <span v-if="props.value === null || props.value === undefined" class="muted">–
            <q-tooltip>Chưa lấy volume (tool lấy lúc 6:00 sáng)</q-tooltip></span>
          <span v-else-if="props.value < 0" class="muted">&lt; 10</span>
          <span v-else class="num">{{ props.value.toLocaleString('vi-VN') }}</span>
        </q-td>""")
    table.add_slot("body-cell-top", """
        <q-td :props="props" class="text-center">
          <span v-if="props.value" :class="'sr-pill goal-' + (props.row.top_n <= 3 ? 3 : props.row.top_n <= 5 ? 5
                : props.row.top_n <= 10 ? 10 : 'x') + (props.row.top_hit ? ' hit' : '')">
            <q-icon v-if="props.row.top_hit" name="check" size="13px" />{{ props.value }}
            <q-tooltip>{{ props.row.top_hit ? 'Đã đạt Top mục tiêu' : 'Chưa đạt Top mục tiêu' }}</q-tooltip></span>
          <span v-else class="muted">–</span>
        </q-td>""")
    table.add_slot("body-cell-change", """
        <q-td :props="props">
          <span v-if="props.value === 'Mới'" class="sr-pill new">Mới<q-tooltip>Lần check đầu tiên của từ khóa
            </q-tooltip></span>
          <span v-else-if="!props.value || props.value === '–'" class="muted">–</span>
          <span v-else class="sr-chg" :class="props.row.move > 0 ? 'up' : 'down'">
            <q-icon :name="props.row.move > 0 ? 'trending_up' : 'trending_down'" size="16px" />
            {{ props.row.change_short }}<q-tooltip>{{ props.value }} so với lần check trước</q-tooltip></span>
        </q-td>""")
    table.add_slot("body-cell-link", """
        <q-td :props="props">
          <div class="row no-wrap items-center" style="gap: 6px; min-width: 0">
            <q-icon v-if="props.row.wrong" name="warning" color="orange-8" size="16px">
              <q-tooltip>Google đang xếp hạng URL khác URL mục tiêu<br/>Mục tiêu: {{ props.row.target_full }}
                (vị trí {{ props.row.target_pos }})</q-tooltip></q-icon>
            <q-icon v-else-if="props.row.target_full && props.row.link_full" name="check_circle" color="green-8"
                    size="16px"><q-tooltip>Đúng URL mục tiêu</q-tooltip></q-icon>
            <a v-if="props.row.link_full" :href="props.row.link_full" target="_blank" rel="noopener"
               :title="props.row.link_full" class="ellipsis" style="color: inherit; text-decoration: none; min-width: 0">
              {{ props.value }}</a>
            <span v-else-if="props.row.target_full" class="muted row inline no-wrap items-center" style="gap:4px">
              <q-icon name="flag" size="16px" color="grey-6" />chưa xếp hạng
              <q-tooltip>URL mục tiêu: {{ props.row.target_full }}</q-tooltip></span>
            <span v-else class="muted">–</span>
          </div>
        </q-td>""")
    table.add_slot("body-cell-chart", """
        <q-td :props="props">
          <div class="row no-wrap justify-center">
            <q-btn v-if="props.row.can_edit" flat round dense icon="edit" color="grey-7" size="sm"
                   :aria-label="'Sửa ' + props.row.keyword" @click="$parent.$emit('edit', props.row)">
              <q-tooltip>Sửa Top mục tiêu / URL mục tiêu</q-tooltip></q-btn>
            <q-btn flat round dense icon="show_chart" color="grey-7" size="sm" :aria-label="'Biểu đồ ' + props.row.keyword"
                   @click="$parent.$emit('chart', props.row)"><q-tooltip>Lịch sử vị trí</q-tooltip></q-btn>
          </div>
        </q-td>""")

    def visible_ids() -> set:
        q = (search.value or "").strip().lower()
        return {r["id"] for r in table.rows if not q or any(q in (r.get(f) or "").lower() for f in SEARCH_FIELDS)}

    def sync_all(_=None):
        """Trạng thái ô chọn tất cả: all / some (dấu gạch) / none, tính trên các dòng đang khớp tìm kiếm."""
        vis = visible_ids()
        sel = {r["id"] for r in table.selected} & vis
        state = "all" if vis and sel == vis else ("some" if sel else "none")
        if table.columns[0].get("all_state") != state:
            table.columns = [{**table.columns[0], "all_state": state}] + table.columns[1:]

    def toggle_all(_=None):
        vis = visible_ids()
        picked = {r["id"] for r in table.selected}
        if vis and vis <= picked:  # đang chọn hết → bỏ chọn các dòng đang khớp
            table.selected = [r for r in table.selected if r["id"] not in vis]
        else:
            table.selected = list(table.selected) + [r for r in table.rows if r["id"] in vis and r["id"] not in picked]
        table.update()
        on_select()

    def on_select(_=None):
        n = len(table.selected)
        selection_bar.set_visibility(n > 0)
        selected_label.text = f"Đã chọn {n}"
        sync_all()

    table.on_select(on_select)
    table.on("toggle_all", toggle_all)
    search.on_value_change(sync_all)

    def show_chart(e):
        """Lịch sử một từ khóa: biểu đồ vị trí, danh sách các lần check (Chủ tool xóa được lần check sai), nhật ký."""
        row = e.args
        with connect() as c:
            hist = R.history(c, row["id"])
            log = R.keyword_log(c, site, row["keyword"])
            evs = R.events(c, site, sid)
            serps = R.serp_history(c, row["id"])
        with ui.dialog() as d, ui.card().style("min-width: 680px; max-width: 94vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label(row["keyword"]).classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=d.close).props("flat round dense")
            with ui.tabs().classes("w-full sr-tabs").props("align=left no-caps dense inline-label") as tabs:
                t1 = ui.tab("Vị trí", icon="show_chart")
                t0 = ui.tab("Kết quả Google", icon="travel_explore")
                t2 = ui.tab(f"Các lần check · {len(hist)}", icon="event_note")
                t3 = ui.tab(f"Nhật ký · {len(log)}", icon="history")
            with ui.tab_panels(tabs, value=t1).classes("w-full").props("animated=false"):
                with ui.tab_panel(t1).classes("q-px-none"):
                    pts = [{"date": dd} for dd, _, _ in hist]
                    ui.echart({"tooltip": {"trigger": "axis"}, "animation": False,
                               "grid": {"left": 40, "right": 16, "top": 20, "bottom": 32},
                               "xAxis": {"type": "category", "data": [_vn(dd)[:5] for dd, _, _ in hist]},
                               "yAxis": {"type": "value", "inverse": True, "min": 1, "name": "Vị trí"},
                               "series": [{"type": "line", "data": [r for _, r, _ in hist], "connectNulls": False,
                                           "itemStyle": {"color": "#1E7C31"}, "label": {"show": True,
                                                                                       "position": "top"},
                                           **event_marks(pts, evs)}]}).classes("w-full").style("height: 300px")
                    ui.label("Trục vị trí đảo ngược: lên cao là tốt hơn. Điểm trống = ngoài độ sâu check. Vạch tím là "
                             "mốc sự kiện.").classes("text-xs muted")
                with ui.tab_panel(t0).classes("q-px-none"):
                    serp_panel(row, serps)
                with ui.tab_panel(t2).classes("q-px-none"):
                    checks = ui.column().classes("w-full gap-0")

                    def draw_checks():
                        checks.clear()
                        with connect() as c:
                            h2 = R.history(c, row["id"])
                        with checks:
                            if not h2:
                                ui.label("Chưa có lần check nào.").classes("text-sm muted")
                            for dd, r, dep in reversed(h2):
                                with ui.row().classes("w-full items-center no-wrap gap-3 q-py-xs"):
                                    ui.label(_vn(dd)).classes("text-sm num").style("width: 96px")
                                    ui.label(f"Vị trí {r}" if r is not None else f"Ngoài top {dep}").classes(
                                        "text-sm col")
                                    ui.label(f"độ sâu {dep}").classes("text-xs muted")
                                    if owner:
                                        ui.button(icon="delete_outline", on_click=lambda dd=dd: drop_check(dd)).props(
                                            "flat round dense size=sm color=negative").tooltip(
                                            "Xóa lần check này (chỉ khi kết quả sai)")
                        if owner:
                            with checks:
                                ui.label("Chỉ xóa lần check có kết quả sai (ví dụ Google trả trang lạ). Việc xóa có "
                                         "ghi nhật ký.").classes("text-xs muted q-mt-sm")

                    def drop_check(dd: str):
                        if not owner:
                            return
                        with connect() as c:
                            R.delete_check(c, site, row["id"], dd, str(user))
                        ui.notify(f"Đã xóa lần check {_vn(dd)}", type="positive")
                        draw_checks()
                        refresh()
                    draw_checks()
                with ui.tab_panel(t3).classes("q-px-none"):
                    if not log:
                        ui.label("Chưa có thay đổi nào được ghi lại.").classes("text-sm muted")
                    for x in log:
                        with ui.row().classes("w-full items-start no-wrap gap-3 q-py-xs"):
                            ui.label(_local(x["at"])).classes("text-xs muted num").style("width: 120px")
                            with ui.column().classes("gap-0 col"):
                                ui.label(x["action"]).classes("text-sm")
                                extra = x["detail"].split(": ", 1)[1] if ": " in (x["detail"] or "") else ""
                                if extra or x["url"]:
                                    ui.label(" · ".join(v for v in (extra, x["url"]) if v)).classes(
                                        "text-xs muted ellipsis")
                            ui.label(x["user"]).classes("text-xs muted")
        d.open()

    def serp_panel(row: dict, serps: list[dict]) -> None:
        """Tab Kết quả Google của một từ khóa: vị trí của website so với AI Overview (có / được trích / các nguồn AI
        trích) và 10 kết quả đầu (đối thủ) kèm thay đổi so với lần trước. Đọc từ kết quả check rank đã trả tiền."""
        host = domain(site)

        def disp(url: str, own: bool = False) -> str:
            """URL dễ đọc: bỏ phần sau dấu ? (mã theo dõi srsltid của Google), giải mã chữ tiếng Việt."""
            from urllib.parse import unquote, urlsplit
            u = urlsplit(url or "")
            path = unquote(u.path) or "/"
            return path if own else unquote(u.netloc).removeprefix("www.") + path

        if not serps:
            T.empty_state(ui, "travel_explore", "Chưa có: lần check sau sẽ có",
                          "Tool lưu AI Overview và 10 kết quả đầu từ kết quả check rank (không tốn thêm phí, AI "
                          "Overview hiện chậm thêm tối đa 0,0006 USD).")
            return
        box = ui.column().classes("w-full gap-3")
        from . import aio as AO
        with connect() as c:
            all_b = AO.brands(c, cfg)
        rivals = [b for b in all_b if not b["own"]]
        own_name = next((b["name"] for b in all_b if b["own"]), "dự án")

        def draw(i: int) -> None:
            box.clear()
            cur, prev = serps[i], (serps[i + 1] if i + 1 < len(serps) else None)
            with box:
                # ---- Vị trí thường và AI Overview, cạnh nhau ----
                with ui.element("div").classes("sr-serp-pair"):
                    with ui.column().classes("gap-0 sr-serp-cell"):
                        ui.label("Vị trí trên Google").classes("text-xs muted")
                        mine = next((x for x in cur["organic"] if R._host_match(x["domain"], host)), None)
                        rank_txt = str(mine["rank"]) if mine else (f"Ngoài top {cur['depth_seen']}"
                                                                   if cur["organic"] else "–")
                        ui.label(rank_txt).classes("sr-mini-num num")
                        if mine:
                            lk = ui.link(disp(mine["url"], own=True), mine["url"], new_tab=True).classes(
                                "text-xs ellipsis muted")
                            lk.props["title"] = mine["url"]
                    with ui.column().classes("gap-0 sr-serp-cell"):
                        ui.label("AI Overview").classes("text-xs muted")
                        if not cur["aio"]:
                            ui.label("Không có").classes("sr-mini-num").style("color:#8C8A7E")
                            ui.label("Google không hiện câu trả lời AI cho từ khóa này").classes("text-xs muted")
                        elif cur["cited"]:
                            ui.label("✓ Được trích").classes("sr-mini-num").style("color:#1E7C31")
                            ui.label(f"Trong {len(cur['refs'])} nguồn AI trích").classes("text-xs muted")
                        elif cur["cited"] is False:
                            ui.label("✗ Chưa được trích").classes("sr-mini-num").style("color:#B3401A")
                            ui.label(f"AI trích {len(cur['refs'])} nguồn khác").classes("text-xs muted")
                        else:
                            ui.label("Có").classes("sr-mini-num")
                            ui.label("Không tải được nội dung AI Overview").classes("text-xs muted")
                # ---- Nguồn AI trích ----
                if cur["aio"] and cur["refs"]:
                    ui.label("Nguồn AI Overview trích").classes("sr-section-title").style("font-size:14px")
                    for x in cur["refs"]:
                        me = R._host_match(x["domain"], host)
                        with ui.row().classes("w-full items-center no-wrap gap-2 sr-serp-row" + (" me" if me else "")):
                            ui.label(x["domain"]).classes("text-sm font-medium").style("min-width:160px")
                            lk = ui.link(x["title"] or disp(x["url"]), x["url"], new_tab=True).classes(
                                "text-sm ellipsis col")
                            lk.props["title"] = x["url"]
                # ---- Đối thủ đang theo dõi (danh sách chung của dự án, tối đa 10) ----
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label("Đối thủ").classes("sr-section-title").style("font-size:14px")
                    ui.space()
                    ui.link("Quản lý đối thủ", "/aio?tab=brands").classes("text-xs")
                if not rivals:
                    ui.label("Chưa có đối thủ nào: thêm ở trang AI Overview → Thương hiệu (tối đa 10).").classes(
                        "text-sm muted")
                else:
                    pos = AO.brand_ranks(cur["organic"], rivals)
                    my_rank = mine["rank"] if mine else None
                    for b in sorted(rivals, key=lambda b: (pos[b["id"]] or {}).get("rank") or 999):
                        p_ = pos[b["id"]]
                        ahead = p_ and (my_rank is None or p_["rank"] < my_rank)
                        with ui.row().classes("w-full items-center no-wrap gap-2 sr-serp-row"):
                            ui.label(str(p_["rank"]) if p_ else "–").classes("sr-mv-num sr-mv-now").style(
                                "min-width:28px")
                            ui.label(b["name"]).classes("text-sm font-medium").style("min-width:180px")
                            if p_:
                                lk = ui.link(disp(p_["url"]), p_["url"], new_tab=True).classes(
                                    "text-xs muted ellipsis col")
                                lk.props["title"] = p_["url"]
                            else:
                                ui.label(f"Không có trong top {cur['depth_seen']}").classes("text-xs muted col")
                            if ahead:
                                ui.label(f"xếp trên {own_name}").classes("sr-delta down")
                # ---- Top 10 ----
                ui.label("10 kết quả đầu trên Google").classes("sr-section-title").style("font-size:14px")
                ref_hosts = {x["domain"] for x in cur["refs"]}
                for x in R.compare_top10(cur["top10"], prev["top10"] if prev else None):
                    me = R._host_match(x["domain"], host)
                    with ui.row().classes("w-full items-center no-wrap gap-2 sr-serp-row" + (" me" if me else "")):
                        ui.label(str(x["rank"])).classes("sr-mv-num sr-mv-now").style("min-width:28px")
                        ui.label(x["domain"] + (" (website dự án)" if me else "")).classes(
                            "text-sm font-medium").style("min-width:180px")
                        lk = ui.link(disp(x["url"], own=me), x["url"], new_tab=True)
                        lk.classes("text-xs muted ellipsis col")
                        lk.props["title"] = x["url"]
                        if x["domain"] in ref_hosts:
                            ui.icon("auto_awesome", size="15px").style("color:#7C3AED").tooltip(
                                "Được AI Overview trích")
                        mv = x["move"]
                        if mv == "new":
                            ui.label("mới").classes("sr-delta flat").tooltip("Mới vào top 10 so với lần trước")
                        elif mv:
                            ui.label(("▲ " if mv > 0 else "▼ ") + str(abs(mv))).classes(
                                "sr-delta " + ("up" if mv > 0 else "down")).tooltip(
                                f"So với lần check {_vn(prev['date'])[:5]}")
                if not cur["top10"]:
                    ui.label("Không có kết quả tự nhiên trong lần check này.").classes("text-sm muted")
                ui.label("Lấy từ kết quả check rank (DataForSEO, cùng nơi check của bộ), trong độ sâu đã check. "
                         "Không tốn thêm phí.").classes(
                    "text-xs muted")

        if len(serps) > 1:
            opts = {i: _vn(x["date"]) + (" (mới nhất)" if i == 0 else "") for i, x in enumerate(serps)}
            ui.select(opts, value=0, label="Lần check", on_change=lambda e: draw(e.value)).props(
                "dense outlined options-dense").classes("w-56")
        else:
            ui.label(f"Lần check {_vn(serps[0]['date'])}").classes("text-sm muted")
        draw(0)

    table.on("chart", show_chart)

    # ---- Sửa một từ khóa: Top mục tiêu, URL mục tiêu (bộ Cam kết: ghi lên sheet) ----
    def edit_dialog(e):
        if not ed:
            return
        row = e.args
        with connect() as c:
            sug = R.url_suggestions(c, site, row["keyword"], end)
        with ui.dialog() as d, ui.card().style("min-width: 560px; max-width: 94vw; border-radius: 14px"):
            ui.label(f"Sửa: {row['keyword']}").classes("text-lg font-semibold")
            if is_kpi:
                ui.label("Từ khóa cam kết: tool ghi thay đổi lên tab Từ khóa cam kết của sheet dự án.").classes(
                    "text-sm muted")
            top = ui.select({0: "Không đặt"} | {t: f"Top {t}" for t in TOPS}, value=row.get("top_n") or 0,
                            label="Top mục tiêu").props("outlined dense").classes("w-48")
            url_in = ui.input("URL mục tiêu", value=row["target_full"],
                              placeholder=f"https://{domain(site)}/trang-muc-tieu/").props(
                "outlined dense clearable").classes("w-full")
            picks = [(s_["url"], f"{s_['clicks']:,} click · {s_['impressions']:,} hiển thị".replace(",", "."))
                     for s_ in sug]
            if row["link_full"] and row["link_full"] not in [u for u, _ in picks]:
                picks.insert(0, (row["link_full"], "Google đang xếp hạng URL này"))
            if picks:
                ui.label("Gợi ý (GSC 90 ngày / URL đang xếp hạng):").classes("text-xs muted")
                for u, note in picks:
                    with ui.row().classes("w-full items-center no-wrap gap-2"):
                        ui.button(icon="north_west", on_click=lambda u=u: url_in.set_value(u)).props(
                            "flat dense round size=sm").tooltip("Dùng URL này")
                        lab = ui.label(short(u)).classes("text-sm ellipsis col")
                        lab.props["title"] = u
                        ui.label(note).classes("text-xs muted")
            note_in = ui.input("Ghi chú", value=row.get("note") or "",
                               placeholder="ví dụ: đã viết lại bài 05/11, chờ index").props(
                "outlined dense clearable maxlength=300").classes("w-full")
            pause_sw = ui.switch("Tạm dừng check từ khóa này", value=bool(row.get("own_paused"))).props("dense")
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")

            async def save():
                err.text = ""
                t = int(top.value or 0) or None
                try:
                    if (url_in.value or "").strip() != row["target_full"] or t != row.get("top_n"):
                        await save_keyword(row, (url_in.value or "").strip(), t)
                    with connect() as c:
                        if (note_in.value or "") != (row.get("note") or ""):
                            R.set_note(c, site, [row["id"]], note_in.value or "", str(user))
                        if bool(pause_sw.value) != bool(row.get("own_paused")):
                            R.set_paused(c, site, [row["id"]], bool(pause_sw.value), str(user))
                except Exception as ex:  # noqa: BLE001
                    err.text = str(ex)
                    return
                d.close()
                ui.notify("Đã lưu" + (" và ghi lên sheet" if is_kpi else ""), type="positive")
                refresh()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Lưu", icon="check", on_click=save).props("unelevated no-caps")
        d.open()

    table.on("edit", edit_dialog)

    async def save_keyword(row: dict, url: str, top: int | None, sync: bool = True):
        """Lưu Top / URL mục tiêu. Bộ Cam kết: ghi dòng đó lên sheet trước, rồi đọc lại sheet (sync=False: người gọi
        đọc lại một lần sau khi sửa nhiều dòng)."""
        from nicegui import run
        if url and domain(url) != domain(site):
            raise ValueError(f"URL phải thuộc {domain(site)}")
        if is_kpi:
            await run.io_bound(KP.sheet_keyword_op, cfg, sheet, "upsert", row["keyword"], url, top)
            with connect() as c:
                R.set_target_url(c, site, row["id"], url, str(user))
            if sync:
                await run.io_bound(_sync_sheet)
            return
        with connect() as c:
            R.set_target_url(c, site, row["id"], url, str(user))
            R.set_top_target(c, site, row["id"], top, str(user))

    def _sync_sheet():
        with connect() as c:
            return KP.sync(c, cfg, str(user))

    def short(url):
        return (url or "").replace(site.rstrip("/"), "") or ("/" if url else "")

    from nicegui import context
    _client = context.client
    _VIEWS.setdefault(site, {})[_client.id] = lambda: (check_btn.props(remove="loading") if ed else None, refresh())
    _client.on_delete(lambda: _VIEWS.get(site, {}).pop(_client.id, None))

    def refresh():
        from . import volume as V
        with connect() as c:
            kws = R.keywords(c, site, end, sid)
            vols = V.latest(c)
            hist = R.set_history(c, site, sid)
            evs = R.events(c, site, sid)
            try:  # mục tiêu cam kết Top N (sheet KPI) cho bảng / biểu đồ xu hướng của bộ Cam kết
                kpi_now = KP.rank_kpi_now(c, site, date.today(), sid) if commit_set else None
            except Exception:  # noqa: BLE001 — sheet KPI lỗi không được làm hỏng màn rank
                kpi_now = None
            n_trash = len(R.keywords(c, site, end, sid, removed=True))
            from . import rank_overview as RO
            aio_now = RO.aio_for(c, cfg, [k for k in kws if not k["own_paused"]])
        trash_slot.clear()
        if n_trash:  # thùng rác chỉ còn cho từ khóa đã bỏ trước khi có Xóa vĩnh viễn
            with trash_slot:
                icon_btn(ui, "delete_sweep", "Thùng rác cũ: từ khóa đã bỏ theo dõi trước đây", lambda: trash_dialog(),
                         color="grey-8", badge=n_trash)
        keep = FILTERS.get(filt.value, FILTERS["all"])[1]
        rows = []
        newest = max((k["date"] for k in kws if k["date"]), default=None)
        with connect() as c:
            flags = R.serp_flags(c, [k["id"] for k in kws])  # AI Overview ở lần check gần nhất
            firsts = {}  # lần check đầu tiên của từng từ khóa: (hạng, độ sâu)
            if kws:
                for kid_, r_, d_ in c.execute(
                        f"SELECT keyword_id, rank, depth FROM rank_checks c WHERE keyword_id IN "
                        f"({','.join('?' * len(kws))}) AND check_date = (SELECT MIN(check_date) FROM rank_checks x "
                        f"WHERE x.keyword_id = c.keyword_id)", [k["id"] for k in kws]):
                    firsts[kid_] = (r_, d_)
            from . import intent as IN
            intents = IN.for_keywords(c, cfg, kws)  # ý định tìm kiếm (đoán theo chữ + kết quả Google, miễn phí)
        for k in kws:
            if not keep(k):
                continue
            cur_pos = k["rank"] if k["rank"] is not None else (k["last_depth"] or 0) + 1
            text, color, move = change_text(k)
            bg, fg = next((t for lim, t in RANK_TONES if k["rank"] is not None and k["rank"] <= lim),
                          ("#F1F0EA", "#6B6A5E"))
            top = k.get("top_target")
            rows.append({
                "id": k["id"], "keyword": k["keyword"], "pos": _pos(k["rank"], k["last_depth"]),
                "source": SOURCES.get(k["source"], k["source"]),
                "top": f"Top {top}" if top else "", "top_n": top,
                "top_hit": bool(top and k["rank"] is not None and k["rank"] <= top),
                "volume": ((vols[k["id"]]["volume"] if vols[k["id"]]["volume"] is not None else -1)
                           if k["id"] in vols else None),
                "checked": bool(k["date"]), "sort_pos": cur_pos or 999, "bg": bg, "fg": fg,
                "change": text, "change_color": color, "move": move, "best": k["best"] or "",
                "best_n": k["best"] if k["best"] is not None else None,
                "change_short": _short_change(text),
                "since_first": (0 if k["id"] not in firsts or not k["date"] else
                                ((firsts[k["id"]][0] if firsts[k["id"]][0] is not None else 999)
                                 - (k["rank"] if k["rank"] is not None else 999))),
                "prev_pos": _pos(k["prev"], k["prev_depth"]),
                "prev_pos_n": (k["prev"] if k["prev"] is not None else 999) if k["prev_depth"] else None,
                "first_pos": _pos(*firsts[k["id"]]) if k["id"] in firsts else "",
                "first_pos_n": ((firsts[k["id"]][0] if firsts[k["id"]][0] is not None else 999)
                                if k["id"] in firsts else None),
                "checked_at": _local(k["checked_at"])[:5] + _local(k["checked_at"])[10:] if k.get("checked_at")
                else "",
                "checked_iso": k.get("checked_at") or "",
                "date": _vn(k["date"])[:5] if k["date"] else "", "date_full": _vn(k["date"]) if k["date"] else "",
                "date_iso": k["date"] or "", "date_old": bool(k["date"] and newest and k["date"] < newest), "link": short(k["ranking_url"]), "link_full": k["ranking_url"] or "",
                "target": short(k["target_url"]), "target_full": k["target_url"] or "",
                "wrong": bool(k["target_url"] and k["ranking_url"] and k["ranking_url"] != k["target_url"]),
                "target_pos": _pos(k["target_rank"], k["last_depth"]),
                "can_edit": ed and (not is_kpi or bool(sheet)),
                "paused": k["paused"], "own_paused": k["own_paused"], "note": k["note"],
                "medal": {1: "#D4A017", 2: "#9AA3AE", 3: "#B87333"}.get(k["rank"], ""),  # vàng / bạc / đồng
                "medal_icon": {1: "emoji_events", 2: "workspace_premium", 3: "military_tech"}.get(k["rank"], ""),
                "aio_rank": (2 if flags.get(k["id"], (False, None))[1] else 1) if flags.get(k["id"], (False,))[0]
                else 0,
                "aio": flags.get(k["id"], (False, None))[0], "aio_cited": flags.get(k["id"], (False, None))[1],
                "intent": intents.get(k["id"], ("",))[0],
                "intent2": [c_ for c_, _ in (intents.get(k["id"]) or ("", "", []))[2]],
                "intent_tip": IN.tip(intents.get(k["id"])),
            })
        table.rows = rows
        table.selected = []
        on_select()
        def load(period):
            with connect() as c:
                return R.set_history(c, site, sid, limit={"check": 30, "week": 26, "month": 18}[period],
                                     period=period)
        bento_box.clear()
        with bento_box:
            bento(ui, kws, hist, evs, load, view_state, lambda: events_dialog(),
                  lambda k: show_chart(SimpleNamespace(args={"id": k["id"], "keyword": k["keyword"]})),
                  on_filter=show_in_table, short_url=short, kpi_now=kpi_now, aio=aio_now, aio_link=f"/aio?bo={sid}")
        with connect() as c:
            est = R.estimate(c, cfg.rank, sched, [k["depth"] for k in kws])
        cost_label.text = f"≈ {R.usd(est)} USD / tháng cho bộ này"
        last_h = hist[-1] if hist else None
        # hàng thông tin luôn là lần check gần nhất; đang check thì trạng thái ở hàng tiến độ
        status_row.clear()
        with status_row:
            if last_h:
                n_un = last_h.get("unchecked", 0)
                stat("check_circle" if not n_un else "error_outline",
                     f"{last_h['checked']}/{len(kws)} từ khóa đã kiểm tra",
                     f"{n_un} từ khóa mới thêm sẽ check ở lần tới" if n_un else "Mọi từ khóa của bộ đã có kết quả",
                     tone="ok" if not n_un else "warn")
                at = max((k["checked_at"] for k in kws if k.get("checked_at")), default=None)
                stat("schedule", f"Cập nhật {_local(at) if at else _vn(last_h['date'])}", "Lần check mới nhất của bộ")
            else:
                stat("schedule", "Chưa kiểm tra lần nào")
            stat("event_repeat", when.replace(" vào ", " · "),
                 f"Lịch check tự động; ước tính ≈ {R.usd(est)} USD / tháng")
            if cur["paused"]:
                stat("pause_circle", "Đang tạm dừng", "Bộ không được check tự động, không tính tiền", tone="warn")
            if is_kpi:
                stat("sync", "Đồng bộ sheet cam kết",
                     "Thêm / sửa / bỏ từ khóa ở đây thì tool ghi lên tab Từ khóa cam kết")
        wrong = sum(1 for k in kws if k["target_url"] and k["ranking_url"] and k["ranking_url"] != k["target_url"])
        wrong_box.clear()
        if wrong and filt.value != "wrong":
            with wrong_box:
                ui.button(f"{wrong} sai URL mục tiêu", icon="warning",
                          on_click=lambda: filt.set_value("wrong")).props(
                    "flat dense no-caps color=orange-9 size=sm")
        if on_budget_change:
            on_budget_change()

    def show_in_table(key: str):
        """Từ thẻ tổng quan xuống bảng: đặt bộ lọc rồi cuộn tới bảng."""
        filt.set_value(key)
        with filt:  # nút bấm nằm trong khung vừa vẽ lại: chạy JS trong ngữ cảnh còn sống
            ui.run_javascript("document.querySelector('.sr-kw-table')?.scrollIntoView({behavior: "
                              "matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', "
                              "block: 'start'})")

    def show_cost(text: str):
        """Ước tính trước khi thêm: số keyword mới, tiền mỗi lần check, tiền thêm mỗi tháng, tổng so với ngân sách."""
        items = R.parse_lines(text if isinstance(text, str) else "")
        cost_box.clear()
        cost_box.set_visibility(bool(items))
        if not items:
            return
        with connect() as c:
            e = R.estimate_add(c, site, cfg.rank, end, [kw for kw, _ in items], sid)
        over, warn = e["ratio"] > 1, e["ratio"] >= R.ALERT_RATIO
        tone = "red" if over else "amber" if warn else "green"
        cost_box.classes(replace=f"sr-cost-box w-full {tone}")
        with cost_box:
            with ui.row().classes("items-center no-wrap gap-2"):
                ui.icon("calculate", size="18px")
                ui.label(f"Ước tính chi phí: {e['new']} keyword mới"
                         + (f" ({e['existing']} đã có trong bộ, không tính)" if e["existing"] else "")
                         ).classes("text-sm font-medium")
            if not e["new"]:
                ui.label("Không tốn thêm tiền.").classes("text-sm")
                return
            ui.label(f"Mỗi lần check thêm khoảng {R.usd(e['per_check'], 4)} USD "
                     + (f"(lần đầu check top {e['depth']}; sau đó tool chỉnh độ sâu theo vị trí nên thường rẻ hơn)."
                        if e["schedule"]["depth"] == "auto" else f"(check top {e['depth']}).")).classes("text-sm")
            if e["checks_per_month"]:
                ui.label(f"Theo lịch của bộ ({R.describe_schedule(e['schedule']).split(';')[0].lower()}): thêm "
                         f"khoảng {R.usd(e['monthly_add'], 3)} USD/tháng.").classes("text-sm")
            else:
                ui.label("Lịch của bộ là Thủ công: chỉ tốn tiền khi bấm Check ngay.").classes("text-sm")
            ui.label(f"Tổng dự kiến cả tháng (mọi bộ): {R.usd(e['monthly_total'])} / {e['budget']:g} USD "
                     f"({e['ratio'] * 100:.0f}% ngân sách)."
                     + (" Vượt ngân sách: phần vượt sẽ không được thêm. Bỏ bớt keyword, giãn lịch hoặc tăng ngân "
                        "sách." if over else " Sắp chạm ngân sách." if warn else "")).classes("text-sm font-medium")

    async def from_sheet():
        if not ed:
            return
        from nicegui import run
        sheet_btn.props("loading")
        try:
            info = await run.io_bound(_sync_sheet)
        except Exception as e:  # noqa: BLE001
            add_result.text = f"Không đọc được sheet: {e}"
            return
        finally:
            sheet_btn.props(remove="loading")
        parts = [f"Sheet có {info['keywords']} từ khóa cam kết, thêm mới {info['added']}"]
        if info.get("moved"):
            parts.append(f"chuyển {len(info['moved'])} từ khóa đã bỏ khỏi sheet sang bộ {R.DROPPED_SET_NAME}")
        if info["over_budget"]:
            parts.append(f"KHÔNG thêm {len(info['over_budget'])} từ khóa vì vượt ngân sách")
        if info["bad_url"]:
            parts.append(f"bỏ qua {len(info['bad_url'])} dòng có URL không thuộc site")
        add_result.text = " · ".join(parts) + "."
        refresh()

    def parse_items(text: str) -> list[tuple]:
        """(keyword, URL, Top) từ ô dán: mỗi dòng 'từ khóa | URL | Top 3' (URL, Top không bắt buộc)."""
        return [(kw.lower(), url or None, t) for kw, url, t in KP.parse_keyword_text(text)]

    async def add():
        if not ed:  # chặn ở server: nút bị ẩn chưa đủ, sự kiện vẫn gửi được từ trình duyệt
            return
        from nicegui import run

        from . import volume as V
        items = parse_items(paste.value or "")
        if not items:
            return
        if is_kpi:  # bộ Cam kết: thêm lên sheet trước, rồi đọc lại sheet
            add_btn.props("loading")
            try:
                for kw, url, t in items:
                    await run.io_bound(KP.sheet_keyword_op, cfg, sheet, "upsert", kw, url, t)
                info = await run.io_bound(_sync_sheet)
            except Exception as e:  # noqa: BLE001
                add_result.text = f"Không ghi được lên sheet: {e}"
                return
            finally:
                add_btn.props(remove="loading")
            r = {"added": info["added"] if isinstance(info["added"], list) else [None] * info["added"],
                 "updated": [], "exists": [], "over_budget": info["over_budget"], "bad_url": info["bad_url"],
                 "estimate": None}
        else:
            with connect() as c:
                r = R.add_keywords(c, site, cfg.rank, end, items, str(user), set_id=sid)

        def fetch_volume():  # keyword mới thêm: lấy volume ngay (keyword đã có số tháng này thì bỏ qua)
            with connect() as c:
                return V.refresh(c, site, cfg, end, log=lambda m: None)
        try:
            await run.io_bound(fetch_volume)
        except Exception as e:  # noqa: BLE001  (keyword vẫn được thêm, volume lấy lại ở lịch hằng ngày)
            ui.notify(f"Chưa lấy được volume: {e}", type="warning", multi_line=True)
        parts = [f"Đã thêm {len(r['added'])}"]
        if r["updated"]:
            parts.append(f"cập nhật URL / Top {len(r['updated'])}")
        if r["exists"]:
            parts.append(f"đã có sẵn {len(r['exists'])}")
        if r["over_budget"]:
            parts.append(f"KHÔNG thêm {len(r['over_budget'])} keyword vì vượt ngân sách: {', '.join(r['over_budget'][:5])}"
                         + (" (ngân sách check rank của dự án đang là 0 USD/tháng: đặt ở màn Ngân sách check rank, "
                            "hoặc thêm vào một bộ Nháp trước)" if not cfg.rank.monthly_budget_usd else ""))
        if r["bad_url"]:
            parts.append(f"bỏ qua {len(r['bad_url'])} dòng có URL không thuộc site")
        add_result.text = " · ".join(parts) + (f". Ước tính: {R.usd(r['estimate'])} USD/tháng."
                                               if r.get("estimate") is not None else ".")
        paste.value = ""
        show_cost("")
        if not r["over_budget"] and not r["bad_url"]:
            add_dialog.close()
            ui.notify(add_result.text, type="positive")
            ui.navigate.to(f"/rank?bo={sid}")  # số từ khóa trên tab cập nhật theo
        else:
            refresh()

    def remove():
        """Xóa vĩnh viễn từ khóa đã chọn (chỉ Admin): báo những gì sẽ mất rồi mới xóa."""
        if not owner:  # chặn ở server: nút bị ẩn chưa đủ, sự kiện vẫn gửi được từ trình duyệt
            return
        if not table.selected:
            ui.notify("Tích chọn keyword cần xóa", type="warning")
            return
        picked_rows = list(table.selected)
        with connect() as c:
            stats = R.purge_stats(c, [r_["id"] for r_ in picked_rows])
        with ui.dialog() as d, ui.card().style("max-width: 480px; border-radius: 14px"):
            with ui.row().classes("items-center no-wrap gap-2"):
                ui.icon("warning", color="negative", size="24px")
                ui.label(f"Xóa vĩnh viễn {len(picked_rows)} từ khóa?").classes("text-lg font-semibold")
            lost(stats, "lựa chọn")
            if is_kpi:
                ui.label("Các dòng này cũng bị xóa khỏi tab Từ khóa cam kết của sheet.").classes("text-sm muted")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")

                async def go():
                    from nicegui import run
                    if is_kpi:  # bộ gắn sheet: xóa dòng trên sheet trước, rồi xóa trong tool
                        if not sheet:
                            ui.notify("Dự án chưa gắn sheet cam kết", type="warning")
                            return
                        try:
                            for r_ in picked_rows:
                                await run.io_bound(KP.sheet_keyword_op, cfg, sheet, "delete", r_["keyword"])
                        except Exception as e:  # noqa: BLE001
                            ui.notify(f"Không ghi được lên sheet: {e}", type="negative", multi_line=True)
                            return
                    with connect() as c:
                        R.purge_keywords(c, site, [r_["id"] for r_ in picked_rows], str(user))
                    if is_kpi:
                        try:
                            await run.io_bound(_sync_sheet)
                        except Exception:  # noqa: BLE001  (đã xóa trên sheet; lần đồng bộ sau đọc lại)
                            pass
                    d.close()
                    ui.notify(f"Đã xóa vĩnh viễn {len(picked_rows)} từ khóa", type="positive")
                    ui.navigate.to(f"/rank?bo={sid}")
                ui.button("Xóa vĩnh viễn", icon="delete_forever", on_click=go).props(
                    "unelevated no-caps color=negative")
        d.open()

    async def check_now(only: list[int] | None = None, confirmed: bool = False):
        if not ed:  # chặn ở server: nút bị ẩn chưa đủ, sự kiện vẫn gửi được từ trình duyệt
            return
        from nicegui import background_tasks

        if site in _RUNNING:
            ui.notify("Đang check rank cho website này, xong sẽ báo.", type="info")
            return
        if draft:
            ui.notify("Bộ đang ở dạng Nháp: bấm Chốt bộ trước khi check", type="warning")
            return
        ids = only or [r_["id"] for r_ in table.selected] or [r_["id"] for r_ in table.rows if not r_["paused"]]
        if not ids:
            ui.notify("Bộ này chưa có từ khóa nào để check", type="warning", position="bottom-right",
                      classes="sr-toast")
            return
        creds = R.load_credentials(cfg.dataforseo_secret)
        if not creds:
            ui.notify(f"Chưa có API key DataForSEO trong {cfg.dataforseo_secret}", type="negative")
            return
        if not confirmed:
            today = date.today().isoformat()
            with connect() as c:
                done_today = {kid: at for kid, at in c.execute(
                    f"SELECT keyword_id, checked_at FROM rank_checks WHERE check_date = ? AND keyword_id IN "
                    f"({','.join('?' * len(ids))})", (today, *ids))}
            if done_today:
                fresh = [i for i in ids if i not in done_today]
                last_at = _local(max(done_today.values()))
                with ui.dialog() as d, ui.card().style("max-width: 480px; border-radius: 14px"):
                    ui.label(f"{len(done_today)}/{len(ids)} từ khóa đã check hôm nay").classes(
                        "text-lg font-semibold")
                    ui.label(f"Lần gần nhất lúc {last_at}. Check lại trong cùng ngày tốn thêm tiền và chỉ thay số của "
                             "hôm nay (Google ít khi đổi hạng trong vài giờ).").classes("text-sm")
                    with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                        ui.button("Hủy", on_click=d.close).props("flat no-caps")

                        async def all_again():
                            d.close()
                            await check_now(ids, confirmed=True)

                        async def only_new():
                            d.close()
                            await check_now(fresh, confirmed=True)
                        ui.button("Check lại tất cả", on_click=all_again).props("outline no-caps")
                        if fresh:
                            ui.button(f"Chỉ check {len(fresh)} từ khóa chưa check", on_click=only_new).props(
                                "unelevated no-caps")
                d.open()
                return
        _RUNNING.add(site)
        _PAUSED.pop((site, sid), None)
        _PROGRESS[site] = {"set": cur["name"], "total": len(ids), "posted": 0, "done": 0, "failed": 0,
                           "phase": "submit", "stop": False}
        tick()
        status_running()
        ui.notify(f"Bắt đầu check {len(ids)} từ khóa", caption="Có thể sang trang khác, xong tool sẽ báo",
                  type="info", position="bottom-right", classes="sr-toast", timeout=4000)
        background_tasks.create(_check_job(cfg, connect, site, end, ids, creds, str(user), sid))

    def stop_check():
        st = _PROGRESS.get(site)
        if not ed or not st or st["stop"]:
            return
        st["stop"] = True
        tick()
        ui.notify("Đã dừng gửi thêm từ khóa", caption="Từ khóa đã gửi vẫn chạy và có kết quả", type="info",
                  position="bottom-right", classes="sr-toast", timeout=4000)

    async def resume_check():
        left = _PAUSED.get((site, sid)) or []
        if left:
            await check_now(left)

    def tick():
        """Mỗi giây: panel tiến độ khi website đang check (gửi / chờ kết quả / đang dừng gửi), nút Tiếp tục khi lượt
        trước bị dừng gửi giữa chừng. Số lấy từ job nền (_PROGRESS), không ước lượng theo thời gian."""
        running = site in _RUNNING
        st = _PROGRESS.get(site) or {}
        run_box.set_visibility(running)
        if ed:
            check_btn.set_enabled(not running and not cfg.rank.paused)
            left = _PAUSED.get((site, sid)) or []
            resume_btn.set_visibility(bool(left) and not running)
            if left:
                resume_btn.text = f"Tiếp tục ({len(left)})"
                resume_btn.tooltip(f"Check nốt {len(left)} từ khóa chưa gửi ở lượt bị dừng")
        if not running:
            return
        total = st.get("total") or 0
        posted, done = st.get("posted", 0), st.get("done", 0)
        failed = st.get("failed", 0)
        waiting = max(posted - done - failed, 0)
        phase = st.get("phase", "submit")
        sending = phase == "submit" and posted + failed < total
        if st.get("stop"):
            head = "Đã dừng gửi, chờ nốt kết quả" if waiting else "Đang dừng gửi…"
        elif sending:
            head = "Đang gửi yêu cầu"
        else:
            head = "Đang chờ kết quả"
        other = st.get("set") and st.get("set") != cur["name"]
        run_label.text = (f"Bộ {st['set']} · " if other else "") + head
        parts = [f"Đã gửi {posted}/{total}", f"Có kết quả {done}/{total}"]
        if waiting:
            parts.append(f"Chờ {waiting}")
        if failed:
            parts.append(f"Lỗi {failed}")
        run_stats.text = " · ".join(parts)
        if done or not waiting:  # đã có kết quả thật: thanh xác định; chưa có gì thì thanh chạy chờ
            run_bar.props(remove="indeterminate")
            run_bar.value = done / total if total else 0
        else:
            run_bar.props("indeterminate")
        run_bar.props(f'aria-valuenow={done} aria-valuemin=0 aria-valuemax={total} '
                      f'aria-label="Đã có kết quả {done} trên {total} từ khóa"')
        if ed:  # chỉ còn ý nghĩa khi còn từ khóa chưa gửi
            stop_btn.set_visibility(sending and not st.get("stop"))

    ui.timer(1.0, tick)

    def picked() -> list[dict]:
        if not table.selected:
            ui.notify("Tích chọn từ khóa trước", type="warning")
        return list(table.selected)

    def small_dialog(title: str, build, on_ok, ok_label: str = "Lưu"):
        """Hộp thoại nhỏ cho thao tác hàng loạt: build() dựng ô nhập, on_ok() (async) chạy khi bấm nút."""
        with ui.dialog() as d, ui.card().style("min-width: 460px; max-width: 94vw; border-radius: 14px"):
            ui.label(title).classes("text-lg font-semibold")
            if is_kpi:
                ui.label("Bộ Cam kết: tool ghi thay đổi lên tab Từ khóa cam kết của sheet.").classes("text-xs muted")
            vals = build()
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")

            async def ok():
                err.text = ""
                btn.props("loading")
                try:
                    msg = await on_ok(vals)
                except Exception as ex:  # noqa: BLE001
                    err.text = str(ex)
                    return
                finally:
                    btn.props(remove="loading")
                d.close()
                ui.notify(msg, type="positive")
                ui.navigate.to(f"/rank?bo={sid}")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                btn = ui.button(ok_label, icon="check", on_click=ok).props("unelevated no-caps")
        d.open()

    def bulk_top():
        rows = picked()
        if not rows or not ed:
            return

        async def go(v):
            t = int(v.value or 0) or None
            for r_ in rows:
                await save_keyword(r_, r_["target_full"], t, sync=False)
            if is_kpi:
                from nicegui import run
                await run.io_bound(_sync_sheet)
            return f"Đã đặt {'Top ' + str(t) if t else 'không có Top mục tiêu'} cho {len(rows)} từ khóa"
        small_dialog(f"Đặt Top mục tiêu cho {len(rows)} từ khóa", lambda: ui.select(
            {0: "Không đặt"} | {t: f"Top {t}" for t in TOPS}, value=3, label="Top mục tiêu").props(
            "outlined dense").classes("w-48"), go)

    def bulk_url():
        rows = picked()
        if not rows or not ed:
            return

        async def go(v):
            url = (v.value or "").strip()
            for r_ in rows:
                await save_keyword(r_, url, r_.get("top_n"), sync=False)
            if is_kpi:
                from nicegui import run
                await run.io_bound(_sync_sheet)
            return f"Đã {'gán URL mục tiêu' if url else 'bỏ URL mục tiêu'} cho {len(rows)} từ khóa"
        small_dialog(f"Gán URL mục tiêu cho {len(rows)} từ khóa", lambda: ui.input(
            "URL mục tiêu (để trống = bỏ URL mục tiêu)", placeholder=f"https://{domain(site)}/trang-muc-tieu/").props(
            "outlined dense clearable").classes("w-full"), go)

    def bulk_note():
        rows = picked()
        if not rows or not ed:
            return

        async def go(v):
            with connect() as c:
                R.set_note(c, site, [r_["id"] for r_ in rows], v.value or "", str(user))
            return f"Đã {'ghi chú' if v.value else 'xóa ghi chú'} cho {len(rows)} từ khóa"
        small_dialog(f"Ghi chú cho {len(rows)} từ khóa", lambda: ui.input(
            "Ghi chú (để trống = xóa)", placeholder="ví dụ: đã viết lại bài 05/11").props(
            "outlined dense clearable maxlength=300").classes("w-full"), go)

    def bulk_pause(on: bool):
        rows = picked()
        if not rows or not ed:
            return
        with connect() as c:
            n = R.set_paused(c, site, [r_["id"] for r_ in rows], on, str(user))
        ui.notify(f"Đã {'tạm dừng' if on else 'chạy lại'} {n} từ khóa", type="positive")
        refresh()

    def bulk_set(mode: str):
        rows = picked()
        if not rows or not ed:
            return
        with connect() as c:
            others = {x["id"]: x["name"] for x in R.sets(c, site) if x["id"] != sid}
        if not others:
            ui.notify("Chưa có bộ khác: tạo bộ mới trước", type="warning")
            return

        async def go(v):
            from nicegui import run
            dest = v.value
            with connect() as c:
                dest_set = R.get_set(c, dest)
            to_kpi = dest_set["kind"] == "kpi"
            if (is_kpi or to_kpi) and not sheet:
                raise ValueError("Dự án chưa gắn sheet cam kết")
            if mode == "move":
                with connect() as c:
                    res = R.move_keywords(c, site, [r_["id"] for r_ in rows], dest, str(user))
                done = res["moved"]
            else:
                with connect() as c:
                    res = R.copy_keywords(c, site, cfg.rank, end, [r_["id"] for r_ in rows], dest, str(user))
                done = res["added"]
            # Bộ Cam kết theo sheet: ra khỏi bộ thì xóa dòng trên sheet, vào bộ thì thêm dòng
            by_kw = {r_["keyword"]: r_ for r_ in rows}
            if is_kpi and mode == "move":
                for kw in done:
                    await run.io_bound(KP.sheet_keyword_op, cfg, sheet, "delete", kw)
            if to_kpi:
                for kw in done:
                    r_ = by_kw.get(kw) or {}
                    await run.io_bound(KP.sheet_keyword_op, cfg, sheet, "upsert", kw, r_.get("target_full"),
                                       r_.get("top_n"))
            if is_kpi or to_kpi:
                await run.io_bound(_sync_sheet)
            skipped = res.get("skipped", []) + res.get("exists", []) + res.get("over_budget", [])
            return (f"Đã {'chuyển' if mode == 'move' else 'chép'} {len(done)} từ khóa sang bộ {others[dest]}"
                    + (f"; bỏ qua {len(skipped)} (đã có ở bộ đó hoặc vượt ngân sách)" if skipped else ""))
        small_dialog(f"{'Chuyển' if mode == 'move' else 'Chép'} {len(rows)} từ khóa sang bộ khác", lambda: (
            ui.select(others, value=next(iter(others)), label="Bộ đích").props("outlined dense").classes("w-full"),
            ui.label("Chuyển: giữ nguyên lịch sử rank, từ khóa rời bộ này." if mode == "move" else
                     "Chép: bộ đích check riêng theo nơi check của nó (tốn thêm tiền), lịch sử bắt đầu từ lần check "
                     "đầu ở bộ đó.").classes("text-xs muted"))[0], go,
            "Chuyển" if mode == "move" else "Chép")

    def trash_dialog():
        """Từ khóa đã bỏ theo dõi của bộ này: khôi phục kèm lịch sử."""
        with connect() as c:
            gone = R.keywords(c, site, end, sid, removed=True)
        with ui.dialog() as d, ui.card().style("min-width: 620px; max-width: 94vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label(f"Thùng rác · {cur['name']}").classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=d.close).props("flat round dense")
            ui.label("Từ khóa đã bỏ theo dõi: thôi check, không tính tiền. Khôi phục thì lấy lại cả lịch sử rank"
                     + (" và thêm lại vào sheet cam kết." if is_kpi else ".")).classes("text-sm muted")
            t = ui.table(columns=[
                {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
                {"name": "rank", "label": "Vị trí cuối", "field": "rank", "align": "center"},
                {"name": "at", "label": "Bỏ lúc", "field": "at", "align": "center", "sortable": True},
                {"name": "by", "label": "Người bỏ", "field": "by", "align": "left"},
            ], rows=[{"id": k["id"], "keyword": k["keyword"], "rank": _pos(k["rank"], k["last_depth"]) or "–",
                      "at": _vn(k["removed_at"]), "by": k["removed_by"] or "", "target_full": k["target_url"] or "",
                      "top_n": k.get("top_target")} for k in gone],
                row_key="id", selection="multiple" if ed else "none", pagination=20).classes("w-full").props(
                "flat bordered dense")
            if not gone:
                ui.label("Thùng rác trống.").classes("text-sm muted")

            async def restore():
                from nicegui import run
                if not ed or not t.selected:
                    ui.notify("Tích chọn từ khóa cần khôi phục", type="warning")
                    return
                rows = list(t.selected)
                try:
                    if is_kpi:
                        if not sheet:
                            raise ValueError("Dự án chưa gắn sheet cam kết")
                        for r_ in rows:
                            await run.io_bound(KP.sheet_keyword_op, cfg, sheet, "upsert", r_["keyword"],
                                               r_["target_full"], r_["top_n"])
                    with connect() as c:
                        n = R.restore_keywords(c, site, [r_["id"] for r_ in rows], str(user))
                    if is_kpi:
                        await run.io_bound(_sync_sheet)
                except Exception as ex:  # noqa: BLE001
                    ui.notify(f"Không khôi phục được: {ex}", type="negative", multi_line=True)
                    return
                d.close()
                ui.notify(f"Đã khôi phục {n} từ khóa", type="positive")
                ui.navigate.to(f"/rank?bo={sid}")
            def purge_old():
                if not owner or not t.selected:
                    ui.notify("Tích chọn từ khóa cần xóa", type="warning")
                    return
                with connect() as c:
                    R.purge_keywords(c, site, [r_["id"] for r_ in t.selected], str(user))
                d.close()
                ui.notify(f"Đã xóa vĩnh viễn {len(t.selected)} từ khóa", type="positive")
                ui.navigate.to(f"/rank?bo={sid}")
            if ed and gone:
                with ui.row().classes("w-full justify-end gap-2"):
                    if owner:
                        ui.button("Xóa vĩnh viễn đã chọn", icon="delete_forever", on_click=purge_old).props(
                            "flat no-caps color=negative")
                    ui.button("Khôi phục đã chọn", icon="restore_from_trash", on_click=restore).props(
                        "unelevated no-caps")
        d.open()

    def events_dialog():
        """Mốc sự kiện của bộ này + mốc chung: xem, thêm, xóa."""
        with ui.dialog() as d, ui.card().style("min-width: 560px; max-width: 94vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label("Mốc sự kiện").classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=d.close).props("flat round dense")
            ui.label("Hiện thành vạch tím trên biểu đồ tăng trưởng và biểu đồ từng từ khóa, để biết rank lên / xuống "
                     "sau việc gì.").classes("text-sm muted")
            box = ui.column().classes("w-full gap-0")

            def draw():
                box.clear()
                with connect() as c:
                    evs = R.events(c, site, sid)
                with box:
                    if not evs:
                        ui.label("Chưa có mốc nào.").classes("text-sm muted")
                    for e in reversed(evs):
                        with ui.row().classes("w-full items-center no-wrap gap-3 q-py-xs"):
                            ui.label(_vn(e["day"])).classes("text-sm num").style("width: 96px")
                            ui.label(e["text"]).classes("text-sm col")
                            ui.label("mọi bộ" if e["set_id"] is None else "bộ này").classes("text-xs muted")
                            if ed:
                                ui.button(icon="delete_outline", on_click=lambda i=e["id"]: drop(i)).props(
                                    "flat round dense size=sm color=negative").tooltip("Xóa mốc")

            def drop(i: int):
                with connect() as c:
                    R.delete_event(c, site, i, str(user))
                draw()
                refresh()
            draw()
            if ed:
                ui.separator()
                with ui.row().classes("w-full items-end gap-2"):
                    day_in = ui.input("Ngày", value=f"{date.today():%d/%m/%Y}").props("outlined dense").classes(
                        "w-36")
                    with day_in.add_slot("append"):
                        ui.icon("event").classes("cursor-pointer")
                        with ui.menu():
                            ui.date(mask="DD/MM/YYYY").bind_value(day_in)
                    text_in = ui.input("Nội dung", placeholder="ví dụ: Google core update, đẩy 20 backlink").props(
                        "outlined dense maxlength=120").classes("col")
                scope = ui.toggle({"set": "Chỉ bộ này", "all": "Mọi bộ của website"}, value="set").props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes("sr-seg")

                def add_ev():
                    try:
                        dd, mm, yy = (day_in.value or "").strip().split("/")
                        day = date(int(yy), int(mm), int(dd))
                    except ValueError:
                        ui.notify("Ngày dạng dd/mm/yyyy", type="warning")
                        return
                    try:
                        with connect() as c:
                            R.add_event(c, site, day, text_in.value or "", str(user),
                                        None if scope.value == "all" else sid)
                    except ValueError as ex:
                        ui.notify(str(ex), type="warning")
                        return
                    text_in.value = ""
                    draw()
                    refresh()
                with ui.row().classes("w-full justify-end"):
                    ui.button("Thêm mốc", icon="add", on_click=add_ev).props("unelevated no-caps")
        d.open()

    def export() -> bytes:
        from openpyxl import Workbook

        from . import volume as V
        from .export import INT, _sheet

        wb = Workbook()
        wb.remove(wb.active)
        with connect() as c:
            kws = R.keywords(c, site, end, sid)
            hist = {k["id"]: R.history(c, k["id"]) for k in kws}
            vols = V.latest(c)
            growth = R.set_history(c, site, sid, limit=1000)
        from . import intent as IN
        with connect() as c:
            intents = IN.for_keywords(c, cfg, kws)
        with connect() as c:
            flags = R.serp_flags(c, [k["id"] for k in kws])
        firsts = {kid: hs[0] for kid, hs in hist.items() if hs}  # (ngày, hạng, độ sâu) lần check đầu

        def aio_text(kid):
            a, cited = flags.get(kid, (False, None))
            return "" if not a else ("Có, được trích" if cited else "Có, chưa trích")
        _sheet(wb, "Check rank", [
            ("STT", 6, INT), ("Từ khóa", 34, None), ("Vị trí", 8, None), ("Thay đổi", 18, None),
            ("Vị trí trước", 10, None), ("Tốt nhất", 9, INT), ("Ban đầu", 9, None), ("AI Overview", 15, None),
            ("Ý định chính", 15, None), ("Ý định khác", 26, None), ("Volume/tháng", 12, INT),
            ("Top mục tiêu", 11, None), ("Check lúc", 17, None), ("URL đang xếp hạng", 60, None),
            ("URL mục tiêu", 55, None), ("Đúng URL", 9, None)],
            [[i, k["keyword"], _pos(k["rank"], k["last_depth"]), change_text(k)[0], _pos(k["prev"], k["prev_depth"]),
              k["best"], _pos(firsts[k["id"]][1], firsts[k["id"]][2]) if k["id"] in firsts else "",
              aio_text(k["id"]), *IN.excel_cells(intents.get(k["id"])), (vols.get(k["id"]) or {}).get("volume"),
              f"Top {k['top_target']}" if k.get("top_target") else "",
              _local(k["checked_at"]) if k.get("checked_at") else "", k["ranking_url"] or "", k["target_url"] or "",
              ("Có" if k["ranking_url"] == k["target_url"] else "Không") if k["target_url"] and k["ranking_url"]
              else ""]
             for i, k in enumerate(kws, 1)])
        _sheet(wb, "Tăng trưởng", [("Ngày check", 12, "dd/mm/yyyy"), ("Top 3", 8, INT), ("Top 4–5", 9, INT),
                                   ("Top 6–10", 9, INT), ("Hạng 11+", 10, INT), ("Không thấy (ngoài độ sâu)", 14, INT),
                                   ("Vị trí TB", 10, None), ("Lên", 6, INT), ("Xuống", 7, INT),
                                   ("Đạt Top mục tiêu", 15, None)],
               [[date.fromisoformat(h["date"]), h["top3"], h["top5"], h["top10"], h["top30"], h["out"], h["avg"],
                 h["up"], h["down"], f"{h['target_hit']}/{h['target_total']}" if h["target_total"] else ""]
                for h in growth])
        _sheet(wb, "Lịch sử", [("Từ khóa", 34, None), ("Ngày check", 12, "dd/mm/yyyy"), ("Vị trí", 8, INT),
                               ("Độ sâu", 8, INT)],
               [[k["keyword"], date.fromisoformat(d), r, dep] for k in kws for d, r, dep in hist[k["id"]]])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    refresh()


async def scheduled_checks(base) -> None:
    """Chạy nền trong máy chủ web, mỗi 15 phút: với từng dự án, gửi các từ khóa đến hạn theo lịch (ngày + giờ) của
    bộ chứa nó; không có gì đến hạn mà còn task đang chờ thì chỉ lấy kết quả. Website đang check (bấm tay) thì đợi
    lượt sau. Máy tắt / lỡ giờ: lượt đầu tiên sau khi bật lại check bù."""
    from contextlib import closing
    from datetime import datetime

    from nicegui import run

    from . import db
    from . import projects as PJ

    with closing(db.connect(base.db_path)) as c:
        projects = PJ.list_projects(c)
    for p in projects:
        try:
            cfg = PJ.config_for(base, p)
            site = cfg.site_url
            if site in _RUNNING or cfg.rank.paused:
                continue
            creds = R.load_credentials(cfg.dataforseo_secret)
            if not creds:
                continue

            def connect(cfg=cfg):
                return closing(db.connect(cfg.db_path))

            def find(site=site, connect=connect):
                with connect() as c:
                    R.ensure_tables(c)
                    end = K.latest_date(c, site)
                    todo = R.due(c, site, end, date.today(), datetime.now())
                    waiting = c.execute("SELECT COUNT(*) FROM rank_tasks WHERE status = 'posted'").fetchone()[0]
                return end, todo, waiting
            end, todo, waiting = await run.io_bound(find)
            if not todo:
                if waiting:
                    def pick(site=site, connect=connect, creds=creds):
                        with connect() as c:
                            R.collect(c, site, R.DataForSEO(*creds), lambda *_: None)
                    await run.io_bound(pick)
                continue
            names = list(dict.fromkeys(k["set_name"] for k in todo))
            _RUNNING.add(site)
            _PROGRESS[site] = {"set": ", ".join(names), "total": len(todo), "posted": 0, "done": 0, "failed": 0,
                               "phase": "submit", "stop": False}
            await _check_job(cfg, connect, site, end, [k["id"] for k in todo], creds, None)
        except Exception:  # noqa: BLE001  (một dự án lỗi không chặn dự án khác)
            import traceback
            traceback.print_exc()


async def _publish_one(cfg) -> None:
    from contextlib import closing

    from nicegui import run

    from . import db
    from . import sheet_view as SV

    def work():
        with closing(db.connect(cfg.db_path)) as c:
            return SV.publish_if_changed(c, cfg)
    try:
        await run.io_bound(work)
    except (Exception, SystemExit):  # noqa: BLE001  (lượt định kỳ sau thử lại)
        import traceback
        traceback.print_exc()


async def publish_sheets(base) -> None:
    """Ghi tab xem lên sheet dự án của từng dự án khi dữ liệu đổi (check mới, sửa từ khóa / bộ / KPI)."""
    from contextlib import closing

    from nicegui import run

    from . import db
    from . import projects as PJ
    from . import sheet_view as SV

    with closing(db.connect(base.db_path)) as c:
        projects = PJ.list_projects(c)
    for p in projects:
        cfg = PJ.config_for(base, p)
        if cfg.site_url in _RUNNING:
            continue

        def work(cfg=cfg):
            with closing(db.connect(cfg.db_path)) as c:
                return SV.publish_if_changed(c, cfg)
        try:
            await run.io_bound(work)
        except (Exception, SystemExit):  # noqa: BLE001  (thiếu quyền ghi sheet / mạng: lượt sau thử lại)
            import traceback
            traceback.print_exc()


async def fetch_intents(base) -> None:
    """Lấy ý định tìm kiếm (DataForSEO) cho từ khóa mới của từng dự án: mỗi từ khóa một lần, rất rẻ."""
    from contextlib import closing

    from nicegui import run

    from . import db
    from . import intent as IN
    from . import projects as PJ

    with closing(db.connect(base.db_path)) as c:
        projects = PJ.list_projects(c)
    for p in projects:
        cfg = PJ.config_for(base, p)
        creds = R.load_credentials(cfg.dataforseo_secret)
        if not creds or cfg.site_url in _RUNNING:
            continue

        def work(cfg=cfg, creds=creds):
            with closing(db.connect(cfg.db_path)) as c:
                return IN.fetch_missing(c, cfg, creds, log=lambda *_: None)
        try:
            await run.io_bound(work)
        except Exception:  # noqa: BLE001  (lượt sau thử lại)
            import traceback
            traceback.print_exc()


async def schedule_loop(base) -> None:
    import asyncio
    await asyncio.sleep(60)  # để máy chủ khởi động xong
    while True:
        await scheduled_checks(base)
        await fetch_intents(base)
        await publish_sheets(base)
        await asyncio.sleep(15 * 60)


async def _check_job(cfg, connect, site: str, end, ids: list[int], creds, user: str | None,
                     set_id: int | None = None) -> None:
    """Check rank chạy nền: không phụ thuộc trang đã bấm (trang có thể đã đóng). Gửi DataForSEO từng nhóm
    CHECK_CHUNK từ khóa, ghi tiến độ vào _PROGRESS (đã gửi / đã có kết quả); khi bấm Tạm dừng thì không gửi nhóm tiếp
    theo, thôi chờ kết quả (task đã gửi vẫn được lấy ở lần chạy sau) và lưu từ khóa chưa gửi cho nút Tiếp tục."""
    import time as _time
    from datetime import date as _date

    from nicegui import run

    from . import live as LIVE

    st = _PROGRESS.setdefault(site, {"total": len(ids), "posted": 0, "done": 0, "failed": 0, "phase": "submit",
                                     "stop": False})
    bad_tasks: set[str] = set()  # task DataForSEO trả lỗi khi lấy kết quả (đếm một lần mỗi task)

    def note(logs: list[str]):
        def add(m: str) -> None:
            if m.startswith("Lỗi kết quả task "):
                bad_tasks.add(m.split()[4].rstrip(":"))
                st["failed"] = st.get("post_failed", 0) + len(bad_tasks)
            logs.append(m)
        return add

    def work():
        logs: list[str] = []
        left: list[int] = []
        if cfg.rank.paused:
            return ["Tạm ngưng check rank cho website này: không gửi yêu cầu nào."], left, False
        client = R.DataForSEO(*creds)
        start = R._now()
        with connect() as c:
            R.ensure_tables(c)
            R.collect(c, site, client, note(logs))  # kết quả còn tồn từ lượt trước
            want = set(ids)
            todo = [k for k in R.keywords(c, site, end) if k["id"] in want]
            st["total"] = len(todo)
            st["before"] = {k["id"]: (k["date"], k["rank"]) for k in todo}

            def count(status: str) -> int:  # tính theo dòng từ khóa: task đã gửi + dòng dùng chung kết quả
                return sum(c.execute(f"SELECT COUNT(*) FROM {t} WHERE status = ? AND posted_at >= ?",
                                     (status, start)).fetchone()[0] for t in ("rank_tasks", "rank_task_links"))
            for i in range(0, len(todo), CHECK_CHUNK):
                if st["stop"]:
                    left = [k["id"] for k in todo[i:]]
                    break
                chunk_logs: list[str] = []
                chunk = todo[i:i + CHECK_CHUNK]
                n = R.post(c, site, cfg.rank, client, chunk, _date.today(), chunk_logs.append,
                           by=user or "Lịch")
                logs.extend(m for m in chunk_logs if not m.startswith("Đã gửi"))
                st["posted"] += n
                if any(m.startswith("Dừng") for m in chunk_logs):  # vượt ngân sách: chưa gửi, giữ lại để Tiếp tục
                    left = [k["id"] for k in todo[i:]]
                    break
                st["post_failed"] = st.get("post_failed", 0) + len(chunk) - n  # DataForSEO từ chối nhận
                st["failed"] = st["post_failed"] + len(bad_tasks)
            st["phase"] = "wait"
            deadline = _time.monotonic() + 5 * 60
            while count("posted") > len(bad_tasks) and not st["stop"]:
                R.collect(c, site, client, note(logs))
                st["done"] = count("done")
                if count("posted") <= len(bad_tasks):
                    break
                if _time.monotonic() > deadline:
                    logs.append("Còn từ khóa chưa có kết quả, lần chạy sau sẽ lấy tiếp.")
                    break
                for _ in range(2):  # hỏi lại sau 10 giây (thanh tiến độ chạy đều), thấy Tạm dừng thì thôi ngay
                    if st["stop"]:
                        break
                    _time.sleep(5)
            st["done"] = count("done")
            waiting = count("posted")
        if st["stop"] and waiting:
            logs.append(f"{waiting} từ khóa đã gửi sẽ có kết quả ở lần chạy sau.")
        return logs, left, st["stop"]
    try:
        logs, left, stopped = await run.io_bound(work)
        if left and set_id is not None:
            _PAUSED[(site, set_id)] = left
        logs = list(dict.fromkeys(m for m in logs if not m.startswith("Lỗi kết quả task ")))
        done, total, failed = st["done"], st["total"], st.get("failed", 0)
        waiting = max(st["posted"] - done - failed, 0)
        budget = any(m.startswith("Dừng") for m in logs)
        if budget:
            head, kind = f"Dừng gửi vì vượt ngân sách · {done}/{total} có kết quả", "warning"
        elif stopped:
            head, kind = f"Đã dừng gửi · {done}/{total} có kết quả", "warning"
        elif failed or waiting:
            head, kind = f"Xong một phần · {done}/{total} có kết quả", "warning"
        else:
            head, kind = f"Xong · {done}/{total} từ khóa có kết quả", "positive"
        bits = []
        try:  # so với số trước khi check: để biết lượt này có làm thay đổi gì không
            with connect() as c:
                after = {k["id"]: (k["date"], k["rank"]) for k in R.keywords(c, site, end)
                         if k["id"] in st.get("before", {})}
            got = [kid for kid, v in after.items() if v[0] == _date.today().isoformat()]
            moved = sum(1 for kid in got if st["before"][kid][1] != after[kid][1])
            if got:
                bits.append(f"{moved} từ khóa đổi hạng" if moved else "Hạng không đổi so với số trước khi check")
        except Exception:  # noqa: BLE001
            pass
        if failed:
            bits.append(f"{failed} lỗi")
        if waiting:
            bits.append(f"{waiting} đang chờ, lấy ở lần chạy sau")
        if left:
            bits.append(f"{len(left)} chưa gửi (không tốn phí), bấm Tiếp tục")
        bits += [m for m in logs if m.startswith(("Không gửi được", "Dừng"))]
        if user is None:  # chạy theo lịch: không ai bấm, không báo
            return
        LIVE.notify(user, f"Check rank {domain(site)}: {head}", caption=" · ".join(bits) or None, type=kind,
                    position="bottom-right", classes="sr-toast", timeout=0 if kind != "positive" else 8000,
                    close_button="Đóng" if kind != "positive" else None)
    except Exception as e:  # noqa: BLE001
        sent = st.get("posted", 0)
        if user is None:
            import traceback
            traceback.print_exc()
            return
        LIVE.notify(user, f"Check rank {domain(site)} bị lỗi",
                    caption=str(e)[:200] + (f" · {sent} từ khóa đã gửi sẽ lấy kết quả ở lần chạy sau" if sent else ""),
                    type="negative",
                    position="bottom-right", classes="sr-toast", timeout=0, close_button="Đóng")
    finally:
        _RUNNING.discard(site)
        _PROGRESS.pop(site, None)
        from nicegui import background_tasks
        background_tasks.create(_publish_one(cfg))  # ghi kết quả mới lên sheet dự án (nơi xem)
        from nicegui import Client
        for cid, fn in list(_VIEWS.get(site, {}).items()):
            client = Client.instances.get(cid)
            if client is None:
                continue
            try:
                with client:
                    fn()
            except Exception:  # noqa: BLE001  (trang vừa đóng)
                pass
