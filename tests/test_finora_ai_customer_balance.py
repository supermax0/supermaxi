"""Read-only retail balance parity and linked-credit deduplication."""
from datetime import datetime
from unittest.mock import patch
from flask import Flask, g
from sqlalchemy import create_engine
from extensions import db
import models
from models.delivery_agent import DeliveryAgent
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan
from models.invoice import Invoice
from modules.finora_ai.services import get_customer_balance


def test_balance_excludes_invalid_invoices_and_does_not_double_count_credit():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    db.init_app(app)
    engine = create_engine("sqlite:///:memory:")
    with app.app_context(), patch("extensions_tenant.get_tenant_engine", return_value=engine):
        db.Model.metadata.create_all(engine)
        g.tenant = "balance-test"
        db.session.add(Customer(name="Synthetic", phone="0770"))
        db.session.flush()
        def invoice(**changes):
            values = dict(customer_id=1, customer_name="Synthetic", total=500000, paid_amount=200000,
                          status="تم الطلب", payment_status="جزئي")
            values.update(changes)
            row = Invoice(**values)
            db.session.add(row)
            return row
        linked_invoice = invoice()
        invoice(is_draft=True)
        invoice(deleted_at=datetime.utcnow())
        invoice(status="ملغي")
        invoice(status="مرتجع")
        invoice(source_module="wholesale")
        invoice(total=100000, paid_amount=0, payment_status="مسدد")
        db.session.flush()
        linked = CustomerCreditPlan(customer_id=1, invoice_id=linked_invoice.id,
                                    entry_type="products", total_amount=500000, paid_amount=200000)
        unlinked = CustomerCreditPlan(customer_id=1, entry_type="opening", total_amount=150000, paid_amount=50000)
        db.session.add_all([linked, unlinked])
        db.session.commit()
        result = get_customer_balance({"customer_id": 1}, {})
        assert result["invoice_balance_due"] == 300000
        assert result["unlinked_credit_balance_due"] == 100000
        assert result["balance_due"] == 400000
        assert result["invoiced"] == 600000
        assert not db.session.dirty and not db.session.new
        assert linked.paid_amount == 200000 and unlinked.paid_amount == 50000
        db.session.remove()
    engine.dispose()
