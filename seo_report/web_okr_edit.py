"""Trang Sửa OKR (/okr/sua).

Tạo nhanh: một đợt mới tạo được từ mẫu (cả khung mục tiêu + hạng mục, ngày tự tính theo đợt), chép từ đợt cũ, hoặc dán
danh sách. Chi tiết sửa sau ngay trên danh sách: tên, phụ trách, thời gian (thanh thời gian trong đợt), trạng thái
(nhãn màu, bấm để đổi), % tiến độ. Sửa ô nào lưu ô đó; tool tự ghi tab OKRs lên sheet dự án.
"""
from datetime import date, datetime, timedelta

from . import okr as O
from . import ui_theme as T

SEG = "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"
STATUS = {O.TODO: ("Chưa bắt đầu", "grey", "radio_button_unchecked"),
          O.DOING: ("Đang làm", "blue", "timelapse"),
          O.DONE: ("Hoàn thành", "green", "check_circle")}
BAR = {O.TODO: "#B8B6A8", O.DOING: "#2563EB", O.DONE: "#1E7C31"}
QUICK_HINT = ("Mỗi dòng một mục tiêu; hạng mục bắt đầu bằng dấu - ngay dưới mục tiêu của nó. "
              "Thêm “| người phụ trách” ở cuối dòng nếu muốn.\n\n"
              "Ví dụ:\nAudit & nền tảng SEO\n- Audit kỹ thuật | SEO, DEV\n- Audit nội dung | CONTENT\n"
              "Tăng traffic từ Google\n- Viết 10 bài chuẩn SEO | CONTENT")


def _vn(iso: str | None, year: bool = False) -> str:
    if not iso:
        return "–"
    return f"{iso[8:10]}/{iso[5:7]}" + (f"/{iso[:4]}" if year else "")


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last))


def build_okr_edit_page(ui, cfg, connect, user, app_connect=None) -> None:
    right = T.page_header(ui, "edit_note", "Sửa OKR",
                          "Tạo cả đợt từ mẫu trong một bước, chi tiết chỉnh sau ngay trên danh sách. Sửa ô nào lưu ô đó; "
                          "tool tự ghi tab OKRs lên sheet dự án.", eyebrow="Báo cáo công việc")
    with right:
        saved = ui.label("").classes("text-xs muted").props('role="status" aria-live="polite"')
        ui.button("Xong", icon="check", on_click=lambda: ui.navigate.to("/okr")).props(
            "unelevated no-caps no-wrap color=primary").style("white-space:nowrap")

    with connect() as c:
        if not O.tool_owned(c):  # mở thẳng trang sửa: chuyển OKR sang tool (giữ dữ liệu đã đồng bộ)
            O.take_over(c)
    state: dict = {"cycle": None, "open": set(), "closed": set(), "sel": set(), "ext": {}}

    def ok(msg: str = "Đã lưu") -> None:
        saved.text = f"{msg} · {datetime.now():%H:%M:%S}"

    def run(fn, *a, refresh: bool = False, **kw):
        try:
            with connect() as c:
                out = fn(c, *a, **kw)
        except ValueError as e:
            ui.notify(str(e), type="warning", position="bottom-right", classes="sr-toast")
            body.refresh()
            return None
        ok()
        if refresh:
            body.refresh()
        return out if out is not None else True

    def templates() -> list[dict]:
        if app_connect:
            with app_connect() as ac:
                return O.all_templates(ac)
        return O.builtin_templates()

    # ================================================================ tạo đợt mới
    def new_cycle_dialog() -> None:
        with connect() as c:
            cs = O.cycle_list(c)
            every = O.items(c)
        tpls = templates()
        last_end = max((x["end"] for x in cs if x["end"]), default=None)
        start0 = (date.fromisoformat(last_end) + timedelta(days=1)) if last_end else date.today()
        st = {"source": f"tpl:{tpls[0]['key']}" if tpls else "blank", "months": 3,
              "skip": set(), "quick": ""}

        with ui.dialog() as dlg, ui.card().classes("sr-oc-card"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label("Tạo đợt OKR mới").classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')

            # ---- 1. thời gian
            ui.label("1 · Thời gian").classes("sr-oc-step")
            with ui.row().classes("w-full items-end no-wrap gap-2"):
                start = ui.input("Từ ngày", value=start0.isoformat()).props(
                    "outlined dense type=date stack-label").classes("col")
                end = ui.input("Đến ngày", value=(_add_months(start0, 3) - timedelta(days=1)).isoformat()).props(
                    "outlined dense type=date stack-label").classes("col")
            with ui.row().classes("items-center gap-2"):
                ui.label("Độ dài:").classes("text-xs muted")

                def set_len(n: int) -> None:
                    st["months"] = n
                    try:
                        s = date.fromisoformat(start.value)
                    except (TypeError, ValueError):
                        return
                    end.value = (_add_months(s, n) - timedelta(days=1)).isoformat()
                    name.value = suggest()
                lens = ui.toggle({1: "1 tháng", 3: "3 tháng", 6: "6 tháng", 12: "12 tháng"}, value=3,
                                 on_change=lambda e: set_len(e.value)).props(SEG).classes("sr-seg")
                lens.props["aria-label"] = "Độ dài đợt"

            def suggest() -> str:
                try:
                    s = date.fromisoformat(start.value)
                except (TypeError, ValueError):
                    return ""
                q = (s.month - 1) // 3 + 1
                return f"OKR Q{q}/{s.year}" if st["months"] == 3 else f"OKR {st['months']} tháng từ {s:%m/%Y}"
            name = ui.input("Tên đợt", value="").props("outlined dense").classes("w-full q-mt-xs")
            name.value = suggest()
            start.on("change", lambda _: set_len(st["months"]))

            # ---- 2. nội dung ban đầu
            ui.label("2 · Bắt đầu từ").classes("sr-oc-step q-mt-sm")
            opts = [(f"tpl:{t['key']}", t["name"], t.get("desc") or "",
                     f"{len(t['objectives'])} mục tiêu · {sum(len(o.get('items') or []) for o in t['objectives'])} "
                     "hạng mục", "auto_awesome" if not t.get("user") else "bookmark") for t in tpls]
            opts += [(f"copy:{x['name']}", f"Chép đợt “{x['name']}”", "Giữ mục tiêu, hạng mục, phụ trách; trạng thái "
                      "về Chưa bắt đầu, ngày dời theo đợt mới.",
                      f"{sum(1 for i in every if i['cycle'] == x['name'] and i['is_objective'])} mục tiêu · "
                      f"{sum(1 for i in every if i['cycle'] == x['name'] and not i['is_objective'])} hạng mục",
                      "content_copy") for x in cs]
            opts += [("quick", "Dán danh sách", "Gõ / dán nhanh mục tiêu và hạng mục, mỗi dòng một mục.", "",
                      "playlist_add"),
                     ("blank", "Đợt trống", "Tự thêm mục tiêu sau.", "", "crop_square")]

            @ui.refreshable
            def source_view() -> None:
                with ui.element("div").classes("sr-oc-opts").props('role="radiogroup" aria-label="Bắt đầu từ"'):
                    for key, title, desc, meta, icon in opts:
                        on = st["source"] == key
                        b = ui.element("button").classes("sr-oc-opt" + (" on" if on else "")).props(
                            f'type="button" role="radio" aria-checked="{str(on).lower()}"')
                        b.on("click", lambda _, k=key: (st.update(source=k, skip=set()), source_view.refresh()))
                        with b:
                            ui.icon(icon, size="20px").classes("sr-oc-ico").props('aria-hidden="true"')
                            with ui.column().classes("gap-0 col").style("min-width:0"):
                                ui.label(title).classes("sr-oc-title")
                                if desc:
                                    ui.label(desc).classes("sr-oc-desc")
                                if meta:
                                    ui.label(meta).classes("sr-oc-meta")
                            ui.icon("radio_button_checked" if on else "radio_button_unchecked", size="18px").classes(
                                "sr-oc-radio").props('aria-hidden="true"')
                src = st["source"]
                if src.startswith("tpl:"):  # bỏ chọn mục tiêu không cần
                    t = next(t for t in tpls if f"tpl:{t['key']}" == src)
                    ui.label("Mục tiêu sẽ tạo (bỏ tích mục không cần):").classes("text-xs muted q-mt-sm")
                    with ui.element("div").classes("sr-oc-objs"):
                        for k, o in enumerate(t["objectives"]):
                            ui.checkbox(f"O{k + 1} · {o['title']} ({len(o.get('items') or [])} hạng mục)",
                                        value=k not in st["skip"],
                                        on_change=lambda e, k=k: st["skip"].discard(k) if e.value else st["skip"].add(
                                            k)).props("dense")
                elif src == "quick":
                    qa = ui.textarea("Danh sách mục tiêu / hạng mục", value=st["quick"],
                                     placeholder=QUICK_HINT).props("outlined").classes("w-full q-mt-sm sr-oc-quick")
                    count = ui.label("").classes("text-xs muted")

                    def recount() -> None:
                        st["quick"] = qa.value or ""
                        q = O.parse_quick(st["quick"])
                        count.text = (f"{len(q['objectives'])} mục tiêu · "
                                      f"{sum(len(o['items']) for o in q['objectives'])} hạng mục")
                    qa.on_value_change(lambda _: recount())
                    recount()
            source_view()

            err = ui.label("").classes("text-sm text-negative")
            err.props["role"] = "alert"

            def create() -> None:
                src = st["source"]
                try:
                    with connect() as c:
                        O.add_cycle(c, name.value, start.value or None, end.value or None,
                                    copy_from=src[5:] if src.startswith("copy:") else None)
                        res = None
                        if src.startswith("tpl:"):
                            t = next(t for t in tpls if f"tpl:{t['key']}" == src)
                            inc = [k for k in range(len(t["objectives"])) if k not in st["skip"]]
                            res = O.apply_template(c, name.value.strip(), t, include=inc)
                        elif src == "quick":
                            res = O.apply_template(c, name.value.strip(), O.parse_quick(st["quick"]))
                except ValueError as e:
                    err.text = str(e)
                    return
                state["cycle"] = name.value.strip()
                dlg.close()
                ok(f"Đã tạo đợt {state['cycle']}" + (f" · {res['objectives']} mục tiêu, {res['items']} hạng mục"
                                                      if res else ""))
                body.refresh()
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Tạo đợt", icon="add", on_click=create).props("unelevated no-caps color=primary")
        dlg.on("hide", lambda: dlg.delete())
        dlg.open()

    def edit_cycle_dialog(cyc: dict) -> None:
        with ui.dialog() as dlg, ui.card().style("width: 460px; max-width: 94vw; border-radius: 14px"):
            ui.label("Sửa đợt").classes("text-lg font-semibold")
            name = ui.input("Tên đợt", value=cyc["name"]).props("outlined dense").classes("w-full")
            with ui.row().classes("w-full no-wrap gap-2"):
                start = ui.input("Từ ngày", value=cyc.get("start") or "").props(
                    "outlined dense type=date stack-label").classes("col")
                end = ui.input("Đến ngày", value=cyc.get("end") or "").props(
                    "outlined dense type=date stack-label").classes("col")

            def save():
                if run(O.update_cycle, cyc["name"], name.value, start.value or None, end.value or None):
                    state["cycle"] = name.value.strip()
                    dlg.close()
                    body.refresh()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Lưu", on_click=save).props("unelevated no-caps color=primary")
        dlg.on("hide", lambda: dlg.delete())
        dlg.open()

    def save_template_dialog(cyc: dict) -> None:
        with ui.dialog() as dlg, ui.card().style("width: 460px; max-width: 94vw; border-radius: 14px"):
            ui.label("Lưu đợt làm mẫu").classes("text-lg font-semibold")
            ui.label("Lưu khung mục tiêu + hạng mục (tên, nhóm, phụ trách, vị trí thời gian trong đợt) để tạo đợt mới "
                     "cho mọi dự án. Trạng thái và tiến độ không lưu.").classes("text-sm muted")
            nm = ui.input("Tên mẫu", value=cyc["name"]).props("outlined dense").classes("w-full")

            def save():
                if not app_connect:
                    return
                with connect() as c:
                    tpl = O.template_from_cycle(c, cyc["name"])
                try:
                    with app_connect() as ac:
                        O.save_template(ac, nm.value, tpl)
                except ValueError as e:
                    ui.notify(str(e), type="warning", position="bottom-right", classes="sr-toast")
                    return
                dlg.close()
                ok(f"Đã lưu mẫu “{nm.value.strip()}”")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Lưu mẫu", on_click=save).props("unelevated no-caps color=primary")
        dlg.on("hide", lambda: dlg.delete())
        dlg.open()

    def confirm(title: str, text: str, action) -> None:
        with ui.dialog() as dlg, ui.card().style("max-width: 440px; border-radius: 14px"):
            ui.label(title).classes("text-lg font-semibold")
            ui.label(text).classes("text-sm")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Xóa", on_click=lambda: (dlg.close(), action())).props("unelevated no-caps color=negative")
        dlg.on("hide", lambda: dlg.delete())
        dlg.open()

    def paste_items_dialog(o: dict) -> None:
        with ui.dialog() as dlg, ui.card().style("width: 520px; max-width: 94vw; border-radius: 14px"):
            ui.label(f"Thêm nhiều hạng mục vào {o['code']}").classes("text-lg font-semibold")
            ta = ui.textarea("Mỗi dòng một hạng mục", placeholder="Viết 10 bài chuẩn SEO | CONTENT\nTối ưu onpage 20 "
                                                                 "trang | SEO").props("outlined autogrow").classes(
                "w-full")

            def save():
                lines = [x.strip().lstrip("-•+*").strip() for x in (ta.value or "").splitlines()]
                n = 0
                with connect() as c:
                    for x in lines:
                        if x:
                            title, _, pic = x.partition("|")
                            O.add_item(c, o["uid"], title.strip(), pic=pic.strip())
                            n += 1
                dlg.close()
                ok(f"Đã thêm {n} hạng mục")
                body.refresh()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Thêm", icon="add", on_click=save).props("unelevated no-caps color=primary")
        dlg.on("hide", lambda: dlg.delete())
        dlg.open()

    def detail_dialog(it: dict) -> None:
        """Trường ít dùng: mô tả, số lượng, đơn vị, nhóm, link, ghi chú."""
        with ui.dialog() as dlg, ui.card().style("width: 560px; max-width: 94vw; border-radius: 14px"):
            ui.label(f"{it['code']} · chi tiết").classes("text-lg font-semibold")
            f = {"title": ui.input("Hạng mục", value=it["title"]).props("outlined dense").classes("w-full"),
                 "details": ui.textarea("Mô tả việc cần làm", value=it["details"]).props(
                     "outlined dense autogrow").classes("w-full")}
            with ui.row().classes("w-full no-wrap gap-2"):
                f["qty"] = ui.input("Số lượng", value=it["qty"]).props("outlined dense").classes("col")
                f["unit"] = ui.input("Đơn vị", value=it["unit"]).props("outlined dense").classes("col")
                f["grp"] = ui.input("Nhóm", value=it["grp"]).props("outlined dense").classes("col")
            f["link"] = ui.input("Link / bằng chứng", value=it["link"]).props("outlined dense").classes("w-full")
            f["note"] = ui.input("Ghi chú", value=it["note"]).props("outlined dense").classes("w-full")

            def save():
                if run(O.update_item, it["uid"], **{k: (v.value or "") for k, v in f.items()}):
                    dlg.close()
                    body.refresh()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Lưu", on_click=save).props("unelevated no-caps color=primary")
        dlg.on("hide", lambda: dlg.delete())
        dlg.open()

    # ================================================================ danh sách
    def status_pill(it: dict) -> None:
        label, tone, icon = STATUS.get(it["status"], STATUS[O.TODO])
        bg, fg = T.TONES[tone]
        with ui.button().props(f'flat dense no-caps aria-label="Trạng thái {it["code"]}: {label}. Bấm để đổi"').classes(
                "sr-oe-pill").style(f"background:{bg}; color:{fg}"):
            ui.icon(icon, size="15px").props('aria-hidden="true"')
            ui.label(label)
            with ui.menu():
                for s, (lb, tn, ic) in STATUS.items():
                    with ui.menu_item(on_click=lambda _, s=s: run(O.update_item, it["uid"], refresh=True,
                                                                  status=s)).classes("items-center gap-2"):
                        ui.icon(ic, size="16px").style(f"color:{T.TONES[tn][1]}")
                        ui.label(lb).classes("text-sm")

    def time_cell(it: dict, cyc: dict) -> None:
        """Thời gian: chữ ngày + thanh vị trí trong đợt; bấm để sửa ngày."""
        cs, ce = cyc.get("start"), cyc.get("end")
        left = width = None
        if cs and ce and it["start"] and it["end"]:
            total = (date.fromisoformat(ce) - date.fromisoformat(cs)).days + 1
            a = (date.fromisoformat(it["start"]) - date.fromisoformat(cs)).days
            b = (date.fromisoformat(it["end"]) - date.fromisoformat(cs)).days + 1
            left, width = max(0, a / total), max(0.02, min(1, b / total) - max(0, a / total))
        late = O.is_late(it, date.today())
        with ui.button().props(f'flat dense no-caps aria-label="Thời gian {it["code"]}: {_vn(it["start"])} đến '
                               f'{_vn(it["end"])}. Bấm để sửa"').classes("sr-oe-time" + (" late" if late else "")):
            with ui.column().classes("gap-0 w-full items-stretch"):
                with ui.row().classes("items-center no-wrap gap-1"):
                    ui.label(f"{_vn(it['start'])} – {_vn(it['end'])}" if it["start"] or it["end"] else
                             "Chưa có ngày").classes("sr-oe-time-text")
                    if state["ext"].get(it["uid"]):
                        ui.label(f"gia hạn ×{state['ext'][it['uid']]}").classes("sr-oe-ext")
                color = "#C2410C" if late else BAR.get(it["status"], BAR[O.TODO])
                ui.html('<div class="sr-oe-track" aria-hidden="true">'
                        + (f'<i style="left:{left * 100:.1f}%;width:{width * 100:.1f}%;background:{color}"></i>'
                           if left is not None else "") + "</div>").classes("w-full")
            with ui.menu().props('anchor="bottom left" self="top left"'):
                with ui.column().classes("q-pa-sm gap-2").style("width: 260px"):
                    s_ = ui.input("Bắt đầu", value=it["start"] or "").props("outlined dense type=date stack-label")
                    e_ = ui.input("Kết thúc", value=it["end"] or "").props("outlined dense type=date stack-label")
                    ui.button("Lưu ngày", on_click=lambda: run(O.update_item, it["uid"], refresh=True,
                                                               start=s_.value or None, end=e_.value or None)).props(
                        "unelevated no-caps dense color=primary")
                    if it["end"]:
                        ui.separator()
                        ui.label("Gia hạn (ghi nhật ký gia hạn)").classes("text-xs muted")
                        with ui.row().classes("gap-1"):
                            for d_ in (3, 7, 14):
                                ui.button(f"+{d_} ngày", on_click=lambda _, d_=d_: run(
                                    O.extend, [it["uid"]], refresh=True, days=d_, by=str(user))).props(
                                    "outline no-caps dense color=grey-9")
                        log = None
                        with connect() as c:
                            log = O.extensions(c, it["uid"])
                        for x in log[-3:]:
                            ui.label(f"{_vn(x['old_end'])} → {_vn(x['new_end'])}"
                                     + (f" · {x['reason']}" if x["reason"] else "")).classes("text-xs muted")

    def item_row(it: dict, cyc: dict) -> None:
        uid = it["uid"]
        with ui.element("div").classes("sr-oe-row" + (" done" if it["status"] == O.DONE else "")
                                        + (" sel" if uid in state["sel"] else "")).props('role="row"'):
            ui.checkbox(value=uid in state["sel"], on_change=lambda e: toggle_sel([uid], e.value)).props(
                f'dense aria-label="Chọn {it["code"]}"')
            status_pill(it)
            ui.label(it["code"]).classes("sr-oe-code")
            t = ui.input(value=it["title"]).props(f'dense borderless aria-label="Tên hạng mục {it["code"]}"').classes(
                "sr-oe-title")
            t.on("blur", lambda e, t=t: t.value != it["title"] and run(O.update_item, uid, title=t.value))
            pic = ui.input(value=it["pic"], placeholder="Phụ trách").props(
                f'dense borderless aria-label="Người phụ trách {it["code"]}"').classes("sr-oe-pic")
            pic.on("blur", lambda e, p=pic: p.value != it["pic"] and run(O.update_item, uid, pic=p.value))
            time_cell(it, cyc)
            pr = ui.number(value=None if it["progress"] is None else round(it["progress"]), min=0, max=100, step=10,
                           suffix="%", placeholder="–").props(
                f'dense borderless aria-label="% tiến độ {it["code"]}"').classes("sr-oe-pct")
            pr.on("blur", lambda e, p=pr: p.value != it["progress"] and run(O.update_item, uid, progress=p.value))
            with ui.button(icon="more_horiz").props(
                    f'flat round dense size=sm color=grey-8 aria-label="Thêm thao tác cho {it["code"]}"'):
                with ui.menu():
                    ui.menu_item("Chi tiết (mô tả, số lượng, link…)", on_click=lambda: detail_dialog(it))
                    ui.menu_item("Xóa hạng mục", on_click=lambda: confirm(
                        f"Xóa hạng mục {it['code']}?", it["title"], lambda: run(O.delete_item, uid, refresh=True)))

    def add_inline(placeholder: str, label: str, on_add, big: bool = False) -> None:
        with ui.row().classes("w-full items-center no-wrap gap-2 sr-oe-add" + (" big" if big else "")):
            inp = ui.input(placeholder=placeholder).props(f'dense outlined aria-label="{label}"').classes("col")

            def go():
                if not (inp.value or "").strip():
                    return
                if run(on_add, inp.value):
                    body.refresh()
            inp.on("keydown.enter", go)
            ui.button(label, icon="add", on_click=go).props("outline no-caps dense color=grey-9")

    def objective(o: dict, kids: list[dict], cyc: dict) -> None:
        done = sum(1 for k in kids if k["status"] == O.DONE)
        late = sum(1 for k in kids if O.is_late(k, date.today()))
        pct = done / len(kids) if kids else 0
        closed = o["uid"] in state["closed"]
        with ui.element("section").classes("sr-card sr-oe-obj").props(f'aria-label="Mục tiêu {o["code"]}"'):
            with ui.row().classes("items-center no-wrap gap-2 w-full"):
                ui.button(icon="expand_more" if not closed else "chevron_right",
                          on_click=lambda: (state["closed"].symmetric_difference_update({o["uid"]}),
                                            body.refresh())).props(
                    f'flat round dense size=sm color=grey-8 aria-expanded="{str(not closed).lower()}" '
                    f'aria-label="{"Thu gọn" if not closed else "Mở"} {o["code"]}"')
                ui.label(o["code"]).classes("sr-oe-ocode")
                ot = ui.input(value=o["title"]).props(
                    f'dense borderless aria-label="Tên mục tiêu {o["code"]}"').classes("sr-oe-otitle col")
                ot.on("blur", lambda e, ot=ot: ot.value != o["title"] and run(O.update_item, o["uid"], title=ot.value))
                with ui.column().classes("gap-0 items-end sr-oe-oprog"):
                    ui.label(f"{done}/{len(kids)} xong" + (f" · {late} trễ" if late else "")).classes(
                        "text-xs" + (" text-negative" if late else " muted"))
                    ui.html(f'<div class="sr-kp-bar thin" style="width:120px"><i style="width:{pct * 100:.0f}%;'
                            f'background:#1E7C31"></i></div>')
                with ui.button(icon="more_horiz").props(
                        f'flat round dense size=sm color=grey-8 aria-label="Thêm thao tác cho {o["code"]}"'):
                    with ui.menu():
                        ui.menu_item("Thêm nhiều hạng mục (dán danh sách)", on_click=lambda: paste_items_dialog(o))
                        ui.menu_item("Xóa mục tiêu", on_click=lambda: confirm(
                            f"Xóa mục tiêu {o['code']}?", f"Xóa luôn {len(kids)} hạng mục bên trong. Không hoàn tác "
                                                         "được.", lambda: run(O.delete_item, o["uid"], refresh=True)))
            if closed:
                return
            if kids:
                with ui.element("div").classes("sr-oe-grid").props('role="table"'):
                    with ui.element("div").classes("sr-oe-row head").props('role="row"'):
                        all_on = bool(kids) and all(k["uid"] in state["sel"] for k in kids)
                        ui.checkbox(value=all_on, on_change=lambda e: toggle_sel([k["uid"] for k in kids], e.value,
                                                                                 redraw=True)).props(
                            f'dense aria-label="Chọn mọi hạng mục của {o["code"]}"')
                        for h in ("Trạng thái", "Mã", "Hạng mục", "Phụ trách", "Thời gian", "Tiến độ", ""):
                            ui.label(h).props('role="columnheader"')
                    for k in kids:
                        item_row(k, cyc)
            add_inline("Thêm hạng mục: gõ tên rồi Enter", "Thêm", lambda c, v: O.add_item(c, o["uid"], v))

    def toggle_sel(uids: list[str], on: bool, redraw: bool = False) -> None:
        state["sel"] = (state["sel"] | set(uids)) if on else (state["sel"] - set(uids))
        if redraw:
            body.refresh()
        else:
            sel_bar.refresh()

    @ui.refreshable
    def sel_bar() -> None:
        """Thanh thao tác cho các hạng mục đang chọn: đổi trạng thái, gia hạn, xóa."""
        n = len(state["sel"])
        if not n:
            return
        with ui.element("div").classes("sr-oe-selbar").props('role="region" aria-label="Thao tác với mục đã chọn"'):
            ui.label(f"Đã chọn {n} hạng mục").classes("text-sm font-semibold")
            with ui.button("Đổi trạng thái", icon="swap_horiz").props("outline no-caps dense color=white"):
                with ui.menu():
                    for s_, (lb, _, _) in STATUS.items():
                        ui.menu_item(lb, on_click=lambda _, s_=s_: (run(O.set_status_many, list(state["sel"]), s_),
                                                                    body.refresh()))
            extend_menu(ui, connect, user, lambda: list(state["sel"]), body.refresh)
            ui.button("Xóa", icon="delete_outline", on_click=lambda: confirm(
                f"Xóa {n} hạng mục đã chọn?", "Không hoàn tác được.",
                lambda: (run(O.delete_items, list(state["sel"])), state["sel"].clear(), body.refresh()))).props(
                "unelevated no-caps dense color=negative")
            ui.space()
            ui.button("Bỏ chọn", on_click=lambda: (state["sel"].clear(), body.refresh())).props(
                "flat no-caps dense color=white")

    @ui.refreshable
    def body() -> None:
        with connect() as c:
            cs = O.cycle_list(c)
            every = O.items(c)
            state["ext"] = O.extension_counts(c)
        if not cs:
            with ui.element("div").classes("sr-card sr-oe-start"):
                ui.icon("flag", size="34px").style(f"color:{T.GREEN}").props('aria-hidden="true"')
                ui.label("Chưa có đợt OKR nào").classes("text-lg font-semibold")
                ui.label("Tạo đợt từ mẫu là có ngay cả khung mục tiêu và hạng mục, ngày tự tính theo đợt; chi tiết "
                         "chỉnh sau.").classes("text-sm muted")
                ui.button("Tạo đợt OKR", icon="add", on_click=new_cycle_dialog).props(
                    "unelevated no-caps color=primary")
            return
        names = [x["name"] for x in cs]
        if state["cycle"] not in names:
            today = date.today().isoformat()
            cur = next((x["name"] for x in cs if x["start"] and x["end"] and x["start"] <= today <= x["end"]), None)
            state["cycle"] = cur or names[-1]
        cyc = next(x for x in cs if x["name"] == state["cycle"])
        its = [i for i in every if i["cycle"] == cyc["name"]]
        objs = [i for i in its if i["is_objective"]]
        leaf = [i for i in its if not i["is_objective"]]
        done = sum(1 for i in leaf if i["status"] == O.DONE)
        doing = sum(1 for i in leaf if i["status"] == O.DOING)
        late = sum(1 for i in leaf if O.is_late(i, date.today()))

        # ---- thanh đợt: chọn đợt, thời gian, số tổng, thao tác
        with ui.element("div").classes("sr-card sr-oe-cycle"):
            with ui.row().classes("w-full items-center gap-2").style("row-gap:8px"):
                if len(cs) > 1:
                    tg = ui.toggle({n: n for n in names}, value=state["cycle"],
                                   on_change=lambda e: (state.update(cycle=e.value), body.refresh())).props(
                        SEG).classes("sr-seg sr-seg-wrap")
                    tg.props["aria-label"] = "Đợt OKR"
                else:
                    ui.label(cyc["name"]).classes("text-base font-semibold")
                ui.space()
                ui.button("Đợt mới", icon="add", on_click=new_cycle_dialog).props(
                    "outline no-caps dense color=grey-9")
                with ui.button(icon="more_horiz").props('flat round dense color=grey-8 aria-label="Thao tác với đợt"'):
                    with ui.menu():
                        ui.menu_item("Sửa tên / ngày của đợt", on_click=lambda: edit_cycle_dialog(cyc))
                        if app_connect:
                            ui.menu_item("Lưu đợt này làm mẫu", on_click=lambda: save_template_dialog(cyc))
                        ui.menu_item("Xóa đợt", on_click=lambda: confirm(
                            f"Xóa đợt “{cyc['name']}”?", "Xóa luôn mọi mục tiêu và hạng mục của đợt. Không hoàn tác "
                                                         "được.",
                            lambda: (run(O.delete_cycle, cyc["name"]), state.update(cycle=None), body.refresh())))
            with ui.element("div").classes("sr-oe-stats"):
                for label, value, tone in (("Thời gian", f"{_vn(cyc['start'], True)} – {_vn(cyc['end'], True)}", ""),
                                           ("Mục tiêu", str(len(objs)), ""),
                                           ("Hoàn thành", f"{done}/{len(leaf)}", "green"),
                                           ("Đang làm", str(doing), "blue"),
                                           ("Trễ hạn", str(late), "red" if late else "")):
                    with ui.column().classes("gap-0 sr-oe-stat"):
                        ui.label(label).classes("text-xs muted")
                        ui.label(value).classes("sr-oe-stat-num" + (f" {tone}" if tone else ""))
            if leaf:
                ui.html(f'<div class="sr-kp-bar" aria-hidden="true"><i style="width:{done / len(leaf) * 100:.1f}%;'
                        f'background:#1E7C31"></i></div>').classes("w-full")

        alerts_panel(ui, connect, user, True, body.refresh, cyc["name"])
        state["sel"] &= {i["uid"] for i in leaf}
        sel_bar()
        if not objs:
            with ui.element("div").classes("sr-card sr-oe-start"):
                ui.label("Đợt này chưa có mục tiêu").classes("text-base font-semibold")
                ui.label("Thêm từ mẫu cho nhanh, hoặc tự thêm từng mục tiêu bên dưới.").classes("text-sm muted")
                tpls = templates()
                with ui.row().classes("gap-2"):
                    for t in tpls[:3]:
                        ui.button(f"Dùng mẫu “{t['name']}”", icon="auto_awesome",
                                  on_click=lambda t=t: (run(O.apply_template, cyc["name"], t, refresh=True))).props(
                            "unelevated no-caps color=primary")
        for o in objs:
            objective(o, [i for i in leaf if i["objective"] == o["uid"]], cyc)
        add_inline("Thêm mục tiêu mới: gõ tên rồi Enter, ví dụ “Tăng hiện diện trên Google”", "Thêm mục tiêu",
                   lambda c, v: O.add_objective(c, cyc["name"], v), big=True)

    body()


# ================================================================ thông báo OKR (dùng ở trang Sửa OKR và Công việc & OKR)
ALERT_GROUPS = (("late", "Trễ hạn", "red", "event_busy"),
                ("due_soon", f"Đến hạn trong {O.DUE_SOON_DAYS} ngày tới", "amber", "schedule"),
                ("not_started", "Đã tới ngày bắt đầu, chưa bắt đầu", "blue", "play_circle_outline"))


def extend_dialog(ui, connect, user, uids: list[str], on_done, label: str = "") -> None:
    """Gia hạn tới một ngày cụ thể, kèm lý do (lưu trong nhật ký gia hạn)."""
    with ui.dialog() as dlg, ui.card().style("width: 420px; max-width: 94vw; border-radius: 14px"):
        ui.label("Gia hạn" + (f" · {label}" if label else f" {len(uids)} hạng mục")).classes("text-lg font-semibold")
        d = ui.input("Hạn mới", value=(date.today() + timedelta(days=7)).isoformat()).props(
            "outlined dense type=date stack-label").classes("w-full")
        r = ui.input("Lý do (không bắt buộc)", placeholder="Ví dụ: chờ khách duyệt nội dung").props(
            "outlined dense").classes("w-full")

        def save():
            try:
                with connect() as c:
                    n = O.extend(c, uids, new_end=d.value, by=str(user), reason=r.value or "")
            except ValueError as e:
                ui.notify(str(e), type="warning", position="bottom-right", classes="sr-toast")
                return
            dlg.close()
            ui.notify(f"Đã gia hạn {n} hạng mục tới {_vn(d.value, True)}", type="positive", position="bottom-right",
                      classes="sr-toast")
            on_done()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
            ui.button("Gia hạn", icon="update", on_click=save).props("unelevated no-caps color=primary")
    dlg.on("hide", lambda: dlg.delete())
    dlg.open()


def extend_menu(ui, connect, user, uids_fn, on_done, label: str = "Gia hạn", dense: bool = True) -> None:
    """Nút Gia hạn: +3 / +7 / +14 ngày (tính từ hạn cũ; đã quá hạn thì từ hôm nay) hoặc chọn ngày."""
    def go(days: int) -> None:
        uids = uids_fn()
        with connect() as c:
            n = O.extend(c, uids, days=days, by=str(user))
        ui.notify(f"Đã gia hạn {n} hạng mục thêm {days} ngày", type="positive", position="bottom-right",
                  classes="sr-toast")
        on_done()
    with ui.button(label, icon="update").props(f"outline no-caps {'dense' if dense else ''} color=grey-9"):
        with ui.menu():
            for d_ in (3, 7, 14):
                ui.menu_item(f"Thêm {d_} ngày", on_click=lambda _, d_=d_: go(d_))
            ui.menu_item("Chọn ngày + lý do…", on_click=lambda: extend_dialog(ui, connect, user, uids_fn(), on_done))


def alerts_panel(ui, connect, user, ed: bool, on_change, cycle: str | None = None, limit: int = 8,
                 tasks: list[dict] | None = None, note: str = "") -> None:
    """Thông báo của đợt: trễ hạn, sắp đến hạn, tới ngày mà chưa bắt đầu (+ task tuần quá deadline nếu truyền `tasks`);
    người được sửa gia hạn / đánh dấu ngay. Mỗi nhóm hiện `limit` dòng, còn lại mở bằng "Xem tất cả"."""
    with connect() as c:
        a = O.alerts(c, date.today(), cycle)
    if not a["cycle"]:
        return
    tasks = tasks or []
    total = sum(len(a[k]) for k, *_ in ALERT_GROUPS) + len(tasks)
    hidden_rows = 0
    box = ui.element("section").classes("sr-card sr-oa").props('id="okr-alerts" aria-label="Thông báo OKR"')
    with box:
        with ui.row().classes("w-full items-center gap-2"):
            ui.icon("notifications_active" if total else "notifications_none", size="20px").style(
                f"color:{T.AMBER if total else T.GREEN}").props('aria-hidden="true"')
            ui.label("Thông báo OKR").classes("text-base font-semibold")
            for key, label, tone, _ in ALERT_GROUPS:
                if a[key]:
                    T.pill(ui, f"{label.split(',')[0]} {len(a[key])}", tone)
            if tasks:
                T.pill(ui, f"Task tuần {len(tasks)}", "red")
            ui.space()
            if ed and a["late"]:
                extend_menu(ui, connect, user, lambda: [i["uid"] for i in a["late"]], on_change,
                            label=f"Gia hạn cả {len(a['late'])} việc trễ")
        if note:
            ui.label(note).classes("text-xs muted")
        if not total:
            ui.label(f"Đợt {a['cycle']}: không có việc trễ hạn hay sắp đến hạn.").classes("text-sm muted")
            return
        today = date.today()

        def head(icon, tone, text):
            with ui.row().classes("items-center gap-1 q-mt-xs"):
                ui.icon(icon, size="16px").style(f"color:{T.TONES[tone][1]}").props('aria-hidden="true"')
                ui.label(text).classes("text-sm font-semibold")

        for key, label, tone, icon in ALERT_GROUPS:
            if not a[key]:
                continue
            head(icon, tone, f"{label} · {len(a[key])}")
            with ui.element("div").classes("sr-oa-list"):
                for n, it in enumerate(a[key]):
                    hidden_rows += n >= limit
                    with ui.element("div").classes("sr-oa-row" + (" more" if n >= limit else "")):
                        ui.label(it["code"]).classes("sr-oe-code")
                        with ui.column().classes("gap-0 col").style("min-width:0"):
                            ui.label(it["title"]).classes("text-sm ellipsis").tooltip(it["title"])
                            days = (date.fromisoformat(it["end"]) - today).days if it["end"] else None
                            when = ("" if days is None else
                                    f"trễ {-days} ngày" if days < 0 else "hạn hôm nay" if days == 0 else
                                    f"còn {days} ngày")
                            meta = " · ".join(x for x in (
                                f"hạn {_vn(it['end'])}" if it["end"] else "", when, it["pic"] or "",
                                f"đã gia hạn {it['extended']} lần" if it.get("extended") else "") if x)
                            ui.label(meta).classes("text-xs" + (" text-negative" if key == "late" else " muted"))
                        if ed:
                            with ui.row().classes("items-center gap-1 no-wrap"):
                                if key == "not_started":
                                    ui.button("Bắt đầu", icon="play_arrow", on_click=lambda _, u=it["uid"]: (
                                        _set(connect, [u], O.DOING), on_change())).props(
                                        "flat no-caps dense color=primary")
                                else:
                                    extend_menu(ui, connect, user, lambda u=it["uid"]: [u], on_change)
                                ui.button("Xong", icon="check", on_click=lambda _, u=it["uid"]: (
                                    _set(connect, [u], O.DONE), on_change())).props("flat no-caps dense color=positive")
        if tasks:
            head("event_note", "red", f"Task tuần cần cập nhật trên sheet · {len(tasks)}")
            with ui.element("div").classes("sr-oa-list"):
                for n, x in enumerate(tasks):
                    hidden_rows += n >= limit
                    with ui.element("div").classes("sr-oa-row" + (" more" if n >= limit else "")):
                        ui.label(x["code"] or "–").classes("sr-oe-code")
                        with ui.column().classes("gap-0 col").style("min-width:0"):
                            ui.label(x["text"]).classes("text-sm ellipsis").tooltip(x["text"])
                            ui.label(f"{x['reason']} · {x['where']}").classes(
                                "text-xs" + (" text-negative" if "Quá" in x["reason"] else " muted"))
        if hidden_rows:
            btn = ui.button(f"Xem tất cả ({hidden_rows} dòng nữa)", icon="expand_more").props(
                "flat no-caps dense color=grey-9").classes("self-start q-mt-xs")

            def toggle():
                opened = "open" in box.classes
                box.classes(remove="open") if opened else box.classes(add="open")
                btn.text = f"Xem tất cả ({hidden_rows} dòng nữa)" if opened else "Thu gọn"
                btn.props(f"icon={'expand_more' if opened else 'expand_less'}")
            btn.on_click(toggle)


def _set(connect, uids: list[str], status: str) -> None:
    with connect() as c:
        O.set_status_many(c, uids, status)
