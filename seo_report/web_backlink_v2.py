"""Các tab của trang Backlink tính từ dữ liệu gộp (DataForSEO + file Semrush): Tổng quan (so sánh hai nguồn + việc cần
làm), Website trỏ về, Trang đích, Anchor text (cột tách theo nguồn), Nguồn dữ liệu (trạng thái, độ phủ, thay đổi giữa
hai lần nhập file)."""
from datetime import date
from urllib.parse import urlparse

from . import access as A
from . import ai_format as F
from . import backlink_agg as AG
from . import table_kit as TK
from . import ui_theme as T
from . import web_labels as WL

TOP_TODO = 4  # Tổng quan chỉ nêu mấy việc nặng nhất
LEVELS = {"high": ("Cần xử lý", "red", "error"), "medium": ("Nên xem", "amber", "warning"),
          "info": ("Tham khảo", "blue", "info"), "ok": ("Ổn", "green", "check_circle")}
ANCHOR_TYPE = {"brand": "Thương hiệu", "url": "URL", "keyword": "Từ khóa", "empty": "Trống / ảnh"}


def _vn(d) -> str:
    try:
        return f"{date.fromisoformat(str(d)[:10]):%d/%m/%Y}"
    except (TypeError, ValueError):
        return "–"


def _path(u: str) -> str:
    p = urlparse(u or "")
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def _pct(v) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def _src_text(src: list[str]) -> str:
    return " + ".join(AG.SRC.get(s_, s_) for s_ in src)


# ---------------------------------------------------------------- Tổng quan

def overview(ui, ld: dict | None, bl: dict | None, checks: list[dict], go, on_import=None) -> None:
    """So sánh số của DataForSEO, Semrush và gộp; việc cần làm (bấm sang tab Audit)."""
    items = (ld or {}).get("items") or []
    sm = AG.summary(items)
    has_sr = bool(sm["semrush"]["links"])
    now = (bl or {}).get("now") or {}
    with T.section(ui, "Số liệu theo nguồn", "compare_arrows",
                   "Số đếm từ danh sách link của từng nguồn; cột Gộp bỏ trùng giữa hai nguồn"):
        rows = [("Website trỏ về", "domains", F.n), ("Backlink", "links", F.n), ("Trang đích có link", "pages", F.n),
                ("Tỷ lệ dofollow", "dofollow", _pct), ("Link về trang chủ", "home", _pct), ("Link ảnh", "image", F.n)]
        data = [{"id": i, "metric": lab, "dfs": fmt(sm["dfs"][k]) if sm["dfs"]["links"] else "–",
                 "semrush": fmt(sm["semrush"][k]) if has_sr else "chưa nhập", "all": fmt(sm["all"][k])}
                for i, (lab, k, fmt) in enumerate(rows)]
        cols = [{"name": "metric", "label": "Chỉ số", "field": "metric", "align": "left"},
                {"name": "dfs", "label": "DataForSEO", "field": "dfs", "align": "right"},
                {"name": "semrush", "label": "Semrush", "field": "semrush", "align": "right"},
                {"name": "all", "label": "Gộp", "field": "all", "align": "right"}]
        ui.table(columns=cols, rows=data, row_key="id").props("flat dense").classes("w-full sr-bl-table")
        notes = []
        if now:
            notes.append(f"DataForSEO báo tổng {F.n(now.get('backlinks') or 0)} backlink từ "
                         f"{F.n(now.get('referring_domains') or 0)} website (số tổng, lấy ngày {_vn(now.get('day'))}); "
                         f"uy tín {now.get('rank') if now.get('rank') is not None else '–'}/1000, điểm spam "
                         f"{now.get('spam_score') if now.get('spam_score') is not None else '–'}/100")
        cov = sm["cover"]["domains"]
        if has_sr:
            notes.append(f"Website: {F.n(cov['both'])} cả hai nguồn cùng thấy · {F.n(cov['dfs_only'])} chỉ DataForSEO · "
                         f"{F.n(cov['semrush_only'])} chỉ Semrush (xem tab Nguồn dữ liệu)")
        for n_ in notes:
            ui.label(n_).classes("text-xs muted q-mt-xs")
        if not has_sr and on_import:  # chưa có Semrush: mời nhập ngay tại chỗ
            with ui.row().classes("items-center gap-2 q-mt-sm"):
                ui.label("Có file Semrush? Nhập để gộp thêm website / backlink mà DataForSEO chưa thấy.").classes(
                    "text-xs muted")
                ui.button("Nhập dữ liệu Semrush", icon="upload_file", on_click=on_import).props(
                    "outline no-caps dense color=grey-9")
    todo = [c for c in checks if c["level"] in ("high", "medium") and c.get("count")]
    show = todo[:TOP_TODO]  # đã xếp nặng trước; phần còn lại xem ở tab Audit cho khỏi lặp cả danh sách
    with T.section(ui, "Việc cần làm trước", "fact_check",
                   (f"{len(show)} việc nặng nhất trong {len(todo)} việc · bấm để xem ở tab Audit" if len(todo) > len(show)
                    else f"{len(todo)} việc · bấm để xem ở tab Audit") if todo else "Không có việc gấp"):
        if not todo:
            ui.label("Audit không thấy vấn đề cần xử lý.").classes("text-sm muted")
        with ui.element("div").classes("sr-au-todo"):
            for c in show:
                label, tone, icon = LEVELS[c["level"]]
                row = ui.element("button").classes("sr-au-todo-row").props('type="button"')
                row.on("click", lambda _, k=c["key"]: go("audit", k))
                with row:
                    T.status_chip(ui, label, tone, icon)
                    ui.label(c["title"]).classes("text-sm font-semibold").style("flex:1 1 0; text-align:left")
                    num = f"{c['count']}{c['unit']}" if c["unit"].startswith("%") else f"{F.n(c['count'])} {c['unit']}"
                    ui.label(num).classes("num text-sm font-semibold")
                    ui.icon("chevron_right", size="18px").style("color:#8C8A7E")
        if len(todo) > len(show):
            ui.button(f"Xem {len(todo) - len(show)} việc còn lại ở tab Audit", icon="fact_check",
                      on_click=lambda: go("audit", todo[len(show)]["key"])).props(
                "flat no-caps dense color=primary").classes("q-mt-xs")


# ---------------------------------------------------------------- Website trỏ về / Trang đích / Anchor

def domains_panel(ui, user, items: list[dict], kit: dict, on_label, open_links) -> None:
    rows = []
    for i, g in enumerate(AG.domains(items)):
        rows.append({"k": g["domain"], "domain": g["domain"], "links": g["links"], "dfs": g.get("dfs", 0),
                     "semrush": g.get("semrush", 0), "dofollow": g["dofollow"], "rank": g["rank"] or None,
                     "ascore": g["ascore"], "spam": g["spam"], "country": g["country"], "ip": g["ip"],
                     "targets": g["targets"], "first_iso": g["first"] or "", "first": _vn(g["first"]),
                     "src": _src_text(g["src"]), "src_l": [AG.SRC[s_] for s_ in g["src"]],
                     "df": "Có dofollow" if g["dofollow"] else "Chỉ nofollow", "danger": g["threat"]})
    WL.enrich(rows, "domain", user)
    cl = A.is_client(user)
    if cl:  # khách hàng: dòng phụ chỉ còn quốc gia, không nguồn dữ liệu / cảnh báo audit
        for r in rows:
            r.update(src="", dfs=0, semrush=0, danger=False)
    cols = [{"name": "domain", "label": "Website", "field": "domain", "align": "left", "sortable": True}, WL.COLUMN,
            {"name": "links", "label": "Số link", "field": "links", "align": "right", "sortable": True,
             "width": 170},
            {"name": "dofollow", "label": "Dofollow", "field": "dofollow", "align": "right", "sortable": True,
             "width": 90},
            {"name": "rank", "label": "Uy tín (DFS)", "field": "rank", "align": "right", "sortable": True, "width": 105},
            {"name": "ascore", "label": "Ascore", "field": "ascore", "align": "right", "sortable": True, "width": 85},
            {"name": "targets", "label": "Trang đích", "field": "targets", "align": "right", "sortable": True,
             "width": 95},
            {"name": "first", "label": "Thấy lần đầu", "field": "first_iso", "align": "left", "sortable": True,
             "width": 115},
            {"name": "act", "label": "", "field": "k", "align": "left", "width": 96, "sortable": False}]
    if not cl:
        cols.insert(6, {"name": "spam", "label": "Spam", "field": "spam", "align": "right", "sortable": True,
                        "width": 75})
    else:  # khách hàng: bỏ cột nhãn nội bộ, dofollow, Ascore (Semrush); "Uy tín" không kèm tên nguồn
        cols = [c_ for c_ in cols if c_["name"] not in ("labels", "dofollow", "ascore")]
        next(c_ for c_ in cols if c_["name"] == "rank")["label"] = "Uy tín"
    TK.table(ui, columns=cols, rows=rows, row_key="k", st=kit, noun="website", classes="sr-kw-tbl", page_size=25,
             filters=[("text", "Website", ["domain"]), ("num", "Số link", "links"), ("num", "Uy tín", "rank"),
                      ("enum", "Quốc gia", "country"), ("date", "Thấy lần đầu", "first_iso")] if cl else
                     [("text", "Website", ["domain"]), ("num", "Số link", "links"), ("num", "Uy tín (DFS)", "rank"),
                      ("num", "Ascore", "ascore"), ("num", "Điểm spam", "spam"),
                      ("enum", "Nguồn dữ liệu", "src_l"), ("enum", "Loại link", "df"), ("enum", "Quốc gia", "country"),
                      WL.FILTER, ("date", "Thấy lần đầu", "first_iso")],
             actions=WL.action(ui, user, "domain", on_label), export="backlink-website",
             events={"drill": lambda e: open_links("domain", e.args), **WL.events(ui, user, on_label)},
             copy=[("Website", "domain"), ("Số link", "links"), ("Uy tín", "rank"), ("Trang đích", "targets"),
                   ("Quốc gia", "country"), ("Thấy lần đầu", "first_iso")] if cl else
                  [("Website", "domain"), WL.COPY, ("Nguồn", "src"), ("Số link", "links"), ("Link DataForSEO", "dfs"),
                   ("Link Semrush", "semrush"), ("Dofollow", "dofollow"), ("Uy tín (DFS)", "rank"), ("Ascore", "ascore"),
                   ("Điểm spam", "spam"), ("Trang đích", "targets"), ("Quốc gia", "country"),
                   ("IP", "ip"), ("Thấy lần đầu", "first_iso")],
             slots={
                 "body-cell-domain": """
                <q-td :props="props"><a :href="'https://' + props.row.domain" target="_blank" rel="noopener"
                  class="sr-bb-link">{{ props.row.domain }}</a>
                  <span v-if="props.row.danger" class="sr-bl-type k-lost q-ml-xs">Google cảnh báo</span>
                  <div class="sr-bb-sub">{{ [props.row.src, props.row.country].filter(Boolean).join(' · ') }}
                  </div></q-td>""",
                 "body-cell-labels": WL.SLOT,
                 "body-cell-links": """
                <q-td :props="props"><span class="num">{{ props.row.links }}</span>
                  <div v-if="props.row.dfs && props.row.semrush" class="sr-bb-sub">{{ props.row.dfs }} DataForSEO ·
                  {{ props.row.semrush }} Semrush</div></q-td>""",
                 "body-cell-first": """<q-td :props="props">{{ props.row.first }}</q-td>""",
                 "body-cell-act": """
                <q-td :props="props" style="overflow:visible"><q-btn flat dense no-caps size="sm" color="primary"
                  label="Xem link" class="q-px-xs" @click.stop="$parent.$emit('drill', props.row.k)"/></q-td>"""})


def pages_panel(ui, user, items: list[dict], kit: dict, open_links) -> None:
    rows = []
    for g in AG.pages(items):
        st = g["status"]
        rows.append({"k": g["page"], "page": _path(g["page"]), "url": g["page"], "domains": g["domains"],
                     "dfs": g["dfs"], "semrush": g["semrush"], "links": g["links"], "dofollow": g["dofollow"],
                     "status": st, "redir": g["redir"],
                     "state": ("Trang lỗi" if st and st >= 400 else "Chuyển hướng" if st and 300 <= st < 400 else
                               "Bình thường" if st else "Chưa rõ")})
    cl = A.is_client(user)
    for r in rows:  # khách hàng: một số website gộp, không tách theo nguồn dữ liệu
        r["split"] = not cl
    cols = [{"name": "page", "label": "Trang đích", "field": "page", "align": "left", "sortable": True},
            {"name": "domains", "label": "Website (DFS / Semrush)", "field": "domains", "align": "right",
             "sortable": True, "width": 170},
            {"name": "links", "label": "Backlink", "field": "links", "align": "right", "sortable": True, "width": 95},
            {"name": "dofollow", "label": "Dofollow", "field": "dofollow", "align": "right", "sortable": True,
             "width": 90},
            {"name": "state", "label": "Tình trạng", "field": "state", "align": "left", "sortable": True, "width": 125},
            {"name": "act", "label": "", "field": "k", "align": "left", "width": 96, "sortable": False}]
    if cl:  # khách hàng: bỏ dofollow và tình trạng trang (mã lỗi / chuyển hướng)
        cols = [c_ for c_ in cols if c_["name"] not in ("dofollow", "state")]
        cols[1]["label"] = "Website trỏ về"
    TK.table(ui, columns=cols, rows=rows, row_key="k", st=kit, noun="trang", classes="sr-kw-tbl", page_size=25,
             filters=[("text", "Trang đích", ["page"]), ("num", "Số website", "domains"), ("num", "Backlink", "links")]
             + ([] if cl else [("enum", "Tình trạng", "state")]),
             export="backlink-trang-dich", events={"drill": lambda e: open_links("page", e.args)},
             copy=[("Trang đích", "url"), ("Website trỏ về", "domains"), ("Backlink", "links")] if cl else
                  [("Trang đích", "url"), ("Website trỏ về", "domains"), ("Website DataForSEO", "dfs"),
                   ("Website Semrush", "semrush"), ("Backlink", "links"), ("Dofollow", "dofollow"),
                   ("Mã trạng thái", "status"), ("Chuyển hướng tới", "redir"), ("Tình trạng", "state")],
             slots={
                 "body-cell-page": """
                <q-td :props="props"><a :href="props.row.url" target="_blank" rel="noopener" class="sr-bb-link ellipsis"
                  style="max-width:100%" :title="props.row.url">{{ props.row.page }}</a></q-td>""",
                 "body-cell-domains": """
                <q-td :props="props"><span class="num">{{ props.row.domains }}</span>
                  <span v-if="props.row.split" class="sr-bb-sub q-ml-xs">{{ props.row.dfs }} / {{ props.row.semrush }}
                  </span></q-td>""",
                 "body-cell-state": """
                <q-td :props="props"><span :class="props.row.status >= 400 ? 'sr-bl-type k-lost' : ''">
                  {{ props.row.state }}{{ props.row.status && props.row.status !== 200 ? ' · ' + props.row.status : '' }}
                  </span></q-td>""",
                 "body-cell-act": """
                <q-td :props="props" style="overflow:visible"><q-btn flat dense no-caps size="sm" color="primary"
                  label="Xem link" class="q-px-xs" @click.stop="$parent.$emit('drill', props.row.k)"/></q-td>"""})


def anchors_panel(ui, items: list[dict], brand_terms: list[str], kit: dict, open_links, client: bool = False) -> None:
    """client (khách hàng): cột website không tách theo nguồn dữ liệu, không câu hướng dẫn tối ưu anchor."""
    rs = AG.anchors(items, brand_terms)
    mix = AG.anchor_mix(rs)
    with ui.element("div").classes("sr-bl-mix q-mb-sm"):
        for t, lab in ANCHOR_TYPE.items():
            ui.html(f"<span class='sr-bl-type'>{lab}</span> <b class='num'>{mix.get(t, 0) * 100:.0f}%</b>")
    rows = [{"k": r["anchor"], "anchor": r["anchor"] or "(trống / ảnh)", "type": ANCHOR_TYPE[r["type"]],
             "domains": r["domains"], "dfs": r["dfs"], "semrush": r["semrush"], "links": r["links"],
             "share": f"{r['share'] * 100:.1f}%".replace(".", ","), "share_n": r["share"],
             "first_iso": r["first"] or "", "first": _vn(r["first"]), "split": not client} for r in rs]
    cols = [{"name": "anchor", "label": "Anchor", "field": "anchor", "align": "left", "sortable": True},
            {"name": "type", "label": "Loại", "field": "type", "align": "left", "sortable": True, "width": 115},
            {"name": "domains", "label": "Website trỏ về" if client else "Website (DFS / Semrush)", "field": "domains",
             "align": "right", "sortable": True, "width": 170},
            {"name": "share", "label": "Tỷ lệ", "field": "share_n", "align": "right", "sortable": True, "width": 80},
            {"name": "links", "label": "Backlink", "field": "links", "align": "right", "sortable": True, "width": 95},
            {"name": "act", "label": "", "field": "k", "align": "left", "width": 96, "sortable": False}]
    TK.table(ui, columns=cols, rows=rows, row_key="k", st=kit, noun="anchor", classes="sr-kw-tbl", page_size=25,
             filters=[("text", "Anchor", ["anchor"]), ("num", "Số website", "domains"), ("enum", "Loại anchor", "type")],
             export="backlink-anchor", events={"drill": lambda e: open_links("anchor", e.args)},
             copy=[("Anchor", "anchor"), ("Loại", "type"), ("Website", "domains"),
                   *([] if client else [("Website DataForSEO", "dfs"), ("Website Semrush", "semrush")]),
                   ("Tỷ lệ", "share"), ("Backlink", "links"), ("Thấy lần đầu", "first_iso")],
             slots={
                 "body-cell-anchor": """
                <q-td :props="props"><div class="ellipsis" :title="props.row.anchor">{{ props.row.anchor }}</div></q-td>""",
                 "body-cell-domains": """
                <q-td :props="props"><span class="num">{{ props.row.domains }}</span>
                  <span v-if="props.row.split" class="sr-bb-sub q-ml-xs">{{ props.row.dfs }} / {{ props.row.semrush }}
                  </span></q-td>""",
                 "body-cell-share": """<q-td :props="props">{{ props.row.share }}</q-td>""",
                 "body-cell-act": """
                <q-td :props="props" style="overflow:visible"><q-btn flat dense no-caps size="sm" color="primary"
                  label="Xem link" class="q-px-xs" @click.stop="$parent.$emit('drill', props.row.k)"/></q-td>"""})
    if client:
        return
    ui.label("Tỷ lệ tính trên số website dùng anchor. Hồ sơ tự nhiên có nhiều anchor thương hiệu / URL; anchor từ khóa "
             "chiếm quá nửa là dấu hiệu tối ưu quá mức.").classes("text-xs muted q-mt-xs")


# ---------------------------------------------------------------- Nguồn dữ liệu

def sources(ui, cfg, user, connect, ld: dict | None, bl: dict | None, st: dict, due, refresh, fetch_btn) -> None:
    """Trạng thái từng nguồn, độ phủ (website chỉ một nguồn thấy), thay đổi giữa hai lần nhập file Semrush."""
    from . import backlinks as BL
    from . import semrush as SR
    from .web_backlink_links import import_dialog
    ed = A.can_edit(user)
    site = cfg.site_url
    own = SR.host(site)
    items = (ld or {}).get("items") or []
    with connect() as c:
        sr_own_bl = SR.latest(c, site, own, "backlinks")
        sr_own_rd = SR.latest(c, site, own, "refdomains")
        owners_ = [o for o in SR.owners(c, site) if o["owner"] != own]
        nm = SR.names(c, site)
        spent = BL.spent_this_month(c, date.today())
    now = (bl or {}).get("now") or {}
    with ui.element("div").classes("sr-bl-two w-full"):
        with T.section(ui, "DataForSEO", "cloud_sync", "Tự lấy theo lịch, tốn phí theo lượt gọi"):
            dfs_items = [x for x in items if "dfs" in (x.get("src") or ["dfs"])]
            lines = [f"Lần lấy gần nhất: {_vn(now.get('day'))}" if now else "Chưa lấy lần nào",
                     f"Số tổng: {F.n(now.get('backlinks') or 0)} backlink · {F.n(now.get('referring_domains') or 0)} "
                     "website" if now else "",
                     f"Danh sách link: {F.n(len(dfs_items))} link · {F.n(len({x['d_from'] for x in dfs_items}))} website",
                     ("Tạm ngưng tự lấy" if st["paused"] else f"{BL.EVERY_CHOICES[st['every_days']]} · lần tới {due:%d/%m}")
                     if st else "", "" if A.is_member(user) or A.is_client(user) else
                     f"Chi phí backlink tháng này: {spent:.2f} USD".replace(".", ",")]
            for ln in [x for x in lines if x]:
                ui.label(ln).classes("text-sm")
            if fetch_btn:
                with ui.row().classes("q-mt-sm"):
                    fetch_btn()
        with T.section(ui, "Semrush (file nhập)", "upload_file", "Nhập tay file xuất từ Semrush, miễn phí"):
            if sr_own_bl or sr_own_rd:
                if sr_own_bl:
                    ui.label(f"Backlinks của {own}: {F.n(len(sr_own_bl['items']))} link còn · nhập "
                             f"{_vn(sr_own_bl['imported_at'])}").classes("text-sm")
                if sr_own_rd:
                    ui.label(f"Referring domains của {own}: {F.n(len(sr_own_rd['items']))} website · nhập "
                             f"{_vn(sr_own_rd['imported_at'])}").classes("text-sm")
            else:
                ui.label(f"Chưa nhập file nào của {own}.").classes("text-sm muted")
            for o in owners_:
                ui.label(f"Đối thủ {nm.get(o['owner'], o['owner'])}: {SR.KINDS[o['kind']]} · {F.n(o['count'] or 0)} "
                         f"dòng · nhập {_vn(o['imported_at'])}").classes("text-sm")
            if ed:
                with ui.row().classes("q-mt-sm gap-2"):
                    ui.button("Nhập dữ liệu Semrush", icon="upload_file",
                              on_click=lambda: import_dialog(ui, cfg, user, refresh)).props("unelevated no-caps")

    # ---- độ phủ
    if items:
        sm = AG.summary(items)
        cov_d, cov_l = sm["cover"]["domains"], sm["cover"]["links"]
        with T.section(ui, "Độ phủ của từng nguồn", "join_inner",
                       "Mỗi công cụ có kho dữ liệu riêng: gộp hai nguồn thì thấy đủ hơn"):
            data = [{"id": 0, "what": "Website trỏ về", "both": F.n(cov_d["both"]), "dfs": F.n(cov_d["dfs_only"]),
                     "semrush": F.n(cov_d["semrush_only"]), "all": F.n(sum(cov_d.values()))},
                    {"id": 1, "what": "Backlink", "both": F.n(cov_l["both"]), "dfs": F.n(cov_l["dfs_only"]),
                     "semrush": F.n(cov_l["semrush_only"]), "all": F.n(sum(cov_l.values()))}]
            ui.table(columns=[{"name": "what", "label": "", "field": "what", "align": "left"},
                              {"name": "both", "label": "Cả hai cùng thấy", "field": "both", "align": "right"},
                              {"name": "dfs", "label": "Chỉ DataForSEO", "field": "dfs", "align": "right"},
                              {"name": "semrush", "label": "Chỉ Semrush", "field": "semrush", "align": "right"},
                              {"name": "all", "label": "Gộp", "field": "all", "align": "right"}],
                     rows=data, row_key="id").props("flat dense").classes("w-full sr-bl-table")
            ui.label("Danh sách website theo nguồn: tab Website trỏ về, lọc “Nguồn dữ liệu”.").classes(
                "text-xs muted q-mt-xs")

    # ---- thay đổi giữa hai lần nhập file
    changes = []
    if sr_own_bl:
        ch = AG.import_changes(sr_own_bl["items"], sr_own_bl["prev_items"], "d_from")
        if ch:
            changes.append((f"Backlinks của {own}", ch, "website trỏ về mình"))
    if sr_own_rd:
        ch = AG.import_changes(sr_own_rd["items"], sr_own_rd["prev_items"], "domain")
        if ch:
            changes.append((f"Referring domains của {own}", ch, "website trỏ về mình"))
    with connect() as c:
        for o in owners_:
            d = SR.latest(c, site, o["owner"], o["kind"])
            ch = AG.import_changes(d["items"], d["prev_items"], "domain" if o["kind"] == "refdomains" else "d_from")
            if ch:
                changes.append((f"{SR.KINDS[o['kind']]} của {nm.get(o['owner'], o['owner'])}", ch,
                                "website trỏ về đối thủ"))
    with T.section(ui, "Thay đổi giữa hai lần nhập file", "difference",
                   "So lần nhập file Semrush mới nhất với lần trước của cùng loại file"):
        if not changes:
            ui.label("Cần nhập ít nhất hai lần cùng một loại file (ví dụ file tháng này và tháng trước) để so.").classes(
                "text-sm muted")
        for title, ch, what in changes:
            with ui.expansion(f"{title}: +{len(ch['new'])} mới · −{len(ch['lost'])} không còn",
                              icon="compare_arrows").props("dense").classes("w-full"):
                if ch["new"]:
                    ui.label(f"Mới ({len(ch['new'])} {what}): " + ", ".join(ch["new"][:60])
                             + (" …" if len(ch["new"]) > 60 else "")).classes("text-xs")
                if ch["lost"]:
                    ui.label(f"Không còn ({len(ch['lost'])}): " + ", ".join(ch["lost"][:60])
                             + (" …" if len(ch["lost"]) > 60 else "")).classes("text-xs q-mt-xs")
