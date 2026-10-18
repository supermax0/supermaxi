"""
schema_guard.py
---------------
Self-healing DB schema guard for Publisher tables.
Creates missing tables and adds missing columns in-place for legacy deployments.

IMPORTANT: Finora routes queries to the active tenant SQLite via
DynamicTenantSession when g.tenant is set. Schema repair MUST target
db.session.get_bind() (tenant DB), not db.engine (core Postgres).
"""

from __future__ import annotations

import traceback
import time
from threading import Lock
from typing import Dict

from flask import current_app, g
from sqlalchemy import inspect, text

from extensions import db


PUBLISHER_TABLES: Dict[str, Dict[str, str]] = {
    "publisher_settings": {
        "tenant_slug": "VARCHAR(100)",
        "fb_app_id": "VARCHAR(50)",
        "fb_app_secret": "TEXT",
        "fb_user_token": "TEXT",
        "fb_verify_token": "TEXT",
        "fb_webhook_verified": "BOOLEAN",
        "fb_webhook_at": "DATETIME",
        "fb_token_expires_at": "DATETIME",
        "openai_api_key": "TEXT",
        "ads_app_id": "VARCHAR(50)",
        "ads_app_secret": "TEXT",
        "ads_user_token": "TEXT",
        "ads_account_id": "VARCHAR(64)",
        "updated_at": "DATETIME",
    },
    "publisher_pages": {
        "tenant_slug": "VARCHAR(100)",
        "page_id": "VARCHAR(128)",
        "page_name": "VARCHAR(255)",
        "page_token": "TEXT",
        "created_at": "DATETIME",
    },
    "publisher_media": {
        "tenant_slug": "VARCHAR(100)",
        "filename": "VARCHAR(255)",
        "original_name": "VARCHAR(255)",
        "media_type": "VARCHAR(20)",
        "size_bytes": "INTEGER",
        "url_path": "VARCHAR(512)",
        "created_at": "DATETIME",
    },
    "publisher_posts": {
        "tenant_slug": "VARCHAR(100)",
        "text": "TEXT",
        "media_ids": "TEXT",
        "page_ids": "TEXT",
        "facebook_post_ids": "TEXT",
        "status": "VARCHAR(30)",
        "publish_type": "VARCHAR(20)",
        "publish_time": "DATETIME",
        "visibility": "VARCHAR(20) DEFAULT 'public'",
        "error_message": "TEXT",
        "created_at": "DATETIME",
    },
}

_SCHEMA_LOCK = Lock()
_LAST_SCHEMA_CHECK: Dict[str, float] = {}
_SCHEMA_CHECK_INTERVAL_SECONDS = 300


def _bind_key(engine) -> str:
    tenant = getattr(g, "tenant", None)
    if tenant:
        return f"tenant:{tenant}"
    try:
        return f"core:{engine.url}"
    except Exception:
        return "core"


def _active_engine():
    try:
        return db.session.get_bind()
    except Exception:
        return db.engine


def ensure_publisher_schema(*, force: bool = False) -> None:
    """
    Best-effort schema repair on the ACTIVE bind (tenant SQLite or core):
    - create missing publisher tables
    - ALTER TABLE ADD COLUMN for missing legacy columns
    """
    engine = _active_engine()
    key = _bind_key(engine)
    now = time.time()
    if (not force) and (now - _LAST_SCHEMA_CHECK.get(key, 0.0) < _SCHEMA_CHECK_INTERVAL_SECONDS):
        return

    with _SCHEMA_LOCK:
        now = time.time()
        if (not force) and (now - _LAST_SCHEMA_CHECK.get(key, 0.0) < _SCHEMA_CHECK_INTERVAL_SECONDS):
            return

        added = False
        try:
            db.session.rollback()
        except Exception:
            pass

        try:
            tables = [
                db.metadata.tables[name]
                for name in PUBLISHER_TABLES
                if name in db.metadata.tables
            ]
            if tables:
                db.metadata.create_all(bind=engine, tables=tables)
            else:
                db.metadata.create_all(bind=engine)
        except Exception:
            current_app.logger.error(traceback.format_exc())

        try:
            inspector = inspect(engine)
            try:
                inspector.clear_cache()
            except Exception:
                pass
            table_names = set(inspector.get_table_names())
        except Exception:
            current_app.logger.error(traceback.format_exc())
            return

        conn = engine.connect()
        trans = conn.begin()
        try:
            if conn.dialect.name == "postgresql":
                conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext('finora_publisher_schema'))")
                )
            for table_name, expected_columns in PUBLISHER_TABLES.items():
                if table_name not in table_names:
                    continue
                existing_columns = _live_columns(conn, table_name)
                if not existing_columns:
                    continue
                for col_name, col_type in expected_columns.items():
                    if col_name in existing_columns:
                        continue
                    ddl_type = (
                        "TIMESTAMP"
                        if conn.dialect.name == "postgresql" and col_type == "DATETIME"
                        else col_type
                    )
                    _add_column(conn, table_name, col_name, ddl_type)
                    added = True
                    existing_columns.add(col_name)
            trans.commit()
            _LAST_SCHEMA_CHECK[key] = time.time()
        except Exception:
            trans.rollback()
            current_app.logger.error(traceback.format_exc())
        finally:
            conn.close()

        if added:
            _refresh_connections(engine)


def _add_column(conn, table_name: str, col_name: str, ddl_type: str) -> None:
    if conn.dialect.name == "postgresql":
        conn.execute(
            text(
                f'ALTER TABLE "{table_name}" '
                f'ADD COLUMN IF NOT EXISTS "{col_name}" {ddl_type}'
            )
        )
        return
    try:
        conn.execute(
            text(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN IF NOT EXISTS {col_name} {ddl_type}"
            )
        )
    except Exception as alter_exc:
        message = str(alter_exc).lower()
        if "duplicate" in message or "exists" in message:
            return
        try:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {ddl_type}"))
        except Exception as fallback_exc:
            fallback = str(fallback_exc).lower()
            if "duplicate" not in fallback and "exists" not in fallback:
                raise


def _live_columns(conn, table_name: str) -> set:
    """Read columns from the database itself, not a cached inspector."""
    try:
        if conn.dialect.name == "sqlite":
            rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            return {row[1] for row in rows}
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :table_name"
            ),
            {"table_name": table_name},
        ).fetchall()
        return {str(row[0]) for row in rows}
    except Exception:
        current_app.logger.error(traceback.format_exc())
        return set()


def _refresh_connections(engine=None) -> None:
    """Drop pooled connections that still see the schema from before ALTER."""
    try:
        db.session.remove()
    except Exception:
        pass
    tenant = getattr(g, "tenant", None)
    if tenant:
        try:
            from extensions_tenant import clear_tenant_engine

            clear_tenant_engine(tenant)
            return
        except Exception:
            pass
    target = engine or db.engine
    try:
        target.dispose()
    except Exception:
        pass
