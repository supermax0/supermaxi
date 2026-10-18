"""Reusable retail supplier cash payment (FIFO allocation + shared-branch copies)."""
from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from utils.branch_mode import independent_branches_enabled
from utils.supplier_payment_allocation import (
    allocate_supplier_payment_fifo,
    backfill_supplier_payment_allocations,
)
from utils.treasury_calculations import InsufficientTreasuryBalance, assert_sufficient_balance
from utils.treasury_helpers import resolve_treasury_account_id
from utils.treasury_schema_guard import ensure_treasury_schema


def _coerce_payment_created_at(raw_value) -> datetime | None:
    """Accept date/datetime/YYYY-MM-DD; return midday local datetime or None."""
    if raw_value is None or raw_value == "":
        return None
    if isinstance(raw_value, datetime):
        return raw_value
    if isinstance(raw_value, date):
        return datetime.combine(raw_value, time(hour=12))
    text = str(raw_value).strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return datetime.combine(parsed, time(hour=12))


class SupplierPaymentError(Exception):
    def __init__(self, message: str, code: str = "supplier_payment_error"):
        self.message = message
        self.code = code
        super().__init__(message)


def shared_supplier_key(supplier: Supplier) -> str:
    name = str(getattr(supplier, "name", "") or "").strip().casefold()
    name = " ".join(name.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").split())
    return name or f"supplier:{supplier.id}"


def shared_supplier_member_ids(supplier: Supplier) -> list[int]:
    """Return all branch copies represented by a supplier row in shared mode."""
    if independent_branches_enabled():
        return [int(supplier.id)]
    rows = (
        Supplier.query.execution_options(skip_branch_scope=True)
        .order_by(Supplier.id.asc())
        .all()
    )
    key = shared_supplier_key(supplier)
    return [int(row.id) for row in rows if shared_supplier_key(row) == key] or [
        int(supplier.id)
    ]


def prepare_supplier_payment_allocations(supplier_id: int) -> None:
    """Persist one-time FIFO allocations for payments created before this feature."""
    try:
        allocated_amount = backfill_supplier_payment_allocations(supplier_id)
        if allocated_amount > 0:
            db.session.commit()
    except IntegrityError:
        db.session.rollback()
        allocated_amount = backfill_supplier_payment_allocations(supplier_id)
        if allocated_amount > 0:
            db.session.commit()


def _clean_optional_text(raw_value) -> str | None:
    if raw_value is None:
        return None
    cleaned = str(raw_value).strip()
    return cleaned or None


def create_supplier_cash_payment(
    supplier_id: int,
    *,
    amount,
    treasury_account_id=None,
    note: str = "",
    document_number=None,
    payment_date=None,
    commit: bool = True,
) -> dict:
    """Create cash payment(s) against a supplier (and shared copies). Does not flash/redirect.

    Returns dict with payment ids, total amount, purchase allocation count, and detail_url.
    Raises SupplierPaymentError / InsufficientTreasuryBalance on validation failure.
    """
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        raise SupplierPaymentError("المورد غير موجود", "not_found")

    member_ids = shared_supplier_member_ids(supplier)
    for member_id in member_ids:
        prepare_supplier_payment_allocations(member_id)

    try:
        amount_i = int(float(str(amount or "0").replace(",", "")))
    except (TypeError, ValueError):
        amount_i = 0

    note_s = str(note or "").strip()
    doc = _clean_optional_text(document_number)
    created_at = _coerce_payment_created_at(payment_date)

    members = (
        Supplier.query.execution_options(skip_branch_scope=True)
        .filter(Supplier.id.in_(member_ids))
        .order_by(Supplier.id.asc())
        .all()
    )
    remaining = sum(max(int(member.remaining or 0), 0) for member in members)
    if amount_i <= 0:
        raise SupplierPaymentError("أدخل مبلغ دفع صحيح أكبر من صفر.")
    if remaining <= 0:
        raise SupplierPaymentError(
            "لا يمكن تسديد دفعة — المورد لا يدين لنا أو تمت تسوية الدين بالكامل."
        )
    if amount_i > remaining:
        raise SupplierPaymentError("مبلغ الدفع أكبر من المتبقي على المورد.")

    ensure_treasury_schema()
    treasury_id = resolve_treasury_account_id(treasury_account_id)
    try:
        assert_sufficient_balance(treasury_id, amount_i)
    except InsufficientTreasuryBalance as exc:
        raise SupplierPaymentError(str(exc), "insufficient_balance") from exc

    leftover = amount_i
    purchase_alloc_count = 0
    payment_ids: list[int] = []
    try:
        for member in members:
            if leftover <= 0:
                break
            member_remaining = max(int(member.remaining or 0), 0)
            if member_remaining <= 0:
                continue
            portion = min(leftover, member_remaining)

            updated = (
                db.session.query(Supplier)
                .filter(
                    Supplier.id == member.id,
                    (
                        func.coalesce(Supplier.total_debt, 0)
                        - func.coalesce(Supplier.total_paid, 0)
                    )
                    >= portion,
                )
                .update(
                    {
                        Supplier.total_paid: (
                            func.coalesce(Supplier.total_paid, 0) + portion
                        )
                    },
                    synchronize_session=False,
                )
            )
            if updated != 1:
                db.session.rollback()
                raise SupplierPaymentError(
                    "تعذر تسجيل الدفعة لأن رصيد المورد تغيّر. حدّث الصفحة وحاول مجدداً.",
                    "race",
                )

            payment_kwargs = {
                "branch_id": member.branch_id,
                "supplier_id": member.id,
                "amount": portion,
                "note": note_s,
                "document_number": doc,
                "treasury_account_id": treasury_id,
                "payment_method": "cash",
            }
            if created_at is not None:
                payment_kwargs["created_at"] = created_at
            payment = SupplierPayment(**payment_kwargs)
            db.session.add(payment)
            db.session.flush()
            allocation = allocate_supplier_payment_fifo(payment, supplier=member)
            purchase_alloc_count += len(allocation.purchase_allocations or [])
            payment_ids.append(int(payment.id))
            leftover -= portion

        if leftover > 0:
            db.session.rollback()
            raise SupplierPaymentError(
                "تعذر تسجيل الدفعة لأن رصيد المورد تغيّر. حدّث الصفحة وحاول مجدداً.",
                "race",
            )

        if commit:
            db.session.commit()
    except SupplierPaymentError:
        raise
    except Exception:
        db.session.rollback()
        raise

    primary_id = payment_ids[0] if payment_ids else None
    return {
        "kind": "supplier_payment",
        "id": primary_id,
        "payment_ids": payment_ids,
        "amount": amount_i,
        "supplier_id": int(supplier.id),
        "supplier_name": supplier.name,
        "purchase_alloc_count": purchase_alloc_count,
        "label": f"تسديد مورد — {supplier.name}",
        "detail_url": f"/suppliers/{int(supplier.id)}",
        "message": (
            f"تم تسجيل الدفعة وتوزيعها محاسبياً على {purchase_alloc_count} فاتورة بالأقدم أولاً."
            if purchase_alloc_count
            else "تم تسجيل الدفعة في حساب المورد بنجاح."
        ),
    }
