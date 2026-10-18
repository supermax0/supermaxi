# -*- coding: utf-8 -*-
"""SQLAlchemy models for order installment lifecycle."""

from datetime import datetime

from extensions import db


class OrderInstallmentSettings(db.Model):
    __tablename__ = "order_installment_settings"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=True)

    enabled = db.Column(db.Boolean, default=False, nullable=False)
    duration_value = db.Column(db.Integer, default=7, nullable=False)
    duration_unit = db.Column(db.String(20), default="days", nullable=False)

    auto_settle_enabled = db.Column(db.Boolean, default=True, nullable=False)
    allow_return = db.Column(db.Boolean, default=True, nullable=False)
    notify_before_due = db.Column(db.Boolean, default=False, nullable=False)
    confirm_on_create = db.Column(db.Boolean, default=True, nullable=False)
    event_log_enabled = db.Column(db.Boolean, default=True, nullable=False)

    cancel_auto_on_full_return = db.Column(db.Boolean, default=True, nullable=False)
    cancel_auto_on_cancel = db.Column(db.Boolean, default=True, nullable=False)
    cancel_auto_on_manual_settle = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "enabled": bool(self.enabled),
            "duration_value": int(self.duration_value or 7),
            "duration_unit": (self.duration_unit or "days").strip().lower(),
            "auto_settle_enabled": bool(self.auto_settle_enabled),
            "allow_return": bool(self.allow_return),
            "notify_before_due": bool(self.notify_before_due),
            "confirm_on_create": bool(self.confirm_on_create),
            "event_log_enabled": bool(self.event_log_enabled),
            "cancel_auto_on_full_return": bool(self.cancel_auto_on_full_return),
            "cancel_auto_on_cancel": bool(self.cancel_auto_on_cancel),
            "cancel_auto_on_manual_settle": bool(self.cancel_auto_on_manual_settle),
        }


class OrderInstallmentLifecycle(db.Model):
    __tablename__ = "order_installment_lifecycles"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=True)
    order_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, nullable=True)

    status = db.Column(db.String(40), default="ACTIVE", nullable=False, index=True)

    started_at = db.Column(db.DateTime, nullable=False)
    due_at = db.Column(db.DateTime, nullable=False, index=True)

    returned_amount = db.Column(db.Integer, default=0, nullable=False)
    settled_amount = db.Column(db.Integer, default=0, nullable=False)

    auto_settled_at = db.Column(db.DateTime, nullable=True)
    manual_settled_at = db.Column(db.DateTime, nullable=True)

    settlement_transaction_id = db.Column(db.Integer, nullable=True)
    idempotency_key = db.Column(db.String(80), nullable=True, unique=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "employee_id": self.employee_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(sep=" ") if self.started_at else None,
            "due_at": self.due_at.isoformat(sep=" ") if self.due_at else None,
            "returned_amount": int(self.returned_amount or 0),
            "settled_amount": int(self.settled_amount or 0),
            "auto_settled_at": (
                self.auto_settled_at.isoformat(sep=" ") if self.auto_settled_at else None
            ),
            "manual_settled_at": (
                self.manual_settled_at.isoformat(sep=" ") if self.manual_settled_at else None
            ),
            "settlement_transaction_id": self.settlement_transaction_id,
            "idempotency_key": self.idempotency_key,
        }


class OrderInstallmentEvent(db.Model):
    __tablename__ = "order_installment_events"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=True)
    installment_lifecycle_id = db.Column(
        db.Integer,
        db.ForeignKey("order_installment_lifecycles.id"),
        nullable=False,
        index=True,
    )
    order_id = db.Column(db.Integer, nullable=True, index=True)
    employee_id = db.Column(db.Integer, nullable=True)

    event_type = db.Column(db.String(60), nullable=False)
    old_status = db.Column(db.String(40), nullable=True)
    new_status = db.Column(db.String(40), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
