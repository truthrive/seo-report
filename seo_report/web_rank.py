"""Màn Từ khóa & rank: mỗi bộ từ khóa một tab (bộ Cam kết theo sheet + các bộ team tạo), mỗi bộ nơi check / lịch
riêng. Trong một bộ: thêm / sửa (Top mục tiêu, URL mục tiêu) / bỏ từ khóa, check ngay, biểu đồ tăng trưởng, phân bố vị
trí, bảng và lịch sử từng từ khóa. Sửa từ khóa ở bộ Cam kết thì tool ghi thẳng lên tab Từ khóa cam kết của sheet."""
import io
from datetime import date

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


def _pos(rank, depth) -> str:
    if depth is None:
        return ""
    return str(rank) if rank is not None else f">{depth}"


# Check ngay chạy nền phía server, không gắn với trang đã bấm: đổi trang / đóng tab vẫn check tiếp, xong thì báo trên
# trang người bấm đang mở và làm mới bảng ở mọi trang Từ khóa & rank của website đó.
_RUNNING: set[str] = set()  # website đang check
_VIEWS: dict[str, dict[str, object]] = {}  # website → {client id: hàm làm mới bảng}

SOURCES = {"kpi": "Cam kết", "manual": "Nhập tay", "gsc": "Từ GSC (★)"}
TOPS = [1, 3, 5, 10, 20, 30]

# Bộ lọc bảng: (tên, điều kiện trên một dòng của rank.keywords)
FILTERS = {
    "all": ("Tất cả", lambda k: True),
    "top3": ("Top 3", lambda k: k["rank"] is not None and k["rank"] <= 3),
    "top10": ("Top 4–10", lambda k: k["rank"] is not None and 3 < k["rank"] <= 10),
    "top30": ("Top 11–30", lambda k: k["rank"] is not None and 10 < k["rank"] <= 30),
    "out": ("Ngoài top 30 / ngoài độ sâu", lambda k: k["date"] and (k["rank"] is None or k["rank"] > 30)),
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

RANK_TONES = [(3, ("#E7F3EA", "#1E7C31")), (10, ("#F2F7DC", "#5E7414")), (30, ("#FBF1DE", "#B7791F"))]


def change_text(k: dict) -> tuple[str, str, int]:
    from .report import rank_change
    return rank_change(k["date"], k["rank"], k["last_depth"], k["prev"], k["prev_depth"])


def event_marks(hist: list[dict], evs: list[dict]) -> dict:
    """Mốc sự kiện thành vạch dọc trên biểu đồ tăng trưởng: đặt ở lần check đầu tiên từ ngày sự kiện trở đi (trục là
    các ngày check). Mốc sau lần check cuối thì chưa vẽ."""
    labels: dict[str, list[str]] = {}
    for e in evs:
        h = next((h for h in hist if h["date"] >= e["day"]), None)
        if h:
            labels.setdefault(_vn(h["date"])[:5], []).append(f"{_vn(e['day'])[:5]} {e['text']}")
    if not labels:
        return {}
    return {"markLine": {"symbol": "none", "silent": True, "animation": False,
                         "lineStyle": {"color": "#7C3AED", "type": "dashed", "width": 1},
                         "label": {"position": "insideEndTop", "color": "#5B21B6", "fontSize": 10,
                                   "overflow": "truncate", "width": 140},
                         "data": [{"xAxis": x, "label": {"formatter": " · ".join(t)}} for x, t in labels.items()]}}


def growth_charts(ui, hist: list[dict], evs: list[dict] | None = None, on_events=None) -> None:
    """Tăng trưởng của bộ qua các lần check (như SERPRobot), mỗi biểu đồ một trục: trái: số từ khóa theo nhóm Top
    (cột chồng); phải: số từ khóa lên / xuống hạng so với lần check trước. Vị trí trung bình và % đạt mục tiêu nằm ở
    hàng ô số phía trên (không ghép trục thứ hai: hai thang đo canh tùy ý dễ đọc nhầm). evs: mốc sự kiện (vạch tím)."""
    from . import ui_theme as T
    x = [_vn(h["date"])[:5] for h in hist]
    marks = event_marks(hist, evs or [])
    bar = {"barMaxWidth": 22, "barCategoryGap": "45%"}
    gap = {"borderColor": "#FFFFFF", "borderWidth": 1}  # khe giữa các đoạn cột
    base = {"animation": False, "grid": {"left": 34, "right": 12, "top": 30, "bottom": 24},
            "legend": {"top": 0, "left": 0, "itemWidth": 10, "itemHeight": 10, "icon": "roundRect",
                       "textStyle": {"fontSize": 11, "color": "#6B6A5E"}},
            "tooltip": {"trigger": "axis", "confine": True, "axisPointer": {"type": "shadow",
                                                                          "shadowStyle": {"color": "rgba(0,0,0,.03)"}}},
            "xAxis": {"type": "category", "data": x, "axisTick": {"show": False},
                      "axisLabel": {"color": "#8C8A7E", "fontSize": 10.5},
                      "axisLine": {"lineStyle": {"color": "#E7E5DC"}}},
            "yAxis": {"type": "value", "minInterval": 1, "splitLine": {"lineStyle": {"color": "#F0EEE6"}},
                      "axisLabel": {"color": "#8C8A7E", "fontSize": 10.5}}}
    bands = [("Top 3", "top3", "#1E7C31"), ("Top 4–10", "top10", "#9BB823"), ("Top 11–30", "top30", "#D9A441"),
             ("Ngoài top 30", "out", "#D6D4CA")]
    with ui.element("div").classes("sr-card q-pa-md w-full"):
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.label("Tăng trưởng của bộ").classes("sr-section-title")
            T.info_icon(ui, "Tăng trưởng của bộ", (
                "Mỗi cột là một ngày check của bộ này.",
                "Trái: cột xanh đậm (Top 3) cao dần là bộ đang lên. Phải: số từ khóa lên hạng (xanh) và xuống hạng "
                "(đỏ) so với lần check trước.",
                "Mỗi ngày lấy lần check gần nhất của từng từ khóa. Vạch tím là mốc sự kiện."))
            ui.space()
            if on_events:
                ui.button(f"Mốc sự kiện · {len(evs)}" if evs else "Mốc sự kiện", icon="flag",
                          on_click=on_events).props("flat dense no-caps color=deep-purple-7").tooltip(
                    "Đánh dấu Google update, đẩy backlink, viết lại bài… lên biểu đồ")
        if len(hist) < 2:
            ui.label("Biểu đồ hiện khi bộ có từ 2 ngày check trở lên.").classes("text-sm muted q-py-md")
            return
        with ui.element("div").classes("w-full").style(
                "display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px"):
            with ui.column().classes("gap-0"):
                ui.label("Số từ khóa theo nhóm Top").classes("text-xs muted")
                ui.echart({**base, "series": [
                    {"type": "bar", "stack": "top", "name": n, "data": [h[k] for h in hist], **bar,
                     "itemStyle": {"color": c, **gap}, **(marks if i == 0 else {})}
                    for i, (n, k, c) in enumerate(bands)]}).classes("w-full").style("height: 240px")
            with ui.column().classes("gap-0"):
                ui.label("Lên / xuống hạng so với lần check trước").classes("text-xs muted")
                ui.echart({**base, "tooltip": {**base["tooltip"], ":valueFormatter": "v => Math.abs(v)"},
                           "series": [{"type": "bar", "stack": "move", "name": "Lên hạng",
                                       "data": [h["up"] for h in hist], **bar,
                                       "itemStyle": {"color": "#1E7C31", "borderRadius": [3, 3, 0, 0]}, **marks},
                                      {"type": "bar", "stack": "move", "name": "Xuống hạng",
                                       "data": [-h["down"] for h in hist], **bar,
                                       "itemStyle": {"color": "#C2410C", "borderRadius": [0, 0, 3, 3]}}]}).classes(
                    "w-full").style("height: 240px")


def build_rank_page(ui, cfg, connect, user: str, on_budget_change=None, set_id: int | None = None) -> None:
    """set_id: bộ (tab) đang mở; không có / không còn thì mở bộ đầu tiên."""
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
    cur = next((x for x in all_sets if x["id"] == set_id), all_sets[0])
    sid, is_kpi = cur["id"], cur["kind"] == "kpi"
    sched = cur["schedule"]
    where = R.settings_for(cfg.rank, cur)

    right = T.page_header(ui, "leaderboard", "Từ khóa & rank", "Vị trí thật trên Google của từng bộ từ khóa.")
    with right:
        if cfg.rank.paused:
            T.status_chip(ui, "Đang tạm ngưng check rank", "amber", "pause_circle")
        if ed:
            ui.button("Thêm keyword", icon="add", on_click=lambda: add_dialog.open()).props("outline no-caps")
            check_btn = ui.button("Check ngay", icon="play_arrow", on_click=lambda: check_now()).props(
                "unelevated no-caps").tooltip("Check các keyword đã tích chọn trong bộ này, hoặc cả bộ nếu không "
                                              "chọn gì. Đổi trang vẫn check tiếp, xong sẽ báo")
            if site in _RUNNING:
                check_btn.props("loading")
            if cfg.rank.paused:  # tạm ngưng: không gửi yêu cầu DataForSEO nào; quản trị bật lại ở màn Ngân sách
                check_btn.disable()
                check_btn.tooltip("Website đang tạm ngưng check rank. Quản trị bật lại ở màn Ngân sách check rank")
        from .web_export import export_menu
        export_menu(ui, cfg, connect, f"check-rank_{cur['name']}_{date.today():%Y-%m-%d}", lambda: export(),
                    user=user)

    # ---- Tab: mỗi bộ một tab ----
    with ui.row().classes("w-full items-end no-wrap gap-2"):
        with ui.tabs(value=sid, on_change=lambda e: ui.navigate.to(f"/rank?bo={e.value}")).classes(
                "sr-tabs col").props("align=left no-caps dense inline-label outside-arrows mobile-arrows"):
            for x in all_sets:
                ui.tab(x["id"], label=f"{x['name']} · {x['count']}",
                       icon="pause_circle" if x["paused"] else "verified" if x["kind"] == "kpi" else None)
        if ed:
            ui.button("Bộ mới", icon="add", on_click=lambda: set_dialog(None)).props("flat dense no-caps")

    # ---- Bộ đang mở: nơi check, lịch, số từ khóa, chi phí ----
    with ui.element("div").classes("sr-card q-px-md q-py-sm w-full"):
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['green'][0]}"):
                ui.icon("verified" if is_kpi else "folder_open", size="18px").style(f"color:{T.GREEN}")
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label(R.describe_target(where) + (" (theo dự án)" if not cur["settings"] else "")).classes(
                    "text-sm font-medium ellipsis")
                schedule_label = ui.label().classes("text-xs muted ellipsis")
            if is_kpi:
                with ui.element("span").tooltip("Bộ này khớp tab Từ khóa cam kết của sheet dự án; thêm / sửa / bỏ "
                                                "ở đây thì tool ghi lên sheet"):
                    T.status_chip(ui, "Theo sheet cam kết", "green", "sync")
            if cur["paused"]:
                T.status_chip(ui, "Bộ đang tạm dừng: không check, không tính tiền", "amber", "pause_circle")
            if ed:
                ui.button("Cài đặt bộ", icon="tune", on_click=lambda: set_dialog(cur)).props("flat no-caps")
                if not is_kpi:
                    ui.button(icon="delete_outline", on_click=lambda: confirm_delete.open()).props(
                        "flat round dense color=negative").tooltip("Xóa bộ này")

    with ui.dialog() as confirm_delete, ui.card().style("max-width: 440px; border-radius: 14px"):
        ui.label(f"Xóa bộ “{cur['name']}”?").classes("text-lg font-semibold")
        ui.label(f"{cur['count']} từ khóa trong bộ sẽ thôi được check. Lịch sử rank vẫn giữ trong file dữ liệu; từ khóa "
                 "nằm ở bộ khác không bị ảnh hưởng.").classes("text-sm")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Hủy", on_click=confirm_delete.close).props("flat no-caps")

            def do_delete():
                if not ed:
                    return
                with connect() as c:
                    R.delete_set(c, sid, str(user))
                ui.navigate.to("/rank")
            ui.button("Xóa bộ", icon="delete", on_click=do_delete).props("unelevated no-caps color=negative")

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
            if st and st["kind"] == "kpi":
                name.disable()
                name.tooltip("Bộ Cam kết giữ tên, đi theo sheet dự án")
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
                             value=sc["type"]).props("no-caps unelevated toggle-color=primary")
            days_box = ui.row().classes("gap-1")
            with days_box:
                day_checks = [ui.chip(n.replace("Thứ ", "T").replace("Chủ nhật", "CN"), selectable=True,
                                      selected=i in sc["weekdays"]).props("outline color=primary")
                              for i, n in enumerate(R.WEEKDAYS)]
            month_day = ui.number("Ngày trong tháng", value=sc["day"], min=1, max=31, step=1, format="%d").props(
                "dense outlined").classes("w-40")
            depth = ui.select({x: ("Tự động" if x == "auto" else f"Top {x}") for x in R.DEPTHS}, value=sc["depth"],
                              label="Độ sâu check").props("dense outlined").classes("w-48")
            ui.label("Tự động: lần đầu check top 30; sau đó theo vị trí lần trước (≤ 8 → top 10, ≤ 18 → top 20, còn "
                     "lại top 30). Check sâu hơn tốn tiền hơn.").classes("text-xs muted")
            if st:
                ui.label("Đổi nơi check thì các lần check sau có thể lệch so với trước (Google trả kết quả khác theo "
                         "nơi tìm), không phải do website lên / xuống hạng.").classes("text-xs").style(
                    f"color:{T.AMBER_TEXT}")

            pause_sw = ui.switch("Tạm dừng cả bộ (không check, không tính tiền; lịch sử vẫn giữ)",
                                 value=bool((st or {}).get("paused"))).props("dense") if st else None

            def view():
                days_box.set_visibility(kind.value == "weekdays")
                month_day.set_visibility(kind.value == "monthly")
            kind.on_value_change(lambda _: view())
            view()

            def save():
                s_new = {"type": kind.value, "weekdays": [i for i, cb in enumerate(day_checks) if cb.selected],
                         "day": int(month_day.value or 1), "depth": depth.value}
                if s_new["type"] == "weekdays" and not s_new["weekdays"]:
                    ui.notify("Chọn ít nhất một thứ trong tuần", type="warning")
                    return
                settings = None if follow.value else {"se_domain": t_domain.value, "device": t_device.value,
                                                      "location_code": t_loc.value, "language_code": t_lang.value}
                try:
                    with connect() as c:
                        if st:
                            R.update_set(c, st["id"], str(user), name=name.value, settings=settings,
                                         schedule=s_new, paused=pause_sw.value)
                            new_id = st["id"]
                        else:
                            new_id = R.create_set(c, site, name.value, str(user), settings=settings,
                                                  schedule=s_new)
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

    # ---- Hàng ô số (lần check mới nhất, so với lần trước) rồi biểu đồ tăng trưởng ----
    kpi_box = ui.element("div").classes("w-full")
    growth_box = ui.column().classes("w-full gap-2")

    def draw_kpis(kws, hist, vols):
        kpi_box.clear()
        checked = [k for k in kws if k["date"]]
        vol_all = sum((vols.get(k["id"]) or {}).get("volume") or 0 for k in kws)
        last, prev = (hist[-1] if hist else None), (hist[-2] if len(hist) > 1 else None)
        labels = [_vn(h["date"])[:5] for h in hist]

        def diff(key, better_low=False, digits=0):
            if not last or not prev or last.get(key) is None or prev.get(key) is None:
                return "", None
            d = round(last[key] - prev[key], digits)
            if not d:
                return "giữ nguyên", None
            text = (f"{d:+.{digits}f}" if digits else f"{d:+d}").replace("-", "−").replace(".", ",")
            return text + " so với lần trước", (d < 0) if better_low else (d > 0)

        def pct(h):
            return h["target_hit"] / h["target_total"] if h["target_total"] else None
        top10 = [h["top3"] + h["top10"] for h in hist]
        with kpi_box, T.kpi_row(ui):
            T.kpi(ui, "format_list_numbered", "Từ khóa theo dõi", str(len(kws)), hint=(
                f"{len(checked)} đã check" + (f" · {vol_all:,} lượt tìm/tháng".replace(",", ".") if vol_all else "")),
                  tone="grey", spark=[])
            t3, g3 = diff("top3")
            T.kpi(ui, "emoji_events", "Top 3", str(last["top3"]) if last else "–", t3, g3,
                  f"trên {last['checked']} từ khóa đã check" if last else "chưa check", spark=[h["top3"] for h in hist],
                  spark_labels=labels, spark_kind="line", tone="green")
            if last:
                last["t10"] = top10[-1]
                if prev:
                    prev["t10"] = top10[-2]
            t10, g10 = diff("t10")
            T.kpi(ui, "military_tech", "Trong top 10", str(top10[-1]) if hist else "–", t10, g10,
                  f"trên {last['checked']} từ khóa đã check" if last else "chưa check", spark=top10,
                  spark_labels=labels, spark_kind="line", tone="lime")
            ta, ga = diff("avg", better_low=True, digits=1)
            T.kpi(ui, "trending_up", "Vị trí trung bình",
                  f"{last['avg']:.1f}".replace(".", ",") if last and last["avg"] is not None else "–", ta, ga,
                  "số nhỏ hơn là tốt hơn", spark=[h["avg"] for h in hist], spark_labels=labels, spark_kind="line",
                  tone="blue")
            hits = [pct(h) for h in hist]
            if last and prev and hits[-1] is not None and hits[-2] is not None:
                d = round((hits[-1] - hits[-2]) * 100)
                tt, gt = ((f"{d:+d} điểm % so với lần trước".replace("-", "−"), d > 0) if d else ("giữ nguyên", None))
            else:
                tt, gt = "", None
            T.kpi(ui, "flag", "Đạt Top mục tiêu",
                  f"{last['target_hit']}/{last['target_total']}" if last and last["target_total"] else "–", tt, gt,
                  (f"{hits[-1] * 100:.0f}% từ khóa có Top mục tiêu" if hist and hits[-1] is not None
                   else "chưa đặt Top mục tiêu"), spark=[h for h in hits], spark_labels=labels, spark_kind="line",
                  spark_fmt="pct", tone="amber")

    # ---- Bảng: tìm, lọc, thùng rác; chọn nhiều thì hiện thanh thao tác hàng loạt ----
    with ui.row().classes("w-full items-center gap-2 q-mt-sm"):
        ui.label(f"Danh sách keyword · {cur['name']}").classes("sr-section-title")
        ui.space()
        search = ui.input(placeholder="Tìm từ khóa, URL, ghi chú…").props("dense outlined clearable").classes(
            "w-64")
        search.props["prepend-icon"] = "search"
        filt = ui.select({k: v[0] for k, v in FILTERS.items()}, value="all", label="Lọc",
                         on_change=lambda: refresh()).props("dense outlined options-dense").classes("w-56")
        trash_btn = ui.button("Thùng rác", icon="delete_sweep", on_click=lambda: trash_dialog()).props(
            "flat dense no-caps color=grey-8")
    wrong_box = ui.row().classes("w-full")
    selection_bar = ui.row().classes("w-full items-center gap-2 sr-bulk-bar")
    with selection_bar:
        selected_label = ui.label().classes("text-sm font-medium")
        if ed:
            ui.button("Check", icon="play_arrow", on_click=lambda: check_now()).props("flat dense no-caps")
            with ui.button("Sửa hàng loạt", icon="edit_note").props("flat dense no-caps"):
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
            ui.button("Bỏ theo dõi", icon="delete_outline", on_click=lambda: remove()).props(
                "flat dense no-caps color=negative")
        ui.space()
        ui.button("Bỏ chọn", on_click=lambda: (table.selected.clear(), table.update(), on_select())).props(
            "flat dense no-caps color=grey-8")
    selection_bar.set_visibility(False)
    cols = [
        {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
        {"name": "top", "label": "Top mục tiêu", "field": "top", "align": "center", "sortable": True,
         ":sort": "(a, b, rowA, rowB) => (rowA.top_n || 999) - (rowB.top_n || 999)"},
        {"name": "volume", "label": "Volume", "field": "volume", "align": "right", "sortable": True,
         ":format": "v => v === null || v === undefined ? 'chờ lấy' : (v < 0 ? '< 10' : v.toLocaleString('vi-VN'))"},
        {"name": "pos", "label": "Vị trí", "field": "pos", "align": "center", "sortable": True,
         ":sort": "(a, b, rowA, rowB) => rowA.sort_pos - rowB.sort_pos"},
        {"name": "change", "label": "Thay đổi", "field": "change", "align": "center", "sortable": True,
         ":sort": "(a, b, rowA, rowB) => rowA.move - rowB.move"},
        {"name": "link", "label": "URL đang xếp hạng", "field": "link", "align": "left"},
        {"name": "chart", "label": "", "field": "id", "align": "center"},
    ]
    if not is_kpi:
        cols.insert(1, {"name": "source", "label": "Nguồn", "field": "source", "align": "left", "sortable": True})
    table = ui.table(columns=cols, rows=[], row_key="id", selection="multiple" if ed else "none",
                     pagination=50).classes("w-full").props("flat bordered dense")
    search.bind_value(table, "filter")
    table.add_slot("body-cell-keyword", """
        <q-td :props="props">
          <div class="row no-wrap items-center" style="gap: 4px">
            <span :style="{opacity: props.row.paused ? 0.55 : 1}">{{ props.value }}</span>
            <q-icon v-if="props.row.note" name="sticky_note_2" size="15px" color="amber-8">
              <q-tooltip max-width="320px">{{ props.row.note }}</q-tooltip></q-icon>
          </div>
        </q-td>""")
    table.add_slot("body-cell-pos", """
        <q-td :props="props" class="text-center">
          <q-chip v-if="props.row.paused" dense square icon="pause" color="grey-3" text-color="grey-8"
                  size="sm">tạm dừng</q-chip>
          <span v-else-if="props.row.checked" :style="{background: props.row.bg, color: props.row.fg, borderRadius: '6px',
                padding: '2px 8px', fontWeight: 700}">{{ props.value }}</span>
          <span v-else class="muted">chờ check</span>
        </q-td>""")
    table.add_slot("body-cell-top", """
        <q-td :props="props" class="text-center">
          <span v-if="props.value" :style="{fontWeight: 600, color: props.row.top_hit ? '#1E7C31' : 'inherit'}">
            {{ props.value }}<q-icon v-if="props.row.top_hit" name="check" size="14px" class="q-ml-xs" /></span>
          <span v-else class="muted">–</span>
        </q-td>""")
    table.add_slot("body-cell-change", """
        <q-td :props="props" class="text-center">
          <span :style="{color: props.row.change_color, fontWeight: 600, whiteSpace: 'nowrap'}">{{ props.value }}</span>
        </q-td>""")
    table.add_slot("body-cell-link", """
        <q-td :props="props">
          <div class="row no-wrap items-center" style="gap: 6px; max-width: 360px">
            <q-icon v-if="props.row.wrong" name="warning" color="orange-8" size="16px">
              <q-tooltip>Google đang xếp hạng URL khác URL mục tiêu<br/>Mục tiêu: {{ props.row.target_full }}
                (vị trí {{ props.row.target_pos }})</q-tooltip></q-icon>
            <q-icon v-else-if="props.row.target_full && props.row.link_full" name="check_circle" color="green-8"
                    size="16px"><q-tooltip>Đúng URL mục tiêu</q-tooltip></q-icon>
            <a v-if="props.row.link_full" :href="props.row.link_full" target="_blank" rel="noopener"
               :title="props.row.link_full" class="ellipsis" style="color: inherit; text-decoration: none; min-width: 0">
              {{ props.value }}</a>
            <span v-else-if="props.row.target_full" class="muted ellipsis" :title="props.row.target_full">
              mục tiêu: {{ props.row.target }}</span>
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

    def on_select(_=None):
        n = len(table.selected)
        selection_bar.set_visibility(n > 0)
        selected_label.text = f"Đã chọn {n}"

    table.on_select(on_select)

    def show_chart(e):
        """Lịch sử một từ khóa: biểu đồ vị trí, danh sách các lần check (Chủ tool xóa được lần check sai), nhật ký."""
        row = e.args
        with connect() as c:
            hist = R.history(c, row["id"])
            log = R.keyword_log(c, site, row["keyword"])
            evs = R.events(c, site, sid)
        with ui.dialog() as d, ui.card().style("min-width: 680px; max-width: 94vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label(f"Lịch sử: {row['keyword']}").classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=d.close).props("flat round dense")
            with ui.tabs().classes("w-full sr-tabs").props("align=left no-caps dense inline-label") as tabs:
                t1 = ui.tab("Vị trí", icon="show_chart")
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
            n_trash = len(R.keywords(c, site, end, sid, removed=True))
        trash_btn.text = f"Thùng rác · {n_trash}" if n_trash else "Thùng rác"
        keep = FILTERS.get(filt.value, FILTERS["all"])[1]
        rows = []
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
                "date": _vn(k["date"])[:5], "link": short(k["ranking_url"]), "link_full": k["ranking_url"] or "",
                "target": short(k["target_url"]), "target_full": k["target_url"] or "",
                "wrong": bool(k["target_url"] and k["ranking_url"] and k["ranking_url"] != k["target_url"]),
                "target_pos": _pos(k["target_rank"], k["last_depth"]),
                "can_edit": ed and (not is_kpi or bool(sheet)),
                "paused": k["paused"], "own_paused": k["own_paused"], "note": k["note"],
            })
        table.rows = rows
        table.selected = []
        on_select()
        draw_kpis(kws, hist, vols)
        growth_box.clear()
        with growth_box:
            growth_charts(ui, hist, evs, on_events=lambda: events_dialog())
        wrong = sum(1 for k in kws if k["target_url"] and k["ranking_url"] and k["ranking_url"] != k["target_url"])
        wrong_box.clear()
        if wrong and filt.value != "wrong":
            with wrong_box:
                ui.button(f"{wrong} từ khóa Google đang xếp hạng URL khác URL mục tiêu: xem", icon="warning",
                          on_click=lambda: filt.set_value("wrong")).props(
                    "flat dense no-caps color=orange-9 size=sm")
        with connect() as c:
            est = R.estimate(c, cfg.rank, sched, [k["depth"] for k in kws])
        schedule_label.text = (f"{R.describe_schedule(sched)} · {len(kws)} keyword · ước tính {R.usd(est)} "
                               "USD/tháng cho bộ này")
        if on_budget_change:
            on_budget_change()

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
            parts.append(f"KHÔNG thêm {len(r['over_budget'])} keyword vì vượt ngân sách: {', '.join(r['over_budget'][:5])}")
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

    async def remove():
        if not ed:  # chặn ở server: nút bị ẩn chưa đủ, sự kiện vẫn gửi được từ trình duyệt
            return
        from nicegui import run
        if not table.selected:
            ui.notify("Tích chọn keyword cần bỏ", type="warning")
            return
        picked = list(table.selected)
        if is_kpi:  # bộ Cam kết: xóa dòng trên sheet, rồi bỏ khỏi tool (không chuyển sang Ngoài cam kết)
            if not sheet:
                ui.notify("Dự án chưa gắn sheet cam kết", type="warning")
                return
            try:
                for r_ in picked:
                    await run.io_bound(KP.sheet_keyword_op, cfg, sheet, "delete", r_["keyword"])
            except Exception as e:  # noqa: BLE001
                ui.notify(f"Không ghi được lên sheet: {e}", type="negative", multi_line=True)
                return
        with connect() as c:
            R.remove_keywords(c, site, [r_["id"] for r_ in picked], str(user))
        if is_kpi:
            try:
                await run.io_bound(_sync_sheet)
            except Exception:  # noqa: BLE001  (đã xóa trên sheet; lần đồng bộ sau đọc lại)
                pass
        ui.notify(f"Đã bỏ theo dõi {len(picked)} keyword (lịch sử vẫn được giữ)"
                  + ("; đã xóa khỏi sheet cam kết" if is_kpi else ""), type="positive")
        ui.navigate.to(f"/rank?bo={sid}")

    async def check_now():
        if not ed:  # chặn ở server: nút bị ẩn chưa đủ, sự kiện vẫn gửi được từ trình duyệt
            return
        from nicegui import background_tasks

        if site in _RUNNING:
            ui.notify("Đang check rank cho website này, xong sẽ báo.", type="info")
            return
        ids = [r_["id"] for r_ in table.selected] or [r_["id"] for r_ in table.rows if not r_["paused"]]
        if not ids:
            return
        creds = R.load_credentials(cfg.dataforseo_secret)
        if not creds:
            ui.notify(f"Chưa có API key DataForSEO trong {cfg.dataforseo_secret}", type="negative")
            return
        _RUNNING.add(site)
        check_btn.props("loading")
        ui.notify(f"Đã bắt đầu check {len(ids)} keyword của bộ {cur['name']}. Có thể sang trang khác, xong tool sẽ "
                  "báo.", type="info")
        background_tasks.create(_check_job(cfg, connect, site, end, ids, creds, str(user)))

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
            if ed and gone:
                with ui.row().classes("w-full justify-end"):
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
                    "no-caps dense unelevated toggle-color=primary")

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
        _sheet(wb, "Check rank", [
            ("STT", 6, INT), ("Từ khóa", 34, None), ("Top mục tiêu", 10, None), ("Volume/tháng", 12, INT),
            ("Vị trí", 8, None), ("Vị trí cũ", 9, None), ("Thay đổi", 18, None), ("Vị trí tốt nhất", 12, INT),
            ("Cập nhật", 12, None), ("Liên kết", 60, None), ("URL mục tiêu", 55, None), ("Đúng URL", 9, None)],
            [[i, k["keyword"], f"Top {k['top_target']}" if k.get("top_target") else "",
              (vols.get(k["id"]) or {}).get("volume"), _pos(k["rank"], k["last_depth"]),
              _pos(k["prev"], k["prev_depth"]), change_text(k)[0], k["best"], _vn(k["date"]), k["ranking_url"] or "",
              k["target_url"] or "",
              ("Có" if k["ranking_url"] == k["target_url"] else "Không") if k["target_url"] and k["ranking_url"] else ""]
             for i, k in enumerate(kws, 1)])
        _sheet(wb, "Tăng trưởng", [("Ngày check", 12, "dd/mm/yyyy"), ("Top 3", 8, INT), ("Top 4–10", 9, INT),
                                   ("Top 11–30", 10, INT), ("Ngoài top 30", 12, INT), ("Vị trí TB", 10, None),
                                   ("Lên", 6, INT), ("Xuống", 7, INT), ("Đạt Top mục tiêu", 15, None)],
               [[date.fromisoformat(h["date"]), h["top3"], h["top10"], h["top30"], h["out"], h["avg"], h["up"],
                 h["down"], f"{h['target_hit']}/{h['target_total']}" if h["target_total"] else ""] for h in growth])
        _sheet(wb, "Lịch sử", [("Từ khóa", 34, None), ("Ngày check", 12, "dd/mm/yyyy"), ("Vị trí", 8, INT),
                               ("Độ sâu", 8, INT)],
               [[k["keyword"], date.fromisoformat(d), r, dep] for k in kws for d, r, dep in hist[k["id"]]])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    refresh()


async def _check_job(cfg, connect, site: str, end, ids: list[int], creds, user: str) -> None:
    """Check rank chạy nền: không phụ thuộc trang đã bấm (trang có thể đã đóng)."""
    from nicegui import run

    from . import live as LIVE

    def work():
        logs = []
        with connect() as c:
            R.run(c, site, cfg.rank, R.DataForSEO(*creds), end, only_ids=ids, wait_minutes=5, log=logs.append)
        return logs
    try:
        logs = await run.io_bound(work)
        failed = any(m.startswith(("Không gửi được", "Dừng")) for m in logs)
        LIVE.notify(user, f"Check rank {domain(site)}: " + (" ".join(logs) or "không có keyword nào được gửi"),
                    type="warning" if failed else "positive", multi_line=True, timeout=0 if failed else 10000,
                    close_button="Đóng" if failed else None)
    except Exception as e:  # noqa: BLE001
        LIVE.notify(user, f"Check rank {domain(site)} thất bại: {e}", type="negative", multi_line=True,
                    timeout=0, close_button="Đóng")
    finally:
        _RUNNING.discard(site)
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
