# Live Pilot Evidence Log

**Product:** FINORA Clinics 1.0 RC1  
**Rule:** no passwords, connection strings, or patient-identifying content.

Use one section per restore drill / milestone.

---

## Restore drill — _(template)_

| Field | Value |
|-------|-------|
| Date (UTC) | |
| Environment | pilot / staging |
| PostgreSQL major version | |
| Backup file name (no path secrets) | |
| `last_backup_status.json` | SUCCESS / FAIL |
| Restore target | disposable DB name only |
| App health after restore | `GET /clinics/api/health` → |
| Operator initials | |

### Counts (IDs / aggregates only)

| Entity | Source DB count | Restored DB count | Match? |
|--------|-----------------|-------------------|--------|
| tenants (`tenant`) | | | |
| patients | | | |
| doctors | | | |
| appointments | | | |
| visits | | | |
| invoices | | | |
| payments | | | |
| inventory items | | | |
| clinical specialty rows (optional rollup) | | | |

### Smoke after restore

- [ ] Tenant login works
- [ ] Sample appointment list loads
- [ ] Sample visit / workspace opens
- [ ] Invoice list loads
- [ ] Specialty pack visible if enabled for that tenant

### Notes / anomalies

```text
(none yet)
```

---

## Usage snapshot — week _N_ (no PHI)

| Date | Clinics live | Appointments | Visits | Completed | Invoices | Public bookings | Open P0 | Open P1 |
|------|--------------|--------------|--------|-----------|----------|-----------------|---------|---------|
| | | | | | | | 0 | 0 |

---

## PostgreSQL gate run — _(template)_

| Field | Value |
|-------|-------|
| Date | |
| `CLINICS_TEST_POSTGRES_URL` host class | disposable test only |
| Command | `pytest tests/test_clinics_postgresql_*.py tests/test_clinics_backup_restore.py` |
| Result | passed / failed / skipped |
| Failed test names | |
