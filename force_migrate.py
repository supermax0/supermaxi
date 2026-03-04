import sqlite3
import os

db_paths = ["database.db", "instance/database.db"]

for path in db_paths:
    if os.path.exists(path):
        print(f"Migrating {path}...")
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        
        # Check current columns
        cursor.execute("PRAGMA table_info(employee)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"  Current columns: {columns}")
        
        try:
            if 'profile_pic' not in columns:
                cursor.execute("ALTER TABLE employee ADD COLUMN profile_pic VARCHAR(500)")
                print("  --> Added profile_pic")
            if 'language' not in columns:
                cursor.execute("ALTER TABLE employee ADD COLUMN language VARCHAR(10) DEFAULT 'ar'")
                print("  --> Added language")
            if 'theme_preference' not in columns:
                cursor.execute("ALTER TABLE employee ADD COLUMN theme_preference VARCHAR(20) DEFAULT 'dark'")
                print("  --> Added theme_preference")
            
            conn.commit()
            print(f"  Successfully migrated {path}")
        except Exception as e:
            print(f"  Error migrating {path}: {e}")
        finally:
            conn.close()
    else:
        print(f"Path not found: {path}")

print("Done.")
