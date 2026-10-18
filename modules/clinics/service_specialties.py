"""Tenant-safe specialties and config-driven visit templates."""
from __future__ import annotations

import json
import hashlib
import math
import re
from datetime import datetime, date, time

from sqlalchemy import func

from extensions import db
from modules.clinics.models import (
    ClinicAppointment,
    ClinicAuditLog,
    ClinicDoctor,
    ClinicDoctorSpecialty,
    ClinicSettings,
    ClinicSpecialty,
    ClinicVisit,
    ClinicVisitFieldValue,
    ClinicVisitTemplate,
    ClinicVisitTemplateField,
    ClinicVisitTemplateSection,
)


ORGANIZATION_MODES = (
    ("solo_clinic", "عيادة طبيب واحد"),
    ("multi_doctor_clinic", "عيادة متعددة الأطباء"),
    ("medical_center", "مجمع طبي"),
)

DEFAULT_SPECIALTIES = (
    ("general_medicine", "الطب العام", "General Medicine"),
    ("internal_medicine", "الباطنية", "Internal Medicine"),
    ("cardiology", "القلب", "Cardiology"),
    ("pediatrics", "الأطفال", "Pediatrics"),
    ("dentistry", "الأسنان", "Dentistry"),
    ("dermatology", "الجلدية", "Dermatology"),
    ("obstetrics_gynecology", "النسائية والتوليد", "Obstetrics and Gynecology"),
    ("ent", "الأنف والأذن والحنجرة", "ENT"),
    ("ophthalmology", "العيون", "Ophthalmology"),
    ("orthopedics", "العظام", "Orthopedics"),
    ("neurology", "الأعصاب", "Neurology"),
    ("endocrinology", "الغدد والسكري", "Endocrinology and Diabetes"),
    ("gastroenterology", "الجهاز الهضمي", "Gastroenterology"),
    ("nephrology", "الكلى", "Nephrology"),
    ("pulmonology", "الصدرية", "Pulmonology"),
    ("rheumatology", "الروماتيزم", "Rheumatology"),
    ("general_surgery", "الجراحة العامة", "General Surgery"),
    ("urology", "المسالك البولية", "Urology"),
    ("psychiatry", "الطب النفسي", "Psychiatry"),
    ("physiotherapy", "العلاج الطبيعي", "Physiotherapy"),
    ("nutrition", "التغذية", "Nutrition"),
    ("family_medicine", "طب الأسرة", "Family Medicine"),
)

LEGACY_SPECIALTY_MAP = {
    "general_practice": ("general_medicine", "الطب العام", "General Medicine"),
    "dental": ("dentistry", "الأسنان", "Dentistry"),
    "dentistry": ("dentistry", "الأسنان", "Dentistry"),
    "dermatology": ("dermatology", "الجلدية", "Dermatology"),
    "pediatrics": ("pediatrics", "الأطفال", "Pediatrics"),
    "gynecology": ("obstetrics_gynecology", "النسائية والتوليد", "Obstetrics and Gynecology"),
    "ophthalmology": ("ophthalmology", "العيون", "Ophthalmology"),
    "ent": ("ent", "الأنف والأذن والحنجرة", "ENT"),
    "physiotherapy": ("physiotherapy", "العلاج الطبيعي", "Physiotherapy"),
}

FIELD_TYPES = {
    "text", "textarea", "number", "date", "time", "select", "multi_select",
    "radio", "checkbox", "boolean", "measurement", "table", "file", "image",
    "drawing", "body_map", "dental_chart", "growth_chart", "pregnancy_tracker",
    "pediatric_growth_history", "vaccination_history", "development_tracker",
}


def _code(value: str) -> str:
    code = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return code[:80]


def _fallback_code(prefix: str, value: str) -> str:
    digest = hashlib.sha256(str(value or "").strip().encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def specialty_dict(row: ClinicSpecialty, doctor_count: int | None = None) -> dict:
    return {
        "id": row.id,
        "name_ar": row.name_ar,
        "name_en": row.name_en or "",
        "code": row.code,
        "description": row.description or "",
        "icon": row.icon or "fa-stethoscope",
        "is_active": bool(row.is_active),
        "is_system": bool(row.is_system),
        "default_visit_template_id": row.default_visit_template_id,
        "doctor_count": int(doctor_count or 0),
    }


def list_specialties(tenant_id: int, active_only: bool = False) -> list[dict]:
    query = ClinicSpecialty.query.filter_by(tenant_id=tenant_id)
    if active_only:
        query = query.filter_by(is_active=True)
    rows = query.order_by(ClinicSpecialty.name_ar.asc()).all()
    counts = dict(
        db.session.query(ClinicDoctorSpecialty.specialty_id, func.count(ClinicDoctorSpecialty.id))
        .filter(ClinicDoctorSpecialty.tenant_id == tenant_id)
        .group_by(ClinicDoctorSpecialty.specialty_id).all()
    )
    return [specialty_dict(row, counts.get(row.id, 0)) for row in rows]


def create_specialty(tenant_id: int, payload: dict, actor_id=None, *, is_system: bool = False) -> dict:
    name_ar = str(payload.get("name_ar") or payload.get("name") or "").strip()
    if not name_ar:
        raise ValueError("اسم الاختصاص مطلوب")
    code = _code(payload.get("code") or payload.get("name_en")) or _fallback_code("custom", name_ar)
    if ClinicSpecialty.query.filter_by(tenant_id=tenant_id, code=code).first():
        raise ValueError("رمز الاختصاص مستخدم")
    row = ClinicSpecialty(
        tenant_id=tenant_id, name_ar=name_ar,
        name_en=str(payload.get("name_en") or "").strip() or None,
        code=code, description=str(payload.get("description") or "").strip() or None,
        icon=str(payload.get("icon") or "fa-stethoscope").strip() or None,
        is_active=bool(payload.get("is_active", True)), is_system=is_system,
        created_by=actor_id, updated_by=actor_id,
    )
    db.session.add(row); db.session.flush()
    from modules.clinics.service import _audit
    _audit(tenant_id, actor_id, "specialty", row.id, "create", f"إنشاء اختصاص {row.name_ar}")
    return specialty_dict(row)


def update_specialty(tenant_id: int, specialty_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, id=specialty_id).first()
    if not row:
        raise ValueError("الاختصاص غير موجود")
    for field in ("name_ar", "name_en", "description", "icon"):
        if field in payload:
            value = str(payload.get(field) or "").strip() or None
            if field == "name_ar" and not value:
                raise ValueError("اسم الاختصاص مطلوب")
            setattr(row, field, value)
    action = "update"
    if "is_active" in payload:
        row.is_active = bool(payload.get("is_active"))
        action = "enable" if row.is_active else "disable"
    row.updated_by = actor_id; row.updated_at = datetime.utcnow()
    from modules.clinics.service import _audit
    _audit(tenant_id, actor_id, "specialty", row.id, action, f"تحديث اختصاص {row.name_ar}")
    return specialty_dict(row)


def seed_default_specialties(tenant_id: int, actor_id=None) -> list[dict]:
    for code, name_ar, name_en in DEFAULT_SPECIALTIES:
        row = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, code=code).first()
        if not row:
            db.session.add(ClinicSpecialty(tenant_id=tenant_id, code=code, name_ar=name_ar, name_en=name_en,
                                           is_active=True, is_system=True, created_by=actor_id, updated_by=actor_id))
    db.session.flush()
    internal = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, code="internal_medicine").first()
    if internal and not ClinicVisitTemplate.query.filter_by(tenant_id=tenant_id, specialty_id=internal.id).first():
        _seed_internal_medicine_template(tenant_id, internal, actor_id)
    _seed_additional_templates(tenant_id, actor_id)
    settings = ClinicSettings.query.filter_by(tenant_id=tenant_id).first()
    if settings:
        settings.specialty_pack_seeded = True
    from modules.clinics.service_dental_completion import seed_dental_services
    seed_dental_services(tenant_id, actor_id)
    return list_specialties(tenant_id)


def doctor_specialties(tenant_id: int, doctor_id: int) -> list[dict]:
    rows = (
        db.session.query(ClinicDoctorSpecialty, ClinicSpecialty)
        .join(ClinicSpecialty, ClinicSpecialty.id == ClinicDoctorSpecialty.specialty_id)
        .filter(ClinicDoctorSpecialty.tenant_id == tenant_id, ClinicDoctorSpecialty.doctor_id == doctor_id,
                ClinicSpecialty.tenant_id == tenant_id)
        .order_by(ClinicDoctorSpecialty.is_primary.desc(), ClinicSpecialty.name_ar.asc()).all()
    )
    return [{**specialty_dict(spec), "is_primary": bool(link.is_primary)} for link, spec in rows]


def doctor_specialties_bulk(tenant_id: int, doctor_ids) -> dict[int, list[dict]]:
    """Load all doctor-specialty links in one query for list endpoints."""
    ids = [int(value) for value in doctor_ids]
    if not ids:
        return {}
    rows = (db.session.query(ClinicDoctorSpecialty, ClinicSpecialty)
            .join(ClinicSpecialty, ClinicSpecialty.id == ClinicDoctorSpecialty.specialty_id)
            .filter(ClinicDoctorSpecialty.tenant_id == tenant_id,
                    ClinicDoctorSpecialty.doctor_id.in_(ids),
                    ClinicSpecialty.tenant_id == tenant_id)
            .order_by(ClinicDoctorSpecialty.doctor_id, ClinicDoctorSpecialty.is_primary.desc(), ClinicSpecialty.name_ar.asc()).all())
    result = {doctor_id: [] for doctor_id in ids}
    for link, spec in rows:
        result.setdefault(link.doctor_id, []).append({**specialty_dict(spec), "is_primary": bool(link.is_primary)})
    return result


def set_doctor_specialties(tenant_id: int, doctor_id: int, primary_id, specialty_ids, actor_id=None) -> list[dict]:
    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first()
    if not doctor:
        raise ValueError("الطبيب غير موجود")
    ids = {int(x) for x in (specialty_ids or []) if x not in (None, "")}
    primary = int(primary_id) if primary_id not in (None, "") else None
    if ids and not primary:
        raise ValueError("الاختصاص الرئيسي مطلوب")
    if primary:
        ids.add(primary)
    specs = ClinicSpecialty.query.filter(ClinicSpecialty.tenant_id == tenant_id, ClinicSpecialty.id.in_(ids)).all() if ids else []
    if len(specs) != len(ids):
        raise ValueError("أحد الاختصاصات لا يتبع هذه المنشأة")
    ClinicDoctorSpecialty.query.filter_by(tenant_id=tenant_id, doctor_id=doctor_id).delete(synchronize_session=False)
    for spec in specs:
        db.session.add(ClinicDoctorSpecialty(tenant_id=tenant_id, doctor_id=doctor_id, specialty_id=spec.id,
                                             is_primary=spec.id == primary, created_by=actor_id))
    primary_spec = next((s for s in specs if s.id == primary), None)
    doctor.specialty = primary_spec.name_ar if primary_spec else (specs[0].name_ar if specs else doctor.specialty)
    from modules.clinics.service import _audit
    _audit(tenant_id, actor_id, "doctor", doctor.id, "specialties", "تغيير اختصاصات الطبيب",
           meta={"primary_specialty_id": primary, "specialty_ids": sorted(ids)})
    db.session.flush()
    return doctor_specialties(tenant_id, doctor_id)


def assert_doctor_specialty(tenant_id: int, doctor_id: int | None, specialty_id: int | None) -> ClinicSpecialty | None:
    if not specialty_id:
        return None
    spec = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, id=int(specialty_id), is_active=True).first()
    if not spec:
        raise ValueError("الاختصاص غير موجود")
    if doctor_id and not ClinicDoctorSpecialty.query.filter_by(tenant_id=tenant_id, doctor_id=int(doctor_id), specialty_id=spec.id).first():
        raise ValueError("الاختصاص غير مرتبط بالطبيب المختار")
    return spec


def primary_specialty_id(tenant_id: int, doctor_id: int | None) -> int | None:
    if not doctor_id:
        return None
    link = (ClinicDoctorSpecialty.query.filter_by(tenant_id=tenant_id, doctor_id=doctor_id)
            .order_by(ClinicDoctorSpecialty.is_primary.desc(), ClinicDoctorSpecialty.id.asc()).first())
    return link.specialty_id if link else None


def published_template(tenant_id: int, specialty_id: int | None) -> ClinicVisitTemplate | None:
    if not specialty_id:
        return None
    return (ClinicVisitTemplate.query.filter_by(tenant_id=tenant_id, specialty_id=specialty_id, status="published", is_active=True)
            .order_by(ClinicVisitTemplate.is_default.desc(), ClinicVisitTemplate.version.desc()).first())


def template_dict(tenant_id: int, template_id: int, include_fields: bool = True) -> dict:
    row = ClinicVisitTemplate.query.filter_by(tenant_id=tenant_id, id=template_id).first()
    if not row:
        raise ValueError("نموذج الزيارة غير موجود")
    result = {"id": row.id, "specialty_id": row.specialty_id, "name": row.name, "version": row.version,
              "status": row.status, "is_active": bool(row.is_active), "is_default": bool(row.is_default), "sections": []}
    if not include_fields:
        return result
    sections = ClinicVisitTemplateSection.query.filter_by(tenant_id=tenant_id, template_id=row.id, is_active=True).order_by(ClinicVisitTemplateSection.sort_order).all()
    fields = ClinicVisitTemplateField.query.filter_by(tenant_id=tenant_id, template_id=row.id, is_active=True).order_by(ClinicVisitTemplateField.sort_order).all()
    by_section = {}
    for field in fields:
        by_section.setdefault(field.section_id, []).append({
            "id": field.id, "key": field.key, "label_ar": field.label_ar, "label_en": field.label_en or "",
            "field_type": field.field_type, "required": bool(field.required), "sort_order": field.sort_order,
            "unit": field.unit or "", "placeholder": field.placeholder or "",
            "options": json.loads(field.options_json or "[]"), "validation": json.loads(field.validation_json or "{}"),
            "visibility_rules": json.loads(field.visibility_rules_json or "{}"),
        })
    result["sections"] = [{"id": section.id, "title_ar": section.title_ar, "title_en": section.title_en or "",
                           "sort_order": section.sort_order, "is_collapsible": bool(section.is_collapsible),
                           "default_open": bool(section.default_open), "fields": by_section.get(section.id, [])} for section in sections]
    return result


def create_template(tenant_id: int, specialty_id: int, payload: dict, actor_id=None) -> dict:
    spec = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, id=specialty_id).first()
    if not spec:
        raise ValueError("الاختصاص غير موجود")
    version = (db.session.query(func.max(ClinicVisitTemplate.version)).filter_by(tenant_id=tenant_id, specialty_id=specialty_id).scalar() or 0) + 1
    row = ClinicVisitTemplate(tenant_id=tenant_id, specialty_id=specialty_id,
                              name=str(payload.get("name") or f"{spec.name_ar} v{version}").strip(), version=version,
                              status="draft", is_active=True, created_by=actor_id, updated_by=actor_id)
    db.session.add(row); db.session.flush()
    _replace_template_sections(tenant_id, row, payload.get("sections") or [])
    return template_dict(tenant_id, row.id)


def _replace_template_sections(tenant_id: int, template: ClinicVisitTemplate, sections: list[dict]) -> None:
    if template.status != "draft":
        raise ValueError("لا يمكن تعديل نموذج منشور؛ أنشئ نسخة جديدة")
    for s_index, data in enumerate(sections):
        title = str(data.get("title_ar") or "").strip()
        if not title:
            raise ValueError("عنوان القسم مطلوب")
        section = ClinicVisitTemplateSection(tenant_id=tenant_id, template_id=template.id, title_ar=title,
                    title_en=str(data.get("title_en") or "").strip() or None, sort_order=int(data.get("sort_order", s_index)),
                    is_collapsible=bool(data.get("is_collapsible", True)), default_open=bool(data.get("default_open", True)))
        db.session.add(section); db.session.flush()
        for f_index, item in enumerate(data.get("fields") or []):
            field_type = str(item.get("field_type") or "text")
            if field_type not in FIELD_TYPES:
                raise ValueError(f"نوع الحقل غير مدعوم: {field_type}")
            key = _code(item.get("key"))
            label = str(item.get("label_ar") or "").strip()
            if not key or not label:
                raise ValueError("مفتاح الحقل وتسميته مطلوبان")
            db.session.add(ClinicVisitTemplateField(tenant_id=tenant_id, template_id=template.id, section_id=section.id,
                key=key, label_ar=label, label_en=str(item.get("label_en") or "").strip() or None,
                field_type=field_type, required=bool(item.get("required", False)), sort_order=int(item.get("sort_order", f_index)),
                unit=str(item.get("unit") or "").strip() or None, placeholder=str(item.get("placeholder") or "").strip() or None,
                options_json=json.dumps(item.get("options") or [], ensure_ascii=False),
                validation_json=json.dumps(item.get("validation") or {}, ensure_ascii=False),
                visibility_rules_json=json.dumps(item.get("visibility_rules") or {}, ensure_ascii=False)))


def publish_template(tenant_id: int, template_id: int, actor_id=None) -> dict:
    query = ClinicVisitTemplate.query.filter_by(tenant_id=tenant_id, id=template_id)
    if db.session.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise ValueError("نموذج الزيارة غير موجود")
    if row.status == "published":
        return template_dict(tenant_id, row.id)
    if row.status != "draft":
        raise ValueError("يمكن نشر المسودات فقط")
    if not ClinicVisitTemplateField.query.filter_by(tenant_id=tenant_id, template_id=row.id, is_active=True).first():
        raise ValueError("أضف حقلاً واحداً على الأقل قبل النشر")
    fields = ClinicVisitTemplateField.query.filter_by(tenant_id=tenant_id, template_id=row.id, is_active=True).all()
    by_key = {f.key: f for f in fields}
    dependencies = {}
    for field in fields:
        rule = json.loads(field.visibility_rules_json or "{}")
        options = json.loads(field.options_json or "[]")
        if not isinstance(options, list) or any(not isinstance(x, str) for x in options):
            raise ValueError("خيارات الحقل يجب أن تكون نصوصاً")
        if field.field_type == "table" and (not options or len(options) > 20 or len(set(options)) != len(options)):
            raise ValueError("حدد أعمدة فريدة للجدول، بحد أقصى 20 عموداً")
        if not isinstance(rule, dict):
            raise ValueError("قاعدة الإظهار غير صالحة")
        if rule and (rule.get("field_key") not in by_key or rule.get("field_key") == field.key or rule.get("operator", "eq") not in {"eq", "ne", "contains", "not_empty"}):
            raise ValueError("قاعدة الإظهار تشير إلى حقل أو شرط غير صالح")
        if rule:
            dependencies[field.key] = rule["field_key"]
        if field.field_type in {"drawing", "body_map", "growth_chart", "pregnancy_tracker"}:
            raise ValueError("المكوّن التخصصي المتقدم غير متاح للنشر بعد")
    # One condition per field is the existing V1 engine, but conditions may form
    # a chain. Reject only actual graph cycles instead of rejecting every chain.
    for start in dependencies:
        seen = set()
        current = start
        while current in dependencies:
            if current in seen:
                raise ValueError("قواعد الإظهار تحتوي اعتماداً دائرياً")
            seen.add(current)
            current = dependencies[current]
    ClinicVisitTemplate.query.filter_by(tenant_id=tenant_id, specialty_id=row.specialty_id, is_default=True).update({"is_default": False}, synchronize_session=False)
    row.status = "published"; row.is_default = True; row.published_at = datetime.utcnow(); row.updated_by = actor_id
    spec = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, id=row.specialty_id).first()
    if spec:
        spec.default_visit_template_id = row.id
    from modules.clinics.service import _audit
    _audit(tenant_id, actor_id, "visit_template", row.id, "publish", f"نشر نموذج {row.name} v{row.version}")
    return template_dict(tenant_id, row.id)


def update_template(tenant_id: int, template_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicVisitTemplate.query.filter_by(tenant_id=tenant_id, id=template_id).first()
    if not row:
        raise ValueError("نموذج الزيارة غير موجود")
    if row.status != "draft" or ClinicVisit.query.filter_by(tenant_id=tenant_id, visit_template_id=row.id).first():
        raise ValueError("لا يمكن تعديل نموذج مستخدم أو منشور؛ أنشئ نسخة جديدة")
    with db.session.begin_nested():
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name:
                raise ValueError("اسم النموذج مطلوب")
            row.name = name
        if "sections" in payload:
            ClinicVisitTemplateField.query.filter_by(tenant_id=tenant_id, template_id=row.id).delete(synchronize_session=False)
            ClinicVisitTemplateSection.query.filter_by(tenant_id=tenant_id, template_id=row.id).delete(synchronize_session=False)
            _replace_template_sections(tenant_id, row, payload["sections"])
        row.updated_by = actor_id
        row.updated_at = datetime.utcnow()
    return template_dict(tenant_id, row.id)


def archive_template(tenant_id: int, template_id: int, actor_id=None) -> dict:
    row = ClinicVisitTemplate.query.filter_by(tenant_id=tenant_id, id=template_id).first()
    if not row:
        raise ValueError("نموذج الزيارة غير موجود")
    row.status = "archived"
    row.is_active = False
    row.is_default = False
    row.updated_by = actor_id
    spec = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, id=row.specialty_id).first()
    if spec and spec.default_visit_template_id == row.id:
        spec.default_visit_template_id = None
    from modules.clinics.service import _audit
    _audit(tenant_id, actor_id, "visit_template", row.id, "archive", "أرشفة النموذج مع حفظ الزيارات القديمة")
    return template_dict(tenant_id, row.id)


def visit_template_context(tenant_id: int, visit_id: int) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    template = template_dict(tenant_id, visit.visit_template_id) if visit.visit_template_id else None
    values = ClinicVisitFieldValue.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).all()
    value_map = {}
    for row in values:
        value_map[str(row.field_id)] = json.loads(row.value_json) if row.value_json else (float(row.value_number) if row.value_number is not None else row.value_text)
    spec = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, id=visit.specialty_id).first() if visit.specialty_id else None
    return {"specialty": specialty_dict(spec) if spec else None, "template": template, "values": value_map}


def save_visit_values(tenant_id: int, visit_id: int, payload: dict, actor_id=None) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    if visit.status == "completed":
        raise ValueError("لا يمكن تعديل الحقول التخصصية بعد إكمال الزيارة")
    if not visit.visit_template_id:
        raise ValueError("لا يوجد نموذج تخصص مرتبط بالزيارة")
    allowed = {f.id: f for f in ClinicVisitTemplateField.query.filter_by(tenant_id=tenant_id, template_id=visit.visit_template_id, is_active=True).all()}
    values = payload.get("values") or {}
    if not isinstance(values, dict):
        raise ValueError("قيم النموذج يجب أن تكون كائناً")
    # Validate the whole patch before touching any saved value.
    normalized = {}
    for raw_id, value in values.items():
        field = allowed.get(int(raw_id))
        if not field:
            raise ValueError("حقل غير تابع لنموذج هذه الزيارة")
        normalized[field.id] = _validate_field_value(field, value, enforce_required=False)
        if field.field_type in {"file", "image"} and normalized[field.id] is not None:
            _validate_attachment_value(tenant_id, visit, field, normalized[field.id])
    changes = []
    for raw_id, value in normalized.items():
        field_id = int(raw_id)
        field = allowed.get(field_id)
        if not field:
            raise ValueError("حقل غير تابع لنموذج هذه الزيارة")
        row = ClinicVisitFieldValue.query.filter_by(tenant_id=tenant_id, visit_id=visit_id, field_id=field_id).first()
        before = (json.loads(row.value_json) if row.value_json is not None else float(row.value_number) if row.value_number is not None else row.value_text) if row else None
        if before != value:
            changes.append({"field_id": field_id, "key": field.key, "before": before, "after": value})
        if not row:
            row = ClinicVisitFieldValue(tenant_id=tenant_id, visit_id=visit_id, field_id=field_id, created_by=actor_id)
            db.session.add(row)
        row.value_text = row.value_number = row.value_json = None
        if isinstance(value, (dict, list, bool)) or (field.field_type in {"file", "image"} and value is not None):
            row.value_json = json.dumps(value, ensure_ascii=False)
        elif field.field_type in {"number", "measurement"} and value not in (None, ""):
            row.value_number = float(value)
        else:
            row.value_text = None if value is None else str(value)
        row.updated_by = actor_id; row.updated_at = datetime.utcnow()
    from modules.clinics.service import _audit
    if changes:
        _audit(tenant_id, actor_id, "visit", visit.id, "clinical_fields_update", "تحديث حقول النموذج التخصصي", meta={"template_id": visit.visit_template_id, "changes": changes})
    db.session.flush()
    return visit_template_context(tenant_id, visit_id)


def _validate_field_value(field, value, *, enforce_required=True):
    if value is None or (isinstance(value, str) and not value.strip()) or value == []:
        if enforce_required and field.required:
            raise ValueError(f"الحقل مطلوب: {field.label_ar}")
        return None
    kind = field.field_type
    options = json.loads(field.options_json or "[]")
    rules = json.loads(field.validation_json or "{}")
    if kind in {"number", "measurement"}:
        if isinstance(value, bool):
            raise ValueError("قيمة رقمية غير صالحة")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("قيمة رقمية غير صالحة")
        if "min" in rules and value < float(rules["min"]):
            raise ValueError(f"القيمة أقل من الحد: {field.label_ar}")
        if "max" in rules and value > float(rules["max"]):
            raise ValueError(f"القيمة أكبر من الحد: {field.label_ar}")
    elif kind in {"boolean", "checkbox"}:
        if not isinstance(value, bool):
            raise ValueError("قيمة منطقية غير صالحة")
    elif kind == "multi_select":
        if not isinstance(value, list) or any(item not in options for item in value):
            raise ValueError("خيار متعدد غير صالح")
    elif kind in {"select", "radio"}:
        if value not in options:
            raise ValueError("خيار غير صالح")
    elif kind == "table":
        if not isinstance(value, list) or len(value) > 100 or any(not isinstance(row, dict) for row in value):
            raise ValueError("الجدول يجب أن يحتوي على 100 صف كحد أقصى")
        if any(set(row) - set(options) or any(not isinstance(v, str) or len(v) > 2000 for v in row.values()) for row in value):
            raise ValueError("أعمدة أو قيم الجدول غير صالحة")
    elif kind in {"file", "image"}:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("مرجع المرفق غير صالح")
    elif kind in {"text", "textarea", "date", "time"}:
        if not isinstance(value, str):
            raise ValueError("قيمة نصية غير صالحة")
        if len(value) > int(rules.get("max_length", 20000)):
            raise ValueError("قيمة النص طويلة جداً")
        if kind == "date":
            date.fromisoformat(value)
        if kind == "time":
            time.fromisoformat(value)
    return value


def _validate_attachment_value(tenant_id, visit, field, attachment_id):
    from modules.clinics.models import ClinicAttachment
    row = ClinicAttachment.query.filter_by(tenant_id=tenant_id, id=attachment_id, patient_id=visit.patient_id).first()
    if not row or row.visit_id not in (None, visit.id):
        raise ValueError("المرفق غير تابع للمريض أو الزيارة")
    if field.field_type == "image" and not str(row.mime_type or "").startswith("image/"):
        raise ValueError("هذا الحقل يقبل صورة فقط")


def field_is_visible(field, values_by_key):
    rule = json.loads(field.visibility_rules_json or "{}")
    if not rule:
        return True
    value = values_by_key.get(rule.get("field_key"))
    operator = rule.get("operator", "eq")
    if operator == "eq":
        return value == rule.get("value")
    if operator == "ne":
        return value != rule.get("value")
    if operator == "contains":
        return isinstance(value, list) and rule.get("value") in value
    if operator == "not_empty":
        return value not in (None, "", [])
    return False


def validate_visit_completion(tenant_id: int, visit: ClinicVisit) -> None:
    """Validate the pinned version before any completion or billing mutation."""
    if visit.tenant_id != tenant_id:
        raise ValueError("الزيارة غير موجودة")
    if not visit.visit_template_id:
        return  # Legacy core-only visits remain compatible.
    template = ClinicVisitTemplate.query.filter_by(tenant_id=tenant_id, id=visit.visit_template_id).first()
    if not template or template.specialty_id != visit.specialty_id:
        raise ValueError("نموذج الزيارة غير متوافق مع الاختصاص")
    fields = (ClinicVisitTemplateField.query.join(
        ClinicVisitTemplateSection, ClinicVisitTemplateSection.id == ClinicVisitTemplateField.section_id
    ).filter(
        ClinicVisitTemplateField.tenant_id == tenant_id,
        ClinicVisitTemplateField.template_id == template.id,
        ClinicVisitTemplateField.is_active.is_(True),
        ClinicVisitTemplateSection.tenant_id == tenant_id,
        ClinicVisitTemplateSection.template_id == template.id,
        ClinicVisitTemplateSection.is_active.is_(True),
    ).all())
    values = {row.field_id: row for row in ClinicVisitFieldValue.query.filter_by(tenant_id=tenant_id, visit_id=visit.id).all()}
    decoded = {f.key: (json.loads(values[f.id].value_json) if values[f.id].value_json is not None else values[f.id].value_number if values[f.id].value_number is not None else values[f.id].value_text) for f in fields if f.id in values}
    for field in fields:
        if not field_is_visible(field, decoded):
            continue
        row = values.get(field.id)
        value = None
        if row:
            value = json.loads(row.value_json) if row.value_json is not None else (row.value_number if row.value_number is not None else row.value_text)
        _validate_field_value(field, value)
        if field.field_type in {"file", "image"} and value is not None:
            _validate_attachment_value(tenant_id, visit, field, value)


def assign_visit_specialty(tenant_id: int, visit: ClinicVisit, specialty_id=None, *, doctor_id=None) -> None:
    if visit.tenant_id != tenant_id:
        raise ValueError("الزيارة غير موجودة")
    target_doctor = doctor_id if doctor_id is not None else visit.doctor_id
    if target_doctor and not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=target_doctor).first():
        raise ValueError("الطبيب غير موجود")
    chosen = int(specialty_id) if specialty_id else primary_specialty_id(tenant_id, target_doctor)
    assert_doctor_specialty(tenant_id, target_doctor, chosen)
    from modules.clinics.service import assert_service_selection
    assert_service_selection(tenant_id, visit.service_id, target_doctor, chosen)
    if visit.visit_template_id and chosen == visit.specialty_id:
        visit.doctor_id = target_doctor
        return
    if visit.visit_template_id and ClinicVisitFieldValue.query.filter_by(tenant_id=tenant_id, visit_id=visit.id).first():
        raise ValueError("لا يمكن تغيير الاختصاص بعد تسجيل قيم النموذج")
    template = published_template(tenant_id, chosen) if chosen else None
    visit.doctor_id = target_doctor
    visit.specialty_id = chosen
    visit.visit_template_id = template.id if template else None


def migrate_legacy_specialties(tenant_id: int, session=None) -> None:
    """Idempotent compatibility migration for one tenant database."""
    session = session if session is not None else db.session
    marker = "specialties_v17_migrated"
    if session.query(ClinicAuditLog).filter_by(tenant_id=tenant_id, action=marker).first():
        return
    settings = session.query(ClinicSettings).filter_by(tenant_id=tenant_id).first()
    doctors = session.query(ClinicDoctor).filter_by(tenant_id=tenant_id).all()
    if settings:
        legacy = str(settings.clinic_type or "").strip()
        if legacy == "medical_center":
            settings.organization_mode = "medical_center"
        elif legacy in {"multi_doctor", "multi_doctor_clinic"} or len(doctors) > 1:
            settings.organization_mode = "multi_doctor_clinic"
        elif settings.organization_mode not in {x[0] for x in ORGANIZATION_MODES}:
            settings.organization_mode = "solo_clinic"
    for doctor in doctors:
        if session.query(ClinicDoctorSpecialty).filter_by(tenant_id=tenant_id, doctor_id=doctor.id).first():
            continue
        label = str(doctor.specialty or "").strip()
        legacy_spec = LEGACY_SPECIALTY_MAP.get(str(settings.clinic_type if settings else "")) if not label else None
        if not label and legacy_spec:
            code, label, name_en = legacy_spec
        elif label:
            code, name_en = _code(label) or _fallback_code("legacy", label), None
        else:
            continue
        spec = session.query(ClinicSpecialty).filter_by(tenant_id=tenant_id, name_ar=label).first()
        if not spec:
            spec = session.query(ClinicSpecialty).filter_by(tenant_id=tenant_id, code=code).first()
        if not spec:
            spec = ClinicSpecialty(tenant_id=tenant_id, code=code, name_ar=label, name_en=name_en,
                                   is_active=True, is_system=bool(legacy_spec))
            session.add(spec); session.flush()
        session.add(ClinicDoctorSpecialty(tenant_id=tenant_id, doctor_id=doctor.id,
                                             specialty_id=spec.id, is_primary=True))
    session.flush()
    primary = {link.doctor_id: link.specialty_id for link in session.query(ClinicDoctorSpecialty).filter_by(tenant_id=tenant_id, is_primary=True).all()}
    appointments = session.query(ClinicAppointment).filter_by(tenant_id=tenant_id).all()
    for appt in appointments:
        if appt.specialty_id is None:
            appt.specialty_id = primary.get(appt.doctor_id)
    appointment_specialties = {appt.id: appt.specialty_id for appt in appointments}
    for visit in session.query(ClinicVisit).filter_by(tenant_id=tenant_id).all():
        if not visit.specialty_id:
            visit.specialty_id = appointment_specialties.get(visit.appointment_id) or primary.get(visit.doctor_id)
        # Historical visits retain their original core-only form, even after seeding.
    session.add(ClinicAuditLog(tenant_id=tenant_id, entity_type="schema", action=marker,
                               summary="ترحيل الاختصاصات القديمة دون تغيير نماذج الزيارات التاريخية"))
    session.flush()


def _seed_internal_medicine_template(tenant_id: int, specialty: ClinicSpecialty, actor_id=None) -> None:
    sections = [
        {"title_ar": "التاريخ المرضي", "title_en": "Medical History", "fields": [
            {"key": "history_present_illness", "label_ar": "تاريخ المرض الحالي", "field_type": "textarea"},
            {"key": "past_medical_history", "label_ar": "التاريخ المرضي السابق", "field_type": "textarea"},
            {"key": "previous_surgeries", "label_ar": "العمليات السابقة", "field_type": "textarea"},
            {"key": "family_history", "label_ar": "التاريخ العائلي", "field_type": "textarea"},
            {"key": "smoking", "label_ar": "التدخين", "field_type": "select", "options": ["لا", "حالياً", "سابقاً"]},
            {"key": "current_medications", "label_ar": "الأدوية الحالية", "field_type": "textarea"},
        ]},
        {"title_ar": "الأمراض المزمنة", "title_en": "Chronic Conditions", "fields": [
            {"key": "chronic_conditions_review", "label_ar": "مراجعة الأمراض المزمنة", "field_type": "multi_select",
             "options": ["السكري", "ارتفاع الضغط", "أمراض القلب", "أمراض الكلى", "أمراض الكبد", "الغدة الدرقية", "الربو/COPD", "فقر الدم", "السمنة", "أخرى"]},
        ]},
        {"title_ar": "الفحص السريري", "title_en": "Examination", "fields": [
            {"key": f"exam_{key}", "label_ar": label, "field_type": "radio", "options": ["طبيعي", "غير طبيعي", "لم يفحص"]}
            for key, label in (("general", "الفحص العام"), ("cardiovascular", "القلب والأوعية"),
                               ("respiratory", "الجهاز التنفسي"), ("abdominal", "البطن"),
                               ("neurological", "الجهاز العصبي"), ("extremities", "الأطراف"))
        ]},
        {"title_ar": "التقييم والخطة", "title_en": "Assessment and Plan", "fields": [
            {"key": "assessment_plan", "label_ar": "التقييم والخطة", "field_type": "textarea"},
        ]},
    ]
    data = create_template(tenant_id, specialty.id, {"name": "نموذج زيارة الباطنية", "sections": sections}, actor_id)
    publish_template(tenant_id, data["id"], actor_id)


def _seed_additional_templates(tenant_id: int, actor_id=None) -> None:
    """Documentation presets only; vitals, diagnoses and treatment remain core."""
    presets = {
        "dentistry": (
            ("التاريخ السني", [("dental_history", "التاريخ السني", "textarea")]),
            ("مخطط الأسنان", [("dental_chart", "مخطط الأسنان التفاعلي", "dental_chart")]),
            ("الفحص والخطة", [("dental_examination", "ملاحظات فحص الأسنان", "textarea"),
                               ("dental_plan", "خطة العلاج", "textarea"),
                               ("dental_followup", "توصية المتابعة", "textarea")]),
        ),
        "pediatrics": (
            ("ملخص وولادة", [("pediatric_overview", "ملخص زيارة الأطفال", "textarea")]),
            ("تاريخ النمو", [("pediatric_growth_history", "تاريخ قياسات النمو", "pediatric_growth_history")]),
            ("التطعيمات", [("vaccination_history", "سجل التطعيمات", "vaccination_history")]),
            ("التطور", [("development_tracker", "تتبع التطور", "development_tracker")]),
            ("الفحص والمتابعة", [
                ("exam_general", "الفحص العام", "radio", ["طبيعي", "غير طبيعي", "لم يفحص"]),
                ("exam_respiratory", "الجهاز التنفسي", "radio", ["طبيعي", "غير طبيعي", "لم يفحص"]),
                ("exam_cardio", "القلب والأوعية", "radio", ["طبيعي", "غير طبيعي", "لم يفحص"]),
                ("exam_abdomen", "البطن", "radio", ["طبيعي", "غير طبيعي", "لم يفحص"]),
                ("exam_neuro", "الجهاز العصبي", "radio", ["طبيعي", "غير طبيعي", "لم يفحص"]),
                ("exam_ent", "أنف وأذن وحنجرة", "radio", ["طبيعي", "غير طبيعي", "لم يفحص"]),
                ("exam_skin", "الجلد", "radio", ["طبيعي", "غير طبيعي", "لم يفحص"]),
                ("exam_hydration", "الترطيب", "radio", ["طبيعي", "غير طبيعي", "لم يفحص"]),
                ("pediatric_followup", "توصية المتابعة", "textarea"),
            ]),
        ),
        "obstetrics_gynecology": (
            ("التاريخ النسائي والتوليدي", [("lmp", "تاريخ آخر دورة", "date"),
                                            ("edd", "موعد الولادة المتوقع (يدخله الطبيب)", "date"),
                                            ("gravida", "عدد مرات الحمل", "number"),
                                            ("para", "عدد الولادات", "number"),
                                            ("abortions", "عدد حالات الإجهاض", "number"),
                                            ("pregnancy_week", "أسبوع الحمل", "number"),
                                            ("obstetric_history", "التاريخ التوليدي", "textarea")]),
            ("الخطة والمتابعة", [("obstetric_plan", "الخطة", "textarea"),
                                   ("obstetric_followup", "توصية المتابعة", "textarea")]),
        ),
        "cardiology": (
            ("الأعراض القلبية", [
                ("chest_pain", "ألم صدري", "select", ["لا", "نعم"]),
                ("chest_pain_onset", "بداية الألم", "text"),
                ("chest_pain_location", "موقع الألم", "text"),
                ("chest_pain_character", "طبيعة الألم", "text"),
                ("chest_pain_radiation", "انتشار الألم", "text"),
                ("chest_pain_duration", "مدة الألم", "text"),
                ("chest_pain_provoking", "محفزات", "textarea"),
                ("chest_pain_relieving", "مخففات", "textarea"),
                ("chest_pain_associated", "أعراض مرافقة", "textarea"),
                ("dyspnea", "ضيق تنفس", "select", ["لا", "نعم"]),
                ("dyspnea_onset", "بداية ضيق التنفس", "text"),
                ("dyspnea_exertional", "عند الجهد", "select", ["لا", "نعم"]),
                ("dyspnea_resting", "في الراحة", "select", ["لا", "نعم"]),
                ("orthopnea", "ضيق تنفس اضطجاعي", "select", ["لا", "نعم"]),
                ("pnd", "ضيق تنفس ليلي انتيابي", "select", ["لا", "نعم"]),
                ("nyha_class", "NYHA (اختيار الطبيب)", "select", ["", "I", "II", "III", "IV"]),
                ("palpitations", "خفقان", "select", ["لا", "نعم"]),
                ("palpitations_notes", "ملاحظات الخفقان", "textarea"),
                ("syncope", "إغماء", "select", ["لا", "نعم"]),
                ("presyncope", "قبل الإغماء", "select", ["لا", "نعم"]),
                ("leg_swelling", "تورم الساقين", "select", ["لا", "نعم"]),
                ("fatigue", "إرهاق", "select", ["لا", "نعم"]),
                ("exercise_intolerance", "عدم تحمل الجهد", "select", ["لا", "نعم"]),
                ("cardiac_symptoms_notes", "ملاحظات الأعراض", "textarea"),
            ]),
            ("الفحص القلبي", [
                ("exam_general_appearance", "المظهر العام", "textarea"),
                ("exam_jvp", "JVP", "text"),
                ("exam_heart_sounds", "أصوات القلب", "textarea"),
                ("murmur_present", "نفخة", "select", ["لا", "نعم"]),
                ("murmur_location", "موقع النفخة", "text"),
                ("murmur_timing", "توقيت النفخة", "text"),
                ("murmur_grade", "درجة النفخة", "text"),
                ("murmur_radiation", "انتشار النفخة", "text"),
                ("murmur_notes", "ملاحظات النفخة", "textarea"),
                ("exam_peripheral_pulses", "نبضات طرفية", "textarea"),
                ("exam_edema", "الوذمة", "textarea"),
                ("exam_respiratory", "موجودات تنفسية", "textarea"),
                ("exam_other_notes", "ملاحظات الفحص", "textarea"),
            ]),
            ("التقييم والمتابعة", [
                ("cardio_assessment", "التقييم", "textarea"),
                ("cardio_plan", "الخطة", "textarea"),
                ("cardio_followup", "توصية المتابعة", "textarea"),
            ]),
        ),
        "urology": (
            ("الأعراض البولية", [
                ("dysuria", "حرقة تبول", "select", ["لا", "نعم"]),
                ("frequency", "تكرار التبول", "select", ["لا", "نعم"]),
                ("urgency", "إلحاح بولي", "select", ["لا", "نعم"]),
                ("nocturia", "تبول ليلي", "select", ["لا", "نعم"]),
                ("hesitancy", "تردد/صعوبة بدء التبول", "select", ["لا", "نعم"]),
                ("weak_stream", "ضعف تدفق البول", "select", ["لا", "نعم"]),
                ("incomplete_emptying", "إحساس بعدم إفراغ المثانة", "select", ["لا", "نعم"]),
                ("hematuria", "دم في البول", "select", ["لا", "نعم"]),
                ("flank_pain", "ألم خاصرة", "select", ["لا", "نعم"]),
                ("renal_colic", "مغص كلوي", "select", ["لا", "نعم"]),
                ("incontinence", "سلس بولي", "select", ["لا", "نعم"]),
                ("erectile_dysfunction", "ضعف انتصاب", "select", ["لا", "نعم"]),
                ("scrotal_mass", "كتلة صفن", "select", ["لا", "نعم"]),
                ("urology_symptoms_notes", "ملاحظات الأعراض", "textarea"),
            ]),
            ("الفحص والتقييم", [
                ("exam_abdomen", "فحص البطن", "textarea"),
                ("exam_cva", "إيلام الزاوية الضلعية القطنية", "select", ["لا", "نعم", "لم يفحص"]),
                ("exam_scrotum", "فحص الصفن", "textarea"),
                ("dre_notes", "فحص المستقيم/البروستات", "textarea"),
                ("ipss_score", "IPSS (إن وُجد)", "number"),
                ("urology_assessment", "التقييم", "textarea"),
                ("urology_plan", "الخطة", "textarea"),
                ("urology_followup", "توصية المتابعة", "textarea"),
            ]),
        ),
        "dermatology": (
            ("القصة الجلدية", [
                ("rash_onset", "بداية الطفح/الشكوى", "text"),
                ("itch", "حكة", "select", ["لا", "نعم"]),
                ("distribution", "التوزيع", "textarea"),
                ("previous_treatments", "علاجات سابقة", "textarea"),
            ]),
            ("الفحص", [
                ("lesion_type", "نوع الآفة", "textarea"),
                ("skin_exam", "موجودات الفحص", "textarea"),
                ("derm_plan", "الخطة", "textarea"),
            ]),
        ),
        "ent": (
            ("الأعراض", [
                ("ear_pain", "ألم أذن", "select", ["لا", "نعم"]),
                ("nasal_obstruction", "انسداد أنف", "select", ["لا", "نعم"]),
                ("sore_throat", "التهاب حلق", "select", ["لا", "نعم"]),
                ("vertigo", "دوار", "select", ["لا", "نعم"]),
                ("ent_notes", "ملاحظات", "textarea"),
            ]),
            ("الفحص والخطة", [
                ("ear_exam", "فحص الأذن", "textarea"),
                ("nose_exam", "فحص الأنف", "textarea"),
                ("throat_exam", "فحص الحلق", "textarea"),
                ("ent_plan", "الخطة", "textarea"),
            ]),
        ),
        "ophthalmology": (
            ("الأعراض", [
                ("vision_change", "تغير الرؤية", "textarea"),
                ("eye_pain", "ألم عين", "select", ["لا", "نعم"]),
                ("redness", "احمرار", "select", ["لا", "نعم"]),
                ("discharge", "إفرازات", "select", ["لا", "نعم"]),
            ]),
            ("الفحص", [
                ("visual_acuity", "حدة البصر", "text"),
                ("eye_exam", "موجودات الفحص", "textarea"),
                ("ophtho_plan", "الخطة", "textarea"),
            ]),
        ),
        "orthopedics": (
            ("الأعراض", [
                ("pain_site", "موقع الألم", "text"),
                ("trauma_history", "قصة رضح", "textarea"),
                ("swelling", "تورم", "select", ["لا", "نعم"]),
                ("limited_rom", "محدودية حركة", "select", ["لا", "نعم"]),
            ]),
            ("الفحص والخطة", [
                ("ortho_exam", "الفحص العظمي/المفصلي", "textarea"),
                ("ortho_plan", "الخطة", "textarea"),
            ]),
        ),
        "neurology": (
            ("الأعراض", [
                ("headache", "صداع", "select", ["لا", "نعم"]),
                ("dizziness", "دوخة", "select", ["لا", "نعم"]),
                ("weakness", "ضعف", "select", ["لا", "نعم"]),
                ("numbness", "تنميل", "select", ["لا", "نعم"]),
                ("seizure", "تشنجات", "select", ["لا", "نعم"]),
                ("neuro_history", "القصة العصبية", "textarea"),
            ]),
            ("الفحص والخطة", [
                ("neuro_exam", "الفحص العصبي", "textarea"),
                ("neuro_plan", "الخطة", "textarea"),
            ]),
        ),
        "endocrinology": (
            ("المتابعة الغدية", [
                ("diabetes_control", "ضبط السكري", "textarea"),
                ("thyroid_symptoms", "أعراض درقية", "textarea"),
                ("weight_change", "تغير الوزن", "text"),
                ("endo_meds", "الأدوية الحالية", "textarea"),
            ]),
            ("التقييم", [
                ("endo_exam", "الفحص", "textarea"),
                ("endo_plan", "الخطة", "textarea"),
            ]),
        ),
        "gastroenterology": (
            ("الأعراض الهضمية", [
                ("abdominal_pain", "ألم بطن", "select", ["لا", "نعم"]),
                ("heartburn", "حموضة", "select", ["لا", "نعم"]),
                ("diarrhea", "إسهال", "select", ["لا", "نعم"]),
                ("constipation", "إمساك", "select", ["لا", "نعم"]),
                ("gi_bleeding", "نزف هضمي", "select", ["لا", "نعم"]),
                ("gi_notes", "ملاحظات", "textarea"),
            ]),
            ("الفحص والخطة", [
                ("abdomen_exam", "فحص البطن", "textarea"),
                ("gi_plan", "الخطة", "textarea"),
            ]),
        ),
        "nephrology": (
            ("الأعراض الكلوية", [
                ("edema", "تورم", "select", ["لا", "نعم"]),
                ("oliguria", "قلة بول", "select", ["لا", "نعم"]),
                ("htn_control", "ضبط الضغط", "textarea"),
                ("dialysis_status", "حالة الغسيل", "textarea"),
            ]),
            ("التقييم", [
                ("nephro_exam", "الفحص", "textarea"),
                ("nephro_plan", "الخطة", "textarea"),
            ]),
        ),
        "pulmonology": (
            ("الأعراض التنفسية", [
                ("cough", "سعال", "select", ["لا", "نعم"]),
                ("dyspnea", "ضيق تنفس", "select", ["لا", "نعم"]),
                ("wheeze", "أزيز", "select", ["لا", "نعم"]),
                ("sputum", "بلغم", "select", ["لا", "نعم"]),
                ("pulm_notes", "ملاحظات", "textarea"),
            ]),
            ("الفحص والخطة", [
                ("chest_exam", "فحص الصدر", "textarea"),
                ("pulm_plan", "الخطة", "textarea"),
            ]),
        ),
        "rheumatology": (
            ("الأعراض الروماتيزمية", [
                ("joint_pain", "ألم مفاصل", "select", ["لا", "نعم"]),
                ("morning_stiffness", "تيبس صباحي", "select", ["لا", "نعم"]),
                ("joint_swelling", "تورم مفصل", "select", ["لا", "نعم"]),
                ("rheum_notes", "ملاحظات", "textarea"),
            ]),
            ("الفحص والخطة", [
                ("joint_exam", "فحص المفاصل", "textarea"),
                ("rheum_plan", "الخطة", "textarea"),
            ]),
        ),
        "general_surgery": (
            ("القصة الجراحية", [
                ("acute_abdomen", "بطن حاد", "select", ["لا", "نعم"]),
                ("mass_or_hernia", "كتلة/فتق", "textarea"),
                ("wound_status", "حالة الجرح", "textarea"),
                ("surgery_history", "عمليات سابقة", "textarea"),
            ]),
            ("الفحص والخطة", [
                ("surgical_exam", "الفحص", "textarea"),
                ("surgical_plan", "الخطة", "textarea"),
            ]),
        ),
        "psychiatry": (
            ("التقييم النفسي", [
                ("mood", "المزاج", "textarea"),
                ("sleep", "النوم", "textarea"),
                ("anxiety", "القلق", "textarea"),
                ("suicidal_ideation", "أفكار انتحارية", "select", ["لا", "نعم — يحتاج تقييماً فورياً"]),
                ("psych_notes", "ملاحظات", "textarea"),
            ]),
            ("الخطة", [
                ("psych_plan", "الخطة العلاجية", "textarea"),
            ]),
        ),
        "physiotherapy": (
            ("التقييم الوظيفي", [
                ("pain_site", "موقع الألم", "text"),
                ("rom_status", "مدى الحركة", "textarea"),
                ("muscle_strength", "القوة العضلية", "textarea"),
                ("gait", "المشية", "textarea"),
            ]),
            ("الخطة", [
                ("pt_plan", "خطة العلاج الطبيعي", "textarea"),
            ]),
        ),
        "nutrition": (
            ("التقييم الغذائي", [
                ("goal", "الهدف", "textarea"),
                ("diet_history", "التاريخ الغذائي", "textarea"),
                ("bmi_notes", "ملاحظات الوزن/BMI", "textarea"),
            ]),
            ("الخطة", [
                ("nutrition_plan", "الخطة الغذائية", "textarea"),
            ]),
        ),
        "general_medicine": (
            ("القصة الحالية", [
                ("hpi", "تاريخ المرض الحالي", "textarea"),
                ("associated_symptoms", "أعراض مرافقة", "textarea"),
            ]),
            ("الفحص والخطة", [
                ("general_exam", "الفحص العام", "textarea"),
                ("general_plan", "الخطة", "textarea"),
            ]),
        ),
        "family_medicine": (
            ("المتابعة الأسرية", [
                ("chronic_review", "مراجعة الأمراض المزمنة", "textarea"),
                ("preventive_care", "الوقاية والفحوصات الدورية", "textarea"),
            ]),
            ("الفحص والخطة", [
                ("fm_exam", "الفحص", "textarea"),
                ("fm_plan", "الخطة", "textarea"),
            ]),
        ),
    }
    for code, sections in presets.items():
        specialty = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, code=code).first()
        if not specialty or ClinicVisitTemplate.query.filter_by(tenant_id=tenant_id, specialty_id=specialty.id).first():
            continue

        def _field_payload(spec):
            key, label, kind = spec[0], spec[1], spec[2]
            field = {"key": key, "label_ar": label, "field_type": kind}
            if len(spec) > 3:
                field["options"] = list(spec[3])
            return field

        payload = {"name": f"نموذج {specialty.name_ar}", "sections": [
            {"title_ar": title, "fields": [_field_payload(spec) for spec in fields]}
            for title, fields in sections
        ]}
        template = create_template(tenant_id, specialty.id, payload, actor_id)
        publish_template(tenant_id, template["id"], actor_id)
