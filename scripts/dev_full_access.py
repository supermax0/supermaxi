"""
رفع خطة الشركة في قاعدة بيانات المستأجر إلى enterprise (كل ميزات القائمة)
للتطوير / اختبارات E2E محلية فقط.

استخدام:
  py scripts/dev_full_access.py supermax
"""
from __future__ import annotations

import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app
from extensions import db
from flask import g
from models.tenant import Tenant
from utils.plan_limits import get_plan


def main() -> None:
    slug = (sys.argv[1] if len(sys.argv) > 1 else "supermax").strip().lower()
    if not slug:
        print("Usage: py scripts/dev_full_access.py <tenant_slug>", file=sys.stderr)
        sys.exit(1)

    plan = get_plan("enterprise")
    with app.app_context():
        g.tenant = slug
        row = Tenant.query.first()
        if not row:
            print(f"No tenant row in {slug!r} database.", file=sys.stderr)
            sys.exit(1)
        row.plan_key = "enterprise"
        row.plan_name = str(plan.get("name") or "خطة الشركات")
        row.monthly_price = int(plan.get("price_monthly") or 0)
        db.session.commit()
        print(
            f"OK: tenant id={row.id} plan_key=enterprise (slug context={slug!r})"
        )


if __name__ == "__main__":
    main()
