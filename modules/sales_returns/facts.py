"""Read posted return-document facts, never maintain a parallel balance ledger."""
from flask import g, has_app_context
from sqlalchemy import func, inspect, literal, select
from extensions import db
from .models import SalesReturn, SalesReturnLine, SalesReturnOrigin


def available():
    if not has_app_context() or not getattr(g, "tenant", None):
        return False
    with db.session.no_autoflush:
        return inspect(db.session.connection()).has_table(SalesReturn.__tablename__)


def documents(invoice_id):
    return SalesReturn.query.filter_by(tenant_key=g.tenant, invoice_id=invoice_id) if available() else None


def returned_quantities(invoice_id):
    if not available():
        return {}
    rows = db.session.query(SalesReturnLine.order_item_id, func.sum(SalesReturnLine.quantity)).join(
        SalesReturn, SalesReturn.id == SalesReturnLine.document_id).filter(
            SalesReturn.tenant_key == g.tenant, SalesReturn.invoice_id == invoice_id).group_by(
                SalesReturnLine.order_item_id).all()
    return {int(row_id): int(quantity) for row_id, quantity in rows}


def recovered_cost_expr(item_model):
    if not available():
        return literal(0)
    return select(func.coalesce(func.sum(SalesReturnLine.cost_amount), 0)).join(
        SalesReturn, SalesReturn.id == SalesReturnLine.document_id).where(
            SalesReturnLine.order_item_id == item_model.id,
            SalesReturn.tenant_key == g.tenant).correlate(item_model).scalar_subquery()


def exists_expr(invoice_model):
    return select(SalesReturn.id).where(SalesReturn.invoice_id == invoice_model.id,
        SalesReturn.tenant_key == g.tenant).correlate(invoice_model).exists()


def totals():
    if not available():
        return 0, 0
    from models.invoice import Invoice
    credit, cost = db.session.query(func.coalesce(func.sum(SalesReturn.credit_amount), 0),
        func.coalesce(func.sum(SalesReturn.cost_amount), 0)).join(
            Invoice, Invoice.id == SalesReturn.invoice_id).filter(SalesReturn.tenant_key == g.tenant).one()
    return int(credit), int(cost)


def original_total(invoice):
    if available():
        row = SalesReturnOrigin.query.filter_by(tenant_key=g.tenant, invoice_id=invoice.id).first()
        if row:
            import json
            return int(json.loads(row.snapshot)["invoice"]["total"])
    return int(invoice.total or 0)


def summary(invoice):
    if not getattr(invoice, "id", None):
        return None
    query = documents(invoice.id)
    if query is None:
        return None
    rows = query.order_by(SalesReturn.id).all()
    if not rows:
        return None
    values = {"original_total": original_total(invoice), "credit": sum(row.credit_amount for row in rows),
        "net_total": int(invoice.total or 0), "document_ids": [row.id for row in rows]}
    from .collections import for_invoice
    undated = for_invoice(invoice.id)
    if undated:
        values["undated_collection_amount"] = undated["amount"]
    return values
