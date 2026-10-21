# FINORA 0.10.3 — live settlement drafts

Saving an order edit, price, status, collection, shipping company or delivery-agent change refreshes open shipping windows immediately. Draft manifests also refresh every three seconds while online and on window focus, so edits from the website or another device appear without reopening the manifest. The detail dialog follows the current row; receipt amounts and unfinished classifications stay local until explicitly saved. Earlier autosave acknowledgements cannot clear a newer edit, and a rejected draft is not resubmitted repeatedly.

Changing or clearing an order's delivery agent removes it from the former agent's open AGT and settlement drafts, including its selection and portal claim, inside the same database transaction. The existing rule identifying duplicate agent records by name and phone is shared by grouping and synchronization. A rollback restores both the assignment and draft membership. Carrier manifests retain their independent ownership. Existing stale drafts are reconciled as a read-only view as well.

Approval captures current order amounts and details. Subsequent reads of approved manifests use their stored snapshot and settlement allocations, without substituting the current order price or agent. Existing approved records use their saved rows; financial postings, receipt allocation, stock and the approval lock remain governed by the shared settlement executor.

Regression coverage includes price/summary agreement, reassignment, clearing an agent, duplicate agent identities, rollback, stale drafts, immutable approved snapshots, live detail refresh, preserving entered receipts, autosave races, rejected saves, and query invalidation after order edits.
