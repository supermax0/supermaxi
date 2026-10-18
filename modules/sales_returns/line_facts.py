"""Current line quantities/values/costs from immutable original and credits."""
import json
from sqlalchemy import func
from extensions import db
from modules.finance.common import tenant_key
from .allocation import SaleLine, discounted_line_values
from .facts import available
from .models import SalesReturn, SalesReturnLine, SalesReturnOrigin, ReturnEvidenceError


def original_cost(row):
    if row["cost_layers"]:
        if sum(layer["quantity"] for layer in row["cost_layers"]) != row["quantity"]:
            raise ReturnEvidenceError("طبقات كلفة الأصل لا تغطي كميته؛ راجع دليل البيع")
        return sum(layer["quantity"] * layer["unit_cost"] for layer in row["cost_layers"])
    if type(row["saved_unit_cost"]) is not int or row["saved_unit_cost"] < 0:
        raise ReturnEvidenceError("كلفة الأصل غير مكتملة؛ يلزم مراجعة الدليل")
    return row["quantity"] * row["saved_unit_cost"]


def net_line_rows(invoice):
    if not available():
        return None
    origin = SalesReturnOrigin.query.filter_by(tenant_key=tenant_key(), invoice_id=invoice.id).first()
    if origin is None:
        return None
    source = json.loads(origin.snapshot)
    lines = [row for row in source["lines"] if row["physical"]]
    values = discounted_line_values(source["invoice"]["total"], [
        SaleLine(row["id"], row["quantity"], row["value"]) for row in lines])
    returned = db.session.query(SalesReturnLine.order_item_id, func.sum(SalesReturnLine.quantity),
        func.sum(SalesReturnLine.credit_amount), func.sum(SalesReturnLine.cost_amount)).join(
            SalesReturn, SalesReturn.id == SalesReturnLine.document_id).filter(
                SalesReturn.tenant_key == tenant_key(), SalesReturn.invoice_id == invoice.id).group_by(
                    SalesReturnLine.order_item_id).all()
    totals = {row_id: (int(quantity), int(credit), int(cost)) for row_id, quantity, credit, cost in returned}
    result = []
    for row in lines:
        quantity, credit, cost = totals.get(row["id"], (0, 0, 0))
        remaining = row["quantity"]-quantity
        value, net_cost = values[row["id"]]-credit, original_cost(row)-cost
        if remaining < 0 or value < 0 or net_cost < 0:
            raise ReturnEvidenceError("المستندات تجاوزت كمية أو قيمة أو كلفة الأصل")
        result.append({"id": row["id"], "product_id": row["product_id"], "name": row["name"],
            "quantity": remaining, "total": value, "cost": row["saved_unit_cost"], "cost_amount": net_cost,
            "original_quantity": row["quantity"], "returned_quantity": quantity})
    return result
