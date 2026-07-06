#!/usr/bin/env python3
"""Probe tenant lookup used by login (run on server in app directory)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

try:
    import dotenv
    dotenv.load_dotenv()
except Exception:
    pass

from app import app
from models.core.tenant import Tenant as CoreTenant

slug = (sys.argv[1] if len(sys.argv) > 1 else "super").strip().lower()
with app.app_context():
    print("DATABASE_URL=", os.environ.get("DATABASE_URL", "(unset)"))
    print("SQLALCHEMY_DATABASE_URI=", app.config.get("SQLALCHEMY_DATABASE_URI"))
    all_tenants = CoreTenant.query.all()
    print("ALL_TENANTS=", [(t.id, t.slug, t.is_active) for t in all_tenants])
    t = CoreTenant.query.filter_by(slug=slug).first()
    print("LOOKUP", slug, "=", None if not t else (t.id, t.slug, t.is_active))
