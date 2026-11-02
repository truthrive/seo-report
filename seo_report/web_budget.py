"""Màn Ngân sách check rank (Quản trị): chi phí DataForSEO của mọi website trong một màn.

Mỗi website có ngân sách riêng (USD/tháng); chi phí gồm check rank và lấy volume keyword, tính theo tháng dương lịch.
Tài khoản DataForSEO dùng chung: tổng ngân sách các website nên nằm trong số dư tài khoản.
"""
import calendar
from contextlib import closing
from datetime import date

from . import db
from . import keywords as K
from . import projects as PJ
from . import rank as R
from . import ui_theme as T

PROJECT_COLORS = [T.GREEN, T.BLUE, "#7C3AED", "#B7791F", "#0E7C86", "#C2410C", "#5E7414", "#8C8A7E"]


def _usd(v: float | None) -> str:
    return "–" if v is None else R.usd(v)


def projected(spent: float, monthly: float, today: date, paused: bool = False) -> float:
    """Dự kiến cả tháng = đã dùng + phần lịch check còn lại của tháng (không bao giờ thấp hơn số đã dùng)."""
    days = calendar.monthrange(today.year, today.month)[1]
    return spent + (0 if paused else monthly * (days - today.day) / days)


def collect(base, projects: list[dict], today: date | None = None) -> list[dict]:
    """Số liệu ngân sách của từng website: ngân sách, đã dùng tháng này, dự kiến cả tháng, lịch, chi phí 6 tháng."""
    today = today or date.today()
    months = R.last_months(today, 6)
    rows = []
    for p in projects:
        cfg = PJ.config_for(base, p)
        with closing(db.connect(cfg.db_path)) as c:
            st = R.budget_status(c, cfg.site_url, cfg.rank, K.latest_date(c, cfg.site_url), today)
            schedule = R.describe_schedule(R.get_schedule(c))
            hist = R.cost_by_month(c, months)
        budget = st["budget"]
        st["monthly"] = st["estimate"]  # chi phí một tháng đủ theo lịch hiện tại
        st["estimate"] = projected(st["spent"], st["monthly"], today, cfg.rank.paused)
        worst = st["estimate"]
        status = ("paused" if cfg.rank.paused else "off" if not budget
                  else "over" if worst > budget or st["spent"] >= budget
                  else "near" if worst >= budget * R.ALERT_RATIO else "ok")
        rows.append({"project": p, "budget": budget, "spent": st["spent"], "estimate": st["estimate"],
                     "monthly": 0 if cfg.rank.paused else st["monthly"],
                     "keywords": st["stars"], "schedule": schedule, "status": status, "history": hist,
                     "paused": cfg.rank.paused})
    return rows


STATUS = {"ok": ("Trong ngân sách", "green", "check_circle"), "near": ("Gần trần (≥ 80%)", "amber", "warning"),
          "over": ("Vượt ngân sách", "red", "error"), "off": ("Ngân sách 0: không check", "grey", "block"),
          "paused": ("Tạm ngưng", "grey", "pause_circle")}


def build_budget_page(ui, base, app_connect, user) -> None:
    from nicegui import app, run

    T.page_header(ui, "account_balance_wallet", "Ngân sách check rank",
                  "Chi phí DataForSEO (check rank và volume keyword) của từng website, tính theo tháng dương lịch.",
                  eyebrow="Quản trị", tone="grey")
    today = date.today()
    months = R.last_months(today, 6)
    state = {"balance": None, "balance_err": "", "loading": True}

    @ui.refreshable
    def body():
        with app_connect() as c:
            projects = PJ.list_projects(c)
        rows = collect(base, projects, today)
        total_budget = sum(r["budget"] for r in rows)
        total_spent = sum(r["spent"] for r in rows)
        total_est = sum(r["estimate"] for r in rows)  # đã dùng + lịch còn lại (website tạm ngưng không tốn thêm)
        run_rate = sum(r["monthly"] for r in rows)  # chi phí một tháng đủ theo lịch của các website đang chạy

        # ---- Tổng quan ----
        with T.kpi_row(ui):
            T.kpi(ui, "payments", f"Đã dùng tháng {today:%m/%Y}", f"{_usd(total_spent)} USD",
                  hint=(f"{total_spent / total_budget * 100:.1f}% tổng ngân sách".replace(".", ",") if total_budget
                        else "chưa đặt ngân sách"),
                  tone="green")
            T.kpi(ui, "query_stats", "Dự kiến cả tháng", f"{_usd(total_est)} USD",
                  hint="đã dùng + các lần check còn lại theo lịch", tone="blue")
            T.kpi(ui, "savings", "Tổng ngân sách", f"{total_budget:g} USD/tháng", hint=f"{len(rows)} website",
                  tone="lime")
            if state["loading"]:
                bal_value, bal_hint = "…", "Đang hỏi DataForSEO"
            elif state["balance"] is None:
                bal_value, bal_hint = "chưa có", state["balance_err"] or "Chưa nhập tài khoản DataForSEO"
            else:
                bal_value = f"{_usd(state['balance'])} USD"
                months_left = state["balance"] / run_rate if run_rate else None
                bal_hint = (f"đủ khoảng {months_left:.0f} tháng theo lịch check hiện tại"
                            if months_left and months_left < 120 else "tài khoản dùng chung cho mọi website")
            low = state["balance"] is not None and state["balance"] < run_rate
            T.kpi(ui, "account_balance", "Số dư DataForSEO", bal_value, hint=bal_hint, tone="red" if low else "grey")
        if state["balance"] is not None and state["balance"] < run_rate:  # chỉ cảnh báo khi thật sự sắp hết tiền
            T.status_chip(ui, f"Số dư DataForSEO ({_usd(state['balance'])} USD) không đủ cho một tháng check rank "
                              f"theo lịch ({_usd(run_rate)} USD): nạp thêm tiền để check rank không bị dừng giữa "
                              "tháng", "amber", "warning")

        # ---- Theo website ----
        with T.section(ui, f"Theo website · {len(rows)}", "domain",
                       "Thanh: phần đã dùng (đậm) và dự kiến cả tháng (nhạt) so với ngân sách. Đổi ngân sách ngay "
                       "trên dòng."):
            for i, r in enumerate(rows):
                p = r["project"]
                text, tone, icon = STATUS[r["status"]]
                # Lưới cố định cột: website | thanh ngân sách | trạng thái | ô ngân sách | nút
                with ui.element("div").classes("sr-access-row sr-budget-row w-full"):
                    with ui.row().classes("items-center gap-3 no-wrap").style("min-width:0"):
                        T.project_icon(ui, p, 34)
                        with ui.column().classes("gap-0").style("min-width:0"):
                            ui.label(p["name"]).classes("text-sm font-semibold ellipsis")
                            ui.label(f"{r['keywords']} từ khóa").classes("text-xs muted")
                            ui.label(r["schedule"]).classes("text-xs muted ellipsis").tooltip(r["schedule"])
                    with ui.column().classes("gap-1").style("min-width:0"):
                        b = r["budget"] or 1
                        done, ahead = min(r["spent"] / b, 1), min(r["estimate"] / b, 1)
                        color = T.TONES[tone][1]
                        ui.html(f'<div title="Đã dùng {r["spent"] / b * 100:.0f}% · dự kiến {r["estimate"] / b * 100:.0f}%"'
                                f' style="position:relative;height:8px;border-radius:4px;background:#ECEAE2;'
                                f'overflow:hidden"><div style="position:absolute;inset:0 auto 0 0;'
                                f'width:{ahead * 100:.1f}%;background:{color};opacity:.28"></div>'
                                f'<div style="position:absolute;inset:0 auto 0 0;width:{done * 100:.1f}%;'
                                f'background:{color}"></div></div>').classes("w-full")
                        ui.label(f"Đã dùng {_usd(r['spent'])} · dự kiến {_usd(r['estimate'])} / "
                                 f"{r['budget']:g} USD").classes("text-xs muted num")
                    T.status_chip(ui, text, tone, icon)

                    def save(box, s_=p["slug"], name=p["name"]):
                        try:
                            with app_connect() as c:
                                PJ.set_budget(c, s_, box.value, user)
                        except (ValueError, TypeError) as e:
                            ui.notify(str(e), type="warning")
                            return
                        ui.notify(f"{name}: ngân sách {box.value:g} USD/tháng", type="positive")
                        body.refresh()

                    def open_rank(_, s_=p["slug"]):
                        app.storage.user["project"] = s_
                        ui.navigate.to("/rank")

                    def toggle_pause(e, s_=p["slug"], name=p["name"]):
                        with app_connect() as c:
                            PJ.set_paused(c, s_, not e.value, user)
                        ui.notify(f"{name}: {'chạy lại' if e.value else 'tạm ngưng'} check rank", type="positive")
                        body.refresh()

                    # Ô ngân sách + nút Lưu (chỉ sáng khi đã đổi số); công tắc chạy / tạm ngưng có hiệu lực ngay
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        inp = ui.number(value=r["budget"], min=0, step=5, format="%.0f", suffix="USD").props(
                            "outlined dense").classes("w-28").tooltip("Ngân sách USD/tháng")
                        btn = ui.button("Lưu", on_click=lambda _, box=inp, f=save: f(box)).props(
                            "unelevated dense no-caps")
                        btn.disable()
                        inp.on_value_change(lambda e, b=btn, old=r["budget"]: b.set_enabled(
                            e.value is not None and float(e.value) != float(old)))
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.switch("Chạy" if not r["paused"] else "Tạm ngưng", value=not r["paused"],
                                  on_change=toggle_pause).props("dense color=positive").classes("text-xs").tooltip(
                            "Bật: check rank và lấy volume theo lịch. Tắt: tạm ngưng mọi chi phí DataForSEO của "
                            "website này (dữ liệu cũ vẫn giữ). Có hiệu lực ngay, không cần bấm Lưu")
                        ui.button(icon="leaderboard", on_click=open_rank).props(
                            "flat round dense color=grey-8").tooltip("Mở Từ khóa & rank của website này")

        # ---- Chi phí 6 tháng ----
        labels = [f"{m[5:]}/{m[2:4]}" for m in months]
        series = [{"name": r["project"]["name"], "type": "bar", "stack": "c", "barMaxWidth": 34,
                   "itemStyle": {"color": PROJECT_COLORS[i % len(PROJECT_COLORS)]},
                   "data": [round(r["history"][m]["total"], 4) for m in months]} for i, r in enumerate(rows)]
        totals = [sum(r["history"][m]["total"] for r in rows) for m in months]
        with T.section(ui, "Chi phí 6 tháng gần nhất", "bar_chart",
                       f"Tổng 6 tháng {_usd(sum(totals))} USD · gồm check rank và volume keyword"):
            ui.echart({
                "animation": False, "legend": {"bottom": 0, "icon": "roundRect", "itemWidth": 12, "itemHeight": 10,
                                               "textStyle": {"fontSize": 12, "color": "#4A4A40"}},
                "grid": {"left": 48, "right": 12, "top": 14, "bottom": 40},
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                            ":valueFormatter": "v => (v || 0).toLocaleString('vi-VN', {maximumFractionDigits: 3}) "
                                               "+ ' USD'"},
                "xAxis": {"type": "category", "data": labels, "axisTick": {"show": False},
                          "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                          "axisLabel": {"color": "#8C8A7E", "fontSize": 11}},
                "yAxis": {"type": "value", "splitNumber": 4, "splitLine": {"lineStyle": {"color": "#EEECE4"}},
                          "axisLabel": {"color": "#8C8A7E", "fontSize": 11,
                                        ":formatter": "v => v.toLocaleString('vi-VN') + ' $'"}},
                "series": series}).classes("w-full").style("height: 260px")

        with ui.element("div").classes("sr-card q-pa-md w-full").style(f"background:{T.TONES['amber'][0]};"
                                                                       "border-color:#EAD7AE"):
            with ui.row().classes("items-start gap-2 no-wrap"):
                ui.icon("info", size="18px").style(f"color:{T.AMBER}")
                ui.label("Dự kiến cả tháng = đã dùng + các lần check còn lại theo lịch. Một tháng check = số từ khóa × số trang kết quả (mỗi 10 vị trí một trang, theo độ sâu) × giá mỗi "
                         "trang × số lần check trong tháng theo lịch. Tool không cho thêm từ khóa nếu ước tính vượt "
                         "ngân sách, cảnh báo ở 80% và ngừng gửi yêu cầu khi đã dùng chạm ngân sách. Ngân sách 0 là "
                         "tắt check rank cho website đó. Volume keyword (mỗi tháng một lần) tính chung vào ngân sách."
                         ).classes("text-sm")

    async def load_balance():
        creds = R.load_credentials(base.dataforseo_secret)
        if creds:
            try:
                state["balance"] = await run.io_bound(lambda: R.DataForSEO(*creds).balance())
            except Exception as e:  # noqa: BLE001
                state["balance_err"] = f"Không lấy được số dư ({type(e).__name__})"
        state["loading"] = False
        body.refresh()

    body()
    from nicegui import background_tasks
    background_tasks.create(load_balance())
