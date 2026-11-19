"""Bảng có bộ lọc, chọn dòng, sao chép và cột cố định độ rộng (giống bảng Keyword Research), dùng cho các bảng ở trang
Backlink.

- Cột: {"name", "label", "field", "align", "width" (px; không có = cột co giãn lấy phần còn lại), "sortable"}.
- Bộ lọc (chỉ hiện loại có trong `filters`):
    ("text", "Website", ["domain", ...])  → nút Bao gồm / Loại trừ (mỗi dòng hoặc dấu phẩy một cụm)
    ("num", "Uy tín", "rank")             → nút Khoảng số (từ – đến)
    ("enum", "Loại link", "follow")       → nút Loại & trạng thái (chọn nhiều; trường là danh sách thì khớp bất kỳ)
    ("date", "Thấy lần đầu", "first_iso") → nút Khoảng ngày (trường dạng YYYY-MM-DD…)
- Sao chép: các cột `copy` [(tiêu đề, trường)], cách nhau bằng Tab, có dòng tiêu đề: dán vào Google Sheets / Excel là
  ra đúng cột. Chưa chọn dòng nào thì chép mọi dòng đang lọc.
- Trạng thái lọc / chọn lưu trong `st` (dict của người gọi) để vẽ lại bảng không mất bộ lọc.
- `actions`: nút thêm khi đã chọn dòng [{"label": hàm(số dòng) hoặc chữ, "icon", "on": hàm(các dòng đã chọn)}].
- `export`: tên file (không đuôi) → nút "Xuất Excel" (các cột `copy`; đã chọn dòng thì chỉ xuất dòng đã chọn).
"""
import unicodedata

from . import ui_theme as T

PAGE_SIZES = "[25, 50, 100, 0]"


def new_state() -> dict:
    return {"inc": [], "exc": [], "num": {}, "enum": {}, "date": {}, "sel": set()}


def _fold(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "").lower()).replace("đ", "d")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _terms(text: str) -> list[str]:
    return [t.strip() for t in (text or "").replace(",", "\n").split("\n") if t.strip()]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def apply(rows: list[dict], filters: list[tuple], st: dict) -> list[dict]:
    """Các dòng qua mọi bộ lọc đang bật."""
    text_fields = [f for kind, _l, fs in filters if kind == "text" for f in fs]
    inc, exc = [_fold(t) for t in st["inc"]], [_fold(t) for t in st["exc"]]
    out = []
    for r in rows:
        if text_fields and (inc or exc):
            blob = _fold(" ".join(str(r.get(f) or "") for f in text_fields))
            if inc and not any(t in blob for t in inc):
                continue
            if exc and any(t in blob for t in exc):
                continue
        ok = True
        for field, (lo, hi) in st["num"].items():
            v = _num(r.get(field))
            if (lo is not None or hi is not None) and v is None:
                ok = False
            elif lo is not None and v < lo or hi is not None and v > hi:
                ok = False
        for field, want in st["enum"].items():
            if not want:
                continue
            v = r.get(field)
            vals = v if isinstance(v, list) else [v]
            if not any(str(x) in want for x in vals):
                ok = False
        for field, (a, b) in st["date"].items():
            d = str(r.get(field) or "")[:10]
            if (a or b) and not d:
                ok = False
            elif a and d < a or b and d > b:
                ok = False
        if ok:
            out.append(r)
    return out


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "có" if v else ""
    if isinstance(v, float):
        v = int(v) if v == int(v) else round(v, 4)
        return str(v).replace(".", ",")
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v).replace("\t", " ").replace("\n", " ")


def tsv(rows: list[dict], copy: list[tuple[str, str]]) -> str:
    return "\n".join("\t".join(line) for line in
                     [[h for h, _ in copy]] + [[_cell(r.get(f)) for _, f in copy] for r in rows])


def xlsx(rows: list[dict], copy: list[tuple[str, str]], title: str = "Dữ liệu") -> bytes:
    """File Excel một sheet: các cột `copy`, có tiêu đề, bộ lọc, cố định dòng đầu."""
    import io

    from openpyxl import Workbook

    from .export import _sheet
    wb = Workbook()
    wb.remove(wb.active)
    widths = [min(60, max(10, len(h) + 2, *(len(str(r.get(f) or "")) for r in rows[:200]))) for h, f in copy]

    def val(v):
        return ", ".join(str(x) for x in v) if isinstance(v, list) else v
    _sheet(wb, title[:31] or "Dữ liệu", [(h, w, None) for (h, _), w in zip(copy, widths)],
           [[val(r.get(f)) for _, f in copy] for r in rows])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def fixed_columns(columns: list[dict]) -> list[dict]:
    """Độ rộng cột cố định (bảng không co giãn theo nội dung khi đổi bộ lọc / trang)."""
    out = []
    for c in columns:
        c = dict(c)
        w = c.pop("width", None)
        if w:
            style = f"width:{w}px;min-width:{w}px;max-width:{w}px"
            c["style"] = style + (";" + c["style"] if c.get("style") else "")
            c["headerStyle"] = style + (";" + c["headerStyle"] if c.get("headerStyle") else "")
        c.setdefault("sortable", bool(c.get("label")))
        out.append(c)
    return out


def _active(filters: list[tuple], st: dict) -> list[tuple[str, dict]]:
    """[(chữ trên chip, phần cần xóa)] của các bộ lọc đang bật."""
    labels = {f: l for kind, l, f in filters if kind in ("num", "enum", "date")}
    out = []
    if st["inc"]:
        out.append(("Bao gồm: " + ", ".join(st["inc"]), {"inc": []}))
    if st["exc"]:
        out.append(("Loại trừ: " + ", ".join(st["exc"]), {"exc": []}))
    for f, (lo, hi) in st["num"].items():
        if lo is not None or hi is not None:
            fmt = (lambda x: f"{x:g}".replace(".", ","))
            txt = f"{fmt(lo)}–{fmt(hi)}" if lo is not None and hi is not None else (
                f"≥ {fmt(lo)}" if lo is not None else f"≤ {fmt(hi)}")
            out.append((f"{labels.get(f, f)}: {txt}", {"num": f}))
    for f, want in st["enum"].items():
        if want:
            out.append((f"{labels.get(f, f)}: " + ", ".join(sorted(want)), {"enum": f}))
    for f, (a, b) in st["date"].items():
        if a or b:
            vn = (lambda d: f"{d[8:10]}/{d[5:7]}/{d[:4]}" if d else "…")
            out.append((f"{labels.get(f, f)}: {vn(a)} – {vn(b)}", {"date": f}))
    return out


def _drop(st: dict, part: dict) -> None:
    for k, v in part.items():
        if k in ("inc", "exc"):
            st[k] = []
        else:
            st[k].pop(v, None)


def table(ui, *, columns: list[dict], rows: list[dict], row_key: str, filters: list[tuple], st: dict,
          copy: list[tuple[str, str]], slots: dict | None = None, events: dict | None = None, noun: str = "dòng",
          page_size: int = 20, classes: str = "", selectable: bool = True, actions: list[dict] | None = None,
          export: str | None = None) -> None:
    """Vẽ thanh lọc + dòng trạng thái (đếm / đã chọn / sao chép) + bảng. Tự vẽ lại khi đổi lọc / chọn."""

    @ui.refreshable
    def view() -> None:
        shown = apply(rows, filters, st)
        keys = {r[row_key] for r in shown}
        st["sel"] &= {r[row_key] for r in rows}  # bỏ dòng không còn trong bảng
        minw = sum(c.get("width") or 200 for c in columns) + (44 if selectable else 0)  # cột co giãn: tối thiểu 200
        box = ui.element("div").classes("sr-tk-box")  # bộ lọc + thanh đếm + bảng nằm chung một khung
        with box:
            with ui.element("div").classes("sr-tk-tools"):  # lọc + đếm + sao chép / xuất Excel
                bar(shown)
                status(shown, keys)
            tb = ui.table(columns=fixed_columns(columns), rows=shown, row_key=row_key,
                          pagination={"rowsPerPage": page_size}, selection="multiple" if selectable else None).props(
                f'flat dense binary-state-sort :rows-per-page-options="{PAGE_SIZES}" rows-per-page-label="Dòng mỗi '
                f'trang" no-data-label="Không có {noun} nào khớp bộ lọc"').classes(
                "w-full sr-fx " + classes).style(f"--tk-minw:{minw}px")  # bề rộng tối thiểu đặt cho bảng bên trong
            # (table-style của Quasar đặt lên khung cuộn: bảng rộng hơn màn hình bị cắt, không cuộn ngang được)
        if selectable:
            tb.selected = [r for r in shown if r[row_key] in st["sel"]]

            def picked(_=None):
                st["sel"] = (st["sel"] - keys) | {r[row_key] for r in tb.selected}  # dòng đang bị lọc ẩn: giữ
                status.refresh(shown, keys)
            tb.on_select(picked)
        for name, html in (slots or {}).items():
            tb.add_slot(name, html)
        for name, fn in (events or {}).items():
            tb.on(name, fn)

    def changed() -> None:
        view.refresh()

    def drop_btn(label: str, active: str = ""):
        return ui.button(f"{label}: {active}" if active else label).props(
            "flat no-caps dense icon-right=expand_more").classes("sr-fbtn" + (" on" if active else ""))

    def bar(shown: list[dict]) -> None:
        kinds = {k for k, *_ in filters}
        with ui.row().classes("items-center gap-1 sr-tk-bar"):
            if "text" in kinds:
                text_label = next(l for k, l, _ in filters if k == "text")
                for key, name in (("inc", "Bao gồm"), ("exc", "Loại trừ")):
                    b = drop_btn(name, f"{len(st[key])} cụm" if st[key] else "")
                    with b, ui.menu().classes("sr-kr-fmenu") as m:
                        with ui.column().classes("q-pa-sm gap-1").style("width: 280px"):
                            ui.label(f"{name} các dòng có {text_label.lower()} chứa:").classes("text-xs muted")
                            t = ui.textarea(placeholder="Mỗi dòng (hoặc dấu phẩy) một cụm, ví dụ: bao, .vn",
                                            value="\n".join(st[key])).props("outlined dense autogrow").classes(
                                "w-full")
                            with ui.row().classes("w-full justify-between"):
                                ui.button("Bỏ", on_click=lambda m=m, key=key: (st.update({key: []}), m.close(),
                                                                                changed())).props("flat dense no-caps")
                                ui.button("Áp dụng", on_click=lambda m=m, t=t, key=key: (
                                    st.update({key: _terms(t.value)}), m.close(), changed())).props(
                                    "unelevated dense no-caps")
            nums = [(l, f) for k, l, f in filters if k == "num"]
            if nums:
                on_ = [l for l, f in nums if any(v is not None for v in st["num"].get(f, (None, None)))]
                b = drop_btn("Khoảng số", ", ".join(on_))
                with b, ui.menu().classes("sr-kr-fmenu") as m:
                    boxes = {}
                    with ui.column().classes("q-pa-sm gap-1"):
                        for l, f in nums:
                            lo, hi = st["num"].get(f, (None, None))
                            ui.label(l).classes("text-xs muted")
                            with ui.row().classes("gap-2 no-wrap"):
                                boxes[f] = (ui.number(placeholder="Từ", value=lo).props("outlined dense").classes(
                                    "w-28"), ui.number(placeholder="Đến", value=hi).props("outlined dense").classes(
                                    "w-28"))

                        def apply_nums(m, boxes=boxes):
                            st["num"] = {f: (a.value, b_.value) for f, (a, b_) in boxes.items()
                                         if a.value is not None or b_.value is not None}
                            m.close()
                            changed()
                        with ui.row().classes("w-full justify-between"):
                            ui.button("Bỏ", on_click=lambda m=m: (st.update(num={}), m.close(), changed())).props(
                                "flat dense no-caps")
                            ui.button("Áp dụng", on_click=lambda m=m, f_=apply_nums: f_(m)).props("unelevated dense no-caps")
            enums = [(l, f) for k, l, f in filters if k == "enum"]
            if enums:
                on_ = [l for l, f in enums if st["enum"].get(f)]
                b = drop_btn("Loại & trạng thái", ", ".join(on_))
                with b, ui.menu().classes("sr-kr-fmenu") as m:
                    sels = {}
                    with ui.column().classes("q-pa-sm gap-1").style("width: 300px"):
                        for l, f in enums:
                            opts = sorted({str(x) for r in rows for x in (r.get(f) if isinstance(r.get(f), list)
                                                                          else [r.get(f)]) if x not in (None, "")})
                            sels[f] = ui.select(opts, value=sorted(st["enum"].get(f, set()) & set(opts)),
                                                multiple=True, label=l).props(
                                "outlined dense options-dense use-chips").classes("w-full")

                        def apply_enums(m, sels=sels):
                            st["enum"] = {f: set(s.value or []) for f, s in sels.items() if s.value}
                            m.close()
                            changed()
                        with ui.row().classes("w-full justify-between"):
                            ui.button("Bỏ", on_click=lambda m=m: (st.update(enum={}), m.close(), changed())).props(
                                "flat dense no-caps")
                            ui.button("Áp dụng", on_click=lambda m=m, f_=apply_enums: f_(m)).props("unelevated dense no-caps")
            dates = [(l, f) for k, l, f in filters if k == "date"]
            if dates:
                on_ = [l for l, f in dates if any(st["date"].get(f, ("", "")))]
                b = drop_btn("Khoảng ngày", ", ".join(on_))
                with b, ui.menu().classes("sr-kr-fmenu") as m:
                    boxes_d = {}
                    with ui.column().classes("q-pa-sm gap-1"):
                        for l, f in dates:
                            a0, b0 = st["date"].get(f, ("", ""))
                            ui.label(l).classes("text-xs muted")
                            with ui.row().classes("gap-2 no-wrap"):
                                boxes_d[f] = (ui.input(value=a0).props('outlined dense type=date').classes("w-40"),
                                              ui.input(value=b0).props('outlined dense type=date').classes("w-40"))

                        def apply_dates(m, boxes_d=boxes_d):
                            st["date"] = {f: (a.value or "", b_.value or "") for f, (a, b_) in boxes_d.items()
                                          if a.value or b_.value}
                            m.close()
                            changed()
                        with ui.row().classes("w-full justify-between"):
                            ui.button("Bỏ", on_click=lambda m=m: (st.update(date={}), m.close(), changed())).props(
                                "flat dense no-caps")
                            ui.button("Áp dụng", on_click=lambda m=m, f_=apply_dates: f_(m)).props("unelevated dense no-caps")
            act = _active(filters, st)
            for text, part in act:
                T.filter_chip(ui, text, lambda part=part: (_drop(st, part), changed()))
            if act:
                ui.button("Xóa lọc", on_click=lambda: (st.update(inc=[], exc=[], num={}, enum={}, date={}),
                                                          changed())).props(
                    "flat dense no-caps size=sm color=negative")

    @ui.refreshable
    def status(shown: list[dict], keys: set) -> None:
        sel = [r for r in rows if r[row_key] in st["sel"]]
        with ui.row().classes("items-center gap-2 sr-kr-status" + (" on" if sel else "")):
            if sel:
                ui.label(f"Đã chọn {len(sel):,} {noun}".replace(",", ".")).classes("text-sm font-semibold")

                def clear():
                    st["sel"] = set()
                    view.refresh()
                ui.button("Bỏ chọn", on_click=clear).props("flat dense no-caps color=primary")
                ui.element("span").classes("sr-tk-sep")
                # việc chính (nút đầu) nền đậm, việc phụ viền mảnh: không để hai nút đen cạnh nhau
                for i, a in enumerate(actions or []):
                    lab = a["label"](sel) if callable(a["label"]) else a["label"]
                    ui.button(lab, icon=a.get("icon"), on_click=lambda _, a=a, sel=sel: a["on"](sel)).props(
                        "unelevated dense no-caps" if i == 0 else "outline dense no-caps color=grey-9").classes(
                        "sr-tk-act")
                ui.space()
                ui.button("Sao chép", icon="content_copy", on_click=lambda: do_copy(sel)).props(
                    "flat dense no-caps color=primary").tooltip("Chép đủ thông tin, dán vào Google Sheets / Excel")
                if export:
                    ui.button("Xuất Excel", icon="download", on_click=lambda: do_export(sel)).props(
                        "flat dense no-caps color=primary").tooltip("Tải file Excel các dòng đã chọn")
            else:
                ui.label(f"{len(shown):,} / {len(rows):,} {noun}".replace(",", ".") if len(shown) != len(rows)
                         else f"{len(rows):,} {noun}".replace(",", ".")).classes("text-sm col")
                if selectable:
                    ui.label("Tick ô đầu dòng để chọn").classes("text-xs muted gt-sm")
                ui.button(f"Sao chép {len(shown):,} {noun}".replace(",", "."), icon="content_copy",
                          on_click=lambda: do_copy(shown)).props("flat dense no-caps color=primary").tooltip(
                    "Chép mọi dòng đang lọc, dán vào Google Sheets / Excel")
                if export:
                    ui.button("Xuất Excel", icon="download", on_click=lambda: do_export(shown)).props(
                        "flat dense no-caps color=primary").tooltip("Tải file Excel mọi dòng đang lọc")

    def do_export(rs: list[dict]) -> None:
        if not rs:
            return
        from datetime import date
        ui.download.content(xlsx(rs, copy, noun.capitalize()), f"{export}-{date.today():%Y%m%d}.xlsx")

    def do_copy(rs: list[dict]) -> None:
        if not rs:
            return
        ui.clipboard.write(tsv(rs, copy))
        ui.notify(f"Đã sao chép {len(rs):,} {noun} (dán vào Google Sheets / Excel)".replace(",", "."),
                  type="positive")

    view()
