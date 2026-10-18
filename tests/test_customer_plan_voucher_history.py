"""Late installment attribution preserves posted sources and their exact reversal."""
from copy import deepcopy
from uuid import uuid4

import pytest

from tests.test_finance_operations import finance, review_opening, voucher, installment_invoice, adjust_invoice_collection
from tests.test_customer_plan_builder import unpaid_invoice, call, payload
from tests.test_customer_plan_prior_payments import money, payments
from tests.test_customer_schedules import request_schedule


def financial_snapshot():
    from modules.finance.models import FinanceVoucher, FinanceAllocation
    from models.receipt import Receipt
    from models.journal_entry import JournalEntry
    from models.account_transaction import AccountTransaction
    return tuple(tuple(tuple(getattr(row, c.name) for c in model.__table__.columns)
        for row in model.query.order_by(model.id))
        for model in (FinanceVoucher, FinanceAllocation, Receipt, JournalEntry, AccountTransaction))


def prepare(f, *, offset=False, reversed=False, direct=0):
    customer, invoice = unpaid_invoice(f)
    review_opening(f)
    if direct:
        result = adjust_invoice_collection(f, invoice, direct)
        assert result.status_code == 200, result.get_json()
    if offset:
        voucher(f, "customer_advance", 100000, party_id=customer.id, treasury_account_id=f["bank"].id)
        source = f["call"]("credit.apply", {"party_type": "customer", "party_id": customer.id,
            "amount": 75000, "branch_id": f["branch"].id})
    else:
        source = voucher(f, "customer_payment", 75000, party_id=customer.id, treasury_account_id=f["bank"].id)
    if reversed:
        f["call"]("voucher.reverse", {"id": source["id"], "version": source["version"], "reason": "تصحيح قبل الجدولة"})
    return customer, invoice, source


@pytest.mark.parametrize("offset,reversed,direct", [(False,False,0), (True,False,50000), (False,True,0), (True,True,50000)])
def test_schedule_preserves_old_vouchers_and_exact_reversal_after_repartition(finance, offset, reversed, direct):
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
    from modules.finance.models import FinanceAllocation
    f = finance
    customer, invoice, original = prepare(f, offset=offset, reversed=reversed, direct=direct)
    before = deepcopy((financial_snapshot(), payments(), money(f)))
    draft = call(f, customer.id, invoice.id).get_json()["data"]
    assert draft["eligible"] and draft["historical"]["paid"] == direct + (0 if reversed else 75000)
    assert draft["historical"]["vouchers"] == [{"id": original["id"], "number": original["number"],
        "date": original["transaction_date"], "amount": 75000, "reversed": reversed}]
    assert before == (financial_snapshot(), payments(), money(f))
    command = payload(draft)
    created = call(f, customer.id, invoice.id, command)
    assert created.status_code == 200, created.get_json()
    data = created.get_json()["data"]
    plan = f["db"].session.get(CustomerCreditPlan, data["id"])
    link = CustomerSchedulePaymentLink.query.one()
    allocation = f["db"].session.get(FinanceAllocation, link.invoice_allocation_id)
    payment = f["db"].session.get(CustomerCreditPayment, link.payment_id)
    assert allocation.voucher_id == original["id"] and allocation.amount == payment.amount == 75000
    assert payment.note.startswith(f"[FV:{original['id']}]") and payment.employee_id == f["admin"].id
    assert bool(link.reversal_payment_id) == reversed
    assert before == (financial_snapshot(), payments(), money(f))
    assert sum(p.amount for p in CustomerCreditPayment.query.filter_by(plan_id=plan.id)) == plan.paid_amount == invoice.paid_amount
    fixed = data["installments"][0]
    assert fixed["id"] in data["protected_ids"] and fixed["paid"] == fixed["total"] == draft["paid"]
    source = request_schedule(f, customer.id, plan.id).get_json()["data"]
    changed = call(f, customer.id, plan.id, payload(source, 2), create=False)
    assert changed.status_code == 200, changed.get_json()
    assert changed.get_json()["data"]["installments"][0] == fixed
    assert before == (financial_snapshot(), payments(), money(f))
    if not reversed:
        key = uuid4().hex
        values = {"id": original["id"], "version": original["version"], "reason": "عكس السند بعد تقسيم المتبقي"}
        result = f["call"]("voucher.reverse", values, key)
        after = financial_snapshot(), payments(), money(f)
        assert f["call"]("voucher.reverse", values, key) == result
        assert after == (financial_snapshot(), payments(), money(f))
        assert plan.paid_amount == invoice.paid_amount == direct
        assert sum(p.amount for p in CustomerCreditPayment.query.filter_by(plan_id=plan.id)) == direct
        assert sum(r.paid_amount for r in plan.installments) == direct
        assert money(f)[1] == (100000 if offset else 0)
        assert money(f)[2] == 400000 - direct
        assert f["db"].session.get(CustomerCreditPayment, payment.id).installment_id == fixed["id"]
    assert call(f, customer.id, invoice.id, command).get_json() == created.get_json()
    assert CustomerSchedulePaymentLink.query.count() == 1


def test_one_voucher_with_existing_and_late_schedules_reverses_both_original_slices(finance):
    from models.invoice import Invoice
    from models.customer_credit import CustomerCreditPlan
    from modules.finance.models import FinanceAllocation
    f = finance
    customer, scheduled_invoice, existing = installment_invoice(f)
    invoice = Invoice(customer_id=customer.id, customer_name=customer.name, total=300000, paid_amount=0,
        status="تم التوصيل", branch_id=f["branch"].id)
    f["db"].session.add(invoice); f["db"].session.commit()
    review_opening(f)
    source = voucher(f, "customer_payment", 125000, party_id=customer.id, treasury_account_id=f["bank"].id,
        allocations=[{"invoice_id": scheduled_invoice.id, "amount": 50000}, {"invoice_id": invoice.id, "amount": 75000}])
    allocations = [(a.id,a.reference_type,a.reference_id,a.amount) for a in FinanceAllocation.query.filter_by(voucher_id=source["id"])]
    draft = call(f, customer.id, invoice.id).get_json()["data"]
    assert draft["eligible"] and draft["historical"]["vouchers"][0]["amount"] == 75000
    created = call(f, customer.id, invoice.id, payload(draft))
    assert created.status_code == 200, created.get_json()
    late = f["db"].session.get(CustomerCreditPlan, created.get_json()["data"]["id"])
    assert allocations == [(a.id,a.reference_type,a.reference_id,a.amount) for a in FinanceAllocation.query.filter_by(voucher_id=source["id"])]
    f["call"]("voucher.reverse", {"id":source["id"], "version":source["version"], "reason":"عكس التحصيل المشترك"})
    assert late.paid_amount == invoice.paid_amount == existing.paid_amount == scheduled_invoice.paid_amount == 0
    assert money(f)[1] == 0 and money(f)[2] == 700000


@pytest.mark.parametrize("fault", ["missing_ledger", "duplicate_ledger", "wrong_account", "outside_branch", "wrong_customer"])
def test_invalid_financial_attribution_blocks_creation_without_changes(finance, fault):
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.branch import Branch
    from modules.finance.models import FinanceAllocation, FinanceVoucher
    from models.customer_credit import CustomerCreditPlan
    from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
    f = finance
    customer, invoice, source = prepare(f)
    row = InvoicePaymentLedger.query.filter_by(source_module=f"finance:{source['id']}").one()
    # Deliberately simulate damaged imported data, outside a finance command.
    if fault == "missing_ledger":
        f["db"].session.delete(row)
    elif fault == "duplicate_ledger":
        f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id, amount_delta=row.amount_delta,
            source_module=row.source_module, recorded_at=row.recorded_at, payment_method=row.payment_method,
            treasury_account_id=row.treasury_account_id))
    elif fault == "wrong_account":
        row.treasury_account_id = f["cash"].id
    else:
        from sqlalchemy import update
        values = {"party_id": customer.id + 999}
        if fault == "outside_branch":
            branch = Branch(code="OUT", name="خارج النطاق", is_active=True)
            f["db"].session.add(branch); f["db"].session.flush()
            values = {"branch_id": branch.id}
        f["db"].session.execute(update(FinanceVoucher).where(FinanceVoucher.id == source["id"]).values(**values))
    f["db"].session.commit()
    before = financial_snapshot(), payments(), money(f)
    draft = call(f, customer.id, invoice.id, view_all=False).get_json()["data"]
    assert not draft["eligible"] and draft["blocked_reason"]
    assert call(f, customer.id, invoice.id, payload(draft), view_all=False).status_code == 409
    assert before == (financial_snapshot(), payments(), money(f))
    assert CustomerCreditPlan.query.count() == CustomerSchedulePaymentLink.query.count() == 0


def test_source_changes_and_failed_link_commit_are_atomic_and_retryable(finance, monkeypatch):
    from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from modules.desktop_api.sync import DesktopSyncReceipt
    f = finance
    customer, invoice, source = prepare(f)
    stale = call(f, customer.id, invoice.id).get_json()["data"]
    f["call"]("voucher.reverse", {"id":source["id"], "version":source["version"], "reason":"عكس قبل الحفظ"})
    assert call(f, customer.id, invoice.id, payload(stale)).status_code == 409
    fresh = call(f, customer.id, invoice.id).get_json()["data"]
    assert fresh["eligible"] and fresh["revision"] != stale["revision"]
    before = financial_snapshot(), payments(), money(f)
    add = f["db"].session.add
    def fail(row, *args, **kwargs):
        if isinstance(row, CustomerSchedulePaymentLink):
            raise RuntimeError("forced late voucher link failure")
        return add(row, *args, **kwargs)
    monkeypatch.setattr(f["db"].session, "add", fail)
    command = payload(fresh)
    assert call(f, customer.id, invoice.id, command).status_code == 500
    assert CustomerCreditPlan.query.count() == CustomerCreditPayment.query.count() == CustomerSchedulePaymentLink.query.count() == DesktopSyncReceipt.query.count() == 0
    assert before == (financial_snapshot(), payments(), money(f))
    monkeypatch.setattr(f["db"].session, "add", add)
    assert call(f, customer.id, invoice.id, command).status_code == 200


def test_history_links_are_immutable_and_finance_paid_cannot_be_edited_as_direct_cash(finance):
    from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
    from modules.finance.common import FinanceError
    f = finance
    customer, invoice, source = prepare(f)
    draft = call(f, customer.id, invoice.id).get_json()["data"]
    assert call(f, customer.id, invoice.id, payload(draft)).status_code == 200
    before = financial_snapshot(), payments(), money(f)
    assert adjust_invoice_collection(f, invoice, 0).status_code == 409
    link = CustomerSchedulePaymentLink.query.one()
    link.payment_id += 999
    with pytest.raises(FinanceError):
        f["db"].session.commit()
    f["db"].session.rollback()
    assert before == (financial_snapshot(), payments(), money(f))
