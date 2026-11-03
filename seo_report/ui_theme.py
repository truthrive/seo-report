"""Bộ giao diện chung: màu thương hiệu, CSS, và các khối dùng lại (tiêu đề trang, thẻ KPI có sparkline, khung mục,
nhãn trạng thái, ô số có thanh). Mọi màn dùng chung để nhìn đồng bộ.

Bảng màu của tool: xanh lá #1E7C31, xanh chanh #B8D332. Phong cách (nền kem ấm, tiêu đề đậm hai tông, nhãn
mono in hoa, thẻ trắng bo lớn, nút viên thuốc đen) tham khảo lucianlabs.dev theo yêu cầu.
"""
import re
from html import escape
from contextlib import contextmanager

GREEN, LIME, CREAM, INK, MUTED = "#1E7C31", "#B8D332", "#EDEDE5", "#1F221E", "#6B6A5E"
RED, AMBER, BLUE, GREY = "#C2410C", "#B7791F", "#2563EB", "#8C8A7E"
AMBER_TEXT = "#8F5F14"  # hổ phách đậm cho chữ: đủ tương phản 4,5:1 trên nền trắng và nền kem
PAGE_BG = "#F4F4EF"

HEAD = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Be+Vietnam+Pro:wght@600;700;800&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  /* Phong cách tham khảo lucianlabs.dev: nền kem ấm, tiêu đề đậm, nhãn mono in hoa, thẻ trắng bo lớn, nút viên thuốc. */
  :root { --ink: #1F221E; --muted: #6B6A5E; --soft: #8E8D80; --line: #E4E3DA; --green: #1E7C31; --lime: #C5E063;
          --bg: #F4F4EF; --head: 'Be Vietnam Pro', Inter, sans-serif; --mono: 'JetBrains Mono', ui-monospace, monospace; }
  body { font-family: Inter, 'Segoe UI', sans-serif; background: var(--bg); color: var(--ink);
         font-feature-settings: 'tnum' 1, 'cv11' 1; letter-spacing: -0.006em; }
  .muted { color: var(--muted); }
  .num { font-variant-numeric: tabular-nums; }
  .sr-head { font-family: var(--head); }
  /* tiêu đề trang: nhãn mono + tiêu đề lớn hai tông */
  .sr-eyebrow { font-family: var(--mono); font-size: 11.5px; font-weight: 600; letter-spacing: .08em;
                text-transform: uppercase; color: var(--muted); display: flex; align-items: center; gap: 8px; }
  .sr-eyebrow::before { content: ''; width: 8px; height: 8px; border-radius: 50%; background: var(--lime);
                        box-shadow: 0 0 0 3px rgba(197,224,99,.28); }
  .sr-title { font-family: var(--head); font-size: 28px; font-weight: 800; letter-spacing: -0.03em;
              line-height: 1.15; color: var(--ink); }
  .sr-title .soft { color: var(--soft); }
  /* thẻ và khung */
  .q-card { border-radius: 12px; }
  .q-card.q-card--bordered, .q-card--flat.q-card--bordered { border-color: var(--line); }
  .sr-card { background: #fff; border: 1px solid var(--line); border-radius: 14px; }
  /* Thẻ nằm trong thẻ (ô KPI, thẻ mục tiêu, ô danh sách): bỏ viền, chỉ giữ nền nhạt để bớt đường kẻ lồng nhau. */
  .sr-card .sr-card { border-color: transparent; background: #F6F6F1; }
  .sr-card .sr-kpi.clickable:hover { background: #F1F1EA; }
  .sr-section-title { font-family: var(--head); font-size: 16px; font-weight: 700; letter-spacing: -0.015em; }
  .sr-link { color: var(--ink) !important; font-size: 13.5px; font-weight: 600; text-decoration: none;
             border-bottom: 1.5px solid var(--ink); padding-bottom: 1px; white-space: nowrap; }
  .sr-link:hover { color: var(--green) !important; border-color: var(--green); }
  .sr-kpi { transition: box-shadow .15s, transform .15s; flex: 1 1 0; min-width: 160px; align-self: stretch;
            display: flex; flex-direction: column; border-radius: 12px !important; }
  .sr-kpi-hint { margin-top: auto; padding-top: 6px; line-height: 1.3; }
  /* Khối so sánh dưới số chính (như GSC): kỳ so sánh · số của kỳ đó · chênh lệch tô màu */
  .sr-cost-box { border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; }
  .sr-cost-box.green { background: #EEF6EF; color: #1E5A2A; }
  .sr-cost-box.amber { background: #FBF1DE; color: #8F5F14; }
  .sr-cost-box.red { background: #FCEBE3; color: #9A3412; }
  .sr-info { color: #A3A194; cursor: help; flex: none; border-radius: 50%; }
  .sr-info:hover, .sr-info:focus { color: #4A4A40; outline: none; }
  .sr-info-tip { font-size: 12.5px; line-height: 1.45; padding: 8px 10px; background: #2B2E29; }
  .sr-info-head { font-size: 10.5px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
    color: #C9D88A; }
  .sr-cmp { display: flex; flex-wrap: wrap; align-items: baseline; column-gap: 8px; margin-top: 8px; padding-top: 6px;
            border-top: 1px dashed #DEDCD2; white-space: nowrap; min-width: 0; }
  .sr-cmp .lab { flex-basis: 100%; font-size: 11.5px; color: var(--muted); overflow: hidden; text-overflow: ellipsis;
                 line-height: 1.3; }
  .sr-cmp .val { font-size: 15px; font-weight: 650; color: #4A4A40; font-variant-numeric: tabular-nums; }
  .sr-cmp .diff { font-size: 12.5px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .sr-cmp .diff.up { color: #1E7C31; } .sr-cmp .diff.down { color: #C2410C; } .sr-cmp .diff.flat { color: #6B6A5E; }
  .sr-kpi-row { display: flex; flex-wrap: wrap; gap: 12px; width: 100%; align-items: stretch; }
  .sr-kpi.clickable:hover { box-shadow: 0 6px 18px rgba(31,34,30,.08); transform: translateY(-1px); cursor: pointer; }
  .sr-kpi-value { font-family: var(--head); font-size: 22px; font-weight: 700; letter-spacing: -0.025em;
                  line-height: 1.15; }
  .sr-icon-bubble { width: 32px; height: 32px; border-radius: 10px; display: flex; align-items: center;
                    justify-content: center; }
  .sr-delta { font-size: 12px; font-weight: 650; padding: 1px 7px; border-radius: 999px; white-space: nowrap; }
  .sr-delta.up { color: #1E7C31; background: #E7F3EA; }
  .sr-delta.down { color: #C2410C; background: #FCEDE6; }
  .sr-delta.flat { color: #6B6A5E; background: #EFEFE8; }
  /* nút viên thuốc: chính = đen đặc, phụ = viền */
  .q-btn { border-radius: 999px !important; font-weight: 650; letter-spacing: -0.01em; }
  .q-btn.bg-primary { background: var(--ink) !important; color: #F6F7F1 !important; }
  .q-btn--outline { color: var(--ink) !important; background: #fff !important; }
  .q-btn--outline:before { border-color: #D6D5CB !important; }
  .q-btn-group { border-radius: 999px !important; }
  .q-btn-dropdown--split .q-btn-dropdown__arrow-container { border-left: 1px solid rgba(255,255,255,.25) !important; }
  .q-field--outlined .q-field__control { border-radius: 10px; background: #fff; }
  .q-field--outlined .q-field__control:before { border-color: var(--line); }
  .q-menu { border-radius: 12px !important; box-shadow: 0 12px 32px rgba(31,34,30,.12) !important; }
  .q-dialog .q-card { border-radius: 14px !important; }
  /* bảng */
  .q-table__container { border-radius: 12px; border-color: var(--line) !important; }
  .q-table thead th { font-family: var(--mono); font-size: 11px; font-weight: 600; text-transform: uppercase;
                      letter-spacing: .07em; color: var(--muted); background: #FAFAF6; }
  .q-table tbody td { font-size: 13px; font-variant-numeric: tabular-nums; }
  .q-table tbody tr:nth-child(even) td { background: #FAFAF6; }
  .q-table tbody tr:hover td { background: #F0F2E8; }
  .q-table th.sortable .q-table__sort-icon { font-size: 14px; }
  .sr-busy { display: contents; }
  /* danh sách URL (màn Hiệu suất URL) */
  .sr-url-item { width: 100%; flex-shrink: 0; padding: 7px 10px; border-radius: 8px; cursor: pointer;
                 display: flex; flex-direction: column; gap: 1px; border: 1px solid transparent; }
  .sr-url-item:hover { background: #F3F3EC; }
  .sr-url-item.selected { background: #E7F3EA; }
  .sr-url-item:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
  .sr-url-line { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; min-width: 0; }
  .sr-url-path { font-size: 13px; font-weight: 550; color: var(--ink); overflow: hidden; text-overflow: ellipsis;
                 white-space: nowrap; min-width: 0; }
  .sr-url-item.selected .sr-url-path { color: var(--green); }
  .sr-url-clicks { font-size: 13px; font-weight: 650; }
  .sr-url-meta { display: flex; align-items: center; gap: 5px; min-width: 0; font-size: 11.5px; color: var(--muted); }
  .sr-url-delta { font-size: 11.5px; font-weight: 600; white-space: nowrap; }
  /* bento: một hộp bo tròn, các ô cùng bán kính, nền đặc, một khoảng cách chung */
  .sr-bento { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); grid-auto-rows: minmax(92px, auto);
              gap: 6px; padding: 6px; background: #E9E9E1; border-radius: 16px; }
  .sr-bento-tile { background: #fff; border-radius: 11px; padding: 12px 14px; display: flex; flex-direction: column;
                   gap: 4px; min-width: 0; }
  .sr-bento-tile.big { grid-column: span 2; grid-row: span 2; gap: 6px; }
  .sr-bento-tile.wide { grid-column: span 2; }
  .sr-bento-eyebrow { font-family: var(--mono); font-size: 11px; font-weight: 600; letter-spacing: .08em;
                      text-transform: uppercase; }
  .sr-bento-hero { font-family: var(--head); font-size: 32px; font-weight: 800; letter-spacing: -0.035em;
                   line-height: 1.05; }
  .sr-seg { background: #EEECE4; border-radius: 999px; padding: 3px; gap: 2px; box-shadow: none; }
  .sr-seg .q-btn { border-radius: 999px !important; padding: 2px 12px; min-height: 26px; font-size: 12.5px; }
  .sr-seg .q-btn.bg-white { box-shadow: 0 1px 2px rgba(31,34,30,.12); font-weight: 600; }
  .sr-access-row { padding: 8px 4px; border-bottom: 1px solid var(--line); }
  .sr-access-row:last-child { border-bottom: 0; }
  /* Màn rộng: nội dung không giãn quá 1.440px, căn giữa */
  .nicegui-content { max-width: 1440px; margin-left: auto; margin-right: auto; width: 100%; }
  /* Hai khối cạnh nhau khi đủ chỗ (SEO | GEO), tự xuống dòng trên màn nhỏ */
  .sr-two { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 520px), 1fr)); gap: 16px;
            align-items: stretch; }
  .sr-two > .sr-card { height: 100%; }
  /* Ô chỉ số bật/tắt đường (kiểu GSC): gọn, nền trắng; ô đang bật có vạch màu trên + nền màu rất nhạt */
  .sr-trend-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
  .sr-trend-tile { position: relative; border-radius: 10px; padding: 10px 12px 9px; border: 1px solid var(--line);
                   background: #fff; cursor: pointer; transition: background .15s, border-color .15s;
                   user-select: none; overflow: hidden; }
  .sr-trend-tile:hover { border-color: var(--c); }
  .sr-trend-tile:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .sr-trend-tile.active { border-color: color-mix(in srgb, var(--c) 45%, white);
                          background: color-mix(in srgb, var(--c) 7%, white); }
  .sr-trend-tile.static { cursor: default; background: #F8F8F4; }
  .sr-trend-check { color: var(--c); }
  .sr-trend-tile:not(.active) .sr-trend-check { color: #B8B6A8; }
  .sr-trend-label { font-size: 12.5px; color: var(--muted); white-space: nowrap; overflow: hidden;
                    text-overflow: ellipsis; }
  .sr-trend-value { font-family: var(--head); font-size: 21px; font-weight: 700; letter-spacing: -0.02em;
                    color: var(--ink); }
  .sr-trend-hint { font-size: 11px; color: var(--muted); margin-top: 1px; white-space: nowrap; overflow: hidden;
                   text-overflow: ellipsis; }
  .sr-todo { display: flex; align-items: center; gap: 10px; padding: 9px 10px; border-radius: 10px;
             color: var(--ink) !important; }
  .sr-todo:hover { background: #F3F3EC; }
  .sr-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
  .sr-bento-tile .sr-delta, .sr-metric .sr-delta { align-self: flex-start; }
  @media (max-width: 1100px) { .sr-bento { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  #sr-top { position: fixed; right: 24px; bottom: calc(24px + env(safe-area-inset-bottom)); z-index: 2000;
            width: 44px; height: 44px; border-radius: 50%; border: 1px solid var(--line); background: #fff;
            color: var(--ink); box-shadow: 0 6px 18px rgba(31,34,30,.14); cursor: pointer; display: flex;
            align-items: center; justify-content: center; opacity: 0; transform: translateY(8px);
            pointer-events: none; transition: opacity .2s, transform .2s; }
  #sr-top.show { opacity: 1; transform: none; pointer-events: auto; }
  #sr-top:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .q-notifications__list--bottom { padding-bottom: 76px; }  /* chừa chỗ nút về đầu trang */
  .q-notification { border-radius: 14px !important; }
  .q-table--dense .q-table th, .q-table--dense .q-table td { padding: 7px 10px; }
  .sr-bar { position: relative; display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
  .sr-bar-fill { height: 6px; border-radius: 3px; background: #CFE6D4; }
  /* tab dạng viên thuốc như nhãn chủ đề */
  .sr-tabs .q-tab { border: 1px solid var(--line); border-radius: 8px; min-height: 32px; margin-right: 6px;
                    padding: 0 14px; background: #fff; color: var(--ink); }
  .sr-tabs .q-tab--active { background: var(--ink); border-color: var(--ink); color: #F6F7F1; }
  .sr-tabs .q-tab__label { font-weight: 600; }
  .sr-tabs .q-tab__indicator { display: none; }
  /* menu trái */
  .sr-nav a { display: flex; align-items: center; gap: 10px; padding: 7px 12px; border-radius: 8px;
              color: #3A3B35; text-decoration: none; font-size: 14px; }
  .sr-nav a:hover { background: #E8E8E0; }
  .sr-nav a.active { background: #fff; color: var(--ink); font-weight: 650; box-shadow: 0 1px 2px rgba(31,34,30,.08); }
  .sr-nav a.active .q-icon { color: var(--green); }
  .sr-nav-group { font-family: var(--mono); font-size: 11px; font-weight: 600; text-transform: uppercase;
                  letter-spacing: .09em; color: #6B6A5E; padding: 16px 12px 5px; }
  .sr-summary { display: flex; flex-wrap: wrap; padding: 0; }
  .sr-summary-half { flex: 1 1 460px; min-width: 0; padding: 18px 20px; display: flex; flex-direction: column;
                     gap: 12px; }
  .sr-summary-half.geo { border-left: 1px solid var(--line); background: #FBFAFD; border-radius: 0 14px 14px 0; }
  .sr-metric-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .sr-metric { padding: 2px 14px; border-left: 1px solid var(--line); display: flex; flex-direction: column;
               gap: 3px; align-items: flex-start; min-width: 0; }
  .sr-metric:first-child { border-left: none; padding-left: 0; }
  .sr-metric-value { font-family: var(--head); font-size: 20px; font-weight: 700; letter-spacing: -0.025em;
                     line-height: 1.2; }
  .q-header.sr-top .q-field--dense .q-field__control { min-height: 34px; height: 34px; }
  .q-header.sr-top .q-field--dense .q-field__marginal { height: 34px; }
  .q-header.sr-top .q-field--dense .q-field__native { min-height: 34px; padding: 0; }
  /* Lớp riêng thay cho q-mini-drawer-*: Quasar ẩn các lớp đó khi menu ở chế độ điện thoại (mất chữ menu) */
  .q-drawer--mini .sr-mini-hide { display: none !important; }
  .q-drawer:not(.q-drawer--mini) .sr-mini-only { display: none !important; }
  /* Ô thứ hạng Top 3 / 5 / 10: số lớn, màu số theo mức đạt cam kết */
  .sr-rank-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 12px; }
  .sr-rank-tile { background: #F6F6F1; border-radius: 12px; padding: 14px 18px 16px; }
  .sr-rank-name { font-size: 14px; font-weight: 650; color: var(--ink); }
  .sr-rank-num { font-family: var(--head); font-size: 44px; font-weight: 800; letter-spacing: -0.03em;
                 line-height: 1.1; margin: 6px 0 4px; color: var(--ink); }
  .sr-rank-num span { font-size: 20px; font-weight: 600; color: var(--muted); letter-spacing: 0; margin-left: 2px; }
  .sr-rank-tile.good .sr-rank-num { color: var(--green); }
  .sr-rank-tile.warn .sr-rank-num { color: #8F5F14; }
  .sr-rank-tile.bad .sr-rank-num { color: #C2410C; }
  .sr-rank-sub { font-size: 13.5px; color: var(--muted); }
  .sr-rank-goal { font-size: 13.5px; font-weight: 650; margin-top: 6px; color: var(--ink); }
  .sr-rank-tile.good .sr-rank-goal { color: var(--green); }
  .sr-rank-tile.warn .sr-rank-goal { color: #8F5F14; }
  .sr-rank-tile.bad .sr-rank-goal { color: #C2410C; }
  .sr-rank-goal.none { font-weight: 400; color: var(--muted); }
  /* Avatar có chấm trạng thái (kiểu PresenceBadge / Badge dot overlap circular): chấm tròn đè mép dưới phải của avatar,
     viền 2px cùng màu nền để tách khỏi avatar. Trạng thái đang online có vòng lan (ping) phía sau, lõi đứng yên. */
  .sr-presence { position: relative; display: inline-flex; flex-shrink: 0; }
  .sr-presence-avatar { border-radius: 50%; display: flex; align-items: center; justify-content: center;
                        font-weight: 650; font-family: var(--head); line-height: 1; }
  .sr-presence-dot { position: absolute; right: 0; bottom: 0; transform: translate(18%, 18%); border-radius: 50%;
                     border: 2px solid var(--ring, #fff); background: var(--ring, #fff); box-sizing: content-box; }
  .sr-presence-dot > .core { position: relative; display: block; width: 100%; height: 100%; border-radius: 50%;
                             background: var(--dot); z-index: 1; }
  .sr-presence-dot > .halo { position: absolute; inset: 0; border-radius: 50%; background: var(--dot); opacity: .55;
                             z-index: 0; }
  @media (prefers-reduced-motion: no-preference) {
    .sr-presence-dot > .halo { animation: sr-ping 1.8s cubic-bezier(0, 0, .2, 1) infinite; }
  }
  @media (prefers-reduced-motion: reduce) { .sr-presence-dot > .halo { display: none; } }
  @keyframes sr-ping { 75%, 100% { transform: scale(2.4); opacity: 0; } }
  /* Nhóm avatar (kiểu MUI AvatarGroup): avatar tròn chồng lên nhau bằng khoảng âm, viền màu nền quanh mỗi avatar,
     avatar đứng trước nằm trên (z-index giảm dần), ô cuối "+N" khi còn người bị ẩn. */
  .sr-avatar-group { display: inline-flex; align-items: center; padding: 2px; cursor: pointer;
                     border-radius: 999px; }
  .sr-avatar-group:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .sr-ag-item { position: relative; margin-left: -10px; border-radius: 50%; border: 2px solid var(--ring, #fff);
                box-sizing: content-box; display: flex; align-items: center; justify-content: center;
                font-weight: 650; font-family: var(--head); line-height: 1; overflow: visible; }
  .sr-ag-item img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; display: block; }
  .sr-ag-item.more { background: #E4E2D8; color: var(--ink); font-family: var(--body, inherit); letter-spacing: -.02em; }
  .sr-ag-dot { position: absolute; right: -2px; bottom: -2px; width: 8px; height: 8px; border-radius: 50%;
               border: 2px solid var(--ring, #fff); box-sizing: content-box; }
  .sr-avatar-group:hover .sr-ag-item { transform: translateY(-1px); transition: transform .15s; }
  /* Tổng quan: 6 ô nhịp số liệu (3 cột) và 3 khối Thứ hạng · Index · OKR */
  .sr-dash-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
  @media (max-width: 1100px) { .sr-dash-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 600px) { .sr-dash-grid { grid-template-columns: 1fr; } }
  .sr-dash-grid > .sr-kpi { min-width: 0; }
  .sr-dash-three { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: 16px;
                   align-items: stretch; }
  .sr-dash-three > .sr-card { height: 100%; }
  .sr-mini-stats { display: flex; gap: 24px; flex-wrap: wrap; }
  .sr-mini-num { font-family: var(--head); font-size: 26px; font-weight: 750; letter-spacing: -0.02em; line-height: 1.15; }
  .sr-mini-num span { font-size: 14px; font-weight: 600; color: var(--muted); letter-spacing: 0; }
  /* Dòng website ở màn Ngân sách check rank */
  .sr-budget-row { display: grid; align-items: center; column-gap: 16px;
                   grid-template-columns: minmax(200px, 1.1fr) minmax(180px, 1.4fr) 160px 150px 76px; }
  /* Dòng dự án: logo | thông tin | người | 3 ô nút icon cố định (thẳng hàng giữa các dòng) */
  .sr-proj-row { display: grid; align-items: center; column-gap: 12px;
                 grid-template-columns: 36px minmax(0, 1fr) 128px repeat(3, 36px); }
  .sr-proj-row .sr-link { justify-self: end; }
  .sr-icon-slot { width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; }
  @media (max-width: 700px) { .sr-proj-row { grid-template-columns: 36px minmax(0, 1fr) repeat(3, 36px); }
                              .sr-proj-row .sr-link { grid-area: 2 / 2; justify-self: start; } }
  @media (max-width: 900px) {
    /* Điện thoại: hàng 1 website | trạng thái, hàng 2 thanh ngân sách, hàng 3 ô ngân sách | công tắc */
    .sr-budget-row { grid-template-columns: minmax(0, 1fr) auto; row-gap: 10px; }
    .sr-budget-row > :nth-child(1) { grid-area: 1 / 1; } .sr-budget-row > :nth-child(3) { grid-area: 1 / 2; }
    .sr-budget-row > :nth-child(2) { grid-area: 2 / 1 / 3 / 3; }
    .sr-budget-row > :nth-child(4) { grid-area: 3 / 1; } .sr-budget-row > :nth-child(5) { grid-area: 3 / 2; } }
  /* Hàng tài khoản ở cuối menu trái: bấm mở menu tài khoản */
  .sr-account { padding: 6px 8px; border-radius: 10px; cursor: pointer; transition: background .15s; }
  .sr-account:hover { background: #E8E8E0; }
  .sr-account:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
  .q-drawer--mini .sr-account { justify-content: center; padding: 6px 0; }
  .sr-account-menu { border-radius: 14px !important; border: 1px solid var(--line);
                     box-shadow: 0 12px 32px rgba(31,34,30,.14) !important; }
  .sr-account-menu { overflow-x: hidden !important; }
  .sr-account-menu .q-item { min-height: 40px; padding: 6px 10px; margin: 1px 6px; border-radius: 10px; }
  .sr-account-menu .q-item .q-focus-helper { display: none; }  /* lớp phủ xám mặc định của Quasar: thay bằng nền nhẹ */
  .sr-account-menu .q-item:hover, .sr-account-menu .q-item:focus-visible { background: #F1F0EA; }
  .sr-account-menu .q-item { min-height: 34px; padding: 5px 14px; }
  .sr-account-menu .q-separator { margin: 4px 0; }
  .sr-account-menu .sr-acct-head { padding: 12px 14px 8px; }
  .sr-account-menu .sr-acct-group { padding: 6px 14px 2px; }
  .sr-account-menu .q-item.sr-current { background: #EEF6F0; }
  /* Biểu tượng dự án (logo website) */
  .sr-proj-icon { flex-shrink: 0; display: flex; align-items: center; justify-content: center; overflow: hidden;
                  background: #fff; border: 1px solid var(--line); color: var(--green); font-weight: 700;
                  font-family: var(--head); }
  .sr-proj-icon img { width: 100%; height: 100%; object-fit: contain; padding: 3px; display: block; }
  .sr-proj-switch { border: 1px solid var(--line); border-radius: 10px; background: #fff; padding: 4px 8px 4px 5px;
                    cursor: pointer; max-width: 280px; }
  .sr-proj-switch:hover { border-color: #C9C7BC; }
  /* Câu kết luận đầu trang */
  .sr-verdict { display: flex; align-items: flex-start; gap: 10px; background: #fff; border: 1px solid var(--line);
                border-radius: 12px; padding: 12px 16px; font-size: 15px;
                line-height: 1.5; color: var(--ink); }
  .sr-verdict .q-icon { margin-top: 2px; flex-shrink: 0; }
  /* Nhãn KPI khi dự án chưa bắt đầu */
  .sr-kpi-chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 999px;
                 border: 1px solid var(--line); background: #fff; color: var(--ink) !important; font-size: 13px;
                 font-weight: 600; text-decoration: none; white-space: nowrap; }
  .sr-kpi-chip:hover { border-color: var(--green); color: var(--green) !important; }
  .sr-kpi-chip .q-icon { color: var(--green); }
  /* Điện thoại: tiêu đề nhỏ lại, nút đầu trang chỉ còn icon, ô chỉ số hai cột, số và % được xuống dòng */
  @media (max-width: 600px) {
    .sr-title { font-size: 22px; }
    .sr-head-btn .q-btn__content > span:not(.q-icon), .sr-head-btn .block { display: none; }
    .sr-head-btn .q-icon { margin: 0 !important; }
    .sr-page-head, .sr-sec-head { flex-wrap: wrap !important; }
    .sr-sec-head > .q-space { display: none; }
    .sr-sec-head > .nicegui-column { flex: 1 1 210px; min-width: 0; }
    .sr-sec-head > .sr-link { margin-left: 46px; }
    .sr-trend-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .sr-trend-value { font-size: 19px; }
    .sr-verdict { font-size: 14px; }
  }
  /* menu thu gọn: mỗi mục là một ô vuông 40px căn giữa; nhóm ngăn bằng vạch mảnh thay cho chữ */
  .sr-nav { align-items: stretch !important; }
  .sr-nav a { width: 100%; }
  .q-drawer--mini .sr-nav { align-items: center !important; }
  .q-drawer--mini .sr-nav a { width: 40px; height: 40px; padding: 0; margin: 2px 0; justify-content: center;
                              border-radius: 10px; gap: 0; }
  .q-drawer--mini .sr-nav-group { font-size: 0; padding: 0; width: 24px; height: 1px; margin: 10px 0;
                                  background: #D9D8CE; }
  .q-header.sr-top { background: rgba(244,244,239,.9); backdrop-filter: blur(10px); color: var(--ink);
                     border-bottom: 1px solid var(--line); }
</style>
"""

TONES = {"green": ("#E7F3EA", GREEN), "lime": ("#F2F7DC", "#5E7414"), "blue": ("#E8EFFD", BLUE),
         "amber": ("#FBF1DE", AMBER_TEXT), "red": ("#FCEDE6", RED), "grey": ("#F1F0EA", MUTED),
         "purple": ("#F1EAFB", "#7C3AED")}


EYEBROWS = {"space_dashboard": "Tổng quan", "summarize": "Báo cáo", "travel_explore": "SEO", "leaderboard": "SEO",
            "link": "SEO", "auto_awesome": "AI & GEO", "verified": "AI & GEO", "folder_open": "SEO"}


def page_header(ui, icon: str, title: str, subtitle: str = "", tone: str = "green", eyebrow: str | None = None):
    """Tiêu đề trang: nhãn mono nhỏ ở trên, tiêu đề lớn hai tông (phần số/ngày màu nhạt). Trả về row bên phải để đặt
    nút/bộ lọc."""
    m = re.search(r"\d", title)
    strong, soft = (title[:m.start()], title[m.start():]) if m and m.start() > 0 else (title, "")
    # Không còn nhãn mono "SEO Report — …" phía trên: nó lặp lại đúng tiêu đề và mục đang chọn trong menu.
    with ui.row().classes("w-full items-end gap-3 no-wrap q-mb-md q-mt-xs sr-page-head"):
        with ui.column().classes("gap-1").style("min-width: 0"):
            ui.html(f'<h1 class="sr-title" style="margin:0">{escape(strong)}<span class="soft">{escape(soft)}</span>'
                    '</h1>')
            if subtitle:
                ui.label(subtitle).classes("text-sm muted q-mt-xs")
        ui.space()
        right = ui.row().classes("items-center gap-2")
    return right


def compare_line(ui, parts: dict, good: bool | None) -> None:
    """Khối so sánh dưới số chính: kỳ so sánh và số của kỳ đó ("Tuần 28/09 · 5.535"). Mức chênh không đặt ở đây (dễ
    đọc nhầm là kỳ trước tăng / giảm) mà ở nhãn cạnh số chính, xem change_text."""
    with ui.element("div").classes("sr-cmp") as box:
        ui.label(parts["label"]).classes("lab")
        ui.label(parts["value"]).classes("val")
    box.props["title"] = f"{parts['label']}: {parts['value']}" + (f" ({parts['diff']})" if parts.get("diff") else "")


def info_icon(ui, label: str, info: tuple | None = None):
    """Nút (i) cạnh tên chỉ số: rê chuột (điện thoại: chạm giữ) hiện chỉ số là gì, cho biết điều gì, đo thế nào.
    info mặc định tra theo tên chỉ số trong metric_help; không có giải thích thì không vẽ gì."""
    from .metric_help import help_for
    info = info or help_for(label)
    if not info:
        return None
    icon = ui.icon("info_outline", size="15px").classes("sr-info")
    icon.props["tabindex"] = "0"
    icon.props["aria-label"] = f"Giải thích: {label}"
    icon.on("click.stop", lambda: None)  # trong ô bấm được (bật / tắt đường): bấm (i) không bật / tắt
    with icon, ui.tooltip().classes("sr-info-tip").props("max-width=320px anchor='bottom middle' "
                                                         "self='top middle'"):
        for head, text in zip(("Là gì", "Cho biết", "Đo thế nào"), info):
            with ui.element("div").classes("q-mb-xs"):
                ui.label(head).classes("sr-info-head")
                ui.label(text)
    return icon


def change_text(delta: str, prev: dict | None) -> str:
    """Nhãn cạnh số chính: chênh tuyệt đối kèm % ("+177 (+3,3%)"); không có số kỳ trước thì giữ nguyên delta."""
    diff = (prev or {}).get("diff")
    if not diff:
        return "" if (prev and (delta or "").startswith("kỳ trước")) else delta
    return f"{diff} ({delta})" if delta and not delta.startswith("kỳ trước") else diff


def delta_badge(ui, text: str, good: bool | None):
    if not text:
        return
    cls = "flat" if good is None else ("up" if good else "down")
    arrow = "" if good is None else ("▲ " if text.lstrip().startswith("+") else "▼ " if text.lstrip().startswith(
        ("-", "−")) else "")
    ui.label(arrow + text).classes(f"sr-delta {cls}")


def sparkline(ui, values: list, color: str = GREEN, height: int = 40, labels: list | None = None,
              fmt: str = "num", compare: list | None = None, compare_labels: list | None = None, **_):
    """Đường nhỏ theo kỳ (cũ → mới) có nền mờ, chấm đậm ở kỳ đang xem, rê chuột hiện số. Trục từ 0 để độ dốc đúng tỷ
    lệ: không phóng đại -0,6% thành một cú tụt; muốn xem chênh lệch chính xác thì xem nhãn % cạnh số lớn.
    compare: số của kỳ so sánh, cùng số điểm, vẽ nét đứt chồng lên cùng biểu đồ (như chế độ so sánh của GSC);
    compare_labels: ngày của từng điểm kỳ so sánh, hiện khi rê chuột."""
    import json
    vals = list(values)
    if not any(v for v in vals if v is not None):
        ui.element("div").style(f"height:{height}px")  # giữ chỗ để các thẻ cùng hàng thẳng nhau
        return
    last = max(i for i, v in enumerate(vals) if v is not None)
    data = [{"value": v, "symbolSize": 6 if i == last else 0} for i, v in enumerate(vals)]
    xs = labels or [str(i) for i in range(len(vals))]
    series = [{"type": "line", "data": data, "name": "Kỳ này", "smooth": 0.3, "symbol": "circle", "z": 3,
               "lineStyle": {"color": color, "width": 2}, "itemStyle": {"color": color},
               "areaStyle": {"color": color, "opacity": 0.12}}]
    tooltip = {"trigger": "axis", "confine": True, "axisPointer": {"type": "line", "lineStyle": {"color": "#D9D8CF"}},
               "textStyle": {"fontSize": 11}, "padding": [4, 8], ":valueFormatter": _value_js(fmt)}
    if compare and any(v is not None for v in compare):
        series.append({"type": "line", "data": list(compare)[:len(vals)], "name": "Kỳ so sánh", "smooth": 0.3,
                       "symbol": "none", "z": 2, "lineStyle": {"color": "#8C8A7E", "width": 1.5, "type": [4, 3],
                                                                "opacity": 0.9}, "itemStyle": {"color": "#8C8A7E"}})
        cl = list(compare_labels or [])
        fmt_js = _value_js(fmt)
        tooltip[":formatter"] = (  # mỗi dòng ghi ngày của chính kỳ đó: "24/10 Kỳ này 700" / "26/09 Kỳ so sánh 650"
            "ps => ps.map(p => '<span style=\"display:inline-block;width:16px;height:0;vertical-align:middle;"
            "margin-right:6px;border-top:' + (p.seriesIndex === 0 ? '3px solid ' : '2px dashed ') + p.color + "
            "'\"></span>' + (p.seriesIndex === 0 ? " + json.dumps(xs) + "[p.dataIndex] + ' · Kỳ này' : "
            "(" + json.dumps(cl) + "[p.dataIndex] || '') + ' · Kỳ so sánh') + ': <b>' + (" + fmt_js + ")(p.value) "
            "+ '</b>').join('<br/>')")
    ui.echart({"animation": False, "grid": {"left": 3, "right": 5, "top": 5, "bottom": 2}, "tooltip": tooltip,
               "xAxis": {"type": "category", "show": False, "boundaryGap": False, "data": xs},
               "yAxis": {"type": "value", "show": False, "min": 0},
               "series": series}).style(f"height:{height}px; width:100%")


def _value_js(fmt: str) -> str:
    return ("v => v == null ? 'chưa có' : (v * 100).toLocaleString('vi-VN', {maximumFractionDigits: 2}) + '%'"
            if fmt == "pct" else "v => v == null ? 'chưa có' : v.toLocaleString('vi-VN', {maximumFractionDigits: 1})")


def trend_chart(ui, metrics: list[dict], labels: list[str], height: int = 230,
                compare_labels: list[str] | None = None) -> None:
    """Kiểu biểu đồ Hiệu suất của Google Search Console: mỗi chỉ số là một ô bấm để bật/tắt đường của nó trên biểu
    đồ chung bên dưới. Mỗi đường có trục riêng (ẩn) nên chỉ số nhỏ (phiên ~5.000) và lớn (impression ~180.000) cùng
    hiện rõ; rê chuột hiện số mọi đường của kỳ đó.

    metrics: [{"key", "label", "value", "delta", "good", "prev": dòng kỳ trước, "data": [số theo kỳ], "color", "icon",
    "hint", "fmt": "num" |
    "pct", "kind": "line" | "bar", "axis": nhóm trục, "zero": trục từ 0, "source": nguồn (tooltip), "on": bật sẵn hay
    không, "compare": [số kỳ so sánh, cùng vị trí với data]}]. Chỉ số không có dữ liệu xu hướng thì ô không bấm được.
    Trục số của hai chỉ số bật đầu tiên hiện ở trái / phải, cùng màu đường.
    compare: vẽ nét đứt cùng màu trên cùng trục (như chế độ so sánh của GSC); compare_labels: ngày của từng điểm kỳ
    so sánh, hiện khi rê chuột. Có compare_labels (biểu đồ theo ngày) thì các cột đậm như nhau, không làm nổi cột
    cuối."""
    import json
    on = {m["key"] for m in metrics if m.get("on") and _has(m)}
    if not on:
        on = {m["key"] for m in metrics[:1] if _has(m)}

    @ui.refreshable
    def body():
        with ui.element("div").classes("sr-trend-tiles w-full"):
            for m in metrics:
                active = m["key"] in on
                usable = _has(m)
                tile = ui.element("div").classes("sr-trend-tile" + (" active" if active else "")
                                                 + ("" if usable else " static"))
                tile.style(f"--c:{m['color']}")
                if usable:
                    tile.props(f'role=button tabindex=0 aria-pressed={"true" if active else "false"}')
                    tile.on("click", lambda _, k=m["key"]: toggle(k))
                    tile.on("keydown.enter", lambda _, k=m["key"]: toggle(k))
                with tile:
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        icon = ("check_box" if active else "check_box_outline_blank") if usable else \
                            (m.get("icon") or "insights")
                        ui.icon(icon, size="18px").classes("sr-trend-check")
                        ui.label(m["label"]).classes("sr-trend-label")
                        info_icon(ui, m["label"], m.get("info"))
                    # Số chính rồi nhãn chênh ở dòng riêng: ô nào cũng cùng bố cục (ô hẹp, số lớn không bị lệch hàng)
                    with ui.column().classes("items-start gap-1 q-mt-xs"):
                        ui.label(m["value"]).classes("sr-trend-value num")
                        text = change_text(m.get("delta") or "", m.get("prev"))
                        if text:
                            delta_badge(ui, text, m.get("good"))
                        else:
                            ui.label(" ").classes("sr-delta flat").style("visibility:hidden")  # giữ chỗ cho đều
                    if m.get("prev"):
                        compare_line(ui, m["prev"], m.get("good"))
                    hint = ui.label(m.get("hint") or " ").classes("sr-trend-hint")
                    full = " · ".join(x for x in (m.get("hint"), m.get("source")) if x)
                    if full:  # chữ phụ có thể bị cắt "…" và nguồn số liệu: rê chuột để đọc đủ
                        hint.props["title"] = full  # gán thẳng, không ghép vào chuỗi props
                        tile.props["aria-description"] = full
        shown = [m for m in metrics if m["key"] in on]
        if not shown:
            return
        fmts = {m["label"]: m.get("fmt", "num") for m in shown}
        has_bar = any(m.get("kind") == "bar" for m in shown)
        pairs = []  # (series, chỉ số của nó): đường kỳ so sánh dùng chung trục với đường chính
        cmp_names = {}  # tên đường kỳ so sánh → tên chỉ số, để tooltip ghi "Click · 03/07"
        for m in shown:
            base = {"name": m["label"], "itemStyle": {"color": m["color"]}}
            if m.get("kind") == "bar":
                last = len(m["data"]) - 1 if compare_labels is None else None
                pairs.append(({**base, "type": "bar", "barMaxWidth": 26, "z": 1,
                               "data": [{"value": v, "itemStyle": {"color": m["color"], "opacity": 0.45 if last
                                                                   is not None and j != last else 1,
                                                                   "borderRadius": [4, 4, 0, 0]}}
                                        for j, v in enumerate(m["data"])]}, m))
            else:
                pairs.append(({**base, "type": "line", "data": m["data"], "smooth": 0.25, "symbol": "circle",
                               "symbolSize": 6, "showSymbol": len(labels) <= 12, "connectNulls": False, "z": 3,
                               "lineStyle": {"width": 2.5, "color": m["color"]},
                               "areaStyle": {"color": m["color"], "opacity": 0.05 if len(shown) > 1 else 0.1}}, m))
            cmp = m.get("compare")
            if cmp and any(v is not None for v in cmp):
                name = m["label"] + " (kỳ so sánh)"
                cmp_names[name] = m["label"]
                fmts[name] = m.get("fmt", "num")
                pairs.append(({"name": name, "type": "line", "data": (list(cmp) + [None] * len(labels))[:len(labels)],
                               "smooth": 0.25, "symbol": "none", "connectNulls": False, "z": 2,
                               "itemStyle": {"color": m["color"]},
                               "lineStyle": {"width": 1.5, "type": "dashed", "color": m["color"], "opacity": 0.75}},
                              m))
        pct_js = "v => (v * 100).toLocaleString('vi-VN', {maximumFractionDigits: 1}) + '%'"
        num_js = ("v => Math.abs(v) >= 1000 ? (v / 1000).toLocaleString('vi-VN', {maximumFractionDigits: 1}) + 'k' "
                  ": v.toLocaleString('vi-VN')")
        # Trục số: đường thứ nhất bên trái, đường thứ hai bên phải (cùng màu đường), các đường khác trục ẩn
        # Chỉ số cùng "axis" dùng chung một trục (cùng đơn vị, cùng độ lớn: so độ cao được); trục chung màu trung tính
        groups = list(dict.fromkeys(m.get("axis", m["key"]) for m in shown))
        for s, m in pairs:
            s["yAxisIndex"] = groups.index(m.get("axis", m["key"]))
        series = [s for s, _ in pairs]
        y_axes = []
        for i, g in enumerate(groups):
            ms = [m for m in shown if m.get("axis", m["key"]) == g]
            m = ms[0]
            zero = m.get("kind") == "bar" or m.get("zero")
            y = {"type": "value", "show": i < 2, "position": "left" if i == 0 else "right",
                 "scale": not zero, "splitNumber": 4,
                 "splitLine": {"show": i == 0, "lineStyle": {"color": "#EEECE4"}},
                 "axisLine": {"show": False}, "axisTick": {"show": False},
                 "axisLabel": {"color": m["color"] if len(ms) == 1 else "#8C8A7E", "fontSize": 10.5,
                               ":formatter": pct_js if m.get("fmt") == "pct" else num_js}}
            if zero:
                y["min"] = 0
            y_axes.append(y)
        # Rê chuột: ký hiệu giống nét vẽ (nét liền = kỳ này, nét đứt = kỳ so sánh, ô vuông = cột) thay cho chấm tròn.
        # Biểu đồ theo ngày có kỳ so sánh: trục đánh số ngày 1, 2, 3… (như GSC), mỗi dòng ghi ngày của chính kỳ đó:
        # "Ngày 3 / Click · 21/10: 766 / Click · 14/10: 666"
        days = compare_labels is not None
        bars = [m["label"] for m in shown if m.get("kind") == "bar"]
        mark_js = ("(p, dashed) => " + json.dumps(bars, ensure_ascii=False) + ".includes(p.seriesName) && !dashed "
                   "? '<span style=\"display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;"
                   "background:' + p.color + '\"></span>' : '<span style=\"display:inline-block;width:16px;height:0;"
                   "vertical-align:middle;margin-right:6px;border-top:' + (dashed ? '2px dashed ' : '3px solid ') + "
                   "p.color + '\"></span>'")
        names = json.dumps(cmp_names, ensure_ascii=False)
        tip = ("ps => { const C = " + names + ", X = " + json.dumps(labels) + ", CL = "
               + json.dumps(compare_labels or []) + ", F = " + json.dumps(fmts, ensure_ascii=False)
               + ", mk = " + mark_js + "; "
               "return (" + ("'Ngày ' + (ps[0].dataIndex + 1)" if days else "ps[0].axisValue") + ") + ps.map(p => { "
               "const cmp = C[p.seriesName]; "
               "const name = cmp ? cmp + ' · ' + (CL[p.dataIndex] || 'kỳ so sánh') : p.seriesName"
               + (" + ' · ' + X[p.dataIndex]" if days else "") + "; "
               "const v = p.value == null ? 'chưa có' : (F[p.seriesName] === 'pct' ? (p.value * 100).toLocaleString("
               "'vi-VN', {maximumFractionDigits: 1}) + '%' : p.value.toLocaleString('vi-VN')); "
               "return '<br/>' + mk(p, !!cmp) + name + ': <b>' + v + '</b>'; }).join(''); }")
        ui.echart({"animation": False, "legend": {"show": False},
                   "grid": {"left": 44, "right": 48 if len(groups) > 1 else 14, "top": 14,
                            "bottom": 26},
                   "tooltip": {"trigger": "axis", "confine": True, ":formatter": tip,
                               "axisPointer": {"type": "shadow" if has_bar else "line",
                                               "shadowStyle": {"color": "rgba(31,34,30,0.04)"},
                                               "lineStyle": {"color": "#C9C7BC"}}},
                   "xAxis": {"type": "category", "data": [str(i + 1) for i in range(len(labels))] if days else labels,
                             "boundaryGap": has_bar, "axisTick": {"show": False},
                             "axisLine": {"lineStyle": {"color": "#E7E5DC"}},
                             "axisLabel": {"color": "#8C8A7E", "fontSize": 10.5}},
                   "yAxis": y_axes, "series": series}).classes("w-full q-mt-sm").style(f"height:{height}px")

    def toggle(key: str) -> None:
        if key in on:
            if len(on) > 1:  # luôn giữ ít nhất một đường
                on.discard(key)
        else:
            on.add(key)
        body.refresh()

    body()


def _has(m: dict) -> bool:
    return any(v is not None for v in (m.get("data") or []))


def kpi(ui, icon: str, label: str, value: str, delta: str = "", good: bool | None = None, hint: str = "",
        spark: list | None = None, tone: str = "green", href: str | None = None, spark_kind: str = "bar",
        spark_labels: list | None = None, spark_fmt: str = "num", prev: dict | None = None,
        spark_compare: list | None = None, spark_compare_labels: list | None = None, info: tuple | None = None):
    """Thẻ KPI: icon + nhãn, số lớn, nhãn thay đổi (xanh/đỏ), sparkline, dòng phụ. Có href thì bấm để đi sâu.
    Bố cục cố định để mọi thẻ cùng hàng cao bằng nhau: spark=[] giữ chỗ biểu đồ dù không có số, dòng phụ luôn có
    chỗ (để trống nếu không có)."""
    bg, fg = TONES[tone]
    href = href if href and link_allowed(href) else None
    card = ui.element("div").classes("sr-card sr-kpi q-pa-md" + (" clickable" if href else ""))
    if href:
        card.on("click", lambda: ui.navigate.to(href))
    with card:
        with ui.row().classes("items-center gap-2 no-wrap"):
            with ui.element("div").classes("sr-icon-bubble").style(f"background:{bg}"):
                ui.icon(icon, size="18px").style(f"color:{fg}")
            ui.label(label).classes("text-sm muted").style("line-height:1.2")
            info_icon(ui, label, info)  # (i): chỉ số là gì, đo thế nào
        with ui.row().classes("items-baseline gap-2 q-mt-sm").style("row-gap:2px"):  # hẹp thì nhãn chênh xuống dòng
            ui.label(value).classes("sr-kpi-value num")
            delta_badge(ui, change_text(delta, prev), good)
        if prev:  # số kỳ so sánh và mức chênh (như ô so sánh của GSC)
            compare_line(ui, prev, good)
        if spark is not None:
            with ui.element("div").classes("q-mt-xs w-full"):
                sparkline(ui, spark, fg, labels=spark_labels, fmt=spark_fmt, compare=spark_compare,
                          compare_labels=spark_compare_labels)
        ui.label(hint or " ").classes("text-xs muted sr-kpi-hint")
    return card


def link_allowed(href: str) -> bool:
    """Người đang xem có mở được trang này không (khách hàng chỉ mở các màn báo cáo): không thì ẩn link "Xem chi tiết"
    thay vì để bấm vào rồi bị đưa về trang chủ. Danh sách do web.open_page đặt cho từng lần mở trang."""
    try:
        from nicegui import app
        only = app.storage.client.get("only_links")
    except (RuntimeError, KeyError, AttributeError):  # ngoài trang web (test, xuất file)
        return True
    return not only or href.split("?")[0] in only


@contextmanager
def section(ui, title: str, icon: str | None = None, subtitle: str = "", href: str | None = None,
            link_text: str = "Xem chi tiết"):
    """Khung trắng có tiêu đề mục; nội dung đặt trong `with`."""
    with ui.element("div").classes("sr-card q-pa-md w-full"):
        with ui.row().classes("w-full items-center gap-2 no-wrap q-mb-sm sr-sec-head"):
            if icon:
                with ui.element("div").classes("sr-icon-bubble").style(f"background:{TONES['green'][0]}"):
                    ui.icon(icon, size="18px").style(f"color:{GREEN}")
            with ui.column().classes("gap-0"):
                ui.label(title).classes("sr-section-title").props('role=heading aria-level=2')
                if subtitle:
                    ui.label(subtitle).classes("text-xs muted")
            ui.space()
            if href and link_allowed(href):
                ui.link(link_text + " →", href).classes("sr-link")
        body = ui.column().classes("w-full gap-2")
        with body:
            yield body


def project_icon(ui, project: dict, size: int = 32):
    """Biểu tượng của dự án: logo website (ô vuông bo góc, nền trắng) hoặc chữ cái đầu tên khi chưa có logo."""
    from .projects import icon_of
    src = icon_of(project)
    box = ui.element("div").classes("sr-proj-icon").style(f"width:{size}px;height:{size}px;"
                                                           f"border-radius:{max(6, size // 4)}px")
    with box:
        if src:
            ui.html(f'<img src="{escape(src)}" alt="">').classes("w-full h-full")
        else:
            ui.label(project["name"][:1].upper()).style(f"font-size:{size // 2}px")
    return box


PRESENCE_COLOR = {"available": GREEN, "away": AMBER, "busy": RED, "offline": "#A3A195"}
# Màu avatar chữ cái: cố định theo email (cùng người luôn cùng màu)
AVATAR_PALETTE = [("#E7F3EA", GREEN), ("#E8EFFD", BLUE), ("#F1EAFB", "#7C3AED"), ("#FBF1DE", AMBER_TEXT),
                  ("#FCEDE6", RED), ("#E3F2F3", "#0E7C86")]


def avatar_color(key: str) -> tuple[str, str]:
    import hashlib
    return AVATAR_PALETTE[int(hashlib.md5(key.lower().encode()).hexdigest(), 16) % len(AVATAR_PALETTE)]


def avatar_group(ui, people: list[dict], max_shown: int = 4, size: int = 28, ring: str = "#fff", label: str = ""):
    """Nhóm avatar chồng nhau. people: [{"name", "text" (tooltip / tên đọc được), "status" (available / away /
    offline), "photo" (không bắt buộc)}] theo thứ tự hiển thị. Hiện tối đa max_shown ô; thừa thì ô cuối là "+N".
    Không có ảnh thì hiện chữ cái đầu. Trả về phần tử ngoài cùng (gắn menu / sự kiện bấm vào đó)."""
    shown = people if len(people) <= max_shown else people[:max_shown - 1]
    hidden = len(people) - len(shown)
    total = len(shown) + (1 if hidden else 0)
    box = ui.element("div").classes("sr-avatar-group").props("role=button tabindex=0 aria-haspopup=menu").style(
        f"--ring:{ring}")
    box.props["aria-label"] = label  # gán thẳng, không ghép vào chuỗi props
    with box:
        for i, p in enumerate(shown):
            bg, fg = avatar_color(p["name"])
            item = ui.element("div").classes("sr-ag-item").style(
                f"width:{size}px;height:{size}px;background:{bg};color:{fg};font-size:{round(size * .42)}px;"
                f"z-index:{total - i};" + ("margin-left:0;" if i == 0 else ""))
            with item:
                if p.get("photo"):
                    ui.html(f'<img src="{escape(p["photo"])}" alt="">').classes("w-full h-full")
                else:
                    ui.label(p["name"][:1].upper()).props("aria-hidden=true")
                if p.get("status") in ("available", "away"):
                    ui.element("span").classes("sr-ag-dot").style(f"background:{PRESENCE_COLOR[p['status']]}")
                ui.tooltip(p["text"]).props('anchor="bottom middle" self="top middle" :offset="[0, 6]"').style(
                    "white-space: nowrap; max-width: none")
        if hidden:
            more = ui.element("div").classes("sr-ag-item more").style(
                f"width:{size}px;height:{size}px;font-size:{round(size * .38)}px;z-index:0")
            with more:
                ui.label(f"+{hidden}")
                ui.tooltip(f"{hidden} người khác").props('anchor="bottom middle" self="top middle" :offset="[0, 6]"')
    return box


def presence_avatar(ui, name: str, status: str, label: str, size: int = 32, ring: str = "#fff",
                    tone: str = "green", colors: tuple[str, str] | None = None, photo: str = ""):
    """Avatar chữ cái đầu + chấm trạng thái. Màu chấm chỉ theo một giá trị `status` (available xanh, away vàng, busy
    đỏ, offline xám); ý nghĩa nằm trong tên đọc được (aria-label, tooltip) và dòng chữ cạnh đó, không chỉ bằng màu.
    `ring` là màu nền phía sau avatar (viền 2px tách chấm khỏi avatar)."""
    bg, fg = colors or TONES[tone]
    dot = max(8, round(size * 0.3))
    text = f"{name} · {label}"
    box = ui.element("div").classes("sr-presence").props("role=img").style(f"--ring:{ring}")
    box.props["aria-label"] = text
    with box:
        inner = (f'<img src="{escape(photo)}" alt="" style="width:100%;height:100%;object-fit:cover;'
                 f'border-radius:50%">' if photo else escape(name[:1].upper()))
        ui.html(f'<div class="sr-presence-avatar" style="width:{size}px;height:{size}px;background:{bg};color:{fg};'
                f'font-size:{round(size * 0.44)}px;overflow:hidden" aria-hidden="true">{inner}</div>')
        halo = '<span class="halo"></span>' if status == "available" else ""
        ui.html(f'<span class="sr-presence-dot" style="--dot:{PRESENCE_COLOR.get(status, PRESENCE_COLOR["offline"])};'
                f'width:{dot}px;height:{dot}px" aria-hidden="true">{halo}<span class="core"></span></span>')
        # Hiện bên phải avatar, một dòng: tránh bị cắt ở mép trên / đè lên tên khi avatar nằm sát cạnh màn hình
        ui.tooltip(text).props('anchor="center right" self="center left" :offset="[10, 0]"').style(
            "white-space: nowrap; max-width: none")
    return box


def status_chip(ui, text: str, tone: str = "grey", icon: str | None = None):
    bg, fg = TONES[tone]
    with ui.row().classes("items-center gap-1 no-wrap").style(
            f"background:{bg}; color:{fg}; border-radius:999px; padding:2px 10px; font-size:12px; font-weight:600"):
        if icon:
            ui.icon(icon, size="14px")
        ui.label(text)


def bar_slot(table, column: str, max_value: float, fmt: str = "toLocaleString('vi-VN')"):
    """Ô số kèm thanh ngang tỷ lệ với giá trị lớn nhất của cột (dễ nhìn thứ tự hơn số trần)."""
    mx = max(max_value, 1)
    table.add_slot(f"body-cell-{column}", f"""
        <q-td :props="props">
          <div class="sr-bar">
            <div class="sr-bar-fill" :style="{{width: Math.max(2, 48 * (props.value || 0) / {mx}) + 'px'}}"></div>
            <span>{{{{ props.value === null || props.value === undefined ? 'N/A' : props.value.{fmt} }}}}</span>
          </div>
        </q-td>""")


def empty_state(ui, icon: str, title: str, text: str = ""):
    with ui.element("div").classes("sr-card q-pa-xl w-full").style("text-align:center"):
        ui.icon(icon, size="40px").style("color:#B8B6A8")
        ui.label(title).classes("text-base font-semibold q-mt-sm")
        if text:
            ui.label(text).classes("text-sm muted")


def kpi_row(ui):
    """Hàng thẻ KPI: các thẻ cao bằng nhau, tự xuống hàng khi màn hẹp."""
    return ui.element("div").classes("sr-kpi-row")


def good_of(value) -> bool | None:
    return None if value is None or value == 0 else value > 0


# ---- Bảng: mặc định chung cho mọi ui.table ----
# Số trong bảng thường đã định dạng kiểu Việt ("4.981", "53,85%", "–"), sắp xếp chữ sẽ sai thứ tự (9 > 10). Cột căn
# phải (cột số) dùng hàm so sánh đọc lại con số; giá trị không phải số ("–", "chờ check") xếp cuối.
NUM_SORT = ("(a, b) => { const p = v => { if (v === null || v === undefined || v === '') return -Infinity;"
            " if (typeof v === 'number') return v; const s = String(v).replace(/[^0-9,.\\-]/g, '')"
            ".replace(/\\./g, '').replace(',', '.'); const n = parseFloat(s); return isNaN(n) ? -Infinity : n; };"
            " return p(a) - p(b); }")
NO_SORT = {"chart", "star", "gsc", "id"}


def _polish_column(col: dict) -> dict:
    col = dict(col)
    if col.get("name") in NO_SORT or not col.get("label"):
        return col
    col.setdefault("sortable", True)
    if col.get("align") == "right" and ":sort" not in col and "sort" not in col:
        col[":sort"] = NUM_SORT
    return col


def install_table_defaults() -> None:
    """Mọi bảng: cột nào cũng sắp xếp được (sắp trên toàn bộ dữ liệu, không chỉ trang đang xem), cột số sắp theo giá trị.
    Sọc xen kẽ và aria-sort làm bằng CSS/JS trong HEAD."""
    from nicegui.elements.table import Table
    if getattr(Table, "_sr_defaults", False):
        return
    original = Table.__init__

    def init(self, *, columns=None, **kwargs):
        original(self, columns=[_polish_column(c) for c in columns] if columns else columns, **kwargs)

    Table.__init__ = init
    Table._sr_defaults = True


def skeleton(ui):
    """Khung xám chờ dữ liệu, đặt trong vùng aria-busy để trình đọc màn hình biết đang tải."""
    with ui.element("div").classes("sr-busy").props('aria-busy="true" aria-label="Đang tải dữ liệu"'):
        return ui.skeleton()


BODY = """
<button id="sr-top" type="button" aria-label="Về đầu trang" title="Về đầu trang"
        onclick="window.scrollTo({top: 0, behavior: 'smooth'})">
  <span class="material-icons" aria-hidden="true">arrow_upward</span>
</button>
<script>
(() => {
  // Nút về đầu trang: chỉ hiện khi đã cuộn quá 400px.
  const top = () => document.getElementById('sr-top');
  addEventListener('scroll', () => { const b = top(); if (b) b.classList.toggle('show', scrollY > 400); },
                   {passive: true});

  // aria-sort cho tiêu đề cột đang sắp xếp (Quasar chỉ đổi class).
  let queued = false;
  const syncSort = () => {
    queued = false;
    document.querySelectorAll('th.sortable').forEach(th => {
      const v = th.classList.contains('sorted') ? (th.classList.contains('sort-desc') ? 'descending' : 'ascending')
                                                : 'none';
      if (th.getAttribute('aria-sort') !== v) th.setAttribute('aria-sort', v);
    });
  };
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(syncSort); } })
    .observe(document.documentElement, {subtree: true, childList: true, attributes: true, attributeFilter: ['class']});

  // Toast: một góc cố định (dưới phải), role="status"; thông báo thường tự tắt sau 4,5 giây và dừng đếm khi rê
  // chuột hoặc focus vào; lỗi và thông báo đang chạy giữ đến khi bấm Đóng / xong việc.
  const patch = () => {
    if (!window.Quasar || !Quasar.Notify || typeof Quasar.Notify.create !== 'function') return false;
    if (Quasar.Notify._sr) return true;
    const create = Quasar.Notify.create.bind(Quasar.Notify);
    Quasar.Notify.create = (opts) => {
      if (typeof opts === 'string') opts = {message: opts};
      opts = {position: 'bottom-right', ...opts};
      if (opts.position === 'bottom') opts.position = 'bottom-right';
      const error = opts.type === 'negative';
      const ongoing = opts.type === 'ongoing' || opts.spinner;
      if (error && !opts.closeBtn) opts.closeBtn = 'Đóng';
      if (error || ongoing || opts.timeout === 0 || opts.closeBtn) {
        opts.timeout = ongoing ? opts.timeout : 0;
        opts.attrs = {...(opts.attrs || {}), role: error ? 'alert' : 'status'};
        return create(opts);
      }
      const id = 't' + Math.random().toString(36).slice(2);
      let left = opts.timeout || 4500, start = Date.now(), timer;
      const dismiss = create({...opts, timeout: 0, attrs: {...(opts.attrs || {}), role: 'status', 'data-toast': id}});
      const run = () => { start = Date.now(); timer = setTimeout(dismiss, Math.max(left, 800)); };
      const pause = () => { clearTimeout(timer); left -= Date.now() - start; };
      run();
      setTimeout(() => {
        const el = document.querySelector(`[data-toast="${id}"]`);
        if (!el) return;
        el.addEventListener('mouseenter', pause); el.addEventListener('mouseleave', run);
        el.addEventListener('focusin', pause); el.addEventListener('focusout', run);
      }, 60);
      return dismiss;
    };
    Quasar.Notify._sr = true;
    return true;
  };
  const wait = setInterval(() => { if (patch()) clearInterval(wait); }, 100);
})();
</script>
"""


def donut(ui, items: list[tuple[str, float]], colors: list[str], unit: str, height: int = 230):
    """Donut cho các phần của một tổng (tối đa 6 phần, phần nhỏ nên gộp "Khác" trước khi gọi): khe đều giữa các
    lát, tổng ở giữa, chú thích cùng màu và cùng thứ tự. Rê chuột vào lát hoặc dòng chú thích thì lát đó nhô ra và
    giá trị hiện ở giữa (che phần tổng)."""
    import json
    pairs = [(n, v, c) for (n, v), c in zip(items, colors) if v][:6]  # bỏ phần bằng 0 mà vẫn giữ đúng màu
    items, colors = [(n, v) for n, v, _ in pairs], [c for _, _, c in pairs]
    total = sum(v for _, v in items)
    if not total:
        return None
    vi = {n: f"{v:,.0f}".replace(",", ".") + f"  ·  {v / total * 100:.0f}%" for n, v in items}
    # Tổng ở giữa là nhãn của lát đầu tiên; lát khác không có nhãn. Rê chuột vào một lát: lát đó hiện giá trị của nó,
    # các lát còn lại chuyển trạng thái "blur" và ẩn nhãn, nên ở giữa luôn chỉ có một dòng chữ (không chồng nhau).
    total_text = f"{total:,.0f}".replace(",", ".")
    return ui.echart({
        "animation": True,
        "tooltip": {"show": False},
        "legend": {"orient": "vertical", "left": "60%", "top": "middle", "icon": "circle", "itemWidth": 9,
                   "itemHeight": 9, "itemGap": 12, "textStyle": {"fontSize": 12, "color": INK},
                   ":formatter": f"name => name + '   ' + ({json.dumps(vi, ensure_ascii=False)})[name]"},
        "series": [{
            "type": "pie", "radius": ["58%", "80%"], "center": ["30%", "50%"], "padAngle": 2,
            "avoidLabelOverlap": False, "labelLine": {"show": False},
            "itemStyle": {"borderRadius": 4, "borderColor": "#fff", "borderWidth": 1},
            "label": {"show": True, "position": "center", "color": INK,
                      ":formatter": f"p => p.dataIndex === 0 ? '{{t|{total_text}}}\\n{{u|{unit}}}' : ''",
                      "rich": {"t": {"fontSize": 22, "fontWeight": 800, "lineHeight": 26, "color": INK},
                               "u": {"fontSize": 11, "color": MUTED, "lineHeight": 16}}},
            "emphasis": {"focus": "self", "scale": True, "scaleSize": 6, "label": {
                "show": True,
                ":formatter": "p => '{n|' + p.name + '}\\n{t|' + p.value.toLocaleString('vi-VN') + '}\\n{u|' + "
                              "p.percent.toLocaleString('vi-VN', {maximumFractionDigits: 0}) + '%}'",
                "rich": {"n": {"fontSize": 11, "color": MUTED, "lineHeight": 16},
                         "t": {"fontSize": 20, "fontWeight": 800, "lineHeight": 24, "color": INK},
                         "u": {"fontSize": 11, "color": MUTED, "lineHeight": 16}}}},
            "blur": {"label": {"show": False}, "itemStyle": {"opacity": 0.35}},
            "data": [{"name": n, "value": v, "itemStyle": {"color": c}} for (n, v), c in zip(items, colors)],
        }],
    }).style(f"height: {height}px; width: 100%")
