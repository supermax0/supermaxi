"""Quotes preserve original discounts/FIFO and cannot silently refund offsets."""
import copy
import pytest
from tests.test_finance_operations import finance, balance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment, receipt


def test_quote_real_fifo_sale_without_any_money_or_stock_mutation(shipment):
    from modules.sales_returns.preview import quote
    from models.journal_entry import JournalEntry
    from utils.inventory_lots import current_lot_inventory_value
    f = shipment
    assert receipt(f).status_code == 200
    before = balance(f), current_lot_inventory_value(), JournalEntry.query.count()
    result = quote(f["order"], [{"id": f["order"].items[0].id, "quantity": 1}])
    assert result["credit"] == result["debt_relief"] == 400
    assert result["cost"] == 100 and result["excess_collection"] == 0
    assert (balance(f), current_lot_inventory_value(), JournalEntry.query.count()) == before


def test_next_partial_uses_saved_original_and_keeps_old_collection_separate(shipment):
    from modules.sales_returns.evidence import capture
    from modules.sales_returns.preview import quote
    f = shipment
    assert receipt(f).status_code == 200
    source = capture(f["order"])
    line_id = f["order"].items[0].id
    f["order"].total = 400
    f["order"].paid_amount = 300
    f["order"].payment_status = "جزئي"
    f["db"].session.commit()
    result = quote(f["order"], [{"id": line_id, "quantity": 1}], original=source,
        returned_quantities={line_id: 1})
    assert result["credit"] == 400 and result["debt_relief"] == 100 and result["excess_collection"] == 300
    assert result["sale_remaining"] == result["collection_remaining"] == 0


@pytest.mark.parametrize("problem", ["over_quantity", "duplicate", "foreign_source", "currency", "trade_in", "missing_cost"])
def test_quote_rejects_unsupported_or_invalid_evidence(shipment, problem):
    from modules.sales_returns.evidence import capture
    from modules.sales_returns.preview import quote, ReturnPreviewError
    f = shipment
    source = copy.deepcopy(capture(f["order"]))
    line_id = source["lines"][0]["id"]
    selection = [{"id": line_id, "quantity": 1}]
    if problem == "over_quantity": selection[0]["quantity"] = 3
    elif problem == "duplicate": selection.append(dict(selection[0]))
    elif problem == "foreign_source": source["invoice"]["id"] += 1
    elif problem == "currency": source["invoice"]["currency"] = "USD"
    elif problem == "trade_in": source["lines"][0]["sale_mode"] = "exchange"
    elif problem == "missing_cost": source["lines"][0]["saved_unit_cost"] = None
    with pytest.raises(ReturnPreviewError):
        quote(f["order"], selection, original=source)


def test_quote_saved_original_does_not_flush_pending_unrelated_product_changes(shipment):
    from modules.sales_returns.evidence import capture
    from modules.sales_returns.preview import quote
    f = shipment
    source = capture(f["order"])
    product_id, line_id = f["product"].id, f["order"].items[0].id
    f["db"].session.expire(f["order"])
    f["product"].buy_price = 999
    quote(f["order"], [{"id": line_id, "quantity": 1}], original=source)
    actual = f["db"].session.connection().exec_driver_sql(
        "SELECT buy_price FROM product WHERE id = ?", (product_id,)).scalar()
    assert actual == 250
    f["db"].session.rollback()
