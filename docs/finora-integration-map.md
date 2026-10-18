# FINORA Management Desktop — Integration Map

Every desktop feature is listed with the FINORA code that already implements it, the
endpoint the desktop calls, the request/response shape, and the permission FINORA
enforces. **FINORA stays the source of truth**: the desktop never re-implements a
rule that lives in a route or service below.

Legend — ✅ endpoint exists and is used as-is · 🟡 exists but needs a thin JSON/pagination
adapter before the desktop can use it without loading everything · 🔴 missing in FINORA
(documented requirement, not invented in the client).

## 0. Transport and authentication

FINORA's management endpoints (orders, purchases, inventory) are **session-cookie**
endpoints guarded by `app.require_login` + `utils.permission_checks`. They do not
accept bearer tokens. The desktop therefore uses the **same staff session as the web
app**:

| | |
|---|---|
| Sign-in | `POST /api/v1/desktop/auth/login` (new, `modules/desktop_api/routes.py`) |
| Why new | The web `/login` is an HTML form (renders errors as HTML, redirects). The desktop needs the same check with a JSON answer. It calls the **same** helpers as the web login (`services/staff_auth.py`, extracted from `routes/index.py:login`) so both clients produce an identical session. |
| Session probe | `GET /api/v1/desktop/auth/session` → user, tenant, branch, roles, permissions |
| Sign-out | `POST /api/v1/desktop/auth/logout` |
| Cookie storage | Electron main process, partition `persist:finora-management` (Chromium cookie store, encrypted at rest with DPAPI on Windows). The renderer never sees it (`document.cookie` is empty, verified by E2E). |
| Expiry | `PERMANENT_SESSION_LIFETIME` (7 days). A redirect to `/login` or a `401` ⇒ "انتهت الجلسة" → sign-in screen. |
| One-time passwords | `must_change_password` ⇒ `403 password_change_required`; no session is opened. The user changes it on the web first. |
| Rate limit | 10 sign-in attempts / minute / IP (reuses `modules/pos_api/services/rate_limit.allow_request`). |
| Headers sent | `Accept: application/json`, `X-Requested-With: XMLHttpRequest` (makes `guard_permission` answer JSON 403 instead of redirecting), `X-Finora-Client: management-desktop/<version>` |

Request shape (login): `{"tenant_slug","username","password"}` →
`{"ok":true,"session":{"user":{id,name,username,role},"tenant":{id,slug,name,business_type},"branch":{id,name}|null,"roles":[...],"permissions":[...],"session_max_age_seconds"}}`.
Errors: `{"ok":false,"error":"<Arabic>","code":"validation_error|tenant_not_found|tenant_inactive|invalid_credentials|user_inactive|password_change_required|rate_limited|unauthenticated"}`.

Permissions reported (`DESKTOP_PERMISSIONS`): `can_see_orders`, `can_see_orders_{placed,packed,shipped,delivered,returned}`,
`manage_orders`, `delete_orders`, `return_orders`, `pay_orders`, `print_pos_invoice`,
`can_manage_inventory`, `edit_product`, `edit_price`, `edit_current_stock`,
`can_manage_suppliers`, `view_all_branches`. The UI hides actions without the
permission; FINORA still enforces every call.

## 1. Orders (Milestone 2)

Backend: `routes/orders.py` (`orders_bp`, prefix `/orders`), model `models/invoice.Invoice`
(+ `Customer`, `ShippingCompany`, `DeliveryAgent`), stock rules `utils/order_stock_policy.py`.

| Desktop feature | Endpoint | Request | Response | Permission | Status |
|---|---|---|---|---|---|
| Orders list (server pagination, sort) | `GET /orders/data` | `page`, `page_size` (≤ grid max), `page_type=all\|ordered\|packed\|shipping\|delivered\|returned`, `sort_field`, `sort_dir` | `{success, rows[], page, page_size, total, total_pages, total_amount, total_quantity}` | `can_see_orders` + per-tab `can_see_orders_*`; non-admins limited by `allowed_order_statuses_for` | ✅ |
| Search (order #, customer, phone, city, address) | same, `search=` | debounced 300 ms, server-side (`_orders_search_condition`) | same | same | ✅ |
| Filters: status / city / shipping company / delivery agent | same, `status=`, `city=` (repeatable), `shipping=<name>`, `delivery_agent=<name>\|none` | | | | ✅ |
| Filters: date from/to | same, `date_from=`, `date_to=` | added to `_orders_data_query` (shared by the web grid) | | | ✅ |
| Filters: min/max amount | same, `amount_min=`, `amount_max=` | added to `_orders_data_query` | | | ✅ |
| Status tab counts | `GET /orders/api/counts` (+ same filters) | `{success, counts:{all, ordered, packed, shipping, delivered, returned}}` — same query as the grid, tabs without permission omitted | | `can_see_orders` + per-tab | ✅ |
| Status mapping / colors | FINORA stores Arabic status strings: `تم الطلب`, `معباة`, `جاري الشحن`, `تم التوصيل` (+`واصل/واصلة`), `راجع` (`RETURN_STATUS`) / `ملغي` | | | | ✅ the Milestone 2 mapping is keyed by FINORA's stored values, not by display labels |
| Order details | `GET /orders/details/<id>` | | JSON (items, customer, payments) | `can_see_orders` + `guard_order_access` | ✅ |
| Change status (bulk or single) | `POST /orders/bulk-status` | `{order_ids:[...], status, selected_order_ids?}` | `{success, updated, updated_ids, skipped_ids}`; `409 STOCK_SELECTION_REQUIRED` with `shortages`/`orders` when stock is short | `manage_orders` (via `required_order_mutation_permission`) | ✅ (allowed targets: تم الطلب/معباة/جاري الشحن/تم التوصيل) |
| Mark returned | `POST /orders/bulk-return` | | | `return_orders` | ✅ |
| Change shipping company | `POST /orders/update-shipping` | `{order_id, shipping_id\|null}` | `{success}` | `manage_orders` | ✅ (one order per call; bulk = N calls) |
| Assign delivery agent | `POST /orders/update-delivery-agent` | `{order_id, agent_id\|null}` | `{success, message}` | `manage_orders` | ✅ (one order per call) |
| Lookups: cities, shipping companies, agents, branches | `GET /orders/api/lookups` | `{success, cities[], shipping_companies[{id,name}], delivery_agents[...], branches[...]}` | | `can_see_orders` | ✅ |
| Print selected (A4 invoices, FINORA templates) | `GET /orders/print-invoices?ids=1,2,3` (HTML print page) | loaded by main in a hidden window of the same session partition → `webContents.print()` | HTML | `print_pos_invoice` | ✅ |
| Print data (custom layouts / thermal later) | `POST /orders/print-selected` | `{ids:[...]}` | `{orders:[{order, items}]}` | session | ✅ |
| Real-time | none (no SSE/WebSocket for orders) | smart polling 20 s while the Orders window is open | | | ✅ polling |

## 2. Products / Inventory (Milestone 3)

Backend: `routes/inventory.py` (`inventory_bp`), model `models/product.Product`
(`sku`, `barcode`, `buy_price`, `sale_price`, `quantity`, `low_stock_threshold`,
`image_url`, `catalog_category`, `active`), per-branch stock `models/branch.BranchStock`,
movements `routes/inventory_ledger.py`.

| Desktop feature | Endpoint | Status |
|---|---|---|
| Products list (paginated, search name/SKU/barcode, category & stock filters, sort) | `GET /inventory/api/products` — built on `_inventory_snapshot()`, extracted from the inventory page so both use the same branch/shared-catalog/colour quantities | ✅ |
| Stats (total / available / low / out) | `stats` in the same response (low = qty ≤ `low_stock_threshold`) | ✅ |
| Categories quick filters | `categories` in the same response (`Product.catalog_category`) | ✅ |
| Brand | no `brand` column (may live in `meta_json`) | 🔴 confirm the field before showing the column |
| Reserved quantity | not a column; derived from open orders by the stock policy | 🔴 confirm the definition (`utils/order_stock_policy.py`) before showing it |
| Barcode search | `GET /orders/search-by-barcode` (orders), `GET /purchases/api/products/search` | 🟡 reuse purchase product search for barcode/SKU lookups |
| Product movements (in / sales / adjustments) | `GET /inventory/api/movements/<product_id>` | ✅ |
| Edit product / price | `POST /inventory/edit/<id>` (form post) | 🟡 JSON variant needed; permissions `edit_product`, `edit_price` |
| Manual stock adjustment | `POST /inventory/adjust-stock/<id>` | 🟡 form post; `edit_current_stock`; confirmation dialog required |
| Permission to view | `can_manage_inventory` | ✅ |

## 3. Purchases (Milestone 4)

Backend: `routes/purchases.py` (`purchases_bp`, prefix `/purchases`), model
`models/purchase.Purchase` (+ items, payments, attachments), supplier payments
`routes/suppliers.py`.

| Desktop feature | Endpoint | Status |
|---|---|---|
| Purchases list | `GET /purchases/api/page?tab&page&page_size&search&supplier_id&date_from&date_to` — same rows as `/api/list` via the extracted `_purchase_list_record()` | ✅ |
| Summary cards + tab counts + suppliers | `summary`, `counts`, `suppliers` in the same response | ✅ |
| Details | `GET /purchases/api/<id>` | ✅ |
| Edit | `POST /purchases/api/<id>/update` | ✅ |
| Cancel (confirmation) | `POST /purchases/api/<id>/cancel` — reverses stock/payments in FINORA | ✅ |
| Reopen / unlock edit / clone | `POST /purchases/api/<id>/reopen\|unlock-edit\|clone` | ✅ |
| Record payment | `POST /suppliers/pay/<supplier_id>` (supplier-level) | 🟡 confirm per-purchase allocation semantics |
| Print | `GET /purchases/print/<id>` (HTML) | ✅ |
| Statuses | FINORA has `draft`, `confirmed`, `cancelled` (+ `is_draft`, `stock_applied`, `remaining_total`) | 🔴 the requested statuses (قيد الشراء / قيد الاستلام / مستلم / بانتظار الدفع) do **not** exist; see blocker B3 |
| Receiving | stock is applied when a purchase is confirmed (`stock_applied`); there is no separate receive step | 🔴 see blocker B3 |
| Permission | `can_manage_inventory` | ✅ |

## 3b. Point of sale

Backend: `routes/pos.py` + `services/pos_checkout.py` — the same checkout as the web POS (FINORA prices each line, enforces `edit_price`, colours, branch and stock rules, de-duplicates by `submission_token`).

| Desktop feature | Endpoint | Permission | Status |
|---|---|---|---|
| Provinces, branch, can_edit_price / can_print / can_pay | `GET /pos/api/bootstrap` (new, read-only) | `view_pos` | ✅ |
| Catalogue (paginated, search name/SKU/barcode, categories) | `GET /pos/api/products` (new; same product set as `/pos/all-products`) | `view_pos` | ✅ |
| Customer search / add | `GET /pos/search-customer`, `POST /pos/add-customer` | `view_pos` | ✅ existing |
| Checkout / edit invoice | `POST /pos/create-order` (`order_id` for edits) | `view_pos` | ✅ existing |
| Sale type نقد / بنك | after checkout `POST /orders/payment` (`مسدد`, one allocation to the branch cash drawer or the chosen bank account from `/orders/payment-accounts`) | `pay_orders` | ✅ existing |
| Sale type أجل | order stays `غير مسدد` (receivable) | — | ✅ |
| Print | `/orders/print-invoices?ids=` print window | `print_pos_invoice` | ✅ existing |

If the payment step fails after the order was created, the cashier is told the order number and that payment must be recorded from the Orders window — the order is never silently lost or duplicated.

## 3c. Suppliers (native management workbench)

Open **المزيد → الموردين**, search with Ctrl+K, or use Ctrl+6. Requires
`can_manage_suppliers` and the existing supplier feature entitlement.

| Desktop feature | FINORA endpoint / service |
|---|---|
| Search, balance tabs, sorting, pagination and account summary | `GET /suppliers/api/page` (`search`, `tab=all/debt/credit/settled`, `sort=name/balance/recent`, `min_balance`, `page`, `page_size`) |
| Contact details, purchase invoices, payments, sales and treasury choices | `GET /suppliers/api/<id>` |
| Create with optional opening balance | `POST /suppliers/api/create` |
| Edit contact fields without changing balances | `POST /suppliers/api/<id>/update` |
| Record supplier payment with treasury validation and FIFO allocations | `POST /suppliers/api/<id>/pay` → `create_supplier_cash_payment()` |
| Search sale products by name, SKU or barcode with branch stock and colors | `GET /suppliers/api/sale-products?q=...` |
| Sell to supplier from the sales tab, previewing the resulting balance | `POST /suppliers/api/<id>/sale` → `create_supplier_sale()`; deducts stock and records an offset against the supplier account, with no cash treasury movement |
| New purchase | Existing native purchase composer, with the selected supplier; replacement of an existing draft requires confirmation |
| Print statement | IPC `kind=supplier` → existing `/suppliers/statement/print/<id>` in the session-protected print window |
| CSV | Current page or selected rows on that page; Arabic UTF-8, formula-safe text cells |

The server respects independent branch scope and combines shared supplier copies
by the existing supplier identity rule. Account totals come from FINORA, while
purchase totals exclude drafts and cancelled invoices. A negative remaining
balance is shown as credit owed to the company. Due dates, email, supplier
categories and return counts are not invented because the supplier model does
not provide them. Contact edits preserve the identity of shared branch copies.

## 3d. Offline foundation and synchronization

Electron main persists scoped cached reads and supplier-sale drafts in encrypted
SQLite. Settings → الأوفلاين والمزامنة displays queue state and stock conflicts.
Previously loaded data survives offline restarts for the same recently verified
user and branch; the initial authorization lease is capped at 24 hours.

`POST /api/v1/desktop/sync/supplier-sale` uses a durable device/operation UUID
receipt and calls the existing supplier-sale domain service. Sale, supplier
offset, stock deduction and receipt commit together. Replaying the same payload
returns the original invoice; changing it returns 409. Insufficient stock also
returns a conflict, retaining the local draft for review.

When local access is ready, native supplier sales use this durable path online
as well. Other financial operations require connectivity.

Settings also downloads a complete, permission-scoped generation through
`POST /api/v1/desktop/snapshots` and immutable hashed pages from
`GET /api/v1/desktop/snapshots/<id>/<dataset>?cursor=N`. Sixteen native dataset
families cover product/color search, customers, suppliers, orders, purchases and
their details. Local query adapters support unseen records, search, filters and
pagination. Each page is durably checkpointed; restart resumes the next page.
Publication replaces the previous generation only after verifying completeness,
and removes deleted records. Confirmed financial synchronization marks this
display copy stale. Images/reports still require connectivity. Supplier sales may use a pre-granted device quota: reservation and
return are idempotent, held stock is protected by tenant SQLite triggers, and a
reserved offline sale consumes its product/color allocation in the same encrypted
checkpoint as its local number. Reconnect sends the allocation with the existing
durable sale receipt. Reserved POS checkout also stores a local receipt and cash,
bank or credit intent; `/api/v1/desktop/sync/pos-sale` commits native invoice,
stock, collection ledger, commission and replay receipt together. The original
sale time is retained. Local POS receipts can be printed without connectivity.
Standalone collections, edits, cancellations and specialty warehouse ledgers
remain online-only; existing balances do not yet project local pending sales. See
[the implementation plan](finora-offline-plan.md).

## 4. Status of the original blockers

- **B1 order lookups, B2 products JSON, B4 purchases pagination/summary, B5 date/amount ranges** — done as thin read adapters in the existing blueprints (tests: `tests/test_desktop_data_api.py`, incl. permission parity with FINORA's own endpoints).
- **B3 purchase lifecycle** — implemented option (a): tabs map to FINORA's real states — مسودة (`draft`), مستلم (`confirmed`, stock applied, fully paid), بانتظار الدفع (`confirmed` with `remaining_total > 0`), ملغي (`cancelled`). No separate "receiving" step exists in FINORA, so none is invented.
- **Still open — B6:** product *brand* (no column) and *reserved quantity* (not a stored value) are not shown until FINORA defines them.
- **Edits that need FINORA's full forms** (order edit, purchase edit, product edit) open the matching FINORA web page in the browser instead of duplicating the forms. Supplier contact edits and payments use the native workbench above.

## Expenses window (المصاريف)

| Desktop feature | FINORA endpoint | Rules reused |
|---|---|---|
| Categories + treasury choices | `GET /expenses/api/meta` | `get_expense_categories`, `treasury_choices_for_form` |
| List, tab counts, period totals, by-category | `GET /expenses/api/page` | posts due scheduled expenses first (same as the web page); `sum_posted_expenses`; branch scope from the ORM |
| Add (single or recurring) | `POST /expenses/api/create` | `create_expense_batch` — the same function the web form uses (balance check, due-now posting, scheduled series) |
| Delete (refund when posted) | `POST /expenses/delete/<id>` (XHR → JSON) | existing route; payroll expenses are refused |
| New category | `POST /expenses/categories/add` | existing route |

Permission: `view_expenses` (FINORA `can_see_expenses`). Tests: `tests/test_expenses_api.py`,
`desktop/finora_management/src/windows/expenses/expenses.test.tsx`, E2E «expenses page» in `e2e/shell.spec.ts`.

## Shipping & Logistics Center (مركز الشحن والتسويات) — phase 1

Backend: `modules/desktop_api/shipping_center.py` (prefix `/api/v1/desktop/shipping-center`, JSON, GET/POST only).
It works over FINORA's own `ShippingReport` manifests — no new tables.

| Desktop feature | Endpoint | Rules reused |
|---|---|---|
| Carriers, agents, treasury accounts, approve/manage flags | `GET meta` | `_unique_shipping_companies`, `treasury_choices_for_form` |
| Six overview cards | `GET overview` | `order_payment_snapshot` / SQL remaining amount |
| Carrier / agent tables and profiles (orders by bucket, manifests, statement) | `GET carriers`, `GET carriers/<id>`, `GET carriers/<id>/orders`, `GET agents`, `GET agents/<id>`, `GET agents/<id>/orders` | carriers merged by name like the web shipping page; statement = `ShippingPayment` |
| Manifest list / details with analysis | `GET manifests`, `GET manifests/<id>` | analyzer flags: missing, duplicate, other carrier, closed / already paid, open elsewhere, status mismatch, unclassified |
| New settlement manifest (`STL-…`, carrier reference, date) | `POST manifests` | stored as a `ShippingReport`; meta in `notes` |
| Add rows (order no. / invoice barcode / waybill, up to 500) | `POST manifests/<id>/rows` | `find_order_by_code` |
| Remove row / save classification draft | `POST manifests/<id>/rows/<order>/remove`, `POST manifests/<id>/selections` | draft only — nothing in orders or treasury changes |
| Approve | `POST manifests/<id>/approve` | admin only; refused (409) when blocking issues remain or received ≠ expected net; runs `execute_shipping_report` (واصل → paid + treasury; راجع → «ملغي» with stock restored; مؤجل stays with the carrier) |
| Handover manifest (`KSH-…`) | `POST handover`, `POST lookup` | `routes.orders._create_shipping_report_from_ids` |

Expected net = Σ remaining(واصل) − Σ shipping fee line(واصل). Differences are never auto-corrected; approved manifests are
immutable (correct with a new manifest).

Permissions: `can_see_shipping` (view) and `can_manage_shipping` (create / edit manifests). Approval is admin only.
Phase 2 is documented below; still not built: period/branch filters, xlsx import (phase 3 analytics).

### Phase 2 — accounting links (`modules/desktop_api/shipping_center_finance.py`, `models/shipping_center.py`)

| Feature | Endpoint | Rules reused |
|---|---|---|
| Partial settlement | `POST manifests/<id>/approve` with `allocations {order_id: amount}` | each «واصل» row is paid up to its allocation by `execute_shipping_report` (full, FINORA piece settlement, or 0 = carried while the carrier still owes it); the courier fee is withdrawn once per order (`_find_delivery_withdraw_tx`); received must equal Σ allocations − fees due − return fees exactly |
| Receipt voucher (سند قبض) | created on approval; `GET receipts`, `GET receipts/<id>/print` | `receipts` / `receipt_allocations` rows (`RCV-SHP-…`, no journal of their own — cash is posted by the executor; no report sums this table) |
| Account statement | `GET carriers|agents/<id>/statement` | debit = an order's due amount the first time it is reported delivered; credit = courier fees, return fees, receipts; running balance = still owed |
| Agent custody / portal settlement | `GET agents/<id>` (`custody`), `GET agents/<id>/portal`, `POST manifests {agent_id, from_portal}` | rows + the agent's own classification from open `AGT-` portal reports (kept as `agent_claim`, differences flagged); settled orders are detached from those portal reports so they can never execute twice |
| Carrier settings | `GET/POST carriers/<id>/settings` | default fee = FINORA's `ShippingCompany.price`; return fee posted as an expense with `routes.expenses._post_expense_to_treasury` |
| Returns lifecycle | `GET returns`, `GET returns/<id>`, `POST returns/receive {code|return_id}`, `POST returns/<id>/close` | «راجع» on approval only registers `awaiting`; receipt → `received`; inspection closes with `process_order_return` (FIFO restock to the chosen branch, sale + collection reversal) and damaged quantities via `modules.stock_operations.writeoffs.post` (inventory-loss journal; needs `edit_current_stock` + `finance.approve` + `finance.view`) |

Behaviour change from phase 1: an approved «راجع» no longer restocks immediately — it waits for physical receipt and inspection.

### Follow-up (`modules/desktop_api/shipping_center_insights.py`, read-only)

| Feature | Endpoint | Rule |
|---|---|---|
| Missing orders in a settlement manifest | `GET manifests/<id>/missing` | orders of the manifest's carrier / agent still shipped or delivered with money due and not in this manifest; oldest first; flags orders already in another open settlement |
| Overdue | `GET overdue?days=N` | parcels «جاري الشحن» out more than N days, returns not received / inspected, settlement drafts open more than N days |

Days out are measured from `stock_deducted_at` (when the order left the shelf), falling back to `created_at`; both are UTC.

Tests: `tests/test_shipping_center_api.py`, `tests/test_shipping_center_phase2.py`, `desktop/finora_management/src/windows/shipping/shipping.test.tsx`, `phase2.test.tsx`,
E2E «shipping center» + «shipping center phase 2» in `e2e/shell.spec.ts` (stub: `e2e/shippingStub.ts`).

### Dispatch from the orders page and the shipping center («تسليم وإسناد»)

One dialog (`windows/shipping/Dispatch.tsx`) with three modes, preloaded from the selected orders and fed by barcode scan / paste:

| Mode | Endpoint | FINORA rule reused |
|---|---|---|
| كشف مندوب | `POST /api/v1/desktop/shipping-center/agent-report` | `routes.orders.create_agent_report_internal` — links orders to the agent, dispatches them, creates the `AGT-` manifest shown in the agent portal; refuses duplicates / executed orders |
| إسناد لمندوب | `POST /orders/update-delivery-agent` (per order) | FINORA's own assignment (stock-lock check, audit log); the order shows in the portal as a single order |
| تسليم لشركة نقل | `POST /api/v1/desktop/shipping-center/handover` | `_create_shipping_report_from_ids` (KSH) |

Allowed with `manage_orders` or `can_manage_shipping`. Orders page: «مسح للتحديد» (or Settings → الطلبات → «تحديد الطلب») makes a scanned order barcode select the order directly.

## Branches & warehouses (الفروع والمخازن)

| Desktop feature | Endpoint | Rules reused |
|---|---|---|
| Mode, primary branch, scope options | `GET /api/v1/desktop/branches/meta` | `independent_branches_enabled` untouched; display flag `multi_branch_enabled` in `ui_flags` (explicit, else derived: >1 active branch) |
| List / detail with live figures | `GET /branches`, `GET /branches/<id>` | sales from invoices, stock from FIFO lots, cash from `calculate_treasury_balance` (null when it cannot be computed) |
| Create (empty: one cash account, no movements) | `POST /branches` | same steps as web `/settings/branches/save` incl. `sync_bank_accounts_across_branches` |
| Edit / archive / restore | `POST /branches/<id>/update`, `/<id>/archive` | archive refused for the primary branch and while stock, open orders or pending transfers exist |
| Turn feature on/off | `POST /branches/feature` | writes a UI flag only; off refused with >1 active branch |
| Work scope (view) | `POST /branches/switch` | `utils.branch_context.switch_branch_api` (session `branch_id` / `view_all_branches`) |

Admin-only management; non-admins see only their assigned branch. Table `branch_profile` (1:1 with `branch`) holds descriptive fields. Spec/progress: `docs/finora-multi-branch-spec.md`, `docs/finora-multi-branch-phase0-report.md`.

### Branch transfers — approval, partial receipt, residual (`modules/stock_operations/transfer_partial.py`)

| Action (`POST /api/v1/desktop/stock-operations/branch/transfers/<id>/<action>`) | Body | Rule |
|---|---|---|
| `approve` | `revision`, `reason` | draft → approved; admin of the source; required before `send` only when `transfer_approval_required` is on |
| `receive_partial` | `lines: [{line_id, received}]` | sent → received / partially_received; quantities taken FIFO from the original send layers |
| `resolve` | `lines: [{line_id, action: late\|return\|loss}]` | partially_received → received; admin; `loss` posts a stock write-off (inventory-loss journal) |
| `reject` | `revision`, `reason` | sent → rejected; everything returns to the sender |
| `POST /api/v1/desktop/branches/transfer-policy` | `approval_required` | admin; company policy flag in `ui_flags` |

Unsettled quantity stays the sender's (`in_transit_by_sender`, `in_transit_value`). All actions carry an `operation_id` (replay-safe) and the document `revision` (stale writes refused).

### Branch cash transfers (`utils/branch_cash_transfers.py`, `modules/desktop_api/branch_cash.py`)

| Endpoint (`/api/v1/desktop/branch-cash`) | Who | Effect |
|---|---|---|
| `GET /meta`, `GET /`, `GET /<id>` | accounts permission | accounts (other branches' balances hidden from non-admins), list scoped to the user's branch |
| `POST /` `{from_account_id,to_account_id,amount,reason,reference,operation_id,execute_now?}` | source-branch employee, admin | creates `BCT-…` (replay-safe by `operation_id`); `execute_now` admin only; nothing posted |
| `POST /<id>/approve` | admin | nothing posted |
| `POST /<id>/receive` | receiving-branch employee, admin | claim `posting` (committed) → `record_treasury_transfer(allow_cross_branch=True)` → `completed`; refusal reverts to `approved` |
| `POST /<id>/reject` · `/cancel` | receiver / admin · requester / admin | closes with a reason, nothing posted |

Business date is Asia/Baghdad. Table `branch_cash_transfer`; interrupted «posting» is reconciled from the `TreasuryTransfer` note.
