import os
import sys

from flask import g

# أضف مجلد المشروع إلى PYTHONPATH حتى يمكن استيراد app.py وملفات الامتدادات
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app
from extensions import db
from models.employee import Employee
from werkzeug.security import generate_password_hash
from extensions_tenant import init_tenant_db


def main() -> None:
    if len(sys.argv) < 4:
        print(
            "Usage: python scripts/create_dev_user.py <tenant_slug> <username> <password>",
            file=sys.stderr,
        )
        sys.exit(1)

    tenant_slug = sys.argv[1].strip().lower()
    username = sys.argv[2].strip()
    password = sys.argv[3]

    if not tenant_slug or not username or not password:
        print("All arguments are required.", file=sys.stderr)
        sys.exit(1)

    with app.app_context():
        g.tenant = tenant_slug

        # التأكد من تهيئة قاعدة بيانات الشركة (إنشاء الجداول إن لم تكن موجودة)
        init_tenant_db(tenant_slug)

        existing = Employee.query.filter_by(username=username).first()
        if existing:
            print(f"Updating existing user '{username}' in tenant '{tenant_slug}'...")
            existing.password = generate_password_hash(password)
            existing.role = "admin"
            existing.is_active = True
            dev = existing
        else:
            print(f"Creating new dev user '{username}' in tenant '{tenant_slug}'...")
            dev = Employee(
                name="Developer",
                username=username,
                password=generate_password_hash(password),
                role="admin",
                is_active=True,
            )
            db.session.add(dev)

        db.session.commit()
        print(f"Done. User id={dev.id}, username={dev.username}, tenant={tenant_slug}")


if __name__ == "__main__":
    main()

