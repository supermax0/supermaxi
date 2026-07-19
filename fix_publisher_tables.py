"""
Repair Publisher schema on the core database.

Publisher tables (publisher_posts, publisher_pages, etc.) live in the core DB,
not in per-tenant SQLite files. create_all() only creates missing tables; it
does not add new columns to existing tables. schema_guard handles both.
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from sqlalchemy import inspect

from app import app
from extensions import db
from modules.publisher.services.schema_guard import ensure_publisher_schema, PUBLISHER_TABLES


def fix_publisher_schema():
    with app.app_context():
        print("Repairing Publisher schema on core DB...")
        ensure_publisher_schema(force=True)

        inspector = inspect(db.engine)
        table_names = set(inspector.get_table_names())

        for table_name, expected_columns in PUBLISHER_TABLES.items():
            if table_name not in table_names:
                print(f"  MISSING TABLE: {table_name}")
                continue
            existing = {c["name"] for c in inspector.get_columns(table_name)}
            missing = [col for col in expected_columns if col not in existing]
            if missing:
                print(f"  {table_name}: still missing columns {missing}")
            else:
                print(f"  {table_name}: OK ({len(existing)} columns)")


if __name__ == "__main__":
    fix_publisher_schema()
    print("\nPublisher schema repair complete.")
