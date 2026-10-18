"""Historical reads use actual finance and invoice sources, never a synthetic opening."""
from datetime import date, datetime, timedelta
import json

from tests.test_finance_operations import finance, installment_invoice, standalone_debt, review_opening, voucher, balance


def read(f, cid, suffix="", *, tenant=None, view_all=True):
    from flask import g, session
    path = f"/api/v1/desktop/customers/{cid}/account-history{suffix}"
    with f["app"].test_request_context(path):
        session.update(user_id=f["admin"].id, role="admin", tenant_slug=tenant or f["tenant"])
        g.tenant=f["tenant"];g.branch=f["branch"];g.branches=[f["branch"]]
        g.branch_scope_ready=True;g.view_all_branches=view_all;g.independent_branches_enabled=True
        endpoint, args=f["app"].url_map.bind("localhost").match(path.split("?")[0])
        return f["app"].make_response(f["app"].view_functions[endpoint](**args))


def born_invoice(f):
    review_opening(f)
    customer, invoice, plan=installment_invoice(f)
    invoice.stock_is_deducted=True
    f["db"].session.commit()
    return customer, invoice, plan


def test_history_records_origin_price_changes_receipts_offsets_and_reversals_once(finance):
    f=finance
    customer, invoice, plan=born_invoice(f)
    invoice.total=450000
    plan.total_amount=450000
    for installment in plan.installments:
        installment.amount=225000
    f["db"].session.commit()
    collected=voucher(f,"customer_payment",100000,party_id=customer.id,
        allocations=[{"invoice_id":invoice.id,"amount":100000}])
    voucher(f,"customer_advance",50000,party_id=customer.id)
    offset=f["call"]("credit.apply",{"party_type":"customer","party_id":customer.id,"amount":20000,
        "allocations":[{"invoice_id":invoice.id,"amount":20000}]})
    from modules.finance.models import FinanceVoucher
    from models.journal_entry import JournalEntry
    before=(balance(f),balance(f,"bank"),FinanceVoucher.query.count(),JournalEntry.query.count(),invoice.paid_amount)
    response=read(f,customer.id)
    assert response.status_code==200,response.get_json()
    data=response.get_json()["data"]
    assert data["coverage"]["complete"] is True,data
    assert sum(row["debt_change"] for row in data["items"])==330000
    assert sum(row["advance_change"] for row in data["items"])==30000
    assert data["summary"]["closing_net"]==300000
    assert sum(row["cash"] for row in data["items"])==150000
    assert len([r for r in data["items"] if r["kind"]=="debt_origin"])==2
    assert read(f,customer.id,"/print").status_code==200
    assert read(f,customer.id,"/export").status_code==200
    assert before==(balance(f),balance(f,"bank"),FinanceVoucher.query.count(),JournalEntry.query.count(),invoice.paid_amount)
    f["call"]("voucher.reverse",{"id":collected["id"],"version":collected["version"],"reason":"عكس"})
    f["call"]("voucher.reverse",{"id":offset["id"],"version":offset["version"],"reason":"عكس"})
    data=read(f,customer.id).get_json()["data"]
    assert data["coverage"]["complete"] and data["summary"]["closing_net"]==400000
    from pathlib import Path
    output=Path(__file__).resolve().parents[1]/"tests/_artifacts/erp-customers"
    output.mkdir(parents=True,exist_ok=True)
    (output/"account-history-real.json").write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    (output/"account-history-real.html").write_text(read(f,customer.id,"/print").get_data(as_text=True),encoding="utf-8")
    (output/"account-history-real.csv").write_text(read(f,customer.id,"/export").get_json()["data"]["content"],encoding="utf-8")


def test_history_unknown_legacy_origin_never_invents_running_balances(finance):
    f=finance
    customer, invoice, _=installment_invoice(f)
    data=read(f,customer.id).get_json()["data"]
    assert data["coverage"]["complete"] is False
    assert data["coverage"]["missing_origins"]==1
    assert data["coverage"]["unplaced_debt"]==400000
    assert data["summary"]["closing_net"] is None
    assert all(row["net_balance"] is None for row in data["items"])
    assert "غير مثبت" in read(f,customer.id,"/print").get_data(as_text=True)


def test_history_period_opening_and_paginated_day_end_balance(finance):
    f=finance
    customer, invoice, _=born_invoice(f)
    from modules.finance.models import FinanceVoucher
    first=FinanceVoucher.query.filter_by(source_type="invoice_auto",source_id=invoice.id).first()
    from flask import g
    g.finance_operation=True
    first.transaction_date=date(2026,1,1)
    f["db"].session.commit()
    g.finance_operation=False
    receipt=voucher(f,"customer_payment",100000,party_id=customer.id,
        allocations=[{"invoice_id":invoice.id,"amount":100000}])
    v=f["db"].session.get(FinanceVoucher,receipt["id"])
    # Change dates through the existing finance command before posting in real usage;
    # this test fixture only arranges business dates directly.
    from flask import g
    g.finance_operation=True
    v.transaction_date=date(2026,1,2)
    f["db"].session.commit()
    g.finance_operation=False
    data=read(f,customer.id,"?date_from=2026-01-02&date_to=2026-01-02&page_size=10").get_json()["data"]
    assert data["coverage"]["complete"] and data["total"]==1
    assert data["summary"]["opening_net"]==400000 and data["summary"]["closing_net"]==300000
    assert data["items"][0]["net_balance"]==300000
    assert read(f,customer.id,"?date_from=2026-02-30").status_code==400
    assert read(f,customer.id,"?date_from=2026-01-03&date_to=2026-01-01").status_code==400
    assert read(f,customer.id,"?page=-1").status_code==400
    assert read(f,customer.id,tenant="other-company").status_code==403


def test_history_bad_source_and_undated_baseline_are_explicit(finance):
    f=finance
    customer, invoice, _=born_invoice(f)
    from modules.finance.models import FinanceVoucher
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from flask import g
    g.finance_operation=True
    v=FinanceVoucher.query.filter_by(source_type="invoice_auto",source_id=invoice.id).first()
    v.payload='{"before":null,"after":{}}'
    f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id,amount_delta=0,source_module="invoice_legacy_baseline"))
    f["db"].session.commit()
    g.finance_operation=False
    data=read(f,customer.id).get_json()["data"]
    assert data["coverage"]["malformed_sources"]==1 and data["coverage"]["undated_movements"]==1
    assert not data["coverage"]["complete"] and all(row["net_balance"] is None for row in data["items"])


def test_history_cancellation_has_original_and_counter_entry_without_cash(finance):
    f=finance
    customer, invoice, _=born_invoice(f)
    invoice.status="ملغي"
    invoice.stock_is_deducted=False
    f["db"].session.commit()
    data=read(f,customer.id).get_json()["data"]
    assert data["coverage"]["complete"] and data["summary"]["closing_net"]==0
    assert sorted(row["debt_change"] for row in data["items"])==[-400000,400000]
    assert all(row["cash"]==0 for row in data["items"])


def test_history_permission_limit_and_safe_print(finance,monkeypatch):
    f=finance
    customer, invoice, _=born_invoice(f)
    customer.name="<script>bad()</script>"
    f["db"].session.commit()
    html=read(f,customer.id,"/print").get_data(as_text=True)
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html and "<script>bad()" not in html
    monkeypatch.setattr("modules.desktop_api.customer_statement.LIMIT",0)
    assert read(f,customer.id).status_code==400
    monkeypatch.setattr("modules.desktop_api.customers.employee_can",lambda *_:False)
    assert read(f,customer.id).status_code==403


def test_history_branch_scope_and_explicit_customer_attribution(finance):
    f=finance
    customer, invoice, _=born_invoice(f)
    from models.branch import Branch
    from models.customer import Customer
    from modules.finance.models import FinanceVoucher
    from flask import g
    branch=Branch(code="OTHER-HISTORY",name="فرع آخر",is_active=True)
    f["db"].session.add(branch);f["db"].session.flush()
    other=Customer(name="عميل فرع آخر",phone="07700000009",branch_id=branch.id)
    f["db"].session.add(other);f["db"].session.commit()
    assert read(f,other.id,view_all=False).status_code==404
    # A source with a recorded customer identity must never be reassigned by
    # looking up its invoice's current owner. Arrange an imported mismatch.
    g.finance_operation=True
    origin=FinanceVoucher.query.filter_by(source_type="invoice_auto",source_id=invoice.id).first()
    origin.party_id=other.id
    f["db"].session.commit();g.finance_operation=False
    data=read(f,customer.id).get_json()["data"]
    assert not any(row["kind"]=="debt_origin" for row in data["items"])
    assert not data["coverage"]["complete"] and data["coverage"]["unplaced_debt"]==400000


def test_history_standalone_origin_and_collection_are_not_invoice_principal(finance):
    f=finance
    review_opening(f)
    customer, plan=standalone_debt(f,total=200000,paid=0)
    voucher(f,"customer_payment",50000,party_id=customer.id,
        allocations=[{"plan_id":plan.id,"amount":50000}])
    data=read(f,customer.id).get_json()["data"]
    assert data["coverage"]["complete"] and data["summary"]["closing_net"]==150000
    origins=[row for row in data["items"] if row["kind"]=="debt_origin"]
    assert len(origins)==1 and origins[0]["plan_id"]==plan.id and origins[0]["invoice_id"] is None
    assert sum(row["cash"] for row in data["items"])==50000


def test_history_old_source_cannot_certify_a_new_document_with_reused_id(finance):
    f=finance
    customer, invoice, _=born_invoice(f)
    from flask import g
    g.finance_operation=True
    invoice.created_at=datetime.utcnow()+timedelta(seconds=1)
    f["db"].session.commit();g.finance_operation=False
    data=read(f,customer.id).get_json()["data"]
    assert data["coverage"]["archived_documents"]==1
    assert not data["coverage"]["complete"] and data["summary"]["closing_net"] is None


def test_history_unattributed_legacy_source_does_not_prove_original_customer(finance):
    f=finance
    customer, invoice, _=born_invoice(f)
    from flask import g
    from modules.finance.models import FinanceVoucher
    g.finance_operation=True
    origin=FinanceVoucher.query.filter_by(source_type="invoice_auto",source_id=invoice.id).first()
    origin.party_type="other";origin.party_id=None
    f["db"].session.commit();g.finance_operation=False
    data=read(f,customer.id).get_json()["data"]
    assert any(row["kind"]=="debt_origin" for row in data["items"])
    assert data["coverage"]["unplaced_debt"]==0 and data["coverage"]["missing_origins"]==1
    assert not data["coverage"]["complete"] and all(row["net_balance"] is None for row in data["items"])
