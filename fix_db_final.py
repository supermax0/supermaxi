import sqlite3
import os

def fix_db(db_path):
    if not os.path.exists(db_path):
        print(f"Skipping {db_path} - not found.")
        return
    
    print(f"Fixing {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Product table
    cursor.execute("PRAGMA table_info(product)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if "barcode" not in columns:
        try:
            cursor.execute("ALTER TABLE product ADD COLUMN barcode VARCHAR(100)")
            print("  Added barcode to product.")
        except Exception as e:
            print(f"  Error adding barcode: {e}")
            
    if "low_stock_threshold" not in columns:
        try:
            cursor.execute("ALTER TABLE product ADD COLUMN low_stock_threshold INTEGER DEFAULT 5")
            print("  Added low_stock_threshold to product.")
        except Exception as e:
            print(f"  Error adding low_stock_threshold: {e}")

    # 2. Invoice table
    cursor.execute("PRAGMA table_info(invoice)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if "page_id" not in columns:
        try:
            cursor.execute("ALTER TABLE invoice ADD COLUMN page_id INTEGER")
            print("  Added page_id to invoice.")
        except Exception as e:
            print(f"  Error adding page_id: {e}")
            
    if "page_name" not in columns:
        try:
            cursor.execute("ALTER TABLE invoice ADD COLUMN page_name VARCHAR(100)")
            print("  Added page_name to invoice.")
        except Exception as e:
            print(f"  Error adding page_name: {e}")

    # 3. Page table (visibility)
    cursor.execute("PRAGMA table_info(page)")
    try:
        page_columns = [row[1] for row in cursor.fetchall()]
        if "is_visible" not in page_columns:
            cursor.execute("ALTER TABLE page ADD COLUMN is_visible BOOLEAN DEFAULT 1")
            print("  Added is_visible to page.")
    except Exception:
        pass

    conn.commit()
    conn.close()

# Fix Core DB
fix_db(r"c:\Users\msi\Desktop\مجلد جديد (2)\accounting_system\database.db")

# Fix all Tenant DBs
tenants_dir = r"c:\Users\msi\Desktop\مجلد جديد (2)\accounting_system\tenants"
if os.path.exists(tenants_dir):
    for f in os.listdir(tenants_dir):
        if f.endswith(".db"):
            fix_db(os.path.join(tenants_dir, f))

print("All databases fixed.")
