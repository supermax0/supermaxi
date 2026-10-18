"""Orders grid must page through the full result set instead of truncating at 500."""

from datetime import datetime, timedelta
from unittest.mock import patch

from flask import Flask, session


def _request_page(app, employee_id, query):
    from routes.orders import orders_data

    with app.test_request_context(f"/orders/data?{query}"):
        session["user_id"] = employee_id
        with patch("routes.orders._ensure_order_columns_and_unlock"), patch(
            "utils.order_stock_trace.build_order_stock_trace_map",
            return_value={},
        ):
            response = orders_data()
        assert response.status_code == 200, response.get_json()
        return response.get_json()


def test_orders_grid_pages_beyond_500_and_searches_all_rows():
    from extensions import db
    from models.branch import Branch
    from models.customer import Customer
    from models.delivery_agent import DeliveryAgent
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.page import Page, employee_pages
    from models.product import Product
    from models.role import Permission, Role, employee_roles
    from models.shipping import ShippingCompany
    from models.tenant import Tenant
    from models.user import User  # noqa: F401 - resolves invoice-template relationships

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="orders-pagination-test",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(app)

    with app.app_context():
        db.Model.metadata.create_all(
            db.engine,
            tables=[
                Tenant.__table__,
                ShippingCompany.__table__,
                Branch.__table__,
                Permission.__table__,
                Role.__table__,
                employee_roles,
                Employee.__table__,
                Page.__table__,
                employee_pages,
                Customer.__table__,
                Product.__table__,
                DeliveryAgent.__table__,
                Invoice.__table__,
                OrderItem.__table__,
            ],
        )
        admin = Employee(
            name="Pagination Admin",
            username="pagination_admin",
            password="pw",
            role="admin",
            is_active=True,
        )
        customer = Customer(
            name="Pagination Customer",
            phone="07700000000",
            phone2="07719000000",
            city="بغداد",
        )
        db.session.add_all([admin, customer])
        db.session.flush()
        employee_id = admin.id
        start = datetime(2026, 1, 1, 8, 0)
        invoices = []
        for index in range(505):
            invoices.append(Invoice(
                customer_id=customer.id,
                customer_name=customer.name,
                employee_id=admin.id,
                employee_name=admin.name,
                total=index + 1,
                paid_amount=0,
                status="تم الطلب",
                payment_status="غير مسدد",
                created_at=start + timedelta(minutes=index),
                barcode=f"PAGE-{index + 1:03d}",
            ))
        future_scheduled = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=admin.id,
            employee_name=admin.name,
            total=788,
            paid_amount=0,
            status="تم الطلب",
            payment_status="غير مسدد",
            created_at=start + timedelta(minutes=506),
            scheduled_date=datetime(2099, 1, 1),
            barcode="FUTURE-788",
        )
        db.session.add_all([*invoices, future_scheduled])
        db.session.commit()
        oldest_id = invoices[0].id
        future_scheduled_id = future_scheduled.id

    first = _request_page(app, employee_id, "page_type=all&page=1&page_size=100")
    assert first["total"] == 506
    assert first["total_pages"] == 6
    assert len(first["rows"]) == 100
    assert first["rows"][0]["duplicate_count"] == 506
    assert first["rows"][0]["duplicate_risk"] == "same_employee"

    sixth = _request_page(app, employee_id, "page_type=all&page=6&page_size=100")
    assert sixth["page"] == 6
    assert len(sixth["rows"]) == 6
    assert oldest_id in {row["id"] for row in sixth["rows"]}

    searched = _request_page(
        app,
        employee_id,
        f"page_type=all&page=1&page_size=100&search=PAGE-001",
    )
    assert searched["total"] == 1
    assert searched["rows"][0]["id"] == oldest_id
    assert searched["rows"][0]["phone2"] == "07719000000"

    searched_by_second_phone = _request_page(
        app,
        employee_id,
        "page_type=all&page=1&page_size=100&search=077190",
    )
    assert searched_by_second_phone["total"] == 506
    assert {row["phone2"] for row in searched_by_second_phone["rows"]} == {"07719000000"}

    future_scheduled_result = _request_page(
        app,
        employee_id,
        "page_type=ordered&page=1&page_size=100&search=FUTURE-788",
    )
    assert future_scheduled_result["total"] == 1
    assert future_scheduled_result["rows"][0]["id"] == future_scheduled_id


if __name__ == "__main__":
    test_orders_grid_pages_beyond_500_and_searches_all_rows()
    print("orders server pagination tests passed")
