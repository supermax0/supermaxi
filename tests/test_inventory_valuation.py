from flask import Flask
from sqlalchemy import text

from extensions import db
from utils.accounting_calculations import calculate_inventory_value


def test_inventory_value_uses_current_quantity_and_product_purchase_price():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    with app.app_context():
        db.session.execute(
            text(
                "CREATE TABLE product ("
                "id INTEGER PRIMARY KEY, quantity INTEGER, buy_price INTEGER)"
            )
        )
        db.session.execute(
            text(
                "INSERT INTO product (id, quantity, buy_price) "
                "VALUES (1, 4, 250), (2, 3, 400)"
            )
        )

        assert calculate_inventory_value() == (4 * 250) + (3 * 400)
