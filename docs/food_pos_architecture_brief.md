# Finora Food POS — Architecture Brief

## Current architecture

- Flask + SQLAlchemy with one database per tenant and a shared Finora domain model.
- `Product`, `Invoice`, `OrderItem`, `Customer`, `Branch`, and the invoice payment ledger remain the system of record.
- `modules/food` is an additive projection for food variants, units, barcodes, warehouse balances, expiry batches, immutable sale/purchase snapshots, and food inventory movements.
- `/food/cashier` is rendered by the existing Food workspace and uses JSON endpoints under `/food/api`.
- Existing products are projected safely into a default variant/base unit without replacing IDs or rewriting historical invoices.

## Changes required

- Replace the current eager 250-product cashier feed with paginated/ranked search, exact barcode lookup, best sellers, and recent items.
- Move cart validation, pricing, discounts, payment allocation, credit rules, and permissions to backend services.
- Add checkout idempotency, hold/restore, partial returns, audit records, and explicit stock validation.
- Upgrade the current cashier layout into a keyboard/touch-first responsive POS while retaining Finora styling and RTL.
- Persist draft carts locally and revalidate them against the backend before checkout.

## Database impact

- Add food-only checkout request, held sale, return, return line, and POS audit tables.
- Extend food settings and sale snapshots additively. Existing tables and foreign keys remain authoritative.
- Add tenant-scoped indexes for barcode/search/status/warehouse paths.
- Decimal/weighted quantities require an additive precision migration before enabling them for PostgreSQL tenants; legacy integer rows remain valid.

## API impact

- Keep the existing `/food/api` structure.
- Add focused cashier catalog/search, validate-cart, hold, return, stock-by-branch, last-sale, and checkout endpoints.
- Checkout accepts identifiers and user intent only; prices, conversion factors, permissions, stock, customer ownership, and totals are recalculated by the backend.

## POS impact

- Sticky tool strip, ranked search suggestions, scanner-first focus, grid/list toggle, responsive cart drawer, compact editable cart lines, payment drawer, quick cash, split payments, holds, price check, and shortcuts.
- Secondary operations stay in drawers/menus to preserve the “scan → add → pay → done” flow.

## Inventory impact

- Warehouse is resolved from the cashier/employee context and validated on every operation.
- Base-unit stock remains canonical; exact stock is rechecked with row locks during checkout.
- Expiry-controlled products allocate sellable batches with FEFO/FIFO according to product policy; expired, disabled, quarantined, and reserved stock is excluded.
- Returns create traceable reverse movements and restore original batch allocations where possible.

## Accounting impact

- `Invoice` and `InvoicePaymentLedger` continue to drive sales, cash, receivables, and reports.
- Split payments create one ledger row per effective payment method; change is never recorded as revenue or an extra payment.
- Credit remains the unpaid invoice balance. Returns reverse paid value through negative ledger entries and reduce the effective receivable.

## Backward compatibility

- Legacy products retain their original IDs and receive a default Food projection only when needed.
- Historical invoices keep their stored values; food snapshots preserve unit, factor, barcode, price, cost, discount, tax, and quantity at the time of sale.
- General-business and wholesale modules are not replaced.

## Migration risk

- Highest risk: live tenant schema drift because this repository contains old SQLite schemas and lazy additive schema creation.
- Mitigation: additive tables/columns only, `checkfirst`, tenant-scoped constraints, no destructive rewrites, focused migration tests, and regression tests across existing invoices/products.
- Existing dirty-worktree changes are preserved and treated as user-owned.
