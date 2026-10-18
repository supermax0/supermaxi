"""Subdivide existing branch FIFO; do not maintain a second stock quantity ledger."""
from datetime import datetime
from extensions import db


class InventoryStorageLocation(db.Model):
    __tablename__ = "inventory_storage_location"
    __table_args__ = (
        db.UniqueConstraint("branch_id", "code", name="uq_storage_branch_code"),
        db.CheckConstraint("kind IN ('storage','sales','damaged','returns')", name="ck_storage_kind"),
    )
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    code = db.Column(db.String(60), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="storage")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class InventoryLotPlacement(db.Model):
    __tablename__ = "inventory_lot_placement"
    inventory_lot_id = db.Column(db.Integer, db.ForeignKey("inventory_lot.id"), primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("inventory_storage_location.id"), nullable=False, index=True)
    # Quantity and cost remain exclusively on the original InventoryLot.


class InventoryOrderItemLocation(db.Model):
    __tablename__ = "inventory_order_item_location"
    order_item_id = db.Column(db.Integer, db.ForeignKey("order_item.id", ondelete="CASCADE"), primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("inventory_storage_location.id"), nullable=True)
    automatic = db.Column(db.Boolean(create_constraint=True,name='ck_order_source_automatic'), nullable=False, default=False)
    __table_args__=(db.CheckConstraint('NOT automatic OR location_id IS NULL',name='ck_order_source_auto_site'),)


class InventoryStorageTransfer(db.Model):
    __tablename__ = "inventory_storage_transfer"
    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_storage_transfer_qty"),
        db.CheckConstraint("status IN ('draft','sent','received','cancelled')", name="ck_storage_transfer_status"),
        db.CheckConstraint("from_location_id IS NOT NULL OR to_location_id IS NOT NULL", name="ck_storage_transfer_site"),
    )
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(60), nullable=False, unique=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    # NULL means the branch's existing unassigned/main stock, never another branch.
    from_location_id = db.Column(db.Integer, db.ForeignKey("inventory_storage_location.id"), nullable=True)
    to_location_id = db.Column(db.Integer, db.ForeignKey("inventory_storage_location.id"), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    variant_name = db.Column(db.String(80), nullable=False, default="")
    product_snapshot_json = db.Column(db.Text, nullable=False, default="{}")
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="draft", index=True)
    reason = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime, nullable=True)
    received_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)


class InventoryStorageTransferLayer(db.Model):
    __tablename__ = "inventory_storage_transfer_layer"
    __table_args__ = (
        db.UniqueConstraint("transfer_id", "phase", "sequence", name="uq_storage_transfer_layer"),
        db.CheckConstraint("quantity > 0 AND unit_cost >= 0", name="ck_storage_transfer_layer_value"),
        db.CheckConstraint("phase IN ('send','receive','cancel')", name="ck_storage_transfer_layer_phase"),
    )
    id = db.Column(db.Integer, primary_key=True)
    transfer_id = db.Column(db.Integer, db.ForeignKey("inventory_storage_transfer.id"), nullable=False, index=True)
    phase = db.Column(db.String(10), nullable=False)
    sequence = db.Column(db.Integer, nullable=False)
    inventory_lot_id = db.Column(db.Integer, db.ForeignKey("inventory_lot.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("inventory_storage_location.id"), nullable=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Integer, nullable=False)
    source_created_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
