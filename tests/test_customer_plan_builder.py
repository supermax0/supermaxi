"""Schedule creation/repartition keep debt, cash and historical reversal identities."""
from copy import deepcopy
from uuid import uuid4

import pytest

from tests.test_finance_operations import finance, installment_invoice, standalone_debt, review_opening, voucher, balance
from tests.test_customer_schedules import request_schedule


def call(f, customer_id, source_id, body=None, *, create=True, tenant=None, view_all=True):
    from flask import g, session
    path = f"/api/v1/desktop/customers/{customer_id}/" + (
        f"invoices/{source_id}/schedule" if create else f"plans/{source_id}/repartition")
    with f["app"].test_request_context(path, method="POST" if body else "GET", json=body):
        session.update(user_id=f["admin"].id, role=f["admin"].role, tenant_slug=tenant or f["tenant"])
        g.tenant=f["tenant"]; g.branch=f["branch"]; g.branches=[f["branch"]]
        g.branch_scope_ready=True; g.view_all_branches=view_all; g.independent_branches_enabled=True
        endpoint, args=f["app"].url_map.bind("localhost").match(path, method="POST" if body else "GET")
        return f["app"].make_response(f["app"].view_functions[endpoint](**args))


def payload(data, count=3):
    return {"idempotency_key":str(uuid4()), "revision":data["revision"], "reason":"طلب العميل تقسيم المبلغ المتبقي",
        "count":count, "first_due_date":"2027-01-31", "interval":"monthly"}


def unpaid_invoice(f):
    customer, invoice, plan=installment_invoice(f)
    f["db"].session.delete(plan); f["db"].session.commit()
    return customer, invoice


def test_new_invoice_schedule_is_exact_retry_safe_calendar_based_and_never_posts_money(finance):
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from modules.finance.models import FinanceVoucher
    from modules.desktop_api.customers import _workspace_query
    f=finance
    customer, invoice=unpaid_invoice(f)
    before=(invoice.total,invoice.paid_amount,balance(f),CustomerCreditPayment.query.count(),InvoicePaymentLedger.query.count(),FinanceVoucher.query.count())
    preview=call(f,customer.id,invoice.id).get_json()["data"]
    assert preview["eligible"] and preview["plan_id"] is None
    body=payload(preview)
    result=call(f,customer.id,invoice.id,body)
    assert result.status_code==200, result.get_json()
    data=result.get_json()["data"]
    assert [r["date"] for r in data["installments"]]==["2027-01-31","2027-02-28","2027-03-31"]
    assert [r["total"] for r in data["installments"]]==[133333,133333,133334]
    assert data["total"]==400000 and data["paid"]==0 and data["history_total"]==1
    assert before==(invoice.total,invoice.paid_amount,balance(f),CustomerCreditPayment.query.count(),InvoicePaymentLedger.query.count(),FinanceVoucher.query.count())
    assert call(f,customer.id,invoice.id,body).get_json()==result.get_json()
    second=payload(preview)
    assert call(f,customer.id,invoice.id,second).status_code==409
    assert CustomerCreditPlan.query.filter_by(invoice_id=invoice.id).count()==1
    assert not call(f,customer.id,invoice.id).get_json()["data"]["eligible"]
    invoice.status="ملغي"; f["db"].session.commit()
    assert call(f,customer.id,invoice.id,body).get_json()==result.get_json()


@pytest.mark.parametrize("linked", [True,False])
def test_future_repartition_preserves_paid_rows_and_real_financial_reversal(finance, linked):
    from models.customer_credit import CustomerCreditPayment
    from modules.finance import ledger
    f=finance
    if linked: customer,invoice,plan=installment_invoice(f)
    else:
        customer,plan=standalone_debt(f,total=400000,paid=0); invoice=None
    review_opening(f)
    payment=voucher(f,"customer_payment",150000,party_id=customer.id,treasury_account_id=f["bank"].id)
    source=request_schedule(f,customer.id,plan.id).get_json()["data"]
    frozen=source["installments"][0]
    assert source["protected_ids"]==[frozen["id"]]
    payments=[(p.id,p.installment_id,p.amount) for p in CustomerCreditPayment.query.order_by(CustomerCreditPayment.id)]
    body=payload(source,3)
    response=call(f,customer.id,plan.id,body,create=False)
    assert response.status_code==200,response.get_json()
    data=response.get_json()["data"]
    assert len(data["installments"])==4 and data["installments"][0]==frozen
    assert sum(r["total"] for r in data["installments"])==400000 and data["paid"]==150000
    assert plan.installments_count==4 and balance(f,"bank")==150000 and ledger.account("receivable").balance==250000
    assert payments==[(p.id,p.installment_id,p.amount) for p in CustomerCreditPayment.query.order_by(CustomerCreditPayment.id)]
    assert call(f,customer.id,plan.id,body,create=False).get_json()==response.get_json()
    f["call"]("voucher.reverse",{"id":payment["id"],"version":payment["version"],"reason":"عكس بعد تغيير عدد الأقساط"})
    assert plan.paid_amount==0 and (not invoice or invoice.paid_amount==0)
    assert balance(f,"bank")==0 and ledger.account("receivable").balance==400000
    # Even a fully reversed historical payment keeps its installment identity frozen.
    source=request_schedule(f,customer.id,plan.id).get_json()["data"]
    assert frozen["id"] in source["protected_ids"]
    reduced=call(f,customer.id,plan.id,payload(source,1),create=False)
    assert reduced.status_code==200 and len(reduced.get_json()["data"]["installments"])==2
    assert reduced.get_json()["data"]["installments"][0]["id"]==frozen["id"]


@pytest.mark.parametrize("invalid", ["count","boolean","fraction","interval","date","overflow","reason","revision"])
def test_builder_rejects_invalid_values_without_receipts_or_plans(finance, invalid):
    from models.customer_credit import CustomerCreditPlan
    from modules.desktop_api.sync import DesktopSyncReceipt
    f=finance; customer,invoice=unpaid_invoice(f)
    body=payload(call(f,customer.id,invoice.id).get_json()["data"])
    if invalid=="count": body["count"]=0
    elif invalid=="boolean": body["count"]=True
    elif invalid=="fraction": body["count"]=2.5
    elif invalid=="interval": body["interval"]="daily"
    elif invalid=="date": body["first_due_date"]="2027-02-30"
    elif invalid=="overflow": body["first_due_date"]="9999-12-31"
    elif invalid=="reason": body["reason"]=""
    elif invalid=="revision": body["revision"]="bad"
    assert call(f,customer.id,invoice.id,body).status_code==400
    assert CustomerCreditPlan.query.count()==0 and DesktopSyncReceipt.query.count()==0


def test_builder_rejects_changed_paid_canceled_or_out_of_scope_sources(finance):
    from models.branch import Branch
    from models.role import Role
    from models.invoice_payment_ledger import InvoicePaymentLedger
    f=finance; customer,invoice=unpaid_invoice(f)
    body=payload(call(f,customer.id,invoice.id).get_json()["data"])
    invoice.total+=1; f["db"].session.commit()
    assert call(f,customer.id,invoice.id,body).status_code==409
    fresh=payload(call(f,customer.id,invoice.id).get_json()["data"])
    f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id,amount_delta=1))
    f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id,amount_delta=-1)); f["db"].session.commit()
    assert not call(f,customer.id,invoice.id).get_json()["data"]["eligible"]
    assert call(f,customer.id,invoice.id,fresh).status_code==409
    assert call(f,customer.id,invoice.id,tenant="wrong-company").status_code==403
    f["admin"].role="cashier"; f["admin"].roles=[Role(name="plan-builder-denied-"+uuid4().hex)]; f["db"].session.commit()
    assert call(f,customer.id,invoice.id).status_code==403 and call(f,customer.id,invoice.id,fresh).status_code==403
    f["admin"].role="admin"
    other=Branch(code="OTHER",name="other"); f["db"].session.add(other); f["db"].session.flush()
    invoice.branch_id=other.id; f["db"].session.commit()
    assert call(f,customer.id,invoice.id,view_all=False).status_code==404


@pytest.mark.parametrize("create", [True,False])
def test_creation_rolls_back_source_guard_audit_and_schedule_then_retries(finance, monkeypatch, create):
    from models.activity_log import ActivityLog
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment
    from modules.desktop_api.sync import DesktopSyncReceipt
    f=finance
    if create:
        customer,invoice=unpaid_invoice(f); source_id=invoice.id
        source=call(f,customer.id,source_id).get_json()["data"]
    else:
        customer,invoice,plan=installment_invoice(f); source_id=plan.id
        source=request_schedule(f,customer.id,source_id).get_json()["data"]
    body=payload(source)
    counts=(CustomerCreditPlan.query.count(),CustomerInstallment.query.count(),DesktopSyncReceipt.query.count())
    original=f["db"].session.add
    def fail_audit(row, *args, **kwargs):
        if isinstance(row,ActivityLog): raise RuntimeError("simulated audit failure")
        return original(row,*args,**kwargs)
    monkeypatch.setattr(f["db"].session,"add",fail_audit)
    assert call(f,customer.id,source_id,body,create=create).status_code==500
    assert counts==(CustomerCreditPlan.query.count(),CustomerInstallment.query.count(),DesktopSyncReceipt.query.count())
    if not create:
        assert request_schedule(f,customer.id,source_id).get_json()["data"]==source
    monkeypatch.setattr(f["db"].session,"add",original)
    assert call(f,customer.id,source_id,body,create=create).status_code==200


@pytest.mark.parametrize("field,value",[("status","ملغي"),("payment_status","مرتجع"),("paid_amount",400000),("is_stock_locked",True)])
def test_creation_rejects_ineligible_invoice_states(finance, field, value):
    f=finance; customer,invoice=unpaid_invoice(f)
    body=payload(call(f,customer.id,invoice.id).get_json()["data"])
    setattr(invoice,field,value); f["db"].session.commit()
    assert not call(f,customer.id,invoice.id).get_json()["data"]["eligible"]
    assert call(f,customer.id,invoice.id,body).status_code==409


def test_payment_history_changes_revision_even_when_paid_net_stays_zero(finance):
    from models.customer_credit import CustomerCreditPayment
    f=finance; customer,_,plan=installment_invoice(f)
    before=request_schedule(f,customer.id,plan.id).get_json()["data"]
    target=before["installments"][0]["id"]
    f["db"].session.add_all([CustomerCreditPayment(customer_id=customer.id,plan_id=plan.id,installment_id=target,amount=1),
        CustomerCreditPayment(customer_id=customer.id,plan_id=plan.id,installment_id=target,amount=-1)])
    f["db"].session.commit()
    after=request_schedule(f,customer.id,plan.id).get_json()["data"]
    assert after["revision"]!=before["revision"] and after["paid"]==0 and after["protected_ids"]==[target]
    assert call(f,customer.id,plan.id,payload(before),create=False).status_code==409


def test_zero_baseline_is_not_a_payment_and_weekly_creation_keeps_the_source_amount(finance):
    from models.invoice_payment_ledger import InvoicePaymentLedger
    f=finance; customer,invoice=unpaid_invoice(f)
    f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id,amount_delta=0)); f["db"].session.commit()
    preview=call(f,customer.id,invoice.id).get_json()["data"]
    assert preview["eligible"]
    body=payload(preview); body["interval"]="weekly"
    result=call(f,customer.id,invoice.id,body)
    assert result.status_code==200,result.get_json()
    assert [r["date"] for r in result.get_json()["data"]["installments"]]==["2027-01-31","2027-02-07","2027-02-14"]
    assert invoice.total==400000 and invoice.paid_amount==0
