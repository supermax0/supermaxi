import sqlite3
import os

# الاتصال بقاعدة البيانات
db_path = 'database.db'
if not os.path.exists(db_path):
    print(f"Error: Database file {db_path} not found!")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# التحقق من وجود الجدول
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='invoice'")
if not cursor.fetchone():
    print("Error: Table 'invoice' does not exist!")
    conn.close()
    exit(1)

# التحقق من الأعمدة الموجودة
cursor.execute("PRAGMA table_info(invoice)")
columns = [row[1] for row in cursor.fetchall()]

try:
    # إضافة عمود barcode إذا لم يكن موجوداً
    if 'barcode' not in columns:
        cursor.execute("ALTER TABLE invoice ADD COLUMN barcode VARCHAR(100)")
        print("Added column: barcode")
    else:
        print("Column barcode already exists")
except Exception as e:
    print(f"Error adding barcode: {e}")

try:
    # إضافة عمود shipping_barcode إذا لم يكن موجوداً
    if 'shipping_barcode' not in columns:
        cursor.execute("ALTER TABLE invoice ADD COLUMN shipping_barcode VARCHAR(100)")
        print("Added column: shipping_barcode")
    else:
        print("Column shipping_barcode already exists")
except Exception as e:
    print(f"Error adding shipping_barcode: {e}")

# حفظ التغييرات
conn.commit()
conn.close()

print("\nDatabase updated successfully!")

