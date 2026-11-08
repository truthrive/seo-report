"""Dashboard AI Overview theo thương hiệu (dữ liệu từ kết quả check rank, DataForSEO): thương hiệu của mình và đối thủ
được AI **nhắc tên** (trong nội dung chữ) và được **trích** (link trong nguồn AI trích), theo từng tuần.

- Thương hiệu (`aio_brands`): tên, các cách gọi khác, tên miền; một dòng là của mình (own). Tự tạo dòng của mình từ
  tên miền website và từ khóa thương hiệu của dự án.
- Nhận biết nhắc tên: so nội dung chữ AI Overview với tên / cách gọi / tên miền (không phân biệt hoa thường, có dấu hay
  không dấu). Lần check cũ chưa lưu nội dung chữ thì "không biết", không tính vào tỷ lệ nhắc tên.
- Mỗi tuần lấy lần check cuối của tuần đó cho từng từ khóa (mỗi từ khóa một dòng, ưu tiên bộ Cam kết).
"""
import functools
import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone

from . import rank as R
from .projects import domain

SCHEMA = """
CREATE TABLE IF NOT EXISTS aio_brands (
    id INTEGER PRIMARY KEY,
    site TEXT NOT NULL,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '',   -- mỗi dòng một cách gọi
    domains TEXT NOT NULL DEFAULT '',   -- mỗi dòng một tên miền
    own INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    removed_at TEXT
);
"""
# Bảng màu đã qua bộ kiểm tra của skill dataviz (độ sáng, độ đậm, tách màu cho người mù màu): thương hiệu mình là màu
# 1 (xanh dương, không dùng xanh lá / đỏ vì đó là màu tốt / xấu của nhãn ▲▼), 4 đối thủ đầu là màu 2–5; đối thủ thứ 5 trở
# đi xám và không vẽ trên biểu đồ (không sinh thêm màu).
OWN_COLOR = "#2a78d6"
# Màu đối thủ theo thứ tự thêm (cố định theo thương hiệu, không theo hạng); 7 màu + màu của mình đã chạy
# validate_palette (độ sáng, độ đậm, mù màu): đối thủ thứ 8 trở đi màu xám
COLORS = ["#eb6834", "#1a9e8f", "#6250d6", "#eda100", "#b04a8f", "#7d9a1e", "#e87ba4"]
OTHER_COLOR = "#A9A79B"


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    if "logo" not in {c[1] for c in con.execute("PRAGMA table_info(aio_brands)")}:  # NULL: chưa lấy, '': không lấy được
        con.execute("ALTER TABLE aio_brands ADD COLUMN logo TEXT")
        con.commit()
    R.ensure_tables(con)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_MARKS = re.compile(r"[̀-ͯ᪰-᫿᷀-᷿⃐-⃿︠-︯]")  # dấu kết hợp (Mn)
_WORD = re.compile(r"[a-z0-9]+")


def norm(text: str) -> str:
    """Chữ thường, bỏ dấu (đ → d), chỉ giữ chữ và số, cách nhau một khoảng trắng. Bỏ dấu bằng regex thay vì xét từng
    ký tự: nhanh hơn nhiều lần với chữ AI Overview dài (bộ hàng trăm từ khóa)."""
    t = unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D"))
    return " ".join(_WORD.findall(_MARKS.sub("", t).lower()))


def _lines(v: str) -> list[str]:
    return [x.strip() for x in re.split(r"[\n,;]", v or "") if x.strip()]


def terms(b: dict) -> list[str]:
    """Các chuỗi để nhận biết nhắc tên: tên, cách gọi khác, tên miền và phần trước đuôi tên miền (matkinhtamduc)."""
    return list(_terms(b["name"], tuple(b["aliases"]), tuple(b["domains"])))


@functools.lru_cache(maxsize=512)
def _terms(name: str, aliases: tuple, domains: tuple) -> tuple:
    out = [name, *aliases]
    for d in domains:
        out += [d, d.split(".")[0]]
    return tuple(t for t in dict.fromkeys(norm(x) for x in out) if len(t) >= 3)


def mentioned(text_norm: str, b: dict) -> bool:
    padded = f" {text_norm} "
    return any(f" {t} " in padded for t in terms(b))


def cited(refs: list[dict], b: dict) -> bool:
    return any(R._host_match(x.get("domain") or "", d.lower().removeprefix("www.")) for x in refs for d in b["domains"])


def brands(con: sqlite3.Connection, cfg) -> list[dict]:
    """Thương hiệu đang theo dõi, của mình trước; chưa có dòng của mình thì tạo từ tên miền và từ khóa thương hiệu."""
    ensure_tables(con)
    site = cfg.site_url
    if not con.execute("SELECT 1 FROM aio_brands WHERE site = ? AND own = 1 AND removed_at IS NULL", (site,)).fetchone():
        host = domain(site)
        alias = [t for t in getattr(getattr(cfg, "keywords", None), "brand_terms", ()) or () if t]
        name = (alias[0].title() if alias else host)
        with con:
            con.execute("INSERT INTO aio_brands (site, name, aliases, domains, own, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                        (site, name, "\n".join(alias), host, _now()))
    out = []
    for i, (bid, name, aliases, domains, own, logo) in enumerate(con.execute(
            "SELECT id, name, aliases, domains, own, logo FROM aio_brands WHERE site = ? AND removed_at IS NULL "
            "ORDER BY own DESC, id", (site,))):
        out.append({"id": bid, "name": name, "aliases": _lines(aliases), "domains": _lines(domains),
                    "logo": (getattr(cfg, "logo", "") or logo) if own else logo,
                    "own": bool(own), "charted": bool(own) or i - 1 < len(COLORS),
                    "color": OWN_COLOR if own else (COLORS[i - 1] if i - 1 < len(COLORS) else OTHER_COLOR)})
    return out


MAX_COMPETITORS = 10  # đối thủ theo dõi mỗi dự án (dùng chung cho thứ hạng và AI Overview)


def competitor_count(con, site: str) -> int:
    ensure_tables(con)
    return con.execute("SELECT COUNT(*) FROM aio_brands WHERE site = ? AND own = 0 AND removed_at IS NULL",
                       (site,)).fetchone()[0]


def brand_ranks(organic: list[dict], brands_: list[dict]) -> dict[int, dict | None]:
    """Vị trí tốt nhất của từng thương hiệu trong các kết quả tự nhiên của một lần check: {id: {rank, url} | None}."""
    out = {}
    for b in brands_:
        hit = next((x for x in sorted(organic, key=lambda x: x["rank"]) if cited([x], b)), None)
        out[b["id"]] = {"rank": hit["rank"], "url": hit["url"]} if hit else None
    return out


def save_brand(con, site: str, name: str, aliases: str, domains: str, brand_id: int | None = None) -> int:
    ensure_tables(con)
    name = name.strip()
    if not name:
        raise ValueError("Cần tên thương hiệu")
    if not brand_id and competitor_count(con, site) >= MAX_COMPETITORS:
        raise ValueError(f"Mỗi dự án theo dõi tối đa {MAX_COMPETITORS} đối thủ: bỏ bớt một đối thủ trước khi thêm")
    doms = "\n".join(domain(d) for d in _lines(domains))
    with con:
        if brand_id:
            old = con.execute("SELECT domains FROM aio_brands WHERE id = ?", (brand_id,)).fetchone()
            con.execute("UPDATE aio_brands SET name = ?, aliases = ?, domains = ? WHERE id = ? AND site = ?",
                        (name, "\n".join(_lines(aliases)), doms, brand_id, site))
            if old and old[0] != doms:  # đổi tên miền: lấy lại logo
                con.execute("UPDATE aio_brands SET logo = NULL WHERE id = ?", (brand_id,))
            return brand_id
        cur = con.execute("INSERT INTO aio_brands (site, name, aliases, domains, own, created_at) "
                          "VALUES (?, ?, ?, ?, 0, ?)", (site, name, "\n".join(_lines(aliases)), doms, _now()))
        return cur.lastrowid


def add_or_restore(con, site: str, domain_: str) -> int:
    """Thêm đối thủ theo tên miền; nếu trước đây đã theo dõi rồi bỏ thì khôi phục dòng cũ (giữ tên, cách gọi đã sửa)."""
    ensure_tables(con)
    d = domain(domain_)
    for bid, doms in con.execute("SELECT id, domains FROM aio_brands WHERE site = ? AND own = 0 AND removed_at IS NOT "
                                 "NULL ORDER BY removed_at DESC", (site,)):
        if d in _lines(doms):
            if competitor_count(con, site) >= MAX_COMPETITORS:
                raise ValueError(f"Mỗi dự án theo dõi tối đa {MAX_COMPETITORS} đối thủ: bỏ bớt một đối thủ trước khi thêm")
            with con:
                con.execute("UPDATE aio_brands SET removed_at = NULL WHERE id = ?", (bid,))
            return bid
    return save_brand(con, site, d, "", d)


def remove_brand(con, site: str, brand_id: int) -> None:
    """Bỏ theo dõi (giữ dòng, đánh dấu đã bỏ); không bỏ được thương hiệu của mình."""
    with con:
        con.execute("UPDATE aio_brands SET removed_at = ? WHERE id = ? AND site = ? AND own = 0",
                    (_now(), brand_id, site))


def _week(d: str) -> str:
    x = date.fromisoformat(d)
    return (x - timedelta(days=x.weekday())).isoformat()


def scope_keywords(con, site: str, end: date, set_id: int | None = None) -> list[dict]:
    """Từ khóa đang xét: mọi bộ (mỗi từ khóa một dòng) hoặc một bộ; bỏ bộ Nháp. Từ khóa tạm dừng vẫn tính theo lần
    check gần nhất, trừ khi chưa check lần nào (cùng cách tính với màn Từ khóa & Thứ hạng)."""
    kws = R.primary_keywords(con, site, end) if set_id is None else R.keywords(con, site, end, set_id)
    return [k for k in kws if not k.get("draft") and (not k.get("paused") or k.get("date"))]


def snapshots(con, site: str, end: date, today: date, weeks: int,
              set_id: int | None = None) -> dict[str, dict[int, dict]]:
    """{tuần: {id từ khóa: lần check cuối tuần đó}} trong `weeks` tuần gần nhất (mỗi từ khóa một dòng)."""
    ensure_tables(con)
    kws = scope_keywords(con, site, end, set_id)
    ids = [k["id"] for k in kws]
    if not ids:
        return {}
    since = (today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)).isoformat()
    marks = ",".join("?" * len(ids))
    out: dict[str, dict[int, dict]] = {}
    for kid, d, aio, cit, refs, top10, text in con.execute(
            f"SELECT keyword_id, check_date, aio, aio_cited, aio_refs, top10, aio_text FROM rank_serp "
            f"WHERE aio IS NOT NULL AND check_date >= ? AND keyword_id IN ({marks}) ORDER BY check_date",
            [since, *ids]):
        out.setdefault(_week(d), {})[kid] = {"date": d, "aio": bool(aio), "refs": json.loads(refs or "[]"),
                                             "top10": json.loads(top10 or "[]"), "text": text}
    return out


def week_metrics(snap: dict[int, dict], bs: list[dict], site: str) -> dict:
    """Số của một tuần: có AIO, đọc được chữ / nguồn, từng thương hiệu được nhắc / được trích, website trong top 10."""
    host = domain(site)
    rows = list(snap.values())
    with_aio = [r for r in rows if r["aio"]]
    texted = [r for r in with_aio if r["text"]]
    reffed = [r for r in with_aio if r["refs"]]
    norms = {id(r): norm(r["text"]) for r in texted}
    per = {}
    for b in bs:
        per[b["id"]] = {"mention": sum(1 for r in texted if mentioned(norms[id(r)], b)),
                        "cite": sum(1 for r in reffed if cited(r["refs"], b))}
    return {"checked": len(rows), "aio": len(with_aio), "texted": len(texted), "reffed": len(reffed),
            "organic": sum(1 for r in rows if any(R._host_match(x["domain"], host) for x in r["top10"])),
            "brands": per}


def dashboard(con, cfg, today: date | None = None, weeks: int = 12, set_id: int | None = None) -> dict:
    """Mọi số cho tab AI Overview: các tuần (cũ → mới), thương hiệu, 4 thẻ của mình (tuần mới nhất so với tuần trước),
    tổng số từ khóa."""
    today = today or date.today()
    site = cfg.site_url
    from . import keywords as K
    end = K.latest_date(con, site)
    bs = brands(con, cfg)
    snaps = snapshots(con, site, end, today, weeks, set_id)
    series = [{"week": w, **week_metrics(snaps[w], bs, site)} for w in sorted(snaps)]
    total = len(scope_keywords(con, site, end, set_id))
    own = next(b for b in bs if b["own"])

    def kpis(m: dict | None) -> dict:
        if not m:
            return {}
        o = m["brands"][own["id"]]
        return {"visibility": (o["mention"], m["texted"]), "citations": (o["cite"], m["reffed"]),
                "presence": (m["aio"], m["checked"]), "organic": (m["organic"], m["checked"])}
    return {"weeks": series, "brands": bs, "own": own, "total": total,
            "now": kpis(series[-1] if series else None), "prev": kpis(series[-2] if len(series) > 1 else None),
            "last_week": series[-1]["week"] if series else None}


def keyword_rows(con, cfg, set_id: int | None = None) -> list[dict]:
    """Bảng tab Từ khóa: lần check mới nhất của từng từ khóa, thương hiệu được nhắc / được trích."""
    from . import keywords as K
    site = cfg.site_url
    end = K.latest_date(con, site)
    bs = brands(con, cfg)
    out = []
    for k in scope_keywords(con, site, end, set_id):
        row = con.execute("SELECT check_date, aio, aio_refs, aio_text FROM rank_serp WHERE keyword_id = ? AND aio "
                          "IS NOT NULL ORDER BY check_date DESC LIMIT 1", (k["id"],)).fetchone()
        if not row:
            continue
        d, aio, refs, text = row
        refs = json.loads(refs or "[]")
        tn = norm(text or "")
        out.append({"id": k["id"], "keyword": k["keyword"], "rank": k["rank"], "depth": k["last_depth"], "date": d,
                    "aio": bool(aio), "text": text or "", "refs": refs,
                    "mentioned": [b["name"] for b in bs if text and mentioned(tn, b)],
                    "cited": [b["name"] for b in bs if cited(refs, b)],
                    "own_mentioned": None if not (aio and text) else mentioned(tn, bs[0]),
                    "own_cited": bool(aio) and cited(refs, bs[0])})
    return out


def changes(con, cfg, set_id: int | None = None) -> dict[str, list[dict]]:
    """So lần check mới nhất với lần trước của từng từ khóa (thương hiệu của mình): mới được nhắc, mất nhắc, mới được
    trích, mất trích. Lần nào chưa có nội dung chữ thì không xét nhắc tên."""
    from . import keywords as K
    site = cfg.site_url
    end = K.latest_date(con, site)
    own = brands(con, cfg)[0]
    out = {"new_mention": [], "lost_mention": [], "new_cite": [], "lost_cite": []}
    for k in scope_keywords(con, site, end, set_id):
        rows = con.execute("SELECT check_date, aio, aio_refs, aio_text FROM rank_serp WHERE keyword_id = ? AND aio "
                           "IS NOT NULL ORDER BY check_date DESC LIMIT 2", (k["id"],)).fetchall()
        if len(rows) < 2:
            continue
        (d1, a1, r1, t1), (d0, a0, r0, t0) = rows
        info = {"keyword": k["keyword"], "date": d1, "prev_date": d0}

        def m_state(a, txt):  # không có AIO: không được nhắc; có AIO mà chưa lưu chữ: không biết
            return False if not a else (None if txt is None else mentioned(norm(txt), own))
        m1, m0 = m_state(a1, t1), m_state(a0, t0)
        if m1 is not None and m0 is not None:
            if m1 and not m0:
                out["new_mention"].append(info)
            elif m0 and not m1:
                out["lost_mention"].append(info)
        c1 = bool(a1) and cited(json.loads(r1 or "[]"), own)
        c0 = bool(a0) and cited(json.loads(r0 or "[]"), own)
        if c1 and not c0:
            out["new_cite"].append(info)
        elif c0 and not c1:
            out["lost_cite"].append(info)
    return out


def suggestions(con, cfg, limit: int = 8) -> list[tuple[str, int]]:
    """Website AI hay trích mà chưa có trong danh sách thương hiệu: (tên miền, số từ khóa)."""
    bs = brands(con, cfg)
    have = {d for b in bs for d in b["domains"]}
    count: dict[str, int] = {}
    for r in keyword_rows(con, cfg):
        for d in {x["domain"] for x in r["refs"]}:
            if d and not any(R._host_match(d, h) for h in have):
                count[d] = count.get(d, 0) + 1
    return sorted(count.items(), key=lambda x: (-x[1], x[0]))[:limit]


def fill_logos(con, cfg, fetch=None, limit: int = 10) -> int:
    """Lấy logo cho thương hiệu chưa có (theo tên miền đầu tiên, cùng cách lấy logo dự án: apple-touch-icon → icon lớn
    nhất → favicon, chỉ qua http/https). Không lấy được thì ghi '' để không thử lại mỗi lần mở trang. Trả số đã thử."""
    from .projects import fetch_logo
    fetch = fetch or fetch_logo
    ensure_tables(con)
    rows = con.execute("SELECT id, domains FROM aio_brands WHERE site = ? AND removed_at IS NULL AND own = 0 "
                       "AND logo IS NULL LIMIT ?", (cfg.site_url, limit)).fetchall()
    for bid, domains in rows:
        doms = _lines(domains)
        logo = (fetch(doms[0]) if doms else None) or ""
        with con:
            con.execute("UPDATE aio_brands SET logo = ? WHERE id = ?", (logo, bid))
    return len(rows)
