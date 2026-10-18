"""POS my-orders period filter defaults to the current month."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_pos_my_orders_{os.getpid()}"


def _fresh_tenant_db():
    try:
        from extensions import db
        db.session.remove()
    except Exception:
        pass
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def _seed():
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from utils.branch_migration import get_default_branch

    g.tenant = TENANT
    init_tenant_db(TENANT)
    branch = get_default_branch()
    customer = Customer(branch_id=branch.id, name="زبون الفترة", phone="07701112233")
    employee = Employee(
        name="كاشير طلباتي",
        username="my-orders-cashier",
        password="x",
        role="cashier",
        is_active=True,
        branch_id=branch.id,
    )
    product = Product(
        branch_id=branch.id,
        name="شاشة اختبار",
        buy_price=10,
        sale_price=100,
        quantity=10,
        active=True,
    )
    db.session.add_all([customer, employee, product])
    db.session.flush()

    now = datetime.utcnow()
    last_month = (now.replace(day=1) - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    this_month = Invoice(
        customer_id=customer.id,
        customer_name=customer.name,
        employee_id=employee.id,
        employee_name=employee.name,
        total=100,
        status="تم الطلب",
        payment_status="غير مسدد",
        paid_amount=0,
        branch_id=branch.id,
        created_at=now,
    )
    previous_month = Invoice(
        customer_id=customer.id,
        customer_name=customer.name,
        employee_id=employee.id,
        employee_name=employee.name,
        total=200,
        status="تم التوصيل",
        payment_status="مسدد",
        paid_amount=200,
        branch_id=branch.id,
        created_at=last_month,
    )
    db.session.add_all([this_month, previous_month])
    db.session.flush()
    db.session.add_all([
        OrderItem(
            invoice_id=this_month.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            price=100,
            cost=10,
            total=100,
            fulfillment_branch_id=branch.id,
        ),
        OrderItem(
            invoice_id=previous_month.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            price=200,
            cost=10,
            total=200,
            fulfillment_branch_id=branch.id,
        ),
    ])
    db.session.commit()
    return employee.id, this_month.id, previous_month.id


def _render_my_orders(app, employee_id, query=""):
    from flask import g, session
    from routes.pos import my_orders

    with app.test_request_context(f"/pos/my-orders{query}"):
        g.tenant = TENANT
        session["user_id"] = employee_id
        result = my_orders()
        return result.get_data(as_text=True) if hasattr(result, "get_data") else result


def test_my_orders_defaults_to_current_month():
    _fresh_tenant_db()
    from app import app

    with app.app_context():
        employee_id, this_month_id, last_month_id = _seed()

    html = _render_my_orders(app, employee_id)
    assert 'value="this_month" selected' in html
    assert "هذا الشهر" in html
    assert f">{this_month_id}</span>" in html
    assert f">{last_month_id}</span>" not in html


def test_my_orders_all_periods_includes_previous_month():
    _fresh_tenant_db()
    from app import app

    with app.app_context():
        employee_id, this_month_id, last_month_id = _seed()

    html = _render_my_orders(app, employee_id, "?period_type=all")
    assert f">{this_month_id}</span>" in html
    assert f">{last_month_id}</span>" in html
    assert "كل الفترات" in html


def test_my_orders_last_month_hides_current_month():
    _fresh_tenant_db()
    from app import app

    with app.app_context():
        employee_id, this_month_id, last_month_id = _seed()

    html = _render_my_orders(app, employee_id, "?period_type=last_month")
    assert f">{last_month_id}</span>" in html
    assert f">{this_month_id}</span>" not in html
