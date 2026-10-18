"""Ensure Leads CRM tables/columns exist on Core DB."""
from __future__ import annotations

from sqlalchemy import inspect, text

from extensions import db

_SCHEMA_ENSURED = False
_REQUIRED_TABLES = (
    "business_activities",
    "business_leads",
    "business_lead_phones",
    "lead_source_records",
    "lead_notes",
    "lead_interactions",
    "lead_follow_ups",
    "lead_saved_views",
    "lead_status_configs",
    "lead_duplicate_candidates",
    "lead_import_batches",
    "lead_import_rows",
    "lead_merge_logs",
    "lead_audit_logs",
    "lead_scores",
    "lead_automation_rules",
    "lead_discovery_runs",
)


def _bool_default(dialect_name: str, enabled: bool = True) -> str:
    if dialect_name == "postgresql":
        return "true" if enabled else "false"
    return "1" if enabled else "0"


def _timestamp_type(dialect_name: str) -> str:
    return "TIMESTAMP" if dialect_name == "postgresql" else "DATETIME"


def _expected_columns(dialect_name: str) -> dict[str, dict[str, str]]:
    ts = _timestamp_type(dialect_name)
    true_default = _bool_default(dialect_name, True)
    false_default = _bool_default(dialect_name, False)
    return {
        "business_activities": {
            "name": "VARCHAR(120)",
            "name_ar": "VARCHAR(120)",
            "slug": "VARCHAR(80)",
            "icon": "VARCHAR(60) DEFAULT 'fa-store'",
            "color": "VARCHAR(20) DEFAULT '#6366f1'",
            "description": "TEXT",
            "is_active": f"BOOLEAN DEFAULT {true_default} NOT NULL",
            "sort_order": "INTEGER DEFAULT 0 NOT NULL",
            "created_at": ts,
            "updated_at": ts,
        },
        "lead_status_configs": {
            "code": "VARCHAR(40)",
            "label_ar": "VARCHAR(80)",
            "sort_order": "INTEGER DEFAULT 0 NOT NULL",
            "color": "VARCHAR(20) DEFAULT '#6366f1'",
            "is_active": f"BOOLEAN DEFAULT {true_default} NOT NULL",
            "is_pipeline": f"BOOLEAN DEFAULT {true_default} NOT NULL",
            "created_at": ts,
        },
        "business_leads": {
            "activity_id": "INTEGER",
            "business_name": "VARCHAR(255)",
            "normalized_business_name": "VARCHAR(255)",
            "owner_name": "VARCHAR(120)",
            "governorate": "VARCHAR(80)",
            "city": "VARCHAR(80)",
            "district": "VARCHAR(120)",
            "area": "VARCHAR(120)",
            "full_address": "TEXT",
            "latitude": "FLOAT",
            "longitude": "FLOAT",
            "website": "VARCHAR(255)",
            "instagram_url": "VARCHAR(255)",
            "facebook_url": "VARCHAR(255)",
            "tiktok_url": "VARCHAR(255)",
            "status": "VARCHAR(40) DEFAULT 'NEW' NOT NULL",
            "priority": "VARCHAR(20) DEFAULT 'MEDIUM' NOT NULL",
            "assigned_to_superadmin_id": "INTEGER",
            "preferred_contact_method": "VARCHAR(40)",
            "last_contact_at": ts,
            "next_follow_up_at": ts,
            "trial_started_at": ts,
            "trial_ends_at": ts,
            "finora_company_id": "INTEGER",
            "estimated_value": "NUMERIC(12, 2)",
            "monthly_subscription_value": "NUMERIC(12, 2)",
            "source_primary": "VARCHAR(120)",
            "lead_score": "INTEGER DEFAULT 0 NOT NULL",
            "is_verified": f"BOOLEAN DEFAULT {false_default} NOT NULL",
            "is_active": f"BOOLEAN DEFAULT {true_default} NOT NULL",
            "duplicate_status": "VARCHAR(20) DEFAULT 'NONE' NOT NULL",
            "merged_into_lead_id": "INTEGER",
            "merged_at": ts,
            "merged_by": "INTEGER",
            "created_by": "INTEGER",
            "updated_by": "INTEGER",
            "created_at": ts,
            "updated_at": ts,
            "deleted_at": ts,
        },
        "business_lead_phones": {
            "lead_id": "INTEGER",
            "phone_original": "VARCHAR(40)",
            "normalized_phone": "VARCHAR(20)",
            "country_code": "VARCHAR(5) DEFAULT '964'",
            "is_primary": f"BOOLEAN DEFAULT {true_default} NOT NULL",
            "is_whatsapp": f"BOOLEAN DEFAULT {false_default} NOT NULL",
            "is_verified": f"BOOLEAN DEFAULT {false_default} NOT NULL",
            "is_valid": f"BOOLEAN DEFAULT {true_default} NOT NULL",
            "created_at": ts,
            "updated_at": ts,
        },
        "lead_source_records": {
            "lead_id": "INTEGER",
            "source_name": "VARCHAR(120)",
            "source_detail": "VARCHAR(255)",
            "import_batch_id": "INTEGER",
            "created_at": ts,
        },
        "lead_notes": {
            "lead_id": "INTEGER",
            "author_superadmin_id": "INTEGER",
            "body": "TEXT",
            "created_at": ts,
        },
        "lead_interactions": {
            "lead_id": "INTEGER",
            "superadmin_id": "INTEGER",
            "interaction_type": "VARCHAR(30)",
            "result_status": "VARCHAR(40)",
            "note": "TEXT",
            "contacted_at": ts,
            "next_follow_up_at": ts,
            "created_at": ts,
        },
        "lead_follow_ups": {
            "lead_id": "INTEGER",
            "superadmin_id": "INTEGER",
            "scheduled_at": ts,
            "reason": "VARCHAR(255)",
            "status": "VARCHAR(20) DEFAULT 'pending' NOT NULL",
            "completed_at": ts,
            "created_at": ts,
        },
        "lead_saved_views": {
            "name": "VARCHAR(120)",
            "superadmin_id": "INTEGER",
            "filters_json": "TEXT DEFAULT '{}'",
            "is_shared": f"BOOLEAN DEFAULT {false_default} NOT NULL",
            "created_at": ts,
        },
        "lead_import_batches": {
            "filename": "VARCHAR(255)",
            "activity_id": "INTEGER",
            "source_label": "VARCHAR(120)",
            "status": "VARCHAR(30) DEFAULT 'uploaded' NOT NULL",
            "mapping_json": "TEXT",
            "stats_json": "TEXT",
            "created_by": "INTEGER",
            "created_at": ts,
        },
        "lead_import_rows": {
            "batch_id": "INTEGER",
            "row_number": "INTEGER",
            "raw_json": "TEXT",
            "normalized_json": "TEXT",
            "validation_errors": "TEXT",
            "duplicate_level": "VARCHAR(20)",
            "duplicate_lead_id": "INTEGER",
            "duplicate_score": "FLOAT",
            "duplicate_reason": "TEXT",
            "commit_action": "VARCHAR(30)",
            "result_lead_id": "INTEGER",
            "created_at": ts,
        },
        "lead_duplicate_candidates": {
            "lead_id": "INTEGER",
            "candidate_lead_id": "INTEGER",
            "duplicate_level": "VARCHAR(20)",
            "duplicate_score": "FLOAT",
            "duplicate_reason": "TEXT",
            "status": "VARCHAR(20) DEFAULT 'pending' NOT NULL",
            "reviewed_by": "INTEGER",
            "reviewed_at": ts,
            "created_at": ts,
        },
        "lead_merge_logs": {
            "target_lead_id": "INTEGER",
            "source_lead_id": "INTEGER",
            "merged_by": "INTEGER",
            "snapshot_json": "TEXT",
            "created_at": ts,
        },
        "lead_audit_logs": {
            "lead_id": "INTEGER",
            "action": "VARCHAR(60)",
            "actor_superadmin_id": "INTEGER",
            "details_json": "TEXT",
            "created_at": ts,
        },
        "lead_scores": {
            "lead_id": "INTEGER",
            "score": "INTEGER DEFAULT 0 NOT NULL",
            "factors_json": "TEXT",
            "updated_at": ts,
        },
        "lead_automation_rules": {
            "name": "VARCHAR(120)",
            "trigger_event": "VARCHAR(60)",
            "conditions_json": "TEXT",
            "actions_json": "TEXT",
            "is_active": f"BOOLEAN DEFAULT {true_default} NOT NULL",
            "created_at": ts,
        },
        "lead_discovery_runs": {
            "status": "VARCHAR(30) DEFAULT 'running' NOT NULL",
            "source_name": "VARCHAR(120) DEFAULT 'OpenStreetMap' NOT NULL",
            "requested_limit": "INTEGER DEFAULT 100 NOT NULL",
            "discovered_count": "INTEGER DEFAULT 0 NOT NULL",
            "created_count": "INTEGER DEFAULT 0 NOT NULL",
            "skipped_count": "INTEGER DEFAULT 0 NOT NULL",
            "duplicate_count": "INTEGER DEFAULT 0 NOT NULL",
            "error_message": "TEXT",
            "settings_json": "TEXT",
            "created_by": "INTEGER",
            "started_at": ts,
            "finished_at": ts,
            "created_at": ts,
        },
    }


def _table_has_required_columns(inspector, table_name: str, expected: dict[str, str]) -> bool:
    if table_name not in set(inspector.get_table_names()):
        return False
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    return set(expected).issubset(existing)


def _ensure_columns() -> None:
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    expected_by_table = _expected_columns(db.engine.dialect.name)

    with db.engine.begin() as conn:
        for table_name, expected_columns in expected_by_table.items():
            if table_name not in tables:
                continue
            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            for column_name, column_type in expected_columns.items():
                if column_name in existing_columns:
                    continue
                conn.execute(
                    text(
                        f'ALTER TABLE "{table_name}" '
                        f'ADD COLUMN "{column_name}" {column_type}'
                    )
                )
                existing_columns.add(column_name)


def ensure_leads_crm_schema() -> None:
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        inspector = inspect(db.engine)
        expected_by_table = _expected_columns(db.engine.dialect.name)
        if all(
            _table_has_required_columns(inspector, table, expected_by_table[table])
            for table in _REQUIRED_TABLES
        ):
            return
        _SCHEMA_ENSURED = False

    from models.core.super_admin import SuperAdmin
    from models.core.tenant import Tenant
    from models.core.leads.models import (  # noqa: F401
        BusinessActivity,
        BusinessLead,
        BusinessLeadPhone,
        LeadAuditLog,
        LeadAutomationRule,
        LeadDiscoveryRun,
        LeadDuplicateCandidate,
        LeadFollowUp,
        LeadImportBatch,
        LeadImportRow,
        LeadInteraction,
        LeadMergeLog,
        LeadNote,
        LeadSavedView,
        LeadScore,
        LeadSourceRecord,
        LeadStatusConfig,
    )
    table_models = (
        SuperAdmin,
        Tenant,
        BusinessActivity,
        LeadStatusConfig,
        LeadImportBatch,
        BusinessLead,
        BusinessLeadPhone,
        LeadSourceRecord,
        LeadNote,
        LeadInteraction,
        LeadFollowUp,
        LeadSavedView,
        LeadImportRow,
        LeadDuplicateCandidate,
        LeadMergeLog,
        LeadAuditLog,
        LeadScore,
        LeadAutomationRule,
        LeadDiscoveryRun,
    )

    try:
        for model in table_models:
            model.__table__.create(bind=db.engine, checkfirst=True)
        db.session.commit()
        _ensure_columns()
    except Exception:
        db.session.rollback()
        raise

    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    if not all(t in tables for t in _REQUIRED_TABLES):
        return

    index_stmts = []
    if "business_leads" in tables:
        index_stmts.extend([
            "CREATE INDEX IF NOT EXISTS ix_business_leads_status_governorate ON business_leads (status, governorate)",
            "CREATE INDEX IF NOT EXISTS ix_business_leads_activity_status ON business_leads (activity_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_business_leads_deleted_at ON business_leads (deleted_at)",
            "CREATE INDEX IF NOT EXISTS ix_business_leads_lat_lng ON business_leads (latitude, longitude)",
        ])
    if "lead_discovery_runs" in tables:
        index_stmts.extend([
            "CREATE INDEX IF NOT EXISTS ix_lead_discovery_runs_started_at ON lead_discovery_runs (started_at)",
            "CREATE INDEX IF NOT EXISTS ix_lead_discovery_runs_status ON lead_discovery_runs (status)",
        ])

    with db.engine.connect() as conn:
        for stmt in index_stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass
        conn.commit()

    _SCHEMA_ENSURED = True
