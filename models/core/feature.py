"""Generic tenant feature management (Core DB only).

Absence of a ``tenant_features`` row always means DISABLED.
"""
from datetime import datetime

from extensions import db


class TenantFeature(db.Model):
    __tablename__ = "tenant_features"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "feature_key", name="uq_tenant_features_tenant_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_key = db.Column(db.String(64), nullable=False, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    configuration_json = db.Column(db.Text, nullable=True)
    enabled_at = db.Column(db.DateTime, nullable=True)
    enabled_by = db.Column(db.String(100), nullable=True)
    disabled_at = db.Column(db.DateTime, nullable=True)
    disabled_by = db.Column(db.String(100), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class FeatureAuditLog(db.Model):
    __tablename__ = "feature_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    # NULL tenant_id = platform-wide action (global kill switch).
    tenant_id = db.Column(db.Integer, nullable=True, index=True)
    feature_key = db.Column(db.String(64), nullable=False, index=True)
    action = db.Column(db.String(32), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    performed_by = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
