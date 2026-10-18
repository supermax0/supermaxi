# Payment workflow analysis (read before writing `payment.record`)

Read directly from the real implementation; nothing here is guessed from button names. No refund/void/journal-reversal
code is touched in Phase 8B — this document only describes what already exists.

## 1. Where payment starts

Only one screen: **Billing** (`/clinics/billing`, `static/clinics/finance.js`, permission `clinics_billing`).
Three entry points, all opening the same modal (`promptPay`):
* Row action "تحصيل" (only shown when `balance > 0`).
* Row overflow menu → "تسجيل دفعة" (same condition).
* Invoice drawer footer → "تسجيل دفعة" (opened by "عرض التفاصيل"/clicking the invoice number).
* The page header's "تسجيل دفعة" button picks the first unpaid invoice in the current list (a convenience, not a new flow).

There is **no** payment entry point inside the treatment-plan/invoice-creation UI (`dental-treatment-plan.js`) — creating an
invoice there never leads to paying it; the user must go to Billing. The lesson therefore starts at Billing, like the real
workflow.

## 2. Endpoint

`POST /clinics/api/invoices/<id>/pay` → `service.receive_payment(tenant_id, invoice_id, payload, actor_id, branch_id)`
(`modules/clinics/routes.py:2284`, `modules/clinics/service.py:2030`). Body: `{amount, method, notes}`.

## 3. What gets written

* A new `ClinicPayment` row (`modules/clinics/models.py:588`): `invoice_id`, `patient_id`, `amount`, `method`, `notes`,
  `created_by` (the real signed-in employee — the tutor is never the actor), `paid_at`/`created_at`.
* The **same** `ClinicInvoice` row is updated in place: `paid += amount`, `balance = max(0, total - paid)`,
  `status = "paid" if balance == 0 else "partial"`, `updated_by`/`updated_at`.
* If the invoice has an `appointment_id`, that appointment's `payment_status` is set to the invoice's new status.
* An audit-log row (`clinic_audit_log`, action `payment`/`create`).
* `ClinicAccountingPostingService.post_clinic_payment(...)` → a double-entry `JournalEntry`: debit the payment-method
  account, credit `patient_receivable`, for `amount` (see §13). This is a real accounting side effect that already
  exists; Phase 8B does not add, remove or change it.

So: **yes**, a separate `Payment` record is created, **and yes**, it directly mutates the invoice's `paid`/`balance`/
`status` columns (there is no separate "ledger of unapplied payments" — the invoice itself is always the live balance).

## 4. Invoice statuses (real, from `static/clinics/finance.js` `INV_STATUS` + `service.py`)

`open` (unpaid, default) → `partial` (some paid) → `paid` (balance 0). Also `void` (see §10; blocked once anything is
paid), `cancelled` and `refunded` exist in the status map/UI but nothing in the payment code path sets them — no code
in this repo currently produces `cancelled` or `refunded` through the invoice model (a separate `ClinicRefund` model and
`post_clinic_refund` exist for accounting purposes, but Phase 8B does not touch or teach them). The UI also computes a
client-side-only "overdue" badge (`balance > 0` and 7+ days old) that is never written to the database.

## 5. Payment methods (real, `static/clinics/finance-shared.js`)

`cash` (نقدي), `card` (بطاقة), `transfer` (تحويل), `zain` (زين كاش), `electronic` (دفع إلكتروني), `other` (أخرى).
No FastPay/QiCard in this codebase — only what is listed above is taught.

## 6. Partial payment — does it exist already?

Yes, already fully implemented (not something Phase 8B adds): `receive_payment` accepts any `0 < amount <= balance`
in one call; the resulting status is computed from the real balance (`"partial"` when `balance > 0`, else `"paid"`).
There is one endpoint and one code path for both a partial and a full payment — the amount decides which.

## 7. Outstanding-balance calculation

`balance = max(0, total - paid)` (`service.py:2052`), recomputed on every payment from the invoice's own `total`/`paid`
columns (not a separate running ledger). `total`/`subtotal`/`discount` are set when the invoice is created
(`invoice.create`, Phase 7) and are not touched by `receive_payment`.

## 8. Overpayment

**Rejected.** `if amount > float(inv.balance or 0): raise ValueError("المبلغ أكبر من الرصيد المتبقي")`
(`service.py:2038`). The client (`finance.js promptPay`) also checks this before sending, but the rule that matters is
server-side. Verified in the backend tests below with a tenant whose balance check is exercised directly against the
real `receive_payment`.

## 9. Zero / negative payment

**Rejected server-side**, not just by the HTML `type="number"` input. `_money()` (`service.py:65`) clamps to
`max(0, int(round(...)))`, so a negative payload becomes `0`, and `amount <= 0` raises
`"مبلغ الدفع غير صالح"` either way.

## 10. Void / refund (not built, not changed)

`void_invoice` (`service.py:2067`) **requires `paid == 0`** — "يجب استرجاع المدفوعات قبل إلغاء الفاتورة" — so an
invoice with any payment on it cannot be voided without a refund first. `POST /api/invoices/<id>/refund` and
`ClinicRefund`/`post_clinic_refund` already exist in the codebase for this, but **Phase 8B does not build, teach or
call them** (explicitly out of scope per the task).

## 11. Duplicate-submission / idempotency — real finding, not fixed

`_locked_invoice()` (`service.py:2023`) only applies `SELECT ... FOR UPDATE` **when the SQL dialect is PostgreSQL**:
```python
if db.session.get_bind().dialect.name == "postgresql":
    query = query.with_for_update()
```
Clinic tenant data lives in **per-tenant SQLite files** (`extensions_tenant`), not the Postgres core DB, so in
production `with_for_update()` is **never applied for clinic payments** — the row lock this code comments on
("Re-read balance under row lock so concurrent payments cannot overpay") does not actually happen for clinics. There
is also no idempotency key, no server-side de-duplication by client-generated token.

Practical effect, verified with a backend test (two sequential `receive_payment` calls, same amount, on SQLite):
* **A duplicate full-amount submission is naturally caught**: the first call drops `balance` to `0`; the second call's
  `amount > balance(0)` check correctly rejects it. No double full payment is possible.
* **A duplicate partial-amount submission is NOT caught**: if `amount < balance` both times (e.g. two clicks of
  "تحصيل" with the same smaller amount before the UI re-renders), **both succeed**, creating two `ClinicPayment` rows
  and reducing the balance twice. This is a real gap, confirmed on this test tenant's SQLite database, not assumed.
  **Documented here per the task's instruction; not fixed in Phase 8B** (no idempotency architecture is added to the
  tutor or the backend). The tutor's own UX mitigates the user-facing risk per §14 (a clear warning before the single
  confirm, and the lesson disables its own "Confirm" step while the request is in flight) but cannot fix the
  underlying backend gap.

## 12. Payment history

No dedicated `/invoices/<id>/payments` endpoint. The drawer (`billingDrawer` in `finance.js`) gets payment rows from
`GET /clinics/api/patients/<patient_id>/statement` (`service_ops.patient_statement`), filtered client-side to
`type === "payment"`. Each line shows amount, method (label from `PAYMENT_METHODS`), `paid_at`, and `notes`. No
`created_by`/employee name is rendered today — `ClinicPayment.created_by` is stored but never surfaced in this UI.
So `payment.history` is a **read-only Show Me** pointing at the existing drawer timeline, not a new screen.

## 13. Accounting side effects (documented, not modified)

`ClinicAccountingPostingService.post_clinic_payment` posts a journal entry: debit the method's account
(`_payment_account(method)`), credit `patient_receivable`, amount = the payment amount, dated `paid_at`. This runs
inside the same `receive_payment()` call (same DB transaction, before `db.session.commit()` in the route). Nothing in
Phase 8B changes this call or the account mapping.

## 14. Permission & validation summary

* Permission: `clinics_billing` (route decorator `@require_clinics("clinics_billing", json_mode=True)` on the `pay`
  endpoint, the invoice list, and the statement endpoint).
* Tenant isolation: `_locked_invoice` filters `ClinicInvoice.query.filter_by(tenant_id=tenant_id, id=invoice_id)`, and
  every clinics route runs against `g.tenant`'s own SQLite file — an id from another tenant's database simply cannot
  resolve, structurally, not just by a `tenant_id` column check.
* No confirmation dialog exists today before the "حفظ"/submit of the pay modal (the shared `openModal` save button is
  the only click). Per the task: do not add a popup confirmation (would be a double-confirm); the lesson instead adds
  one line of in-card guidance right before that same click (see the tutorial).
* No receipt feature exists: the drawer's "طباعة" button (`data-drawer-print`) has **no click handler at all** in
  `finance.js`, and the row menu's "طباعة" (`data-act="print"`) is wired to `openInvoiceDrawer`, not a print view —
  both are effectively dead/mislabeled buttons. **Finding, not fixed.** The lesson's completion message does not
  mention printing or offer a "وريني الوصل" action, per the task's "only if the feature actually exists."

## 15. Currency

Single currency per tenant (`clinic_settings.default_currency`, default `IQD`), no conversion anywhere in the clinic
module. The tutor never assumes `IQD` and never formats or converts an amount — it only ever says "اكتب مبلغ الدفعة"
(§40 of the task), never shows or invents a number.

## 16. Training-log sanitizer — a pre-existing (not Phase 8B) blind spot, documented not fixed

`modules/ai_tutor/routes.py:_log()` keeps a `detail` string only if it matches `DETAIL_TOKEN = r"^[A-Za-z0-9_.:\-]{1,80}$"`.
That check is purely about **character class**, not meaning: a *bare run of digits with no separators* — a raw
payment amount ("777000") or a phone number without spaces/dashes ("07701234567") — satisfies the regex and would be
stored verbatim if it ever reached `detail`. This predates Phase 8B (the same gap exists for every other lesson) and
is not introduced by it. In practice no lesson is affected today: the real client (`static/ai-tutor/engine/engine.js`)
only ever sends a fixed machine code (`"user_exit"`, `"engine_error"`, …) or a `"kind:id"` target reference
(`"field:payment.amount"`) as `detail`, never a raw typed value — confirmed by reading every `this.api.progress(...)`
call site. Verified in `tests/test_ai_tutor_payment.py::test_payment_training_logs_never_contain_amounts_or_methods`
with realistic client traffic (passes) and noted here as a **defense-in-depth gap**, not fixed in this phase (fixing
the shared regex is a cross-cutting change affecting all 14 lessons, out of this phase's scope).
