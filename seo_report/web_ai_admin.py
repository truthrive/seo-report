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


def build_ai_admin(ui, base, app_connect, user) -> None:
    from . import db
    from . import integrations as I
    from . import projects as PJ
    with app_connect() as c:
        projects = PJ.list_projects(c)
    providers = {"auto": "Tự chọn (nhà cung cấp đầu tiên có khóa)",
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

    # ---------------------------------------------------------------- từng tác vụ
    with T.section(ui, "Tác vụ AI", "tune", "Áp cho mọi dự án; dự án nào cần khác thì đổi ở mục bên dưới."):
        with ui.element("div").classes("sr-aia-tasks"):
            for task, (name, desc, kind) in AIS.TASKS.items():
                task_card(ui, base, task, name, desc, kind, providers)

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


def task_card(ui, base, task: str, name: str, desc: str, kind: str | None, providers: dict) -> None:
    with AIS._connect() as c:
        st = AIS.task_settings(c, task)
    with ui.element("div").classes("sr-aia-card"):
        with ui.row().classes("w-full items-start no-wrap gap-3"):
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label(name).classes("sr-aia-name")
                ui.label(desc).classes("text-xs muted")
            on = ui.switch("Đang dùng", value=bool(st["enabled"])).props("dense color=deep-purple-6")
        with ui.row().classes("w-full items-end gap-2 q-mt-sm"):
            prov = ui.select(providers, value=st.get("provider") if st.get("provider") in providers else "auto",
                             label="Nhà cung cấp").props("outlined dense options-dense").classes("sr-aia-prov")
            model = ui.input("Model", value=st.get("model", ""), placeholder="để trống: theo Cài đặt tích hợp").props(
                "outlined dense").classes("col")
            test_btn = ui.button("Gọi thử", icon="bolt", on_click=lambda: test()).props("flat dense no-caps")
            test_btn.tooltip("Gửi một câu ngắn để kiểm tra model (tốn một lượt rất nhỏ)")
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
        vals = {"enabled": bool(on.value), "provider": prov.value or "auto", "model": (model.value or "").strip()}
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
        p, mdl = prov.value or "auto", (model.value or "").strip()
        try:
            if p == "auto":
                pr = AW.provider(base)
                pr["model"] = mdl or pr["model"]
            else:
                s = AH.settings_for(base, p)
                if not s:
                    raise AW.NoProvider("Nhà cung cấp này chưa có khóa")
                pr = {"name": providers[p], **s, "model": mdl or s["model"] or AW.DEFAULT_MODEL.get(p, "")}
                if not pr["model"]:
                    raise AW.NoProvider("Chưa có model")
        except AW.NoProvider as e:
            ui.notify(str(e), type="warning")
            return
        test_btn.props("loading")
        try:
            out = await run.io_bound(AH.complete, pr["style"], pr["base"], pr["key"], pr["model"],
                                     "Trả lời đúng một chữ: OK", "", 20, 60)
            AIS.log_call("", task, "test", "Owner", pr, True)
            ui.notify(f"Model trả lời: {out[:40]}", type="positive", position="bottom-right")
        except AH.AIError as e:
            AIS.log_call("", task, "test", "Owner", pr, False, str(e))
            ui.notify(f"Lỗi: {e}", type="negative", multi_line=True, position="bottom-right")
        finally:
            test_btn.props(remove="loading")
