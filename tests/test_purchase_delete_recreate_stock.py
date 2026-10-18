"""Regression helpers for purchase stock_revision allocation after SQLite id reuse."""

from types import SimpleNamespace

import pytest
from flask import Flask

from extensions import db
from models.delivery_agent import DeliveryAgent  # noqa: F401
from models.stock_movement import StockMovement
from models.user import User  # noqa: F401
from utils.stock_movement_guard import StockMovementConflict, claim_stock_movement


@pytest.fixture()
def purchase_movement_app():
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


def test_allocate_skips_orphaned_purchase_revision(purchase_movement_app):
    import routes.purchases as purchases

    with purchase_movement_app.app_context():
        claim_stock_movement(
            "purchase:83:revision:1:item:135:receive",
            movement_type="purchase_receive",
            direction="in",
            product_id=7,
            branch_id=2,
            quantity=2,
            unit_cost=100,
            source_type="purchase",
            source_id=83,
            source_line_id=135,
        )
        claim_stock_movement(
            "purchase:83:revision:1:item:135:reverse",
            movement_type="purchase_reverse",
            direction="out",
            product_id=7,
            branch_id=2,
            quantity=2,
            unit_cost=100,
            source_type="purchase",
            source_id=83,
            source_line_id=135,
            reversal_of_key="purchase:83:revision:1:item:135:receive",
        )
        db.session.commit()

        assert purchases._max_recorded_purchase_stock_revision(83) == 1
        assert purchases._allocate_purchase_stock_revision(83) == 2


def test_apply_receive_recovers_from_orphaned_key_conflict(purchase_movement_app, monkeypatch):
    import routes.purchases as purchases

    with purchase_movement_app.app_context():
        claim_stock_movement(
            "purchase:83:revision:1:item:135:receive",
            movement_type="purchase_receive",
            direction="in",
            product_id=7,
            branch_id=2,
            quantity=2,
            unit_cost=100,
            source_type="purchase",
            source_id=83,
            source_line_id=135,
        )
        db.session.commit()

        received = []
        monkeypatch.setattr(
            purchases,
            "receive_stock",
            lambda *args: received.append(args),
        )

        purchase = SimpleNamespace(id=83, stock_revision=1)
        product = SimpleNamespace(id=9, name="New", quantity=0)
        item = SimpleNamespace(
            id=135,
            product=product,
            quantity=5,
            final_unit_cost=250,
            variant_color=None,
        )

        with pytest.raises(StockMovementConflict):
            claim_stock_movement(
                "purchase:83:revision:1:item:135:receive",
                movement_type="purchase_receive",
                direction="in",
                product_id=9,
                branch_id=2,
                quantity=5,
                unit_cost=250,
                source_type="purchase",
                source_id=83,
                source_line_id=135,
            )
        db.session.rollback()

        applied = purchases._apply_purchase_item_stock(
            purchase,
            item,
            branch_id=2,
            apply_stock=True,
        )

        assert applied is True
        assert int(purchase.stock_revision) == 2
        assert received == [(2, 9, 5)]
        assert StockMovement.query.filter_by(
            movement_key="purchase:83:revision:2:item:135:receive"
        ).first()
