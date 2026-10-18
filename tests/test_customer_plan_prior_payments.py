"""Late schedules preserve direct payment history without reposting money."""
from copy import deepcopy

import pytest

from tests.test_finance_operations import finance, review_opening, balance, voucher, adjust_invoice_collection
from tests.test_customer_plan_builder import unpaid_invoice, call, payload
from tests.test_customer_schedules import request_schedule


def payments():
    from models.invoice_payment_ledger import InvoicePaymentLedger
    return [(p.id, p.invoice_id, p.amount_delta, p.recorded_at, p.source_module, p.payment_method,
        p.treasury_account_id) for p in InvoicePaymentLedger.query.order_by(InvoicePaymentLedger.id)]


def money(f):
    from modules.finance import ledger
    from modules.finance.models import FinanceVoucher, FinanceAllocation
    from models.journal_entry import JournalEntry
    from models.receipt import Receipt
    return (shared_cash(), balance(f, "bank"), ledger.account("receivable").balance,
        FinanceVoucher.query.count(), FinanceAllocation.query.count(), JournalEntry.query.count(), Receipt.query.count())


def shared_cash():
    """The fixture has branch and compatibility cash rows; use its canonical total."""
    from flask import g
    from utils.treasury_helpers import get_default_cash_account
    from utils.treasury_calculations import calculate_treasury_balance
    previous = getattr(g, "independent_branches_enabled", None)
    try:
        g.independent_branches_enabled = False
        return calculate_treasury_balance(get_default_cash_account().id)
    finally:
        if previous is None:
            g.pop("independent_branches_enabled", None)
        else:
            g.independent_branches_enabled = previous


def prepared(f, itemized):
    customer, invoice = unpaid_invoice(f)
    if not itemized:
        invoice.paid_amount = 125000
        invoice.payment_status = "جزئي"
        f["db"].session.commit()
    review_opening(f)
    if itemized:
        for paid in (100000, 150000, 125000):
            response = adjust_invoice_collection(f, invoice, paid)
            assert response.status_code == 200, response.get_json()
    return customer, invoice


@pytest.mark.parametrize("itemized", [True, False])
def test_create_paid_invoice_schedule_preserves_sources_and_following_collection_reversal(finance, itemized):
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from modules.finance import ledger
    f = finance
    customer, invoice = prepared(f, itemized)
    before, originals = money(f), payments()
    assert before[0] == 20125000
    source = call(f, customer.id, invoice.id).get_json()["data"]
    assert source["eligible"] and source["historical"]["paid"] == 125000
    assert source["historical"]["payment_count"] == (3 if itemized else 0)
    assert (before, originals) == (money(f), payments())  # GET is read-only.
    command = payload(source)
    created = call(f, customer.id, invoice.id, command)
    assert created.status_code == 200, created.get_json()
    data = created.get_json()["data"]
    plan = f["db"].session.get(CustomerCreditPlan, data["id"])
    assert plan.total_amount == invoice.total == 400000 and plan.paid_amount == invoice.paid_amount == 125000
    assert [r["total"] for r in data["installments"]] == [125000, 91666, 91666, 91668]
    assert [r["paid"] for r in data["installments"]] == [125000, 0, 0, 0]
    assert data["installments"][0]["date"] == invoice.created_at.date().isoformat()
    history = CustomerCreditPayment.query.filter_by(plan_id=plan.id).order_by(CustomerCreditPayment.id).all()
    assert [p.amount for p in history] == ([100000, 50000, -25000] if itemized else [125000])
    assert all(p.installment_id == data["installments"][0]["id"] and "[IP:" in p.note for p in history)
    assert [p.created_at for p in history] == ([p[3] for p in originals] if itemized else [invoice.created_at])
    assert (before, originals) == (money(f), payments())
    assert call(f, customer.id, invoice.id, command).get_json() == created.get_json()
    assert len(history) == CustomerCreditPayment.query.filter_by(plan_id=plan.id).count()
    assert call(f, customer.id, invoice.id, payload(source)).status_code == 409

    # A subsequent ordinary edit and a real bank voucher use the newly linked plan.
    response = adjust_invoice_collection(f, invoice, 175000)
    assert response.status_code == 200, response.get_json()
    assert invoice.paid_amount == plan.paid_amount == 175000
    payment = voucher(f, "customer_payment", 25000, party_id=customer.id, treasury_account_id=f["bank"].id)
    assert invoice.paid_amount == plan.paid_amount == 200000 and balance(f, "bank") == 25000
    source = request_schedule(f, customer.id, plan.id).get_json()["data"]
    repartition = call(f, customer.id, plan.id, payload(source, 2), create=False)
    assert repartition.status_code == 200, repartition.get_json()
    assert repartition.get_json()["data"]["installments"][:2] == source["installments"][:2]
    response = adjust_invoice_collection(f, invoice, 75000)
    assert response.status_code == 200, response.get_json()
    assert plan.paid_amount == invoice.paid_amount == 75000
    f["call"]("voucher.reverse", {"id": payment["id"], "version": payment["version"], "reason": "عكس تحصيل بعد إنشاء الجدول"})
    assert invoice.paid_amount == plan.paid_amount == 50000 and balance(f, "bank") == 0
    assert shared_cash() == before[0] - 75000 == 20050000
    assert ledger.account("receivable").balance == 350000
    current = request_schedule(f, customer.id, plan.id).get_json()["data"]
    assert sum(r["paid"] for r in current["installments"]) == 50000
    assert sum(p.amount for p in CustomerCreditPayment.query.filter_by(plan_id=plan.id)) == 50000
    assert call(f, customer.id, invoice.id, command).get_json() == created.get_json()


@pytest.mark.parametrize("history", ["mismatch", "zero_marker", "missing_source", "finance_ledger", "fully_paid", "negative"])
def test_untraceable_prior_sources_stay_blocked_without_side_effects(finance, history):
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from modules.desktop_api.sync import DesktopSyncReceipt
    from sqlalchemy import text
    f = finance
    customer, invoice = prepared(f, False)
    if history in {"mismatch", "zero_marker"}:
        f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id, amount_delta=1 if history == "mismatch" else 0))
    elif history in {"missing_source", "finance_ledger"}:
        f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id, amount_delta=125000, source_module="finance:123" if history == "finance_ledger" else None))
    else:
        invoice.paid_amount = 400000 if history == "fully_paid" else -1
    f["db"].session.commit()
    if history == "missing_source":
        # Preview must handle the older physical schema without migrating it.
        f["db"].session.execute(text("ALTER TABLE invoice_payment_ledger DROP COLUMN source_module"))
        f["db"].session.commit()
    preview = call(f, customer.id, invoice.id)
    assert preview.status_code == 200, preview.get_json()
    source = preview.get_json()["data"]
    assert not source["eligible"] and source["blocked_reason"]
    assert call(f, customer.id, invoice.id, payload(source)).status_code == 409
    assert CustomerCreditPlan.query.count() == CustomerCreditPayment.query.count() == DesktopSyncReceipt.query.count() == 0


def test_historical_summary_counts_towards_the_limit_and_never_commits_a_partial_plan(finance):
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from modules.desktop_api.sync import DesktopSyncReceipt
    f = finance
    customer, invoice = prepared(f, False)
    source = call(f, customer.id, invoice.id).get_json()["data"]
    assert call(f, customer.id, invoice.id, payload(source, 240)).status_code == 400
    assert CustomerCreditPlan.query.count() == CustomerCreditPayment.query.count() == DesktopSyncReceipt.query.count() == 0


def test_zero_marker_alongside_real_history_is_not_copied_as_an_installment_payment(finance):
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.customer_credit import CustomerCreditPayment
    f = finance
    customer, invoice = prepared(f, True)
    f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id, amount_delta=0))
    f["db"].session.commit()
    source = call(f, customer.id, invoice.id).get_json()["data"]
    assert source["eligible"] and source["historical"]["payment_count"] == 3
    before = payments(), money(f)
    result = call(f, customer.id, invoice.id, payload(source))
    assert result.status_code == 200, result.get_json()
    assert CustomerCreditPayment.query.count() == 3
    assert before == (payments(), money(f))


def test_paid_source_revision_tracks_historical_metadata_and_audit_failure_rolls_back_all_copies(finance, monkeypatch):
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from models.activity_log import ActivityLog
    from modules.desktop_api.sync import DesktopSyncReceipt
    f = finance
    customer, invoice = prepared(f, True)
    source = call(f, customer.id, invoice.id).get_json()["data"]
    entry = InvoicePaymentLedger.query.first()
    entry.payment_method = "bank"
    f["db"].session.commit()
    assert call(f, customer.id, invoice.id, payload(source)).status_code == 409
    fresh = call(f, customer.id, invoice.id).get_json()["data"]
    assert fresh["revision"] != source["revision"]
    before = deepcopy(payments()), money(f)
    command = payload(fresh)
    add = f["db"].session.add
    def fail(row, *args, **kwargs):
        if isinstance(row, ActivityLog):
            raise RuntimeError("simulated historical allocation audit failure")
        return add(row, *args, **kwargs)
    monkeypatch.setattr(f["db"].session, "add", fail)
    assert call(f, customer.id, invoice.id, command).status_code == 500
    assert CustomerCreditPlan.query.count() == CustomerCreditPayment.query.count() == DesktopSyncReceipt.query.count() == 0
    assert before == (payments(), money(f))
    monkeypatch.setattr(f["db"].session, "add", add)
    assert call(f, customer.id, invoice.id, command).status_code == 200
