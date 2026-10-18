"""
ملف بيانات التسجيل لكل شركة: tenants/profiles/{slug}.json
يُنشأ عند التسجيل/الإنشاء ويُجلب تلقائياً (مع مزامنة من قاعدة الشركة إن لزم).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from flask import current_app
from sqlalchemy.orm import sessionmaker

from extensions_tenant import get_tenant_engine


DISCOVERY_SOURCE_LABELS = {
    "chatgpt": "ChatGPT",
    "facebook": "فيسبوك",
    "instagram": "إنستغرام",
    "tiktok": "تيك توك",
    "google_search": "بحث Google",
    "google_ads": "إعلان Google",
    "youtube": "YouTube",
    "friend": "صديق أو توصية",
    "other": "أخرى",
}


def normalize_whatsapp_number(value: str) -> str:
    """تحويل الرقم العراقي إلى الصيغة الرقمية الدولية المناسبة لرابط wa.me."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("00964"):
        digits = digits[2:]
    elif digits.startswith("07"):
        digits = "964" + digits[1:]
    elif len(digits) == 10 and digits.startswith("7"):
        digits = "964" + digits
    return digits


def new_activation_code() -> str:
    """رمز قصير يسهل قراءته ومطابقته في رسالة واتساب."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def build_whatsapp_activation_message(registration: dict) -> str:
    return "\n".join(
        [
            "مرحباً، أرجو تفعيل حسابي في نظام Finora.",
            f"الاسم: {registration.get('contact_name') or '—'}",
            f"اسم النشاط: {registration.get('company_name') or '—'}",
            f"رقم واتساب المسجل: {registration.get('phone') or '—'}",
            f"معرّف الشركة: {registration.get('slug') or '—'}",
            f"رمز طلب التفعيل: {registration.get('activation_code') or '—'}",
        ]
    )


def build_whatsapp_activation_url(service_number: str, registration: dict) -> str:
    number = normalize_whatsapp_number(service_number)
    if not number:
        return ""
    return f"https://wa.me/{number}?text={quote(build_whatsapp_activation_message(registration))}"


def normalize_discovery_source(source, other=None) -> tuple[str, str]:
    source_clean = str(source or "").strip().lower()
    if source_clean not in DISCOVERY_SOURCE_LABELS:
        return "", ""
    other_clean = str(other or "").strip()[:120] if source_clean == "other" else ""
    return source_clean, other_clean


def discovery_source_label(source, other=None) -> str:
    source_clean, other_clean = normalize_discovery_source(source, other)
    if not source_clean:
        return "—"
    if source_clean == "other" and other_clean:
        return f"أخرى — {other_clean}"
    return DISCOVERY_SOURCE_LABELS[source_clean]


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


SECRET_KEYS = ("password", "password2", "admin_password", "new_password")


def _strip_secrets(payload: dict) -> bool:
    """Remove every credential field (legacy files stored plaintext passwords). True when something was removed."""
    removed = False
    for key in SECRET_KEYS:
        if key in payload:
            payload.pop(key, None)
            removed = True
    return removed


def save_tenant_registration(slug: str, data: dict, app_root: Optional[str] = None) -> str:
    """حفظ/دمج بيانات التسجيل في ملف JSON. لا تُخزَّن كلمات المرور إطلاقاً (التجزئة فقط في جدول الموظفين)."""
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

    _strip_secrets(payload)

    if not payload.get("unsubscribe_token"):
        payload["unsubscribe_token"] = existing.get("unsubscribe_token") or str(uuid.uuid4())
    if "marketing_opt_in" not in payload and "marketing_opt_in" not in (data or {}):
        if "marketing_opt_in" in existing:
            payload["marketing_opt_in"] = existing["marketing_opt_in"]
        else:
            payload["marketing_opt_in"] = True

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return path


def load_tenant_registration(slug: str, app_root: Optional[str] = None) -> Optional[dict]:
    path = registration_file_path(slug, app_root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(data, dict) and _strip_secrets(data):
        # Legacy record held a plaintext password: scrub it from disk the first time it is read.
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
    return data


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
    password: str = "",  # accepted for compatibility only — never stored
    plan_key: str,
    plan_name: str,
    billing: str,
    business_type: str = "general",
    source: str = "signup",
    marketing_opt_in: bool = True,
    discovery_source: str = "",
    discovery_source_other: str = "",
) -> dict:
    discovery_source, discovery_source_other = normalize_discovery_source(
        discovery_source, discovery_source_other
    )
    return {
        "slug": slug,
        "company_name": company_name,
        "contact_name": contact_name,
        "email": email or None,
        "phone": phone or None,
        "username": username,
        "plan_key": plan_key,
        "plan_name": plan_name,
        "billing": billing,
        "business_type": business_type,
        "source": source,
        "discovery_source": discovery_source or None,
        "discovery_source_other": discovery_source_other or None,
        "marketing_opt_in": bool(marketing_opt_in),
        "activation_status": "pending_whatsapp",
        "activation_code": new_activation_code(),
        "unsubscribe_token": str(uuid.uuid4()),
        "registered_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


def unsubscribe_by_token(token: str) -> tuple[bool, str]:
    """إلغاء اشتراك النشرة عبر الرمز."""
    token_clean = (token or "").strip()
    if not token_clean:
        return False, "رمز غير صالح"

    profiles_path = profiles_dir()
    if not os.path.isdir(profiles_path):
        return False, "لم يُعثر على بيانات الاشتراك"

    for filename in os.listdir(profiles_path):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(profiles_path, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("unsubscribe_token") != token_clean:
            continue
        data["marketing_opt_in"] = False
        data["unsubscribed_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        data["updated_at"] = data["unsubscribed_at"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        company = data.get("company_name") or data.get("slug") or ""
        return True, company

    return False, "رمز غير صالح أو منتهي"
