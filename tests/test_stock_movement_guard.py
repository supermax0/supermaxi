"""Database uniqueness tests for exactly-once stock movements."""

import pytest
from flask import Flask

from extensions import db
from models.delivery_agent import DeliveryAgent  # noqa: F401 - completes Invoice mapper
from models.stock_movement import StockMovement
from models.user import User  # noqa: F401 - completes template ownership mappers
from utils.stock_movement_guard import (
    StockMovementConflict,
    claim_stock_movement,
    latest_order_item_movement_key,
    next_order_item_movement_key,
)


@pytest.fixture()
def movement_app():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(app)
    with app.app_context():
        StockMovement.__table__.create(bind=db.engine, checkfirst=True)
        yield app
        db.session.remove()


def _claim(key: str, *, quantity: int = 3, details: dict | None = None):
    return claim_stock_movement(
        key,
        movement_type="order_deduct",
        direction="out",
        product_id=7,
        branch_id=2,
        quantity=quantity,
        unit_cost=100,
        source_type="invoice",
        source_id=55,
        source_line_id=9,
        details=details,
    )


def test_same_movement_key_is_applied_once(movement_app):
    with movement_app.app_context():
        first = _claim("order:55:item:9:deduct:v1")
        db.session.commit()
        second = _claim("order:55:item:9:deduct:v1")
        db.session.commit()

        assert first.applied is True
        assert second.applied is False
        assert StockMovement.query.count() == 1


def test_same_key_with_different_quantity_is_rejected(movement_app):
    with movement_app.app_context():
        _claim("order:55:item:9:deduct:v1", quantity=3)
        with pytest.raises(StockMovementConflict):
            _claim("order:55:item:9:deduct:v1", quantity=4)
        db.session.rollback()


def test_same_key_cannot_change_variant_details(movement_app):
    with movement_app.app_context():
        _claim("order:55:item:9:deduct:v1", details={"variant_color": "Black"})
        with pytest.raises(StockMovementConflict):
            _claim("order:55:item:9:deduct:v1", details={"variant_color": "White"})
        db.session.rollback()


def test_new_stock_lifecycle_gets_a_new_versioned_key(movement_app):
    with movement_app.app_context():
        first = next_order_item_movement_key(55, 9, "restore")
        assert first == "order:55:item:9:restore:v1"
        claim_stock_movement(
            first,
            movement_type="order_restore",
            direction="in",
            product_id=7,
            branch_id=2,
            quantity=3,
            unit_cost=100,
            source_type="invoice",
            source_id=55,
            source_line_id=9,
        )
        db.session.commit()

        assert latest_order_item_movement_key(55, 9, "restore") == first
        assert next_order_item_movement_key(55, 9, "restore") == "order:55:item:9:restore:v2"
