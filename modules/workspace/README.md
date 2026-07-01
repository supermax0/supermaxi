# Finora AI Workspace — Phase 1

## الوصول

- **Stable:** `http://localhost:5008/workspace/`
- **Dev shell:** `http://localhost:5008/workspace/?dev=1`
- **استعادة جلسة:** `http://localhost:5008/workspace/?session=<uuid>`

يتطلب:
- تسجيل دخول
- خطة **Enterprise** (`ai_workspace` feature)

## تجربة Mock Workflow

1. افتح `/workspace/`
2. اضغط **تشغيل تجربة**
3. راقب:
   - بث أسطر التقرير في النافذة اليسرى
   - خط المسح في معاينة المستند
   - حركة أفاتار LEON
   - فتح نافذة ملاحظات في النهاية

## API (Phase 1)

| Method | Path |
|--------|------|
| POST | `/workspace/api/sessions` |
| GET | `/workspace/api/sessions` |
| GET | `/workspace/api/sessions/{id}` |
| POST | `/workspace/api/sessions/{id}/run-mock` |
| POST | `/workspace/api/sessions/{id}/cancel` |
| GET | `/workspace/api/sessions/{id}/stream` (SSE) |

## اختبارات

```bash
python tests/workspace/test_workspace_routes.py
python tests/workspace/test_workspace_session_service.py
```

## قيود Phase 1

- لا رفع مستندات حقيقية
- لا OCR / AI
- لا ترحيل محاسبي أو مخزني
- SSE in-memory (يعاد البث من DB عند إعادة الاتصال)

## المرحلة التالية

**Phase 2 — Document Upload + Viewer**
