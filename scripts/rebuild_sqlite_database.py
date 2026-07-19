#!/usr/bin/env python3
"""Rebuild a SQLite database into a clean file while preserving readable data."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def rebuild(source_path: str, output_path: str) -> dict:
    if os.path.abspath(source_path) == os.path.abspath(output_path):
        raise ValueError("Output path must differ from source path")
    if os.path.exists(output_path):
        os.unlink(output_path)

    started_at = time.monotonic()
    source = sqlite3.connect(source_path, timeout=30)
    output = sqlite3.connect(output_path, timeout=30)
    output.execute("PRAGMA foreign_keys=OFF")
    objects = source.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
        ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, rowid
        """
    ).fetchall()
    tables = [row for row in objects if row[0] == "table"]
    secondary_objects = [row for row in objects if row[0] != "table"]
    copied_rows: dict[str, int] = {}

    try:
        for _object_type, table_name, _parent, create_sql in tables:
            output.execute(create_sql)
            columns = [row[1] for row in source.execute(f"PRAGMA table_info({_quoted(table_name)})")]
            if not columns:
                continue
            column_sql = ",".join(_quoted(column) for column in columns)
            placeholders = ",".join("?" for _column in columns)
            cursor = source.execute(f"SELECT {column_sql} FROM {_quoted(table_name)}")
            inserted = 0
            verb = "INSERT OR IGNORE" if table_name == "activity_log" else "INSERT"
            while True:
                rows = cursor.fetchmany(1000)
                if not rows:
                    break
                output.executemany(
                    f"{verb} INTO {_quoted(table_name)} ({column_sql}) VALUES ({placeholders})",
                    rows,
                )
                inserted += len(rows)
            copied_rows[table_name] = inserted
            output.commit()

        if "activity_log" in copied_rows:
            output.execute(
                """
                UPDATE activity_log
                SET employee_id = NULL
                WHERE employee_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM employee WHERE employee.id = activity_log.employee_id)
                """
            )
            output.execute(
                """
                UPDATE activity_log
                SET branch_id = NULL
                WHERE branch_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM branch WHERE branch.id = activity_log.branch_id)
                """
            )

        for _object_type, _name, _parent, create_sql in secondary_objects:
            output.execute(create_sql)
        output.commit()

        integrity = [row[0] for row in output.execute("PRAGMA integrity_check").fetchall()]
        foreign_key_errors = output.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != ["ok"]:
            raise RuntimeError(f"Integrity check failed: {integrity[:10]}")
        if foreign_key_errors:
            raise RuntimeError(f"Foreign key check failed: {foreign_key_errors[:10]}")

        journal_mode = output.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        output.execute("PRAGMA synchronous=NORMAL")
        output.commit()
        return {
            "status": "ok",
            "tables": len(tables),
            "secondary_objects": len(secondary_objects),
            "activity_rows_scanned": copied_rows.get("activity_log", 0),
            "activity_rows_preserved": output.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
            if "activity_log" in copied_rows
            else 0,
            "journal_mode": journal_mode,
            "duration_seconds": round(time.monotonic() - started_at, 2),
            "output_bytes": os.path.getsize(output_path),
        }
    finally:
        source.close()
        output.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()
    print(json.dumps(rebuild(args.source, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
