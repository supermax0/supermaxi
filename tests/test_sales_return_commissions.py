"""Partial returns refresh pending commissions and propose approved corrections."""
from datetime import date
from uuid import uuid4
import json
import pytest
from tests.test_finance_operations import finance, balance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment
from tests.test_sales_return_posting import prepare, body, perform


@pytest.mark.parametrize("approved", [False, True])
def test_return_uses_remaining_fifo_profit_without_rewriting_approved_commission(shipment, approved):
    from modules.hr.models import HRPerson, HRCommissionPolicy, HRCommission, HRCommissionChange
    from modules.sales_returns.line_facts import net_line_rows
    from utils.inventory_lots import current_lot_inventory_value
    f = shipment
    person = HRPerson(employee_id=f["admin"].id, branch_id=f["branch"].id, code=uuid4().hex,
        name="صاحب البيع", joined_on=date(2026, 1, 1))
    f["db"].session.add(person)
    f["db"].session.flush()
    f["db"].session.add(HRCommissionPolicy(person_id=person.id, effective_from=date(2026, 1, 1),
        kind="profit", rules=json.dumps({"basis_points": 2500}), created_by=f["admin"].id))
    f["db"].session.commit()
    prepare(f)
    row = HRCommission.query.filter_by(invoice_id=f["order"].id).one()
    assert row.amount == 150 and row.status == "pending"
    if approved:
        row.status = "approved"
        f["db"].session.commit()
    request = body(f)
    result = perform(f, request)
    lines = net_line_rows(f["order"])
    assert lines[0]["quantity"] == 1 and lines[0]["total"] == 400 and lines[0]["cost_amount"] == 100
    assert result["cost"] == 100 and current_lot_inventory_value() == 1100
    assert balance(f) == 20_000_000 and balance(f, "bank") == 400
    if approved:
        assert row.amount == 150 and row.status == "approved"
        change = HRCommissionChange.query.filter_by(commission_id=row.id).one()
        assert change.amount == -75 and change.target_amount == 75 and change.status == "pending"
        assert perform(f, request) == result
        assert HRCommissionChange.query.filter_by(commission_id=row.id).count() == 1
    else:
        assert row.amount == 75 and row.status == "pending"
        perform(f, body(f))
        assert row.amount == 0 and row.status == "void"
        assert net_line_rows(f["order"])[0]["quantity"] == 0
