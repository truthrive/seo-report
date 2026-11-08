"""Hai ô chọn nhiều mục (Vue, chuẩn ARIA):

- MultiSelect: nút gọn hiện số đã chọn → danh sách tìm được, chọn / bỏ nhiều mục mà danh sách vẫn mở, mục đã chọn
  hiện thành chip có nút bỏ (multiselect.js).
- Transfer: hai khung có tiêu đề (Có thể chọn · Đã chọn), target_keys là các mục ở khung phải, nút chuyển chỉ bật khi
  có mục hợp lệ đã đánh dấu (transfer.js). Tương đương Ant Design Transfer.
"""
from typing import Any, Callable

from nicegui import ui
from nicegui.elements.mixins.value_element import ValueElement


class MultiSelect(ValueElement, component="multiselect.js"):
    VALUE_PROP = "value"
    LOOPBACK = False  # trình duyệt giữ lựa chọn; máy chủ nhận lại mỗi lần đổi

    def __init__(self, options: dict[Any, str], *, label: str, value: list | None = None, placeholder: str = "",
                 chips: bool = True, chips_when_all: bool = True, inline: bool = False, pop_right: bool = False,
                 on_change=None) -> None:
        super().__init__(value=list(value or []), on_value_change=on_change)
        self._props["options"] = [{"value": k, "label": v} for k, v in options.items()]
        self._props["label"] = label
        self._props["chips"] = chips
        self._props["chipsWhenAll"] = chips_when_all
        self._props["inline"] = inline
        self._props["popRight"] = pop_right
        if placeholder:
            self._props["placeholder"] = placeholder


class Transfer(ui.element, component="transfer.js"):
    def __init__(self, data: list[dict], target_keys: list, *, titles: tuple[str, str],
                 operations: tuple[str, str] = ("Thêm", "Bỏ"), empty_text: tuple[str, str] | None = None,
                 unit: str = "mục", max_target: int = 0,
                 on_change: Callable[[str, list, list], None] | None = None) -> None:
        """data: [{key, title, description?, disabled?}]. on_change(direction, move_keys, target_keys) được gọi khi
        bấm nút chuyển; máy chủ áp dụng rồi gọi set_data / set_target_keys để vẽ lại."""
        super().__init__()
        self._props["data"] = data
        self._props["targetKeys"] = list(target_keys)
        self._props["titles"] = list(titles)
        self._props["operations"] = list(operations)
        if empty_text:
            self._props["emptyText"] = list(empty_text)
        self._props["unit"] = unit
        self._props["max"] = max_target
        if on_change:
            self.on("change", lambda e: on_change(e.args["direction"], e.args["moveKeys"], e.args["targetKeys"]))

    def set_data(self, data: list[dict], target_keys: list) -> None:
        self._props["data"] = data
        self._props["targetKeys"] = list(target_keys)
        self.update()
