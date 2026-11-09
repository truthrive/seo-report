"""Nhóm nút nổi góc dưới phải: nút + mở speed dial (3 thao tác có nhãn), nút chat (tùy chọn), nút về đầu trang
hiện khi cuộn quá 400px (fab.js)."""
from typing import Callable

from nicegui import ui


class FloatGroup(ui.element, component="fab.js"):
    def __init__(self, actions: list[dict], *, fab_label: str = "Thao tác nhanh", chat: dict | None = None,
                 on_action: Callable[[str], None] | None = None, on_chat: Callable[[], None] | None = None) -> None:
        """actions: [{key, icon, label, badge?}] (tối đa 3; rỗng = không có nút +). chat: {label, icon}."""
        super().__init__()
        self._props["actions"] = actions[:3]
        self._props["fabLabel"] = fab_label
        if chat:
            self._props["chat"] = chat
        if on_action:
            self.on("action", lambda e: on_action(e.args))
        if on_chat:
            self.on("chat", lambda _: on_chat())
