# FINORA Clinics v21 — Minimal Implementation Plan

**Date:** 2026-09-04  
**Base:** Production Core `clinics-v20-concurrency-guards` (frozen)  
**Next internal schema (only when real tables land):** `clinics-v21-specialty-clinical-tools`

---

## 1. Production Core freeze (confirmed)

Do **not** rewrite or parallelize these Stable Core areas unless fixing a proven bug:

| Area | Anchor |
|---|---|
| Schema gate | `modules/clinics/schema.py` — `SCHEMA_VERSION`, `ensure_clinics_schema` |
| Patients / appointments / reception / queue | `service.py`, `service_reception.py`, `service_appointments.py` |
| Visits / doctor workspace / clinical record | `service.py`, `service_ops.py`, clinical JS |
| Specialty identity + template versions | `service_specialties.py`, `ClinicVisitTemplate*` |
| Billing / payments / cash / settlements | existing finance paths + PG payment locks |
| Inventory / purchases / suppliers | `service_ops.py`, purchase modules |
| Lab / radiology / follow-ups | `service_clinical_ops.py` |
| Public booking | `service_booking.py`, public routes |
| Auth / tenant isolation | `guards.py` |

**v20 certificate remains valid:** `docs/CLINICS_PRODUCTION_READINESS_REPORT.md`.

---

## 2. Specialty clinical tool extension points (exact)

| Need | Existing hook | Do not create |
|---|---|---|
| Specialty context | `ClinicSpecialty`, `ClinicDoctorSpecialty`, visit `specialty_id` | Per-specialty apps |
| Visit form widgets | `FIELD_TYPES` includes stub `dental_chart`; `ClinicVisitFieldValue.value_json` | Separate dental DB |
| Dentistry seed form | `_seed_additional_templates` dentistry textareas | New visit engine |
| Procedures + stock | `transition_execution` → `stock_out_fefo`; `ClinicProcedureRecipeItem` | Second inventory engine |
| Billing link | existing invoices / visit bill lines | Parallel billing |
| Radiology | existing orders + modality label `dental` | Dental imaging product |

---

## 3. Minimal v21 phases (order)

### Phase A — Procedure Inventory Concurrency Guard *(first)*

**Goal:** Stock=1, two concurrent procedure completions → one succeeds, one fails safely; stock never &lt; 0; retry does not double-consume.

**Changes (minimal):**
- `stock_out_fefo`: `SELECT … FOR UPDATE` on item (+ batches when tracked)
- `transition_execution`: lock `ClinicVisitProcedure` row before consume; keep movement idempotency by `reference_type/reference_id`
- PG concurrent test mirroring payment/booking gates

**Schema bump:** none (behavior-only).

### Phase B — Interactive Dental Chart

**Goal:** FDI chart as `field_type=dental_chart` inside Visit Template Engine.

**Changes:**
- Lift `publish_template` block for `dental_chart` once widget exists
- Builder + doctor workspace widget; persist tooth map in `value_json`
- Optional later: dedicated `ClinicDentalChartObservation` only if JSON-on-visit is insufficient for treatment-plan queries

**Schema bump:** only if new tables are required.

### Phase C — Dental Treatment Plan

**Goal:** Multi-session plan linked to patient + optional teeth + existing billing.

**Changes:** new thin models (e.g. plan + plan items) under `modules/clinics/`; reuse invoices/payments for cost/paid/remaining; no new patient system.

### Later (after A–C stable)

Pediatrics measurements → reference curves → pregnancy tracker → IM chronic tracking → lab/vital trends → cardiology pack → production metrics review.

---

## 4. Non-negotiables for every phase

- One platform, `business_type=clinics`, `/clinics/*`
- No auto-diagnosis / auto-prescription
- No duplicate vitals/lab storage
- Template versions immutable; historical visits untouched
- Tenant isolation + permissions
- Idempotent migrations
- Do not advertise incomplete UI
- Phase report: Implemented / Files / DB / Migration / Tests / Security / Tenant / Performance / Limitations / Regression

---

## 5. Immediate next action

Implement **Phase A** only; regress `test_clinics_*` including new PG concurrency case.
