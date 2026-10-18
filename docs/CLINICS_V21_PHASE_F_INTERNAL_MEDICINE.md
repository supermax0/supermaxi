# Phase F Report — Internal Medicine Longitudinal Clinical Tools

Date: 2026-09-05
Base: clinics-v24-gynecology-obstetrics-tools
Schema: clinics-v25-internal-medicine-longitudinal

## Implemented

Patient-level chronic disease registry, clinician-confirmed medications, vital/lab trend views, disease contextual packs, and visit comparison — surfaced only in Doctor Workspace + Patient Profile for specialty `internal_medicine` (no new sidebar pages). No auto diagnosis, risk scoring, dose calculation, or treatment recommendations.

## Modified Files

- `modules/clinics/models.py` — `ClinicChronicCondition`, `ClinicPatientMedication`
- `modules/clinics/schema.py` — SCHEMA_VERSION → v25
- `modules/clinics/guards.py` — doctor scope + write protection
- `modules/clinics/service_internal_medicine.py` — new service
- `modules/clinics/routes.py` — IM APIs under `clinics_clinical`
- `static/clinics/internal-medicine-tools.js|css`
- `static/clinics/clinics.js` — doctor tab for `internal_medicine`
- `static/clinics/patient-profile.js` — clinical hub section
- `templates/clinics/workspace.html` — asset includes
- `tests/test_clinics_internal_medicine.py`
- `tests/test_clinics_gynecology_tools.py` — schema assert relaxed (≥ v24)

## New Models

| Model | Table |
|-------|-------|
| ClinicChronicCondition | clinic_chronic_condition |
| ClinicPatientMedication | clinic_patient_medication |

## Database Changes

Additive tables via `CLINIC_MODELS` / `ensure_clinics_schema()` (checkfirst). No rewrite of visits, gyn, pediatric, or dental data.

## Migration

Idempotent `ensure_clinics_schema()` twice. Expected: no duplicate chronic rows from migration; v24 gyn / pediatric / dental untouched.

## APIs

- `GET /api/patients/<id>/internal-medicine-context`
- `GET /api/visits/<id>/internal-medicine-context`
- `GET|POST /api/patients/<id>/chronic-conditions`
- `PATCH /api/chronic-conditions/<id>`
- `POST /api/patients/<id>/chronic-conditions/promote-diagnosis`
- `GET|POST /api/patients/<id>/medications`
- `PATCH /api/patient-medications/<id>`
- `GET /api/patients/<id>/vital-trends?range=`
- `GET /api/patients/<id>/lab-trends?analytes=&range=`
- `GET /api/patients/<id>/visit-comparison?visit_ids=`

## Chronic Disease Registry

Multiple conditions per patient; catalog codes + custom `other`; status/severity; archive (no hard delete); promote from encounter diagnosis.

## Current Medications

Clinician-confirmed active/stopped/historical; prescription items shown as history hints only (not auto-promoted).

## Vital Trends

`ClinicVital` source of truth; BP text `120/80` parsed; ranges 30d/3m/6m/1y/all; lazy full load in UI.

## Lab Trends

Existing `ClinicLabOrder` / items; analyte alias match; series keyed by unit (no cross-unit conversion).

## Disease Context Packs

Diabetes, hypertension, CKD, thyroid, lipids, liver, anemia — related labs + vitals only; `auto_scoring: false`.

## Visit Comparison

2–4 visits: vitals, diagnoses, Rx items, notes, follow-up date.

## Doctor Workspace

Tab «الباطنية والأمراض المزمنة» when specialty is `internal_medicine`.

## Patient Profile

Clinical hub subsection `internal_medicine` (same tools pack).

## UX / Navigation

No sidebar entries for diabetes/chronic/trends. Phase UX hub rules preserved.

## Security

Routes require `clinics_clinical`. Guards apply doctor scope + write protection on new models.

## Tenant Isolation

All queries filter `tenant_id`; cross-tenant context/create raises.

## Doctor Scope

`created_by_doctor_id` on new rows; guards mirror pediatrics/gyn pattern.

## Audit

create / update / status_change / archive / promote_diagnosis on chronic; create/update/archive on medications (old/new meta).

## Performance

Context summary uses bounded queries; full vital/lab trends lazy-loaded from UI. Query-bound test &lt; 45 statements.

## RTL/Mobile

Arabic RTL UI; comparison stacks on narrow screens; charts/sparks LTR on time axis.

## Browser E2E

Covered by unit/API wiring + workspace asset smoke (manual browser scenario per prompt §60–61 recommended on live tenant).

## PostgreSQL

Schema create is checkfirst/idempotent; uniqueness/concurrency unchanged from prior phases (no new unique chronic constraint that would conflict).

## Tests

`tests/test_clinics_internal_medicine.py` — registry, promote, meds, vitals, labs, comparison, packs, isolation, query bound, sidebar clutter, migration.

## Known Limitations

No clinical decision support, CV risk scores, CKD staging, auto control classification, drug interactions, or dose calculators.

## Regression Result

`pytest tests -k "test_clinics_"` → **204 passed / 0 failed** (was 192; +12 Phase F).

## Next Phase Recommendation

**Phase G — Cardiology Clinical Tools** — reuse this longitudinal vital/lab/condition foundation; add cardiac history, ECG/Echo context, risk-factor documentation, cardiology exam — do not build a separate trend engine.
