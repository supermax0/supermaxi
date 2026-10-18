"""Legacy counters remain undated evidence; only actual refunds are new flows."""
import json
from datetime import datetime
import pytest
from tests.test_finance_operations import finance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment, returned
from tests.test_sales_return_posting import prepare, body, perform, context


def legacy_sale(f, *, dated=False, paid=800):
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from modules.sales_returns.collections import read_default_cash_id
    prepare(f, paid=False)
    f["order"].shipping_company_id = None
    f["order"].shipping_status = None
    f["order"].status = "تم التوصيل"
    f["order"].payment_status = "مسدد" if paid == 800 else "جزئي"
    f["order"].paid_amount = paid
    if dated:
        f["db"].session.add(InvoicePaymentLedger(invoice_id=f["order"].id, branch_id=f["branch"].id,
            amount_delta=paid, treasury_account_id=None, payment_method=None, source_module="legacy_import",
            recorded_at=datetime(2026, 1, 2)))
    f["db"].session.commit()
    return read_default_cash_id(f["branch"].id)


def test_undated_counter_requires_review_and_full_after_partial_does_not_date_a_receipt(shipment):
    from modules.finance.common import FinanceError
    from modules.finance.control import current
    from modules.sales_returns.models import SalesReturn, SalesReturnOrigin
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from utils.treasury_calculations import calculate_treasury_balance, get_treasury_movements
    f = shipment
    cash_id = legacy_sale(f)
    assert calculate_treasury_balance(cash_id) == 800
    request = body(f)
    with pytest.raises(FinanceError, match="أكد مراجعة"):
        perform(f, request)
    assert SalesReturn.query.count() == 0 and calculate_treasury_balance(cash_id) == 800
    request["acknowledge_undated_collection"] = True
    result = perform(f, request)
    assert result["refund"] == 400 and calculate_treasury_balance(cash_id) == 400
    evidence = json.loads(SalesReturnOrigin.query.one().snapshot)["undated_collection"]
    assert evidence == {"amount": 800, "treasury_account_id": cash_id, "date": None,
        "basis": "saved_paid_counter_default_cash"}
    assert [row.amount_delta for row in InvoicePaymentLedger.query.order_by(InvoicePaymentLedger.id)] == [-400]
    details = f["order_request"](f'/orders/details/{f["order"].id}').get_json()
    assert details["order"]["return_summary"]["undated_collection_amount"] == 800
    cash_page = f["order_request"](f'/cash/?treasury_account_id={cash_id}')
    assert cash_page.status_code == 200, cash_page.get_data(as_text=True)[:120]
    assert "دليل تحصيل قديم غير مؤرخ" in cash_page.get_data(as_text=True)
    flows = get_treasury_movements(cash_id)
    assert not any(row["type"] == "cash_in" and row.get("invoice_id") == f["order"].id for row in flows)
    assert context(f, current)["coverage_issues"] == []
    assert perform(f, request) == result and SalesReturn.query.count() == 1
    response = returned(f)
    assert response.status_code == 200, response.get_json()
    assert f["order"].status == "راجع" and calculate_treasury_balance(cash_id) == 0
    assert [row.amount_delta for row in InvoicePaymentLedger.query.order_by(InvoicePaymentLedger.id)] == [-400, -400]
    assert context(f, current)["coverage_issues"] == []


def test_dated_legacy_null_account_refunds_default_cash_without_a_baseline(shipment):
    from modules.sales_returns.models import SalesReturnOrigin
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from utils.treasury_calculations import calculate_treasury_balance
    f = shipment
    cash_id = legacy_sale(f, dated=True)
    result = perform(f, body(f))
    assert result["refund"] == 400 and calculate_treasury_balance(cash_id) == 400
    assert json.loads(SalesReturnOrigin.query.one().snapshot)["undated_collection"] is None
    rows = InvoicePaymentLedger.query.order_by(InvoicePaymentLedger.id).all()
    assert rows[0].recorded_at == datetime(2026, 1, 2) and rows[0].treasury_account_id is None
    assert rows[1].treasury_account_id == cash_id and rows[1].amount_delta == -400


def test_undated_collection_credit_retains_money_and_posts_customer_liability(shipment):
    from modules.finance import ledger
    from modules.finance.control import current
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from utils.treasury_calculations import calculate_treasury_balance
    f = shipment
    cash_id = legacy_sale(f)
    result = perform(f, body(f, refund_mode="credit", acknowledge_undated_collection=True))
    assert result["customer_credit"] == 400 and result["refund"] == 0
    assert calculate_treasury_balance(cash_id) == 800
    assert ledger.account("customer_advance").balance == 400
    row = InvoicePaymentLedger.query.one()
    assert row.amount_delta == -400 and row.payment_method == "finance_offset"
    assert context(f, current)["coverage_issues"] == []


def test_new_finance_receipt_after_debt_return_does_not_date_old_collection(shipment):
    from modules.finance.control import current
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from modules.sales_returns.models import SalesReturnFunding
    from utils.treasury_calculations import calculate_treasury_balance
    f = shipment
    cash_id = legacy_sale(f, paid=300)
    first = perform(f, body(f))
    assert first["debt_relief"] == 400 and first["refund"] == 0
    receipt = f["call"]("voucher.create", {"category": "customer_payment", "amount": 100,
        "party_id": f["order"].customer_id, "treasury_account_id": f["bank"].id,
        "branch_id": f["branch"].id, "intent": "post",
        "allocations": [{"invoice_id": f["order"].id, "amount": 100}]})
    rows = InvoicePaymentLedger.query.all()
    assert len(rows) == 1 and rows[0].amount_delta == 100 and rows[0].source_module == f'finance:{receipt["id"]}'
    final = perform(f, body(f, acknowledge_undated_collection=True))
    assert final["refund"] == 400 and calculate_treasury_balance(cash_id) == 0
    assert len(InvoicePaymentLedger.query.all()) == 3
    assert sorted(row.amount for row in SalesReturnFunding.query) == [100, 300]
    assert context(f, current)["coverage_issues"] == []


def test_legacy_unassigned_invoice_keeps_company_default_cash_provenance(shipment):
    from modules.sales_returns.models import SalesReturnOrigin
    from utils.treasury_calculations import calculate_treasury_balance
    f = shipment
    cash_id = legacy_sale(f)
    f["order"].branch_id = None
    f["db"].session.commit()
    result = perform(f, body(f, acknowledge_undated_collection=True))
    assert result["refund"] == 400 and calculate_treasury_balance(cash_id) == 400
    original = json.loads(SalesReturnOrigin.query.one().snapshot)
    assert original["invoice"]["branch_id"] is None
    assert original["undated_collection"]["treasury_account_id"] == cash_id


def test_cash_shift_counts_only_actual_refund_when_old_counter_becomes_saved_evidence(shipment):
    from tests.test_finance_cash_shifts import detail, closing
    from models.journal_entry import JournalEntry
    from utils.treasury_calculations import calculate_treasury_balance
    f = shipment
    cash_id = legacy_sale(f)
    shift = f["call"]("cash_shift.open", {"treasury_account_id": cash_id,
        "opening_actual": 800, "name": "وردية رصيد قديم"})
    perform(f, body(f, acknowledge_undated_collection=True))
    preview = detail(f, shift)["preview"]
    assert preview["net_movement"] == -400 and preview["expected"] == 400
    count = JournalEntry.query.count()
    closed = closing(f, shift, 400)
    assert closed["variance"] == 0 and closed["expected"] == closed["actual"] == 400
    assert JournalEntry.query.count() == count and calculate_treasury_balance(cash_id) == 400


def test_changed_default_cash_cannot_redirect_a_previously_used_null_account_source(shipment):
    from modules.finance.common import FinanceError
    from modules.sales_returns.models import SalesReturn, SalesReturnFunding
    from models.treasury_account import TreasuryAccount
    from models.journal_entry import JournalEntry
    f = shipment
    original_id = legacy_sale(f, dated=True)
    perform(f, body(f))
    assert SalesReturnFunding.query.one().treasury_account_id == original_id
    f["db"].session.get(TreasuryAccount, original_id).is_default = False
    f["cash"].is_default = True
    f["db"].session.commit()
    before = JournalEntry.query.count()
    with pytest.raises(FinanceError) as denied:
        perform(f, body(f))
    assert denied.value.code == "source_review"
    assert SalesReturn.query.count() == SalesReturnFunding.query.count() == 1
    assert f["order"].total == f["order"].paid_amount == 400 and JournalEntry.query.count() == before


def test_capture_does_not_invent_a_default_cash_account_when_none_is_configured(shipment):
    from modules.sales_returns.evidence import capture
    from models.treasury_account import TreasuryAccount
    f = shipment
    legacy_sale(f)
    for row in TreasuryAccount.query.filter_by(account_type="cash"):
        row.is_default = False
    f["db"].session.commit()
    count = TreasuryAccount.query.count()
    original = capture(f["order"])
    assert original["undated_collection"]["treasury_account_id"] is None
    assert TreasuryAccount.query.count() == count and not f["db"].session.dirty
