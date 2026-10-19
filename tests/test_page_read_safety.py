"""Real tenant regression checks for read-only finance pages and explicit maintenance."""
import os
import json
import re
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest


@pytest.fixture(scope="module")
def safety():
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db, get_tenant_db_path, clear_tenant_engine
    from flask import g
    from models.core.tenant import Tenant as CoreTenant
    from models.tenant import Tenant
    from models.employee import Employee
    from models.customer import Customer
    from models.product import Product
    from models.account_transaction import AccountTransaction
    from utils.branch_migration import get_default_branch
    from utils.branch_stock_service import set_branch_stock
    from utils.treasury_helpers import get_default_cash_account
    from utils.order_stock_policy import set_packed_stock_deduction_policy

    slug = f"test_read_safety_{os.getpid()}_{uuid4().hex[:8]}"
    app.config["TESTING"] = True
    with app.app_context():
        g.tenant = None
        core = CoreTenant(name="Read Safety", slug=slug, db_path=get_tenant_db_path(slug), is_active=True,
                          subscription_end_date=datetime.utcnow() + timedelta(days=30))
        db.session.add(core)
        db.session.commit()
        g.tenant = slug
        init_tenant_db(slug)
        company = Tenant(name="Read Safety", subdomain=slug, plan_key="enterprise", is_active=True)
        db.session.add(company)
        db.session.flush()
        branch = get_default_branch()
        admin = Employee(name="Read Safety Admin", username="read_admin", password="unused", role="admin",
                         is_active=True, tenant_id=company.id, branch_id=branch.id, salary=1000,
                         pay_type="monthly", pay_day_of_month=date.today().day,
                         payroll_effective_from=date.today() - timedelta(days=40))
        customer = Customer(name="Read Safety Customer", phone="07700000911", branch_id=branch.id)
        product = Product(name="Read Safety Product", quantity=5, buy_price=600, sale_price=1000,
                          active=True, branch_id=branch.id)
        db.session.add_all([admin, customer, product])
        db.session.flush()
        cash = get_default_cash_account(branch.id)
        set_branch_stock(branch.id, product.id, 5)
        set_packed_stock_deduction_policy(True)
        db.session.add(AccountTransaction(type="deposit", amount=20000, treasury_account_id=cash.id,
                                          branch_id=branch.id, note="isolated opening"))
        db.session.commit()
        state = dict(app=app, tenant=slug, admin=admin.id, company=company.id, branch=branch.id,
                     customer=customer.id, product=product.id, cash=cash.id)
    yield state
    with app.app_context():
        db.session.remove()
    clear_tenant_engine(slug)


@pytest.fixture
def client(safety, monkeypatch):
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    c = safety["app"].test_client()
    with c.session_transaction() as session:
        session.update(user_id=safety["admin"], tenant_slug=safety["tenant"], role="admin",
                       tenant_id=safety["company"], branch_id=safety["branch"], view_all_branches=False)
    return c


def money_state(safety):
    from extensions import db
    from flask import g
    from models.expense import Expense
    from models.employee_payment import EmployeePayment
    from utils.treasury_calculations import calculate_treasury_balance
    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        return Expense.query.count(), EmployeePayment.query.count(), calculate_treasury_balance(safety["cash"])


def test_opening_and_refreshing_payroll_never_pays_due_salary(safety, client):
    before = money_state(safety)
    for path in ["/payroll/", "/payroll/", "/payroll/api/dashboard"]:
        response = client.get(path)
        assert response.status_code == 200, response.get_data(as_text=True)[:500]
    assert money_state(safety) == before


def test_explicit_due_salary_command_still_pays_exactly_once(safety, client):
    before = money_state(safety)
    first = client.post("/payroll/api/process-due", json={"treasury_account_id": safety["cash"]})
    assert first.status_code == 200 and first.json["paid_count"] == 1, first.json
    after = money_state(safety)
    assert after == (before[0] + 1, before[1] + 1, before[2] - 1000)
    second = client.post("/payroll/api/process-due", json={"treasury_account_id": safety["cash"]})
    assert second.status_code == 200 and second.json["paid_count"] == 0, second.json
    assert money_state(safety) == after


def seed_credit_case(safety):
    from extensions import db
    from flask import g
    from models.customer import Customer
    from models.invoice import Invoice
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment
    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        customer = Customer(name="Legacy Credit " + uuid4().hex[:6], phone=uuid4().hex[:11], branch_id=safety["branch"])
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(customer_id=customer.id, customer_name=customer.name, total=9999,
                          status="ملغي", payment_status="ملغي", branch_id=safety["branch"])
        db.session.add(invoice)
        db.session.flush()
        active = CustomerCreditPlan(customer_id=customer.id, entry_type="opening", total_amount=1000, paid_amount=0)
        voided = CustomerCreditPlan(customer_id=customer.id, entry_type="products", total_amount=9999,
                                   paid_amount=0, invoice_id=invoice.id)
        db.session.add_all([active, voided])
        db.session.flush()
        inst = CustomerInstallment(plan_id=active.id, sequence=1, amount=1000, paid_amount=0,
                                   due_date=date.today() - timedelta(days=2), status="pending")
        db.session.add(inst)
        db.session.commit()
        return customer.id, active.id, voided.id, inst.id


def test_credit_views_exclude_voided_debt_without_deleting_or_updating_history(safety, client):
    from extensions import db
    from flask import g
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment
    from utils.customer_credit_service import customer_credit_summary
    customer, active, voided, installment = seed_credit_case(safety)
    before = money_state(safety)
    for path in ["/customers/credit/", f"/customers/credit/{customer}"]:
        response = client.get(path)
        assert response.status_code == 200, response.get_data(as_text=True)[:500]
    payload = re.search(r'<script[^>]*id="ccdData"[^>]*>(.*?)</script>', response.get_data(as_text=True), re.S)
    assert payload
    assert any(row["status"] == "overdue" for row in json.loads(payload.group(1))["installments"])
    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        summary = customer_credit_summary(customer)
        assert summary["total_debt"] == 1000 and summary["overdue_count"] == 1
        assert db.session.get(CustomerCreditPlan, voided) is not None
        assert db.session.get(CustomerInstallment, installment).status == "pending"
        assert not db.session.dirty
    assert money_state(safety) == before


def test_cleanup_command_previews_then_applies_only_on_request(safety):
    from extensions import db
    from flask import g
    from models.customer_credit import CustomerCreditPlan
    _, active, voided, _ = seed_credit_case(safety)
    runner = safety["app"].test_cli_runner()
    preview = runner.invoke(args=["customer_credit", "cleanup-voided", "--tenant", safety["tenant"]])
    assert preview.exit_code == 0, preview.output
    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        assert db.session.get(CustomerCreditPlan, voided) is not None
    applied = runner.invoke(args=["customer_credit", "cleanup-voided", "--tenant", safety["tenant"], "--apply"])
    assert applied.exit_code == 0, applied.output
    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        assert db.session.get(CustomerCreditPlan, voided) is None
        assert db.session.get(CustomerCreditPlan, active) is not None


def test_deferred_pos_order_catalog_reports_unchanged_physical_stock(safety, client):
    response = client.post("/pos/create-order", json={
        "customer_id": safety["customer"], "branch_id": safety["branch"],
        "items": [{"product_id": safety["product"], "qty": 1, "price": 1000}],
        "submission_token": uuid4().hex,
    })
    assert response.status_code == 200 and response.json["success"], response.json
    catalog = client.get("/pos/all-products")
    assert catalog.status_code == 200
    product = next(p for p in catalog.json["products"] if p["id"] == safety["product"])
    assert product["quantity"] == 5
