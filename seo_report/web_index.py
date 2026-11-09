"""Màn Check index: dán URL (bài mới…) để kiểm tra ngay và theo dõi đến khi được index."""
from datetime import datetime, timezone

from . import indexing as IX
from .projects import domain


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
    T.page_header(ui, "travel_explore", "Index", "Tình trạng Google index của toàn site, URL chưa index theo lý do, và "
                  "theo dõi bài mới đến khi được index. Tool chỉ kiểm tra, không gửi yêu cầu index.", tone="blue")

    # ---- Tổng quan index: nhóm SEO chủ lực + toàn bộ URL đã kiểm tra ----
    from . import urls as U
    with connect() as c:
        gid = U.ensure_group(c, site)
        group_name = dict(U.list_groups(c, site))[gid]
        members = U.group_members(c, gid)
        latest = IX.latest(c, [m["id"] for m in members])
        coverage = IX.summary(c, site)
        missing = IX.not_indexed(c, site)
    fmt = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
    checked = sum(n for _, n in coverage)
    to_fix = [x for x in missing if not x["intentional"]]
    on_purpose = [x for x in missing if x["intentional"]]
    ok = sum(1 for m in members if m["id"] in latest and latest[m["id"]]["indexed"])
    dropped = sum(1 for m in members if m["id"] in latest and latest[m["id"]]["dropped"])
    with T.kpi_row(ui):  # cùng cách đếm với khối Index ở Tổng quan: lần kiểm tra gần nhất của mỗi URL
        T.kpi(ui, "task_alt", "Đã index · toàn site", f"{fmt(checked - len(missing))}/{fmt(checked)}", tone="green",
              hint=(f"{(checked - len(missing)) / checked * 100:.1f}% URL đã kiểm tra".replace(".", ",")
                    if checked else "chưa kiểm tra URL nào"))
        reasons = {}
        for x in to_fix:
            reasons[x["coverage"]] = reasons.get(x["coverage"], 0) + 1
        top = max(reasons.items(), key=lambda kv: kv[1]) if reasons else None
        T.kpi(ui, "report", "Chưa index · cần xem", fmt(len(to_fix)), tone="red" if to_fix else "green",
              hint=(f"nhiều nhất: {top[0]} ({fmt(top[1])}) · {fmt(len(on_purpose))} URL loại trừ có chủ ý"
                    if top else f"{fmt(len(on_purpose))} URL loại trừ có chủ ý (noindex, chuyển hướng…)"))
        T.kpi(ui, "star", f"Nhóm {group_name}", f"{ok}/{len(members)} đã index", tone="lime",
              hint=" · ".join(x for x in (
                  f"{len(members) - len(latest)} URL chưa kiểm tra" if len(latest) < len(members) else "",
                  f"{dropped} URL vừa rớt index" if dropped else "") if x))
        quota_card = T.kpi(ui, "speed", "Quota kiểm tra hôm nay", "…", tone="amber", hint="gồm cả lịch chạy tự động")

    # ---- URL chưa index theo lý do ----
    with T.section(ui, "URL chưa index", "report",
                   "Theo lần kiểm tra gần nhất của mỗi URL. \"Cần xem\": lỗi hoặc Google chưa index. \"Có chủ ý\": "
                   "website tự loại trừ (noindex, chuyển hướng, trang thay thế có chính tắc), thường không cần sửa."):
        with ui.row().classes("items-center gap-3 w-full"):
            kind = ui.toggle({"fix": f"Cần xem · {fmt(len(to_fix))}", "intent": f"Có chủ ý · {fmt(len(on_purpose))}"},
                             value="fix").props("unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8").classes("sr-seg")
            reason = ui.select({}, label="Lý do", clearable=True).props("outlined dense options-dense").classes(
                "w-72")
        miss_table = ui.table(columns=[
            {"name": "url", "label": "URL", "field": "url", "align": "left", "sortable": True,
             "classes": "ellipsis", "style": "max-width: 420px"},
            {"name": "reason", "label": "Lý do", "field": "reason", "align": "left", "sortable": True},
            {"name": "crawl", "label": "Crawl gần nhất", "field": "crawl", "align": "left", "sortable": True},
            {"name": "checked", "label": "Kiểm tra lần cuối", "field": "checked", "align": "left", "sortable": True},
            {"name": "gsc", "label": "GSC", "field": "gsc", "align": "center"},
        ], rows=[], row_key="url", pagination=25).classes("w-full").props("flat dense")
        miss_table.add_slot("no-data", """
            <div class="full-width row items-center justify-center q-pa-md text-grey-7" style="gap:6px">
              <q-icon name="check_circle" color="green-7" size="20px" /> Không có URL nào trong mục này</div>""")
        miss_table.add_slot("body-cell-gsc", """
            <q-td :props="props">
              <a :href="props.value" target="_blank" rel="noopener" aria-label="Mở URL này trong Search Console">
                <q-icon name="open_in_new" color="grey-7" /></a>
            </q-td>""")

        def show_missing():
            items = to_fix if kind.value == "fix" else on_purpose
            counts = {}
            for x in items:
                counts[x["coverage"]] = counts.get(x["coverage"], 0) + 1
            reason.options = {k: f"{k} · {fmt(n)}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])}
            if reason.value not in counts:
                reason.value = None
            reason.update()
            miss_table.rows = [{"url": x["url"].replace(site.rstrip("/"), "") or "/", "reason": x["coverage"],
                                "crawl": _vn(x["last_crawl"]), "checked": _vn(x["checked_at"]),
                                "gsc": IX.gsc_inspect_link(site, x["url"])}
                               for x in items if not reason.value or x["coverage"] == reason.value]
        kind.on_value_change(lambda _: show_missing())
        reason.on_value_change(lambda _: show_missing())
        show_missing()

    if ed:
        with T.section(ui, "Kiểm tra URL mới", "add_link", "Mỗi dòng một URL. Kiểm tra ngay rồi theo dõi đến khi index"):
            paste = ui.textarea(placeholder=f"https://{domain(cfg.site_url)}/bai-moi/\nhttps://{domain(cfg.site_url)}/bai-moi-2/").props(
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
    if ed:  # chỉ hiện khi đã tích chọn URL
        ui.button("Bỏ theo dõi các URL đã chọn", icon="visibility_off", on_click=lambda: unwatch()).props(
            "outline no-caps").bind_visibility_from(table, "selected", backward=bool)
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
    sitemap_section(ui, connect, site)


def sitemap_section(ui, connect, site: str) -> None:
    """Sitemap đã gửi cho Search Console (lấy cùng lượt Nguồn tìm kiếm): lần gửi / Google đọc, số URL, lỗi."""
    from datetime import date

    from . import gsc_types as GT
    from . import ui_theme as T
    with connect() as c:
        maps = GT.sitemaps(c, site)
        fetched = GT.last_date(c, site)
    if not maps and not fetched:
        return  # chưa lấy lần nào (lượt chạy sáng mai sẽ lấy)
    checks = GT.sitemap_checks(maps)
    levels = {"high": ("Cần sửa", "red", "error"), "medium": ("Nên xem", "amber", "warning"),
              "info": ("Tham khảo", "blue", "info")}
    with T.section(ui, f"Sitemap · {len(maps)}", "account_tree",
                   "Sitemap đã gửi cho Search Console: Google đọc lần cuối khi nào, có lỗi không"):
        for ch in checks:
            label, tone, icon = levels[ch["level"]]
            with ui.row().classes("items-center gap-2 no-wrap w-full q-mb-xs"):
                T.status_chip(ui, label, tone, icon)
                ui.label((ch["path"].replace(site.rstrip("/"), "") + ": " if ch["path"] else "") + ch["text"])                     .classes("text-sm")
        if not maps:
            return

        def d(v):
            return f"{date.fromisoformat(v[:10]):%d/%m/%Y}" if v else "–"
        rows = []
        for i, m in enumerate(maps):
            sub = sum(int(x.get("submitted") or 0) for x in m.get("contents") or [])
            rows.append({"id": i, "path": m.get("path", "").replace(site.rstrip("/"), "") or m.get("path", ""),
                         "url": m.get("path", ""), "kind": "Sitemap index" if m.get("isSitemapsIndex") else "Sitemap",
                         "submitted": d(m.get("lastSubmitted")), "read": d(m.get("lastDownloaded")),
                         "urls": sub or "–", "errors": int(m.get("errors") or 0),
                         "warnings": int(m.get("warnings") or 0)})
        cols = [{"name": "path", "label": "Sitemap", "field": "path", "align": "left"},
                {"name": "kind", "label": "Loại", "field": "kind", "align": "left"},
                {"name": "submitted", "label": "Gửi lúc", "field": "submitted", "align": "left"},
                {"name": "read", "label": "Google đọc lúc", "field": "read", "align": "left"},
                {"name": "urls", "label": "URL đã gửi", "field": "urls", "align": "right"},
                {"name": "errors", "label": "Lỗi", "field": "errors", "align": "right"},
                {"name": "warnings", "label": "Cảnh báo", "field": "warnings", "align": "right"}]
        tb = ui.table(columns=cols, rows=rows, row_key="id").props("flat dense").classes("w-full")
        tb.add_slot("body-cell-path", """
            <q-td :props="props"><a :href="props.row.url" target="_blank" rel="noopener" class="sr-bl-link">
              {{ props.value }}</a></q-td>""")
