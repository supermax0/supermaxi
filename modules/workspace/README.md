# Finora AI Workspace

## Phase 1 + 2 + 3 + 4

### الوصول

- **Stable:** `http://localhost:5008/workspace/`
- **Dev:** `http://localhost:5008/workspace/?dev=1` (يعرض زر «الخطوة التالية»)
- **استعادة جلسة:** `http://localhost:5008/workspace/?session=<uuid>`

يتطلب Enterprise + تسجيل دخول.

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
- `courier_settlement` — هيكل بدون مطابقة/ترحيل
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
```

---

## قيود

- لا OCR · لا AI · لا مطابقة · لا ترحيل
- الموافقة تجريبية فقط

## التالي

**Phase 4 — Document Intelligence Foundation**
