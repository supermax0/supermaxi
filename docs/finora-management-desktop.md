# FINORA Management Desktop

Windows desktop client (Electron + React + TypeScript) for FINORA's orders,
purchases and products. Code: `desktop/finora_management/`. Endpoint mapping:
[`finora-integration-map.md`](finora-integration-map.md).

## 1. Architecture analysis (existing FINORA)

- **Backend**: one Flask app (`app.py`) with ~60 blueprints in `routes/` and feature
  modules in `modules/`. Multi-tenant: a Core DB (PostgreSQL in production) holds
  tenants; each tenant has its own database, selected per request via `g.tenant`
  (`extensions_tenant.py`).
- **Staff auth**: server-side Flask session (`session["user_id"]`, `tenant_slug`,
  `role`, …) created by `routes/index.py:login`; `app.require_login` binds `g.tenant`
  and redirects anonymous requests to `/login`. RBAC: `models/role.py` +
  `utils/permission_checks.employee_can` (admin = all; legacy role bridge).
  `guard_permission` answers JSON 403 for XHR/JSON requests.
- **Bearer APIs that exist** (`/api/v1/pos`, `/api/phone/v1`, `/api/v1/store`,
  `/api/v1/finora-core`) serve other clients (POS machine, phone companion, store,
  super-admin desktop) and do **not** expose order/purchase/product management.
- **Orders** (`routes/orders.py`): paginated JSON grid `/orders/data` with search,
  tabs and filters; atomic bulk status with stock checks; shipping/agent updates;
  details JSON; print pages. **Purchases** (`routes/purchases.py`): JSON list/detail/
  update/cancel (unpaginated list). **Inventory** (`routes/inventory.py`): mostly
  server-rendered pages + a movements JSON endpoint.
- **Real-time**: no SSE/WebSocket for these domains (FINORA CORE's SSE outbox is
  super-admin only) → smart polling.
- **No CSRF middleware**; session cookie `HttpOnly`, `SameSite=Lax`, 7-day lifetime.

**Decision**: the desktop signs in to the **same staff session** as the web and calls
the existing JSON endpoints. The only backend addition is
`modules/desktop_api` (JSON sign-in / session probe / sign-out), built on
`services/staff_auth.py`, which the web login now also uses — one implementation,
two clients. Missing list/lookup endpoints are documented as blockers (integration map §4)
and will be added as thin read adapters in their milestone.

## 2. Desktop architecture

```
electron/                         (main process — Node, privileged)
  main/index.ts                   window (frameless, 1440×900 → work area, min 1180×700),
                                  single instance, IPC handlers with sender checks,
                                  navigation/window-open/webview/permission lockdown
  main/finoraHttp.ts              all FINORA traffic: session.fetch on partition
                                  persist:finora-management, cookies never leave main
  main/httpCore.ts                pure helpers: URL building, headers, response
                                  classification (login redirect ⇒ unauthenticated, …)
  main/config.ts                  non-secret settings (server URL, last tenant/user)
  preload/index.ts                sandboxed preload → window.finoraDesktop (typed bridge)
shared/
  ipc.ts / channels.ts            IPC contract + zod validation (path allow-list,
                                  traversal refusal, JSON-only bodies, origin-only URLs)
src/                              (renderer — React, no Node)
  api/finora/                     the ONLY way to reach FINORA: finora.auth.*, …
                                  transport.ts (bridge + zod parse), errors.ts (unified
                                  Arabic error layer), schemas.ts, transportEvents.ts
  stores/                         zustand: windowManager, session, connection,
                                  notifications, toasts, ui, preferences
  windows/                        registry, WindowTransitionManager, FinoraWindow,
                                  WindowHeader, orders/ purchases/ products/
  animations/                     morph geometry, nav anchors, variants/transitions
  components/                     TopNavigation, NavButton, WindowControls, Popover,
                                  CommandPalette, NotificationsPanel, SettingsPanel,
                                  Toaster, OfflineBanner, EmptyState, IconButton, FinoraLogo
  features/auth/LoginScreen.tsx
  hooks/                          useSessionProbe, useFinoraLifecycle, useSignOut, useHotkeys
  theme/index.css                 tokens (RGB channels) + glass utilities, Tailwind
```

**Security**: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`,
strict CSP (`script-src 'self'`), every IPC call checks the sender frame and validates
its payload with zod; the renderer can only reach allow-listed FINORA prefixes
(`/api/v1/desktop/`, `/orders/`, `/purchases/`, `/inventory/`, `/suppliers/`,
`/shipping/`, `/delivery/`). No token/cookie/password in localStorage or logs; the dev
request log prints method, path, outcome and timing only.

**Window system**: `useWindowManager` holds `active` (orders | purchases | products |
null). `WindowTransitionManager` renders only the active window inside
`AnimatePresence` (sync mode), so a switch is one state change: the leaving window
runs its exit morph back into its nav button while the new one grows out of its own
button — concurrently, and a window re-requested mid-exit is re-entered instead of
duplicated. Each window has two layers: an empty glass **shell** that is morphed with
transforms only (translate + scale, radius pre-divided by scale, opacity, 8px→0 blur)
and a **content** layer that never scales (fades in after ~170 ms, out in ~110 ms).
Origin rects come from DOM refs registered by each `NavButton`; geometry is resolved
when the variant runs, so window resizes and the expand toggle stay correct. Open 440 ms,
close 360 ms. Reduced motion (OS setting or Settings toggle) keeps only fades.

**Session & connectivity**: startup probe → sign-in or shell; revalidation every 5 min
and on focus (permission changes in FINORA flow in). Any `unauthenticated` answer ⇒
"انتهت الجلسة" sign-in screen; `network/timeout` ⇒ "لا يوجد اتصال بـ FINORA" banner,
read-only (`canMutate()`), probe every 8 s, and full refetch on reconnect. TanStack
Query keeps previous data while refetching (tables never blank).

## 3. Implementation plan

| Milestone | Scope | Backend work |
|---|---|---|
| **1 — done** | Electron shell, theme, logo, top navigation, native window controls, window manager + morph animations, sign-in/session/sign-out, offline banner, notifications, settings, quick search (Ctrl+K), toasts | `modules/desktop_api` + `services/staff_auth.py` |
| 2 — Orders | `DataTable` (TanStack Table, memoized rows, 64 px rows), status tabs with counts, server search (300 ms debounce), filter panel, selection + select-page, print selected (hidden print window on the session partition), bulk status (confirmation + 409 stock-selection flow), shipping/agent changes, row context menu, pagination 10/25/50/100, 20 s polling while open, optimistic status with rollback | B1 lookups, B5 date/amount range |
| 3 — Products | stats, list, search + barcode scanner (keyboard-wedge detection), category quick filters from API, stock status, detail side panel with movements | B2, B6 |
| 4 — Purchases | summary cards, list, tabs, filters, context actions, cancel (confirmation), payments, print | B3 decision, B4 |
| 5 — Polish | keyboard navigation, column hiding < 1280 px, permission-driven actions everywhere, performance pass, packaging (installer, auto-update, deep links) | — |

Each milestone ships only after `npm run verify` (format, lint, typecheck, unit tests,
build), the Electron E2E (`npm run e2e`) and the backend tests pass.

## 4. Milestone 1 — verification

- Backend: `python -m pytest tests/test_desktop_api.py tests/test_credential_security.py` → 22 passed
  (desktop sign-in/session/sign-out, rate limit, one-time password refusal, and the
  refactored web login).
- Desktop: `npm run verify` → prettier, ESLint (strict, no `any`, no ts-comments, no
  floating promises, no empty catch, no TODO/FIXME), 3× `tsc`, Vitest (window manager,
  morph geometry, error layer, IPC validation, transport classification, auth API,
  full shell integration), production build.
- Electron E2E (`npm run e2e`, real app + local auth stub): frame-sampled proof that a
  window grows out of its button monotonically to full size; orders→products→purchases→orders
  switching (both windows during the switch, exactly one after); rapid switching settles
  on the last click at full size; native maximize/restore; renderer has no
  `require`/`process`; disallowed and traversal paths refused; session cookie invisible to
  the renderer but used by main; offline banner and auto-reconnect; session persists
  across restart; sign-out ends it and remembers only tenant + username.

## 5. Running

```bash
cd desktop/finora_management
npm install
npm run dev            # Vite + Electron, FINORA_SERVER_URL defaults to http://localhost:5008
npm run build && npm start
npm run verify && npm run e2e
```

The FINORA server must include `modules/desktop_api` (restart it after pulling).

## قائمة «المزيد» (Navigation Hub)

The `LayoutGrid` button in the top bar opens a panel that grows out of the bar (CSS morph on transform/opacity:
200ms open, 150ms close, `cubic-bezier(0.22, 1, 0.36, 1)`, respects `prefers-reduced-motion` and the app's reduced-motion
preference). Ctrl+K and «المزيد» close each other.

- **Data source (single):** `src/navigation/config.ts` → `NAV_GROUPS`. It ships **empty**. Add a group, or add items to
  an existing group, there; nothing else changes. Item = `{ id, label, description?, icon, keywords?, permission?,
  target }`, where `target` is `{ kind: "window", window }` (existing window navigation) or `{ kind: "run", run }`.
- **Search (shared with the Ctrl+K palette):** `src/navigation/search.ts`.
  - Arabic and English, with variant letters, diacritics and digits normalized.
  - Partial words; the «ال» prefix is optional.
  - Synonyms come from `keywords`.
  - Every query word must match, and results are ranked.
- **Permissions:** an item is hidden without its `permission`. A window target inherits the window's permission.
  Groups left empty are not shown.
- **Favorites / recent:** `src/stores/navigationPrefs.ts` (localStorage, by item `id`). The two sections are hidden
  while they are empty.
- **Tests:** `src/navigation/navigation.test.tsx` and the E2E «المزيد» test in `e2e/shell.spec.ts`.
