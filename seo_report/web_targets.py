"""Tab "URL mục tiêu" ở màn Quản lý URL: team gán URL mục tiêu cho từng từ khóa check rank (mọi bộ). Từ khóa ở bộ Cam
kết đi theo sheet: sửa ở màn Từ khóa & rank (tool ghi lên sheet) hoặc trên sheet; tool không tự gán."""
from . import keywords as K
from . import rank as R
from .web_rank import SOURCES


def build_target_panel(ui, cfg, connect, user: str, site: str) -> None:
    from . import ui_theme as T

    state = {"kw": None}

    def short(url):
        return (url or "").replace(site.rstrip("/"), "") or ("/" if url else "")

    ui.label("URL mục tiêu là trang bạn muốn xếp hạng cho từ khóa. Tool không tự gán: từ khóa cam kết lấy URL trong "
             "sheet Từ khóa cam kết, từ khóa khác do team gán ở đây.").classes("text-sm muted")
    with ui.row().classes("items-end gap-3"):
        search = ui.input("Tìm từ khóa").props("clearable dense outlined").classes("w-72")
        only_empty = ui.checkbox("Chỉ từ khóa chưa có URL mục tiêu", on_change=lambda: refresh()).props("dense")
    table = ui.table(columns=[
        {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
        {"name": "set", "label": "Bộ", "field": "set", "align": "left", "sortable": True},
        {"name": "source", "label": "Nguồn", "field": "source", "align": "left", "sortable": True},
        {"name": "top", "label": "Top mục tiêu", "field": "top", "align": "center"},
        {"name": "target", "label": "URL mục tiêu", "field": "target", "align": "left"},
        {"name": "ranking", "label": "URL đang xếp hạng", "field": "ranking", "align": "left"},
        {"name": "edit", "label": "", "field": "id", "align": "center"},
    ], rows=[], row_key="id", pagination=50).classes("w-full").props("flat bordered dense")
    search.bind_value(table, "filter")
    table.add_slot("body-cell-target", """
        <q-td :props="props">
          <div class="row no-wrap items-center" style="gap: 4px; max-width: 320px">
            <span v-if="props.value" class="ellipsis" :title="props.row.target_full">{{ props.value }}</span>
            <span v-else class="muted">chưa gán</span>
            <q-icon v-if="props.row.locked" name="lock" size="14px" color="grey-6">
              <q-tooltip>Từ khóa cam kết: sửa ở màn Từ khóa &amp; rank (tab Cam kết), tool ghi lên sheet</q-tooltip>
            </q-icon>
          </div>
        </q-td>""")
    table.add_slot("body-cell-ranking", """
        <q-td :props="props">
          <div class="row no-wrap items-center" style="gap: 4px; max-width: 280px">
            <span class="ellipsis" :title="props.row.ranking_full">{{ props.value }}</span>
            <q-icon v-if="props.row.wrong" name="warning" color="orange-8" size="16px">
              <q-tooltip>Google đang xếp hạng URL khác URL mục tiêu</q-tooltip>
            </q-icon>
          </div>
        </q-td>""")
    table.add_slot("body-cell-edit", """
        <q-td :props="props" class="text-center">
          <q-btn v-if="!props.row.locked" flat dense round size="sm" icon="edit" aria-label="Gán URL mục tiêu"
                 @click="() => $parent.$emit('edit', props.row)"><q-tooltip>Gán URL mục tiêu</q-tooltip></q-btn>
        </q-td>""")
    table.on("edit", lambda e: open_edit(e.args))

    with ui.dialog() as dialog, ui.card().style("min-width: 560px; border-radius: 14px"):
        title = ui.label().classes("text-lg font-semibold")
        ui.label("Chọn một gợi ý (trang có click / hiển thị cho từ khóa này trên GSC 90 ngày qua, hoặc URL Google "
                 "đang xếp hạng), hoặc dán URL.").classes("text-sm muted")
        picks = ui.column().classes("w-full gap-1")
        url_in = ui.input("URL mục tiêu", placeholder=f"https://{R.domain(site)}/trang-muc-tieu/").props(
            "outlined dense clearable").classes("w-full")
        err = ui.label().classes("text-sm").style(f"color:{T.RED}")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Hủy", on_click=dialog.close).props("flat no-caps")
            ui.button("Bỏ URL mục tiêu", on_click=lambda: save("")).props("flat no-caps color=negative")
            ui.button("Lưu", on_click=lambda: save(url_in.value)).props("unelevated no-caps")

    def open_edit(row: dict):
        state["kw"] = row
        title.text = f"URL mục tiêu: {row['keyword']}"
        url_in.value = row["target_full"]
        err.text = ""
        with connect() as c:
            sug = R.url_suggestions(c, site, row["keyword"], K.latest_date(c, site))
        options = [(s_["url"], f"{s_['clicks']:,} click · {s_['impressions']:,} hiển thị".replace(",", "."))
                   for s_ in sug]
        if row["ranking_full"] and row["ranking_full"] not in [u for u, _ in options]:
            options.insert(0, (row["ranking_full"], "Google đang xếp hạng URL này"))
        picks.clear()
        with picks:
            if not options:
                ui.label("Chưa có gợi ý cho từ khóa này.").classes("text-xs muted")
            for url, note in options:
                with ui.row().classes("w-full items-center no-wrap gap-2 sr-pick"):
                    ui.button(icon="north_west", on_click=lambda u=url: url_in.set_value(u)).props(
                        "flat dense round size=sm").tooltip("Dùng URL này")
                    lab = ui.label(short(url)).classes("text-sm ellipsis col")
                    lab.props["title"] = url  # gán thẳng, không ghép vào chuỗi props
                    ui.label(note).classes("text-xs muted")
        dialog.open()

    def save(value: str):
        from .access import can_edit
        if not can_edit(user) or not state["kw"] or state["kw"]["locked"]:
            return
        try:
            with connect() as c:
                R.set_target_url(c, site, state["kw"]["id"], value, user)
        except ValueError as e:
            err.text = str(e)
            return
        dialog.close()
        ui.notify("Đã bỏ URL mục tiêu" if not (value or "").strip() else "Đã lưu URL mục tiêu", type="positive")
        refresh()

    def refresh():
        with connect() as c:
            kws = R.keywords(c, site, K.latest_date(c, site))
        rows = []
        for k in kws:
            if only_empty.value and k["target_url"]:
                continue
            rows.append({
                "id": k["id"], "keyword": k["keyword"], "set": k["set_name"],
                "source": "Cam kết" if k["set_kind"] == "kpi" else SOURCES.get(k["source"], k["source"]),
                "top": f"Top {k['top_target']}" if k.get("top_target") else "",
                "target": short(k["target_url"]), "target_full": k["target_url"] or "",
                "locked": k["set_kind"] == "kpi",
                "ranking": short(k["ranking_url"]), "ranking_full": k["ranking_url"] or "",
                "wrong": bool(k["target_url"] and k["ranking_url"] and k["ranking_url"] != k["target_url"]),
            })
        table.rows = rows

    refresh()
