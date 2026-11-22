"""Trang Quản trị › AI (chỉ Owner): bật / tắt từng tác vụ AI, chọn nhà cung cấp / model, lịch tự chạy, trần số lần
gọi tự động mỗi tháng, chỉnh riêng từng dự án và nhật ký mọi lần gọi AI. Cài đặt lưu ở ai_settings.py; lịch ở
ai_auto.py."""
from contextlib import closing
from datetime import date, datetime, timedelta

from . import ai_settings as AIS
from . import ui_theme as T

TRIGGER = {"manual": "Bấm tay", "auto": "Lịch", "test": "Gọi thử"}
TRI = {None: "Theo chung", True: "Bật", False: "Tắt"}
DAY_ON = "color=deep-purple-1 text-color=deep-purple-9"
DAY_OFF = "color=white text-color=grey-7"


def _months(n: int = 6) -> list[str]:
    d = date.today().replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    return out


def _vn_at(iso: str) -> str:
    from datetime import datetime
    try:
        return f"{datetime.fromisoformat(iso).astimezone():%H:%M %d/%m}"
    except (TypeError, ValueError):
        return ""


def build_ai_admin(ui, base, app_connect, user, local: bool = True, open_key: str | None = None) -> None:
    from . import ai_writer as AW
    from . import db
    from . import integrations as I
    from . import projects as PJ
    with app_connect() as c:
        projects = PJ.list_projects(c)
    I.sync_gateways(base)
    providers = {"auto": "",
                 **{k: I.BY_KEY[k].name for k in I.AI_PROVIDERS if I.configured(base, k)}}
    T.page_header(ui, "smart_toy", "Quản trị AI", "Bật / tắt, model và lịch tự chạy của các tính năng AI.",
                  eyebrow="Quản trị")
    state = {"month": _months()[0], "site": ""}

    # ---------------------------------------------------------------- số tháng này + trần
    @ui.refreshable
    def stats() -> None:
        with AIS._connect() as c:
            s = AIS.summary(c, date.today().strftime("%Y-%m"))
            cap = AIS.cap(c)
        with T.kpi_row(ui):
            T.kpi(ui, "smart_toy", "Lần gọi AI tháng này", f"{s['total']:,}".replace(",", "."),
                  hint=f"{s['total'] - s['auto']} bấm tay · {s['auto']} tự chạy", tone="purple")
            ratio = s["auto"] / cap if cap else 1
            T.kpi(ui, "event_repeat", "Tự chạy / trần tháng", f"{s['auto']} / {cap}",
                  hint="chạm trần thì lịch dừng, bấm tay vẫn chạy",
                  tone="red" if ratio >= 1 else "amber" if ratio >= 0.8 else "green")
            T.kpi(ui, "error_outline", "Lỗi", str(s["errors"]), hint="xem trong nhật ký",
                  tone="red" if s["errors"] else "grey")
            T.kpi(ui, "toll", "Credit Member dùng cho AI", f"{s['credits']:,}".replace(",", "."), tone="lime")
    stats()

    with T.section(ui, "Trần số lần gọi AI tự động mỗi tháng", "speed",
                   "Tính chung mọi dự án. 0 = tắt mọi lịch tự chạy."):
        with AIS._connect() as c:
            cur_cap = AIS.cap(c)
        with ui.row().classes("items-center gap-2"):
            cap_in = ui.number(value=cur_cap, min=0, step=50, format="%.0f").props(
                'outlined dense suffix="lần / tháng"').classes("w-48")

            def save_cap():
                with AIS._connect() as c:
                    AIS.set_cap(c, int(cap_in.value or 0))
                ui.notify("Đã lưu trần", type="positive")
                stats.refresh()
            ui.button("Lưu", icon="check", on_click=save_cap).props("unelevated no-caps dense")

    # ---------------------------------------------------------------- nhà cung cấp AI (khóa)
    with T.section(ui, "Kết nối AI", "key",
                   "Cổng API và nhà cung cấp đã kết nối. Model của chúng dùng để tạo combo ở mục dưới."):
        from .web_settings import ai_provider_cards

        def provider_saved(_it):
            ui.notify("Đang tải lại trang để cập nhật danh sách…")
            ui.timer(1.2, lambda: ui.navigate.to("/quan-tri-ai"), once=True)
        ai_provider_cards(ui, base, app_connect, user, local, on_saved=provider_saved, open_key=open_key)

    # ---------------------------------------------------------------- combo (router)
    with T.section(ui, "Combo AI", "alt_route",
                   "Mỗi combo là danh sách model thử lần lượt: model 1 lỗi (bị chặn, sập, hết giờ chờ, trả sai) thì tool "
                   "chuyển sang model 2, rồi 3… Mỗi tác vụ chọn một combo ở mục Tác vụ AI."):
        with AIS._connect() as c:
            AW.migrate_combos(c, base)
            cstate = [{**x, "steps": [dict(st) for st in x["steps"]]} for x in AIS.combos(c)]
            users = AIS.combo_users(c)
            blk = AIS.block_status(c)
        if blk:
            with ui.row().classes("w-full items-start no-wrap gap-2 sr-aia-block q-mb-sm"):
                ui.icon("error_outline", size="18px")
                with ui.column().classes("gap-0 col"):
                    ui.label(f"Model {blk['name']} · {blk['model']} đang bị chặn từ "
                             f"{_vn_at(blk['at'])}").classes("text-sm font-semibold")
                    ui.label(blk["error"]).classes("text-xs")
                    ui.label(("Đang chạy bằng model kế tiếp trong combo: " + blk["fallback"]) if blk.get("fallback")
                             else "Các model khác trong combo cũng lỗi: tác vụ AI đang dừng.").classes("text-xs")
        step_opts = {k: v for k, v in providers.items() if k != "auto"}

        async def fill_models(sel, key, cur):
            """Nạp danh sách model của nhà cung cấp / cổng vào ô chọn (miễn phí, nhớ 10 phút), kèm giá nếu cổng ghi."""
            from nicegui import run
            cat = await run.io_bound(I.model_catalog, base, key)
            opts = {m["id"]: f"{m['id']}  ·  {m['price']}" if m["price"] else m["id"] for m in cat}
            if cur and cur not in opts:
                opts = {cur: cur, **opts}
            sel.set_options(opts, value=cur or None)
            sel.props(f'label="Model ({len(cat)})"' if cat else 'label="Model (không lấy được danh sách: gõ tên)"')

        async def try_model(row, out):
            from nicegui import run

            from . import ai_http as AH
            chain = AW.fallback_chain(base, [row])
            if not chain:
                out.text = "Chưa có model: gõ tên model"
                out.style(f"color:{T.RED}")
                return
            fb = chain[0]
            out.text = "Đang gọi thử…"
            out.style("color:inherit")
            try:
                await run.io_bound(AH.complete, fb["style"], fb["base"], fb["key"], fb["model"], "Trả lời: OK",
                                   max_tokens=200, timeout=40, allow_cut=True)
            except AH.AIError as e:
                out.text = f"Lỗi: {e}"
                out.style(f"color:{T.RED}")
                return
            out.text = "Dùng được"
            out.style(f"color:{T.GREEN}")

        def combo_options() -> dict:
            return {x["id"]: x["name"] for x in cstate}

        def sync_task_selects():
            opts = combo_options()
            for sel in combo_selects:
                sel.set_options(opts, value=sel.value if sel.value in opts else AIS.DEFAULT_COMBO)

        def save_combo(cb):
            with AIS._connect() as c:
                stored = [x for x in AIS.combos(c) if x["id"] != cb["id"]]
                pos = next((i for i, x in enumerate(cstate) if x["id"] == cb["id"]), len(stored))
                stored.insert(min(pos, len(stored)), cb)
                saved = AIS.save_combos(c, stored)
            fresh = next(x for x in saved if x["id"] == cb["id"])
            cb.update(name=fresh["name"], steps=[dict(st) for st in fresh["steps"]], new=False)
            combos_view.refresh()
            sync_task_selects()
            ui.notify(f"Đã lưu combo {cb['name']}", type="positive", position="bottom-right")

        def remove_combo(cb):
            with ui.dialog() as d, ui.card().style("max-width: 420px; border-radius: 14px"):
                ui.label(f"Xóa combo {cb['name']}?").classes("text-lg font-semibold")
                ui.label("Tác vụ đang dùng combo này sẽ chuyển về combo Mặc định.").classes("text-sm")

                def go():
                    with AIS._connect() as c:
                        AIS.save_combos(c, [x for x in AIS.combos(c) if x["id"] != cb["id"]])
                    cstate.remove(cb)
                    d.close()
                    combos_view.refresh()
                    sync_task_selects()
                    ui.notify(f"Đã xóa combo {cb['name']}", type="positive", position="bottom-right")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Hủy", on_click=d.close).props("flat no-caps")
                    ui.button("Xóa", icon="delete", on_click=go).props("unelevated no-caps color=negative")
            d.open()

        def new_combo():
            with AIS._connect() as c:
                cid = AIS.new_combo_id(c)
            have = {x["id"] for x in cstate}
            n = int(cid[1:])
            while f"c{n}" in have:
                n += 1
            cstate.append({"id": f"c{n}", "name": "Combo mới", "new": True,
                           "steps": [{"provider": next(iter(step_opts)), "model": ""}] if step_opts else []})
            combos_view.refresh()

        def move(cb, i, d):
            j = i + d
            if 0 <= j < len(cb["steps"]):
                cb["steps"][i], cb["steps"][j] = cb["steps"][j], cb["steps"][i]
                combos_view.refresh()

        @ui.refreshable
        def combos_view():
            if not step_opts:
                ui.label("Chưa có cổng / nhà cung cấp nào kết nối: thêm ở mục Kết nối AI phía trên.").classes(
                    "text-sm muted")
                return
            for cb in cstate:
                with ui.element("div").classes("sr-aia-combo"):
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.input("Tên combo", value=cb["name"], on_change=lambda e, cb=cb: cb.update(name=e.value)).props(
                            "outlined dense" + (" readonly" if cb["id"] == AIS.DEFAULT_COMBO else "")).classes("w-56")
                        who = users.get(cb["id"]) or []
                        ui.label(("Dùng cho: " + ", ".join(who)) if who else
                                 ("Chưa lưu" if cb.get("new") else "Chưa tác vụ nào dùng")).classes(
                            "text-xs muted col").style("min-width:0")
                        if cb["id"] != AIS.DEFAULT_COMBO:
                            ui.button(icon="delete_outline", on_click=lambda _, cb=cb: (
                                (cstate.remove(cb), combos_view.refresh()) if cb.get("new") else remove_combo(cb))
                            ).props("flat dense round color=grey-7").tooltip("Xóa combo")
                    if not cb["steps"]:
                        ui.label("Chưa có model nào.").classes("text-sm muted q-mt-xs")
                    for i, row in enumerate(cb["steps"]):
                        with ui.row().classes("w-full items-center gap-2 no-wrap sr-aia-fb"):
                            ui.label(str(i + 1)).classes("sr-aia-fb-n")
                            with ui.row().classes("col items-center gap-2 wrap").style("min-width:0"):
                                ui.select(step_opts, value=row["provider"] if row.get("provider") in step_opts else None,
                                          label="Cổng / nhà cung cấp",
                                          on_change=lambda e, r=row: (r.update(provider=e.value, model=""),
                                                                      combos_view.refresh())).props(
                                    "outlined dense options-dense").classes("w-56")
                                cur = row.get("model") or ""
                                m_in = ui.select({cur: cur} if cur else {}, value=cur or None, label="Model",
                                                 with_input=True, new_value_mode="add-unique", clearable=True,
                                                 on_change=lambda e, r=row: r.update(model=e.value or "")).props(
                                    'outlined dense options-dense '
                                    'input-debounce=0 placeholder="bấm để chọn, hoặc gõ để lọc"').classes(
                                    "col").style("min-width:200px")
                                if row.get("provider") in step_opts:
                                    ui.timer(0.1, lambda s=m_in, k=row["provider"], c=cur: fill_models(s, k, c),
                                             once=True)
                                res = ui.label().classes("text-xs")
                            with ui.row().classes("items-center gap-0 no-wrap"):
                                ui.button(icon="bolt", on_click=lambda _, r=row, lb=res: try_model(r, lb)).props(
                                    "flat dense round").tooltip("Gọi thử 1 câu rất ngắn (tốn vài đồng)")
                                ui.button(icon="arrow_upward", on_click=lambda _, cb=cb, i=i: move(cb, i, -1)).props(
                                    "flat dense round" + (" disable" if i == 0 else "")).tooltip("Thử trước")
                                ui.button(icon="close", on_click=lambda _, cb=cb, i=i: (
                                    cb["steps"].pop(i), combos_view.refresh())).props("flat dense round").tooltip(
                                    "Bỏ model này")
                    with ui.row().classes("w-full items-center justify-between gap-2 q-mt-xs"):
                        ui.button("Thêm model", icon="add", on_click=lambda _, cb=cb: (
                            cb["steps"].append({"provider": next(iter(step_opts)), "model": ""}),
                            combos_view.refresh())).props(
                            "flat dense no-caps" + (" disable" if len(cb["steps"]) >= AIS.MAX_STEPS else ""))
                        ui.button("Lưu combo", icon="check", on_click=lambda _, cb=cb: save_combo(cb)).props(
                            "unelevated no-caps dense")
            ui.button("Tạo combo", icon="add", on_click=new_combo).props("outline dense no-caps q-mt-sm")
        combo_selects: list = []
        combos_view()

    # ---------------------------------------------------------------- từng tác vụ
    with T.section(ui, "Tác vụ AI", "tune", "Áp cho mọi dự án; dự án nào cần khác thì đổi ở mục bên dưới."):
        with ui.element("div").classes("sr-aia-tasks"):
            for task, (name, desc, kind) in AIS.TASKS.items():
                combo_selects.append(task_card(ui, base, task, name, desc, kind, combo_options()))

    # ---------------------------------------------------------------- riêng từng dự án
    with T.section(ui, "Riêng từng dự án", "domain", "Để \"Theo chung\" là dùng cài đặt ở trên."):
        for p in projects:
            site = PJ.config_for(base, p).site_url
            with ui.expansion(p["name"], icon="language", caption=PJ.domain(p["site_url"])).classes(
                    "w-full sr-aia-proj"):
                with AIS._connect() as c:
                    ov = {t: AIS.override(c, site, t) for t in AIS.TASKS}
                with ui.element("div").classes("sr-aia-ovgrid"):
                    ui.label("Tác vụ").classes("sr-aia-th")
                    ui.label("Dùng AI").classes("sr-aia-th")
                    ui.label("Tự chạy").classes("sr-aia-th")
                    for task, (name, _, kind) in AIS.TASKS.items():
                        ui.label(name).classes("text-sm")
                        for key in ("enabled", "auto"):
                            if key == "auto" and not kind:
                                ui.label("–").classes("muted")
                                continue

                            def change(e, site=site, task=task, key=key):
                                v = {"Theo chung": None, "Bật": True, "Tắt": False}[e.value]
                                with AIS._connect() as c:
                                    AIS.save_override(c, site, task, key, v)
                                ui.notify("Đã lưu", type="positive", position="bottom-right")
                            ui.select(list(TRI.values()), value=TRI[ov[task].get(key)], on_change=change).props(
                                "outlined dense options-dense").classes("sr-aia-sel")
                pc = PJ.config_for(base, p)
                try:
                    from . import ai_auto as AU
                    with closing(db.connect(pc.db_path)) as c:
                        rs = AU.runs(c, 8)
                except Exception:  # noqa: BLE001
                    rs = []
                if rs:
                    ui.label("Lần tự chạy gần nhất").classes("text-xs muted q-mt-sm")
                    for r in rs:
                        at = datetime.fromisoformat(r["at"]).astimezone()
                        with ui.row().classes("items-center gap-3 no-wrap"):
                            ui.label(f"{at:%d/%m %H:%M}").classes("text-xs muted num").style("width:80px")
                            ui.label(AIS.TASKS.get(r["task"], (r["task"],))[0]).classes("text-sm").style(
                                "width:200px")
                            ui.label(r["result"]).classes("text-sm ellipsis col").style(
                                "color:#A93A0B" if r["result"].startswith("lỗi") else "")

    # ---------------------------------------------------------------- nhật ký
    with T.section(ui, "Nhật ký gọi AI", "history", "Mỗi lần gọi AI: lúc nào, tác vụ gì, ai chạy, kết quả."):
        names = {PJ.config_for(base, p).site_url: p["name"] for p in projects}
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            ui.toggle({m: f"Th{int(m[5:])}/{m[:4]}" for m in _months()}, value=state["month"],
                      on_change=lambda e: (state.update(month=e.value), log_table.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
            ui.space()
            ui.select({"": "Mọi dự án", **names}, value="", on_change=lambda e: (
                state.update(site=e.value), log_table.refresh())).props("outlined dense").classes("w-56")

        @ui.refreshable
        def log_table() -> None:
            with AIS._connect() as c:
                rows = AIS.calls(c, state["month"], state["site"] or None)
            if not rows:
                ui.label("Chưa có lần gọi nào.").classes("text-sm muted")
                return
            data = [{"id": i, "at": f"{datetime.fromisoformat(r['at']).astimezone():%d/%m %H:%M}",
                     "site": names.get(r["site"], r["site"]), "task": AIS.TASKS.get(r["task"], (r["task"],))[0],
                     "trigger": TRIGGER.get(r["trigger"], r["trigger"]), "user": r["user"],
                     "model": r["model"] or r["provider"], "ok": "Được" if r["ok"] else "Lỗi",
                     "error": r["error"], "credits": r["credits"] or ""} for i, r in enumerate(rows)]
            t = ui.table(columns=[
                {"name": "at", "label": "Lúc", "field": "at", "align": "left"},
                {"name": "site", "label": "Dự án", "field": "site", "align": "left"},
                {"name": "task", "label": "Tác vụ", "field": "task", "align": "left"},
                {"name": "trigger", "label": "Cách chạy", "field": "trigger", "align": "left"},
                {"name": "user", "label": "Người", "field": "user", "align": "left"},
                {"name": "model", "label": "Model", "field": "model", "align": "left"},
                {"name": "ok", "label": "Kết quả", "field": "ok", "align": "left"},
                {"name": "credits", "label": "Credit", "field": "credits", "align": "right"},
            ], rows=data, row_key="id", pagination=20).props("flat dense").classes("w-full sr-bl-table")
            t.add_slot("body-cell-ok", """
                <q-td :props="props"><span :class="props.value === 'Lỗi' ? 'sr-bl-type k-lost' : 'sr-bl-type k-new'">
                  {{ props.value }}<q-tooltip v-if="props.row.error" max-width="360px">{{ props.row.error }}</q-tooltip>
                  </span></q-td>""")
        log_table()


def task_card(ui, base, task: str, name: str, desc: str, kind: str | None, combo_opts: dict):
    """Thẻ một tác vụ; trả ô chọn combo (để trang cập nhật danh sách khi tạo / xóa combo)."""
    with AIS._connect() as c:
        st = AIS.task_settings(c, task)
    with ui.element("div").classes("sr-aia-card"):
        with ui.row().classes("w-full items-start no-wrap gap-3"):
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label(name).classes("sr-aia-name")
                ui.label(desc).classes("text-xs muted")
            on = ui.switch("Đang dùng", value=bool(st["enabled"])).props("dense color=deep-purple-6")
        with ui.row().classes("w-full items-end gap-2 q-mt-sm"):
            combo = ui.select(combo_opts, value=st.get("combo") if st.get("combo") in combo_opts
                              else AIS.DEFAULT_COMBO, label="Combo AI").props(
                "outlined dense options-dense").classes("sr-aia-prov")
            ui.space()
            test_btn = ui.button("Gọi thử", icon="bolt", on_click=lambda: test()).props("flat dense no-caps")
            test_btn.tooltip("Gửi một câu ngắn qua combo này (tốn một lượt rất nhỏ)")
        sch = {}
        if kind:
            with ui.row().classes("w-full items-center gap-3 q-mt-sm sr-aia-sched"):
                sch["auto"] = ui.switch("Tự chạy", value=bool(st.get("auto"))).props("dense color=deep-purple-6")
                if kind == "weekly":
                    days = set(st.get("days") or [])
                    sch["dayset"] = days
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        for i, d in enumerate(AIS.DAYS):
                            b = ui.button(d).props("dense no-caps unelevated " + (DAY_ON if i in days else DAY_OFF)
                                                   ).classes("sr-aia-day")
                            b.on("click", lambda _, i=i, b=b: toggle_day(i, b))
                else:
                    ui.label("Ngày").classes("text-sm muted")
                    sch["day"] = ui.number(value=st.get("day", 1), min=1, max=28, step=1, format="%.0f").props(
                        'outlined dense suffix="hằng tháng"').classes("w-40")
                ui.label("lúc").classes("text-sm muted")
                sch["time"] = ui.input(value=st.get("time", "07:00")).props(
                    'outlined dense mask="##:##" placeholder="07:00"').classes("w-24")
                if "limit" in st:
                    sch["limit"] = ui.number(value=st.get("limit", 5), min=1, max=50, step=1, format="%.0f").props(
                        'outlined dense suffix="từ khóa / lượt"').classes("w-48")
        with ui.row().classes("w-full justify-end q-mt-sm"):
            ui.button("Lưu", icon="check", on_click=lambda: save()).props("unelevated no-caps dense")

    def toggle_day(i: int, b) -> None:
        ds = sch["dayset"]
        if i in ds:
            ds.discard(i)
            b.props(remove=DAY_ON).props(DAY_OFF)
        else:
            ds.add(i)
            b.props(remove=DAY_OFF).props(DAY_ON)

    def save() -> None:
        vals = {"enabled": bool(on.value), "combo": combo.value or AIS.DEFAULT_COMBO}
        if kind:
            hm = (sch["time"].value or "07:00").strip()
            try:
                h, m = hm.split(":")
                assert 0 <= int(h) <= 23 and 0 <= int(m) <= 59
            except (ValueError, AssertionError):
                ui.notify("Giờ chưa đúng, ví dụ 07:00", type="warning")
                return
            vals.update(auto=bool(sch["auto"].value), time=f"{int(h):02d}:{int(m):02d}")
            if kind == "weekly":
                vals["days"] = sorted(sch["dayset"])
            else:
                vals["day"] = int(sch["day"].value or 1)
            if "limit" in sch:
                vals["limit"] = int(sch["limit"].value or 5)
        with AIS._connect() as c:
            AIS.save_task(c, task, vals)
        ui.notify(f"Đã lưu {name}", type="positive", position="bottom-right")

    async def test() -> None:
        from nicegui import run

        from . import ai_http as AH
        from . import ai_writer as AW
        try:
            with AIS._connect() as c:
                cb = next((x for x in AIS.combos(c) if x["id"] == combo.value), None)
            if cb is None:
                raise AW.NoProvider("Combo chưa lưu: bấm Lưu combo trước")
            pr = AW.combo_provider(base, cb)
        except AW.NoProvider as e:
            ui.notify(str(e), type="warning")
            return
        test_btn.props("loading")
        try:
            out = await run.io_bound(AH.ask, pr, "Trả lời đúng một chữ: OK", max_tokens=200, timeout=60,
                                     allow_cut=True)
            AIS.log_call("", task, "test", "Owner", pr, True)
            ui.notify(f"{pr['name']} · {pr['model']} trả lời: {out[:40] or '(trống)'}", type="positive",
                      position="bottom-right", multi_line=True)
        except AH.AIError as e:
            AIS.log_call("", task, "test", "Owner", pr, False, str(e))
            ui.notify(f"Lỗi: {e}", type="negative", multi_line=True, position="bottom-right")
        finally:
            test_btn.props(remove="loading")

    return combo
