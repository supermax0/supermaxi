from __future__ import annotations

import os
import traceback

from flask import current_app
from sqlalchemy import inspect, text

from extensions import db


WORKSPACE_TABLES = {
    "ai_workspace_sessions": {
        "tenant_slug": "VARCHAR(100)",
        "user_id": "INTEGER",
        "workflow_type": "VARCHAR(50)",
        "status": "VARCHAR(30)",
        "current_step_id": "VARCHAR(80)",
        "windows_json": "TEXT",
        "avatar_state_json": "TEXT",
        "metadata_json": "TEXT",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    },
    "ai_workspace_audit_events": {
        "session_id": "VARCHAR(36)",
        "event_type": "VARCHAR(80)",
        "message": "TEXT",
        "payload_json": "TEXT",
        "user_id": "INTEGER",
        "created_at": "DATETIME",
    },
    "ai_workspace_documents": {
        "session_id": "VARCHAR(36)",
        "tenant_slug": "VARCHAR(100)",
        "user_id": "INTEGER",
        "original_filename": "VARCHAR(255)",
        "stored_filename": "VARCHAR(255)",
        "storage_path": "VARCHAR(512)",
        "public_preview_path": "VARCHAR(512)",
        "mime_type": "VARCHAR(120)",
        "file_ext": "VARCHAR(20)",
        "file_size": "INTEGER",
        "sha256": "VARCHAR(64)",
        "page_count": "INTEGER",
        "status": "VARCHAR(30)",
        "metadata_json": "TEXT",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    },
    "ai_workspace_document_extraction_results": {
        "document_id": "VARCHAR(36)",
        "session_id": "VARCHAR(36)",
        "tenant_slug": "VARCHAR(100)",
        "user_id": "INTEGER",
        "status": "VARCHAR(30)",
        "document_kind": "VARCHAR(50)",
        "confidence": "FLOAT",
        "signals_json": "TEXT",
        "extracted_text": "TEXT",
        "text_sample": "TEXT",
        "tables_json": "TEXT",
        "normalized_entities_json": "TEXT",
        "pages_json": "TEXT",
        "error_message": "TEXT",
        "metadata_json": "TEXT",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    },
    "ai_workspace_courier_statement_analyses": {
        "session_id": "VARCHAR(36)",
        "document_id": "VARCHAR(36)",
        "extraction_result_id": "VARCHAR(36)",
        "tenant_slug": "VARCHAR(100)",
        "user_id": "INTEGER",
        "status": "VARCHAR(30)",
        "courier_company_id": "INTEGER",
        "courier_company_name_detected": "VARCHAR(200)",
        "document_kind": "VARCHAR(50)",
        "confidence": "FLOAT",
        "total_rows": "INTEGER",
        "matched_rows": "INTEGER",
        "review_rows": "INTEGER",
        "unmatched_rows": "INTEGER",
        "issue_rows": "INTEGER",
        "duplicate_rows": "INTEGER",
        "total_collected_amount": "INTEGER",
        "total_delivery_fees": "INTEGER",
        "expected_net_amount": "INTEGER",
        "unmatched_amount": "INTEGER",
        "total_variance_amount": "INTEGER",
        "summary_json": "TEXT",
        "metadata_json": "TEXT",
        "error_message": "TEXT",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    },
}


_tenant_schema_ready: set = set()


def ensure_workspace_schema_for_tenant(tenant_slug: str | None) -> None:
    """Ensure workspace tables exist on the active tenant database."""
    if not tenant_slug or tenant_slug in _tenant_schema_ready:
        return
    from modules.workspace.models.workspace_session import WorkspaceSession  # noqa: F401
    from modules.workspace.models.workspace_audit_event import WorkspaceAuditEvent  # noqa: F401
    from modules.workspace.models.workspace_document import WorkspaceDocument  # noqa: F401
    from modules.workspace.models.document_extraction_result import DocumentExtractionResult  # noqa: F401
    from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis  # noqa: F401
    from modules.workspace.models.courier_statement_analysis_row import CourierStatementAnalysisRow  # noqa: F401
    from modules.workspace.models.courier_statement_analysis_issue import CourierStatementAnalysisIssue  # noqa: F401

    try:
        from extensions_tenant import get_tenant_engine

        engine = get_tenant_engine(tenant_slug)
        db.Model.metadata.create_all(engine)
        _tenant_schema_ready.add(tenant_slug)
    except Exception:
        current_app.logger.warning(
            "Workspace schema for tenant %s: %s", tenant_slug, traceback.format_exc()
        )


def ensure_workspace_schema() -> None:
    """Create workspace tables on current bind and tenant SQLite files."""
    from modules.workspace.models.workspace_session import WorkspaceSession  # noqa: F401
    from modules.workspace.models.workspace_audit_event import WorkspaceAuditEvent  # noqa: F401
    from modules.workspace.models.workspace_document import WorkspaceDocument  # noqa: F401
    from modules.workspace.models.document_extraction_result import DocumentExtractionResult  # noqa: F401
    from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis  # noqa: F401
    from modules.workspace.models.courier_statement_analysis_row import CourierStatementAnalysisRow  # noqa: F401
    from modules.workspace.models.courier_statement_analysis_issue import CourierStatementAnalysisIssue  # noqa: F401

    try:
        db.create_all()
    except Exception:
        current_app.logger.error(traceback.format_exc())

    try:
        from extensions_tenant import get_tenant_engine

        tenants_dir = os.path.join(current_app.root_path, "tenants")
        if os.path.isdir(tenants_dir):
            for db_name in os.listdir(tenants_dir):
                if not db_name.endswith(".db"):
                    continue
                slug = os.path.splitext(db_name)[0]
                try:
                    engine = get_tenant_engine(slug)
                    db.Model.metadata.create_all(engine)
                except Exception:
                    current_app.logger.warning(
                        "Workspace schema skip tenant %s: %s", slug, traceback.format_exc()
                    )
    except Exception:
        current_app.logger.error(traceback.format_exc())

    try:
        inspector = inspect(db.engine)
        table_names = set(inspector.get_table_names())
        conn = db.engine.connect()
        trans = conn.begin()
        try:
            for table_name, cols in WORKSPACE_TABLES.items():
                if table_name not in table_names:
                    continue
                existing = {c["name"] for c in inspector.get_columns(table_name)}
                for col_name, col_type in cols.items():
                    if col_name not in existing:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
            trans.commit()
        except Exception:
            trans.rollback()
        finally:
            conn.close()
    except Exception:
        pass
