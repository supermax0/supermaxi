"""Mobile app design / branding settings (Phase 8)."""
from __future__ import annotations

import re

from extensions import db
from modules.mobile_app.models import MobileAppDesign

_HEX = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def _norm_color(value: str, default: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return default
    if not raw.startswith("#"):
        raw = f"#{raw}"
    if not _HEX.match(raw):
        return default
    return raw.upper().replace("#", "#")


def get_design() -> dict:
    row = MobileAppDesign.query.order_by(MobileAppDesign.id.asc()).first()
    if row is None:
        row = MobileAppDesign()
        db.session.add(row)
        db.session.commit()
    return {
        "app_name": row.app_name,
        "primary_dark": row.primary_dark,
        "surface_dark": row.surface_dark,
        "soft_white": row.soft_white,
        "gold_accent": row.gold_accent,
        "muted_gold": row.muted_gold,
        "logo_url": row.logo_url or "",
        "maintenance_mode": bool(row.maintenance_mode),
        "maintenance_message": row.maintenance_message or "",
    }


def update_design(payload: dict) -> dict:
    row = MobileAppDesign.query.order_by(MobileAppDesign.id.asc()).first()
    if row is None:
        row = MobileAppDesign()
        db.session.add(row)
        db.session.flush()
    if "app_name" in payload and str(payload["app_name"]).strip():
        row.app_name = str(payload["app_name"]).strip()[:120]
    for key, default in (
        ("primary_dark", "#08090C"),
        ("surface_dark", "#111318"),
        ("soft_white", "#F7F6F2"),
        ("gold_accent", "#D9A441"),
        ("muted_gold", "#B9872F"),
    ):
        if key in payload:
            setattr(row, key, _norm_color(str(payload[key]), default))
    if "logo_url" in payload:
        row.logo_url = (str(payload.get("logo_url") or "").strip() or None)
    if "maintenance_mode" in payload:
        row.maintenance_mode = bool(payload["maintenance_mode"])
    if "maintenance_message" in payload:
        row.maintenance_message = (str(payload.get("maintenance_message") or "").strip() or None)
    db.session.commit()
    return get_design()
