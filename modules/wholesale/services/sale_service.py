"""Wholesale sales against Invoice + OrderItem + warehouse stock."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
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


def _tenant_invoices(tenant_id: int | None):
    q = Invoice.query.filter(
        Invoice.source_module == "wholesale",
        Invoice.deleted_at.is_(None),
    )
    if tenant_id is not None:
        q = q.filter(or_(Invoice.tenant_id == tenant_id, Invoice.tenant_id.is_(None)))
    return q


def next_invoice_no(tenant_id: int | None) -> str:
    last = _tenant_invoices(tenant_id).order_by(Invoice.id.desc()).first()
    return next_doc_no("WS", getattr(last, "invoice_no", None) if last else None)


def search_products(tenant_id: int | None, q: str, warehouse_id: int | None = None, limit: int = 30) -> list[dict]:
    term = (q or "").strip()
    query = Product.query.filter(Product.active.is_(True))
    if tenant_id is not None:
        query = query.filter(or_(Product.tenant_id == tenant_id, Product.tenant_id.is_(None)))
    if term:
        like = f"%{term}%"
        filters = [Product.name.ilike(like), Product.barcode.ilike(like)]
        if hasattr(Product, "sku"):
            filters.append(Product.sku.ilike(like))
        query = query.filter(or_(*filters))
    products = query.order_by(Product.name.asc()).limit(limit).all()
    out = []
    for p in products:
        avail = None
        stock = None
        if warehouse_id:
            stock = warehouse_service.stock_snapshot(tenant_id, warehouse_id, p.id)
            avail = stock["available"]
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "barcode": p.barcode,
                "sku": getattr(p, "sku", None),
                "sale_price": int(p.sale_price or 0),
                "buy_price": int(p.buy_price or 0),
                "exchange_sale_price": getattr(p, "exchange_sale_price", None),
                "available_qty": avail,
                "stock": stock,
            }
        )
    return out


def create_or_update_sale(
    tenant_id: int | None,
    payload: dict,
    *,
    employee_id: int | None = None,
    confirm: bool = False,
    as_draft: bool = False,
) -> Invoice:
    customer_id = parse_int(payload.get("customer_id"))
    warehouse_id = parse_int(payload.get("warehouse_id"))
    if customer_id <= 0:
        raise WholesaleError("اختر العميل")
    if warehouse_id <= 0:
        raise WholesaleError("اختر المخزن")

    customer = Customer.query.get(customer_id)
    if not customer:
        raise WholesaleError("العميل غير موجود")
    if tenant_id is not None and customer.tenant_id not in (tenant_id, None):
        raise WholesaleError("العميل لا يتبع هذه الشركة")

    warehouse_service.get_warehouse(tenant_id, warehouse_id)

    currency = normalize_currency(payload.get("currency"))
    exchange_rate = parse_float(payload.get("exchange_rate"), 1.0 if currency == "IQD" else 1500.0)
    sale_type = (payload.get("sale_type") or "credit").strip().lower()
    if sale_type not in ("cash", "credit", "partial"):
        sale_type = "credit"

    lines = payload.get("lines") or payload.get("items") or []
    if not lines:
        raise WholesaleError("أضف منتجاً واحداً على الأقل")

    invoice_id = parse_int(payload.get("id") or payload.get("invoice_id"))
    invoice = None
    if invoice_id:
        invoice = _tenant_invoices(tenant_id).filter(Invoice.id == invoice_id).first()
        if not invoice:
            raise WholesaleError("الفاتورة غير موجودة")
        if not invoice.is_draft and invoice.status not in ("مسودة", "draft"):
            raise WholesaleError("لا يمكن تعديل فاتورة معتمدة")
        for item in list(invoice.items):
            db.session.delete(item)
        db.session.flush()
    else:
        invoice_no = (payload.get("invoice_no") or "").strip() or next_invoice_no(tenant_id)
        dup = _tenant_invoices(tenant_id).filter(Invoice.invoice_no == invoice_no).first()
        if dup:
            raise WholesaleError("رقم الفاتورة مكرر", "duplicate_invoice")
        invoice = Invoice(
            tenant_id=tenant_id,
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee_id,
            invoice_no=invoice_no,
            source_module="wholesale",
            is_draft=True,
            status="مسودة",
        )
        db.session.add(invoice)
        db.session.flush()

    subtotal = 0
    line_discount_total = 0
    cogs_total = 0
    for raw in lines:
        product_id = parse_int(raw.get("product_id"))
        qty = parse_int(raw.get("quantity"), 1)
        price = parse_int(raw.get("price"))
        discount = max(0, parse_int(raw.get("discount"), 0))
        if product_id <= 0 or qty <= 0:
            continue
        product = Product.query.get(product_id)
        if not product:
            raise WholesaleError(f"منتج غير موجود: {product_id}")
        if price <= 0:
            price = int(product.sale_price or 0)
        line_total = max(0, price * qty - discount)
        cost = int(product.buy_price or 0)
        item = OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            price=price,
            quantity=qty,
            cost=cost,
            total=line_total,
            discount_value=discount,
            warehouse_id=warehouse_id,
            sale_mode="normal",
        )
        db.session.add(item)
        subtotal += price * qty
        line_discount_total += discount
        cogs_total += cost * qty

    header_discount = max(0, parse_int(payload.get("discount_amount"), 0))
    shipping_fee = max(0, parse_int(payload.get("shipping_fee"), 0))
    paid_amount = max(0, parse_int(payload.get("paid_amount"), 0))
    grand = max(0, subtotal - line_discount_total - header_discount + shipping_fee)

    if sale_type == "cash":
        paid_amount = grand
    elif sale_type == "credit":
        paid_amount = min(paid_amount, grand)
        if paid_amount == 0:
            pass
    else:
        paid_amount = min(paid_amount, grand)

    invoice.customer_id = customer.id
    invoice.customer_name = customer.name
    invoice.warehouse_id = warehouse_id
    invoice.currency = currency
    invoice.exchange_rate = exchange_rate
    invoice.payment_currency = normalize_currency(payload.get("payment_currency") or currency)
    invoice.sale_type = sale_type
    invoice.discount_amount = header_discount + line_discount_total
    invoice.shipping_fee = shipping_fee
    invoice.total = grand
    invoice.paid_amount = paid_amount
    invoice.note = (payload.get("note") or payload.get("notes") or "") or None
    invoice.employee_id = employee_id
    invoice.branch_id = parse_int(payload.get("branch_id")) or invoice.branch_id
    invoice.source_module = "wholesale"
    if payload.get("date"):
        invoice.created_at = datetime.combine(parse_date(payload.get("date")), datetime.min.time())

    remaining = grand - paid_amount
    if remaining <= 0:
        invoice.payment_status = "مسدد"
    elif paid_amount > 0:
        invoice.payment_status = "جزئي"
    else:
        invoice.payment_status = "غير مسدد"

    if as_draft or (not confirm):
        invoice.is_draft = True
        invoice.status = "مسودة"
        invoice.stock_is_deducted = False
        db.session.flush()
        return invoice

    # Confirm inside caller transaction
    _confirm_sale(tenant_id, invoice, cogs_total=cogs_total, employee_id=employee_id)
    return invoice


def _confirm_sale(tenant_id: int | None, invoice: Invoice, *, cogs_total: int, employee_id: int | None) -> None:
    if not invoice.items:
        raise WholesaleError("الفاتورة بلا بنود")
    for item in invoice.items:
        warehouse_service.apply_movement(
            tenant_id,
            warehouse_id=invoice.warehouse_id,
            product_id=item.product_id,
            quantity_delta=-int(item.quantity),
            movement_type="out",
            reference_type="wholesale_sale",
            reference_id=invoice.id,
            unit_cost=int(item.cost or 0),
            created_by=employee_id,
        )
        # Keep product.quantity in sync for shared catalog views
        product = Product.query.get(item.product_id)
        if product is not None:
            product.quantity = max(0, int(product.quantity or 0) - int(item.quantity))

    invoice.is_draft = False
    invoice.status = "مكتمل"
    invoice.stock_is_deducted = True
    invoice.stock_deducted_at = datetime.utcnow()

    entry_date = invoice.created_at.date() if invoice.created_at else datetime.utcnow().date()
    party_ledger_service.add_entry(
        tenant_id,
        party_type="customer",
        party_id=invoice.customer_id,
        entry_date=entry_date,
        entry_type="sale",
        debit=int(invoice.total or 0),
        credit=0,
        currency=invoice.currency or "IQD",
        exchange_rate=float(invoice.exchange_rate or 1),
        doc_no=invoice.invoice_no,
        description=f"فاتورة بيع {invoice.invoice_no}",
        reference_type="wholesale_sale",
        reference_id=invoice.id,
        created_by=employee_id,
    )
    if int(invoice.paid_amount or 0) > 0:
        party_ledger_service.add_entry(
            tenant_id,
            party_type="customer",
            party_id=invoice.customer_id,
            entry_date=entry_date,
            entry_type="receipt",
            debit=0,
            credit=int(invoice.paid_amount or 0),
            currency=invoice.payment_currency or invoice.currency or "IQD",
            exchange_rate=float(invoice.exchange_rate or 1),
            doc_no=invoice.invoice_no,
            description=f"دفعة مع فاتورة بيع {invoice.invoice_no}",
            reference_type="wholesale_sale_payment",
            reference_id=invoice.id,
            created_by=employee_id,
        )

    cogs_base = to_base_amount(cogs_total, invoice.currency or "IQD", float(invoice.exchange_rate or 1))
    # COGS is already in purchase cost units (typically IQD)
    journal_hooks.post_sale_journals(invoice, cogs=cogs_total)
    db.session.flush()


def confirm_sale(tenant_id: int | None, invoice_id: int, employee_id: int | None = None) -> Invoice:
    invoice = _tenant_invoices(tenant_id).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise WholesaleError("الفاتورة غير موجودة")
    if not invoice.is_draft and invoice.status not in ("مسودة", "draft"):
        raise WholesaleError("الفاتورة معتمدة مسبقاً")
    cogs = sum(int(i.cost or 0) * int(i.quantity or 0) for i in invoice.items)
    _confirm_sale(tenant_id, invoice, cogs_total=cogs, employee_id=employee_id)
    return invoice


def list_sales(tenant_id: int | None, limit: int = 100, include_drafts: bool = True) -> list[Invoice]:
    q = _tenant_invoices(tenant_id)
    if not include_drafts:
        q = q.filter(or_(Invoice.is_draft.is_(False), Invoice.is_draft.is_(None)))
    return q.order_by(Invoice.id.desc()).limit(limit).all()


def sale_to_dict(invoice: Invoice) -> dict:
    return {
        "id": invoice.id,
        "invoice_no": invoice.invoice_no,
        "customer_id": invoice.customer_id,
        "customer_name": invoice.customer_name,
        "warehouse_id": invoice.warehouse_id,
        "currency": invoice.currency or "IQD",
        "exchange_rate": float(invoice.exchange_rate or 1),
        "sale_type": invoice.sale_type,
        "total": int(invoice.total or 0),
        "discount_amount": int(invoice.discount_amount or 0),
        "shipping_fee": int(getattr(invoice, "shipping_fee", 0) or 0),
        "paid_amount": int(invoice.paid_amount or 0),
        "remaining": max(0, int(invoice.total or 0) - int(invoice.paid_amount or 0)),
        "payment_status": invoice.payment_status,
        "status": invoice.status,
        "is_draft": bool(invoice.is_draft),
        "note": invoice.note,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "lines": [
            {
                "product_id": i.product_id,
                "product_name": i.product_name,
                "quantity": i.quantity,
                "price": i.price,
                "discount": int(getattr(i, "discount_value", 0) or 0),
                "total": i.total,
            }
            for i in (invoice.items or [])
        ],
    }
