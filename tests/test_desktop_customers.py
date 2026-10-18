"""Real customer workspace reads: accounting parity, isolation and no GET writes."""
import os
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def workspace():
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db, clear_tenant_engine
    from flask import g, session
    from models.branch import Branch
    from models.employee import Employee
    from models.role import Role
    from models.customer import Customer
    from models.invoice import Invoice
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment
    from modules.desktop_api import customers
    tenant = f"test_desktop_customers_{os.getpid()}_{uuid4().hex[:8]}"
    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        branches = [Branch(code="C1", name="الأول", is_active=True, is_default=True),
                    Branch(code="C2", name="الثاني", is_active=True)]
        db.session.add_all(branches)
        db.session.flush()
        admin = Employee(name="Admin", username=uuid4().hex, password="test", role="admin", is_active=True, branch_id=branches[0].id)
        staff = Employee(name="Staff", username=uuid4().hex, password="test", role="cashier", is_active=True, branch_id=branches[0].id)
        staff.roles = [Role(name="customer-workspace-denied-" + uuid4().hex[:8])]
        rows = [Customer(name="أحمد", phone="07700000001", branch_id=branches[0].id),
                Customer(name="شركة ثانية", phone="07700000002", branch_id=branches[1].id)]
        db.session.add_all([admin, staff, *rows])
        db.session.flush()
        invoice = Invoice(customer_id=rows[0].id, customer_name=rows[0].name, branch_id=branches[0].id,
                          total=300000, paid_amount=100000, payment_status="جزئي", status="تم التوصيل", is_stock_locked=False)
        voided = Invoice(customer_id=rows[0].id, customer_name=rows[0].name, branch_id=branches[0].id,
                         total=900000, payment_status="مرتجع", status="مرتجع", is_stock_locked=False)
        db.session.add_all([invoice, voided])
        db.session.flush()
        plans = [CustomerCreditPlan(customer_id=rows[0].id, invoice_id=invoice.id, entry_type="products", total_amount=300000, paid_amount=100000),
                 CustomerCreditPlan(customer_id=rows[0].id, entry_type="opening", total_amount=50000),
                 CustomerCreditPlan(customer_id=rows[0].id, invoice_id=voided.id, entry_type="products", total_amount=900000)]
        db.session.add_all(plans)
        db.session.flush()
        for index, plan in enumerate(plans):
            db.session.add(CustomerInstallment(plan_id=plan.id, sequence=1, amount=plan.remaining,
                                              due_date=date.today()-timedelta(days=2), status="pending"))
        db.session.commit()

        def get(path, employee=admin, all_branches=True, authenticated=True, shared=False, method="GET", body=None, session_tenant=None):
            with app.test_request_context(path, method=method, json=body):
                g.tenant = tenant
                if authenticated:
                    session.update(user_id=employee.id, tenant_slug=session_tenant or tenant, role=employee.role)
                g.branch = branches[0]
                g.branches = branches
                g.view_all_branches = all_branches
                g.independent_branches_enabled = not shared
                g.branch_scope_ready = True
                endpoint, kwargs = app.url_map.bind("localhost").match(path.split("?")[0], method=method)
                return app.make_response(app.view_functions[endpoint](**kwargs))

        yield {"get": get, "admin": admin, "staff": staff, "rows": rows, "plans": plans, "db": db, "module": customers}
        db.session.remove()
    clear_tenant_engine(tenant)
    (Path(__file__).resolve().parents[1]/"tenants"/f"{tenant}.db").unlink(missing_ok=True)


def test_customer_debt_counts_linked_principal_once_and_get_preserves_history(workspace):
    f = workspace
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment
    before = [(row.id, row.status, row.paid_amount) for row in CustomerInstallment.query.order_by(CustomerInstallment.id)]
    data = f["get"]("/api/v1/desktop/customers").get_json()["data"]
    assert data["stats"] == {"customers": 2, "debt": 250000, "overdue": 250000, "debtors": 1}
    detail = f["get"](f'/api/v1/desktop/customers/{f["rows"][0].id}').get_json()["data"]
    assert detail["debt"] == 250000
    history = f["get"](f'/api/v1/desktop/customers/{detail["id"]}/history?kind=installments').get_json()["data"]
    assert history["total"] == 2
    assert all(row["status"] == "overdue" for row in history["items"])
    assert CustomerCreditPlan.query.count() == 3  # voided history was not deleted by GET
    assert before == [(row.id, row.status, row.paid_amount) for row in CustomerInstallment.query.order_by(CustomerInstallment.id)]


def test_customers_require_auth_and_permission_and_validate_filters(workspace, monkeypatch):
    f = workspace
    assert f["get"]("/api/v1/desktop/customers", authenticated=False).status_code == 401
    assert f["get"]("/api/v1/desktop/customers", employee=f["staff"]).status_code == 403
    assert f["get"]("/api/v1/desktop/customers", session_tenant="different-company").status_code == 403
    f["admin"].is_active = False
    assert f["get"]("/api/v1/desktop/customers").status_code == 401
    f["admin"].is_active = True
    for query in ("page=0", "page_size=200", "tab=unknown", "q=" + "x"*151):
        assert f["get"]("/api/v1/desktop/customers?"+query).status_code == 400
    assert f["get"]("/api/v1/desktop/customers?q=%25").get_json()["data"]["total"] == 0
    assert f["get"]("/api/v1/desktop/customers?tab=debt").get_json()["data"]["total"] == 1
    assert f["get"]("/api/v1/desktop/customers?tab=settled").get_json()["data"]["total"] == 1


def test_current_statement_matches_debt_without_duplicate_or_voided_principal(workspace):
    f = workspace
    customer_id = f["rows"][0].id
    path = f"/api/v1/desktop/customers/{customer_id}/history?kind=receivables"
    response = f["get"](path)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] == 2
    assert data["summary"] == {"total": 350000, "paid": 100000, "remaining": 250000}
    assert {row["kind"] for row in data["items"]} == {"invoice", "credit_plan"}
    assert sum(row["remaining"] for row in data["items"]) == 250000
    assert len([row for row in data["items"] if row["invoice_id"] is not None]) == 1
    assert f["get"](path+"&page=2").get_json()["data"]["items"] == []
    assert f["get"](path+"&page=2").get_json()["data"]["summary"] == data["summary"]
    empty = f["get"](f'/api/v1/desktop/customers/{f["rows"][1].id}/history?kind=receivables').get_json()["data"]
    assert empty["items"] == []
    assert empty["summary"] == {"total": 0, "paid": 0, "remaining": 0}


def test_statement_print_has_all_pages_escapes_names_and_checks_permission(workspace):
    f = workspace
    from models.customer_credit import CustomerCreditPlan
    customer = f["rows"][0]
    customer.name = '<script>alert("unsafe")</script>'
    for number in range(30):
        f["db"].session.add(CustomerCreditPlan(customer_id=customer.id, entry_type="manual",
            description=f"print-document-{number}", total_amount=1000))
    f["db"].session.commit()
    path = f"/api/v1/desktop/customers/{customer.id}/statement/print"
    assert f["get"](path, authenticated=False).status_code == 401
    assert f["get"](path, employee=f["staff"]).status_code == 403
    html = f["get"](path).get_data(as_text=True)
    assert '<script>alert("unsafe")</script>' not in html
    assert "&lt;script&gt;" in html
    assert all(f"print-document-{number}" in html for number in range(30))
    assert "280,000" in html
    assert f["get"](f'/api/v1/desktop/customers/{f["rows"][1].id}/statement/print', all_branches=False).status_code == 404
    from pathlib import Path
    output = Path(__file__).resolve().parents[1]/"tests"/"_artifacts"/"erp-customers"
    output.mkdir(parents=True, exist_ok=True)
    from models.customer import Customer
    customer = Customer.query.filter_by(id=customer.id).one()
    customer.name = "أحمد — اختبار الطباعة"
    f["db"].session.commit()
    sample = f["get"](path).get_data(as_text=True)
    assert "أحمد — اختبار الطباعة" in sample
    assert "&lt;script&gt;" not in sample
    (output/"statement-real.html").write_text(sample, encoding="utf-8")


def test_customer_detail_history_and_totals_are_branch_scoped(workspace, monkeypatch):
    f = workspace
    monkeypatch.setattr(f["module"], "employee_can", lambda employee, permission: True)
    list_data = f["get"]("/api/v1/desktop/customers", employee=f["staff"]).get_json()["data"]
    assert list_data["total"] == 1
    other = f["rows"][1].id
    assert f["get"](f"/api/v1/desktop/customers/{other}", employee=f["staff"]).status_code == 404
    assert f["get"](f"/api/v1/desktop/customers/{other}/history", employee=f["staff"]).status_code == 404
    assert f["get"](f"/api/v1/desktop/customers/{other}/history?kind=receivables", employee=f["staff"]).status_code == 404
    assert f["get"]("/api/v1/desktop/customers", all_branches=False).get_json()["data"]["total"] == 1
    assert f["get"]("/api/v1/desktop/customers", employee=f["staff"], shared=True).get_json()["data"]["total"] == 2


def test_profile_create_retry_edit_conflict_and_audit_are_atomic(workspace):
    f = workspace
    from models.customer import Customer
    from models.activity_log import ActivityLog
    from modules.desktop_api.sync import DesktopSyncReceipt
    path = "/api/v1/desktop/customers/commands"
    fields = {"name": "عميل جديد", "phone": "07712345678", "phone2": "", "city": "بغداد", "address": "", "notes": ""}
    create = {"operation": "create", "idempotency_key": str(uuid4()), "data": fields}
    first = f["get"](path, method="POST", body=create)
    assert first.status_code == 200
    created = first.get_json()["data"]
    from models.branch import Branch
    assert f["db"].session.get(Branch, created["branch_id"]).is_active
    count_after_create = Customer.query.count()
    assert f["get"](path, method="POST", body=create).get_json() == first.get_json()
    assert Customer.query.count() == count_after_create
    assert Customer.query.filter_by(name="عميل جديد").count() == 1
    assert ActivityLog.query.filter_by(category="customers").count() == 1
    assert f["get"](path, method="POST", body={**create, "data": {**fields, "name": "اسم آخر"}}).status_code == 409
    update = {"operation": "update", "idempotency_key": str(uuid4()), "id": created["id"], "revision": created["revision"],
              "data": {**fields, "name": "عميل معدل"}}
    edited = f["get"](path, method="POST", body=update)
    assert edited.status_code == 200
    assert edited.get_json()["data"]["name"] == "عميل معدل"
    assert f["get"](path, method="POST", body=update).get_json() == edited.get_json()
    assert f["get"](path, method="POST", body={**update, "idempotency_key": str(uuid4())}).status_code == 409
    assert Customer.query.filter_by(id=created["id"]).one().name == "عميل معدل"
    assert ActivityLog.query.filter_by(category="customers").count() == 2
    assert DesktopSyncReceipt.query.count() == 2


def test_profile_command_rejects_foreign_records_and_financial_fields(workspace, monkeypatch):
    f = workspace
    monkeypatch.setattr(f["module"], "employee_can", lambda employee, permission: True)
    row = f["rows"][1]
    data = {"name": "ممنوع", "phone": "07712345678", "phone2": "", "city": "", "address": "", "notes": ""}
    update = {"operation": "update", "idempotency_key": str(uuid4()), "id": row.id,
              "revision": f["module"]._revision(row), "data": data}
    path = "/api/v1/desktop/customers/commands"
    assert f["get"](path, method="POST", body=update, employee=f["staff"]).status_code == 404
    assert f["get"](path, method="POST", body={**update, "branch_id": 1}).status_code == 400
    assert f["get"](path, method="POST", body={**update, "data": {**data, "debt": 0}}).status_code == 400
    assert f["get"](path, method="POST", body={**update, "data": {**data, "phone": "x"}}).status_code == 400
    assert row.name == "شركة ثانية"


def test_profile_failure_rolls_back_profile_audit_and_replay_receipt(workspace, monkeypatch):
    f = workspace
    from models.activity_log import ActivityLog
    from models.customer import Customer
    from models.invoice import Invoice
    from modules.desktop_api.sync import DesktopSyncReceipt
    row = f["rows"][0]
    original = f["module"]._profile(row)
    invoice_balances = [(invoice.id, invoice.total, invoice.paid_amount) for invoice in Invoice.query.order_by(Invoice.id)]
    command = {"operation": "update", "idempotency_key": str(uuid4()), "id": row.id,
        "revision": f["module"]._revision(row), "data": {**original, "name": "اسم يجب التراجع عنه"}}
    path = "/api/v1/desktop/customers/commands"
    with monkeypatch.context() as patch:
        def failed_audit(*args, **kwargs):
            raise RuntimeError("simulated audit persistence failure")
        patch.setattr(ActivityLog, "set_payload", failed_audit)
        with pytest.raises(RuntimeError, match="simulated audit"):
            f["get"](path, method="POST", body=command)
    assert f["module"]._profile(Customer.query.filter_by(id=row.id).one()) == original
    assert ActivityLog.query.filter_by(category="customers").count() == 0
    assert DesktopSyncReceipt.query.filter_by(operation_id=command["idempotency_key"]).count() == 0
    assert invoice_balances == [(invoice.id, invoice.total, invoice.paid_amount) for invoice in Invoice.query.order_by(Invoice.id)]
    # A failed transaction must not consume the key or prevent an exact retry.
    retried = f["get"](path, method="POST", body=command)
    assert retried.status_code == 200
    assert retried.get_json()["data"]["name"] == "اسم يجب التراجع عنه"
    assert DesktopSyncReceipt.query.filter_by(operation_id=command["idempotency_key"]).count() == 1
