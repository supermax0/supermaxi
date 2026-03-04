import sqlite3
import os

db_path = r"c:\Users\msi\Desktop\مجلد جديد (2)\accounting_system\database.db"
print(f"Checking schema for {db_path}...")

if not os.path.exists(db_path):
    print("Core database not found!")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(product)")
    columns = [row[1] for row in cursor.fetchall()]
    print(f"Columns in 'product' table (Core DB): {columns}")
    conn.close()

# Also check a tenant DB if possible
tenants_dir = r"c:\Users\msi\Desktop\مجلد جديد (2)\accounting_system\tenants"
if os.path.exists(tenants_dir):
    files = [f for f in os.listdir(tenants_dir) if f.endswith(".db")]
    if files:
        tenant_db = os.path.join(tenants_dir, files[0])
        print(f"Checking schema for tenant DB: {tenant_db}...")
        conn = sqlite3.connect(tenant_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(product)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"Columns in 'product' table (Tenant DB): {columns}")
        conn.close()
    else:
        print("No tenant DBs found.")
else:
    print("Tenants directory not found.")
