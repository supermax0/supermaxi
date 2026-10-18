# FINORA Clinics v20 — Final Audit Findings (Working)

**Schema:** `clinics-v20-concurrency-guards`  
**Date:** 2026-09-04  
**Status:** In progress — not a release certificate.

## 1. Documentation vs Implementation

| Feature | Documented State | Actual State | Mismatch | Action |
|---------|------------------|--------------|----------|--------|
| Organization Mode | Separated in specialties report; full report still mixes nav | `organization_mode` live (`solo_clinic` / `multi_doctor_clinic` / `medical_center`); settings UI uses it | Full report sidebar omits `/clinics/specialties`; specialties report still describes pre-implementation gaps as current | Update docs after code freeze |
| Specialties | Planned / partial in specialties report; readiness says implemented | `ClinicSpecialty` + page `/clinics/specialties` + APIs under `clinics_admin` | Specialties report §1 outdated | Refresh specialties report |
| Specialties Page | Planned under الإدارة | Present in `workspace.html` under الإدارة | Full report nav map missing it | Add to nav map |
| Doctor Specialties | Planned M2M + primary | `ClinicDoctorSpecialty` implemented | Docs lag | Align docs |
| Service Specialties | v18 implemented; empty links = global | `ClinicServiceSpecialty` + empty = unrestricted | Document global-service BC clearly | Keep BC; document |
| Procedure Specialties | Readiness: implemented | `ClinicProcedureSpecialty` | Specialties report listed as remaining | Done in code |
| Prescription Templates | Readiness: implemented | Models + clinical APIs (`clinics_clinical`) | Specialties report listed as remaining | Done in code |
| Visit Templates | Versioned draft/publish/archive | Implemented + PG publish lock | OK | Keep |
| Dashboard Modes | owner+doctor switch; finance redaction | Implemented | OK | Keep |
| Public Booking Flow | Specialty→Doctor→Service→… | Template + JS flow implemented; live E2E still open | Readiness correctly holds live E2E | Run live E2E |
| Doctor Scope | ORM + write guards | Appointments/visits/FU/labs/rad + clinical children | Financial entities permission-gated not ORM-scoped | Acceptable if billing gate solid |
| Concurrency Guards | v20 name; booking + complete tested | Appointment advisory lock; visit FOR UPDATE; invoice unique; **payment FOR UPDATE added this audit** | Payment was gap | Closed in code; need PG gate |
| `clinic_type` | Deprecated alongside org mode | Still in DB/API; UI no longer edits it as mixed select | Dashboard used `clinic_type_label`; settings/services UX residual | Hardened this audit |

## 2. Fixes applied in this audit pass

- `update_settings`: `organization_mode` primary; `clinic_type` only when explicitly sent; legacy org-shaped values map into `organization_mode` without hybrid storage.
- Dashboard subtitle uses `organization_mode_label`.
- Settings UI: clear «نوع المنشأة» vs «الاختصاصات الطبية» sections.
- Services seed no longer presents `clinic_type` specialty packs as facility type.
- `seed_specialty_pack` never treats org-shaped keys as packs / never mutates `organization_mode`.
- `receive_payment`: PostgreSQL `FOR UPDATE` + balance re-check (overpay race).
- Financial leak hardening: visit complete / treatment-bill respect `include_financial`; search invoices require `clinics_billing`; settings commission redacted; visits registry strips unpaid flag + doctor commission without billing.
- `reschedule_appointment`: specialty/service/doctor validation + block identity change after visit started.
- Tests: org-mode preference; PG concurrent payment gate.

## 3. Remaining release blockers (from readiness + this pass)

1. Complete authorization negative matrix (exports, purchases fallbacks, communications).
2. Complete financial leak audit across every API/export.
3. Live-backend public booking E2E (beyond HTTP fixtures).
4. Populated PostgreSQL **v16→v20** migration twice with history counts (synthetic gates ≠ customer snapshot).
5. Critical RTL/mobile matrix for internal pages.
6. Report/export filter parity.
7. Query-count benchmark for listed pages.
8. Sidebar shows all admin links without permission hide (pages/APIs still gated) — soft gap vs brief §4.

## 4. Allowed non-blocking V1 limitations

- Interactive Dental Chart — Planned (builder does not offer type; seeded dentistry uses textarea notes).
- WHO/CDC Growth Curves — Planned (no Growth Chart label as interactive product).
- Advanced Pregnancy Tracking / CDS / advanced conditional builder.

## Phase 1 — Live Public Booking E2E

**Result: PASS (15/15)** — `tests/test_clinics_booking_live_e2e.py`

| Scenario | Result | Evidence |
|----------|--------|----------|
| 1 Normal specialty booking + DB persist | PASS | widths 1920/1366/375/390/430; screenshots `s1_success_*` |
| 2 Multi-specialty change resets invalid service/slot | PASS | Endocrinology persisted |
| 3 Doctor change clears slot | PASS | valid service may remain |
| 4 Service change clears slot | PASS | |
| 5 Direct doctor link (1 vs multi specialty) | PASS | |
| 6 No availability empty state | PASS | |
| 7 Disabled relations excluded | PASS | |
| 8 Concurrent double booking | PASS | one success / one conflict; 1 DB row |
| 9 OTP invalid then valid | PASS | |
| 10 Manage reschedule + cancel | PASS | specialty/service preserved |

Artifacts: `tests/_artifacts/booking_live_e2e/`

Also fixed: `create_online_booking` slot check now passes `specialty_id`.

---
