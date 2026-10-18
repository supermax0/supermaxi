"""A newly created schedule participates in real collection and exact reversal."""
from tests.test_finance_operations import finance, review_opening, voucher, balance
from tests.test_customer_plan_builder import unpaid_invoice, call, payload
from tests.test_customer_schedules import request_schedule


def test_new_schedule_collect_repartition_and_reverse_use_one_cash_and_debt_source(finance):
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from modules.finance import ledger
    f=finance
    customer,invoice=unpaid_invoice(f)
    review_opening(f)
    before=(balance(f),balance(f,"bank"),ledger.account("receivable").balance)
    source=call(f,customer.id,invoice.id).get_json()["data"]
    created=call(f,customer.id,invoice.id,payload(source))
    assert created.status_code==200,created.get_json()
    plan_id=created.get_json()["data"]["id"]
    assert before==(balance(f),balance(f,"bank"),ledger.account("receivable").balance)
    payment=voucher(f,"customer_payment",150000,party_id=customer.id,treasury_account_id=f["bank"].id)
    plan=CustomerCreditPlan.query.get(plan_id)
    assert plan.paid_amount==invoice.paid_amount==150000
    assert balance(f,"bank")==150000 and ledger.account("receivable").balance==250000
    links=[(p.id,p.installment_id,p.amount) for p in CustomerCreditPayment.query.filter_by(plan_id=plan_id)]
    source=request_schedule(f,customer.id,plan_id).get_json()["data"]
    changed=call(f,customer.id,plan_id,payload(source),create=False)
    assert changed.status_code==200,changed.get_json()
    assert len(changed.get_json()["data"]["installments"])==5
    assert links==[(p.id,p.installment_id,p.amount) for p in CustomerCreditPayment.query.filter_by(plan_id=plan_id)]
    f["call"]("voucher.reverse",{"id":payment["id"],"version":payment["version"],"reason":"عكس تحصيل جدول منشأ حديثاً"})
    assert invoice.paid_amount==plan.paid_amount==0 and balance(f,"bank")==0
    assert ledger.account("receivable").balance==400000


def test_reused_deleted_plan_id_does_not_show_the_previous_plans_audit(finance):
    from datetime import datetime, timedelta
    from models.activity_log import ActivityLog
    from tests.test_finance_operations import installment_invoice
    f=finance
    customer,invoice,old=installment_invoice(f)
    old_id=old.id
    audit=ActivityLog(employee_id=f["admin"].id,employee_name=f["admin"].name,branch_id=f["branch"].id,
        action="update",category="customers",entity_type="customer_credit_schedule",entity_id=str(old_id),
        summary="old plan",created_at=datetime.utcnow()-timedelta(days=1))
    audit.set_payload({"reason":"سبب خاص بالخطة المحذوفة", "before":{"installments":[]},"after":{"installments":[]}})
    f["db"].session.add(audit); f["db"].session.delete(old); f["db"].session.commit()
    source=call(f,customer.id,invoice.id).get_json()["data"]
    result=call(f,customer.id,invoice.id,payload(source))
    assert result.status_code==200,result.get_json()
    data=result.get_json()["data"]
    assert data["id"]==old_id and data["history_total"]==1
    assert all(row["reason"]!="سبب خاص بالخطة المحذوفة" for row in data["history"])
