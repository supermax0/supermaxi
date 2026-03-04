import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'database.db')

def update_db():
    print(f"Connecting to database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if the column exists first
        cursor.execute("PRAGMA table_info(message)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'is_edited' not in columns:
            print("Adding 'is_edited' column to 'message' table...")
            cursor.execute("ALTER TABLE message ADD COLUMN is_edited BOOLEAN DEFAULT 0;")
            conn.commit()
            print("Successfully added 'is_edited' column.")
        else:
            print("Column 'is_edited' already exists in 'message' table.")
            
    except Exception as e:
        print(f"Error updating database: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    update_db()
