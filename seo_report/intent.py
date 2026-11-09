"""Ý định tìm kiếm (search intent) của từ khóa, đoán bằng quy tắc, không tốn tiền.

Bốn loại theo cách chia phổ biến (Google / Semrush / Ahrefs):
- I  Informational (Thông tin): muốn biết / học ("cách đọc bảng đo thị lực", "là gì").
- N  Navigational (Điều hướng): tìm một thương hiệu / website cụ thể ("mắt kính tâm đức").
- C  Commercial (Cân nhắc mua): đang tìm hiểu sản phẩm để chọn ("gọng kính nam", "bảng giá tròng kính chemi").
- T  Transactional (Mua / giao dịch): muốn mua hoặc đến cửa hàng ngay ("mua kính cận ở đâu", "cắt kính gần đây").

Thứ tự xét: tên thương hiệu đang theo dõi → chữ chỉ thông tin → chữ chỉ mua ngay / ô bản đồ (local pack) → chữ chỉ
cân nhắc → kết quả Google (nhiều bài viết trong top 10 → Thông tin, còn lại → Cân nhắc mua).
"""
import json
import math
import re
import unicodedata

INTENTS = {"I": ("Informational", "Thông tin"), "N": ("Navigational", "Điều hướng"),
           "C": ("Commercial", "Cân nhắc mua"), "T": ("Transactional", "Mua / giao dịch")}

_INFO = ("cach", "la gi", "tai sao", "vi sao", "the nao", "nhu the nao", "huong dan", "nguyen nhan", "trieu chung",
         "bao lau", "co nen", "co tot khong", "co hai khong", "kien thuc", "y nghia", "phan biet",
         "bang do", "do thi luc", "kham mat", "lam sao")
# Chữ dễ nhầm khi bỏ dấu ("mèo" / "mẹo", "đọc" / "dọc", "bị" / "bí"): so có dấu
_INFO_ACCENT = ("mẹo", "đọc", "bị")
_TRANS = ("mua", "dat hang", "dat mua", "o dau", "dia chi", "cua hang", "shop", "gan day", "gan nhat",
          "khuyen mai", "giam gia", "gia re", "uu dai", "freeship", "ship", "hotline", "tai ha noi", "tai hcm",
          "tphcm", "ha noi", "sai gon", "quan ")
_COMM = ("gia", "bang gia", "review", "danh gia", "so sanh", "tot nhat", "loai nao", "nen mua", "top ",
         "chinh hang", "thuong hieu", "dep", "cao cap", "hang hieu", "loai", "mau")
_ARTICLE = re.compile(r"/(blog|blogs|tin-tuc|tintuc|news|kien-thuc|bai-viet|cam-nang|huong-dan|wiki|hoi-dap|"
                      r"tu-van|goc-tu-van|chia-se)(/|$)|\.html?$|/\d{4}/\d{2}/", re.I)


def _plain(t: str) -> str:
    t = unicodedata.normalize("NFD", (t or "").lower().replace("đ", "d"))
    return " " + " ".join("".join(ch for ch in t if unicodedata.category(ch) != "Mn").split()) + " "


def _has(text: str, words) -> str | None:
    for w in words:
        if f" {w.strip()} " in text or (w.endswith(" ") and f" {w}" in text):
            return w.strip()
    return None


def classify(keyword: str, features: list[str] | None = None, top10: list[dict] | None = None,
             brand_terms: list[str] | None = None) -> tuple[str, str]:
    """(mã I/N/C/T, lý do ngắn)."""
    k = _plain(keyword)
    for b in brand_terms or []:
        pb = _plain(b).strip()
        if pb and f" {pb} " in k:
            return "N", f"có tên thương hiệu “{b}”"
    if w := (_has(k, _INFO) or _has(" " + " ".join((keyword or "").lower().split()) + " ", _INFO_ACCENT)):
        return "I", f"có chữ “{w}”"
    if w := _has(k, _TRANS):
        return "T", f"có chữ “{w}”"
    if "local_pack" in (features or []):
        return "T", "Google hiện bản đồ cửa hàng"
    if w := _has(k, _COMM):
        return "C", f"có chữ “{w}”"
    urls = [x.get("url") or "" for x in (top10 or [])]
    if urls:
        articles = sum(1 for u in urls if _ARTICLE.search(u.split("?")[0]))
        if articles * 2 >= len(urls):
            return "I", f"{articles}/{len(urls)} kết quả đầu là bài viết"
        return "C", f"{len(urls) - articles}/{len(urls)} kết quả đầu là trang sản phẩm / danh mục"
    return "C", "từ khóa sản phẩm (chưa có kết quả Google để xét thêm)"


def label(code: str) -> str:
    en, vi = INTENTS.get(code, ("", ""))
    return f"{en} ({vi})" if en else ""


def for_keywords(con, cfg, kws: list[dict]) -> dict[int, tuple[str, str]]:
    """{keyword_id: (mã, lý do)}: ý định DataForSEO đã lấy (kèm độ chắc chắn); chưa có thì đoán theo quy tắc (chữ
    của từ khóa + trang kết quả Google của lần check gần nhất)."""
    from . import aio as AO
    ds = stored(con, getattr(getattr(cfg, "rank", None), "language_code", "vi"))
    terms = []
    for b in AO.brands(con, cfg):
        terms += [b["name"]] + b["aliases"] + [d.split(".")[0] for d in b["domains"]]
    out = {}
    for k in kws:
        d = ds.get(_key(k["keyword"]))
        if d:
            why = f"DataForSEO, chắc {d['probability'] * 100:.0f}%" if d["probability"] is not None else "DataForSEO"
            sec = [(c_, p_) for c_, p_ in d["secondary"] if c_ in INTENTS and c_ != d["intent"] and p_]
            out[k["id"]] = (d["intent"], why, sec, d["probability"])
            continue
        row = con.execute("SELECT features, organic, top10 FROM rank_serp WHERE keyword_id = ? AND "
                          "(features IS NOT NULL OR top10 IS NOT NULL) ORDER BY check_date DESC LIMIT 1",
                          (k["id"],)).fetchone()
        feats = json.loads(row[0] or "[]") if row else []
        top = json.loads(row[2] or "[]") if row else []
        code, why = classify(k["keyword"], feats, top, terms)
        out[k["id"]] = (code, f"tool đoán ({why})", [], None)
    return out


def tip(v: tuple | None) -> str:
    """Chú thích khi rê chuột: ý định chính (nguồn, độ chắc) và các ý định khác."""
    if not v or not v[0]:
        return ""
    main = f"{label(v[0])}: {v[1]}"
    others = "; ".join(f"{label(c)} {p * 100:.0f}%" for c, p in (v[2] if len(v) > 2 else []))
    return main + (f" · có thể là: {others}" if others else "")


def excel_cells(v: tuple | None) -> list[str]:
    """Hai ô cho file Excel: ý định chính, các ý định khác. Chỉ ghi tên tiếng Anh (Commercial, Informational…)."""
    if not v or not v[0]:
        return ["", ""]
    return [INTENTS[v[0]][0], ", ".join(INTENTS[c][0] for c, _ in (v[2] if len(v) > 2 else []) if c in INTENTS)]


# ---- Ý định từ DataForSEO Labs (search_intent) ----
# Giá (11/2026): 0,012 USD mỗi lần gọi + 0,00012 USD mỗi từ khóa, tối đa 1.000 từ khóa một lần gọi. Mỗi từ khóa chỉ
# lấy một lần (lưu theo chữ + ngôn ngữ), từ khóa mới thêm thì lấy bổ sung.
ENDPOINT = "https://api.dataforseo.com/v3/dataforseo_labs/google/search_intent/live"
BATCH = 1000
CODES = {"informational": "I", "navigational": "N", "commercial": "C", "transactional": "T"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS keyword_intent (
    keyword TEXT NOT NULL,       -- chữ thường, gọn khoảng trắng
    language TEXT NOT NULL,
    intent TEXT NOT NULL,        -- I / N / C / T
    probability REAL,
    secondary TEXT,              -- JSON [[mã, xác suất], …]
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (keyword, language)
);
CREATE TABLE IF NOT EXISTS intent_runs (
    run_at TEXT NOT NULL,
    keywords INTEGER NOT NULL,
    cost REAL NOT NULL
);
"""


def ensure_tables(con) -> None:
    con.executescript(SCHEMA)


def _key(kw: str) -> str:
    return " ".join((kw or "").lower().split())


def spent_this_month(con, today) -> float:
    ensure_tables(con)
    return con.execute("SELECT COALESCE(SUM(cost), 0) FROM intent_runs WHERE substr(run_at, 1, 7) = ?",
                       (today.strftime("%Y-%m"),)).fetchone()[0]


def stored(con, language: str) -> dict[str, dict]:
    ensure_tables(con)
    return {k: {"intent": i, "probability": p, "secondary": json.loads(s or "[]")}
            for k, i, p, s in con.execute("SELECT keyword, intent, probability, secondary FROM keyword_intent "
                                          "WHERE language = ?", (language,))}


def fetch_missing(con, cfg, creds, log=print, post=None) -> int:
    """Lấy ý định cho các từ khóa (mọi bộ, kể cả Nháp) chưa có. Dự án tạm ngưng check hoặc hết ngân sách: bỏ qua.
    Trả số từ khóa đã lấy. post(body) -> phản hồi JSON (để test)."""
    from datetime import date, datetime, timezone

    from . import rank as R
    ensure_tables(con)
    s = cfg.rank
    if getattr(s, "paused", False):
        return 0
    lang = s.language_code
    have = stored(con, lang)
    want = sorted({_key(k) for (k,) in con.execute(
        "SELECT keyword FROM rank_keywords WHERE site = ? AND removed_at IS NULL", (cfg.site_url,))} - set(have))
    if not want:
        return 0
    cost_est = 0.012 * math.ceil(len(want) / BATCH) + 0.00012 * len(want)
    if R.spent_this_month(con, date.today()) + cost_est > s.monthly_budget_usd:
        log(f"Chưa lấy ý định tìm kiếm: cần khoảng {cost_est:.3f} USD, vượt ngân sách DataForSEO tháng này.")
        return 0
    if post is None:
        from urllib.request import Request, urlopen
        headers = R.DataForSEO(*creds).headers

        def post(body):
            return json.loads(urlopen(Request(ENDPOINT, data=json.dumps(body).encode(), headers=headers),
                                      timeout=120).read())
    got = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for i in range(0, len(want), BATCH):
        chunk = want[i:i + BATCH]
        resp = post([{"keywords": chunk, "language_code": lang}])
        task = (resp.get("tasks") or [{}])[0]
        if task.get("status_code") != 20000:
            log(f"DataForSEO không trả ý định tìm kiếm: {task.get('status_message')}")
            break
        with con:
            con.execute("INSERT INTO intent_runs VALUES (?, ?, ?)", (now, len(chunk), task.get("cost") or 0))
            for it in (task.get("result") or [{}])[0].get("items") or []:
                main = it.get("keyword_intent") or {}
                code = CODES.get(main.get("label"))
                if not code:
                    continue
                sec = [[CODES.get(x.get("label"), ""), x.get("probability")]
                       for x in it.get("secondary_keyword_intents") or [] if CODES.get(x.get("label"))]
                con.execute("INSERT OR REPLACE INTO keyword_intent VALUES (?, ?, ?, ?, ?, ?)",
                            (_key(it.get("keyword")), lang, code, main.get("probability"), json.dumps(sec), now))
                got += 1
    return got
