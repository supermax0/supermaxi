import os
import sqlite3

from app import app

with app.app_context():
    tenants_dir = os.path.join(app.root_path, "tenants")
    total = 0
    for db_name in sorted(os.listdir(tenants_dir)):
        if not db_name.endswith(".db"):
            continue
        db_path = os.path.join(tenants_dir, db_name)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='invoice'"
        )
        if not cur.fetchone():
            conn.close()
            continue
        cur.execute(
            "UPDATE invoice SET status = ? WHERE status = ? AND payment_status = ?",
            ("تم التوصيل", "مسدد", "مسدد"),
        )
        n = cur.rowcount or 0
        conn.commit()
        conn.close()
        if n:
            print(db_name, n)
            total += n
    print("total", total)
