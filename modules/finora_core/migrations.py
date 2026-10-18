"""Versioned FINORA CORE schema migrations for the Core DB (PostgreSQL in production, any SQLAlchemy dialect).

Every change is a numbered step with an upgrade and a downgrade. Run with:
  flask finora-core-db upgrade | downgrade --to N | current
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

META_TABLE = "fc_schema_meta"


def _v1_up(engine: Engine) -> None:
    from .models import FC_TABLES

    for table in FC_TABLES:
        table.create(bind=engine, checkfirst=True)


def _v1_down(engine: Engine) -> None:
    from .models import FC_TABLES

    for table in reversed(FC_TABLES):
        table.drop(bind=engine, checkfirst=True)


def _v2_up(engine: Engine) -> None:
    from .brain.models import BRAIN_TABLES

    for table in BRAIN_TABLES:
        table.create(bind=engine, checkfirst=True)


def _v2_down(engine: Engine) -> None:
    from .brain.models import BRAIN_TABLES

    for table in reversed(BRAIN_TABLES):
        table.drop(bind=engine, checkfirst=True)


def _v3_up(engine: Engine) -> None:
    """Phase 9: shadow proposals, merge ledger, knowledge events + additive columns on the v2 tables.

    A fresh database already gets the v3 columns from v2's ``create`` (same models), so columns are added only when
    missing — the step is idempotent on both fresh and upgraded databases."""
    from sqlalchemy import inspect

    from .brain.models import BRAIN_TABLES, V3_COLUMNS, V3_TABLES

    for table in V3_TABLES:
        table.create(bind=engine, checkfirst=True)
    by_name = {t.name: t for t in BRAIN_TABLES}
    inspector = inspect(engine)
    for table_name, columns in V3_COLUMNS.items():
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        for name in columns:
            if name in existing:
                continue
            column = by_name[table_name].c[name]
            ddl = f"ALTER TABLE {table_name} ADD COLUMN {name} {column.type.compile(dialect=engine.dialect)}"
            default = getattr(column.default, "arg", None)
            if isinstance(default, (int, float)) and not isinstance(default, bool):
                ddl += f" NOT NULL DEFAULT {default}"
            elif isinstance(default, str):
                ddl += f" NOT NULL DEFAULT '{default}'"
            with engine.begin() as conn:
                conn.execute(text(ddl))
                if column.index:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_{name} ON {table_name} ({name})"))


def _v3_down(engine: Engine) -> None:
    from sqlalchemy import inspect

    from .brain.models import V3_COLUMNS, V3_TABLES

    for table in reversed(V3_TABLES):
        table.drop(bind=engine, checkfirst=True)
    inspector = inspect(engine)
    for table_name, columns in V3_COLUMNS.items():
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        indexes = inspector.get_indexes(table_name)
        for name in columns:
            if name not in existing:
                continue
            with engine.begin() as conn:
                for index in indexes:  # SQLite refuses to drop an indexed column
                    if name in (index.get("column_names") or []):
                        conn.execute(text(f"DROP INDEX IF EXISTS {index['name']}"))
                conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {name}"))


def _v4_up(engine: Engine) -> None:
    from .brain.support import FcSupportIssue
    FcSupportIssue.__table__.create(bind=engine, checkfirst=True)


def _v4_down(engine: Engine) -> None:
    from .brain.support import FcSupportIssue
    FcSupportIssue.__table__.drop(bind=engine, checkfirst=True)


STEPS: dict[int, tuple[Callable[[Engine], None], Callable[[Engine], None]]] = {
    1: (_v1_up, _v1_down),
    2: (_v2_up, _v2_down),  # Phase 8: customers, memory, knowledge, agent runs, tools, approvals, onboarding
    3: (_v3_up, _v3_down),  # Phase 9: shadow mode, memory evidence, approval plans, merge ledger, knowledge, traces
    4: (_v4_up, _v4_down),  # Owner support inbox.
}
TARGET_VERSION = max(STEPS)


def _ensure_meta(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(f"CREATE TABLE IF NOT EXISTS {META_TABLE} (key VARCHAR(40) PRIMARY KEY, value VARCHAR(40) NOT NULL)")
        )


def current_version(engine: Engine) -> int:
    _ensure_meta(engine)
    with engine.begin() as conn:
        row = conn.execute(text(f"SELECT value FROM {META_TABLE} WHERE key = 'version'")).fetchone()
    return int(row[0]) if row else 0


def _set_version(engine: Engine, version: int) -> None:
    with engine.begin() as conn:
        updated = conn.execute(text(f"UPDATE {META_TABLE} SET value = :v WHERE key = 'version'"), {"v": str(version)})
        if not updated.rowcount:
            conn.execute(text(f"INSERT INTO {META_TABLE} (key, value) VALUES ('version', :v)"), {"v": str(version)})


def upgrade(engine: Engine, to: int = TARGET_VERSION) -> int:
    version = current_version(engine)
    while version < to:
        version += 1
        logger.info("finora_core schema upgrade → v%s", version)
        STEPS[version][0](engine)
        _set_version(engine, version)
    return version


def downgrade(engine: Engine, to: int = 0) -> int:
    version = current_version(engine)
    while version > to:
        logger.info("finora_core schema downgrade v%s → v%s", version, version - 1)
        STEPS[version][1](engine)
        version -= 1
        _set_version(engine, version)
    return version
