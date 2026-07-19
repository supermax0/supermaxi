"""Health and bootstrap endpoints."""
from __future__ import annotations

from flask import g

from modules.mobile_app.api.v1.routes import mobile_api_v1_bp
from modules.mobile_app.schemas import api_ok
from modules.mobile_app.services import design as design_service
from modules.mobile_app.services.feature_flags import is_flag_enabled, list_feature_flags


@mobile_api_v1_bp.get("/health")
def health():
    return api_ok(
        {
            "service": "finora-mobile-api",
            "version": "v1",
            "tenant": getattr(g, "tenant", None),
            "status": "ok",
        }
    )


@mobile_api_v1_bp.get("/bootstrap")
def bootstrap():
    flags = list_feature_flags()
    design = design_service.get_design()
    return api_ok(
        {
            "tenant": getattr(g, "tenant", None),
            "feature_flags": flags,
            "branding": {
                "app_name": design["app_name"],
                "primary_dark": design["primary_dark"],
                "surface_dark": design["surface_dark"],
                "soft_white": design["soft_white"],
                "gold_accent": design["gold_accent"],
                "muted_gold": design["muted_gold"],
                "logo_url": design.get("logo_url") or "",
            },
            "maintenance": {
                "enabled": bool(design.get("maintenance_mode")),
                "message": design.get("maintenance_message") or "",
            },
            "locale": {"default": "ar", "rtl": True},
            "push_notifications_enabled": is_flag_enabled(
                "push_notifications_enabled", True
            ),
        }
    )
