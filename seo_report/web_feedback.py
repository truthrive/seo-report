"""Yêu cầu hỗ trợ gửi tới đội SEO. Người gửi là người xem báo cáo với quyền "Khách hàng" (có thể là quản lý, team
nội bộ của bên dự án…), nên chữ trên giao diện không gọi họ là "khách".

- Người gửi: thao tác "Gửi yêu cầu" ở nút nổi mở hộp thoại (kèm tên trang đang xem); trang /yeu-cau ("Yêu cầu của tôi")
  liệt kê các yêu cầu đã gửi kèm trạng thái và câu trả lời của đội SEO.
- Đội SEO: trang /ho-tro ("Yêu cầu hỗ trợ") đọc, trả lời, đánh dấu đã xử lý.
"""
from datetime import datetime

from . import access as A
from . import feedback as FB
from . import ui_theme as T

SEG = "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"


def _local(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return f"{datetime.fromisoformat(iso).astimezone():%H:%M · %d/%m/%Y}"
    except ValueError:
        return iso


def _meta(ui, f: dict, client: bool = False) -> None:
    """Trạng thái (pill) · loại (tag) · giờ gửi · trang. Người gửi thấy "Đã gửi" thay cho "Mới" (mới với đội SEO)."""
    label, tone = FB.STATUS.get(f["status"], ("", "grey"))
    if client and f["status"] == "new":
        label, tone = "Đã gửi", "grey"
    with ui.row().classes("items-center gap-2").style("row-gap:4px"):
        T.pill(ui, label, tone)
        T.tag(ui, FB.CATEGORIES.get(f["category"], "Khác"), "grey")
        ui.label(_local(f["created_at"]) + (f" · trang {f['page']}" if f["page"] else "")).classes("sr-rq-time")


def _reply(ui, f: dict, waiting_text: bool = False) -> None:
    if f["reply"]:
        with ui.element("div").classes("sr-rq-reply"):
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.icon("support_agent", size="16px").props('aria-hidden="true"')
                ui.label("Đội SEO trả lời" + (f" · {_local(f['replied_at'])}" if f["replied_at"] else "")).classes(
                    "sr-rq-reply-head")
            ui.label(f["reply"]).classes("sr-rq-text")
    elif waiting_text:
        ui.label("Đội SEO đã tiếp nhận, sẽ trả lời tại đây." if f["status"] == "seen"
                 else "Đội SEO sẽ trả lời tại đây.").classes("sr-rq-wait")


def _filter(ui, rows: list[dict], state: dict, refresh, labels: dict[str, str]) -> list[dict]:
    counts = {"open": sum(f["status"] != "done" for f in rows), "done": sum(f["status"] == "done" for f in rows),
              "all": len(rows)}
    tg = ui.toggle({k: f"{v} · {counts[k]}" for k, v in labels.items()}, value=state["view"],
                   on_change=lambda e: (state.update(view=e.value), refresh())).props(SEG).classes("sr-seg")
    tg.props["aria-label"] = "Lọc yêu cầu"
    return [f for f in rows if state["view"] == "all" or (f["status"] == "done") == (state["view"] == "done")]


# ------------------------------------------------------------------ người gửi: hộp thoại gửi
def feedback_opener(ui, connect, user, page: str):
    """Trả về hàm open(category) mở hộp thoại gửi yêu cầu cho đội SEO (kèm trang đang xem), loại chọn sẵn."""
    path = ""
    try:
        req = ui.context.client.request
        path = req.url.path + (f"?{req.url.query}" if req.url.query else "")
    except Exception:  # noqa: BLE001
        pass

    def open_dialog(category: str = "question", on_sent=None) -> None:
        with ui.dialog() as dlg, ui.card().classes("sr-fb-card"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label("Gửi yêu cầu cho đội SEO").classes("text-lg font-semibold col")
                ui.button(icon="close", on_click=dlg.close).props('flat round dense aria-label="Đóng"')
            if page:
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.icon("description", size="16px").classes("muted").props('aria-hidden="true"')
                    ui.label(f"Đính kèm trang đang xem: {page}").classes("text-sm muted")
            ui.label("Loại yêu cầu").classes("sr-rq-field q-mt-sm")
            cat = ui.toggle(FB.CATEGORIES, value=category if category in FB.CATEGORIES else "question").props(
                SEG).classes("sr-seg sr-seg-wrap")
            cat.props["aria-label"] = "Loại yêu cầu"
            body = ui.textarea("Nội dung yêu cầu", placeholder="Ví dụ: số click tuần này khác với Search Console, "
                                                              "nhờ đội SEO kiểm tra giúp.").props(
                f"outlined counter maxlength={FB.MAX_LEN}").classes("w-full q-mt-sm")
            err = ui.label("").classes("text-sm text-negative")
            err.props["role"] = "alert"
            err.set_visibility(False)

            def send() -> None:
                try:
                    with connect() as c:
                        FB.add(c, str(user), body.value or "", page, path, cat.value)
                except ValueError as e:
                    err.text = str(e)
                    err.set_visibility(True)
                    return
                dlg.close()
                ui.notify("Đã gửi yêu cầu. Theo dõi trạng thái và câu trả lời ở mục Yêu cầu của tôi.",
                          type="positive", position="bottom-right", classes="sr-toast")
                if on_sent:
                    on_sent()
            with ui.row().classes("w-full items-center gap-2 q-mt-xs"):
                ui.link("Xem yêu cầu đã gửi →", "/yeu-cau").classes("sr-link text-sm")
                ui.space()
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Gửi yêu cầu", icon="send", on_click=send).props("unelevated no-caps color=primary")
        dlg.on("hide", lambda: dlg.delete())
        dlg.open()

    return open_dialog


# ------------------------------------------------------------------ người gửi: trang Yêu cầu của tôi
def build_my_requests_page(ui, cfg, connect, user) -> None:
    right = T.page_header(ui, "support_agent", "Yêu cầu của tôi",
                          "Câu hỏi, báo lỗi số liệu và đề xuất bạn đã gửi cho đội SEO, kèm trạng thái và câu trả lời.")
    open_dialog = feedback_opener(ui, connect, user, "")
    with right:
        ui.button("Gửi yêu cầu mới", icon="add", on_click=lambda: open_dialog(on_sent=body.refresh)).props(
            "unelevated no-caps no-wrap color=primary").style("white-space:nowrap")
    state = {"view": "all"}

    @ui.refreshable
    def body() -> None:
        with connect() as c:
            rows = FB.list_mine(c, str(user), limit=200)
        if not rows:
            T.empty_state(ui, "support_agent", "Bạn chưa gửi yêu cầu nào",
                          "Bấm “Gửi yêu cầu mới”, hoặc nút + ở góc màn hình khi đang xem báo cáo.")
            return
        with ui.row().classes("items-center gap-2 q-mb-sm"):
            shown = _filter(ui, rows, state, body.refresh,
                            {"all": "Tất cả", "open": "Đang xử lý", "done": "Đã xử lý"})
        if not shown:
            ui.label("Không có yêu cầu nào trong mục này.").classes("text-sm muted")
            return
        with ui.element("div").classes("sr-rq-list"):
            for f in shown:
                with ui.element("article").classes("sr-rq-item"):
                    _meta(ui, f, client=True)
                    ui.label(f["body"]).classes("sr-rq-text sr-rq-body")
                    _reply(ui, f, waiting_text=True)
    body()


# ------------------------------------------------------------------ đội SEO: trang Yêu cầu hỗ trợ
def build_feedback_page(ui, cfg, connect, user) -> None:
    ed = A.can_edit(user)
    T.page_header(ui, "support_agent", "Yêu cầu hỗ trợ",
                  "Câu hỏi, báo lỗi số liệu và đề xuất gửi từ trang báo cáo. Trả lời ở đây thì người gửi thấy "
                  "ngay ở mục Yêu cầu của tôi.")
    state = {"view": "open", "open_reply": None}

    @ui.refreshable
    def body() -> None:
        with connect() as c:
            rows = FB.list_all(c)
        n_new = sum(f["status"] == "new" for f in rows)
        with ui.row().classes("w-full items-center gap-3 q-mb-sm"):
            shown = _filter(ui, rows, state, body.refresh,
                            {"open": "Cần xử lý", "done": "Đã xử lý", "all": "Tất cả"})
            if n_new:
                ui.label(f"{n_new} yêu cầu mới chưa ai đọc").classes("sr-rq-new-note")
        if not shown:
            T.empty_state(ui, "support_agent", "Không có yêu cầu nào" if not rows else "Không có yêu cầu trong mục này",
                          "Người xem báo cáo gửi yêu cầu bằng nút + ở góc màn hình.")
            return
        with ui.element("div").classes("sr-rq-list"):
            for f in shown:
                item(f)
        with connect() as c:  # team đã mở trang: yêu cầu mới đang hiện chuyển sang "Đã tiếp nhận"
            FB.mark_seen(c, [f["id"] for f in shown if f["status"] == "new"])

    def item(f: dict) -> None:
        with ui.element("article").classes("sr-rq-item" + (" new" if f["status"] == "new" else "")):
            with ui.row().classes("w-full items-start no-wrap gap-3"):
                ui.label((f["author"] or "?")[:1].upper()).classes("sr-rq-avatar").props('aria-hidden="true"')
                with ui.column().classes("col gap-1").style("min-width:0"):
                    with ui.row().classes("items-baseline gap-2"):
                        ui.label(f["author"]).classes("sr-rq-author")
                    _meta(ui, f)
                if f["path"]:
                    ui.link("Mở trang", f["path"]).classes("sr-link text-xs").props(
                        f'aria-label="Mở trang {f["page"] or "người gửi đang xem"}"')
            ui.label(f["body"]).classes("sr-rq-text sr-rq-body")
            _reply(ui, f)
            if not ed:
                return
            if state["open_reply"] == f["id"]:
                composer(f)
                return
            with ui.row().classes("items-center gap-2 sr-rq-actions"):
                ui.button("Sửa câu trả lời" if f["reply"] else "Trả lời", icon="reply",
                          on_click=lambda f=f: (state.update(open_reply=f["id"]), body.refresh())).props(
                    "outline no-caps dense color=grey-9")
                if f["status"] != "done":
                    ui.button("Đánh dấu đã xử lý", icon="check", on_click=lambda f=f: status(f, "done")).props(
                        "flat no-caps dense color=positive")
                else:
                    ui.button("Mở lại", icon="undo", on_click=lambda f=f: status(f, "seen")).props(
                        "flat no-caps dense color=grey-8")

    def composer(f: dict) -> None:
        with ui.element("div").classes("sr-rq-composer"):
            ans = ui.textarea("Câu trả lời", value=f["reply"]).props(
                f"outlined autogrow autofocus maxlength={FB.MAX_LEN}").classes("w-full")
            done = ui.checkbox("Đánh dấu đã xử lý sau khi gửi", value=True).props("dense")

            def send() -> None:
                try:
                    with connect() as c:
                        FB.reply(c, f["id"], ans.value or "", str(user), done=bool(done.value))
                except ValueError as e:
                    ui.notify(str(e), type="warning", position="bottom-right", classes="sr-toast")
                    return
                state["open_reply"] = None
                ui.notify("Đã gửi câu trả lời" + (" · đã xử lý" if done.value else ""), type="positive",
                          position="bottom-right", classes="sr-toast")
                body.refresh()
            with ui.row().classes("w-full items-center justify-end gap-2"):
                ui.button("Hủy", on_click=lambda: (state.update(open_reply=None), body.refresh())).props(
                    "flat no-caps dense")
                ui.button("Gửi trả lời", icon="send", on_click=send).props("unelevated no-caps dense color=primary")

    def status(f: dict, s: str) -> None:
        with connect() as c:
            FB.set_status(c, f["id"], s)
        body.refresh()

    with ui.element("div").classes("w-full").style("max-width: 980px"):
        body()
