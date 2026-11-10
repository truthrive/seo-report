"""AI đọc sheet cam kết KPI (bố cục bất kỳ) và trả về bảng cam kết cho trang Sửa cam kết điền sẵn (người dùng xem lại
rồi mới Lưu).

Kiểm tra đầu ra để AI không bịa:
- Mỗi con số AI trả phải có trong nội dung sheet (so sau khi chuẩn hoá 1.234 / 1,234 / 40% / 0,4); số không có thì bỏ
  ô đó (để trống) và đếm vào "bỏ".
- Từ khóa phải xuất hiện trong sheet; một từ khóa chỉ thuộc một mốc Top (mốc nhỏ hơn thắng).
- Số tháng 1–36; % > 1 hiểu là phần trăm (40 → 40%)."""
import json
import re

from . import ai_http as AH
from . import ai_writer as AW

ROW_KEYS = ("top3", "top5", "top10", "organic", "ai")
MAX_CELLS = 6000

SYSTEM = (
    "Bạn đọc bảng cam kết KPI SEO từ Google Sheet (bố cục có thể khác nhau) và chép lại đúng số liệu.\n"
    "Quy tắc bắt buộc:\n"
    "- Chỉ chép số và từ khóa có trong sheet; không tự tính, không đoán. Ô không có thì để null.\n"
    "- Cam kết thứ hạng: số từ khóa (hoặc %) trong Top 3 / Top 5 / Top 10 theo từng tháng.\n"
    "- Traffic: số phiên Organic / AI đạt được mỗi tháng. Nếu sheet ghi dạng tăng thêm / cộng dồn thì vẫn chép đúng "
    "số trong sheet và ghi rõ trong notes.\n"
    "- Từ khóa: chia theo mốc Top mục tiêu (3 / 5 / 10) nếu sheet có cột Top mục tiêu; không có thì để danh sách rỗng.\n"
    "- Chỉ trả về một đối tượng JSON hợp lệ, không thêm chữ nào ngoài JSON.")

SHAPE = """{
  "start": "dd/mm/yyyy hoặc rỗng",
  "months": 12,
  "rows": {
    "top3": {"unit": "count|pct", "values": [null, 6, 16]},
    "top5": {"unit": "count|pct", "values": []},
    "top10": {"unit": "count|pct", "values": []},
    "organic": {"values": []},
    "ai": {"values": []}
  },
  "keywords": {"3": [{"keyword": "...", "url": ""}], "5": [], "10": []},
  "notes": "1-2 câu: sheet ghi gì khác thường (nếu có)"
}"""


def sheet_text(cfg, sid: str) -> str:
    """Toàn bộ tab của sheet thành chữ gọn (mỗi dòng: tên tab | ô1 | ô2…), cắt bớt cho vừa."""
    from googleapiclient.discovery import build

    from . import auth
    svc = build("sheets", "v4", credentials=auth.get_credentials(cfg, need=(auth.SHEETS_SCOPE,)),
                cache_discovery=False)
    titles = [s["properties"]["title"] for s in svc.spreadsheets().get(
        spreadsheetId=sid, fields="sheets(properties(title))").execute()["sheets"]]
    # ưu tiên các tab có chữ KPI / cam kết / từ khóa
    pri = [t for t in titles if re.search(r"kpi|cam k|t[ừu] kh[óo]a|keyword", t, re.I)]
    order = pri + [t for t in titles if t not in pri]
    out, cells = [], 0
    for t in order[:8]:
        rng = "'" + t.replace("'", "''") + "'!A1:AZ400"
        rows = svc.spreadsheets().values().get(spreadsheetId=sid, range=rng,
                                               valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
        out.append(f"### Tab: {t}")
        for r in rows:
            vals = [str(v).strip() for v in r]
            if not any(vals):
                continue
            out.append(" | ".join(vals))
            cells += len(vals)
            if cells > MAX_CELLS:
                break
        if cells > MAX_CELLS:
            break
    return "\n".join(out)


def _nums(text: str) -> set[str]:
    out = set()
    for m in re.findall(r"\d[\d.,]*", text or ""):
        m = m.rstrip(".,")
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", m):
            m = re.sub(r"[.,]", "", m)
        else:
            m = m.replace(",", ".")
        try:
            f = float(m)
        except ValueError:
            continue
        out.add(f"{f:g}")
    return out


def check(raw: dict, text: str) -> dict:
    """Áp quy tắc kiểm tra; trả {start, months, rows: {key: {unit, values: [..]}}, keywords: {3: [...]}, dropped, notes}."""
    allowed = _nums(text)
    low = text.lower()
    dropped = 0
    try:
        months = max(1, min(36, int(raw.get("months") or 0)))
    except (TypeError, ValueError):
        months = 0
    rows = {}
    for key in ROW_KEYS:
        r = (raw.get("rows") or {}).get(key) or {}
        vals = list(r.get("values") or [])
        unit = "pct" if key.startswith("top") and r.get("unit") == "pct" else "count"
        clean = []
        for v in vals[:36]:
            if v in (None, ""):
                clean.append(None)
                continue
            sv = str(v).replace("%", "").strip()
            if re.fullmatch(r"\d{1,3}([.,]\d{3})+", sv):  # 26.500 / 26,500 = hai mươi sáu nghìn rưỡi
                sv = re.sub(r"[.,]", "", sv)
            try:
                f = float(sv.replace(",", "."))
            except ValueError:
                clean.append(None)
                dropped += 1
                continue
            if f"{f:g}" not in allowed and f"{f * 100:g}" not in allowed:
                clean.append(None)  # số không có trong sheet: bỏ
                dropped += 1
                continue
            if unit == "pct":
                f = f / 100 if f > 1 else f
                clean.append(round(f, 4))
            else:
                clean.append(int(round(f)))
        rows[key] = {"unit": unit, "values": clean}
        months = max(months, len(clean)) if not raw.get("months") else months
    seen: set[str] = set()
    kws = {}
    for top in ("3", "5", "10"):
        lst = []
        for k in ((raw.get("keywords") or {}).get(top) or []):
            kw = " ".join(str((k or {}).get("keyword") if isinstance(k, dict) else k or "").split())
            if not kw or kw.lower() in seen:
                continue
            if kw.lower() not in low:
                dropped += 1
                continue
            seen.add(kw.lower())
            url = str((k or {}).get("url") or "").strip() if isinstance(k, dict) else ""
            lst.append({"keyword": kw, "url": url if url and url.lower() in low else ""})
        kws[int(top)] = lst
    start = str(raw.get("start") or "").strip()
    if start and not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", start):
        start = ""
    return {"start": start, "months": months or max((len(r["values"]) for r in rows.values()), default=0) or 12,
            "rows": rows, "keywords": kws, "dropped": dropped, "notes": " ".join(str(raw.get("notes") or "").split())[:300]}


def read(cfg, text: str, prov: dict | None = None, opener=None) -> tuple[dict, dict]:
    prov = prov or AW.provider(cfg, "kpi_import")
    out = AH.complete(prov["style"], prov["base"], prov["key"], prov["model"],
                      "Nội dung sheet:\n" + text + "\n\nTrả về JSON đúng dạng:\n" + SHAPE, system=SYSTEM,
                      max_tokens=6000, timeout=180, opener=opener)
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        raw = json.loads(m.group(0)) if m else None
    except ValueError:
        raw = None
    if not isinstance(raw, dict):
        raise AH.AIError("AI không trả về đúng định dạng, bấm lại")
    res = check(raw, text)
    if not any(v is not None for r in res["rows"].values() for v in r["values"]) and not any(res["keywords"].values()):
        raise AH.AIError("AI không tìm thấy bảng cam kết trong sheet")
    return res, prov
