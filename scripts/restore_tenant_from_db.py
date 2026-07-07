#!/usr/bin/env python3
"""
Re-register a tenant in PostgreSQL (core) from an existing SQLite file.

Use when a company was deleted from Super Admin but the .db file still exists
(e.g. restored from a Hostinger snapshot).

Examples:
  python scripts/restore_tenant_from_db.py supermax tenants/supermax.db
  python scripts/restore_tenant_from_db.py test /path/to/test.db --name "شركة تجريبية"
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

try:
    import dotenv

    dotenv.load_dotenv()
except Exception:
    pass

from app import app
from extensions import db
from extensions_tenant import clear_tenant_engine, get_tenant_db_path
from models.core.tenant import Tenant as CoreTenant
from utils.tenant_registration import get_tenant_registration


def _read_tenant_meta(db_path: str, slug: str) -> dict:
    import sqlite3

    out = {"slug": slug, "name": slug.upper(), "business_type": "general"}
    if not os.path.isfile(db_path):
        return out
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        for sql in (
            "SELECT name, business_type, plan_key FROM tenant LIMIT 1",
            "SELECT name, business_type FROM tenant LIMIT 1",
        ):
            try:
                row = cur.execute(sql).fetchone()
                if row:
                    out["name"] = (row[0] or out["name"]).strip()
                    if len(row) > 1 and row[1]:
                        out["business_type"] = row[1]
                    break
            except sqlite3.Error:
                continue
    finally:
        conn.close()
    return out


def restore_tenant(slug: str, source_db: str, name: str | None, trial_days: int, dry_run: bool) -> None:
    slug = (slug or "").strip().lower()
    if not slug:
        raise SystemExit("slug مطلوب")

    source_db = os.path.abspath(source_db)
    if not os.path.isfile(source_db):
        raise SystemExit(f"ملف قاعدة البيانات غير موجود: {source_db}")

    meta = _read_tenant_meta(source_db, slug)
    company_name = (name or meta.get("name") or slug).strip()
    business_type = meta.get("business_type") or "general"
    dest_rel = f"tenants/{slug}.db"
    dest_abs = get_tenant_db_path(slug)

    with app.app_context():
        existing = CoreTenant.query.filter_by(slug=slug).first()
        if existing:
            raise SystemExit(f"الشركة «{slug}» مسجّلة مسبقاً (id={existing.id}).")

        print(f"slug: {slug}")
        print(f"name: {company_name}")
        print(f"business_type: {business_type}")
        print(f"source: {source_db}")
        print(f"dest:   {dest_abs}")

        if dry_run:
            print("\n[dry-run] لم يُنفَّذ شيء.")
            return

        os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
        shutil.copy2(source_db, dest_abs)
        os.chmod(dest_abs, 0o664)

        row = CoreTenant(
            name=company_name,
            slug=slug,
            db_path=dest_rel,
            business_type=business_type,
            is_active=True,
            subscription_end_date=datetime.utcnow() + timedelta(days=max(1, trial_days)),
        )
        db.session.add(row)
        db.session.commit()
        clear_tenant_engine(slug)

        get_tenant_registration(slug, core_tenant=row, sync_if_missing=True)
        print(f"\nتمت استعادة تسجيل الشركة «{slug}» بنجاح.")


def main():
    parser = argparse.ArgumentParser(description="Restore core tenant registration from SQLite file")
    parser.add_argument("slug", help="معرف الشركة (مثل supermax)")
    parser.add_argument("db_path", help="مسار ملف SQLite المستعاد")
    parser.add_argument("--name", help="اسم الشركة (اختياري)")
    parser.add_argument("--trial-days", type=int, default=365, help="أيام الاشتراك (افتراضي 365)")
    parser.add_argument("--dry-run", action="store_true", help="عرض فقط بدون تنفيذ")
    args = parser.parse_args()
    restore_tenant(args.slug, args.db_path, args.name, args.trial_days, args.dry_run)


if __name__ == "__main__":
    main()
