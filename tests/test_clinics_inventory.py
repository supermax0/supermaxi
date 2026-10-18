"""Medical inventory workflow regression tests."""
from datetime import date, timedelta

import pytest
from flask import Flask

from extensions import db


@pytest.fixture()
def inventory_db():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="inventory-test",
    )
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.clinics.models import CLINIC_MODELS  # noqa: F401
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_purchase_requires_receipt_before_stock_changes(inventory_db):
    from modules.clinics.models import ClinicInventoryMovement, ClinicPurchaseReceipt
    from modules.clinics.service_ops import create_inventory_item, inventory_item_detail, issue_stock
    from modules.clinics.service_suppliers import create_purchase, create_supplier, receive_purchase

    with inventory_db.app_context():
        supplier = create_supplier(1, {"name": "المورد الطبي"})
        item = create_inventory_item(1, {
            "name": "قفازات طبية", "unit": "علبة", "batch_tracking": True,
            "expiry_tracking": True, "minimum_stock": 2,
        })
        purchase = create_purchase(1, {
            "supplier_id": supplier["id"],
            "items": [{"item_id": item["id"], "quantity": 10, "unit_cost": 1000}],
        })
        assert purchase["receipt_status"] == "pending"
        assert inventory_item_detail(1, item["id"])["item"]["current_stock"] == 0
        line_id = purchase["items"][0]["id"]

        first = receive_purchase(1, purchase["id"], {"items": [{
            "purchase_item_id": line_id, "quantity": 4, "batch_number": "B-001",
            "expiry_date": (date.today() + timedelta(days=60)).isoformat(), "unit_cost": 1000,
        }]})
        assert first["receipt_status"] == "partial"
        assert first["items"][0]["remaining_quantity"] == 6

        second = receive_purchase(1, purchase["id"], {"items": [{
            "purchase_item_id": line_id, "quantity": 6, "batch_number": "B-002",
            "expiry_date": (date.today() + timedelta(days=120)).isoformat(), "unit_cost": 2000,
        }]})
        assert second["receipt_status"] == "complete"
        detail = inventory_item_detail(1, item["id"])
        assert detail["item"]["current_stock"] == 10
        assert detail["item"]["average_cost"] == 1600
        assert ClinicPurchaseReceipt.query.count() == 2

        issue_stock(1, item["id"], {"quantity": 3, "reason": "procedure"})
        detail = inventory_item_detail(1, item["id"])
        assert detail["item"]["current_stock"] == 7
        latest = ClinicInventoryMovement.query.order_by(ClinicInventoryMovement.id.desc()).first()
        assert float(latest.stock_before) == 10
        assert float(latest.stock_after) == 7
        db.session.commit()


def test_expired_batch_is_not_issued(inventory_db):
    from modules.clinics.service_ops import create_inventory_item, issue_stock, stock_in

    with inventory_db.app_context():
        item = create_inventory_item(1, {
            "name": "مادة منتهية", "batch_tracking": True, "expiry_tracking": True,
        })
        stock_in(1, item["id"], {
            "quantity": 2, "batch_number": "EXP-1",
            "expiry_date": (date.today() - timedelta(days=1)).isoformat(),
        })
        with pytest.raises(ValueError, match="الدفعات"):
            issue_stock(1, item["id"], {"quantity": 1, "reason": "internal_use"})
        db.session.rollback()
