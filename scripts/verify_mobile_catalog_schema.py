"""Verify the normalized mobile catalog category projection in a tenant DB."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def inspect_catalog_schema(database: Path) -> dict:
    connection = sqlite3.connect(str(database))
    try:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(product)")
        }
        indexes = {
            str(row[1]) for row in connection.execute("PRAGMA index_list(product)")
        }
        has_column = "catalog_category" in columns
        backfilled = 0
        if has_column:
            backfilled = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM product
                    WHERE COALESCE(catalog_category, '') <> ''
                    """
                ).fetchone()[0]
            )
        return {
            "database": str(database),
            "catalog_category_column": has_column,
            "catalog_category_index": any(
                "catalog_category" in name for name in indexes
            ),
            "backfilled_products": backfilled,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error(f"database not found: {args.database}")
    report = inspect_catalog_schema(args.database)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["catalog_category_column"] and report["catalog_category_index"] else 2


if __name__ == "__main__":
    sys.exit(main())
