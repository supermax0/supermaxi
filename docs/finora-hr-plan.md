# FINORA HR Workspace

## Project assessment

The desktop uses React/TypeScript, the existing floating workspace and FINORA colour tokens. Flask staff sessions, tenant-specific databases, RBAC and branch scoping remain authoritative. `Employee` currently represents a login account; it is not suitable for requiring every HR employee to have credentials. Existing payroll, commission lines, treasury transactions, expenses and double-entry journals must be reused rather than replaced.

At the start of this work, the missing pieces were independent employment profiles, dated contracts, shifts, attendance/leave workflows, approved payroll snapshots and partial payouts, advance receivables, recruitment and permission-scoped HR offline data. These are now implemented in the additive HR workspace.

## Implementation sequence

1. Add tenant-local HR profiles linked optionally to existing login accounts; additive schema only. Preserve existing employees and financial records. Add granular permissions and immutable command/audit records.
2. Build the six-tab desktop workspace with server pagination, filters, employee drawer and real create/edit actions using the existing components and tokens.
3. Add dated shifts, attendance events, overnight calculations, corrections and leave approval with version checks.
4. Implement reviewed/approved payroll snapshots, partial payments and advance instalments, using existing treasury and journals in one transaction. Integrate existing commission sources without duplicating entitlements.
5. Add employment history, documents/contracts, performance, offboarding and existing-asset assignments.
6. Add versioned recruitment forms, expiring/PIN-protected links, validated submissions and deliberate applicant conversion.
7. Integrate scoped offline reads/non-financial commands, reports, approval notifications and verification.

Each stage requires focused tests before the next. Financial operations require a central acknowledgement; offline actions remain pending until replay succeeds. No statutory tax or leave assumptions are hard-coded. Baghdad time is used for local attendance dates, UTC for stored timestamps.

## Verification and rollout

Use isolated temporary tenants, existing pytest/Vitest/Playwright runners, RBAC and branch isolation tests, command replay/conflict tests, payroll/treasury/journal reconciliation and real desktop layout checks. Existing accounting and offline stock tests remain regression checks. Deployment requires the matching server and desktop build; old cached HR permissions must be replaced through an online session.

## Implemented in desktop 0.4.0

- Six RTL tabs under the existing More menu, paginated directories, the employee drawer on the right, personal profiles with optional login accounts, emergency/private information and dated financial contracts.
- Dated day/night shifts, attendance, a monthly calendar, holiday policies, correction requests with approval and optimistic versions, leave balances/half-days/individual entitlements, and atomic bulk changes.
- Draft/review/approve payroll, frozen source calculations, partial payouts, advance instalments, six commission policies and cancellation/restoration reconciliation. Expenses, treasury withdrawals, native employee payments and journals stay connected without duplicate posting. Payroll reports include accounting reconciliation.
- Personnel documents, custody of existing fixed assets, reviews/goals/actions, termination snapshots and printable final settlement statements.
- Versioned recruitment forms, thirteen field types, expiring/PIN-protected public links, uploads, application review and deliberate conversion into an employee.
- An approval center inside the existing workspace. A unified employee financial statement follows actual payable journals, separates cash payments from offsets, links each row to its source document and keeps advance receivables separate. Legacy direct payouts appear once as closed historic payments; their original entitlement date is not inferred.
- Granular RBAC and tenant/branch/department/manager/self scoping, scoped alerts, Excel/native PDF/print exports and private audit history. A full financial statement requires salary, commission and advance visibility (or ownership); an ordinary HR directory permission does not disclose financial amounts.
- Encrypted, permission-scoped offline snapshots and durable non-financial commands. Reconnection replays the original UUID and timestamp; stale versions become visible conflicts. An uncertain financial acknowledgement must be resolved using the original command before another payout. Only definitively rejected non-financial drafts may be discarded.

## Operational boundaries

An online session and a complete permitted HR download are required before using HR offline. Attendance history in the baseline bundle covers recent days; previously visited monthly calendars may be available locally. Full financial statements, private file downloads, recruitment management and full exports require the server. Offline employee creation is a queued draft; it receives its central profile only after successful synchronization.

Payroll approval closes a completed calendar month. A mid-month termination produces an accrued settlement snapshot; it does not silently approve the unfinished month or issue cash. Leave encashment, statutory taxes, carryover rules and company retention periods must follow configured company policy; no legal rate or destructive data-expiry rule is invented. Existing private documents and application data are retained until an authorized company retention policy is defined.

Roll out the matching Flask server code before enabling the 0.4.0 desktop. Additive schema initialization and legacy backfill run in each tenant's context; existing accounting records and legacy clinic HR routes are preserved. Back up tenant databases before production rollout. This work builds the installer; it does not deploy to an external server or install over a running user session.

## Verification recorded on 2026-10-10

- All 37 backend HR tests passed after the financial statement, settlement export and granular financial visibility changes (`tests/_artifacts/hr-backend-final.log`). Coverage includes native payroll/treasury/GL linkage, replay, partial payments, advanced/legacy commissions, private data, recruiting, dated calendars/corrections, bulk rollback and scopes.
- All 180 desktop unit tests passed (`hr-vitest-final.log`); the subsequent report/IPC checks passed all 27 targeted tests (`hr-release-targeted.log`). The shared dialog focus change also passed the supplier sale unit regression.
- TypeScript checks, ESLint, Prettier checks and the production renderer/Electron build passed.
- Six real Electron E2E cases passed (`hr-release-e2e.log`): HR layout/profile/corrections/approval center/financial document/calendar, encrypted HR restart/replay, three existing POS/offline scenarios and the supplier workbench. After the final visual/focus adjustment, all three affected HR/supplier E2E cases passed again (`hr-visual-final-e2e.log`). Layout screenshots cover 1180, 1536 and 1920 window widths.
- Final compact-layout checks passed all three affected HR/supplier cases (`hr-toolbar-e2e.log`). The first employee row must stay fully visible at all three tested widths; financial KPI values stay complete, selected-row CSV requires the report permission, and modal focus restoration preserves the drawer scroll position. The latest production build is recorded in `hr-toolbar-build.log`.

The desktop E2E tests use isolated temporary profiles and an explicit test server fixture. They verify real renderer/IPC/encrypted persistence; real Flask tenant and accounting behavior is verified separately by the backend integration tests. They do not prove a deployment to an external production server.

The Windows 10/11 x64 NSIS installer was built successfully as version 0.4.0 (`hr-installer-final.log`). The packaged executable itself passed the encrypted HR snapshot/restart/offline replay case (`hr-packaged-smoke.log`). Packaged JavaScript, CSS and WebAssembly assets were compared byte-for-byte against the latest tested build; the installer size and SHA-256 are recorded in `tests/_artifacts/hr-release-integrity.json`.
