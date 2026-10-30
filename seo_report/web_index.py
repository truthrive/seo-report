"""Màn Check index: dán URL (bài mới…) để kiểm tra ngay và theo dõi đến khi được index."""
from datetime import datetime, timezone

from . import indexing as IX


def _vn(iso: str | None) -> str:
    if not iso:
        return ""
    y, m, d = iso[:10].split("-")
    return f"{d}/{m}/{y}"


def build_index_page(ui, cfg, connect, user: str) -> None:
    from .access import can_edit
    site = cfg.site_url
    ed = can_edit(user)  # người chỉ xem: không thêm URL kiểm tra (dùng quota GSC), không bỏ theo dõi
    from . import ui_theme as T
    T.page_header(ui, "travel_explore", "Index", "Dán URL cần kiểm tra, ví dụ bài mới đăng. Tool kiểm tra ngay, rồi tự "
                  "kiểm tra lại sau 3, 7 và 14 ngày cho đến khi Google index. Tool chỉ kiểm tra, không gửi yêu cầu "
                  "index.", tone="blue")

    # ---- Tổng quan index: nhóm SEO chủ lực + toàn bộ URL đã kiểm tra ----
    from . import urls as U
    with connect() as c:
        gid = U.ensure_group(c, site)
        group_name = dict(U.list_groups(c, site))[gid]
        members = U.group_members(c, gid)
        latest = IX.latest(c, [m["id"] for m in members])
        coverage = IX.summary(c, site)
    ok = sum(1 for m in members if m["id"] in latest and latest[m["id"]]["indexed"])
    bad = sum(1 for m in members if m["id"] in latest and not latest[m["id"]]["indexed"])
    dropped = sum(1 for m in members if m["id"] in latest and latest[m["id"]]["dropped"])
    with T.kpi_row(ui):
        T.kpi(ui, "task_alt", f"Đã index · nhóm {group_name}", f"{ok}/{len(members)}", tone="green",
              hint=f"{len(members) - len(latest)} URL chưa kiểm tra" if len(latest) < len(members) else "")
        T.kpi(ui, "report", "Chưa index", str(bad), tone="red" if bad else "green",
              hint=f"{dropped} URL vừa rớt index" if dropped else "")
        T.kpi(ui, "inventory_2", "URL đã kiểm tra (toàn site)", f"{sum(n for _, n in coverage):,}".replace(",", "."),
              tone="blue", hint=" · ".join(f"{k or 'không rõ'}: {n:,}".replace(",", ".") for k, n in coverage[:2]))
        quota_card = T.kpi(ui, "speed", "Quota kiểm tra hôm nay", "…", tone="amber", hint="gồm cả lịch chạy tự động")

    if ed:
        with T.section(ui, "Kiểm tra URL mới", "add_link", "Mỗi dòng một URL. Kiểm tra ngay rồi theo dõi đến khi index"):
            paste = ui.textarea(placeholder="https://matkinhtamduc.com/bai-moi/\nhttps://matkinhtamduc.com/bai-moi-2/").props(
                "outlined autogrow").classes("w-full")
            with ui.row().classes("items-center gap-3"):
                check_btn = ui.button("Kiểm tra và theo dõi", icon="travel_explore", on_click=lambda: check()).props(
                    "unelevated no-caps")
                result = ui.label().classes("text-sm")

    with ui.row().classes("items-center gap-3 q-mt-md"):
        ui.label("Đang theo dõi").classes("sr-section-title")
        only_open = ui.switch("Chỉ hiện URL chưa index", value=False, on_change=lambda: refresh())
    table = ui.table(columns=[
        {"name": "url", "label": "URL", "field": "url", "align": "left", "sortable": True},
        {"name": "status", "label": "Trạng thái", "field": "status", "align": "left", "sortable": True},
        {"name": "crawl", "label": "Crawl gần nhất", "field": "crawl", "align": "left"},
        {"name": "sitemap", "label": "Có trong sitemap", "field": "sitemap", "align": "center", "sortable": True},
        {"name": "added", "label": "Ngày nhập", "field": "added", "align": "left", "sortable": True},
        {"name": "checks", "label": "Số lần kiểm tra", "field": "checks", "align": "right"},
        {"name": "gsc", "label": "GSC", "field": "gsc", "align": "center"},
    ], rows=[], row_key="url_id", selection="multiple" if ed else "none", pagination=50).classes("w-full").props(
        "flat bordered dense")
    table.add_slot("no-data", """
        <div class="full-width column items-center q-pa-lg" style="gap: 6px">
          <q-icon name="travel_explore" size="32px" color="grey-5" />
          <div class="text-body2">Chưa theo dõi URL nào</div>
          <div class="text-caption text-grey-7">Dán URL bài mới ở khung phía trên để bắt đầu theo dõi</div>
        </div>""")
    table.add_slot("body-cell-status", """
        <q-td :props="props">
          <q-badge :color="props.row.color" text-color="white" :label="props.value" />
        </q-td>""")
    table.add_slot("body-cell-gsc", """
        <q-td :props="props">
          <a :href="props.value" target="_blank" rel="noopener" aria-label="Mở URL này trong Search Console">
            <q-icon name="open_in_new" color="grey-7" /></a>
        </q-td>""")
    if ed:
        ui.button("Bỏ theo dõi các URL đã chọn", icon="visibility_off", on_click=lambda: unwatch()).props(
            "outline no-caps")
    ui.label("Trạng thái màu đỏ: quá 14 ngày vẫn chưa index. Nên kiểm tra URL có trong sitemap không, có link nội bộ "
             "trỏ tới không, rồi mở GSC để yêu cầu lập chỉ mục.").classes("text-xs muted")

    def refresh():
        with connect() as c:
            today = datetime.now(timezone.utc).date()
            used = IX.checked_today(c, today)
            rows = []
            for w in IX.watch_list(c, site):
                if only_open.value and w["indexed"]:
                    continue
                ix = w["check"]
                if w["indexed"]:
                    status, color = "Đã index", "green-8"
                elif w["overdue"]:
                    status, color = f"Chưa index sau {w['days']} ngày", "red-8"
                elif ix:
                    status, color = ix["coverage"] or ix["verdict"] or "Chưa index", "orange-8"
                else:
                    status, color = "Chờ kiểm tra", "grey-6"
                rows.append({"url_id": w["url_id"], "url": w["url"].replace(site.rstrip("/"), "") or "/",
                             "status": status, "color": color,
                             "crawl": _vn(ix["last_crawl"]) if ix and ix["last_crawl"] else "",
                             "sitemap": "Có" if w["in_sitemap"] else "Không", "added": _vn(w["added_at"]),
                             "checks": w["checks"], "gsc": IX.gsc_inspect_link(site, w["url"])})
        quota_card.clear()
        with quota_card:
            with ui.row().classes("items-center gap-2 no-wrap"):
                with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['amber'][0]}"):
                    ui.icon("speed", size="18px").style(f"color:{T.AMBER}")
                ui.label("Quota kiểm tra hôm nay").classes("text-sm muted")
            ui.label(f"{used:,} / {IX.DAILY_QUOTA:,}".replace(",", ".")).classes("sr-kpi-value num q-mt-sm")
            ui.linear_progress(min(used / IX.DAILY_QUOTA, 1), show_value=False, size="6px",
                               color="orange-8" if used > IX.DAILY_QUOTA * 0.8 else "primary").classes("q-mt-sm")
            ui.label("gồm cả lịch chạy tự động").classes("text-xs muted sr-kpi-hint")
        table.rows = rows
        table.selected = []

    async def check():
        from nicegui import run

        from . import auth

        if not (paste.value or "").strip():
            return
        with connect() as c:
            items, invalid = IX.add_watch(c, site, paste.value, user)
        check_btn.props("loading")
        try:
            creds = auth.get_credentials(cfg)

            def work():
                with connect() as c:
                    return IX.check_now(c, site, items, lambda: auth.build_service(creds))

            done, skipped = await run.io_bound(work)
        except (Exception, SystemExit) as e:  # SystemExit khi token hết hạn, lỗi mạng…
            ui.notify(f"Không kiểm tra được: {e}", type="negative", multi_line=True)
            done, skipped = 0, len(items)
        finally:
            check_btn.props(remove="loading")
        msg = [f"Đã kiểm tra {done} URL, đang theo dõi {len(items)} URL."]
        if skipped:
            msg.append(f"{skipped} URL chưa kiểm tra được vì hết quota hôm nay; lịch chạy sẽ kiểm tra sau.")
        if invalid:
            msg.append(f"Bỏ qua {len(invalid)} dòng không phải URL của {site}: {', '.join(invalid[:5])}")
        result.text = " ".join(msg)
        paste.value = ""
        refresh()

    def unwatch():
        if not table.selected:
            ui.notify("Tích chọn URL cần bỏ theo dõi", type="warning")
            return
        with connect() as c:
            IX.remove_watch(c, site, [r["url_id"] for r in table.selected], user)
        refresh()

    refresh()
