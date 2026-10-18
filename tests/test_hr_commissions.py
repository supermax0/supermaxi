from datetime import datetime
from uuid import uuid4
from flask import g
from extensions import db
from extensions_tenant import init_tenant_db
from tests.test_hr_workspace import ctx, command, create_person, _client, _fund, TENANT, JSON


def invoice(ctx, total=100000, cost=None):
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        base = db.session.get(Invoice, ctx["ids"]["order_ids"][0])
        row = Invoice(customer_id=base.customer_id, customer_name=base.customer_name,
            branch_id=base.branch_id, status="تم التوصيل", payment_status="مسدد", paid_amount=total,
            total=total, created_at=datetime(2026, 6, 10, 8))
        db.session.add(row)
        db.session.flush()
        if cost is not None:
            product = Product.query.first()
            db.session.add(OrderItem(invoice_id=row.id, product_id=product.id, product_name=product.name, quantity=1, price=total, total=total, cost=cost))
        db.session.commit()
        return row.id


def get_row(client, person_id, source="hr"):
    response = client.get(f"/hr/api/workspace?tab=commissions&person_id={person_id}", headers=JSON)
    assert response.status_code == 200, response.get_json()
    return next(r for r in response.get_json()["rows"] if r["source"] == source)


def test_importing_paid_legacy_commission_preserves_the_original_cash_and_expense(ctx):
    client=_client(ctx)
    client.get("/hr/api/lookups",headers=JSON)
    account_id=_fund(ctx)
    invoice_id=invoice(ctx)
    from models.employee_commission_line import EmployeeCommissionLine
    from modules.hr.models import HRPerson,HRCommission
    from models.account_transaction import AccountTransaction
    from models.expense import Expense
    from utils.payroll_service import settle_employee_commission_payment
    with ctx["app"].app_context():
        g.tenant=TENANT;init_tenant_db(TENANT)
        person_id=HRPerson.query.filter_by(employee_id=ctx["ids"]["clerk_id"]).one().id
        line=EmployeeCommissionLine(code=EmployeeCommissionLine.make_code(invoice_id,ctx["ids"]["clerk_id"]),invoice_id=invoice_id,employee_id=ctx["ids"]["clerk_id"],amount=9000,accrued_at=datetime(2026,6,10))
        db.session.add(line);db.session.commit();line_id=line.id
        with ctx["app"].test_request_context("/hr/legacy-test"):
            from flask import session
            session.update(user_id=ctx["ids"]["admin_id"],tenant_slug=TENANT,role="admin")
            paid=settle_employee_commission_payment(ctx["ids"]["clerk_id"],treasury_account_id=account_id,settled_by=ctx["ids"]["admin_id"],year=2026,month=6)
        assert paid["ok"],paid
        db.session.commit()
        movements=AccountTransaction.query.filter_by(type="withdraw",treasury_account_id=account_id).count()
        expenses=Expense.query.count()
    imported=command(client,"commission.import",{"legacy_id":line_id})
    assert imported.status_code==200,imported.get_json()
    row=get_row(client,person_id)
    assert row["paid"]==9000 and row["remaining"]==0 and row["status"]=="paid"
    statement=client.get(f"/hr/api/statement?person_id={person_id}",headers=JSON).get_json()
    assert statement["balance"]==0 and statement["paid"]==9000 and len(statement["rows"])==1
    assert command(client,"commission.pay",{"commission_id":imported.get_json()["id"],"version":row["version"],"treasury_account_id":account_id}).status_code==400
    with ctx["app"].app_context():
        g.tenant=TENANT;init_tenant_db(TENANT)
        assert AccountTransaction.query.filter_by(type="withdraw",treasury_account_id=account_id).count()==movements
        assert Expense.query.count()==expenses
        assert db.session.get(HRCommission,imported.get_json()["id"]).legacy_line_id==line_id


def test_pending_commission_reassignment_cannot_pay_the_previous_owner(ctx):
    client=_client(ctx)
    first,second=create_person(client,ctx),create_person(client,ctx)
    for person_id in (first,second):
        assert command(client,"commission.policy",{"person_id":person_id,"effective_from":"2026-01-01","kind":"sales","basis_points":1000}).status_code==200
    sale=invoice(ctx)
    assert command(client,"commission.assign",{"person_id":first,"invoice_id":sale}).status_code==200
    old=get_row(client,first)
    assert command(client,"commission.assign",{"person_id":second,"invoice_id":sale}).status_code==200
    assert get_row(client,first)["status"]=="void"
    refused=command(client,"commission.approve",{"commission_id":old["id"],"version":old["version"]})
    assert refused.status_code==400,refused.get_json()
    current=get_row(client,second)
    assert current["amount"]==10000
    assert command(client,"commission.approve",{"commission_id":current["id"],"version":current["version"]}).status_code==200
    assert command(client,"commission.assign",{"person_id":first,"invoice_id":sale}).status_code==400


def test_commission_pay_cancel_restore_preserves_cash_and_expense_history(ctx):
    client = _client(ctx)
    person_id = create_person(client, ctx)
    policy = command(client, "commission.policy", {"person_id": person_id, "effective_from": "2026-01-01", "kind": "sales", "basis_points": 1000})
    assert policy.status_code == 200, policy.get_json()
    invoice_id = invoice(ctx)
    assert command(client, "commission.assign", {"person_id": person_id, "invoice_id": invoice_id}).status_code == 200
    row = get_row(client, person_id)
    assert row["amount"] == 10000
    approved = command(client, "commission.approve", {"commission_id": row["id"], "version": row["version"]})
    assert approved.status_code == 200, approved.get_json()
    account_id = _fund(ctx)
    row = get_row(client, person_id)
    request_id = str(uuid4())
    payload = {"commission_id": row["id"], "version": row["version"], "treasury_account_id": account_id}
    paid = command(client, "commission.pay", payload, request_id)
    assert paid.status_code == 200, paid.get_json()
    assert command(client, "commission.pay", payload, request_id).get_json() == paid.get_json()
    from models.invoice import Invoice
    from models.account_transaction import AccountTransaction
    from models.expense import Expense
    from modules.hr.models import HRCommission, HRAdvance
    from utils.payroll_service import sync_commission_line_for_invoice, remove_commission_lines_for_deleted_invoice
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        sale = db.session.get(Invoice, invoice_id)
        sale.status = "ملغي"
        sync_commission_line_for_invoice(sale)
        db.session.commit()
        assert AccountTransaction.query.filter_by(treasury_account_id=account_id, type="withdraw").count() == 1
        assert db.session.get(HRCommission, row["id"]).paid == 10000
        try:
            remove_commission_lines_for_deleted_invoice(invoice_id, allow_paid=True)
            assert False, "HR financial history must prevent hard deletion"
        except ValueError:
            pass
    change = get_row(client, person_id, "change")
    accepted = command(client, "commission.change", {"change_id": change["entity_id"], "version": change["version"],
        "reason": "إلغاء البيع", "first_month": "2026-07", "instalments": 2})
    assert accepted.status_code == 200, accepted.get_json()
    assert get_row(client, person_id)["remaining"] == 0
    statement=client.get(f"/hr/api/statement?person_id={person_id}",headers=JSON).get_json()
    assert statement["balance"]==0 and statement["paid"]==10000 and statement["advance_remaining"]==10000
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        assert HRAdvance.query.filter_by(person_id=person_id).one().amount == 10000
        sale = db.session.get(Invoice, invoice_id)
        sale.status = "تم التوصيل"
        sync_commission_line_for_invoice(sale)
        db.session.commit()
    change = get_row(client, person_id, "change")
    result = command(client, "commission.change", {"change_id": change["entity_id"], "version": change["version"], "reason": "إعادة البيع"})
    assert result.status_code == 200, result.get_json()
    statement=client.get(f"/hr/api/statement?person_id={person_id}",headers=JSON).get_json()
    assert statement["balance"]==0 and statement["advance_remaining"]==0
    row = get_row(client, person_id)
    assert row["remaining"] == 0
    assert command(client, "commission.pay", {"commission_id": row["id"], "version": row["version"], "treasury_account_id": account_id}).status_code == 400
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        advance = HRAdvance.query.filter_by(person_id=person_id).one()
        assert advance.repaid == 10000 and advance.status == "repaid"
        assert AccountTransaction.query.filter_by(treasury_account_id=account_id, type="withdraw").count() == 1
        expenses = Expense.query.filter(Expense.title.like(f"%HR-C{row['id']}%") | Expense.title.like(f"%فاتورة {invoice_id}%")).all()
        assert sum(e.amount for e in expenses) == 10000


def test_commission_profit_and_target_marginal_reconcile(ctx):
    client = _client(ctx)
    person_id = create_person(client, ctx)
    assert command(client, "commission.policy", {"person_id": person_id, "effective_from": "2026-01-01", "kind": "profit", "basis_points": 2500}).status_code == 200
    sale_id = invoice(ctx, 100000, 60000)
    assert command(client, "commission.assign", {"person_id": person_id, "invoice_id": sale_id}).status_code == 200
    assert get_row(client, person_id)["amount"] == 10000
    target_person = create_person(client, ctx)
    assert command(client, "commission.policy", {"person_id": target_person, "effective_from": "2026-01-01", "kind": "target", "fixed": 5000, "target": 150000}).status_code == 200
    first, second = invoice(ctx), invoice(ctx)
    for sale_id in (first, second):
        result = command(client, "commission.assign", {"person_id": target_person, "invoice_id": sale_id})
        assert result.status_code == 200, result.get_json()
    row = get_row(client, target_person)
    assert row["invoice_id"] == second and row["amount"] == 5000
    from models.invoice import Invoice
    from utils.payroll_service import sync_commission_line_for_invoice
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        sale = db.session.get(Invoice, first)
        sale.status = "ملغي"
        sync_commission_line_for_invoice(sale)
        db.session.commit()
    assert get_row(client, target_person)["amount"] == 0
