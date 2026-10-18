"""Freeze the commercial/FIFO source once a posted return depends on it."""
from flask import g
from sqlalchemy import inspect
from models.invoice import Invoice
from models.order_item import OrderItem
from models.inventory_lot import OrderItemCostLayer
from models.invoice_payment_ledger import InvoicePaymentLedger
from .facts import available
from .models import SalesReturnOrigin, ReturnEvidenceError


def guard_sources(session):
    changed = list(session.new) + list(session.dirty) + list(session.deleted)
    candidates = []
    for row in changed:
        invoice_id = row.id if isinstance(row, Invoice) else row.invoice_id if isinstance(row, (OrderItem, InvoicePaymentLedger)) else None
        if isinstance(row, OrderItemCostLayer):
            item = session.get(OrderItem, row.order_item_id) if row.order_item_id else row.order_item
            invoice_id = item.invoice_id if item else None
        if invoice_id:
            candidates.append((row, invoice_id))
    if not candidates or not available():
        return
    with session.no_autoflush:
        protected = {row[0] for row in session.query(SalesReturnOrigin.invoice_id).filter(
            SalesReturnOrigin.tenant_key == g.tenant,
            SalesReturnOrigin.invoice_id.in_({invoice_id for _, invoice_id in candidates})).all()}
    for row, invoice_id in candidates:
        if invoice_id not in protected:
            continue
        if row in session.deleted:
            raise ReturnEvidenceError("أصل البيع مرتبط بمرتجع معتمد؛ لا يمكن حذف دليله")
        if isinstance(row, InvoicePaymentLedger) and row in session.new:
            continue
        if isinstance(row, Invoice):
            fields = ("discount_amount", "currency", "exchange_rate", "customer_id", "branch_id",
                "source_module", "shipping_fee", "shipping_company_id", "delivery_agent_id", "created_at")
            if not session.info.get("sales_return_atomic"):
                fields += ("total", "stock_is_deducted")
                if inspect(row).attrs.status.history.has_changes() and row.status in {"تم الطلب", "ملغي", "راجع", "مرتجع", "راجعة"}:
                    raise ReturnEvidenceError("استخدم مسار المرتجع المرتبط لتغيير حالة البيع")
        else:
            if row in session.new:
                raise ReturnEvidenceError("لا تضاف بنود أو طبقات إلى أصل بيع له مرتجع معتمد")
            fields = tuple(column.key for column in inspect(type(row)).columns)
        if any(inspect(row).attrs[field].history.has_changes() for field in fields):
            raise ReturnEvidenceError("أسعار وكميات وكلفة وأطراف البيع محفوظة بدليل مرتجع؛ يلزم مستند مستقل")
