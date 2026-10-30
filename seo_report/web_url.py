"""Màn URL 3 cột: danh sách URL của nhóm ở giữa, chi tiết keyword của URL đang chọn bên phải."""
from . import indexing as IX
from . import keywords as K
from . import rank as R
from . import urls as U

GREEN, RED, MUTED = "#1E7C31", "#C2410C", "#6B6A5E"


def _n(v) -> str:
    return f"{v:,.0f}".replace(",", ".") if v is not None else "–"


def _pct(v) -> str:
    return f"{v * 100:.1f}%".replace(".", ",") if v is not None else "–"


def _pos(v) -> str:
    return f"{v:.1f}".replace(".", ",") if v else "–"


def _vn_date(iso: str) -> str:
    """'2026-10-28T06:22:14Z' → '28/10/2026'."""
    y, m, d = iso[:10].split("-")
    return f"{d}/{m}/{y}"


def _short(url: str, site: str) -> str:
    return url.replace(site.rstrip("/"), "") or "/"


def _delta(now, prev, lower_is_better=False, percent=True):
    """Trả về (chữ, màu) cho mức thay đổi so với kỳ trước."""
    if now is None or prev is None:
        return "", MUTED
    diff = now - prev
    if abs(diff) < 1e-9:
        return "–", MUTED
    good = diff < 0 if lower_is_better else diff > 0
    arrow = "▲" if good else "▼"
    if percent and prev:
        text = f"{arrow} {abs(diff) / prev * 100:.1f}%".replace(".", ",")
    else:
        text = f"{arrow} {abs(diff):.1f}".replace(".", ",") if isinstance(diff, float) else f"{arrow} {abs(diff)}"
    return text, GREEN if good else RED


RANK_TONES = [(3, ("#E7F3EA", "#1E7C31")), (10, ("#F2F7DC", "#5E7414")), (30, ("#FBF1DE", "#B7791F"))]


def organic_sessions_by_week(cfg, url: str, wks: list) -> dict[str, int]:
    """Phiên Organic Search (GA4) có trang đích là URL này, theo tuần thứ Hai (khóa: ngày thứ Hai ISO). GA4 ghi đường
    dẫn có hoặc không có / cuối, nên lọc cả hai dạng; tính theo giờ của property (Việt Nam)."""
    from contextlib import closing
    from datetime import date as _date, timedelta as _td
    from urllib.parse import urlsplit

    from . import ai_classifier as C
    from . import auth, db, ga4_query
    path = urlsplit(url).path or "/"
    paths = sorted({path, path.rstrip("/") or "/"})
    start, end = wks[-1][0], wks[0][1]
    with closing(db.connect(cfg.db_path)) as con:
        client = ga4_query.GA4Client(auth.build_ga4_data(auth.get_credentials(cfg, need=auth.ALL_SCOPES)),
                                     cfg.ga4_property, con)
        rep = client.run(["date"], ["sessions"], start, end, C.and_filters(
            C.channel_filter("Organic Search"), C._f("landingPage", inListFilter={"values": paths})), limit=1000)
    out: dict[str, int] = {}
    for r in rep.rows:
        d = _date(int(r["date"][:4]), int(r["date"][4:6]), int(r["date"][6:]))
        monday = (d - _td(days=d.weekday())).isoformat()
        out[monday] = out.get(monday, 0) + (r["sessions"] or 0)
    return out


def build_url_page(ui, cfg, connect, user: str, on_budget_change=None, ctx: dict | None = None) -> None:
    from .access import can_edit
    site = cfg.site_url
    ed = can_edit(user)  # người chỉ xem: không kiểm tra index, không sửa target, không thêm keyword / gắn ★
    with connect() as c:
        U.assign_urls(c, site)
        K.ensure_tables(c)
        end = K.latest_date(c, site)
        groups = dict(U.list_groups(c, site))
        gid = U.ensure_group(c, site)
    wks = K.weeks(end, 12)
    week_options = {i: f"Tuần {s:%d/%m}–{e:%d/%m}" for i, (s, e) in enumerate(wks)}
    # Tuần và nhóm lấy từ thanh trên cùng (dùng chung mọi màn).
    state = {"group": ctx["group"] if ctx else gid, "week": ctx["week"] if ctx else 0, "url": None, "search": "",
             "rows": [], "analysis": {}, "ga4": {}}

    def load_group():
        with connect() as c:
            members = U.group_members(c, state["group"])
            ids = [m["id"] for m in members]
            state["analysis"] = K.analyze(c, site, ids, end, cfg.keywords)
            state["targets"] = K.targets(c, ids)
            state["index"] = IX.latest(c, ids)
        state["members"] = members
        load_week()

    def load_week():
        s, e = wks[state["week"]]
        ps, pe = wks[state["week"] + 1] if state["week"] + 1 < len(wks) else (None, None)
        ids = [m["id"] for m in state["members"]]
        with connect() as c:
            now = K.url_period(c, ids, s, e)
            prev = K.url_period(c, ids, ps, pe) if ps else {}
        rows = []
        for m in state["members"]:
            a = state["analysis"].get(m["id"])
            c_now, i_now, p_now = now.get(m["id"], (0, 0, None))
            c_prev = prev.get(m["id"], (0, 0, None))[0] if ps else None
            match = K.head_matches_target(a.head if a else None, state["targets"].get(m["id"]))
            rows.append({**m, "path": _short(m["url"], site), "clicks_w": c_now, "impr_w": i_now, "pos_w": p_now,
                         "clicks_prev": c_prev, "head": a.head.query if a and a.head else "",
                         "mismatch": match is False, "cannibal": len(a.cannibal) if a else 0,
                         "index": state["index"].get(m["id"])})
        rows.sort(key=lambda r: -r["clicks_w"])
        state["rows"] = rows
        if state["url"] not in {r["id"] for r in rows}:
            state["url"] = rows[0]["id"] if rows else None

    # Cột danh sách dính trên màn và tự cuộn bên trong: danh sách dài không kéo cả trang, cột chi tiết luôn ở cạnh.
    with ui.row().classes("w-full no-wrap items-start gap-4"):
        with ui.column().classes("sr-card q-pa-md gap-2 no-wrap").style(
                "width: 360px; min-width: 300px; position: sticky; top: 60px; height: calc(100vh - 80px)"):
            with ui.row().classes("w-full items-baseline justify-between"):
                ui.label("URL").classes("text-xl font-semibold")
                count_label = ui.label().classes("text-sm muted")
            group_select = ui.select(groups, value=state["group"], label="Nhóm").classes("w-full").props(
                "dense outlined")
            week_select = ui.select(week_options, value=state["week"], label="Kỳ").classes("w-full").props(
                "dense outlined")
            if ctx:  # đã chọn ở thanh trên cùng
                group_select.set_visibility(False)
                week_select.set_visibility(False)
            search = ui.input(placeholder="Tìm URL hoặc head KW").props("dense outlined clearable").classes("w-full")
            from .web_export import export_menu
            with ui.row().classes("w-full"):
                export_menu(ui, cfg, connect, f"du-lieu-seo_tuan-{wks[state['week']][0]:%Y-%m-%d}",
                            lambda: export(), "Xuất dữ liệu", user=user)
            url_list = ui.column().classes("w-full gap-1 no-wrap").style(
                "flex: 1 1 auto; overflow-y: auto; min-height: 0; margin-right: -8px; padding-right: 6px")
        detail = ui.column().classes("col gap-4").style("min-width: 0")

    @ui.refreshable
    def render_list():
        rows = state["rows"]
        q = (state["search"] or "").lower()
        if q:
            rows = [r for r in rows if q in r["path"].lower() or q in r["head"].lower()]
        count_label.text = f"{len(state['rows'])} URL"
        if not state["rows"]:
            ui.label("Nhóm chưa có URL. Vào Quản lý URL để thêm.").classes("muted")
            ui.link("Mở Quản lý URL", "/urls")
            return
        for r in rows:
            selected = r["id"] == state["url"]
            # Một dòng = 2 hàng chữ gọn: đường dẫn + click; loại · head KW + mức đổi. Cảnh báo là chấm màu nhỏ có
            # chú thích khi rê chuột, không chen nhãn dài vào giữa dòng.
            flags = []
            if r["mismatch"]:
                flags.append(("#B7791F", "Head KW lệch target bạn gán"))
            ix = r["index"]
            if ix and ix["dropped"]:
                flags.append(("#C2410C", "Vừa rớt index"))
            elif ix and not ix["indexed"]:
                flags.append(("#C2410C", "Chưa được Google index"))
            text, color = _delta(r["clicks_w"], r["clicks_prev"], percent=False)
            with ui.element("div").classes("sr-url-item" + (" selected" if selected else "")).props(
                    f'title="{r["url"]}" tabindex="0" role="button"').on(
                    "click", lambda _, rid=r["id"]: select(rid)):
                with ui.element("div").classes("sr-url-line"):
                    ui.label(r["path"]).classes("sr-url-path")
                    ui.label(_n(r["clicks_w"])).classes("sr-url-clicks num")
                with ui.element("div").classes("sr-url-line"):
                    with ui.element("div").classes("sr-url-meta"):
                        for c, tip in flags:
                            ui.element("span").classes("sr-dot").style(f"background:{c}").tooltip(tip)
                        ui.label(f"{r['type'] or '–'} · {r['head'] or 'chưa có head'}").classes("ellipsis")
                    ui.label(text).classes("sr-url-delta num").style(f"color: {color}")

    with url_list:
        render_list()

    @ui.refreshable
    def render_detail():
        rid = state["url"]
        row = next((r for r in state["rows"] if r["id"] == rid), None)
        if not row:
            ui.label("Chọn một URL ở cột bên trái.").classes("muted")
            return
        a = state["analysis"][rid]
        s, e = wks[state["week"]]
        has_prev = state["week"] + 1 < len(wks)
        with connect() as c:
            now = K.url_period(c, [rid], s, e).get(rid, (0, 0, None))
            prev = K.url_period(c, [rid], *wks[state["week"] + 1]).get(rid, (0, 0, None)) if has_prev else None
            week_q = K.query_period(c, rid, s, e)
            series = K.weekly_series(c, rid, wks)
        target = state["targets"].get(rid, "")

        with ui.row().classes("w-full items-start justify-between"):
            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(row["path"]).classes("text-xl font-semibold")
                    with ui.link(target=row["url"], new_tab=True).props('aria-label="Mở trang trên site"'):
                        ui.icon("open_in_new", color="grey-7")
                with ui.row().classes("gap-2"):
                    ui.badge(row["type"] or "Chưa phân loại").props("outline color=grey-8")
                    ui.badge(groups.get(state["group"], "")).props("color=green-1 text-color=green-10")
            ui.label(f"{week_options[state['week']]} · so với tuần trước").classes("text-sm muted")

        from . import ui_theme as T

        labels = [p["week"] for p in series]

        def kpi(label, value, text_color, icon, tone, spark, hint=None):
            text, color = text_color
            T.kpi(ui, icon, label, value, text, None if color == MUTED else color == GREEN, tone=tone, spark=spark,
                  spark_labels=labels, hint=hint or f"{len(series)} tuần gần nhất")

        c_now, i_now, _ = now
        c_prev, i_prev, _ = prev if prev else (None, None, None)

        @ui.refreshable
        def kpi_cards():
            ga = state["ga4"].get(rid)
            with T.kpi_row(ui):
                kpi("Click (GSC)", _n(c_now), _delta(c_now, c_prev), "ads_click", "green", [p["clicks"] for p in series])
                kpi("Impression (GSC)", _n(i_now), _delta(i_now, i_prev), "visibility", "blue",
                    [p["impressions"] for p in series])
                if ga is None:
                    kpi("Phiên Organic Search (GA4)", "…", ("", MUTED), "groups", "purple", [], "đang tải từ GA4")
                elif ga.get("error"):
                    kpi("Phiên Organic Search (GA4)", "N/A", ("", MUTED), "groups", "purple", [],
                        f"không lấy được: {ga['error'][:60]}")
                else:
                    weekly = [ga["weeks"].get(w0.isoformat(), 0) for w0, _ in reversed(wks)]
                    s_now = ga["weeks"].get(s.isoformat(), 0)
                    s_prev = ga["weeks"].get(wks[state["week"] + 1][0].isoformat(), 0) if has_prev else None
                    kpi("Phiên Organic Search (GA4)", _n(s_now), _delta(s_now, s_prev), "groups", "purple", weekly,
                        "giờ Việt Nam (GSC theo giờ Pacific)")

        kpi_cards()

        async def load_ga4():
            if rid in state["ga4"] or not cfg.ga4_property:
                if not cfg.ga4_property:
                    state["ga4"][rid] = {"error": "chưa kết nối GA4"}
                    kpi_cards.refresh()
                return
            from nicegui import run as nrun

            def work():
                return organic_sessions_by_week(cfg, row["url"], wks)

            try:
                state["ga4"][rid] = {"weeks": await nrun.io_bound(work)}
            except (Exception, SystemExit) as e:  # noqa: BLE001
                state["ga4"][rid] = {"error": str(e)}
            kpi_cards.refresh()

        from nicegui import background_tasks
        background_tasks.create(load_ga4())

        ix = state["index"].get(rid)
        with ui.card().props("flat bordered").classes("w-full q-pa-sm"):
            with ui.row().classes("w-full items-center gap-3"):
                ui.icon("travel_explore", color="grey-7")
                if not ix:
                    ui.label("Chưa kiểm tra index.").classes("text-sm")
                else:
                    color = "green-10" if ix["indexed"] else ("red-10" if ix["dropped"] else "orange-10")
                    ui.label(ix["coverage"] or ix["verdict"] or "?").classes(f"text-sm font-medium text-{color}")
                    crawl = _vn_date(ix["last_crawl"]) if ix["last_crawl"] else "chưa crawl"
                    ui.label(f"Crawl gần nhất: {crawl} · kiểm tra ngày {_vn_date(ix['checked_at'])}").classes(
                        "text-xs muted")
                    if IX.canonical_mismatch(ix, row["url"]):
                        ui.badge(f"Google chọn canonical khác: {_short(ix['google_canonical'], site)}").props(
                            "color=orange-2 text-color=orange-10")
                ui.space()
                if ed:
                    check_btn = ui.button("Kiểm tra ngay", icon="refresh", on_click=lambda: check_now()).props(
                        "flat dense no-caps")

        async def check_now():
            from nicegui import run as nrun

            from . import auth

            def work():
                svc = auth.build_service(auth.get_credentials(cfg))
                r = IX.inspect(svc, site, row["url"])
                with connect() as c:
                    IX.save(c, rid, r)
                    return IX.latest(c, [rid])

            check_btn.props("loading")
            try:
                state["index"].update(await nrun.io_bound(work))
            except Exception as e:  # hết quota, mất mạng…
                ui.notify(f"Không kiểm tra được: {e}", type="negative", multi_line=True)
                return
            finally:
                check_btn.props(remove="loading")
            load_week()
            render_list.refresh()
            render_detail.refresh()

        visible = sum(v[0] for v in week_q.values())

        with ui.row().classes("w-full gap-3 items-end"):
            target_input = ui.input("Target KW (bạn gán)", value=target).props(
                "outlined dense" + ("" if ed else " readonly")).classes("col")

            def save_target():
                with connect() as c:
                    K.set_target(c, site, rid, target_input.value or "", user)
                    state["targets"] = K.targets(c, [r["id"] for r in state["rows"]])
                ui.notify("Đã lưu target KW", type="positive")
                load_week()
                render_list.refresh()
                render_detail.refresh()

            if ed:
                ui.button("Lưu", on_click=save_target).props("outline")
            with ui.column().classes("col gap-1"):
                ui.label("Head KW (Google nhận diện, 28 ngày)").classes("text-xs muted")
                with ui.row().classes("items-center gap-2"):
                    ui.label(a.head.query if a.head else "Chưa có query nào").classes("text-base font-medium")
                    match = K.head_matches_target(a.head, target)
                    if match is True:
                        ui.badge("✓ khớp target").props("color=green-1 text-color=green-10")
                    elif match is False:
                        ui.badge("lệch target").props("color=orange-2 text-color=orange-10")
                    elif not target:
                        ui.badge("chưa gán target").props("outline color=grey-7")
                if a.head and a.head_basis == "impression":
                    ui.label("Không query nào có click; chọn theo impression.").classes("text-xs muted")

        def kw_row(k: K.Kw, role: str):
            wc, wi, _ = week_q.get(k.query_id, (0, 0, None))
            return {"id": k.query_id, "role": role, "query": k.query, "star": k.query in starred,
                    "clicks": _n(wc), "impr": _n(wi), "c28": _n(k.clicks)}

        # ---- Khối 1: keyword SEO cam kết (DataForSEO) cho URL này ----
        from . import volume as V
        from .report import rank_change
        with connect() as c:
            committed = [k for k in R.keywords(c, site, end) if k["target_url"] == row["url"]]
            vols = V.latest(c)
            ranks = R.latest_by_keyword(c, site)
        starred = set(ranks)
        total_vol = sum((vols.get(k["id"]) or {}).get("volume") or 0 for k in committed)
        with T.section(ui, f"Keyword SEO cam kết · {len(committed)}", "flag",
                       "Keyword team theo dõi rank (DataForSEO, mobile toàn VN) với URL này là URL mục tiêu"
                       + (f" · tổng volume {_n(total_vol)}/tháng" if total_vol else "")):
            if ed:
                with ui.row().classes("w-full justify-end"):
                    ui.button("Thêm keyword SEO", icon="add", on_click=lambda: add_dialog.open()).props(
                        "flat dense no-caps")
            if not committed:
                T.empty_state(ui, "flag", "Chưa có keyword cam kết cho URL này",
                              "Bấm 'Thêm keyword SEO', hoặc gắn ★ cho keyword GSC ở khối bên dưới")
            else:
                krows = []
                for k in committed:
                    text, color, move = rank_change(k["date"], k["rank"], k["last_depth"], k["prev"], k["prev_depth"])
                    bg, fg = next((t for lim, t in RANK_TONES if k["rank"] is not None and k["rank"] <= lim),
                                  ("#F1F0EA", "#6B6A5E"))
                    v = vols.get(k["id"])
                    krows.append({
                        "id": k["id"], "keyword": k["keyword"],
                        "volume": (v["volume"] if v["volume"] is not None else -1) if v else None,
                        "pos": (str(k["rank"]) if k["rank"] is not None else f">{k['last_depth']}") if k["date"]
                        else "chờ check", "bg": bg, "fg": fg, "checked": bool(k["date"]),
                        "change": text, "change_color": color, "best": k["best"] or "",
                        "ranking": _short(k["ranking_url"], site) if k["ranking_url"] else "",
                        "ranking_full": k["ranking_url"] or "",
                        "wrong": bool(k["ranking_url"] and k["ranking_url"] != row["url"]),
                        "date": _vn_date(k["date"])[:5] if k["date"] else ""})
                kt = ui.table(columns=[
                    {"name": "keyword", "label": "Keyword", "field": "keyword", "align": "left", "sortable": True},
                    {"name": "volume", "label": "Volume/tháng", "field": "volume", "align": "right", "sortable": True,
                     ":format": "v => v === null || v === undefined ? 'chờ lấy' : (v < 0 ? '< 10' : "
                                "v.toLocaleString('vi-VN'))"},
                    {"name": "pos", "label": "Vị trí", "field": "pos", "align": "center"},
                    {"name": "change", "label": "Thay đổi", "field": "change", "align": "center"},
                    {"name": "best", "label": "Tốt nhất", "field": "best", "align": "center"},
                    {"name": "ranking", "label": "URL đang xếp hạng", "field": "ranking", "align": "left"},
                    {"name": "date", "label": "Check", "field": "date", "align": "center"},
                ], rows=krows, row_key="id").classes("w-full").props("flat dense")
                kt.add_slot("body-cell-pos", """
                    <q-td :props="props" class="text-center">
                      <span v-if="props.row.checked" :style="{background: props.row.bg, color: props.row.fg,
                            borderRadius: '6px', padding: '2px 8px', fontWeight: 700}">{{ props.value }}</span>
                      <span v-else class="muted">chờ check</span>
                    </q-td>""")
                kt.add_slot("body-cell-change", """
                    <q-td :props="props" class="text-center">
                      <span :style="{color: props.row.change_color, fontWeight: 600, whiteSpace: 'nowrap'}">
                        {{ props.value }}</span>
                    </q-td>""")
                kt.add_slot("body-cell-ranking", """
                    <q-td :props="props">
                      <div class="row no-wrap items-center" style="gap: 4px; max-width: 260px">
                        <a v-if="props.row.ranking_full" :href="props.row.ranking_full" target="_blank"
                           rel="noopener" :title="props.row.ranking_full" class="ellipsis"
                           style="color: inherit; text-decoration: none; min-width: 0">{{ props.value }}</a>
                        <span v-else class="muted">–</span>
                        <q-icon v-if="props.row.wrong" name="warning" color="orange-8" size="16px">
                          <q-tooltip>Google đang xếp hạng URL khác, không phải URL này</q-tooltip></q-icon>
                      </div>
                    </q-td>""")
                ui.label("Volume: Google Ads, Việt Nam, cập nhật mỗi tháng. Google gộp các biến thể gần nhau (ví dụ "
                         "'mắt kính' và 'kính mắt') thành cùng một số.").classes("text-xs muted")

        with ui.dialog() as add_dialog, ui.card().style("min-width: 560px; border-radius: 14px"):
            ui.label(f"Thêm keyword SEO cho {row['path']}").classes("text-lg font-semibold")
            ui.label("Mỗi dòng một keyword. URL mục tiêu là URL này. Volume lấy ngay sau khi thêm.").classes(
                "text-sm muted")
            new_kw = ui.textarea(placeholder="tròng kính chống ánh sáng xanh\ntròng kính đổi màu").props(
                "outlined autogrow").classes("w-full")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Đóng", on_click=add_dialog.close).props("flat no-caps")
                add_btn = ui.button("Thêm", icon="playlist_add", on_click=lambda: add_committed()).props(
                    "unelevated no-caps")

        async def add_committed():
            from nicegui import run as nrun
            items = [(line.split("|")[0].strip(), row["url"]) for line in (new_kw.value or "").splitlines()
                     if line.split("|")[0].strip()]
            if not items:
                return
            with connect() as c:
                r = R.add_keywords(c, site, cfg.rank, end, items, user)
                ids = [k["id"] for k in R.keywords(c, site, end) if k["keyword"] in {i[0] for i in items}]
            add_btn.props("loading")
            try:
                def work():
                    with connect() as c:
                        return V.refresh(c, site, cfg, end, only_ids=ids, log=lambda m: None)
                await nrun.io_bound(work)
            except Exception as e:  # noqa: BLE001  (thêm keyword vẫn thành công, chỉ thiếu volume)
                ui.notify(f"Đã thêm keyword nhưng chưa lấy được volume: {e}", type="warning", multi_line=True)
            finally:
                add_btn.props(remove="loading")
            msg = f"Đã thêm {len(r['added'])} keyword"
            if r["updated"]:
                msg += f", đổi URL mục tiêu {len(r['updated'])}"
            if r["over_budget"]:
                msg += f"; KHÔNG thêm {len(r['over_budget'])} keyword vì vượt ngân sách"
            ui.notify(msg, type="warning" if r["over_budget"] else "positive", multi_line=True)
            add_dialog.close()
            if on_budget_change:
                on_budget_change()
            render_detail.refresh()

        # ---- Khối 2: keyword GSC nhận diện cho URL này ----
        with T.section(ui, "Keyword GSC nhận diện", "manage_search",
                       f"Head và keyword phụ từ dữ liệu GSC ({cfg.keywords.window_days} ngày). ★ = đưa vào keyword "
                       "SEO cam kết của URL này"):
            if c_now:
                ui.label(f"Click nhìn thấy theo keyword: {_n(visible)}/{_n(c_now)} ({visible / c_now * 100:.0f}%). "
                         "Phần còn lại thuộc các query hiếm mà Google ẩn.").classes("text-xs muted")
            rows = ([kw_row(a.head, "Head")] if a.head else []) + [kw_row(k, "Phụ") for k in a.secondary]
            kw_table = ui.table(columns=[
                {"name": "role", "label": "Vai trò", "field": "role", "align": "left"},
                {"name": "query", "label": "Keyword", "field": "query", "align": "left"},
                {"name": "star", "label": "★", "field": "star", "align": "center"},
                {"name": "clicks", "label": "Click tuần", "field": "clicks", "align": "right"},
                {"name": "impr", "label": "Impression tuần", "field": "impr", "align": "right"},
                {"name": "c28", "label": f"Click {cfg.keywords.window_days} ngày", "field": "c28", "align": "right"},
            ], rows=rows, row_key="id").classes("w-full").props("flat dense")
            kw_table.add_slot("body-cell-star", """
                <q-td :props="props" auto-width>
                  <q-btn flat round dense size="sm" :icon="props.value ? 'star' : 'star_border'"
                         :color="props.value ? 'lime-9' : 'grey-6'"
                         :aria-label="(props.value ? 'Bỏ ★ ' : 'Gắn ★ ') + props.row.query"
                         @click="$parent.$emit('star', props.row)" />
                </q-td>""" if ed else """
                <q-td :props="props" auto-width>
                  <q-icon v-if="props.value" name="star" color="lime-9" size="18px" />
                </q-td>""")

            def on_star(e):
                with connect() as c:
                    ok, msg = R.toggle_star(c, site, cfg.rank, end, rid, e.args["query"], user)
                ui.notify(msg, type="positive" if ok else "negative", multi_line=True, timeout=6000)
                if ok:
                    from nicegui import background_tasks as bt

                    async def vol():
                        from nicegui import run as nrun

                        def work():
                            with connect() as c:
                                return V.refresh(c, site, cfg, end, log=lambda m: None)
                        try:
                            await nrun.io_bound(work)
                        except Exception:  # noqa: BLE001
                            pass
                    bt.create(vol())
                if on_budget_change:
                    on_budget_change()
                render_detail.refresh()

            if ed:
                kw_table.on("star", on_star)
            ui.label(f"Keyword phụ: impression ≥ {cfg.keywords.min_impressions} và position ≤ "
                     f"{cfg.keywords.max_position:g} trong {cfg.keywords.window_days} ngày, không phải thương hiệu, "
                     "URL này mạnh nhất cho query đó.").classes("text-xs muted")

        if a.cannibal:
            with ui.expansion(f"Cannibalization: {len(a.cannibal)} query có URL khác cùng nhận",
                              icon="call_split").classes("w-full").props("dense"):
                ui.table(columns=[
                    {"name": "query", "label": "Query", "field": "query", "align": "left"},
                    {"name": "clicks", "label": "Click 28 ngày (URL này)", "field": "clicks", "align": "right"},
                    {"name": "other", "label": "URL đang mạnh hơn", "field": "other", "align": "left"},
                ], rows=[{"id": k.query_id, "query": k.query, "clicks": _n(k.clicks),
                          "other": _short(k.stronger_url, site)} for k in sorted(a.cannibal, key=lambda k: -k.impressions)],
                    row_key="id").classes("w-full").props("flat dense")

        with ui.expansion(f"Keyword bị loại: {len(a.excluded)}", icon="filter_alt").classes("w-full").props("dense"):
            ui.table(columns=[
                {"name": "query", "label": "Query", "field": "query", "align": "left", "sortable": True},
                {"name": "reason", "label": "Lý do", "field": "reason", "align": "left", "sortable": True},
                {"name": "clicks", "label": "Click 28 ngày", "field": "clicks", "align": "right", "sortable": True},
                {"name": "impr", "label": "Impr 28 ngày", "field": "impr", "align": "right", "sortable": True},
                {"name": "pos", "label": "Pos", "field": "pos", "align": "right", "sortable": True},
            ], rows=[{"id": k.query_id, "query": k.query, "reason": k.reason, "clicks": k.clicks,
                      "impr": k.impressions, "pos": round(k.position, 1)} for k in a.excluded],
                row_key="id", pagination=20).classes("w-full").props("flat dense")

        ui.echart({
            "tooltip": {"trigger": "axis"},
            "legend": {"data": ["Click", "Impression"], "bottom": 0},
            "grid": {"left": 48, "right": 48, "top": 24, "bottom": 48},
            "xAxis": {"type": "category", "data": [p["week"] for p in series]},
            "yAxis": [{"type": "value", "name": "Click"},
                      {"type": "value", "name": "Impression", "splitLine": {"show": False}}],
            "series": [
                {"name": "Click", "type": "bar", "data": [p["clicks"] for p in series],
                 "itemStyle": {"color": GREEN, "borderRadius": [4, 4, 0, 0]}},
                {"name": "Impression", "type": "line", "yAxisIndex": 1, "data": [p["impressions"] for p in series],
                 "itemStyle": {"color": "#2563EB"}, "smooth": True, "symbol": "circle", "symbolSize": 5},
            ],
        }).classes("w-full").style("height: 260px")
        ui.label("12 tuần gần nhất (GSC).").classes("text-xs muted")

    with detail:
        render_detail()

    async def export() -> bytes:
        from nicegui import run

        from .export import build_data_export

        def make():
            with connect() as c:
                return build_data_export(c, cfg, state["group"], state["week"], user)

        return await run.io_bound(make)

    def select(rid):
        state["url"] = rid
        render_list.refresh()
        render_detail.refresh()

    def on_group(e):
        state["group"] = e.value
        load_group()
        render_list.refresh()
        render_detail.refresh()

    def on_week(e):
        state["week"] = e.value
        load_week()
        render_list.refresh()
        render_detail.refresh()

    def on_search(e):
        state["search"] = e.value or ""
        render_list.refresh()

    load_group()
    render_list.refresh()
    render_detail.refresh()
    group_select.on_value_change(on_group)
    week_select.on_value_change(on_week)
    search.on_value_change(on_search)
