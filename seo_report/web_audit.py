"""Technical Audit (/audit, menu Website): checklist kỹ thuật SEO theo 10 hạng mục của bộ tiêu chuẩn "Technical
Search & GEO" (audit_checklist.py). Tool tự mở các URL trong nhóm URL SEO và trang nhiều traffic nhất (tối đa
site_audit.MAX_PAGES trang), kiểm tra từng trang và cả website (site_checks.py). Tự quét mỗi tuần, miễn phí. Chỉ team.

Hai tab: Checklist (tổng kết, việc làm trước, thay đổi so với lần quét trước, từng tiêu chí có trạng thái Đạt / Cần
sửa / Nên sửa / Tham khảo / Chưa kiểm; bấm một tiêu chí để xem bảng Trang · Đang là · Nên là, đánh dấu "Cố ý, bỏ qua")
· Theo trang (mỗi trang một dòng). Link cũ /co-hoi?tab=audit và ?tab=schema vẫn mở được."""
from datetime import date

from . import access as A
from . import audit_checklist as AC
from . import keywords as K
from . import points as PT
from . import site_audit as SA
from . import table_kit as TK
from . import ui_theme as T

TABS = (("loi", "Checklist"), ("trang", "Theo trang"))
HOW = ["Trang được quét: mọi URL trong nhóm URL SEO (Quản lý URL) luôn được quét trước, kể cả trang mới chưa có "
       "click; rồi thêm trang nhiều click (rồi nhiều lượt hiển thị) nhất trên Search Console 90 ngày qua cho đủ {n} "
       "trang, bỏ URL có tham số và URL cũ. Quét lại mỗi tuần, miễn phí; người có quyền sửa bấm “Quét ngay” để quét "
       "liền.",
       "Checklist chia 10 hạng mục theo bộ tiêu chuẩn Technical Search & GEO của team; mã trong cột thứ hai (ACC-003, "
       "LINK-002…) là mã tiêu chí của bộ đó. Mỗi tiêu chí có trạng thái: Đạt (đã kiểm, không trang nào vướng), Cần sửa "
       "(ảnh hưởng trực tiếp tới việc lên Google), Nên sửa, Tham khảo, Chưa kiểm (thiếu dữ liệu, ví dụ URL không mở "
       "được lúc kiểm: không tính là lỗi).",
       "Bấm một tiêu chí để xem bảng Trang · Đang là · Nên là, lọc, xuất Excel riêng. Trường hợp cố ý (ví dụ trang "
       "ẩn khỏi Google có chủ đích) thì tick rồi bấm “Cố ý, bỏ qua”: lần quét sau không tính là lỗi nữa, vẫn xem lại / "
       "bỏ đánh dấu được.",
       "Việc làm trước xếp theo mức nặng rồi tới số click của các trang bị ảnh hưởng. Chặn bot huấn luyện AI (GPTBot…) "
       "là chính sách của website, không phải lỗi; cho bot tìm kiếm AI vào cũng không bảo đảm được trích dẫn."]
NOGRP = "(không thuộc nhóm)"


def _path(url: str, site: str) -> str:
    from .web_opps import _path as p_
    return p_(url, site)


def build_audit_page(ui, cfg, connect, user, start: str = "") -> None:
    from nicegui import background_tasks, run
    site = cfg.site_url
    with connect() as c:
        end = K.latest_date(c, site)
    right = T.page_header(ui, "fact_check", "Technical Audit",
                          "Checklist kỹ thuật SEO của các URL trong nhóm URL SEO và trang nhiều traffic nhất (tối đa "
                          f"{SA.MAX_PAGES} trang). Tự quét mỗi tuần, miễn phí.")
    ed = A.can_edit(user)
    open_area = "schema" if start == "schema" else ""  # link cũ ?tab=schema: mở hạng mục Schema
    state = {"tab": start if start in dict(TABS) else TABS[0][0], "au": None, "kit": TK.new_state(), "kits": {},
             "clicks": {}, "groups": {}, "sc": None, "diff": None, "prev_at": None, "only_bad": False,
             "exp": {}, "open": open_area}
    key = str(cfg.db_path)

    def pick(v: str) -> None:
        state["tab"] = v
        ui.run_javascript(f"history.replaceState(null, '', '/audit' + ('{v}' === '{TABS[0][0]}' ? '' : '?tab={v}'))")

    # ------------------------------------------------------------ đầu trang: Cách đọc · Quét ngay / tiến độ · Xuất
    @ui.refreshable
    def actions() -> None:
        au = state["au"]
        with ui.button(icon="help_outline").props('flat round dense color=grey-8 aria-label="Cách đọc"'):
            ui.tooltip("Cách đọc")
            with ui.menu().classes("sr-kr-fmenu"):
                with ui.column().classes("q-pa-md gap-2").style("max-width:440px"):
                    ui.label("Cách đọc").classes("text-sm font-semibold")
                    for t in HOW:
                        ui.label(t.format(n=SA.MAX_PAGES)).classes("text-sm")
        if key in SA.running:
            prog = ui.label().classes("text-sm muted")

            def tick():
                r = SA.running.get(key)
                if not r:
                    prog.text = "Đã quét xong: tải lại trang để xem kết quả"
                elif r.get("phase") == "site":  # giai đoạn 2: robots.txt, HTTPS, link nội bộ, canonical, sitemap
                    prog.text = (f"Đang kiểm link, canonical, sitemap {r['n']:,}/{r['total']:,} URL".replace(",", ".")
                                 if r["total"] else "Đang kiểm robots.txt, HTTPS, bot AI…")
                else:
                    prog.text = f"Đang quét trang {r['n']}/{r['total'] or '…'}"
            tick()
            ui.timer(2, tick)
        elif ed:
            btn = ui.button("Quét ngay", icon="travel_explore").props("unelevated no-caps")
            btn.on_click(lambda: scan_now(btn))
        if au and au["pages"]:
            from .web_export import export_menu
            last = au["run"]
            stamp = (last["finished_at"] or "")[:10] if last else ""
            export_menu(ui, cfg, connect, f"audit-ky-thuat_{stamp or end}",
                        lambda: audit_xlsx(au, site, AC.build(au, state["sc"], au.get("meta") or {})), user=user,
                        category="audit")
    with right:
        actions()

    async def scan_now(btn) -> None:
        from contextlib import closing

        from . import db
        from . import notices as N
        if not ed or key in SA.running:
            return
        _pt = PT.take(ui, user, cfg, "audit")
        if _pt is False:
            return
        SA.running[key] = {"n": 0, "total": 0, "by": str(user), "phase": "pages"}
        btn.props("loading")
        note = ui.notification("Đang quét các trang quan trọng và kiểm tra cấp website (khoảng 10 phút, có thể rời "
                               "trang)…", spinner=True, timeout=None, type="ongoing", position="bottom-right")

        def prog(n, total, phase="pages"):
            SA.running[key].update(n=n, total=total, phase=phase)

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                from .cwv import load_key
                try:
                    key_ = load_key(cfg)
                except Exception:  # noqa: BLE001
                    key_ = ""
                return SA.run(c, site, end, str(user), progress=prog, log=lambda m: None, key=key_)
        actions.refresh()
        r, err = None, None
        try:
            r = await run.io_bound(work)
        except Exception as ex:  # noqa: BLE001
            err = ex
            PT.give_back(_pt)
        finally:
            SA.running.pop(key, None)
        N.forget()
        # Quét lâu nên người dùng hay rời trang giữa chừng: kết quả đã lưu, phần báo / vẽ lại thì bỏ qua
        try:
            note.dismiss()
            if err:
                ui.notify(f"Quét chưa xong: {err}", type="warning", position="bottom-right")
            else:
                ui.notify(f"Đã quét {r['pages']} trang" + (f" ({r['errors']} trang không mở được)" if r["errors"]
                                                             else ""), type="positive", position="bottom-right")
            await reload()
        except RuntimeError:
            pass

    def _clicks(c, au: dict) -> dict:
        ids = sorted({p["url_id"] for ch in au["checks"] for p in ch["pages"] if p.get("url_id") is not None})
        return SA.page_clicks(c, site, end, ids)

    def read_all(c) -> dict:
        """Mọi thứ trang cần, đọc một lần (chạy trong luồng nền)."""
        from . import site_checks as SC
        au = SA.cached_findings(c, cfg)
        prev, prev_at = SA.findings_history(c, au) if au.get("run") else (None, None)
        return {"au": au, "clicks": _clicks(c, au), "groups": SA.url_groups(c, site), "sc": SC.latest(c),
                "diff": AC.diff(AC.snapshot(au), prev, set(au.get("scanned") or [])), "prev_at": prev_at}

    async def reload() -> None:
        from contextlib import closing

        from . import db

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                return read_all(c)
        state.update(await run.io_bound(work))
        actions.refresh()
        body.refresh()

    # ------------------------------------------------------------ bảng chi tiết một mục kiểm tra
    def mark(code: str, rows: list[dict], on: bool) -> None:
        """Đánh dấu / bỏ đánh dấu "Cố ý, bỏ qua" rồi vẽ lại ngay (tính lại kết quả trong vài giây)."""
        with connect() as c:
            n = SA.set_ignored(c, code, list(dict.fromkeys(r["url"] for r in rows)), on, str(user))
            state.update(read_all(c))
        ui.notify((f"Đã bỏ qua {n} dòng: không tính là lỗi nữa, xem lại ở “Đã bỏ qua có chủ ý”" if on else
                   f"Đã tính lại {n} dòng là lỗi"), type="positive", position="bottom-right")
        actions.refresh()
        body.refresh()

    def check_table(ch: dict, ignored: bool = False) -> None:
        """Bảng một mục kiểm tra: Trang · Đang là · Nên là · Ghi chú · Click 28 ngày; lọc, sao chép, xuất riêng; tick
        để đánh dấu "Cố ý, bỏ qua" (hoặc bỏ đánh dấu ở bảng các dòng đã bỏ qua)."""
        clicks, groups = state["clicks"], state["groups"]
        src = ch["ignored"] if ignored else ch["pages"]
        rows = [{"k": f"{p['url']}|{i}", "url": p["url"],
                 "path": _path(p["url"], site) if p["url"].startswith("http") else p["url"],
                 "is_url": p["url"].startswith("http"), "now": p.get("now") or p.get("detail") or "",
                 "want": p.get("want") or "", "extra": p.get("extra") or "",
                 "clicks": (clicks.get(p.get("url_id")) or (0, 0))[0],
                 "grp_l": groups.get(p.get("url_id")) or [NOGRP], "type": p.get("type") or ""}
                for i, p in enumerate(src)]
        rows.sort(key=lambda r: -r["clicks"])
        has_grp = not ch.get("site") and any(r["grp_l"] != [NOGRP] for r in rows)
        has_extra = any(r["extra"] for r in rows)
        has_type = len({r["type"] for r in rows if r["type"]}) > 1
        kit = state["kits"].setdefault(ch["code"] + ("-ign" if ignored else ""), TK.new_state())
        acts = []
        if ed:
            acts.append({"label": (lambda sel: f"Tính lại là lỗi · {len(sel)}") if ignored else
                         (lambda sel: f"Cố ý, bỏ qua · {len(sel)}"), "icon": "undo" if ignored else "block",
                         "on": lambda sel, code=ch["code"]: mark(code, sel, not ignored)})
        TK.table(ui, columns=[
            {"name": "path", "label": "Trang" if not ch.get("site") else "URL", "field": "path", "align": "left",
             "sortable": True},
            {"name": "now", "label": "Đang là", "field": "now", "align": "left", "width": 260},
            {"name": "want", "label": "Nên là", "field": "want", "align": "left", "width": 220},
            *([{"name": "extra", "label": "Ghi chú", "field": "extra", "align": "left", "width": 200}]
              if has_extra else []),
            *([{"name": "type", "label": "Loại trang", "field": "type", "align": "left", "width": 120}]
              if has_type else []),
            *([{"name": "clicks", "label": "Click 28 ngày", "field": "clicks", "align": "right", "sortable": True,
                "width": 120, ":format": "v => v.toLocaleString('vi-VN')"}] if not ch.get("site") else []),
        ], rows=rows, row_key="k", st=kit, noun=ch.get("unit", "trang"), page_size=10,
            filters=[("text", "Trang / nội dung", ["path", "now", "want", "extra"]),
                     *([("num", "Click 28 ngày", "clicks")] if not ch.get("site") else []),
                     *([("enum", "Nhóm URL", "grp_l")] if has_grp else []),
                     *([("enum", "Loại trang", "type")] if has_type else [])],
            copy=[("Trang", "url"), ("Đang là", "now"), ("Nên là", "want"), ("Ghi chú", "extra"),
                  ("Loại trang", "type"), ("Click 28 ngày", "clicks")],
            export=f"audit-{ch['code']}" + ("-bo-qua" if ignored else ""), actions=acts or None,
            slots={"body-cell-path": """
                <q-td :props="props"><div class="sr-bl-src"><a v-if="props.row.is_url" :href="props.row.url"
                  target="_blank" rel="noopener" class="sr-bl-link" :title="props.row.url">{{ props.value }}</a>
                  <span v-else>{{ props.value }}</span></div></q-td>""",
                   "body-cell-now": """<q-td :props="props"><div class="sr-op-detail">{{ props.value || '–' }}</div>
                </q-td>""",
                   "body-cell-want": """<q-td :props="props"><div class="sr-op-detail sr-ta-want">{{ props.value
                  || '–' }}</div></q-td>"""})

    def root_cause(ch: dict) -> None:
        """Bộ tiêu chuẩn: một lỗi giao diện (template) thường gây ra hàng loạt URL lỗi; sửa một chỗ là xong."""
        types = [p.get("type") for p in ch["pages"] if p.get("type")]
        if len(ch["pages"]) < 5 or not types:
            return
        top = max(set(types), key=types.count)
        n_ = types.count(top)
        if n_ / len(ch["pages"]) >= 0.8:
            ui.label(f"{n_}/{len(ch['pages'])} {ch.get('unit', 'trang')} là trang {top}: nhiều khả năng do một lỗi chung "
                     "của giao diện trang này, sửa một chỗ là hết.").classes("text-xs sr-ta-root")

    def check_block(ch: dict, many: bool) -> None:
        if many:  # tiêu chí gom nhiều mục: tên mục nhỏ ở trên mỗi bảng
            name, tone = SA.LEVELS[ch["level"]]
            with ui.row().classes("items-center gap-2 q-mt-sm"):
                T.pill(ui, name, tone)
                ui.label(f"{ch['name']} · {len(ch['pages'])} {ch.get('unit', 'trang')}").classes(
                    "text-sm font-semibold")
        ui.label(ch["fix"]).classes("text-sm q-mb-xs")
        root_cause(ch)
        check_table(ch)

    def ignored_block(row: dict) -> None:
        ign = [ch for ch in (state["au"].get("ignored_checks") or []) if ch["code"] in row["codes"]]
        ign += [ch for ch in row["checks"] if ch.get("ignored")]
        n_ = sum(len(ch["ignored"]) for ch in ign)
        if not n_:
            return
        with ui.expansion(f"Đã bỏ qua có chủ ý · {n_}").props("dense").classes("w-full sr-au-fold q-mt-xs"):
            for ch in ign:
                if ch["ignored"]:
                    ui.label(ch["name"]).classes("text-xs muted q-mt-xs")
                    check_table(ch, ignored=True)

    # ------------------------------------------------------------ phần riêng của vài tiêu chí
    def host_detail() -> None:
        host = (state["sc"] or {}).get("host") or []
        if not host:
            return
        rows = [{"id": h["url"], "url": h["url"] + (" (địa chỉ chính)" if h["main"] else ""),
                 "chain": " → ".join(f"{st or '?'}" for _, st in h["chain"]) or (h["error"] or "–"),
                 "final": h["final"] or "–", "problem": h["problem"] or ("không có (không phải lỗi)" if h["error"]
                                                                          else "Đạt")} for h in host]
        ui.table(columns=[
            {"name": "url", "label": "Địa chỉ", "field": "url", "align": "left"},
            {"name": "chain", "label": "Mã trả về", "field": "chain", "align": "left"},
            {"name": "final", "label": "Về tới", "field": "final", "align": "left"},
            {"name": "problem", "label": "Kết luận", "field": "problem", "align": "left"},
        ], rows=rows, row_key="id").props("flat dense hide-bottom").classes("w-full sr-bl-table q-mt-xs")

    def bots_detail() -> None:
        bots = (state["sc"] or {}).get("bots") or []
        if not bots:
            return
        ui.label("Bot tìm kiếm lấy nội dung để trả lời và trích dẫn; chặn thì website khó xuất hiện ở đó, cho vào cũng "
                 "không bảo đảm được trích dẫn. Bot huấn luyện chỉ lấy dữ liệu dạy mô hình: chặn hay không là chính "
                 "sách của website, không phải lỗi; chặn GPTBot không chặn ChatGPT Search.").classes(
            "text-xs muted q-mb-xs")
        rows = [{"id": b["bot"], "bot": b["bot"], "use": b["use"],
                 "kind": "Tìm kiếm" if b["kind"] == "search" else "Huấn luyện (chính sách)",
                 "home": "Được vào" if b["home"] else "Bị chặn", "pages": f"{b['blocked']}/{b['total']}",
                 "rule": b["rule"] or ("có nhóm riêng" if b["named"] else "theo nhóm *")} for b in bots]
        ui.table(columns=[
            {"name": "bot", "label": "Bot", "field": "bot", "align": "left"},
            {"name": "use", "label": "Dùng để", "field": "use", "align": "left"},
            {"name": "kind", "label": "Loại", "field": "kind", "align": "left"},
            {"name": "home", "label": "Trang chủ", "field": "home", "align": "left"},
            {"name": "pages", "label": "Trang bị chặn", "field": "pages", "align": "right"},
            {"name": "rule", "label": "Dòng robots.txt", "field": "rule", "align": "left"},
        ], rows=rows, row_key="id").props("flat dense hide-bottom").classes("w-full sr-bl-table")

    def evidence(row: dict) -> str:
        """Câu "đã kiểm thế nào" cho tiêu chí Đạt / phạm vi kiểm của vài tiêu chí."""
        sc, au = state["sc"] or {}, state["au"]
        unk = (au.get("meta") or {}).get("unknown") or {}
        n_ = (lambda v: f"{v:,}".replace(",", "."))
        if row["need"] == "links":
            lk = sc.get("links") or {}
            return (f"Đã kiểm {n_(lk.get('checked', 0))}/{n_(lk.get('targets', 0))} URL được link tới từ các trang đã "
                    "quét" + (f" · {n_(unk['links'])} link chưa mở được lúc kiểm (không tính là lỗi)"
                              if unk.get("links") else ""))
        if row["need"] == "sitemap":
            sm = sc.get("sitemap") or {}
            return (f"Đã kiểm {n_(sm.get('checked', 0))}/{n_(sm.get('urls', 0))} URL trong sitemap (kiểm dần qua các "
                    "lần quét)" + (f" · {n_(unk['sitemap'])} URL chưa mở được lúc kiểm (không tính là lỗi)"
                                   if unk.get("sitemap") else ""))
        if row["need"] == "safe":
            return f"Đã hỏi Google Safe Browsing cho {n_((sc.get('safe') or {}).get('checked', 0))} URL"
        if row["need"] == "robots":
            rob = sc.get("robots") or {}
            return ("Website không có robots.txt: Google được crawl tất cả" if rob.get("missing") else
                    f"Đã đọc robots.txt và thử với {n_((au.get('meta') or {}).get('pages', 0))} trang đã quét")
        return f"Không trang nào vướng trong {n_(au['pages'])} trang đã quét"

    # ------------------------------------------------------------ một tiêu chí
    def criterion(row: dict, idx: str) -> None:
        label, tone = AC.LABEL[row["status"]]
        bad = row["status"] in ("high", "medium", "info")
        with ui.expansion().classes("w-full sr-ta-crit").props(f'dense id="crit-{idx}"') as ex:
            with ex.add_slot("header"):
                with ui.row().classes("w-full items-center gap-x-3 gap-y-1 sr-ta-head"):
                    T.pill(ui, label, tone)
                    ui.label(row["code"] or "—").classes("sr-ta-code")
                    ui.label(row["name"]).classes("text-sm sr-ta-name")
                    ui.label(f"{row['count']:,} {row['unit']}".replace(",", ".") if bad else "").classes(
                        "text-sm num muted sr-ta-n")
            if row["status"] == "unknown":
                ui.label(f"Chưa kiểm: {row['why']}.").classes("text-sm muted")
            elif row["status"] == "na":
                ui.label("Không áp dụng cho website này (chưa thấy trang sản phẩm).").classes("text-sm muted")
            elif row["status"] == "ok":
                ui.label(f"Đạt. {evidence(row)}.").classes("text-sm")
            if bad and row["need"] in ("links", "sitemap"):
                ui.label(evidence(row) + ".").classes("text-xs muted q-mb-xs")
            for ch in row["checks"]:
                check_block(ch, len(row["checks"]) > 1)
            if row["need"] == "host":
                host_detail()
            if row["need"] == "bots":
                bots_detail()
            ignored_block(row)
        for ch in row["checks"]:
            state["exp"][ch["code"]] = (ex, f"crit-{idx}")
        for code in row["codes"]:
            state["exp"].setdefault(code, (ex, f"crit-{idx}"))

    def go_check(code: str) -> None:
        """Từ "Việc làm trước" / "Thay đổi": mở đúng tiêu chí và cuộn tới."""
        hit = state["exp"].get(code)
        if hit:
            hit[0].set_value(True)
            T.scroll_to(ui, hit[1])

    # ------------------------------------------------------------ tab Checklist
    def summary(areas: list[dict], au: dict) -> None:
        tot = AC.totals(areas)
        dif = state["diff"] or {}
        tiles = [(f"{tot['checked']}", "tiêu chí đã kiểm", ""), (f"{tot['ok']}", "đạt", "green"),
                 (f"{tot['high']}", "cần sửa", "red" if tot["high"] else ""),
                 (f"{tot['medium']}", "nên sửa", "amber" if tot["medium"] else ""),
                 (f"{tot['unknown']}", "chưa kiểm", "")]
        with ui.element("div").classes("sr-op-audit-sum sr-ta-sum w-full"):
            for num, lab, tone in tiles:
                with ui.element("div").classes("sr-op-stat"):
                    ui.label(num).classes("sr-op-stat-num" + (f" t-{tone}" if tone else ""))
                    ui.label(lab).classes("text-sm muted")
            with ui.element("div").classes("sr-op-stat"):
                if dif.get("has_prev"):
                    ui.label(f"+{len(dif['new'])} · −{len(dif['fixed'])}").classes("sr-op-stat-num")
                    ui.label(f"lỗi mới · đã hết, so với lần quét {_vn_day(state['prev_at'])}").classes("text-sm muted")
                else:
                    ui.label("–").classes("sr-op-stat-num")
                    ui.label("so với lần trước: chưa có lần quét trước để so").classes("text-sm muted")

    def todo(au: dict) -> None:
        pr = AC.priorities(au, state["clicks"])
        if not pr:
            return
        with ui.element("div").classes("sr-ta-todo w-full"):
            with ui.row().classes("items-baseline gap-2"):
                ui.label("Việc làm trước").classes("text-sm font-semibold")
                ui.label("xếp theo mức nặng rồi tới click của trang bị ảnh hưởng").classes("text-xs muted")
            for i, p in enumerate(pr, 1):
                name, tone = SA.LEVELS[p["level"]]
                with ui.element("button").classes("sr-ta-todo-row").props('type="button"').on(
                        "click", lambda _, c_=p["code"]: go_check(c_)):
                    ui.label(f"{i}").classes("sr-ta-todo-n")
                    T.pill(ui, name, tone)
                    ui.label(p["name"]).classes("text-sm sr-ta-name")
                    ui.label(f"{p['count']:,} {p['unit']}".replace(",", ".")
                             + (f" · {p['clicks']:,} click".replace(",", ".") if p["clicks"] else "")).classes(
                        "text-xs muted sr-ta-n")

    def changes(au: dict) -> None:
        dif = state["diff"] or {}
        if not dif.get("has_prev") or not (dif["new"] or dif["fixed"]):
            return
        names = {c: n for c, (_, n, _) in SA.CHECKS.items()}
        with ui.expansion(f"Thay đổi so với lần quét {_vn_day(state['prev_at'])}: {len(dif['new'])} lỗi mới · "
                          f"{len(dif['fixed'])} đã hết").props("dense").classes("w-full sr-au-fold"):
            for title, items, tone in (("Lỗi mới", dif["new"], "red"), ("Đã hết (trang vẫn được quét)", dif["fixed"],
                                                                     "green")):
                if not items:
                    continue
                ui.label(f"{title} · {len(items)}").classes("text-xs muted q-mt-xs")
                rows = [{"id": f"{c}|{u}", "name": names.get(c, c), "url": _path(u, site) if u.startswith("http")
                         else u} for c, u in items[:200]]
                ui.table(columns=[{"name": "name", "label": "Mục", "field": "name", "align": "left"},
                                  {"name": "url", "label": "Trang / URL", "field": "url", "align": "left"}],
                         rows=rows, row_key="id", pagination=10).props("flat dense").classes("w-full sr-bl-table")

    @ui.refreshable
    def areas_view(areas: list[dict]) -> None:
        state["exp"] = {}
        for i, a in enumerate(areas, 1):
            rows = [r for r in a["rows"] if not state["only_bad"] or r["status"] not in ("ok", "na")]
            if not rows:
                continue
            cnt = a["counts"]
            parts = [f"{cnt[k]} {AC.LABEL[k][0].lower()}" for k in ("high", "medium", "info", "ok", "unknown")
                     if cnt.get(k)]
            with ui.element("div").classes("sr-ta-area w-full").props(f'id="area-{a["key"]}"'):
                with ui.row().classes("w-full items-baseline gap-2 sr-ta-area-h"):
                    ui.label(f"{i}. {a['name']}").classes("sr-ta-area-name")
                    ui.label(" · ".join(parts)).classes("text-xs muted")
                for j, r in enumerate(rows):
                    criterion(r, f"{a['key']}-{j}")
                if a["key"] == "schema":
                    with ui.expansion("Kết quả nổi bật trên Google và theo dõi schema qua các lần quét").props(
                            "dense").classes("w-full sr-ta-crit"):
                        schema_detail()

    def checklist_tab(au: dict) -> None:
        if not au["pages"]:
            T.empty_state(ui, "fact_check", "Chưa có kết quả audit",
                          "Bấm “Quét ngay” ở đầu trang (người có quyền sửa) hoặc chờ lịch quét hằng tuần.")
            return
        areas = AC.build(au, state["sc"], au.get("meta") or {})
        summary(areas, au)
        todo(au)
        changes(au)
        with ui.row().classes("w-full items-center gap-2 q-mt-md"):
            ui.toggle({False: "Tất cả tiêu chí", True: "Chỉ tiêu chí chưa đạt"}, value=state["only_bad"],
                      on_change=lambda e: (state.update(only_bad=e.value), areas_view.refresh(areas))).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
        areas_view(areas)
        if state["open"]:  # link cũ ?tab=schema
            T.scroll_to(ui, f"area-{state['open']}")
            state["open"] = ""

    # ------------------------------------------------------------ schema: kết quả nổi bật, theo dõi, loại đang dùng
    def schema_detail() -> None:
        from . import gsc_types as GT
        with connect() as c:
            SA.snapshot(c)
            sm = SA.schema_summary(c)
            hist = SA.schema_history(c)
            try:
                app, period = GT.appearance(c, site)
            except Exception:  # noqa: BLE001  (chưa lấy số loại kết quả của Search Console)
                app, period = [], None
        n = (lambda v: f"{v:,}".replace(",", "."))
        if not sm["pages"]:
            ui.label("Lần quét gần nhất chưa ghi dữ liệu cấu trúc. Bấm “Quét ngay” ở đầu trang để có số.").classes(
                "text-sm muted")
            return
        stats = [(f"{sm['with']}/{sm['pages']}", "trang có dữ liệu cấu trúc", "")]
        if sm["products"]:
            stats.append((f"{sm['rated']}/{sm['products']}", "sản phẩm có sao đánh giá",
                          "amber" if sm["rated"] < sm["products"] / 2 else ""))
        with ui.element("div").classes("sr-op-audit-sum w-full"):
            for num, lab, tone in stats:
                with ui.element("div").classes("sr-op-stat"):
                    ui.label(num).classes("sr-op-stat-num" + (f" t-{tone}" if tone else ""))
                    ui.label(lab).classes("text-sm muted")
        if app:
            ui.label("Kết quả nổi bật trên Google").classes("text-sm font-semibold q-mt-md")
            ui.label((f"Search Console {_vn_day(period[0])} – {_vn_day(period[1])}, so với 28 ngày trước"
                      if period else "Search Console 28 ngày") + ". Các dạng hiển thị nhờ dữ liệu cấu trúc: khai báo "
                     "rồi mà số thấp nghĩa là Google chưa dùng.").classes("text-xs muted")

            def chg(cur, prev):
                if prev is None:
                    return "mới"
                d_ = (cur or 0) - prev
                return "–" if not d_ else f"{'▲' if d_ > 0 else '▼'} {n(abs(d_))}"
            rows = [{"id": k, "name": a["name"], "clicks": a["clicks"] or 0, "impr": a["impressions"] or 0,
                     "c_chg": chg(a["clicks"], a["prev_clicks"]), "up": (a["clicks"] or 0) >= (a["prev_clicks"] or 0)}
                    for k, a in enumerate(app)]
            tb = ui.table(columns=[
                {"name": "name", "label": "Dạng hiển thị", "field": "name", "align": "left"},
                {"name": "clicks", "label": "Click", "field": "clicks", "align": "right", "sortable": True,
                 ":format": "v => v.toLocaleString('vi-VN')"},
                {"name": "c_chg", "label": "So với kỳ trước", "field": "c_chg", "align": "right"},
                {"name": "impr", "label": "Lượt hiển thị", "field": "impr", "align": "right", "sortable": True,
                 ":format": "v => v.toLocaleString('vi-VN')"},
            ], rows=rows, row_key="id").props("flat dense hide-bottom").classes("w-full sr-bl-table")
            tb.add_slot("body-cell-c_chg", """
                <q-td :props="props" class="text-right"><span class="num"
                  :style="{color: props.value === '–' || props.value === 'mới' ? '#8C8A7E' :
                           (props.row.up ? '#1E7C31' : '#C2410C')}">{{ props.value }}</span></q-td>""")
        if hist:
            ui.label("Theo dõi qua các lần quét").classes("text-sm font-semibold q-mt-md")

            def cell(h, key_):
                v = h.get(key_)
                return "chưa kiểm" if v is None else n(v)
            hrows = [{"id": k, "at": _vn_day(h["at"][:10]), "with": f"{h['with']}/{h['pages']}",
                      "rated": f"{h.get('rated', 0)}/{h.get('products', 0)}",
                      "ship": cell(h, "no_shipping"), "ret": cell(h, "no_returns"), "bad": n(h.get("bad", 0))}
                     for k, h in enumerate(hist)]
            ui.table(columns=[
                {"name": "at", "label": "Lần quét", "field": "at", "align": "left"},
                {"name": "with", "label": "Trang có schema", "field": "with", "align": "right"},
                {"name": "rated", "label": "Sản phẩm có sao", "field": "rated", "align": "right"},
                {"name": "ship", "label": "Thiếu phí ship", "field": "ship", "align": "right"},
                {"name": "ret", "label": "Thiếu đổi trả", "field": "ret", "align": "right"},
                {"name": "bad", "label": "JSON-LD lỗi", "field": "bad", "align": "right"},
            ], rows=hrows, row_key="id").props("flat dense hide-bottom").classes("w-full sr-bl-table")
        if sm["types"]:
            ui.label(f"Loại schema đang dùng · {len(sm['types'])} loại").classes("text-sm font-semibold q-mt-md")
            rows = [{"id": k, "type": t, "pages": c_, "share": f"{c_ / sm['pages'] * 100:.0f}%"}
                    for k, (t, c_) in enumerate(sm["types"])]
            ui.table(columns=[
                {"name": "type", "label": "Loại (@type)", "field": "type", "align": "left", "sortable": True},
                {"name": "pages", "label": "Số trang", "field": "pages", "align": "right", "sortable": True},
                {"name": "share", "label": "Tỷ lệ trang", "field": "share", "align": "right"},
            ], rows=rows, row_key="id", pagination=10).props("flat dense").classes("w-full sr-bl-table")

    # ------------------------------------------------------------ tab Theo trang
    def pages_tab(au: dict) -> None:
        """Mỗi trang một dòng: số lỗi theo mức và tên các lỗi; lọc, sắp xếp, xuất như các bảng khác."""
        if not au["pages"]:
            T.empty_state(ui, "fact_check", "Chưa có kết quả audit",
                          "Bấm “Quét ngay” ở đầu trang (người có quyền sửa) hoặc chờ lịch quét hằng tuần.")
            return
        per: dict[str, dict] = {}
        for c in au["checks"]:
            if c.get("site"):  # mục cấp website (địa chỉ http / www, sitemap, bot AI) không thuộc trang nào đã quét
                continue
            for p in c["pages"]:
                d = per.setdefault(p["url"], {k: 0 for k in SA.LEVELS} | {"names": [], "uid": p.get("url_id"),
                                                                           "type": p.get("type") or ""})
                d[c["level"]] += 1
                if c["name"] not in d["names"]:
                    d["names"].append(c["name"])
        clicks, groups = state["clicks"], state["groups"]
        rows = [{"url": u, "path": _path(u, site), **{k: d[k] for k in SA.LEVELS},
                 "total": sum(d[k] for k in SA.LEVELS), "names": " · ".join(d["names"]), "names_l": d["names"],
                 "clicks": (clicks.get(d["uid"]) or (0, 0))[0], "grp": ", ".join(groups.get(d["uid"]) or []),
                 "grp_l": groups.get(d["uid"]) or [NOGRP], "type": d["type"]}
                for u, d in per.items()]
        has_grp = any(r["grp"] for r in rows)
        # lỗi nặng trước; cùng mức thì trang nhiều click trước (sửa trang mang traffic trước)
        rows.sort(key=lambda r: (-r["high"], -r["medium"], -r["clicks"], -r["info"], r["path"]))
        ui.label(f"{len(rows)} / {au['pages']} trang có ít nhất một mục cần xem (trang không có mục nào không nằm "
                 "trong bảng). Xếp lỗi nặng trước, cùng mức thì trang nhiều click trước.").classes("text-sm muted q-mb-sm")
        names = {k: n for k, (n, _) in SA.LEVELS.items()}
        cols = [{"name": "path", "label": "Trang", "field": "path", "align": "left", "sortable": True},
                *([{"name": "grp", "label": "Nhóm URL", "field": "grp", "align": "left", "sortable": True,
                    "width": 140}] if has_grp else []),
                {"name": "type", "label": "Loại trang", "field": "type", "align": "left", "sortable": True,
                 "width": 120},
                {"name": "clicks", "label": "Click 28 ngày", "field": "clicks", "align": "right", "sortable": True,
                 "width": 120, ":format": "v => v.toLocaleString('vi-VN')"},
                *[{"name": k, "label": names[k], "field": k, "align": "right", "sortable": True, "width": 100}
                  for k in SA.LEVELS],
                {"name": "names", "label": "Các lỗi", "field": "names", "align": "left", "width": 420}]
        TK.table(ui, columns=cols, rows=rows, row_key="url", st=state["kit"], noun="trang", page_size=25,
                 filters=[("text", "Trang", ["path"]), ("num", "Click 28 ngày", "clicks"),
                          *[("num", names[k], k) for k in SA.LEVELS], ("enum", "Lỗi", "names_l"),
                          ("enum", "Loại trang", "type"), *([("enum", "Nhóm URL", "grp_l")] if has_grp else [])],
                 copy=[("Trang", "url"), ("Nhóm URL", "grp"), ("Loại trang", "type"), ("Click 28 ngày", "clicks"),
                       *[(names[k], k) for k in SA.LEVELS], ("Các lỗi", "names")],
                 export="audit-theo-trang",
                 slots={"body-cell-path": """
                    <q-td :props="props"><div class="sr-bl-src"><a :href="props.row.url" target="_blank"
                      rel="noopener" class="sr-bl-link" :title="props.row.url">{{ props.value }}</a></div></q-td>""",
                        "body-cell-names": """
                    <q-td :props="props"><div class="sr-op-detail">{{ props.value }}</div></q-td>"""})

    # ------------------------------------------------------------ thân trang
    @ui.refreshable
    def body() -> None:
        au = state["au"]
        if au is None:
            with ui.element("div").classes("w-full sr-busy").props('aria-busy="true" aria-label="Đang tải"'):
                T.bone(ui, "420px", radius="14px")
            return
        last = au["run"]
        if last and last["finished_at"]:
            from datetime import datetime
            at = datetime.fromisoformat(last["finished_at"]).astimezone()
            ui.label(f"Quét lần gần nhất {at:%H:%M %d/%m/%Y} · {last['pages']} trang"
                     + (f" · {last['errors']} trang không mở được" if last["errors"] else "")
                     + (" · đang quét lần mới" if key in SA.running else "")).classes("text-xs muted q-mb-xs")
        elif key not in SA.running:
            ui.label("Chưa quét lần nào.").classes("text-xs muted q-mb-xs")
        n_fix = AC.totals(AC.build(au, state["sc"], au.get("meta") or {}))["high"] if au["pages"] else 0
        label = {"loi": f"Checklist · {n_fix} cần sửa" if n_fix else "Checklist", "trang": "Theo trang"}
        with ui.tabs(value=state["tab"], on_change=lambda e: pick(e.value)).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs") as tabs:
            for k, _ in TABS:
                ui.tab(k, label[k])
        with ui.tab_panels(tabs, value=state["tab"]).classes("w-full").props("animated=false"):
            with ui.tab_panel("loi").classes("q-px-none"):
                with ui.element("div").classes("sr-card sr-op-panel w-full"):
                    checklist_tab(au)
            with ui.tab_panel("trang").classes("q-px-none"):
                pages_tab(au)

    body()

    async def load() -> None:
        try:
            await reload()
        except Exception as ex:  # noqa: BLE001
            state["au"] = {"checks": [], "pages": 0, "healthy": 0, "run": None}
            ui.notify(f"Chưa đọc được kết quả audit: {ex}", type="warning")
            actions.refresh()
            body.refresh()

    background_tasks.create(load())


def _vn_day(iso: str | None) -> str:
    try:
        return f"{date.fromisoformat(str(iso)[:10]):%d/%m/%Y}"
    except (TypeError, ValueError):
        return "–"


def audit_xlsx(au: dict, site: str, areas: list[dict] | None = None) -> bytes:
    """File audit: Checklist (mỗi tiêu chí một dòng: hạng mục, mã, trạng thái, số trang, cách sửa — khớp checklist
    của team) · Tóm tắt · Lỗi theo trang (mỗi dòng một lỗi: đang là / nên là) · Theo trang · Đã bỏ qua."""
    import io
    from datetime import datetime

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="EEF3E6")
    fills = {"high": "FCE4D6", "medium": "FFF2CC", "info": "DDEBF7", "ok": "E2EFDA", "unknown": "EDEDED",
             "na": "EDEDED"}
    wb = Workbook()

    def table(ws, head, rows, widths, level_col=None, levels=None):
        ws.append(head)
        for c in ws[ws.max_row]:
            c.font, c.fill = bold, head_fill
        start = ws.max_row
        for r in rows:
            ws.append(r)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        names = levels or {k: n for k, (n, _) in SA.LEVELS.items()}
        rev = {n: k for k, n in names.items()}
        for row in ws.iter_rows(min_row=start + 1):
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=True)
            if level_col is not None and rev.get(row[level_col].value) in fills:
                row[level_col].fill = PatternFill("solid", fgColor=fills[rev[row[level_col].value]])
        ws.auto_filter.ref = f"A{start}:{get_column_letter(len(head))}{ws.max_row}"
        ws.freeze_panes = f"A{start + 1}"

    # 1. Checklist
    ws = wb.active
    ws.title = "Checklist"
    labels = {k: n for k, (n, _) in AC.LABEL.items()}
    rows = []
    for a in areas or []:
        for r in a["rows"]:
            fix = " / ".join(ch["fix"] for ch in r["checks"])
            rows.append([a["name"], r["code"] or "", r["name"], labels[r["status"]],
                         r["count"] if r["status"] in ("high", "medium", "info") else "",
                         fix if r["checks"] else (r["why"] or ""), ", ".join(ch["name"] for ch in r["checks"])])
    table(ws, ["Hạng mục", "Mã", "Tiêu chí", "Trạng thái", "Số trang / URL", "Cách sửa / ghi chú", "Mục vướng"],
          rows, [22, 11, 46, 13, 12, 80, 40], level_col=3, levels=labels)

    # 2. Tóm tắt
    ws = wb.create_sheet("Tóm tắt")
    last = au["run"] or {}
    at = ""
    if last.get("finished_at"):
        at = f"{datetime.fromisoformat(last['finished_at']).astimezone():%H:%M %d/%m/%Y}"
    lp = SA.level_pages(au)
    tot = AC.totals(areas or [])
    for k, v in (("Website", site), ("Quét lúc", at), ("Số trang đã quét", au["pages"]),
                 ("Trang không mở được", last.get("errors") or 0),
                 ("Tiêu chí đã kiểm", tot.get("checked", 0)), ("Tiêu chí đạt", tot.get("ok", 0)),
                 ("Tiêu chí chưa kiểm", tot.get("unknown", 0)),
                 *[(f"Trang có mục {name}", lp[k]) for k, (name, _) in SA.LEVELS.items()]):
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = bold
    ws.append([])
    table(ws, ["Mức", "Lỗi", "Số trang", "Cách sửa"],
          [[SA.LEVELS[c["level"]][0], c["name"], len(c["pages"]), c["fix"]] for c in au["checks"]],
          [30, 44, 10, 90], level_col=0)
    ws.freeze_panes = None

    # 3. Lỗi theo trang
    table(wb.create_sheet("Lỗi theo trang"),
          ["Mức", "Lỗi", "Trang", "URL", "Đang là", "Nên là", "Ghi chú", "Loại trang", "Cách sửa"],
          [[SA.LEVELS[c["level"]][0], c["name"], _path(p["url"], site) if p["url"].startswith("http") else p["url"],
            p["url"], p.get("now") or p.get("detail") or "", p.get("want") or "", p.get("extra") or "",
            p.get("type") or "", c["fix"]] for c in au["checks"] for p in c["pages"]],
          [12, 36, 40, 50, 46, 36, 30, 14, 70], level_col=0)

    # 4. Theo trang
    per: dict[str, dict] = {}
    for c in au["checks"]:
        if c.get("site"):
            continue
        for p in c["pages"]:
            d = per.setdefault(p["url"], {k: 0 for k in SA.LEVELS} | {"names": []})
            d[c["level"]] += 1
            d["names"].append(f"[{SA.LEVELS[c['level']][0]}] {c['name']}")
    rows = sorted(per.items(), key=lambda x: (-x[1]["high"], -x[1]["medium"], -x[1]["info"], x[0]))
    table(wb.create_sheet("Theo trang"),
          ["Trang", "URL", *[n for n, _ in SA.LEVELS.values()], "Các lỗi"],
          [[_path(u, site), u, *[d[k] for k in SA.LEVELS], "\n".join(d["names"])] for u, d in rows],
          [40, 50, 10, 10, 10, 70])

    # 5. Đã bỏ qua có chủ ý
    ign = [(c, p) for c in au["checks"] + (au.get("ignored_checks") or []) for p in c.get("ignored") or []]
    if ign:
        table(wb.create_sheet("Đã bỏ qua"), ["Lỗi", "URL", "Đang là"],
              [[c["name"], p["url"], p.get("now") or p.get("detail") or ""] for c, p in ign], [40, 60, 50])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
