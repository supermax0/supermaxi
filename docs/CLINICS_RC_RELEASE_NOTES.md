# FINORA Clinics — RC Release Notes

## RC1 — 2026-09-05

**Product:** FINORA Clinics 1.0 RC1  
**Schema change:** no (current internal schema `clinics-v26-cardiology-clinical-tools`)  
**Migration required for new installs:** `ensure_clinics_schema()` on first Clinics request (additive)

### Included

- Production core + UX navigation
- Dental chart + treatment plan
- Pediatrics / Gynecology / Internal Medicine longitudinal / Cardiology (ECG–Echo)
- Public booking live E2E hardened
- Health: `GET /clinics/api/health`
- Backup/restore runbook + daily backup SUCCESS/FAIL status file

### Fixes since specialty build-out

See phase reports A–H under `docs/CLINICS_V21_*` and `docs/CLINICS_V1_RC1_READINESS_REPORT.md`.

### Known issues

See `docs/CLINICS_KNOWN_LIMITATIONS.md`.  
Pilot issues: `docs/CLINICS_PILOT_ISSUES.md`.

### Upgrade notes

- Prefer PostgreSQL for any real clinic.
- Run backup before any schema-affecting deploy.
- Pilot changes should ship as `RC1.1`, `RC1.2` (small controlled releases).

---

## RC1.1 — _(template)_

**Date:**  
**Schema change:** yes/no  
**Migration required:** yes/no  

### Fixes

- …

### Known issues

- …
