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

Where layout rewrites conflicted with existing functionality, the complete
functional page was restored. The global Finora theme remains, along with
compatible redesigned pages. Clinic-specific layouts keep their own styles.
Navigation, branch-aware inventory quantities and delivery tracking links were
merged explicitly.

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
