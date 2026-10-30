"""Bản xem tĩnh để đưa lên Vercel: chụp số liệu hôm nay của các màn chính (báo cáo tuần, báo cáo tháng, công việc &
OKR, từ khóa & rank) thành một trang HTML, chỉ đọc.

Toàn bộ số liệu được mã hóa AES-256-GCM, khóa sinh từ mật khẩu bằng PBKDF2-SHA256 (600.000 vòng). Trang chỉ có ô nhập
mật khẩu và chuỗi đã mã hóa; trình duyệt tự giải mã bằng WebCrypto. Không có mật khẩu thì không đọc được số nào, kể cả
khi có link hay tải file HTML về. Không có token Google, khóa API hay file dữ liệu nào được đưa lên.
"""
import base64
import html
import json
import os
import shutil
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from . import ai_format as F

ITERATIONS = 600_000
GREEN, LIME, INK, MUTED, RED, AMBER, BLUE = "#1E7C31", "#B8D332", "#1F221E", "#6B6A5E", "#C2410C", "#B7791F", "#2563EB"
STATUS_COLOR = {"done": GREEN, "doing": BLUE, "todo": "#B8B6A8", "other": AMBER}
ECHARTS = "https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js"


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def _vn(iso) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso else "–"


def _path(url: str | None, site: str) -> str:
    return (url or "").replace(site.rstrip("/"), "") or "/"


# ---- Thu dữ liệu ----

def collect(cfg, today: date | None = None) -> dict:
    """Mọi số cần cho bản xem, tính bằng đúng các hàm của tool (cùng số với màn hình và file Excel)."""
    from . import db, keywords as K, okr as O, rank as R, urls as U, volume as V
    from .report import build, build_month

    today = today or date.today()
    with closing(db.connect(cfg.db_path)) as c:
        site = cfg.site_url
        gid = U.ensure_group(c, site)
        week = build(c, cfg, gid, 0, with_ai=True)
        month = build_month(c, cfg, gid, 0, with_ai=True)
        end = K.latest_date(c, site)
        ranks = R.keywords(c, site, end)
        vols = V.latest(c)
        okr = None
        if O.sheet_id(cfg.okr.sheet) and O.sync_info(c):
            cur = (today - timedelta(days=today.weekday()), today - timedelta(days=today.weekday() - 6))
            okr = O.overview(c, today, cur)
            okr["week"] = cur
            okr["tasks"] = O.tasks(c)
            okr["synced"] = O.sync_info(c)["at"]
    return {"site": cfg.site_url, "today": today, "end": end, "week": week, "month": month, "ranks": ranks,
            "vols": vols, "okr": okr}


# ---- Dựng HTML ----

class Charts:
    def __init__(self):
        self.items = []

    def add(self, option: dict, height: int = 240) -> str:
        cid = f"c{len(self.items)}"
        self.items.append({"id": cid, "option": option})
        return f'<div class="chart" id="{cid}" style="height:{height}px"></div>'


def _delta(text: str, good) -> str:
    if not text:
        return ""
    cls = "muted" if good is None else ("up" if good else "down")
    return f'<span class="delta {cls}">{e(text)}</span>'


def _kpi(label: str, value: str, delta: str = "", good=None, hint: str = "", tone: str = GREEN) -> str:
    return (f'<div class="tile"><div class="tl"><span class="dot" style="background:{tone}"></span>{e(label)}</div>'
            f'<div class="tv num">{e(value)}</div>{_delta(delta, good)}'
            + (f'<div class="hint">{e(hint)}</div>' if hint else "") + "</div>")


def _section(title: str, body: str, sub: str = "") -> str:
    return (f'<section class="card"><div class="st">{e(title)}</div>'
            + (f'<div class="ss">{e(sub)}</div>' if sub else "") + body + "</section>")


def _table(headers: list[str], rows: list[list[str]], num_cols: set[int] = frozenset()) -> str:
    """rows: ô đã là HTML an toàn."""
    if not rows:
        return '<div class="empty">Không có dữ liệu.</div>'
    th = "".join(f'<th class="{"r" if i in num_cols else ""}">{e(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td class="{"r num" if i in num_cols else ""}">{c}</td>'
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _report(rep, site: str, charts: Charts) -> str:
    from .report import BUCKETS, rank_change, summary
    sm = summary(rep)
    month = rep.kind == "month"
    unit = "tháng" if month else "tuần"
    (ws, we), (ps, pe) = rep.week, rep.prev_week
    title = f"Báo cáo tháng {ws:%m/%Y}" if month else f"Báo cáo tuần {ws:%d/%m} – {we:%d/%m/%Y}"
    compare = f"So với tháng {ps:%m/%Y}" if month else f"So với tuần {ps:%d/%m} – {pe:%d/%m}"
    out = [f'<div class="ph"><div class="eb">Báo cáo</div><h1>{e(title)}</h1>'
           f'<div class="sub">{e(compare)} · nhóm {e(rep.group)}</div></div>']
    if rep.incomplete_days:
        out.append(f'<div class="chip amber">Còn {rep.incomplete_days} ngày trong {unit} chưa có dữ liệu GSC</div>')

    # Tổng quan SEO + GEO
    tiles = "".join(_kpi(i["short"], i["value"], i["delta"], i["good"], i["label"], GREEN) for i in sm["seo"])
    tiles += "".join(_kpi(i["short"], i["value"], i["delta"], i["good"], i["label"], "#7C3AED") for i in sm["geo"])
    notes = "".join(f'<li class="{n["tone"]}">{e(n["long"])}</li>' for n in sm["seo_notes"] + sm["geo_notes"])
    out.append(_section("Tổng quan SEO & GEO", f'<div class="grid4">{tiles}</div>'
                        + (f'<ul class="notes">{notes}</ul>' if notes else ""),
                        "Xanh lá: Google Search · tím: AI Search (GA4 + AI Overviews)"))
    if rep.note or (month and rep.plan):
        body = f'<div class="two"><div><div class="hint">Nhận xét</div><p class="pre">{e(rep.note or "Chưa có")}</p></div>'
        if month:
            body += f'<div><div class="hint">Kế hoạch tháng sau</div><p class="pre">{e(rep.plan or "Chưa có")}</p></div>'
        out.append(_section("Nhận xét", body + "</div>"))

    # Xu hướng click
    tr = rep.trend
    chart = charts.add({
        "tooltip": {"trigger": "axis"}, "legend": {"bottom": 0},
        "grid": {"left": 56, "right": 56, "top": 20, "bottom": 40},
        "xAxis": {"type": "category", "data": [t["week"] for t in tr], "axisTick": {"show": False}},
        "yAxis": [{"type": "value", "name": "Click", "splitLine": {"lineStyle": {"color": "#EEECE4"}}},
                  {"type": "value", "name": "Impression", "splitLine": {"show": False}}],
        "series": [
            {"name": "Click toàn site", "type": "bar", "data": [t["site_clicks"] for t in tr], "barWidth": "38%",
             "itemStyle": {"color": GREEN, "borderRadius": [4, 4, 0, 0]}},
            {"name": f"Click nhóm {rep.group}", "type": "bar", "data": [t["group_clicks"] for t in tr],
             "barWidth": "38%", "itemStyle": {"color": LIME, "borderRadius": [4, 4, 0, 0]}},
            {"name": "Impression (trục phải)", "type": "line", "yAxisIndex": 1, "smooth": True,
             "data": [t.get("site_impressions") for t in tr], "itemStyle": {"color": BLUE}}]})
    out.append(_section(f"Google Search · {len(tr)} {unit} gần nhất", chart,
                        "Click và impression toàn site theo GSC"))

    # Rank
    buckets = " · ".join(f"{b}: {rep.rank_buckets[b][0]}" for b in BUCKETS if any(rep.rank_buckets[b]))
    rows = []
    for r in rep.ranks:
        text, color, _ = rank_change(r["date"], r["rank"], r["depth"], r["prev"], r["prev_depth"])
        wrong = bool(r["target_url"] and r["ranking_url"] and r["ranking_url"] != r["target_url"])
        rows.append([e(r["keyword"]), e(r["rank"] if r["rank"] is not None else f">{r['depth']}"),
                     f'<span style="color:{color};font-weight:600">{e(text)}</span>',
                     e(_path(r["ranking_url"], site)) + (' <span class="warn">⚠ khác URL mục tiêu</span>' if wrong
                                                         else "")])
    out.append(_section(f"Rank thực tế · {len(rep.ranks)} keyword",
                        (f'<div class="hint">{e(buckets)}</div>' if buckets else "")
                        + _table(["Keyword", "Vị trí", "Thay đổi", "URL đang xếp hạng"], rows, {1}),
                        "DataForSEO, Google mobile, Việt Nam"))

    # URL tăng / giảm
    cols = []
    for name, items, color in [("URL tăng click", rep.winners, GREEN), ("URL giảm click", rep.losers, RED)]:
        rows = [[e(_path(x["url"], site)), F.n(x["clicks"]), F.n(x["prev"]),
                 f'<span style="color:{color};font-weight:600">{x["diff"]:+,}</span>'.replace(",", ".")]
                for x in items]
        cols.append(_section(f"Top {len(items)} {name}", _table(["URL", f"{unit.capitalize()} này", "Trước", "Chênh"],
                                                               rows, {1, 2, 3}), f"Nhóm {rep.group} · URL có từ 20 click"))
    out.append(f'<div class="two">{"".join(cols)}</div>')

    if month:
        rows = [[e(r["type"]), F.n(r["clicks"]), F.n(r["prev_clicks"]), _pct_cell(r["change"])] for r in rep.by_type]
        out.append(_section("Theo loại trang", _table(["Loại trang", "Click", "Tháng trước", "Thay đổi"], rows,
                                                      {1, 2, 3}), "Cộng theo URL nên tổng khác tổng toàn site"))
        a = _section("Top 10 URL của tháng", _table(["URL", "Click", "Thay đổi"], [
            [e(_path(r["url"], site)), F.n(r["clicks"]), _pct_cell(r["change"])] for r in rep.top_urls], {1, 2}))
        b = _section("Top 10 từ khóa của tháng", _table(["Query", "Click", "Thay đổi"], [
            [e(r["query"]), F.n(r["clicks"]), _pct_cell(r["change"])] for r in rep.top_queries], {1, 2}))
        out.append(f'<div class="two">{a}{b}</div>')
    return "".join(out)


def _pct_cell(v) -> str:
    if v is None:
        return '<span class="muted">–</span>'
    return f'<span style="color:{GREEN if v > 0 else RED if v < 0 else MUTED};font-weight:600">' \
           f'{e(F.delta_pct(v))}</span>'


def _okr(ov: dict, today: date, charts: Charts) -> str:
    from . import okr as O
    cnt, total = ov["counts"], ov["total"] or 1
    synced = datetime.fromisoformat(ov["synced"]).astimezone()
    out = ['<div class="ph"><div class="eb">Báo cáo công việc</div><h1>Công việc &amp; OKR</h1>'
           f'<div class="sub">Từ Google Sheet của team · đồng bộ {synced:%H:%M %d/%m}</div></div>']
    tiles = (_kpi("Hoàn thành OKR", f"{cnt[O.DONE] / total * 100:.0f}%", hint=f"{cnt[O.DONE]} / {ov['total']} hạng mục")
             + _kpi("Đang làm", str(cnt[O.DOING]), tone=BLUE) + _kpi("Chưa bắt đầu", str(cnt[O.TODO]), tone="#B8B6A8")
             + _kpi("Trễ hạn", str(len(ov["late"])), tone=RED if ov["late"] else GREEN, hint="tính đến hôm nay"))
    out.append(f'<div class="grid4">{tiles}</div>')

    cards = ""
    for o in ov["objectives"]:
        pct = o["pct"] or 0
        cards += (f'<div class="tile"><div class="row"><span class="tag">{e(o["code"])}</span>'
                  f'<b class="num">{pct * 100:.0f}%</b></div><div class="ot">{e(o["title"])}</div>'
                  f'<div class="hint">{_vn(o["start"])} – {_vn(o["end"])} · {o["done"]}/{o["total"]} xong</div>'
                  f'<div class="bar"><span style="width:{pct * 100:.0f}%"></span></div></div>')
    out.append(_section("Theo mục tiêu", f'<div class="grid5">{cards}</div>'))

    items = [i for i in ov["items"] if i["start"] and i["end"]]
    if items:
        d0 = date.fromisoformat(min(i["start"] for i in items))
        rows = items[::-1]
        days = max((date.fromisoformat(i["end"]) - d0).days for i in items) + 2
        labels = [(d0 + timedelta(days=k)).strftime("%d/%m") for k in range(days)]
        today_x = (today - d0).days
        out.append(_section("Lịch triển khai", charts.add({
            "grid": {"left": 250, "right": 24, "top": 24, "bottom": 28},
            "tooltip": {"trigger": "item"},
            "xAxis": {"type": "value", "min": 0, "max": days, "interval": 7, "position": "top",
                      "splitLine": {"lineStyle": {"color": "#EEECE4"}}, "axisLabel": {"labels": labels}},
            "yAxis": {"type": "category", "data": [f"{i['code']}  {i['title']}" for i in rows],
                      "axisTick": {"show": False},
                      "axisLabel": {"fontSize": 11, "width": 236, "overflow": "truncate", "ellipsis": "…"}},
            "series": [
                {"type": "bar", "stack": "g", "silent": True, "itemStyle": {"color": "transparent"},
                 "data": [(date.fromisoformat(i["start"]) - d0).days for i in rows], "tooltip": {"show": False}},
                {"type": "bar", "stack": "g", "barWidth": 12,
                 "data": [{"value": (date.fromisoformat(i["end"]) - date.fromisoformat(i["start"])).days + 1,
                           "name": f"{i['code']} {i['title']} · {_vn(i['start'])} – {_vn(i['end'])} · "
                                   f"{O.STATUS_LABEL[i['status']]}",
                           "itemStyle": {"color": RED if O.is_late(i, today) else STATUS_COLOR[i["status"]],
                                         "borderRadius": 4}} for i in rows],
                 "markLine": {"silent": True, "symbol": "none", "lineStyle": {"color": RED, "type": "solid"},
                              "label": {"formatter": "Hôm nay", "color": RED, "position": "start"},
                              "data": [{"xAxis": today_x}]} if 0 <= today_x <= days else {}}]},
            height=max(200, 22 * len(rows) + 60)), "Vạch đỏ: hôm nay"))

    p, (ws, we) = ov["period"], ov["week"]
    lists = ""
    for name, its in [("Đến hạn", p["due"]), ("Hoàn thành", p["done"]), ("Trễ hạn", ov["late"]),
                      ("Tuần sau", p["next"])]:
        li = "".join(f'<li><span class="dot" style="background:{STATUS_COLOR[i["status"]]}"></span>'
                     f'<span class="muted">{e(i["code"])}</span> {e(i["title"])}</li>' for i in its[:8])
        lists += (f'<div class="tile"><div class="tl"><b>{name}</b> <span class="muted">{len(its)}</span></div>'
                  f'<ul class="list">{li or "<li class=muted>Không có</li>"}</ul></div>')
    week_tasks = [t for t in ov["tasks"] if t["week"] == ws.isoformat()]
    tasks = _table(["Mã OKR", "Việc", "PIC", "Deadline", "Trạng thái"], [
        [e(t["okr_code"]), e(t["task"] or t["item"]), e(t["pic"]), _vn(t["deadline"]), e(O.STATUS_LABEL[t["status"]])]
        for t in week_tasks]) if week_tasks else '<div class="empty">Chưa có task tuần này trong sheet.</div>'
    out.append(_section(f"Tuần {ws:%d/%m} – {we:%d/%m}", f'<div class="grid4">{lists}</div>'
                        f'<div class="st2">Task tuần · {len(week_tasks)}</div>{tasks}'))
    return "".join(out)


def _rank(data: dict) -> str:
    from .report import rank_change
    site, vols = data["site"], data["vols"]
    rows = []
    for k in sorted(data["ranks"], key=lambda k: (k["rank"] is None, k["rank"] or 0, k["keyword"])):
        v = vols.get(k["id"])
        vol = "chờ lấy" if not v else ("< 10" if v["volume"] is None else F.n(v["volume"]))
        text, color, _ = rank_change(k["date"], k["rank"], k["last_depth"], k["prev"], k["prev_depth"])
        pos = (str(k["rank"]) if k["rank"] is not None else f">{k['last_depth']}") if k["date"] else "chờ check"
        rows.append([e(k["keyword"]), e(vol), e(pos), f'<span style="color:{color};font-weight:600">{e(text)}</span>',
                     e(k["best"] or ""), e(_path(k["ranking_url"], site) if k["ranking_url"] else "–"),
                     e(_path(k["target_url"], site) if k["target_url"] else "–")])
    return ('<div class="ph"><div class="eb">SEO</div><h1>Từ khóa &amp; rank</h1>'
            '<div class="sub">Google mobile, Việt Nam, qua DataForSEO · volume Google Ads hằng tháng</div></div>'
            + _section(f"Danh sách keyword · {len(rows)}", _table(
                ["Từ khóa", "Volume", "Vị trí", "Thay đổi", "Tốt nhất", "URL đang xếp hạng", "URL mục tiêu"],
                rows, {1, 2})))


def render(data: dict) -> dict:
    charts = Charts()
    tabs = [("week", "Báo cáo tuần", _report(data["week"], data["site"], charts)),
            ("month", "Báo cáo tháng", _report(data["month"], data["site"], charts))]
    if data["okr"]:
        tabs.append(("okr", "Công việc & OKR", _okr(data["okr"], data["today"], charts)))
    tabs.append(("rank", "Từ khóa & rank", _rank(data)))
    nav = "".join(f'<button data-tab="{k}">{e(t)}</button>' for k, t, _ in tabs)
    panes = "".join(f'<div class="pane" data-pane="{k}">{body}</div>' for k, _, body in tabs)
    return {"nav": nav, "html": panes, "charts": charts.items,
            "stamp": f"Số liệu GSC đến {data['end']:%d/%m/%Y} · chụp lúc {datetime.now():%H:%M %d/%m/%Y}"}


# ---- Mã hóa ----

def encrypt(payload: dict, password: str) -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"salt": b64(salt), "iv": b64(iv), "ct": b64(ct), "iter": ITERATIONS}


def decrypt(blob: dict, password: str) -> dict:
    """Ngược với encrypt (dùng để kiểm tra)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    d = {k: base64.b64decode(blob[k]) for k in ("salt", "iv", "ct")}
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=d["salt"], iterations=blob["iter"]).derive(
        password.encode())
    return json.loads(AESGCM(key).decrypt(d["iv"], d["ct"], None))


# ---- Trang ----

PAGE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>SEO Report · __HOST__</title>
<link rel="icon" href="favicon.png"><link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<script src="__ECHARTS__"></script>
<style>
:root{--bg:#F4F4EF;--card:#fff;--ink:#1F221E;--muted:#6B6A5E;--line:#E7E5DC;--green:#1E7C31;--red:#C2410C;--amber:#B7791F}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 Inter,system-ui,sans-serif}
.num{font-variant-numeric:tabular-nums}.muted{color:var(--muted)}h1{font:700 26px/1.2 'Be Vietnam Pro',sans-serif;margin:4px 0}
header{position:sticky;top:0;z-index:5;background:rgba(244,244,239,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.hd{max-width:1200px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.hd img{height:34px}.stamp{font-size:12px;color:var(--muted);margin-left:auto}
nav{display:flex;gap:2px;background:#EEECE4;border-radius:999px;padding:3px;overflow-x:auto;max-width:100%}
nav button{border:0;background:transparent;border-radius:999px;padding:5px 14px;font:500 13px Inter;color:#4a4a42;cursor:pointer;white-space:nowrap}
nav button.on{background:#fff;color:var(--ink);font-weight:600;box-shadow:0 1px 2px rgba(31,34,30,.12)}
main{max-width:1200px;margin:0 auto;padding:16px}.pane{display:none}.pane.on{display:block}
.ph{margin:8px 0 16px}.eb{font:500 11px 'JetBrains Mono',monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--green)}
.sub{color:var(--muted);font-size:13px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:16px;min-width:0}
.st{font:600 15px 'Be Vietnam Pro',sans-serif}.ss{font-size:12px;color:var(--muted);margin-bottom:10px}.st2{font-weight:600;margin:14px 0 6px}
.grid4{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:12px}
.grid5{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:16px}
.tile{background:#FAFAF7;border:1px solid var(--line);border-radius:12px;padding:12px;min-width:0}
.tl{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px}.tv{font:700 22px 'Be Vietnam Pro',sans-serif;margin:2px 0}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;flex-shrink:0}.hint{font-size:12px;color:var(--muted)}
.delta{font-size:12px;font-weight:600;border-radius:6px;padding:1px 6px}.delta.up{color:var(--green);background:#E7F3EA}
.delta.down{color:var(--red);background:#FCEDE6}.delta.muted{background:#F1F0EA}
.notes{margin:4px 0 0;padding-left:18px;font-size:13px}.notes .up{color:var(--green)}.notes .down{color:var(--red)}.notes .warn{color:var(--amber)}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th{font:500 11px 'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);text-align:left;padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid #F0EEE6}.r{text-align:right}.warn{color:var(--amber);font-size:12px}
.empty{color:var(--muted);font-size:13px;padding:8px 0}.chip{display:inline-block;font-size:12px;border-radius:999px;padding:3px 10px;margin-bottom:12px}
.chip.amber{background:#FBF1DE;color:var(--amber)}.pre{white-space:pre-line;margin:4px 0}
.row{display:flex;justify-content:space-between;align-items:center}.tag{font:600 11px Inter;background:#F1F0EA;border-radius:999px;padding:1px 8px}
.ot{font-weight:500;margin:6px 0 2px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.9em}
.bar{height:6px;background:#EEECE4;border-radius:3px;margin-top:8px;overflow:hidden}.bar span{display:block;height:100%;background:var(--green)}
.list{list-style:none;margin:6px 0 0;padding:0;font-size:13px}.list li{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.list .dot{margin-right:6px}
#lock{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}
#lock form{background:#fff;border:1px solid var(--line);border-radius:16px;padding:28px;width:100%;max-width:360px;text-align:center}
#lock img{height:44px;margin-bottom:12px}#lock input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;font:14px Inter;margin:14px 0 10px}
#lock button{width:100%;padding:10px;border:0;border-radius:999px;background:var(--ink);color:#fff;font:600 14px Inter;cursor:pointer}
#err{color:var(--red);font-size:13px;min-height:20px;margin-top:8px}#app{display:none}
</style></head><body>
<div id="lock"><form autocomplete="off"><img src="logo.svg" alt=""><div style="font:600 17px 'Be Vietnam Pro'">Báo cáo SEO &amp; GEO</div>
<div class="muted" style="font-size:13px">Bản xem chỉ đọc · nhập mật khẩu để mở</div>
<input id="pw" type="password" placeholder="Mật khẩu" autofocus><button id="go" type="submit">Mở báo cáo</button><div id="err"></div></form></div>
<div id="app"><header><div class="hd"><img src="logo.svg" alt="__HOST__"><nav id="nav"></nav><div class="stamp" id="stamp"></div></div></header><main id="main"></main></div>
<script id="blob" type="application/json">__BLOB__</script>
<script>
const blob = JSON.parse(document.getElementById('blob').textContent);
const ub = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
async function unlock(pw) {
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey({name: 'PBKDF2', salt: ub(blob.salt), iterations: blob.iter, hash: 'SHA-256'},
    base, {name: 'AES-GCM', length: 256}, false, ['decrypt']);
  const plain = await crypto.subtle.decrypt({name: 'AES-GCM', iv: ub(blob.iv)}, key, ub(blob.ct));
  return JSON.parse(new TextDecoder().decode(plain));
}
function show(d) {
  document.getElementById('lock').style.display = 'none';
  document.getElementById('app').style.display = 'block';
  document.getElementById('nav').innerHTML = d.nav;
  document.getElementById('main').innerHTML = d.html;
  document.getElementById('stamp').textContent = d.stamp;
  const inst = {};
  const draw = pane => d.charts.forEach(c => {  // vẽ khi tab hiện ra, để biểu đồ có đúng chiều rộng
    const el = document.getElementById(c.id);
    if (!el || !pane.contains(el) || !window.echarts) return;
    if (inst[c.id]) { inst[c.id].resize(); return; }
    const o = c.option, lab = o.xAxis && o.xAxis.axisLabel && o.xAxis.axisLabel.labels;
    if (lab) o.xAxis.axisLabel.formatter = v => lab[v] || '';
    if (o.tooltip && o.tooltip.trigger === 'item') o.tooltip.formatter = p => p.name;
    inst[c.id] = echarts.init(el); inst[c.id].setOption(o);
  });
  const pick = k => {
    document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('on', b.dataset.tab === k));
    document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.dataset.pane === k));
    try { localStorage.setItem('tab', k); } catch (e) {}
    draw(document.querySelector(`[data-pane="${k}"]`));
  };
  document.querySelectorAll('#nav button').forEach(b => b.onclick = () => pick(b.dataset.tab));
  let first = 'week'; try { first = localStorage.getItem('tab') || 'week'; } catch (e) {}
  if (!document.querySelector(`[data-pane="${first}"]`)) first = 'week';
  pick(first);
  addEventListener('resize', () => Object.values(inst).forEach(c => c.resize()));
}
document.querySelector('#lock form').onsubmit = async ev => {
  ev.preventDefault();
  const btn = document.getElementById('go'), err = document.getElementById('err');
  btn.disabled = true; btn.textContent = 'Đang mở…'; err.textContent = '';
  try {
    const pw = document.getElementById('pw').value;
    show(await unlock(pw));
    try { sessionStorage.setItem('pw', pw); } catch (e) {}
  } catch (e) { err.textContent = 'Sai mật khẩu.'; btn.disabled = false; btn.textContent = 'Mở báo cáo'; }
};
(async () => { let pw = null; try { pw = sessionStorage.getItem('pw'); } catch (e) {}
  if (pw) { try { show(await unlock(pw)); } catch (e) {} } })();
</script></body></html>
"""

VERCEL_JSON = {"headers": [{"source": "/(.*)", "headers": [
    {"key": "X-Robots-Tag", "value": "noindex, nofollow"},
    {"key": "Referrer-Policy", "value": "no-referrer"},
    {"key": "X-Frame-Options", "value": "DENY"},
    {"key": "Cache-Control", "value": "no-store"}]}]}


def export(cfg, out_dir: Path, password: str, today: date | None = None) -> Path:
    """Ghi index.html (đã mã hóa) + logo + vercel.json vào out_dir; xóa sạch out_dir trước để không sót file cũ."""
    if len(password) < 10:
        raise ValueError("Mật khẩu cần ít nhất 10 ký tự")
    payload = render(collect(cfg, today))
    blob = encrypt(payload, password)
    host = cfg.site_url.split("//")[-1].strip("/")
    page = (PAGE.replace("__HOST__", e(host)).replace("__ECHARTS__", ECHARTS)
            .replace("__BLOB__", json.dumps(blob).replace("</", "<\\/")))
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    assets = Path(__file__).parent / "assets"
    for name in ("logo.svg", "favicon.png"):
        shutil.copy(assets / name, out_dir / name)
    (out_dir / "vercel.json").write_text(json.dumps(VERCEL_JSON, indent=2), encoding="utf-8")
    return out_dir / "index.html"
