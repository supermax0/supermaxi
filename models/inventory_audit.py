from __future__ import annotations

import json
from datetime import datetime

from extensions import db


class InventoryQuantityAudit(db.Model):
    """Immutable before/after evidence for every branch-stock mutation."""

    __tablename__ = "inventory_quantity_audit"

    id = db.Column(db.Integer, primary_key=True)
    event_key = db.Column(db.String(64), nullable=False, unique=True, index=True)
    movement_id = db.Column(db.Integer, db.ForeignKey("stock_movement.id"), nullable=True, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    operation = db.Column(db.String(50), nullable=False, index=True)
    before_quantity = db.Column(db.Integer, nullable=False)
    delta_quantity = db.Column(db.Integer, nullable=False)
    after_quantity = db.Column(db.Integer, nullable=False)
    source_type = db.Column(db.String(60), nullable=True, index=True)
    source_id = db.Column(db.Integer, nullable=True, index=True)
    source_line_id = db.Column(db.Integer, nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    employee_name = db.Column(db.String(150), nullable=True)
    request_path = db.Column(db.String(500), nullable=True)
    reason = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    movement = db.relationship("StockMovement", lazy=True)
    product = db.relationship("Product", lazy=True)
    branch = db.relationship("Branch", lazy=True)

    def get_metadata(self) -> dict:
        try:
            return json.loads(self.metadata_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def set_metadata(self, value: dict | None) -> None:
        self.metadata_json = json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


class InventoryStockSnapshot(db.Model):
    """Point-in-time stock evidence used to prove changes between audits."""

    __tablename__ = "inventory_stock_snapshot"
    __table_args__ = (
        db.Index("ix_inventory_snapshot_product_branch_time", "product_id", "branch_id", "captured_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    snapshot_key = db.Column(db.String(64), nullable=False, unique=True, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    session_id = db.Column(db.String(36), nullable=True, index=True)
    source = db.Column(db.String(50), nullable=False, default="forensic_scan")
    captured_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    product = db.relationship("Product", lazy=True)
    branch = db.relationship("Branch", lazy=True)
