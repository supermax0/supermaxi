# Reliability audit — 2026-10-19

The isolated real-SQLite regression run passed 118 cases across 23 workflow suites:
order state changes, cancellation/deletion, stock once-only handling, product color stock,
split payments, authorization, POS checkout and rollback, purchase edits/reopening,
customer debt edits/payments, receipt creation/cancellation, customer transactions,
product editor validation, storefront publication, inventory accuracy, cash accounts,
cash shifts, invoice printing, sales returns and expense posting.

The infrastructure-only runner restricts database files to the validation directory,
disables outbound connections and scheduled jobs, and uses synthetic tenants. No production
sale, payment, stock adjustment or customer message was created by these tests. The run
completed in 281.90 seconds with 118 passes and 50 warnings. This is focused regression
coverage, not a claim that every possible workflow or external integration was tested.

The live audit after the responsive release found no application exception in 4,447 journal
entries. Nginx recorded 7,117 successful HTTP 200 responses and five HTTP 502 responses.
All five failures occurred 1.2–2.2 seconds after release installation during the service
restart, on background message/order counters. This exposed an availability gap during
deployment even though the application subsequently served requests successfully.

Normal code updates in Deploy Studio now use systemd reload-or-restart. Service definitions
and the existing-server drop-in implement reload through Gunicorn's HUP signal; the master
keeps the listener while workers change. Requirements updates still use restart because
the application server itself or startup environment may have changed. This requires
preload_app to be disabled, as documented by [Gunicorn](https://gunicorn.org/signals/).
The existing live command was checked to use Gunicorn without --preload. Full service
repair and the explicit restart action retain their intentional restart semantics.

Ten deployment-tool cases passed, including generated-command checks for code-only updates
versus requirements updates. Live rollout verification also checks master PID continuity,
worker replacement, HTTP responses during reload, and read-only authenticated routes.
Results are retained in the release audit/backup directory rather than exposing raw request
logs, credentials or customer payloads in this document.

Remaining limits: no guarantee of zero future errors, no exhaustive concurrent-user load
test, and no live external-provider sends/payments. Earlier responsive validation covered
82 accessible pages on five viewport widths; it does not substitute for workflow tests.
