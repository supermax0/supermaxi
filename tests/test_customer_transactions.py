"""Collections read real sources once; GET/CSV/print never post money."""
from uuid import uuid4

from tests.test_finance_operations import finance, installment_invoice, standalone_debt, review_opening, voucher, balance


def read(f, customer_id, suffix="", *, tenant=None, view_all=True):
    from flask import g, session
    path = f"/api/v1/desktop/customers/{customer_id}/transactions{suffix}"
    with f["app"].test_request_context(path):
        session.update(user_id=f["admin"].id, role=f["admin"].role, tenant_slug=tenant or f["tenant"])
        g.tenant=f["tenant"]; g.branch=f["branch"]; g.branches=[f["branch"]]
        g.branch_scope_ready=True; g.view_all_branches=view_all; g.independent_branches_enabled=True
        endpoint, args = f["app"].url_map.bind("localhost").match(path.split("?")[0])
        return f["app"].make_response(f["app"].view_functions[endpoint](**args))


def test_customer_collections_deduplicate_invoice_and_installment_copies_and_reverse_exactly(finance):
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment, CustomerCreditPayment
    from models.activity_log import ActivityLog
    from modules.finance.models import FinanceVoucher
    f=finance
    customer, invoice, linked = installment_invoice(f)
    debt = CustomerCreditPlan(customer_id=customer.id, entry_type="opening", total_amount=200000, paid_amount=0, installments_count=1)
    f["db"].session.add(debt); f["db"].session.flush()
    f["db"].session.add(CustomerInstallment(plan_id=debt.id, sequence=1, amount=200000, due_date=linked.installments[0].due_date))
    f["db"].session.commit(); review_opening(f)
    collected = voucher(f,"customer_payment",150000,party_id=customer.id,treasury_account_id=f["bank"].id,
        allocations=[{"invoice_id":invoice.id,"amount":100000},{"plan_id":debt.id,"amount":50000}])
    voucher(f,"customer_advance",100000,party_id=customer.id)
    settled = f["call"]("credit.apply", {"party_type":"customer","party_id":customer.id,"amount":75000,
        "allocations":[{"invoice_id":invoice.id,"amount":50000},{"plan_id":debt.id,"amount":25000}]})
    voucher(f,"customer_refund",10000,party_id=customer.id)
    data=read(f,customer.id).get_json()["data"]
    assert data["total"] == 4 and all(row["kind"]=="voucher" for row in data["items"])
    assert data["summary"] == {"debt":375000,"advance":15000,"net_due":360000,"unexplained_documents":0,"unexplained_amount":0}
    offset=next(row for row in data["items"] if row["voucher_id"]==settled["id"])
    assert offset["cash"]==0 and offset["debt_change"]==-75000 and offset["advance_change"]==-75000
    f["call"]("voucher.reverse",{"id":collected["id"],"version":collected["version"],"reason":"عكس التحصيل"})
    f["call"]("voucher.reverse",{"id":settled["id"],"version":settled["version"],"reason":"عكس التسوية"})
    snapshot=(FinanceVoucher.query.count(),CustomerCreditPayment.query.count(),ActivityLog.query.count(),balance(f),balance(f,"bank"))
    data=read(f,customer.id).get_json()["data"]
    assert data["total"]==6 and data["summary"]["debt"]==600000 and data["summary"]["advance"]==90000
    assert sum(row["cash"] for row in data["items"])==90000
    assert sum(row["debt_change"] for row in data["items"])==0
    assert read(f,customer.id,"/export").status_code==200
    html=read(f,customer.id,"/print").get_data(as_text=True)
    assert "600,000" in html and "90,000" in html and "عكس تسوية" in html
    assert snapshot==(FinanceVoucher.query.count(),CustomerCreditPayment.query.count(),ActivityLog.query.count(),balance(f),balance(f,"bank"))
    from pathlib import Path
    output=Path(__file__).resolve().parents[1]/"tests"/"_artifacts"/"erp-customers"
    output.mkdir(parents=True,exist_ok=True)
    (output/"transactions-real.html").write_text(html,encoding="utf-8")


def test_customer_collections_preserve_legacy_rows_and_warn_about_missing_history(finance):
    from datetime import datetime
    from models.invoice_payment_ledger import InvoicePaymentLedger
    f=finance
    customer, invoice, _=installment_invoice(f)
    invoice.paid_amount=100000; invoice.payment_status="جزئي"
    f["db"].session.commit()
    data=read(f,customer.id).get_json()["data"]
    assert data["total"]==0 and data["summary"]["unexplained_amount"]==100000
    f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id,branch_id=None,amount_delta=75000,payment_method="cash",recorded_at=datetime(2026,10,11,22,30)))
    f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id,branch_id=None,amount_delta=25000,source_module="invoice_legacy_baseline"))
    f["db"].session.commit()
    data=read(f,customer.id).get_json()["data"]
    assert data["total"]==2 and data["summary"]["unexplained_documents"]==0
    assert next(row for row in data["items"] if row["amount"]==25000)["cash"] is None
    assert next(row for row in data["items"] if row["amount"]==25000)["date"] is None
    assert next(row for row in data["items"] if row["amount"]==75000)["date"].endswith("Z")
    assert "2026-10-12" in read(f,customer.id,"/print").get_data(as_text=True)
    assert "2026-10-12" in read(f,customer.id,"/export").get_json()["data"]["content"]


def test_customer_collections_paginate_export_escape_and_enforce_company_branch_permissions(finance):
    import csv, io
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.branch import Branch
    f=finance
    customer, invoice, _=installment_invoice(f)
    for i in range(32):
        f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id,branch_id=f["branch"].id,amount_delta=1000,
            note="=HYPERLINK(\"unsafe\")" if i==31 else str(i)))
    invoice.paid_amount=32000; invoice.payment_status="جزئي"
    f["db"].session.commit()
    first=read(f,customer.id).get_json()["data"]
    second=read(f,customer.id,"?page=2").get_json()["data"]
    assert first["total"]==second["total"]==32 and len(first["items"])==25 and len(second["items"])==7
    assert first["summary"]==second["summary"] and first["summary"]["debt"]==368000
    rows=list(csv.reader(io.StringIO(read(f,customer.id,"/export").get_json()["data"]["content"].lstrip("\ufeff"))))
    assert len(rows)==33 and any(row[-1].startswith("'=HYPERLINK") for row in rows[1:])
    html=read(f,customer.id,"/print").get_data(as_text=True)
    assert html.count("<tr>")==33 and "368,000" in html
    from pathlib import Path
    output=Path(__file__).resolve().parents[1]/"tests"/"_artifacts"/"erp-customers"
    output.mkdir(parents=True,exist_ok=True)
    (output/"transactions-many-real.html").write_text(html,encoding="utf-8")
    assert read(f,customer.id,"?page_size=4").status_code==400
    assert read(f,customer.id,tenant="another-company").status_code==403
    from models.role import Role
    f["admin"].role="cashier"; f["admin"].roles=[Role(name="transactions-denied-"+uuid4().hex)]; f["db"].session.commit()
    assert read(f,customer.id).status_code==403
    assert read(f,customer.id,"/export").status_code==403
    assert read(f,customer.id,"/print").status_code==403
    f["admin"].role="admin"
    other=Branch(code="HIST",name="Other"); f["db"].session.add(other); f["db"].session.flush()
    customer.branch_id=invoice.branch_id=other.id; f["db"].session.commit()
    assert read(f,customer.id,view_all=False).status_code==404
    assert read(f,customer.id,"/export",view_all=False).status_code==404
    assert read(f,customer.id,"/print",view_all=False).status_code==404


def test_customer_collections_legacy_standalone_cash_is_traced_not_added_twice(finance):
    from utils.customer_credit_service import allocate_payment_fifo
    from sqlalchemy import inspect
    f=finance
    customer, plan=standalone_debt(f,total=500000,paid=0)
    allocate_payment_fifo(customer.id,250000,employee_id=f["admin"].id,note="تحصيل قديم")
    f["db"].session.commit()
    before=balance(f)
    tables=inspect(f["db"].session.connection()).get_table_names()
    result=read(f,customer.id).get_json()["data"]
    assert result["total"]==1 and result["items"][0]["kind"]=="debt_payment"
    assert result["items"][0]["cash"]==250000 and result["items"][0]["debt_change"]==-250000
    assert result["summary"]["debt"]==250000 and result["summary"]["unexplained_documents"]==0
    assert balance(f)==before and inspect(f["db"].session.connection()).get_table_names()==tables


def test_customer_collections_old_ledger_schema_is_read_without_schema_or_balance_mutations(finance):
    from sqlalchemy import text, inspect
    f=finance
    customer, invoice, _=installment_invoice(f)
    invoice.paid_amount=5000; invoice.payment_status="جزئي"; f["db"].session.commit()
    connection=f["db"].session.connection()
    connection.execute(text("DROP TABLE invoice_payment_ledger"))
    connection.execute(text("CREATE TABLE invoice_payment_ledger (id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL, amount_delta INTEGER NOT NULL, recorded_at DATETIME NOT NULL)"))
    connection.execute(text("INSERT INTO invoice_payment_ledger VALUES (1,:invoice,5000,'2026-10-11 12:00:00')"),{"invoice":invoice.id})
    f["db"].session.commit()
    def schema():
        return [{**row,"type":str(row["type"])} for row in inspect(f["db"].session.connection()).get_columns("invoice_payment_ledger")]
    before=schema()
    result=read(f,customer.id).get_json()["data"]
    assert result["total"]==1 and result["items"][0]["amount"]==5000
    assert result["summary"]["unexplained_documents"]==0
    assert schema()==before
