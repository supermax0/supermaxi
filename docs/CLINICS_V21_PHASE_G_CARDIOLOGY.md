# Phase G Report — Cardiology Clinical Tools

Date: 2026-09-05
Base: clinics-v25-internal-medicine-longitudinal
Schema: clinics-v26-cardiology-clinical-tools

## Implemented

Cardiology specialty pack on top of Phase F longitudinal engines: cardiac history profile, risk-factor display (derived), ECG/Echo structured records, visit template for symptoms/exam, Doctor Workspace + Patient Profile hub section «القلب والأوعية». No ASCVD/CHA2DS2/auto ECG/Echo interpretation or medication engines.

## Modified Files

- `modules/clinics/models.py` — Cardiology profile / ECG / Echo
- `modules/clinics/schema.py` — SCHEMA_VERSION → v26
- `modules/clinics/guards.py` — ECG/Echo visit doctor scope
- `modules/clinics/service_cardiology.py` — new
- `modules/clinics/service_internal_medicine.py` — cardiac condition codes + cardio analytes
- `modules/clinics/service_specialties.py` — cardiology visit template seed
- `modules/clinics/routes.py` — cardiology APIs
- `static/clinics/cardiology-tools.js|css`
- `static/clinics/clinics.js` / `patient-profile.js`
- `templates/clinics/workspace.html`
- `tests/test_clinics_cardiology.py`
- `tests/test_clinics_specialty_browser_smoke.py`
- `tests/test_clinics_internal_medicine.py` — schema assert ≥ v25

## New Models

| Model | Table |
|-------|-------|
| ClinicCardiologyProfile | clinic_cardiology_profile |
| ClinicCardiologyECG | clinic_cardiology_ecg |
| ClinicCardiologyEcho | clinic_cardiology_echo |

## Database Changes

Additive tables via `CLINIC_MODELS` / `ensure_clinics_schema()`. No rewrite of IM/gyn/pediatric/dental data.

## Migration

Idempotent double `ensure_clinics_schema()`.

## APIs

- `GET /api/patients/<id>/cardiology-context`
- `GET /api/visits/<id>/cardiology-context`
- `GET|PUT /api/patients/<id>/cardiology-profile`
- `GET|POST /api/patients/<id>/cardiology/ecgs`
- `PATCH /api/cardiology/ecgs/<id>`
- `GET|POST /api/patients/<id>/cardiology/echos`
- `PATCH /api/cardiology/echos/<id>`
- `GET /api/patients/<id>/cardiology/visit-comparison` (wraps Phase F compare)

Reuses existing: chronic-conditions, medications, vital-trends, lab-trends.

## Cardiology Profile

Smoking, family history, prior MI/PCI/CABG notes, device type/implant — not a duplicate disease registry.

## Cardiac Conditions

`ClinicChronicCondition` with shared codes (CAD, HF, AF, valvular, etc.).

## Symptoms / Examination

Dynamic cardiology visit template (chest pain fields, dyspnea/NYHA clinician-selected, murmur, exam).

## Risk Factors

Derived display from chronic conditions + profile + BMI — **no scores**.

## ECG / Echo

Clinician-entered structured records; attachment ownership validated; completed visit read-only; archive (no hard delete).

## Procedure / Radiology / Medication Integration

No new engines; meds via `ClinicPatientMedication`; optional radiology_order_id on Echo.

## Vital / Lab Trends / Visit Comparison

Phase F `get_vital_trends` / `get_lab_trends` / `compare_visits` (+ ECG/Echo attach).

## Doctor Workspace / Patient Profile

Contextual tab/section only for specialty `cardiology`.

## UX / Navigation

No sidebar ECG/Echo/Cardiac Risk pages.

## Security / Tenant / Doctor Scope / Completed Visit / Audit

`clinics_clinical`; tenant filters; visit-scoped ECG/Echo in doctor scope; completed visit blocks writes; profile/ECG/Echo audited.

## Performance

Context returns recent summaries (5 ECG/Echo); full trends lazy via Phase F APIs.

## RTL/Mobile

Arabic RTL cards/collapsibles.

## Browser E2E

`tests/test_clinics_specialty_browser_smoke.py` — cardiology workspace+profile; IM hardening; gyn hardening.

## PostgreSQL

Additive checkfirst schema; double-run safe.

## Tests

Unit: profile, ECG, Echo, condition/med reuse, trend reuse, comparison, query bound, template seed, clutter, migration.

## Known Limitations

No ASCVD/Framingham/CHA2DS2/HAS-BLED/HEART/TIMI/GRACE; no auto ECG/Echo interpretation; no device interrogation; no Holter engine; no drug-class inference.

## Regression Result

`pytest tests -k "test_clinics_"` → **218 passed / 0 failed** (was 204; +11 cardiology unit + 3 specialty browser smoke).

## Next Phase Recommendation

**Phase H — Final Clinical Hardening & Release Candidate** (do not auto-start another specialty).
