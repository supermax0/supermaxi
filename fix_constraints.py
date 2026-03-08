import os
import sqlite3
import shutil
from flask import Flask
from extensions import db
from models.employee import Employee
from models.product import Product

app = Flask(__name__)
# Load config to get DB URI
from config import DevelopmentConfig
app.config.from_object(DevelopmentConfig)
db.init_app(app)

def fix_sqlite_table(db_path, table_name, create_sql):
    print(f"Fixing table '{table_name}' in {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 1. Get existing data
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [info[1] for info in cursor.fetchall()]
        
        # 2. Rename old table
        cursor.execute(f"ALTER TABLE {table_name} RENAME TO {table_name}_old")
        
        # 3. Create new table with new schema
        cursor.execute(create_sql)
        
        # 4. Insert data back
        cols_str = ", ".join(columns)
        placeholders = ", ".join(["?" for _ in columns])
        cursor.executemany(f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})", rows)
        
        # 5. Drop old table
        cursor.execute(f"DROP TABLE {table_name}_old")
        
        conn.commit()
        print(f"Successfully fixed '{table_name}'")
    except Exception as e:
        conn.rollback()
        print(f"Error fixing table '{table_name}': {e}")
    finally:
        conn.close()

# SQL for creating new tables with composite unique constraints
# Note: These must match the models exactly.
EMPLOYEE_CREATE_SQL = """
CREATE TABLE employee (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER,
    name VARCHAR(100) NOT NULL,
    username VARCHAR(50) NOT NULL,
    password VARCHAR(200) NOT NULL,
    role VARCHAR(30) DEFAULT 'cashier',
    is_active BOOLEAN DEFAULT 1,
    profile_pic VARCHAR(500),
    language VARCHAR(10) DEFAULT 'ar',
    theme_preference VARCHAR(20) DEFAULT 'dark',
    can_see_orders BOOLEAN DEFAULT 1,
    can_see_orders_placed BOOLEAN DEFAULT 1,
    can_see_orders_delivered BOOLEAN DEFAULT 1,
    can_see_orders_returned BOOLEAN DEFAULT 1,
    can_see_orders_shipped BOOLEAN DEFAULT 1,
    can_edit_price BOOLEAN DEFAULT 0,
    can_see_reports BOOLEAN DEFAULT 1,
    can_manage_inventory BOOLEAN DEFAULT 0,
    can_see_expenses BOOLEAN DEFAULT 0,
    can_manage_suppliers BOOLEAN DEFAULT 0,
    can_manage_customers BOOLEAN DEFAULT 1,
    can_see_accounts BOOLEAN DEFAULT 0,
    can_see_financial BOOLEAN DEFAULT 0,
    shipping_company_id INTEGER,
    commission_percent INTEGER DEFAULT 0,
    salary INTEGER DEFAULT 0,
    total_orders INTEGER DEFAULT 0,
    total_sales INTEGER DEFAULT 0,
    created_at DATETIME,
    CONSTRAINT _username_tenant_uc UNIQUE (tenant_id, username),
    FOREIGN KEY(tenant_id) REFERENCES tenant (id),
    FOREIGN KEY(shipping_company_id) REFERENCES shipping_company (id)
)
"""

PRODUCT_CREATE_SQL = """
CREATE TABLE product (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER,
    name VARCHAR(150) NOT NULL,
    barcode VARCHAR(100),
    buy_price INTEGER NOT NULL,
    sale_price INTEGER NOT NULL,
    shipping_cost INTEGER DEFAULT 0,
    marketing_cost INTEGER DEFAULT 0,
    opening_stock INTEGER DEFAULT 0,
    quantity INTEGER DEFAULT 0,
    active BOOLEAN DEFAULT 1,
    low_stock_threshold INTEGER DEFAULT 5,
    created_at DATETIME,
    CONSTRAINT _product_barcode_tenant_uc UNIQUE (tenant_id, barcode),
    FOREIGN KEY(tenant_id) REFERENCES tenant (id)
)
"""

def main():
    # 1. Fix Core DB
    core_db = "database.db"
    if os.path.exists(core_db):
        fix_sqlite_table(core_db, "employee", EMPLOYEE_CREATE_SQL)
        fix_sqlite_table(core_db, "product", PRODUCT_CREATE_SQL)
    
    # 2. Fix Tenant DBs
    tenants_dir = "tenants"
    if os.path.exists(tenants_dir):
        for filename in os.listdir(tenants_dir):
            if filename.endswith(".db"):
                db_path = os.path.join(tenants_dir, filename)
                fix_sqlite_table(db_path, "employee", EMPLOYEE_CREATE_SQL)
                fix_sqlite_table(db_path, "product", PRODUCT_CREATE_SQL)

if __name__ == "__main__":
    main()
