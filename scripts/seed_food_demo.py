"""Seed ten complete food products into one explicitly selected tenant.

Usage:
    python scripts/seed_food_demo.py --tenant hdhh
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flask import g

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app
from extensions import db
from extensions_tenant import init_tenant_db
from modules.food.demo_data import seed_demo_products
from models.tenant import Tenant


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Seed the Finora food demo catalog")
    parser.add_argument("--tenant", required=True, help="tenant slug, for example hdhh")
    parser.add_argument("--tenant-id", type=int, default=1, help="tenant id inside the selected database")
    args = parser.parse_args()
    with app.app_context():
        g.tenant = args.tenant.strip().lower()
        init_tenant_db(g.tenant)
        tenant = Tenant.query.first()
        if tenant is None:
            tenant = Tenant(
                id=args.tenant_id,
                name=args.tenant,
                business_type="food_wholesale_retail",
                is_active=True,
            )
            db.session.add(tenant)
            db.session.commit()
        result = seed_demo_products(args.tenant_id)
        print(
            f"تم تجهيز {result['total']} منتجات تجريبية: "
            f"أضيف {len(result['created'])} وتجاوز {len(result['skipped'])} موجوداً مسبقاً."
        )
        print(f"المخزن: {result['warehouse_id']} | المورد: {result['supplier_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
