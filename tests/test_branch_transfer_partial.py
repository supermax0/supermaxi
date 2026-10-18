"""Branch transfers beyond send / full receive: approval policy, partial receipt, residual resolution, rejection.

Invariants (multi-branch spec, phase 8): a transfer is not a sale — no cash, no journal, no profit; goods that
left the sender and are not received stay owned by the sender (in transit) and keep their exact FIFO cost; a
loss is posted only through the stock write-off service; every step is replay-safe and guarded server-side."""
from uuid import uuid4

from tests.test_desktop_stock_operations import draft, source, stock  # noqa: F401
from tests.test_finance_operations import balance, finance  # noqa: F401

BASE = "/api/v1/desktop/stock-operations/branch/transfers"


def act(f, document, name, *, lines=None, reason="تنفيذ", key=None):
    detail = f["read"](f"{BASE}/{document}")
    body = {"operation_id": key or str(uuid4()), "revision": detail["revision"], "reason": reason}
    if lines is not None:
        body["lines"] = lines
    return f["request"](f"{BASE}/{document}/{name}", body), body


def line_of(f, document):
    return f["read"](f"{BASE}/{document}")["lines"][0]


def values():
    from utils.accounting_calculations import calculate_inventory_value
    from utils.inventory_lots import current_lot_inventory_value

    return current_lot_inventory_value(), calculate_inventory_value()


def destination_qty(f, document):
    from models.branch import BranchStock, StockTransfer

    row = StockTransfer.query.get(document)
    product = row.lines[0].destination_product_id
    if not product:
        return 0
    stock_row = BranchStock.query.filter_by(branch_id=f["destination"].id, product_id=product).first()
    return int(stock_row.quantity) if stock_row else 0


def test_partial_receipt_then_return_keeps_value_fifo_and_books(stock):  # noqa: F811
    from models.journal_entry import JournalEntry

    f = stock
    cash, journals = balance(f), JournalEntry.query.count()
    document, _ = draft(f)  # 3 units: 2 @100 + 1 @250 (FIFO)
    assert act(f, document, "send")[0].status_code == 200
    line = line_of(f, document)
    assert line["sent"] == 3 and line["residual"] == 3

    response, _ = act(f, document, "receive_partial", lines=[{"line_id": line["id"], "received": 2}])
    assert response.status_code == 200, response.get_json()
    detail = f["read"](f"{BASE}/{document}")
    assert detail["status"] == "partially_received"
    assert detail["lines"][0]["received"] == 2 and detail["lines"][0]["residual"] == 1
    assert destination_qty(f, document) == 2
    assert detail["can_resolve"] is True and detail["can_receive"] is False
    assert values() == (1200, 1200)  # the unsettled 1 @250 is still the sender's, at its exact cost

    response, _ = act(f, document, "resolve", lines=[{"line_id": line["id"], "action": "return"}])
    assert response.status_code == 200, response.get_json()
    assert f["read"](f"{BASE}/{document}")["status"] == "received"
    assert source(f)["quantity"] == 4 and destination_qty(f, document) == 2
    assert [lot.remaining_quantity for lot in f["lots"]] == [0, 4]  # the returned unit went back to ITS lot
    assert values() == (1200, 1200)
    assert balance(f) == cash and JournalEntry.query.count() == journals  # a transfer is not a sale


def test_late_arrival_completes_the_transfer_like_a_full_receipt(stock):  # noqa: F811
    from models.inventory_lot import InventoryLot

    f = stock
    document, _ = draft(f)
    act(f, document, "send")
    line = line_of(f, document)
    assert act(f, document, "receive_partial", lines=[{"line_id": line["id"], "received": 1}])[0].status_code == 200
    assert destination_qty(f, document) == 1
    response, _ = act(f, document, "resolve", lines=[{"line_id": line["id"], "action": "late"}])
    assert response.status_code == 200, response.get_json()
    assert destination_qty(f, document) == 3
    # the layers stay as they left the sender (split across the two receipts); value and units are the same
    lots = sorted((lot.remaining_quantity, lot.unit_cost)
                  for lot in InventoryLot.query.filter_by(branch_id=f["destination"].id))
    assert lots == [(1, 100), (1, 100), (1, 250)]
    assert sum(q * c for q, c in lots) == 450
    assert values() == (1200, 1200)
    assert f["read"](f"{BASE}/{document}")["lines"][0]["received"] == 3


def test_loss_in_transit_is_written_off_through_the_writeoff_service_at_fifo_cost(stock):  # noqa: F811
    from models.journal_entry import JournalEntry
    from models.stock_operations import InventoryWriteOff

    f = stock
    journals = JournalEntry.query.count()
    document, _ = draft(f)
    act(f, document, "send")
    line = line_of(f, document)
    act(f, document, "receive_partial", lines=[{"line_id": line["id"], "received": 2}])
    response, _ = act(f, document, "resolve", lines=[{"line_id": line["id"], "action": "loss"}],
                      reason="الصندوق وصل ناقصاً")
    assert response.status_code == 200, response.get_json()
    assert f["read"](f"{BASE}/{document}")["status"] == "received"
    written = InventoryWriteOff.query.order_by(InventoryWriteOff.id.desc()).first()
    # like every write-off, the unit is valued at the OLDEST layer of the receiving branch (FIFO: units are
    # fungible) — here the 100 layer — and the lost value leaves the books exactly once
    assert written is not None and written.quantity == 1 and written.cost == 100
    assert "فاقد" in written.reason and "الصندوق وصل ناقصاً" in written.reason
    assert JournalEntry.query.count() == journals + 1  # exactly the inventory-loss entry
    assert values() == (1100, 1100)  # 1200 − 100, nothing else moved


def test_receiver_rejection_returns_everything_to_the_sender(stock):  # noqa: F811
    f = stock
    document, _ = draft(f)
    act(f, document, "send")
    assert source(f)["quantity"] == 3
    response, _ = act(f, document, "reject", reason="البضاعة غير مطابقة")
    assert response.status_code == 200, response.get_json()
    assert f["read"](f"{BASE}/{document}")["status"] == "rejected"
    assert source(f)["quantity"] == 6 and [lot.remaining_quantity for lot in f["lots"]] == [2, 4]
    assert destination_qty(f, document) == 0 and values() == (1200, 1200)
    # a rejected transfer is final
    assert act(f, document, "receive")[0].status_code == 409
    assert act(f, document, "reject")[0].status_code == 409


def test_approval_policy_is_enforced_by_the_server(stock):  # noqa: F811
    from extensions import db
    from modules.stock_operations import transfer_partial

    f = stock
    document, _ = draft(f)
    transfer_partial.set_approval_required(True)
    db.session.commit()
    assert f["read"](f"{BASE}/{document}")["approval_required"] is True
    blocked, _ = act(f, document, "send")
    assert blocked.status_code == 409 and "اعتماد" in blocked.get_json()["error"]
    assert source(f)["quantity"] == 6
    approved, _ = act(f, document, "approve")
    assert approved.status_code == 200, approved.get_json()
    assert f["read"](f"{BASE}/{document}")["status"] == "approved"
    assert act(f, document, "send")[0].status_code == 200 and source(f)["quantity"] == 3
    # policy off: the original draft → send flow is unchanged
    transfer_partial.set_approval_required(False)
    db.session.commit()
    other, _ = draft(f)
    assert act(f, other, "send")[0].status_code == 200


def test_partial_receipt_validation_and_single_use(stock):  # noqa: F811
    f = stock
    document, _ = draft(f)
    act(f, document, "send")
    line = line_of(f, document)
    over, _ = act(f, document, "receive_partial", lines=[{"line_id": line["id"], "received": 4}])
    assert over.status_code == 400
    zero, _ = act(f, document, "receive_partial", lines=[{"line_id": line["id"], "received": 0}])
    assert zero.status_code == 400
    nothing, _ = act(f, document, "resolve", lines=[{"line_id": line["id"], "action": "return"}])
    assert nothing.status_code == 409  # not partially received yet
    assert destination_qty(f, document) == 0 and source(f)["quantity"] == 3  # refused steps changed nothing

    ok, body = act(f, document, "receive_partial", lines=[{"line_id": line["id"], "received": 1}])
    assert ok.status_code == 200
    replay = f["request"](f"{BASE}/{document}/receive_partial", body)  # same operation id: no double stock
    assert replay.status_code == 200 and destination_qty(f, document) == 1
    again, _ = act(f, document, "receive_partial", lines=[{"line_id": line["id"], "received": 1}])
    assert again.status_code == 409
    undecided, _ = act(f, document, "resolve", lines=[{"line_id": 99999, "action": "late"}])
    assert undecided.status_code == 400
    bad, _ = act(f, document, "resolve", lines=[{"line_id": line["id"], "action": "teleport"}])
    assert bad.status_code == 400
