from datetime import datetime

from extensions import db


class FacebookPageRouting(db.Model):
    __tablename__ = "facebook_page_routing"

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.String(128), nullable=False, unique=True, index=True)
    channel_account_id = db.Column(db.Integer, index=True)
    routing_enabled = db.Column(db.Boolean, default=False, nullable=False, index=True)
    routing_method = db.Column(db.String(30), default="LEAST_ACTIVE", nullable=False)
    default_max_conversations = db.Column(db.Integer, default=10, nullable=False)
    reply_timeout_seconds = db.Column(db.Integer, default=180, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FacebookPageEmployee(db.Model):
    __tablename__ = "facebook_page_employee"
    __table_args__ = (
        db.UniqueConstraint("page_id", "employee_id", name="uq_fb_page_employee"),
    )

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.String(128), nullable=False, index=True)
    employee_id = db.Column(db.Integer, nullable=False, index=True)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False, index=True)
    max_active_conversations = db.Column(db.Integer, nullable=True)
    last_assigned_at = db.Column(db.DateTime, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class FacebookEmployeeRouting(db.Model):
    __tablename__ = "facebook_employee_routing"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    accept_messages = db.Column(db.Boolean, default=True, nullable=False, index=True)
    presence = db.Column(db.String(20), default="AVAILABLE", nullable=False, index=True)
    max_active_conversations = db.Column(db.Integer, default=10, nullable=False)
    reply_timeout_seconds = db.Column(db.Integer, nullable=True)
    last_seen_at = db.Column(db.DateTime, index=True)
    activity = db.Column(db.String(20), default="open", nullable=False)
    activity_label = db.Column(db.String(80))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FacebookRoutingEvent(db.Model):
    __tablename__ = "facebook_routing_event"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, index=True)
    page_id = db.Column(db.String(128), index=True)
    old_employee_id = db.Column(db.Integer)
    new_employee_id = db.Column(db.Integer)
    action = db.Column(db.String(40), nullable=False, index=True)
    reason = db.Column(db.String(300))
    performed_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
