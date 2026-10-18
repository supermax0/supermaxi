"""Clinic-facing staff accounts and RBAC management."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from werkzeug.security import generate_password_hash

from extensions import db
from models.branch import Branch
from models.employee import Employee
from models.role import Permission, Role
from modules.clinics.models import ClinicDoctor, ClinicSpecialty
from modules.clinics.service import _audit, create_doctor


CLINIC_PERMISSION_CATALOG = (
    ("daily", "التشغيل اليومي", (
        ("clinics_dashboard", "لوحة العيادة"),
        ("clinics_reception", "الاستقبال والطابور"),
        ("clinics_appointments", "المواعيد"),
        ("clinics_patients", "ملفات المرضى"),
        ("clinics_visits", "الزيارات"),
    )),
    ("clinical", "العمل السريري", (
        ("clinics_clinical", "السجل الطبي والوصفات"),
        ("clinics_clinical_shared_read", "قراءة السجل المشترك"),
        ("dental.view", "وحدة الأسنان"),
        ("dental.chart.view", "عرض مخطط الأسنان"),
        ("dental.chart.edit", "تعديل مخطط الأسنان"),
        ("dental.treatment_plan.view", "عرض خطط الأسنان"),
        ("dental.treatment_plan.create", "إنشاء خطط الأسنان"),
        ("dental.treatment_plan.edit", "تعديل خطط الأسنان"),
        ("dental.sessions.view", "عرض جلسات الأسنان"),
        ("dental.sessions.create", "إنشاء جلسات الأسنان"),
        ("dental.sessions.edit", "تعديل جلسات الأسنان"),
        ("dental.sessions.complete", "إكمال جلسات الأسنان"),
        ("dental.images.view", "عرض صور الأسنان"),
        ("dental.images.upload", "رفع صور الأسنان"),
    )),
    ("finance", "المالية والمخزون", (
        ("clinics_billing", "الفواتير والمدفوعات"),
        ("clinics_reports", "تقارير العيادة"),
        ("clinics_inventory", "مخزون العيادة"),
        ("purchases.view", "عرض المشتريات"),
        ("purchases.create", "إنشاء المشتريات"),
        ("purchases.edit", "تعديل المشتريات"),
        ("purchases.approve", "اعتماد المشتريات"),
        ("purchases.receive", "استلام المشتريات"),
        ("purchases.payment.view", "عرض دفعات الموردين"),
        ("purchases.payment.create", "دفع الموردين"),
        ("purchases.cost.view", "عرض كلفة الشراء"),
    )),
    ("communication", "التواصل", (
        ("clinics_communications_view", "عرض التواصل"),
        ("clinics_communications_reply", "الرد على الرسائل"),
        ("clinics_communications_assign", "تعيين المحادثات"),
        ("clinics_communications_close", "إغلاق المحادثات"),
        ("clinics_booking_requests_view", "عرض طلبات الحجز"),
        ("clinics_booking_requests_approve", "اعتماد طلبات الحجز"),
        ("clinics_patient_contact_sensitive_view", "عرض بيانات اتصال المريض"),
    )),
    ("admin", "الإدارة", (
        ("clinics_admin", "إدارة الأطباء والطاقم والخدمات"),
        ("clinics_settings", "إعدادات العيادة"),
        ("clinics_booking_settings_manage", "إعدادات الحجز"),
        ("clinics_reminders_manage", "إدارة التذكيرات"),
        ("clinics_templates_manage", "إدارة قوالب الرسائل"),
        ("clinics_whatsapp_manage", "إعدادات واتساب"),
    )),
)

PERMISSION_LABELS = {
    name: label
    for _group_key, _group_label, permissions in CLINIC_PERMISSION_CATALOG
    for name, label in permissions
}

ROLE_PRESETS = {
    "clinic_reception": {
        "label": "موظف استقبال",
        "permissions": (
            "clinics_dashboard", "clinics_reception", "clinics_appointments",
            "clinics_patients", "clinics_visits", "clinics_communications_view",
            "clinics_communications_reply", "clinics_booking_requests_view",
            "clinics_booking_requests_approve", "clinics_patient_contact_sensitive_view",
        ),
    },
    "clinic_doctor": {
        "label": "طبيب",
        "permissions": (
            "clinics_dashboard", "clinics_appointments", "clinics_patients",
            "clinics_visits", "clinics_clinical", "dental.view",
            "dental.chart.view", "dental.chart.edit", "dental.treatment_plan.view",
            "dental.treatment_plan.create", "dental.treatment_plan.edit",
            "dental.sessions.view", "dental.sessions.create", "dental.sessions.edit",
            "dental.sessions.complete", "dental.images.view", "dental.images.upload",
        ),
    },
    "clinic_nurse": {
        "label": "ممرض / مساعد طبي",
        "permissions": (
            "clinics_dashboard", "clinics_reception", "clinics_appointments",
            "clinics_patients", "clinics_visits", "clinics_clinical",
            "clinics_clinical_shared_read",
        ),
    },
    "clinic_accountant": {
        "label": "محاسب",
        "permissions": (
            "clinics_dashboard", "clinics_billing", "clinics_reports",
            "purchases.view", "purchases.payment.view", "purchases.payment.create",
            "purchases.cost.view",
        ),
    },
    "clinic_inventory": {
        "label": "مسؤول مخزون ومشتريات",
        "permissions": (
            "clinics_dashboard", "clinics_inventory", "purchases.view",
            "purchases.create", "purchases.edit", "purchases.receive",
            "purchases.payment.view", "purchases.cost.view",
        ),
    },
    "clinic_manager": {
        "label": "مدير عيادة",
        "permissions": tuple(PERMISSION_LABELS.keys()),
    },
}


def _employee_query(tenant_id: int):
    return Employee.query.filter(Employee.tenant_id == tenant_id)


def _branch(branch_id):
    if branch_id in (None, "", 0, "0"):
        return None
    row = Branch.query.filter_by(id=int(branch_id), is_active=True).first()
    if not row:
        raise ValueError("الفرع غير موجود أو غير فعال")
    return row


def _username(tenant_id: int, raw, *, exclude_id=None) -> str:
    value = str(raw or "").strip().lower()
    if len(value) < 3 or " " in value:
        raise ValueError("اسم المستخدم يجب أن يكون 3 أحرف على الأقل وبدون مسافات")
    query = _employee_query(tenant_id).filter(Employee.username == value)
    if exclude_id:
        query = query.filter(Employee.id != int(exclude_id))
    if query.first():
        raise ValueError("اسم المستخدم مستخدم بالفعل")
    return value


def _password(raw) -> str:
    value = str(raw or "")
    if len(value) < 6:
        raise ValueError("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
    return generate_password_hash(value)


def _permission_names(payload: dict, role_key: str) -> list[str]:
    raw = payload.get("permissions")
    if raw is None:
        raw = ROLE_PRESETS.get(role_key, ROLE_PRESETS["clinic_reception"])["permissions"]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("الصلاحيات يجب أن تكون قائمة")
    names = list(dict.fromkeys(str(value).strip() for value in raw if str(value).strip()))
    unknown = sorted(set(names) - set(PERMISSION_LABELS))
    if unknown:
        raise ValueError("توجد صلاحيات غير معروفة")
    return names


def _assign_permissions(employee: Employee, names: list[str]) -> None:
    rows = {row.name: row for row in Permission.query.filter(Permission.name.in_(names or ["-"])).all()}
    for name in names:
        if name not in rows:
            row = Permission(name=name, description=PERMISSION_LABELS[name], created_at=datetime.utcnow())
            db.session.add(row)
            rows[name] = row
    db.session.flush()
    role_name = f"clinic_staff_{employee.id}"
    role = Role.query.filter_by(name=role_name).first()
    if not role:
        role = Role(name=role_name, description=f"صلاحيات عيادات مخصصة للموظف #{employee.id}")
        db.session.add(role)
        db.session.flush()
    role.permissions = [rows[name] for name in names]
    employee.roles = [role]


def _effective_permissions(employee: Employee) -> list[str]:
    if employee.role == "admin":
        return list(PERMISSION_LABELS)
    return sorted({
        permission.name
        for role in employee.roles
        for permission in role.permissions
        if permission.name in PERMISSION_LABELS
    })


def _employee_dict(tenant_id: int, employee: Employee, doctor_by_employee: dict[int, ClinicDoctor]) -> dict:
    doctor = doctor_by_employee.get(employee.id)
    permissions = _effective_permissions(employee)
    return {
        "id": employee.id,
        "name": employee.name,
        "username": employee.username,
        "phone": employee.phone or "",
        "role_key": employee.role or "clinic_reception",
        "role_label": "مدير النظام" if employee.role == "admin" else ROLE_PRESETS.get(
            employee.role or "", {"label": "صلاحيات مخصصة"}
        )["label"],
        "active": bool(employee.is_active),
        "branch_id": employee.branch_id,
        "permissions": permissions,
        "permissions_count": len(permissions),
        "protected": employee.role == "admin",
        "doctor": ({
            "id": doctor.id,
            "name": doctor.full_name,
            "active": bool(doctor.active),
            "specialty": doctor.specialty or "",
            "license_number": doctor.license_number or "",
        } if doctor else None),
    }


def staff_center(tenant_id: int) -> dict:
    employees = _employee_query(tenant_id).order_by(Employee.is_active.desc(), Employee.name.asc()).all()
    doctors = ClinicDoctor.query.filter_by(tenant_id=tenant_id).order_by(ClinicDoctor.full_name.asc()).all()
    doctor_by_employee = {row.employee_id: row for row in doctors if row.employee_id}
    items = [_employee_dict(tenant_id, row, doctor_by_employee) for row in employees]
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.is_default.desc(), Branch.name.asc()).all()
    specialties = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, is_active=True).order_by(
        ClinicSpecialty.name_ar.asc()
    ).all()
    return {
        "items": items,
        "unlinked_doctors": [{
            "id": row.id,
            "name": row.full_name,
            "specialty": row.specialty or "",
            "active": bool(row.active),
        } for row in doctors if not row.employee_id],
        "branches": [{"id": row.id, "name": row.name} for row in branches],
        "specialties": [{"id": row.id, "name": row.name_ar} for row in specialties],
        "roles": [{
            "key": key,
            "label": value["label"],
            "permissions": list(value["permissions"]),
        } for key, value in ROLE_PRESETS.items()],
        "permission_groups": [{
            "key": group_key,
            "label": group_label,
            "permissions": [{"name": name, "label": label} for name, label in permissions],
        } for group_key, group_label, permissions in CLINIC_PERMISSION_CATALOG],
        "stats": {
            "total": len(items),
            "active": sum(1 for row in items if row["active"]),
            "doctors": sum(1 for row in items if row["doctor"]),
            "reception": sum(1 for row in items if row["role_key"] == "clinic_reception"),
        },
    }


def create_staff(tenant_id: int, payload: dict, actor_id=None, default_branch_id=None) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("اسم الموظف مطلوب")
    role_key = str(payload.get("role_key") or "clinic_reception").strip()
    if role_key not in ROLE_PRESETS:
        raise ValueError("الدور الوظيفي غير صالح")
    branch = _branch(payload.get("branch_id") or default_branch_id)
    employee = Employee(
        tenant_id=tenant_id,
        name=name,
        username=_username(tenant_id, payload.get("username")),
        password=_password(payload.get("password")),
        phone=str(payload.get("phone") or "").strip()[:20] or None,
        role=role_key,
        branch_id=branch.id if branch else None,
        is_active=True,
    )
    db.session.add(employee)
    db.session.flush()
    _assign_permissions(employee, _permission_names(payload, role_key))

    doctor_id = int(payload.get("doctor_id") or 0) or None
    staff_type = str(payload.get("staff_type") or "employee").strip()
    doctor = None
    if doctor_id:
        doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first()
        if not doctor or doctor.employee_id:
            raise ValueError("الطبيب غير موجود أو لديه حساب مرتبط")
        doctor.employee_id = employee.id
        doctor.updated_by = actor_id
        doctor.updated_at = datetime.utcnow()
    elif staff_type == "doctor" or role_key == "clinic_doctor":
        doctor = create_doctor(tenant_id, {
            "full_name": name,
            "employee_id": employee.id,
            "phone": employee.phone,
            "license_number": payload.get("license_number"),
            "scientific_title": payload.get("scientific_title"),
            "primary_specialty_id": payload.get("primary_specialty_id"),
            "specialty_ids": payload.get("specialty_ids") or [],
            "commission_pct": payload.get("commission_pct") or 0,
        }, actor_id, branch.id if branch else default_branch_id)

    _audit(
        tenant_id, actor_id, "clinic_staff", employee.id, "create",
        f"إنشاء حساب {ROLE_PRESETS[role_key]['label']}: {name}",
        meta={"role_key": role_key, "doctor_id": doctor.get("id") if isinstance(doctor, dict) else getattr(doctor, "id", None)},
        branch_id=employee.branch_id,
    )
    db.session.flush()
    return next(row for row in staff_center(tenant_id)["items"] if row["id"] == employee.id)


def update_staff(tenant_id: int, employee_id: int, payload: dict, actor_id=None) -> dict:
    employee = _employee_query(tenant_id).filter(Employee.id == employee_id).first()
    if not employee:
        raise ValueError("حساب الموظف غير موجود")
    if employee.role == "admin" and any(key in payload for key in ("role_key", "permissions", "active")):
        raise ValueError("لا يمكن تغيير دور أو تعطيل حساب مدير النظام من هذه الشاشة")
    if employee.id == actor_id and payload.get("active") is False:
        raise ValueError("لا يمكنك تعطيل حسابك الحالي")
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("اسم الموظف مطلوب")
        employee.name = name
    if "username" in payload:
        employee.username = _username(tenant_id, payload.get("username"), exclude_id=employee.id)
    if "phone" in payload:
        employee.phone = str(payload.get("phone") or "").strip()[:20] or None
    if "branch_id" in payload:
        branch = _branch(payload.get("branch_id"))
        employee.branch_id = branch.id if branch else None
    if "password" in payload and str(payload.get("password") or ""):
        employee.password = _password(payload.get("password"))
    if "active" in payload:
        employee.is_active = bool(payload.get("active"))
    if "role_key" in payload or "permissions" in payload:
        role_key = str(payload.get("role_key") or employee.role or "clinic_reception").strip()
        if role_key not in ROLE_PRESETS:
            raise ValueError("الدور الوظيفي غير صالح")
        employee.role = role_key
        _assign_permissions(employee, _permission_names(payload, role_key))

    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, employee_id=employee.id).first()
    if doctor:
        if "name" in payload:
            doctor.full_name = employee.name
        if "phone" in payload:
            doctor.phone = employee.phone
        if "active" in payload:
            doctor.active = employee.is_active
        doctor.updated_by = actor_id
        doctor.updated_at = datetime.utcnow()
    _audit(
        tenant_id, actor_id, "clinic_staff", employee.id, "update",
        f"تحديث حساب الموظف {employee.name}", branch_id=employee.branch_id,
    )
    db.session.flush()
    return next(row for row in staff_center(tenant_id)["items"] if row["id"] == employee.id)
