import os
import sys

# Add the current directory to path so we can import app modules
sys.path.insert(0, os.getcwd())

from app import app
from extensions import db
from extensions_tenant import get_tenant_engine

# Import ALL publisher models so metadata.create_all() sees them
from modules.publisher.models.publisher_page import PublisherPage
from modules.publisher.models.publisher_media import PublisherMedia
from modules.publisher.models.publisher_post import PublisherPost
from modules.publisher.models.publisher_settings import PublisherSettings

def fix_all_databases():
    with app.app_context():
        # 1. Fix Core DB
        print("Initializing Core DB...")
        db.Model.metadata.create_all(db.engine)
        
        # 2. Fix all Tenant DBs
        tenants_dir = os.path.join(app.root_path, "tenants")
        if not os.path.exists(tenants_dir):
            print("No tenants directory found.")
            return

        db_files = [f for f in os.listdir(tenants_dir) if f.endswith(".db")]
        print(f"Found {len(db_files)} tenant databases.")

        for db_file in db_files:
            tenant_slug = db_file.replace(".db", "")
            print(f"--- Processing Tenant: {tenant_slug} ---")
            try:
                engine = get_tenant_engine(tenant_slug)
                db.Model.metadata.create_all(engine)
                print(f"Successfully initialized tables for {tenant_slug}")
            except Exception as e:
                print(f"Error processing {tenant_slug}: {e}")

if __name__ == "__main__":
    fix_all_databases()
    print("\nAll database initializations complete.")
