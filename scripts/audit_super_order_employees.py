"""Audit and restore original invoice employee attribution using activity_log create events."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "tenants" / "super.db"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_employee_names(conn: sqlite3.Connection) -> dict[int, str]:
    rows = conn.execute("SELECT id, name FROM employee").fetchall()
    return {int(r["id"]): str(r["name"] or "") for r in rows}


def build_fix_plan(conn: sqlite3.Connection) -> list[dict]:
    """Invoices edited via POS where current employee differs from create-log actor."""
    rows = conn.execute(
        """
        WITH creates AS (
          SELECT
            entity_id,
            employee_id AS create_emp,
            employee_name AS create_name,
            MIN(created_at) AS created_at
          FROM activity_log
          WHERE category = 'pos'
            AND entity_type = 'invoice'
            AND action = 'create'
            AND employee_id IS NOT NULL
          GROUP BY entity_id
        ),
        updates AS (
          SELECT entity_id, COUNT(1) AS update_count
          FROM activity_log
          WHERE category = 'pos'
            AND entity_type = 'invoice'
            AND action = 'update'
          GROUP BY entity_id
        )
        SELECT
          i.id AS invoice_id,
          i.customer_name,
          i.total,
          i.status,
          i.created_at,
          i.employee_id AS current_employee_id,
          i.employee_name AS current_employee_name,
          c.create_emp AS original_employee_id,
          c.create_name AS original_employee_name,
          c.created_at AS original_log_at,
          COALESCE(u.update_count, 0) AS update_log_count
        FROM invoice i
        JOIN creates c ON c.entity_id = CAST(i.id AS TEXT)
        INNER JOIN updates u ON u.entity_id = CAST(i.id AS TEXT)
        WHERE c.create_emp IS NOT NULL
          AND (i.employee_id IS NULL OR i.employee_id != c.create_emp)
        ORDER BY i.id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def apply_fixes(conn: sqlite3.Connection, fixes: list[dict], employee_names: dict[int, str]) -> int:
    updated = 0
    for fix in fixes:
        emp_id = int(fix["original_employee_id"])
        emp_name = fix["original_employee_name"] or employee_names.get(emp_id, "")
        conn.execute(
            "UPDATE invoice SET employee_id = ?, employee_name = ? WHERE id = ?",
            (emp_id, emp_name, fix["invoice_id"]),
        )
        updated += 1
    conn.commit()
    return updated


def export_report(fixes: list[dict], report_path: Path) -> None:
    report_path.write_text(json.dumps(fixes, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore original invoice employees from activity_log")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to tenant sqlite db")
    parser.add_argument("--apply", action="store_true", help="Apply fixes (default: dry-run)")
    parser.add_argument("--limit", type=int, default=0, help="Limit printed rows")
    parser.add_argument("--report", default="", help="Optional JSON report path")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    conn = connect(db_path)
    employee_names = load_employee_names(conn)
    fixes = build_fix_plan(conn)

    print(f"Database: {db_path}")
    print(f"Invoices to restore: {len(fixes)}")
    show = fixes if not args.limit else fixes[: args.limit]
    for fix in show:
        print(
            f"  #{fix['invoice_id']:>5} | {(fix['customer_name'] or '—')[:22]:22} | "
            f"{fix['current_employee_name'] or '—'} ({fix['current_employee_id']}) -> "
            f"{fix['original_employee_name'] or '—'} ({fix['original_employee_id']}) "
            f"[updates={fix['update_log_count']}]"
        )
    if args.limit and len(fixes) > args.limit:
        print(f"  ... and {len(fixes) - args.limit} more")

    if args.report:
        export_report(fixes, Path(args.report))
        print(f"Report saved: {args.report}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to update invoice rows.")
        conn.close()
        return

    if not fixes:
        print("Nothing to apply.")
        conn.close()
        return

    backup = db_path.with_suffix(f".pre-employee-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db")
    shutil.copy2(db_path, backup)
    print(f"\nBackup created: {backup}")

    count = apply_fixes(conn, fixes, employee_names)
    print(f"Updated {count} invoice(s).")
    conn.close()


if __name__ == "__main__":
    main()
