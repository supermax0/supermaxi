"""Real checkout and printable routes, using isolated tenant records and RBAC."""
import json
from pathlib import Path

import pytest
from tests.test_desktop_product_colors import inventory  # noqa: F401


@pytest.mark.parametrize("actor", ["cashier", "admin"])
def test_checkout_single_and_batch_print_with_product_options(inventory, monkeypatch, actor):
    from flask import current_app, session
    from extensions import db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.invoice_settings import InvoiceSettings
    from models.role import Permission, Role
    from routes.pos import create_order
    import routes.orders as orders
    from utils.permission_checks import employee_can

    product, stock, update, inventory_routes = inventory
    monkeypatch.setattr(inventory_routes, "check_permission", lambda _: True)
    product.name = "قميص اختبار الطباعة"
    option = "اللون: أسود / المقاس: L"
    payload = {"axes": ["اللون", "المقاس"], "expected_stock": 6, "rows": [
        {"name": "اللون: أبيض / المقاس: M", "attributes": {"اللون": "أبيض", "المقاس": "M"}, "qty": 2, "sale_price": 180},
        {"name": option, "attributes": {"اللون": "أسود", "المقاس": "L"}, "qty": 4, "sale_price": 250},
    ]}
    body, status = update({"product_options": json.dumps(payload)})
    assert status == 200, body
    customer = Customer(branch_id=product.branch_id, name="زبون اختبار الطباعة", phone="07700000123", city="بغداد", address="عنوان تجريبي")
    employee = Employee(branch_id=product.branch_id, name=f"Print {actor}", username=f"print_{actor}", password="test-only", role=actor, is_active=True)
    view_pos = Permission.query.filter_by(name="view_pos").first()
    if not view_pos:
        view_pos = Permission(name="view_pos", description="Test POS")
        db.session.add(view_pos)
    role = Role(name=f"print_test_{actor}", description="Isolated print test")
    role.permissions.append(view_pos)
    employee.roles.append(role)
    db.session.add_all([customer, employee])
    settings = InvoiceSettings.get_settings()
    settings.company_name = "FINORA — اختبار الطباعة"
    settings.warranty_notes = "فاتورة تجريبية للتحقق من الطباعة"
    db.session.commit()
    assert employee_can(employee, "print_pos_invoice")
    # Choose the built-in template explicitly without consulting live core settings.
    monkeypatch.setattr(orders, "_tenant_invoice_template_bundle", lambda: ("invoice.html", {}))
    ids = []
    for qty in [2, 1]:
        with current_app.test_request_context("/pos/create-order", method="POST", json={
            "customer_id": customer.id, "branch_id": product.branch_id, "discount_amount": 25,
            "items": [{"product_id": product.id, "qty": qty, "color": option, "price": 250}],
        }):
            session["user_id"] = employee.id
            response = create_order()
            response, status = response if isinstance(response, tuple) else (response, 200)
            assert status == 200, response.get_json()
            data = response.get_json()
            assert data["success"], data
            ids.append(data["invoice_id"])
    first = db.session.get(Invoice, ids[0])
    assert first.total == 475 and first.discount_amount == 25
    first.paid_amount = 100
    first.payment_status = "جزئي"
    db.session.commit()
    before_stock = (product.quantity, stock.quantity)
    artifacts = Path(__file__).parent / "_artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    for mode, path, view in [
        ("single", f"/orders/invoice/{ids[0]}", lambda: orders.invoice_page(ids[0])),
        ("batch", f"/orders/print-invoices?ids={ids[0]},{ids[1]}", orders.print_invoices),
    ]:
        with current_app.test_request_context(path):
            session["user_id"] = employee.id
            result = view()
            assert isinstance(result, str), result
            assert product.name in result and option in result and customer.name in result
            assert "475.00" in result and "25.00" in result and "375.00" in result
            assert 'data:image/svg+xml;base64,' in result and 'alt="QR رابط الفاتورة"' in result
            if mode == "batch":
                assert result.count('class="invoice-frame-wrap"') == 2
                assert "225.00" in result
            (artifacts / f"invoice-print-{actor}-{mode}.html").write_text(result, encoding="utf-8")
    assert (product.quantity, stock.quantity) == before_stock
    (artifacts / f"invoice-print-{actor}-expected.json").write_text(json.dumps({
        "ids": ids, "product": product.name, "option": option, "totals": [475, 225], "due": 375,
    }, ensure_ascii=False), encoding="utf-8")
    # A logged-in employee without print permission receives an explicit refusal.
    denied_employee = Employee(name="No Print", username="no_print", password="test-only", role="employee", is_active=True, branch_id=product.branch_id)
    db.session.add(denied_employee); db.session.commit()
    for view in [lambda: orders.invoice_page(ids[0]), orders.print_invoices]:
        with current_app.test_request_context(f"/orders/print-invoices?ids={ids[0]}&finora_embed=1"):
            session["user_id"] = denied_employee.id
            denied = view()
            assert denied[1] == 403 and "data-finora-print-blocked" in denied[0]
