"""Legacy schema and damaged attribution never produce guessed financial slices."""
import pytest
from sqlalchemy import inspect, delete

from tests.test_finance_operations import finance
from tests.test_customer_plan_builder import call, payload
from tests.test_customer_plan_voucher_history import prepare, financial_snapshot
from tests.test_customer_plan_prior_payments import payments, money
from tests.test_customer_schedules import request_schedule


def test_preview_does_not_create_a_missing_history_table_but_command_upgrades_it(finance):
    from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
    f = finance
    customer, invoice, source = prepare(f)
    CustomerSchedulePaymentLink.__table__.drop(bind=f["db"].session.connection())
    f["db"].session.commit()
    before = financial_snapshot(), payments(), money(f)
    draft = call(f, customer.id, invoice.id).get_json()["data"]
    assert draft["eligible"]
    assert not inspect(f["db"].session.connection()).has_table(CustomerSchedulePaymentLink.__tablename__)
    assert before == (financial_snapshot(), payments(), money(f))
    created = call(f, customer.id, invoice.id, payload(draft))
    assert created.status_code == 200, created.get_json()
    assert CustomerSchedulePaymentLink.query.count() == 1
    assert before == (financial_snapshot(), payments(), money(f))


def test_reversed_mixed_voucher_allows_late_schedule_after_other_invoice_is_returned(finance):
    from tests.test_finance_operations import installment_invoice, review_opening, voucher
    from models.invoice import Invoice
    from models.customer_credit import CustomerCreditPlan
    from utils.order_lifecycle import process_order_return
    f = finance
    customer, returned, previous = installment_invoice(f)
    invoice = Invoice(customer_id=customer.id, customer_name=customer.name, total=300000, paid_amount=0,
        status="تم التوصيل", branch_id=f["branch"].id)
    f["db"].session.add(invoice); f["db"].session.commit()
    review_opening(f)
    source = voucher(f, "customer_payment", 125000, party_id=customer.id, treasury_account_id=f["bank"].id,
        allocations=[{"invoice_id":returned.id,"amount":50000}, {"invoice_id":invoice.id,"amount":75000}])
    f["call"]("voucher.reverse", {"id":source["id"], "version":source["version"], "reason":"عكس السند المشترك قبل الترجيع"})
    returned.barcode = "ARCHIVED-MIXED"; f["db"].session.commit()
    process_order_return(returned, returned.barcode); f["db"].session.commit()
    assert CustomerCreditPlan.query.count() == 0
    before = financial_snapshot(), payments(), money(f)
    draft = call(f, customer.id, invoice.id).get_json()["data"]
    assert draft["eligible"] and draft["historical"]["paid"] == 0
    created = call(f, customer.id, invoice.id, payload(draft))
    assert created.status_code == 200, created.get_json()
    assert before == (financial_snapshot(), payments(), money(f))


def test_future_dates_can_change_with_a_preserved_zero_net_history_row(finance):
    f = finance
    customer, invoice, source = prepare(f, reversed=True)
    draft = call(f, customer.id, invoice.id).get_json()["data"]
    created = call(f, customer.id, invoice.id, payload(draft)).get_json()["data"]
    before = financial_snapshot(), payments(), money(f)
    command = {"idempotency_key": payload(created)["idempotency_key"], "revision":created["revision"],
        "reason":"تأجيل استحقاق دون تغيير تاريخ العكس", "installments":[
            {"id":row["id"], "date":"2027-05-01" if index == 1 else row["date"], "total":row["total"]}
            for index,row in enumerate(created["installments"])]}
    changed = request_schedule(f, customer.id, created["id"], command)
    assert changed.status_code == 200, changed.get_json()
    data = changed.get_json()["data"]
    assert data["installments"][0] == created["installments"][0]
    assert data["installments"][1]["date"] == "2027-05-01"
    assert before == (financial_snapshot(), payments(), money(f))
    assert request_schedule(f, customer.id, created["id"], command).get_json() == changed.get_json()
    # A future unpaid installment cannot become a new zero row, even with a balanced total.
    invalid = {**command, "idempotency_key":payload(data)["idempotency_key"], "revision":data["revision"],
        "installments":[dict(row) for row in command["installments"]]}
    invalid["installments"][2]["total"] += invalid["installments"][1]["total"]
    invalid["installments"][1]["total"] = 0
    assert request_schedule(f, customer.id, created["id"], invalid).status_code == 400
    assert request_schedule(f, customer.id, created["id"]).get_json()["data"]["installments"] == data["installments"]


def test_missing_history_link_blocks_reversal_without_partial_cash_or_installment_changes(finance):
    from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from modules.finance.common import FinanceError
    f = finance
    customer, invoice, source = prepare(f)
    draft = call(f, customer.id, invoice.id).get_json()["data"]
    assert call(f, customer.id, invoice.id, payload(draft)).status_code == 200
    # Simulate corrupted imported data; the normal ORM path forbids deleting a link.
    f["db"].session.execute(delete(CustomerSchedulePaymentLink))
    f["db"].session.commit()
    before = financial_snapshot(), payments(), money(f)
    plan = CustomerCreditPlan.query.one()
    history = [(p.id,p.amount,p.installment_id) for p in CustomerCreditPayment.query]
    with pytest.raises(FinanceError) as error:
        f["call"]("voucher.reverse", {"id":source["id"], "version":source["version"], "reason":"فحص ربط مفقود"})
    assert error.value.status == 409
    assert plan.paid_amount == invoice.paid_amount == 75000
    assert history == [(p.id,p.amount,p.installment_id) for p in CustomerCreditPayment.query]
    assert before == (financial_snapshot(), payments(), money(f))
