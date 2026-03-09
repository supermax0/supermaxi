import os
import sys
from datetime import datetime, timedelta

# إضافة مجلد المشروع للمسار
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app
from extensions import db
from models.core.tenant import Tenant
from extensions_tenant import get_tenant_db_path


def main():
    slug = "supermax"
    name = "Supermax Company"

    with app.app_context():
        # لو موجود لا نكرره
        existing = Tenant.query.filter_by(slug=slug).first()
        if existing:
            print("Tenant already exists:", existing.id, existing.slug, existing.db_path)
            return

        db_path = get_tenant_db_path(slug)  # tenants/supermax.db

        t = Tenant(
            name=name,
            slug=slug,
            db_path=db_path,
            subscription_end_date=datetime.utcnow() + timedelta(days=365),
            is_active=True,
        )
        db.session.add(t)
        db.session.commit()
        print("Created core tenant:", t.id, t.slug, t.db_path)


if __name__ == "__main__":
    main()