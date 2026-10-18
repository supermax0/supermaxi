# تقرير إكمال منصة الأسنان — FINORA Clinics v28

**التاريخ:** 2026-09-07  
**المصدر:** `docs/guides/2`  
**المخطط:** `clinics-v28-dental-completion`  
**القاعدة:** إعادة استخدام Core الحالي + Specialty Engine + Dental Platform دون نسخ صفحات المرضى/الفوترة/المخزون.

---

## 1. الملفات المعدّلة

- `modules/clinics/models.py`
- `modules/clinics/schema.py`
- `modules/clinics/service.py`
- `modules/clinics/service_dental.py`
- `modules/clinics/service_dental_treatment.py`
- `modules/clinics/service_dental_completion.py` *(جديد)*
- `modules/clinics/service_specialties.py`
- `modules/clinics/service_specialty_registry.py`
- `modules/clinics/service_dashboard.py`
- `modules/clinics/guards.py`
- `modules/clinics/routes.py`
- `static/clinics/clinics.js`
- `static/clinics/services.js`
- `static/clinics/dashboard.js`
- `static/clinics/appointments.js`
- `static/clinics/doctor.js`
- `static/clinics/dental-treatment-plan.js`
- `static/clinics/patient-profile.js`
- `tests/test_clinics_dental_platform.py`
- `tests/test_clinics_phase_h_hardening.py`
- `tests/test_clinics_cardiology.py`
- `tests/test_clinics_backup_restore.py`
- `tests/test_clinics_postgresql_v16_migration.py`

## 2. الملفات الجديدة

- `modules/clinics/service_dental_completion.py`
- `docs/CLINICS_V28_DENTAL_COMPLETION.md`

## 3. Database migrations

لا يوجد Alembic منفصل. الترحيل يتم عبر `ensure_clinics_schema()` (idempotent) عند أول طلب `/clinics/*`.

الإصدار: `clinics-v27-dental-platform` → `clinics-v28-dental-completion`

## 4. الجداول / الأعمدة الجديدة

**جدول جديد**

- `clinic_dental_tooth_event` — تاريخ سن append-only (المصدر التاريخي)، مع بقاء الحالة الحالية في `clinic_dental_tooth_finding`

**أعمدة مضافة**

| جدول | أعمدة |
|------|--------|
| `clinic_settings` | `dental_config_json` |
| `clinic_service` | `requires_tooth`, `allows_multiple_teeth`, `requires_sessions`, `default_sessions` |
| `clinic_appointment` | `treatment_plan_item_id`, `tooth_number` |
| `clinic_invoice` | `treatment_plan_id` |
| `clinic_invoice_item` | `treatment_plan_item_id`, `dental_session_id` |
| `clinic_dental_treatment_plan_item` | `service_id` |

## 5. Routes الجديدة

لا صفحات `/dental/*` مكررة. الإضافات كلها تحت `/clinics/*`.

## 6. API الجديدة

- `GET /clinics/api/patients/<id>/dental-tooth-events`
- `GET /clinics/api/patients/<id>/dental-active-treatments`
- `GET /clinics/api/visits/<id>/dental-complete-preflight`
- `POST /clinics/api/dental-treatment-plans/<id>/invoice`

المستخدم مسبقاً (أُعيد استخدامه): مخطط الأسنان، خطط العلاج، الجلسات، الصور، التقارير، specialty-resolver.

## 7. Permissions الجديدة

لا صلاحيات جديدة. المطلوبة في البرومبت موجودة مسبقاً عبر RBAC الحالي:

`dental.view`, `dental.chart.*`, `dental.treatment_plan.*`, `dental.sessions.*`, `dental.images.*`, `dental.reports.view`

فاتورة الخطة تتطلب `clinics_billing`.

## 8. Specialty Resolver

المسار المركزي: `modules/clinics/service_specialty_registry.py`

```
Visit snapshot → Appointment snapshot → Doctor primary → Clinic primary → general
```

- Alias: `dental` → `dentistry`
- لقطة `specialty_code_snapshot` + `workspace_snapshot` على الموعد والزيارة
- إذا `dental_config.enabled = false` تُطفأ ميزات الأسنان حتى لو الاختصاص dentistry

## 9. Dental Workflow

1. طبيب باختصاص أسنان → الموعد/الزيارة تأخذ snapshot `dentistry`
2. فتح `/clinics/doctor/<visit_id>` يعرض Dental Workspace (مخطط + خطة + جلسات + صور)
3. اختيار سن يسجّل حالة حالية + حدث تاريخي
4. بند خطة يرتبط بنفس العلاج عبر جلسات متعددة (لا علاج جديد لكل جلسة)
5. إكمال الجلسة يستهلك مخزون وصفة الإجراء مرة واحدة عبر النظام الحالي
6. فاتورة الخطة تُنشأ من محرك فواتير Finora (`ClinicInvoice`) وليست دفتراً مستقلاً
7. إنهاء الزيارة لا يغلق خطة العلاج إن بقيت بنود مفتوحة
8. عودة المريض تعرض «متابعة العلاج» من البنود النشطة

## 10. Tests المضافة

في `tests/test_clinics_dental_platform.py`:

- Resolver + snapshot (موجود)
- 3 جلسات على نفس البند + إكمال نهائي يحدّث الحالة (موجود)
- عزل المستأجرين للصور والتقارير (موجود)
- أحداث السن append-only + عزل tenant
- خدمة تتطلب سناً + مدة الموعد من الخدمة
- فاتورة من الخطة + preflight إنهاء الزيارة + عزل tenant

تشغيل محلي: **26 passed**  
`test_clinics_dental_platform.py` + `test_clinics_dental_chart.py` + `test_clinics_dental_treatment_plan.py`

## 11. ما لم يُنفَّذ / حدود متعمدة

- لا نظام فوترة/مخزون/مرضى مستقل للأسنان (م forbidden في البرومبت)
- ترقيم Universal/Palmer مخزَّن في الإعدادات فقط؛ الرسم الحالي يبقى FDI
- محاكاة علاج رسومية ثلاثية الأبعاد غير موجودة (حد معروف سابقاً)
- عارض الصور (تكبير/تدوير/ملء الشاشة) كان موجوداً وأُبقي
- استهلاك المخزون يبقى عبر `ClinicProcedureRecipeItem` وليس جدولاً مكرراً `service_inventory_items`
- صفحات `/dental/patients` لم تُنشأ عمداً

## 12. ما يجب تشغيله

لا أمر ترحيل يدوي. بعد النشر:

1. افتح أي مسار `/clinics/*` حتى يعمل `ensure_clinics_schema()`
2. من الإعدادات: **إضافة الاختصاصات الافتراضية** لتهيئة خدمات الأسنان إن لم تكن موجودة
3. فعّل وحدة الأسنان من إعدادات العيادة إن لزم
4. اربط الطبيب باختصاص الأسنان ثم أنشئ موعداً/زيارة للتحقق من Dental Workspace

---

**النتيجة:** FINORA Clinics يبقى نظاماً واحداً متعدد الاختصاصات. الأسنان أصبحت Specialty Module مكتملاً فوق الـ Core: مخطط، تاريخ أحداث، خطة، جلسات، أشعة، تقارير، فوترة مرتبطة، مواعيد واعية بالأسنان، ولوحة مؤشرات — دون تكرار النظام الأساسي.
