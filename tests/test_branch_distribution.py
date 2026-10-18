"""Initial distribution session (spec phase 5): selection → preview → approval → resumable execution.

Hard rules under test: nothing runs unapproved; a blocked item blocks approval; stock moves as a real transfer
at FIFO cost with company stock value and books unchanged; a session cannot execute twice."""
from __future__ import annotations

from tests.test_desktop_stock_operations import stock  # noqa: F401
from tests.test_finance_operations import balance, finance  # noqa: F401

BASE = "/api/v1/desktop/branches/distribution"


def _item(f, quantity):
    return {"type": "stock", "product_id": f["product"].id, "quantity": quantity,
            "from_branch_id": f["branch"].id, "to_branch_id": f["destination"].id}


def _data(response):
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_eligibility_blocked_item_and_full_execution(stock):  # noqa: F811
    from models.branch import BranchStock
    from models.journal_entry import JournalEntry
    from utils.accounting_calculations import calculate_inventory_value
    from utils.inventory_lots import current_lot_inventory_value

    f = stock
    assert _data(f["request"](BASE))["eligibility"]["eligible"] is True

    # a request for more than the source holds is created, but blocked from approval and execution
    bad = _data(f["request"](BASE, {"title": "توزيع زائد", "items": [_item(f, 99)]}))["session"]
    detail = _data(f["request"](f"{BASE}/{bad['id']}"))
    assert detail["preview"]["can_execute"] is False and detail["preview"]["summary"]["blocked"] == 1
    assert f["request"](f"{BASE}/{bad['id']}/approve", {}).status_code == 409
    assert f["request"](f"{BASE}/{bad['id']}/execute", {}).status_code == 409  # not approved → never runs

    cash, journals = balance(f), JournalEntry.query.count()
    session = _data(f["request"](BASE, {"title": "توزيع أولي", "items": [_item(f, 3)]}))["session"]
    detail = _data(f["request"](f"{BASE}/{session['id']}"))
    assert detail["preview"]["summary"]["stock_units"] == 3
    assert detail["preview"]["summary"]["stock_value"] == 2 * 100 + 1 * 250  # FIFO: 2 @100 then 1 @250
    assert _data(f["request"](f"{BASE}/{session['id']}/approve", {}))["session"]["status"] == "ready"

    done = _data(f["request"](f"{BASE}/{session['id']}/execute", {}))["session"]
    assert done["status"] == "completed" and done["done"] == 1 and done["failed"] == 0
    assert done["backup_path"]  # a restore copy was taken (or declared unavailable) before the first item ran
    assert BranchStock.query.filter_by(branch_id=f["branch"].id, product_id=f["product"].id).one().quantity == 3
    assert current_lot_inventory_value() == calculate_inventory_value() == 1200  # value only moved
    assert balance(f) == cash and JournalEntry.query.count() == journals  # a distribution is not a sale

    # executing again is refused and moves nothing more
    assert f["request"](f"{BASE}/{session['id']}/execute", {}).status_code == 409
    assert BranchStock.query.filter_by(branch_id=f["branch"].id, product_id=f["product"].id).one().quantity == 3


def test_editing_after_approval_returns_to_draft_and_cancel_is_final(stock):  # noqa: F811
    f = stock
    session = _data(f["request"](BASE, {"title": "جلسة للإلغاء", "items": [_item(f, 1)]}))["session"]
    _data(f["request"](f"{BASE}/{session['id']}/approve", {}))
    edited = _data(f["request"](f"{BASE}/{session['id']}/items", {"items": [_item(f, 2)]}))["session"]
    assert edited["status"] == "draft"  # any change needs a fresh approval
    assert _data(f["request"](f"{BASE}/{session['id']}/cancel", {}))["session"]["status"] == "cancelled"
    assert f["request"](f"{BASE}/{session['id']}/approve", {}).status_code == 409
