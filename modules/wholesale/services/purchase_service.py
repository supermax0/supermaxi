"""Wholesale purchases against Purchase + PurchaseItem + warehouse stock."""
from __future__ import annotations

from sqlalchemy import or_

from extensions import db
from models.product import Product
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from models.supplier import Supplier
from modules.wholesale.services import journal_hooks, party_ledger_service, warehouse_service
from modules.wholesale.services.helpers import (
    WholesaleError,
    next_doc_no,
    normalize_currency,
    parse_date,
    parse_float,
    parse_int,
    to_base_amount,
)


def _tenant_purchases(tenant_id: int | None):
    q = Purchase.query.filter(
        Purchase.source_module == "wholesale",
        Purchase.deleted_at.is_(None),
    )
    return q


def next_purchase_no(tenant_id: int | None) -> str:
    last = _tenant_purchases(tenant_id).order_by(Purchase.id.desc()).first()
    return next_doc_no("WP", getattr(last, "invoice_no", None) if last else None)


def create_or_update_purchase(
    tenant_id: int | None,
    payload: dict,
    *,
    employee_id: int | None = None,
    confirm: bool = False,
    as_draft: bool = False,
) -> Purchase:
    supplier_id = parse_int(payload.get("supplier_id"))
    warehouse_id = parse_int(payload.get("warehouse_id"))
    if supplier_id <= 0:
        raise WholesaleError("اختر المورد")
    if warehouse_id <= 0:
        raise WholesaleError("اختر المخزن المستلم")

    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        raise WholesaleError("المورد غير موجود")
    warehouse_service.get_warehouse(tenant_id, warehouse_id)

    lines = payload.get("lines") or payload.get("items") or []
    if not lines:
        raise WholesaleError("أضف منتجات الشراء")

    currency = normalize_currency(payload.get("currency"))
    exchange_rate = parse_float(payload.get("exchange_rate"), 1.0 if currency == "IQD" else 1500.0)
    purchase_mode = (payload.get("purchase_mode") or payload.get("sale_type") or "credit").strip().lower()
    if purchase_mode not in ("cash", "credit", "mixed", "partial"):
        purchase_mode = "credit"
    if purchase_mode == "partial":
        purchase_mode = "mixed"

    purchase_id = parse_int(payload.get("id") or payload.get("purchase_id"))
    purchase = None
    if purchase_id:
        purchase = _tenant_purchases(tenant_id).filter(Purchase.id == purchase_id).first()
        if not purchase:
            raise WholesaleError("فاتورة الشراء غير موجودة")
        if purchase.status == "confirmed" and not purchase.is_draft:
            raise WholesaleError("لا يمكن تعديل شراء معتمد")
        for it in list(purchase.items):
            db.session.delete(it)
        db.session.flush()
    else:
        invoice_no = (payload.get("invoice_no") or "").strip() or next_purchase_no(tenant_id)
        first_pid = parse_int(lines[0].get("product_id"))
        first_product = Product.query.get(first_pid)
        if not first_product:
            raise WholesaleError("منتج غير صالح في أول بند")
        purchase = Purchase(
            supplier_id=supplier_id,
            product_id=first_product.id,
            quantity=1,
            price=0,
            total=0,
            invoice_no=invoice_no,
            status="draft",
            is_draft=True,
            source_module="wholesale",
            warehouse_id=warehouse_id,
            created_by_employee_id=employee_id,
        )
        db.session.add(purchase)
        db.session.flush()

    sub_total = 0
    parsed_items = []
    for raw in lines:
        pid = parse_int(raw.get("product_id"))
        qty = parse_int(raw.get("quantity"), 1)
        unit = parse_int(raw.get("price") or raw.get("unit_cost"))
        discount = max(0, parse_int(raw.get("discount"), 0))
        if pid <= 0 or qty <= 0:
            continue
        product = Product.query.get(pid)
        if not product:
            raise WholesaleError(f"منتج غير موجود: {pid}")
        final_unit = max(0, unit)
        line_total = max(0, final_unit * qty - discount)
        item = PurchaseItem(
            purchase_id=purchase.id,
            product_id=product.id,
            quantity=qty,
            unit_cost_before_discount=unit,
            discount_value=discount,
            final_unit_cost=final_unit if qty == 0 else max(0, (line_total // qty) if qty else final_unit),
            line_total=line_total,
        )
        db.session.add(item)
        parsed_items.append(item)
        sub_total += line_total

    shipping_extra = max(0, parse_int(payload.get("shipping_extra") or payload.get("shipping_fee"), 0))
    customs_extra = max(0, parse_int(payload.get("customs_extra"), 0))
    other_extra = max(0, parse_int(payload.get("other_extra"), 0))
    header_discount = max(0, parse_int(payload.get("discount_value") or payload.get("discount_amount"), 0))
    extras = shipping_extra + customs_extra + other_extra
    grand = max(0, sub_total - header_discount + extras)

    # Distribute extras onto unit costs proportionally for inventory costing
    if extras > 0 and sub_total > 0 and parsed_items:
        allocated = 0
        for idx, item in enumerate(parsed_items):
            share = extras if idx == len(parsed_items) - 1 else int(round(extras * (item.line_total / sub_total)))
            if idx < len(parsed_items) - 1:
                allocated += share
            else:
                share = extras - allocated
            if item.quantity > 0:
                item.final_unit_cost = int(round((item.line_total + share) / item.quantity))
                item.line_total = item.final_unit_cost * item.quantity

    paid_total = max(0, parse_int(payload.get("paid_amount") or payload.get("paid_total"), 0))
    if purchase_mode == "cash":
        paid_total = grand
    else:
        paid_total = min(paid_total, grand)

    first = parsed_items[0] if parsed_items else None
    purchase.supplier_id = supplier_id
    purchase.warehouse_id = warehouse_id
    purchase.currency = currency
    purchase.exchange_rate = exchange_rate
    purchase.payment_currency = normalize_currency(payload.get("payment_currency") or currency)
    purchase.purchase_mode = purchase_mode
    purchase.supplier_invoice_no = (payload.get("supplier_invoice_no") or "").strip() or None
    purchase.notes = (payload.get("note") or payload.get("notes") or "") or None
    purchase.sub_total = sub_total
    purchase.discount_value = header_discount
    purchase.shipping_extra = shipping_extra
    purchase.customs_extra = customs_extra
    purchase.other_extra = other_extra
    purchase.grand_total = grand
    purchase.paid_total = paid_total
    purchase.remaining_total = max(0, grand - paid_total)
    purchase.purchase_date = parse_date(payload.get("date"))
    purchase.source_module = "wholesale"
    purchase.branch_id = parse_int(payload.get("branch_id")) or purchase.branch_id
    if first:
        purchase.product_id = first.product_id
        purchase.quantity = first.quantity
        purchase.price = first.final_unit_cost
        purchase.total = first.line_total

    if as_draft or not confirm:
        purchase.is_draft = True
        purchase.status = "draft"
        purchase.stock_applied = False
        db.session.flush()
        return purchase

    _confirm_purchase(tenant_id, purchase, employee_id=employee_id)
    return purchase


def _confirm_purchase(tenant_id: int | None, purchase: Purchase, *, employee_id: int | None) -> None:
    if not purchase.items:
        raise WholesaleError("فاتورة الشراء بلا بنود")
    if purchase.stock_applied:
        raise WholesaleError("تم تطبيق المخزون مسبقاً")

    for item in purchase.items:
        warehouse_service.apply_movement(
            tenant_id,
            warehouse_id=purchase.warehouse_id,
            product_id=item.product_id,
            quantity_delta=int(item.quantity),
            movement_type="in",
            reference_type="wholesale_purchase",
            reference_id=purchase.id,
            unit_cost=int(item.final_unit_cost or 0),
            created_by=employee_id,
            allow_negative=True,
        )
        product = Product.query.get(item.product_id)
        if product is not None:
            product.quantity = int(product.quantity or 0) + int(item.quantity)
            if item.final_unit_cost:
                product.buy_price = int(item.final_unit_cost)

    purchase.is_draft = False
    purchase.status = "confirmed"
    purchase.stock_applied = True

    party_ledger_service.add_entry(
        tenant_id,
        party_type="supplier",
        party_id=purchase.supplier_id,
        entry_date=purchase.purchase_date,
        entry_type="purchase",
        debit=0,
        credit=int(purchase.grand_total or 0),
        currency=purchase.currency or "IQD",
        exchange_rate=float(purchase.exchange_rate or 1),
        doc_no=purchase.invoice_no,
        description=f"فاتورة شراء {purchase.invoice_no}",
        reference_type="wholesale_purchase",
        reference_id=purchase.id,
        created_by=employee_id,
    )
    if int(purchase.paid_total or 0) > 0:
        party_ledger_service.add_entry(
            tenant_id,
            party_type="supplier",
            party_id=purchase.supplier_id,
            entry_date=purchase.purchase_date,
            entry_type="payment",
            debit=int(purchase.paid_total or 0),
            credit=0,
            currency=purchase.payment_currency or purchase.currency or "IQD",
            exchange_rate=float(purchase.exchange_rate or 1),
            doc_no=purchase.invoice_no,
            description=f"دفعة مع شراء {purchase.invoice_no}",
            reference_type="wholesale_purchase_payment",
            reference_id=purchase.id,
            created_by=employee_id,
        )

    amount_base = to_base_amount(
        int(purchase.grand_total or 0),
        purchase.currency or "IQD",
        float(purchase.exchange_rate or 1),
    )
    journal_hooks.post_purchase_journal(purchase, amount_base=amount_base)
    db.session.flush()


def confirm_purchase(tenant_id: int | None, purchase_id: int, employee_id: int | None = None) -> Purchase:
    purchase = _tenant_purchases(tenant_id).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise WholesaleError("فاتورة الشراء غير موجودة")
    if purchase.status == "confirmed" and purchase.stock_applied:
        raise WholesaleError("الشراء معتمد مسبقاً")
    _confirm_purchase(tenant_id, purchase, employee_id=employee_id)
    return purchase


def list_purchases(tenant_id: int | None, limit: int = 100) -> list[Purchase]:
    return _tenant_purchases(tenant_id).order_by(Purchase.id.desc()).limit(limit).all()


def purchase_to_dict(purchase: Purchase) -> dict:
    return {
        "id": purchase.id,
        "invoice_no": purchase.invoice_no,
        "supplier_id": purchase.supplier_id,
        "supplier_invoice_no": purchase.supplier_invoice_no,
        "warehouse_id": purchase.warehouse_id,
        "currency": purchase.currency or "IQD",
        "exchange_rate": float(purchase.exchange_rate or 1),
        "purchase_mode": purchase.purchase_mode,
        "sub_total": int(purchase.sub_total or 0),
        "discount_value": int(purchase.discount_value or 0),
        "shipping_extra": int(purchase.shipping_extra or 0),
        "customs_extra": int(getattr(purchase, "customs_extra", 0) or 0),
        "other_extra": int(getattr(purchase, "other_extra", 0) or 0),
        "grand_total": int(purchase.grand_total or 0),
        "paid_total": int(purchase.paid_total or 0),
        "remaining_total": int(purchase.remaining_total or 0),
        "status": purchase.status,
        "is_draft": bool(purchase.is_draft),
        "purchase_date": purchase.purchase_date.isoformat() if purchase.purchase_date else None,
        "notes": purchase.notes,
        "lines": [
            {
                "product_id": i.product_id,
                "quantity": i.quantity,
                "unit_cost": i.final_unit_cost,
                "discount": i.discount_value,
                "line_total": i.line_total,
            }
            for i in (purchase.items or [])
        ],
    }
