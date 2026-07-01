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
}


def ensure_workspace_schema() -> None:
    """Create workspace tables on current bind and tenant SQLite files."""
    from modules.workspace.models.workspace_session import WorkspaceSession  # noqa: F401
    from modules.workspace.models.workspace_audit_event import WorkspaceAuditEvent  # noqa: F401

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
