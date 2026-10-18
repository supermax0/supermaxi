# تقرير تنفيذ توسعة FINORA Clinics للاختصاصات المتعددة

**التاريخ:** 2026-09-05  
**إصدار المنتج:** FINORA Clinics 1.0 RC1  
**الإصدار المخططي الحالي:** `clinics-v26-cardiology-clinical-tools`  
**النطاق:** توسعة تراكمية داخل `business_type = clinics` والمسارات الحالية `/clinics/*`.

## 0. الوضع بعد Phase G/H (v26)

- حزم سريرية مكتملة: أسنان، أطفال، نسائية/توليد، باطنية طولية، قلب (ECG/Echo).
- لا محركات مكررة للاتجاهات/الأدوية المزمنة بعد Phase F/G.
- توحيد ملف المريض + مساحة الطبيب + منع تضخم الشريط الجانبي.
- Phase H: hardening / migration v16→v26 / backup-restore / health / RC docs.

## 1. الوضع بعد التنفيذ (v20 — أساس الاختصاصات)

- `ClinicSettings.organization_mode` هو مصدر الحقيقة لشكل المنشأة: `solo_clinic` | `multi_doctor_clinic` | `medical_center`.
- `ClinicSettings.clinic_type` بقي للتوافق والترحيل فقط؛ لا يُخلط مع حزم الاختصاص (`dental` / `pediatrics` …).
- الاختصاصات تُدار عبر `ClinicSpecialty` + `/clinics/specialties` تحت الإدارة.
- `ClinicDoctorSpecialty` يدعم اختصاصات متعددة مع اختصاص رئيسي واحد كحد أقصى.
- `ClinicAppointment.specialty_id` و`ClinicVisit.specialty_id` / `visit_template_id` مفعّلة.
- نماذج الزيارة ذات الإصدارات: `ClinicVisitTemplate*` + `ClinicVisitFieldValue`.
- ربط الخدمات: `ClinicServiceSpecialty` + `ClinicDoctorService`.
- ربط الإجراءات: `ClinicProcedureSpecialty`.
- قوالب الوصفات: `ClinicPrescriptionTemplate` + `ClinicPrescriptionTemplateItem`.
- مخطط العيادات lazy/idempotent في `schema.py`؛ إصدار حالي `clinics-v26-cardiology-clinical-tools`.

## 2. الموجود الذي أُعيد استخدامه

- نفس `ClinicPatient` ومحركات المواعيد/الزيارة/الفوترة/المختبر/الأشعة/الإجراءات/المتابعات.
- نفس `/clinics/doctors`, `/clinics/appointments`, `/clinics/doctor/<visit_id>`, `/clinics/settings` والحجز العام.
- نفس `ClinicAuditLog` ونمط `tenant_id`.
- نفس جداول الدوام والعمولات و`employee_id`.

## 3. النماذج المُنفَّذة (أسماء الأصناف الفعلية)

- `ClinicSpecialty`
- `ClinicDoctorSpecialty`
- `ClinicVisitTemplate`
- `ClinicVisitTemplateSection`
- `ClinicVisitTemplateField`
- `ClinicVisitFieldValue`
- `ClinicServiceSpecialty`
- `ClinicDoctorService`
- `ClinicProcedureSpecialty`
- `ClinicPrescriptionTemplate`
- `ClinicPrescriptionTemplateItem`

## 4. الترحيل v16 → v20

- مسار الترحيل الحقيقي عبر `ensure_clinics_schema()` (إضافات أعمدة/جداول + `migrate_legacy_specialties`).
- اختبار مأهول على PostgreSQL 16: `tests/test_clinics_postgresql_v16_migration.py` (تشغيل مرتين للتحقق من idempotency).
- قواعد `organization_mode`: لا يُحوَّل إلى `medical_center` لمجرد وجود عدة أطباء؛ أكثر من طبيب → `multi_doctor_clinic` عند غياب قيمة منشأة صريحة.
- تحويل `ClinicDoctor.specialty` النصي إلى `ClinicSpecialty` + رابط رئيسي واحد.
- الزيارات التاريخية المكتملة بلا نموذج تبقى بلا `visit_template_id` مُفبرك.

## 5. الحجز العام

التدفق المُتحقق بالمتصفح:

```text
Specialty → Doctor → Service → Time → Patient → OTP? → Confirm
```

مع إدارة `/book/<slug>/manage/<token>` (إعادة جدولة/إلغاء) بعد rollout الاختصاصات.

## 6. الأمان المالي بعد الاختصاصات

تصنيفات مستخدمة في مصفوفة الصلاحيات:

| Class | أمثلة | بوابة |
|---|---|---|
| transactional_finance | سعر الخدمة للمريض، مبلغ فاتورة، المتبقي | `clinics_billing` لمسارات الدفتر |
| management_finance | إيراد، عمولة طبيب، تسويات، تقارير مالية | `clinics_billing` (+ تقارير تتطلب الاثنين) |
| cost_finance | `purchase_price` / `average_cost` / تقييم المخزون | `purchases.cost.view` أو `clinics_billing` (بدون fallback من المخزون وحده) |

## 7. الاختبارات ذات الصلة

- `tests/test_clinics_specialties.py`
- `tests/test_clinics_release_security.py`
- `tests/test_clinics_financial_auth_matrix.py`
- `tests/test_clinics_booking_live_e2e.py`
- `tests/test_clinics_postgresql_v16_migration.py`
- `tests/test_clinics_postgresql_release.py`
- `tests/test_clinics_report_export_parity.py`
- `tests/test_clinics_query_benchmarks.py`
- `tests/test_clinics_internal_rtl_mobile.py`

## 8. حدود غير حاجزة للإصدار

- Interactive Dental Chart غير منفَّذ.
- منحنيات نمو أطفال مرجعية غير منفَّذة.
- متتبع حمل متقدم غير منفَّذ.

لا تُعرض هذه كميزات جاهزة في الواجهة الحالية.
