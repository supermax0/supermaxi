"""Provision a ready-to-use FINORA solo urology clinic tenant.

Usage:
    py scripts/provision_urology_clinic.py
    py scripts/provision_urology_clinic.py --slug ahnouri --password 'Secret123!'
"""
from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
from datetime import datetime, timedelta
from pathlib import Path

from flask import g
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISABLE_CLINICS_SCHEDULER", "1")
os.environ.setdefault("DISABLE_PUBLISHER_SCHEDULER", "1")
os.environ.setdefault("FINORA_DISABLE_SCHEDULERS", "1")

from app import app
from extensions import db
from extensions_tenant import clear_tenant_engine, get_tenant_db_path, init_tenant_db
from models.core.tenant import Tenant as CoreTenant
from models.employee import Employee
from models.role import Permission, Role
from models.tenant import Tenant
from modules.clinics.schema import ensure_clinics_schema
from modules.clinics.service import (
    create_doctor,
    create_room,
    create_service,
    get_or_create_settings,
    update_service,
    update_settings,
)
from modules.clinics.service_extras import seed_specialty_pack
from modules.clinics.service_ops import upsert_schedule
from modules.clinics.service_specialties import seed_default_specialties, update_specialty
from routes.permissions import ensure_default_permissions
from utils.plan_limits import get_plan
from utils.tenant_registration import save_tenant_registration

# Urology-focused services (IQD)
UROLOGY_SERVICES = [
    ("استشارة جراحة بولية", "استشارات", 20, 25000),
    ("مراجعة مسالك بولية", "استشارات", 15, 15000),
    ("فحص البروستات", "فحوصات", 20, 30000),
    ("سونار مسالك بولية", "فحوصات", 20, 40000),
    ("قسطرة بولية", "إجراءات", 30, 50000),
    ("تنظير مثانة", "إجراءات", 45, 150000),
    ("تفتيت حصى خارجي", "إجراءات", 60, 200000),
    ("استئصال حصاة مثانة", "عمليات", 90, 350000),
    ("ختان", "عمليات", 30, 75000),
    ("علاج التهاب مسالك", "علاج", 15, 20000),
]


def _password(explicit: str | None, prefix: str = "Uro@") -> str:
    if explicit:
        return explicit
    alphabet = string.ascii_letters + string.digits
    return prefix + "".join(secrets.choice(alphabet) for _ in range(8))


def _ensure_role(name: str, display: str, permission_names: list[str]) -> Role:
    role = Role.query.filter_by(name=name).first()
    if not role:
        role = Role(name=name, description=display)
        db.session.add(role)
        db.session.flush()
    existing = {p.name for p in role.permissions}
    for pname in permission_names:
        perm = Permission.query.filter_by(name=pname).first()
        if not perm:
            perm = Permission(name=pname, description=pname)
            db.session.add(perm)
            db.session.flush()
        if pname not in existing:
            role.permissions.append(perm)
            existing.add(pname)
    return role


def _create_employee(*, tenant_id: int, name: str, username: str, password: str, role_name: str, roles: list[Role]) -> Employee:
    emp = Employee.query.filter_by(tenant_id=tenant_id, username=username).first()
    if emp:
        emp.password = generate_password_hash(password)
        emp.is_active = True
        emp.role = role_name
        emp.name = name
    else:
        emp = Employee(
            name=name,
            username=username,
            password=generate_password_hash(password),
            role=role_name,
            salary=0,
            is_active=True,
            tenant_id=tenant_id,
            language="ar",
        )
        db.session.add(emp)
        db.session.flush()
    emp.roles = list(roles)
    return emp


def provision(
    slug: str,
    clinic_name: str,
    owner_name: str,
    doctor_name: str,
    admin_password: str,
    doctor_password: str | None,
    reception_password: str | None,
    trial_days: int,
) -> dict:
    slug = slug.strip().lower()
    doctor_password = doctor_password or _password(None, "Dr@")
    reception_password = reception_password or _password(None, "Rec@")
    os.environ["DISABLE_CLINICS_SCHEDULER"] = "1"
    os.environ["DISABLE_PUBLISHER_SCHEDULER"] = "1"

    with app.app_context():
        existing = CoreTenant.query.filter_by(slug=slug).first()
        if existing:
            raise SystemExit(f"المعرّف «{slug}» مستخدم مسبقاً. اختر --slug آخر.")

        db_path = get_tenant_db_path(slug)
        subscription_end = datetime.utcnow() + timedelta(days=trial_days)
        core = CoreTenant(
            name=clinic_name.upper(),
            slug=slug,
            db_path=db_path,
            business_type="clinics",
            is_active=True,
            subscription_end_date=subscription_end,
        )
        db.session.add(core)
        db.session.commit()
        db.session.remove()

        clear_tenant_engine(slug)
        g.tenant = slug
        init_tenant_db(slug)
        db.session.commit()
        db.session.remove()
        ensure_default_permissions()
        db.session.commit()
        db.session.remove()
        ensure_clinics_schema()
        db.session.remove()

        plan = get_plan("basic")
        tenant_row = Tenant(
            name=clinic_name,
            contact_name=owner_name,
            contact_phone=None,
            contact_email=None,
            business_type="clinics",
            plan_key="basic",
            plan_name=plan["name"],
            monthly_price=plan.get("price_monthly", 0),
            is_active=True,
            subscription_end=subscription_end,
        )
        db.session.add(tenant_row)
        db.session.flush()
        tenant_id = tenant_row.id

        owner_role = _ensure_role(
            "clinic_owner",
            "مالك العيادة",
            [
                "clinics_dashboard",
                "clinics_reception",
                "clinics_appointments",
                "clinics_patients",
                "clinics_visits",
                "clinics_clinical",
                "clinics_billing",
                "clinics_inventory",
                "clinics_admin",
                "clinics_reports",
                "clinics_settings",
                "clinics_communications_view",
                "purchases.view",
                "purchases.create",
                "purchases.edit",
                "purchases.receive",
                "purchases.payment.view",
                "purchases.payment.create",
            ],
        )
        doctor_role = _ensure_role(
            "clinic_doctor",
            "طبيب جراحة بولية",
            [
                "clinics_dashboard",
                "clinics_patients",
                "clinics_visits",
                "clinics_clinical",
                "clinics_appointments",
                "clinics_billing",
            ],
        )
        reception_role = _ensure_role(
            "clinic_reception",
            "استقبال عيادة",
            [
                "clinics_dashboard",
                "clinics_reception",
                "clinics_appointments",
                "clinics_patients",
                "clinics_visits",
                "clinics_billing",
                "clinics_communications_view",
                "clinics_communications_reply",
            ],
        )

        admin = _create_employee(
            tenant_id=tenant_id,
            name=owner_name,
            username="admin",
            password=admin_password,
            role_name="admin",
            roles=[owner_role],
        )
        doctor_emp = _create_employee(
            tenant_id=tenant_id,
            name=doctor_name,
            username="doctor",
            password=doctor_password,
            role_name="employee",
            roles=[doctor_role],
        )
        reception_emp = _create_employee(
            tenant_id=tenant_id,
            name="موظف استقبال",
            username="reception",
            password=reception_password,
            role_name="employee",
            roles=[reception_role],
        )
        db.session.flush()

        get_or_create_settings(tenant_id, actor_id=admin.id)
        update_settings(
            tenant_id,
            {
                "organization_mode": "solo_clinic",
                "clinic_type": "general_practice",
                "clinic_name": clinic_name,
                "appointment_slot_minutes": 20,
                "allow_online_booking": True,
                "booking_mode": "direct",
                "booking_otp_enabled": False,
                "queue_display_enabled": True,
                "allow_same_day_booking": True,
                "allow_public_reschedule": True,
                "allow_public_cancellation": True,
                "public_show_prices": True,
                "public_profile_enabled": True,
                "public_chat_enabled": False,
                "booking_welcome_text": f"مرحباً بكم في {clinic_name} — احجز موعدك مع {doctor_name}.",
                "public_working_hours": "السبت–الخميس 9:00–17:00",
                "minimum_booking_notice_hours": 1,
                "maximum_advance_booking_days": 60,
                "cancellation_deadline_hours": 4,
                "max_active_appointments_per_patient": 3,
                "default_followup_days": 14,
                "reminder_hours_before": 24,
                "display_sound_enabled": True,
                "display_voice_enabled": False,
                "display_volume": 70,
            },
            actor_id=admin.id,
        )

        specialties = seed_default_specialties(tenant_id, actor_id=admin.id)
        by_code = {s["code"]: s for s in specialties}
        if "urology" not in by_code:
            raise SystemExit("اختصاص urology غير موجود في كتالوج النظام.")

        for spec in specialties:
            update_specialty(
                tenant_id,
                spec["id"],
                {"is_active": spec["code"] == "urology"},
                actor_id=admin.id,
            )

        urology = by_code["urology"]
        # Base GP pack (labs/common items) then replace services with urology set
        pack = seed_specialty_pack(tenant_id, clinic_type="general_practice", actor_id=admin.id)

        doctor = create_doctor(
            tenant_id,
            {
                "full_name": doctor_name,
                "phone": "07700000000",
                "specialty": "جراحة بولية / المسالك البولية",
                "scientific_title": "اختصاص جراحة بولية",
                "employee_id": doctor_emp.id,
                "primary_specialty_id": urology["id"],
                "specialty_ids": [urology["id"]],
                "color": "#0D9488",
                "active": True,
            },
            actor_id=admin.id,
        )

        from modules.clinics.models import ClinicService

        # Deactivate generic GP services; keep labs/procedures from pack
        for svc in ClinicService.query.filter_by(tenant_id=tenant_id, active=True).all():
            update_service(
                tenant_id,
                svc.id,
                {"active": False, "specialty_ids": [urology["id"]], "doctor_ids": [doctor["id"]]},
                actor_id=admin.id,
            )

        created_services = 0
        for name, category, duration, price in UROLOGY_SERVICES:
            existing = ClinicService.query.filter_by(tenant_id=tenant_id, name=name).first()
            if existing:
                update_service(
                    tenant_id,
                    existing.id,
                    {
                        "active": True,
                        "category": category,
                        "duration_minutes": duration,
                        "price": price,
                        "specialty_ids": [urology["id"]],
                        "doctor_ids": [doctor["id"]],
                    },
                    actor_id=admin.id,
                )
            else:
                create_service(
                    tenant_id,
                    {
                        "name": name,
                        "category": category,
                        "duration_minutes": duration,
                        "price": price,
                        "specialty_ids": [urology["id"]],
                        "doctor_ids": [doctor["id"]],
                        "active": True,
                    },
                    actor_id=admin.id,
                )
            created_services += 1

        room = create_room(
            tenant_id,
            {"name": "غرفة المعاينة 1", "room_type": "consultation", "active": True},
            actor_id=admin.id,
        )

        # Sat–Thu (Iraq): weekdays 5,6,0,1,2,3
        for weekday in (5, 6, 0, 1, 2, 3):
            upsert_schedule(
                tenant_id,
                {
                    "doctor_id": doctor["id"],
                    "weekday": weekday,
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "break_start": "13:00",
                    "break_end": "14:00",
                    "slot_minutes": 20,
                },
                actor_id=admin.id,
            )

        db.session.commit()

        save_tenant_registration(
            slug,
            {
                "slug": slug,
                "company_name": clinic_name,
                "contact_name": owner_name,
                "username": "admin",
                "password": admin_password,
                "doctor_username": "doctor",
                "doctor_password": doctor_password,
                "reception_username": "reception",
                "reception_password": reception_password,
                "plan_key": "basic",
                "plan_name": plan["name"],
                "business_type": "clinics",
                "clinic_focus": "urology",
                "doctor_name": doctor_name,
                "source": "provision_urology_clinic",
                "registered_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

        return {
            "slug": slug,
            "clinic_name": clinic_name,
            "tenant_id": tenant_id,
            "business_type": "clinics",
            "organization_mode": "solo_clinic",
            "specialty": "urology",
            "specialty_ar": "المسالك البولية / جراحة بولية",
            "services_seeded": created_services,
            "pack_created": pack.get("created"),
            "doctor_id": doctor["id"],
            "room_id": room["id"],
            "booking_url": f"/c/{slug}",
            "admin": {"username": "admin", "password": admin_password, "name": owner_name},
            "doctor": {"username": "doctor", "password": doctor_password, "name": doctor_name},
            "reception": {"username": "reception", "password": reception_password, "name": reception_emp.name},
            "login_hint": "معرف الشركة (Slug) + اسم المستخدم + كلمة المرور",
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Provision FINORA solo urology clinic")
    parser.add_argument("--slug", default="ahnouri", help="company login slug")
    parser.add_argument("--name", default="عيادة د. أحمد النوري للجراحة البولية", help="clinic display name")
    parser.add_argument("--owner", default="د. أحمد النوري", help="owner display name")
    parser.add_argument("--doctor-name", default="د. أحمد النوري", help="doctor full name")
    parser.add_argument("--password", default="", help="admin password (generated if empty)")
    parser.add_argument("--doctor-password", default="", help="doctor password (generated if empty)")
    parser.add_argument("--reception-password", default="", help="reception password (generated if empty)")
    parser.add_argument("--trial-days", type=int, default=90)
    args = parser.parse_args()
    password = args.password.strip() or _password(None, "Admin@")
    info = provision(
        args.slug,
        args.name,
        args.owner,
        args.doctor_name,
        password,
        args.doctor_password.strip() or None,
        args.reception_password.strip() or None,
        args.trial_days,
    )
    print("=" * 56)
    print("تم إنشاء عيادة الجراحة البولية بنجاح")
    print("=" * 56)
    print(f"اسم العيادة     : {info['clinic_name']}")
    print(f"معرف الشركة     : {info['slug']}")
    print(f"الطبيب          : {info['doctor']['name']}")
    print(f"الاختصاص        : {info['specialty_ar']}")
    print(f"وضع المنشأة     : solo_clinic (طبيب واحد)")
    print(f"رابط الحجز العام: {info['booking_url']}")
    print(f"خدمات مفعّلة    : {info['services_seeded']}")
    print("-" * 56)
    print("بيانات تسجيل الدخول")
    print("-" * 56)
    print(f"المالك    | مستخدم: {info['admin']['username']:12} | كلمة المرور: {info['admin']['password']}")
    print(f"الطبيب    | مستخدم: {info['doctor']['username']:12} | كلمة المرور: {info['doctor']['password']}")
    print(f"الاستقبال | مستخدم: {info['reception']['username']:12} | كلمة المرور: {info['reception']['password']}")
    print("-" * 56)
    print("طريقة الدخول: صفحة الدخول → معرف الشركة ثم المستخدم وكلمة المرور")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
