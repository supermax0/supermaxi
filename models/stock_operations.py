"""Stock documents preserve the original quantities and valuation evidence."""
from datetime import datetime
from extensions import db


class StockTransferCostLayer(db.Model):
    __tablename__ = "stock_transfer_cost_layer"
    __table_args__ = (
        db.UniqueConstraint("transfer_kind", "line_id", "phase", "sequence", name="uq_transfer_cost_phase"),
        db.CheckConstraint("quantity > 0 AND unit_cost >= 0", name="ck_transfer_cost_positive"),
    )
    id = db.Column(db.Integer, primary_key=True)
    transfer_kind = db.Column(db.String(12), nullable=False)
    transfer_id = db.Column(db.Integer, nullable=False, index=True)
    line_id = db.Column(db.Integer, nullable=False, index=True)
    phase = db.Column(db.String(12), nullable=False)
    sequence = db.Column(db.Integer, nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey("inventory_lot.id"), nullable=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class InventoryWriteOff(db.Model):
    __tablename__ = "inventory_writeoff"
    __table_args__ = (db.CheckConstraint("quantity > 0 AND cost >= 0", name="ck_writeoff_positive"),)
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(60), nullable=False, unique=True)
    ledger_kind = db.Column(db.String(12), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    variant_name = db.Column(db.String(80), nullable=False, default="")
    quantity = db.Column(db.Integer, nullable=False)
    cost = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    layers_json = db.Column(db.Text, nullable=False)
    before_quantity = db.Column(db.Integer, nullable=False)
    after_quantity = db.Column(db.Integer, nullable=False)
    movement_id = db.Column(db.Integer, nullable=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=True)
    reversal_of_id = db.Column(db.Integer, db.ForeignKey("inventory_writeoff.id"), unique=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    business_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sealed = db.Column(db.Boolean, nullable=False, default=False)


class StockReorderRule(db.Model):
    __tablename__ = "stock_reorder_rule"
    __table_args__ = (
        db.UniqueConstraint("ledger_kind", "location_id", "product_id", "variant_name", name="uq_stock_reorder_location"),
        db.CheckConstraint("minimum >= 0 AND target >= minimum", name="ck_reorder_limits"),
    )
    id = db.Column(db.Integer, primary_key=True)
    ledger_kind = db.Column(db.String(12), nullable=False)
    location_id = db.Column(db.Integer, nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    variant_name = db.Column(db.String(80), nullable=False, default="")
    minimum = db.Column(db.Integer, nullable=False)
    target = db.Column(db.Integer, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)

