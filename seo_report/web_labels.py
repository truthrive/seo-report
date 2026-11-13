"""Giao diện nhãn website dùng chung cho các bảng (table_kit): cột nhãn, bộ lọc, nút "Gắn nhãn" và hộp gắn nhãn."""
from . import access as A
from . import site_labels as SL

COLUMN = {"name": "labels", "label": "Nhãn", "field": "labels_t", "align": "left", "sortable": True, "width": 150}
FILTER = ("enum", "Nhãn", "labels")
COPY = ("Nhãn", "labels_t")
SLOT = """
<q-td :props="props"><div class="sr-lbl-cell">
  <span v-for="l in props.row.labels_c" :key="l.n" class="sr-lbl"
        :style="{color: l.c, background: l.c + '14', borderColor: l.c + '40'}">{{ l.n }}
    <button v-if="props.row.lbl_edit" type="button" class="sr-lbl-x" :aria-label="'Gỡ nhãn ' + l.n"
            @click.stop="$parent.$emit('unlabel', {d: props.row.lbl_key, l: l.n})">
      <q-tooltip>Gỡ nhãn {{ l.n }} khỏi {{ props.row.lbl_key }}</q-tooltip>✕</button>
  </span>
  <span v-if="!props.row.labels_c || !props.row.labels_c.length" class="muted">–</span>
</div></q-td>"""


def enrich(rows: list[dict], key: str, user=None) -> None:
    """Thêm vào từng dòng: labels (lọc), labels_c (vẽ chip), labels_t (sắp xếp / sao chép) theo website ở `key`;
    lbl_key / lbl_edit để chip có dấu ✕ gỡ nhãn ngay trên bảng (chỉ người được sửa)."""
    try:
        with SL.connect() as c:
            table, colors = SL.all_labels(c), {d["name"]: d["color"] for d in SL.defs(c)}
    except Exception:  # noqa: BLE001  (chưa có file dữ liệu chính, ví dụ test)
        table, colors = {}, {}
    for r in rows:
        labs = SL.lookup(table, r.get(key) or "")
        r["labels"] = labs or ["(chưa gắn)"]
        r["labels_c"] = [{"n": n, "c": colors.get(n, "#4B5563")} for n in labs]
        r["labels_t"] = ", ".join(labs)
        r["lbl_key"] = SL.norm(r.get(key) or "")
        r["lbl_edit"] = bool(labs) and A.can_edit(user)


def action(ui, user, key: str, on_done) -> list[dict]:
    """Nút "Gắn nhãn" cho table_kit (chỉ người được sửa)."""
    if not A.can_edit(user):
        return []
    return [{"label": lambda sel: f"Gắn nhãn · {len({SL.norm(r.get(key)) for r in sel})} website", "icon": "sell",
             "on": lambda sel: dialog(ui, user, [r.get(key) or "" for r in sel], on_done)}]


def events(ui, user, on_done=None) -> dict:
    """Sự kiện cho table_kit: bấm ✕ trên một chip thì gỡ ngay nhãn đó khỏi website của dòng."""
    if not A.can_edit(user):
        return {}

    def un(e) -> None:
        d, lab = (e.args or {}).get("d") or "", (e.args or {}).get("l") or ""
        if not d or not lab:
            return
        with SL.connect() as c:
            SL.apply(c, [d], remove=[lab], user=str(user))
        ui.notify(f"Đã gỡ nhãn {lab} khỏi {d}", type="positive", position="bottom-right")
        if on_done:
            on_done()
    return {"unlabel": un}


def dialog(ui, user, domains: list[str], on_done=None) -> None:
    """Gắn / gỡ nhãn cho các website đã chọn. Ô đánh dấu: có (mọi website đã có), trống (chưa website nào có),
    gạch ngang (một số website có: để nguyên). Thêm nhãn mới ngay trong hộp."""
    doms = sorted({SL.norm(d) for d in domains if SL.norm(d)})
    if not doms:
        return
    with SL.connect() as c:
        table = SL.all_labels(c)
    have = {d: set(table.get(d, [])) for d in doms}
    state: dict[str, bool | None] = {}
    st = {"color": SL.PALETTE[0]}
    with ui.dialog() as d, ui.card().style("width:440px; max-width:94vw; border-radius:14px"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label(f"Gắn nhãn · {len(doms)} website").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        ui.label(", ".join(doms[:6]) + (f" và {len(doms) - 6} website khác" if len(doms) > 6 else "")).classes(
            "text-xs muted ellipsis-2-lines")
        ui.label("Nhãn dùng chung cho mọi dự án và mọi bảng phần Backlink. Tick để gắn, bỏ tick để gỡ nhãn đang "
                 "có, rồi bấm Lưu. Ô gạch ngang: chỉ một số website đang có nhãn, để nguyên thì không đổi.").classes(
            "text-xs muted q-mt-xs")

        @ui.refreshable
        def boxes() -> None:
            with SL.connect() as c:
                labels = SL.defs(c)
            with ui.column().classes("w-full gap-0 q-mt-sm"):
                for lab in labels:
                    n = lab["name"]
                    cnt = sum(1 for x in doms if n in have[x])
                    if n not in state:
                        state[n] = True if cnt == len(doms) else (False if cnt == 0 else None)
                    with ui.row().classes("w-full items-center no-wrap gap-2"):
                        ui.checkbox(value=state[n], on_change=lambda e, n=n: state.update({n: e.value})).props(
                            "dense" + (" toggle-indeterminate" if 0 < cnt < len(doms) else ""))
                        ui.html(f'<span class="sr-lbl" style="color:{lab["color"]};background:{lab["color"]}14;'
                                f'border-color:{lab["color"]}40">{n}</span>')
                        if 0 < cnt < len(doms):
                            ui.label(f"{cnt}/{len(doms)} website").classes("text-xs muted")
        boxes()

        with ui.row().classes("w-full items-center no-wrap gap-1 q-mt-sm"):
            new = ui.input(placeholder="Nhãn mới, ví dụ: Guest post").props(
                f"dense outlined maxlength={SL.MAX_NAME}").classes("col")

            @ui.refreshable
            def swatches() -> None:
                with ui.row().classes("gap-1 no-wrap"):
                    for col in SL.PALETTE[:6]:
                        ui.element("button").classes("sr-lbl-sw" + (" on" if st["color"] == col else "")).style(
                            f"background:{col}").props(f'type="button" aria-label="Màu {col}"').on(
                            "click", lambda _, col=col: (st.update(color=col), swatches.refresh()))
            swatches()

            def add_new() -> None:
                if not (new.value or "").strip():
                    return
                try:
                    with SL.connect() as c:
                        x = SL.add_def(c, new.value, st["color"], str(user))
                except ValueError as e:
                    ui.notify(str(e), type="warning")
                    return
                state[x["name"]] = True
                new.value = ""
                boxes.refresh()
            new.on("keydown.enter", add_new)
            ui.button(icon="add", on_click=add_new).props("flat round dense color=primary").tooltip("Thêm nhãn")

        def save() -> None:
            add = [n for n, v in state.items() if v is True]
            rem = [n for n, v in state.items() if v is False]
            with SL.connect() as c:
                SL.apply(c, doms, add, rem, str(user))
            d.close()
            ui.notify(f"Đã cập nhật nhãn cho {len(doms)} website", type="positive", position="bottom-right")
            if on_done:
                on_done()
        def drop_all() -> None:
            now = sorted({n for x in doms for n in have[x]})
            if not now:
                ui.notify("Các website đang chọn chưa có nhãn nào", type="info", position="bottom-right")
                return
            with SL.connect() as c:
                SL.apply(c, doms, remove=now, user=str(user))
            d.close()
            ui.notify(f"Đã gỡ {len(now)} nhãn khỏi {len(doms)} website", type="positive", position="bottom-right")
            if on_done:
                on_done()
        with ui.row().classes("w-full items-center gap-2 q-mt-md"):
            ui.button("Gỡ hết nhãn", icon="label_off", on_click=drop_all).props(
                "flat no-caps dense color=negative").tooltip(
                f"Gỡ mọi nhãn đang có khỏi {len(doms)} website đã chọn")
            ui.space()
            ui.button("Hủy", on_click=d.close).props("flat no-caps")
            ui.button("Lưu", icon="check", on_click=save).props("unelevated no-caps")
    d.on("hide", d.delete)
    d.open()
