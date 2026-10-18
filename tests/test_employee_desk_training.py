"""Academy authorization and selling-data boundaries, using an isolated memory DB."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from extensions import db
from models.product import Product
from models.delivery_agent import DeliveryAgent  # noqa: F401 — complete Invoice's relationship registry
from modules.employee_desk import routes as desk


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def academy_app(monkeypatch):
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.config.update(TESTING=True, SECRET_KEY="test-only", SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    db.init_app(app)
    app.register_blueprint(desk.employee_desk_bp)
    from modules.ai_sales import schema
    monkeypatch.setattr(schema, "ensure_ai_sales_schema", lambda: None)
    with app.app_context():
        Product.__table__.create(db.engine)
        yield app
        db.session.remove()


def viewer(monkeypatch, *, allowed=True):
    employee = SimpleNamespace(id=11, name="متدرّب", role="cashier", profile_pic=None)
    monkeypatch.setattr(desk, "_employee", lambda: employee)
    from utils import permission_checks
    monkeypatch.setattr(permission_checks, "employee_can", lambda emp, permission: allowed and emp is employee and permission == "use_employee_desk")
    return employee


def signed_client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 11
        session["tenant_id"] = 7
    return client


@pytest.mark.parametrize("path", ["/employee-desk/training", "/api/employee-desk/training/products"])
def test_training_requires_session(academy_app, path):
    assert academy_app.test_client().get(path).status_code == 401


@pytest.mark.parametrize("path", ["/employee-desk/training", "/api/employee-desk/training/products"])
def test_training_requires_desk_permission(academy_app, monkeypatch, path):
    viewer(monkeypatch, allowed=False)
    assert signed_client(academy_app).get(path).status_code == 403


def test_training_scope_is_per_company_and_user_and_private(academy_app, monkeypatch):
    viewer(monkeypatch)
    response = signed_client(academy_app).get("/employee-desk/training")
    assert response.status_code == 200
    assert '"scope": "7:11"' in response.get_data(as_text=True)
    assert response.headers["Cache-Control"] == "private, no-store"
    client = signed_client(academy_app)
    with client.session_transaction() as session:
        session["tenant_id"] = 8
    assert '"scope": "8:11"' in client.get("/employee-desk/training").get_data(as_text=True)


def test_catalog_only_exposes_public_selling_fields(academy_app, monkeypatch):
    employee = viewer(monkeypatch)
    from utils import product_color_service, trade_in_service
    monkeypatch.setattr(trade_in_service, "employee_can_access_replacement_product", lambda emp, product: emp is employee)
    monkeypatch.setattr(product_color_service, "colors_for_product_dict", lambda product: {
        "colors": [{"name": "أسود", "sale_price": 27000, "buy_price": 12000, "buy_price_set": True}],
        "dual_region_pricing": True, "governorate_sale_price": 28000, "primary_province": "بغداد",
        "internal_field": "private", "option_axes": {"unexpected": "private"},
    })
    db.session.add_all([
        Product(name="مرئي", sku="PUB", buy_price=12000, sale_price=25000, active=True, pos_visible=True,
                description="وصف معتمد", meta_json=json.dumps({"specs_items": [{"label": "القياس", "value": "40 سم"}], "private_note": "never expose"})),
        Product(name="مخفي", buy_price=10, sale_price=20, active=True, pos_visible=False),
        Product(name="موقف", buy_price=10, sale_price=20, active=False, pos_visible=True),
    ])
    db.session.commit()
    response = signed_client(academy_app).get("/api/employee-desk/training/products?q=PUB")
    assert response.status_code == 200
    rows = response.get_json()["products"]
    assert len(rows) == 1
    assert rows[0]["description"] == "وصف معتمد"
    assert rows[0]["specs"] == [{"label": "القياس", "value": "40 سم"}]
    assert rows[0]["colors"] == [{"name": "أسود", "sale_price": 27000}]
    assert rows[0]["governorate_sale_price"] == 28000
    assert not {"buy_price", "meta_json", "internal_field", "option_axes"} & rows[0].keys()
    assert "never expose" not in response.get_data(as_text=True)
    assert response.headers["Cache-Control"] == "private, no-store"
    # The existing desk search retains its response contract.
    original = signed_client(academy_app).get("/api/employee-desk/products?q=PUB").get_json()["products"][0]
    assert "description" not in original and "specs" not in original


def test_restricted_products_are_excluded_and_access_errors_fail_closed(academy_app, monkeypatch):
    viewer(monkeypatch)
    from utils import trade_in_service
    db.session.add(Product(name="restricted", buy_price=10, sale_price=20, active=True, pos_visible=True))
    db.session.commit()
    monkeypatch.setattr(trade_in_service, "employee_can_access_replacement_product", lambda *_: False)
    assert signed_client(academy_app).get("/api/employee-desk/training/products").get_json()["products"] == []
    def failed_access(*_):
        raise RuntimeError("Access service unavailable")
    monkeypatch.setattr(trade_in_service, "employee_can_access_replacement_product", failed_access)
    with pytest.raises(RuntimeError, match="Access service unavailable"):
        signed_client(academy_app).get("/api/employee-desk/training/products")


@pytest.mark.parametrize("raw_meta", ["{broken-json", "[]"])
def test_missing_description_and_invalid_metadata_are_not_invented(academy_app, monkeypatch, raw_meta):
    viewer(monkeypatch)
    from utils import product_color_service, trade_in_service
    monkeypatch.setattr(trade_in_service, "employee_can_access_replacement_product", lambda *_: True)
    monkeypatch.setattr(product_color_service, "colors_for_product_dict", lambda *_: {})
    db.session.add(Product(name="بدون وصف", buy_price=10, sale_price=20, active=True, pos_visible=True, meta_json=raw_meta))
    db.session.commit()
    row = signed_client(academy_app).get("/api/employee-desk/training/products").get_json()["products"][0]
    assert row["description"] == ""
    assert row["specs"] == []
    assert row["colors"] == []
