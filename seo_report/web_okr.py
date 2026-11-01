"""Màn Công việc & OKR: tiến độ OKR 3 tháng và Weekly Task Tracker đọc từ Google Sheet của team (chỉ đọc)."""
import json
from datetime import date, datetime, timedelta

from . import okr as O
from . import ui_theme as T

STATUS_TONE = {O.DONE: "green", O.DOING: "blue", O.TODO: "grey", O.OTHER: "amber"}
STATUS_COLOR = {O.DONE: "#1E7C31", O.DOING: "#2563EB", O.TODO: "#B8B6A8", O.OTHER: "#B7791F"}


def _vn(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso else "–"


def build_okr_page(ui, cfg, connect, user: str, ctx: dict) -> None:
    from nicegui import run

    today = date.today()
    ws, we = ctx["weeks"][ctx["week"]]
    sheet_url = cfg.okr.sheet if cfg.okr.sheet.startswith("http") else \
        f"https://docs.google.com/spreadsheets/d/{O.sheet_id(cfg.okr.sheet)}/edit"

    right = T.page_header(ui, "task_alt", "Công việc & OKR",
                          "Đọc từ Google Sheet của team · cập nhật trên sheet", eyebrow="Báo cáo công việc")
    from .access import can_edit
    with right:
        if can_edit(user):  # người chỉ xem không mở được sheet (đã đóng link) và không đồng bộ
            ui.button("Mở sheet", icon="open_in_new", on_click=lambda: ui.navigate.to(sheet_url, new_tab=True)).props(
                "outline no-caps")
            sync_btn = ui.button("Đồng bộ ngay", icon="sync", on_click=lambda: do_sync()).props("unelevated no-caps")

    if not O.sheet_id(cfg.okr.sheet):
        T.empty_state(ui, "table_view", "Chưa khai báo Google Sheet",
                      "Gắn link Google Sheet OKR cho dự án ở màn Dự án (Quản trị → Dự án → Sửa).")
        return

    body = ui.column().classes("w-full gap-4")

    async def do_sync():
        sync_btn.props("loading")
        try:
            def work():
                with connect() as c:
                    return O.sync(c, cfg)
            res = await run.io_bound(work)
            ui.notify(f"Đã đồng bộ {res['items']} hạng mục OKR và {res['tasks']} task tuần", type="positive")
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không đồng bộ được: {e}", type="negative", multi_line=True)
        finally:
            sync_btn.props(remove="loading")
        render.refresh()

    cur_week = (today - timedelta(days=today.weekday()), today - timedelta(days=today.weekday()) + timedelta(days=6))
    view = {"week": "now", "gantt": "all", "cycle": None}

    @ui.refreshable
    def render():
        with connect() as c:
            info = O.sync_info(c)
            ov = O.overview(c, today, cycle=view["cycle"]) if info else None
            tasks = O.tasks(c) if info else []
        if not info:
            T.empty_state(ui, "sync", "Chưa đồng bộ lần nào", "Bấm Đồng bộ ngay để lấy dữ liệu từ sheet.")
            return
        synced = datetime.fromisoformat(info["at"]).astimezone()
        with ui.row().classes("items-center gap-2"):
            T.status_chip(ui, f"Đồng bộ lúc {synced:%H:%M %d/%m} · {info['items']} hạng mục · "
                              f"{info['tasks']} task tuần", "grey", "schedule")
            if info["source"] == "public":
                with ui.element("div"):
                    T.status_chip(ui, "Đang đọc qua link công khai", "amber", "public")
                    ui.tooltip("Sheet đang để ai có link đều xem được. Sau khi cấp quyền Google Sheets cho tool "
                               "(đăng nhập lại), nên tắt chia sẻ công khai.")

        # ---- Chọn đợt OKR (mỗi tab "OKRs …" là một đợt) ----
        if len(ov["cycles"]) > 1:
            def pick(e):
                view.update(cycle=e.value, gantt="all")
                render.refresh()
            ui.toggle({c["name"]: f"{c['name']} · {_vn(c['start'])} – {_vn(c['end'])}" for c in ov["cycles"]},
                      value=ov["cycle"], on_change=pick).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")

        # ---- Cần cập nhật trên sheet ----
        issues = _sheet_issues(ov["items"], tasks, today)
        overdue_tasks = sum(1 for x in issues if x["kind"] == "task" and x["reason"] == "Quá deadline")
        if issues:
            with ui.element("div").classes("q-pa-md w-full").style(
                    f"border-radius:12px;background:{T.TONES['amber'][0]};border:1px solid #EAD7AE"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("rule", size="18px").style(f"color:{T.AMBER}")
                    ui.label(f"Cần cập nhật trên sheet · {len(issues)}").classes("text-sm font-semibold")
                for x in issues[:8]:
                    with ui.row().classes("items-center gap-2 no-wrap w-full"):
                        T.status_chip(ui, x["reason"], "red" if "Quá" in x["reason"] else "amber")
                        ui.label(x["code"] or "–").classes("text-xs muted").style("min-width:40px")
                        ui.label(x["text"]).classes("text-sm ellipsis col").tooltip(x["text"])
                        ui.label(x["where"]).classes("text-xs muted")
                if len(issues) > 8:
                    ui.label(f"và {len(issues) - 8} dòng khác").classes("text-xs muted")

        # ---- Số tổng (bento) ----
        cnt, total = ov["counts"], ov["total"] or 1
        late = ov["late"]
        with ui.element("div").classes("sr-bento w-full"):
            with ui.element("div").classes("sr-bento-tile big"):
                ui.label("Tiến độ OKR 3 tháng").classes("sr-bento-eyebrow").style(f"color:{T.GREEN}")
                ui.label(f"{cnt[O.DONE]} / {ov['total']} hạng mục hoàn thành").classes("text-sm muted")
                ui.label(f"{cnt[O.DONE] / total * 100:.0f}%").classes("sr-bento-hero num")
                with ui.element("div").classes("w-full").style("margin-top:auto"):
                    seg = "".join(
                        f'<div title="{O.STATUS_LABEL[s]}: {cnt[s]}" style="flex:{cnt[s]};background:{STATUS_COLOR[s]}">'
                        f"</div>" for s in (O.DONE, O.DOING, O.TODO, O.OTHER) if cnt[s])
                    ui.html(f'<div style="display:flex;gap:3px;height:10px;border-radius:5px;overflow:hidden">{seg}'
                            "</div>")
                    with ui.row().classes("items-center gap-3 q-mt-xs"):
                        for s in (O.DONE, O.DOING, O.TODO, O.OTHER):
                            if cnt[s]:
                                with ui.row().classes("items-center gap-1 no-wrap"):
                                    ui.element("span").classes("sr-dot").style(f"background:{STATUS_COLOR[s]}")
                                    ui.label(O.STATUS_LABEL[s]).classes("text-xs muted")
            for label, value, tone in [("Hoàn thành", cnt[O.DONE], "green"), ("Đang làm", cnt[O.DOING], "blue"),
                                       ("Chưa bắt đầu", cnt[O.TODO], "grey"),
                                       ("Trễ hạn", len(late), "red" if late else "green")]:
                with ui.element("div").classes("sr-bento-tile"):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.element("span").classes("sr-dot").style(f"background:{T.TONES[tone][1]}")
                        ui.label(label).classes("text-xs muted")
                    ui.label(str(value)).classes("sr-metric-value num")
                    if label != "Trễ hạn":
                        hint = f"{value / total * 100:.0f}% hạng mục"
                    else:
                        hint = "hạng mục quá ngày kết thúc" if late else "không có hạng mục trễ"
                        if overdue_tasks:
                            hint += f" · {overdue_tasks} task tuần quá deadline"
                    ui.label(hint).classes("text-xs muted")

        # ---- Theo mục tiêu ----
        with T.section(ui, "Theo mục tiêu", "flag"):
            with ui.element("div").classes("w-full").style(
                    "display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px"):
                for o in ov["objectives"]:
                    pct = o["pct"] or 0
                    with ui.element("div").classes("sr-card q-pa-md column no-wrap").style("border-radius:12px"):
                        with ui.row().classes("items-center justify-between no-wrap w-full"):
                            T.status_chip(ui, o["code"], "green" if pct >= 1 else "grey")
                            ui.label(f"{pct * 100:.0f}%").classes("text-sm font-semibold num")
                        ui.label(o["title"]).classes("text-sm font-medium q-mt-xs").style(
                            "display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;"
                            "line-height:1.35;min-height:2.7em").tooltip(o["title"])
                        ui.label(f"{_vn(o['start'])} – {_vn(o['end'])} · {o['done']}/{o['total']} xong"
                                 + (f" · {o['doing']} đang làm" if o["doing"] else "")).classes("text-xs muted")
                        ui.linear_progress(pct, show_value=False, size="8px",
                                           color="positive").classes("rounded-borders q-mt-sm")
                        if o["late"]:
                            T.status_chip(ui, f"{o['late']} việc trễ", "red", "warning")

        # ---- Gantt ----
        all_dated = [i for i in ov["items"] if i["start"] and i["end"]]
        if all_dated:
            objs = {o["uid"]: o["code"] for o in ov["objectives"]}  # lọc theo uid (mã có thể trùng giữa các đợt)
            with T.section(ui, "Lịch triển khai", "view_timeline", "Rê chuột vào thanh để xem chi tiết"):
                opts = {"all": "Tất cả", "open": "Chưa xong", **objs}
                ui.toggle(opts, value=view["gantt"], on_change=lambda e: (view.update(gantt=e.value),
                                                                          gantt.refresh())).props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                    "sr-seg q-mb-sm")
                with ui.row().classes("items-center gap-4 q-mb-xs").style("flex-wrap: wrap"):
                    for color, text in (("#1E7C31", "Hoàn thành"), ("#2563EB", "Đang làm (đậm = phần đã làm)"),
                                        ("#B8B6A8", "Chưa bắt đầu"), ("#C2410C", "Trễ hạn")):
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.element("span").style(f"width:18px;height:8px;border-radius:4px;background:{color}")
                            ui.label(text).classes("text-xs muted")
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.element("span").style("width:18px;height:4px;border-radius:2px;background:#1F221E")
                        ui.label("Thời gian của cả mục tiêu").classes("text-xs muted")
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.element("span").style("width:2px;height:12px;background:#C2410C")
                        ui.label("Hôm nay").classes("text-xs muted")
                gantt(all_dated, ov["objectives"])

        # ---- Tuần ----
        week_block(tasks, late)

        # ---- Toàn bộ hạng mục / task ----
        with ui.expansion(f"Tất cả hạng mục OKR ({ov['total']}) và task tuần ({len(tasks)})",
                          icon="list").classes("w-full sr-card"):
            with ui.tabs().props("dense no-caps align=left active-color=primary indicator-color=primary") as tabs:
                t_items = ui.tab(f"Hạng mục OKR · {ov['total']}")
                t_tasks = ui.tab(f"Task tuần · {len(tasks)}")
            with ui.tab_panels(tabs, value=t_items).classes("w-full"):
                with ui.tab_panel(t_items).classes("q-pa-none"):
                    ui.table(columns=[
                        {"name": "code", "label": "ID", "field": "code", "align": "left"},
                        {"name": "grp", "label": "Nhóm", "field": "grp", "align": "left"},
                        {"name": "title", "label": "Hạng mục", "field": "title", "align": "left",
                         "style": "white-space: normal; min-width: 240px"},
                        {"name": "time", "label": "Thời gian", "field": "time", "align": "left"},
                        {"name": "pic", "label": "PIC", "field": "pic", "align": "left"},
                        {"name": "st", "label": "Trạng thái", "field": "st", "align": "left"},
                    ], rows=[{**i, "time": f"{_vn(i['start'])} – {_vn(i['end'])}",
                              "st": ("Trễ hạn · " if O.is_late(i, today) else "") + O.STATUS_LABEL[i["status"]]}
                             for i in ov["items"]], row_key="code", pagination=50).classes("w-full").props(
                        "flat dense")
                with ui.tab_panel(t_tasks).classes("q-pa-none"):
                    ui.table(columns=[
                        {"name": "week", "label": "Tuần", "field": "wk", "align": "left"},
                        {"name": "okr", "label": "Mã OKR", "field": "okr_code", "align": "left"},
                        {"name": "task", "label": "Việc", "field": "task", "align": "left",
                         "style": "white-space: normal; min-width: 260px"},
                        {"name": "pic", "label": "PIC", "field": "pic", "align": "left"},
                        {"name": "dl", "label": "Deadline", "field": "dl", "align": "center"},
                        {"name": "st", "label": "Trạng thái", "field": "st", "align": "left"},
                    ], rows=[{**t, "wk": _vn(t["week"]), "dl": _vn(t["deadline"]), "st": O.STATUS_LABEL[t["status"]]}
                             for t in sorted(tasks, key=lambda t: t["week"] or "", reverse=True)],
                        row_key="row", pagination=50).classes("w-full").props("flat dense")

    @ui.refreshable
    def gantt(all_dated, objectives):
        """Lịch triển khai: mỗi mục tiêu một dòng tiêu đề (thanh mảnh = thời gian của cả mục tiêu, kèm % xong), bên dưới
        là các hạng mục. Màu theo trạng thái, thanh "đang làm" tô đậm phần đã làm theo % tiến độ, nền xen kẽ theo tháng,
        vạch đỏ là hôm nay."""
        import html
        sel = view["gantt"]
        items = [i for i in all_dated if sel == "all" or (sel == "open" and i["status"] != O.DONE)
                 or i["objective"] == sel]
        if not items:
            ui.label("Không có hạng mục nào.").classes("text-sm muted")
            return
        d0 = date.fromisoformat(min(i["start"] for i in all_dated))  # trục thời gian giữ nguyên khi lọc
        d1 = date.fromisoformat(max(i["end"] for i in all_dated))
        days = (d1 - d0).days + 2

        def x(iso):
            return (date.fromisoformat(iso) - d0).days

        def short(t, n):
            return t if len(t) <= n else t[:n - 1].rstrip() + "…"

        # Dòng hiển thị từ trên xuống: tiêu đề mục tiêu rồi các hạng mục của nó
        top = []
        for o in objectives:
            its = [i for i in items if i["objective"] == o["uid"]]
            if not its:
                continue
            mine = [i for i in all_dated if i["objective"] == o["uid"]]
            top.append({"kind": "obj", "o": o, "start": min(i["start"] for i in mine),
                        "end": max(i["end"] for i in mine)})
            top += [{"kind": "item", "i": i} for i in its]
        rows = top[::-1]  # trục danh mục vẽ từ dưới lên
        keys = [f"r{n}" for n in range(len(rows))]
        labels = {}
        for k, r in zip(keys, rows):
            if r["kind"] == "obj":
                o = r["o"]
                pct = f"{(o['pct'] or 0) * 100:.0f}%"
                labels[k] = f"{{oc|{o['code']}}} {{ot|{short(o['title'], 30)}}} {{op|{pct}}}"
            else:
                i = r["i"]
                labels[k] = f"{{ic|{i['code'][-5:]}}} {{it|{short(i['title'], 36)}}}"

        none = "-"
        off_i, len_i, off_p, len_p, off_o, len_o = [], [], [], [], [], []
        for r in rows:
            if r["kind"] == "obj":
                off_i.append(none), len_i.append(none), off_p.append(none), len_p.append(none)
                o = r["o"]
                off_o.append(x(r["start"]))
                len_o.append({"value": x(r["end"]) - x(r["start"]) + 1, "tip": (
                    f"<b>{html.escape(o['code'])} · {html.escape(o['title'])}</b><br/>{_vn(r['start'])} – "
                    f"{_vn(r['end'])}<br/>{o['done']}/{o['total']} hạng mục xong"
                    + (f" · {o['late']} trễ hạn" if o["late"] else ""))})
                continue
            i = r["i"]
            off_o.append(none), len_o.append(none)
            s, ln = x(i["start"]), x(i["end"]) - x(i["start"]) + 1
            late = O.is_late(i, today)
            doing = i["status"] == O.DOING and not late
            prog = i.get("progress")
            color = "#C2410C" if late else ("#BFD3FB" if doing else STATUS_COLOR[i["status"]])
            status = "Trễ hạn · " + O.STATUS_LABEL[i["status"]] if late else O.STATUS_LABEL[i["status"]]
            tip = (f"<b>{html.escape(i['code'])} · {html.escape(i['title'])}</b><br/>{_vn(i['start'])} – "
                   f"{_vn(i['end'])} · {ln} ngày<br/>{status}" + (f" · {prog:.0f}%" if prog is not None else "")
                   + f"<br/>PIC: {html.escape(i['pic'] or 'chưa có')}")
            off_i.append(s)
            len_i.append({"value": ln, "tip": tip, "itemStyle": {"color": color}})
            if doing and prog:  # phần đã làm của thanh "đang làm"
                off_p.append(s)
                len_p.append({"value": max(1, round(ln * min(prog, 100) / 100)), "tip": tip})
            else:
                off_p.append(none), len_p.append(none)

        # Nền xen kẽ theo tháng + nhãn tháng ở đầu cột
        bands, m = [], date(d0.year, d0.month, 1)
        while m <= d1:
            nm = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
            a, b = max(0, (m - d0).days), min(days, (nm - d0).days)
            bands.append([{"xAxis": a, "name": f"Tháng {m.month}",
                           "itemStyle": {"color": "rgba(31,34,30,0.035)" if m.month % 2 else "rgba(0,0,0,0)"}},
                          {"xAxis": b}])
            m = nm
        today_x = (today - d0).days
        ticks = [(d0 + timedelta(days=k)).strftime("%d/%m") for k in range(days)]
        hidden = {"color": "transparent"}
        bar = {"type": "bar", "barWidth": 12, "barGap": "-100%"}
        ui.echart({
            "animation": False,
            "grid": {"left": 300, "right": 28, "top": 46, "bottom": 30},
            "tooltip": {"trigger": "item", "confine": True, "backgroundColor": "#fff", "borderColor": "#E7E5DC",
                        "textStyle": {"color": "#1F221E", "fontSize": 12},
                        ":formatter": "p => (p.data && p.data.tip) || ''"},
            "xAxis": {"type": "value", "min": 0, "max": days, "interval": 7, "position": "top",
                      "splitLine": {"lineStyle": {"color": "#EEECE4"}}, "axisLine": {"show": False},
                      "axisTick": {"show": False},
                      "axisLabel": {"color": "#8C8A7E", "fontSize": 10,
                                    ":formatter": f"v => ({json.dumps(ticks)})[v] || ''"}},
            "yAxis": {"type": "category", "data": keys, "axisTick": {"show": False},
                      "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                      "axisLabel": {":formatter": f"v => ({json.dumps(labels, ensure_ascii=False)})[v] || ''",
                                    "align": "left", "margin": 290,
                                    "rich": {"oc": {"fontWeight": 700, "fontSize": 12, "color": "#1E7C31"},
                                             "ot": {"fontWeight": 700, "fontSize": 12, "color": "#1F221E"},
                                             "op": {"fontSize": 11, "color": "#6B6A5E", "padding": [0, 0, 0, 4]},
                                             "ic": {"fontSize": 11, "color": "#8C8A7E", "padding": [0, 0, 0, 14]},
                                             "it": {"fontSize": 11.5, "color": "#3A3B35"}}}},
            "series": [
                {**bar, "stack": "i", "data": off_i, "itemStyle": hidden, "silent": True, "tooltip": {"show": False},
                 "markArea": {"silent": True, "data": bands,
                              "label": {"show": True, "position": "insideTop", "color": "#6B6A5E", "fontSize": 11,
                                        "fontWeight": 600, "offset": [0, -40]}},
                 "markLine": {"silent": True, "symbol": "none",
                              "lineStyle": {"color": "#C2410C", "width": 1.5, "type": "solid"},
                              "label": {"formatter": f"Hôm nay {today:%d/%m}", "color": "#C2410C", "fontSize": 10,
                                        "position": "start"},
                              "data": [{"xAxis": today_x}]} if 0 <= today_x <= days else {}},
                {**bar, "stack": "i", "data": len_i, "itemStyle": {"borderRadius": 6}},
                {**bar, "stack": "p", "data": off_p, "itemStyle": hidden, "silent": True, "tooltip": {"show": False}},
                {**bar, "stack": "p", "data": len_p, "itemStyle": {"color": "#2563EB", "borderRadius": 6}},
                {**bar, "barWidth": 5, "stack": "o", "data": off_o, "itemStyle": hidden, "silent": True,
                 "tooltip": {"show": False}},
                {**bar, "barWidth": 5, "stack": "o", "data": len_o, "itemStyle": {"color": "#1F221E", "borderRadius": 3}},
            ],
        }).classes("w-full").style(f"height:{max(220, 24 * len(rows) + 80)}px")

    @ui.refreshable
    def week_block(tasks, late):
        ps, pe = cur_week if view["week"] == "now" else (ws, we)
        with connect() as c:
            p = O.overview(c, today, (ps, pe), cycle=view["cycle"])["period"]
        week_tasks = [t for t in tasks if t["week"] == ps.isoformat()]
        with T.section(ui, f"Tuần {ps:%d/%m} – {pe:%d/%m}", "date_range"):
            if cur_week != (ws, we):
                ui.toggle({"now": "Tuần này", "sel": f"Tuần {ws:%d/%m}"},
                          value=view["week"],
                          on_change=lambda e: (view.update(week=e.value), week_block.refresh())).props(
                    "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                    "sr-seg q-mb-sm")
            period_lists(ui, p, late, "tuần")
            task_table(ui, week_tasks, today, "tuần")

    with body:
        render()


def period_lists(ui, p: dict, late: list[dict], unit: str) -> None:
    """Bốn ô: đến hạn / hoàn thành trong kỳ, trễ hạn, kế hoạch kỳ sau (dùng ở màn OKR và báo cáo tuần/tháng)."""
    with ui.element("div").classes("w-full").style(
            "display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px"):
        note = (f"Sheet không có cột ngày hoàn thành: tính theo ngày tool thấy trạng thái đổi sang Hoàn thành "
                f"(theo dõi từ {_vn(p['tracking_since'])}).") if p["tracking_since"] else ""
        lists = [("Đến hạn", p["due"], "event", ""), ("Hoàn thành", p["done"], "task_alt", note),
                 ("Trễ hạn", late, "warning", "Quá ngày kết thúc, chưa Hoàn thành (tính đến hôm nay)"),
                 (f"{unit.capitalize()} sau", p["next"], "east", "")]
        for title, its, icon, tip in lists:
            with ui.element("div").classes("sr-card q-pa-md").style("border-radius:12px"):
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.icon(icon, size="18px").classes("muted")
                    ui.label(title).classes("text-sm font-semibold")
                    ui.label(str(len(its))).classes("text-xs muted num")
                    if tip:
                        ui.icon("info", size="14px").classes("muted").tooltip(tip)
                if not its:
                    ui.label("Không có").classes("text-sm muted")
                for i in its[:8]:
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        ui.element("span").classes("sr-dot").style(f"background:{STATUS_COLOR[i['status']]}")
                        ui.label(i["code"]).classes("text-xs muted").style("min-width:40px")
                        ui.label(i["title"]).classes("text-sm ellipsis").tooltip(
                            f"{i['title']} · {_vn(i['start'])} – {_vn(i['end'])} · {O.STATUS_LABEL[i['status']]}")
                if len(its) > 8:
                    ui.label(f"và {len(its) - 8} hạng mục khác").classes("text-xs muted")


def task_table(ui, rows: list[dict], today: date, unit: str) -> None:
    ui.label(f"Task {unit} · {len(rows)}").classes("text-sm font-semibold q-mt-md")
    if not rows:
        ui.label("Chưa có task trong sheet").classes("text-sm muted")
        return
    tbl = ui.table(columns=[
        {"name": "okr", "label": "Mã OKR", "field": "okr_code", "align": "left"},
        {"name": "task", "label": "Việc", "field": "task", "align": "left",
         "style": "white-space: normal; min-width: 260px"},
        {"name": "prio", "label": "Ưu tiên", "field": "priority", "align": "center"},
        {"name": "pic", "label": "PIC", "field": "pic", "align": "left"},
        {"name": "dl", "label": "Deadline", "field": "dl", "align": "center"},
        {"name": "st", "label": "Trạng thái", "field": "st", "align": "left"},
        {"name": "warn", "label": "Lưu ý", "field": "warn", "align": "left"},
    ], rows=[{**t, "dl": _vn(t["deadline"]), "st": O.STATUS_LABEL[t["status"]], "warn": _task_warning(t, today)}
             for t in rows], row_key="row").classes("w-full").props("flat bordered dense")
    tbl.add_slot("body-cell-warn", """
        <q-td :props="props"><span style="color:#C2410C; font-weight:600">{{ props.value }}</span></q-td>""")


def okr_report_section(ui, rep) -> None:
    """Khối 'Tiến độ công việc' trong báo cáo tuần/tháng."""
    k = rep.okr
    if not k:
        return
    unit = "tháng" if rep.kind == "month" else "tuần"
    today = date.today()
    cnt, total = k["counts"], k["total"]
    with T.section(ui, "Tiến độ công việc (OKR)", "task_alt",
                   f"Đọc từ Google Sheet của team · đồng bộ {k['synced'][8:10]}/{k['synced'][5:7]}",
                   href="/okr", link_text="Xem chi tiết"):
        with T.kpi_row(ui):
            T.kpi(ui, "flag", "Hoàn thành OKR 3 tháng",
                  f"{cnt[O.DONE] / total * 100:.0f}%" if total else "–", "", None,
                  hint=f"{cnt[O.DONE]} / {total} hạng mục")
            T.kpi(ui, "task_alt", f"Xong trong {unit}", str(len(k["period"]["done"])), "", None, tone="green",
                  hint=f"{len(k['period']['due'])} hạng mục đến hạn trong {unit}")
            T.kpi(ui, "autorenew", "Đang làm", str(cnt[O.DOING]), "", None, tone="blue")
            T.kpi(ui, "warning", "Trễ hạn", str(len(k["late"])), "", None, tone="amber" if k["late"] else "grey",
                  hint="Tính đến hôm nay")
        period_lists(ui, k["period"], k["late"], unit)
        task_table(ui, k["tasks"], today, unit)


def _sheet_issues(items: list[dict], tasks: list[dict], today: date) -> list[dict]:
    """Dòng trên sheet cần người phụ trách cập nhật: quá hạn mà chưa xong, hoặc % tiến độ không khớp trạng thái."""
    out = []
    for i in items:
        if O.is_late(i, today):
            out.append({"kind": "item", "code": i["code"], "text": i["title"], "reason": "Quá hạn",
                        "where": f"OKR · hạn {_vn(i['end'])}"})
        elif i["progress"] is not None and i["progress"] >= 100 and i["status"] != O.DONE:
            out.append({"kind": "item", "code": i["code"], "text": i["title"], "reason": "100% chưa Hoàn thành",
                        "where": "OKR"})
    for t in tasks:
        w = _task_warning(t, today)
        if w and w != "Chưa có deadline":
            out.append({"kind": "task", "code": t["okr_code"], "text": t["task"] or t["item"], "reason": w,
                        "where": f"Task tuần {_vn(t['week'])}" + (f" · hạn {_vn(t['deadline'])}" if t["deadline"]
                                                                    else "")})
    return out


def _task_warning(t: dict, today: date) -> str:
    """Điểm bất thường trong dòng task để người cập nhật sheet sửa."""
    if t["status"] != O.DONE and t["deadline"] and date.fromisoformat(t["deadline"]) < today:
        return "Quá deadline"
    if t["progress"] is not None and t["progress"] >= 100 and t["status"] != O.DONE:
        return "100% nhưng chưa đánh Hoàn thành"
    if not t["deadline"]:
        return "Chưa có deadline"
    return ""
