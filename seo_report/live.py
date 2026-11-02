"""Trang đang mở của từng người. Mỗi trang giữ quyền và cài đặt dự án (tạm ngưng, ngân sách) lúc dựng trang; khi chúng
đổi thì ngắt các trang liên quan: trình duyệt tải lại (kiểm tra quyền từ đầu) và phía server xóa trang cũ, nên các nút
của trang cũ không còn chạy được, kể cả khi trình duyệt cố giữ trang."""
import asyncio

_PAGES: dict[str, tuple[str, str]] = {}  # client id → (email, mã dự án)
_PENDING: dict[str, list[tuple[str, dict]]] = {}  # email → thông báo chưa gửi được (lúc đó không mở trang nào)


def register(client, email: str, project: str) -> None:
    _PAGES[client.id] = (str(email).strip().lower(), project)
    client.on_delete(lambda: _PAGES.pop(client.id, None))
    for message, opts in _PENDING.pop(_PAGES[client.id][0], []):  # việc chạy nền xong lúc đang chuyển trang
        _show(client, message, opts)


def notify(email: str, message: str, **opts) -> int:
    """Hiện thông báo trên mọi trang người này đang mở (việc chạy nền như check rank xong khi họ đã sang trang khác).
    Không mở trang nào thì giữ lại, hiện ở trang kế tiếp họ mở. Trả số trang đã hiện."""
    from nicegui import Client
    n = 0
    for cid in targets(email):
        client = Client.instances.get(cid)
        if client is not None and _show(client, message, opts):
            n += 1
    if not n:
        _PENDING.setdefault(str(email).strip().lower(), []).append((message, opts))
    return n


def _show(client, message: str, opts: dict) -> bool:
    try:
        from nicegui import ui
        with client:
            ui.notify(message, **opts)
        return True
    except Exception:  # noqa: BLE001  (trang vừa đóng)
        return False


def targets(email: str | None = None, project: str | None = None, keep: str | None = None) -> list[str]:
    e = str(email).strip().lower() if email is not None else None
    return [cid for cid, (who, p) in _PAGES.items()
            if (e is None or who == e) and (project is None or p == project) and cid != keep]


def kick(email: str | None = None, project: str | None = None, keep: str | None = None) -> int:
    """Ngắt trang của một người (email) và / hoặc mọi trang đang mở một dự án. keep: trang không ngắt (trang của
    chính người đang thao tác). Trả số trang bị ngắt."""
    from nicegui import Client, background_tasks
    ids = targets(email, project, keep)
    for cid in ids:
        _PAGES.pop(cid, None)
        client = Client.instances.get(cid)
        if client is None:
            continue
        try:
            client.run_javascript("location.reload()")
        except Exception:  # noqa: BLE001  (trang đã mất kết nối: vẫn xóa phía server)
            pass
        background_tasks.create(_drop(client))
    return len(ids)


async def _drop(client) -> None:
    await asyncio.sleep(1.5)  # đợi lệnh tải lại tới trình duyệt rồi mới xóa hẳn trang cũ phía server
    try:
        client.delete()
    except Exception:  # noqa: BLE001
        pass
