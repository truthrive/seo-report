"""Trang Research từ khóa (/research, nhóm SEO, chỉ team): ý tưởng từ khóa của Google Keyword Planner (Google Ads API,
miễn phí) từ từ khóa gốc, một trang hoặc cả website (của mình / đối thủ); đối chiếu Search Console và danh sách theo
dõi hạng; thêm từ khóa đã chọn vào bộ theo dõi hạng (lúc đó mới tốn tiền check rank); xuất Excel."""
import io
import json
from datetime import datetime

from . import access as A
from . import keyword_overview as KO
from . import keyword_research as KR
from . import keywords as K
from . import ui_theme as T

INTENT_FULL = {"I": "Thông tin", "N": "Điều hướng", "C": "Cân nhắc mua", "T": "Mua / giao dịch"}
COMP = {"LOW": ("Thấp", "k-new"), "MEDIUM": ("Vừa", "k-kw"), "HIGH": ("Cao", "k-lost")}
HINT = {"list": "Chỉ lấy số của đúng các từ khóa đã nhập (không thêm ý tưởng). Muốn thêm ý tưởng liên quan: chọn "
                "Từ khóa gốc. Enter để tìm, Shift+Enter để xuống dòng.",
        "keywords": "Dán thẳng cột từ khóa từ Google Sheets / Excel (mỗi dòng một từ khóa, tối đa 100). Enter để "
                    "tìm, Shift+Enter để xuống dòng.",
        "url": "Địa chỉ một trang (của mình hoặc đối thủ): Google gợi ý từ khóa theo nội dung trang đó.",
        "site": "Tên miền (của mình hoặc đối thủ), ví dụ doithu.vn: Google gợi ý từ khóa theo cả website.",
        "rank_url": "Dán một URL. Trang của site: mọi từ khóa Search Console ghi nhận cho trang đó (28 ngày). Trang "
                    "đối thủ: các từ khóa trong bộ theo dõi hạng mà trang đó đang lên (lần check gần nhất)."}


def build_research_page(ui, cfg, connect, user, open_id: int | None = None, lookup: str = "",
                        preset: tuple[str, str] | None = None, view: dict | None = None) -> None:
    """preset = (cách tìm, nội dung): mở từ tab Tổng quan từ khóa (bấm từ khóa / website / URL) → tự tìm luôn."""
    from nicegui import run
    site = cfg.site_url
    ed = A.can_edit(user)
    state = {"mode": "keywords", "seed": "", "rec": None, "q": "",
             "f": json.loads(json.dumps(KR.FILTER_DEFAULT)),
             "view": "list", "shown_groups": 30, "sel": [], "kind": "all", "match": "all", "word": None,
             "wsort": "count", "word_label": "",
             "busy": False, "hidden": _hidden_cols()}
    if lookup:  # mở từ màn Hiệu suất URL / Tổng quan từ khóa: Tra URL
        preset = ("rank_url", lookup)
    for k, v in (view or {}).items():  # từ tab Tổng quan: "Xem tất cả" biến thể (khớp rộng) / câu hỏi
        if (k == "match" and v in ("broad", "phrase")) or (k == "kind" and v == "questions") \
                or (k == "view" and v == "groups"):
            state[k] = v
    auto = None
    if preset and preset[1].strip():
        state["mode"], state["seed"] = preset
        with connect() as c:
            auto = KR.find_recent(c, *preset)
        if auto:
            open_id = auto
    with connect() as c:
        if open_id:
            state["rec"] = KR.get(c, cfg, open_id)
        from . import aio
        rivals = [b for b in aio.brands(c, cfg) if not b["own"] and b["domains"]]

    async def go(btn=None) -> None:
        if not ed or state["busy"]:
            return
        try:
            KR.parse_seed(state["mode"], state["seed"])
        except ValueError as ex:
            ui.notify(str(ex), type="warning")
            return
        state["busy"] = True
        results.refresh()
        if btn:
            btn.props("loading")
        note = ui.notification(f"Đang tìm ý tưởng cho “{state['seed'][:60]}”…", spinner=True, timeout=None,
                               type="ongoing", position="bottom-right")
        from contextlib import closing

        from . import db

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                return KR.research(c, cfg, state["mode"], state["seed"], str(user))
        try:
            state["rec"] = await run.io_bound(work)
            reset_view()
            ui.run_javascript(f"history.replaceState(null, '', '/research?id={state['rec']['id']}')")
        except Exception as ex:  # noqa: BLE001
            ui.notify(str(ex), type="warning", multi_line=True)
        finally:
            state["busy"] = False
            note.dismiss()
            if btn:
                btn.props(remove="loading")
        head.refresh()
        side.refresh()
        results.refresh()

    keep = dict(view or {})

    def toggle_col(key: str, show: bool) -> None:
        state["hidden"].discard(key) if show else state["hidden"].add(key)
        try:
            from nicegui import app
            app.storage.user["kr_hidden_cols"] = sorted(state["hidden"])
        except Exception:  # noqa: BLE001
            pass
        table.refresh()

    def reset_view() -> None:
        """Lần research mới / mở lần khác: bỏ hết bộ lọc, ô tìm nhanh, từ khóa đã chọn (lọc của lần trước không áp
        sang danh sách mới)."""
        state.update(f=json.loads(json.dumps(KR.FILTER_DEFAULT)), q="", sel=[], shown_groups=30, word=None,
                     word_label="", kind=keep.get("kind", "all"), match=keep.get("match", "all"))
        keep.clear()

    def open_rec(rid: int) -> None:
        reset_view()
        with connect() as c:
            state["rec"] = KR.get(c, cfg, rid)
        ui.run_javascript(f"history.replaceState(null, '', '/research?id={rid}')")
        head.refresh()
        side.refresh()
        results.refresh()

    def confirm_drop(rid: int, seed_: str) -> None:
        with ui.dialog() as dlg, ui.card().style("max-width: 420px; border-radius: 14px"):
            ui.label("Xóa lần tìm này?").classes("text-lg font-semibold")
            ui.label(f"“{seed_[:80]}” sẽ bị xóa khỏi lịch sử. Có thể tìm lại bất cứ lúc nào (miễn phí).").classes(
                "text-sm")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Xóa", on_click=lambda: (dlg.close(), drop_rec(rid))).props(
                    "unelevated no-caps color=negative")
        dlg.open()

    def drop_rec(rid: int) -> None:
        with connect() as c:
            KR.delete(c, rid)
        if state["rec"] and state["rec"]["id"] == rid:
            state["rec"] = None
            head.refresh()
            results.refresh()
        side.refresh()

    def set_mode(m: str, manual: bool = True) -> None:
        both = {state["mode"], m} <= {"keywords", "list"}
        state["mode"] = m
        if manual:
            state["mode_manual"] = True
        if both and ui_refs.get("hint"):
            ui_refs["hint"].text = HINT[m]
            if ui_refs.get("mode") and ui_refs["mode"].value != m:
                ui_refs["mode"].value = m
            return
        form.refresh()
        ui.run_javascript("setTimeout(() => document.querySelector('.sr-kr-search input:not([readonly])')?.focus(), 50)")

    ui_refs: dict = {}

    def fill_site(host: str) -> None:
        state["mode"], state["seed"] = "site", host
        form.refresh()

    # ---- Thanh tìm kiếm (kiểu Keyword Magic Tool): chọn cách tìm · ô nhập một dòng · Tìm · Lịch sử ----
    @ui.refreshable
    def head() -> None:
        rec = state["rec"]
        seeds = KR.split_keywords(rec["seed"]) if rec and rec["mode"] in ("keywords", "list") else []
        seed = f"{len(seeds)} từ khóa" if len(seeds) > 1 else (seed_label(rec["seed"]) if rec else "")
        ui.html('<h1 class="sr-title sr-kr-h1" style="margin:0">Ý tưởng từ khóa'
                + (f': <span class="soft">{_esc(seed)}</span>' if rec else "") + "</h1>")
        if len(seeds) > 1:
            ui.label(", ".join(seeds)).classes("text-sm sr-kr-seedline").tooltip("\n".join(seeds)).props(
                'aria-label="Các từ khóa đã nhập"')
        if rec:
            with ui.row().classes("items-center gap-2 no-wrap"):
                T.flag(ui)
                ui.label(f"{rec['currency']} · {KR.MODES[rec['mode']]} · "
                         f"{datetime.fromisoformat(rec['at']).astimezone():%H:%M %d/%m/%Y} · "
                         f"{rec['by'].split('@')[0]}").classes("text-sm muted")
        else:
            ui.label("Tìm hàng trăm từ khóa liên quan từ Google Keyword Planner (miễn phí): volume, xu hướng, CPC, "
                     "mục đích; đối chiếu với Search Console.").classes("text-sm muted")

    with ui.column().classes("w-full gap-1 q-mb-md"):
        head()

    @ui.refreshable
    def form() -> None:
        with ui.row().classes("w-full items-center no-wrap gap-2 sr-kr-search"):
            ui_refs["mode"] = ui.select(KR.MODES, value=state["mode"],
                                        on_change=lambda e: set_mode(e.value) if e.value != state["mode"] else None).props(
                "outlined dense options-dense").classes("sr-kr-mode").props('aria-label="Cách tìm"')
            ph = {"keywords": "Gõ hoặc dán danh sách từ khóa (mỗi dòng một từ khóa, tối đa 100)",
                  "list": "Gõ hoặc dán danh sách từ khóa (mỗi dòng một từ khóa, tối đa 100)",
                  "url": "https://… (một trang của mình hoặc đối thủ)",
                  "site": "tên miền, ví dụ doithu.vn", "rank_url": "Dán URL cần xem từ khóa đang có hạng"}
            if state["mode"] in ("keywords", "list"):
                inp = ui.textarea(placeholder=ph[state["mode"]], value=state["seed"]).props(
                    'outlined dense autogrow rows=1 clearable').classes("col sr-kr-kwbox")
            else:
                inp = ui.input(placeholder=ph[state["mode"]], value=state["seed"]).props(
                    "outlined dense clearable").classes("col")
            inp.props('aria-label="Từ khóa / URL / website"')
            count = ui.label().classes("sr-kr-count")

            def on_seed(e):
                state["seed"] = e.value or ""
                n = len(KR.split_keywords(state["seed"])) if state["mode"] in ("keywords", "list") else 0
                count.text = f"{n}/{KR.MAX_SEEDS}" if n > 1 else ""
                count.classes(replace="sr-kr-count" + (" over" if n > KR.MAX_SEEDS else ""))
                # dán / gõ nhiều từ khóa → tự chuyển sang "Danh sách từ khóa" (chỉ check đúng list), trừ khi người
                # dùng đã tự chọn lại "Từ khóa gốc"
                if n > 1 and state["mode"] == "keywords" and not state.get("mode_manual"):
                    set_mode("list", manual=False)
                elif n <= 1 and state["mode"] == "list" and not state.get("mode_manual"):
                    set_mode("keywords", manual=False)
            inp.on_value_change(on_seed)
            if ed:
                b = ui.button("Tìm", icon="search").props("unelevated no-caps")
                b.on_click(lambda: go(b))
                # Enter = Tìm; Shift+Enter = xuống dòng (ô danh sách từ khóa)
                inp.on("keydown", lambda: go(b), js_handler="(e) => { if (e.key === 'Enter' && !e.shiftKey && "
                                                            "!e.isComposing) { e.preventDefault(); emit(); } }")
            hist_btn = ui.button("Lịch sử", icon="history").props("flat no-caps")
            with hist_btn, ui.menu().classes("sr-kr-fmenu"):
                side()
        with ui.row().classes("w-full items-center gap-2 q-mt-xs"):
            ui_refs["hint"] = ui.label(HINT[state["mode"]]).classes("text-xs muted col")
            try:
                from . import google_ads as GA
                ui.label(f"Google Ads hôm nay còn {max(0, GA.cap() - GA.used()):,} lượt".replace(",", ".")).classes(
                    "text-xs muted")
            except Exception:  # noqa: BLE001
                pass
        if state["mode"] == "site":
            with ui.row().classes("gap-1 items-center"):
                from .projects import domain
                own = domain(site)
                ui.button(own, on_click=lambda h=own: fill_site(h)).props("outline dense no-caps size=sm rounded")
                for b_ in rivals[:10]:
                    ui.button(b_["name"], on_click=lambda h=b_["domains"][0]: fill_site(h)).props(
                        "flat dense no-caps size=sm rounded color=grey-8").tooltip(b_["domains"][0])
        if not ed:
            ui.label("Chỉ người có quyền sửa chạy research; bạn mở được các lần đã tìm ở nút Lịch sử.").classes(
                "text-xs muted")

    @ui.refreshable
    def side() -> None:
        with ui.column().classes("q-pa-sm gap-0").style("width: 380px; max-height: 420px; overflow-y: auto"):
            ui.label("Đã tìm gần đây").classes("text-sm font-semibold q-mb-xs")
            with connect() as c:
                hist = KR.history(c)
            if not hist:
                ui.label("Chưa có.").classes("text-sm muted")
            for h in hist[:20]:
                on = state["rec"] and state["rec"]["id"] == h["id"]
                with ui.row().classes("w-full items-center no-wrap gap-1 sr-kr-hrow" + (" on" if on else "")):
                    with ui.column().classes("gap-0 col cursor-pointer").style("min-width:0") as col:
                        ui.label(seed_label(h["seed"])).classes("text-sm ellipsis")
                        ui.label(f"{KR.MODES[h['mode']]} · {h['n']} từ khóa · "
                                 f"{datetime.fromisoformat(h['at']).astimezone():%d/%m %H:%M}").classes(
                            "text-xs muted")
                    col.props("tabindex=0 role=button")
                    col.props["aria-label"] = f"Mở lần tìm {seed_label(h['seed'])}"
                    col.on("click", lambda i=h["id"]: open_rec(i))
                    col.on("keydown.enter", lambda i=h["id"]: open_rec(i))
                    if ed:
                        with ui.button(icon="more_horiz").props(
                                'flat round dense color=grey-7 aria-label="Thêm thao tác"').tooltip("Thêm thao tác"):
                            with ui.menu():
                                ui.menu_item("Xóa lần tìm này", on_click=lambda i=h["id"], t=h["seed"]:
                                             confirm_drop(i, t)).classes("text-negative")

    with ui.element("div").classes("sr-card q-pa-md w-full q-mb-md"):
        form()

    def base_rows() -> list[dict]:
        """Sau bộ lọc, Tất cả / Câu hỏi, kiểu khớp và Tìm nhanh (chưa tính từ đang chọn ở cột trái)."""
        rec = state["rec"]
        rows = KR.apply_filters(rec["rows"], state["f"])
        if state["kind"] == "questions":
            rows = [r for r in rows if r.get("question")]
        if rec["mode"] == "keywords" and state["match"] != "all":
            rows = KR.match_rows(rows, rec["seed"], state["match"])
        q = K.fold(state["q"]) if state["q"] else ""
        return [r for r in rows if not q or q in K.fold(r["keyword"])]

    def shown_rows() -> list[dict]:
        rows = base_rows()
        if state["word"]:
            rows = [r for r in rows if state["word"] in KR.word_set(r["keyword"])]
        return rows

    def export_rows() -> list[dict]:
        """File xuất = đúng danh sách đang hiện theo bộ lọc hiện tại (kể cả ô Tìm nhanh)."""
        return shown_rows()

    def filter_summary() -> list[tuple[str, str]]:
        """Các bộ lọc đang bật, dạng (tên, giá trị) để ghi vào file xuất."""
        f, out = state["f"], []
        names = {"I": "Thông tin", "N": "Điều hướng", "C": "Cân nhắc mua", "T": "Mua / giao dịch"}

        def rg(v):
            lo, hi = v
            fmt = (lambda x: f"{x:,.0f}".replace(",", "."))
            return f"{fmt(lo)}–{fmt(hi)}" if lo is not None and hi is not None else (
                f"từ {fmt(lo)}" if lo is not None else f"đến {fmt(hi)}")
        if f["vol"] != [None, None]:
            out.append(("Số lượng tìm kiếm", rg(f["vol"])))
        if f["comp"]:
            out.append(("Cạnh tranh", ", ".join(COMP[c][0] for c in f["comp"])))
        if f["intent"]:
            out.append(("Mục đích", ", ".join(names[i] for i in f["intent"])))
        if f["cpc"] != [None, None]:
            out.append((f"CPC ({state['rec']['currency']})", rg(f["cpc"])))
        if f["inc"]:
            out.append(("Bao gồm (" + ("tất cả" if f["inc_all"] else "bất kỳ") + ")", ", ".join(f["inc"])))
        exc = [x for x, on in (("đã theo dõi hạng", f["exc_tracked"]), ("thương hiệu của mình", f["exc_brand"]),
                               ("thương hiệu đối thủ", f["exc_rival"])) if on] + f["exc"]
        if exc:
            out.append(("Loại bỏ", ", ".join(exc)))
        if f["words"] != [None, None]:
            out.append(("Số từ", rg(f["words"])))
        if f["site"] != "all":
            out.append(("Thứ hạng site", KR.SITE_FILTERS[f["site"]]))
        if f["trend"] != "all":
            out.append(("Xu hướng", KR.TREND_FILTERS[f["trend"]]))
        if f["question"]:
            out.append(("Chỉ câu hỏi", "Có"))
        if state["q"]:
            out.append(("Tìm nhanh", state["q"]))
        return out

    def grid(rows: list[dict]) -> tuple[list[str], list[list]]:
        """Bảng đầy đủ của các từ khóa (dùng chung cho file xuất và Sao chép): tiêu đề + từng dòng."""
        groups = KR.clusters(rows, site)
        group_of = {id(r): g["name"] for g in groups for r in g["rows"]}
        months = next((r["monthly"] for r in rows if r["monthly"]), [])
        head = ["Từ khóa", "Volume/tháng", "Cạnh tranh", "Chỉ số cạnh tranh", f"CPC ({state['rec']['currency']})",
                "Giá thầu thấp", "Giá thầu cao", "Vị trí site (28 ngày)", "Click site", "Hiển thị site", "Trang site",
                "Đang theo dõi hạng", "Nhóm chủ đề", "Mục đích", "Xu hướng", "Pillar (từ khóa chính)",
                "AI Overview"]
        tra = state["rec"]["mode"] == "rank_url"
        if tra:
            head += ["Vị trí URL này", "Click URL này (28 ngày)", "Hiển thị URL này (28 ngày)", "Nguồn"]
        head += [f"Volume {m[5:]}/{m[:4]}" for m, _ in months]
        body = []
        for r in rows:
            mm = dict(r["monthly"])
            body.append([r["keyword"], r["volume"], COMP.get(r["competition"], ("",))[0], r["competition_index"],
                         r["cpc"], r["low_bid"], r["high_bid"], r["gsc_pos"], r["gsc_clicks"], r["gsc_impr"],
                         r["gsc_page"], "Có" if r["tracked"] else "", group_of.get(id(r), ""),
                         INTENT_FULL.get(r.get("intent"), ""), {"up": "Tăng", "down": "Giảm"}.get(r.get("trend"), ""),
                         r.get("pillar") or "",
                         ("Có, site được trích" if (r.get("aio") or {}).get("cited") else "Có")
                         if (r.get("aio") or {}).get("shown") else ("Không" if r.get("aio") else "")]
                        + ([r.get("url_pos"), r.get("url_clicks"), r.get("url_impr"),
                            "Search Console" if r.get("source") == "gsc" else f"Check hạng {r.get('checked') or ''}"]
                           if tra else [])
                        + [mm.get(m) for m, _ in months])
        return head, body

    def make_xlsx() -> bytes:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        rows = export_rows()
        groups = KR.clusters(rows, site)
        wb = Workbook()
        ws = wb.active
        ws.title = "Research"
        head, body = grid(rows)
        ws.append(head)
        for c in ws[1]:
            c.font = Font(bold=True)
        for line in body:
            ws.append(line)
        ws.freeze_panes = "B2"
        ws.column_dimensions["A"].width = 40
        wg = wb.create_sheet("Nhóm chủ đề")
        wg.append(["Nhóm (từ khóa chính)", "Số từ khóa", "Tổng volume/tháng", f"CPC bình quân ({state['rec']['currency']})",
                   "Từ khóa site đã có hạng", "Vị trí tốt nhất", "Trang đích hiện có", "Việc nên làm", "Các từ khóa"])
        for c in wg[1]:
            c.font = Font(bold=True)
        for g in groups:
            wg.append([g["name"], len(g["rows"]), g["volume"], g["cpc"], g["ranked"], g["best"], g["page"] or "",
                       g["action"], ", ".join(r["keyword"] for r in g["rows"])])
        wg.freeze_panes = "B2"
        wg.column_dimensions["A"].width = 36
        wg.column_dimensions["G"].width = 50
        wg.column_dimensions["I"].width = 80
        wf = wb.create_sheet("Bộ lọc")
        rec = state["rec"]
        wf.append(["Research", rec["seed"].replace("\n", ", ")])
        wf.append(["Cách tìm", KR.MODES[rec["mode"]]])
        wf.append(["Số từ khóa trong file", len(rows), f"/ {len(rec['rows'])} ý tưởng"])
        for name, val in filter_summary() or [("Bộ lọc", "Không lọc")]:
            wf.append([name, val])
        for c in wf["A"]:
            c.font = Font(bold=True)
        wf.column_dimensions["A"].width = 26
        wf.column_dimensions["B"].width = 70
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def file_name() -> str:
        import re
        from datetime import date
        first = state["rec"]["seed"].replace(",", "\n").split("\n")[0]
        seed = "-".join(w for w in (K.fold(x) for x in re.split(r"[\s/.]+", first)) if w)[:40] or "research"
        return f"research-tu-khoa_{seed}_{date.today():%Y-%m-%d}"

    def copy(words: list[str]) -> None:
        """Sao chép đủ thông tin của các từ khóa (cột cách nhau bằng Tab, có dòng tiêu đề): dán vào Google Sheets /
        Excel là ra đúng cột. Số thập phân dùng dấu phẩy, không có dấu chấm hàng nghìn."""
        want = set(words)
        rows = [r for r in state["rec"]["rows"] if r["keyword"] in want]
        if not rows:
            return
        head, body = grid(rows)

        def cell(v) -> str:
            if v is None:
                return ""
            if isinstance(v, float):
                v = round(v) if state["rec"]["currency"] == "VND" and v >= 100 else round(v, 2)
                return str(v).replace(".", ",")
            return str(v).replace("\t", " ").replace("\n", " ")
        text = "\n".join("\t".join(cell(v) for v in line) for line in [head] + body)
        ui.clipboard.write(text)
        ui.notify(f"Đã sao chép {len(rows)} từ khóa kèm đủ thông tin (dán vào Google Sheets / Excel)",
                  type="positive")

    @ui.refreshable
    def status(rows: list[dict]) -> None:
        """Một dòng trên bảng: tóm tắt danh sách đang xem, hoặc (khi đã tick chọn) các thao tác với phần đã chọn."""
        n = len(state["sel"])
        cur = state["rec"]["currency"]
        with ui.row().classes("w-full items-center no-wrap gap-2 sr-kr-status" + (" on" if n else "")):
            if not n:
                vol = sum(r["volume"] or 0 for r in rows)
                priced = [r["cpc"] for r in rows if r["cpc"]]
                no_rank = sum(1 for r in rows if not r["gsc_impr"])
                parts = [f"<b>{len(rows):,}</b> từ khóa", f"<b>{vol:,}</b> lượt tìm / tháng"]
                if priced:
                    parts.append(f"CPC trung bình <b>{sum(priced) / len(priced):,.0f}</b> {cur}")
                parts.append(f"<b>{no_rank:,}</b> site chưa có hạng")
                ui.html(" · ".join(parts).replace(",", ".")).classes("text-sm col")
                ui.label("Tick ô đầu dòng để sao chép / theo dõi hạng").classes("text-xs muted gt-sm")
                return
            ui.label(f"Đã chọn {n} từ khóa").classes("text-sm font-semibold")

            def clear():
                state["sel"] = []
                table.refresh()
            ui.button("Bỏ chọn", on_click=clear).props("flat dense no-caps color=primary")
            ui.space()
            ui.button("Sao chép", icon="content_copy", on_click=lambda: copy(list(state["sel"]))).props(
                "flat dense no-caps color=primary").tooltip("Chép đủ thông tin, dán vào Google Sheets / Excel")
            if ed:
                want = set(state["sel"])
                need = [r["keyword"] for r in state["rec"]["rows"] if r["keyword"] in want and not r.get("aio")]
                b_aio = ui.button(f"Check AIO ({len(need)})" if need else "Check AIO", icon="auto_awesome",
                                  on_click=lambda: aio_dialog(need)).props("outline dense no-caps")
                b_aio.tooltip(f"Tốn phí DataForSEO: khoảng {KO.LIVE_EST_USD:.3f} USD / từ khóa chưa có số AI Overview"
                              .replace(".", ",") if need else "Các từ khóa đã chọn đều đã có số AI Overview")
                if not need:
                    b_aio.props("disable")
                ui.button("Theo dõi hạng", icon="playlist_add",
                          on_click=lambda: add_dialog([r for r in state["rec"]["rows"] if r["keyword"] in want])
                          ).props("unelevated dense no-caps")

    def aio_dialog(keywords: list[str]) -> None:
        """Xác nhận rồi check AI Overview (xem trang kết quả Google một lần) cho các từ khóa chưa có số."""
        from . import rank as R
        kws = keywords[:50]
        cost = len(kws) * KO.LIVE_EST_USD
        with ui.dialog() as dlg, ui.card().style("max-width: 460px; border-radius: 14px"):
            ui.label(f"Check AI Overview cho {len(kws)} từ khóa?").classes("text-lg font-semibold")
            with ui.row().classes("items-start no-wrap gap-2 sr-kr-paid"):
                ui.icon("paid", size="18px")
                ui.label(f"Có tốn phí: khoảng {R.usd(cost, 3)} USD ({KO.LIVE_EST_USD:.3f} USD / từ khóa), tính vào "
                         "ngân sách DataForSEO của website. Từ khóa đã có số AI Overview không check lại."
                         .replace("0.002", "0,002")).classes("text-sm")
            if len(keywords) > len(kws):
                ui.label(f"Mỗi lần tối đa 50 từ khóa: lần này check 50/{len(keywords)}.").classes("text-sm muted")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Check", icon="auto_awesome", on_click=lambda: (dlg.close(), run_aio(kws))).props(
                    "unelevated no-caps")
        dlg.open()

    async def run_aio(kws: list[str]) -> None:
        from contextlib import closing

        from . import db
        note = ui.notification(f"Đang check AI Overview 0/{len(kws)}…", spinner=True, timeout=None, type="ongoing",
                               position="bottom-right")
        prog = {"n": 0}

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                res = KO.check_aio(c, cfg, kws, str(user), progress=lambda i, n: prog.update(n=i))
                return res, KR.get(c, cfg, state["rec"]["id"])
        timer = ui.timer(1, lambda: setattr(note, "message", f"Đang check AI Overview {prog['n']}/{len(kws)}…"))
        try:
            res, rec = await run.io_bound(work)
            state["rec"] = rec
            msg = f"Đã check {res['done']} từ khóa"
            if res["error"]:
                ui.notify(f"{msg}; dừng lại: {res['error']}", type="warning", multi_line=True, position="bottom-right")
            else:
                ui.notify(msg, type="positive", position="bottom-right")
        except Exception as ex:  # noqa: BLE001
            ui.notify(str(ex), type="warning", position="bottom-right")
        finally:
            timer.cancel()
            note.dismiss()
        table.refresh()

    def add_dialog(selected: list[dict]) -> None:
        from . import rank as R
        kws = [r["keyword"] for r in selected]
        with connect() as c:
            sets = [s for s in R.sets(c, site) if s.get("kind") != "kpi"]
        if not sets:
            ui.notify("Chưa có bộ từ khóa nào do team tạo: tạo bộ ở trang Từ khóa & Thứ hạng trước", type="warning")
            return
        with ui.dialog() as d, ui.card().style("min-width: 480px; max-width: 94vw; border-radius: 14px"):
            ui.label(f"Thêm {len(kws)} từ khóa vào bộ theo dõi hạng").classes("text-lg font-semibold")
            sel = ui.select({s["id"]: s["name"] + (" (Nháp)" if s.get("draft") else "") for s in sets},
                            value=sets[0]["id"], label="Bộ từ khóa").props("outlined dense").classes("w-full")
            est = ui.label().classes("text-sm muted")

            def update_est():
                with connect() as c:
                    e = R.estimate_add(c, site, cfg.rank, K.latest_date(c, site), kws, sel.value)
                est.text = (f"{e['new']} từ khóa mới ({e['existing']} đã có trong bộ). Check hạng tốn thêm khoảng "
                            f"{R.usd(e['monthly_add'])} USD/tháng theo lịch của bộ; cả tháng dự kiến "
                            f"{R.usd(e['monthly_total'])}/{e['budget']:.0f} USD. Bộ Nháp chưa tốn tiền đến khi Chốt.")
            sel.on_value_change(lambda _: update_est())
            update_est()

            def do_add():
                with connect() as c:
                    res = R.add_keywords(c, site, cfg.rank, K.latest_date(c, site), [(k, None) for k in kws],
                                         str(user), set_id=sel.value)
                msg = f"Đã thêm {len(res['added'])} từ khóa"
                if res["over_budget"]:
                    msg += f", {len(res['over_budget'])} từ khóa vượt ngân sách chưa thêm"
                ui.notify(msg, type="positive" if res["added"] else "warning")
                d.close()
                with connect() as c:
                    state["rec"] = KR.get(c, cfg, state["rec"]["id"])
                results.refresh()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Thêm vào bộ", icon="add", on_click=do_add).props("unelevated no-caps")
        d.open()

    def groups_view(rows: list[dict], cur: str) -> None:
        """Cụm chủ đề: mỗi cụm một trang đích (có sẵn hoặc cần viết mới), bấm mở xem các từ khóa."""
        groups = KR.clusters(rows, site)
        new = [g for g in groups if g["new"]]
        ui.label(f"{len(groups):,} nhóm từ {len(rows):,} từ khóa · {len(new):,} nhóm cần trang mới "
                 f"(tổng {sum(g['volume'] for g in new):,} lượt tìm / tháng)".replace(",", ".")).classes(
            "text-sm muted q-mb-xs")
        ui.label("Nhóm theo trang site đang lên cho từ khóa (Search Console), phần còn lại theo độ giống của từ khóa. "
                 "Mỗi nhóm nên có một trang đích; nhóm “Cần trang mới” là gợi ý bài / danh mục nên làm.").classes(
            "text-xs muted q-mb-sm")
        tone = {True: "amber", False: "blue"}
        for g in groups[:state["shown_groups"]]:
            with ui.expansion().classes("w-full sr-op-check").props("dense") as ex:
                with ex.add_slot("header"):
                    with ui.row().classes("w-full items-center no-wrap gap-3"):
                        with ui.column().classes("gap-0 col").style("min-width:0"):
                            ui.label(g["name"]).classes("text-sm font-semibold ellipsis")
                            ui.label((g["path"] or "chưa có trang") + f" · {len(g['rows'])} từ khóa"
                                     + (f" · vị trí tốt nhất {g['best']:.1f}".replace(".", ",") if g["best"] else "")
                                     ).classes("text-xs muted ellipsis")
                        T.pill(ui, g["action"], "amber" if g["new"] else "green" if g["action"].startswith("Đang")
                               else "blue")
                        with ui.column().classes("gap-0 items-end").style("min-width:96px"):
                            ui.label(f"{g['volume']:,}".replace(",", ".")).classes("text-sm num font-semibold")
                            ui.label("lượt tìm / tháng").classes("text-xs muted")
                with ui.row().classes("w-full items-center gap-2 q-mb-xs"):
                    if g["page"]:
                        ui.link(g["page"], g["page"], new_tab=True).classes("sr-bl-link text-sm col")
                    else:
                        ui.space()
                    ui.button("Sao chép nhóm", icon="content_copy",
                              on_click=lambda g=g: copy([r["keyword"] for r in g["rows"]])).props(
                        "flat dense no-caps size=sm color=primary")
                ui.table(columns=[
                    {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left"},
                    {"name": "volume", "label": "Volume", "field": "volume", "align": "right",
                     ":format": "v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN')"},
                    {"name": "cpc", "label": f"CPC ({cur})", "field": "cpc", "align": "right",
                     ":format": "v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN', "
                                "{maximumFractionDigits: 0})"},
                    {"name": "pos", "label": "Vị trí site", "field": "gsc_pos", "align": "right",
                     ":format": "v => v === null || v === undefined ? 'chưa có' : v.toLocaleString('vi-VN')"},
                ], rows=[{**r, "id": i} for i, r in enumerate(g["rows"])], row_key="id", pagination=10).props(
                    "flat dense").classes("w-full sr-bl-table")
        if len(groups) > state["shown_groups"]:
            def more():
                state["shown_groups"] += 30
                table.refresh()
            ui.button(f"Xem thêm nhóm ({len(groups) - state['shown_groups']} nhóm nữa)", on_click=more).props(
                "flat no-caps")

    @ui.refreshable
    def table() -> None:
        rows = shown_rows()
        rec = state["rec"]
        if not rows:
            T.empty_state(ui, "search_off", "Không có từ khóa nào khớp bộ lọc")
            return
        if state["view"] == "groups":
            groups_view(rows, rec["currency"])
            return
        # Tra URL của chính site: cột "Website bạn" chỉ có ý nghĩa khi Google xếp một trang KHÁC của site
        own_url = ""
        if rec["mode"] == "rank_url" and _host(rec["seed"]) == _host(site):
            own_url = _norm_url(rec["seed"])
        data = []
        for i, r in enumerate(rows):
            mx = max((n for _, n in r["monthly"]), default=0) or 1
            data.append({"id": i, "keyword": r["keyword"], "volume": r["volume"], "cpc": r["cpc"],
                         "comp": COMP.get(r["competition"], ("–", ""))[0], "comp_cls": COMP.get(r["competition"],
                                                                                              ("", ""))[1],
                         "comp_i": r["competition_index"], "tracked": r["tracked"], "brand": r["brand"],
                         "aio": (r.get("aio") or {}).get("shown"), "aio_cited": (r.get("aio") or {}).get("cited"),
                         "aio_at": (r.get("aio") or {}).get("at") or "",
                         "pillar": r.get("pillar") or "", "is_pillar": r.get("is_pillar"),
                         "flags": (2 if r["tracked"] else 0) + (1 if (r.get("aio") or {}).get("shown") else 0),
                         "intent": r.get("intent") or "", "rival": r.get("rival"), "trend": r.get("trend") or "",
                         "pos": r["gsc_pos"], "clicks": r["gsc_clicks"], "impr": r["gsc_impr"],
                         "page": (r["gsc_page"] or "").replace(site.rstrip("/"), "") or None,
                         "page_url": r["gsc_page"],
                         "same_page": bool(own_url and r["gsc_page"] and _norm_url(r["gsc_page"]) == own_url),
                         "u_pos": r.get("url_pos"), "u_clicks": r.get("url_clicks"), "u_impr": r.get("url_impr"),
                         "u_src": r.get("source") or "", "u_date": (r.get("checked") or "")[:10],
                         "bars": [{"m": f"{m[5:]}/{m[2:4]}", "n": n, "h": max(2, round(22 * n / mx))}
                                  for m, n in r["monthly"]]})
        status(rows)
        cur = rec["currency"]
        fmt_money = ("v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN', {maximumFractionDigits: "
                     + ("0" if cur == "VND" else "2") + "})")
        tb = ui.table(columns=[
            {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left",
             "classes": "sr-kc sr-kc-keyword", "headerClasses": "sr-kc sr-kc-keyword"},
            {"name": "flags", "label": "Rank · AIO", "field": "flags", "align": "center",
             "classes": "sr-kc sr-kc-flags", "headerClasses": "sr-kc sr-kc-flags"},
            {"name": "intent", "label": "Mục đích", "field": "intent", "align": "center",
             "classes": "sr-kc sr-kc-intent", "headerClasses": "sr-kc sr-kc-intent"},
            {"name": "volume", "label": "Volume", "field": "volume", "align": "right",
             ":format": "v => v === null || v === undefined ? '–' : v.toLocaleString('vi-VN')",
             "classes": "sr-kc sr-kc-num", "headerClasses": "sr-kc sr-kc-num"},
            {"name": "trend", "label": "Xu hướng", "field": "volume", "align": "left", "sortable": False,
             "classes": "sr-kc sr-kc-trend", "headerClasses": "sr-kc sr-kc-trend"},
            {"name": "comp", "label": "Cạnh tranh", "field": "comp_i", "align": "center",
             "classes": "sr-kc sr-kc-comp", "headerClasses": "sr-kc sr-kc-comp"},
            {"name": "cpc", "label": f"CPC ({cur})", "field": "cpc", "align": "right", ":format": fmt_money,
             "classes": "sr-kc sr-kc-cpc", "headerClasses": "sr-kc sr-kc-cpc"},
            *([{"name": "urlpos", "label": "Trang đang tra", "field": "u_pos", "align": "left",
                "classes": "sr-kc sr-kc-urlpos", "headerClasses": "sr-kc sr-kc-urlpos"}]
              if rec["mode"] == "rank_url" else []),
            {"name": "pillar", "label": "Pillar", "field": "pillar", "align": "left",
             "classes": "sr-kc sr-kc-pillar", "headerClasses": "sr-kc sr-kc-pillar"},
            {"name": "site", "label": "Trang khác của site" if own_url else "Website bạn", "field": "pos", "align": "left",
             "classes": "sr-kc sr-kc-site", "headerClasses": "sr-kc sr-kc-site"},
        ], rows=data, row_key="id", pagination={"rowsPerPage": 25}, selection="multiple").props(
            'flat dense binary-state-sort :rows-per-page-options="[25, 50, 100, 0]" '
            'rows-per-page-label="Dòng mỗi trang"').classes(
            "w-full sr-bl-table sr-kr-table" + (" wide" if rec["mode"] == "rank_url" else ""))
        tb.columns = [c for c in tb.columns if c["name"] not in state["hidden"]]
        chosen = set(state["sel"])
        tb.selected = [d for d in data if d["keyword"] in chosen]

        def picked(_=None):
            on_page = {d["keyword"] for d in data}
            keep = [k for k in state["sel"] if k not in on_page]  # đã chọn nhưng đang bị bộ lọc ẩn: giữ
            state["sel"] = keep + [s_["keyword"] for s_ in tb.selected]
            status.refresh(rows)
        tb.on_select(picked)
        tb.add_slot("body-cell-keyword", """
            <q-td :props="props"><div class="sr-op-kw"><a :href="'/tu-khoa?kw=' +
              encodeURIComponent(props.value)" class="sr-ko-kw" @click.stop>{{ props.value }}<q-tooltip>Mở tổng quan
              từ khóa</q-tooltip></a>

              <span v-if="props.row.brand" class="sr-bl-type q-ml-xs">thương hiệu</span>
              <span v-if="props.row.rival" class="sr-bl-type q-ml-xs">đối thủ</span></div></q-td>""")
        tb.add_slot("body-cell-flags", """
            <q-td :props="props"><div class="sr-kr-flags">
              <span class="sr-kr-slot"><q-icon v-if="props.row.tracked" name="leaderboard" size="18px"
                class="sr-kr-ico trk" aria-label="Đang theo dõi hạng"><q-tooltip>Đang theo dõi hạng</q-tooltip>
                </q-icon></span>
              <span class="sr-kr-slot"><q-icon v-if="props.row.aio" name="auto_awesome" size="18px" class="sr-kr-ico"
                :class="props.row.aio_cited ? 'aio-on' : 'aio'"
                :aria-label="props.row.aio_cited ? 'Có AI Overview, site được trích' : 'Có AI Overview'">
                <q-tooltip>{{ props.row.aio_cited ? 'Có AI Overview · site được trích dẫn' :
                  'Có AI Overview · site chưa được trích' }} (số ngày {{ props.row.aio_at.slice(8, 10) }}/{{
                  props.row.aio_at.slice(5, 7) }})</q-tooltip></q-icon></span></div></q-td>""")
        tb.add_slot("body-cell-pillar", """
            <q-td :props="props"><template v-if="props.value">
              <span v-if="props.row.is_pillar" class="sr-kr-pillar self"><q-icon name="star" size="14px" />
                chính<q-tooltip>Từ khóa này có thứ hạng cao nhất trên URL của nó: là pillar của các từ khóa cùng
                URL</q-tooltip></span>
              <a v-else :href="'/tu-khoa?kw=' + encodeURIComponent(props.value)" class="sr-ko-kw sr-kr-pillar"
                @click.stop>{{ props.value }}<q-tooltip>Pillar: từ khóa có thứ hạng cao nhất trên cùng URL
                {{ props.row.page }}</q-tooltip></a></template>
              <span v-else class="muted">–</span></q-td>""")
        tb.add_slot("body-cell-intent", """
            <q-td :props="props"><span v-if="props.value" class="sr-kr-intent" :class="'i-' + props.value">{{
              props.value }}<q-tooltip>{{ {I: 'Thông tin', N: 'Điều hướng', C: 'Cân nhắc mua',
              T: 'Mua / giao dịch'}[props.value] }}</q-tooltip></span></q-td>""")
        tb.add_slot("body-cell-trend", """
            <q-td :props="props"><div class="row items-end no-wrap" style="gap:6px" v-if="props.row.bars.length">
              <div class="sr-kr-spark" :aria-label="props.row.trend === 'up' ? 'Đang tăng' :
                props.row.trend === 'down' ? 'Đang giảm' : 'Đi ngang'" role="img">
              <div v-for="b in props.row.bars" :key="b.m" class="sr-kr-bar" :class="props.row.trend"
                :style="{height: b.h + 'px'}"></div>
              <q-tooltip><div v-for="b in props.row.bars" :key="b.m">{{ b.m }}: {{ b.n.toLocaleString('vi-VN') }}
              </div></q-tooltip></div>
              <span v-if="props.row.trend" class="sr-op-move" :class="props.row.trend" aria-hidden="true">{{
                props.row.trend === 'up' ? '▲' : '▼' }}</span></div>
              <span v-else class="muted">–</span></q-td>""")
        tb.add_slot("body-cell-comp", """
            <q-td :props="props"><span v-if="props.row.comp_cls" class="sr-bl-type" :class="props.row.comp_cls">{{
              props.row.comp }}<q-tooltip>Mức cạnh tranh quảng cáo (0–100): {{ props.value }}</q-tooltip></span>
              <span v-else class="muted">–</span></q-td>""")
        tip_url = ("Vị trí, click và lượt hiển thị của đúng trang bạn đang tra (Search Console 28 ngày)."
                   if own_url else "Vị trí của trang đối thủ bạn đang tra, theo lần check hạng gần nhất.")
        tip_site = ("Google có xếp trang KHÁC của site cho từ khóa này không (Search Console 28 ngày). "
                    "\"–\" nghĩa là chính trang đang tra là trang tốt nhất." if own_url else
                    "Vị trí tốt nhất của website bạn trên Google cho từ khóa (Search Console 28 ngày) "
                    "và trang đang lên hạng.")
        for col, tip in (("urlpos", tip_url), ("site", tip_site)):
            tb.add_slot(f"header-cell-{col}", f"""
                <q-th :props="props">{{{{ props.col.label }}}}<q-icon name="info_outline" size="14px"
                  class="q-ml-xs muted" /><q-tooltip max-width="280px">{tip}</q-tooltip></q-th>""")
        tb.add_slot("body-cell-urlpos", """
            <q-td :props="props"><template v-if="props.value !== null && props.value !== undefined">
              <span class="num">vị trí {{ props.value.toLocaleString('vi-VN') }}<template
                v-if="props.row.u_src === 'gsc'"> · {{ (props.row.u_clicks || 0).toLocaleString('vi-VN') }}
                click</template></span>
              <div class="sr-bl-sub" v-if="props.row.u_src === 'gsc'">{{ props.row.u_impr.toLocaleString('vi-VN') }}
                hiển thị</div>
              <div class="sr-bl-sub" v-else>check {{ props.row.u_date.slice(8, 10) }}/{{ props.row.u_date.slice(5, 7)
                }}</div></template><span v-else class="muted">–</span></q-td>""")
        tb.add_slot("body-cell-site", """
            <q-td :props="props"><span v-if="props.row.same_page" class="muted">–</span>
              <template v-else-if="props.row.impr">
              <span class="num">vị trí {{ props.value.toLocaleString('vi-VN') }} ·
                {{ props.row.clicks.toLocaleString('vi-VN') }} click</span>
              <div class="sr-bl-sub sr-kr-page"><a :href="props.row.page_url" target="_blank" rel="noopener"
                class="sr-bl-link" style="font-weight:400" :title="props.row.page_url">{{ props.row.page }}</a>
              </div></template>
              <span v-else class="sr-bl-type k-kw">chưa có hạng</span></q-td>""")

    # ---- Thanh bộ lọc (kiểu Semrush): mỗi nút một menu nhỏ, bấm Áp dụng ----
    VOL_PRESETS = [("100.001+", 100001, None), ("10.001–100.000", 10001, 100000), ("1.001–10.000", 1001, 10000),
                   ("101–1.000", 101, 1000), ("11–100", 11, 100), ("1–10", 1, 10)]
    INTENT_NAMES = {"I": "Thông tin", "N": "Điều hướng", "C": "Cân nhắc mua", "T": "Mua / giao dịch"}

    def num(v) -> str:
        return f"{v:,.0f}".replace(",", ".")

    def rng(lo, hi) -> str:
        if lo is not None and hi is not None:
            return f"{num(lo)}–{num(hi)}"
        return f"≥ {num(lo)}" if lo is not None else f"≤ {num(hi)}"

    def apply_f(**kw) -> None:
        state["f"].update(kw)
        state["word"] = None
        fbar.refresh()
        words_panel.refresh()
        table.refresh()

    def to_num(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def words_of(text: str) -> list[str]:
        return [w.strip() for w in (text or "").replace(",", "\n").splitlines() if w.strip()]

    def drop_btn(label: str, active: str = ""):
        b = ui.button((f"{label}: {active}" if active else label)).props(
            "flat no-caps dense icon-right=expand_more").classes("sr-fbtn" + (" on" if active else ""))
        return b

    def range_menu(b, key: str, presets=None, unit: str = "") -> None:
        lo0, hi0 = state["f"][key]
        with b, ui.menu().classes("sr-kr-fmenu") as m:
            with ui.column().classes("q-pa-sm gap-1"):
                for text, lo, hi in presets or []:
                    ui.button(text, on_click=lambda lo=lo, hi=hi: (apply_f(**{key: [lo, hi]}), m.close())).props(
                        "flat dense no-caps align=left").classes("w-full")
                ui.label("Tùy chọn" + (f" ({unit})" if unit else "")).classes("text-xs muted q-mt-xs")
                with ui.row().classes("gap-2 no-wrap"):
                    a = ui.number(placeholder="Từ", value=lo0).props("outlined dense").classes("w-28")
                    z = ui.number(placeholder="Đến", value=hi0).props("outlined dense").classes("w-28")
                with ui.row().classes("w-full justify-between"):
                    ui.button("Bỏ", on_click=lambda: (apply_f(**{key: [None, None]}), m.close())).props(
                        "flat dense no-caps")
                    ui.button("Áp dụng", on_click=lambda: (apply_f(**{key: [to_num(a.value), to_num(z.value)]}),
                                                           m.close())).props("unelevated dense no-caps")

    def check_menu(b, key: str, options: dict) -> None:
        with b, ui.menu().classes("sr-kr-fmenu") as m:
            with ui.column().classes("q-pa-sm gap-0"):
                boxes = {k: ui.checkbox(v, value=k in state["f"][key]).props("dense") for k, v in options.items()}
                with ui.row().classes("w-full justify-between q-mt-sm"):
                    ui.button("Bỏ", on_click=lambda: (apply_f(**{key: []}), m.close())).props("flat dense no-caps")
                    ui.button("Áp dụng", on_click=lambda: (apply_f(**{key: [k for k, c in boxes.items() if c.value]}),
                                                           m.close())).props("unelevated dense no-caps")

    @ui.refreshable
    def fbar() -> None:
        f = state["f"]
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            b = drop_btn("Số lượng tìm kiếm", rng(*f["vol"]) if f["vol"] != [None, None] else "")
            range_menu(b, "vol", VOL_PRESETS)
            b = drop_btn("Cạnh tranh", ", ".join(COMP[c][0] for c in f["comp"]))
            check_menu(b, "comp", {"LOW": "Thấp", "MEDIUM": "Vừa", "HIGH": "Cao"})
            b.tooltip("Mức cạnh tranh quảng cáo trên Google Ads (không phải độ khó SEO)")
            b = drop_btn("Mục đích", ", ".join(f["intent"]))
            check_menu(b, "intent", {k: f"{k} · {v}" for k, v in INTENT_NAMES.items()})
            b = drop_btn(f"CPC ({state['rec']['currency']})", rng(*f["cpc"]) if f["cpc"] != [None, None] else "")
            range_menu(b, "cpc", [("Có giá thầu", 0.01, None), ("Từ 5.000", 5000, None), ("Từ 10.000", 10000, None)],
                       state["rec"]["currency"])
            # Bao gồm từ khóa
            b = drop_btn("Bao gồm từ khóa", f"{len(f['inc'])} từ" if f["inc"] else "")
            with b, ui.menu().classes("sr-kr-fmenu") as m:
                with ui.column().classes("q-pa-sm gap-1").style("width: 280px"):
                    mode = ui.toggle({False: "Chứa bất kỳ", True: "Chứa tất cả"}, value=f["inc_all"]).props(
                        "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"
                    ).classes("sr-seg")
                    t = ui.textarea(placeholder="Mỗi dòng (hoặc dấu phẩy) một từ, ví dụ: cận, giá",
                                    value="\n".join(f["inc"])).props("outlined dense autogrow").classes("w-full")
                    with ui.row().classes("w-full justify-between"):
                        ui.button("Bỏ", on_click=lambda m=m: (apply_f(inc=[]), m.close())).props("flat dense no-caps")
                        ui.button("Áp dụng", on_click=lambda m=m, t=t, mode=mode: (
                            apply_f(inc=words_of(t.value), inc_all=mode.value), m.close())).props(
                            "unelevated dense no-caps")
            # Loại bỏ từ khóa
            n_exc = len(f["exc"]) + f["exc_tracked"] + f["exc_brand"] + f["exc_rival"]
            b = drop_btn("Loại bỏ từ khóa", f"{n_exc} điều kiện" if n_exc else "")
            with b, ui.menu().classes("sr-kr-fmenu") as m:
                with ui.column().classes("q-pa-sm gap-0").style("width: 280px"):
                    c1 = ui.checkbox("Đã theo dõi hạng", value=f["exc_tracked"]).props("dense")
                    c2 = ui.checkbox("Thương hiệu của mình", value=f["exc_brand"]).props("dense")
                    c3 = ui.checkbox("Thương hiệu đối thủ", value=f["exc_rival"]).props("dense")
                    t = ui.textarea(placeholder="Bỏ từ khóa chứa các từ này (mỗi dòng một từ)",
                                    value="\n".join(f["exc"])).props("outlined dense autogrow").classes(
                        "w-full q-mt-sm")
                    with ui.row().classes("w-full justify-between q-mt-xs"):
                        ui.button("Bỏ", on_click=lambda m=m: (apply_f(exc=[], exc_tracked=False, exc_brand=False,
                                                                       exc_rival=False), m.close())).props(
                            "flat dense no-caps")
                        ui.button("Áp dụng", on_click=lambda m=m, t=t, c1=c1, c2=c2, c3=c3: (
                            apply_f(exc=words_of(t.value), exc_tracked=c1.value, exc_brand=c2.value,
                                    exc_rival=c3.value), m.close())).props("unelevated dense no-caps")
            # Nâng cao
            n_adv = (f["words"] != [None, None]) + (f["site"] != "all") + (f["trend"] != "all") + f["question"]
            b = drop_btn("Bộ lọc nâng cao", f"{n_adv} điều kiện" if n_adv else "")
            with b, ui.menu().classes("sr-kr-fmenu") as m:
                with ui.column().classes("q-pa-sm gap-1").style("width: 300px"):
                    ui.label("Số từ trong từ khóa").classes("text-xs muted")
                    with ui.row().classes("gap-2 no-wrap"):
                        w1 = ui.number(placeholder="Từ", value=f["words"][0]).props("outlined dense").classes("w-28")
                        w2 = ui.number(placeholder="Đến", value=f["words"][1]).props("outlined dense").classes("w-28")
                    s_ = ui.select(KR.SITE_FILTERS, value=f["site"], label="Thứ hạng của site").props(
                        "outlined dense").classes("w-full")
                    tr = ui.select(KR.TREND_FILTERS, value=f["trend"], label="Xu hướng tìm kiếm").props(
                        "outlined dense").classes("w-full")
                    qn = ui.checkbox("Chỉ từ khóa dạng câu hỏi", value=f["question"]).props("dense")
                    with ui.row().classes("w-full justify-between q-mt-xs"):
                        ui.button("Bỏ", on_click=lambda m=m: (apply_f(words=[None, None], site="all", trend="all",
                                                                       question=False), m.close())).props(
                            "flat dense no-caps")
                        ui.button("Áp dụng", on_click=lambda m=m, w1=w1, w2=w2, s_=s_, tr=tr, qn=qn: (
                            apply_f(words=[to_num(w1.value), to_num(w2.value)], site=s_.value, trend=tr.value,
                                    question=qn.value), m.close())).props("unelevated dense no-caps")
        chips = active_chips()
        if chips:
            with ui.row().classes("w-full items-center gap-1 q-mt-xs"):
                for text, reset in chips:
                    T.filter_chip(ui, text, lambda r=reset: (apply_f(**r) if r else pick_word(None)))
                ui.button("Xóa tất cả", on_click=clear_filters).props("flat dense no-caps size=sm color=negative")

    def active_chips() -> list[tuple[str, dict | None]]:
        """Bộ lọc đang bật: (chữ trên nhãn, giá trị trả về mặc định khi bấm bỏ; None = bỏ từ ở cột trái)."""
        f, out = state["f"], []
        if f["vol"] != [None, None]:
            out.append((f"Volume {rng(*f['vol'])}", {"vol": [None, None]}))
        if f["comp"]:
            out.append(("Cạnh tranh: " + ", ".join(COMP[c][0] for c in f["comp"]), {"comp": []}))
        if f["intent"]:
            out.append(("Mục đích: " + ", ".join(f["intent"]), {"intent": []}))
        if f["cpc"] != [None, None]:
            out.append((f"CPC {rng(*f['cpc'])}", {"cpc": [None, None]}))
        if f["inc"]:
            out.append(("Có: " + ", ".join(f["inc"]), {"inc": []}))
        for key, text in (("exc_tracked", "Bỏ đã theo dõi hạng"), ("exc_brand", "Bỏ thương hiệu của mình"),
                          ("exc_rival", "Bỏ thương hiệu đối thủ")):
            if f[key]:
                out.append((text, {key: False}))
        if f["exc"]:
            out.append(("Bỏ: " + ", ".join(f["exc"]), {"exc": []}))
        if f["words"] != [None, None]:
            out.append((f"Số từ {rng(*f['words'])}", {"words": [None, None]}))
        if f["site"] != "all":
            out.append((KR.SITE_FILTERS[f["site"]], {"site": "all"}))
        if f["trend"] != "all":
            out.append((KR.TREND_FILTERS[f["trend"]].split(" (")[0], {"trend": "all"}))
        if f["question"]:
            out.append(("Chỉ câu hỏi", {"question": False}))
        if state["word"]:
            out.append((f"Từ: {state['word_label'] or state['word']}", None))
        return out

    def clear_filters() -> None:
        state.update(f=json.loads(json.dumps(KR.FILTER_DEFAULT)), word=None, word_label="")
        fbar.refresh()
        words_panel.refresh()
        table.refresh()

    def pick_word(w, label: str = "") -> None:
        state["word"], state["word_label"] = w, label
        fbar.refresh()
        words_panel.refresh()
        table.refresh()

    @ui.refreshable
    def words_panel() -> None:
        """Cột trái kiểu Semrush: nhóm từ khóa theo từ xuất hiện nhiều (bấm để lọc)."""
        rows = base_rows()
        groups = KR.word_groups(rows, state["rec"]["seed"], by=state["wsort"])
        with ui.column().classes("w-full gap-1 q-mb-xs"):
            ui.label("Nhóm theo từ").classes("text-sm font-semibold")
            ui.toggle({"count": "Số lượng", "volume": "Volume"}, value=state["wsort"],
                      on_change=lambda e: (state.update(wsort=e.value), words_panel.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"
            ).classes("sr-seg")

        with ui.column().classes("w-full gap-0 sr-kr-wlist"):
            items = [(None, "Tất cả từ khóa", len(rows), sum(r["volume"] or 0 for r in rows))] + \
                [(g["word"], g["label"], g["count"], g["volume"]) for g in groups[:60]]
            for key, label, n, vol in items:
                on = state["word"] == key
                with ui.row().classes("w-full items-center no-wrap gap-2 sr-kr-wrow cursor-pointer"
                                      + (" on" if on else "")) as row_:
                    ui.label(label).classes("text-sm col ellipsis" + (" font-semibold" if key is None else ""))
                    ui.label(f"{n:,}".replace(",", ".")).classes("text-xs num muted")
                row_.props(f'tabindex=0 role=button aria-pressed={"true" if on else "false"}')
                row_.on("click", lambda k=key, lb=label: pick_word(k, lb if k else ""))
                row_.on("keydown.enter", lambda k=key, lb=label: pick_word(k, lb if k else ""))
                row_.tooltip(f"{vol:,} lượt tìm / tháng".replace(",", "."))

    @ui.refreshable
    def results() -> None:
        rec = state["rec"]
        if state["busy"]:
            with ui.element("div").classes("sr-card sr-kr-panel sr-busy").props(
                    'aria-busy="true" aria-label="Đang tìm ý tưởng từ khóa"'):
                T.bone(ui, "32px", "60%", "8px")
                T.bone(ui, "28px", "90%", "8px").classes("q-mt-sm")
                with ui.element("div").classes("sr-kr-magic"):
                    T.bone(ui, "320px", radius="10px")
                    T.bone(ui, "320px", radius="10px")
            return
        if not rec:
            with ui.element("div").classes("sr-card q-pa-lg w-full"):
                ui.label("Bắt đầu từ đâu?").classes("text-base font-semibold q-mb-sm")
                with ui.element("div").classes("sr-kr-start"):
                    for mode, icon, title, text in (
                            ("keywords", "search", "Từ khóa gốc",
                             "Gõ hoặc dán tới 100 từ khóa: Google gợi ý hàng trăm từ khóa liên quan."),
                            ("site", "language", "Cả website", "Gõ tên miền đối thủ: xem họ nhắm những từ khóa nào."),
                            ("rank_url", "link", "Tra URL", "Dán URL: các từ khóa trang đó đang có hạng.")):
                        with ui.column().classes("gap-1 sr-kr-start-opt") as opt:
                            ui.icon(icon, size="22px").classes("sr-kr-start-ico")
                            ui.label(title).classes("text-sm font-semibold")
                            ui.label(text).classes("text-sm muted")
                        opt.props(f'tabindex=0 role=button aria-label="Tìm theo {title}"')
                        opt.on("click", lambda m=mode: set_mode(m))
                        opt.on("keydown.enter", lambda m=mode: set_mode(m))
            return
        seg = "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"
        with ui.element("div").classes("sr-card sr-kr-panel"):
            with ui.row().classes("w-full items-center gap-2 sr-kr-toolbar"):
                ui.toggle({"all": "Tất cả", "questions": "Câu hỏi"}, value=state["kind"],
                          on_change=lambda e: (state.update(kind=e.value, word=None, word_label=""), fbar.refresh(),
                                               words_panel.refresh(), table.refresh())).props(seg).classes("sr-seg")
                if rec["mode"] == "keywords":
                    m = ui.toggle({"all": "Mọi ý tưởng", "broad": "Khớp rộng", "phrase": "Khớp cụm"},
                                  value=state["match"],
                                  on_change=lambda e: (state.update(match=e.value, word=None, word_label=""),
                                                       fbar.refresh(), words_panel.refresh(), table.refresh())
                                  ).props(seg).classes("sr-seg")
                    m.tooltip("Khớp rộng: chứa đủ các từ của từ khóa gốc (thứ tự bất kỳ). Khớp cụm: chứa đúng cụm "
                              "từ khóa gốc. Mọi ý tưởng: cả từ khóa liên quan Google gợi ý.")
                ui.space()
                ui.input(placeholder="Tìm trong danh sách", value=state["q"],
                         on_change=lambda e: (state.update(q=e.value or ""), words_panel.refresh(),
                                              table.refresh())).props(
                    "outlined dense clearable debounce=300").classes("sr-op-search").props(
                    'aria-label="Tìm trong danh sách"')
                with ui.button(icon="view_column").props('flat round dense aria-label="Chọn cột hiển thị"').tooltip(
                        "Chọn cột hiển thị"):
                    with ui.menu().classes("sr-kr-fmenu"):
                        with ui.column().classes("q-pa-sm gap-0"):
                            ui.label("Cột hiển thị").classes("text-sm font-semibold q-mb-xs")
                            for key, name in OPTIONAL_COLS.items():
                                ui.checkbox(name, value=key not in state["hidden"],
                                            on_change=lambda e, k=key: toggle_col(k, e.value)).props("dense")
                            ui.label("File xuất và Sao chép luôn có đủ cột.").classes("text-xs muted q-mt-xs")
                ui.toggle({"list": "Danh sách", "groups": "Nhóm chủ đề"}, value=state["view"],
                          on_change=lambda e: (state.update(view=e.value, shown_groups=30), table.refresh())).props(
                    seg).classes("sr-seg")
                from .web_export import export_menu
                export_menu(ui, cfg, connect, file_name(), make_xlsx, user=user, category="research")
            fbar()
            with ui.element("div").classes("sr-kr-magic"):
                with ui.element("div").classes("sr-kr-words"):
                    words_panel()
                with ui.element("div").classes("sr-kr-main"):
                    table()

    results()
    if preset and preset[1].strip() and not auto and ed:
        from nicegui import background_tasks
        anchor = ui.element("div").classes("hidden")  # chỗ bám cho thông báo / làm mới khi chạy ngoài sự kiện bấm

        async def auto_run():
            with anchor:
                await go()
        background_tasks.create(auto_run())


OPTIONAL_COLS = {"flags": "Rank · AIO", "intent": "Mục đích", "trend": "Xu hướng", "comp": "Cạnh tranh",
                 "cpc": "CPC", "pillar": "Pillar", "site": "Website bạn"}


def _norm_url(u: str) -> str:
    """So khớp URL: bỏ http(s), www, tham số và dấu / cuối."""
    import re
    return re.sub(r"^https?://(www\.)?", "", (u or "").strip().lower()).split("?")[0].split("#")[0].rstrip("/")


def _host(u: str) -> str:
    return _norm_url(u).split("/")[0]


def _hidden_cols() -> set[str]:
    """Cột người dùng đã ẩn (nhớ theo trình duyệt); mặc định ẩn CPC."""
    try:
        from nicegui import app
        return set(app.storage.user.get("kr_hidden_cols", ["cpc"]))
    except Exception:  # noqa: BLE001
        return {"cpc"}


def short_url(u: str, keep: int = 48) -> str:
    """https://www.site.vn/a/b/?x=1 → site.vn/a/b/; dài quá thì giữ phần cuối, "…" ở đầu."""
    import re
    t = re.sub(r"^https?://(www\.)?", "", u.strip()).split("?")[0].split("#")[0]
    return t if len(t) <= keep else "…" + t[-(keep - 1):]


def seed_label(seed: str, show: int = 3) -> str:
    """Từ khóa gốc gọn cho tiêu đề / lịch sử: 3 từ khóa đầu, còn lại ghi "+ n từ khóa"; URL / tên miền rút gọn."""
    s0 = seed.strip()
    if "\n" not in s0 and ("://" in s0 or (" " not in s0 and "/" in s0)):
        return short_url(s0)
    parts = KR.split_keywords(seed) if ("\n" in seed or "," in seed) else [seed.strip()]
    head_ = ", ".join(parts[:show])
    return head_ + (f" + {len(parts) - show} từ khóa" if len(parts) > show else "")


def _esc(t: str) -> str:
    from html import escape
    return escape(t)
