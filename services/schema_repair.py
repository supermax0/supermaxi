"""
Auto-align tenant SQLite schema with SQLAlchemy models: missing tables + missing columns.

Core-only tables (hosted on the main app DB) are never created on tenant DBs.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.schema import Column, Table

# Tables that belong to the SaaS / core database only — do not create on tenant SQLite.
_CORE_ONLY_TABLES: frozenset[str] = frozenset(
    {
        "super_admins",
        "tenants",
        "global_settings",
        "landing_visits",
        "payment_requests",
        "subscription_plans",
        "users",
        "invoice_templates",
        "tenant_template_purchases",
        "tenant_template_settings",
    }
)


def _register_models_for_metadata() -> None:
    """Import model modules so db.Model.metadata is populated for tenant features."""
    import models  # noqa: F401

    import models.agent_message  # noqa: F401
    import models.comment_log  # noqa: F401
    import models.delivery_agent  # noqa: F401
    import models.invoice_settings  # noqa: F401
    import models.page  # noqa: F401
    import models.pos_ai_log  # noqa: F401
    import models.report  # noqa: F401
    import models.social_account  # noqa: F401
    import models.social_post  # noqa: F401
    import models.social_post_platform  # noqa: F401
    import models.supplier_invoice  # noqa: F401
    import models.supplier_payment  # noqa: F401
    import models.system_settings  # noqa: F401


def _quote_ident(name: str) -> str:
    return name.replace('"', '""')


def _add_column_sql(engine, table: Table, column: Column) -> str | None:
    """Build ADD COLUMN DDL for the engine dialect (tenant DBs are SQLite)."""
    if getattr(column, "computed", None) is not None:
        return None
    dialect = engine.dialect.name
    col_sql = column.type.compile(dialect=engine.dialect)
    tq = _quote_ident(table.name)
    cq = _quote_ident(column.name)
    if dialect == "sqlite":
        # SQLite: new columns are nullable by default; avoid NOT NULL without DEFAULT.
        return f'ALTER TABLE "{tq}" ADD COLUMN "{cq}" {col_sql}'
    if dialect == "postgresql":
        return f'ALTER TABLE "{tq}" ADD COLUMN "{cq}" {col_sql}'
    # Generic fallback
    return f'ALTER TABLE "{tq}" ADD COLUMN "{cq}" {col_sql}'


def repair_tenant_schema(engine, *, dry_run: bool = True) -> dict[str, Any]:
    """
    Compare live DB to SQLAlchemy metadata; optionally apply fixes.

    Returns a report dict with planned/applied actions.
    """
    from extensions import db

    _register_models_for_metadata()
    metadata = db.Model.metadata
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    report: dict[str, Any] = {
        "dry_run": dry_run,
        "dialect": engine.dialect.name,
        "tables_created": [],
        "columns_added": [],
        "sql_executed": [],
        "warnings": [],
        "errors": [],
    }

    # --- Missing tables (tenant-safe subset) ---
    missing_table_names: list[str] = []
    for tname, _tbl in metadata.tables.items():
        if tname in _CORE_ONLY_TABLES:
            continue
        if tname not in existing_tables:
            missing_table_names.append(tname)

    tables_to_create = [metadata.tables[n] for n in sorted(missing_table_names) if n in metadata.tables]

    if tables_to_create:
        if dry_run:
            report["tables_created"] = [t.name for t in tables_to_create]
        else:
            try:
                metadata.create_all(engine, tables=tables_to_create, checkfirst=True)
                report["tables_created"] = [t.name for t in tables_to_create]
            except Exception as e:
                report["errors"].append({"phase": "create_all", "error": str(e)})

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    # --- Missing columns on existing tables ---
    for tname in sorted(existing_tables):
        if tname not in metadata.tables:
            continue
        meta_table = metadata.tables[tname]
        try:
            db_cols = {c["name"] for c in inspector.get_columns(tname)}
        except Exception as e:
            report["warnings"].append({"table": tname, "message": f"skip columns: {e}"})
            continue

        for col in meta_table.columns:
            if col.name in db_cols:
                continue
            if getattr(col, "computed", None) is not None:
                continue
            ddl = _add_column_sql(engine, meta_table, col)
            if not ddl:
                continue
            entry = {"table": tname, "column": col.name, "sql": ddl}
            if dry_run:
                report["columns_added"].append(entry)
            else:
                try:
                    with engine.begin() as conn:
                        conn.execute(text(ddl))
                    report["columns_added"].append(entry)
                    report["sql_executed"].append(ddl)
                    db_cols.add(col.name)
                except Exception as e:
                    report["errors"].append({"phase": "add_column", "table": tname, "column": col.name, "error": str(e)})

    return report
