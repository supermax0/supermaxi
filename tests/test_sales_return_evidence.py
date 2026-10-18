"""Real tenant evidence is additive, immutable and constrained at the database."""
import hashlib
import json
from datetime import datetime
from uuid import uuid4
import pytest
from sqlalchemy.exc import IntegrityError
from tests.test_finance_operations import finance, balance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment


def origin(f):
    from modules.sales_returns.schema import ensure_schema
    from modules.sales_returns.models import SalesReturnOrigin
    ensure_schema()
    snapshot = json.dumps({"invoice_id": f["order"].id, "quantity": 2, "value": 800, "saved_unit_cost": 100}, sort_keys=True)
    row = SalesReturnOrigin(tenant_key=f["tenant"], invoice_id=f["order"].id,
        created_by=f["admin"].id, snapshot=snapshot,
        snapshot_hash=hashlib.sha256(snapshot.encode("utf-8")).hexdigest())
    f["db"].session.add(row)
    f["db"].session.commit()
    return row


def document(f, evidence, *, key=None, debt=400, excess=0):
    from modules.sales_returns.models import SalesReturn
    return SalesReturn(tenant_key=f["tenant"], origin_id=evidence.id, invoice_id=f["order"].id,
        branch_id=f["branch"].id, operation_key=key or uuid4().hex, fingerprint="a"*64,
        kind="return", reason="دليل اختبار معزول", created_by=f["admin"].id,
        credit_amount=400, cost_amount=100, debt_relief=debt, excess_collection=excess,
        refund_amount=excess, customer_credit=0, evidence="{}")


def test_additive_original_evidence_does_not_post_or_rewrite_sale(shipment):
    from models.journal_entry import JournalEntry
    f = shipment
    before = balance(f), JournalEntry.query.count(), f["order"].total
    row = origin(f)
    assert json.loads(row.snapshot)["value"] == 800
    assert (balance(f), JournalEntry.query.count(), f["order"].total) == before


@pytest.mark.parametrize("action", ["update", "delete", "wrong_hash", "duplicate"])
def test_original_evidence_rejects_rewrite_delete_and_duplicate(shipment, action):
    from modules.sales_returns.models import SalesReturnOrigin, ReturnEvidenceError
    f = shipment
    row = origin(f)
    if action == "update":
        row.snapshot = "{}"
    elif action == "delete":
        f["db"].session.delete(row)
    else:
        f["db"].session.add(SalesReturnOrigin(tenant_key=f["tenant"], invoice_id=f["order"].id,
            created_by=f["admin"].id, snapshot=row.snapshot,
            snapshot_hash="b"*64 if action == "wrong_hash" else row.snapshot_hash))
    expected = IntegrityError if action == "duplicate" else ReturnEvidenceError
    with pytest.raises(expected):
        f["db"].session.commit()
    f["db"].session.rollback()
    assert SalesReturnOrigin.query.count() == 1
    assert json.loads(f["db"].session.get(SalesReturnOrigin, row.id).snapshot)["value"] == 800


def test_posted_document_and_cost_history_cannot_be_modified_or_deleted(shipment):
    from modules.sales_returns.models import SalesReturnLine, SalesReturnCost, ReturnEvidenceError
    f = shipment
    row = document(f, origin(f))
    f["db"].session.add(row)
    f["db"].session.flush()
    line = SalesReturnLine(document_id=row.id, order_item_id=f["order"].items[0].id,
        quantity=1, credit_amount=400, cost_amount=100, snapshot="{}")
    f["db"].session.add(line)
    f["db"].session.flush()
    cost = SalesReturnCost(line_id=line.id, original_layer_id=99, original_lot_id=f["lots"][0].id,
        restored_lot_id=f["lots"][0].id, quantity=1, unit_cost=100, original_received_at=datetime(2026, 1, 1))
    f["db"].session.add(cost)
    f["db"].session.commit()
    for target, field, value in [(row,"reason","تغيير"), (line,"quantity",2), (cost,"unit_cost",250)]:
        setattr(target, field, value)
        with pytest.raises(ReturnEvidenceError):
            f["db"].session.commit()
        f["db"].session.rollback()
    f["db"].session.delete(cost)
    with pytest.raises(ReturnEvidenceError):
        f["db"].session.commit()
    f["db"].session.rollback()
    assert cost.original_layer_id == 99 and cost.unit_cost == 100


def test_database_rejects_duplicate_command_and_unbalanced_credit_parts(shipment):
    f = shipment
    evidence = origin(f)
    key = uuid4().hex
    f["db"].session.add(document(f, evidence, key=key))
    f["db"].session.commit()
    for row in (document(f, evidence, key=key), document(f, evidence, debt=300)):
        f["db"].session.add(row)
        with pytest.raises(IntegrityError):
            f["db"].session.commit()
        f["db"].session.rollback()


@pytest.mark.parametrize("basis,layer_id,valid", [("saved_fifo",None,False),
    ("saved_layer_cost",99,True), ("saved_layer_cost",None,False), ("saved_line_cost",None,True)])
def test_missing_lot_history_is_explicit_in_the_cost_basis(shipment, basis, layer_id, valid):
    from modules.sales_returns.models import SalesReturnLine, SalesReturnCost
    f = shipment
    row = document(f, origin(f))
    f["db"].session.add(row)
    f["db"].session.flush()
    line = SalesReturnLine(document_id=row.id, order_item_id=f["order"].items[0].id,
        quantity=1, credit_amount=400, cost_amount=100, snapshot="{}")
    f["db"].session.add(line)
    f["db"].session.flush()
    cost = SalesReturnCost(line_id=line.id, original_layer_id=layer_id, original_lot_id=None,
        restored_lot_id=f["lots"][0].id, cost_basis=basis, quantity=1, unit_cost=100,
        original_received_at=None)
    f["db"].session.add(cost)
    if valid:
        f["db"].session.commit()
        assert cost.original_lot_id is None and cost.original_received_at is None
    else:
        with pytest.raises(IntegrityError):
            f["db"].session.commit()
        f["db"].session.rollback()


def test_capture_reads_real_fifo_without_repricing_it_from_current_product(shipment):
    from modules.sales_returns.evidence import capture, encoded
    from tests.test_desktop_order_returns_shipping import receipt
    from models.journal_entry import JournalEntry
    f = shipment
    assert receipt(f).status_code == 200
    before = balance(f), JournalEntry.query.count()
    original = capture(f["order"])
    layer = original["lines"][0]["cost_layers"][0]
    assert layer["unit_cost"] == 100 and layer["quantity"] == 2 and layer["basis"] == "saved_fifo"
    f["product"].buy_price = 900
    f["db"].session.commit()
    assert encoded(capture(f["order"])) == encoded(original)
    assert (balance(f), JournalEntry.query.count()) == before


def test_capture_keeps_legacy_cost_and_paid_counter_without_inventing_dates(shipment):
    from modules.sales_returns.evidence import capture
    f = shipment
    result = capture(f["order"])
    assert result["payment_basis"] == "saved_paid_counter" and result["payments"] == []
    line = result["lines"][0]
    assert line["cost_layers"] == [] and line["cost_basis"] == "saved_line_cost"
    assert line["saved_unit_cost"] == 250


def test_read_capture_does_not_flush_unrelated_pending_product_changes(shipment):
    from modules.sales_returns.evidence import capture
    f = shipment
    product_id = f["product"].id
    f["product"].buy_price = 999
    result = capture(f["order"])
    actual = f["db"].session.connection().exec_driver_sql(
        "SELECT buy_price FROM product WHERE id = ?", (product_id,)).scalar()
    assert actual == 250 and result["lines"][0]["saved_unit_cost"] == 250
    f["db"].session.rollback()


def test_capture_refuses_uncommitted_original_invoice_changes(shipment):
    from modules.sales_returns.evidence import capture
    from modules.sales_returns.models import ReturnEvidenceError
    f = shipment
    invoice_id = f["order"].id
    f["order"].total = 799
    with pytest.raises(ReturnEvidenceError, match="تعديل الفاتورة"):
        capture(f["order"])
    actual = f["db"].session.connection().exec_driver_sql(
        "SELECT total FROM invoice WHERE id = ?", (invoice_id,)).scalar()
    assert actual == 800
    f["db"].session.rollback()
