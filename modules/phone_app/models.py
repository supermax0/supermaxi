"""Phone call-center tables (tenant DB) — ORM mirrors versioned migrations."""

from __future__ import annotations

from datetime import datetime

from extensions import db


class PhoneRefreshToken(db.Model):
    __tablename__ = "phone_refresh_token"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    device_id = db.Column(db.String(128), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class PhoneAppDevice(db.Model):
    __tablename__ = "phone_app_devices"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    device_uuid = db.Column(db.String(128), nullable=False, index=True)
    device_name = db.Column(db.String(120), nullable=True)
    manufacturer = db.Column(db.String(80), nullable=True)
    model = db.Column(db.String(120), nullable=True)
    android_version = db.Column(db.String(40), nullable=True)
    app_version = db.Column(db.String(40), nullable=True)
    push_token = db.Column(db.String(512), nullable=True)
    sim_slots_count = db.Column(db.Integer, nullable=True)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("employee_id", "device_uuid", name="uq_phone_device_emp_uuid"),
    )


class PhoneCallLog(db.Model):
    __tablename__ = "phone_call_log"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=True, index=True)
    phone_e164 = db.Column(db.String(32), nullable=False, index=True)
    phone_normalized = db.Column(db.String(32), nullable=True, index=True)
    direction = db.Column(db.String(16), nullable=False, default="inbound")
    # Separated statuses
    call_status = db.Column(db.String(24), nullable=False, default="detected")
    sync_status = db.Column(db.String(24), nullable=False, default="pending")
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    duration_sec = db.Column(db.Integer, nullable=True)
    detected_at = db.Column(db.DateTime, nullable=True)
    ringing_at = db.Column(db.DateTime, nullable=True)
    dialing_at = db.Column(db.DateTime, nullable=True)
    answered_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    failed_at = db.Column(db.DateTime, nullable=True)
    server_received_at = db.Column(db.DateTime, nullable=True)
    client_id = db.Column(db.String(128), nullable=False, unique=True, index=True)
    local_call_uuid = db.Column(db.String(64), nullable=True, index=True)
    idempotency_key = db.Column(db.String(191), nullable=True, index=True)
    device_id = db.Column(db.String(128), nullable=True, index=True)
    sim_slot = db.Column(db.Integer, nullable=True)
    synced_note = db.Column(db.Text, nullable=True)
    # Phase 2A structured outcomes
    outcome = db.Column(db.String(32), nullable=True, index=True)
    outcome_note = db.Column(db.Text, nullable=True)
    follow_up_required = db.Column(db.Boolean, default=False, nullable=False)
    follow_up_at = db.Column(db.DateTime, nullable=True)
    outcome_recorded_at = db.Column(db.DateTime, nullable=True)
    outcome_recorded_by = db.Column(db.Integer, nullable=True)
    outcome_client_id = db.Column(db.String(64), nullable=True, index=True)
    # Phase 2B: device call recording attachment
    recording_path = db.Column(db.String(512), nullable=True)
    recording_size = db.Column(db.Integer, nullable=True)
    recording_duration_sec = db.Column(db.Integer, nullable=True)
    recording_mime = db.Column(db.String(64), nullable=True)
    recording_uploaded_at = db.Column(db.DateTime, nullable=True)
    recording_uploaded_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_phone_call_tenant_idem"
        ),
        db.Index("ix_phone_call_tenant_started", "tenant_id", "started_at"),
        db.Index("ix_phone_call_tenant_outcome", "tenant_id", "outcome"),
        db.Index("ix_phone_call_tenant_customer_started", "tenant_id", "customer_id", "started_at"),
    )


class PhoneCallNote(db.Model):
    __tablename__ = "phone_call_note"

    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.Integer, db.ForeignKey("phone_call_log.id"), nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=True, index=True)
    body = db.Column(db.Text, nullable=False)
    client_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class PhoneFollowupTask(db.Model):
    __tablename__ = "phone_followup_task"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=True, index=True)
    phone = db.Column(db.String(32), nullable=False, index=True)
    phone_normalized = db.Column(db.String(32), nullable=True, index=True)
    call_id = db.Column(db.Integer, db.ForeignKey("phone_call_log.id"), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    due_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(32), nullable=False, default="open")
    source = db.Column(db.String(32), nullable=False, default="missed_call")
    task_type = db.Column(db.String(32), nullable=False, default="missed_call_followup")
    attempt_count = db.Column(db.Integer, nullable=False, default=1)
    priority = db.Column(db.String(16), nullable=False, default="normal")
    reason = db.Column(db.String(64), nullable=True)
    resolved_by_call_id = db.Column(db.Integer, nullable=True)
    snoozed_until = db.Column(db.DateTime, nullable=True)
    client_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "call_id", "task_type", name="uq_phone_task_tenant_call_type"
        ),
        db.Index("ix_phone_task_status_due", "status", "due_at"),
        db.Index("ix_phone_task_priority", "priority", "status"),
    )


class PhoneOrderDraft(db.Model):
    __tablename__ = "phone_order_draft"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False, index=True)
    client_id = db.Column(db.String(64), nullable=False, unique=True)
    idempotency_key = db.Column(db.String(128), nullable=False, unique=True, index=True)
    status = db.Column(db.String(24), nullable=False, default="draft")  # draft|confirmed
    payload_json = db.Column(db.Text, nullable=False)
    invoice_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    confirmed_at = db.Column(db.DateTime, nullable=True)


class PhoneAuditLog(db.Model):
    __tablename__ = "phone_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, nullable=True, index=True)
    device_id = db.Column(db.String(128), nullable=True)
    action = db.Column(db.String(64), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
