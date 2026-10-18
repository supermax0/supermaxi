"""Suppliers and purchases for clinic inventory."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_

from extensions import db
from models.employee import Employee
from modules.clinics.models import (
    ClinicAuditLog,
    ClinicInventoryItem,
    ClinicPurchase,
    ClinicPurchaseItem,
    ClinicPurchasePayment,
    ClinicPurchaseReceipt,
    ClinicPurchaseReceiptItem,
    ClinicSupplier,
)
from modules.clinics.service import _audit, _money, _parse_date, _today
from modules.clinics.service_ops import stock_in


def _client_ip() -> str:
    try:
        from flask import request

        return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    except RuntimeError:
        return ""


def _purchase_audit(
    tenant_id: int,
    actor_id,
    entity_type: str,
    entity_id,
    action: str,
    summary: str,
    *,
    purchase_id=None,
    old_values=None,
    new_values=None,
    reason=None,
    branch_id=None,
):
    meta = {"purchase_id": purchase_id or (entity_id if entity_type == "purchase" else None), "ip": _client_ip()}
    if old_values is not None:
        meta["old_values"] = old_values
    if new_values is not None:
        meta["new_values"] = new_values
    if reason:
        meta["reason"] = reason
    _audit(tenant_id, actor_id, entity_type, entity_id, action, summary, meta=meta, branch_id=branch_id)


def _qty(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _employee_name(employee_id) -> str:
    if not employee_id:
        return ""
    row = Employee.query.get(employee_id)
    return row.name if row else ""


def _display_payment_status(row: ClinicPurchase) -> str:
    ps = (row.payment_status or "").strip()
    if ps:
        return ps
    legacy = (row.status or "").strip().lower()
    if legacy == "paid":
        return "paid"
    if legacy == "partial":
        return "partial"
    if legacy in ("cancelled", "canceled"):
        return "cancelled"
    if row.due_date and row.due_date < _today() and (row.balance or 0) > 0:
        return "overdue"
    return "unpaid"


def _sync_payment_status(row: ClinicPurchase) -> None:
    if (row.invoice_status or "").lower() in ("cancelled", "canceled"):
        row.payment_status = "cancelled"
        row.status = "cancelled"
        return
    total = int(row.total or 0)
    paid = int(row.paid or 0)
    balance = max(0, total - paid)
    row.balance = balance
    if paid >= total and total > 0:
        row.payment_status = "paid"
        row.status = "paid"
    elif paid > 0:
        row.payment_status = "partial"
        row.status = "partial"
    elif row.due_date and row.due_date < _today() and balance > 0:
        row.payment_status = "overdue"
        row.status = "open"
    else:
        row.payment_status = "unpaid"
        row.status = "open"


def supplier_dict(row: ClinicSupplier) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "phone": row.phone or "",
        "email": row.email or "",
        "address": row.address or "",
        "contact_person": row.contact_person or "",
        "tax_number": row.tax_number or "",
        "opening_balance": row.opening_balance,
        "notes": row.notes or "",
        "active": bool(row.active),
    }


def list_suppliers(tenant_id: int, active_only: bool = True) -> list[dict]:
    query = ClinicSupplier.query.filter_by(tenant_id=tenant_id)
    if active_only:
        query = query.filter_by(active=True)
    return [supplier_dict(r) for r in query.order_by(ClinicSupplier.name.asc()).all()]


def create_supplier(tenant_id: int, payload: dict, actor_id=None) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("اسم المورد مطلوب")
    row = ClinicSupplier(
        tenant_id=tenant_id,
        name=name,
        phone=str(payload.get("phone") or "").strip() or None,
        email=str(payload.get("email") or "").strip() or None,
        address=str(payload.get("address") or "").strip() or None,
        contact_person=str(payload.get("contact_person") or "").strip() or None,
        tax_number=str(payload.get("tax_number") or "").strip() or None,
        opening_balance=_money(payload.get("opening_balance")),
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return supplier_dict(row)


def _next_purchase_number(tenant_id: int) -> str:
    year = _today().year
    prefix = f"PO-{year}-"
    count = (
        ClinicPurchase.query.filter_by(tenant_id=tenant_id)
        .filter(ClinicPurchase.purchase_number.like(f"{prefix}%"))
        .count()
    )
    if not count:
        count = ClinicPurchase.query.filter_by(tenant_id=tenant_id).count()
    return f"{prefix}{count + 1:05d}"


def _next_payment_number(tenant_id: int, purchase_id: int) -> str:
    count = ClinicPurchasePayment.query.filter_by(tenant_id=tenant_id, purchase_id=purchase_id).count() + 1
    return f"PAY-{purchase_id:05d}-{count:02d}"


def _parse_items(tenant_id: int, items: list) -> tuple[int, list]:
    subtotal = 0
    parsed = []
    for line in items:
        item_id = int(line.get("item_id") or 0)
        qty = float(line.get("quantity") or 0)
        free_qty = float(line.get("free_quantity") or 0)
        unit_cost = _money(line.get("unit_cost"))
        if qty <= 0:
            continue
        if not ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=item_id).first():
            raise ValueError("صنف المخزون غير موجود")
        line_discount = _money(line.get("line_discount"))
        line_discount_pct = line.get("line_discount_percent")
        gross = int(round(qty * unit_cost))
        if line_discount_pct not in (None, ""):
            try:
                line_discount = int(round(gross * float(line_discount_pct) / 100))
            except (TypeError, ValueError):
                pass
        line_total = max(0, gross - line_discount)
        subtotal += line_total
        parsed.append((item_id, qty, free_qty, unit_cost, line_total, line_discount, line_discount_pct, line))
    if not parsed:
        raise ValueError("لا توجد بنود صالحة")
    return subtotal, parsed


def _calc_totals(subtotal: int, payload: dict) -> tuple[int, int, int, int, int]:
    discount = _money(payload.get("discount"))
    discount_percent = payload.get("discount_percent")
    if discount_percent not in (None, ""):
        try:
            discount = int(round(subtotal * float(discount_percent) / 100))
        except (TypeError, ValueError):
            pass
    shipping = _money(payload.get("shipping_extra"))
    tax_amount = _money(payload.get("tax_amount"))
    other_charges = _money(payload.get("other_charges"))
    total = max(0, subtotal - discount + shipping + tax_amount + other_charges)
    return discount, shipping, tax_amount, other_charges, total


def _item_dict(it: ClinicPurchaseItem, tenant_id: int) -> dict:
    inv = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=it.item_id).first()
    ordered = _qty(it.quantity)
    received = _qty(it.received_quantity)
    return {
        "id": it.id,
        "item_id": it.item_id,
        "item_name": inv.name if inv else "",
        "item_unit": inv.unit if inv else "",
        "batch_tracking": bool(inv and inv.batch_tracking),
        "expiry_tracking": bool(inv and inv.expiry_tracking),
        "quantity": float(ordered),
        "free_quantity": float(_qty(it.free_quantity)),
        "received_quantity": float(received),
        "remaining_quantity": float(max(ordered - received, _qty(0))),
        "returned_quantity": float(_qty(it.returned_quantity)),
        "returnable_quantity": float(max(received - _qty(it.returned_quantity), _qty(0))),
        "unit_cost": it.unit_cost,
        "line_discount": it.line_discount,
        "line_discount_percent": float(it.line_discount_percent or 0),
        "line_total": it.line_total,
        "batch_number": it.batch_number or "",
        "expiry_date": it.expiry_date.isoformat() if it.expiry_date else "",
    }


def purchase_dict(row: ClinicPurchase, tenant_id: int, *, detailed: bool = False) -> dict:
    supplier = ClinicSupplier.query.filter_by(tenant_id=tenant_id, id=row.supplier_id).first()
    items = ClinicPurchaseItem.query.filter_by(tenant_id=tenant_id, purchase_id=row.id).all()
    item_rows = [_item_dict(it, tenant_id) for it in items]
    data = {
        "id": row.id,
        "purchase_number": row.purchase_number,
        "supplier_invoice_no": row.supplier_invoice_no or "",
        "supplier_id": row.supplier_id,
        "supplier_name": supplier.name if supplier else "",
        "purchase_date": row.purchase_date.isoformat(),
        "due_date": row.due_date.isoformat() if row.due_date else "",
        "subtotal": row.subtotal,
        "discount": row.discount,
        "discount_percent": float(row.discount_percent or 0),
        "shipping_extra": row.shipping_extra or 0,
        "tax_amount": row.tax_amount or 0,
        "other_charges": row.other_charges or 0,
        "total": row.total,
        "paid": row.paid,
        "balance": row.balance,
        "status": row.status,
        "invoice_status": row.invoice_status or "approved",
        "payment_status": _display_payment_status(row),
        "receipt_status": row.receipt_status or "pending",
        "purchase_type": row.purchase_type or "credit",
        "warehouse_name": row.warehouse_name or "",
        "notes": row.notes or "",
        "items_count": len(item_rows),
        "created_by": row.created_by,
        "created_by_name": _employee_name(row.created_by),
        "branch_id": row.branch_id,
        "items": item_rows,
        "return_total": row.return_total or 0,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }
    if detailed:
        receipts = ClinicPurchaseReceipt.query.filter_by(tenant_id=tenant_id, purchase_id=row.id).order_by(
            ClinicPurchaseReceipt.id.asc()
        ).all()
        payments = ClinicPurchasePayment.query.filter_by(tenant_id=tenant_id, purchase_id=row.id).order_by(
            ClinicPurchasePayment.id.asc()
        ).all()
        data["receipts"] = [
            {
                "id": r.id,
                "receipt_number": r.receipt_number,
                "received_at": r.received_at.isoformat() if r.received_at else "",
                "notes": r.notes or "",
                "received_by_name": _employee_name(r.received_by),
                "items_count": ClinicPurchaseReceiptItem.query.filter_by(tenant_id=tenant_id, receipt_id=r.id).count(),
            }
            for r in receipts
        ]
        data["payments"] = [
            {
                "id": p.id,
                "payment_number": p.payment_number,
                "payment_date": p.payment_date.isoformat(),
                "amount": p.amount,
                "payment_method": p.payment_method,
                "account_name": p.account_name or "",
                "reference_no": p.reference_no or "",
                "notes": p.notes or "",
                "created_by_name": _employee_name(p.created_by),
            }
            for p in payments
        ]
        data["timeline"] = _purchase_timeline(tenant_id, row.id)
    return data


def _purchase_timeline(tenant_id: int, purchase_id: int) -> list[dict]:
    receipt_ids = [
        r.id
        for r in ClinicPurchaseReceipt.query.filter_by(tenant_id=tenant_id, purchase_id=purchase_id).all()
    ]
    payment_ids = [
        p.id
        for p in ClinicPurchasePayment.query.filter_by(tenant_id=tenant_id, purchase_id=purchase_id).all()
    ]
    from modules.clinics.models import ClinicPurchaseReturn

    return_ids = [
        r.id
        for r in ClinicPurchaseReturn.query.filter_by(tenant_id=tenant_id, purchase_id=purchase_id).all()
    ]
    filters = [
        (ClinicAuditLog.entity_type == "purchase") & (ClinicAuditLog.entity_id == purchase_id),
    ]
    if receipt_ids:
        filters.append(
            (ClinicAuditLog.entity_type == "purchase_receipt") & (ClinicAuditLog.entity_id.in_(receipt_ids))
        )
    if payment_ids:
        filters.append(
            (ClinicAuditLog.entity_type == "purchase_payment") & (ClinicAuditLog.entity_id.in_(payment_ids))
        )
    if return_ids:
        filters.append(
            (ClinicAuditLog.entity_type == "purchase_return") & (ClinicAuditLog.entity_id.in_(return_ids))
        )
    rows = (
        ClinicAuditLog.query.filter_by(tenant_id=tenant_id)
        .filter(or_(*filters))
        .order_by(ClinicAuditLog.created_at.asc())
        .all()
    )
    return [
        {
            "at": r.created_at.isoformat() if r.created_at else "",
            "action": r.action,
            "summary": r.summary,
            "actor_name": _employee_name(r.actor_id),
        }
        for r in rows
    ]


def _date_range(quick: str) -> tuple[date | None, date | None]:
    today = _today()
    if quick == "today":
        return today, today
    if quick == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if quick == "week":
        return today - timedelta(days=6), today
    if quick == "month":
        return today.replace(day=1), today
    if quick == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    return None, None


def _apply_purchase_filters(query, tenant_id: int, args: dict):
    q = str(args.get("q") or "").strip()
    if q:
        supplier_ids = [
            s.id
            for s in ClinicSupplier.query.filter(
                ClinicSupplier.tenant_id == tenant_id,
                ClinicSupplier.name.ilike(f"%{q}%"),
            ).all()
        ]
        item_purchase_ids = []
        for pi in ClinicPurchaseItem.query.filter_by(tenant_id=tenant_id).all():
            inv = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=pi.item_id).first()
            if inv and (
                (inv.name or "").lower().find(q.lower()) >= 0
                or (inv.sku or "").lower().find(q.lower()) >= 0
                or (inv.barcode or "").lower().find(q.lower()) >= 0
            ):
                item_purchase_ids.append(pi.purchase_id)
        clauses = [
            ClinicPurchase.purchase_number.ilike(f"%{q}%"),
            ClinicPurchase.supplier_invoice_no.ilike(f"%{q}%"),
        ]
        if supplier_ids:
            clauses.append(ClinicPurchase.supplier_id.in_(supplier_ids))
        if item_purchase_ids:
            clauses.append(ClinicPurchase.id.in_(item_purchase_ids))
        query = query.filter(or_(*clauses))
    supplier_id = args.get("supplier_id")
    if supplier_id:
        query = query.filter(ClinicPurchase.supplier_id == int(supplier_id))
    invoice_status = args.get("invoice_status")
    if invoice_status:
        query = query.filter(ClinicPurchase.invoice_status == invoice_status)
    receipt_status = args.get("receipt_status")
    if receipt_status:
        query = query.filter(ClinicPurchase.receipt_status == receipt_status)
    payment_status = args.get("payment_status")
    if payment_status:
        query = query.filter(ClinicPurchase.payment_status == payment_status)
    created_by = args.get("created_by")
    if created_by:
        query = query.filter(ClinicPurchase.created_by == int(created_by))
    branch_id = args.get("branch_id")
    if branch_id:
        query = query.filter(ClinicPurchase.branch_id == int(branch_id))

    quick = args.get("quick") or ""
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    if quick:
        d_from, d_to = _date_range(quick)
    else:
        d_from = _parse_date(date_from, "من") if date_from else None
        d_to = _parse_date(date_to, "إلى") if date_to else None
    if d_from:
        query = query.filter(ClinicPurchase.purchase_date >= d_from)
    if d_to:
        query = query.filter(ClinicPurchase.purchase_date <= d_to)
    return query


def purchase_kpis(tenant_id: int, args: dict | None = None) -> dict:
    args = args or {}
    today = _today()
    month_start = today.replace(day=1)

    base = ClinicPurchase.query.filter_by(tenant_id=tenant_id).filter(
        ClinicPurchase.invoice_status != "cancelled"
    )
    today_total = sum(
        p.total or 0
        for p in base.filter(ClinicPurchase.purchase_date == today).all()
    )
    month_total = sum(
        p.total or 0
        for p in base.filter(ClinicPurchase.purchase_date >= month_start).all()
    )
    all_open = base.all()
    supplier_payable = sum(p.balance or 0 for p in all_open)
    unpaid_count = sum(1 for p in all_open if (p.payment_status or "") in ("unpaid", "partial", "overdue") and (p.balance or 0) > 0)
    pending_receipt = sum(1 for p in all_open if (p.receipt_status or "pending") == "pending")
    partial_receipt = sum(1 for p in all_open if (p.receipt_status or "") == "partial")
    return {
        "purchases_today": today_total,
        "purchases_month": month_total,
        "supplier_payable": supplier_payable,
        "unpaid_count": unpaid_count,
        "pending_receipt": pending_receipt,
        "partial_receipt": partial_receipt,
    }


def list_purchases(tenant_id: int, args: dict | None = None) -> dict:
    args = args or {}
    page = max(1, int(args.get("page") or 1))
    per_page = min(100, max(10, int(args.get("per_page") or 25)))
    query = ClinicPurchase.query.filter_by(tenant_id=tenant_id)
    query = _apply_purchase_filters(query, tenant_id, args)
    total = query.count()
    rows = (
        query.order_by(ClinicPurchase.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "items": [purchase_dict(r, tenant_id) for r in rows],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": max(1, (total + per_page - 1) // per_page),
        },
        "kpis": purchase_kpis(tenant_id, args),
    }


def get_purchase(tenant_id: int, purchase_id: int) -> dict:
    row = ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).first()
    if not row:
        raise ValueError("فاتورة الشراء غير موجودة")
    from modules.clinics.service_purchase_extras import enrich_purchase_detail

    return enrich_purchase_detail(tenant_id, purchase_dict(row, tenant_id, detailed=True))


def get_purchase_receipt_print(tenant_id: int, purchase_id: int, receipt_id: int) -> dict:
    receipt = ClinicPurchaseReceipt.query.filter_by(
        tenant_id=tenant_id, purchase_id=purchase_id, id=receipt_id
    ).first()
    if not receipt:
        raise ValueError("سند الاستلام غير موجود")
    purchase = purchase_dict(
        ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).first(),
        tenant_id,
    )
    items = []
    for ri in ClinicPurchaseReceiptItem.query.filter_by(tenant_id=tenant_id, receipt_id=receipt.id).all():
        line = ClinicPurchaseItem.query.filter_by(tenant_id=tenant_id, id=ri.purchase_item_id).first()
        inv = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=line.item_id).first() if line else None
        items.append({
            "item_name": inv.name if inv else "",
            "quantity": float(ri.quantity or 0),
            "unit_cost": ri.unit_cost,
            "line_total": int(float(ri.quantity or 0) * int(ri.unit_cost or 0)),
            "batch_number": ri.batch_number or "",
            "expiry_date": ri.expiry_date.isoformat() if ri.expiry_date else "",
        })
    return {
        "receipt_number": receipt.receipt_number,
        "received_at": receipt.received_at.isoformat() if receipt.received_at else "",
        "received_by_name": _employee_name(receipt.received_by),
        "notes": receipt.notes or "",
        "purchase_number": purchase["purchase_number"],
        "supplier_name": purchase["supplier_name"],
        "supplier_invoice_no": purchase.get("supplier_invoice_no") or "",
        "warehouse_name": purchase.get("warehouse_name") or "",
        "items": items,
        "total_value": sum(i["line_total"] for i in items),
    }


def get_purchase_payment_print(tenant_id: int, purchase_id: int, payment_id: int) -> dict:
    pay = ClinicPurchasePayment.query.filter_by(
        tenant_id=tenant_id, purchase_id=purchase_id, id=payment_id
    ).first()
    if not pay:
        raise ValueError("سند الدفع غير موجود")
    purchase_row = ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).first()
    purchase = purchase_dict(purchase_row, tenant_id)
    return {
        "payment_number": pay.payment_number,
        "payment_date": pay.payment_date.isoformat(),
        "amount": pay.amount,
        "payment_method": pay.payment_method,
        "account_name": pay.account_name or "",
        "reference_no": pay.reference_no or "",
        "notes": pay.notes or "",
        "created_by_name": _employee_name(pay.created_by),
        "purchase_number": purchase["purchase_number"],
        "supplier_name": purchase["supplier_name"],
        "supplier_invoice_no": purchase.get("supplier_invoice_no") or "",
        "purchase_total": purchase["total"],
        "purchase_paid": purchase["paid"],
        "purchase_balance": purchase["balance"],
    }


def check_duplicate_invoice(tenant_id: int, supplier_id: int, supplier_invoice_no: str, exclude_id=None) -> dict:
    ref = str(supplier_invoice_no or "").strip()
    if not ref:
        return {"duplicate": False}
    query = ClinicPurchase.query.filter_by(
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        supplier_invoice_no=ref,
    ).filter(ClinicPurchase.invoice_status != "cancelled")
    if exclude_id:
        query = query.filter(ClinicPurchase.id != int(exclude_id))
    existing = query.first()
    if not existing:
        return {"duplicate": False}
    return {
        "duplicate": True,
        "purchase_id": existing.id,
        "purchase_number": existing.purchase_number,
    }


def _add_purchase_items(tenant_id: int, purchase_id: int, parsed_items) -> None:
    for item_id, qty, free_qty, unit_cost, line_total, line_discount, line_discount_pct, raw in parsed_items:
        db.session.add(
            ClinicPurchaseItem(
                tenant_id=tenant_id,
                purchase_id=purchase_id,
                item_id=item_id,
                batch_number=str(raw.get("batch_number") or "").strip() or None,
                expiry_date=_parse_date(raw["expiry_date"], "انتهاء") if raw.get("expiry_date") else None,
                quantity=qty,
                free_quantity=free_qty,
                unit_cost=unit_cost,
                line_discount=line_discount,
                line_discount_percent=line_discount_pct if line_discount_pct not in (None, "") else None,
                line_total=line_total,
            )
        )


def _record_payment_internal(
    tenant_id: int,
    purchase: ClinicPurchase,
    payload: dict,
    actor_id=None,
) -> ClinicPurchasePayment:
    amount = _money(payload.get("amount"))
    if amount <= 0:
        raise ValueError("مبلغ الدفعة غير صالح")
    if amount > purchase.balance:
        raise ValueError("مبلغ الدفعة أكبر من المتبقي")
    pay = ClinicPurchasePayment(
        tenant_id=tenant_id,
        purchase_id=purchase.id,
        payment_number=_next_payment_number(tenant_id, purchase.id),
        payment_date=_parse_date(payload.get("payment_date") or _today().isoformat(), "تاريخ الدفع"),
        amount=amount,
        payment_method=str(payload.get("payment_method") or "cash"),
        account_name=str(payload.get("account_name") or "").strip() or None,
        reference_no=str(payload.get("reference_no") or "").strip() or None,
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(pay)
    db.session.flush()
    purchase.paid = int(purchase.paid or 0) + amount
    _sync_payment_status(purchase)
    _purchase_audit(
        tenant_id,
        actor_id,
        "purchase_payment",
        pay.id,
        "create",
        f"دفعة {pay.payment_number} — {amount}",
        purchase_id=purchase.id,
        new_values={"amount": amount, "payment_method": pay.payment_method, "balance": purchase.balance},
        branch_id=purchase.branch_id,
    )
    # Paying an existing supplier liability is not a second clinic expense.
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.post_clinic_purchase_payment(pay.id, tenant_id, actor_id)
    return pay


def create_purchase(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    supplier_id = int(payload.get("supplier_id") or 0)
    if not ClinicSupplier.query.filter_by(tenant_id=tenant_id, id=supplier_id).first():
        raise ValueError("المورد غير موجود")
    supplier_invoice_no = str(payload.get("supplier_invoice_no") or "").strip()
    if supplier_invoice_no:
        dup = check_duplicate_invoice(tenant_id, supplier_id, supplier_invoice_no)
        if dup.get("duplicate"):
            raise ValueError(f"فاتورة المورد مسجلة مسبقاً: {dup['purchase_number']}")

    items = payload.get("items") or []
    subtotal, parsed_items = _parse_items(tenant_id, items)
    discount, shipping, tax_amount, other_charges, total = _calc_totals(subtotal, payload)
    invoice_status = _apply_approval_status(tenant_id, total, payload)
    pay_now = bool(payload.get("pay_now")) or _money(payload.get("paid")) > 0
    paid = _money(payload.get("paid")) if pay_now else 0
    if paid > total:
        paid = total

    row = ClinicPurchase(
        tenant_id=tenant_id,
        branch_id=branch_id,
        supplier_id=supplier_id,
        purchase_number=_next_purchase_number(tenant_id),
        supplier_invoice_no=supplier_invoice_no or None,
        purchase_date=_parse_date(payload.get("purchase_date") or _today().isoformat(), "تاريخ الشراء"),
        due_date=_parse_date(payload["due_date"], "تاريخ الاستحقاق") if payload.get("due_date") else None,
        subtotal=subtotal,
        discount=discount,
        discount_percent=payload.get("discount_percent") if payload.get("discount_percent") not in (None, "") else None,
        shipping_extra=shipping,
        tax_amount=tax_amount,
        other_charges=other_charges,
        total=total,
        paid=0,
        balance=total,
        invoice_status=invoice_status,
        receipt_status="pending",
        purchase_type=str(payload.get("purchase_type") or "credit"),
        warehouse_name=str(payload.get("warehouse_name") or "").strip() or None,
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    _sync_payment_status(row)
    db.session.add(row)
    db.session.flush()
    _add_purchase_items(tenant_id, row.id, parsed_items)

    if row.invoice_status == "approved":
        from modules.clinics.accounting_service import ClinicAccountingPostingService
        ClinicAccountingPostingService.post_clinic_purchase(row.id, tenant_id, actor_id)

    if paid > 0:
        if row.invoice_status == "draft":
            raise ValueError("لا يمكن دفع فاتورة شراء قبل اعتمادها")
        _record_payment_internal(
            tenant_id,
            row,
            {
                "amount": paid,
                "payment_method": payload.get("payment_method") or "cash",
                "account_name": payload.get("account_name"),
                "reference_no": payload.get("reference_no"),
                "payment_date": payload.get("purchase_date"),
                "notes": "دفعة عند الإنشاء",
            },
            actor_id,
        )

    _purchase_audit(tenant_id, actor_id, "purchase", row.id, "create", f"فاتورة شراء {row.purchase_number}", purchase_id=row.id, new_values={"total": total, "supplier_id": supplier_id}, branch_id=branch_id)

    if payload.get("receive_now"):
        receive_lines = []
        for item_id, qty, free_qty, unit_cost, line_total, line_discount, line_discount_pct, raw in parsed_items:
            purchase_item = ClinicPurchaseItem.query.filter_by(
                tenant_id=tenant_id, purchase_id=row.id, item_id=item_id
            ).first()
            if purchase_item:
                receive_lines.append({
                    "purchase_item_id": purchase_item.id,
                    "quantity": float(qty) + float(free_qty),
                    "batch_number": raw.get("batch_number"),
                    "expiry_date": raw.get("expiry_date"),
                    "unit_cost": unit_cost,
                })
        if receive_lines:
            receive_purchase(tenant_id, row.id, {"items": receive_lines, "notes": "استلام فوري"}, actor_id, branch_id)

    db.session.flush()
    return purchase_dict(row, tenant_id, detailed=True)


def _apply_approval_status(tenant_id: int, total: int, payload: dict) -> str:
    from modules.clinics.service_purchase_extras import _purchase_settings

    requested = str(payload.get("invoice_status") or "approved").strip()
    if requested == "draft":
        return "draft"
    limit = _purchase_settings(tenant_id)["approval_limit"]
    if total > limit and not payload.get("force_approve"):
        return "draft"
    return "approved"


def update_purchase(tenant_id: int, purchase_id: int, payload: dict, actor_id=None) -> dict:
    purchase = ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).with_for_update().first()
    if not purchase:
        raise ValueError("فاتورة الشراء غير موجودة")
    if purchase.invoice_status == "cancelled":
        raise ValueError("لا يمكن تعديل فاتورة ملغاة")
    if purchase.receipt_status != "pending":
        raise ValueError("لا يمكن تعديل فاتورة تم استلامها")
    if int(purchase.paid or 0) > 0:
        raise ValueError("لا يمكن تعديل فاتورة بها مدفوعات")

    supplier_id = int(payload.get("supplier_id") or purchase.supplier_id)
    supplier_invoice_no = str(payload.get("supplier_invoice_no") or purchase.supplier_invoice_no or "").strip()
    if supplier_invoice_no:
        dup = check_duplicate_invoice(tenant_id, supplier_id, supplier_invoice_no, exclude_id=purchase.id)
        if dup.get("duplicate"):
            raise ValueError(f"فاتورة المورد مسجلة مسبقاً: {dup['purchase_number']}")

    items = payload.get("items") or []
    subtotal, parsed_items = _parse_items(tenant_id, items)
    discount, shipping, tax_amount, other_charges, total = _calc_totals(subtotal, payload)

    purchase.supplier_id = supplier_id
    purchase.supplier_invoice_no = supplier_invoice_no or None
    purchase.purchase_date = _parse_date(payload.get("purchase_date") or purchase.purchase_date.isoformat(), "تاريخ الشراء")
    purchase.due_date = _parse_date(payload["due_date"], "تاريخ الاستحقاق") if payload.get("due_date") else purchase.due_date
    purchase.subtotal = subtotal
    purchase.discount = discount
    purchase.discount_percent = payload.get("discount_percent") if payload.get("discount_percent") not in (None, "") else None
    purchase.shipping_extra = shipping
    purchase.tax_amount = tax_amount
    purchase.other_charges = other_charges
    purchase.total = total
    purchase.balance = total
    purchase.paid = 0
    purchase.purchase_type = str(payload.get("purchase_type") or purchase.purchase_type or "credit")
    purchase.warehouse_name = str(payload.get("warehouse_name") or purchase.warehouse_name or "").strip() or None
    purchase.notes = str(payload.get("notes") or "").strip() or None
    purchase.invoice_status = _apply_approval_status(tenant_id, total, payload)
    _sync_payment_status(purchase)
    purchase.updated_at = datetime.utcnow()

    ClinicPurchaseItem.query.filter_by(tenant_id=tenant_id, purchase_id=purchase.id).delete()
    _add_purchase_items(tenant_id, purchase.id, parsed_items)
    _purchase_audit(tenant_id, actor_id, "purchase", purchase.id, "update", f"تعديل {purchase.purchase_number}", purchase_id=purchase.id, new_values={"total": total})
    db.session.flush()
    if purchase.invoice_status == "approved":
        from modules.clinics.accounting_service import ClinicAccountingPostingService
        ClinicAccountingPostingService.post_clinic_purchase(purchase.id, tenant_id, actor_id)
    return purchase_dict(purchase, tenant_id, detailed=True)


def copy_purchase(tenant_id: int, purchase_id: int, actor_id=None, branch_id=None) -> dict:
    source = ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).first()
    if not source:
        raise ValueError("فاتورة الشراء غير موجودة")
    items = ClinicPurchaseItem.query.filter_by(tenant_id=tenant_id, purchase_id=source.id).all()
    payload = {
        "supplier_id": source.supplier_id,
        "purchase_date": _today().isoformat(),
        "purchase_type": source.purchase_type,
        "warehouse_name": source.warehouse_name,
        "notes": f"نسخة من {source.purchase_number}",
        "discount": source.discount,
        "discount_percent": float(source.discount_percent or 0) if source.discount_percent else None,
        "shipping_extra": source.shipping_extra,
        "tax_amount": source.tax_amount,
        "other_charges": source.other_charges,
        "invoice_status": "approved",
        "items": [
            {
                "item_id": it.item_id,
                "quantity": float(it.quantity or 0),
                "free_quantity": float(it.free_quantity or 0),
                "unit_cost": it.unit_cost,
                "line_discount": it.line_discount,
                "line_discount_percent": float(it.line_discount_percent or 0) if it.line_discount_percent else None,
            }
            for it in items
        ],
    }
    result = create_purchase(tenant_id, payload, actor_id, branch_id)
    _purchase_audit(tenant_id, actor_id, "purchase", result["id"], "copy", f"نسخ من {source.purchase_number}", purchase_id=result["id"])
    return result


def approve_purchase(tenant_id: int, purchase_id: int, actor_id=None) -> dict:
    purchase = ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).with_for_update().first()
    if not purchase:
        raise ValueError("فاتورة الشراء غير موجودة")
    if purchase.invoice_status == "cancelled":
        raise ValueError("لا يمكن اعتماد فاتورة ملغاة")
    purchase.invoice_status = "approved"
    _sync_payment_status(purchase)
    purchase.updated_at = datetime.utcnow()
    _purchase_audit(tenant_id, actor_id, "purchase", purchase.id, "approve", f"اعتماد {purchase.purchase_number}", purchase_id=purchase.id)
    db.session.flush()
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.post_clinic_purchase(purchase.id, tenant_id, actor_id)
    return purchase_dict(purchase, tenant_id, detailed=True)


def receive_purchase(tenant_id: int, purchase_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    purchase = ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).with_for_update().first()
    if not purchase:
        raise ValueError("فاتورة الشراء غير موجودة")
    if purchase.invoice_status == "draft":
        raise ValueError("لا يمكن استلام فاتورة مسودة — يجب اعتمادها أولاً")
    if purchase.invoice_status == "cancelled":
        raise ValueError("لا يمكن استلام فاتورة ملغاة")
    if purchase.receipt_status == "complete":
        raise ValueError("تم استلام هذه الفاتورة بالكامل")
    submitted = payload.get("items") or []
    if not submitted:
        raise ValueError("أدخل الكميات المستلمة")

    purchase_items = {
        row.id: row
        for row in ClinicPurchaseItem.query.filter_by(tenant_id=tenant_id, purchase_id=purchase.id)
        .with_for_update()
        .all()
    }
    receipt = ClinicPurchaseReceipt(
        tenant_id=tenant_id,
        purchase_id=purchase.id,
        branch_id=branch_id,
        receipt_number=f"GRN-{purchase.id:05d}-{ClinicPurchaseReceipt.query.filter_by(tenant_id=tenant_id, purchase_id=purchase.id).count() + 1:02d}",
        notes=str(payload.get("notes") or "").strip() or None,
        received_by=actor_id,
    )
    db.session.add(receipt)
    db.session.flush()
    received_any = False
    for raw in submitted:
        line = purchase_items.get(int(raw.get("purchase_item_id") or 0))
        if not line:
            raise ValueError("بند الشراء غير صالح")
        qty = _qty(raw.get("quantity"))
        if qty <= 0:
            continue
        ordered_total = _qty(line.quantity) + _qty(line.free_quantity)
        remaining = ordered_total - _qty(line.received_quantity)
        if qty > remaining:
            raise ValueError("الكمية المستلمة أكبر من المتبقي")
        item = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=line.item_id).first()
        batch_number = str(raw.get("batch_number") or line.batch_number or "").strip()
        expiry_date = raw.get("expiry_date") or (line.expiry_date.isoformat() if line.expiry_date else None)
        if item and item.batch_tracking and not batch_number:
            raise ValueError(f"رقم الدفعة مطلوب للصنف: {item.name}")
        if expiry_date and item and item.expiry_tracking:
            exp = _parse_date(expiry_date, "تاريخ الانتهاء")
            if exp < _today():
                raise ValueError(f"لا يمكن استلام دفعة منتهية الصلاحية: {item.name}")
        stock_in(
            tenant_id,
            line.item_id,
            {
                "quantity": qty,
                "batch_number": batch_number,
                "manufacturing_date": raw.get("manufacturing_date"),
                "expiry_date": expiry_date,
                "unit_cost": raw.get("unit_cost") or line.unit_cost,
                "supplier_id": purchase.supplier_id,
                "purchase_id": purchase.id,
                "reference_type": "purchase_receipt",
                "reference_id": receipt.id,
                "reason": "purchase",
                "branch_id": branch_id,
                "notes": f"استلام {receipt.receipt_number} من {purchase.purchase_number}",
            },
            actor_id,
        )
        from modules.clinics.models import ClinicInventoryBatch

        batch = (
            ClinicInventoryBatch.query.filter_by(
                tenant_id=tenant_id, item_id=line.item_id, purchase_id=purchase.id, batch_number=batch_number
            )
            .order_by(ClinicInventoryBatch.id.desc())
            .first()
            if batch_number
            else None
        )
        line.received_quantity = _qty(line.received_quantity) + qty
        db.session.add(
            ClinicPurchaseReceiptItem(
                tenant_id=tenant_id,
                receipt_id=receipt.id,
                purchase_item_id=line.id,
                batch_id=batch.id if batch else None,
                quantity=qty,
                unit_cost=int(raw.get("unit_cost") or line.unit_cost or 0),
                batch_number=batch_number or None,
                manufacturing_date=_parse_date(raw.get("manufacturing_date"), "تاريخ الإنتاج")
                if raw.get("manufacturing_date")
                else None,
                expiry_date=_parse_date(expiry_date, "تاريخ الانتهاء") if expiry_date else None,
            )
        )
        received_any = True
    if not received_any:
        raise ValueError("لا توجد كمية صالحة للاستلام")
    all_complete = all(
        _qty(line.received_quantity) >= (_qty(line.quantity) + _qty(line.free_quantity))
        for line in purchase_items.values()
    )
    purchase.receipt_status = "complete" if all_complete else "partial"
    purchase.updated_at = datetime.utcnow()
    _purchase_audit(
        tenant_id,
        actor_id,
        "purchase_receipt",
        receipt.id,
        "receive",
        f"استلام {receipt.receipt_number}",
        purchase_id=purchase.id,
        branch_id=branch_id,
    )
    db.session.flush()
    return purchase_dict(purchase, tenant_id, detailed=True)


def record_purchase_payment(tenant_id: int, purchase_id: int, payload: dict, actor_id=None) -> dict:
    purchase = ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).with_for_update().first()
    if not purchase:
        raise ValueError("فاتورة الشراء غير موجودة")
    if purchase.invoice_status == "draft":
        raise ValueError("لا يمكن تسجيل دفعة لفاتورة مسودة — يجب اعتمادها أولاً")
    if purchase.invoice_status == "cancelled":
        raise ValueError("لا يمكن تسجيل دفعة لفاتورة ملغاة")
    _record_payment_internal(tenant_id, purchase, payload, actor_id)
    purchase.updated_at = datetime.utcnow()
    db.session.flush()
    return purchase_dict(purchase, tenant_id, detailed=True)


def cancel_purchase(tenant_id: int, purchase_id: int, actor_id=None) -> dict:
    purchase = ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).with_for_update().first()
    if not purchase:
        raise ValueError("فاتورة الشراء غير موجودة")
    if purchase.receipt_status in ("partial", "complete"):
        raise ValueError("لا يمكن إلغاء فاتورة تم استلامها")
    purchase.invoice_status = "cancelled"
    _sync_payment_status(purchase)
    purchase.updated_at = datetime.utcnow()
    _purchase_audit(tenant_id, actor_id, "purchase", purchase.id, "cancel", f"إلغاء {purchase.purchase_number}", purchase_id=purchase.id)
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.reverse_posting(
        tenant_id, "clinic_purchase", purchase.id,
        source_event_prefix="purchase_created", reversal_event="voided", actor_id=actor_id,
    )
    db.session.flush()
    return purchase_dict(purchase, tenant_id, detailed=True)


def supplier_statement(tenant_id: int, supplier_id: int) -> dict:
    supplier = ClinicSupplier.query.filter_by(tenant_id=tenant_id, id=supplier_id).first()
    if not supplier:
        raise ValueError("المورد غير موجود")
    purchases = ClinicPurchase.query.filter_by(tenant_id=tenant_id, supplier_id=supplier_id).order_by(
        ClinicPurchase.purchase_date.asc(), ClinicPurchase.id.asc()
    ).all()
    lines = []
    balance = int(supplier.opening_balance or 0)
    if balance:
        lines.append({"date": "", "type": "opening", "reference": "رصيد افتتاحي", "debit": balance, "credit": 0, "balance": balance})
    for p in purchases:
        if p.invoice_status == "cancelled":
            continue
        balance += p.total
        lines.append(
            {
                "date": p.purchase_date.isoformat(),
                "type": "purchase",
                "reference": p.purchase_number,
                "debit": p.total,
                "credit": 0,
                "balance": balance,
            }
        )
        payments = ClinicPurchasePayment.query.filter_by(tenant_id=tenant_id, purchase_id=p.id).all()
        for pay in payments:
            balance -= pay.amount
            lines.append(
                {
                    "date": pay.payment_date.isoformat(),
                    "type": "payment",
                    "reference": pay.payment_number,
                    "debit": 0,
                    "credit": pay.amount,
                    "balance": balance,
                }
            )
        legacy_paid = int(p.paid or 0) - sum(pay.amount for pay in payments)
        if legacy_paid > 0:
            balance -= legacy_paid
            lines.append(
                {
                    "date": p.purchase_date.isoformat(),
                    "type": "payment",
                    "reference": f"PAY-{p.id}",
                    "debit": 0,
                    "credit": legacy_paid,
                    "balance": balance,
                }
            )
        from modules.clinics.models import ClinicPurchaseReturn

        for ret in ClinicPurchaseReturn.query.filter_by(tenant_id=tenant_id, purchase_id=p.id).all():
            balance -= ret.total_value
            lines.append(
                {
                    "date": ret.return_date.isoformat(),
                    "type": "return",
                    "reference": ret.return_number,
                    "debit": 0,
                    "credit": ret.total_value,
                    "balance": balance,
                }
            )
    return {"supplier": supplier_dict(supplier), "outstanding_balance": balance, "lines": lines}
