# FINORA Clinics 1.0 RC1 — Live Pilot Execution

**Product:** FINORA Clinics 1.0 RC1  
**Schema:** `clinics-v26-cardiology-clinical-tools`  
**Started (docs):** 2026-09-05  
**Nature:** Real-clinic validation — not a feature phase

```text
Do NOT add specialties
Do NOT redesign core workflows
Do NOT ship speculative features
```

---

## Current verdict

```text
READY FOR CONTROLLED PILOT
```

**Not** `PRODUCTION READY` — live observation has not started; this workspace is not the pilot host.

---

## Gate status (this workspace / 2026-09-05)

| Gate | Result | Notes |
|------|--------|-------|
| `py scripts/clinics_pilot_preflight.py` | **FAIL (4)** | Expected on local `FLASK_ENV=development`; must **PASS on pilot host** |
| DEBUG / non-dev | FAIL | Local development |
| SECRET_KEY | FAIL | Weak/missing in local `.env` path used by preflight |
| DATABASE_URL PostgreSQL | PASS | Host recorded as localhost only |
| Timezone documented | FAIL | Set `TZ` or `CLINICS_TIMEZONE` on pilot |
| Backup script + runbook | PASS | Present |
| `last_backup_status.json` SUCCESS | FAIL | No daily status file yet — run backup once on pilot |
| `CLINICS_TEST_POSTGRES_URL` | **NOT SET** | PG hard gates skipped until disposable URL is provided |
| Pilot clinics provisioned | not started | Assign 3–5 tenants |
| Observation window (≥2 weeks) | not started | Starts on first live clinic day |

**Operator action:** re-run preflight and backup/restore on the **actual pilot deployment host**, not this developer machine.

---

## Day-0 checklist (pilot host)

Copy ticks into this section when done.

### A. Preflight

```powershell
py scripts/clinics_pilot_preflight.py
```

- [ ] Result = **PASS**
- [ ] HTTPS verified at reverse proxy
- [ ] `GET /clinics/api/health` → `ok: true`
- [ ] Monitoring / 5xx alerts active

### B. PostgreSQL release gates (disposable DB only)

```powershell
$env:CLINICS_TEST_POSTGRES_URL = "postgresql+psycopg2://USER@HOST:5432/finora_clinics_test_DISPOSABLE"
py -m pytest tests/test_clinics_postgresql_release.py tests/test_clinics_postgresql_v16_migration.py tests/test_clinics_backup_restore.py -q --tb=line
```

- [ ] 0 failed
- [ ] 0 unexpected skips of PostgreSQL hard gates
- [ ] URL is **not** production

### C. Backup → restore → smoke

1. [ ] `pwsh -File scripts/backup_database.ps1`
2. [ ] `backups/daily/last_backup_status.json` → `"status": "SUCCESS"`
3. [ ] Restore dump into isolated disposable DB (see `docs/CLINICS_BACKUP_RESTORE_RUNBOOK.md`)
4. [ ] App smoke against restored DB + health green
5. [ ] Record counts in `docs/CLINICS_LIVE_PILOT_EVIDENCE.md` (no credentials, no PHI)

### D. Provision clinics (3–5)

Use `docs/CLINICS_PILOT_ONBOARDING_CHECKLIST.md` + real RBAC (no admin-for-everyone).

| # | Mix | Tenant code | Go-live date | Owner contact (non-PHI) | Status |
|---|-----|-------------|--------------|-------------------------|--------|
| 1 | Solo | | | | pending |
| 2 | Multi-doctor | | | | pending |
| 3 | Dentistry | | | | pending |
| 4 | Internal medicine | | | | pending |
| 5 | Mixed medical center | | | | pending |

### E. First-day smoke (per clinic)

Reception / Doctor / Owner paths from master prompt §6 — tick on checklist.

Printing on real hardware: Rx, invoice, dental plan, reports (Arabic / RTL / A4 / thermal).

---

## Observation (≥ 2 weeks)

| Metric | How to capture | Target |
|--------|----------------|--------|
| Appointments / visits / completed | Ops dashboard or SQL counts (IDs only) | trending usage |
| Invoices / payments | Finance summary | no integrity incidents |
| Public bookings | Booking logs | failures investigated |
| HTTP 5xx / DB errors | Monitoring | near-zero unexplained |
| P0 / P1 | `docs/CLINICS_PILOT_ISSUES.md` | **must be 0 open** before promotion |

Friction notes (hesitation, “وين؟”, wrong module, excess clicks) → classify P2–P4; do not fix UX only with training.

### RC fix policy

Confirmed defects only via `RC1.1` / `RC1.2` / …  
Reproduce → test → fix → regression → deploy. No mixed feature drops.

---

## Promotion blockers (any one blocks PRODUCTION READY)

```text
Open P0 or P1
Unreliable backup / failed restore
Tenant isolation issue
Financial corruption
Frequent booking failure
Visit completion blocker
Major workflow blocker
```

Before promotion, re-run full Clinics regression + PG gates + specialty browser E2E + backup/restore (**0 failed**).

---

## Final report

After the observation window, fill:

`docs/CLINICS_PILOT_COMPLETION_REPORT.md`

Allowed verdicts only:

```text
NOT READY
READY FOR EXTENDED PILOT
PRODUCTION READY
```

Template lives at the end of master prompt §18 / create that file when observation ends.

---

## Related docs

| Doc | Role |
|-----|------|
| `docs/CLINICS_PHASE_I_CONTROLLED_PILOT.md` | Kickoff / package delivered |
| `docs/CLINICS_PILOT_ONBOARDING_CHECKLIST.md` | Per-tenant setup |
| `docs/CLINICS_PILOT_ISSUES.md` | Issue log (no PHI) |
| `docs/CLINICS_LIVE_PILOT_EVIDENCE.md` | Backup/restore + count evidence |
| `docs/CLINICS_RC_RELEASE_NOTES.md` | RC1.x notes |
| `docs/guides/CLINICS_GUIDE_*.md` | Role one-pagers |
| `docs/CLINICS_KNOWN_LIMITATIONS.md` | Non-bugs |
