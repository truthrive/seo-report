"""Màn Check rank: nhập keyword (kèm URL mục tiêu nếu có), đặt lịch chung, xem bảng vị trí và biểu đồ lịch sử."""
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


RANK_TONES = [(3, ("#E7F3EA", "#1E7C31")), (10, ("#F2F7DC", "#5E7414")), (30, ("#FBF1DE", "#B7791F"))]


def change_text(k: dict) -> tuple[str, str, int]:
    from .report import rank_change
    return rank_change(k["date"], k["rank"], k["last_depth"], k["prev"], k["prev_depth"])


def build_rank_page(ui, cfg, connect, user: str, on_budget_change=None) -> None:
    from .access import can_edit
    site = cfg.site_url
    ed = can_edit(user)  # người chỉ xem: không thêm/bỏ keyword, không check (tốn tiền), không sửa lịch
    with connect() as c:
        end = K.latest_date(c, site)
        sched = R.get_schedule(c)

    from . import ui_theme as T
    right = T.page_header(ui, "leaderboard", "Từ khóa & rank",
                          f"Google mobile, Việt Nam, qua DataForSEO. Ngân sách {cfg.rank.monthly_budget_usd:.0f} "
                          "USD/tháng.")
    with right:
        if ed:
            ui.button("Thêm keyword", icon="add", on_click=lambda: add_dialog.open()).props("outline no-caps")
            check_btn = ui.button("Check ngay", icon="play_arrow", on_click=lambda: check_now()).props(
                "unelevated no-caps").tooltip("Check các keyword đã tích chọn, hoặc toàn bộ nếu không chọn gì")
        from .web_export import export_menu
        export_menu(ui, cfg, connect, f"check-rank_{date.today():%Y-%m-%d}", lambda: export(), user=user)

    # ---- Lịch check chung: một dòng tóm tắt, sửa trong hộp thoại ----
    with ui.element("div").classes("sr-card q-px-md q-py-sm w-full"):
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['blue'][0]}"):
                ui.icon("event_repeat", size="18px").style(f"color:{T.BLUE}")
            with ui.column().classes("gap-0"):
                ui.label("Lịch check (áp dụng cho mọi keyword)").classes("text-xs muted")
                schedule_label = ui.label().classes("text-sm font-medium")
            ui.space()
            if ed:
                ui.button("Sửa lịch", icon="edit_calendar", on_click=lambda: sched_dialog.open()).props(
                    "flat no-caps")

    with ui.dialog() as sched_dialog, ui.card().style("min-width: 520px; border-radius: 14px"):
        ui.label("Lịch check rank").classes("text-lg font-semibold")
        kind = ui.toggle({"weekdays": "Hằng tuần", "monthly": "Hằng tháng", "manual": "Thủ công"},
                         value=sched["type"]).props("no-caps unelevated toggle-color=primary")
        days_box = ui.row().classes("gap-1")
        with days_box:
            day_checks = [ui.chip(name.replace("Thứ ", "T").replace("Chủ nhật", "CN"), selectable=True,
                                  selected=i in sched["weekdays"]).props("outline color=primary")
                          for i, name in enumerate(R.WEEKDAYS)]
        month_day = ui.number("Ngày trong tháng", value=sched["day"], min=1, max=31, step=1, format="%d").props(
            "dense outlined").classes("w-40")
        manual_note = ui.label("Chỉ check khi bấm nút Check ngay.").classes("text-sm muted")
        depth = ui.select({d: ("Tự động" if d == "auto" else f"Top {d}") for d in R.DEPTHS}, value=sched["depth"],
                          label="Độ sâu check").props("dense outlined").classes("w-48")
        ui.label("Tự động: lần đầu check top 30; sau đó theo vị trí lần trước (≤ 8 → top 10, ≤ 18 → top 20, còn lại "
                 "top 30). Check sâu hơn tốn tiền hơn.").classes("text-xs muted")
        estimate_label = ui.label().classes("text-sm")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Hủy", on_click=sched_dialog.close).props("flat no-caps")
            ui.button("Lưu lịch", on_click=lambda: save_schedule()).props("unelevated no-caps")

    def current_schedule() -> dict:
        return {"type": kind.value, "weekdays": [i for i, cb in enumerate(day_checks) if cb.selected],
                "day": int(month_day.value or 1), "depth": depth.value}

    def update_schedule_view():
        days_box.set_visibility(kind.value == "weekdays")
        month_day.set_visibility(kind.value == "monthly")
        manual_note.set_visibility(kind.value == "manual")
        s = current_schedule()
        with connect() as c:
            kws = R.keywords(c, site, end)
            saved = R.get_schedule(c)
        depths = [R.depth_for(s["depth"], k["rank"], k["last_depth"]) for k in kws]
        est = R.estimate(None, cfg.rank, s, depths)
        warn = est > cfg.rank.monthly_budget_usd
        estimate_label.text = f"Ước tính với {len(kws)} keyword: {R.usd(est)} USD/tháng" + (
            " — vượt ngân sách!" if warn else "")
        estimate_label.classes(replace="text-sm " + ("text-negative" if warn else "muted"))
        saved_depths = [R.depth_for(saved["depth"], k["rank"], k["last_depth"]) for k in kws]
        schedule_label.text = (f"{R.describe_schedule(saved)} · {len(kws)} keyword · ước tính "
                               f"{R.usd(R.estimate(None, cfg.rank, saved, saved_depths))} USD/tháng")

    for el in [kind, month_day, depth]:
        el.on_value_change(lambda _: update_schedule_view())
    for cb in day_checks:
        cb.on_selection_change(lambda _: update_schedule_view())

    def save_schedule():
        s = current_schedule()
        if s["type"] == "weekdays" and not s["weekdays"]:
            ui.notify("Chọn ít nhất một thứ trong tuần", type="warning")
            return
        with connect() as c:
            R.set_schedule(c, site, s, user)
        ui.notify(f"Đã lưu lịch: {R.describe_schedule(s)}", type="positive")
        sched_dialog.close()
        refresh()

    # ---- Thêm keyword: hộp thoại ----
    with ui.dialog() as add_dialog, ui.card().style("min-width: 620px; border-radius: 14px"):
        ui.label("Thêm keyword").classes("text-lg font-semibold")
        ui.label("Mỗi dòng một keyword. Muốn gán URL mục tiêu thì thêm URL sau dấu | (hoặc dán 2 cột từ Excel).").classes(
            "text-sm muted")
        paste = ui.textarea(placeholder=f"từ khóa 1\ntừ khóa 2 | https://{domain(cfg.site_url)}/trang-muc-tieu/").props("outlined autogrow").classes("w-full")
        add_result = ui.label().classes("text-sm")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Đóng", on_click=add_dialog.close).props("flat no-caps")
            ui.button("Thêm vào danh sách", icon="playlist_add", on_click=lambda: add()).props("unelevated no-caps")

    # ---- Phân bố vị trí (donut) + số chính bên cạnh ----
    dist_box = ui.element("div").classes("w-full").style(
        "display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 12px")

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
                    ("Tổng volume theo dõi", f"{vol_all:,}".replace(",", ".") if vol_all else "–",
                     "lượt tìm/tháng (Google Ads)", "blue"),
                    ("Sai URL mục tiêu", str(wrong), "Google xếp hạng URL khác" if wrong else "tất cả đúng URL",
                     "amber" if wrong else "green"),
                ]:
                    with ui.element("div").classes("sr-bento-tile"):
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.element("span").classes("sr-dot").style(f"background:{T.TONES[tone][1]}")
                            ui.label(label).classes("text-xs muted")
                        ui.label(value).classes("sr-metric-value num")
                        if hint:
                            ui.label(hint).classes("text-xs muted")

    # ---- Bảng ----
    with ui.row().classes("w-full items-center gap-2 q-mt-sm"):
        ui.label("Danh sách keyword").classes("sr-section-title")
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
    table = ui.table(columns=[
        {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
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
    ], rows=[], row_key="id", selection="multiple" if ed else "none", pagination=50).classes("w-full").props(
        "flat bordered dense")
    table.add_slot("body-cell-pos", """
        <q-td :props="props" class="text-center">
          <span v-if="props.row.checked" :style="{background: props.row.bg, color: props.row.fg, borderRadius: '6px',
                padding: '2px 8px', fontWeight: 700}">{{ props.value }}</span>
          <span v-else class="muted">chờ check</span>
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
          <q-btn flat round dense icon="show_chart" color="grey-7" size="sm" :aria-label="'Biểu đồ ' + props.row.keyword"
                 @click="$parent.$emit('chart', props.row)"><q-tooltip>Lịch sử vị trí</q-tooltip></q-btn>
        </q-td>""")

    def on_select(_=None):
        n = len(table.selected)
        selection_bar.set_visibility(n > 0)
        selected_label.text = f"Đã chọn {n}"

    table.on_select(on_select)

    with ui.dialog() as chart_dialog, ui.card().style("min-width: 640px"):
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

    def short(url):
        return (url or "").replace(site.rstrip("/"), "") or ("/" if url else "")

    def refresh():
        from . import volume as V
        with connect() as c:
            kws = R.keywords(c, site, end)
            vols = V.latest(c)
        rows = []
        for k in kws:
            cur = k["rank"] if k["rank"] is not None else (k["last_depth"] or 0) + 1
            text, color, move = change_text(k)
            bg, fg = next((t for lim, t in RANK_TONES if k["rank"] is not None and k["rank"] <= lim),
                          ("#F1F0EA", "#6B6A5E"))
            rows.append({
                "id": k["id"], "keyword": k["keyword"], "pos": _pos(k["rank"], k["last_depth"]),
                "volume": ((vols[k["id"]]["volume"] if vols[k["id"]]["volume"] is not None else -1)
                           if k["id"] in vols else None),
                "checked": bool(k["date"]), "sort_pos": cur or 999, "bg": bg, "fg": fg,
                "change": text, "change_color": color, "move": move, "best": k["best"] or "",
                "date": _vn(k["date"])[:5], "link": short(k["ranking_url"]), "link_full": k["ranking_url"] or "",
                "target": short(k["target_url"]), "target_full": k["target_url"] or "",
                "wrong": bool(k["target_url"] and k["ranking_url"] and k["ranking_url"] != k["target_url"]),
                "target_pos": _pos(k["target_rank"], k["last_depth"]),
            })
        table.rows = rows
        table.selected = []
        on_select()
        draw_dist(kws)
        update_schedule_view()
        if on_budget_change:
            on_budget_change()

    async def add():
        from nicegui import run

        from . import volume as V
        items = R.parse_lines(paste.value or "")
        if not items:
            return
        with connect() as c:
            r = R.add_keywords(c, site, cfg.rank, end, items, user)

        def fetch_volume():  # keyword mới thêm: lấy volume ngay (keyword đã có số tháng này thì bỏ qua)
            with connect() as c:
                return V.refresh(c, site, cfg, end, log=lambda m: None)
        try:
            await run.io_bound(fetch_volume)
        except Exception as e:  # noqa: BLE001  (keyword vẫn được thêm, volume lấy lại ở lịch hằng ngày)
            ui.notify(f"Chưa lấy được volume: {e}", type="warning", multi_line=True)
        parts = [f"Đã thêm {len(r['added'])}"]
        if r["updated"]:
            parts.append(f"đổi URL mục tiêu {len(r['updated'])}")
        if r["exists"]:
            parts.append(f"đã có sẵn {len(r['exists'])}")
        if r["over_budget"]:
            parts.append(f"KHÔNG thêm {len(r['over_budget'])} keyword vì vượt ngân sách: {', '.join(r['over_budget'][:5])}")
        if r["bad_url"]:
            parts.append(f"bỏ qua {len(r['bad_url'])} dòng có URL không thuộc site")
        add_result.text = " · ".join(parts) + f". Ước tính: {R.usd(r['estimate'])} USD/tháng."
        paste.value = ""
        refresh()
        if not r["over_budget"] and not r["bad_url"]:
            add_dialog.close()
            ui.notify(add_result.text, type="positive")

    def remove():
        if not table.selected:
            ui.notify("Tích chọn keyword cần bỏ", type="warning")
            return
        with connect() as c:
            R.remove_keywords(c, site, [r["id"] for r in table.selected], user)
        ui.notify(f"Đã bỏ theo dõi {len(table.selected)} keyword (lịch sử vẫn được giữ)", type="positive")
        refresh()

    async def check_now():
        from nicegui import run

        ids = [r["id"] for r in table.selected] or [r["id"] for r in table.rows]
        if not ids:
            return
        creds = R.load_credentials(cfg.dataforseo_secret)
        if not creds:
            ui.notify(f"Chưa có API key DataForSEO trong {cfg.dataforseo_secret}", type="negative")
            return

        def work():
            logs = []
            with connect() as c:
                R.run(c, site, cfg.rank, R.DataForSEO(*creds), end, only_ids=ids, wait_minutes=5, log=logs.append)
            return logs

        check_btn.props("loading")
        try:
            logs = await run.io_bound(work)
            failed = any(m.startswith(("Không gửi được", "Dừng")) for m in logs)
            ui.notify(" ".join(logs) or "Không có keyword nào được gửi", type="warning" if failed else "positive",
                      multi_line=True, timeout=0 if failed else 8000, close_button="Đóng" if failed else None)
        except Exception as e:
            ui.notify(f"Check rank thất bại: {e}", type="negative", multi_line=True, timeout=10000)
        finally:
            check_btn.props(remove="loading")
        refresh()

    def export() -> bytes:
        from openpyxl import Workbook

        from . import volume as V
        from .export import INT, _sheet

        wb = Workbook()
        wb.remove(wb.active)
        with connect() as c:
            kws = R.keywords(c, site, end)
            hist = {k["id"]: R.history(c, k["id"]) for k in kws}
            vols = V.latest(c)
        _sheet(wb, "Check rank", [
            ("STT", 6, INT), ("Từ khóa", 34, None), ("Volume/tháng", 12, INT), ("Vị trí", 8, None),
            ("Vị trí cũ", 9, None), ("Thay đổi", 18, None), ("Vị trí tốt nhất", 12, INT), ("Cập nhật", 12, None),
            ("Liên kết", 60, None), ("URL mục tiêu", 55, None), ("Đúng URL", 9, None)],
            [[i, k["keyword"], (vols.get(k["id"]) or {}).get("volume"), _pos(k["rank"], k["last_depth"]),
              _pos(k["prev"], k["prev_depth"]), change_text(k)[0], k["best"], _vn(k["date"]), k["ranking_url"] or "",
              k["target_url"] or "",
              ("Có" if k["ranking_url"] == k["target_url"] else "Không") if k["target_url"] and k["ranking_url"] else ""]
             for i, k in enumerate(kws, 1)])
        _sheet(wb, "Lịch sử", [("Từ khóa", 34, None), ("Ngày check", 12, "dd/mm/yyyy"), ("Vị trí", 8, INT),
                               ("Độ sâu", 8, INT)],
               [[k["keyword"], date.fromisoformat(d), r, dep] for k in kws for d, r, dep in hist[k["id"]]])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    refresh()
