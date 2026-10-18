# Production stock matched to the completed count — 12 October 2026

The user authorized matching both branches to the completed audit, explicitly confirmed uncounted items were zero, then confirmed six replacement units physically arrived after the original count and must be retained.

## Verified result

- Primary session `INV-20261012-9D5C98A857` (id 1) is posted: 336 lines, branch 1 has 171 and branch 2 has 165.
- Independent read-only SQL verified zero discrepancies between those saved physical targets and current option/branch balances; FIFO remaining quantities also match every target. Managed option aggregates were verified too.
- Main-branch replacement stock is 6. Karrada replacement stock is 0.
- Primary post event 924 contains 69 stock adjustments and 67 noncash journal pairs. Every adjustment has one corresponding stock audit. No treasury account is a debit or credit in these journals.
- Supplemental posted session `INV-20261012-21235D5A3C` (id 2) corrects only Karrada's hidden replacement quantity, 11 to 0. It explicitly acknowledges partial coverage; the other 165 lines are not counted or reposted. No financial journal was needed for its zero-cost stock.
- Local encrypted requests are settled. There were 726 unique dispatches, 725 successful validated/acknowledged receipts and one explicit HTTP 409 rejection that produced no post event. There is exactly one successful post event per session.

## Required fixes

1. Added explicit, optional FIFO basis reconciliation with a fingerprint, cost/system permission checks and a reason. It repairs stale/uncovered layers to authoritative on-hand before the count adjustment. Full layer changes are saved in the immutable post event and print/Excel reports. Historical sales are not booked again as a second loss or cash event. Standard posting retains its existing conflict guard.
2. Posting now measures the exact updated option balance and inserts mandatory audit evidence when the legacy aggregate helper cannot capture it. A color count of 1 to 0 with an aggregate already at 0 is covered. Missing/failed mandatory inserts still abort the transaction.
3. Branch catalog resolution excludes archived copies. An inactive replacement copy in branch 2 had hidden the canonical branch stock of 11 behind a false zero. This was repaired with a supplemental audit, preserving the first posted audit's immutability.

Existing period, actor, tenant, branch, approval, stock-reservation and idempotency checks remain enforced. No direct SQL stock writes were used.

## Verification

- Original audit subsystem run: 38 passed, with three failures in the new print template subsequently repaired and passed. Focused final FIFO/option-audit tests: 5 passed; archived-copy end-to-end regression: 1 passed; related color/shared-catalog regressions: 7 passed.
- Native IPC, API and encrypted audit journal: 44 tests passed. Renderer/e2e type checks, focused lint and renderer/web builds passed.
- Existing responsive count-to-post browser scenario passed. New explicit FIFO preview/acknowledgement/post scenario passed after rebuilding the web assets before serving them. Mobile layout was visually inspected.
- Production application files and HTTPS asset hashes verified. Actual Desktop displayed the posted primary audit. Read-only production verification is saved in `tests/_artifacts/smart-inventory-audit/live-completion/posted-verified.json`.

Production backup: `/var/backups/finora/smart-audit-basis-20261012`, including an integrity-checked SQLite backup restricted to mode 600. Deployment changed only audit files/assets and one targeted predicate in the production branch-stock service; unrelated local customer-account development was not published.

The verification applies to the completed audit scope at verification time. An inactive product outside that scope and legacy color projection rows are not additional physical counts; normal later business movements retain their own records.
