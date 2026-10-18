"""Additive counting records. These tables never replace inventory balances."""
from datetime import datetime

from extensions import db


class InventoryCountControl(db.Model):
    __tablename__ = "inventory_count_control"
    id = db.Column(db.Integer, primary_key=True)
    revision = db.Column(db.Integer, nullable=False, default=0)


class InventoryCountSession(db.Model):
    __tablename__ = "inventory_count_session"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(60), nullable=False, unique=True)
    tenant_key = db.Column(db.String(150), nullable=False, index=True)
    ledger_kind = db.Column(db.String(20), nullable=False)
    locations_json = db.Column(db.Text, nullable=False)
    title = db.Column(db.String(150), nullable=False, default="")
    status = db.Column(db.String(30), nullable=False, default="counting", index=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey("employee.id"))
    approved_at = db.Column(db.DateTime)
    posted_by = db.Column(db.Integer, db.ForeignKey("employee.id"))
    posted_at = db.Column(db.DateTime)
    review_note = db.Column(db.Text, nullable=False, default="")
    __table_args__ = (
        db.CheckConstraint("ledger_kind IN ('branch','warehouse')", name="inventory_count_ledger_kind"),
        db.CheckConstraint("version > 0", name="inventory_count_version"),
    )


class InventoryCountLine(db.Model):
    __tablename__ = "inventory_count_line"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("inventory_count_session.id"), nullable=False, index=True)
    location_key = db.Column(db.String(60), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    # Zero denotes a product without managed options; never a nullable uniqueness key.
    variant_id = db.Column(db.Integer, nullable=False, default=0)
    variant_name = db.Column(db.String(80), nullable=False, default="")
    catalog_key = db.Column(db.String(100), nullable=False, index=True)
    product_snapshot_json = db.Column(db.Text, nullable=False, default="{}")
    baseline_quantity = db.Column(db.Integer, nullable=False)
    baseline_stamp = db.Column(db.String(64), nullable=False)
    counted_quantity = db.Column(db.Integer)
    expected_quantity = db.Column(db.Integer)
    counted_stamp = db.Column(db.String(64))
    counted_at = db.Column(db.DateTime)
    counted_by = db.Column(db.Integer, db.ForeignKey("employee.id"))
    version = db.Column(db.Integer, nullable=False, default=1)
    excluded = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text, nullable=False, default="")
    ticket = db.Column(db.String(36))
    ticket_quantity = db.Column(db.Integer)
    ticket_stamp = db.Column(db.String(64))
    ticket_at = db.Column(db.DateTime)
    ticket_by = db.Column(db.Integer)
    ticket_product_json = db.Column(db.Text, nullable=False, default="{}")
    investigation_json = db.Column(db.Text, nullable=False, default="{}")
    investigation_stamp = db.Column(db.String(64))
    resolution = db.Column(db.String(30), nullable=False, default="unreviewed")
    resolution_note = db.Column(db.Text, nullable=False, default="")
    reviewed_by = db.Column(db.Integer)
    reviewed_at = db.Column(db.DateTime)
    posted_delta = db.Column(db.Integer)
    posted_cost = db.Column(db.BigInteger)
    movement_id = db.Column(db.Integer)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"))
    __table_args__ = (
        db.UniqueConstraint("session_id", "location_key", "product_id", "variant_id", name="inventory_count_line_unique"),
        db.CheckConstraint("counted_quantity IS NULL OR counted_quantity >= 0", name="inventory_count_nonnegative"),
        db.Index("inventory_count_lines_location", "session_id", "location_key", "counted_at"),
    )


class InventoryCountEvent(db.Model):
    """Append-only count history and retry receipts in the same transaction."""
    __tablename__ = "inventory_count_event"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("inventory_count_session.id"), nullable=False, index=True)
    line_id = db.Column(db.Integer, db.ForeignKey("inventory_count_line.id"), index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    actor_name = db.Column(db.String(255), nullable=False, default="")
    action = db.Column(db.String(40), nullable=False)
    command_key = db.Column(db.String(36), nullable=False, unique=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    detail_json = db.Column(db.Text, nullable=False)
    result_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class InventoryCountOfflineTicket(db.Model):
    """Independent snapshot tickets: downloading never takes another counter's ticket."""
    __tablename__ = "inventory_count_offline_ticket"
    token = db.Column(db.String(36), primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("inventory_count_session.id"), nullable=False, index=True)
    line_id = db.Column(db.Integer, db.ForeignKey("inventory_count_line.id"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    stamp = db.Column(db.String(64), nullable=False)
    product_snapshot_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    consumed_at = db.Column(db.DateTime)


MODELS = (InventoryCountControl, InventoryCountSession, InventoryCountLine, InventoryCountEvent, InventoryCountOfflineTicket)
