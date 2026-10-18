"""Single tenant-provisioning path (Super Admin create, payment approval, FINORA CORE trials, admin reset).

Credential rules (security review, Phase 9):
- initial passwords are cryptographically random (``secrets``), never a shared default;
- only the password hash is stored; the plaintext exists only in the returned ``ProvisionResult`` so the calling
  operator can see it exactly once — it is never written to the registration record, logs, audit rows, e-mails or
  AI prompts;
- provisioned / reset admins get ``must_change_password`` and are forced to replace it at first login;
- a half-provisioned tenant is rolled back (Core row + database files).
"""
from __future__ import annotations

import logging
import os
import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from flask import g
from sqlalchemy.orm import Session, sessionmaker
from werkzeug.security import generate_password_hash

from extensions import db

logger = logging.getLogger(__name__)

ADMIN_USERNAME = "admin"
_ALPHABET = string.ascii_letters + string.digits + "-_.@#%"


def generate_initial_password(length: int = 16) -> str:
    """Random password with at least one lowercase, uppercase, digit and symbol (CSPRNG)."""
    while True:
        candidate = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if (any(c.islower() for c in candidate) and any(c.isupper() for c in candidate)
                and any(c.isdigit() for c in candidate) and any(c in "-_.@#%" for c in candidate)):
            return candidate


@dataclass
class ProvisionResult:
    tenant_id: int
    slug: str
    username: str
    password: str = field(repr=False)  # one-time; repr hidden so it never lands in logs by accident

    def credentials(self) -> dict[str, str]:
        return {"slug": self.slug, "username": self.username, "password": self.password}


class ProvisioningError(RuntimeError):
    pass


_POLICY_COLUMN_ENSURED: set[str] = set()


def ensure_password_policy_column(engine) -> None:
    """Add ``employee.must_change_password`` to a (legacy) database if missing. Idempotent and cached per engine."""
    from sqlalchemy import inspect, text

    key = str(engine.url)
    if key in _POLICY_COLUMN_ENSURED:
        return
    inspector = inspect(engine)
    if "employee" in inspector.get_table_names():
        if "must_change_password" not in {c["name"] for c in inspector.get_columns("employee")}:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE employee ADD COLUMN must_change_password BOOLEAN DEFAULT FALSE"))
        _POLICY_COLUMN_ENSURED.add(key)


def provision_tenant(
    *,
    name: str,
    slug: str,
    business_type: str,
    source: str,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    subscription_days: int = 14,
    plan_key: str = "basic",
    core: Session | None = None,
) -> ProvisionResult:
    """Create a complete tenant and return one-time admin credentials. ``core`` defaults to ``db.session``."""
    from extensions_tenant import get_tenant_db_path, get_tenant_engine, init_tenant_db
    from models.core.tenant import Tenant

    s = core or db.session
    if s.query(Tenant).filter_by(slug=slug).first() is not None:
        raise ProvisioningError("slug already in use")
    tenant = Tenant(name=name, slug=slug, db_path=f"tenants/{slug}.db", business_type=business_type, is_active=True,
                    subscription_end_date=datetime.utcnow() + timedelta(days=subscription_days))
    s.add(tenant)
    s.commit()
    # ``db.session`` is one scoped session routed by ``g.tenant``; it is removed below, so keep plain values.
    tenant_id, subscription_end = tenant.id, tenant.subscription_end_date
    password = generate_initial_password()
    try:
        previous = getattr(g, "tenant", None)
        try:
            g.tenant = slug
            init_tenant_db(slug)
            db.session.commit()
        finally:
            db.session.remove()
            if previous is None:
                g.pop("tenant", None)
            else:
                g.tenant = previous
        _create_admin(get_tenant_engine(slug), subscription_end, name=name, business_type=business_type, plan_key=plan_key,
                      contact_name=contact_name, contact_email=contact_email, contact_phone=contact_phone,
                      password=password)
        if not os.path.exists(get_tenant_db_path(slug)) or not _admin_exists(get_tenant_engine(slug)):
            raise ProvisioningError("verification failed")
    except Exception as exc:
        compensate(s, slug)
        logger.error("tenant provisioning failed for %s (%s); rolled back", slug, type(exc).__name__)
        raise ProvisioningError("tenant provisioning failed and was rolled back") from exc
    _save_registration(slug, name=name, contact_name=contact_name, email=contact_email, phone=contact_phone,
                       business_type=business_type, plan_key=plan_key, source=source)
    logger.info("tenant %s provisioned (source=%s); one-time admin credentials issued", slug, source)
    return ProvisionResult(tenant_id=tenant_id, slug=slug, username=ADMIN_USERNAME, password=password)


def _create_admin(engine, subscription_end, *, name, business_type, plan_key, contact_name, contact_email, contact_phone,
                  password) -> None:
    from models.employee import Employee
    from models.tenant import Tenant as TenantModel
    from utils.plan_limits import get_plan

    plan = get_plan(plan_key)
    ensure_password_policy_column(engine)
    local = sessionmaker(bind=engine)()
    try:
        row = TenantModel(name=name, contact_name=contact_name or name, contact_email=contact_email or None,
                          contact_phone=contact_phone or None, business_type=business_type, plan_key=plan_key,
                          plan_name=plan["name"], monthly_price=plan.get("price_monthly", 0), is_active=True,
                          subscription_end=subscription_end)
        local.add(row)
        local.flush()
        local.add(Employee(name=contact_name or name, username=ADMIN_USERNAME, password=generate_password_hash(password),
                           role="admin", salary=0, is_active=True, tenant_id=row.id, must_change_password=True))
        local.commit()
    finally:
        local.close()


def _admin_exists(engine) -> bool:
    from models.employee import Employee

    local = sessionmaker(bind=engine)()
    try:
        return local.query(Employee).filter_by(username=ADMIN_USERNAME, role="admin").first() is not None
    finally:
        local.close()


def reset_admin_password(slug: str) -> ProvisionResult:
    """Password RESET (never reveal): new random password, hash stored, must change at next login."""
    from sqlalchemy import or_

    from extensions_tenant import get_tenant_engine
    from models.core.tenant import Tenant
    from models.employee import Employee

    tenant = db.session.query(Tenant).filter(db.func.lower(Tenant.slug) == slug.strip().lower()).first()
    if tenant is None:
        raise ProvisioningError("tenant not found")
    engine = get_tenant_engine(tenant.slug)
    ensure_password_policy_column(engine)
    local = sessionmaker(bind=engine)()
    try:
        admin = local.query(Employee).filter(or_(Employee.username == ADMIN_USERNAME, Employee.role == "admin")).order_by(
            (Employee.username == ADMIN_USERNAME).desc()).first()
        if admin is None:
            raise ProvisioningError("admin account not found")
        password = generate_initial_password()
        admin.password = generate_password_hash(password)
        admin.must_change_password = True
        local.commit()
        username = admin.username
    finally:
        local.close()
    logger.info("admin password reset for tenant %s; one-time credentials issued", tenant.slug)
    return ProvisionResult(tenant_id=tenant.id, slug=tenant.slug, username=username, password=password)


def compensate(s: Session, slug: str) -> None:
    """Undo a half-provisioned tenant: Core row + database files."""
    from extensions_tenant import clear_tenant_engine, get_tenant_db_path
    from models.core.tenant import Tenant

    try:
        s.rollback()
        tenant = s.query(Tenant).filter_by(slug=slug).first()
        if tenant is not None:
            s.delete(tenant)
            s.commit()
    except Exception:
        s.rollback()
        logger.exception("compensation: could not delete tenant row %s", slug)
    clear_tenant_engine(slug)
    for suffix in ("", "-wal", "-shm"):
        path = get_tenant_db_path(slug) + suffix
        if os.path.exists(path):
            os.remove(path)


def _save_registration(slug: str, **fields: Any) -> None:
    try:
        from utils.tenant_registration import save_tenant_registration

        save_tenant_registration(slug, {
            "slug": slug,
            "company_name": fields["name"],
            "contact_name": fields.get("contact_name") or fields["name"],
            "email": fields.get("email"),
            "phone": fields.get("phone"),
            "username": ADMIN_USERNAME,
            "plan_key": fields.get("plan_key"),
            "business_type": fields.get("business_type"),
            "source": fields.get("source"),
            "registered_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception:
        logger.exception("registration record not saved for %s (tenant is provisioned)", slug)
