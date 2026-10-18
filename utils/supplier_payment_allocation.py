"""FIFO allocation of supplier-account payments without double-counting cash."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, or_

from extensions import db
from models.purchase import Purchase
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from models.supplier_payment_allocation import SupplierPaymentAllocation


PURCHASE = "purchase"
OPENING_BALANCE = "opening_balance"
ON_ACCOUNT = "on_account"


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _purchase_total(purchase: Purchase) -> int:
    value = purchase.grand_total
    if value is None or _safe_int(value) <= 0:
        value = purchase.total
    return max(_safe_int(value), 0)


def _purchase_initial_paid(purchase: Purchase) -> int:
    return min(max(_safe_int(purchase.paid_total), 0), _purchase_total(purchase))


def _purchase_is_active(purchase: Purchase) -> bool:
    status = (purchase.status or "confirmed").strip().lower()
    if status in {"cancelled", "canceled"}:
        return False
    if status in {"draft", "draft_editing"}:
        return bool(getattr(purchase, "stock_applied", False))
    return True


def ensure_supplier_payment_allocation_schema() -> None:
    """Create the allocation ledger for existing tenant databases."""
    bind = db.session.connection()
    SupplierPaymentAllocation.__table__.create(bind=bind, checkfirst=True)


def purchase_allocation_totals(supplier_id: int) -> dict[int, int]:
    ensure_supplier_payment_allocation_schema()
    rows = (
        db.session.query(
            SupplierPaymentAllocation.purchase_id,
            func.coalesce(func.sum(SupplierPaymentAllocation.amount), 0),
        )
        .join(
            SupplierPayment,
            SupplierPayment.id == SupplierPaymentAllocation.supplier_payment_id,
        )
        .filter(
            SupplierPayment.supplier_id == supplier_id,
            SupplierPayment.deleted_at.is_(None),
            SupplierPaymentAllocation.allocation_type == PURCHASE,
            SupplierPaymentAllocation.purchase_id.isnot(None),
        )
        .group_by(SupplierPaymentAllocation.purchase_id)
        .all()
    )
    return {int(purchase_id): _safe_int(amount) for purchase_id, amount in rows}


def purchase_allocation_totals_for_ids(purchase_ids: list[int]) -> dict[int, int]:
    ensure_supplier_payment_allocation_schema()
    normalized_ids = [int(value) for value in purchase_ids if value is not None]
    if not normalized_ids:
        return {}
    rows = (
        db.session.query(
            SupplierPaymentAllocation.purchase_id,
            func.coalesce(func.sum(SupplierPaymentAllocation.amount), 0),
        )
        .join(SupplierPayment, SupplierPayment.id == SupplierPaymentAllocation.supplier_payment_id)
        .filter(
            SupplierPayment.deleted_at.is_(None),
            SupplierPaymentAllocation.purchase_id.in_(normalized_ids),
            SupplierPaymentAllocation.allocation_type == PURCHASE,
        )
        .group_by(SupplierPaymentAllocation.purchase_id)
        .all()
    )
    return {int(purchase_id): _safe_int(amount) for purchase_id, amount in rows}


def effective_purchase_payment_totals(
    purchase: Purchase,
    allocated_amount: int | None = None,
) -> tuple[int, int, int]:
    """Return (effective paid, remaining, later-payment allocation)."""
    total = _purchase_total(purchase)
    initial_paid = _purchase_initial_paid(purchase)
    if allocated_amount is None:
        ensure_supplier_payment_allocation_schema()
        allocated_amount = (
            db.session.query(func.coalesce(func.sum(SupplierPaymentAllocation.amount), 0))
            .join(SupplierPayment,SupplierPayment.id==SupplierPaymentAllocation.supplier_payment_id)
            .filter(
                SupplierPayment.deleted_at.is_(None),
                SupplierPaymentAllocation.purchase_id == purchase.id,
                SupplierPaymentAllocation.allocation_type == PURCHASE,
            )
            .scalar()
            or 0
        )
    later_paid = min(max(_safe_int(allocated_amount), 0), max(total - initial_paid, 0))
    effective_paid = min(initial_paid + later_paid, total)
    return effective_paid, max(total - effective_paid, 0), later_paid


def _payment_cutoff_date(payment: SupplierPayment) -> date:
    created_at = payment.created_at
    if isinstance(created_at, datetime):
        return created_at.date()
    if isinstance(created_at, date):
        return created_at
    return date.today()


def _payment_existing_allocation(payment_id: int) -> int:
    return _safe_int(
        db.session.query(func.coalesce(func.sum(SupplierPaymentAllocation.amount), 0))
        .filter(SupplierPaymentAllocation.supplier_payment_id == payment_id)
        .scalar()
        or 0
    )


def _opening_balance_allocated(supplier_id: int) -> int:
    return _safe_int(
        db.session.query(func.coalesce(func.sum(SupplierPaymentAllocation.amount), 0))
        .join(
            SupplierPayment,
            SupplierPayment.id == SupplierPaymentAllocation.supplier_payment_id,
        )
        .filter(
            SupplierPayment.supplier_id == supplier_id,
            SupplierPaymentAllocation.allocation_type.in_([OPENING_BALANCE,"opening_settled"]),
            SupplierPayment.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )


@dataclass
class AllocationResult:
    payment_id: int
    payment_amount: int
    allocated_now: int = 0
    opening_balance_amount: int = 0
    purchase_amount: int = 0
    on_account_amount: int = 0
    purchase_allocations: list[dict] = field(default_factory=list)


def _record_allocation(
    *,
    payment_id: int,
    allocation_type: str,
    target_key: str,
    amount: int,
    purchase_id: int | None = None,
) -> SupplierPaymentAllocation:
    existing = (
        SupplierPaymentAllocation.query.filter_by(
            supplier_payment_id=payment_id,
            target_key=target_key,
        )
        .order_by(SupplierPaymentAllocation.id.asc())
        .first()
    )
    if existing:
        existing.amount = _safe_int(existing.amount) + amount
        return existing
    allocation = SupplierPaymentAllocation(
        supplier_payment_id=payment_id,
        purchase_id=purchase_id,
        allocation_type=allocation_type,
        target_key=target_key,
        amount=amount,
    )
    db.session.add(allocation)
    return allocation


def allocate_supplier_payment_fifo(
    payment: SupplierPayment,
    supplier: Supplier | None = None,
    *,
    recorded_at: datetime | None = None,
) -> AllocationResult:
    """
    Allocate the still-unallocated part of a supplier payment.

    Purchase invoices are cleared first by purchase date, creation time and id,
    because they are the traceable open items shown in the supplier statement.
    Any remainder then clears the unitemized opening balance. The Purchase
    ``paid_total`` is deliberately not changed: it represents payments entered
    on the purchase itself and is already counted separately by the supplier
    ledger reconciliation. For a finance document whose timestamp stores its
    accounting date, recorded_at limits known purchases by the actual posting
    instant while the accounting date still limits their purchase dates.
    """
    ensure_supplier_payment_allocation_schema()
    db.session.flush()

    supplier = supplier or Supplier.query.get(payment.supplier_id)
    if not supplier:
        raise ValueError("Supplier payment has no valid supplier")

    payment_amount = max(_safe_int(payment.amount), 0)
    existing_amount = _payment_existing_allocation(payment.id)
    if existing_amount > payment_amount:
        raise ValueError("Supplier payment allocations exceed the payment amount")

    remaining = payment_amount - existing_amount
    result = AllocationResult(
        payment_id=int(payment.id),
        payment_amount=payment_amount,
    )
    if remaining <= 0:
        return result

    if remaining > 0:
        allocated_by_purchase = purchase_allocation_totals(supplier.id)
        cutoff = _payment_cutoff_date(payment)
        payment_created_at = recorded_at or payment.created_at or datetime.utcnow()
        purchases = (
            Purchase.query.filter_by(supplier_id=supplier.id)
            .filter(
                or_(
                    Purchase.purchase_date.is_(None),
                    Purchase.purchase_date <= cutoff,
                ),
                or_(
                    Purchase.created_at.is_(None),
                    Purchase.created_at <= payment_created_at,
                ),
            )
            .order_by(
                Purchase.purchase_date.asc(),
                Purchase.created_at.asc(),
                Purchase.id.asc(),
            )
            .all()
        )
        for purchase in purchases:
            if remaining <= 0:
                break
            if not _purchase_is_active(purchase):
                continue
            total = _purchase_total(purchase)
            initial_paid = _purchase_initial_paid(purchase)
            already_allocated = max(_safe_int(allocated_by_purchase.get(purchase.id)), 0)
            invoice_due = max(total - initial_paid - already_allocated, 0)
            if invoice_due <= 0:
                continue
            amount = min(remaining, invoice_due)
            _record_allocation(
                payment_id=payment.id,
                purchase_id=purchase.id,
                allocation_type=PURCHASE,
                target_key=f"{PURCHASE}:{purchase.id}",
                amount=amount,
            )
            allocated_by_purchase[purchase.id] = already_allocated + amount
            result.purchase_amount += amount
            result.allocated_now += amount
            result.purchase_allocations.append(
                {
                    "purchase_id": int(purchase.id),
                    "invoice_no": purchase.invoice_no or f"LEG-{purchase.id}",
                    "amount": amount,
                }
            )
            remaining -= amount

    if remaining > 0:
        opening_total = max(_safe_int(getattr(supplier, "opening_balance", 0)), 0)
        opening_due = max(opening_total - _opening_balance_allocated(supplier.id), 0)
        if opening_due > 0:
            amount = min(remaining, opening_due)
            _record_allocation(
                payment_id=payment.id,
                purchase_id=None,
                allocation_type=OPENING_BALANCE,
                target_key=OPENING_BALANCE,
                amount=amount,
            )
            result.opening_balance_amount += amount
            result.allocated_now += amount
            remaining -= amount

    if remaining > 0:
        _record_allocation(
            payment_id=payment.id,
            purchase_id=None,
            allocation_type=ON_ACCOUNT,
            target_key=ON_ACCOUNT,
            amount=remaining,
        )
        result.on_account_amount += remaining
        result.allocated_now += remaining

    db.session.flush()
    return result


def rebalance_supplier_payment_allocations(supplier_id: int) -> int:
    """
    Move opening/on-account allocations to currently open purchase invoices.

    This is what lets a historical payment-on-account clear invoices that were
    entered later, while preserving the original payment record and amount.
    """
    ensure_supplier_payment_allocation_schema()
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return 0

    sources = (
        SupplierPaymentAllocation.query.join(
            SupplierPayment,
            SupplierPayment.id == SupplierPaymentAllocation.supplier_payment_id,
        )
        .filter(
            SupplierPayment.supplier_id == supplier_id,
            SupplierPayment.deleted_at.is_(None),
            SupplierPaymentAllocation.allocation_type.in_(
                [OPENING_BALANCE, ON_ACCOUNT]
            ),
            SupplierPaymentAllocation.amount > 0,
        )
        .order_by(
            SupplierPayment.created_at.asc(),
            SupplierPayment.id.asc(),
            SupplierPaymentAllocation.id.asc(),
        )
        .all()
    )
    if not sources:
        return 0

    allocated_by_purchase = purchase_allocation_totals(supplier_id)
    purchases = (
        Purchase.query.filter_by(supplier_id=supplier_id)
        .order_by(
            Purchase.purchase_date.asc(),
            Purchase.created_at.asc(),
            Purchase.id.asc(),
        )
        .all()
    )

    moved = 0
    for purchase in purchases:
        if not _purchase_is_active(purchase):
            continue
        total = _purchase_total(purchase)
        initial_paid = _purchase_initial_paid(purchase)
        already_allocated = max(
            _safe_int(allocated_by_purchase.get(purchase.id)),
            0,
        )
        invoice_due = max(total - initial_paid - already_allocated, 0)
        if invoice_due <= 0:
            continue

        for source in sources:
            source_amount = max(_safe_int(source.amount), 0)
            if source_amount <= 0:
                continue
            amount = min(source_amount, invoice_due)
            _record_allocation(
                payment_id=source.supplier_payment_id,
                purchase_id=purchase.id,
                allocation_type=PURCHASE,
                target_key=f"{PURCHASE}:{purchase.id}",
                amount=amount,
            )
            source.amount = source_amount - amount
            if source.amount <= 0:
                db.session.delete(source)
            allocated_by_purchase[purchase.id] = already_allocated + amount
            already_allocated += amount
            invoice_due -= amount
            moved += amount
            if invoice_due <= 0:
                break

    # Only after every traceable invoice is cleared may unapplied credit reduce
    # the unitemized opening balance.
    db.session.flush()
    opening_total = max(_safe_int(getattr(supplier, "opening_balance", 0)), 0)
    opening_due = max(opening_total - _opening_balance_allocated(supplier_id), 0)
    if opening_due > 0:
        on_account_sources = [
            source
            for source in sources
            if source.allocation_type == ON_ACCOUNT
            and max(_safe_int(source.amount), 0) > 0
        ]
        for source in on_account_sources:
            if opening_due <= 0:
                break
            source_amount = max(_safe_int(source.amount), 0)
            amount = min(source_amount, opening_due)
            _record_allocation(
                payment_id=source.supplier_payment_id,
                purchase_id=None,
                allocation_type=OPENING_BALANCE,
                target_key=OPENING_BALANCE,
                amount=amount,
            )
            source.amount = source_amount - amount
            if source.amount <= 0:
                db.session.delete(source)
            opening_due -= amount
            moved += amount

    db.session.flush()
    return moved


def backfill_supplier_payment_allocations(supplier_id: int) -> int:
    """Allocate legacy supplier payments once, oldest payment first."""
    ensure_supplier_payment_allocation_schema()
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return 0

    changed = 0
    payments = (
        SupplierPayment.query.filter_by(supplier_id=supplier_id).filter(SupplierPayment.deleted_at.is_(None))
        .order_by(SupplierPayment.created_at.asc(), SupplierPayment.id.asc())
        .all()
    )
    for payment in payments:
        result = allocate_supplier_payment_fifo(payment, supplier=supplier)
        changed += result.allocated_now
    changed += rebalance_supplier_payment_allocations(supplier_id)
    return changed


def purchase_has_supplier_payment_allocations(purchase_id: int) -> bool:
    ensure_supplier_payment_allocation_schema()
    return (
        db.session.query(SupplierPaymentAllocation.id)
        .filter(
            SupplierPaymentAllocation.purchase_id == purchase_id,
            SupplierPaymentAllocation.allocation_type == PURCHASE,
        )
        .first()
        is not None
    )
