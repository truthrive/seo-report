# SEO REPORT — AI SEARCH & GEO ANALYTICS MODULE

**Technical / Product Specification v1.0**  
Ngày đặc tả: 29/10/2026 | Ngôn ngữ giao diện: Tiếng Việt (giữ convention i18n của ứng dụng nếu có)  
Trạng thái: **Ready for repository discovery & implementation planning**. Chưa kiểm tra trực tiếp mã nguồn SEO Report hiện tại.

> **Mục tiêu:** Bổ sung module AI Search & GEO Analytics vào SEO Report đã có kết nối API GSC và GA4. Không xây app mới, không viết lại OAuth, không thay stack. Dashboard Looker Studio Tâm Đức trong `AI_Traffic_Analytics.pdf` là tài liệu tham chiếu về nghiệp vụ/bố cục, **không phải nguồn xác thực công thức nguyên bản**.

## 0. Cơ sở và phân loại bằng chứng

- **[REFERENCE]**: Từ PDF 5 trang (Tâm Đức – GA4, 31/07–29/10/2026): (1) Organic channels Overview, (2) AI sources, (3) Landing pages, (4) Countries, (5) Content groups. Bộ lọc property, ngày, channel, source, country, landing page.
- **[VERIFIED GOOGLE]**: Thông tin chính thức về GA4 Data API, Search Console Search Analytics API, GA4 AI Assistants channel và GSC Generative AI report, trích dẫn ở cuối.
- **[DESIGN]**: Các phần nằm trong đặc tả này là quyết định đề xuất để xây module mới; không khẳng định có sẵn trong repository.
- **[OPEN]**: Framework, frontend, state management, database, route, services, job scheduler, permissions, naming conventions, exact GA4 property/GSC siteUrl, hệ thống caching: bắt buộc Claude Code tự khám phá trong repo.

### 0.1. Những gì MVP đo lường được và không được

| Nhu cầu | Nguồn | MVP | Giới hạn cách diễn giải |
|---|---|---|---|
| Lượt truy cập từ AI assistants và hiệu quả | GA4 Data API | **Có** | Là attributed/referral sessions xác định được; không phải mọi lượt AI nhắc brand |
| Chất lượng AI traffic và key events | GA4 Data API | **Có** | Dùng đúng session-scoped metrics và rate gốc |
| So sánh với Organic Search/Social | GA4 Data API | **Có** | Google AI Overviews/Mode click phần lớn nằm trong Google Organic Search, không tách bằng GA4 nguồn thông thường |
| Search impressions/clicks/CTR/position | GSC Search Analytics API `type=web` | **Có** | Là tổng Google Web, **không gọi là AIO/AI Mode metrics** |
| GSC Generative AI impressions | GSC giao diện báo cáo chuyên biệt | **Bổ sung nhập dữ liệu nếu có** | Không giả định Search Analytics API có endpoint/type truy vấn trực tiếp |
| AI citations, brand mentions, competitor SOV | Công cụ theo dõi prompt/API ngoài | **Không** | UI ghi “Chưa có nguồn dữ liệu”, không dựng số mẫu thành KPI thật |
| AI crawler bot requests | Server logs | **Không** | Chỉ bật khi SEO Report có module logfile đã tích hợp và dữ liệu kiểm chứng |

**Naming boundary bắt buộc:** `AI Referral Traffic` ≠ `Google Generative AI Visibility` ≠ `Brand/Citation Visibility`.

---

## 1. Agent workflow — trước khi viết code

Claude Code phải thực hiện tuần tự:

1. Đọc README, cấu trúc project, package manifests, env example, module SEO Reports hiện hữu, route/API handlers, services GSC & GA4, OAuth/token refresh, project/property selection, persistence/cache, test framework, design system.
2. Tìm các data models dùng chung: `Project`, `Connection`, `GA4Property`, `GSCProperty`, `Report`, `ReportRun` (tên là ví dụ; giữ đúng tên thực tế). Kiểm tra project isolation.
3. Truy tìm nơi API trả về GA4/GSC, nơi normalize row, nơi cấu hình date ranges và nơi dùng timezone.
4. Kiểm tra metadata GA4 và compatibility cho các dimension/metric dự kiến. Không sử dụng trường không hỗ trợ trong property thực tế.
5. Lập `REPO_DISCOVERY_REPORT.md` gồm stack phát hiện, file entry points, paths sửa, cách tái sử dụng service/OAuth, rủi ro breaking changes và migration (nếu có).
6. Chỉ sau discovery mới bắt đầu implementation, ưu tiên một vertical slice end-to-end (API → normalize → UI → test).

**Hard constraints:** Không tạo OAuth flow mới; không duplicate Google API client; không chuyển stack; không thêm database/queue nếu tính năng hiện tại chưa cần; không sửa behavior module khác; không xóa dữ liệu/ghi production, không commit/push/deploy trừ khi user yêu cầu; không dùng secrets trong logs hoặc fixture.

---

## 2. Functional scope và thứ tự ưu tiên

### P0 — Must-have, triển khai từ GA4 API hiện hữu

- **Page A — Executive Overview:** tổng AI referral sessions, AI traffic share, growth kỳ so sánh, engaged sessions, engagement rate, average engagement time/session, key events, session key event rate. So sánh AI Assistants, Organic Search, Organic Social; trend tuần/ngày.
- **Page B — AI Traffic Sources:** traffic theo từng AI source; nguồn native vs fallback; traffic trends; bảng breakdown; nguồn chưa phân loại; có export CSV.
- **Page C — AI Landing Pages:** landing page của AI sessions; sessions, engagement, key events, session key event rate, comparison period; drilldown source × URL; export; `(not set)` riêng.
- **Page D — Geography:** country, sessions, rate, weekly trend; country × source; click to filter.
- **Page F — Data Quality:** trạng thái kết nối, metric coverage, data freshness, unmatched sources, discrepancies, unsupported metrics, last sync/last successful run.

### P1 — Nâng giá trị SEO/GEO với GSC API hiện hữu

- **Page E — SEO/GEO Opportunities:** bảng URL GA4 AI referral sessions và GSC Web clicks/impressions/CTR/position nằm **trong hai cột dữ liệu khác nguồn**, không ảo tưởng rằng clicks GSC do AI tạo ra; URL normalization có kiểm soát; opportunities theo luật rõ ràng.
- Tối thiểu ba rule:
  - `AI_REFERRAL_WITH_LOW_GSC_VISIBILITY`: trang có AI referrals nhưng GSC Web impressions thấp so với ngưỡng có cấu hình; chỉ là gợi ý phân tích, không kết luận nhân quả.
  - `GSC_HIGH_IMPRESSIONS_LOW_AI_REFERRAL`: trang có Web impressions cao, AI referrals thấp; **không gọi là thiếu AIO citations**.
  - `AI_ENGAGEMENT_WEAK`: AI sessions đủ sample, engagement thấp hơn baseline đã chọn; hiển thị sample size, confidence.
- Cho phép cấu hình thresholds theo project; không hardcode 10 hay 100 thành chuẩn thống kê.

### P2 — Optional, phụ thuộc nguồn dữ liệu ngoài hai API

- **Google Generative AI Visibility:** chỉ khi có import CSV/sheet/export đáng tin cậy hoặc tích hợp API chính thức được xác nhận có hỗ trợ. `status = NOT_CONNECTED / MANUAL_IMPORT / API_VERIFIED`. Tách dữ liệu Search và Discover, tách scope `property/day`, `page/day`, `country/day`, `device/day`. Không cộng chéo các bảng tổng.
- **Content group**: chỉ bật khi `contentGroup` metadata GA4 có dữ liệu hữu ích, hoặc dự án có URL taxonomy/mapping minh bạch. Nếu `(not set)` > 80%, show coverage warning và danh sách URL chưa phân loại, không tạo chart “phân nhóm” thiếu ý nghĩa.
- **AI Visibility / citations / SOV** và **AI bot crawlers**: placeholder minh bạch, không tính hoặc estimate từ GSC Web/GA4.

---

## 3. UX/UI: navigation, filters, biểu đồ

### 3.1. Navigation

Thêm một mục `AI Search & GEO` vào module Reports hiện tại; các tabs/sections sau là đề xuất, đổi theo UI convention của repo:

1. Tổng quan
2. Nguồn AI
3. Trang đích
4. Khu vực địa lý
5. Cơ hội SEO/GEO
6. Chất lượng dữ liệu
7. Google AI Visibility *(chỉ khi P2 đã có dataset)*

Chung mọi trang: `Project`, `GA4 property`, `GSC property` (chỉ những trang dùng GSC), `Date range`, `Compare to previous period`, `Channel`, `AI source`, `Country`, `Landing page` (search/select); controls phải dùng chung query state, lưu URL query params nếu codebase đã hỗ trợ. Không render filter rỗng như nút có hiệu lực.

### 3.2. Page A — Tổng quan

- KPI cards: AI Sessions, AI Traffic Share of Selected Comparison Base, AI Engaged Sessions, AI Engagement Rate, Average Engagement Time Per Session, Key Events, Session Key Event Rate, AI Session Growth.
- Secondary cards: Organic Search Sessions, Organic Social Sessions và trend tương ứng.
- Daily/weekly multi-line: `AI Assistants`, `Organic Search`, `Organic Social`.
- Comparison table: channel × sessions / engaged sessions / engagement rate / key events / key event rate / average session duration; source-specific data availability flags.
- AI Source share bar hoặc donut, không tạo quá nhiều donut trùng ý nghĩa.
- CTA drill-down: `Xem nguồn AI`, `Xem landing pages`, `Kiểm tra dữ liệu`.
- Toggle hiển thị native GA4 vs hybrid source classification (nếu khác biệt), có chú thích số chênh.

### 3.3. Page B — Nguồn AI

- Table/Bar: `AI source`, `source host`, `Sessions`, `Engaged sessions`, `Engagement rate`, `Average engagement time/session`, `Key events`, `Session key event rate`, `% change`, `Classification method`.
- Week/day trend multi-series (top 5 sources + `Other AI`).
- Khung `Unknown / ambiguous sources` với số và khả năng export để bổ sung allowlist.
- Bấm source → các trang khác cập nhật source filter.

### 3.4. Page C — Trang đích

- Table paginated/sort/search, URL hiển thị path ngắn nhưng tooltip/full URL được lưu riêng:
  `Landing page`, `AI Sessions`, `AI Engagement Rate`, `Key Events`, `Session Key Event Rate`, `Organic Search Sessions` (optional), `AI Sessions Δ`.
- Time series cho URL được chọn; pivot `landing page × AI source` (nếu quy mô cho phép).
- Segmentation có thể dựa trên URL taxonomy có cấu hình: home/category/product/service/blog/location/other; tuyệt đối không coi GA4 `contentGroup=(not set)` là nhóm thực.
- `(not set)` là hàng riêng có warning; không âm thầm chuyển thành homepage.

### 3.5. Page D — Địa lý

- Country table; country × source matrix; trend country top N; optional map nếu package hiện có.
- Không suy đoán vị trí cửa hàng từ `country`; đây là geography của người truy cập do GA4 ghi nhận.

### 3.6. Page E — SEO/GEO Opportunities

- Thẻ `GSC Web Search context` với giải thích `includes AI-related Google Search traffic but is not AI-only`.
- URL table hai nhóm cột tách biệt: **GA4 AI referral** (`sessions`, `engagement rate`, `key events`) và **GSC Web** (`clicks`, `impressions`, `CTR`, `position`).
- Cho phép lọc `only matched`, `unmatched GA4`, `unmatched GSC`, loại URL theo page type.
- Audit/opportunity list: `rule_id`, `title`, `evidence`, `threshold`, `severity`, `confidence`, `recommended verification`, `suggested SEO action`, `data_period`, `source`.
- Chỉ tính delta có căn cứ, không nhân `GSC clicks` với `GA4 key event rate` để suy ra AI conversions.

### 3.7. Page F — Data Quality & Settings

- Connections: GA4/GSC linked, permission status, data range status, active Google property ID/siteUrl (không hiển thị credentials).
- Source mapping version, source inventory, counts `native`, `fallback`, `unclassified`, updated_at.
- KPI QA: total consistency/delta, rate range 0–1, invalid/empty URLs, partial weeks, API thresholding/data loss/limits warnings.
- Settings: editable trusted domain allowlist (only if settings infrastructure & authorization exists), selected key event(s), opportunity thresholds, cache refresh, source classification mode.

### 3.8. Visual rules

- Tôn trọng design system, typography, responsive breakpoints, dark/light mode nếu có.
- Loading skeleton, empty state (genuine zero vs no permission vs unsupported vs loading vs partial), retry CTA.
- Format: counts integer; rates 0–100% 1–2 decimals; durations `mm:ss` hoặc `hh:mm:ss` khi hợp lý; negative delta có dấu; `N/A` nếu không có denominator.
- Cảnh báo dữ liệu gốc/đã ước tính/không khả dụng, không được giả số minh họa thành thật.
- CSV export dùng chính query state, có metadata header hoặc file README kèm kỳ, source, timestamp, filter.

---

## 4. Domain model & nguồn dữ liệu

### 4.1. GA4 field mapping (Google Analytics Data API)

| Business field | GA4 API field | Scope / notes |
|---|---|---|
| Date | `date` | Property-local date |
| Source | `sessionSource` | **Session** scope |
| Source/Medium | `sessionSourceMedium` | Session scope, debug |
| Medium | `sessionMedium` | Session scope |
| Native channel | `sessionDefaultChannelGroup` | Session scope: `AI Assistants`, Organic Search, Organic Social... |
| Landing page | `landingPage` | First pageview in session |
| Landing query page | `landingPagePlusQueryString` | Optional, avoid parameter cardinality for main table |
| Country | `country` | GA4 geography |
| Sessions | `sessions` | Integer |
| Engaged sessions | `engagedSessions` | Integer |
| Engagement rate | `engagementRate` | 0–1 fraction from API |
| Bounce rate | `bounceRate` | 0–1 fraction, optional |
| Avg session duration | `averageSessionDuration` | Seconds; query at correct grain |
| User engagement total | `userEngagementDuration` | Seconds; derived average = total/sessions when compatible |
| Key events | `keyEvents` | Count of key event occurrences |
| Session key event rate | `sessionKeyEventRate` | 0–1 fraction; **not** `keyEvents/sessions` |
| Specific key event rate | `sessionKeyEventRate:<event_name>` | Only if metadata confirms event exists |
| Revenue (optional) | `totalRevenue` | Only if ecommerce instrumentation is validated; do not present as reliable by default |

**Rule:** Always retrieve property metadata (`properties.getMetadata`) and check specific request compatibility (`properties.checkCompatibility`) before issuing complex queries. When incompatible, split into multiple queries or return metric `unsupported`, not silent zero.

### 4.2. GSC field mapping

- API `searchanalytics.query` with `siteUrl` exactly as property selection returned (support `sc-domain:...` and `https://.../` prefixes).
- Explicit `type: "web"` for standard search context; dimensions `date`, `page`, `query`, `country`, `device` as relevant; output metrics `clicks`, `impressions`, `ctr`, `position`.
- Separate **property aggregated totals** from **page aggregated rows**; no sum of page rows to impersonate property totals.
- `rowLimit <= 25000`, `startRow` pagination and returned top-row data limitations. Show coverage warning when likely incomplete.
- Preserve raw URL/canonical mapping; normalized keys are for *comparison*, not replacement of source URLs.
- **Never** label `type=web` as “Google AI Overviews clicks/impressions.”

### 4.3. Optional GSC Generative AI import schema

*Implement only after confirming source UI exports can be mapped to chosen schema.*

```
import_batch_id,project_id,site_url,report_type,aggregation_scope,
period_start,period_end,date,page,country,device,impressions,
source_export_date,source_filename,timezone,validation_status
```

- `report_type` ∈ `GSC_GENAI_SEARCH`, `GSC_GENAI_DISCOVER`.
- `aggregation_scope` ∈ `PROPERTY_DATE`, `PAGE_DATE`, `COUNTRY_DATE`, `DEVICE_DATE`.
- `page/country/device` optional according to scope.
- Không cộng chéo scopes; không suy đoán AI clicks/CTR nếu nguồn không có.
- Import validation, duplicate handling, import audit trail, rollback; không dùng import làm thay đổi raw GSC Web dataset.

---

## 5. Quy tắc phân loại AI sessions (Critical)

### 5.1. Labels

`AI_ASSISTANTS`, `ORGANIC_SEARCH`, `ORGANIC_SOCIAL`, `OTHER`.  
Subsource `CHATGPT`, `GEMINI`, `CLAUDE`, `PERPLEXITY`, `COPILOT`, `DEEPSEEK`, `GROK`, `OTHER_AI`, `UNKNOWN`.

### 5.2. Prioritization, session scope

1. Nếu native `sessionDefaultChannelGroup` normalized ∈ `AI Assistant`, `AI Assistants` → `AI_ASSISTANTS`, `classificationMethod=NATIVE`.
2. Fallback: `sessionSource` chứa hostname đã xác nhận thuộc allowlist (exact host hoặc subdomain hợp lệ, không substring tùy tiện) và `sessionMedium` **không** thuộc paid medium bị loại trừ theo policy → `AI_ASSISTANTS`, `classificationMethod=FALLBACK_REFERRER`.
3. Nếu native `Organic Search` → `ORGANIC_SEARCH`; `Organic Social` → `ORGANIC_SOCIAL`; còn lại `OTHER`.
4. Một session không được cộng hai lần dù native và fallback cùng nhận diện. Preserve raw source/channel cùng classification version để QA.
5. Không gán `google`, `google.com` hay `google / organic` thành AI vì không có cơ sở tách AI Overviews/AI Mode từ GA4.

Danh sách seed allowlist (configurable/validated, không khẳng định exhaustively complete): `chatgpt.com`, `chat.openai.com`, `gemini.google.com`, `claude.ai`, `perplexity.ai`, `copilot.microsoft.com`, `deepseek.com`, `grok.com`. Xác minh các hostname/alias thực tế bằng inventory trong GA4; không wildcard domain `openai.com`, `google.com`, `microsoft.com`.

**Important:** Định nghĩa “AI Referral” có thể bao gồm traffic mang UTM khác `referral`, và native GA4 có thể phân loại khác fallback. Chỉ định `classificationMode` là `NATIVE`, `HYBRID` (default), `FALLBACK_ONLY` (diagnostic). Hiển thị reconciliation native vs hybrid; không ép số khớp Looker gốc.

### 5.3. Accurate aggregated KPI strategy

**Không được:** query theo source, sau đó `sum(averageSessionDuration)` hoặc `sum(sessionKeyEventRate)`; cũng không tổng hợp `keyEvents/sessions` rồi đặt tên “Conversion Rate.”

**Bắt buộc:** khi user lọc nhóm AI, truy vấn **aggregate GA4 trực tiếp theo same filter** với dimensions rỗng để lấy group-level `sessions`, `engagedSessions`, `engagementRate`, `averageSessionDuration`, `keyEvents`, `sessionKeyEventRate`. Có thể xây `dimensionFilter` với OR native group/fallback allowed sources, kèm AND các filter toàn cục. Danh sách fallback đủ hẹp, có test source exclusion, query size & compatibility. Với query chưa thể biểu diễn logic classification trên server, trả về unavailable cho affected rate hoặc tạo query kế hoạch khác có tính chính xác đã kiểm định; **không vá sai bằng cộng các percentage**.

- Cùng một khoảng ngày, filter, comparison period, GA4 property, mode cho mọi chart.
- Nếu denominator = 0, delta = `null` + reason `NO_BASELINE`, không hiển thị ±∞%.
- **Engagement rate** = engaged sessions / sessions, có thể rederive đúng nếu `engagedSessions` và `sessions` là same scope/filter; ưu tiên native metric nếu phù hợp.
- **Average engagement time/session** = total `userEngagementDuration` / sessions (chỉ nếu tương thích và đúng GA4 scope).
- **Session key event rate** từ native metric, không thể xác định từ `keyEvents/sessions`.
- **Key Events per 100 Sessions** = 100 × keyEvents / sessions, nhãn phải ghi đúng (không gọi “session conversion rate”).
- **AI share** = AI sessions / denominator đã mô tả rõ (`all sessions` hoặc `selected organic comparison base`). UI hiển thị denominator và query contract.

### 5.4. Query templates — PSEUDOCODE, adapt to repository conventions

**Q0 Summary AI group:**

```json
{
  "dateRanges": [{"startDate":"2026-09-01","endDate":"2026-09-30"}],
  "dimensions": [],
  "metrics": [
    {"name":"sessions"}, {"name":"engagedSessions"},
    {"name":"engagementRate"}, {"name":"averageSessionDuration"},
    {"name":"userEngagementDuration"}, {"name":"keyEvents"},
    {"name":"sessionKeyEventRate"}
  ],
  "dimensionFilter": {
    "orGroup": {"expressions": [
      {"filter": {"fieldName":"sessionDefaultChannelGroup", "stringFilter":{"value":"AI Assistants","matchType":"EXACT"}}},
      {"filter": {"fieldName":"sessionDefaultChannelGroup", "stringFilter":{"value":"AI Assistant","matchType":"EXACT"}}},
      {"filter": {"fieldName":"sessionSource", "inListFilter":{"values":["chatgpt.com","gemini.google.com","claude.ai","perplexity.ai"]}}}
    ]}
  },
  "returnPropertyQuota": true
}
```

**CHÚ Ý:** Đây chỉ là ví dụ hình dạng API, chưa là production query: phải thêm country/URL/source/medium filters, paid-source exclusions và dynamic allowlist, xác minh channel label thực tế; `checkCompatibility`; không chấp nhận sao chép nguyên xi mà bỏ qua classification contract. Nếu repo không có hỗ trợ truy vấn `inList` hoặc filter OR/AND, implement query builder testable, không tự SUM các rate source rows.

**Q1 Source breakdown:** dimensions `[sessionSource, sessionDefaultChannelGroup]`, metrics `[sessions, engagedSessions, keyEvents]`, optional rates per source query/GA4 native tại đúng scope; pagination và return `rowCount`.

**Q2 Trend:** dimensions `[date]` cho overall; thêm `[date, sessionSource]` cho source lines khi compatible.

**Q3 Landing:** dimensions `[landingPage]` / `[landingPage, sessionSource]`; metric set minimum; filter AI đúng như Q0.

**Q4 Country:** dimensions `[country]` / `[country, sessionSource]`; filter AI đúng như Q0.

**Q5 GSC Web:** site-total `dimensions:[date]`; page table `dimensions:[page]`; optional `dimensions:[page,query]` là limited top rows, không dùng làm denominator toàn site.

---

## 6. API / domain service contract (đề xuất, không ép route tên)

Reuse backend router/module patterns, authorization and project scoping đã có. Ví dụ endpoint:

```http
GET /api/projects/{projectId}/ai-analytics/capabilities
GET /api/projects/{projectId}/ai-analytics/summary?startDate=...&endDate=...&compare=previous&mode=hybrid
GET /api/projects/{projectId}/ai-analytics/trend?interval=week&...
GET /api/projects/{projectId}/ai-analytics/sources?sort=sessions&limit=...
GET /api/projects/{projectId}/ai-analytics/landing-pages?limit=50&offset=0&...
GET /api/projects/{projectId}/ai-analytics/countries?...
GET /api/projects/{projectId}/ai-analytics/opportunities?...
GET /api/projects/{projectId}/ai-analytics/quality?...
```

### 6.1. Shared filters and response shape

```json
{
  "projectId": "<opaque-project-id>",
  "period": {"startDate":"YYYY-MM-DD", "endDate":"YYYY-MM-DD", "timezone":"<GA4 timezone>"},
  "comparisonPeriod": {"startDate":"YYYY-MM-DD", "endDate":"YYYY-MM-DD"},
  "filters": {"channel":"AI_ASSISTANTS", "source":null, "country":null, "landingPage":null},
  "classification": {"mode":"HYBRID", "version":"v1", "definition":"native+verified-referrer"},
  "data": {"sessions":609, "engagedSessions":null, "engagementRate":null, "keyEvents":17, "sessionKeyEventRate":null},
  "status": "PARTIAL",
  "warnings": [{"code":"EXAMPLE_ONLY","message":"Illustrative structure, values not current live data"}],
  "sourceMeta": {"provider":"GA4", "propertyId":"<id>", "queriedAt":"ISO-8601", "isSampled":null}
}
```

**Không hardcode các số ví dụ vào code**; JSON chỉ mô tả payload type. Numeric rates luôn 0–1 trên wire; frontend format %; numeric durations seconds; counts integer. `null` là unavailable, `0` chỉ khi API trả về zero xác thực. Type-safe error/warning envelopes; project-specific permission checks, no credentials in payload.

### 6.2. Proposed service boundaries

- `AIAnalyticsService` orchestration: filter normalization, date ranges, concurrency, snapshots.
- `AIChannelClassifier` pure + versioned domain allowlist.
- `GA4AnalyticsAdapter` *reuses existing GA4 API client*, request builder, fetch metadata, validate dimension/metric compatibility, aggregate queries.
- `GSCSearchAdapter` *reuses existing GSC API client*; property-level vs page-level distinctions.
- `URLNormalizer` pure; query stripping policy and host canonical mapping **must be project-configurable**.
- `OpportunityEngine` rule-based with provenance/threshold/confidence.
- `ReportQualityValidator` consistency, missing fields, source reconciliation, no denominator.
- `GenerativeAIImportService` optional P2.

### 6.3. Persistence / cache

- Reuse project config and cache primitives already present; don't introduce Redis/DB for this feature unless existing cache cannot meet use cases.
- Cache key must include `projectId`, `ga4PropertyId`, `gscSiteUrl`, `start`, `end`, `compare`, all dimensions filters, `classificationMode`, `classificationVersion`, `querySchemaVersion`.
- TTL configurable; proposed recent-period 1–6h, closed historic 24h (team decides based on actual rate limits).
- Explicit refresh with permission, rate limit; distinguish `cached` / `fresh` / `stale` responses.
- Persist optional snapshot only if existing reporting architecture already persists report runs; never store OAuth access tokens in analytics snapshot.
- GA4: request `returnPropertyQuota`, queue concurrency, capped retries exponential backoff for 429/5xx; batch related requests within API limits and monitor token cost.

### 6.4. Date / time

- GA4 query date = property's timezone. GSC Search Analytics API date boundaries use Pacific Time; **do not silently join daily time series as if dates had identical timezone**.
- UI allows shared calendar range; show tooltip on date discrepancy and separate source provenance.
- Comparison `previous period` = immediately preceding inclusive interval with same number of calendar days. `previous year` optional, correct leap-day handling.
- ISO weekly intervals start Monday; mark partial first/last weeks (30/07–01/08 etc.) and do not treat incomplete last week as full-week decline.
- Recent incomplete dates should be marked `provisional`; standard GSC default `dataState=final` unless user chooses fresh data.

---

## 7. Data Quality & Known problems from reference

### 7.1. Reference figures (PDF snapshot ONLY, not acceptance oracle)

- Organic Search **68,441 sessions**, **740 key events**.
- Organic Social **3,842 sessions**, **19 key events**.
- AI Chats **609 sessions**, **17 key events**.
- AI sources ChatGPT `537`, Gemini `66`, Claude `3`, Perplexity `3` (sums 609).
- AI page performance table displays 195 landing page rows; content group `594 (not set)`, `15 blank`.
- Different tables displayed GA4 AI total 608, 609, 610, 603 — not sufficient to assign an exact root cause.

### 7.2. Avoid reproducing Looker reference bugs

1. `03:49 + 03:10 + 11:08 + 00:50 = 18:57`, and source AI table overall incorrectly appears to show `18:57` average; weighted illustrative value is ~03:46. **Do not SUM averages**; native group GA4 metric is source of truth.
2. Organic Search source session key event rates `0.79%+0.85%+0.95%=2.59%`, suspiciously equal displayed 2.6%. **Do not SUM percentages**.
3. Looker `Conversion rate` chart appears `17/609≈2.79%` while actual `sessionKeyEventRate` may differ. Rename appropriately or use native rate metric.
4. `null` totals, missing countries, missing landing pages, `contentGroup=(not set)` may be export, scope, GA4 cardinality/thresholding or chart configuration; don't automatically decide root cause without query-level QA.

### 7.3. QA report requirements

Each API query should retain internal diagnostics (not leaked to public UI): query fingerprint, range, field list, dimensions, GA4 property, rowCount, exception, retry count, quota status, timestamps, query filter fingerprint. No PII or OAuth tokens.

Diagnostic flags with severity:
- `API_PERMISSION_DENIED`, `PROPERTY_NOT_FOUND`, `METRIC_INCOMPATIBLE`, `DATA_NOT_AVAILABLE`, `INCOMPLETE_PERIOD`, `LOW_SAMPLE_SIZE`, `GA4_TOTAL_DISCREPANCY`, `UNMAPPED_AI_SOURCE`, `GSC_TOP_ROWS_LIMIT`, `URL_MATCH_AMBIGUOUS`, `NO_GENERATIVE_AI_SOURCE`, `CONTENT_GROUP_LOW_COVERAGE`.

---

## 8. Testing strategy

### Unit tests

- Classification native AI label singular/plural, source allowlist, subdomain boundaries (not `evilchatgpt.com`), upper/lowercase, full hostname, `google.com` excluded, paid medium policy, native + fallback dedup.
- Rate handling: GA4 0.0243 → UI `2.43%`; no doubling; 0 sessions → `N/A`; `keyEvents=17,sessions=609` → `2.79 key events per 100 sessions` and **NOT** session key event rate.
- Avg duration: group `229s × 537`, `190s × 66`, `668s × 3`, `50s × 3`: weighted illustrative ≈226s, **never** 1137s.
- Period comparison equal-length dates; ISO week crossing year; partial week; property timezone vs GSC Pacific warning.
- URL normalization preserving raw URL, preventing collisions of meaningful params; canonical different hosts explicitly handled; `(not set)` preserved.
- Prevent GSC Web metrics from being labeled AI impressions; no implicit join by sessions.

### Integration tests (mock Google APIs; live smoke opt-in)

- Existing Google OAuth/service reused; project A cannot query project B credentials/property.
- Pagination GA4 and GSC; 429/403/5xx error handling; Data API incompatible metric fallback or warning.
- Same filters propagate summary/source/landing/country queries; errors produce partial data status not false zero.
- Metadata/compatibility discovery; key event-specific metric only when registered.
- GSC domain property `sc-domain:...` vs URL prefix exact string; no accidental rewriting.
- CSV export uses same dataset snapshot, includes schema/period provenance.

### UI tests / manual QA

- Responsive desktop/tablet/mobile; loading/empty/error; filter persistence/navigation; source drilldown; %/time formatting; no table overflow; accessible sort/pagination.
- Screenshot regression on selected pages if existing CI supports it; otherwise manual review report.
- Compare API aggregate against GA4 UI/data API same filters; reconcile numeric deltas with notes, do not assert that every dimensioned table sums exactly due API limits/thresholding.

### Exit criteria (definition of done)

1. At least 5 P0 pages implemented and accessible from existing SEO Report navigation.
2. Existing GSC & GA4 connections unaffected, existing tests pass.
3. For GA4 queried project/date filter, source breakdown, charts and total KPI use consistent channel definition and query provenance.
4. `sessionKeyEventRate` and `averageSessionDuration` are **not** calculated by sum over source rows; native aggregate verified.
5. AI Google Search visibility cannot appear as zero/false if GSC generative AI data was never connected/imported; status `Not available`.
6. Error/permission handling and export work; multi-project isolation validated.
7. QA report includes discovered source/schema, checks, known limitations and screenshots; no unsupported “fully GEO visibility” claims.

---

## 9. Delivery phases & artifact checklist

| Phase | Required outputs | Stop / proceed gate |
|---|---|---|
| 0 — Repo Discovery | `REPO_DISCOVERY_REPORT.md`, existing-code map, API support matrix, final file plan | Identify actual stack/OAuth/data state before writing |
| 1 — GA4 Core | Classification, aggregator, Overview, Sources, Landing Pages, Countries, tests | GA4 totals & rate semantics validated |
| 2 — GSC Context | Opportunities, URL alignment, status warnings, tests | GSC page data not relabeled as AI visibility |
| 3 — QA & Rollout | Data Quality page, exports, tests, screenshots, user docs | All core acceptance criteria pass |
| 4 — Optional | GSC Generative AI imports, content taxonomy, bot logs, third-party AI visibility | Requires independently verified source/coverage |

For each implementation round, Claude Code should report:
- Files changed, architecture decisions, tests executed (command + result), assumptions and blockers.
- Real API smoke result only if environment has authorized test credentials; otherwise explicit `NOT VERIFIED LIVE`.
- Screenshots of UI or describe inability to run UI; do not claim QA complete without evidence.
- Avoid auto-commit/push/deploy without instruction.

---

## 10. Open questions for repository discovery (not user-blocking for spec)

1. Repository, framework, persistence, auth, current route structure; all unknown from conversation.
2. GA4 property/account selection, timezone discovery and Data API existing query builder.
3. Whether current GSC connector handles Domain and URL-prefix properties, `dataState`, pagination and high cardinality.
4. Definitions/which events are marked key events; selecting `All key events` vs a specific event.
5. Which URL paths and hostname aliases are in each project; page taxonomy and handling marketing query params.
6. Existing UI module structure and permissions for storing project-level source mapping.
7. Production runtime limits and Google API quotas observed on active properties.

## 11. Primary official references (verified 29/10/2026)

- Google Analytics Default channel group — AI Assistants and Organic Search: https://support.google.com/analytics/answer/9756891
- GA4 Data API dimensions & metrics: https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema
- GA4 property metadata: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/getMetadata
- GA4 metric-dimension compatibility: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/checkCompatibility
- GA4 runReport: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport
- GA4 quotas: https://developers.google.com/analytics/devguides/reporting/data/v1/quotas
- Search Analytics query API: https://developers.google.com/webmaster-tools/v1/searchanalytics/query
- GSC Generative AI reporting release: https://developers.google.com/search/blog/2026/06/gen-ai-performance-reports
- GSC Generative AI performance report: https://support.google.com/webmasters/answer/16984139
- Google AI features eligibility/measurement: https://developers.google.com/search/docs/appearance/ai-features

**Key rule:** Do not invent a GSC API for Generative AI impressions; implement manual import only after verifying actual export format, or integrate a publicly documented supported API once genuinely available.
