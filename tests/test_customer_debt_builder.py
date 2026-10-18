"""Real opening receivable creation, source guards and collection/reversal lifecycle."""
from uuid import uuid4

import pytest

from tests.test_finance_operations import finance, review_opening, voucher, balance


def customer(f):
    from models.customer import Customer
    row = Customer(name="عميل الرصيد الافتتاحي", phone="0770"+uuid4().hex[:7], branch_id=f["branch"].id)
    f["db"].session.add(row); f["db"].session.commit()
    return row


def call(f, customer_id, body=None, *, tenant=None, view_all=True):
    from flask import g, session
    from modules.desktop_api.customer_debt_builder import customer_debt_create
    with f["app"].test_request_context(f"/api/v1/desktop/customers/{customer_id}/debts", method="POST" if body else "GET", json=body):
        session.update(user_id=f["admin"].id, role=f["admin"].role, tenant_slug=tenant or f["tenant"])
        g.tenant=f["tenant"]; g.branch=f["branch"]; g.branches=[f["branch"]]
        g.branch_scope_ready=True; g.view_all_branches=view_all; g.independent_branches_enabled=True
        return f["app"].make_response(customer_debt_create(customer_id))


def payload(source, **changes):
    return {"idempotency_key":str(uuid4()), "revision":source["revision"], "source_type":"opening",
        "source_reference":"EXT-2026-001", "amount":400000, "reason":"كشف مديونية خارجي متبقٍ",
        "count":3, "first_due_date":"2027-01-31", "interval":"monthly", **changes}


def prepared(f):
    row=customer(f); review_opening(f)
    return row,payload(call(f,row.id).get_json()["data"])


def counts():
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment, CustomerCreditPayment
    from modules.finance.models import FinanceCommand, FinanceVoucher, FinanceSourceState
    from models.journal_entry import JournalEntry
    from modules.desktop_api.sync import DesktopSyncReceipt
    from models.activity_log import ActivityLog
    from models.account_transaction import AccountTransaction
    return tuple(model.query.count() for model in (CustomerCreditPlan,CustomerInstallment,CustomerCreditPayment,
        FinanceCommand,FinanceVoucher,FinanceSourceState,JournalEntry,DesktopSyncReceipt,ActivityLog,AccountTransaction))


def test_opening_debt_posts_once_then_collects_and_reverses_exactly(finance):
    from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
    from modules.finance import ledger
    from modules.finance.models import FinanceVoucher, FinanceSourceState
    from models.journal_entry import JournalEntry
    from models.invoice import Invoice
    from modules.finance.standalone_debts import assert_reviewed
    f=finance; row,body=prepared(f)
    money_before=(balance(f),balance(f,"bank"),ledger.account("revenue").balance,ledger.account("inventory").balance)
    result=call(f,row.id,body)
    assert result.status_code==200,result.get_json()
    data=result.get_json()["data"]
    plan=f["db"].session.get(CustomerCreditPlan,data["id"])
    assert plan.invoice_id is None and plan.entry_type=="opening" and plan.paid_amount==0
    assert [(i["date"],i["total"]) for i in data["installments"]]==[("2027-01-31",133333),("2027-02-28",133333),("2027-03-31",133334)]
    assert data["history_total"]==1 and "EXT-2026-001" in data["history"][0]["reason"]
    assert Invoice.query.count()==CustomerCreditPayment.query.count()==0
    assert money_before==(balance(f),balance(f,"bank"),ledger.account("revenue").balance,ledger.account("inventory").balance)
    assert ledger.account("receivable").balance==400000
    origin=FinanceVoucher.query.filter_by(source_type="customer_debt_auto",source_id=plan.id).one()
    assert origin.kind=="settlement" and origin.status=="posted" and origin.party_id==row.id and origin.branch_id==f["branch"].id
    assert "EXT-2026-001" in origin.notes
    html=f["get"](f"/accounts/finance/vouchers/{origin.id}/print")
    assert "EXT-2026-001" in html and "تسجيل رصيد دين مستقل" in html
    entries=ledger.entries(origin)
    assert len(entries)==1 and entries[0].amount==400000
    assert entries[0].debit_account_id==ledger.account("receivable").id and entries[0].credit_account_id==ledger.account("opening_equity").id
    assert_reviewed(plan)
    after=counts()
    assert call(f,row.id,body).get_json()==result.get_json() and counts()==after
    duplicate={**body,"idempotency_key":str(uuid4()),"source_reference":"  ext-2026-001  "}
    assert call(f,row.id,duplicate).status_code==409 and counts()==after
    payment=voucher(f,"customer_payment",150000,party_id=row.id,treasury_account_id=f["bank"].id,
        allocations=[{"plan_id":plan.id,"amount":150000}])
    assert plan.paid_amount==150000 and balance(f,"bank")==150000 and ledger.account("receivable").balance==250000
    f["call"]("voucher.reverse",{"id":payment["id"],"version":payment["version"],"reason":"تصحيح التحصيل"})
    assert plan.paid_amount==0 and balance(f,"bank")==0 and ledger.account("receivable").balance==400000
    assert_reviewed(plan)
    assert call(f,row.id,body).get_json()==result.get_json()
    assert FinanceSourceState.query.filter_by(key=f"customer_debt:{plan.id}").one()
    assert len(JournalEntry.query.filter_by(reference_type="finance_voucher",reference_id=origin.id).all())==1
    workspace=f["get"](f"/api/v1/desktop/customers/{row.id}/history?kind=receivables").get_json()["data"]
    assert workspace["summary"]["remaining"]==400000 and workspace["items"][0]["kind"]=="credit_plan"


@pytest.mark.parametrize("changes",[
    {"amount":True},{"amount":0},{"amount":1.5},{"amount":2147483648},{"amount":2},
    {"source_type":"sale"},{"source_reference":"a"},{"source_reference":"x"*81},{"source_reference":"ABC\nDEF"},
    {"reason":"x"*121},{"count":False},{"count":241},{"first_due_date":"9999-12-31"},
    {"interval":"daily"},{"revision":"bad"},{"extra":"unexpected"},
])
def test_invalid_opening_debt_has_no_business_or_command_side_effects(finance,changes):
    f=finance; row,body=prepared(f); before=counts()
    response=call(f,row.id,{**body,**changes})
    assert response.status_code==400,response.get_json()
    assert counts()==before


def test_preview_is_read_only_and_creation_requires_review_and_fresh_customer(finance):
    f=finance; row=customer(f); before=counts()
    source=call(f,row.id).get_json()["data"]
    assert not source["eligible"] and counts()==before
    assert call(f,row.id,payload(source)).status_code==409 and counts()==before
    review_opening(f)
    source=call(f,row.id).get_json()["data"]
    row.name="تغير الاسم"; f["db"].session.commit(); before=counts()
    assert call(f,row.id,payload(source)).status_code==409 and counts()==before


def test_opening_debt_scopes_tenant_branch_and_explicit_permissions(finance):
    from models.branch import Branch
    from models.role import Role, Permission
    f=finance; row,body=prepared(f); before=counts()
    assert call(f,row.id,body,tenant="another").status_code==403 and counts()==before
    f["admin"].role="cashier"
    permission=Permission.query.filter_by(name="manage_customers").first()
    if not permission:
        permission=Permission(name="manage_customers"); f["db"].session.add(permission)
    role=Role(name="debt-no-finance-"+uuid4().hex); role.permissions=[permission]
    f["admin"].roles=[role]; f["db"].session.commit()
    assert call(f,row.id).status_code==403 and call(f,row.id,body).status_code==403
    f["admin"].role="admin"; f["db"].session.commit()
    other=Branch(code="OTHER",name="other"); f["db"].session.add(other); f["db"].session.flush()
    row.branch_id=other.id; f["db"].session.commit()
    assert call(f,row.id,view_all=False).status_code==404 and call(f,row.id,body,view_all=False).status_code==404


def test_audit_failure_rolls_back_principal_journal_receipt_and_allows_exact_retry(finance,monkeypatch):
    from models.activity_log import ActivityLog
    from modules.finance import ledger
    f=finance; row,body=prepared(f); before=counts(); old_add=f["db"].session.add
    def fail(row,*args,**kwargs):
        if isinstance(row,ActivityLog): raise RuntimeError("simulated activity failure")
        return old_add(row,*args,**kwargs)
    monkeypatch.setattr(f["db"].session,"add",fail)
    response=call(f,row.id,body)
    assert response.status_code==500 and counts()==before and ledger.account("receivable").balance==0
    monkeypatch.setattr(f["db"].session,"add",old_add)
    assert call(f,row.id,body).status_code==200 and ledger.account("receivable").balance==400000


def test_closed_posting_period_rejects_the_whole_opening_source(finance):
    from models.financial_period_close import FinancialPeriodClose
    from modules.finance.common import today
    f=finance; row,body=prepared(f)
    f["db"].session.add(FinancialPeriodClose(period_year=today().year,period_month=today().month,closed_by=f["admin"].id))
    f["db"].session.commit(); before=counts()
    assert call(f,row.id,body).status_code==409 and counts()==before


def test_uuid_cannot_be_reused_with_another_amount_or_customer(finance):
    f=finance; row,body=prepared(f)
    assert call(f,row.id,body).status_code==200
    before=counts()
    assert call(f,row.id,{**body,"amount":400001}).status_code==409 and counts()==before
    other=customer(f)
    assert call(f,other.id,body).status_code==409 and counts()==before


def test_collapsed_account_mapping_cannot_recognize_debt_without_a_journal(finance):
    from modules.finance.models import FinanceMapping
    f=finance; row,body=prepared(f)
    f["db"].session.get(FinanceMapping,"opening_equity").account_id=f["db"].session.get(FinanceMapping,"receivable").account_id
    f["db"].session.commit(); before=counts()
    assert call(f,row.id,body).status_code==409 and counts()==before


def test_receipt_replay_is_bound_to_the_original_customer_branch(finance):
    from models.branch import Branch
    f=finance; row,body=prepared(f)
    assert call(f,row.id,body).status_code==200
    other=Branch(code="OTHER",name="other"); f["db"].session.add(other); f["db"].session.flush()
    row.branch_id=other.id; f["db"].session.commit(); before=counts()
    assert call(f,row.id,body).status_code==409 and counts()==before
