"""Khối và biểu đồ của màn Tổng quan kiểu bảng điều khiển (nhóm theo nguồn: Thứ hạng · Google Analytics · Tốc độ
trang · Backlink · Search Console). Chỉ vẽ từ số đã có (SQLite / GA4 đã tải), không gọi API trả phí."""
from html import escape

from . import ai_format as F
from . import ui_theme as T

# Nhóm vị trí (màu theo nhóm, cố định): xanh đậm → xanh lá → vàng → đỏ
RANK_BANDS = (("Top 1–3", "#1E7C31"), ("4–10", "#8DBF3F"), ("11 trở đi", "#E0A93B"), ("Ngoài độ sâu check", "#C2410C"))
# Kênh GA4 → màu cố định (màu theo kênh, không theo thứ tự lớn nhỏ)
CHANNEL_COLORS = {"Organic Search": "#1E7C31", "Direct": "#2a78d6", "Referral": "#6250d6", "Paid Search": "#E0A93B",
                  "Organic Social": "#d6457a", "Paid Social": "#b35c2e", "Email": "#1a9e8f", "Display": "#8C7A3D",
                  "Paid Shopping": "#C98A2E", "Organic Shopping": "#5E9A2B", "Organic Video": "#7C3AED",
                  "Cross-network": "#4A6FA5", "Unassigned": "#A9A79B", "Khác": "#C9C7BC"}
AXIS = {"axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
        "axisLabel": {"color": "#8C8A7E", "fontSize": 11}}
Y = {"type": "value", "splitNumber": 3, "splitLine": {"lineStyle": {"color": "#EEECE4"}},
     "axisLabel": {"color": "#8C8A7E", "fontSize": 11}}


def group_head(ui, title: str, icon: str, sub: str = "", href: str | None = None, link_text: str = "") -> None:
    """Thanh tên nhóm (trắng, bo góc) trên các thẻ của nhóm: tên nguồn + loại thời gian + link đi sâu."""
    with ui.element("div").classes("sr-db-head"):
        with ui.row().classes("items-center gap-2 no-wrap").style("min-width:0"):
            ui.icon(icon, size="18px").classes("sr-db-head-ico")
            with ui.column().classes("gap-0").style("min-width:0"):
                ui.label(title).classes("sr-db-title")
                if sub:
                    ui.label(sub).classes("sr-db-sub")
        if href and T.link_allowed(href):
            ui.link(f"{link_text} →", href).classes("sr-link")


def stat(ui, label: str, value: str, icon: str = "", delta: str = "", good: bool | None = None, sub: str = "",
         href: str | None = None, info: tuple | None = None, color: str | None = None, loading: bool = False,
         value_html: str = "", tone: str = "grey", ratio: float | None = None, split: tuple | None = None):
    """Thẻ một số: icon nền màu theo nguồn (tone), tên, số lớn (color: màu số khi số tự nói tốt / xấu), nhãn tăng /
    giảm, thanh tỷ lệ (ratio 0–1, cùng màu nguồn) hoặc thanh hai phần (split = (lên, rớt): xanh / đỏ), dòng phụ."""
    if href and not T.link_allowed(href):  # khách hàng không mở được trang đó: thẻ thường, không link
        href = None
    if href:  # thẻ bấm được là một link thật: bàn phím Tab tới được, Enter mở
        el = ui.link(target=href).classes("sr-card sr-db-card sr-db-stat clickable no-underline")
    else:
        el = ui.element("div").classes("sr-card sr-db-card sr-db-stat")
    with el:
        with ui.row().classes("items-center gap-1 no-wrap"):
            if icon:
                bg, fg = T.TONES.get(tone, T.TONES["grey"])
                with ui.element("div").classes("sr-db-bubble").style(f"background:{bg}"):
                    ui.icon(icon, size="16px").style(f"color:{fg}").props('aria-hidden="true"')
            ui.label(label).classes("sr-db-card-title")
            T.info_icon(ui, label, info)
            if href:
                ui.icon("chevron_right", size="16px").classes("sr-db-card-ico q-ml-auto").props('aria-hidden="true"')
        with ui.row().classes("items-center q-mt-xs").style("gap:4px 8px"):  # ô hẹp: nhãn chênh xuống dòng
            if loading:  # khung giữ chỗ cùng chiều cao số thật: không nhảy khi số về, không lặp chữ "đang tải"
                ui.skeleton("rect").style("height:30px; width:110px; border-radius:6px")
            elif value_html:
                ui.html(value_html).classes("sr-db-num")
            else:
                num = ui.label(value).classes("sr-db-num")
                if color:
                    num.style(f"color:{color}")
            if delta:
                T.delta_badge(ui, delta, good)
        if not loading and ratio is not None:  # phần đã đạt của cả bộ / tổng: thanh mảnh cùng màu nguồn
            fg = T.TONES.get(tone, T.TONES["grey"])[1]
            with ui.element("div").classes("sr-db-meter").props('aria-hidden="true"'):
                ui.element("div").style(f"width:{max(0, min(ratio, 1)) * 100:.1f}%; background:{fg}")
        if not loading and split is not None and sum(split):  # lên / rớt: hai phần xanh / đỏ
            a_, b_ = split
            with ui.element("div").classes("sr-db-meter split").props('aria-hidden="true"'):
                ui.element("div").style(f"flex:{a_} 1 0; background:{T.GREEN}")
                ui.element("div").style(f"flex:{b_} 1 0; background:{T.RED}")
        if loading:
            ui.skeleton("text").style("width:70%")
        elif sub:
            ui.label(sub).classes("sr-db-note")
    return el


def card(ui, label: str, icon: str = "", extra: str = ""):
    """Thẻ trắng có tiêu đề nhỏ; nội dung đặt trong `with`."""
    el = ui.element("div").classes("sr-card sr-db-card " + extra)
    if not label:  # thẻ không tiêu đề (nội dung tự có tiêu đề nhỏ)
        return el
    with el:
        with ui.row().classes("items-center gap-1 no-wrap"):
            if icon:
                ui.icon(icon, size="15px").classes("sr-db-card-ico")
            ui.label(label).classes("sr-db-card-title")
    return el


def rank_bands_chart(ui, hist: list[dict], height: int = 190) -> None:
    """Cột chồng theo tuần: số từ khóa ở Top 1–3 / 4–10 / 11 trở đi / ngoài độ sâu đã check (R.history_of)."""
    series_vals = [[h["top3"] for h in hist], [h["top5"] + h["top10"] for h in hist], [h["top30"] for h in hist],
                   [h["out"] for h in hist]]
    ui.echart({
        "animation": False, "grid": {"left": 30, "right": 8, "top": 30, "bottom": 22},
        "legend": {"top": 0, "left": 0, "icon": "circle", "itemWidth": 8, "itemHeight": 8, "itemGap": 10,
                   "textStyle": {"fontSize": 11, "color": "#4A4A40"}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "category", "data": [h["label"] for h in hist], **AXIS},
        "yAxis": {**Y, "minInterval": 1},
        "series": [{"type": "bar", "name": name, "stack": "r", "barMaxWidth": 16, "data": vals,
                    "itemStyle": {"color": color, "borderColor": "#fff", "borderWidth": 1}}
                   for (name, color), vals in zip(RANK_BANDS, series_vals)],
    }).classes("w-full").style(f"height:{height}px")


def gauge(ui, value: float | None, label: str, max_: float = 100, height: int = 118, color: str | None = None) -> None:
    """Vòng điểm (0–max). Không có số: vòng xám, ghi "–"."""
    v = round(value) if value is not None else None
    lighthouse = color is None
    if color is None:  # ngưỡng của Lighthouse
        color = "#A9A79B" if v is None else ("#1E7C31" if v >= 90 else "#E0A93B" if v >= 50 else "#C2410C")
    ui.echart({
        "animation": False,
        "series": [{"type": "gauge", "startAngle": 90, "endAngle": -270, "min": 0, "max": max_, "radius": "92%",
                    "pointer": {"show": False},
                    "progress": {"show": True, "roundCap": True, "width": 9, "itemStyle": {"color": color}},
                    "axisLine": {"lineStyle": {"width": 9, "color": [[1, "#E2E0D7"]]}},
                    "splitLine": {"show": False}, "axisTick": {"show": False}, "axisLabel": {"show": False},
                    "title": {"show": False},
                    "detail": {"offsetCenter": [0, 0], "fontSize": 22, "fontWeight": 800, "color": T.INK,
                               ":formatter": "'" + ("–" if v is None else F.n(v)) + "'"},
                    "data": [{"value": v or 0, "name": label}]}],
    }).classes("w-full").style(f"height:{height}px").props['aria-label'] = (
        f"{label}: chưa có số" if v is None else f"{label}: {v}/{F.n(max_)}" + (
            (", tốt" if v >= 90 else ", cần cải thiện" if v >= 50 else ", kém") if lighthouse else ""))


def new_lost_chart(ui, hist: list[dict], height: int = 190) -> None:
    """Link mới (trên trục, xanh) / link mất (dưới trục, đỏ) theo tháng (DataForSEO, 12 tháng)."""
    labels = [f"{h['month'][5:]}/{h['month'][2:4]}" for h in hist]
    ui.echart({
        "animation": False, "grid": {"left": 44, "right": 8, "top": 30, "bottom": 22},
        "legend": {"top": 0, "left": 0, "icon": "circle", "itemWidth": 8, "itemHeight": 8,
                   "textStyle": {"fontSize": 11, "color": "#4A4A40"}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                    ":valueFormatter": "v => Math.abs(v).toLocaleString('vi-VN')"},
        "xAxis": {"type": "category", "data": labels, **AXIS},
        "yAxis": {**Y, "axisLabel": {"color": "#8C8A7E", "fontSize": 11,
                                     ":formatter": "v => Math.abs(v).toLocaleString('vi-VN')"}},
        "series": [{"type": "bar", "name": "Link mới", "stack": "nl", "barMaxWidth": 18,
                    "data": [h["new_backlinks"] or 0 for h in hist],
                    "itemStyle": {"color": "#8DBF3F", "borderRadius": [3, 3, 0, 0]}},
                   {"type": "bar", "name": "Link mất", "stack": "nl", "barMaxWidth": 18,
                    "data": [-(h["lost_backlinks"] or 0) for h in hist],
                    "itemStyle": {"color": "#C2410C", "borderRadius": [0, 0, 3, 3]}}],
    }).classes("w-full").style(f"height:{height}px").props['aria-label'] = (
        f"Link mới / mất {len(hist)} tháng: " + "; ".join(
            f"{h['month'][5:]}/{h['month'][2:4]} +{h['new_backlinks'] or 0} −{h['lost_backlinks'] or 0}"
            for h in hist[-3:]))


def line_chart(ui, values: list, prev_values: list, labels: list[str], prev_labels: list[str], name: str,
               color: str = "#2a78d6", height: int = 130) -> None:
    """Đường theo ngày kỳ này (liền, có nền) và kỳ trước (nét đứt), cùng số điểm."""
    tip = ("ps => ps.map(p => p.marker + (p.seriesIndex ? " + str(prev_labels) + "[p.dataIndex] : p.axisValue) + "
           "': <b>' + (p.value == null ? '–' : p.value.toLocaleString('vi-VN')) + '</b>').join('<br/>')")
    ui.echart({
        "animation": False, "grid": {"left": 4, "right": 4, "top": 6, "bottom": 4},
        "tooltip": {"trigger": "axis", ":formatter": tip},
        "xAxis": {"type": "category", "data": labels, "show": False, "boundaryGap": False},
        "yAxis": {"type": "value", "show": False, "scale": True},
        "series": [{"type": "line", "name": name, "data": values, "symbol": "none", "smooth": 0.3,
                    "lineStyle": {"width": 2, "color": color},
                    "areaStyle": {"color": color, "opacity": 0.08}},
                   {"type": "line", "name": "Kỳ trước", "data": prev_values, "symbol": "none", "smooth": 0.3,
                    "lineStyle": {"width": 1.5, "color": "#A9A79B", "type": "dashed"}}],
    }).classes("w-full").style(f"height:{height}px")


def channel_items(channels: dict[str, int], keep: int = 5) -> tuple[list[tuple[str, int]], list[str]]:
    """Kênh GA4 cho donut: `keep` kênh lớn nhất, phần còn lại gộp "Khác". Trả (items, colors)."""
    rows = sorted(((k or "Unassigned", v) for k, v in channels.items() if v), key=lambda kv: -kv[1])
    items = rows[:keep]
    rest = sum(v for _, v in rows[keep:])
    if rest:
        items.append(("Khác", rest))
    palette = ["#2a78d6", "#6250d6", "#1a9e8f", "#d6457a", "#8C7A3D"]
    colors, spare = [], iter(palette)
    for name, _ in items:
        colors.append(CHANNEL_COLORS.get(name) or next(spare, "#C9C7BC"))
    return items, colors


def lighthouse_avg(pages: list[dict]) -> dict:
    """Điểm Lighthouse trung bình (0–100) trên các trang có số: {perf, seo, a11y, bp, n, at}."""
    out: dict = {"n": 0, "at": None}
    for k in ("perf", "seo", "a11y", "bp"):
        vals = [p[k] for p in pages if p.get(k) is not None]
        out[k] = sum(vals) / len(vals) if vals else None
    ok = [p for p in pages if p.get("perf") is not None]
    out["n"] = len(ok)
    out["at"] = max((p["fetched_at"] for p in ok if p.get("fetched_at")), default=None)
    return out


def donut_legend(ui, items: list[tuple[str, int]], colors: list[str], unit: str, height: int = 170) -> None:
    """Donut có tổng ở giữa và chú thích dạng danh sách HTML bên dưới (không bị cắt khi thẻ hẹp)."""
    total = sum(v for _, v in items) or 1
    ui.echart({
        "animation": False, "tooltip": {"trigger": "item", ":valueFormatter": "v => v.toLocaleString('vi-VN')"},
        # tổng ở giữa vẽ bằng title (không phải nhãn của lát: rê chuột vào lát không thay chữ ở giữa)
        "title": {"text": F.n(total), "subtext": unit, "left": "center", "top": "middle", "itemGap": 0,
                  "textStyle": {"fontSize": 20, "fontWeight": 800, "color": T.INK},
                  "subtextStyle": {"fontSize": 11, "color": T.MUTED}},
        "series": [{"type": "pie", "radius": ["62%", "88%"], "center": ["50%", "50%"], "padAngle": 2,
                    "itemStyle": {"borderRadius": 4, "borderColor": "#fff", "borderWidth": 1},
                    "label": {"show": False},
                    "labelLine": {"show": False}, "emphasis": {"scale": False},
                    "data": [{"name": n, "value": v, "itemStyle": {"color": c}} for (n, v), c in zip(items, colors)]}],
    }).classes("w-full").style(f"height:{height}px")
    with ui.element("div").classes("sr-db-legend"):
        for (name, v), c in zip(items, colors):
            with ui.element("div").classes("sr-db-legend-row"):
                ui.html(f"<i style='background:{c}'></i>{name}")
                ui.html(f"<b class='num'>{F.n(v)}</b> <span>{v / total * 100:.0f}%</span>")


# ---- Hàng ngang theo nguồn (Thứ hạng / Search Console / Google Analytics) ----
# Nhóm hạng là thang có thứ tự: một tông xanh đậm → nhạt (đã kiểm bằng validate_palette --ordinal), "ngoài độ sâu"
# là xám trung tính (không phải màu trạng thái).
RANK_RAMP = (("Top 1–3", "#14532D"), ("4–10", "#2F8F46"), ("11 trở đi", "#86C27A"),
             ("Ngoài top check", "#C9C7BC"))


def rank_share_chart(ui, hist: list[dict], height: int = 220) -> None:
    """Cột chồng 100%: mỗi cột là tỷ lệ các nhóm hạng trên số từ khóa ĐÃ CÓ SỐ ở thời điểm đó (không vẽ số đếm cộng
    dồn, vì số từ khóa đã check tăng dần làm cột cao lên giả). Tooltip ghi cả số từ khóa và mẫu số."""
    import json
    rows = []
    for h in hist:
        n = h["checked"] or 0
        counts = [h["top3"], h["top5"] + h["top10"], h["top30"], h["out"]]
        rows.append((h["label"], n, counts))
    labels = [r[0] for r in rows]
    totals = [r[1] for r in rows]
    counts = [[r[2][i] for r in rows] for i in range(4)]
    tip = ("ps => ps[0].axisValue + ' · ' + " + json.dumps(totals) + "[ps[0].dataIndex] + ' từ khóa đã check<br/>' + "
           "ps.map(p => p.marker + p.seriesName + ': <b>' + " + json.dumps(counts) + "[p.seriesIndex][p.dataIndex] + "
           "'</b> (' + p.value.toLocaleString('vi-VN', {maximumFractionDigits: 0}) + '%)').join('<br/>')")
    ui.echart({
        "animation": False, "grid": {"left": 40, "right": 8, "top": 30, "bottom": 24},
        "legend": {"top": 0, "left": 0, "icon": "circle", "itemWidth": 8, "itemHeight": 8, "itemGap": 12,
                   "textStyle": {"fontSize": 12, "color": "#4A4A40"}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, ":formatter": tip},
        "xAxis": {"type": "category", "data": labels, **{**AXIS, "axisLabel": {"color": "#6B6A5E", "fontSize": 12}}},
        "yAxis": {**Y, "max": 100, "axisLabel": {"color": "#6B6A5E", "fontSize": 12, "formatter": "{value}%"}},
        "series": [{"type": "bar", "name": name, "stack": "r", "barMaxWidth": 22,
                    "data": [round(c / t * 100, 1) if t else 0 for c, t in zip(counts[i], totals)],
                    "itemStyle": {"color": color, "borderColor": "#fff", "borderWidth": 2}}
                   for i, (name, color) in enumerate(RANK_RAMP)],
    }).classes("w-full").style(f"height:{height}px").props['aria-label'] = (
        "Tỷ lệ từ khóa theo nhóm hạng qua các lần check: " + "; ".join(
            f"{lab}: Top 1–3 {c[0]}/{n}" for lab, n, c in rows[-3:]))


def daily_line(ui, values: list, prev_values: list, labels: list[str], prev_labels: list[str], name: str,
               color: str = "#2a78d6", height: int = 220, marks: dict | None = None) -> None:
    """Đường theo ngày (kỳ này liền, kỳ trước nét đứt), trục Y bắt đầu từ 0 và có số (không phóng đại dao động)."""
    tip = ("ps => ps.map(p => p.marker + (p.seriesIndex ? " + str(prev_labels) + "[p.dataIndex] : p.axisValue) + "
           "': <b>' + (p.value == null ? '–' : p.value.toLocaleString('vi-VN')) + '</b>').join('<br/>')")
    step = max(1, len(labels) // 7)
    el = ui.echart({
        "animation": False, "grid": {"left": 48, "right": 10, "top": 30, "bottom": 24},
        "legend": {"top": 0, "left": 0, "itemWidth": 16, "itemHeight": 2, "textStyle": {"fontSize": 12,
                                                                                         "color": "#4A4A40"}},
        "tooltip": {"trigger": "axis", ":formatter": tip},
        "xAxis": {"type": "category", "data": labels, "boundaryGap": False,
                  **{**AXIS, "axisLabel": {"color": "#6B6A5E", "fontSize": 12, "interval": step - 1}}},
        "yAxis": {**Y, "min": 0, "axisLabel": {"color": "#6B6A5E", "fontSize": 12,
                                               ":formatter": "v => v.toLocaleString('vi-VN')"}},
        "series": [{"type": "line", "name": f"{name} kỳ này", "data": values, "symbol": "none", "smooth": 0.3,
                    "lineStyle": {"width": 2, "color": color}, "itemStyle": {"color": color},
                    "areaStyle": {"color": color, "opacity": 0.08}, **(marks or {})},
                   {"type": "line", "name": "Kỳ trước", "data": prev_values, "symbol": "none", "smooth": 0.3,
                    "lineStyle": {"width": 1.5, "color": "#A9A79B", "type": "dashed"}, "itemStyle": {"color": "#A9A79B"}}],
    }).classes("w-full").style(f"height:{height}px")
    vals = [v for v in values if v is not None]
    if vals:
        el.props["aria-label"] = (f"{name} theo ngày {labels[0]}–{labels[-1]}: tổng {F.n(sum(vals))}, cao nhất "
                                  f"{F.n(max(vals))}, thấp nhất {F.n(min(vals))}")


def channel_bars(ui, channels: dict[str, int], keep: int = 6, accent: str = "Organic Search") -> None:
    """Phiên theo kênh dạng thanh ngang xếp hạng (so sánh các kênh chính xác hơn donut): kênh SEO (Organic) màu nhấn,
    các kênh khác xám; số và % ghi sẵn cạnh thanh (không phải rê chuột)."""
    rows = sorted(((k or "Unassigned", v) for k, v in channels.items() if v), key=lambda kv: -kv[1])
    items = rows[:keep]
    rest = sum(v for _, v in rows[keep:])
    if rest:
        items.append(("Khác", rest))
    total = sum(v for _, v in items) or 1
    top = max(v for _, v in items) if items else 1
    with ui.element("div").classes("sr-db-bars").props('role="list" aria-label="Phiên theo kênh"'):
        for name, v in items:
            on = name == accent
            with ui.element("div").classes("sr-db-bar-row" + (" on" if on else "")).props('role="listitem"'):
                ui.label(name).classes("sr-db-bar-name")
                with ui.element("div").classes("sr-db-bar-track"):
                    ui.element("div").classes("sr-db-bar-fill").style(f"width:{v / top * 100:.1f}%")
                ui.html(f"<b class='num'>{F.n(v)}</b> <span>{v / total * 100:.0f}%</span>").classes("sr-db-bar-val")


def rank_segment_bar(ui, h: dict) -> None:
    """Một lần check (chưa đủ điểm để vẽ xu hướng): thanh phân đoạn theo nhóm hạng, số và % ghi sẵn trên / dưới
    thanh (không phải biểu đồ một cột)."""
    n = h["checked"] or 0
    parts = [(name, color, v) for (name, color), v in
             zip(RANK_RAMP, (h["top3"], h["top5"] + h["top10"], h["top30"], h["out"])) if v]
    with ui.element("div").classes("sr-db-seg").props(
            f'role="img" aria-label="Lần check {h["label"]}: ' + "; ".join(f"{p[0]} {p[2]}/{n}" for p in parts) + '"'):
        for name, color, v in parts:
            ui.element("div").style(f"flex:{v} 1 0; background:{color}").props(f'title="{name}: {v}/{n}"')
    with ui.element("div").classes("sr-db-legend-inline"):
        for name, color, v in parts:
            ui.html(f"<i style='background:{color}'></i>{name} <b class='num'>{v}</b>"
                    f"<span> · {v / n * 100:.0f}%</span>" if n else name)


def source_bars(ui, rows: list[tuple[str, int]], color: str = "#7C3AED", empty: str = "Chưa có lượt nào") -> None:
    """Thanh ngang cùng một màu (nguồn AI…), số và % ghi sẵn cạnh thanh."""
    rows = [r for r in rows if r[1]]
    if not rows:
        ui.label(empty).classes("sr-db-note")
        return
    total = sum(v for _, v in rows) or 1
    top = max(v for _, v in rows)
    with ui.element("div").classes("sr-db-bars").props('role="list"'):
        for name, v in rows:
            with ui.element("div").classes("sr-db-bar-row").props('role="listitem"'):
                ui.label(name).classes("sr-db-bar-name")
                with ui.element("div").classes("sr-db-bar-track"):
                    ui.element("div").classes("sr-db-bar-fill").style(f"width:{v / top * 100:.1f}%; background:{color}")
                ui.html(f"<b class='num'>{F.n(v)}</b> <span>{v / total * 100:.0f}%</span>").classes("sr-db-bar-val")



def fact(ui, icon: str, tone: str, label: str, value_html: str, href: str | None = None, tip: str = "") -> None:
    """Một dòng "nhãn → số" gọn (thay cho câu dài): icon màu, nhãn mờ bên trái, số đậm bên phải. Giải thích đầy đủ ở
    chú thích khi rê chuột / focus."""
    href = href if href and T.link_allowed(href) else None
    el = ui.link(target=href).classes("sr-db-fact no-underline") if href else \
        ui.element("div").classes("sr-db-fact")
    with el:
        bg, fg = T.TONES.get(tone, T.TONES["grey"])
        with ui.element("div").classes("sr-db-fact-ico").style(f"background:{bg}"):
            ui.icon(icon, size="14px").style(f"color:{fg}").props('aria-hidden="true"')
        ui.label(label).classes("sr-db-fact-label")
        ui.html(value_html).classes("sr-db-fact-val")
    if tip:
        el.tooltip(tip)
        el.props["aria-description"] = tip



def segment_bar(ui, parts: list[tuple[str, str, int]], label: str, total: int | None = None,
                compact: bool = False) -> None:
    """Thanh phân đoạn (một tổng chia phần) + chú thích có số và %: parts = [(tên, màu, số)]. compact: chú thích
    nối tiếp trên một hàng (tự xuống dòng khi hẹp) thay cho lưới 2 cột."""
    parts = [p for p in parts if p[2]]
    n = total if total is not None else sum(p[2] for p in parts)
    with ui.element("div").classes("sr-db-seg").props(
            f'role="img" aria-label="{label}: ' + "; ".join(f"{p[0]} {p[2]}/{n}" for p in parts) + '"'):
        for name, color, v in parts:
            ui.element("div").style(f"flex:{v} 1 0; background:{color}").props(f'title="{name}: {v}/{n}"')
    if compact:
        with ui.element("div").classes("sr-db-legend-inline"):
            for name, color, v in parts:
                ui.html(f"<i style='background:{color}'></i>{name} <b class='num'>{v}</b>"
                        f"<span> · {v / n * 100:.0f}%</span>" if n else name)
        return
    with ui.element("div").classes("sr-db-legend"):
        for name, color, v in parts:
            with ui.element("div").classes("sr-db-legend-row"):
                ui.html(f"<i style='background:{color}'></i>{name}")
                ui.html(f"<b class='num'>{v}</b> <span>{v / n * 100:.0f}%</span>" if n else "–")


AIO_PARTS = (("Được trích", "#5B21B6"), ("Có AIO, chưa trích", "#A78BFA"), ("Không có AIO", "#C9C7BC"))


def share_bars(ui, rows: list[dict], keep: int = 6) -> None:
    """Thị phần hiển thị trong bộ từ khóa: thanh ngang xếp hạng, mỗi thương hiệu giữ màu riêng (màu theo thương hiệu,
    như màn Đối thủ); website dự án in đậm. rows = [{name, color, own, share, top10}]."""
    rows = sorted([r for r in rows if r["share"]], key=lambda r: -r["share"])
    shown, rest = rows[:keep], rows[keep:]
    if rest:
        shown.append({"name": f"{len(rest)} đối thủ khác", "color": "#A9A79B", "own": False,
                      "share": sum(r["share"] for r in rest), "top10": None})
    top = max((r["share"] for r in shown), default=1) or 1
    with ui.element("div").classes("sr-db-bars").props('role="list" aria-label="Thị phần hiển thị"'):
        for r in shown:
            with ui.element("div").classes("sr-db-bar-row sr-db-share" + (" on" if r["own"] else "")).props(
                    'role="listitem"'):
                ui.label(r["name"]).classes("sr-db-bar-name").props["title"] = r["name"]
                with ui.element("div").classes("sr-db-bar-track"):
                    ui.element("div").classes("sr-db-bar-fill").style(
                        f"width:{r['share'] / top * 100:.1f}%; background:{r['color']}")
                ui.html(f"<b class='num'>{r['share'] * 100:.0f}%</b>"
                        + (f" <span>Top 10: {r['top10']}</span>" if r["top10"] is not None else "")).classes(
                    "sr-db-bar-val")



def mini_row(ui, icon: str, tone: str, label: str, value: str = "", sub: str = "", value_html: str = "",
             ratio: float | None = None, split: tuple | None = None, info: tuple | None = None) -> None:
    """Một dòng chỉ số gọn trong thẻ danh sách: icon màu · tên (+ dòng phụ) · số bên phải, thanh mảnh bên dưới."""
    with ui.element("div").classes("sr-db-mini"):
        with ui.row().classes("items-center no-wrap w-full").style("gap:8px"):
            bg, fg = T.TONES.get(tone, T.TONES["grey"])
            with ui.element("div").classes("sr-db-bubble").style(f"background:{bg}"):
                ui.icon(icon, size="15px").style(f"color:{fg}").props('aria-hidden="true"')
            with ui.column().classes("gap-0 col").style("min-width:0"):
                with ui.row().classes("items-center no-wrap gap-1"):
                    ui.label(label).classes("sr-db-card-title")
                    T.info_icon(ui, label, info)
                if sub:
                    ui.label(sub).classes("sr-db-note ellipsis")
            if not value_html and value.count("/") == 1:  # "10/69": số hiện tại đậm, tổng nhỏ và nhạt
                cur, tot = value.split("/")
                value_html = f"{escape(cur)}<span class='sr-db-mini-of'>/{escape(tot)}</span>"
            if value_html:
                ui.html(value_html).classes("sr-db-mini-num")
            else:
                ui.label(value).classes("sr-db-mini-num")
        if ratio is not None:
            fg = T.TONES.get(tone, T.TONES["grey"])[1]
            with ui.element("div").classes("sr-db-meter").props('aria-hidden="true"'):
                ui.element("div").style(f"width:{max(0, min(ratio, 1)) * 100:.1f}%; background:{fg}")
        if split is not None and sum(split):
            with ui.element("div").classes("sr-db-meter split").props('aria-hidden="true"'):
                ui.element("div").style(f"flex:{split[0]} 1 0; background:{T.GREEN}")
                ui.element("div").style(f"flex:{split[1]} 1 0; background:{T.RED}")
