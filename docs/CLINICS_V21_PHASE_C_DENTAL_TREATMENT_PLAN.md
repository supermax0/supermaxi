# Phase C Report — Dental Treatment Plan

**Date:** 2026-09-04  
**Base:** `clinics-v21-dental-chart`  
**Schema:** `clinics-v22-dental-treatment-plan`

## Implemented

- Patient-level dental treatment plans (clinical intent only — no auto invoice/payment/inventory)
- Multi-item plans with tooth or general (full-mouth) items
- Priority, status, estimated sessions/price
- Link items to existing `ClinicVisitProcedure` executions across visits
- Derived progress + estimated vs actual billed/paid (from linked procedures + visit invoices)
- Dental chart drawer: active plan items + “إضافة إلى خطة العلاج”
- Doctor workspace tab **خطة العلاج** (dentistry)
- Patient profile dental section mounts treatment plan panel
- Patient-facing print payload (no cost/commission/audit internals)

## Modified Files

- `modules/clinics/models.py`
- `modules/clinics/schema.py`
- `modules/clinics/service_dental_treatment.py` (new)
- `modules/clinics/service_dental.py` (`validate_tooth_number`)
- `modules/clinics/routes.py`
- `modules/clinics/guards.py`
- `static/clinics/dental-treatment-plan.js` / `.css` (new)
- `static/clinics/dental-chart.js` / `.css`
- `static/clinics/clinics.js`
- `static/clinics/patient-profile.js`
- `templates/clinics/workspace.html`
- `tests/test_clinics_dental_treatment_plan.py` (new)
- `tests/test_clinics_dental_treatment_browser.py` (new)
- `tests/test_clinics_postgresql_release.py` (concurrent link + tables)

## New Models

- `ClinicDentalTreatmentPlan`
- `ClinicDentalTreatmentPlanItem`
- `ClinicDentalTreatmentPlanItemLink` (unique `tenant_id + item + visit_procedure`)

## Database Changes

Three new tables via idempotent `ensure_clinics_schema()` / `CLINIC_MODELS`.

## Migration

Schema bumped to `clinics-v22-dental-treatment-plan`. No fabricated plans for legacy patients. Phase B dental tables retained.

## APIs

- `GET|POST /clinics/api/patients/<id>/dental-treatment-plans`
- `GET|PATCH /clinics/api/dental-treatment-plans/<id>`
- `POST /clinics/api/dental-treatment-plans/<id>/items`
- `PATCH /clinics/api/dental-treatment-plan-items/<id>`
- `POST /clinics/api/dental-treatment-plan-items/<id>/procedure-links`
- `GET /clinics/api/patients/<id>/dental-treatment-plans/tooth/<tooth>`
- `GET /clinics/api/dental-treatment-plans/<id>/print`

## Dental Chart Integration

Tooth drawer shows active plan items for that tooth and quick-add into the plan.

## Treatment Plan UX

Summary cards + item cards; mobile-friendly; RTL layout for plan text (odontogram remains LTR).

## Procedure Integration

Links only — no duplicate procedure engine; inventory unchanged by planning/linking.

## Billing Integration

Estimates are planning-only. Actual billed/paid derived from linked visit procedures + visit invoices when `clinics_billing` is present.

## Patient Profile

Plan panel under **مخطط الأسنان**.

## Printing

Browser print via `/print` payload (clinic, patient, items, estimated total).

## Security

`clinics_clinical` on all plan APIs; billing fields gated by `clinics_billing`.

## Tenant Isolation

All lookups tenant-scoped; cross-tenant IDs raise not-found.

## Doctor Scope

Plans scoped by `created_by_doctor_id`; items/links follow plan ownership; flush guards enforced.

## Financial Permissions

Without billing: clinical plan + estimates visible; `actual_billed` / `paid` / `remaining` omitted.

## Concurrency

Idempotent link + `FOR UPDATE` on item before insert; PG concurrent double-link → single row.

## Performance

Bulk load items + links + procedures + invoices per plan open (no per-item API).

## RTL / Mobile

Plan UI RTL; cards on narrow viewports; browser check at 375px.

## Browser E2E

`test_clinics_dental_treatment_browser.py` — create plan → add tooth 16 root-canal-style item → priority → persist in session.

## Tests

- Unit: create/items/multi-visit links/finance/complete override/tenant/doctor scope/archive/financial redaction/Phase B regression/schema version
- Browser fixture E2E
- PostgreSQL: tables + concurrent unique link

## Known Limitations

- No drag-and-drop reorder
- Appointment “حجز جلسة” not auto-wired (plan does not own scheduling)
- Radiology/attachment association left to existing visit tools
- Pediatrics (Phase D) not started

## Regression Result

- Phase C unit + Phase B dental: **17 passed**
- Browser E2E: **1 passed**
- Full `pytest tests -k "test_clinics_"` — **160 passed / 0 failed** (2026-09-04)

## Next Phase Recommendation

**Phase D — Pediatric Clinical Tools** (structured history, growth measurements, vaccination, development) — after this report is accepted. Do not implement WHO/CDC percentiles until dataset/methodology are defined.
