#!/usr/bin/env python3
"""Seed missing specialty visit templates for a tenant (idempotent).

Usage:
    py scripts/seed_specialty_visit_templates.py --slug ahnouri
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISABLE_CLINICS_SCHEDULER", "1")
os.environ.setdefault("DISABLE_PUBLISHER_SCHEDULER", "1")
os.environ.setdefault("FINORA_DISABLE_SCHEDULERS", "1")

from flask import g

from app import app
from extensions import db
from extensions_tenant import init_tenant_db
from models.tenant import Tenant
from modules.clinics.models import ClinicSpecialty, ClinicVisitTemplate
from modules.clinics.schema import ensure_clinics_schema
from modules.clinics.service_specialties import seed_default_specialties


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Seed specialty visit templates")
    parser.add_argument("--slug", default="ahnouri", help="Tenant slug")
    args = parser.parse_args()
    slug = str(args.slug or "").strip().lower()
    if not slug:
        print("ERROR: --slug required")
        return 1

    with app.app_context():
        g.tenant = slug
        init_tenant_db(slug)
        ensure_clinics_schema()
        db.session.remove()

        tenant = Tenant.query.first()
        if not tenant:
            print(f"ERROR: no tenant row inside DB for slug={slug}")
            return 1
        tenant_id = tenant.id

        before = {
            s.code: ClinicVisitTemplate.query.filter_by(
                tenant_id=tenant_id, specialty_id=s.id
            ).count()
            for s in ClinicSpecialty.query.filter_by(tenant_id=tenant_id).all()
        }
        seed_default_specialties(tenant_id, actor_id=None)
        db.session.commit()

        created = []
        for s in ClinicSpecialty.query.filter_by(tenant_id=tenant_id).all():
            n = ClinicVisitTemplate.query.filter_by(
                tenant_id=tenant_id, specialty_id=s.id
            ).count()
            if n > before.get(s.code, 0):
                created.append(s.code)

        print(f"OK tenant={slug} id={tenant_id}")
        print(f"created_or_filled={len(created)} codes={','.join(created) or '-'}")
        urology = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, code="urology").first()
        if urology:
            tpl = ClinicVisitTemplate.query.filter_by(
                tenant_id=tenant_id, specialty_id=urology.id, status="published"
            ).first()
            print(
                f"urology_template={'yes#' + str(tpl.id) if tpl else 'missing'} "
                f"default={urology.default_visit_template_id}"
            )
        else:
            print("urology_specialty=missing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
