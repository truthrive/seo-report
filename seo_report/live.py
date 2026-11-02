"""Trang đang mở của từng người. Mỗi trang giữ quyền và cài đặt dự án (tạm ngưng, ngân sách) lúc dựng trang; khi chúng
đổi thì ngắt các trang liên quan: trình duyệt tải lại (kiểm tra quyền từ đầu) và phía server xóa trang cũ, nên các nút
của trang cũ không còn chạy được, kể cả khi trình duyệt cố giữ trang."""
import asyncio

_PAGES: dict[str, tuple[str, str]] = {}  # client id → (email, mã dự án)


def register(client, email: str, project: str) -> None:
    _PAGES[client.id] = (str(email).strip().lower(), project)
    client.on_delete(lambda: _PAGES.pop(client.id, None))


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
