"""The redesigned pages must render their real data and keep recovered workflows."""
import json
import re
from datetime import date, timedelta

import pytest

from tests.test_page_read_safety import safety, client, money_state  # noqa: F401


def json_data(html, element_id):
    match = re.search(r'<script[^>]*id="' + element_id + r'"[^>]*>(.*?)</script>', html, re.S)
    assert match, element_id
    return json.loads(match.group(1))


@pytest.mark.parametrize("path", [
    "/orders/", "/inventory/", "/accounts/", "/cash/", "/payroll/",
    "/employees/", "/expenses/", "/shipping/", "/suppliers/", "/purchases/",
    "/purchases/new", "/reports/", "/reports/daily",
])
def test_designed_pages_render_valid_data_without_posting_money(safety, client, path):
    before = money_state(safety)
    response = client.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="fdPage"' in html or 'id="ordersFd"' in html
    for payload in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.S):
        json.loads(payload)
    assert money_state(safety) == before


def test_supplier_drawer_data_keeps_second_phone_balances_and_purchase_count(safety, client):
    from extensions import db
    from flask import g
    from models.supplier import Supplier
    from models.purchase import Purchase

    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        supplier = Supplier(name="Design supplier", phone="07700000111", phone2="07800000222",
                            branch_id=safety["branch"], opening_balance=100, total_debt=600, total_paid=200)
        db.session.add(supplier)
        db.session.flush()
        supplier_id = supplier.id
        db.session.add(Purchase(supplier_id=supplier_id, product_id=safety["product"], quantity=1,
                                price=500, total=500, status="confirmed", purchase_date=date.today(),
                                branch_id=safety["branch"]))
        db.session.commit()
    html = client.get("/suppliers/").get_data(as_text=True)
    row = next(row for row in json_data(html, "suppliersData") if row["id"] == supplier_id)
    assert (row["phone2"], row["total_debt"], row["total_paid"], row["purchases"]) == ("07800000222", 600, 200, 1)
    assert 'id="sfPhone2"' in html and 'fetch("/suppliers/api/"' in html


def test_credit_redesign_keeps_edit_backdated_payments_and_current_overdue_status(safety, client):
    from extensions import db
    from flask import g
    from models.customer import Customer
    from utils.customer_credit_service import create_credit_plan

    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        customer = Customer(name="Design credit", phone="07700000333", branch_id=safety["branch"])
        db.session.add(customer)
        db.session.flush()
        plan = create_credit_plan(customer_id=customer.id, entry_type="opening", total_amount=5000,
                                  installments_count=1, first_due_date=date.today() - timedelta(days=5),
                                  interval="monthly", description="Design opening")
        db.session.commit()
        customer_id, plan_id = customer.id, plan.id
    response = client.get(f"/customers/credit/{customer_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    data = json_data(html, "ccdData")
    assert data["plans"][0]["id"] == plan_id
    assert data["installments"][0]["status"] == "overdue"
    assert 'name="payment_date"' in html
    assert f'id="planEditDrawer{plan_id}"' in html


def test_shared_supplier_design_aggregates_branch_purchases_and_preserves_contact_edit(safety, client):
    from extensions import db
    from flask import g
    from models.branch import Branch
    from models.supplier import Supplier
    from models.purchase import Purchase
    from models.system_settings import SystemSettings

    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        settings = SystemSettings.get_settings()
        original_flags = dict(settings.get_ui_flags())
        settings.set_ui_flags({**original_flags, "legacy_shared_mode_enabled": True})
        branch = Branch(name="Design second branch", code="design-second")
        db.session.add(branch)
        db.session.flush()
        ids = []
        for branch_id in (safety["branch"], branch.id):
            supplier = Supplier(name="Design shared supplier", phone="07700000444", phone2="07800000555",
                                branch_id=branch_id, opening_balance=100, total_debt=600, total_paid=200)
            db.session.add(supplier)
            db.session.flush()
            ids.append(supplier.id)
            db.session.add(Purchase(supplier_id=supplier.id, product_id=safety["product"], quantity=1,
                                    price=500, total=500, status="confirmed", purchase_date=date.today(),
                                    branch_id=branch_id))
        db.session.commit()
    try:
        rows = json_data(client.get("/suppliers/").get_data(as_text=True), "suppliersData")
        row = next(row for row in rows if row["id"] in ids)
        assert (row["member_count"], row["opening_balance"], row["total_debt"], row["purchases"]) == (2, 200, 1200, 2)
        response = client.post(f'/suppliers/api/{row["id"]}/update', json={
            "name": row["name"], "phone": row["phone"], "phone2": "07900000666", "address": "Design address",
        })
        assert response.status_code == 200 and response.json["success"]
        with safety["app"].app_context():
            g.tenant = safety["tenant"]
            records = Supplier.query.execution_options(skip_branch_scope=True).filter(Supplier.id.in_(ids)).all()
            assert all(record.phone2 == "07900000666" and record.total_debt == 600 for record in records)
    finally:
        with safety["app"].app_context():
            g.tenant = safety["tenant"]
            SystemSettings.get_settings().set_ui_flags(original_flags)
            db.session.commit()


def test_inventory_redesign_keeps_branch_color_adjustment_and_bulk_pos_controls(client):
    html = client.get("/inventory/").get_data(as_text=True)
    assert json_data(html, "productsData")
    for field in ["filterPosVisible", "invPosBulkBar", "adjustColorName", "adjustSalePrice", "adjustBranchId"]:
        assert f'id="{field}"' in html
    assert '"branch_colors"' in html
    assert "/inventory/api/products/" in html


def test_expense_redesign_keeps_scheduled_time_and_series_editor(client):
    html = client.get("/expenses/").get_data(as_text=True)
    assert 'name="expense_time"' in html
    assert 'id="seriesModal"' in html
    assert "/expenses/api/series/" in html
