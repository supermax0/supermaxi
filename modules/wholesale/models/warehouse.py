"""Warehouse models — separate from Branch, linked via branch_id."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class Warehouse(db.Model):
    __tablename__ = "warehouse"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "code", name="_warehouse_tenant_code_uc"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    code = db.Column(db.String(60), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    kind = db.Column(db.String(30), nullable=False, default="main")  # main|damaged|returns
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    stocks = db.relationship("WarehouseStock", back_populates="warehouse", lazy="dynamic")
    branch = db.relationship("Branch", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "branch_id": self.branch_id,
            "code": self.code,
            "name": self.name,
            "kind": self.kind,
            "is_active": bool(self.is_active),
            "branch_name": self.branch.name if self.branch else None,
        }


class WarehouseStock(db.Model):
    __tablename__ = "warehouse_stock"
    __table_args__ = (
        db.UniqueConstraint("warehouse_id", "product_id", name="_warehouse_product_uc"),
        db.Index("ix_warehouse_stock_tenant_wh_prod", "tenant_id", "warehouse_id", "product_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouse.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    quantity = db.Column(db.Integer, default=0, nullable=False)
    opening_stock = db.Column(db.Integer, default=0, nullable=False)
    low_stock_threshold = db.Column(db.Integer, default=5, nullable=False)
    reserved_quantity = db.Column(db.Integer, default=0, nullable=False)
    in_transit_quantity = db.Column(db.Integer, default=0, nullable=False)

    @property
    def available_quantity(self):
        return max(0, int(self.quantity or 0) - int(self.reserved_quantity or 0))

    warehouse = db.relationship("Warehouse", back_populates="stocks")
    product = db.relationship("Product", lazy=True)


class WarehouseMovement(db.Model):
    __tablename__ = "warehouse_movement"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouse.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    movement_type = db.Column(db.String(30), nullable=False)  # in|out|transfer|adjust|count
    quantity = db.Column(db.Integer, nullable=False)
    quantity_before = db.Column(db.Integer, nullable=True)
    quantity_after = db.Column(db.Integer, nullable=True)
    unit_cost = db.Column(db.Integer, nullable=True)
    reference_type = db.Column(db.String(50), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)
    note = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class WarehouseTransfer(db.Model):
    __tablename__ = "warehouse_transfer"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)
    transfer_no = db.Column(db.String(60), nullable=True, index=True)
    from_warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouse.id"), nullable=False)
    to_warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouse.id"), nullable=False)
    status = db.Column(db.String(30), default="draft", nullable=False)  # draft|approved|sent|received|cancelled
    note = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    received_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    received_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    lines = db.relationship(
        "WarehouseTransferLine",
        back_populates="transfer",
        cascade="all, delete-orphan",
        lazy=True,
    )


class WarehouseTransferLine(db.Model):
    __tablename__ = "warehouse_transfer_line"

    id = db.Column(db.Integer, primary_key=True)
    transfer_id = db.Column(db.Integer, db.ForeignKey("warehouse_transfer.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)

    transfer = db.relationship("WarehouseTransfer", back_populates="lines")
