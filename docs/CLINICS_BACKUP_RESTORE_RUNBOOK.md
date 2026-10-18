# FINORA Clinics — Backup & Restore Runbook

**Audience:** operators / DevOps  
**Product:** FINORA Clinics 1.0  
**Updated:** 2026-09-05

Do **not** put real passwords in this file. Use environment variables / secret stores.

---

## 1. How daily backup runs (Windows)

Script: `scripts/backup_database.ps1`

```powershell
pwsh -File scripts/backup_database.ps1 -RetentionDays 30
```

Behavior:

- Reads `DATABASE_URL` from project `.env` (PostgreSQL only)
- Writes dumps under `backups/daily/` (or `-BackupRoot`)
- Prunes files older than retention days

Schedule via Windows Task Scheduler (daily off-peak). Prefer copying finished dumps to off-instance storage.

## 2. Linux / server

Script: `scripts/create_server_company_backup.sh` (pg_dump based). Align paths with your deploy layout.

## 3. Required environment

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Primary PostgreSQL connection (`postgresql://…`) |
| `PGPASSWORD` | Optional; may be embedded in URL |
| `CLINICS_TEST_POSTGRES_URL` | Disposable DB for automated restore tests only |

Tools: `pg_dump`, `psql` (PostgreSQL 15+ client tools).

## 4. Restore procedure (disposable verification)

1. Create or reset a **disposable** database (never restore blindly over production without a freeze plan).
2. Restore:

```bash
psql -h HOST -p PORT -U USER -d TARGET_DB -v ON_ERROR_STOP=1 -f backup.sql
```

3. Start app against that database.
4. Verify:

- `/clinics/api/health` → `{"ok":true,"database":"up"}`
- tenant login works
- sample patients / appointments / visits / invoices present
- specialty tables exist if schema ≥ v21 packs

## 5. Automated evidence

`tests/test_clinics_backup_restore.py` (requires `CLINICS_TEST_POSTGRES_URL` + client tools) dumps, restores, and writes:

```text
tests/_artifacts/backup_restore/last_restore_evidence.txt
```

## 6. Rollback notes

- Prefer restore to a **new** database + cutover DNS/config rather than in-place overwrite.
- After restore, run application once so `ensure_clinics_schema()` can apply additive migrations safely (idempotent).
- Keep at least one known-good dump from before any major schema bump.

## 7. Monitoring backup success

The daily script always writes:

```text
backups/daily/last_backup_status.json
```

Example shape:

```json
{
  "status": "SUCCESS",
  "at": "2026-09-05T10:00:00.0000000Z",
  "message": "OK file=…",
  "file": "dbname_2026-09-05_….dump",
  "size_bytes": 123456,
  "retention_days": 30,
  "database": "dbname"
}
```

On failure, `status` is `FAIL` and `message` holds the error (no password).

**Alert on:**

- Task Scheduler / cron exit code ≠ 0
- `status` ≠ `SUCCESS` in `last_backup_status.json`
- Dump file size ≈ 0 or missing for the day
- Status file older than ~26 hours (backup did not run)

Pilot preflight also checks this file: `py scripts/clinics_pilot_preflight.py`.

Optional: checksum + copy confirmation to off-instance store.
