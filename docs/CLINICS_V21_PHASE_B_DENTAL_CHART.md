# Phase B Report — Interactive Dental Chart

**Date:** 2026-09-04  
**Base:** `clinics-v20-concurrency-guards`  
**Schema:** `clinics-v21-dental-chart`

## Implemented

- Visit-scoped interactive FDI odontogram as specialty field type `dental_chart`
- Structured models (no opaque whole-chart JSON): record / tooth finding / tooth↔procedure link
- Permanent, primary, and mixed dentition modes
- Tooth status + multi-surface persistence with visit history integrity
- Patient dental history (current state derived from latest finding per tooth)
- Doctor workspace mount + patient profile **مخطط الأسنان** tab
- Procedure link reuses existing `ClinicVisitProcedure` (no duplicate procedure engine)

## Modified Files

- `modules/clinics/models.py`
- `modules/clinics/schema.py`
- `modules/clinics/service_dental.py` (new)
- `modules/clinics/routes.py`
- `modules/clinics/guards.py`
- `modules/clinics/service_specialties.py`
- `static/clinics/dental-chart.js` (new)
- `static/clinics/dental-chart.css` (new)
- `static/clinics/clinics.js`
- `static/clinics/patient-profile.js`
- `static/clinics/specialty-builder.js`
- `templates/clinics/workspace.html`
- `tests/test_clinics_dental_chart.py` (new)

## New Models

- `ClinicDentalRecord` — unique `tenant_id + visit_id`
- `ClinicDentalToothFinding` — unique per record + tooth; soft-archive via `archived_at`
- `ClinicDentalToothProcedure` — tooth context on existing visit procedures

## Database Changes

New tables created idempotently via `ensure_clinics_schema()` / `CLINIC_MODELS`.

## Migration

Schema version bumped to `clinics-v21-dental-chart`. Existing dentistry visits without a chart open with empty chart (no fabricated history). New dentistry seed templates include `dental_chart`; historical published templates are not rewritten.

## APIs

- `GET /clinics/api/visits/<id>/dental-chart`
- `PUT /clinics/api/visits/<id>/dental-chart/tooth/<tooth_number>`
- `GET /clinics/api/patients/<id>/dental-history`

## Doctor Workspace

Chart mounts from `dental_chart` template fields; dentistry specialty also gets a fallback panel if the published template lacks the field. Odontogram root uses `dir="ltr"` so RTL page direction does not reverse anatomical FDI order. Mobile uses quadrant navigation.

## Patient Profile

Clinical users see tab **مخطط الأسنان** backed by dental-history API.

## Procedure Integration

`link_visit_procedure_id` on tooth upsert creates `ClinicDentalToothProcedure` only; billing/inventory remain on `ClinicVisitProcedure`.

## Security

- `clinics_clinical` required on dental APIs
- Doctor-scope ORM criteria extended to dental models
- Completed visits: chart readable, edits rejected

## Tenant Isolation

All queries filter by `tenant_id`; cross-tenant visit IDs raise not-found.

## RTL / Mobile

- Anatomical LTR odontogram inside RTL workspace
- Quadrant UI under ~900px; tooth hit targets ≥40–52px
- Status badge text (not color alone)

## Performance

Single bulk GET loads all findings + previous-state summary + procedure links for the visit (no per-tooth N+1 API).

## Tests

`tests/test_clinics_dental_chart.py` — validation, history, tenant isolation, completed visit, procedure link, doctor scope, seed field, RTL asset order.

Security + specialties regression: **57 passed** (specialties + release_security + dental).

## Known Limitations

- Treatment plan models deferred to Phase C
- Graphical per-surface tooth SVG deferred; V1 uses tooth select + surface multi-select
- Live Playwright E2E for save/refresh is covered at unit/API level; full browser scenario can be added in a follow-up hardening pass
- Existing tenants with an old published dentistry template keep that version until a new draft is published with `dental_chart` (fallback panel still shows the chart for dentistry visits)

## Regression Result

- `test_clinics_dental_chart.py` — 8/8 PASS
- `test_clinics_specialties.py` + `test_clinics_release_security.py` + dental — 57/57 PASS
- Full `test_clinics_*` — see session run after this report

## Phase C

Not started. Next: **Dental Treatment Plan** (then Pediatrics only after Phase C DoD if required by roadmap).
