"""
Versioned Phone App schema migrations for tenant databases.

Finora uses one physical DB per tenant (not a single Alembic chain).
This module is the official upgrade/downgrade path for phone_app tables.

Commands (from project root, with tenant context):
  flask phone-db upgrade --tenant <slug>
  flask phone-db upgrade-all
  flask phone-db downgrade --tenant <slug> --to 0
  flask phone-db current --tenant <slug>
"""

from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)

SCHEMA_META_TABLE = "phone_schema_meta"
TARGET_VERSION = 4


def _engine():
    from flask import g
    from extensions import db

    if getattr(g, "tenant", None):
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(g.tenant)
    return db.engine


def _dialect_types(engine):
    if engine.dialect.name == "postgresql":
        return {
            "dt": "TIMESTAMP",
            "bool": "BOOLEAN",
            "text": "TEXT",
            "int": "INTEGER",
            "str": "VARCHAR",
        }
    return {
        "dt": "DATETIME",
        "bool": "INTEGER",
        "text": "TEXT",
        "int": "INTEGER",
        "str": "VARCHAR",
    }


def _ensure_meta(conn) -> None:
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA_META_TABLE} (
                key VARCHAR(64) PRIMARY KEY,
                value VARCHAR(64) NOT NULL
            )
            """
        )
    )


def get_schema_version(engine=None) -> int:
    engine = engine or _engine()
    with engine.begin() as conn:
        _ensure_meta(conn)
        row = conn.execute(
            text(f"SELECT value FROM {SCHEMA_META_TABLE} WHERE key = 'version'")
        ).fetchone()
        if not row:
            return 0
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return 0


def set_schema_version(version: int, engine=None) -> None:
    engine = engine or _engine()
    with engine.begin() as conn:
        _ensure_meta(conn)
        existing = conn.execute(
            text(f"SELECT value FROM {SCHEMA_META_TABLE} WHERE key = 'version'")
        ).fetchone()
        if existing:
            conn.execute(
                text(
                    f"UPDATE {SCHEMA_META_TABLE} SET value = :v WHERE key = 'version'"
                ),
                {"v": str(version)},
            )
        else:
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA_META_TABLE} (key, value) VALUES ('version', :v)"
                ),
                {"v": str(version)},
            )


def _table_exists(inspector, name: str) -> bool:
    return name in set(inspector.get_table_names())


def _cols(inspector, table: str) -> set[str]:
    if not _table_exists(inspector, table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _add_col(conn, inspector, table: str, name: str, ddl: str) -> None:
    if name in _cols(inspector, table):
        return
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _create_index(conn, engine, name: str, table: str, cols: str, unique: bool = False) -> None:
    u = "UNIQUE " if unique else ""
    # IF NOT EXISTS supported by SQLite 3.9+ and Postgres
    try:
        conn.execute(text(f"CREATE {u}INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
    except Exception as exc:
        msg = str(exc).lower()
        if "already exists" in msg or "duplicate" in msg:
            return
        # SQLite older: retry without IF NOT EXISTS
        try:
            conn.execute(text(f"CREATE {u}INDEX {name} ON {table} ({cols})"))
        except Exception as exc2:
            msg2 = str(exc2).lower()
            if "already exists" not in msg2 and "duplicate" not in msg2:
                logger.warning("index %s failed: %s", name, exc2)


def upgrade_to_v1(engine) -> None:
    """Create base phone tables (nullable-friendly)."""
    t = _dialect_types(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS phone_refresh_token (
                    id {t['int']} PRIMARY KEY,
                    employee_id {t['int']} NOT NULL,
                    token_hash VARCHAR(64) NOT NULL,
                    device_id VARCHAR(128) NOT NULL,
                    expires_at {t['dt']} NOT NULL,
                    revoked_at {t['dt']},
                    created_at {t['dt']} NOT NULL
                )
                """
            )
        )
        # SQLite needs AUTOINCREMENT differently — use ORM create for PK if empty
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS phone_app_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    employee_id INTEGER NOT NULL,
                    device_uuid VARCHAR(128) NOT NULL,
                    device_name VARCHAR(120),
                    manufacturer VARCHAR(80),
                    model VARCHAR(120),
                    android_version VARCHAR(40),
                    app_version VARCHAR(40),
                    push_token VARCHAR(512),
                    sim_slots_count INTEGER,
                    last_seen_at {t['dt']},
                    registered_at {t['dt']} NOT NULL,
                    revoked_at {t['dt']},
                    is_active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS phone_call_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    employee_id INTEGER NOT NULL,
                    customer_id INTEGER,
                    phone_e164 VARCHAR(32) NOT NULL,
                    phone_normalized VARCHAR(32),
                    direction VARCHAR(16) NOT NULL DEFAULT 'inbound',
                    call_status VARCHAR(24) NOT NULL DEFAULT 'detected',
                    sync_status VARCHAR(24) NOT NULL DEFAULT 'pending',
                    started_at {t['dt']} NOT NULL,
                    ended_at {t['dt']},
                    duration_sec INTEGER,
                    detected_at {t['dt']},
                    ringing_at {t['dt']},
                    dialing_at {t['dt']},
                    answered_at {t['dt']},
                    cancelled_at {t['dt']},
                    failed_at {t['dt']},
                    server_received_at {t['dt']},
                    client_id VARCHAR(128) NOT NULL,
                    local_call_uuid VARCHAR(64),
                    idempotency_key VARCHAR(191),
                    device_id VARCHAR(128),
                    sim_slot INTEGER,
                    synced_note TEXT,
                    created_at {t['dt']} NOT NULL,
                    updated_at {t['dt']} NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS phone_call_note (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_id INTEGER,
                    employee_id INTEGER NOT NULL,
                    customer_id INTEGER,
                    body TEXT NOT NULL,
                    client_id VARCHAR(64) NOT NULL,
                    created_at {t['dt']} NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS phone_followup_task (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    employee_id INTEGER NOT NULL,
                    customer_id INTEGER,
                    phone VARCHAR(32) NOT NULL,
                    phone_normalized VARCHAR(32),
                    call_id INTEGER,
                    title VARCHAR(255) NOT NULL,
                    due_at {t['dt']},
                    status VARCHAR(32) NOT NULL DEFAULT 'open',
                    source VARCHAR(32) NOT NULL DEFAULT 'missed_call',
                    task_type VARCHAR(32) NOT NULL DEFAULT 'missed_call_followup',
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    client_id VARCHAR(64) NOT NULL,
                    created_at {t['dt']} NOT NULL,
                    updated_at {t['dt']} NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS phone_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER,
                    device_id VARCHAR(128),
                    action VARCHAR(64) NOT NULL,
                    detail TEXT,
                    created_at {t['dt']} NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS phone_order_draft (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    employee_id INTEGER NOT NULL,
                    customer_id INTEGER NOT NULL,
                    client_id VARCHAR(64) NOT NULL,
                    idempotency_key VARCHAR(128) NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'draft',
                    payload_json TEXT NOT NULL,
                    invoice_id INTEGER,
                    created_at {t['dt']} NOT NULL,
                    updated_at {t['dt']} NOT NULL,
                    confirmed_at {t['dt']}
                )
                """
            )
        )


def upgrade_to_v2(engine) -> None:
    """Add columns/indexes/constraints safely for existing installs."""
    t = _dialect_types(engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        # Refresh token columns already base.
        if _table_exists(inspector, "phone_call_log"):
            for name, ddl in (
                ("phone_normalized", "VARCHAR(32)"),
                ("call_status", "VARCHAR(24) DEFAULT 'detected'"),
                ("sync_status", "VARCHAR(24) DEFAULT 'pending'"),
                ("dialing_at", t["dt"]),
                ("cancelled_at", t["dt"]),
                ("failed_at", t["dt"]),
                ("server_received_at", t["dt"]),
                ("local_call_uuid", "VARCHAR(64)"),
                ("idempotency_key", "VARCHAR(191)"),
                ("device_id", "VARCHAR(128)"),
                ("sim_slot", "INTEGER"),
                ("detected_at", t["dt"]),
                ("ringing_at", t["dt"]),
                ("answered_at", t["dt"]),
            ):
                _add_col(conn, inspector, "phone_call_log", name, ddl)

            # Backfill call_status from legacy status column if present.
            cols = _cols(inspect(engine), "phone_call_log")
            if "status" in cols and "call_status" in cols:
                conn.execute(
                    text(
                        """
                        UPDATE phone_call_log
                        SET call_status = CASE
                            WHEN status IN ('synced') THEN 'ended'
                            WHEN status IS NULL OR status = '' THEN 'detected'
                            ELSE status
                        END
                        WHERE call_status IS NULL OR call_status = '' OR call_status = 'detected'
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE phone_call_log
                        SET sync_status = CASE
                            WHEN status = 'synced' THEN 'synced'
                            ELSE COALESCE(sync_status, 'pending')
                        END
                        """
                    )
                )
            conn.execute(
                text(
                    """
                    UPDATE phone_call_log
                    SET phone_normalized = phone_e164
                    WHERE phone_normalized IS NULL OR phone_normalized = ''
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE phone_call_log
                    SET local_call_uuid = client_id
                    WHERE (local_call_uuid IS NULL OR local_call_uuid = '')
                      AND client_id IS NOT NULL
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE phone_call_log
                    SET idempotency_key = client_id
                    WHERE (idempotency_key IS NULL OR idempotency_key = '')
                      AND client_id IS NOT NULL
                    """
                )
            )

        if _table_exists(inspector, "phone_followup_task"):
            for name, ddl in (
                ("phone_normalized", "VARCHAR(32)"),
                ("task_type", "VARCHAR(32) DEFAULT 'missed_call_followup'"),
                ("attempt_count", "INTEGER DEFAULT 1"),
            ):
                _add_col(conn, inspector, "phone_followup_task", name, ddl)

        if not _table_exists(inspector, "phone_app_devices"):
            upgrade_to_v1(engine)
            inspector = inspect(engine)

        if not _table_exists(inspector, "phone_order_draft"):
            upgrade_to_v1(engine)

        # Indexes / unique constraints (nullable-safe unique via unique index)
        _create_index(conn, engine, "ix_phone_devices_uuid", "phone_app_devices", "device_uuid")
        _create_index(conn, engine, "ix_phone_devices_employee", "phone_app_devices", "employee_id")
        _create_index(conn, engine, "ix_phone_devices_revoked", "phone_app_devices", "revoked_at")
        _create_index(conn, engine, "ix_phone_devices_active", "phone_app_devices", "is_active")
        _create_index(
            conn,
            engine,
            "uq_phone_devices_emp_uuid",
            "phone_app_devices",
            "employee_id, device_uuid",
            unique=True,
        )

        _create_index(conn, engine, "ix_phone_call_phone_norm", "phone_call_log", "phone_normalized")
        _create_index(conn, engine, "ix_phone_call_employee", "phone_call_log", "employee_id")
        _create_index(conn, engine, "ix_phone_call_tenant_started", "phone_call_log", "tenant_id, started_at")
        _create_index(conn, engine, "ix_phone_call_local_uuid", "phone_call_log", "local_call_uuid")
        _create_index(conn, engine, "ix_phone_call_device", "phone_call_log", "device_id")
        _create_index(
            conn,
            engine,
            "uq_phone_call_tenant_idem",
            "phone_call_log",
            "tenant_id, idempotency_key",
            unique=True,
        )
        _create_index(
            conn,
            engine,
            "uq_phone_call_client_id",
            "phone_call_log",
            "client_id",
            unique=True,
        )

        _create_index(conn, engine, "ix_phone_task_status_due", "phone_followup_task", "status, due_at")
        _create_index(conn, engine, "ix_phone_task_phone_norm", "phone_followup_task", "phone_normalized")
        _create_index(
            conn,
            engine,
            "uq_phone_task_tenant_call_type",
            "phone_followup_task",
            "tenant_id, call_id, task_type",
            unique=True,
        )
        _create_index(
            conn,
            engine,
            "uq_phone_task_client",
            "phone_followup_task",
            "client_id",
            unique=True,
        )

        _create_index(
            conn,
            engine,
            "uq_phone_order_draft_idem",
            "phone_order_draft",
            "idempotency_key",
            unique=True,
        )
        _create_index(conn, engine, "ix_phone_order_draft_status", "phone_order_draft", "status")
        _create_index(
            conn,
            engine,
            "uq_phone_note_client",
            "phone_call_note",
            "client_id",
            unique=True,
        )


def upgrade_to_v3(engine) -> None:
    """Phase 2A: call outcomes + smart follow-up columns."""
    t = _dialect_types(engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        if _table_exists(inspector, "phone_call_log"):
            for name, ddl in (
                ("outcome", "VARCHAR(32)"),
                ("outcome_note", "TEXT"),
                ("follow_up_required", f"{t['bool']} DEFAULT 0"),
                ("follow_up_at", t["dt"]),
                ("outcome_recorded_at", t["dt"]),
                ("outcome_recorded_by", "INTEGER"),
                ("outcome_client_id", "VARCHAR(64)"),
            ):
                _add_col(conn, inspector, "phone_call_log", name, ddl)
            _create_index(
                conn, engine, "ix_phone_call_tenant_outcome", "phone_call_log", "tenant_id, outcome"
            )
            _create_index(
                conn,
                engine,
                "ix_phone_call_tenant_customer_started",
                "phone_call_log",
                "tenant_id, customer_id, started_at",
            )
            _create_index(
                conn,
                engine,
                "ix_phone_call_outcome_client",
                "phone_call_log",
                "outcome_client_id",
            )

        if _table_exists(inspector, "phone_followup_task"):
            for name, ddl in (
                ("priority", "VARCHAR(16) DEFAULT 'normal'"),
                ("reason", "VARCHAR(64)"),
                ("resolved_by_call_id", "INTEGER"),
                ("snoozed_until", t["dt"]),
            ):
                _add_col(conn, inspector, "phone_followup_task", name, ddl)
            _create_index(
                conn,
                engine,
                "ix_phone_task_priority_status",
                "phone_followup_task",
                "priority, status",
            )


def upgrade_to_v4(engine) -> None:
    """Call recordings: attachment metadata on phone_call_log."""
    t = _dialect_types(engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        if _table_exists(inspector, "phone_call_log"):
            for name, ddl in (
                ("recording_path", "VARCHAR(512)"),
                ("recording_size", "INTEGER"),
                ("recording_duration_sec", "INTEGER"),
                ("recording_mime", "VARCHAR(64)"),
                ("recording_uploaded_at", t["dt"]),
                ("recording_uploaded_by", "INTEGER"),
            ):
                _add_col(conn, inspector, "phone_call_log", name, ddl)
            _create_index(
                conn,
                engine,
                "ix_phone_call_recording",
                "phone_call_log",
                "tenant_id, recording_uploaded_at",
            )


def downgrade_to_v3(engine) -> None:
    """Best-effort: keep recording columns (non-destructive)."""
    logger.info("phone_app downgrade v4→v3: columns retained (non-destructive)")


def downgrade_to_v2(engine) -> None:
    """Best-effort: SQLite cannot DROP COLUMN reliably — leave columns, bump meta only."""
    logger.info("phone_app downgrade v3→v2: columns retained (non-destructive)")


def downgrade_to_v1(engine) -> None:
    """Best-effort downgrade: drop v2-only draft table; keep columns (SQLite can't drop easily)."""
    with engine.begin() as conn:
        try:
            conn.execute(text("DROP TABLE IF EXISTS phone_order_draft"))
        except Exception as exc:
            logger.warning("downgrade drop phone_order_draft: %s", exc)


def downgrade_to_v0(engine) -> None:
    """Drop all phone_app tables."""
    tables = [
        "phone_order_draft",
        "phone_followup_task",
        "phone_call_note",
        "phone_call_log",
        "phone_app_devices",
        "phone_refresh_token",
        "phone_audit_log",
        SCHEMA_META_TABLE,
    ]
    with engine.begin() as conn:
        for table in tables:
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
            except Exception as exc:
                logger.warning("downgrade drop %s: %s", table, exc)


UPGRADES: dict[int, Callable] = {
    1: upgrade_to_v1,
    2: upgrade_to_v2,
    3: upgrade_to_v3,
    4: upgrade_to_v4,
}

DOWNGRADES: dict[int, Callable] = {
    4: downgrade_to_v3,
    3: downgrade_to_v2,
    2: downgrade_to_v1,
    1: downgrade_to_v0,
}


def upgrade(target: int | None = None, engine=None) -> int:
    engine = engine or _engine()
    target = TARGET_VERSION if target is None else target
    current = get_schema_version(engine)
    # Detect legacy create_all installs (tables exist, meta missing)
    inspector = inspect(engine)
    if current == 0 and _table_exists(inspector, "phone_call_log"):
        current = 1
        set_schema_version(1, engine)
    while current < target:
        nxt = current + 1
        fn = UPGRADES.get(nxt)
        if not fn:
            raise RuntimeError(f"No upgrade path to version {nxt}")
        fn(engine)
        set_schema_version(nxt, engine)
        current = nxt
        logger.info("phone_app schema upgraded to v%s", current)
    return current


def downgrade(to_version: int = 0, engine=None) -> int:
    engine = engine or _engine()
    current = get_schema_version(engine)
    while current > to_version:
        fn = DOWNGRADES.get(current)
        if not fn:
            raise RuntimeError(f"No downgrade path from version {current}")
        fn(engine)
        current -= 1
        set_schema_version(current, engine)
        logger.info("phone_app schema downgraded to v%s", current)
    return current


def ensure_phone_app_schema(*, force: bool = False) -> int:
    """Idempotent ensure used by API before_request — runs pending upgrades only."""
    return upgrade(TARGET_VERSION)
