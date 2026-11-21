"""Giao diện "Tất cả backlink": bảng mỗi link một dòng, audit theo từng link (mỗi mục là bộ lọc của bảng), hộp xem
link cụ thể khi bấm ở các bảng tổng (website / anchor / trang đích), gợi ý nhãn theo loại website."""
from datetime import date
from urllib.parse import urlparse

from . import access as A
from . import ai_format as F
from . import link_audit as LA
from . import site_labels as SL
from . import table_kit as TK
from . import ui_theme as T
from . import web_labels as WL

from .backlink_links import SB_TYPES as BLL_SB  # noqa: E402

SRC_NAME = {"dfs": "DataForSEO", "semrush": "Semrush"}
GROUPS = (("high", "Cần xử lý ngay", "ảnh hưởng xấu tới SEO, nên làm trước"),
          ("medium", "Nên xem", "chưa gấp, soát lại khi có thời gian"),
          ("info ok", "Chỉ số hồ sơ", "Số liệu mô tả hồ sơ backlink, không phải việc phải làm."))
LEVELS = {"high": ("Cần xử lý", "red", "error"), "medium": ("Nên xem", "amber", "warning"),
          "info": ("Tham khảo", "blue", "info"), "ok": ("Ổn", "green", "check_circle")}
TYPE_NAME = {"anchor": "chữ", "image": "ảnh", "redirect": "chuyển hướng", "canonical": "canonical",
             "alternate": "alternate", "meta": "meta"}


def _vn(d) -> str:
    try:
        return f"{date.fromisoformat(str(d)[:10]):%d/%m/%Y}"
    except (TypeError, ValueError):
        return "–"


def _path(url: str) -> str:
    p = urlparse(url or "")
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def pbn_table(ui, user, check: dict, kit: dict, on_label) -> None:
    """Mục “Nghi ngờ mạng PBN”: bảng website, mỗi dòng một website kèm IP / dải IP đang dùng chung và số website khác
    cùng IP đó. Lọc, tick chọn để gắn nhãn và xuất Excel như các bảng khác."""
    rows, seen = [], set()
    for g in check.get("groups") or []:
        n = len(g["domains"])
        for d in g["domains"]:
            if d in seen:  # website nằm ở cả nhóm IP lẻ và nhóm dải IP: chỉ lấy một dòng (khớp số của mục)
                continue
            seen.add(d)
            mine = [x for x in check["rows"] if x["d_from"] == d]
            rows.append({"k": d, "domain": d, "where": g["where"], "n_sites": n,
                         "links": len(mine), "rank": max((x.get("d_rank") or 0 for x in mine), default=0),
                         "spam": max((x.get("spam") or 0 for x in mine), default=0),
                         "country": next((x.get("country") or "" for x in mine if x.get("country")), "").upper()})
    if not rows:
        return
    rows.sort(key=lambda r: (-r["n_sites"], r["where"], r["domain"]))
    WL.enrich(rows, "domain", user)
    cl = A.is_client(user)
    cols = [{"name": "domain", "label": "Website", "field": "domain", "align": "left", "sortable": True}, WL.COLUMN,
            {"name": "where", "label": "Dùng chung", "field": "where", "align": "left", "sortable": True,
             "width": 190},
            {"name": "n_sites", "label": "Website chung IP", "field": "n_sites", "align": "right", "sortable": True,
             "width": 140},
            {"name": "links", "label": "Link về mình", "field": "links", "align": "right", "sortable": True,
             "width": 120},
            {"name": "rank", "label": "Uy tín", "field": "rank", "align": "right", "sortable": True, "width": 85},
            {"name": "country", "label": "Quốc gia", "field": "country", "align": "left", "sortable": True,
             "width": 95}]
    if not cl:
        cols.insert(-1, {"name": "spam", "label": "Spam", "field": "spam", "align": "right", "sortable": True,
                         "width": 75})
    TK.table(ui, columns=cols, rows=rows, row_key="k", st=kit, noun="website", classes="sr-kw-tbl", page_size=25,
             filters=[("text", "Website", ["domain"]), ("enum", "IP / dải IP", "where"),
                      ("num", "Website chung IP", "n_sites"), ("num", "Link về mình", "links"),
                      ("num", "Uy tín", "rank"), *([] if cl else [("num", "Điểm spam", "spam")]), WL.FILTER],
             actions=WL.action(ui, user, "domain", on_label), export="backlink-pbn",
             events=WL.events(ui, user, on_label),
             copy=[("Website", "domain"), WL.COPY, ("Dùng chung", "where"), ("Website chung IP", "n_sites"),
                   ("Link về mình", "links"), ("Uy tín", "rank"), *([] if cl else [("Điểm spam", "spam")]),
                   ("Quốc gia", "country")],
             slots={"body-cell-domain": """
                <q-td :props="props"><a :href="'https://' + props.row.domain" target="_blank" rel="noopener"
                  class="sr-bb-link">{{ props.row.domain }}</a></q-td>""",
                    "body-cell-labels": WL.SLOT})


def rows_of(items: list[dict], client: bool = False, brand_terms: list[str] | None = None,
            user=None) -> list[dict]:
    from .backlink_audit import anchor_type
    rows = []
    for i, x in enumerate(items):
        st = x.get("st_to")
        tags = [a for a in x.get("attrs") or [] if a in ("sponsored", "ugc")]
        rows.append({
            "i": i, "d_from": x["d_from"], "from": x["u_from"], "from_path": _path(x["u_from"]), "title": x["title"],
            "anchor": x["anchor"] or ("(ảnh" + (f": {x['alt']}" if x.get("alt") else ", không alt") + ")"
                                      if x.get("type") == "image" else "(trống)"),
            "to": x["u_to"], "to_path": _path(x["u_to"]),
            "st": "" if not st or st == 200 else str(st), "bad": bool(x.get("broken") or (st or 0) >= 400),
            "follow": "dofollow" if x["follow"] else "nofollow", "tags": ", ".join(tags),
            "type": TYPE_NAME.get(x.get("type"), x.get("type") or ""), "place": LA.place(x),
            "src": " + ".join(SRC_NAME.get(s_, s_) for s_ in (x.get("src") or ["dfs"])),
            "src_l": [SRC_NAME.get(s_, s_) for s_ in (x.get("src") or ["dfs"])], "ascore": x.get("ascore"),
            "d_rank": x.get("d_rank") or 0, "p_rank": x.get("p_rank") or 0, "spam": x.get("spam") or 0,
            "kw10": x.get("kw10") or 0, "ext": x.get("ext"), "lang": x.get("lang") or "",
            "country": x.get("country") or "", "ip": x.get("ip") or "",
            "first_iso": x.get("first") or "", "first": _vn(x.get("first")), "last_iso": x.get("last") or "",
            "spammy": (x.get("spam") or 0) >= LA.SPAM and not client,
            "client": client,  # khách hàng: ô bảng không hiện dòng phụ kỹ thuật (dạng link, mã trạng thái)
            # thêm cho xuất file / sao chép (đủ dữ liệu để audit)
            "pre": x.get("pre") or "", "post": x.get("post") or "", "alt": x.get("alt") or "",
            "st_to": st, "redir": x.get("redir") or "", "indirect": "có" if x.get("indirect") else "",
            "attrs_all": ", ".join(x.get("attrs") or []), "loc": x.get("loc") or "", "same": x.get("same"),
            "rank": x.get("rank"), "kw100": x.get("kw100") or 0, "platform": ", ".join(x.get("platform") or []),
            "st_from": x.get("st_from"), "original": "có" if x.get("original") else "",
            "threat": ((BLL_SB.get(x["threat"], x["threat"]) if x["threat"] else "an toàn") if "threat" in x
                       else "chưa kiểm tra"),
            "danger": BLL_SB.get(x.get("threat") or "", "") if x.get("threat") and not client else "",
            "a_type": {"url": "URL", "brand": "Thương hiệu", "keyword": "Từ khóa", "empty": "Trống / ảnh"}.get(
                anchor_type(x.get("anchor") or "", brand_terms or []), "")})
    WL.enrich(rows, "d_from", user)
    return rows


def table(ui, user, items: list[dict], kit: dict, on_label=None, export: str = "backlink", noun: str = "link") -> None:
    """Bảng link: lọc, chọn, gắn nhãn website, sao chép, xuất Excel."""
    cl = A.is_client(user)
    rows = rows_of(items, cl, user=user)
    cols = [{"name": "from", "label": "Trang đặt link", "field": "d_from", "align": "left", "sortable": True},
            WL.COLUMN,
            {"name": "anchor", "label": "Anchor", "field": "anchor", "align": "left", "sortable": True, "width": 180},
            {"name": "to", "label": "Trang đích", "field": "to_path", "align": "left", "sortable": True, "width": 200},
            {"name": "follow", "label": "Loại", "field": "follow", "align": "left", "sortable": True, "width": 110},
            # Vị trí đặt link: phần lớn là "không rõ" nên không để thành cột; vẫn lọc được và có trong file xuất
            {"name": "d_rank", "label": "Uy tín", "field": "d_rank", "align": "right", "sortable": True, "width": 80},
            {"name": "src", "label": "Nguồn", "field": "src", "align": "left", "sortable": True, "width": 105},
            {"name": "first", "label": "Thấy lần đầu", "field": "first_iso", "align": "left", "sortable": True,
             "width": 115}]
    if not cl:
        cols.insert(-1, {"name": "spam", "label": "Spam", "field": "spam", "align": "right", "sortable": True,
                         "width": 75})
    else:  # khách hàng: kết quả, không cột kỹ thuật (nhãn nội bộ, dofollow / nofollow, nguồn dữ liệu)
        cols = [c_ for c_ in cols if c_["name"] not in ("labels", "follow", "src")]
    filters = ([("text", "Website / trang đặt link / anchor / trang đích", ["from", "title", "anchor", "to"]),
                ("num", "Uy tín website", "d_rank"), ("date", "Thấy lần đầu", "first_iso")] if cl else
               [("text", "Website / trang đặt link / anchor / trang đích", ["from", "title", "anchor", "to"]),
                ("num", "Uy tín website", "d_rank"), ("num", "Điểm spam", "spam"),
                ("enum", "Loại link", "follow"), ("enum", "Vị trí", "place"), ("enum", "Dạng link", "type"),
                ("enum", "Nguồn dữ liệu", "src_l"),
                WL.FILTER, ("date", "Thấy lần đầu", "first_iso")])
    copy = ([("Website", "d_from"), ("Trang đặt link", "from"), ("Tiêu đề trang", "title"), ("Anchor", "anchor"),
             ("Trang đích", "to"), ("Uy tín website", "d_rank"), ("Thấy lần đầu", "first_iso")] if cl else
            [("Website", "d_from"), WL.COPY, ("Nguồn", "src"), ("Page ascore (Semrush)", "ascore"), ("Trang đặt link", "from"), ("Tiêu đề trang", "title"),
             ("Anchor", "anchor"), ("Loại anchor", "a_type"), ("Chữ trước anchor", "pre"),
             ("Chữ sau anchor", "post"), ("Dạng link", "type"), ("Alt ảnh", "alt"), ("Trang đích", "to"),
             ("Mã trang đích", "st_to"), ("Chuyển hướng tới", "redir"), ("Link gián tiếp", "indirect"),
             ("Loại", "follow"), ("Thuộc tính rel", "attrs_all"), ("Vị trí", "place"), ("Vị trí (HTML)", "loc"),
             ("Số link giống trên trang", "same"), ("Uy tín website", "d_rank"), ("Uy tín trang", "p_rank"),
             ("Uy tín truyền (rank)", "rank"), ("Điểm spam", "spam"),
             ("Link ra ngoài của trang nguồn", "ext"), ("Từ khóa top 10 của trang nguồn", "kw10"),
             ("Từ khóa top 100 của trang nguồn", "kw100"), ("Loại website (DataForSEO)", "platform"),
             ("Ngôn ngữ", "lang"), ("Quốc gia", "country"), ("IP", "ip"), ("Mã trang nguồn", "st_from"), ("Google Safe Browsing", "threat"),
             ("Có từ lần đầu", "original"), ("Thấy lần đầu", "first_iso"), ("Thấy gần nhất", "last_iso")])
    TK.table(ui, columns=cols, rows=rows, row_key="i", st=kit, noun=noun, classes="sr-kw-tbl", page_size=25,
             filters=filters,
             actions=WL.action(ui, user, "d_from", on_label) if on_label else None, export=export,
             events=WL.events(ui, user, on_label),
             copy=copy,
             slots={
                 "body-cell-from": """
                <q-td :props="props"><div class="ellipsis" style="max-width:100%">
                  <a :href="props.row.from" target="_blank" rel="noopener" class="sr-bb-link ellipsis"
                     style="max-width:100%" :title="props.row.from">{{ props.row.title || props.row.from_path }}</a>
                  <div class="sr-bb-sub ellipsis" style="max-width:100%">{{ props.row.d_from }}{{ props.row.from_path }}
                  </div><span v-if="props.row.danger" class="sr-bl-type k-lost">Google cảnh báo: {{ props.row.danger }}
                  </span></div></q-td>""",
                 "body-cell-labels": WL.SLOT,
                 "body-cell-anchor": """
                <q-td :props="props"><div class="ellipsis" :title="props.row.anchor">{{ props.row.anchor }}</div>
                  <div v-if="!props.row.client" class="sr-bb-sub">{{ props.row.type }}</div></q-td>""",
                 "body-cell-to": """
                <q-td :props="props"><div class="ellipsis" :title="props.row.to">{{ props.row.to_path }}</div>
                  <span v-if="props.row.st && !props.row.client" class="sr-bl-type" :class="props.row.bad ? 'k-lost' : ''">
                    {{ props.row.bad ? 'lỗi ' : '' }}{{ props.row.st }}</span></q-td>""",
                 "body-cell-follow": """
                <q-td :props="props"><span class="sr-bl-type" :class="props.row.follow === 'dofollow' ? 'k-new' : ''">
                  {{ props.row.follow }}</span><div v-if="props.row.tags" class="sr-bb-sub">{{ props.row.tags }}</div>
                </q-td>""",
                 "body-cell-spam": """
                <q-td :props="props"><span :class="props.row.spammy ? 'sr-bl-type k-lost' : ''">{{ props.row.spam }}
                </span></q-td>""",
                 "body-cell-first": """<q-td :props="props">{{ props.row.first }}</q-td>""",
                 "body-cell-src": """
                <q-td :props="props"><span class="text-xs">{{ props.row.src }}</span>
                  <div v-if="props.row.ascore != null" class="sr-bb-sub">ascore {{ props.row.ascore }}</div></q-td>"""})


def dialog(ui, user, title: str, sub: str, items: list[dict], on_label=None) -> None:
    """Hộp xem link cụ thể (bấm ở bảng website / anchor / trang đích, hoặc một mục audit)."""
    kit = TK.new_state()
    with ui.dialog() as d, ui.card().style("width:1180px; max-width:97vw; border-radius:14px"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            with ui.column().classes("gap-0 col").style("min-width:0"):
                ui.label(title).classes("text-lg font-semibold ellipsis")
                ui.label(sub).classes("text-xs muted ellipsis")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        if not items:
            ui.label("Không có link nào khớp trong lần lấy gần nhất (danh sách toàn bộ backlink có thể được lấy trước "
                     "khi số tổng thay đổi).").classes("text-sm muted q-mt-sm")
        else:
            table(ui, user, items, kit, on_label=on_label, export="backlink-chi-tiet")
    d.on("hide", d.delete)
    d.open()


def suggest_dialog(ui, user, check: dict, on_done) -> None:
    """Xác nhận nhãn gợi ý theo loại website (báo → Báo PR, diễn đàn → Diễn đàn, blog / wiki → Web 2.0)."""
    sugg = check.get("suggest") or {}
    pick = {d_: set(v) for d_, v in sugg.items()}
    with ui.dialog() as d, ui.card().style("width:560px; max-width:95vw; border-radius:14px"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label(f"Gợi ý nhãn · {len(sugg)} website").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        ui.label("Theo phân loại website của DataForSEO, có thể sai: bỏ tick nhãn không đúng rồi bấm Gắn nhãn.").classes(
            "text-xs muted")
        with ui.column().classes("w-full gap-0 q-mt-sm").style("max-height:55vh; overflow:auto"):
            for dom, labs in sorted(sugg.items()):
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    ui.link(dom, f"https://{dom}", new_tab=True).classes("text-sm col ellipsis sr-bb-link")
                    for lab in labs:
                        ui.checkbox(lab, value=True, on_change=lambda e, dom=dom, lab=lab: (
                            pick[dom].add(lab) if e.value else pick[dom].discard(lab))).props("dense")

        def go() -> None:
            with SL.connect() as c:
                SL.ensure(c)
                for lab in {lb for v in pick.values() for lb in v}:
                    SL.apply(c, [x for x, v in pick.items() if lab in v], add=[lab], user=str(user))
            d.close()
            ui.notify(f"Đã gắn nhãn cho {sum(1 for v in pick.values() if v)} website", type="positive",
                      position="bottom-right")
            on_done()
        with ui.row().classes("w-full justify-end gap-2 q-mt-md"):
            ui.button("Hủy", on_click=d.close).props("flat no-caps")
            ui.button("Gắn nhãn", icon="sell", on_click=go).props("unelevated no-caps")
    d.on("hide", d.delete)
    d.open()


def panel(ui, cfg, user, data: dict | None, checks: list[dict], state: dict, refresh, export=None,
          mode: str = "links") -> None:
    """mode "links" (tab Tất cả backlink): bảng mọi link. mode "audit" (tab Audit): các mục kiểm tra, bấm một mục để
    xem danh sách link của mục đó (lọc, gắn nhãn, xuất file), kèm file disavow / Safe Browsing / gợi ý nhãn."""
    if mode == "links":
        checks = []
    ed = A.can_edit(user)
    site = cfg.site_url
    if not data:
        T.empty_state(ui, "link", "Chưa có danh sách toàn bộ backlink",
                      "Danh sách mỗi link một dòng được lấy cùng lượt “Lấy số mới” (khoảng 0,05 USD với website "
                      "khoảng 600 link), hoặc nhập file backlink xuất từ Semrush." if ed else
                      "Danh sách sẽ có sau lần lấy số tiếp theo.")
        if ed:
            with ui.row().classes("w-full justify-center"):
                ui.button("Nhập dữ liệu Semrush", icon="upload_file",
                          on_click=lambda: import_dialog(ui, cfg, user, refresh)).props("outline no-caps")
        return
    items = data["items"]
    st = state.setdefault(mode, {"f": None, "kit": TK.new_state()})
    by_key = {c["key"]: c for c in checks}

    def set_filter(key: str | None, toggle: bool = True) -> None:
        st["f"] = None if toggle and st["f"] == key else key
        st["kit"]["sel"] = set()
        checks_box.refresh()
        tbl.refresh()
        if st["f"]:  # cuộn xuống bảng (đợi bảng vẽ lại / tab hiện ra)
            T.scroll_to(ui, f"bl-{mode}-table")
    state.setdefault("setf", {})[mode] = set_filter

    @ui.refreshable
    def checks_box() -> None:
        """Các mục kiểm tra chia ba nhóm: Cần xử lý ngay, Nên xem, Chỉ số hồ sơ (thu gọn). Số chính của mỗi mục là
        số website bị ảnh hưởng (đơn vị chung để so mức nặng), số theo đơn vị riêng ghi ở dòng dưới."""
        if not checks:
            return
        n_high = sum(1 for c in checks if c["level"] == "high")
        n_med = sum(1 for c in checks if c["level"] == "medium")
        sub = (f"{n_high} việc cần xử lý · {n_med} việc nên xem" if n_high or n_med else "Không có vấn đề")

        def check_row(c: dict) -> None:
            label, tone, icon_ = LEVELS[c["level"]]
            can = bool(c["rows"]) and c["level"] != "ok"
            on = st["f"] == c["key"]
            row = ui.element("button").classes("sr-au-filter" + (" on" if on else "")
                                               + ("" if can else " off")).props('type="button"')
            if can:
                row.on("click", lambda _, k_=c["key"]: set_filter(k_))
            with row:
                T.status_chip(ui, label, tone, icon_)
                with ui.column().classes("gap-0").style("min-width:0; flex:1 1 0; text-align:left"):
                    ui.label(c["title"]).classes("text-sm font-semibold")
                    mix = c.get("mix")
                    ui.label(" · ".join(f"{k_} {v}%" for k_, v in mix.items()) if mix else c["action"]).classes(
                        "text-xs muted")
                own = f"{c['count']}{c['unit']}" if c["unit"].startswith("%") else f"{F.n(c['count'])} {c['unit']}"
                n_web = len({x.get("d_from") for x in c["rows"] if x.get("d_from")}) if c["rows"] else 0
                with ui.column().classes("gap-0 items-end"):
                    ui.label(f"{F.n(n_web)} website" if n_web else own).classes("sr-au-num num")
                    if n_web and c["unit"] != "website":
                        ui.label(own).classes("text-xs muted")
                if can:
                    ui.icon("close" if on else "filter_list", size="18px").classes("sr-au-ico")
            row.tooltip(c["why"])

        def tools() -> None:
            """Thao tác của tab Audit, đặt ngay dưới nhóm Cần xử lý cho khỏi lạc cuối trang."""
            if not ed:
                return
            with ui.row().classes("items-center gap-2 q-mt-sm"):
                if by_key.get("L_spam", {}).get("rows") or by_key.get("L_threat", {}).get("rows"):
                    from . import link_audit as LA_

                    def download(_=None):
                        ui.download.content(LA_.disavow(items, f"{date.today():%d/%m/%Y}"),
                                            f"disavow-{urlparse(site).netloc or 'site'}-{date.today():%Y%m%d}.txt",
                                            "text/plain")
                    ui.button("Tải file disavow (.txt)", icon="download", on_click=download).props(
                        "outline no-caps dense color=grey-9").tooltip(
                        "Website có link điểm spam cao hoặc bị Google đánh dấu nguy hiểm. Xem lại trước khi nộp.")
                if not all("threat" in x for x in items):
                    ui.button("Kiểm tra Safe Browsing", icon="gpp_maybe", on_click=lambda: safe_browsing()).props(
                        "outline no-caps dense color=grey-9").tooltip(
                        "Hỏi Google Safe Browsing website đặt link có bị đánh dấu mã độc / lừa đảo không (miễn phí)")
                if by_key.get("L_platform", {}).get("count"):
                    ui.button(f"Xem gợi ý nhãn · {by_key['L_platform']['count']} website", icon="sell",
                              on_click=lambda: suggest_dialog(ui, user, by_key["L_platform"], refresh)).props(
                        "outline no-caps dense color=grey-9")
        with T.section(ui, "Audit backlink", "fact_check", sub + " · bấm một mục để xem danh sách link bên dưới"):
            for lvl, name, note in GROUPS:
                part = [c for c in checks if c["level"] in lvl]
                if not part:
                    continue
                if "info" in lvl:  # chỉ số mô tả hồ sơ, không phải việc: thu gọn
                    with ui.expansion(f"{name} · {len(part)} mục").props("dense").classes("w-full sr-au-fold"):
                        ui.label(note).classes("text-xs muted q-mb-xs")
                        with ui.element("div").classes("sr-au-todo"):
                            for c in part:
                                check_row(c)
                    continue
                with ui.row().classes("sr-au-group-h"):
                    ui.label(f"{name} · {len(part)} mục")
                    ui.label(note).classes("sr-au-group-note")
                with ui.element("div").classes("sr-au-todo"):
                    for c in part:
                        check_row(c)
                if "high" in lvl:
                    tools()

    def drop_import(source: str) -> None:
        from contextlib import closing

        from . import backlink_links as BLL
        from . import db
        with closing(db.connect(cfg.db_path)) as c:
            BLL.remove_import(c, site, source)
        ui.notify(f"Đã bỏ dữ liệu {SRC_NAME.get(source, source)} đã nhập", type="positive", position="bottom-right")
        refresh()

    async def safe_browsing() -> None:
        from contextlib import closing

        from nicegui import run

        from . import backlink_links as BLL
        from . import db
        from .cwv import load_key
        key = load_key(cfg)
        if not key:
            ui.notify("Chưa có Google API key (Owner nhập ở Cài đặt tích hợp)", type="warning", position="bottom-right")
            return

        def work():
            with closing(db.connect(cfg.db_path)) as c:
                return BLL.safe_check(c, site, key)
        try:
            r = await run.io_bound(work)
            ui.notify(f"Đã kiểm tra {r['checked']} URL: {r['flagged']} link từ website bị Google đánh dấu nguy hiểm",
                      type="warning" if r["flagged"] else "positive", position="bottom-right")
            refresh()
        except Exception as e:  # noqa: BLE001
            ui.notify(str(e)[:300], type="negative", position="bottom-right", multi_line=True, timeout=0,
                      close_button="Đóng")
    checks_box()

    if mode == "audit":
        with T.section(ui, "Link của mục đang chọn", "link"):
            ui.element("div").props('id="bl-audit-table"').style("position:relative; top:-80px")

            @ui.refreshable
            def tbl() -> None:
                c = by_key.get(st["f"]) if st["f"] else None
                if not c:
                    ui.label("Bấm một mục ở trên để xem danh sách link của mục đó.").classes("text-sm muted")
                    return
                T.filter_chip(ui, f"{c['title']} · {F.n(len(c['rows']))} link", lambda: set_filter(c["key"]))
                if c["key"] == "L_pbn" and c.get("groups"):
                    pbn_table(ui, user, c, st.setdefault("pbn", TK.new_state()), refresh)
                    with ui.expansion(f"Xem {F.n(len(c['rows']))} link cụ thể").props("dense").classes(
                            "w-full sr-au-fold"):
                        table(ui, user, c["rows"], st["kit"], on_label=refresh, export="backlink-audit-l_pbn")
                    return
                table(ui, user, c["rows"], st["kit"], on_label=refresh, export=f"backlink-audit-{c['key'].lower()}")
            tbl()
        return
    with T.section(ui, "Tất cả backlink", "link"):
        ui.element("div").props('id="bl-links-table"').style("position:relative; top:-80px")  # đích cuộn tới
        note = (f"Lấy lúc {_vn(data['fetched_at'])} · {F.n(len(items))} link"
                + (f" / {F.n(data['total'])} (lấy {F.n(len(items))} link uy tín cao nhất)"
                   if data.get("total") and data["total"] > len(items) else "")
                + (f" · so với lần lấy {_vn(data['prev']['fetched_at'])}" if data.get("prev") else ""))
        if A.is_client(user):  # khách hàng: chỉ ngày cập nhật và số link, không chuyện nhập file / giới hạn lấy
            note = f"Cập nhật {_vn(data['fetched_at'])} · {F.n(len(items))} link"
        for imp in [] if A.is_client(user) else data.get("imports") or []:
            note += (f" · gộp file {SRC_NAME.get(imp['source'], imp['source'])} nhập {_vn(imp['imported_at'])} "
                     f"({F.n(imp['count'])} link còn)")
        with ui.row().classes("w-full items-center no-wrap gap-2 q-mb-xs"):
            ui.label(note).classes("text-xs muted col")
            if ed:
                with ui.button(icon="upload_file").props("flat round dense color=grey-8"):
                    ui.tooltip("Nhập file backlink từ Semrush")
                    with ui.menu().props("auto-close"):
                        with ui.list().props("dense").style("min-width:240px"):
                            with ui.item(on_click=lambda: import_dialog(ui, cfg, user, refresh)).props("clickable"):
                                ui.item_section("Nhập dữ liệu Semrush (Backlinks, Referring Domains)")
                            for imp in data.get("imports") or []:
                                with ui.item(on_click=lambda _, s_=imp["source"]: drop_import(s_)).props("clickable"):
                                    ui.item_section(f"Bỏ dữ liệu {SRC_NAME.get(imp['source'], imp['source'])} đã nhập")
            if export:
                export()  # file đủ cột + audit theo link (mỗi mục một sheet)

        @ui.refreshable
        def tbl() -> None:
            c = by_key.get(st["f"]) if st["f"] else None
            shown = c["rows"] if c else items
            if c:
                T.filter_chip(ui, f"Đang lọc: {c['title']} · {F.n(len(shown))} {'link' if c['unit'] != 'website' else 'link'}",
                              lambda: set_filter(c["key"]))
                if c["key"] == "L_pbn" and c.get("groups"):
                    pbn_table(ui, user, c, st.setdefault("pbn", TK.new_state()), refresh)
                    with ui.expansion(f"Xem {F.n(len(shown))} link cụ thể").props("dense").classes(
                            "w-full sr-au-fold"):
                        table(ui, user, shown, st["kit"], on_label=refresh, export="backlink-tat-ca")
                    return
            table(ui, user, shown, st["kit"], on_label=refresh, export="backlink-tat-ca")
        tbl()


def import_dialog(ui, cfg, user, refresh) -> None:
    """Nhập dữ liệu Semrush: kéo thả nhiều file (Backlinks / Referring domains) của website mình và đối thủ. Tool tự
    nhận loại file và tên miền, người dùng sửa lại nếu sai, rồi bấm Nhập. Website mình · Backlinks: kiểm tra trang đích
    và Google Safe Browsing (miễn phí). File đối thủ: gộp vào Backlink GAP."""
    from contextlib import closing

    from nicegui import run

    from . import backlink_gap as BG
    from . import db
    from . import semrush as SR
    site = cfg.site_url
    own = SR.host(site)
    host = ui.context.client.layout  # thông báo / hẹn giờ gắn vào trang (hộp thoại đóng sẽ bị xóa)
    with closing(db.connect(cfg.db_path)) as c:
        rivals = BG.all_rivals(c, cfg)
    files: list[dict] = []
    role_opts = {"own": f"Website mình ({own})", **{f"rv:{r['domain']}": f"Đối thủ: {r['name']}" for r in rivals},
                 "new": "Đối thủ mới (thêm cho Backlink GAP)"}

    def role_of(pv: dict) -> str:
        if pv.get("role") == "own":
            return "own"
        if pv.get("role") == "rival":
            return "rv:" + next(r["domain"] for r in rivals if r["name"] == pv["rival"])
        return "new"

    async def got(e) -> None:
        data = await e.file.read()
        name = getattr(e.file, "name", "") or ""
        pv = SR.preview(data, name, site, rivals)
        files.append({"name": name, "data": data, "pv": pv, "role": role_of(pv), "owner": pv.get("owner") or ""})
        listing.refresh()

    with ui.dialog() as d, ui.card().style("width:780px; max-width:96vw; border-radius:14px"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("Nhập dữ liệu Semrush").classes("text-lg font-semibold col")
            ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
        ui.label("Kéo thả một hoặc nhiều file CSV xuất từ Semrush (Backlink Analytics): Backlinks và Referring Domains "
                 "của website mình và đối thủ. Tool tự nhận loại file và website; sửa lại nếu sai rồi bấm Nhập.").classes(
            "text-sm")
        ui.upload(on_upload=got, auto_upload=True, multiple=True, max_file_size=60_000_000,
                  label="Kéo thả hoặc chọn file .csv").props('accept=".csv" flat bordered').classes("w-full q-mt-sm")

        @ui.refreshable
        def listing() -> None:
            if not files:
                return
            with ui.column().classes("w-full gap-1 q-mt-sm"):
                for f in files:
                    pv = f["pv"]
                    with ui.row().classes("w-full items-center no-wrap gap-2 sr-qc-row"):
                        ui.icon("description", size="18px").classes("muted")
                        with ui.column().classes("gap-0 col").style("min-width:0"):
                            ui.label(f["name"] or "(không tên)").classes("text-sm ellipsis")
                            info = (pv.get("error") if not pv.get("kind") else
                                    f"{SR.KINDS[pv['kind']]} · {pv['rows']:,} dòng".replace(",", ".")
                                    + (f" · {pv['error']}" if pv.get("error") else ""))
                            ui.label(info).classes("text-xs " + ("text-negative" if pv.get("error") else "muted"))
                        if pv.get("kind"):
                            ui.input(value=f["owner"], on_change=lambda e, f=f: f.update(owner=e.value or "")).props(
                                "dense outlined").style("width:170px").tooltip("Tên miền của file")
                            ui.select(role_opts, value=f["role"], on_change=lambda e, f=f: f.update(role=e.value)).props(
                                "dense outlined options-dense").style("width:230px")
                        ui.button(icon="close", on_click=lambda _, f=f: (files.remove(f), listing.refresh())).props(
                            "flat round dense size=sm")
        listing()

        async def go() -> None:
            ok = [f for f in files if f["pv"].get("kind")]
            if not ok:
                ui.notify("Chưa có file nào đọc được", type="warning")
                return
            b_go.props("loading")

            def work():
                out, own_bl = [], False
                with closing(db.connect(cfg.db_path)) as c:
                    for f in ok:
                        role, owner = f["role"], SR.host(f["owner"])
                        if role == "own":
                            owner = own
                        elif role.startswith("rv:"):
                            owner = role[3:]
                            SR.set_name(c, site, owner, next(r["name"] for r in rivals if r["domain"] == owner))
                        else:
                            if not owner:
                                out.append(f"{f['name']}: chưa có tên miền")
                                continue
                            try:
                                BG.add_extra(c, cfg, owner, str(user))  # đối thủ mới: thêm vào danh sách GAP
                            except RuntimeError:
                                pass  # đã có
                            SR.set_name(c, site, owner, owner)
                        try:
                            r = SR.save(c, site, owner, f["pv"]["kind"], f["data"], f["name"], str(user))
                            n = r.get("count", 0)
                            out.append(f"{owner} · {SR.KINDS[f['pv']['kind']]}: {n:,} dòng".replace(",", "."))
                            own_bl = own_bl or (owner == own and f["pv"]["kind"] == "backlinks")
                        except ValueError as ex:
                            out.append(f"{f['name']}: {ex}")
                    BG.rebuild(c, site)
                return out, own_bl
            try:
                msgs, own_bl = await run.io_bound(work)
            except Exception as ex:  # noqa: BLE001
                b_go.props(remove="loading")
                ui.notify(f"Chưa nhập được: {str(ex)[:200]}", type="negative", multi_line=True)
                return
            d.close()
            with host:
                ui.notify("Đã nhập: " + " · ".join(msgs)[:400], type="positive", position="bottom-right",
                          multi_line=True, timeout=8000)
                if own_bl:
                    await _after_own_backlinks(ui, cfg)
                refresh()
        with ui.row().classes("w-full justify-end gap-2 q-mt-md"):
            ui.button("Hủy", on_click=d.close).props("flat no-caps")
            b_go = ui.button("Nhập", icon="upload", on_click=go).props("unelevated no-caps")
        ui.label("Sau khi nhập Backlinks của website mình, tool mở thử các trang đích (biết trang lỗi / chuyển hướng) và "
                 "hỏi Google Safe Browsing, đều miễn phí. File Semrush không có điểm spam theo link; Referring Domains "
                 "có IP và quốc gia (dùng cho mục nghi PBN).").classes("text-xs muted q-mt-xs")
    d.on("hide", d.delete)
    d.open()


async def _after_own_backlinks(ui, cfg) -> None:
    """Sau khi nhập Backlinks của website mình: kiểm tra trang đích và Safe Browsing (chạy nền, có tiến độ)."""
    from contextlib import closing

    from nicegui import run

    from . import backlink_links as BLL
    from . import db
    from .cwv import load_key
    site = cfg.site_url
    note = ui.notification("Đang kiểm tra trang đích của link vừa nhập…", spinner=True, timeout=None,
                           position="bottom-right")
    prog = {"d": 0, "t": 0}

    def show():
        if prog["t"]:
            note.message = f"Đang kiểm tra trang đích: {prog['d']}/{prog['t']} trang…"
    poll = ui.timer(2, show)

    def after():
        out = {}
        with closing(db.connect(cfg.db_path)) as c:
            out["targets"] = BLL.check_targets(c, site, progress=lambda i, n: prog.update(d=i, t=n))
            key = load_key(cfg)
            if key:
                try:
                    out["sb"] = BLL.safe_check(c, site, key)
                except Exception as ex:  # noqa: BLE001
                    out["sb_err"] = str(ex)
        return out
    try:
        r = await run.io_bound(after)
        ui.notify(f"Trang đích: {r['targets']['broken']} trang lỗi, {r['targets']['redirect']} trang chuyển hướng"
                  + (f" · Safe Browsing: {r['sb']['flagged']} link nguy hiểm" if r.get("sb") else ""),
                  caption=r.get("sb_err", "")[:200] or None, position="bottom-right", multi_line=True,
                  type="warning" if r.get("sb_err") else "positive")
    except Exception as ex:  # noqa: BLE001
        ui.notify(f"Chưa kiểm tra xong: {str(ex)[:200]}", type="warning", position="bottom-right")
    poll.cancel()
    note.dismiss()
