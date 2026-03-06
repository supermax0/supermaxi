#!/usr/bin/env python3
"""
Migrate core database from SQLite to PostgreSQL.
Run from project root. Requires DATABASE_URL set to PostgreSQL.

Usage:
  export DATABASE_URL=postgresql://finora:password@localhost/finora_db
  python scripts/migrate_sqlite_to_postgres.py

Ensure PostgreSQL tables exist first: flask db upgrade (or run app once with POSTGRES URL).
"""
import os
import sys

# Project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    from sqlalchemy import create_engine, text, MetaData, Table
    from sqlalchemy.engine import reflection

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sqlite_path = os.path.join(base_dir, "database.db")
    if not os.path.exists(sqlite_path):
        print(f"SQLite database not found: {sqlite_path}")
        sys.exit(1)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url or "postgresql" not in database_url:
        print("Set DATABASE_URL to PostgreSQL. Example:")
        print("  export DATABASE_URL=postgresql://finora:password@localhost/finora_db")
        sys.exit(1)

    sqlite_uri = f"sqlite:///{sqlite_path}"
    sqlite_engine = create_engine(sqlite_uri)
    pg_engine = create_engine(database_url)

    # Core tables only (order matters if there are FKs; core tables have no cross-FKs)
    core_tables = [
        "super_admins",
        "tenants",
        "payment_requests",
        "subscription_plans",
        "global_settings",
    ]

    inspector_sqlite = reflection.Inspector.from_engine(sqlite_engine)
    inspector_pg = reflection.Inspector.from_engine(pg_engine)
    pg_tables = inspector_pg.get_table_names()

    for table_name in core_tables:
        if table_name not in inspector_sqlite.get_table_names():
            print(f"  Skip {table_name} (not in SQLite)")
            continue
        if table_name not in pg_tables:
            print(f"  Skip {table_name} (not in PostgreSQL; run flask db upgrade first)")
            continue

        with sqlite_engine.connect() as src:
            rows = src.execute(text(f"SELECT * FROM {table_name}")).fetchall()
        cols = [c["name"] for c in inspector_sqlite.get_columns(table_name)]
        n = len(rows)
        if n == 0:
            print(f"  {table_name}: 0 rows")
            continue

        with pg_engine.connect() as dst:
            for row in rows:
                col_list = ", ".join(cols)
                placeholders = ", ".join(":{}".format(c) for c in cols)
                stmt = text(
                    f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})"
                )
                try:
                    dst.execute(stmt, dict(zip(cols, row)))
                except Exception as e:
                    if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                        pass
                    else:
                        dst.rollback()
                        raise
            dst.commit()
        print(f"  {table_name}: {n} rows migrated")

    print("Done.")
    sqlite_engine.dispose()
    pg_engine.dispose()

if __name__ == "__main__":
    main()
