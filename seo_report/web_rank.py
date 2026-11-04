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

RANK_TONES = [(3, ("#E7F3EA", "#1E7C31")), (10, ("#F2F7DC", "#5E7414")), (30, ("#FBF1DE", "#B7791F"))]


def change_text(k: dict) -> tuple[str, str, int]:
    from .report import rank_change
    return rank_change(k["date"], k["rank"], k["last_depth"], k["prev"], k["prev_depth"])


def growth_charts(ui, hist: list[dict]) -> None:
    """Tăng trưởng của bộ qua các lần check (như SERPRobot): trái: số từ khóa theo nhóm Top (cột chồng) + vị trí
    trung bình (đường, trục đảo: lên là tốt); phải: số từ khóa lên / xuống so với lần trước + tỷ lệ đạt Top mục tiêu."""
    from . import ui_theme as T
    x = [_vn(h["date"])[:5] for h in hist]
    bars = [("Top 3", "top3", "#1E7C31"), ("Top 4–10", "top10", "#9BB823"), ("Top 11–30", "top30", "#B7791F"),
            ("Ngoài top 30 / chưa thấy", "out", "#C9C7BC")]
    base = {"animation": False, "grid": {"left": 40, "right": 44, "top": 34, "bottom": 26},
            "legend": {"top": 0, "itemWidth": 12, "itemHeight": 8, "textStyle": {"fontSize": 11, "color": "#6B6A5E"}},
            "tooltip": {"trigger": "axis", "confine": True},
            "xAxis": {"type": "category", "data": x, "axisTick": {"show": False},
                      "axisLabel": {"color": "#8C8A7E", "fontSize": 10.5},
                      "axisLine": {"lineStyle": {"color": "#E7E5DC"}}}}
    axis = {"type": "value", "splitLine": {"lineStyle": {"color": "#EEECE4"}},
            "axisLabel": {"color": "#8C8A7E", "fontSize": 10.5}}
    with ui.element("div").classes("w-full").style(
            "display:grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 12px"):
        with ui.element("div").classes("sr-card q-pa-md"):
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.label("Phân bố Top & vị trí trung bình").classes("sr-section-title")
                T.info_icon(ui, "Phân bố Top theo lần check", (
                    "Mỗi cột là một ngày check: bao nhiêu từ khóa trong bộ đang ở Top 3, 4–10, 11–30, ngoài top 30.",
                    "Cột xanh đậm cao dần là bộ từ khóa đang lên. Đường vị trí trung bình đi lên là tốt hơn.",
                    "Mỗi ngày lấy lần check gần nhất của từng từ khóa. Vị trí trung bình chỉ tính từ khóa có hạng."))
            ui.echart({**base, "yAxis": [{**axis},
                                         {**axis, "inverse": True, "min": 1, "splitLine": {"show": False}}],
                       "series": [{"type": "bar", "stack": "top", "name": n, "data": [h[k] for h in hist],
                                   "itemStyle": {"color": c}, "barMaxWidth": 28} for n, k, c in bars]
                       + [{"type": "line", "name": "Vị trí trung bình", "yAxisIndex": 1, "smooth": 0.2,
                           "data": [h["avg"] for h in hist], "symbol": "circle", "symbolSize": 6,
                           "itemStyle": {"color": "#2563EB"}, "lineStyle": {"width": 2.5}}]}).classes(
                "w-full").style("height: 260px")
        with ui.element("div").classes("sr-card q-pa-md"):
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.label("Lên / xuống & đạt mục tiêu").classes("sr-section-title")
                T.info_icon(ui, "Lên xuống theo lần check", (
                    "Cột xanh: số từ khóa lên hạng, cột đỏ: số từ khóa xuống hạng so với lần check trước.",
                    "Đường cam: phần trăm từ khóa đã đạt Top mục tiêu của chính nó (ví dụ Top 3 mà đang hạng 2).",
                    "Chỉ tính từ khóa có Top mục tiêu; từ khóa giữ nguyên hạng không vẽ."))
            ui.echart({**base, "tooltip": {**base["tooltip"], ":valueFormatter": "v => v == null ? 'chưa có' : "
                                                                                "Math.abs(v)"},
                       "yAxis": [{**axis},
                                         {**axis, "min": 0, "max": 100, "splitLine": {"show": False},
                                          "axisLabel": {"color": "#8C8A7E", "fontSize": 10.5, "formatter": "{value}%"}}],
                       "series": [{"type": "bar", "name": "Lên hạng", "data": [h["up"] for h in hist],
                                   "itemStyle": {"color": "#1E7C31"}, "barMaxWidth": 18},
                                  {"type": "bar", "name": "Xuống hạng", "data": [-h["down"] for h in hist],
                                   "itemStyle": {"color": "#C2410C"}, "barMaxWidth": 18, "barGap": "-100%"},
                                  {"type": "line", "name": "% đạt Top mục tiêu", "yAxisIndex": 1, "smooth": 0.2,
                                   "data": [round(h["target_hit"] / h["target_total"] * 100) if h["target_total"]
                                            else None for h in hist],
                                   "symbol": "circle", "symbolSize": 6, "itemStyle": {"color": "#B7791F"},
                                   "lineStyle": {"width": 2.5}}]}).classes("w-full").style("height: 260px")


def build_rank_page(ui, cfg, connect, user: str, on_budget_change=None, set_id: int | None = None) -> None:
    """set_id: bộ (tab) đang mở; không có / không còn thì mở bộ đầu tiên."""
    from .access import can_edit
    from . import kpi as KP
    from . import ui_theme as T
    site = cfg.site_url
    ed = can_edit(user)  # người chỉ xem: không thêm/bỏ keyword, không check (tốn tiền), không sửa bộ
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

    right = T.page_header(ui, "leaderboard", "Từ khóa & rank",
                          f"Mỗi tab một bộ từ khóa, check qua DataForSEO theo nơi check riêng của bộ. Ngân sách "
                          f"{cfg.rank.monthly_budget_usd:g} USD/tháng cho cả website.")
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
                       icon="verified" if x["kind"] == "kpi" else None)
        if ed:
            ui.button("Bộ mới", icon="add", on_click=lambda: set_dialog(None)).props("flat dense no-caps")

    # ---- Bộ đang mở: nơi check, lịch, số từ khóa, chi phí ----
    with ui.element("div").classes("sr-card q-px-md q-py-sm w-full"):
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['green'][0]}"):
                ui.icon("verified" if is_kpi else "folder_open", size="18px").style(f"color:{T.GREEN}")
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label(("Bộ Cam kết: khớp tab Từ khóa cam kết của sheet dự án; sửa ở đây thì tool ghi lên sheet"
                          if is_kpi else f"Bộ {cur['name']}")).classes("text-xs muted")
                ui.label(R.describe_target(where) + (" (theo dự án)" if not cur["settings"] else "")).classes(
                    "text-sm font-medium")
                schedule_label = ui.label().classes("text-xs muted")
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
                                         schedule=s_new)
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

    # ---- Tăng trưởng của bộ ----
    growth_box = ui.column().classes("w-full gap-2")

    # ---- Phân bố vị trí (donut) + số chính bên cạnh ----
    dist_box = ui.element("div").classes("w-full").style(
        "display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px")

    def draw_dist(kws):
        from . import volume as V
        dist_box.clear()
        # Không thấy trong độ sâu đã check (ví dụ check top 10) thì chưa biết hạng thật: nhóm riêng, không gọi là
        # "ngoài top 30".
        counts = {"Top 3": 0, "Top 4–10": 0, "Top 11–30": 0, "Hạng > 30": 0, "Ngoài độ sâu check": 0}
        for k in kws:
            if not k["date"]:
                continue
            r = k["rank"]
            key = ("Ngoài độ sâu check" if r is None else "Top 3" if r <= 3 else "Top 4–10" if r <= 10
                   else "Top 11–30" if r <= 30 else "Hạng > 30")
            counts[key] += 1
        with connect() as c:
            vols = V.latest(c)
        checked = [k for k in kws if k["date"]]
        top10 = sum(1 for k in checked if k["rank"] is not None and k["rank"] <= 10)
        vol_top10 = sum((vols.get(k["id"]) or {}).get("volume") or 0 for k in checked
                        if k["rank"] is not None and k["rank"] <= 10)
        vol_all = sum((vols.get(k["id"]) or {}).get("volume") or 0 for k in kws)
        wrong = sum(1 for k in kws if k["target_url"] and k["ranking_url"] and k["ranking_url"] != k["target_url"])
        with_top = [k for k in checked if k.get("top_target")]
        hit = sum(1 for k in with_top if k["rank"] is not None and k["rank"] <= k["top_target"])
        with dist_box:
            with ui.element("div").classes("sr-card q-pa-md"):
                ui.label("Phân bố vị trí · lần check mới nhất").classes("sr-section-title")
                if not any(counts.values()):
                    ui.label("Chưa có lần check nào.").classes("text-sm muted")
                else:
                    T.donut(ui, list(counts.items()), ["#1E7C31", "#9BB823", "#B7791F", "#DB2777", "#B8B6A8"],
                            "keyword", 200)
                    ui.label("Ngoài độ sâu check: không thấy trong số kết quả đã check (ví dụ top 10), chưa biết "
                             "hạng thật.").classes("text-xs muted")
            with ui.element("div").classes("sr-bento").style("grid-template-columns: repeat(2, minmax(0, 1fr))"):
                for label, value, hint, tone in [
                    ("Keyword theo dõi", str(len(kws)), f"{len(checked)} đã check", "grey"),
                    ("Trong top 10", f"{top10}/{len(checked)}" if checked else "–",
                     f"{vol_top10:,} lượt tìm/tháng".replace(",", ".") if vol_top10 else "", "green"),
                    ("Đạt Top mục tiêu", f"{hit}/{len(with_top)}" if with_top else "–",
                     f"{hit / len(with_top) * 100:.0f}% từ khóa có Top mục tiêu" if with_top
                     else "chưa đặt Top mục tiêu", "blue"),
                    ("Tổng volume theo dõi", f"{vol_all:,}".replace(",", ".") if vol_all else "–",
                     "lượt tìm/tháng (Google Ads)", "blue"),
                    ("Sai URL mục tiêu", str(wrong), "Google xếp hạng URL khác" if wrong else "tất cả đúng URL",
                     "amber" if wrong else "green"),
                ]:
                    with ui.element("div").classes("sr-bento-tile"):
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.element("span").classes("sr-dot").style(f"background:{T.TONES[tone][1]}")
                            ui.label(label).classes("text-xs muted")
                            T.info_icon(ui, label)
                        ui.label(value).classes("sr-metric-value num")
                        if hint:
                            ui.label(hint).classes("text-xs muted")

    # ---- Bảng ----
    with ui.row().classes("w-full items-center gap-2 q-mt-sm"):
        ui.label(f"Danh sách keyword · {cur['name']}").classes("sr-section-title")
        ui.space()
        selection_bar = ui.row().classes("items-center gap-2")
    with selection_bar:
        selected_label = ui.label().classes("text-sm font-medium")
        if ed:
            ui.button("Check các keyword này", icon="play_arrow", on_click=lambda: check_now()).props(
                "flat dense no-caps")
            ui.button("Bỏ theo dõi", icon="delete_outline", on_click=lambda: remove()).props(
                "flat dense no-caps color=negative")
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
        {"name": "best", "label": "Tốt nhất", "field": "best", "align": "center", "sortable": True},
        {"name": "link", "label": "URL đang xếp hạng", "field": "link", "align": "left"},
        {"name": "target", "label": "URL mục tiêu", "field": "target", "align": "left"},
        {"name": "date", "label": "Check lúc", "field": "date", "align": "center", "sortable": True},
        {"name": "chart", "label": "", "field": "id", "align": "center"},
    ]
    if not is_kpi:
        cols.insert(1, {"name": "source", "label": "Nguồn", "field": "source", "align": "left", "sortable": True})
    table = ui.table(columns=cols, rows=[], row_key="id", selection="multiple" if ed else "none",
                     pagination=50).classes("w-full").props("flat bordered dense")
    table.add_slot("body-cell-pos", """
        <q-td :props="props" class="text-center">
          <span v-if="props.row.checked" :style="{background: props.row.bg, color: props.row.fg, borderRadius: '6px',
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
          <div class="row no-wrap items-center" style="gap: 4px; max-width: 280px">
            <a v-if="props.row.link_full" :href="props.row.link_full" target="_blank" rel="noopener"
               :title="props.row.link_full" class="ellipsis" style="color: inherit; text-decoration: none; min-width: 0">
              {{ props.value }} <q-icon name="open_in_new" size="12px" color="grey-6" /></a>
            <q-icon v-if="props.row.wrong" name="warning" color="orange-8" size="16px">
              <q-tooltip>Khác URL mục tiêu (URL mục tiêu đang ở vị trí {{ props.row.target_pos }})</q-tooltip>
            </q-icon>
          </div>
        </q-td>""")
    table.add_slot("body-cell-target", """
        <q-td :props="props">
          <a v-if="props.row.target_full" :href="props.row.target_full" target="_blank" rel="noopener"
             :title="props.row.target_full" class="ellipsis block"
             style="color: inherit; text-decoration: none; max-width: 240px">
            {{ props.value }} <q-icon name="open_in_new" size="12px" color="grey-6" /></a>
          <span v-else class="muted">chưa gán</span>
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

    with ui.dialog() as chart_dialog, ui.card().style("min-width: 640px; max-width: 94vw"):
        chart_title = ui.label().classes("text-base font-semibold")
        chart = ui.echart({"xAxis": {"type": "category", "data": []}, "yAxis": {"type": "value"}, "series": []}).classes(
            "w-full").style("height: 300px")
        ui.label("Trục vị trí đảo ngược: lên cao là tốt hơn. Điểm trống = ngoài độ sâu check.").classes("text-xs muted")

    def show_chart(e):
        with connect() as c:
            hist = R.history(c, e.args["id"])
        chart_title.text = f"Lịch sử vị trí: {e.args['keyword']}"
        chart.options.update({
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 40, "right": 16, "top": 16, "bottom": 32},
            "xAxis": {"type": "category", "data": [_vn(d)[:5] for d, _, _ in hist]},
            "yAxis": {"type": "value", "inverse": True, "min": 1, "name": "Vị trí"},
            "series": [{"type": "line", "data": [r for _, r, _ in hist], "connectNulls": False,
                        "itemStyle": {"color": "#1E7C31"}, "label": {"show": True, "position": "top"}}],
        })
        chart.update()
        chart_dialog.open()

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
            err = ui.label().classes("text-sm").style(f"color:{T.RED}")

            async def save():
                err.text = ""
                t = int(top.value or 0) or None
                try:
                    await save_keyword(row, (url_in.value or "").strip(), t)
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

    async def save_keyword(row: dict, url: str, top: int | None):
        """Lưu Top / URL mục tiêu. Bộ Cam kết: ghi dòng đó lên sheet trước, rồi đọc lại sheet."""
        from nicegui import run
        if url and domain(url) != domain(site):
            raise ValueError(f"URL phải thuộc {domain(site)}")
        if is_kpi:
            await run.io_bound(KP.sheet_keyword_op, cfg, sheet, "upsert", row["keyword"], url, top)
            with connect() as c:
                R.set_target_url(c, site, row["id"], url, str(user))
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
        rows = []
        for k in kws:
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
            })
        table.rows = rows
        table.selected = []
        on_select()
        growth_box.clear()
        with growth_box:
            if len(hist) >= 2:
                growth_charts(ui, hist)
            elif kws:
                ui.label("Biểu đồ tăng trưởng hiện khi bộ có từ 2 ngày check trở lên.").classes("text-sm muted")
        draw_dist(kws)
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
        ids = [r_["id"] for r_ in table.selected] or [r_["id"] for r_ in table.rows]
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
