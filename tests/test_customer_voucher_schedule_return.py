"""Returning a fully reversed invoice archives attribution without erasing vouchers."""
import pytest

from tests.test_finance_operations import finance
from tests.test_customer_plan_builder import call, payload
from tests.test_customer_plan_voucher_history import prepare


@pytest.mark.parametrize("action", ["return", "cancel"])
def test_void_invoice_after_reversal_keeps_payment_sources_and_removes_current_debt(finance, action):
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment, CustomerInstallment
    from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
    from utils.order_lifecycle import process_order_return, process_order_cancel
    from utils.customer_credit_service import customer_credit_summary
    from modules.finance import ledger
    f = finance
    customer, invoice, original = prepare(f)
    draft = call(f, customer.id, invoice.id).get_json()["data"]
    assert call(f, customer.id, invoice.id, payload(draft)).status_code == 200
    f["call"]("voucher.reverse", {"id": original["id"], "version": original["version"], "reason":"عكس القبض قبل ترجيع الفاتورة"})
    history = [(p.id,p.amount,p.note,p.created_at,p.employee_id) for p in CustomerCreditPayment.query.order_by(CustomerCreditPayment.id)]
    link = CustomerSchedulePaymentLink.query.one()
    original_link = (link.id,link.invoice_allocation_id,link.payment_id,link.reversal_payment_id)
    if action == "return":
        invoice.barcode = "REVERSE-RETURN"
        f["db"].session.commit()
        process_order_return(invoice, invoice.barcode)
    else:
        invoice.status = "تم الطلب"; f["db"].session.commit()
        process_order_cancel(invoice)
    f["db"].session.commit()
    assert CustomerCreditPlan.query.count() == CustomerInstallment.query.count() == 0
    assert history == [(p.id,p.amount,p.note,p.created_at,p.employee_id) for p in CustomerCreditPayment.query.order_by(CustomerCreditPayment.id)]
    assert all(p.plan_id is None and p.installment_id is None for p in CustomerCreditPayment.query)
    link = CustomerSchedulePaymentLink.query.one()
    assert original_link == (link.id,link.invoice_allocation_id,link.payment_id,link.reversal_payment_id)
    assert customer_credit_summary(customer.id)["remaining"] == 0
    assert ledger.account("receivable").balance == 0


def test_financial_history_cannot_be_detached_from_an_active_invoice_even_after_reversal(finance):
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from modules.finance.common import FinanceError
    f = finance
    customer, invoice, original = prepare(f)
    draft = call(f, customer.id, invoice.id).get_json()["data"]
    assert call(f, customer.id, invoice.id, payload(draft)).status_code == 200
    f["call"]("voucher.reverse", {"id":original["id"], "version":original["version"], "reason":"عكس دون إلغاء الفاتورة"})
    plan = CustomerCreditPlan.query.one()
    with f["db"].session.no_autoflush:
        for payment in list(plan.payments):
            payment.plan_id = None; payment.installment_id = None
        f["db"].session.delete(plan)
    with pytest.raises(FinanceError):
        f["db"].session.commit()
    f["db"].session.rollback()
    assert CustomerCreditPlan.query.count() == 1
    assert all(p.plan_id == plan.id and p.installment_id is not None for p in CustomerCreditPayment.query)
