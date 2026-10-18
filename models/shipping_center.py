"""Shipping & Logistics Center (phase 2) — returns awaiting receipt / inspection and per-carrier settings.

Money and stock never live here: settlements run through ``execute_shipping_report``, returned stock through
``process_order_return`` and damaged goods through the stock write-off service. These rows only track the
operational lifecycle and the inspector's decisions.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db


class ShippingReturn(db.Model):
    __tablename__ = "shipping_center_returns"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, index=True)
    manifest_id = db.Column(db.Integer, nullable=True, index=True)
    manifest_number = db.Column(db.String(60), nullable=True)
    party_type = db.Column(db.String(20), nullable=False, default="carrier")  # carrier | agent
    party_id = db.Column(db.Integer, nullable=True, index=True)
    party_name = db.Column(db.String(150), nullable=True)
    # awaiting (reported returned by the carrier) → received (parcel in hand) → closed (inspected, stock posted)
    state = db.Column(db.String(20), nullable=False, default="awaiting", index=True)
    order_amount = db.Column(db.Integer, nullable=False, default=0)
    reported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    reported_by = db.Column(db.String(120), nullable=True)
    received_at = db.Column(db.DateTime, nullable=True)
    received_by = db.Column(db.String(120), nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    closed_by = db.Column(db.String(120), nullable=True)
    branch_id = db.Column(db.Integer, nullable=True)
    packaging_ok = db.Column(db.Boolean, nullable=True)
    inspection_json = db.Column(db.Text, nullable=True)  # [{item_id, product_id, name, variant, quantity, sellable, damaged}]
    writeoffs_json = db.Column(db.Text, nullable=True)  # write-off document numbers for damaged quantities
    note = db.Column(db.Text, nullable=True)


class ShippingCarrierSetting(db.Model):
    __tablename__ = "shipping_center_carrier_settings"

    carrier_id = db.Column(db.Integer, primary_key=True)
    return_fee = db.Column(db.Integer, nullable=False, default=0)  # charged by the carrier per returned parcel
    settlement_cycle = db.Column(db.String(20), nullable=False, default="manifest")  # daily | weekly | manifest
    payment_method = db.Column(db.String(20), nullable=False, default="cash")  # cash | bank
    treasury_account_id = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.String(120), nullable=True)


def ensure_shipping_center_tables() -> None:
    connection = db.session.connection()
    ShippingReturn.__table__.create(bind=connection, checkfirst=True)
    ShippingCarrierSetting.__table__.create(bind=connection, checkfirst=True)
    from models.receipt import Receipt, ReceiptAllocation

    Receipt.__table__.create(bind=connection, checkfirst=True)
    ReceiptAllocation.__table__.create(bind=connection, checkfirst=True)
