"""FINORA CORE core-DB tables (prefix ``fc_``). Schema changes go through ``migrations.py`` only."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class FcOperatorRole(db.Model):
    """Role of a Super Admin account inside FINORA CORE. No row → ``super_admin`` (platform owners)."""

    __tablename__ = "fc_operator_roles"

    superadmin_id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class FcDesktopSession(db.Model):
    """One signed-in desktop. Only hashes of refresh tokens are stored; rotation keeps the previous hash
    to detect refresh-token reuse (theft) and revoke the whole session."""

    __tablename__ = "fc_desktop_sessions"

    id = db.Column(db.Integer, primary_key=True)
    superadmin_id = db.Column(db.Integer, nullable=False, index=True)
    refresh_hash = db.Column(db.String(64), nullable=False, unique=True)
    previous_hash = db.Column(db.String(64), index=True)
    user_agent = db.Column(db.String(300))
    ip = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)
    revoke_reason = db.Column(db.String(60))


class FcEvent(db.Model):
    """Durable realtime outbox. SSE streams replay from ``seq``; the DB stays the source of truth."""

    __tablename__ = "fc_events"

    seq = db.Column(db.Integer, primary_key=True, autoincrement=True)
    type = db.Column(db.String(40), nullable=False)
    payload_json = db.Column(db.Text, nullable=False)
    dedupe_key = db.Column(db.String(160), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class FcAuditLog(db.Model):
    """Append-only audit trail (spec §52). Never updated or deleted by application code."""

    __tablename__ = "fc_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(120), nullable=False)
    actor_type = db.Column(db.String(10), nullable=False)  # ai | human | system
    category = db.Column(db.String(20), nullable=False, index=True)  # messages | ai | finora | errors | approvals
    action = db.Column(db.String(60), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    customer = db.Column(db.String(150))
    conversation_ref = db.Column(db.String(40), index=True)
    tenant_ref = db.Column(db.String(64))
    input_summary = db.Column(db.String(500))
    result = db.Column(db.String(10), nullable=False, default="ok")  # ok | failed | pending
    correlation_id = db.Column(db.String(64), nullable=False, index=True)
    approval_id = db.Column(db.String(40))
    dedupe_key = db.Column(db.String(160), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class FcNote(db.Model):
    """Internal, never customer-visible note on a conversation."""

    __tablename__ = "fc_notes"

    id = db.Column(db.Integer, primary_key=True)
    conversation_ref = db.Column(db.String(40), nullable=False, index=True)
    author = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class FcConversationRead(db.Model):
    """Per-operator read marker (operators are Super Admins, not tenant employees)."""

    __tablename__ = "fc_conversation_reads"

    superadmin_id = db.Column(db.Integer, primary_key=True)
    conversation_ref = db.Column(db.String(40), primary_key=True)
    last_read_message_id = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class FcIdempotency(db.Model):
    """Stored responses for idempotent writes (``Idempotency-Key`` header)."""

    __tablename__ = "fc_idempotency"

    key = db.Column(db.String(100), primary_key=True)
    superadmin_id = db.Column(db.Integer, nullable=False)
    route = db.Column(db.String(80), nullable=False)
    status_code = db.Column(db.Integer, nullable=False)
    response_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class FcSetting(db.Model):
    """Small key/value settings: kill switch, house sync cursors."""

    __tablename__ = "fc_settings"

    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Text, nullable=False)
    updated_by = db.Column(db.String(120))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


FC_TABLES = [
    FcOperatorRole.__table__,
    FcDesktopSession.__table__,
    FcEvent.__table__,
    FcAuditLog.__table__,
    FcNote.__table__,
    FcConversationRead.__table__,
    FcIdempotency.__table__,
    FcSetting.__table__,
]
