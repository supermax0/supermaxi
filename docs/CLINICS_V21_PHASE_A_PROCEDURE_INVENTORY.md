# Phase A Report — Procedure Inventory Concurrency Guard

**Date:** 2026-09-04  
**Base:** `clinics-v20-concurrency-guards` (schema unchanged)

## Implemented

- Row-level lock on inventory item (+ FEFO batches) inside `stock_out_fefo`
- Row-level lock on `ClinicVisitProcedure` in `transition_execution` before consume
- Concurrent PG test: stock=1, two completions → one success / one safe failure / stock never &lt; 0
- Idempotency test: retry after `inventory_deducted` does not double-consume

## Modified Files

- `modules/clinics/service_ops.py` — `stock_out_fefo`
- `modules/clinics/service_clinical_ops.py` — `transition_execution`
- `tests/test_clinics_postgresql_release.py` — two new tests
- `docs/CLINICS_V21_IMPLEMENTATION_PLAN.md` — freeze + plan

## Database Changes

None.

## Migration

None (behavior-only; no `SCHEMA_VERSION` bump).

## Tests

PostgreSQL release suite: **6 passed** (including new procedure inventory cases) with `CLINICS_TEST_POSTGRES_URL`.

## Security / Tenant Isolation

Locks remain scoped by `tenant_id` filters already present on queries.

## Performance

`FOR UPDATE` only on the contended item/execution rows during stock-out paths; no list-endpoint change.

## Known Limitations

SQLite does not provide the same row-lock semantics; the hard gate is PostgreSQL (production).

## Regression Result

`tests/test_clinics_postgresql_release.py` — 6/6 PASS (2026-09-04).
