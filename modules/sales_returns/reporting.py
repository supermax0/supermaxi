"""Dated corrections for reports that group current invoice balances by sale date.

Restore the original sale at its own date, then deduct each return at its
document date. No legacy receipt date is inferred by these adjustments.
"""
import json
from sqlalchemy import or_
from extensions import db
from models.invoice import Invoice
from .facts import available
from .models import SalesReturn, SalesReturnOrigin
from .allocation import SaleLine, discounted_line_values
from .line_facts import original_cost
from utils.business_time import business_date, utc_period_filter
from modules.finance.common import tenant_key


def period_adjustments(date_from, date_to):
    result = {"revenue": 0, "cogs": 0, "settled": 0, "buckets": {}, "returns": [], "original_invoice_ids": set()}
    if not available():
        return result
    sold = utc_period_filter(Invoice.created_at, date_from, date_to)
    returned = utc_period_filter(SalesReturn.created_at, date_from, date_to)
    rows = db.session.query(SalesReturn, Invoice.created_at).join(Invoice, Invoice.id == SalesReturn.invoice_id).filter(
        SalesReturn.tenant_key == tenant_key(), or_(sold, returned)).order_by(SalesReturn.id).all()

    def add(day, sign, document):
        bucket = result["buckets"].setdefault(day, {"revenue": 0, "cogs": 0, "settled": 0})
        for key, amount in (("revenue", document.credit_amount), ("cogs", document.cost_amount),
                ("settled", document.excess_collection)):
            result[key] += sign * amount
            bucket[key] += sign * amount

    for document, created_at in rows:
        sale_day = business_date(created_at)
        return_day = business_date(document.created_at)
        if sale_day is not None and date_from <= sale_day <= date_to:
            add(sale_day, 1, document)
            result["original_invoice_ids"].add(document.invoice_id)
        if date_from <= return_day <= date_to:
            add(return_day, -1, document)
            result["returns"].append({"id": document.id, "invoice_id": document.invoice_id,
                "date": return_day, "credit": document.credit_amount, "cost": document.cost_amount,
                "debt_relief": document.debt_relief, "settled_relief": document.excess_collection})
    return result


class _ActivityInvoice:
    def __init__(self, invoice, original, *, event_id, created_at, total, settled, sale_count):
        self._invoice = invoice
        self.id = event_id
        self.actual_invoice_id = invoice.id
        self.created_at = created_at
        self.total = total
        self.report_settled = settled
        self.report_sale_count = sale_count
        self.customer_name = original["invoice"]["customer_name"]

    def __getattr__(self, key):
        return getattr(self._invoice, key)


def period_activity(date_from, date_to):
    """Original sales and signed returns, with matching product allocations."""
    result = {"invoices": [], "cogs": {}, "products": [], "returns": []}
    if not available():
        return result
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from utils.order_stock_lock import stock_unlocked_filter
    in_period = lambda column: utc_period_filter(column, date_from, date_to)
    returned_ids = select(SalesReturn.invoice_id).where(
        SalesReturn.tenant_key == tenant_key(), in_period(SalesReturn.created_at))
    originals = db.session.query(Invoice, SalesReturnOrigin).join(
        SalesReturnOrigin, SalesReturnOrigin.invoice_id == Invoice.id).filter(
            SalesReturnOrigin.tenant_key == tenant_key(), stock_unlocked_filter(Invoice),
            or_(in_period(Invoice.created_at), Invoice.id.in_(returned_ids))).all()
    if not originals:
        return result
    documents = SalesReturn.query.options(selectinload(SalesReturn.lines)).filter(
        SalesReturn.tenant_key == tenant_key(), SalesReturn.invoice_id.in_([invoice.id for invoice, _ in originals])).all()
    grouped = {}
    for document in documents:
        grouped.setdefault(document.invoice_id, []).append(document)

    for invoice, origin in originals:
        original = json.loads(origin.snapshot)
        sources = {row["id"]: row for row in original["lines"] if row["physical"]}
        values = discounted_line_values(original["invoice"]["total"], [
            SaleLine(row["id"], row["quantity"], row["value"]) for row in sources.values()])
        returns = grouped.get(invoice.id, [])
        sale_day = business_date(invoice.created_at)
        if sale_day is not None and date_from <= sale_day <= date_to:
            cost = 0
            for row in sources.values():
                amount = original_cost(row)
                cost += amount
                result["products"].append({"product_id": row["product_id"], "name": row["name"],
                    "qty": row["quantity"], "revenue": values[row["id"]], "cogs": amount})
            settled = min(original["invoice"]["total"], int(invoice.paid_amount or 0) + sum(
                document.excess_collection for document in returns))
            result["invoices"].append(_ActivityInvoice(invoice, original, event_id=invoice.id,
                created_at=invoice.created_at, total=original["invoice"]["total"], settled=settled, sale_count=1))
            result["cogs"][invoice.id] = cost
        for document in returns:
            if not date_from <= business_date(document.created_at) <= date_to:
                continue
            result["invoices"].append(_ActivityInvoice(invoice, original, event_id=-document.id,
                created_at=document.created_at, total=-document.credit_amount,
                settled=-document.excess_collection, sale_count=0))
            result["cogs"][-document.id] = -document.cost_amount
            result["returns"].append({"id": document.id, "invoice_id": invoice.id,
                "date": business_date(document.created_at).isoformat(), "credit": document.credit_amount,
                "cost": document.cost_amount})
            for line in document.lines:
                row = sources[line.order_item_id]
                result["products"].append({"product_id": row["product_id"], "name": row["name"],
                    "qty": -line.quantity, "revenue": -line.credit_amount, "cogs": -line.cost_amount})
    return result
