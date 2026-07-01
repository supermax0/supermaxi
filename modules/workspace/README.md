# Finora AI Workspace

## Phase 1 + 2 + 3 + 4 + 5

### الوصول

- **Stable:** `http://localhost:5008/workspace/`
- **Dev:** `http://localhost:5008/workspace/?dev=1` (يعرض زر «الخطوة التالية»)
- **استعادة جلسة:** `http://localhost:5008/workspace/?session=<uuid>`

يتطلب Enterprise + تسجيل دخول.

---

## Phase 5 — Courier Settlement Read-Only Analysis

تحليل كشف تسديد شركة التوصيل **قراءة فقط** — بدون ترحيل، بدون تعديل فواتير، بدون AI.

### زر جديد

| الزر | الوظيفة |
|------|---------|
| **تحليل كشف التسديد قراءة فقط** | يشغّل التحليل بعد فهم المستند (أو يعيد استخدام نتيجة الاستخراج) |

### API

| Method | Path |
|--------|------|
| POST | `/workspace/api/sessions/{id}/courier-analysis/run` |
| GET | `/workspace/api/sessions/{id}/courier-analysis` |
| GET | `/workspace/api/courier-analysis/{id}` |
| GET | `/workspace/api/courier-analysis/{id}/rows` |
| GET | `/workspace/api/courier-analysis/{id}/issues` |
| GET | `/workspace/api/courier-analysis/{id}/financial-preview` |

### نوافذ جديدة

- `courier_settlement_analysis` — ملخص الصفوف والمطابقة والمشاكل
- `courier_rows` — صفوف الكشف مع حالة المطابقة
- `courier_issues` — المشاكل مجمّعة حسب الخطورة
- `financial_preview` — معاينة مالية فقط (ليست تسديداً)

### أحداث SSE

`courier.analysis.started`, `courier.rows.parsed`, `courier.matching.started`, `courier.row.matched`, `courier.issues.detected`, `courier.financial_preview.ready`, `courier.analysis.completed`, `courier.analysis.failed`

### اختبار يدوي (Phase 5)

1. افتح `/workspace/`
2. ارفع PDF كشف تسديد
3. اضغط **فهم المستند** ثم **تحليل كشف التسديد قراءة فقط**
4. أو شغّل workflow `courier_settlement`
5. تأكد من نوافذ الصفوف والمشاكل والمعاينة المالية
6. رسالة التقرير: «هذه نتائج قراءة فقط، لا يوجد ترحيل»
7. Refresh مع `?session=` — النتائج محفوظة
8. تأكد أن فواتير Finora لم تتغير

### قيود Phase 5

- لا ترحيل · لا تسديد · لا تعديل فواتير/مخزون/حسابات
- لا موافقة تنفّذ ترحيلاً
- لا استدعاء OpenAI

---

## Phase 4 — Document Intelligence

### زر جديد

| الزر | الوظيفة |
|------|---------|
| **فهم المستند** | يشغّل التحليل الأولي على المستند النشط (بدون AI وبدون ترحيل) |

### API

| Method | Path |
|--------|------|
| POST | `/workspace/api/documents/{id}/intelligence/run` |
| GET | `/workspace/api/documents/{id}/intelligence` |
| GET | `/workspace/api/sessions/{id}/intelligence` |
| POST | `/workspace/api/sessions/{id}/intelligence/run-active` |

### نوافذ جديدة

- `document_intelligence` — نوع المستند، الثقة، الإشارات، عينة النص
- `raw_table_preview` — جداول خام (حتى 100 صف)

### أحداث SSE

`document.intelligence.started`, `document.text.extracted`, `document.tables.extracted`, `document.normalized`, `document.classified`, `document.intelligence.completed`, `document.intelligence.failed`

### اختبار يدوي (Phase 4)

1. افتح `/workspace/`
2. ارفع PDF أو صورة
3. اضغط **فهم المستند**
4. تأكد من رسائل التقرير: بدأت القراءة → استخراج النص → الجداول → التصنيف
5. تأكد من نافذة فهم المستند + LEON في وضع القراءة
6. Refresh مع `?session=` — النتائج محفوظة
7. جرّب نصوص: كشف تسديد / كشف راجع / فاتورة شراء / مستند غير معروف
8. تأكد أن بيانات Finora (فواتير، مشتريات، مخزون) لم تتغير

---

## Phase 3 — Workflow Engine

### أزرار الشريط

| الزر | الوظيفة |
|------|---------|
| رفع مستند | Phase 2 — رفع PDF/صورة |
| تشغيل Workflow | يبدأ `mock_workspace` حتى موافقة أو اكتمال |
| اختيار نوع العمل | يبدأ `unknown_document` + نافذة الاختيار |
| تشغيل تجربة | يشغّل mock كاملاً مع موافقة تلقائية (توافق Phase 1) |
| الخطوة التالية | dev فقط — خطوة واحدة |

### API Workflow

| Method | Path |
|--------|------|
| GET | `/workspace/api/sessions/{id}/workflow` |
| POST | `/workspace/api/sessions/{id}/workflow/start` |
| POST | `/workspace/api/sessions/{id}/workflow/next` |
| POST | `/workspace/api/sessions/{id}/workflow/input` |
| POST | `/workspace/api/sessions/{id}/workflow/approval` |
| POST | `/workspace/api/sessions/{id}/workflow/cancel` |
| POST | `/workspace/api/sessions/{id}/run-mock` (legacy) |

### أنواع Workflow (هيكل فقط في Phase 3)

- `mock_workspace` — تجربة كاملة + موافقة تجريبية
- `unknown_document` — اختيار يدوي لنوع العمل
- `courier_settlement` — تحليل قراءة فقط (Phase 5)
- `return_statement` — هيكل بدون باركود
- `purchase_invoice` — هيكل بدون مطابقة منتجات

### Event Replay

- SSE: `GET /workspace/api/sessions/{id}/stream?since=<event_id>`
- Header: `Last-Event-ID`
- localStorage: `workspace:lastEventId:<session_id>`
- تقارير مكررة تُمنع عبر `event_id`

---

## اختبار يدوي (Phase 3)

1. افتح `/workspace/`
2. ارفع PDF
3. اضغط **تشغيل Workflow**
4. راقب التقرير + حركة LEON + خط المسح
5. عند فتح **موافقة مطلوبة** — اضغط موافقة
6. تأكد من اكتمال الجلسة
7. Refresh مع `?session=` — لا تكرار أسطر التقرير
8. **اختيار نوع العمل** → اختر كشف تسوية → رسائل placeholder فقط
9. تأكد أن بيانات Finora لم تتغير

---

## اختبارات

```bash
python tests/workspace/test_document_normalization_service.py
python tests/workspace/test_document_classifier_service.py
python tests/workspace/test_document_text_extraction_service.py
python tests/workspace/test_document_table_extraction_service.py
python tests/workspace/test_document_intelligence_api.py
python tests/workspace/test_document_intelligence_workflow.py
python tests/workspace/test_workflow_engine.py
python tests/workspace/test_window_orchestrator.py
python tests/workspace/test_event_replay.py
python tests/workspace/test_workflow_api.py
python tests/workspace/test_workspace_session_service.py
python tests/workspace/test_workspace_document_upload.py
python tests/workspace/test_workspace_routes.py
python tests/workspace/test_courier_statement_parser.py
python tests/workspace/test_courier_order_matcher.py
python tests/workspace/test_courier_issue_detector.py
python tests/workspace/test_courier_financial_preview.py
python tests/workspace/test_courier_readonly_analysis_service.py
python tests/workspace/test_courier_analysis_api.py
python tests/workspace/test_courier_workflow_readonly.py
python tests/workspace/test_window_cleanup_on_workflow_start.py
python tests/workspace/test_no_approval_in_readonly_courier.py
python tests/workspace/test_workspace_layout_lifecycle.py
```

---

## تنسيق النوافذ ودورة حياتها (Workspace UX)

- **Layout Director** (`static/workspace/js/workspace-layout-director.js`): يوزّع النوافذ على مناطق حتمية ومتجاوبة:
  - العمود الأيسر: `courier_settlement_analysis` / `live_report` / `document_intelligence` / `courier_issues`
  - العمود الأيمن: `document_viewer` / `assistant_notes`
  - الشريط السفلي: `courier_rows` / `financial_preview` / `raw_table_preview`
  - مركز (Modal فوق الكل): `workflow_selector` / `approval_panel`
- النوافذ **مفردة (singleton)** حسب الهوية (`type + documentId/analysisId`)؛ لا تكرار.
- بدء أي سير عمل يستدعي `WindowOrchestrator.cleanup_for_workflow_start` فيُبقي `document_viewer` و`live_report` ويغلق النوافذ الانتقالية القديمة (منها `approval_panel`).
- تحليل كشف التسديد **قراءة فقط** لا يفتح `approval_panel` إطلاقاً؛ ويغلق أي لوحة موافقة قديمة عند البدء.
- عند إعادة التحميل: `GET /sessions/<id>` يستدعي `normalize_windows` لإزالة المكررات ولوحة الموافقة القديمة، ويُعاد بثّ التقرير من الصفر إذا كان فارغاً.
- LEON يبقى في الممر الأوسط بين العمودين ولا يغطّي أي نافذة، وطبقته أسفل النوافذ/المودال.

### اختبار يدوي
1. افتح `/workspace/` وارفع مستنداً → المعاينة يمين، التقرير يسار، LEON في الوسط لا يغطّي المعاينة.
2. اضغط **فهم المستند** → تفتح نافذة الفهم بلا لوحة موافقة.
3. اضغط **تشغيل تجربة** ثم وافق/تجاهل (لوحة الموافقة تظهر في التجربة فقط).
4. اضغط **تحليل كشف التسديد قراءة فقط** → لا تظهر لوحة موافقة، وتُغلق نوافذ التجربة القديمة، وتفتح نوافذ الكشف في مناطقها.
5. حدّث الصفحة مع `?session=<id>` → تخطيط نظيف بلا تكرار وبلا أسطر تقرير مكررة.

---

## قيود

- لا OCR · لا AI · لا ترحيل فعلي
- تحليل كشف التسديد قراءة فقط في Phase 5

## التالي

**Phase 6 — Courier Settlement Review & Manual Corrections**
- حل الصفوف غير المطابقة يدوياً
- اختيار فاتورة مرشحة / تجاهل صف / تعليم مكرر
- ما زال بدون ترحيل
