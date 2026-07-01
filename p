You are working inside the existing Finora codebase.

Phase 1 — Workspace Foundation is complete.
Phase 2 — Document Upload + Viewer is complete.
Phase 3 — Workflow Engine + Recipes + Real Event Replay is complete.
Phase 4 — Document Intelligence Foundation is complete.

Now implement ONLY:

PHASE 5 — Courier Settlement Read-Only Analysis

This phase adds a real read-only courier settlement analysis workflow.

It must use existing uploaded documents and DocumentExtractionResult from Phase 4.

It must parse courier settlement rows from extraction results, match them against existing Finora orders in read-only mode, detect settlement issues, calculate read-only financial preview summaries, and show everything inside the LEON Workspace.

This phase must NOT post anything.
This phase must NOT mark orders as paid.
This phase must NOT execute shipping reports.
This phase must NOT create real accounting entries.
This phase must NOT modify inventory.
This phase must NOT mutate any operational business records.

============================================================
PHASE 5 OBJECTIVE
============================================================

Build the first real business workflow on top of the LEON Workspace:

Courier Settlement Read-Only Analysis

The workflow should support this user journey:

1. User opens /workspace/.
2. User uploads a courier settlement PDF/image.
3. User clicks "فهم المستند" or starts "كشف تسديد شركة توصيل".
4. Document Intelligence runs if needed.
5. System identifies or confirms document kind = courier_settlement.
6. System parses raw courier rows from extracted tables/text.
7. System normalizes:
   - order number
   - customer name
   - collected amount
   - delivery fee
   - net amount if present
   - date if present
   - courier company name if present
8. System matches each row against existing Finora orders/invoices in read-only mode.
9. System detects issues:
   - order in statement but not found in Finora
   - duplicated row in statement
   - amount mismatch
   - delivery fee mismatch
   - order already settled/paid
   - order status incompatible
   - returned/cancelled order included as delivered
   - wrong or unknown courier company
   - customer name mismatch
   - date out of expected range
   - negative or suspicious profit if profit data is safely available read-only
10. System calculates summary:
   - total rows
   - matched rows
   - issue rows
   - duplicate rows
   - total collected amount
   - total delivery fees
   - expected net amount
   - unmatched amount
   - total variance
11. System opens smart windows:
   - Courier Settlement Analysis window
   - Courier Rows table
   - Issues window
   - Financial Preview window
12. System streams report lines gradually.
13. System moves LEON avatar according to steps.
14. System persists analysis results and audit events.
15. User can refresh session and see analysis results again.
16. No posting button should execute anything in this phase.
17. If an approval panel appears, it must be clearly labeled as read-only / disabled / future phase.

============================================================
STRICT SAFETY RULES
============================================================

1. No accounting posting.
2. No inventory posting.
3. No order mutation.
4. No invoice mutation.
5. No product mutation.
6. No purchase mutation.
7. No shipping report execution.
8. No account transaction creation.
9. No expense creation.
10. No JournalEntry creation.
11. Do not call delivery_agent.execute_report.
12. Do not call shipping.settle_order.
13. Do not call purchases._create_purchase_from_payload.
14. Do not update Invoice.status.
15. Do not update Invoice.payment_status.
16. Do not update Invoice.paid_amount.
17. Do not update Product.quantity.
18. Do not update ShippingReport.is_executed.
19. Do not mutate AccountTransaction, Expense, JournalEntry.
20. Do not touch modules/publisher/**.
21. No OpenAI/LLM calls.
22. Matching must be deterministic and explainable.
23. All persisted data must be workspace analysis data only.
24. Every analysis step must write WorkspaceAuditEvent.
25. Every API endpoint must verify session/document access.
26. Every business query must be read-only.
27. The UI must clearly say:
    "هذه معاينة قراءة فقط. لم يتم تسديد أو ترحيل أي طلب."

============================================================
CURRENT STATE
============================================================

Existing backend includes:

modules/workspace/
  models/
    workspace_session.py
    workspace_audit_event.py
    workspace_document.py
    document_extraction_result.py

  services/
    session_service.py
    event_bus.py
    document_storage_service.py
    file_validation_service.py
    workflow_engine.py
    window_orchestrator.py
    workflow_registry.py
    workflow_context.py
    workflow_errors.py
    schema_guard.py
    document_intelligence/
      document_classifier_service.py
      document_text_extraction_service.py
      document_table_extraction_service.py
      document_normalization_service.py
      document_intelligence_service.py

  recipes/
    mock_workspace_recipe.py
    unknown_document_recipe.py
    courier_settlement_recipe.py
    return_statement_recipe.py
    purchase_invoice_recipe.py

  api/
    session_api.py
    stream_api.py
    document_api.py
    workflow_api.py
    document_intelligence_api.py

Existing frontend includes:

static/workspace/js/
  workspace-app.js
  session-store.js
  event-stream.js
  workspace-canvas.js
  window-manager.js
  leon-avatar.js
  upload-manager.js
  workflow-client.js
  document-intelligence-client.js
  session-timeline.js
  windows/
    live-report-window.js
    document-viewer-window.js
    assistant-notes-window.js
    approval-panel-window.js
    workflow-selector-window.js
    session-timeline-window.js
    document-intelligence-window.js
    raw-table-preview-window.js

Existing behavior:

- Workspace opens.
- Session works.
- SSE replay works.
- PDF/image upload works.
- Document preview persists.
- Document Intelligence can classify/extract/normalize.
- Recipes can run.
- No business mutations exist.

Do not rewrite previous phases.
Extend them.

============================================================
FILES TO CREATE
============================================================

Create backend files:

modules/workspace/models/courier_statement_analysis.py
modules/workspace/models/courier_statement_analysis_row.py
modules/workspace/models/courier_statement_analysis_issue.py

modules/workspace/services/courier_settlement/
  __init__.py
  courier_statement_parser.py
  courier_order_matcher.py
  courier_issue_detector.py
  courier_financial_preview_service.py
  courier_readonly_analysis_service.py
  courier_analysis_errors.py

modules/workspace/api/courier_analysis_api.py

Create frontend files:

static/workspace/js/courier-analysis-client.js

static/workspace/js/windows/courier-settlement-analysis-window.js
static/workspace/js/windows/courier-rows-window.js
static/workspace/js/windows/courier-issues-window.js
static/workspace/js/windows/financial-preview-window.js

Create tests:

tests/workspace/test_courier_statement_parser.py
tests/workspace/test_courier_order_matcher.py
tests/workspace/test_courier_issue_detector.py
tests/workspace/test_courier_financial_preview.py
tests/workspace/test_courier_readonly_analysis_service.py
tests/workspace/test_courier_analysis_api.py
tests/workspace/test_courier_workflow_readonly.py

If naming conventions differ, adapt to existing project style.

============================================================
FILES TO MODIFY
============================================================

Modify carefully:

modules/workspace/__init__.py
  - register courier analysis API

modules/workspace/models/__init__.py
  - export courier analysis models if required

modules/workspace/services/schema_guard.py
  - create courier analysis tables safely

modules/workspace/services/window_orchestrator.py
  - support new window types:
    courier_settlement_analysis
    courier_rows
    courier_issues
    financial_preview

modules/workspace/services/workflow_engine.py
  - register/call courier read-only handler if needed

modules/workspace/recipes/courier_settlement_recipe.py
  - replace placeholder flow with read-only analysis steps
  - keep final state completed or waiting_review
  - no posting

modules/workspace/api/document_intelligence_api.py
  - no major changes unless needed

static/workspace/js/workspace-app.js
  - integrate courier-analysis-client
  - optional button:
    "تحليل كشف التسديد قراءة فقط"

static/workspace/js/event-stream.js
  - handle new events:
    courier.analysis.started
    courier.rows.parsed
    courier.matching.started
    courier.row.matched
    courier.issues.detected
    courier.financial_preview.ready
    courier.analysis.completed
    courier.analysis.failed

static/workspace/js/window-manager.js
  - register new window types

static/workspace/css/workspace.css
  - add styles for courier tables, issue badges, financial preview cards

modules/workspace/README.md
  - update manual tests

Do not modify business modules except read-only imports/queries if needed.

============================================================
DATABASE MODELS
============================================================

Add only workspace analysis tables.

Do not modify Invoice/Product/Purchase/ShippingReport/AccountTransaction.

------------------------------------------------------------
1. CourierStatementAnalysis
------------------------------------------------------------

Suggested fields:

- id: string UUID primary key
- session_id: string required
- document_id: string required
- extraction_result_id: string nullable
- tenant_slug: string nullable/required depending current pattern
- user_id: nullable
- status: string
  - pending
  - parsing
  - matching
  - issues_detected
  - completed
  - failed
- courier_company_id: nullable
- courier_company_name_detected: string nullable
- document_kind: string default courier_settlement
- confidence: float default 0
- total_rows: integer default 0
- matched_rows: integer default 0
- issue_rows: integer default 0
- duplicate_rows: integer default 0
- total_collected_amount: integer default 0
- total_delivery_fees: integer default 0
- expected_net_amount: integer default 0
- unmatched_amount: integer default 0
- total_variance_amount: integer default 0
- summary_json: JSON/Text
- metadata_json: JSON/Text
- error_message: Text nullable
- created_at
- updated_at

------------------------------------------------------------
2. CourierStatementAnalysisRow
------------------------------------------------------------

Suggested fields:

- id: string UUID primary key
- analysis_id: string required
- row_index: integer
- source_table_index: integer nullable
- source_page: integer nullable
- raw_row_json: JSON/Text
- raw_order_number: string nullable
- normalized_order_number: string nullable
- customer_name: string nullable
- customer_phone: string nullable
- collected_amount: integer nullable
- delivery_fee: integer nullable
- net_amount: integer nullable
- statement_date: string nullable
- matched_invoice_id: integer/string nullable depending Invoice.id type
- match_score: float default 0
- match_status: string
  - matched
  - review
  - unmatched
  - duplicate
  - ignored
- match_reasons_json: JSON/Text
- warnings_json: JSON/Text
- issues_json: JSON/Text
- created_at
- updated_at

------------------------------------------------------------
3. CourierStatementAnalysisIssue
------------------------------------------------------------

Suggested fields:

- id: string UUID primary key
- analysis_id: string required
- row_id: string nullable
- issue_type: string
- severity: string
  - info
  - warning
  - error
  - critical
- message: string
- details_json: JSON/Text
- created_at

Indexes:

- analysis_id
- normalized_order_number
- matched_invoice_id
- issue_type

============================================================
COURIER ROW PARSER
============================================================

Implement CourierStatementParser.

Input:

- DocumentExtractionResult
- tables_json
- extracted_text
- normalized_entities_json

Output:

{
  "rows": [
    {
      "row_index": 1,
      "source_table_index": 0,
      "source_page": 1,
      "raw_row": [...],
      "raw_order_number": "#10248",
      "normalized_order_number": "10248",
      "customer_name": "محمد علي",
      "customer_phone": null,
      "collected_amount": 560000,
      "delivery_fee": 10000,
      "net_amount": 550000,
      "statement_date": "2026-07-01",
      "confidence": 0.78,
      "warnings": []
    }
  ],
  "warnings": []
}

Parsing approach:

1. Prefer raw tables from DocumentExtractionResult.tables_json.
2. If tables exist:
   - detect likely headers.
   - map columns by keywords.
   - parse rows.
3. If no tables:
   - fallback to text line heuristic.
4. Normalize every cell through DocumentNormalizationService.
5. Detect columns using Arabic and English keywords.

Column keyword examples:

Order number:
- رقم الطلب
- رقم الفاتورة
- الطلب
- order
- invoice
- tracking
- awb

Customer:
- العميل
- الزبون
- الاسم
- customer
- name

Phone:
- الهاتف
- الموبايل
- phone
- mobile

Collected amount:
- المبلغ
- المبلغ المحصل
- المحصل
- قيمة الطلب
- total
- amount
- collected
- COD

Delivery fee:
- اجور التوصيل
- أجور التوصيل
- التوصيل
- كلفة التوصيل
- delivery fee
- shipping fee
- fee

Net:
- الصافي
- net

Date:
- التاريخ
- date

Rules:

- Ignore obvious header rows.
- Ignore empty rows.
- A valid courier row should usually have:
  - order number or customer phone
  - and at least one amount
- If order number missing but phone + amount exists, keep row as review.
- Do not drop ambiguous rows; mark warnings.

============================================================
ORDER MATCHER — READ ONLY
============================================================

Implement CourierOrderMatcher.

Input:

- parsed row
- current tenant DB session
- optional courier company context

Output:

{
  "matched_invoice_id": 123,
  "score": 92,
  "status": "matched",
  "reasons": [
    "order_number_exact",
    "amount_matches"
  ],
  "warnings": []
}

Important:

- Query Invoice / Order model read-only.
- Do not mutate results.
- Do not call update methods.
- Do not commit business changes.

First inspect actual model names/fields.

Likely Finora uses Invoice + OrderItem.
Verify:

- Invoice.id
- Invoice.order_number
- Invoice.customer_name
- Invoice.customer_phone or customer relation
- Invoice.total or total_amount or final_total
- Invoice.status
- Invoice.payment_status
- Invoice.shipping_company_id or related field
- Invoice.created_at
- Invoice.delivery_fee if exists

If fields differ, adapt safely.

Matching scoring suggested:

- exact normalized order number match: +55
- Invoice.id numeric equals normalized order number: +45
- customer phone last 8 digits match: +20
- customer name fuzzy/simple normalized includes: +10
- collected amount matches invoice total ± 1% or ± 1000 IQD: +20
- date within ±7 days: +5
- courier company matches if available: +10

Score thresholds:

- score >= 75: matched
- 50 <= score < 75: review
- score < 50: unmatched

Fuzzy matching:

- Prefer existing library if installed.
- If no rapidfuzz installed, use Python difflib safely.
- Do not add heavy dependencies unless already planned.

Return top candidates for review:

{
  "top_candidates": [
    {"invoice_id": 1, "score": 68, "reasons": [...]}
  ]
}

============================================================
ISSUE DETECTOR
============================================================

Implement CourierIssueDetector.

Input:

- analysis rows after matching
- invoice snapshots
- analysis summary

Output:

- list of issue objects

Issue types:

1. ORDER_NOT_FOUND
   - row unmatched

2. DUPLICATE_ORDER_IN_STATEMENT
   - same normalized_order_number appears more than once

3. AMOUNT_MISMATCH
   - collected amount differs from invoice total beyond tolerance

4. DELIVERY_FEE_MISMATCH
   - if Finora has expected delivery fee

5. ORDER_ALREADY_SETTLED
   - if invoice/payment status indicates already paid/settled

6. INVALID_ORDER_STATUS
   - cancelled/returned/rejected order appears as delivered/settled

7. CUSTOMER_NAME_MISMATCH
   - if row customer name conflicts heavily

8. DATE_OUT_OF_RANGE
   - if statement date far from order creation/delivery date

9. UNKNOWN_COURIER_COMPANY
   - if courier company not detected or not selected

10. NEGATIVE_PROFIT_OR_SUSPICIOUS_MARGIN
   - only if profit can be read safely from existing calculations
   - if not available, skip with warning

Severity rules:

- critical:
  duplicated paid row, already settled, severe amount mismatch
- error:
  order not found, invalid status
- warning:
  delivery fee mismatch, name mismatch, date issue
- info:
  low confidence match

Every issue must include:

- issue_type
- severity
- row_id if applicable
- message in Arabic
- details_json

============================================================
FINANCIAL PREVIEW — READ ONLY
============================================================

Implement CourierFinancialPreviewService.

Purpose:

Show what the settlement looks like financially without posting.

Input:

- analysis rows
- matched invoice snapshots
- issues

Output:

{
  "total_rows": 50,
  "matched_rows": 47,
  "review_rows": 2,
  "unmatched_rows": 1,
  "total_collected_amount": 25840000,
  "total_delivery_fees": 1250000,
  "expected_net_amount": 24590000,
  "issue_amount": 560000,
  "variance_amount": 20000,
  "safe_to_post_rows": 47,
  "blocked_rows": 3,
  "warnings": [],
  "posting_preview": {
    "readonly": true,
    "message": "هذه معاينة فقط. لم يتم إنشاء أي قيد أو تسديد."
  }
}

Rules:

1. Use row collected_amount and delivery_fee from statement.
2. If invoice total exists, compare to collected amount.
3. Do not create AccountTransaction.
4. Do not create Expense.
5. Do not create ShippingReport.
6. Do not update paid status.
7. If COGS/profit calculations are easily available read-only, include optional profit preview.
8. If not safe/easy, skip profit preview and add warning:
   "تحليل الربح التفصيلي غير مفعّل في هذه المرحلة."

============================================================
READ-ONLY ANALYSIS SERVICE
============================================================

Implement CourierReadonlyAnalysisService.

Main method:

analyze(session_id, document_id=None)

Flow:

1. Load session.
2. Determine active document:
   - explicit document_id if provided
   - latest uploaded document in session otherwise
3. Ensure DocumentExtractionResult exists:
   - if not, call DocumentIntelligenceService
   - if exists, reuse it
4. Verify document kind:
   - if courier_settlement confidence >= 0.55, proceed
   - if unknown or low confidence, proceed with warning but do not fail hard
5. Create CourierStatementAnalysis status parsing.
6. Emit:
   courier.analysis.started
   report.appended "بدأ تحليل كشف التسديد قراءة فقط..."
7. Parse rows.
8. Persist CourierStatementAnalysisRow records.
9. Emit:
   courier.rows.parsed
   report.appended "تم استخراج X صف من الكشف."
10. Match rows read-only.
11. Update row match fields.
12. Emit:
   courier.matching.started
   courier.row.matched events optionally summarized, not one huge payload
   report.appended "تمت مطابقة الصفوف مع الطلبات قراءة فقط."
13. Detect issues.
14. Persist CourierStatementAnalysisIssue records.
15. Emit:
   courier.issues.detected
   report.appended "تم اكتشاف X مشكلة تحتاج مراجعة."
16. Compute financial preview.
17. Update analysis summary fields.
18. Emit:
   courier.financial_preview.ready
   report.appended "تم تجهيز المعاينة المالية بدون ترحيل."
19. Open/update windows:
   - courier_settlement_analysis
   - courier_rows
   - courier_issues
   - financial_preview
20. Mark analysis completed.
21. Emit:
   courier.analysis.completed
22. Return result.

If failure:
- status failed
- persist error
- emit courier.analysis.failed
- do not mutate business records

============================================================
API ENDPOINTS
============================================================

Add under /workspace/api.

POST /workspace/api/sessions/<session_id>/courier-analysis/run

Body optional:

{
  "document_id": "..."
}

Runs read-only analysis.

GET /workspace/api/sessions/<session_id>/courier-analysis

Returns latest analysis for session.

GET /workspace/api/courier-analysis/<analysis_id>

Returns full analysis summary.

GET /workspace/api/courier-analysis/<analysis_id>/rows

Query params:
- status
- issue_type
- page
- page_size

Returns parsed/matched rows.

GET /workspace/api/courier-analysis/<analysis_id>/issues

Returns issue list.

GET /workspace/api/courier-analysis/<analysis_id>/financial-preview

Returns financial preview.

Important:

- All endpoints verify current tenant/user can access the session/analysis.
- No endpoint posts anything.
- No endpoint has approve/commit in Phase 5.

============================================================
WORKFLOW INTEGRATION
============================================================

Update courier_settlement_recipe.py.

Required steps:

start
  - opens document_viewer and live_report
  - report "تم اختيار سير كشف تسديد شركة التوصيل."

ensure_document_intelligence
  - handler: document_intelligence.run_active_document
  - if already completed, reuse
  - opens document_intelligence window

run_readonly_courier_analysis
  - handler: courier_analysis.run_readonly
  - opens courier windows
  - avatar mode matching
  - scan overlay active/preview

review_results
  - opens:
    courier_settlement_analysis
    courier_rows
    courier_issues
    financial_preview
  - status may be completed or waiting_user_review
  - report "هذه نتائج قراءة فقط، لا يوجد ترحيل."

complete
  - avatar success
  - report "اكتمل تحليل كشف التسديد قراءة فقط."

No approval step that posts.
If you keep approval panel, it must be disabled/read-only and say future phase.

Also update unknown_document_recipe:

If user selects courier_settlement after document intelligence, route to courier_settlement recipe or start it.

Keep return and purchase recipes as Phase 4 skeletons.

============================================================
FRONTEND REQUIREMENTS
============================================================

Add Courier Analysis Client:

static/workspace/js/courier-analysis-client.js

Methods:

runForSession(sessionId, documentId=null)
getLatest(sessionId)
getAnalysis(analysisId)
getRows(analysisId, filters={})
getIssues(analysisId)
getFinancialPreview(analysisId)

Add UI button:

- "تحليل كشف التسديد قراءة فقط"
- Show only after document uploaded, or always but validate if no document.

Add windows:

------------------------------------------------------------
1. courier-settlement-analysis-window.js
------------------------------------------------------------

Window type: courier_settlement_analysis

Show summary cards:

- إجمالي الصفوف
- الصفوف المطابقة
- صفوف تحتاج مراجعة
- صفوف غير مطابقة
- الصفوف المكررة
- إجمالي المبلغ المحصل
- إجمالي أجور التوصيل
- الصافي المتوقع
- حالة التحليل

Show disclaimer:

"قراءة فقط — لم يتم تسديد أو ترحيل أي طلب."

------------------------------------------------------------
2. courier-rows-window.js
------------------------------------------------------------

Window type: courier_rows

Show table columns:

- #
- رقم الطلب
- العميل
- المبلغ
- أجور التوصيل
- الصافي
- المطابقة
- النتيجة
- ملاحظات

Support simple filters:

- الكل
- مطابق
- مراجعة
- غير مطابق
- مكرر

No editing in Phase 5.

------------------------------------------------------------
3. courier-issues-window.js
------------------------------------------------------------

Window type: courier_issues

Show grouped issues by severity:

- critical
- error
- warning
- info

Each issue:

- type
- Arabic message
- related order/row
- details

------------------------------------------------------------
4. financial-preview-window.js
------------------------------------------------------------

Window type: financial_preview

Show read-only financial preview:

- إجمالي التحصيل
- إجمالي أجور التوصيل
- الصافي المتوقع
- مبالغ بها مشكلة
- عدد الصفوف الآمنة نظرياً
- عدد الصفوف الممنوعة من الترحيل
- تحذيرات

Show clear notice:

"هذه ليست عملية تسديد. هذه معاينة فقط."

============================================================
FRONTEND EVENT HANDLING
============================================================

Update event-stream.js handlers for:

courier.analysis.started
courier.rows.parsed
courier.matching.started
courier.row.matched
courier.issues.detected
courier.financial_preview.ready
courier.analysis.completed
courier.analysis.failed

Expected UI behavior:

- courier.analysis.started:
  - avatar mode reading_document/matching
  - report line appended

- courier.rows.parsed:
  - open/update courier_rows
  - report line appended

- courier.issues.detected:
  - open/update courier_issues
  - issue badge on summary

- courier.financial_preview.ready:
  - open/update financial_preview

- courier.analysis.completed:
  - avatar success
  - report line appended

- courier.analysis.failed:
  - avatar error/warning
  - show error in assistant_notes

Avoid sending massive rows in SSE if too large.
For large analyses, send summary then frontend fetches rows through API.

============================================================
WINDOW ORCHESTRATOR INTEGRATION
============================================================

Support new window types:

- courier_settlement_analysis
- courier_rows
- courier_issues
- financial_preview

Rules:

1. Do not duplicate windows of same type for same analysis.
2. Preserve document_viewer preview props.
3. Use positions:
   - courier_settlement_analysis: left/top or center-left
   - courier_rows: bottom wide
   - courier_issues: left/bottom or right/bottom
   - financial_preview: center/right
4. Each window event must include:
   - analysisId
   - status
   - summary or fetch URL

============================================================
READ-ONLY BUSINESS QUERY RULES
============================================================

When querying invoices/orders:

- Use SQLAlchemy queries only.
- Do not mutate model instances.
- Do not call db.session.commit after business queries.
- It is acceptable to commit workspace analysis records.
- Keep business objects as snapshots in memory.
- If needed, convert matched invoice into plain dict snapshot:
  {
    "id": ...,
    "order_number": ...,
    "customer_name": ...,
    "total": ...,
    "status": ...,
    "payment_status": ...
  }

Do not store full customer PII in analysis rows unless already needed.
Prefer storing invoice id + minimal snapshot in metadata.

============================================================
MATCHING FIELD DISCOVERY
============================================================

Before implementing CourierOrderMatcher, inspect actual Invoice model.

Find real fields for:

- id
- order number
- customer name
- customer phone
- total/final amount
- status
- payment status
- shipping company
- delivery fee
- created/delivery date

If fields differ, implement a safe adapter:

InvoiceSnapshotAdapter

Methods:

from_invoice(invoice) -> dict
get_order_number(invoice)
get_customer_name(invoice)
get_customer_phone(invoice)
get_total_amount(invoice)
get_status(invoice)
get_payment_status(invoice)
get_delivery_fee(invoice)
get_created_at(invoice)

This prevents scattered field assumptions.

============================================================
TOLERANCES
============================================================

Amount tolerance:

- exact match preferred
- acceptable if absolute difference <= 1000 IQD
- or relative difference <= 1%

Delivery fee tolerance:

- absolute difference <= 1000 IQD

Date tolerance:

- +/- 7 days

Name matching:

- normalize Arabic text
- exact contains or difflib ratio
- do not rely on name alone for automatic matching

Phone matching:

- last 8 digits if available

============================================================
TESTS
============================================================

Add tests.

Required parser tests:

1. Parses row with:
   ["#10248", "محمد علي", "560,000", "10,000"]
   into normalized order 10248, collected 560000, fee 10000.

2. Ignores header rows.

3. Keeps ambiguous rows with warnings.

Required matcher tests:

4. Exact order number match gets score >= 75.

5. Amount mismatch creates warning or issue.

6. Unknown order returns unmatched.

7. Duplicate order rows detected.

Required issue tests:

8. ORDER_NOT_FOUND issue.

9. DUPLICATE_ORDER_IN_STATEMENT issue.

10. AMOUNT_MISMATCH issue.

11. INVALID_ORDER_STATUS issue for returned/cancelled order if model supports statuses.

Required financial preview tests:

12. Correct total_collected_amount.

13. Correct total_delivery_fees.

14. Correct expected_net_amount.

15. Safe_to_post_rows excludes issue rows.

Required service/API tests:

16. Read-only analysis creates CourierStatementAnalysis.

17. Analysis rows are persisted.

18. Issues are persisted.

19. Events are emitted:
    courier.analysis.started
    courier.rows.parsed
    courier.issues.detected
    courier.financial_preview.ready
    courier.analysis.completed

20. API returns latest analysis.

21. API rows pagination works.

22. No business records are mutated.

23. Existing Phase 1–4 tests still pass.

If full Invoice fixtures are hard, mock InvoiceSnapshotAdapter for unit tests and add one integration test with actual Invoice model.

============================================================
MANUAL TEST CHECKLIST
============================================================

Update modules/workspace/README.md.

Manual test:

1. Open /workspace/.
2. Upload courier settlement PDF/image.
3. Click "فهم المستند".
4. Confirm document kind is courier_settlement or manually start courier workflow.
5. Click "تحليل كشف التسديد قراءة فقط".
6. Confirm report shows:
   - بدأ تحليل كشف التسديد قراءة فقط
   - تم استخراج الصفوف
   - تمت المطابقة قراءة فقط
   - تم اكتشاف المشاكل
   - تم تجهيز المعاينة المالية
7. Confirm LEON moves and speaks.
8. Confirm courier summary window appears.
9. Confirm courier rows table appears.
10. Confirm issues window appears.
11. Confirm financial preview appears.
12. Refresh with ?session=<id>.
13. Confirm analysis result persists.
14. Confirm no duplicate report lines.
15. Check database:
   - Invoice unchanged
   - Product unchanged
   - ShippingReport unchanged
   - AccountTransaction unchanged

============================================================
ACCEPTANCE CRITERIA
============================================================

Phase 5 is complete only when:

1. /workspace/ still opens.
2. Upload/preview still works.
3. Document Intelligence still works.
4. Workflow runtime still works.
5. CourierStatementAnalysis models exist.
6. CourierStatementParser parses raw rows.
7. CourierOrderMatcher matches existing invoices read-only.
8. CourierIssueDetector detects issue types.
9. CourierFinancialPreviewService calculates read-only summary.
10. CourierReadonlyAnalysisService runs full read-only analysis.
11. Results persist and restore after refresh.
12. New courier windows render results.
13. Events persist and stream.
14. API endpoints return analysis/rows/issues/financial preview.
15. No posting exists.
16. No approval commit exists.
17. No business records are modified.
18. No OpenAI/AI call exists.
19. modules/publisher/** untouched.
20. Tests pass.

============================================================
OUTPUT REQUIRED AFTER IMPLEMENTATION
============================================================

After implementing Phase 5, report:

1. Created files.
2. Modified files.
3. Database/schema changes.
4. Courier parser behavior.
5. Matcher behavior and actual Invoice fields used.
6. Issue types implemented.
7. Financial preview behavior.
8. API endpoints added.
9. Frontend windows added.
10. Event types added.
11. Test results.
12. Manual testing instructions.
13. Known limitations.
14. Safety confirmation:
   - no posting
   - no settlement
   - no order mutation
   - no inventory mutation
   - no accounting mutation
   - no business data mutation
   - no AI calls
15. Next recommended task.

Recommended next task after Phase 5:

Phase 6 — Courier Settlement Review & Manual Corrections
- allow user to resolve unmatched rows manually
- choose correct invoice candidate
- ignore row
- mark duplicate
- adjust statement row classification
- still no posting

Do NOT recommend posting yet unless read-only analysis and manual correction workflow are stable.

Start implementing Phase 5 only.