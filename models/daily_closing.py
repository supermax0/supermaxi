"""Persistent daily-closing snapshots and selective inventory counts."""

from datetime import datetime

from extensions import db


class DailySession(db.Model):
    __tablename__ = "daily_session"
    __table_args__ = (
        db.Index("ix_daily_session_company_branch_status", "company_key", "branch_id", "status"),
        db.Index("ix_daily_session_period", "opened_at", "closed_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    report_number = db.Column(db.String(40), nullable=False, unique=True, index=True)
    company_key = db.Column(db.String(80), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    business_date = db.Column(db.Date, nullable=False, index=True)
    shift_name = db.Column(db.String(100), nullable=True)
    opened_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    closed_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    reopened_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    opened_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)
    reopened_at = db.Column(db.DateTime, nullable=True)
    opening_cash = db.Column(db.Integer, nullable=False, default=0)
    expected_closing_cash = db.Column(db.Integer, nullable=True)
    actual_closing_cash = db.Column(db.Integer, nullable=True)
    cash_variance = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(24), nullable=False, default="open", index=True)
    notes = db.Column(db.Text, nullable=True)
    variance_reason = db.Column(db.Text, nullable=True)
    reopen_reason = db.Column(db.Text, nullable=True)
    snapshot_json = db.Column(db.Text, nullable=True)
    source_fingerprint = db.Column(db.String(64), nullable=True)
    snapshot_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    branch = db.relationship("Branch", lazy=True)
    opener = db.relationship("Employee", foreign_keys=[opened_by], lazy=True)
    closer = db.relationship("Employee", foreign_keys=[closed_by], lazy=True)
    counts = db.relationship("DailyInventoryCount", cascade="all, delete-orphan", lazy=True)
    adjustments = db.relationship("DailyCashAdjustment", cascade="all, delete-orphan", lazy=True)
    snapshot_history = db.relationship("DailyClosingSnapshotHistory", cascade="all, delete-orphan", lazy=True)


class DailyInventoryCount(db.Model):
    __tablename__ = "daily_inventory_count"
    __table_args__ = (
        db.UniqueConstraint("daily_session_id", "product_id", "warehouse_id", name="uq_daily_count_item"),
        db.Index("ix_daily_count_session_product", "daily_session_id", "product_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    daily_session_id = db.Column(db.Integer, db.ForeignKey("daily_session.id", ondelete="CASCADE"), nullable=False)
    company_key = db.Column(db.String(80), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, nullable=False, default=0)
    opening_quantity = db.Column(db.Integer, nullable=False, default=0)
    incoming_quantity = db.Column(db.Integer, nullable=False, default=0)
    outgoing_quantity = db.Column(db.Integer, nullable=False, default=0)
    expected_quantity = db.Column(db.Integer, nullable=False, default=0)
    actual_quantity = db.Column(db.Integer, nullable=True)
    variance = db.Column(db.Integer, nullable=True)
    counted_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    counted_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = db.relationship("Product", lazy=True)


class InventoryCountTemplate(db.Model):
    __tablename__ = "inventory_count_template"
    __table_args__ = (db.UniqueConstraint("company_key", "branch_id", "name", name="uq_count_template_name"),)

    id = db.Column(db.Integer, primary_key=True)
    company_key = db.Column(db.String(80), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    name = db.Column(db.String(150), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    items = db.relationship("InventoryCountTemplateItem", cascade="all, delete-orphan", lazy=True)


class InventoryCountTemplateItem(db.Model):
    __tablename__ = "inventory_count_template_item"
    __table_args__ = (db.UniqueConstraint("template_id", "product_id", name="uq_count_template_item"),)

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("inventory_count_template.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, nullable=False, default=0)
    product = db.relationship("Product", lazy=True)


class DailyCashAdjustment(db.Model):
    """Report-only adjustment; it never posts to the accounting ledger."""

    __tablename__ = "daily_cash_adjustment"
    id = db.Column(db.Integer, primary_key=True)
    daily_session_id = db.Column(db.Integer, db.ForeignKey("daily_session.id", ondelete="CASCADE"), nullable=False, index=True)
    company_key = db.Column(db.String(80), nullable=False, index=True)
    direction = db.Column(db.String(8), nullable=False)  # in | out
    category = db.Column(db.String(40), nullable=False, default="CASH_ADJUSTMENT")
    amount = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(255), nullable=False)
    reference = db.Column(db.String(120), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class DailyClosingAuditLog(db.Model):
    __tablename__ = "daily_closing_audit_log"
    __table_args__ = (db.Index("ix_daily_closing_audit_session_time", "daily_session_id", "created_at"),)

    id = db.Column(db.Integer, primary_key=True)
    daily_session_id = db.Column(db.Integer, db.ForeignKey("daily_session.id", ondelete="CASCADE"), nullable=False)
    company_key = db.Column(db.String(80), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    action = db.Column(db.String(60), nullable=False, index=True)
    entity_type = db.Column(db.String(60), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    user_name = db.Column(db.String(150), nullable=True)
    old_value_json = db.Column(db.Text, nullable=True)
    new_value_json = db.Column(db.Text, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class DailyClosingSnapshotHistory(db.Model):
    """Immutable copy of every closed snapshot archived before a reopen."""

    __tablename__ = "daily_closing_snapshot_history"
    __table_args__ = (
        db.UniqueConstraint("daily_session_id", "snapshot_version", name="uq_daily_snapshot_history_version"),
        db.Index("ix_daily_snapshot_history_session", "daily_session_id", "archived_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    daily_session_id = db.Column(db.Integer, db.ForeignKey("daily_session.id", ondelete="CASCADE"), nullable=False)
    company_key = db.Column(db.String(80), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    snapshot_version = db.Column(db.Integer, nullable=False)
    snapshot_json = db.Column(db.Text, nullable=False)
    source_fingerprint = db.Column(db.String(64), nullable=True)
    closed_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    archived_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    archived_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    reopen_reason = db.Column(db.Text, nullable=False)
