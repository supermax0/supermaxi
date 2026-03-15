"""
schema_guard.py
---------------
Self-healing DB schema guard for Publisher tables.
Creates missing tables and adds missing columns in-place for legacy deployments.
"""

from __future__ import annotations

import traceback
import time
from threading import Lock
from typing import Dict

from flask import current_app
from sqlalchemy import inspect, text

from extensions import db


PUBLISHER_TABLES: Dict[str, Dict[str, str]] = {
    "publisher_settings": {
        "tenant_slug": "VARCHAR(100)",
        "fb_app_id": "VARCHAR(50)",
        "fb_app_secret": "TEXT",
        "fb_user_token": "TEXT",
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
        "error_message": "TEXT",
        "created_at": "DATETIME",
    },
}

_SCHEMA_LOCK = Lock()
_LAST_SCHEMA_CHECK_TS = 0.0
_SCHEMA_CHECK_INTERVAL_SECONDS = 300


def ensure_publisher_schema() -> None:
    """
    Best-effort schema repair:
    - db.create_all() for missing tables
    - ALTER TABLE ADD COLUMN for missing legacy columns
    """
    global _LAST_SCHEMA_CHECK_TS
    now = time.time()
    if now - _LAST_SCHEMA_CHECK_TS < _SCHEMA_CHECK_INTERVAL_SECONDS:
        return

    with _SCHEMA_LOCK:
        now = time.time()
        if now - _LAST_SCHEMA_CHECK_TS < _SCHEMA_CHECK_INTERVAL_SECONDS:
            return

        try:
            db.create_all()
        except Exception:
            current_app.logger.error(traceback.format_exc())

        try:
            inspector = inspect(db.engine)
            table_names = set(inspector.get_table_names())
        except Exception:
            current_app.logger.error(traceback.format_exc())
            return

        conn = db.engine.connect()
        trans = conn.begin()
        try:
            for table_name, expected_columns in PUBLISHER_TABLES.items():
                if table_name not in table_names:
                    continue
                try:
                    existing_columns = {c["name"] for c in inspector.get_columns(table_name)}
                except Exception:
                    current_app.logger.error(traceback.format_exc())
                    continue
                for col_name, col_type in expected_columns.items():
                    if col_name in existing_columns:
                        continue
                    ddl = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
                    conn.execute(text(ddl))
            trans.commit()
            _LAST_SCHEMA_CHECK_TS = time.time()
        except Exception:
            trans.rollback()
            current_app.logger.error(traceback.format_exc())
        finally:
            conn.close()

