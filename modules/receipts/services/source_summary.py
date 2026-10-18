"""Source summaries: customer / courier / shipping company outstanding."""
from __future__ import annotations

from sqlalchemy import or_, and_

from models.customer import Customer
from models.delivery_agent import DeliveryAgent
from models.invoice import Invoice
from models.shipping import ShippingCompany
from modules.receipts.services.helpers import (
    SOURCE_COURIER,
    SOURCE_CUSTOMER,
    SOURCE_SHIPPING,
    ReceiptError,
    invoice_remaining,
)
from utils.order_status import (
    CANCELED_STATUSES,
    COMPLETED_STATUSES,
    RETURN_STATUSES,
    is_canceled,
    is_returned,
)


def _base_open_invoice_filter():
    return and_(
        or_(Invoice.is_draft.is_(False), Invoice.is_draft.is_(None)),
        or_(Invoice.deleted_at.is_(None), Invoice.deleted_at == None),  # noqa: E711
        or_(
            Invoice.status.is_(None),
            ~Invoice.status.in_(list(CANCELED_STATUSES) + list(RETURN_STATUSES)),
        ),
        or_(
            Invoice.payment_status.is_(None),
            ~Invoice.payment_status.in_(list(CANCELED_STATUSES) + list(RETURN_STATUSES)),
        ),
        or_(Invoice.source_module.is_(None), Invoice.source_module != "wholesale"),
    )


def _invoice_dict(inv: Invoice) -> dict:
    total = int(inv.total or 0)
    paid = int(inv.paid_amount or 0)
    remaining = max(0, total - paid)
    status = inv.payment_status or "غير مسدد"
    if remaining <= 0:
        pay_label = "مسدد"
    elif paid > 0:
        pay_label = "مسدد جزئياً"
    else:
        pay_label = "غير مسدد"
    return {
        "id": inv.id,
        "invoice_no": getattr(inv, "invoice_no", None) or str(inv.id),
        "date": (inv.created_at.date().isoformat() if inv.created_at else None),
        "customer_name": inv.customer.name if getattr(inv, "customer", None) else None,
        "total": total,
        "paid_amount": paid,
        "remaining": remaining,
        "payment_status": status,
        "status_label": pay_label,
        "status": inv.status,
        "delivery_fee": int(getattr(inv, "delivery_fee", 0) or getattr(inv, "shipping_fee", 0) or 0),
    }


def customer_open_invoices(customer_id: int) -> list[Invoice]:
    q = Invoice.query.filter(
        Invoice.customer_id == customer_id,
        _base_open_invoice_filter(),
    ).order_by(Invoice.created_at.asc(), Invoice.id.asc())
    return [inv for inv in q.all() if invoice_remaining(inv) > 0]


def courier_open_invoices(agent_id: int) -> list[Invoice]:
    """كل الطلبات غير المسددة المرتبطة بالمندوب (وليس فقط المسلّمة).

    كان الفلتر السابق يقتصر على حالة «تم التوصيل»، لذلك الطلبات الجديدة
    (تم الطلب / معباة / جاري الشحن) لا تظهر في سند القبض.
    """
    q = Invoice.query.filter(
        Invoice.delivery_agent_id == agent_id,
        _base_open_invoice_filter(),
    ).order_by(Invoice.created_at.asc(), Invoice.id.asc())
    rows = []
    for inv in q.all():
        if is_canceled(inv.status, inv.payment_status) or is_returned(inv.status, inv.payment_status):
            continue
        if (inv.payment_status or "").strip() == "مسدد":
            continue
        if invoice_remaining(inv) <= 0:
            continue
        rows.append(inv)
    return rows


def shipping_open_invoices(company_id: int) -> list[Invoice]:
    """طلبات شركة النقل غير المسددة بالكامل وغير المسوّاة مع الشركة."""
    settled = {"تم التسديد", "مسدد من الشركة"}
    q = Invoice.query.filter(
        Invoice.shipping_company_id == company_id,
        _base_open_invoice_filter(),
        or_(Invoice.shipping_status.is_(None), ~Invoice.shipping_status.in_(list(settled))),
    ).order_by(Invoice.created_at.asc(), Invoice.id.asc())
    rows = []
    for inv in q.all():
        if is_canceled(inv.status, inv.payment_status) or is_returned(inv.status, inv.payment_status):
            continue
        if (inv.payment_status or "").strip() == "مسدد" and invoice_remaining(inv) <= 0:
            continue
        if invoice_remaining(inv) <= 0:
            continue
        rows.append(inv)
    return rows


def open_invoices_for_source(source_type: str, source_id: int) -> list[Invoice]:
    if source_type == SOURCE_CUSTOMER:
        return customer_open_invoices(source_id)
    if source_type == SOURCE_COURIER:
        return courier_open_invoices(source_id)
    if source_type == SOURCE_SHIPPING:
        return shipping_open_invoices(source_id)
    raise ReceiptError("نوع الجهة غير معروف")


def resolve_source(source_type: str, source_id: int):
    if source_type == SOURCE_CUSTOMER:
        obj = Customer.query.get(source_id)
        if not obj:
            raise ReceiptError("العميل غير موجود")
        return obj, obj.name, getattr(obj, "phone", None)
    if source_type == SOURCE_COURIER:
        obj = DeliveryAgent.query.get(source_id)
        if not obj:
            raise ReceiptError("المندوب غير موجود")
        return obj, obj.name, getattr(obj, "phone", None)
    if source_type == SOURCE_SHIPPING:
        obj = ShippingCompany.query.get(source_id)
        if not obj:
            raise ReceiptError("شركة النقل غير موجودة")
        return obj, obj.name, getattr(obj, "phone", None)
    raise ReceiptError("نوع الجهة غير معروف")


def source_summary(source_type: str, source_id: int) -> dict:
    source, name, phone = resolve_source(source_type, source_id)
    opens = open_invoices_for_source(source_type, source_id)
    invoices = [_invoice_dict(inv) for inv in opens]
    balance = sum(r["remaining"] for r in invoices)

    base = {
        "source_type": source_type,
        "source_id": source_id,
        "name": name,
        "phone": phone,
        "balance": balance,
        "open_count": len(invoices),
        "invoices": invoices,
    }

    if source_type == SOURCE_CUSTOMER:
        oldest = invoices[0] if invoices else None
        last_paid = (
            Invoice.query.filter(
                Invoice.customer_id == source_id,
                Invoice.payment_status.in_(["مسدد", "جزئي"]),
            )
            .order_by(Invoice.created_at.desc())
            .first()
        )
        base.update(
            {
                "oldest_invoice": oldest["invoice_no"] if oldest else None,
                "oldest_date": oldest["date"] if oldest else None,
                "open_invoices_total": balance,
                "last_payment_amount": int(last_paid.paid_amount or 0) if last_paid else None,
                "last_payment_date": last_paid.created_at.date().isoformat()
                if last_paid and last_paid.created_at
                else None,
            }
        )
    elif source_type == SOURCE_COURIER:
        delivered_count = (
            Invoice.query.filter(
                Invoice.delivery_agent_id == source_id,
                Invoice.status.in_(list(COMPLETED_STATUSES) + ["تم التسليم"]),
            ).count()
        )
        base.update(
            {
                "delivered_count": delivered_count,
                "outstanding_count": len(invoices),
                "net_due": balance,
            }
        )
    elif source_type == SOURCE_SHIPPING:
        base.update(
            {
                "cod_total": balance,
                "outstanding_count": len(invoices),
                "net_due": balance,
                "opening_balance": int(getattr(source, "opening_balance", 0) or 0),
            }
        )
    return base


def search_sources(source_type: str, q: str, limit: int = 20) -> list[dict]:
    term = (q or "").strip()
    limit = max(1, min(int(limit or 20), 50))
    rows = []
    if source_type == SOURCE_CUSTOMER:
        query = Customer.query
        if term:
            like = f"%{term}%"
            query = query.filter(
                or_(Customer.name.ilike(like), Customer.phone.ilike(like), Customer.phone2.ilike(like))
            )
        for c in query.order_by(Customer.id.desc()).limit(limit).all():
            rows.append({"id": c.id, "name": c.name, "phone": c.phone, "source_type": SOURCE_CUSTOMER})
    elif source_type == SOURCE_COURIER:
        query = DeliveryAgent.query.filter(
            or_(DeliveryAgent.is_active.is_(True), DeliveryAgent.is_active.is_(None))
        )
        if term:
            like = f"%{term}%"
            query = query.filter(or_(DeliveryAgent.name.ilike(like), DeliveryAgent.phone.ilike(like)))
        for a in query.order_by(DeliveryAgent.name.asc()).limit(limit).all():
            rows.append({"id": a.id, "name": a.name, "phone": a.phone, "source_type": SOURCE_COURIER})
    elif source_type == SOURCE_SHIPPING:
        query = ShippingCompany.query
        if term:
            like = f"%{term}%"
            query = query.filter(
                or_(ShippingCompany.name.ilike(like), ShippingCompany.phone.ilike(like))
            )
        for s in query.order_by(ShippingCompany.name.asc()).limit(limit).all():
            rows.append({"id": s.id, "name": s.name, "phone": s.phone, "source_type": SOURCE_SHIPPING})
    else:
        raise ReceiptError("نوع الجهة غير معروف")
    return rows
