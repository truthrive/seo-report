"""Combobox có nhãn, đúng mẫu ARIA (combobox + listbox): gõ để lọc (không phân biệt dấu), ↓ ↑ Enter Escape.
Dùng thay ui.select(with_input=True) cho danh sách dài (vd vị trí tìm kiếm)."""
from typing import Any

from nicegui.elements.mixins.value_element import ValueElement


class Combobox(ValueElement, component="combobox.js"):
    VALUE_PROP = "value"
    LOOPBACK = False  # giá trị do trình duyệt giữ; máy chủ chỉ nhận lại khi người dùng chọn

    def __init__(self, options: dict[Any, str], *, label: str, value: Any = None, placeholder: str = "",
                 hint: str = "", limit: int = 60, on_change=None) -> None:
        """options: {giá trị: chữ hiện}. label: nhãn hiện trên ô (bắt buộc, cũng là tên đọc của ô)."""
        super().__init__(value=value, on_value_change=on_change)
        self._props["options"] = [{"value": k, "label": v} for k, v in options.items()]
        self._props["label"] = label
        self._props["placeholder"] = placeholder
        self._props["hint"] = hint
        self._props["limit"] = limit
