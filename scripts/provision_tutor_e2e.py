"""Create (or remove) throwaway tenants + Super Admin for the AI Tutor browser E2E.

    py scripts/provision_tutor_e2e.py setup  <credentials.json>
    py scripts/provision_tutor_e2e.py cleanup

Credentials are random per run and written ONLY to the given JSON file (keep it
outside the repository). Intended for a local development database.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("DISABLE_CLINICS_SCHEDULER", "1")
os.environ.setdefault("DISABLE_PUBLISHER_SCHEDULER", "1")
os.environ.setdefault("FINORA_DISABLE_SCHEDULERS", "1")

SLUGS = ("tutor-e2e-a", "tutor-e2e-b", "tutor-e2e-c")  # c: stripped to an empty clinic by the multi-level dependency spec
SUPERADMIN_USERNAME = "tutor_e2e_admin"


def _secret() -> str:
    return "E2e!" + secrets.token_urlsafe(12)


def _lift_user_limit(slug: str) -> None:
    """The seeded basic plan (3 users) is already full after provisioning; the lesson needs headroom."""
    import sqlite3

    from app import app
    from extensions_tenant import get_tenant_db_path

    with app.app_context():
        db_path = get_tenant_db_path(slug)
    con = sqlite3.connect(db_path)
    try:
        with con:
            con.execute("UPDATE tenant SET plan_key = ?, plan_name = ?", ("enterprise", "E2E enterprise"))
    finally:
        con.close()


def setup(out_path: str) -> None:
    from app import app
    from extensions import db
    from models.core.super_admin import SuperAdmin
    from provision_dental_clinic import provision

    creds = {"tenants": {}, "superadmin": {}}
    for slug in SLUGS:
        password = _secret()
        info = provision(slug, f"E2E {slug}", "E2E Owner", "Dr E2E Seed", password, _secret(), _secret(), 7)
        creds["tenants"][slug] = {"username": info["admin"]["username"], "password": password}
        _lift_user_limit(slug)
    with app.app_context():
        admin = SuperAdmin.query.filter_by(username=SUPERADMIN_USERNAME).first() or SuperAdmin(username=SUPERADMIN_USERNAME)
        password = _secret()
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        creds["superadmin"] = {"username": SUPERADMIN_USERNAME, "password": password}
    Path(out_path).write_text(json.dumps(creds), encoding="utf-8")
    print(f"created {', '.join(SLUGS)} and {SUPERADMIN_USERNAME}; credentials -> {out_path}")


def cleanup() -> None:
    from app import app
    from extensions import db
    from extensions_tenant import clear_tenant_engine, get_tenant_db_path
    from models.core.feature import FeatureAuditLog, TenantFeature
    from models.core.super_admin import SuperAdmin
    from models.core.tenant import Tenant as CoreTenant

    with app.app_context():
        for slug in SLUGS:
            core = CoreTenant.query.filter_by(slug=slug).first()
            if core:
                TenantFeature.query.filter_by(tenant_id=core.id).delete()
                FeatureAuditLog.query.filter_by(tenant_id=core.id).delete()
                db.session.delete(core)
        SuperAdmin.query.filter_by(username=SUPERADMIN_USERNAME).delete()
        db.session.commit()
        for slug in SLUGS:
            clear_tenant_engine(slug)
            base = Path(get_tenant_db_path(slug))
            for path in (base, Path(f"{base}-shm"), Path(f"{base}-wal"), base.parent / "profiles" / f"{slug}.json"):
                path.unlink(missing_ok=True)
    print("removed E2E tenants, their files and the temporary Super Admin")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "setup":
        setup(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "cleanup":
        cleanup()
    else:
        raise SystemExit(__doc__)
