"""Real partial returns change stock, cash, debt and the original GL once."""
from uuid import uuid4
from pathlib import Path
import json
import pytest
from tests.test_finance_operations import finance, review_opening, balance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment, receipt


def context(f, fn):
    from flask import g, session
    with f["app"].test_request_context("/api/v1/desktop/sales-returns", method="POST"):
        session.update(user_id=f["admin"].id, employee_id=f["admin"].id, role="admin", tenant_slug=f["tenant"])
        g.tenant=f["tenant"]; g.branch=f["branch"]; g.branches=[f["branch"], f["destination"]]
        g.view_all_branches=True; g.independent_branches_enabled=True; g.branch_scope_ready=True
        return fn()


def prepare(f, *, paid=True):
    f["get"] = lambda path: f["request"](path)
    def command(operation, values=None, key=None):
        response = f["request"]("/api/finance/commands", {"operation": operation,
            "idempotency_key": key or uuid4().hex, **(values or {})})
        assert response.status_code == 200, response.get_json()
        return response.get_json()["data"]
    f["call"] = command
    f["get"]("/api/finance/meta")
    review_opening(f)
    assert receipt(f).status_code == 200
    if paid:
        response = f["order_request"]("/orders/payment", {"id": f["order"].id, "payment": "مسدد",
            "payment_allocations": [{"treasury_account_id": f["cash"].id, "amount": 400},
                {"treasury_account_id": f["bank"].id, "amount": 400}]})
        assert response.status_code == 200, response.get_json()


def body(f, quantity=1, **extra):
    from modules.sales_returns.service import preview
    lines = [{"id": f["order"].items[0].id, "quantity": quantity}]
    proposal = context(f, lambda: preview(f["order"].id, lines))
    return {"operation_id": uuid4().hex, "invoice_id": f["order"].id,
        "lines": lines, "preview_token": proposal["preview_token"], "reason": "قطع مستلمة فعلياً",
        "return_branch_id": f["branch"].id, **extra}


def perform(f, values):
    from modules.sales_returns.service import execute
    return context(f, lambda: execute(values))


def test_split_paid_partial_then_remainder_preserves_fifo_and_original_evidence(shipment):
    from models.branch import BranchStock
    from models.inventory_lot import OrderItemCostLayer
    from modules.sales_returns.models import SalesReturn, SalesReturnOrigin
    from utils.accounting_calculations import invoice_cogs_by_ids, calculate_total_returns, calculate_returns_cogs
    from utils.inventory_lots import current_lot_inventory_value
    from modules.finance.control import current
    from utils.order_shipping import invoice_print_amounts
    f = shipment
    prepare(f)
    first = body(f)
    result = perform(f, first)
    assert result["credit"] == result["refund"] == 400 and result["cost"] == 100
    assert f["order"].total == f["order"].paid_amount == 400
    assert f["order"].items[0].quantity == 2 and f["order"].items[0].total == 800
    assert OrderItemCostLayer.query.one().quantity == 2
    assert invoice_cogs_by_ids([f["order"].id])[f["order"].id] == 100
    assert current_lot_inventory_value() == 1100
    assert calculate_total_returns() == 400 and calculate_returns_cogs() == 100
    assert invoice_print_amounts(f["order"], 400)["due"] == 0
    assert BranchStock.query.filter_by(branch_id=f["branch"].id, product_id=f["product"].id).one().quantity == 5
    details = f["order_request"](f'/orders/details/{f["order"].id}').get_json()
    assert details["order"]["return_summary"] == {"original_total": 800, "credit": 400, "net_total": 400, "document_ids": [result["id"]]}
    assert details["items"][0]["qty"] == 2 and details["items"][0]["returned_qty"] == details["items"][0]["remaining_qty"] == 1
    assert not details["order"]["can_edit_invoice"] and not details["order"]["can_hard_delete"]
    html = f["order_request"](f'/orders/print-invoices?ids={f["order"].id}').get_data(as_text=True)
    assert 'data-finora-sales-returns' in html and 'أصل البيع: 800' in html and 'صافي البيع: 400' in html
    artifacts = Path(__file__).parent / "_artifacts" / "sales-returns-20261014"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "invoice-partial.html").write_text(html, encoding="utf-8")
    assert perform(f, first) == result
    assert SalesReturn.query.count() == 1
    perform(f, body(f))
    assert f["order"].total == f["order"].paid_amount == 0 and f["order"].status == "راجع"
    assert f["order"].shipping_status == "راجع" and f["order"].shipping_barcode is None
    assert json.loads(SalesReturnOrigin.query.one().snapshot)["invoice"]["shipping_barcode"] == "SHIP-001"
    assert current_lot_inventory_value() == 1200
    assert calculate_total_returns() == 800 and calculate_returns_cogs() == 200
    assert balance(f) == 20_000_000 and balance(f,"bank") == 0
    html = f["order_request"](f'/orders/print-invoices?ids={f["order"].id}').get_data(as_text=True)
    assert 'صافي البيع: 0' in html and 'المرتجع: 800' in html
    (artifacts / "invoice-complete.html").write_text(html, encoding="utf-8")
    assert context(f, current)["coverage_issues"] == []


def test_unpaid_partial_relieves_only_debt_and_rolls_back_a_failed_receipt(shipment, monkeypatch):
    from modules.sales_returns import service
    from modules.sales_returns.models import SalesReturn
    from utils.inventory_lots import current_lot_inventory_value
    f = shipment
    prepare(f, paid=False)
    request = body(f)
    original = service.restore_line
    def fail(*args):
        original(*args)
        raise RuntimeError("injected after physical receipt")
    monkeypatch.setattr(service, "restore_line", fail)
    with pytest.raises(RuntimeError):
        perform(f, request)
    assert SalesReturn.query.count() == 0 and f["order"].total == 800
    assert current_lot_inventory_value() == 1000 and balance(f) == 20_000_000
    monkeypatch.setattr(service, "restore_line", original)
    result = perform(f, request)
    assert result["debt_relief"] == 400 and result["refund"] == 0
    assert f["order"].total == 400 and f["order"].paid_amount == 0


def test_stale_quote_rejected_without_money_or_stock_change(shipment):
    from modules.finance.common import FinanceError
    from modules.sales_returns.models import SalesReturn
    f = shipment
    prepare(f, paid=False)
    request = body(f)
    request["preview_token"] = "stale"
    with pytest.raises(FinanceError, match="تغير أصل"):
        perform(f, request)
    assert SalesReturn.query.count() == 0 and f["order"].total == 800


def test_legacy_full_return_after_partial_restores_only_remaining_and_replays(shipment):
    from tests.test_desktop_order_returns_shipping import returned
    from modules.sales_returns.models import SalesReturn
    from utils.inventory_lots import current_lot_inventory_value
    from modules.finance.control import current
    f = shipment
    prepare(f)
    perform(f, body(f))
    response = returned(f)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["updated_ids"] == [f["order"].id]
    assert SalesReturn.query.count() == 2
    assert f["order"].total == f["order"].paid_amount == 0
    assert f["order"].status == f["order"].shipping_status == "راجع"
    assert f["order"].shipping_barcode is None
    assert current_lot_inventory_value() == 1200
    assert balance(f) == 20_000_000 and balance(f, "bank") == 0
    assert context(f, current)["coverage_issues"] == []
    assert returned(f).get_json()["updated"] == 0
    assert SalesReturn.query.count() == 2 and current_lot_inventory_value() == 1200


def test_legacy_full_return_failure_rolls_back_remaining_receipt(shipment, monkeypatch):
    from tests.test_desktop_order_returns_shipping import returned
    from routes import orders
    from modules.sales_returns.models import SalesReturn
    from utils.inventory_lots import current_lot_inventory_value
    f = shipment
    prepare(f)
    perform(f, body(f))
    def fail(*args):
        raise RuntimeError("failure in the outer lifecycle")
    monkeypatch.setattr(orders, "_complete_order_return_side_effects", fail)
    response = returned(f)
    assert response.status_code == 400, response.get_json()
    assert response.get_json()["updated"] == 0 and response.get_json()["failed"]
    assert SalesReturn.query.count() == 1 and current_lot_inventory_value() == 1100
    assert f["order"].total == f["order"].paid_amount == 400
    assert balance(f) == 20_000_000 and balance(f, "bank") == 400


def test_direct_sale_return_to_customer_credit_retains_cash_and_has_matching_liability(shipment):
    from modules.finance import ledger
    from modules.finance.control import current
    f = shipment
    prepare(f, paid=False)
    f["order"].shipping_company_id = None
    f["order"].shipping_status = None
    f["order"].status = "تم التوصيل"
    f["db"].session.commit()
    response = f["order_request"]("/orders/payment", {"id": f["order"].id, "payment": "مسدد",
        "payment_allocations": [{"treasury_account_id": f["cash"].id, "amount": 800}]})
    assert response.status_code == 200, response.get_json()
    result = perform(f, body(f, refund_mode="credit"))
    assert result["credit"] == result["customer_credit"] == 400 and result["refund"] == 0
    assert balance(f) == 20_000_800
    assert ledger.account("customer_advance").balance == 400
    assert context(f, current)["coverage_issues"] == []
    perform(f, body(f, refund_mode="credit"))
    assert f["order"].total == f["order"].paid_amount == 0
    assert balance(f) == 20_000_800 and ledger.account("customer_advance").balance == 800
    assert context(f, current)["coverage_issues"] == []


@pytest.mark.parametrize("change", ["total", "line_quantity", "fifo_price", "delete"])
def test_posted_return_freezes_original_financial_and_stock_evidence(shipment, change):
    from modules.sales_returns.models import ReturnEvidenceError
    from models.inventory_lot import OrderItemCostLayer
    from utils.inventory_lots import current_lot_inventory_value
    f = shipment
    prepare(f)
    perform(f, body(f))
    invoice_id = f["order"].id
    if change == "total":
        f["order"].total = 999
    elif change == "line_quantity":
        f["order"].items[0].quantity = 3
    elif change == "fifo_price":
        OrderItemCostLayer.query.one().unit_cost = 999
    else:
        f["db"].session.delete(f["order"])
    with pytest.raises(ReturnEvidenceError):
        f["db"].session.commit()
    f["db"].session.rollback()
    assert f["db"].session.get(type(f["order"]), invoice_id).total == 400
    assert current_lot_inventory_value() == 1100
