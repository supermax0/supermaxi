"""Lazy tenant-local schema for Finora Clinics."""
from __future__ import annotations

import logging

from flask import g
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from extensions import db
from modules.clinics.models import CLINIC_MODELS

_log = logging.getLogger(__name__)
_ensured: set[tuple] = set()
SCHEMA_VERSION = "clinics-v30-accounting-integration"

ADDITIVE_INDEXES = (
    # PostgreSQL and SQLite both allow multiple NULL visit_id values while
    # rejecting a second invoice for the same tenant visit.
    'CREATE UNIQUE INDEX IF NOT EXISTS "uq_clinic_invoice_visit" ON "clinic_invoice" ("tenant_id", "visit_id")',
    'CREATE UNIQUE INDEX IF NOT EXISTS "uq_clinic_invoice_number" ON "clinic_invoice" ("tenant_id", "invoice_number")',
    'CREATE INDEX IF NOT EXISTS "ix_clinic_appt_dental_context" ON "clinic_appointment" ("tenant_id", "treatment_plan_id", "treatment_plan_item_id", "dental_session_id")',
    'CREATE INDEX IF NOT EXISTS "ix_clinic_appt_tooth" ON "clinic_appointment" ("tenant_id", "tooth_number")',
    'CREATE INDEX IF NOT EXISTS "ix_clinic_service_default_procedure" ON "clinic_service" ("tenant_id", "default_procedure_id")',
    'CREATE INDEX IF NOT EXISTS "ix_clinic_dental_event_active" ON "clinic_dental_tooth_event" ("tenant_id", "patient_id", "tooth_number", "is_active")',
    'CREATE INDEX IF NOT EXISTS "ix_clinic_dental_event_supersedes" ON "clinic_dental_tooth_event" ("tenant_id", "supersedes_event_id")',
    'CREATE INDEX IF NOT EXISTS "ix_clinic_dental_item_option" ON "clinic_dental_treatment_plan_item" ("tenant_id", "treatment_option_id")',
    'CREATE INDEX IF NOT EXISTS "ix_clinic_dental_image_context" ON "clinic_dental_image" ("tenant_id", "treatment_plan_id", "dental_session_id")',
    'CREATE UNIQUE INDEX IF NOT EXISTS "uq_accounting_posting_source_event" ON "accounting_posting" ("tenant_id", "source_module", "source_type", "source_id", "source_event")',
    'CREATE INDEX IF NOT EXISTS "ix_accounting_posting_source" ON "accounting_posting" ("tenant_id", "source_module", "source_type", "source_id")',
)

ADDITIVE_COLUMNS = {
    "clinic_settings": {
        "organization_mode": "VARCHAR(30) NOT NULL DEFAULT 'solo_clinic'",
        "queue_display_enabled": "BOOLEAN DEFAULT 1",
        "doctor_commission_default_pct": "NUMERIC(5,2) DEFAULT 0",
        "doctor_availability_requires_attendance": "BOOLEAN DEFAULT 0",
        "language": "VARCHAR(10) DEFAULT 'ar'",
        "booking_welcome_text": "TEXT",
        "whatsapp_notifications_enabled": "BOOLEAN DEFAULT 0",
        "default_followup_days": "INTEGER DEFAULT 7",
        "reminder_hours_before": "INTEGER DEFAULT 24",
        "booking_rate_limit_per_hour": "INTEGER DEFAULT 10",
        "booking_otp_enabled": "BOOLEAN DEFAULT 0",
        "booking_mode": "VARCHAR(30) DEFAULT 'direct'",
        "minimum_booking_notice_hours": "INTEGER DEFAULT 2",
        "maximum_advance_booking_days": "INTEGER DEFAULT 60",
        "allow_same_day_booking": "BOOLEAN DEFAULT 1",
        "allow_public_reschedule": "BOOLEAN DEFAULT 1",
        "allow_public_cancellation": "BOOLEAN DEFAULT 1",
        "cancellation_deadline_hours": "INTEGER DEFAULT 4",
        "max_active_appointments_per_patient": "INTEGER DEFAULT 3",
        "public_show_prices": "BOOLEAN DEFAULT 0",
        "clinic_whatsapp_number": "VARCHAR(40)",
        "public_profile_enabled": "BOOLEAN DEFAULT 1",
        "public_chat_enabled": "BOOLEAN DEFAULT 1",
        "public_logo_url": "VARCHAR(500)",
        "public_location": "VARCHAR(300)",
        "public_working_hours": "VARCHAR(300)",
        "specialty_pack_seeded": "BOOLEAN DEFAULT 0",
        "display_sound_enabled": "BOOLEAN DEFAULT 1",
        "display_voice_enabled": "BOOLEAN DEFAULT 0",
        "display_volume": "INTEGER DEFAULT 70",
        "display_show_short_name": "BOOLEAN DEFAULT 0",
        "display_footer_message": "TEXT",
        "purchase_warn_expiry_days": "INTEGER DEFAULT 90",
        "purchase_price_warn_pct": "INTEGER DEFAULT 20",
        "purchase_approval_limit": "INTEGER DEFAULT 500000",
        "primary_specialty_id": "INTEGER",
        "specialty_features_json": "TEXT",
        "dental_config_json": "TEXT",
    },
    "clinic_service": {
        "requires_tooth": "BOOLEAN DEFAULT 0",
        "allows_multiple_teeth": "BOOLEAN DEFAULT 0",
        "requires_sessions": "BOOLEAN DEFAULT 0",
        "default_sessions": "INTEGER DEFAULT 1",
        "default_procedure_id": "INTEGER",
    },
    "clinic_invoice": {
        "treatment_plan_id": "INTEGER",
    },
    "clinic_invoice_item": {
        "treatment_plan_item_id": "INTEGER",
        "dental_session_id": "INTEGER",
    },
    "clinic_dental_treatment_plan_item": {
        "service_id": "INTEGER",
        "treatment_option_id": "INTEGER",
        "tooth_numbers_json": "TEXT",
        "whole_mouth": "BOOLEAN DEFAULT 0",
        "quantity": "NUMERIC(10,2) DEFAULT 1",
        "discount": "INTEGER DEFAULT 0",
        "completed_by": "INTEGER",
        "cancelled_by": "INTEGER",
        "cancellation_reason": "TEXT",
    },
    "clinic_doctor_settlement": {
        "payment_method": "VARCHAR(40) NOT NULL DEFAULT 'cash'",
    },
    "clinic_cash_session": {
        "cash_collections": "INTEGER NOT NULL DEFAULT 0",
        "cash_refunds": "INTEGER NOT NULL DEFAULT 0",
        "cash_expenses": "INTEGER NOT NULL DEFAULT 0",
        "supplier_payments": "INTEGER NOT NULL DEFAULT 0",
        "doctor_payments": "INTEGER NOT NULL DEFAULT 0",
        "other_cash_in": "INTEGER NOT NULL DEFAULT 0",
        "other_cash_out": "INTEGER NOT NULL DEFAULT 0",
        "difference": "INTEGER",
    },
    "clinic_dental_treatment_plan": {
        "accepted_at": "DATETIME",
        "accepted_by": "INTEGER",
        "selected_option_id": "INTEGER",
        "acceptance_method": "VARCHAR(40)",
        "signature_attachment_id": "INTEGER",
        "estimated_discount": "INTEGER DEFAULT 0",
        "cancellation_reason": "TEXT",
    },
    "clinic_dental_tooth_event": {
        "is_active": "BOOLEAN DEFAULT 0",
        "finding_key": "VARCHAR(80)",
        "supersedes_event_id": "INTEGER",
        "resolved_at": "DATETIME",
        "resolved_by": "INTEGER",
    },
    "clinic_dental_session": {
        "next_recommendation": "TEXT",
        "cancellation_reason": "TEXT",
        "completed_by": "INTEGER",
        "cancelled_by": "INTEGER",
    },
    "clinic_dental_image": {
        "treatment_plan_id": "INTEGER",
        "dental_session_id": "INTEGER",
    },
    "clinic_patient": {
        "secondary_phone": "VARCHAR(40)",
        "blood_type": "VARCHAR(10)",
        "national_id": "VARCHAR(60)",
        "city": "VARCHAR(100)",
        "emergency_contact": "VARCHAR(200)",
        "emergency_phone": "VARCHAR(40)",
        "allergies": "TEXT",
        "chronic_conditions": "TEXT",
    },
    "clinic_appointment": {
        "specialty_id": "INTEGER",
        "specialty_code_snapshot": "VARCHAR(80)",
        "workspace_snapshot": "VARCHAR(80)",
        "queue_number": "INTEGER",
        "queue_priority": "INTEGER DEFAULT 0",
        "payment_status": "VARCHAR(30) DEFAULT 'unpaid'",
        "cancelled_reason": "VARCHAR(255)",
        "checked_in_at": "DATETIME",
        "source": "VARCHAR(40) DEFAULT 'reception'",
        "treatment_plan_item_id": "INTEGER",
        "treatment_plan_id": "INTEGER",
        "dental_session_id": "INTEGER",
        "tooth_number": "VARCHAR(4)",
        "tooth_numbers_json": "TEXT",
    },
    "clinic_visit": {
        "specialty_id": "INTEGER",
        "specialty_code_snapshot": "VARCHAR(80)",
        "workspace_snapshot": "VARCHAR(80)",
        "visit_template_id": "INTEGER",
    },
    "clinic_booking_request": {
        "specialty_id": "INTEGER",
    },
    "clinic_doctor": {
        "photo_url": "VARCHAR(500)",
        "scientific_title": "VARCHAR(120)",
    },
    "clinic_vital": {
        "bmi": "NUMERIC(6,2)",
        "respiratory_rate": "INTEGER",
        "blood_glucose": "NUMERIC(7,2)",
        "head_circumference_cm": "NUMERIC(6,2)",
    },
    "clinic_doctor_schedule": {
        "break_start": "TIME",
        "break_end": "TIME",
    },
    "clinic_visit_procedure": {
        "inventory_deducted": "BOOLEAN DEFAULT 0",
    },
    "clinic_attachment": {
        "document_date": "DATE",
        "notes": "TEXT",
    },
    "clinic_diagnosis": {
        "status": "VARCHAR(30) DEFAULT 'active'",
        "updated_at": "DATETIME",
    },
    "clinic_procedure": {
        "description": "TEXT",
        "available_for_booking": "BOOLEAN DEFAULT 0",
        "creates_charge": "BOOLEAN DEFAULT 1",
    },
    "clinic_visit_procedure": {
        "status": "VARCHAR(30) DEFAULT 'requested'",
        "quantity": "NUMERIC(10,2) DEFAULT 1",
        "started_at": "DATETIME",
        "completed_at": "DATETIME",
        "cancelled_at": "DATETIME",
        "inventory_consumed_at": "DATETIME",
        "updated_at": "DATETIME",
    },
    "clinic_lab_order": {"reviewed_at": "DATETIME", "updated_at": "DATETIME"},
    "clinic_radiology_order": {"recommendations": "TEXT", "reviewed_at": "DATETIME", "updated_at": "DATETIME"},
    "clinic_follow_up": {
        "followup_type": "VARCHAR(40) DEFAULT 'treatment_review'",
        "last_attempt_at": "DATETIME",
        "outcome": "VARCHAR(60)",
    },
    "clinic_inventory_item": {
        "scientific_name": "VARCHAR(200)",
        "description": "TEXT",
        "average_cost": "INTEGER DEFAULT 0",
        "last_purchase_cost": "INTEGER DEFAULT 0",
        "maximum_stock": "NUMERIC(14,3) DEFAULT 0",
        "reorder_point": "NUMERIC(14,3) DEFAULT 0",
        "suggested_reorder_qty": "NUMERIC(14,3) DEFAULT 0",
        "serial_tracking": "BOOLEAN DEFAULT 0",
        "requires_cooling": "BOOLEAN DEFAULT 0",
        "sensitive_item": "BOOLEAN DEFAULT 0",
        "prevent_expired_usage": "BOOLEAN DEFAULT 1",
        "default_supplier_id": "INTEGER",
    },
    "clinic_inventory_batch": {
        "manufacturing_date": "DATE",
        "supplier_id": "INTEGER",
        "purchase_id": "INTEGER",
    },
    "clinic_inventory_movement": {
        "stock_before": "NUMERIC(14,3)",
        "stock_after": "NUMERIC(14,3)",
        "unit_cost": "INTEGER DEFAULT 0",
        "reason": "VARCHAR(80)",
        "branch_id": "INTEGER",
    },
    "clinic_purchase_item": {
        "received_quantity": "NUMERIC(14,3) DEFAULT 0",
        "free_quantity": "NUMERIC(14,3) DEFAULT 0",
        "line_discount": "INTEGER DEFAULT 0",
        "line_discount_percent": "NUMERIC(5,2)",
        "returned_quantity": "NUMERIC(14,3) DEFAULT 0",
    },
    "clinic_purchase": {
        "receipt_status": "VARCHAR(30) DEFAULT 'pending'",
        "supplier_invoice_no": "VARCHAR(120)",
        "due_date": "DATE",
        "invoice_status": "VARCHAR(30) DEFAULT 'approved'",
        "payment_status": "VARCHAR(30) DEFAULT 'unpaid'",
        "discount_percent": "NUMERIC(5,2)",
        "shipping_extra": "INTEGER DEFAULT 0",
        "tax_amount": "INTEGER DEFAULT 0",
        "other_charges": "INTEGER DEFAULT 0",
        "purchase_type": "VARCHAR(30) DEFAULT 'credit'",
        "warehouse_name": "VARCHAR(120)",
        "return_total": "INTEGER DEFAULT 0",
    },
}


def _engine():
    slug = getattr(g, "tenant", None)
    if slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(slug)
    return db.session.get_bind() or db.engine


def ensure_clinics_schema() -> None:
    engine = _engine()
    key = (engine, getattr(g, 'tenant', None), SCHEMA_VERSION)
    if key in _ensured:
        return
    try:
        # Let SQLAlchemy dependency-sort the full Clinics graph. This is
        # required by the intentional appointment <-> dental-session links;
        # creating one table at a time is not safe on PostgreSQL.
        db.metadata.create_all(
            bind=engine,
            tables=[model.__table__ for model in CLINIC_MODELS],
            checkfirst=True,
        )
        inspector = inspect(engine)
        with engine.begin() as connection:
            for table_name, additions in ADDITIVE_COLUMNS.items():
                if not inspector.has_table(table_name):
                    continue
                existing = {column["name"] for column in inspector.get_columns(table_name)}
                for column_name, definition in additions.items():
                    if column_name in existing:
                        continue
                    connection.execute(
                        text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}')
                    )
            if inspector.has_table("clinic_invoice"):
                for statement in ADDITIVE_INDEXES:
                    connection.execute(text(statement))
        from modules.clinics.models import ClinicSettings, ClinicDoctor
        from modules.clinics.service_specialties import migrate_legacy_specialties
        # Run before either staff or public requests; never commit their session.
        with Session(engine) as migration_session, migration_session.begin():
            tenant_ids = {row[0] for row in migration_session.query(ClinicSettings.tenant_id).all()}
            tenant_ids.update(row[0] for row in migration_session.query(ClinicDoctor.tenant_id).all())
            for tenant_id in tenant_ids:
                migrate_legacy_specialties(int(tenant_id), migration_session)
        # Account creation is idempotent and does not post historical clinic
        # activity.  It prepares every existing tenant for the first GL event.
        from utils.accounting_logic import initialize_accounts
        initialize_accounts()
        _ensured.add(key)
    except Exception:
        _log.exception("Clinics schema initialization failed")
        raise


def clear_clinics_schema_cache() -> None:
    _ensured.clear()
