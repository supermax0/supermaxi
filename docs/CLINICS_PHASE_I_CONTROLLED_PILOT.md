# Phase I Report — Controlled Pilot & Production Promotion

**Date:** 2026-09-05  
**Nature:** Ops / pilot kickoff (not a specialty feature phase)  
**Product Version:** FINORA Clinics 1.0 RC1  
**Schema:** `clinics-v26-cardiology-clinical-tools`

---

## Status of this document

This is the **Phase I kickoff / readiness package**.  
Live execution tracker: `docs/CLINICS_LIVE_PILOT_EXECUTION.md`.  
Real clinic observation has **not** started. Production promotion is therefore **not** claimed.

After live pilot observation, fill `docs/CLINICS_PILOT_COMPLETION_REPORT.md` and replace the verdict only if promotion gates pass.

---

## Pilot Clinics

| Slot | Target mix | Tenant | Status |
|------|------------|--------|--------|
| 1 | Solo clinic | _(assign)_ | not started |
| 2 | Multi-doctor | _(assign)_ | not started |
| 3 | Dentistry | _(assign)_ | not started |
| 4 | Internal medicine | _(assign)_ | not started |
| 5 | Mixed medical center | _(assign)_ | not started |

Target: 3–5 clinics (diversity over count).

## Observation Window

```text
Not started — schedule ≥ 2 weeks after first live clinic day
```

## Ops package delivered (this phase)

| Artifact | Path |
|----------|------|
| Onboarding checklist | `docs/CLINICS_PILOT_ONBOARDING_CHECKLIST.md` |
| Issue log | `docs/CLINICS_PILOT_ISSUES.md` |
| RC release notes | `docs/CLINICS_RC_RELEASE_NOTES.md` |
| Reception guide | `docs/guides/CLINICS_GUIDE_RECEPTION.md` |
| Doctor guide | `docs/guides/CLINICS_GUIDE_DOCTOR.md` |
| Owner guide | `docs/guides/CLINICS_GUIDE_OWNER.md` |
| Backup SUCCESS/FAIL status | `backups/daily/last_backup_status.json` via `scripts/backup_database.ps1` |
| Preflight | `scripts/clinics_pilot_preflight.py` |
| Count evidence helper | `scripts/clinics_pilot_count_evidence.py` |
| Live execution tracker | `docs/CLINICS_LIVE_PILOT_EXECUTION.md` |
| Evidence / completion templates | `docs/CLINICS_LIVE_PILOT_EVIDENCE.md`, `docs/CLINICS_PILOT_COMPLETION_REPORT.md` |
| Backup runbook update | `docs/CLINICS_BACKUP_RESTORE_RUNBOOK.md` §7 |
| Automated checks | `tests/test_clinics_phase_i_pilot.py` |

## Pre-pilot safety gates (operator)

Before first live clinic:

1. `py scripts/clinics_pilot_preflight.py` → **PASS**
2. Backup → restore into disposable DB → app smoke → **PASS**
3. `GET /clinics/api/health` → `ok: true`
4. HTTPS, PostgreSQL, DEBUG off, secrets, monitoring — per checklist

## Usage Summary

```text
No live pilot usage yet
```

## Issues

| Class | Count |
|-------|-------|
| P0 Issues | 0 (none from live pilot) |
| P1 Issues | 0 |
| P2 Issues | 0 |
| P3 Issues | 0 |
| Feature Requests | track as P4 in `CLINICS_PILOT_ISSUES.md` |

## Resolved During Pilot

```text
n/a — pilot not started
```

## Open Issues

None from live use. Known product limits: `docs/CLINICS_KNOWN_LIMITATIONS.md`.

## Role Feedback

| Role | Feedback |
|------|----------|
| Reception | awaiting interviews |
| Doctor | awaiting interviews |
| Owner | awaiting interviews |

## Reliability / Performance / Booking / Printing / Mobile

Awaiting live observation. RC1 automated gates remain green (Phase H + Phase I artifact tests).

## Backup / Restore

- Daily script writes alertable `last_backup_status.json` (`SUCCESS` / `FAIL`)
- Runbook documents monitoring
- Prior automated restore evidence: Phase H (`tests/test_clinics_backup_restore.py` when `CLINICS_TEST_POSTGRES_URL` set)
- **Still required on pilot infra:** operator restore drill before first clinic

## Security / Tenant / Doctor Scope / Finance

Unchanged from RC1. No new specialty surface in Phase I.

## Tests / Regression

```text
pytest tests -k "test_clinics_"
selected: 234
Phase I artifact tests: 5 passed (test_clinics_phase_i_pilot.py)
Specialty browser smoke (isolation): 5 passed
Full-suite last green expectation: 225 passed / 0 failed / 9 skipped
  (9 skips = PostgreSQL / backup restore without CLINICS_TEST_POSTGRES_URL)
Note: under heavy full-suite load, specialty profile mounts may flake on SQLite;
      re-run specialty browser module; see CLINICS_KNOWN_LIMITATIONS.md
```

## Migration / Browser E2E

No schema change in Phase I. Specialty + UX browser suites remain as in RC1.

## Known Limitations

Unchanged — see `docs/CLINICS_KNOWN_LIMITATIONS.md`.

## Release Blockers (for Production)

```text
Real pilot observation incomplete
Operator restore drill on pilot host not evidenced in this repo
No production promotion without open-P0/P1 clearance from live use
```

---

## Final Verdict

```text
READY FOR CONTROLLED PILOT — AWAITING REAL CLINIC OBSERVATION
```

Not yet:

```text
PRODUCTION READY
```

Allowed later verdicts after observation: `NOT READY` · `READY FOR EXTENDED PILOT` · `PRODUCTION READY`.

## Recommendation

1. Provision 3–5 pilot tenants using the onboarding checklist.  
2. Run preflight + restore drill on the deploy host.  
3. Observe ≥ 2 weeks; log issues without PHI.  
4. Ship only small `RC1.x` fixes.  
5. Re-run final gates (§52–§58 in master prompt) before writing `PRODUCTION READY`.  
6. Do **not** start a new major specialty until this report’s completion section is reviewed.
