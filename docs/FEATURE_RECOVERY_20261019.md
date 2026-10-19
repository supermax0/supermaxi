# Recovery after the October 18 layout deployment

The GitHub layout branch was based on an older application tree. Local features
from later months were still uncommitted, while server deployments had copied
them directly. Fast-forwarding the local branch did not publish those local
changes. Running `git reset --hard origin/main` on the server then replaced the
tracked production code with the older implementation.

The recovery uses the complete October 18 validation workspace, including the
verified final order workspace changes, to restore functional templates and
their backend implementations. The application source that previously existed
only outside Git is included in the release commit.

The initial recovery restored complete functional templates at conflicting
pages, which also replaced Claude's page designs. The follow-up merges those
designs explicitly: compact toolbars, action menus, drawers, table/card layouts,
headers and navigation retain server pagination, permission checks, installment
editing, backdated payments, branch/color inventory adjustment, bulk POS
visibility, supplier second phones and shared balances, scheduled expense
editing, monthly commission settlement/statement and scan-company selection.
The purchase editor retains its complete local workflow within the FD design.
Clinic-specific layouts keep their own styles.

Supplier list presentation data follows the existing branch visibility and
shared supplier grouping. Drawer mutations use the mature scoped APIs, including
the inventory API that preserves colors, product options and media metadata.
Saved order views also retain the redesigned date and amount filters.

`scripts/safe_git_update.py` now rejects dirty server files, divergent history
and incoming files that would replace server-only files. Both the server deploy
command and Deploy Studio's Fix All use this check instead of a hard reset.
Fix All stops after failures and restarts the managed service without killing
all Gunicorn processes or deleting compiled static assets.

Customer databases, WAL/SHM files, uploads, generated reports and local build
caches are excluded from version control and from the source release. Deployment
copies source files and does not delete customer files. Before deployment, an
on-server source snapshot and consistent snapshots of 33 SQLite databases and
the PostgreSQL core database were saved under
`/var/backups/finora/merge-recovery-20261019`.

Validation includes Python/Jinja syntax checks, the order/navigation/permissions/
payroll/report/inventory acceptance suite, real-repository deployment guard
tests, desktop API and financial regression tests, and browser smoke checks of
orders, inventory, cash, payroll, accounts, reports and suppliers. The mobile
order page was checked at 390 pixels. All validation uses disposable tenant
databases and disabled external integrations.

Several older tests were corrected to inspect rendered navigation attributes
instead of selector text inside JavaScript, include the undated cash summary
field, use the Baghdad business date, and model unambiguous legacy product
copies across branches. These corrections do not relax permissions or change
financial calculations.

The review also found that daily report defaults used the server calendar even
though transaction periods use Baghdad dates. Default report dates and new
daily sessions now use `business_today()`. Explicit user-selected dates remain
supported. Boundary and session-creation tests cover UTC 20:59, UTC 21:00 and the
late evening; the affected report/integrity suite passed 29 checks.

Finance and daily-closing test fixtures now supply business-calendar dates,
instead of the server's UTC calendar. Seeded movements stay inside their actual
report window, and the late-opening test uses a completed business day. The
previously failing loan/report cases and all 18 daily-closing cases also passed
against the real clock during Baghdad's midnight boundary.

Final automated coverage: **3010 unique cases: 2999 passed, 11 skipped, zero
unresolved failures**, combined from the completed isolated segments and focused
reruns. Database/live-integration prerequisites account for the skips. Python
browser-only suites were excluded from this count; separate Chrome smoke checks
covered seven main pages and mobile orders. Fourteen authenticated production
GETs and the public storefront returned HTTP 200, including verification of the
live Baghdad report date. All 3342 deployed source fingerprints matched.

Preview-writing tests create their generated-output directories on a fresh
checkout. The rotating-savings standalone fixture registers the HR/finance
foreign-key graph before creating its database. Temporary SQLite files stay in
the validation sandbox. The threaded search cache was rechecked with the real
monotonic clock. These changes preserve every functional assertion.

The design follow-up passed 159 distinct focused Python regressions (including
rerunning the credit read-safety check against the redesigned JSON status rather
than a removed CSS class), and 21 navigation/saved-view JavaScript checks.
Browser acceptance covers 13 desktop and 13 mobile page routes, with real
isolated order pagination/filtering, compact row print actions, product drawer
saves, supplier contact edits, installment editing/payment dates, employee
branch/transfer fields and monthly payroll statements. External notification
polling is stubbed in browser acceptance; financial actions use isolated data.
