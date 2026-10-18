"""Central server-side specialty registry and deterministic resolver."""
from __future__ import annotations

import json

from modules.clinics.models import (
    ClinicAppointment,
    ClinicDoctorSpecialty,
    ClinicSettings,
    ClinicSpecialty,
    ClinicVisit,
)

ALIASES = {"dental": "dentistry", "general": "general_medicine", "general_practice": "general_medicine"}

REGISTRY = {
    "general_medicine": {"workspace": "general", "features": {}},
    "internal_medicine": {"workspace": "internal_medicine", "features": {"clinical_timeline": True}},
    "cardiology": {"workspace": "cardiology", "features": {"ecg": True, "echo": True}},
    "pediatrics": {"workspace": "pediatrics", "features": {"growth": True, "vaccinations": True}},
    "obstetrics_gynecology": {"workspace": "gynecology", "features": {"pregnancy": True}},
    "dentistry": {
        "workspace": "dental",
        "features": {
            "odontogram": True,
            "treatment_plans": True,
            "sessions": True,
            "dental_images": True,
            "dental_reports": True,
        },
    },
}


def canonical_code(value) -> str:
    code = str(value or "").strip().lower()
    return ALIASES.get(code, code)


def registry_entry(code) -> dict:
    canonical = canonical_code(code) or "general_medicine"
    configured = REGISTRY.get(canonical, {"workspace": "general", "features": {}})
    return {
        "code": canonical,
        "workspace": configured["workspace"],
        "features": dict(configured["features"]),
    }


def _feature_overrides(settings: ClinicSettings | None, code: str) -> dict:
    if not settings or not settings.specialty_features_json:
        return {}
    try:
        data = json.loads(settings.specialty_features_json)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    scoped = data.get(code, data)
    return scoped if isinstance(scoped, dict) else {}


def _specialty_by_id(tenant_id: int, specialty_id) -> ClinicSpecialty | None:
    if not specialty_id:
        return None
    return ClinicSpecialty.query.filter_by(
        tenant_id=tenant_id, id=int(specialty_id), is_active=True
    ).first()


def resolve_specialty(
    tenant_id: int,
    *,
    visit: ClinicVisit | None = None,
    appointment: ClinicAppointment | None = None,
    doctor_id: int | None = None,
) -> dict:
    """Resolve snapshot -> doctor primary -> clinic primary -> general."""
    settings = ClinicSettings.query.filter_by(tenant_id=tenant_id).first()
    source = "general"
    specialty = None
    snapshot_code = None
    snapshot_workspace = None

    context = visit or appointment
    if context is not None:
        if context.tenant_id != tenant_id:
            raise ValueError("السجل غير موجود")
        snapshot_code = canonical_code(getattr(context, "specialty_code_snapshot", None))
        snapshot_workspace = getattr(context, "workspace_snapshot", None)
        specialty = _specialty_by_id(tenant_id, getattr(context, "specialty_id", None))
        if snapshot_code or specialty:
            source = "visit_snapshot" if visit is not None else "appointment_snapshot"

    effective_doctor = doctor_id or (getattr(context, "doctor_id", None) if context else None)
    if not snapshot_code and specialty is None and effective_doctor:
        link = (
            ClinicDoctorSpecialty.query.filter_by(tenant_id=tenant_id, doctor_id=int(effective_doctor))
            .order_by(ClinicDoctorSpecialty.is_primary.desc(), ClinicDoctorSpecialty.id.asc())
            .first()
        )
        specialty = _specialty_by_id(tenant_id, link.specialty_id if link else None)
        if specialty:
            source = "doctor_primary"

    if not snapshot_code and specialty is None and settings:
        specialty = _specialty_by_id(tenant_id, settings.primary_specialty_id)
        if specialty:
            source = "clinic_primary"

    entry = registry_entry(snapshot_code or (specialty.code if specialty else "general_medicine"))
    if snapshot_workspace:
        entry["workspace"] = snapshot_workspace
    entry["features"].update(_feature_overrides(settings, entry["code"]))
    if entry["code"] in {"dentistry", "dental"} and settings:
        from modules.clinics.service_dental_completion import normalize_dental_config
        dental_config = normalize_dental_config(getattr(settings, "dental_config_json", None))
        entry["dental_config"] = dental_config
        if not dental_config["enabled"]:
            for key in ("odontogram", "treatment_plans", "sessions", "dental_images", "dental_reports"):
                entry["features"][key] = False
            entry["disabled_reason"] = "وحدة الأسنان موقوفة من إعدادات العيادة"
    entry.update({"specialty_id": specialty.id if specialty else None, "source": source})
    return entry


def apply_specialty_snapshot(tenant_id: int, row, *, doctor_id=None) -> dict:
    resolved = resolve_specialty(
        tenant_id,
        visit=row if isinstance(row, ClinicVisit) else None,
        appointment=row if isinstance(row, ClinicAppointment) else None,
        doctor_id=doctor_id,
    )
    row.specialty_code_snapshot = resolved["code"]
    row.workspace_snapshot = resolved["workspace"]
    return resolved
