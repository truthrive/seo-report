"""Technical Audit (/audit, menu Website): checklist kỹ thuật SEO theo 10 hạng mục của bộ tiêu chuẩn "Technical
Search & GEO" (audit_checklist.py). Tool tự mở các URL trong nhóm URL SEO, mọi trang không phải sản phẩm trong
sitemap và các trang / sản phẩm nhiều traffic nhất (site_audit.pick_pages), kiểm tra từng trang và cả website
(site_checks.py). Tự quét mỗi tuần, miễn phí. Chỉ team.

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

TABS = (("loi", "Checklist"), ("trang", "Theo trang"), ("tuan", "Theo tuần"))
AREA_ICONS = {"overview": "dashboard", "access": "security", "index": "manage_search", "canon": "alt_route",
              "link": "link", "sitemap": "account_tree", "content": "title", "schema": "data_object",
              "perf": "speed", "media": "image", "ai": "auto_awesome"}
WEEKS = 8  # tab Theo tuần: số lần quét gần nhất hiện thành cột
RESULT = {"pass": ("Đạt", "green"), "fail": ("Còn lỗi", "red"), "unknown": ("Chưa kiểm được", "grey")}
HOW = ["Trang được quét: mọi URL trong nhóm URL SEO (Quản lý URL), kể cả trang mới chưa có click; {top} trang nhiều "
       "click nhất trên Search Console 90 ngày qua; {prod} trang sản phẩm nhiều click nhất; và mọi trang không phải sản "
       "phẩm trong sitemap (bài viết, danh mục, cửa hàng, trang thông tin). Trang sản phẩm dùng chung một giao diện "
       "nên quét mẫu là đủ thấy lỗi chung. Tối đa {n} trang, bỏ URL có tham số và URL cũ. Quét lại mỗi tuần, miễn "
       "phí; người có quyền sửa bấm “Quét ngay” để quét liền.",
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


def build_audit_page(ui, cfg, connect, user, start: str = "", area: str = "") -> None:
    from nicegui import background_tasks, run
    site = cfg.site_url
    with connect() as c:
        end = K.latest_date(c, site)
    right = T.page_header(ui, "fact_check", "Technical Audit",
                          "Checklist kỹ thuật SEO cho các trang quan trọng của website.")
    ed = A.can_edit(user)
    open_area = "schema" if start == "schema" else ""  # link cũ ?tab=schema: mở hạng mục Schema
    area_keys = [k for k, _ in AC.AREAS]
    state = {"tab": start if start in dict(TABS) else TABS[0][0], "au": None, "kit": TK.new_state(), "kits": {},
             "clicks": {}, "groups": {}, "sc": None, "diff": None, "prev_at": None, "only_bad": False,
             "exp": {}, "open": open_area, "sched": SA.DEFAULT_SCHEDULE, "hist": [], "fixlog": [],
             "area": open_area or (area if area in area_keys else "overview"), "wk_bad": False}
    key = str(cfg.db_path)

    def set_url() -> None:
        q = []
        if state["tab"] != TABS[0][0]:
            q.append(f"tab={state['tab']}")
        elif state["area"] != "overview":
            q.append(f"muc={state['area']}")
        ui.run_javascript(f"history.replaceState(null, '', '/audit{'?' + '&'.join(q) if q else ''}')")

    def pick(v: str) -> None:
        state["tab"] = v
        set_url()

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
                        ui.label(t.format(n=f"{SA.MAX_PAGES:,}".replace(",", "."), top=SA.TOP_TRAFFIC,
                                          prod=SA.TOP_PRODUCTS)).classes("text-sm")
        if key in SA.running:
            ui.button("Đang quét…", icon="travel_explore").props("unelevated no-caps loading disable").tooltip(
                "Xem tiến độ ngay dưới đầu trang")
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

    def sched_text(sch: dict) -> str:
        from datetime import datetime
        if sch.get("paused"):
            return "Tạm ngưng tự quét: chỉ quét khi bấm “Quét ngay”"
        nxt = SA.next_slot(sch, datetime.now().astimezone())
        return (f"Tự quét {SA.WEEKDAYS[sch['weekday']]} {sch['hour']:02d}:00 mỗi tuần · lần tới "
                f"{nxt:%d/%m} {sch['hour']:02d}:00")

    def schedule_dialog() -> None:
        """Lịch tự quét: thứ + giờ trong tuần (giờ của máy chạy tool), tạm ngưng."""
        sch = dict(state["sched"])
        with ui.dialog() as d, ui.card().style("width: 440px; max-width: 94vw; border-radius: 14px"):
            ui.label("Lịch quét Technical Audit").classes("text-base font-semibold")
            ui.label("Tool tự quét mỗi tuần một lần vào thứ và giờ chọn ở đây. Máy chạy tool tắt đúng lúc đó thì quét "
                     "bù khi máy bật lại. Nên chọn giờ website ít người vào (ban đêm).").classes("text-xs muted")
            pause = ui.switch("Tạm ngưng tự quét (chỉ quét khi bấm “Quét ngay”)", value=sch["paused"]).props("dense")
            with ui.row().classes("w-full gap-2 no-wrap"):
                wd = ui.select({i: n for i, n in enumerate(SA.WEEKDAYS)}, value=sch["weekday"], label="Thứ").props(
                    "outlined dense").classes("col")
                hr = ui.select({h: f"{h:02d}:00" for h in range(24)}, value=sch["hour"], label="Giờ").props(
                    "outlined dense").classes("col")
            note = ui.label().classes("text-sm q-mt-xs")

            def show(_=None):
                wd.set_enabled(not pause.value)
                hr.set_enabled(not pause.value)
                note.text = sched_text({"weekday": wd.value, "hour": hr.value, "paused": pause.value})
            for w in (pause, wd, hr):
                w.on_value_change(show)
            show()

            def save():
                with connect() as c:
                    state["sched"] = SA.save_schedule(c, wd.value, hr.value, pause.value, str(user))
                ui.notify("Đã lưu lịch quét", type="positive", position="bottom-right")
                d.close()
                body.refresh()
            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Lưu", on_click=save).props("unelevated no-caps color=primary")
        d.on("hide", d.delete)
        d.open()

    async def scan_now(btn) -> None:
        from contextlib import closing

        from . import db
        from . import notices as N
        if not ed or key in SA.running:
            return
        _pt = PT.take(ui, user, cfg, "audit")
        if _pt is False:
            return
        prog = SA.track(key, str(user))
        btn.props("loading")
        note = ui.notification("Đang quét các trang và kiểm tra cấp website (khoảng 20–30 phút, có thể rời trang, "
                               "quét xong sẽ có kết quả)…", spinner=True, timeout=None, type="ongoing", position="bottom-right")

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                from .cwv import load_key
                try:
                    key_ = load_key(cfg)
                except Exception:  # noqa: BLE001
                    key_ = ""
                return SA.run(c, site, end, str(user), progress=prog, log=lambda m: None, key=key_, cfg=cfg)
        actions.refresh()
        body.refresh()
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
                                                             else "")
                          + (f" · website chặn bot ở {r['blocked']} trang" if r.get("blocked") else "")
                          + (" · đã dừng sớm vì bị chặn liên tục" if r.get("stopped_early") else ""),
                          type="warning" if r.get("blocked") else "positive", position="bottom-right")
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
        dif = AC.diff(AC.snapshot(au), prev, set(au.get("scanned") or []), SA.prev_scanned(c, au) if prev else None)
        return {"au": au, "clicks": _clicks(c, au), "groups": SA.url_groups(c, site), "sc": SC.latest(c),
                "diff": dif, "prev_at": prev_at,
                "sched": SA.schedule(c), "hist": SA.history_list(c), "fixlog": SA.fix_log(c, limit=300),
                "stopped": SA.stopped(c)}

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

    async def recheck_rows(code: str, rows: list[dict]) -> None:
        await recheck_items([(code, r["url"]) for r in rows])

    async def recheck_items(items: list[tuple[str, str]]) -> None:
        """Người dùng báo đã xử lý: mở lại đúng các trang / URL đó, báo từng dòng Đạt / Còn lỗi, ghi nhật ký."""
        from contextlib import closing

        from . import db
        items = list(dict.fromkeys(items))
        cnames = {c: n for c, (_, n, _) in SA.CHECKS.items()}
        note = ui.notification(f"Đang kiểm lại {len(items)} dòng…", spinner=True, timeout=None, type="ongoing",
                               position="bottom-right")

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                return SA.recheck(c, cfg, items, str(user))
        try:
            res = await run.io_bound(work)
        except Exception as ex:  # noqa: BLE001
            note.dismiss()
            ui.notify(f"Chưa kiểm lại được: {ex}", type="warning", position="bottom-right")
            return
        note.dismiss()
        n = {k: sum(1 for r in res if r["result"] == k) for k in RESULT}
        with ui.dialog() as d, ui.card().style("width: 760px; max-width: 96vw; border-radius: 14px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label("Kết quả kiểm lại").classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
            ui.label(f"{n['pass']} đạt · {n['fail']} còn lỗi · {n['unknown']} chưa kiểm được. Đã ghi vào nhật ký xác "
                     "nhận của tiêu chí.").classes("text-sm")
            rows_ = [{"id": f"{r['code']}|{r['url']}", "url": _path(r["url"], site) if r["url"].startswith("http")
                      else r["url"], "res": RESULT[r["result"]][0], "tone": r["result"], "now": r["now"],
                      "name": cnames.get(r["code"], r["code"])} for r in res]
            many = len({r["code"] for r in res}) > 1
            tb = ui.table(columns=[
                {"name": "url", "label": "Trang / URL", "field": "url", "align": "left"},
                *([{"name": "name", "label": "Mục", "field": "name", "align": "left"}] if many else []),
                {"name": "res", "label": "Kết quả", "field": "res", "align": "left"},
                {"name": "now", "label": "Đang là", "field": "now", "align": "left"},
            ], rows=rows_, row_key="id", pagination=10).props("flat dense").classes("w-full sr-bl-table")
            tb.add_slot("body-cell-res", """
                <q-td :props="props"><span class="sr-status" :style="{background: {pass: '#E7F3EA', fail: '#FCEDE6',
                  unknown: '#F1F0EA'}[props.row.tone], color: {pass: '#1E7C31', fail: '#C2410C',
                  unknown: '#6B6A5E'}[props.row.tone]}">{{ props.value }}</span></q-td>""")
        d.on("hide", d.delete)
        d.open()
        await reload()

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
        if ed and not ignored:
            acts.append({"label": "Đã xử lý, kiểm tra lại", "icon": "task_alt",
                         "on": lambda sel, code=ch["code"]: recheck_rows(code, sel)})
        if ed:
            acts.append({"label": "Tính lại là lỗi" if ignored else
                         "Cố ý, bỏ qua", "icon": "undo" if ignored else "block",
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

    def fixes_block(row: dict) -> None:
        log = [x for x in state["fixlog"] if x["code"] in row["codes"]]
        if not log:
            return
        n_ok = sum(1 for x in log if x["result"] == "pass")
        with ui.expansion(f"Đã xác nhận xử lý · {len(log)} lần kiểm lại ({n_ok} đạt)").props("dense").classes(
                "w-full sr-au-fold q-mt-xs"):
            from datetime import datetime
            rows_ = [{"id": i, "at": f"{datetime.fromisoformat(x['at']).astimezone():%H:%M %d/%m}",
                      "url": _path(x["url"], site) if x["url"].startswith("http") else x["url"],
                      "res": RESULT[x["result"]][0], "by": x["by"], "now": x["detail"]} for i, x in enumerate(log)]
            ui.table(columns=[
                {"name": "at", "label": "Lúc", "field": "at", "align": "left"},
                {"name": "url", "label": "Trang / URL", "field": "url", "align": "left"},
                {"name": "res", "label": "Kết quả", "field": "res", "align": "left"},
                {"name": "now", "label": "Đang là", "field": "now", "align": "left"},
                {"name": "by", "label": "Người xác nhận", "field": "by", "align": "left"},
            ], rows=rows_, row_key="id", pagination=10).props("flat dense").classes("w-full sr-bl-table")

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
            fixes_block(row)
            if row["code"]:
                ui.label(f"Mã quy tắc: {row['code']}").classes("text-xs muted q-mt-xs").props(
                    'title="Mã trong bộ tiêu chuẩn Technical SEO, để tra cứu"')
        for ch in row["checks"]:
            state["exp"][ch["code"]] = (ex, f"crit-{idx}")
        for code in row["codes"]:
            state["exp"].setdefault(code, (ex, f"crit-{idx}"))

    def go_check(code: str) -> None:
        """Từ "Việc làm trước" / "Thay đổi": chuyển sang hạng mục của mục đó, mở đúng tiêu chí và cuộn tới."""
        area_of = {c: a for a, _, _, codes, _ in AC.CRITERIA for c in codes}
        if area_of.get(code) and state["area"] != area_of[code]:
            go_area(area_of[code])
        hit = state["exp"].get(code)
        if hit:
            hit[0].set_value(True)
            T.scroll_to(ui, hit[1])

    def go_area(key_: str) -> None:
        state["area"] = key_
        set_url()
        checklist_view.refresh()
        ui.run_javascript("setTimeout(() => {const l = document.querySelector('.sr-ta-layout');"
                          " if (l && l.getBoundingClientRect().top < 64) l.scrollIntoView({block: 'start'});}, 30)")

    # ------------------------------------------------------------ tab Checklist
    def summary(areas: list[dict], au: dict) -> None:
        tot = AC.totals(areas)
        dif = state["diff"] or {}
        tiles = [(tot["high"], "tiêu chí cần sửa", "red", "error"),
                 (tot["medium"], "tiêu chí nên sửa", "amber", "warning"),
                 (tot["ok"], f"đạt / {tot['checked']} đã kiểm", "green", "check_circle"),
                 (tot["unknown"], "chưa kiểm", "grey", "help_outline")]
        with ui.element("div").classes("sr-ta-sum w-full"):
            for num, lab, tone, icon in tiles:
                with ui.element("div").classes(f"sr-ta-tile {tone}" + ("" if num else " zero")):
                    with ui.element("div").classes("sr-ta-tile-ic"):
                        ui.icon(icon, size="20px").props('aria-hidden="true"')
                    with ui.column().classes("gap-0"):
                        ui.label(f"{num}").classes("sr-ta-tile-num")
                        ui.label(lab).classes("text-sm muted")
        if not dif.get("has_prev"):
            ui.label("Chưa có lần quét trước để so sánh: từ lần quét sau, tool báo lỗi mới / lỗi đã hết ở đây.").classes(
                "text-xs muted q-mt-sm")
        elif not (dif["new"] or dif["fixed"] or dif.get("first")):
            ui.label(f"Không có lỗi mới hay lỗi đã hết so với lần quét {_vn_day(state['prev_at'])}.").classes(
                "text-xs muted q-mt-sm")

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
        first = dif.get("first") or []
        if not dif.get("has_prev") or not (dif["new"] or dif["fixed"] or first):
            return
        names = {c: n for c, (_, n, _) in SA.CHECKS.items()}
        n_ = lambda v: f"{v:,}".replace(",", ".")  # noqa: E731
        head = (f"So với lần quét {_vn_day(state['prev_at'])}: {n_(len(dif['new']))} dòng lỗi mới · "
                f"{n_(len(dif['fixed']))} đã hết")
        if first:
            head += f" · {n_(dif['first_pages'])} trang lần đầu được quét ({n_(len(first))} dòng lỗi)"
        with ui.expansion(head).props("dense").classes("w-full sr-au-fold"):
            ui.label("Đếm theo dòng: mỗi dòng là một trang × một vấn đề (ô số phía trên đếm theo tiêu chí). Lỗi ở trang "
                     "lần đầu được quét không tính là lỗi mới vì lần trước chưa xem trang đó.").classes(
                "text-xs muted")
            for title, items, tone in (("Lỗi mới (trang đã quét lần trước)", dif["new"], "red"),
                                       ("Đã hết (trang vẫn được quét)", dif["fixed"], "green"),
                                       ("Ở trang lần đầu được quét", first, "grey")):
                if not items:
                    continue
                ui.label(f"{title} · {len(items)}").classes("text-xs muted q-mt-xs")
                rows = [{"id": f"{c}|{u}", "name": names.get(c, c), "url": _path(u, site) if u.startswith("http")
                         else u} for c, u in items[:200]]
                ui.table(columns=[{"name": "name", "label": "Mục", "field": "name", "align": "left"},
                                  {"name": "url", "label": "Trang / URL", "field": "url", "align": "left"}],
                         rows=rows, row_key="id", pagination=10).props("flat dense").classes("w-full sr-bl-table")

    def area_status(cnt: dict) -> None:
        """Chỉ số, không chữ: số đỏ = tiêu chí cần sửa, số vàng = nên sửa, ✓ = đạt hết (chữ đầy đủ ở tooltip)."""
        with ui.row().classes("sr-ta-cnt items-center gap-1 no-wrap"):
            for k in ("high", "medium"):
                if cnt.get(k):
                    t = f"{cnt[k]} tiêu chí {AC.LABEL[k][0].lower()}"
                    ui.html(f'<span aria-hidden="true">{cnt[k]}</span><span class="sr-only">{t}</span>').classes(
                        f"sr-ta-n-{k}").props(f'title="{t}"')
            if not cnt.get("high") and not cnt.get("medium") and cnt.get("ok") and not cnt.get("info")                     and not cnt.get("unknown"):
                ui.icon("check", size="16px").classes("sr-ta-n-ok").props('aria-label="Đạt hết" title="Đạt hết"')

    def area_view(a: dict, i: int) -> None:
        rows = [r for r in a["rows"] if not state["only_bad"] or r["status"] not in ("ok", "na")]
        cnt = a["counts"]
        with ui.row().classes("w-full items-center gap-2 sr-ta-area-h"):
            ui.icon(AREA_ICONS.get(a["key"], "folder"), size="20px").classes("sr-ta-area-ic").props(
                'aria-hidden="true"')
            ui.label(a["name"]).classes("sr-ta-area-name")
            area_status(cnt)
            ui.space()
            ui.toggle({False: "Tất cả", True: "Chưa đạt"}, value=state["only_bad"],
                      on_change=lambda e: (state.update(only_bad=e.value), checklist_view.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
        if not rows:
            ui.label("Mọi tiêu chí của hạng mục này đã đạt.").classes("text-sm muted q-mt-sm")
        for j, r in enumerate(rows):
            criterion(r, f"{a['key']}-{j}")
        if a["key"] == "schema":
            with ui.expansion("Kết quả nổi bật trên Google và theo dõi schema qua các lần quét").props(
                    "dense").classes("w-full sr-ta-crit"):
                schema_detail()

    def overview(areas: list[dict], au: dict) -> None:
        summary(areas, au)
        changes(au)
        todo(au)

    @ui.refreshable
    def checklist_view() -> None:
        """Cột trái: Tổng quan + 10 hạng mục (màn hẹp: thanh trượt ngang); bên phải: nội dung mục đang chọn."""
        au = state["au"]
        areas = AC.build(au, state["sc"], au.get("meta") or {})
        state["exp"] = {}
        with ui.element("div").classes("sr-ta-layout"):
            with ui.element("nav").classes("sr-ta-nav").props('aria-label="Hạng mục checklist"'):
                items = [("overview", "Tổng quan", None)] + [(a["key"], a["name"], a) for a in areas]
                for k, name, a in items:
                    on = state["area"] == k
                    b = ui.element("button").classes("sr-ta-nav-item" + (" on" if on else "")).props(
                        f'type="button" aria-current="{"true" if on else "false"}"')
                    b.on("click", lambda _, k=k: go_area(k))
                    with b:
                        ui.icon(AREA_ICONS.get(k, "folder"), size="18px").classes("sr-ta-nav-ic").props(
                            'aria-hidden="true"')
                        ui.label(name).classes("sr-ta-nav-name")
                        if a:
                            area_status(a["counts"])
            with ui.element("div").classes("sr-ta-main"):
                ui.run_javascript(  # màn hẹp: cuộn thanh hạng mục tới mục đang chọn
                    "setTimeout(() => {const n = document.querySelector('.sr-ta-nav'), o = n && n.querySelector('.on');"
                    " if (o && n.scrollWidth > n.clientWidth) n.scrollLeft = o.offsetLeft - (n.clientWidth - "
                    "o.offsetWidth) / 2;}, 50)")
                if state["area"] == "overview":
                    overview(areas, au)
                else:
                    i, a = next((i, a) for i, a in enumerate(areas, 1) if a["key"] == state["area"])
                    area_view(a, i)

    def checklist_tab(au: dict) -> None:
        if not au["pages"]:
            T.empty_state(ui, "fact_check", "Chưa có kết quả audit",
                          "Bấm “Quét ngay” ở đầu trang (người có quyền sửa) hoặc chờ lịch quét hằng tuần.")
            return
        checklist_view()

    # ------------------------------------------------------------ tab Theo tuần
    @ui.refreshable
    def weekly_view() -> None:
        from datetime import datetime
        hist = state["hist"]
        if not hist:
            T.empty_state(ui, "date_range", "Chưa có kết quả theo tuần",
                          "Mỗi lần quét xong, tool ghi lại kết quả để xem và so qua các tuần.")
            return
        names = {c: (n, lv) for c, (lv, n, _) in SA.CHECKS.items()}
        cols_h = hist[:WEEKS]
        area_name = dict(AC.AREAS)

        def cell(h: dict, crit: tuple) -> dict:
            area, code, name, codes, _ = crit
            st = (h.get("status") or {}).get(name)
            if st:
                return {"s": st[0], "n": st[1] if st[0] in ("high", "medium", "info") else 0}
            bad = [(c, h["codes"].get(c) or []) for c in codes if h["codes"].get(c)]
            if not bad:  # lần quét cũ chỉ ghi lỗi: không có lỗi chưa chắc là đạt
                return {"s": "na" if not h.get("totals") else "ok", "n": 0}
            lv = min((names.get(c, (c, "info"))[1] for c, _ in bad), key=lambda x: SA._ORDER[x])
            return {"s": lv, "n": sum(len(u) for _, u in bad)}

        rows_m = []
        for crit in AC.CRITERIA:
            cells = [cell(h, crit) for h in cols_h]
            if state["wk_bad"] and all(c_["s"] in ("ok", "na") for c_ in cells):
                continue
            rows_m.append({"id": crit[2], "area": area_name.get(crit[0], crit[0]), "name": crit[2],
                           **{f"w{i}": c_ for i, c_ in enumerate(cells)}})
        def tot(h: dict) -> str:
            if h.get("status"):
                sts = [v[0] for v in h["status"].values()]
                return f"{sts.count('high')} cần sửa · {sts.count('medium')} nên sửa"
            if h.get("totals"):
                return f"{h['totals'].get('high', '–')} cần sửa · {h['totals'].get('medium', '–')} nên sửa"
            return f"{sum(1 for v in h['codes'].values() if v)} mục có lỗi"
        tot_row = {"id": "_tot", "area": "", "name": "Tổng số tiêu chí",
                   **{f"w{i}": {"s": "tot", "t": tot(h)} for i, h in enumerate(cols_h)}}
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            ui.label("Mỗi dòng một tiêu chí, mỗi cột một lần quét (mới nhất bên trái). Ô ghi trạng thái và số trang / "
                     "URL lỗi của lần quét đó; “–” là lần quét cũ chưa ghi trạng thái đạt.").classes(
                "text-sm muted col")
            ui.toggle({False: "Tất cả tiêu chí", True: "Từng chưa đạt"}, value=state["wk_bad"],
                      on_change=lambda e: (state.update(wk_bad=e.value), weekly_view.refresh())).props(
                "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes(
                "sr-seg")
        cols = [{"name": "name", "label": "Tiêu chí", "field": "name", "align": "left", "classes": "sr-ta-wname",
                 "headerClasses": "sr-ta-wname"}]
        for i, h in enumerate(cols_h):
            at = datetime.fromisoformat(h["at"]).astimezone()
            cols.append({"name": f"w{i}", "label": f"{at:%d/%m}" + (" (mới nhất)" if i == 0 else ""),
                         "field": f"w{i}", "align": "left"})
        tb = ui.table(columns=cols, rows=[tot_row] + rows_m, row_key="id", pagination=0).props(
            "flat dense hide-bottom").classes("w-full sr-bl-table sr-ta-week")
        tb.add_slot("body-cell-name", """
            <q-td :props="props"><div :class="props.row.id === '_tot' ? 'font-semibold' : ''">{{ props.value }}</div>
              <div v-if="props.row.area" class="text-xs muted">{{ props.row.area }}</div></q-td>""")
        tb.add_slot("body-cell", """
            <q-td :props="props">
              <span v-if="props.value && props.value.s === 'tot'" class="text-sm num">{{ props.value.t }}</span>
              <span v-else-if="props.value && props.value.s !== 'na'" class="sr-status" :style="{
                background: {high: '#FCEDE6', medium: '#FBF1DE', info: '#E8EFFD', ok: '#E7F3EA', unknown: '#F1F0EA'}[props.value.s],
                color: {high: '#C2410C', medium: '#8F5F14', info: '#1D4ED8', ok: '#1E7C31', unknown: '#6B6A5E'}[props.value.s]}">
                {{ {high: 'Cần sửa', medium: 'Nên sửa', info: 'Tham khảo', ok: 'Đạt', unknown: 'Chưa kiểm'}[props.value.s] }}
                <template v-if="props.value.n"> · {{ props.value.n.toLocaleString('vi-VN') }}</template></span>
              <span v-else class="muted">–</span></q-td>""")
        with ui.expansion("Chi tiết lỗi từng lần quét").props("dense").classes("w-full sr-au-fold q-mt-md"):
            for h in hist:
                weekly_run(h, names)

    def weekly_run(h: dict, names: dict) -> None:
        from datetime import datetime
        if True:
            t = h["totals"] or {}
            at = datetime.fromisoformat(h["at"]).astimezone()
            nums = (f"{h['pages']} trang · {t.get('ok', '–')} đạt · {t.get('high', '–')} cần sửa · "
                    f"{t.get('medium', '–')} nên sửa" if t else f"{sum(len(v) for v in h['codes'].values())} dòng lỗi")
            diff_ = (f" · +{h['new']} dòng lỗi mới / −{h['fixed']} đã hết" if h["new"] is not None else "")
            if h.get("first"):
                diff_ += f" · {h['first']} dòng ở trang lần đầu quét"
            with ui.expansion(f"{at:%d/%m/%Y %H:%M} · {nums}{diff_}").props("dense").classes("w-full sr-ta-crit"):
                rows_ = sorted(({"id": c, "name": names.get(c, (c, "info"))[0],
                                 "lv": SA.LEVELS[names.get(c, (c, "info"))[1]][0],
                                 "rank": SA._ORDER[names.get(c, (c, "info"))[1]], "n": len(urls),
                                 "urls": ", ".join(_path(u, site) if u.startswith("http") else u for u in urls[:5])
                                 + (" …" if len(urls) > 5 else "")} for c, urls in h["codes"].items() if urls),
                               key=lambda r: (r["rank"], -r["n"]))
                ui.table(columns=[
                    {"name": "lv", "label": "Mức", "field": "lv", "align": "left"},
                    {"name": "name", "label": "Mục", "field": "name", "align": "left"},
                    {"name": "n", "label": "Số trang / URL", "field": "n", "align": "right"},
                    {"name": "urls", "label": "Ví dụ", "field": "urls", "align": "left"},
                ], rows=rows_, row_key="id", pagination=15).props("flat dense").classes("w-full sr-bl-table")

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
                d.setdefault("codes", []).append(c["code"])
                if c["name"] not in d["names"]:
                    d["names"].append(c["name"])
        clicks, groups = state["clicks"], state["groups"]
        rows = [{"url": u, "path": _path(u, site), **{k: d[k] for k in SA.LEVELS},
                 "total": sum(d[k] for k in SA.LEVELS), "names": " · ".join(d["names"]), "names_l": d["names"],
                 "clicks": (clicks.get(d["uid"]) or (0, 0))[0], "grp": ", ".join(groups.get(d["uid"]) or []),
                 "grp_l": groups.get(d["uid"]) or [NOGRP], "type": d["type"], "codes": d.get("codes") or []}
                for u, d in per.items()]
        has_grp = any(r["grp"] for r in rows)
        # lỗi nặng trước; cùng mức thì trang nhiều click trước (sửa trang mang traffic trước)
        rows.sort(key=lambda r: (-r["high"], -r["medium"], -r["clicks"], -r["info"], r["path"]))
        ui.label(f"{len(rows)} / {au['pages']} trang có ít nhất một mục cần xem (trang không có mục nào không nằm "
                 "trong bảng). Xếp lỗi nặng trước, cùng mức thì trang nhiều click trước.").classes("text-sm muted q-mb-sm")
        names = {k: n for k, (n, _) in SA.LEVELS.items()}
        cols = [{"name": "path", "label": "Trang", "field": "path", "align": "left", "sortable": True,
                 "classes": "sr-ta-pcol", "headerClasses": "sr-ta-pcol"},
                *([{"name": "grp", "label": "Nhóm URL", "field": "grp", "align": "left", "sortable": True,
                    "width": 140}] if has_grp else []),
                {"name": "type", "label": "Loại trang", "field": "type", "align": "left", "sortable": True,
                 "width": 120},
                {"name": "clicks", "label": "Click 28 ngày", "field": "clicks", "align": "right", "sortable": True,
                 "width": 120, ":format": "v => v.toLocaleString('vi-VN')"},
                *[{"name": k, "label": names[k], "field": k, "align": "right", "sortable": True, "width": 92}
                  for k in SA.LEVELS],
                {"name": "names", "label": "Các lỗi", "field": "names", "align": "left",
                 "classes": "sr-ta-ncol", "headerClasses": "sr-ta-ncol"}]
        acts = [{"label": "Đã xử lý, kiểm tra lại", "icon": "task_alt",
                 "on": lambda sel: recheck_items([(c_, r["url"]) for r in sel for c_ in r["codes"]])}] if ed else None
        TK.table(ui, columns=cols, rows=rows, row_key="url", st=state["kit"], noun="trang", page_size=25,
                 filters=[("text", "Trang", ["path"]), ("num", "Click 28 ngày", "clicks"),
                          *[("num", names[k], k) for k in SA.LEVELS], ("enum", "Lỗi", "names_l"),
                          ("enum", "Loại trang", "type"), *([("enum", "Nhóm URL", "grp_l")] if has_grp else [])],
                 copy=[("Trang", "url"), ("Nhóm URL", "grp"), ("Loại trang", "type"), ("Click 28 ngày", "clicks"),
                       *[(names[k], k) for k in SA.LEVELS], ("Các lỗi", "names")],
                 export="audit-theo-trang", actions=acts, classes="sr-ta-pages",
                 slots={"body-cell-path": """
                    <q-td :props="props"><a :href="props.row.url" target="_blank" rel="noopener"
                      class="sr-bl-link sr-ta-purl" :title="props.row.url">{{ props.value }}</a></q-td>""",
                        "body-cell-names": """
                    <q-td :props="props"><div class="sr-op-detail">{{ props.value }}</div></q-td>"""})

    # ------------------------------------------------------------ khung tiến độ khi đang quét
    def scan_card() -> None:
        """Đang quét gì, tới đâu, còn bao lâu: các bước (xong / đang chạy / chờ), thanh tiến độ của bước đang chạy,
        trang đang mở, thời gian còn lại ước tính. Tự cập nhật mỗi 2 giây; xong thì mời xem kết quả."""
        from datetime import datetime
        import time
        steps = SA.STEPS
        order = [k for k, _, _ in steps]
        with ui.element("div").classes("sr-ta-scan w-full q-mb-md").props('role="status" aria-live="polite"'):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                spin = ui.spinner(size="18px", color="green-8")
                title = ui.label().classes("text-sm font-semibold col")
                total_l = ui.label().classes("text-xs muted")
            rows = {}
            with ui.element("div").classes("sr-ta-steps"):
                for k, name, _ in steps:
                    with ui.element("div").classes("sr-ta-step") as el:
                        ic = ui.icon("radio_button_unchecked", size="18px").props('aria-hidden="true"')
                        with ui.column().classes("gap-0 col").style("min-width:0"):
                            ui.label(name).classes("sr-ta-step-name")
                            det = ui.label().classes("text-xs muted sr-ta-step-det")
                            bar = ui.linear_progress(value=0, show_value=False, size="6px", color="green-8").props(
                                "rounded track-color=grey-3").classes("q-mt-xs")
                    rows[k] = (el, ic, det, bar)
            done_box = ui.row().classes("w-full items-center gap-2 q-mt-sm")
            done_box.set_visibility(False)
            with done_box:
                ui.label("Đã quét xong.").classes("text-sm font-semibold")
                ui.button("Xem kết quả", icon="refresh", on_click=lambda: reload()).props(
                    "unelevated no-caps dense color=primary")

        def mins(sec: int) -> str:
            return "dưới 1 phút" if sec < 60 else f"khoảng {round(sec / 60)} phút"

        def tick():
            r = SA.running.get(key)
            if not r:
                spin.set_visibility(False)
                title.text = "Lần quét đã xong"
                total_l.text = ""
                for el, ic, det, bar in rows.values():
                    el.classes(replace="sr-ta-step done")
                    ic.name = "check_circle"
                    det.text, bar.visible = "", False
                done_box.set_visibility(True)
                timer.deactivate()
                return
            cur = order.index(r["phase"]) if r["phase"] in order else 0
            t0 = datetime.fromtimestamp(r["t0"]).astimezone()
            title.text = f"Đang quét · bắt đầu {t0:%H:%M}" + (f" · {r['by']}" if r.get("by") else "")
            total_l.text = f"đã chạy {mins(int(time.time() - r['t0'])).replace('khoảng ', '')}"
            for i, (k, _, unit) in enumerate(steps):
                el, ic, det, bar = rows[k]
                if i < cur:
                    el.classes(replace="sr-ta-step done")
                    ic.name = "check_circle"
                    det.text, bar.visible = "", False
                elif i > cur:
                    el.classes(replace="sr-ta-step")
                    ic.name = "radio_button_unchecked"
                    det.text = "chờ"
                    bar.visible = False
                else:
                    el.classes(replace="sr-ta-step on")
                    ic.name = "autorenew"
                    if r["total"]:
                        left = SA.eta(r)
                        det.text = (f"{r['n']:,}/{r['total']:,} {unit}".replace(",", ".")
                                    + (f" · còn {mins(left)}" if left is not None else " · đang ước thời gian…")
                                    + (f" · {_path(r['url'], site)}" if k == "pages" and r.get("url") else ""))
                        bar.value = r["n"] / r["total"]
                        bar.visible = True
                    else:
                        det.text = "đang chạy…"
                        bar.visible = False
        timer = ui.timer(2, tick)
        tick()

    # ------------------------------------------------------------ thân trang
    @ui.refreshable
    def body() -> None:
        au = state["au"]
        if au is None:
            with ui.element("div").classes("w-full sr-busy").props('aria-busy="true" aria-label="Đang tải"'):
                T.bone(ui, "420px", radius="14px")
            return
        last = au["run"]
        from datetime import datetime
        sch = state["sched"]
        paused = sch.get("paused")
        with ui.element("div").classes("sr-ta-meta w-full q-mb-md"):
            with ui.element("div").classes("sr-ta-meta-item"):  # lần quét gần nhất
                ui.icon("history", size="18px").props('aria-hidden="true"')
                ui.label("Quét gần nhất").classes("sr-ta-meta-k")
                if last and last["finished_at"]:
                    at = datetime.fromisoformat(last["finished_at"]).astimezone()
                    v = ui.label(f"{at:%H:%M %d/%m} · {last['pages']:,} trang".replace(",", ".")).classes(
                        "sr-ta-meta-v")
                    if last["errors"]:
                        v.props(f'title="{last["errors"]} trang không mở được"')
                else:
                    ui.label("chưa có").classes("sr-ta-meta-v")
            el = ui.element("button" if ed else "div").classes("sr-ta-meta-item" + (" edit" if ed else ""))
            nxt = SA.next_slot(sch, datetime.now().astimezone())
            el.props(f'title="{"Tạm ngưng: chỉ quét khi bấm Quét ngay" if paused else f"Lần tới {nxt:%d/%m} {sch["hour"]:02d}:00"}'
                     + ('. Bấm để đổi lịch" type="button"' if ed else '"'))
            if ed:
                el.on("click", lambda: schedule_dialog())
            with el:
                ui.icon("pause_circle" if paused else "event_repeat", size="18px").props('aria-hidden="true"')
                ui.label("Tự quét").classes("sr-ta-meta-k")
                ui.label("Tạm ngưng" if paused else f"{SA.WEEKDAYS[sch['weekday']]} {sch['hour']:02d}:00").classes(
                    "sr-ta-meta-v")
                if ed:
                    ui.icon("edit", size="15px").classes("sr-ta-meta-ed").props('aria-hidden="true"')
        if key in SA.running:
            scan_card()
        stop = state.get("stopped")
        if stop and key not in SA.running:
            from datetime import datetime
            st_at = datetime.fromisoformat(stop["started_at"]).astimezone()
            with ui.element("div").classes("sr-ta-stop w-full q-mb-sm").props('role="status"'):
                ui.icon("report", size="20px").props('aria-hidden="true"')
                with ui.column().classes("gap-0 col"):
                    ui.label(f"Lần quét lúc {st_at:%H:%M %d/%m} bị dừng giữa chừng (đã quét {stop['pages_done']} "
                             "trang)").classes("text-sm font-semibold")
                    ui.label("Kết quả bên dưới là của lần quét xong gần nhất, cộng số liệu mới của các trang vừa quét "
                             "được. " + ("Tool tự quét bù trong vòng 15 phút." if not paused else
                                         "Bấm “Quét ngay” để quét lại.")).classes("text-xs")
        n_blk = sum(len(c["pages"]) for c in au["checks"] if c["code"] == "blocked")
        if n_blk and key not in SA.running:
            with ui.element("div").classes("sr-ta-stop w-full q-mb-sm").props('role="status"'):
                ui.icon("shield", size="20px").props('aria-hidden="true"')
                with ui.column().classes("gap-0 col"):
                    ui.label(f"Website đang chặn bot của tool ở {n_blk} trang").classes("text-sm font-semibold")
                    ui.label("Các trang này chưa kiểm được (không tính là lỗi 4xx / 5xx). Nhờ dev cho phép User-Agent "
                             "“SEOReportBot” trong tường lửa / Cloudflare rồi quét lại. Danh sách ở Checklist › Truy "
                             "cập và robots.").classes("text-xs")
        n_fix = AC.totals(AC.build(au, state["sc"], au.get("meta") or {}))["high"] if au["pages"] else 0
        with ui.tabs(value=state["tab"], on_change=lambda e: pick(e.value)).props(
                "align=left no-caps dense mobile-arrows outside-arrows").classes("w-full sr-tabs sr-bl-tabs") as tabs:
            for k, name in TABS:
                with ui.tab(k, name):
                    if k == "loi" and n_fix:
                        T.count_badge(ui, n_fix, f"{n_fix} tiêu chí cần sửa").classes("sr-tab-badge")
        with ui.tab_panels(tabs, value=state["tab"]).classes("w-full").props("animated=false"):
            with ui.tab_panel("loi").classes("q-px-none"):
                with ui.element("div").classes("sr-card sr-op-panel w-full"):
                    checklist_tab(au)
            with ui.tab_panel("trang").classes("q-px-none"):
                pages_tab(au)
            with ui.tab_panel("tuan").classes("q-px-none"):
                with ui.element("div").classes("sr-card sr-op-panel w-full"):
                    weekly_view()

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


async def schedule_loop(base) -> None:
    """Tự quét Technical Audit theo lịch (thứ + giờ) của từng dự án: xem mỗi 15 phút, tới lịch thì quét (chạy nền,
    một dự án một lúc). Lịch hằng ngày (cli) cũng gọi site_audit.refresh: lần nào tới trước thì quét."""
    import asyncio
    import traceback
    from contextlib import closing

    from nicegui import run

    from . import db
    from . import projects as PJ
    await asyncio.sleep(90)  # để máy chủ khởi động xong
    while True:
        try:
            with closing(db.connect(base.db_path)) as c:
                projects = PJ.list_projects(c)
            for p in projects:
                cfg = PJ.config_for(base, p)
                key = str(cfg.db_path)
                if key in SA.running:
                    continue

                def due(cfg=cfg):
                    with closing(db.connect(cfg.db_path)) as c:
                        return SA.due(c)
                if not await run.io_bound(due):
                    continue
                prog = SA.track(key, "lịch tự động")

                def work(cfg=cfg, prog=prog):
                    with closing(db.connect(cfg.db_path)) as c:
                        return SA.refresh(c, cfg, log=lambda m: None, progress=prog)
                try:
                    await run.io_bound(work)
                finally:
                    SA.running.pop(key, None)
        except Exception:  # noqa: BLE001  (lượt sau thử lại)
            traceback.print_exc()
        await asyncio.sleep(15 * 60)


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
