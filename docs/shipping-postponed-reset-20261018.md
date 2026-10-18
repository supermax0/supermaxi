# Postponed settlement orders return to pending

Approving a desktop shipping settlement now passes `مؤجل` rows to the existing shared shipping-report executor. The executor returns both invoice and shipping statuses to `تم الطلب`, restores dispatched stock through the existing idempotent lifecycle and resets payment state according to the existing delayed-order policy. Postponed rows do not enter receipt allocations or collection totals. They also leave a delivery agent's open portal reports, like other processed rows.

Only `modules/desktop_api/shipping_center.py` changes in production. The shared executor and stock policy are reused unchanged. Draft classification still has no inventory or payment effects, and approved reports remain locked.

Verification: the shipping center API and phase 2 suites passed 14 tests; the additional mixed-settlement rollback/retry regression passed separately. Coverage includes postponed-only zero collection, one-time stock restoration, carrier/agent flows, partial receipts, unchanged collection totals and atomic rollback when restoring postponed stock fails.

Production: released 2026-10-18. The specific approved report `STL-20261018-0001` (428) in tenant `super` was corrected for orders 2409, 2423 and 2448. They already had pending invoice statuses but stale shipping statuses and deducted stock. The correction was exercised on a cloned database first, then applied transactionally after a fresh tenant backup. Both statuses are now pending and stock is restored. Financial table fingerprints, original receipt allocations and report execution state were preserved; the approved report was not reexecuted. An activity entry and report metadata identify the correction.

Release and recovery evidence: `output/shipping-postponed-fix/`; remote backup `.finora-remote-backups/shipping-postponed-20261018-125738/`.
