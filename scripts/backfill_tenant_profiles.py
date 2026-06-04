"""
إنشاء ملفات بيانات التسجيل للشركات القديمة من قواعد البيانات.
تشغيل: python scripts/backfill_tenant_profiles.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import app
from models.core.tenant import Tenant
from utils.tenant_registration import get_tenant_registration, registration_file_path


def main():
    with app.app_context():
        tenants = Tenant.query.all()
        created = 0
        for t in tenants:
            before = os.path.isfile(registration_file_path(t.slug, app.root_path))
            get_tenant_registration(t.slug, core_tenant=t, sync_if_missing=True)
            after = os.path.isfile(registration_file_path(t.slug, app.root_path))
            if after and not before:
                created += 1
                print(f"  + {t.slug}")
            elif after:
                print(f"  ~ {t.slug} (موجود)")
            else:
                print(f"  ! {t.slug} (تعذّر)")
        print(f"\nتمت المعالجة: {len(tenants)} شركة، ملفات جديدة: {created}")


if __name__ == "__main__":
    main()
