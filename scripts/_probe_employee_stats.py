"""Quick probe: why employee orders/sales/commission show zero."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
db = ROOT / "tenants" / "super.db"
if not db.exists():
    raise SystemExit(f"DB not found: {db}")

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("=== Employees ===")
for r in c.execute("SELECT id, name, username, commission_percent FROM employee"):
    print(dict(r))

print("\n=== Invoice counts ===")
row = c.execute(
    """
    SELECT
      COUNT(*) AS total,
      SUM(CASE WHEN employee_id IS NOT NULL THEN 1 ELSE 0 END) AS with_emp,
      SUM(CASE WHEN payment_status = 'مسدد' OR status = 'مسدد' THEN 1 ELSE 0 END) AS paid,
      SUM(CASE WHEN employee_id IS NOT NULL AND (payment_status = 'مسدد' OR status = 'مسدد') THEN 1 ELSE 0 END) AS paid_with_emp,
      SUM(CASE WHEN employee_id IS NOT NULL AND (payment_status = 'مسدد' OR status = 'مسدد') AND employee_commission_settled_at IS NULL THEN 1 ELSE 0 END) AS unsettled_comm
    FROM invoice
    """
).fetchone()
print(dict(row))

print("\n=== Status breakdown (with employee_id) ===")
for r in c.execute(
    """
    SELECT status, payment_status, COUNT(*) AS cnt
    FROM invoice WHERE employee_id IS NOT NULL
    GROUP BY status, payment_status ORDER BY cnt DESC LIMIT 15
    """
):
    print(dict(r))

print("\n=== Per employee (all invoices) ===")
for r in c.execute(
    """
    SELECT e.id, e.name, COUNT(i.id) AS orders, COALESCE(SUM(i.total), 0) AS sales
    FROM employee e LEFT JOIN invoice i ON i.employee_id = e.id
    GROUP BY e.id ORDER BY orders DESC
    """
):
    print(dict(r))

print("\n=== Per employee (paid + unsettled commission) ===")
for r in c.execute(
    """
    SELECT e.id, e.name, COUNT(i.id) AS orders, COALESCE(SUM(i.total), 0) AS sales
    FROM employee e
    LEFT JOIN invoice i ON i.employee_id = e.id
      AND (i.payment_status = 'مسدد' OR i.status = 'مسدد')
      AND i.employee_commission_settled_at IS NULL
      AND i.status NOT IN ('ملغي', 'راجع', 'مرتجع', 'راجعة', 'راجعه')
      AND (i.payment_status IS NULL OR i.payment_status NOT IN ('ملغي', 'راجع', 'مرتجع', 'راجعة', 'راجعه'))
    GROUP BY e.id ORDER BY orders DESC
    """
):
    print(dict(r))

print("\n=== Invoices missing employee_id but have employee_name ===")
row = c.execute(
    """
    SELECT COUNT(*) AS cnt FROM invoice
    WHERE employee_id IS NULL AND employee_name IS NOT NULL AND employee_name != ''
    """
).fetchone()
print(dict(row))
