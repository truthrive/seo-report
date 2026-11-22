"""AI viết "đoạn còn thiếu" cho trang đang ở vị trí 4–15 (SEO Opportunities › Striking Distance).

Ý tưởng: trang đã xếp hạng cho từ khóa nhưng chưa vào top 3, thường vì thiếu một phần trả lời đúng ý người tìm. Thay vì
viết bài mới (dễ thành hai trang tranh nhau), AI đọc nội dung hiện tại của trang và viết thêm đúng phần còn thiếu:
- một tiêu đề H2 và đoạn 120–180 từ, kèm gợi ý đặt sau mục nào của trang;
- một câu hỏi đáp (FAQ);
- tiêu đề SEO gợi ý khi tiêu đề hiện tại chưa nói tới ý của từ khóa;
- 2–3 anchor text để đặt link nội bộ từ trang khác về trang này.

Team đọc, sửa rồi tự đưa lên website: tool không ghi gì lên website. Dữ liệu gửi cho AI: từ khóa, vị trí / lượt hiển thị
từ Search Console, các từ khóa khác của trang, tiêu đề + dàn ý + một phần nội dung chữ của trang (trang công khai của
chính website). Không gửi email, tài khoản hay số GA4."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin

from . import ai_http as AH
from . import ai_writer as AW
from . import keywords as K

KIND = "page_gap"        # loại bản nháp trong ai_drafts
TASK = "page_gap"        # tác vụ ở Quản trị › AI
ACTION = "ai_page_gap"   # mã credit của Member
MAX_TEXT = 6000          # ký tự nội dung chữ của trang gửi cho AI
MAX_HEADINGS = 40
MAX_HOPS = 3             # số lần theo chuyển hướng khi đọc trang
SECTION_WORDS = (120, 180)


# ---------------------------------------------------------------- đọc trang

class _Outline(HTMLParser):
    """Tiêu đề, mô tả, H1, dàn ý H2–H3 và nội dung chữ chính (bỏ menu, đầu / chân trang, cột bên, form, script)."""
    SKIP = {"script", "style", "noscript", "template", "svg", "nav", "header", "footer", "aside", "form", "iframe"}
    BLOCK = {"p", "li", "td", "th", "blockquote", "dd", "dt", "figcaption", "h1", "h2", "h3", "h4", "div", "section",
             "article", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = self.desc = None
        self.h1: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self._skip = 0
        self._head: str | None = None
        self._head_buf: list[str] = []
        self._in_title = False
        self._title_buf: list[str] = []
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
            return
        if tag == "title" and self.title is None:
            self._in_title = True
        elif tag == "meta" and self.desc is None:
            a = {k: (v or "") for k, v in attrs}
            if (a.get("name") or a.get("property") or "").lower() in ("description", "og:description"):
                self.desc = " ".join(a.get("content", "").split()) or None
        if self._skip:
            return
        if tag in ("h1", "h2", "h3"):
            self._head, self._head_buf = tag, []
        if tag in self.BLOCK:
            self._text.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = " ".join("".join(self._title_buf).split()) or None
        if tag == self._head:
            text = " ".join("".join(self._head_buf).split())
            if text:
                if tag == "h1":
                    self.h1.append(text)
                elif len(self.headings) < MAX_HEADINGS:
                    self.headings.append((int(tag[1]), text))
            self._head = None
        if tag in self.BLOCK:
            self._text.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self._title_buf.append(data)
        if self._skip:
            return
        if self._head:
            self._head_buf.append(data)
        self._text.append(data)


def outline(html: str) -> dict:
    """{"title", "desc", "h1", "headings": [(cấp, chữ)], "text", "words"} của một trang HTML."""
    p = _Outline()
    try:
        p.feed(html or "")
    except Exception:  # noqa: BLE001 — HTML hỏng: lấy được tới đâu dùng tới đó
        pass
    lines = [" ".join(x.split()) for x in "".join(p._text).split("\n")]
    text = "\n".join(x for x in lines if x)
    return {"title": p.title, "desc": p.desc, "h1": p.h1[:3], "headings": p.headings, "text": text[:MAX_TEXT],
            "words": len(text.split())}


def read_page(url: str, fetch=None) -> dict:
    """Đọc trang đang xếp hạng (website của chính khách hàng, UA SEOReportBot như Technical Audit), theo tối đa
    MAX_HOPS lần chuyển hướng. Trả outline + {"ok", "status", "url", "error"}; không đọc được thì ok = False."""
    if fetch is None:
        from .site_audit import fetch
    cur, r = url, {}
    for _ in range(MAX_HOPS + 1):
        r = fetch(cur)
        if r.get("final_url") and r.get("status") in (301, 302, 303, 307, 308):
            cur = urljoin(cur, r["final_url"])
            continue
        break
    base = {"url": cur, "status": r.get("status"), "error": r.get("error")}
    if r.get("blocked"):
        return {**base, "ok": False, "error": "tường lửa của website chặn tool đọc trang"}
    if r.get("status") != 200 or not r.get("html"):
        why = r.get("error") or (f"trang trả mã {r.get('status')}" if r.get("status") else "không mở được trang")
        return {**base, "ok": False, "error": why}
    o = outline(r["html"])
    return {**base, **o, "ok": o["words"] >= 30, "error": None if o["words"] >= 30 else
            "trang gần như không có chữ (có thể nội dung tải bằng JavaScript)"}


# ---------------------------------------------------------------- prompt

SYSTEM = (
    "Bạn là biên tập viên SEO. Nhiệm vụ: một trang của website đang xếp hạng 4–15 trên Google cho một từ khóa nhưng "
    "chưa vào top 3. Hãy tìm phần nội dung trang còn thiếu so với ý định tìm kiếm của từ khóa và viết đúng phần đó để "
    "chèn vào trang hiện có (không viết lại cả bài, không viết bài mới).\n"
    "Quy tắc bắt buộc:\n"
    "- Viết bằng ngôn ngữ của trang. Văn phong tự nhiên, rõ ràng, trả lời thẳng; không nhồi từ khóa, không quảng cáo "
    "lố.\n"
    "- Không lặp lại ý trang đã có; nếu trang đã trả lời đủ thì viết phần làm rõ / bổ sung sâu hơn.\n"
    "- Không bịa số liệu, giá, thông số, địa chỉ, chính sách, trích dẫn. Chỗ cần thông tin riêng của doanh nghiệp thì "
    "để dạng [điền …] cho người viết điền. Được dùng kiến thức phổ thông đã được công nhận.\n"
    "- Chỉ trả về một đối tượng JSON hợp lệ, không thêm chữ nào ngoài JSON.")


def _fmt_pos(v) -> str:
    return "–" if v is None else f"{v:.1f}".replace(".", ",")


def prompt(row: dict, page: dict, queries: list[dict]) -> str:
    """row: một dòng Striking Distance (query, url, position, impressions, clicks)."""
    others = "\n".join(f"- {q['query']} (vị trí {_fmt_pos(q.get('position'))}, {q.get('impressions', 0)} lượt hiển "
                       f"thị)" for q in queries if K.fold(q["query"]) != K.fold(row["query"]))[:1500] or "- (không có)"
    if page.get("ok"):
        heads = "\n".join(("  " if lv == 3 else "") + f"H{lv}: {t}" for lv, t in page.get("headings") or []) \
            or "(trang không có H2 / H3)"
        body = (f"Tiêu đề trang (title): {page.get('title') or '(không có)'}\n"
                f"Mô tả (meta description): {page.get('desc') or '(không có)'}\n"
                f"H1: {' | '.join(page.get('h1') or []) or '(không có)'}\n"
                f"Dàn ý hiện tại:\n{heads}\n\n"
                f"Nội dung chữ của trang (đã rút gọn):\n\"\"\"\n{page.get('text', '')}\n\"\"\"")
    else:
        body = (f"KHÔNG đọc được nội dung trang ({page.get('error') or 'lỗi'}). Chỉ dựa vào từ khóa và đường dẫn trang; "
                "ghi rõ trong diagnosis rằng chưa xem được nội dung trang.")
    return (
        f"Từ khóa: {row['query']}\n"
        f"Trang đang xếp hạng: {row['url']}\n"
        f"Search Console 28 ngày: vị trí trung bình {_fmt_pos(row.get('position'))}, "
        f"{row.get('impressions', 0)} lượt hiển thị, {row.get('clicks', 0)} click\n"
        f"Các từ khóa khác trang này đang nhận lượt hiển thị:\n{others}\n\n"
        f"{body}\n\n"
        "Hãy trả về JSON đúng dạng:\n"
        "{\n"
        '  "diagnosis": "1–2 câu: trang đang thiếu gì so với điều người tìm từ khóa muốn biết",\n'
        '  "heading": "tiêu đề H2 mới cho phần bổ sung",\n'
        '  "placement": "nên đặt phần này ở đâu: sau mục … (ghi đúng tên một tiêu đề có trong dàn ý) hoặc cuối bài",\n'
        '  "section": "đoạn bổ sung 120–180 từ, trả lời thẳng ý của từ khóa ngay câu đầu",\n'
        '  "faq": {"q": "một câu hỏi người tìm hay hỏi", "a": "trả lời 1–2 câu"},\n'
        '  "title": "tiêu đề SEO gợi ý (dưới 60 ký tự) nếu tiêu đề hiện tại chưa nói tới ý của từ khóa; đã ổn thì để """,\n'
        '  "anchors": ["2–3 anchor text tự nhiên để đặt link nội bộ từ trang khác về trang này"]\n'
        "}")


def parse(text: str) -> dict:
    """Kiểm tra và làm sạch JSON AI trả về. Thiếu đoạn bổ sung → AIError (bấm Viết lại)."""
    import json
    import re
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise AH.AIError("AI không trả về đúng định dạng, bấm Viết lại")
    try:
        d = json.loads(m.group(0))
    except ValueError as e:
        raise AH.AIError("AI trả về JSON lỗi, bấm Viết lại") from e

    def s(v) -> str:
        return " ".join(str(v or "").split()) if not isinstance(v, (dict, list)) else ""

    faq = d.get("faq") if isinstance(d.get("faq"), dict) else {}
    out = {"diagnosis": s(d.get("diagnosis")), "heading": s(d.get("heading")), "placement": s(d.get("placement")),
           "section": str(d.get("section") or "").strip(),
           "faq": {"q": s(faq.get("q")), "a": s(faq.get("a"))} if faq.get("q") else None,
           "title": s(d.get("title")),
           "anchors": [s(a) for a in d.get("anchors") or [] if s(a)][:4] if isinstance(d.get("anchors"), list) else []}
    if not out["section"] or not out["heading"]:
        raise AH.AIError("AI chưa viết đoạn bổ sung, bấm Viết lại")
    return out


def write(cfg, row: dict, queries: list[dict], page: dict, prov: dict | None = None,
          opener=None) -> tuple[dict, dict]:
    """Gọi AI; trả (bản nháp kèm ngữ cảnh để xem lại sau, nhà cung cấp đã dùng). Lỗi → AH.AIError / AW.NoProvider."""
    prov = prov or AW.provider(cfg, TASK)
    text = AH.ask(prov, expect_json=True, prompt=prompt(row, page, queries), system=SYSTEM, max_tokens=1800,
                  timeout=150, opener=opener)
    d = parse(text)
    d.update(keyword=row["query"], url=row["url"], position=row.get("position"), impressions=row.get("impressions"),
             page_read=bool(page.get("ok")), page_error=None if page.get("ok") else page.get("error"),
             page_title=page.get("title"))
    return d, prov


def ref_of(url_id: int, query: str) -> str:
    """Mã bản nháp: một trang + một từ khóa."""
    return f"{url_id}|{K.fold(query)}"


def words(text: str) -> int:
    return len((text or "").split())


def as_text(d: dict) -> str:
    """Bản chữ để sao chép."""
    out = [f"Từ khóa: {d.get('keyword', '')}", f"Trang: {d.get('url', '')}", ""]
    if d.get("diagnosis"):
        out += [f"Trang đang thiếu: {d['diagnosis']}", ""]
    if d.get("placement"):
        out += [f"Đặt ở: {d['placement']}", ""]
    out += [f"## {d.get('heading', '')}", d.get("section", ""), ""]
    if d.get("faq"):
        out += ["Hỏi đáp:", f"H: {d['faq']['q']}", f"Đ: {d['faq']['a']}", ""]
    if d.get("title"):
        out += [f"Tiêu đề SEO gợi ý: {d['title']}", ""]
    if d.get("anchors"):
        out += ["Anchor link nội bộ về trang này:"] + [f"- {a}" for a in d["anchors"]]
    return "\n".join(out).strip()
