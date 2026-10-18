# FINORA desktop offline and synchronization plan

اكتمل التخزين المشفّر وتنزيل البيانات وحجز مخزون لكل جهاز. البيع للمورد
ونقطة البيع يدعمان اعتماد بيع محلي من الحصة، مع التحصيل النقدي أو التحويل
أو البيع الآجل في نقطة البيع. باقي التعديلات والإلغاءات والتحصيلات المنفصلة
ومخزون المواد الغذائية والمستودعات تحتاج الاتصال أو مسار مزامنة خاصاً بها.

## Findings

The management desktop currently sends every request to Flask. React Query holds
temporary data only; restarting without the server leads to the login screen.
Electron already isolates cookies and privileged operations in its main process.
Stock is branch-aware, with color stock as an authoritative detail ledger. POS
checkout and collection are separate operations. Several other modules write
inventory, so reserving stock cannot be implemented only in the desktop UI.
The Windows 7 build targets Electron 22 / Node 16; an embedded database must also
work there, without relying on recent Node SQLite APIs.

## Invariants

- Separate server, tenant, employee and branch data. A permission failure must
  never fall back to cached data. Explicit logout disables local access.
- Never store passwords. Encrypt local business data with an OS-protected key.
- An operation is acknowledged locally only after an atomic durable checkpoint.
- Persist UUIDs before transmission. Replays must return the same server result;
  changes to an already-used UUID must be rejected.
- Distinguish local drafts, queued operations, conflicts and confirmed invoices.
  A draft is not a receipt, payment or authorization to deliver goods.
- Do not resolve stock, payment or ledger conflicts by last-write-wins.
- Never automatically release a device's inventory quota merely because it went
  offline: it may already have sold that inventory without synchronizing.

## Delivery stages

1. **Durable local foundation and verified synchronization (delivered).**
   Main-process SQLite, encrypted atomic checkpoints, scoped response cache,
   bounded offline session access, durable supplier-sale drafts, idempotent
   server replay, automatic reconnect synchronization and an Arabic queue view.
   Previously loaded data remains readable after restart. A supplier sale saved
   offline is explicitly pending server validation; failed stock validation
   retains the draft as a conflict. Other financial writes stay online until
   their domain-specific synchronization is implemented.
2. **Complete downloadable snapshots (delivered).** Paginated authoritative snapshots for
   products, colors, customers, suppliers, orders and purchases; resumable
   download; deletions through full generation replacement; recorded capture
   interval; visible snapshot age/completeness.
   This removes the stage-one limitation to previously loaded responses.
3. **Authoritative device inventory quotas.** Reserve atomically on the server
   before disconnecting, enforce quotas in every stock-consuming service,
   protect color quantities, consume allocations and create financial documents
   in one transaction. Add controlled quota return and lost-device reconciliation.
   Then allow final offline sales from the allocated quantity. Last piece: one
   device gets it; every other writer sees zero available.
4. **POS and remaining business workflows.** Atomic checkout + cash collection,
   locally unique receipt numbers and printing; customers and purchases with
   dependency mapping; server validations for payments, cancellations and stock
   adjustments. Apply each operation through existing domain services, with
   durable deduplication and explicit conflict handling.
5. **Production readiness.** Concurrent last-piece tests across web/desktop,
   disconnect after server commit, restart before acknowledgment, interrupted
   checkpoints, permission revocation, branch/user/server switching, large
   snapshots, encrypted backup/recovery and installer smoke tests.

## Initial implementation choices

Use sql.js SQLite in main, not renderer localStorage. Persist exports through
AES-256-GCM and atomic write/fsync/rename; protect the random encryption key with
Electron safeStorage. Fail closed if decryption or OS encryption is unavailable.
Keep a previous durable state on failed writes, and never silently recreate a
corrupt database. Initial offline authorization is bounded to 24 hours from the
last successful online session verification (also capped by server session age).

Cache only explicitly allowed read adapters, never login responses, arbitrary
URLs, redirects or permission errors. Fall back only on network/timeout failures.
Replay queued supplier drafts only after verifying the same online identity.
Keep operations and their errors across restarts and logout; resume only when
the original identity signs in again. Changing identity must not expose them.

## References

- https://developer.android.com/topic/architecture/data-layer/offline-first
- https://github.com/sql-js/sql.js
- https://github.com/electron/electron/blob/v44.4.5/docs/api/safe-storage.md

## Stage-one delivery — 2026-10-09

Implemented encrypted SQLite checkpoints in Electron main, a Windows-protected
key, cached read adapters, a 24-hour offline authorization lease, and durable
supplier-sale drafts. The Arabic queue is under Settings → الأوفلاين والمزامنة
and follows the existing violet/maroon design. It shows pending, confirmed and
conflicted operations, their server invoice number and the reason for rejection.

Online supplier sales also use the durable queue when local access is ready.
The server receipt and sale, stock deduction and supplier offset commit together.
A retry uses the original device/operation UUID; changed payloads are rejected.
Local drafts are scoped to server, tenant, employee, branch and branch-view mode.
Synchronization verifies the current server session before sending, and pins
requests to the original configured server. Logout revokes cached access.

The branch-stock deduction now conditionally updates the authoritative balance,
preventing concurrent successful deductions beyond the available quantity.
Two simultaneous supplier sales against one piece produced one confirmed invoice
and one stock conflict, with zero stock remaining. A conflict stays visible;
it does not become an invoice automatically.

Verification uses throwaway tenants and isolated Electron profiles, not live
business data:

- Native supplier/read/sync backend tests: 18 passed, including concurrent last
  piece, durable replay, changed-payload rejection and full rollback.
- Desktop auth: 8 passed; supplier allocations/statements: 4 passed.
- Shared stock/order/color regressions: 7 passed.
- Full desktop unit suite: all 144 tests across 21 files passed. The shell test
  session now explicitly grants inventory permission for its expected windows;
  serial workers avoid the existing animated-payment timing race.
- Electron end-to-end: 2 passed, including two offline restarts, cached product
  lookup, durable draft recovery and automatic reconnect replay exactly once.
- Build/type checks, focused ESLint and changed-file formatting checks passed.
- Screenshots: `desktop/finora_management/screenshots/offline-queue.png` and
  `offline-synchronized.png`.

### Stage-one limitations, superseded in part by stage two

Stage one caches only previously requested read responses, with a maximum of
500 responses per context. It does not download every server record. Saving
supplier-sale drafts requires previously loaded product stock. Confirmed sync
invalidates that context's cached business responses, which active views reload
from the server. Unfinished local operations are limited to 500 per context.

POS checkout, collections, payments and other financial mutations still need
the server. Device stock quotas, full snapshots and final offline receipts are
not implemented yet. Do not deliver goods against an unconfirmed local draft.
The code and development bundles are built; production installers, Windows 7
smoke testing, encrypted backup recovery and large-data testing remain for stage
five. Deploy the matching backend and restart the updated desktop together.

## Stage-two delivery — 2026-10-09

Settings → الأوفلاين والمزامنة now provides download, update, resume and restart
controls in the existing maroon/violet design. Downloaded collections support
local search, filters, pagination and details after an offline restart, including
records that have never been opened. Permissions determine which datasets exist:
products and their details, purchase-product search, purchases and their details,
suppliers and their details, supplier-sale product/color search, orders and their
details/lookups/counts, POS catalog/bootstrap and customers (15 dataset families).
Server adapters retain their native branch, catalog, balance and visibility rules.
Order-tab membership comes from the server's actual queries rather than inferred
client status labels. Unsupported filters fall back to an exact cached response
or require connectivity instead of returning an approximation.

`POST /api/v1/desktop/snapshots` freezes a generation under a durable client UUID.
`GET /api/v1/desktop/snapshots/<id>/<dataset>?cursor=N` returns immutable pages of
100 records, with a SHA-256 digest over the exact JSON text. Each page is checked
and saved through the encrypted atomic checkpoint before advancing its cursor.
Interrupted downloads resume at the saved page after restarting the app. A
generation is published only when all dataset counts and unique IDs match; old
records and response-cache entries are then replaced in the same checkpoint.
This also removes records deleted on the server. The previous complete copy and
queued financial drafts survive failed downloads and an explicit download restart.

The server checks identity, branch mode, role and permissions on every page.
Client scope and permissions are checked during download and publication;
permission/role changes clear downloaded reads. Permission denials revoke cached
access, even when received while downloading. Server pages expire after 24 hours
for resumability; local use remains subject to the existing offline authorization
lease. Captured data represents a recorded interval, not a single transactional
stock snapshot or inventory allocation. Confirmed supplier synchronization marks
the local generation stale; the UI asks for an update. Later exact cached reads
can take precedence over older snapshot rows.

Verification completed against isolated profiles and throwaway tenants:

- Backend desktop adapter/auth/supplier synchronization/snapshot suite: 41 passed.
  Snapshot checks include multiple pages, immutable replay after a source edit,
  digest verification, denied access and generation expiry.
- Full desktop unit suite: 158 passed across 24 files. Snapshot tests cover
  offline restart and unseen barcode lookup, resume after a failed page, retaining
  an old complete generation, deleted-record removal, corruption rejection,
  explicit restart recovery, permission denial and user isolation. Local query
  tests exercise balances, purchase totals and native overlapping order tabs.
- Electron end-to-end: 3 passed, including full download followed by offline
  restart, unseen supplier/product lookup and durable draft creation; the
  existing automatic reconnect and supplier workflows still pass.
- Build/type checks, focused ESLint and formatting checks passed.
- Screenshot: `desktop/finora_management/screenshots/offline-snapshot.png`.

### Current remaining scope

The current generation limit is 50,000 records per dataset and 8 MiB per page.
Server generation currently uses synchronous native read adapters; large-data
performance and installer/Windows 7 smoke tests remain to be completed. Images
and printed reports still need connectivity. This generation is a full refresh;
incremental change-log synchronization is not implemented.

## Stage-three delivery — device inventory escrow

Offline supplier sales can now use an explicit device quota. While online, the
user reserves product/color quantities for the current device, employee and
branch. The server writes the grant atomically and the SQLite tenant database
protects its physical branch, color and aggregate product ledgers with triggers.
Direct inventory edits, product deletion/identity changes and online sales that
would cross a held floor are rejected with a stock conflict. Shared-catalog
aggregate mirrors receive one-use synchronization tickets, so the protection
does not weaken the existing branch/color source of truth.

The reservation and return endpoints are idempotent by UUID. A return freezes
local rows before transmission and never releases them on timeout; the user
resumes the same request after reconnect. The server accepts returns only from
the original device, employee and branch. A reserved supplier sale consumes the
exact product/color allocation, creates an `OFF-<device>-<counter>` local number
and stores the draft plus allocation consumption in one encrypted checkpoint.
Reconnect sends the original allocation IDs with the existing durable sale
receipt UUID; quota consumption, stock deduction, supplier offset and receipt
are one server transaction. Replays return the same invoice.

This controlled final offline workflow applies to supplier sales with a
pre-granted quota. A cached quantity alone cannot authorize a sale. Unused quota
can be returned only by the original device/user/branch. Lost-device recovery
and administrative reconciliation are still unimplemented; never manually release
a missing device's allocation without reconciling its unsynchronized invoices.
No timer releases a quota. Stage four below adds a coordinated POS transaction;
specialty food/wholesale ledgers still require their own quota adapters.

Stage-three verification uses isolated tenants and encrypted temporary profiles:

- Backend quota tests: 4 focused tests, including concurrent last-piece grants,
  online writer protection, color allocation, idempotent reserve/return, foreign
  device rejection and reserved supplier replay.
- Desktop quota tests: 5 cases, including interrupted reserve/return recovery,
  offline local number allocation, exactly-once reconnect, checkpoint rollback,
  scope change and malformed grant rejection.
- Full desktop build/type/lint checks passed after integrating the quota bridge.

The remaining production gates are large-data snapshot timing, installer and
Windows 7 smoke tests, backup/recovery, and cross-module stock-writer tests for
specialty ledgers. Standalone collections/cancellations still need coordinated
domain transactions before offline operation can be enabled.

## Stage four delivered: reserved POS checkout and collection

The POS keeps its existing online checkout and adds a compact violet device-quota
strip. Reserve the current cart online, then select sale from the device quota;
disconnected checkout automatically uses the quota. New invoices support cash,
bank-account collection and credit. Editing old invoices and creating new customers
still require connectivity. Credit represents goods handed over, so stock is
deducted and the invoice delivered while its payment remains unpaid.

The main process validates the cached customer/product/color/account and current
permission lease. Quota consumption, local receipt number, payment intent and
immutable checkout UUID share one encrypted durable checkpoint. Repeating the
checkout UUID returns the same receipt, including after restart. Supplier and POS
sales consume the same local stock pool, so neither can resell an exhausted quota.

`POST /api/v1/desktop/sync/pos-sale` reuses native checkout with an explicit external
transaction owner. Inventory, invoice, treasury payment ledger, commission and
durable replay receipt commit together. The original local sale time is retained
on the invoice and collection ledger. Invalid accounts, changed prices, revoked
permissions or inadequate allocations remain conflicts; they never free locally
used stock automatically. Deferred-stock policy cannot postpone stock deduction
for a completed reserved offline sale. Independent special ledgers are rejected
at reservation and replay, with conversion guards while stock is held.

Local POS receipts are printable/reprintable through trusted IPC using persisted
operation data. Their HTML escapes all customer/product/color strings, forbids
network resources and scripts, and shows pending synchronization or the mapped
server invoice. Physical-printer and Windows 7 checks remain production gates.
The complete snapshot now optionally includes payment accounts for users who can
collect payments; previously cached authorized accounts also work offline.
The session advertises `offline_pos_enabled` only on the supported database
engine. Old/missing capability prevents new local POS checkout and retains
existing queued sales until a compatible server is available. Deploy the backend
changes and verify a fresh online session before using desktop 0.3.2 offline POS.

Financial reports and existing customer/supplier balances are display copies and
do not yet project unposted local transactions. Use the synchronization queue and
local receipt to inspect unposted sales until reconnect updates server balances.

Stage-four verification used isolated tenants and temporary encrypted profiles:

- The final complete frontend suite passed 167 cases with two workers. An earlier
  concurrent build/test run hit UI timeouts; limiting workers resolved those
  timeouts without changing behavior or assertions. Coverage includes older-server
  rejection and mixed POS/supplier consumption of the same stock pool.
- Expanded backend coverage passed 63 cases; one old private catalog import was
  updated to the extracted service, and both color-display cases then passed.
- Four Electron integration flows passed: POS quota/offline restart/reconnect,
  complete snapshot, supplier draft recovery and native supplier workbench.
- The packaged Windows 10/11 executable also passed the POS offline/restart/sync
  smoke test. Desktop 0.3.2 installer builds successfully; real printer, Windows 7,
  installation and live server deployment remain unverified.
