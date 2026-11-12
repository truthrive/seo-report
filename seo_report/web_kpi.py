"""Màn Cam kết KPI (Quản trị) và khối "Tiến độ KPI" trên Tổng quan / báo cáo. Số cam kết đọc từ Google Sheet; mỗi cam
kết là một dòng (kpi.py), màn hình vẽ một ô cho mỗi dòng."""
from contextlib import closing
from html import escape
from datetime import date

from . import access as A
from . import ai_format as F
from . import kpi as KP
from . import ui_theme as T

ICONS = {"green": "check_circle", "amber": "error_outline", "red": "error_outline", "grey": "hourglass_empty"}
KT_STYLE = (".sr-kt{width:100%;border-collapse:collapse;font-size:13px}.sr-kt th{background:#F3F3ED;color:#1F221E;"
            "font-weight:600;padding:8px;text-align:center}.sr-kt th .d{font-weight:400;font-size:11px;opacity:.75}"
            ".sr-kt td{padding:7px 8px;border-bottom:1px solid #EEECE4;text-align:center}.sr-kt td.lab{text-align:left;"
            "font-weight:600;white-space:nowrap}.sr-kt tr.sub td{background:#FAFAF7}.sr-kt tr.sub td.lab{font-weight:400;"
            "color:#6B6A5E;padding-left:20px}.sr-kt td .d{font-size:11px;color:#6B6A5E}.sr-kt th .d{color:#6B6A5E}.sr-kt .ok{color:#1E7C31;"
            "font-weight:700}.sr-kt .bad{color:#C2410C;font-weight:700}.sr-kt .warn{color:#8F5F14;font-weight:700}"
            ".sr-kt .mut{color:#B8B6A8}")


def _vn(iso) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso else "–"


def _pct(v) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def _signed(v) -> str:
    return "–" if v is None else ("+" if v >= 0 else "−") + F.n(abs(v))


def load_progress(cfg, today: date | None = None, watch: tuple = ()) -> dict | None:
    """Tính tiến độ (gọi GA4 nên chạy trong run.io_bound)."""
    from . import db
    today = today or date.today()
    with closing(db.connect(cfg.db_path)) as c:
        if not KP.versions(c):
            return None
        try:
            ga4 = KP.ga4_sessions(cfg, c)
        except (Exception, SystemExit):  # noqa: BLE001  (chưa đăng nhập GA4: vẫn hiện phần thứ hạng)
            ga4 = None
        p = KP.progress(c, cfg.site_url, today, ga4, watch)
        if p is not None:
            p["ga4"] = ga4 is not None
        return p


def _rank_target(ch: dict) -> str:
    """Cam kết thứ hạng ghi cả hai cách: '40% (16 từ khóa)' hoặc '16 từ khóa (40%)'."""
    if ch["unit"] == "pct":
        return _pct(ch["target_pct"]) + (f" ({ch['need']} từ khóa)" if ch["need"] is not None else "")
    return f"{int(ch['target'])} từ khóa" + (f" ({_pct(ch['target_pct'])})" if ch["target_pct"] is not None else "")


SEG = "unelevated no-caps dense toggle-color=white toggle-text-color=dark text-color=grey-8"
TILE_LOOK = {3: ("emoji_events", "green"), 5: ("workspace_premium", "blue"), 10: ("format_list_numbered", "lime")}


def _tile(ui, line: dict, ch: dict, running: bool, has_ga4: bool) -> None:
    """Một ô tiến độ: icon + tên + trạng thái, số lớn kèm đơn vị, thanh tiến độ (vạch đen = mức cam kết), gợi ý."""
    text, tone = KP.status(ch, running)
    committed = ch["target"] is not None
    icon, look = (TILE_LOOK.get(line.get("top"), ("leaderboard", "green")) if ch["kind"] == "rank"
                  else ("trending_up", "purple"))
    unit = ""
    fill = ahead = mark = None  # thanh: phần đậm / phần nhạt (dự báo) / vạch cam kết, cùng thang 0–1
    if ch["kind"] == "rank":
        value = "chưa check" if not ch["checked"] else (_pct(ch["actual"]) if ch["total"] else "–")
        unit = f"{ch['count']}/{ch['total']} từ khóa" if ch["checked"] and ch["total"] else ""
        hint = f"Cam kết {_rank_target(ch)}" if committed else "Tháng này không cam kết"
        if not ch["checked"]:
            hint = "Chưa có lần check nào trong tháng này" + (f" · cam kết {_rank_target(ch)}" if committed else "")
        if ch["total"] and ch["checked"]:
            fill = ch["count"] / ch["total"]
            if committed and ch["need"]:
                mark = min(ch["need"] / ch["total"], 1)
    elif not has_ga4:
        value, hint = "chưa có", "Chưa kết nối GA4"
    elif ch["kind"] == "level":
        value = F.n(ch["actual"]) if ch["actual"] is not None else "chưa có"
        unit = "phiên"
        parts = [f"Cam kết {F.n(ch['target'])}" if committed else "Tháng này không cam kết"]
        if running and ch.get("forecast") is not None:
            parts.append(f"dự báo cuối tháng {F.n(ch['forecast'])}")
        elif running and ch.get("expected") is not None and ch["actual"] is not None:
            parts.append(f"{ch['days_done']} ngày đầu cần khoảng {F.n(ch['expected'])}")
        hint = " · ".join(parts)
        if ch["actual"] is not None:
            top = max(ch["target"] or 0, ch.get("forecast") or 0, ch["actual"]) or 1
            fill = ch["actual"] / top
            ahead = (ch["forecast"] / top) if running and ch.get("forecast") else None
            mark = (ch["target"] / top) if committed and ch["target"] else None
    else:  # tích lũy: số lớn là lũy kế
        cum = ch["cum"]
        value = _signed(cum) if cum is not None else (_signed(ch["actual"]) if ch["actual"] is not None else "chưa có")
        unit = "lũy kế"
        if ch["baseline"] is None:
            hint = "Chưa có số gốc để so"
        else:
            hint = f"Cam kết cả dự án {F.n(ch['total'])} · tháng này {_signed(ch['actual'])}"
            if running and ch.get("forecast_inc") is not None:
                hint += f" · dự báo {_signed(ch['forecast_inc'])}"
        if ch["total"] and cum is not None:
            fill = min(max(cum, 0) / ch["total"], 1)
            mark = min(ch["plan_cum"] / ch["total"], 1) if ch.get("plan_cum") is not None else None
    muted_value = value in ("chưa check", "chưa có")
    bar = T.TONES[tone][1] if committed and tone != "grey" else T.TONES[look][1]
    bg_icon, fg_icon = T.TONES[look]
    with ui.element("div").classes("sr-kp-tile"):
        with ui.row().classes("items-center no-wrap w-full").style("gap:8px"):
            with ui.element("div").classes("sr-db-bubble").style(f"background:{bg_icon}"):
                ui.icon(icon, size="15px").style(f"color:{fg_icon}").props('aria-hidden="true"')
            ui.label(KP.line_label(line)).classes("sr-kp-label col ellipsis")
            if committed:  # tháng không cam kết: đã đếm ở dòng đầu khối, không lặp chip trên từng ô
                with ui.element("span").classes(f"sr-kp-chip {tone}"):
                    ui.icon(ICONS.get(tone, "remove"), size="13px").props('aria-hidden="true"')
                    ui.label(text)
        with ui.row().classes("items-baseline no-wrap").style("gap:8px; margin-top:6px"):
            ui.label(value).classes("sr-kp-value num" + (" muted" if muted_value else ""))
            if unit and not muted_value:
                ui.label(unit).classes("sr-kp-unit")
        if fill is not None:
            title = f"Đạt {fill / mark * 100:.0f}% mức cam kết" if mark else ""
            html = (f'<div class="sr-kp-bar" title="{title}">'
                    + (f'<i style="width:{min(ahead, 1) * 100:.1f}%;background:{bar};opacity:.25"></i>'
                       if ahead else "")
                    + f'<i style="width:{min(fill, 1) * 100:.1f}%;background:{bar}"></i>'
                    + (f'<b style="left:{mark * 100:.1f}%"></b>' if mark else "") + "</div>")
            ui.html(html).classes("w-full")
        ui.label(hint).classes("sr-kp-hint")


def kpi_skeleton(ui, n_lines: int = 4) -> None:
    """Khung chờ cùng hình dạng khối Tiến độ KPI (dòng ngày + chip, lưới ô: icon · tên, số lớn, thanh, gợi ý)."""
    with T.section(ui, "Tiến độ KPI cam kết", "flag", "Đang tính tiến độ…"):
        with ui.element("div").classes("sr-kp-strip"):
            T.bone(ui, "14px", "240px")
            T.bone(ui, "22px", "120px", "999px")
        with ui.element("div").classes("sr-kp-grid"):
            for _ in range(n_lines):
                with ui.element("div").classes("sr-kp-tile"):
                    with ui.row().classes("items-center no-wrap w-full").style("gap:8px"):
                        T.bone(ui, "28px", "28px", "50%")
                        T.bone(ui, "14px", "55%")
                    T.bone(ui, "30px", "45%").style("margin-top:8px")
                    T.bone(ui, "7px", "100%", "4px").style("margin:8px 0 6px")
                    T.bone(ui, "12px", "75%")
                    T.bone(ui, "12px", "45%").style("margin-top:4px")  # gợi ý thường dài hai dòng
        T.bone(ui, "12px", "40%").style("margin-top:2px")  # dòng chú thích dưới lưới


def _month_strip(ui, m: dict, running: bool, p: dict, free: list[str]) -> None:
    """Dòng đầu khối: tháng đã trôi bao nhiêu ngày (thanh mảnh) + đếm trạng thái các cam kết."""
    d0, d1 = date.fromisoformat(m["from"]), date.fromisoformat(m["to"])
    days = (d1 - d0).days + 1
    done = days if not running else max(0, min(days, (date.today() - d0).days + 1))
    counts = {"green": 0, "amber": 0, "red": 0}
    for line in p["lines"]:
        ch = m["checks"].get(KP.line_id(line))
        if ch and ch["target"] is not None:
            _, tone = KP.status(ch, running)
            if tone in counts:
                counts[tone] += 1
    with ui.element("div").classes("sr-kp-strip"):
        with ui.element("div").classes("sr-kp-days"):
            ui.label(f"Ngày {done}/{days}" if running else f"Đã chốt · {days} ngày").classes("sr-kp-days-text")
            ui.html(f'<div class="sr-kp-bar thin"><i style="width:{done / days * 100:.1f}%;background:#1F221E">'
                    "</i></div>").classes("col")
        with ui.row().classes("items-center gap-2"):
            for tone, label in (("green", "Đang đạt" if running else "Đạt"), ("amber", "Đang thiếu"),
                                ("red", "Không đạt")):
                if counts[tone]:
                    with ui.element("span").classes(f"sr-kp-chip {tone}"):
                        ui.icon(ICONS[tone], size="13px").props('aria-hidden="true"')
                        ui.label(f"{label} {counts[tone]}")
            if free:
                with ui.element("span").classes("sr-kp-chip grey") as chip:
                    ui.icon("remove", size="13px").props('aria-hidden="true"')
                    ui.label(f"Không cam kết {len(free)}")
                chip.tooltip("Tháng này không cam kết: " + ", ".join(free))


def kpi_block(ui, p: dict | None, compact: bool = True) -> None:
    """Khối tiến độ của tháng dự án đang chạy (hoặc tháng gần nhất đã chốt)."""
    if not p:
        return
    if not p.get("start"):
        with T.section(ui, "Tiến độ KPI cam kết", "flag", "Chưa nhập ngày bắt đầu dự án trong sheet KPI",
                       href="/kpi" if compact else None, link_text="Mở Cam kết KPI"):
            ui.label("Điền 'Ngày bắt đầu' trong sheet KPI cam kết rồi bấm Đồng bộ để tool bắt đầu chấm.").classes(
                "text-sm muted")
        return
    months = [m for m in p["months"] if m["status"] != "future"]
    if not months:
        first = p["months"][0] if p["months"] else None
        with T.section(ui, "Tiến độ KPI cam kết", "flag", f"Dự án bắt đầu {_vn(first['from']) if first else '–'}",
                       href="/kpi" if compact else None, link_text="Mở Cam kết KPI"):
            ui.label("Dự án chưa bắt đầu.").classes("text-sm muted")
        return
    m = next((x for x in months if x["status"] == "running"), months[-1])
    running = m["status"] == "running"
    total = len(p["months"])
    free = [KP.line_label(ln).replace("Từ khóa top", "Top") for ln in p["lines"]
            if (m["checks"].get(KP.line_id(ln)) or {}).get("target", 0) is None]
    sub = (f"{_vn(m['from'])} – {_vn(m['to'])} · {m['rank']['total']} từ khóa cam kết"
           + (" · đang chạy, số còn thay đổi" if running else " · đã chốt"))
    with T.section(ui, f"Tiến độ KPI · Tháng dự án {m['n']}/{total}" + (f" · {p['project']}" if p.get("project") else ""),
                   "flag", sub, href="/kpi" if compact else None, link_text=f"Xem {total} tháng"):
        _month_strip(ui, m, running, p, free)
        with ui.element("div").classes("sr-kp-grid"):
            for line in p["lines"]:
                ch = m["checks"].get(KP.line_id(line))
                if ch:
                    _tile(ui, line, ch, running, bool(p.get("ga4")))
        notes = []
        if m["rank"].get("target_set"):
            notes.append(f"{m['rank']['target_ok']}/{m['rank']['target_set']} từ khóa đạt Top mục tiêu riêng "
                         "của từng từ khóa")
        if m["rank"]["checked"] < m["rank"]["total"]:
            left = m["rank"]["total"] - m["rank"]["checked"]
            notes.append(f"{left} từ khóa chưa có lần check nào trong tháng này" + (
                (": lịch check tự động sẽ cập nhật" if T.client_view() else
                 ": lịch check tự động sẽ cập nhật, hoặc bấm Kiểm tra thứ hạng ở màn Từ khóa & Thứ hạng") if running
                else ": tính là chưa đạt"))
        if notes:
            ui.label(" · ".join(notes)).classes("text-xs muted")


def _unit_val(line: dict, ch: dict | None, target=None, running: bool = False):
    """Số để vẽ / so (cùng đơn vị với cam kết). Lượt truy cập của tháng đang chạy dùng dự báo cuối tháng (số mới chạy
    vài ngày không so được với tháng trọn); chưa đủ ngày để dự báo thì để trống."""
    if line["kind"] == "rank":
        if target is not None:
            return round(target * 100, 1) if line["unit"] == "pct" else target
        if not ch or not ch.get("checked") or not ch.get("total"):
            return None
        return round(ch["actual"] * 100, 1) if line["unit"] == "pct" else ch["count"]
    if target is not None:
        return target
    if not ch:
        return None
    if ch.get("kind") == "level":
        return ch.get("forecast") if running else ch.get("actual")
    return ch.get("cum")


def _first_commit(p: dict, lid: str | None = None, after: int = 0) -> int | None:
    """Tháng đầu tiên (sau tháng `after`) có cam kết; lid None = bất kỳ cam kết nào."""
    for m in p["months"]:
        if m["n"] <= after:
            continue
        tg = m.get("targets") or {}
        if any(v is not None for k, v in tg.items() if lid is None or k == lid):
            return m["n"]
    return None


def _pool_gap(p: dict, line: dict, total: int) -> int | None:
    """Mục tiêu (số từ khóa) lớn nhất trong lộ trình nếu vượt số từ khóa đang có trong bộ của mốc; None = không vượt."""
    if line["kind"] != "rank" or line.get("unit") != "count":
        return None
    lid = KP.line_id(line)
    need = max(((m.get("targets") or {}).get(lid) or 0 for m in p["months"]), default=0)
    return int(need) if need > total else None


def _empty_reason(line: dict, ch: dict | None, has_ga4: bool, running: bool) -> str:
    """Câu giải thích khi chưa có số (không để "–" trơn)."""
    if line["kind"] != "rank":
        if not has_ga4:
            return "Chưa kết nối GA4"
        if not ch:
            return "Chưa có số tháng này"
        if ch.get("actual") is None:
            return "Đang chờ số GA4 (tháng mới bắt đầu)" if running else "GA4 chưa có số tháng này"
        return ""
    if ch and not ch.get("total"):
        return f"Bộ {_short(line)} chưa có từ khóa"
    if ch and not ch.get("checked"):
        return "Chờ lần check đầu trong tháng"
    return ""


def _short(line: dict) -> str:
    """Tên ngắn của cam kết: Top 3 / Organic traffic / AI traffic."""
    if line["kind"] == "rank" and line.get("name"):
        return f"{line['name']} · Top {line['top']}"
    if line["kind"] == "rank":
        return "Đạt Top mục tiêu" if line.get("mode") == "own" else f"Top {line['top']}"
    return {"organic": "Organic traffic", "ai": "AI traffic"}.get(line.get("source"), KP.line_label(line))


RING_COLOR = {"green": "#1E7C31", "amber": "#B7791F", "red": "#C2410C", "grey": "#8C8A7E", "ink": "#1F221E"}


def _ring(ui, frac: float, caption: str, tone: str) -> None:
    """Vòng % nhỏ cạnh số chính (đạt bao nhiêu phần mục tiêu / bộ)."""
    f = max(0.0, min(1.0, frac))
    c = 2 * 3.14159 * 22
    col = RING_COLOR.get(tone, "#1F221E")
    ui.html(f'<div class="sr-kg-ring" role="img" aria-label="{round(frac * 100)}% {caption}">'
            f'<svg viewBox="0 0 54 54" width="54" height="54"><circle cx="27" cy="27" r="22" fill="none" '
            f'stroke="#EEECE4" stroke-width="5"/><circle cx="27" cy="27" r="22" fill="none" stroke="{col}" '
            f'stroke-width="5" stroke-linecap="round" stroke-dasharray="{f * c:.1f} {c:.1f}" '
            f'transform="rotate(-90 27 27)"/></svg><b class="num">{round(frac * 100)}%</b>'
            f'<small>{caption}</small></div>')


def _month_tone(m: dict) -> str:
    """Màu ô tháng trên dải 12 tháng: đã chốt đạt / không đạt / không có cam kết, đang chạy, chưa tới."""
    if m["status"] == "future":
        return "future"
    if m["status"] == "running":
        return "running"
    oks = [c.get("ok") for c in (m.get("checks") or {}).values() if c.get("target") is not None]
    if not oks:
        return "none"
    return "ok" if all(oks) else "fail"


def line_groups(lines: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """Nhóm dòng cam kết theo bộ từ khóa: (khóa, tên, dòng). Bộ chính trước, rồi các bộ riêng theo thứ tự, cuối cùng là
    lượt truy cập."""
    main, sets, traffic = [], {}, []
    for ln in lines:
        if ln["kind"] != "rank":
            traffic.append(ln)
        elif ln.get("set") and ln.get("name"):
            sets.setdefault(ln["set"], (ln["name"], []))[1].append(ln)
        else:
            main.append(ln)
    out = [("main", "Cam kết", main)] if main else []
    out += [(f"s{k}", nm, lst) for k, (nm, lst) in sets.items()]
    if traffic:
        out.append(("traffic", "Lượt truy cập", traffic))
    return out


def _in_group(line: dict) -> str:
    """Tên ngắn khi thẻ / dòng đã nằm dưới tiêu đề bộ: Top 3 / Organic traffic."""
    if line["kind"] == "rank" and line.get("name"):
        return f"Top {line['top']}"
    return _short(line)


def _goal_card(ui, p: dict, line: dict, cur: dict, has_ga4: bool, any_commit: bool, ed: bool,
               title: str | None = None) -> None:
    """Một cam kết: số thực tế, câu nhấn chính (đạt / còn thiếu / tháng sau cần), biểu đồ thực tế so với lộ trình."""
    lid = KP.line_id(line)
    running = cur["status"] == "running"
    ch = (cur.get("checks") or {}).get(lid)
    committed = bool(ch and ch.get("target") is not None)
    text, tone = KP.status(ch, running) if committed else ("", "grey")
    rank = line["kind"] == "rank"
    unit = ("%" if line.get("unit") == "pct" else "từ khóa") if rank else "phiên"
    months = p["months"]
    total = ch.get("total", 0) if (rank and ch) else 0
    reason = _empty_reason(line, ch, has_ga4, running)
    with ui.element("div").classes(f"sr-kg-card {tone}"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.label(title or _short(line)).classes("sr-kg-name col ellipsis")
            if not committed and line.get("watch"):
                ui.label("Theo dõi").classes("sr-kp-chip grey").tooltip("Không cam kết, chỉ theo dõi số GA4")
            if committed:
                with ui.element("span").classes(f"sr-kp-chip {tone}"):
                    ui.icon(ICONS.get(tone, "remove"), size="13px").props('aria-hidden="true"')
                    ui.label(text)
        # số chính (không bao giờ là "–" trơn: thiếu số thì ghi lý do)
        ring = None  # % để vẽ vòng: so với mục tiêu tháng này, chưa cam kết thì so với cả bộ từ khóa
        if reason:
            with ui.row().classes("items-center no-wrap gap-2 sr-kg-empty"):
                ui.icon("hourglass_empty", size="18px").props('aria-hidden="true"')
                ui.label(reason)
        else:
            if rank:
                value = str(ch["count"]) if line["unit"] == "count" else _pct(ch["actual"])
                sub = (f"/ {ch['total']} từ khóa" if line["unit"] == "count" else
                       f"{ch['count']}/{ch['total']} từ khóa")
            else:
                value = F.n(ch["actual"])
                sub = "phiên" + (f" · dự báo {F.n(ch['forecast'])}" if running and ch.get("forecast") else "")
            now = _unit_val(line, ch, running=running)
            goal = _unit_val(line, None, ch.get("target")) if committed else None
            if now is not None and goal:
                ring = (now / goal, "của mục tiêu")
            elif rank and ch.get("total"):
                ring = (ch["count"] / ch["total"], "của bộ")
            with ui.row().classes("w-full items-center no-wrap gap-3 q-mt-xs sr-kg-vrow"):
                with ui.row().classes("col items-baseline gap-2").style("min-width:0"):
                    ui.label(value).classes("sr-kg-value num")
                    ui.label(sub).classes("sr-kg-sub")
                if ring:
                    _ring(ui, ring[0], ring[1], tone if committed else "ink")
        # câu nhấn chính: một câu thay cho lưới ô nhỏ
        nxt_n = _first_commit(p, lid, cur["n"])
        nxt_t = next(((m.get("targets") or {}).get(lid) for m in months if m["n"] == nxt_n), None) if nxt_n else None
        lead = ""
        if committed:
            tgt = _rank_target(ch) if rank else f"{F.n(ch['target'])} phiên"
            lead = (f"Thiếu {ch['gap']} từ khóa để đạt {tgt}" if rank and ch.get("gap") else
                    f"Thiếu {F.n(ch['gap'])} phiên để đạt {tgt}" if ch.get("gap") else f"Mục tiêu {tgt}")
        if nxt_t is not None:
            lead += (" · " if lead else "") + f"tháng {nxt_n} cần {KP.fmt_target(line, nxt_t)}"
        if lead:
            ui.label(lead[0].upper() + lead[1:]).classes("sr-kg-lead")
        gap = _pool_gap(p, line, total) if ed and rank else None  # cảnh báo gom một chỗ dưới đầu trang
        # biểu đồ: cột thực tế (tháng đang chạy: viền đứt, lượt truy cập là dự báo), nét đứt = lộ trình cam kết.
        # Chỉ vẽ tới tháng đang chạy + 3 (hoặc tới tháng cam kết kế tiếp): mục tiêu xa cuối dự án kéo thang quá lớn
        # làm cột thực tế không còn thấy; cả lộ trình xem ở Bảng các tháng.
        end = max(cur["n"] + 3, nxt_n or 0)
        months = [m for m in months if m["n"] <= end]
        labels = [f"T{m['n']}" for m in months]
        tgt_s = [_unit_val(line, None, (m.get("targets") or {}).get(lid)) for m in months]
        act = []
        for m in months:
            run_m = m["status"] == "running"
            v = None if m["status"] == "future" else _unit_val(line, (m.get("checks") or {}).get(lid), running=run_m)
            mch = (m.get("checks") or {}).get(lid)
            style = {"color": "#1E7C31", "borderRadius": [4, 4, 0, 0]}
            if run_m:
                style = {"color": "#DCEFE0", "borderColor": "#1E7C31", "borderWidth": 1, "borderType": "dashed",
                         "borderRadius": [4, 4, 0, 0]}
            elif m["status"] == "closed" and mch and mch.get("ok") is False:
                style["color"] = "#E3A48A"
            act.append({"value": v, "itemStyle": style})
        if any(v is not None for v in tgt_s) or any(a["value"] is not None for a in act):
            fmt = "{value}%" if rank and line["unit"] == "pct" else "{value}"
            bar_name = "Thực tế"
            mark = ({"markLine": {"silent": True, "symbol": "none", "data": [{"yAxis": total}],
                                  "lineStyle": {"color": "#C2410C", "type": "dotted"},
                                  "label": {"formatter": f"bộ có {total} từ", "color": "#A93A0B", "fontSize": 10,
                                            "position": "insideEndTop", "backgroundColor": "#fff", "padding": [1, 4]}}}
                    if gap else {})
            chart = ui.echart({
                "animation": False, "grid": {"left": 32, "right": 6, "top": 24, "bottom": 20},
                "tooltip": {"trigger": "axis"},
                "legend": {"top": 0, "left": 0, "itemWidth": 12, "itemHeight": 7, "itemGap": 10,
                           "textStyle": {"fontSize": 10, "color": "#6B6A5E"}},
                "xAxis": {"type": "category", "data": labels, "axisTick": {"show": False},
                          "axisLabel": {"color": "#6B6A5E", "fontSize": 10}},
                "yAxis": {"type": "value", "min": 0, "axisLabel": {"formatter": fmt, "color": "#8C8A7E", "fontSize": 10},
                          "splitLine": {"lineStyle": {"color": "#F0EEE6"}}},
                "series": [
                    {"type": "bar", "name": bar_name, "data": act, "barMaxWidth": 22, "itemStyle": {"color": "#1E7C31"}},
                ] + ([
                    {"type": "line", "name": "Cam kết", "data": tgt_s, "connectNulls": False, "symbol": "circle",
                     "symbolSize": 6, "lineStyle": {"type": "dashed", "width": 2, "color": "#1F221E"},
                     "itemStyle": {"color": "#1F221E"}, **mark},
                ] if any(v is not None for v in tgt_s) else [])}).classes("w-full sr-kg-chart")
            chart.props["role"] = "img"
            chart.props["aria-label"] = (f"{_short(line)}: thực tế và lộ trình cam kết theo tháng ({unit})")


KPI_COLORS = ("#1E7C31", "#2563EB", "#B7791F", "#7C3AED", "#C2410C", "#0E7490", "#6B6A5E")
KPI_DASH = ("solid", "dashed", "dotted")
KPI_SYMBOL = ("circle", "rect", "triangle", "diamond")


def all_chart(ui, p: dict) -> None:
    """Một biểu đồ cho mọi KPI: % hoàn thành cam kết từng tháng (100% = đạt). Chưa có tháng nào vừa có cam kết vừa
    có số thì không vẽ (đầu trang đã nói tháng nào bắt đầu cam kết). Mỗi KPI khác nhau cả màu lẫn kiểu nét."""
    months = p["months"]
    series = []
    for i, line in enumerate(p["lines"]):
        lid = KP.line_id(line)
        data = []
        for m in months:
            t = _unit_val(line, None, (m.get("targets") or {}).get(lid))
            a = None if m["status"] == "future" else _unit_val(line, (m.get("checks") or {}).get(lid),
                                                               running=m["status"] == "running")
            data.append(round(a / t * 100) if t and a is not None else None)
        if any(v is not None for v in data):
            series.append({"type": "line", "name": _short(line), "data": data, "connectNulls": False,
                           "symbol": KPI_SYMBOL[i % len(KPI_SYMBOL)], "symbolSize": 7,
                           "lineStyle": {"width": 2, "type": KPI_DASH[i % len(KPI_DASH)]},
                           "itemStyle": {"color": KPI_COLORS[i % len(KPI_COLORS)]}})
    if not series:
        return
    series[0]["markLine"] = {"silent": True, "symbol": "none", "data": [{"yAxis": 100}],
                             "lineStyle": {"color": "#1F221E", "type": "dashed"},
                             "label": {"formatter": "đạt cam kết", "color": "#1F221E", "fontSize": 10,
                                       "position": "insideEndTop", "backgroundColor": "#fff", "padding": [1, 4]}}
    with T.section(ui, "Tiến độ mọi KPI", "insights", "% hoàn thành cam kết từng tháng · 100% = đạt"):
        chart = ui.echart({
            "animation": False, "grid": {"left": 44, "right": 16, "top": 20, "bottom": 56},
            "tooltip": {"trigger": "axis"},
            "legend": {"bottom": 0, "type": "scroll", "textStyle": {"fontSize": 11}},
            "xAxis": {"type": "category", "data": [f"Th{m['n']}" for m in months], "axisTick": {"show": False},
                      "axisLabel": {"color": "#6B6A5E", "fontSize": 11}},
            "yAxis": {"type": "value", "min": 0, "axisLabel": {"formatter": "{value}%", "color": "#8C8A7E",
                                                               "fontSize": 10},
                      "splitLine": {"lineStyle": {"color": "#F0EEE6"}}},
            "series": series}).classes("w-full").style("height: 260px")
        chart.props["role"] = "img"
        chart.props["aria-label"] = "% hoàn thành cam kết từng tháng của " + ", ".join(s["name"] for s in series)


def page_view(ui, p: dict, ed: bool = False, ai: dict | None = None) -> None:
    """Trang KPI: đầu trang (tháng dự án, nút chọn tháng, bộ từ khóa từng mốc, bao nhiêu cam kết đạt) + biểu đồ chung
    + mỗi cam kết một thẻ có biểu đồ. Chọn tháng khác thì cả đầu trang và các thẻ hiện số của tháng đó."""
    state = {"n": None}

    @ui.refreshable
    def view() -> None:
        _page_view(ui, p, ed, state["n"], pick, ai)

    def pick(n) -> None:
        state["n"] = n
        view.refresh()
    view()


def _month_menu(ui, p: dict, cur: dict, pick) -> None:
    """Nút chọn tháng dự án: tháng đã chốt / đang chạy xem được, tháng chưa tới khóa lại."""
    run_n = next((m["n"] for m in p["months"] if m["status"] == "running"), None)
    with ui.button(f"Xem tháng {cur['n']}", icon="calendar_month").props(
            'outline no-caps dense icon-right="expand_more" aria-label="Chọn tháng dự án"').classes("sr-kg-pick"):
        with ui.menu().props("anchor='bottom right' self='top right'").classes("sr-kg-pickmenu"):
            for m in p["months"]:
                fut = m["status"] == "future"
                st = "đang chạy" if m["status"] == "running" else ("chưa tới" if fut else "đã chốt")
                item = ui.menu_item(on_click=(None if fut else (lambda _, n=m["n"]: pick(None if n == run_n else n))))
                if fut:
                    item.props("disable")
                with item:
                    with ui.row().classes("w-full items-center no-wrap gap-3"):
                        ui.label(f"Tháng {m['n']}").classes("sr-kg-pm-n" + (" on" if m["n"] == cur["n"] else ""))
                        ui.label(f"{_vn(m.get('from'))} – {_vn(m.get('to'))}").classes("text-xs muted col")
                        ui.label(st).classes("text-xs" + (" sr-kg-pm-run" if m["status"] == "running" else " muted"))


AI_LEVEL = {"good": ("Đang ổn", "#1E7C31"), "watch": ("Cần theo dõi", "#B7791F"), "risk": ("Rủi ro", "#C2410C")}


def _ai_insight(ui, p: dict, ai: dict, slot, box) -> None:
    """Nút "AI nhận định" (đầu trang) + bản nhận định đã lưu (tông tím nhạt, cuối khối đầu trang). Chỉ team."""
    from datetime import datetime

    from . import ai_kpi_insight as AKI
    from . import ai_settings as AIS
    from . import ai_writer as AW
    from . import points as PT
    cfg, connect, user = ai["cfg"], ai["connect"], ai["user"]
    site = cfg.site_url
    if not AIS.enabled(site, "kpi_insight"):
        return
    f = AKI.facts(p)
    if not f.get("kpi"):
        return
    with connect() as c:
        state = {"d": AW.latest(c, site, AKI.KIND, "kpi")}

    def paint() -> None:
        box.clear()
        d = state["d"]
        if not d:
            return
        with box, ui.element("div").classes("sr-kai"):
            with ui.row().classes("w-full items-center gap-2 sr-kai-top"):
                ui.icon("auto_awesome", size="18px").classes("sr-br-ico")
                ui.label("AI nhận định KPI").classes("sr-br-h sr-kai-title")
                at = datetime.fromisoformat(d["at"]).astimezone() if d.get("at") else None
                stale = d.get("fingerprint") != AKI.fingerprint(f)
                ui.label((f"{at:%d/%m %H:%M}" if at else "") + (" · đã có số mới, bấm cập nhật" if stale else "")
                         ).classes("sr-br-sub" + (" stale" if stale else ""))
            items = sorted(d.get("items") or [], key=lambda x: ("risk", "watch", "good").index(
                x.get("level") if x.get("level") in AI_LEVEL else "watch"))
            with ui.row().classes("w-full items-center gap-2 sr-kai-sum"):
                if d.get("headline"):
                    ui.label(d["headline"]).classes("sr-kai-head col")
                for lv in ("risk", "watch", "good"):
                    n = sum(1 for x in items if x.get("level") == lv)
                    if n:
                        lab, col = AI_LEVEL[lv]
                        ui.html(f'<span class="sr-kai-cnt"><i style="background:{col}"></i>{n} {lab.lower()}</span>')
            # mỗi KPI một dòng: tên + mức | nhận định | dự đoán | nên làm (tiêu đề cột ghi một lần)
            with ui.element("div").classes("sr-kai-list"):
                ui.html('<div class="sr-kai-row hd"><span>KPI</span><span>Nhận định</span><span>Dự đoán</span>'
                        '<span>Nên làm</span></div>')
                for it in items:
                    lab, col = AI_LEVEL.get(it.get("level"), AI_LEVEL["watch"])
                    with ui.element("div").classes(f"sr-kai-row {it.get('level')}"):
                        with ui.column().classes("gap-1"):
                            ui.label(it.get("name") or "").classes("sr-kai-name")
                            ui.html(f'<span class="sr-kai-lv"><i style="background:{col}"></i>{lab}</span>')
                        ui.label(it.get("insight") or "").classes("sr-kai-t")
                        with ui.row().classes("items-start no-wrap gap-1 sr-kai-f"):
                            ui.icon("trending_up", size="15px").props('aria-hidden="true"')
                            ui.label(it.get("forecast") or "Chưa đủ dữ liệu để dự đoán")
                        with ui.row().classes("items-start no-wrap gap-1 sr-kai-a"):
                            ui.icon("arrow_forward", size="15px").props('aria-hidden="true"')
                            ui.label(it.get("action") or "–")
            ui.label("AI đọc số tool đã tính; dự đoán theo tốc độ các tháng trước, chỉ để tham khảo.").classes(
                "sr-kai-note")

    async def go(btn) -> None:
        from .web_ai_research import _run
        btn.props("loading")
        try:
            res = await _run(ui, user, cfg, "ai_kpi_insight", "nhận định KPI", AKI.write, f)
        finally:
            btn.props(remove="loading")
        if not res:
            return
        data, prov = res
        with connect() as c:
            AW.save(c, site, AKI.KIND, "kpi", data, prov, str(user))
            state["d"] = AW.latest(c, site, AKI.KIND, "kpi")
        btn.text = "Cập nhật nhận định" + (f" · {PT.cost('ai_kpi_insight')} credit" if PT.member(user) else "")
        paint()

    with slot:
        label = ("Cập nhật nhận định" if state["d"] else "AI nhận định") + (
            f" · {PT.cost('ai_kpi_insight')} credit" if PT.member(user) else "")
        btn = ui.button(label, icon="auto_awesome", on_click=lambda: go(btn)).props(
            "unelevated no-caps dense color=deep-purple-1 text-color=deep-purple-9").classes("sr-br-btn sr-kg-aibtn")
        btn.tooltip("AI nhận định từng KPI, dự đoán tháng cam kết kế tiếp và việc nên làm")
    paint()


def _page_view(ui, p: dict, ed: bool, sel, pick, ai: dict | None = None) -> None:
    months = [m for m in p["months"] if m["status"] != "future"]
    if not months:
        first = p["months"][0] if p["months"] else None
        T.empty_state(ui, "flag", "Dự án chưa bắt đầu",
                      f"Tháng 1 bắt đầu {_vn(first['from'])}/{first['from'][:4]}" if first and first.get("from") else "")
        return
    cur = next((x for x in months if x["status"] == "running"), months[-1])
    live = cur  # tháng đang chạy (dải tháng tô theo tháng này dù đang xem tháng khác)
    if sel:
        cur = next((x for x in months if x["n"] == sel), cur)
    running = cur["status"] == "running"
    counts = {"green": 0, "amber": 0, "red": 0, "grey": 0}
    committed = 0
    for line in p["lines"]:
        ch = (cur.get("checks") or {}).get(KP.line_id(line))
        if ch and ch.get("target") is not None:
            committed += 1
            counts[KP.status(ch, running)[1]] += 1
    d0, d1 = date.fromisoformat(cur["from"]), date.fromisoformat(cur["to"])
    days = (d1 - d0).days + 1
    done = days if not running else max(0, min(days, (date.today() - d0).days + 1))
    start_n = _first_commit(p, None, cur["n"]) if not committed else None
    l0, l1 = date.fromisoformat(live["from"]), date.fromisoformat(live["to"])
    live_frac = (max(0, min((l1 - l0).days + 1, (date.today() - l0).days + 1)) / ((l1 - l0).days + 1)
                 if live["status"] == "running" else 1)
    tiers = []  # mẫu số từng mốc: đúng số từ khóa từng mốc được chấm
    for line in p["lines"]:
        ch = (cur.get("checks") or {}).get(KP.line_id(line))
        if line["kind"] == "rank" and ch is not None:
            tiers.append(f"{_short(line)} · {ch['total']} từ")
    left = len(p["months"]) - live["n"]
    with ui.element("div").classes("sr-card sr-kg-head w-full"):
        # ---- hàng 1: tháng đang xem + nút (về tháng hiện tại / chọn tháng / AI nhận định) ----
        with ui.element("div").classes("sr-kg-hrow"):
            with ui.column().classes("gap-0").style("min-width:0"):
                ui.label("Tháng đang chạy" if running else ("Đang xem tháng đã chốt" if live is not cur
                                                            else "Tháng gần nhất")).classes("sr-kg-eyebrow")
                ui.html(f'<div class="sr-kg-hn num">Tháng {cur["n"]}<span> / {len(p["months"])}</span></div>')
                ui.label(f"{_vn(cur['from'])}/{cur['from'][:4]} – {_vn(cur['to'])}/{cur['to'][:4]}").classes(
                    "text-sm muted")
            with ui.row().classes("items-center gap-2 sr-kg-acts"):
                if live is not cur:
                    ui.button("Về tháng hiện tại", on_click=lambda: pick(None)).props(
                        "flat no-caps dense").classes("sr-kg-back")
                _month_menu(ui, p, cur, pick)
                ai_slot = ui.element("div").classes("sr-kg-aislot")
        # ---- hàng 2: 4 ô số nhanh ----
        with ui.element("div").classes("sr-kg-stats"):
            with ui.element("div").classes("sr-kg-stat"):
                ui.label("Tiến độ tháng").classes("sr-kg-sk")
                ui.html(f'<div class="sr-kg-sv num">{done}<span>/{days} ngày</span></div>')
                ui.html(f'<div class="sr-kp-bar thin" role="img" aria-label="Ngày {done}/{days}"><i style="width:'
                        f'{done / days * 100:.0f}%;background:#1F221E"></i></div>').classes("w-full")
            with ui.element("div").classes("sr-kg-stat"):
                ui.label("Cam kết tháng này" if running else f"Cam kết tháng {cur['n']}").classes("sr-kg-sk")
                if committed:
                    ui.html(f'<div class="sr-kg-sv num">{counts["green"]}<span>/{committed} '
                            f'{"đang đạt" if running else "đạt"}</span></div>')
                    with ui.row().classes("gap-1"):
                        for tone, lab in (("amber", "đang thiếu"), ("red", "không đạt")):
                            if counts[tone]:
                                ui.label(f"{counts[tone]} {lab}").classes(f"sr-kp-chip {tone}")
                else:
                    ui.html('<div class="sr-kg-sv none">Chưa có</div>')
                    if start_n:
                        ui.label(f"Bắt đầu từ tháng {start_n}").classes("sr-kg-sn")
            with ui.element("div").classes("sr-kg-stat"):
                ui.label("Thời gian dự án").classes("sr-kg-sk")
                ui.html(f'<div class="sr-kg-sv num">{left}<span> tháng còn lại</span></div>')
                ui.label(f"Kết thúc {_vn(p['months'][-1].get('to'))}/{(p['months'][-1].get('to') or '')[:4]}"
                         ).classes("sr-kg-sn")
            with ui.element("div").classes("sr-kg-stat"):
                ui.label("Bộ từ khóa").classes("sr-kg-sk")
                pools = [int(t.rsplit("·", 1)[1].split()[0]) for t in tiers] if tiers else []
                ui.html(f'<div class="sr-kg-sv num">{max(pools) if pools else 0}<span> từ khóa</span></div>')
                ui.label(f"{len(tiers)} mốc Top" if tiers else "Chưa có bộ").classes("sr-kg-sn")
        # ---- hàng 3: dải các tháng (đang ở đâu, tháng nào đạt / trượt, cam kết bắt đầu từ đâu) ----
        cells = []
        for m in p["months"]:
            mt = _month_tone(m)
            has_t = any(v is not None for v in (m.get("targets") or {}).values())
            fill = (f'<i style="width:{live_frac * 100:.0f}%"></i>' if mt == "running" else "")
            tip = {"ok": "đạt", "fail": "không đạt", "none": "không có cam kết", "running": "đang chạy",
                   "future": "chưa tới"}[mt]
            cells.append(f'<div class="sr-kg-m {mt}{" commit" if has_t else ""}{" sel" if m is cur else ""}" '
                         f'title="Tháng {m["n"]}: {tip}{" · có cam kết" if has_t else ""}"><span class="bar">{fill}'
                         f'</span><span class="lab">T{m["n"]}</span></div>')
        ui.html(f'<div class="sr-kg-months" role="img" aria-label="Tháng {cur["n"]} trên {len(p["months"])} tháng">'
                + "".join(cells) + "</div>").classes("w-full")
        with ui.row().classes("w-full items-center gap-3 sr-kg-legend"):
            for cls, lab in (("ok", "Đạt"), ("fail", "Không đạt"), ("running", "Đang chạy"), ("commit", "Có cam kết")):
                ui.html(f'<span class="sr-kg-key {cls}"></span>{lab}').classes("sr-kg-keyl")
        # ---- AI nhận định (team): nút ở hàng 1, nội dung ở cuối khối ----
        if ai:
            ai_box = ui.element("div").classes("w-full")
            _ai_insight(ui, p, ai, ai_slot, ai_box)
    # vượt bộ từ khóa: gom một cảnh báo (chỉ team thấy) thay vì lặp ở từng thẻ
    if ed:
        over = []
        for line in p["lines"]:
            ch = (live.get("checks") or {}).get(KP.line_id(line))  # luôn theo bộ hiện tại
            tot = ch.get("total", 0) if ch else 0
            g = _pool_gap(p, line, tot)
            if g:
                over.append(f"{_short(line)} cần {g}, bộ có {tot}")
        if over:
            with ui.row().classes("w-full items-center no-wrap gap-3 sr-kg-alert"):
                ui.icon("playlist_add", size="22px").props('aria-hidden="true"')
                with ui.column().classes("col gap-0").style("min-width:0"):
                    ui.label("Lộ trình cần nhiều từ khóa hơn số đang có trong bộ").classes("sr-kg-alert-t")
                    ui.label(" · ".join(over)).classes("text-sm")
                ui.button("Thêm từ khóa", on_click=lambda: ui.navigate.to("/kpi/sua")).props(
                    "outline no-caps dense").classes("sr-kg-alert-b")
    all_chart(ui, p)
    # cam kết đã bỏ ở bản hiện tại (chỉ còn trong tháng cũ, không có mục tiêu tháng này / tháng sau): không vẽ thẻ
    shown = [ln for ln in p["lines"] if KP.line_id(ln) in (cur.get("checks") or {})
             or _first_commit(p, KP.line_id(ln), cur["n"] - 1)]
    from nicegui import app
    key = "kpi_hide:" + str(p.get("project") or "")
    try:
        hidden = set(app.storage.user.get(key) or [])
    except Exception:  # noqa: BLE001  (không có phiên trình duyệt: hiện đủ)
        hidden = set()
    hidden &= {KP.line_id(ln) for ln in shown}
    sub = ""
    if cur["rank"]["checked"] < cur["rank"]["total"]:
        sub = (f"{cur['rank']['total'] - cur['rank']['checked']} từ khóa chưa check trong tháng"
               + ("" if running else ": tính là chưa đạt"))
    # đầu khối tự vẽ (thay T.section): nút chọn KPI nằm cùng hàng tiêu đề, không chiếm một hàng riêng
    with ui.element("div").classes("sr-card q-pa-md w-full"):
        with ui.row().classes("w-full items-center gap-2 no-wrap q-mb-sm sr-sec-head"):
            with ui.element("div").classes("sr-icon-bubble").style(f"background:{T.TONES['green'][0]}"):
                ui.icon("flag", size="18px").style(f"color:{T.GREEN}")
            with ui.column().classes("gap-0"):
                ui.label("Các KPI").classes("sr-section-title").props('role=heading aria-level=2')
                if sub:
                    ui.label(sub).classes("text-xs muted")
            ui.space()
            filter_slot = ui.element("div")

        @ui.refreshable
        def body() -> None:
            filter_slot.clear()
            with filter_slot:
                n_on = sum(1 for ln in shown if KP.line_id(ln) not in hidden)
                with ui.button(f"Hiện {n_on}/{len(shown)} KPI", icon="tune").props(
                        "flat no-caps dense size=sm color=grey-8"):
                    with ui.menu().props("auto-close=false"):
                        for ln in shown:
                            lid = KP.line_id(ln)
                            on = lid not in hidden
                            with ui.menu_item(on_click=lambda _, x=lid: flip(x)).props("dense"):
                                with ui.row().classes("items-center no-wrap gap-2"):
                                    ui.icon("check_box" if on else "check_box_outline_blank", size="18px").style(
                                        f"color:{'#1E7C31' if on else '#8C8A7E'}")
                                    ui.label(_short(ln) + (" (theo dõi)" if ln.get("watch") else "")).classes(
                                        "text-sm")
            vis = [ln for ln in shown if KP.line_id(ln) not in hidden]
            groups = line_groups(vis)
            many = sum(1 for k, *_ in groups if k != "traffic") > 1
            for i, (gk, gname, glines) in enumerate(groups if many else [("all", "", vis)]):
                if many:
                    with ui.row().classes(f"items-baseline gap-2 sr-kg-gh {'traffic' if gk == 'traffic' else f'g{i % 4}'}"):
                        ui.label(gname).classes("sr-kg-ghn")
                        if gk != "traffic":
                            ui.label(("Bộ chính · " if gk == "main" else "")
                                     + f"{len(glines)} mốc Top").classes("sr-kg-ghs")
                n = len(glines)
                rows = -(-n // 3) if n else 0
                counts = [n // rows + (1 if j < n % rows else 0) for j in range(rows)] if rows else []
                spans = [6 // c for c in counts for _ in range(c)]  # lưới 6 cột: hàng 3 / 2 / 1 thẻ đều kín hàng
                with ui.element("div").classes("sr-kg-grid6" + (" q-mb-md" if many else "")):
                    for ln, sp in zip(glines, spans):
                        with ui.element("div").classes(f"sr-kg-cell s{sp}"):
                            _goal_card(ui, p, ln, cur, bool(p.get("ga4")), bool(committed), ed,
                                       title=_in_group(ln) if many else None)

        def flip(lid: str) -> None:
            if lid in hidden:
                hidden.discard(lid)
            elif len(hidden) < len(shown) - 1:  # luôn còn ít nhất một thẻ
                hidden.add(lid)
            else:
                ui.notify("Cần hiện ít nhất một KPI", position="bottom-right")
                return
            try:
                app.storage.user[key] = sorted(hidden)
            except Exception:  # noqa: BLE001
                pass
            body.refresh()
        body()


def _target_cell(line: dict, t, n: int) -> str:
    if t is None:
        return "–"
    if line["kind"] == "rank":
        return KP.fmt_target(line, t)
    if line["kind"] == "level":
        return F.n(t)
    plan_cum = sum(v for k, v in line["targets"].items() if v is not None and int(k) <= n)
    return f'{_signed(t)}<div class="d">lũy kế {F.n(plan_cum)}</div>'


def _actual_cell(ch: dict, m: dict) -> str:
    if ch["kind"] == "rank":
        if not ch["checked"] and m["status"] == "running":
            return '<span class="mut">chưa check</span>'
        val = f'{_pct(ch["actual"]) if ch["total"] else "–"}<div class="d">{ch["count"]}/{ch["total"]} từ khóa</div>'
    elif ch["kind"] == "level":
        val = F.n(ch["actual"]) if ch["actual"] is not None else "chưa có"
        if m["status"] == "running" and ch.get("forecast") is not None:
            val += f'<div class="d">dự báo {F.n(ch["forecast"])}</div>'
    else:
        if ch["baseline"] is None:
            return '<span class="mut">chưa có baseline</span>'
        val = _signed(ch["actual"]) if ch["actual"] is not None else "chưa có"
        if ch["cum"] is not None:
            val += f'<div class="d">lũy kế {"dự báo " if m["status"] == "running" else ""}{F.n(ch["cum"])}</div>'
        if m["status"] == "running" and ch.get("forecast_inc") is not None:
            val += f'<div class="d">dự báo {_signed(ch["forecast_inc"])}</div>'
    cls = "" if ch["ok"] is None else ("ok" if ch["ok"] else ("warn" if m["status"] == "running" else "bad"))
    return f'<span class="{cls}">{val}</span>'


def _fmt_unit(line: dict, v) -> str:
    """Số cùng đơn vị với cam kết, viết ngắn: 6 · 40% · 12.500."""
    if v is None:
        return ""
    if line["kind"] == "rank" and line.get("unit") == "pct":
        return f"{v:g}%"
    return F.n(v)


def _now_value(line: dict, months: list[dict]):
    """Số hiện tại của một cam kết (tháng đang chạy, chưa có thì tháng đã chốt gần nhất): cùng một bộ từ khóa nên
    số này là mức đã đạt tới lúc này, dùng để so với cam kết các tháng sau."""
    lid = KP.line_id(line)
    past = [x for x in months if x["status"] != "future"]
    for m in sorted(past, key=lambda x: (x["status"] != "running", -x["n"])):
        ch = (m.get("checks") or {}).get(lid)
        if line["kind"] == "rank":  # từ khóa: chỉ số của bộ hiện tại (tháng cũ có thể là bộ khác)
            return _unit_val(line, ch) if ch and ch.get("checked") and ch.get("total") else None
        if ch:  # lượt truy cập: dự báo tháng đang chạy, chưa đủ ngày thì tháng đã chốt gần nhất
            v = _unit_val(line, ch, running=m["status"] == "running")
            if v is not None:
                return v
    return None


def _ratio(r: float) -> str:
    return "↑ vượt " + f"{round(r * 100)}%" if r > 1 else ("✓ đạt" if r >= 1 else f"{round(r * 100)}%")


def _cell(line: dict, m: dict, now=None) -> tuple[str, str]:
    """Một ô bảng các tháng: (html, lớp màu). Thực tế đậm, cam kết nhỏ sau dấu /. Tháng chưa tới: số hiện tại so với
    cam kết tháng đó (đã đạt sớm thì tô xanh nhạt)."""
    lid = KP.line_id(line)
    t = _unit_val(line, None, (m.get("targets") or {}).get(lid))
    ch = (m.get("checks") or {}).get(lid)
    tgt = f'<span class="t">/ {_fmt_unit(line, t)}</span>' if t is not None else ""
    if m["status"] == "future" or not ch:
        if t is None:
            return "", ""
        if now is None or not t:
            return f'<b class="tg">{_fmt_unit(line, t)}</b>', "fut"  # chưa có số hiện tại: chỉ số cam kết
        r = now / t
        tip = (f"Hiện có {_fmt_unit(line, now)} · cam kết tháng {m['n']}: {_fmt_unit(line, t)} · "
               f"{'đã đạt sớm' if r >= 1 else f'{round(r * 100)}%'}")
        return (f'<div title="{tip}"><b class="tg">{_fmt_unit(line, t)}{" ✓" if r >= 1 else ""}</b>'
                f'<div class="pb"><i style="width:{min(r, 1) * 100:.0f}%"></i></div></div>',
                "fut" + (" ok" if r >= 1 else ""))
    if line["kind"] == "cum":
        return _actual_cell(ch, m), ""
    if line["kind"] == "rank" and not ch.get("checked"):
        return '<span class="mut">chưa check</span>' + tgt, ""
    a = _unit_val(line, ch, running=m["status"] == "running")
    if a is None:
        return '<span class="mut">chưa có</span>' + tgt, ""
    cls = "" if ch.get("ok") is None else ("ok" if ch["ok"] else ("run" if m["status"] == "running" else "bad"))
    pct = ""
    if t:
        r = a / t
        if r > 1:
            cls = "over"
        pct = f'<span class="p">{_ratio(r)}</span>'
    return f"<b>{_fmt_unit(line, a)}</b>{tgt}{pct}", cls


def full_table(ui, p: dict) -> None:
    """Bảng cả dự án: mỗi tháng một cột, mỗi cam kết một dòng; ô = thực tế / cam kết, nền xanh đạt, cam không đạt."""
    months = p["months"]

    def zone(m: dict) -> str:  # vùng cột: đã qua / hiện tại / sắp tới (màu nền khác nhau)
        return {"closed": "zp", "running": "zc"}.get(m["status"], "zf")
    tag = {"zp": "Đã qua", "zc": "Hiện tại", "zf": "Sắp tới"}
    head = ""
    for m in months:  # vùng đã qua / hiện tại / sắp tới thể hiện bằng màu nền cột, tên vùng ở tooltip
        z = zone(m)
        head += (f'<th class="{z}" title="{tag[z]}">Tháng {m["n"]}'
                 f'<div class="d">{_vn(m.get("from"))} – {_vn(m.get("to"))}</div></th>')
    # dòng timeline: chấm trạng thái từng tháng nối thành một đường, nhãn ngắn bên dưới
    first_c = _first_commit(p)
    steps = ""
    for i, m in enumerate(months):
        mt = _month_tone(m)
        if mt == "running" and m.get("from") and m.get("to"):
            d0, d1 = date.fromisoformat(m["from"]), date.fromisoformat(m["to"])
            tot = (d1 - d0).days + 1
            note = f"Đang chạy · {max(0, min(tot, (date.today() - d0).days + 1))}/{tot}"
        else:
            note = {"ok": "Đạt", "fail": "Không đạt", "none": "Không cam kết"}.get(mt, "")
        if mt == "future" and m["n"] == first_c:
            note = "Bắt đầu cam kết"
        elif mt == "future" and i == len(months) - 1:
            note = "Kết thúc dự án"
        icon = {"ok": "✓", "fail": "!"}.get(mt, "")
        edge = (" first" if i == 0 else "") + (" last" if i == len(months) - 1 else "")
        steps += (f'<td class="tl {mt} {zone(m)}{edge}{" start" if m["n"] == first_c else ""}"><span class="dot">{icon}</span>'
                  f'<span class="nt">{note}</span></td>')
    body = f'<tr class="tl-row"><td class="lab">Tiến trình</td>{steps}</tr>'
    live = next((m for m in months if m["status"] == "running"), None) or \
        next((m for m in reversed(months) if m["status"] == "closed"), None) or {}

    def lab_sub(line: dict) -> str:
        if line["kind"] != "rank":
            return "phiên / tháng"
        tot = ((live.get("checks") or {}).get(KP.line_id(line)) or {}).get("total")
        return f"bộ {tot} từ" if tot is not None else ""
    groups = line_groups(p["lines"])
    many = sum(1 for k, *_ in groups if k != "traffic") > 1
    for i, (gk, gname, glines) in enumerate(groups):
        part = ""
        for line in glines:
            now = _now_value(line, months)
            cells = [_cell(line, m, now) for m in months]
            if all(not h for h, _ in cells):
                continue  # cam kết không còn số nào: bỏ dòng
            sub_ = lab_sub(line)
            part += (f'<tr><td class="lab">{_in_group(line) if many else _short(line)}'
                     + (f'<div class="ls">{sub_}</div>' if sub_ else "") + '</td>'
                     + "".join(f'<td class="{c} {zone(m)}">{h}</td>'
                               for (h, c), m in zip(cells, months)) + "</tr>")
        if part and many:  # nhiều bộ: tiêu đề nhóm trước các dòng của bộ
            tone = "traffic" if gk == "traffic" else f"g{i % 4}"
            part = (f'<tr class="grp {tone}"><td class="lab">{escape(gname)}</td>'
                    f'<td colspan="{len(months)}"></td></tr>') + part
        body += part
    # dòng kết quả: tháng đã chốt bao nhiêu cam kết đạt
    res = ""
    for m in months:
        oks = [c.get("ok") for c in (m.get("checks") or {}).values() if c.get("target") is not None]
        if m["status"] == "future" or not oks:
            res += f'<td class="{zone(m)} none"></td>'
        elif m["status"] == "running":
            res += f'<td class="zc"><span class="t">{sum(1 for o in oks if o)}/{len(oks)} đang đạt</span></td>'
        else:
            good = sum(1 for o in oks if o)
            res += f'<td class="zp {"ok" if good == len(oks) else "bad"}"><b>{good}/{len(oks)}</b> đạt</td>'
    if res.count(' none"') < len(months):  # chưa tháng nào có cam kết: bỏ dòng trống
        body += f'<tr class="res"><td class="lab">Kết quả</td>{res}</tr>'
    ui.html(f'<div class="sr-kt3-wrap"><table class="sr-kt3"><thead><tr><th class="lab">Cam kết</th>{head}</tr>'
            f'</thead><tbody>{body}</tbody></table></div>').classes("w-full")
    ui.label("Ô xanh: đạt · ô cam: không đạt. Tháng sắp tới: số cam kết, thanh là phần số hiện tại đã đạt "
             "(rê chuột để xem số).").classes("text-xs muted q-mt-sm")
    base = p.get("baseline") or {}
    if any(ln["kind"] == "cum" for ln in p["lines"]):
        ui.label("Baseline: " + " · ".join(
            f"{KP.SOURCES[k]} {F.n(base.get(k)) if base.get(k) is not None else 'chưa nhập'} phiên/tháng"
            for k in ("organic", "ai") if any(ln["kind"] == "cum" and ln["source"] == k for ln in p["lines"]))
                 + " · tăng thêm = phiên tháng − baseline, cộng dồn qua các tháng").classes("text-xs muted q-mt-sm")


def build_kpi_page(ui, cfg, connect, user, app_connect=None, project: dict | None = None) -> None:
    from nicegui import run

    from .access import can_edit, is_client
    ed = can_edit(user)
    cl = is_client(user)  # khách hàng: chỉ tiến độ KPI; không trạng thái sheet, lịch sử phiên bản, lỗi kỹ thuật
    with connect() as c:
        sid = KP.sheet_id(c)
    with connect() as c:
        has_versions = bool(KP.versions(c)) if sid else False
    from . import sheet_view as SV
    with connect() as c:
        pub = SV.published(c) if sid else None
    right = T.page_header(ui, "flag", "Cam kết KPI",
                          "Tiến độ cam kết từng tháng: thứ hạng từ khóa và lượt khách từ Google, AI.", eyebrow="KPI")
    with right:
        sync_btn = None
        if sid and ed:  # người chỉ xem không mở được sheet nội bộ
            ui.button(icon="open_in_new", on_click=lambda: ui.navigate.to(
                f"https://docs.google.com/spreadsheets/d/{sid}/edit", new_tab=True)).props(
                'flat round dense color=grey-8 aria-label="Mở sheet dự án"').tooltip("Mở sheet dự án")
        if sid and ed and has_versions:
            ui.button("Sửa cam kết", icon="edit", on_click=lambda: ui.navigate.to("/kpi/sua")).props(
                "unelevated no-caps")
        elif sid and ed:  # sheet vừa gắn: nhập một lần từ sheet, sau đó tool là nơi quản lý
            sync_btn = ui.button("Nhập từ sheet", icon="download", on_click=lambda: do_sync()).props(
                "unelevated no-caps")
        if sid and ed:
            with ui.button(icon="more_vert").props('flat round dense color=grey-8 aria-label="Thêm"'):
                with ui.menu():
                    if has_versions:
                        ui.menu_item("Ghi lên sheet ngay", on_click=lambda: do_publish())
                    ui.menu_item("Đổi sheet / tạo sheet dự án mới", on_click=lambda: ask_unlink())
                    if pub and not cl:
                        ui.separator()
                        ui.label(f"Đã ghi lên sheet lúc {_local(pub['at'])} · {pub['tabs']} tab").classes(
                            "text-xs muted q-px-md q-py-sm")

    def ask_unlink():
        with ui.dialog() as dlg, ui.card().style("border-radius:16px; max-width:520px"):
            ui.label("Gỡ sheet đang gắn?").classes("text-lg font-semibold")
            ui.label("Tool thôi đọc sheet này; file trên Drive vẫn còn. Sau đó màn KPI hiện wizard tạo sheet dự án "
                     "mới (hoặc ô dán link sheet khác). Phiên bản KPI đã lưu của sheet này vẫn giữ: dán lại link cũ "
                     "là dùng tiếp.").classes("text-sm")

            def go():
                with connect() as c:
                    KP.unlink_sheet(c)
                dlg.close()
                ui.navigate.reload()

            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Gỡ sheet", on_click=go).props("unelevated no-caps color=negative")
        dlg.open()

    async def do_publish():
        from . import sheet_view as SV
        ui.notify("Đang ghi lên sheet…", position="bottom-right")
        try:
            def work():
                with connect() as c:
                    info = SV.publish(c, cfg)
                    KP._setting(c, "sheet_view_fp", SV.fingerprint(c, cfg.site_url))
                    return info
            r = await run.io_bound(work)
            ui.notify(f"Đã ghi {r['tabs']} tab lên sheet ({r['rows']} dòng dữ liệu check)", type="positive")
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không ghi được lên sheet: {e}", type="negative", multi_line=True)

    async def do_sync():
        sync_btn.props("loading")
        try:
            def work():
                with connect() as c:
                    return KP.sync(c, cfg, user)
            r = await run.io_bound(work)
            msg = (f"Đã đồng bộ: {r['months']} tháng, {r.get('lines', 0)} cam kết, {r['keywords']} từ khóa cam kết"
                   + (f", thêm {r['added']} từ khóa vào check rank" if r["added"] else "")
                   + ("" if r["changed"] else " · KPI không đổi"))
            ui.notify(msg, type="positive")
            if r["over_budget"]:
                ui.notify(f"{len(r['over_budget'])} từ khóa chưa thêm được vì vượt ngân sách check rank",
                          type="warning", multi_line=True)
            if r["bad_url"]:
                ui.notify(f"{len(r['bad_url'])} dòng có URL mục tiêu không thuộc site: {r['bad_url'][0]}",
                          type="warning", multi_line=True)
        except KP.TabNotFound as e:  # tab đổi tên mà không đoán được: cho chọn tab, tool nhớ theo mã tab
            sync_btn.props(remove="loading")
            pick_tab(e)
            return
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không đồng bộ được: {e}", type="negative", multi_line=True)
        finally:
            sync_btn.props(remove="loading")
        ui.navigate.reload()

    def pick_tab(err) -> None:
        """Chọn tab thay cho tab không tìm thấy; tool lưu mã tab (không đổi khi đổi tên) rồi đồng bộ lại."""
        if not ed:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        label = {KP.KPI_TAB: "tab KPI cam kết", KP.KW_TAB: "tab Từ khóa cam kết"}.get(err.want, err.want)
        with ui.dialog() as dlg, ui.card().style("min-width: 460px; max-width: 94vw; border-radius: 14px"):
            ui.label(f"Không tìm thấy {label}").classes("text-lg font-semibold")
            ui.label("Chọn đúng tab, tool sẽ nhớ.").classes("text-sm muted")
            sel = ui.select(err.titles, label="Tab trong sheet").props("outlined dense").classes("w-full")

            async def go():
                if not sel.value:
                    return

                def work():
                    from googleapiclient.discovery import build

                    from . import auth
                    svc = build("sheets", "v4", credentials=auth.get_credentials(cfg, need=(auth.SHEETS_SCOPE,)),
                                cache_discovery=False)
                    meta = svc.spreadsheets().get(spreadsheetId=sid,
                                                  fields="sheets(properties(sheetId,title))").execute()
                    gid = next(x["properties"]["sheetId"] for x in meta["sheets"]
                               if x["properties"]["title"] == sel.value)
                    with connect() as c:
                        KP.set_tab_id(c, sid, err.want, gid)
                await run.io_bound(work)
                dlg.close()
                await do_sync()

            with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
                ui.button("Hủy", on_click=dlg.close).props("flat no-caps")
                ui.button("Dùng tab này", on_click=go).props("unelevated no-caps color=primary")
        dlg.open()

    if not sid:
        if cl:
            T.empty_state(ui, "flag", "Chưa có KPI cam kết", "Tiến độ KPI sẽ hiện ở đây khi cam kết được thiết lập.")
            return
        _setup(ui, cfg, connect, ed, user, app_connect, project)
        return

    with connect() as c:
        KP.snapshot_keywords(c, cfg.site_url, date.today())  # từ khóa cam kết theo bộ Cam kết trên tool
        vs = KP.versions(c)
    if not vs:
        if cl:
            T.empty_state(ui, "flag", "Chưa có KPI cam kết", "Tiến độ KPI sẽ hiện ở đây khi cam kết được thiết lập.")
        else:
            T.empty_state(ui, "download", "Chưa có KPI trên tool", "Bấm Nhập từ sheet để lấy cam kết, sau đó sửa trên tool.")
        return

    box = ui.column().classes("w-full gap-4").props('aria-busy="true"')
    with box:
        kpi_skeleton(ui, len((vs[-1]["data"] or {}).get("lines") or []) or 4)

    async def load():
        try:
            p = await run.io_bound(lambda: load_progress(cfg, watch=("organic", "ai")))
        except (Exception, SystemExit) as e:  # noqa: BLE001
            box.clear()
            with box:
                T.status_chip(ui, "Chưa tải được tiến độ KPI, vui lòng thử lại sau" if cl else
                              f"Không tính được tiến độ: {str(e)[:160]}", "red", "error")
            T.busy(box, False)
            return
        box.clear()
        T.busy(box, False)
        with box:
            if p and not p.get("start"):
                kpi_block(ui, p, compact=False)
            elif p:
                page_view(ui, p, ed and not cl, {"cfg": cfg, "connect": connect, "user": user}
                          if ed and not cl else None)
            if p and p.get("start"):
                with ui.expansion(f"Lộ trình {len(p['months'])} tháng", icon="timeline",
                                  caption="Tháng nào đạt, tháng nào cần bao nhiêu, đang tiến tới đâu",
                                  value=True).classes("w-full sr-card"):
                    full_table(ui, p)
                cur = next((m for m in p["months"] if m["status"] == "running"), None) or \
                    next((m for m in reversed(p["months"]) if m["status"] == "closed"), None)
                if cur or p.get("pre"):
                    keyword_table(ui, cur or p["pre"], cfg.site_url, p.get("lines"))
            with ui.expansion(f"Lịch sử phiên bản KPI ({len(vs)})", icon="history").classes(
                    "w-full sr-card" + (" hidden" if cl else "")):
                for v in reversed(vs):
                    d = v["data"]
                    ui.label(f"Từ {_vn(v['day'])}/{v['day'][:4]} · {len(d['months'])} tháng · {len(d['lines'])} cam "
                             f"kết · {len(d.get('keywords', []))} từ khóa · bắt đầu {d['start'] or 'chưa nhập'}"
                             ).classes("text-sm")
                ui.label("Tháng đã qua được chấm theo phiên bản có hiệu lực cuối tháng đó.").classes("text-xs muted")

    from nicegui import background_tasks
    background_tasks.create(load())


def keyword_table(ui, m: dict, site: str, lines: list | None = None) -> None:
    """Từng từ khóa cam kết: vị trí lần check cuối trong tháng, đang ở mốc Top nào của bộ (mốc chung của bộ: Top 3 /
    5 / 10…), còn cách mốc kế tiếp bao nhiêu bậc. Mặc định chỉ hiện từ khóa chưa vào mốc nào (việc cần làm)."""
    rk = m["rank"]
    rank_lines = [ln for ln in (lines or []) if ln.get("kind") == "rank" and ln.get("mode") != "own"]
    set_tops: dict = {}
    names: dict = {}
    for ln in rank_lines:
        if ln.get("set"):
            set_tops.setdefault(ln["set"], set()).add(ln["top"])
            names[ln["set"]] = ln.get("name") or ""
    main_tops = sorted({ln["top"] for ln in rank_lines if not ln.get("set")}) or [3, 5, 10]
    rows = []
    for x in rk["items"]:
        tops = sorted(set_tops.get(x.get("set")) or main_tops)
        r = x["rank"]
        reached = next((t for t in tops if r is not None and r <= t), None)
        if x["date"] is None:
            pos, note, st = "–", "chưa check", "Chưa check"
        else:
            pos = str(r) if r is not None else f">{x['depth']}"
            st = "Đã vào Top" if reached else "Chưa vào Top"
            # mốc kế tiếp: chưa vào mốc nào thì mốc lớn nhất (dễ nhất); đã vào thì mốc nhỏ hơn liền trên
            smaller = [t for t in tops if reached is not None and t < reached]
            nxt = max(tops) if reached is None else (max(smaller) if smaller else None)
            note = ""
            if r is not None and nxt is not None and r > nxt:
                note = f"cần lên {r - nxt} bậc để vào Top {nxt}"
            elif r is None:
                note = f"ngoài Top {x['depth']}"
        rows.append({"keyword": x["keyword"], "group": names.get(x.get("set"), ""),
                     "target": f"Top {reached}" if reached else "", "tn": reached or 999, "pos": pos,
                     "pn": r if r is not None else 999, "note": note, "status": st,
                     "url": (x["url"] or "").replace(site.rstrip("/"), "") if x.get("url") else ""})
    rows.sort(key=lambda z: (z["status"] != "Chưa vào Top", z["status"] == "Chưa check", z["pn"], z["keyword"]))
    last = max((x["date"] for x in rk["items"] if x["date"]), default=None)
    sub = ((f"Check lần cuối {_vn(last)}" if last else "Chưa check trong tháng này") if m["n"] else
           "Trước khi bắt đầu dự án")
    with T.section(ui, f"Từ khóa cam kết · {rk['total']}", "search", sub, href="/rank", link_text="Thứ hạng"):
        if not rows:
            ui.label("Chưa có từ khóa cam kết nào.").classes("text-sm muted")
            return
        top_max = max(main_tops)
        filt = {"Chưa vào Top": f"Chưa vào Top {top_max}" if not set_tops else "Chưa vào Top",
                "Đã vào Top": "Đã vào Top", "Chưa check": "Chưa check", "all": "Tất cả"}
        cnt = {k: sum(1 for r in rows if r["status"] == k) for k in filt if k != "all"}
        state = {"f": "Chưa vào Top" if cnt["Chưa vào Top"] else "all", "q": ""}

        def shown() -> list[dict]:
            q = state["q"].strip().lower()
            return [r for r in rows if (state["f"] == "all" or r["status"] == state["f"])
                    and (not q or q in r["keyword"].lower())]

        def apply() -> None:
            tbl.rows = shown()
            tbl.update()
            empty.set_visibility(not tbl.rows)

        def set_f(v) -> None:
            state["f"] = v
            apply()

        def set_q(v) -> None:
            state["q"] = v or ""
            apply()
        with ui.row().classes("w-full items-center gap-2 q-mb-sm no-wrap sr-kw-bar"):
            with ui.element("div").classes("sr-kg-filt col"):  # màn hẹp: cuộn ngang trong khung, trang không tràn
                ui.toggle({k: (f"{v} · {cnt[k]}" if k in cnt else f"{v} · {len(rows)}") for k, v in filt.items()
                           if k == "all" or cnt[k]}, value=state["f"], on_change=lambda e: set_f(e.value)).props(
                    SEG).classes("sr-seg")
            ui.input(placeholder="Tìm từ khóa", on_change=lambda e: set_q(e.value)).props(
                'dense outlined clearable debounce=250 aria-label="Tìm từ khóa"').classes("sr-kw-q").add_slot(
                "prepend", '<q-icon name="search" size="18px" />')
        cols = [
            {"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left", "sortable": True},
            {"name": "pos", "label": "Vị trí hiện tại", "field": "pn", "align": "left", "sortable": True},
            {"name": "target", "label": "Đang ở mốc", "field": "tn", "align": "center", "sortable": True},
        ]
        tbl = ui.table(columns=cols, rows=shown(), row_key="keyword", pagination=25).classes(
            "w-full sr-kw-tbl").props("flat dense" + (" hide-bottom" if len(rows) <= 25 else ""))
        tbl.add_slot("body-cell-keyword", """
            <q-td :props="props"><div class="sr-kw-k">{{ props.row.keyword }}</div>
              <div v-if="props.row.url" class="sr-kw-u ellipsis" :title="props.row.url">{{ props.row.url }}</div>
            </q-td>""")
        tbl.add_slot("body-cell-target", """
            <q-td :props="props"><span v-if="props.row.target" class="sr-kw-top">{{ props.row.target }}</span>
              <div v-if="props.row.group" class="sr-kw-g">{{ props.row.group }}</div>
              <span v-else class="muted">–</span></q-td>""")
        tbl.add_slot("body-cell-pos", """
            <q-td :props="props"><span class="sr-kw-pos num">{{ props.row.pos }}</span>
              <span v-if="props.row.note" class="sr-kw-note">{{ props.row.note }}</span></q-td>""")
        tbl.add_slot("body-cell-status", """
            <q-td :props="props"><span class="sr-kw-chip" :class="props.value === 'Đã vào Top' ? 'ok' :
              (props.value === 'Chưa vào Top' ? 'bad' : '')">{{ props.value }}</span></q-td>""")
        empty = ui.label("Không có từ khóa khớp.").classes("text-sm muted q-pa-sm")
        empty.set_visibility(not tbl.rows)


def _local(iso: str) -> str:
    from datetime import datetime
    return f"{datetime.fromisoformat(iso).astimezone():%H:%M %d/%m}"


def _setup(ui, cfg, connect, ed: bool, user: str, app_connect=None, project: dict | None = None) -> None:
    """Dự án chưa có sheet: wizard thiết lập cam kết rồi tạo sheet dự án trên Drive, hoặc dán link sheet đã có."""
    from nicegui import run

    from . import projects as PJ
    from .okr import parse_date
    from .projects import domain
    host = domain(cfg.site_url)
    master = ""
    if app_connect:
        with app_connect() as c:
            master = PJ.master_sheet(c)
    if not ed:
        with T.section(ui, "Chưa có sheet KPI", "table_view"):
            ui.label("Chỉ người được sửa mới thiết lập được cam kết.").classes("text-sm muted")
        return

    data = {"project": f"SEO {host}", "start": date.today().isoformat(), "months": list(range(1, 13)),
            "baseline": {"organic": None, "ai": None}, "lines": []}
    with T.section(ui, "Thiết lập cam kết KPI", "flag",
                   "Điền bảng cam kết theo tháng và bộ từ khóa từng mốc Top, tool tạo sẵn sheet dự án."):
        ui.label("Đã có sheet cam kết của khách? Bấm AI đọc sheet cam kết để điền sẵn bảng bên dưới.").classes(
            "text-sm muted")
    _edit_form(ui, cfg, connect, user, "", {"data": data, "keywords": [], "fingerprint": None, "old_format": False},
               create={"master": master, "app_connect": app_connect, "project": project})

    def use_link():
        if not A.is_admin(user):  # sheet có sẵn đọc / ghi bằng token Google chung của chủ: chỉ Owner / Admin
            ui.notify("Chỉ Owner hoặc Admin gắn được sheet có sẵn", type="warning")
            return
        try:
            with connect() as c:
                KP.set_sheet(c, link.value)
            ui.navigate.reload()
        except ValueError as e:
            ui.notify(str(e), type="warning")

    with T.section(ui, "Đã có sheet", "link", "Sheet có 2 tab 'KPI cam kết' và 'Từ khóa cam kết' (mẫu cũ hay mới "
                                              "đều đọc được)"):
        if A.is_admin(user):
            with ui.row().classes("items-center gap-3"):
                link = ui.input(placeholder="Dán link Google Sheet đã có").props("outlined dense").classes("w-96")
                ui.button("Dùng sheet này", on_click=use_link).props("outline no-caps")
        else:
            ui.label("Gắn sheet có sẵn: nhờ Admin hoặc Owner."
                     ).classes("text-sm muted")


# ---- Sửa cam kết trên tool ----

TABLE_ROWS = (  # khóa, tên, Top N (None = lượt truy cập), nguồn
    ("top3", "Top 3", 3, None), ("top5", "Top 5", 5, None), ("top10", "Top 10", 10, None),
    ("organic", "Organic traffic", None, "organic"), ("ai", "AI traffic", None, "ai"),
)


def build_kpi_edit_page(ui, cfg, connect, user) -> None:
    """Sửa cam kết: thông tin dự án, bảng cam kết theo tháng (Top 3 / 5 / 10, Organic, AI), bộ từ khóa của từng mốc
    Top. Lưu = phiên bản KPI mới trên tool + bộ từ khóa vào bộ Cam kết, rồi tool ghi lại sheet."""
    with connect() as c:
        sid = KP.sheet_id(c)
    right = T.page_header(ui, "edit", "Sửa cam kết KPI", "Hoạch định cam kết theo từng tháng ngay trên tool.",
                          eyebrow="KPI")
    with right:
        ui.button("Quay lại", icon="arrow_back", on_click=lambda: ui.navigate.to("/kpi")).props("flat no-caps")
    with connect() as c:
        cur = KP.version_at(KP.versions(c), date.today())
    if not cur:
        T.empty_state(ui, "flag", "Chưa có KPI cam kết", "Thiết lập cam kết ở màn KPI cam kết trước.")
        return
    _edit_form(ui, cfg, connect, user, sid, {"data": cur, "keywords": [], "fingerprint": None, "old_format": False})


def _edit_form(ui, cfg, connect, user, sid: str, loaded: dict, create: dict | None = None) -> None:
    """create: dự án chưa có sheet — Lưu = tạo sheet dự án trên Drive (từ sheet mẫu gốc) với bảng cam kết và bộ từ
    khóa này, rồi đồng bộ về tool."""
    from nicegui import run

    from . import rank as R
    from .okr import parse_date
    data = loaded["data"]
    months0 = list(data["months"]) or list(range(1, 13))
    # ---- đưa các dòng đang có vào bảng; dòng kiểu khác (đạt Top mục tiêu riêng, cộng dồn…) giữ nguyên
    rows: dict[str, dict] = {k: {"unit": "count", "values": {}} for k, *_ in TABLE_ROWS}
    taken, extras, merged = set(), [], 0
    set_lines = []  # dòng của bộ từ khóa riêng (bộ Cam kết có tên, mỗi bộ nhiều mốc Top)
    for ln in data["lines"]:
        key = None
        if ln["kind"] == "rank" and ln.get("mode") != "own" and ln.get("set"):
            set_lines.append(ln)
            continue
        if ln["kind"] == "rank" and ln.get("mode") != "own" and ln.get("top"):
            key = f"top{ln['top']}"
        elif ln["kind"] == "level":
            key = ln["source"]
        if key and key in taken:
            merged += 1  # dòng trùng: giữ dòng đầu
            continue
        if key:
            taken.add(key)
            rows[key] = {"unit": ln.get("unit", "count") if key.startswith("top") else "count",
                         "values": {int(k): v for k, v in ln["targets"].items() if v is not None}}
        else:
            extras.append(ln)
    with connect() as c:
        kws = KP.commitment_keywords(c, cfg.site_url)
        main_set = R.kpi_set(c, cfg.site_url)
        all_sets = R.sets(c, cfg.site_url)
        tracked = {r[0].lower() for r in c.execute(
            "SELECT keyword FROM rank_keywords WHERE site = ? AND removed_at IS NULL", (cfg.site_url,))}

    def kw_text(lst) -> str:
        return "\n".join(k["keyword"] + (f" | {k['url']}" if k.get("url") else "") for k in lst)
    # bộ chính (bộ Cam kết đầu tiên ở Thứ hạng) + các bộ riêng (bộ loại Cam kết khác, vd Từ khóa thúc đẩy)
    main = {"key": "main", "main": True, "set": main_set["id"] if main_set else None,
            "name": (main_set or {}).get("name") or "Cam kết", "orig": None, "tiers": [], "texts": {},
            "deleted": False}
    groups: list[dict] = [main]
    for ln in set_lines:
        st = next((x for x in all_sets if x["id"] == ln["set"]), None)
        if not st or (main_set and st["id"] == main_set["id"]):
            extras.append(ln)
            continue
        g = next((x for x in groups if x["set"] == st["id"]), None)
        if not g:
            g = {"key": f"s{st['id']}", "main": False, "set": st["id"], "name": ln.get("name") or st["name"],
                 "orig": st["name"], "tiers": [], "texts": {}, "deleted": False}
            groups.append(g)
        n = int(ln.get("top") or 10)
        if n not in g["tiers"]:  # mỗi mốc Top của bộ là một dòng cam kết (đếm trên cả bộ)
            g["tiers"].append(n)
            rows[f"{g['key']}:{n}"] = {"unit": ln.get("unit", "count"),
                                       "values": {int(k): v for k, v in ln["targets"].items() if v is not None}}
    for st in all_sets:  # bộ Cam kết khác chưa có dòng cam kết: vẫn hiện để đặt lộ trình
        if st["kind"] == "kpi" and not st["draft"] and (not main_set or st["id"] != main_set["id"]) \
                and not any(g["set"] == st["id"] for g in groups):
            groups.append({"key": f"s{st['id']}", "main": False, "set": st["id"], "name": st["name"],
                           "orig": st["name"], "tiers": [], "texts": {}, "deleted": False})
    custom_ids0 = {g["set"] for g in groups if not g["main"]}
    for g in groups:
        own = [k for k in kws if (k.get("set") == g["set"] if not g["main"] else k.get("set") not in custom_ids0)]
        if g["main"]:  # bộ chính: Top 3 / 5 / 10 + mốc khác đã có dòng cam kết
            g["tiers"] = sorted({3, 5, 10} | {int(k[3:]) for k in taken if k.startswith("top")})
        else:
            g["tiers"] = sorted(g["tiers"]) or [10]
        g["texts"][0] = kw_text(own)  # cả bộ một danh sách
        for n in g["tiers"]:
            rows.setdefault(f"top{n}" if g["main"] else f"{g['key']}:{n}", {"unit": "count", "values": {}})
    main_had = bool(main["texts"].get(0, "").strip())
    gmap = {g["key"]: g for g in groups}
    state = {"months": months0}

    if loaded["old_format"]:
        T.status_chip(ui, "Sheet đang ở mẫu cũ: bấm Lưu thì tab KPI cam kết được ghi lại theo mẫu mới", "amber", "info")

    # ---------------------------------------------------------------- thông tin dự án + AI đọc sheet
    with T.section(ui, "Thông tin dự án", "info"):
        with ui.row().classes("items-end gap-3 wrap"):
            name = ui.input("Tên dự án", value=data["project"]).props("outlined dense").classes("w-72")
            start = ui.input("Ngày bắt đầu", value=(f"{data['start'][8:10]}/{data['start'][5:7]}/{data['start'][:4]}"
                                                    if data["start"] else ""),
                             placeholder="dd/mm/yyyy").props('outlined dense mask="##/##/####"').classes("w-44")
            with ui.column().classes("gap-1"):
                ui.label("Số tháng").classes("text-xs muted")
                with ui.row().classes("items-center gap-2 no-wrap"):
                    quick = ui.toggle({3: "3", 6: "6", 9: "9", 12: "12"},
                                      value=len(months0) if len(months0) in (3, 6, 9, 12) else None,
                                      on_change=lambda e: e.value and set_months(e.value)).props(SEG).classes("sr-seg")
                    n_months = ui.number(value=len(months0), min=1, max=36, step=1, format="%.0f").props(
                        'outlined dense suffix="tháng"').classes("w-28")
                    n_months.on("change", lambda _: set_months(int(n_months.value or 1)))
            ui.space()
            from . import ai_settings as _AIS
            ai_btn = ui.button("AI đọc sheet cam kết", icon="auto_awesome", on_click=lambda: ask_link()).props(
                "unelevated no-caps color=deep-purple-1 text-color=deep-purple-9")
            ai_btn.tooltip("Dán link Google Sheet cam kết: AI đọc bảng cam kết và danh sách từ khóa, điền sẵn vào "
                           "bảng bên dưới để bạn kiểm tra rồi Lưu")
            ai_btn.set_visibility(_AIS.enabled(cfg.site_url, "kpi_import"))
        window = ui.label().classes("text-xs muted q-mt-xs")
        if merged:
            ui.label(f"Đã gộp {merged} cam kết trùng (giữ dòng đầu).").classes("text-xs").style("color:#8F5F14")

    def month_dates(n: int) -> str:
        d = parse_date(start.value, date.today()) if start.value else None
        if not d:
            return ""
        s, e = KP.month_window(d, n)
        return f"{s:%d/%m}–{e:%d/%m}"

    def paint_window() -> None:
        ms = state["months"]
        d0, d1 = month_dates(ms[0]), month_dates(ms[-1])
        window.text = (f"Tháng 1: {d0} · Tháng {ms[-1]}: {d1}" if d0 else "Nhập ngày bắt đầu để thấy ngày từng tháng")

    def set_months(n: int) -> None:
        n = max(1, min(36, int(n)))
        state["months"] = list(range(1, n + 1))
        n_months.value = n
        quick.value = n if n in (3, 6, 9, 12) else None
        paint_window()
        table.refresh()

    start.on("blur", lambda _: (paint_window(), table.refresh()))
    paint_window()

    # ---------------------------------------------------------------- bộ từ khóa (khai báo trước bảng)
    tier_box: dict[int, object] = {}  # ô từ khóa các mốc của bộ chính (AI đọc sheet điền vào)

    def parse_lines(text: str) -> list[tuple[str, str]]:
        out = []
        for line in (text or "").splitlines():
            kw, _, url = line.partition("|")
            kw = " ".join(kw.split())
            if kw:
                out.append((kw, url.strip()))
        return out

    def rkey(g: dict, n: int) -> str:
        return f"top{n}" if g["main"] else f"{g['key']}:{n}"

    def tkey(g: dict, n: int) -> int:
        return 0  # mỗi bộ một ô từ khóa: mốc Top chỉ là dòng cam kết

    def glist(g: dict, n: int) -> list[tuple[str, str]]:
        return parse_lines(g["texts"].get(tkey(g, n), ""))

    def tier_list(n: int) -> list[tuple[str, str]]:
        return glist(main, n)

    def locate(key: str):
        for g in groups:
            for n in g["tiers"]:
                if rkey(g, n) == key:
                    return g, n
        return None

    def pool(key: str) -> int:
        hit_ = locate(key)
        return len(glist(*hit_)) if hit_ else 0

    def live_groups() -> list[dict]:
        return [g for g in groups if not g["deleted"]]

    def table_rows() -> list[tuple]:
        """Các dòng bảng cam kết. Nhiều bộ: mỗi bộ một nhóm có dòng tiêu đề ("__head__", tên, dòng phụ, kiểu)."""
        many = len(live_groups()) > 1
        out = []
        for i, g in enumerate(live_groups()):
            if many:
                k = len(glist(g, 0))
                out.append(("__head__", g["name"] or "Bộ mới", ("Bộ chính · " if g["main"] else "")
                            + f"{len(g['tiers'])} mốc Top · {k} từ khóa", f"g{i % 4}"))
            for n in sorted(g["tiers"]):
                out.append((rkey(g, n), f"Top {n}", n, None))
        if many:
            out.append(("__head__", "Lượt truy cập", "Organic và AI · phiên mỗi tháng", "traffic"))
        return out + list(TABLE_ROWS[3:])

    # ---------------------------------------------------------------- bảng cam kết theo tháng
    with T.section(ui, "Bảng cam kết theo tháng", "table_chart",
                   "Mỗi dòng một cam kết, mỗi cột một tháng. Để trống tháng không cam kết."):
        @ui.refreshable
        def table() -> None:
            ms = state["months"]
            cols = f"var(--kt2-lab, 170px) repeat({len(ms)}, minmax(76px, 1fr)) 36px"
            with ui.element("div").classes("sr-kt2-wrap"):
                with ui.element("div").classes("sr-kt2").style(f"grid-template-columns:{cols}"):
                    ui.label("Cam kết").classes("sr-kt2-h left")
                    for n in ms:
                        with ui.element("div").classes("sr-kt2-h"):
                            ui.label(f"Tháng {n}")
                            ui.label(month_dates(n)).classes("sr-kt2-d")
                    ui.label("").classes("sr-kt2-h")
                    for key, title, top, src in table_rows():
                        if key == "__head__":  # tiêu đề nhóm (một bộ từ khóa / lượt truy cập), trải hết hàng
                            with ui.element("div").classes(f"sr-kt2-grp {src}").style("grid-column: 1 / -1"):
                                with ui.row().classes("items-baseline gap-2 no-wrap sr-kt2-grpin"):
                                    ui.label(title).classes("sr-kt2-grpn")
                                    ui.label(top).classes("sr-kt2-grps")
                            continue
                        r = rows.setdefault(key, {"unit": "count", "values": {}})
                        with ui.element("div").classes("sr-kt2-lab"):
                            ui.label(title).classes("sr-kt2-name")
                            if top:
                                with ui.row().classes("items-center gap-1 no-wrap"):
                                    ui.toggle({"count": "Số", "pct": "%"}, value=r["unit"],
                                              on_change=lambda e, key=key: switch_unit(key, e.value)).props(
                                        SEG + " size=sm").classes("sr-seg sr-kt2-unit")
                                    ui.label(f"bộ {pool(key)} từ").classes("sr-kt2-pool")
                                over = over_need(key)
                                if over:
                                    ui.label(f"cần tới {over} · thiếu {over - pool(key)}").classes(
                                        "sr-kt2-over").tooltip(f"Lộ trình cần tới {over} từ khóa nhưng bộ {title} "
                                                               f"có {pool(key)}: dán thêm từ khóa ở bên dưới")
                            else:
                                ui.label("phiên / tháng").classes("sr-kt2-pool")
                        for n in ms:
                            v = r["values"].get(n)
                            shown = None if v is None else (round(v * 100, 1) if r["unit"] == "pct" else v)
                            ui.number(value=shown, min=0, format="%g", on_change=lambda e, key=key, n=n: put(key, n, e.value)
                                      ).props('dense borderless input-class="text-right"' + (
                                ' suffix="%"' if r["unit"] == "pct" else "")).classes("sr-kt2-in")
                        ui.button(icon="linear_scale", on_click=lambda _, key=key: spread(key)).props(
                            "flat round dense size=sm color=grey-7").tooltip(
                            "Chia đều: điền tháng đầu và tháng cuối rồi bấm để tool điền các tháng giữa")
            ui.label("Mẹo: điền tháng đầu và tháng cuối của lộ trình rồi bấm ↔ cuối dòng để chia đều các tháng giữa."
                     ).classes("text-xs muted q-mt-xs")
            if extras:
                ui.label(f"Giữ nguyên {len(extras)} cam kết kiểu khác: "
                         + ", ".join(KP.line_label(x) for x in extras) + ".").classes("text-xs muted q-mt-xs")

        def over_need(key: str) -> int:
            """Số từ khóa lớn nhất lộ trình cần nếu vượt bộ của mốc (0 = không vượt)."""
            r, size = rows[key], pool(key)
            need = max(((v if r["unit"] == "count" else v * size) for v in r["values"].values() if v is not None),
                       default=0)
            return int(round(need)) if r["values"] and need > size else 0

        def put(key: str, n: int, v) -> None:
            r = rows[key]
            if v in (None, ""):
                r["values"].pop(n, None)
            else:
                r["values"][n] = round(float(v) / 100, 4) if r["unit"] == "pct" else int(float(v))

        def switch_unit(key: str, unit: str) -> None:
            r = rows[key]
            if unit == r["unit"]:
                return
            size = pool(key) or 1
            r["values"] = {n: (round(v / size, 4) if unit == "pct" else round(v * size)) for n, v in r["values"].items()}
            r["unit"] = unit
            table.refresh()

        def spread(key: str) -> None:
            r, ms = rows[key], state["months"]
            have = [n for n in ms if r["values"].get(n) is not None]
            if len(have) < 2:
                ui.notify("Điền ít nhất tháng đầu và tháng cuối của lộ trình", type="warning")
                return
            a, b = have[0], have[-1]
            va, vb = r["values"][a], r["values"][b]
            for n in ms:
                if a < n < b:
                    v = va + (vb - va) * (n - a) / (b - a)
                    r["values"][n] = round(v, 4) if r["unit"] == "pct" else int(round(v))
            table.refresh()

        table()

    # ---------------------------------------------------------------- đồng bộ với Thứ hạng
    def track_text(lst: list) -> str:
        if not lst:
            return ""
        on = sum(1 for kw, _ in lst if kw.lower() in tracked)
        return (f"Cả {on} từ đang được check rank" if on == len(lst) else
                f"{on}/{len(lst)} từ đang được check rank · {len(lst) - on} từ mới")

    def append_to(g: dict, n: int, add: list[tuple[str, str]]) -> None:
        n = tkey(g, n)
        cur_ = g["texts"].get(n, "")
        have = {kw.lower() for kw, _ in parse_lines(cur_)}
        new = [f"{kw} | {url}" if url else kw for kw, url in add if kw.lower() not in have]
        if new:
            g["texts"][n] = (cur_.rstrip() + "\n" if cur_.strip() else "") + "\n".join(new)
            sets_area.refresh()
            table.refresh()
        ui.notify(f"Đã thêm {len(new)} từ khóa" + (f" ({len(add) - len(new)} từ đã có)" if len(add) > len(new) else ""),
                  type="positive" if new else "info", position="bottom-right")

    def pick_from_rank(add_fn) -> None:
        with connect() as c:
            rk = c.execute("SELECT k.keyword, u.url, k.set_id FROM rank_keywords k LEFT JOIN urls u ON u.id = k.url_id "
                           "WHERE k.site = ? AND k.removed_at IS NULL ORDER BY k.keyword", (cfg.site_url,)).fetchall()
        names = {x["id"]: x["name"] for x in all_sets}
        grouped: dict[str, dict] = {}  # một từ khóa ở nhiều bộ: một dòng, ghi đủ các bộ
        for kw, u, sid_ in rk:
            g = grouped.setdefault(kw.lower(), {"id": len(grouped), "keyword": kw, "full": u or "", "sids": [],
                                                "set": ""})
            g["full"] = g["full"] or (u or "")
            if sid_ not in g["sids"]:
                g["sids"].append(sid_)
        for g in grouped.values():
            g["set"] = ", ".join(names.get(x, "") for x in g["sids"] if names.get(x))
        data_rows = list(grouped.values())
        with ui.dialog() as d, ui.card().classes("sr-ar-dlg q-pa-none").style("width:640px"):
            with ui.row().classes("w-full items-center no-wrap gap-2 sr-ar-head"):
                ui.icon("playlist_add", size="20px").classes("q-mt-xs").style("color:#1E7C31")
                with ui.column().classes("gap-0 col"):
                    ui.label("Lấy từ khóa từ Thứ hạng").classes("sr-br-h")
                    ui.label("Chọn từ khóa đang check rank để đưa vào bộ này").classes("sr-br-sub")
                ui.button(icon="close", on_click=d.close).props('flat round dense aria-label="Đóng"')
            with ui.column().classes("w-full gap-2 sr-ar-body"):
                if not data_rows:
                    ui.label("Chưa có từ khóa nào ở trang Thứ hạng.").classes("text-sm muted")
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    opts = {0: "Mọi bộ"} | {x["id"]: f"{x['name']} · {x['count']}" for x in all_sets}
                    sel = ui.select(opts, value=0).props("dense outlined").classes("col")
                    q = ui.input(placeholder="Tìm từ khóa").props("dense outlined clearable debounce=200").classes(
                        "col")
                tbl = ui.table(columns=[{"name": "keyword", "label": "Từ khóa", "field": "keyword", "align": "left",
                                         "sortable": True},
                                        {"name": "set", "label": "Bộ", "field": "set", "align": "left"}],
                               rows=data_rows, row_key="id", selection="multiple", pagination=10).classes(
                    "w-full").props("flat dense")

                def refilt(_=None):
                    t = (q.value or "").strip().lower()
                    tbl.rows = [r for r in data_rows if (not sel.value or sel.value in r["sids"])
                                and (not t or t in r["keyword"].lower())]
                    tbl.update()
                sel.on_value_change(refilt)
                q.on_value_change(refilt)
            with ui.row().classes("w-full justify-end gap-2 sr-ar-foot"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")

                def take():
                    picked = [(r["keyword"], r["full"]) for r in tbl.selected]
                    if not picked:
                        ui.notify("Chưa chọn từ khóa nào", type="warning")
                        return
                    add_fn(picked)
                    d.close()
                ui.button("Thêm vào bộ", icon="south", on_click=take).props("unelevated no-caps")
        d.on("hide", d.delete)
        d.open()

    async def push_now(g: dict, n: int = 0) -> None:
        lst = glist(g, 0)
        if not lst:
            ui.notify("Bộ chưa có từ khóa", type="warning")
            return
        if not g["main"] and not (g["name"] or "").strip():
            ui.notify("Đặt tên bộ trước", type="warning")
            return

        def work():
            from . import keywords as K
            with connect() as c:
                if g["main"]:
                    sid_ = R.kpi_set(c, cfg.site_url, create=True, user=str(user))["id"]
                else:
                    if not g["set"]:
                        g["set"] = R.create_set(c, cfg.site_url, g["name"].strip(), str(user), kind="kpi",
                                                schedule=R.get_schedule(c))
                        g["orig"] = g["name"].strip()
                    sid_ = g["set"]
                return R.add_keywords(c, cfg.site_url, cfg.rank, K.latest_date(c, cfg.site_url),
                                      [(kw, url or None) for kw, url in lst], str(user), set_id=sid_)
        try:
            res = await run.io_bound(work)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Chưa thêm được: {str(e)[:200]}", type="negative", multi_line=True)
            return
        tracked.update(kw.lower() for kw, _ in lst if kw not in res["over_budget"])
        msg = f"Đã đưa {len(res['added'])} từ mới vào check rank"
        if res["over_budget"]:
            msg += f"; {len(res['over_budget'])} từ vượt ngân sách check rank"
        if res["bad_url"]:
            msg += f"; {len(res['bad_url'])} dòng có URL không thuộc website"
        ui.notify(msg, type="positive" if not res["over_budget"] else "warning", multi_line=True)
        sets_area.refresh()

    # ---------------------------------------------------------------- các bộ từ khóa
    with T.section(ui, "Bộ từ khóa", "search",
                   "Mỗi bộ một danh sách từ khóa; mốc Top (3 / 5 / 10…) là mốc chung, đếm bao nhiêu từ của cả bộ vào "
                   "Top đó. Mỗi dòng một từ khóa, URL mục tiêu sau dấu | nếu có. Tool tự check rank các từ khóa này."):
        ui.label("Đồng bộ với Thứ hạng: mỗi bộ là một bộ loại Cam kết ở trang Thứ hạng; thêm / bỏ từ khóa hay đổi "
                 "Top mục tiêu ở đó thì ở đây và trang KPI tự cập nhật theo.").classes("text-xs muted q-mb-sm")

        @ui.refreshable
        def sets_area() -> None:
            tier_box.clear()
            for g in live_groups():
                group_card(g)
            ui.button("Thêm bộ từ khóa", icon="add", on_click=lambda: add_group()).props(
                "outline no-caps").classes("sr-kt2-add").tooltip(
                "Một bộ mới (vd Từ khóa thúc đẩy): danh sách từ khóa riêng, cam kết bao nhiêu từ của bộ vào Top N")

        def group_card(g: dict) -> None:
            with ui.element("div").classes("sr-kt2-group"):
                with ui.row().classes("w-full items-center gap-2 sr-kt2-ghead"):
                    if g["main"]:
                        ui.label(g["name"]).classes("sr-kt2-gname")
                        ui.label("Bộ chính").classes("sr-kt2-gtag")
                    else:
                        nm = ui.input(value=g["name"], placeholder="Tên bộ, vd Từ khóa thúc đẩy").props(
                            'dense outlined aria-label="Tên bộ từ khóa"').classes("sr-kt2-cname")

                        def rename(_=None, g=g, nm=nm):
                            g["name"] = " ".join((nm.value or "").split())[:60]
                            table.refresh()
                        nm.on("blur", rename)
                    ui.space()
                    if not g["main"]:
                        ui.button(icon="delete_outline", on_click=lambda _, g=g: ask_drop(g)).props(
                            'flat round dense color=grey-7 aria-label="Bỏ bộ khỏi cam kết"').tooltip(
                            "Bỏ bộ khỏi cam kết")
                # mốc Top: mỗi mốc là một dòng cam kết, đếm trên cả bộ
                with ui.row().classes("w-full items-center gap-2 sr-kt2-tops"):
                    ui.label("Mốc cam kết:").classes("text-xs muted")
                    for n in sorted(g["tiers"]):
                        removable = (n not in (3, 5, 10)) if g["main"] else len(g["tiers"]) > 1
                        with ui.element("span").classes("sr-kt2-topchip"):
                            ui.label(f"Top {n}")
                            if removable:
                                ui.button(icon="close", on_click=lambda _, n=n, g=g: drop_tier(g, n)).props(
                                    f'flat round dense size=xs aria-label="Bỏ mốc Top {n}"')
                    with ui.button("Thêm mốc", icon="add").props("flat no-caps dense size=sm color=grey-8"):
                        with ui.menu():
                            for n in (1, 3, 5, 10, 20, 30, 50, 100):
                                if n not in g["tiers"]:
                                    ui.menu_item(f"Top {n}", on_click=lambda _, n=n, g=g: add_tier(g, n))
                            ui.separator()
                            with ui.row().classes("items-center no-wrap gap-1 q-px-sm q-py-xs"):
                                num = ui.number(placeholder="Top khác", min=1, max=100, step=1, format="%.0f").props(
                                    "dense outlined").style("width:110px")
                                ui.button("Thêm", on_click=lambda _, g=g, num=num: add_tier(g, num.value)).props(
                                    "flat no-caps dense")
                cnt = ui.label().classes("sr-kt2-tc q-mt-sm")
                ta = ui.textarea(value=g["texts"].get(0, ""), placeholder="giá tròng kính\nkính râm | https://…").props(
                    "outlined autogrow input-style='min-height:140px'").classes("w-full")
                stat = ui.label().classes("sr-kt2-trk")

                def recount(_=None, g=g, ta=ta, cnt=cnt, stat=stat):
                    g["texts"][0] = ta.value or ""
                    lst = glist(g, 0)
                    cnt.text = (f"{len(lst)} từ khóa · đếm bao nhiêu từ của cả bộ vào "
                                + " / ".join(f"Top {n}" for n in sorted(g["tiers"])))
                    stat.text = track_text(lst)
                ta.on_value_change(recount)
                ta.on("blur", lambda _: table.refresh())
                recount()
                with ui.row().classes("items-center gap-1 sr-kt2-tools"):
                    ui.button("Lấy từ Thứ hạng", icon="playlist_add",
                              on_click=lambda _, g=g: pick_from_rank(lambda add: append_to(g, 0, add))).props(
                        "flat no-caps dense size=sm color=grey-8")
                    ui.button("Check rank ngay", icon="radar", on_click=lambda _, g=g: push_now(g)).props(
                        "flat no-caps dense size=sm color=grey-8").tooltip(
                        "Thêm các từ mới của bộ vào check rank ngay (không cần chờ Lưu cam kết)")

        def add_tier(g: dict, n) -> None:
            try:
                n = int(n)
            except (TypeError, ValueError):
                ui.notify("Nhập mốc Top từ 1 đến 100", type="warning")
                return
            if not 1 <= n <= 100:
                ui.notify("Mốc Top từ 1 đến 100", type="warning")
                return
            if n in g["tiers"]:
                ui.notify(f"Bộ đã có mốc Top {n}", type="info")
                return
            g["tiers"].append(n)
            rows.setdefault(rkey(g, n), {"unit": "count", "values": {}})
            sets_area.refresh()
            table.refresh()

        def drop_tier(g: dict, n: int) -> None:
            def do() -> None:
                g["tiers"].remove(n)
                sets_area.refresh()
                table.refresh()
            if not any(v is not None for v in rows.get(rkey(g, n), {}).get("values", {}).values()):
                do()
                return
            with ui.dialog() as d, ui.card().style("width:440px; max-width:94vw; border-radius:14px"):
                ui.label(f"Bỏ mốc Top {n}?").classes("text-lg font-semibold")
                ui.label(f"Lộ trình cam kết Top {n} của bộ này bị bỏ khi bấm Lưu. Từ khóa của bộ giữ nguyên.").classes(
                    "text-sm muted")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Hủy", on_click=d.close).props("flat no-caps")
                    ui.button("Bỏ mốc", on_click=lambda: (d.close(), do())).props("unelevated no-caps color=red-8")
            d.on("hide", d.delete)
            d.open()

        def add_group() -> None:
            key = f"n{len(groups) + 1}"
            g = {"key": key, "main": False, "set": None, "name": "", "orig": None, "tiers": [10], "texts": {},
                 "deleted": False}
            groups.append(g)
            gmap[key] = g
            for n in g["tiers"]:
                rows.setdefault(rkey(g, n), {"unit": "count", "values": {}})
            sets_area.refresh()
            table.refresh()

        def ask_drop(g: dict) -> None:
            with ui.dialog() as d, ui.card().style("width:440px; max-width:94vw; border-radius:14px"):
                ui.label(f"Bỏ bộ “{g['name'] or 'Bộ mới'}” khỏi cam kết?").classes("text-lg font-semibold")
                ui.label("Lộ trình của bộ này bị bỏ khi bấm Lưu. Từ khóa vẫn được check rank (bộ chuyển thành loại "
                         "Theo dõi ở trang Thứ hạng).").classes("text-sm muted")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Hủy", on_click=d.close).props("flat no-caps")

                    def drop():
                        g["deleted"] = True
                        d.close()
                        sets_area.refresh()
                        table.refresh()
                    ui.button("Bỏ bộ", on_click=drop).props("unelevated no-caps color=red-8")
            d.on("hide", d.delete)
            d.open()

        sets_area()

    # ---------------------------------------------------------------- AI đọc sheet
    def ask_link() -> None:
        with ui.dialog() as d, ui.card().style("width: 520px; max-width: 94vw; border-radius: 14px"):
            ui.label("AI đọc sheet cam kết").classes("text-lg font-semibold")
            ui.label("Dán link Google Sheet có bảng cam kết (bố cục nào cũng được). Tài khoản Google của tool cần "
                     "được xem sheet này.").classes("text-sm muted")
            link = ui.input("Link Google Sheet", value=f"https://docs.google.com/spreadsheets/d/{sid}/edit" if sid
                            else "").props("outlined dense").classes("w-full")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")

                async def go():
                    import re as _re
                    m = _re.search(r"/d/([A-Za-z0-9_-]+)", link.value or "")
                    target = m.group(1) if m else (link.value or "").strip()
                    if not _re.fullmatch(r"[A-Za-z0-9_-]{20,}", target):
                        ui.notify("Không nhận ra link Google Sheet", type="warning")
                        return
                    d.close()
                    await ai_read(target)
                ui.button("Đọc sheet", icon="auto_awesome", on_click=go).props(
                    "unelevated no-caps color=deep-purple-1 text-color=deep-purple-9")
        d.on("hide", d.delete)
        d.open()

    async def ai_read(target: str) -> None:
        from . import ai_kpi as AK
        from . import ai_settings as AIS
        from . import points as PT
        try:
            prov = AW_provider()
        except Exception as e:  # noqa: BLE001
            ui.notify(str(e), type="warning", multi_line=True)
            return
        entry = PT.take(ui, user, cfg, "ai_kpi", detail="đọc sheet cam kết")
        if entry is False:
            return
        ai_btn.props("loading")
        try:
            def work():
                text = AK.sheet_text(cfg, target)
                return AK.read(cfg, text, prov)
            res, used = await run.io_bound(work)
        except Exception as e:  # noqa: BLE001
            PT.give_back(entry)
            AIS.log_call(cfg.site_url, "kpi_import", "manual", str(user), prov, False, str(e))
            ui.notify(f"AI chưa đọc được sheet: {str(e)[:200]}", type="warning", multi_line=True)
            return
        finally:
            ai_btn.props(remove="loading")
        AIS.log_call(cfg.site_url, "kpi_import", "manual", str(user), used, True,
                     credits=PT.cost("ai_kpi") if PT.member(user) else 0)
        preview(res)

    def AW_provider():
        from . import ai_writer as AW
        return AW.provider(cfg, "kpi_import")

    def preview(res: dict) -> None:
        names = {k: t for k, t, *_ in TABLE_ROWS}
        with ui.dialog() as d, ui.card().classes("sr-ar-dlg q-pa-none").style("width:640px"):
            with ui.row().classes("w-full items-center no-wrap gap-2 sr-ar-head"):
                ui.icon("auto_awesome", size="20px").classes("sr-br-ico")
                ui.label("AI đã đọc sheet cam kết").classes("sr-br-h col")
                ui.button(icon="close", on_click=d.close).props("flat round dense")
            with ui.column().classes("w-full gap-2 sr-ar-body"):
                ui.label(f"{res['months']} tháng" + (f" · bắt đầu {res['start']}" if res["start"] else "")).classes(
                    "text-sm")
                for key, r in res["rows"].items():
                    vals = [v for v in r["values"] if v is not None]
                    if vals:
                        last = vals[-1]
                        ui.label(f"{names[key]}: {len(vals)} tháng có cam kết, tháng cuối "
                                 + (f"{last * 100:.0f}%" if r["unit"] == "pct" else F.n(last))).classes("text-sm")
                for n, lst in res["keywords"].items():
                    if lst:
                        ui.label(f"Bộ Top {n}: {len(lst)} từ khóa").classes("text-sm")
                if res["dropped"]:
                    ui.label(f"Đã bỏ {res['dropped']} ô AI đưa ra nhưng không thấy trong sheet.").classes(
                        "text-xs").style("color:#8F5F14")
                if res["notes"]:
                    ui.label(res["notes"]).classes("sr-br-headline q-mx-none")
                ui.label("Bấm Điền vào bảng để xem trên tool; chưa lưu cho tới khi bạn bấm Lưu cam kết.").classes(
                    "text-xs muted")
            with ui.row().classes("w-full justify-end gap-2 sr-ar-foot"):
                ui.button("Hủy", on_click=d.close).props("flat no-caps")
                ui.button("Điền vào bảng", icon="south", on_click=lambda: (apply(res), d.close())).props(
                    "unelevated no-caps color=deep-purple-1 text-color=deep-purple-9")
        d.on("hide", d.delete)
        d.open()

    def apply(res: dict) -> None:
        if res["start"]:
            start.value = res["start"]
        set_months(res["months"] or len(state["months"]))
        for key, r in res["rows"].items():
            if any(v is not None for v in r["values"]):
                rows[key] = {"unit": r["unit"], "values": {i + 1: v for i, v in enumerate(r["values"])
                                                           if v is not None}}
        got = [k for lst in res["keywords"].values() for k in lst]
        if got:
            main["texts"][0] = "\n".join(dict.fromkeys(
                k["keyword"] + (f" | {k['url']}" if k["url"] else "") for k in got))
        sets_area.refresh()
        paint_window()
        table.refresh()
        ui.notify("Đã điền vào bảng: kiểm tra rồi bấm Lưu cam kết", type="positive")

    # ---------------------------------------------------------------- lưu
    def build() -> tuple[dict, dict[int, list]]:
        d = parse_date(start.value, date.today()) if start.value else None
        if start.value and not d:
            raise ValueError("Ngày bắt đầu chưa đúng (dd/mm/yyyy)")
        tiers = {0: glist(main, 0)}
        seen: dict[str, str] = {}
        names_seen = set()
        for g in live_groups():
            has = bool(glist(g, 0)) or any(
                v is not None for n in g["tiers"] for v in rows.get(rkey(g, n), {}).get("values", {}).values())
            if not g["main"] and has:
                nm_ = (g["name"] or "").strip()
                if not nm_:
                    raise ValueError("Có bộ từ khóa chưa đặt tên")
                if nm_.lower() in names_seen or nm_.lower() == main["name"].lower():
                    raise ValueError(f"Hai bộ cùng tên “{nm_}”")
                names_seen.add(nm_.lower())
            lab = g["name"] or "Bộ mới"
            for kw, _ in glist(g, 0):
                if kw.lower() in seen and seen[kw.lower()] != lab:
                    raise ValueError(f"“{kw}” có ở cả bộ {seen[kw.lower()]} và bộ {lab}: mỗi từ khóa chỉ thuộc "
                                     "một bộ.")
                seen[kw.lower()] = lab
        ms = state["months"]
        lines = []
        for g in live_groups():
            for n in sorted(g["tiers"]):
                r = rows.setdefault(rkey(g, n), {"unit": "count", "values": {}})
                vals = {str(m): r["values"].get(m) for m in ms}
                has_v = any(v is not None for v in vals.values())
                if g["main"]:  # mốc chung: đếm cả bộ chính vào Top N
                    if has_v:
                        lines.append({"kind": "rank", "top": n, "mode": "shared", "unit": r["unit"],
                                      "targets": vals})
                elif has_v or glist(g, 0):  # bộ riêng: đếm cả bộ vào Top N
                    lines.append({"kind": "rank", "top": n, "mode": "shared", "unit": r["unit"], "set": g["set"],
                                  "name": g["name"].strip(), "targets": vals, "_key": g["key"]})
        for key, _, top, src in TABLE_ROWS[3:]:
            r = rows[key]
            vals = {str(m): r["values"].get(m) for m in ms}
            if any(v is not None for v in vals.values()):
                lines.append({"kind": "level", "source": src, "targets": vals})
        lines += [dict(x, targets={str(n): x["targets"].get(str(n)) for n in ms}) for x in extras]
        return ({"project": (name.value or "").strip(), "start": d.isoformat() if d else None, "months": ms,
                 "baseline": data.get("baseline") or {"organic": None, "ai": None}, "lines": lines}, tiers)

    def apply_customs(c, new: dict, notes: list) -> None:
        """Bộ riêng = bộ loại Cam kết ở Thứ hạng: tạo / đổi tên, thêm từ khóa theo mốc Top, bỏ từ khóa đã xóa khỏi
        các mốc, gắn id bộ vào dòng cam kết."""
        from . import keywords as K
        for g in groups:
            if g["main"]:
                continue
            if g["deleted"]:
                if g["set"]:
                    R.update_set(c, g["set"], str(user), kind="custom")  # thôi cam kết, vẫn check
                continue
            if not any(ln.get("_key") == g["key"] for ln in new["lines"]):
                continue
            if not g["set"]:
                g["set"] = R.create_set(c, cfg.site_url, g["name"].strip(), str(user), kind="kpi",
                                        schedule=R.get_schedule(c))
            elif g.get("orig") and g["name"].strip() != g["orig"]:
                R.update_set(c, g["set"], str(user), name=g["name"].strip())
            g["orig"] = g["name"].strip()
            items = [(kw, url or None) for kw, url in glist(g, 0)]
            if items:
                res = R.add_keywords(c, cfg.site_url, cfg.rank, K.latest_date(c, cfg.site_url), items, str(user),
                                     set_id=g["set"])
                if res["over_budget"]:
                    notes.append(f"{g['name']}: {len(res['over_budget'])} từ khóa vượt ngân sách check rank")
            keep = {kw.lower() for kw, *_ in items}
            gone = [i for i, kw in c.execute(
                "SELECT id, keyword FROM rank_keywords WHERE site = ? AND set_id = ? AND removed_at IS NULL",
                (cfg.site_url, g["set"])) if kw.lower() not in keep]
            if gone:  # từ khóa team xóa khỏi ô của bộ: vào thùng rác ở Thứ hạng (khôi phục được)
                R.remove_keywords(c, cfg.site_url, gone, str(user))
        for ln in new["lines"]:
            k_ = ln.pop("_key", None)
            if k_:
                ln["set"] = gmap[k_]["set"]

    async def save():
        try:
            new, tiers = build()
        except ValueError as e:
            ui.notify(str(e), type="warning", multi_line=True)
            return
        if create:
            if not new["start"]:
                ui.notify("Nhập ngày bắt đầu dự án", type="warning")
                return
            await create_sheet(new, tiers)
            return
        save_btn.props("loading")
        try:
            def work():
                from . import keywords as K
                from . import sheet_view as SV
                notes = []
                with connect() as c:
                    if any(tiers.values()) or main_had:
                        kset = R.kpi_set(c, cfg.site_url, create=True, user=str(user))
                        items = [(kw, url or None) for kw, url in tiers[0]]
                        if items:
                            res = R.add_keywords(c, cfg.site_url, cfg.rank, K.latest_date(c, cfg.site_url), items,
                                                 str(user), set_id=kset["id"])
                            if res["over_budget"]:
                                notes.append(f"{len(res['over_budget'])} từ khóa chưa thêm được vì vượt ngân sách "
                                             "check rank")
                            if res["bad_url"]:
                                notes.append(f"{len(res['bad_url'])} dòng có URL không thuộc website")
                        keep = {kw.lower() for kw, _ in tiers[0]}
                        gone = [i for i, kw in c.execute(
                            "SELECT id, keyword FROM rank_keywords WHERE site = ? AND set_id = ? AND removed_at IS NULL",
                            (cfg.site_url, kset["id"])) if kw.lower() not in keep]
                        if gone:  # xóa khỏi ô của bộ: vào thùng rác ở Thứ hạng (khôi phục được)
                            R.remove_keywords(c, cfg.site_url, gone, str(user))
                    apply_customs(c, new, notes)
                    KP.save(c, {**new, "keywords": KP.commitment_keywords(c, cfg.site_url)}, date.today())
                    try:
                        SV.publish(c, cfg)
                    except (Exception, SystemExit) as e:  # noqa: BLE001
                        notes.append(f"chưa ghi được lên sheet: {str(e)[:120]}")
                return notes
            notes = await run.io_bound(work)
            ui.notify("Đã lưu cam kết" + ("; " + "; ".join(notes) if notes else ""),
                      type="positive" if not notes else "warning", multi_line=True)
            ui.navigate.to("/kpi")
        except (Exception, SystemExit) as e:  # noqa: BLE001
            ui.notify(f"Không lưu được: {str(e)[:300]}", type="negative", multi_line=True)
        finally:
            save_btn.props(remove="loading")

    async def create_sheet(new: dict, tiers: dict) -> None:
        from . import projects as PJ
        kws = [(kw, url or None, None) for kw, url in tiers[0]]
        save_btn.props("loading")
        try:
            def work():
                from . import sheet_view as SV
                clines = [ln for ln in new["lines"] if ln.get("_key")]
                base = {**new, "lines": [ln for ln in new["lines"] if not ln.get("_key")]}
                with connect() as c:
                    f = KP.create_project_sheet(c, cfg, base, kws, create["master"])
                    KP.sync(c, cfg, user)
                    if clines:  # bộ riêng: tạo sau khi có sheet + bộ Cam kết chính, rồi lưu thêm dòng cam kết
                        notes: list = []
                        apply_customs(c, new, notes)
                        cur_v = KP.version_at(KP.versions(c), date.today()) or base
                        KP.save(c, {**cur_v, "lines": list(cur_v.get("lines") or []) + clines,
                                    "keywords": KP.commitment_keywords(c, cfg.site_url)}, date.today())
                        try:
                            SV.publish(c, cfg)
                        except (Exception, SystemExit):  # noqa: BLE001  (sheet ghi lại ở lần Lưu sau)
                            pass
                ac, proj = create.get("app_connect"), create.get("project")
                if ac and proj:  # một link sheet dự án: màn OKR đọc cùng file
                    with ac() as a:
                        if create["master"] or not proj["settings"].get("okr_sheet"):
                            PJ.set_sheet_link(a, proj["slug"], f["id"], user)
                return f
            f = await run.io_bound(work)
            ui.notify("Đã tạo sheet dự án trên Drive và lưu cam kết", type="positive")
            ui.navigate.to(f["webViewLink"], new_tab=True)
            ui.navigate.reload()
        except (Exception, SystemExit) as e:  # noqa: BLE001
            from . import drive as D
            ui.notify(f"Không tạo được sheet: {D.explain(e)}", type="negative", multi_line=True)
        finally:
            save_btn.props(remove="loading")

    with ui.row().classes("items-center gap-3 q-mt-sm sr-ke-save"):
        save_btn = ui.button("Tạo sheet dự án và lưu" if create else "Lưu cam kết", icon="add_chart" if create
                             else "save", on_click=lambda: save()).props("unelevated no-caps")
        if not create:
            ui.button("Hủy", on_click=lambda: ui.navigate.to("/kpi")).props("flat no-caps")
        ui.label("Tool tạo sheet trong thư mục Drive của dự án." if create else
                 "Tháng đã qua vẫn chấm theo bản cam kết cũ.").classes("text-xs muted")
