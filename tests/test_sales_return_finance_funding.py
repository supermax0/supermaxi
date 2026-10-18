"""Linked partial refunds block only the consumed receipt's reversal."""
import pytest
from tests.test_finance_operations import finance, balance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment
from tests.test_sales_return_posting import prepare, body, perform, context


def setup(f):
    prepare(f, paid=False)
    f["order"].shipping_company_id = None
    f["order"].shipping_status = None
    f["order"].status = "تم التوصيل"
    f["db"].session.commit()


def collect(f, amount, account):
    return f["call"]("voucher.create", {"category": "customer_payment", "amount": amount,
        "party_id": f["order"].customer_id, "treasury_account_id": account.id,
        "branch_id": f["branch"].id, "intent": "post",
        "allocations": [{"invoice_id": f["order"].id, "amount": amount}]})


@pytest.mark.parametrize("mode", ["cash", "credit"])
def test_finance_receipt_partial_return_links_every_dinar_and_blocks_double_refund(shipment, mode):
    from modules.finance.common import FinanceError
    from modules.finance.control import current
    from modules.finance.models import FinanceAllocation
    from modules.finance import ledger
    from modules.sales_returns.models import SalesReturnFunding, ReturnEvidenceError
    f = shipment
    setup(f)
    receipt = collect(f, 800, f["cash"])
    assert balance(f) == 20_000_800
    first = body(f, refund_mode=mode)
    result = perform(f, first)
    funding = SalesReturnFunding.query.one()
    assert funding.source_voucher_id == receipt["id"] and funding.amount == 400
    assert funding.source_ledger_id is not None and funding.disposition == ("refund" if mode == "cash" else "credit")
    assert FinanceAllocation.query.filter_by(voucher_id=receipt["id"], reference_type="invoice").one().amount == 800
    with pytest.raises(FinanceError, match="مرتجع أو رصيد") as denied:
        f["call"]("voucher.reverse", {"id": receipt["id"], "version": receipt["version"], "reason": "محاولة عكس قبض مردود جزئياً"})
    assert denied.value.code == "dependency"
    assert perform(f, first) == result and SalesReturnFunding.query.count() == 1
    funding.amount = 401
    with pytest.raises(ReturnEvidenceError):
        f["db"].session.commit()
    f["db"].session.rollback()
    perform(f, body(f, refund_mode=mode))
    assert sum(row.amount for row in SalesReturnFunding.query) == 800
    assert balance(f) == (20_000_000 if mode == "cash" else 20_000_800)
    assert ledger.account("customer_advance").balance == (0 if mode == "cash" else 800)
    assert context(f, current)["coverage_issues"] == []


def test_unconsumed_receipt_can_reverse_after_another_receipt_funded_return(shipment):
    from modules.finance.common import FinanceError
    from modules.finance.control import current
    from modules.sales_returns.models import SalesReturnFunding
    f = shipment
    setup(f)
    cash = collect(f, 400, f["cash"])
    bank = collect(f, 400, f["bank"])
    perform(f, body(f))
    assert SalesReturnFunding.query.one().source_voucher_id == cash["id"]
    with pytest.raises(FinanceError, match="مرتجع أو رصيد"):
        f["call"]("voucher.reverse", {"id": cash["id"], "version": cash["version"], "reason": "محاولة تكرار الرد"})
    reversed_bank = f["call"]("voucher.reverse", {"id": bank["id"], "version": bank["version"], "reason": "عكس القبض الآخر غير المستخدم"})
    assert reversed_bank["status"] == "reversed" and f["order"].paid_amount == 0
    result = perform(f, body(f))
    assert result["debt_relief"] == 400 and result["refund"] == 0
    assert balance(f) == 20_000_000 and balance(f, "bank") == 0
    assert context(f, current)["coverage_issues"] == []


@pytest.mark.parametrize("remove", [False, True])
def test_ordinary_payment_used_by_return_cannot_be_edited_or_deleted(shipment, remove):
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from modules.sales_returns.models import SalesReturnFunding, ReturnEvidenceError
    f = shipment
    prepare(f)
    perform(f, body(f))
    source_id = SalesReturnFunding.query.one().source_ledger_id
    source = f["db"].session.get(InvoicePaymentLedger, source_id)
    if remove:
        f["db"].session.delete(source)
    else:
        source.amount_delta += 1
    with pytest.raises(ReturnEvidenceError):
        f["db"].session.commit()
    f["db"].session.rollback()
    assert f["db"].session.get(InvoicePaymentLedger, source_id).amount_delta == 400
    assert f["order"].total == f["order"].paid_amount == 400


def test_previously_reversed_receipt_is_not_used_to_fund_a_later_return(shipment):
    from modules.sales_returns.models import SalesReturnFunding
    from modules.finance.control import current
    f = shipment
    setup(f)
    old = collect(f, 400, f["cash"])
    f["call"]("voucher.reverse", {"id": old["id"], "version": old["version"], "reason": "قبض سابق معكوس"})
    active = collect(f, 800, f["cash"])
    perform(f, body(f))
    assert SalesReturnFunding.query.one().source_voucher_id == active["id"]
    assert balance(f) == 20_000_400 and context(f, current)["coverage_issues"] == []


def test_paid_invoice_delete_switch_cannot_remove_return_funding_history(shipment):
    from utils.invoice_mutation_policy import set_paid_invoice_mutations_enabled
    from modules.sales_returns.models import SalesReturn, SalesReturnFunding
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.journal_entry import JournalEntry
    from utils.inventory_lots import current_lot_inventory_value
    f = shipment
    prepare(f)
    perform(f, body(f))
    set_paid_invoice_mutations_enabled(True)
    before = JournalEntry.query.count(), InvoicePaymentLedger.query.count()
    response = f["order_request"](f'/orders/delete/{f["order"].id}', {})
    assert response.status_code == 400 and "مرتجع معتمد" in response.get_json()["error"]
    assert before == (JournalEntry.query.count(), InvoicePaymentLedger.query.count())
    assert SalesReturn.query.count() == SalesReturnFunding.query.count() == 1
    assert f["order"].total == 400 and current_lot_inventory_value() == 1100


def test_bank_receipt_funding_keeps_bank_method_and_refunds_bank_only(shipment):
    from modules.sales_returns.models import SalesReturnFunding
    from modules.finance.control import current
    f = shipment
    setup(f)
    receipt = collect(f, 800, f["bank"])
    perform(f, body(f))
    source = SalesReturnFunding.query.one()
    assert source.source_voucher_id == receipt["id"] and source.treasury_account_id == f["bank"].id
    assert source.payment_method == "bank" and source.amount == 400
    assert balance(f, "bank") == 400 and balance(f) == 20_000_000
    assert context(f, current)["coverage_issues"] == []
