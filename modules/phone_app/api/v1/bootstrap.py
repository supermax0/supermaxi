"""Bootstrap for Finora Phone."""

from __future__ import annotations

from flask import g

from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.schemas import api_ok
from modules.phone_app.services.feature_flags import get_feature_flags
from utils.tenant_provinces import get_tenant_provinces_config


@phone_api_v1_bp.get("/bootstrap")
@require_phone_auth
def bootstrap():
    branding = {"name": "Finora Phone", "tenant_slug": g.tenant}
    province_config = get_tenant_provinces_config()
    try:
        from models.tenant import Tenant

        # Tenant row may live on core; ignore failures on tenant DB.
        t = Tenant.query.filter_by(slug=g.tenant).first()
        if t:
            branding["company_name"] = getattr(t, "name", None) or g.tenant
    except Exception:
        branding["company_name"] = g.tenant

    return api_ok(
        {
            "branding": branding,
            "feature_flags": get_feature_flags(),
            "settings": {
                "missed_call_followup_minutes": _followup_minutes(),
                "allowed_followup_minutes": [5, 15, 30],
                "provinces": province_config["list"],
                "primary_province": province_config["primary"],
            },
            "min_app_version": "1.0.0",
            "employee": {
                "id": g.phone_employee.id,
                "name": g.phone_employee.name,
                "role": g.phone_employee.role,
            },
        }
    )


def _followup_minutes() -> int:
    try:
        from models.system_settings import SystemSettings

        row = SystemSettings.query.filter_by(key="phone_missed_followup_minutes").first()
        if row and row.value:
            m = int(str(row.value).strip())
            if m in (5, 15, 30, 60):
                return m
    except Exception:
        pass
    return 30
