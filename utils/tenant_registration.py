"""
ملف بيانات التسجيل لكل شركة: tenants/profiles/{slug}.json
يُنشأ عند التسجيل/الإنشاء ويُجلب تلقائياً (مع مزامنة من قاعدة الشركة إن لزم).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

from flask import current_app
from sqlalchemy.orm import sessionmaker

from extensions_tenant import get_tenant_engine


def _app_root(app_root: Optional[str] = None) -> str:
    if app_root:
        return app_root
    return current_app.root_path


def profiles_dir(app_root: Optional[str] = None) -> str:
    path = os.path.join(_app_root(app_root), "tenants", "profiles")
    os.makedirs(path, exist_ok=True)
    return path


def registration_file_path(slug: str, app_root: Optional[str] = None) -> str:
    slug_clean = (slug or "").strip().lower()
    return os.path.join(profiles_dir(app_root), f"{slug_clean}.json")


def _fmt_dt(value) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        return value
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)


def save_tenant_registration(slug: str, data: dict, app_root: Optional[str] = None) -> str:
    """حفظ/دمج بيانات التسجيل في ملف JSON (تتضمن كلمة المرور الأصلية إن وُفرت)."""
    slug_clean = (slug or "").strip().lower()
    if not slug_clean:
        raise ValueError("slug مطلوب")

    path = registration_file_path(slug_clean, app_root)
    existing: dict = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f) or {}
        except (json.JSONDecodeError, OSError):
            existing = {}

    payload = {**existing, **(data or {})}
    payload["slug"] = slug_clean
    payload["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if not payload.get("registered_at"):
        payload["registered_at"] = payload["updated_at"]

    payload.pop("password2", None)
    # عند المزامنة من القاعدة دون كلمة مرور جديدة — الإبقاء على المحفوظة سابقاً
    if not payload.get("password") and existing.get("password"):
        payload["password"] = existing["password"]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return path


def load_tenant_registration(slug: str, app_root: Optional[str] = None) -> Optional[dict]:
    path = registration_file_path(slug, app_root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def delete_tenant_registration(slug: str, app_root: Optional[str] = None) -> None:
    path = registration_file_path(slug, app_root)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def build_registration_from_db(slug: str, core_tenant=None) -> Optional[dict]:
    """قراءة بيانات التسجيل من قاعدة الشركة."""
    slug_clean = (slug or "").strip().lower()
    if not slug_clean:
        return None

    from models.employee import Employee
    from models.tenant import Tenant as TenantModel

    engine = get_tenant_engine(slug_clean)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        tenant_row = session.query(TenantModel).first()
        admin_emp = (
            session.query(Employee).filter(Employee.role == "admin").first()
            or session.query(Employee).filter_by(username="admin").first()
        )
        if not tenant_row and not admin_emp and not core_tenant:
            return None

        sub_end = None
        if tenant_row and tenant_row.subscription_end:
            sub_end = _fmt_dt(tenant_row.subscription_end)
        elif core_tenant and getattr(core_tenant, "subscription_end_date", None):
            sub_end = _fmt_dt(core_tenant.subscription_end_date)

        return {
            "slug": slug_clean,
            "company_name": (tenant_row.name if tenant_row else None) or getattr(core_tenant, "name", None),
            "contact_name": getattr(tenant_row, "contact_name", None) or (admin_emp.name if admin_emp else None),
            "email": getattr(tenant_row, "contact_email", None),
            "phone": getattr(tenant_row, "contact_phone", None),
            "username": admin_emp.username if admin_emp else None,
            "plan_key": getattr(tenant_row, "plan_key", None) or "basic",
            "plan_name": getattr(tenant_row, "plan_name", None),
            "business_type": getattr(tenant_row, "business_type", None)
            or getattr(core_tenant, "business_type", None)
            or "general",
            "subscription_end": sub_end,
            "registered_at": _fmt_dt(getattr(tenant_row, "created_at", None))
            or _fmt_dt(getattr(core_tenant, "created_at", None)),
            "source": "database_sync",
        }
    finally:
        session.close()


def get_tenant_registration(slug: str, core_tenant=None, sync_if_missing: bool = True) -> dict:
    """
    جلب بيانات التسجيل: من الملف أولاً، ثم من قاعدة الشركة مع إنشاء الملف تلقائياً.
    """
    slug_clean = (slug or "").strip().lower()
    file_data = load_tenant_registration(slug_clean)
    if file_data:
        return file_data

    if not sync_if_missing:
        return {}

    db_data = build_registration_from_db(slug_clean, core_tenant=core_tenant)
    if db_data:
        try:
            save_tenant_registration(slug_clean, db_data)
        except Exception:
            pass
        return db_data

    if core_tenant:
        minimal = {
            "slug": slug_clean,
            "company_name": core_tenant.name,
            "business_type": getattr(core_tenant, "business_type", "general"),
            "subscription_end": _fmt_dt(core_tenant.subscription_end_date),
            "registered_at": _fmt_dt(core_tenant.created_at),
            "source": "core_only",
        }
        try:
            save_tenant_registration(slug_clean, minimal)
        except Exception:
            pass
        return minimal

    return {}


def registration_payload_for_signup(
    *,
    slug: str,
    company_name: str,
    contact_name: str,
    email: str,
    phone: str,
    username: str,
    password: str,
    plan_key: str,
    plan_name: str,
    billing: str,
    business_type: str = "general",
    source: str = "signup",
) -> dict:
    return {
        "slug": slug,
        "company_name": company_name,
        "contact_name": contact_name,
        "email": email or None,
        "phone": phone or None,
        "username": username,
        "password": password,
        "plan_key": plan_key,
        "plan_name": plan_name,
        "billing": billing,
        "business_type": business_type,
        "source": source,
        "registered_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }
