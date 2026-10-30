# CLAUDE CODE IMPLEMENTATION BRIEF — AI SEARCH & GEO ANALYTICS

Bạn là Senior Full-stack Engineer + Analytics Engineer chịu trách nhiệm tích hợp một module mới vào **SEO Report hiện tại**. Ứng dụng đã có Google Search Console API và Google Analytics 4 API connections.

**Tài liệu bắt buộc đọc trước:** `SEO_Report_AI_Search_GEO_Module_Spec_v1.0.md`. Nếu tài liệu chưa ở trong repo, yêu cầu tôi đặt vào đường dẫn docs thích hợp hoặc đọc file đã copy; không giả định đã đọc.

## Hệ quy tắc triển khai

- KHÔNG tạo app mới, KHÔNG tái cấu trúc toàn bộ repo hoặc thay framework.
- KHÔNG tạo OAuth flow/client GSC/GA4 mới nếu codebase đã có.
- KHÔNG tự hardcode GA4/GSC properties hoặc dữ liệu Tâm Đức vào production.
- KHÔNG tự commit, push, deploy, thêm service trả phí hay migration phá dữ liệu.
- Không dùng AI để đoán missing GA4 metrics hay giả lập AI citations/visibility.
- Tôn trọng conventions, design system, auth, project-scoping, tests, caching và logging sẵn có.
- Phản biện spec nếu phát hiện giới hạn API, incompatibility hay xung đột thực tế trong repo. Báo cáo bằng chứng trước khi thay đổi thiết kế.

## PHASE 0 (BẮT BUỘC): Repo Discovery — chưa viết tính năng

1. Đọc toàn bộ cấu trúc liên quan đến Report module, GA4/GSC integration, OAuth/token refresh, projects/properties, backend/data transformations, UI components, test setup.
2. Tạo `REPO_DISCOVERY_REPORT.md` gồm:
   - Actual stack, architecture, routes/services, auth and storage
   - Reusable GA4/GSC functions
   - Required files changes, proposed module structure, data flow
   - GA4 metrics/dimensions metadata and compatibility verification plan
   - How to implement correct aggregate metrics (NOT sum of rates/averages)
   - GA4 AI Assistants channel fallback strategy, GSC Web vs Generative AI API boundary
   - Risks, missing data, staged plan, specific tests & acceptance checklist
3. Nếu codebase khác giả định spec, ưu tiên codebase thật; ghi rõ thiết kế điều chỉnh và lý do.
4. Kết thúc phase bằng report để tôi review. **Không tự chuyển sang coding** khi Phase 0 chưa được review.

## IMPLEMENTATION ROUNDS (SAU KHI PHASE 0 ĐƯỢC CHẤP NHẬN)

- R1: GA4 core analytics engine + classifier + unit/integration tests.
- R2: Executive Overview & AI Sources UI, có API integration và error/empty states.
- R3: Landing Pages & Geography, filters, trend, CSV export.
- R4: GSC Web context + Opportunities; tuyệt đối không đổi label GSC Web sang AI-only impressions.
- R5: Data Quality & QA, end-to-end tests, screenshot/report, fix findings.
- R6 optional: GSC Generative AI import nếu chứng thực được nguồn export và mapping.

## Mỗi round phải trả report

- Changed files (exact paths)
- New/changed contracts/data types
- Google API fields/queries used
- Tests & build commands + PASS/FAIL
- UI evidence/screenshots when possible
- Reconciliation checks, caveats, unknowns
- Next round proposal

**Các semantic rules không được vi phạm:**

1. Session Key Event Rate = phần trăm **sessions có ít nhất 1 key event**. Không được dùng Key Events / Sessions để thay thế.
2. `averageSessionDuration` không SUM across sources.
3. GA4 `AI Assistants` excludes Google AI Overviews/AI Mode; Google AI features are counted under Organic Search, so do not pretend those clicks are identifiable from GA4 source alone.
4. GSC API `type=web` represents total Web Search performance, not AIO-specific data. If dedicated Generative AI report data is unavailable via supported API, show unavailable/manual import option, not 0.
5. All charts use consistent property/date/filter/classification version and show data provenance/quality.

Bắt đầu bằng **Phase 0 only**. Không viết production code trong phản hồi đầu tiên.
